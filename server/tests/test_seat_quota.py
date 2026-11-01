"""goal-d7：O-3 额度——100 次/月 seat 归集 + 加油包透明化 + 绝不断供 + 30 天重校。

一次动作 = 一条 ledger 行：agent_run（发起时刻；演练零计量）/ meeting_convene
（工具面；人工免费）/ ai_chat（分析成功就绪时计）。超额只标注不拦截
（record_action 永不抛错）——「交付中途绝不静默断供」。
"""
from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from sqlalchemy import select

from test_agents_d4_harness import (
    FakeScanner,
    api_client,
    prime_run,
    seed_agent,
)
from test_agents_d4_harness import d4_app, d4_client, d4_settings  # noqa: F401  (pytest fixture)
from test_document_drafts_api import _persist_project

from fde_api.agents.models import AgentRun, SeatActionLedger


def _ledger(db_session, user_id: str) -> list[SeatActionLedger]:
    return list(
        db_session.scalars(
            select(SeatActionLedger)
            .where(SeatActionLedger.user_id == user_id)
            .order_by(SeatActionLedger.created_at, SeatActionLedger.id)
        )
    )


def _setup(db_session, d4_client, d4_settings):
    leader = api_client(d4_client, db_session, d4_settings, "project_lead")
    project = _persist_project(db_session, leader.user, code=f"D7Q{uuid4().hex[:6]}")
    agent = seed_agent(db_session, d4_settings, allowed_tools=("read_file", "meeting_convene"))
    return leader, project, agent


def _refs_writer(path: str):
    def factory(run_id, workspace):
        output = Path(workspace) / "output"
        output.mkdir(parents=True, exist_ok=True)
        (output / path).write_text("产物正文", encoding="utf-8")
        return FakeScanner([])

    return factory


def _start(leader, agent, project, *, key: str | None = None):
    return leader.post(
        f"/api/v1/agents/{agent.id}/run",
        json={"project_id": project.id, "idempotency_key": key or f"quota:{uuid4().hex}"},
    )


# ---------------------------------------------------------------------------
# 计量口径
# ---------------------------------------------------------------------------


def test_run_counts_one_action(db_session, d4_client, d4_settings, d4_app) -> None:
    leader, project, agent = _setup(db_session, d4_client, d4_settings)
    prime_run(d4_app, scanner_factory=_refs_writer("plan.md"))
    body = _start(leader, agent, project)
    assert body.status_code == 201, body.json
    rows = _ledger(db_session, leader.user.id)
    assert len(rows) == 1
    assert rows[0].action_type == "agent_run" and rows[0].units == 1
    assert rows[0].ref_id == body.json["data"]["id"] and rows[0].over_quota is False


def test_rehearsal_and_manual_meeting_free(db_session, d4_client, d4_settings) -> None:
    """演练 run（rehearsal: 前缀）与人工开会零计量——「人工不占 agent 限额」。"""
    admin = api_client(d4_client, db_session, d4_settings, "admin")
    leader, project, agent = _setup(db_session, d4_client, d4_settings)  # noqa: F841 (agent 供演练)
    body = admin.post(f"/api/v1/agents/{agent.id}/fallback-rehearsal", json={"level": "L1", "project_id": project.id})
    assert body.status_code == 200, body.json  # d6 契约：演练 200（幂等形态返回）
    manual = leader.post(
        "/api/v1/meetings", json={"project_id": project.id, "template_id": "S6-free"}
    )
    assert manual.status_code == 201
    assert _ledger(db_session, leader.user.id) == []
    assert _ledger(db_session, admin.user.id) == []


def test_toolface_convene_counts_action(db_session, d4_client, d4_settings, app) -> None:
    """工具面召集 = 一场评审会 = 一次动作；seat 归集 = 触发 run 的发起人。"""
    leader, project, agent = _setup(db_session, d4_client, d4_settings)
    run = AgentRun(
        project_id=project.id,
        agent_id=agent.id,
        initiated_by_user_id=leader.user.id,
        capability_used=agent.capability_tier,
        status="running",
        context_ref="agent-workspaces/x/context.md",
        idempotency_key=f"qconv:{uuid4().hex}",
    )
    db_session.add(run)
    db_session.commit()
    from fde_api.meetings.service import dispatch_agent_tool

    with app.app_context():
        dispatch_agent_tool(
            actor=leader.user, agent_id=agent.id, run_id=run.id,
            tool_name="meeting_convene",
            payload={"template_id": "T3-adhoc", "triggered_by_run_id": run.id, "reason": "额度核对"},
        )
    rows = _ledger(db_session, leader.user.id)
    assert len(rows) == 1 and rows[0].action_type == "meeting_convene"
    assert rows[0].user_id == run.initiated_by_user_id  # seat 归集到 run 发起人


