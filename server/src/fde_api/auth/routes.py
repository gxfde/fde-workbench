from __future__ import annotations

from typing import Any

from flask import Blueprint, g, jsonify, request

from fde_api.auth.decorators import require_auth
from fde_api.auth.models import User
from fde_api.auth.service import (
    AuthServiceError,
    INVALID_CURRENT_PASSWORD,
    TokenPair,
    change_password as change_user_password,
    login as login_user,
    revoke_refresh_token,
    rotate_refresh_token,
    verify_current_password,
)
from fde_api.errors import error_response


auth_blueprint = Blueprint("auth", __name__, url_prefix="/api/v1/auth")


@auth_blueprint.post("/login")
def login_route():
    payload = _json_payload()
    values = _required_strings(payload, "username", "password", "device_label")
    if values is None:
        return _invalid_request()
    try:
        user, pair = login_user(*values)
    except AuthServiceError as error:
        return _service_error(error)
    return jsonify(
        {
            "data": {"user": _serialize_user(user), **_serialize_token_pair(pair)},
            "error": None,
        }
    )


@auth_blueprint.post("/refresh")
def refresh_route():
    values = _required_strings(_json_payload(), "refresh_token")
    if values is None:
        return _invalid_request()
    try:
        user, pair = rotate_refresh_token(values[0])
    except AuthServiceError as error:
        return _service_error(error)
    return jsonify(
        {
            "data": {"user": _serialize_user(user), **_serialize_token_pair(pair)},
            "error": None,
        }
    )


@auth_blueprint.post("/logout")
def logout_route():
    values = _required_strings(_json_payload(), "refresh_token")
    if values is None:
        return _invalid_request()
    revoke_refresh_token(values[0])
    return jsonify({"data": {"revoked": True}, "error": None})


@auth_blueprint.get("/me")
@require_auth
def me_route():
    return jsonify({"data": _serialize_user(g.current_user), "error": None})


@auth_blueprint.post("/verify-password")
@require_auth
def verify_password_route():
    values = _required_strings(_json_payload(), "password")
    if values is None:
        return _invalid_request()
    try:
        valid = verify_current_password(g.current_user, values[0])
    except AuthServiceError as error:
        return _service_error(error)
    if not valid:
        return error_response(*INVALID_CURRENT_PASSWORD)
    return jsonify({"data": {"valid": True}, "error": None})


@auth_blueprint.post("/change-password")
@require_auth
def change_password_route():
    values = _required_strings(
        _json_payload(), "current_password", "new_password"
    )
    if values is None:
        return _invalid_request()
    try:
        user, pair = change_user_password(g.current_user, *values)
    except AuthServiceError as error:
        return _service_error(error)
    return jsonify(
        {
            "data": {"user": _serialize_user(user), **_serialize_token_pair(pair)},
            "error": None,
        }
    )


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


def _serialize_user(user: User) -> dict[str, Any]:
    return {
        "id": user.id,
        "username": user.username,
        "display_name": user.display_name,
        "role": user.role,
        "must_change_password": user.must_change_password,
        "is_active": user.is_active,
    }


def _serialize_token_pair(pair: TokenPair) -> dict[str, str]:
    return {
        "access_token": pair.access_token,
        "refresh_token": pair.refresh_token,
        "access_expires_at": pair.access_expires_at.isoformat(),
        "refresh_expires_at": pair.refresh_expires_at.isoformat(),
    }


def _invalid_request():
    return error_response(
        "invalid_request", "The request body is missing required fields.", 400
    )


def _service_error(error: AuthServiceError):
    return error_response(error.code, error.message, error.status)
