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

**G3 追加（任务书 §7；ADR-003 §2.1–§2.5）**：收入科目层与订阅席位计费——
三类科目（席位费/培训费/项目分成）**分别记账可分别核对**；六项计费名目
**只定义归属不定义计算方式**；分成比例**本期不落数**（只落「按角色与项目
类型配置」的结构）；席位份额**复用** ``dispatch/settlements.py::seat_shares_for``
（引用其结果，不重算）；**禁止**在 ``delivery_settlements`` 上加列硬塞科目。
本期只落一个金额：首单席位费 3980（任务书 §7 明文），其余金额/期限/分数线
一律走配置位且**缺省未设**。
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    JSON,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    text,
)
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


# ══════════════════════════════════════════════════════════════════════════
# 商业化 G3：收入科目层与订阅席位计费（任务书 §7；ADR-003 §2.1–§2.5 / ADR-008）
# ══════════════════════════════════════════════════════════════════════════

# ── 三类科目（任务书 §7「科目层」：培训费、席位费、项目分成分别记账可分别核对）──
REVENUE_SUBJECT_TYPES = ("seat_fee", "training_fee", "project_share")

# ── 六项计费名目（ADR-003 §2.4：**只定义归属，不定义计算方式**）──
REVENUE_LINE_ITEMS = (
    "software_subscription",  # 软件订阅
    "enterprise_subscription",  # 企业订阅
    "usage",  # 使用量
    "project_fee",  # 项目费
    "software_service_fee",  # 软件服务费
    "platform_share",  # 平台分成
)

# 名目 → 科目归属矩阵（**归属**定义；金额算法不在本期定义——结账金额走线下约定）
LINE_ITEM_SUBJECTS: dict[str, tuple[str, ...]] = {
    "software_subscription": ("seat_fee",),
    "enterprise_subscription": ("seat_fee",),
    "usage": ("seat_fee",),
    "project_fee": ("project_share",),
    "software_service_fee": ("training_fee",),
    "platform_share": ("project_share",),
}

# 科目记账状态（记账层；收款状态仍在 payments 侧，两层不混）
REVENUE_LEDGER_STATUSES = ("recorded", "reconciled", "voided")

# ── 套餐目录（**不存价目**：价格走 quotes/payments 收款台账，避免双写）──
# ``covers_first_year_fee``＝套餐是否已含首年席位费（任务书 §7「席位不重复收」：
# 实战营/陪跑营均含首年 3980 ⇒ 已购者不再重复收首单扣费）。
REVENUE_PACKAGES: dict[str, dict[str, Any]] = {
    "bootcamp_practical": {
        "label": "实战营（含首年席位）",
        "seat_source": "bootcamp_practical",
        "covers_first_year_fee": True,
    },
    "bootcamp_mentorship": {
        "label": "陪跑营（含首年席位）",
        "seat_source": "bootcamp_mentorship",
        "covers_first_year_fee": True,
    },
    "first_delivery": {
        "label": "首单席位（首单扣费）",
        "seat_source": "first_delivery",
        "covers_first_year_fee": False,
    },
}
REVENUE_PACKAGE_CODES = tuple(REVENUE_PACKAGES)

# ── 扣费方式（任务书 §7：方案 A 一次性扣除为默认，**须事先书面选定**）──
DEDUCTION_METHODS = ("one_time", "annual_installment")
# 本期**只实现方案 A**：方案 B（年度分期）的周期与算式未拍板（任务书 §17 数值类
# 待外部输入），选 B 时扣费闸 fail-closed 拒绝（不误扣、不静默按 A 扣）。
DEDUCTION_METHODS_IMPLEMENTED = ("one_time",)
DEDUCTION_ELECTION_STATUSES = ("elected", "superseded")

