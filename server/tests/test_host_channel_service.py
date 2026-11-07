"""T-Z1 裁定 A 实施轮：宿主通道 service 集成面（开关分支 + _finalize 复用）。

用 d4 harness 注入面（extensions + settings model_copy）；spawner 经
monkeypatch 注入模块默认 spawner（``_default_spawner`` 替换点）。
"""
from __future__ import annotations

import json

import pytest

from test_agents_d4_harness import (  # noqa: F401  (pytest fixtures)
    d4_app,
    d4_client,
    d4_settings,
    issue_access_token,
    make_user,
)
from test_document_drafts_api import _persist_project

from fde_api.agents import host_channel as hc

_SUMMARY = {
    "sessionId": "sess_host_it",
    "usage": {"outputTokens": 42},
    "projection": {"status": "done"},
}


class _ItProc:
    pid = 7

    def kill(self) -> None:
        pass

    def communicate(self, timeout=None):  # noqa: ANN001
        return json.dumps(_SUMMARY), ""

    @property
    def returncode(self) -> int:
        return 0


class _ItScanner:
    receipt_state = "ok"

    def scan(self):
        return []


def _host_settings(base, **overrides):
    payload = {
        "agent_host_channel_enabled": True,
        "agent_host_zcode_bin": "C:/zcode/ZCode.exe",
        "agent_host_zcode_cjs": "C:/zcode/resources/glm/zcode.cjs",
    }
    payload.update(overrides)
    return base.model_copy(update=payload)


def _leader_client(app, settings, db_session):
    user = make_user(db_session, "project_lead")
    token = issue_access_token(user, settings)
    from test_agents_d4_harness import ApiClient

    return ApiClient(app.test_client(), user, {"Authorization": f"Bearer {token}"})


def _prime_spawner(monkeypatch):
    proc = _ItProc()
    monkeypatch.setattr(hc, "_default_spawner", lambda argv, **kwargs: proc)
    return proc


def test_host_channel_disabled_keeps_container_path(db_session, d4_client, d4_app, d4_settings, monkeypatch):
    """开关关闭（默认）：行为零变化——仍走容器沙箱路径（可注入 backend 正常完成）。"""
    from test_agents_d4_harness import FakeClock, ScriptedEvents, api_client, prime_run

    leader = api_client(d4_client, db_session, d4_settings, "project_lead")
    project = _persist_project(db_session, leader.user, code="HZ0")
    agent = seed_agent_helper(db_session, d4_settings)
    prime_run(d4_app, events=ScriptedEvents([[{"type": "done", "exit_code": 0}]]), clock=FakeClock())

    body = leader.post(f"/api/v1/agents/{agent.id}/run", json={"project_id": project.id, "idempotency_key": "hz-0"})
    assert body.status_code == 201, body.json
    assert body.json["data"]["status"] == "completed"


def test_host_channel_enabled_runs_host_spawner_and_finalizes(db_session, d4_settings, monkeypatch):
    """开关开启：不建容器沙箱（无 docker backend 也成功）→ 宿主 spawner → _finalize 复用落账。"""
    from sqlalchemy import select

    from fde_api.app import create_app
    from fde_api.agents.models import AgentRun

    settings = _host_settings(d4_settings)
    app = create_app(settings)
    app.config.update(TESTING=True)
    app.extensions["fde_agent_output_scanner_factory"] = lambda run_id, workspace: _ItScanner()
    _prime_spawner(monkeypatch)

    leader = _leader_client(app, settings, db_session)
    project = _persist_project(db_session, leader.user, code="HZ1")
    agent = seed_agent_helper(db_session, settings)

    body = leader.post(f"/api/v1/agents/{agent.id}/run", json={"project_id": project.id, "idempotency_key": "hz-1"})
    assert body.status_code == 201, body.json
    data = body.json["data"]
    assert data["status"] == "completed"
    assert data["token_cost"] == 42
    assert data["degraded"] is False

    stored = db_session.scalar(select(AgentRun).where(AgentRun.idempotency_key == "hz-1"))
    assert stored is not None and stored.status == "completed"
    assert stored.token_cost == 42


def test_host_channel_enabled_without_bin_lands_l2(db_session, d4_settings, monkeypatch):
    """开启但 zcode 路径未配置：503 + L2 + 零计费（fail-closed，不裸奔半配置）。"""
    from sqlalchemy import select

    from fde_api.app import create_app
    from fde_api.agents.models import AgentRun
    from test_agents_d4_harness import api_client

    settings = _host_settings(d4_settings, agent_host_zcode_bin="")
    app = create_app(settings)
    app.config.update(TESTING=True)

    leader = api_client(app.test_client(), db_session, settings, "project_lead")
    project = _persist_project(db_session, leader.user, code="HZ2")
    agent = seed_agent_helper(db_session, settings)

    body = leader.post(f"/api/v1/agents/{agent.id}/run", json={"project_id": project.id, "idempotency_key": "hz-2"})
    assert body.status_code == 503
    assert body.json["error"]["details"]["reason"] == "host_channel_bin_missing"

    # HTTP 路由面测试：app 请求侧另一 session，读侧须 commit 后再开新查询
    db_session.commit()
    stored = db_session.scalar(select(AgentRun).where(AgentRun.idempotency_key == "hz-2"))
    assert stored is not None and stored.fallback_level == "L2"


def seed_agent_helper(db_session, settings):
    """seed_agent 依赖 d4_settings fixture 的 retry 退避 0 值；此处直接同参构造。"""
    from test_agents_d4_harness import seed_agent

    return seed_agent(db_session, settings)
