from __future__ import annotations

from dataclasses import dataclass
from threading import Event, Thread, current_thread

import pytest
from sqlalchemy import event, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from fde_api.auth.models import RefreshSession, User
from fde_api.auth.passwords import hash_password, verify_password
from fde_api.auth.tokens import issue_access_token
from fde_api.workbench.models import IndustryTemplateVersion
from fde_api.workbench.seed import seed_workbench


INITIAL_PASSWORD = "InitialPass!234"
TEMPORARY_PASSWORD = "TempPass!2345"
RESET_PASSWORD = "ResetPass!6789"


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

    def delete(self, *args, **kwargs):
        return self.client.delete(*args, headers=self.headers, **kwargs)


@pytest.fixture
def admin_user(db_session):
    user = User(
        username="admin.user",
        display_name="Administrator",
        role="admin",
        password_hash=hash_password(INITIAL_PASSWORD),
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


@pytest.fixture
def engineer_client(client, db_session, settings):
    user = User(
        username="engineer.user",
        display_name="Engineer",
        role="fde_engineer",
        password_hash=hash_password(INITIAL_PASSWORD),
        must_change_password=False,
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()
    return AuthorizedClient(
        client, {"Authorization": f"Bearer {issue_access_token(user, settings)}"}
    )


@pytest.fixture
def forced_change_admin_client(client, db_session, settings):
    user = User(
        username="forced.admin",
        display_name="Forced administrator",
        role="admin",
        password_hash=hash_password(INITIAL_PASSWORD),
        must_change_password=True,
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()
    return AuthorizedClient(
        client, {"Authorization": f"Bearer {issue_access_token(user, settings)}"}
    )


def assert_error(response, status: int, code: str) -> None:
    assert response.status_code == status
    assert response.json["data"] is None
    assert response.json["error"]["code"] == code
    assert "details" in response.json["error"]


def create_user(admin_client, **overrides):
    payload = {
        "username": "engineer.li",
        "display_name": "李工程师",
        "role": "fde_engineer",
        "temporary_password": TEMPORARY_PASSWORD,
    }
    payload.update(overrides)
    return admin_client.post("/api/v1/users", json=payload)


def create_led_project(admin_client, db_session, *, status: str):
    leader = create_user(
        admin_client,
        username=f"lead.{status}",
        display_name=f"Lead {status}",
        role="project_lead",
    ).json["data"]
    seed_workbench(db_session)
    db_session.commit()
    template = db_session.scalar(
        select(IndustryTemplateVersion).where(
            IndustryTemplateVersion.status == "published"
        )
    )
    project_response = admin_client.post(
        "/api/v1/projects",
        json={
            "name": f"{status} project",
            "enterprise_name": "星河制造",
            "template_version_id": template.id,
            "leader_user_id": leader["id"],
            "planned_start_date": "2026-08-21",
            "module_keys": ["pre_diagnosis"],
        },
    )
    assert project_response.status_code == 201
    project = project_response.json["data"]
    transitions = {
        "active": ("active",),
        "paused": ("active", "paused"),
        "completed": ("active", "completed"),
        "cancelled": ("cancelled",),
    }
    for next_status in transitions.get(status, ()):
        transitioned = admin_client.patch(
            f"/api/v1/projects/{project['id']}",
            json={"version": project["version"], "status": next_status},
        )
        assert transitioned.status_code == 200
        project = transitioned.json["data"]
    return leader, project


def test_admin_creates_normalized_forced_change_user(admin_client, db_session):
    response = create_user(admin_client, username="  Ｅngineer.Li  ")

    assert response.status_code == 201
    assert response.json["error"] is None
    data = response.json["data"]
    assert data["username"] == "engineer.li"
    assert data["display_name"] == "李工程师"
    assert data["role"] == "fde_engineer"
    assert data["must_change_password"] is True
    assert data["is_active"] is True
    assert data["created_at"].endswith("+00:00")
    assert data["updated_at"].endswith("+00:00")
    assert "password" not in data
    assert TEMPORARY_PASSWORD not in response.get_data(as_text=True)

    persisted = db_session.scalar(select(User).where(User.id == data["id"]))
    assert persisted is not None
    assert persisted.password_hash != TEMPORARY_PASSWORD
    assert verify_password(persisted.password_hash, TEMPORARY_PASSWORD)


def test_non_admin_cannot_list_users(engineer_client):
    response = engineer_client.get("/api/v1/users")

    assert_error(response, 403, "forbidden")


def test_forced_change_admin_cannot_manage_users(forced_change_admin_client):
    response = forced_change_admin_client.get("/api/v1/users")

    assert_error(response, 403, "password_change_required")


def test_duplicate_normalized_username_is_rejected_without_secret_echo(
    admin_client, caplog
):
    assert create_user(admin_client).status_code == 201

    response = create_user(admin_client, username="  ＥNGINEER.LI  ")

    assert_error(response, 409, "username_already_exists")
    assert TEMPORARY_PASSWORD not in response.get_data(as_text=True)
    assert TEMPORARY_PASSWORD not in caplog.text


def test_concurrent_normalized_creation_returns_a_stable_duplicate_error(
    app, caplog, monkeypatch
):
    from fde_api.users import service

    password_hashing_started = Event()
    release_first_creation = Event()
    second_conflicting_select_started = Event()
    winner_confirmation_called = Event()
    outcomes = []
    failures = []
    real_hash_password = service.hash_password
    real_username_exists = service._username_exists

    with app.app_context():
        from fde_api.extensions import db

        engine = db.engine
        actor = User(
            username="concurrent.creator",
            display_name="并发创建人",
            role="admin",
            password_hash="x",
            must_change_password=False,
            is_active=True,
        )
        session = db.session()
        session.add(actor)
        session.commit()
        session.close()

    def pause_first_hash(raw_password):
        if current_thread().name == "first-user-creation":
            password_hashing_started.set()
            assert release_first_creation.wait(10)
        return real_hash_password(raw_password)

    monkeypatch.setattr(service, "hash_password", pause_first_hash)

    def observe_winner_confirmation(username):
        winner_confirmation_called.set()
        return real_username_exists(username)

    monkeypatch.setattr(service, "_username_exists", observe_winner_confirmation)

    def observe_second_conflicting_select(_conn, _cursor, statement, *_args):
        normalized = " ".join(statement.lower().split())
        if (
            current_thread().name == "second-user-creation"
            and "from users" in normalized
            and "for update" in normalized
        ):
            second_conflicting_select_started.set()

    event.listen(engine, "before_cursor_execute", observe_second_conflicting_select)

    def create_in_thread(username):
        try:
            with app.app_context():
                user = service.create_user(
                    actor=actor,
                    username=username,
                    display_name="Concurrent engineer",
                    role="fde_engineer",
                    temporary_password=TEMPORARY_PASSWORD,
                )
                outcomes.append(("created", user.username))
        except service.UserServiceError as error:
            outcomes.append((error.code, None))
        except Exception as error:  # surfaced in the main test thread
            failures.append(error)

    first = Thread(
        target=create_in_thread,
        args=("  ＥNGINEER.RACE  ",),
        name="first-user-creation",
    )
    second = Thread(
        target=create_in_thread,
        args=("engineer.race",),
        name="second-user-creation",
    )
    try:
        first.start()
        assert password_hashing_started.wait(10)
        second.start()
        assert second_conflicting_select_started.wait(10)
    finally:
        release_first_creation.set()
        first.join(10)
        second.join(10)
        event.remove(engine, "before_cursor_execute", observe_second_conflicting_select)

    assert not first.is_alive()
    assert not second.is_alive()
    assert failures == []
    assert winner_confirmation_called.is_set()
    assert sorted(outcomes) == [
        ("created", "engineer.race"),
        ("username_already_exists", None),
    ]
    assert TEMPORARY_PASSWORD not in caplog.text
    assert "$argon2" not in caplog.text
    assert "[SQL:" not in caplog.text
    assert "[parameters:" not in caplog.text


def test_duplicate_confirmation_query_failure_is_sanitized(
    admin_client, caplog, monkeypatch
):
    from fde_api.users import service

    class DuplicateKeyError(Exception):
        def __init__(self):
            super().__init__(1062, "duplicate username")

    def raise_duplicate_insert(**_kwargs):
        raise IntegrityError("INSERT users", {"password_hash": "$argon2"}, DuplicateKeyError())

    def fail_confirmation(_username):
        raise SQLAlchemyError("confirmation database failure")

    monkeypatch.setattr(service, "_create_user_once", raise_duplicate_insert)
    monkeypatch.setattr(service, "_username_exists", fail_confirmation)

    response = create_user(admin_client, username="engineer.confirmation-error")

    assert_error(response, 503, "user_creation_failed")
    assert TEMPORARY_PASSWORD not in response.get_data(as_text=True)
    assert "$argon2" not in response.get_data(as_text=True)
    assert "$argon2" not in caplog.text
    assert "[SQL:" not in caplog.text
    assert "[parameters:" not in caplog.text


def test_invalid_role_is_a_validation_error(admin_client):
    response = create_user(admin_client, role="owner")

    assert_error(response, 400, "invalid_role")


@pytest.mark.parametrize(
    "payload",
    [
        {"username": "u" * 121},
        {"display_name": "n" * 121},
    ],
)
def test_create_rejects_values_that_exceed_storage_limits(admin_client, payload):
    response = create_user(admin_client, **payload)

    assert_error(response, 400, "invalid_request")


def test_create_rejects_oversized_password_before_hashing(admin_client, monkeypatch):
    def must_not_hash(*_args):
        raise AssertionError("oversized password reached hashing")

    monkeypatch.setattr("fde_api.users.service.hash_password", must_not_hash)
    response = create_user(admin_client, temporary_password="P" * 1025)

    assert_error(response, 400, "invalid_request")


def test_reset_rejects_oversized_password_before_hashing(admin_client, monkeypatch):
    created = create_user(admin_client).json["data"]

    def must_not_hash(*_args):
        raise AssertionError("oversized password reached hashing")

    monkeypatch.setattr("fde_api.users.service.hash_password", must_not_hash)
    response = admin_client.post(
        f"/api/v1/users/{created['id']}/reset-password",
        json={"temporary_password": "P" * 1025},
    )

    assert_error(response, 400, "invalid_request")


def test_reset_password_revokes_active_sessions_and_requires_change(
    admin_client, client, db_session
):
    created = create_user(admin_client).json["data"]
    pre_reset_login = client.post(
        "/api/v1/auth/login",
        json={
            "username": "engineer.li",
            "password": TEMPORARY_PASSWORD,
            "device_label": "Engineer Mac",
        },
    )
    assert pre_reset_login.status_code == 200

    response = admin_client.post(
        f"/api/v1/users/{created['id']}/reset-password",
        json={"temporary_password": RESET_PASSWORD},
    )

    assert response.status_code == 200
    assert response.json["data"]["must_change_password"] is True
    assert RESET_PASSWORD not in response.get_data(as_text=True)
    db_session.expire_all()
    target = db_session.get(User, created["id"])
    assert target is not None
    assert verify_password(target.password_hash, RESET_PASSWORD)
    assert all(session.revoked_at is not None for session in target.refresh_sessions)

    rejected = client.post(
        "/api/v1/auth/refresh", json={"refresh_token": pre_reset_login.json["data"]["refresh_token"]}
    )
    assert_error(rejected, 401, "refresh_token_invalid")

    reset_login = client.post(
        "/api/v1/auth/login",
        json={
            "username": "engineer.li",
            "password": RESET_PASSWORD,
            "device_label": "Engineer Mac after reset",
        },
    )
    assert reset_login.status_code == 200
    changed = client.post(
        "/api/v1/auth/change-password",
        headers={"Authorization": f"Bearer {reset_login.json['data']['access_token']}"},
        json={"current_password": RESET_PASSWORD, "new_password": "ChangedPass!9012"},
    )
    assert changed.status_code == 200
    old_access = client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {pre_reset_login.json['data']['access_token']}"},
    )
    assert_error(old_access, 401, "access_token_invalid")
    current_access = client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {changed.json['data']['access_token']}"},
    )
    assert current_access.status_code == 200


def test_disabling_user_revokes_refresh_sessions(admin_client, client, db_session):
    created = create_user(admin_client).json["data"]
    login = client.post(
        "/api/v1/auth/login",
        json={
            "username": "engineer.li",
            "password": TEMPORARY_PASSWORD,
            "device_label": "Engineer Mac",
        },
    )
    assert login.status_code == 200

    response = admin_client.patch(
        f"/api/v1/users/{created['id']}", json={"is_active": False}
    )

    assert response.status_code == 200
    assert response.json["data"]["is_active"] is False
    db_session.expire_all()
    target = db_session.get(User, created["id"])
    assert target is not None
    assert all(session.revoked_at is not None for session in target.refresh_sessions)
    rejected = client.post(
        "/api/v1/auth/refresh", json={"refresh_token": login.json["data"]["refresh_token"]}
    )
    assert_error(rejected, 401, "refresh_token_invalid")


def test_pre_disable_access_token_stays_invalid_after_reenable(
    admin_client, client
):
    created = create_user(admin_client).json["data"]
    login = client.post(
        "/api/v1/auth/login",
        json={
            "username": "engineer.li",
            "password": TEMPORARY_PASSWORD,
            "device_label": "Engineer Mac",
        },
    )
    assert login.status_code == 200
    assert admin_client.patch(
        f"/api/v1/users/{created['id']}", json={"is_active": False}
    ).status_code == 200
    assert admin_client.patch(
        f"/api/v1/users/{created['id']}", json={"is_active": True}
    ).status_code == 200

    response = client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {login.json['data']['access_token']}"},
    )

    assert_error(response, 401, "access_token_invalid")


