from flask import Blueprint, g, jsonify, request

from fde_api.auth.decorators import require_auth
from fde_api.errors import error_response
from fde_api.solutions import service

solutions_blueprint = Blueprint("project_solutions", __name__, url_prefix="/api/v1/projects/<project_id>/solutions")


@solutions_blueprint.errorhandler(service.SolutionServiceError)
def service_error(error):
    return error_response(error.code, error.message, error.status)


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
