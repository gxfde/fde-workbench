from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select

from fde_api.auth.models import User
from fde_api.control.models import UserAIAccessGrant
from fde_api.extensions import db
from fde_api.projects.permissions import project_access
from fde_api.workbench.models import Project


ACCESS_RANK = {
    "disabled": 0,
    "assistant_read": 1,
    "project_operator": 2,
    "project_manager": 3,
    "system_operator": 4,
}
DEFAULT_ACCESS_BY_ROLE = {
    "viewer": "assistant_read",
    "fde_engineer": "project_operator",
    "project_lead": "project_manager",
    "admin": "system_operator",
}
CAPABILITY_REQUIREMENTS = {
    "workbench.write": "project_operator",
    "project.read": "assistant_read",
    "project.summarize": "assistant_read",
    "file.search": "assistant_read",
    "memo.personal.write": "project_operator",
    "research.draft.generate": "project_operator",
    "opportunity.draft.generate": "project_operator",
    "task.assigned.update": "project_operator",
    "memo.shared.write": "project_manager",
    "task.batch_assign": "project_manager",
    "project.schedule.manage": "project_manager",
    "project.members.manage": "project_manager",
    "system.health": "system_operator",
    "system.logs": "system_operator",
    "system.release": "system_operator",
    "system.database.migrate": "system_operator",
    "system.dsh.switch": "system_operator",
}


@dataclass(frozen=True, slots=True)
class AIAccessDecision:
    allowed: bool
    access_level: str
    source: str
    reason: str


def effective_ai_access(user: User) -> tuple[str, str]:
    # Administrators always retain full administration rights. Historical role
    # defaults/grants must not silently hide management controls after upgrade.
    if user.role == "admin":
        return "system_operator", "administrator"
    session = db.session()
    try:
        grant = session.scalar(select(UserAIAccessGrant).where(UserAIAccessGrant.user_id == user.id))
    finally:
        session.close()
    if grant is not None:
        return grant.access_level, "explicit"
    return DEFAULT_ACCESS_BY_ROLE.get(user.role, "disabled"), "role_default"


def capabilities_for_level(level: str) -> list[str]:
    rank = ACCESS_RANK.get(level, 0)
    return sorted(name for name, required in CAPABILITY_REQUIREMENTS.items() if rank >= ACCESS_RANK[required])


def authorize_ai_capability(*, user: User, capability: str, project: Project | None = None) -> AIAccessDecision:
    level, source = effective_ai_access(user)
    required = CAPABILITY_REQUIREMENTS.get(capability)
    if not user.is_active:
        return AIAccessDecision(False, level, source, "account_inactive")
    if required is None:
        return AIAccessDecision(False, level, source, "capability_unknown")
    if ACCESS_RANK[level] < ACCESS_RANK[required]:
        return AIAccessDecision(False, level, source, "ai_access_insufficient")
    if capability.startswith("system."):
        return AIAccessDecision(level == "system_operator", level, source, "allowed" if level == "system_operator" else "system_operator_required")
    if project is None:
        return AIAccessDecision(False, level, source, "project_required")
    access = project_access(user, project)
    if not access.can_view:
        return AIAccessDecision(False, level, source, "project_forbidden")
    if required == "project_manager" and not access.can_manage:
        return AIAccessDecision(False, level, source, "project_manage_required")
    return AIAccessDecision(True, level, source, "allowed")
