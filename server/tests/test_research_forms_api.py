from dataclasses import dataclass
from datetime import date
from copy import deepcopy
from time import monotonic
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.orm.attributes import flag_modified

from fde_api.auth.models import User
from fde_api.auth.passwords import hash_password
from fde_api.auth.tokens import issue_access_token
from fde_api.extensions import db
from fde_api.research.models import (
    ProjectResearchAnswer,
    ProjectResearchForm,
    ProjectResearchExport,
    ProjectResearchFormRevision,
    ProjectResearchSubject,
    TemplateResearchField,
    TemplateResearchForm,
    TemplateResearchSection,
)
from fde_api.jobs.models import OutboxEvent
from fde_api.research.answers import validate_answer
from fde_api.research.form_service import _visible_field_keys, initialize_subject_forms
from fde_api.projects import events as project_events
from fde_api.workbench.models import (
    IndustryTemplate,
    IndustryTemplateVersion,
    OperationEvent,
    Project,
    ProjectMember,
)
from mysql_lock_race import (
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
            username=f"forms.{role}.{uuid4().hex}",
            display_name=role,
            role=role,
            password_hash=hash_password("InitialPass!234"),
            must_change_password=False,
            is_active=True,
        )
        db_session.add(user)
        db_session.commit()
        return AuthorizedClient(client, user, {"Authorization": f"Bearer {issue_access_token(user, settings)}"})

    return create


@pytest.fixture
def form_context(db_session, authorized_client_factory):
    admin = authorized_client_factory("admin")
    engineer = authorized_client_factory("fde_engineer")
    leader = authorized_client_factory("project_lead")
    viewer = authorized_client_factory("viewer")
    template = IndustryTemplate(name=f"Research {uuid4().hex}", industry_name="制造", status="active")
    version = IndustryTemplateVersion(
        template=template,
        name=template.name,
        industry_name=template.industry_name,
        description="",
        version_number=1,
        status="published",
        published_by=admin.user,
    )
    source_form = TemplateResearchForm(
        template_version=version, form_key="role_interview", name="Role interview", subject_type="role"
    )
    section = TemplateResearchSection(form=source_form, section_key="main", name="Main")
    fields = [
        TemplateResearchField(section=section, field_key="mode", name="Mode", field_type="single_choice", is_required=True, options_json={"options": {"choices": ["yes", "no"]}}),
        TemplateResearchField(section=section, field_key="detail", name="Detail", field_type="long_text", is_required=True, options_json={"options": {}, "condition": {"field_key": "mode", "operator": "equals", "value": "yes"}}),
    ]
    db_session.add(version)
    db_session.flush()
    snapshot = {
        "forms": [{
            "id": source_form.id,
            "form_key": "role_interview", "name": "Role interview", "description": "", "subject_type": "role", "sort_order": 0,
            "sections": [{"id": section.id, "section_key": "main", "name": "Main", "description": "", "sort_order": 0,
                "fields": [
                    {"id": fields[0].id, "field_key": "mode", "name": "Mode", "help_text": "", "type": "single_choice", "is_required": True, "options": {"choices": ["yes", "no"]}, "sort_order": 0},
                    {"id": fields[1].id, "field_key": "detail", "name": "Detail", "help_text": "", "type": "long_text", "is_required": True, "options": {}, "sort_order": 1, "condition": {"field_key": "mode", "operator": "equals", "value": "yes"}},
                ]}],
        }]}
    project = Project(
        project_code=f"FDE-FORM-{uuid4().hex[:10]}", name="Research project", enterprise_name="星河制造",
        leader=leader.user, source_template_version=version, template_snapshot={}, research_snapshot=snapshot,
        planned_start_date=date(2026, 8, 22),
    )
    subject = ProjectResearchSubject(project=project, subject_type="role", subject_key="planner", name="Planner")
    form = ProjectResearchForm(project=project, subject=subject, source_template_form=source_form, form_key="role_interview", name="Role interview")
    revision = ProjectResearchFormRevision(
        form=form, revision_number=1, status="draft", definition_snapshot=deepcopy(snapshot["forms"][0])
    )
    form.current_revision = revision
    db_session.add_all([
        ProjectMember(project=project, user=engineer.user, role="member"),
        ProjectMember(project=project, user=viewer.user, role="viewer"),
    ])
    db_session.commit()
    return {"admin": admin, "engineer": engineer, "leader": leader, "viewer": viewer, "project": project, "form": form, "revision": revision}


