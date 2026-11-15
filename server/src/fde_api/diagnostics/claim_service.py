"""获客诊断 T-11：认领闸 ＋ 三档归因 ＋ 台账行生成。

**这一层要解决什么**：诊断会话里留了资的企业，谁来跟、归谁、算不算渠道带来的
——必须**机械可判**（不靠人自觉、不靠口头约定、不靠"事后翻台账对账"）。

**四道闸**（P-6 + P-2，机械执行，测试钉死）：

① **认领窗口**：90 天窗口过期 ⇒ 拒（窗口是机制不是提示）；
② **一线一线**：同线索已有未决认领 ⇒ 拒（未决申请锁住线索）；
③ **R4 仅本区域**：R4 认领方区域 ≠ 线索区域 ⇒ 拒；线索**未登记区域** ⇒
   **fail-closed 拒**（无法判定本区域即不许认领——不许"先认了再说"）；
④ **同主体自诊自认领** ⇒ **自动 C 档零转化费**（**不是拒**：自认领本身合法，
   只是没有转化费；拒了等于把"自诊企业"的线索挤出池子）。

**三档归因（P-2 ＋ T-16 价格轮）**——**比例只在配置面，模型列零比例零金额**：

| 档 | 含义 | 判定 | 转化费口径 |
|---|---|---|---|
| A | 渠道报备 | 线索来自区域合作商专属链接（``source_type='partner'``） | ``ratio_applied``（缺省 20%，见配置面） |
| B | 认领转化 | 有平台接受的认领且线索非渠道报备来 | ``ratio_applied``（缺省 10%，见配置面） |
| C | 平台留存 | 无有效认领，**或**同主体自诊自认领 | ``none`（零转化费） |

**不建平行 CRM**（P-3）：本模块不建流水线表，**真相层仍是本地台账**
（``D:\\test\\FDE\\leads.md`` 九字段 ＋ 9 态 ＋ 回访触发日）。本模块只做三件事：
判闸、算档、**生成台账行**（代号化九字段）——落账由**宿主侧脚本**写文件，
服务端**不碰真相层文件**（容器里没有真相层，也不该有）。

**红线**：企业自填的联系方式/姓名**不进台账行**（leads.md 口径：真实名与电话
留 FDEOps/OpenFDE）；台账行只落**代号化九字段**；本模块落库的联系方式**只存
指纹**（主体指纹），明文仍在诊断会话的留资行里（那是访客自愿自填、有同意
与留存期的数据，与交付真相层纪律不同）。
"""
from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from fde_api.diagnostics.models import (
    ATTRIBUTION_TIERS,
    CLAIMANT_KINDS,
    FEE_BASES,
    LeadDiagnosticClaim,
    LeadDiagnosticSession,
)
from fde_api.diagnostics.service import (
    MAX_REGION_CHARS,
    DiagnosticsServiceError,
    _enforce_retention as _enforce_retention_for_lead,
    _error,
    _redact_text,
    ensure_enabled,
    hash_ip,
    subject_fingerprint,
)
from fde_api.extensions import db

# 认领方声明所代表的联系方式长度上限
MAX_SUBJECT_KEY_CHARS = 200
# 认领留言长度上限
MAX_NOTE_CHARS = 500
# 痛点一句话截断长度（leads.md 是「一句话」栏位）
PAIN_SUMMARY_CHARS = 40
# 台账行「九字段」列序（leads.md §一 表头顺序）——落账脚本按同一序写
LEDGER_COLUMNS = (
    "线索号",
    "#",
    "来源",
    "行业",
    "联系人角色",
    "痛点一句话",
    "资格五问得分",
    "下一步动作+日期",
    "①状态",
    "②来源人/报备到期日",
    "③回访触发日",
    "④资料索引",
)

# 来源结构 → 台账「来源」列（leads.md 既有取值：自有/协会活动/渠道伙伴）
SOURCE_TO_LEDGER = {
    "direct": "自有",
    "channel": "协会活动",
    "partner": "渠道伙伴",
}

