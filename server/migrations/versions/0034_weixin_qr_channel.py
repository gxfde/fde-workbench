"""Add encrypted, per-user Tencent iLink QR bindings and durable inbox.

Revision ID: 0034_weixin_qr_channel
Revises: 0033_model_preferences
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

revision = "0034_weixin_qr_channel"
down_revision = "0033_model_preferences"
branch_labels = None
depends_on = None


def _timestamps():
    return [sa.Column("created_at", sa.DateTime(), server_default=sa.text("UTC_TIMESTAMP(6)"), nullable=False),
            sa.Column("updated_at", mysql.TIMESTAMP(fsp=6), server_default=sa.text("CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6)"), nullable=False)]


def upgrade():
    op.create_table(
        "weixin_accounts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("binding_id", sa.String(36), sa.ForeignKey("channel_bindings.id", ondelete="CASCADE"), nullable=False),
        sa.Column("credentials_encrypted", sa.Text(), nullable=False),
        sa.Column("login_encrypted", sa.Text(), nullable=False),
        sa.Column("login_status", sa.String(32), nullable=False),
        sa.Column("login_expires_at", sa.DateTime(), nullable=True),
        sa.Column("cursor_encrypted", sa.Text(), nullable=False),
        sa.Column("last_poll_at", sa.DateTime(), nullable=True),
        sa.Column("last_error_code", sa.String(64), nullable=False),
        *_timestamps(), sa.UniqueConstraint("binding_id", name="uq_weixin_binding"),
    )
    op.create_table(
        "weixin_inbox",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("account_id", sa.String(36), sa.ForeignKey("weixin_accounts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("event_digest", sa.String(64), nullable=False),
        sa.Column("payload_encrypted", sa.Text(), nullable=False),
        sa.Column("reply_encrypted", sa.Text(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        *_timestamps(), sa.UniqueConstraint("account_id", "event_digest", name="uq_weixin_inbox_event"),
    )
    op.create_index("ix_weixin_inbox_pending", "weixin_inbox", ["account_id", "status"])


def downgrade():
    op.drop_table("weixin_inbox")
    op.drop_table("weixin_accounts")
