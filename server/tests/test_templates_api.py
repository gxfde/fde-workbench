from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass

import pytest
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from fde_api.auth.models import User
from fde_api.auth.passwords import hash_password
from fde_api.auth.tokens import issue_access_token
from fde_api.templates.service import serialize_template_snapshot
from fde_api.workbench.models import (
    IndustryTemplate,
    IndustryTemplateVersion,
    ModuleCatalog,
    OperationEvent,
    TemplateTask,
    TemplateTaskDependency,
)


INITIAL_PASSWORD = "InitialPass!234"


@dataclass(frozen=True)
class AuthorizedClient:
    client: object
    headers: dict[str, str]

    def get(self, *args, **kwargs):
        return self.client.get(*args, headers=self.headers, **kwargs)

    def post(self, *args, **kwargs):
        return self.client.post(*args, headers=self.headers, **kwargs)

    def patch(self, *args, **kwargs):
        return self.client.patch(*args, headers=self.headers, **kwargs)


@pytest.fixture
def authorized_client_factory(client, db_session, settings):
    def create(role: str) -> AuthorizedClient:
        user = User(
            username=f"{role}.template",
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
            {"Authorization": f"Bearer {issue_access_token(user, settings)}"},
        )

    return create


@pytest.fixture
def admin_client(authorized_client_factory):
    return authorized_client_factory("admin")


@pytest.fixture
def project_lead_client(authorized_client_factory):
    return authorized_client_factory("project_lead")


@pytest.fixture
def engineer_client(authorized_client_factory):
    return authorized_client_factory("fde_engineer")


def assert_error(response, status: int, code: str) -> None:
    assert response.status_code == status
    assert response.json["data"] is None
    assert response.json["error"]["code"] == code


@pytest.fixture
def template_v1_payload(db_session):
    db_session.add_all(
        [
            ModuleCatalog(
                module_key="pre_diagnosis",
                name="前期诊断",
                description="澄清业务目标。",
                sort_order=10,
                is_active=True,
            ),
            ModuleCatalog(
                module_key="pov",
                name="PoV 验证",
                description="验证价值。",
                sort_order=30,
                is_active=True,
            ),
        ]
    )
    db_session.commit()
    return {
        "name": "制造业 AI 落地模板",
        "industry_name": "制造业",
        "description": "从诊断到 PoV。",
        "modules": [
            {
                "module_key": "pre_diagnosis",
                "name": "前期诊断",
                "description": "确认目标。",
                "sort_order": 10,
                "tasks": [
                    {
                        "task_key": "collect_enterprise_info",
                        "name": "收集企业基础信息",
                        "description": "",
                        "duration_days": 2,
                        "default_assignee_role": "project_lead",
                        "sort_order": 10,
                        "dependency_keys": [],
                    },
                    {
                        "task_key": "confirm_business_scope",
                        "name": "明确业务目标与范围",
                        "description": "",
                        "duration_days": 1,
                        "default_assignee_role": "project_lead",
                        "sort_order": 20,
                        "dependency_keys": ["collect_enterprise_info"],
                    },
                ],
            },
            {
                "module_key": "pov",
                "name": "PoV 验证",
                "description": "验证优先场景。",
                "sort_order": 30,
                "tasks": [
                    {
                        "task_key": "build_pov",
                        "name": "开发 PoV 方案",
                        "description": "",
                        "duration_days": 5,
                        "default_assignee_role": "fde_engineer",
                        "sort_order": 10,
                        "dependency_keys": ["confirm_business_scope"],
                    }
                ],
            },
        ],
    }


@pytest.fixture
def cyclic_template_payload(template_v1_payload):
    payload = deepcopy(template_v1_payload)
    first, second = payload["modules"][0]["tasks"]
    first["dependency_keys"] = [second["task_key"]]
    return payload


def create_template(admin_client, payload):
    response = admin_client.post("/api/v1/industry-templates", json=payload)
    assert response.status_code == 201
    return response.json["data"]


