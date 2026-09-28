from __future__ import annotations

from typing import Any

from flask import Blueprint, g, jsonify, request

from fde_api.auth.decorators import require_auth
from fde_api.control.service import (
    ControlServiceError,
    account_summary,
    begin_wechat_binding,
    create_automation_task,
    create_dsh_approval_request,
    decide_automation_approval,
    dsh_approval_status,
    execute_approved_dsh_tool,
    complete_wechat_binding,
    dsh_knowledge_for_run,
    list_task_center,
    list_automation_approvals,
    record_dsh_execution_event,
    request_automation_run,
    submit_wechat_command,
    update_profile,
    update_wechat_binding,
)
from fde_api.control.clawbot_gateway import verify_gateway_token
from fde_api.control.extensions_service import (
    decide_plugin_change,
    extensions_center,
    request_plugin_change,
    save_ai_model,
    save_ai_provider,
    save_personal_skill,
    save_public_skill,
)
from fde_api.control.dsh_market import search_dsh_market, sync_dsh_market
from fde_api.control.access import authorize_ai_capability
from fde_api.control.dsh_runtime import DSHRuntimeError, dsh_runtime
from fde_api.errors import error_response


control_blueprint = Blueprint("control", __name__, url_prefix="/api/v1")


@control_blueprint.get("/extensions")
@require_auth
def extensions_route():
    return jsonify({"data": extensions_center(user=g.current_user), "error": None})


@control_blueprint.post("/extensions/skills/personal")
@require_auth
def personal_skill_route():
    payload = _json_payload()
    if payload is None:
        return _invalid_request()
    try:
        data = save_personal_skill(user=g.current_user, payload=payload)
        return jsonify({"data": data, "error": None}), 201
    except ControlServiceError as error:
        return _service_error(error)


@control_blueprint.post("/extensions/skills/public")
@require_auth
def public_skill_route():
    payload = _json_payload()
    if payload is None:
        return _invalid_request()
    try:
        return jsonify({"data": save_public_skill(user=g.current_user, payload=payload), "error": None}), 201
    except ControlServiceError as error:
        return _service_error(error)


@control_blueprint.post("/extensions/providers")
@require_auth
def provider_config_route():
    payload = _json_payload()
    if payload is None:
        return _invalid_request()
    try:
        return jsonify({"data": save_ai_provider(user=g.current_user, payload=payload), "error": None}), 201
    except ControlServiceError as error:
        return _service_error(error)


@control_blueprint.post("/extensions/models")
@require_auth
def model_config_route():
    payload = _json_payload()
    if payload is None:
        return _invalid_request()
    try:
        return jsonify({"data": save_ai_model(user=g.current_user, payload=payload), "error": None}), 201
    except ControlServiceError as error:
        return _service_error(error)


@control_blueprint.post("/extensions/plugins/<plugin_id>/requests")
@require_auth
def plugin_change_request_route(plugin_id: str):
    payload = _json_payload()
    if payload is None:
        return _invalid_request()
    try:
        data = request_plugin_change(user=g.current_user, plugin_id=plugin_id, payload=payload)
        return jsonify({"data": data, "error": None}), 202
    except ControlServiceError as error:
        return _service_error(error)


@control_blueprint.post("/extensions/plugin-requests/<request_id>/decision")
@require_auth
def plugin_change_decision_route(request_id: str):
    payload = _json_payload()
    if payload is None:
        return _invalid_request()
    try:
        data = decide_plugin_change(user=g.current_user, request_id=request_id, payload=payload)
        return jsonify({"data": data, "error": None})
    except ControlServiceError as error:
        return _service_error(error)


@control_blueprint.get("/extensions/marketplace/search")
@require_auth
def marketplace_search_route():
    try:
        data = search_dsh_market(
            query=request.args.get("q", ""),
            category=request.args.get("category", ""),
            page=request.args.get("page", 1, type=int),
            page_size=request.args.get("page_size", 24, type=int),
        )
        return jsonify({"data": data, "error": None})
    except ControlServiceError as error:
        return _service_error(error)


