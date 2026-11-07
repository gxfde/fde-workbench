"""meetings 服务层：评审会编排 + 纪要封存 + agent 工具面（goal-d5，技术实施方案 §3.2/§6）。

编排中枢是主持人（PartyMode §4：定议题、控话轮、收敛纪要，不发表专业意见）；
agent 只是申请人——脑不能直接动手。全部 REST 写路径人工授权
（can_manage / can_view 沿既有纪律）；api_catalog 只收只读三条。

工具面（技术文档 §3.2「mcp_gateway 增量」按行为事实落点）：``dispatch_agent_tool``
是 agent 执行面的工具网关——三重白名单（enabled / allowed_tools 显式声明 /
capability 实时鉴权）、计费+占预算、每 run ≤2 次、denied 落 agent_tool_calls。
不进桌面 mcp_gateway TOOLS：那是用户 AI 对话面（actor=人、无 run_id 可挂
留痕），两个 actor 模型不同（goal-d5 报告 §二.7 登记）。

T2 强制门（U2）助手 ``t2_gate_satisfied``：agents 服务层在产物提交终审
（solution 绑定落库）前调用——无已封存强制纪要则迁移被拒（review_gate_open），
状态机级强制，非 prompt。goal-d7 扩展三强制门：T1 计划门（start_run 前置闸，
``t1_gate_satisfied``）/ T4 高难度加座（difficulty=high 的 run 召集强制门会
自动升 full 档 + 角色卡加座，门判定要求满档纪要）/ T5 降级恢复补审（家族含
L1 run 时门只认 T5 纪要）。自动纪要（Killjoy 收敛/超时收场/checklist 降级，
todos 带 auto 标记）永不作门证据。

编排中枢 authority（goal-d7）：add_turn 发言 agent 必须匹配会议到场表
（模板 attendees；gate_tier=full 时叠加 persona_addons 加座）——persona 只
经 ``persona:<key>`` 入场，泛标签（module_agent/quality_guard）对非 persona
可执行 agent 兼容（d5 语料零适配）。PM-2 三层防火墙系统级封存：persona
发言注入常驻徽标 + 处方话术拒收 + 专业结论只进待办段（固定文案前缀）。
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from typing import Any

from flask import current_app
from sqlalchemy import func, select

from fde_api.agents.models import AgentRegistry, AgentRun, AgentToolCall
from fde_api.agents.quota import record_action as record_seat_action
from fde_api.agents.seeds import PERSONA_CAPABILITY_PREFIX
from fde_api.auth.models import User
from fde_api.control.access import authorize_ai_capability
from fde_api.extensions import db
from fde_api.meetings.models import (
    GATE_TIERS,
    MEETING_TRIGGERS,
    ReviewMeeting,
    ReviewMeetingMinutes,
    ReviewMeetingTurn,
)
from fde_api.meetings.templates import (
    GATE_TIER_TURN_BUDGETS,
    MEETING_AGENT_TOOLS,
    MEETING_CONVENE_COST_UNITS,
    MEETING_CONVENE_LIMIT_PER_RUN,
    get_template,
    list_templates,
)
from fde_api.projects.events import record_event
from fde_api.projects.permissions import project_access, visible_project_ids
from fde_api.solutions.models import ProjectSolution
from fde_api.workbench.models import Project

_CONVENE_TOOL = "meeting_convene"
_MINUTES_TOOL = "meeting_get_minutes"

_TEXT_MAX = 2000
_TURN_TEXT_MAX = 4000
_REF_MAX = 160
_REFS_MAX = 20
_TOPIC_KEY_MAX = 20

# —— goal-d7 常量 ——
# PM-2 提示层（PartyMode §4.2）：persona 发言顶部常驻徽标（系统注入，UI
# 强制不可关闭；系统级封存——不靠客户端自觉）
PERSONA_DISCLAIMER = "AI 模拟视角，非专业意见"
# PM-2 内容层文案（PartyMode §4.2 固定文案）：persona 来源的专业结论只进
# 待办段，服务端强制前缀（系统级封存，非客户端文案）
PROFESSIONAL_TODO_PREFIX = "提交专业顾问确认："
# 自动纪要标记（决议 4）：Killjoy 收敛/超时收场/checklist 降级封存的纪要，
# todos 条目带 auto=true——永不作强制门证据（未完成评审 ≠ 评审完成）
AUTO_MINUTES_FLAG = "auto"
# M5 memlog：同项目二次开会自动引用最近已封存纪要（≤3 条，新→旧）
MEMLOG_PRIOR_LIMIT = 3


def _settings():
    return current_app.config["SETTINGS"]


class MeetingsServiceError(Exception):
    def __init__(self, code: str, message: str, status: int, detail: dict[str, Any] | None = None):
        super().__init__(message)
        self.code, self.message, self.status = code, message, status
        self.detail = detail or {}


def _error(code: str, message: str, status: int = 400, detail: dict[str, Any] | None = None) -> MeetingsServiceError:
    return MeetingsServiceError(code, message, status, detail)


def _load_project_for(session: Any, actor: User, project_id: str, *, manage: bool) -> Project:
    project = session.get(Project, project_id)
    access = project_access(actor, project) if project else None
    if project is None or access is None:
        raise _error("project_not_found", "项目不存在或无权访问。", 404)
    if manage and not access.can_manage:
        raise _error("project_forbidden", "需要项目管理权限。", 403)
    if not manage and not access.can_view:
        raise _error("project_forbidden", "无权访问该项目。", 403)
    return project


def _load_meeting_for(session: Any, actor: User, meeting_id: str, *, manage: bool) -> ReviewMeeting:
    meeting = session.get(ReviewMeeting, meeting_id)
    if meeting is None:
        raise _error("meeting_not_found", "评审会不存在。", 404)
    _load_project_for(session, actor, meeting.project_id, manage=manage)
    _reap_stale_meetings(session, project_id=meeting.project_id, actor=actor)
    return meeting


# ---------------------------------------------------------------------------
# 编排中枢 authority：到场表 / T4 升档 / memlog / 自动纪要（goal-d7）
# ---------------------------------------------------------------------------


def _meeting_roster(meeting: ReviewMeeting) -> list[str]:
    """会议到场表（模板 attendees；T4 升档为 full 档时叠加角色卡加座）。

    到场表是编排中枢的 authority：发言 agent 必须在册（决议 5）。
    """
    template = get_template(meeting.template_id) or {}
    roster = [str(item) for item in (template.get("attendees") or [])]
    if meeting.gate_tier == "full":
        roster.extend(str(item) for item in (template.get("persona_addons") or []))
    return roster


def _label_admits(label: str, agent: AgentRegistry) -> bool:
    """到场表标签是否接纳该发言 agent。

    persona 只经 ``persona:<key>`` 入场（**永不落入泛标签**——PM-2 边界）；
    泛标签 ``module_agent`` 对任何非 persona 可执行 agent 兼容（d5 语料零
    适配）；``quality_guard``/``module:<key>`` 按能力腿精确匹配。
    """
    tier = agent.capability_tier or ""
    if agent.kind == "persona":
        if not tier.startswith(PERSONA_CAPABILITY_PREFIX):
            return False
        return label == f"persona:{tier[len(PERSONA_CAPABILITY_PREFIX):]}"
    if label == "module_agent":
        return True
    if label == "quality_guard":
        return tier == "agent.quality_guard"
    if label.startswith("module:"):
        return tier == f"agent.module.{label[len('module:'):]}"
    return False


def _speaker_roster_ok(session: Any, meeting: ReviewMeeting, agent_id: str) -> bool:
    agent = session.get(AgentRegistry, agent_id)
    if agent is None:  # 存在性由调用方先查；此处兜底
        return False
    return any(_label_admits(label, agent) for label in _meeting_roster(meeting))


def _persona_speaker_refs(session: Any, meeting: ReviewMeeting) -> list[str]:
    """会中发言过的角色卡 speaker_ref 集（``persona:<agent_id>``）——PM-2
    第 3 层的封存扫描输入（专业结论只进待办段）。"""
    rows = session.execute(
        select(AgentRegistry.id)
        .join(ReviewMeetingTurn, ReviewMeetingTurn.speaker_agent_id == AgentRegistry.id)
        .where(ReviewMeetingTurn.meeting_id == meeting.id, AgentRegistry.kind == "persona")
    )
    return [f"persona:{row_id}" for row_id in rows.scalars()]


def _apply_t4_upgrade(meeting: ReviewMeeting, template: dict[str, Any], run: AgentRun | None) -> bool:
    """T4 高难度加座（总纲 §2.2 T4 + U10）：difficulty=high 的 run 召集
    强制门模板（min_difficulty=high）时自动升档——gate_tier→full（话轮预算
    12）+ persona_addons 三角色卡入座（到场表经 _meeting_roster 生效）。
    返回是否升档。决议 2：difficulty 由发起人声明、系统按声明强制门档。"""
    if run is None or run.difficulty != "high":
        return False
    if meeting.trigger != "mandatory" or template.get("min_difficulty") != "high":
        return False
    meeting.gate_tier = "full"
    meeting.turn_budget = int(GATE_TIER_TURN_BUDGETS["full"])
    meeting.min_difficulty = template.get("min_difficulty")
    return True


def _attach_prior_minutes(session: Any, project_id: str, topic_refs: dict[str, str]) -> None:
    """M5 memlog：同项目二次开会自动引用最近已封存纪要（新→旧 ≤3 条），
    落 topic_refs["prior_minutes"]（get_minutes 回链可见 = 计入纪要上下文）。"""
    latest = list(
        session.execute(
            select(ReviewMeetingMinutes.id)
            .join(ReviewMeeting, ReviewMeeting.id == ReviewMeetingMinutes.meeting_id)
            .where(ReviewMeeting.project_id == project_id)
            .order_by(ReviewMeetingMinutes.created_at.desc(), ReviewMeetingMinutes.id.desc())
            .limit(MEMLOG_PRIOR_LIMIT)
        )
        .scalars()
    )
    if latest:
        topic_refs["prior_minutes"] = ",".join(latest)[:255]


def _minutes_is_auto(minutes: ReviewMeetingMinutes | None) -> bool:
    """自动纪要标记检测（决议 4）：todos 任一条目带 auto=true 即自动封存。"""
    if minutes is None:
        return False
    return any(
        isinstance(item, dict) and item.get(AUTO_MINUTES_FLAG) is True
        for item in (minutes.todos or [])
    )


def _seal_auto_minutes(
    session: Any,
    *,
    actor: User,
    meeting: ReviewMeeting,
    event_name: str,
    consensus: list[dict[str, Any]] | None = None,
    disputes: list[dict[str, Any]] | None = None,
    todos: list[dict[str, Any]],
    event_detail: dict[str, Any] | None = None,
) -> ReviewMeetingMinutes:
    """自动封存未完成纪要（Killjoy 收敛 / M7 超时收场 / M8 checklist 降级）。

    三段式沿用人工封存契约（todos 条目带 auto 标记），meeting 落 degraded +
    closed；自动纪要永不作强制门证据（t2_gate_satisfied / U4 修订回路输入
    均排除——决议 4）。幂等：已封存/已关闭直接返回既有形态不重写。
    """
    existing = session.scalar(
        select(ReviewMeetingMinutes).where(ReviewMeetingMinutes.meeting_id == meeting.id)
    )
    if existing is not None:
        # 幂等：已封存不重写（auto 纪要不可变，沿人工封存心智）
        return existing
    normalized_todos = [{**item, AUTO_MINUTES_FLAG: True} for item in todos]
    digest = sha256(
        json.dumps(
            {
                "meeting_id": meeting.id,
                "consensus": consensus or [],
                "disputes": disputes or [],
                "todos": normalized_todos,
            },
            sort_keys=True,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    minutes = ReviewMeetingMinutes(
        meeting_id=meeting.id,
        consensus=consensus or [],
        disputes=disputes or [],
        todos=normalized_todos,
        sealed_sha256=digest,
    )
    session.add(minutes)
    meeting.status = "closed"
    meeting.degraded = True
    detail = {"meeting_id": meeting.id, "sealed_sha256": digest, "auto_minutes": True}
    if event_detail:
        detail.update(event_detail)
    record_event(session, actor, event_name, _project(session, meeting), detail)
    session.flush()
    return minutes


def _reap_stale_meetings(session: Any, *, project_id: str, actor: User) -> int:
    """M7 超时自动收场（懒收场，PartyMode §5.2）：live/paused 超过阈值小时
    无活动的会议自动收场出未完成纪要（auto 标记）。阈值
    FDE_MEETING_STALE_CLOSE_HOURS（默认 24h）。返回本轮收场数。"""
    settings = _settings()
    stale_hours = int(getattr(settings, "meeting_stale_close_hours", 24) or 24)
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=stale_hours)
    stale = list(
        session.scalars(
            select(ReviewMeeting)
            .where(
                ReviewMeeting.project_id == project_id,
                ReviewMeeting.status.in_(("live", "paused")),
                ReviewMeeting.updated_at <= cutoff,
            )
        )
    )
    for meeting in stale:
        _seal_auto_minutes(
            session,
            actor=actor,
            meeting=meeting,
            event_name="review_meeting_timeout_closed",
            disputes=[
                {
                    "positions": [
                        {"speaker": "主持人（系统）", "text": "会议超过中断恢复窗口（24h）无活动。", "source_refs": []},
                        {"speaker": "系统", "text": "按 M7 中断恢复规则自动收场，出未完成纪要。", "source_refs": []},
                    ],
                    "conflict": "中断超时：恢复窗口（≤24h）已过，会议自动收场",
                }
            ],
            todos=[
                {
                    "text": "超时自动收场：会议未完成评审，结论需人工补录或重新召集。",
                    "source_refs": [],
                }
            ],
            event_detail={"reason": "stale_timeout", "stale_hours": stale_hours},
        )
    return len(stale)


# ---------------------------------------------------------------------------
# 召集（人工开会 + 工具面 agent 召集共用主干）
# ---------------------------------------------------------------------------


def _validate_topic_refs(value: Any) -> dict[str, str]:
    if value is None:
        return {}
    if not isinstance(value, dict) or len(value) > _TOPIC_KEY_MAX:
        raise _error("invalid_request", "topic_refs 必须为 ≤20 键的对象。")
    refs: dict[str, str] = {}
    for key, item in value.items():
        if not isinstance(key, str) or not key or len(key) > 64 or not isinstance(item, str) or len(item) > 255:
            raise _error("invalid_request", "topic_refs 键值必须为短字符串。")
        refs[key] = item
    return refs


def _require_adhoc_reason(template: dict[str, Any], payload: dict[str, Any]) -> str | None:
    """U3：自主召集模板（requires_reason）必须带 reason（1..160），缺失即拒；
    非自主模板显式带 reason 同样拒（键集纪律）。reason 落 topic_refs 计入纪要。
    """
    reason = payload.get("reason")
    if template.get("requires_reason"):
        if not isinstance(reason, str) or not reason.strip():
            raise _error(
                "reason_required",
                "自主召集必须声明召集理由（reason 必填）。",
                400,
                detail={"template_id": template.get("template_id")},
            )
        reason = reason.strip()
        if len(reason) > 160:
            raise _error("invalid_request", "reason 必须为 ≤160 字符字符串。")
        return reason
    if reason is not None:
        raise _error("invalid_request", "该模板不接受 reason 字段。")
    return None


def _serialize_meeting(
    session: Any,
    meeting: ReviewMeeting,
    *,
    with_turns: bool = False,
    turns_count: int | None = None,
) -> dict[str, Any]:
    data: dict[str, Any] = {
        "id": meeting.id,
        "project_id": meeting.project_id,
        "template_id": meeting.template_id,
        "status": meeting.status,
        "gate_tier": meeting.gate_tier,
        "trigger": meeting.trigger,
        "topic_refs": dict(meeting.topic_refs or {}),
        "turn_budget": meeting.turn_budget,
        "hosted_by_user_id": meeting.hosted_by_user_id,
        "triggered_by_run_id": meeting.triggered_by_run_id,
        "convened_by_agent_id": meeting.convened_by_agent_id,
        "min_difficulty": meeting.min_difficulty,
        "degraded": meeting.degraded,
        "created_at": meeting.created_at.isoformat() if meeting.created_at else None,
    }
    turns: list[ReviewMeetingTurn] | None = None
    if turns_count is not None:
        # 列表面传入的预聚合计数（list_meetings 单条分组查询取得）——跳过逐行
        # SELECT 的 N+1。
        data["turns_count"] = turns_count
    else:
        turns = list(
            session.scalars(
                select(ReviewMeetingTurn)
                .where(ReviewMeetingTurn.meeting_id == meeting.id)
                .order_by(ReviewMeetingTurn.seq)
            )
        )
        data["turns_count"] = len(turns)
    if with_turns:
        if turns is None:
            turns = list(
                session.scalars(
                    select(ReviewMeetingTurn)
                    .where(ReviewMeetingTurn.meeting_id == meeting.id)
                    .order_by(ReviewMeetingTurn.seq)
                )
            )
        data["turns"] = [
            {
                "seq": turn.seq,
                "speaker_agent_id": turn.speaker_agent_id,
                "speaker_user_id": turn.speaker_user_id,
                "content": dict(turn.content or {}),
            }
            for turn in turns
        ]
    return data


def _serialize_minutes(minutes: ReviewMeetingMinutes) -> dict[str, Any]:
    return {
        "id": minutes.id,
        "meeting_id": minutes.meeting_id,
        "consensus": list(minutes.consensus or []),
        "disputes": list(minutes.disputes or []),
        "todos": list(minutes.todos or []),
        "sealed_sha256": minutes.sealed_sha256,
        "created_at": minutes.created_at.isoformat() if minutes.created_at else None,
    }


def _agent_convene_preflight(
    session: Any, *, actor: User, project: Project, agent_id: Any, run_id: Any
) -> tuple[AgentRegistry, AgentRun]:
    """三重白名单 + 限额/预算前置；任何拒绝都落 agent_tool_calls denied（U1，
    独立事务留痕——拒绝路径回滚不丢痕）。"""
    if run_id is None:
        raise _error("invalid_request", "工具面召集必须提供 triggered_by_run_id。")
    run = session.get(AgentRun, run_id)
    if run is None or run.project_id != project.id:
        # run 归属复核失败同样留痕（denied 必留痕红线）
        _record_denied_now(run_id=str(run_id), tool_name=_CONVENE_TOOL, capability="unknown", reason="run_not_found")
        raise _error("agent_run_not_found", "触发 run 不存在或不属于该项目。", 404)
    agent = session.get(AgentRegistry, agent_id) if isinstance(agent_id, str) else None
    if agent is None:
        _record_denied_now(run_id=run.id, tool_name=_CONVENE_TOOL, capability="unknown", reason="agent_not_found")
        raise _error("agent_not_found", "智能体不存在。", 404)
    capability = agent.capability_tier
    if not agent.enabled:
        _record_denied_now(run_id=run.id, tool_name=_CONVENE_TOOL, capability=capability, reason="agent_disabled")
        raise _error("agent_disabled", "智能体未启用，召集被拒。", 403, detail={"reason": "agent_disabled"})
    if _CONVENE_TOOL not in set(agent.allowed_tools or []):
        # U1：默认不在任何白名单——未显式声明的 agent 调用被拒且留痕
        _record_denied_now(run_id=run.id, tool_name=_CONVENE_TOOL, capability=capability, reason="not_in_allowlist")
        raise _error("not_in_allowlist", "meeting_convene 不在该智能体的声明白名单内。", 403,
                     detail={"reason": "not_in_allowlist"})
    decision = authorize_ai_capability(user=actor, capability="agent.meeting.convene", project=project)
    if not decision.allowed:
        _record_denied_now(run_id=run.id, tool_name=_CONVENE_TOOL, capability=capability,
                           reason=(decision.reason or "capability_missing"))
        raise _error(decision.reason or "capability_missing", "当前账号无权召集评审会。", 403)
    return agent, run


def _record_tool_call(
    session: Any, *, run_id: str, tool_name: str, capability: str, decision: str, reason: str | None
) -> None:
    session.add(
        AgentToolCall(
            run_id=run_id,
            tool_name=tool_name[:120],
            decision=decision,
            capability=(capability or "unknown")[:64],
            reason=reason[:120] if reason else None,
        )
    )


def _record_denied_now(*, run_id: str, tool_name: str, capability: str, reason: str) -> None:
    """denied 留痕走独立事务：拒绝路径整体回滚也绝不丢痕（denied 必留痕红线）。"""
    with db.session() as session, session.begin():
        session.add(
            AgentToolCall(
                run_id=run_id,
                tool_name=tool_name[:120],
                decision="denied",
                capability=(capability or "unknown")[:64],
                reason=reason[:120],
            )
        )


def _billing_and_quota(session: Any, *, run: AgentRun, capability: str) -> None:
    """计费+占预算（技术文档 §3.2）与每 run ≤2 次限额（U7）；拒绝独立留痕。

    goal-d7 O-3：工具面召集放行即落一条 meeting_convene 动作（seat 归集到
    触发 run 的发起人；人工开会不经此函数 = 不占额度）。"""
    convened = session.scalar(
        select(func.count())
        .select_from(ReviewMeeting)
        .where(ReviewMeeting.triggered_by_run_id == run.id)
    )
    if int(convened or 0) >= MEETING_CONVENE_LIMIT_PER_RUN:
        _record_denied_now(run_id=run.id, tool_name=_CONVENE_TOOL, capability=capability,
                           reason="convene_limit_exceeded")
        raise _error(
            "convene_limit_exceeded",
            "每个 run 最多召集 2 次评审会。",
            409,
            detail={"reason": "convene_limit_exceeded", "limit": MEETING_CONVENE_LIMIT_PER_RUN},
        )
    registry = session.get(AgentRegistry, run.agent_id)
    cap = registry.max_cost_units if registry else 0
    if cap and run.token_cost + MEETING_CONVENE_COST_UNITS > cap:
        _record_denied_now(run_id=run.id, tool_name=_CONVENE_TOOL, capability=capability,
                           reason="convene_budget_exhausted")
        raise _error(
            "convene_budget_exhausted",
            "召集计费将超出该 run 的预算上限，召集被拒。",
            409,
            detail={"reason": "convene_budget_exhausted", "max_cost_units": cap},
        )
    run.token_cost += MEETING_CONVENE_COST_UNITS
    # O-3：工具面召集 = 一场评审会 = 一次动作（seat 归集到触发 run 的发起人；
    # 人工开会不经本函数 = 不占额度——「人工不占 agent 限额」）
    record_seat_action(
        session,
        project_id=run.project_id,
        user_id=run.initiated_by_user_id,
        action_type="meeting_convene",
        ref_id=run.id,
        quota_monthly=int(getattr(_settings(), "seat_action_quota_monthly", 100) or 0),
    )


def create_meeting(*, actor: User, payload: dict[str, Any]) -> dict[str, Any]:
    """召集评审会（人工开会，或工具面经 agent_id 走三重白名单）。

    goal-d7：``mode="checklist"`` = M8 降级清单模式（智能体层不可用时整会
    降级为模板清单——建会即封 auto 纪要，静态 checklist 给创业者自查）。
    """
    allowed_keys = {"project_id", "template_id", "topic_refs", "solution_id", "triggered_by_run_id", "agent_id", "reason", "mode"}
    if set(payload) - allowed_keys:
        raise _error("invalid_request", "请求字段无效。")
    project_id = payload.get("project_id")
    template_id = payload.get("template_id")
    if not isinstance(project_id, str) or not project_id or not isinstance(template_id, str) or not template_id:
        raise _error("invalid_request", "project_id 与 template_id 必填。")
    template = get_template(template_id)
    if template is None:
        raise _error("meeting_template_not_found", "评审会模板不存在。", 404)
    agent_mode = "agent_id" in payload
    if agent_mode and payload.get("agent_id") is None:
        raise _error("invalid_request", "agent_id 不能为空。")
    if not agent_mode and payload.get("agent_id") is not None:
        raise _error("invalid_request", "agent_id 仅限工具面召集路径。")
    mode = payload.get("mode")
    if mode is not None and mode != "checklist":
        raise _error("invalid_request", "mode 仅支持 checklist（降级清单模式）。")
    if mode == "checklist" and agent_mode:
        raise _error("invalid_request", "checklist 降级模式仅限人工路径。")

    with db.session() as session, session.begin():
        manage = not agent_mode
        project = _load_project_for(session, actor, project_id, manage=manage)
        agent: AgentRegistry | None = None
        run: AgentRun | None = None
        if agent_mode:
            agent, run = _agent_convene_preflight(
                session, actor=actor, project=project, agent_id=payload.get("agent_id"),
                run_id=payload.get("triggered_by_run_id"),
            )
            _billing_and_quota(session, run=run, capability=agent.capability_tier)
        topic_refs = _validate_topic_refs(payload.get("topic_refs"))
        adhoc_reason = _require_adhoc_reason(template, payload)
        if adhoc_reason is not None:
            topic_refs["reason"] = adhoc_reason
        solution_id = payload.get("solution_id")
        if solution_id is not None:
            if not isinstance(solution_id, str) or not solution_id:
                raise _error("invalid_request", "solution_id 无效。")
            solution = session.get(ProjectSolution, solution_id)
            if solution is None or solution.project_id != project.id:
                raise _error("solution_not_found", "方案不存在或不属于该项目。", 404)
            topic_refs["solution_id"] = solution.id
        run_id = payload.get("triggered_by_run_id")
        run_row: AgentRun | None = None
        if not agent_mode and run_id is not None:
            run_row = session.get(AgentRun, run_id)
            if run_row is None or run_row.project_id != project.id:
                raise _error("agent_run_not_found", "触发 run 不存在或不属于该项目。", 404)
        # M5 memlog：同项目二次开会引用最近已封存纪要（先查后挂，避免
        # 新会把自己的纪要算进 prior）
        _attach_prior_minutes(session, project.id, topic_refs)
        meeting = ReviewMeeting(
            project_id=project.id,
            template_id=template["template_id"],
            status="live",
            topic_refs=topic_refs,
            turn_budget=int(template["turn_budget"]),
            hosted_by_user_id=actor.id,
            gate_tier=template["gate_tier"] if template["gate_tier"] in GATE_TIERS else "lite",
            trigger=template["trigger"] if template["trigger"] in MEETING_TRIGGERS else "manual",
            triggered_by_run_id=(
                run.id if agent_mode and run is not None else (run_id if isinstance(run_id, str) else None)
            ),
            convened_by_agent_id=agent.id if agent else None,
            min_difficulty=template.get("min_difficulty"),
        )
        session.add(meeting)
        # T4 高难度加座（U10）：difficulty=high 的触发 run + 强制门模板 →
        # 自动升 full 档 + 角色卡入座（人工/工具面两路同规则）
        _apply_t4_upgrade(meeting, template, run if agent_mode else run_row)
        if agent is not None and run is not None:
            _record_tool_call(session, run_id=run.id, tool_name=_CONVENE_TOOL,
                              capability=agent.capability_tier, decision="allowed", reason=None)
        record_event(
            session,
            actor,
            "review_meeting_convened",
            project,
            {
                "meeting_id": meeting.id,
                "template_id": meeting.template_id,
                "trigger": meeting.trigger,
                "triggered_by_run_id": meeting.triggered_by_run_id,
                "convened_by_agent_id": meeting.convened_by_agent_id,
                "t4_upgraded": meeting.gate_tier == "full",
            },
        )
        if mode == "checklist":
            # M8：降级清单模式——建会即封 auto 纪要（模板 checklist 步骤化为
            # 待办段），静态自查，绝不作门证据（决议 4）
            _seal_auto_minutes(
                session,
                actor=actor,
                meeting=meeting,
                event_name="review_meeting_checklist_mode",
                todos=[
                    {"text": f"[checklist] {item['action']}——{item['detail']}", "source_refs": []}
                    for item in _checklist_items(template)
                ],
                event_detail={"template_id": meeting.template_id},
            )
        session.flush()
        body = _serialize_meeting(session, meeting)
        if mode == "checklist":
            minutes = session.scalar(
                select(ReviewMeetingMinutes).where(ReviewMeetingMinutes.meeting_id == meeting.id)
            )
            if minutes is not None:
                body["minutes"] = _serialize_minutes(minutes)
                body["mode"] = "checklist"
        return body


# ---------------------------------------------------------------------------
# 话轮 / 收敛 / 纪要
# ---------------------------------------------------------------------------


def _validate_turn_content(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise _error("invalid_request", "content 必须为对象。")
    text = value.get("text")
    if not isinstance(text, str) or not text.strip() or len(text) > _TURN_TEXT_MAX:
        raise _error("invalid_request", "content.text 必填（≤4000 字符）。")
    content: dict[str, Any] = {"text": text}
    stance = value.get("stance")
    if stance is not None:
        if not isinstance(stance, str) or len(stance) > 16:
            raise _error("invalid_request", "stance 必须为 ≤16 字符字符串。")
        content["stance"] = stance
    refs = value.get("source_refs", [])
    if not isinstance(refs, list) or len(refs) > _REFS_MAX or any(
        not isinstance(ref, str) or not ref or len(ref) > _REF_MAX for ref in refs
    ):
        raise _error("invalid_request", "source_refs 必须为 ≤20 条短字符串。")
    content["source_refs"] = refs
    return content


def _persona_denylist_patterns() -> list[str]:
    """PM-2 内容层（PartyMode §4.2）：角色卡处方话术 denylist（Settings 可
    调；系统级抽查落点——persona 发言命中即拒收）。"""
    raw = str(getattr(_settings(), "persona_forbidden_patterns", "") or "")
    return [item.strip() for item in raw.split(",") if item.strip()]


def _normalize_turn_text(text: str) -> str:
    """Killjoy 复读检测的归一化：去首尾/压空白（保留大小写与标点——中英
    混排语料下空白归一已足够抓逐字复读）。"""
    return re.sub(r"\s+", "", text).strip()


def add_turn(*, actor: User, meeting_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    allowed_keys = {"speaker_agent_id", "speaker_user_id", "content"}
    if set(payload) - allowed_keys:
        raise _error("invalid_request", "请求字段无效。")
    agent_id = payload.get("speaker_agent_id")
    user_id = payload.get("speaker_user_id")
    if (agent_id is None) == (user_id is None):
        raise _error("invalid_request", "speaker_agent_id 与 speaker_user_id 二选一。")
    content = _validate_turn_content(payload.get("content"))
    with db.session() as session, session.begin():
        meeting = _load_meeting_for(session, actor, meeting_id, manage=True)
        if meeting.status != "live":
            raise _error("meeting_not_live", "会议已不在进行中，不能再发言。", 409)
        count = int(
            session.scalar(
                select(func.count()).select_from(ReviewMeetingTurn).where(ReviewMeetingTurn.meeting_id == meeting.id)
            )
            or 0
        )
        seq = count + 1
        # M6：话轮预算是硬墙——超限后唯一出路是收敛（close）；话轮内复读
        # 由 Killjoy 提前收题（本轮落地，见下方复读检测）
        if seq > meeting.turn_budget:
            raise _error(
                "turn_budget_exhausted",
                "话轮预算已用尽，请收敛纪要（close）。",
                409,
                detail={"turn_budget": meeting.turn_budget, "turns_count": count},
            )
        speaker_agent: AgentRegistry | None = None
        if agent_id is not None:
            speaker_agent = session.get(AgentRegistry, agent_id)
            if speaker_agent is None:
                raise _error("agent_not_found", "发言智能体不存在。", 404)
            # 编排中枢 authority（决议 5）：发言 agent 必须匹配会议到场表；
            # persona 永不落入泛标签（PM-2 边界），S6 空到场表 = 自由席
            if not _speaker_roster_ok(session, meeting, str(agent_id)):
                raise _error(
                    "speaker_not_in_roster",
                    "该智能体不在本会到场表内（编排中枢 authority）。",
                    403,
                    detail={"roster": _meeting_roster(meeting), "capability_tier": speaker_agent.capability_tier},
                )
        elif session.get(User, user_id) is None:
            raise _error("speaker_not_found", "发言用户不存在。", 404)
        if speaker_agent is not None and speaker_agent.kind == "persona":
            # PM-2 第 2 层：persona 禁令——只讲惯例不开处方，denylist 命中即拒
            for pattern in _persona_denylist_patterns():
                if pattern and pattern in content["text"]:
                    raise _error(
                        "persona_prescription_blocked",
                        "角色卡只讲行业惯例，不开处方（PM-2 防火墙）：发言含处方话术被拒。",
                        422,
                        detail={"persona_id": speaker_agent.id, "pattern": pattern},
                    )
            # PM-2 第 1 层：常驻徽标 + persona 标注系统注入（系统级封存，
            # 不靠客户端自觉；speaker_ref 供封存扫描定位 persona 来源）
            content["disclaimer"] = PERSONA_DISCLAIMER
            content["persona"] = True
            content["speaker_ref"] = f"persona:{speaker_agent.id}"
        turn = ReviewMeetingTurn(
            meeting_id=meeting.id,
            seq=seq,
            speaker_agent_id=agent_id if agent_id is not None else None,
            speaker_user_id=user_id if user_id is not None else None,
            content=content,
        )
        session.add(turn)
        record_event(session, actor, "review_meeting_turn_added", _project(session, meeting), {"meeting_id": meeting.id, "seq": seq})
        session.flush()
        body = _serialize_meeting(session, meeting, with_turns=True)
        # Killjoy 自动收敛（PartyMode §7）：重复论点检测——本轮发言与此前
        # 任一话轮逐字复读（归一化空白后）→ 主持人强制收题（自动封存未完成
        # 纪要）。对全部话轮生效（agent/人同规则，复读不分发言方）。
        normalized = _normalize_turn_text(content["text"])
        if normalized:
            prior_texts = [
                _normalize_turn_text(str((row.content or {}).get("text") or ""))
                for row in session.scalars(
                    select(ReviewMeetingTurn)
                    .where(
                        ReviewMeetingTurn.meeting_id == meeting.id,
                        ReviewMeetingTurn.seq < seq,
                    )
                )
            ]
            if any(text == normalized for text in prior_texts):
                _seal_auto_minutes(
                    session,
                    actor=actor,
                    meeting=meeting,
                    event_name="review_meeting_auto_converged",
                    disputes=[
                        {
                            "positions": [
                                {
                                    "speaker": "主持人（Killjoy）",
                                    "text": "检测到重复论点（逐字复读），按 Killjoy 规则强制收敛。",
                                    "source_refs": [],
                                },
                                {
                                    "speaker": "系统",
                                    "text": "话轮死循环防护：会议提前收题，结论待人工补录。",
                                    "source_refs": [],
                                },
                            ],
                            "conflict": "重复论点（复读）检测触发强制收敛",
                        }
                    ],
                    todos=[
                        {
                            "text": "主持人强制收敛：会议因重复论点提前收题，结论需人工补录或重新召集。",
                            "source_refs": [],
                        }
                    ],
                    event_detail={"seq": seq, "trigger": "killjoy_repetition"},
                )
                body = _serialize_meeting(session, meeting, with_turns=True)
                body["killjoy_converged"] = True
        return body


def _project(session: Any, meeting: ReviewMeeting) -> Project:
    project = session.get(Project, meeting.project_id)
    if project is None:  # FK RESTRICT 保证存在；mypy 收窄
        raise _error("project_not_found", "项目不存在。", 404)
    return project


def _validate_sections(payload: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """三段式契约：键集精确 {consensus, disputes, todos}；分歧条目必须保留
    双方论点并带冲突标注（M3：分歧点不被调和，原样保留）。"""
    if set(payload) != {"consensus", "disputes", "todos"}:
        raise _error("invalid_request", "纪要必须为三段式：consensus/disputes/todos。")

    def _refs(value: Any) -> list[str]:
        if not isinstance(value, list) or len(value) > _REFS_MAX or any(
            not isinstance(ref, str) or not ref or len(ref) > _REF_MAX for ref in value
        ):
            raise _error("invalid_request", "source_refs 必须为 ≤20 条短字符串。")
        return list(value)

    consensus: list[dict[str, Any]] = []
    if not isinstance(payload["consensus"], list) or len(payload["consensus"]) > 50:
        raise _error("invalid_request", "consensus 必须为 ≤50 条的列表。")
    for item in payload["consensus"]:
        if not isinstance(item, dict) or not isinstance(item.get("text"), str) or not item["text"].strip() or len(item["text"]) > _TEXT_MAX:
            raise _error("invalid_request", "共识条目必须带 text（≤2000 字符）。")
        consensus.append({"text": item["text"], "source_refs": _refs(item.get("source_refs", []))})

    disputes: list[dict[str, Any]] = []
    if not isinstance(payload["disputes"], list) or len(payload["disputes"]) > 50:
        raise _error("invalid_request", "disputes 必须为 ≤50 条的列表。")
    for item in payload["disputes"]:
        if not isinstance(item, dict):
            raise _error("invalid_request", "分歧条目必须为对象。")
        positions = item.get("positions")
        if not isinstance(positions, list) or len(positions) < 2 or len(positions) > 4:
            # M3：分歧双方论点原样保留（2–4 方），不允许调和成单点
            raise _error("invalid_dispute", "分歧条目必须保留 ≥2 方论点（positions）。")
        normalized: list[dict[str, Any]] = []
        for position in positions:
            if not isinstance(position, dict) or not isinstance(position.get("speaker"), str) or not position["speaker"].strip() or len(position["speaker"]) > 80:
                raise _error("invalid_request", "分歧论点必须带 speaker（≤80 字符）。")
            if not isinstance(position.get("text"), str) or not position["text"].strip() or len(position["text"]) > _TEXT_MAX:
                raise _error("invalid_request", "分歧论点必须带 text（≤2000 字符）。")
            normalized.append({"speaker": position["speaker"], "text": position["text"], "source_refs": _refs(position.get("source_refs", []))})
        conflict = item.get("conflict")
        if not isinstance(conflict, str) or not conflict.strip() or len(conflict) > _TEXT_MAX:
            raise _error("invalid_request", "分歧条目必须带冲突标注 conflict。")
        disputes.append({"positions": normalized, "conflict": conflict})

    todos: list[dict[str, Any]] = []
    if not isinstance(payload["todos"], list) or len(payload["todos"]) > 50:
        raise _error("invalid_request", "todos 必须为 ≤50 条的列表。")
    for item in payload["todos"]:
        if not isinstance(item, dict) or not isinstance(item.get("text"), str) or not item["text"].strip() or len(item["text"]) > _TEXT_MAX:
            raise _error("invalid_request", "待办条目必须带 text（≤2000 字符）。")
        todo = {"text": item["text"], "source_refs": _refs(item.get("source_refs", []))}
        owner = item.get("owner")
        if owner is not None:
            if not isinstance(owner, str) or len(owner) > 80:
                raise _error("invalid_request", "owner 必须为 ≤80 字符字符串。")
            todo["owner"] = owner
        todos.append(todo)
    return consensus, disputes, todos


def _mark_meeting_degraded_now(meeting_id: str) -> None:
    """守卫拒封存标 degraded（独立事务，拒绝回滚不丢标注；技术文档 §6）。"""
    with db.session() as session, session.begin():
        row = session.get(ReviewMeeting, meeting_id)
        if row is not None:
            row.degraded = True


def close_meeting(*, actor: User, meeting_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    """收敛纪要：三段式 + 守卫复核引用闭合 + sealed_sha256 封存（不可变）。"""
    if not isinstance(payload, dict):
        raise _error("invalid_request", "请求内容必须为 JSON 对象。")
    consensus, disputes, todos = _validate_sections(payload)
    with db.session() as session, session.begin():
        meeting = _load_meeting_for(session, actor, meeting_id, manage=True)
        existing = session.scalar(select(ReviewMeetingMinutes).where(ReviewMeetingMinutes.meeting_id == meeting.id))
        if existing is not None:
            raise _error("minutes_already_sealed", "纪要已封存，不可重写。", 409)
        if meeting.status != "live":
            raise _error("meeting_not_live", "会议已结束，不能再收敛。", 409)
        # 守卫复核（技术文档 §6）：纪要引用必须闭合于评审输入（topic_refs +
        # 全部话轮 source_refs）；失败拒封存标 degraded，人工补正后重试
        turns = list(
            session.scalars(select(ReviewMeetingTurn).where(ReviewMeetingTurn.meeting_id == meeting.id))
        )
        known: set[str] = {str(value) for value in (meeting.topic_refs or {}).values()}
        for turn in turns:
            refs = (turn.content or {}).get("source_refs")
            if isinstance(refs, list):
                known.update(ref for ref in refs if isinstance(ref, str))
        # persona speaker_ref（PM-2 第 1 层系统注入）是合法引用源——可入
        # 待办段 source_refs（第 3 层扫描的定位键）
        known.update(_persona_speaker_refs(session, meeting))
        sections = {"consensus": consensus, "disputes": disputes, "todos": todos}
        unknown: set[str] = set()
        for section in sections.values():
            for item in section:
                for ref in item.get("source_refs", []):
                    if ref not in known:
                        unknown.add(ref)
                for position in item.get("positions", []) or ():
                    for ref in position.get("source_refs", []):
                        if ref not in known:
                            unknown.add(ref)
        if unknown:
            # 拒封存标 degraded（独立事务——本次拒绝回滚不丢标注），人工补正后重试
            _mark_meeting_degraded_now(meeting.id)
            raise _error(
                "source_ref_unknown",
                "纪要引用未闭合（守卫复核失败），已标 degraded；请补正后重试。",
                422,
                detail={"unknown_refs": sorted(unknown)[:20]},
            )
        # PM-2 第 3 层（系统级封存）：角色卡来源的专业结论只进待办段——
        # persona speaker_ref 出现在共识/分歧段 → 拒封存；出现在待办段 →
        # 服务端固定文案前缀（「提交专业顾问确认：」，PartyMode §4.2）
        persona_refs = set(_persona_speaker_refs(session, meeting))
        if persona_refs:
            misplaced: list[str] = []
            for item in consensus + disputes:
                refs = set(item.get("source_refs") or [])
                for position in item.get("positions", []) or ():
                    refs.update(position.get("source_refs") or [])
                misplaced.extend(sorted(refs & persona_refs))
            if misplaced:
                _mark_meeting_degraded_now(meeting.id)
                raise _error(
                    "persona_conclusion_misplaced",
                    "角色卡视角不能进共识/分歧段（PM-2：专业结论只进待办段）；"
                    "请移入待办段，由服务端补「提交专业顾问确认」前缀。",
                    422,
                    detail={"persona_refs": sorted(set(misplaced))[:20]},
                )
            for item in todos:
                refs = set(item.get("source_refs") or [])
                if refs & persona_refs and not str(item.get("text", "")).startswith(PROFESSIONAL_TODO_PREFIX):
                    item["text"] = (PROFESSIONAL_TODO_PREFIX + str(item["text"]))[:_TEXT_MAX]
        digest = sha256(
            json.dumps(
                {"meeting_id": meeting.id, "consensus": consensus, "disputes": disputes, "todos": todos},
                sort_keys=True,
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        minutes = ReviewMeetingMinutes(
            meeting_id=meeting.id,
            consensus=consensus,
            disputes=disputes,
            todos=todos,
            sealed_sha256=digest,
        )
        session.add(minutes)
        meeting.status = "closed"
        record_event(
            session,
            actor,
            "review_meeting_sealed",
            _project(session, meeting),
            {"meeting_id": meeting.id, "sealed_sha256": digest, "triggered_by_run_id": meeting.triggered_by_run_id},
        )
        session.flush()
        return _serialize_minutes(minutes)


def list_meetings(*, actor: User, project_id: str | None, limit: int, offset: int) -> dict[str, Any]:
    """会议列表（T-A8 桌面控制台数据源，只读）。

    - project_id 给定：can_view 闸（局外人 403）；未给定：跨「actor 可见项目」
      聚合——可见性单一权威是 `projects.permissions.visible_project_ids`。
    - 列表行不带话轮正文（防 N+1）：话轮计数走单条分组查询预聚合，正文走
      既有会议详情端点按需取；纪要走 /meetings/<id>/minutes。
    - 有界分页：取 limit+1 行判定 truncated（诚实标记可能还有更多）。
    """
    with db.session() as session:
        if project_id is not None:
            project = _load_project_for(session, actor, project_id, manage=False)
            scope = ReviewMeeting.project_id == project.id
        else:
            scope = ReviewMeeting.project_id.in_(visible_project_ids(session, actor))
        rows = list(
            session.scalars(
                select(ReviewMeeting)
                .where(scope)
                .order_by(ReviewMeeting.created_at.desc(), ReviewMeeting.id.desc())
                .offset(offset)
                .limit(limit + 1)
            )
        )
        truncated = len(rows) > limit
        rows = rows[:limit]
        counts: dict[str, int] = {}
        if rows:
            counts = {
                meeting_id: count
                for meeting_id, count in session.execute(
                    select(ReviewMeetingTurn.meeting_id, func.count())
                    .where(ReviewMeetingTurn.meeting_id.in_([row.id for row in rows]))
                    .group_by(ReviewMeetingTurn.meeting_id)
                ).all()
            }
        items = [
            _serialize_meeting(session, row, with_turns=False, turns_count=counts.get(row.id, 0))
            for row in rows
        ]
        return {"items": items, "truncated": truncated}


def get_meeting(*, actor: User, meeting_id: str) -> dict[str, Any]:
    with db.session() as session:
        meeting = _load_meeting_for(session, actor, meeting_id, manage=False)
        return _serialize_meeting(session, meeting, with_turns=True)


def get_minutes(*, actor: User, meeting_id: str) -> dict[str, Any]:
    """纪要（含溯源回链：triggered_by_run_id / topic_refs，M2 反查链的会议段）。"""
    with db.session() as session:
        meeting = _load_meeting_for(session, actor, meeting_id, manage=False)
        minutes = session.scalar(select(ReviewMeetingMinutes).where(ReviewMeetingMinutes.meeting_id == meeting.id))
        if minutes is None:
            raise _error("minutes_not_sealed", "纪要尚未封存。", 409)
        data = _serialize_minutes(minutes)
        data["triggered_by_run_id"] = meeting.triggered_by_run_id
        data["topic_refs"] = dict(meeting.topic_refs or {})
        data["convened_by_agent_id"] = meeting.convened_by_agent_id
        return data


def list_meeting_templates() -> dict[str, Any]:
    return {"items": list_templates()}


def _checklist_items(template: dict[str, Any]) -> list[dict[str, Any]]:
    """模板 → 静态人工执行单步骤（U9 checklist 与 M8 checklist 建会共用）。"""
    section_labels = {"consensus": "共识", "disputes": "分歧", "todos": "待办"}
    items: list[dict[str, Any]] = [
        {"step": 1, "action": "确认评审范围与产物清单", "detail": "按 topic_refs 圈定产物（storage_ref + sha256）"},
    ]
    for offset, attendee in enumerate(template.get("attendees", []), start=2):
        items.append({"step": offset, "action": f"由 {attendee} 角色逐项检查产物", "detail": "检查意见记入对应话轮/记录"})
    step = len(items) + 1
    for section in template.get("sections", []):
        items.append(
            {
                "step": step,
                "action": f"整理{section_labels.get(str(section), str(section))}段",
                "detail": "分歧条目须 ≥2 方论点并标注冲突（M3）",
            }
        )
        step += 1
    items.append({"step": step, "action": "人工拍板并封存结论", "detail": "证据按 source_uri 指针 + sha256 指针留证，绝不入库原件"})
    return items


def get_template_checklist(template_id: str) -> dict[str, Any]:
    """U9：强制门模板降级为静态 checklist（智能体层不可用时不阻塞交付）。

    模板的 attendees/sections 是门禁语义，checklist 是其人工执行形态：
    逐条可勾选的步骤单，人按单执行并留证（门禁证据通道 source_uri+sha256）。
    """
    template = get_template(template_id)
    if template is None:
        raise _error("meeting_template_not_found", "评审会模板不存在。", 404)
    return {
        "template_id": template["template_id"],
        "gate": template["gate"],
        "trigger": template["trigger"],
        "mode": "manual_checklist",
        "items": _checklist_items(template),
    }


# ---------------------------------------------------------------------------
# M7 中断恢复 / M9 会议成本（goal-d7）
# ---------------------------------------------------------------------------


def pause_meeting(*, actor: User, meeting_id: str) -> dict[str, Any]:
    """M7：主持人暂停会议（中断）。恢复窗口 = meeting_stale_close_hours
    （默认 24h）；窗口内 resume 复活，超窗自动收场（懒 reap）。"""
    with db.session() as session, session.begin():
        meeting = _load_meeting_for(session, actor, meeting_id, manage=True)
        if meeting.status != "live":
            raise _error("meeting_not_live", "仅进行中的会议可暂停。", 409)
        meeting.status = "paused"
        record_event(session, actor, "review_meeting_paused", _project(session, meeting), {"meeting_id": meeting.id})
        session.flush()
        return _serialize_meeting(session, meeting)


def resume_meeting(*, actor: User, meeting_id: str) -> dict[str, Any]:
    """M7：恢复暂停的会议——≤24h（恢复窗口）内复活；超窗自动收场并 409
    （PartyMode §5.2：中断恢复 ≤24h，超时自动收场出未完成纪要）。"""
    with db.session() as session, session.begin():
        meeting = _load_meeting_for(session, actor, meeting_id, manage=True)
        if meeting.status == "live":
            return _serialize_meeting(session, meeting)
        if meeting.status == "closed":
            # 懒收场（M7 reaper）已把它关掉：若纪要是 auto（超时收场产物），
            # 恢复被拒的准确原因就是「恢复窗口已过」；人工收敛则普通拒绝
            minutes = session.scalar(
                select(ReviewMeetingMinutes).where(ReviewMeetingMinutes.meeting_id == meeting.id)
            )
            if minutes is not None and _minutes_is_auto(minutes):
                raise _error(
                    "meeting_resume_expired",
                    "暂停已超过恢复窗口（24h），会议已自动收场并出未完成纪要。",
                    409,
                    detail={"meeting_id": meeting.id},
                )
            raise _error("meeting_not_resumable", "会议已结束，不可恢复。", 409)
        if meeting.status != "paused":
            raise _error("meeting_not_resumable", "会议已结束，不可恢复。", 409)
        settings = _settings()
        stale_hours = int(getattr(settings, "meeting_stale_close_hours", 24) or 24)
        updated = meeting.updated_at
        expired = updated is None or (
            datetime.now(timezone.utc) - (updated if updated.tzinfo else updated.replace(tzinfo=timezone.utc))
        ) > timedelta(hours=stale_hours)
        if expired:
            # 超窗：自动收场出未完成纪要（auto 标记，不作门证据），恢复被拒
            _seal_auto_minutes(
                session,
                actor=actor,
                meeting=meeting,
                event_name="review_meeting_timeout_closed",
                disputes=[
                    {
                        "positions": [
                            {"speaker": "主持人（系统）", "text": "暂停超过中断恢复窗口（24h）。", "source_refs": []},
                            {"speaker": "系统", "text": "按 M7 中断恢复规则自动收场，出未完成纪要。", "source_refs": []},
                        ],
                        "conflict": "中断超时：恢复窗口（≤24h）已过，会议自动收场",
                    }
                ],
                todos=[
                    {"text": "超时自动收场：会议未完成评审，结论需人工补录或重新召集。", "source_refs": []}
                ],
                event_detail={"reason": "resume_expired", "stale_hours": stale_hours},
            )
            raise _error(
                "meeting_resume_expired",
                "暂停已超过恢复窗口（24h），会议已自动收场并出未完成纪要。",
                409,
                detail={"meeting_id": meeting.id},
            )
        meeting.status = "live"
        record_event(session, actor, "review_meeting_resumed", _project(session, meeting), {"meeting_id": meeting.id})
        session.flush()
        return _serialize_meeting(session, meeting)


def get_meeting_cost(*, actor: User, meeting_id: str) -> dict[str, Any]:
    """M9：成本按会议归集可查（沿用 M-1 成本口径——会议计费落触发 run，
    单会视角 = 召集计费 + 触发 run 累计；话轮/收敛计费随 U6 全量归集挂账）。"""
    with db.session() as session:
        meeting = _load_meeting_for(session, actor, meeting_id, manage=False)
        convene_cost = MEETING_CONVENE_COST_UNITS if meeting.convened_by_agent_id is not None else 0
        turns_count = int(
            session.scalar(
                select(func.count()).select_from(ReviewMeetingTurn).where(ReviewMeetingTurn.meeting_id == meeting.id)
            )
            or 0
        )
        run_total: int | None = None
        if meeting.triggered_by_run_id is not None:
            run = session.get(AgentRun, meeting.triggered_by_run_id)
            run_total = int(run.token_cost) if run is not None else None
        return {
            "meeting_id": meeting.id,
            "template_id": meeting.template_id,
            "convened_by_agent_id": meeting.convened_by_agent_id,
            "triggered_by_run_id": meeting.triggered_by_run_id,
            "convene_cost_units": convene_cost,
            "turns_count": turns_count,
            "total_cost_units": convene_cost,
            "triggering_run_token_cost": run_total,
        }


# ---------------------------------------------------------------------------
# agent 工具面（技术文档 §3.2：meeting_convene / meeting_get_minutes）
# ---------------------------------------------------------------------------


def dispatch_agent_tool(
    *, actor: User, agent_id: str, run_id: str, tool_name: str, payload: dict[str, Any]
) -> dict[str, Any]:
    """agent 执行面工具网关：会中全角色只读（U8/M4），面外工具一律 denied 留痕。"""
    with db.session() as session, session.begin():
        agent = session.get(AgentRegistry, agent_id)
        if agent is None:
            raise _error("agent_not_found", "智能体不存在。", 404)
        run = session.get(AgentRun, run_id)
        if run is None or run.agent_id != agent.id:
            raise _error("agent_run_not_found", "run 不存在或不属于该智能体。", 404)
        project = session.get(Project, run.project_id)
        if project is None:  # FK RESTRICT 保证存在；mypy 收窄
            raise _error("project_not_found", "项目不存在。", 404)
        if tool_name not in MEETING_AGENT_TOOLS:
            # U8/M4（d5 切片）：会中工具面恒等只读二面，写类/面外一律拒绝留痕
            _record_denied_now(run_id=run.id, tool_name=tool_name, capability=agent.capability_tier,
                               reason="not_in_meeting_surface")
            raise _error(
                "tool_not_in_meeting_surface",
                "会中只读：该工具不在评审会工具面内。",
                403,
                detail={"reason": "not_in_meeting_surface"},
            )
        if tool_name == _CONVENE_TOOL:
            _agent_convene_preflight(session, actor=actor, project=project, agent_id=agent.id, run_id=run.id)
            _billing_and_quota(session, run=run, capability=agent.capability_tier)
            template = get_template(str(payload.get("template_id", "")))
            if template is None:
                raise _error("meeting_template_not_found", "评审会模板不存在。", 404)
            topic_refs = _validate_topic_refs(payload.get("topic_refs"))
            adhoc_reason = _require_adhoc_reason(template, payload)
            if adhoc_reason is not None:
                topic_refs["reason"] = adhoc_reason
            # M5 memlog：同项目二次开会引用最近已封存纪要（工具面同规则）
            _attach_prior_minutes(session, project.id, topic_refs)
            meeting = ReviewMeeting(
                project_id=project.id,
                template_id=template["template_id"],
                status="live",
                topic_refs=topic_refs,
                turn_budget=int(template["turn_budget"]),
                hosted_by_user_id=actor.id,
                gate_tier=template["gate_tier"],
                trigger=template["trigger"],
                triggered_by_run_id=run.id,
                convened_by_agent_id=agent.id,
                min_difficulty=template.get("min_difficulty"),
            )
            session.add(meeting)
            # T4 高难度加座（U10）：工具面召集与人工路径同规则
            _apply_t4_upgrade(meeting, template, run)
            _record_tool_call(session, run_id=run.id, tool_name=_CONVENE_TOOL,
                              capability=agent.capability_tier, decision="allowed", reason=None)
            record_event(
                session,
                actor,
                "review_meeting_convened",
                project,
                {"meeting_id": meeting.id, "template_id": meeting.template_id, "trigger": meeting.trigger,
                 "triggered_by_run_id": run.id, "convened_by_agent_id": agent.id,
                 "t4_upgraded": meeting.gate_tier == "full"},
            )
            session.flush()
            return {"tool": _CONVENE_TOOL, "meeting": _serialize_meeting(session, meeting)}
        # meeting_get_minutes：会话内自动可读自己触发的纪要（技术文档 §3.2）
        minutes_meeting_id = payload.get("meeting_id")
        minutes_meeting = (
            session.get(ReviewMeeting, minutes_meeting_id) if isinstance(minutes_meeting_id, str) else None
        )
        if minutes_meeting is None or minutes_meeting.project_id != project.id:
            _record_denied_now(run_id=run.id, tool_name=_MINUTES_TOOL, capability=agent.capability_tier,
                               reason="meeting_not_found")
            raise _error("meeting_not_found", "评审会不存在或不属于该项目。", 404)
        if minutes_meeting.convened_by_agent_id != agent.id:
            _record_denied_now(run_id=run.id, tool_name=_MINUTES_TOOL, capability=agent.capability_tier,
                               reason="minutes_not_owned")
            raise _error("minutes_not_owned", "只能读取自己触发的评审会纪要。", 403)
        minutes = session.scalar(
            select(ReviewMeetingMinutes).where(ReviewMeetingMinutes.meeting_id == minutes_meeting.id)
        )
        if minutes is None:
            _record_denied_now(run_id=run.id, tool_name=_MINUTES_TOOL, capability=agent.capability_tier,
                               reason="minutes_not_sealed")
            raise _error("minutes_not_sealed", "纪要尚未封存。", 409)
        _record_tool_call(session, run_id=run.id, tool_name=_MINUTES_TOOL,
                          capability=agent.capability_tier, decision="allowed", reason=None)
        return {"tool": _MINUTES_TOOL, "minutes": _serialize_minutes(minutes)}


# ---------------------------------------------------------------------------
# T2 强制门（U2）助手：agents 服务层产物提交终审前调用
# ---------------------------------------------------------------------------


def t2_gate_satisfied(session: Any, *, run_id: str, solution_id: str | None) -> bool:
    """已封存的强制评审纪要是否存在（run 直链/家流域 triggered_by_run_id，或
    topic_refs.solution_id 侧链）。无则迁移被拒 → review_gate_open。

    家流域：纪要挂在被门拦下的那次 run（run1）上，重试 run（run2，同幂等
    键家族）同样视为已评审——评审针对产物与方案，不针对单次尝试。

    goal-d7 三门扩展（状态机级，非 prompt）：
    - auto 纪要排除：Killjoy 收敛/超时收场/checklist 降级的未完成纪要永不
      放行（决议 4）。
    - T4（U10）：difficulty=high 的 run，满足门的纪要必须出自满档（full）
      且带加座的强制门模板——lite 纪要放不高难度的 run。
    - T5：家族含 L1 降级 run（降级恢复）时，满足门的纪要必须出自 T5 模板
      （补审）——降级期间产物不自动放行（自动交付 §3.3）。
    """
    family_ids = {run_id}
    run = session.get(AgentRun, run_id)
    if run is not None and run.idempotency_key:
        family_ids.update(
            session.scalars(select(AgentRun.id).where(AgentRun.idempotency_key == run.idempotency_key))
        )
    difficulty = str(getattr(run, "difficulty", None) or "standard")
    l1_recovery = any(
        row.fallback_level == "L1"
        for row in session.scalars(select(AgentRun).where(AgentRun.id.in_(family_ids)))
    )
    rows = list(
        session.execute(
            select(ReviewMeeting, ReviewMeetingMinutes)
            .join(ReviewMeetingMinutes, ReviewMeetingMinutes.meeting_id == ReviewMeeting.id)
            .where(ReviewMeeting.trigger == "mandatory")
        )
    )
    for meeting, minutes in rows:
        if _minutes_is_auto(minutes):
            continue
        linked = meeting.triggered_by_run_id in family_ids or (
            solution_id is not None
            and str((meeting.topic_refs or {}).get("solution_id") or "") == solution_id
        )
        if not linked:
            continue
        template = get_template(meeting.template_id) or {}
        if template.get("gate") == "T1":
            continue  # T1（计划评审）纪要不满足 T2（产物评审）——两门语义分离
        if difficulty == "high" and (
            meeting.gate_tier != "full" or template.get("min_difficulty") != "high"
        ):
            continue  # T4：高难度 run 需满档加座纪要
        if l1_recovery and template.get("gate") != "T5":
            continue  # T5：降级恢复家族只认补审纪要
        return True
    return False


def t1_gate_satisfied(session: Any, *, solution_id: str) -> bool:
    """T1 计划评审强制门（总纲 §2.2 T1，goal-d7）：start_run 带 solution_id
    的前置闸——须存在已封存 T1 模板强制纪要侧链该 solution（topic_refs.
    solution_id）。pre-run 无 run 家族可言；agent 自动召集 T1 走「规划 run
    先行」路径（规划 run 经工具面召集并声明 solution_id）。auto 纪要排除。
    """
    rows = list(
        session.execute(
            select(ReviewMeeting, ReviewMeetingMinutes)
            .join(ReviewMeetingMinutes, ReviewMeetingMinutes.meeting_id == ReviewMeeting.id)
            .where(ReviewMeeting.trigger == "mandatory")
        )
    )
    for meeting, minutes in rows:
        if _minutes_is_auto(minutes):
            continue
        template = get_template(meeting.template_id) or {}
        if template.get("gate") != "T1":
            continue
        if str((meeting.topic_refs or {}).get("solution_id") or "") == solution_id:
            return True
    return False


def t6_gate_satisfied(session: Any, *, project_id: str) -> bool:
    """T6 高成本 run 前评审强制门（总纲 §2.2 T6，goal-d11）：max_cost_units
    超阈值档的 run，start_run 前置闸——须存在已封存 T6 模板强制纪要侧链该
    项目（topic_refs.project_id）。评审对象是「项目内高成本 run 的性价比」，
    同项目评审一次即放行后续 run。auto 纪要排除（决议 4：自动收敛纪要不作
    强制门证据）。
    """
    rows = list(
        session.execute(
            select(ReviewMeeting, ReviewMeetingMinutes)
            .join(ReviewMeetingMinutes, ReviewMeetingMinutes.meeting_id == ReviewMeeting.id)
            .where(ReviewMeeting.trigger == "mandatory")
        )
    )
    for meeting, minutes in rows:
        if _minutes_is_auto(minutes):
            continue
        template = get_template(meeting.template_id) or {}
        if template.get("gate") != "T6":
            continue
        if str((meeting.topic_refs or {}).get("project_id") or "") == project_id:
            return True
    return False


def latest_sealed_mandatory_minutes(
    session: Any, *, run_id: str, idempotency_key: str | None
) -> ReviewMeetingMinutes | None:
    """U4 修订回路：run 家族（直链 + 同幂等键）关联的**最新**已封存强制纪要；
    无则 None。disputes 非空 = 存在未决分歧 → 修订升级人工。auto 纪要排除
    （未完成的自动收敛纪要不是修订回路输入，决议 4）。
    """
    family_ids = {run_id}
    if idempotency_key:
        family_ids.update(
            session.scalars(select(AgentRun.id).where(AgentRun.idempotency_key == idempotency_key))
        )
    for minutes, meeting in session.execute(
        select(ReviewMeetingMinutes, ReviewMeeting)
        .join(ReviewMeeting, ReviewMeeting.id == ReviewMeetingMinutes.meeting_id)
        .where(ReviewMeeting.trigger == "mandatory", ReviewMeeting.triggered_by_run_id.in_(family_ids))
        .order_by(ReviewMeetingMinutes.created_at.desc(), ReviewMeetingMinutes.id.desc())
    ):
        if _minutes_is_auto(minutes):
            continue
        return minutes
    return None
