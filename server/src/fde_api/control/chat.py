"""Durable per-user AI conversations; the outbox survives client disconnects."""
from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4, uuid5, NAMESPACE_URL

from flask import Blueprint, g, jsonify, request
from sqlalchemy import Boolean, ForeignKey, JSON, String, Text, select
from sqlalchemy.orm import Mapped, mapped_column

from fde_api.auth.decorators import require_auth
from fde_api.auth.models import Base, User
from fde_api.control.access import effective_ai_access
from fde_api.control.ai_server_client import execute_ai_prompt
from fde_api.control.dsh_runtime import DSHRuntimeError
from fde_api.control.service import ControlServiceError
from fde_api.errors import error_response
from fde_api.extensions import db
from fde_api.jobs.outbox import enqueue_outbox
from fde_api.workbench.models import TimestampMixin, new_uuid, Project
from fde_api.projects.permissions import project_access


class AIConversation(Base, TimestampMixin):
    __tablename__ = "ai_conversations"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(160), nullable=False)
    project_id: Mapped[str | None] = mapped_column(ForeignKey("projects.id", ondelete="RESTRICT"))
    source: Mapped[str] = mapped_column(String(20), nullable=False, default="desktop")


class AIChatTurn(Base, TimestampMixin):
    __tablename__ = "ai_chat_turns"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    conversation_id: Mapped[str] = mapped_column(ForeignKey("ai_conversations.id", ondelete="CASCADE"), index=True)
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    response: Mapped[str] = mapped_column(Text, nullable=False, default="")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="queued")
    error_message: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    model_preference_id: Mapped[str | None] = mapped_column(String(36))
    deep_thinking: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="0")
    metrics_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)


chat_blueprint = Blueprint("ai_chat", __name__, url_prefix="/api/v1/ai/chat")


def _authorize(user):
    if not user.is_active or effective_ai_access(user)[0] == "disabled":
        raise ControlServiceError("ai_access_denied", "管理员尚未为此账号开放 AI 权限。", 403)


def _turn(turn):
    return {"id": turn.id, "conversation_id": turn.conversation_id, "prompt": turn.prompt,
            "response": turn.response, "status": turn.status, "error_message": turn.error_message,
            "created_at": turn.created_at.isoformat(), "deep_thinking": turn.deep_thinking,
            "metrics": turn.metrics_json or {}}


def create_turn(*, user: User, payload: dict, source="desktop", enqueue=True):
    _authorize(user)
    deep_thinking = payload.get("deep_thinking", False)
    if type(deep_thinking) is not bool:
        raise ControlServiceError("invalid_request", "深度思考开关无效。", 400)
    prompt = payload.get("message")
    if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > 16000:
        raise ControlServiceError("invalid_request", "消息不能为空且最多16000字。", 400)
    try:
        turn_id = str(UUID(payload.get("message_id", "")))
        conversation_id = str(UUID(payload["conversation_id"])) if payload.get("conversation_id") else str(uuid4())
    except (ValueError, TypeError, AttributeError) as error:
        raise ControlServiceError("invalid_request", "会话标识无效。", 400) from error
    with db.session() as session, session.begin():
        # Serialize same-user retries/concurrent sends before looking up their ID.
        session.scalar(select(User).where(User.id == user.id).with_for_update())
        previous = session.get(AIChatTurn, turn_id)
        if previous:
            conversation = session.get(AIConversation, previous.conversation_id)
            if (conversation.user_id != user.id or previous.prompt != prompt.strip()
                or (payload.get("conversation_id") and conversation.id != conversation_id)
                or previous.deep_thinking != deep_thinking
                or previous.model_preference_id != (payload.get("model_preference_id") or None)
                or (payload.get("project_id") and conversation.project_id != payload["project_id"])):
                raise ControlServiceError("message_conflict", "消息标识冲突。", 409)
            return _turn(previous)
        conversation = session.get(AIConversation, conversation_id)
        if conversation is not None and conversation.user_id != user.id:
            raise ControlServiceError("not_found", "会话不存在。", 404)
        if conversation is None:
            project_id = payload.get("project_id") or None
            if project_id:
                project = session.get(Project, project_id)
                if not project or not project_access(user, project).can_view:
                    raise ControlServiceError("forbidden", "无权访问此项目。", 403)
            conversation = AIConversation(id=conversation_id, user_id=user.id, title=prompt.strip()[:80],
                                          project_id=project_id, source=source)
            session.add(conversation)
            session.flush()
        pending = session.scalar(select(AIChatTurn.id).where(AIChatTurn.conversation_id == conversation.id,
                    AIChatTurn.status.in_(["queued", "running"])).limit(1))
        if pending:
            raise ControlServiceError("chat_busy", "此会话上一条消息仍在处理中。", 409)
        preference = payload.get("model_preference_id") or None
        if preference:
            from fde_api.control.model_preferences import resolve_model_preference
            resolve_model_preference(session, user.id, preference)
        turn = AIChatTurn(id=turn_id, conversation_id=conversation.id, prompt=prompt.strip(),
                          model_preference_id=preference, deep_thinking=deep_thinking, status="queued", response="", error_message="")
        session.add(turn)
        session.flush()
        conversation.updated_at = datetime.now(UTC)
        if enqueue:
            enqueue_outbox(session, "ai.chat", turn.id, {})
        return _turn(turn)


