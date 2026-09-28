from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from fde_api.auth.models import User
from fde_api.auth.passwords import hash_password
from fde_api.auth.tokens import issue_access_token
from fde_api.projects.permissions import ProjectAccess, project_access
from fde_api.projects.service import project_completion
from fde_api.research.models import ProjectResearchSubject, TemplateResearchField, TemplateResearchForm, TemplateResearchSection
from fde_api.workbench.models import (
    IndustryTemplateVersion,
    OperationEvent,
    Project,
    ProjectMember,
    ProjectModule,
    ProjectTask,
    ProjectTaskDependency,
    TemplateTask,
    TemplateTaskDependency,
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
    assert response.status_code == status
    assert response.json["data"] is None
    assert response.json["error"]["code"] == code


def project_payload(template, leader, **overrides):
    payload = {
        "name": "星河 PoV",
        "enterprise_name": "星河制造",
        "template_version_id": template.id,
        "leader_user_id": leader.id,
        "planned_start_date": "2026-08-21",
        "module_keys": ["pre_diagnosis", "pov"],
    }
    payload.update(overrides)
    return payload


def create_project(client, template, leader, **overrides):
    response = client.post(
        "/api/v1/projects", json=project_payload(template, leader, **overrides)
    )
    assert response.status_code == 201, response.get_data(as_text=True)
    return response.json["data"]


def test_manual_project_creation_does_not_create_or_require_a_template(
    admin_client, leader_client, db_session
):
    seed_workbench(db_session)
    db_session.commit()
    response = admin_client.post("/api/v1/projects", json={
        "name": "手动项目",
        "enterprise_name": "无模板企业",
        "planned_start_date": "2026-09-01",
        "leader_user_id": leader_client.user.id,
        "creation_source": "manual",
        "module_keys": ["pre_diagnosis"],
        "project_snapshot": {
            "industry_name": "通用",
            "description": "人工填写",
            "modules": [{
                "module_key": "pre_diagnosis",
                "name": "预诊断",
                "description": "确认范围",
                "tasks": [{
                    "task_key": "manual_scope",
                    "name": "确认项目范围",
                    "description": "整理输入和验收口径",
                    "duration_days": 2,
                    "default_assignee_role": "project_lead",
                    "dependency_keys": [],
                    "sort_order": 0,
                }],
            }],
        },
    })
    assert response.status_code == 201, response.get_data(as_text=True)
    assert response.json["data"]["template_version_id"] is None
    assert response.json["data"]["template_snapshot"]["creation_source"] == "manual"
    assert response.json["data"]["tasks"][0]["task_key"] == "manual_scope"


def test_project_creation_preserves_its_research_definition_snapshot(
    admin_client, published_template, leader_client, db_session
):
    """Replacing a template definition later must not rewrite an existing project."""
    form = TemplateResearchForm(
        template_version=published_template,
        form_key="project_context",
        name="Project context",
        subject_type="project",
    )
    section = TemplateResearchSection(
        form=form, section_key="overview", name="Overview"
    )
    state_field = TemplateResearchField(
        section=section,
        field_key="current_state",
        name="Current state",
        field_type="single_choice",
        is_required=True,
        options_json={"options": {"choices": ["yes", "no"]}},
    )
    notes_field = TemplateResearchField(
        section=section,
        field_key="notes",
        name="Notes",
        field_type="long_text",
        options_json={
            "options": {},
            "condition": {"field_key": "current_state", "operator": "equals", "value": "yes"},
        },
    )
    db_session.add(form)
    db_session.commit()
    created = create_project(admin_client, published_template, leader_client.user)
    form.name = "Changed template context"
    db_session.commit()

    detail = admin_client.get(f"/api/v1/projects/{created['id']}")

    assert detail.status_code == 200
    assert detail.json["data"]["research_snapshot"] == {
        "forms": [
            {
                "id": form.id,
                "form_key": "project_context",
                "name": "Project context",
                    "description": "",
                    "subject_type": "project",
                    "module_key": None,
                    "sort_order": 0,
                "sections": [
                    {
                        "id": section.id,
                        "section_key": "overview",
                        "name": "Overview",
                        "description": "",
                        "sort_order": 0,
                        "fields": [
                            {
                                "id": state_field.id,
                                "field_key": "current_state",
                                "name": "Current state",
                                "help_text": "",
                                "type": "single_choice",
                                "is_required": True,
                                "options": {"choices": ["yes", "no"]},
                                "sort_order": 0,
                            },
                            {
                                "id": notes_field.id,
                                "field_key": "notes",
                                "name": "Notes",
                                "help_text": "",
                                "type": "long_text",
                                "is_required": False,
                                "options": {},
                                "sort_order": 0,
                                "condition": {"field_key": "current_state", "operator": "equals", "value": "yes"},
                            },
                        ],
                    }
                ],
            }
        ]
    }


def test_create_project_copies_only_selected_modules_and_schedules_tasks(
    admin_client, published_template, leader_client, db_session
):
    """Copying the full template or skipping scheduling would corrupt execution scope."""
    response = admin_client.post(
        "/api/v1/projects",
        json=project_payload(
            published_template,
            leader_client.user,
            contact_name="林总",
            contact_phone="13800000000",
            address="示例地址",
            background="验证质检场景",
            notes="周五例会",
            project_code="XH-POV-001",
            planned_end_date="2026-10-31",
        ),
    )

    assert response.status_code == 201
    project = response.json["data"]
    assert [module["module_key"] for module in project["modules"]] == [
        "pre_diagnosis",
        "pov",
    ]
    assert all(
        task["planned_start_date"] and task["planned_end_date"]
        for task in project["tasks"]
    )
    assert project["contact_name"] == "林总"
    assert project["contact_phone"] == "13800000000"
    assert project["address"] == "示例地址"
    assert project["background"] == "验证质检场景"
    assert project["notes"] == "周五例会"
    assert project["project_code"] == "XH-POV-001"
    assert project["planned_end_date"] == "2026-10-31"
    assert {module["module_key"] for module in project["template_snapshot"]["modules"]} == {
        "pre_diagnosis",
        "diagnosis",
        "pov",
        "production_deployment",
        "training_handover",
    }
    assert all(
        task["assignee_user_id"] == leader_client.user.id
        for task in project["tasks"]
    )
    persisted_dependencies = db_session.scalar(
        select(func.count()).select_from(ProjectTaskDependency)
    )
    assert persisted_dependencies == 6


def test_create_project_rejects_selected_module_missing_dependency_predecessor(
    admin_client, published_template, leader_client, db_session
):
    """Dropping a dependency from an omitted predecessor module rewrites the template."""
    predecessor = db_session.scalar(
        select(TemplateTask).where(TemplateTask.task_key == "deliver_pre_diagnosis")
    )
    successor = db_session.scalar(
        select(TemplateTask).where(TemplateTask.task_key == "confirm_pov_acceptance")
    )
    db_session.add(
        TemplateTaskDependency(
            predecessor_task_id=predecessor.id,
            successor_task_id=successor.id,
        )
    )
    db_session.commit()

    response = admin_client.post(
        "/api/v1/projects",
        json=project_payload(
            published_template,
            leader_client.user,
            module_keys=["pov"],
        ),
    )

    assert_error(response, 400, "missing_required_module_dependency")
    assert "pre_diagnosis" in response.json["error"]["message"]
    assert "deliver_pre_diagnosis" in response.json["error"]["message"]
    assert "confirm_pov_acceptance" in response.json["error"]["message"]


def test_create_project_preserves_cross_module_dependency_when_both_are_selected(
    admin_client, published_template, leader_client, db_session
):
    """A dependency-closed selection must retain its cross-module edge and schedule."""
    predecessor = db_session.scalar(
        select(TemplateTask).where(TemplateTask.task_key == "deliver_pre_diagnosis")
    )
    successor = db_session.scalar(
        select(TemplateTask).where(TemplateTask.task_key == "confirm_pov_acceptance")
    )
    db_session.add(
        TemplateTaskDependency(
            predecessor_task_id=predecessor.id,
            successor_task_id=successor.id,
        )
    )
    db_session.commit()

    created = create_project(
        admin_client,
        published_template,
        leader_client.user,
        module_keys=["pre_diagnosis", "pov"],
    )

    tasks = {task["task_key"]: task for task in created["tasks"]}
    assert "deliver_pre_diagnosis" in tasks["confirm_pov_acceptance"]["dependency_keys"]
    assert tasks["confirm_pov_acceptance"]["planned_start_date"] > tasks[
        "deliver_pre_diagnosis"
    ]["planned_end_date"]


def test_unmatched_default_role_stays_pending_assignment(
    admin_client, published_template, leader_client, db_session
):
    """Matching actors outside project membership would leak assignments into a project."""
    task = db_session.scalar(
        select(TemplateTask).where(TemplateTask.task_key == "collect_enterprise_info")
    )
    task.default_assignee_role = "admin"
    db_session.commit()
    created = create_project(
        admin_client,
        published_template,
        leader_client.user,
        module_keys=["pre_diagnosis"],
    )

    unmatched = next(
        task for task in created["tasks"] if task["task_key"] == "collect_enterprise_info"
    )
    assert unmatched["assignee_user_id"] is None
    assert unmatched["pending_assignment"] is True


def test_project_lead_creates_only_self_led_project_and_admin_validates_leader_role(
    admin_client, leader_client, published_template, authorized_client_factory
):
    """Role inheritance must not let a lead create projects owned by another user."""
    other_leader = authorized_client_factory("project_lead")
    engineer = authorized_client_factory("fde_engineer")
    inactive_leader = authorized_client_factory("project_lead", active=False)

    assert (
        leader_client.post(
            "/api/v1/projects",
            json=project_payload(published_template, leader_client.user),
        ).status_code
        == 201
    )
    assert_error(
        leader_client.post(
            "/api/v1/projects",
            json=project_payload(
                published_template,
                other_leader.user,
                project_code="OTHER-LEAD",
            ),
        ),
        403,
        "forbidden",
    )
    assert_error(
        admin_client.post(
            "/api/v1/projects",
            json=project_payload(
                published_template,
                engineer.user,
                project_code="ENGINEER-LEAD",
            ),
        ),
        400,
        "invalid_project_leader",
    )
    assert_error(
        admin_client.post(
            "/api/v1/projects",
            json=project_payload(
                published_template,
                inactive_leader.user,
                project_code="INACTIVE-LEAD",
            ),
        ),
        400,
        "invalid_project_leader",
    )


def test_engineer_lists_only_projects_where_they_are_member(
    admin_client, engineer_client, leader_client, published_template, db_session
):
    """A higher system role must never widen a non-admin user's project data scope."""
    assigned = create_project(
        admin_client,
        published_template,
        leader_client.user,
        project_code="VISIBLE",
    )
    hidden = create_project(
        admin_client,
        published_template,
        leader_client.user,
        project_code="HIDDEN",
    )
    db_session.add(
        ProjectMember(
            project_id=assigned["id"], user_id=engineer_client.user.id, role="member"
        )
    )
    db_session.commit()

    response = engineer_client.get("/api/v1/projects")

    assert response.status_code == 200
    ids = {item["id"] for item in response.json["data"]["items"]}
    assert assigned["id"] in ids
    assert hidden["id"] not in ids
    assert engineer_client.get(f"/api/v1/projects/{hidden['id']}").status_code == 403


def test_project_access_combines_role_inheritance_with_membership(
    admin_client, engineer_client, viewer_client, leader_client, published_template, db_session
):
    """Computing access from system rank alone would expose every project."""
    created = create_project(admin_client, published_template, leader_client.user)
    db_session.rollback()
    project = db_session.get(Project, created["id"])
    db_session.add_all(
        [
            ProjectMember(project_id=project.id, user_id=engineer_client.user.id, role="member"),
            ProjectMember(project_id=project.id, user_id=viewer_client.user.id, role="viewer"),
        ]
    )
    db_session.commit()
    db_session.expire_all()

    assert project_access(admin_client.user, project) == ProjectAccess(True, True, True)
    assert project_access(leader_client.user, project) == ProjectAccess(True, True, True)
    assert project_access(engineer_client.user, project) == ProjectAccess(True, False, True)
    assert project_access(viewer_client.user, project) == ProjectAccess(True, False, False)
    outsider = User(
        username=f"lead.outside.{uuid4().hex}",
        display_name="outside",
        role="project_lead",
        password_hash=hash_password(INITIAL_PASSWORD),
        must_change_password=False,
        is_active=True,
    )
    db_session.add(outsider)
    db_session.commit()
    assert project_access(outsider, project) == ProjectAccess(False, False, False)


def test_project_list_filters_and_orders_stably(
    admin_client, published_template, leader_client, authorized_client_factory, db_session
):
    """Missing allowlisted filters or a unique tie-breaker would make pagination drift."""
    other_leader = authorized_client_factory("project_lead")
    oldest = create_project(
        admin_client,
        published_template,
        leader_client.user,
        name="北斗诊断",
        enterprise_name="北斗制造",
        project_code="P-001",
        module_keys=["pre_diagnosis"],
    )
    newest = create_project(
        admin_client,
        published_template,
        other_leader.user,
        name="星河 PoV",
        enterprise_name="星河制造",
        project_code="P-002",
        module_keys=["pov"],
    )
    moment = datetime(2026, 8, 21, 8, 0, tzinfo=UTC)
    db_session.get(Project, oldest["id"]).created_at = moment
    db_session.get(Project, newest["id"]).created_at = moment + timedelta(seconds=1)
    db_session.commit()

    filtered = admin_client.get(
        "/api/v1/projects?search=星河&status=draft"
        f"&leader_user_id={other_leader.user.id}&industry=通用"
        "&module_key=pov&page=1&page_size=1"
    )

    assert filtered.status_code == 200
    assert [item["id"] for item in filtered.json["data"]["items"]] == [newest["id"]]
    assert filtered.json["data"]["total"] == 1
    all_items = admin_client.get("/api/v1/projects?page_size=20").json["data"]["items"]
    assert [item["id"] for item in all_items[:2]] == [newest["id"], oldest["id"]]
    assert_error(admin_client.get("/api/v1/projects?status=unknown"), 400, "invalid_request")


def test_project_list_supports_legacy_snapshot_without_industry_name(
    admin_client, published_template, leader_client, db_session
):
    """A legacy snapshot must not make the entire project workbench unavailable."""
    created = create_project(
        admin_client,
        published_template,
        leader_client.user,
        name="历史项目",
        module_keys=["pre_diagnosis"],
    )
    project = db_session.get(Project, created["id"])
    project.template_snapshot = {"version_id": published_template.id, "modules": []}
    db_session.commit()

    response = admin_client.get("/api/v1/projects?page=1&page_size=20")

    assert response.status_code == 200
    item = next(item for item in response.json["data"]["items"] if item["id"] == created["id"])
    assert item["industry"] == published_template.industry_name

    filtered = admin_client.get(
        f"/api/v1/projects?industry={published_template.industry_name}"
        "&page=1&page_size=20"
    )
    assert filtered.status_code == 200
    assert created["id"] in {item["id"] for item in filtered.json["data"]["items"]}


@pytest.mark.parametrize(
    ("literal", "expected_name"),
    [
        ("%", "百分%项目"),
        ("_", "下划_项目"),
        ("!", "感叹!项目"),
        ("\\", "路径\\项目"),
    ],
)
def test_project_search_treats_like_metacharacters_as_literals(
    admin_client, published_template, leader_client, literal, expected_name
):
    """User search text must not expand through SQL LIKE wildcard semantics."""
    for index, name in enumerate(
        ("百分%项目", "下划_项目", "感叹!项目", "路径\\项目", "普通项目"),
        start=1,
    ):
        create_project(
            admin_client,
            published_template,
            leader_client.user,
            name=name,
            project_code=f"SEARCH-{index}",
            module_keys=["pre_diagnosis"],
        )

    response = admin_client.get(
        "/api/v1/projects", query_string={"search": literal, "page_size": 20}
    )

    assert response.status_code == 200
    assert [item["name"] for item in response.json["data"]["items"]] == [
        expected_name
    ]


def test_project_update_fields_and_state_machine_require_current_version(
    admin_client, leader_client, published_template
):
    """Unchecked transitions or stale writes would corrupt project lifecycle history."""
    project = create_project(admin_client, published_template, leader_client.user)

    activated = leader_client.patch(
        f"/api/v1/projects/{project['id']}",
        json={
            "version": project["version"],
            "status": "active",
            "contact_name": "新联系人",
            "planned_end_date": "2026-12-01",
        },
    )
    paused = leader_client.patch(
        f"/api/v1/projects/{project['id']}",
        json={"version": activated.json["data"]["version"], "status": "paused"},
    )
    resumed = leader_client.patch(
        f"/api/v1/projects/{project['id']}",
        json={"version": paused.json["data"]["version"], "status": "active"},
    )

    assert activated.status_code == paused.status_code == resumed.status_code == 200
    assert activated.json["data"]["contact_name"] == "新联系人"
    assert activated.json["data"]["planned_end_date"] == "2026-12-01"
    assert resumed.json["data"]["status"] == "active"
    assert_error(
        leader_client.patch(
            f"/api/v1/projects/{project['id']}",
            json={"version": project["version"], "notes": "stale"},
        ),
        409,
        "stale_version",
    )
    assert_error(
        leader_client.patch(
            f"/api/v1/projects/{project['id']}",
            json={"version": resumed.json["data"]["version"], "status": "draft"},
        ),
        409,
        "invalid_project_transition",
    )


def test_project_name_and_background_update_the_research_root(
    admin_client, leader_client, published_template, db_session
):
    project = create_project(
        admin_client,
        published_template,
        leader_client.user,
        background="旧项目背景",
    )

    response = leader_client.patch(
        f"/api/v1/projects/{project['id']}",
        json={
            "version": project["version"],
            "name": "更新后的项目名称",
            "background": "更新后的项目背景",
        },
    )

    assert response.status_code == 200
    db_session.rollback()
    db_session.expire_all()
    root = db_session.scalar(
        select(ProjectResearchSubject).where(
            ProjectResearchSubject.project_id == project["id"],
            ProjectResearchSubject.subject_type == "project",
        )
    )
    assert root is not None
    assert root.name == "更新后的项目名称"
    assert root.description == "更新后的项目背景"
    assert root.version == 2


def test_admin_transfers_project_lead_and_preserves_old_leader_membership(
    admin_client,
    leader_client,
    published_template,
    authorized_client_factory,
    db_session,
):
    """Changing only leader_user_id would leave membership and access inconsistent."""
    new_leader = authorized_client_factory("project_lead")
    project = create_project(admin_client, published_template, leader_client.user)

    response = admin_client.patch(
        f"/api/v1/projects/{project['id']}",
        json={
            "version": project["version"],
            "leader_user_id": new_leader.user.id,
        },
    )

    assert response.status_code == 200
    assert response.json["data"]["leader_user_id"] == new_leader.user.id
    db_session.rollback()
    members = list(
        db_session.scalars(
            select(ProjectMember).where(ProjectMember.project_id == project["id"])
        )
    )
    assert {member.user_id for member in members} == {
        leader_client.user.id,
        new_leader.user.id,
    }
    assert next(
        member.role for member in members if member.user_id == new_leader.user.id
    ) == "member"
    assert new_leader.get(f"/api/v1/projects/{project['id']}").status_code == 200
    assert (
        new_leader.patch(
            f"/api/v1/projects/{project['id']}",
            json={"version": response.json["data"]["version"], "notes": "new owner"},
        ).status_code
        == 200
    )
    assert_error(
        leader_client.patch(
            f"/api/v1/projects/{project['id']}",
            json={"version": response.json["data"]["version"], "notes": "old owner"},
        ),
        403,
        "forbidden",
    )


def test_project_lead_cannot_transfer_project_to_another_user(
    admin_client, leader_client, published_template, authorized_client_factory
):
    """Manage permission alone must not let a non-admin delegate project ownership."""
    other_leader = authorized_client_factory("project_lead")
    project = create_project(admin_client, published_template, leader_client.user)

    response = leader_client.patch(
        f"/api/v1/projects/{project['id']}",
        json={
            "version": project["version"],
            "leader_user_id": other_leader.user.id,
        },
    )

    assert_error(response, 403, "forbidden")


def test_admin_cannot_transfer_project_to_invalid_leader(
    admin_client, leader_client, published_template, authorized_client_factory
):
    """A transferred project leader must remain an active admin or project lead."""
    engineer = authorized_client_factory("fde_engineer")
    project = create_project(admin_client, published_template, leader_client.user)

    response = admin_client.patch(
        f"/api/v1/projects/{project['id']}",
        json={
            "version": project["version"],
            "leader_user_id": engineer.user.id,
        },
    )

    assert_error(response, 400, "invalid_project_leader")


def test_inactive_terminal_project_leader_has_no_primitive_access(
    admin_client, leader_client, published_template, db_session
):
    """An inactive historical leader must not regain view access through membership."""
    project = create_project(admin_client, published_template, leader_client.user)
    cancelled = admin_client.patch(
        f"/api/v1/projects/{project['id']}",
        json={"version": project["version"], "status": "cancelled"},
    )
    assert cancelled.status_code == 200
    disabled = admin_client.patch(
        f"/api/v1/users/{leader_client.user.id}",
        json={"role": "viewer", "is_active": False},
    )
    assert disabled.status_code == 200
    db_session.rollback()
    current_user = db_session.get(User, leader_client.user.id)
    current_project = db_session.get(Project, project["id"])

    assert project_access(current_user, current_project) == ProjectAccess(
        False, False, False
    )


def test_cancelled_project_is_terminal(admin_client, leader_client, published_template):
    """A cancelled project must not resume and silently rewrite its terminal state."""
    project = create_project(admin_client, published_template, leader_client.user)
    cancelled = leader_client.patch(
        f"/api/v1/projects/{project['id']}",
        json={"version": project["version"], "status": "cancelled"},
    )

    assert cancelled.status_code == 200
    assert_error(
        leader_client.patch(
            f"/api/v1/projects/{project['id']}",
            json={"version": cancelled.json["data"]["version"], "status": "active"},
        ),
        409,
        "invalid_project_transition",
    )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("contact_phone", 13800000000),
        ("background", ["not", "text"]),
        ("planned_end_date", "not-a-date"),
        ("status", ["active"]),
    ],
)
def test_project_update_rejects_malformed_optional_fields(
    admin_client, leader_client, published_template, field, value
):
    """Malformed optional values must stay a stable 400 rather than escape as a 500."""
    project = create_project(admin_client, published_template, leader_client.user)

    response = leader_client.patch(
        f"/api/v1/projects/{project['id']}",
        json={"version": project["version"], field: value},
    )

    assert_error(response, 400, "invalid_request")


