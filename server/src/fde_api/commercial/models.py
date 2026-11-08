"""商业化 G1：权益四分与角色分层（任务书 T-04/T-05，ADR-001/ADR-002）。

语义边界（裁决钉，实施不得越界）：

- **角色分层 R1–R4**（R1 企业／R2 创业者／R3 交付者／R4 区域合作商，可空=未分层）
  与平台权限角色 ``users.role``（admin/project_lead/fde_engineer/viewer + ROLE_RANK
  阶梯）**正交并存、互不推导**；与 ``fde_profiles.level``（交付能力等级：衡量人、
  越大越资深）**零关联**——后者由 dispatch 域独占，本模块零触碰（ADR-001）。
- **四类权益独立建模、互不推导**（ADR-002）：培训权益（购买与有效期，1:N）、
  订阅权益（年度席位 3980：激活状态/来源/到期）、认证状态（挂模拟考核指针）、
  交付资格。禁止任何「由 A 推导 B」的写路径；``delivery_eligibility`` 与
  ``fde_profiles.status`` 并存（前者=商业资格，后者=供给池生命周期），唯一
  同步点=席位激活时 pending→active 的单向升级（服务层，落事件）。
- 对外 L0–L4 商业编号**不在本模块落值域**；唯一换算入口是 ``ladder.py``
  映射（ADR-006：代码与迁移中不出现以 L 开头的角色枚举值）。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import CheckConstraint, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from fde_api.auth.models import UTCDateTime, UTC_TIMESTAMP_SQL
from fde_api.workbench.models import Base, TimestampMixin, new_uuid

# 值域闭集（R 系命名纪律：ADR-006——不出现 L 开头角色枚举值）
COMMERCIAL_ROLES = ("R1", "R2", "R3", "R4")
SEAT_STATUSES = ("none", "active")
SEAT_SOURCES = (
    "first_delivery",  # 首个付费项目交付完成并验收后激活（G3 首单扣费闸）
    "bootcamp_practical",  # 实战营含首年席位
    "bootcamp_mentorship",  # 陪跑营含首年席位
)
CERTIFICATION_STATUSES = ("uncertified", "certified")
DELIVERY_ELIGIBILITIES = ("none", "eligible")
TRAINING_ITEM_TYPES = ("training", "certification", "mentoring")
TRAINING_STATUSES = ("active", "revoked")


class CommercialEntitlement(Base, TimestampMixin):
    """一人一份商业权益（PK=user_id，与 fde_profiles 同构）。

    四类权益各自独立列组，互不推导（ADR-002 §2.2）：

    - 角色分层 ``commercial_role``（R1–R4，NULL=未分层）；
    - 订阅权益 ``seat_*``（年度席位激活状态/来源/起止）；
    - 认证状态 ``certification_*``（是否已获认证；source 是模拟考核等
      证据的**指针**，不内嵌正文——证据红线同款）；
    - 交付资格 ``delivery_eligibility``（是否具备接单并激活席位资格；
      与 ``fde_profiles.status`` 并存，语义边界见模块 docstring）。
    """

    __tablename__ = "commercial_entitlements"
    __table_args__ = (
        CheckConstraint(
            "commercial_role IS NULL OR commercial_role IN ('R1', 'R2', 'R3', 'R4')",
            name="ck_commercial_entitlements_role",
        ),
        CheckConstraint(
            f"seat_status IN {SEAT_STATUSES!r}",
            name="ck_commercial_entitlements_seat_status",
        ),
        CheckConstraint(
            "seat_source IS NULL OR seat_source IN "
            "('first_delivery', 'bootcamp_practical', 'bootcamp_mentorship')",
            name="ck_commercial_entitlements_seat_source",
        ),
        CheckConstraint(
            "certification_status IN ('uncertified', 'certified')",
            name="ck_commercial_entitlements_certification",
        ),
        CheckConstraint(
            "delivery_eligibility IN ('none', 'eligible')",
            name="ck_commercial_entitlements_delivery_eligibility",
        ),
    )

    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="RESTRICT"), primary_key=True
    )
    # ── 角色分层（正交于 users.role 权限角色；NULL=未分层）──
    commercial_role: Mapped[str | None] = mapped_column(String(2))
    # ── 订阅权益：年度席位（3980）──
    seat_status: Mapped[str] = mapped_column(String(10), nullable=False, default="none")
    seat_source: Mapped[str | None] = mapped_column(String(24))
    seat_activated_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    seat_expires_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    # ── 认证状态：是否已获认证（培训出口；与 fde_level_evidence 等级评定互不替代）──
    certification_status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="uncertified"
    )
    certification_source: Mapped[str | None] = mapped_column(String(120))
    # ── 交付资格：是否具备接单并激活席位资格（不覆盖 fde_profiles.status）──
    delivery_eligibility: Mapped[str] = mapped_column(
        String(10), nullable=False, default="none"
    )

    user = relationship("User", foreign_keys=[user_id])


class TrainingEntitlement(Base, TimestampMixin):
    """培训权益购买行（1:N）：培训费／认证费／陪跑的购买与有效期。

    ``valid_until`` 可空——陪跑期限数值本期不定数（任务书 §1.2-6「规则先立
    框架、数值后填」），结构与容量先落。金额与科目记账归 G3 科目层，
    本表只承载权益事实（不存金额，避免与科目层双写）。
    """

    __tablename__ = "training_entitlements"
    __table_args__ = (
        CheckConstraint(
            f"item_type IN {TRAINING_ITEM_TYPES!r}",
            name="ck_training_entitlements_item_type",
        ),
        CheckConstraint(
            "status IN ('active', 'revoked')",
            name="ck_training_entitlements_status",
        ),
        Index("ix_training_entitlements_user", "user_id", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    item_type: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(10), nullable=False, default="active")
    purchased_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), nullable=False, server_default=UTC_TIMESTAMP_SQL
    )
    valid_from: Mapped[datetime | None] = mapped_column(UTCDateTime())
    valid_until: Mapped[datetime | None] = mapped_column(UTCDateTime())
    granted_by_user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    note: Mapped[str | None] = mapped_column(String(255))

    user = relationship("User", foreign_keys=[user_id])
    granted_by = relationship("User", foreign_keys=[granted_by_user_id])
