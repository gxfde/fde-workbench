"""add skills, plugin catalog and model registry

Revision ID: 0029_ai_extension_registry
Revises: 0028_approved_tool_results
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql


revision = "0029_ai_extension_registry"
down_revision = "0028_approved_tool_results"
branch_labels = None
depends_on = None


def _timestamps() -> tuple[sa.Column, sa.Column]:
    return (
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("UTC_TIMESTAMP(6)"), nullable=False),
        sa.Column("updated_at", mysql.TIMESTAMP(fsp=6), server_default=sa.text("CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6)"), nullable=False),
    )


def upgrade() -> None:
    op.create_table(
        "skill_definitions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("scope", sa.String(length=20), nullable=False),
        sa.Column("namespace_key", sa.String(length=80), nullable=False),
        sa.Column("owner_user_id", sa.String(length=36), nullable=True),
        sa.Column("skill_key", sa.String(length=100), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("current_version_number", sa.Integer(), nullable=False),
        sa.Column("created_by_user_id", sa.String(length=36), nullable=False),
        sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        *_timestamps(),
        sa.CheckConstraint("scope IN ('public','personal')", name="ck_skill_definitions_scope"),
        sa.CheckConstraint("status IN ('active','disabled')", name="ck_skill_definitions_status"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["owner_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("namespace_key", "skill_key", name="uq_skill_definitions_namespace_key"),
    )
    op.create_index("ix_skill_definitions_scope_status", "skill_definitions", ["scope", "status"], unique=False)
    op.create_table(
        "skill_versions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("skill_id", sa.String(length=36), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("instructions_text", sa.Text(), nullable=False),
        sa.Column("manifest_json", sa.JSON(), nullable=False),
        sa.Column("required_capabilities", sa.JSON(), nullable=False),
        sa.Column("content_sha256", sa.String(length=64), nullable=False),
        sa.Column("created_by_user_id", sa.String(length=36), nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["skill_id"], ["skill_definitions.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("skill_id", "version_number", name="uq_skill_versions_number"),
        sa.UniqueConstraint("skill_id", "content_sha256", name="uq_skill_versions_content"),
    )
    op.create_table(
        "plugin_packages",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("plugin_key", sa.String(length=140), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("publisher", sa.String(length=160), nullable=False),
        sa.Column("current_version", sa.String(length=80), nullable=False),
        sa.Column("manifest_json", sa.JSON(), nullable=False),
        sa.Column("package_sha256", sa.String(length=64), nullable=False),
        sa.Column("verified", sa.Boolean(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("created_by_user_id", sa.String(length=36), nullable=False),
        sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        *_timestamps(),
        sa.CheckConstraint("status IN ('active','disabled')", name="ck_plugin_packages_status"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("plugin_key", name="uq_plugin_packages_key"),
    )
    op.create_table(
        "plugin_installations",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("plugin_id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("installed_version", sa.String(length=80), nullable=False),
        sa.Column("granted_capabilities", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        *_timestamps(),
        sa.CheckConstraint("status IN ('installed','disabled','removed')", name="ck_plugin_installations_status"),
        sa.ForeignKeyConstraint(["plugin_id"], ["plugin_packages.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("plugin_id", "user_id", name="uq_plugin_installations_user"),
    )
    op.create_table(
        "ai_provider_configs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("provider_key", sa.String(length=80), nullable=False),
        sa.Column("display_name", sa.String(length=160), nullable=False),
        sa.Column("base_url", sa.String(length=500), nullable=False),
        sa.Column("credential_ref", sa.String(length=500), nullable=False),
        sa.Column("credential_hint", sa.String(length=40), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("created_by_user_id", sa.String(length=36), nullable=False),
        sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        *_timestamps(),
        sa.CheckConstraint("status IN ('active','disabled')", name="ck_ai_provider_configs_status"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("provider_key", name="uq_ai_provider_configs_key"),
    )
    op.create_table(
        "ai_model_configs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("provider_id", sa.String(length=36), nullable=False),
        sa.Column("model_key", sa.String(length=160), nullable=False),
        sa.Column("display_name", sa.String(length=160), nullable=False),
        sa.Column("context_window", sa.Integer(), nullable=False),
        sa.Column("supports_tools", sa.Boolean(), nullable=False),
        sa.Column("supports_json", sa.Boolean(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        *_timestamps(),
        sa.CheckConstraint("status IN ('active','disabled')", name="ck_ai_model_configs_status"),
        sa.ForeignKeyConstraint(["provider_id"], ["ai_provider_configs.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("provider_id", "model_key", name="uq_ai_model_configs_provider_key"),
    )


def downgrade() -> None:
    op.drop_table("ai_model_configs")
    op.drop_table("ai_provider_configs")
    op.drop_table("plugin_installations")
    op.drop_table("plugin_packages")
    op.drop_table("skill_versions")
    op.drop_index("ix_skill_definitions_scope_status", table_name="skill_definitions")
    op.drop_table("skill_definitions")
