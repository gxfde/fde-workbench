from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError, OperationalError, SQLAlchemyError

from fde_api.auth.models import (
    InvalidRoleError,
    RefreshSession,
    User,
    VALID_ROLES,
)
from fde_api.auth.passwords import hash_password
from fde_api.auth.limits import USERNAME_MAX_LENGTH
from fde_api.auth.service import normalize_username, validate_password_strength
from fde_api.extensions import db
from fde_api.projects.events import record_event
from fde_api.workbench.models import Project, ProjectMember


class UserServiceError(Exception):
    def __init__(self, code: str, message: str, status: int):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


DISPLAY_NAME_MAX_LENGTH = 120
MYSQL_DUPLICATE_ENTRY = 1062
MYSQL_DEADLOCK = 1213
NONTERMINAL_PROJECT_STATUSES = frozenset({"draft", "active", "paused"})


def list_users(
    *, page: int, page_size: int, role: str | None, active: bool | None
) -> tuple[list[User], int]:
    if role is not None:
        _validate_role(role)

    session = db.session()
    try:
        filters = []
        if role is not None:
            filters.append(User.role == role)
        if active is not None:
            filters.append(User.is_active.is_(active))

        statement = select(User).where(*filters).order_by(User.created_at, User.id)
        users = list(
            session.scalars(statement.offset((page - 1) * page_size).limit(page_size))
        )
        total = session.scalar(select(func.count()).select_from(User).where(*filters))
        return users, int(total or 0)
    finally:
        session.close()


def create_user(
    *, actor: User, username: str, display_name: str, role: str, temporary_password: str
) -> User:
    _validate_role(role)
    normalized_username = normalize_username(username)
    normalized_display_name = display_name.strip()
    if (
        not normalized_username
        or not normalized_display_name
        or len(normalized_username) > USERNAME_MAX_LENGTH
        or len(normalized_display_name) > DISPLAY_NAME_MAX_LENGTH
    ):
        raise UserServiceError(
            "invalid_request", "The request body is missing required fields.", 400
        )
    validate_password_strength(temporary_password)

    for attempt in range(2):
        try:
            return _create_user_once(
                actor=actor,
                username=normalized_username,
                display_name=normalized_display_name,
                role=role,
                temporary_password=temporary_password,
            )
        except IntegrityError as error:
            if _database_error_code(error) == MYSQL_DUPLICATE_ENTRY and _confirmed_username_winner(
                normalized_username
            ):
                raise _duplicate_username_error() from None
            raise _user_creation_failed_error() from None
        except OperationalError as error:
            if _database_error_code(error) == MYSQL_DEADLOCK:
                if _confirmed_username_winner(normalized_username):
                    raise _duplicate_username_error() from None
                if attempt == 0:
                    continue
            raise _user_creation_failed_error() from None
        except SQLAlchemyError:
            raise _user_creation_failed_error() from None

    raise _user_creation_failed_error()


