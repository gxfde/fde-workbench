"""Add the project workbench relational schema."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql


revision: str = "0003_project_workbench"
down_revision: str | None = "0002_add_user_auth_version"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def _timestamps() -> tuple[sa.Column, sa.Column]:
    return (
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("UTC_TIMESTAMP(6)"),
        ),
        sa.Column(
            "updated_at",
            mysql.TIMESTAMP(fsp=6),
            nullable=False,
            server_default=sa.text(
                "CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6)"
            ),
        ),
    )


def _version() -> sa.Column:
    return sa.Column("version", sa.Integer(), nullable=False, server_default=sa.text("1"))


def upgrade() -> None:
    op.create_table(
        "module_catalog",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("module_key", sa.String(length=80), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("1")),
        _version(),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("module_key"),
        sa.UniqueConstraint("name"),
    )
    op.create_table(
        "industry_templates",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("industry_name", sa.String(length=160), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="active"),
        sa.Column("latest_published_version_number", sa.Integer(), nullable=True),
        _version(),
        *_timestamps(),
        sa.CheckConstraint(
            "status IN ('active', 'inactive')", name="ck_industry_templates_status"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "industry_template_versions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("template_id", sa.String(length=36), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="draft"),
        sa.Column("published_by_user_id", sa.String(length=36), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        _version(),
        *_timestamps(),
        sa.CheckConstraint(
            "version_number >= 1", name="ck_industry_template_versions_number"
        ),
        sa.CheckConstraint(
            "status IN ('draft', 'published', 'inactive')",
            name="ck_industry_template_versions_status",
        ),
        sa.ForeignKeyConstraint(
            ["published_by_user_id"], ["users.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["template_id"], ["industry_templates.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "template_id",
            "version_number",
            name="uq_industry_template_versions_template_version",
        ),
    )
    op.create_table(
        "template_modules",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("template_version_id", sa.String(length=36), nullable=False),
        sa.Column("module_catalog_id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default=sa.text("0")),
        *_timestamps(),
        sa.ForeignKeyConstraint(
            ["module_catalog_id"], ["module_catalog.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["template_version_id"],
            ["industry_template_versions.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "template_version_id",
            "module_catalog_id",
            name="uq_template_modules_version_catalog",
        ),
    )
    op.create_table(
        "template_tasks",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("template_module_id", sa.String(length=36), nullable=False),
        sa.Column("task_key", sa.String(length=100), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("duration_days", sa.Integer(), nullable=False),
        sa.Column("default_assignee_role", sa.String(length=32), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default=sa.text("0")),
        *_timestamps(),
        sa.CheckConstraint("duration_days >= 1", name="ck_template_tasks_duration"),
        sa.CheckConstraint(
            "default_assignee_role IN "
            "('admin', 'project_lead', 'fde_engineer', 'viewer')",
            name="ck_template_tasks_default_role",
        ),
        sa.ForeignKeyConstraint(
            ["template_module_id"], ["template_modules.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "template_module_id", "task_key", name="uq_template_tasks_module_key"
        ),
    )
    op.create_table(
        "template_task_dependencies",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("predecessor_task_id", sa.String(length=36), nullable=False),
        sa.Column("successor_task_id", sa.String(length=36), nullable=False),
        *_timestamps(),
        sa.CheckConstraint(
            "predecessor_task_id <> successor_task_id",
            name="ck_template_task_dependencies_not_self",
        ),
        sa.ForeignKeyConstraint(
            ["predecessor_task_id"], ["template_tasks.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["successor_task_id"], ["template_tasks.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "predecessor_task_id",
            "successor_task_id",
            name="uq_template_task_dependencies_edge",
        ),
    )
    op.create_table(
        "projects",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project_code", sa.String(length=40), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("enterprise_name", sa.String(length=160), nullable=False),
        sa.Column("enterprise_contact_name", sa.String(length=120), nullable=False, server_default=""),
        sa.Column("enterprise_contact_phone", sa.String(length=60), nullable=False, server_default=""),
        sa.Column("enterprise_address", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("background", sa.Text(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="draft"),
        sa.Column("planned_start_date", sa.Date(), nullable=False),
        sa.Column("planned_end_date", sa.Date(), nullable=True),
        sa.Column("leader_user_id", sa.String(length=36), nullable=False),
        sa.Column("source_template_version_id", sa.String(length=36), nullable=False),
        sa.Column("template_snapshot", sa.JSON(), nullable=False),
        _version(),
        *_timestamps(),
        sa.CheckConstraint(
            "status IN ('draft', 'active', 'paused', 'completed', 'cancelled')",
            name="ck_projects_status",
        ),
        sa.ForeignKeyConstraint(["leader_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["source_template_version_id"],
            ["industry_template_versions.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_code"),
    )
    op.create_index("ix_projects_status", "projects", ["status"])
    op.create_index("ix_projects_leader_user_id", "projects", ["leader_user_id"])
    op.create_index(
        "ix_projects_planned_dates",
        "projects",
        ["planned_start_date", "planned_end_date"],
    )
    op.create_table(
        "project_members",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("role", sa.String(length=20), nullable=False, server_default="member"),
        *_timestamps(),
        sa.CheckConstraint(
            "role IN ('member', 'viewer')", name="ck_project_members_role"
        ),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "project_id", "user_id", name="uq_project_members_project_user"
        ),
    )
    op.create_index("ix_project_members_user_id", "project_members", ["user_id"])
    op.create_table(
        "project_modules",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("source_template_module_id", sa.String(length=36), nullable=True),
        sa.Column("module_catalog_id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="active"),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("planned_start_date", sa.Date(), nullable=True),
        sa.Column("planned_end_date", sa.Date(), nullable=True),
        *_timestamps(),
        sa.CheckConstraint(
            "status IN ('active', 'cancelled')", name="ck_project_modules_status"
        ),
        sa.ForeignKeyConstraint(
            ["module_catalog_id"], ["module_catalog.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["source_template_module_id"], ["template_modules.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "project_id",
            "module_catalog_id",
            name="uq_project_modules_project_catalog",
        ),
    )
    op.create_index(
        "ix_project_modules_planned_dates",
        "project_modules",
        ["planned_start_date", "planned_end_date"],
    )
    op.create_table(
        "project_tasks",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project_module_id", sa.String(length=36), nullable=False),
        sa.Column("source_template_task_id", sa.String(length=36), nullable=True),
        sa.Column("task_key", sa.String(length=100), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="not_started"),
        sa.Column("planned_start_date", sa.Date(), nullable=False),
        sa.Column("planned_end_date", sa.Date(), nullable=False),
        sa.Column("duration_days", sa.Integer(), nullable=False),
        sa.Column("default_assignee_role", sa.String(length=32), nullable=True),
        sa.Column("assignee_user_id", sa.String(length=36), nullable=True),
        sa.Column("progress", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("blocked_reason", sa.Text(), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default=sa.text("0")),
        _version(),
        *_timestamps(),
        sa.CheckConstraint("duration_days >= 1", name="ck_project_tasks_duration"),
        sa.CheckConstraint(
            "progress >= 0 AND progress <= 100", name="ck_project_tasks_progress"
        ),
        sa.CheckConstraint(
            "default_assignee_role IS NULL OR default_assignee_role IN "
            "('admin', 'project_lead', 'fde_engineer', 'viewer')",
            name="ck_project_tasks_default_role",
        ),
        sa.CheckConstraint(
            "status IN "
            "('not_started', 'in_progress', 'blocked', 'completed', 'cancelled')",
            name="ck_project_tasks_status",
        ),
        sa.ForeignKeyConstraint(
            ["assignee_user_id"], ["users.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["project_module_id"], ["project_modules.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["source_template_task_id"], ["template_tasks.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "project_module_id", "task_key", name="uq_project_tasks_module_key"
        ),
    )
    op.create_index(
        "ix_project_tasks_assignee_user_id", "project_tasks", ["assignee_user_id"]
    )
    op.create_index(
        "ix_project_tasks_planned_dates",
        "project_tasks",
        ["planned_start_date", "planned_end_date"],
    )
    op.create_table(
        "project_task_collaborators",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("task_id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(["task_id"], ["project_tasks.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "task_id", "user_id", name="uq_project_task_collaborators_task_user"
        ),
    )
    op.create_table(
        "project_task_dependencies",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("predecessor_task_id", sa.String(length=36), nullable=False),
        sa.Column("successor_task_id", sa.String(length=36), nullable=False),
        *_timestamps(),
        sa.CheckConstraint(
            "predecessor_task_id <> successor_task_id",
            name="ck_project_task_dependencies_not_self",
        ),
        sa.ForeignKeyConstraint(
            ["predecessor_task_id"], ["project_tasks.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["successor_task_id"], ["project_tasks.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "predecessor_task_id",
            "successor_task_id",
            name="uq_project_task_dependencies_edge",
        ),
    )
    op.create_table(
        "operation_events",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("actor_user_id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=True),
        sa.Column("target_type", sa.String(length=80), nullable=False),
        sa.Column("target_id", sa.String(length=80), nullable=False),
        sa.Column("event_type", sa.String(length=100), nullable=False),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("UTC_TIMESTAMP(6)"),
        ),
        sa.Column("changes", sa.JSON(), nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(
            ["actor_user_id"], ["users.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_operation_events_project_occurred",
        "operation_events",
        ["project_id", "occurred_at"],
    )
    op.create_index(
        "ix_operation_events_actor_user_id", "operation_events", ["actor_user_id"]
    )


def downgrade() -> None:
    op.drop_table("operation_events")
    op.drop_table("project_task_dependencies")
    op.drop_table("project_task_collaborators")
    op.drop_table("project_tasks")
    op.drop_table("project_modules")
    op.drop_table("project_members")
    op.drop_table("projects")
    op.drop_table("template_task_dependencies")
    op.drop_table("template_tasks")
    op.drop_table("template_modules")
    op.drop_table("industry_template_versions")
    op.drop_table("industry_templates")
    op.drop_table("module_catalog")
