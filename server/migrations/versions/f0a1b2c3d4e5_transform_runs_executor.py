"""transform_runs table (AF2-WP3 isolated transform executor)

One row per transform execution (17号 v1.0 spec, 甲案=worker fixed operators):
plan anchor + input snapshot anchor (file_version/sha256) + idempotency key +
terminal status (closed set: succeeded/failed/budget_exhausted/
internal_inconsistency) + output rows (capped) + reject ledger (zero row
values — entries are {row_index, reason, column}) + quality report + lineage.
Append-only; no PATCH/DELETE route. Row conservation is machine-checked as
weak conservation per T3 data_eng.row_conservation (output >= input -
rejected, i.e. no row loss): a join with many_to_one cardinality may
legitimately expand one input row into N output rows, so a strict equality
would be false on valid data (spec bug found during encoding, P1-ratified
round2).
"""
from alembic import op
import sqlalchemy as sa

revision = "f0a1b2c3d4e5"
down_revision = "e8f9a0b1c2d3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "transform_runs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "project_id",
            sa.String(36),
            sa.ForeignKey("projects.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "plan_id",
            sa.String(36),
            sa.ForeignKey("transform_plans.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("plan_version", sa.String(32), nullable=False),
        sa.Column("idempotency_key", sa.String(80), nullable=False, unique=True),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("failure_reason", sa.String(80), nullable=True),
        sa.Column("input_anchor_json", sa.JSON(), nullable=False),
        sa.Column("output_rows_json", sa.JSON(), nullable=False),
        sa.Column("output_row_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("output_columns_json", sa.JSON(), nullable=False),
        sa.Column("reject_ledger_json", sa.JSON(), nullable=False),
        sa.Column("rejected_row_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("overflow_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("quality_report_json", sa.JSON(), nullable=False),
        sa.Column("lineage_json", sa.JSON(), nullable=False),
        sa.Column("conservation_json", sa.JSON(), nullable=False),
        sa.Column(
            "created_by_user_id",
            sa.String(36),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    op.create_index("ix_transform_runs_project", "transform_runs", ["project_id"])
    op.create_index("ix_transform_runs_plan", "transform_runs", ["plan_id"])


def downgrade() -> None:
    op.drop_index("ix_transform_runs_plan", table_name="transform_runs")
    op.drop_index("ix_transform_runs_project", table_name="transform_runs")
    op.drop_table("transform_runs")
