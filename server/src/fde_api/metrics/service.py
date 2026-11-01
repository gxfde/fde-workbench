"""P0/P1 指标聚合服务（goal-d8 建卡，goal-d9 埋点三件转实）。

口径纪律（报告 §二 登记）：
- 全部为只读聚合（无客户数据，纯计数/中位数），require_auth 登录即可读。
- 样本不足的指标显式返回 ``status="insufficient_data"``（不编造数值）。
- goal-d9 埋点三件转实：SOW 拍板事件（solution_signoff_resolved）/
  资深介入时长（agent_run_handoff ↔ 拍板事件按 run 软链配对）/ 422 拦截
  事件（ai_output_intercepted）——空库（样本 0）仍 insufficient。
- 「一次通过率」当前口径 = run 终态 completed 占比（retry 幂等链未折算，
  细化口径挂账）；「草稿生成耗时」当前口径 = agent 路 completed run
  duration_ms 中位数（人工路无计时埋点，基线对比挂账）。
- 当月口径 = UTC 自然月（O-3 重校窗口 30 天语义在 agents/quota.py，不混用）。
"""
from __future__ import annotations

from datetime import datetime, time, timezone
from statistics import median
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from fde_api.agents.models import AgentRun, SeatActionLedger
from fde_api.guidance.models import ProjectGuidanceAnalysis
from fde_api.meetings.models import ReviewMeeting
from fde_api.workbench.models import OperationEvent

_TERMINAL_FAILED = ("failed", "timeout", "budget_exceeded")


def _metric(
    key: str,
    label: str,
    *,
    value: Any,
    sample_size: int,
    definition: str,
    target: float | None = None,
) -> dict[str, Any]:
    return {
        "key": key,
        "label": label,
        "value": value,
        "sample_size": sample_size,
        "definition": definition,
        "target": target,
        "status": "ok" if sample_size > 0 else "insufficient_data",
    }


