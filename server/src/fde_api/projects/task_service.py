from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime, timedelta
from typing import Any, TypedDict
from unicodedata import normalize

from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session, selectinload

from fde_api.auth.models import User
from fde_api.auth.permissions import role_at_least
from fde_api.extensions import db
from fde_api.projects.events import record_event
from fde_api.projects.permissions import project_access
from fde_api.projects.service import ProjectServiceError
from fde_api.workbench.models import (
    ModuleCatalog,
    Project,
    ProjectMember,
    ProjectModule,
    ProjectTask,
    ProjectTaskCollaborator,
    ProjectTaskDependency,
)
from fde_api.workbench.scheduling import (
    ScheduleTask,
    ScheduledTask,
    SchedulingError,
    add_workdays,
    normalize_workday,
    reschedule_descendants,
    validate_acyclic,
)


TASK_STATUSES = frozenset(
    {"not_started", "in_progress", "blocked", "completed", "cancelled"}
)
TASK_EXECUTION_FIELDS = frozenset({"status", "progress", "blocked_reason"})
TASK_MANAGER_FIELDS = frozenset(
    {
        "planned_start_date",
        "planned_end_date",
        "duration_days",
        "assignee_user_id",
        "collaborator_user_ids",
        "dependency_ids",
    }
)
TASK_DESCRIPTION_FIELD = "description"
TASK_UPDATE_FIELDS = (
    TASK_EXECUTION_FIELDS | TASK_MANAGER_FIELDS | {TASK_DESCRIPTION_FIELD}
)


class TaskListQuery(TypedDict, total=False):
    status: str | None
    module_key: str | None
    assignee_user_id: str | None


class BatchTaskAssignment(TypedDict):
    task_id: str
    version: int


def list_project_tasks(
    *, actor: User, project_id: str, query: TaskListQuery
) -> list[dict[str, Any]]:
    session = db.session()
    try:
        project = _load_project(session, project_id)
        _require_project_view(actor, project)
        filters = [ProjectModule.project_id == project.id]
        if query.get("status"):
            filters.append(ProjectTask.status == query["status"])
        if query.get("module_key"):
            filters.append(
                ProjectModule.module_catalog.has(module_key=query["module_key"])
            )
        if query.get("assignee_user_id"):
            filters.append(
                ProjectTask.assignee_user_id == query["assignee_user_id"]
            )
        tasks = list(
            session.scalars(
                select(ProjectTask)
                .join(ProjectModule)
                .where(*filters)
                .options(
                    selectinload(ProjectTask.project_module).selectinload(
                        ProjectModule.module_catalog
                    ),
                    selectinload(ProjectTask.assignee),
                    selectinload(ProjectTask.collaborators),
                )
                .order_by(
                    ProjectModule.sort_order,
                    ProjectTask.planned_start_date,
                    ProjectTask.planned_end_date,
                    ProjectTask.id,
                )
            )
        )
        return _serialize_tasks(session, tasks)
    finally:
        session.close()


def get_project_task(
    *, actor: User, project_id: str, task_id: str
) -> dict[str, Any]:
    session = db.session()
    try:
        project = _load_project(session, project_id)
        _require_project_view(actor, project)
        task = _load_task(session, project.id, task_id)
        if task is None:
            raise _task_not_found_error()
        return _serialize_tasks(session, [task])[0]
    finally:
        session.close()


def batch_assign_project_tasks(
    *,
    actor: User,
    project_id: str,
    member_user_id: str,
    mode: str,
    assignments: Sequence[BatchTaskAssignment],
) -> dict[str, Any]:
    """Assign one project member to several tasks in one atomic transaction."""
    if mode not in {"assignee", "collaborator"} or not assignments:
        raise _invalid_request_error()
    expected_versions = {item["task_id"]: item["version"] for item in assignments}
    if len(expected_versions) != len(assignments):
        raise _invalid_request_error()

    session = db.session()
    try:
        with session.begin():
            return batch_assign_project_tasks_in_session(
                session=session,
                actor=actor,
                project_id=project_id,
                member_user_id=member_user_id,
                mode=mode,
                assignments=assignments,
            )
    except ProjectServiceError:
        raise
    except IntegrityError:
        raise ProjectServiceError(
            "project_task_conflict",
            "The tasks could not be assigned due to a conflict.",
            409,
        ) from None
    except SQLAlchemyError:
        raise ProjectServiceError(
            "project_task_update_failed",
            "Unable to assign tasks at this time.",
            503,
        ) from None
    finally:
        session.close()