def test_admin_cannot_disable_self(admin_client, admin_user):
    response = admin_client.patch(
        f"/api/v1/users/{admin_user.id}", json={"is_active": False}
    )

    assert_error(response, 400, "self_disable_not_allowed")


def test_admin_updates_user_profile_role_and_active_state(admin_client):
    created = create_user(admin_client).json["data"]

    response = admin_client.patch(
        f"/api/v1/users/{created['id']}",
        json={"display_name": "Lead Engineer", "role": "project_lead"},
    )

    assert response.status_code == 200
    assert response.json["data"]["display_name"] == "Lead Engineer"
    assert response.json["data"]["role"] == "project_lead"
    assert response.json["data"]["is_active"] is True


@pytest.mark.parametrize("project_status", ["draft", "active", "paused"])
def test_admin_cannot_downgrade_or_disable_user_leading_nonterminal_project(
    admin_client, db_session, project_status
):
    """Invalidating a live project's leader would split primitive and route access."""
    leader, _project = create_led_project(
        admin_client, db_session, status=project_status
    )

    downgrade = admin_client.patch(
        f"/api/v1/users/{leader['id']}", json={"role": "fde_engineer"}
    )
    disable = admin_client.patch(
        f"/api/v1/users/{leader['id']}", json={"is_active": False}
    )

    assert_error(downgrade, 409, "user_leads_active_projects")
    assert_error(disable, 409, "user_leads_active_projects")


