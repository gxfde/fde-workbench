"""quote_service：P4 报价台账与报价单草稿（设计 §6，承接《报价计算卡-v1.1》）。

口径铁律（卡原文程序化，卡一字不动；工程层不得发明方法论层没有的取值）：
- 三层计算式（卡 §一）：
    realistic = ideal × 档内集成偏离 × 数据成熟度 × 合规系数 × 2.0
    成本 = 现金成本 + realistic × 时薪
    公式价 = 成本 × 1.4（毛利 28.6%）
- 系数取值集合封闭（卡 §2.2/§4，v1.1 已填值）：
    档内偏离 ∈ {0.75, 1.00, 1.40}；数据成熟度 ∈ {0.8, 1.0, 1.3, 1.6}；
    合规 ∈ {1.0, 1.2, 1.35}；时薪 ∈ {150, 180, 400}；毛利 ×1.4。
- B 层（卡 §三）：score 0–10 → 系数 = 0.9 + score/10 × 0.3；
    冷启动纪律——anchor_mode=cold_start 时 score ≤ 5（系数上限 1.05）。
- 锚点（卡 §5.1）与三分支（卡 §5.3）：
    A 公式价 < 锚点下沿 → 报 [下沿, 下沿×1.25]；
    B 区间内 → 报 [公式价×0.9, min(公式价×1.2, 锚点上沿)]，B 层系数在此生效；
    C > 锚点上沿 → 不许硬报，必须 c_handling 四选一（缩范围/拆分期/外部协作/门票单）。
- 首单默认参数（卡 §5.4）：轻量优先、档内 ×1.0、数据 ×1.0、合规 ×1.0、缓冲 ×2.0、
    时薪 ¥150、B 层 ≤1.05；三条硬约束——不接高集成、不接 D 档、realistic ≤ 120 h。
- 每个数字带 claim_status ∈ {estimated, claimed, measured, accepted}（§5.3 四值，
    accepted 之外 UI 黄标）；默认全 estimated（卡 §九：回校前都是初始假设）。
- 回校义务（卡 §9 #1 / 设计 §6）：首单结项必须回校缓冲 ×2.0，落 deviation_pct /
    deviation_reason——finalize 强制先 calibrate，做成结项 checklist 固定一步。
- 对外报价单（draft HTML）不出现任何系数（卡 §九/§十-3）：客户看三档。
"""

from __future__ import annotations

import html
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Mapping

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session, joinedload

from fde_api.auth.models import User
from fde_api.dispatch.channel_guard import (
    ChannelGuardError,
    ensure_enterprise_channel,
)
from fde_api.extensions import db
from fde_api.projects.events import record_event
from fde_api.projects.permissions import project_access
from fde_api.workbench.models import OperationEvent, Project, Quote

QUOTE_CARD_SOURCE = "deliverables/fde-sop-v1.1/报价计算卡-v1.1.md"

TIER_LABELS = {"light": "轻量", "standard": "标准", "flagship": "旗舰"}

# 卡 §2.1 场景—基线工时 + §2.3 现金成本三档 + §5.1 双轨锚点（v2.4.6 拍板值）
TIERS: dict[str, dict[str, Any]] = {
    "light": {
        "ideal_hours": Decimal("25"),
        "cash_cost": 1500,
        "anchors": {
            "cold_start": (18000, 28000),
            "steady": (28000, 38000),
        },
    },
    "standard": {
        "ideal_hours": Decimal("50"),
        "cash_cost": 5000,
        "anchors": {
            "cold_start": (35000, 50000),
            "steady": (55000, 70000),
        },
    },
    "flagship": {
        "ideal_hours": Decimal("80"),
        "cash_cost": 9000,
        "anchors": {
            "cold_start": (55000, 75000),
            "steady": (85000, 110000),
        },
    },
}

# 卡 §2.2 三个调节系数（v1.1 填值，封闭集合）
INTEGRATION_FACTORS = (Decimal("0.75"), Decimal("1.00"), Decimal("1.40"))
DATA_FACTORS = (Decimal("0.8"), Decimal("1.0"), Decimal("1.3"), Decimal("1.6"))
COMPLIANCE_FACTORS = (Decimal("1.0"), Decimal("1.2"), Decimal("1.35"))
# 卡 §4 两档时薪（150 首单 / 180 第 2-3 单 / 400 稳态）
HOURLY_RATES = (150, 180, 400)
# 卡 §1 毛利 28.6% / §5.4 缓冲 ×2.0
MARGIN_FACTOR = Decimal("1.4")
DEFAULT_BUFFER = Decimal("2.00")
# 卡 §七 让利：冷启动 50% / 稳态 40%（可让利额度 = 毛利 × X）
ALLOWANCE_RATES = {"cold_start": Decimal("0.5"), "steady": Decimal("0.4")}
# 卡 §6 成交底线 = 成本 × 1.25（低于此须书面记门票单）
DEAL_FLOOR_FACTOR = Decimal("1.25")
# 卡 §5.3 C 分支四选一
C_HANDLING_OPTIONS = ("scope_cut", "split_phases", "external_collab", "ticket_deal")
C_HANDLING_LABELS = {
    "scope_cut": "缩范围",
    "split_phases": "拆分期",
    "external_collab": "外部协作",
    "ticket_deal": "门票单（书面记亏损额与补回路径）",
}
# 卡 §5.4 首单默认参数（preset=first_order_defaults 一键取值）
FIRST_ORDER_PRESET = "first_order_defaults"

