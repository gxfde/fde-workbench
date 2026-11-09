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
    Boolean,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
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
    # 企业自助注册时的业务问题描述（G6；注册必填，库列可空＝兼容 G2 admin 授予的存量行）
    problem_description: Mapped[str | None] = mapped_column(Text)

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


# ══════════════════════════════════════════════════════════════════════════
# 商业化 G4：商机归属与渠道保护（任务书 §8；ADR-009）
# ══════════════════════════════════════════════════════════════════════════

# 七步链路状态机（成文规则 §2）
OPPORTUNITY_STATUSES = (
    "submitted",  # ① 报备（创业者提交企业线索）
    "enterprise_confirmed",  # ② 企业确认有真实需求
    "attribution_confirmed",  # ③ 平台确认商机归属
    "presales",  # ④ 创业者负责售前与客户关系
    "matched",  # ⑤ 平台撮合交付者
    "settled",  # ⑥ 按既定分成规则结算
    "disputed",  # 争议中（规则位未配置则不可发起）
    "withdrawn",  # 报备人撤回
)

# 保护期三态（**可区分**：未配置 ≠ 永久保护 ≠ 立即失效；ADR-009 §2.3）
OPPORTUNITY_PROTECTION_STATUSES = (
    "unconfigured",  # 规则位未配置 ⇒ 既非永久保护，也非立即失效
    "active",  # 保护中（**必有到期时刻**——结构上不可能永久锁定）
    "expired",  # 已到期（直签立即恢复放行）
    "revoked",  # 已撤销（人工显式撤销）
)

# 规则位（**成文规则 ↔ 代码配置位一一对应**；本期全部 unset，ADR-009 §2.2）
OPPORTUNITY_RULE_KEYS = (
    "protection_period_days",  # 保护期长度（数值）
    "renewal_conditions",  # 续期条件
    "customer_choice",  # 客户自主选择权
    "dispute_handling",  # 争议处理机制
    "attribution_criteria",  # 归属判定
)
OPPORTUNITY_RULE_VALUE_KINDS = {
    "protection_period_days": "days",
    "renewal_conditions": "criteria",
    "customer_choice": "criteria",
    "dispute_handling": "criteria",
    "attribution_criteria": "criteria",
}
OPPORTUNITY_RULE_STATUSES = ("unset", "configured")


