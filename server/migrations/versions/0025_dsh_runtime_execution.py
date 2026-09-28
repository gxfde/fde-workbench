"""add DSH execution metadata and ontology snapshots

Revision ID: 0025_dsh_runtime_execution
Revises: 0024_control_plane_foundation
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql


revision = "0025_dsh_runtime_execution"
down_revision = "0024_control_plane_foundation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Keep 0024 immutable: installations that already ran it receive all
    # execution-contract additions through this independent migration.
    op.add_column(
        "automation_tasks",
        sa.Column("requested_capabilities", sa.JSON(), nullable=True),
    )
    op.execute(
        "UPDATE automation_tasks "
        "SET requested_capabilities = JSON_ARRAY('project.read','project.summarize','file.search') "
        "WHERE requested_capabilities IS NULL"
    )
    op.alter_column(
        "automation_tasks",
        "requested_capabilities",
        existing_type=sa.JSON(),
        nullable=False,
    )

    op.create_table(
        "knowledge_snapshots",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("created_by_user_id", sa.String(length=36), nullable=False),
        sa.Column("schema_version", sa.String(length=40), nullable=False),
        sa.Column("content_sha256", sa.String(length=64), nullable=False),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("UTC_TIMESTAMP(6)"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            mysql.TIMESTAMP(fsp=6),
            server_default=sa.text("CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6)"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["users.id"],
            name="fk_knowledge_snapshots_created_by_user_id_users",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name="fk_knowledge_snapshots_project_id_projects",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "project_id",
            "content_sha256",
            name="uq_knowledge_snapshots_project_sha256",
        ),
    )
    op.create_index(
        "ix_knowledge_snapshots_project_created",
        "knowledge_snapshots",
        ["project_id", "created_at"],
        unique=False,
    )

    op.add_column(
        "automation_task_runs",
        sa.Column("requested_by_user_id", sa.String(length=36), nullable=True),
    )
    op.add_column(
        "automation_task_runs",
        sa.Column(
            "external_execution_id",
            sa.String(length=120),
            server_default=sa.text("''"),
            nullable=False,
        ),
    )
    op.add_column(
        "automation_task_runs",
        sa.Column("output_json", sa.JSON(), nullable=True),
    )
    op.execute(
        "UPDATE automation_task_runs AS run "
        "JOIN automation_tasks AS task ON task.id = run.task_id "
        "SET run.requested_by_user_id = task.created_by_user_id "
        "WHERE run.requested_by_user_id IS NULL"
    )
    op.execute(
        "UPDATE automation_task_runs SET output_json = JSON_OBJECT() "
        "WHERE output_json IS NULL"
    )
    op.alter_column(
        "automation_task_runs",
        "requested_by_user_id",
        existing_type=sa.String(length=36),
        nullable=False,
    )
    op.alter_column(
        "automation_task_runs",
        "output_json",
        existing_type=sa.JSON(),
        nullable=False,
    )
    op.create_foreign_key(
        "fk_task_runs_requested_by_user",
        "automation_task_runs",
        "users",
        ["requested_by_user_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_task_runs_knowledge_snapshot",
        "automation_task_runs",
        "knowledge_snapshots",
        ["knowledge_snapshot_id"],
        ["id"],
        ondelete="RESTRICT",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_task_runs_knowledge_snapshot",
        "automation_task_runs",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_task_runs_requested_by_user",
        "automation_task_runs",
        type_="foreignkey",
    )
    op.drop_column("automation_task_runs", "output_json")
    op.drop_column("automation_task_runs", "external_execution_id")
    op.drop_column("automation_task_runs", "requested_by_user_id")
    op.drop_table("knowledge_snapshots")
    op.drop_column("automation_tasks", "requested_capabilities")
