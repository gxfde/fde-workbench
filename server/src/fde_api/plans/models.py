"""plans 模型：交付方案三表（V3.1 P0-3）。"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from fde_api.auth.models import UTCDateTime
from fde_api.workbench.models import Base, TimestampMixin, VersionedMixin, new_uuid

PLAN_STATUSES = ("draft", "approved", "published", "superseded")
# 条目类型闭集（任务书 §7「方案至少包含」的可结构化子集；文本大段走
# project_solutions，这里只收可映射/可执行的结构化条目）
ITEM_TYPES = ("requirement", "objective", "milestone", "risk", "acceptance", "non_goal")
PLAN_VERSION_MAX = 9999


class DeliveryPlan(Base, TimestampMixin, VersionedMixin):
    """交付方案行（项目内版本化；同一时刻至多一个 published）。"""

    __tablename__ = "delivery_plans"
    __table_args__ = (
        CheckConstraint(
            "status IN ('draft', 'approved', 'published', 'superseded')",
            name="ck_delivery_plans_status",
        ),
        CheckConstraint("version >= 1", name="ck_delivery_plans_version"),
        CheckConstraint(
            "(status = 'draft') = (reviewed_by_user_id IS NULL AND reviewed_at IS NULL)",
            name="ck_delivery_plans_review_stamp",
        ),
        CheckConstraint(
            "(status <> 'published') OR (published_by_user_id IS NOT NULL AND published_at IS NOT NULL)",
            name="ck_delivery_plans_published_complete",
        ),
        Index("ix_delivery_plans_project_status", "project_id", "status"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False)
    created_by_user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    # 生成来源（可空=纯手工）：discovery 抽取行（确定性拼装输入快照）
    source_extraction_id: Mapped[str | None] = mapped_column(String(36))
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    summary: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft", server_default="draft")
    reviewed_by_user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    reviewed_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    review_comment: Mapped[str | None] = mapped_column(String(500))
    published_by_user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    published_at: Mapped[datetime | None] = mapped_column(UTCDateTime())


class DeliveryPlanItem(Base, TimestampMixin):
    """方案条目：requirement_keys/fact_ids 只能引用已批准/已接受的输入。"""

    __tablename__ = "delivery_plan_items"
    __table_args__ = (
        CheckConstraint(
            "item_type IN ('requirement', 'objective', 'milestone', 'risk', 'acceptance', 'non_goal')",
            name="ck_delivery_plan_items_type",
        ),
        Index("ix_delivery_plan_items_plan", "plan_id"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    plan_id: Mapped[str] = mapped_column(ForeignKey("delivery_plans.id", ondelete="CASCADE"), nullable=False)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False)
    item_type: Mapped[str] = mapped_column(String(20), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    detail: Mapped[str | None] = mapped_column(Text)
    priority: Mapped[str] = mapped_column(String(10), nullable=False, default="medium", server_default="medium")
    # 引用清单（requirement_key 列表 / fact id 列表）——引用校验在服务层
    # （生成器只从已批准需求拼装；手工路径同闸）
    requirement_keys: Mapped[list[Any] | None] = mapped_column(JSON(none_as_null=True))
    fact_ids: Mapped[list[Any] | None] = mapped_column(JSON(none_as_null=True))
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")


class DeliveryPlanTaskLink(Base, TimestampMixin):
    """条目↔既有 project_tasks 映射（任务唯一事实源=project_tasks）。"""

    __tablename__ = "delivery_plan_task_links"
    __table_args__ = (
        UniqueConstraint("item_id", "task_id", name="uq_delivery_plan_task_links_item_task"),
        UniqueConstraint("item_id", name="uq_delivery_plan_task_links_item_unique"),
        Index("ix_delivery_plan_task_links_task", "task_id"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    plan_id: Mapped[str] = mapped_column(ForeignKey("delivery_plans.id", ondelete="CASCADE"), nullable=False)
    item_id: Mapped[str] = mapped_column(ForeignKey("delivery_plan_items.id", ondelete="CASCADE"), nullable=False)
    task_id: Mapped[str] = mapped_column(ForeignKey("project_tasks.id", ondelete="RESTRICT"), nullable=False)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False)
    created_by_user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
