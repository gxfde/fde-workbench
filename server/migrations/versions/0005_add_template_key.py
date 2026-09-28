"""Add a stable unique identity for industry template roots."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0005_add_template_key"
down_revision: str | None = "0004_version_template_metadata"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    connection = op.get_bind()
    duplicate_generic_ids = list(
        connection.execute(
            sa.text(
                "SELECT id FROM industry_templates "
                "WHERE name = :name AND industry_name = :industry_name "
                "ORDER BY id"
            ),
            {"name": "通用企业 AI 落地模板", "industry_name": "通用"},
        ).scalars()
    )
    if len(duplicate_generic_ids) > 1:
        ids = ", ".join(duplicate_generic_ids)
        raise RuntimeError(
            "Cannot assign generic_enterprise_ai: multiple legacy generic "
            f"template roots exist ({ids}). Preserve history, rename every "
            "noncanonical duplicate root, then rerun the migration."
        )

    op.add_column(
        "industry_templates",
        sa.Column("template_key", sa.String(length=100), nullable=True),
    )
    op.execute(
        sa.text(
            "UPDATE industry_templates SET template_key = CASE "
            "WHEN name = '通用企业 AI 落地模板' AND industry_name = '通用' "
            "THEN 'generic_enterprise_ai' "
            "ELSE CONCAT('template_', REPLACE(id, '-', '')) END"
        )
    )
    op.alter_column(
        "industry_templates",
        "template_key",
        existing_type=sa.String(length=100),
        nullable=False,
    )
    op.create_unique_constraint(
        "uq_industry_templates_template_key",
        "industry_templates",
        ["template_key"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_industry_templates_template_key",
        "industry_templates",
        type_="unique",
    )
    op.drop_column("industry_templates", "template_key")
