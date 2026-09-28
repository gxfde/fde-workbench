from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date, timedelta
from typing import Any, TypedDict
from unicodedata import normalize
from uuid import uuid4

from sqlalchemy import exists, func, or_, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session, selectinload

from fde_api.auth.models import User
from fde_api.auth.permissions import ROLE_RANK, role_at_least
from fde_api.extensions import db
from fde_api.projects.events import record_event
from fde_api.projects.permissions import project_access
from fde_api.research.models import ProjectResearchSubject
from fde_api.research.form_service import initialize_subject_forms
from fde_api.research.template_service import snapshot_research_definition
from fde_api.templates.service import (
    TemplateServiceError,
    read_published_template_snapshot,
)
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
    schedule_tasks,
)


PROJECT_STATUSES = frozenset({"draft", "active", "paused", "completed", "cancelled"})
PROJECT_TRANSITIONS = {
    "draft": frozenset({"active", "cancelled"}),
    "active": frozenset({"paused", "completed", "cancelled"}),
    "paused": frozenset({"active", "cancelled"}),
    "completed": frozenset(),
    "cancelled": frozenset(),
}
PROJECT_MEMBER_ROLES = frozenset({"member", "viewer"})


class ProjectCreateInput(TypedDict, total=False):
    name: str
    enterprise_name: str
    contact_name: str
    contact_phone: str
    address: str
    background: str
    notes: str
    project_code: str
    planned_start_date: str
    planned_end_date: str | None
    template_version_id: str
    leader_user_id: str
    module_keys: list[str]


class ProjectListQuery(TypedDict, total=False):
    search: str | None
    status: str | None
    leader_user_id: str | None
    industry: str | None
    module_key: str | None
    page: int
    page_size: int


class ProjectServiceError(Exception):
    def __init__(self, code: str, message: str, status: int):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


def create_project(*, actor: User, input: Mapping[str, Any]) -> dict[str, Any]:
    values = _normalize_create_input(input)
    session = db.session()
    try:
        with session.begin():
            leader = session.get(User, values["leader_user_id"], with_for_update=True)
            _authorize_project_creation(actor, leader)
            if values["template_version_id"]:
                snapshot = read_published_template_snapshot(session=session, version_id=values["template_version_id"])
                research_snapshot = snapshot_research_definition(version_id=values["template_version_id"], session=session)
            else:
                snapshot = _normalize_project_snapshot(session, values["project_snapshot"], values["creation_source"])
                research_snapshot = {"forms": []}
            selected_modules = _selected_snapshot_modules(
                snapshot, values["module_keys"]
            )
            project = Project(
                project_code=values["project_code"] or _generated_project_code(),
                name=values["name"],
                enterprise_name=values["enterprise_name"],
                enterprise_contact_name=values["contact_name"],
                enterprise_contact_phone=values["contact_phone"],
                enterprise_address=values["address"],
                background=values["background"],
                notes=values["notes"],
                status="draft",
                planned_start_date=values["planned_start_date"],
                planned_end_date=values["planned_end_date"],
                leader_user_id=leader.id,
                source_template_version_id=snapshot.get("version_id"),
                template_snapshot=snapshot,
                research_snapshot=research_snapshot,
            )
            session.add(project)
            session.flush()
            session.add(
                ProjectMember(project_id=project.id, user_id=leader.id, role="member")
            )
            root_subject = ProjectResearchSubject(
                project_id=project.id,
                subject_type="project",
                subject_key="project",
                name=project.name,
                description=project.background,
                sort_order=0,
                status="active",
            )
            session.add(root_subject)
            session.flush()

            module_rows = _insert_project_modules(session, project, selected_modules)
            initialize_subject_forms(session, project, root_subject)
            task_definitions = [
                task for module in selected_modules for task in module["tasks"]
            ]
            selected_task_keys = {task["task_key"] for task in task_definitions}
            schedule_input = [
                ScheduleTask(
                    key=task["task_key"],
                    duration_days=task["duration_days"],
                    dependency_keys=tuple(task["dependency_keys"]),
                )
                for task in task_definitions
            ]
            schedules = schedule_tasks(schedule_input, values["planned_start_date"])
            task_rows = _insert_project_tasks(
                session=session,
                leader=leader,
                module_rows=module_rows,
                selected_modules=selected_modules,
                schedules=schedules,
            )
            _insert_project_dependencies(
                session, task_definitions, selected_task_keys, task_rows
            )
            _set_module_dates(module_rows, task_rows)
            if project.planned_end_date is None:
                project.planned_end_date = max(
                    task.planned_end_date for task in task_rows.values()
                )
            record_event(
                session,
                actor,
                "project_created",
                project,
                {
                    "project_code": project.project_code,
                    "module_keys": list(values["module_keys"]),
                },
            )
            session.flush()
            loaded_project = _load_project(session, project.id)
            assert loaded_project is not None
            created_dto = _serialize_project(
                session, loaded_project, include_tree=True
            )
        return created_dto
    except ProjectServiceError:
        raise
    except TemplateServiceError as error:
        raise ProjectServiceError(error.code, error.message, error.status) from None
    except SchedulingError as error:
        raise ProjectServiceError(error.code, error.message, 400) from None
    except IntegrityError:
        raise ProjectServiceError(
            "project_conflict", "The project could not be created due to a conflict.", 409
        ) from None
    except Exception:
        raise ProjectServiceError(
            "project_creation_failed", "Unable to create the project at this time.", 503
        ) from None
    finally:
        session.close()


