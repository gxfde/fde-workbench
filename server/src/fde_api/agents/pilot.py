"""S1 试点开关（goal-d6，PRD §10 / 技术实施方案 §1 S1-7 / 总纲 UM-1）。

试点口径：**30 天 / 20 run，先到为准**；全部会议走 lite 档；试点期产出
拦截率 / 一次通过率 / 单会成本报告（UM-1 闸门数据），O-8/UM-5 阈值由人在
试点结束后评（本模块只出数、不判阈——PRD 决议 D15）。

- 窗口起点：``FDE_AGENT_PILOT_STARTED_AT``（ISO 显式配置）优先；缺省以最早
  一条 agent_run 的 created_at 推导（首个 run 即试点启动）；无 run = 未启动。
- 计数排除演练 run（幂等键 ``rehearsal:`` 前缀，goal-d6 V4 手动触发面）。
- 窗口走完不再拦（试点结束 → 报告定升级/回退），上限只在窗口内生效。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func, select

from fde_api.agents.models import AgentArtifact, AgentRun, AgentToolCall
from fde_api.meetings.models import ReviewMeeting
from fde_api.meetings.templates import MEETING_CONVENE_COST_UNITS

REHEARSAL_KEY_PREFIX = "rehearsal:"

# 拦截标记（goal-d5 U2 落库口径）：run.degraded_reason 的门拦截值
GATE_BLOCKED_REASON = "review_gate_open"

# 熔断终态（V5/B 类）
CIRCUIT_STATUSES = frozenset({"timeout", "budget_exceeded"})


def _parse_started_at(raw: str) -> datetime | None:
    raw = (raw or "").strip()
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def pilot_window(session: Any, settings: Any) -> tuple[datetime, datetime] | None:
    """(起点, 到期)；试点关闭或无法确定起点 → None。"""
    if not getattr(settings, "agent_pilot_enabled", False):
        return None
    days = int(getattr(settings, "agent_pilot_window_days", 30) or 30)
    started = _parse_started_at(getattr(settings, "agent_pilot_started_at", "") or "")
    if started is None:
        started = session.scalar(select(func.min(AgentRun.created_at)))
    if started is None:
        return None
    if started.tzinfo is None:
        started = started.replace(tzinfo=timezone.utc)
    return started, started + timedelta(days=days)


def pilot_status(session: Any, settings: Any, *, now: datetime | None = None) -> dict[str, Any]:
    """试点状态快照（report 与 start_run 闸共用）。"""
    window = pilot_window(session, settings)
    if window is None:
        return {"enabled": bool(getattr(settings, "agent_pilot_enabled", False)), "active": False}
    started, expires = window
    now = now or datetime.now(timezone.utc)
    max_runs = int(getattr(settings, "agent_pilot_max_runs", 20) or 20)
    runs_used = int(
        session.scalar(
            select(func.count())
            .select_from(AgentRun)
            .where(
                AgentRun.created_at >= started,
                AgentRun.created_at < expires,
                AgentRun.idempotency_key.notlike(REHEARSAL_KEY_PREFIX + "%"),
            )
        )
    )
    active = now < expires
    # 架构评估 2026-11-07 D4：试点开启 ≠ 执行通道可用——ZcodeAdapter spawn
    # 契约未经任何真实完成的 run 验证前（售前方案 v1.2 Q5 拍板「须重写」，
    # T-Z1 落地前），每个 run 的 spawn 段预期失败并全部落入 L2 降级，试点
    # 指标（降级率/一次通过率）会被污染。派生警示只读呈现，不拦 run。
    proven = (
        session.scalar(
            select(AgentRun.id)
            .where(
                AgentRun.status == "completed",
                AgentRun.created_at >= started,
                AgentRun.created_at < expires,
                AgentRun.idempotency_key.notlike(REHEARSAL_KEY_PREFIX + "%"),
            )
            .limit(1)
        )
        is not None
    )
    contract_unverified = active and not proven
    warnings: list[str] = []
    if contract_unverified:
        warnings.append(
            "ZcodeAdapter 契约尚未经任何真实完成的 run 验证（售前方案 Q5：spawn 段契约须重写，见 T-Z1）；"
            "spawn 失败将全部落入 L2 降级并污染试点指标，建议先完成执行通道裁定（T-Z1）再解读试点数据。"
        )
    return {
        "enabled": True,
        "active": active,
        "started_at": started.isoformat(),
        "expires_at": expires.isoformat(),
        "window_days": int((expires - started).days),
        "runs_used": runs_used,
        "runs_limit": max_runs,
        "runs_remaining": max(0, max_runs - runs_used),
        "days_remaining": max(0, int((expires - now).days)),
        "exhausted": active and runs_used >= max_runs,
        "contract_unverified": contract_unverified,
        "warnings": warnings,
    }


def pilot_capacity_error(session: Any, settings: Any, *, now: datetime | None = None) -> tuple[str, str, dict[str, Any]] | None:
    """窗口内 20 run 上限闸；返回 (code, message, detail) 或 None（放行）。"""
    status = pilot_status(session, settings, now=now)
    if not status.get("active") or not status.get("exhausted"):
        return None
    return (
        "pilot_run_limit_exceeded",
        "试点期 run 配额已用尽（30 天/20 run 先到为准）；请等待试点窗口结束或联系管理员调整。",
        {"runs_used": status["runs_used"], "runs_limit": status["runs_limit"], "expires_at": status["expires_at"]},
    )


def _median(values: list[int]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return float(ordered[mid])
    return (ordered[mid - 1] + ordered[mid]) / 2


def build_report(session: Any, settings: Any, *, now: datetime | None = None) -> dict[str, Any]:
    """试点报告（UM-1）：试点状态 + 六指标。只出数，不判 O-8/UM-5 阈值。"""
    status = pilot_status(session, settings, now=now)
    window = pilot_window(session, settings)
    metrics: dict[str, Any] = {}
    if window is not None:
        started, expires = window
        rows = list(
            session.scalars(
                select(AgentRun)
                .where(AgentRun.created_at >= started, AgentRun.created_at < expires)
                .order_by(AgentRun.created_at)
            )
        )
        total = len(rows)
        blocked = [row for row in rows if row.degraded_reason == GATE_BLOCKED_REASON]
        # 过门产物 run：家族任意尝试最终产出挂 solution 的产物（终审通道入口）
        linked_run_ids = set(
            session.scalars(
                select(AgentArtifact.run_id)
                .join(AgentRun, AgentRun.id == AgentArtifact.run_id)
                .where(
                    AgentArtifact.linked_solution_id.isnot(None),
                    AgentRun.created_at >= started,
                    AgentRun.created_at < expires,
                )
            )
        )
        first_try_passed = 0
        if linked_run_ids:
            family_rows = session.execute(
                select(AgentRun.idempotency_key, AgentRun.retry_of).where(AgentRun.id.in_(linked_run_ids))
            ).all()
            first_try_passed = sum(1 for _key, retry_of in family_rows if not retry_of)
        gate_attempts = len(blocked) + len(linked_run_ids)
        meetings = int(session.scalar(select(func.count()).select_from(ReviewMeeting).where(
            ReviewMeeting.created_at >= started, ReviewMeeting.created_at < expires)) or 0)
        convene_calls = int(session.scalar(
            select(func.count())
            .select_from(AgentToolCall)
            .join(AgentRun, AgentRun.id == AgentToolCall.run_id)
            .where(
                AgentToolCall.tool_name == "meeting_convene",
                AgentToolCall.decision == "allowed",
                AgentRun.created_at >= started,
                AgentRun.created_at < expires,
            )) or 0)
        metrics = {
            # 强制门拦截率（U2 试点观测；持续为 0 或过高都触发复盘——总纲 §5）
            "intercept_rate": round(len(blocked) / gate_attempts, 4) if gate_attempts else None,
            # 评审后一次通过率：过门产物 run 中首次尝试（无 retry_of）占比
            "first_pass_rate": round(first_try_passed / len(linked_run_ids), 4) if linked_run_ids else None,
            # 单会成本：工具面召集计费总额 / 会议总数（U6 口径：计费落触发 run）
            "avg_meeting_cost_units": round(convene_calls * MEETING_CONVENE_COST_UNITS / meetings, 4) if meetings else None,
            # 降级率（L1+ 占比；持续 >30% = 基座不成熟——自动交付 §7.3 红线）
            "degraded_rate": round(sum(1 for row in rows if row.degraded) / total, 4) if total else None,
            # 超时/预算熔断率
            "circuit_breaker_rate": round(sum(1 for row in rows if row.status in CIRCUIT_STATUSES) / total, 4) if total else None,
            "median_run_cost_units": _median([row.token_cost for row in rows]),
            "total_runs": total,
            "total_meetings": meetings,
            "blocked_runs": len(blocked),
        }
    stale_minutes = int(getattr(settings, "agent_recover_stale_minutes", 15) or 0)
    stuck_count = 0
    if window is not None:
        started, expires = window
        now = now or datetime.now(timezone.utc)
        threshold = timedelta(minutes=stale_minutes) if stale_minutes > 0 else timedelta(0)
        stuck_count = int(
            session.scalar(
                select(func.count())
                .select_from(AgentRun)
                .where(
                    AgentRun.status.in_(["queued", "running"]),
                    AgentRun.created_at >= started,
                    AgentRun.created_at < expires,
                    AgentRun.updated_at <= now - threshold,
                )
            )
        )
    return {"pilot": status, "metrics": metrics, "stuck_inflight_runs": stuck_count}


__all__ = [
    "REHEARSAL_KEY_PREFIX",
    "build_report",
    "pilot_capacity_error",
    "pilot_status",
    "pilot_window",
]
