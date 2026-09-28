"""Durable AI conversations, additive migration only."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

revision = "0035_ai_conversations"
down_revision = "0034_weixin_qr_channel"
branch_labels = None
depends_on = None

def timestamps():
    return [sa.Column("created_at", sa.DateTime(), server_default=sa.text("UTC_TIMESTAMP(6)"), nullable=False),
            sa.Column("updated_at", mysql.TIMESTAMP(fsp=6), server_default=sa.text("CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6)"), nullable=False)]

def upgrade():
    op.create_table("ai_conversations", sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("title", sa.String(160), nullable=False),
        sa.Column("project_id", sa.String(36), sa.ForeignKey("projects.id", ondelete="RESTRICT")),
        sa.Column("source", sa.String(20), nullable=False), *timestamps())
    op.create_index("ix_ai_conversations_user_id", "ai_conversations", ["user_id"])
    op.create_table("ai_chat_turns", sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("conversation_id", sa.String(36), sa.ForeignKey("ai_conversations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("prompt", sa.Text(), nullable=False), sa.Column("response", sa.Text(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False), sa.Column("error_message", sa.String(500), nullable=False),
        sa.Column("model_preference_id", sa.String(36)), *timestamps())
    op.create_index("ix_ai_chat_turns_conversation_id", "ai_chat_turns", ["conversation_id"])

def downgrade():
    op.drop_table("ai_chat_turns")
    op.drop_table("ai_conversations")