# §5.3 四值 claim 状态（Quote 数字字段全量；默认 estimated）
CLAIM_STATUSES = ("estimated", "claimed", "measured", "accepted")
_CLAIM_ORDER = {status: index for index, status in enumerate(CLAIM_STATUSES)}
CLAIMABLE_FIELDS = (
    "ideal_hours",
    "integration_factor",
    "data_factor",
    "compliance_factor",
    "buffer_factor",
    "hourly_rate",
    "cash_cost",
    "b_layer_score",
    "formula_price",
    "final_amount",
    "actual_hours",
)

TWO_PLACES = Decimal("0.01")

# 数值入参的合理上限（工程防御，非方法论取值）：超出即视为录入错误拒 400
MAX_INPUT_HOURS = Decimal("10000")
MAX_INPUT_MONEY = Decimal("10000000")


class QuoteServiceError(Exception):
    def __init__(self, code: str, message: str, status: int):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


def _money(value: Decimal) -> Decimal:
    return value.quantize(TWO_PLACES, rounding=ROUND_HALF_UP)


def _b_layer_factor(score: int) -> Decimal:
    # 卡 §三：系数 = 0.9 + 总分/10 × 0.3
    return (Decimal("0.9") + Decimal(score) * Decimal("0.03")).quantize(TWO_PLACES)


def _compute(
    *,
    ideal_hours: Decimal,
    integration: Decimal,
    data: Decimal,
    compliance: Decimal,
    buffer: Decimal,
    hourly_rate: int,
    cash_cost: int,
    margin: Decimal,
) -> dict[str, Decimal]:
    """卡 §一 三层计算式（纯函数，三档复用）。"""
    realistic = (
        ideal_hours * integration * data * compliance * buffer
    ).quantize(TWO_PLACES)
    labor = _money(realistic * Decimal(hourly_rate))
    total = _money(Decimal(cash_cost) + labor)
    formula = _money(total * margin)
    return {
        "realistic_hours": realistic,
        "labor_cost": labor,
        "total_cost": total,
        "formula_price": formula,
    }


def _branch_of(formula: Decimal, anchor_low: int, anchor_high: int) -> str:
    if formula < Decimal(anchor_low):
        return "A"
    if formula > Decimal(anchor_high):
        return "C"
    return "B"


def _quote_range(branch: str, formula: Decimal, anchor_low: int, anchor_high: int) -> tuple[Decimal | None, Decimal | None]:
    # 卡 §5.3 三分支怎么报
    if branch == "A":
        return (
            Decimal(anchor_low),
            _money(Decimal(anchor_low) * Decimal("1.25")),
        )
    if branch == "B":
        return (
            _money(formula * Decimal("0.9")),
            min(_money(formula * Decimal("1.2")), Decimal(anchor_high)),
        )
    return (None, None)


def _b_reference_price(quote: Quote) -> float | None:
    """B 分支建议报价点（卡 §5.3：B 层系数在 B 区间内生效）。"""
    if quote.branch != "B" or quote.quote_low is None or quote.quote_high is None:
        return None
    candidate = _money(quote.formula_price * quote.b_layer_factor)
    clamped = min(max(candidate, quote.quote_low), quote.quote_high)
    return float(clamped)


def _tier_defaults(tier: str, anchor_mode: str) -> tuple[Decimal, int, int, int]:
    spec = TIERS[tier]
    anchor_low, anchor_high = spec["anchors"][anchor_mode]
    return spec["ideal_hours"], spec["cash_cost"], anchor_low, anchor_high


def _decimal_input(payload: Mapping[str, Any], key: str) -> Decimal | None:
    """解析数字入参：缺省返回 None；提供即必须可解析为有限数，否则 400。

    不许「非法输入静默落默认」——封闭集合/正负校验必须看到调用方真实传的值，
    否则 0、负数、NaN、Infinity 会被 or 兜底或比较恒假洗白（负成本会击穿成交底线）。
    """
    if key not in payload or payload.get(key) is None:
        return None
    value = payload.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise QuoteServiceError("invalid_request", f"{key} 必须是数字。", 400)
    try:
        parsed = Decimal(str(value))
    except ArithmeticError:
        raise QuoteServiceError("invalid_request", f"{key} 必须是数字。", 400) from None
    if not parsed.is_finite():
        raise QuoteServiceError("invalid_request", f"{key} 必须是有限数字。", 400)
    return parsed