@pytest.mark.parametrize("project_status", ["completed", "cancelled"])
def test_admin_may_downgrade_and_disable_user_leading_only_terminal_project(
    admin_client, db_session, project_status
):
    """Terminal project history must not permanently lock a user's role or account."""
    leader, _project = create_led_project(
        admin_client, db_session, status=project_status
    )

    response = admin_client.patch(
        f"/api/v1/users/{leader['id']}",
        json={"role": "viewer", "is_active": False},
    )

    assert response.status_code == 200
    assert response.json["data"]["role"] == "viewer"
    assert response.json["data"]["is_active"] is False


@pytest.mark.parametrize("project_status", ["draft", "active", "paused"])
@pytest.mark.parametrize(
    "changes", [{"role": "viewer"}, {"is_active": False}]
)
def test_admin_cannot_downgrade_or_disable_working_member_of_nonterminal_project(
    admin_client, db_session, project_status, changes
):
    """A working membership must not outlive the system capability that permits it."""
    _leader, project = create_led_project(
        admin_client, db_session, status=project_status
    )
    engineer = create_user(
        admin_client,
        username=f"member.{project_status}.{changes!s}",
        display_name="Working member",
    ).json["data"]
    added = admin_client.post(
        f"/api/v1/projects/{project['id']}/members",
        json={"user_id": engineer["id"], "role": "member", "version": project["version"]},
    )
    assert added.status_code == 200

    response = admin_client.patch(f"/api/v1/users/{engineer['id']}", json=changes)

    assert_error(response, 409, "user_has_active_project_memberships")