def _url(context, suffix=""):
    return f"/api/v1/projects/{context['project'].id}/research/forms/{context['form'].id}{suffix}"


def _assert_error(response, status, code):
    assert response.status_code == status, response.get_data(as_text=True)
    assert response.json["data"] is None
    assert response.json["error"]["code"] == code


def test_export_confirmation_queues_one_background_generation(form_context, db_session):
    context = form_context
    saved = context["engineer"].patch(
        _url(context), json={"version": 1, "answers": {"mode": "no"}}
    )
    assert saved.status_code == 200

    first = context["engineer"].post(_url(context, "/export"), json={})
    second = context["engineer"].post(_url(context, "/export"), json={})

    assert first.status_code == 202, first.get_data(as_text=True)
    assert second.status_code == 200, second.get_data(as_text=True)
    assert first.json["data"]["status"] == "queued"
    assert second.json["data"]["id"] == first.json["data"]["id"]
    library = context["engineer"].get(
        f'/api/v1/projects/{context["project"].id}/files'
    )
    assert library.status_code == 200
    generated_card = next(
        item
        for item in library.json["data"]["items"]
        if item["generation_export_id"] == first.json["data"]["id"]
    )
    assert generated_card["generation_status"] == "queued"
    assert generated_card["current_version"] is None
    export = db_session.get(ProjectResearchExport, first.json["data"]["id"])
    assert export is not None
    events = db_session.scalars(
        select(OutboxEvent).where(
            OutboxEvent.topic == "research.export",
            OutboxEvent.aggregate_id == export.id,
        )
    ).all()
    assert len(events) == 1


def test_patch_is_whole_form_optimistic_and_does_not_partially_update(form_context):
    """Skipping prevalidation would save valid fields even when the same whole-form request is invalid."""
    engineer = form_context["engineer"]
    revision = form_context["revision"]
    rejected = engineer.patch(_url(form_context), json={"version": revision.version, "answers": {"mode": "yes", "unknown": "x"}})
    _assert_error(rejected, 422, "invalid_research_answer")
    saved = engineer.patch(_url(form_context), json={"version": revision.version, "answers": {"mode": "yes"}})
    assert saved.status_code == 200
    assert saved.json["data"]["current_revision"]["version"] == 2
    stale = engineer.patch(_url(form_context), json={"version": 1, "answers": {"mode": "no"}})
    _assert_error(stale, 409, "stale_version")


def test_patch_null_explicitly_deletes_a_persisted_answer_and_clears_return_metadata(form_context, db_session):
    """Ignoring an explicit null would leave a cleared desktop number persisted with its old value."""
    engineer = form_context["engineer"]
    saved = engineer.patch(_url(form_context), json={"version": 1, "answers": {"mode": "no"}})
    assert saved.status_code == 200
    returned = form_context["leader"].post(
        _url(form_context, "/reject"),
        json={"version": 2, "review_comment": "Clear the obsolete selection"},
    )
    assert returned.status_code == 200

    cleared = engineer.patch(_url(form_context), json={"version": 3, "answers": {"mode": None}})

    assert cleared.status_code == 200
    revision = cleared.json["data"]["current_revision"]
    assert revision["version"] == 4
    assert revision["answers"] == []
    assert revision["returned_by_user_id"] is None
    assert revision["returned_at"] is None
    assert revision["return_comment"] is None
    db_session.expire_all()
    patch_events = db_session.scalars(
        select(OperationEvent).where(
            OperationEvent.project_id == form_context["project"].id,
            OperationEvent.event_type == "project_research_form_patched",
        )
    ).all()
    assert len(patch_events) == 2


def test_patch_rejects_integer_answers_outside_json_safe_range_with_422(form_context, db_session):
    """An unsafe JSON integer must fail before it can be serialized back with lost precision."""
    revision = form_context["revision"]
    detail = revision.definition_snapshot["sections"][0]["fields"][1]
    detail["type"] = "integer"
    detail["options"] = {}
    flag_modified(revision, "definition_snapshot")
    db_session.commit()

    accepted = form_context["engineer"].patch(
        _url(form_context),
        json={"version": 1, "answers": {"mode": "yes", "detail": 9_007_199_254_740_991}},
    )
    assert accepted.status_code == 200
    rejected = form_context["engineer"].patch(
        _url(form_context),
        json={"version": 2, "answers": {"detail": 9_007_199_254_740_992}},
    )

    _assert_error(rejected, 422, "invalid_research_answer")


