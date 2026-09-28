"""Persist per-message thinking preference; no existing data changes."""
from alembic import op
import sqlalchemy as sa
revision = "0036_chat_thinking"
down_revision = "0035_ai_conversations"
branch_labels = None
depends_on = None
def upgrade():
    op.add_column("ai_chat_turns", sa.Column("deep_thinking", sa.Boolean(), nullable=False, server_default=sa.false()))
def downgrade():
    op.drop_column("ai_chat_turns", "deep_thinking")
