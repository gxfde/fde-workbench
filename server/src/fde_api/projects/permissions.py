from __future__ import annotations

from dataclasses import dataclass

from fde_api.auth.models import User
from fde_api.auth.permissions import role_at_least
from fde_api.workbench.models import Project


@dataclass(frozen=True, slots=True)
class ProjectAccess:
    can_view: bool
    can_manage: bool
    can_update_assigned_tasks: bool


NO_PROJECT_ACCESS = ProjectAccess(False, False, False)


def project_access(user: User, project: Project) -> ProjectAccess:
    """Combine inherited system capability with explicit project scope."""
    if not user.is_active:
        return NO_PROJECT_ACCESS
    if user.role == "admin":
        return ProjectAccess(True, True, True)
    if (
        user.id == project.leader_user_id
        and role_at_least(user.role, "project_lead")
    ):
        return ProjectAccess(True, True, role_at_least(user.role, "fde_engineer"))

    member = next((item for item in project.members if item.user_id == user.id), None)
    if member is None:
        return NO_PROJECT_ACCESS
    if member.role == "viewer":
        return ProjectAccess(True, False, False)
    return ProjectAccess(
        True,
        False,
        role_at_least(user.role, "fde_engineer"),
    )
