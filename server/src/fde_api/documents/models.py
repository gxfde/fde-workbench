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
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from fde_api.auth.models import UTCDateTime, User
from fde_api.files.models import BUSINESS_CATEGORIES, ProjectFileVersion
from fde_api.workbench.models import (
    Base,
    TimestampMixin,
    VersionedMixin,
    Project,
    new_uuid,
)

DOCUMENT_VERSION_SOURCES = ("generated", "online_revised", "manual_upload")
DOCUMENT_STATES = ("draft", "confirmed", "archived")
DOCUMENT_TEMPLATE_STATUSES = ("active", "inactive")
DOCUMENT_TEMPLATE_VERSION_STATUSES = ("draft", "published", "inactive")
DOCUMENT_GENERATION_STATUSES = ("queued", "running", "succeeded", "failed", "cancelled")

# Canonical document categories supported by the document engine.
DOCUMENT_TYPE_KEYS = (
    "research_result",
    "project_plan_progress",
    "prediagnosis",
    "job_description",
    "job_questionnaire",
    "shadowing_record",
    "process_system_map",
    "ai_opportunity_score",
    "scenario_decision",
    "pov_plan",
    "pov_report",
    "sow",
    "weekly_issue",
    "change_request",
    "acceptance",
    "training_handover",
    "contract",
)