def current_version(admin_client, version_id: str) -> int:
    return admin_client.get(
        f"/api/v1/industry-templates/versions/{version_id}"
    ).json["data"]["version"]


def publish_template(admin_client, version_id: str, *, version: int | None = None):
    return admin_client.post(
        f"/api/v1/industry-templates/versions/{version_id}/publish",
        json={
            "version": current_version(admin_client, version_id)
            if version is None
            else version
        },
    )


def deactivate_template(admin_client, version_id: str, *, version: int | None = None):
    return admin_client.post(
        f"/api/v1/industry-templates/versions/{version_id}/deactivate",
        json={
            "version": current_version(admin_client, version_id)
            if version is None
            else version
        },
    )


def delete_with(authorized_client, url: str, *, version: int | None = None):
    kwargs = {"headers": authorized_client.headers}
    if version is not None:
        kwargs["json"] = {"version": version}
    return authorized_client.client.delete(url, **kwargs)


def test_published_version_remains_editable(
    admin_client, template_v1_payload
):
    """Editing a published template in place does not touch project snapshots copied at creation."""
    created = create_template(admin_client, template_v1_payload)

    published = publish_template(admin_client, created["version_id"])

    assert published.status_code == 200
    assert published.json["data"]["version_number"] == 1
    assert published.json["data"]["version"] == created["version"] + 1

    # A published template is still editable; only inactive versions are locked.
    edited = admin_client.patch(
        f"/api/v1/industry-templates/versions/{created['version_id']}",
        json={
            "version": published.json["data"]["version"],
            "description": "mutate",
        },
    )

    assert edited.status_code == 200
    assert edited.json["data"]["version"] == published.json["data"]["version"] + 1
    assert edited.json["data"]["description"] == "mutate"

    # Deleting a non-draft version is still rejected (kept in the audit history).
    assert_error(
        delete_with(
            admin_client,
            f"/api/v1/industry-templates/versions/{created['version_id']}",
            version=edited.json["data"]["version"],
        ),
        409,
        "template_version_immutable",
    )

    copied = admin_client.post(
        f"/api/v1/industry-templates/{created['template_id']}/versions", json={}
    )

    assert copied.status_code == 201
    assert copied.json["data"]["version_number"] == 2
    assert copied.json["data"]["status"] == "draft"
    assert copied.json["data"]["modules"] == [
        {
            **module,
            "id": copied.json["data"]["modules"][index]["id"],
            "tasks": [
                {
                    **task,
                    "id": copied.json["data"]["modules"][index]["tasks"][task_index]["id"],
                }
                for task_index, task in enumerate(module["tasks"])
            ],
        }
        for index, module in enumerate(edited.json["data"]["modules"])
    ]
    assert {
        module["id"] for module in copied.json["data"]["modules"]
    }.isdisjoint({module["id"] for module in edited.json["data"]["modules"]})


def test_publish_rejects_a_stale_second_editor_and_increments_once(
    admin_client, template_v1_payload, db_session
):
    """A second publisher using the same draft DTO must not repeat the transition."""
    created = create_template(admin_client, template_v1_payload)

    published = publish_template(
        admin_client, created["version_id"], version=created["version"]
    )
    stale = publish_template(
        admin_client, created["version_id"], version=created["version"]
    )

    assert published.status_code == 200
    assert published.json["data"]["status"] == "published"
    assert published.json["data"]["version"] == created["version"] + 1
    assert_error(stale, 409, "stale_version")
    events = list(
        db_session.scalars(
            select(OperationEvent).where(
                OperationEvent.target_id == created["version_id"],
                OperationEvent.event_type
                == "industry_template_version_published",
            )
        )
    )
    assert len(events) == 1
    assert events[0].project_id is None
    assert events[0].target_type == "industry_template_version"
    assert events[0].changes == {
        "status": {"from": "draft", "to": "published"},
        "version_number": 1,
    }