def test_patch_rejects_an_extreme_decimal_answer_with_a_bounded_422(form_context):
    """A short extreme exponent must not expand or enter the persisted answer record."""
    revision = form_context["revision"]
    detail = revision.definition_snapshot["sections"][0]["fields"][1]
    detail["type"] = "decimal"
    detail["options"] = {}

    started = monotonic()
    response = form_context["engineer"].patch(
        _url(form_context),
        json={"version": revision.version, "answers": {"detail": "1e100000"}},
    )

    _assert_error(response, 422, "invalid_research_answer")
    assert monotonic() - started < 0.5


@pytest.mark.mysql_observer
def test_concurrent_form_patches_allow_one_current_revision_version(
    app, form_context, db_session
):
    """The loser must wait on the winner's project row and never overwrite it."""
    context = form_context
    before = context["revision"].version
    answer_details = ("winner candidate one", "winner candidate two")
    diagnostics = RaceDiagnostics()

    with app.app_context():
        with open_mysql_observer_or_skip(db.engine) as observer:
            race = run_mysql_lock_race(
                observer=observer,
                settings_payload=app.config["SETTINGS"].model_dump(mode="json"),
                request_url=_url(context),
                request_headers=dict(context["engineer"].headers),
                request_payloads=tuple(
                    {
                        "version": before,
                        "answers": {"mode": "yes", "detail": detail},
                    }
                    for detail in answer_details
                ),
                request_method="PATCH",
                lock_target="form_project",
                diagnostics=diagnostics,
            )
            state = tracked_mysql_state(observer, diagnostics.tracked_connection_ids)

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

    assert sorted(status for status, _payload in race.responses) == [200, 409]
    loser_payload = next(payload for status, payload in race.responses if status == 409)
    assert loser_payload["error"]["code"] == "stale_version"
    winner_index = next(
        index for index, (status, _payload) in enumerate(race.responses) if status == 200
    )

    db_session.expire_all()
    revision = db_session.get(ProjectResearchFormRevision, context["revision"].id)
    assert revision.version == before + 1
    assert {answer.field_key: answer.value_json for answer in revision.answers} == {
        "mode": "yes",
        "detail": answer_details[winner_index],
    }
    events = db_session.scalars(
        select(OperationEvent).where(
            OperationEvent.project_id == context["project"].id,
            OperationEvent.target_type == "project_research_form",
            OperationEvent.target_id == context["form"].id,
            OperationEvent.event_type == "project_research_form_patched",
        )
    ).all()
    assert len(events) == 1
    assert state.active_transactions == ()
    assert state.lock_wait_count == 0


def test_confirmed_form_becomes_editable_on_write_without_mutating_history(form_context, db_session):
    """Legacy confirmed forms transparently get a working revision when edited."""
    engineer = form_context["engineer"]
    leader = form_context["leader"]
    saved = engineer.patch(_url(form_context), json={"version": 1, "answers": {"mode": "no"}})
    assert saved.status_code == 200
    confirmed = leader.post(_url(form_context, "/confirm"), json={"version": 2})
    assert confirmed.status_code == 200
    assert confirmed.json["data"]["current_revision"]["status"] == "confirmed"
    edited = engineer.patch(_url(form_context), json={"version": confirmed.json["data"]["current_revision"]["version"], "answers": {"mode": "yes"}})
    assert edited.status_code == 200
    current = edited.json["data"]["current_revision"]
    assert current["revision_number"] == 2
    assert current["version"] == 2
    assert current["parent_revision_id"] == confirmed.json["data"]["current_revision"]["id"]
    assert current["answers"] == [{"field_key": "mode", "value": "yes"}]
    db_session.expire_all()
    parent = db_session.get(ProjectResearchFormRevision, confirmed.json["data"]["current_revision"]["id"])
    assert parent.status == "confirmed"
    child = db_session.get(ProjectResearchFormRevision, current["id"])
    assert child.definition_snapshot == parent.definition_snapshot


def test_confirm_requires_visible_required_fields_and_form_permissions(form_context):
    """Relaxing required checks or permissions would allow incomplete or viewer-confirmed research."""
    viewer = form_context["viewer"]
    engineer = form_context["engineer"]
    leader = form_context["leader"]
    _assert_error(viewer.patch(_url(form_context), json={"version": 1, "answers": {"mode": "no"}}), 403, "forbidden")
    _assert_error(engineer.post(_url(form_context, "/confirm"), json={"version": 1}), 403, "forbidden")
    _assert_error(leader.post(_url(form_context, "/confirm"), json={"version": 1}), 422, "research_required_fields_missing")
    saved = engineer.patch(_url(form_context), json={"version": 1, "answers": {"mode": "yes", "detail": "Need one source of truth"}})
    assert saved.status_code == 200
    assert leader.post(_url(form_context, "/confirm"), json={"version": 2}).status_code == 200


