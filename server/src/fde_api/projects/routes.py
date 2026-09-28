from __future__ import annotations

from typing import Any

from flask import Blueprint, g, jsonify, request

from fde_api.auth.decorators import require_auth, require_minimum_role
from fde_api.errors import error_response
from fde_api.projects.service import (
    PROJECT_STATUSES,
    ProjectServiceError,
    add_project_member,
    append_project_module,
    assign_project_default_tasks,
    cancel_project_module,
    create_project,
    get_project,
    list_project_members,
    list_projects,
    remove_project_member,
    update_project_member,
    update_project,
)
from fde_api.projects.gantt import get_project_gantt
from fde_api.projects.task_service import (
    TASK_STATUSES,
    TASK_UPDATE_FIELDS,
    batch_assign_project_tasks,
    create_project_task,
    get_project_task,
    list_project_tasks,
    update_project_task,
)


projects_blueprint = Blueprint("projects", __name__, url_prefix="/api/v1/projects")

CREATE_FIELDS = frozenset(
    {
        "name",
        "enterprise_name",
        "contact_name",
        "contact_phone",
        "address",
        "background",
        "notes",
        "project_code",
        "planned_start_date",
        "planned_end_date",
        "template_version_id",
        "leader_user_id",
        "module_keys",
        "creation_source",
        "project_snapshot",
    }
)
REQUIRED_CREATE_FIELDS = frozenset(
    {
        "name",
        "enterprise_name",
        "planned_start_date",
        "leader_user_id",
        "module_keys",
    }
)
UPDATE_FIELDS = frozenset(
    {
        "version",
        "name",
        "enterprise_name",
        "contact_name",
        "contact_phone",
        "address",
        "background",
        "notes",
        "project_code",
        "planned_start_date",
        "planned_end_date",
        "leader_user_id",
        "status",
    }
)
MEMBER_CREATE_FIELDS = frozenset({"user_id", "role", "version"})
MEMBER_UPDATE_FIELDS = frozenset({"role", "version"})
VERSION_ONLY_FIELDS = frozenset({"version"})
BATCH_ASSIGNMENT_MODES = frozenset({"assignee", "collaborator"})


@projects_blueprint.get("")
@require_auth
def list_projects_route():
    query = _list_query()
    if query is None:
        return _invalid_request()
    projects, total = list_projects(actor=g.current_user, query=query)
    return jsonify(
        {
            "data": {
                "items": projects,
                "page": query["page"],
                "page_size": query["page_size"],
                "total": total,
            },
            "error": None,
        }
    )


@projects_blueprint.post("")
@require_minimum_role("project_lead")
def create_project_route():
    payload = _json_payload()
    if (
        payload is None
        or set(payload) - CREATE_FIELDS
        or not REQUIRED_CREATE_FIELDS <= set(payload)
    ):
        return _invalid_request()
    try:
        project = create_project(actor=g.current_user, input=payload)
        return jsonify({"data": project, "error": None}), 201
    except ProjectServiceError as error:
        return _service_error(error)


@projects_blueprint.get("/<project_id>")
@require_auth
def get_project_route(project_id: str):
    try:
        project = get_project(actor=g.current_user, project_id=project_id)
        return jsonify({"data": project, "error": None})
    except ProjectServiceError as error:
        return _service_error(error)


@projects_blueprint.patch("/<project_id>")
@require_minimum_role("project_lead")
def update_project_route(project_id: str):
    payload = _json_payload()
    if (
        not payload
        or set(payload) - UPDATE_FIELDS
        or type(payload.get("version")) is not int
        or payload["version"] < 1
        or not set(payload) - {"version"}
        or any(
            payload[field] is None
            for field in set(payload) - {"version", "planned_end_date"}
        )
    ):
        return _invalid_request()
    try:
        project = update_project(
            actor=g.current_user,
            project_id=project_id,
            expected_version=payload["version"],
            changes={key: value for key, value in payload.items() if key != "version"},
        )
        return jsonify({"data": project, "error": None})
    except ProjectServiceError as error:
        return _service_error(error)


@projects_blueprint.get("/<project_id>/members")
@require_auth
def list_project_members_route(project_id: str):
    try:
        members, project_version = list_project_members(
            actor=g.current_user, project_id=project_id
        )
        return jsonify(
            {
                "data": {"items": members, "project_version": project_version},
                "error": None,
            }
        )
    except ProjectServiceError as error:
        return _service_error(error)


