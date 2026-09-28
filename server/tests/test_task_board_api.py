from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from fde_api.control.models import AutomationTask, AutomationTaskRun
from fde_api.control.task_board import task_board_blueprint
from fde_api.workbench.models import OperationEvent, ProjectMember, ProjectTask, ProjectTaskCollaborator

from test_control_plane_api import authorized_client_factory, create_project_with_task  # noqa: F401


@pytest.fixture(autouse=True)
def board_routes(app):
    # Keep this module independently runnable before application registration.
    if task_board_blueprint.name not in app.blueprints:
        app.register_blueprint(task_board_blueprint)


def task_url(task: ProjectTask) -> str:
    return f"/api/v1/task-center/board/project/{task.id}/status"


def automation_url(task: AutomationTask) -> str:
    return f"/api/v1/task-center/board/automation/{task.id}/status"


def create_automation(db_session, user, project, *, kind="interval", expression="1d", status="active"):
    task = AutomationTask(
        project_id=project.id, created_by_user_id=user.id, title="每日项目检查",
        source="desktop", task_type="ai", status=status, schedule_kind=kind,
        schedule_expression=expression, timezone="Asia/Shanghai", prompt="检查项目现状",
        next_run_at=datetime.now(UTC) + timedelta(days=1), requested_capabilities=["project.read"],
    )
    db_session.add(task)
    db_session.commit()
    return task


def test_board_returns_live_versions_permissions_and_separate_statuses(authorized_client_factory, db_session):
    leader = authorized_client_factory("project_lead")
    project, task = create_project_with_task(db_session, leader.user)
    automation = create_automation(db_session, leader.user, project)

    response = leader.get("/api/v1/task-center/board")

    assert response.status_code == 200
    data = response.json["data"]
    assert data["counts"] == {"project": 1, "automation": 1}
    items = {item["id"]: item for item in data["items"]}
    assert items[task.id]["status"] == "not_started"
    assert items[task.id]["version"] == task.version
    assert items[task.id]["can_edit"] is True
    assert items[automation.id]["status"] == "active"
    assert items[automation.id]["assignee_name"] == "AI Server"


def test_board_hides_unrelated_projects_and_denies_direct_status_mutation(authorized_client_factory, db_session):
    owner = authorized_client_factory("project_lead")
    outsider = authorized_client_factory("project_lead")
    _, task = create_project_with_task(db_session, owner.user)

    assert outsider.get("/api/v1/task-center/board").json["data"]["items"] == []
    response = outsider.patch(task_url(task), json={"status": "completed", "version": task.version})
    assert response.status_code == 404
    db_session.expire_all()
    assert task.status == "not_started"


def test_project_status_edit_updates_progress_and_writes_existing_audit_event(authorized_client_factory, db_session):
    leader = authorized_client_factory("project_lead")
    _, task = create_project_with_task(db_session, leader.user)
    original_version = task.version

    response = leader.patch(task_url(task), json={"status": "in_progress", "version": original_version})

    assert response.status_code == 200, response.json
    assert response.json["data"]["progress"] == 1
    assert response.json["data"]["version"] == original_version + 1
    completed = leader.patch(task_url(task), json={"status": "completed", "version": original_version + 1})
    assert completed.status_code == 200, completed.json
    assert completed.json["data"]["progress"] == 100
    db_session.expire_all()
    assert task.completed_at is not None
    events = list(db_session.scalars(select(OperationEvent).where(OperationEvent.target_id == task.id)))
    assert len(events) == 2
    assert {event.event_type for event in events} == {"project_task_updated"}


def test_project_version_conflict_does_not_overwrite_newer_status(authorized_client_factory, db_session):
    leader = authorized_client_factory("project_lead")
    _, task = create_project_with_task(db_session, leader.user)
    version = task.version
    assert leader.patch(task_url(task), json={"status": "completed", "version": version}).status_code == 200

    stale = leader.patch(task_url(task), json={"status": "in_progress", "version": version})

    assert stale.status_code == 409
    assert stale.json["error"]["code"] == "stale_version"
    assert "其他人更新" in stale.json["error"]["message"]
    db_session.expire_all()
    assert task.status == "completed"
    assert task.progress == 100


def test_blocked_requires_a_reason_and_cancelled_is_read_only(authorized_client_factory, db_session):
    leader = authorized_client_factory("project_lead")
    _, task = create_project_with_task(db_session, leader.user)
    version = task.version
    assert leader.patch(task_url(task), json={"status": "blocked", "version": version}).status_code == 400
    blocked = leader.patch(task_url(task), json={"status": "blocked", "version": version, "blocked_reason": "等待客户资料"})
    assert blocked.status_code == 200, blocked.json
    assert blocked.json["data"]["blocked_reason"] == "等待客户资料"
    cancelled = leader.patch(task_url(task), json={"status": "cancelled", "version": version + 1})
    assert cancelled.status_code == 200, cancelled.json
    assert cancelled.json["data"]["can_edit"] is False
    assert leader.patch(task_url(task), json={"status": "in_progress", "version": version + 2}).status_code == 403


