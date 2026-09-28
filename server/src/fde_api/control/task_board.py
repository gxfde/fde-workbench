"""Task-board reads and narrowly scoped, versioned status edits.

Project execution status and automation scheduling status are deliberately separate.
Moving an automation never changes an existing run or pretends it has completed.
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from flask import Blueprint, g, jsonify, request
from sqlalchemy import or_, select
from sqlalchemy.orm import joinedload, selectinload

from fde_api.auth.decorators import require_auth
from fde_api.auth.models import User
from fde_api.control.access import authorize_ai_capability
from fde_api.control.models import AutomationTask
from fde_api.control.scheduler import next_schedule_time
from fde_api.control.service import (
    ControlServiceError, _project_scope, _serialize_automation_task, _serialize_project_task,
)
from fde_api.errors import error_response
from fde_api.extensions import db
from fde_api.projects.permissions import project_access
from fde_api.projects.service import ProjectServiceError
from fde_api.projects.task_service import TASK_STATUSES, update_project_task
from fde_api.workbench.models import OperationEvent, Project, ProjectModule, ProjectTask


task_board_blueprint = Blueprint("task_board", __name__, url_prefix="/api/v1/task-center/board")
AUTOMATION_STATUSES = frozenset({"active", "paused", "archived"})


@task_board_blueprint.get("")
@require_auth
def task_board_route():
    return jsonify({"data": list_task_board(user=g.current_user), "error": None})


@task_board_blueprint.patch("/<kind>/<task_id>/status")
@require_auth
def task_board_status_route(kind: str, task_id: str):
    payload = request.get_json(silent=True)
    try:
        result = update_board_status(user=g.current_user, kind=kind, task_id=task_id, payload=payload)
        return jsonify({"data": result, "error": None})
    except (ControlServiceError, ProjectServiceError) as error:
        messages = {
            "forbidden": "你没有修改此任务状态的权限。",
            "stale_version": "任务已被其他人更新，请重新查看最新状态后再操作。",
            "task_cancelled": "任务已取消，不能再修改状态。",
            "invalid_task_state": "任务状态或阻塞原因无效，请检查后重试。",
        }
        return error_response(error.code, messages.get(error.code, error.message), error.status)


def _can_edit_project(user: User, task: ProjectTask) -> bool:
    access = project_access(user, task.project_module.project)
    return task.status != "cancelled" and (
        access.can_manage or (
            access.can_update_assigned_tasks and (
                task.assignee_user_id == user.id
                or any(collaborator.user_id == user.id for collaborator in task.collaborators)
            )
        )
    )


def _can_edit_automation(user: User, task: AutomationTask) -> bool:
    return user.is_active and (user.role == "admin" or authorize_ai_capability(
        user=user, capability="project.schedule.manage", project=task.project,
    ).allowed)


def _project_item(user: User, task: ProjectTask) -> dict[str, Any]:
    return {
        **_serialize_project_task(task), "version": task.version,
        "progress": task.progress, "blocked_reason": task.blocked_reason,
        "can_edit": _can_edit_project(user, task),
    }


def _automation_item(user: User, task: AutomationTask) -> dict[str, Any]:
    allowed = _can_edit_automation(user, task)
    return {**_serialize_automation_task(task, can_run=allowed), "version": task.version,
            "can_edit": allowed, "assignee_name": "AI Server"}


def list_task_board(*, user: User) -> dict[str, Any]:
    session = db.session()
    try:
        scope = _project_scope(user)
        project_tasks = list(session.scalars(
            select(ProjectTask)
            .join(ProjectModule, ProjectTask.project_module_id == ProjectModule.id)
            .join(Project, ProjectModule.project_id == Project.id)
            .where(scope)
            .options(
                joinedload(ProjectTask.project_module).joinedload(ProjectModule.project).selectinload(Project.members),
                joinedload(ProjectTask.assignee), selectinload(ProjectTask.collaborators),
            )
        ).unique())
        automation_scope = True if user.role == "admin" else or_(
            AutomationTask.created_by_user_id == user.id,
            AutomationTask.project_id.in_(select(Project.id).where(scope)),
        )
        automations = list(session.scalars(select(AutomationTask).where(automation_scope).options(
            joinedload(AutomationTask.project).selectinload(Project.members),
        )).unique())
        items = [_project_item(user, task) for task in project_tasks]
        items.extend(_automation_item(user, task) for task in automations)
        items.sort(key=lambda item: (item["updated_at"], item["id"]), reverse=True)
        return {"items": items, "total": len(items), "counts": {"project": len(project_tasks), "automation": len(automations)}}
    finally:
        session.close()


def update_board_status(*, user: User, kind: str, task_id: str, payload: Any) -> dict[str, Any]:
    if kind not in {"project", "automation"}:
        raise ControlServiceError("invalid_task_kind", "不支持的任务类型。", 400)
    if (not isinstance(payload, dict) or set(payload) - {"status", "version", "blocked_reason"}
            or type(payload.get("version")) is not int or payload["version"] < 1
            or not isinstance(payload.get("status"), str)):
        raise ControlServiceError("invalid_request", "请提供任务状态和当前版本。", 400)
    status = payload["status"]
    if status not in (TASK_STATUSES if kind == "project" else AUTOMATION_STATUSES):
        raise ControlServiceError("invalid_task_state", "此状态不适用于该类任务。", 400)
    if "blocked_reason" in payload and (
        kind != "project" or status != "blocked" or not isinstance(payload["blocked_reason"], str)
        or not payload["blocked_reason"].strip() or len(payload["blocked_reason"]) > 2000
    ):
        raise ControlServiceError("invalid_task_state", "请填写有效的阻塞原因。", 400)
    if kind == "automation":
        return _update_automation_status(user=user, task_id=task_id, status=status, version=payload["version"])

    session = db.session()
    try:
        task = session.scalar(select(ProjectTask).where(ProjectTask.id == task_id).options(
            joinedload(ProjectTask.project_module).joinedload(ProjectModule.project).selectinload(Project.members),
            selectinload(ProjectTask.collaborators),
        ))
        if task is None or not project_access(user, task.project_module.project).can_view:
            raise ControlServiceError("task_not_found", "任务不存在或无权查看。", 404)
        if not _can_edit_project(user, task):
            raise ControlServiceError("forbidden", "你没有修改此任务状态的权限。", 403)
        project_id = task.project_module.project_id
        changes: dict[str, Any] = {"status": status}
        if status == "in_progress":
            # The project service requires an actual 1–99 progress value.
            changes["progress"] = task.progress if 1 <= task.progress <= 99 else 1
        if status == "blocked":
            changes["blocked_reason"] = payload.get("blocked_reason", task.blocked_reason)
            if not changes["blocked_reason"].strip():
                raise ControlServiceError("invalid_task_state", "请先填写阻塞原因。", 400)
    finally:
        session.close()
    # The established service rechecks project membership and atomically compares
    # the version, updates progress/completion timestamps and writes an audit event.
    saved = update_project_task(actor=user, project_id=project_id, task_id=task_id,
                                expected_version=payload["version"], changes=changes)
    return {"id": saved["id"], "kind": "project", "status": saved["status"],
            "version": saved["version"], "progress": saved["progress"],
            "blocked_reason": saved["blocked_reason"], "can_edit": saved["status"] != "cancelled"}


def _update_automation_status(*, user: User, task_id: str, status: str, version: int) -> dict[str, Any]:
    session = db.session()
    try:
        with session.begin():
            task = session.scalar(select(AutomationTask).where(AutomationTask.id == task_id).options(
                joinedload(AutomationTask.project).selectinload(Project.members),
            ).with_for_update())
            if task is None or not (
                user.role == "admin" or task.created_by_user_id == user.id
                or task.project is not None and project_access(user, task.project).can_view
            ):
                raise ControlServiceError("automation_not_found", "任务不存在或无权查看。", 404)
            if not _can_edit_automation(user, task):
                raise ControlServiceError("forbidden", "你没有修改此自动任务的权限。", 403)
            if task.version != version:
                raise ControlServiceError("stale_version", "任务已更新，请重新查看后再操作。", 409)
            if task.status == status:
                return _automation_item(user, task)
            previous = task.status
            if status == "active":
                now = datetime.now(UTC)
                try:
                    next_run = next_schedule_time(kind=task.schedule_kind, expression=task.schedule_expression,
                                                  timezone=task.timezone, after=now)
                except (ValueError, OverflowError):
                    raise ControlServiceError("invalid_schedule", "任务计划无效，无法重新启用。", 409) from None
                if next_run is not None and next_run <= now:
                    raise ControlServiceError("schedule_expired", "此一次性任务的计划时间已过，不能重新启用。", 409)
                task.next_run_at = next_run
            else:
                task.next_run_at = None
            task.status = status
            task.version += 1
            session.add(OperationEvent(
                actor_user_id=user.id, project_id=task.project_id, target_type="automation_task",
                target_id=task.id, event_type="automation_status_updated",
                changes={"previous_status": previous, "status": status, "version": task.version},
            ))
            session.flush()
            session.refresh(task)
            return _automation_item(user, task)
    finally:
        session.close()
