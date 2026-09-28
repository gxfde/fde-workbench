"""add durable asynchronous research exports

Revision ID: 0017_async_research_exports
Revises: 0016_file_version_deprecation
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql


revision = "0017_async_research_exports"
down_revision = "0016_file_version_deprecation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "project_research_exports",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("project_id", sa.String(36), nullable=False),
        sa.Column("form_id", sa.String(36), nullable=False),
        sa.Column("requested_by_user_id", sa.String(36), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("project_file_id", sa.String(36), nullable=True),
        sa.Column("file_version_id", sa.String(36), nullable=True),
        sa.Column("version_number", sa.Integer(), nullable=True),
        sa.Column("display_name", sa.String(255), nullable=False),
        sa.Column("failure_code", sa.String(80), nullable=False),
        sa.Column("failure_message", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("UTC_TIMESTAMP(6)")),
        sa.Column(
            "updated_at",
            mysql.TIMESTAMP(fsp=6),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6)"),
        ),
        sa.CheckConstraint(
            "status IN ('queued', 'generating', 'succeeded', 'failed')",
            name="ck_project_research_exports_status",
        ),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["form_id"], ["project_research_forms.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["requested_by_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["project_file_id"], ["project_files.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["file_version_id"], ["project_file_versions.id"], ondelete="RESTRICT"),
    )
    op.create_index("ix_project_research_exports_project_form", "project_research_exports", ["project_id", "form_id"])
    op.create_index("ix_project_research_exports_status", "project_research_exports", ["status"])


def downgrade() -> None:
    op.drop_table("project_research_exports")
