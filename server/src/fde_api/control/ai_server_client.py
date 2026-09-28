"""Shared AI Server entry point for chat and existing structured AI workflows."""
from __future__ import annotations

import json
from contextvars import ContextVar
from uuid import uuid4

from flask import current_app, g, has_request_context
from sqlalchemy import select

from fde_api.auth.models import User
from fde_api.control.dsh_runtime import DSHRuntimeError, dsh_runtime
from fde_api.control.mcp_gateway import issue_mcp_token
from fde_api.control.model_preferences import resolve_model_preference
from fde_api.extensions import db

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
                      return_metadata: bool = False) -> str | dict:
    identifier = execution_id or str(uuid4())
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
        token = issue_mcp_token(user, project_id=None if all_projects else project_id, capabilities=capabilities, execution_id=identifier) if use_tools else None
    settings = current_app.config["SETTINGS"]
    runtime = dsh_runtime.current.primary
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
    response = runtime._request("POST", "/v1/executions", json=body, timeout=settings.dsh_timeout_seconds,
                                headers={"Idempotency-Key": identifier})
    if response.status_code >= 400:
        raise runtime._service_error(response.status_code)
    result = runtime._json_object(response)
    text = result.get("output", {}).get("text")
    if result.get("status") != "succeeded" or not isinstance(text, str) or not text.strip():
        raise DSHRuntimeError("ai_output_invalid", "AI Server 未返回有效结果。", retryable=True)
    if return_metadata:
        return {"text": text, "model": {"provider": model.get("provider", ""), "name": model.get("model", "")},
                "provider_usage": result.get("provider_usage", {"complete": False, "calls": []})}
    return text


def structured_completion(*, messages, model: str, base_url: str, api_key, max_tokens: int, on_event=None, deep_thinking=None):
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
    value = execute_ai_prompt(user_id=actor, prompt=json.dumps(messages, ensure_ascii=False), use_tools=False,
        system_prompt="按提供的messages逐条理解角色和要求。只输出一个合法JSON对象，不要Markdown代码块，不调用工具。",
        max_tokens=max_tokens, deep_thinking=deep_thinking, model_override=None if has_default else {"model": model, "base_url": base_url, "api_key": key,
                                            "provider": "deepseek" if "deepseek.com" in base_url else "openai-compatible"})
    from fde_api.ai.deepseek import _parse_json_object
    parsed = _parse_json_object(value)
    if not isinstance(parsed, dict):
        raise DSHRuntimeError("ai_output_invalid", "AI Server 返回格式不正确。", retryable=True)
    if on_event:
        on_event({"type": "content_delta", "text": json.dumps(parsed, ensure_ascii=False)})
    return parsed
