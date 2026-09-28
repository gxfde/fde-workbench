"""Add structured AI opportunity profiles and document provenance."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "0014_ai_opportunity_profiles"
down_revision: str | None = "0013_business_category"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "project_ai_opportunity_profiles",
        sa.Column("subject_id", sa.String(length=36), primary_key=True),
        sa.Column("target_audience", sa.String(length=300), nullable=False, server_default=""),
        sa.Column("owner_user_id", sa.String(length=36), nullable=True),
        sa.Column("opportunity_status", sa.String(length=20), nullable=False, server_default="discovered"),
        sa.Column("priority", sa.String(length=12), nullable=True),
        sa.Column("business_value_score", sa.Integer(), nullable=True),
        sa.Column("feasibility_score", sa.Integer(), nullable=True),
        sa.Column("data_readiness_score", sa.Integer(), nullable=True),
        sa.Column("risk_level", sa.String(length=12), nullable=True),
        sa.Column("next_action", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("UTC_TIMESTAMP(6)")),
        sa.Column("updated_at", mysql.TIMESTAMP(fsp=6), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6)")),
        sa.ForeignKeyConstraint(["subject_id"], ["project_research_subjects.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["owner_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.CheckConstraint("opportunity_status IN ('discovered', 'assessing', 'ready', 'converted', 'paused')", name="ck_project_ai_opportunity_profiles_status"),
        sa.CheckConstraint("priority IS NULL OR priority IN ('high', 'medium', 'low')", name="ck_project_ai_opportunity_profiles_priority"),
        sa.CheckConstraint("risk_level IS NULL OR risk_level IN ('high', 'medium', 'low')", name="ck_project_ai_opportunity_profiles_risk"),
        sa.CheckConstraint("business_value_score IS NULL OR business_value_score BETWEEN 1 AND 5", name="ck_project_ai_opportunity_profiles_business_score"),
        sa.CheckConstraint("feasibility_score IS NULL OR feasibility_score BETWEEN 1 AND 5", name="ck_project_ai_opportunity_profiles_feasibility_score"),
        sa.CheckConstraint("data_readiness_score IS NULL OR data_readiness_score BETWEEN 1 AND 5", name="ck_project_ai_opportunity_profiles_data_score"),
    )
    op.execute(sa.text("INSERT INTO project_ai_opportunity_profiles (subject_id, target_audience, opportunity_status, next_action) SELECT id, '', 'discovered', '' FROM project_research_subjects WHERE subject_type = 'opportunity'"))
    op.add_column("project_documents", sa.Column("source_opportunity_id", sa.String(length=36), nullable=True))
    op.create_foreign_key("fk_project_documents_source_opportunity", "project_documents", "project_research_subjects", ["source_opportunity_id"], ["id"], ondelete="RESTRICT")
    op.create_index("ix_project_documents_source_opportunity", "project_documents", ["source_opportunity_id"])


def downgrade() -> None:
    op.drop_constraint("fk_project_documents_source_opportunity", "project_documents", type_="foreignkey")
    op.drop_index("ix_project_documents_source_opportunity", table_name="project_documents")
    op.drop_column("project_documents", "source_opportunity_id")
    op.drop_table("project_ai_opportunity_profiles")
