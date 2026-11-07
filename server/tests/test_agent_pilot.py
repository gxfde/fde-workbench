"""goal-d6：S1 试点开关（30 天/20 run 计数器 + UM-1 报告六指标）。

判定锚：PRD §10 试点 + 技术文档 §1 S1-7 + 总纲 UM-1/D15（只出数不判阈）。
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from test_agents_d4_harness import (
    ScriptedEvents,
    api_client,
    prime_run,
    seed_agent,
)
from test_agents_d4_harness import d4_app, d4_client, d4_settings  # noqa: F401  (pytest fixture)
from test_document_drafts_api import _persist_project

from fde_api.agents.models import AgentArtifact, AgentRun, AgentToolCall
from fde_api.agents.pilot import pilot_status
from fde_api.app import create_app
from fde_api.meetings.models import ReviewMeeting
from fde_api.solutions.models import ProjectSolution


@pytest.fixture
def pilot_settings(d4_settings):
    return d4_settings.model_copy(update={"agent_pilot_enabled": True, "agent_pilot_max_runs": 2})


@pytest.fixture
def pilot_app(pilot_settings):
    app = create_app(pilot_settings)
    app.config.update(TESTING=True)
    return app


@pytest.fixture
def pilot_client(pilot_app):
    return pilot_app.test_client()


def _api(client, db_session, settings, role):
    return api_client(client, db_session, settings, role)


def _start(leader, agent, project, key: str):
    return leader.post(
        f"/api/v1/agents/{agent.id}/run", json={"project_id": project.id, "idempotency_key": key}
    )


def test_pilot_disabled_by_default(db_session, d4_client, d4_app, d4_settings) -> None:
    """默认关闭：run 不受闸；报告 pilot.active=False 且无指标段。"""
    leader = _api(d4_client, db_session, d4_settings, "project_lead")
    project = _persist_project(db_session, leader.user, code=f"PL{uuid4().hex[:4]}")
    agent = seed_agent(db_session, d4_settings)
    prime_run(d4_app)
    for index in range(3):  # 远超默认 20 也不用——证明无闸即可
        assert _start(leader, agent, project, f"pl:{index}:{uuid4().hex}").status_code == 201
    admin = _api(d4_client, db_session, d4_settings, "admin")
    report = admin.get("/api/v1/agents/pilot-report").json["data"]
    assert report["pilot"]["enabled"] is False and report["pilot"]["active"] is False
    assert report["metrics"] == {}


def test_pilot_run_cap_blocks_excess(db_session, pilot_client, pilot_app, pilot_settings) -> None:
    """窗口内 20 run 上限（本轮 fixtures 压到 2）：第 3 次 409 + 明细。"""
    leader = _api(pilot_client, db_session, pilot_settings, "project_lead")
    project = _persist_project(db_session, leader.user, code=f"PL{uuid4().hex[:4]}")
    agent = seed_agent(db_session, pilot_settings)
    prime_run(pilot_app)
    assert _start(leader, agent, project, f"a:{uuid4().hex}").status_code == 201
    assert _start(leader, agent, project, f"b:{uuid4().hex}").status_code == 201
    third = _start(leader, agent, project, f"c:{uuid4().hex}")
    assert third.status_code == 409 and third.json["error"]["code"] == "pilot_run_limit_exceeded"
    assert third.json["error"]["details"]["runs_used"] == 2


def test_pilot_ignores_rehearsal_runs(db_session, pilot_client, pilot_app, pilot_settings) -> None:
    """演练 run（rehearsal: 前缀）不占试点配额。"""
    admin = _api(pilot_client, db_session, pilot_settings, "admin")
    leader = _api(pilot_client, db_session, pilot_settings, "project_lead")
    project = _persist_project(db_session, leader.user, code=f"PL{uuid4().hex[:4]}")
    agent = seed_agent(db_session, pilot_settings)
    for _ in range(3):
        assert admin.post(
            f"/api/v1/agents/{agent.id}/fallback-rehearsal", json={"level": "L1", "project_id": project.id}
        ).status_code == 200
    prime_run(pilot_app)
    assert _start(leader, agent, project, f"a:{uuid4().hex}").status_code == 201
    assert _start(leader, agent, project, f"b:{uuid4().hex}").status_code == 201
    assert _start(leader, agent, project, f"c:{uuid4().hex}").status_code == 409


def test_pilot_window_expiry_reopens(db_session, d4_settings) -> None:
    """30 天先到为准：窗口走完 active=False，超配额不再拦。"""
    expired = d4_settings.model_copy(
        update={
            "agent_pilot_enabled": True,
            "agent_pilot_max_runs": 1,
            "agent_pilot_started_at": (datetime.now(timezone.utc) - timedelta(days=31)).isoformat(),
        }
    )
    app = create_app(expired)
    app.config.update(TESTING=True)
    client = app.test_client()
    leader = _api(client, db_session, expired, "project_lead")
    project = _persist_project(db_session, leader.user, code=f"PL{uuid4().hex[:4]}")
    agent = seed_agent(db_session, expired)
    prime_run(app)
    assert _start(leader, agent, project, f"a:{uuid4().hex}").status_code == 201
    assert _start(leader, agent, project, f"b:{uuid4().hex}").status_code == 201  # 窗口外不拦
    admin = _api(client, db_session, expired, "admin")
    report = admin.get("/api/v1/agents/pilot-report").json["data"]
    assert report["pilot"]["active"] is False and report["pilot"]["exhausted"] is False


def test_pilot_report_admin_only(db_session, d4_client, d4_app, d4_settings) -> None:
    leader = _api(d4_client, db_session, d4_settings, "project_lead")
    assert leader.get("/api/v1/agents/pilot-report").status_code == 403


def test_pilot_report_metrics(db_session, d4_client, d4_app, d4_settings) -> None:
    """UM-1 六指标数值断言（构造 5 run + 2 会议 + 1 次召集计费 + 1 卡死）。"""
    started = datetime.now(timezone.utc) - timedelta(hours=1)
    settings = d4_settings.model_copy(
        update={"agent_pilot_enabled": True, "agent_pilot_started_at": started.isoformat()}
    )
    app = create_app(settings)
    app.config.update(TESTING=True)
    client = app.test_client()
    leader = _api(client, db_session, settings, "project_lead")
    project = _persist_project(db_session, leader.user, code=f"PL{uuid4().hex[:4]}")
    agent = seed_agent(db_session, settings)
    solution = ProjectSolution(project_id=project.id, name="试点方案", owner_user_id=leader.user.id)
    db_session.add(solution)
    db_session.commit()

    def _run(*, status, token, degraded=False, reason=None, retry_of=None, level=None):
        run = AgentRun(
            project_id=project.id, agent_id=agent.id, initiated_by_user_id=leader.user.id,
            capability_used=agent.capability_tier, status=status, token_cost=token,
            context_ref="agent-workspaces/m/context.md", idempotency_key=f"m:{uuid4().hex}",
            degraded=degraded, degraded_reason=reason, retry_of=retry_of, fallback_level=level,
        )
        db_session.add(run)
        db_session.commit()
        return run

    passed_first = _run(status="completed", token=2)
    _run(status="failed", token=4, degraded=True, reason="review_gate_open")
    _run(status="completed", token=4, degraded=True, reason="tool_denied", level="L1")
    _run(status="timeout", token=4)
    passed_retry = _run(status="completed", token=8, retry_of=passed_first.id)
    db_session.add(AgentArtifact(run_id=passed_first.id, kind="doc", storage_ref="a", sha256="1" * 64, linked_solution_id=solution.id))
    db_session.add(AgentArtifact(run_id=passed_retry.id, kind="doc", storage_ref="b", sha256="2" * 64, linked_solution_id=solution.id))
    db_session.add(ReviewMeeting(project_id=project.id, template_id="T2-lite", status="closed", topic_refs={}, turn_budget=2, hosted_by_user_id=leader.user.id, gate_tier="lite", trigger="mandatory"))
    db_session.add(ReviewMeeting(project_id=project.id, template_id="T2-lite", status="live", topic_refs={}, turn_budget=2, hosted_by_user_id=leader.user.id, gate_tier="lite", trigger="mandatory"))
    db_session.add(AgentToolCall(run_id=passed_first.id, tool_name="meeting_convene", decision="allowed", capability=agent.capability_tier))
    stuck = _run(status="queued", token=0)
    stuck.updated_at = datetime.now(timezone.utc) - timedelta(hours=2)
    db_session.commit()

    report = leader.get("/api/v1/agents/pilot-report")
    assert report.status_code == 403  # project_lead 非管理员不可读
    data = _api(client, db_session, settings, "admin").get("/api/v1/agents/pilot-report").json["data"]
    assert data["pilot"]["active"] is True and data["pilot"]["runs_used"] == 6
    assert data["pilot"]["runs_limit"] == 20 and data["pilot"]["runs_remaining"] == 14
    metrics = data["metrics"]
    assert metrics["intercept_rate"] == round(1 / 3, 4)  # 1 拦截 / (1 拦截 + 2 过门产物 run)
    assert metrics["first_pass_rate"] == 0.5  # 过门 2 run 中首次尝试 1（A）
    assert metrics["avg_meeting_cost_units"] == 1.0  # 1 次 allowed 召集 ×2 / 2 会议
    assert metrics["degraded_rate"] == round(2 / 6, 4)  # 2/6
    assert metrics["circuit_breaker_rate"] == round(1 / 6, 4)  # timeout 1/6
    assert metrics["median_run_cost_units"] == 4.0  # [2,4,4,4,8]
    assert metrics["total_runs"] == 6 and metrics["total_meetings"] == 2 and metrics["blocked_runs"] == 1
    assert data["stuck_inflight_runs"] == 1


# ---------- 架构评估 2026-11-07 D4：契约未验证警示（只读呈现，不拦 run） ----------

def _contract_world(db_session, settings):
    """窗口显式起点的试点世界：app + leader + project + agent（零 run）。"""
    started = settings.model_copy(update={
        "agent_pilot_enabled": True,
        "agent_pilot_started_at": "2026-01-01T00:00:00+00:00",
    })
    app = create_app(started)
    app.config.update(TESTING=True)
    client = app.test_client()
    leader = _api(client, db_session, started, "project_lead")
    project = _persist_project(db_session, leader.user, code=f"PL{uuid4().hex[:4]}")
    agent = seed_agent(db_session, started)
    return started, leader.user, project, agent


def _seed_run(db_session, *, user, project, agent, status, key, created_at=None):
    run = AgentRun(
        project_id=project.id, agent_id=agent.id, initiated_by_user_id=user.id,
        capability_used=agent.capability_tier, status=status, token_cost=1,
        context_ref="agent-workspaces/m/context.md", idempotency_key=key,
        created_at=created_at,
    )
    db_session.add(run)
    db_session.commit()
    return run


_NOW = datetime(2026, 1, 5, tzinfo=timezone.utc)


def test_pilot_contract_unverified_warns_with_zero_runs(db_session, d4_settings) -> None:
    """架构评估 2026-11-07 D4：窗口激活但零真实完成 run → contract_unverified 警示。

    ZcodeAdapter spawn 契约未经真机验证（售前方案 Q5/T-Z1）——spawn 失败全落
    L2 会污染试点指标；警示只读呈现，不拦 run（pilot_capacity_error 不变）。
    """
    settings, user, project, agent = _contract_world(db_session, d4_settings)
    status = pilot_status(db_session, settings, now=_NOW)
    assert status["active"] is True and status["runs_used"] == 0
    assert status["contract_unverified"] is True
    assert status["warnings"] and "T-Z1" in status["warnings"][0]


def test_pilot_contract_warning_clears_after_real_completed_run(db_session, d4_settings) -> None:
    settings, user, project, agent = _contract_world(db_session, d4_settings)
    _seed_run(db_session, user=user, project=project, agent=agent,
              status="completed", key=f"m:{uuid4().hex}",
              created_at=datetime(2026, 1, 2, tzinfo=timezone.utc))
    status = pilot_status(db_session, settings, now=_NOW)
    assert status["contract_unverified"] is False
    assert status["warnings"] == []


def test_pilot_rehearsal_run_does_not_verify_contract(db_session, d4_settings) -> None:
    """演练 run（rehearsal: 前缀）不算契约证据——与试点计数同一排除口径。"""
    settings, user, project, agent = _contract_world(db_session, d4_settings)
    _seed_run(db_session, user=user, project=project, agent=agent,
              status="completed", key=f"rehearsal:{uuid4().hex}",
              created_at=datetime(2026, 1, 2, tzinfo=timezone.utc))
    status = pilot_status(db_session, settings, now=_NOW)
    assert status["runs_used"] == 0  # 排除口径一致
    assert status["contract_unverified"] is True
    assert status["warnings"]
