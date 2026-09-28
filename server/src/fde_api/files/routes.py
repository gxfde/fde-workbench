from __future__ import annotations

from flask import Blueprint, g, jsonify, request

from fde_api.auth.decorators import require_auth
from fde_api.errors import error_response
from fde_api.files.previews import (
    get_download_url,
    get_preview_url,
    request_preview_regeneration,
)
from fde_api.files.service import (
    FileServiceError,
    abort_upload,
    complete_upload,
    create_upload_session,
    deprecate_project_file,
    deprecate_file_version,
    list_file_versions,
    list_project_files,
    rename_project_file,
    restore_file_version,
    restore_latest_project_file_version,
    sign_upload_part,
)

files_blueprint = Blueprint(
    "files", __name__, url_prefix="/api/v1/projects/<project_id>/files"
)


@files_blueprint.post("")
@require_auth
def create_upload_session_route(project_id: str):
    payload = _json_payload()
    if (
        not isinstance(payload, dict)
        or "name" not in payload
        or "size_bytes" not in payload
        or "idempotency_key" not in payload
    ):
        return _invalid_request()
    try:
        data = create_upload_session(
            actor=g.current_user,
            project_id=project_id,
            input=payload,
        )
        return jsonify({"data": data, "error": None}), 201
    except FileServiceError as error:
        return _service_error(error)


@files_blueprint.post("/<session_id>/parts")
@require_auth
def sign_upload_part_route(project_id: str, session_id: str):
    payload = _json_payload()
    if (
        not isinstance(payload, dict)
        or type(payload.get("part_number")) is not int
        or payload["part_number"] < 1
    ):
        return _invalid_request()
    try:
        data = sign_upload_part(
            actor=g.current_user,
            project_id=project_id,
            session_id=session_id,
            part_number=payload["part_number"],
        )
        return jsonify({"data": data, "error": None})
    except FileServiceError as error:
        return _service_error(error)


@files_blueprint.post("/<session_id>/complete")
@require_auth
def complete_upload_route(project_id: str, session_id: str):
    payload = _json_payload()
    if (
        not isinstance(payload, dict)
        or "parts" not in payload
        or not isinstance(payload["parts"], list)
    ):
        return _invalid_request()
    try:
        data = complete_upload(
            actor=g.current_user,
            project_id=project_id,
            session_id=session_id,
            parts=payload["parts"],
        )
        return jsonify({"data": data, "error": None}), 202
    except FileServiceError as error:
        return _service_error(error)


@files_blueprint.post("/<session_id>/abort")
@require_auth
def abort_upload_route(project_id: str, session_id: str):
    try:
        abort_upload(
            actor=g.current_user,
            project_id=project_id,
            session_id=session_id,
        )
        return jsonify({"data": None, "error": None})
    except FileServiceError as error:
        return _service_error(error)


@files_blueprint.get("")
@require_auth
def list_files_route(project_id: str):
    if set(request.args) - {"business_category"}:
        return _invalid_request()
    try:
        business_category = request.args.get("business_category") or None
        items = list_project_files(
            actor=g.current_user,
            project_id=project_id,
            business_category=business_category,
        )
        return jsonify({"data": {"items": items}, "error": None})
    except FileServiceError as error:
        return _service_error(error)


@files_blueprint.patch("/items/<file_id>")
@require_auth
def rename_file_route(project_id: str, file_id: str):
    payload = _json_payload()
    if not isinstance(payload, dict) or set(payload) != {"name"}:
        return _invalid_request()
    try:
        data = rename_project_file(
            actor=g.current_user,
            project_id=project_id,
            file_id=file_id,
            name=payload["name"],
        )
        return jsonify({"data": data, "error": None})
    except FileServiceError as error:
        return _service_error(error)


@files_blueprint.post("/items/<file_id>/deprecate")
@require_auth
def deprecate_file_route(project_id: str, file_id: str):
    payload = _json_payload() or {}
    reason = payload.get("reason", "")
    if not isinstance(reason, str):
        return _invalid_request()
    try:
        data = deprecate_project_file(
            actor=g.current_user, project_id=project_id, file_id=file_id, reason=reason,
            expected_version=payload.get("expected_version")
        )
        return jsonify({"data": data, "error": None})
    except FileServiceError as error:
        return _service_error(error)


@files_blueprint.post("/items/<file_id>/restore")
@require_auth
def restore_file_route(project_id: str, file_id: str):
    try:
        data = restore_latest_project_file_version(
            actor=g.current_user, project_id=project_id, file_id=file_id
        )
        return jsonify({"data": data, "error": None})
    except FileServiceError as error:
        return _service_error(error)


@files_blueprint.get("/<version_id>/preview-url")
@require_auth
def get_preview_url_route(project_id: str, version_id: str):
    if request.args:
        return _invalid_request()
    try:
        url = get_preview_url(
            actor=g.current_user,
            project_id=project_id,
            version_id=version_id,
        )
        return jsonify(
            {"data": {"url": url, "expires_seconds": 300}, "error": None}
        )
    except FileServiceError as error:
        return _service_error(error)


@files_blueprint.post("/<version_id>/preview")
@require_auth
def regenerate_preview_route(project_id: str, version_id: str):
    if request.args:
        return _invalid_request()
    try:
        data = request_preview_regeneration(
            actor=g.current_user,
            project_id=project_id,
            version_id=version_id,
        )
        return jsonify({"data": data, "error": None}), 202
    except FileServiceError as error:
        return _service_error(error)


@files_blueprint.get("/items/<file_id>/versions")
@require_auth
def list_file_versions_route(project_id: str, file_id: str):
    try:
        items = list_file_versions(actor=g.current_user, project_id=project_id, file_id=file_id)
        return jsonify({"data": {"items": items}, "error": None})
    except FileServiceError as error:
        return _service_error(error)


@files_blueprint.post("/versions/<version_id>/deprecate")
@require_auth
def deprecate_file_version_route(project_id: str, version_id: str):
    payload = _json_payload() or {}
    reason = payload.get("reason", "")
    if not isinstance(reason, str):
        return _invalid_request()
    try:
        data = deprecate_file_version(
            actor=g.current_user, project_id=project_id, version_id=version_id, reason=reason
        )
        return jsonify({"data": data, "error": None})
    except FileServiceError as error:
        return _service_error(error)


@files_blueprint.post("/versions/<version_id>/restore")
@require_auth
def restore_file_version_route(project_id: str, version_id: str):
    try:
        data = restore_file_version(actor=g.current_user, project_id=project_id, version_id=version_id)
        return jsonify({"data": data, "error": None})
    except FileServiceError as error:
        return _service_error(error)


@files_blueprint.get("/<version_id>/download-url")
@require_auth
def get_download_url_route(project_id: str, version_id: str):
    try:
        url = get_download_url(
            actor=g.current_user,
            project_id=project_id,
            version_id=version_id,
        )
        return jsonify(
            {"data": {"url": url, "expires_seconds": 300}, "error": None}
        )
    except FileServiceError as error:
        return _service_error(error)


def _json_payload():
    return request.get_json(silent=True) if request.is_json else None


def _invalid_request():
    return error_response("invalid_request", "The request body is invalid.", 400)


def _service_error(error: FileServiceError):
    return error_response(error.code, error.message, error.status)