def test_confirm_treats_ascii_whitespace_only_structured_rich_text_as_empty(form_context, db_session):
    """Counting an empty rich-text document as answered would let a required field be confirmed blank."""
    revision = form_context["revision"]
    snapshot = deepcopy(revision.definition_snapshot)
    detail = snapshot["sections"][0]["fields"][1]
    detail["type"] = "rich_text"
    detail["options"] = {}
    revision.definition_snapshot = snapshot
    db_session.commit()
    empty_document = {
        "type": "doc",
        "content": [{"type": "paragraph", "content": [{"type": "text", "text": " \t\r\n"}]}],
    }
    saved = form_context["engineer"].patch(
        _url(form_context),
        json={"version": 1, "answers": {"mode": "yes", "detail": empty_document}},
    )
    assert saved.status_code == 200

    response = form_context["leader"].post(_url(form_context, "/confirm"), json={"version": 2})

    _assert_error(response, 422, "research_required_fields_missing")


def test_return_requires_a_lead_comment_and_keeps_the_revision_draft(form_context):
    """Allowing a commentless return would give engineers no actionable review ruling."""
    leader = form_context["leader"]
    engineer = form_context["engineer"]
    _assert_error(leader.post(_url(form_context, "/reject"), json={"version": 1}), 400, "invalid_request")
    _assert_error(engineer.post(_url(form_context, "/reject"), json={"version": 1, "review_comment": "Add evidence"}), 403, "forbidden")
    returned = leader.post(_url(form_context, "/reject"), json={"version": 1, "review_comment": "Add evidence"})
    assert returned.status_code == 200
    revision = returned.json["data"]["current_revision"]
    assert revision["status"] == "draft"
    assert revision["return_comment"] == "Add evidence"


def test_form_detail_and_list_are_scoped_and_events_do_not_expose_answer_bodies(form_context, db_session):
    """Ignoring project scope or recording answer payloads would expose research content across project boundaries."""
    context = form_context
    saved = context["engineer"].patch(_url(context), json={"version": 1, "answers": {"mode": "no"}})
    assert saved.status_code == 200
    listed = context["viewer"].get(f"/api/v1/projects/{context['project'].id}/research/forms")
    assert listed.status_code == 200
    assert listed.json["data"]["items"][0]["id"] == context["form"].id
    hidden = context["admin"].get(f"/api/v1/projects/{uuid4()}/research/forms/{context['form'].id}")
    _assert_error(hidden, 404, "project_not_found")
    db_session.expire_all()
    event = db_session.scalar(select(OperationEvent).where(OperationEvent.event_type == "project_research_form_patched"))
    assert event is not None
    assert "mode" not in event.changes


def test_subject_instance_gets_a_draft_form_with_its_frozen_definition(form_context, db_session):
    """Skipping form-instance creation would leave a newly scoped subject without its required questionnaire."""
    context = form_context
    subject = ProjectResearchSubject(
        project=context["project"], subject_type="role", subject_key="dispatcher", name="Dispatcher"
    )
    db_session.add(subject)
    db_session.flush()
    initialize_subject_forms(db_session, context["project"], subject)
    db_session.commit()
    form = db_session.scalar(select(ProjectResearchForm).where(ProjectResearchForm.subject_id == subject.id))
    assert form is not None
    assert form.current_revision.status == "draft"
    assert form.current_revision.definition_snapshot["form_key"] == "role_interview"


def test_recursive_visibility_hides_downstream_field_when_its_controller_is_hidden():
    """Treating a hidden controller's stored answer as live would reveal a downstream required field."""
    fields = {
        "a": {"field_key": "a"},
        "b": {"field_key": "b", "condition": {"field_key": "a", "operator": "equals", "value": "show"}},
        "c": {"field_key": "c", "condition": {"field_key": "b", "operator": "equals", "value": "old"}},
    }

    assert _visible_field_keys(fields, {"a": "hide", "b": "old"}) == {"a"}


