"""Allow project research forms and answers to live without a template source.

Projects may now author their own research forms bound to a subject directly
(decoupled from the frozen template snapshot), so the template-source foreign
keys need to become optional.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0012_research_form_nullable"
down_revision: str | None = "0011_document_engine"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column(
        "project_research_forms",
        "source_template_research_form_id",
        existing_type=sa.String(length=36),
        nullable=True,
    )
    op.alter_column(
        "project_research_answers",
        "source_template_research_field_id",
        existing_type=sa.String(length=36),
        nullable=True,
    )


def downgrade() -> None:
    op.alter_column(
        "project_research_answers",
        "source_template_research_field_id",
        existing_type=sa.String(length=36),
        nullable=False,
    )
    op.alter_column(
        "project_research_forms",
        "source_template_research_form_id",
        existing_type=sa.String(length=36),
        nullable=False,
    )