# 中国时区固定偏移（无夏令时）——台账线索号的日期按**本地日**落，
# 与 leads.md 的 ``L-<YYYYMMDD>-<NN>`` 口径一致（UTC 日界会把夜里的认领
# 记到前一天，与人工台账对不上）。
CN_UTC_OFFSET = timedelta(hours=8)


# ── 指纹与规范化 ───────────────────────────────────────────────────────


def _normalize(value: str) -> str:
    """区域/标识规范化：去空白 + 小写（比对口径，不改写落库原文）。"""
    return re.sub(r"\s+", "", value.strip().lower())


def _ledger_date(now: datetime | None = None) -> str:
    """台账日期（本地日，YYYY-MM-DD）。"""
    moment = (now or datetime.now(UTC)) + CN_UTC_OFFSET
    return moment.strftime("%Y-%m-%d")


def _ledger_line_no(ledger_date: str, seq: int) -> str:
    """线索号 = ``L-<YYYYMMDD>-<两位序号>``（leads.md §一 既有口径）。"""
    return f"L-{ledger_date.replace('-', '')}-{seq:02d}"


# ── 自认领信号 ─────────────────────────────────────────────────────────


def _self_claim_signals(
    *,
    lead: LeadDiagnosticSession,
    claimant_email: str | None,
    subject_key: str | None,
    request_ip_hash: str | None,
) -> list[str]:
    """同主体自诊自认领的**信号集**（P-6：同 IP / 联系方式 / 主体指纹）。

    只记「哪个信号命中」，不记可比对的明文。信号命中 ⇒ **自动 C 档零转化费**
    （降档，不拒单——自认领合法，只是无转化费）。
    """
    signals: list[str] = []
    if request_ip_hash and lead.created_ip_hash and request_ip_hash == lead.created_ip_hash:
        signals.append("ip")
    lead_fingerprint = lead.subject_fingerprint
    if lead_fingerprint and claimant_email:
        if subject_fingerprint(claimant_email) == lead_fingerprint:
            signals.append("contact")
    if lead_fingerprint and subject_key:
        if subject_fingerprint(subject_key) == lead_fingerprint:
            signals.append("subject")
    return signals


# ── 认领（申请） ───────────────────────────────────────────────────────


def create_claim(
    *,
    actor: Any,
    session_id: str,
    payload: dict[str, Any],
    ip_address: str | None,
) -> LeadDiagnosticClaim:
    """发起认领（**申请 ≠ 生效**）——闸①②③在此执行。"""
    ensure_enabled()
    claimant_kind = str(payload.get("claimant_kind") or "").strip()
    if claimant_kind not in CLAIMANT_KINDS:
        raise _error("invalid_claimant_kind", "认领方身份非法。", 400)
    region_raw = payload.get("region_name")
    region_name = str(region_raw).strip() if region_raw is not None else ""
    if len(region_name) > MAX_REGION_CHARS:
        raise _error("invalid_region", "区域名称过长。", 400)
    if claimant_kind == "r4_partner" and not region_name:
        raise _error("region_required", "区域合作商认领必须声明所在区域。", 400)
    subject_raw = payload.get("subject_key")
    subject_key = str(subject_raw).strip() if subject_raw is not None else ""
    if len(subject_key) > MAX_SUBJECT_KEY_CHARS:
        raise _error("invalid_subject_key", "声明的联系方式过长。", 400)
    note_raw = payload.get("note")
    note = str(note_raw).strip() if note_raw is not None else ""
    if len(note) > MAX_NOTE_CHARS:
        raise _error("note_too_long", "留言过长。", 400)
    note = _redact_text(note) if note else ""

    request_ip_hash = hash_ip(ip_address)
    now = datetime.now(UTC)

    with db.session() as session:
        lead = session.get(LeadDiagnosticSession, session_id)
        if lead is None:
            raise _error("lead_not_found", "线索不存在。", 404)
        # ①认领窗口与 30 天留存期：过期即拒并懒清空匿名内容（QR-042）
        if now >= lead.claim_window_expires_at:
            raise _error("claim_window_expired", "该线索已过认领窗口。", 409)
        if _enforce_retention_for_lead(session, lead, now=now):
            raise _error("lead_expired", "该线索已过期。", 409)
        if lead.status == "claimed":
            raise _error("lead_already_claimed", "该线索已被认领。", 409)
        if not lead.lead_contact:
            raise _error("lead_not_captured", "该线索尚未留资，不可认领。", 409)
        # ②一线一线：已有未决认领 ⇒ 拒（未决申请锁住线索）
        pending = session.scalar(
            select(LeadDiagnosticClaim.id).where(
                LeadDiagnosticClaim.session_id == lead.id,
                LeadDiagnosticClaim.status == "pending",
            )
        )
        if pending:
            raise _error("claim_in_flight", "该线索有一条待裁定的认领申请。", 409)
        # ③R4 仅本区域：线索无区域 ⇒ fail-closed 拒
        if claimant_kind == "r4_partner":
            lead_region = (lead.region_name or "").strip()
            if not lead_region:
                raise _error(
                    "lead_region_unknown",
                    "该线索未登记区域，无法判定本区域认领资格。",
                    409,
                )
            if _normalize(lead_region) != _normalize(region_name):
                raise _error("region_mismatch", "区域合作商仅可认领本区域线索。", 409)
        # ④自认领：降档信号（不拒单）
        signals = _self_claim_signals(
            lead=lead,
            claimant_email=getattr(actor, "email", None),
            subject_key=subject_key or None,
            request_ip_hash=request_ip_hash,
        )
        claim = LeadDiagnosticClaim(
            session_id=lead.id,
            claimant_user_id=actor.id,
            claimant_kind=claimant_kind,
            region_name=region_name or None,
            status="pending",
            self_claim=bool(signals),
            self_claim_signals=signals or None,
            subject_fingerprint=subject_fingerprint(subject_key) if subject_key else None,
            claimed_ip_hash=request_ip_hash,
            note=note or None,
        )
        session.add(claim)
        session.commit()
        return claim


