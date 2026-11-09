"""Shared AI Server entry point for chat and existing structured AI workflows."""
from __future__ import annotations

import json
import logging
import re
import time
from contextvars import ContextVar
from typing import Any
from uuid import uuid4

import requests
from flask import current_app, g, has_request_context
from sqlalchemy import select

from fde_api.auth.models import User
from fde_api.control.dsh_runtime import DSHRuntimeError, dsh_runtime
from fde_api.control.mcp_gateway import issue_mcp_token
from fde_api.control.model_preferences import resolve_model_preference
from fde_api.extensions import db

logger = logging.getLogger(__name__)

# DSH 运行时不可用时，可以降级为「直连供应商」的故障码。
# 直连路径不需要 DSH 服务、不签发 MCP token，因此工具能力不可用，
# 但对话本身仍可继续 —— 否则在没有部署 DSH 的环境里 AI 完全没有出路。
# dsh_execution_conflict 不在列：那是幂等冲突，降级会导致同一次执行跑两遍。
DEGRADABLE_DSH_CODES = frozenset({
    "dsh_not_enabled",
    "dsh_not_configured",
    "dsh_unavailable",
    "dsh_authentication_failed",
    "dsh_timeout",
})

# V31-P1（somwyn 试点偏离）——实测定案（2026-11-09，MiniMax-M3.1-Flash）：
#
# 1. 推理模型的 ``reasoning_content`` 与 ``content`` **共享** max_tokens，
#    且**思考长度随授予预算增长**：授予 16,384 时思考 ~11–15k tokens；授予
#    32,768 时思考同步变长，同一篇 10K 字符纪要 **>900s 未返回**（超时）。
# 2. 供应商 completion 有**硬顶**（MiniMax-M3.1-Flash = 16,384 tokens）：
#    请求超过硬顶换不来更多正文——输出到顶即被截断（JSON 断在半路）。
#
# 结论：「给推理模型 ×2 预留预算」是**错的**（V31-P1 初版即此错，实弹证伪：
# 预留后既没成功还更快超时）。正确解法是把活拆小——大纪要**分段抽取**
# （``discovery/chunking.py``），单批输出落在硬顶内再合并。
#
# 本模块保留推理模型识别，只用于**截断诊断措辞**与部署扩展
# （``FDE_AI_REASONING_MODEL_PATTERN``（Python 正则）作为**额外**分支并入）：
# 命中推理特征 → 提示「思考吃掉了预算」（处置=精简输入/换非推理模型/分段）；
# 未命中 → 提示「输出触达预算上限」（处置=精简输入/分段）。
REASONING_MODEL_PATTERN = re.compile(
    r"(?i)(minimax-m\d|deepseek-(?:reasoner|r\d)|qwq|reasoner|-thinking|\bo[134](?![\w.]))"
)


def _reasoning_extra_pattern() -> str | None:
    """读部署扩展的推理模型特征（无 app 上下文/未配置返回 None，误配忽略）。"""
    try:
        extra = str(current_app.config["SETTINGS"].ai_reasoning_model_pattern or "")
    except RuntimeError:  # 无 Flask app 上下文（单元测试直调等）
        return None
    return extra or None


def is_reasoning_model(model_name: str, extra_pattern: str | None = None) -> bool:
    """模型名是否命中推理特征（内置特征 ∪ 部署扩展正则，坏正则忽略并告警）。"""
    if not model_name:
        return False
    patterns: list[re.Pattern[str]] = [REASONING_MODEL_PATTERN]
    if extra_pattern:
        try:
            patterns.append(re.compile(extra_pattern, re.IGNORECASE))
        except re.error:
            logger.warning("invalid ai_reasoning_model_pattern, ignored: %r", extra_pattern)
    return any(pattern.search(model_name) for pattern in patterns)