def batch_assign_project_tasks_in_session(
    *,
    session: Session,
    actor: User,
    project_id: str,
    member_user_id: str,
    mode: str,
    assignments: Sequence[BatchTaskAssignment],
) -> dict[str, Any]:
    """Run the same batch assignment inside a caller-owned transaction."""
    if mode not in {"assignee", "collaborator"} or not assignments:
        raise _invalid_request_error()
    expected_versions = {item["task_id"]: item["version"] for item in assignments}
    if len(expected_versions) != len(assignments):
        raise _invalid_request_error()

    project = _load_project(session, project_id, for_update=True)
    access = _require_project_view(actor, project)
    if not access.can_manage:
        raise _forbidden_error()
    _validate_task_people(
        project,
        assignee_id=member_user_id,
        collaborator_ids=[],
    )

    tasks = list(
        session.scalars(
            select(ProjectTask)
            .join(ProjectModule)
            .where(
                ProjectModule.project_id == project.id,
                ProjectTask.id.in_(expected_versions),
            )
            .options(
                selectinload(ProjectTask.project_module).selectinload(
                    ProjectModule.module_catalog
                ),
                selectinload(ProjectTask.assignee),
                selectinload(ProjectTask.collaborators),
            )
            .with_for_update()
        )
    )
    if len(tasks) != len(expected_versions):
        raise _task_not_found_error()
    if any(task.status == "cancelled" for task in tasks):
        raise ProjectServiceError(
            "task_cancelled",
            "Cancelled tasks cannot be assigned.",
            409,
        )
    if any(task.version != expected_versions[task.id] for task in tasks):
        raise ProjectServiceError(
            "stale_version",
            "One or more tasks have been updated. Refresh and try again.",
            409,
        )

    updated: list[ProjectTask] = []
    for task in tasks:
        collaborator_ids = {
            collaborator.user_id for collaborator in task.collaborators
        }
        changed = False
        if mode == "assignee":
            if task.assignee_user_id != member_user_id:
                task.assignee_user_id = member_user_id
                changed = True
            duplicate = next(
                (
                    collaborator
                    for collaborator in task.collaborators
                    if collaborator.user_id == member_user_id
                ),
                None,
            )
            if duplicate is not None:
                session.delete(duplicate)
                changed = True
        elif task.assignee_user_id != member_user_id and member_user_id not in collaborator_ids:
            session.add(
                ProjectTaskCollaborator(
                    task_id=task.id,
                    user_id=member_user_id,
                )
            )
            changed = True

        if not changed:
            continue
        task.version += 1
        updated.append(task)
        record_event(
            session,
            actor,
            "project_task_batch_assigned",
            task,
            {
                "mode": mode,
                "member_user_id": member_user_id,
            },
        )

    session.flush()
    for task in updated:
        session.expire(task, ["assignee", "collaborators"])
    saved = [
        _load_task(session, project.id, task.id)
        for task in updated
    ]
    serialized = _serialize_tasks(
        session,
        [task for task in saved if task is not None],
    )
    return {
        "updated_count": len(serialized),
        "skipped_count": len(assignments) - len(serialized),
        "tasks": serialized,
    }


