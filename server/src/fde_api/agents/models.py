"""agents 模型：S1 编程工作台最小闭环的表簇（goal-d3，技术实施方案 §2）。

字段来源：架构方案 §9（SQLAlchemy 风格原文）+ 自动交付 §5.1 增量
（degraded/retry/idempotency/cost_owner + agent_tool_calls denied 留痕 +
agent_registry.allowed_tools 声明式白名单）+ 技术文档 §2 决议增量
（agent_registry.kind 含 persona）。本轮只落表簇与沙箱基座；REST 蓝图
（agents 7 路由）与 zcode 适配器归 goal-d4，review_meetings 三表归 d5。

溯源红线：agent 产物只存 storage_ref 指针 + sha256 指纹（架构方案 §6.6），
证据原件永不进仓库/数据库；agent_credentials 为 Fernet 密文，绝不回显。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from fde_api.workbench.models import Base, TimestampMixin, new_uuid


class AgentRegistry(Base, TimestampMixin):
    """外部编程智能体注册表（架构方案 §9；心智复用 FDE_DSH_MARKET）。"""

    __tablename__ = "agent_registry"
    __table_args__ = (
        CheckConstraint(
            "kind IN ('zcode', 'codex', 'claude_code', 'opencode', 'persona')",
            name="ck_agent_registry_kind",
        ),
        CheckConstraint("max_cost_units >= 0", name="ck_agent_registry_max_cost"),
        CheckConstraint("max_duration_ms >= 0", name="ck_agent_registry_max_duration"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    # persona = 角色卡（S2 多模块编排/PM-2 防火墙），不是可执行外部 CLI
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    # capability_tier 关联 CAPABILITY_REQUIREMENTS 的 agent.* 能力名
    capability_tier: Mapped[str] = mapped_column(String(64), nullable=False)
    sandbox_profile: Mapped[str] = mapped_column(String(64), nullable=False)
    max_cost_units: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    max_duration_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    # 指向 agent_credentials（或外部密钥代号）；本身不是 FK——注册表可先于凭据存在
    credential_ref: Mapped[str | None] = mapped_column(String(120))
    # 声明式工具白名单（自动交付 §5.1）：与 run 时 AgentRunContext.allowed_tools 求交集
    allowed_tools: Mapped[list[Any]] = mapped_column(JSON, nullable=False, default=list)


class AgentRun(Base, TimestampMixin):
    """agent 执行记录：溯源 + 成本 + 降级/重试/幂等链（自动交付 §5.1 增量）。"""

    __tablename__ = "agent_runs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('queued', 'running', 'completed', 'failed', 'timeout', 'budget_exceeded')",
            name="ck_agent_runs_status",
        ),
        CheckConstraint(
            "fallback_level IS NULL OR fallback_level IN ('L0', 'L1', 'L2', 'L3')",
            name="ck_agent_runs_fallback_level",
        ),
        CheckConstraint(
            "cost_owner_type IN ('project', 'seat', 'platform')",
            name="ck_agent_runs_cost_owner_type",
        ),
        CheckConstraint(
            "difficulty IN ('standard', 'high')",
            name="ck_agent_runs_difficulty",
        ),
        CheckConstraint("token_cost >= 0", name="ck_agent_runs_token_cost"),
        CheckConstraint("duration_ms >= 0", name="ck_agent_runs_duration"),
        Index("ix_agent_runs_project_status", "project_id", "status"),
        # 幂等键只建索引不设唯一：重试行与原 run 共享同一 key，幂等去重语义
        # 在服务层（d4）按 retry_of 链收敛，唯一约束会封死重试链。
        Index("ix_agent_runs_idempotency", "idempotency_key"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False)
    agent_id: Mapped[str] = mapped_column(ForeignKey("agent_registry.id", ondelete="RESTRICT"), nullable=False)
    # 实时鉴权人（架构方案 §6.4：权限回收即时生效，发起人即责任人）
    initiated_by_user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    capability_used: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="queued", server_default="queued")
    # 脱敏上下文指针（只指 masked_context 渲染产物，绝不指真相层）
    context_ref: Mapped[str] = mapped_column(String(255), nullable=False)
    token_cost: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    exit_code: Mapped[int | None] = mapped_column(Integer)
    # —— 自动交付 §5.1 增量：降级链 ——
    degraded: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    # 对应自动交付 §3.2 异常分类（A/B/C/D/E）
    degraded_reason: Mapped[str | None] = mapped_column(String(32))
    fallback_level: Mapped[str | None] = mapped_column(String(8))
    # 重试链软引用：故意不设 FK——允许指向已归档清理的 run，硬 RESTRICT 会
    # 制造清理死锁（偏离架构方案原文处，goal-d3 报告 §二 登记）。
    retry_of: Mapped[str | None] = mapped_column(String(36))
    # 幂等键 = solution_id + 上下文指纹（自动交付 §5.1）
    idempotency_key: Mapped[str] = mapped_column(String(160), nullable=False)
    # 成本归属（O-3 d7 定稿：沙箱 run 按 project 归集——自动交付 §6 归属分层）
    cost_owner_type: Mapped[str] = mapped_column(
        String(16), nullable=False, default="project", server_default="project"
    )
    cost_owner_id: Mapped[str | None] = mapped_column(String(64))
    # L3 转人工接管人（自动交付 §3.5 收口）
    handoff_user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    # T4 高难度加座的 run 侧事实（总纲 §2.2 T4）：发起人声明，责任人人工承担；
    # 派单订单难度自动带入随 d8（goal-d7 报告 §二 决议 2）
    difficulty: Mapped[str] = mapped_column(
        String(16), nullable=False, default="standard", server_default="standard"
    )


class AgentArtifact(Base, TimestampMixin):
    """agent 产物溯源：storage_ref 指针 + sha256 指纹（红线 §6.6）。"""

    __tablename__ = "agent_artifacts"
    __table_args__ = (
        CheckConstraint("kind IN ('code', 'doc', 'diff', 'config')", name="ck_agent_artifacts_kind"),
        # 红线列完整性：指纹必须是完整 64hex，短指纹/占位符一律拒绝
        CheckConstraint("char_length(sha256) = 64", name="ck_agent_artifacts_sha256_len"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    run_id: Mapped[str] = mapped_column(ForeignKey("agent_runs.id", ondelete="RESTRICT"), nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    # source_uri 风格指针（证据原件留在项目工作目录，不进仓库/数据库）
    storage_ref: Mapped[str] = mapped_column(String(255), nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    # 终审流标记（技术文档 §2 决议增量；V 判定用）
    reviewed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    linked_solution_id: Mapped[str | None] = mapped_column(
        ForeignKey("project_solutions.id", ondelete="RESTRICT")
    )


class AgentToolCall(Base, TimestampMixin):
    """工具调用留痕：越权可反查（自动交付 §5.1；denied 必留痕）。"""

    __tablename__ = "agent_tool_calls"
    __table_args__ = (
        CheckConstraint("decision IN ('allowed', 'denied')", name="ck_agent_tool_calls_decision"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    run_id: Mapped[str] = mapped_column(ForeignKey("agent_runs.id", ondelete="RESTRICT"), nullable=False)
    # 对应 mcp_gateway 工具名
    tool_name: Mapped[str] = mapped_column(String(120), nullable=False)
    decision: Mapped[str] = mapped_column(String(16), nullable=False)
    # 判定时所用 capability（白名单交集/能力门槛的共同输入）
    capability: Mapped[str] = mapped_column(String(64), nullable=False)
    # denied 原因（capability_missing / not_in_allowlist 等）
    reason: Mapped[str | None] = mapped_column(String(120))
    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")


class AgentCredential(Base, TimestampMixin):
    """加密凭据（架构方案 §6.4）：Fernet 密文入库，绝不回显。

    加密先例沿用 ModelPreference（control/model_preferences.py）：密钥来自
    FDE_MODEL_CREDENTIAL_KEY，缺省派生自 jwt_secret；解密只发生在 d4 的
    沙箱注入时刻，任何序列化路径只出 name 不出密文。
    """

    __tablename__ = "agent_credentials"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    credential_ciphertext: Mapped[str] = mapped_column(Text, nullable=False)
    # system_operator 才能配置（§6.4 凭证分层）；可空留系统级种子凭据
    created_by_user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))


class SeatActionLedger(Base, TimestampMixin):
    """O-3 额度台账（goal-d7）：一次工作台动作 = 一条行，seat 归集。

    一次动作 = 一次完整管道（自动交付 §6）：agent_run=一次方案生成 /
    meeting_convene=一场评审会（工具面；人工开会不占额度）/
    ai_chat=一次预调研分析（worker 成功就绪时计）。超额只标注不拦截
    （over_quota=透明计价加油包的标注位）——「交付中途绝不静默断供」。
    演练 run（idempotency_key rehearsal: 前缀）零计量。
    """

    __tablename__ = "seat_action_ledger"
    __table_args__ = (
        CheckConstraint(
            "action_type IN ('agent_run', 'meeting_convene', 'ai_chat')",
            name="ck_seat_action_ledger_action_type",
        ),
        CheckConstraint("units >= 0", name="ck_seat_action_ledger_units"),
        Index("ix_seat_action_ledger_user_created", "user_id", "created_at"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False)
    # seat 归集键：动作发起人（run 发起人 / 召集触发 run 的发起人 / 分析创建人）
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    action_type: Mapped[str] = mapped_column(String(24), nullable=False)
    # 溯源指针：run id / meeting id / analysis id（软引用不设 FK，沿
    # agent_runs.retry_of 偏离先例——被引用行允许归档清理）
    ref_id: Mapped[str | None] = mapped_column(String(64))
    units: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    over_quota: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")


class SolutionReviewCheckpoint(Base, TimestampMixin):
    """方案审核节点（E5 人工闸门）：template/rule/knowledge/signoff 四类。"""

    __tablename__ = "solution_review_checkpoints"
    __table_args__ = (
        CheckConstraint(
            "checkpoint_type IN ('template', 'rule', 'knowledge', 'signoff')",
            name="ck_solution_review_checkpoints_type",
        ),
        # 沿用 ACCESS_RANK 四档（disabled 是撤销态，不作为要求档）
        CheckConstraint(
            "required_level IN ('assistant_read', 'project_operator', 'project_manager', 'system_operator')",
            name="ck_solution_review_checkpoints_level",
        ),
        CheckConstraint(
            "status IN ('pending', 'approved', 'rejected')",
            name="ck_solution_review_checkpoints_status",
        ),
        Index("ix_solution_review_checkpoints_solution", "solution_id", "status"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    solution_id: Mapped[str] = mapped_column(
        ForeignKey("project_solutions.id", ondelete="RESTRICT"), nullable=False
    )
    checkpoint_type: Mapped[str] = mapped_column(String(32), nullable=False)
    required_level: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending", server_default="pending")
    reviewer_user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    # 证据只存指针（红线：原件留项目工作目录）
    evidence_ref: Mapped[str | None] = mapped_column(String(255))