# ── 裁定（平台接受 / 驳回） ────────────────────────────────────────────


def _auto_tier(lead: LeadDiagnosticSession, claim: LeadDiagnosticClaim) -> str:
    """自动档位：自认领 ⇒ C；渠道报备来 ⇒ A；其余有认领 ⇒ B。"""
    if claim.self_claim:
        return "C"
    if lead.source_type == "partner":
        return "A"
    return "B"


def _fee_basis(tier: str) -> str:
    """转化费口径（结构）：C 档零转化费；A/B 按平台配置比例计（T-16 落数）。

    比例数值只在配置面（``Settings.diagnostics_fee_ratio_tier_a/b``，env
    ``FDE_DIAGNOSTICS_FEE_RATIO_TIER_A/B`` 可调）——模型列零比例零金额字段
    （静态钉不变）；认领单投影也不携带比例数字（dispatch 域「报价/收款明细
    不出响应」同款纪律）。闭集取自 ``models.FEE_BASES``。
    """
    basis = "none" if tier == "C" else "ratio_applied"
    assert basis in FEE_BASES, basis
    return basis


def accept_claim(
    *,
    actor: Any,
    claim_id: str,
    payload: dict[str, Any],
) -> LeadDiagnosticClaim:
    """平台接受认领（**认领在此刻才生效**）——落档位、落台账行、推线索状态。"""
    ensure_enabled()
    decision_note = str(payload.get("decision_note") or "").strip()
    if not decision_note:
        raise _error("decision_note_required", "接受认领必须写明理由。", 400)
    if len(decision_note) > MAX_NOTE_CHARS:
        raise _error("decision_note_too_long", "理由过长。", 400)
    override_tier = payload.get("attribution_tier")
    override_reason = str(payload.get("override_reason") or "").strip()
    if override_tier is not None:
        override_tier = str(override_tier).strip()
        if override_tier not in ATTRIBUTION_TIERS:
            raise _error("invalid_attribution_tier", "归因档位非法。", 400)
        if not override_reason:
            raise _error("override_reason_required", "人工改档必须写明理由。", 400)

    now = datetime.now(UTC)
    for attempt in range(5):
        try:
            with db.session() as session:
                claim = session.get(LeadDiagnosticClaim, claim_id, with_for_update=True)
                if claim is None:
                    raise _error("claim_not_found", "认领申请不存在。", 404)
                if claim.status != "pending":
                    raise _error("claim_not_pending", "该认领申请已裁定。", 409)
                # 锁线索行 ⇒ 同线索的并发接受被串行化（一线一线）
                lead = session.get(
                    LeadDiagnosticSession, claim.session_id, with_for_update=True
                )
                if lead is None:
                    raise _error("lead_not_found", "线索不存在。", 404)
                if now >= lead.claim_window_expires_at:
                    raise _error("claim_window_expired", "该线索已过认领窗口。", 409)
                if _enforce_retention_for_lead(session, lead, now=now):
                    raise _error("lead_expired", "该线索已过期。", 409)
                accepted_other = session.scalar(
                    select(LeadDiagnosticClaim.id).where(
                        LeadDiagnosticClaim.session_id == lead.id,
                        LeadDiagnosticClaim.status == "accepted",
                        LeadDiagnosticClaim.id != claim.id,
                    )
                )
                if accepted_other:
                    raise _error("lead_already_claimed", "该线索已有生效认领。", 409)

                auto_tier = _auto_tier(lead, claim)
                tier = override_tier or auto_tier
                tier_override = bool(override_tier and override_tier != auto_tier)

                ledger_date = _ledger_date(now)
                seq = _next_ledger_seq(session, ledger_date)
                line_no = _ledger_line_no(ledger_date, seq)
                ledger_row = build_ledger_row(
                    lead=lead,
                    claim=claim,
                    ledger_line_no=line_no,
                    ledger_date=ledger_date,
                    now=now,
                )

                claim.status = "accepted"
                claim.attribution_tier = tier
                claim.fee_basis = _fee_basis(tier)
                claim.tier_override = tier_override
                claim.decided_by_user_id = actor.id
                claim.decided_at = now
                claim.decision_note = decision_note
                claim.ledger_date = ledger_date
                claim.ledger_seq = seq
                claim.ledger_line_no = line_no
                claim.ledger_row = ledger_row
                lead.status = "claimed"
                lead.claimed_at = now
                lead.claimed_by_user_id = actor.id
                lead.attribution_tier = tier
                session.commit()
                return claim
        except IntegrityError as error:
            # **只有**「同日序号被并发抢走」才重算；其它完整性错误**如实抛出**
            # ——上一版把 CHECK 违规也吞成"序号冲突"，真因被藏了 5 次。
            detail = str(getattr(error, "orig", error))
            if "uq_lead_diagnostic_claims_ledger" not in detail:
                raise
            if attempt >= 4:
                raise _error("ledger_seq_conflict", "台账序号冲突，请重试。", 409)
            continue
    raise _error("ledger_seq_conflict", "台账序号冲突，请重试。", 409)


