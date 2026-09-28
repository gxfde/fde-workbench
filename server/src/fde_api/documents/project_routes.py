"""Project-scoped document draft API routes.

Blueprint: ``project_documents_blueprint``, url_prefix
``/api/v1/projects/<project_id>/documents``. View routes are open to any project
viewer; create is project-manager only; draft patching and generation are open to
project engineers/managers. Service errors are wrapped with
:func:`fde_api.errors.error_response`.
"""

from __future__ import annotations

import base64
from typing import Any

from flask import Blueprint, g, jsonify, request

from fde_api.auth.decorators import require_auth
from fde_api.documents.draft_service import (
    DocumentDraftServiceError,
    create_project_document,
    get_project_document,
    list_project_documents,
    patch_project_document_draft,
    rename_project_document,
    request_document_generation,
)
from fde_api.documents.version_service import (
    DocumentVersionServiceError,
    archive_document_version,
    archive_all_document_versions,
    confirm_document_version,
    get_document_download_url,
    get_document_preview_url,
    list_document_versions,
    online_revise_document,
    resolve_document_version,
    restore_document_version,
    restore_latest_document_version,
    upload_manual_revision,
)
from fde_api.errors import error_response

project_documents_blueprint = Blueprint(
    "project_documents", __name__, url_prefix="/api/v1/projects/<project_id>/documents"
)


@project_documents_blueprint.get("")
@require_auth
def list_project_documents_route(project_id: str):
    if set(request.args) - {"business_category"}:
        return error_response(
            "invalid_request", "The request query is invalid.", 400
        )
    try:
        business_category = request.args.get("business_category") or None
        items = list_project_documents(
            actor=g.current_user,
            project_id=project_id,
            business_category=business_category,
        )
        return jsonify({"data": {"items": items}, "error": None})
    except DocumentDraftServiceError as error:
        return _service_error(error)


@project_documents_blueprint.post("")
@require_auth
def create_project_document_route(project_id: str):
    payload = _json_payload()
    if not payload or set(payload) - {
        "document_type",
        "template_version_id",
        "expected_version",
        "business_category",
        "source_opportunity_id",
        "source_opportunity_ids",
        "generation_scope",
    }:
        return error_response(
            "invalid_request", "Invalid document create payload.", 400
        )
    try:
        document = create_project_document(
            actor=g.current_user,
            project_id=project_id,
            input=payload,
        )
        return jsonify({"data": document, "error": None}), 201
    except DocumentDraftServiceError as error:
        return _service_error(error)


@project_documents_blueprint.get("/<document_id>")
@require_auth
def get_project_document_route(project_id: str, document_id: str):
    try:
        document = get_project_document(
            actor=g.current_user, project_id=project_id, document_id=document_id
        )
        return jsonify({"data": document, "error": None})
    except DocumentDraftServiceError as error:
        return _service_error(error)


@project_documents_blueprint.patch("/<document_id>")
@require_auth
def rename_project_document_route(project_id: str, document_id: str):
    payload = _json_payload()
    if (
        not payload
        or set(payload) != {"version", "name"}
        or type(payload.get("version")) is not int
        or payload["version"] < 1
    ):
        return error_response("invalid_request", "Invalid document rename payload.", 400)
    try:
        document = rename_project_document(
            actor=g.current_user,
            project_id=project_id,
            document_id=document_id,
            expected_version=payload["version"],
            name=payload["name"],
        )
        return jsonify({"data": document, "error": None})
    except DocumentDraftServiceError as error:
        return _service_error(error)


@project_documents_blueprint.post("/items/<document_id>/archive")
@require_auth
def archive_project_document_route(project_id: str, document_id: str):
    payload = _json_payload()
    if not payload or type(payload.get("version")) is not int or payload["version"] < 1:
        return error_response("invalid_request", "缺少有效的文档版本号。", 400)
    try:
        data = archive_all_document_versions(
            actor=g.current_user, project_id=project_id, document_id=document_id,
            expected_version=payload["version"],
        )
        return jsonify({"data": data, "error": None})
    except DocumentVersionServiceError as error:
        return _version_service_error(error)


