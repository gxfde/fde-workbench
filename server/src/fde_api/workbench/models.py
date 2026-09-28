from __future__ import annotations

from datetime import date, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
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

from fde_api.auth.models import (
    Base,
    CURRENT_TIMESTAMP_SQL,
    UTC_TIMESTAMP_SQL,
    UTCDateTime,
    UTCTimestamp,
    User,
)


def new_uuid() -> str:
    return str(uuid4())


def new_template_key() -> str:
    return f"template_{uuid4().hex}"


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), nullable=False, server_default=UTC_TIMESTAMP_SQL
    )
    updated_at: Mapped[datetime] = mapped_column(
        UTCTimestamp(),
        nullable=False,
        server_default=CURRENT_TIMESTAMP_SQL,
        server_onupdate=CURRENT_TIMESTAMP_SQL,
    )


class VersionedMixin:
    version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default=text("1")
    )


class ModuleCatalog(Base, TimestampMixin, VersionedMixin):
    __tablename__ = "module_catalog"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    module_key: Mapped[str] = mapped_column(String(80), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False, unique=True)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class IndustryTemplate(Base, TimestampMixin, VersionedMixin):
    __tablename__ = "industry_templates"
    __table_args__ = (
        CheckConstraint(
            "status IN ('active', 'inactive')",
            name="ck_industry_templates_status",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    template_key: Mapped[str] = mapped_column(
        String(100), nullable=False, unique=True, default=new_template_key
    )
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    industry_name: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    latest_published_version_number: Mapped[int | None] = mapped_column(Integer)

    versions: Mapped[list[IndustryTemplateVersion]] = relationship(
        back_populates="template"
    )


class IndustryTemplateVersion(Base, TimestampMixin, VersionedMixin):
    __tablename__ = "industry_template_versions"
    __table_args__ = (
        UniqueConstraint(
            "template_id",
            "version_number",
            name="uq_industry_template_versions_template_version",
        ),
        CheckConstraint(
            "version_number >= 1",
            name="ck_industry_template_versions_number",
        ),
        CheckConstraint(
            "status IN ('draft', 'published', 'inactive')",
            name="ck_industry_template_versions_status",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    template_id: Mapped[str] = mapped_column(
        ForeignKey("industry_templates.id", ondelete="RESTRICT"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    industry_name: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft")
    published_by_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT")
    )
    published_at: Mapped[datetime | None] = mapped_column(UTCDateTime())

    template: Mapped[IndustryTemplate] = relationship(back_populates="versions")
    published_by: Mapped[User | None] = relationship(
        foreign_keys=[published_by_user_id]
    )
    modules: Mapped[list[TemplateModule]] = relationship(
        back_populates="template_version",
        passive_deletes=True,
    )
    research_forms: Mapped[list["TemplateResearchForm"]] = relationship(
        back_populates="template_version",
        passive_deletes=True,
    )


class TemplateModule(Base, TimestampMixin):
    __tablename__ = "template_modules"
    __table_args__ = (
        UniqueConstraint(
            "template_version_id",
            "module_catalog_id",
            name="uq_template_modules_version_catalog",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    template_version_id: Mapped[str] = mapped_column(
        ForeignKey("industry_template_versions.id", ondelete="RESTRICT"), nullable=False
    )
    module_catalog_id: Mapped[str] = mapped_column(
        ForeignKey("module_catalog.id", ondelete="RESTRICT"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    template_version: Mapped[IndustryTemplateVersion] = relationship(
        back_populates="modules"
    )
    module_catalog: Mapped[ModuleCatalog] = relationship()
    tasks: Mapped[list[TemplateTask]] = relationship(
        back_populates="template_module",
        passive_deletes=True,
    )


class TemplateTask(Base, TimestampMixin):
    __tablename__ = "template_tasks"
    __table_args__ = (
        UniqueConstraint(
            "template_module_id",
            "task_key",
            name="uq_template_tasks_module_key",
        ),
        CheckConstraint("duration_days >= 1", name="ck_template_tasks_duration"),
        CheckConstraint(
            "default_assignee_role IN "
            "('admin', 'project_lead', 'fde_engineer', 'viewer')",
            name="ck_template_tasks_default_role",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    template_module_id: Mapped[str] = mapped_column(
        ForeignKey("template_modules.id", ondelete="RESTRICT"), nullable=False
    )
    task_key: Mapped[str] = mapped_column(String(100), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    duration_days: Mapped[int] = mapped_column(Integer, nullable=False)
    default_assignee_role: Mapped[str] = mapped_column(String(32), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    template_module: Mapped[TemplateModule] = relationship(back_populates="tasks")


class TemplateTaskDependency(Base, TimestampMixin):
    __tablename__ = "template_task_dependencies"
    __table_args__ = (
        UniqueConstraint(
            "predecessor_task_id",
            "successor_task_id",
            name="uq_template_task_dependencies_edge",
        ),
        CheckConstraint(
            "predecessor_task_id <> successor_task_id",
            name="ck_template_task_dependencies_not_self",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    predecessor_task_id: Mapped[str] = mapped_column(
        ForeignKey("template_tasks.id", ondelete="RESTRICT"), nullable=False
    )
    successor_task_id: Mapped[str] = mapped_column(
        ForeignKey("template_tasks.id", ondelete="RESTRICT"), nullable=False
    )

    predecessor_task: Mapped[TemplateTask] = relationship(
        foreign_keys=[predecessor_task_id]
    )
    successor_task: Mapped[TemplateTask] = relationship(
        foreign_keys=[successor_task_id]
    )


class Project(Base, TimestampMixin, VersionedMixin):
    __tablename__ = "projects"
    __table_args__ = (
        CheckConstraint(
            "status IN ('draft', 'active', 'paused', 'completed', 'cancelled')",
            name="ck_projects_status",
        ),
        Index("ix_projects_status", "status"),
        Index("ix_projects_leader_user_id", "leader_user_id"),
        Index("ix_projects_planned_dates", "planned_start_date", "planned_end_date"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    project_code: Mapped[str] = mapped_column(String(40), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    enterprise_name: Mapped[str] = mapped_column(String(160), nullable=False)
    enterprise_contact_name: Mapped[str] = mapped_column(
        String(120), nullable=False, default=""
    )
    enterprise_contact_phone: Mapped[str] = mapped_column(
        String(60), nullable=False, default=""
    )
    enterprise_address: Mapped[str] = mapped_column(
        String(255), nullable=False, default=""
    )
    background: Mapped[str] = mapped_column(Text, nullable=False, default="")
    notes: Mapped[str] = mapped_column(Text, nullable=False, default="")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft")
    planned_start_date: Mapped[date] = mapped_column(Date, nullable=False)
    planned_end_date: Mapped[date | None] = mapped_column(Date)
    leader_user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    source_template_version_id: Mapped[str | None] = mapped_column(
        ForeignKey("industry_template_versions.id", ondelete="RESTRICT"),
        nullable=True,
    )
    template_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    research_snapshot: Mapped[dict[str, Any]] = mapped_column(
        JSON, nullable=False, default=dict
    )

    leader: Mapped[User] = relationship(foreign_keys=[leader_user_id])
    source_template_version: Mapped[IndustryTemplateVersion | None] = relationship()
    members: Mapped[list[ProjectMember]] = relationship(back_populates="project")
    modules: Mapped[list[ProjectModule]] = relationship(back_populates="project")
    events: Mapped[list[OperationEvent]] = relationship(back_populates="project")
    research_subjects: Mapped[list["ProjectResearchSubject"]] = relationship(
        back_populates="project",
        passive_deletes=True,
    )
    research_forms: Mapped[list["ProjectResearchForm"]] = relationship(
        back_populates="project",
        passive_deletes=True,
    )


class ProjectMember(Base, TimestampMixin):
    __tablename__ = "project_members"
    __table_args__ = (
        UniqueConstraint(
            "project_id", "user_id", name="uq_project_members_project_user"
        ),
        CheckConstraint(
            "role IN ('member', 'viewer')", name="ck_project_members_role"
        ),
        Index("ix_project_members_user_id", "user_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False
    )
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    role: Mapped[str] = mapped_column(String(20), nullable=False, default="member")

    project: Mapped[Project] = relationship(back_populates="members")
    user: Mapped[User] = relationship()


class ProjectModule(Base, TimestampMixin):
    __tablename__ = "project_modules"
    __table_args__ = (
        UniqueConstraint(
            "project_id",
            "module_catalog_id",
            name="uq_project_modules_project_catalog",
        ),
        CheckConstraint(
            "status IN ('active', 'cancelled')",
            name="ck_project_modules_status",
        ),
        Index(
            "ix_project_modules_planned_dates",
            "planned_start_date",
            "planned_end_date",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False
    )
    source_template_module_id: Mapped[str | None] = mapped_column(
        ForeignKey("template_modules.id", ondelete="RESTRICT")
    )
    module_catalog_id: Mapped[str] = mapped_column(
        ForeignKey("module_catalog.id", ondelete="RESTRICT"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    planned_start_date: Mapped[date | None] = mapped_column(Date)
    planned_end_date: Mapped[date | None] = mapped_column(Date)

    project: Mapped[Project] = relationship(back_populates="modules")
    source_template_module: Mapped[TemplateModule | None] = relationship()
    module_catalog: Mapped[ModuleCatalog] = relationship()
    tasks: Mapped[list[ProjectTask]] = relationship(back_populates="project_module")


class ProjectTask(Base, TimestampMixin, VersionedMixin):
    __tablename__ = "project_tasks"
    __table_args__ = (
        UniqueConstraint(
            "project_module_id", "task_key", name="uq_project_tasks_module_key"
        ),
        CheckConstraint("duration_days >= 1", name="ck_project_tasks_duration"),
        CheckConstraint(
            "status IN "
            "('not_started', 'in_progress', 'blocked', 'completed', 'cancelled')",
            name="ck_project_tasks_status",
        ),
        CheckConstraint(
            "progress >= 0 AND progress <= 100", name="ck_project_tasks_progress"
        ),
        CheckConstraint(
            "default_assignee_role IS NULL OR default_assignee_role IN "
            "('admin', 'project_lead', 'fde_engineer', 'viewer')",
            name="ck_project_tasks_default_role",
        ),
        Index("ix_project_tasks_assignee_user_id", "assignee_user_id"),
        Index(
            "ix_project_tasks_planned_dates",
            "planned_start_date",
            "planned_end_date",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    project_module_id: Mapped[str] = mapped_column(
        ForeignKey("project_modules.id", ondelete="RESTRICT"), nullable=False
    )
    source_template_task_id: Mapped[str | None] = mapped_column(
        ForeignKey("template_tasks.id", ondelete="RESTRICT")
    )
    task_key: Mapped[str] = mapped_column(String(100), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="not_started"
    )
    planned_start_date: Mapped[date] = mapped_column(Date, nullable=False)
    planned_end_date: Mapped[date] = mapped_column(Date, nullable=False)
    duration_days: Mapped[int] = mapped_column(Integer, nullable=False)
    default_assignee_role: Mapped[str | None] = mapped_column(String(32))
    assignee_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT")
    )
    progress: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    blocked_reason: Mapped[str] = mapped_column(Text, nullable=False, default="")
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    project_module: Mapped[ProjectModule] = relationship(back_populates="tasks")
    source_template_task: Mapped[TemplateTask | None] = relationship()
    assignee: Mapped[User | None] = relationship(foreign_keys=[assignee_user_id])
    collaborators: Mapped[list[ProjectTaskCollaborator]] = relationship(
        back_populates="task"
    )


class ProjectTaskCollaborator(Base, TimestampMixin):
    __tablename__ = "project_task_collaborators"
    __table_args__ = (
        UniqueConstraint(
            "task_id", "user_id", name="uq_project_task_collaborators_task_user"
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    task_id: Mapped[str] = mapped_column(
        ForeignKey("project_tasks.id", ondelete="RESTRICT"), nullable=False
    )
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )

    task: Mapped[ProjectTask] = relationship(back_populates="collaborators")
    user: Mapped[User] = relationship()


class ProjectTaskDependency(Base, TimestampMixin):
    __tablename__ = "project_task_dependencies"
    __table_args__ = (
        UniqueConstraint(
            "predecessor_task_id",
            "successor_task_id",
            name="uq_project_task_dependencies_edge",
        ),
        CheckConstraint(
            "predecessor_task_id <> successor_task_id",
            name="ck_project_task_dependencies_not_self",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    predecessor_task_id: Mapped[str] = mapped_column(
        ForeignKey("project_tasks.id", ondelete="RESTRICT"), nullable=False
    )
    successor_task_id: Mapped[str] = mapped_column(
        ForeignKey("project_tasks.id", ondelete="RESTRICT"), nullable=False
    )

    predecessor_task: Mapped[ProjectTask] = relationship(
        foreign_keys=[predecessor_task_id]
    )
    successor_task: Mapped[ProjectTask] = relationship(
        foreign_keys=[successor_task_id]
    )


class OperationEvent(Base, TimestampMixin):
    __tablename__ = "operation_events"
    __table_args__ = (
        Index("ix_operation_events_project_occurred", "project_id", "occurred_at"),
        Index("ix_operation_events_actor_user_id", "actor_user_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    actor_user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    project_id: Mapped[str | None] = mapped_column(
        ForeignKey("projects.id", ondelete="RESTRICT")
    )
    target_type: Mapped[str] = mapped_column(String(80), nullable=False)
    target_id: Mapped[str] = mapped_column(String(80), nullable=False)
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), nullable=False, server_default=UTC_TIMESTAMP_SQL
    )
    changes: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)

    actor: Mapped[User] = relationship(foreign_keys=[actor_user_id])
    project: Mapped[Project | None] = relationship(back_populates="events")


from fde_api.research import models as research_models  # noqa: E402, F401