def execute_chat_turn(turn_id):
    with db.session() as session, session.begin():
        turn = session.get(AIChatTurn, turn_id, with_for_update=True)
        if not turn or turn.status == "completed":
            return turn.response if turn else ""
        conversation = session.get(AIConversation, turn.conversation_id)
        user = session.get(User, conversation.user_id)
        try:
            _authorize(user)
        except ControlServiceError as error:
            turn.status, turn.error_message = "failed", error.message
            return error.message
        history = session.scalars(select(AIChatTurn).where(AIChatTurn.conversation_id == conversation.id,
            AIChatTurn.status == "completed").order_by(AIChatTurn.created_at.desc()).limit(12)).all()
        context = "\n\n".join(f"用户：{t.prompt}\n助手：{t.response}" for t in reversed(history))[-60000:]
        prompt = ("以下是当前会话历史：\n" + context + "\n\n当前用户消息：\n" if context else "") + turn.prompt
        actor_id, project_id, preference_id = user.id, conversation.project_id, turn.model_preference_id
        depth = turn.deep_thinking
        turn.status = "running"
    try:
        output = execute_ai_prompt(user_id=actor_id, prompt=prompt, execution_id=turn_id,
                                   project_id=project_id, preference_id=preference_id, deep_thinking=depth,
                                   all_projects=True, return_metadata=True)
        answer = output["text"] if isinstance(output, dict) else output
        metrics = {"model": output.get("model", {}), "provider_usage": output.get("provider_usage", {})} if isinstance(output, dict) else {}
        if metrics:
            from fde_api.control.chat_cost import estimate_chat_cost
            metrics["cost"] = estimate_chat_cost(metrics["provider_usage"])
    except (DSHRuntimeError, ControlServiceError) as error:
        message = getattr(error, "public_message", None) or getattr(error, "message", "AI Server 暂不可用。")
        with db.session() as session, session.begin():
            current = session.get(AIChatTurn, turn_id)
            current.status, current.error_message = "failed", message
        raise
    except Exception:
        with db.session() as session, session.begin():
            current = session.get(AIChatTurn, turn_id)
            current.status, current.error_message = "failed", "AI Server 处理异常，请重试。"
        raise DSHRuntimeError("ai_execution_failed", "AI Server 处理异常，请重试。", retryable=True) from None
    with db.session() as session, session.begin():
        current = session.get(AIChatTurn, turn_id)
        current.status, current.response, current.error_message = "completed", answer, ""
        current.metrics_json = metrics
    return answer


def execute_chat_job(job):
    execute_chat_turn(job.target_id)


