"""AF1-WP1 定参①：AgentRun 取消入口（docs/ai-fde/09 §1；WorkflowRun cancel_run 同款语义）。

- 幂等：对已取消行再取消回 cancelled=False（200）；
- 终态（completed/failed/timeout/budget_exceeded/succeeded_but_receipt_invalid）→ 409 already_terminal；
- host_running → 409 cancel_provider_unsupported（宿主通道回执语义未含取消，显式拒绝）；
- running 沙箱：cancel API 写行 + 监听段 should_cancel 轮询收口 → status=cancelled、
  产物沿 B-1 非 completed 一律不入库、kill 由 finally 恒定发生（CR-015）；
- 启动守卫：cancelled 行在 SandboxHandle.create 之前被拦（沙箱永不带取消复活）。
"""
from __future__ import annotations

from uuid import uuid4

import pytest

from test_agents_d4_harness import (
    ApiClient,
    FakeClock,
    FakeScanner,
    ScriptedEvents,
    api_client,
    d4_app,
    d4_client,
    d4_settings,  # noqa: F401  (pytest fixture 再导出，F401 由 tests/* 忽略兜底)
    make_user,
    prime_run,
    seed_agent,
)
from test_document_drafts_api import _persist_project

from fde_api.agents.adapter import ArtifactFile
from fde_api.agents.cancellation import _make_cancel_check, _raise_if_cancelled
from fde_api.agents.models import AgentRun
from fde_api.agents import service as agents_service
from fde_api.auth.tokens import issue_access_token
from fde_api.workbench.models import ProjectMember


def _setup_lead(db_session, d4_client, d4_settings):
    leader = api_client(d4_client, db_session, d4_settings, "project_lead")
    project = _persist_project(db_session, leader.user, code=f"D4X{uuid4().hex[:6]}")
    agent = seed_agent(db_session, d4_settings)
    return leader, project, agent


def _make_run(db_session, leader, project, agent, status="queued", **overrides):
    run = AgentRun(
        project_id=project.id,
        agent_id=agent.id,
        initiated_by_user_id=leader.user.id,
        capability_used=agent.capability_tier,
        status=status,
        context_ref=f"masked://{uuid4().hex}",
        idempotency_key=f"idem-{uuid4().hex}",
        **overrides,
    )
    db_session.add(run)
    db_session.commit()
    return run


def test_cancel_queued_run_then_idempotent(db_session, d4_client, d4_settings):
    leader, project, agent = _setup_lead(db_session, d4_client, d4_settings)
    run = _make_run(db_session, leader, project, agent)

    body = leader.post(f"/api/v1/agents/runs/{run.id}/cancel")
    assert body.status_code == 200, body.json
    assert body.json["data"]["cancelled"] is True
    assert body.json["data"]["run"]["status"] == "cancelled"

    # 幂等：已取消行再取消 → cancelled=False，零报错零二次终态翻转
    body2 = leader.post(f"/api/v1/agents/runs/{run.id}/cancel")
    assert body2.status_code == 200, body2.json
    assert body2.json["data"]["cancelled"] is False


@pytest.mark.parametrize(
    "status",
    ["completed", "failed", "timeout", "budget_exceeded", "succeeded_but_receipt_invalid"],
)
def test_cancel_terminal_run_conflict(db_session, d4_client, d4_settings, status):
    leader, project, agent = _setup_lead(db_session, d4_client, d4_settings)
    run = _make_run(db_session, leader, project, agent, status=status, exit_code=1)
    body = leader.post(f"/api/v1/agents/runs/{run.id}/cancel")
    assert body.status_code == 409
    assert body.json["error"]["code"] == "already_terminal"


def test_cancel_missing_run_404(db_session, d4_client, d4_settings):
    leader, _project, _agent = _setup_lead(db_session, d4_client, d4_settings)
    body = leader.post("/api/v1/agents/runs/nonexistent-run/cancel")
    assert body.status_code == 404
    assert body.json["error"]["code"] == "agent_run_not_found"


def test_cancel_member_without_manage_forbidden(db_session, d4_client, d4_settings):
    """同项目可见但不可管理、非发起人 → 403 run_cancel_forbidden（授权面钉死）。"""
    leader, project, agent = _setup_lead(db_session, d4_client, d4_settings)
    run = _make_run(db_session, leader, project, agent)
    member = make_user(db_session, "viewer")
    db_session.add(ProjectMember(project_id=project.id, user_id=member.id, role="viewer"))
    db_session.commit()
    viewer = ApiClient(d4_client, member, {"Authorization": f"Bearer {issue_access_token(member, d4_settings)}"})
    body = viewer.post(f"/api/v1/agents/runs/{run.id}/cancel")
    assert body.status_code == 403
    assert body.json["error"]["code"] == "run_cancel_forbidden"


