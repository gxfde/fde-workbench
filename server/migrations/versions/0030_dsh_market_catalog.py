"""add dsh-market catalog metadata

Revision ID: 0030_dsh_market_catalog
Revises: 0029_ai_extension_registry
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql


revision = "0030_dsh_market_catalog"
down_revision = "0029_ai_extension_registry"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("plugin_packages", sa.Column("source", sa.String(40), server_default="internal", nullable=False))
    op.add_column("plugin_packages", sa.Column("source_url", sa.String(1000), server_default="", nullable=False))
    op.add_column("plugin_packages", sa.Column("page_url", sa.String(1000), server_default="", nullable=False))
    op.add_column("plugin_packages", sa.Column("category", sa.String(120), server_default="", nullable=False))
    op.add_column("plugin_packages", sa.Column("install_spec", sa.String(500), server_default="", nullable=False))
    op.add_column("plugin_packages", sa.Column("catalog_entry_sha256", sa.String(64), server_default="", nullable=False))
    op.create_index("ix_plugin_packages_source_category", "plugin_packages", ["source", "category"], unique=False)
    op.create_table(
        "plugin_catalog_syncs",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("source", sa.String(40), nullable=False),
        sa.Column("registry_url", sa.String(1000), nullable=False),
        sa.Column("registry_updated", sa.String(80), nullable=False),
        sa.Column("plugin_count", sa.Integer(), nullable=False),
        sa.Column("content_sha256", sa.String(64), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("error_message", sa.String(500), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("UTC_TIMESTAMP(6)"), nullable=False),
        sa.Column("updated_at", mysql.TIMESTAMP(fsp=6), server_default=sa.text("CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6)"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source"),
    )


def downgrade() -> None:
    op.drop_table("plugin_catalog_syncs")
    op.drop_index("ix_plugin_packages_source_category", table_name="plugin_packages")
    for column in ("catalog_entry_sha256", "install_spec", "category", "page_url", "source_url", "source"):
        op.drop_column("plugin_packages", column)
