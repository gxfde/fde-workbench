"""transform_plans table (AF2-WP2 TransformPlan plan face)

One row per statically validated transform plan: nine-operator whitelist +
per-operator exact parameter key sets (no free-text expression slots —
03 §5) + validation report with op-level dependency DAG. Only plans that
passed structural validation are persisted (status stays "validated" —
closed key space, no production state); compilation face belongs to WP3
design-first gate, so no executable artifacts are stored. Append-only;
no PATCH/DELETE route (03 §77: no promotion channel).
"""
from alembic import op
import sqlalchemy as sa

revision = "e8f9a0b1c2d3"
down_revision = "d5e6f7a8b9c0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "transform_plans",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "project_id",
            sa.String(36),
            sa.ForeignKey("projects.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("plan_version", sa.String(32), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="validated"),
        sa.Column("source_profile_id", sa.String(36), nullable=False),
        sa.Column("source_table", sa.String(255), nullable=False),
        sa.Column("plan_json", sa.JSON(), nullable=False),
        sa.Column("validation_json", sa.JSON(), nullable=False),
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
    op.create_index("ix_transform_plans_project", "transform_plans", ["project_id"])


def downgrade() -> None:
    op.drop_index("ix_transform_plans_project", table_name="transform_plans")
    op.drop_table("transform_plans")