def effective_max_tokens(model_name: str, requested: int, extra_pattern: str | None = None) -> int:
    """直连腿输出预算：**原样使用调用方给的预算，不对推理模型加码**。

    V31-P1 初版在此对推理模型 ×2 预留——实弹证伪（见文件头注释）：思考长度
    随授予预算增长，×2 只让模型想更久（32,768 预算实测 >900s 超时），
    供应商 completion 硬顶（16,384）也不会因请求更大而放宽。
    保留本函数（而非直接删）为的是把「不加码」这条实证结论钉在代码里，
    防止后人照旧例加回预留；``model_name``/``extra_pattern`` 形参保留只为
    未来出现**有依据**的预算策略时不必改调用点。
    """
    return requested


def _reasoning_tokens_from_usage(payload: dict[str, Any]) -> int | None:
    """从 OpenAI 兼容 usage 块提取 reasoning tokens（无该明细返回 None，不发明数字）。"""
    usage = payload.get("usage")
    if not isinstance(usage, dict):
        return None
    details = usage.get("completion_tokens_details")
    if not isinstance(details, dict):
        return None
    try:
        value = int(details.get("reasoning_tokens") or 0)
    except (TypeError, ValueError):
        return None
    return value or None


def _completion_tokens_from_usage(payload: dict[str, Any]) -> int | None:
    """从 OpenAI 兼容 usage 块提取 completion tokens（无该块返回 None）。"""
    usage = payload.get("usage")
    if not isinstance(usage, dict):
        return None
    try:
        value = int(usage.get("completion_tokens") or 0)
    except (TypeError, ValueError):
        return None
    return value


def _provider_usage_from_response(payload: dict[str, Any], model_name: str) -> dict[str, Any]:
    """Map an OpenAI-compatible usage block onto the DSH usage shape."""
    usage = payload.get("usage")
    if not isinstance(usage, dict):
        return {"complete": False, "calls": []}
    try:
        input_tokens = int(usage.get("prompt_tokens") or 0)
        output_tokens = int(usage.get("completion_tokens") or 0)
    except (TypeError, ValueError):
        return {"complete": False, "calls": []}
    return {
        "complete": True,
        "calls": [{
            "model": model_name,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cache_read_tokens": 0,
            "cache_write_tokens": 0,
        }],
    }


def _sum_provider_usage_tokens(usage: dict[str, Any] | None) -> tuple[int | None, int | None]:
    """把 DSH usage shape（``calls[]`` 聚合）折算成 input/output token 总量。

    无 calls（``complete=False`` 或缺块）返回 (None, None)——账本记元数据，
    预算按可测口径汇总，不发明数字。
    """
    calls = (usage or {}).get("calls")
    if not isinstance(calls, list) or not calls:
        return None, None
    input_total = 0
    output_total = 0
    for call in calls:
        if not isinstance(call, dict):
            continue
        try:
            input_total += int(call.get("input_tokens") or 0)
            output_total += int(call.get("output_tokens") or 0)
        except (TypeError, ValueError):
            continue
    return input_total, output_total


def _audit_execution(*, request_id: str, actor_id: str | None, purpose: str,
                     model: str, used_fallback: bool, duration_ms: int,
                     usage: dict[str, Any] | None, status: str, error_code: str | None,
                     prompt_version: str | None = None,
                     prompt_fingerprint: str | None = None) -> None:
    """CR-006 统一记账腿：DSH 主路径/降级直连路径统一落 ``ai_call_audits``（E7）。

    此前这两条路径零记账——``dsh_enabled=true`` 时平台月度预算对 skill 节点/
    聊天/结构化调用恒失效（goal-c CR-006）。尽力而为：审计自身失败不打断业务。
    """
    try:
        from fde_api.ai.auditing import record_audit

        input_tokens, output_tokens = _sum_provider_usage_tokens(usage)
        record_audit(
            request_id=request_id,
            actor_id=actor_id,
            purpose=purpose,
            model=model,
            used_fallback=used_fallback,
            duration_ms=int(duration_ms),
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            status=status,
            error_code=error_code,
            prompt_version=prompt_version,
            prompt_fingerprint=prompt_fingerprint,
        )
    except Exception:  # noqa: BLE001 - 审计失败不阻塞业务
        logger.warning("AI execution audit dispatch failed request_id=%s", request_id, exc_info=True)


