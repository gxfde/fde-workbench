"""Local tool-calling loop for direct provider calls.

The MCP gateway already implements every workbench tool server-side
(`mcp_gateway.TOOLS` + `mcp_gateway.call_tool`). Those tools only ever needed
a DSH runtime to *reach* them over HTTP — the implementation itself is a
plain function of (session, user, claims, allowed, name, arguments).

This module closes that gap: when no DSH runtime is deployed, the provider is
called directly and the model's tool calls are executed in-process. The
capability model is unchanged — the same `capabilities_for_level` gate and
the same `call_tool` authorisation path apply, so a direct call can never
reach more data than the MCP route would allow.

AF1 提议档（docs/ai-fde/04 §3.1 C1 已批；11 号 WP1）：只产草稿/校验结果、
零直接副作用的工具（Logic 只读执行、dry-validate 预检、动作提议——runtime
默认 dry-run）也进本循环白名单；执行档（ontology_action_execute / api_execute
/ file_send_wechat）仍排除——真执行必须人工批准，不因循环白名单放宽。
"""
from __future__ import annotations

import json
import logging
from typing import Any

import requests
from sqlalchemy.orm import Session

from fde_api.auth.models import User
from fde_api.control.access import capabilities_for_level, effective_ai_access
from fde_api.control.mcp_gateway import DATA_QUALITY_FEEDBACK_TOOL, TOOLS, call_tool, tool_is_granted
from fde_api.control.payload_audit import MAX_AUDIT_PAYLOAD_BYTES, audit_payload
from fde_api.control.service import ControlServiceError
from fde_api.extensions import db

logger = logging.getLogger(__name__)

# How many times the model may ask for tools before we force an answer.
MAX_TOOL_ROUNDS = 6

__all__ = ["MAX_AUDIT_PAYLOAD_BYTES", "MAX_TOOL_ROUNDS", "direct_tool_completion",
           "tool_definitions"]


def _configured_max_tool_rounds() -> int:
    """AF1-WP1 定参③（docs/ai-fde/09 §1）：轮数走 FDE_AGENT_* 配置族。

    ``agent_max_tool_rounds``（config.py，初值 6 = 历史硬编码值）；无应用
    上下文时回退模块常量，调用方也可用 ``max_tool_rounds`` 参数直传覆盖。
    """
    try:
        from flask import current_app

        settings = current_app.config["SETTINGS"]
    except RuntimeError:
        return MAX_TOOL_ROUNDS
    return int(getattr(settings, "agent_max_tool_rounds", MAX_TOOL_ROUNDS))


# A single tool result may not exceed this many characters when fed back to
# the model; larger results are truncated with an explicit marker so the
# model never silently works off a partial payload.
MAX_TOOL_RESULT_CHARS = 24_000

# Tools that mutate state or leave the machine are not offered to a direct
# provider call: they were designed to run behind the MCP confirmation flow
# (password confirmation, approval records). Offering them here would bypass
# that control. Read-only tools are safe to expose.
READ_ONLY_TOOLS = frozenset({
    "ontology_read",
    "api_catalog",
    "project_list",
    "project_read",
    "quote_list",
    "gates_read",
    "file_search",
    "file_read",
    "system_status",
    "skill_list",
    "skill_read",
    "help_fetch",
    "lcsc_runs_read",
})

# 提议档：草稿/校验类（见模块 docstring AF1 提议档注）。
PROPOSE_TIER_TOOLS = frozenset({
    "ontology_logic_run",
    "ontology_dry_validate",
    "ontology_action_propose",
})
LOOP_TOOL_WHITELIST = READ_ONLY_TOOLS | PROPOSE_TIER_TOOLS | {DATA_QUALITY_FEEDBACK_TOOL}


def _permitted_loop_tools(
    allowed_tools: list[str] | tuple[str, ...] | set[str] | frozenset[str] | None = None,
) -> frozenset[str]:
    """直连循环可暴露的工具面 = 只读面 ∪ 提议档（见模块 docstring AF1 注）。"""
    if allowed_tools is None:
        return LOOP_TOOL_WHITELIST
    return frozenset(name for name in LOOP_TOOL_WHITELIST if name in set(allowed_tools))