def update_user(
    *,
    actor: User,
    target: User,
    display_name: str | None,
    role: str | None,
    is_active: bool | None,
) -> User:
    if role is not None:
        _validate_role(role)
    if (
        display_name is not None
        and (not display_name.strip() or len(display_name.strip()) > DISPLAY_NAME_MAX_LENGTH)
    ):
        raise UserServiceError(
            "invalid_request", "The request body is missing required fields.", 400
        )
    if target.id == actor.id and is_active is False:
        raise UserServiceError(
            "self_disable_not_allowed", "You cannot disable your own account.", 400
        )

    session = db.session()
    try:
        with session.begin():
            current_target = session.get(User, target.id, with_for_update=True)
            if current_target is None:
                raise UserServiceError("user_not_found", "User was not found.", 404)

            invalidates_leadership = (
                role is not None and role not in {"admin", "project_lead"}
            ) or is_active is False
            if invalidates_leadership:
                led_project = session.scalar(
                    select(Project.id)
                    .where(
                        Project.leader_user_id == current_target.id,
                        Project.status.in_(NONTERMINAL_PROJECT_STATUSES),
                    )
                    .with_for_update()
                    .limit(1)
                )
                if led_project is not None:
                    raise UserServiceError(
                        "user_leads_active_projects",
                        "Transfer the user's non-terminal projects before changing "
                        "their role or disabling the account.",
                        409,
                    )

            invalidates_working_membership = role == "viewer" or is_active is False
            if invalidates_working_membership:
                working_membership = session.scalar(
                    select(ProjectMember.id)
                    .join(Project)
                    .where(
                        ProjectMember.user_id == current_target.id,
                        ProjectMember.role == "member",
                        Project.status.in_(NONTERMINAL_PROJECT_STATUSES),
                    )
                    .with_for_update()
                    .limit(1)
                )
                if working_membership is not None:
                    raise UserServiceError(
                        "user_has_active_project_memberships",
                        "Remove the user's non-terminal project memberships or "
                        "transfer leadership and reassign work before changing their "
                        "role or disabling the account.",
                        409,
                    )

            applied_changes: dict[str, Any] = {}
            if display_name is not None:
                normalized_display_name = display_name.strip()
                if normalized_display_name != current_target.display_name:
                    applied_changes["display_name"] = {
                        "from": current_target.display_name,
                        "to": normalized_display_name,
                    }
                current_target.display_name = normalized_display_name
            if role is not None:
                if role != current_target.role:
                    applied_changes["role"] = {
                        "from": current_target.role,
                        "to": role,
                    }
                current_target.role = role
            if is_active is not None:
                if is_active != current_target.is_active:
                    applied_changes["is_active"] = {
                        "from": current_target.is_active,
                        "to": is_active,
                    }
                current_target.is_active = is_active
                if not is_active:
                    _revoke_active_sessions(session, current_target.id)
                    current_target.auth_version += 1

            session.flush()
            session.refresh(current_target)
            if applied_changes:
                record_event(
                    session,
                    actor,
                    (
                        "user_deactivated"
                        if applied_changes.get("is_active", {}).get("to") is False
                        else "user_updated"
                    ),
                    current_target,
                    applied_changes,
                )
        return current_target
    finally:
        session.close()


def reset_password(*, target: User, temporary_password: str) -> User:
    validate_password_strength(temporary_password)
    session = db.session()
    try:
        with session.begin():
            current_target = session.get(User, target.id, with_for_update=True)
            if current_target is None:
                raise UserServiceError("user_not_found", "User was not found.", 404)

            _revoke_active_sessions(session, current_target.id)
            current_target.password_hash = hash_password(temporary_password)
            current_target.must_change_password = True
            current_target.auth_version += 1
            session.flush()
            session.refresh(current_target)
        return current_target
    finally:
        session.close()


def get_user(user_id: str) -> User:
    session = db.session()
    try:
        user = session.get(User, user_id)
        if user is None:
            raise UserServiceError("user_not_found", "User was not found.", 404)
        return user
    finally:
        session.close()


def _validate_role(role: str) -> None:
    if role not in VALID_ROLES:
        raise InvalidRoleError(f"unsupported role: {role}")


def _revoke_active_sessions(session, user_id: str) -> None:
    session.execute(
        update(RefreshSession)
        .where(
            RefreshSession.user_id == user_id,
            RefreshSession.revoked_at.is_(None),
        )
        .values(revoked_at=datetime.now(UTC))
    )


def _create_user_once(
    *, actor: User, username: str, display_name: str, role: str, temporary_password: str
) -> User:
    session = db.session()
    try:
        with session.begin():
            existing = session.scalar(
                select(User.id).where(User.username == username).with_for_update()
            )
            if existing is not None:
                raise _duplicate_username_error()
            user = User(
                username=username,
                display_name=display_name,
                role=role,
                password_hash=hash_password(temporary_password),
                must_change_password=True,
                is_active=True,
            )
            session.add(user)
            session.flush()
            session.refresh(user)
            record_event(
                session,
                actor,
                "user_created",
                user,
                {
                    "username": user.username,
                    "display_name": user.display_name,
                    "role": user.role,
                },
            )
        return user
    finally:
        session.close()


def _username_exists(username: str) -> bool:
    session = db.session()
    try:
        return session.scalar(select(User.id).where(User.username == username)) is not None
    finally:
        session.close()


def _confirmed_username_winner(username: str) -> bool:
    try:
        return _username_exists(username)
    except SQLAlchemyError:
        raise _user_creation_failed_error() from None


def _database_error_code(error: SQLAlchemyError) -> int | None:
    original = getattr(error, "orig", None)
    arguments = getattr(original, "args", ())
    return arguments[0] if arguments and isinstance(arguments[0], int) else None


def _duplicate_username_error() -> UserServiceError:
    return UserServiceError(
        "username_already_exists", "A user with this username already exists.", 409
    )


def _user_creation_failed_error() -> UserServiceError:
    return UserServiceError(
        "user_creation_failed", "Unable to create user at this time.", 503
    )
