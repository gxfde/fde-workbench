import pytest
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from fde_api.auth.models import User
from fde_api.auth.passwords import hash_password
from fde_api.auth.tokens import issue_access_token
from fde_api.research.models import TemplateResearchField, TemplateResearchForm
from fde_api.workbench.models import IndustryTemplateVersion, ModuleCatalog, OperationEvent


def valid_form_payload():
    return {
        "form_key": "role_interview",
        "name": "Role interview",
        "description": "",
        "subject_type": "role",
        "sort_order": 10,
        "sections": [
            {
                "section_key": "context",
                "name": "Context",
                "description": "",
                "sort_order": 10,
                "fields": [
                    {
                        "field_key": "current_state",
                        "name": "Current state",
                        "help_text": "",
                        "type": "single_choice",
                        "is_required": True,
                        "options": {"choices": ["yes", "no"]},
                        "sort_order": 10,
                    },
                    {
                        "field_key": "notes",
                        "name": "Notes",
                        "help_text": "",
                        "type": "long_text",
                        "is_required": False,
                        "options": {},
                        "sort_order": 20,
                        "condition": {
                            "field_key": "current_state",
                            "operator": "equals",
                            "value": "yes",
                        },
                    },
                ],
            }
        ],
    }


def template_payload():
    return {
        "name": "Manufacturing template",
        "industry_name": "Manufacturing",
        "description": "",
        "modules": [
            {
                "module_key": "diagnosis",
                "name": "Diagnosis",
                "description": "",
                "sort_order": 10,
                "tasks": [
                    {
                        "task_key": "collect_info",
                        "name": "Collect info",
                        "description": "",
                        "duration_days": 1,
                        "default_assignee_role": "project_lead",
                        "sort_order": 10,
                        "dependency_keys": [],
                    }
                ],
            }
        ],
    }


