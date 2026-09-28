"""Generic, audited API execution and server-enforced password confirmation.

OperationEvent is append-only: request, start and result are separate records.
An uncertain started mutation is never replayed. Skills cannot approve actions.
"""
import hashlib
import json
import re
from datetime import UTC, datetime, timedelta

from flask import Blueprint, current_app, g, jsonify, request
from sqlalchemy import select

from fde_api.auth.decorators import require_auth
from fde_api.auth.models import User
from fde_api.auth.passwords import verify_password
from fde_api.auth.tokens import issue_access_token
from fde_api.control.access import capabilities_for_level, effective_ai_access
from fde_api.control.api_catalog import CATALOG
from fde_api.control.service import ControlServiceError
from fde_api.errors import error_response
from fde_api.extensions import db
from fde_api.workbench.models import OperationEvent

actions_blueprint = Blueprint("ai_actions", __name__, url_prefix="/api/v1/ai/actions")
SECRET_KEYS = {"password", "api_key", "token", "access_token", "refresh_token", "authorization", "credential", "credential_ciphertext", "secret"}


def _safe(value, *, incoming=False):
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            if any(word in str(key).lower() for word in SECRET_KEYS):
                if incoming:
                    raise ControlServiceError("secret_not_allowed", "密码和密钥只能在专用安全界面输入，不能作为 AI 操作参数。", 400)
                continue
            result[key] = _safe(item, incoming=incoming)
        return result
    if isinstance(value, list):
        return [_safe(item, incoming=incoming) for item in value]
    return value


