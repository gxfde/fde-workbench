"""V3.1 P0-3：交付方案三表（delivery_plans/delivery_plan_items/
delivery_plan_task_links，2026-11-08）。

任务书 §7 目标模型的落地形（00-gap-register P0-3 裁决）：
- plans：项目内版本化（draft→approved→published + superseded；新版本=新行）；
- items：类型闭集六值；requirement_keys/fact_ids 引用清单（服务层闸校验）；
- links：条目↔既有 project_tasks（任务唯一事实源=project_tasks；
  UNIQUE(item,task)+UNIQUE(item)=幂等锚；task FK RESTRICT）。

Backup hint: additive only; downgrade drops child-first
(links → items → plans).
"""
import sqlalchemy as sa
from alembic import op


revision = "a9c1e5f7b3d8"
down_revision = "d6f2a8b4c9e1"
branch_labels = None
depends_on = None


def _timestamp_columns() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    ]


def upgrade() -> None:
    op.create_table(
        "delivery_plans",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("created_by_user_id", sa.String(length=36), nullable=False),
        sa.Column("source_extraction_id", sa.String(length=36), nullable=True),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=20), server_default="draft", nullable=False),
        sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("reviewed_by_user_id", sa.String(length=36), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("review_comment", sa.String(length=500), nullable=True),
        sa.Column("published_by_user_id", sa.String(length=36), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamp_columns(),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["reviewed_by_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["published_by_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.CheckConstraint(
            "status IN ('draft', 'approved', 'published', 'superseded')",
            name="ck_delivery_plans_status",
        ),
        sa.CheckConstraint("version >= 1", name="ck_delivery_plans_version"),
        sa.CheckConstraint(
            "(status = 'draft') = (reviewed_by_user_id IS NULL AND reviewed_at IS NULL)",
            name="ck_delivery_plans_review_stamp",
        ),
        sa.CheckConstraint(
            "(status <> 'published') OR (published_by_user_id IS NOT NULL AND published_at IS NOT NULL)",
            name="ck_delivery_plans_published_complete",
        ),
    )
    op.create_index("ix_delivery_plans_project_status", "delivery_plans", ["project_id", "status"])
    op.create_table(
        "delivery_plan_items",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("plan_id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("item_type", sa.String(length=20), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("detail", sa.Text(), nullable=True),
        sa.Column("priority", sa.String(length=10), server_default="medium", nullable=False),
        sa.Column("requirement_keys", sa.JSON(), nullable=True),
        sa.Column("fact_ids", sa.JSON(), nullable=True),
        sa.Column("sort_order", sa.Integer(), server_default=sa.text("0"), nullable=False),
        *_timestamp_columns(),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["plan_id"], ["delivery_plans.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="RESTRICT"),
        sa.CheckConstraint(
            "item_type IN ('requirement', 'objective', 'milestone', 'risk', 'acceptance', 'non_goal')",
            name="ck_delivery_plan_items_type",
        ),
    )
    op.create_index("ix_delivery_plan_items_plan", "delivery_plan_items", ["plan_id"])
    op.create_table(
        "delivery_plan_task_links",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("plan_id", sa.String(length=36), nullable=False),
        sa.Column("item_id", sa.String(length=36), nullable=False),
        sa.Column("task_id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("created_by_user_id", sa.String(length=36), nullable=False),
        *_timestamp_columns(),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["plan_id"], ["delivery_plans.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["item_id"], ["delivery_plan_items.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["task_id"], ["project_tasks.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("item_id", "task_id", name="uq_delivery_plan_task_links_item_task"),
        sa.UniqueConstraint("item_id", name="uq_delivery_plan_task_links_item_unique"),
    )
    op.create_index("ix_delivery_plan_task_links_task", "delivery_plan_task_links", ["task_id"])


def downgrade() -> None:
    op.drop_index("ix_delivery_plan_task_links_task", table_name="delivery_plan_task_links")
    op.drop_table("delivery_plan_task_links")
    op.drop_index("ix_delivery_plan_items_plan", table_name="delivery_plan_items")
    op.drop_table("delivery_plan_items")
    op.drop_index("ix_delivery_plans_project_status", table_name="delivery_plans")
    op.drop_table("delivery_plans")
