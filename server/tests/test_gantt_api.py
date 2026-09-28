from dataclasses import dataclass
from datetime import date
from uuid import uuid4

import pytest
from sqlalchemy import select

from fde_api.auth.models import User
from fde_api.auth.passwords import hash_password
from fde_api.auth.tokens import issue_access_token
from fde_api.workbench.models import IndustryTemplateVersion, ProjectMember, ProjectModule, ProjectTask
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


def _create_project(client, template, leader):
    response = client.post(
        "/api/v1/projects",
        json={
            "name": "甘特图试点",
            "enterprise_name": "星河制造",
            "project_code": f"GANTT-{uuid4().hex[:8]}",
            "template_version_id": template.id,
            "leader_user_id": leader.id,
            "planned_start_date": "2026-08-21",
            "module_keys": ["pre_diagnosis", "pov"],
        },
    )
    assert response.status_code == 201, response.get_data(as_text=True)
    return response.json["data"]


def test_gantt_groups_tasks_stably_and_excludes_cancelled_work_from_range(
    admin_client, leader_client, viewer_client, published_template, db_session
):
    """Changing module/task ordering or counting cancelled dates would misdraw the plan."""
    project = _create_project(admin_client, published_template, leader_client.user)
    db_session.rollback()
    db_session.add(
        ProjectMember(project_id=project["id"], user_id=viewer_client.user.id, role="viewer")
    )
    db_session.flush()
    modules = list(
        db_session.scalars(
            select(ProjectModule)
            .where(ProjectModule.project_id == project["id"])
            .order_by(ProjectModule.sort_order, ProjectModule.id)
        )
    )
    first_module, second_module = modules
    first_tasks = list(
        db_session.scalars(
            select(ProjectTask)
            .where(ProjectTask.project_module_id == first_module.id)
            .order_by(ProjectTask.id)
        )
    )
    second_tasks = list(
        db_session.scalars(
            select(ProjectTask)
            .where(ProjectTask.project_module_id == second_module.id)
            .order_by(ProjectTask.id)
        )
    )
    assert len(first_tasks) >= 2 and second_tasks
    first_tasks[0].planned_start_date = date(2026, 8, 25)
    first_tasks[0].planned_end_date = date(2026, 8, 26)
    first_tasks[0].assignee_user_id = leader_client.user.id
    first_tasks[0].progress = 50
    first_tasks[1].planned_start_date = date(2026, 8, 21)
    first_tasks[1].planned_end_date = date(2026, 8, 22)
    first_tasks[1].status = "blocked"
    first_tasks[1].blocked_reason = "等待客户数据"
    first_tasks[2].planned_start_date = date(2026, 8, 27)
    first_tasks[2].planned_end_date = date(2026, 8, 28)
    for task in second_tasks:
        task.planned_start_date = date(2026, 10, 1)
        task.planned_end_date = date(2026, 10, 2)
        task.status = "cancelled"
    db_session.commit()

    response = viewer_client.get(f"/api/v1/projects/{project['id']}/gantt")

    assert response.status_code == 200, response.get_data(as_text=True)
    data = response.json["data"]
    assert [group["module_key"] for group in data["groups"]] == [
        "pre_diagnosis",
        "pov",
    ]
    assert [task["id"] for task in data["groups"][0]["tasks"]] == [
        first_tasks[1].id,
        first_tasks[0].id,
        first_tasks[2].id,
    ]
    assert data["range"] == {"start": "2026-08-21", "end": "2026-08-28"}
    scheduled = data["groups"][0]["tasks"][1]
    assert scheduled["assignee"] == {
        "id": leader_client.user.id,
        "display_name": "project_lead",
        "role": "project_lead",
    }
    assert scheduled["progress"] == 50
    assert scheduled["status"] == "not_started"
    assert scheduled["cancelled"] is False
    cancelled = data["groups"][1]["tasks"][0]
    assert cancelled["status"] == "cancelled"
    assert cancelled["cancelled"] is True


def test_gantt_reuses_project_access_for_unrelated_viewers(
    admin_client, leader_client, viewer_client, published_template
):
    """A route-level authorization omission would leak project schedules."""
    project = _create_project(admin_client, published_template, leader_client.user)

    response = viewer_client.get(f"/api/v1/projects/{project['id']}/gantt")

    assert response.status_code == 403
    assert response.json["data"] is None
    assert response.json["error"]["code"] == "forbidden"
    assert response.json["error"]["message"] == "You do not have access to this project."
