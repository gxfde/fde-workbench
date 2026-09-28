from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from threading import Event, Thread, current_thread

import jwt
import pytest
from sqlalchemy import event, select

from fde_api.auth.models import InvalidRoleError, RefreshSession, User
from fde_api.auth.passwords import hash_password


INITIAL_PASSWORD = "InitialPass!234"
CHANGED_PASSWORD = "ChangedPass!567"


@dataclass(frozen=True)
class LoginTokens:
    access: str
    refresh: str


@pytest.fixture
def active_user(db_session):
    user = User(
        username="  ＳAMPLE_USER  ",
        display_name="示例用户",
        role="admin",
        password_hash=hash_password(INITIAL_PASSWORD),
        must_change_password=True,
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()
    return user


@pytest.fixture
def login_tokens(client, active_user):
    response = client.post(
        "/api/v1/auth/login",
        json={
            "username": active_user.username,
            "password": INITIAL_PASSWORD,
            "device_label": "Example Mac",
        },
    )
    assert response.status_code == 200
    return LoginTokens(
        access=response.json["data"]["access_token"],
        refresh=response.json["data"]["refresh_token"],
    )


def auth_header(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def assert_error(response, status: int, code: str) -> None:
    assert response.status_code == status
    assert response.json["data"] is None
    assert response.json["error"]["code"] == code
    assert "details" in response.json["error"]


def test_login_returns_access_and_rotatable_refresh(client, active_user, db_session):
    response = client.post(
        "/api/v1/auth/login",
        json={
            "username": "  SAMPLE_USER  ",
            "password": INITIAL_PASSWORD,
            "device_label": "Example Mac",
        },
    )

    assert response.status_code == 200
    assert response.json["error"] is None
    assert response.json["data"]["user"] == {
        "id": active_user.id,
        "username": "sample_user",
        "display_name": "示例用户",
        "role": "admin",
        "must_change_password": True,
        "is_active": True,
    }
    assert response.json["data"]["access_token"]
    refresh_token = response.json["data"]["refresh_token"]
    assert refresh_token
    assert response.json["data"]["access_expires_at"].endswith("+00:00")
    assert response.json["data"]["refresh_expires_at"].endswith("+00:00")

    db_session.expire_all()
    persisted = db_session.scalars(select(RefreshSession)).one()
    assert persisted.device_label == "Example Mac"
    assert persisted.token_digest != refresh_token
    assert refresh_token not in persisted.token_digest


@pytest.mark.parametrize("username,password", [("missing", INITIAL_PASSWORD), ("sample_user", "WrongPass!234")])
def test_login_uses_same_error_for_unknown_user_and_wrong_password(
    client, active_user, username, password
):
    response = client.post(
        "/api/v1/auth/login",
        json={"username": username, "password": password, "device_label": "Browser"},
    )

    assert_error(response, 401, "invalid_credentials")
    assert response.json["error"]["message"] == "Invalid username or password."


def test_login_rejects_inactive_user(client, active_user, db_session):
    active_user.is_active = False
    db_session.commit()

    response = client.post(
        "/api/v1/auth/login",
        json={"username": "sample_user", "password": INITIAL_PASSWORD, "device_label": "Browser"},
    )

    assert_error(response, 403, "account_inactive")


def test_login_rejects_missing_json_fields_without_echoing_password(client, active_user):
    response = client.post(
        "/api/v1/auth/login",
        json={"username": "sample_user", "password": INITIAL_PASSWORD},
    )

    assert_error(response, 400, "invalid_request")
    assert INITIAL_PASSWORD not in response.get_data(as_text=True)


def test_refresh_rotates_and_rejects_reuse(client, login_tokens):
    first = client.post(
        "/api/v1/auth/refresh", json={"refresh_token": login_tokens.refresh}
    )
    assert first.status_code == 200
    assert first.json["data"]["refresh_token"] != login_tokens.refresh

    reused = client.post(
        "/api/v1/auth/refresh", json={"refresh_token": login_tokens.refresh}
    )
    assert_error(reused, 401, "refresh_token_invalid")

    rotated = client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": first.json["data"]["refresh_token"]},
    )
    assert rotated.status_code == 200


def test_refresh_rejects_expired_session(client, login_tokens, db_session):
    persisted = db_session.scalars(select(RefreshSession)).one()
    persisted.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    db_session.commit()

    response = client.post(
        "/api/v1/auth/refresh", json={"refresh_token": login_tokens.refresh}
    )

    assert_error(response, 401, "refresh_token_invalid")


def test_logout_revokes_refresh_without_echoing_it(client, login_tokens):
    response = client.post(
        "/api/v1/auth/logout", json={"refresh_token": login_tokens.refresh}
    )

    assert response.status_code == 200
    assert response.json == {"data": {"revoked": True}, "error": None}
    assert login_tokens.refresh not in response.get_data(as_text=True)

    rejected = client.post(
        "/api/v1/auth/refresh", json={"refresh_token": login_tokens.refresh}
    )
    assert_error(rejected, 401, "refresh_token_invalid")


def test_me_allows_forced_change_token(client, active_user, login_tokens):
    response = client.get(
        "/api/v1/auth/me", headers=auth_header(login_tokens.access)
    )

    assert response.status_code == 200
    assert response.json["data"]["id"] == active_user.id
    assert response.json["data"]["must_change_password"] is True
    assert "password_hash" not in response.json["data"]


def test_verify_password_accepts_the_current_password(client, login_tokens):
    response = client.post(
        "/api/v1/auth/verify-password",
        headers=auth_header(login_tokens.access),
        json={"password": INITIAL_PASSWORD},
    )

    assert response.status_code == 200
    assert response.json == {"data": {"valid": True}, "error": None}
    assert INITIAL_PASSWORD not in response.get_data(as_text=True)


def test_verify_password_rejects_a_wrong_password_without_echoing_it(
    client, login_tokens
):
    wrong_password = "WrongPass!999"
    response = client.post(
        "/api/v1/auth/verify-password",
        headers=auth_header(login_tokens.access),
        json={"password": wrong_password},
    )

    assert_error(response, 400, "invalid_password")
    assert wrong_password not in response.get_data(as_text=True)


def test_verify_password_still_accepts_a_forced_change_token(
    client, active_user, login_tokens
):
    response = client.post(
        "/api/v1/auth/verify-password",
        headers=auth_header(login_tokens.access),
        json={"password": INITIAL_PASSWORD},
    )

    assert response.status_code == 200
    assert response.json["data"]["valid"] is True


def test_verify_password_requires_authentication(client):
    response = client.post(
        "/api/v1/auth/verify-password", json={"password": INITIAL_PASSWORD}
    )

    assert_error(response, 401, "access_token_invalid")


def test_verify_password_rejects_missing_or_oversized_password(
    client, login_tokens
):
    missing = client.post(
        "/api/v1/auth/verify-password",
        headers=auth_header(login_tokens.access),
        json={},
    )
    assert_error(missing, 400, "invalid_request")

    oversized = client.post(
        "/api/v1/auth/verify-password",
        headers=auth_header(login_tokens.access),
        json={"password": "P" * 1025},
    )
    assert_error(oversized, 400, "invalid_request")
    assert ("P" * 1025) not in oversized.get_data(as_text=True)


def test_forced_change_token_cannot_access_normal_authenticated_route(
    app, client, active_user, settings
):
    from fde_api.auth.decorators import require_auth
    from fde_api.auth.tokens import issue_access_token

    @app.get("/api/v1/test-authenticated")
    @require_auth
    def authenticated_route():
        return {"data": {"ok": True}, "error": None}

    access_token = issue_access_token(active_user, settings)
    response = client.get(
        "/api/v1/test-authenticated", headers=auth_header(access_token)
    )

    assert_error(response, 403, "password_change_required")


def test_require_role_runs_forced_change_check_before_role_check(
    app, client, active_user, settings
):
    from fde_api.auth.decorators import require_role
    from fde_api.auth.tokens import issue_access_token

    @app.get("/api/v1/test-admin")
    @require_role("viewer")
    def viewer_route():
        return {"data": {"ok": True}, "error": None}

    access_token = issue_access_token(active_user, settings)
    response = client.get(
        "/api/v1/test-admin", headers=auth_header(access_token)
    )

    assert_error(response, 403, "password_change_required")


def test_require_role_rejects_invalid_declared_role():
    from fde_api.auth.decorators import require_role

    with pytest.raises(InvalidRoleError):
        require_role("owner")


def test_expired_access_token_is_rejected(app, client, active_user, settings):
    expired = jwt.encode(
        {
            "sub": active_user.id,
            "role": active_user.role,
            "pwd": True,
            "ver": active_user.auth_version,
            "iat": datetime.now(UTC) - timedelta(minutes=20),
            "exp": datetime.now(UTC) - timedelta(minutes=5),
            "iss": "fde-workbench",
        },
        settings.jwt_secret,
        algorithm="HS256",
    )

    response = client.get("/api/v1/auth/me", headers=auth_header(expired))

    assert_error(response, 401, "access_token_invalid")


def test_authentication_reloads_user_and_rejects_newly_inactive_user(
    client, active_user, login_tokens, db_session
):
    active_user.is_active = False
    db_session.commit()

    response = client.get(
        "/api/v1/auth/me", headers=auth_header(login_tokens.access)
    )

    assert_error(response, 403, "account_inactive")


def test_authentication_rejects_a_token_with_an_old_auth_version(
    client, active_user, login_tokens, db_session
):
    active_user.must_change_password = False
    active_user.auth_version += 1
    db_session.commit()

    response = client.get(
        "/api/v1/auth/me", headers=auth_header(login_tokens.access)
    )

    assert_error(response, 401, "access_token_invalid")


def test_require_role_uses_current_database_role_not_stale_claim(
    app, client, active_user, db_session, settings
):
    from fde_api.auth.decorators import require_role
    from fde_api.auth.tokens import issue_access_token

    active_user.must_change_password = False
    db_session.commit()
    admin_claim_token = issue_access_token(active_user, settings)
    active_user.role = "viewer"
    db_session.commit()

    @app.get("/api/v1/test-current-admin")
    @require_role("admin")
    def current_admin_route():
        return {"data": {"ok": True}, "error": None}

    response = client.get(
        "/api/v1/test-current-admin", headers=auth_header(admin_claim_token)
    )

    assert_error(response, 403, "forbidden")


def test_change_password_revokes_all_prior_sessions_and_issues_permitted_pair(
    client, active_user
):
    first_login = client.post(
        "/api/v1/auth/login",
        json={"username": "sample_user", "password": INITIAL_PASSWORD, "device_label": "Mac"},
    ).json["data"]
    second_login = client.post(
        "/api/v1/auth/login",
        json={"username": "sample_user", "password": INITIAL_PASSWORD, "device_label": "Phone"},
    ).json["data"]

    changed = client.post(
        "/api/v1/auth/change-password",
        headers=auth_header(first_login["access_token"]),
        json={
            "current_password": INITIAL_PASSWORD,
            "new_password": CHANGED_PASSWORD,
        },
    )

    assert changed.status_code == 200
    assert changed.json["data"]["access_token"]
    assert changed.json["data"]["refresh_token"]
    assert changed.json["data"]["user"] == {
        "id": active_user.id,
        "username": "sample_user",
        "display_name": "示例用户",
        "role": "admin",
        "must_change_password": False,
        "is_active": True,
    }
    assert CHANGED_PASSWORD not in changed.get_data(as_text=True)

    me = client.get(
        "/api/v1/auth/me",
        headers=auth_header(changed.json["data"]["access_token"]),
    )
    assert me.status_code == 200
    assert me.json["data"]["must_change_password"] is False

    for old_refresh in (first_login["refresh_token"], second_login["refresh_token"]):
        rejected = client.post(
            "/api/v1/auth/refresh", json={"refresh_token": old_refresh}
        )
        assert_error(rejected, 401, "refresh_token_invalid")

    new_refresh = client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": changed.json["data"]["refresh_token"]},
    )
    assert new_refresh.status_code == 200

    old_login = client.post(
        "/api/v1/auth/login",
        json={"username": "sample_user", "password": INITIAL_PASSWORD, "device_label": "Mac"},
    )
    assert_error(old_login, 401, "invalid_credentials")
    new_login = client.post(
        "/api/v1/auth/login",
        json={"username": "sample_user", "password": CHANGED_PASSWORD, "device_label": "Mac"},
    )
    assert new_login.status_code == 200


