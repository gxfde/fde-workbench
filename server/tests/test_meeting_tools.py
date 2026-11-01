"""goal-d5：agent 工具面——三重白名单 / 计费占预算 / 每 run ≤2 次 / 只读面。

U1：meeting_convene 经三重白名单生效；未声明 agent 调用被拒且留痕。
U7：每 run 2 次召集限额生效。
U8/M4（d5 切片）：会中全角色（含召集 agent）只读，面外/写类工具一律 denied。
"""
from __future__ import annotations

from uuid import uuid4

import pytest

from test_agents_d4_harness import api_client, seed_agent
from test_agents_d4_harness import d4_app, d4_client, d4_settings  # noqa: F401  (pytest fixture)
from test_document_drafts_api import _persist_project

from fde_api.agents.models import AgentRun, AgentToolCall
from fde_api.meetings.service import MeetingsServiceError, dispatch_agent_tool
from fde_api.meetings.templates import MEETING_AGENT_TOOLS

_MINUTES_OK = {
    "consensus": [{"text": "通过", "source_refs": []}],
    "disputes": [],
    "todos": [],
}


def _setup(db_session, d4_client, d4_settings, *, allowed=("meeting_convene",), max_cost_units: int = 0):
    leader = api_client(d4_client, db_session, d4_settings, "project_lead")
    project = _persist_project(db_session, leader.user, code=f"D5T{uuid4().hex[:6]}")
    agent = seed_agent(
        db_session,
        d4_settings,
        allowed_tools=("read_file", *allowed),
        max_cost_units=max_cost_units,
    )
    return leader, project, agent


def _seed_run(db_session, project, leader, agent) -> AgentRun:
    run = AgentRun(
        project_id=project.id,
        agent_id=agent.id,
        initiated_by_user_id=leader.user.id,
        capability_used=agent.capability_tier,
        status="running",
        context_ref="agent-workspaces/x/context.md",
        idempotency_key=f"tool:{uuid4().hex}",
    )
    db_session.add(run)
    db_session.commit()
    return run


def _denied_rows(db_session, run_id: str, tool: str) -> list[AgentToolCall]:
    return list(
        db_session.execute(
            AgentToolCall.__table__.select().where(
                AgentToolCall.run_id == run_id,
                AgentToolCall.tool_name == tool,
                AgentToolCall.decision == "denied",
            )
        )
    )


def test_meeting_surface_is_readonly_pair() -> None:
    """M4/U8 面断言：会中工具面恒等只读二面——无任何写类工具。"""
    assert MEETING_AGENT_TOOLS == frozenset({"meeting_convene", "meeting_get_minutes"})


def test_out_of_surface_tool_denied_and_recorded_u8(db_session, d4_client, d4_settings, d4_app) -> None:
    """U8：面外工具（写类）一律拒绝且留痕——脑不能直接动手。"""
    leader, project, agent = _setup(db_session, d4_client, d4_settings)
    run = _seed_run(db_session, project, leader, agent)
    with d4_app.app_context():
        with pytest.raises(MeetingsServiceError) as excinfo:
            dispatch_agent_tool(
                actor=leader.user, agent_id=agent.id, run_id=run.id,
                tool_name="file.write", payload={"path": "x"},
            )
        error = excinfo.value
        assert error.code == "tool_not_in_meeting_surface" and error.status == 403
    rows = _denied_rows(db_session, run.id, "file.write")
    assert len(rows) == 1 and rows[0].reason == "not_in_meeting_surface"


def test_convene_without_allowlist_declaration_denied_u1(db_session, d4_client, d4_settings, d4_app) -> None:
    """U1：默认不在任何白名单——未显式声明的 agent 调用被拒且留痕。"""
    leader, project, agent = _setup(db_session, d4_client, d4_settings, allowed=())
    run = _seed_run(db_session, project, leader, agent)
    with d4_app.app_context():
        with pytest.raises(MeetingsServiceError) as excinfo:
            dispatch_agent_tool(
                actor=leader.user, agent_id=agent.id, run_id=run.id,
                tool_name="meeting_convene",
                payload={"template_id": "T2-lite"},
            )
        assert excinfo.value.code == "not_in_allowlist" and excinfo.value.status == 403
    rows = _denied_rows(db_session, run.id, "meeting_convene")
    assert len(rows) == 1 and rows[0].reason == "not_in_allowlist"


def test_disabled_agent_convene_denied(db_session, d4_client, d4_settings, d4_app) -> None:
    """三重白名单第一重：注册表未启用。"""
    leader, project, agent = _setup(db_session, d4_client, d4_settings)
    agent.enabled = False
    db_session.commit()
    run = _seed_run(db_session, project, leader, agent)
    with d4_app.app_context():
        with pytest.raises(MeetingsServiceError) as excinfo:
            dispatch_agent_tool(
                actor=leader.user, agent_id=agent.id, run_id=run.id,
                tool_name="meeting_convene", payload={"template_id": "T2-lite"},
            )
        assert excinfo.value.code == "agent_disabled"
    assert len(_denied_rows(db_session, run.id, "meeting_convene")) == 1


