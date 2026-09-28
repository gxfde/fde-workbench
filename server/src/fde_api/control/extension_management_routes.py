from __future__ import annotations

from flask import Blueprint, g, jsonify, request
from sqlalchemy import select

from fde_api.auth.decorators import require_auth
from fde_api.auth.models import User
from fde_api.control.access import ACCESS_RANK, capabilities_for_level, effective_ai_access
from fde_api.control.extensions_service import get_plugin_detail, get_skill_detail, update_skill_status
from fde_api.control.model_preferences import delete_model_preference, list_model_preferences, save_model_preference
from fde_api.control.models import UserAIAccessGrant
from fde_api.control.service import ControlServiceError
from fde_api.errors import error_response
from fde_api.extensions import db
from fde_api.workbench.models import OperationEvent

management_blueprint = Blueprint("extension_management", __name__, url_prefix="/api/v1")
ACCESS_LABELS = {"disabled": "未开通 AI", "assistant_read": "AI 只读助手", "project_operator": "AI 项目操作员", "project_manager": "AI 项目管理员", "system_operator": "AI 系统管理员（完全权限）"}


@management_blueprint.errorhandler(ControlServiceError)
def handle_error(error):
    return error_response(error.code, error.message, error.status)


def _payload():
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        raise ControlServiceError("invalid_request", "请求参数无效。", 400)
    return payload


def _data(value):
    return jsonify({"data": value, "error": None})


@management_blueprint.get("/extensions/model-preferences")
@require_auth
def model_preferences_list():
    return _data({"items": list_model_preferences(user=g.current_user)})


@management_blueprint.post("/extensions/model-preferences")
@require_auth
def model_preferences_save():
    return _data(save_model_preference(user=g.current_user, payload=_payload()))


@management_blueprint.delete("/extensions/model-preferences/<preference_id>")
@require_auth
def model_preferences_delete(preference_id):
    from fde_api.auth.passwords import verify_password
    payload = _payload()
    password = payload.get("password")
    if set(payload) - {"password", "expected_version"} or not isinstance(password, str) or not 1 <= len(password) <= 1024:
        raise ControlServiceError("password_required", "请输入当前账号的密码确认删除。", 400)
    if not verify_password(g.current_user.password_hash, password):
        raise ControlServiceError("invalid_password", "当前账号密码不正确。", 403)
    return _data(delete_model_preference(user=g.current_user, preference_id=preference_id, expected_version=payload.get("expected_version")))


@management_blueprint.get("/extensions/skills/<skill_id>")
@require_auth
def skill_detail(skill_id):
    return _data(get_skill_detail(user=g.current_user, skill_id=skill_id))


@management_blueprint.patch("/extensions/skills/<skill_id>")
@require_auth
def skill_status(skill_id):
    return _data(update_skill_status(user=g.current_user, skill_id=skill_id, payload=_payload()))


@management_blueprint.get("/extensions/plugins/<plugin_id>")
@require_auth
def plugin_detail(plugin_id):
    return _data(get_plugin_detail(user=g.current_user, plugin_id=plugin_id))


def _require_admin():
    if g.current_user.role != "admin":
        raise ControlServiceError("forbidden", "只有管理员可以分配账号的 AI 权限。", 403)


@management_blueprint.get("/extensions/ai-access-options")
@require_auth
def access_options():
    return _data({"items": [{"level": level, "label": ACCESS_LABELS[level], "capabilities": capabilities_for_level(level)} for level in ACCESS_RANK]})


@management_blueprint.get("/users/<user_id>/ai-access")
@require_auth
def user_ai_access(user_id):
    _require_admin()
    with db.session() as session:
        user = session.get(User, user_id)
        if user is None:
            raise ControlServiceError("user_not_found", "用户不存在。", 404)
        level, source = effective_ai_access(user)
        return _data({"user_id": user.id, "level": level, "source": source, "label": ACCESS_LABELS[level], "capabilities": capabilities_for_level(level), "locked": user.role == "admin"})


@management_blueprint.patch("/users/<user_id>/ai-access")
@require_auth
def save_user_ai_access(user_id):
    _require_admin()
    payload = _payload()
    if set(payload) != {"level"} or payload["level"] not in ACCESS_RANK:
        raise ControlServiceError("invalid_access", "请选择有效的 AI 权限。", 400)
    with db.session() as session, session.begin():
        user = session.scalar(select(User).where(User.id == user_id).with_for_update())
        if user is None:
            raise ControlServiceError("user_not_found", "用户不存在。", 404)
        if user.role == "admin" and payload["level"] != "system_operator":
            raise ControlServiceError("admin_full_access", "管理员始终拥有完全权限；如需限制，请先调整账号角色。", 409)
        grant = session.scalar(select(UserAIAccessGrant).where(UserAIAccessGrant.user_id == user_id).with_for_update())
        before = grant.access_level if grant else effective_ai_access(user)[0]
        if grant is None:
            grant = UserAIAccessGrant(user_id=user_id, access_level=payload["level"], granted_by_user_id=g.current_user.id, reason="管理员在用户管理中分配")
            session.add(grant)
        else:
            grant.access_level, grant.granted_by_user_id = payload["level"], g.current_user.id
            grant.reason = "管理员在用户管理中分配"
        session.add(OperationEvent(actor_user_id=g.current_user.id, target_type="user_ai_access", target_id=user_id, event_type="ai_access.updated", changes={"before": before, "after": payload["level"]}))
        return _data({"user_id": user_id, "level": payload["level"], "label": ACCESS_LABELS[payload["level"]]})