def tool_definitions(
    allowed: list[str] | set[str],
    *,
    allowed_tools: list[str] | tuple[str, ...] | set[str] | frozenset[str] | None = None,
    quality_feedback_project_id: str | None = None,
) -> list[dict[str, Any]]:
    """Build the OpenAI-compatible `tools` array for the loop whitelist (read face + propose tier)."""
    permitted_tools = _permitted_loop_tools(allowed_tools)
    claims = {"quality_feedback_project_id": quality_feedback_project_id}
    definitions: list[dict[str, Any]] = []
    for name, entry in TOOLS.items():
        description, _, properties, _, _ = entry
        if name not in permitted_tools or not tool_is_granted(name, allowed, claims):
            continue
        schema: dict[str, Any] = {"type": "object", "properties": properties or {}}
        required = [key for key, value in (properties or {}).items() if isinstance(value, dict) and value.get("required")]
        if name == DATA_QUALITY_FEEDBACK_TOOL:
            schema.update(required=["run_id"], additionalProperties=False)
        elif required:
            schema["required"] = required
        definitions.append({
            "type": "function",
            "function": {"name": name, "description": description, "parameters": schema},
        })
    return definitions


def _claims_for(user: User, *, project_id: str | None, execution_id: str, allowed: list[str]) -> dict[str, Any]:
    return {
        "sub": user.id,
        "ver": user.auth_version,
        "project_id": project_id,
        "execution_id": execution_id,
        "capabilities": allowed,
    }


def _truncate(payload: Any) -> str:
    text = json.dumps(payload, ensure_ascii=False, default=str)
    if len(text) <= MAX_TOOL_RESULT_CHARS:
        return text
    return text[:MAX_TOOL_RESULT_CHARS] + "\n…（工具结果过长，已截断）"