def _spec(operation, parameters, body, query):
    spec = CATALOG.get(operation) if isinstance(operation, str) else None
    if not spec or not all(isinstance(v, dict) for v in (parameters, body, query)):
        raise ControlServiceError("invalid_operation", "操作或参数格式无效，请先查询操作目录。", 400)
    expected = set(re.findall(r"\{(\w+)\}", spec["path"]))
    if set(parameters) != expected or any(not isinstance(v, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", v) for v in parameters.values()):
        raise ControlServiceError("invalid_parameters", "实体 ID 参数缺失或格式无效。", 400)
    _safe({"body": body, "query": query}, incoming=True)
    if len(json.dumps([body, query], ensure_ascii=False)) > 60000:
        raise ControlServiceError("request_too_large", "操作参数过大，请分批处理。", 400)
    if spec["method"] == "GET" and body:
        raise ControlServiceError("invalid_request", "查询操作不能携带写入内容。", 400)
    return spec


def _invoke(user, spec, parameters, body, query):
    # Internal dispatch to exactly the same authenticated API used by the UI.
    token = issue_access_token(user, current_app.config["SETTINGS"])
    response = current_app.test_client().open(spec["path"].format(**parameters), method=spec["method"],
        json=body if spec["method"] != "GET" else None, query_string=query,
        headers={"Authorization": "Bearer " + token})
    if len(response.data) > 2_000_000:
        raise ControlServiceError("result_too_large", "结果过大，请使用查询条件或分页。", 409)
    result = response.get_json(silent=True)
    if not isinstance(result, dict):
        raise ControlServiceError("invalid_api_response", "接口未返回可读取结果。", 502)
    return {"http_status": response.status_code, "result": _safe(result)}


def _event(session, user, identifier, kind, changes, project_id=None):
    session.add(OperationEvent(actor_user_id=user.id, project_id=project_id, target_type="ai_api_action",
        target_id=identifier, event_type="ai.api." + kind, changes=changes))
    session.commit()


def _events(session, user_id, identifier):
    return session.scalars(select(OperationEvent).where(OperationEvent.actor_user_id == user_id,
        OperationEvent.target_type == "ai_api_action", OperationEvent.target_id == identifier)
        .order_by(OperationEvent.created_at, OperationEvent.id)).all()


def _result(events):
    for item in events:
        if item.event_type == "ai.api.finished":
            return item.changes
    if any(e.event_type == "ai.api.cancelled" for e in events):
        return {"status": "cancelled"}
    if any(e.event_type == "ai.api.started" for e in events):
        return {"status": "uncertain", "message": "操作已开始，结果尚未确认。为防止重复修改，不会自动重试，请先查询目标状态。"}
    return None


def _authorized(user, spec, parameters, scope=None):
    if not user.is_active or user.must_change_password:
        raise ControlServiceError("forbidden", "账号授权已失效。", 403)
    allowed = capabilities_for_level(effective_ai_access(user)[0])
    if not allowed or (spec["write"] and "workbench.write" not in allowed):
        raise ControlServiceError("forbidden", "当前账号没有 AI 操作权限。", 403)
    if scope and parameters.get("project_id") != scope:
        raise ControlServiceError("forbidden", "操作超出本次项目授权范围。", 403)
    if parameters.get("project_id"):
        from fde_api.control.mcp_gateway import _project
        with db.session() as session:
            _project(session, user, {"project_id": scope}, parameters["project_id"])


def execute_api(*, user, claims, allowed, operation=None, parameters=None, body=None, query=None):
    parameters, body, query = parameters or {}, body or {}, query or {}
    spec = _spec(operation, parameters, body, query)
    if spec["write"] and "workbench.write" not in allowed:
        raise ControlServiceError("forbidden", "本次 AI 执行未获写入授权。", 403)
    _authorized(user, spec, parameters, claims.get("project_id"))
    if not spec["write"]:
        return _invoke(user, spec, parameters, body, query)
    execution_id = claims.get("execution_id")
    if not execution_id:
        raise ControlServiceError("execution_required", "写入操作需要可追溯的执行身份。", 403)
    data = {"operation": operation, "parameters": parameters, "body": body, "query": query}
    identifier = hashlib.sha256(json.dumps([user.id, execution_id, data], ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    lock = current_app.extensions["fde_api_redis"].lock("fde:ai:action:" + identifier, timeout=180, blocking=False)
    if not lock.acquire(blocking=False):
        return {"action_id": identifier, "status": "running"}
    try:
        with db.session() as session:
            events = _events(session, user.id, identifier)
            previous = _result(events)
            if previous:
                return {"action_id": identifier, **previous}
            sensitive = spec["confirmation"] or any(k in body for k in ("leader_user_id", "role", "permissions")) or str(body.get("status", "")) in {"archived", "deprecated", "cancelled", "inactive"} or body.get("action") in {"uninstall", "remove", "disable"}
            if operation == "plugins.decide":
                from fde_api.control.models import PluginChangeRequest
                change = session.get(PluginChangeRequest, parameters["request_id"])
                sensitive = bool(change and change.action in {"remove", "disable"} and body.get("decision") == "approve")
            if operation == "models.save" and body.get("id"):
                from fde_api.control.model_preferences import ModelPreference
                model = session.get(ModelPreference, body["id"])
                # Retained keys must not silently be redirected to a new host/provider.
                sensitive = sensitive or bool(model and model.credential_ciphertext and (
                    model.base_url.rstrip("/") != str(body.get("base_url", "")).rstrip("/")
                    or model.provider != body.get("provider")))
            if not events:
                fingerprint = None
                if operation == "files.deprecate":
                    from fde_api.files.models import ProjectFile
                    target = session.get(ProjectFile, parameters["file_id"])
                    if not target or target.project_id != parameters["project_id"]:
                        raise ControlServiceError("not_found", "文件不存在。", 404)
                    fingerprint = [target.id, target.version, target.current_version_id, target.status, target.display_name]
                if operation == "models.delete":
                    from fde_api.control.model_preferences import ModelPreference
                    target = session.get(ModelPreference, parameters["preference_id"])
                    if not target or not (target.scope == "public" and user.role == "admin" or target.owner_user_id == user.id):
                        raise ControlServiceError("not_found", "模型不存在或无权删除。", 404)
                    fingerprint = [target.id, target.version, target.name]
                _event(session, user, identifier, "requested", {**data, "auth_version": user.auth_version,
                    "scope": claims.get("project_id"), "confirmation_required": sensitive,
                    "execution_id": execution_id, "target_fingerprint": fingerprint,
                    "description": spec["description"] + ("：" + fingerprint[-1] if fingerprint else "")}, parameters.get("project_id"))
            if sensitive:
                return {"action_id": identifier, "status": "awaiting_confirmation", "message": "尚未执行。请在工作台确认弹窗输入当前账号密码；微信使用专用确认指令，密码不交给模型。"}
            return _run(session, user, identifier, spec, data)
    finally:
        try:
            lock.release()
        except Exception:
            pass


def _run(session, user, identifier, spec, data, password=None):
    _event(session, user, identifier, "started", {}, data["parameters"].get("project_id"))
    body = dict(data["body"])
    if data["operation"] == "models.save":
        body["api_key"] = ""  # Retain existing secret or create unconfigured draft.
    if data["operation"] == "solutions.archive":
        body["password"] = password  # Verified via the dedicated confirmation UI, never persisted.
    if data["operation"] == "models.delete":
        body["password"] = password  # In-memory only, never recorded in events.
        if data.get("target_fingerprint"):
            body["expected_version"] = data["target_fingerprint"][1]
    if data["operation"] == "files.deprecate" and data.get("target_fingerprint"):
        body["expected_version"] = data["target_fingerprint"][1]
    result = _invoke(user, spec, data["parameters"], body, data["query"])
    outcome = {"status": "completed" if result["http_status"] < 400 else "failed", **result}
    _event(session, user, identifier, "finished", outcome, data["parameters"].get("project_id"))
    return {"action_id": identifier, **outcome}


def pending_actions(user):
    with db.session() as session:
        rows = session.scalars(select(OperationEvent).where(OperationEvent.actor_user_id == user.id,
            OperationEvent.event_type == "ai.api.requested", OperationEvent.created_at >= datetime.now(UTC) - timedelta(minutes=15))
            .order_by(OperationEvent.created_at.desc()).limit(50)).all()
        return [{"id": row.target_id, "description": row.changes["description"],
                 "operation": row.changes["operation"], "parameters": row.changes["parameters"], "body": row.changes["body"]}
                for row in rows if row.changes.get("confirmation_required") and not _result(_events(session, user.id, row.target_id))]


def action_status(user, identifier):
    with db.session() as session:
        events = _events(session, user.id, identifier)
        if not events:
            raise ControlServiceError("not_found", "操作不存在或不属于当前账号。", 404)
        previous = _result(events)
        if previous:
            return previous
        original = next((e for e in events if e.event_type == "ai.api.requested"), None)
        if original:
            return {"status": "expired" if original.created_at < datetime.now(UTC) - timedelta(minutes=15) else "awaiting_confirmation"}
        return {"status": "not_completed", "message": "尚未确认完成，请勿声称成功。"}


def decide_action(user, identifier, password, approve=True):
    if not re.fullmatch(r"[a-f0-9]{64}", identifier or ""):
        raise ControlServiceError("invalid_action", "确认请求无效。", 400)
    lock = current_app.extensions["fde_api_redis"].lock("fde:ai:action:" + identifier, timeout=180, blocking=False)
    if not lock.acquire(blocking=False):
        raise ControlServiceError("action_running", "操作处理中，请勿重复确认。", 409)
    try:
        with db.session() as session:
            events = _events(session, user.id, identifier)
            previous = _result(events)
            if previous:
                return previous
            original = next((e for e in events if e.event_type == "ai.api.requested"), None)
            if not original or not original.changes.get("confirmation_required") or original.created_at < datetime.now(UTC) - timedelta(minutes=15):
                raise ControlServiceError("action_expired", "确认请求不存在或已过期，请重新发起操作。", 409)
            data = original.changes
            if not approve:
                _event(session, user, identifier, "cancelled", {}, original.project_id)
                return {"status": "cancelled"}
            current = session.get(User, user.id)
            if current.auth_version != data["auth_version"]:
                raise ControlServiceError("action_expired", "账号验证信息已改变，请重新发起操作。", 409)
            redis = current_app.extensions["fde_api_redis"]
            key = "fde:ai:confirmation-failures:" + user.id
            if int(redis.get(key) or 0) >= 5:
                raise ControlServiceError("too_many_attempts", "密码错误次数过多，请 15 分钟后重试。", 429)
            if not isinstance(password, str) or len(password) > 1024 or not verify_password(current.password_hash, password):
                redis.incr(key)
                redis.expire(key, 900)
                raise ControlServiceError("invalid_password", "当前账号密码不正确。", 403)
            spec = _spec(data["operation"], data["parameters"], data["body"], data["query"])
            _authorized(current, spec, data["parameters"], data.get("scope"))
            if data.get("target_fingerprint") and data["operation"] == "files.deprecate":
                from fde_api.files.models import ProjectFile
                target = session.get(ProjectFile, data["parameters"]["file_id"], with_for_update=True)
                if not target or [target.id, target.version, target.current_version_id, target.status, target.display_name] != data["target_fingerprint"]:
                    raise ControlServiceError("stale_version", "待操作文件已经变化，请重新发起操作并确认。", 409)
            return _run(session, current, identifier, spec, data, password=password)
    finally:
        try:
            lock.release()
        except Exception:
            pass


@actions_blueprint.get("")
@require_auth
def pending_route():
    return jsonify({"data": {"items": pending_actions(g.current_user)}, "error": None})


@actions_blueprint.post("/<identifier>/decision")
@require_auth
def decision_route(identifier):
    payload = request.get_json(silent=True) or {}
    try:
        if not isinstance(payload, dict) or set(payload) - {"password", "approve"} or type(payload.get("approve", True)) is not bool:
            raise ControlServiceError("invalid_request", "确认参数无效。", 400)
        result = decide_action(g.current_user, identifier, payload.get("password"), payload.get("approve", True))
        return jsonify({"data": result, "error": None})
    except ControlServiceError as error:
        return error_response(error.code, error.message, error.status)
