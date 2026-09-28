"""add per-user memos to project research subjects

Revision ID: 0023_research_personal_memos
Revises: 0022_research_subject_memo
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql


revision = "0023_research_personal_memos"
down_revision = "0022_research_subject_memo"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "project_research_personal_memos",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("subject_id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("memo", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("UTC_TIMESTAMP(6)"), nullable=False),
        sa.Column("updated_at", mysql.TIMESTAMP(fsp=6), server_default=sa.text("CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6)"), nullable=False),
        sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.CheckConstraint("version >= 1", name="ck_research_personal_memos_version"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["subject_id"], ["project_research_subjects.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "project_id",
            "subject_id",
            "user_id",
            name="uq_research_personal_memos_subject_user",
        ),
    )
    op.create_index(
        "ix_research_personal_memos_project_subject",
        "project_research_personal_memos",
        ["project_id", "subject_id"],
        unique=False,
    )
    op.create_index(
        "ix_research_personal_memos_user_id",
        "project_research_personal_memos",
        ["user_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_table("project_research_personal_memos")