class CommercialOpportunity(Base, TimestampMixin):
    """商机（报备→确认→保护→售前→撮合→结算；ADR-009）。

    **只登企业代号与业务描述**——真实企业名/联系人/凭证一律不入库（AGENTS 红线）；
    线索、企业答复、归属判据、争议材料**只存指针 + sha256 指纹**。

    归属（``attribution_owner_user_id``）是本域事实：**企业侧立项路径没有任何
    写路径可触碰本行**——「企业后续自行注册不自动易主」是结构性保证（ADR-009
    §2.5），并由反例用例钉死。
    """

    __tablename__ = "commercial_opportunities"
    __table_args__ = (
        CheckConstraint(
            f"status IN {OPPORTUNITY_STATUSES!r}",
            name="ck_commercial_opportunities_status",
        ),
        CheckConstraint(
            f"protection_status IN {OPPORTUNITY_PROTECTION_STATUSES!r}",
            name="ck_commercial_opportunities_protection_status",
        ),
        # 归属人非空 ⇒ 必有确认时刻（归属必须是「确认过的事实」）
        CheckConstraint(
            "attribution_owner_user_id IS NULL OR attribution_confirmed_at IS NOT NULL",
            name="ck_commercial_opportunities_attribution_shape",
        ),
        # 进入售前/撮合/结算 ⇒ 必有归属人（链路不可跳过归属确认）
        CheckConstraint(
            "status NOT IN ('presales', 'matched', 'settled') "
            "OR attribution_owner_user_id IS NOT NULL",
            name="ck_commercial_opportunities_stage_requires_owner",
        ),
        # **保护中必有起止时刻**——结构上不可能出现永久保护（任务书 §8）
        CheckConstraint(
            "protection_status <> 'active' OR "
            "(protection_started_at IS NOT NULL AND protection_expires_at IS NOT NULL)",
            name="ck_commercial_opportunities_protection_window",
        ),
        CheckConstraint(
            "protection_status <> 'active' OR protection_expires_at > protection_started_at",
            name="ck_commercial_opportunities_protection_order",
        ),
        Index("ix_commercial_opportunities_enterprise", "enterprise_code"),
        Index("ix_commercial_opportunities_reporter", "reported_by_user_id"),
        Index("ix_commercial_opportunities_status", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    # 企业代号（三段式，与 projects.enterprise_code 同口径；**不是真实企业名**）
    enterprise_code: Mapped[str] = mapped_column(String(80), nullable=False)
    title: Mapped[str] = mapped_column(String(160), nullable=False)
    note: Mapped[str | None] = mapped_column(String(500))
    status: Mapped[str] = mapped_column(
        String(24), nullable=False, default="submitted", server_default="submitted"
    )
    # ── ① 报备（当事人自证）──
    reported_by_user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    reported_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), nullable=False, server_default=UTC_TIMESTAMP_SQL
    )
    source_uri: Mapped[str] = mapped_column(String(500), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    # ── ② 企业确认有真实需求（平台代录企业书面答复）──
    enterprise_confirmed_by_user_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="RESTRICT")
    )
    enterprise_confirmed_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    enterprise_confirmation_uri: Mapped[str | None] = mapped_column(String(500))
    enterprise_confirmation_hash: Mapped[str | None] = mapped_column(String(64))
    # ── ③ 平台确认商机归属（关键流转：admin 门 + 密码确认）──
    attribution_owner_user_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="RESTRICT")
    )
    attribution_confirmed_by_user_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="RESTRICT")
    )
    attribution_confirmed_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    attribution_uri: Mapped[str | None] = mapped_column(String(500))
    attribution_hash: Mapped[str | None] = mapped_column(String(64))
    # ── ④ 保护期（规则位未配置 ⇒ unconfigured；active 必有到期）──
    protection_status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="unconfigured", server_default="unconfigured"
    )
    protection_started_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    protection_expires_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    protection_renewal_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    protection_renewed_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    # ── ⑤ 售前与客户关系 ──
    presales_owner_user_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="RESTRICT")
    )
    # ── ⑥ 撮合交付者（引用既有 dispatch 交付包，不建第二套撮合）──
    matched_delivery_package_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("delivery_packages.id", ondelete="RESTRICT")
    )
    customer_choice_package_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("delivery_packages.id", ondelete="RESTRICT")
    )
    # ── ⑦ 按既定分成规则结算（引用 G3 科目层的 project_share 行）──
    settled_ledger_entry_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("commercial_revenue_ledger.id", ondelete="RESTRICT")
    )
    # 规则位状态快照（最近一次规则相关流转时；成文规则未定数的事实留痕）
    rule_snapshot: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    # ── 旁支：撤回 / 争议 ──
    withdrawn_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    disputed_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    dispute_uri: Mapped[str | None] = mapped_column(String(500))
    dispute_hash: Mapped[str | None] = mapped_column(String(64))