class DocumentTemplate(Base, TimestampMixin, VersionedMixin):
    """A document type root with a stable type key and published version pointer."""

    __tablename__ = "document_templates"
    __table_args__ = (
        CheckConstraint(
            "status IN ('active', 'inactive')",
            name="ck_document_templates_status",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    document_type: Mapped[str] = mapped_column(String(80), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    industry_name: Mapped[str] = mapped_column(String(160), nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="active", server_default="active"
    )
    latest_published_version_number: Mapped[int | None] = mapped_column(Integer)

    versions: Mapped[list[DocumentTemplateVersion]] = relationship(
        back_populates="template", passive_deletes=True
    )


class DocumentTemplateVersion(Base, TimestampMixin, VersionedMixin):
    """An immutable declarative mapping plus the source DOCX binary reference."""

    __tablename__ = "document_template_versions"
    __table_args__ = (
        UniqueConstraint(
            "template_id",
            "version_number",
            name="uq_document_template_versions_template_version",
        ),
        CheckConstraint(
            "version_number >= 1", name="ck_document_template_versions_number"
        ),
        CheckConstraint(
            "status IN ('draft', 'published', 'inactive')",
            name="ck_document_template_versions_status",
        ),
        Index("ix_document_template_versions_template_id", "template_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    template_id: Mapped[str] = mapped_column(
        ForeignKey("document_templates.id", ondelete="RESTRICT"), nullable=False
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="draft", server_default="draft"
    )
    docx_file_version_id: Mapped[str | None] = mapped_column(
        ForeignKey("project_file_versions.id", ondelete="RESTRICT")
    )
    # System-level template assets are stored directly on the template version.
    # ``docx_file_version_id`` is retained only as a nullable legacy bridge for
    # rolling upgrades; new uploads never create project files.
    docx_original_filename: Mapped[str | None] = mapped_column(String(255))
    docx_mime_type: Mapped[str | None] = mapped_column(String(120))
    docx_bucket: Mapped[str | None] = mapped_column(String(63))
    docx_storage_key: Mapped[str | None] = mapped_column(String(512))
    docx_size_bytes: Mapped[int | None] = mapped_column(BigInteger)
    docx_etag: Mapped[str | None] = mapped_column(String(128))
    mapping_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    sections_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    table_loops_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    required_data_json: Mapped[dict[str, Any]] = mapped_column(
        JSON, nullable=False, default=dict
    )
    source_sha256: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    created_by_user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    published_by_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT")
    )
    published_at: Mapped[datetime | None] = mapped_column(UTCDateTime())

    template: Mapped[DocumentTemplate] = relationship(back_populates="versions")
    docx_file: Mapped[ProjectFileVersion | None] = relationship(
        foreign_keys=[docx_file_version_id]
    )
    created_by: Mapped[User] = relationship(foreign_keys=[created_by_user_id])
    published_by: Mapped[User | None] = relationship(
        foreign_keys=[published_by_user_id]
    )


class ProjectDocument(Base, TimestampMixin, VersionedMixin):
    """A project-scoped document identity with an immutable version chain."""

    __tablename__ = "project_documents"
    __table_args__ = (
        UniqueConstraint(
            "project_id",
            "business_code",
            name="uq_project_documents_project_business_code",
        ),
        CheckConstraint(
            "status IN ('draft', 'confirmed', 'archived')",
            name="ck_project_documents_status",
        ),
        CheckConstraint(
            "business_category IS NULL OR business_category IN "
            "('商务合约', '预调研', '调研', 'PoV验证', '生产部署', '培训预交接')",
            name="ck_project_documents_business_category",
        ),
        Index("ix_project_documents_project_status", "project_id", "status"),
        Index("ix_project_documents_document_type", "document_type"),
        Index("ix_project_documents_source_opportunity", "source_opportunity_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False
    )
    document_type: Mapped[str] = mapped_column(String(80), nullable=False)
    business_code: Mapped[str] = mapped_column(String(80), nullable=False)
    business_category: Mapped[str | None] = mapped_column(String(32), nullable=True)
    current_version_id: Mapped[str | None] = mapped_column(
        ForeignKey("project_document_versions.id", ondelete="RESTRICT", use_alter=True)
    )
    library_file_id: Mapped[str | None] = mapped_column(
        ForeignKey("project_files.id", ondelete="RESTRICT")
    )
    source_template_version_id: Mapped[str] = mapped_column(
        ForeignKey("document_template_versions.id", ondelete="RESTRICT"), nullable=False
    )
    source_opportunity_id: Mapped[str | None] = mapped_column(
        ForeignKey("project_research_subjects.id", ondelete="RESTRICT")
    )
    opportunity_scope_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="draft", server_default="draft"
    )
    owner_user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )

    project: Mapped[Project] = relationship(foreign_keys=[project_id])
    owner: Mapped[User] = relationship(foreign_keys=[owner_user_id])
    source_template_version: Mapped[DocumentTemplateVersion] = relationship(
        foreign_keys=[source_template_version_id]
    )
    current_version: Mapped[ProjectDocumentVersion | None] = relationship(
        foreign_keys=[current_version_id],
        post_update=True,
    )
    versions: Mapped[list[ProjectDocumentVersion]] = relationship(
        back_populates="document",
        foreign_keys="ProjectDocumentVersion.document_id",
        passive_deletes=True,
    )
    draft: Mapped[ProjectDocumentDraft | None] = relationship(
        back_populates="document",
        passive_deletes=True,
    )


class ProjectDocumentDraft(Base, TimestampMixin):
    """Structured, editor-authored content for the current document draft."""

    __tablename__ = "project_document_drafts"
    __table_args__ = (
        UniqueConstraint(
            "document_id", name="uq_project_document_drafts_document"
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    document_id: Mapped[str] = mapped_column(
        ForeignKey("project_documents.id", ondelete="RESTRICT"), nullable=False
    )
    field_overrides_json: Mapped[dict[str, Any]] = mapped_column(
        JSON, nullable=False, default=dict
    )
    rich_text_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    list_selections_json: Mapped[dict[str, Any]] = mapped_column(
        JSON, nullable=False, default=dict
    )
    version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default=text("1")
    )

    document: Mapped[ProjectDocument] = relationship(back_populates="draft")


class ProjectDocumentVersion(Base, TimestampMixin):
    """One immutable document output referencing its source snapshot and DOCX binary."""

    __tablename__ = "project_document_versions"
    __table_args__ = (
        UniqueConstraint(
            "document_id",
            "version_number",
            name="uq_project_document_versions_document_version",
        ),
        CheckConstraint(
            "version_number >= 1", name="ck_project_document_versions_number"
        ),
        CheckConstraint(
            "source IN ('generated', 'online_revised', 'manual_upload')",
            name="ck_project_document_versions_source",
        ),
        CheckConstraint(
            "status IN ('draft', 'confirmed', 'archived')",
            name="ck_project_document_versions_status",
        ),
        Index("ix_project_document_versions_document_id", "document_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    document_id: Mapped[str] = mapped_column(
        ForeignKey("project_documents.id", ondelete="RESTRICT"), nullable=False
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    source: Mapped[str] = mapped_column(
        String(24), nullable=False, default="generated", server_default="generated"
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="draft", server_default="draft"
    )
    parent_version_id: Mapped[str | None] = mapped_column(
        ForeignKey("project_document_versions.id", ondelete="RESTRICT")
    )
    source_template_version_id: Mapped[str] = mapped_column(
        ForeignKey("document_template_versions.id", ondelete="RESTRICT"), nullable=False
    )
    source_snapshot_json: Mapped[dict[str, Any]] = mapped_column(
        JSON, nullable=False, default=dict
    )
    content_snapshot_json: Mapped[dict[str, Any]] = mapped_column(
        JSON, nullable=False, default=dict
    )
    docx_file_version_id: Mapped[str] = mapped_column(
        ForeignKey("project_file_versions.id", ondelete="RESTRICT"), nullable=False
    )
    preview_file_version_id: Mapped[str | None] = mapped_column(
        ForeignKey("project_file_versions.id", ondelete="RESTRICT")
    )
    sha256: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    generated_by_user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    confirmed_by_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT")
    )
    confirmed_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    generation_error: Mapped[str] = mapped_column(Text, nullable=False, default="")

    document: Mapped[ProjectDocument] = relationship(
        back_populates="versions", foreign_keys=[document_id]
    )
    parent_version: Mapped[ProjectDocumentVersion | None] = relationship(
        foreign_keys=[parent_version_id], remote_side=[id]
    )
    source_template_version: Mapped[DocumentTemplateVersion] = relationship(
        foreign_keys=[source_template_version_id]
    )
    docx_file: Mapped[ProjectFileVersion] = relationship(
        foreign_keys=[docx_file_version_id]
    )
    preview_file: Mapped[ProjectFileVersion | None] = relationship(
        foreign_keys=[preview_file_version_id]
    )
    generated_by: Mapped[User] = relationship(foreign_keys=[generated_by_user_id])
    confirmed_by: Mapped[User | None] = relationship(foreign_keys=[confirmed_by_user_id])
    generation_jobs: Mapped[list[DocumentGenerationJob]] = relationship(
        back_populates="document_version", passive_deletes=True
    )


class DocumentGenerationJob(Base, TimestampMixin, VersionedMixin):
    """An async generation attempt for one document version.

    The single-active-job-per-target rule is deliberately NOT a database
    uniqueness constraint: active jobs are tracked by status so the service
    layer can decide which transitions free the slot. This keeps the DB clean
    while still allowing the service to enqueue at most one active job per
    document version.
    """

    __tablename__ = "document_generation_jobs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('queued', 'running', 'succeeded', 'failed', 'cancelled')",
            name="ck_document_generation_jobs_status",
        ),
        CheckConstraint("attempts >= 0", name="ck_document_generation_jobs_attempts"),
        Index(
            "ix_document_generation_jobs_document_version_status",
            "document_version_id",
            "status",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    document_version_id: Mapped[str] = mapped_column(
        ForeignKey("project_document_versions.id", ondelete="RESTRICT"), nullable=False
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="queued", server_default="queued"
    )
    attempts: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    last_error: Mapped[str] = mapped_column(Text, nullable=False, default="")

    document_version: Mapped[ProjectDocumentVersion] = relationship(
        back_populates="generation_jobs"
    )