def update_project_task(
    *,
    actor: User,
    project_id: str,
    task_id: str,
    expected_version: int,
    changes: Mapping[str, Any],
) -> dict[str, Any]:
    if not changes or set(changes) - TASK_UPDATE_FIELDS:
        raise _invalid_request_error()
    session = db.session()
    try:
        with session.begin():
            project = _load_project(
                session,
                project_id,
                for_update=bool(
                    {"assignee_user_id", "collaborator_user_ids"} & set(changes)
                ),
            )
            access = _require_project_view(actor, project)
            task = _load_task(session, project.id, task_id)
            if task is None:
                raise _task_not_found_error()
            if task.status == "cancelled":
                raise ProjectServiceError(
                    "task_cancelled",
                    "Cancelled tasks cannot be updated.",
                    409,
                )
            is_manager = access.can_manage
            if not is_manager:
                if (
                    not access.can_update_assigned_tasks
                    or set(changes) - TASK_EXECUTION_FIELDS
                    or (
                        task.assignee_user_id != actor.id
                        and actor.id
                        not in {
                            collaborator.user_id
                            for collaborator in task.collaborators
                        }
                    )
                ):
                    raise _forbidden_error()

            scalar_values, event_changes = _normalized_scalar_values(task, changes)
            assignee_id = (
                changes["assignee_user_id"]
                if "assignee_user_id" in changes
                else task.assignee_user_id
            )
            collaborator_ids = (
                _identifier_list(changes["collaborator_user_ids"])
                if "collaborator_user_ids" in changes
                else sorted(
                    collaborator.user_id for collaborator in task.collaborators
                )
            )
            if is_manager and (
                "assignee_user_id" in changes
                or "collaborator_user_ids" in changes
            ):
                _validate_task_people(
                    project,
                    assignee_id=assignee_id,
                    collaborator_ids=collaborator_ids,
                )
                event_changes.update(
                    {
                        "assignee_user_id": assignee_id,
                        "collaborator_user_ids": collaborator_ids,
                    }
                )

            dependency_ids = None
            if "dependency_ids" in changes:
                dependency_ids = _identifier_list(changes["dependency_ids"])
                _validate_dependencies(
                    session,
                    project_id=project.id,
                    task=task,
                    dependency_ids=dependency_ids,
                )
                event_changes["dependency_ids"] = dependency_ids

            statement = (
                update(ProjectTask)
                .where(
                    ProjectTask.id == task.id,
                    ProjectTask.version == expected_version,
                )
                .values(
                    **scalar_values,
                    version=ProjectTask.version + 1,
                )
            )
            result = session.execute(
                statement, execution_options={"synchronize_session": False}
            )
            if result.rowcount != 1:
                raise ProjectServiceError(
                    "stale_version",
                    "The task has been updated. Refresh and try again.",
                    409,
                )

            if "collaborator_user_ids" in changes:
                session.execute(
                    delete(ProjectTaskCollaborator).where(
                        ProjectTaskCollaborator.task_id == task.id
                    )
                )
                session.add_all(
                    ProjectTaskCollaborator(task_id=task.id, user_id=user_id)
                    for user_id in collaborator_ids
                )
            if dependency_ids is not None:
                session.execute(
                    delete(ProjectTaskDependency).where(
                        ProjectTaskDependency.successor_task_id == task.id
                    )
                )
                session.add_all(
                    ProjectTaskDependency(
                        predecessor_task_id=predecessor_id,
                        successor_task_id=task.id,
                    )
                    for predecessor_id in dependency_ids
                )
            rescheduled_task_ids: list[str] = []
            if (
                {"planned_start_date", "planned_end_date", "duration_days"}
                & set(changes)
                or dependency_ids is not None
            ):
                rescheduled_task_ids = _reschedule_dependents(
                    session,
                    project_id=project.id,
                    changed_task_id=task.id,
                    dependency_changed=dependency_ids is not None,
                )
                if rescheduled_task_ids:
                    event_changes["rescheduled_task_ids"] = rescheduled_task_ids
            record_event(
                session,
                actor,
                "project_task_updated",
                task,
                event_changes,
            )
            session.flush()
            session.expire_all()
            saved = _load_task(session, project.id, task.id)
            assert saved is not None
            return _serialize_tasks(session, [saved])[0]
    except ProjectServiceError:
        raise
    except SchedulingError as error:
        raise ProjectServiceError(error.code, error.message, 400) from None
    except IntegrityError:
        raise ProjectServiceError(
            "project_task_conflict",
            "The task could not be updated due to a conflict.",
            409,
        ) from None
    except SQLAlchemyError:
        raise ProjectServiceError(
            "project_task_update_failed",
            "Unable to update the task at this time.",
            503,
        ) from None
    except Exception:
        raise ProjectServiceError(
            "project_task_update_failed",
            "Unable to update the task at this time.",
            503,
        ) from None
    finally:
        session.close()


