from __future__ import annotations

from typing import Any

from flask import Blueprint, g, jsonify, request

from fde_api.auth.decorators import require_role
from fde_api.errors import error_response
from fde_api.templates.service import (
    TemplateServiceError,
    copy_template_version,
    create_template,
    deactivate_template_version,
    delete_draft_version,
    get_template_version_dto,
    list_template_versions,
    publish_template_version,
    serialize_template_version,
    update_draft_version,
)


templates_blueprint = Blueprint(
    "industry_templates", __name__, url_prefix="/api/v1/industry-templates"
)


@templates_blueprint.get("")
@require_role("admin", "project_lead")
def list_templates_route():
    pagination = _pagination()
    if pagination is None:
        return _invalid_request()
    page, page_size = pagination
    version_dtos, total = list_template_versions(
        template_id=None,
        include_unpublished=g.current_user.role == "admin",
        page=page,
        page_size=page_size,
    )
    return _list_response(version_dtos, page, page_size, total)


@templates_blueprint.get("/<template_id>/versions")
@require_role("admin", "project_lead")
def list_versions_route(template_id: str):
    pagination = _pagination()
    if pagination is None:
        return _invalid_request()
    page, page_size = pagination
    version_dtos, total = list_template_versions(
        template_id=template_id,
        include_unpublished=g.current_user.role == "admin",
        page=page,
        page_size=page_size,
    )
    return _list_response(version_dtos, page, page_size, total)


@templates_blueprint.get("/versions/<version_id>")
@require_role("admin", "project_lead")
def get_version_route(version_id: str):
    try:
        dto = get_template_version_dto(
            version_id=version_id,
            include_unpublished=g.current_user.role == "admin",
        )
        return jsonify({"data": dto, "error": None})
    except TemplateServiceError as error:
        return _service_error(error)


@templates_blueprint.post("")
@require_role("admin")
def create_template_route():
    payload = _json_payload()
    if (
        payload is None
        or set(payload) - {"name", "industry_name", "description", "modules"}
        or not {"name", "industry_name", "modules"} <= set(payload)
    ):
        return _invalid_request()
    try:
        version = create_template(
            actor=g.current_user,
            name=payload["name"],
            industry_name=payload["industry_name"],
            description=payload.get("description", ""),
            modules=payload["modules"],
        )
        return jsonify({"data": serialize_template_version(version), "error": None}), 201
    except TemplateServiceError as error:
        return _service_error(error)


@templates_blueprint.patch("/versions/<version_id>")
@require_role("admin")
def update_version_route(version_id: str):
    payload = _json_payload()
    if (
        not payload
        or set(payload) - {
            "version",
            "name",
            "industry_name",
            "description",
            "modules",
        }
        or type(payload.get("version")) is not int
        or payload["version"] < 1
        or not (set(payload) - {"version"})
        or any(
            payload[field] is None
            for field in set(payload) - {"version"}
        )
    ):
        return _invalid_request()
    try:
        version = update_draft_version(
            actor=g.current_user,
            version_id=version_id,
            expected_version=payload["version"],
            name=payload.get("name"),
            industry_name=payload.get("industry_name"),
            description=payload.get("description"),
            modules=payload.get("modules"),
        )
        return jsonify({"data": serialize_template_version(version), "error": None})
    except TemplateServiceError as error:
        return _service_error(error)


@templates_blueprint.delete("/versions/<version_id>")
@require_role("admin")
def delete_version_route(version_id: str):
    expected_version = _version_action_payload()
    if expected_version is None:
        return _invalid_request()
    try:
        delete_draft_version(
            version_id=version_id, expected_version=expected_version
        )
        return "", 204
    except TemplateServiceError as error:
        return _service_error(error)


@templates_blueprint.post("/<template_id>/versions")
@require_role("admin")
def copy_version_route(template_id: str):
    if not _valid_empty_action_payload():
        return _invalid_request()
    try:
        version = copy_template_version(template_id=template_id)
        return jsonify({"data": serialize_template_version(version), "error": None}), 201
    except TemplateServiceError as error:
        return _service_error(error)


@templates_blueprint.post("/versions/<version_id>/publish")
@require_role("admin")
def publish_version_route(version_id: str):
    expected_version = _version_action_payload()
    if expected_version is None:
        return _invalid_request()
    try:
        version = publish_template_version(
            actor=g.current_user,
            version_id=version_id,
            expected_version=expected_version,
        )
        return jsonify({"data": serialize_template_version(version), "error": None})
    except TemplateServiceError as error:
        return _service_error(error)


@templates_blueprint.post("/versions/<version_id>/deactivate")
@require_role("admin")
def deactivate_version_route(version_id: str):
    expected_version = _version_action_payload()
    if expected_version is None:
        return _invalid_request()
    try:
        version = deactivate_template_version(
            actor=g.current_user,
            version_id=version_id,
            expected_version=expected_version,
        )
        return jsonify({"data": serialize_template_version(version), "error": None})
    except TemplateServiceError as error:
        return _service_error(error)


def _list_response(version_dtos, page: int, page_size: int, total: int):
    return jsonify(
        {
            "data": {
                "items": version_dtos,
                "page": page,
                "page_size": page_size,
                "total": total,
            },
            "error": None,
        }
    )


def _pagination() -> tuple[int, int] | None:
    page = _positive_int(request.args.get("page", "1"))
    page_size = _positive_int(request.args.get("page_size", "20"))
    if page is None or page_size is None or page_size > 100:
        return None
    return page, page_size


def _positive_int(value: str) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _json_payload() -> dict[str, Any] | None:
    payload = request.get_json(silent=True)
    return payload if isinstance(payload, dict) else None


def _valid_empty_action_payload() -> bool:
    if not request.get_data(cache=True):
        return True
    return request.get_json(silent=True) == {}


def _version_action_payload() -> int | None:
    payload = _json_payload()
    if (
        payload is None
        or set(payload) != {"version"}
        or type(payload["version"]) is not int
        or payload["version"] < 1
    ):
        return None
    return payload["version"]


def _invalid_request():
    return error_response("invalid_request", "The request body is invalid.", 400)


def _service_error(error: TemplateServiceError):
    return error_response(error.code, error.message, error.status, error.details)
