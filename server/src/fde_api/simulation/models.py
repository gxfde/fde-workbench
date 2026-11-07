"""模拟场景库表（V3.2 G2）。

一行 = 一个**不可变版本快照**：(scenario_key, version)。内容变更不原地改，
而是追加新版本行——历史 run 永远可复现（G1 §4.4）。

列职责（**故意**不与既有域混用）：
- ``content_json``：客户侧真相 + 场景机制（客户画像、初始简报、隐藏事实、
  变体覆盖、故障注入、虚拟种子数据）。
- ``reference_json``：评分侧（预期结果、验收标准、Rubric、参考方案/工作流）。
  **只允许 Judge View 装载**；Tester View 装载器递归断言其不存在。

隔离纪律：表里**没有** ``project_id`` 列——这不是遗漏，是 P1 设计的落点。
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from fde_api.workbench.models import Base, TimestampMixin, VersionedMixin, new_uuid

# 客户行为变体（G1 §4.1：每案例三变体 → 18 个基础模拟任务）
SCENARIO_VARIANTS = ("normal", "vague", "complex")
# 数据集三分（G1 §11.1）：train 允许用于提改进；regression 检退化；blind 最终盲测
SCENARIO_SPLITS = ("train", "regression", "blind")
SCENARIO_STATUSES = ("draft", "active", "archived")
# 难度档（初版：basic 用于最小可跑样本）
SCENARIO_DIFFICULTIES = ("basic", "standard", "hard")
# 来源：seed=内置案例种子 / manual=人工创建 / import=导入
SCENARIO_SOURCE_KINDS = ("seed", "manual", "import")

# ---- 运行层（G3）----------------------------------------------------------
# 运行状态机：queued → running →（completed | failed | failed_hard | timeout | cancelled）
# failed_hard＝硬性失败命中（不可被其他维度高分抵消，且不可重试）
RUN_STATUSES = (
    "queued",
    "running",
    "awaiting_approval",
    "completed",
    "failed",
    "failed_hard",
    "timeout",
    "cancelled",
)
# 终态集合（不可再推进）
RUN_TERMINAL_STATUSES = ("completed", "failed", "failed_hard", "timeout", "cancelled")
# 适配模式：real＝委托 V3.1 既有执行面；mock＝明确标记的脚本化替身（G1 §8.3）
ADAPTER_MODES = ("real", "mock")
# 角色（G1 §5.1 六类）
ACTOR_ROLES = (
    "customer",
    "fde_consultant",
    "domain_expert",
    "architect",
    "implementer",
    "acceptance_reviewer",
)
# Trace 相位（G1 §5.4）
TRACE_PHASES = (
    "setup",
    "interview",
    "analysis",
    "design",
    "implementation",
    "validation",
    "wrapup",
)
# 工具白名单前缀（G1 §6.3）：只有 sim.* 工具在模拟面可达
SIM_TOOL_PREFIX = "sim."


class SimulationScenario(Base, TimestampMixin, VersionedMixin):
    """模拟场景版本行：案例库的唯一权威载体。"""

    __tablename__ = "simulation_scenarios"
    __table_args__ = (
        # 业务键 × 变体 × 版本：同一案例的三个客户行为变体是三条**独立分支**，
        # 各自版本化（案例是 key，变体是分支，不是三个 key）。
        UniqueConstraint(
            "scenario_key",
            "variant",
            "version",
            name="uq_simulation_scenarios_key_variant_version",
        ),
        CheckConstraint(
            "variant IN ('normal', 'vague', 'complex')",
            name="ck_simulation_scenarios_variant",
        ),
        CheckConstraint(
            "split IN ('train', 'regression', 'blind')",
            name="ck_simulation_scenarios_split",
        ),
        CheckConstraint(
            "status IN ('draft', 'active', 'archived')",
            name="ck_simulation_scenarios_status",
        ),
        CheckConstraint(
            "difficulty IN ('basic', 'standard', 'hard')",
            name="ck_simulation_scenarios_difficulty",
        ),
        CheckConstraint(
            "source_kind IN ('seed', 'manual', 'import')",
            name="ck_simulation_scenarios_source_kind",
        ),
        Index("ix_simulation_scenarios_split_status", "split", "status"),
        Index("ix_simulation_scenarios_industry", "industry"),
        Index("ix_simulation_scenarios_key", "scenario_key"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    # 稳定业务键（如 CASE-A-QUALITY-TRACE）；跨版本不变
    scenario_key: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    industry: Mapped[str] = mapped_column(String(64), nullable=False)
    variant: Mapped[str] = mapped_column(String(16), nullable=False, default="normal")
    difficulty: Mapped[str] = mapped_column(String(16), nullable=False, default="standard")
    split: Mapped[str] = mapped_column(String(16), nullable=False, default="train")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="draft")
    # 分类标签（G2 要求「案例分类和标签」）：行业之外的自由标签
    tags: Mapped[list[Any]] = mapped_column(JSON, nullable=False, default=list)
    content_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    reference_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    rubric_version: Mapped[str] = mapped_column(String(32), nullable=False, default="rubric-v1")
    source_kind: Mapped[str] = mapped_column(String(16), nullable=False, default="manual")
    source_ref: Mapped[str | None] = mapped_column(String(200))
    created_by_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    note: Mapped[str | None] = mapped_column(Text)


class SimulationRun(Base, TimestampMixin):
    """一次模拟运行（G3）。

    **没有** ``project_id`` 列——模拟运行不属于任何真实项目（G1 §3.2 P1）。
    ``scenario_id`` + ``scenario_version`` 冻结场景快照，历史 run 永远可复现。
    ``adapter_mode`` 显式记录本次实际走的执行面（real/mock），**不静默降级**。
    """

    __tablename__ = "simulation_runs"
    __table_args__ = (
        UniqueConstraint("run_key", name="uq_simulation_runs_run_key"),
        CheckConstraint(
            "status IN ('queued', 'running', 'awaiting_approval', 'completed', "
            "'failed', 'failed_hard', 'timeout', 'cancelled')",
            name="ck_simulation_runs_status",
        ),
        CheckConstraint(
            "adapter_mode IN ('real', 'mock')",
            name="ck_simulation_runs_adapter_mode",
        ),
        CheckConstraint(
            "split IN ('train', 'regression', 'blind')",
            name="ck_simulation_runs_split",
        ),
        Index("ix_simulation_runs_scenario_status", "scenario_id", "status"),
        Index("ix_simulation_runs_split_created", "split", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    # 幂等键 = scenario + version + seed + attempt（重试派生新键，不串号）
    run_key: Mapped[str] = mapped_column(String(200), nullable=False)
    scenario_id: Mapped[str] = mapped_column(
        ForeignKey("simulation_scenarios.id", ondelete="RESTRICT"), nullable=False
    )
    scenario_version: Mapped[int] = mapped_column(Integer, nullable=False)
    split: Mapped[str] = mapped_column(String(16), nullable=False, default="train")
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="queued")
    adapter_mode: Mapped[str] = mapped_column(String(8), nullable=False, default="mock")
    seed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    # 本次运行的角色编排快照（角色 → 配置），保证复现
    actor_set_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    context_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    cost_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    error_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    started_at: Mapped[str | None] = mapped_column(String(32))
    finished_at: Mapped[str | None] = mapped_column(String(32))
    created_by_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )


class SimulationActor(Base, TimestampMixin):
    """运行内的角色实例（G3）：角色身份 + 披露状态 + 配置快照。"""

    __tablename__ = "simulation_actors"
    __table_args__ = (
        UniqueConstraint("run_id", "role", name="uq_simulation_actors_run_role"),
        CheckConstraint(
            "role IN ('customer', 'fde_consultant', 'domain_expert', 'architect', "
            "'implementer', 'acceptance_reviewer')",
            name="ck_simulation_actors_role",
        ),
        Index("ix_simulation_actors_run", "run_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    run_id: Mapped[str] = mapped_column(
        ForeignKey("simulation_runs.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[str] = mapped_column(String(24), nullable=False)
    display_name: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    # 客户模拟器的披露状态（已披露事实 id 列表、追问计数等）
    state_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    config_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)


class SimulationTrace(Base, TimestampMixin):
    """模拟过程留痕（G3）：调用 / 状态变化 / 产物 / 证据，全量可回查。"""

    __tablename__ = "simulation_traces"
    __table_args__ = (
        UniqueConstraint("run_id", "seq", name="uq_simulation_traces_run_seq"),
        CheckConstraint(
            "phase IN ('setup', 'interview', 'analysis', 'design', 'implementation', "
            "'validation', 'wrapup')",
            name="ck_simulation_traces_phase",
        ),
        Index("ix_simulation_traces_run_phase", "run_id", "phase"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    run_id: Mapped[str] = mapped_column(
        ForeignKey("simulation_runs.id", ondelete="CASCADE"), nullable=False
    )
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    parent_seq: Mapped[int | None] = mapped_column(Integer)
    actor_id: Mapped[str | None] = mapped_column(
        ForeignKey("simulation_actors.id", ondelete="SET NULL")
    )
    phase: Mapped[str] = mapped_column(String(16), nullable=False)
    event_type: Mapped[str] = mapped_column(String(48), nullable=False)
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    tool_call_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    state_before_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    state_after_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    evidence_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    cost_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