def create_project_task(
    *,
    actor: User,
    project_id: str,
    module_identifier: str,
    input: Mapping[str, Any],
) -> dict[str, Any]:
    """Create a manually-added task inside a project module.

    Project leads and admins may add a task with a name, description, duration and
    optional assignee / collaborators / dependencies. The duration must be >= 1 and
    every assigned person must be an active working project member.
    """
    values = _normalize_create_task_input(input)
    session = db.session()
    try:
        with session.begin():
            project = _load_project(session, project_id, for_update=True)
            access = _require_project_view(actor, project)
            if not access.can_manage:
                raise _forbidden_error()
            module = session.scalar(
                select(ProjectModule)
                .join(ModuleCatalog)
                .where(
                    ProjectModule.project_id == project.id,
                    or_(
                        ProjectModule.id == module_identifier,
                        ModuleCatalog.module_key == module_identifier,
                    ),
                )
                .options(selectinload(ProjectModule.module_catalog))
                .with_for_update()
            )
            if module is None:
                raise ProjectServiceError(
                    "project_module_not_found",
                    "The project module was not found.",
                    404,
                )
            if module.status == "cancelled":
                raise ProjectServiceError(
                    "project_module_cancelled",
                    "Tasks cannot be added to a cancelled module.",
                    409,
                )

            assignee_id = values["assignee_user_id"]
            collaborator_ids = values["collaborator_user_ids"]
            _validate_task_people(
                project, assignee_id=assignee_id, collaborator_ids=collaborator_ids
            )

            task_key = _unique_task_key(session, module.id, values["name"])
            sort_order = _next_task_sort_order(session, module.id)
            start = normalize_workday(
                values.get("planned_start_date")
                or module.planned_start_date
                or project.planned_start_date
            )
            end = add_workdays(start, values["duration_days"])
            task = ProjectTask(
                project_module_id=module.id,
                task_key=task_key,
                name=values["name"],
                description=values["description"],
                status="not_started",
                planned_start_date=start,
                planned_end_date=end,
                duration_days=values["duration_days"],
                default_assignee_role=None,
                assignee_user_id=assignee_id,
                progress=0,
                blocked_reason="",
                sort_order=sort_order,
            )
            session.add(task)
            session.flush()

            if collaborator_ids:
                session.add_all(
                    ProjectTaskCollaborator(task_id=task.id, user_id=user_id)
                    for user_id in collaborator_ids
                )
            dependency_ids = values["dependency_ids"]
            if dependency_ids:
                _validate_dependencies(
                    session, project_id=project.id, task=task, dependency_ids=dependency_ids
                )
                session.add_all(
                    ProjectTaskDependency(
                        predecessor_task_id=predecessor_id, successor_task_id=task.id
                    )
                    for predecessor_id in dependency_ids
                )
            if module.planned_start_date is None or start < module.planned_start_date:
                module.planned_start_date = start
            if module.planned_end_date is None or end > module.planned_end_date:
                module.planned_end_date = end
            project.version += 1
            record_event(
                session,
                actor,
                "project_task_created",
                task,
                {
                    "task_key": task_key,
                    "name": values["name"],
                    "module_key": module.module_catalog.module_key,
                    "duration_days": values["duration_days"],
                    "assignee_user_id": assignee_id,
                    "collaborator_user_ids": collaborator_ids,
                    "dependency_ids": dependency_ids,
                },
            )
            session.flush()
            session.expire_all()
            saved = _load_task(session, project.id, task.id)
            assert saved is not None
            return _serialize_tasks(session, [saved])[0]
    except ProjectServiceError:
        raise
    except SchedulingError as error:
        raise ProjectServiceError(error.code, error.message, 400) from None
    except IntegrityError:
        raise ProjectServiceError(
            "project_task_conflict",
            "The task could not be created due to a conflict.",
            409,
        ) from None
    except SQLAlchemyError:
        raise ProjectServiceError(
            "project_task_create_failed",
            "Unable to create the task at this time.",
            503,
        ) from None
    finally:
        session.close()