@project_documents_blueprint.post("/items/<document_id>/restore")
@require_auth
def restore_project_document_route(project_id: str, document_id: str):
    payload = _json_payload()
    if not payload or type(payload.get("version")) is not int or payload["version"] < 1:
        return error_response("invalid_request", "缺少有效的文档版本号。", 400)
    try:
        data = restore_latest_document_version(
            actor=g.current_user, project_id=project_id, document_id=document_id,
            expected_version=payload["version"],
        )
        return jsonify({"data": data, "error": None})
    except DocumentVersionServiceError as error:
        return _version_service_error(error)


@project_documents_blueprint.patch("/<document_id>/draft")
@require_auth
def patch_project_document_draft_route(project_id: str, document_id: str):
    payload = _json_payload()
    if (
        not payload
        or type(payload.get("version")) is not int
        or payload["version"] < 1
        or set(payload) - {"version", "field_overrides", "rich_text", "list_selections"}
    ):
        return error_response("invalid_request", "Invalid draft patch payload.", 400)
    try:
        draft = patch_project_document_draft(
            actor=g.current_user,
            project_id=project_id,
            document_id=document_id,
            expected_version=payload["version"],
            changes={
                key: value for key, value in payload.items() if key != "version"
            },
        )
        return jsonify({"data": draft, "error": None})
    except DocumentDraftServiceError as error:
        return _service_error(error)


@project_documents_blueprint.post("/<document_id>/generate")
@require_auth
def request_document_generation_route(project_id: str, document_id: str):
    payload = _json_payload()
    if not payload or type(payload.get("version")) is not int or payload["version"] < 1:
        return error_response("invalid_request", "A document version is required.", 400)
    try:
        version = request_document_generation(
            actor=g.current_user,
            project_id=project_id,
            document_id=document_id,
            expected_version=payload["version"],
        )
        return jsonify({"data": version, "error": None})
    except DocumentDraftServiceError as error:
        return _service_error(error)


@project_documents_blueprint.get("/<document_id>/versions")
@require_auth
def list_document_versions_route(project_id: str, document_id: str):
    try:
        items = list_document_versions(
            actor=g.current_user, project_id=project_id, document_id=document_id
        )
        return jsonify({"data": {"items": items}, "error": None})
    except DocumentVersionServiceError as error:
        return _version_service_error(error)


@project_documents_blueprint.post("/<document_id>/revise")
@require_auth
def online_revise_route(project_id: str, document_id: str):
    payload = _json_payload()
    if (
        not payload
        or type(payload.get("version")) is not int
        or payload["version"] < 1
        or "draft_changes" not in payload
        or not isinstance(payload["draft_changes"], dict)
    ):
        return error_response("invalid_request", "Invalid revise payload.", 400)
    try:
        version = online_revise_document(
            actor=g.current_user,
            project_id=project_id,
            document_id=document_id,
            expected_version=payload["version"],
            draft_changes=payload["draft_changes"],
        )
        return jsonify({"data": version, "error": None})
    except DocumentVersionServiceError as error:
        return _version_service_error(error)


@project_documents_blueprint.post("/<document_id>/revisions/manual")
@require_auth
def upload_manual_revision_route(project_id: str, document_id: str):
    note = ""
    docx_bytes: bytes | None = None
    version: Any = None

    file_storage = request.files.get("file")
    if file_storage is not None:
        docx_bytes = file_storage.read()
        note = request.form.get("note", "")
        raw_version = request.form.get("version", "")
        version = int(raw_version) if raw_version.isdigit() else None
    else:
        payload = _json_payload()
        if not payload:
            return error_response(
                "invalid_request", "Invalid manual revision payload.", 400
            )
        note = payload.get("note", "")
        version = payload.get("version")
        file_b64 = payload.get("file_base64")
        if file_b64 is None or not isinstance(file_b64, str):
            return error_response("invalid_request", "A DOCX file is required.", 400)
        try:
            docx_bytes = base64.b64decode(file_b64)
        except (ValueError, TypeError):
            return error_response("invalid_request", "The file payload is invalid.", 400)

    if type(version) is not int or version < 1 or not docx_bytes:
        return error_response("invalid_request", "A document version is required.", 400)

    try:
        version_result = upload_manual_revision(
            actor=g.current_user,
            project_id=project_id,
            document_id=document_id,
            expected_version=version,
            docx_bytes=docx_bytes,
            note=note,
        )
        return jsonify({"data": version_result, "error": None}), 201
    except DocumentVersionServiceError as error:
        return _version_service_error(error)


