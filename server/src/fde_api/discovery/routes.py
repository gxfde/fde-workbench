"""discovery 蓝图：8 路由（V3.1 P0-1）。

全部不进 api_catalog（治理审阅面——事实/需求审阅是人工决策动作，不是
AI 工具调用面；沿 transcripts/ontology 治理面先例）。
权限：创建抽取/重跑/审阅=can_manage；读面=can_view。
"""

from flask import Blueprint, g, jsonify, request

from fde_api.auth.decorators import require_auth
from fde_api.discovery import service
from fde_api.errors import error_response

discovery_blueprint = Blueprint("discovery", __name__, url_prefix="/api/v1")


@discovery_blueprint.errorhandler(service.DiscoveryServiceError)
def service_error(error):
    return error_response(error.code, error.message, error.status, error.detail or None)


def _payload():
    value = request.get_json(silent=True)
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise service.DiscoveryServiceError("invalid_request", "请求内容必须为 JSON 对象。", 400)
    return value


def _data(value, status=200):
    return jsonify({"data": value, "error": None}), status


def _list_args(default_limit: int = 50, max_limit: int = 200) -> tuple[int, int]:
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    try:
        limit = int(limit_raw) if limit_raw is not None else default_limit
        offset = int(offset_raw) if offset_raw is not None else 0
    except ValueError:
        raise service.DiscoveryServiceError("invalid_request", "limit/offset 必须是整数。", 400) from None
    if not 1 <= limit <= max_limit:
        raise service.DiscoveryServiceError("invalid_request", f"limit 须在 1..{max_limit}。", 400)
    if offset < 0:
        raise service.DiscoveryServiceError("invalid_request", "offset 不能为负。", 400)
    return limit, offset


@discovery_blueprint.post("/projects/<project_id>/discovery/extractions")
@require_auth
def create_extraction(project_id):
    """创建结构化抽取（入队后台任务；同源同版本幂等返回既有行=200，新建=201）。"""
    result = service.create_extraction(actor=g.current_user, project_id=project_id, payload=_payload())
    return _data(result, 201 if result.get("created") else 200)


@discovery_blueprint.get("/projects/<project_id>/discovery/extractions")
@require_auth
def list_extractions(project_id):
    limit, offset = _list_args()
    return _data(
        service.list_extractions(actor=g.current_user, project_id=project_id, limit=limit, offset=offset)
    )


@discovery_blueprint.get("/discovery/extractions/<extraction_id>")
@require_auth
def get_extraction(extraction_id):
    return _data(service.get_extraction(actor=g.current_user, extraction_id=extraction_id))


@discovery_blueprint.post("/discovery/extractions/<extraction_id>/run")
@require_auth
def run_extraction(extraction_id):
    """重跑失败抽取（review_required 行的审阅痕迹不可被覆盖——409 保护）。"""
    return _data(service.rerun_extraction(actor=g.current_user, extraction_id=extraction_id))


@discovery_blueprint.get("/projects/<project_id>/business-facts")
@require_auth
def list_facts(project_id):
    limit, offset = _list_args(default_limit=100)
    return _data(
        service.list_facts(
            actor=g.current_user,
            project_id=project_id,
            review_status=request.args.get("review_status"),
            fact_type=request.args.get("fact_type"),
            limit=limit,
            offset=offset,
        )
    )


@discovery_blueprint.patch("/business-facts/<fact_id>/review")
@require_auth
def review_fact(fact_id):
    return _data(service.review_fact(actor=g.current_user, fact_id=fact_id, payload=_payload()))


@discovery_blueprint.get("/projects/<project_id>/requirements")
@require_auth
def list_requirements(project_id):
    limit, offset = _list_args(default_limit=100)
    return _data(
        service.list_requirements(
            actor=g.current_user,
            project_id=project_id,
            status=request.args.get("status"),
            limit=limit,
            offset=offset,
        )
    )


@discovery_blueprint.patch("/requirements/<requirement_id>/review")
@require_auth
def review_requirement(requirement_id):
    return _data(service.review_requirement(actor=g.current_user, requirement_id=requirement_id, payload=_payload()))