def direct_provider_completion(
    *,
    model: dict[str, Any],
    prompt: str,
    system_prompt: str | None = None,
    max_tokens: int = 16384,
    timeout_seconds: int = 300,
    session: Any | None = None,
) -> tuple[str, dict[str, Any]]:
    """Call an OpenAI-compatible provider directly, without the DSH runtime.

    Used as the degraded path when no DSH runtime is deployed. The model
    descriptor must carry base_url / api_key / model — every producer of
    that dict (model preferences, system default, structured overrides)
    already does.

    V31-P1：截断识别与诚实报错。截断有两条证据——供应商回报
    ``finish_reason == "length"``，或输出 token 数**触达请求预算**（模型
    自然收尾时必小于预算：实测正常样本 15,834 < 16,384）。命中且正文缺失
    时报 ``ai_output_truncated``（含处置指引）而非笼统 ``ai_output_invalid``；
    正文非空但被截断时把证据写进 usage 供消费方判读。
    """
    base_url = str(model.get("base_url") or "").rstrip("/")
    model_name = str(model.get("model") or "")
    api_key = model.get("api_key")
    if not base_url or not model_name:
        raise DSHRuntimeError("ai_model_not_configured", "尚未配置可直连的模型。", retryable=False)
    if not api_key:
        raise DSHRuntimeError("ai_model_not_configured", "尚未配置可直连的模型 API Key。", retryable=False)

    # 预算原样使用（推理模型不加码——实证见文件头注释）。
    max_tokens = effective_max_tokens(model_name, max_tokens, _reasoning_extra_pattern())

    messages: list[dict[str, str]] = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})

    http = session or requests.Session()
    try:
        response = http.post(
            f"{base_url}/chat/completions",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={"model": model_name, "messages": messages, "max_tokens": max_tokens},
            timeout=timeout_seconds,
        )
    except requests.Timeout as error:
        raise DSHRuntimeError("ai_timeout", "AI 请求超时，请稍后重试。", retryable=True) from error
    except requests.RequestException as error:
        raise DSHRuntimeError("ai_unavailable", "暂时无法连接 AI 服务。", retryable=True) from error

    if response.status_code == 429:
        raise DSHRuntimeError("ai_rate_limited", "AI 服务额度或频率受限，请稍后重试。", retryable=True)
    if response.status_code in (401, 403):
        raise DSHRuntimeError("ai_authentication_failed", "AI 服务认证失败，请检查 API Key。", retryable=False)
    if response.status_code >= 400:
        raise DSHRuntimeError(
            "ai_unavailable", "AI 服务返回错误，请稍后重试。", retryable=response.status_code >= 500)

    try:
        payload = response.json()
    except ValueError as error:
        raise DSHRuntimeError("ai_output_invalid", "AI 服务未返回有效结果。", retryable=True) from error
    if not isinstance(payload, dict):
        raise DSHRuntimeError("ai_output_invalid", "AI 服务未返回有效结果。", retryable=True)
    choices = payload.get("choices")
    choice = choices[0] if isinstance(choices, list) and choices else None
    message = choice.get("message") if isinstance(choice, dict) else None
    if not isinstance(message, dict):
        raise DSHRuntimeError("ai_output_invalid", "AI 服务未返回有效结果。", retryable=True)
    # content 键缺失与显式 null 同视（截断场景部分供应商省略键）
    text = message.get("content")
    finish_reason = choice.get("finish_reason") if isinstance(choice, dict) else None
    reasoning_tokens = _reasoning_tokens_from_usage(payload)
    completion_tokens = _completion_tokens_from_usage(payload)
    # 截断证据：供应商明说 length，或输出 token 触达请求预算（到顶即被截断）。
    truncated = finish_reason == "length" or (
        completion_tokens is not None and max_tokens > 0 and completion_tokens >= max_tokens
    )
    if not isinstance(text, str) or not text.strip():
        if truncated:
            # V31-P1：输出预算被思考吃满、正文零产出——诚实报错并给处置指引，
            # 不再伪装成「格式不正确」的 ai_output_invalid（试点的真实痛点：
            # 两次重试同样必败，白烧两轮推理费用）。不可重试：同输入重放同败。
            if is_reasoning_model(model_name, _reasoning_extra_pattern()):
                detail = f"（模型报告 reasoning {reasoning_tokens} tokens）" if reasoning_tokens else ""
                advice = "推理模型把输出预算用在了思考上，正文未产出" + detail
                remedy = "请把长纪要分段抽取（或先人工整理精简）或更换非推理模型后重试"
            else:
                advice = "输出触达预算上限被截断，正文未产出"
                remedy = "请把输入分段抽取（或先人工整理精简）后重试"
            raise DSHRuntimeError(
                "ai_output_truncated",
                advice + "。" + remedy + "。",
                retryable=False)
        raise DSHRuntimeError("ai_output_invalid", "AI 服务未返回有效结果。", retryable=True)
    usage = _provider_usage_from_response(payload, model_name)
    if truncated:
        # 正文非空但被截断：返回内容（对话场景可用），但把截断证据写进
        # usage（结构化消费方解析失败时可据此给出同款诊断，审计可查）。
        for call in usage.get("calls", []) if isinstance(usage, dict) else []:
            call["truncated"] = True
            if finish_reason is not None:
                call["finish_reason"] = finish_reason
            if reasoning_tokens is not None:
                call["reasoning_tokens"] = reasoning_tokens
    return text, usage


