from __future__ import annotations

from typing import Any

from flask import Blueprint, g, jsonify, request

from fde_api.auth.decorators import require_auth, require_role
from fde_api.errors import error_response
from fde_api.modules.service import (
    ModuleServiceError,
    create_module,
    list_modules,
    update_module,
)
from fde_api.workbench.models import ModuleCatalog


modules_blueprint = Blueprint("modules", __name__, url_prefix="/api/v1/modules")


@modules_blueprint.get("")
@require_auth
def list_modules_route():
    query = _list_query()
    if query is None:
        return _invalid_request()
    page, page_size, is_active = query
    modules, total = list_modules(
        page=page, page_size=page_size, is_active=is_active
    )
    return jsonify(
        {
            "data": {
                "items": [serialize_module(module) for module in modules],
                "page": page,
                "page_size": page_size,
                "total": total,
            },
            "error": None,
        }
    )


@modules_blueprint.post("")
@require_role("admin")
def create_module_route():
    payload = _json_payload()
    if not _valid_create_payload(payload):
        return _invalid_request()
    assert payload is not None
    try:
        module = create_module(
            actor=g.current_user,
            name=payload["name"],
            description=payload.get("description", ""),
            sort_order=payload.get("sort_order", 0),
            is_active=payload.get("is_active", True),
            key=payload.get("key"),
        )
    except ModuleServiceError as error:
        return _service_error(error)
    return jsonify({"data": serialize_module(module), "error": None}), 201


@modules_blueprint.patch("/<module_id>")
@require_role("admin")
def update_module_route(module_id: str):
    payload = _json_payload()
    if not _valid_update_payload(payload):
        return _invalid_request()
    assert payload is not None
    try:
        module = update_module(
            actor=g.current_user,
            module_id=module_id,
            expected_version=payload["version"],
            name=payload.get("name"),
            description=payload.get("description"),
            sort_order=payload.get("sort_order"),
            is_active=payload.get("is_active"),
        )
    except ModuleServiceError as error:
        return _service_error(error)
    return jsonify({"data": serialize_module(module), "error": None})


def serialize_module(module: ModuleCatalog) -> dict[str, object]:
    return {
        "id": module.id,
        "key": module.module_key,
        "name": module.name,
        "description": module.description,
        "sort_order": module.sort_order,
        "is_active": module.is_active,
        "version": module.version,
    }


def _list_query() -> tuple[int, int, bool | None] | None:
    page = _positive_int(request.args.get("page", "1"))
    page_size = _positive_int(request.args.get("page_size", "20"))
    if page is None or page_size is None or page_size > 100:
        return None
    raw_active = request.args.get("active")
    is_active = {"true": True, "false": False}.get(raw_active)
    if raw_active is not None and is_active is None:
        return None
    return page, page_size, is_active


def _positive_int(value: str) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _json_payload() -> dict[str, Any] | None:
    payload = request.get_json(silent=True)
    return payload if isinstance(payload, dict) else None


def _valid_create_payload(payload: dict[str, Any] | None) -> bool:
    if payload is None or set(payload) - {
        "name", "key", "description", "sort_order", "is_active"
    }:
        return False
    return (
        isinstance(payload.get("name"), str)
        and ("key" not in payload or isinstance(payload["key"], str))
        and ("description" not in payload or isinstance(payload["description"], str))
        and ("sort_order" not in payload or type(payload["sort_order"]) is int)
        and ("is_active" not in payload or isinstance(payload["is_active"], bool))
    )


def _valid_update_payload(payload: dict[str, Any] | None) -> bool:
    if (
        not payload
        or set(payload) - {"version", "name", "description", "sort_order", "is_active"}
        or type(payload.get("version")) is not int
        or payload["version"] < 1
        or not (set(payload) - {"version"})
    ):
        return False
    return (
        ("name" not in payload or isinstance(payload["name"], str))
        and ("description" not in payload or isinstance(payload["description"], str))
        and ("sort_order" not in payload or type(payload["sort_order"]) is int)
        and ("is_active" not in payload or isinstance(payload["is_active"], bool))
    )


def _invalid_request():
    return error_response("invalid_request", "The request body is invalid.", 400)


def _service_error(error: ModuleServiceError):
    return error_response(error.code, error.message, error.status)
