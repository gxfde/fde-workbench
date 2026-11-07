"""V3.2 G4：评估结果表 simulation_evaluations

FDE 交付模拟训练场的评估层：一次评估 = 一行，**按层各留一行**（deterministic /
model / human），**并列不合并**——机器结论与人工结论同时留痕。

唯一约束 (run_id, layer, evaluator_id, rubric_version)：同层同评估器同规则版本
幂等；换规则版本 ⇒ 新行（历史评估不改写）。

Backup hint: additive only; downgrade drops the single table.
"""
import sqlalchemy as sa
from alembic import op


revision = "c9d2f4a7e1b5"
down_revision = "b8e3c7f1a5d9"
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
        "simulation_evaluations",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("run_id", sa.String(length=36), nullable=False),
        sa.Column("layer", sa.String(length=16), nullable=False),
        sa.Column("evaluator_id", sa.String(length=80), nullable=False),
        sa.Column("mode", sa.String(length=16), server_default="rules", nullable=False),
        sa.Column("rubric_version", sa.String(length=32), server_default="rubric-v1", nullable=False),
        sa.Column("scores_json", sa.JSON(), nullable=False),
        sa.Column("hard_failures_json", sa.JSON(), nullable=False),
        sa.Column("total_score", sa.Numeric(precision=6, scale=4), server_default=sa.text("0"), nullable=False),
        sa.Column("verdict", sa.String(length=16), server_default="inconclusive", nullable=False),
        sa.Column("unverified_ratio", sa.Numeric(precision=6, scale=4), server_default=sa.text("0"), nullable=False),
        sa.Column("evidence_refs_json", sa.JSON(), nullable=False),
        sa.Column("decided_by_user_id", sa.String(length=36), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        *_timestamp_columns(),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["run_id"], ["simulation_runs.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["decided_by_user_id"], ["users.id"], ondelete="SET NULL"
        ),
        sa.UniqueConstraint(
            "run_id",
            "layer",
            "evaluator_id",
            "rubric_version",
            name="uq_simulation_evaluations_identity",
        ),
        sa.CheckConstraint(
            "layer IN ('deterministic', 'model', 'human')",
            name="ck_simulation_evaluations_layer",
        ),
        sa.CheckConstraint(
            "verdict IN ('pass', 'conditional', 'fail', 'hard_fail', "
            "'inconclusive', 'unavailable')",
            name="ck_simulation_evaluations_verdict",
        ),
    )
    op.create_index(
        "ix_simulation_evaluations_run_layer",
        "simulation_evaluations",
        ["run_id", "layer"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_simulation_evaluations_run_layer", table_name="simulation_evaluations"
    )
    op.drop_table("simulation_evaluations")