def list_projects(
    *, actor: User, query: ProjectListQuery
) -> tuple[list[dict[str, Any]], int]:
    session = db.session()
    try:
        filters = []
        if actor.role != "admin":
            filters.append(
                or_(
                    Project.leader_user_id == actor.id,
                    exists(
                        select(ProjectMember.id).where(
                            ProjectMember.project_id == Project.id,
                            ProjectMember.user_id == actor.id,
                        )
                    ),
                )
            )
        search = query.get("search")
        if search:
            pattern = f"%{_escape_like_literal(search)}%"
            filters.append(
                or_(
                    Project.name.like(pattern, escape="!"),
                    Project.enterprise_name.like(pattern, escape="!"),
                )
            )
        if query.get("status"):
            filters.append(Project.status == query["status"])
        if query.get("leader_user_id"):
            filters.append(Project.leader_user_id == query["leader_user_id"])
        if query.get("industry"):
            filters.append(
                or_(
                    Project.template_snapshot["industry_name"].as_string()
                    == query["industry"],
                    Project.source_template_version.has(
                        industry_name=query["industry"]
                    ),
                )
            )
        if query.get("module_key"):
            filters.append(
                exists(
                    select(ProjectModule.id)
                    .join(ModuleCatalog)
                    .where(
                        ProjectModule.project_id == Project.id,
                        ModuleCatalog.module_key == query["module_key"],
                    )
                )
            )
        page = query["page"]
        page_size = query["page_size"]
        ids = list(
            session.scalars(
                select(Project.id)
                .where(*filters)
                .order_by(Project.created_at.desc(), Project.id.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        )
        total = int(
            session.scalar(select(func.count()).select_from(Project).where(*filters))
            or 0
        )
        projects_by_id = {
            project.id: project for project in _load_projects(session, ids)
        }
        return [
            _serialize_project(session, projects_by_id[project_id], include_tree=False)
            for project_id in ids
        ], total
    finally:
        session.close()


def get_project(*, actor: User, project_id: str) -> dict[str, Any]:
    session = db.session()
    try:
        project = _load_project(session, project_id)
        if project is None:
            raise ProjectServiceError("project_not_found", "Project was not found.", 404)
        if not project_access(actor, project).can_view:
            raise _forbidden_error()
        return _serialize_project(session, project, include_tree=True)
    finally:
        session.close()


def update_project(
    *, actor: User, project_id: str, expected_version: int, changes: Mapping[str, Any]
) -> dict[str, Any]:
    normalized_changes = _normalize_update_input(changes)
    session = db.session()
    try:
        with session.begin():
            project = session.scalar(
                select(Project)
                .options(selectinload(Project.members))
                .where(Project.id == project_id)
                .with_for_update()
            )
            if project is None:
                raise ProjectServiceError(
                    "project_not_found", "Project was not found.", 404
                )
            if not project_access(actor, project).can_manage:
                raise _forbidden_error()
            if project.version != expected_version:
                raise ProjectServiceError(
                    "stale_version",
                    "The project has been updated. Refresh and try again.",
                    409,
                )
            next_leader_id = normalized_changes.pop("leader_user_id", None)
            if next_leader_id is not None and next_leader_id != project.leader_user_id:
                if actor.role != "admin":
                    raise _forbidden_error()
                next_leader = session.get(User, next_leader_id, with_for_update=True)
                _validate_project_leader(next_leader)
                project.leader_user_id = next_leader.id
                next_member = next(
                    (
                        member
                        for member in project.members
                        if member.user_id == next_leader.id
                    ),
                    None,
                )
                if next_member is None:
                    session.add(
                        ProjectMember(
                            project_id=project.id,
                            user_id=next_leader.id,
                            role="member",
                        )
                    )
                else:
                    next_member.role = "member"
            next_status = normalized_changes.pop("status", None)
            if next_status is not None and next_status != project.status:
                if next_status not in PROJECT_TRANSITIONS[project.status]:
                    raise ProjectServiceError(
                        "invalid_project_transition",
                        "The requested project status transition is not allowed.",
                        409,
                    )
                project.status = next_status
            field_map = {
                "name": "name",
                "enterprise_name": "enterprise_name",
                "contact_name": "enterprise_contact_name",
                "contact_phone": "enterprise_contact_phone",
                "address": "enterprise_address",
                "background": "background",
                "notes": "notes",
                "project_code": "project_code",
                "planned_start_date": "planned_start_date",
                "planned_end_date": "planned_end_date",
            }
            for input_name, model_name in field_map.items():
                if input_name in normalized_changes:
                    setattr(project, model_name, normalized_changes[input_name])
            root_subject_changes: dict[str, Any] = {}
            if "name" in normalized_changes or "background" in normalized_changes:
                root_subject = session.scalar(
                    select(ProjectResearchSubject)
                    .where(
                        ProjectResearchSubject.project_id == project.id,
                        ProjectResearchSubject.subject_type == "project",
                        ProjectResearchSubject.status == "active",
                    )
                    .with_for_update()
                )
                if root_subject is not None:
                    if root_subject.name != project.name:
                        root_subject.name = project.name
                        root_subject_changes["name"] = project.name
                    if root_subject.description != project.background:
                        root_subject.description = project.background
                        root_subject_changes["description"] = project.background
                    if root_subject_changes:
                        root_subject.version += 1
                        record_event(
                            session,
                            actor,
                            "project_research_subject_updated",
                            root_subject,
                            root_subject_changes,
                        )
            if (
                project.planned_end_date is not None
                and project.planned_end_date < project.planned_start_date
            ):
                raise _invalid_request_error()
            project.version += 1
            record_event(
                session,
                actor,
                "project_updated",
                project,
                {key: _json_value(value) for key, value in normalized_changes.items()}
                | (
                    {"leader_user_id": next_leader_id}
                    if next_leader_id is not None
                    else {}
                )
                | ({"status": next_status} if next_status is not None else {}),
            )
        return get_project(actor=actor, project_id=project_id)
    except ProjectServiceError:
        raise
    except IntegrityError:
        raise ProjectServiceError(
            "project_conflict", "The project could not be updated due to a conflict.", 409
        ) from None
    except SQLAlchemyError:
        raise ProjectServiceError(
            "project_update_failed", "Unable to update the project at this time.", 503
        ) from None
    finally:
        session.close()


def list_project_members(*, actor: User, project_id: str) -> tuple[list[dict[str, Any]], int]:
    session = db.session()
    try:
        project = _load_project(session, project_id)
        if project is None:
            raise ProjectServiceError("project_not_found", "Project was not found.", 404)
        if not project_access(actor, project).can_view:
            raise _forbidden_error()
        return (
            [_serialize_member(member) for member in sorted(project.members, key=lambda item: item.id)],
            project.version,
        )
    finally:
        session.close()


def add_project_member(
    *,
    actor: User,
    project_id: str,
    expected_version: int,
    user_id: str,
    role: str,
) -> dict[str, Any]:
    member_user_id, member_role = _normalize_member_input(user_id=user_id, role=role)
    session = db.session()
    try:
        with session.begin():
            project = _load_project_for_update(session, project_id)
            _require_project_manager(actor, project)
            _require_current_version(project, expected_version)
            target = session.get(User, member_user_id, with_for_update=True)
            _validate_project_member_target(target, member_role)
            if any(member.user_id == target.id for member in project.members):
                raise ProjectServiceError(
                    "duplicate_project_member",
                    "The user is already a project member.",
                    409,
                )
            member = ProjectMember(
                project_id=project.id,
                user_id=target.id,
                role=member_role,
                user=target,
            )
            session.add(member)
            session.flush()
            project.version += 1
            record_event(
                session,
                actor,
                "project_member_added",
                member,
                {"user_id": target.id, "role": member_role},
            )
            return _serialize_member(member) | {"project_version": project.version}
    except ProjectServiceError:
        raise
    except IntegrityError:
        raise ProjectServiceError(
            "duplicate_project_member", "The user is already a project member.", 409
        ) from None
    except SQLAlchemyError:
        raise ProjectServiceError(
            "project_member_update_failed",
            "Unable to update project members at this time.",
            503,
        ) from None
    finally:
        session.close()


def update_project_member(
    *,
    actor: User,
    project_id: str,
    member_identifier: str,
    expected_version: int,
    role: str,
) -> dict[str, Any]:
    _, member_role = _normalize_member_input(user_id="member", role=role)
    session = db.session()
    try:
        with session.begin():
            project = _load_project_for_update(session, project_id)
            _require_project_manager(actor, project)
            _require_current_version(project, expected_version)
            member = _find_project_member(project, member_identifier)
            if member is None:
                raise ProjectServiceError(
                    "project_member_not_found", "Project member was not found.", 404
                )
            _validate_project_member_target(member.user, member_role)
            if member.role != member_role:
                if member_role == "viewer":
                    _require_no_active_task_assignments(
                        session,
                        project_id=project.id,
                        user_id=member.user_id,
                    )
                previous_role = member.role
                member.role = member_role
                project.version += 1
                record_event(
                    session,
                    actor,
                    "project_member_updated",
                    member,
                    {
                        "user_id": member.user_id,
                        "role": member_role,
                        "previous_role": previous_role,
                    },
                )
            session.flush()
            return _serialize_member(member) | {"project_version": project.version}
    except ProjectServiceError:
        raise
    except SQLAlchemyError:
        raise ProjectServiceError(
            "project_member_update_failed",
            "Unable to update project members at this time.",
            503,
        ) from None
    finally:
        session.close()


def remove_project_member(
    *, actor: User, project_id: str, member_identifier: str, expected_version: int
) -> None:
    session = db.session()
    try:
        with session.begin():
            project = _load_project_for_update(session, project_id)
            _require_project_manager(actor, project)
            _require_current_version(project, expected_version)
            member = _find_project_member(project, member_identifier)
            if member is None:
                raise ProjectServiceError(
                    "project_member_not_found", "Project member was not found.", 404
                )
            if member.user_id == project.leader_user_id:
                raise ProjectServiceError(
                    "current_project_leader",
                    "Change the project leader before removing this membership.",
                    409,
                )
            _require_no_active_task_assignments(
                session,
                project_id=project.id,
                user_id=member.user_id,
            )
            project.version += 1
            record_event(
                session,
                actor,
                "project_member_removed",
                member,
                {"user_id": member.user_id, "role": member.role},
            )
            session.delete(member)
    except ProjectServiceError:
        raise
    except SQLAlchemyError:
        raise ProjectServiceError(
            "project_member_update_failed",
            "Unable to update project members at this time.",
            503,
        ) from None
    finally:
        session.close()


def _require_no_active_task_assignments(
    session: Session, *, project_id: str, user_id: str
) -> None:
    collaborator_assignment = exists(
        select(ProjectTaskCollaborator.id).where(
            ProjectTaskCollaborator.task_id == ProjectTask.id,
            ProjectTaskCollaborator.user_id == user_id,
        )
    )
    assigned_tasks = list(
        session.scalars(
            select(ProjectTask)
            .join(ProjectModule)
            .where(
                ProjectModule.project_id == project_id,
                ProjectTask.status != "cancelled",
                or_(
                    ProjectTask.assignee_user_id == user_id,
                    collaborator_assignment,
                ),
            )
            .with_for_update()
        )
    )
    if assigned_tasks:
        raise ProjectServiceError(
            "member_has_active_task_assignments",
            "Reassign the member's active tasks before changing their access.",
            409,
        )


def assign_project_default_tasks(
    *, actor: User, project_id: str, expected_version: int
) -> dict[str, Any]:
    session = db.session()
    try:
        with session.begin():
            project = _load_project_for_update(session, project_id)
            _require_project_manager(actor, project)
            _require_current_version(project, expected_version)
            candidates = sorted(
                (
                    member
                    for member in project.members
                    if member.role == "member" and member.user.is_active
                ),
                key=lambda member: (ROLE_RANK[member.user.role], member.user_id),
            )
            unassigned_tasks = list(
                session.scalars(
                    select(ProjectTask)
                    .join(ProjectModule)
                    .where(
                        ProjectModule.project_id == project.id,
                        ProjectTask.assignee_user_id.is_(None),
                    )
                    .order_by(ProjectTask.sort_order, ProjectTask.id)
                    .with_for_update()
                )
            )
            assignments: list[dict[str, str]] = []
            for task in unassigned_tasks:
                if task.default_assignee_role is None:
                    continue
                assignee = next(
                    (
                        member
                        for member in candidates
                        if role_at_least(member.user.role, task.default_assignee_role)
                    ),
                    None,
                )
                if assignee is None:
                    continue
                task.assignee_user_id = assignee.user_id
                task.version += 1
                assignments.append({"task_id": task.id, "assignee_user_id": assignee.user_id})
            if assignments:
                project.version += 1
                record_event(
                    session,
                    actor,
                    "project_default_assignments_applied",
                    project,
                    {"assignments": assignments},
                )
            session.flush()
            return {
                "assigned_count": len(assignments),
                "assignments": assignments,
                "project_version": project.version,
            }
    except ProjectServiceError:
        raise
    except SQLAlchemyError:
        raise ProjectServiceError(
            "project_assignment_failed",
            "Unable to assign project tasks at this time.",
            503,
        ) from None
    finally:
        session.close()


def project_completion(project_id: str) -> int:
    session = db.session()
    try:
        values = list(
            session.scalars(
                select(ProjectTask.progress)
                .join(ProjectModule)
                .where(
                    ProjectModule.project_id == project_id,
                    ProjectTask.status != "cancelled",
                )
            )
        )
        return round(sum(values) / len(values)) if values else 0
    finally:
        session.close()


def append_project_module(
    *,
    actor: User,
    project_id: str,
    module_key: str,
    planned_start_date: str,
    expected_version: int,
) -> dict[str, Any]:
    try:
        normalized_key = _required_text(module_key, maximum=80)
        submitted_start = _date_value(planned_start_date)
    except (TypeError, ValueError):
        raise _invalid_request_error() from None

    session = db.session()
    try:
        with session.begin():
            project = _load_project_for_update(session, project_id)
            _require_project_manager(actor, project)
            _require_current_version(project, expected_version)
            snapshot_module = next(
                (
                    module
                    for module in project.template_snapshot["modules"]
                    if module["module_key"] == normalized_key
                ),
                None,
            )
            if snapshot_module is None:
                raise ProjectServiceError(
                    "module_not_in_project_template",
                    "The module does not exist in the project's template snapshot.",
                    400,
                )
            duplicate = session.scalar(
                select(ProjectModule)
                .join(ModuleCatalog)
                .where(
                    ProjectModule.project_id == project.id,
                    ModuleCatalog.module_key == normalized_key,
                )
                .with_for_update()
            )
            if duplicate is not None:
                raise ProjectServiceError(
                    "project_module_already_exists",
                    "The project module already exists and cannot be added again.",
                    409,
                )

            existing_tasks = list(
                session.scalars(
                    select(ProjectTask)
                    .join(ProjectModule)
                    .where(ProjectModule.project_id == project.id)
                    .options(selectinload(ProjectTask.project_module))
                    .with_for_update()
                )
            )
            active_existing_by_key = {
                task.task_key: task
                for task in existing_tasks
                if task.project_module.status == "active"
                and task.status != "cancelled"
            }
            new_task_definitions = list(snapshot_module["tasks"])
            new_task_keys = {task["task_key"] for task in new_task_definitions}
            snapshot_task_module = {
                task["task_key"]: module["module_key"]
                for module in project.template_snapshot["modules"]
                for task in module["tasks"]
            }
            missing_cross_dependencies = sorted(
                (
                    dependency_key,
                    task["task_key"],
                )
                for task in new_task_definitions
                for dependency_key in task["dependency_keys"]
                if dependency_key not in new_task_keys
                and dependency_key not in active_existing_by_key
            )
            if missing_cross_dependencies:
                dependency_key, task_key = missing_cross_dependencies[0]
                predecessor_module = snapshot_task_module.get(
                    dependency_key, "unknown"
                )
                raise ProjectServiceError(
                    "missing_required_module_dependency",
                    f"Module '{normalized_key}' task '{task_key}' requires active "
                    f"module '{predecessor_module}' task '{dependency_key}'.",
                    400,
                )

            internal_schedule_input = [
                ScheduleTask(
                    key=task["task_key"],
                    duration_days=task["duration_days"],
                    dependency_keys=tuple(
                        key
                        for key in task["dependency_keys"]
                        if key in new_task_keys
                    ),
                )
                for task in new_task_definitions
            ]
            base_schedules = schedule_tasks(
                internal_schedule_input, submitted_start
            )
            task_definition_by_key = {
                task["task_key"]: task for task in new_task_definitions
            }
            schedules: dict[str, ScheduledTask] = {}
            baseline = normalize_workday(submitted_start)
            for task_key in base_schedules:
                definition = task_definition_by_key[task_key]
                dependency_ends = [
                    (
                        schedules[dependency_key].end_date
                        if dependency_key in schedules
                        else active_existing_by_key[dependency_key].planned_end_date
                    )
                    for dependency_key in definition["dependency_keys"]
                ]
                task_start = baseline
                if dependency_ends:
                    task_start = max(
                        task_start,
                        normalize_workday(max(dependency_ends) + timedelta(days=1)),
                    )
                schedules[task_key] = ScheduledTask(
                    key=task_key,
                    start_date=task_start,
                    end_date=add_workdays(
                        task_start, definition["duration_days"]
                    ),
                )

            module = ProjectModule(
                project_id=project.id,
                source_template_module_id=snapshot_module["id"],
                module_catalog_id=snapshot_module["module_catalog_id"],
                name=snapshot_module["name"],
                description=snapshot_module["description"],
                status="active",
                sort_order=snapshot_module["sort_order"],
            )
            session.add(module)
            session.flush()
            for subject in session.scalars(
                select(ProjectResearchSubject).where(
                    ProjectResearchSubject.project_id == project.id,
                    ProjectResearchSubject.status == "active",
                )
            ):
                initialize_subject_forms(session, project, subject)
            working_members = sorted(
                (
                    member
                    for member in project.members
                    if member.role == "member" and member.user.is_active
                ),
                key=lambda member: (ROLE_RANK[member.user.role], member.user_id),
            )
            new_tasks: dict[str, ProjectTask] = {}
            for definition in new_task_definitions:
                default_role = definition["default_assignee_role"]
                default_member = next(
                    (
                        member
                        for member in working_members
                        if role_at_least(member.user.role, default_role)
                    ),
                    None,
                )
                scheduled = schedules[definition["task_key"]]
                task = ProjectTask(
                    project_module_id=module.id,
                    source_template_task_id=definition["id"],
                    task_key=definition["task_key"],
                    name=definition["name"],
                    description=definition["description"],
                    status="not_started",
                    planned_start_date=scheduled.start_date,
                    planned_end_date=scheduled.end_date,
                    duration_days=definition["duration_days"],
                    default_assignee_role=default_role,
                    assignee_user_id=(
                        default_member.user_id if default_member is not None else None
                    ),
                    progress=0,
                    blocked_reason="",
                    sort_order=definition["sort_order"],
                )
                session.add(task)
                new_tasks[task.task_key] = task
            session.flush()
            for definition in new_task_definitions:
                successor = new_tasks[definition["task_key"]]
                for predecessor_key in definition["dependency_keys"]:
                    predecessor = new_tasks.get(
                        predecessor_key
                    ) or active_existing_by_key.get(predecessor_key)
                    assert predecessor is not None
                    session.add(
                        ProjectTaskDependency(
                            predecessor_task_id=predecessor.id,
                            successor_task_id=successor.id,
                        )
                    )
            module.planned_start_date = min(
                task.planned_start_date for task in new_tasks.values()
            )
            module.planned_end_date = max(
                task.planned_end_date for task in new_tasks.values()
            )
            if (
                project.planned_end_date is None
                or module.planned_end_date > project.planned_end_date
            ):
                project.planned_end_date = module.planned_end_date
            project.version += 1
            record_event(
                session,
                actor,
                "project_module_appended",
                module,
                {
                    "module_key": normalized_key,
                    "planned_start_date": submitted_start.isoformat(),
                    "task_ids": sorted(task.id for task in new_tasks.values()),
                },
            )
            session.flush()
            return _serialize_project_module(
                session, module, project_version=project.version
            )
    except ProjectServiceError:
        raise
    except SchedulingError as error:
        raise ProjectServiceError(error.code, error.message, 400) from None
    except IntegrityError:
        raise ProjectServiceError(
            "project_module_already_exists",
            "The project module already exists and cannot be added again.",
            409,
        ) from None
    except Exception:
        raise ProjectServiceError(
            "project_module_append_failed",
            "Unable to append the project module at this time.",
            503,
        ) from None
    finally:
        session.close()


def cancel_project_module(
    *,
    actor: User,
    project_id: str,
    module_identifier: str,
    expected_version: int,
) -> dict[str, Any]:
    session = db.session()
    try:
        with session.begin():
            project = _load_project_for_update(session, project_id)
            _require_project_manager(actor, project)
            _require_current_version(project, expected_version)
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
                .options(
                    selectinload(ProjectModule.module_catalog),
                )
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
                    "project_module_already_cancelled",
                    "The project module is already cancelled.",
                    409,
                )
            tasks = list(
                session.scalars(
                    select(ProjectTask)
                    .where(ProjectTask.project_module_id == module.id)
                    .order_by(ProjectTask.sort_order, ProjectTask.id)
                    .with_for_update()
                )
            )
            module.status = "cancelled"
            cancelled_task_ids = []
            for task in tasks:
                if task.status != "cancelled":
                    task.status = "cancelled"
                    task.version += 1
                    cancelled_task_ids.append(task.id)
            project.version += 1
            record_event(
                session,
                actor,
                "project_module_cancelled",
                module,
                {
                    "module_key": module.module_catalog.module_key,
                    "cancelled_task_ids": sorted(cancelled_task_ids),
                },
            )
            session.flush()
            return _serialize_project_module(
                session,
                module,
                tasks=tasks,
                project_version=project.version,
            )
    except ProjectServiceError:
        raise
    except SQLAlchemyError:
        raise ProjectServiceError(
            "project_module_cancel_failed",
            "Unable to cancel the project module at this time.",
            503,
        ) from None
    finally:
        session.close()


def _normalize_create_input(input: Mapping[str, Any]) -> dict[str, Any]:
    try:
        values = {
            "name": _required_text(input.get("name"), maximum=160),
            "enterprise_name": _required_text(
                input.get("enterprise_name"), maximum=160
            ),
            "contact_name": _optional_text(input.get("contact_name", ""), 120),
            "contact_phone": _optional_text(input.get("contact_phone", ""), 60),
            "address": _optional_text(input.get("address", ""), 255),
            "background": _optional_text(input.get("background", "")),
            "notes": _optional_text(input.get("notes", "")),
            "project_code": _optional_text(input.get("project_code", ""), 40),
            "planned_start_date": _date_value(input.get("planned_start_date")),
            "planned_end_date": _optional_date_value(input.get("planned_end_date")),
            "template_version_id": _optional_text(input.get("template_version_id") or "", 36) or None,
            "creation_source": _creation_source(input.get("creation_source", "template")),
            "project_snapshot": input.get("project_snapshot"),
            "leader_user_id": _required_text(input.get("leader_user_id"), maximum=36),
            "module_keys": _module_keys(input.get("module_keys")),
        }
    except (TypeError, ValueError):
        raise _invalid_request_error() from None
    if (
        values["planned_end_date"] is not None
        and values["planned_end_date"] < values["planned_start_date"]
    ):
        raise _invalid_request_error()
    if values["creation_source"] == "template" and not values["template_version_id"]:
        raise _invalid_request_error()
    if values["creation_source"] != "template" and values["template_version_id"]:
        raise _invalid_request_error()
    return values


def _creation_source(value: object) -> str:
    if value not in {"template", "presurvey", "manual"}:
        raise ValueError
    return str(value)


def _normalize_project_snapshot(session: Session, value: object, creation_source: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise _invalid_request_error()
    modules = value.get("modules")
    if not isinstance(modules, list) or not modules:
        raise _invalid_request_error()
    catalog = {
        item.module_key: item
        for item in session.scalars(select(ModuleCatalog).where(ModuleCatalog.is_active.is_(True))).all()
    }
    normalized_modules: list[dict[str, Any]] = []
    task_keys: set[str] = set()
    for order, raw_module in enumerate(modules):
        if not isinstance(raw_module, Mapping) or raw_module.get("module_key") not in catalog:
            raise _invalid_request_error()
        module = catalog[str(raw_module["module_key"])]
        raw_tasks = raw_module.get("tasks")
        if not isinstance(raw_tasks, list) or not raw_tasks:
            raw_tasks = [{
                "task_key": f"{module.module_key}_planning", "name": f"{module.name}实施规划",
                "description": "梳理范围、输入、负责人和验收口径。", "duration_days": 1,
                "default_assignee_role": "project_lead", "dependency_keys": [], "sort_order": 0,
            }]
        tasks: list[dict[str, Any]] = []
        for task_order, raw_task in enumerate(raw_tasks):
            if not isinstance(raw_task, Mapping):
                raise _invalid_request_error()
            task_key = _required_text(raw_task.get("task_key"), maximum=100)
            if task_key in task_keys:
                raise _invalid_request_error()
            task_keys.add(task_key)
            dependencies = raw_task.get("dependency_keys", [])
            if not isinstance(dependencies, list) or not all(isinstance(item, str) for item in dependencies):
                raise _invalid_request_error()
            tasks.append({
                "id": None, "task_key": task_key,
                "name": _required_text(raw_task.get("name"), maximum=200),
                "description": _optional_text(raw_task.get("description", "")),
                "duration_days": max(1, int(raw_task.get("duration_days", 1))),
                "default_assignee_role": raw_task.get("default_assignee_role") if raw_task.get("default_assignee_role") in {"admin", "project_lead", "fde_engineer", "viewer"} else "project_lead",
                "dependency_keys": list(dependencies), "sort_order": int(raw_task.get("sort_order", task_order)),
            })
        normalized_modules.append({
            "id": None, "module_catalog_id": module.id, "module_key": module.module_key,
            "name": _optional_text(raw_module.get("name", module.name), 160) or module.name,
            "description": _optional_text(raw_module.get("description", module.description)),
            "sort_order": int(raw_module.get("sort_order", order)), "tasks": tasks,
        })
    for module in normalized_modules:
        for task in module["tasks"]:
            if any(key not in task_keys for key in task["dependency_keys"]):
                raise _invalid_request_error()
    return {
        "version_id": None, "template_id": None, "template_name": "非模板项目",
        "name": "项目自定义配置", "industry_name": _optional_text(value.get("industry_name", "通用"), 160) or "通用",
        "description": _optional_text(value.get("description", "")), "creation_source": creation_source,
        "modules": normalized_modules,
    }


def _normalize_update_input(changes: Mapping[str, Any]) -> dict[str, Any]:
    try:
        normalized_changes: dict[str, Any] = {}
        text_limits = {
            "name": 160,
            "enterprise_name": 160,
            "project_code": 40,
        }
        for key, maximum in text_limits.items():
            if key in changes:
                normalized_changes[key] = _required_text(
                    changes[key], maximum=maximum
                )
        optional_text_limits = {
            "contact_name": 120,
            "contact_phone": 60,
            "address": 255,
            "background": None,
            "notes": None,
        }
        for key, maximum in optional_text_limits.items():
            if key in changes:
                normalized_changes[key] = _optional_text(changes[key], maximum)
        if "planned_start_date" in changes:
            normalized_changes["planned_start_date"] = _date_value(
                changes["planned_start_date"]
            )
        if "planned_end_date" in changes:
            normalized_changes["planned_end_date"] = _optional_date_value(
                changes["planned_end_date"]
            )
        if "leader_user_id" in changes:
            normalized_changes["leader_user_id"] = _required_text(
                changes["leader_user_id"], maximum=36
            )
        if "status" in changes:
            status = changes["status"]
            if not isinstance(status, str) or status not in PROJECT_STATUSES:
                raise ValueError
            normalized_changes["status"] = status
        return normalized_changes
    except (TypeError, ValueError):
        raise _invalid_request_error() from None


def _authorize_project_creation(actor: User, leader: User | None) -> None:
    if actor.role not in {"admin", "project_lead"}:
        raise _forbidden_error()
    if actor.role == "project_lead" and actor.id != getattr(leader, "id", None):
        raise _forbidden_error()
    _validate_project_leader(leader)


def _validate_project_leader(leader: User | None) -> None:
    if leader is None or not leader.is_active or leader.role not in {
        "admin",
        "project_lead",
    }:
        raise ProjectServiceError(
            "invalid_project_leader",
            "The project leader must be an active administrator or project lead.",
            400,
        )


def _normalize_member_input(*, user_id: str, role: str) -> tuple[str, str]:
    try:
        normalized_user_id = _required_text(user_id, maximum=36)
    except (TypeError, ValueError):
        raise _invalid_request_error() from None
    if role not in PROJECT_MEMBER_ROLES:
        raise _invalid_request_error()
    return normalized_user_id, role


def _validate_project_member_target(target: User | None, role: str) -> None:
    if target is None or not target.is_active:
        raise ProjectServiceError(
            "invalid_project_member",
            "The project member must be an active user.",
            400,
        )
    if role == "member" and not role_at_least(target.role, "fde_engineer"):
        raise ProjectServiceError(
            "member_role_exceeds_system_role",
            "The project member role exceeds the user's system role.",
            400,
        )


def _load_project_for_update(session: Session, project_id: str) -> Project | None:
    return session.scalar(
        select(Project)
        .options(selectinload(Project.members).selectinload(ProjectMember.user))
        .where(Project.id == project_id)
        .with_for_update()
    )


def _require_project_manager(actor: User, project: Project | None) -> Project:
    if project is None:
        raise ProjectServiceError("project_not_found", "Project was not found.", 404)
    if not project_access(actor, project).can_manage:
        raise _forbidden_error()
    return project


def _require_current_version(project: Project, expected_version: int) -> None:
    if project.version != expected_version:
        raise ProjectServiceError(
            "stale_version", "The project has been updated. Refresh and try again.", 409
        )


def _find_project_member(project: Project, identifier: str) -> ProjectMember | None:
    return next(
        (
            member
            for member in project.members
            if member.id == identifier or member.user_id == identifier
        ),
        None,
    )


def _selected_snapshot_modules(
    snapshot: Mapping[str, Any], module_keys: Sequence[str]
) -> list[dict[str, Any]]:
    modules_by_key = {module["module_key"]: module for module in snapshot["modules"]}
    missing = set(module_keys) - modules_by_key.keys()
    if missing:
        raise ProjectServiceError(
            "module_not_in_template",
            "Every selected module must belong to the template version.",
            400,
        )
    selected = sorted(
        (modules_by_key[key] for key in module_keys),
        key=lambda module: (module["sort_order"], module["id"]),
    )
    selected_task_keys = {
        task["task_key"] for module in selected for task in module["tasks"]
    }
    task_module_by_key = {
        task["task_key"]: module["module_key"]
        for module in snapshot["modules"]
        for task in module["tasks"]
    }
    missing_dependencies = sorted(
        (
            task_module_by_key[dependency_key],
            dependency_key,
            module["module_key"],
            task["task_key"],
        )
        for module in selected
        for task in module["tasks"]
        for dependency_key in task["dependency_keys"]
        if dependency_key not in selected_task_keys
    )
    if missing_dependencies:
        predecessor_module, predecessor_task, successor_module, successor_task = (
            missing_dependencies[0]
        )
        raise ProjectServiceError(
            "missing_required_module_dependency",
            f"Module '{successor_module}' task '{successor_task}' requires "
            f"module '{predecessor_module}' task '{predecessor_task}'.",
            400,
        )
    return selected


def _insert_project_modules(
    session: Session,
    project: Project,
    selected_modules: Sequence[Mapping[str, Any]],
) -> dict[str, ProjectModule]:
    rows = {}
    for module in selected_modules:
        row = ProjectModule(
            project_id=project.id,
            source_template_module_id=module.get("id"),
            module_catalog_id=module["module_catalog_id"],
            name=module["name"],
            description=module["description"],
            status="active",
            sort_order=module["sort_order"],
        )
        session.add(row)
        rows[module["module_key"]] = row
    session.flush()
    return rows


def _insert_project_tasks(
    *,
    session: Session,
    leader: User,
    module_rows: Mapping[str, ProjectModule],
    selected_modules: Sequence[Mapping[str, Any]],
    schedules: Mapping[str, Any],
) -> dict[str, ProjectTask]:
    rows = {}
    for module in selected_modules:
        for task in module["tasks"]:
            default_role = task["default_assignee_role"]
            assignee_id = (
                leader.id if role_at_least(leader.role, default_role) else None
            )
            scheduled = schedules[task["task_key"]]
            row = ProjectTask(
                project_module_id=module_rows[module["module_key"]].id,
                source_template_task_id=task.get("id"),
                task_key=task["task_key"],
                name=task["name"],
                description=task["description"],
                status="not_started",
                planned_start_date=scheduled.start_date,
                planned_end_date=scheduled.end_date,
                duration_days=task["duration_days"],
                default_assignee_role=default_role,
                assignee_user_id=assignee_id,
                progress=0,
                blocked_reason="",
                sort_order=task["sort_order"],
            )
            session.add(row)
            rows[task["task_key"]] = row
    session.flush()
    return rows


def _insert_project_dependencies(
    session: Session,
    task_definitions: Sequence[Mapping[str, Any]],
    selected_task_keys: set[str],
    task_rows: Mapping[str, ProjectTask],
) -> None:
    for task in task_definitions:
        for predecessor_key in task["dependency_keys"]:
            assert predecessor_key in selected_task_keys
            session.add(
                ProjectTaskDependency(
                    predecessor_task_id=task_rows[predecessor_key].id,
                    successor_task_id=task_rows[task["task_key"]].id,
                )
            )


def _set_module_dates(
    module_rows: Mapping[str, ProjectModule], task_rows: Mapping[str, ProjectTask]
) -> None:
    tasks_by_module_id: dict[str, list[ProjectTask]] = {}
    for task in task_rows.values():
        tasks_by_module_id.setdefault(task.project_module_id, []).append(task)
    for module in module_rows.values():
        tasks = tasks_by_module_id[module.id]
        module.planned_start_date = min(task.planned_start_date for task in tasks)
        module.planned_end_date = max(task.planned_end_date for task in tasks)


def _load_project(session: Session, project_id: str) -> Project | None:
    projects = _load_projects(session, [project_id])
    return projects[0] if projects else None


def _load_projects(session: Session, project_ids: Sequence[str]) -> list[Project]:
    if not project_ids:
        return []
    return list(
        session.scalars(
            select(Project)
            .options(
                selectinload(Project.leader),
                selectinload(Project.source_template_version),
                selectinload(Project.members).selectinload(ProjectMember.user),
                selectinload(Project.modules).selectinload(ProjectModule.module_catalog),
                selectinload(Project.modules)
                .selectinload(ProjectModule.tasks)
                .selectinload(ProjectTask.assignee),
                selectinload(Project.modules)
                .selectinload(ProjectModule.tasks)
                .selectinload(ProjectTask.collaborators),
            )
            .where(Project.id.in_(project_ids))
        )
    )


def _serialize_project(
    session: Session, project: Project, *, include_tree: bool
) -> dict[str, Any]:
    modules = sorted(project.modules, key=lambda item: (item.sort_order, item.id))
    tasks = [
        task
        for module in modules
        for task in sorted(module.tasks, key=lambda item: (item.sort_order, item.id))
    ]
    dependency_metadata = _dependency_metadata(session, tasks)
    completion_values = [task.progress for task in tasks if task.status != "cancelled"]
    dto: dict[str, Any] = {
        "id": project.id,
        "project_code": project.project_code,
        "name": project.name,
        "enterprise_name": project.enterprise_name,
        "contact_name": project.enterprise_contact_name,
        "contact_phone": project.enterprise_contact_phone,
        "address": project.enterprise_address,
        "background": project.background,
        "notes": project.notes,
        "status": project.status,
        "planned_start_date": project.planned_start_date.isoformat(),
        "planned_end_date": (
            project.planned_end_date.isoformat()
            if project.planned_end_date is not None
            else None
        ),
        "leader_user_id": project.leader_user_id,
        "leader": {
            "id": project.leader.id,
            "display_name": project.leader.display_name,
            "role": project.leader.role,
        },
        "template_version_id": project.source_template_version_id,
        "research_snapshot": project.research_snapshot,
        "industry": _project_industry(project),
        "completion": (
            round(sum(completion_values) / len(completion_values))
            if completion_values
            else 0
        ),
        "version": project.version,
        "created_at": project.created_at.isoformat(),
        "updated_at": project.updated_at.isoformat(),
    }
    dto["modules"] = [
        {
            "id": module.id,
            "module_key": module.module_catalog.module_key,
            "name": module.name,
            "description": module.description,
            "status": module.status,
            "sort_order": module.sort_order,
            "planned_start_date": (
                module.planned_start_date.isoformat()
                if module.planned_start_date is not None
                else None
            ),
            "planned_end_date": (
                module.planned_end_date.isoformat()
                if module.planned_end_date is not None
                else None
            ),
        }
        for module in modules
    ]
    if include_tree:
        module_key_by_id = {
            module.id: module.module_catalog.module_key for module in modules
        }
        dto["tasks"] = [
            {
                "id": task.id,
                "project_module_id": task.project_module_id,
                "module_key": module_key_by_id[task.project_module_id],
                "task_key": task.task_key,
                "name": task.name,
                "description": task.description,
                "status": task.status,
                "planned_start_date": task.planned_start_date.isoformat(),
                "planned_end_date": task.planned_end_date.isoformat(),
                "duration_days": task.duration_days,
                "default_assignee_role": task.default_assignee_role,
                "assignee_user_id": task.assignee_user_id,
                "pending_assignment": task.assignee_user_id is None,
                "progress": task.progress,
                "blocked_reason": task.blocked_reason,
                "completed_at": (
                    task.completed_at.isoformat()
                    if task.completed_at is not None
                    else None
                ),
                "sort_order": task.sort_order,
                "collaborator_user_ids": sorted(
                    collaborator.user_id for collaborator in task.collaborators
                ),
                "dependency_ids": dependency_metadata[task.id]["ids"],
                "dependency_keys": dependency_metadata[task.id]["keys"],
                "dependency_risk": bool(
                    dependency_metadata[task.id]["incomplete_ids"]
                ),
                "incomplete_dependency_ids": dependency_metadata[task.id][
                    "incomplete_ids"
                ],
                "version": task.version,
            }
            for task in tasks
        ]
        dto["members"] = [
            _serialize_member(member)
            for member in sorted(project.members, key=lambda item: item.id)
        ]
        dto["template_snapshot"] = project.template_snapshot
    return dto


def _project_industry(project: Project) -> str:
    """Read new snapshots while keeping projects created by older builds usable."""
    snapshot = project.template_snapshot
    if isinstance(snapshot, Mapping):
        snapshot_industry = snapshot.get("industry_name")
        if isinstance(snapshot_industry, str) and snapshot_industry.strip():
            return snapshot_industry
    return project.source_template_version.industry_name if project.source_template_version is not None else "通用"


def _serialize_member(member: ProjectMember) -> dict[str, Any]:
    return {
        "id": member.id,
        "user_id": member.user_id,
        "display_name": member.user.display_name,
        "system_role": member.user.role,
        "role": member.role,
    }


def _serialize_project_module(
    session: Session,
    module: ProjectModule,
    *,
    tasks: Sequence[ProjectTask] | None = None,
    project_version: int | None = None,
) -> dict[str, Any]:
    tasks = sorted(
        module.tasks if tasks is None else tasks,
        key=lambda task: (task.sort_order, task.id),
    )
    task_ids = {task.id for task in tasks}
    dependency_ids = {task.id: [] for task in tasks}
    incomplete_dependency_ids = {task.id: [] for task in tasks}
    if task_ids:
        for dependency in session.scalars(
            select(ProjectTaskDependency)
            .where(ProjectTaskDependency.successor_task_id.in_(task_ids))
            .options(
                selectinload(ProjectTaskDependency.predecessor_task)
            )
        ):
            dependency_ids[dependency.successor_task_id].append(
                dependency.predecessor_task_id
            )
            if dependency.predecessor_task.status != "completed":
                incomplete_dependency_ids[dependency.successor_task_id].append(
                    dependency.predecessor_task_id
                )
    result = {
        "id": module.id,
        "module_key": module.module_catalog.module_key,
        "name": module.name,
        "description": module.description,
        "status": module.status,
        "sort_order": module.sort_order,
        "planned_start_date": (
            module.planned_start_date.isoformat()
            if module.planned_start_date is not None
            else None
        ),
        "planned_end_date": (
            module.planned_end_date.isoformat()
            if module.planned_end_date is not None
            else None
        ),
        "tasks": [
            {
                "id": task.id,
                "project_module_id": task.project_module_id,
                "module_key": module.module_catalog.module_key,
                "task_key": task.task_key,
                "name": task.name,
                "description": task.description,
                "status": task.status,
                "planned_start_date": task.planned_start_date.isoformat(),
                "planned_end_date": task.planned_end_date.isoformat(),
                "duration_days": task.duration_days,
                "default_assignee_role": task.default_assignee_role,
                "assignee_user_id": task.assignee_user_id,
                "pending_assignment": task.assignee_user_id is None,
                "progress": task.progress,
                "blocked_reason": task.blocked_reason,
                "completed_at": (
                    task.completed_at.isoformat()
                    if task.completed_at is not None
                    else None
                ),
                "sort_order": task.sort_order,
                "dependency_ids": sorted(dependency_ids[task.id]),
                "dependency_risk": bool(incomplete_dependency_ids[task.id]),
                "incomplete_dependency_ids": sorted(
                    incomplete_dependency_ids[task.id]
                ),
                "version": task.version,
            }
            for task in tasks
        ],
    }
    if project_version is not None:
        result["project_version"] = project_version
    return result


def _dependency_metadata(
    session: Session, tasks: Sequence[ProjectTask]
) -> dict[str, dict[str, list[str]]]:
    task_ids = {task.id for task in tasks}
    result = {
        task.id: {"ids": [], "keys": [], "incomplete_ids": []}
        for task in tasks
    }
    if not task_ids:
        return result
    tasks_by_id = {task.id: task for task in tasks}
    dependencies = session.scalars(
        select(ProjectTaskDependency).where(
            ProjectTaskDependency.successor_task_id.in_(task_ids),
            ProjectTaskDependency.predecessor_task_id.in_(task_ids),
        )
    )
    for dependency in dependencies:
        predecessor = tasks_by_id[dependency.predecessor_task_id]
        metadata = result[dependency.successor_task_id]
        metadata["ids"].append(predecessor.id)
        metadata["keys"].append(predecessor.task_key)
        if predecessor.status != "completed":
            metadata["incomplete_ids"].append(predecessor.id)
    for metadata in result.values():
        for values in metadata.values():
            values.sort()
    return result


def _required_text(value: Any, *, maximum: int | None = None) -> str:
    if not isinstance(value, str):
        raise ValueError
    result = normalize("NFKC", value).strip()
    if not result or (maximum is not None and len(result) > maximum):
        raise ValueError
    return result


def _optional_text(value: Any, maximum: int | None = None) -> str:
    if not isinstance(value, str):
        raise ValueError
    result = normalize("NFKC", value).strip()
    if maximum is not None and len(result) > maximum:
        raise ValueError
    return result


def _date_value(value: Any) -> date:
    if not isinstance(value, str):
        raise ValueError
    return date.fromisoformat(value)


def _optional_date_value(value: Any) -> date | None:
    return None if value is None else _date_value(value)


def _module_keys(value: Any) -> list[str]:
    if (
        not isinstance(value, list)
        or not value
        or any(not isinstance(key, str) or not key for key in value)
        or len(set(value)) != len(value)
    ):
        raise ValueError
    return value


def _generated_project_code() -> str:
    return f"FDE-{date.today():%Y%m%d}-{uuid4().hex[:8].upper()}"


def _escape_like_literal(value: str) -> str:
    return value.replace("!", "!!").replace("%", "!%").replace("_", "!_")


def _json_value(value: Any) -> Any:
    return value.isoformat() if isinstance(value, date) else value


def _invalid_request_error() -> ProjectServiceError:
    return ProjectServiceError("invalid_request", "The request body is invalid.", 400)


def _forbidden_error() -> ProjectServiceError:
    return ProjectServiceError(
        "forbidden", "You do not have permission to access this resource.", 403
    )