def _run_tools(*, user: User, claims: dict[str, Any], allowed: list[str],
               tool_calls: list[dict[str, Any]], session: Session,
               allowed_tools: list[str] | tuple[str, ...] | set[str] | frozenset[str] | None = None
               ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Execute the requested tools and build the `tool` role messages.

    返回 ``(results, metas)``：metas 与 results 逐位对齐，承载审计载荷
    （AF1-WP4 N1——trace/持久留痕需要 arguments/result/decision；回灌给模型
    的 ``results`` 形状零变化）。
    """
    permitted_tools = _permitted_loop_tools(allowed_tools)
    results: list[dict[str, Any]] = []
    metas: list[dict[str, Any]] = []
    for call in tool_calls:
        function = call.get("function") or {}
        name = function.get("name")
        raw_arguments = function.get("arguments")
        try:
            arguments = json.loads(raw_arguments) if isinstance(raw_arguments, str) else (raw_arguments or {})
        except ValueError:
            arguments = {}
        if not isinstance(arguments, dict):
            arguments = {}
        if not isinstance(name, str) or name not in permitted_tools:
            content = json.dumps(
                {"error": "forbidden", "message": "直连只读循环不允许调用写类或未授权工具。"},
                ensure_ascii=False,
            )
            results.append({"role": "tool", "tool_call_id": call.get("id", ""), "name": name, "content": content})
            # 闭集外工具的载荷照旧留痕（N1：越权反查要连载荷可回查）
            metas.append({"name": name, "decision": "denied", "arguments": arguments, "result": content})
            continue
        try:
            value = call_tool(session, user=user, claims=claims, allowed=allowed,
                              name=name, arguments=arguments)
            content = _truncate(value)
        except ControlServiceError as error:
            # A refused tool must be reported back to the model as data, not
            # as a crash: the model can then explain the refusal to the user.
            content = json.dumps({"error": error.code, "message": error.message}, ensure_ascii=False)
            # N1（评审 edge-case）：拒执腿的 metas 不得落公共 allowed 路径——
            # 能力拒绝照 denied 留痕（决策错标即审计失真），载荷照旧留痕。
            results.append({"role": "tool", "tool_call_id": call.get("id", ""), "name": name, "content": content})
            metas.append({"name": name, "decision": "denied", "arguments": arguments, "result": content})
            continue
        except Exception as error:  # noqa: BLE001 - a tool failure must not kill the turn
            logger.warning("Direct tool call failed tool=%s error_type=%s", name, type(error).__name__)
            # A crashed tool may leave this shared session holding an aborted
            # transaction with open row locks (e.g. a FOR UPDATE that died on
            # a dropped DB connection). Roll back so the locks release
            # immediately and the next provider round starts clean — idling
            # the session in that state blocks every other caller wanting
            # the same rows.
            session.rollback()
            content = json.dumps({"error": "tool_failed", "message": "工具执行失败。"}, ensure_ascii=False)
        results.append({"role": "tool", "tool_call_id": call.get("id", ""), "name": name, "content": content})
        metas.append({"name": name, "decision": "allowed", "arguments": arguments, "result": content})
    return results, metas


def _force_final_answer(*, http, headers: dict[str, str], base_url: str, model_name: str,
                        messages: list[dict[str, Any]], max_tokens: int,
                        timeout_seconds: int, private_context: bool) -> tuple[str, dict[str, Any] | None]:
    """Ask the model for a final answer with the tools withdrawn.

    Used when the tool-round budget is spent: the model is mid-thought and
    would otherwise return "let me check" as its answer. Dropping the tools
    and asking for the conclusion makes it commit. A failed final call is not
    fatal — the caller keeps the previous content.
    """
    conversation = list(messages)
    conversation.append({
        "role": "user",
        "content": "不要再调用工具。请根据上面的查询结果，直接给出最终答案。",
    })
    from fde_api.control.ai_server_client import _reject_private_redirect

    try:
        response = http.post(f"{base_url}/chat/completions", headers=headers,
                             json={"model": model_name, "messages": conversation,
                                   "max_tokens": max_tokens},
                             timeout=timeout_seconds, allow_redirects=not private_context)
    except (requests.Timeout, requests.RequestException):
        return "", None
    if private_context:
        _reject_private_redirect(response)
    if response.status_code >= 400:
        return "", None
    try:
        payload = response.json()
    except ValueError:
        return "", None
    choice = (payload.get("choices") or [{}])[0]
    content = (choice.get("message") or {}).get("content")
    text = content if isinstance(content, str) else ""
    usage = payload.get("usage")
    usage_entry = None
    if isinstance(usage, dict):
        usage_entry = {
            "model": model_name,
            "input_tokens": int(usage.get("prompt_tokens") or 0),
            "output_tokens": int(usage.get("completion_tokens") or 0),
            "cache_read_tokens": 0,
            "cache_write_tokens": 0,
        }
    return text, usage_entry


def direct_tool_completion(
    *,
    model: dict[str, Any],
    prompt: str,
    user: User,
    project_id: str | None,
    execution_id: str,
    system_prompt: str | None = None,
    max_tokens: int = 16384,
    timeout_seconds: int = 300,
    max_tool_rounds: int | None = None,
    session: Any | None = None,
    capabilities: list[str] | tuple[str, ...] | None = None,
    allowed_tools: list[str] | tuple[str, ...] | set[str] | frozenset[str] | None = None,
    grant_quality_feedback: bool = False,
    private_context: bool = False,
) -> tuple[str, dict[str, Any], list[dict[str, Any]]]:
    """Call the provider with tools and run the tool loop locally.

    Returns (text, provider_usage, tool_trace). The trace records which tools
    ran so the caller can show the user what actually looked up — the
    direct path has no DSH execution timeline to borrow.

    V31-P1：输出预算**不加码**（与 ``direct_provider_completion`` 同款）——
    实测推理模型的思考长度随授予预算增长，加码只会更慢更易触顶（见
    ``ai_server_client`` 文件头注释）。
    """
    from fde_api.control.ai_server_client import _reasoning_extra_pattern, _reject_private_redirect, effective_max_tokens
    from fde_api.control.dsh_runtime import DSHRuntimeError

    base_url = str(model.get("base_url") or "").rstrip("/")
    model_name = str(model.get("model") or "")
    api_key = model.get("api_key")
    if not base_url or not model_name or not api_key:
        raise DSHRuntimeError("ai_model_not_configured", "尚未配置可直连的模型。", retryable=False)

    max_tokens = effective_max_tokens(model_name, max_tokens, _reasoning_extra_pattern())

    level, _ = effective_ai_access(user)
    allowed = capabilities_for_level(level)
    if capabilities is not None:
        requested = {str(item) for item in capabilities}
        allowed = [item for item in allowed if item in requested]
    quality_feedback_project_id = project_id if grant_quality_feedback else None
    definitions = tool_definitions(
        allowed, allowed_tools=allowed_tools, quality_feedback_project_id=quality_feedback_project_id,
    )
    # Every later request replays this turn, including any quality tool result.
    private_context = private_context or any(
        item["function"]["name"] == DATA_QUALITY_FEEDBACK_TOOL for item in definitions
    )
    claims = _claims_for(user, project_id=project_id, execution_id=execution_id, allowed=allowed)
    if quality_feedback_project_id:
        claims["quality_feedback_project_id"] = quality_feedback_project_id

    messages: list[dict[str, Any]] = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})

    http = session or requests.Session()
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    usage_calls: list[dict[str, Any]] = []
    trace: list[dict[str, Any]] = []
    text = ""

    if max_tool_rounds is not None:
        rounds_limit = int(max_tool_rounds)
    else:
        rounds_limit = _configured_max_tool_rounds()
    if rounds_limit < 1:
        raise ValueError("max_tool_rounds must be >= 1")

    with db.session() as db_session:
        for round_index in range(rounds_limit + 1):
            body: dict[str, Any] = {
                "model": model_name,
                "messages": messages,
                "max_tokens": max_tokens,
            }
            if definitions:
                body["tools"] = definitions
                body["tool_choice"] = "auto"
            try:
                response = http.post(f"{base_url}/chat/completions", headers=headers,
                                     json=body, timeout=timeout_seconds,
                                     allow_redirects=not private_context)
            except requests.Timeout as error:
                raise DSHRuntimeError("ai_timeout", "AI 请求超时，请稍后重试。", retryable=True) from error
            except requests.RequestException as error:
                raise DSHRuntimeError("ai_unavailable", "暂时无法连接 AI 服务。", retryable=True) from error

            if private_context:
                _reject_private_redirect(response)
            if response.status_code == 429:
                raise DSHRuntimeError("ai_rate_limited", "AI 服务额度或频率受限，请稍后重试。", retryable=True)
            if response.status_code in (401, 403):
                raise DSHRuntimeError("ai_authentication_failed", "AI 服务认证失败，请检查 API Key。", retryable=False)
            if response.status_code >= 400:
                raise DSHRuntimeError("ai_unavailable", "AI 服务返回错误，请稍后重试。",
                                      retryable=response.status_code >= 500)
            try:
                payload = response.json()
            except ValueError as error:
                raise DSHRuntimeError("ai_output_invalid", "AI 服务未返回有效结果。", retryable=True) from error

            choice = (payload.get("choices") or [{}])[0]
            message = choice.get("message") or {}
            content = message.get("content")
            tool_calls = message.get("tool_calls") or []
            usage = payload.get("usage")
            if isinstance(usage, dict):
                usage_calls.append({
                    "model": model_name,
                    "input_tokens": int(usage.get("prompt_tokens") or 0),
                    "output_tokens": int(usage.get("completion_tokens") or 0),
                    "cache_read_tokens": 0,
                    "cache_write_tokens": 0,
                })

            if not tool_calls:
                text = content if isinstance(content, str) else ""
                if not text.strip():
                    text = "AI 服务未返回有效结果。"
                break

            if round_index >= rounds_limit:
                # The round budget is spent, but the model answered with a
                # mid-thought sentence ("Let me look that up") instead of a
                # result. Ask once more with the tools withdrawn so it must
                # commit to an answer instead of announcing the next lookup.
                final_text, final_usage = _force_final_answer(
                    http=http, headers=headers, base_url=base_url, model_name=model_name,
                    messages=messages, max_tokens=max_tokens, timeout_seconds=timeout_seconds,
                    private_context=private_context)
                if final_usage:
                    usage_calls.append(final_usage)
                # If the forced call failed or came back empty, keep the
                # model's last content rather than answering with nothing.
                text = final_text.strip() or (content if isinstance(content, str) else "")
                if not text.strip():
                    text = "AI 服务未返回有效结果。"
                break

            messages.append({"role": "assistant", "content": content or "",
                             "tool_calls": tool_calls})
            results, tool_metas = _run_tools(user=user, claims=claims, allowed=allowed,
                                             tool_calls=tool_calls, session=db_session,
                                             allowed_tools=allowed_tools)
            # Close the transaction this tool round may have opened: the next
            # provider call (up to `timeout_seconds`, zero DB traffic) must not
            # overlap a connection that sits idle-in-transaction while still
            # holding the tool round's row locks. Loop-whitelist tools write
            # nothing to this database — the read face is read-only and the
            # propose tier's drafts live in ontology-service, not here (AF1
            # 提议档，docs/ai-fde/04 §3.1) — so rolling back loses nothing.
            db_session.rollback()
            for call, result, meta in zip(tool_calls, results, tool_metas):
                # AF1-WP4 N1（挂账「直连循环持久审计留痕」的数据面前提）：
                # trace 项带载荷摘要——automation output 留痕随之携带载荷；
                # 判定语义零变化（载荷为附加留痕，截断失败＝None）。
                arguments_text, _cut = audit_payload(meta["arguments"])
                result_text, _cut = audit_payload(meta["result"])
                trace.append({
                    "tool": result.get("name"),
                    "ok": not str(result.get("content", "")).startswith('{"error"'),
                    "decision": meta["decision"],
                    "arguments": arguments_text,
                    "result": result_text,
                })
            messages.extend(results)

    usage_payload = {"complete": bool(usage_calls), "calls": usage_calls}
    return text, usage_payload, trace
