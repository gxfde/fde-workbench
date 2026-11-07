"""V3.2 G3：模拟运行三表（simulation_runs / simulation_actors / simulation_traces）

FDE 交付模拟训练场的运行层：一次运行（run）、运行内的六类角色实例（actor）、
以及全量过程留痕（trace）。

隔离纪律（V3.2 P1）：三张表**都没有** project_id 列——模拟运行不属于任何真实
项目，从根上杜绝模拟数据混入真实项目视图/成本/证据口径。

Backup hint: additive only; downgrade drops the three tables child-first.
"""
import sqlalchemy as sa
from alembic import op


revision = "b8e3c7f1a5d9"
down_revision = "d4f1a8c3b6e9"
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
        "simulation_runs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("run_key", sa.String(length=200), nullable=False),
        sa.Column("scenario_id", sa.String(length=36), nullable=False),
        sa.Column("scenario_version", sa.Integer(), nullable=False),
        sa.Column("split", sa.String(length=16), server_default="train", nullable=False),
        sa.Column("status", sa.String(length=24), server_default="queued", nullable=False),
        sa.Column("adapter_mode", sa.String(length=8), server_default="mock", nullable=False),
        sa.Column("seed", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("attempt", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("actor_set_json", sa.JSON(), nullable=False),
        sa.Column("context_json", sa.JSON(), nullable=False),
        sa.Column("cost_json", sa.JSON(), nullable=False),
        sa.Column("error_json", sa.JSON(), nullable=True),
        sa.Column("started_at", sa.String(length=32), nullable=True),
        sa.Column("finished_at", sa.String(length=32), nullable=True),
        sa.Column("created_by_user_id", sa.String(length=36), nullable=True),
        *_timestamp_columns(),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["scenario_id"], ["simulation_scenarios.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"], ["users.id"], ondelete="SET NULL"
        ),
        sa.UniqueConstraint("run_key", name="uq_simulation_runs_run_key"),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'awaiting_approval', 'completed', "
            "'failed', 'failed_hard', 'timeout', 'cancelled')",
            name="ck_simulation_runs_status",
        ),
        sa.CheckConstraint(
            "adapter_mode IN ('real', 'mock')",
            name="ck_simulation_runs_adapter_mode",
        ),
        sa.CheckConstraint(
            "split IN ('train', 'regression', 'blind')",
            name="ck_simulation_runs_split",
        ),
    )
    op.create_index(
        "ix_simulation_runs_scenario_status",
        "simulation_runs",
        ["scenario_id", "status"],
    )
    op.create_index(
        "ix_simulation_runs_split_created",
        "simulation_runs",
        ["split", "created_at"],
    )

    op.create_table(
        "simulation_actors",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("run_id", sa.String(length=36), nullable=False),
        sa.Column("role", sa.String(length=24), nullable=False),
        sa.Column("display_name", sa.String(length=120), server_default="", nullable=False),
        sa.Column("state_json", sa.JSON(), nullable=False),
        sa.Column("config_json", sa.JSON(), nullable=False),
        *_timestamp_columns(),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["run_id"], ["simulation_runs.id"], ondelete="CASCADE"
        ),
        sa.UniqueConstraint("run_id", "role", name="uq_simulation_actors_run_role"),
        sa.CheckConstraint(
            "role IN ('customer', 'fde_consultant', 'domain_expert', 'architect', "
            "'implementer', 'acceptance_reviewer')",
            name="ck_simulation_actors_role",
        ),
    )
    op.create_index(
        "ix_simulation_actors_run",
        "simulation_actors",
        ["run_id"],
    )

    op.create_table(
        "simulation_traces",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("run_id", sa.String(length=36), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("parent_seq", sa.Integer(), nullable=True),
        sa.Column("actor_id", sa.String(length=36), nullable=True),
        sa.Column("phase", sa.String(length=16), nullable=False),
        sa.Column("event_type", sa.String(length=48), nullable=False),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column("tool_call_json", sa.JSON(), nullable=True),
        sa.Column("state_before_json", sa.JSON(), nullable=True),
        sa.Column("state_after_json", sa.JSON(), nullable=True),
        sa.Column("evidence_json", sa.JSON(), nullable=True),
        sa.Column("cost_json", sa.JSON(), nullable=True),
        *_timestamp_columns(),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["run_id"], ["simulation_runs.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["actor_id"], ["simulation_actors.id"], ondelete="SET NULL"
        ),
        sa.UniqueConstraint("run_id", "seq", name="uq_simulation_traces_run_seq"),
        sa.CheckConstraint(
            "phase IN ('setup', 'interview', 'analysis', 'design', 'implementation', "
            "'validation', 'wrapup')",
            name="ck_simulation_traces_phase",
        ),
    )
    op.create_index(
        "ix_simulation_traces_run_phase",
        "simulation_traces",
        ["run_id", "phase"],
    )


def downgrade() -> None:
    op.drop_index("ix_simulation_traces_run_phase", table_name="simulation_traces")
    op.drop_table("simulation_traces")
    op.drop_index("ix_simulation_actors_run", table_name="simulation_actors")
    op.drop_table("simulation_actors")
    op.drop_index("ix_simulation_runs_split_created", table_name="simulation_runs")
    op.drop_index("ix_simulation_runs_scenario_status", table_name="simulation_runs")
    op.drop_table("simulation_runs")
