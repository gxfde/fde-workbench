"""诊断域数据模型：``lead_diagnostic_sessions``（获客线索行）。

**与项目的隔离**（本域最关键的一条结构纪律）：

- **零外键指向 ``projects``**——线索 ≠ 项目，沿 transcripts 草稿区同款隔离手法
  （``test_diagnostics_mvp`` 用 metadata 扫描钉死「零外键指向 projects」）。
- **认领 = 显式转化动作**（T-11）：``claimed_by_user_id`` 只是指针，认领本身
  **不自动写交付真相层**；转正式交付时另走 presurvey 项目流程。
- ``source_type`` / ``channel_ref`` / ``claim_window_*`` 只落**结构**不落数
  （P-2：三档归因比例挂账到价格轮；比例属 G3 收入科目层，与四席位交付分成
  分层不混算）。

**匿名面**：``anonymous_token`` 的**明文不入库**——库里只有 sha256 指纹，
客户端持有明文；库泄漏不等于会话被接管（沿 share token 同款做法）。

**红线条码化**：本表存的是企业**自愿自填**的线索数据（有明示同意 + 隐私政策
+ 留存期），与交付真相层资料（扫描件/凭证）纪律不同；正文字段同样走脱敏管线。
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    text,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from fde_api.auth.models import UTCDateTime
from fde_api.workbench.models import Base, TimestampMixin, new_uuid

# 状态机：draft → submitted → report_ready → claimed | expired
# T-10a 落 draft/submitted；report_ready/claimed 由 T-10b/T-11 推进；
# expired 由 30 天留存期懒检查（QR-042）推进并匿名化清空内容字段。
SESSION_STATUSES = (
    "draft",
    "submitted",
    "report_ready",
    "claimed",
    "expired",
)

# 三档归因的**结构**（P-2）：direct=平台直达 / channel=内容与活动渠道 /
# partner=区域合作商专属链接。比例不落数。
SOURCE_TYPES = ("direct", "channel", "partner")

# 认领窗口（P-2：90 天认领窗口制，日期在 T-11 落）
CLAIM_WINDOW_DAYS = 90

# 线索留存期（个保法：留存期 + 删除请求通道）
SESSION_RETENTION_DAYS = 30

# ── T-11 认领闸 ────────────────────────────────────────────────────────

# 认领方身份**结构**（P-6：R2 创业者 / R4 区域合作商）——**不落数不落比例**。
# 「谁是 R2/R4」由**平台接受**环节人工核验（P-6：claimed ≠ accepted）；
# 本域只落「认领方自称的结构」＋平台裁定的结果。
CLAIMANT_KINDS = ("r2_entrepreneur", "r4_partner")

# 认领单状态机：pending → accepted | rejected（withdrawn = 认领方自撤）。
# **claimed ≠ accepted**（P-6）：pending 只是一份申请，未决时不改线索状态。
CLAIM_STATUSES = ("pending", "accepted", "rejected", "withdrawn")

# 三档归因（P-2：A 渠道报备 / B 认领转化 / C 平台留存）——**比例不落数**。
ATTRIBUTION_TIERS = ("A", "B", "C")

# 转化费口径（**结构**）：
#   none = 零转化费（C 档：平台留存 / 同主体自诊自认领）
#   ratio_applied = 按平台配置比例计（A/B 档）——比例数值只在配置面
#     （``Settings.diagnostics_fee_ratio_tier_a/b``，T-16 价格轮落数），
#     模型列零比例零金额字段。
# 历史：``pending_pricing``（比例待价格轮）随 T-16 价格轮落定**退役**——
#     主部署闸关期间零认领、轻部署库全新，零存量行，CHECK 同步换值
#     （迁移 f2a7c4e9b6d3）。
FEE_BASES = ("none", "ratio_applied")

# 同主体自诊自认领的**信号集**（P-6：同 IP / 联系方式 / 主体指纹）。
# 只记「哪个信号命中」，不记可比对的明文。
SELF_CLAIM_SIGNALS = ("ip", "contact", "subject")


class LeadDiagnosticSession(Base, TimestampMixin):
    """一次免注册诊断会话。

    一行 = 一次匿名诊断尝试。``answers`` 存问卷答案（代号化后），
    ``assessment`` 存首屏政策补贴测算卡（纯规则结果），``report`` 存 AI 报告
    （T-10b 落），``lead_contact`` 存留资信息（可空——摘要免注册可见）。
    """

    __tablename__ = "lead_diagnostic_sessions"
    __table_args__ = (
        CheckConstraint(
            "status IN ('draft', 'submitted', 'report_ready', 'claimed', 'expired')",
            name="ck_lead_diagnostic_sessions_status",
        ),
        CheckConstraint(
            "source_type IN ('direct', 'channel', 'partner')",
            name="ck_lead_diagnostic_sessions_source_type",
        ),
        CheckConstraint(
            "char_length(token_sha256) = 64",
            name="ck_lead_diagnostic_sessions_token_sha_len",
        ),
        CheckConstraint(
            "char_length(created_ip_hash) = 64",
            name="ck_lead_diagnostic_sessions_ip_hash_len",
        ),
        # 指纹唯一：同一个匿名令牌只对应一行（令牌碰撞或重放都归一行）
        Index("ux_lead_diagnostic_sessions_token", "token_sha256", unique=True),
        # 分享指纹：可空（未生成分享链接时无值），非空时唯一 + 64 位
        Index(
            "ux_lead_diagnostic_sessions_share_token",
            "share_token_sha256",
            unique=True,
        ),
        CheckConstraint(
            "share_token_sha256 IS NULL OR char_length(share_token_sha256) = 64",
            name="ck_lead_diagnostic_sessions_share_token_len",
        ),
        # 认领窗口的到期日必填（认领时限是机制的一部分，不能留空）
        CheckConstraint(
            "claim_window_expires_at IS NOT NULL",
            name="ck_lead_diagnostic_sessions_claim_window",
        ),
        # 认领档位闭集（T-11 落 P-2 三档；比例不落数）
        CheckConstraint(
            "attribution_tier IS NULL OR attribution_tier IN ('A', 'B', 'C')",
            name="ck_lead_diagnostic_sessions_attribution_tier",
        ),
        # 主体指纹必为 64 位（明文不入库，只有指纹）
        CheckConstraint(
            "subject_fingerprint IS NULL OR char_length(subject_fingerprint) = 64",
            name="ck_lead_diagnostic_sessions_subject_fingerprint_len",
        ),
        Index("ix_lead_diagnostic_sessions_status_created", "status", "created_at"),
        Index("ix_lead_diagnostic_sessions_source", "source_type", "channel_ref"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    # 匿名令牌**只存指纹**（明文在客户端；库泄漏不等于会话被接管）
    token_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft", server_default="draft")
    # 问卷答案（键为槽位键）；首屏 5 题与续填槽位分开存，便于「已答/未答」判定
    answers: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    # 首屏测算卡结果（纯规则；R-1：定性档位，无分数）
    assessment: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    # AI 报告（T-10b；三层 + 政策层；生成完成前恒为 NULL）
    report: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    # 报告生成请求时刻（异步：受理 ≠ 就绪；用于区分「未请求」与「生成中」）
    report_requested_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    # 分享令牌**只存指纹**（明文只在生成响应里返回一次）
    # ——分享页是**只读**面（无写权限），故令牌可入 URL；会话令牌是写权限凭证，
    # 只走请求头。两者权限域不同，指纹域也分开（不同域分隔前缀）。
    share_token_sha256: Mapped[str | None] = mapped_column(String(64))
    # 留资信息（可空——摘要免注册即时可见）
    lead_contact: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    # 三档归因结构（P-2：比例不落数）
    source_type: Mapped[str] = mapped_column(String(20), nullable=False, default="direct", server_default="direct")
    channel_ref: Mapped[str | None] = mapped_column(String(80))
    # 来源 IP 的**稳定假名**（sha256(ip + 密钥，域分隔）——不是明文 IP）
    created_ip_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    # 认领窗口到期（P-2：90 天）
    claim_window_expires_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    # 留存期到期（个保法：留存期 + 删除请求通道）
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    submitted_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    report_ready_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    claimed_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    # 认领人（指针；认领须平台接受——P-6：claimed ≠ accepted）
    claimed_by_user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    # 认领档位（P-2 三档：A 渠道报备 / B 认领转化 / C 平台留存；比例不落数）
    attribution_tier: Mapped[str | None] = mapped_column(String(20))
    # 主体指纹（T-11 自认领判定的**结构**之一）：sha256(规范化联系方式)，
    # 域分隔前缀。**明文不入库**——库里只有指纹。
    subject_fingerprint: Mapped[str | None] = mapped_column(String(64))
    # 线索所在区域（T-11：R4 仅可认领**本区域**线索）。
    # 可空＝线索未登记区域 ⇒ R4 认领 fail-closed（无法判定本区域即不许认领）。
    region_name: Mapped[str | None] = mapped_column(String(120))
    # 失败原因（异步生成失败时留痕；不吞错）
    failure_code: Mapped[str | None] = mapped_column(String(60))
    failure_message: Mapped[str | None] = mapped_column(Text)


class LeadDiagnosticClaim(Base, TimestampMixin):
    """一次认领动作（**申请 ≠ 生效**——P-6：认领须平台接受）。

    一行 = 一份认领申请。**四道闸**（服务层执行，机械钉见测试）：

    ① **认领窗口**：P-2 的 90 天窗口过期 ⇒ 拒（窗口是机制，不是提示）；
    ② **一线一线**：同线索已有未决认领 ⇒ 拒（未决认领锁住线索）；
    ③ **R4 仅本区域**：R4 认领方的区域 ≠ 线索区域 ⇒ 拒；线索**未登记区域**
       ⇒ **fail-closed 拒**（无法判定本区域即不许认领——不许"先认了再说"）；
    ④ **同主体自诊自认领** ⇒ **自动 C 档零转化费**（**不是拒**：自认领本身
       合法，只是没有转化费——拒了会把"自诊企业"的线索挤出池子）。

    **不建平行 CRM**（P-3）：本行不是流水线，只承载「认领闸 ＋ 台账行生成 ＋
    留痕」。**真相层仍是本地台账**（``D:\\test\\FDE\\leads.md`` 九字段）：
    ``ledger_row`` 是**待落账的台账行**（代号化九字段），落账由宿主侧脚本完成
    （脚本写文件，服务端**不碰真相层文件**），回执写回 ``ledger_written_at`` /
    ``ledger_hash``。

    **认领 ≠ 转交付**：接受认领只改线索行的指针与档位，**不建项目、不写交付
    真相层**——转正式交付另走 presurvey 流程（T-12 门面轮）。
    """

    __tablename__ = "lead_diagnostic_claims"
    __table_args__ = (
        CheckConstraint(
            f"claimant_kind IN {CLAIMANT_KINDS!r}",
            name="ck_lead_diagnostic_claims_claimant_kind",
        ),
        CheckConstraint(
            f"status IN {CLAIM_STATUSES!r}",
            name="ck_lead_diagnostic_claims_status",
        ),
        CheckConstraint(
            "attribution_tier IS NULL OR attribution_tier IN ('A', 'B', 'C')",
            name="ck_lead_diagnostic_claims_attribution_tier",
        ),
        CheckConstraint(
            f"fee_basis IS NULL OR fee_basis IN {FEE_BASES!r}",
            name="ck_lead_diagnostic_claims_fee_basis",
        ),
        # R4 认领**必须**带区域（R2 不需要——R2 是创业者，不按区域分）
        CheckConstraint(
            "claimant_kind <> 'r4_partner' OR region_name IS NOT NULL",
            name="ck_lead_diagnostic_claims_r4_region",
        ),
        # 未决申请不得带裁定字段（pending 就没有「生效」这回事）
        CheckConstraint(
            "status <> 'pending' OR (decided_at IS NULL AND attribution_tier IS NULL "
            "AND ledger_line_no IS NULL)",
            name="ck_lead_diagnostic_claims_pending_shape",
        ),
        # 裁定必留痕（接受/驳回都必须有裁定人 + 裁定时刻 + 理由）
        CheckConstraint(
            "status IN ('pending', 'withdrawn') OR (decided_at IS NOT NULL "
            "AND decided_by_user_id IS NOT NULL AND decision_note IS NOT NULL)",
            name="ck_lead_diagnostic_claims_decision_shape",
        ),
        # 接受 ⇒ 必须已落档（线索号 + 九字段行都在）；未接受 ⇒ 不得有台账号
        CheckConstraint(
            "status <> 'accepted' OR (ledger_line_no IS NOT NULL AND ledger_row IS NOT NULL)",
            name="ck_lead_diagnostic_claims_accepted_ledger",
        ),
        CheckConstraint(
            "status = 'accepted' OR ledger_line_no IS NULL",
            name="ck_lead_diagnostic_claims_ledger_only_when_accepted",
        ),
        CheckConstraint(
            "subject_fingerprint IS NULL OR char_length(subject_fingerprint) = 64",
            name="ck_lead_diagnostic_claims_subject_fingerprint_len",
        ),
        CheckConstraint(
            "claimed_ip_hash IS NULL OR char_length(claimed_ip_hash) = 64",
            name="ck_lead_diagnostic_claims_ip_hash_len",
        ),
        CheckConstraint(
            "ledger_hash IS NULL OR char_length(ledger_hash) = 64",
            name="ck_lead_diagnostic_claims_ledger_hash_len",
        ),
        # 一线一线：同一天同一序号只能有一条（认领时分配序号）
        UniqueConstraint(
            "ledger_date", "ledger_seq", name="uq_lead_diagnostic_claims_ledger_seq"
        ),
        # 线索号全局唯一（L-YYYYMMDD-NN）
        UniqueConstraint("ledger_line_no", name="uq_lead_diagnostic_claims_ledger_line_no"),
        Index("ix_lead_diagnostic_claims_session", "session_id"),
        Index("ix_lead_diagnostic_claims_claimant", "claimant_user_id"),
        Index("ix_lead_diagnostic_claims_status", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    # 被认领的线索（**不建外键指向 projects**——线索 ≠ 项目）
    session_id: Mapped[str] = mapped_column(
        ForeignKey("lead_diagnostic_sessions.id", ondelete="CASCADE"), nullable=False
    )
    # 认领方（指针；**不是**平台身份）
    claimant_user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    # 认领方身份结构（R2 创业者 / R4 区域合作商）
    claimant_kind: Mapped[str] = mapped_column(String(20), nullable=False)
    # 认领方所在区域（R4 必填；比对口径＝规范化后全等）
    region_name: Mapped[str | None] = mapped_column(String(120))
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="pending", server_default="pending"
    )
    # 三档归因（接受时落；比例只在配置面，模型列零比例零金额——T-16）
    attribution_tier: Mapped[str | None] = mapped_column(String(4))
    # 转化费口径（结构）：none=零转化费 / ratio_applied=按配置比例计（T-16）
    fee_basis: Mapped[str | None] = mapped_column(String(20))
    # 同主体自诊自认领判定结果（命中信号清单；**自动 C 档零转化费**）
    self_claim: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    self_claim_signals: Mapped[list[str] | None] = mapped_column(JSON)
    # 认领方声明所代表的联系方式指纹（**只存指纹**；与线索主体指纹同域前缀）
    subject_fingerprint: Mapped[str | None] = mapped_column(String(64))
    # 认领请求来源 IP 假名（同域前缀的 sha256；不是明文 IP）
    claimed_ip_hash: Mapped[str | None] = mapped_column(String(64))
    # 台账行（L-YYYYMMDD-NN + 九字段代号化内容）
    ledger_date: Mapped[str | None] = mapped_column(String(10))
    ledger_seq: Mapped[int | None] = mapped_column(Integer)
    ledger_line_no: Mapped[str | None] = mapped_column(String(20))
    ledger_row: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    # 落账回执（宿主侧脚本写完真相层台账后回写：时刻 + 行指纹）
    ledger_hash: Mapped[str | None] = mapped_column(String(64))
    ledger_written_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    # 裁定留痕（平台接受 / 驳回：谁、何时、为什么）
    decided_by_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    decided_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    decision_note: Mapped[str | None] = mapped_column(String(500))
    # 人工改档留痕（接受时改了自动算出的档位 ⇒ 必须带理由）
    tier_override: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    # 认领方留言（申请时的自述；**过脱敏管线**——企业名不入库）
    note: Mapped[str | None] = mapped_column(String(500))


class LeadDiagnosticChannelLink(Base, TimestampMixin):
    """R4 专属渠道链接（获客诊断 T-15：渠道链接 ID 体系）。

    一行 = 平台发给区域合作商的一条专属诊断链接。链接 token 是**归因凭证**：
    访客经该链接进入 ⇒ 服务端**机械地**落 ``source_type='partner'``（A 渠道
    报备档），零手工记账（P-2）。

    **纪律**（沿匿名写面同尺）：

    - token **只存 sha256 指纹**（明文只在创建响应里返回一次——admin 把它拼进
      专属链接后交付渠道方；库泄漏拿不到可用链接）；
    - ``channel_ref`` 归因写回线索行的是**链接行的 UUID**（``lead_diagnostic_sessions.channel_ref``
      是普通字符串列，不加外键——线索域与链接注册表松耦合，删链接不改历史归因）；
    - **零外键指向 ``projects``**（线索 ≠ 项目，域内自持）；``created_by`` 指向
      users 且 **SET NULL**（发链接的平台操作员离职不锁表）。

    停用（``is_active=False``）是**软撤**：历史归因不改写，新会话不再解析为
    partner（fail-closed 降档 direct——过期链接不拦访客，只不再给 A 档证据）。
    """

    __tablename__ = "lead_diagnostic_channel_links"
    __table_args__ = (
        CheckConstraint(
            "char_length(token_sha256) = 64",
            name="ck_lead_diagnostic_channel_links_token_sha_len",
        ),
        CheckConstraint(
            "is_active OR deactivated_at IS NOT NULL",
            name="ck_lead_diagnostic_channel_links_deactivate_shape",
        ),
        # 指纹唯一：同一条链接 token 只对应一行
        Index("ux_lead_diagnostic_channel_links_token", "token_sha256", unique=True),
        Index("ix_lead_diagnostic_channel_links_active", "is_active"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    # 链接 token **只存指纹**（明文只在创建响应里出现一次）
    token_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    # 渠道方区域（R4 的本区域；记录/对齐用——线索区域仍以访客自填为准）
    region_name: Mapped[str | None] = mapped_column(String(80))
    # 渠道方代号化备注（不写真实姓名/联系方式——台账纪律）
    note: Mapped[str | None] = mapped_column(String(200))
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true")
    )
    deactivated_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    created_by_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
