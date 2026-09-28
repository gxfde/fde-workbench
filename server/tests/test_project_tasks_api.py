from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4

import pytest
from sqlalchemy import event, func, select

from fde_api.auth.models import User
from fde_api.auth.passwords import hash_password
from fde_api.auth.tokens import issue_access_token
from fde_api.workbench.models import (
    IndustryTemplateVersion,
    OperationEvent,
    ProjectMember,
    ProjectModule,
    ProjectTask,
    ProjectTaskCollaborator,
    ProjectTaskDependency,
)
from fde_api.workbench.seed import seed_workbench


INITIAL_PASSWORD = "InitialPass!234"


@dataclass(frozen=True)
class AuthorizedClient:
    client: object
    user: User
    headers: dict[str, str]

    def get(self, *args, **kwargs):
        return self.client.get(*args, headers=self.headers, **kwargs)

    def post(self, *args, **kwargs):
        return self.client.post(*args, headers=self.headers, **kwargs)

    def patch(self, *args, **kwargs):
        return self.client.patch(*args, headers=self.headers, **kwargs)

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
def viewer_client(authorized_client_factory):
    return authorized_client_factory("viewer")


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


def create_project(client, template, leader, *, code: str, module_keys=None):
    response = client.post(
        "/api/v1/projects",
        json={
            "name": "任务执行试点",
            "enterprise_name": "星河制造",
            "project_code": code,
            "template_version_id": template.id,
            "leader_user_id": leader.id,
            "planned_start_date": "2026-08-21",
            "module_keys": module_keys or ["pre_diagnosis"],
        },
    )
    assert response.status_code == 201, response.get_data(as_text=True)
    return response.json["data"]


def project_tasks(db_session, project_id: str) -> list[ProjectTask]:
    db_session.rollback()
    return list(
        db_session.scalars(
            select(ProjectTask)
            .join(ProjectModule)
            .where(ProjectModule.project_id == project_id)
            .order_by(ProjectTask.sort_order, ProjectTask.id)
        )
    )


def add_member(db_session, project_id: str, user: User, *, role: str = "member"):
    db_session.rollback()
    db_session.add(
        ProjectMember(project_id=project_id, user_id=user.id, role=role)
    )
    db_session.commit()


def patch_task(client, project_id: str, task_id: str, version: int, **changes):
    return client.patch(
        f"/api/v1/projects/{project_id}/tasks/{task_id}",
        json={"version": version, **changes},
    )


def batch_assign_tasks(client, project_id: str, member_user_id: str, mode: str, tasks):
    return client.post(
        f"/api/v1/projects/{project_id}/tasks/batch-assignments",
        json={
            "member_user_id": member_user_id,
            "mode": mode,
            "tasks": [
                {"task_id": task.id, "version": task.version}
                for task in tasks
            ],
        },
    )


def test_task_list_and_detail_are_project_scoped_and_viewer_is_read_only(
    admin_client,
    leader_client,
    viewer_client,
    published_template,
    db_session,
):
    """A task ID must not widen access beyond the project named in the URL."""
    visible = create_project(
        admin_client, published_template, leader_client.user, code="TASK-VISIBLE"
    )
    hidden = create_project(
        admin_client, published_template, leader_client.user, code="TASK-HIDDEN"
    )
    add_member(db_session, visible["id"], viewer_client.user, role="viewer")
    visible_task = project_tasks(db_session, visible["id"])[0]
    hidden_task = project_tasks(db_session, hidden["id"])[0]

    listed = viewer_client.get(f"/api/v1/projects/{visible['id']}/tasks")
    detail = viewer_client.get(
        f"/api/v1/projects/{visible['id']}/tasks/{visible_task.id}"
    )

    assert listed.status_code == detail.status_code == 200
    assert {item["id"] for item in listed.json["data"]["items"]} == {
        task.id for task in project_tasks(db_session, visible["id"])
    }
    assert detail.json["data"]["id"] == visible_task.id
    assert_error(
        viewer_client.get(f"/api/v1/projects/{hidden['id']}/tasks"),
        403,
        "forbidden",
    )
    assert_error(
        viewer_client.get(
            f"/api/v1/projects/{visible['id']}/tasks/{hidden_task.id}"
        ),
        404,
        "project_task_not_found",
    )
    assert_error(
        patch_task(
            viewer_client,
            visible["id"],
            visible_task.id,
            visible_task.version,
            progress=20,
        ),
        403,
        "forbidden",
    )


