from __future__ import annotations

from dataclasses import dataclass
from copy import deepcopy
from uuid import uuid4

import pytest
from sqlalchemy import event, func, select
from sqlalchemy.orm.attributes import flag_modified

from fde_api.auth.models import User
from fde_api.auth.passwords import hash_password
from fde_api.auth.tokens import issue_access_token
from fde_api.projects.service import project_completion
from fde_api.workbench.models import (
    IndustryTemplateVersion,
    OperationEvent,
    Project,
    ProjectModule,
    ProjectTask,
    TemplateTask,
)
from fde_api.workbench.seed import seed_workbench


INITIAL_PASSWORD = "InitialPass!234"


@dataclass(frozen=True)
class AuthorizedClient:
    client: object
    user: User
    headers: dict[str, str]

    def post(self, *args, **kwargs):
        return self.client.post(*args, headers=self.headers, **kwargs)

    def delete(self, *args, **kwargs):
        return self.client.delete(*args, headers=self.headers, **kwargs)


@pytest.fixture
def authorized_client_factory(client, db_session, settings):
    def create(role: str) -> AuthorizedClient:
        user = User(
            username=f"{role}.{uuid4().hex}",
            display_name=role,
            role=role,
            password_hash=hash_password(INITIAL_PASSWORD),
            must_change_password=False,
            is_active=True,
        )
        db_session.add(user)
        db_session.commit()
        return AuthorizedClient(
            client,
            user,
            {"Authorization": f"Bearer {issue_access_token(user, settings)}"},
        )

    return create


@pytest.fixture
def admin_client(authorized_client_factory):
    return authorized_client_factory("admin")


@pytest.fixture
def leader_client(authorized_client_factory):
    return authorized_client_factory("project_lead")


@pytest.fixture
def engineer_client(authorized_client_factory):
    return authorized_client_factory("fde_engineer")


@pytest.fixture
def published_template(db_session):
    seed_workbench(db_session)
    db_session.commit()
    return db_session.scalar(
        select(IndustryTemplateVersion).where(
            IndustryTemplateVersion.status == "published"
        )
    )


def assert_error(response, status: int, code: str) -> None:
    assert response.status_code == status, response.get_data(as_text=True)
    assert response.json["data"] is None
    assert response.json["error"]["code"] == code


def create_project(client, template, leader, *, module_keys=None):
    response = client.post(
        "/api/v1/projects",
        json={
            "name": "模块追加试点",
            "enterprise_name": "星河制造",
            "template_version_id": template.id,
            "leader_user_id": leader.id,
            "planned_start_date": "2026-08-21",
            "module_keys": module_keys or ["pre_diagnosis"],
        },
    )
    assert response.status_code == 201, response.get_data(as_text=True)
    return response.json["data"]


def append_module(
    client,
    project_id: str,
    module_key: str = "production_deployment",
    *,
    version: int = 1,
):
    return client.post(
        f"/api/v1/projects/{project_id}/modules",
        json={
            "module_key": module_key,
            "planned_start_date": "2026-09-14",
            "version": version,
        },
    )


def task_dates(db_session, project_id: str, *, exclude_module: str | None = None):
    db_session.rollback()
    statement = (
        select(ProjectTask, ProjectModule)
        .join(ProjectModule)
        .where(ProjectModule.project_id == project_id)
        .order_by(ProjectTask.id)
    )
    rows = db_session.execute(statement).all()
    return {
        task.id: (task.planned_start_date.isoformat(), task.planned_end_date.isoformat())
        for task, module in rows
        if module.module_catalog.module_key != exclude_module
    }


def add_snapshot_dependency(
    db_session, project_id: str, *, module_key: str, task_key: str, predecessor_key: str
) -> None:
    db_session.rollback()
    project = db_session.get(Project, project_id)
    snapshot = deepcopy(project.template_snapshot)
    task = next(
        task
        for module in snapshot["modules"]
        if module["module_key"] == module_key
        for task in module["tasks"]
        if task["task_key"] == task_key
    )
    task["dependency_keys"] = [predecessor_key]
    project.template_snapshot = snapshot
    flag_modified(project, "template_snapshot")
    db_session.commit()


