"""add private memo to project research subjects

Revision ID: 0022_research_subject_memo
Revises: 0021_normalize_file_versions
"""

import sqlalchemy as sa
from alembic import op


revision = "0022_research_subject_memo"
down_revision = "0021_normalize_file_versions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "project_research_subjects",
        sa.Column("memo", sa.Text(), nullable=True),
    )
    op.execute("UPDATE project_research_subjects SET memo = '' WHERE memo IS NULL")
    op.alter_column(
        "project_research_subjects",
        "memo",
        existing_type=sa.Text(),
        nullable=False,
    )


def downgrade() -> None:
    op.drop_column("project_research_subjects", "memo")