def _form_definition(subject_type: str, **overrides):
    definition = {
        "form_key": "role_self_added",
        "name": "自建调研表",
        "description": "项目内自建",
        "subject_type": subject_type,
        "module_key": None,
        "sort_order": 0,
        "sections": [{
            "section_key": "profile",
            "name": "档案",
            "description": "",
            "sort_order": 0,
            "fields": [{
                "field_key": "summary",
                "name": "总结",
                "help_text": "",
                "type": "long_text",
                "is_required": True,
                "options": {},
                "sort_order": 0,
            }],
        }],
    }
    definition.update(overrides)
    return definition


def test_project_scoped_form_creation_binds_to_a_subject_and_snapshots_definition(form_context, db_session):
    """A project may author a form directly on a subject without a template source."""
    context = form_context
    subject = db_session.scalar(select(ProjectResearchSubject).where(
        ProjectResearchSubject.project_id == context["project"].id
    ))
    assert subject is not None
    response = context["engineer"].post(
        f"/api/v1/projects/{context['project'].id}/research/forms",
        json={"subject_id": subject.id, **_form_definition("role")},
    )

    assert response.status_code == 201, response.get_data(as_text=True)
    data = response.json["data"]
    assert data["subject_id"] == subject.id
    assert data["form_key"] == "role_self_added"
    current = data["current_revision"]
    assert current["status"] == "draft"
    assert current["revision_number"] == 1
    snapshot = data["definition_snapshot"]
    assert snapshot["subject_type"] == "role"
    assert snapshot["sections"][0]["section_key"] == "profile"
    assert all(isinstance(section["id"], str) for section in snapshot["sections"])
    listed = context["viewer"].get(f"/api/v1/projects/{context['project'].id}/research/forms")
    assert any(item["id"] == data["id"] for item in listed.json["data"]["items"])


def test_project_form_creation_rejects_subject_type_mismatch(form_context, db_session):
    """A form authored for a different subject type must not bind to the node."""
    context = form_context
    subject = db_session.scalar(select(ProjectResearchSubject).where(
        ProjectResearchSubject.project_id == context["project"].id
    ))
    response = context["engineer"].post(
        f"/api/v1/projects/{context['project'].id}/research/forms",
        json={"subject_id": subject.id, **_form_definition("department")},
    )

    _assert_error(response, 400, "research_form_subject_type_mismatch")


def test_project_form_creation_rejects_an_invalid_definition(form_context, db_session):
    """Invalid authored definitions must surface the deterministic definition issues."""
    context = form_context
    subject = db_session.scalar(select(ProjectResearchSubject).where(
        ProjectResearchSubject.project_id == context["project"].id
    ))
    definition = _form_definition("role")
    definition["form_key"] = "Not A Valid Key"
    response = context["engineer"].post(
        f"/api/v1/projects/{context['project'].id}/research/forms",
        json={"subject_id": subject.id, **definition},
    )

    _assert_error(response, 400, "invalid_research_definition")


def test_project_form_recreate_conflicts_on_existing_form_key(form_context, db_session):
    """Duplicate form keys on one subject must be rejected as a conflict."""
    context = form_context
    subject = db_session.scalar(select(ProjectResearchSubject).where(
        ProjectResearchSubject.project_id == context["project"].id
    ))
    first = context["engineer"].post(
        f"/api/v1/projects/{context['project'].id}/research/forms",
        json={"subject_id": subject.id, **_form_definition("role")},
    )
    assert first.status_code == 201
    second = context["engineer"].post(
        f"/api/v1/projects/{context['project'].id}/research/forms",
        json={"subject_id": subject.id, **_form_definition("role")},
    )

    _assert_error(second, 409, "research_form_conflict")


def test_project_form_creation_requires_fill_permission(form_context, db_session):
    """Viewers without fill permission must not author project research forms."""
    context = form_context
    subject = db_session.scalar(select(ProjectResearchSubject).where(
        ProjectResearchSubject.project_id == context["project"].id
    ))
    response = context["viewer"].post(
        f"/api/v1/projects/{context['project'].id}/research/forms",
        json={"subject_id": subject.id, **_form_definition("role")},
    )

    _assert_error(response, 403, "forbidden")