@projects_blueprint.post("/<project_id>/members")
@require_auth
def add_project_member_route(project_id: str):
    payload = _json_payload()
    if not _valid_member_payload(payload, MEMBER_CREATE_FIELDS):
        return _invalid_request()
    assert payload is not None
    try:
        member = add_project_member(
            actor=g.current_user,
            project_id=project_id,
            expected_version=payload["version"],
            user_id=payload["user_id"],
            role=payload["role"],
        )
        return jsonify({"data": member, "error": None})
    except ProjectServiceError as error:
        return _service_error(error)


@projects_blueprint.patch("/<project_id>/members/<member_identifier>")
@require_auth
def update_project_member_route(project_id: str, member_identifier: str):
    payload = _json_payload()
    if not _valid_member_payload(payload, MEMBER_UPDATE_FIELDS):
        return _invalid_request()
    assert payload is not None
    try:
        member = update_project_member(
            actor=g.current_user,
            project_id=project_id,
            member_identifier=member_identifier,
            expected_version=payload["version"],
            role=payload["role"],
        )
        return jsonify({"data": member, "error": None})
    except ProjectServiceError as error:
        return _service_error(error)


@projects_blueprint.delete("/<project_id>/members/<member_identifier>")
@require_auth
def remove_project_member_route(project_id: str, member_identifier: str):
    payload = _json_payload()
    if not _valid_member_payload(payload, VERSION_ONLY_FIELDS):
        return _invalid_request()
    assert payload is not None
    try:
        remove_project_member(
            actor=g.current_user,
            project_id=project_id,
            member_identifier=member_identifier,
            expected_version=payload["version"],
        )
        return "", 204
    except ProjectServiceError as error:
        return _service_error(error)


@projects_blueprint.post("/<project_id>/tasks/assign-defaults")
@require_auth
def assign_project_default_tasks_route(project_id: str):
    payload = _json_payload()
    if not _valid_member_payload(payload, VERSION_ONLY_FIELDS):
        return _invalid_request()
    assert payload is not None
    try:
        assignments = assign_project_default_tasks(
            actor=g.current_user,
            project_id=project_id,
            expected_version=payload["version"],
        )
        return jsonify({"data": assignments, "error": None})
    except ProjectServiceError as error:
        return _service_error(error)


@projects_blueprint.post("/<project_id>/tasks/batch-assignments")
@require_auth
def batch_assign_project_tasks_route(project_id: str):
    payload = _json_payload()
    assignments = payload.get("tasks") if payload is not None else None
    if (
        payload is None
        or set(payload) != {"member_user_id", "mode", "tasks"}
        or not isinstance(payload.get("member_user_id"), str)
        or not payload["member_user_id"].strip()
        or payload.get("mode") not in BATCH_ASSIGNMENT_MODES
        or not isinstance(assignments, list)
        or not assignments
        or len(assignments) > 200
        or any(
            not isinstance(item, dict)
            or set(item) != {"task_id", "version"}
            or not isinstance(item.get("task_id"), str)
            or not item["task_id"]
            or type(item.get("version")) is not int
            or item["version"] < 1
            for item in assignments
        )
        or len({item["task_id"] for item in assignments}) != len(assignments)
    ):
        return _invalid_request()
    try:
        result = batch_assign_project_tasks(
            actor=g.current_user,
            project_id=project_id,
            member_user_id=payload["member_user_id"],
            mode=payload["mode"],
            assignments=assignments,
        )
        return jsonify({"data": result, "error": None})
    except ProjectServiceError as error:
        return _service_error(error)


@projects_blueprint.post("/<project_id>/modules")
@require_auth
def append_project_module_route(project_id: str):
    payload = _json_payload()
    if (
        payload is None
        or set(payload) != {"module_key", "planned_start_date", "version"}
        or not isinstance(payload.get("module_key"), str)
        or not isinstance(payload.get("planned_start_date"), str)
        or type(payload.get("version")) is not int
        or payload["version"] < 1
    ):
        return _invalid_request()
    try:
        module = append_project_module(
            actor=g.current_user,
            project_id=project_id,
            module_key=payload["module_key"],
            planned_start_date=payload["planned_start_date"],
            expected_version=payload["version"],
        )
        return jsonify({"data": module, "error": None}), 201
    except ProjectServiceError as error:
        return _service_error(error)


@projects_blueprint.delete("/<project_id>/modules/<module_identifier>")
@require_auth
def cancel_project_module_route(project_id: str, module_identifier: str):
    payload = _json_payload()
    if not _valid_member_payload(payload, VERSION_ONLY_FIELDS):
        return _invalid_request()
    assert payload is not None
    try:
        module = cancel_project_module(
            actor=g.current_user,
            project_id=project_id,
            module_identifier=module_identifier,
            expected_version=payload["version"],
        )
        return jsonify({"data": module, "error": None})
    except ProjectServiceError as error:
        return _service_error(error)


