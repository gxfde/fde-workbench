from dataclasses import dataclass
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

import mysql_lock_race
from fde_api.auth.models import User
from fde_api.auth.passwords import hash_password
from fde_api.auth.tokens import issue_access_token
from fde_api.extensions import db
from fde_api.research.models import ProjectResearchSubject
from fde_api.research import subject_service
from fde_api.workbench.models import IndustryTemplateVersion, OperationEvent, ProjectMember
from fde_api.workbench.seed import seed_workbench
from mysql_lock_race import (
    MysqlLockRaceTimeout,
    RaceDiagnostics,
    open_mysql_observer_or_skip,
    run_mysql_lock_race,
    tracked_mysql_state,
)


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
            username=f"research.{role}.{uuid4().hex}",
            display_name=role,
            role=role,
            password_hash=hash_password("InitialPass!234"),
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


def _project_payload(template, leader):
    return {
        "name": "Research project",
        "enterprise_name": "星河制造",
        "template_version_id": template.id,
        "leader_user_id": leader.id,
        "planned_start_date": "2026-08-22",
        "module_keys": ["pre_diagnosis"],
    }


def _create_project(client, template, leader):
    response = client.post("/api/v1/projects", json=_project_payload(template, leader))
    assert response.status_code == 201, response.get_data(as_text=True)
    return response.json["data"]


def _subject_payload(subject_type: str, **overrides):
    payload = {
        "version": 1,
        "subject_type": subject_type,
        "subject_key": f"{subject_type}_{uuid4().hex[:8]}",
        "name": f"{subject_type} name",
        "description": "",
    }
    payload.update(overrides)
    return payload


def _assert_error(response, status: int, code: str):
    assert response.status_code == status
    assert response.json["data"] is None
    assert response.json["error"]["code"] == code


def test_project_creation_creates_the_root_research_subject(
    admin_client, published_template, leader_client
):
    """Omitting the root subject would leave every project without a stable hierarchy anchor."""
    project = _create_project(admin_client, published_template, leader_client.user)

    response = admin_client.get(
        f"/api/v1/projects/{project['id']}/research/subjects"
    )

    assert response.status_code == 200
    items = response.json["data"]["items"]
    assert len(items) == 1
    assert {key: value for key, value in items[0].items() if key != "id"} == {
        "project_id": project["id"],
        "parent_subject_id": None,
        "subject_type": "project",
        "subject_key": "project",
        "name": "Research project",
        "description": "",
        "sort_order": 0,
        "status": "active",
        "tracking_code": None,
            "version": 1,
            "opportunity_profile": None,
            "links": [],
    }


def test_engineer_cannot_create_subject_in_unassigned_project(
    admin_client, engineer_client, published_template, leader_client
):
    """Dropping project membership checks would expose a foreign project to engineers."""
    foreign_project = _create_project(admin_client, published_template, leader_client.user)

    response = engineer_client.post(
        f"/api/v1/projects/{foreign_project['id']}/research/subjects",
        json=_subject_payload("department"),
    )

    _assert_error(response, 404, "project_not_found")


def test_subject_creation_requires_the_current_project_version(
    admin_client, published_template, leader_client
):
    """Ignoring the project aggregate version would let concurrent creates overwrite its history."""
    project = _create_project(admin_client, published_template, leader_client.user)
    url = f"/api/v1/projects/{project['id']}/research/subjects"

    missing = admin_client.post(url, json={key: value for key, value in _subject_payload("department").items() if key != "version"})
    boolean = admin_client.post(url, json=_subject_payload("department", version=True))
    zero = admin_client.post(url, json=_subject_payload("department", version=0))
    negative = admin_client.post(url, json=_subject_payload("department", version=-1))
    first = admin_client.post(url, json=_subject_payload("department", subject_key="operations"))
    stale = admin_client.post(url, json=_subject_payload("process", version=1))

    _assert_error(missing, 400, "invalid_request")
    _assert_error(boolean, 400, "invalid_request")
    _assert_error(zero, 400, "invalid_request")
    _assert_error(negative, 400, "invalid_request")
    assert first.status_code == 201
    assert first.json["data"]["project_version"] == 2
    _assert_error(stale, 409, "stale_version")


@pytest.mark.parametrize("subject_type", ["project", "bogus"])
def test_client_cannot_create_root_or_unknown_subject_types(
    admin_client, published_template, leader_client, subject_type
):
    """Delegating type validation to the database would return the wrong contract error."""
    project = _create_project(admin_client, published_template, leader_client.user)

    response = admin_client.post(
        f"/api/v1/projects/{project['id']}/research/subjects",
        json=_subject_payload(subject_type, subject_key=f"{subject_type}_client"),
    )

    _assert_error(response, 400, "invalid_request")