@control_blueprint.post("/extensions/marketplace/sync")
@require_auth
def marketplace_sync_route():
    try:
        data = sync_dsh_market(user=g.current_user)
        return jsonify({"data": data, "error": None})
    except ControlServiceError as error:
        return _service_error(error)


@control_blueprint.get("/account")
@require_auth
def account_route():
    return jsonify({"data": account_summary(g.current_user), "error": None})


@control_blueprint.patch("/account/profile")
@require_auth
def profile_route():
    payload = _json_payload()
    if payload is None or set(payload) != {"display_name"} or not isinstance(payload["display_name"], str):
        return _invalid_request()
    try:
        data = update_profile(user=g.current_user, display_name=payload["display_name"])
        return jsonify({"data": data, "error": None})
    except ControlServiceError as error:
        return _service_error(error)


@control_blueprint.post("/account/wechat-clawbot/binding")
@require_auth
def begin_wechat_binding_route():
    return jsonify({"data": begin_wechat_binding(user=g.current_user), "error": None}), 201


@control_blueprint.post("/account/wechat-clawbot/<action>")
@require_auth
def update_wechat_binding_route(action: str):
    try:
        data = update_wechat_binding(user=g.current_user, action=action)
        return jsonify({"data": data, "error": None})
    except ControlServiceError as error:
        return _service_error(error)


@control_blueprint.get("/task-center")
@require_auth
def task_center_route():
    return jsonify({"data": list_task_center(user=g.current_user), "error": None})


@control_blueprint.get("/task-center/approvals")
@require_auth
def task_center_approvals_route():
    return jsonify({"data": list_automation_approvals(user=g.current_user), "error": None})


@control_blueprint.post("/task-center/approvals/<approval_id>/decision")
@require_auth
def task_center_approval_decision_route(approval_id: str):
    payload = _json_payload()
    if payload is None:
        return _invalid_request()
    try:
        data = decide_automation_approval(
            user=g.current_user,
            approval_id=approval_id,
            decision_value=payload.get("decision", ""),
            password=payload.get("password", ""),
            reason=payload.get("reason", ""),
        )
        return jsonify({"data": data, "error": None})
    except ControlServiceError as error:
        return _service_error(error)


@control_blueprint.post("/task-center/automations")
@require_auth
def create_automation_route():
    payload = _json_payload()
    if payload is None:
        return _invalid_request()
    try:
        data = create_automation_task(user=g.current_user, payload=payload)
        return jsonify({"data": data, "error": None}), 201
    except ControlServiceError as error:
        return _service_error(error)


@control_blueprint.post("/task-center/automations/<task_id>/runs")
@require_auth
def run_automation_route(task_id: str):
    try:
        data = request_automation_run(
            user=g.current_user,
            task_id=task_id,
            idempotency_key=request.headers.get("Idempotency-Key"),
        )
        return jsonify({"data": data, "error": None}), 202
    except ControlServiceError as error:
        return _service_error(error)


@control_blueprint.get("/control/dsh/health")
@require_auth
def dsh_health_route():
    decision = authorize_ai_capability(user=g.current_user, capability="system.health")
    if not decision.allowed:
        return error_response("forbidden", "当前账户无权查看 DSH 运行状态。", 403)
    try:
        return jsonify({"data": dsh_runtime.current.health(), "error": None})
    except DSHRuntimeError as error:
        return error_response(error.code, error.public_message, 503 if error.retryable else 409)


@control_blueprint.post("/internal/dsh/executions/<run_id>/events")
def dsh_execution_event_route(run_id: str):
    authorization = request.headers.get("Authorization", "")
    token = authorization[7:] if authorization.startswith("Bearer ") else None
    if not dsh_runtime.current.verify_service_token(token):
        return error_response("authentication_required", "DSH 服务认证失败。", 401)
    payload = _json_payload()
    if payload is None:
        return _invalid_request()
    try:
        data = record_dsh_execution_event(run_id=run_id, payload=payload)
        return jsonify({"data": data, "error": None})
    except ControlServiceError as error:
        return _service_error(error)