ai_actor_id: ContextVar[str | None] = ContextVar("ai_actor_id", default=None)


def apply_runtime_plugin(*, action, plugin):
    from fde_api.control.service import ControlServiceError
    runtime = dsh_runtime.current.primary
    response = runtime._request("POST", "/v1/plugins/apply", json={"action": action, "plugin": plugin}, timeout=300)
    payload = runtime._json_object(response)
    if response.status_code >= 400:
        raise ControlServiceError(payload.get("error", "plugin_execution_failed"), payload.get("message", "AI Server 插件变更失败。"), response.status_code)
    return payload


def execute_ai_prompt(*, user_id: str, prompt: str, execution_id: str | None = None,
                      project_id: str | None = None, preference_id: str | None = None,
                      use_tools: bool = True, system_prompt: str | None = None,
                      max_tokens: int = 16384, model_override: dict | None = None,
                      capabilities: list[str] | None = None, deep_thinking: bool | None = None, all_projects: bool = False,
                      return_metadata: bool = False, purpose: str,
                      prompt_version: str | None = None) -> str | dict:
    identifier = execution_id or str(uuid4())
    # N2 仪表化（G-09）：指纹＝指令源文本 sha256（system_prompt 优先，否则
    # prompt 本身）；提示词正文绝不落库。模板身份 → 输出可按模板归因。
    from fde_api.ai.auditing import compute_prompt_fingerprint

    fingerprint = compute_prompt_fingerprint(system_prompt=system_prompt, prompt=prompt)
    settings = current_app.config["SETTINGS"]
    runtime = dsh_runtime.current.primary
    dsh_usable = runtime.enabled
    started = time.monotonic()
    with db.session() as session:
        user = session.get(User, user_id)
        if user is None or not user.is_active:
            raise DSHRuntimeError("ai_access_denied", "账号已停用。", retryable=False)
        from fde_api.control.access import effective_ai_access
        level, _ = effective_ai_access(user)
        if level == "disabled":
            raise DSHRuntimeError("ai_access_denied", "管理员尚未为此账号开放 AI 权限。", retryable=False)
        model = model_override or resolve_model_preference(session, user_id, preference_id)
        if deep_thinking and model.get("provider") not in {"deepseek", "deepseek-official"}:
            from fde_api.control.service import ControlServiceError
            raise ControlServiceError("thinking_unsupported", "当前模型暂不支持手动深度思考，请关闭开关或选择 DeepSeek 模型。", 400)
        use_tools = use_tools and model.get("supports_tools", True)
        # CR-006 统一预算门：``ai_monthly_token_budget`` 超限即拒，且不发起
        # 任何 DSH/供应商请求。与 deepseek 直连腿同语义（预算 0=不限额；设施
        # 故障 fail-open）。此门带显式 user_id——后台任务（workflow skill
        # 节点等无请求上下文场景）同样生效，补齐 deepseek 门依赖 flask g 的
        # 后台盲区。先判门再签 MCP token：拦截路径零写副作用。
        budget_blocked = False
        try:
            from fde_api.ai.auditing import budget_exceeded

            budget_blocked = budget_exceeded(session, user_id, int(settings.ai_monthly_token_budget or 0))
        except Exception:  # noqa: BLE001 - 预算设施故障不阻塞业务（fail-open）
            logger.warning("AI budget gate failed open execution_id=%s", identifier, exc_info=True)
        # 工具只能经由 DSH 转发；没有可用运行时时不签发 MCP token。
        token = None if budget_blocked else (issue_mcp_token(user, project_id=None if all_projects else project_id, capabilities=capabilities, execution_id=identifier) if (use_tools and dsh_usable) else None)
    if budget_blocked:
        from fde_api.ai.auditing import audit_budget_blocked

        audit_budget_blocked(request_id=identifier, actor_id=user_id, purpose=purpose,
                             model=str(model.get("model") or ""),
                             prompt_version=prompt_version, prompt_fingerprint=fingerprint)
        raise DSHRuntimeError("ai_budget_exceeded", "本月 AI 用量已达预算上限，请联系管理员调整或下月再试。", retryable=False)
    if not dsh_usable:
        # 没有部署 DSH 运行时：直接走供应商直连降级路径（带本地工具循环）。
        return _degraded_direct_result(
            model=model, prompt=prompt, system_prompt=system_prompt,
            max_tokens=max_tokens, timeout_seconds=settings.dsh_timeout_seconds,
            reason="dsh_not_enabled", return_metadata=return_metadata,
            user_id=user_id, project_id=project_id, execution_id=identifier,
            use_tools=use_tools, purpose=purpose,
            prompt_version=prompt_version, prompt_fingerprint=fingerprint)
    body = {"schema_version": "fde-dsh-v1", "execution_id": identifier,
            "actor": {"user_id": user_id}, "scope": {"project_id": project_id},
            "agent_profile": "fde-assistant" if use_tools else "fde-structured",
            "prompt": prompt, "model_config": model, "max_tokens": max_tokens}
    if deep_thinking is not None:
        body["deep_thinking"] = deep_thinking
    if token:
        body["mcp"] = {"url": settings.ai_internal_api_url.rstrip("/") + "/api/v1/internal/ai/mcp", "token": token}
    if system_prompt:
        body["system_prompt"] = system_prompt
    elapsed_ms = int((time.monotonic() - started) * 1000)
    try:
        response = runtime._request("POST", "/v1/executions", json=body, timeout=settings.dsh_timeout_seconds,
                                    headers={"Idempotency-Key": identifier})
    except DSHRuntimeError as error:
        if error.code not in DEGRADABLE_DSH_CODES:
            _audit_execution(request_id=identifier, actor_id=user_id, purpose=purpose,
                             model=str(model.get("model") or ""), used_fallback=False,
                             duration_ms=elapsed_ms, usage=None, status="failed", error_code=error.code,
                             prompt_version=prompt_version,
                             prompt_fingerprint=fingerprint)
            raise
        logger.warning("DSH runtime unusable, degrading to direct provider call code=%s", error.code)
        return _degraded_direct_result(
            model=model, prompt=prompt, system_prompt=system_prompt,
            max_tokens=max_tokens, timeout_seconds=settings.dsh_timeout_seconds,
            reason=error.code, return_metadata=return_metadata,
            user_id=user_id, project_id=project_id, execution_id=identifier,
            use_tools=use_tools, purpose=purpose,
            prompt_version=prompt_version, prompt_fingerprint=fingerprint)
    if response.status_code >= 400:
        service_error = runtime._service_error(response.status_code)
        _audit_execution(request_id=identifier, actor_id=user_id, purpose=purpose,
                         model=str(model.get("model") or ""), used_fallback=False,
                         duration_ms=int((time.monotonic() - started) * 1000), usage=None,
                         status="failed", error_code=service_error.code,
                         prompt_version=prompt_version,
                         prompt_fingerprint=fingerprint)
        raise service_error
    result = runtime._json_object(response)
    text = result.get("output", {}).get("text")
    if result.get("status") != "succeeded" or not isinstance(text, str) or not text.strip():
        _audit_execution(request_id=identifier, actor_id=user_id, purpose=purpose,
                         model=str(model.get("model") or ""), used_fallback=False,
                         duration_ms=int((time.monotonic() - started) * 1000), usage=None,
                         status="failed", error_code="ai_output_invalid",
                         prompt_version=prompt_version,
                         prompt_fingerprint=fingerprint)
        raise DSHRuntimeError("ai_output_invalid", "AI Server 未返回有效结果。", retryable=True)
    provider_usage = result.get("provider_usage") or {"complete": False, "calls": []}
    _audit_execution(request_id=identifier, actor_id=user_id, purpose=purpose,
                     model=str(model.get("model") or ""), used_fallback=False,
                     duration_ms=int((time.monotonic() - started) * 1000), usage=provider_usage,
                     status="succeeded", error_code=None,
                     prompt_version=prompt_version,
                     prompt_fingerprint=fingerprint)
    if return_metadata:
        return {"text": text, "model": {"provider": model.get("provider", ""), "name": model.get("model", "")},
                "provider_usage": provider_usage}
    return text