@pytest.mark.parametrize("assigned,collaborator,allowed", [(True, False, True), (False, True, True), (False, False, False)])
def test_engineer_can_only_move_assigned_or_collaborated_tasks(authorized_client_factory, db_session, assigned, collaborator, allowed):
    leader = authorized_client_factory("project_lead")
    engineer = authorized_client_factory("fde_engineer")
    project, task = create_project_with_task(db_session, leader.user)
    db_session.add(ProjectMember(project_id=project.id, user_id=engineer.user.id, role="member"))
    if assigned:
        task.assignee_user_id = engineer.user.id
    if collaborator:
        db_session.add(ProjectTaskCollaborator(task_id=task.id, user_id=engineer.user.id))
    db_session.commit()

    listing = engineer.get("/api/v1/task-center/board")
    assert listing.json["data"]["items"][0]["can_edit"] is allowed
    changed = engineer.patch(task_url(task), json={"status": "completed", "version": task.version})
    assert changed.status_code == (200 if allowed else 403), changed.json


def test_viewer_can_read_but_cannot_move_tasks(authorized_client_factory, db_session):
    leader = authorized_client_factory("project_lead")
    viewer = authorized_client_factory("viewer")
    project, task = create_project_with_task(db_session, leader.user)
    db_session.add(ProjectMember(project_id=project.id, user_id=viewer.user.id, role="viewer"))
    db_session.commit()
    assert viewer.get("/api/v1/task-center/board").json["data"]["items"][0]["can_edit"] is False
    assert viewer.patch(task_url(task), json={"status": "completed", "version": task.version}).status_code == 403


def test_automation_pause_and_resume_change_schedule_not_run_history(authorized_client_factory, db_session):
    leader = authorized_client_factory("project_lead")
    project, _ = create_project_with_task(db_session, leader.user)
    task = create_automation(db_session, leader.user, project)
    run = AutomationTaskRun(task_id=task.id, requested_by_user_id=leader.user.id,
                            status="running", scheduled_for=datetime.now(UTC), idempotency_key=f"board-test:{task.id}")
    db_session.add(run)
    db_session.commit()
    version = task.version

    paused = leader.patch(automation_url(task), json={"status": "paused", "version": version})
    assert paused.status_code == 200, paused.json
    assert paused.json["data"]["next_run_at"] is None
    assert paused.json["data"]["can_run"] is False
    stale = leader.patch(automation_url(task), json={"status": "archived", "version": version})
    assert stale.status_code == 409
    resumed = leader.patch(automation_url(task), json={"status": "active", "version": version + 1})
    assert resumed.status_code == 200, resumed.json
    assert resumed.json["data"]["next_run_at"] is not None
    db_session.expire_all()
    assert run.status == "running"
    assert task.next_run_at > datetime.now(UTC)
    events = list(db_session.scalars(select(OperationEvent).where(OperationEvent.target_id == task.id)))
    assert len(events) == 2
    assert {event.event_type for event in events} == {"automation_status_updated"}


def test_automation_rejects_execution_states_and_expired_once_schedule(authorized_client_factory, db_session):
    leader = authorized_client_factory("project_lead")
    project, _ = create_project_with_task(db_session, leader.user)
    task = create_automation(db_session, leader.user, project, kind="once",
                             expression="2020-01-01T00:00:00+08:00", status="paused")
    wrong_kind = leader.patch(automation_url(task), json={"status": "completed", "version": task.version})
    assert wrong_kind.status_code == 400
    expired = leader.patch(automation_url(task), json={"status": "active", "version": task.version})
    assert expired.status_code == 409
    assert expired.json["error"]["code"] == "schedule_expired"
    db_session.expire_all()
    assert task.status == "paused"


@pytest.mark.parametrize("payload", [None, [], {}, {"status": "completed", "version": True},
                                     {"status": "completed", "version": 0}, {"status": [], "version": 1},
                                     {"status": "completed", "version": 1, "assignee_user_id": "other"}])
def test_status_endpoint_rejects_malformed_or_broad_payloads(authorized_client_factory, db_session, payload):
    leader = authorized_client_factory("project_lead")
    _, task = create_project_with_task(db_session, leader.user)
    response = leader.patch(task_url(task), json=payload)
    assert response.status_code == 400
