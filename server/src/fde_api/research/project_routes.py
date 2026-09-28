from __future__ import annotations

from flask import Blueprint, g, jsonify, request

from fde_api.auth.decorators import require_auth
from fde_api.errors import error_response
from fde_api.research.subject_service import (
    ResearchSubjectServiceError,
    archive_subject,
    create_subject,
    get_subject_memo,
    list_subject_personal_memos,
    link_subjects,
    list_subjects,
    update_subject,
    update_subject_memo,
    update_own_subject_personal_memo,
)
from fde_api.research.imports import (
    ImportServiceError,
    authorize_subject_import,
    commit_subject_import,
    preview_subject_import,
    store_subject_import_preview,
)
from fde_api.research.form_service import (
    ResearchFormServiceError,
    confirm_form_revision,
    create_project_form,
    delete_project_form,
    get_form,
    list_forms,
    patch_form_revision,
    reject_form_revision,
    revise_form,
    update_project_form_definition,
)
from fde_api.research.export_service import ResearchExportError, get_research_export, request_research_export


project_research_blueprint = Blueprint(
    "project_research", __name__, url_prefix="/api/v1/projects"
)


@project_research_blueprint.get("/<project_id>/research/subjects")
@require_auth
def list_subjects_route(project_id: str):
    if request.args:
        return _invalid_request()
    try:
        return jsonify(
            {
                "data": {"items": list_subjects(actor=g.current_user, project_id=project_id)},
                "error": None,
            }
        )
    except ResearchSubjectServiceError as error:
        return _service_error(error)


@project_research_blueprint.post("/<project_id>/research/subjects/reorder")
@require_auth
def reorder_subjects_route(project_id: str):
    from .reorder_service import reorder_subjects
    try:
        return jsonify({"data": reorder_subjects(actor=g.current_user, project_id=project_id, payload=request.get_json(silent=True)), "error": None})
    except ResearchSubjectServiceError as error:
        return _service_error(error)


@project_research_blueprint.post("/<project_id>/research/subjects")
@require_auth
def create_subject_route(project_id: str):
    payload = _json_payload()
    if (
        not isinstance(payload, dict)
        or type(payload.get("version")) is not int
        or payload["version"] < 1
    ):
        return _invalid_request()
    try:
        subject = create_subject(
            actor=g.current_user,
            project_id=project_id,
            expected_project_version=payload["version"],
            input={key: value for key, value in payload.items() if key != "version"},
        )
        return jsonify({"data": subject, "error": None}), 201
    except ResearchSubjectServiceError as error:
        return _service_error(error)


@project_research_blueprint.post(
    "/<project_id>/research/subjects/imports/preview"
)
@require_auth
def preview_subject_import_route(project_id: str):
    if (
        request.args
        or set(request.form) != {"subject_type"}
        or set(request.files) != {"file"}
    ):
        return _invalid_request()
    upload = request.files["file"]
    if not upload.filename:
        return _invalid_request()
    try:
        authorize_subject_import(g.current_user, project_id)
        preview = preview_subject_import(
            upload.stream, upload.filename, request.form["subject_type"]
        )
        stored = store_subject_import_preview(
            actor=g.current_user, project_id=project_id, preview=preview
        )
        return jsonify({"data": stored.to_dict(), "error": None})
    except ImportServiceError as error:
        return _import_service_error(error)


@project_research_blueprint.post(
    "/<project_id>/research/subjects/imports/commit"
)
@require_auth
def commit_subject_import_route(project_id: str):
    payload = _json_payload()
    if (
        not isinstance(payload, dict)
        or set(payload) != {"preview_token", "version"}
        or not isinstance(payload.get("preview_token"), str)
        or type(payload.get("version")) is not int
        or payload["version"] < 1
    ):
        return _invalid_request()
    try:
        result = commit_subject_import(
            project_id,
            payload["preview_token"],
            payload["version"],
            g.current_user,
        )
        status = 200 if result.idempotent_replay else 201
        return jsonify({"data": result.to_dict(), "error": None}), status
    except ImportServiceError as error:
        return _import_service_error(error)
    except ResearchSubjectServiceError as error:
        return _service_error(error)


@project_research_blueprint.patch("/<project_id>/research/subjects/<subject_id>")
@require_auth
def update_subject_route(project_id: str, subject_id: str):
    payload = _json_payload()
    if (
        not isinstance(payload, dict)
        or type(payload.get("version")) is not int
        or payload["version"] < 1
        or not set(payload) - {"version"}
    ):
        return _invalid_request()
    try:
        subject = update_subject(
            actor=g.current_user,
            project_id=project_id,
            subject_id=subject_id,
            expected_version=payload["version"],
            changes={key: value for key, value in payload.items() if key != "version"},
        )
        return jsonify({"data": subject, "error": None})
    except ResearchSubjectServiceError as error:
        return _service_error(error)


@project_research_blueprint.get("/<project_id>/research/subjects/<subject_id>/memo")
@require_auth
def get_subject_memo_route(project_id: str, subject_id: str):
    if request.args:
        return _invalid_request()
    try:
        memo = get_subject_memo(
            actor=g.current_user, project_id=project_id, subject_id=subject_id
        )
        return jsonify({"data": memo, "error": None})
    except ResearchSubjectServiceError as error:
        return _service_error(error)