# ── 费用/周期配置位（**本期全部 unset**：认证费金额、陪跑期限、认证通过线）──
FEE_CONFIG_KEYS = (
    "certification_fee",  # 认证费金额（缺省不可收款）
    "mentoring_period_days",  # 陪跑期限（与培训周期挂钩，数值待定）
    "certification_pass_threshold",  # 认证通过线（认证挂模拟考核，通过线本期不设）
)
FEE_CONFIG_STATUSES = ("unset", "configured")
FEE_CONFIG_VALUE_KINDS = ("amount", "days", "threshold")
# 配置位 → 值型（配置位的结构属性，随槽位固定；值本身本期一律未设）
FEE_CONFIG_VALUE_KIND_BY_KEY: dict[str, str] = {
    "certification_fee": "amount",
    "mentoring_period_days": "days",
    "certification_pass_threshold": "threshold",
}
# 可直接进科目层的收费项（其余配置位是周期/门槛，不是金额）
CHARGEABLE_FEE_KEYS = ("certification_fee",)

# ── 分成比例配置结构（ADR-003 §2.3：按角色与项目类型配置，**本期不落数**）──
SPLIT_RULE_STATUSES = ("unset", "configured")

# ── 认证记录（认证挂模拟考核；通过线本期不设 ⇒ 缺省停在 pending_threshold）──
CERTIFICATION_RECORD_STATUSES = (
    "pending_threshold",  # 已挂考核，但通过线未配置 ⇒ 不判定通过
    "certified",
    "rejected",
    "revoked",
)

# 首单席位费（任务书 §7 明文：交付者首个付费项目**交付完成并验收后**扣除 3980）。
# 本期**只有这一个金额落数**；认证费金额/陪跑期限/通过线/分成比例一律走配置位
# 且缺省未设。数值集中此处一处，便于商务/法务复核后一次替换（同 DISPATCH_CONSTANTS 惯例）。
FIRST_ORDER_SEAT_FEE = Decimal("3980.00")


class CommercialSplitRule(Base, TimestampMixin):
    """分成比例配置结构（ADR-003 §2.3：**按角色与项目类型配置**，本期不落数）。

    一行＝一个 (角色, 项目类型) 维度。``status='unset'`` 表示**维度已登记、
    比例未定数**——本期表内零行，任何比例都不得预写默认值（任务书 §7 硬约束）。
    ``ratio_bp``（万分比）只在 ``status='configured'`` 时非空，且必须附书面依据
    指针与 sha256 指纹（证据红线：原件不进仓、不进库）。

    **本期不参与金额计算**：科目层在分成事件上**引用**既有分账结果
    （ADR-003 §2.2「不重算」），本表只提供「按角色与项目类型」的落位与可见性。
    """

    __tablename__ = "commercial_split_rules"
    __table_args__ = (
        UniqueConstraint(
            "role_code", "project_type", name="uq_commercial_split_rules_dimension"
        ),
        CheckConstraint(
            "role_code IN ('R1', 'R2', 'R3', 'R4')", name="ck_commercial_split_rules_role"
        ),
        CheckConstraint(
            f"status IN {SPLIT_RULE_STATUSES!r}", name="ck_commercial_split_rules_status"
        ),
        CheckConstraint(
            "status <> 'configured' OR (ratio_bp IS NOT NULL AND ratio_bp >= 0 "
            "AND ratio_bp <= 10000)",
            name="ck_commercial_split_rules_ratio_shape",
        ),
        CheckConstraint(
            "status <> 'unset' OR ratio_bp IS NULL",
            name="ck_commercial_split_rules_unset_has_no_ratio",
        ),
        Index("ix_commercial_split_rules_role", "role_code"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    role_code: Mapped[str] = mapped_column(String(2), nullable=False)
    project_type: Mapped[str] = mapped_column(String(32), nullable=False)
    ratio_bp: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(12), nullable=False, default="unset")
    source_uri: Mapped[str | None] = mapped_column(String(500))
    content_hash: Mapped[str | None] = mapped_column(String(64))
    configured_by_user_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="RESTRICT")
    )
    configured_at: Mapped[datetime | None] = mapped_column(UTCDateTime())


