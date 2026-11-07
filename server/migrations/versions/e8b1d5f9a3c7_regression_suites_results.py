"""V3.2 G6：回归套件 regression_suites + 回归结果 regression_results
            ＋ improvement_proposals 扩列 override_json（候选改进的模拟域覆盖载荷）

FDE 交付模拟训练场的回归与盲测系统：套件（一组案例 + 基线参数）与对比结果
（基线组 vs 候选组）。

improvement_proposals 的 override_json 采用 **expand/backfill/contract**：
先加可空列 → 回填 '{}' → 收紧非空（不留 server_default，与模型口径一致，
`alembic check` 才过）。该列只承载**模拟域内**的运行参数覆盖，
**不触及任何生产配置**。

Backup hint: additive only; downgrade drops the two tables and the added column.
"""
import sqlalchemy as sa
from alembic import op


revision = "e8b1d5f9a3c7"
down_revision = "e3b7d9f1a5c6"
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
    # ---- expand/backfill/contract：候选改进的模拟域覆盖载荷 --------------
    op.add_column(
        "improvement_proposals",
        sa.Column("override_json", sa.JSON(), nullable=True),
    )
    op.execute("UPDATE improvement_proposals SET override_json = '{}'::json")
    op.alter_column(
        "improvement_proposals", "override_json", nullable=False, existing_type=sa.JSON()
    )

    op.create_table(
        "regression_suites",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("split", sa.String(length=16), server_default="train", nullable=False),
        sa.Column("scenario_ids_json", sa.JSON(), nullable=False),
        sa.Column("baseline_config_json", sa.JSON(), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_by_user_id", sa.String(length=36), nullable=True),
        *_timestamp_columns(),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"], ["users.id"], ondelete="SET NULL"
        ),
        sa.UniqueConstraint("name", name="uq_regression_suites_name"),
        sa.CheckConstraint(
            "split IN ('train', 'regression', 'blind', 'mixed')",
            name="ck_regression_suites_split",
        ),
    )
    op.create_index(
        "ix_regression_suites_split", "regression_suites", ["split"]
    )

    op.create_table(
        "regression_results",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("suite_id", sa.String(length=36), nullable=False),
        sa.Column("proposal_id", sa.String(length=36), nullable=True),
        sa.Column("fingerprint", sa.String(length=32), nullable=False),
        sa.Column("before_run_ids_json", sa.JSON(), nullable=False),
        sa.Column("after_run_ids_json", sa.JSON(), nullable=False),
        sa.Column("before_summary_json", sa.JSON(), nullable=False),
        sa.Column("after_summary_json", sa.JSON(), nullable=False),
        sa.Column("deltas_json", sa.JSON(), nullable=False),
        sa.Column("new_hard_failures_json", sa.JSON(), nullable=False),
        sa.Column("resolved_hard_failures_json", sa.JSON(), nullable=False),
        sa.Column(
            "generalization_gap",
            sa.Numeric(precision=8, scale=4),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column("overfit_risk", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("verdict", sa.String(length=16), server_default="inconclusive", nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        *_timestamp_columns(),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["suite_id"], ["regression_suites.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["proposal_id"], ["improvement_proposals.id"], ondelete="SET NULL"
        ),
        sa.UniqueConstraint(
            "suite_id",
            "proposal_id",
            "fingerprint",
            name="uq_regression_results_identity",
        ),
        sa.CheckConstraint(
            "verdict IN ('improved', 'regressed', 'mixed', 'no_change', 'inconclusive')",
            name="ck_regression_results_verdict",
        ),
    )
    op.create_index(
        "ix_regression_results_suite", "regression_results", ["suite_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_regression_results_suite", table_name="regression_results")
    op.drop_table("regression_results")
    op.drop_index("ix_regression_suites_split", table_name="regression_suites")
    op.drop_table("regression_suites")
    op.drop_column("improvement_proposals", "override_json")