@project_research_blueprint.patch("/<project_id>/research/subjects/<subject_id>/memo")
@require_auth
def update_subject_memo_route(project_id: str, subject_id: str):
    payload = _json_payload()
    if (
        not isinstance(payload, dict)
        or set(payload) != {"version", "memo"}
        or type(payload.get("version")) is not int
        or payload["version"] < 1
        or not isinstance(payload.get("memo"), str)
    ):
        return _invalid_request()
    try:
        memo = update_subject_memo(
            actor=g.current_user,
            project_id=project_id,
            subject_id=subject_id,
            expected_version=payload["version"],
            memo=payload["memo"],
        )
        return jsonify({"data": memo, "error": None})
    except ResearchSubjectServiceError as error:
        return _service_error(error)


@project_research_blueprint.get("/<project_id>/research/subjects/<subject_id>/personal-memos")
@require_auth
def list_subject_personal_memos_route(project_id: str, subject_id: str):
    if request.args:
        return _invalid_request()
    try:
        result = list_subject_personal_memos(
            actor=g.current_user, project_id=project_id, subject_id=subject_id
        )
        return jsonify({"data": result, "error": None})
    except ResearchSubjectServiceError as error:
        return _service_error(error)


@project_research_blueprint.patch("/<project_id>/research/subjects/<subject_id>/personal-memo")
@require_auth
def update_own_subject_personal_memo_route(project_id: str, subject_id: str):
    payload = _json_payload()
    if (
        not isinstance(payload, dict)
        or set(payload) != {"version", "memo"}
        or type(payload.get("version")) is not int
        or payload["version"] < 0
        or not isinstance(payload.get("memo"), str)
    ):
        return _invalid_request()
    try:
        result = update_own_subject_personal_memo(
            actor=g.current_user,
            project_id=project_id,
            subject_id=subject_id,
            expected_version=payload["version"],
            memo=payload["memo"],
        )
        return jsonify({"data": result, "error": None})
    except ResearchSubjectServiceError as error:
        return _service_error(error)


@project_research_blueprint.delete("/<project_id>/research/subjects/<subject_id>")
@require_auth
def archive_subject_route(project_id: str, subject_id: str):
    payload = _json_payload()
    if (
        not isinstance(payload, dict)
        or set(payload) != {"version"}
        or type(payload.get("version")) is not int
        or payload["version"] < 1
    ):
        return _invalid_request()
    try:
        subject = archive_subject(
            actor=g.current_user,
            project_id=project_id,
            subject_id=subject_id,
            expected_version=payload["version"],
        )
        return jsonify({"data": subject, "error": None})
    except ResearchSubjectServiceError as error:
        return _service_error(error)


@project_research_blueprint.post("/<project_id>/research/subjects/<subject_id>/links")
@require_auth
def link_subjects_route(project_id: str, subject_id: str):
    payload = _json_payload()
    if (
        not isinstance(payload, dict)
        or set(payload) != {"version", "target_subject_id", "link_type"}
        or type(payload.get("version")) is not int
        or payload["version"] < 1
    ):
        return _invalid_request()
    try:
        link = link_subjects(
            actor=g.current_user,
            project_id=project_id,
            source_subject_id=subject_id,
            expected_source_version=payload["version"],
            target_subject_id=payload["target_subject_id"],
            link_type=payload["link_type"],
        )
        return jsonify({"data": link, "error": None}), 201
    except ResearchSubjectServiceError as error:
        return _service_error(error)


@project_research_blueprint.get("/<project_id>/research/forms")
@require_auth
def list_forms_route(project_id: str):
    if request.args:
        return _invalid_request()
    try:
        return jsonify({"data": {"items": list_forms(actor=g.current_user, project_id=project_id)}, "error": None})
    except ResearchFormServiceError as error:
        return _form_service_error(error)


@project_research_blueprint.post("/<project_id>/research/forms")
@require_auth
def create_project_form_route(project_id: str):
    payload = _json_payload()
    if not isinstance(payload, dict) or not isinstance(payload.get("subject_id"), str):
        return _invalid_request()
    try:
        form = create_project_form(
            actor=g.current_user,
            project_id=project_id,
            subject_id=payload["subject_id"],
            input_mapping={key: value for key, value in payload.items() if key != "subject_id"},
        )
        return jsonify({"data": form, "error": None}), 201
    except ResearchFormServiceError as error:
        return _form_service_error(error)


@project_research_blueprint.post("/<project_id>/research/forms/<form_id>/export")
@require_auth
def export_research_result_route(project_id: str, form_id: str):
    payload = _json_payload()
    if payload != {}:
        return _invalid_request()
    try:
        data, created = request_research_export(actor=g.current_user, project_id=project_id, form_id=form_id)
        return jsonify({"data": data, "error": None}), 202 if created else 200
    except ResearchExportError as error:
        return error_response(error.code, error.message, error.status)


