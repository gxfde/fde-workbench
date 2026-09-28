"""support explicit project file version deprecation

Revision ID: 0016_file_version_deprecation
Revises: 0015_project_guidance_analyses
"""

from alembic import op
import sqlalchemy as sa

revision = "0016_file_version_deprecation"
down_revision = "0015_project_guidance_analyses"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("project_file_versions") as batch:
        batch.drop_constraint("ck_project_file_versions_status", type_="check")
        batch.create_check_constraint(
            "ck_project_file_versions_status",
            "status IN ('uploading', 'quarantined', 'available', 'deprecated', 'rejected', 'failed')",
        )
        batch.add_column(sa.Column("deprecated_by_user_id", sa.String(36), nullable=True))
        batch.add_column(sa.Column("deprecated_at", sa.DateTime(timezone=True), nullable=True))
        # Older MySQL versions reject defaults on TEXT columns. Add it nullable,
        # backfill existing rows, then tighten the constraint without a default.
        batch.add_column(sa.Column("deprecation_reason", sa.Text(), nullable=True))
        batch.create_foreign_key(
            "fk_file_version_deprecated_by", "users", ["deprecated_by_user_id"], ["id"], ondelete="RESTRICT"
        )
    op.execute(sa.text("UPDATE project_file_versions SET deprecation_reason = '' WHERE deprecation_reason IS NULL"))
    with op.batch_alter_table("project_file_versions") as batch:
        batch.alter_column("deprecation_reason", existing_type=sa.Text(), nullable=False)
    with op.batch_alter_table("project_ai_opportunity_profiles") as batch:
        batch.add_column(sa.Column("evidence_json", sa.JSON(), nullable=True))
        batch.add_column(sa.Column("ai_generated", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.execute(sa.text("UPDATE project_ai_opportunity_profiles SET evidence_json = JSON_ARRAY() WHERE evidence_json IS NULL"))
    with op.batch_alter_table("project_ai_opportunity_profiles") as batch:
        batch.alter_column("evidence_json", existing_type=sa.JSON(), nullable=False)
    with op.batch_alter_table("project_documents") as batch:
        batch.add_column(sa.Column("library_file_id", sa.String(36), nullable=True))
        batch.create_foreign_key("fk_project_document_library_file", "project_files", ["library_file_id"], ["id"], ondelete="RESTRICT")


def downgrade() -> None:
    with op.batch_alter_table("project_documents") as batch:
        batch.drop_constraint("fk_project_document_library_file", type_="foreignkey")
        batch.drop_column("library_file_id")
    with op.batch_alter_table("project_ai_opportunity_profiles") as batch:
        batch.drop_column("ai_generated")
        batch.drop_column("evidence_json")
    with op.batch_alter_table("project_file_versions") as batch:
        batch.drop_constraint("fk_file_version_deprecated_by", type_="foreignkey")
        batch.drop_column("deprecation_reason")
        batch.drop_column("deprecated_at")
        batch.drop_column("deprecated_by_user_id")
        batch.drop_constraint("ck_project_file_versions_status", type_="check")
        batch.create_check_constraint(
            "ck_project_file_versions_status",
            "status IN ('uploading', 'quarantined', 'available', 'rejected', 'failed')",
        )
