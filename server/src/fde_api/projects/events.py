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
from fde_api.dispatch.models import DeliveryPackage, DispatchOffer
from fde_api.files.models import ProjectFile, ProjectFileVersion
from fde_api.research.models import ProjectResearchForm, ProjectResearchSubject
from fde_api.workbench.models import (
    Contract,
    Gate,
    IndustryTemplateVersion,
    ModuleCatalog,
    OperationEvent,
    Payment,
    Project,
    ProjectMember,
    ProjectModule,
    ProjectTask,
    Quote,
)
from fde_api.ontology.models import (  # V3 T-O1/T-O2/T-O3（只引 models，无环）
    OntologyChangeSet,
    OntologyRelationType,
    OntologyTerm,
)
from fde_api.workflows.models import WorkflowDefinition, WorkflowRun  # V3 T-W1/T-W2（只引 models，无环）


EventTarget: TypeAlias = (
    IndustryTemplateVersion
    | ModuleCatalog
    | User
    | Project
    | ProjectMember
    | ProjectModule
    | ProjectTask
    | Gate
    | Quote
    | Payment
    | Contract
    | ProjectResearchForm
    | ProjectResearchSubject
    | ProjectFile
    | ProjectFileVersion
    # 派单两类目标（设计 §2.5/§8.3 P0-6：交付包状态迁移与 offer 留痕都写
    # OperationEvent；不注册则 record_event 直接 TypeError）
    | DeliveryPackage
    | DispatchOffer
    # V3 T-W1：workflow 定义创建/更新/发布留痕（project_id 可空=平台模板）
    | WorkflowDefinition
    # V3 T-W3：workflow 运行生命周期留痕（created/终态/resumed）
    | WorkflowRun
    # V3 T-O1：术语治理留痕（合并保留来源的逐项事件，项目内术语）
    | OntologyTerm
    # V3 T-O2：类型注册留痕（登记/停用；全局类型 project_id 为空）
    | OntologyRelationType
    # V3 T-O3：变更集确认留痕（逐项物化结果，项目内）
    | OntologyChangeSet
)

_TARGET_TYPES = {
    IndustryTemplateVersion: "industry_template_version",
    ModuleCatalog: "module",
    User: "user",
    Project: "project",
    ProjectMember: "project_member",
    ProjectModule: "project_module",
    ProjectTask: "project_task",
    Gate: "gate",
    Quote: "quote",
    Payment: "payment",
    Contract: "contract",
    ProjectResearchForm: "project_research_form",
    ProjectResearchSubject: "project_research_subject",
    ProjectFile: "project_file",
    ProjectFileVersion: "project_file_version",
    DeliveryPackage: "delivery_package",
    DispatchOffer: "dispatch_offer",
    WorkflowDefinition: "workflow_definition",
    WorkflowRun: "workflow_run",
    OntologyTerm: "ontology_term",  # V3 T-O1
    OntologyRelationType: "ontology_relation_type",  # V3 T-O2
    OntologyChangeSet: "ontology_change_set",  # V3 T-O3
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
    if isinstance(target, (ProjectMember, ProjectModule, Gate, Quote, Payment, Contract)):
        return target.project_id
    if isinstance(target, (ProjectResearchForm, ProjectResearchSubject)):
        return target.project_id
    if isinstance(target, (ProjectFile, ProjectFileVersion)):
        return target.project_id
    if isinstance(target, DeliveryPackage):
        return target.project_id
    if isinstance(target, WorkflowDefinition):
        # 平台模板定义 project_id 为 NULL（事件仍可挂全局面）
        return target.project_id
    if isinstance(target, WorkflowRun):
        # 运行永远属于某个项目（平台模板定义也在项目上下文里实例化）
        return target.project_id
    if isinstance(target, OntologyTerm):
        # 术语永远属于某个项目（V3 T-O1 项目内治理）
        return target.project_id
    if isinstance(target, OntologyRelationType):
        # 类型可全局登记（project_id 为空）——事件挂全局面（同平台模板定义）
        return target.project_id
    if isinstance(target, OntologyChangeSet):
        # 变更集永远属于某个项目（V3 T-O3 项目内治理）
        return target.project_id
    if isinstance(target, DispatchOffer):
        # offer 只挂 package_id；project_id 经交付包反查（一次主键点查）
        return session.scalar(
            select(DeliveryPackage.project_id).where(
                DeliveryPackage.id == target.package_id
            )
        )
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
