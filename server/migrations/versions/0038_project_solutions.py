"""Separate saved delivery designs from opportunities and exported documents.

Additive only: existing opportunity answers and document history are untouched.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.mysql import DATETIME, MEDIUMTEXT, TIMESTAMP

revision = "0038_project_solutions"
down_revision = "0037_document_opportunities"
branch_labels = None
depends_on = None


def _timestamps():
    return [sa.Column("created_at", DATETIME(fsp=6), nullable=False, server_default=sa.text("UTC_TIMESTAMP(6)")),
            sa.Column("updated_at", TIMESTAMP(fsp=6), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6)"),
                      server_onupdate=sa.text("CURRENT_TIMESTAMP(6)"))]


def upgrade():
    op.create_table(
        "project_solutions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("project_id", sa.String(36), sa.ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("design_markdown", sa.Text().with_variant(MEDIUMTEXT(), "mysql"), nullable=False),
        *[sa.Column(key, sa.Text(), nullable=False) for key in (
            "deliverables", "acceptance_criteria", "data_systems", "schedule", "risks_dependencies")],
        sa.Column("business_category", sa.String(32)),
        sa.Column("status", sa.String(20), nullable=False, server_default="active"),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("owner_user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("legacy_source_key", sa.String(100)),
        sa.Column("source_json", sa.JSON()),
        *_timestamps(),
        sa.CheckConstraint("status IN ('active', 'archived')", name="ck_project_solutions_status"),
        sa.CheckConstraint("version >= 1", name="ck_project_solutions_version"),
        sa.UniqueConstraint("project_id", "legacy_source_key", name="uq_project_solutions_legacy_source"),
    )
    op.create_index("ix_project_solutions_project_status", "project_solutions", ["project_id", "status"])
    op.create_table(
        "project_solution_opportunities",
        sa.Column("solution_id", sa.String(36), sa.ForeignKey("project_solutions.id", ondelete="RESTRICT"), primary_key=True),
        sa.Column("opportunity_id", sa.String(36), sa.ForeignKey("project_research_subjects.id", ondelete="RESTRICT"), primary_key=True),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("snapshot_json", sa.JSON(), nullable=False),
    )
    op.create_table(
        "project_solution_exports",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("solution_id", sa.String(36), sa.ForeignKey("project_solutions.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("solution_version", sa.Integer(), nullable=False),
        sa.Column("document_id", sa.String(36), sa.ForeignKey("project_documents.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("document_version_id", sa.String(36), sa.ForeignKey("project_document_versions.id", ondelete="RESTRICT"), nullable=False),
        *_timestamps(),
        sa.UniqueConstraint("solution_id", "solution_version", name="uq_project_solution_exports_revision"),
    )


def downgrade():
    op.drop_table("project_solution_exports")
    op.drop_table("project_solution_opportunities")
    op.drop_table("project_solutions")
