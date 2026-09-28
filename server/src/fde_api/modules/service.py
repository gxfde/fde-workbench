from __future__ import annotations

import re
from typing import Any
from unicodedata import normalize

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from fde_api.auth.models import User
from fde_api.extensions import db
from fde_api.projects.events import record_event
from fde_api.workbench.models import ModuleCatalog


MODULE_NAME_MAX_LENGTH = 160
MODULE_KEY_MAX_LENGTH = 80


class ModuleServiceError(Exception):
    def __init__(self, code: str, message: str, status: int):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


def list_modules(
    *, page: int, page_size: int, is_active: bool | None
) -> tuple[list[ModuleCatalog], int]:
    session = db.session()
    try:
        filters = []
        if is_active is not None:
            filters.append(ModuleCatalog.is_active.is_(is_active))
        statement = (
            select(ModuleCatalog)
            .where(*filters)
            .order_by(ModuleCatalog.sort_order, ModuleCatalog.id)
        )
        modules = list(
            session.scalars(statement.offset((page - 1) * page_size).limit(page_size))
        )
        total = session.scalar(
            select(func.count()).select_from(ModuleCatalog).where(*filters)
        )
        return modules, int(total or 0)
    finally:
        session.close()


def create_module(
    *,
    actor: User,
    name: str,
    description: str,
    sort_order: int,
    is_active: bool,
    key: str | None = None,
) -> ModuleCatalog:
    normalized_name = _normalize_name(name)
    module_key = _normalize_key(key if key is not None else normalized_name)
    _validate_module_values(
        name=normalized_name,
        key=module_key,
        description=description,
        sort_order=sort_order,
    )

    session = db.session()
    try:
        with session.begin():
            module = ModuleCatalog(
                module_key=module_key,
                name=normalized_name,
                description=description,
                sort_order=sort_order,
                is_active=is_active,
            )
            session.add(module)
            session.flush()
            session.refresh(module)
            record_event(
                session,
                actor,
                "module_created",
                module,
                {
                    "module_key": module.module_key,
                    "name": module.name,
                    "is_active": module.is_active,
                },
            )
        return module
    except IntegrityError:
        raise _module_already_exists_error() from None
    except SQLAlchemyError:
        raise _module_creation_failed_error() from None
    finally:
        session.close()


def update_module(
    *,
    actor: User,
    module_id: str,
    expected_version: int,
    name: str | None,
    description: str | None,
    sort_order: int | None,
    is_active: bool | None,
) -> ModuleCatalog:
    if name is not None:
        name = _normalize_name(name)
        _validate_name(name)
    if description is not None and not isinstance(description, str):
        raise _invalid_request_error()
    if sort_order is not None and type(sort_order) is not int:
        raise _invalid_request_error()

    session = db.session()
    try:
        with session.begin():
            module = session.get(ModuleCatalog, module_id, with_for_update=True)
            if module is None:
                raise ModuleServiceError(
                    "module_not_found", "Module was not found.", 404
                )
            if module.version != expected_version:
                raise ModuleServiceError(
                    "stale_version",
                    "The module has been updated. Refresh and try again.",
                    409,
                )
            applied_changes: dict[str, Any] = {}
            if name is not None and name != module.name:
                applied_changes["name"] = {"from": module.name, "to": name}
                module.name = name
            if description is not None and description != module.description:
                applied_changes["description"] = {
                    "from": module.description,
                    "to": description,
                }
                module.description = description
            if sort_order is not None and sort_order != module.sort_order:
                applied_changes["sort_order"] = {
                    "from": module.sort_order,
                    "to": sort_order,
                }
                module.sort_order = sort_order
            if is_active is not None and is_active != module.is_active:
                applied_changes["is_active"] = {
                    "from": module.is_active,
                    "to": is_active,
                }
                module.is_active = is_active
            module.version += 1
            session.flush()
            session.refresh(module)
            if applied_changes:
                record_event(
                    session,
                    actor,
                    (
                        "module_deactivated"
                        if applied_changes.get("is_active", {}).get("to") is False
                        else "module_updated"
                    ),
                    module,
                    applied_changes,
                )
        return module
    except IntegrityError:
        raise _module_already_exists_error() from None
    except SQLAlchemyError:
        raise _module_update_failed_error() from None
    finally:
        session.close()


def _normalize_name(value: str) -> str:
    return normalize("NFKC", value).strip()


def _normalize_key(value: str) -> str:
    normalized = normalize("NFKC", value).strip().lower()
    return re.sub(r"_+", "_", re.sub(r"[^\w]+", "_", normalized)).strip("_")


def _validate_module_values(
    *, name: str, key: str, description: str, sort_order: int
) -> None:
    _validate_name(name)
    if not key or len(key) > MODULE_KEY_MAX_LENGTH:
        raise _invalid_request_error()
    if not isinstance(description, str) or type(sort_order) is not int:
        raise _invalid_request_error()


def _validate_name(name: str) -> None:
    if not name or len(name) > MODULE_NAME_MAX_LENGTH:
        raise _invalid_request_error()


def _invalid_request_error() -> ModuleServiceError:
    return ModuleServiceError(
        "invalid_request", "The request body is invalid.", 400
    )


def _module_already_exists_error() -> ModuleServiceError:
    return ModuleServiceError(
        "module_already_exists", "A module with this name or key already exists.", 409
    )


def _module_creation_failed_error() -> ModuleServiceError:
    return ModuleServiceError(
        "module_creation_failed", "Unable to create the module at this time.", 503
    )


def _module_update_failed_error() -> ModuleServiceError:
    return ModuleServiceError(
        "module_update_failed", "Unable to update the module at this time.", 503
    )