@project_documents_blueprint.post("/<version_id>/confirm")
@require_auth
def confirm_document_version_route(project_id: str, version_id: str):
    payload = _json_payload()
    if not payload or type(payload.get("version")) is not int or payload["version"] < 1:
        return error_response("invalid_request", "A document version is required.", 400)
    try:
        document_id, target_version_number = resolve_document_version(version_id)
        version = confirm_document_version(
            actor=g.current_user,
            project_id=project_id,
            document_id=document_id,
            expected_version=payload["version"],
            target_version_number=target_version_number,
        )
        return jsonify({"data": version, "error": None})
    except DocumentVersionServiceError as error:
        return _version_service_error(error)


@project_documents_blueprint.post("/<version_id>/archive")
@require_auth
def archive_document_version_route(project_id: str, version_id: str):
    payload = _json_payload()
    if not payload or type(payload.get("version")) is not int or payload["version"] < 1:
        return error_response("invalid_request", "A document version is required.", 400)
    try:
        document_id, target_version_number = resolve_document_version(version_id)
        version = archive_document_version(
            actor=g.current_user,
            project_id=project_id,
            document_id=document_id,
            expected_version=payload["version"],
            target_version_number=target_version_number,
        )
        return jsonify({"data": version, "error": None})
    except DocumentVersionServiceError as error:
        return _version_service_error(error)


@project_documents_blueprint.post("/<version_id>/restore")
@require_auth
def restore_document_version_route(project_id: str, version_id: str):
    payload = _json_payload()
    if not payload or type(payload.get("version")) is not int or payload["version"] < 1:
        return error_response("invalid_request", "缺少有效的文档版本号。", 400)
    try:
        document_id, target_version_number = resolve_document_version(version_id)
        version = restore_document_version(
            actor=g.current_user, project_id=project_id, document_id=document_id,
            expected_version=payload["version"], target_version_number=target_version_number,
        )
        return jsonify({"data": version, "error": None})
    except DocumentVersionServiceError as error:
        return _version_service_error(error)


@project_documents_blueprint.get("/<version_id>/download-url")
@require_auth
def document_download_url_route(project_id: str, version_id: str):
    try:
        document_id, version_number = resolve_document_version(version_id)
        url = get_document_download_url(
            actor=g.current_user,
            project_id=project_id,
            document_id=document_id,
            version_number=version_number,
        )
        return jsonify(
            {"data": {"url": url, "expires_seconds": 300}, "error": None}
        )
    except DocumentVersionServiceError as error:
        return _version_service_error(error)


@project_documents_blueprint.get("/<version_id>/preview-url")
@require_auth
def document_preview_url_route(project_id: str, version_id: str):
    try:
        document_id, version_number = resolve_document_version(version_id)
        url = get_document_preview_url(
            actor=g.current_user,
            project_id=project_id,
            document_id=document_id,
            version_number=version_number,
        )
        return jsonify(
            {"data": {"url": url, "expires_seconds": 300}, "error": None}
        )
    except DocumentVersionServiceError as error:
        return _version_service_error(error)


def _json_payload() -> dict[str, Any] | None:
    payload = request.get_json(silent=True)
    return payload if isinstance(payload, dict) else None


def _service_error(error: DocumentDraftServiceError):
    return error_response(error.code, error.message, error.status)


def _version_service_error(error: DocumentVersionServiceError):
    return error_response(error.code, error.message, error.status)
