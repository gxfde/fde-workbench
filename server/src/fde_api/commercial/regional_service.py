"""商业化 G5：区域合作商能力建设服务层（区域阶梯 + 售卖开关；ADR-005）。

- **售卖能力默认关闭**：``regional_sale_gate`` 迁移播种 closed；开启＝关键流转
  （admin 门＋密码确认双闸），且合规条件清单四项的签署证据（指针＋指纹＋
  签署时刻）必须先行登记齐备（CHECK 结构性排除缺件开门）。
- **对外收费签约的唯一闸门是 ``require_sale_gate_open``**：进入正式区域合作商
  （formal_partner，三档定价 T1/T2/T3）必须先过闸；闸关着 ⇒ 一切收费签约路径
  409 ``regional_sale_gate_closed``——这是「无任何代码路径可在开关未开启时对外
  收费签约」的结构性保证（试运营升级指标与首期金额本期不定数，不落数）。
- **前两阶段（城市观察／城市服务）不授予独家区域权**（CHECK 联锁＋服务层校验）；
  **区域代理（regional_agent）本期不启用**——闭集保留位置，服务层显式拒绝。
- **城市服务伙伴按项目结算（一单一结）**：``regional_service_settlements`` 引用
  既有 G3 科目层 ``project_share`` 行，不建第二套结算引擎。
- 留痕：逐动作 ``operation_events``（Actor/前后状态/来源/请求 ID，**密码不落事件**）。
- 真实身份材料零入库：只登伙伴代号与区域名；材料只存指针 + sha256 指纹。
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from fde_api.auth.models import ROLE_ADMIN, User
from fde_api.auth.passwords import verify_password
from fde_api.commercial.models import (
    REGIONAL_GATE_CONDITION_KEYS,
    REGIONAL_GATE_SINGLETON_ID,
    REGIONAL_PARTNER_STAGES,
    REGIONAL_PARTNER_STAGE_NOTES,
    REGIONAL_TIER_CODES,
    REGIONAL_TIER_SEED,
    RegionalPartner,
    RegionalPartnerTier,
    RegionalSaleGate,
    RegionalServiceSettlement,
)
from fde_api.commercial.service import CommercialServiceError
from fde_api.commercial.models import CommercialRevenueLedger
from fde_api.dispatch.models import DeliveryPackage
from fde_api.projects.events import record_event
from fde_api.workbench.models import Project


def _error(code: str, message: str, status: int = 400) -> CommercialServiceError:
    return CommercialServiceError(code, message, status)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _require_admin(actor: User) -> None:
    if actor.role != ROLE_ADMIN:
        raise _error("commercial_admin_required", "商业权益管理仅系统运维员可用。", 403)


def _confirm_password(session: Session, actor: User, password: object) -> None:
    """单次显式授权：admin 写原语须携带当前账号密码（高风险写默认人工确认）。"""
    if not isinstance(password, str) or not password:
        raise _error("invalid_request", "confirm_password 必填（高风险写人工确认）。")
    current = session.get(User, actor.id)
    if current is None or not verify_password(current.password_hash, password):
        raise _error("invalid_password", "当前账号密码不正确。", 403)


def _require_str(value: object, field: str, *, max_len: int) -> str:
    if not isinstance(value, str) or not value.strip():
        raise _error("invalid_request", f"{field} 必填。")
    value = value.strip()
    if len(value) > max_len:
        raise _error("invalid_request", f"{field} 长度不得超过 {max_len} 字符。")
    return value


def _validate_evidence(source_uri: object, content_hash: object) -> tuple[str, str]:
    """书面依据＝指针 + sha256 指纹（缺一即 400；原件永不入库）。"""
    uri = source_uri.strip() if isinstance(source_uri, str) else ""
    digest = content_hash.strip().lower() if isinstance(content_hash, str) else ""
    if not uri or len(uri) > 500:
        raise _error("invalid_request", "source_uri 必填（≤500 字符，书面依据指针）。")
    if len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
        raise _error("invalid_request", "content_hash 必填（sha256 十六进制 64 位）。")
    return uri, digest


# ══════════════════════════════════════════════════════════════════════════
# 售卖开关（regional_sale_gate；默认 closed）
# ══════════════════════════════════════════════════════════════════════════


def get_or_create_gate(session: Session) -> RegionalSaleGate:
    """开关单行（迁移播种 closed；缺行即补建，补建恒为 closed）。"""
    row = session.get(RegionalSaleGate, REGIONAL_GATE_SINGLETON_ID)
    if row is None:
        row = RegionalSaleGate(id=REGIONAL_GATE_SINGLETON_ID, status="closed")
        session.add(row)
        session.flush()
    return row


def serialize_gate(row: RegionalSaleGate) -> dict[str, Any]:
    """开关读面：状态 + 各条件登记态（只出指针，不回读证据内容）。"""
    conditions: dict[str, dict[str, Any]] = {}
    for key in REGIONAL_GATE_CONDITION_KEYS:
        uri = getattr(row, f"{key}_uri")
        signed_at = getattr(row, f"{key}_signed_at")
        conditions[key] = {
            "registered": uri is not None,
            "source_uri": uri,
            "signed_at": signed_at.isoformat() if signed_at is not None else None,
        }
    return {
        "status": row.status,
        "conditions": conditions,
        "opened_at": row.opened_at.isoformat() if row.opened_at is not None else None,
    }


def require_sale_gate_open(session: Session) -> RegionalSaleGate:
    """**对外收费签约的唯一闸门**（fail-closed；ADR-005 §2.2）。

    闸未开启 ⇒ 409 ``regional_sale_gate_closed``——不回落、不绕行、无默认值。
    所有可把伙伴推进正式档（或任何对外收费动作）的代码路径都必须先过本闸。
    """
    gate = get_or_create_gate(session)
    if gate.status != "opened":
        raise _error(
            "regional_sale_gate_closed",
            "区域售卖能力默认关闭：合规条件清单（备案／披露／冷静期／两店一年资格）"
            "四项签署证据登记齐备并经人工开启后方可对外收费签约（本期未开放）。",
            409,
        )
    return gate


def register_gate_condition(
    session: Session,
    *,
    actor: User,
    key: object,
    source_uri: object,
    content_hash: object,
    signed_at: object,
    confirm_password: object,
) -> dict[str, Any]:
    """登记一项合规条件的签署证据（admin+密码；**登记 ≠ 开启**）。"""
    _require_admin(actor)
    _confirm_password(session, actor, confirm_password)
    if key not in REGIONAL_GATE_CONDITION_KEYS:
        raise _error("invalid_request", f"合规条件 {key!r} 不在清单内（{len(REGIONAL_GATE_CONDITION_KEYS)} 项）。", 404)
    uri, digest = _validate_evidence(source_uri, content_hash)
    signed = signed_at if isinstance(signed_at, datetime) else None
    if signed is None:
        raise _error("invalid_request", "signed_at 必填（ISO 8601，签署时刻）。")
    gate = get_or_create_gate(session)
    if gate.status == "opened":
        raise _error(
            "gate_already_opened", "开关已开启，条件登记不可再变更。", 409
        )
    setattr(gate, f"{key}_uri", uri)
    setattr(gate, f"{key}_hash", digest)
    setattr(gate, f"{key}_signed_at", signed)
    session.flush()
    record_event(
        session,
        actor,
        "regional_sale_gate_condition_registered",
        actor,
        {
            "request_id": str(uuid4()),
            "condition": key,
            "source_uri": uri,
            "content_hash": digest,
        },
    )
    return {"gate": serialize_gate(gate), "changed": True}


def open_sale_gate(
    session: Session,
    *,
    actor: User,
    confirm_password: object,
) -> dict[str, Any]:
    """开启售卖开关（admin+密码；四项条件证据齐备才可——CHECK 结构性排除缺件）。"""
    _require_admin(actor)
    _confirm_password(session, actor, confirm_password)
    gate = get_or_create_gate(session)
    if gate.status == "opened":
        raise _error("gate_already_opened", "开关已处于开启态。", 409)
    missing = [
        key
        for key in REGIONAL_GATE_CONDITION_KEYS
        if getattr(gate, f"{key}_uri") is None
        or getattr(gate, f"{key}_hash") is None
        or getattr(gate, f"{key}_signed_at") is None
    ]
    if missing:
        raise _error(
            "gate_condition_missing",
            f"合规条件清单未登记齐备，缺：{'、'.join(missing)}。",
            409,
        )
    gate.status = "opened"
    gate.opened_by_user_id = actor.id
    gate.opened_at = _now()
    session.flush()
    record_event(
        session,
        actor,
        "regional_sale_gate_opened",
        actor,
        {"request_id": str(uuid4()), "status": "opened"},
    )
    return {"gate": serialize_gate(gate), "changed": True}


# ══════════════════════════════════════════════════════════════════════════
# 区域伙伴（四阶段；前两阶段无独家权；区域代理本期不启用）
# ══════════════════════════════════════════════════════════════════════════


def serialize_partner(row: RegionalPartner) -> dict[str, Any]:
    return {
        "id": row.id,
        "partner_code": row.partner_code,
        "region_name": row.region_name,
        "note": row.note,
        "stage": row.stage,
        "stage_note": REGIONAL_PARTNER_STAGE_NOTES.get(row.stage),
        "tier_code": row.tier_code,
        "exclusive_territory": row.exclusive_territory,
        "applied_at": row.applied_at.isoformat(),
        "stage_changed_at": (
            row.stage_changed_at.isoformat() if row.stage_changed_at is not None else None
        ),
    }


def serialize_tier(row: RegionalPartnerTier) -> dict[str, Any]:
    return {
        "tier_code": row.tier_code,
        "annual_fee_amount": str(row.annual_fee_amount),
        "included_seats": row.included_seats,
        "transfer_quota_seats": row.transfer_quota_seats,
        "basis_reference": row.basis_reference,
    }


def ensure_tier_catalog(session: Session) -> None:
    """档位目录惰性补建（结构数据缺失即按 ``REGIONAL_TIER_SEED`` 补齐）。

    迁移已播种三行；共享测试库逐测清行后由本原语按代码权威补建——
    **补建值与迁移种子同源**（REGIONAL_TIER_SEED 单一权威，不另写数字）。
    """
    existing = set(session.scalars(select(RegionalPartnerTier.tier_code)))
    for seed in REGIONAL_TIER_SEED:
        if seed["tier_code"] in existing:
            continue
        session.add(RegionalPartnerTier(**seed))
    session.flush()


def list_tiers(session: Session) -> list[RegionalPartnerTier]:
    ensure_tier_catalog(session)
    return list(
        session.scalars(select(RegionalPartnerTier).order_by(RegionalPartnerTier.tier_code))
    )


def apply_city_observer(
    session: Session,
    *,
    actor: User,
    partner_code: object,
    region_name: object,
    note: object = None,
) -> dict[str, Any]:
    """申请成为城市观察伙伴（免费；当事人自证，不走 admin 门）。"""
    code = _require_str(partner_code, "partner_code", max_len=80)
    region = _require_str(region_name, "region_name", max_len=120)
    clean_note = None
    if note is not None and isinstance(note, str) and note.strip():
        clean_note = note.strip()[:500]
    existing = session.scalars(
        select(RegionalPartner).where(RegionalPartner.partner_code == code)
    ).first()
    if existing is not None:
        raise _error("partner_already_exists", f"伙伴代号 {code} 已存在。", 409)
    row = RegionalPartner(
        partner_code=code,
        region_name=region,
        note=clean_note,
        stage="city_observer",
        applicant_user_id=actor.id,
    )
    session.add(row)
    session.flush()
    record_event(
        session,
        actor,
        "regional_partner_applied",
        actor,
        {
            "request_id": str(uuid4()),
            "partner_id": row.id,
            "partner_code": row.partner_code,
            "stage": row.stage,
        },
    )
    return {"partner": serialize_partner(row), "changed": True}


def _load_partner(session: Session, partner_id: object) -> RegionalPartner:
    if not isinstance(partner_id, str) or not partner_id:
        raise _error("invalid_request", "partner_id 必填。")
    row = session.get(RegionalPartner, partner_id)
    if row is None:
        raise _error("partner_not_found", "区域伙伴不存在。", 404)
    return row


def promote_partner(
    session: Session,
    *,
    actor: User,
    partner_id: object,
    to_stage: object,
    tier_code: object = None,
    exclusive_territory: object = False,
    source_uri: object = None,
    content_hash: object = None,
    confirm_password: object,
) -> dict[str, Any]:
    """阶段升级（admin+密码+书面依据；**formal_partner 必先过售卖闸**）。

    - ``city_observer → city_service``：书面依据（指针+指纹）齐备即可。
    - ``city_service → formal_partner``：**先过 ``require_sale_gate_open``**
      （闸关 ⇒ 409 ``regional_sale_gate_closed``），且必须选择 T1/T2/T3 档位。
    - 任何 → ``regional_agent``：409 ``regional_agent_not_enabled``（本期不启用）。
    - 独家区域权只在正式档可声明（前两阶段被 CHECK + 服务层双重封死）。
    """
    _require_admin(actor)
    _confirm_password(session, actor, confirm_password)
    row = _load_partner(session, partner_id)
    if to_stage not in REGIONAL_PARTNER_STAGES:
        raise _error("invalid_request", f"目标阶段 {to_stage!r} 不在阶段闭集内。", 400)
    if to_stage == "regional_agent":
        raise _error(
            "regional_agent_not_enabled",
            "区域代理本阶段不启用（暂不启用；省级方案待试点后另定）。",
            409,
        )
    if to_stage == row.stage:
        raise _error("invalid_transition", "伙伴已处于目标阶段。", 409)
    allowed_from = {
        "city_service": {"city_observer"},
        "formal_partner": {"city_observer", "city_service"},
    }
    if to_stage not in allowed_from or row.stage not in allowed_from[to_stage]:
        raise _error(
            "invalid_transition",
            f"阶段流转 {row.stage} → {to_stage} 不被允许（只能沿阶梯前进）。",
            409,
        )
    uri, digest = _validate_evidence(source_uri, content_hash)
    chosen_tier: str | None = None
    if to_stage == "formal_partner":
        # **收费签约闸**：闸关 ⇒ 一切正式档进入路径 409（结构性保证）
        require_sale_gate_open(session)
        ensure_tier_catalog(session)  # 目录是结构数据：缺失即按种子补齐
        if not isinstance(tier_code, str) or tier_code not in REGIONAL_TIER_CODES:
            raise _error(
                "invalid_request", "正式区域合作商必须选择档位（T1/T2/T3）。", 400
            )
        tier = session.get(RegionalPartnerTier, tier_code)
        if tier is None:
            raise _error("tier_not_found", f"档位 {tier_code} 不在目录中。", 404)
        chosen_tier = tier.tier_code
    want_exclusive = bool(exclusive_territory)
    if want_exclusive and to_stage != "formal_partner":
        raise _error(
            "exclusive_not_allowed",
            "前两阶段（城市观察／城市服务）不授予独家区域权。",
            409,
        )
    prev_stage = row.stage
    row.stage = to_stage
    row.stage_changed_by_user_id = actor.id
    row.stage_changed_at = _now()
    row.stage_evidence_uri = uri
    row.stage_evidence_hash = digest
    row.tier_code = chosen_tier
    row.exclusive_territory = want_exclusive
    session.flush()
    record_event(
        session,
        actor,
        "regional_partner_promoted",
        actor,
        {
            "request_id": str(uuid4()),
            "partner_id": row.id,
            "partner_code": row.partner_code,
            "from_stage": prev_stage,
            "to_stage": to_stage,
            "tier_code": row.tier_code,
            "exclusive_territory": row.exclusive_territory,
            "source_uri": uri,
        },
    )
    return {"partner": serialize_partner(row), "changed": True}


def record_service_settlement(
    session: Session,
    *,
    actor: User,
    partner_id: object,
    project_id: object,
    ledger_entry_id: object,
    note: object = None,
    confirm_password: object,
) -> dict[str, Any]:
    """城市服务伙伴按项目结算（一单一结；admin+密码）。

    - 只适用于 ``city_service`` 阶段（正式档走各自签约/年费通道，不写本表）。
    - **引用既有科目层**：``commercial_revenue_ledger`` 的 ``project_share`` 行，
      且科目行归属同一项目（不张冠李戴）；一个科目行至多关联一次（UNIQUE）。
    """
    _require_admin(actor)
    _confirm_password(session, actor, confirm_password)
    row = _load_partner(session, partner_id)
    if row.stage != "city_service":
        raise _error(
            "settlement_channel_mismatch",
            "按项目结算关联只适用于城市服务伙伴阶段（正式区域合作商走签约通道）。",
            409,
        )
    if not isinstance(project_id, str) or not project_id:
        raise _error("invalid_request", "project_id 必填。")
    if not isinstance(ledger_entry_id, str) or not ledger_entry_id:
        raise _error("invalid_request", "ledger_entry_id 必填（G3 科目行）。")
    project = session.get(Project, project_id)
    if project is None:
        raise _error("project_not_found", "项目不存在。", 404)
    entry = session.get(CommercialRevenueLedger, ledger_entry_id)
    if entry is None:
        raise _error("ledger_entry_not_found", "收入科目行不存在。", 404)
    if entry.subject_type != "project_share":
        raise _error(
            "ledger_subject_mismatch",
            "城市服务伙伴按项目结算必须引用 project_share 科目行。",
            409,
        )
    # 科目行的项目归属经交付包间接持有（G3 结构）：包缺失 ⇒ 无法证一单一结；包不符 ⇒ 张冠李戴
    entry_package = (
        session.get(DeliveryPackage, entry.delivery_package_id)
        if entry.delivery_package_id is not None
        else None
    )
    if entry_package is None or entry_package.project_id != project_id:
        raise _error(
            "ledger_project_mismatch", "科目行归属与结算项目不一致。", 409
        )
    duplicate = session.scalars(
        select(RegionalServiceSettlement).where(
            RegionalServiceSettlement.ledger_entry_id == ledger_entry_id
        )
    ).first()
    if duplicate is not None:
        raise _error("ledger_entry_already_settled", "该科目行已有关联结算。", 409)
    clean_note = None
    if note is not None and isinstance(note, str) and note.strip():
        clean_note = note.strip()[:500]
    settlement = RegionalServiceSettlement(
        partner_id=row.id,
        project_id=project_id,
        ledger_entry_id=ledger_entry_id,
        note=clean_note,
    )
    session.add(settlement)
    session.flush()
    record_event(
        session,
        actor,
        "regional_service_settlement_recorded",
        actor,
        {
            "request_id": str(uuid4()),
            "partner_id": row.id,
            "partner_code": row.partner_code,
            "project_id": project_id,
            "ledger_entry_id": ledger_entry_id,
        },
    )
    return {"settlement": _serialize_settlement(settlement), "changed": True}


def _serialize_settlement(row: RegionalServiceSettlement) -> dict[str, Any]:
    return {
        "id": row.id,
        "partner_id": row.partner_id,
        "project_id": row.project_id,
        "ledger_entry_id": row.ledger_entry_id,
        "settled_at": row.settled_at.isoformat(),
        "note": row.note,
    }


def get_partner(session: Session, *, actor: User, partner_id: object) -> dict[str, Any]:
    """伙伴详情（admin 全量；非 admin 只见本人申请的，他人 404 不透 existence）。"""
    row = _load_partner(session, partner_id)
    if actor.role != ROLE_ADMIN and row.applicant_user_id != actor.id:
        raise _error("partner_not_found", "区域伙伴不存在。", 404)
    return serialize_partner(row)


def list_partners(session: Session, *, actor: User) -> list[RegionalPartner]:
    """读面：admin 全量；非 admin 只见本人申请的伙伴。"""
    if actor.role == ROLE_ADMIN:
        return list(session.scalars(select(RegionalPartner).order_by(RegionalPartner.applied_at)))
    return list(
        session.scalars(
            select(RegionalPartner)
            .where(RegionalPartner.applicant_user_id == actor.id)
            .order_by(RegionalPartner.applied_at)
        )
    )