def test_subject_create_permissions_distinguish_assigned_engineer_and_viewer(
    admin_client, engineer_client, authorized_client_factory, published_template, leader_client, db_session
):
    """Treating all project members as writers would let viewers modify research scope."""
    project = _create_project(admin_client, published_template, leader_client.user)
    viewer = authorized_client_factory("viewer")
    db_session.add_all(
        [
            ProjectMember(project_id=project["id"], user_id=engineer_client.user.id, role="member"),
            ProjectMember(project_id=project["id"], user_id=viewer.user.id, role="viewer"),
        ]
    )
    db_session.commit()
    url = f"/api/v1/projects/{project['id']}/research/subjects"

    engineer = engineer_client.post(url, json=_subject_payload("department", subject_key="engineering"))
    viewer_response = viewer.post(
        url,
        json=_subject_payload(
            "department", subject_key="viewer_attempt", version=engineer.json["data"]["project_version"]
        ),
    )
    lead = leader_client.post(
        url,
        json=_subject_payload(
            "department", subject_key="lead_department", version=engineer.json["data"]["project_version"]
        ),
    )

    assert engineer.status_code == 201
    _assert_error(viewer_response, 403, "forbidden")
    assert lead.status_code == 201


def test_subjects_get_project_scoped_codes_and_preserve_links_on_archive(
    admin_client, published_template, leader_client
):
    """Changing counters, project scope, or archive handling would break JOB to OPP traceability."""
    project = _create_project(admin_client, published_template, leader_client.user)
    base_url = f"/api/v1/projects/{project['id']}/research/subjects"

    role = admin_client.post(base_url, json=_subject_payload("role", subject_key="planner"))
    assert role.status_code == 201
    opportunity = admin_client.post(
        base_url,
        json=_subject_payload(
            "opportunity",
            subject_key="planning_copilot",
            version=role.json["data"]["project_version"],
        ),
    )
    assert opportunity.status_code == 201
    link = admin_client.post(
        f"{base_url}/{opportunity.json['data']['id']}/links",
        json={
            "version": opportunity.json["data"]["version"],
            "target_subject_id": role.json["data"]["id"],
            "link_type": "opportunity_role",
        },
    )
    assert link.status_code == 201

    archived = admin_client.delete(
        f"{base_url}/{role.json['data']['id']}", json={"version": role.json["data"]["version"]}
    )
    subjects = admin_client.get(base_url)

    assert archived.status_code == 200
    assert role.json["data"]["tracking_code"] == "JOB-0001"
    assert opportunity.json["data"]["tracking_code"] == "OPP-0001"
    assert archived.json["data"]["status"] == "archived"
    listed_opportunity = next(
        item
        for item in subjects.json["data"]["items"]
        if item["id"] == opportunity.json["data"]["id"]
    )
    assert listed_opportunity["links"][0]["target_subject_id"] == role.json["data"]["id"]


def test_opportunity_has_structured_profile_and_can_update_it(
    admin_client, published_template, leader_client
):
    """Removing the opportunity profile would collapse filterable delivery metadata back into form prose."""
    project = _create_project(admin_client, published_template, leader_client.user)
    base_url = f"/api/v1/projects/{project['id']}/research/subjects"
    created = admin_client.post(
        base_url,
        json=_subject_payload("opportunity", subject_key="service_copilot"),
    )

    assert created.status_code == 201, created.get_data(as_text=True)
    opportunity = created.json["data"]
    assert opportunity["opportunity_profile"] == {
        "target_audience": "",
        "owner_user_id": None,
        "owner_display_name": None,
        "opportunity_status": "discovered",
        "priority": None,
        "business_value_score": None,
        "feasibility_score": None,
        "data_readiness_score": None,
        "risk_level": None,
        "next_action": "",
        "evidence": [],
        "ai_generated": False,
    }

    updated = admin_client.patch(
        f"{base_url}/{opportunity['id']}",
        json={
            "version": opportunity["version"],
            "opportunity_profile": {
                "target_audience": "客服部门的一线坐席与主管",
                "owner_user_id": leader_client.user.id,
                "opportunity_status": "ready",
                "priority": "high",
                "business_value_score": 5,
                "feasibility_score": 4,
                "data_readiness_score": 3,
                "risk_level": "medium",
                "next_action": "整理历史工单并创建 PoV 草稿",
            },
        },
    )

    assert updated.status_code == 200, updated.get_data(as_text=True)
    profile = updated.json["data"]["opportunity_profile"]
    assert profile["target_audience"] == "客服部门的一线坐席与主管"
    assert profile["owner_user_id"] == leader_client.user.id
    assert profile["owner_display_name"] == leader_client.user.display_name
    assert profile["business_value_score"] == 5
    assert profile["next_action"] == "整理历史工单并创建 PoV 草稿"


