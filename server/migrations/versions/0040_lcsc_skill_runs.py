"""Durable per-actor LCSC browser skill traces and usage."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

revision = "0040_lcsc_skill_runs"
down_revision = "0038_project_solutions"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("lcsc_skill_runs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("execution_id", sa.String(36), nullable=False),
        sa.Column("request_sha256", sa.String(64), nullable=False),
        sa.Column("skill_key", sa.String(100), nullable=False),
        sa.Column("query", sa.String(120), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("browser_url", sa.Text(), nullable=False),
        sa.Column("steps_json", sa.JSON(), nullable=False),
        sa.Column("candidates_json", sa.JSON(), nullable=False),
        sa.Column("result_json", sa.JSON(), nullable=False),
        sa.Column("model_json", sa.JSON(), nullable=False),
        sa.Column("usage_json", sa.JSON(), nullable=False),
        sa.Column("cost_json", sa.JSON(), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=False),
        sa.Column("error_code", sa.String(80), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("UTC_TIMESTAMP(6)"), nullable=False),
        sa.Column("updated_at", mysql.TIMESTAMP(fsp=6), server_default=sa.text("CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6)"), nullable=False),
        sa.UniqueConstraint("execution_id", "request_sha256", name="uq_lcsc_execution_request"))
    op.create_index("ix_lcsc_runs_user_created", "lcsc_skill_runs", ["user_id", "created_at"])


def downgrade():
    op.drop_table("lcsc_skill_runs")