def test_publish_validation_failure_writes_no_operation_event(
    admin_client, cyclic_template_payload, db_session
):
    """An invalid draft must not leave an audit event for a transition that never happened."""
    created = create_template(admin_client, cyclic_template_payload)

    response = publish_template(admin_client, created["version_id"])

    assert_error(response, 400, "cyclic_dependency")
    assert list(
        db_session.scalars(
            select(OperationEvent).where(
                OperationEvent.target_id == created["version_id"],
                OperationEvent.event_type == "industry_template_version_published",
            )
        )
    ) == []


def test_publish_rolls_back_the_event_and_status_together(
    admin_client, template_v1_payload, db_session, monkeypatch
):
    """Committing publication separately from its event would leave one side without the other."""
    from fde_api.projects.events import record_event as real_record_event

    created = create_template(admin_client, template_v1_payload)

    def record_then_fail(*args, **kwargs):
        real_record_event(*args, **kwargs)
        raise SQLAlchemyError("forced event failure")

    monkeypatch.setattr(
        "fde_api.projects.events.record_event", record_then_fail
    )

    response = publish_template(admin_client, created["version_id"])
    db_session.expire_all()
    version = db_session.get(IndustryTemplateVersion, created["version_id"])

    assert_error(response, 503, "template_publish_failed")
    assert version.status == "draft"
    assert version.version == created["version"]
    assert list(
        db_session.scalars(
            select(OperationEvent).where(
                OperationEvent.target_id == created["version_id"],
                OperationEvent.event_type == "industry_template_version_published",
            )
        )
    ) == []


def test_editing_v2_metadata_does_not_change_published_v1_history(
    admin_client, template_v1_payload
):
    """Version metadata stored on the aggregate root would rewrite published history."""
    created = create_template(admin_client, template_v1_payload)
    assert publish_template(admin_client, created["version_id"]).status_code == 200
    v1_before = admin_client.get(
        f"/api/v1/industry-templates/versions/{created['version_id']}"
    ).json["data"]
    v2 = admin_client.post(
        f"/api/v1/industry-templates/{created['template_id']}/versions", json={}
    ).json["data"]

    changed = admin_client.patch(
        f"/api/v1/industry-templates/versions/{v2['version_id']}",
        json={
            "version": v2["version"],
            "name": "制造业 AI 落地模板 v2",
            "industry_name": "先进制造",
            "description": "v2 only",
        },
    )
    v1_after = admin_client.get(
        f"/api/v1/industry-templates/versions/{created['version_id']}"
    ).json["data"]

    assert changed.status_code == 200
    assert changed.json["data"]["description"] == "v2 only"
    assert v1_after == v1_before


def test_template_with_cycle_cannot_publish(admin_client, cyclic_template_payload):
    """Skipping DAG validation would publish a template that cannot be scheduled."""
    created = create_template(admin_client, cyclic_template_payload)

    response = publish_template(admin_client, created["version_id"])

    assert_error(response, 400, "cyclic_dependency")


def test_self_dependency_is_rejected_as_a_document_cycle(
    admin_client, template_v1_payload
):
    """Letting a self-edge reach the database would misclassify it as a 409 conflict."""
    payload = deepcopy(template_v1_payload)
    task = payload["modules"][0]["tasks"][0]
    task["dependency_keys"] = [task["task_key"]]

    response = admin_client.post("/api/v1/industry-templates", json=payload)

    assert_error(response, 400, "cyclic_dependency")


def test_non_string_task_role_returns_stable_validation_error(
    admin_client, template_v1_payload
):
    """Set membership on malformed JSON must not escape as an internal server error."""
    payload = deepcopy(template_v1_payload)
    payload["modules"][0]["tasks"][0]["default_assignee_role"] = ["project_lead"]

    response = admin_client.post("/api/v1/industry-templates", json=payload)

    assert_error(response, 400, "invalid_request")