def test_change_password_rejects_fewer_than_six_characters(client, login_tokens):
    response = client.post(
        "/api/v1/auth/change-password",
        headers=auth_header(login_tokens.access),
        json={"current_password": INITIAL_PASSWORD, "new_password": "12345"},
    )

    assert_error(response, 400, "password_too_weak")


def test_change_password_rejects_wrong_current_password(client, login_tokens):
    response = client.post(
        "/api/v1/auth/change-password",
        headers=auth_header(login_tokens.access),
        json={"current_password": "WrongPass!234", "new_password": CHANGED_PASSWORD},
    )

    assert_error(response, 401, "invalid_credentials")
    still_valid = client.post(
        "/api/v1/auth/refresh", json={"refresh_token": login_tokens.refresh}
    )
    assert still_valid.status_code == 200


def test_password_and_bad_refresh_never_appear_in_response_or_logs(
    client, active_user, caplog
):
    raw_password = "NeverLogThis!456"
    raw_refresh = "NeverLogThisRefreshToken"

    bad_login = client.post(
        "/api/v1/auth/login",
        json={"username": "sample_user", "password": raw_password, "device_label": "Browser"},
    )
    bad_refresh = client.post(
        "/api/v1/auth/refresh", json={"refresh_token": raw_refresh}
    )

    combined_responses = bad_login.get_data(as_text=True) + bad_refresh.get_data(as_text=True)
    assert raw_password not in combined_responses
    assert raw_refresh not in combined_responses
    assert raw_password not in caplog.text
    assert raw_refresh not in caplog.text


