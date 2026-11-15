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
"""
from __future__ import annotations

import json
import logging
from typing import Any

import requests
from sqlalchemy.orm import Session

from fde_api.auth.models import User
from fde_api.control.access import capabilities_for_level, effective_ai_access
from fde_api.control.mcp_gateway import TOOLS, call_tool
from fde_api.control.service import ControlServiceError
from fde_api.extensions import db

logger = logging.getLogger(__name__)

# How many times the model may ask for tools before we force an answer.
MAX_TOOL_ROUNDS = 6
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


def _permitted_read_only_tools(
    allowed_tools: list[str] | tuple[str, ...] | set[str] | frozenset[str] | None = None,
) -> frozenset[str]:
    if allowed_tools is None:
        return READ_ONLY_TOOLS
    return frozenset(name for name in READ_ONLY_TOOLS if name in set(allowed_tools))


def tool_definitions(
    allowed: list[str] | set[str],
    *,
    allowed_tools: list[str] | tuple[str, ...] | set[str] | frozenset[str] | None = None,
) -> list[dict[str, Any]]:
    """Build the OpenAI-compatible `tools` array for the readable tools."""
    permitted_tools = _permitted_read_only_tools(allowed_tools)
    definitions: list[dict[str, Any]] = []
    for name, entry in TOOLS.items():
        description, capability, properties, _, _ = entry
        if name not in permitted_tools:
            continue
        if capability and capability not in allowed:
            continue
        schema: dict[str, Any] = {"type": "object", "properties": properties or {}}
        required = [key for key, value in (properties or {}).items() if isinstance(value, dict) and value.get("required")]
        if required:
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
               allowed_tools: list[str] | tuple[str, ...] | set[str] | frozenset[str] | None = None) -> list[dict[str, Any]]:
    """Execute the requested tools and build the `tool` role messages."""
    permitted_tools = _permitted_read_only_tools(allowed_tools)
    results: list[dict[str, Any]] = []
    for call in tool_calls:
        function = call.get("function") or {}
        name = function.get("name")
        if not isinstance(name, str) or name not in permitted_tools:
            content = json.dumps(
                {"error": "forbidden", "message": "直连只读循环不允许调用写类或未授权工具。"},
                ensure_ascii=False,
            )
            results.append({"role": "tool", "tool_call_id": call.get("id", ""), "name": name, "content": content})
            continue
        raw_arguments = function.get("arguments")
        try:
            arguments = json.loads(raw_arguments) if isinstance(raw_arguments, str) else (raw_arguments or {})
        except ValueError:
            arguments = {}
        if not isinstance(arguments, dict):
            arguments = {}
        try:
            value = call_tool(session, user=user, claims=claims, allowed=allowed,
                              name=name, arguments=arguments)
            content = _truncate(value)
        except ControlServiceError as error:
            # A refused tool must be reported back to the model as data, not
            # as a crash: the model can then explain the refusal to the user.
            content = json.dumps({"error": error.code, "message": error.message}, ensure_ascii=False)
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
    return results


def _force_final_answer(*, http, headers: dict[str, str], base_url: str, model_name: str,
                        messages: list[dict[str, Any]], max_tokens: int,
                        timeout_seconds: int) -> tuple[str, dict[str, Any] | None]:
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
    try:
        response = http.post(f"{base_url}/chat/completions", headers=headers,
                             json={"model": model_name, "messages": conversation,
                                   "max_tokens": max_tokens},
                             timeout=timeout_seconds)
    except (requests.Timeout, requests.RequestException):
        return "", None
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
    session: Any | None = None,
    capabilities: list[str] | tuple[str, ...] | None = None,
    allowed_tools: list[str] | tuple[str, ...] | set[str] | frozenset[str] | None = None,
) -> tuple[str, dict[str, Any], list[dict[str, Any]]]:
    """Call the provider with tools and run the tool loop locally.

    Returns (text, provider_usage, tool_trace). The trace records which tools
    ran so the caller can show the user what actually looked up — the
    direct path has no DSH execution timeline to borrow.

    V31-P1：输出预算**不加码**（与 ``direct_provider_completion`` 同款）——
    实测推理模型的思考长度随授予预算增长，加码只会更慢更易触顶（见
    ``ai_server_client`` 文件头注释）。
    """
    from fde_api.control.ai_server_client import effective_max_tokens, _reasoning_extra_pattern
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
    definitions = tool_definitions(allowed, allowed_tools=allowed_tools)
    claims = _claims_for(user, project_id=project_id, execution_id=execution_id, allowed=allowed)

    messages: list[dict[str, Any]] = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})

    http = session or requests.Session()
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    usage_calls: list[dict[str, Any]] = []
    trace: list[dict[str, Any]] = []
    text = ""

    with db.session() as db_session:
        for round_index in range(MAX_TOOL_ROUNDS + 1):
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
                                     json=body, timeout=timeout_seconds)
            except requests.Timeout as error:
                raise DSHRuntimeError("ai_timeout", "AI 请求超时，请稍后重试。", retryable=True) from error
            except requests.RequestException as error:
                raise DSHRuntimeError("ai_unavailable", "暂时无法连接 AI 服务。", retryable=True) from error

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

            if round_index >= MAX_TOOL_ROUNDS:
                # The round budget is spent, but the model answered with a
                # mid-thought sentence ("Let me look that up") instead of a
                # result. Ask once more with the tools withdrawn so it must
                # commit to an answer instead of announcing the next lookup.
                final_text, final_usage = _force_final_answer(
                    http=http, headers=headers, base_url=base_url, model_name=model_name,
                    messages=messages, max_tokens=max_tokens, timeout_seconds=timeout_seconds)
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
            results = _run_tools(user=user, claims=claims, allowed=allowed,
                                  tool_calls=tool_calls, session=db_session,
                                  allowed_tools=allowed_tools)
            # Close the transaction this tool round may have opened: the next
            # provider call (up to `timeout_seconds`, zero DB traffic) must not
            # overlap a connection that sits idle-in-transaction while still
            # holding the tool round's row locks. Direct-loop tools are
            # read-only, so rolling back loses nothing.
            db_session.rollback()
            for call, result in zip(tool_calls, results):
                trace.append({
                    "tool": result.get("name"),
                    "ok": not str(result.get("content", "")).startswith('{"error"'),
                })
            messages.extend(results)

    usage_payload = {"complete": bool(usage_calls), "calls": usage_calls}
    return text, usage_payload, trace
