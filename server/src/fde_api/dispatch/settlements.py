"""delivery_settlements 席位级结算服务（设计 §7.2/§7.3/§7.4，P0-4）。

分工铁律（§2.4 理由三）：Payment = 客户↔平台收款，语义零改动；本模块 =
平台↔FDE 分账，两表以 package→project 关联，资金流方向相反，绝不合并。

- 基数 = 里程碑实收回款（§7.3-1），不从分成池二次扣工时（§7.3-2）。
- 四席位 35/5/20/40；冷启动该城前 3 单 40/5/15/40（上浮 5pp 自城市合伙人
  扣，§7.1 建议，需确认）。比例取值：active 规则版本快照优先，回退
  DISPATCH_CONSTANTS（§6.2：改比例 = 新版本 + 公示，禁止硬编码散落）。
- 状态机 draft → accrued → payable → paid，任一方争议 → disputed。
  accrued 双条件：对应 Payment 实收 + G8 过门（acceptance_passed_at 非空）。
- 个税按劳务报酬累计预扣法（§7.4 公式）；率表以税务总局 2025 年第 16 号
  公告原文为准（附录 C 待确认项，代码常量集中此处便于法务复核后一次替换）。
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from sqlalchemy import extract, func, select
from sqlalchemy.orm import Session

from fde_api.auth.models import User
from fde_api.dispatch.cities import city_from_enterprise_code, package_client_city
from fde_api.dispatch.errors import DispatchServiceError
from fde_api.dispatch.models import DeliveryPackage, DeliverySettlement
from fde_api.dispatch.rules import active_rule_snapshot
from fde_api.projects.events import record_event
from fde_api.system_configuration import DISPATCH_CONSTANTS
from fde_api.workbench.models import Payment, Project

TWO_PLACES = Decimal("0.01")
SEAT_KEYS = ("platform", "region", "city", "delivery")

# §7.4 累计预扣法：劳务报酬预扣率表（累计应纳税所得额 → 预扣率 / 速算扣除数）。
# 率表口径：税务总局 2025 年第 16 号公告（设计文档明确「率表不抄进文档，
# 实现以公告原文为准」——本常量即实现侧唯一落点，法务确认后只改这里）。
WITHHOLDING_BRACKETS: tuple[tuple[int, int | None, Decimal, Decimal], ...] = (
    (0, 36_000, Decimal("0.03"), Decimal(0)),
    (36_000, 144_000, Decimal("0.10"), Decimal(2520)),
    (144_000, 300_000, Decimal("0.20"), Decimal(16920)),
    (300_000, 420_000, Decimal("0.25"), Decimal(31920)),
    (420_000, 660_000, Decimal("0.30"), Decimal(52920)),
    (660_000, 960_000, Decimal("0.35"), Decimal(85920)),
    (960_000, None, Decimal("0.45"), Decimal(181920)),
)

# §7.4 公式常数：累计费用 = 累计收入 × 20%；累计减除费用 = 5000 元/月
_EXPENSE_RATE = Decimal("0.20")
_MONTHLY_DEDUCTION = Decimal(5000)


def _money(value: Decimal) -> Decimal:
    return value.quantize(TWO_PLACES, rounding=ROUND_HALF_UP)


def seat_shares_for(session: Session, package: DeliveryPackage) -> dict[str, int]:
    """席位份额 %：active 版本快照优先（§7.3-3），回退 DISPATCH_CONSTANTS。
    冷启动判定 = 该城（包侧客户城，留注⑤ 终版口径）已接单序号 ≤ 前 N 单（§7.1）。"""
    snapshot = active_rule_snapshot(session)
    base_shares = (snapshot or {}).get("seat_shares") or DISPATCH_CONSTANTS["seat_shares"]
    cold_shares = (snapshot or {}).get("cold_start_seat_shares") or (
        DISPATCH_CONSTANTS["cold_start_seat_shares"]
    )
    cold_orders = (snapshot or {}).get("cold_start_first_orders") or (
        DISPATCH_CONSTANTS["cold_start_first_orders"]
    )
    if _city_order_rank(session, package) <= cold_orders:
        return {key: int(cold_shares[key]) for key in SEAT_KEYS}
    return {key: int(base_shares[key]) for key in SEAT_KEYS}


def _city_order_rank(session: Session, package: DeliveryPackage) -> int:
    """该包在同城的接单序号（1 起）。城 = **包侧客户城**（企业代号第三段，
    §3.1 三段式——留注⑤ 终版切换：home_city 代理随 B-④ 城市拍板退役，
    与 cities.package_client_city 同口径）。无城可判 → 返回大数（不触发冷启动）。"""
    city = package_client_city(session, package)
    if not city:
        return 1 << 30
    earlier_rows = session.execute(
        select(DeliveryPackage.id, Project.enterprise_code)
        .join(Project, Project.id == DeliveryPackage.project_id)
        .where(
            DeliveryPackage.id != package.id,
            DeliveryPackage.dispatch_status == "accepted",
            DeliveryPackage.accepted_at.is_not(None),
            DeliveryPackage.accepted_at
            < (package.accepted_at or datetime.now(timezone.utc)),
        )
    ).all()
    earlier = sum(
        1 for _row_id, code in earlier_rows if city_from_enterprise_code(code) == city
    )
    return earlier + 1


def split_four_seats(
    base_amount: Decimal, shares: dict[str, int]
) -> dict[str, Decimal]:
    """四席位金额（分）：区域/城市/交付按比例四舍五入，平台吸收舍入尾差，
    保证 Σ四席位 = 基数（审计口径）。"""
    if base_amount < 0:
        raise DispatchServiceError("invalid_request", "计提基数不能为负数。")
    region = _money(base_amount * Decimal(shares["region"]) / 100)
    city = _money(base_amount * Decimal(shares["city"]) / 100)
    delivery = _money(base_amount * Decimal(shares["delivery"]) / 100)
    platform = _money(base_amount - region - city - delivery)
    return {"platform": platform, "region": region, "city": city, "delivery": delivery}


def compute_withholding(
    session: Session,
    *,
    delivery_user_id: str,
    current_amount: Decimal,
    now: datetime | None = None,
) -> Decimal:
    """§7.4 累计预扣法：
    本期应预扣 = (累计收入 − 累计费用(收入×20%) − 累计减除(5000×月份数))
                 × 预扣率 − 速算扣除数 − 累计已预扣，下限 0。

    累计口径 = 该交付方本自然年已到 accrued/payable/paid 的席位结算 +
    本笔 current_amount；月份数 = 这些结算的验收月（含本月）去重计数。
    """
    now = now or datetime.now(timezone.utc)
    past_rows = session.execute(
        select(
            DeliverySettlement.delivery_amount,
            DeliverySettlement.withholding_tax,
            func.coalesce(
                DeliverySettlement.acceptance_passed_at, DeliverySettlement.created_at
            ),
        ).where(
            DeliverySettlement.seat_delivery_user_id == delivery_user_id,
            DeliverySettlement.status.in_(("accrued", "payable", "paid")),
            extract("year", DeliverySettlement.created_at) == now.year,
        )
    ).all()
    cumulative_income = Decimal(current_amount) + sum(
        (row[0] for row in past_rows), Decimal(0)
    )
    cumulative_withheld = sum((row[1] for row in past_rows), Decimal(0))
    months = {row[2].month for row in past_rows} | {now.month}
    taxable_base = max(
        Decimal(0),
        cumulative_income * (1 - _EXPENSE_RATE) - _MONTHLY_DEDUCTION * len(months),
    )
    for floor, ceiling, rate, quick in WITHHOLDING_BRACKETS:
        if taxable_base < floor:
            continue
        if ceiling is None or taxable_base <= ceiling:
            full_tax = _money(taxable_base * rate) - quick
            return max(Decimal(0), _money(full_tax - cumulative_withheld))
    return Decimal(0)


def record_receipt_settlements(
    session: Session, *, actor: User, project: Project, payment: Payment
) -> int:
    """收款实收回填钩子（payment_service.update_payment 事务内调用）：
    为项目下已发布/已接的交付包 upsert 结算 draft 行（基数 = 实收）。
    无交付包 → 纯 no-op（存量 A 组路径零感知，催款逻辑不动）。"""
    if payment.received_amount is None:
        return 0
    packages = session.scalars(
        select(DeliveryPackage).where(
            DeliveryPackage.project_id == project.id,
            DeliveryPackage.dispatch_status.in_(("published", "offered", "assigned", "accepted")),
        )
    ).all()
    created = 0
    for package in packages:
        shares = seat_shares_for(session, package)
        amounts = split_four_seats(payment.received_amount, shares)
        row = session.scalar(
            select(DeliverySettlement).where(
                DeliverySettlement.package_id == package.id,
                DeliverySettlement.settlement_key == payment.milestone_key,
            )
        )
        if row is None:
            row = DeliverySettlement(
                package_id=package.id,
                snapshot_hash=package.snapshot_hash,
                settlement_key=payment.milestone_key,
                base_amount=payment.received_amount,
                seat_delivery_user_id=package.seat_delivery,
                platform_amount=amounts["platform"],
                region_amount=amounts["region"],
                city_amount=amounts["city"],
                delivery_amount=amounts["delivery"],
            )
            session.add(row)
            created += 1
        else:
            row.base_amount = payment.received_amount
            row.platform_amount = amounts["platform"]
            row.region_amount = amounts["region"]
            row.city_amount = amounts["city"]
            row.delivery_amount = amounts["delivery"]
        session.flush()
        record_event(
            session,
            actor,
            "settlement_draft_recorded",
            package,
            {
                "settlement_key": payment.milestone_key,
                "base_amount": float(payment.received_amount),
                "shares": shares,
                "delivery_amount": float(amounts["delivery"]),
                "status": row.status,
            },
        )
    return len(packages)


def accrue_settlements_for_project(
    session: Session, *, actor: User, project_id: str
) -> int:
    """G8 过门联动（gate_service decide 事务内调用）：把「实收 + 验收双满足」
    的 draft 行推进 accrued，冗余 acceptance_passed_at 并计提当期预扣。"""
    payments = {
        row.milestone_key: row
        for row in session.scalars(
            select(Payment)
            .where(
                Payment.project_id == project_id,
                Payment.received_amount.is_not(None),
                Payment.acceptance_passed_at.is_not(None),
            )
            # 累计预扣按里程碑键序推进，计提顺序可复算（§7.4 审计口径）
            .order_by(Payment.milestone_key)
        )
    }
    if not payments:
        return 0
    packages = session.scalars(
        select(DeliveryPackage).where(DeliveryPackage.project_id == project_id)
    ).all()
    accrued = 0
    for package in packages:
        for key, payment in payments.items():
            row = session.scalar(
                select(DeliverySettlement).where(
                    DeliverySettlement.package_id == package.id,
                    DeliverySettlement.settlement_key == key,
                    DeliverySettlement.status == "draft",
                )
            )
            if row is None:
                continue
            passed_at = payment.acceptance_passed_at
            if passed_at is None:
                continue
            # 先算后改：compute_withholding 内的 SELECT 会触发 autoflush，
            # 若先把本行置 accrued，本行会混进「累计已计提」口径被双计。
            withholding = Decimal(0)
            if row.seat_delivery_user_id is not None:
                withholding = compute_withholding(
                    session,
                    delivery_user_id=row.seat_delivery_user_id,
                    current_amount=row.delivery_amount,
                    now=passed_at,
                )
            row.acceptance_passed_at = passed_at
            row.status = "accrued"
            row.withholding_tax = withholding
            accrued += 1
            session.flush()
            record_event(
                session,
                actor,
                "settlement_accrued",
                package,
                {
                    "settlement_key": key,
                    "base_amount": float(row.base_amount),
                    "withholding_tax": float(row.withholding_tax),
                    "acceptance_passed_at": passed_at.isoformat(),
                },
            )
    return accrued


def _load_settlement(session: Session, settlement_id: str) -> DeliverySettlement:
    row = session.get(DeliverySettlement, settlement_id)
    if row is None:
        raise DispatchServiceError("settlement_not_found", "结算行不存在。", 404)
    return row


def _package_or_404(session: Session, row: DeliverySettlement) -> DeliveryPackage:
    package = session.get(DeliveryPackage, row.package_id)
    if package is None:
        # package_id 外键 RESTRICT，父行被删才会走到这里
        raise DispatchServiceError("package_not_found", "交付包不存在。", 404)
    return package


def _linked_payment(session: Session, row: DeliverySettlement) -> Payment | None:
    package = session.get(DeliveryPackage, row.package_id)
    if package is None:
        return None
    return session.scalar(
        select(Payment).where(
            Payment.project_id == package.project_id,
            Payment.milestone_key == row.settlement_key,
        )
    )


def mark_payable(session: Session, *, actor: User, settlement_id: str) -> dict[str, Any]:
    """accrued → payable：发票前置校验（§7.5——对应里程碑发票已登记）。"""
    row = _load_settlement(session, settlement_id)
    if row.status != "accrued":
        raise DispatchServiceError(
            "invalid_settlement_state", "只有 accrued 结算可转 payable。", 409
        )
    payment = _linked_payment(session, row)
    if payment is None or not payment.invoice_no:
        raise DispatchServiceError(
            "invoice_required", "发票前置校验未过：对应里程碑尚未登记发票。", 422
        )
    row.status = "payable"
    session.flush()
    record_event(
        session,
        actor,
        "settlement_payable",
        _package_or_404(session, row),
        {"settlement_key": row.settlement_key},
    )
    return {"id": row.id, "status": row.status, "settlement_key": row.settlement_key}


def mark_paid(
    session: Session,
    *,
    actor: User,
    settlement_id: str,
    paid_proof_source_uri: str,
    paid_at: datetime | None = None,
) -> dict[str, Any]:
    """payable → paid：打款凭证只存指针（红线：不存本体）。"""
    row = _load_settlement(session, settlement_id)
    if row.status != "payable":
        raise DispatchServiceError(
            "invalid_settlement_state", "只有 payable 结算可转 paid。", 409
        )
    if not isinstance(paid_proof_source_uri, str) or not paid_proof_source_uri.strip():
        raise DispatchServiceError(
            "invalid_request", "paid_proof_source_uri 必须是非空指针。"
        )
    row.status = "paid"
    row.paid_proof_source_uri = paid_proof_source_uri.strip()
    row.paid_at = paid_at or datetime.now(timezone.utc)
    session.flush()
    record_event(
        session,
        actor,
        "settlement_paid",
        _package_or_404(session, row),
        {
            "settlement_key": row.settlement_key,
            "paid_proof_source_uri": row.paid_proof_source_uri,
            "paid_at": row.paid_at.isoformat(),
        },
    )
    return {"id": row.id, "status": row.status, "settlement_key": row.settlement_key}


def mark_disputed(
    session: Session, *, actor: User, settlement_id: str, reason: str
) -> dict[str, Any]:
    """任一方发起争议（§6.6 L0-L3 仲裁入口；disputes 表随后续轮落位）。"""
    row = _load_settlement(session, settlement_id)
    if row.status == "paid":
        raise DispatchServiceError(
            "invalid_settlement_state", "已打款结算不能转 disputed，走人工对账。", 409
        )
    if not isinstance(reason, str) or not reason.strip():
        raise DispatchServiceError("invalid_request", "争议原因必填。")
    row.status = "disputed"
    session.flush()
    record_event(
        session,
        actor,
        "settlement_disputed",
        _package_or_404(session, row),
        {"settlement_key": row.settlement_key, "reason": reason.strip()},
    )
    return {"id": row.id, "status": row.status, "settlement_key": row.settlement_key}
