"""dispatch_cities 白名单加载与 §6.4 抢单开闸评估（P1-5 / C9）。

种子 schema = 设计 §12 逐字段；白名单只管需求侧开城，供给池全国开放。
§6.4 三条件（同时满足才允许 claim）：
1. 城内合格供给数 > 同期需求单量（供给 = status='active' 且 home_city=该城
   的 fde_profiles 计数；需求 = 近 90 天 published 包数，包城=企业代号第三段）；
2. 该城近 90 天拒单率 < 40%（rejected ÷ offered，经包的客户城归属）；
3. 算法备案完成且权重版本已公示——**备案编号无承载模型**（goal-r4 留注⑨），
   以「存在 published/active 规则版本」为代理；备案编号公示随 §5.1 落位后
   收紧。备案未定期间（附录 B-①）条件 3 恒不满足 → claim 全城关闭 = §11.1
   降级态，与种子 claim_enabled=false 双保险。
最终开闸 = 种子城市开关 AND 三条件（城市级，§6.4）。
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from fde_api.dispatch.models import (
    DeliveryPackage,
    DispatchOffer,
    DispatchRuleVersion,
    FdeProfile,
)
from fde_api.workbench.models import Project

_SEEDS_DIR = Path(__file__).resolve().parents[3] / "seeds"
_REJECT_RATE_CEILING = 0.40
_DEMAND_WINDOW_DAYS = 90


@lru_cache(maxsize=1)
def _city_seed() -> tuple[dict[str, Any], ...]:
    path = _SEEDS_DIR / "dispatch_cities.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise RuntimeError("dispatch_cities.json unavailable") from error
    rows = payload.get("cities") if isinstance(payload, dict) else None
    if not isinstance(rows, list) or not rows:
        raise RuntimeError("dispatch_cities.json empty")
    return tuple(rows)


@lru_cache(maxsize=1)
def _metrics_seed() -> tuple[dict[str, Any], ...]:
    path = _SEEDS_DIR / "acceptance_metrics.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise RuntimeError("acceptance_metrics.json unavailable") from error
    rows = payload.get("metrics") if isinstance(payload, dict) else None
    if not isinstance(rows, list) or not rows:
        raise RuntimeError("acceptance_metrics.json empty")
    return tuple(rows)


def load_dispatch_cities() -> tuple[dict[str, Any], ...]:
    """白名单投影（幂等：文件只读 + 进程缓存，重复调用同对象）。"""
    return _city_seed()


def load_acceptance_metrics() -> tuple[dict[str, Any], ...]:
    """验收指标投影（BP §11 闸门目标值；度量实现随闸门轮次落位）。"""
    return _metrics_seed()


def city_is_whitelisted(city: str | None) -> bool:
    if not city:
        return False
    return any(row["city"] == city for row in _city_seed())


def city_from_enterprise_code(code: str | None) -> str | None:
    """企业代号 → 客户城（§3.1 三段式「客户·行业·城市」第三段；不足三段 = 无城）。"""
    segments = (code or "").split("·")
    return segments[2] if len(segments) == 3 else None


def package_client_city(session: Session, package: DeliveryPackage) -> str | None:
    """包的客户城 = 企业代号第三段（§3.1 三段式「客户·行业·城市」）。
    留注⑤ 终版口径：包侧城市唯一权威，home_city 代理已退役（r12 B-④）。"""
    project = session.get(Project, package.project_id)
    code = project.enterprise_code if project is not None else None
    return city_from_enterprise_code(code)


def claim_gate_status(
    session: Session, city: str, *, now: datetime | None = None
) -> dict[str, Any]:
    """§6.4 三条件评估 + 种子开关，输出可解释的判定明细（§5.2 释明义务）。"""
    now = now or datetime.now(timezone.utc)
    window_start = now - timedelta(days=_DEMAND_WINDOW_DAYS)

    supply = session.scalar(
        select(func.count())
        .select_from(FdeProfile)
        .where(
            FdeProfile.home_city == city,
            FdeProfile.status == "active",
            FdeProfile.is_active.is_(True),
        )
    ) or 0

    published_rows = session.scalars(
        select(DeliveryPackage).where(
            DeliveryPackage.dispatch_status.in_(("published", "offered", "assigned", "accepted")),
            DeliveryPackage.published_at.is_not(None),
            DeliveryPackage.published_at >= window_start,
        )
    ).all()
    demand = sum(1 for row in published_rows if package_client_city(session, row) == city)

    round_offers = session.scalars(
        select(DispatchOffer).where(
            DispatchOffer.offered_at.is_not(None),
            DispatchOffer.offered_at >= window_start,
        )
    ).all()
    city_offers = [
        offer
        for offer in round_offers
        if (offer_package := session.get(DeliveryPackage, offer.package_id)) is not None
        and package_client_city(session, offer_package) == city
    ]
    offered = len(city_offers)
    rejected = sum(1 for offer in city_offers if offer.status == "declined")
    reject_rate = (rejected / offered) if offered else 0.0

    rule_published = (
        session.scalar(
            select(DispatchRuleVersion.id).where(
                DispatchRuleVersion.status.in_(("published", "active"))
            )
        )
        is not None
    )

    seed_row = next((row for row in _city_seed() if row["city"] == city), None)
    city_switch = bool(seed_row["claim_enabled"]) if seed_row else False

    conditions = {
        "supply_gt_demand": supply > demand,
        "reject_rate_ok": reject_rate < _REJECT_RATE_CEILING,
        "rule_publicized": rule_published,
    }
    return {
        "city": city,
        "whitelisted": seed_row is not None,
        "city_switch": city_switch,
        "supply": supply,
        "demand": demand,
        "offered": offered,
        "declined": rejected,
        "reject_rate": round(reject_rate, 4),
        "conditions": conditions,
        "claim_open": city_switch and all(conditions.values()),
    }