class CommercialFeeConfig(Base, TimestampMixin):
    """费用/周期配置位（认证费金额、陪跑期限、认证通过线）——**本期全部 unset**。

    语义：**缺省不可用**。
    - ``certification_fee`` 未配置 ⇒ 认证费**不可收款**（写路径 409
      ``fee_not_configured``，任务书 §7「金额本期不设……缺省不可收款」）；
    - ``mentoring_period_days`` 未配置 ⇒ 陪跑期限**数值待定**（结构在，
      ``TrainingEntitlement.valid_until`` 留空，任务书 §7「陪跑期限与培训周期
      挂钩：结构先落，数值待定」）；
    - ``certification_pass_threshold`` 未配置 ⇒ 认证**不判定通过**（停在
      ``pending_threshold``，任务书 §7「认证挂模拟考核：通过线本期不设」）。
    """

    __tablename__ = "commercial_fee_configs"
    __table_args__ = (
        CheckConstraint(
            f"status IN {FEE_CONFIG_STATUSES!r}", name="ck_commercial_fee_configs_status"
        ),
        CheckConstraint(
            f"value_kind IN {FEE_CONFIG_VALUE_KINDS!r}",
            name="ck_commercial_fee_configs_value_kind",
        ),
        CheckConstraint(
            "status <> 'unset' OR (amount IS NULL AND days IS NULL AND threshold IS NULL)",
            name="ck_commercial_fee_configs_unset_has_no_value",
        ),
        CheckConstraint(
            "status <> 'configured' OR ("
            "(value_kind = 'amount' AND amount IS NOT NULL AND days IS NULL "
            "AND threshold IS NULL) OR "
            "(value_kind = 'days' AND days IS NOT NULL AND amount IS NULL "
            "AND threshold IS NULL) OR "
            "(value_kind = 'threshold' AND threshold IS NOT NULL AND amount IS NULL "
            "AND days IS NULL))",
            name="ck_commercial_fee_configs_configured_shape",
        ),
        CheckConstraint(
            "status <> 'configured' OR (source_uri IS NOT NULL AND content_hash IS NOT NULL)",
            name="ck_commercial_fee_configs_configured_has_evidence",
        ),
    )

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(12), nullable=False, default="unset")
    amount: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    days: Mapped[int | None] = mapped_column(Integer)
    threshold: Mapped[Decimal | None] = mapped_column(Numeric(8, 4))
    source_uri: Mapped[str | None] = mapped_column(String(500))
    content_hash: Mapped[str | None] = mapped_column(String(64))
    configured_by_user_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="RESTRICT")
    )
    configured_at: Mapped[datetime | None] = mapped_column(UTCDateTime())