@control_blueprint.get("/internal/dsh/executions/<run_id>/knowledge")
def dsh_execution_knowledge_route(run_id: str):
    authorization = request.headers.get("Authorization", "")
    token = authorization[7:] if authorization.startswith("Bearer ") else None
    if not dsh_runtime.current.verify_service_token(token):
        return error_response("authentication_required", "DSH 服务认证失败。", 401)
    try:
        return jsonify({"data": dsh_knowledge_for_run(run_id=run_id), "error": None})
    except ControlServiceError as error:
        return _service_error(error)


@control_blueprint.post("/internal/dsh/executions/<run_id>/approvals")
def dsh_approval_request_route(run_id: str):
    authorization = request.headers.get("Authorization", "")
    token = authorization[7:] if authorization.startswith("Bearer ") else None
    if not dsh_runtime.current.verify_service_token(token):
        return error_response("authentication_required", "DSH 服务认证失败。", 401)
    payload = _json_payload()
    if payload is None:
        return _invalid_request()
    try:
        data = create_dsh_approval_request(run_id=run_id, payload=payload)
        return jsonify({"data": data, "error": None}), 202
    except ControlServiceError as error:
        return _service_error(error)


@control_blueprint.get("/internal/dsh/approvals/<approval_id>")
def dsh_approval_status_route(approval_id: str):
    authorization = request.headers.get("Authorization", "")
    token = authorization[7:] if authorization.startswith("Bearer ") else None
    if not dsh_runtime.current.verify_service_token(token):
        return error_response("authentication_required", "DSH 服务认证失败。", 401)
    try:
        return jsonify({"data": dsh_approval_status(approval_id=approval_id), "error": None})
    except ControlServiceError as error:
        return _service_error(error)


@control_blueprint.post("/internal/dsh/approvals/<approval_id>/execute")
def dsh_approval_execute_route(approval_id: str):
    authorization = request.headers.get("Authorization", "")
    token = authorization[7:] if authorization.startswith("Bearer ") else None
    if not dsh_runtime.current.verify_service_token(token):
        return error_response("authentication_required", "DSH 服务认证失败。", 401)
    try:
        data = execute_approved_dsh_tool(approval_id=approval_id)
        return jsonify({"data": data, "error": None})
    except ControlServiceError as error:
        return _service_error(error)


@control_blueprint.post("/internal/clawbot/bindings/complete")
def clawbot_binding_complete_route():
    if not _gateway_authenticated():
        return error_response("authentication_required", "ClawBot 网关认证失败。", 401)
    payload = _json_payload()
    if payload is None:
        return _invalid_request()
    try:
        data = complete_wechat_binding(
            binding_code=payload.get("binding_code", ""),
            external_subject=payload.get("external_subject", ""),
            display_name=payload.get("display_name", ""),
        )
        return jsonify({"data": data, "error": None})
    except ControlServiceError as error:
        return _service_error(error)


@control_blueprint.post("/internal/clawbot/events")
def clawbot_event_route():
    if not _gateway_authenticated():
        return error_response("authentication_required", "ClawBot 网关认证失败。", 401)
    payload = _json_payload()
    if payload is None:
        return _invalid_request()
    try:
        data = submit_wechat_command(payload=payload)
        return jsonify({"data": data, "error": None}), 202
    except ControlServiceError as error:
        return _service_error(error)


def _gateway_authenticated() -> bool:
    authorization = request.headers.get("Authorization", "")
    token = authorization[7:] if authorization.startswith("Bearer ") else None
    return verify_gateway_token(token)


def _json_payload() -> dict[str, Any] | None:
    payload = request.get_json(silent=True)
    return payload if isinstance(payload, dict) else None


def _invalid_request():
    return error_response("invalid_request", "请检查输入内容。", 400)


def _service_error(error: ControlServiceError):
    return error_response(error.code, error.message, error.status)