def test_engineer_updates_assigned_or_collaborating_execution_fields_only(
    admin_client,
    leader_client,
    engineer_client,
    published_template,
    db_session,
):
    """Project membership alone must not permit editing unrelated tasks or ownership."""
    project = create_project(
        admin_client, published_template, leader_client.user, code="TASK-OWNER"
    )
    add_member(db_session, project["id"], engineer_client.user)
    assigned, collaborating, unrelated = project_tasks(db_session, project["id"])
    assigned.assignee_user_id = engineer_client.user.id
    db_session.add(
        ProjectTaskCollaborator(
            task_id=collaborating.id, user_id=engineer_client.user.id
        )
    )
    db_session.commit()

    assigned_response = patch_task(
        engineer_client,
        project["id"],
        assigned.id,
        assigned.version,
        progress=20,
    )
    collaborating_response = patch_task(
        engineer_client,
        project["id"],
        collaborating.id,
        collaborating.version,
        progress=40,
    )

    assert assigned_response.status_code == 200
    assert collaborating_response.status_code == 200
    assert assigned_response.json["data"]["status"] == "in_progress"
    assert collaborating_response.json["data"]["progress"] == 40
    assert_error(
        patch_task(
            engineer_client,
            project["id"],
            unrelated.id,
            unrelated.version,
            progress=40,
        ),
        403,
        "forbidden",
    )
    assert_error(
        patch_task(
            engineer_client,
            project["id"],
            assigned.id,
            assigned_response.json["data"]["version"],
            assignee_user_id=leader_client.user.id,
        ),
        403,
        "forbidden",
    )


def test_task_state_rules_and_completion_fields_are_strict(
    admin_client, leader_client, published_template, db_session
):
    """Contradictory status, progress, reason, and completion time corrupt execution state."""
    project = create_project(
        admin_client, published_template, leader_client.user, code="TASK-STATES"
    )
    task = project_tasks(db_session, project["id"])[0]

    assert_error(
        patch_task(
            leader_client,
            project["id"],
            task.id,
            task.version,
            blocked_reason="还没有进入阻塞状态",
        ),
        400,
        "invalid_task_state",
    )
    assert_error(
        patch_task(
            leader_client,
            project["id"],
            task.id,
            task.version,
            status="blocked",
            blocked_reason="   ",
        ),
        400,
        "invalid_task_state",
    )
    blocked = patch_task(
        leader_client,
        project["id"],
        task.id,
        task.version,
        status="blocked",
        blocked_reason="等待客户数据",
    )
    assert blocked.status_code == 200, blocked.get_data(as_text=True)
    assert blocked.json["data"]["progress"] == 0
    assert blocked.json["data"]["completed_at"] is None

    assert_error(
        patch_task(
            leader_client,
            project["id"],
            task.id,
            blocked.json["data"]["version"],
            status="in_progress",
            progress=0,
        ),
        400,
        "invalid_task_state",
    )
    completed = patch_task(
        leader_client,
        project["id"],
        task.id,
        blocked.json["data"]["version"],
        status="completed",
    )
    assert completed.status_code == 200, completed.get_data(as_text=True)
    assert completed.json["data"]["progress"] == 100
    assert completed.json["data"]["blocked_reason"] == ""
    assert completed.json["data"]["completed_at"] is not None

    reset = patch_task(
        leader_client,
        project["id"],
        task.id,
        completed.json["data"]["version"],
        status="not_started",
    )
    assert reset.status_code == 200, reset.get_data(as_text=True)
    assert reset.json["data"]["progress"] == 0
    assert reset.json["data"]["completed_at"] is None