def build_metrics_report(session: Session) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    month_start = datetime.combine(now.date().replace(day=1), time.min, tzinfo=timezone.utc)

    # ---- P0：售前独立完成录入+确认率（confirmed 分析版覆盖的项目占比）----
    guidance_rows = session.execute(
        select(ProjectGuidanceAnalysis.project_id, ProjectGuidanceAnalysis.status)
    ).all()
    guidance_projects = {project_id for project_id, _status in guidance_rows}
    confirmed_projects = {
        project_id
        for project_id, status in guidance_rows
        if status == "confirmed"
    }
    p0_confirm = _metric(
        "presurvey_confirm_rate",
        "售前独立完成录入+确认率",
        value=round(len(confirmed_projects) / len(guidance_projects), 4)
        if guidance_projects
        else 0.0,
        sample_size=len(guidance_projects),
        definition="存在 confirmed 预调研分析版的项目数 / 出现过分析版的项目数（按 project 去重）",
        target=0.90,
    )

    # ---- P0：方案草稿生成耗时（agent 路观测；人工基线未积累挂账）----
    completed_durations = session.scalars(
        select(AgentRun.duration_ms).where(AgentRun.status == "completed")
    ).all()
    p0_draft_ms = _metric(
        "draft_generation_p50_ms",
        "方案草稿生成耗时中位数（agent 路）",
        value=median(completed_durations) if completed_durations else None,
        sample_size=len(completed_durations),
        definition="completed run 的 duration_ms 中位数；人工路无计时埋点，↓≥50% 基线对比待积累（挂账）",
    )

    # ---- P0：SOW 一次拍板通过率（goal-d9 埋点转实：signoff 拍板事件序）----
    signoff_rows = session.execute(
        select(OperationEvent.changes, OperationEvent.created_at)
        .where(OperationEvent.event_type == "solution_signoff_resolved")
        .order_by(OperationEvent.created_at.asc(), OperationEvent.id.asc())
    ).all()
    first_decisions: dict[str, str] = {}
    for changes, _created in signoff_rows:
        solution_id = str((changes or {}).get("solution_id") or "")
        if solution_id and solution_id not in first_decisions:
            first_decisions[solution_id] = str((changes or {}).get("decision") or "")
    first_pass_solutions = sum(1 for decision in first_decisions.values() if decision == "approved")
    p0_sow = _metric(
        "sow_first_pass_rate",
        "SOW 一次拍板通过率",
        value=round(first_pass_solutions / len(first_decisions), 4) if first_decisions else 0.0,
        sample_size=len(first_decisions),
        definition="首个拍板事件即 approved 的方案数 / 出现过拍板事件的方案数（拍板事件=solution_signoff_resolved）",
        target=0.70,
    )
    # ---- P0：资深工程师售前介入时长（goal-d9 埋点转实：接管→拍板配对）----
    handoff_rows = session.execute(
        select(OperationEvent.changes, OperationEvent.created_at)
        .where(OperationEvent.event_type == "agent_run_handoff")
        .order_by(OperationEvent.created_at.asc(), OperationEvent.id.asc())
    ).all()
    handoff_at: dict[str, datetime] = {}
    for changes, created in handoff_rows:
        run_id = str((changes or {}).get("run_id") or "")
        if run_id and run_id not in handoff_at:
            handoff_at[run_id] = created
    durations_hours = [
        (created - handoff_at[run_id]).total_seconds() / 3600.0
        for changes, created in signoff_rows
        if (run_id := str((changes or {}).get("run_id") or "")) and run_id in handoff_at and created is not None
    ]
    p0_senior = _metric(
        "senior_intervention_hours",
        "资深工程师售前介入时长",
        value=round(median(durations_hours), 2) if durations_hours else None,
        sample_size=len(durations_hours),
        definition="L3 转人工接管（agent_run_handoff）→ 拍板收口（signoff 事件）的中位时长（小时）；配对键=checkpoint.handoff_run_id 软链。↓≥60% 为目标（基线待积累）",
        target=0.60,
    )

    # ---- P1 试点：lite 档会议占比（试点期要求全部 lite，UM-1）----
    tier_rows = session.scalars(select(ReviewMeeting.gate_tier)).all()
    lite_count = sum(1 for tier in tier_rows if tier == "lite")
    p1_lite = _metric(
        "lite_meeting_share",
        "lite 档会议占比",
        value=round(lite_count / len(tier_rows), 4) if tier_rows else 0.0,
        sample_size=len(tier_rows),
        definition="gate_tier=lite 的评审会数 / 评审会总数（P1 试点期目标=1.0）",
        target=1.0,
    )

    # ---- P1 试点：run 一次通过率（终态 completed 占比）----
    status_rows = session.scalars(select(AgentRun.status)).all()
    completed_count = sum(1 for status in status_rows if status == "completed")
    terminal_count = sum(1 for status in status_rows if status == "completed" or status in _TERMINAL_FAILED)
    p1_first_pass = _metric(
        "run_first_pass_rate",
        "run 一次通过率",
        value=round(completed_count / terminal_count, 4) if terminal_count else 0.0,
        sample_size=terminal_count,
        definition="终态 completed 占比（retry 幂等链未折算，细化口径挂账）",
    )

    # ---- P1 试点：降级率（降级产物占比，>30% 暂停扩大授权）----
    degraded_count = session.scalar(
        select(func.count()).select_from(AgentRun).where(AgentRun.degraded.is_(True))
    )
    p1_degraded = _metric(
        "run_degraded_share",
        "降级产物占比（L1+）",
        value=round((degraded_count or 0) / completed_count, 4)
        if completed_count
        else 0.0,
        sample_size=completed_count,
        definition="degraded=true 的 run 数 / completed run 数（持续 >30% 暂停扩大 agent 授权范围）",
        target=0.30,
    )

    # ---- 持续观测：单 run 成本中位数（token_cost，O-3 口径单位）----
    token_costs = session.scalars(select(AgentRun.token_cost)).all()
    ongoing_cost = _metric(
        "run_cost_median_units",
        "单 run 成本中位数",
        value=median(token_costs) if token_costs else None,
        sample_size=len(token_costs),
        definition="全部 run 的 token_cost 中位数（O-3 计量单位）",
    )

    # ---- 持续观测：输出拦截率（goal-d9 埋点转实：422 拦截事件计数）----
    intercepted_count = int(session.scalar(
        select(func.count()).select_from(OperationEvent)
        .where(OperationEvent.event_type == "ai_output_intercepted")
    ) or 0)
    ongoing_intercept = _metric(
        "interception_rate",
        "输出拦截率",
        value=round(intercepted_count / (completed_count + intercepted_count), 4)
        if (completed_count + intercepted_count) else 0.0,
        sample_size=completed_count + intercepted_count,
        definition="422 输出扫描拦截事件数（ai_output_intercepted）/（completed run 数 + 拦截事件数）",
    )

    # ---- 持续观测：当月工作台动作（O-3 seat 台账）----
    month_rows = session.scalars(
        select(SeatActionLedger.over_quota).where(
            SeatActionLedger.created_at >= month_start
        )
    ).all()
    ongoing_quota = _metric(
        "seat_actions_month",
        "当月工作台动作数",
        value=len(month_rows),
        sample_size=len(month_rows),
        definition="seat_action_ledger 当月（UTC 自然月）行数；over_quota 行数见 detail",
    )
    ongoing_quota["detail"] = {"over_quota_rows": sum(1 for flag in month_rows if flag)}

    return {
        "generated_at": now.isoformat(),
        "sections": {
            "p0": [p0_confirm, p0_draft_ms, p0_sow, p0_senior],
            "p1_pilot": [p1_lite, p1_first_pass, p1_degraded],
            "ongoing": [ongoing_cost, ongoing_intercept, ongoing_quota],
        },
    }