def test_ai_chat_counted_on_analysis_ready(db_session, d4_client, d4_settings, app, monkeypatch) -> None:
    """ai_chat：预调研分析 worker 成功就绪时计一条（失败/重试不计）。"""
    from test_guidance_retry import (
        _install_fake_kimi,
        _load_generator,
        _seed_analysis,
        _valid_payload,
    )

    _leader, _project, _agent = _setup(db_session, d4_client, d4_settings)
    docx_bytes = _load_generator()._build_missing_sections()  # noqa: SLF001
    analysis, job, version = _seed_analysis(db_session, data=docx_bytes)
    source_ref = f"kimi-file:{version.id}"
    _install_fake_kimi(monkeypatch, [lambda content, filename: _valid_payload(source_ref)])
    with app.app_context():
        from fde_api.guidance.jobs import handle_presurvey_analysis

        handle_presurvey_analysis(job)
    rows = [row for row in _ledger(db_session, analysis.created_by_user_id) if row.action_type == "ai_chat"]
    assert len(rows) == 1 and rows[0].ref_id == analysis.id


# ---------------------------------------------------------------------------
# 配额快照 / 超额不断供 / 重校钩子
# ---------------------------------------------------------------------------


def test_quota_endpoint_snapshot(db_session, d4_client, d4_settings, d4_app) -> None:
    leader, project, agent = _setup(db_session, d4_client, d4_settings)
    prime_run(d4_app, scanner_factory=_refs_writer("plan.md"))
    assert _start(leader, agent, project).status_code == 201
    body = leader.get("/api/v1/agents/quota")
    assert body.status_code == 200, body.json
    data = body.json["data"]
    assert data["quota_monthly"] == 100 and data["used"] == 1 and data["remaining"] == 99
    assert data["over_quota"] is False and data["warn_low_remaining"] is False
    assert data["pack"]["entry"] == "action_pack" and data["pack"]["price_yuan"] > 0
    assert data["window"]["review_due"] is False


def test_over_quota_never_blocks(db_session, d4_client, d4_settings, d4_app) -> None:
    """超额只标注不拦截（绝不断供）：第 2 个 run 照常 201 + over_quota 落账 +
    配额快照标超额与加油包入口。"""
    leader, project, agent = _setup(db_session, d4_client, d4_settings)
    leader_user = leader.user
    # 压配额：直接改 app settings（d6 试点闸同款 fixture 注入路径）
    d4_app.config["SETTINGS"] = d4_app.config["SETTINGS"].model_copy(update={"seat_action_quota_monthly": 1})
    try:
        prime_run(d4_app, scanner_factory=_refs_writer("plan.md"))
        first = _start(leader, agent, project, key="quota:first")
        assert first.status_code == 201, first.json
        prime_run(d4_app, scanner_factory=_refs_writer("plan.md"))
        second = _start(leader, agent, project, key="quota:second")
        assert second.status_code == 201, second.json  # 绝不断供
        rows = _ledger(db_session, leader_user.id)
        assert [row.over_quota for row in rows] == [False, True]
        snapshot = leader.get("/api/v1/agents/quota").json["data"]
        assert snapshot["used"] == 2 and snapshot["over_quota"] is True
        assert snapshot["remaining"] == 0 and snapshot["warn_low_remaining"] is True
        assert "加油包" in snapshot["pack"]["note"]
    finally:
        d4_app.config["SETTINGS"] = d4_app.config["SETTINGS"].model_copy(update={"seat_action_quota_monthly": 100})


def test_quota_scope_permissions(db_session, d4_client, d4_settings) -> None:
    """本席默认 self；他席 leader 403 / admin 放行。"""
    leader, project, agent = _setup(db_session, d4_client, d4_settings)
    other = api_client(d4_client, db_session, d4_settings, "project_lead")
    forbidden = leader.get(f"/api/v1/agents/quota?user_id={other.user.id}")
    assert forbidden.status_code == 403
    assert forbidden.json["error"]["code"] == "quota_scope_forbidden"
    admin = api_client(d4_client, db_session, d4_settings, "admin")
    ok = admin.get(f"/api/v1/agents/quota?user_id={other.user.id}")
    assert ok.status_code == 200 and ok.json["data"]["user_id"] == other.user.id


def test_quota_zero_is_unlimited(db_session, d4_client, d4_settings, d4_app) -> None:
    leader, project, agent = _setup(db_session, d4_client, d4_settings)
    d4_app.config["SETTINGS"] = d4_app.config["SETTINGS"].model_copy(update={"seat_action_quota_monthly": 0})
    try:
        prime_run(d4_app, scanner_factory=_refs_writer("plan.md"))
        assert _start(leader, agent, project).status_code == 201
        data = leader.get("/api/v1/agents/quota").json["data"]
        assert data["unlimited"] is True and data["over_quota"] is False
        assert data["remaining_pct"] is None and data["warn_low_remaining"] is False
    finally:
        d4_app.config["SETTINGS"] = d4_app.config["SETTINGS"].model_copy(update={"seat_action_quota_monthly": 100})


def test_review_window_derived_from_first_action(db_session, d4_client, d4_settings, d4_app) -> None:
    """30 天重校钩子：窗口起点 = 最早 ledger 行；未到期 review_due=False。"""
    leader, project, agent = _setup(db_session, d4_client, d4_settings)
    prime_run(d4_app, scanner_factory=_refs_writer("plan.md"))
    assert _start(leader, agent, project).status_code == 201
    data = leader.get("/api/v1/agents/quota").json["data"]["window"]
    assert data["started_at"] is not None and data["review_due_at"] is not None
    assert data["review_due"] is False