@pytest.mark.parametrize(
    "changes",
    [
        {"status": "cancelled"},
        {"progress": 0},
        {"blocked_reason": ""},
        {"planned_start_date": "2026-09-07"},
        {"planned_end_date": "2026-09-08"},
        {"duration_days": 2},
        {"assignee_user_id": None},
        {"collaborator_user_ids": []},
        {"dependency_ids": []},
    ],
)
def test_cancelled_task_rejects_every_patch_before_writes_or_events(
    changes,
    admin_client,
    leader_client,
    published_template,
    db_session,
):
    project = create_project(
        admin_client, published_template, leader_client.user, code="TASK-CANCEL"
    )
    db_session.rollback()
    task = project_tasks(db_session, project["id"])[0]
    module = db_session.get(ProjectModule, task.project_module_id)
    cancelled = leader_client.delete(
        f"/api/v1/projects/{project['id']}/modules/{module.id}",
        json={"version": project["version"]},
    )
    assert cancelled.status_code == 200, cancelled.get_data(as_text=True)
    cancelled_task = next(
        item for item in cancelled.json["data"]["tasks"] if item["id"] == task.id
    )
    db_session.rollback()
    before_events = db_session.scalar(
        select(func.count())
        .select_from(OperationEvent)
        .where(OperationEvent.project_id == project["id"])
    )

    response = patch_task(
        leader_client,
        project["id"],
        task.id,
        cancelled_task["version"],
        **changes,
    )

    assert_error(response, 409, "task_cancelled")
    db_session.rollback()
    saved = db_session.get(ProjectTask, task.id)
    assert saved.status == "cancelled"
    assert saved.version == cancelled_task["version"]
    assert db_session.scalar(
        select(func.count())
        .select_from(OperationEvent)
        .where(OperationEvent.project_id == project["id"])
    ) == before_events


def test_stale_task_version_has_no_partial_write_or_event(
    admin_client, leader_client, engineer_client, published_template, db_session
):
    """A stale optimistic update must neither overwrite data nor record a false event."""
    project = create_project(
        admin_client, published_template, leader_client.user, code="TASK-STALE"
    )
    add_member(db_session, project["id"], engineer_client.user)
    task = project_tasks(db_session, project["id"])[0]
    first = patch_task(
        leader_client,
        project["id"],
        task.id,
        task.version,
        progress=25,
    )
    assert first.status_code == 200, first.get_data(as_text=True)

    stale = patch_task(
        leader_client,
        project["id"],
        task.id,
        task.version,
        progress=50,
        collaborator_user_ids=[engineer_client.user.id],
    )

    assert_error(stale, 409, "stale_version")
    db_session.rollback()
    saved = db_session.get(ProjectTask, task.id)
    assert saved.progress == 25
    assert saved.version == first.json["data"]["version"]
    assert db_session.scalar(
        select(func.count())
        .select_from(ProjectTaskCollaborator)
        .where(ProjectTaskCollaborator.task_id == task.id)
    ) == 0
    assert db_session.scalar(
        select(func.count())
        .select_from(OperationEvent)
        .where(
            OperationEvent.project_id == project["id"],
            OperationEvent.event_type == "project_task_updated",
        )
    ) == 1


def test_manager_assigns_only_active_working_members_without_assignee_duplication(
    admin_client,
    leader_client,
    engineer_client,
    viewer_client,
    authorized_client_factory,
    published_template,
    db_session,
):
    """Assignment must not grant execution rights to outsiders, viewers, or duplicates."""
    project = create_project(
        admin_client, published_template, leader_client.user, code="TASK-PEOPLE"
    )
    add_member(db_session, project["id"], engineer_client.user)
    add_member(db_session, project["id"], viewer_client.user, role="member")
    outsider = authorized_client_factory("fde_engineer")
    task = project_tasks(db_session, project["id"])[0]

    assert_error(
        patch_task(
            leader_client,
            project["id"],
            task.id,
            task.version,
            assignee_user_id=outsider.user.id,
        ),
        400,
        "invalid_task_member",
    )
    assert_error(
        patch_task(
            leader_client,
            project["id"],
            task.id,
            task.version,
            collaborator_user_ids=[viewer_client.user.id],
        ),
        400,
        "invalid_task_member",
    )
    assert_error(
        patch_task(
            leader_client,
            project["id"],
            task.id,
            task.version,
            assignee_user_id=engineer_client.user.id,
            collaborator_user_ids=[engineer_client.user.id],
        ),
        400,
        "invalid_task_assignment",
    )

    assigned = patch_task(
        leader_client,
        project["id"],
        task.id,
        task.version,
        assignee_user_id=engineer_client.user.id,
        collaborator_user_ids=[leader_client.user.id],
    )

    assert assigned.status_code == 200, assigned.get_data(as_text=True)
    assert assigned.json["data"]["assignee_user_id"] == engineer_client.user.id
    assert assigned.json["data"]["collaborator_user_ids"] == [
        leader_client.user.id
    ]


