"""O-3 额度计量（goal-d7，自动交付 §6）。

一次动作 = 一条 ledger 行：agent_run（发起时刻计，演练零计量）/
meeting_convene（工具面召集；人工开会免费——「人工不占 agent 限额」）/
ai_chat（预调研分析 worker 成功就绪时计，失败不计）。seat 归集键 = 动作
发起人。超额**只标注不拦截**：record_action 永不抛错，over_quota 标注 +
加油包计价入口由配额快照透出——「交付中途绝不静默断供，只限速不限质」。
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, select

from fde_api.agents.models import SeatActionLedger

# 透明化硬规则（自动交付 §6）：余量 ≤20% 提醒
WARN_REMAINING_PCT = 20

# translation = 翻译器草稿采纳（goal-d10 O-3 随路落账：翻译时无项目维度不计，
# 采纳时刻项目上下文齐备随路落，计 1 unit，ref_id=translation_id）。
ACTION_TYPES = ("agent_run", "meeting_convene", "ai_chat", "translation")


def _month_start(now: datetime) -> datetime:
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def month_used(session: Any, *, user_id: str, now: datetime | None = None) -> int:
    """当月（UTC 月桶）该席位的动作数（ledger 行数，units 累计口径一致）。"""
    moment = now or datetime.now(timezone.utc)
    return int(
        session.scalar(
            select(func.coalesce(func.sum(SeatActionLedger.units), 0)).where(
                SeatActionLedger.user_id == user_id,
                SeatActionLedger.created_at >= _month_start(moment),
            )
        )
        or 0
    )


def record_action(
    session: Any,
    *,
    project_id: str,
    user_id: str,
    action_type: str,
    ref_id: str | None = None,
    units: int = 1,
    quota_monthly: int,
    now: datetime | None = None,
) -> bool:
    """落一条动作台账并返回 over_quota 标注。**绝不抛错、绝不拦截**——
    超额与否只决定标注位（绝不断供，自动交付 §6 透明化硬规则）。"""
    if action_type not in ACTION_TYPES:
        raise ValueError(f"unknown action_type: {action_type}")
    moment = now or datetime.now(timezone.utc)
    over = False
    if quota_monthly > 0:
        over = month_used(session, user_id=user_id, now=moment) >= quota_monthly
    session.add(
        SeatActionLedger(
            project_id=project_id,
            user_id=user_id,
            action_type=action_type,
            ref_id=ref_id[:64] if ref_id else None,
            units=units,
            over_quota=over,
        )
    )
    return over


def _window(session: Any, settings: Any, *, now: datetime) -> dict[str, Any]:
    """30 天重校钩子（自动交付 §6 重校条款）：起点显式配置或以最早 ledger
    行推导；到期后 review_due=true——重校结论回写文档并知会拍板人（人工）。"""
    started_at: datetime | None = None
    raw = (getattr(settings, "seat_quota_started_at", "") or "").strip()
    if raw:
        try:
            started_at = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            started_at = None
    if started_at is None:
        started_at = session.scalar(
            select(func.min(SeatActionLedger.created_at))
        )
    if started_at is None:
        return {"started_at": None, "review_due_at": None, "review_due": False}
    if started_at.tzinfo is None:
        started_at = started_at.replace(tzinfo=timezone.utc)
    review_days = int(getattr(settings, "seat_quota_review_days", 30) or 30)
    review_due_at = started_at.fromtimestamp(
        started_at.timestamp() + review_days * 86400, tz=timezone.utc
    )
    return {
        "started_at": started_at.isoformat(),
        "review_due_at": review_due_at.isoformat(),
        "review_due": now >= review_due_at,
    }


def quota_snapshot(session: Any, settings: Any, *, user_id: str) -> dict[str, Any]:
    """配额快照（GET /agents/quota）：消耗显示 / ≤20% 提醒 / 超额标注 /
    加油包计价入口 / 重校窗口。只读透明，无任何拦截语义。"""
    now = datetime.now(timezone.utc)
    quota = int(getattr(settings, "seat_action_quota_monthly", 100) or 0)
    used = month_used(session, user_id=user_id, now=now)
    unlimited = quota <= 0
    remaining = 0 if unlimited else max(0, quota - used)
    remaining_pct = None if unlimited else round(remaining * 100 / quota, 1)
    return {
        "user_id": user_id,
        "quota_monthly": quota,
        "unlimited": unlimited,
        "used": used,
        "remaining": remaining,
        "remaining_pct": remaining_pct,
        # 超额标注（不拦截）：used >= quota
        "over_quota": (not unlimited) and used >= quota,
        # 余量 ≤20% 提醒（透明化硬规则）
        "warn_low_remaining": (not unlimited) and remaining_pct is not None and remaining_pct <= WARN_REMAINING_PCT,
        "warn_threshold_pct": WARN_REMAINING_PCT,
        "pack": {
            "entry": "action_pack",
            "price_yuan": float(getattr(settings, "seat_action_pack_price_yuan", 1.0) or 0),
            "unit": "action",
            "note": str(getattr(settings, "seat_action_pack_note", "")),
        },
        "window": _window(session, settings, now=now),
    }