def weixin_message_handler(user_id, text, event_id):
    with db.session() as session:
        user = session.get(User, user_id)
    if not user:
        return "工作台账号不可用。"
    try:
        # These commands terminate here: passwords never enter a model turn.
        if text.startswith(("确认操作 ", "取消操作 ")):
            from fde_api.control.api_actions import decide_action
            parts = text.split(" ", 2)
            approve = parts[0] == "确认操作"
            result = decide_action(user, parts[1] if len(parts) > 1 else "",
                parts[2] if len(parts) > 2 else "", approve)
            labels = {"completed": "操作已完成并留痕。", "cancelled": "操作已取消。", "failed": "操作未完成，请在工作台查看目标状态。", "uncertain": "操作结果尚待核实，请勿重复执行。"}
            return labels.get(result.get("status"), "确认请求已处理。")
        turn = create_turn(user=user, source="wechat", enqueue=False, payload={"message": text,
            "message_id": str(uuid5(NAMESPACE_URL, f"weixin:{user_id}:{event_id}")),
            "conversation_id": str(uuid5(NAMESPACE_URL, f"weixin-chat:{user_id}"))})
        answer = execute_chat_turn(turn["id"])
        from fde_api.control.api_actions import pending_actions
        pending = pending_actions(user)
        if pending:
            answer += "\n\n以下操作尚未执行，需验证当前工作台账号密码。也可在工作台弹窗确认。微信专用格式：确认操作 操作编号 密码（该指令由服务端验证，不交给 AI）。取消格式：取消操作 操作编号。\n" + "\n".join(f"{item['description']}\n操作编号：{item['id']}" for item in pending)
        return answer
    except ControlServiceError as error:
        if error.status < 500:
            return error.message
        raise


@chat_blueprint.get("/conversations")
@require_auth
def conversations():
    with db.session() as session:
        rows = session.scalars(select(AIConversation).where(AIConversation.user_id == g.current_user.id)
            .order_by(AIConversation.updated_at.desc()).limit(50))
        return jsonify({"data": {"items": [{"id": c.id, "title": c.title, "source": c.source} for c in rows]}, "error": None})


@chat_blueprint.get("/conversations/<conversation_id>")
@require_auth
def conversation_details(conversation_id):
    with db.session() as session:
        row = session.get(AIConversation, conversation_id)
        if row is None or row.user_id != g.current_user.id:
            return error_response("not_found", "会话不存在。", 404)
        turns = session.scalars(select(AIChatTurn).where(AIChatTurn.conversation_id == row.id)
            .order_by(AIChatTurn.created_at.desc(), AIChatTurn.id.desc()).limit(200)).all()
        return jsonify({"data": {"id": row.id, "title": row.title, "items": [_turn(t) for t in reversed(turns)]}, "error": None})


@chat_blueprint.post("/messages")
@require_auth
def send_message():
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return error_response("invalid_request", "消息参数无效。", 400)
    try:
        return jsonify({"data": create_turn(user=g.current_user, payload=payload), "error": None}), 202
    except ControlServiceError as error:
        return error_response(error.code, error.message, error.status)


@chat_blueprint.get("/messages/<turn_id>/progress")
@require_auth
def message_progress(turn_id):
    with db.session() as session:
        row = session.execute(select(AIChatTurn, AIConversation).join(AIConversation)
            .where(AIChatTurn.id == turn_id, AIConversation.user_id == g.current_user.id)).first()
        if row is None:
            return error_response("not_found", "消息不存在。", 404)
        try:
            _authorize(g.current_user)
            from fde_api.control.dsh_runtime import dsh_runtime
            response = dsh_runtime.current.primary._request("GET", f"/v1/executions/{row[0].id}/progress",
                params={"actor": g.current_user.id}, timeout=5)
            value = response.json() if response.status_code == 200 else {}
        except ControlServiceError as error:
            return error_response(error.code, error.message, error.status)
        except (DSHRuntimeError, ValueError):
            value = {}
        return jsonify({"data": {"text": value.get("text", ""), "steps": value.get("steps", []),
            "phase": value.get("phase", "正在处理"), "status": row[0].status}, "error": None})