def test_draft_replacement_is_atomic_and_rejects_child_ids(
    admin_client, template_v1_payload
):
    """Accepting client child IDs could attach another version's child or lose the draft."""
    first = create_template(admin_client, template_v1_payload)
    other_payload = deepcopy(template_v1_payload)
    other_payload["name"] = "其他模板"
    other = create_template(admin_client, other_payload)
    before = admin_client.get(
        f"/api/v1/industry-templates/versions/{first['version_id']}"
    ).json["data"]
    rejected_modules = deepcopy(template_v1_payload["modules"])
    rejected_modules[0]["id"] = other["modules"][0]["id"]

    response = admin_client.patch(
        f"/api/v1/industry-templates/versions/{first['version_id']}",
        json={
            "version": first["version"],
            "description": "must roll back",
            "modules": rejected_modules,
        },
    )

    assert_error(response, 400, "invalid_request")
    after = admin_client.get(
        f"/api/v1/industry-templates/versions/{first['version_id']}"
    ).json["data"]
    assert after["description"] == before["description"]
    assert after["modules"] == before["modules"]


def test_draft_patch_replaces_the_complete_child_tree(admin_client, template_v1_payload):
    """Appending a replacement tree would retain removed tasks and duplicate dependencies."""
    created = create_template(admin_client, template_v1_payload)
    original_ids = {
        task["id"]
        for module in created["modules"]
        for task in module["tasks"]
    }
    replacement = deepcopy(template_v1_payload["modules"][:1])
    replacement[0]["tasks"] = replacement[0]["tasks"][:1]
    replacement[0]["tasks"][0]["name"] = "重新收集企业信息"

    response = admin_client.patch(
        f"/api/v1/industry-templates/versions/{created['version_id']}",
        json={
            "version": created["version"],
            "description": "更新后说明",
            "modules": replacement,
        },
    )

    assert response.status_code == 200
    updated = response.json["data"]
    assert updated["description"] == "更新后说明"
    assert [module["module_key"] for module in updated["modules"]] == [
        "pre_diagnosis"
    ]
    assert [task["task_key"] for task in updated["modules"][0]["tasks"]] == [
        "collect_enterprise_info"
    ]
    assert updated["modules"][0]["tasks"][0]["name"] == "重新收集企业信息"
    assert updated["modules"][0]["tasks"][0]["id"] not in original_ids


def test_draft_patch_rejects_stale_expected_version(admin_client, template_v1_payload):
    """Serial row locks alone would let a later stale editor overwrite newer draft data."""
    created = create_template(admin_client, template_v1_payload)

    first = admin_client.patch(
        f"/api/v1/industry-templates/versions/{created['version_id']}",
        json={"version": 1, "description": "first editor"},
    )
    stale = admin_client.patch(
        f"/api/v1/industry-templates/versions/{created['version_id']}",
        json={"version": 1, "description": "stale editor"},
    )
    current = admin_client.get(
        f"/api/v1/industry-templates/versions/{created['version_id']}"
    ).json["data"]

    assert created["version"] == 1
    assert first.status_code == 200
    assert first.json["data"]["version"] == 2
    assert_error(stale, 409, "stale_version")
    assert current["description"] == "first editor"
    assert current["version"] == 2


@pytest.mark.parametrize("field", ["name", "industry_name", "description", "modules"])
def test_draft_patch_rejects_explicit_null_fields(
    admin_client, template_v1_payload, field
):
    """Treating explicit null as omission would silently acknowledge an invalid edit."""
    created = create_template(admin_client, template_v1_payload)

    response = admin_client.patch(
        f"/api/v1/industry-templates/versions/{created['version_id']}",
        json={"version": created["version"], field: None},
    )

    assert_error(response, 400, "invalid_request")


def test_publish_rejects_a_module_deactivated_after_draft_creation(
    admin_client, template_v1_payload, db_session
):
    """Publishing a disabled catalog module would make new projects select retired work."""
    created = create_template(admin_client, template_v1_payload)
    module = db_session.scalar(
        select(ModuleCatalog).where(ModuleCatalog.module_key == "pov")
    )
    module.is_active = False
    db_session.commit()

    response = publish_template(admin_client, created["version_id"])

    assert_error(response, 400, "inactive_module")


