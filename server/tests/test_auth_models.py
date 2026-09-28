from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError

from fde_api.auth.models import InvalidRoleError, RefreshSession, User


def test_user_rejects_invalid_role_at_model_boundary():
    with pytest.raises(InvalidRoleError):
        User(username="sample_user", password_hash="x", role="unknown")


def test_database_role_check_rejects_direct_invalid_storage(db_session):
    with pytest.raises(DBAPIError):
        db_session.execute(
            text(
                "INSERT INTO users (id, username, display_name, role, password_hash, "
                "must_change_password, is_active) "
                "VALUES (:id, :username, :display_name, :role, :password_hash, "
                ":must_change_password, :is_active)"
            ),
            {
                "id": str(uuid4()),
                "username": "invalid-role",
                "display_name": "Invalid Role",
                "role": "unknown",
                "password_hash": "x",
                "must_change_password": True,
                "is_active": True,
            },
        )


def test_user_username_is_normalized_and_unique(db_session):
    first = User(username="  SAMPLE_USER  ", password_hash="x", role="admin")
    second = User(username="sample_user", password_hash="x", role="viewer")
    db_session.add(first)
    db_session.commit()

    assert first.username == "sample_user"

    db_session.add(second)
    with pytest.raises(IntegrityError):
        db_session.commit()


def test_refresh_session_belongs_to_user_and_has_utc_expiry(db_session):
    user = User(username="sample_user", password_hash="x", role="admin")
    session = RefreshSession(
        user=user,
        token_digest="a" * 64,
        expires_at=datetime(2030, 1, 1, tzinfo=UTC),
        device_label="Example Mac",
    )
    db_session.add(user)
    db_session.commit()

    assert user.refresh_sessions == [session]
    assert session.user_id == user.id


def test_database_timestamps_reload_with_utc_timezone(db_session):
    user = User(username="sample_user", password_hash="x", role="admin")
    db_session.add(user)
    db_session.commit()
    db_session.expire_all()

    reloaded = db_session.get(User, user.id)

    assert reloaded is not None
    assert reloaded.created_at.tzinfo is UTC
    assert reloaded.updated_at.tzinfo is UTC


def test_user_auth_version_defaults_to_one_in_model_and_database(db_session):
    user = User(username="versioned", password_hash="x", role="admin")

    assert user.auth_version == 1
    db_session.add(user)
    db_session.commit()
    db_session.expire_all()

    reloaded = db_session.get(User, user.id)
    assert reloaded is not None
    assert reloaded.auth_version == 1


def test_app_database_sessions_default_to_utc(db_session):
    assert db_session.execute(text("SELECT @@session.time_zone")).scalar_one() == "+00:00"


def test_mysql_server_timestamps_ignore_connection_timezone(db_session):
    user_id = str(uuid4())
    db_session.execute(text("SET time_zone = '+08:00'"))
    try:
        db_session.execute(
            text(
                "INSERT INTO users (id, username, display_name, role, password_hash, "
                "must_change_password, is_active) "
                "VALUES (:id, :username, :display_name, :role, :password_hash, "
                ":must_change_password, :is_active)"
            ),
            {
                "id": user_id,
                "username": "database-user",
                "display_name": "Database User",
                "role": "admin",
                "password_hash": "x",
                "must_change_password": True,
                "is_active": True,
            },
        )
        db_session.commit()
        db_session.execute(text("SET time_zone = '+00:00'"))
        db_session.expire_all()
        inserted = db_session.get(User, user_id)
        assert inserted is not None
        original_updated_at = inserted.updated_at
        assert abs((datetime.now(UTC) - inserted.created_at).total_seconds()) < 5

        db_session.execute(text("SET time_zone = '+08:00'"))
        db_session.execute(
            text("UPDATE users SET display_name = 'Updated User' WHERE id = :id"),
            {"id": user_id},
        )
        db_session.commit()
        db_session.execute(text("SET time_zone = '+00:00'"))
        db_session.expire_all()
        updated = db_session.get(User, user_id)
        assert updated is not None
        assert updated.updated_at > original_updated_at
        assert abs((datetime.now(UTC) - updated.updated_at).total_seconds()) < 5
    finally:
        db_session.execute(text("SET time_zone = '+00:00'"))
        db_session.commit()
