from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from fde_api.auth.models import UTCDateTime, User
from fde_api.workbench.models import (
    Base,
    TimestampMixin,
    VersionedMixin,
    Project,
    new_uuid,
)

FILE_CATEGORIES = ("attachment", "document")
# The fixed business stages a project file/document can be classified into.
# ``None``/empty means uncategorized (未分类). ``_UNCATEGORIZED_LABEL`` is the
# filter token used by the list endpoints, not a stored column value.
BUSINESS_CATEGORIES = (
    "商务合约",
    "预调研",
    "调研",
    "PoV验证",
    "生产部署",
    "培训预交接",
)
BUSINESS_CATEGORY_UNCATEGORIZED_LABEL = "未分类"
PROJECT_FILE_STATUSES = ("active", "archived")
FILE_VERSION_STATUSES = (
    "uploading", "quarantined", "available", "deprecated", "rejected", "failed"
)
FILE_VERSION_SOURCES = ("upload", "manual_upload", "system_generated", "preview")
FILE_VERSION_SCAN_STATUSES = (
    "pending",
    "scanning",
    "clean",
    "infected",
    "error",
    "not_required",
)
FILE_VERSION_PREVIEW_STATUSES = ("none", "pending", "ready", "failed")
UPLOAD_SESSION_STATUSES = ("uploading", "completed", "aborted", "expired")


class ProjectFile(Base, TimestampMixin, VersionedMixin):
    """A project-scoped file identity with an immutable version chain."""

    __tablename__ = "project_files"
    __table_args__ = (
        UniqueConstraint(
            "project_id",
            "category",
            "display_name",
            name="uq_project_files_project_category_name",
        ),
        CheckConstraint(
            "category IN ('attachment', 'document')",
            name="ck_project_files_category",
        ),
        CheckConstraint(
            "business_category IS NULL OR business_category IN "
            "('商务合约', '预调研', '调研', 'PoV验证', '生产部署', '培训预交接')",
            name="ck_project_files_business_category",
        ),
        CheckConstraint("status IN ('active', 'archived')", name="ck_project_files_status"),
        Index("ix_project_files_project_id", "project_id"),
        Index("ix_project_files_project_status", "project_id", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False
    )
    category: Mapped[str] = mapped_column(
        String(32), nullable=False, default="attachment"
    )
    business_category: Mapped[str | None] = mapped_column(String(32), nullable=True)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    tags_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    current_version_id: Mapped[str | None] = mapped_column(
        ForeignKey("project_file_versions.id", ondelete="RESTRICT", use_alter=True)
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="active", server_default="active"
    )
    created_by_user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )

    created_by: Mapped[User] = relationship(foreign_keys=[created_by_user_id])
    project: Mapped[Project] = relationship()
    current_version: Mapped[ProjectFileVersion | None] = relationship(
        foreign_keys=[current_version_id], post_update=True
    )
    versions: Mapped[list[ProjectFileVersion]] = relationship(
        back_populates="project_file",
        foreign_keys="ProjectFileVersion.file_id",
        passive_deletes=True,
    )


class ProjectFileVersion(Base, TimestampMixin):
    """One immutable version of a project file."""

    __tablename__ = "project_file_versions"
    __table_args__ = (
        UniqueConstraint(
            "file_id", "version_number", name="uq_project_file_versions_file_version"
        ),
        CheckConstraint("version_number >= 1", name="ck_project_file_versions_number"),
        CheckConstraint(
            "status IN ('uploading', 'quarantined', 'available', 'deprecated', 'rejected', 'failed')",
            name="ck_project_file_versions_status",
        ),
        CheckConstraint(
            "scan_status IN "
            "('pending', 'scanning', 'clean', 'infected', 'error', 'not_required')",
            name="ck_project_file_versions_scan_status",
        ),
        CheckConstraint(
            "preview_status IN ('none', 'pending', 'ready', 'failed')",
            name="ck_project_file_versions_preview_status",
        ),
        Index("ix_project_file_versions_file_id", "file_id"),
        Index("ix_project_file_versions_status", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    file_id: Mapped[str] = mapped_column(
        ForeignKey("project_files.id", ondelete="RESTRICT"), nullable=False
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    source: Mapped[str] = mapped_column(String(24), nullable=False, default="upload")
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    safe_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    extension: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    mime_type: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    bucket: Mapped[str] = mapped_column(String(63), nullable=False)
    storage_key: Mapped[str] = mapped_column(String(512), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    etag: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    sha256: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    scan_status: Mapped[str] = mapped_column(
        String(24), nullable=False, default="pending", server_default="pending"
    )
    preview_status: Mapped[str] = mapped_column(
        String(24), nullable=False, default="none", server_default="none"
    )
    preview_version_id: Mapped[str | None] = mapped_column(
        ForeignKey("project_file_versions.id", ondelete="RESTRICT")
    )
    uploaded_by_user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    parent_version_id: Mapped[str | None] = mapped_column(
        ForeignKey("project_file_versions.id", ondelete="RESTRICT")
    )
    deprecated_by_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT")
    )
    deprecated_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    deprecation_reason: Mapped[str] = mapped_column(Text, nullable=False, default="")
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="uploading", server_default="uploading"
    )

    project_file: Mapped[ProjectFile] = relationship(
        back_populates="versions", foreign_keys=[file_id]
    )
    uploaded_by: Mapped[User] = relationship(foreign_keys=[uploaded_by_user_id])
    deprecated_by: Mapped[User | None] = relationship(
        foreign_keys=[deprecated_by_user_id]
    )
    parent_version: Mapped[ProjectFileVersion | None] = relationship(
        foreign_keys=[parent_version_id], remote_side=[id]
    )
    preview_version: Mapped[ProjectFileVersion | None] = relationship(
        foreign_keys=[preview_version_id], remote_side=[id]
    )


class UploadSession(Base, TimestampMixin):
    """A multipart upload intent bound to one project and idempotency key."""

    __tablename__ = "upload_sessions"
    __table_args__ = (
        UniqueConstraint(
            "project_id", "idempotency_key", name="uq_upload_sessions_project_idempotency"
        ),
        CheckConstraint(
            "status IN ('uploading', 'completed', 'aborted', 'expired')",
            name="ck_upload_sessions_status",
        ),
        Index("ix_upload_sessions_project_status", "project_id", "status"),
        Index("ix_upload_sessions_expires_at", "expires_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False
    )
    file_id: Mapped[str | None] = mapped_column(
        ForeignKey("project_files.id", ondelete="RESTRICT")
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    expected_size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    expected_mime_type: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    bucket: Mapped[str] = mapped_column(String(63), nullable=False)
    storage_prefix: Mapped[str] = mapped_column(String(512), nullable=False)
    multipart_upload_id: Mapped[str] = mapped_column(String(128), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="uploading", server_default="uploading"
    )
    requested_by_user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    idempotency_key: Mapped[str] = mapped_column(String(64), nullable=False)
    completion_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)

    requested_by: Mapped[User] = relationship(foreign_keys=[requested_by_user_id])
    project: Mapped[Project] = relationship()