@pytest.mark.parametrize(
    "payload",
    [
        {"username": "u" * 121, "password": INITIAL_PASSWORD},
        {"username": "sample_user", "password": "P" * 1025},
    ],
)
def test_login_rejects_oversized_credentials_before_password_verification(
    client, monkeypatch, payload
):
    def must_not_verify(*_args):
        raise AssertionError("oversized credentials reached password verification")

    monkeypatch.setattr("fde_api.auth.service.verify_password", must_not_verify)
    response = client.post(
        "/api/v1/auth/login",
        json={**payload, "device_label": "Boundary test"},
    )

    assert_error(response, 400, "invalid_request")


@pytest.mark.parametrize(
    "payload",
    [
        {"current_password": "P" * 1025, "new_password": CHANGED_PASSWORD},
        {"current_password": INITIAL_PASSWORD, "new_password": "P" * 1025},
    ],
)
def test_change_password_rejects_oversized_passwords_before_verification(
    client, login_tokens, monkeypatch, payload
):
    def must_not_verify(*_args):
        raise AssertionError("oversized password reached verification")

    monkeypatch.setattr("fde_api.auth.service.verify_password", must_not_verify)
    response = client.post(
        "/api/v1/auth/change-password",
        headers=auth_header(login_tokens.access),
        json=payload,
    )

    assert_error(response, 400, "invalid_request")


