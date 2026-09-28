"""Project-level delivery scope with multiple opportunity snapshots; legacy links retained."""
from alembic import op
import sqlalchemy as sa
revision = "0037_document_opportunities"
down_revision = "0036_chat_thinking"
branch_labels = None
depends_on = None

def upgrade():
    op.add_column("project_documents", sa.Column("opportunity_scope_json", sa.JSON(), nullable=True))

def downgrade():
    op.drop_column("project_documents", "opportunity_scope_json")