def test_publish_revalidates_stable_task_keys(admin_client, template_v1_payload, db_session):
    """Trusting only API input validation would publish a database-corrupted task key."""
    created = create_template(admin_client, template_v1_payload)
    task = db_session.get(TemplateTask, created["modules"][0]["tasks"][0]["id"])
    task.task_key = "Not stable"
    db_session.commit()

    response = publish_template(admin_client, created["version_id"])

    assert_error(response, 400, "invalid_task_key")


def test_publish_rejects_dependency_crossing_template_versions(
    admin_client, template_v1_payload, db_session
):
    """A cross-version edge would couple immutable histories and corrupt scheduling."""
    first = create_template(admin_client, template_v1_payload)
    second_payload = deepcopy(template_v1_payload)
    second_payload["name"] = "另一个模板"
    second = create_template(admin_client, second_payload)
    db_session.add(
        TemplateTaskDependency(
            predecessor_task_id=second["modules"][0]["tasks"][0]["id"],
            successor_task_id=first["modules"][0]["tasks"][0]["id"],
        )
    )
    db_session.commit()

    response = publish_template(admin_client, first["version_id"])

    assert_error(response, 400, "missing_dependency")


def test_project_lead_lists_only_active_published_versions_and_cannot_mutate(
    admin_client, project_lead_client, template_v1_payload
):
    """Exposing drafts to project leads would let projects use unapproved definitions."""
    published = create_template(admin_client, template_v1_payload)
    assert publish_template(admin_client, published["version_id"]).status_code == 200
    draft = admin_client.post(
        f"/api/v1/industry-templates/{published['template_id']}/versions", json={}
    ).json["data"]

    lead_list = project_lead_client.get("/api/v1/industry-templates")
    lead_history = project_lead_client.get(
        f"/api/v1/industry-templates/{published['template_id']}/versions"
    )
    admin_history = admin_client.get(
        f"/api/v1/industry-templates/{published['template_id']}/versions"
    )

    assert lead_list.status_code == 200
    assert [item["version_id"] for item in lead_list.json["data"]["items"]] == [
        published["version_id"]
    ]
    assert [item["status"] for item in lead_history.json["data"]["items"]] == [
        "published"
    ]
    assert [item["status"] for item in admin_history.json["data"]["items"]] == [
        "draft",
        "published",
    ]
    assert_error(
        project_lead_client.get(
            f"/api/v1/industry-templates/versions/{draft['version_id']}"
        ),
        403,
        "forbidden",
    )
    assert_error(
        project_lead_client.patch(
            f"/api/v1/industry-templates/versions/{draft['version_id']}",
            json={"description": "unauthorized"},
        ),
        403,
        "forbidden",
    )
    assert_error(
        project_lead_client.post(
            f"/api/v1/industry-templates/versions/{published['version_id']}/deactivate",
            json={"version": published["version"]},
        ),
        403,
        "forbidden",
    )


def test_engineer_cannot_list_template_catalog(
    admin_client, engineer_client, template_v1_payload
):
    """Allowing engineers to browse templates would exceed the project-creation role scope."""
    created = create_template(admin_client, template_v1_payload)
    assert publish_template(admin_client, created["version_id"]).status_code == 200

    response = engineer_client.get("/api/v1/industry-templates")

    assert_error(response, 403, "forbidden")