@pytest.fixture
def admin_client(client, db_session, settings):
    user = User(
        username="admin.research",
        display_name="Admin",
        role="admin",
        password_hash=hash_password("InitialPass!234"),
        must_change_password=False,
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()
    return client, {"Authorization": f"Bearer {issue_access_token(user, settings)}"}


@pytest.fixture
def project_lead_client(client, db_session, settings):
    user = User(
        username="lead.research",
        display_name="Lead",
        role="project_lead",
        password_hash=hash_password("InitialPass!234"),
        must_change_password=False,
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()
    return client, {"Authorization": f"Bearer {issue_access_token(user, settings)}"}


@pytest.fixture
def draft_template(admin_client, db_session):
    db_session.add(
        ModuleCatalog(
            module_key="diagnosis",
            name="Diagnosis",
            description="",
            sort_order=10,
            is_active=True,
        )
    )
    db_session.commit()
    client, headers = admin_client
    response = client.post("/api/v1/industry-templates", json=template_payload(), headers=headers)
    assert response.status_code == 201
    return response.json["data"]


def research_url(template):
    return f"/api/v1/templates/{template['template_id']}/versions/{template['version_id']}/research-forms"


def assert_error(response, status, code):
    assert response.status_code == status
    assert response.json["data"] is None
    assert response.json["error"]["code"] == code


def versioned_form(template, form=None):
    return {"version": template["version"], **(form or valid_form_payload())}


def test_admin_can_create_read_update_and_delete_a_draft_definition(admin_client, draft_template):
    """Removing draft mutation persistence would leave the schema editor unable to save."""
    client, headers = admin_client
    created = client.post(
        research_url(draft_template), json=versioned_form(draft_template), headers=headers
    )

    assert created.status_code == 201
    assert created.json["data"]["version"] == draft_template["version"] + 1
    assert created.json["data"]["forms"][0]["form_key"] == "role_interview"
    assert created.json["data"]["forms"][0]["sections"][0]["fields"][1]["condition"] == {
        "field_key": "current_state",
        "operator": "equals",
        "value": "yes",
    }
    assert client.get(research_url(draft_template), headers=headers).json["data"]["version"] == created.json["data"]["version"]

    replacement = valid_form_payload()
    replacement["name"] = "Updated role interview"
    updated = client.put(
        research_url(draft_template),
        json={"version": created.json["data"]["version"], "forms": [replacement]},
        headers=headers,
    )
    assert updated.status_code == 200
    assert updated.json["data"]["version"] == created.json["data"]["version"] + 1
    assert updated.json["data"]["forms"][0]["name"] == "Updated role interview"

    deleted = client.delete(
        research_url(draft_template),
        json={"version": updated.json["data"]["version"]},
        headers=headers,
    )
    assert deleted.status_code == 200
    assert deleted.json["data"]["version"] == updated.json["data"]["version"] + 1
    assert client.get(research_url(draft_template), headers=headers).json["data"]["forms"] == []


def test_mutations_reject_unknown_keys_and_non_admin_roles(project_lead_client, draft_template):
    """Permissive bodies or project-lead writes would bypass definition governance."""
    client, headers = project_lead_client
    assert_error(client.post(research_url(draft_template), json={**versioned_form(draft_template), "script": "x"}, headers=headers), 403, "forbidden")


def test_mutations_reject_unknown_payload_keys(admin_client, draft_template):
    """Ignoring unknown payload keys would silently accept unsupported executable config."""
    client, headers = admin_client
    assert_error(client.post(research_url(draft_template), json={**versioned_form(draft_template), "script": "x"}, headers=headers), 400, "invalid_request")


def test_module_scoped_forms_reject_unknown_or_cross_template_module_keys(admin_client, draft_template):
    """A typo or foreign module key must fail at create and replace boundaries."""
    client, headers = admin_client
    invalid = valid_form_payload() | {"module_key": "foreign_module"}
    assert_error(client.post(research_url(draft_template), json=versioned_form(draft_template, invalid), headers=headers), 400, "invalid_research_definition")
    created = client.post(research_url(draft_template), json=versioned_form(draft_template), headers=headers)
    assert created.status_code == 201
    invalid_definition = created.json["data"]
    invalid_definition["forms"][0]["module_key"] = "foreign_module"
    assert_error(client.put(research_url(draft_template), json=invalid_definition, headers=headers), 400, "invalid_research_definition")


def test_put_rejects_invalid_choice_default_and_duplicate_table_column_key(
    admin_client, draft_template
):
    """The mutation boundary must reject definitions the renderer cannot safely execute."""
    client, headers = admin_client
    definition = valid_form_payload()
    definition["sections"][0]["fields"][0]["options"]["default_value"] = "maybe"
    definition["sections"][0]["fields"].append(
        {
            "field_key": "line_items",
            "name": "Line items",
            "help_text": "",
            "type": "table",
            "is_required": False,
            "options": {
                "columns": [
                    {"key": "item", "name": "Item"},
                    {"key": "item", "name": "Duplicate"},
                ]
            },
            "sort_order": 30,
        }
    )

    response = client.put(
        research_url(draft_template),
        json={"version": draft_template["version"], "forms": [definition]},
        headers=headers,
    )

    assert_error(response, 400, "invalid_research_definition")
    assert response.json["error"]["details"] == {
        "issues": [
            {
                "code": "invalid_choice_default",
                "path": "forms[0].sections[0].fields[0].options.default_value",
            },
            {
                "code": "duplicate_table_column_key",
                "path": "forms[0].sections[0].fields[2].options.columns[1].key",
            },
        ]
    }


def test_put_rejects_a_string_condition_for_an_integer_controller(
    admin_client, draft_template
):
    """The API must not persist an integer comparison that can never match an integer answer."""
    client, headers = admin_client
    definition = valid_form_payload()
    definition["sections"][0]["fields"][0]["type"] = "integer"
    definition["sections"][0]["fields"][0]["options"] = {}
    definition["sections"][0]["fields"][1]["condition"] = {
        "field_key": "current_state",
        "operator": "equals",
        "value": "1",
    }

    response = client.put(
        research_url(draft_template),
        json={"version": draft_template["version"], "forms": [definition]},
        headers=headers,
    )

    assert_error(response, 400, "invalid_research_definition")
    assert response.json["error"]["details"] == {
        "issues": [
            {
                "code": "invalid_condition_value",
                "path": "forms[0].sections[0].fields[1].condition.value",
            }
        ]
    }


def test_put_rejects_a_numeric_json_condition_for_a_decimal_controller(
    admin_client, draft_template
):
    """Decimal conditions must use the same precision-preserving string as stored answers."""
    client, headers = admin_client
    definition = valid_form_payload()
    definition["sections"][0]["fields"][0]["type"] = "decimal"
    definition["sections"][0]["fields"][0]["options"] = {}
    definition["sections"][0]["fields"][1]["condition"] = {
        "field_key": "current_state",
        "operator": "equals",
        "value": 1.25,
    }

    response = client.put(
        research_url(draft_template),
        json={"version": draft_template["version"], "forms": [definition]},
        headers=headers,
    )

    assert_error(response, 400, "invalid_research_definition")
    assert response.json["error"]["details"] == {
        "issues": [
            {
                "code": "invalid_condition_value",
                "path": "forms[0].sections[0].fields[1].condition.value",
            }
        ]
    }


@pytest.mark.parametrize("value", ["1e100000", "not-a-decimal"])
def test_put_maps_bounded_or_malformed_decimal_conditions_to_a_definition_issue(
    admin_client, draft_template, value
):
    """Decimal parser and size failures must stay inside the public 400 envelope."""
    client, headers = admin_client
    definition = valid_form_payload()
    definition["sections"][0]["fields"][0]["type"] = "decimal"
    definition["sections"][0]["fields"][0]["options"] = {}
    definition["sections"][0]["fields"][1]["condition"] = {
        "field_key": "current_state",
        "operator": "equals",
        "value": value,
    }

    response = client.put(
        research_url(draft_template),
        json={"version": draft_template["version"], "forms": [definition]},
        headers=headers,
    )

    assert_error(response, 400, "invalid_research_definition")
    assert response.json["error"]["details"] == {
        "issues": [
            {
                "code": "invalid_condition_value",
                "path": "forms[0].sections[0].fields[1].condition.value",
            }
        ]
    }


@pytest.mark.parametrize("value", ["\ufeffready\ufeff", "\u0085ready\u0085"])
def test_text_condition_non_ascii_edge_content_round_trips_through_get_and_put(
    admin_client, draft_template, value
):
    """A legal text condition snapshot remains legal under the explicit ASCII trim contract."""
    client, headers = admin_client
    definition = valid_form_payload()
    definition["sections"][0]["fields"][0]["type"] = "short_text"
    definition["sections"][0]["fields"][0]["options"] = {}
    definition["sections"][0]["fields"][1]["condition"] = {
        "field_key": "current_state",
        "operator": "equals",
        "value": value,
    }
    created = client.post(
        research_url(draft_template),
        json=versioned_form(draft_template, definition),
        headers=headers,
    )
    assert created.status_code == 201
    snapshot = client.get(research_url(draft_template), headers=headers).json["data"]

    replaced = client.put(research_url(draft_template), json=snapshot, headers=headers)

    assert replaced.status_code == 200


def test_get_snapshot_with_valid_typed_conditions_can_be_put_without_changes(
    admin_client, draft_template
):
    """A legal serializer response must remain legal at the same API mutation boundary."""
    client, headers = admin_client
    definition = valid_form_payload()
    definition["sections"][0]["fields"][0]["type"] = "decimal"
    definition["sections"][0]["fields"][0]["options"] = {}
    definition["sections"][0]["fields"][1]["condition"] = {
        "field_key": "current_state",
        "operator": "equals",
        "value": "1.25",
    }
    created = client.post(
        research_url(draft_template),
        json=versioned_form(draft_template, definition),
        headers=headers,
    )
    assert created.status_code == 201
    snapshot = client.get(research_url(draft_template), headers=headers).json["data"]

    replaced = client.put(research_url(draft_template), json=snapshot, headers=headers)

    assert replaced.status_code == 200


def test_publish_rejects_a_persisted_form_module_key_outside_the_template(
    admin_client, draft_template, db_session
):
    """Skipping publish-time ownership validation would publish a corrupt saved form."""
    client, headers = admin_client
    created = client.post(
        research_url(draft_template),
        json=versioned_form(draft_template),
        headers=headers,
    )
    assert created.status_code == 201

    persisted_form = db_session.scalar(
        select(TemplateResearchForm).where(
            TemplateResearchForm.template_version_id == draft_template["version_id"]
        )
    )
    assert persisted_form is not None
    persisted_form.module_key = "foreign_module"
    db_session.commit()

    published = client.post(
        f"/api/v1/industry-templates/versions/{draft_template['version_id']}/publish",
        json={"version": created.json["data"]["version"]},
        headers=headers,
    )
    assert_error(published, 400, "invalid_research_definition")
    assert published.json["error"]["details"] == {
        "issues": [
            {
                "code": "unknown_form_module_key",
                "path": "forms[0].module_key",
            }
        ]
    }
    db_session.expire_all()
    assert db_session.get(
        IndustryTemplateVersion, draft_template["version_id"]
    ).status == "draft"


def test_read_rejects_a_version_owned_by_a_different_template(admin_client, draft_template):
    """Ignoring the template segment would expose a version through any template URL."""
    client, headers = admin_client
    second = client.post("/api/v1/industry-templates", json=template_payload(), headers=headers)
    assert second.status_code == 201

    response = client.get(
        f"/api/v1/templates/{draft_template['template_id']}/versions/{second.json['data']['version_id']}/research-forms",
        headers=headers,
    )

    assert_error(response, 404, "template_version_not_found")


def test_project_lead_cannot_read_a_draft_definition(project_lead_client, draft_template):
    """Returning drafts to project leads would expose unapproved industry configuration."""
    client, headers = project_lead_client

    response = client.get(research_url(draft_template), headers=headers)

    assert_error(response, 403, "forbidden")


def test_existing_stable_key_cannot_be_changed_by_draft_replacement(admin_client, draft_template):
    """Allowing replacement to rename a key would orphan saved answers and conditions."""
    client, headers = admin_client
    created = client.post(
        research_url(draft_template), json=versioned_form(draft_template), headers=headers
    )
    assert created.status_code == 201
    replacement = created.json["data"]
    replacement["forms"][0]["form_key"] = "renamed_interview"

    assert_error(client.put(research_url(draft_template), json=replacement, headers=headers), 400, "stable_key_immutable")


def test_published_research_definition_is_immutable(admin_client, draft_template):
    """Allowing an added form after publication would rewrite the published contract."""
    client, headers = admin_client
    created = client.post(
        research_url(draft_template), json=versioned_form(draft_template), headers=headers
    )
    assert created.status_code == 201
    published = client.post(
        f"/api/v1/industry-templates/versions/{draft_template['version_id']}/publish",
        json={"version": created.json["data"]["version"]},
        headers=headers,
    )
    assert published.status_code == 200

    response = client.post(
        research_url(draft_template),
        json={"version": published.json["data"]["version"], **valid_form_payload()},
        headers=headers,
    )

    assert_error(response, 409, "template_version_immutable")


def test_copying_a_published_template_copies_its_research_definition(admin_client, draft_template):
    """Dropping research children during copy would make the next draft lose its schema."""
    client, headers = admin_client
    created = client.post(
        research_url(draft_template), json=versioned_form(draft_template), headers=headers
    )
    assert created.status_code == 201
    assert client.post(
        f"/api/v1/industry-templates/versions/{draft_template['version_id']}/publish",
        json={"version": created.json["data"]["version"]},
        headers=headers,
    ).status_code == 200

    copied = client.post(
        f"/api/v1/industry-templates/{draft_template['template_id']}/versions",
        json={},
        headers=headers,
    )

    assert copied.status_code == 201
    copied_definition = client.get(research_url(copied.json["data"]), headers=headers)
    assert copied_definition.json["data"]["forms"][0]["form_key"] == "role_interview"
    assert copied_definition.json["data"]["forms"][0]["id"] != client.get(
        research_url(draft_template), headers=headers
    ).json["data"]["forms"][0]["id"]


def test_copy_uses_stable_keys_for_equal_research_sort_orders(admin_client, draft_template):
    """Random database IDs must not choose the display order of copied peer forms."""
    client, headers = admin_client
    current = dict(draft_template)
    for form_key in ["zulu", "yankee", "xray", "whiskey", "victor"]:
        form = valid_form_payload()
        form["form_key"] = form_key
        form["sort_order"] = 10
        created = client.post(research_url(draft_template), json=versioned_form(current, form), headers=headers)
        assert created.status_code == 201
        current["version"] = created.json["data"]["version"]
    assert client.post(
        f"/api/v1/industry-templates/versions/{draft_template['version_id']}/publish",
        json={"version": current["version"]},
        headers=headers,
    ).status_code == 200
    copied = client.post(
        f"/api/v1/industry-templates/{draft_template['template_id']}/versions",
        json={},
        headers=headers,
    )

    forms = client.get(research_url(copied.json["data"]), headers=headers).json["data"]["forms"]

    assert [form["form_key"] for form in forms] == ["victor", "whiskey", "xray", "yankee", "zulu"]


def test_invalid_research_definition_rolls_back_template_publication(admin_client, draft_template, db_session):
    """Separating validation from publish would record an event for an invalid definition."""
    client, headers = admin_client
    created = client.post(
        research_url(draft_template), json=versioned_form(draft_template), headers=headers
    )
    assert created.status_code == 201
    conditional_field = db_session.scalar(
        select(TemplateResearchField).where(TemplateResearchField.field_key == "notes")
    )
    assert conditional_field is not None
    conditional_field.options_json = {
        "options": {},
        "condition": {"field_key": "missing", "operator": "equals", "value": "yes"},
    }
    db_session.commit()

    response = client.post(
        f"/api/v1/industry-templates/versions/{draft_template['version_id']}/publish",
        json={"version": created.json["data"]["version"]},
        headers=headers,
    )
    db_session.expire_all()

    assert_error(response, 400, "invalid_research_definition")
    assert response.json["error"]["details"] == {"issues": [
        {
            "code": "unknown_condition_field",
            "path": "forms[0].sections[0].fields[1].condition.field_key",
        }
    ]}
    version = db_session.get(IndustryTemplateVersion, draft_template["version_id"])
    assert version.status == "draft"
    assert {event.event_type for event in db_session.scalars(
        select(OperationEvent).where(OperationEvent.target_id == version.id)
    )} == {
        "industry_template_version_created",
        "industry_template_research_definition_created",
    }


@pytest.mark.parametrize("invalid_version", [None, 0, -1, True])
def test_mutations_require_a_positive_integer_version(admin_client, draft_template, invalid_version):
    """Removing aggregate preconditions would let a stale editor overwrite a definition."""
    client, headers = admin_client
    payload = valid_form_payload()
    if invalid_version is not None:
        payload["version"] = invalid_version

    assert_error(
        client.post(research_url(draft_template), json=payload, headers=headers),
        400,
        "invalid_request",
    )
    assert_error(
        client.put(
            research_url(draft_template),
            json={"version": invalid_version, "forms": []},
            headers=headers,
        ),
        400,
        "invalid_request",
    )
    assert_error(
        client.delete(
            research_url(draft_template),
            json={"version": invalid_version},
            headers=headers,
        ),
        400,
        "invalid_request",
    )


def test_stale_research_definition_write_does_not_overwrite_first_editor(admin_client, draft_template):
    """Comparing after mutation would let a stale request replace the first editor's form."""
    client, headers = admin_client
    first = client.post(research_url(draft_template), json=versioned_form(draft_template), headers=headers)
    second_payload = valid_form_payload()
    second_payload["form_key"] = "process_interview"
    second = client.post(
        research_url(draft_template),
        json={"version": draft_template["version"], **second_payload},
        headers=headers,
    )

    assert first.status_code == 201
    assert_error(second, 409, "stale_version")
    forms = client.get(research_url(draft_template), headers=headers).json["data"]["forms"]
    assert [form["form_key"] for form in forms] == ["role_interview"]


def test_stale_delete_leaves_the_current_definition_intact(admin_client, draft_template):
    """A delete without the locked aggregate version would erase a newer definition."""
    client, headers = admin_client
    created = client.post(research_url(draft_template), json=versioned_form(draft_template), headers=headers)
    deleted = client.delete(
        research_url(draft_template),
        json={"version": draft_template["version"]},
        headers=headers,
    )

    assert created.status_code == 201
    assert_error(deleted, 409, "stale_version")
    assert client.get(research_url(draft_template), headers=headers).json["data"]["forms"][0]["form_key"] == "role_interview"


def test_replace_can_add_and_remove_nested_fields_but_cannot_rename_an_id(admin_client, draft_template):
    """Set equality blocks normal draft editing, while changing an existing ID's key breaks history."""
    client, headers = admin_client
    created = client.post(research_url(draft_template), json=versioned_form(draft_template), headers=headers)
    assert created.status_code == 201
    replacement = created.json["data"]
    replacement["forms"][0]["sections"][0]["fields"] = [
        replacement["forms"][0]["sections"][0]["fields"][0],
        {
            "field_key": "future_state",
            "name": "Future state",
            "help_text": "",
            "type": "short_text",
            "is_required": False,
            "options": {},
            "sort_order": 30,
        },
    ]
    replacement["forms"][0]["sections"].append(
        {
            "section_key": "outcomes",
            "name": "Outcomes",
            "description": "",
            "sort_order": 20,
            "fields": [],
        }
    )
    updated = client.put(research_url(draft_template), json=replacement, headers=headers)
    assert updated.status_code == 200
    assert [field["field_key"] for field in updated.json["data"]["forms"][0]["sections"][0]["fields"]] == ["current_state", "future_state"]
    assert [section["section_key"] for section in updated.json["data"]["forms"][0]["sections"]] == ["context", "outcomes"]

    invalid = updated.json["data"]
    invalid["forms"][0]["name"] = "Should roll back"
    invalid["forms"][0]["sections"][0]["fields"][0]["field_key"] = "renamed_state"
    rejected = client.put(research_url(draft_template), json=invalid, headers=headers)

    assert_error(rejected, 400, "stable_key_immutable")
    persisted = client.get(research_url(draft_template), headers=headers).json["data"]
    assert persisted["forms"][0]["name"] == "Role interview"
    assert [field["field_key"] for field in persisted["forms"][0]["sections"][0]["fields"]] == ["current_state", "future_state"]


def test_definition_mutations_append_events_and_roll_back_with_event_failure(admin_client, draft_template, db_session, monkeypatch):
    """Writing an event outside the definition transaction would leave audit and state divergent."""
    client, headers = admin_client
    created = client.post(research_url(draft_template), json=versioned_form(draft_template), headers=headers)
    assert created.status_code == 201
    updated = client.put(research_url(draft_template), json=created.json["data"], headers=headers)
    assert updated.status_code == 200
    deleted = client.delete(research_url(draft_template), json={"version": updated.json["data"]["version"]}, headers=headers)
    assert deleted.status_code == 200
    events = list(db_session.scalars(select(OperationEvent).where(OperationEvent.target_id == draft_template["version_id"])))
    assert {event.event_type for event in events} == {
        "industry_template_version_created",
        "industry_template_research_definition_created",
        "industry_template_research_definition_replaced",
        "industry_template_research_definition_deleted",
    }

    from fde_api.projects.events import record_event as real_record_event

    def record_then_fail(*args, **kwargs):
        real_record_event(*args, **kwargs)
        raise SQLAlchemyError("forced research event failure")

    monkeypatch.setattr("fde_api.projects.events.record_event", record_then_fail)
    failed = client.post(research_url(draft_template), json={"version": deleted.json["data"]["version"], **valid_form_payload()}, headers=headers)
    assert_error(failed, 503, "template_research_update_failed")
    db_session.expire_all()
    assert db_session.get(IndustryTemplateVersion, draft_template["version_id"]).version == deleted.json["data"]["version"]
    assert list(db_session.scalars(select(OperationEvent).where(OperationEvent.target_id == draft_template["version_id"]))) == events