def _degraded_direct_result(*, model: dict[str, Any], prompt: str, system_prompt: str | None,
                            max_tokens: int, timeout_seconds: int, reason: str,
                            return_metadata: bool, user_id: str | None = None,
                            project_id: str | None = None, execution_id: str | None = None,
                            use_tools: bool = True, purpose: str,
                            prompt_version: str | None = None,
                            prompt_fingerprint: str | None = None) -> str | dict:
    """Run the direct provider call and shape it like a normal AI Server result.

    When tools are wanted, the provider is called with the workbench tool
    catalogue and the model's tool calls are executed in-process — the same
    tools and the same capability gate the MCP route uses, just without the
    DSH hop. `degraded` marks the run as having bypassed the DSH runtime.
    CR-006：降级腿同样记账（used_fallback=True 标记绕行），成功/失败各落一条。
    """
    model_name = str(model.get("model") or "")
    request_identifier = execution_id or str(uuid4())
    tool_trace: list[dict[str, Any]] = []
    if use_tools and user_id:
        from fde_api.control.ai_tool_loop import direct_tool_completion
        with db.session() as session:
            user = session.get(User, user_id)
            if user is not None:
                started = time.monotonic()
                try:
                    text, usage, tool_trace = direct_tool_completion(
                        model=model, prompt=prompt, user=user, project_id=project_id,
                        execution_id=request_identifier,
                        system_prompt=system_prompt, max_tokens=max_tokens,
                        timeout_seconds=timeout_seconds)
                except DSHRuntimeError as error:
                    _audit_execution(request_id=request_identifier, actor_id=user_id,
                                     purpose=purpose, model=model_name, used_fallback=True,
                                     duration_ms=int((time.monotonic() - started) * 1000),
                                     usage=None, status="failed", error_code=error.code,
                                     prompt_version=prompt_version,
                                     prompt_fingerprint=prompt_fingerprint)
                    raise
                _audit_execution(request_id=request_identifier, actor_id=user_id,
                                 purpose=purpose, model=model_name, used_fallback=True,
                                 duration_ms=int((time.monotonic() - started) * 1000),
                                 usage=usage, status="succeeded", error_code=None,
                                 prompt_version=prompt_version,
                                 prompt_fingerprint=prompt_fingerprint)
                if not return_metadata:
                    return text
                return {
                    "text": text,
                    "model": {"provider": model.get("provider", ""), "name": model.get("model", "")},
                    "provider_usage": usage,
                    "degraded": True,
                    "degraded_reason": reason,
                    "tools_available": True,
                    "tool_trace": tool_trace,
                }
    started = time.monotonic()
    try:
        text, usage = direct_provider_completion(
            model=model, prompt=prompt, system_prompt=system_prompt,
            max_tokens=max_tokens, timeout_seconds=timeout_seconds)
    except DSHRuntimeError as error:
        _audit_execution(request_id=request_identifier, actor_id=user_id,
                         purpose=purpose, model=model_name, used_fallback=True,
                         duration_ms=int((time.monotonic() - started) * 1000),
                         usage=None, status="failed", error_code=error.code,
                         prompt_version=prompt_version,
                         prompt_fingerprint=prompt_fingerprint)
        raise
    _audit_execution(request_id=request_identifier, actor_id=user_id,
                     purpose=purpose, model=model_name, used_fallback=True,
                     duration_ms=int((time.monotonic() - started) * 1000),
                     usage=usage, status="succeeded", error_code=None,
                     prompt_version=prompt_version,
                     prompt_fingerprint=prompt_fingerprint)
    if not return_metadata:
        return text
    return {
        "text": text,
        "model": {"provider": model.get("provider", ""), "name": model.get("model", "")},
        "provider_usage": usage,
        "degraded": True,
        "degraded_reason": reason,
        "tools_available": False,
        "tool_trace": tool_trace,
    }


