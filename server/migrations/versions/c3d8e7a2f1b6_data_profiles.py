"""data_profiles table (AF2-WP1 read-only profiling artifacts)

One row per profile run: source name + byte-exact sha256 snapshot + table/
column statistics + relation candidates (status stays "candidate" — no
promotion channel; 03 §77) + masked sample rows (04 §3.2: raw sensitive
rows never leave the authorized domain). Append-only; no PATCH/DELETE route.
"""
from alembic import op
import sqlalchemy as sa

revision = "c3d8e7a2f1b6"
down_revision = "b7f2d9e4c6a8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "data_profiles",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "project_id",
            sa.String(36),
            sa.ForeignKey("projects.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("source_name", sa.String(255), nullable=False, server_default=""),
        sa.Column("input_sha256", sa.String(64), nullable=False),
        sa.Column("truncated", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("table_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("tables_json", sa.JSON(), nullable=False),
        sa.Column("relation_candidates_json", sa.JSON(), nullable=False),
        sa.Column("samples_json", sa.JSON(), nullable=False),
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
    op.create_index("ix_data_profiles_project", "data_profiles", ["project_id"])


def downgrade() -> None:
    op.drop_index("ix_data_profiles_project", table_name="data_profiles")
    op.drop_table("data_profiles")
