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
