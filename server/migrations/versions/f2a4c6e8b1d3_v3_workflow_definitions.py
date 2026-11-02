"""Workflow 定义层两表（V3 T-W1，设计 workflow-dag-v1 §2）

workflow_definitions（定义行：draft/published/archived，发布递增 version）+
workflow_definition_versions（发布快照，(definition_id, version) 唯一，**写后不可
变**）。纯增量零改既有表；runs / node_runs 表随 T-W2 另行迁移。

Backup hint: additive only (two new tables); downgrade drops them child-first.
"""
import sqlalchemy as sa
from alembic import op

revision = "f2a4c6e8b1d3"
down_revision = "e1f3a5c7b9d2"
branch_labels = None
depends_on = None


def _timestamp_columns() -> list[sa.Column]:
    return [
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    ]


def upgrade() -> None:
    op.create_table(
        "workflow_definitions",
        sa.Column("id", sa.String(length=36), nullable=False),
        # NULL = 平台模板（仅 admin），非 NULL = 项目内定义
        sa.Column("project_id", sa.String(length=36), nullable=True),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("dag_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("status", sa.String(length=16), server_default="draft", nullable=False),
        sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        # dag_json 规范化（sort_keys/紧凑）后的 sha256
        sa.Column("content_sha256", sa.String(length=64), nullable=True),
        sa.Column("created_by_user_id", sa.String(length=36), nullable=True),
        sa.Column("published_by_user_id", sa.String(length=36), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamp_columns(),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["published_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.CheckConstraint(
            "status IN ('draft', 'published', 'archived')",
            name="ck_workflow_definitions_status",
        ),
        sa.CheckConstraint("version >= 1", name="ck_workflow_definitions_version"),
    )
    op.create_index(
        "ix_workflow_definitions_project_status",
        "workflow_definitions",
        ["project_id", "status"],
    )
    op.create_table(
        "workflow_definition_versions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("definition_id", sa.String(length=36), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        # 发布快照：写后不可变（决策：运行固定引用版本号，fde-v2 教训）
        sa.Column("dag_json", sa.JSON(), nullable=False),
        sa.Column("content_sha256", sa.String(length=64), nullable=False),
        sa.Column("published_by_user_id", sa.String(length=36), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=False),
        *_timestamp_columns(),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["definition_id"], ["workflow_definitions.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["published_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.UniqueConstraint(
            "definition_id", "version", name="uq_workflow_definition_versions_definition_version"
        ),
        sa.CheckConstraint("version >= 1", name="ck_workflow_definition_versions_version"),
    )


def downgrade() -> None:
    op.drop_table("workflow_definition_versions")
    op.drop_index("ix_workflow_definitions_project_status", table_name="workflow_definitions")
    op.drop_table("workflow_definitions")
