from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from unicodedata import normalize
from uuid import uuid4

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Integer, String, text
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, validates
from sqlalchemy.types import TypeDecorator


ROLE_ADMIN = "admin"
ROLE_PROJECT_LEAD = "project_lead"
ROLE_FDE_ENGINEER = "fde_engineer"
ROLE_VIEWER = "viewer"
VALID_ROLES = frozenset(
    {ROLE_ADMIN, ROLE_PROJECT_LEAD, ROLE_FDE_ENGINEER, ROLE_VIEWER}
)


class InvalidRoleError(ValueError):
    """Raised when application code attempts to assign an unsupported user role."""


class UTCDateTime(TypeDecorator[datetime]):
    """Persist UTC datetimes in MySQL while restoring timezone information on read."""

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value: datetime | None, _: Any) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("datetime values must be timezone-aware")
        return value.astimezone(UTC).replace(tzinfo=None)

    def process_result_value(self, value: datetime | None, _: Any) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)


class UTCTimestamp(UTCDateTime):
    """Use MySQL's UTC-normalized TIMESTAMP storage for auto-updated values."""

    impl = mysql.TIMESTAMP
    cache_ok = True

    def load_dialect_impl(self, dialect: Any) -> Any:
        return dialect.type_descriptor(mysql.TIMESTAMP(fsp=6))


class Base(DeclarativeBase):
    pass


UTC_TIMESTAMP_SQL = text("UTC_TIMESTAMP(6)")
CURRENT_TIMESTAMP_SQL = text("CURRENT_TIMESTAMP(6)")


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint(
            "role IN ('admin', 'project_lead', 'fde_engineer', 'viewer')",
            name="ck_users_role",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    username: Mapped[str] = mapped_column(String(120), nullable=False, unique=True)
    display_name: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    role: Mapped[str] = mapped_column(String(32), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    must_change_password: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    auth_version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default=text("1")
    )
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), nullable=False, server_default=UTC_TIMESTAMP_SQL
    )
    updated_at: Mapped[datetime] = mapped_column(
        UTCTimestamp(),
        nullable=False,
        server_default=CURRENT_TIMESTAMP_SQL,
        server_onupdate=CURRENT_TIMESTAMP_SQL,
    )

    refresh_sessions: Mapped[list[RefreshSession]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
    )

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        if self.id is None:
            self.id = str(uuid4())
        if self.auth_version is None:
            self.auth_version = 1

    @validates("username")
    def normalize_username(self, _: str, value: str) -> str:
        return normalize("NFKC", value).strip().lower()

    @validates("role")
    def validate_role(self, _: str, value: str) -> str:
        if value not in VALID_ROLES:
            raise InvalidRoleError(f"unsupported role: {value}")
        return value


class RefreshSession(Base):
    __tablename__ = "refresh_sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    token_digest: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), nullable=False, server_default=UTC_TIMESTAMP_SQL
    )
    last_used_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    device_label: Mapped[str] = mapped_column(String(255), nullable=False, default="")

    user: Mapped[User] = relationship(back_populates="refresh_sessions")

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        if self.id is None:
            self.id = str(uuid4())
