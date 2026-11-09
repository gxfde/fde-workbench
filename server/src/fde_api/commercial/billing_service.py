"""商业化 G3 服务层（二）：订阅席位计费闸 + 扣费方式书面选定 + 认证挂模拟考核。

语义钉（任务书 §7；ADR-003 §2.1–§2.5 / ADR-008）：

- **首单扣费闸**（任务书 §7）：交付者首个付费项目**交付完成并验收后**才触发
  扣除 3980；**验收前不触发**（服务层强校验，非仅靠人工纪律）。
- **扣费方式须事先书面选定**（任务书 §7）：本模块的 ``elect_deduction_method``
  是**当事人自证动作**（ADR-007 §2.4 自我动作例外）——交付者本人选定自己的
  扣费方式，**他人/admin 不得代选定**；书面证据只存指针 + sha256 指纹。
  **未选定 ⇒ 扣费闸 409**（任务书 §7 验收：「未选定方案时不得扣费」）。
- **席位不重复收**（任务书 §7）：已购含席位套餐（实战营/陪跑营）者不再重复收
  首年席位费；判定走两条独立路径——权益行的席位来源 + 科目层已入账的套餐席位费。
- **未接单候选人不产生年度欠费**：扣费只挂在「已接单且已验收」的交付项目上，
  且本期唯一可选定方式是方案 A（一次性扣除）——无年度周期欠费口径。
- **认证挂模拟考核**（任务书 §7）：认证状态由模拟考核结果驱动；**通过线本期
  不设** ⇒ 未配置通过线时记录停在 ``pending_threshold``，**不判定通过**。
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from fde_api.auth.models import ROLE_ADMIN, User
from fde_api.auth.passwords import verify_password
from fde_api.commercial.ledger_service import insert_revenue_entry
from fde_api.commercial.models import (
    DEDUCTION_METHODS,
    DEDUCTION_METHODS_IMPLEMENTED,
    FIRST_ORDER_SEAT_FEE,
    REVENUE_PACKAGES,
    CommercialCertificationRecord,
    CommercialDeductionElection,
    CommercialEntitlement,
    CommercialRevenueLedger,
)
from fde_api.commercial.service import (
    CommercialServiceError,
    activate_seat,
    ensure_entitlement,
)
from fde_api.dispatch.models import DeliveryPackage, DeliverySettlement
from fde_api.projects.events import record_event
from fde_api.workbench.models import Payment

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def _error(code: str, message: str, status: int = 400) -> CommercialServiceError:
    return CommercialServiceError(code, message, status)


def _require_admin(actor: User) -> None:
    if actor.role != ROLE_ADMIN:
        raise _error("commercial_admin_required", "商业计费治理仅系统运维员可用。", 403)


def _confirm_password(session: Session, actor: User, password: object) -> None:
    if not isinstance(password, str) or not password:
        raise _error("invalid_request", "confirm_password 必填（高风险写人工确认）。")
    current = session.get(User, actor.id)
    if current is None or not verify_password(current.password_hash, password):
        raise _error("invalid_password", "当前账号密码不正确。", 403)


def _require_sha256(value: object, field: str) -> str:
    if not isinstance(value, str) or not _SHA256_RE.match(value.strip().lower()):
        raise _error("invalid_request", f"{field} 必须是 64 位 sha256 十六进制指纹。")
    return value.strip().lower()


def _require_uri(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > 500:
        raise _error("invalid_request", f"{field} 必须是 ≤500 字符指针字符串。")
    return value.strip()


def _require_user(session: Session, user_id: object) -> User:
    if not isinstance(user_id, str) or not user_id:
        raise _error("invalid_request", "user_id 必填。")
    user = session.get(User, user_id)
    if user is None:
        raise _error("user_not_found", "用户不存在。", 404)
    return user


def _add_one_year(moment: datetime) -> datetime:
    """年度席位到期 = 激活时刻 + 一年（2/29 落到 2/28）。"""
    try:
        return moment.replace(year=moment.year + 1)
    except ValueError:  # 2/29 → 非闰年
        return moment.replace(year=moment.year + 1, day=28)


# ══════════════════════════════════════════════════════════════════════════
# 套餐目录（**不含价目**：价格走 quotes/payments 收款台账）
# ══════════════════════════════════════════════════════════════════════════


def list_packages() -> list[dict[str, Any]]:
    """套餐目录读面——「套餐含席位不重复收」的结构依据。"""
    return [
        {
            "code": code,
            "label": item["label"],
            "seat_source": item["seat_source"],
            "covers_first_year_fee": item["covers_first_year_fee"],
        }
        for code, item in sorted(REVENUE_PACKAGES.items())
    ]


# ══════════════════════════════════════════════════════════════════════════
# 扣费方式书面选定（当事人自证动作）
# ══════════════════════════════════════════════════════════════════════════


def get_active_election(session: Session, user_id: str) -> CommercialDeductionElection | None:
    return session.scalar(
        select(CommercialDeductionElection).where(
            CommercialDeductionElection.user_id == user_id,
            CommercialDeductionElection.status == "elected",
        )
    )


def elect_deduction_method(
    session: Session,
    *,
    actor: User,
    method: object,
    source_uri: object,
    content_hash: object,
) -> dict[str, Any]:
    """交付者**本人**书面选定扣费方式（自我动作例外，ADR-007 §2.4）。

    - 只能选自己的（路由层的 actor 即被计费人；本原语不接受 user_id 参数，
      **杜绝他人/admin 代选定**）；
    - 须附书面依据指针 + sha256 指纹（证据红线：原件不入库不入仓）；
    - 改选时旧行转 ``superseded``（历史保留，不改写）；
    - 方法 A（一次性扣除）为默认；方法 B（年度分期）本期**未实现**——允许
      登记（结构位），但扣费闸 fail-closed 拒绝（不误按 A 扣）。
    """
    if method not in DEDUCTION_METHODS:
        raise _error(
            "invalid_deduction_method",
            "method 必须是 one_time（方案A 一次性扣除）或 annual_installment 之一。",
        )
    uri = _require_uri(source_uri, "source_uri")
    digest = _require_sha256(content_hash, "content_hash")

    previous = get_active_election(session, actor.id)
    if previous is not None:
        previous.status = "superseded"
        session.flush()
    row = CommercialDeductionElection(
        user_id=actor.id,
        method=method,  # type: ignore[arg-type]
        status="elected",
        source_uri=uri,
        content_hash=digest,
        elected_by_user_id=actor.id,
        elected_at=datetime.now(timezone.utc),
    )
    session.add(row)
    session.flush()
    record_event(
        session,
        actor,
        "commercial_deduction_method_elected",
        actor,
        {
            "request_id": str(uuid4()),
            "method": method,
            "election_id": row.id,
            "superseded_id": previous.id if previous is not None else None,
        },
    )
    return {
        "election": serialize_election(row),
        "changed": True,
        "implemented": method in DEDUCTION_METHODS_IMPLEMENTED,
    }


def serialize_election(row: CommercialDeductionElection) -> dict[str, Any]:
    return {
        "id": row.id,
        "user_id": row.user_id,
        "method": row.method,
        "status": row.status,
        "implemented": row.method in DEDUCTION_METHODS_IMPLEMENTED,
        "source_uri": row.source_uri,
        "content_hash": row.content_hash,
        "elected_by_user_id": row.elected_by_user_id,
        "elected_at": row.elected_at.isoformat() if row.elected_at else None,
    }


# ══════════════════════════════════════════════════════════════════════════
# 首单扣费闸（验收 + 书面选定 + 不重复收）
# ══════════════════════════════════════════════════════════════════════════


def first_year_fee_already_covered(session: Session, user_id: str) -> bool:
    """「套餐含席位不重复收」判定（两条独立路径，任一成立即已覆盖）。

    路径一：权益行的席位来源＝实战营/陪跑营（该席位随含席位套餐而来）；
    路径二：科目层已入账一条**含首年席位费**的套餐席位费（订单已付费）。
    """
    entitlement = session.get(CommercialEntitlement, user_id)
    if (
        entitlement is not None
        and entitlement.seat_status == "active"
        and entitlement.seat_source in ("bootcamp_practical", "bootcamp_mentorship")
    ):
        return True
    covering_codes = tuple(
        code for code, item in REVENUE_PACKAGES.items() if item["covers_first_year_fee"]
    )
    covering_sources = tuple(
        item["seat_source"] for item in REVENUE_PACKAGES.values() if item["covers_first_year_fee"]
    )
    row = session.scalar(
        select(CommercialRevenueLedger.id).where(
            CommercialRevenueLedger.subject_type == "seat_fee",
            CommercialRevenueLedger.subject_user_id == user_id,
            CommercialRevenueLedger.status != "voided",
            (CommercialRevenueLedger.package_code.in_(covering_codes))
            | (CommercialRevenueLedger.seat_source.in_(covering_sources)),
        )
    )
    return row is not None


def _accepted_paid_payment(session: Session, package: DeliveryPackage) -> Payment | None:
    """该项目下**实收且验收通过**的里程碑收款（付费 + 验收双条件）。"""
    return session.scalar(
        select(Payment)
        .where(
            Payment.project_id == package.project_id,
            Payment.received_amount.is_not(None),
            Payment.acceptance_passed_at.is_not(None),
        )
        .order_by(Payment.milestone_key)
    )


def charge_first_order_seat_fee(
    session: Session,
    *,
    actor: User,
    user_id: object,
    package_id: object,
    confirm_password: object,
) -> dict[str, Any]:
    """首单扣费（admin + 密码确认的高风险写，ADR-007 §2.1）。

    闸门顺序（任一不满足即拒，零副作用）：
    1. **交付完成并验收**（``dispatch_status='accepted'`` 且 ``accepted_at``
       非空）——验收前**不触发**（任务书 §7 验收）；
    2. 该交付包的交付席位须为该交付者（未接单候选人不产生年度欠费）；
    3. 项目下存在**实收且验收通过**的里程碑收款（= 付费项目）；
    4. **席位不重复收**：已购含席位套餐／席位已激活／已扣过首单费 ⇒ 拒绝；
    5. **扣费方式已书面选定**且本期可实现（未选定 ⇒ 409）；
    6. 记账（金额＝任务书 §7 明文的 3980）＋ 激活席位（来源 first_delivery）。
    """
    _require_admin(actor)
    _confirm_password(session, actor, confirm_password)
    user = _require_user(session, user_id)
    if not isinstance(package_id, str) or not package_id:
        raise _error("invalid_request", "package_id 必填（首单对应的交付包）。")
    package = session.get(DeliveryPackage, package_id)
    if package is None:
        raise _error("package_not_found", "交付包不存在。", 404)

    if package.dispatch_status != "accepted" or package.accepted_at is None:
        raise _error(
            "acceptance_not_passed",
            "交付尚未完成并验收，不得触发首单扣费（任务书 §7：验收后触发）。",
            409,
        )
    if package.seat_delivery != user.id:
        raise _error(
            "deliverer_not_matched",
            "该交付包的交付席位不是本人，不能计首单扣费。",
            403,
        )
    payment = _accepted_paid_payment(session, package)
    if payment is None:
        raise _error(
            "payment_not_settled",
            "该项目尚无实收且验收通过的里程碑收款，不构成付费项目。",
            409,
        )

    if first_year_fee_already_covered(session, user.id):
        raise _error(
            "seat_fee_already_included",
            "已购含席位套餐（含首年席位费），不再重复收取。",
            409,
        )
    entitlement = ensure_entitlement(session, user.id)
    if entitlement.seat_status == "active":
        raise _error("seat_already_active", "该交付者年度席位已激活，不重复扣费。", 409)
    charged = session.scalar(
        select(CommercialRevenueLedger.id).where(
            CommercialRevenueLedger.subject_type == "seat_fee",
            CommercialRevenueLedger.subject_user_id == user.id,
            CommercialRevenueLedger.status != "voided",
            (CommercialRevenueLedger.package_code == "first_delivery")
            | (CommercialRevenueLedger.seat_source == "first_delivery"),
        )
    )
    if charged is not None:
        raise _error("seat_fee_already_charged", "该交付者已扣过首单席位费，不重复收取。", 409)

    election = get_active_election(session, user.id)
    if election is None:
        raise _error(
            "deduction_method_not_selected",
            "未书面选定扣费方式，不得扣费（任务书 §7：须交付者事先书面选定）。",
            409,
        )
    if election.method not in DEDUCTION_METHODS_IMPLEMENTED:
        raise _error(
            "deduction_method_not_implemented",
            "该扣费方式本期未实现（方案B 的周期与算式待拍板），不误按方案A 扣费。",
            409,
        )

    settlement = session.scalar(
        select(DeliverySettlement).where(DeliverySettlement.package_id == package.id)
    )
    entry = insert_revenue_entry(
        session,
        actor=actor,
        subject_type="seat_fee",
        line_item="software_subscription",
        amount=Decimal(FIRST_ORDER_SEAT_FEE),
        subject_user_id=user.id,
        package_code="first_delivery",
        seat_source="first_delivery",
        delivery_package_id=package.id,
        delivery_settlement_id=settlement.id if settlement is not None else None,
        payment_id=payment.id,
        basis={
            "reason": "first_paid_delivery_accepted",
            "package_id": package.id,
            "accepted_at": package.accepted_at.isoformat() if package.accepted_at else None,
            "payment_id": payment.id,
            "milestone_key": payment.milestone_key,
            "deduction_election_id": election.id,
            "deduction_method": election.method,
        },
    )
    activated_at = datetime.now(timezone.utc)
    activate_seat(
        session,
        actor=actor,
        user_id=user.id,
        seat_source="first_delivery",
        expires_at=_add_one_year(activated_at).isoformat(),
        confirm_password=confirm_password,
    )
    record_event(
        session,
        actor,
        "commercial_first_order_seat_fee_charged",
        user,
        {
            "request_id": str(uuid4()),
            "target_user_id": user.id,
            "entry_id": entry.id,
            "package_id": package.id,
            "amount": float(entry.amount),
            "deduction_election_id": election.id,
        },
    )
    return {
        "entry": entry.id,
        "amount": float(entry.amount),
        "seat_source": "first_delivery",
        "changed": True,
    }


# ══════════════════════════════════════════════════════════════════════════
# 认证挂模拟考核（通过线本期不设 ⇒ 缺省不判定通过）
# ══════════════════════════════════════════════════════════════════════════


def record_certification_evaluation(
    session: Session,
    *,
    actor: User,
    user_id: object,
    simulation_evaluation_id: object,
    source_uri: object = None,
    content_hash: object = None,
    confirm_password: object,
) -> dict[str, Any]:
    """挂模拟考核结果为认证依据（admin + 密码确认）。

    - 通过线配置位**未配置** ⇒ 记录停在 ``pending_threshold``，**不判定通过**
      （任务书 §7「认证挂模拟考核：通过线本期不设」），认证状态不变更；
    - 通过线已配置且考核 verdict='pass' 且得分达标 ⇒ 置 ``certified`` 并把
      ``certification_source`` 指向该考核行（指针，不内嵌正文）；
    - 未达标 ⇒ 置 ``rejected``，认证状态回落 ``uncertified``。
    """
    _require_admin(actor)
    _confirm_password(session, actor, confirm_password)
    user = _require_user(session, user_id)
    if not isinstance(simulation_evaluation_id, str) or not simulation_evaluation_id:
        raise _error("invalid_request", "simulation_evaluation_id 必填。")
    from fde_api.simulation.models import SimulationEvaluation

    evaluation = session.get(SimulationEvaluation, simulation_evaluation_id)
    if evaluation is None:
        raise _error("simulation_evaluation_not_found", "模拟考核评估行不存在。", 404)

    from fde_api.commercial.ledger_service import get_fee_config

    threshold_row = get_fee_config(session, "certification_pass_threshold")
    threshold = (
        Decimal(threshold_row.threshold)
        if threshold_row.status == "configured" and threshold_row.threshold is not None
        else None
    )
    score = Decimal(str(evaluation.total_score))
    verdict = evaluation.verdict
    if threshold is None:
        status = "pending_threshold"
    elif verdict == "pass" and score >= threshold:
        status = "certified"
    else:
        status = "rejected"

    row = session.scalar(
        select(CommercialCertificationRecord).where(
            CommercialCertificationRecord.user_id == user.id,
            CommercialCertificationRecord.simulation_evaluation_id == evaluation.id,
        )
    )
    if row is None:
        row = CommercialCertificationRecord(
            user_id=user.id, simulation_evaluation_id=evaluation.id
        )
        session.add(row)
    row.evaluation_verdict = verdict
    row.evaluation_score = score
    row.threshold = threshold
    row.status = status
    row.source_uri = source_uri.strip() if isinstance(source_uri, str) and source_uri.strip() else None
    row.content_hash = (
        content_hash.strip().lower()
        if isinstance(content_hash, str) and _SHA256_RE.match(content_hash.strip().lower())
        else None
    )
    row.decided_by_user_id = actor.id
    row.decided_at = datetime.now(timezone.utc)
    session.flush()

    entitlement = ensure_entitlement(session, user.id)
    if status == "certified":
        entitlement.certification_status = "certified"
        entitlement.certification_source = f"simulation_evaluation:{evaluation.id}"
    elif status == "rejected":
        entitlement.certification_status = "uncertified"
        entitlement.certification_source = f"simulation_evaluation:{evaluation.id}"

    record_event(
        session,
        actor,
        "commercial_certification_evaluation_recorded",
        actor,
        {
            "request_id": str(uuid4()),
            "target_user_id": user.id,
            "record_id": row.id,
            "simulation_evaluation_id": evaluation.id,
            "verdict": verdict,
            "score": float(score),
            "threshold": float(threshold) if threshold is not None else None,
            "status": status,
        },
    )
    return {
        "record": serialize_certification_record(row),
        "certified": status == "certified",
        "changed": True,
    }


def serialize_certification_record(row: CommercialCertificationRecord) -> dict[str, Any]:
    return {
        "id": row.id,
        "user_id": row.user_id,
        "simulation_evaluation_id": row.simulation_evaluation_id,
        "evaluation_verdict": row.evaluation_verdict,
        "evaluation_score": float(row.evaluation_score),
        "threshold": float(row.threshold) if row.threshold is not None else None,
        "status": row.status,
        "source_uri": row.source_uri,
        "content_hash": row.content_hash,
        "decided_by_user_id": row.decided_by_user_id,
        "decided_at": row.decided_at.isoformat() if row.decided_at else None,
    }


def list_certification_records(
    session: Session, *, actor: User, user_id: str
) -> dict[str, Any]:
    """认证记录读面（本人或 admin）。"""
    if actor.id != user_id and actor.role != ROLE_ADMIN:
        raise _error("commercial_certification_forbidden", "只能查看本人认证记录。", 403)
    _require_user(session, user_id)
    rows = list(
        session.scalars(
            select(CommercialCertificationRecord)
            .where(CommercialCertificationRecord.user_id == user_id)
            .order_by(CommercialCertificationRecord.decided_at.desc())
        )
    )
    return {
        "records": [serialize_certification_record(row) for row in rows],
        "count": len(rows),
    }


__all__ = [
    "CommercialServiceError",
    "charge_first_order_seat_fee",
    "elect_deduction_method",
    "first_year_fee_already_covered",
    "get_active_election",
    "list_certification_records",
    "list_packages",
    "record_certification_evaluation",
    "serialize_certification_record",
    "serialize_election",
]
