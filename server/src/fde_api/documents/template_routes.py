"""Admin-only document template API routes.

Blueprint: ``document_templates_blueprint``, url_prefix ``/api/v1/document-templates``.
Every route is gated by ``require_minimum_role("admin")``; service errors are
wrapped with :func:`fde_api.errors.error_response`.
"""

from __future__ import annotations

from flask import Blueprint, g, jsonify, request

from fde_api.auth.decorators import require_minimum_role
from fde_api.documents.template_service import (
    DocumentTemplateServiceError,
    copy_template_version,
    create_document_template_version,
    deactivate_template_version,
    get_template_version_download_url,
    list_document_templates,
    publish_template_version,
    test_generate_template_version,
)
from fde_api.errors import error_response

document_templates_blueprint = Blueprint(
    "document_templates", __name__, url_prefix="/api/v1/document-templates"
)


@document_templates_blueprint.get("")
@require_minimum_role("admin")
def list_document_templates_route():
    items = list_document_templates(actor=g.current_user)
    return jsonify({"data": {"items": items}, "error": None})


@document_templates_blueprint.post("/<identifier>/versions")
@require_minimum_role("admin")
def create_or_copy_version_route(identifier: str):
    uploaded_file = request.files.get("file")
    if uploaded_file is not None:
        try:
            version = create_document_template_version(
                actor=g.current_user,
                document_type=identifier,
                upload=uploaded_file.read(),
            )
            return jsonify({"data": version, "error": None}), 201
        except DocumentTemplateServiceError as error:
            return _service_error(error)

    try:
        version = copy_template_version(actor=g.current_user, template_id=identifier)
        return jsonify({"data": version, "error": None}), 201
    except DocumentTemplateServiceError as error:
        return _service_error(error)


@document_templates_blueprint.post("/<version_id>/test")
@require_minimum_role("admin")
def test_generate_version_route(version_id: str):
    try:
        result = test_generate_template_version(
            actor=g.current_user, version_id=version_id
        )
        return jsonify({"data": result, "error": None})
    except DocumentTemplateServiceError as error:
        return _service_error(error)


@document_templates_blueprint.post("/<version_id>/publish")
@require_minimum_role("admin")
def publish_version_route(version_id: str):
    try:
        version = publish_template_version(
            actor=g.current_user, version_id=version_id
        )
        return jsonify({"data": version, "error": None})
    except DocumentTemplateServiceError as error:
        return _service_error(error)


@document_templates_blueprint.post("/<version_id>/deactivate")
@require_minimum_role("admin")
def deactivate_version_route(version_id: str):
    try:
        version = deactivate_template_version(
            actor=g.current_user, version_id=version_id
        )
        return jsonify({"data": version, "error": None})
    except DocumentTemplateServiceError as error:
        return _service_error(error)


@document_templates_blueprint.get("/<version_id>/download-url")
@require_minimum_role("admin")
def download_version_route(version_id: str):
    try:
        url = get_template_version_download_url(
            actor=g.current_user, version_id=version_id
        )
        return jsonify(
            {"data": {"url": url, "expires_seconds": 300}, "error": None}
        )
    except DocumentTemplateServiceError as error:
        return _service_error(error)


def _service_error(error: DocumentTemplateServiceError):
    return error_response(error.code, error.message, error.status)