def test_concurrent_old_password_login_cannot_survive_password_change(
    app, client, active_user, db_session, monkeypatch
):
    from fde_api.auth import service
    from fde_api.extensions import db

    active_user.must_change_password = False
    db_session.commit()

    login_verified = Event()
    release_login = Event()
    change_lock_attempted = Event()
    change_finished = Event()
    results = {}
    failures = []
    real_verify_password = service.verify_password

    def coordinated_verify(hash_value, raw):
        matches = real_verify_password(hash_value, raw)
        if current_thread().name == "old-password-login":
            login_verified.set()
            if not release_login.wait(10):
                raise AssertionError("login coordination timed out")
        return matches

    monkeypatch.setattr(service, "verify_password", coordinated_verify)

    with app.app_context():
        engine = db.engine

    def observe_change_lock_attempt(_conn, _cursor, statement, *_args):
        normalized = " ".join(statement.lower().split())
        if (
            current_thread().name == "password-change"
            and "from users" in normalized
            and "for update" in normalized
        ):
            change_lock_attempted.set()

    event.listen(engine, "before_cursor_execute", observe_change_lock_attempt)

    def old_password_login():
        try:
            with app.app_context():
                _user, results["old_login_pair"] = service.login(
                    "sample_user", INITIAL_PASSWORD, "Concurrent old login"
                )
        except Exception as error:  # surfaced in the main test thread
            failures.append(error)

    def password_change():
        try:
            with app.app_context():
                (_changed_user, results["changed_pair"]) = (
                    service.change_password(
                        active_user, INITIAL_PASSWORD, CHANGED_PASSWORD
                    )
                )
        except Exception as error:  # surfaced in the main test thread
            failures.append(error)
        finally:
            change_finished.set()

    login_thread = Thread(target=old_password_login, name="old-password-login")
    change_thread = Thread(target=password_change, name="password-change")
    try:
        login_thread.start()
        assert login_verified.wait(10)
        change_thread.start()
        assert change_lock_attempted.wait(10)
        change_completed_while_login_was_paused = change_finished.wait(1)
    finally:
        release_login.set()
        login_thread.join(10)
        change_thread.join(10)
        event.remove(engine, "before_cursor_execute", observe_change_lock_attempt)

    assert not login_thread.is_alive()
    assert not change_thread.is_alive()
    assert failures == []
    assert change_completed_while_login_was_paused is False

    old_refresh = results["old_login_pair"].refresh_token
    rejected = client.post(
        "/api/v1/auth/refresh", json={"refresh_token": old_refresh}
    )
    assert_error(rejected, 401, "refresh_token_invalid")

    changed_refresh = results["changed_pair"].refresh_token
    accepted = client.post(
        "/api/v1/auth/refresh", json={"refresh_token": changed_refresh}
    )
    assert accepted.status_code == 200