@pytest.mark.parametrize("changes", [{"role": "viewer"}, {"is_active": False}])
def test_viewer_project_relation_does_not_block_user_lifecycle_changes(
    admin_client, db_session, changes
):
    """Read-only project access does not require a working system role."""
    _leader, project = create_led_project(admin_client, db_session, status="active")
    engineer = create_user(
        admin_client, username=f"viewer.member.{changes!s}", display_name="Viewer"
    ).json["data"]
    added = admin_client.post(
        f"/api/v1/projects/{project['id']}/members",
        json={"user_id": engineer["id"], "role": "viewer", "version": project["version"]},
    )
    assert added.status_code == 200

    response = admin_client.patch(f"/api/v1/users/{engineer['id']}", json=changes)

    assert response.status_code == 200


@pytest.mark.parametrize("project_status", ["completed", "cancelled"])
def test_terminal_working_membership_does_not_block_user_downgrade(
    admin_client, db_session, project_status
):
    """Terminal project history must not permanently retain a working capability."""
    _leader, project = create_led_project(
        admin_client, db_session, status=project_status
    )
    engineer = create_user(
        admin_client,
        username=f"terminal.member.{project_status}",
        display_name="Terminal member",
    ).json["data"]
    added = admin_client.post(
        f"/api/v1/projects/{project['id']}/members",
        json={"user_id": engineer["id"], "role": "member", "version": project["version"]},
    )
    assert added.status_code == 200

    response = admin_client.patch(
        f"/api/v1/users/{engineer['id']}", json={"role": "viewer", "is_active": False}
    )

    assert response.status_code == 200


