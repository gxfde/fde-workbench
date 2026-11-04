"""goal-d4：V5 超时/预算熔断（B-1/B-2）+ V10 成本查询（M-1），API 全链。

B-1：max_duration_ms 到点 kill → status=timeout、产物不入库；
B-2：max_cost_units 越界熔断 → status=budget_exceeded、成本停在阈值内；
月度闸：agent_monthly_budget 达标即拒（409 agent_budget_exhausted）。
"""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest
from sqlalchemy import select

from test_agents_d4_harness import (
    FakeClock,
    FakeScanner,
    RecordingBackend,
    ScriptedEvents,
    api_client,
    prime_run,
    seed_agent,
)
from test_document_drafts_api import _persist_project

from fde_api.agents.adapter import ArtifactFile
from fde_api.agents.models import AgentArtifact, AgentRun
from test_agents_d4_harness import d4_app, d4_client, d4_settings  # noqa: F401  (pytest fixture)


def _setup(db_session, d4_client, d4_settings, **agent_overrides):
    leader = api_client(d4_client, db_session, d4_settings, "project_lead")
    project = _persist_project(db_session, leader.user, code=f"D4B{uuid4().hex[:6]}")
    agent = seed_agent(db_session, d4_settings, **agent_overrides)
    return leader, project, agent


def test_b1_timeout_kills_and_discards_artifacts(db_session, d4_client, d4_app, d4_settings) -> None:
    """B-1：max_duration_ms=1000 + 长跑事件流 → timeout、零计费、产物不入库。"""
    leader, project, agent = _setup(db_session, d4_client, d4_settings, max_duration_ms=1000)
    clock = FakeClock()
    # 产物扫描器「能扫到东西」，但超时终态必须一律作废（B-1 产物不入库）
    backend = prime_run(
        d4_app,
        events=ScriptedEvents([[{"type": "tool_call", "tool": "read_file"}]]),
        clock=clock,
    )
    d4_app.extensions["fde_agent_output_scanner_factory"] = lambda run_id, workspace: FakeScanner(
        [ArtifactFile(path="late.md", kind="doc", source_refs=("src-1",))]
    )

    body = leader.post(f"/api/v1/agents/{agent.id}/run", json={"project_id": project.id})
    assert body.status_code == 201, body.json
    data = body.json["data"]
    assert data["status"] == "timeout"
    assert data["token_cost"] == 0 and data["artifacts"] == []
    assert data["duration_ms"] >= 1000
    # 沙箱确实被回收（kill → rm -f）
    assert ["rm", "-f", f"agent-run-{data['id']}"] in backend.argvs
    stored = db_session.get(AgentRun, data["id"])
    assert stored.status == "timeout"
    assert db_session.scalar(select(AgentArtifact).where(AgentArtifact.run_id == data["id"])) is None


def test_b2_budget_circuit_keeps_cost_under_threshold(db_session, d4_client, d4_app, d4_settings) -> None:
    """B-2：max_cost_units=5，事件 3+4 → budget_exceeded，成本停在 3。"""
    leader, project, agent = _setup(db_session, d4_client, d4_settings, max_cost_units=5)
    backend = prime_run(
        d4_app,
        events=ScriptedEvents([[{"type": "cost", "units": 3}], [{"type": "cost", "units": 4}]]),
    )
    body = leader.post(f"/api/v1/agents/{agent.id}/run", json={"project_id": project.id})
    assert body.status_code == 201
    data = body.json["data"]
    assert data["status"] == "budget_exceeded"
    assert data["token_cost"] == 3
    assert ["rm", "-f", f"agent-run-{data['id']}"] in backend.argvs


def test_monthly_budget_gate_blocks_before_any_billing(db_session, d4_client, d4_app, d4_settings) -> None:
    """月度闸（FDE_AGENT_MONTHLY_BUDGET）：月内已花 ≥ 预算 → 409，不建 run 不计费。"""
    leader, project, agent = _setup(db_session, d4_client, d4_settings)
    settings = d4_app.config["SETTINGS"].model_copy(update={"agent_monthly_budget": 100})
    d4_app.config["SETTINGS"] = settings
    db_session.add(
        AgentRun(
            project_id=project.id,
            agent_id=agent.id,
            initiated_by_user_id=leader.user.id,
            capability_used=agent.capability_tier,
            status="completed",
            context_ref="agent-workspaces/seed/context.md",
            idempotency_key=f"seed:{uuid4().hex}",
            token_cost=100,
            created_at=datetime.now(timezone.utc),
        )
    )
    db_session.commit()

    prime_run(d4_app)
    body = leader.post(f"/api/v1/agents/{agent.id}/run", json={"project_id": project.id, "idempotency_key": f"fresh:{uuid4().hex}"})
    assert body.status_code == 409
    assert body.json["error"]["code"] == "agent_budget_exhausted"

    # 预算 0 = 不限额：同一状态放行
    d4_app.config["SETTINGS"] = settings.model_copy(update={"agent_monthly_budget": 0})
    ok = leader.post(f"/api/v1/agents/{agent.id}/run", json={"project_id": project.id, "idempotency_key": f"fresh:{uuid4().hex}"})
    assert ok.status_code == 201