def _normalize_create_task_input(input: Mapping[str, Any]) -> dict[str, Any]:
    name = input.get("name")
    if not isinstance(name, str) or not name.strip():
        raise _invalid_request_error()
    normalized_name = normalize("NFKC", name).strip()
    if len(normalized_name) > 200:
        raise _invalid_request_error()
    description = input.get("description", "")
    if not isinstance(description, str):
        raise _invalid_request_error()
    normalized_description = normalize("NFKC", description).strip()
    if len(normalized_description) > 2000:
        raise _invalid_request_error()
    duration = input.get("duration_days")
    if type(duration) is not int or duration < 1:
        raise _invalid_request_error()
    assignee_id = input.get("assignee_user_id")
    if assignee_id is not None and not isinstance(assignee_id, str):
        raise _invalid_request_error()
    collaborator_ids = (
        _identifier_list(input["collaborator_user_ids"])
        if "collaborator_user_ids" in input
        else []
    )
    dependency_ids = (
        _identifier_list(input["dependency_ids"])
        if "dependency_ids" in input
        else []
    )
    planned_start_date = input.get("planned_start_date")
    if planned_start_date is not None:
        if not isinstance(planned_start_date, str):
            raise _invalid_request_error()
        try:
            normalize_workday(date.fromisoformat(planned_start_date))
        except ValueError:
            raise _invalid_request_error() from None
    return {
        "name": normalized_name,
        "description": normalized_description,
        "duration_days": duration,
        "assignee_user_id": assignee_id,
        "collaborator_user_ids": collaborator_ids,
        "dependency_ids": dependency_ids,
        "planned_start_date": planned_start_date,
    }


def _unique_task_key(session: Session, module_id: str, name: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "_", normalize("NFKC", name).lower()).strip("_") or "task"
    existing_count = int(
        session.scalar(
            select(func.count())
            .select_from(ProjectTask)
            .where(ProjectTask.project_module_id == module_id)
        )
        or 0
    )
    candidate = base if existing_count == 0 else f"{base}_{existing_count + 1}"
    return candidate[:100]


def _next_task_sort_order(session: Session, module_id: str) -> int:
    latest = session.scalar(
        select(func.coalesce(func.max(ProjectTask.sort_order), 0)).where(
            ProjectTask.project_module_id == module_id
        )
    )
    return (int(latest or 0)) + 10