def test_admin_deactivates_published_version_without_deleting_history(
    admin_client, project_lead_client, template_v1_payload
):
    """Deleting a retired published version would break project provenance."""
    created = create_template(admin_client, template_v1_payload)
    published = publish_template(admin_client, created["version_id"])
    assert published.status_code == 200

    deactivated = deactivate_template(
        admin_client,
        created["version_id"],
        version=published.json["data"]["version"],
    )

    assert deactivated.status_code == 200
    assert deactivated.json["data"]["status"] == "inactive"
    assert deactivated.json["data"]["version"] == published.json["data"]["version"] + 1
    assert project_lead_client.get("/api/v1/industry-templates").json["data"][
        "items"
    ] == []
    history = admin_client.get(
        f"/api/v1/industry-templates/{created['template_id']}/versions"
    )
    assert history.json["data"]["items"][0]["status"] == "inactive"
    assert_error(
        delete_with(
            admin_client,
            f"/api/v1/industry-templates/versions/{created['version_id']}",
            version=deactivated.json["data"]["version"],
        ),
        409,
        "template_version_immutable",
    )


def test_deactivating_latest_version_restores_root_alias_to_previous_publication(
    admin_client, template_v1_payload, db_session
):
    """Leaving the aggregate alias on inactive v2 would contradict its latest-v1 marker."""
    v1 = create_template(admin_client, template_v1_payload)
    assert publish_template(admin_client, v1["version_id"]).status_code == 200
    v2 = admin_client.post(
        f"/api/v1/industry-templates/{v1['template_id']}/versions", json={}
    ).json["data"]
    updated_v2 = admin_client.patch(
        f"/api/v1/industry-templates/versions/{v2['version_id']}",
        json={
            "version": v2["version"],
            "name": "v2 alias",
            "industry_name": "v2 industry",
            "description": "v2 description",
        },
    ).json["data"]
    assert publish_template(admin_client, updated_v2["version_id"]).status_code == 200

    response = deactivate_template(admin_client, v2["version_id"])
    db_session.expire_all()
    root = db_session.get(IndustryTemplate, v1["template_id"])

    assert response.status_code == 200
    assert root.latest_published_version_number == 1
    assert root.name == template_v1_payload["name"]
    assert root.industry_name == template_v1_payload["industry_name"]
    assert root.description == template_v1_payload["description"]


def test_deactivate_rejects_a_stale_second_editor(admin_client, template_v1_payload):
    """A stale published DTO must not repeat a lifecycle transition."""
    created = create_template(admin_client, template_v1_payload)
    published = publish_template(admin_client, created["version_id"]).json["data"]

    deactivated = deactivate_template(
        admin_client, created["version_id"], version=published["version"]
    )
    stale = deactivate_template(
        admin_client, created["version_id"], version=published["version"]
    )

    assert deactivated.status_code == 200
    assert deactivated.json["data"]["version"] == published["version"] + 1
    assert_error(stale, 409, "stale_version")


def test_draft_can_be_deleted_without_leaving_a_version(admin_client, template_v1_payload):
    """Draft deletion must remove only disposable work while keeping published rules intact."""
    created = create_template(admin_client, template_v1_payload)

    response = delete_with(
        admin_client,
        f"/api/v1/industry-templates/versions/{created['version_id']}",
        version=created["version"],
    )

    assert response.status_code == 204
    assert response.data == b""
    assert_error(
        admin_client.get(
            f"/api/v1/industry-templates/versions/{created['version_id']}"
        ),
        404,
        "template_version_not_found",
    )


def test_stale_draft_delete_preserves_the_newer_editor_version(
    admin_client, template_v1_payload
):
    """Deleting with an old DTO after another editor saves would destroy newer work."""
    created = create_template(admin_client, template_v1_payload)
    updated = admin_client.patch(
        f"/api/v1/industry-templates/versions/{created['version_id']}",
        json={"version": created["version"], "description": "另一位编辑者的草稿"},
    ).json["data"]

    stale = delete_with(
        admin_client,
        f"/api/v1/industry-templates/versions/{created['version_id']}",
        version=created["version"],
    )
    current = admin_client.get(
        f"/api/v1/industry-templates/versions/{created['version_id']}"
    ).json["data"]

    assert updated["version"] == created["version"] + 1
    assert_error(stale, 409, "stale_version")
    assert current["description"] == "另一位编辑者的草稿"
    assert current["version"] == updated["version"]