def test_non_opportunity_rejects_opportunity_profile(
    admin_client, published_template, leader_client
):
    """Accepting opportunity metadata on departments would make the subject contract ambiguous."""
    project = _create_project(admin_client, published_template, leader_client.user)
    base_url = f"/api/v1/projects/{project['id']}/research/subjects"
    department = admin_client.post(
        base_url, json=_subject_payload("department", subject_key="support")
    ).json["data"]

    response = admin_client.patch(
        f"{base_url}/{department['id']}",
        json={"version": department["version"], "opportunity_profile": {"priority": "high"}},
    )

    _assert_error(response, 400, "invalid_request")


def test_role_memo_is_saved_independently_from_description(
    admin_client, published_template, leader_client
):
    project = _create_project(admin_client, published_template, leader_client.user)
    base_url = f"/api/v1/projects/{project['id']}/research/subjects"
    department = admin_client.post(
        base_url, json=_subject_payload("department", subject_key="sales")
    ).json["data"]
    role = admin_client.post(
        base_url,
        json=_subject_payload(
            "role",
            subject_key="account_manager",
            version=department["project_version"],
            parent_subject_id=department["id"],
        ),
    ).json["data"]

    updated = admin_client.patch(
        f"{base_url}/{role['id']}/memo",
        json={"version": role["version"], "memo": "客户回访仍用 Excel，待确认数据口径。"},
    )

    assert updated.status_code == 200, updated.get_data(as_text=True)
    assert updated.json["data"]["memo"] == "客户回访仍用 Excel，待确认数据口径。"
    assert updated.json["data"]["version"] == role["version"] + 1
    loaded = admin_client.get(f"{base_url}/{role['id']}/memo")
    assert loaded.status_code == 200
    assert loaded.json["data"] == updated.json["data"]
    listed = admin_client.get(base_url).json["data"]["items"]
    listed_role = next(item for item in listed if item["id"] == role["id"])
    assert listed_role["description"] == role["description"]
    assert "memo" not in listed_role


def test_project_department_and_process_each_accept_an_independent_memo(
    admin_client, published_template, leader_client
):
    project = _create_project(admin_client, published_template, leader_client.user)
    base_url = f"/api/v1/projects/{project['id']}/research/subjects"
    root = next(
        item for item in admin_client.get(base_url).json["data"]["items"]
        if item["subject_type"] == "project"
    )
    department = admin_client.post(
        base_url, json=_subject_payload("department", subject_key="sales")
    ).json["data"]
    process = admin_client.post(
        base_url,
        json=_subject_payload(
            "process",
            subject_key="lead_to_cash",
            version=department["project_version"],
            parent_subject_id=department["id"],
        ),
    ).json["data"]

    for subject, memo in (
        (root, "企业级访谈待确认事项"),
        (department, "部门现场记录"),
        (process, "流程断点与后续动作"),
    ):
        response = admin_client.patch(
            f"{base_url}/{subject['id']}/memo",
            json={"version": subject["version"], "memo": memo},
        )
        assert response.status_code == 200
        assert response.json["data"]["memo"] == memo


def test_subject_memo_preserves_markdown_whitespace(
    admin_client, published_template, leader_client
):
    project = _create_project(admin_client, published_template, leader_client.user)
    base_url = f"/api/v1/projects/{project['id']}/research/subjects"
    subject = next(
        item for item in admin_client.get(base_url).json["data"]["items"]
        if item["subject_type"] == "project"
    )
    memo = "# 访谈记录\n\n  - 保留缩进  \n    - 子项\n"

    response = admin_client.patch(
        f"{base_url}/{subject['id']}/memo",
        json={"version": subject["version"], "memo": memo},
    )

    assert response.status_code == 200
    assert response.json["data"]["memo"] == memo