def _normalized_scalar_values(
    task: ProjectTask, changes: Mapping[str, Any]
) -> tuple[dict[str, Any], dict[str, Any]]:
    status = task.status
    progress = task.progress
    blocked_reason = task.blocked_reason
    completed_at = task.completed_at
    description = task.description

    if "status" in changes:
        if not isinstance(changes["status"], str) or changes["status"] not in TASK_STATUSES:
            raise _invalid_task_state_error()
        status = changes["status"]
    if "progress" in changes:
        value = changes["progress"]
        if type(value) is not int or value < 0 or value > 100:
            raise _invalid_task_state_error()
        progress = value
        if "status" not in changes:
            status = (
                "not_started"
                if progress == 0
                else "completed"
                if progress == 100
                else "in_progress"
            )
    if task.status == "cancelled" and status != "cancelled":
        raise _invalid_task_state_error()

    reason_supplied = "blocked_reason" in changes
    if reason_supplied:
        if not isinstance(changes["blocked_reason"], str):
            raise _invalid_task_state_error()
        blocked_reason = normalize("NFKC", changes["blocked_reason"]).strip()
    if reason_supplied and status != "blocked" and blocked_reason:
        raise _invalid_task_state_error()

    if status == "not_started":
        if "progress" in changes and progress != 0:
            raise _invalid_task_state_error()
        progress = 0
        blocked_reason = ""
        completed_at = None
    elif status == "in_progress":
        if progress < 1 or progress > 99:
            raise _invalid_task_state_error()
        if reason_supplied and blocked_reason:
            raise _invalid_task_state_error()
        blocked_reason = ""
        completed_at = None
    elif status == "blocked":
        if "progress" in changes and progress != task.progress:
            raise _invalid_task_state_error()
        progress = task.progress
        if not blocked_reason:
            raise _invalid_task_state_error()
        completed_at = None
    elif status == "completed":
        progress = 100
        blocked_reason = ""
        completed_at = task.completed_at or datetime.now(UTC)
    else:
        if "progress" in changes and progress != task.progress:
            raise _invalid_task_state_error()
        progress = task.progress
        completed_at = task.completed_at

    if "description" in changes:
        if not isinstance(changes["description"], str):
            raise _invalid_request_error()
        description = normalize("NFKC", changes["description"]).strip()
        if len(description) > 2000:
            raise _invalid_request_error()

    planned_start = task.planned_start_date
    planned_end = task.planned_end_date
    duration = task.duration_days
    try:
        if "planned_start_date" in changes:
            planned_start = normalize_workday(
                _date_value(changes["planned_start_date"])
            )
        if "duration_days" in changes:
            duration_value = changes["duration_days"]
            if type(duration_value) is not int or duration_value < 1:
                raise ValueError
            duration = duration_value
        calculated_end = add_workdays(planned_start, duration)
        if "planned_end_date" in changes:
            submitted_end = _date_value(changes["planned_end_date"])
            if submitted_end.weekday() >= 5 or submitted_end != calculated_end:
                raise ValueError
            planned_end = submitted_end
        elif "planned_start_date" in changes or "duration_days" in changes:
            planned_end = calculated_end
    except (TypeError, ValueError):
        raise _invalid_request_error() from None
    if planned_end < planned_start:
        raise _invalid_request_error()

    scalar_values = {
        "status": status,
        "progress": progress,
        "blocked_reason": blocked_reason,
        "completed_at": completed_at,
        "description": description,
        "planned_start_date": planned_start,
        "planned_end_date": planned_end,
        "duration_days": duration,
        "assignee_user_id": (
            changes["assignee_user_id"]
            if "assignee_user_id" in changes
            else task.assignee_user_id
        ),
    }
    event_changes = {
        key: _json_value(value)
        for key, value in scalar_values.items()
        if key
        in {
            "status",
            "progress",
            "blocked_reason",
            "completed_at",
            "description",
            "planned_start_date",
            "planned_end_date",
            "duration_days",
        }
        and (
            key in changes
            or key in {"status", "blocked_reason", "completed_at"}
            and ("status" in changes or "progress" in changes)
        )
    }
    return scalar_values, event_changes


def _validate_task_people(
    project: Project, *, assignee_id: object, collaborator_ids: list[str]
) -> None:
    if assignee_id is not None and not isinstance(assignee_id, str):
        raise _invalid_request_error()
    working_ids = {
        member.user_id
        for member in project.members
        if member.role == "member"
        and member.user.is_active
        and role_at_least(member.user.role, "fde_engineer")
    }
    requested = set(collaborator_ids)
    if assignee_id is not None:
        requested.add(assignee_id)
    if requested - working_ids:
        raise ProjectServiceError(
            "invalid_task_member",
            "Task assignees and collaborators must be active working project members.",
            400,
        )
    if assignee_id is not None and assignee_id in collaborator_ids:
        raise ProjectServiceError(
            "invalid_task_assignment",
            "The assignee cannot also be a task collaborator.",
            400,
        )


def _validate_dependencies(
    session: Session,
    *,
    project_id: str,
    task: ProjectTask,
    dependency_ids: list[str],
) -> None:
    if task.id in dependency_ids:
        raise ProjectServiceError(
            "cyclic_dependency", "Task dependency cycle detected", 400
        )
    project_tasks = list(
        session.scalars(
            select(ProjectTask)
            .join(ProjectModule)
            .where(ProjectModule.project_id == project_id)
        )
    )
    tasks_by_id = {item.id: item for item in project_tasks}
    if set(dependency_ids) - tasks_by_id.keys():
        raise ProjectServiceError(
            "invalid_task_dependency",
            "Task dependencies must belong to the same project.",
            400,
        )
    task_ids = set(tasks_by_id)
    dependency_keys = {task_id: [] for task_id in task_ids}
    for edge in session.scalars(
        select(ProjectTaskDependency).where(
            ProjectTaskDependency.predecessor_task_id.in_(task_ids),
            ProjectTaskDependency.successor_task_id.in_(task_ids),
        )
    ):
        if edge.successor_task_id != task.id:
            dependency_keys[edge.successor_task_id].append(
                edge.predecessor_task_id
            )
    dependency_keys[task.id] = dependency_ids
    validate_acyclic(
        ScheduleTask(
            key=item.id,
            duration_days=item.duration_days,
            dependency_keys=tuple(sorted(dependency_keys[item.id])),
        )
        for item in project_tasks
    )


