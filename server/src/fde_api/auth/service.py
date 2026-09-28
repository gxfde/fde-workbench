from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from unicodedata import normalize

from flask import current_app
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from fde_api.auth.models import RefreshSession, User
from fde_api.auth.limits import (
    DEVICE_LABEL_MAX_LENGTH,
    PASSWORD_MAX_LENGTH,
    USERNAME_MAX_LENGTH,
)
from fde_api.auth.passwords import hash_password, verify_password
from fde_api.auth.tokens import issue_access_token, new_refresh_token
from fde_api.config import Settings
from fde_api.extensions import db


@dataclass(frozen=True)
class TokenPair:
    access_token: str
    refresh_token: str
    access_expires_at: datetime
    refresh_expires_at: datetime


class AuthServiceError(Exception):
    def __init__(self, code: str, message: str, status: int):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


INVALID_CREDENTIALS = (
    "invalid_credentials",
    "Invalid username or password.",
    401,
)
REFRESH_TOKEN_INVALID = (
    "refresh_token_invalid",
    "Refresh token is invalid or expired.",
    401,
)
PASSWORD_POLICY_MESSAGE = "Password must be at least 6 characters."
INVALID_CURRENT_PASSWORD = (
    "invalid_password",
    "The current password is incorrect.",
    400,
)

# Verifying this hash when the username is unknown keeps the credential-failure
# path equivalent without retaining or logging the submitted password.
_DUMMY_PASSWORD_HASH = hash_password("TimingOnly-Dummy-Password!1")


def normalize_username(username: str) -> str:
    return normalize("NFKC", username).strip().lower()


def validate_username(username: str) -> str:
    normalized = normalize_username(username)
    if not normalized or len(normalized) > USERNAME_MAX_LENGTH:
        raise _invalid_credential_request()
    return normalized


def validate_password_length(password: str) -> None:
    if not password or len(password) > PASSWORD_MAX_LENGTH:
        raise _invalid_credential_request()


def validate_password_strength(password: str) -> None:
    validate_password_length(password)
    if len(password) < 6:
        raise AuthServiceError("password_too_weak", PASSWORD_POLICY_MESSAGE, 400)


def login(username: str, password: str, device_label: str) -> tuple[User, TokenPair]:
    normalized_username = validate_username(username)
    validate_password_length(password)
    if not device_label.strip() or len(device_label) > DEVICE_LABEL_MAX_LENGTH:
        raise _invalid_credential_request()
    session = db.session()
    try:
        with session.begin():
            user = session.scalar(
                select(User)
                .where(User.username == normalized_username)
                .with_for_update()
            )
            hash_value = user.password_hash if user is not None else _DUMMY_PASSWORD_HASH
            password_matches = verify_password(hash_value, password)
            if user is None or not password_matches:
                raise AuthServiceError(*INVALID_CREDENTIALS)
            if not user.is_active:
                raise AuthServiceError("account_inactive", "This account is inactive.", 403)

            pair = _issue_token_pair(session, user, device_label)
        return user, pair
    finally:
        session.close()


def rotate_refresh_token(raw_token: str) -> tuple[User, TokenPair]:
    token_digest = _digest_refresh_token(raw_token)
    user_id = _refresh_user_id(token_digest)
    if user_id is None:
        raise AuthServiceError(*REFRESH_TOKEN_INVALID)

    now = datetime.now(UTC)
    session = db.session()
    try:
        with session.begin():
            user = session.get(User, user_id, with_for_update=True)
            if user is None:
                raise AuthServiceError(*REFRESH_TOKEN_INVALID)

            refresh_session = session.scalar(
                select(RefreshSession)
                .where(
                    RefreshSession.token_digest == token_digest,
                    RefreshSession.user_id == user_id,
                )
                .with_for_update()
            )
            if (
                refresh_session is None
                or refresh_session.revoked_at is not None
                or refresh_session.expires_at <= now
            ):
                raise AuthServiceError(*REFRESH_TOKEN_INVALID)
            if not user.is_active:
                raise AuthServiceError("account_inactive", "This account is inactive.", 403)

            refresh_session.revoked_at = now
            refresh_session.last_used_at = now
            pair = _issue_token_pair(session, user, refresh_session.device_label)

        return user, pair
    finally:
        session.close()


def revoke_refresh_token(raw_token: str) -> None:
    token_digest = _digest_refresh_token(raw_token)
    user_id = _refresh_user_id(token_digest)
    if user_id is None:
        return

    now = datetime.now(UTC)
    session = db.session()
    try:
        with session.begin():
            user = session.get(User, user_id, with_for_update=True)
            if user is None:
                return

            refresh_session = session.scalar(
                select(RefreshSession)
                .where(
                    RefreshSession.token_digest == token_digest,
                    RefreshSession.user_id == user_id,
                )
                .with_for_update()
            )
            if refresh_session is not None and refresh_session.revoked_at is None:
                refresh_session.revoked_at = now
    finally:
        session.close()


def change_password(
    user: User, current_password: str, new_password: str
) -> tuple[User, TokenPair]:
    validate_password_length(current_password)
    validate_password_strength(new_password)
    now = datetime.now(UTC)
    session = db.session()
    try:
        with session.begin():
            current_user = session.get(User, user.id, with_for_update=True)
            if current_user is None or not current_user.is_active:
                raise AuthServiceError("account_inactive", "This account is inactive.", 403)
            if not verify_password(current_user.password_hash, current_password):
                raise AuthServiceError(*INVALID_CREDENTIALS)

            session.execute(
                update(RefreshSession)
                .where(
                    RefreshSession.user_id == current_user.id,
                    RefreshSession.revoked_at.is_(None),
                )
                .values(revoked_at=now)
            )
            current_user.password_hash = hash_password(new_password)
            current_user.must_change_password = False
            current_user.auth_version += 1
            pair = _issue_token_pair(session, current_user, "Password change")

        return current_user, pair
    finally:
        session.close()


def verify_current_password(user: User, password: str) -> bool:
    """Return whether ``password`` matches the current user's stored hash."""
    validate_password_length(password)
    return verify_password(user.password_hash, password)


def _issue_token_pair(session: Session, user: User, device_label: str) -> TokenPair:
    settings = _settings()
    now = datetime.now(UTC)
    access_expires_at = now + timedelta(minutes=settings.access_token_minutes)
    refresh_expires_at = now + timedelta(days=settings.refresh_token_days)
    raw_refresh_token, token_digest = new_refresh_token()
    session.add(
        RefreshSession(
            user_id=user.id,
            token_digest=token_digest,
            expires_at=refresh_expires_at,
            device_label=device_label,
        )
    )
    return TokenPair(
        access_token=issue_access_token(user, settings),
        refresh_token=raw_refresh_token,
        access_expires_at=access_expires_at,
        refresh_expires_at=refresh_expires_at,
    )


def _digest_refresh_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def _refresh_user_id(token_digest: str) -> str | None:
    lookup_session = db.session()
    try:
        return lookup_session.scalar(
            select(RefreshSession.user_id).where(
                RefreshSession.token_digest == token_digest
            )
        )
    finally:
        lookup_session.close()


def _settings() -> Settings:
    return current_app.config["SETTINGS"]


def _invalid_credential_request() -> AuthServiceError:
    return AuthServiceError("invalid_request", "The credential input is invalid.", 400)
