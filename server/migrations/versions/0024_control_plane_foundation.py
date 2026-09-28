"""add v1 control-plane foundations

Revision ID: 0024_control_plane_foundation
Revises: 0023_research_personal_memos
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql


revision = "0024_control_plane_foundation"
down_revision = "0023_research_personal_memos"
branch_labels = None
depends_on = None


def _timestamps() -> tuple[sa.Column, sa.Column]:
    return (
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("UTC_TIMESTAMP(6)"), nullable=False),
        sa.Column("updated_at", mysql.TIMESTAMP(fsp=6), server_default=sa.text("CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6)"), nullable=False),
    )


def upgrade() -> None:
    op.create_table(
        "user_ai_access_grants",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("access_level", sa.String(length=32), nullable=False),
        sa.Column("granted_by_user_id", sa.String(length=36), nullable=False),
        sa.Column("reason", sa.String(length=255), nullable=False),
        *_timestamps(),
        sa.CheckConstraint("access_level IN ('disabled','assistant_read','project_operator','project_manager','system_operator')", name="ck_user_ai_access_level"),
        sa.ForeignKeyConstraint(["granted_by_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", name="uq_user_ai_access_grants_user"),
    )

    op.create_table(
        "channel_bindings",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("channel", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("external_subject_hash", sa.String(length=64), nullable=True),
        sa.Column("channel_display_name", sa.String(length=120), nullable=False),
        sa.Column("default_project_id", sa.String(length=36), nullable=True),
        sa.Column("commands_enabled", sa.Boolean(), nullable=False),
        sa.Column("notifications_enabled", sa.Boolean(), nullable=False),
        sa.Column("binding_code_digest", sa.String(length=64), nullable=True),
        sa.Column("binding_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        *_timestamps(),
        sa.CheckConstraint("channel IN ('wechat_clawbot')", name="ck_channel_bindings_channel"),
        sa.CheckConstraint("status IN ('pending','active','paused','revoked')", name="ck_channel_bindings_status"),
        sa.ForeignKeyConstraint(["default_project_id"], ["projects.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "channel", name="uq_channel_bindings_user_channel"),
        sa.UniqueConstraint("channel", "external_subject_hash", name="uq_channel_bindings_external_subject"),
    )
    op.create_index("ix_channel_bindings_status", "channel_bindings", ["channel", "status"], unique=False)

    op.create_table(
        "automation_tasks",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=True),
        sa.Column("created_by_user_id", sa.String(length=36), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("source", sa.String(length=20), nullable=False),
        sa.Column("task_type", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("schedule_kind", sa.String(length=20), nullable=False),
        sa.Column("schedule_expression", sa.String(length=255), nullable=False),
        sa.Column("timezone", sa.String(length=64), nullable=False),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column("dsh_profile", sa.String(length=120), nullable=False),
        sa.Column("risk_level", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("next_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("notification_policy", sa.JSON(), nullable=False),
        sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        *_timestamps(),
        sa.CheckConstraint("source IN ('desktop','wechat','system')", name="ck_automation_tasks_source"),
        sa.CheckConstraint("task_type IN ('ai','system')", name="ck_automation_tasks_type"),
        sa.CheckConstraint("status IN ('active','paused','archived')", name="ck_automation_tasks_status"),
        sa.CheckConstraint("schedule_kind IN ('once','calendar','interval','event')", name="ck_automation_tasks_schedule_kind"),
        sa.CheckConstraint("risk_level >= 0 AND risk_level <= 4", name="ck_automation_tasks_risk"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_automation_tasks_owner_status", "automation_tasks", ["created_by_user_id", "status"], unique=False)
    op.create_index("ix_automation_tasks_project_status", "automation_tasks", ["project_id", "status"], unique=False)
    op.create_index("ix_automation_tasks_next_run", "automation_tasks", ["status", "next_run_at"], unique=False)

    op.create_table(
        "automation_task_runs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("task_id", sa.String(length=36), nullable=False),
        sa.Column("scheduled_for", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("attempt", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("idempotency_key", sa.String(length=160), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("dsh_runtime_version", sa.String(length=80), nullable=False),
        sa.Column("agent_profile_version", sa.String(length=80), nullable=False),
        sa.Column("knowledge_snapshot_id", sa.String(length=36), nullable=True),
        sa.Column("result_summary", sa.Text(), nullable=False),
        sa.Column("error_code", sa.String(length=80), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=False),
        *_timestamps(),
        sa.CheckConstraint("status IN ('queued','running','waiting_approval','succeeded','failed','cancelled','skipped')", name="ck_automation_task_runs_status"),
        sa.CheckConstraint("attempt >= 0", name="ck_automation_task_runs_attempt"),
        sa.ForeignKeyConstraint(["task_id"], ["automation_tasks.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("idempotency_key", name="uq_automation_task_runs_idempotency"),
    )
    op.create_index("ix_automation_task_runs_task_scheduled", "automation_task_runs", ["task_id", "scheduled_for"], unique=False)
    op.create_index("ix_automation_task_runs_status", "automation_task_runs", ["status", "scheduled_for"], unique=False)


def downgrade() -> None:
    op.drop_table("automation_task_runs")
    op.drop_table("automation_tasks")
    op.drop_table("channel_bindings")
    op.drop_table("user_ai_access_grants")
