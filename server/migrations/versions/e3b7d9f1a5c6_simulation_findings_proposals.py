"""V3.2 G5：失败发现 simulation_findings + 改进提案 improvement_proposals

FDE 交付模拟训练场的改进层：失败发现（由评估结论归因）+ 改进提案（**只提案，
不落地**）。

**improvement_proposals 的状态机止于 approved**——没有 publish / apply 状态，
也没有指向生产配置的写列（target_json 只是文本指针）。这正是「改进必须先过
独立评估与回归、再经人工审批、最后才发布」的分闸在数据层的落点。

Backup hint: additive only; downgrade drops the two tables child-first.
"""
import sqlalchemy as sa
from alembic import op


revision = "e3b7d9f1a5c6"
down_revision = "c9d2f4a7e1b5"
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
        "simulation_findings",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("run_id", sa.String(length=36), nullable=False),
        sa.Column("evaluation_id", sa.String(length=36), nullable=False),
        sa.Column("code", sa.String(length=16), nullable=False),
        sa.Column("title", sa.String(length=160), nullable=False),
        sa.Column("severity", sa.String(length=16), server_default="medium", nullable=False),
        sa.Column("dimension", sa.String(length=16), server_default="", nullable=False),
        sa.Column("description", sa.Text(), server_default="", nullable=False),
        sa.Column("evidence_refs_json", sa.JSON(), nullable=False),
        sa.Column("root_causes_json", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="open", nullable=False),
        sa.Column("detail_json", sa.JSON(), nullable=False),
        *_timestamp_columns(),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["run_id"], ["simulation_runs.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["evaluation_id"], ["simulation_evaluations.id"], ondelete="CASCADE"
        ),
        sa.UniqueConstraint(
            "evaluation_id", "code", name="uq_simulation_findings_evaluation_code"
        ),
        sa.CheckConstraint(
            "severity IN ('high', 'medium', 'low')",
            name="ck_simulation_findings_severity",
        ),
        sa.CheckConstraint(
            "status IN ('open', 'confirmed', 'rejected')",
            name="ck_simulation_findings_status",
        ),
    )
    op.create_index(
        "ix_simulation_findings_run",
        "simulation_findings",
        ["run_id"],
    )

    op.create_table(
        "improvement_proposals",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("proposal_key", sa.String(length=32), nullable=False),
        sa.Column("title", sa.String(length=160), nullable=False),
        sa.Column("problem", sa.Text(), server_default="", nullable=False),
        sa.Column("finding_ids_json", sa.JSON(), nullable=False),
        sa.Column("finding_codes_json", sa.JSON(), nullable=False),
        sa.Column("fingerprint", sa.String(length=32), nullable=False),
        sa.Column("target_json", sa.JSON(), nullable=False),
        sa.Column("current_version", sa.String(length=32), server_default="v1", nullable=False),
        sa.Column("proposed_version", sa.String(length=32), server_default="v2", nullable=False),
        sa.Column("change_summary", sa.Text(), server_default="", nullable=False),
        sa.Column("expected_effect_json", sa.JSON(), nullable=False),
        sa.Column("impact_scope_json", sa.JSON(), nullable=False),
        sa.Column("regression_plan_json", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="draft", nullable=False),
        sa.Column("created_by_user_id", sa.String(length=36), nullable=True),
        sa.Column("decided_by_user_id", sa.String(length=36), nullable=True),
        sa.Column("decided_at", sa.String(length=32), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        *_timestamp_columns(),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"], ["users.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["decided_by_user_id"], ["users.id"], ondelete="SET NULL"
        ),
        sa.UniqueConstraint(
            "fingerprint", name="uq_improvement_proposals_fingerprint"
        ),
        sa.CheckConstraint(
            "status IN ('draft', 'in_review', 'approved', 'rejected')",
            name="ck_improvement_proposals_status",
        ),
    )
    op.create_index(
        "ix_improvement_proposals_status",
        "improvement_proposals",
        ["status"],
    )


def downgrade() -> None:
    op.drop_index("ix_improvement_proposals_status", table_name="improvement_proposals")
    op.drop_table("improvement_proposals")
    op.drop_index("ix_simulation_findings_run", table_name="simulation_findings")
    op.drop_table("simulation_findings")
