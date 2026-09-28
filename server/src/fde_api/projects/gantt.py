from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from fde_api.auth.models import User
from fde_api.extensions import db
from fde_api.projects.permissions import project_access
from fde_api.projects.service import ProjectServiceError
from fde_api.workbench.models import (
    Project,
    ProjectMember,
    ProjectModule,
    ProjectTask,
    ProjectTaskDependency,
)


def get_project_gantt(*, actor: User, project_id: str) -> dict[str, Any]:
    session = db.session()
    try:
        project = session.scalar(
            select(Project)
            .where(Project.id == project_id)
            .options(
                selectinload(Project.members).selectinload(ProjectMember.user),
                selectinload(Project.modules).selectinload(ProjectModule.module_catalog),
                selectinload(Project.modules)
                .selectinload(ProjectModule.tasks)
                .selectinload(ProjectTask.assignee),
            )
        )
        if project is None:
            raise ProjectServiceError("project_not_found", "Project was not found.", 404)
        if not project_access(actor, project).can_view:
            raise ProjectServiceError(
                "forbidden", "You do not have access to this project.", 403
            )
        return _serialize_gantt(session, project)
    finally:
        session.close()


def _serialize_gantt(session: Session, project: Project) -> dict[str, Any]:
    modules = sorted(project.modules, key=lambda module: (module.sort_order, module.id))
    tasks = [task for module in modules for task in module.tasks]
    dependencies, incomplete = _dependency_metadata(session, tasks)
    groups = []
    active_dates = []
    for module in modules:
        module_tasks = sorted(
            module.tasks,
            key=lambda task: (task.planned_start_date, task.planned_end_date, task.id),
        )
        serialized_tasks = []
        for task in module_tasks:
            cancelled = module.status == "cancelled" or task.status == "cancelled"
            if not cancelled:
                active_dates.extend((task.planned_start_date, task.planned_end_date))
            serialized_tasks.append(
                {
                    "id": task.id,
                    "task_key": task.task_key,
                    "name": task.name,
                    "planned_start_date": task.planned_start_date.isoformat(),
                    "planned_end_date": task.planned_end_date.isoformat(),
                    "assignee": (
                        {
                            "id": task.assignee.id,
                            "display_name": task.assignee.display_name,
                            "role": task.assignee.role,
                        }
                        if task.assignee is not None
                        else None
                    ),
                    "progress": task.progress,
                    "status": task.status,
                    "cancelled": cancelled,
                    "dependency_ids": dependencies[task.id],
                    "dependency_risk": bool(incomplete[task.id]),
                    "incomplete_dependency_ids": incomplete[task.id],
                }
            )
        groups.append(
            {
                "id": module.id,
                "module_key": module.module_catalog.module_key,
                "name": module.name,
                "status": module.status,
                "cancelled": module.status == "cancelled",
                "tasks": serialized_tasks,
            }
        )
    return {
        "project_id": project.id,
        "range": {
            "start": min(active_dates).isoformat() if active_dates else None,
            "end": max(active_dates).isoformat() if active_dates else None,
        },
        "groups": groups,
    }


def _dependency_metadata(
    session: Session, tasks: list[ProjectTask]
) -> tuple[dict[str, list[str]], dict[str, list[str]]]:
    task_ids = {task.id for task in tasks}
    dependency_ids = {task.id: [] for task in tasks}
    incomplete_ids = {task.id: [] for task in tasks}
    if not task_ids:
        return dependency_ids, incomplete_ids
    dependencies = session.scalars(
        select(ProjectTaskDependency)
        .where(ProjectTaskDependency.successor_task_id.in_(task_ids))
        .options(selectinload(ProjectTaskDependency.predecessor_task))
    )
    for dependency in dependencies:
        predecessor = dependency.predecessor_task
        successor_id = dependency.successor_task_id
        dependency_ids[successor_id].append(predecessor.id)
        if predecessor.status != "completed":
            incomplete_ids[successor_id].append(predecessor.id)
    for task_id in task_ids:
        dependency_ids[task_id].sort()
        incomplete_ids[task_id].sort()
    return dependency_ids, incomplete_ids