def test_removing_nonterminal_working_membership_allows_user_downgrade(
    admin_client, db_session
):
    """Removing the last live working relation restores the user's lifecycle change."""
    _leader, project = create_led_project(admin_client, db_session, status="active")
    engineer = create_user(
        admin_client, username="removed.member", display_name="Removed member"
    ).json["data"]
    added = admin_client.post(
        f"/api/v1/projects/{project['id']}/members",
        json={"user_id": engineer["id"], "role": "member", "version": project["version"]},
    )
    assert added.status_code == 200
    removed = admin_client.delete(
        f"/api/v1/projects/{project['id']}/members/{added.json['data']['id']}",
        json={"version": added.json["data"]["project_version"]},
    )
    assert removed.status_code == 204

    response = admin_client.patch(
        f"/api/v1/users/{engineer['id']}", json={"role": "viewer"}
    )

    assert response.status_code == 200


def test_update_rejects_display_name_that_exceeds_storage_limit(admin_client):
    created = create_user(admin_client).json["data"]

    response = admin_client.patch(
        f"/api/v1/users/{created['id']}", json={"display_name": "n" * 121}
    )

    assert_error(response, 400, "invalid_request")


def test_list_filters_by_role_and_status_and_uses_stable_pagination(admin_client):
    first = create_user(
        admin_client,
        username="viewer.alpha",
        display_name="Alpha",
        role="viewer",
    ).json["data"]
    second = create_user(
        admin_client,
        username="viewer.beta",
        display_name="Beta",
        role="viewer",
    ).json["data"]
    third = create_user(
        admin_client,
        username="viewer.gamma",
        display_name="Gamma",
        role="viewer",
    ).json["data"]
    assert admin_client.patch(
        f"/api/v1/users/{second['id']}", json={"is_active": False}
    ).status_code == 200

    active_response = admin_client.get("/api/v1/users?role=viewer&active=true")
    inactive_response = admin_client.get("/api/v1/users?role=viewer&active=false")
    assert active_response.status_code == 200
    assert {item["id"] for item in active_response.json["data"]["items"]} == {
        first["id"],
        third["id"],
    }
    assert [item["id"] for item in inactive_response.json["data"]["items"]] == [
        second["id"]
    ]

    page_one = admin_client.get("/api/v1/users?role=viewer&page=1&page_size=2")
    page_one_again = admin_client.get(
        "/api/v1/users?role=viewer&page=1&page_size=2"
    )
    page_two = admin_client.get("/api/v1/users?role=viewer&page=2&page_size=2")
    assert page_one.status_code == 200
    assert page_one.json["data"] == page_one_again.json["data"]
    assert page_one.json["data"]["total"] == 3
    assert page_one.json["data"]["page"] == 1
    assert page_one.json["data"]["page_size"] == 2
    assert len(page_one.json["data"]["items"]) == 2
    assert len(page_two.json["data"]["items"]) == 1
    assert {
        item["id"] for item in page_one.json["data"]["items"]
    }.isdisjoint({item["id"] for item in page_two.json["data"]["items"]})


