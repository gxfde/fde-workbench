from __future__ import annotations

from flask import Blueprint, g, jsonify, request

from fde_api.auth.decorators import require_auth
from fde_api.errors import error_response
from fde_api.guidance.service import (
    GuidanceServiceError, confirm_analysis, create_analysis, create_manual_revision, current_guidance,
    get_analysis, list_analyses, set_presurvey_source, update_analysis,
)

guidance_blueprint = Blueprint("guidance", __name__, url_prefix="/api/v1/projects/<project_id>")


def _ok(data, status=200): return jsonify({"data": data, "error": None}), status
def _error(error: GuidanceServiceError): return error_response(error.code, error.message, error.status)


@guidance_blueprint.post("/presurvey-source")
@require_auth
def source_route(project_id: str):
    payload = request.get_json(silent=True) or {}
    try: return _ok(set_presurvey_source(actor=g.current_user, project_id=project_id, file_version_id=payload.get("file_version_id", "")))
    except GuidanceServiceError as error: return _error(error)


@guidance_blueprint.get("/guidance-analyses")
@require_auth
def list_route(project_id: str):
    try: return _ok({"items": list_analyses(actor=g.current_user, project_id=project_id)})
    except GuidanceServiceError as error: return _error(error)


@guidance_blueprint.post("/guidance-analyses")
@require_auth
def create_route(project_id: str):
    payload = request.get_json(silent=True) or {}
    try: return _ok(create_analysis(actor=g.current_user, project_id=project_id, source_file_version_id=payload.get("source_file_version_id")), 201)
    except GuidanceServiceError as error: return _error(error)


@guidance_blueprint.get("/guidance-analyses/<analysis_id>")
@require_auth
def detail_route(project_id: str, analysis_id: str):
    try: return _ok(get_analysis(actor=g.current_user, project_id=project_id, analysis_id=analysis_id))
    except GuidanceServiceError as error: return _error(error)


@guidance_blueprint.patch("/guidance-analyses/<analysis_id>")
@require_auth
def patch_route(project_id: str, analysis_id: str):
    payload = request.get_json(silent=True) or {}
    version = payload.pop("version", None)
    if type(version) is not int: return error_response("invalid_request", "缺少有效版本号。", 400)
    try: return _ok(update_analysis(actor=g.current_user, project_id=project_id, analysis_id=analysis_id, expected_version=version, changes=payload))
    except GuidanceServiceError as error: return _error(error)


@guidance_blueprint.post("/guidance-analyses/<analysis_id>/revisions")
@require_auth
def revision_route(project_id: str, analysis_id: str):
    payload = request.get_json(silent=True) or {}
    if type(payload.get("version")) is not int: return error_response("invalid_request", "缺少有效版本号。", 400)
    try: return _ok(create_manual_revision(actor=g.current_user, project_id=project_id, analysis_id=analysis_id, expected_version=payload["version"]), 201)
    except GuidanceServiceError as error: return _error(error)


@guidance_blueprint.post("/guidance-analyses/<analysis_id>/confirm")
@require_auth
def confirm_route(project_id: str, analysis_id: str):
    payload = request.get_json(silent=True) or {}
    if type(payload.get("version")) is not int: return error_response("invalid_request", "缺少有效版本号。", 400)
    try: return _ok(confirm_analysis(actor=g.current_user, project_id=project_id, analysis_id=analysis_id, expected_version=payload["version"]))
    except GuidanceServiceError as error: return _error(error)


@guidance_blueprint.get("/guidance")
@require_auth
def current_route(project_id: str):
    try: return _ok(current_guidance(actor=g.current_user, project_id=project_id))
    except GuidanceServiceError as error: return _error(error)