class CommercialOpportunityRule(Base, TimestampMixin):
    """商机规则位（成文规则 ↔ 代码配置位**一一对应**；本期**全部 unset**）。

    「规则先立框架、数值后填」（任务书 §1.2-6）：配置位缺省即 ``unset``，
    **任何路径都不得预写业务数值**——未配置的相关动作一律 fail-closed
    （409 ``rule_not_configured``），而不是回落到某个硬编码默认值。
    """

    __tablename__ = "commercial_opportunity_rules"
    __table_args__ = (
        CheckConstraint(
            f"status IN {OPPORTUNITY_RULE_STATUSES!r}",
            name="ck_commercial_opportunity_rules_status",
        ),
        CheckConstraint(
            "value_kind IN ('days', 'criteria')",
            name="ck_commercial_opportunity_rules_value_kind",
        ),
        CheckConstraint(
            "status <> 'unset' OR (days IS NULL AND criteria IS NULL)",
            name="ck_commercial_opportunity_rules_unset_has_no_value",
        ),
        CheckConstraint(
            "status <> 'configured' OR ("
            "(value_kind = 'days' AND days IS NOT NULL AND days > 0 AND criteria IS NULL) OR "
            "(value_kind = 'criteria' AND criteria IS NOT NULL AND days IS NULL))",
            name="ck_commercial_opportunity_rules_configured_shape",
        ),
        CheckConstraint(
            "status <> 'configured' OR (source_uri IS NOT NULL AND content_hash IS NOT NULL)",
            name="ck_commercial_opportunity_rules_configured_has_evidence",
        ),
    )

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(
        String(12), nullable=False, default="unset", server_default="unset"
    )
    days: Mapped[int | None] = mapped_column(Integer)
    criteria: Mapped[str | None] = mapped_column(String(500))
    source_uri: Mapped[str | None] = mapped_column(String(500))
    content_hash: Mapped[str | None] = mapped_column(String(64))
    configured_by_user_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="RESTRICT")
    )
    configured_at: Mapped[datetime | None] = mapped_column(UTCDateTime())



# ══════════════════════════════════════════════════════════════════════════
# G5：区域合作商能力建设（T-12a，**不含 T-12b**；ADR-005 区域商业化闸）
# ══════════════════════════════════════════════════════════════════════════

REGIONAL_PARTNER_STAGES = (
    "city_observer",   # 城市观察伙伴（免费申请）
    "city_service",    # 城市服务伙伴（按项目结算，一单一结，不设固定年费）
    "formal_partner",  # 正式区域合作商（三档定价，见 regional_partner_tiers）
    "regional_agent",  # 区域代理（**本期不启用**——保留位置，无任何进入路径）
)

# 阶段注记（读面派生；「暂不启用」是任务书 §9 对区域代理的落库要求）
REGIONAL_PARTNER_STAGE_NOTES = {
    "city_observer": "免费申请：参与活动、体验系统、了解市场；不授予独家区域权",
    "city_service": "按项目结算，一单一结，不设固定年费；不授予独家区域权",
    "formal_partner": "正式区域合作商（三档定价以 BP v4.0 为唯一基准）",
    "regional_agent": "暂不启用（省级方案待试点后另定）",
}

REGIONAL_TIER_CODES = ("T1", "T2", "T3")

REGIONAL_GATE_STATUSES = ("closed", "opened")

# 售卖开关的合规条件清单（开启的**必要条件**；任务书 §9 硬约束——本期只登记，
# 不实现任何对外收费签约路径；「本模式是否被认定为特许经营」是法律判断，须律师意见）
REGIONAL_GATE_CONDITION_KEYS = (
    "filing",         # ① 首次订立特许经营合同后 15 日内向商务主管部门备案
    "disclosure",     # ② 订立合同之日前至少 30 日书面披露（经营资源/费用构成/合同文本）
    "cooling_off",    # ③ 合同含被特许人单方解除冷静期条款并明确费用返还方式
    "qualification",  # ④ 「至少 2 个直营店且经营满 1 年」主体资格（客观时间门槛，不可提前）
)

REGIONAL_GATE_SINGLETON_ID = "regional-sale-gate"

# 正式区域合作商三档定价种子（**以 BP v4.0 为唯一基准**，v4.0 终版经蔡工拍板）——
# 迁移播种与惰性补建（ensure_tier_catalog）共用此权威；测试机器闸对规则文件双向核对。
REGIONAL_TIER_SEED = (
    {"tier_code": "T1", "annual_fee_amount": Decimal("29800.00"),
     "included_seats": 15, "transfer_quota_seats": 7,
     "basis_reference": "BP v4.0 附录 C（v4.0 终版，经蔡工拍板）"},
    {"tier_code": "T2", "annual_fee_amount": Decimal("59800.00"),
     "included_seats": 30, "transfer_quota_seats": 15,
     "basis_reference": "BP v4.0 附录 C（v4.0 终版，经蔡工拍板）"},
    {"tier_code": "T3", "annual_fee_amount": Decimal("98000.00"),
     "included_seats": 50, "transfer_quota_seats": 25,
     "basis_reference": "BP v4.0 附录 C（v4.0 终版，经蔡工拍板）"},
)