def _reschedule_dependents(
    session: Session,
    *,
    project_id: str,
    changed_task_id: str,
    dependency_changed: bool,
) -> list[str]:
    session.flush()
    session.expire_all()
    tasks = list(
        session.scalars(
            select(ProjectTask)
            .join(ProjectModule)
            .where(ProjectModule.project_id == project_id)
            .with_for_update()
        )
    )
    tasks_by_id = {task.id: task for task in tasks}
    task_ids = set(tasks_by_id)
    dependency_ids = {task_id: [] for task_id in task_ids}
    for edge in session.scalars(
        select(ProjectTaskDependency).where(
            ProjectTaskDependency.predecessor_task_id.in_(task_ids),
            ProjectTaskDependency.successor_task_id.in_(task_ids),
        )
    ):
        dependency_ids[edge.successor_task_id].append(edge.predecessor_task_id)

    changed = tasks_by_id[changed_task_id]
    if dependency_changed and dependency_ids[changed.id]:
        latest_end = max(
            tasks_by_id[predecessor_id].planned_end_date
            for predecessor_id in dependency_ids[changed.id]
        )
        changed.planned_start_date = normalize_workday(
            latest_end + timedelta(days=1)
        )
        changed.planned_end_date = add_workdays(
            changed.planned_start_date, changed.duration_days
        )

    definitions = [
        ScheduleTask(
            key=task.id,
            duration_days=task.duration_days,
            dependency_keys=tuple(sorted(dependency_ids[task.id])),
        )
        for task in tasks
    ]
    existing = {
        task.id: ScheduledTask(
            key=task.id,
            start_date=task.planned_start_date,
            end_date=task.planned_end_date,
        )
        for task in tasks
    }
    updated = reschedule_descendants(
        existing, definitions, changed_keys={changed_task_id}
    )
    rescheduled_ids: list[str] = []
    affected_module_ids = {changed.project_module_id}
    for task_id, scheduled in updated.items():
        if task_id == changed_task_id:
            continue
        task = tasks_by_id[task_id]
        if task.status == "cancelled" or (
            task.planned_start_date == scheduled.start_date
            and task.planned_end_date == scheduled.end_date
        ):
            continue
        task.planned_start_date = scheduled.start_date
        task.planned_end_date = scheduled.end_date
        task.version += 1
        rescheduled_ids.append(task.id)
        affected_module_ids.add(task.project_module_id)

    session.flush()
    for module in session.scalars(
        select(ProjectModule)
        .where(ProjectModule.id.in_(affected_module_ids))
        .options(selectinload(ProjectModule.tasks))
    ):
        if module.tasks:
            module.planned_start_date = min(
                task.planned_start_date for task in module.tasks
            )
            module.planned_end_date = max(
                task.planned_end_date for task in module.tasks
            )
    return sorted(rescheduled_ids)