def test_manager_batch_assigns_assignee_and_collaborator_atomically(
    admin_client,
    leader_client,
    engineer_client,
    published_template,
    db_session,
):
    project = create_project(
        admin_client, published_template, leader_client.user, code="TASK-BATCH"
    )
    add_member(db_session, project["id"], engineer_client.user)
    tasks = project_tasks(db_session, project["id"])
    assert len(tasks) >= 2
    selected = tasks[:2]

    assigned = batch_assign_tasks(
        leader_client,
        project["id"],
        engineer_client.user.id,
        "assignee",
        selected,
    )

    assert assigned.status_code == 200, assigned.get_data(as_text=True)
    assert assigned.json["data"]["updated_count"] == 2
    assert assigned.json["data"]["skipped_count"] == 0
    assert {
        item["assignee_user_id"] for item in assigned.json["data"]["tasks"]
    } == {engineer_client.user.id}

    db_session.rollback()
    refreshed = project_tasks(db_session, project["id"])[:2]
    collaborated = batch_assign_tasks(
        leader_client,
        project["id"],
        leader_client.user.id,
        "collaborator",
        refreshed,
    )
    assert collaborated.status_code == 200, collaborated.get_data(as_text=True)
    assert collaborated.json["data"]["updated_count"] == 2
    assert all(
        leader_client.user.id in item["collaborator_user_ids"]
        for item in collaborated.json["data"]["tasks"]
    )


def test_batch_assignment_rejects_stale_task_without_partial_changes(
    admin_client,
    leader_client,
    engineer_client,
    published_template,
    db_session,
):
    project = create_project(
        admin_client, published_template, leader_client.user, code="TASK-BATCH-STALE"
    )
    add_member(db_session, project["id"], engineer_client.user)
    tasks = project_tasks(db_session, project["id"])
    assert len(tasks) >= 2
    selected = tasks[:2]
    original_assignees = {
        task.id: task.assignee_user_id for task in selected
    }
    selected[1].version += 1

    response = batch_assign_tasks(
        leader_client,
        project["id"],
        engineer_client.user.id,
        "assignee",
        selected,
    )

    assert_error(response, 409, "stale_version")
    db_session.rollback()
    saved = project_tasks(db_session, project["id"])[:2]
    assert {
        task.id: task.assignee_user_id for task in saved
    } == original_assignees


@pytest.mark.parametrize("relation", ["assignee", "collaborator"])
@pytest.mark.parametrize("action", ["downgrade", "remove"])
def test_member_with_active_task_assignment_cannot_be_downgraded_or_removed(
    relation,
    action,
    admin_client,
    leader_client,
    engineer_client,
    published_template,
    db_session,
):
    project = create_project(
        admin_client, published_template, leader_client.user, code="TASK-MEMBER-GUARD"
    )
    add_member(db_session, project["id"], engineer_client.user)
    task = project_tasks(db_session, project["id"])[0]
    changes = (
        {"assignee_user_id": engineer_client.user.id}
        if relation == "assignee"
        else {"collaborator_user_ids": [engineer_client.user.id]}
    )
    assigned = patch_task(
        leader_client, project["id"], task.id, task.version, **changes
    )
    assert assigned.status_code == 200, assigned.get_data(as_text=True)
    db_session.rollback()
    member = db_session.scalar(
        select(ProjectMember).where(
            ProjectMember.project_id == project["id"],
            ProjectMember.user_id == engineer_client.user.id,
        )
    )
    statements: list[str] = []

    def capture_statement(_conn, _cursor, statement, _parameters, _context, _many):
        statements.append(" ".join(statement.lower().split()))

    event.listen(db_session.bind, "before_cursor_execute", capture_statement)
    try:
        if action == "downgrade":
            response = leader_client.patch(
                f"/api/v1/projects/{project['id']}/members/{member.id}",
                json={"version": project["version"], "role": "viewer"},
            )
        else:
            response = leader_client.delete(
                f"/api/v1/projects/{project['id']}/members/{member.id}",
                json={"version": project["version"]},
            )
    finally:
        event.remove(db_session.bind, "before_cursor_execute", capture_statement)

    assert_error(response, 409, "member_has_active_task_assignments")
    assert any(
        "from project_tasks" in statement and "for update" in statement
        for statement in statements
    )
    db_session.rollback()
    assert db_session.get(ProjectMember, member.id).role == "member"