def test_retry_run_also_checks_platform_monthly_budget(db_session, d4_client, d4_app, d4_settings) -> None:
    """goal-c CR-012：retry 通道也过平台月度闸——start 的月度封顶不能只对新建 run 生效。

    跨月失败 run 的 retry 若不重判月度闸，会绕过「下月再试」语义（V8 家族重试是
    原 start 的延续，预算口径不豁免）。修复前 retry 无 `_platform_month_spent` 调用。
    """
    leader, project, agent = _setup(db_session, d4_client, d4_settings)
    # 先建一个 failed run（此时预算 0 不限额，201）——作为 retry 目标
    d4_app.extensions["fde_agent_sandbox_backend"] = RecordingBackend()
    d4_app.extensions["fde_agent_event_provider_factory"] = lambda run_id, workspace: ScriptedEvents(
        [[{"type": "done", "exit_code": 1}]]
    )
    key = f"cr12:{uuid4().hex}"
    original_id = leader.post(
        f"/api/v1/agents/{agent.id}/run", json={"project_id": project.id, "idempotency_key": key}
    ).json["data"]["id"]
    assert db_session.get(AgentRun, original_id).status == "failed"

    # 把平台月花顶到预算（completed 行 100，token_cost 计入月度闸），预算=100 → 达标
    settings = d4_app.config["SETTINGS"].model_copy(update={"agent_monthly_budget": 100})
    d4_app.config["SETTINGS"] = settings
    db_session.add(
        AgentRun(
            project_id=project.id,
            agent_id=agent.id,
            initiated_by_user_id=leader.user.id,
            capability_used=agent.capability_tier,
            status="completed",
            context_ref="agent-workspaces/cr12/context.md",
            idempotency_key=f"cr12-spend:{uuid4().hex}",
            token_cost=100,
            created_at=datetime.now(timezone.utc),
        )
    )
    db_session.commit()

    blocked = leader.post(f"/api/v1/agents/runs/{original_id}/retry", json=None)
    assert blocked.status_code == 409, blocked.json
    assert blocked.json["error"]["code"] == "agent_budget_exhausted"
    # 未新建 retry run（家族仍只 1 行）
    db_session.expire_all()
    family = list(db_session.scalars(select(AgentRun).where(AgentRun.idempotency_key == key)))
    assert len(family) == 1 and family[0].id == original_id

    # 对照：预算 0 不限额时 retry 放行（既有行为不回归）
    d4_app.config["SETTINGS"] = settings.model_copy(update={"agent_monthly_budget": 0})
    ok = leader.post(f"/api/v1/agents/runs/{original_id}/retry", json=None)
    assert ok.status_code == 201, ok.json


def test_m1_cost_query_scopes_and_rollup(db_session, d4_client, d4_app, d4_settings) -> None:
    """V10/M-1：run 级明细 + 月度汇总一致；scope 权限与参数校验收口。"""
    leader, project, agent = _setup(db_session, d4_client, d4_settings)
    other_leader = api_client(d4_client, db_session, d4_settings, "project_lead")
    other_project = _persist_project(db_session, other_leader.user, code=f"D4C{uuid4().hex[:6]}")
    admin = api_client(d4_client, db_session, d4_settings, "admin")
    now = datetime.now(timezone.utc)
    for cost in (10, 20):
        db_session.add(
            AgentRun(
                project_id=project.id, agent_id=agent.id, initiated_by_user_id=leader.user.id,
                capability_used=agent.capability_tier, status="completed",
                context_ref="agent-workspaces/m1/context.md", idempotency_key=f"m1:{uuid4().hex}",
                token_cost=cost, created_at=now,
            )
        )
    db_session.add(
        AgentRun(
            project_id=other_project.id, agent_id=agent.id, initiated_by_user_id=other_leader.user.id,
            capability_used=agent.capability_tier, status="failed",
            context_ref="agent-workspaces/m1b/context.md", idempotency_key=f"m1:{uuid4().hex}",
            token_cost=7, created_at=now,
        )
    )
    db_session.commit()
    base = "/api/v1/agents/cost"

    project_body = leader.get(f"{base}?scope=project&project_id={project.id}")
    assert project_body.status_code == 200
    payload = project_body.json["data"]
    assert len(payload["items"]) == 2 and payload["total_token_cost"] == 30
    assert sum(payload["monthly"].values()) == payload["total_token_cost"]

    # 他人项目 404；seat/platform 非管理员 403；缺参与参数 400
    assert leader.get(f"{base}?scope=project&project_id={other_project.id}").status_code == 404
    assert leader.get(f"{base}?scope=seat").status_code == 403
    assert leader.get(f"{base}?scope=platform").status_code == 403
    assert leader.get(f"{base}?scope=project").status_code == 400
    assert leader.get(f"{base}?scope=nope").status_code == 400

    seat = admin.get(f"{base}?scope=seat")
    assert seat.status_code == 200
    by_user = {item["user_id"]: item for item in seat.json["data"]["items"]}
    assert by_user[leader.user.id]["token_cost"] == 30 and by_user[leader.user.id]["runs"] == 2
    assert by_user[other_leader.user.id]["token_cost"] == 7

    platform = admin.get(f"{base}?scope=platform")
    assert platform.status_code == 200
    assert platform.json["data"]["total_runs"] == 3
    assert platform.json["data"]["total_token_cost"] == 37