def test_whitelisted_convene_bills_the_run(db_session, d4_client, d4_settings, d4_app) -> None:
    """三重全过：召集成立 + 计费落触发 run（只读发起；计费+占预算）。"""
    leader, project, agent = _setup(db_session, d4_client, d4_settings)
    run = _seed_run(db_session, project, leader, agent)
    with d4_app.app_context():
        result = dispatch_agent_tool(
            actor=leader.user, agent_id=agent.id, run_id=run.id,
            tool_name="meeting_convene", payload={"template_id": "T2-lite"},
        )
    meeting = result["meeting"]
    assert meeting["convened_by_agent_id"] == agent.id
    assert meeting["triggered_by_run_id"] == run.id
    assert meeting["trigger"] == "mandatory"  # T2-lite 模板派生
    db_session.expire_all()
    assert db_session.get(AgentRun, run.id).token_cost == 2  # MEETING_CONVENE_COST_UNITS


def test_convene_budget_guard_blocks_and_records(db_session, d4_client, d4_settings, d4_app) -> None:
    """占预算：召集计费将越界该 run 预算 → 拒绝 + 留痕，成本停在阈值内。"""
    leader, project, agent = _setup(db_session, d4_client, d4_settings, max_cost_units=3)
    run = _seed_run(db_session, project, leader, agent)
    with d4_app.app_context():
        dispatch_agent_tool(
            actor=leader.user, agent_id=agent.id, run_id=run.id,
            tool_name="meeting_convene", payload={"template_id": "T2-lite"},
        )
        with pytest.raises(MeetingsServiceError) as excinfo:
            dispatch_agent_tool(
                actor=leader.user, agent_id=agent.id, run_id=run.id,
                tool_name="meeting_convene", payload={"template_id": "T2-lite"},
            )
        assert excinfo.value.code == "convene_budget_exhausted" and excinfo.value.status == 409
    db_session.expire_all()
    assert db_session.get(AgentRun, run.id).token_cost == 2  # 停在阈值内，不入账越界
    rows = _denied_rows(db_session, run.id, "meeting_convene")
    assert len(rows) == 1 and rows[0].reason == "convene_budget_exhausted"


def test_convene_limit_two_per_run_u7(db_session, d4_client, d4_settings, d4_app) -> None:
    """U7：每 run ≤2 次召集限额，第 3 次拒绝且留痕。"""
    leader, project, agent = _setup(db_session, d4_client, d4_settings)
    run = _seed_run(db_session, project, leader, agent)
    with d4_app.app_context():
        for _ in range(2):
            dispatch_agent_tool(
                actor=leader.user, agent_id=agent.id, run_id=run.id,
                tool_name="meeting_convene", payload={"template_id": "T2-lite"},
            )
        with pytest.raises(MeetingsServiceError) as excinfo:
            dispatch_agent_tool(
                actor=leader.user, agent_id=agent.id, run_id=run.id,
                tool_name="meeting_convene", payload={"template_id": "T2-lite"},
            )
        assert excinfo.value.code == "convene_limit_exceeded" and excinfo.value.status == 409
    assert len(_denied_rows(db_session, run.id, "meeting_convene")) == 1


def test_get_minutes_ownership_and_unsealed(db_session, d4_client, d4_settings, d4_app) -> None:
    """meeting_get_minutes：只读 + 会话内自动可读自己触发的纪要。"""
    leader, project, agent = _setup(db_session, d4_client, d4_settings)
    other = seed_agent(db_session, d4_settings, name="另一智能体", allowed_tools=("meeting_convene", "meeting_get_minutes"))
    run = _seed_run(db_session, project, leader, agent)
    other_run = _seed_run(db_session, project, leader, other)
    with d4_app.app_context():
        convened = dispatch_agent_tool(
            actor=leader.user, agent_id=agent.id, run_id=run.id,
            tool_name="meeting_convene", payload={"template_id": "T2-lite"},
        )["meeting"]
        # 未封存先读 → 拒
        with pytest.raises(MeetingsServiceError) as excinfo:
            dispatch_agent_tool(
                actor=leader.user, agent_id=agent.id, run_id=run.id,
                tool_name="meeting_get_minutes", payload={"meeting_id": convened["id"]},
            )
        assert excinfo.value.code == "minutes_not_sealed"
    body = leader.post(f"/api/v1/meetings/{convened['id']}/close", json=_MINUTES_OK)
    assert body.status_code == 200
    with d4_app.app_context():
        # 他者 agent 读非自己触发的纪要 → 拒且留痕
        with pytest.raises(MeetingsServiceError) as excinfo:
            dispatch_agent_tool(
                actor=leader.user, agent_id=other.id, run_id=other_run.id,
                tool_name="meeting_get_minutes", payload={"meeting_id": convened["id"]},
            )
        assert excinfo.value.code == "minutes_not_owned" and excinfo.value.status == 403
        owned = dispatch_agent_tool(
            actor=leader.user, agent_id=agent.id, run_id=run.id,
            tool_name="meeting_get_minutes", payload={"meeting_id": convened["id"]},
        )
    minutes = owned["minutes"]
    assert set(minutes) >= {"consensus", "disputes", "todos", "sealed_sha256"}