def _advance_claims(quote: Quote, updates: Mapping[str, str]) -> None:
    """内部写手（calibrate/finalize）与 API 同守 claim 单调前进（§5.3）：只升不降。"""
    claims = dict(quote.field_claims)
    for field, status in updates.items():
        current = claims.get(field, "estimated")
        if _CLAIM_ORDER[status] > _CLAIM_ORDER[current]:
            claims[field] = status
    quote.field_claims = claims


def _next_quote_key(session: Session, project_id: str) -> str:
    count = session.scalar(
        select(func.count()).select_from(Quote).where(Quote.project_id == project_id)
    )
    return f"Q-{(count or 0) + 1:03d}"


def create_quote(*, actor: User, project_id: str, payload: Mapping[str, Any]) -> dict[str, Any]:
    """建报价（输入=卡系数；输出=公式列 + 三分支）。preset=first_order_defaults
    走卡 §5.4 首单默认参数并强制三条硬约束。"""
    session = db.session()
    try:
        with session.begin():
            project = _load_project(session, actor, project_id, manage=True)
            # P2-4 私单封堵（派单设计 §8.5）H2：直签线项目 × 池内企业 → 报价
            # 同样封堵（成交从报价开始；存量直签项目的防御纵深）。
            try:
                ensure_enterprise_channel(
                    session,
                    actor=actor,
                    business_line=project.business_line or "FDE",
                    enterprise_code=project.enterprise_code,
                )
            except ChannelGuardError as error:
                raise QuoteServiceError(
                    error.code, error.message, error.status
                ) from None
            # 串行化同项目的报价创建（quote_key 按 count+1 生成，防并发撞唯一键）
            session.execute(
                select(Project.id).where(Project.id == project.id).with_for_update()
            )
            preset = payload.get("preset")
            if preset is not None and preset != FIRST_ORDER_PRESET:
                raise QuoteServiceError("invalid_request", "未知的报价预设。", 400)

            tier = payload.get("tier") or ("light" if preset else None)
            if tier not in TIERS:
                raise QuoteServiceError("invalid_tier", "档位必须是 light/standard/flagship。", 400)
            anchor_mode = payload.get("anchor_mode") or (
                "cold_start" if preset else None
            )
            if anchor_mode not in ("cold_start", "steady"):
                raise QuoteServiceError("invalid_anchor_mode", "锚点必须是 cold_start 或 steady。", 400)
            default_ideal, default_cash, anchor_low, anchor_high = _tier_defaults(
                tier, anchor_mode
            )

            ideal = _decimal_input(payload, "ideal_hours")
            if ideal is None:
                ideal = default_ideal
            if not Decimal("0") < ideal <= MAX_INPUT_HOURS:
                raise QuoteServiceError(
                    "invalid_request",
                    f"ideal_hours 必须在 0–{MAX_INPUT_HOURS} h 内。",
                    400,
                )
            cash_cost = payload.get("cash_cost")
            cash_cost = default_cash if cash_cost is None else cash_cost
            if isinstance(cash_cost, bool) or not isinstance(cash_cost, int) or cash_cost < 0:
                raise QuoteServiceError("invalid_request", "现金成本必须是不为负的整数金额。", 400)
            if cash_cost > int(MAX_INPUT_MONEY):
                # 数值入参的合理上限（工程防御，非方法论取值）：超出即视为录入错误拒 400
                # （同 final_amount 口径——cash_cost 是 Integer 列，超限 500 前拦下）。
                raise QuoteServiceError(
                    "invalid_request",
                    f"现金成本不得超过 {int(MAX_INPUT_MONEY)}（超出视为录入错误）。",
                    400,
                )
            integration = _decimal_input(payload, "integration_factor")
            if integration is None:
                integration = Decimal("1.00")
            data = _decimal_input(payload, "data_factor")
            if data is None:
                data = Decimal("1.00")
            compliance = _decimal_input(payload, "compliance_factor")
            if compliance is None:
                compliance = Decimal("1.00")
            buffer = _decimal_input(payload, "buffer_factor")
            if buffer is None:
                buffer = DEFAULT_BUFFER
            hourly_rate = payload.get("hourly_rate")
            if hourly_rate is None:
                hourly_rate = 150 if preset else None
            if hourly_rate not in HOURLY_RATES:
                raise QuoteServiceError(
                    "invalid_hourly_rate", "时薪必须是 150 / 180 / 400（卡 §4 两档）。", 400
                )
            score = payload.get("b_layer_score")
            score = 0 if score is None else score
            if isinstance(score, bool) or not isinstance(score, int) or not 0 <= score <= 10:
                raise QuoteServiceError("invalid_b_score", "B 层打分必须是 0–10 整数。", 400)

            if integration not in INTEGRATION_FACTORS:
                raise QuoteServiceError("invalid_factor", "档内集成偏离取值必须是 0.75/1.00/1.40。", 400)
            if data not in DATA_FACTORS:
                raise QuoteServiceError("invalid_factor", "数据成熟度取值必须是 0.8/1.0/1.3/1.6。", 400)
            if compliance not in COMPLIANCE_FACTORS:
                raise QuoteServiceError("invalid_factor", "合规系数取值必须是 1.0/1.2/1.35。", 400)
            if buffer != DEFAULT_BUFFER:
                raise QuoteServiceError(
                    "invalid_buffer",
                    "缓冲系数当前固定 ×2.0（卡 §1；回校走结项 calibrate，不接受随手改）。",
                    400,
                )
            # 卡 §三 冷启动纪律：前 3 单 B 层上限 1.05（总分 ≤ 5）
            if anchor_mode == "cold_start" and score > 5:
                raise QuoteServiceError(
                    "b_layer_cold_cap",
                    "冷启动锚点下 B 层总分不得超过 5（系数上限 1.05，卡 §三）。",
                    400,
                )
            # 卡 §5.4 首单三条硬约束
            if preset == FIRST_ORDER_PRESET:
                if integration == Decimal("1.40"):
                    raise QuoteServiceError(
                        "first_order_constraint",
                        "首单硬约束①：不接高集成/跨系统事务（档内升级请改按上一档报价）。",
                        400,
                    )
                if data == Decimal("1.6"):
                    raise QuoteServiceError(
                        "first_order_constraint",
                        "首单硬约束②：不接 D 档脏数据（数据治理段须单列，首单不碰）。",
                        400,
                    )

            computed = _compute(
                ideal_hours=ideal,
                integration=integration,
                data=data,
                compliance=compliance,
                buffer=buffer,
                hourly_rate=hourly_rate,
                cash_cost=cash_cost,
                margin=MARGIN_FACTOR,
            )
            if preset == FIRST_ORDER_PRESET and computed["realistic_hours"] > Decimal("120"):
                raise QuoteServiceError(
                    "first_order_constraint",
                    f"首单硬约束③：realistic {computed['realistic_hours']} h 超过 120 h，请拆分期。",
                    400,
                )
            formula = computed["formula_price"]
            branch = _branch_of(formula, anchor_low, anchor_high)
            quote_low, quote_high = _quote_range(branch, formula, anchor_low, anchor_high)
            c_handling = None
            if branch == "C":
                c_handling = payload.get("c_handling")
                if c_handling not in C_HANDLING_OPTIONS:
                    raise QuoteServiceError(
                        "branch_c_handling_required",
                        "公式价高于锚点上沿不许硬报（卡 §5.3 C）：必须四选一 "
                        + "/".join(C_HANDLING_OPTIONS) + "。",
                        400,
                    )

            quote_key = _next_quote_key(session, project.id)
            quote = Quote(
                project_id=project.id,
                quote_key=quote_key,
                tier=tier,
                status="draft",
                ideal_hours=ideal,
                integration_factor=integration,
                data_factor=data,
                compliance_factor=compliance,
                buffer_factor=buffer,
                hourly_rate=hourly_rate,
                cash_cost=cash_cost,
                margin_factor=MARGIN_FACTOR,
                b_layer_score=score,
                anchor_mode=anchor_mode,
                preset=preset,
                realistic_hours=computed["realistic_hours"],
                labor_cost=computed["labor_cost"],
                total_cost=computed["total_cost"],
                formula_price=formula,
                b_layer_factor=_b_layer_factor(score),
                anchor_low=anchor_low,
                anchor_high=anchor_high,
                branch=branch,
                quote_low=quote_low,
                quote_high=quote_high,
                c_handling=c_handling,
                # P1-6（派单设计 §8.4）：报价归属人=创建者（派单语境交付方侧
                # 归属过滤维度；平台侧台账报价可后续置空）
                owner_user_id=actor.id,
                # 卡 §九：回校前所有取值都是初始假设 → 全 estimated
                field_claims={field: "estimated" for field in CLAIMABLE_FIELDS},
            )
            session.add(quote)
            session.flush()
            record_event(
                session,
                actor,
                "quote_created",
                quote,
                {
                    "quote_key": quote_key,
                    "tier": tier,
                    "branch": branch,
                    "formula_price": float(formula),
                    "preset": preset,
                },
            )
            result = _serialize_quote(quote)
        return result
    except QuoteServiceError:
        raise
    finally:
        session.close()