def test_decoupled_project_form_answers_do_not_require_a_template_field(form_context, db_session):
    """Self-authored forms store answers without referencing a template field id."""
    context = form_context
    subject = db_session.scalar(select(ProjectResearchSubject).where(
        ProjectResearchSubject.project_id == context["project"].id
    ))
    created = context["engineer"].post(
        f"/api/v1/projects/{context['project'].id}/research/forms",
        json={"subject_id": subject.id, **_form_definition("role")},
    )
    assert created.status_code == 201, created.get_data(as_text=True)
    form_id = created.json["data"]["id"]
    revision = created.json["data"]["current_revision"]

    saved = context["engineer"].patch(
        f"/api/v1/projects/{context['project'].id}/research/forms/{form_id}",
        json={"version": revision["version"], "answers": {"summary": "自建内容"}},
    )

    assert saved.status_code == 200, saved.get_data(as_text=True)
    answers = saved.json["data"]["current_revision"]["answers"]
    assert {"field_key": "summary", "value": "自建内容"} in answers


def test_project_form_structure_can_change_without_losing_matching_answers(form_context, db_session):
    context = form_context
    subject = db_session.scalar(select(ProjectResearchSubject).where(
        ProjectResearchSubject.project_id == context["project"].id
    ))
    created = context["engineer"].post(
        f"/api/v1/projects/{context['project'].id}/research/forms",
        json={"subject_id": subject.id, **_form_definition("role")},
    )
    form_id = created.json["data"]["id"]
    saved = context["engineer"].patch(
        f"/api/v1/projects/{context['project'].id}/research/forms/{form_id}",
        json={"version": 1, "answers": {"summary": "保留的调研内容"}},
    )
    definition = _form_definition("role")
    definition["name"] = "现状调研"
    definition["sections"][0]["fields"].append({
        "field_key": "target", "name": "期望目标", "help_text": "", "type": "long_text",
        "is_required": True, "options": {}, "sort_order": 20,
    })
    updated = context["engineer"].patch(
        f"/api/v1/projects/{context['project'].id}/research/forms/{form_id}/definition",
        json={"version": saved.json["data"]["current_revision"]["version"], **definition},
    )

    assert updated.status_code == 200, updated.get_data(as_text=True)
    data = updated.json["data"]
    assert data["name"] == "现状调研"
    assert data["current_revision"]["answers"] == [{"field_key": "summary", "value": "保留的调研内容"}]
    assert all(
        field["is_required"] is False
        for section in data["definition_snapshot"]["sections"]
        for field in section["fields"]
    )


def test_project_manager_can_delete_a_research_form_and_its_history(form_context, db_session):
    context = form_context
    subject = db_session.scalar(select(ProjectResearchSubject).where(
        ProjectResearchSubject.project_id == context["project"].id
    ))
    created = context["engineer"].post(
        f"/api/v1/projects/{context['project'].id}/research/forms",
        json={"subject_id": subject.id, **_form_definition("role")},
    )
    form = created.json["data"]
    saved = context["engineer"].patch(
        f"/api/v1/projects/{context['project'].id}/research/forms/{form['id']}",
        json={"version": form["current_revision"]["version"], "answers": {"summary": "待删除"}},
    )
    revision_id = saved.json["data"]["current_revision"]["id"]

    denied = context["engineer"].delete(
        f"/api/v1/projects/{context['project'].id}/research/forms/{form['id']}",
        json={"version": form["version"]},
    )
    _assert_error(denied, 403, "forbidden")
    deleted = context["leader"].delete(
        f"/api/v1/projects/{context['project'].id}/research/forms/{form['id']}",
        json={"version": form["version"]},
    )

    assert deleted.status_code == 204, deleted.get_data(as_text=True)
    db_session.expire_all()
    assert db_session.get(ProjectResearchForm, form["id"]) is None
    assert db_session.get(ProjectResearchFormRevision, revision_id) is None


def test_new_opportunity_subject_gets_identification_only_default_form(form_context, db_session):
    """AI opportunities identify needs; delivery design belongs to solutions."""
    context = form_context
    subject = ProjectResearchSubject(
        project=context["project"], subject_type="opportunity", subject_key="copilot", name="Copilot"
    )
    db_session.add(subject)
    db_session.flush()
    initialize_subject_forms(db_session, context["project"], subject)
    db_session.commit()

    form = db_session.scalar(select(ProjectResearchForm).where(ProjectResearchForm.subject_id == subject.id))
    assert form is not None
    snapshot = form.current_revision.definition_snapshot
    assert snapshot["subject_type"] == "opportunity"
    assert [section["section_key"] for section in snapshot["sections"]] == ["discovery"]
    assert [section["name"] for section in snapshot["sections"]] == ["发现"]
    assert len(snapshot["sections"][0]["fields"]) == 6


