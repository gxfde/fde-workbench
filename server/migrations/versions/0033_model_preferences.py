"""Add encrypted, scoped model preferences without changing existing data."""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision = "0033_model_preferences"
down_revision = "0032_dsh_rollout_control"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("ai_model_preferences",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("scope", sa.String(20), nullable=False),
        sa.Column("owner_user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE")),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("provider", sa.String(80), nullable=False),
        sa.Column("base_url", sa.String(500), nullable=False),
        sa.Column("model", sa.String(160), nullable=False),
        sa.Column("credential_ciphertext", sa.Text(), nullable=False),
        sa.Column("is_default", sa.Boolean(), nullable=False),
        sa.Column("supports_tools", sa.Boolean(), nullable=False),
        sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("UTC_TIMESTAMP(6)"), nullable=False),
        sa.Column("updated_at", mysql.TIMESTAMP(fsp=6), server_default=sa.text("CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6)"), nullable=False),
        sa.CheckConstraint("scope IN ('personal', 'public')", name="ck_model_preferences_scope"))
    op.create_index("ix_model_preferences_owner", "ai_model_preferences", ["owner_user_id", "scope"])


def downgrade():
    op.drop_table("ai_model_preferences")
