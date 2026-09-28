from __future__ import annotations

from flask import Blueprint, g, jsonify, request

from fde_api.auth.decorators import require_role
from fde_api.errors import error_response
from fde_api.research.template_service import (
    create_research_form,
    delete_research_definition,
    replace_research_definition,
    snapshot_research_definition,
)
from fde_api.extensions import db
from fde_api.templates.service import TemplateServiceError
from fde_api.workbench.models import IndustryTemplateVersion


template_research_blueprint = Blueprint("template_research", __name__, url_prefix="/api/v1/templates")


@template_research_blueprint.get("/<template_id>/versions/<version_id>/research-forms")
@require_role("admin", "project_lead")
def get_research_definition_route(template_id: str, version_id: str):
    session = db.session()
    try:
        definition = snapshot_research_definition(
            version_id=version_id,
            session=session,
            template_id=template_id,
            published_only=g.current_user.role != "admin",
        )
        version = session.get(IndustryTemplateVersion, version_id)
        assert version is not None
        definition["version"] = version.version
        return jsonify({"data": definition, "error": None})
    except TemplateServiceError as error:
        return _service_error(error)
    finally:
        session.close()


@template_research_blueprint.post("/<template_id>/versions/<version_id>/research-forms")
@require_role("admin")
def create_research_form_route(template_id: str, version_id: str):
    payload = _json_payload()
    if not _valid_form_payload(payload):
        return _invalid_request()
    try:
        definition = create_research_form(
            actor=g.current_user,
            template_id=template_id,
            version_id=version_id,
            expected_version=payload["version"],
            form={key: value for key, value in payload.items() if key != "version"},
        )
        return jsonify({"data": definition, "error": None}), 201
    except TemplateServiceError as error:
        return _service_error(error)


@template_research_blueprint.put("/<template_id>/versions/<version_id>/research-forms")
@require_role("admin")
def replace_research_definition_route(template_id: str, version_id: str):
    payload = _json_payload()
    if (
        not isinstance(payload, dict)
        or set(payload) != {"version", "forms"}
        or not _valid_version(payload.get("version"))
        or not isinstance(payload["forms"], list)
    ):
        return _invalid_request()
    try:
        definition = replace_research_definition(
            actor=g.current_user,
            template_id=template_id,
            version_id=version_id,
            expected_version=payload["version"],
            definition={"forms": payload["forms"]},
        )
        return jsonify({"data": definition, "error": None})
    except TemplateServiceError as error:
        return _service_error(error)


@template_research_blueprint.delete("/<template_id>/versions/<version_id>/research-forms")
@require_role("admin")
def delete_research_definition_route(template_id: str, version_id: str):
    payload = _json_payload()
    if not isinstance(payload, dict) or set(payload) != {"version"} or not _valid_version(payload.get("version")):
        return _invalid_request()
    try:
        version = delete_research_definition(
            actor=g.current_user,
            template_id=template_id,
            version_id=version_id,
            expected_version=payload["version"],
        )
        return jsonify({"data": {"version": version}, "error": None})
    except TemplateServiceError as error:
        return _service_error(error)


def _valid_form_payload(payload: object) -> bool:
    return (
        isinstance(payload, dict)
        and not (set(payload) - {"version", "id", "form_key", "name", "description", "subject_type", "module_key", "sort_order", "sections"})
        and {"version", "form_key", "name", "subject_type", "sections"} <= set(payload)
        and _valid_version(payload.get("version"))
    )


def _valid_version(value: object) -> bool:
    return type(value) is int and value > 0


def _json_payload():
    return request.get_json(silent=True) if request.is_json else None


def _invalid_request():
    return error_response("invalid_request", "The request body is invalid.", 400)


def _service_error(error: TemplateServiceError):
    return error_response(error.code, error.message, error.status, error.details)
