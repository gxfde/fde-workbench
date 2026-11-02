"""Workflow 运行层两表（V3 T-W2，设计 workflow-dag-v1 §2）

workflow_runs（一次执行：固定 (definition_id, definition_version)，idempotency_key
全局唯一——修 fde-v2 FV-F3 无幂等重跑重复建单）+ workflow_node_runs（节点级状态机，
UNIQUE(run_id, node_key)，depends_on 冗余快照）。纯增量零改既有表；执行器随 T-W3。

Backup hint: additive only (two new tables); downgrade drops them child-first.
"""
import sqlalchemy as sa
from alembic import op

revision = "b7d9f1a3c5e2"
down_revision = "f2a4c6e8b1d3"
branch_labels = None
depends_on = None


def _timestamp_columns() -> list[sa.Column]:
    return [
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    ]


def upgrade() -> None:
    op.create_table(
        "workflow_runs",
        sa.Column("id", sa.String(length=36), nullable=False),
        # RESTRICT：run 是执行史证据，定义删除不得静默带走
        sa.Column("definition_id", sa.String(length=36), nullable=False),
        # 运行固定版本（fde-v2 教训：跑动中被改即受影响）
        sa.Column("definition_version", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("status", sa.String(length=20), server_default="queued", nullable=False),
        sa.Column("initiated_by_user_id", sa.String(length=36), nullable=True),
        # 调用方业务幂等键：同方案重提交在数据库层即拒绝（FV-F3）
        sa.Column("idempotency_key", sa.String(length=120), nullable=False),
        # 运行级入参（占位符解析源）
        sa.Column("context_json", sa.JSON(), server_default=sa.text("'{}'"), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamp_columns(),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["definition_id"], ["workflow_definitions.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["initiated_by_user_id"], ["users.id"], ondelete="SET NULL"
        ),
        sa.UniqueConstraint("idempotency_key", name="uq_workflow_runs_idempotency_key"),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'waiting_approval', 'paused', "
            "'succeeded', 'failed', 'cancelled')",
            name="ck_workflow_runs_status",
        ),
        sa.CheckConstraint(
            "definition_version >= 1", name="ck_workflow_runs_definition_version"
        ),
    )
    op.create_index(
        "ix_workflow_runs_project_status",
        "workflow_runs",
        ["project_id", "status"],
    )
    op.create_table(
        "workflow_node_runs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("run_id", sa.String(length=36), nullable=False),
        sa.Column("node_key", sa.String(length=60), nullable=False),
        sa.Column("node_type", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=20), server_default="pending", nullable=False),
        sa.Column("attempt", sa.Integer(), server_default=sa.text("0"), nullable=False),
        # 定义侧冗余快照（历史 run 可追溯，不随定义演进漂移）
        sa.Column("depends_on", sa.JSON(), nullable=True),
        # 外副作用节点业务幂等键（api_actions sha256 模式）；T-W3 执行器强制必填
        sa.Column("idempotency_key", sa.String(length=120), nullable=True),
        # 占位符填充后的实际输入（执行前落，审计可回放）
        sa.Column("input_snapshot", sa.JSON(), nullable=True),
        sa.Column("output_json", sa.JSON(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamp_columns(),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["run_id"], ["workflow_runs.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("run_id", "node_key", name="uq_workflow_node_runs_run_node"),
        sa.CheckConstraint(
            "node_type IN ('call', 'skill', 'agent', 'human_approval')",
            name="ck_workflow_node_runs_node_type",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'ready', 'running', 'waiting', 'succeeded', "
            "'failed', 'skipped', 'cancelled')",
            name="ck_workflow_node_runs_status",
        ),
    )
    op.create_index(
        "ix_workflow_node_runs_run_status",
        "workflow_node_runs",
        ["run_id", "status"],
    )


def downgrade() -> None:
    op.drop_index("ix_workflow_node_runs_run_status", table_name="workflow_node_runs")
    op.drop_table("workflow_node_runs")
    op.drop_index("ix_workflow_runs_project_status", table_name="workflow_runs")
    op.drop_table("workflow_runs")