@pytest.mark.parametrize("action", ["publish", "deactivate", "delete"])
@pytest.mark.parametrize("payload", [None, {}, {"version": True}, {"version": 0}, {"version": "1"}])
def test_template_lifecycle_actions_require_a_positive_integer_version(
    admin_client, template_v1_payload, db_session, action, payload
):
    """Missing or coercible lifecycle tokens would bypass optimistic concurrency."""
    created = create_template(admin_client, template_v1_payload)
    version_id = created["version_id"]
    if action == "deactivate":
        version = db_session.get(IndustryTemplateVersion, version_id)
        version.status = "published"
        version.template.status = "active"
        db_session.commit()
    url = f"/api/v1/industry-templates/versions/{version_id}"
    if action == "publish":
        response = admin_client.post(f"{url}/publish", json=payload)
    elif action == "deactivate":
        response = admin_client.post(f"{url}/deactivate", json=payload)
    else:
        response = admin_client.client.delete(
            url, headers=admin_client.headers, json=payload
        )

    assert_error(response, 400, "invalid_request")


def test_snapshot_serializer_is_stable_and_contains_dependency_keys(
    admin_client, template_v1_payload, db_session
):
    """Omitting stable keys or source IDs would prevent later project snapshot reuse."""
    created = create_template(admin_client, template_v1_payload)
    assert publish_template(admin_client, created["version_id"]).status_code == 200
    db_session.expire_all()
    snapshot = serialize_template_snapshot(
        session=db_session,
        version_id=created["version_id"],
    )

    assert set(snapshot) == {
        "template_id",
        "template_name",
        "industry_name",
        "description",
        "version_id",
        "version_number",
        "modules",
    }
    assert [module["module_key"] for module in snapshot["modules"]] == [
        "pre_diagnosis",
        "pov",
    ]
    assert set(snapshot["modules"][0]) == {
        "id",
        "module_catalog_id",
        "module_key",
        "name",
        "description",
        "sort_order",
        "tasks",
    }
    tasks = {
        task["task_key"]: task
        for module in snapshot["modules"]
        for task in module["tasks"]
    }
    assert tasks["build_pov"]["dependency_keys"] == ["confirm_business_scope"]
    assert set(tasks["build_pov"]) == {
        "id",
        "task_key",
        "name",
        "description",
        "duration_days",
        "default_assignee_role",
        "sort_order",
        "dependency_keys",
    }


def test_published_snapshot_reader_uses_the_callers_transaction(
    admin_client, template_v1_payload, db_session, monkeypatch
):
    """Opening a second session would split publication validation from snapshot reads."""
    from fde_api.extensions import db
    from fde_api.templates.service import read_published_template_snapshot

    created = create_template(admin_client, template_v1_payload)
    assert publish_template(admin_client, created["version_id"]).status_code == 200

    def must_not_open_another_session():
        raise AssertionError("snapshot reader opened a second session")

    monkeypatch.setattr(db, "session", must_not_open_another_session)

    snapshot = read_published_template_snapshot(
        session=db_session,
        version_id=created["version_id"],
    )

    assert snapshot["version_id"] == created["version_id"]
    assert snapshot["version_number"] == 1


def test_template_detail_builds_visibility_and_dto_in_one_read_session(
    admin_client, template_v1_payload, monkeypatch
):
    """Separate status and serialization sessions permit a deactivate visibility race."""
    from fde_api.extensions import db

    created = create_template(admin_client, template_v1_payload)
    assert publish_template(admin_client, created["version_id"]).status_code == 200
    real_session = db.session
    opened_sessions = 0

    def counted_session():
        nonlocal opened_sessions
        opened_sessions += 1
        return real_session()

    monkeypatch.setattr(db, "session", counted_session)

    response = admin_client.get(
        f"/api/v1/industry-templates/versions/{created['version_id']}"
    )

    assert response.status_code == 200
    assert opened_sessions == 2  # authentication plus one atomic detail read