@project_research_blueprint.get("/<project_id>/research/exports/<export_id>")
@require_auth
def get_research_export_route(project_id: str, export_id: str):
    if request.args:
        return _invalid_request()
    try:
        data = get_research_export(actor=g.current_user, project_id=project_id, export_id=export_id)
        return jsonify({"data": data, "error": None})
    except ResearchExportError as error:
        return error_response(error.code, error.message, error.status)


@project_research_blueprint.get("/<project_id>/research/forms/<form_id>")
@require_auth
def get_form_route(project_id: str, form_id: str):
    if request.args:
        return _invalid_request()
    try:
        return jsonify({"data": get_form(actor=g.current_user, project_id=project_id, form_id=form_id), "error": None})
    except ResearchFormServiceError as error:
        return _form_service_error(error)


@project_research_blueprint.patch("/<project_id>/research/forms/<form_id>")
@require_auth
def patch_form_route(project_id: str, form_id: str):
    payload = _json_payload()
    if (
        not isinstance(payload, dict)
        or set(payload) != {"version", "answers"}
        or type(payload.get("version")) is not int
        or payload["version"] < 1
        or not isinstance(payload.get("answers"), dict)
    ):
        return _invalid_request()
    try:
        return jsonify({"data": patch_form_revision(
            actor=g.current_user,
            project_id=project_id,
            form_id=form_id,
            expected_version=payload["version"],
            changes=payload["answers"],
        ), "error": None})
    except ResearchFormServiceError as error:
        return _form_service_error(error)


@project_research_blueprint.patch("/<project_id>/research/forms/<form_id>/definition")
@require_auth
def update_form_definition_route(project_id: str, form_id: str):
    payload = _json_payload()
    if (
        not isinstance(payload, dict)
        or type(payload.get("version")) is not int
        or payload["version"] < 1
    ):
        return _invalid_request()
    try:
        return jsonify({"data": update_project_form_definition(
            actor=g.current_user,
            project_id=project_id,
            form_id=form_id,
            expected_version=payload["version"],
            input_mapping={key: value for key, value in payload.items() if key != "version"},
        ), "error": None})
    except ResearchFormServiceError as error:
        return _form_service_error(error)


@project_research_blueprint.delete("/<project_id>/research/forms/<form_id>")
@require_auth
def delete_project_form_route(project_id: str, form_id: str):
    payload = _json_payload()
    if not _version_only(payload):
        return _invalid_request()
    try:
        delete_project_form(
            actor=g.current_user,
            project_id=project_id,
            form_id=form_id,
            expected_version=payload["version"],
        )
        return "", 204
    except ResearchFormServiceError as error:
        return _form_service_error(error)


@project_research_blueprint.post("/<project_id>/research/forms/<form_id>/confirm")
@require_auth
def confirm_form_route(project_id: str, form_id: str):
    payload = _json_payload()
    if not _version_only(payload):
        return _invalid_request()
    try:
        return jsonify({"data": confirm_form_revision(
            actor=g.current_user, project_id=project_id, form_id=form_id, expected_version=payload["version"]
        ), "error": None})
    except ResearchFormServiceError as error:
        return _form_service_error(error)


@project_research_blueprint.post("/<project_id>/research/forms/<form_id>/reject")
@require_auth
def reject_form_route(project_id: str, form_id: str):
    payload = _json_payload()
    if not (
        isinstance(payload, dict)
        and set(payload) == {"version", "review_comment"}
        and type(payload.get("version")) is int
        and payload["version"] > 0
        and isinstance(payload.get("review_comment"), str)
        and payload["review_comment"].strip()
    ):
        return _invalid_request()
    try:
        return jsonify({"data": reject_form_revision(
            actor=g.current_user, project_id=project_id, form_id=form_id, expected_version=payload["version"], review_comment=payload["review_comment"]
        ), "error": None})
    except ResearchFormServiceError as error:
        return _form_service_error(error)


@project_research_blueprint.post("/<project_id>/research/forms/<form_id>/revise")
@require_auth
def revise_form_route(project_id: str, form_id: str):
    payload = _json_payload()
    if not _version_only(payload):
        return _invalid_request()
    try:
        data = revise_form(
            actor=g.current_user, project_id=project_id, form_id=form_id, expected_version=payload["version"]
        )
        return jsonify({"data": data, "error": None}), 201
    except ResearchFormServiceError as error:
        return _form_service_error(error)


def _json_payload():
    return request.get_json(silent=True) if request.is_json else None


def _invalid_request():
    return error_response("invalid_request", "The request body is invalid.", 400)


def _service_error(error: ResearchSubjectServiceError):
    return error_response(error.code, error.message, error.status)


def _form_service_error(error: ResearchFormServiceError):
    return error_response(error.code, error.message, error.status, error.details)


def _import_service_error(error: ImportServiceError):
    return error_response(error.code, error.message, error.status, error.details)


def _version_only(payload) -> bool:
    return (
        isinstance(payload, dict)
        and set(payload) == {"version"}
        and type(payload.get("version")) is int
        and payload["version"] > 0
    )