def list_quotes(*, actor: User, project_id: str) -> dict[str, Any]:
    session = db.session()
    try:
        with session.begin():
            project = _load_project(session, actor, project_id, manage=False)
            rows = list(
                session.scalars(
                    select(Quote)
                    .where(Quote.project_id == project.id)
                    .order_by(Quote.created_at, Quote.quote_key)
                )
            )
            events = _recent_quote_events(session, project.id)
        return {
            "quotes": [_serialize_quote(row) for row in rows],
            "events": events,
        }
    finally:
        session.close()


def update_quote_claim(
    *, actor: User, project_id: str, quote_key: str, payload: Mapping[str, Any]
) -> dict[str, Any]:
    """§5.3 单字段 claim 前进（只许单调前进：estimated→claimed→measured→accepted）。"""
    field = payload.get("field")
    status = payload.get("claim_status")
    if field not in CLAIMABLE_FIELDS:
        raise QuoteServiceError("invalid_request", f"该字段不在 claim 范围内：{field}", 400)
    if status not in CLAIM_STATUSES:
        raise QuoteServiceError("invalid_request", "claim_status 必须是 estimated/claimed/measured/accepted。", 400)
    session = db.session()
    try:
        with session.begin():
            project = _load_project(session, actor, project_id, manage=True)
            quote = _load_quote(session, project.id, quote_key, for_update=True)
            current = quote.field_claims.get(field, "estimated")
            if _CLAIM_ORDER[status] < _CLAIM_ORDER[current]:
                raise QuoteServiceError(
                    "claim_not_revertible",
                    f"{field} 当前 {current}，claim 状态只许前进不许回退（§5.3）。",
                    409,
                )
            if status == current:
                raise QuoteServiceError("claim_unchanged", "该字段已是该状态。", 400)
            claims = dict(quote.field_claims)
            claims[field] = status
            quote.field_claims = claims
            session.flush()
            record_event(
                session,
                actor,
                "quote_claim_updated",
                quote,
                {"quote_key": quote.quote_key, "field": field, "claim_status": status},
            )
            return _serialize_quote(quote)
    finally:
        session.close()