def _legacy_opportunity_form(context, db_session):
    subject = ProjectResearchSubject(
        project=context["project"], subject_type="opportunity",
        subject_key=f"legacy_{uuid4().hex}", name="既有机会",
    )
    db_session.add(subject)
    db_session.flush()
    form = initialize_subject_forms(db_session, context["project"], subject)[0]
    definition = deepcopy(form.current_revision.definition_snapshot)
    definition["sections"].append({
        "id": str(uuid4()), "section_key": "delivery", "name": "交付说明",
        "description": "旧版交付说明", "sort_order": 1,
        "fields": [{
            "id": str(uuid4()), "field_key": key, "name": name,
            "help_text": "", "type": "long_text", "is_required": True,
            "options": {}, "sort_order": index,
        } for index, (key, name) in enumerate([
            ("delivery_scope", "交付范围"), ("acceptance_criteria", "验收标准"),
            ("custom_delivery", "历史自定义交付内容"),
        ])],
    })
    form.current_revision.definition_snapshot = definition
    db_session.add_all([
        ProjectResearchAnswer(revision=form.current_revision, field_key="delivery_scope", value_json="旧范围，必须保留"),
        ProjectResearchAnswer(revision=form.current_revision, field_key="custom_delivery", value_json="旧自定义内容，必须保留"),
    ])
    db_session.commit()
    return form, deepcopy(definition)


def test_legacy_opportunity_delivery_is_hidden_but_preserved_on_save_and_confirm(form_context, db_session):
    context = form_context
    form, original_definition = _legacy_opportunity_form(context, db_session)
    original_revision_id = form.current_revision_id
    url = f"/api/v1/projects/{context['project'].id}/research/forms/{form.id}"

    listed = context["engineer"].get(url)
    assert listed.status_code == 200
    view = listed.json["data"]
    assert [section["section_key"] for section in view["definition_snapshot"]["sections"]] == ["discovery"]
    assert view["current_revision"]["answers"] == []
    assert set(view["completion"]["missing_required_field_keys"]) == {"pain_points", "business_value"}

    saved = context["engineer"].patch(url, json={
        "version": 1, "answers": {"pain_points": "人工操作耗时", "business_value": "减少重复工作"},
    })
    assert saved.status_code == 200, saved.get_data(as_text=True)
    confirmed = context["leader"].post(url + "/confirm", json={"version": 2})
    assert confirmed.status_code == 200, confirmed.get_data(as_text=True)
    assert "acceptance_criteria" not in confirmed.json["data"]["completion"]["missing_required_field_keys"]

    rejected = context["engineer"].patch(url, json={"version": 3, "answers": {"delivery_scope": None}})
    _assert_error(rejected, 422, "invalid_research_answer")
    db_session.expire_all()
    revision = db_session.get(ProjectResearchFormRevision, original_revision_id)
    assert revision.definition_snapshot == original_definition
    values = {answer.field_key: answer.value_json for answer in revision.answers}
    assert values["delivery_scope"] == "旧范围，必须保留"
    assert values["custom_delivery"] == "旧自定义内容，必须保留"


def test_legacy_delivery_answers_survive_repeated_opportunity_definition_edits(form_context, db_session):
    context = form_context
    form, original_definition = _legacy_opportunity_form(context, db_session)
    original_revision_id = form.current_revision_id
    url = f"/api/v1/projects/{context['project'].id}/research/forms/{form.id}"
    definition = {key: value for key, value in original_definition.items() if key != "id"}
    definition["sections"] = definition["sections"][:1]
    version = 1

    for label in ["识别机会", "机会业务调研"]:
        definition["name"] = label
        updated = context["engineer"].patch(url + "/definition", json={"version": version, **definition})
        assert updated.status_code == 200, updated.get_data(as_text=True)
        version = updated.json["data"]["current_revision"]["version"]
        assert updated.json["data"]["current_revision"]["answers"] == []
        db_session.expire_all()
        current = db_session.get(ProjectResearchForm, form.id).current_revision
        assert {answer.field_key: answer.value_json for answer in current.answers} == {
            "delivery_scope": "旧范围，必须保留", "custom_delivery": "旧自定义内容，必须保留",
        }
    assert db_session.get(ProjectResearchFormRevision, original_revision_id).definition_snapshot == original_definition