class RegionalPartnerTier(Base, TimestampMixin):
    """正式区域合作商三档定价目录（**以 BP v4.0 为唯一基准**；定价定案目录数据）。

    目录存在 ≠ 可以售卖——对外收费签约被 ``regional_sale_gate`` 全局闸住
    （默认 closed，开启须合规条件清单四项齐备，ADR-005 §2.2）。
    城市服务伙伴**没有**档位行——按项目结算、不设固定年费是其结构性属性
    （本表只收正式区域合作商三档）。
    """

    __tablename__ = "regional_partner_tiers"
    __table_args__ = (
        CheckConstraint(
            f"tier_code IN {REGIONAL_TIER_CODES!r}",
            name="ck_regional_partner_tiers_tier_code",
        ),
        CheckConstraint(
            "annual_fee_amount > 0",
            name="ck_regional_partner_tiers_amount_positive",
        ),
        CheckConstraint(
            "included_seats > 0 AND transfer_quota_seats >= 0 "
            "AND transfer_quota_seats < included_seats",
            name="ck_regional_partner_tiers_seats_shape",
        ),
    )

    tier_code: Mapped[str] = mapped_column(String(8), primary_key=True)
    annual_fee_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    included_seats: Mapped[int] = mapped_column(Integer, nullable=False)
    transfer_quota_seats: Mapped[int] = mapped_column(Integer, nullable=False)
    # 定价基准指针（BP v4.0 附录 C，经蔡工拍板；不落第三方材料正文）
    basis_reference: Mapped[str] = mapped_column(String(200), nullable=False)


class RegionalPartner(Base, TimestampMixin):
    """区域伙伴主体行（四阶段可区分；任务书 §9 / GAP-12）。

    **只登伙伴代号与区域名**——真实身份材料一律指针 + sha256（AGENTS 红线）。
    阶段升级须书面依据（指针＋指纹）；**前两阶段结构性不授予独家区域权**
    （CHECK 联锁）；``regional_agent`` 在闭集里保留位置但**本期无任何写路径**
    （服务层显式拒绝——「暂不启用」不是数据状态，是能力边界）。
    """

    __tablename__ = "regional_partners"
    __table_args__ = (
        CheckConstraint(
            f"stage IN {REGIONAL_PARTNER_STAGES!r}",
            name="ck_regional_partners_stage",
        ),
        # 前两阶段**不得授予独家区域权**（任务书 §9：结构性 CHECK，非判据）
        CheckConstraint(
            "stage NOT IN ('city_observer', 'city_service') OR exclusive_territory = FALSE",
            name="ck_regional_partners_first_two_stages_no_exclusive",
        ),
        # 观察伙伴是初始态：无升级留痕；进入服务伙伴/正式合作商必有升级留痕
        CheckConstraint(
            "stage <> 'city_observer' OR (stage_changed_at IS NULL AND stage_evidence_uri IS NULL)",
            name="ck_regional_partners_observer_shape",
        ),
        CheckConstraint(
            "stage <> 'city_service' OR stage_changed_at IS NOT NULL",
            name="ck_regional_partners_service_promoted",
        ),
        # 正式合作商 = 对外收费签约的开始：升级留痕 + 书面依据（指针+指纹）齐备
        CheckConstraint(
            "stage <> 'formal_partner' OR (stage_changed_at IS NOT NULL "
            "AND stage_evidence_uri IS NOT NULL AND stage_evidence_hash IS NOT NULL)",
            name="ck_regional_partners_formal_evidence",
        ),
        Index("ix_regional_partners_stage", "stage"),
        UniqueConstraint("partner_code", name="uq_regional_partners_partner_code"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    # 伙伴代号（企业代号三段式口径；**不是真实企业名**）
    partner_code: Mapped[str] = mapped_column(String(80), nullable=False)
    region_name: Mapped[str] = mapped_column(String(120), nullable=False)
    note: Mapped[str | None] = mapped_column(String(500))
    stage: Mapped[str] = mapped_column(
        String(20), nullable=False, default="city_observer", server_default="city_observer"
    )
    # ── 申请（当事人自证，免费）──
    applicant_user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    applied_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), nullable=False, server_default=UTC_TIMESTAMP_SQL
    )
    # ── 阶段升级（admin+密码；书面依据指针+指纹；正式档须选择 T1/T2/T3）──
    stage_changed_by_user_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="RESTRICT")
    )
    stage_changed_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    stage_evidence_uri: Mapped[str | None] = mapped_column(String(500))
    stage_evidence_hash: Mapped[str | None] = mapped_column(String(64))
    tier_code: Mapped[str | None] = mapped_column(String(8))
    exclusive_territory: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )


