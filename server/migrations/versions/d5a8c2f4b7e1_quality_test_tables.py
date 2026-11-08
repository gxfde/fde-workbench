"""V3.1 P1-2：测试计划三表（test_plans/test_cases/test_executions，2026-11-08）。

任务书 §10 目标模型的落地形（00-gap-register P1-2 6.3/6.4 裁决）：
- plans：项目内版本化（draft→approved + superseded；新版本=新行；审核戳两段式）；
- cases：requirement_key 强制追溯 + acceptance_mode（test/manual）闭集；
- executions：append-only（无 UPDATE 路径——失败不可被改写为成功）；
  environment 三值（production 写入唯一通道=服务层硬闸）；报告指针+sha256
  成对 CHECK（证据红线只存指针+指纹）。

evidence_links 第四表不建：测试↔证据关联由既有 project_evidence 登记簿
（提交闸+候选采纳）+ cases.requirement_key 追溯承载，单独关联表是冗余
（gap-register 6.2 复用裁决的隐含判断，偏差注记见 CHANGELOG）。

Backup hint: additive only; downgrade drops child-first
(executions → cases → plans).
"""
import sqlalchemy as sa
from alembic import op


revision = "d5a8c2f4b7e1"
down_revision = "a9c1e5f7b3d8"
branch_labels = None
depends_on = None


def _timestamp_columns() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    ]


def upgrade() -> None:
    op.create_table(
        "test_plans",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("source_task_id", sa.String(length=36), nullable=True),
        sa.Column("created_by_user_id", sa.String(length=36), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="draft", nullable=False),
        sa.Column("reviewed_by_user_id", sa.String(length=36), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("review_comment", sa.String(length=500), nullable=True),
        *_timestamp_columns(),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["source_task_id"], ["project_tasks.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["reviewed_by_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.CheckConstraint(
            "status IN ('draft', 'approved', 'superseded')", name="ck_test_plans_status"
        ),
        sa.CheckConstraint("version >= 1", name="ck_test_plans_version"),
        sa.CheckConstraint(
            "(status = 'draft') = (reviewed_by_user_id IS NULL AND reviewed_at IS NULL)",
            name="ck_test_plans_review_stamp",
        ),
    )
    op.create_index("ix_test_plans_project_status", "test_plans", ["project_id", "status"])
    op.create_table(
        "test_cases",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("plan_id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("created_by_user_id", sa.String(length=36), nullable=False),
        sa.Column("case_key", sa.String(length=40), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("preconditions", sa.Text(), nullable=True),
        sa.Column("steps", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("expected", sa.Text(), nullable=True),
        sa.Column("risk_level", sa.Integer(), nullable=False),
        sa.Column("automated", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("acceptance_mode", sa.String(length=10), server_default="test", nullable=False),
        sa.Column("requirement_key", sa.String(length=40), nullable=False),
        sa.Column("sort_order", sa.Integer(), server_default=sa.text("0"), nullable=False),
        *_timestamp_columns(),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["plan_id"], ["test_plans.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.CheckConstraint("risk_level IN (1, 2, 3)", name="ck_test_cases_risk_level"),
        sa.CheckConstraint(
            "acceptance_mode IN ('test', 'manual')", name="ck_test_cases_acceptance_mode"
        ),
        sa.UniqueConstraint("project_id", "case_key", name="uq_test_cases_project_key"),
    )
    op.create_index("ix_test_cases_plan", "test_cases", ["plan_id"])
    op.create_table(
        "test_executions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("plan_id", sa.String(length=36), nullable=False),
        sa.Column("case_id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("executed_by_user_id", sa.String(length=36), nullable=False),
        sa.Column("environment", sa.String(length=12), nullable=False),
        sa.Column("result", sa.String(length=10), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("report_uri", sa.String(length=500), nullable=True),
        sa.Column("report_sha256", sa.String(length=64), nullable=True),
        sa.Column("note", sa.String(length=500), nullable=True),
        *_timestamp_columns(),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["plan_id"], ["test_plans.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["case_id"], ["test_cases.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["executed_by_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.CheckConstraint(
            "environment IN ('dev', 'staging', 'production')",
            name="ck_test_executions_environment",
        ),
        sa.CheckConstraint("result IN ('passed', 'failed', 'blocked')", name="ck_test_executions_result"),
        sa.CheckConstraint(
            "(report_uri IS NULL) = (report_sha256 IS NULL)", name="ck_test_executions_report_pair"
        ),
        sa.CheckConstraint(
            "report_sha256 IS NULL OR char_length(report_sha256) = 64",
            name="ck_test_executions_report_sha_len",
        ),
    )
    op.create_index("ix_test_executions_project", "test_executions", ["project_id"])
    op.create_index("ix_test_executions_case", "test_executions", ["case_id"])


def downgrade() -> None:
    op.drop_index("ix_test_executions_case", table_name="test_executions")
    op.drop_index("ix_test_executions_project", table_name="test_executions")
    op.drop_table("test_executions")
    op.drop_index("ix_test_cases_plan", table_name="test_cases")
    op.drop_table("test_cases")
    op.drop_index("ix_test_plans_project_status", table_name="test_plans")
    op.drop_table("test_plans")
