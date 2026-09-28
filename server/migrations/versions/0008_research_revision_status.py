"""Align research revision states with returned-draft workflow."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008_research_revision_status"
down_revision: str | None = "0007_research_form_snapshot"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.execute("UPDATE project_research_form_revisions SET status = 'draft' WHERE status = 'submitted'")
    op.drop_constraint("ck_project_research_form_revisions_status", "project_research_form_revisions", type_="check")
    op.create_check_constraint("ck_project_research_form_revisions_status", "project_research_form_revisions", "status IN ('draft', 'confirmed', 'archived')")


def downgrade() -> None:
    op.execute("UPDATE project_research_form_revisions SET status = 'draft' WHERE status = 'archived'")
    op.drop_constraint("ck_project_research_form_revisions_status", "project_research_form_revisions", type_="check")
    op.create_check_constraint("ck_project_research_form_revisions_status", "project_research_form_revisions", "status IN ('draft', 'submitted', 'confirmed')")