def test_append_module_uses_snapshot_and_preserves_existing_task_dates(
    admin_client, leader_client, published_template, db_session
):
    """Reading the live template or globally rescheduling would rewrite project history."""
    project = create_project(admin_client, published_template, leader_client.user)
    before = task_dates(db_session, project["id"])
    live_task = db_session.scalar(
        select(TemplateTask).where(
            TemplateTask.task_key == "confirm_production_architecture"
        )
    )
    live_task.name = "被篡改的实时模板任务"
    db_session.commit()

    response = append_module(admin_client, project["id"])

    assert response.status_code == 201, response.get_data(as_text=True)
    assert response.json["data"]["module_key"] == "production_deployment"
    assert response.json["data"]["project_version"] == project["version"] + 1
    assert response.json["data"]["tasks"][0]["name"] == "确认生产架构与安全方案"
    db_session.expire_all()
    assert task_dates(
        db_session, project["id"], exclude_module="production_deployment"
    ) == before
    events = list(
        db_session.scalars(
            select(OperationEvent).where(
                OperationEvent.project_id == project["id"],
                OperationEvent.event_type == "project_module_appended",
            )
        )
    )
    assert len(events) == 1


def test_append_module_requires_active_cross_module_predecessors_and_uses_their_dates(
    admin_client, leader_client, published_template, db_session
):
    """Dropping or ignoring a snapshot cross-module edge corrupts dependency closure."""
    missing_project = create_project(
        admin_client,
        published_template,
        leader_client.user,
        module_keys=["pre_diagnosis"],
    )
    add_snapshot_dependency(
        db_session,
        missing_project["id"],
        module_key="production_deployment",
        task_key="confirm_production_architecture",
        predecessor_key="deliver_pov_conclusion",
    )
    assert_error(
        append_module(admin_client, missing_project["id"]),
        400,
        "missing_required_module_dependency",
    )

    dated_project = create_project(
        admin_client,
        published_template,
        leader_client.user,
        module_keys=["pre_diagnosis"],
    )
    add_snapshot_dependency(
        db_session,
        dated_project["id"],
        module_key="production_deployment",
        task_key="confirm_production_architecture",
        predecessor_key="deliver_pre_diagnosis",
    )
    predecessor = db_session.scalar(
        select(ProjectTask)
        .join(ProjectModule)
        .where(
            ProjectModule.project_id == dated_project["id"],
            ProjectTask.task_key == "deliver_pre_diagnosis",
        )
    )
    predecessor.planned_end_date = predecessor.planned_start_date
    db_session.commit()

    response = admin_client.post(
        f"/api/v1/projects/{dated_project['id']}/modules",
        json={
            "module_key": "production_deployment",
            "planned_start_date": predecessor.planned_start_date.isoformat(),
            "version": dated_project["version"],
        },
    )

    assert response.status_code == 201, response.get_data(as_text=True)
    added = response.json["data"]["tasks"][0]
    assert added["planned_start_date"] > predecessor.planned_end_date.isoformat()
    assert added["dependency_ids"] == [predecessor.id]
    assert added["dependency_risk"] is True
    assert added["incomplete_dependency_ids"] == [predecessor.id]


