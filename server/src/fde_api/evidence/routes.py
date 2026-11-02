from flask import Blueprint, g, jsonify, request

from fde_api.auth.decorators import require_auth
from fde_api.errors import error_response
from fde_api.evidence import service

evidence_blueprint = Blueprint(
    "project_evidence", __name__, url_prefix="/api/v1/projects/<project_id>/evidence"
)


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