def test_default_cancel_check_reads_row_status(db_session, d4_app, d4_client, d4_settings):
    """默认取消检查（生产装配真身）：cancelled 行 True / in-flight 行 False。"""
    leader, project, agent = _setup_lead(db_session, d4_client, d4_settings)
    cancelled = _make_run(db_session, leader, project, agent, status="cancelled")
    queued = _make_run(db_session, leader, project, agent, status="queued")
    with d4_app.app_context():
        assert _make_cancel_check(cancelled.id)() is True
        assert _make_cancel_check(queued.id)() is False


def test_execute_run_guard_wiring_blocks_cancelled(db_session, d4_app, d4_client, d4_settings, monkeypatch):
    """接线钉：_execute_run 真调用启动守卫——删线即本测试转红。

    monkeypatch 守卫符号：回调内把 queued 行翻 cancelled（模拟守卫读取后
    的取消竞窗），再走真守卫语义断言 409；calls 计数钉住「守卫确实被调用」。
    """
    leader, project, agent = _setup_lead(db_session, d4_client, d4_settings)
    prime_run(d4_app)  # RecordingBackend——断言的是守卫拦截，不是沙箱执行
    calls = {"n": 0}

    def flipping_guard(run_id):
        calls["n"] += 1
        row = db_session.get(AgentRun, run_id)
        if row is not None:
            row.status = "cancelled"
            db_session.commit()
        _raise_if_cancelled(run_id)  # 真守卫语义：cancelled → 409

    monkeypatch.setattr(agents_service, "_raise_if_cancelled", flipping_guard)
    body = leader.post(f"/api/v1/agents/{agent.id}/run", json={"project_id": project.id})
    assert body.status_code == 409, body.json
    assert body.json["error"]["code"] == "agent_run_cancelled"
    assert calls["n"] == 1


def test_cancel_host_running_explicitly_unsupported(db_session, d4_client, d4_settings):
    leader, project, agent = _setup_lead(db_session, d4_client, d4_settings)
    run = _make_run(
        db_session, leader, project, agent, status="host_running", execution_provider="host_poll"
    )
    body = leader.post(f"/api/v1/agents/runs/{run.id}/cancel")
    assert body.status_code == 409
    assert body.json["error"]["code"] == "cancel_provider_unsupported"


def test_cancel_cross_project_forbidden(db_session, d4_client, d4_settings):
    leader, project, agent = _setup_lead(db_session, d4_client, d4_settings)
    run = _make_run(db_session, leader, project, agent)
    outsider = api_client(d4_client, db_session, d4_settings, "project_lead")
    body = outsider.post(f"/api/v1/agents/runs/{run.id}/cancel")
    assert body.status_code == 403
    assert body.json["error"]["code"] == "project_forbidden"


def test_running_sandbox_cancel_honest_closeout(db_session, d4_app, d4_client, d4_settings):
    """监听段 should_cancel 轮询到取消 → cancelled 终态、产物作废、kill 发生。"""
    leader, project, agent = _setup_lead(db_session, d4_client, d4_settings)
    polls = {"n": 0}

    def factory(run_id):
        def check():
            polls["n"] += 1
            return polls["n"] >= 2

        return check

    d4_app.extensions["fde_agent_cancel_check_factory"] = factory
    clock = FakeClock()
    backend = prime_run(
        d4_app,
        events=ScriptedEvents([[{"type": "tool_call", "tool": "read_file"}]]),
        clock=clock,
    )
    # 产物扫描器「能扫到东西」，但 cancelled 终态必须一律作废（B-1 同款纪律）
    d4_app.extensions["fde_agent_output_scanner_factory"] = lambda run_id, workspace: FakeScanner(
        [ArtifactFile(path="late.md", kind="doc", source_refs=("src-1",))]
    )

    body = leader.post(f"/api/v1/agents/{agent.id}/run", json={"project_id": project.id})
    assert body.status_code == 201, body.json
    data = body.json["data"]
    assert data["status"] == "cancelled"
    assert data["artifacts"] == []
    assert data["token_cost"] == 0
    # 沙箱确实被回收（kill → rm -f；CR-015 finally 恒定发生）
    assert ["rm", "-f", f"agent-run-{data['id']}"] in backend.argvs
    stored = db_session.get(AgentRun, data["id"])
    assert stored.status == "cancelled"


def test_launch_guard_rejects_cancelled_row(db_session, d4_app, d4_client, d4_settings):
    """启动守卫：cancelled 行在沙箱创建之前被拦；queued 行不受影响。"""
    leader, project, agent = _setup_lead(db_session, d4_client, d4_settings)
    cancelled = _make_run(db_session, leader, project, agent, status="cancelled")
    queued = _make_run(db_session, leader, project, agent, status="queued")

    with d4_app.app_context():
        with pytest.raises(agents_service.AgentsServiceError) as excinfo:
            _raise_if_cancelled(cancelled.id)
        assert excinfo.value.code == "agent_run_cancelled"
        assert excinfo.value.status == 409
        assert _raise_if_cancelled(queued.id) is None
