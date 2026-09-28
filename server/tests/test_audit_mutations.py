"""Integration proof that representative mutations append OperationEvent rows
while read-only calls do not. Uses the same client/auth style as test_users_api."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from fde_api.auth.models import User
from fde_api.auth.passwords import hash_password
from fde_api.auth.tokens import issue_access_token
from fde_api.workbench.models import OperationEvent

TEMPORARY_PASSWORD = "InitialPass!234"


class AuthorizedClient:
    def __init__(self, client, headers):
        self.client = client
        self.headers = headers

    def get(self, *args, **kwargs):
        return self.client.get(*args, headers=self.headers, **kwargs)

    def post(self, *args, **kwargs):
        return self.client.post(*args, headers=self.headers, **kwargs)

    def patch(self, *args, **kwargs):
        return self.client.patch(*args, headers=self.headers, **kwargs)


@pytest.fixture
def admin_user(db_session):
    user = User(
        username="audit.admin",
        display_name="Audit Administrator",
        role="admin",
        password_hash=hash_password(TEMPORARY_PASSWORD),
        must_change_password=False,
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()
    return user


@pytest.fixture
def admin_client(client, admin_user, settings):
    return AuthorizedClient(
        client, {"Authorization": f"Bearer {issue_access_token(admin_user, settings)}"}
    )


def _event(db_session, *, target_type, event_type):
    # End any in-progress read transaction so REPEATABLE READ sees rows committed
    # by the API's own request-scoped transaction since the previous read.
    db_session.rollback()
    return db_session.scalar(
        select(OperationEvent).where(
            OperationEvent.target_type == target_type,
            OperationEvent.event_type == event_type,
        )
    )


def test_user_creation_and_deactivation_are_audited(admin_client, db_session):
    created = admin_client.post(
        "/api/v1/users",
        json={
            "username": "audited.engineer",
            "display_name": "被审计工程师",
            "role": "fde_engineer",
            "temporary_password": TEMPORARY_PASSWORD,
        },
    )
    assert created.status_code == 201, created.get_data(as_text=True)
    user_id = created.json["data"]["id"]

    create_event = _event(db_session, target_type="user", event_type="user_created")
    assert create_event is not None
    assert create_event.target_id == user_id
    assert create_event.project_id is None
    assert create_event.changes["role"] == "fde_engineer"

    # Deactivate (PATCH is_active=false) emits a distinct deactivation event.
    deactivated = admin_client.patch(
        f"/api/v1/users/{user_id}", json={"is_active": False}
    )
    assert deactivated.status_code == 200, deactivated.get_data(as_text=True)

    deactivate_event = _event(
        db_session, target_type="user", event_type="user_deactivated"
    )
    assert deactivate_event is not None
    assert deactivate_event.target_id == user_id
    assert deactivate_event.changes["is_active"]["to"] is False


def test_module_creation_is_audited(admin_client, db_session):
    created = admin_client.post(
        "/api/v1/modules",
        json={"name": "审计模块", "description": "", "sort_order": 1, "is_active": True},
    )
    assert created.status_code == 201, created.get_data(as_text=True)
    module_id = created.json["data"]["id"]

    create_event = _event(db_session, target_type="module", event_type="module_created")
    assert create_event is not None
    assert create_event.target_id == module_id
    assert create_event.project_id is None


def test_read_calls_do_not_write_operation_events(admin_client, db_session):
    before = len(list(db_session.scalars(select(OperationEvent))))

    listed_users = admin_client.get("/api/v1/users?page=1&page_size=20")
    assert listed_users.status_code == 200
    listed_modules = admin_client.get("/api/v1/modules?page=1&page_size=20")
    assert listed_modules.status_code == 200

    assert len(list(db_session.scalars(select(OperationEvent)))) == before