def _serialize_tasks(
    session: Session, tasks: Sequence[ProjectTask]
) -> list[dict[str, Any]]:
    task_ids = {task.id for task in tasks}
    dependency_ids = {task.id: [] for task in tasks}
    dependency_keys = {task.id: [] for task in tasks}
    incomplete_ids = {task.id: [] for task in tasks}
    if task_ids:
        dependencies = list(
            session.scalars(
                select(ProjectTaskDependency)
                .where(ProjectTaskDependency.successor_task_id.in_(task_ids))
                .options(selectinload(ProjectTaskDependency.predecessor_task))
            )
        )
        for dependency in dependencies:
            successor_id = dependency.successor_task_id
            predecessor = dependency.predecessor_task
            dependency_ids[successor_id].append(predecessor.id)
            dependency_keys[successor_id].append(predecessor.task_key)
            if predecessor.status != "completed":
                incomplete_ids[successor_id].append(predecessor.id)

    result = []
    for task in tasks:
        collaborator_ids = sorted(
            collaborator.user_id for collaborator in task.collaborators
        )
        predecessors = sorted(dependency_ids[task.id])
        incomplete = sorted(incomplete_ids[task.id])
        result.append(
            {
                "id": task.id,
                "project_module_id": task.project_module_id,
                "module_key": task.project_module.module_catalog.module_key,
                "task_key": task.task_key,
                "name": task.name,
                "description": task.description,
                "status": task.status,
                "planned_start_date": task.planned_start_date.isoformat(),
                "planned_end_date": task.planned_end_date.isoformat(),
                "duration_days": task.duration_days,
                "default_assignee_role": task.default_assignee_role,
                "assignee_user_id": task.assignee_user_id,
                "assignee": (
                    {
                        "id": task.assignee.id,
                        "display_name": task.assignee.display_name,
                        "role": task.assignee.role,
                    }
                    if task.assignee is not None
                    else None
                ),
                "pending_assignment": task.assignee_user_id is None,
                "collaborator_user_ids": collaborator_ids,
                "progress": task.progress,
                "blocked_reason": task.blocked_reason,
                "completed_at": (
                    task.completed_at.isoformat()
                    if task.completed_at is not None
                    else None
                ),
                "sort_order": task.sort_order,
                "dependency_ids": predecessors,
                "dependency_keys": sorted(dependency_keys[task.id]),
                "dependency_risk": bool(incomplete),
                "incomplete_dependency_ids": incomplete,
                "version": task.version,
            }
        )
    return result


def _load_project(
    session: Session, project_id: str, *, for_update: bool = False
) -> Project | None:
    statement = (
        select(Project)
        .where(Project.id == project_id)
        .options(
            selectinload(Project.members).selectinload(ProjectMember.user)
        )
    )
    if for_update:
        statement = statement.with_for_update()
    return session.scalar(statement)


def _load_task(
    session: Session, project_id: str, task_id: str
) -> ProjectTask | None:
    return session.scalar(
        select(ProjectTask)
        .join(ProjectModule)
        .where(
            ProjectModule.project_id == project_id,
            ProjectTask.id == task_id,
        )
        .options(
            selectinload(ProjectTask.project_module).selectinload(
                ProjectModule.module_catalog
            ),
            selectinload(ProjectTask.assignee),
            selectinload(ProjectTask.collaborators),
        )
    )


def _require_project_view(actor: User, project: Project | None):
    if project is None:
        raise ProjectServiceError(
            "project_not_found", "Project was not found.", 404
        )
    access = project_access(actor, project)
    if not access.can_view:
        raise _forbidden_error()
    return access


def _identifier_list(value: object) -> list[str]:
    if (
        not isinstance(value, list)
        or any(not isinstance(item, str) or not item or len(item) > 36 for item in value)
        or len(set(value)) != len(value)
    ):
        raise _invalid_request_error()
    return sorted(value)


def _date_value(value: object) -> date:
    if not isinstance(value, str):
        raise ValueError
    return date.fromisoformat(value)


def _json_value(value: Any) -> Any:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return value


def _invalid_request_error() -> ProjectServiceError:
    return ProjectServiceError(
        "invalid_request", "The request body is invalid.", 400
    )


def _invalid_task_state_error() -> ProjectServiceError:
    return ProjectServiceError(
        "invalid_task_state",
        "The task status, progress, or blocked reason is invalid.",
        400,
    )


def _task_not_found_error() -> ProjectServiceError:
    return ProjectServiceError(
        "project_task_not_found", "The project task was not found.", 404
    )


def _forbidden_error() -> ProjectServiceError:
    return ProjectServiceError(
        "forbidden", "You do not have permission to access this resource.", 403
    )