def structured_completion(*, messages, model: str, base_url: str, api_key, max_tokens: int,
                          on_event=None, deep_thinking=None, purpose: str = "structured",
                          prompt_version: str | None = None):
    actor = ai_actor_id.get()
    if not actor and has_request_context():
        user = getattr(g, "current_user", None)
        actor = user.id if user else None
    if not actor:
        # Background business jobs already authorize and build their own scoped
        # prompt. No MCP tools are enabled for these structured requests.
        with db.session() as session:
            actor = session.scalar(select(User.id).where(User.role == "admin", User.is_active.is_(True)).limit(1))
    if not actor:
        raise DSHRuntimeError("ai_access_denied", "没有可用的 AI 执行账号。", retryable=False)
    if on_event:
        on_event({"type": "stage_changed", "text": "AI Server 正在生成结构化结果"})
    key = api_key.get_secret_value() if hasattr(api_key, "get_secret_value") else api_key
    from fde_api.control.model_preferences import ModelPreference
    from sqlalchemy import or_
    with db.session() as session:
        has_default = session.scalar(select(ModelPreference.id).where(ModelPreference.is_default.is_(True),
            or_(ModelPreference.owner_user_id == actor, ModelPreference.scope == "public")).limit(1)) is not None
    # DSH 路径的失败必须落在同一个错误分类里：调用方（kimi/deepseek 客户端）
    # 只把 DSHRuntimeError 转成自己的异常类型，其余异常会逃出去被上层当成
    # 未预期错误——重试语义与失败分类都会失效。
    from fde_api.control.service import ControlServiceError
    try:
        value = execute_ai_prompt(user_id=actor, prompt=json.dumps(messages, ensure_ascii=False), use_tools=False,
            system_prompt="按提供的messages逐条理解角色和要求。只输出一个合法JSON对象，不要Markdown代码块，不调用工具。",
            max_tokens=max_tokens, deep_thinking=deep_thinking, purpose=purpose,
            prompt_version=prompt_version,
            model_override=None if has_default else {"model": model, "base_url": base_url, "api_key": key,
                                                "provider": "deepseek" if "deepseek.com" in base_url else "openai-compatible"})
    except ControlServiceError as error:
        # 模型未配置/密钥不可用/无权限等确定性配置问题：重试也不会好。
        raise DSHRuntimeError(error.code, error.message, retryable=False) from error
    from fde_api.ai.deepseek import _parse_json_object
    try:
        parsed = _parse_json_object(value)
    except (json.JSONDecodeError, ValueError) as error:
        # 模型没按 JSON 合同输出（概率性现象）：可重试，且必须带
        # ai_output_invalid 这个分类——否则上层看不到可重试信号。
        logger.warning("AI Server returned non-JSON structured output")
        raise DSHRuntimeError("ai_output_invalid", "AI Server 返回格式不正确。", retryable=True) from error
    if not isinstance(parsed, dict):
        raise DSHRuntimeError("ai_output_invalid", "AI Server 返回格式不正确。", retryable=True)
    if on_event:
        on_event({"type": "content_delta", "text": json.dumps(parsed, ensure_ascii=False)})
    return parsed