def test_project_update_can_clear_optional_enterprise_fields(
    admin_client, leader_client, published_template
):
    """Treating optional enterprise text as required would prevent clearing stale data."""
    project = create_project(
        admin_client,
        published_template,
        leader_client.user,
        contact_name="林总",
        contact_phone="13800000000",
        address="示例地址",
        background="旧背景",
        notes="旧备注",
    )

    response = leader_client.patch(
        f"/api/v1/projects/{project['id']}",
        json={
            "version": project["version"],
            "contact_name": "",
            "contact_phone": "",
            "address": "",
            "background": "",
            "notes": "",
        },
    )

    assert response.status_code == 200
    assert {
        field: response.json["data"][field]
        for field in ("contact_name", "contact_phone", "address", "background", "notes")
    } == {
        "contact_name": "",
        "contact_phone": "",
        "address": "",
        "background": "",
        "notes": "",
    }


def test_project_completion_excludes_cancelled_tasks(
    admin_client, leader_client, published_template, db_session
):
    """Including cancelled work would understate completion against active scope."""
    created = create_project(
        admin_client,
        published_template,
        leader_client.user,
        module_keys=["pre_diagnosis"],
    )
    db_session.rollback()
    tasks = list(db_session.scalars(select(ProjectTask)))
    tasks[0].progress = 25
    tasks[1].progress = 75
    tasks[2].progress = 100
    tasks[2].status = "cancelled"
    db_session.commit()

    assert project_completion(created["id"]) == 50


