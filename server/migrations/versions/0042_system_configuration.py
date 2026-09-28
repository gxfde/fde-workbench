"""Add administrator-managed system configuration."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

revision = "0042_system_configuration"
down_revision = "0041_chat_metrics"
branch_labels = None
depends_on = None


def upgrade():
    # The public edition intentionally removes the private client-update registry.
    # IF EXISTS keeps a clean installation and upgrades from a copied private tree safe.
    op.execute("DROP TABLE IF EXISTS client_releases")
    op.create_table(
        "system_configuration",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("values_json", sa.JSON(), nullable=False),
        sa.Column("secrets_ciphertext", sa.Text(), nullable=False),
        sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("UTC_TIMESTAMP(6)"), nullable=False),
        sa.Column("updated_at", mysql.TIMESTAMP(fsp=6), server_default=sa.text("CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6)"), nullable=False),
    )


def downgrade():
    op.drop_table("system_configuration")