def test_cancelled_module_is_retained_cancels_tasks_and_cannot_be_readded(
    admin_client, engineer_client, leader_client, published_template, db_session
):
    """Deleting or re-adding a cancelled module would erase execution history."""
    project = create_project(admin_client, published_template, leader_client.user)
    db_session.rollback()
    module = db_session.scalar(
        select(ProjectModule).where(ProjectModule.project_id == project["id"])
    )
    first_task = db_session.scalar(
        select(ProjectTask).where(ProjectTask.project_module_id == module.id)
    )
    first_task.status = "in_progress"
    first_task.progress = 40
    db_session.commit()

    assert_error(
        engineer_client.delete(
            f"/api/v1/projects/{project['id']}/modules/{module.id}",
            json={"version": project["version"]},
        ),
        403,
        "forbidden",
    )
    cancelled = leader_client.delete(
        f"/api/v1/projects/{project['id']}/modules/{module.id}",
        json={"version": project["version"]},
    )

    assert cancelled.status_code == 200, cancelled.get_data(as_text=True)
    assert cancelled.json["data"]["status"] == "cancelled"
    assert cancelled.json["data"]["project_version"] == project["version"] + 1
    db_session.expire_all()
    assert db_session.get(ProjectModule, module.id).status == "cancelled"
    assert {
        task.status
        for task in db_session.scalars(
            select(ProjectTask).where(ProjectTask.project_module_id == module.id)
        )
    } == {"cancelled"}
    assert db_session.get(ProjectTask, first_task.id).progress == 40
    assert project_completion(project["id"]) == 0
    assert_error(
        append_module(
            admin_client,
            project["id"],
            "pre_diagnosis",
            version=cancelled.json["data"]["project_version"],
        ),
        409,
        "project_module_already_exists",
    )
    module_events = list(
        db_session.scalars(
            select(OperationEvent).where(
                OperationEvent.project_id == project["id"],
                OperationEvent.event_type == "project_module_cancelled",
            )
        )
    )
    assert len(module_events) == 1


def test_cancelled_predecessor_module_blocks_dependent_append(
    admin_client, leader_client, published_template, db_session
):
    """A retained but cancelled predecessor cannot satisfy dependency closure."""
    project = create_project(admin_client, published_template, leader_client.user)
    add_snapshot_dependency(
        db_session,
        project["id"],
        module_key="production_deployment",
        task_key="confirm_production_architecture",
        predecessor_key="deliver_pre_diagnosis",
    )
    db_session.rollback()
    module = db_session.scalar(
        select(ProjectModule).where(ProjectModule.project_id == project["id"])
    )
    assert (
        leader_client.delete(
            f"/api/v1/projects/{project['id']}/modules/{module.id}",
            json={"version": project["version"]},
        ).status_code
        == 200
    )

    assert_error(
        append_module(admin_client, project["id"], version=project["version"] + 1),
        400,
        "missing_required_module_dependency",
    )


def test_cancelled_cross_module_predecessor_task_blocks_append(
    admin_client, leader_client, published_template, db_session
):
    """An existing module cannot satisfy closure with a cancelled predecessor task."""
    project = create_project(admin_client, published_template, leader_client.user)
    add_snapshot_dependency(
        db_session,
        project["id"],
        module_key="production_deployment",
        task_key="confirm_production_architecture",
        predecessor_key="deliver_pre_diagnosis",
    )
    predecessor = db_session.scalar(
        select(ProjectTask)
        .join(ProjectModule)
        .where(
            ProjectModule.project_id == project["id"],
            ProjectTask.task_key == "deliver_pre_diagnosis",
        )
    )
    predecessor.status = "cancelled"
    db_session.commit()

    assert_error(
        append_module(admin_client, project["id"]),
        400,
        "missing_required_module_dependency",
    )


def test_append_failure_rolls_back_module_tasks_dependencies_and_event(
    admin_client, leader_client, published_template, db_session, monkeypatch
):
    """A scheduling failure must not leave any part of the appended module tree."""
    from fde_api.projects import service

    project = create_project(admin_client, published_template, leader_client.user)
    db_session.rollback()
    before = {
        model: db_session.scalar(select(func.count()).select_from(model))
        for model in (ProjectModule, ProjectTask, OperationEvent)
    }

    def fail_scheduling(*_args, **_kwargs):
        raise RuntimeError("forced append scheduling failure")

    monkeypatch.setattr(service, "schedule_tasks", fail_scheduling)
    response = append_module(admin_client, project["id"])

    assert_error(response, 503, "project_module_append_failed")
    db_session.rollback()
    for model, count in before.items():
        assert db_session.scalar(select(func.count()).select_from(model)) == count