def reject_claim(*, actor: Any, claim_id: str, payload: dict[str, Any]) -> LeadDiagnosticClaim:
    """平台驳回认领——**驳回不改线索状态**（线索仍可被他人认领）。"""
    ensure_enabled()
    decision_note = str(payload.get("decision_note") or "").strip()
    if not decision_note:
        raise _error("decision_note_required", "驳回认领必须写明理由。", 400)
    if len(decision_note) > MAX_NOTE_CHARS:
        raise _error("decision_note_too_long", "理由过长。", 400)
    now = datetime.now(UTC)
    with db.session() as session:
        claim = session.get(LeadDiagnosticClaim, claim_id, with_for_update=True)
        if claim is None:
            raise _error("claim_not_found", "认领申请不存在。", 404)
        if claim.status != "pending":
            raise _error("claim_not_pending", "该认领申请已裁定。", 409)
        claim.status = "rejected"
        claim.decided_by_user_id = actor.id
        claim.decided_at = now
        claim.decision_note = decision_note
        session.commit()
        return claim


def _next_ledger_seq(session: Any, ledger_date: str) -> int:
    """当日台账序号（从 1 起；跳过已用号——唯一约束兜底并发）。"""
    used = {
        row[0]
        for row in session.execute(
            select(LeadDiagnosticClaim.ledger_seq).where(
                LeadDiagnosticClaim.ledger_date == ledger_date
            )
        )
        if row[0] is not None
    }
    seq = 1
    while seq in used:
        seq += 1
    return seq