def calibrate_quote(
    *, actor: User, project_id: str, quote_key: str, payload: Mapping[str, Any]
) -> dict[str, Any]:
    """回校缓冲 ×2.0（卡 §9 #1：首单结项必做；设计 §6 结项 checklist 固定一步）。

    deviation_pct = (actual_hours − realistic) ÷ realistic（工时偏差，卡 §八）；
    calibrated_buffer_factor = 2.0 × actual ÷ realistic（回校后只改系数不改结构）。
    """
    actual = _decimal_input(payload, "actual_hours")
    if actual is None or not Decimal("0") < actual <= MAX_INPUT_HOURS:
        raise QuoteServiceError("invalid_request", "actual_hours 必须是正数。", 400)
    reason = (payload.get("deviation_reason") or "").strip()
    if not reason:
        raise QuoteServiceError(
            "deviation_reason_required", "回校必须落 deviation_reason（卡 §9 #1）。", 400
        )
    session = db.session()
    try:
        with session.begin():
            project = _load_project(session, actor, project_id, manage=True)
            quote = _load_quote(session, project.id, quote_key, for_update=True)
            if quote.actual_hours is not None:
                raise QuoteServiceError(
                    "already_calibrated", "该报价已回校（回校一次为准）。", 409
                )
            realistic = quote.realistic_hours
            deviation = ((actual - realistic) / realistic).quantize(Decimal("0.0001"))
            # Numeric(7,4) 上限 999.9999：deviation 先落库（flush 前），超限必须先 400
            # 拒（「超出即视为录入错误拒 400」防御口径，同 calibrated 的 99.99 闸）——
            # 否则 flush 抛 DataError 走全局 500（goal-c CR-010）。
            if abs(deviation) > Decimal("999.9999"):
                raise QuoteServiceError(
                    "invalid_request",
                    "actual_hours 与 realistic 偏差超出存储上限（疑似录入错误），请核对实际工时。",
                    400,
                )
            quote.actual_hours = actual
            quote.deviation_pct = deviation
            quote.deviation_reason = reason
            calibrated = (quote.buffer_factor * actual / realistic).quantize(
                Decimal("0.01")
            )
            # Numeric(4,2) 上限 99.99；更大的比例只可能是录入错误
            if calibrated > Decimal("99.99"):
                raise QuoteServiceError(
                    "invalid_request",
                    "actual_hours 与 realistic 比例失衡（回校缓冲超出存储上限），请核对实际工时。",
                    400,
                )
            quote.calibrated_buffer_factor = calibrated
            _advance_claims(
                quote, {"actual_hours": "measured", "buffer_factor": "measured"}
            )
            session.flush()
            record_event(
                session,
                actor,
                "quote_calibrated",
                quote,
                {
                    "quote_key": quote.quote_key,
                    "actual_hours": float(actual),
                    "deviation_pct": float(deviation),
                    "calibrated_buffer_factor": float(quote.calibrated_buffer_factor),
                },
            )
            return _serialize_quote(quote)
    finally:
        session.close()


