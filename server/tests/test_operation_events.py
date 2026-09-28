import json
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from uuid import UUID

import pytest
from sqlalchemy import select

from fde_api.auth.models import User
from fde_api.auth.passwords import hash_password
from fde_api.projects.events import record_event
from fde_api.workbench.models import IndustryTemplate, IndustryTemplateVersion, Project, ProjectTask

class AuditState(Enum):
    READY = "ready"


class UnsafeObject:
    def __repr__(self) -> str:
        return "UnsafeObject(access_token=must-not-persist)"


def _user() -> User:
    return User(
        username="event.actor",
        display_name="事件操作人",
        role="admin",
        password_hash=hash_password("InitialPass!234"),
        must_change_password=False,
        is_active=True,
    )


def _project(actor: User) -> Project:
    template = IndustryTemplate(
        template_key="event-template",
        name="事件模板",
        industry_name="制造业",
    )
    version = IndustryTemplateVersion(
        template=template,
        name="事件模板 v1",
        industry_name="制造业",
        version_number=1,
        status="published",
    )
    return Project(
        project_code="EVENT-001",
        name="事件项目",
        enterprise_name="星河制造",
        planned_start_date=date(2026, 8, 21),
        leader_user_id=actor.id,
        source_template_version=version,
        template_snapshot={"industry_name": "制造业", "modules": []},
    )


def test_record_event_preserves_normal_nested_changes_and_removes_sensitive_keys(
    db_session,
):
    """Dropping a whole nested object, or retaining token-like keys, corrupts audit safety."""
    actor = _user()
    project = _project(actor)
    db_session.add_all([actor, project])
    db_session.flush()

    event = record_event(
        db_session,
        actor,
        "project.updated",
        project,
        {
            "progress": 40,
            "metadata": {
                "owner": "项目组",
                "Access_Token": "must-not-persist",
                "nested": {"refreshToken": "must-not-persist", "kept": True},
            },
            "entries": [{"password": "must-not-persist", "label": "生产"}],
            "api_secret_suffix": "must-not-persist",
        },
    )
    db_session.commit()

    saved = db_session.scalar(select(type(event)).where(type(event).id == event.id))
    assert saved is not None
    assert saved.actor_user_id == actor.id
    assert saved.project_id == project.id
    assert saved.target_type == "project"
    assert saved.target_id == project.id
    assert saved.event_type == "project.updated"
    assert saved.changes == {
        "progress": 40,
        "metadata": {"owner": "项目组", "nested": {"kept": True}},
        "entries": [{"label": "生产"}],
    }


def test_record_event_infers_project_scope_from_a_project_task(db_session):
    """Using only direct Project targets would make task events lose their project boundary."""
    actor = _user()
    project = _project(actor)
    db_session.add_all([actor, project])
    db_session.flush()
    from fde_api.workbench.models import ModuleCatalog, ProjectModule

    catalog = ModuleCatalog(module_key="event_module", name="事件模块")
    module = ProjectModule(
        project_id=project.id,
        module_catalog=catalog,
        name="事件模块",
        sort_order=1,
    )
    task = ProjectTask(
        project_module=module,
        task_key="event_task",
        name="事件任务",
        planned_start_date=date(2026, 8, 21),
        planned_end_date=date(2026, 8, 21),
        duration_days=1,
    )
    db_session.add_all([catalog, module, task])
    db_session.flush()

    event = record_event(db_session, actor, "project_task_updated", task, {"progress": 25})
    db_session.commit()

    assert event.project_id == project.id
    assert event.target_type == "project_task"
    assert event.target_id == task.id
    assert event.changes == {"progress": 25}


def test_record_event_supports_a_redacted_template_version_target(db_session):
    """Rejecting template targets would make publication impossible to audit atomically."""
    actor = _user()
    template = IndustryTemplate(
        template_key="audit-template",
        name="审计模板",
        industry_name="制造业",
    )
    version = IndustryTemplateVersion(
        template=template,
        name="审计模板 v1",
        industry_name="制造业",
        version_number=1,
        status="draft",
    )
    db_session.add_all([actor, version])
    db_session.flush()

    event = record_event(
        db_session,
        actor,
        "industry_template_version_published",
        version,
        {"status": {"from": "draft", "to": "published"}, "access_token": "secret"},
    )
    db_session.commit()

    assert event.project_id is None
    assert event.target_type == "industry_template_version"
    assert event.target_id == version.id
    assert event.event_type == "industry_template_version_published"
    assert event.changes == {"status": {"from": "draft", "to": "published"}}


def _cyclic_changes():
    values = []
    values.append(values)
    return {"nested": values}


@pytest.mark.parametrize(
    ("changes_factory", "expected"),
    [
        (
            lambda: {
                "nested": {
                    "items": [
                        UUID("12345678-1234-5678-1234-567812345678"),
                        datetime(2026, 8, 21, 9, 30, 15),
                        date(2026, 8, 21),
                        Decimal("123.4500"),
                        AuditState.READY,
                        ("tuple", Decimal("2.00")),
                        {"beta", "alpha"},
                        UnsafeObject(),
                        {"refresh_token": "must-not-persist", "kept": "yes"},
                    ]
                }
            },
            {
                "nested": {
                    "items": [
                        "12345678-1234-5678-1234-567812345678",
                        "2026-08-21T09:30:15",
                        "2026-08-21",
                        "123.4500",
                        "ready",
                        ["tuple", "2.00"],
                        ["alpha", "beta"],
                        "[unsupported value]",
                        {"kept": "yes"},
                    ]
                }
            },
        ),
        (
            lambda: {
                UUID("87654321-4321-8765-4321-876543218765"): "mapping-key",
                "ACCESS_TOKEN": UnsafeObject(),
                "normal": {"api_secret_suffix": "must-not-persist", "kept": 1},
            },
            {
                "87654321-4321-8765-4321-876543218765": "mapping-key",
                "normal": {"kept": 1},
            },
        ),
        (
            _cyclic_changes,
            {"nested": ["[cyclic value]"]},
        ),
    ],
)
def test_record_event_normalizes_non_json_values_without_leaking_sensitive_data(
    db_session, changes_factory, expected
):
    """Leaving non-JSON values or rendering unknown objects would break or leak audit writes."""
    actor = _user()
    project = _project(actor)
    db_session.add_all([actor, project])
    db_session.flush()

    event = record_event(
        db_session,
        actor,
        "project.updated",
        project,
        changes_factory(),
    )
    db_session.commit()

    saved = db_session.scalar(select(type(event)).where(type(event).id == event.id))
    assert saved is not None
    assert saved.changes == expected
    assert json.dumps(saved.changes, sort_keys=True)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (float("nan"), "[non-finite-number]"),
        (float("inf"), "[non-finite-number]"),
        (float("-inf"), "[non-finite-number]"),
        (12.5, 12.5),
    ],
)
def test_record_event_normalizes_non_finite_floats_for_strict_json_persistence(
    db_session, value, expected
):
    """Passing NaN or infinity through would break strict JSON audit storage."""
    actor = _user()
    project = _project(actor)
    db_session.add_all([actor, project])
    db_session.flush()

    event = record_event(
        db_session,
        actor,
        "project.updated",
        project,
        {"metric": {"value": value}},
    )
    db_session.commit()

    saved = db_session.scalar(select(type(event)).where(type(event).id == event.id))
    assert saved is not None
    assert saved.changes == {"metric": {"value": expected}}
    assert json.dumps(saved.changes, allow_nan=False)