# ── 台账行生成（九字段、代号化） ───────────────────────────────────────


def _pain_summary(lead: LeadDiagnosticSession) -> str:
    """痛点一句话（代号化、截断）——取自由文本或现状描述，都没有则「待填」。"""
    answers = lead.answers or {}
    raw = answers.get("ctx.free_text") or answers.get("biz.current_process") or ""
    text = str(raw).strip()
    if not text:
        return "待填"
    text = re.sub(r"\s+", " ", text)
    if len(text) > PAIN_SUMMARY_CHARS:
        text = text[:PAIN_SUMMARY_CHARS] + "…"
    return text


def build_ledger_row(
    *,
    lead: LeadDiagnosticSession,
    claim: LeadDiagnosticClaim,
    ledger_line_no: str,
    ledger_date: str,
    now: datetime,
) -> dict[str, Any]:
    """生成台账行（leads.md §一 九字段 ＋ 线索号 ＋ 资料索引）。

    **只落已发生的事实与结构性字段**——工具不臆造：

    - **资格五问得分** ⇒ ``待填``（资格判定是人的动作，工具不代判）；
    - **下一步动作+日期** ⇒ ``认领跟进 <认领日>``（认领当日是事实）；
    - **③回访触发日** ⇒ ``认领窗口到期 → <窗口到期日>``（90 天窗口是 P-2 既有
      事实，不臆造业务 SLA）；
    - **联系方式 / 姓名 / 企业真实名** ⇒ **一律不出现在本行**（leads.md 口径：
      真实名与电话留 FDEOps/OpenFDE）。
    """
    answers = lead.answers or {}
    industry = str(answers.get("org.industry") or "").strip() or "待填"
    role = str(answers.get("biz.decision_maker") or "").strip() or "待填"
    source = SOURCE_TO_LEDGER.get(lead.source_type, "自有")
    if lead.source_type == "partner":
        partner_ref = (lead.channel_ref or "渠道伙伴").strip()
        report_expires = (lead.created_at or now) + timedelta(days=90)
        source_person = f"{partner_ref} / 报备至 {report_expires.strftime('%Y-%m-%d')}"
    else:
        source_person = "自有"
    window_date = lead.claim_window_expires_at.strftime("%Y-%m-%d")
    return {
        "线索号": ledger_line_no,
        "#": int(ledger_line_no.rsplit("-", 1)[1]),
        "来源": source,
        "行业": industry,
        "联系人角色": role,
        "痛点一句话": _pain_summary(lead),
        "资格五问得分": "待填",
        "下一步动作+日期": f"认领跟进 {ledger_date}",
        "①状态": "诊断中",
        "②来源人/报备到期日": source_person,
        "③回访触发日": f"认领窗口到期 → {window_date}",
        "④资料索引": f"诊断会话-{lead.id[:8]}",
    }


# ── 线索池（按区可见） ─────────────────────────────────────────────────


