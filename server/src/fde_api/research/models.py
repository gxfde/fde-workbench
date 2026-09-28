from __future__ import annotations

from typing import Any, TypeAlias
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    event,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from fde_api.auth.models import User
from fde_api.workbench.models import Base, TimestampMixin, VersionedMixin, new_uuid


SUBJECT_TYPES = ("project", "department", "role", "process", "opportunity")
FIELD_TYPES = (
    "short_text",
    "long_text",
    "rich_text",
    "integer",
    "decimal",
    "date",
    "single_choice",
    "multi_choice",
    "table",
    "file_reference",
)
ResearchJSON: TypeAlias = str | int | float | bool | None | list[Any] | dict[str, Any]
FIELD_TYPE_CHECK_SQL = "field_type IN (" + ", ".join(
    f"'{field_type}'" for field_type in FIELD_TYPES
) + ")"


class ResearchImmutableError(ValueError):
    """Raised when code attempts to alter a confirmed research revision."""


class ResearchSubjectLinkOwnershipError(ValueError):
    """Raised when a subject link spans projects or declares the wrong project."""


def assert_revision_mutable(revision: ProjectResearchFormRevision) -> None:
    if revision.status == "confirmed":
        raise ResearchImmutableError("confirmed research revisions are immutable")


class TemplateResearchForm(Base, TimestampMixin):
    __tablename__ = "template_research_forms"
    __table_args__ = (
        UniqueConstraint(
            "template_version_id",
            "form_key",
            name="uq_template_research_forms_version_key",
        ),
        CheckConstraint(
            "subject_type IN ('project', 'department', 'role', 'process', 'opportunity')",
            name="ck_template_research_forms_subject_type",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    template_version_id: Mapped[str] = mapped_column(
        ForeignKey("industry_template_versions.id", ondelete="RESTRICT"), nullable=False
    )
    form_key: Mapped[str] = mapped_column(String(100), nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    subject_type: Mapped[str] = mapped_column(String(32), nullable=False)
    module_key: Mapped[str | None] = mapped_column(String(80))
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    template_version: Mapped["IndustryTemplateVersion"] = relationship(
        back_populates="research_forms"
    )
    sections: Mapped[list[TemplateResearchSection]] = relationship(
        back_populates="form", passive_deletes=True
    )
    project_forms: Mapped[list[ProjectResearchForm]] = relationship(
        back_populates="source_template_form", passive_deletes=True
    )


class TemplateResearchSection(Base, TimestampMixin):
    __tablename__ = "template_research_sections"
    __table_args__ = (
        UniqueConstraint(
            "form_id", "section_key", name="uq_template_research_sections_form_key"
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    form_id: Mapped[str] = mapped_column(
        ForeignKey("template_research_forms.id", ondelete="RESTRICT"), nullable=False
    )
    section_key: Mapped[str] = mapped_column(String(100), nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    form: Mapped[TemplateResearchForm] = relationship(back_populates="sections")
    fields: Mapped[list[TemplateResearchField]] = relationship(
        back_populates="section", passive_deletes=True
    )


class TemplateResearchField(Base, TimestampMixin):
    __tablename__ = "template_research_fields"
    __table_args__ = (
        UniqueConstraint(
            "section_id", "field_key", name="uq_template_research_fields_section_key"
        ),
        CheckConstraint(
            FIELD_TYPE_CHECK_SQL,
            name="ck_template_research_fields_field_type",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    section_id: Mapped[str] = mapped_column(
        ForeignKey("template_research_sections.id", ondelete="RESTRICT"), nullable=False
    )
    field_key: Mapped[str] = mapped_column(String(100), nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    help_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    field_type: Mapped[str] = mapped_column(
        String(32), nullable=False, default="short_text"
    )
    is_required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    options_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    section: Mapped[TemplateResearchSection] = relationship(back_populates="fields")
    answers: Mapped[list[ProjectResearchAnswer]] = relationship(
        back_populates="source_template_field", passive_deletes=True
    )


class ProjectResearchSubject(Base, TimestampMixin, VersionedMixin):
    __tablename__ = "project_research_subjects"
    __table_args__ = (
        UniqueConstraint(
            "project_id", "subject_key", name="uq_project_research_subjects_project_key"
        ),
        UniqueConstraint(
            "project_id", "id", name="uq_project_research_subjects_project_id"
        ),
        UniqueConstraint(
            "project_id",
            "tracking_code",
            name="uq_project_research_subjects_project_tracking_code",
        ),
        CheckConstraint(
            "subject_type IN ('project', 'department', 'role', 'process', 'opportunity')",
            name="ck_project_research_subjects_subject_type",
        ),
        CheckConstraint(
            "version >= 1", name="ck_project_research_subjects_version"
        ),
        CheckConstraint(
            "status IN ('active', 'archived')",
            name="ck_project_research_subjects_status",
        ),
        ForeignKeyConstraint(
            ["project_id", "parent_subject_id"],
            ["project_research_subjects.project_id", "project_research_subjects.id"],
            name="fk_project_research_subjects_parent",
            ondelete="RESTRICT",
        ),
        Index("ix_project_research_subjects_project_id", "project_id"),
        Index("ix_project_research_subjects_subject_type", "subject_type"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False
    )
    parent_subject_id: Mapped[str | None] = mapped_column(String(36))
    subject_type: Mapped[str] = mapped_column(String(32), nullable=False)
    subject_key: Mapped[str] = mapped_column(String(100), nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    memo: Mapped[str] = mapped_column(Text, nullable=False, default="")
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    tracking_code: Mapped[str | None] = mapped_column(String(40))

    project: Mapped["Project"] = relationship(back_populates="research_subjects")
    forms: Mapped[list[ProjectResearchForm]] = relationship(
        back_populates="subject",
        passive_deletes=True,
        overlaps="project,research_forms",
    )
    outgoing_links: Mapped[list[ProjectResearchSubjectLink]] = relationship(
        back_populates="source_subject",
        foreign_keys="ProjectResearchSubjectLink.source_subject_id",
        passive_deletes=True,
    )
    incoming_links: Mapped[list[ProjectResearchSubjectLink]] = relationship(
        back_populates="target_subject",
        foreign_keys="ProjectResearchSubjectLink.target_subject_id",
        passive_deletes=True,
    )
    opportunity_profile: Mapped[ProjectAIOpportunityProfile | None] = relationship(
        back_populates="subject", uselist=False, passive_deletes=True
    )


class ProjectResearchPersonalMemo(Base, TimestampMixin, VersionedMixin):
    __tablename__ = "project_research_personal_memos"
    __table_args__ = (
        UniqueConstraint(
            "project_id",
            "subject_id",
            "user_id",
            name="uq_research_personal_memos_subject_user",
        ),
        CheckConstraint(
            "version >= 1", name="ck_research_personal_memos_version"
        ),
        Index(
            "ix_research_personal_memos_project_subject",
            "project_id",
            "subject_id",
        ),
        Index("ix_research_personal_memos_user_id", "user_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False
    )
    subject_id: Mapped[str] = mapped_column(
        ForeignKey("project_research_subjects.id", ondelete="RESTRICT"), nullable=False
    )
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    memo: Mapped[str] = mapped_column(Text, nullable=False, default="")

    author: Mapped[User] = relationship(foreign_keys=[user_id])


class ProjectAIOpportunityProfile(Base, TimestampMixin):
    __tablename__ = "project_ai_opportunity_profiles"
    __table_args__ = (
        CheckConstraint("opportunity_status IN ('discovered', 'assessing', 'ready', 'converted', 'paused')", name="ck_project_ai_opportunity_profiles_status"),
        CheckConstraint("priority IS NULL OR priority IN ('high', 'medium', 'low')", name="ck_project_ai_opportunity_profiles_priority"),
        CheckConstraint("risk_level IS NULL OR risk_level IN ('high', 'medium', 'low')", name="ck_project_ai_opportunity_profiles_risk"),
        CheckConstraint("business_value_score IS NULL OR business_value_score BETWEEN 1 AND 5", name="ck_project_ai_opportunity_profiles_business_score"),
        CheckConstraint("feasibility_score IS NULL OR feasibility_score BETWEEN 1 AND 5", name="ck_project_ai_opportunity_profiles_feasibility_score"),
        CheckConstraint("data_readiness_score IS NULL OR data_readiness_score BETWEEN 1 AND 5", name="ck_project_ai_opportunity_profiles_data_score"),
    )

    subject_id: Mapped[str] = mapped_column(ForeignKey("project_research_subjects.id", ondelete="RESTRICT"), primary_key=True)
    target_audience: Mapped[str] = mapped_column(String(300), nullable=False, default="")
    owner_user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    opportunity_status: Mapped[str] = mapped_column(String(20), nullable=False, default="discovered", server_default="discovered")
    priority: Mapped[str | None] = mapped_column(String(12))
    business_value_score: Mapped[int | None] = mapped_column(Integer)
    feasibility_score: Mapped[int | None] = mapped_column(Integer)
    data_readiness_score: Mapped[int | None] = mapped_column(Integer)
    risk_level: Mapped[str | None] = mapped_column(String(12))
    next_action: Mapped[str] = mapped_column(Text, nullable=False, default="")
    evidence_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)
    ai_generated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="0")

    subject: Mapped[ProjectResearchSubject] = relationship(back_populates="opportunity_profile")
    owner: Mapped[User | None] = relationship(foreign_keys=[owner_user_id])


class ProjectResearchImportBatch(Base, TimestampMixin):
    """Database-authored receipt for one atomically committed import preview."""

    __tablename__ = "project_research_import_batches"
    __table_args__ = (
        CheckConstraint(
            "subject_type IN ('department', 'role', 'process', 'opportunity')",
            name="ck_project_research_import_batches_subject_type",
        ),
        CheckConstraint(
            "expected_project_version >= 1",
            name="ck_project_research_import_batches_expected_version",
        ),
        CheckConstraint(
            "committed_project_version > expected_project_version",
            name="ck_project_research_import_batches_committed_version",
        ),
        Index("ix_project_research_import_batches_project_id", "project_id"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False
    )
    subject_type: Mapped[str] = mapped_column(String(32), nullable=False)
    expected_project_version: Mapped[int] = mapped_column(Integer, nullable=False)
    committed_project_version: Mapped[int] = mapped_column(Integer, nullable=False)
    result_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)


class ProjectResearchSubjectLink(Base, TimestampMixin):
    __tablename__ = "project_research_subject_links"
    __table_args__ = (
        UniqueConstraint(
            "source_subject_id",
            "target_subject_id",
            "link_type",
            name="uq_project_research_subject_links_edge",
        ),
        CheckConstraint(
            "source_subject_id <> target_subject_id",
            name="ck_project_research_subject_links_not_self",
        ),
        ForeignKeyConstraint(
            ["project_id", "source_subject_id"],
            ["project_research_subjects.project_id", "project_research_subjects.id"],
            name="fk_project_research_subject_links_source",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["project_id", "target_subject_id"],
            ["project_research_subjects.project_id", "project_research_subjects.id"],
            name="fk_project_research_subject_links_target",
            ondelete="RESTRICT",
        ),
        Index(
            "ix_project_research_subject_links_source_project",
            "project_id",
            "source_subject_id",
        ),
        Index(
            "ix_project_research_subject_links_target_project",
            "project_id",
            "target_subject_id",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    project_id: Mapped[str] = mapped_column(String(36), nullable=False)
    source_subject_id: Mapped[str] = mapped_column(
        String(36), nullable=False
    )
    target_subject_id: Mapped[str] = mapped_column(
        String(36), nullable=False
    )
    link_type: Mapped[str] = mapped_column(String(60), nullable=False)

    source_subject: Mapped[ProjectResearchSubject] = relationship(
        back_populates="outgoing_links", foreign_keys=[source_subject_id]
    )
    target_subject: Mapped[ProjectResearchSubject] = relationship(
        back_populates="incoming_links", foreign_keys=[target_subject_id]
    )


def _subject_project_id(subject: ProjectResearchSubject) -> str | None:
    if subject.project_id is not None:
        return subject.project_id
    if subject.project is not None:
        return subject.project.id
    return None


def _synchronize_subject_link_project(
    link: ProjectResearchSubjectLink,
    *,
    source_subject: ProjectResearchSubject | None = None,
    target_subject: ProjectResearchSubject | None = None,
) -> None:
    """Synchronize a relationship-created link with its subjects' project scope."""

    source = source_subject if source_subject is not None else link.source_subject
    target = target_subject if target_subject is not None else link.target_subject
    if source is None or target is None:
        return

    source_project_id = _subject_project_id(source)
    target_project_id = _subject_project_id(target)
    if source_project_id is None or target_project_id is None:
        if (
            source.project is not None
            and target.project is not None
            and source.project is not target.project
        ):
            raise ResearchSubjectLinkOwnershipError(
                "research subject links must use subjects from the same project"
            )
        return

    if source_project_id != target_project_id:
        raise ResearchSubjectLinkOwnershipError(
            "research subject links must use subjects from the same project"
        )
    if link.project_id is None:
        link.project_id = source_project_id
    elif link.project_id != source_project_id:
        raise ResearchSubjectLinkOwnershipError(
            "research subject link project_id must match its subjects' project"
        )


@event.listens_for(ProjectResearchSubjectLink.source_subject, "set")
def _sync_project_from_source_subject(
    link: ProjectResearchSubjectLink,
    subject: ProjectResearchSubject | None,
    _old_subject: ProjectResearchSubject | None,
    _initiator: object,
) -> None:
    if subject is not None:
        _synchronize_subject_link_project(link, source_subject=subject)


@event.listens_for(ProjectResearchSubjectLink.target_subject, "set")
def _sync_project_from_target_subject(
    link: ProjectResearchSubjectLink,
    subject: ProjectResearchSubject | None,
    _old_subject: ProjectResearchSubject | None,
    _initiator: object,
) -> None:
    if subject is not None:
        _synchronize_subject_link_project(link, target_subject=subject)


@event.listens_for(ProjectResearchSubjectLink, "before_insert")
def _sync_project_before_subject_link_insert(
    _mapper: object,
    _connection: object,
    link: ProjectResearchSubjectLink,
) -> None:
    _synchronize_subject_link_project(link)


class ProjectResearchForm(Base, TimestampMixin, VersionedMixin):
    __tablename__ = "project_research_forms"
    __table_args__ = (
        UniqueConstraint(
            "subject_id", "form_key", name="uq_project_research_forms_subject_key"
        ),
        ForeignKeyConstraint(
            ["project_id", "subject_id"],
            ["project_research_subjects.project_id", "project_research_subjects.id"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["id", "current_revision_id"],
            [
                "project_research_form_revisions.form_id",
                "project_research_form_revisions.id",
            ],
            name="fk_project_research_forms_current_revision_id",
            ondelete="RESTRICT",
            use_alter=True,
        ),
        CheckConstraint("version >= 1", name="ck_project_research_forms_version"),
        Index("ix_project_research_forms_project_id", "project_id"),
        Index("ix_project_research_forms_current_revision_id", "current_revision_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False
    )
    subject_id: Mapped[str] = mapped_column(String(36), nullable=False)
    source_template_research_form_id: Mapped[str | None] = mapped_column(
        ForeignKey("template_research_forms.id", ondelete="RESTRICT"), nullable=True
    )
    form_key: Mapped[str] = mapped_column(String(100), nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    current_revision_id: Mapped[str | None] = mapped_column(String(36))

    project: Mapped["Project"] = relationship(
        back_populates="research_forms", overlaps="forms"
    )
    subject: Mapped[ProjectResearchSubject] = relationship(
        back_populates="forms", overlaps="project,research_forms"
    )
    source_template_form: Mapped[TemplateResearchForm] = relationship(
        back_populates="project_forms"
    )
    revisions: Mapped[list[ProjectResearchFormRevision]] = relationship(
        back_populates="form",
        foreign_keys="ProjectResearchFormRevision.form_id",
        passive_deletes=True,
    )
    current_revision: Mapped[ProjectResearchFormRevision | None] = relationship(
        primaryjoin=(
            "and_(ProjectResearchForm.id == ProjectResearchFormRevision.form_id, "
            "ProjectResearchForm.current_revision_id == ProjectResearchFormRevision.id)"
        ),
        foreign_keys=[current_revision_id],
        post_update=True,
    )


class ProjectResearchExport(Base, TimestampMixin):
    __tablename__ = "project_research_exports"
    __table_args__ = (
        CheckConstraint(
            "status IN ('queued', 'generating', 'succeeded', 'failed')",
            name="ck_project_research_exports_status",
        ),
        Index("ix_project_research_exports_project_form", "project_id", "form_id"),
        Index("ix_project_research_exports_status", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False
    )
    form_id: Mapped[str] = mapped_column(
        ForeignKey("project_research_forms.id", ondelete="RESTRICT"), nullable=False
    )
    requested_by_user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="queued")
    project_file_id: Mapped[str | None] = mapped_column(
        ForeignKey("project_files.id", ondelete="RESTRICT")
    )
    file_version_id: Mapped[str | None] = mapped_column(
        ForeignKey("project_file_versions.id", ondelete="RESTRICT")
    )
    version_number: Mapped[int | None] = mapped_column(Integer)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    failure_code: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    failure_message: Mapped[str] = mapped_column(Text, nullable=False, default="")


class ProjectResearchFormRevision(Base, TimestampMixin, VersionedMixin):
    __tablename__ = "project_research_form_revisions"
    __table_args__ = (
        UniqueConstraint(
            "form_id",
            "revision_number",
            name="uq_project_research_form_revisions_form_number",
        ),
        UniqueConstraint(
            "form_id",
            "id",
            name="uq_project_research_form_revisions_form_id",
        ),
        CheckConstraint(
            "revision_number >= 1", name="ck_project_research_form_revisions_number"
        ),
        CheckConstraint(
            "version >= 1", name="ck_project_research_form_revisions_version"
        ),
        CheckConstraint(
            "status IN ('draft', 'confirmed', 'archived')",
            name="ck_project_research_form_revisions_status",
        ),
        Index("ix_project_research_form_revisions_status", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    form_id: Mapped[str] = mapped_column(
        ForeignKey("project_research_forms.id", ondelete="RESTRICT"), nullable=False
    )
    revision_number: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft")
    parent_revision_id: Mapped[str | None] = mapped_column(
        ForeignKey("project_research_form_revisions.id", ondelete="RESTRICT")
    )
    definition_snapshot: Mapped[dict[str, Any]] = mapped_column(
        JSON, nullable=False, default=dict
    )
    returned_by_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT")
    )
    returned_at: Mapped[datetime | None] = mapped_column()
    return_comment: Mapped[str | None] = mapped_column(Text)
    form: Mapped[ProjectResearchForm] = relationship(
        back_populates="revisions", foreign_keys=[form_id]
    )
    parent_revision: Mapped[ProjectResearchFormRevision | None] = relationship(
        foreign_keys=[parent_revision_id], remote_side=[id]
    )
    answers: Mapped[list[ProjectResearchAnswer]] = relationship(
        back_populates="revision", passive_deletes=True
    )


class ProjectResearchAnswer(Base, TimestampMixin):
    __tablename__ = "project_research_answers"
    __table_args__ = (
        UniqueConstraint(
            "revision_id",
            "field_key",
            name="uq_project_research_answers_revision_field_key",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    revision_id: Mapped[str] = mapped_column(
        ForeignKey("project_research_form_revisions.id", ondelete="RESTRICT"),
        nullable=False,
    )
    source_template_research_field_id: Mapped[str | None] = mapped_column(
        ForeignKey("template_research_fields.id", ondelete="RESTRICT"), nullable=True
    )
    field_key: Mapped[str] = mapped_column(String(100), nullable=False)
    value_json: Mapped[ResearchJSON] = mapped_column(JSON, nullable=False, default=dict)

    revision: Mapped[ProjectResearchFormRevision] = relationship(back_populates="answers")
    source_template_field: Mapped[TemplateResearchField] = relationship(
        back_populates="answers"
    )