def test_cancelled_task_assignment_does_not_block_member_downgrade(
    admin_client,
    leader_client,
    engineer_client,
    published_template,
    db_session,
):
    project = create_project(
        admin_client, published_template, leader_client.user, code="TASK-MEMBER-CANCEL"
    )
    add_member(db_session, project["id"], engineer_client.user)
    task = project_tasks(db_session, project["id"])[0]
    assigned = patch_task(
        leader_client,
        project["id"],
        task.id,
        task.version,
        assignee_user_id=engineer_client.user.id,
    )
    assert assigned.status_code == 200, assigned.get_data(as_text=True)
    module = db_session.get(ProjectModule, task.project_module_id)
    cancelled = leader_client.delete(
        f"/api/v1/projects/{project['id']}/modules/{module.id}",
        json={"version": project["version"]},
    )
    assert cancelled.status_code == 200, cancelled.get_data(as_text=True)
    db_session.rollback()
    member = db_session.scalar(
        select(ProjectMember).where(
            ProjectMember.project_id == project["id"],
            ProjectMember.user_id == engineer_client.user.id,
        )
    )

    response = leader_client.patch(
        f"/api/v1/projects/{project['id']}/members/{member.id}",
        json={
            "version": cancelled.json["data"]["project_version"],
            "role": "viewer",
        },
    )

    assert response.status_code == 200, response.get_data(as_text=True)
    assert response.json["data"]["role"] == "viewer"


def test_dependencies_must_be_same_project_and_acyclic(
    admin_client, leader_client, published_template, db_session
):
    """Cross-project or cyclic edges would make project scheduling unsafe."""
    project = create_project(
        admin_client, published_template, leader_client.user, code="TASK-DEPS"
    )
    other = create_project(
        admin_client, published_template, leader_client.user, code="TASK-DEPS-OTHER"
    )
    first, second, _ = project_tasks(db_session, project["id"])
    other_task = project_tasks(db_session, other["id"])[0]

    assert_error(
        patch_task(
            leader_client,
            project["id"],
            second.id,
            second.version,
            dependency_ids=[other_task.id],
        ),
        400,
        "invalid_task_dependency",
    )
    saved = patch_task(
        leader_client,
        project["id"],
        second.id,
        second.version,
        dependency_ids=[first.id],
    )
    assert saved.status_code == 200, saved.get_data(as_text=True)
    assert_error(
        patch_task(
            leader_client,
            project["id"],
            first.id,
            first.version,
            dependency_ids=[second.id],
        ),
        400,
        "cyclic_dependency",
    )
    assert db_session.scalar(
        select(func.count())
        .select_from(ProjectTaskDependency)
        .where(
            ProjectTaskDependency.predecessor_task_id == first.id,
            ProjectTaskDependency.successor_task_id == second.id,
        )
    ) == 1


def test_incomplete_dependencies_report_risk_but_do_not_block_progress(
    admin_client, leader_client, published_template, db_session
):
    """Dependency risk is advisory and must name the incomplete predecessors."""
    project = create_project(
        admin_client, published_template, leader_client.user, code="TASK-RISK"
    )
    predecessor, successor, _ = project_tasks(db_session, project["id"])
    configured = patch_task(
        leader_client,
        project["id"],
        successor.id,
        successor.version,
        dependency_ids=[predecessor.id],
    )
    assert configured.status_code == 200, configured.get_data(as_text=True)
    assert configured.json["data"]["dependency_risk"] is True
    assert configured.json["data"]["incomplete_dependency_ids"] == [
        predecessor.id
    ]
    project_detail = leader_client.get(f"/api/v1/projects/{project['id']}")
    project_successor = next(
        item
        for item in project_detail.json["data"]["tasks"]
        if item["id"] == successor.id
    )
    assert project_successor["dependency_risk"] is True
    assert project_successor["incomplete_dependency_ids"] == [predecessor.id]

    advanced = patch_task(
        leader_client,
        project["id"],
        successor.id,
        configured.json["data"]["version"],
        progress=30,
    )

    assert advanced.status_code == 200, advanced.get_data(as_text=True)
    assert advanced.json["data"]["dependency_risk"] is True
    completed = patch_task(
        leader_client,
        project["id"],
        predecessor.id,
        predecessor.version,
        status="completed",
    )
    assert completed.status_code == 200, completed.get_data(as_text=True)
    refreshed = leader_client.get(
        f"/api/v1/projects/{project['id']}/tasks/{successor.id}"
    )
    assert refreshed.json["data"]["dependency_risk"] is False
    assert refreshed.json["data"]["incomplete_dependency_ids"] == []