def finalize_quote(
    *, actor: User, project_id: str, quote_key: str, payload: Mapping[str, Any]
) -> dict[str, Any]:
    """成交回填（卡 §八：成交后 48h 内）——最终价由人拍板，引擎只做三条线校验。

    卡 §6 毛利三条线：成交底线 = 成本×1.25，低于此必须 ticket_deal + 书面理由；
    让利额度 = (成交价−成本)×50%/40% 在此算出（卡 §七：报备阶段就算出来）。
    C 层校验（算得过账/不超审批上限）为提示性返回，不落库。
    """
    final_amount = _decimal_input(payload, "final_amount")
    if final_amount is None or not Decimal("0") < final_amount <= MAX_INPUT_MONEY:
        raise QuoteServiceError("invalid_request", "final_amount 必须是正数。", 400)
    session = db.session()
    try:
        with session.begin():
            project = _load_project(session, actor, project_id, manage=True)
            quote = _load_quote(session, project.id, quote_key, for_update=True)
            if quote.status == "finalized":
                raise QuoteServiceError("already_finalized", "该报价已成交回填。", 409)
            # 首单身份不依赖调用方自报 preset：工作室首笔成交（尚无任何已 finalize
            # 报价）即首单——卡 §5.4 三条硬约束 + 卡 §9 #1 回校义务在此服务端强制，
            # 手填系数建出的"事实首单"绕不过去。
            #
            # B3 TOCTOU：finalized_count 的统计与随后的判定之间没有行锁，两个
            # 并发 finalize 都能读到 0 → 双双按「首单」放行，绕过「必须回校」
            # 与三条硬约束。事务级 advisory lock 让「统计 + 判定 + 写 finalized」
            # 这一段完全串行（先例：bridge/sync.py 的 fde_bridge_apply）。
            session.execute(
                text("SELECT pg_advisory_xact_lock(hashtext('fde_quote_first_order'))")
            )
            finalized_count = session.scalar(
                select(func.count())
                .select_from(Quote)
                .where(Quote.status == "finalized")
            )
            first_order = (finalized_count or 0) == 0
            if first_order and quote.actual_hours is None:
                raise QuoteServiceError(
                    "calibration_required",
                    "本单为工作室首单：结项必须先回校缓冲系数 ×2.0（calibrate），"
                    "再成交回填（卡 §9 #1 / 设计 §6）。",
                    409,
                )
            if first_order:
                if quote.integration_factor == Decimal("1.40"):
                    raise QuoteServiceError(
                        "first_order_constraint",
                        "首单硬约束①：不接高集成/跨系统事务（档内升级请改按上一档报价）。",
                        409,
                    )
                if quote.data_factor == Decimal("1.6"):
                    raise QuoteServiceError(
                        "first_order_constraint",
                        "首单硬约束②：不接 D 档脏数据（数据治理段须单列，首单不碰）。",
                        409,
                    )
                if quote.realistic_hours > Decimal("120"):
                    raise QuoteServiceError(
                        "first_order_constraint",
                        f"首单硬约束③：realistic {quote.realistic_hours} h 超过 120 h，请拆分期。",
                        409,
                    )
            floor = _money(quote.total_cost * DEAL_FLOOR_FACTOR)
            ticket_deal = bool(payload.get("ticket_deal"))
            ticket_note = (payload.get("ticket_note") or "").strip()
            if final_amount < floor and not (ticket_deal and ticket_note):
                raise QuoteServiceError(
                    "below_deal_floor",
                    f"成交价低于底线 {floor}（成本×1.25，卡 §6）：低于此必须书面记门票单"
                    "（ticket_deal=true + ticket_note 写明亏损额与补回路径）。",
                    400,
                )
            quote.final_amount = final_amount
            quote.final_deviation_pct = (
                (final_amount - Decimal(quote.anchor_low)) / Decimal(quote.anchor_low)
            ).quantize(Decimal("0.0001"))
            # 卡 §七：冷启动（前 3 单）50% / 稳态 40%——首单必属冷启动，锚点报稳态也不许用 40%
            allowance_rate = (
                ALLOWANCE_RATES["cold_start"]
                if first_order
                else ALLOWANCE_RATES[quote.anchor_mode]
            )
            quote.allowance_cap = max(
                Decimal("0"),
                _money((final_amount - quote.total_cost) * allowance_rate),
            )
            allowance_paid = _decimal_input(payload, "allowance_paid")
            if allowance_paid is None:
                allowance_paid = Decimal("0")
            if allowance_paid < 0 or allowance_paid > quote.allowance_cap:
                raise QuoteServiceError(
                    "allowance_exceeded",
                    f"让利实付须在 0–{quote.allowance_cap} 内（可让利额度，卡 §七）。",
                    400,
                )
            quote.allowance_paid = allowance_paid
            quote.ticket_deal = ticket_deal
            quote.ticket_note = ticket_note
            quote.status = "finalized"
            _advance_claims(quote, {"final_amount": "claimed"})
            session.flush()

            # 卡 §6 C 层三道校验（提示性）：算得过账 / 不亏 / 不超审批上限
            checks: dict[str, Any] = {
                "not_below_floor": final_amount >= floor,
                "first_order": first_order,
            }
            first_year_value = _decimal_input(payload, "first_year_recoverable_value")
            if first_year_value:
                ratio = (final_amount / first_year_value).quantize(Decimal("0.0001"))
                checks["value_ratio"] = float(ratio)
                checks["value_ratio_ok"] = Decimal("0.10") <= ratio <= Decimal("0.33")
            approval_cap = _decimal_input(payload, "approval_cap")
            if approval_cap:
                checks["within_approval_cap"] = final_amount <= approval_cap

            record_event(
                session,
                actor,
                "quote_finalized",
                quote,
                {
                    "quote_key": quote.quote_key,
                    "final_amount": float(final_amount),
                    "final_deviation_pct": float(quote.final_deviation_pct),
                    "allowance_cap": float(quote.allowance_cap),
                    "ticket_deal": ticket_deal,
                    "checks": checks,
                },
            )
            result = _serialize_quote(quote)
            result["checks"] = checks
        return result
    finally:
        session.close()


