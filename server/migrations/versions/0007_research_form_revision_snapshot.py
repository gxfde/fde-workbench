"""Freeze form definitions on project research revisions."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0007_research_form_snapshot"
down_revision: str | None = "0006_research_data"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("template_research_forms", sa.Column("module_key", sa.String(length=80), nullable=True))
    op.add_column(
        "project_research_form_revisions",
        sa.Column("definition_snapshot", sa.JSON(), nullable=True),
    )
    op.execute(
        "UPDATE project_research_form_revisions SET definition_snapshot = JSON_OBJECT() "
        "WHERE definition_snapshot IS NULL"
    )
    op.alter_column(
        "project_research_form_revisions",
        "definition_snapshot",
        existing_type=sa.JSON(),
        nullable=False,
        server_default=sa.text("(JSON_OBJECT())"),
    )
    op.add_column("project_research_form_revisions", sa.Column("returned_by_user_id", sa.String(length=36), nullable=True))
    op.add_column("project_research_form_revisions", sa.Column("returned_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("project_research_form_revisions", sa.Column("return_comment", sa.Text(), nullable=True))
    op.create_foreign_key(
        "fk_project_research_form_revisions_returned_by",
        "project_research_form_revisions", "users", ["returned_by_user_id"], ["id"], ondelete="RESTRICT"
    )


def downgrade() -> None:
    database = sa.inspect(op.get_bind())
    foreign_keys = {
        item["name"]
        for item in database.get_foreign_keys("project_research_form_revisions")
    }
    if "fk_project_research_form_revisions_returned_by" in foreign_keys:
        op.drop_constraint("fk_project_research_form_revisions_returned_by", "project_research_form_revisions", type_="foreignkey")
    columns = {item["name"] for item in database.get_columns("project_research_form_revisions")}
    for column in ("return_comment", "returned_at", "returned_by_user_id"):
        if column in columns:
            op.drop_column("project_research_form_revisions", column)
    op.drop_column("project_research_form_revisions", "definition_snapshot")
    template_columns = {item["name"] for item in database.get_columns("template_research_forms")}
    if "module_key" in template_columns:
        op.drop_column("template_research_forms", "module_key")