@projects_blueprint.get("/<project_id>/tasks")
@require_auth
def list_project_tasks_route(project_id: str):
    if set(request.args) - {"status", "module_key", "assignee_user_id"}:
        return _invalid_request()
    status = _query_text("status")
    if status is not None and status not in TASK_STATUSES:
        return _invalid_request()
    try:
        tasks = list_project_tasks(
            actor=g.current_user,
            project_id=project_id,
            query={
                "status": status,
                "module_key": _query_text("module_key"),
                "assignee_user_id": _query_text("assignee_user_id"),
            },
        )
        return jsonify({"data": {"items": tasks}, "error": None})
    except ProjectServiceError as error:
        return _service_error(error)


@projects_blueprint.get("/<project_id>/gantt")
@require_auth
def get_project_gantt_route(project_id: str):
    try:
        return jsonify(
            {"data": get_project_gantt(actor=g.current_user, project_id=project_id), "error": None}
        )
    except ProjectServiceError as error:
        return _service_error(error)


@projects_blueprint.get("/<project_id>/tasks/<task_id>")
@require_auth
def get_project_task_route(project_id: str, task_id: str):
    try:
        task = get_project_task(
            actor=g.current_user, project_id=project_id, task_id=task_id
        )
        return jsonify({"data": task, "error": None})
    except ProjectServiceError as error:
        return _service_error(error)


@projects_blueprint.patch("/<project_id>/tasks/<task_id>")
@require_auth
def update_project_task_route(project_id: str, task_id: str):
    payload = _json_payload()
    if (
        not payload
        or set(payload) - (TASK_UPDATE_FIELDS | {"version"})
        or type(payload.get("version")) is not int
        or payload["version"] < 1
        or not set(payload) - {"version"}
    ):
        return _invalid_request()
    try:
        task = update_project_task(
            actor=g.current_user,
            project_id=project_id,
            task_id=task_id,
            expected_version=payload["version"],
            changes={key: value for key, value in payload.items() if key != "version"},
        )
        return jsonify({"data": task, "error": None})
    except ProjectServiceError as error:
        return _service_error(error)


@projects_blueprint.post("/<project_id>/modules/<module_identifier>/tasks")
@require_auth
def create_project_task_route(project_id: str, module_identifier: str):
    payload = _json_payload()
    if (
        not payload
        or set(payload) - {
            "name",
            "description",
            "duration_days",
            "planned_start_date",
            "assignee_user_id",
            "collaborator_user_ids",
            "dependency_ids",
        }
        or not isinstance(payload.get("name"), str)
        or type(payload.get("duration_days")) is not int
        or payload["duration_days"] < 1
    ):
        return _invalid_request()
    try:
        task = create_project_task(
            actor=g.current_user,
            project_id=project_id,
            module_identifier=module_identifier,
            input=payload,
        )
        return jsonify({"data": task, "error": None}), 201
    except ProjectServiceError as error:
        return _service_error(error)


def _list_query() -> dict[str, Any] | None:
    if set(request.args) - {
        "search",
        "status",
        "leader_user_id",
        "industry",
        "module_key",
        "page",
        "page_size",
    }:
        return None
    page = _positive_int(request.args.get("page", "1"))
    page_size = _positive_int(request.args.get("page_size", "20"))
    status = request.args.get("status")
    if (
        page is None
        or page_size is None
        or page_size > 100
        or (status is not None and status not in PROJECT_STATUSES)
    ):
        return None
    return {
        "search": _query_text("search"),
        "status": status,
        "leader_user_id": _query_text("leader_user_id"),
        "industry": _query_text("industry"),
        "module_key": _query_text("module_key"),
        "page": page,
        "page_size": page_size,
    }


def _query_text(name: str) -> str | None:
    value = request.args.get(name)
    if value is None:
        return None
    value = value.strip()
    return value or None


def _positive_int(value: str) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _json_payload() -> dict[str, Any] | None:
    payload = request.get_json(silent=True)
    return payload if isinstance(payload, dict) else None


def _valid_member_payload(
    payload: dict[str, Any] | None, fields: frozenset[str]
) -> bool:
    return (
        payload is not None
        and set(payload) == fields
        and type(payload.get("version")) is int
        and payload["version"] > 0
        and ("user_id" not in fields or isinstance(payload.get("user_id"), str))
        and ("role" not in fields or isinstance(payload.get("role"), str))
    )


def _invalid_request():
    return error_response("invalid_request", "The request body is invalid.", 400)


def _service_error(error: ProjectServiceError):
    return error_response(error.code, error.message, error.status)