def render_quote_draft(*, actor: User, project_id: str, quote_key: str) -> dict[str, Any]:
    """对外报价单草稿（HTML 字符串，草稿不自动发客户，设计 §6）。

    卡 §十-3：对外报价单仍用三档格式——本卡系数一律不出现；
    数字口径与覆盖范围照卡/SOP 原文。
    """
    session = db.session()
    try:
        with session.begin():
            project = _load_project(session, actor, project_id, manage=False)
            quote = _load_quote(session, project.id, quote_key)
            html_body = _build_draft_html(project, quote)
        return {"html": html_body, "quote_key": quote.quote_key}
    finally:
        session.close()


def _build_draft_html(project: Project, quote: Quote) -> str:
    esc = html.escape
    tiers_html: list[str] = []
    for tier, spec in TIERS.items():
        computed = _compute(
            ideal_hours=spec["ideal_hours"],
            integration=quote.integration_factor,
            data=quote.data_factor,
            compliance=quote.compliance_factor,
            buffer=quote.buffer_factor,
            hourly_rate=quote.hourly_rate,
            cash_cost=spec["cash_cost"],
            margin=quote.margin_factor,
        )
        anchor_low, anchor_high = spec["anchors"][quote.anchor_mode]
        branch = _branch_of(computed["formula_price"], anchor_low, anchor_high)
        low, high = _quote_range(branch, computed["formula_price"], anchor_low, anchor_high)
        recommended = "（推荐）" if tier == quote.tier else ""
        if branch == "C":
            range_text = "当前参数下超锚点，需缩范围/拆分期后另出"
        else:
            range_text = f"¥{low:,.0f} – ¥{high:,.0f}"
        tiers_html.append(
            "<tr>"
            f"<td>{esc(TIER_LABELS[tier])}{recommended}</td>"
            f"<td>¥{computed['formula_price']:,.0f}</td>"
            f"<td>{range_text}</td>"
            f"<td>{branch}</td>"
            "</tr>"
        )
    d_banner = ""
    if quote.data_factor == Decimal("1.6"):
        d_banner = (
            "<p class='banner'>数据治理段单列：本报价按数据成熟度 D 档评估，"
            "数据治理工作量与排期在报价单与排期表单列（不藏在\u201c数据准备\u201d内），"
            "总周期约 30% 留给数据治理；口径变更时映射表工时重做规则见下。</p>"
        )
    return f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8">
