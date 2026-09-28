"""Add database-authored research subject import receipts."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql


revision: str = "0009_research_import_batches"
down_revision: str | None = "0008_research_revision_status"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "project_research_import_batches",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("subject_type", sa.String(length=32), nullable=False),
        sa.Column("expected_project_version", sa.Integer(), nullable=False),
        sa.Column("committed_project_version", sa.Integer(), nullable=False),
        sa.Column("result_json", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("UTC_TIMESTAMP(6)"),
        ),
        sa.Column(
            "updated_at",
            mysql.TIMESTAMP(fsp=6),
            nullable=False,
            server_default=sa.text(
                "CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6)"
            ),
        ),
        sa.CheckConstraint(
            "subject_type IN ('department', 'role', 'process', 'opportunity')",
            name="ck_project_research_import_batches_subject_type",
        ),
        sa.CheckConstraint(
            "expected_project_version >= 1",
            name="ck_project_research_import_batches_expected_version",
        ),
        sa.CheckConstraint(
            "committed_project_version > expected_project_version",
            name="ck_project_research_import_batches_committed_version",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"], ["projects.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_project_research_import_batches_project_id",
        "project_research_import_batches",
        ["project_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_table("project_research_import_batches")