class RegionalSaleGate(Base, TimestampMixin):
    """区域售卖开关（**默认 closed**——售卖能力默认关闭；ADR-005 §2.2）。

    开启＝关键流转（admin 门＋密码确认双闸），且**合规条件清单四项的签署证据
    （指针＋指纹＋签署时刻）必须先行登记齐备**——CHECK 结构性排除缺件开门。
    「两店一年」是客观时间门槛，不可提前：其证据行即 ``qualification`` 条件。
    本期**不实现任何对外收费签约路径**；本表只承载开关与条件登记。
    """

    __tablename__ = "regional_sale_gate"
    __table_args__ = (
        CheckConstraint(
            f"status IN {REGIONAL_GATE_STATUSES!r}",
            name="ck_regional_sale_gate_status",
        ),
        # 每项条件登记的原子性：uri / hash / signed_at 三者同有同无
        CheckConstraint(
            "(filing_uri IS NULL) = (filing_hash IS NULL) AND "
            "(filing_uri IS NULL OR filing_signed_at IS NOT NULL) AND "
            "(disclosure_uri IS NULL) = (disclosure_hash IS NULL) AND "
            "(disclosure_uri IS NULL OR disclosure_signed_at IS NOT NULL) AND "
            "(cooling_off_uri IS NULL) = (cooling_off_hash IS NULL) AND "
            "(cooling_off_uri IS NULL OR cooling_off_signed_at IS NOT NULL) AND "
            "(qualification_uri IS NULL) = (qualification_hash IS NULL) AND "
            "(qualification_uri IS NULL OR qualification_signed_at IS NOT NULL)",
            name="ck_regional_sale_gate_condition_atomic",
        ),
        # **缺件不可开门**（结构性排除）：opened ⇒ 四项齐备 + 开启人/时刻非空
        CheckConstraint(
            "status <> 'opened' OR ("
            "filing_uri IS NOT NULL AND filing_hash IS NOT NULL AND filing_signed_at IS NOT NULL AND "
            "disclosure_uri IS NOT NULL AND disclosure_hash IS NOT NULL AND disclosure_signed_at IS NOT NULL AND "
            "cooling_off_uri IS NOT NULL AND cooling_off_hash IS NOT NULL AND cooling_off_signed_at IS NOT NULL AND "
            "qualification_uri IS NOT NULL AND qualification_hash IS NOT NULL AND qualification_signed_at IS NOT NULL AND "
            "opened_by_user_id IS NOT NULL AND opened_at IS NOT NULL)",
            name="ck_regional_sale_gate_opened_complete",
        ),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    status: Mapped[str] = mapped_column(
        String(10), nullable=False, default="closed", server_default="closed"
    )
    # ① 备案证据
    filing_uri: Mapped[str | None] = mapped_column(String(500))
    filing_hash: Mapped[str | None] = mapped_column(String(64))
    filing_signed_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    # ② 30 日前书面披露证据
    disclosure_uri: Mapped[str | None] = mapped_column(String(500))
    disclosure_hash: Mapped[str | None] = mapped_column(String(64))
    disclosure_signed_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    # ③ 冷静期条款证据
    cooling_off_uri: Mapped[str | None] = mapped_column(String(500))
    cooling_off_hash: Mapped[str | None] = mapped_column(String(64))
    cooling_off_signed_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    # ④ 两店一年主体资格证据（客观时间门槛）
    qualification_uri: Mapped[str | None] = mapped_column(String(500))
    qualification_hash: Mapped[str | None] = mapped_column(String(64))
    qualification_signed_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    # ── 开启留痕（关键流转）──
    opened_by_user_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="RESTRICT")
    )
    opened_at: Mapped[datetime | None] = mapped_column(UTCDateTime())


