from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import CheckConstraint, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from fde_api.auth.models import UTCDateTime
from fde_api.workbench.models import Base, TimestampMixin, VersionedMixin, new_uuid


GUIDANCE_STATUSES = ("draft", "confirmed", "superseded")
GUIDANCE_ANALYSIS_STATES = (
    "queued", "extracting", "analyzing", "ready", "failed", "cancelled"
)
# 售前轻量录入卡的访谈方式（PRD F1 / 决议 D16）。
INTERVIEW_MODES = ("onsite", "remote", "hybrid")


class PresurveyIntake(Base, TimestampMixin):
    """售前轻量录入卡（PRD F1 / 决议 D16）。

    S1–S2 阶段即可填写：只收无敏感结构化字段（行业/规模/地域/访谈方式/
    对象角色/诉求一句话/阶段目标/备注），数据口径等价 SOP leads.md 九字段，
    不触碰「S0–S2 售前资料禁入库」红线。DOCX 上传与 AI 分析链路仍被
    G3 前置闸拦在 S3 之后（service 层强制，见 _require_s3_gate）。
    """

    __tablename__ = "presurvey_intakes"
    __table_args__ = (
        CheckConstraint(
            "interview_mode IN ('onsite', 'remote', 'hybrid')",
            name="ck_presurvey_intakes_interview_mode",
        ),
    )

    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="RESTRICT"), primary_key=True
    )
    industry: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    scale: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    region: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    interview_mode: Mapped[str] = mapped_column(
        String(16), nullable=False, default="onsite"
    )
    interviewee_roles: Mapped[list[Any]] = mapped_column(JSON, nullable=False, default=list)
    customer_vision: Mapped[str] = mapped_column(Text, nullable=False, default="")
    phase_objective: Mapped[str] = mapped_column(Text, nullable=False, default="")
    notes: Mapped[str] = mapped_column(Text, nullable=False, default="")
    updated_by_user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )


class ProjectPresurveySource(Base, TimestampMixin, VersionedMixin):
    __tablename__ = "project_presurvey_sources"
    __table_args__ = (
        CheckConstraint("version >= 1", name="ck_project_presurvey_sources_version"),
    )

    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="RESTRICT"), primary_key=True
    )
    project_file_id: Mapped[str] = mapped_column(
        ForeignKey("project_files.id", ondelete="RESTRICT"), nullable=False
    )
    current_file_version_id: Mapped[str] = mapped_column(
        ForeignKey("project_file_versions.id", ondelete="RESTRICT"), nullable=False
    )


class ProjectGuidanceAnalysis(Base, TimestampMixin, VersionedMixin):
    __tablename__ = "project_guidance_analyses"
    __table_args__ = (
        UniqueConstraint("project_id", "version_number", name="uq_project_guidance_project_version"),
        CheckConstraint("version_number >= 1", name="ck_project_guidance_version_number"),
        CheckConstraint("version >= 1", name="ck_project_guidance_version"),
        CheckConstraint(
            "status IN ('draft', 'confirmed', 'superseded')",
            name="ck_project_guidance_status",
        ),
        CheckConstraint(
            "analysis_state IN ('queued', 'extracting', 'analyzing', 'ready', 'failed', 'cancelled')",
            name="ck_project_guidance_analysis_state",
        ),
        CheckConstraint(
            "source_kind IN ('presurvey_docx', 'translator_draft')",
            name="ck_project_guidance_source_kind",
        ),
        UniqueConstraint("project_id", "translation_id", name="uq_project_guidance_project_translation"),
        Index("ix_project_guidance_project_status", "project_id", "status"),
        Index("ix_project_guidance_source_version", "source_file_version_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False)
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    # goal-d10 采纳流：翻译器草稿来源无源文件——source_file 双列放宽
    # nullable，source_kind 区分来源；source_filename 存
    # translator:<translation_id> 保持可读可追溯（NOT NULL 不放宽）。
    source_kind: Mapped[str] = mapped_column(String(24), nullable=False, default="presurvey_docx")
    translation_id: Mapped[str | None] = mapped_column(String(36))
    source_file_id: Mapped[str | None] = mapped_column(ForeignKey("project_files.id", ondelete="RESTRICT"))
    source_file_version_id: Mapped[str | None] = mapped_column(ForeignKey("project_file_versions.id", ondelete="RESTRICT"))
    source_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    source_sha256: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="draft")
    analysis_state: Mapped[str] = mapped_column(String(24), nullable=False, default="queued")
    customer_vision: Mapped[str] = mapped_column(Text, nullable=False, default="")
    current_phase_objective: Mapped[str] = mapped_column(Text, nullable=False, default="")
    key_business_problems_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)
    priority_departments_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)
    priority_roles_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)
    priority_processes_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)
    success_criteria_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)
    out_of_scope_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)
    data_security_redlines_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)
    systems_and_deployment_constraints_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)
    assumptions_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)
    open_questions_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)
    next_actions_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)
    executive_summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    evidence_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    ai_model: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    ai_generated_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    created_by_user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    reviewed_by_user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    reviewed_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    failure_code: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    failure_message: Mapped[str] = mapped_column(Text, nullable=False, default="")
