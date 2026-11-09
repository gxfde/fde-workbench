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
from fde_api.auth.service import (
    AuthServiceError,
    normalize_username,
    validate_password_strength,
)
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
# v0.2 (PG 迁移): 原为 MySQL 错误码。改为跨方言：
#   MySQL 1062 = duplicate entry   / 1213 = deadlock
#   PG  23505 = unique_violation   / 40P01 = deadlock_detected
MYSQL_DUPLICATE_ENTRY = 1062
MYSQL_DEADLOCK = 1213
PG_DUPLICATE_ENTRY = "23505"
PG_DEADLOCK = "40P01"
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
            if _is_duplicate_entry(error) and _confirmed_username_winner(
                normalized_username
            ):
                raise _duplicate_username_error() from None
            raise _user_creation_failed_error() from None
        except OperationalError as error:
            if _is_deadlock(error):
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


def _database_error_code(error: SQLAlchemyError) -> int | str | None:
    """跨方言取原始驱动错误码。

    v0.2 (PG 迁移): 原实现只认 int（MySQL）。psycopg3 的 SQLSTATE 在
    ``orig.sqlstate`` 属性上（args 只有消息文本，psycopg2 才放 args[0]），
    不读属性会静默丢弃 → PG 上唯一约束冲突不再被识别为「用户名重复」。
    """
    original = getattr(error, "orig", None)
    if original is None:
        return None
    sqlstate = getattr(original, "sqlstate", None)
    if sqlstate is not None:
        return sqlstate
    arguments = getattr(original, "args", ())
    if not arguments:
        return None
    code = arguments[0]
    return code if isinstance(code, (int, str)) else None


def _is_duplicate_entry(error: SQLAlchemyError) -> bool:
    """唯一约束冲突（MySQL 1062 / PG 23505）。"""
    code = _database_error_code(error)
    return code == MYSQL_DUPLICATE_ENTRY or code == PG_DUPLICATE_ENTRY


def _is_deadlock(error: SQLAlchemyError) -> bool:
    """死锁（MySQL 1213 / PG 40P01）。"""
    code = _database_error_code(error)
    return code == MYSQL_DEADLOCK or code == PG_DEADLOCK


def _duplicate_username_error() -> UserServiceError:
    return UserServiceError(
        "username_already_exists", "A user with this username already exists.", 409
    )


def _user_creation_failed_error() -> UserServiceError:
    return UserServiceError(
        "user_creation_failed", "Unable to create user at this time.", 503
    )


def register_self_service_user(
    session: Any, *, username: str, display_name: str, password: str
) -> User:
    """企业自助注册账号（商业化 G6；**当事人自证**，无 admin actor，ADR-010）。

    与 ``create_user`` 的差异：密码由当事人自选（非临时密码 ⇒
    ``must_change_password=False``）；平台权限角色固定 ``viewer``（最低档——
    商业自助面的鉴权按绑定账号判定，不靠平台角色提权）；创建事件由商业域
    以当事人为 actor 落 ``operation_events``（本原语只管账号行，调用方持有
    同一事务——账号/主体/额度/身份分层要么全成要么全败）。
    """
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
    try:
        validate_password_strength(password)
    except AuthServiceError as error:
        raise UserServiceError(error.code, error.message, error.status) from None
    existing = session.scalar(
        select(User.id).where(User.username == normalized_username).with_for_update()
    )
    if existing is not None:
        raise _duplicate_username_error()
    user = User(
        username=normalized_username,
        display_name=normalized_display_name,
        role="viewer",
        password_hash=hash_password(password),
        must_change_password=False,
        is_active=True,
    )
    session.add(user)
    try:
        session.flush()
    except IntegrityError:
        # 并发同名校验兜底：唯一约束在库层兜底（SELECT 抢先窗口）
        raise _duplicate_username_error() from None
    return user