def test_personal_memos_are_visible_to_project_members_but_only_self_is_writable(
    admin_client, published_template, leader_client, authorized_client_factory, db_session
):
    project = _create_project(admin_client, published_template, leader_client.user)
    engineer = authorized_client_factory("fde_engineer")
    viewer = authorized_client_factory("viewer")
    outsider = authorized_client_factory("viewer")
    db_session.add_all(
        [
            ProjectMember(project_id=project["id"], user_id=engineer.user.id, role="member"),
            ProjectMember(project_id=project["id"], user_id=viewer.user.id, role="viewer"),
        ]
    )
    db_session.commit()
    base_url = f"/api/v1/projects/{project['id']}/research/subjects"
    root = next(
        item for item in admin_client.get(base_url).json["data"]["items"]
        if item["subject_type"] == "project"
    )
    personal_url = f"{base_url}/{root['id']}/personal-memo"
    list_url = f"{base_url}/{root['id']}/personal-memos"

    saved_by_viewer = viewer.patch(
        personal_url,
        json={"version": 0, "memo": "# 个人观察\n\n- 待确认数据来源"},
    )
    assert saved_by_viewer.status_code == 200, saved_by_viewer.get_data(as_text=True)
    assert saved_by_viewer.json["data"]["user_id"] == viewer.user.id
    assert saved_by_viewer.json["data"]["version"] == 1

    visible_to_engineer = engineer.get(list_url)
    assert visible_to_engineer.status_code == 200
    viewer_item = next(
        item for item in visible_to_engineer.json["data"]["items"]
        if item["user_id"] == viewer.user.id
    )
    assert viewer_item["memo"] == "# 个人观察\n\n- 待确认数据来源"
    assert viewer_item["is_current_user"] is False

    # The write endpoint is intentionally bound to the authenticated user;
    # another member can only create or update their own memo.
    saved_by_engineer = engineer.patch(
        personal_url,
        json={"version": 0, "memo": "工程师自己的记录"},
    )
    assert saved_by_engineer.status_code == 200
    assert saved_by_engineer.json["data"]["user_id"] == engineer.user.id
    refreshed = viewer.get(list_url).json["data"]["items"]
    assert next(item for item in refreshed if item["user_id"] == viewer.user.id)["memo"].startswith("# 个人观察")
    assert next(item for item in refreshed if item["user_id"] == engineer.user.id)["memo"] == "工程师自己的记录"

    _assert_error(outsider.get(list_url), 404, "project_not_found")


def test_personal_memos_are_supported_for_department_role_and_process(
    admin_client, published_template, leader_client
):
    project = _create_project(admin_client, published_template, leader_client.user)
    base_url = f"/api/v1/projects/{project['id']}/research/subjects"
    department = admin_client.post(
        base_url, json=_subject_payload("department", subject_key="memo_department")
    ).json["data"]
    role = admin_client.post(
        base_url,
        json=_subject_payload(
            "role",
            subject_key="memo_role",
            version=department["project_version"],
            parent_subject_id=department["id"],
        ),
    ).json["data"]
    process = admin_client.post(
        base_url,
        json=_subject_payload(
            "process",
            subject_key="memo_process",
            version=role["project_version"],
            parent_subject_id=role["id"],
        ),
    ).json["data"]

    for subject in (department, role, process):
        response = admin_client.patch(
            f"{base_url}/{subject['id']}/personal-memo",
            json={"version": 0, "memo": f"{subject['name']}的个人记录"},
        )
        assert response.status_code == 200, response.get_data(as_text=True)
        assert response.json["data"]["memo"].endswith("个人记录")


def test_ai_opportunity_rejects_memo(
    admin_client, published_template, leader_client
):
    project = _create_project(admin_client, published_template, leader_client.user)
    base_url = f"/api/v1/projects/{project['id']}/research/subjects"
    opportunity = admin_client.post(
        base_url, json=_subject_payload("opportunity", subject_key="copilot")
    ).json["data"]

    response = admin_client.patch(
        f"{base_url}/{opportunity['id']}/memo",
        json={"version": opportunity["version"], "memo": "not allowed"},
    )

    _assert_error(response, 400, "invalid_request")


def test_opportunity_profile_validation_reports_exact_reason(
    admin_client, published_template, leader_client
):
    project = _create_project(admin_client, published_template, leader_client.user)
    base_url = f"/api/v1/projects/{project['id']}/research/subjects"
    opportunity = admin_client.post(
        base_url, json=_subject_payload("opportunity", subject_key="invalid_score")
    ).json["data"]

    response = admin_client.patch(
        f"{base_url}/{opportunity['id']}",
        json={"version": opportunity["version"], "opportunity_profile": {"business_value_score": 9}},
    )

    _assert_error(response, 400, "invalid_opportunity_profile")


def test_opportunity_owner_must_be_an_active_project_member(
    admin_client, published_template, leader_client, engineer_client
):
    project = _create_project(admin_client, published_template, leader_client.user)
    base_url = f"/api/v1/projects/{project['id']}/research/subjects"
    opportunity = admin_client.post(
        base_url, json=_subject_payload("opportunity", subject_key="invalid_owner")
    ).json["data"]

    response = admin_client.patch(
        f"{base_url}/{opportunity['id']}",
        json={"version": opportunity["version"], "opportunity_profile": {"owner_user_id": engineer_client.user.id}},
    )

    _assert_error(response, 400, "invalid_opportunity_owner")


