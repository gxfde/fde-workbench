from __future__ import annotations

from typing import Any

from flask import Blueprint, g, jsonify, request

from fde_api.auth.decorators import require_role
from fde_api.auth.models import InvalidRoleError, User, VALID_ROLES
from fde_api.auth.service import AuthServiceError
from fde_api.errors import error_response
from fde_api.users.service import (
    UserServiceError,
    create_user,
    get_user,
    list_users,
    reset_password,
    update_user,
)


users_blueprint = Blueprint("users", __name__, url_prefix="/api/v1/users")


@users_blueprint.get("")
@require_role("admin")
def list_users_route():
    query = _list_query()
    if query is None:
        return _invalid_request()
    page, page_size, role, active = query
    try:
        users, total = list_users(
            page=page, page_size=page_size, role=role, active=active
        )
    except InvalidRoleError:
        return _invalid_request()
    return jsonify(
        {
            "data": {
                "items": [_serialize_user(user) for user in users],
                "page": page,
                "page_size": page_size,
                "total": total,
            },
            "error": None,
        }
    )


@users_blueprint.post("")
@require_role("admin")
def create_user_route():
    payload = _json_payload()
    values = _required_strings(
        payload, "username", "display_name", "role", "temporary_password"
    )
    if values is None:
        return _invalid_request()
    try:
        user = create_user(
            actor=g.current_user,
            username=values[0],
            display_name=values[1],
            role=values[2],
            temporary_password=values[3],
        )
    except (UserServiceError, AuthServiceError) as error:
        return _service_error(error)
    except InvalidRoleError:
        return _invalid_role()
    return jsonify({"data": _serialize_user(user), "error": None}), 201


@users_blueprint.patch("/<user_id>")
@require_role("admin")
def update_user_route(user_id: str):
    payload = _json_payload()
    if not _valid_update_payload(payload):
        return _invalid_request()
    assert payload is not None
    try:
        target = get_user(user_id)
        user = update_user(
            actor=g.current_user,
            target=target,
            display_name=payload.get("display_name"),
            role=payload.get("role"),
            is_active=payload.get("is_active"),
        )
    except UserServiceError as error:
        return _service_error(error)
    except InvalidRoleError:
        return _invalid_role()
    return jsonify({"data": _serialize_user(user), "error": None})


@users_blueprint.post("/<user_id>/reset-password")
@require_role("admin")
def reset_password_route(user_id: str):
    values = _required_strings(_json_payload(), "temporary_password")
    if values is None:
        return _invalid_request()
    try:
        target = get_user(user_id)
        user = reset_password(target=target, temporary_password=values[0])
    except (UserServiceError, AuthServiceError) as error:
        return _service_error(error)
    return jsonify({"data": _serialize_user(user), "error": None})


def _list_query() -> tuple[int, int, str | None, bool | None] | None:
    page = _positive_int(request.args.get("page", "1"))
    page_size = _positive_int(request.args.get("page_size", "20"))
    if page is None or page_size is None or page_size > 100:
        return None

    role = request.args.get("role")
    if role is not None and role not in VALID_ROLES:
        return None
    raw_active = request.args.get("active")
    active = {"true": True, "false": False}.get(raw_active)
    if raw_active is not None and active is None:
        return None
    return page, page_size, role, active


def _positive_int(value: str) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _json_payload() -> dict[str, Any] | None:
    payload = request.get_json(silent=True)
    return payload if isinstance(payload, dict) else None


def _required_strings(
    payload: dict[str, Any] | None, *fields: str
) -> tuple[str, ...] | None:
    if payload is None:
        return None
    values = tuple(payload.get(field) for field in fields)
    if any(not isinstance(value, str) or not value for value in values):
        return None
    return values


def _valid_update_payload(payload: dict[str, Any] | None) -> bool:
    if not payload or set(payload) - {"display_name", "role", "is_active"}:
        return False
    if "display_name" in payload and not isinstance(payload["display_name"], str):
        return False
    if "role" in payload and not isinstance(payload["role"], str):
        return False
    return "is_active" not in payload or isinstance(payload["is_active"], bool)


def _serialize_user(user: User) -> dict[str, Any]:
    return {
        "id": user.id,
        "username": user.username,
        "display_name": user.display_name,
        "role": user.role,
        "is_active": user.is_active,
        "must_change_password": user.must_change_password,
        "created_at": user.created_at.isoformat(),
        "updated_at": user.updated_at.isoformat(),
    }


def _invalid_request():
    return error_response(
        "invalid_request", "The request is invalid.", 400
    )


def _invalid_role():
    return error_response("invalid_role", "The requested role is not supported.", 400)


def _service_error(error: UserServiceError | AuthServiceError):
    return error_response(error.code, error.message, error.status)
