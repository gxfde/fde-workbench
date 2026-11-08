"""quality 模型：测试计划三表（V3.1 P1-2，任务书 §10；00-gap-register 6.3 新建裁决）。

- ``test_plans``：项目内版本化计划（draft→approved + superseded；新版本=新行
  不覆盖历史，沿 delivery_plans 先例）；审核戳 CHECK 两段式。
- ``test_cases``：用例（requirement_key 强制追溯——任务书「测试用例可追溯需求」；
  acceptance_mode 区分测试/明确人工验收方式；审核语义由计划 draft→approved
  承载——「模型生成用例先审核」的落点，AI 用例通道为未来增强）。
- ``test_executions``：append-only 执行史（结果行无更新路径，失败不可被摘要
  Agent 改写为成功——重跑=新行）；environment 值域含 production 仅为形状完备，
  **写入唯一通道=服务层硬闸 409 production_forbidden**（任务书「生产环境测试
  默认禁止」）；报告只存指针+sha256（证据红线）。
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from fde_api.auth.models import UTCDateTime
from fde_api.workbench.models import Base, TimestampMixin, new_uuid

PLAN_STATUSES = ("draft", "approved", "superseded")
EXECUTION_ENVIRONMENTS = ("dev", "staging", "production")
EXECUTION_RESULTS = ("passed", "failed", "blocked")
ACCEPTANCE_MODES = ("test", "manual")
CASE_KEY_MAX = 40


class TestPlan(Base, TimestampMixin):
    """测试计划行（项目内版本化；同一时刻至多一个 approved）。"""

    __tablename__ = "test_plans"
    __table_args__ = (
        CheckConstraint("status IN ('draft', 'approved', 'superseded')", name="ck_test_plans_status"),
        CheckConstraint("version >= 1", name="ck_test_plans_version"),
        CheckConstraint(
            "(status = 'draft') = (reviewed_by_user_id IS NULL AND reviewed_at IS NULL)",
            name="ck_test_plans_review_stamp",
        ),
        Index("ix_test_plans_project_status", "project_id", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False
    )
    # 生成来源任务（任务书 API 挂任务语义；可空=项目级生成）
    source_task_id: Mapped[str | None] = mapped_column(
        ForeignKey("project_tasks.id", ondelete="RESTRICT")
    )
    created_by_user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="draft", server_default="draft")
    reviewed_by_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT")
    )
    reviewed_at: Mapped[Any] = mapped_column(UTCDateTime(), nullable=True)
    review_comment: Mapped[str | None] = mapped_column(String(500))


class TestCase(Base, TimestampMixin):
    """测试用例（requirement_key 强制追溯；审核随计划闸）。"""

    __tablename__ = "test_cases"
    __table_args__ = (
        CheckConstraint("risk_level IN (1, 2, 3)", name="ck_test_cases_risk_level"),
        CheckConstraint("acceptance_mode IN ('test', 'manual')", name="ck_test_cases_acceptance_mode"),
        UniqueConstraint("project_id", "case_key", name="uq_test_cases_project_key"),
        Index("ix_test_cases_plan", "plan_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    plan_id: Mapped[str] = mapped_column(
        ForeignKey("test_plans.id", ondelete="CASCADE"), nullable=False
    )
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False
    )
    created_by_user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    case_key: Mapped[str] = mapped_column(String(40), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    preconditions: Mapped[str | None] = mapped_column(Text)
    # 步骤数组（结构化；确定性生成留待人工补齐）
    steps: Mapped[list[Any]] = mapped_column(JSON, nullable=False, default=list, server_default="[]")
    expected: Mapped[str | None] = mapped_column(Text)
    risk_level: Mapped[int] = mapped_column(Integer, nullable=False)
    automated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    # test=测试用例；manual=明确人工验收方式（任务书「至少有测试或明确人工验收
    # 方式」——两者都计入需求覆盖）
    acceptance_mode: Mapped[str] = mapped_column(String(10), nullable=False, default="test", server_default="test")
    # 需求追溯（强制非空：每条用例可溯一条已批准需求）
    requirement_key: Mapped[str] = mapped_column(String(40), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")


class TestExecution(Base, TimestampMixin):
    """执行记录（append-only；报告只存指针+sha256）。"""

    __tablename__ = "test_executions"
    __table_args__ = (
        CheckConstraint(
            "environment IN ('dev', 'staging', 'production')", name="ck_test_executions_environment"
        ),
        CheckConstraint("result IN ('passed', 'failed', 'blocked')", name="ck_test_executions_result"),
        CheckConstraint(
            "(report_uri IS NULL) = (report_sha256 IS NULL)", name="ck_test_executions_report_pair"
        ),
        CheckConstraint(
            "report_sha256 IS NULL OR char_length(report_sha256) = 64",
            name="ck_test_executions_report_sha_len",
        ),
        Index("ix_test_executions_project", "project_id"),
        Index("ix_test_executions_case", "case_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    plan_id: Mapped[str] = mapped_column(
        ForeignKey("test_plans.id", ondelete="RESTRICT"), nullable=False
    )
    case_id: Mapped[str] = mapped_column(
        ForeignKey("test_cases.id", ondelete="RESTRICT"), nullable=False
    )
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False
    )
    executed_by_user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    environment: Mapped[str] = mapped_column(String(12), nullable=False)
    result: Mapped[str] = mapped_column(String(10), nullable=False)
    started_at: Mapped[Any] = mapped_column(UTCDateTime(), nullable=True)
    finished_at: Mapped[Any] = mapped_column(UTCDateTime(), nullable=True)
    report_uri: Mapped[str | None] = mapped_column(String(500))
    report_sha256: Mapped[str | None] = mapped_column(String(64))
    note: Mapped[str | None] = mapped_column(String(500))
