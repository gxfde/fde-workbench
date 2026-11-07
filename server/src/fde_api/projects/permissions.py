from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import select

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


def visible_project_ids(session: Any, user: User) -> list[str]:
    """actor 可见项目 id 集——跨域列表面的可见性单一权威。

    不在 SQL 里重写第二套可见性规则；逐项目复用 project_access 判定
    （内部工作台项目量为个小集合，Python 判定的成本可忽略，换来的是
    可见性语义永远只有这一处）。
    """
    projects = session.scalars(select(Project)).all()
    return [project.id for project in projects if project_access(user, project).can_view]
