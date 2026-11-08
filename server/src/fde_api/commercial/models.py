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
from typing import Any

from sqlalchemy import JSON, CheckConstraint, ForeignKey, Index, String
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


# ── 商业化 G2：企业免费额度（ADR-004 主体认定 + ADR-007 人工确认默认）──

# 六项免费交付物闭集（完成判据=恰好六键全真，ADR-004 §1.5）
FREE_DIAGNOSIS_DELIVERABLES = (
    "diagnosis_report",  # 企业问题诊断报告
    "process_analysis",  # 业务流程初步分析
    "ai_opportunity_list",  # AI 应用机会清单
    "implementation_plan",  # 建议实施方案
    "project_tier_budget",  # 预计项目等级与预算区间（三档纯描述，无数值）
    "next_steps",  # 下一步实施建议
)

# 不免费范围（免费边界即产品边界，ADR-004 §1.6——代码层权威清单）
FREE_EXCLUSIONS = (
    "full_implementation",  # 完整实施
    "real_crm_erp_integration",  # 真实 CRM/ERP 接入
    "large_scale_data_processing",  # 大规模数据处理
    "custom_agent",  # 定制 Agent
    "production_deployment",  # 生产部署
    "continuous_operations",  # 持续运维
    "onsite_residency",  # 驻场
)

# 三档项目等级（纯描述性表述，无数值区间；命名不带 T——与区域席位档 T1–T3 解耦）
DIAGNOSIS_PROJECT_TIERS = {
    "standardized": {
        "label": "标准化程度高且风险低",
        "description": "AI 自助完成候选——适合标准化产品化交付路径。",
    },
    "multi_system": {
        "label": "涉及多个业务系统",
        "description": "AI 辅助＋企业人员审核——需要双方协同的半自助路径。",
    },
    "complex": {
        "label": "复杂业务流程、数据治理、系统集成",
        "description": "转专业 FDE 项目交付——预算区间以正式报价为准（免费诊断不含数值报价）。",
    },
}

# 两档体验上限（**保守占位缺省，试点前须填实数**——占位值非业务拍板数，ADR-004 §1.8）
EXPERIENCE_LIMIT_KINDS = ("founder", "deliverer")
EXPERIENCE_LIMITS = {
    "founder": {"simulation_runs": 3, "mentor_sessions": 1},
    "deliverer": {"simulation_runs": 5, "mentor_sessions": 2},
}
EXPERIENCE_LIMITS_PLACEHOLDER = True  # True=数值未拍板；试点数据到位后置 False 并填实数

# ── 三入口隔离（任务书 §6 语义：企业＝真实业务问题／创业者＝模拟体验／
#    交付者＝脱敏模拟项目考核）──
# 入口注册表是**三入口隔离的结构性声明**：每个入口只允许自己的数据域，
# 非企业入口取用 real_business 即拒（`trial_entry_scope_forbidden`）——
# 「创业者不能取到企业真实商机」的验收面（商机归属/渠道保护本体归 G4）。
REAL_BUSINESS_SCOPE = "real_business"

FREE_TRIAL_ENTRIES: dict[str, dict[str, Any]] = {
    "enterprise": {
        "label": "企业真实业务诊断",
        "scope": REAL_BUSINESS_SCOPE,
        "allowed_scopes": (REAL_BUSINESS_SCOPE,),
        "description": "基于企业真实业务问题的一次完整免费诊断（额度按企业主体计）。",
        "subject_key_required": True,
        "experience_limit_kind": None,  # 企业入口不适用体验档上限
    },
    "founder": {
        "label": "创业者模拟体验",
        "scope": "simulation",
        "allowed_scopes": ("simulation",),
        "description": "模拟场景中的交付能力体验——不触真实商机。",
        "subject_key_required": False,
        "experience_limit_kind": "founder",
    },
    "deliverer": {
        "label": "交付者脱敏模拟项目考核",
        "scope": "sanitized_simulation",
        "allowed_scopes": ("sanitized_simulation",),
        "description": "脱敏模拟项目考核——不触真实商机。",
        "subject_key_required": False,
        "experience_limit_kind": "deliverer",
    },
}
FREE_TRIAL_ENTRY_KEYS = tuple(FREE_TRIAL_ENTRIES)

QUOTA_STATES = ("granted", "in_progress", "completed")



class EnterpriseQuotaSubject(Base, TimestampMixin):
    """企业免费额度主体（PK=规范化统一社会信用代码，ADR-004 §1.1）。

    ``subject_key`` 经 ``normalize_subject_key`` 生成（大写去空格连字符 +
    mod-31 校验位验证）——**额度键挂主体而非账号**，是「换账号不重置」的
    结构性保证（按账号计的实现会在反例用例上转红，任务书 §6 验收）。
    """

    __tablename__ = "enterprise_quota_subjects"

    subject_key: Mapped[str] = mapped_column(String(18), primary_key=True)
    display_name: Mapped[str] = mapped_column(String(160), nullable=False)
    first_user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    note: Mapped[str | None] = mapped_column(String(255))

    first_user = relationship("User", foreign_keys=[first_user_id])


class EnterpriseFreeQuota(Base, TimestampMixin):
    """企业免费诊断额度（每主体一份；一次一主体、长期有效不重置）。

    状态机（三条 CHECK 联锁，见 __table_args__）：
    granted（授予未启动）→ in_progress（绑定账号，诊断进行中）→
    completed（六项齐备；企业确认后为终态确认）。**无重置路径**。
    """

    __tablename__ = "enterprise_free_quota"
    __table_args__ = (
        CheckConstraint(
            "state IN ('granted', 'in_progress', 'completed')",
            name="ck_enterprise_free_quota_state",
        ),
        CheckConstraint(
            "(state = 'granted' AND bound_user_id IS NULL AND completed_at IS NULL "
            "AND enterprise_confirmed_at IS NULL) OR "
            "(state <> 'granted' AND bound_user_id IS NOT NULL)",
            name="ck_enterprise_free_quota_bound_shape",
        ),
        CheckConstraint(
            "state != 'completed' AND completed_at IS NULL "
            "OR state = 'completed' AND completed_at IS NOT NULL",
            name="ck_enterprise_free_quota_completed_shape",
        ),
        CheckConstraint(
            "enterprise_confirmed_at IS NULL OR state = 'completed'",
            name="ck_enterprise_free_quota_confirm_requires_completed",
        ),
    )

    subject_key: Mapped[str] = mapped_column(
        String(18),
        ForeignKey("enterprise_quota_subjects.subject_key", ondelete="RESTRICT"),
        primary_key=True,
    )
    state: Mapped[str] = mapped_column(String(12), nullable=False, default="granted")
    granted_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), nullable=False, server_default=UTC_TIMESTAMP_SQL
    )
    granted_by_user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    bound_user_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="RESTRICT")
    )
    bound_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    deliverables: Mapped[dict[str, bool] | None] = mapped_column(JSON)
    enterprise_confirmed_by_user_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="RESTRICT")
    )
    enterprise_confirmed_at: Mapped[datetime | None] = mapped_column(UTCDateTime())

    subject = relationship("EnterpriseQuotaSubject", foreign_keys=[subject_key])