def test_manager_schedule_change_reschedules_only_dependency_descendants(
    admin_client, leader_client, published_template, db_session
):
    """Changing one task schedule must move its descendants without global rescheduling."""
    project = create_project(
        admin_client,
        published_template,
        leader_client.user,
        code="TASK-RESCHEDULE",
        module_keys=["pre_diagnosis", "diagnosis"],
    )
    tasks = {task.task_key: task for task in project_tasks(db_session, project["id"])}
    changed = tasks["collect_enterprise_info"]
    first_descendant = tasks["confirm_business_scope"]
    second_descendant = tasks["deliver_pre_diagnosis"]
    unrelated = tasks["interview_department_leads"]
    unrelated_dates = (unrelated.planned_start_date, unrelated.planned_end_date)
    descendant_versions = {
        first_descendant.id: first_descendant.version,
        second_descendant.id: second_descendant.version,
    }

    response = patch_task(
        leader_client,
        project["id"],
        changed.id,
        changed.version,
        planned_start_date="2026-09-07",
        duration_days=2,
    )

    assert response.status_code == 200, response.get_data(as_text=True)
    assert response.json["data"]["planned_end_date"] == "2026-09-08"
    db_session.rollback()
    db_session.expire_all()
    assert db_session.get(ProjectTask, first_descendant.id).planned_start_date.isoformat() == "2026-09-09"
    assert db_session.get(ProjectTask, second_descendant.id).planned_start_date.isoformat() == "2026-09-10"
    assert db_session.get(ProjectTask, first_descendant.id).version == descendant_versions[first_descendant.id] + 1
    assert db_session.get(ProjectTask, second_descendant.id).version == descendant_versions[second_descendant.id] + 1
    saved_unrelated = db_session.get(ProjectTask, unrelated.id)
    assert (saved_unrelated.planned_start_date, saved_unrelated.planned_end_date) == unrelated_dates


@pytest.mark.parametrize("invalid_end", ["2026-09-09", "2026-09-12"])
def test_manual_task_dates_normalize_weekends_and_reject_inconsistent_end_dates(
    invalid_end,
    admin_client,
    leader_client,
    published_template,
    db_session,
):
    project = create_project(
        admin_client, published_template, leader_client.user, code="TASK-WORKDAYS"
    )
    task = project_tasks(db_session, project["id"])[0]

    normalized = patch_task(
        leader_client,
        project["id"],
        task.id,
        task.version,
        planned_start_date="2026-09-05",
        planned_end_date="2026-09-08",
        duration_days=2,
    )

    assert normalized.status_code == 200, normalized.get_data(as_text=True)
    assert normalized.json["data"]["planned_start_date"] == "2026-09-07"
    assert normalized.json["data"]["planned_end_date"] == "2026-09-08"
    db_session.rollback()
    before_events = db_session.scalar(
        select(func.count())
        .select_from(OperationEvent)
        .where(
            OperationEvent.project_id == project["id"],
            OperationEvent.event_type == "project_task_updated",
        )
    )

    inconsistent = patch_task(
        leader_client,
        project["id"],
        task.id,
        normalized.json["data"]["version"],
        planned_start_date="2026-09-07",
        planned_end_date=invalid_end,
        duration_days=2,
    )

    assert_error(inconsistent, 400, "invalid_request")
    db_session.rollback()
    saved = db_session.get(ProjectTask, task.id)
    assert saved.planned_start_date.isoformat() == "2026-09-07"
    assert saved.planned_end_date.isoformat() == "2026-09-08"
    assert saved.version == normalized.json["data"]["version"]
    assert db_session.scalar(
        select(func.count())
        .select_from(OperationEvent)
        .where(
            OperationEvent.project_id == project["id"],
            OperationEvent.event_type == "project_task_updated",
        )
    ) == before_events