def test_subject_parent_type_and_versions_are_enforced(
    admin_client, published_template, leader_client
):
    """Accepting stale writes or a foreign parent would corrupt the subject hierarchy."""
    project = _create_project(admin_client, published_template, leader_client.user)
    base_url = f"/api/v1/projects/{project['id']}/research/subjects"
    department = admin_client.post(
        base_url, json=_subject_payload("department", subject_key="operations")
    )
    assert department.status_code == 201
    invalid_parent = admin_client.post(
        base_url,
        json=_subject_payload(
            "role",
            parent_subject_id="missing-subject",
            version=department.json["data"]["project_version"],
        ),
    )
    updated = admin_client.patch(
        f"{base_url}/{department.json['data']['id']}",
        json={"version": department.json["data"]["version"], "name": "Operations"},
    )
    stale = admin_client.patch(
        f"{base_url}/{department.json['data']['id']}",
        json={"version": department.json["data"]["version"], "name": "Stale"},
    )

    _assert_error(invalid_parent, 404, "research_subject_not_found")
    assert updated.status_code == 200
    _assert_error(stale, 409, "stale_version")


def test_subject_archive_rejects_active_children_without_an_event_or_write(
    admin_client, published_template, leader_client, db_session
):
    """Archiving a parent while its child stays active would orphan the visible research hierarchy."""
    project = _create_project(admin_client, published_template, leader_client.user)
    base_url = f"/api/v1/projects/{project['id']}/research/subjects"
    department = admin_client.post(
        base_url, json=_subject_payload("department", subject_key="operations")
    ).json["data"]
    child = admin_client.post(
        base_url,
        json=_subject_payload(
            "role",
            subject_key="dispatcher",
            version=department["project_version"],
            parent_subject_id=department["id"],
        ),
    )
    assert child.status_code == 201

    response = admin_client.delete(
        f"{base_url}/{department['id']}", json={"version": department["version"]}
    )

    _assert_error(response, 409, "research_subject_has_active_children")
    db_session.expire_all()
    persisted = db_session.get(ProjectResearchSubject, department["id"])
    assert persisted.status == "active"
    assert persisted.version == department["version"]
    events = db_session.scalars(
        select(OperationEvent).where(
            OperationEvent.project_id == project["id"],
            OperationEvent.target_id == department["id"],
            OperationEvent.event_type == "project_research_subject_archived",
        )
    ).all()
    assert events == []


def test_links_require_current_source_version_and_whitelisted_direction(
    admin_client, published_template, leader_client
):
    """Loose edges or stale source writes would make the JOB to OPP graph ambiguous."""
    project = _create_project(admin_client, published_template, leader_client.user)
    base_url = f"/api/v1/projects/{project['id']}/research/subjects"
    role = admin_client.post(base_url, json=_subject_payload("role", subject_key="planner"))
    opportunity = admin_client.post(
        base_url,
        json=_subject_payload(
            "opportunity", subject_key="copilot", version=role.json["data"]["project_version"]
        ),
    )
    link_url = f"{base_url}/{opportunity.json['data']['id']}/links"
    missing = admin_client.post(
        link_url, json={"target_subject_id": role.json["data"]["id"], "link_type": "opportunity_role"}
    )
    boolean = admin_client.post(
        link_url,
        json={"version": True, "target_subject_id": role.json["data"]["id"], "link_type": "opportunity_role"},
    )
    zero = admin_client.post(
        link_url,
        json={"version": 0, "target_subject_id": role.json["data"]["id"], "link_type": "opportunity_role"},
    )
    negative = admin_client.post(
        link_url,
        json={"version": -1, "target_subject_id": role.json["data"]["id"], "link_type": "opportunity_role"},
    )
    invalid_type = admin_client.post(
        link_url,
        json={"version": 1, "target_subject_id": role.json["data"]["id"], "link_type": "addresses"},
    )
    reverse = admin_client.post(
        f"{base_url}/{role.json['data']['id']}/links",
        json={"version": 1, "target_subject_id": opportunity.json["data"]["id"], "link_type": "opportunity_role"},
    )
    linked = admin_client.post(
        link_url,
        json={"version": 1, "target_subject_id": role.json["data"]["id"], "link_type": "opportunity_role"},
    )
    stale = admin_client.post(
        link_url,
        json={"version": 1, "target_subject_id": role.json["data"]["id"], "link_type": "opportunity_role"},
    )

    _assert_error(missing, 400, "invalid_request")
    _assert_error(boolean, 400, "invalid_request")
    _assert_error(zero, 400, "invalid_request")
    _assert_error(negative, 400, "invalid_request")
    _assert_error(invalid_type, 422, "invalid_research_subject_link")
    _assert_error(reverse, 422, "invalid_research_subject_link")
    assert linked.status_code == 201
    assert linked.json["data"]["source_version"] == 2
    _assert_error(stale, 409, "stale_version")


