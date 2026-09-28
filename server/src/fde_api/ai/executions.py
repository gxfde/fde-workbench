"""Redis-backed AI executions with live, provider-supplied stream events."""

from __future__ import annotations

import json
import threading
from datetime import UTC, datetime
from typing import Any, Callable
from uuid import uuid4

from flask import current_app

from fde_api.ai.ai_opportunity_service import discover_ai_opportunities
from fde_api.ai.industry_template_service import chat_about_template, generate_project_configuration, generate_template_draft
from fde_api.ai.memo_merge_service import merge_research_memos
from fde_api.ai.research_form_service import generate_project_research_form, generate_research_form
from fde_api.auth.models import User
from fde_api.extensions import db


EXECUTION_TTL_SECONDS = 60 * 60
MAX_EVENTS = 1_200

OPERATIONS: dict[str, tuple[Callable[..., dict[str, Any]], set[str]]] = {
    "industry_template_chat": (chat_about_template, {"admin"}),
    "project_draft_chat": (chat_about_template, {"admin", "project_lead"}),
    "industry_template_generate": (generate_template_draft, {"admin"}),
    "project_draft_generate": (generate_project_configuration, {"admin", "project_lead"}),
    "industry_research_form_generate": (generate_research_form, {"admin"}),
    "project_research_form_generate": (generate_project_research_form, {"admin", "project_lead", "fde_engineer"}),
    "project_ai_opportunities_discover": (discover_ai_opportunities, {"admin", "project_lead", "fde_engineer"}),
    "project_research_memos_merge": (merge_research_memos, {"admin", "project_lead", "fde_engineer"}),
}


class AIExecutionError(Exception):
    def __init__(self, code: str, message: str, status: int):
        super().__init__(message)
        self.code, self.message, self.status = code, message, status


def start_execution(*, actor: User, operation: str, payload: object) -> dict[str, Any]:
    if operation not in OPERATIONS or not isinstance(payload, dict):
        raise AIExecutionError("invalid_request", "AI 执行请求格式不正确。", 400)
    _handler, roles = OPERATIONS[operation]
    if actor.role not in roles:
        raise AIExecutionError("forbidden", "当前账号没有执行该 AI 操作的权限。", 403)
    execution_id = str(uuid4())
    now = datetime.now(UTC).isoformat()
    state = {
        "id": execution_id,
        "operation": operation,
        "status": "running",
        "stage": "正在准备上下文",
        "actor_id": actor.id,
        "created_at": now,
        "updated_at": now,
        "result": None,
        "error": None,
    }
    redis = current_app.extensions["fde_api_redis"]
    redis.setex(_state_key(execution_id), EXECUTION_TTL_SECONDS, json.dumps(state, ensure_ascii=False))
    _append_event(redis, execution_id, {"type": "stage_changed", "text": "正在准备上下文"})
    app = current_app._get_current_object()
    thread = threading.Thread(
        target=_run,
        args=(app, execution_id, actor.id, operation, payload),
        name=f"ai-execution-{execution_id[:8]}",
        daemon=True,
    )
    thread.start()
    return _public_state(state, events=[])


def get_execution(*, actor: User, execution_id: str, after: int = 0) -> dict[str, Any]:
    redis = current_app.extensions["fde_api_redis"]
    state = _load_state(redis, execution_id)
    if state is None or state.get("actor_id") != actor.id:
        raise AIExecutionError("ai_execution_not_found", "AI 执行记录不存在或已过期。", 404)
    raw_events = redis.lrange(_events_key(execution_id), max(0, after), -1)
    events = [json.loads(item) for item in raw_events]
    return _public_state(state, events=events, event_offset=max(0, after))


def _run(app: Any, execution_id: str, actor_id: str, operation: str, payload: dict[str, Any]) -> None:
    from fde_api.control.ai_server_client import ai_actor_id
    ai_actor_id.set(actor_id)
    with app.app_context():
        redis = current_app.extensions["fde_api_redis"]
        session = db.session()
        try:
            actor = session.get(User, actor_id)
            if actor is None or not actor.is_active:
                raise AIExecutionError("authentication_required", "登录状态已失效。", 401)
            handler, _roles = OPERATIONS[operation]
            _update_stage(redis, execution_id, "正在等待 AI 响应")

            def on_event(event: dict[str, str]) -> None:
                _append_event(redis, execution_id, event)

            if operation == "industry_research_form_generate":
                result = handler(payload, on_event=on_event)
            else:
                result = handler(actor=actor, payload=payload, on_event=on_event)
            _update_stage(redis, execution_id, "正在校验并整理结果")
            _finish(redis, execution_id, status="completed", result=result)
            _append_event(redis, execution_id, {"type": "completed", "text": "AI 处理完成"})
        except Exception as error:  # public error fields are deliberately filtered below
            code = getattr(error, "code", "internal_error")
            message = getattr(error, "message", None) or getattr(error, "public_message", None) or "AI 处理失败，请稍后重试。"
            status = int(getattr(error, "status", 500))
            _finish(redis, execution_id, status="failed", error={"code": code, "message": str(message), "status": status})
            _append_event(redis, execution_id, {"type": "failed", "text": str(message)})
        finally:
            session.close()


def _update_stage(redis: Any, execution_id: str, stage: str) -> None:
    state = _load_state(redis, execution_id)
    if state is None:
        return
    state["stage"] = stage
    state["updated_at"] = datetime.now(UTC).isoformat()
    redis.setex(_state_key(execution_id), EXECUTION_TTL_SECONDS, json.dumps(state, ensure_ascii=False))
    _append_event(redis, execution_id, {"type": "stage_changed", "text": stage})


def _finish(redis: Any, execution_id: str, *, status: str, result: Any = None, error: Any = None) -> None:
    state = _load_state(redis, execution_id)
    if state is None:
        return
    state.update(status=status, result=result, error=error, updated_at=datetime.now(UTC).isoformat())
    redis.setex(_state_key(execution_id), EXECUTION_TTL_SECONDS, json.dumps(state, ensure_ascii=False))
    redis.expire(_events_key(execution_id), EXECUTION_TTL_SECONDS)


def _append_event(redis: Any, execution_id: str, event: dict[str, str]) -> None:
    payload = {**event, "at": datetime.now(UTC).isoformat()}
    key = _events_key(execution_id)
    redis.rpush(key, json.dumps(payload, ensure_ascii=False))
    redis.ltrim(key, -MAX_EVENTS, -1)
    redis.expire(key, EXECUTION_TTL_SECONDS)


def _load_state(redis: Any, execution_id: str) -> dict[str, Any] | None:
    raw = redis.get(_state_key(execution_id))
    if raw is None:
        return None
    return json.loads(raw)


def _public_state(state: dict[str, Any], *, events: list[dict[str, Any]], event_offset: int = 0) -> dict[str, Any]:
    return {
        "id": state["id"],
        "operation": state["operation"],
        "status": state["status"],
        "stage": state["stage"],
        "created_at": state["created_at"],
        "updated_at": state["updated_at"],
        "result": state.get("result"),
        "error": state.get("error"),
        "events": events,
        "next_offset": event_offset + len(events),
    }


def _state_key(execution_id: str) -> str:
    return f"fde:ai-execution:{execution_id}:state"


def _events_key(execution_id: str) -> str:
    return f"fde:ai-execution:{execution_id}:events"