def test_task_serialization_failure_rolls_back_update_and_event(
    admin_client, leader_client, published_template, db_session, monkeypatch
):
    """Building the task response after commit would retain a failed mutation."""
    from fde_api.projects import task_service

    project = create_project(
        admin_client,
        published_template,
        leader_client.user,
        code="TASK-ROLLBACK",
    )
    task = project_tasks(db_session, project["id"])[0]

    def fail_serialization(*_args, **_kwargs):
        raise RuntimeError("forced task DTO failure")

    monkeypatch.setattr(task_service, "_serialize_tasks", fail_serialization)
    response = patch_task(
        leader_client,
        project["id"],
        task.id,
        task.version,
        progress=35,
    )

    assert_error(response, 503, "project_task_update_failed")
    db_session.rollback()
    assert db_session.get(ProjectTask, task.id).progress == 0
    assert db_session.scalar(
        select(func.count())
        .select_from(OperationEvent)
        .where(
            OperationEvent.project_id == project["id"],
            OperationEvent.event_type == "project_task_updated",
        )
    ) == 0


def test_task_description_round_trips_through_patch(
    admin_client, leader_client, published_template, db_session
):
    project = create_project(
        admin_client, published_template, leader_client.user, code="TASK-DESC"
    )
    target = project_tasks(db_session, project["id"])[0]

    patched = patch_task(
        admin_client,
        project["id"],
        target.id,
        target.version,
        description=" 与客户确认的交付说明  ",
    )
    assert patched.status_code == 200, patched.get_data(as_text=True)
    assert patched.json["data"]["description"] == "与客户确认的交付说明"

    # Persisted value survives a fresh read.
    listed = admin_client.get(
        f"/api/v1/projects/{project['id']}/tasks/{target.id}"
    )
    assert listed.status_code == 200
    assert listed.json["data"]["description"] == "与客户确认的交付说明"


def test_lead_manually_adds_a_task_with_description_assignee_and_dependencies(
    admin_client, leader_client, engineer_client, published_template, db_session
):
    project = create_project(
        admin_client, published_template, leader_client.user, code="TASK-ADD", module_keys=["pre_diagnosis", "diagnosis"]
    )
    add_member(db_session, project["id"], engineer_client.user, role="member")

    first_module = next(m for m in project["modules"] if m["module_key"] == "pre_diagnosis")
    existing = project_tasks(db_session, project["id"])[0]

    created = admin_client.post(
        f"/api/v1/projects/{project['id']}/modules/{first_module['module_key']}/tasks",
        json={
            "name": "新增交付任务",
            "description": "人工补充的任务说明",
            "duration_days": 3,
            "assignee_user_id": engineer_client.user.id,
            "collaborator_user_ids": [leader_client.user.id],
            "dependency_ids": [existing.id],
        },
    )
    assert created.status_code == 201, created.get_data(as_text=True)
    data = created.json["data"]
    assert data["name"] == "新增交付任务"
    assert data["description"] == "人工补充的任务说明"
    assert data["duration_days"] == 3
    assert data["assignee_user_id"] == engineer_client.user.id
    assert data["collaborator_user_ids"] == [leader_client.user.id]
    assert data["dependency_ids"] == [existing.id]

    # End the read transaction so a fresh snapshot sees the committed task row.
    db_session.rollback()
    new_task = db_session.get(ProjectTask, data["id"])
    assert new_task is not None
    assert new_task.project_module_id == first_module["id"]
    assert new_task.duration_days == 3
    assert new_task.description == "人工补充的任务说明"

    # The task must be listed in the project task list.
    listed = admin_client.get(f"/api/v1/projects/{project['id']}/tasks")
    assert listed.status_code == 200
    assert data["id"] in {item["id"] for item in listed.json["data"]["items"]}


def test_manual_task_rejects_invalid_duration_and_assignee_role(
    admin_client, leader_client, engineer_client, published_template, db_session
):
    project = create_project(
        admin_client, published_template, leader_client.user, code="TASK-ADD-INVALID"
    )
    first_module = next(m for m in project["modules"] if m["module_key"] == "pre_diagnosis")

    zero_duration = admin_client.post(
        f"/api/v1/projects/{project['id']}/modules/{first_module['module_key']}/tasks",
        json={"name": "非法工期", "duration_days": 0},
    )
    assert_error(zero_duration, 400, "invalid_request")

    # A non-member engineer is not a valid working assignee even with an active role.
    assert_error(
        admin_client.post(
            f"/api/v1/projects/{project['id']}/modules/{first_module['module_key']}/tasks",
            json={"name": "非法负责人", "duration_days": 2, "assignee_user_id": engineer_client.user.id},
        ),
        400,
        "invalid_task_member",
    )
