from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4

import pytest
from sqlalchemy import select

from fde_api.auth.models import User
from fde_api.auth.passwords import hash_password
from fde_api.auth.tokens import issue_access_token
from fde_api.workbench.models import (
    IndustryTemplateVersion,
    OperationEvent,
    ProjectMember,
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
    def create(role: str, *, active: bool = True) -> AuthorizedClient:
        user = User(
            username=f"{role}.{uuid4().hex}",
            display_name=role,
            role=role,
            password_hash=hash_password(INITIAL_PASSWORD),
            must_change_password=False,
            is_active=active,
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


def create_project(client, template, leader):
    response = client.post(
        "/api/v1/projects",
        json={
            "name": "成员管理试点",
            "enterprise_name": "星河制造",
            "template_version_id": template.id,
            "leader_user_id": leader.id,
            "planned_start_date": "2026-08-21",
            "module_keys": ["pre_diagnosis"],
        },
    )
    assert response.status_code == 201, response.get_data(as_text=True)
    return response.json["data"]


@pytest.mark.parametrize(
    ("actor_role", "relation", "expected"),
    [
        ("admin", "none", 200),
        ("project_lead", "leader", 200),
        ("project_lead", "member", 403),
        ("fde_engineer", "member", 403),
        ("viewer", "viewer", 403),
    ],
)
def test_only_admin_or_current_project_leader_manages_members(
    authorized_client_factory,
    admin_client,
    leader_client,
    published_template,
    db_session,
    actor_role,
    relation,
    expected,
):
    """A project membership must not turn an ordinary lead into a project manager."""
    project = create_project(admin_client, published_template, leader_client.user)
    actor = (
        admin_client
        if actor_role == "admin"
        else authorized_client_factory(actor_role)
    )
    if relation != "none" and actor.user.id != leader_client.user.id:
        db_session.add(
            ProjectMember(
                project_id=project["id"],
                user_id=actor.user.id,
                role="viewer" if relation == "viewer" else "member",
            )
        )
        db_session.commit()
    if relation == "leader":
        actor = leader_client
    target = authorized_client_factory("fde_engineer")

    response = actor.post(
        f"/api/v1/projects/{project['id']}/members",
        json={"user_id": target.user.id, "role": "member", "version": project["version"]},
    )

    assert response.status_code == expected, response.get_data(as_text=True)


def test_member_list_is_project_scoped_and_mutations_validate_membership_invariants(
    admin_client,
    leader_client,
    authorized_client_factory,
    published_template,
    db_session,
):
    """Cross-project reads, inactive users, duplicates, and leader removal must not leak or corrupt scope."""
    project = create_project(admin_client, published_template, leader_client.user)
    engineer = authorized_client_factory("fde_engineer")
    inactive = authorized_client_factory("fde_engineer", active=False)

    assert_error(
        engineer.get(f"/api/v1/projects/{project['id']}/members"), 403, "forbidden"
    )
    added = leader_client.post(
        f"/api/v1/projects/{project['id']}/members",
        json={"user_id": engineer.user.id, "role": "member", "version": project["version"]},
    )
    assert added.status_code == 200, added.get_data(as_text=True)
    member = added.json["data"]
    assert member["user_id"] == engineer.user.id
    assert member["role"] == "member"
    assert {item["user_id"] for item in leader_client.get(
        f"/api/v1/projects/{project['id']}/members"
    ).json["data"]["items"]} == {leader_client.user.id, engineer.user.id}
    assert_error(
        leader_client.post(
            f"/api/v1/projects/{project['id']}/members",
            json={"user_id": inactive.user.id, "role": "member", "version": added.json["data"]["project_version"]},
        ),
        400,
        "invalid_project_member",
    )
    assert_error(
        leader_client.post(
            f"/api/v1/projects/{project['id']}/members",
            json={"user_id": engineer.user.id, "role": "member", "version": added.json["data"]["project_version"]},
        ),
        409,
        "duplicate_project_member",
    )
    assert_error(
        leader_client.delete(
            f"/api/v1/projects/{project['id']}/members/{leader_client.user.id}",
            json={"version": added.json["data"]["project_version"]},
        ),
        409,
        "current_project_leader",
    )
    changed = leader_client.patch(
        f"/api/v1/projects/{project['id']}/members/{member['id']}",
        json={"role": "viewer", "version": added.json["data"]["project_version"]},
    )
    assert changed.status_code == 200, changed.get_data(as_text=True)
    assert changed.json["data"]["role"] == "viewer"
    assert_error(
        leader_client.delete(
            f"/api/v1/projects/{project['id']}/members/{member['id']}",
            json={"version": added.json["data"]["project_version"]},
        ),
        409,
        "stale_version",
    )
    removed = leader_client.delete(
        f"/api/v1/projects/{project['id']}/members/{member['id']}",
        json={"version": changed.json["data"]["project_version"]},
    )
    assert removed.status_code == 204
    event_types = list(
        db_session.scalars(
            select(OperationEvent.event_type)
            .where(OperationEvent.project_id == project["id"])
            .order_by(OperationEvent.created_at)
        )
    )
    assert {
        "project_member_added",
        "project_member_updated",
        "project_member_removed",
    } <= set(event_types)


def test_member_role_cannot_exceed_the_users_system_role(
    admin_client, leader_client, authorized_client_factory, published_template
):
    """A viewer system account assigned as a working member would be a project-role escalation."""
    project = create_project(admin_client, published_template, leader_client.user)
    viewer = authorized_client_factory("viewer")

    assert_error(
        leader_client.post(
            f"/api/v1/projects/{project['id']}/members",
            json={"user_id": viewer.user.id, "role": "member", "version": project["version"]},
        ),
        400,
        "member_role_exceeds_system_role",
    )


def test_member_add_does_not_reassign_tasks_until_explicit_default_assignment(
    admin_client,
    leader_client,
    authorized_client_factory,
    published_template,
    db_session,
):
    """Adding a qualified account must not silently change an existing task owner."""
    default_task = db_session.scalar(
        select(TemplateTask).where(TemplateTask.task_key == "collect_enterprise_info")
    )
    default_task.default_assignee_role = "admin"
    db_session.commit()
    project = create_project(admin_client, published_template, leader_client.user)
    target_task = db_session.scalar(
        select(ProjectTask).where(ProjectTask.task_key == "collect_enterprise_info")
    )
    assert target_task.assignee_user_id is None
    matching_admin = authorized_client_factory("admin")
    ordinary_engineer = authorized_client_factory("fde_engineer")

    added = leader_client.post(
        f"/api/v1/projects/{project['id']}/members",
        json={"user_id": matching_admin.user.id, "role": "member", "version": project["version"]},
    )
    assert added.status_code == 200
    db_session.expire_all()
    assert db_session.get(ProjectTask, target_task.id).assignee_user_id is None
    assert_error(
        ordinary_engineer.post(
            f"/api/v1/projects/{project['id']}/tasks/assign-defaults",
            json={"version": added.json["data"]["project_version"]},
        ),
        403,
        "forbidden",
    )
    assigned = leader_client.post(
        f"/api/v1/projects/{project['id']}/tasks/assign-defaults",
        json={"version": added.json["data"]["project_version"]},
    )
    assert assigned.status_code == 200, assigned.get_data(as_text=True)
    assert assigned.json["data"]["assigned_count"] == 1
    assert assigned.json["data"]["assignments"] == [
        {"task_id": target_task.id, "assignee_user_id": matching_admin.user.id}
    ]
    db_session.rollback()
    db_session.expire_all()
    assert db_session.get(ProjectTask, target_task.id).assignee_user_id == matching_admin.user.id
    assert db_session.scalar(
        select(OperationEvent).where(
            OperationEvent.project_id == project["id"],
            OperationEvent.event_type == "project_default_assignments_applied",
        )
    ) is not None


def test_default_assignment_skips_working_members_without_the_required_system_role(
    admin_client,
    leader_client,
    authorized_client_factory,
    published_template,
    db_session,
):
    """The project working role alone must not qualify a lower-ranked system account."""
    default_task = db_session.scalar(
        select(TemplateTask).where(TemplateTask.task_key == "collect_enterprise_info")
    )
    default_task.default_assignee_role = "admin"
    db_session.commit()
    project = create_project(admin_client, published_template, leader_client.user)
    engineer = authorized_client_factory("fde_engineer")
    added = leader_client.post(
        f"/api/v1/projects/{project['id']}/members",
        json={"user_id": engineer.user.id, "role": "member", "version": project["version"]},
    )
    assert added.status_code == 200

    assigned = leader_client.post(
        f"/api/v1/projects/{project['id']}/tasks/assign-defaults",
        json={"version": added.json["data"]["project_version"]},
    )

    assert assigned.status_code == 200
    assert assigned.json["data"]["assigned_count"] == 0
