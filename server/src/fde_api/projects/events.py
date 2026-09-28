from __future__ import annotations

import re
import math
from collections.abc import Mapping
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any, TypeAlias
from uuid import UUID

import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from fde_api.auth.models import User
from fde_api.files.models import ProjectFile, ProjectFileVersion
from fde_api.research.models import ProjectResearchForm, ProjectResearchSubject
from fde_api.workbench.models import (
    IndustryTemplateVersion,
    ModuleCatalog,
    OperationEvent,
    Project,
    ProjectMember,
    ProjectModule,
    ProjectTask,
)


EventTarget: TypeAlias = (
    IndustryTemplateVersion
    | ModuleCatalog
    | User
    | Project
    | ProjectMember
    | ProjectModule
    | ProjectTask
    | ProjectResearchForm
    | ProjectResearchSubject
    | ProjectFile
    | ProjectFileVersion
)

_TARGET_TYPES = {
    IndustryTemplateVersion: "industry_template_version",
    ModuleCatalog: "module",
    User: "user",
    Project: "project",
    ProjectMember: "project_member",
    ProjectModule: "project_module",
    ProjectTask: "project_task",
    ProjectResearchForm: "project_research_form",
    ProjectResearchSubject: "project_research_subject",
    ProjectFile: "project_file",
    ProjectFileVersion: "project_file_version",
}
_SENSITIVE_KEY = re.compile(
    r"password|passwd|pwd|token|secret|credential|privatekey|apikey|"
    r"authorization|bearer|sessionkey|accesskey",
    re.IGNORECASE,
)
_UNSUPPORTED_VALUE = "[unsupported value]"
_CYCLIC_VALUE = "[cyclic value]"
_UNSUPPORTED_KEY = "[unsupported key]"
_NON_FINITE_NUMBER = "[non-finite-number]"


def record_event(
    session: Session,
    actor: User,
    event_type: str,
    target: EventTarget,
    changes: Mapping[str, Any],
) -> OperationEvent:
    """Append one safely redacted event to the caller's active transaction."""
    target_type = _TARGET_TYPES.get(type(target))
    if target_type is None:
        raise TypeError("Unsupported operation-event target")
    event = OperationEvent(
        actor_user_id=actor.id,
        project_id=_project_id_for_target(session, target),
        target_type=target_type,
        target_id=target.id,
        event_type=event_type,
        changes=_redact_changes(changes),
    )
    session.add(event)
    return event


def _project_id_for_target(session: Session, target: EventTarget) -> str | None:
    if isinstance(target, (IndustryTemplateVersion, ModuleCatalog, User)):
        return None
    if isinstance(target, Project):
        return target.id
    if isinstance(target, (ProjectMember, ProjectModule)):
        return target.project_id
    if isinstance(target, (ProjectResearchForm, ProjectResearchSubject)):
        return target.project_id
    if isinstance(target, (ProjectFile, ProjectFileVersion)):
        return target.project_id
    return session.scalar(
        select(ProjectModule.project_id).where(ProjectModule.id == target.project_module_id)
    )


def _redact_changes(changes: Mapping[str, Any]) -> dict[str, Any]:
    return _redact_mapping(changes, active_containers=set())


def _redact_mapping(
    values: Mapping[Any, Any], *, active_containers: set[int]
) -> dict[str, Any]:
    if id(values) in active_containers:
        return _CYCLIC_VALUE
    active_containers.add(id(values))
    try:
        redacted: dict[str, Any] = {}
        for raw_key, value in values.items():
            key = _normalize_key(raw_key)
            if not _is_sensitive_key(key):
                redacted[key] = _redact_value(value, active_containers=active_containers)
        return redacted
    finally:
        active_containers.remove(id(values))


def _redact_value(value: Any, *, active_containers: set[int]) -> Any:
    if isinstance(value, Enum):
        return _redact_value(value.value, active_containers=active_containers)
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Mapping):
        return _redact_mapping(value, active_containers=active_containers)
    if isinstance(value, (list, tuple, set, frozenset)):
        if id(value) in active_containers:
            return _CYCLIC_VALUE
        active_containers.add(id(value))
        try:
            normalized = [
                _redact_value(item, active_containers=active_containers)
                for item in value
            ]
            if isinstance(value, (set, frozenset)):
                normalized.sort(key=_stable_json_sort_key)
            return normalized
        finally:
            active_containers.remove(id(value))
    if type(value) is float:
        return value if math.isfinite(value) else _NON_FINITE_NUMBER
    if type(value) in {str, int, bool} or value is None:
        return value
    return _UNSUPPORTED_VALUE


def _normalize_key(key: object) -> str:
    if isinstance(key, str):
        return key
    if isinstance(key, UUID):
        return str(key)
    if isinstance(key, Decimal):
        return str(key)
    if isinstance(key, datetime):
        return key.isoformat()
    if isinstance(key, date):
        return key.isoformat()
    if isinstance(key, Enum):
        return _normalize_key(key.value)
    if type(key) in {int, float, bool}:
        return str(key)
    return _UNSUPPORTED_KEY


def _stable_json_sort_key(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _is_sensitive_key(key: str) -> bool:
    normalized = re.sub(r"[^a-z0-9]", "", key.lower())
    return bool(_SENSITIVE_KEY.search(normalized))
