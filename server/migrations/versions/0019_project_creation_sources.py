"""allow projects created without an industry template

Revision ID: 0019_project_creation_sources
Revises: 0018_template_asset_storage
"""

from alembic import op
import sqlalchemy as sa

revision = "0019_project_creation_sources"
down_revision = "0018_template_asset_storage"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("projects", "source_template_version_id", existing_type=sa.String(36), nullable=True)


def downgrade() -> None:
    op.alter_column("projects", "source_template_version_id", existing_type=sa.String(36), nullable=False)