def test_scheduling_failure_rolls_back_the_complete_project_tree(
    admin_client, leader_client, published_template, db_session, monkeypatch
):
    """Committing parents before scheduling would leave an unusable partial project."""
    from fde_api.projects import service

    def fail_scheduling(*_args, **_kwargs):
        raise RuntimeError("forced schedule failure")

    monkeypatch.setattr(service, "schedule_tasks", fail_scheduling)

    response = admin_client.post(
        "/api/v1/projects",
        json=project_payload(published_template, leader_client.user),
    )

    assert_error(response, 503, "project_creation_failed")
    db_session.rollback()
    for model in (
        ProjectTaskDependency,
        ProjectTask,
        ProjectModule,
        ProjectMember,
        OperationEvent,
        Project,
    ):
        assert db_session.scalar(select(func.count()).select_from(model)) == 0


def test_project_dto_serialization_failure_rolls_back_the_complete_project_tree(
    admin_client, leader_client, published_template, db_session, monkeypatch
):
    """Building the response after commit would return failure but retain the project."""
    from fde_api.projects import service

    def fail_serialization(*_args, **_kwargs):
        raise RuntimeError("forced DTO failure")

    monkeypatch.setattr(service, "_serialize_project", fail_serialization)

    response = admin_client.post(
        "/api/v1/projects",
        json=project_payload(published_template, leader_client.user),
    )

    assert_error(response, 503, "project_creation_failed")
    db_session.rollback()
    for model in (
        ProjectTaskDependency,
        ProjectTask,
        ProjectModule,
        ProjectMember,
        OperationEvent,
        Project,
    ):
        assert db_session.scalar(select(func.count()).select_from(model)) == 0