class CommercialDeductionElection(Base, TimestampMixin):
    """扣费方式**书面选定**记录（任务书 §7「扣费方式方案 A（一次性扣除）为默认，
    **须交付者事先书面选定**」）。

    - **选定前不得扣费**：本表无 elected 行 ⇒ 首单扣费闸 409
      ``deduction_method_not_selected``（任务书 §7 验收）；
    - 书面证据只存 ``source_uri`` 指针 + ``content_hash`` sha256 指纹——原件永不
      进仓、永不进库（证据红线）；
    - **自我动作例外**（ADR-007 §2.4）：交付者本人选定自己的扣费方式属当事人
      自证，不走 admin 密码双闸；他人/admin **不得代选定**（防止平台替用户
      承诺扣费）。
    """

    __tablename__ = "commercial_deduction_elections"
    __table_args__ = (
        CheckConstraint(
            f"method IN {DEDUCTION_METHODS!r}",
            name="ck_commercial_deduction_elections_method",
        ),
        CheckConstraint(
            f"status IN {DEDUCTION_ELECTION_STATUSES!r}",
            name="ck_commercial_deduction_elections_status",
        ),
        Index(
            "uq_commercial_deduction_elections_active",
            "user_id",
            unique=True,
            postgresql_where=text("status = 'elected'"),
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    method: Mapped[str] = mapped_column(String(24), nullable=False)
    status: Mapped[str] = mapped_column(String(12), nullable=False, default="elected")
    source_uri: Mapped[str] = mapped_column(String(500), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    elected_by_user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    elected_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), nullable=False, server_default=UTC_TIMESTAMP_SQL
    )


class CommercialRevenueLedger(Base, TimestampMixin):
    """收入科目层（ADR-003 §2.1：**收入类型 → 金额 → 关联对象**）。

    与 ``delivery_settlements``（平台↔FDE 分账）**分层不合并**：分账表按
    「项目×席位」读，科目账按「科目×期间」读（ADR-003 §3）。**禁止**在本表
    复用分账列，也**禁止**回头给 ``delivery_settlements`` 加列硬塞科目
    （ADR-003 §2.1／任务书 §0.3）。

    - ``subject_type``：三类科目（席位费／培训费／项目分成）分别记账可分别核对；
    - ``line_item``：六项计费名目之一，**只定义归属不定义计算方式**
      （归属矩阵 ``LINE_ITEM_SUBJECTS``，ADR-003 §2.4）；
    - 关联对象通过外键指回既有结算与报价/合同对象（``quotes``／``payments``／
      ``contracts``／``delivery_settlements``）——科目账可与既有收款台账对账；
    - ``seat_shares`` 存 ``seat_shares_for`` 的**结果引用**（ADR-003 §2.2：
      科目层引用其结果、**不重算**份额）。
    """

    __tablename__ = "commercial_revenue_ledger"
    __table_args__ = (
        CheckConstraint(
            f"subject_type IN {REVENUE_SUBJECT_TYPES!r}",
            name="ck_commercial_revenue_ledger_subject_type",
        ),
        CheckConstraint(
            f"line_item IN {REVENUE_LINE_ITEMS!r}",
            name="ck_commercial_revenue_ledger_line_item",
        ),
        CheckConstraint(
            f"status IN {REVENUE_LEDGER_STATUSES!r}",
            name="ck_commercial_revenue_ledger_status",
        ),
        CheckConstraint("amount >= 0", name="ck_commercial_revenue_ledger_amount"),
        CheckConstraint(
            "package_code IS NULL OR package_code IN "
            "('bootcamp_practical', 'bootcamp_mentorship', 'first_delivery')",
            name="ck_commercial_revenue_ledger_package_code",
        ),
        CheckConstraint(
            "seat_source IS NULL OR seat_source IN "
            "('first_delivery', 'bootcamp_practical', 'bootcamp_mentorship')",
            name="ck_commercial_revenue_ledger_seat_source",
        ),
        CheckConstraint(
            "role_code IS NULL OR role_code IN ('R1', 'R2', 'R3', 'R4')",
            name="ck_commercial_revenue_ledger_role_code",
        ),
        CheckConstraint(
            "fee_key IS NULL OR fee_key IN ('certification_fee')",
            name="ck_commercial_revenue_ledger_fee_key",
        ),
        # 关联对象至少一个非空——科目行不得悬空（ADR-003 §2.1 收入类型→金额→
        # 关联对象；关联对象＝订单〔套餐〕/席位/分成事件/报价/收款/合同/分账）
        CheckConstraint(
            "quote_id IS NOT NULL OR payment_id IS NOT NULL OR contract_id IS NOT NULL "
            "OR delivery_settlement_id IS NOT NULL OR delivery_package_id IS NOT NULL "
            "OR training_entitlement_id IS NOT NULL OR package_code IS NOT NULL",
            name="ck_commercial_revenue_ledger_association",
        ),
        Index("ix_commercial_revenue_ledger_subject", "subject_type", "status"),
        Index("ix_commercial_revenue_ledger_user", "subject_user_id"),
        Index("ix_commercial_revenue_ledger_occurred", "occurred_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    subject_type: Mapped[str] = mapped_column(String(16), nullable=False)
    line_item: Mapped[str] = mapped_column(String(24), nullable=False)
    status: Mapped[str] = mapped_column(String(12), nullable=False, default="recorded")
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(8), nullable=False, default="CNY")
    # 义务人（计费对象：交付者／学员）＋ 收款方（项目分成＝交付者；平台侧收费为空）
    subject_user_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="RESTRICT")
    )
    payee_user_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="RESTRICT")
    )
    # ── 关联对象（ADR-003 §2.1：外键指回既有结算与报价/合同对象）──
    quote_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("quotes.id", ondelete="RESTRICT")
    )
    payment_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("payments.id", ondelete="RESTRICT")
    )
    contract_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("contracts.id", ondelete="RESTRICT")
    )
    delivery_settlement_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("delivery_settlements.id", ondelete="RESTRICT")
    )
    delivery_package_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("delivery_packages.id", ondelete="RESTRICT")
    )
    training_entitlement_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("training_entitlements.id", ondelete="RESTRICT")
    )
    split_rule_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("commercial_split_rules.id", ondelete="RESTRICT")
    )
    # ── 业务维度 ──
    package_code: Mapped[str | None] = mapped_column(String(24))
    seat_source: Mapped[str | None] = mapped_column(String(24))
    fee_key: Mapped[str | None] = mapped_column(String(64))
    role_code: Mapped[str | None] = mapped_column(String(2))
    project_type: Mapped[str | None] = mapped_column(String(32))
    # seat_shares_for 的结果引用（ADR-003 §2.2：引用不重算）
    seat_shares: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    basis: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    # 凭证/依据指针 + sha256 指纹（红线：原件不入库不入仓）
    source_uri: Mapped[str | None] = mapped_column(String(500))
    content_hash: Mapped[str | None] = mapped_column(String(64))
    recorded_by_user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    occurred_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), nullable=False, server_default=UTC_TIMESTAMP_SQL
    )


