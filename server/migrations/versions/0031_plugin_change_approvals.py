"""add approved plugin lifecycle changes

Revision ID: 0031_plugin_change_approvals
Revises: 0030_dsh_market_catalog
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql


revision = "0031_plugin_change_approvals"
down_revision = "0030_dsh_market_catalog"
branch_labels = None
depends_on = None


def _timestamps() -> tuple[sa.Column, sa.Column]:
    return (
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("UTC_TIMESTAMP(6)"), nullable=False),
        sa.Column("updated_at", mysql.TIMESTAMP(fsp=6), server_default=sa.text("CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6)"), nullable=False),
    )


def upgrade() -> None:
    op.create_table(
        "plugin_installation_revisions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("installation_id", sa.String(length=36), nullable=False),
        sa.Column("revision_number", sa.Integer(), nullable=False),
        sa.Column("installed_version", sa.String(length=80), nullable=False),
        sa.Column("granted_capabilities", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("action", sa.String(length=20), nullable=False),
        sa.Column("changed_by_user_id", sa.String(length=36), nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(["changed_by_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["installation_id"], ["plugin_installations.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("installation_id", "revision_number", name="uq_plugin_installation_revisions_number"),
    )
    op.create_index("ix_plugin_installation_revisions_version", "plugin_installation_revisions", ["installation_id", "installed_version"], unique=False)
    op.create_table(
        "plugin_change_requests",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("plugin_id", sa.String(length=36), nullable=False),
        sa.Column("target_user_id", sa.String(length=36), nullable=False),
        sa.Column("requested_by_user_id", sa.String(length=36), nullable=False),
        sa.Column("reviewed_by_user_id", sa.String(length=36), nullable=True),
        sa.Column("action", sa.String(length=20), nullable=False),
        sa.Column("from_version", sa.String(length=80), nullable=False),
        sa.Column("target_version", sa.String(length=80), nullable=False),
        sa.Column("requested_capabilities", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("request_reason", sa.String(length=500), nullable=False),
        sa.Column("decision_reason", sa.String(length=500), nullable=False),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("executed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        *_timestamps(),
        sa.CheckConstraint("action IN ('install','upgrade','rollback','disable','remove')", name="ck_plugin_change_requests_action"),
        sa.CheckConstraint("status IN ('pending','approved','rejected','executed','failed')", name="ck_plugin_change_requests_status"),
        sa.ForeignKeyConstraint(["plugin_id"], ["plugin_packages.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["requested_by_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["reviewed_by_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["target_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_plugin_change_requests_status", "plugin_change_requests", ["status", "created_at"], unique=False)
    op.create_index("ix_plugin_change_requests_target", "plugin_change_requests", ["target_user_id", "status"], unique=False)


def downgrade() -> None:
    op.drop_table("plugin_change_requests")
    op.drop_table("plugin_installation_revisions")
