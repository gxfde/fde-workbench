from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import uuid4

from sqlalchemy import (
    Boolean,
    func,
    CheckConstraint,
    Date,
    ForeignKey,
    Index,
    Integer,
    JSON,
    Numeric,
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
    # v0.2 (PG 迁移): PG 没有 ON UPDATE CURRENT_TIMESTAMP，server_onupdate 在 PG 上不生效，
    # 会导致 updated_at 永远冻结。改为 ORM 层 onupdate=func.now()（跨方言通用）。
    updated_at: Mapped[datetime] = mapped_column(
        UTCTimestamp(),
        nullable=False,
        server_default=CURRENT_TIMESTAMP_SQL,
        onupdate=func.now(),
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
        CheckConstraint(
            # P2-3（派单设计 §8.5）：预留 'FDE_DISPATCH'（§11.1 注释已预留路径）——
            # 派单池立项的项目业务线；当前创建路径仍写 'FDE'，值随派单立项入口启用
            "business_line IN ('FDE', 'FDE_DISPATCH')",
            name="ck_projects_business_line",
        ),
        # goal-r2（派单设计 §3.3 复购判据）：「同一 enterprise_code ≥2 个项目」
        # 需可表达——全局唯一约束放宽为普通索引（代号纪律保留：仍只存代号不存
        # 明文，A2 红线不动；唯一性交还录入侧约定，复购走同代号二启项目）。
        Index("ix_projects_enterprise_code", "enterprise_code"),
        Index("ix_projects_status", "status"),
        Index("ix_projects_leader_user_id", "leader_user_id"),
        Index("ix_projects_planned_dates", "planned_start_date", "planned_end_date"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    project_code: Mapped[str] = mapped_column(String(40), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    # P1 代号化（设计 §3.1/§3.2，SOP 红线 A2）：workbench 不存客户明文，
    # 只存代号（格式「客户A·行业·城市」，两段「·」由服务层校验，立项时手工录入），
    # 实名映射只存在于 fdeops / openfde（真相层）。
    enterprise_code: Mapped[str] = mapped_column(String(80), nullable=False)
    openfde_engagement: Mapped[str | None] = mapped_column(String(100))
    fdeops_workspace: Mapped[str | None] = mapped_column(String(160))
    # §1 分工铁律：G3 之后项目才在 workbench 立项，故默认挂在 S3（深度诊断）节点。
    sop_phase: Mapped[str] = mapped_column(
        ForeignKey("sop_nodes.node_key", ondelete="RESTRICT"),
        nullable=False,
        default="S3",
        server_default="S3",
    )
    # §11.1 拍板：业务线当前单值 FDE；未来加值走 schema migration（改 ck_projects_business_line）。
    business_line: Mapped[str] = mapped_column(
        String(20), nullable=False, default="FDE", server_default="FDE"
    )
    background: Mapped[str] = mapped_column(Text, nullable=False, default="")
    notes: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # T6 高成本 run 前评审的项目级关闭开关（goal-d11，总纲 §2.2 T6「可按
    # 项目关闭」）；全局阈值在 settings.t6_review_cost_threshold。
    t6_review_disabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
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
    gates: Mapped[list["Gate"]] = relationship(
        back_populates="project", passive_deletes=True
    )
    quotes: Mapped[list["Quote"]] = relationship(
        back_populates="project", passive_deletes=True
    )
    payments: Mapped[list["Payment"]] = relationship(
        back_populates="project", passive_deletes=True
    )
    contracts: Mapped[list["Contract"]] = relationship(
        back_populates="project", passive_deletes=True
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
    # P1（设计 §3.1）：任务可挂 SOP 节点与门禁证据提交点；证据只存出处指针（A4），
    # 内容本体在 fdeops .fde/ 或 openfde assets/。
    sop_node: Mapped[str | None] = mapped_column(
        ForeignKey("sop_nodes.node_key", ondelete="RESTRICT")
    )
    gate: Mapped[str | None] = mapped_column(String(10))
    evidence_uri: Mapped[str | None] = mapped_column(String(500))
    evidence_hash: Mapped[str | None] = mapped_column(String(64))

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


class SopNode(Base, TimestampMixin):
    """SOP 节点定义（投影层，非真相）。

    数据源：server/seeds/sop_nodes.json（16 条，SOP v2.4.6 + 映射表 v1.3 快照），
    由 server/load_seeds.py 灌入并按 node_key 幂等更新；方法论真相永远在
    SOP 三件套（A1），每条带出处指针（A4：source_uri + content_hash）。
    口径（设计 §5.0）：S9 并入 G8、S13 无编号门禁——均不建 Gate 记录；
    trigger 只存「核心进入条件」原文，不存 T 代号（横切线与开工触发同码不同义）。
    """

    __tablename__ = "sop_nodes"
    __table_args__ = (
        CheckConstraint(
            "segment IN ('售前段', '交付段', '交付后段', '横切线')",
            name="ck_sop_nodes_segment",
        ),
        UniqueConstraint("node_key", name="uq_sop_nodes_node_key"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    node_key: Mapped[str] = mapped_column(String(20), nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    segment: Mapped[str] = mapped_column(String(20), nullable=False)
    gate_key: Mapped[str | None] = mapped_column(String(10))
    gate_note: Mapped[str | None] = mapped_column(String(120))
    trigger: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    human_action: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    # S7.5 无 ②/③ 小节出处，ai_action 为 NULL——工程层不得发明方法论层没有的东西
    ai_action: Mapped[str | None] = mapped_column(Text)
    artifact: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    evidence_location: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    record_track: Mapped[list[str]] = mapped_column(
        JSON, nullable=False, default=list, server_default=text("'[]'")
    )
    signer_role: Mapped[str | None] = mapped_column(String(120))
    fail_exit: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    next_node: Mapped[str] = mapped_column(String(100), nullable=False, default="", server_default="")
    next_node_keys: Mapped[list[str]] = mapped_column(
        JSON, nullable=False, default=list, server_default=text("'[]'")
    )
    contract_payment_auth: Mapped[str | None] = mapped_column(Text)
    # A4 出处指针：映射表行（source_*）与 SOP 主文档 ②/③ 小节（human_ai_*）分开留痕
    source_uri: Mapped[str] = mapped_column(String(500), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    human_ai_source_uri: Mapped[str | None] = mapped_column(String(500))
    human_ai_content_hash: Mapped[str | None] = mapped_column(String(64))


class Gate(Base, TimestampMixin, VersionedMixin):
    """门禁执行状态（每项目每门一条；P1 只建表，状态机由 P3 门禁引擎驱动）。

    状态语义（设计 §5.1，照搬 SOP）：pending → evidence → passed/conditional_pass/failed；
    conditional_pass 仅 G9（SOP 原文「有条件通过」）；G8 过门必带 decision ∈
    {proceed, pivot, stop}——工程层不得增删状态（v0.2 已删无出处的 waived）。
    evidence_checklist 是门禁模板快照（种子 gates.json 程序化生成，P3 灌入）。
    """

    __tablename__ = "gates"
    __table_args__ = (
        UniqueConstraint("project_id", "gate_key", name="uq_gates_project_gate"),
        CheckConstraint(
            "status IN ('pending', 'evidence', 'passed', 'conditional_pass', 'failed')",
            name="ck_gates_status",
        ),
        CheckConstraint(
            "decision IS NULL OR decision IN ('proceed', 'pivot', 'stop')",
            name="ck_gates_decision",
        ),
        Index("ix_gates_project_id", "project_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    gate_key: Mapped[str] = mapped_column(String(10), nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="pending", server_default="pending"
    )
    evidence_checklist: Mapped[list[Any]] = mapped_column(
        JSON, nullable=False, default=list, server_default=text("'[]'")
    )
    # sha256 of gates.json at instantiation time (audit: which checklist version)
    template_hash: Mapped[str | None] = mapped_column(String(64))
    # 证据出处指针（A4）：指向 fdeops .fde/ 或 openfde assets/ 的文件
    evidence_uri: Mapped[str | None] = mapped_column(String(500))
    evidence_hash: Mapped[str | None] = mapped_column(String(64))
    submitted_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    decided_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    decision: Mapped[str | None] = mapped_column(String(10))
    signer_role: Mapped[str | None] = mapped_column(String(120))
    # P0-5 门禁验收分离（派单设计 §9.4，开池四道闸之二）：执行人/拍板人分记，
    # 「拍板人 ≠ 该门禁执行人」由 gate_service.decide_gate 代码强制不可绕过。
    # is_delivery_party 标记证据由交付方（派单池外部 FDE，§9.3 接单后以
    # ProjectMember(role='member') 入场）执行——此类 G8/G9 须平台侧拍板。
    submitted_by_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    decided_by_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    is_delivery_party: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    # V3 T-G1（WB-DEF-8）：任务产物→门禁证据候选。列表项
    # {source_uri, content_hash, task_key, task_name, task_id, proposed_by_user_id,
    # proposed_at}；候选只是建议（advisory）——claim_status 与门禁状态一概不动，
    # 人工经既有提交闸采纳后按指纹剪除。旧行 NULL → 读时合并 []（零破坏）。
    evidence_candidates: Mapped[list[Any] | None] = mapped_column(JSON)
    # B#28 生命周期版本隔离（FF stage 语义）：门禁语法代际，现役=1；将来模板
    # 换 grammar 时旧记录不接受新入口、版本交叉操作失败且不改 version。
    # CAS 拍板（expected_revision 复核）复用上方 VersionedMixin.version 作
    # revision——总览 B#28 的 revision ≡ 本表既有 version 列，不另开重复列。
    lifecycle_version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default=text("1")
    )

    project: Mapped[Project] = relationship(back_populates="gates")


class Quote(Base, TimestampMixin, VersionedMixin):
    """报价台账（P4，设计 §6；承接《报价计算卡-v1.1》——只程序化公式，卡一字不动）。

    输入列 = 卡 §1–§5 的系数与单价（全部"初始假设，待回校"，卡 §九）；
    输出列 = 服务层按卡公式计算（realistic=ideal×档内偏离×数据×合规×缓冲；
    成本=现金+realistic×时薪；公式价=成本×1.4；锚点三分支 A/B/C）。
    field_claims：每个数字字段 → claim_status ∈ {estimated, claimed, measured,
    accepted}（§5.3 四值，accepted 之外黄标；默认全 estimated）。
    对外报价单（draft HTML）不出现任何系数——客户看三档（卡 §十-3）。
    """

    __tablename__ = "quotes"
    __table_args__ = (
        UniqueConstraint("project_id", "quote_key", name="uq_quotes_project_key"),
        CheckConstraint(
            "tier IN ('light', 'standard', 'flagship')", name="ck_quotes_tier"
        ),
        CheckConstraint(
            "anchor_mode IN ('cold_start', 'steady')", name="ck_quotes_anchor_mode"
        ),
        CheckConstraint(
            "status IN ('draft', 'finalized')", name="ck_quotes_status"
        ),
        CheckConstraint(
            "b_layer_score >= 0 AND b_layer_score <= 10", name="ck_quotes_b_score"
        ),
        CheckConstraint(
            "branch IN ('A', 'B', 'C')", name="ck_quotes_branch"
        ),
        CheckConstraint(
            "c_handling IS NULL OR c_handling IN "
            "('scope_cut', 'split_phases', 'external_collab', 'ticket_deal')",
            name="ck_quotes_c_handling",
        ),
        Index("ix_quotes_project_id", "project_id"),
        Index("ix_quotes_owner", "owner_user_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    quote_key: Mapped[str] = mapped_column(String(40), nullable=False)
    tier: Mapped[str] = mapped_column(String(10), nullable=False)
    status: Mapped[str] = mapped_column(
        String(10), nullable=False, default="draft", server_default="draft"
    )
    # ---- 输入（卡 §2/§4/§5；取值集合由服务层按卡校验） ----
    ideal_hours: Mapped[Decimal] = mapped_column(Numeric(7, 2), nullable=False)
    integration_factor: Mapped[Decimal] = mapped_column(
        Numeric(4, 2), nullable=False, default=Decimal("1.00")
    )
    data_factor: Mapped[Decimal] = mapped_column(
        Numeric(4, 2), nullable=False, default=Decimal("1.00")
    )
    compliance_factor: Mapped[Decimal] = mapped_column(
        Numeric(4, 2), nullable=False, default=Decimal("1.00")
    )
    buffer_factor: Mapped[Decimal] = mapped_column(
        Numeric(4, 2), nullable=False, default=Decimal("2.00")
    )
    hourly_rate: Mapped[int] = mapped_column(Integer, nullable=False)
    cash_cost: Mapped[int] = mapped_column(Integer, nullable=False)
    margin_factor: Mapped[Decimal] = mapped_column(
        Numeric(3, 2), nullable=False, default=Decimal("1.40")
    )
    b_layer_score: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    anchor_mode: Mapped[str] = mapped_column(
        String(12), nullable=False, default="cold_start"
    )
    preset: Mapped[str | None] = mapped_column(String(40))
    # ---- 输出（服务层计算，禁止外部直写） ----
    realistic_hours: Mapped[Decimal] = mapped_column(Numeric(8, 2), nullable=False)
    labor_cost: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    total_cost: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    formula_price: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    b_layer_factor: Mapped[Decimal] = mapped_column(Numeric(4, 2), nullable=False)
    anchor_low: Mapped[int] = mapped_column(Integer, nullable=False)
    anchor_high: Mapped[int] = mapped_column(Integer, nullable=False)
    branch: Mapped[str] = mapped_column(String(1), nullable=False)
    quote_low: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    quote_high: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    c_handling: Mapped[str | None] = mapped_column(String(20))
    # P1-6（派单设计 §8.4）：报价归属人（创建者；派单语境下交付方侧的归属
    # 过滤维度）。nullable=存量报价不回填，语义=「无归属（平台侧台账报价）」。
    owner_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    # ---- 台账回填（卡 §八：成交后 48h 内） ----
    final_amount: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    final_deviation_pct: Mapped[Decimal | None] = mapped_column(Numeric(7, 4))
    allowance_cap: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    allowance_paid: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), nullable=False, default=Decimal("0"), server_default=text("0")
    )
    ticket_deal: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    ticket_note: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # ---- 回校（卡 §九 #1：首单结项必回校缓冲 ×2.0，结项 checklist 固定一步） ----
    actual_hours: Mapped[Decimal | None] = mapped_column(Numeric(8, 2))
    deviation_pct: Mapped[Decimal | None] = mapped_column(Numeric(7, 4))
    deviation_reason: Mapped[str] = mapped_column(Text, nullable=False, default="")
    calibrated_buffer_factor: Mapped[Decimal | None] = mapped_column(Numeric(4, 2))
    # ---- 每个数字的 claim 状态（§5.3 四值） ----
    field_claims: Mapped[dict[str, Any]] = mapped_column(
        JSON, nullable=False, default=dict
    )

    project: Mapped[Project] = relationship(back_populates="quotes")


class Payment(Base, TimestampMixin):
    """收款与催款（P4，设计 §6；里程碑定义 = seeds/payment_milestones.json 投影）。

    milestone_key 溯源映射表 v1.3（G3/G4/G8/SOW-C M1/M2/M3/D，各带 source_uri +
    content_hash）。状态不落库：received_at 有值=已收，否则 invoice_no 有值=已开票、
    无值=计划。dunning_level 同理读时现算（D+7/15/30/60 四级，工具包 §10 电子化）。
    G8 stop 也按合同结算（SOP）→ settlement_reason='g8_stop' 由门禁引擎联动打标。
    """

    __tablename__ = "payments"
    __table_args__ = (
        UniqueConstraint(
            "project_id", "milestone_key", name="uq_payments_project_milestone"
        ),
        CheckConstraint(
            "sow_type IN ('a', 'b', 'c', 'd')", name="ck_payments_sow_type"
        ),
        CheckConstraint(
            "settlement_reason IS NULL OR settlement_reason IN ('g8_stop')",
            name="ck_payments_settlement_reason",
        ),
        Index("ix_payments_project_id", "project_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    milestone_key: Mapped[str] = mapped_column(String(20), nullable=False)
    sow_type: Mapped[str] = mapped_column(String(1), nullable=False)
    collects: Mapped[str] = mapped_column(String(80), nullable=False)
    timing: Mapped[str] = mapped_column(String(160), nullable=False)
    ratio: Mapped[Decimal | None] = mapped_column(Numeric(4, 2))
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    received_amount: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    due_date: Mapped[date | None] = mapped_column(Date)
    received_at: Mapped[date | None] = mapped_column(Date)
    # P0-4 分成落库（派单设计 §7.2）：验收通过时刻——G8 过门联动打标，
    # 是 delivery_settlements 从 draft → accrued 的起算条件之一（实收 + 验收）。
    # 催款（D+7/15/30/60）读时现算逻辑零改动。
    acceptance_passed_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    invoice_no: Mapped[str | None] = mapped_column(String(60))
    settlement_reason: Mapped[str | None] = mapped_column(String(20))
    note: Mapped[str] = mapped_column(Text, nullable=False, default="")
    source_uri: Mapped[str] = mapped_column(String(500), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)

    project: Mapped[Project] = relationship(back_populates="payments")


class Contract(Base, TimestampMixin, VersionedMixin):
    """合同台账（P4，设计 §6）：只存指针与关键条款摘要，PDF 本体在 fdeops 文件系统。

    每 (project, sow_type) 一行；source_uri 为 fdeops:// 指针（A4：不存内容本体）。
    acceptance_window_days 默认 15（SOP §S4 既有验收窗口）。
    """

    __tablename__ = "contracts"
    __table_args__ = (
        UniqueConstraint("project_id", "sow_type", name="uq_contracts_project_sow"),
        CheckConstraint(
            "sow_type IN ('a', 'b', 'c', 'd')", name="ck_contracts_sow_type"
        ),
        CheckConstraint(
            "acceptance_window_days >= 1", name="ck_contracts_acceptance_window"
        ),
        Index("ix_contracts_project_id", "project_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    sow_type: Mapped[str] = mapped_column(String(1), nullable=False)
    signed_at: Mapped[date | None] = mapped_column(Date)
    payment_terms: Mapped[str] = mapped_column(Text, nullable=False, default="")
    acceptance_window_days: Mapped[int] = mapped_column(
        Integer, nullable=False, default=15
    )
    termination_terms: Mapped[str] = mapped_column(Text, nullable=False, default="")
    source_uri: Mapped[str | None] = mapped_column(String(500))
    content_hash: Mapped[str | None] = mapped_column(String(64))
    note: Mapped[str] = mapped_column(Text, nullable=False, default="")

    project: Mapped[Project] = relationship(back_populates="contracts")


class BridgeEngagement(Base, TimestampMixin):
    """集成桥投影（P2，设计 §4）：真相层 engagement 在 PG 的单向投影。

    A1 铁律：真相在文件（openfde 每 slug 一个 ledger.db / fdeops .registry + 目录），
    本表只是投影，删掉可由宿主采集器（scripts/bridge-poll.mjs）重新采集重建；
    文件永远赢——slug 从最新采集里消失时本行标 stale 由 UI 一键清理，绝不动文件。
    A4 出处指针按轨道分列：source_uri 记采集命令/文件，content_hash 为原始输出 sha256。
    """

    __tablename__ = "bridge_engagements"
    __table_args__ = (
        UniqueConstraint("slug", name="uq_bridge_engagements_slug"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    slug: Mapped[str] = mapped_column(String(80), nullable=False)
    # openfde 轨：status -e <slug> --json 的规范化结果
    openfde_status: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    openfde_synced_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    openfde_source_uri: Mapped[str | None] = mapped_column(String(500))
    openfde_content_hash: Mapped[str | None] = mapped_column(String(64))
    # fdeops 轨：.registry 绑定 + engagement 目录/.fde 探针（CLI 未装机，文件级探针）
    fdeops_state: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    fdeops_synced_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    fdeops_source_uri: Mapped[str | None] = mapped_column(String(500))
    fdeops_content_hash: Mapped[str | None] = mapped_column(String(64))


class BridgeSyncRun(Base, TimestampMixin):
    """集成桥同步日志（P2）：每次采集入库/手动重投影各一行。

    payload 保留原始采集快照——手动「重新投影」用它重放 adapters，
    不触发宿主采集（容器 subprocess 不到 Windows CLI，采集只在宿主侧发生）。
    """

    __tablename__ = "bridge_sync_runs"
    __table_args__ = (
        CheckConstraint(
            "trigger IN ('poller', 'manual_reproject')",
            name="ck_bridge_sync_runs_trigger",
        ),
        Index("ix_bridge_sync_runs_started_at", "started_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    trigger: Mapped[str] = mapped_column(String(20), nullable=False)
    started_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), nullable=False, server_default=UTC_TIMESTAMP_SQL
    )
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    ok: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    engagements_seen: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    # {openfde_slugs: [...], fdeops_slugs: [...], orphan_projects: N, unlinked: N}
    summary: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    error: Mapped[str | None] = mapped_column(Text)
    payload: Mapped[dict[str, Any] | None] = mapped_column(JSON)


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


class AICallAudit(Base, TimestampMixin):
    """E7：每次 AI 供应商调用落一条审计（不含密钥与明文上下文）。

    记录模型/耗时/token 用量/结果状态，供月度 token 预算核算与调用追溯；
    预算超限时也落一条 status='budget_blocked'（未发起任何供应商请求）。

    N2 仪表化（AI 原生化差距台账 G-09/G-16）：
    - ``purpose`` **NOT NULL**（旧行按 ``legacy_unattributed`` 回填）——归因
      账本不允许匿名调用方（调用点强制传 purpose，见 ``ai/auditing.py``）。
    - ``prompt_fingerprint``＝**指令源文本**的 sha256（模板身份：同模板不同
      输入同指纹；提示词正文绝不落库）；``prompt_version``＝提示词版本标签
      （未登记版本者留空，随 G-13 版本注册表逐步填充）。
    """

    __tablename__ = "ai_call_audits"
    __table_args__ = (
        CheckConstraint(
            "status IN ('succeeded', 'failed', 'budget_blocked')",
            name="ck_ai_call_audits_status",
        ),
        CheckConstraint(
            "purpose IS NOT NULL AND length(purpose) >= 1",
            name="ck_ai_call_audits_purpose",
        ),
        Index("ix_ai_call_audits_actor_created", "actor_user_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    request_id: Mapped[str] = mapped_column(String(120), nullable=False)
    actor_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    purpose: Mapped[str] = mapped_column(String(60), nullable=False)
    model: Mapped[str] = mapped_column(String(120), nullable=False)
    used_fallback: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    input_tokens: Mapped[int | None] = mapped_column(Integer)
    output_tokens: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(60))
    prompt_version: Mapped[str | None] = mapped_column(String(60))
    prompt_fingerprint: Mapped[str | None] = mapped_column(String(64))
