"""Add normalized template and project research data."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql


revision: str = "0006_research_data"
down_revision: str | None = "0005_add_template_key"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

FIELD_TYPES = (
    "short_text",
    "long_text",
    "rich_text",
    "integer",
    "decimal",
    "date",
    "single_choice",
    "multi_choice",
    "table",
    "file_reference",
)
FIELD_TYPE_DEFAULT = "short_text"
FIELD_TYPE_CHECK_SQL = "field_type IN (" + ", ".join(
    f"'{field_type}'" for field_type in FIELD_TYPES
) + ")"


def _timestamps() -> tuple[sa.Column, sa.Column]:
    return (
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
    )


def upgrade() -> None:
    op.create_table(
        "template_research_forms",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("template_version_id", sa.String(length=36), nullable=False),
        sa.Column("form_key", sa.String(length=100), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("subject_type", sa.String(length=32), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default=sa.text("0")),
        *_timestamps(),
        sa.CheckConstraint(
            "subject_type IN ('project', 'department', 'role', 'process', 'opportunity')",
            name="ck_template_research_forms_subject_type",
        ),
        sa.ForeignKeyConstraint(
            ["template_version_id"], ["industry_template_versions.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "template_version_id",
            "form_key",
            name="uq_template_research_forms_version_key",
        ),
    )
    op.create_table(
        "template_research_sections",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("form_id", sa.String(length=36), nullable=False),
        sa.Column("section_key", sa.String(length=100), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default=sa.text("0")),
        *_timestamps(),
        sa.ForeignKeyConstraint(["form_id"], ["template_research_forms.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("form_id", "section_key", name="uq_template_research_sections_form_key"),
    )
    op.create_table(
        "template_research_fields",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("section_id", sa.String(length=36), nullable=False),
        sa.Column("field_key", sa.String(length=100), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("help_text", sa.Text(), nullable=False),
        sa.Column(
            "field_type",
            sa.String(length=32),
            nullable=False,
            server_default=FIELD_TYPE_DEFAULT,
        ),
        sa.Column("is_required", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("options_json", sa.JSON(), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default=sa.text("0")),
        *_timestamps(),
        sa.ForeignKeyConstraint(
            ["section_id"], ["template_research_sections.id"], ondelete="RESTRICT"
        ),
        sa.CheckConstraint(
            FIELD_TYPE_CHECK_SQL,
            name="ck_template_research_fields_field_type",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("section_id", "field_key", name="uq_template_research_fields_section_key"),
    )
    op.create_table(
        "project_research_subjects",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("parent_subject_id", sa.String(length=36), nullable=True),
        sa.Column("subject_type", sa.String(length=32), nullable=False),
        sa.Column("subject_key", sa.String(length=100), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="active"),
        sa.Column("tracking_code", sa.String(length=40), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False, server_default=sa.text("1")),
        *_timestamps(),
        sa.CheckConstraint(
            "subject_type IN ('project', 'department', 'role', 'process', 'opportunity')",
            name="ck_project_research_subjects_subject_type",
        ),
        sa.CheckConstraint("version >= 1", name="ck_project_research_subjects_version"),
        sa.CheckConstraint(
            "status IN ('active', 'archived')",
            name="ck_project_research_subjects_status",
        ),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["project_id", "parent_subject_id"],
            ["project_research_subjects.project_id", "project_research_subjects.id"],
            name="fk_project_research_subjects_parent",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id", "subject_key", name="uq_project_research_subjects_project_key"),
        sa.UniqueConstraint("project_id", "id", name="uq_project_research_subjects_project_id"),
        sa.UniqueConstraint(
            "project_id",
            "tracking_code",
            name="uq_project_research_subjects_project_tracking_code",
        ),
    )
    op.create_index("ix_project_research_subjects_project_id", "project_research_subjects", ["project_id"])
    op.create_index("ix_project_research_subjects_subject_type", "project_research_subjects", ["subject_type"])
    op.add_column("projects", sa.Column("research_snapshot", sa.JSON(), nullable=True))
    op.execute("UPDATE projects SET research_snapshot = JSON_OBJECT() WHERE research_snapshot IS NULL")
    op.alter_column(
        "projects",
        "research_snapshot",
        existing_type=sa.JSON(),
        nullable=False,
        server_default=sa.text("(JSON_OBJECT())"),
    )
    op.create_table(
        "project_research_subject_links",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("source_subject_id", sa.String(length=36), nullable=False),
        sa.Column("target_subject_id", sa.String(length=36), nullable=False),
        sa.Column("link_type", sa.String(length=60), nullable=False),
        *_timestamps(),
        sa.CheckConstraint(
            "source_subject_id <> target_subject_id",
            name="ck_project_research_subject_links_not_self",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "source_subject_id",
            "target_subject_id",
            "link_type",
            name="uq_project_research_subject_links_edge",
        ),
    )
    op.create_index(
        "ix_project_research_subject_links_source_project",
        "project_research_subject_links",
        ["project_id", "source_subject_id"],
    )
    op.create_index(
        "ix_project_research_subject_links_target_project",
        "project_research_subject_links",
        ["project_id", "target_subject_id"],
    )
    op.create_foreign_key(
        "fk_project_research_subject_links_source",
        "project_research_subject_links",
        "project_research_subjects",
        ["project_id", "source_subject_id"],
        ["project_id", "id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_project_research_subject_links_target",
        "project_research_subject_links",
        "project_research_subjects",
        ["project_id", "target_subject_id"],
        ["project_id", "id"],
        ondelete="RESTRICT",
    )
    op.create_table(
        "project_research_forms",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("subject_id", sa.String(length=36), nullable=False),
        sa.Column("source_template_research_form_id", sa.String(length=36), nullable=False),
        sa.Column("form_key", sa.String(length=100), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("current_revision_id", sa.String(length=36), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False, server_default=sa.text("1")),
        *_timestamps(),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["source_template_research_form_id"], ["template_research_forms.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["project_id", "subject_id"],
            ["project_research_subjects.project_id", "project_research_subjects.id"],
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint("version >= 1", name="ck_project_research_forms_version"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("subject_id", "form_key", name="uq_project_research_forms_subject_key"),
    )
    op.create_index("ix_project_research_forms_project_id", "project_research_forms", ["project_id"])
    op.create_index(
        "ix_project_research_forms_current_revision_id",
        "project_research_forms",
        ["current_revision_id"],
    )
    op.create_table(
        "project_research_form_revisions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("form_id", sa.String(length=36), nullable=False),
        sa.Column("revision_number", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="draft"),
        sa.Column("parent_revision_id", sa.String(length=36), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False, server_default=sa.text("1")),
        *_timestamps(),
        sa.CheckConstraint("revision_number >= 1", name="ck_project_research_form_revisions_number"),
        sa.CheckConstraint("version >= 1", name="ck_project_research_form_revisions_version"),
        sa.CheckConstraint(
            "status IN ('draft', 'submitted', 'confirmed')",
            name="ck_project_research_form_revisions_status",
        ),
        sa.ForeignKeyConstraint(["form_id"], ["project_research_forms.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["parent_revision_id"], ["project_research_form_revisions.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "form_id",
            "revision_number",
            name="uq_project_research_form_revisions_form_number",
        ),
        sa.UniqueConstraint(
            "form_id",
            "id",
            name="uq_project_research_form_revisions_form_id",
        ),
    )
    op.create_index(
        "ix_project_research_form_revisions_status",
        "project_research_form_revisions",
        ["status"],
    )
    op.create_foreign_key(
        "fk_project_research_forms_current_revision_id",
        "project_research_forms",
        "project_research_form_revisions",
        ["id", "current_revision_id"],
        ["form_id", "id"],
        ondelete="RESTRICT",
    )
    op.create_table(
        "project_research_answers",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("revision_id", sa.String(length=36), nullable=False),
        sa.Column("source_template_research_field_id", sa.String(length=36), nullable=False),
        sa.Column("field_key", sa.String(length=100), nullable=False),
        sa.Column("value_json", sa.JSON(), nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(
            ["revision_id"], ["project_research_form_revisions.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["source_template_research_field_id"], ["template_research_fields.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "revision_id",
            "field_key",
            name="uq_project_research_answers_revision_field_key",
        ),
    )


def downgrade() -> None:
    op.drop_table("project_research_answers")
    op.drop_constraint(
        "fk_project_research_forms_current_revision_id",
        "project_research_forms",
        type_="foreignkey",
    )
    op.drop_table("project_research_form_revisions")
    op.drop_table("project_research_forms")
    op.drop_table("project_research_subject_links")
    op.drop_table("project_research_subjects")
    op.drop_table("template_research_fields")
    op.drop_table("template_research_sections")
    op.drop_table("template_research_forms")
    project_columns = {
        column["name"] for column in sa.inspect(op.get_bind()).get_columns("projects")
    }
    if "research_snapshot" in project_columns:
        op.drop_column("projects", "research_snapshot")