@pytest.mark.parametrize(
    "query",
    ["page_size=101", "page=0", "active=unknown", "role=owner"],
)
def test_list_rejects_invalid_pagination_and_filters(admin_client, query):
    response = admin_client.get(f"/api/v1/users?{query}")

    assert_error(response, 400, "invalid_request")


def test_missing_target_returns_not_found_and_updates_require_a_field(admin_client):
    missing = admin_client.patch(
        "/api/v1/users/does-not-exist", json={"display_name": "Nobody"}
    )
    empty_update = admin_client.patch("/api/v1/users/does-not-exist", json={})

    assert_error(missing, 404, "user_not_found")
    assert_error(empty_update, 400, "invalid_request")


def test_user_dtos_never_include_security_storage(admin_client):
    created = create_user(admin_client).json["data"]
    listed = admin_client.get("/api/v1/users").json["data"]["items"]
    returned = [item for item in listed if item["id"] == created["id"]][0]

    for data in (created, returned):
        assert set(data) == {
            "id",
            "username",
            "display_name",
            "role",
            "is_active",
            "must_change_password",
            "created_at",
            "updated_at",
        }
        assert "password_hash" not in data
        assert "refresh_sessions" not in data


def test_disable_revokes_only_active_sessions(admin_client, db_session):
    created = create_user(admin_client).json["data"]
    target = db_session.get(User, created["id"])
    assert target is not None
    active_session = RefreshSession(
        user_id=target.id,
        token_digest="a" * 64,
        expires_at=target.created_at,
    )
    revoked_session = RefreshSession(
        user_id=target.id,
        token_digest="b" * 64,
        expires_at=target.created_at,
        revoked_at=target.created_at,
    )
    db_session.add_all((active_session, revoked_session))
    db_session.commit()

    response = admin_client.patch(
        f"/api/v1/users/{target.id}", json={"is_active": False}
    )

    assert response.status_code == 200
    db_session.expire_all()
    active = db_session.get(RefreshSession, active_session.id)
    already_revoked = db_session.get(RefreshSession, revoked_session.id)
    assert active is not None and active.revoked_at is not None
    assert already_revoked is not None and already_revoked.revoked_at == target.created_at
