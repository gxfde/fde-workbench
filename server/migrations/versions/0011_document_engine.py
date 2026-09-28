"""Add document engine schema."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "0011_document_engine"
down_revision: str | None = "0010_project_files_and_outbox"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


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
            server_default=sa.text("CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6)"),
        ),
    )


def _version() -> sa.Column:
    return sa.Column(
        "version", sa.Integer(), nullable=False, server_default=sa.text("1")
    )


def upgrade() -> None:
    op.create_table(
        "document_templates",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("document_type", sa.String(length=80), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("industry_name", sa.String(length=160), nullable=False),
        sa.Column(
            "status", sa.String(length=20), nullable=False, server_default="active"
        ),
        sa.Column("latest_published_version_number", sa.Integer(), nullable=True),
        *_timestamps(),
        _version(),
        sa.UniqueConstraint("document_type"),
        sa.CheckConstraint(
            "status IN ('active', 'inactive')", name="ck_document_templates_status"
        ),
    )

    op.create_table(
        "document_template_versions",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("template_id", sa.String(length=36), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column(
            "status", sa.String(length=20), nullable=False, server_default="draft"
        ),
        sa.Column("docx_file_version_id", sa.String(length=36), nullable=True),
        sa.Column("mapping_json", sa.JSON(), nullable=False),
        sa.Column("sections_json", sa.JSON(), nullable=False),
        sa.Column("table_loops_json", sa.JSON(), nullable=False),
        sa.Column("required_data_json", sa.JSON(), nullable=False),
        sa.Column("source_sha256", sa.String(length=64), nullable=False),
        sa.Column("created_by_user_id", sa.String(length=36), nullable=False),
        sa.Column("published_by_user_id", sa.String(length=36), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        _version(),
        sa.ForeignKeyConstraint(
            ["template_id"], ["document_templates.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["docx_file_version_id"], ["project_file_versions.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"], ["users.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["published_by_user_id"], ["users.id"], ondelete="RESTRICT"
        ),
        sa.UniqueConstraint(
            "template_id",
            "version_number",
            name="uq_document_template_versions_template_version",
        ),
        sa.CheckConstraint(
            "version_number >= 1", name="ck_document_template_versions_number"
        ),
        sa.CheckConstraint(
            "status IN ('draft', 'published', 'inactive')",
            name="ck_document_template_versions_status",
        ),
    )
    op.create_index(
        "ix_document_template_versions_template_id",
        "document_template_versions",
        ["template_id"],
    )

    op.create_table(
        "project_documents",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("document_type", sa.String(length=80), nullable=False),
        sa.Column("business_code", sa.String(length=80), nullable=False),
        sa.Column("current_version_id", sa.String(length=36), nullable=True),
        sa.Column("source_template_version_id", sa.String(length=36), nullable=False),
        sa.Column(
            "status", sa.String(length=20), nullable=False, server_default="draft"
        ),
        sa.Column("owner_user_id", sa.String(length=36), nullable=False),
        *_timestamps(),
        _version(),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["source_template_version_id"],
            ["document_template_versions.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(["owner_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint(
            "project_id",
            "business_code",
            name="uq_project_documents_project_business_code",
        ),
        sa.CheckConstraint(
            "status IN ('draft', 'confirmed', 'archived')",
            name="ck_project_documents_status",
        ),
    )
    op.create_index(
        "ix_project_documents_project_status", "project_documents", ["project_id", "status"]
    )
    op.create_index(
        "ix_project_documents_document_type", "project_documents", ["document_type"]
    )

    op.create_table(
        "project_document_drafts",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("document_id", sa.String(length=36), nullable=False),
        sa.Column("field_overrides_json", sa.JSON(), nullable=False),
        sa.Column("rich_text_json", sa.JSON(), nullable=False),
        sa.Column("list_selections_json", sa.JSON(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default=sa.text("1")),
        *_timestamps(),
        sa.ForeignKeyConstraint(
            ["document_id"], ["project_documents.id"], ondelete="RESTRICT"
        ),
        sa.UniqueConstraint("document_id", name="uq_project_document_drafts_document"),
    )

    op.create_table(
        "project_document_versions",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("document_id", sa.String(length=36), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column(
            "source", sa.String(length=24), nullable=False, server_default="generated"
        ),
        sa.Column(
            "status", sa.String(length=20), nullable=False, server_default="draft"
        ),
        sa.Column("parent_version_id", sa.String(length=36), nullable=True),
        sa.Column("source_template_version_id", sa.String(length=36), nullable=False),
        sa.Column("source_snapshot_json", sa.JSON(), nullable=False),
        sa.Column("content_snapshot_json", sa.JSON(), nullable=False),
        sa.Column("docx_file_version_id", sa.String(length=36), nullable=False),
        sa.Column("preview_file_version_id", sa.String(length=36), nullable=True),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("generated_by_user_id", sa.String(length=36), nullable=False),
        sa.Column("confirmed_by_user_id", sa.String(length=36), nullable=True),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("generation_error", sa.Text(), nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(
            ["document_id"], ["project_documents.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["parent_version_id"], ["project_document_versions.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["source_template_version_id"],
            ["document_template_versions.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["docx_file_version_id"], ["project_file_versions.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["preview_file_version_id"], ["project_file_versions.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["generated_by_user_id"], ["users.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["confirmed_by_user_id"], ["users.id"], ondelete="RESTRICT"
        ),
        sa.UniqueConstraint(
            "document_id",
            "version_number",
            name="uq_project_document_versions_document_version",
        ),
        sa.CheckConstraint(
            "version_number >= 1", name="ck_project_document_versions_number"
        ),
        sa.CheckConstraint(
            "source IN ('generated', 'online_revised', 'manual_upload')",
            name="ck_project_document_versions_source",
        ),
        sa.CheckConstraint(
            "status IN ('draft', 'confirmed', 'archived')",
            name="ck_project_document_versions_status",
        ),
    )
    op.create_index(
        "ix_project_document_versions_document_id",
        "project_document_versions",
        ["document_id"],
    )

    # The circular current-version reference must be added after both tables exist.
    op.create_foreign_key(
        "fk_project_documents_current_version",
        "project_documents",
        "project_document_versions",
        ["current_version_id"],
        ["id"],
        ondelete="RESTRICT",
    )

    op.create_table(
        "document_generation_jobs",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("document_version_id", sa.String(length=36), nullable=False),
        sa.Column(
            "status", sa.String(length=20), nullable=False, server_default="queued"
        ),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("last_error", sa.Text(), nullable=False),
        *_timestamps(),
        _version(),
        sa.ForeignKeyConstraint(
            ["document_version_id"], ["project_document_versions.id"], ondelete="RESTRICT"
        ),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'succeeded', 'failed', 'cancelled')",
            name="ck_document_generation_jobs_status",
        ),
        sa.CheckConstraint("attempts >= 0", name="ck_document_generation_jobs_attempts"),
    )
    op.create_index(
        "ix_document_generation_jobs_document_version_status",
        "document_generation_jobs",
        ["document_version_id", "status"],
    )


def downgrade() -> None:
    op.drop_table("document_generation_jobs")
    op.drop_constraint(
        "fk_project_documents_current_version", "project_documents", type_="foreignkey"
    )
    op.drop_table("project_document_versions")
    op.drop_table("project_document_drafts")
    op.drop_table("project_documents")
    op.drop_table("document_template_versions")
    op.drop_table("document_templates")