def test_subject_keys_cannot_be_renamed_or_accepted_as_unknown_patch_fields(
    admin_client, published_template, leader_client
):
    """Allowing stable-key patches would orphan forms and document references."""
    project = _create_project(admin_client, published_template, leader_client.user)
    base_url = f"/api/v1/projects/{project['id']}/research/subjects"
    subject = admin_client.post(base_url, json=_subject_payload("department", subject_key="operations"))

    response = admin_client.patch(
        f"{base_url}/{subject.json['data']['id']}",
        json={"version": 1, "subject_key": "renamed"},
    )

    _assert_error(response, 400, "invalid_request")


def test_tracking_codes_are_numeric_and_scoped_to_each_project(
    admin_client, published_template, leader_client, db_session
):
    """Lexicographic code selection would collide after JOB-9999 or share counters between projects."""
    first_project = _create_project(admin_client, published_template, leader_client.user)
    second_project = _create_project(admin_client, published_template, leader_client.user)
    db_session.add_all(
        [
            ProjectResearchSubject(
                project_id=first_project["id"], subject_type="role", subject_key="existing_nine", name="Existing 9999", tracking_code="JOB-9999"
            ),
            ProjectResearchSubject(
                project_id=first_project["id"], subject_type="role", subject_key="existing_ten", name="Existing 10000", tracking_code="JOB-10000"
            ),
        ]
    )
    db_session.commit()
    first_url = f"/api/v1/projects/{first_project['id']}/research/subjects"
    second_url = f"/api/v1/projects/{second_project['id']}/research/subjects"

    next_first = admin_client.post(first_url, json=_subject_payload("role", subject_key="next_role"))
    first_second = admin_client.post(
        first_url,
        json=_subject_payload("role", subject_key="after_next", version=next_first.json["data"]["project_version"]),
    )
    second = admin_client.post(second_url, json=_subject_payload("role", subject_key="second_role"))

    assert next_first.status_code == 201
    assert next_first.json["data"]["tracking_code"] == "JOB-10001"
    assert first_second.json["data"]["tracking_code"] == "JOB-10002"
    assert second.json["data"]["tracking_code"] == "JOB-0001"


def test_subject_relationships_reject_cross_project_and_invalid_parent_types(
    admin_client, published_template, leader_client
):
    """Cross-project edges or arbitrary hierarchy parents would expose unrelated research data."""
    first = _create_project(admin_client, published_template, leader_client.user)
    second = _create_project(admin_client, published_template, leader_client.user)
    first_url = f"/api/v1/projects/{first['id']}/research/subjects"
    second_url = f"/api/v1/projects/{second['id']}/research/subjects"
    department = admin_client.post(first_url, json=_subject_payload("department", subject_key="operations"))
    foreign_role = admin_client.post(second_url, json=_subject_payload("role", subject_key="foreign_role"))
    # Under the hierarchy rules an opportunity may sit directly under a department.
    opportunity_under_department = admin_client.post(
        first_url,
        json=_subject_payload(
            "opportunity",
            subject_key="copilot_under_department",
            parent_subject_id=department.json["data"]["id"],
            version=department.json["data"]["project_version"],
        ),
    )
    assert opportunity_under_department.status_code == 201
    project_version = opportunity_under_department.json["data"]["project_version"]
    # A process may not sit under an opportunity.
    invalid_parent = admin_client.post(
        first_url,
        json=_subject_payload(
            "process",
            subject_key="invalid_parent",
            parent_subject_id=opportunity_under_department.json["data"]["id"],
            version=project_version,
        ),
    )
    cross_parent = admin_client.post(
        first_url,
        json=_subject_payload(
            "role",
            subject_key="cross_parent",
            parent_subject_id=foreign_role.json["data"]["id"],
            version=project_version,
        ),
    )
    opportunity = admin_client.post(
        first_url,
        json=_subject_payload(
            "opportunity",
            subject_key="copilot",
            version=project_version,
        ),
    )
    cross_link = admin_client.post(
        f"{first_url}/{opportunity.json['data']['id']}/links",
        json={
            "version": 1,
            "target_subject_id": foreign_role.json["data"]["id"],
            "link_type": "opportunity_role",
        },
    )

    _assert_error(invalid_parent, 400, "invalid_subject_parent")
    _assert_error(cross_parent, 404, "research_subject_not_found")
    assert opportunity.status_code == 201
    _assert_error(cross_link, 404, "research_subject_not_found")


