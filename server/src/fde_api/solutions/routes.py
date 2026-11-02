from flask import Blueprint, g, jsonify, request

from fde_api.agents.service import AgentsServiceError
from fde_api.auth.decorators import require_auth
from fde_api.errors import error_response
from fde_api.solutions import service

solutions_blueprint = Blueprint("project_solutions", __name__, url_prefix="/api/v1/projects/<project_id>/solutions")


@solutions_blueprint.errorhandler(service.SolutionServiceError)
def service_error(error):
    # T-P0-1：409 solution_signoff_required 携 details（pending checkpoint 指路）
    return error_response(error.code, error.message, error.status, error.detail or None)


@solutions_blueprint.errorhandler(AgentsServiceError)
def agents_error(error):
    # generate-agent 复用 agents.start_run 全链，其失败码/明细（如
    # review_gate_open 的 run_id）原样透传
    return error_response(error.code, error.message, error.status, error.detail or None)


def _payload():
    value = request.get_json(silent=True)
    if not isinstance(value, dict):
        raise service.SolutionServiceError("invalid_request", "请求内容必须为 JSON 对象。", 400)
    return value


def _data(value):
    return jsonify({"data": value, "error": None})


@solutions_blueprint.get("")
@require_auth
def list_solutions(project_id):
    return _data({"items": service.list_solutions(actor=g.current_user, project_id=project_id)})


@solutions_blueprint.post("")
@require_auth
def create_solution(project_id):
    return _data(service.create_solution(actor=g.current_user, project_id=project_id, payload=_payload())), 201


@solutions_blueprint.post("/ai-organize")
@require_auth
def organize_solution(project_id):
    return _data(service.organize_solution(actor=g.current_user, project_id=project_id, payload=_payload()))


@solutions_blueprint.post("/skeleton")
@require_auth
def create_solution_skeleton(project_id):
    """按已确认项目指引生成方案骨架草稿（S0-4；draft，人工修订后才可导出 SOW）。"""
    return _data(service.create_solution_skeleton(actor=g.current_user, project_id=project_id, payload=_payload())), 201


@solutions_blueprint.get("/<solution_id>/health")
@require_auth
def solution_health(project_id, solution_id):
    """方案健康度评分 v0：模板覆盖率/引用完整性/报价合法（S0-4）。"""
    return _data(service.solution_health(actor=g.current_user, project_id=project_id, solution_id=solution_id))


@solutions_blueprint.get("/<solution_id>")
@require_auth
def get_solution(project_id, solution_id):
    return _data(service.get_solution(actor=g.current_user, project_id=project_id, solution_id=solution_id))


@solutions_blueprint.patch("/<solution_id>")
@require_auth
def update_solution(project_id, solution_id):
    return _data(service.update_solution(actor=g.current_user, project_id=project_id, solution_id=solution_id, payload=_payload()))


@solutions_blueprint.post("/<solution_id>/archive")
@require_auth
def archive_solution(project_id, solution_id):
    return _data(service.archive_solution(actor=g.current_user, project_id=project_id, solution_id=solution_id, payload=_payload()))


@solutions_blueprint.post("/<solution_id>/export-sow")
@require_auth
def export_sow(project_id, solution_id):
    return _data(service.export_sow(actor=g.current_user, project_id=project_id, solution_id=solution_id, payload=_payload()))


@solutions_blueprint.post("/<solution_id>/generate-agent")
@require_auth
def generate_agent_solution(project_id, solution_id):
    """AI 生成方案（goal-d6）：agents.start_run 全链复用，completed 才接线
    solution.agent_run_id（generated_by='agent'）；T2 门未放行 409 原样透传。
    """
    body, status = service.generate_agent_solution(actor=g.current_user, project_id=project_id, solution_id=solution_id, payload=_payload())
    return _data(body), status


@solutions_blueprint.get("/<solution_id>/review-trail")
@require_auth
def solution_review_trail(project_id, solution_id):
    """终审台合并视图数据源（U5，goal-d9 扩 artifacts+signoff）：会议纪要（家族 ∪ 侧链）。"""
    return _data(service.solution_review_trail(actor=g.current_user, project_id=project_id, solution_id=solution_id))


@solutions_blueprint.post("/<solution_id>/signoff")
@require_auth
def resolve_signoff(project_id, solution_id):
    """终审台拍板收口（goal-d9）：approved/rejected；权限档闸 = checkpoint.required_level。
    人工拍板动作——有意不进 api_catalog（红线：不收代拍板写路径）。"""
    return _data(service.resolve_signoff(actor=g.current_user, project_id=project_id, solution_id=solution_id, payload=_payload()))
