"""Add project pre-survey sources and guidance analysis versions."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "0015_project_guidance_analyses"
down_revision: str | None = "0014_ai_opportunity_profiles"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("UTC_TIMESTAMP(6)")),
        sa.Column("updated_at", mysql.TIMESTAMP(fsp=6), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6)")),
    ]


def upgrade() -> None:
    op.create_table(
        "project_presurvey_sources",
        sa.Column("project_id", sa.String(length=36), primary_key=True),
        sa.Column("project_file_id", sa.String(length=36), nullable=False),
        sa.Column("current_file_version_id", sa.String(length=36), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        *_timestamps(),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["project_file_id"], ["project_files.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["current_file_version_id"], ["project_file_versions.id"], ondelete="RESTRICT"),
        sa.CheckConstraint("version >= 1", name="ck_project_presurvey_sources_version"),
    )
    op.create_table(
        "project_guidance_analyses",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("source_file_id", sa.String(length=36), nullable=False),
        sa.Column("source_file_version_id", sa.String(length=36), nullable=False),
        sa.Column("source_filename", sa.String(length=255), nullable=False),
        sa.Column("source_sha256", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("status", sa.String(length=24), nullable=False, server_default="draft"),
        sa.Column("analysis_state", sa.String(length=24), nullable=False, server_default="queued"),
        sa.Column("customer_vision", sa.Text(), nullable=False),
        sa.Column("current_phase_objective", sa.Text(), nullable=False),
        sa.Column("key_business_problems_json", sa.JSON(), nullable=False),
        sa.Column("priority_departments_json", sa.JSON(), nullable=False),
        sa.Column("priority_roles_json", sa.JSON(), nullable=False),
        sa.Column("priority_processes_json", sa.JSON(), nullable=False),
        sa.Column("success_criteria_json", sa.JSON(), nullable=False),
        sa.Column("out_of_scope_json", sa.JSON(), nullable=False),
        sa.Column("data_security_redlines_json", sa.JSON(), nullable=False),
        sa.Column("systems_and_deployment_constraints_json", sa.JSON(), nullable=False),
        sa.Column("assumptions_json", sa.JSON(), nullable=False),
        sa.Column("open_questions_json", sa.JSON(), nullable=False),
        sa.Column("next_actions_json", sa.JSON(), nullable=False),
        sa.Column("executive_summary", sa.Text(), nullable=False),
        sa.Column("evidence_json", sa.JSON(), nullable=False),
        sa.Column("ai_model", sa.String(length=120), nullable=False, server_default=""),
        sa.Column("ai_generated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by_user_id", sa.String(length=36), nullable=False),
        sa.Column("reviewed_by_user_id", sa.String(length=36), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failure_code", sa.String(length=80), nullable=False, server_default=""),
        sa.Column("failure_message", sa.Text(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        *_timestamps(),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["source_file_id"], ["project_files.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["source_file_version_id"], ["project_file_versions.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["reviewed_by_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("project_id", "version_number", name="uq_project_guidance_project_version"),
        sa.CheckConstraint("version_number >= 1", name="ck_project_guidance_version_number"),
        sa.CheckConstraint("version >= 1", name="ck_project_guidance_version"),
        sa.CheckConstraint("status IN ('draft', 'confirmed', 'superseded')", name="ck_project_guidance_status"),
        sa.CheckConstraint("analysis_state IN ('queued', 'extracting', 'analyzing', 'ready', 'failed', 'cancelled')", name="ck_project_guidance_analysis_state"),
    )
    op.create_index("ix_project_guidance_project_status", "project_guidance_analyses", ["project_id", "status"])
    op.create_index("ix_project_guidance_source_version", "project_guidance_analyses", ["source_file_version_id"])


def downgrade() -> None:
    op.drop_table("project_guidance_analyses")
    op.drop_table("project_presurvey_sources")