def test_append_and_cancel_reject_stale_project_versions_without_writes_or_events(
    admin_client, leader_client, published_template, db_session
):
    project = create_project(admin_client, published_template, leader_client.user)
    db_session.rollback()
    module = db_session.scalar(
        select(ProjectModule).where(ProjectModule.project_id == project["id"])
    )
    project_row = db_session.get(Project, project["id"])
    project_row.version += 1
    db_session.commit()
    before = {
        model: db_session.scalar(select(func.count()).select_from(model))
        for model in (ProjectModule, ProjectTask, OperationEvent)
    }

    assert_error(
        append_module(admin_client, project["id"], version=project["version"]),
        409,
        "stale_version",
    )
    assert_error(
        leader_client.delete(
            f"/api/v1/projects/{project['id']}/modules/{module.id}",
            json={"version": project["version"]},
        ),
        409,
        "stale_version",
    )

    db_session.rollback()
    assert db_session.get(ProjectModule, module.id).status == "active"
    for model, count in before.items():
        assert db_session.scalar(select(func.count()).select_from(model)) == count


@pytest.mark.parametrize("invalid_version", [None, True, 0, -1, "1"])
def test_module_mutations_require_a_positive_integer_project_version(
    invalid_version,
    admin_client,
    leader_client,
    published_template,
    db_session,
):
    project = create_project(admin_client, published_template, leader_client.user)
    db_session.rollback()
    module = db_session.scalar(
        select(ProjectModule).where(ProjectModule.project_id == project["id"])
    )
    append_payload = {
        "module_key": "production_deployment",
        "planned_start_date": "2026-09-14",
    }
    cancel_payload = {}
    if invalid_version is not None:
        append_payload["version"] = invalid_version
        cancel_payload["version"] = invalid_version

    assert_error(
        admin_client.post(
            f"/api/v1/projects/{project['id']}/modules", json=append_payload
        ),
        400,
        "invalid_request",
    )
    assert_error(
        leader_client.delete(
            f"/api/v1/projects/{project['id']}/modules/{module.id}",
            json=cancel_payload,
        ),
        400,
        "invalid_request",
    )


def test_cancel_module_explicitly_locks_task_rows_before_incrementing_versions(
    admin_client, leader_client, published_template, db_session
):
    project = create_project(admin_client, published_template, leader_client.user)
    db_session.rollback()
    module = db_session.scalar(
        select(ProjectModule).where(ProjectModule.project_id == project["id"])
    )
    before_versions = {
        task.id: task.version
        for task in db_session.scalars(
            select(ProjectTask).where(ProjectTask.project_module_id == module.id)
        )
    }
    statements: list[str] = []

    def capture_statement(_conn, _cursor, statement, _parameters, _context, _many):
        statements.append(" ".join(statement.lower().split()))

    event.listen(db_session.bind, "before_cursor_execute", capture_statement)
    try:
        response = leader_client.delete(
            f"/api/v1/projects/{project['id']}/modules/{module.id}",
            json={"version": project["version"]},
        )
    finally:
        event.remove(db_session.bind, "before_cursor_execute", capture_statement)

    assert response.status_code == 200, response.get_data(as_text=True)
    assert any(
        "from project_tasks" in statement and "for update" in statement
        for statement in statements
    )
    db_session.rollback()
    assert {
        task.id: task.version
        for task in db_session.scalars(
            select(ProjectTask).where(ProjectTask.project_module_id == module.id)
        )
    } == {task_id: version + 1 for task_id, version in before_versions.items()}