def test_new_opportunity_from_legacy_template_omits_delivery_without_mutating_snapshot(form_context, db_session):
    context = form_context
    _, legacy_definition = _legacy_opportunity_form(context, db_session)
    snapshot = deepcopy(context["project"].research_snapshot)
    snapshot["forms"].append(legacy_definition)
    context["project"].research_snapshot = deepcopy(snapshot)
    # Use real template source ids for the new form's nullable source FK.
    legacy_definition["id"] = context["form"].source_template_research_form_id
    context["project"].research_snapshot["forms"][-1]["id"] = legacy_definition["id"]
    flag_modified(context["project"], "research_snapshot")
    subject = ProjectResearchSubject(
        project=context["project"], subject_type="opportunity", subject_key="new_from_legacy", name="新机会",
    )
    db_session.add(subject)
    db_session.flush()
    new_form = initialize_subject_forms(db_session, context["project"], subject)[0]
    db_session.commit()
    assert [section["section_key"] for section in new_form.current_revision.definition_snapshot["sections"]] == ["discovery"]
    assert context["project"].research_snapshot["forms"][-1] == legacy_definition


def test_visibility_matches_canonical_high_precision_decimal_and_trimmed_text_answers():
    """Conditions must compare the exact normalized values that answer persistence stores."""
    decimal_value = "123456789012345678901234567890.1234567890123456789"
    answers = {
        "amount": validate_answer({"type": "decimal", "options": {}}, decimal_value),
        "note": validate_answer({"type": "short_text", "options": {}}, "  ready  "),
    }
    fields = {
        "amount": {"field_key": "amount"},
        "note": {"field_key": "note"},
        "amount_detail": {
            "field_key": "amount_detail",
            "condition": {"field_key": "amount", "operator": "equals", "value": decimal_value},
        },
        "note_detail": {
            "field_key": "note_detail",
            "condition": {"field_key": "note", "operator": "equals", "value": "ready"},
        },
        "note_contains": {
            "field_key": "note_contains",
            "condition": {"field_key": "note", "operator": "contains", "value": "ead"},
        },
    }

    assert _visible_field_keys(fields, answers) == set(fields)


def test_hidden_answer_error_identifies_the_sorted_hidden_field(form_context):
    """A generic hidden-field error leaves clients unable to focus the rejected control."""
    context = form_context
    assert context["engineer"].patch(_url(context), json={"version": 1, "answers": {"mode": "no"}}).status_code == 200
    response = context["engineer"].patch(_url(context), json={"version": 2, "answers": {"detail": "stale"}})
    _assert_error(response, 422, "invalid_research_answer")
    assert response.json["error"]["details"] == {"field_key": "detail", "reason": "invalid_value"}


def test_form_patch_event_failure_rolls_back_answers_and_revision(form_context, db_session, monkeypatch):
    """If event persistence fails, a saved answer/version would leave the audit trail inconsistent."""
    context = form_context
    before = context["revision"].version

    def fail_event(*_args, **_kwargs):
        raise RuntimeError("event store unavailable")

    monkeypatch.setattr(project_events, "record_event", fail_event)
    response = context["engineer"].patch(_url(context), json={"version": before, "answers": {"mode": "no"}})
    _assert_error(response, 503, "research_form_mutation_failed")
    db_session.expire_all()
    revision = db_session.get(ProjectResearchFormRevision, context["revision"].id)
    assert revision.version == before
    assert revision.status == "draft"
    assert revision.answers == []
    assert revision.return_comment is None


def test_opportunity_subject_api_returns_identification_form(form_context, db_session):
    """A new opportunity exposes identification, not delivery design fields."""
    context = form_context
    project = context["project"]
    project_version = project.version
    created = context["engineer"].post(
        f"/api/v1/projects/{project.id}/research/subjects",
        json={
            "subject_type": "opportunity",
            "subject_key": "copilot",
            "name": "Copilot 机会",
            "version": project_version,
        },
    )
    assert created.status_code == 201, created.get_data(as_text=True)
    subject_id = created.json["data"]["id"]

    listed = context["engineer"].get(
        f"/api/v1/projects/{project.id}/research/forms"
    )
    assert listed.status_code == 200, listed.get_data(as_text=True)
    opportunity_forms = [
        item for item in listed.json["data"]["items"] if item["subject_id"] == subject_id
    ]
    assert len(opportunity_forms) == 1
    snapshot = opportunity_forms[0]["definition_snapshot"]
    assert snapshot["subject_type"] == "opportunity"
    assert [section["name"] for section in snapshot["sections"]] == ["发现"]
    assert [section["section_key"] for section in snapshot["sections"]] == ["discovery"]
    # Every field must carry the ids the renderer validates against.
    assert all(section["id"] and all(field["id"] for field in section["fields"]) for section in snapshot["sections"])