def test_unknown_subject_and_link_payload_keys_are_rejected(
    admin_client, published_template, leader_client
):
    """Silently accepting unknown fields would make the API contract non-deterministic."""
    project = _create_project(admin_client, published_template, leader_client.user)
    base_url = f"/api/v1/projects/{project['id']}/research/subjects"
    unknown_subject = admin_client.post(
        base_url, json=_subject_payload("department", unsupported="value")
    )
    role = admin_client.post(base_url, json=_subject_payload("role", subject_key="planner"))
    opportunity = admin_client.post(
        base_url,
        json=_subject_payload(
            "opportunity", subject_key="copilot", version=role.json["data"]["project_version"]
        ),
    )
    unknown_link = admin_client.post(
        f"{base_url}/{opportunity.json['data']['id']}/links",
        json={
            "version": 1,
            "target_subject_id": role.json["data"]["id"],
            "link_type": "opportunity_role",
            "unsupported": "value",
        },
    )

    _assert_error(unknown_subject, 400, "invalid_request")
    _assert_error(unknown_link, 400, "invalid_request")


def test_subject_creation_event_failure_rolls_back_project_version_and_code(
    admin_client, published_template, leader_client, monkeypatch
):
    """A failed audit append must roll back both the new subject and its project aggregate update."""
    project = _create_project(admin_client, published_template, leader_client.user)
    base_url = f"/api/v1/projects/{project['id']}/research/subjects"

    def fail_event(*_args, **_kwargs):
        raise SQLAlchemyError("event storage unavailable")

    monkeypatch.setattr(subject_service, "record_event", fail_event)
    failed = admin_client.post(base_url, json=_subject_payload("role", subject_key="failed_role"))
    monkeypatch.undo()
    detail = admin_client.get(f"/api/v1/projects/{project['id']}")
    retry = admin_client.post(base_url, json=_subject_payload("role", subject_key="retry_role"))

    _assert_error(failed, 503, "research_subject_mutation_failed")
    assert detail.json["data"]["version"] == 1
    assert retry.status_code == 201
    assert retry.json["data"]["tracking_code"] == "JOB-0001"
    assert retry.json["data"]["project_version"] == 2


def test_subject_link_event_failure_rolls_back_source_version_and_edge(
    admin_client, published_template, leader_client, monkeypatch
):
    """A failed link audit must not consume the source subject's optimistic version."""
    project = _create_project(admin_client, published_template, leader_client.user)
    base_url = f"/api/v1/projects/{project['id']}/research/subjects"
    role = admin_client.post(base_url, json=_subject_payload("role", subject_key="planner"))
    opportunity = admin_client.post(
        base_url,
        json=_subject_payload(
            "opportunity", subject_key="copilot", version=role.json["data"]["project_version"]
        ),
    )
    link_url = f"{base_url}/{opportunity.json['data']['id']}/links"

    def fail_event(*_args, **_kwargs):
        raise SQLAlchemyError("event storage unavailable")

    monkeypatch.setattr(subject_service, "record_event", fail_event)
    failed = admin_client.post(
        link_url,
        json={"version": 1, "target_subject_id": role.json["data"]["id"], "link_type": "opportunity_role"},
    )
    monkeypatch.undo()
    retry = admin_client.post(
        link_url,
        json={"version": 1, "target_subject_id": role.json["data"]["id"], "link_type": "opportunity_role"},
    )

    _assert_error(failed, 503, "research_subject_mutation_failed")
    assert retry.status_code == 201
    assert retry.json["data"]["source_version"] == 2


def _mysql_lock_race_kwargs(app, admin_client, project, url):
    return {
        "settings_payload": app.config["SETTINGS"].model_dump(mode="json"),
        "request_url": url,
        "request_headers": dict(admin_client.headers),
        "request_payloads": (
            _subject_payload(
                "role", subject_key="concurrent_role_first", version=project["version"]
            ),
            _subject_payload(
                "role", subject_key="concurrent_role_second", version=project["version"]
            ),
        ),
    }


def _flatten_exceptions(error: BaseException):
    if isinstance(error, BaseExceptionGroup):
        return [nested for item in error.exceptions for nested in _flatten_exceptions(item)]
    return [error]


