from __future__ import annotations

from typing import Any

from sqlalchemy import CheckConstraint, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.mysql import MEDIUMTEXT

from fde_api.workbench.models import Base, TimestampMixin, VersionedMixin, new_uuid


class ProjectSolution(Base, TimestampMixin, VersionedMixin):
    """Editable delivery design; linked opportunities remain independent identities."""

    __tablename__ = "project_solutions"
    __table_args__ = (
        CheckConstraint("status IN ('active', 'archived')", name="ck_project_solutions_status"),
        CheckConstraint("version >= 1", name="ck_project_solutions_version"),
        UniqueConstraint("project_id", "legacy_source_key", name="uq_project_solutions_legacy_source"),
        Index("ix_project_solutions_project_status", "project_id", "status"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    design_markdown: Mapped[str] = mapped_column(Text().with_variant(MEDIUMTEXT(), "mysql"), nullable=False, default="")
    deliverables: Mapped[str] = mapped_column(Text, nullable=False, default="")
    acceptance_criteria: Mapped[str] = mapped_column(Text, nullable=False, default="")
    data_systems: Mapped[str] = mapped_column(Text, nullable=False, default="")
    schedule: Mapped[str] = mapped_column(Text, nullable=False, default="")
    risks_dependencies: Mapped[str] = mapped_column(Text, nullable=False, default="")
    business_category: Mapped[str | None] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active", server_default="active")
    owner_user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    legacy_source_key: Mapped[str | None] = mapped_column(String(100))
    source_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    opportunities: Mapped[list[ProjectSolutionOpportunity]] = relationship(
        back_populates="solution", cascade="all, delete-orphan", order_by="ProjectSolutionOpportunity.sort_order"
    )


class ProjectSolutionOpportunity(Base):
    """Many-to-many membership plus a user-reviewed opportunity snapshot."""

    __tablename__ = "project_solution_opportunities"
    solution_id: Mapped[str] = mapped_column(ForeignKey("project_solutions.id", ondelete="RESTRICT"), primary_key=True)
    opportunity_id: Mapped[str] = mapped_column(ForeignKey("project_research_subjects.id", ondelete="RESTRICT"), primary_key=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    snapshot_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    solution: Mapped[ProjectSolution] = relationship(back_populates="opportunities")


class ProjectSolutionExport(Base, TimestampMixin):
    """One immutable SOW export per saved solution revision; repeated requests reuse it."""

    __tablename__ = "project_solution_exports"
    __table_args__ = (UniqueConstraint("solution_id", "solution_version", name="uq_project_solution_exports_revision"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    solution_id: Mapped[str] = mapped_column(ForeignKey("project_solutions.id", ondelete="RESTRICT"), nullable=False)
    solution_version: Mapped[int] = mapped_column(Integer, nullable=False)
    document_id: Mapped[str] = mapped_column(ForeignKey("project_documents.id", ondelete="RESTRICT"), nullable=False)
    document_version_id: Mapped[str] = mapped_column(ForeignKey("project_document_versions.id", ondelete="RESTRICT"), nullable=False)