def list_leads(
    *,
    actor: Any,
    claimant_kind: str,
    region_name: str | None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """线索池列表（**代号化**：不含联系方式与姓名）。

    可见性（P-6）：R4 区域合作商**只看本区域**；R2 创业者看全部未认领线索；
    平台（admin）看全部。区域缺失的线索**只有平台看得见**（fail-closed）。
    """
    ensure_enabled()
    if claimant_kind not in CLAIMANT_KINDS:
        raise _error("invalid_claimant_kind", "认领方身份非法。", 400)
    is_platform = getattr(actor, "role", "") == "admin"
    region = (region_name or "").strip()
    if claimant_kind == "r4_partner" and not region and not is_platform:
        raise _error("region_required", "区域合作商认领必须声明所在区域。", 400)
    capped = max(1, min(int(limit or 50), 200))
    now = datetime.now(UTC)
    with db.session() as session:
        stmt = select(LeadDiagnosticSession).where(
            LeadDiagnosticSession.status.in_(("submitted", "report_ready")),
            LeadDiagnosticSession.claim_window_expires_at > now,
            LeadDiagnosticSession.expires_at > now,
            LeadDiagnosticSession.lead_contact.isnot(None),
        )
        if claimant_kind == "r4_partner" and not is_platform:
            stmt = stmt.where(
                LeadDiagnosticSession.region_name.isnot(None),
                LeadDiagnosticSession.region_name == region,
            )
        stmt = stmt.order_by(LeadDiagnosticSession.created_at.desc()).limit(capped)
        rows = list(session.scalars(stmt))
        return [serialize_lead(row) for row in rows]


def serialize_lead(row: LeadDiagnosticSession) -> dict[str, Any]:
    """线索池投影（**不含**联系方式/姓名/原文——池子里看不到私人信息）。"""
    answers = row.answers or {}
    return {
        "id": row.id,
        "status": row.status,
        "source_type": row.source_type,
        "channel_ref": row.channel_ref,
        "region_name": row.region_name,
        "industry": str(answers.get("org.industry") or "").strip() or None,
        "scale": str(answers.get("org.scale") or "").strip() or None,
        "pain_summary": _pain_summary(row),
        "report_ready": bool(row.report),
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "claim_window_expires_at": (
            row.claim_window_expires_at.isoformat() if row.claim_window_expires_at else None
        ),
        "attribution_tier": row.attribution_tier,
    }


def serialize_claim(row: LeadDiagnosticClaim) -> dict[str, Any]:
    """认领单投影（含台账行——台账行只含代号化九字段）。"""
    return {
        "id": row.id,
        "session_id": row.session_id,
        "claimant_user_id": row.claimant_user_id,
        "claimant_kind": row.claimant_kind,
        "region_name": row.region_name,
        "status": row.status,
        "attribution_tier": row.attribution_tier,
        "fee_basis": row.fee_basis,
        "self_claim": row.self_claim,
        "self_claim_signals": row.self_claim_signals or [],
        "tier_override": row.tier_override,
        "ledger_line_no": row.ledger_line_no,
        "ledger_row": row.ledger_row,
        "ledger_written_at": row.ledger_written_at.isoformat() if row.ledger_written_at else None,
        "decided_by_user_id": row.decided_by_user_id,
        "decided_at": row.decided_at.isoformat() if row.decided_at else None,
        "decision_note": row.decision_note,
        "note": row.note,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


# ── 认领单列表（平台裁定队列 ＋ 我的申请） ─────────────────────────────

CLAIM_STATUS_FILTERS = ("pending", "accepted", "rejected", "all")


def serialize_claim_entry(
    row: LeadDiagnosticClaim,
    lead: LeadDiagnosticSession | None,
    claimant: Any = None,
) -> dict[str, Any]:
    """裁定队列投影＝认领单 ＋ 线索摘要 ＋ 认领人账号名。

    认领人只落**账号名**（username 是账号体系字段，不是真实姓名）；线索摘要
    复用线索池投影（同样**不含**联系方式与姓名——代号化纪律）。
    """
    data = serialize_claim(row)
    data["claimant_username"] = getattr(claimant, "username", None) if claimant else None
    data["lead"] = serialize_lead(lead) if lead is not None else None
    return data


def list_claims(
    *,
    actor: Any,
    status: str = "all",
    limit: int = 50,
) -> list[dict[str, Any]]:
    """认领单列表（**两段可见性，同一路由**）：admin＝全量（裁定队列）；
    非 admin＝**只看自己的申请**（``claimant_user_id == actor.id``）。

    ``status`` 是闭集过滤器（pending/accepted/rejected/all，缺省 all）——
    桌面裁定面传 ``pending`` 拿待裁定队列；「我的申请」缺省拿全部状态。
    """
    ensure_enabled()
    key = (status or "all").strip()
    if key not in CLAIM_STATUS_FILTERS:
        raise _error("invalid_status", "状态过滤器非法。", 400)
    capped = max(1, min(int(limit or 50), 200))
    is_platform = getattr(actor, "role", "") == "admin"
    with db.session() as session:
        stmt = select(LeadDiagnosticClaim).order_by(LeadDiagnosticClaim.created_at.desc())
        if key != "all":
            stmt = stmt.where(LeadDiagnosticClaim.status == key)
        if not is_platform:
            stmt = stmt.where(LeadDiagnosticClaim.claimant_user_id == actor.id)
        rows = list(session.scalars(stmt.limit(capped)))
        lead_ids = {row.session_id for row in rows}
        user_ids = {row.claimant_user_id for row in rows if row.claimant_user_id}
        leads: dict[str, LeadDiagnosticSession] = {}
        if lead_ids:
            for lead in session.scalars(
                select(LeadDiagnosticSession).where(LeadDiagnosticSession.id.in_(lead_ids))
            ):
                leads[lead.id] = lead
        claimants: dict[str, Any] = {}
        if user_ids:
            # 跨域复用 auth 模型：函数内懒导入（包环冻结闸纪律）
            from fde_api.auth.models import User

            for user in session.scalars(select(User).where(User.id.in_(user_ids))):
                claimants[user.id] = user
        return [
            serialize_claim_entry(row, leads.get(row.session_id), claimants.get(row.claimant_user_id))
            for row in rows
        ]


def get_claim(*, actor: Any, claim_id: str) -> LeadDiagnosticClaim:
    """读认领单（admin 全量；非 admin 仅本人申请；不存在或越权一律 ⇒ 404）。"""
    ensure_enabled()
    is_platform = getattr(actor, "role", "") == "admin"
    with db.session() as session:
        row = session.get(LeadDiagnosticClaim, claim_id)
        if row is None:
            raise _error("claim_not_found", "认领申请不存在。", 404)
        if not is_platform and row.claimant_user_id != getattr(actor, "id", None):
            raise _error("claim_not_found", "认领申请不存在。", 404)
        return row


def reveal_claimed_lead_contact(*, actor: Any, claim_id: str) -> dict[str, Any]:
    """受控读取已接受认领线索的留资联系方式并留痕（QR-041，#1A）：

    仅平台 ``admin`` 或该 ``accepted`` 认领单的 ``claimant_user_id == actor.id`` 可读；
    每次读取写入 ``operation_events``（``diagnostic_lead_contact_revealed``，不落明文联系方式）。
    """
    ensure_enabled()
    is_platform = getattr(actor, "role", "") == "admin"
    with db.session() as session:
        claim = session.get(LeadDiagnosticClaim, claim_id)
        if claim is None:
            raise _error("claim_not_found", "认领申请不存在。", 404)
        if not is_platform and (
            claim.claimant_user_id != getattr(actor, "id", None)
            or claim.status != "accepted"
        ):
            raise _error("claim_not_found", "认领申请不存在。", 404)
        lead = session.get(LeadDiagnosticSession, claim.session_id)
        if lead is None or not lead.lead_contact:
            raise _error("lead_not_captured", "该线索无可用留资记录。", 404)
        from fde_api.workbench.models import OperationEvent

        session.add(
            OperationEvent(
                actor_user_id=actor.id,
                project_id=None,
                target_type="lead_diagnostic_claim",
                target_id=claim.id,
                event_type="diagnostic_lead_contact_revealed",
                occurred_at=datetime.now(UTC),
                changes={"session_id": lead.id, "claim_status": claim.status},
            )
        )
        session.commit()
        return {
            "claim_id": claim.id,
            "session_id": lead.id,
            "contact": lead.lead_contact.get("contact"),
            "name": lead.lead_contact.get("name"),
            "captured_at": lead.lead_contact.get("captured_at"),
        }


__all__ = [
    "CLAIM_STATUS_FILTERS",
    "DiagnosticsServiceError",
    "LEDGER_COLUMNS",
    "accept_claim",
    "build_ledger_row",
    "create_claim",
    "get_claim",
    "list_claims",
    "list_leads",
    "reject_claim",
    "reveal_claimed_lead_contact",
    "serialize_claim",
    "serialize_claim_entry",
    "serialize_lead",
    "subject_fingerprint",
]
