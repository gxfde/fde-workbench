"""fde_profiles 档案与等级晋级核验（设计 §3.2/§3.3，P0-3）。

§3.3 统一原则：等级不是自评，是基于已交付事实的核验。本模块把每级判据
落成可复算的查询（判定数据来源：gates + quotes + payments + 交付包席位），
核验通过才写 FdeLevelEvidence 证据链并更新 fde_profiles.level。

口径注记（冲突裁决「代码实测事实 > 设计文档」）：
§3.3「独立交付」定义写的是 delivery_settlements 席位，但该表四席位是商务
席位 platform/region/city/delivery（§7.2），不存在 seat_lead；seat_lead /
seat_delivery 是 delivery_packages 的执行席位（§2.4）。判定按 delivery_packages
执行席位实现（dispatch_status='accepted' 也在该表），语义与 §2.4 一致。

核验人分级的「双签 / 双人 / admin+技术合伙人」（§3.3 表）是运营流程约束，
本层只强制下限：核验人必须是平台侧（admin / project_lead）；升级为双人
留痕随 disputes/工作流轮次落地（留注 goal-r2）。
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import and_, exists, func, or_, select
from sqlalchemy.orm import Session

from fde_api.auth.models import ROLE_ADMIN, ROLE_PROJECT_LEAD, User
from fde_api.dispatch.errors import DispatchServiceError
from fde_api.dispatch.models import DeliveryPackage, FdeLevelEvidence, FdeProfile
from fde_api.meetings.models import ReviewMeetingMinutes
from fde_api.projects.events import record_event
from fde_api.workbench.models import Gate, Payment, Project, Quote

LEVELS = ("L1", "L2", "L3", "L4")

# §3.3 每级判据阈值（四域：业务认知/场景工程/AI 技术/交付保障，短板决定）
_LEVEL_REQUIREMENTS: dict[str, dict[str, int]] = {
    "L1": {"min": 1, "scenario": 1},
    "L2": {"min": 2, "scenario": 3},
    "L3": {"min": 3, "scenario": 4},
    "L4": {"min": 4, "scenario": 5, "biz": 4},
}

# 各级独立交付单数下限（§3.3 ①）
_DELIVERY_COUNTS = {"L1": 1, "L2": 3, "L3": 8, "L4": 15}

_VERIFIER_ROLES = {ROLE_ADMIN, ROLE_PROJECT_LEAD}


def independent_delivery_rows(
    session: Session, user_id: str
) -> list[DeliveryPackage]:
    """「独立交付」操作定义（§3.3）：本人占执行席位 seat_lead 或 seat_delivery、
    该单 dispatch_status='accepted'、该项目 G8 Gate.status='passed'。"""
    g8_passed = exists(
        select(Gate.id).where(
            Gate.project_id == DeliveryPackage.project_id,
            Gate.gate_key == "G8",
            Gate.status == "passed",
        )
    )
    return list(
        session.scalars(
            select(DeliveryPackage).where(
                or_(
                    DeliveryPackage.seat_lead == user_id,
                    DeliveryPackage.seat_delivery == user_id,
                ),
                DeliveryPackage.dispatch_status == "accepted",
                g8_passed,
            )
        )
    )


def _count_b_layer_orders(session: Session, packages: list[DeliveryPackage]) -> int:
    """L3 ②：独立交付中 Quote.branch='B' 且 b_layer_score ≥ 7 的单数。"""
    project_ids = [p.project_id for p in packages]
    if not project_ids:
        return 0
    rows = session.execute(
        select(Quote.project_id, func.max(Quote.b_layer_score))
        .where(
            Quote.project_id.in_(project_ids),
            Quote.branch == "B",
            Quote.b_layer_score >= 7,
        )
        .group_by(Quote.project_id)
    ).all()
    return len(rows)


def _count_c_full_receipt_orders(
    session: Session, packages: list[DeliveryPackage]
) -> int:
    """L4 ②：sow_type='c' 且 Payment 全额实收（Σ实收 ≥ Σ计划，且确有计划行）。"""
    c_projects = {p.project_id for p in packages if p.sow_type == "c"}
    if not c_projects:
        return 0
    rows = session.execute(
        select(
            Payment.project_id,
            func.coalesce(func.sum(Payment.received_amount), 0),
            func.sum(Payment.amount),
        )
        .where(Payment.project_id.in_(c_projects))
        .group_by(Payment.project_id)
    ).all()
    return sum(1 for _, received, planned in rows if received >= planned and planned > 0)


def _repurchase_ok(session: Session, packages: list[DeliveryPackage]) -> bool:
    """「客户复购」操作定义（§3.3）：同一 enterprise_code 下 ≥2 个项目，各自
    至少一条 Quote.status='finalized' 且 field_claims['final_amount'] 为
    measured/accepted（四值法 §5.3）。只统计本人交付过的企业。"""
    enterprise_codes = {
        row[0]
        for row in session.execute(
            select(Project.enterprise_code).where(
                Project.id.in_({p.project_id for p in packages} or {"-"})
            )
        )
    }
    if not enterprise_codes:
        return False
    finalized = (
        Quote.status == "finalized",
        Quote.field_claims["final_amount"].as_string().in_(("measured", "accepted")),
    )
    rows = session.execute(
        select(Project.enterprise_code, func.count(func.distinct(Project.id)))
        .join(Quote, Quote.project_id == Project.id)
        .where(Project.enterprise_code.in_(enterprise_codes), and_(*finalized))
        .group_by(Project.enterprise_code)
    ).all()
    return any(count >= 2 for _, count in rows)


def _mentee_counts(session: Session, user_id: str) -> dict[str, int]:
    """带教记录 = fde_level_evidence.verified_by_user_id = 本人（§3.3/§6.5）。"""
    any_level = session.scalar(
        select(func.count())
        .select_from(FdeLevelEvidence)
        .where(
            FdeLevelEvidence.verified_by_user_id == user_id,
            FdeLevelEvidence.user_id != user_id,
        )
    )
    l1_l2 = session.scalar(
        select(func.count())
        .select_from(FdeLevelEvidence)
        .where(
            FdeLevelEvidence.verified_by_user_id == user_id,
            FdeLevelEvidence.user_id != user_id,
            FdeLevelEvidence.to_level.in_(("L1", "L2")),
        )
    )
    l3 = session.scalar(
        select(func.count())
        .select_from(FdeLevelEvidence)
        .where(
            FdeLevelEvidence.verified_by_user_id == user_id,
            FdeLevelEvidence.user_id != user_id,
            FdeLevelEvidence.to_level == "L3",
        )
    )
    return {"any": any_level or 0, "l1_l2": l1_l2 or 0, "l3": l3 or 0}


def evaluate_level_criteria(
    session: Session, *, user_id: str, to_level: str
) -> tuple[bool, list[str], dict[str, Any]]:
    """复算某级全部判据；返回（是否满足, 未满足项清单, 客观计数快照）。

    快照即 FdeLevelEvidence.evidence_summary 的内容来源（§3.3「判定数据
    来源」逐项可追溯），不满足时也返回快照供运营诊断。
    """
    if to_level not in LEVELS:
        raise DispatchServiceError("invalid_level", "to_level 必须是 L1/L2/L3/L4。")
    profile = session.get(FdeProfile, user_id)
    deficits: list[str] = []
    summary: dict[str, Any] = {}
    if profile is None:
        return False, ["fde_profile_missing"], {"to_level": to_level}

    packages = independent_delivery_rows(session, user_id)
    summary["independent_deliveries"] = len(packages)
    required = _DELIVERY_COUNTS[to_level]
    if len(packages) < required:
        deficits.append(f"independent_deliveries<{required}")

    if to_level == "L1":
        # ② 该单 Quote 状态 finalized
        finalized = 0
        for package in packages:
            if package.quote_id is None:
                continue
            status = session.scalar(select(Quote.status).where(Quote.id == package.quote_id))
            if status == "finalized":
                finalized += 1
        summary["finalized_quote_deliveries"] = finalized
        if finalized < 1:
            deficits.append("finalized_quote_deliveries<1")

    if to_level == "L2":
        repurchase = _repurchase_ok(session, packages)
        summary["repurchase_ok"] = repurchase
        if not repurchase:
            deficits.append("repurchase_missing")
        mentees = _mentee_counts(session, user_id)
        summary["mentees"] = mentees
        if mentees["any"] < 1:
            deficits.append("mentees<1")

    if to_level == "L3":
        b_orders = _count_b_layer_orders(session, packages)
        summary["b_layer_deliveries"] = b_orders
        if b_orders < 2:
            deficits.append("b_layer_deliveries<2")
        mentees = _mentee_counts(session, user_id)
        summary["mentees"] = mentees
        if mentees["l1_l2"] < 2:
            deficits.append("mentees_l1_l2<2")

    if to_level == "L4":
        c_orders = _count_c_full_receipt_orders(session, packages)
        summary["c_full_receipt_deliveries"] = c_orders
        if c_orders < 3:
            deficits.append("c_full_receipt_deliveries<3")
        mentees = _mentee_counts(session, user_id)
        summary["mentees"] = mentees
        if mentees["l3"] < 3:
            deficits.append("mentees_l3<3")

    scores = {
        "biz_cognition": profile.biz_cognition_score,
        "scenario_eng": profile.scenario_eng_score,
        "ai_tech": profile.ai_tech_score,
        "delivery_assure": profile.delivery_assure_score,
    }
    summary["domain_scores"] = scores
    req = _LEVEL_REQUIREMENTS[to_level]
    if min(scores.values()) < req["min"]:
        deficits.append(f"domain_min<{req['min']}")
    if scores["scenario_eng"] < req["scenario"]:
        deficits.append(f"scenario_eng<{req['scenario']}")
    if "biz" in req and scores["biz_cognition"] < req["biz"]:
        deficits.append(f"biz_cognition<{req['biz']}")
    summary["to_level"] = to_level
    return (not deficits), deficits, summary


def promote_user(
    session: Session,
    *,
    actor: User,
    user_id: str,
    to_level: str,
    source_uri: str,
    source_sha256: str,
) -> FdeLevelEvidence:
    """核验晋级（§3.3 晋级路径）：判据全过 → 写证据链 + 更新档案 + 审计事件。

    依据单据只存 source_uri 指针 + sha256 指纹（红线：不存本体）。
    """
    if actor.role not in _VERIFIER_ROLES:
        raise DispatchServiceError(
            "verifier_role_required", "核验人必须是平台侧（admin / project_lead）。", 403
        )
    if not isinstance(source_uri, str) or not source_uri.strip():
        raise DispatchServiceError("invalid_request", "source_uri 必须是非空指针。")
    if (
        not isinstance(source_sha256, str)
        or len(source_sha256) != 64
        or not all(c in "0123456789abcdef" for c in source_sha256.lower())
    ):
        raise DispatchServiceError(
            "invalid_request", "source_sha256 必须是 64 位十六进制指纹。"
        )
    if to_level not in LEVELS:
        raise DispatchServiceError("invalid_level", "to_level 必须是 L1/L2/L3/L4。")

    # goal-d10 M10（PartyMode §8：评审会产出可作为 Stage A/B 闸门证据引用）：
    # 等级是 Stage A A1 门的数据源——证据链允许引用工作台评审会纪要，由服务端
    # 钉住真实性：纪要必须存在（模型层 sealed_sha256 NOT NULL + len=64 check
    # 钉死「行存在即已封存」），且指纹必须等于纪要封存摘要（引用不可伪造）。
    minutes_ref: ReviewMeetingMinutes | None = None
    if source_uri.startswith("workbench-minutes:"):
        meeting_id = source_uri[len("workbench-minutes:"):].strip()
        # 纪要按 meeting_id 定位（一会一纪要唯一约束；主键 id 是纪要行自身 id）。
        minutes_ref = (
            session.scalar(
                select(ReviewMeetingMinutes).where(
                    ReviewMeetingMinutes.meeting_id == meeting_id
                )
            )
            if meeting_id
            else None
        )
        if minutes_ref is None:
            raise DispatchServiceError(
                "minutes_not_found",
                "workbench-minutes 引用的评审会纪要不存在（或尚未封存）。",
                422,
            )
        if source_sha256.lower() != minutes_ref.sealed_sha256:
            raise DispatchServiceError(
                "minutes_fingerprint_mismatch",
                "source_sha256 必须等于所引纪要的 sealed_sha256（指纹一致性）。",
                422,
            )

    profile = session.get(FdeProfile, user_id)
    if profile is None:
        raise DispatchServiceError("profile_not_found", "该用户尚无供给池档案。", 404)
    if profile.level == to_level:
        raise DispatchServiceError(
            "level_unchanged", f"档案已是 {to_level}，无需重复核验。", 409
        )

    ok, deficits, summary = evaluate_level_criteria(session, user_id=user_id, to_level=to_level)
    if not ok:
        raise DispatchServiceError(
            "level_evidence_insufficient",
            f"{to_level} 晋级判据未满足：{'、'.join(deficits)}。",
            422,
        )

    now = datetime.now(timezone.utc)
    evidence = FdeLevelEvidence(
        user_id=user_id,
        from_level=profile.level,
        to_level=to_level,
        verified_by_user_id=actor.id,
        verified_at=now,
        evidence_summary=summary,
        source_uri=source_uri.strip(),
        source_sha256=source_sha256.lower(),
    )
    session.add(evidence)
    session.flush()
    profile.level = to_level
    profile.level_verified_at = now
    profile.level_evidence_id = evidence.id
    target_user = session.get(User, user_id)
    if target_user is None:
        # profile FK 保证用户存在；防御分支只为类型收窄
        raise DispatchServiceError("user_not_found", "用户不存在。", 404)
    record_event(
        session,
        actor,
        "fde_level_promoted",
        target_user,
        {
            "user_id": user_id,
            "from_level": evidence.from_level,
            "to_level": to_level,
            "evidence_id": evidence.id,
            "evidence_form": "workbench_minutes" if minutes_ref is not None else "external_document",
            "minutes_id": minutes_ref.meeting_id if minutes_ref is not None else None,
            "deficits": [],
        },
    )
    return evidence


def create_profile(
    session: Session, *, user_id: str, home_city: str | None = None
) -> FdeProfile:
    """注册入池（pending 不占名额，§3.5）；等级核验走 promote_user。"""
    existing = session.get(FdeProfile, user_id)
    if existing is not None:
        raise DispatchServiceError("profile_exists", "该用户已有供给池档案。", 409)
    profile = FdeProfile(user_id=user_id, home_city=home_city)
    session.add(profile)
    return profile