class RegionalServiceSettlement(Base, TimestampMixin):
    """城市服务伙伴按项目结算关联行（**一单一结**；不设固定年费的结构性证据）。

    **引用既有 G3 科目层** ``commercial_revenue_ledger`` 的 ``project_share`` 行
    （不建第二套结算引擎，ADR-003/ADR-005 同款纪律）；一个科目行至多被一个
    伙伴结算关联（UNIQUE 防重复计数）。正式区域合作商的年费走各自签约通道
    （本期开关关闭、无签约路径），**不得**写本表（服务层显式拒绝）。
    """

    __tablename__ = "regional_service_settlements"
    __table_args__ = (
        UniqueConstraint("ledger_entry_id", name="uq_regional_service_settlements_ledger"),
        Index("ix_regional_service_settlements_partner", "partner_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    partner_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("regional_partners.id", ondelete="RESTRICT"), nullable=False
    )
    project_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False
    )
    ledger_entry_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("commercial_revenue_ledger.id", ondelete="RESTRICT"), nullable=False
    )
    settled_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), nullable=False, server_default=UTC_TIMESTAMP_SQL
    )
    note: Mapped[str | None] = mapped_column(String(500))

# ══════════════════════════════════════════════════════════════════════════
# 商业化 G6：企业空间与企业自助交付（任务书 §10；ADR-010）
# ══════════════════════════════════════════════════════════════════════════

# 三档分流/付费选项的合法键集——**唯一权威＝G2 的 ``DIAGNOSIS_PROJECT_TIERS`` 键集**
# （三档定性描述单一权威，不另立枚举；系统不做任何硬规则判定，零阈值常量——
# 选项/档位载荷无数值由哨兵用例钉住）。
ENTERPRISE_TRIAGE_TIERS = tuple(DIAGNOSIS_PROJECT_TIERS)

# 「同一主体两种状态」（自助态／付费交付态）的派生读面值域：
# paid_delivery ＝ 存在未被取代的付费选项选择行（派生值，**不是账**——科目层零触碰，
# 不另立第三套计费口径，ADR-010 §1.4）。
ENGAGEMENT_STATES = ("self_service", "paid_delivery")

# 四类注册入口（R1–R4 一一对应，齐备性由测试机器闸钉住：键集＝COMMERCIAL_ROLES）：
# R1 企业自助注册＝本轮新增（当事人自证）；R2/R3＝G2 体验入口注册表；
# R4＝G5 区域合作商申请（当事人自证）。
REGISTRATION_ENTRIES: dict[str, dict[str, str]] = {
    "R1": {
        "label": "企业自助注册",
        "path": "POST /api/v1/commercial/enterprise-registrations",
        "source": "g6_self_service",
    },
    "R2": {
        "label": "创业者模拟体验",
        "path": "trial_entry:founder",
        "source": "g2_trial_registry",
    },
    "R3": {
        "label": "交付者脱敏模拟项目考核",
        "path": "trial_entry:deliverer",
        "source": "g2_trial_registry",
    },
    "R4": {
        "label": "区域合作商申请（城市观察）",
        "path": "POST /api/v1/commercial/regional-partners",
        "source": "g5_self_attested",
    },
}