<title>报价单草稿 · {esc(project.enterprise_code)}</title>
<style>
 body{{font-family:"Microsoft YaHei",system-ui,sans-serif;color:#1f2933;max-width:760px;margin:24px auto;padding:0 16px}}
 h1{{font-size:20px;border-bottom:2px solid #1e3a5f;padding-bottom:8px}}
 .meta{{color:#5f6b7a;font-size:13px;margin:4px 0}}
 table{{border-collapse:collapse;width:100%;margin:12px 0}}
 th,td{{border:1px solid #d3dce6;padding:8px 10px;font-size:14px;text-align:left}}
 th{{background:#eef3f8}}
 .banner{{background:#fff7e0;border-left:4px solid #d99a00;padding:8px 12px;font-size:13px}}
 .terms{{font-size:13px;color:#37424f;line-height:1.7}}
 .watermark{{color:#b3261e;font-weight:600}}
</style></head><body>
<h1>FDE 交付服务 · 参考报价（草稿）</h1>
<p class="meta">项目：{esc(project.name)}（{esc(project.enterprise_code)}）</p>
<p class="meta">报价编号：{esc(quote.quote_key)} ｜ 出具日期：____-__-__ ｜ 有效期：__ 天</p>
<p class="watermark">内部草稿 · 不自动发送客户 · 对外以工具包 §6-C 三档格式出具 · 最终价格以双方确认为准</p>
<h3>三档参考价</h3>
<table><tr><th>档位</th><th>参考基准价</th><th>建议报价区间</th><th>锚点分支</th></tr>
{''.join(tiers_html)}
</table>
{d_banner}
<h3>覆盖范围与口径</h3>
<div class="terms">
<ul>
<li>工时口径：自现场调研（Discover）至试点验收的技术工时；<b>不含</b>深度诊断（A 套餐独立计价）、启动建档与售后陪跑。</li>
<li>映射表工时单列：数据映射/口径对照工作单独计价；客户口径变更需重做时按重做规则另行结算，返工不额外计费的范围以报价单写明为准。</li>
<li>差旅单列、实报实销，不计入报价基数；客户账号直付的软件/云资源建议客户自付。</li>
<li>效果数字写方案不写合同；验收标准以双方书面确认为准。</li>
<li>分期与付款节奏按合同约定执行（A 预付 / B 50%+50% / C 40%+40%+20% / D 月付预付）。</li>
</ul>
</div>
<p class="meta">出处：《FDE个人接单工具包与表单模板-v2.4.6》§6-C/§6-D · 《报价计算卡-v1.1》（对内底稿）</p>
</body></html>"""


def _serialize_quote(quote: Quote) -> dict[str, Any]:
    return {
        "id": quote.id,
        "quote_key": quote.quote_key,
        "tier": quote.tier,
        "tier_label": TIER_LABELS[quote.tier],
        "status": quote.status,
        "preset": quote.preset,
        "inputs": {
            "ideal_hours": float(quote.ideal_hours),
            "integration_factor": float(quote.integration_factor),
            "data_factor": float(quote.data_factor),
            "compliance_factor": float(quote.compliance_factor),
            "buffer_factor": float(quote.buffer_factor),
            "hourly_rate": quote.hourly_rate,
            "cash_cost": quote.cash_cost,
            "margin_factor": float(quote.margin_factor),
            "b_layer_score": quote.b_layer_score,
            "anchor_mode": quote.anchor_mode,
        },
        "computed": {
            "realistic_hours": float(quote.realistic_hours),
            "labor_cost": float(quote.labor_cost),
            "total_cost": float(quote.total_cost),
            "formula_price": float(quote.formula_price),
            "b_layer_factor": float(quote.b_layer_factor),
            # 卡 §5.3「B 层系数在此生效」：B 分支建议报价点 = 公式价 × B 层系数，
            # 夹在 B 区间 [公式×0.9, min(公式×1.2, 锚点上沿)] 内。
            "b_reference_price": _b_reference_price(quote),
            "anchor_low": quote.anchor_low,
            "anchor_high": quote.anchor_high,
            "branch": quote.branch,
            "quote_low": float(quote.quote_low) if quote.quote_low is not None else None,
            "quote_high": float(quote.quote_high) if quote.quote_high is not None else None,
            "c_handling": quote.c_handling,
            "c_handling_label": C_HANDLING_LABELS.get(quote.c_handling or ""),
        },
        "ledger": {
            "final_amount": float(quote.final_amount) if quote.final_amount is not None else None,
            "final_deviation_pct": float(quote.final_deviation_pct) if quote.final_deviation_pct is not None else None,
            "allowance_cap": float(quote.allowance_cap) if quote.allowance_cap is not None else None,
            "allowance_paid": float(quote.allowance_paid),
            "ticket_deal": quote.ticket_deal,
            "ticket_note": quote.ticket_note,
        },
        "calibration": {
            "actual_hours": float(quote.actual_hours) if quote.actual_hours is not None else None,
            "deviation_pct": float(quote.deviation_pct) if quote.deviation_pct is not None else None,
            "deviation_reason": quote.deviation_reason,
            "calibrated_buffer_factor": float(quote.calibrated_buffer_factor) if quote.calibrated_buffer_factor is not None else None,
        },
        "field_claims": quote.field_claims,
        "claims_summary": {
            "accepted": sum(1 for v in quote.field_claims.values() if v == "accepted"),
            "total": len(quote.field_claims),
        },
        "created_at": quote.created_at.isoformat() if quote.created_at else None,
    }


QUOTE_EVENT_TYPES = (
    "quote_created",
    "quote_claim_updated",
    "quote_calibrated",
    "quote_finalized",
)


def _recent_quote_events(session: Session, project_id: str) -> list[dict[str, Any]]:
    rows = session.execute(
        select(OperationEvent)
        .options(joinedload(OperationEvent.actor))
        .where(
            OperationEvent.project_id == project_id,
            OperationEvent.event_type.in_(QUOTE_EVENT_TYPES),
        )
        .order_by(OperationEvent.occurred_at.desc())
        .limit(20)
    ).scalars()
    return [
        {
            "event_type": row.event_type,
            "occurred_at": row.occurred_at.isoformat() if row.occurred_at else None,
            "actor_display_name": row.actor.display_name if row.actor else None,
            "changes": row.changes,
        }
        for row in rows
    ]


def _load_project(session: Session, actor: User, project_id: str, *, manage: bool) -> Project:
    project = session.get(Project, project_id)
    if project is None:
        raise QuoteServiceError("project_not_found", "项目不存在或已被删除。", 404)
    access = project_access(actor, project)
    if not (access.can_manage if manage else access.can_view):
        raise QuoteServiceError("forbidden", "你没有该项目报价的操作权限。", 403)
    return project


def _load_quote(
    session: Session, project_id: str, quote_key: str, *, for_update: bool = False
) -> Quote:
    stmt = select(Quote).where(
        Quote.project_id == project_id, Quote.quote_key == quote_key
    )
    if for_update:
        stmt = stmt.with_for_update()
    quote = session.scalar(stmt)
    if quote is None:
        raise QuoteServiceError("quote_not_found", "该报价不存在。", 404)
    return quote