def test_concurrent_refresh_rotation_and_password_change_use_same_lock_order(
    app, client, active_user, db_session
):
    from fde_api.extensions import db

    active_user.must_change_password = False
    db_session.commit()
    login_data = client.post(
        "/api/v1/auth/login",
        json={
            "username": "sample_user",
            "password": INITIAL_PASSWORD,
            "device_label": "Before concurrent change",
        },
    ).json["data"]

    rotation_first_lock = Event()
    release_rotation = Event()
    change_refresh_update_attempted = Event()
    responses = {}
    failures = []

    with app.app_context():
        engine = db.engine

    def pause_after_rotation_first_lock(_conn, _cursor, statement, *_args):
        normalized = " ".join(statement.lower().split())
        if (
            current_thread().name == "refresh-rotation"
            and "for update" in normalized
            and ("from users" in normalized or "from refresh_sessions" in normalized)
            and not rotation_first_lock.is_set()
        ):
            rotation_first_lock.set()
            if not release_rotation.wait(10):
                raise AssertionError("rotation coordination timed out")

    def observe_change_refresh_update(_conn, _cursor, statement, *_args):
        normalized = " ".join(statement.lower().split())
        if (
            current_thread().name == "password-change"
            and normalized.startswith("update refresh_sessions")
        ):
            change_refresh_update_attempted.set()

    event.listen(engine, "after_cursor_execute", pause_after_rotation_first_lock)
    event.listen(engine, "before_cursor_execute", observe_change_refresh_update)

    def rotate_refresh():
        try:
            with app.test_client() as thread_client:
                response = thread_client.post(
                    "/api/v1/auth/refresh",
                    json={"refresh_token": login_data["refresh_token"]},
                )
                responses["rotate"] = (response.status_code, response.json)
        except Exception as error:  # surfaced in the main test thread
            failures.append(error)

    def change_password_concurrently():
        try:
            with app.test_client() as thread_client:
                response = thread_client.post(
                    "/api/v1/auth/change-password",
                    headers=auth_header(login_data["access_token"]),
                    json={
                        "current_password": INITIAL_PASSWORD,
                        "new_password": CHANGED_PASSWORD,
                    },
                )
                responses["change"] = (response.status_code, response.json)
        except Exception as error:  # surfaced in the main test thread
            failures.append(error)

    rotate_thread = Thread(target=rotate_refresh, name="refresh-rotation")
    change_thread = Thread(
        target=change_password_concurrently, name="password-change"
    )
    try:
        rotate_thread.start()
        assert rotation_first_lock.wait(10)
        change_thread.start()
        change_reached_refresh_before_rotation_released = (
            change_refresh_update_attempted.wait(1)
        )
    finally:
        release_rotation.set()
        rotate_thread.join(10)
        change_thread.join(10)
        event.remove(engine, "after_cursor_execute", pause_after_rotation_first_lock)
        event.remove(engine, "before_cursor_execute", observe_change_refresh_update)

    assert not rotate_thread.is_alive()
    assert not change_thread.is_alive()
    assert failures == []
    assert change_reached_refresh_before_rotation_released is False
    assert responses["rotate"][0] == 200
    assert responses["change"][0] == 200

    rotated_refresh = responses["rotate"][1]["data"]["refresh_token"]
    rejected = client.post(
        "/api/v1/auth/refresh", json={"refresh_token": rotated_refresh}
    )
    assert_error(rejected, 401, "refresh_token_invalid")

    changed_refresh = responses["change"][1]["data"]["refresh_token"]
    accepted = client.post(
        "/api/v1/auth/refresh", json={"refresh_token": changed_refresh}
    )
    assert accepted.status_code == 200
