"""add durable approvals for high-risk DSH operations

Revision ID: 0027_automation_approvals
Revises: 0026_clawbot_command_idempotency
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql


revision = "0027_automation_approvals"
down_revision = "0026_clawbot_command_idempotency"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "automation_approvals",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("run_id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("requested_by_user_id", sa.String(length=36), nullable=False),
        sa.Column("reviewed_by_user_id", sa.String(length=36), nullable=True),
        sa.Column("request_key", sa.String(length=160), nullable=False),
        sa.Column("capability", sa.String(length=100), nullable=False),
        sa.Column("tool_name", sa.String(length=120), nullable=False),
        sa.Column("arguments_json", sa.JSON(), nullable=False),
        sa.Column("arguments_sha256", sa.String(length=64), nullable=False),
        sa.Column("risk_level", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decision_reason", sa.String(length=500), nullable=False),
        sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("UTC_TIMESTAMP(6)"), nullable=False),
        sa.Column("updated_at", mysql.TIMESTAMP(fsp=6), server_default=sa.text("CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6)"), nullable=False),
        sa.CheckConstraint("status IN ('pending','approved','rejected','expired','executed')", name="ck_automation_approvals_status"),
        sa.CheckConstraint("risk_level >= 3 AND risk_level <= 4", name="ck_automation_approvals_risk"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["requested_by_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["reviewed_by_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["run_id"], ["automation_task_runs.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_id", "request_key", name="uq_automation_approvals_run_request"),
    )
    op.create_index("ix_automation_approvals_project_status", "automation_approvals", ["project_id", "status"], unique=False)
    op.create_index("ix_automation_approvals_expires", "automation_approvals", ["status", "expires_at"], unique=False)


def downgrade() -> None:
    op.drop_table("automation_approvals")
