"""Store historical template metadata on each template version."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0004_version_template_metadata"
down_revision: str | None = "0003_project_workbench"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "industry_template_versions",
        sa.Column("name", sa.String(length=160), nullable=True),
    )
    op.add_column(
        "industry_template_versions",
        sa.Column("industry_name", sa.String(length=160), nullable=True),
    )
    op.add_column(
        "industry_template_versions",
        sa.Column("description", sa.Text(), nullable=True),
    )
    op.execute(
        sa.text(
            "UPDATE industry_template_versions AS version "
            "JOIN industry_templates AS template ON template.id = version.template_id "
            "SET version.name = template.name, "
            "version.industry_name = template.industry_name, "
            "version.description = template.description"
        )
    )
    op.alter_column(
        "industry_template_versions",
        "name",
        existing_type=sa.String(length=160),
        nullable=False,
    )
    op.alter_column(
        "industry_template_versions",
        "industry_name",
        existing_type=sa.String(length=160),
        nullable=False,
    )
    op.alter_column(
        "industry_template_versions",
        "description",
        existing_type=sa.Text(),
        nullable=False,
    )


def downgrade() -> None:
    op.drop_column("industry_template_versions", "description")
    op.drop_column("industry_template_versions", "industry_name")
    op.drop_column("industry_template_versions", "name")
