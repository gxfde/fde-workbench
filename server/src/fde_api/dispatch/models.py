"""dispatch 模型：交付包派单态 + 派单 offer 留痕 + 供给池档案 + 规则版本 + 结算
（设计 §2/§3/§6/§7/§8.2）。

goal-r1（P0-6）落 delivery_packages / dispatch_offers 骨架；goal-r2（P0-3/P0-4/
P0-8）补 fde_profiles / fde_level_evidence / dispatch_rule_versions /
delivery_settlements。发布/快照冻结（§2.3）、匹配算法（§4）、offer 服务（§6）
随 P0-1/P1-1/P1-2 后续轮次进同一包（§8.6），不在本文件预埋半成品逻辑。

字段来源：设计 §2.2 映射表「新增」行 + §3.2 档案表 + §7.2 结算表 + §8.2 约束清单。
席位口径：delivery_packages 四席位是执行席位 seat_lead/delivery/consult/qa
（§2.4「包 × 角色」的合同事实），与 delivery_settlements 的商务四席位
platform/region/city/delivery（§7.2）不同名不同义，落库不得混用。
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    JSON,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from fde_api.auth.models import UTCDateTime
from fde_api.workbench.models import Base, TimestampMixin, VersionedMixin, new_uuid


class DeliveryPackage(Base, TimestampMixin):
    """交付包派单态（§2.1：方案正文留在 project_solutions，本表只存派单态）。"""

    __tablename__ = "delivery_packages"
    __table_args__ = (
        UniqueConstraint("package_code", name="uq_delivery_packages_package_code"),
        # §2.3 规则 3：版本对 = (project_id, dispatch_round)
        UniqueConstraint(
            "project_id", "dispatch_round", name="uq_delivery_packages_project_round"
        ),
        CheckConstraint(
            "dispatch_mode IN ('assign', 'claim')",
            name="ck_delivery_packages_dispatch_mode",
        ),
        CheckConstraint(
            "dispatch_status IN ('draft', 'published', 'offered', 'assigned', "
            "'accepted', 'rejected', 'expired', 'withdrawn')",
            name="ck_delivery_packages_dispatch_status",
        ),
        # §4.7 扩圈序列 25→50→100→全城；0 = 全城哨兵值（§8.2 注释即契约）
        CheckConstraint(
            "redispatch_radius_km IN (25, 50, 100, 0)",
            name="ck_delivery_packages_redispatch_radius",
        ),
        CheckConstraint(
            "sow_type IS NULL OR sow_type IN ('a', 'b', 'c', 'd')",
            name="ck_delivery_packages_sow_type",
        ),
        CheckConstraint(
            "required_level IS NULL OR required_level IN ('L1', 'L2', 'L3', 'L4')",
            name="ck_delivery_packages_required_level",
        ),
        CheckConstraint(
            "difficulty IS NULL OR difficulty IN ('low', 'medium', 'high')",
            name="ck_delivery_packages_difficulty",
        ),
        # §6.4 开闸统计口径按 published 包数计数，状态列单查
        Index("ix_delivery_packages_status", "dispatch_status"),
    )

    # §2.2：package_id 直接引用 ProjectSolution.id（不另造 uuid），solution_id 再挂 FK
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    solution_id: Mapped[str] = mapped_column(
        ForeignKey("project_solutions.id", ondelete="RESTRICT"), nullable=False
    )
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False
    )
    # 展示码（§9.2 交付包字段白名单第 1 项）；生成规则随发布服务（P0-1）落位
    package_code: Mapped[str] = mapped_column(String(20), nullable=False)
    quote_id: Mapped[str | None] = mapped_column(ForeignKey("quotes.id", ondelete="RESTRICT"))
    sow_type: Mapped[str | None] = mapped_column(String(1))
    # §2.3：发布时计算一次即冻结；撤回→改→重发才是新哈希 + dispatch_round 递增
    snapshot_hash: Mapped[str | None] = mapped_column(String(64))
    dispatch_mode: Mapped[str] = mapped_column(
        String(10), nullable=False, default="assign", server_default="assign"
    )
    dispatch_status: Mapped[str] = mapped_column(
        String(12), nullable=False, default="draft", server_default="draft"
    )
    dispatch_round: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )
    allow_competitive_claim: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    # §6.2 时间常数唯一权威表：响应窗默认 24h（可按包覆盖）
    response_window_hours: Mapped[int] = mapped_column(
        Integer, nullable=False, default=24, server_default="24"
    )
    redispatch_radius_km: Mapped[int] = mapped_column(
        Integer, nullable=False, default=25, server_default="25"
    )
    # §4.5：由 Quote 系数推导（tier 基档 + 任一因子触发最多上调一级），人工覆盖须留痕
    required_level: Mapped[str | None] = mapped_column(String(2))
    required_modules: Mapped[list[Any] | None] = mapped_column(JSON)
    required_industry: Mapped[str | None] = mapped_column(String(64))
    # §4.6：onsite_required 从 ProjectSolution.schedule 派生后落库
    onsite_required: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    onsite_visits: Mapped[int | None] = mapped_column(Integer)
    # §9.2 显示义务：交付方席位 40% 对应金额——发布时按当时报价快照物化冻结
    # （交付包 API 禁 join quotes，§9.2 纪律①，金额只能来自本列；goal-r3 留注⑥）
    delivery_seat_amount: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    published_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    published_by_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    accepted_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    accepted_user_id: Mapped[str |None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    # 四席位 = 执行席位（§2.4 理由一：席位是「包 × 角色」的合同事实，不挂项目）
    seat_lead: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    seat_delivery: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    seat_consult: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    seat_qa: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    # D2 裁决三（PRD §6.3）：接单人显式声明「智能体协同」——声明后才启用
    # T1–T6 评审强制门与溯源联动；不声明 = 纯人工交付（v0.2.0 行为）。
    # 不是状态机的态：声明只落本列 + OperationEvent 留痕，TRANSITIONS 零改动。
    agent_assisted: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    # O-4 订单难度三档（PRD §6.4）：发布时平台侧定档冻结；start_run 按
    # low→standard / medium→high 映射自动带入 run.difficulty（T4 免手报）；
    # high=不派发给智能体（协同声明前置禁入）。
    difficulty: Mapped[str | None] = mapped_column(String(8))


class DispatchOffer(Base, TimestampMixin, VersionedMixin):
    """派单/抢单全量留痕（§6；一包 × 一轮 × 一候选人一行）。

    乐观锁：接单/中签/确认走 VersionedMixin.version 比对，冲突 409
    stale_version（§6.3，沿用本仓 32 模型已泛化模式，禁分布式锁）。
    """

    __tablename__ = "dispatch_offers"
    __table_args__ = (
        UniqueConstraint(
            "package_id",
            "dispatch_round",
            "candidate_user_id",
            name="uq_dispatch_offers_package_round_candidate",
        ),
        CheckConstraint(
            "status IN ('offered', 'accepted', 'rejected', 'declined', "
            "'transferred', 'expired')",
            name="ck_dispatch_offers_status",
        ),
        Index("ix_dispatch_offers_candidate", "candidate_user_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    package_id: Mapped[str] = mapped_column(
        ForeignKey("delivery_packages.id", ondelete="RESTRICT"), nullable=False
    )
    dispatch_round: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )
    candidate_user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    status: Mapped[str] = mapped_column(
        String(12), nullable=False, default="offered", server_default="offered"
    )
    # §4.8 输出契约：Top3 + match_breakdown 结构化明细；rule_version 指向
    # 当时版权本（P0-8 判据：版本切换后旧 offer 仍指旧版权本）
    match_breakdown: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    # §6.2：评估窗/响应窗起算时刻（服务逻辑 P1-1 落位）
    offered_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    responded_at: Mapped[datetime | None] = mapped_column(UTCDateTime())


class PackageAccess(Base, TimestampMixin):
    """跨主体只读授权——「第三语义」（§9.1/§9.2，P0-2）。

    独立于 project_access（项目内协作）与 admin（平台全局）：只有被授权的
    交付方才能看到对应交付包。不复用 Project.members（语义不同，§1.2 边界二）。
    可撤销（revoked_at）；接单后按 §9.3 升级为正式项目成员（member）。
    """

    __tablename__ = "package_access"
    __table_args__ = (
        UniqueConstraint(
            "package_id", "user_id", "role", name="uq_package_access_package_user_role"
        ),
        CheckConstraint(
            "role IN ('lead', 'seller', 'delivery', 'audit')",
            name="ck_package_access_role",
        ),
        Index("ix_package_access_user", "user_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    package_id: Mapped[str] = mapped_column(
        ForeignKey("delivery_packages.id", ondelete="RESTRICT"), nullable=False
    )
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[str] = mapped_column(String(10), nullable=False)
    granted_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    granted_by_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    revoked_at: Mapped[datetime | None] = mapped_column(UTCDateTime())


class FdeProfile(Base, TimestampMixin):
    """供给池能力档案（§3.2：等级是标量，四大子能力域是四个独立评分轴）。

    一人一档案（PK=user_id）。等级核验走 fde_level_evidence 证据链（§3.3），
    四域分数只用于等级晋级的评定维度，不进 Stage B 排序（§3.2 合规理由）。
    """

    __tablename__ = "fde_profiles"
    __table_args__ = (
        CheckConstraint(
            "level IS NULL OR level IN ('L1', 'L2', 'L3', 'L4')",
            name="ck_fde_profiles_level",
        ),
        CheckConstraint(
            "biz_cognition_score BETWEEN 0 AND 5",
            name="ck_fde_profiles_biz_cognition",
        ),
        CheckConstraint(
            "scenario_eng_score BETWEEN 0 AND 5", name="ck_fde_profiles_scenario_eng"
        ),
        CheckConstraint("ai_tech_score BETWEEN 0 AND 5", name="ck_fde_profiles_ai_tech"),
        CheckConstraint(
            "delivery_assure_score BETWEEN 0 AND 5",
            name="ck_fde_profiles_delivery_assure",
        ),
        CheckConstraint(
            "status IN ('pending', 'active', 'suspended')",
            name="ck_fde_profiles_status",
        ),
    )

    # 一人一档案（§8.2：PK user_id）
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    # NULL = 未定级（注册 pending 期）；核验后按 §3.3 证据链定级
    level: Mapped[str | None] = mapped_column(String(4))
    level_verified_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    # 当前等级所依据的证据记录（§3.2）
    level_evidence_id: Mapped[str | None] = mapped_column(
        ForeignKey("fde_level_evidence.id", ondelete="SET NULL")
    )
    # 四大子能力域（§3.2：等级 = 四域「短板决定」映射，不做加权平均）
    biz_cognition_score: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    scenario_eng_score: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    ai_tech_score: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    delivery_assure_score: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    # 标签全部申报制（§5.2：非平台推断）；取值域 = IndustryTemplate.industry_name /
    # ModuleCatalog.module_key
    industry_tags: Mapped[list[Any] | None] = mapped_column(JSON)
    module_tags: Mapped[list[Any] | None] = mapped_column(JSON)
    service_cities: Mapped[list[Any] | None] = mapped_column(JSON)
    home_city: Mapped[str | None] = mapped_column(String(32))
    # 围栏是「加权」不是「门槛」（§3.5：不排除围栏外候选）
    geo_fence_km: Mapped[int] = mapped_column(
        Integer, nullable=False, default=25, server_default=text("25")
    )
    # 同时接单上限 = floor(monthly_capacity_hours ÷ max(avg_delivery_hours, 1))
    # 自动计算，不允许手工设置（§4.2 A4 / BP 规则五）
    monthly_capacity_hours: Mapped[int | None] = mapped_column(Integer)
    avg_delivery_hours: Mapped[int | None] = mapped_column(Integer)
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    # 供给池生命周期（§3.5）：pending（注册不占名额）→ active（参与匹配）→ suspended
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="pending", server_default="pending"
    )


class FdeLevelEvidence(Base, TimestampMixin):
    """等级判定证据链（§3.3：等级不是自评，是基于已交付事实的核验）。

    每条 = 一次晋级的客观依据快照 + 核验人。依据单据只存 source_uri 指针 +
    sha256 指纹（红线：不存本体）。带教记录 = verified_by_user_id（§6.5）。
    """

    __tablename__ = "fde_level_evidence"
    __table_args__ = (
        CheckConstraint(
            "from_level IS NULL OR from_level IN ('L1', 'L2', 'L3', 'L4')",
            name="ck_fde_level_evidence_from",
        ),
        CheckConstraint(
            "to_level IN ('L1', 'L2', 'L3', 'L4')",
            name="ck_fde_level_evidence_to",
        ),
        Index("ix_fde_level_evidence_verified_by", "verified_by_user_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    from_level: Mapped[str | None] = mapped_column(String(4))
    to_level: Mapped[str] = mapped_column(String(4), nullable=False)
    # 核验人（L1 平台运营 / L2 双签 / L3 双人 / L4 admin+技术合伙人——§3.3 表）
    verified_by_user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    verified_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    # 核验时刻的客观计数快照（§3.3 判定数据来源：gates/quotes/settlements 查询结果）
    evidence_summary: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    # 依据单据指针 + sha256（红线：不存本体）
    source_uri: Mapped[str] = mapped_column(String(500), nullable=False)
    source_sha256: Mapped[str] = mapped_column(String(64), nullable=False)


class DispatchRuleVersion(Base, TimestampMixin):
    """权重与规则版本快照（§4.3/§6.2/规则表 B9）。

    权重唯一来源是版本表——Stage B 权重、等级映射分、席位份额全部进
    rule_snapshot JSON，不硬编码；改规则 = 新版本 + 公示（§6.2：重大调整
    提前 ≥30 天），旧 offer 的 match_breakdown.rule_version 永指当时版本。
    """

    __tablename__ = "dispatch_rule_versions"
    __table_args__ = (
        UniqueConstraint("version_no", name="uq_dispatch_rule_versions_version_no"),
        CheckConstraint("version_no >= 1", name="ck_dispatch_rule_versions_no"),
        CheckConstraint(
            "status IN ('draft', 'published', 'active', 'retired')",
            name="ck_dispatch_rule_versions_status",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    version_no: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(
        String(12), nullable=False, default="draft", server_default="draft"
    )
    # 快照内容：stage_b_weights / level_score_map / seat_shares /
    # cold_start_overrides / top_n / tie_break 规则引用（§4.3/§6.2）
    rule_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    # 生效日 ≥ 公示日 + 30 天（§6.2 重大调整公示；服务层发布/生效校验强制）
    effective_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    retired_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    published_by_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )


class DeliverySettlement(Base, TimestampMixin):
    """席位级结算（§7.2：平台↔FDE 分账，与 Payment 客户↔平台收款绝不合并）。

    商务四席位 platform/region/city/delivery——与 delivery_packages 的执行
    四席位（lead/delivery/consult/qa）不同名不同义（§2.4 理由三）。
    状态机：draft → accrued → payable → paid，任一方争议 → disputed（§6.6）。
    """

    __tablename__ = "delivery_settlements"
    __table_args__ = (
        UniqueConstraint(
            "package_id", "settlement_key", name="uq_delivery_settlements_package_key"
        ),
        CheckConstraint(
            "status IN ('draft', 'accrued', 'payable', 'paid', 'disputed')",
            name="ck_delivery_settlements_status",
        ),
        Index("ix_delivery_settlements_delivery_user", "seat_delivery_user_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    package_id: Mapped[str] = mapped_column(
        ForeignKey("delivery_packages.id", ondelete="RESTRICT"), nullable=False
    )
    # 结算引用当时快照（§2.3 规则 2：争议仲裁看到的是「当时那一版」）
    snapshot_hash: Mapped[str | None] = mapped_column(String(64))
    # 对齐 Payment.milestone_key 溯源（G3/G4/G8/SOW-C M1/M2/M3/D）
    settlement_key: Mapped[str] = mapped_column(String(20), nullable=False)
    # 计提基数 = 该里程碑实收金额（§7.3：基数=实收回款，不从分成池二次扣工时）
    base_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    # 商务四席位（挂包不挂项目；金额份额 % 存 dispatch_rule_versions 快照）
    seat_platform_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    seat_region_agent_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    seat_city_partner_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    seat_delivery_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    platform_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    region_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    city_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    delivery_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    # 当期累计预扣税额（§7.4 累计预扣法）
    withholding_tax: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), nullable=False, default=0, server_default=text("0")
    )
    status: Mapped[str] = mapped_column(
        String(12), nullable=False, default="draft", server_default="draft"
    )
    # 冗余自 Payment.acceptance_passed_at（P0-4 新增列），accrued 起算时刻
    acceptance_passed_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    # 打款凭证指针（红线：不存本体）
    paid_proof_source_uri: Mapped[str | None] = mapped_column(String(500))
    paid_at: Mapped[datetime | None] = mapped_column(UTCDateTime())


class Dispute(Base, TimestampMixin):
    """争议单（§6.6 四层仲裁 + §7.5 T+30 对账草稿，§8.1 第 8 张表）。

    L0 机器对账（每次必跑，对账单只存 source_uri 指针）→ L1 平台运营
    （≤¥50,000，48h 人工答复 SLA）→ L2 双人复核（双签留痕二期，goal-r6 留注⑯）
    → L3 外部（二期）。**处罚类动作 100% 人工**（BP §7.3.3 表 3）——本表
    只有「人工打开/人工裁决」写入路径，自动侧只产 L0 草稿。
    """

    __tablename__ = "disputes"
    __table_args__ = (
        CheckConstraint(
            "layer IN ('L0', 'L1', 'L2', 'L3')", name="ck_disputes_layer"
        ),
        CheckConstraint(
            "status IN ('draft', 'open', 'reviewing', 'resolved', 'closed')",
            name="ck_disputes_status",
        ),
        Index("ix_disputes_package", "package_id"),
        Index("ix_disputes_status", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    package_id: Mapped[str] = mapped_column(
        ForeignKey("delivery_packages.id", ondelete="RESTRICT"), nullable=False
    )
    # 对齐 Payment.milestone_key / DeliverySettlement.settlement_key 溯源
    settlement_key: Mapped[str | None] = mapped_column(String(20))
    layer: Mapped[str] = mapped_column(String(2), nullable=False, default="L0")
    status: Mapped[str] = mapped_column(
        String(10), nullable=False, default="draft", server_default="draft"
    )
    amount: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    reason: Mapped[str] = mapped_column(Text, nullable=False, default="")
    resolution: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # L0 机器对账单指针（红线：只存指针 + 指纹，不存本体）
    l0_report_source_uri: Mapped[str | None] = mapped_column(String(500))
    # 争议锚定「当时那一版」快照（§2.3 规则 2）
    snapshot_hash: Mapped[str | None] = mapped_column(String(64))
    opened_by_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    handled_by_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    # §6.6：L1 人工答复 SLA 48h（§6.2 唯一权威表 appeal_sla_hours）
    sla_due_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    resolved_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