class EnterpriseTriageDecision(Base, TimestampMixin):
    """三档分流**人工判定**留痕行（交付咨询环节；任务书 §10 验收②）。

    判据＝**定性描述**（``rationale`` 必填，判定人手写的依据）；系统不做任何
    硬规则计算（本域零阈值常量，判定＝人的输入不是计算输出）；``tier`` 值域
    复用 G2 三档闭集（单一权威）。可回看＝企业空间读面按主体列出（谁在何时
    判了哪一档、依据是什么）。书面依据可选，落指针＋sha256 指纹（同有同无
    CHECK；原件永不入库，证据红线同款）。
    """

    __tablename__ = "enterprise_triage_decisions"
    __table_args__ = (
        CheckConstraint(
            f"tier IN {ENTERPRISE_TRIAGE_TIERS!r}",
            name="ck_enterprise_triage_decisions_tier",
        ),
        CheckConstraint(
            "(basis_uri IS NULL) = (basis_sha256 IS NULL)",
            name="ck_enterprise_triage_decisions_basis_atomic",
        ),
        Index("ix_enterprise_triage_decisions_subject", "subject_key"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    subject_key: Mapped[str] = mapped_column(
        String(18),
        ForeignKey("enterprise_quota_subjects.subject_key", ondelete="RESTRICT"),
        nullable=False,
    )
    tier: Mapped[str] = mapped_column(String(20), nullable=False)
    decided_by_user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    decided_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), nullable=False, server_default=UTC_TIMESTAMP_SQL
    )
    rationale: Mapped[str] = mapped_column(String(2000), nullable=False)
    basis_uri: Mapped[str | None] = mapped_column(String(500))
    basis_sha256: Mapped[str | None] = mapped_column(String(64))
    request_id: Mapped[str | None] = mapped_column(String(64))


class EnterprisePaidOptionChoice(Base, TimestampMixin):
    """付费选项选择行（诊断完成后系统呈现三个选项；**企业自主选择不被取消**）。

    - **append-only**：全仓无删除/取消路径（源码扫描钉）；企业换主意＝企业本人
      再选（新行写旧行 ``superseded_at`` 取代）；admin **不可代选、不可取消、
      不可改选**——选择动作只认绑定账号本人（服务层 403，ADR-010 §1.7）。
    - 平台侧唯一写面＝顾问跟进注记（admin+密码；只能补注记三元组，不能动
      ``option_key``/``chosen_*``——CHECK 联锁原子性）。
    - 一主体至多一份现行选择＝部分唯一索引（``superseded_at IS NULL``）；
      「付费交付态」＝存在现行选择行（派生读面，不是账，科目层零触碰）。
    """

    __tablename__ = "enterprise_paid_option_choices"
    __table_args__ = (
        CheckConstraint(
            f"option_key IN {ENTERPRISE_TRIAGE_TIERS!r}",
            name="ck_enterprise_paid_option_choices_option",
        ),
        CheckConstraint(
            "(advisor_note IS NULL) = (advisor_user_id IS NULL) "
            "AND (advisor_note IS NULL) = (advisor_at IS NULL)",
            name="ck_enterprise_paid_option_choices_advisor_atomic",
        ),
        Index(
            "uq_enterprise_paid_option_choices_active",
            "subject_key",
            unique=True,
            postgresql_where=text("superseded_at IS NULL"),
        ),
        Index("ix_enterprise_paid_option_choices_subject", "subject_key"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    subject_key: Mapped[str] = mapped_column(
        String(18),
        ForeignKey("enterprise_quota_subjects.subject_key", ondelete="RESTRICT"),
        nullable=False,
    )
    option_key: Mapped[str] = mapped_column(String(20), nullable=False)
    chosen_by_user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    chosen_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), nullable=False, server_default=UTC_TIMESTAMP_SQL
    )
    superseded_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    advisor_note: Mapped[str | None] = mapped_column(String(500))
    advisor_user_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="RESTRICT")
    )
    advisor_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