class CommercialCertificationRecord(Base, TimestampMixin):
    """认证记录（任务书 §7「认证挂模拟考核」）。

    认证状态**由模拟考核结果驱动**：本行挂 ``simulation_evaluations`` 指针并
    快照当次的 verdict/score（重评不改写历史行，同款「同层同评估器同规则版本
    只留一行」纪律在 simulation 域已由唯一约束保证）。

    **通过线本期不设**：``threshold`` 配置位未设 ⇒ 本行停在 ``pending_threshold``，
    **不判定通过**（认证状态不变更）——缺省不可通过，不落任何默认分数线。
    """

    __tablename__ = "commercial_certification_records"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "simulation_evaluation_id",
            name="uq_commercial_certification_records_identity",
        ),
        CheckConstraint(
            f"status IN {CERTIFICATION_RECORD_STATUSES!r}",
            name="ck_commercial_certification_records_status",
        ),
        CheckConstraint(
            "status <> 'certified' OR threshold IS NOT NULL",
            name="ck_commercial_certification_records_certified_has_threshold",
        ),
        Index("ix_commercial_certification_records_user", "user_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    simulation_evaluation_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("simulation_evaluations.id", ondelete="RESTRICT"),
        nullable=False,
    )
    evaluation_verdict: Mapped[str] = mapped_column(String(16), nullable=False)
    evaluation_score: Mapped[Decimal] = mapped_column(Numeric(8, 4), nullable=False)
    threshold: Mapped[Decimal | None] = mapped_column(Numeric(8, 4))
    status: Mapped[str] = mapped_column(
        String(24), nullable=False, default="pending_threshold"
    )
    source_uri: Mapped[str | None] = mapped_column(String(500))
    content_hash: Mapped[str | None] = mapped_column(String(64))
    decided_by_user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    decided_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), nullable=False, server_default=UTC_TIMESTAMP_SQL
    )
