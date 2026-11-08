from flask import Blueprint, g, jsonify, request

from fde_api.auth.decorators import require_auth
from fde_api.errors import error_response
from fde_api.evidence import service

evidence_blueprint = Blueprint(
    "project_evidence", __name__, url_prefix="/api/v1/projects/<project_id>/evidence"
)

# 只读执行事实链（借鉴登记 #9）：独立全路径 blueprint——路径语义是「项目事实
# 流」而非「证据簿」，与 T-W6 workflow-runs 只读挂件同范式（can_view、有界、
# 只读、有意不进 api_catalog——AI 不经此面读审计原始流）。
fact_chain_blueprint = Blueprint("execution_fact_chain", __name__)


@fact_chain_blueprint.errorhandler(service.EvidenceServiceError)
def fact_chain_service_error(error):
    return error_response(error.code, error.message, error.status)


@fact_chain_blueprint.get("/api/v1/projects/<project_id>/execution-facts")
@require_auth
def list_execution_facts(project_id):
    """三源只读时间线（can_view）：?fact_type=evidence|operation_event|ai_call_audit；?limit=1–200。"""
    raw_limit = request.args.get("limit")
    try:
        limit = int(raw_limit) if raw_limit is not None else None
    except ValueError:
        raise service.EvidenceServiceError("invalid_request", "limit 必须是整数。", 400)
    data = service.execution_facts(
        actor=g.current_user,
        project_id=project_id,
        fact_type=request.args.get("fact_type"),
        limit=limit,
    )
    return jsonify({"data": data, "error": None})


@evidence_blueprint.errorhandler(service.EvidenceServiceError)
def service_error(error):
    return error_response(error.code, error.message, error.status)


def _payload():
    value = request.get_json(silent=True)
    if not isinstance(value, dict):
        raise service.EvidenceServiceError("invalid_request", "请求内容必须为 JSON 对象。", 400)
    return value


@evidence_blueprint.get("")
@require_auth
def list_evidence(project_id):
    """证据登记簿（can_view）：?kind= 按种类；?referenced_by=gate:G5 反查门禁清单项挂接的证据。"""
    data = service.list_evidence(
        actor=g.current_user,
        project_id=project_id,
        kind=request.args.get("kind"),
        referenced_by=request.args.get("referenced_by"),
    )
    return jsonify({"data": data, "error": None})


@evidence_blueprint.post("")
@require_auth
def register_evidence(project_id):
    """登记证据指针（can_manage）：同指纹幂等（created=false 时 200）。人工路径——有意不进 api_catalog。"""
    data = service.register_evidence(actor=g.current_user, project_id=project_id, payload=_payload())
    return jsonify({"data": data, "error": None}), (201 if data["created"] else 200)


@evidence_blueprint.post("/validate")
@require_auth
def validate_evidence(project_id):
    """证据完整性只读校验（can_view；V3.1 P1-2 6.5）：零写入零事件，逐条报五维检查。"""
    data = service.validate_evidence(actor=g.current_user, project_id=project_id, payload=_payload())
    return jsonify({"data": data, "error": None})
