"""Workflow 定义与运行表（V3 T-W1 定义层 / T-W2 运行层；设计 workflow-dag-v1 §2）。

决策 3：**不复制队列**——workflow 将来是 background_jobs 的一个 job_type；本模块
只有「定义 + 不可变版本 + 运行 + 节点运行」四表，执行器（T-W3）后续落地。
版本化沿 WB 已验证的「定义 + 版本行」双表（skill_definitions / skill_versions 同构）：
定义行可改（draft），发布即把 dag_json 快照成版本行，**版本行不可变**；已发布定义
再改动会自动开新草稿版本（version+1），运行时固定引用版本号（fde-v2 教训：跑动中
被改即受影响）。

T-W2：run 固定 (definition_id, definition_version)，run 级 idempotency_key 全局唯一
（修 fde-v2 FV-F3：flow 无幂等重跑重复建单）；node_run 冗余 depends_on 快照，外副作用
节点另有业务幂等键（api_actions sha256 模式，T-W3 执行器强制）。
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import CheckConstraint, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from fde_api.auth.models import UTCDateTime
from fde_api.workbench.models import Base, TimestampMixin, new_uuid

WORKFLOW_STATUSES = ("draft", "published", "archived")
# 没有 condition/wait 节点——when 表达式与 depends_on 已覆盖既有需求；新类型待真实需求
NODE_TYPES = ("call", "skill", "agent", "human_approval")
# ready = 依赖全绿待调度（T-W3 执行器的调度循环状态）；waiting 供 human_approval
# 「paused」= 预留值域·当前无写入方（run 永不进入 paused）。2026-11-08 架构评估
# P2-6 拍板：保留 CHECK（不收窄、不迁移），用机械钉把它钉成「登记在册的预留值」
# ——形状钉与写入方钉见 server/tests/test_workflow_run_status_domain.py。
RUN_STATUSES = (
    "queued",
    "running",
    "waiting_approval",
    "paused",
    "succeeded",
    "failed",
    "cancelled",
)
NODE_RUN_STATUSES = (
    "pending",
    "ready",
    "running",
    "waiting",
    "succeeded",
    "failed",
    "skipped",
    "cancelled",
)


class WorkflowDefinition(Base, TimestampMixin):
    __tablename__ = "workflow_definitions"
    __table_args__ = (
        CheckConstraint(
            "status IN ('draft', 'published', 'archived')", name="ck_workflow_definitions_status"
        ),
        CheckConstraint("version >= 1", name="ck_workflow_definitions_version"),
        Index("ix_workflow_definitions_project_status", "project_id", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    # NULL = 平台模板（仅 admin），非 NULL = 项目内定义
    project_id: Mapped[str | None] = mapped_column(ForeignKey("projects.id", ondelete="RESTRICT"))
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    dag_json: Mapped[dict[str, Any]] = mapped_column(
        JSON, nullable=False, default=dict, server_default=text("'{}'")
    )
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="draft", server_default="draft"
    )
    # 当前（草稿或已发布）版本号；发布时快照到版本行，再改动则 +1 开新草稿
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default=text("1"))
    # dag_json 规范化（sort_keys/紧凑）后的 sha256
    content_sha256: Mapped[str | None] = mapped_column(String(64))
    created_by_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    published_by_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    published_at: Mapped[datetime | None] = mapped_column(UTCDateTime())


class WorkflowDefinitionVersion(Base, TimestampMixin):
    """发布快照：一行 = 一个被锁定的 dag_json 版本，**写后不可变**。"""

    __tablename__ = "workflow_definition_versions"
    __table_args__ = (
        UniqueConstraint(
            "definition_id", "version", name="uq_workflow_definition_versions_definition_version"
        ),
        CheckConstraint("version >= 1", name="ck_workflow_definition_versions_version"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    definition_id: Mapped[str] = mapped_column(
        ForeignKey("workflow_definitions.id", ondelete="CASCADE"), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    dag_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    published_by_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    published_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)


class WorkflowRun(Base, TimestampMixin):
    """一次执行：固定 (definition_id, definition_version)（fde-v2 教训：跑动中被改即受影响）。

    idempotency_key 全局唯一（修 fde-v2 FV-F3：flow 无幂等，重跑重复建单）；执行器
    在 T-W3 落地，本表只承载状态与结果。
    """

    __tablename__ = "workflow_runs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('queued', 'running', 'waiting_approval', 'paused', "
            "'succeeded', 'failed', 'cancelled')",
            name="ck_workflow_runs_status",
        ),
        CheckConstraint(
            "definition_version >= 1", name="ck_workflow_runs_definition_version"
        ),
        UniqueConstraint("idempotency_key", name="uq_workflow_runs_idempotency_key"),
        Index("ix_workflow_runs_project_status", "project_id", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    # RESTRICT：run 是执行史证据，定义删除不得静默带走（版本行 CASCADE 是定义内部
    # 快照，语义不同）；清库走 conftest 的子表先行顺序
    definition_id: Mapped[str] = mapped_column(
        ForeignKey("workflow_definitions.id", ondelete="RESTRICT"), nullable=False
    )
    definition_version: Mapped[int] = mapped_column(Integer, nullable=False)
    # 运行永远属于某个项目（平台模板也在项目上下文里实例化执行）
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="queued", server_default="queued"
    )
    initiated_by_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    # 调用方业务幂等键（如同方案同 key 重提交 → 数据库层即拒绝重复建 run）
    idempotency_key: Mapped[str] = mapped_column(String(120), nullable=False)
    # 运行级入参（占位符 {{project_id}}/{{run_id}} 等的解析源）
    context_json: Mapped[dict[str, Any]] = mapped_column(
        JSON, nullable=False, default=dict, server_default=text("'{}'")
    )
    error: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    # B#1 跳数熔断（agent-autoloop decide 语义）：跨「重投代际」累加的链长
    # 计数——resume_run（拍板重投）每次 +1，继承不清零；执行器入口超
    # MAX_RUN_HOPS 直接 honest failed(hops_exceeded)，封顶自触发链。
    hops: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )


class WorkflowNodeRun(Base, TimestampMixin):
    """节点级执行：一行 = 一个节点在该 run 内的状态机；恢复时只重跑未完成节点。

    depends_on 是定义侧冗余快照（定义后续演进不影响历史 run 的可追溯性）；
    外副作用节点（effect=external）的业务幂等键由 T-W3 执行器强制必填。
    """

    __tablename__ = "workflow_node_runs"
    __table_args__ = (
        UniqueConstraint("run_id", "node_key", name="uq_workflow_node_runs_run_node"),
        CheckConstraint(
            "node_type IN ('call', 'skill', 'agent', 'human_approval')",
            name="ck_workflow_node_runs_node_type",
        ),
        CheckConstraint(
            "status IN ('pending', 'ready', 'running', 'waiting', 'succeeded', "
            "'failed', 'skipped', 'cancelled')",
            name="ck_workflow_node_runs_status",
        ),
        Index("ix_workflow_node_runs_run_status", "run_id", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    run_id: Mapped[str] = mapped_column(
        ForeignKey("workflow_runs.id", ondelete="CASCADE"), nullable=False
    )
    node_key: Mapped[str] = mapped_column(String(60), nullable=False)
    node_type: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="pending", server_default="pending"
    )
    # 已尝试次数（含进行中这次）；重试策略在 T-W3 的调度循环里消费
    attempt: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    depends_on: Mapped[list[str] | None] = mapped_column(JSON)
    # 外副作用节点的业务幂等键（api_actions sha256 模式）；T-W3 强制，表级可空
    idempotency_key: Mapped[str | None] = mapped_column(String(120))
    # 占位符填充后的实际输入（执行前落，审计可回放）
    input_snapshot: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    # 成功产物（下游 {{output}} 占位符的解析源）
    output_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    error: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