@pytest.mark.mysql_observer
def test_concurrent_subject_creates_allow_one_current_project_version(
    app, admin_client, published_template, leader_client
):
    """The loser must be observed waiting on the winner's real MySQL project-row lock."""
    project = _create_project(admin_client, published_template, leader_client.user)
    url = f"/api/v1/projects/{project['id']}/research/subjects"

    with app.app_context():
        with open_mysql_observer_or_skip(db.engine) as observer:
            race = run_mysql_lock_race(
                observer=observer,
                **_mysql_lock_race_kwargs(app, admin_client, project, url),
            )

    evidence = race.lock_wait_evidence
    assert evidence["requesting_connection_id"] == race.lock_connection_ids["second"]
    assert evidence["blocking_connection_id"] == race.lock_connection_ids["first"]
    assert evidence["requesting_transaction_id"] is not None
    assert evidence["blocking_transaction_id"] is not None
    assert evidence["requesting_transaction_id"] != evidence["blocking_transaction_id"]
    assert evidence["object_schema"] == "fde_workbench_test"
    assert evidence["object_name"] == "projects"
    assert evidence["requesting_lock_status"] == "WAITING"
    assert evidence["blocking_lock_status"] == "GRANTED"

    statuses = sorted(status for status, _payload in race.responses)
    failed_payload = next(payload for status, payload in race.responses if status == 409)
    detail = admin_client.get(f"/api/v1/projects/{project['id']}")
    subjects = admin_client.get(url).json["data"]["items"]
    roles = [subject for subject in subjects if subject["subject_type"] == "role"]

    assert statuses == [201, 409]
    assert failed_payload["error"]["code"] == "stale_version"
    assert detail.json["data"]["version"] == project["version"] + 1
    assert len(roles) == 1
    assert [role["tracking_code"] for role in roles] == ["JOB-0001"]


@pytest.mark.mysql_observer
def test_kill_query_error_still_runs_connection_cleanup_and_joins_child(
    app,
    admin_client,
    published_template,
    leader_client,
    monkeypatch,
):
    """A failed KILL QUERY must not skip stronger cleanup or leave a child behind."""
    project = _create_project(admin_client, published_template, leader_client.user)
    url = f"/api/v1/projects/{project['id']}/research/subjects"
    diagnostics = RaceDiagnostics()
    kill_kinds = []
    real_kill = mysql_lock_race._kill_exact_lock_connections

    def fail_query_only(observer, connection_ids, kind):
        kill_kinds.append(kind)
        if kind == "QUERY":
            raise RuntimeError("injected KILL QUERY failure")
        return real_kill(observer, connection_ids, kind)

    monkeypatch.setattr(mysql_lock_race, "_kill_exact_lock_connections", fail_query_only)

    with app.app_context():
        with open_mysql_observer_or_skip(db.engine) as observer:
            with pytest.raises(BaseExceptionGroup) as raised:
                run_mysql_lock_race(
                    observer=observer,
                    diagnostics=diagnostics,
                    process_timeout=0.2,
                    force_child_hang=True,
                    **_mysql_lock_race_kwargs(app, admin_client, project, url),
                )
            state = tracked_mysql_state(observer, diagnostics.tracked_connection_ids)

    flattened = _flatten_exceptions(raised.value)
    assert any(isinstance(error, MysqlLockRaceTimeout) for error in flattened)
    assert any("injected KILL QUERY failure" in str(error) for error in flattened)
    assert kill_kinds == ["QUERY", "CONNECTION"]
    assert diagnostics.kill_commands == [
        ("CONNECTION", connection_id)
        for connection_id in sorted(diagnostics.tracked_connection_ids)
    ]
    assert diagnostics.child_exitcode is not None
    assert diagnostics.hard_terminated is True
    assert state.active_transactions == ()
    assert state.lock_wait_count == 0
    assert admin_client.get(f"/api/v1/projects/{project['id']}").status_code == 200


@pytest.mark.mysql_observer
def test_scenario_timeout_clears_tracked_mysql_state_before_fixture_continues(
    app, admin_client, published_template, leader_client
):
    """A wedged child must be hard-stopped before later fixture database work begins."""
    project = _create_project(admin_client, published_template, leader_client.user)
    url = f"/api/v1/projects/{project['id']}/research/subjects"
    diagnostics = RaceDiagnostics()

    with app.app_context():
        with open_mysql_observer_or_skip(db.engine) as observer:
            with pytest.raises(MysqlLockRaceTimeout):
                run_mysql_lock_race(
                    observer=observer,
                    diagnostics=diagnostics,
                    process_timeout=0.2,
                    force_child_hang=True,
                    **_mysql_lock_race_kwargs(app, admin_client, project, url),
                )
            state = tracked_mysql_state(observer, diagnostics.tracked_connection_ids)

    assert diagnostics.child_exitcode is not None
    assert diagnostics.hard_terminated is True
    assert state.active_transactions == ()
    assert state.lock_wait_count == 0
    assert admin_client.get(f"/api/v1/projects/{project['id']}").status_code == 200
