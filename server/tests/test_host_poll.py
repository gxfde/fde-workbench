"""P2′① 宿主轮询领取：服务层三函数 + 三路由（§11.3 六条约束）。

覆盖：fail-closed 闸 / 领取 FIFO+幂等+token 绑定 / 回执终态对齐+产物指纹直录 /
H4 失联只标记 / 状态机迁移（queued→host_running→终态）。
集成层免 app 直调 service（claim/receipt/status 都是纯 session 面）；
HTTP 面跑 1 例烟测（路由→service 接线 + 错误投影）。
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from fde_api.agents import service as svc
from fde_api.agents.models import AgentArtifact, AgentRun
from sqlalchemy import select

from pydantic import SecretStr

from test_agents_d4_harness import d4_settings  # noqa: F401  (pytest fixture)
from test_document_drafts_api import _persist_project

TOKEN = "host-proxy-token-0123456789abcdef"
_TOKEN_SECRET = SecretStr(TOKEN)
SUMMARY = {
    "sessionId": "sess_p2",
    "usage": {"inputTokens": 10, "outputTokens": 20},
    "projection": {"status": "done", "totalTokenCount": 30},
}


@pytest.fixture
def poll_settings(d4_settings, monkeypatch):
    """settings 快照 + 服务层 _settings 注入（service 直调不经 app context）。"""
    settings = d4_settings.model_copy(
        update={
            "agent_host_poll_enabled": True,
            "agent_host_poll_token": _TOKEN_SECRET,
            "agent_host_lost_mark_minutes": 30,
        }
    )
    monkeypatch.setattr(svc, "_settings", lambda: settings)
    return settings


def _seed_host_run(db_session, settings, *, status="queued", claimed=None, provider="host_poll"):
    """直接落一条 host_poll run（绕过 start_run 全闸——闸面已有既有测试覆盖）。"""
    from test_agents_d4_harness import make_user, seed_agent

    import uuid as _uuid

    user = make_user(db_session, "project_lead")
    project = _persist_project(db_session, user, code=f"HP{_uuid.uuid4().hex[:6].upper()}")
    agent = seed_agent(db_session, settings)
    run = AgentRun(
        project_id=project.id,
        agent_id=agent.id,
        initiated_by_user_id=user.id,
        capability_used=agent.capability_tier,
        status=status,
        context_ref="agent-workspaces/r-host/task.md",
        idempotency_key=f"host-{status}-{claimed}-{datetime.now(timezone.utc).timestamp()}",
        execution_provider=provider,
        host_claimed_at=claimed,
        host_token_hash=svc._host_poll_token_hash(TOKEN) if claimed else None,
    )
    db_session.add(run)
    db_session.commit()
    return run


# ---------------------------------------------------------------------------
# fail-closed 闸（约束：生产启用闸不放宽）
# ---------------------------------------------------------------------------


def test_disabled_by_default_403(db_session, d4_settings):
    """默认关闭：三条面全部 403 host_poll_disabled。"""
    for fn, kwargs in (
        (svc.host_poll_status, {"presented_token": TOKEN}),
        (svc.claim_host_run, {"presented_token": TOKEN}),
        (svc.submit_host_receipt, {"presented_token": TOKEN, "run_id": "x", "payload": {"summary": {}}}),
    ):
        with pytest.raises(svc.AgentsServiceError) as ei:
            fn(**kwargs)
        assert ei.value.code == "host_poll_disabled" and ei.value.status == 403


def test_enabled_without_token_403(db_session, poll_settings, monkeypatch):
    """开关开但令牌为空 ⇒ 仍 403（半配置不裸奔）。"""
    import unittest.mock as mock

    broken = poll_settings.model_copy(update={"agent_host_poll_token": None})
    monkeypatch.setattr(svc, "_settings", lambda: broken)
    with pytest.raises(svc.AgentsServiceError) as ei:
        svc.claim_host_run(presented_token=TOKEN)
    assert ei.value.code == "host_poll_disabled"


def test_wrong_token_403(db_session, poll_settings):
    with pytest.raises(svc.AgentsServiceError) as ei:
        svc.claim_host_run(presented_token="wrong-token")
    assert ei.value.code == "host_poll_forbidden"


# ---------------------------------------------------------------------------
# 领取：FIFO / 状态迁移 / 幂等重领 / token 绑定
# ---------------------------------------------------------------------------


def test_claim_fifo_and_status_transition(db_session, poll_settings):
    r1 = _seed_host_run(db_session, poll_settings)
    r2 = _seed_host_run(db_session, poll_settings)
    out = svc.claim_host_run(presented_token=TOKEN)
    assert out["run_id"] in (r1.id, r2.id)
    assert "claimed_at" in out and "context_ref" in out
    assert out["claimed_at"] is not None
    db_session.expire_all()  # claim 在另一 session 提交
    row = db_session.get(AgentRun, out["run_id"])
    assert row.status == "host_running"
    assert row.execution_provider == "host_poll"
    assert row.host_token_hash == svc._host_poll_token_hash(TOKEN)
    # FIFO：早创建的先领
    assert out["run_id"] == r1.id


def test_claim_idempotent_same_token(db_session, poll_settings):
    run = _seed_host_run(db_session, poll_settings)
    first = svc.claim_host_run(presented_token=TOKEN)
    second = svc.claim_host_run(presented_token=TOKEN)
    assert first["run_id"] == second["run_id"] == run.id
    db_session.expire_all()  # claim 在另一 session 提交
    row = db_session.get(AgentRun, run.id)
    assert row.host_claimed_at is not None


def test_claim_conflict_after_token_rotation(db_session, poll_settings, monkeypatch):
    """服务端令牌轮换后，旧 hash 的 run 被新令牌续领 ⇒ host_claim_conflict。

    （真实冲突面：config 只有一个 token，异 token 在 _verify 就 403；hash 不
    匹配分支覆盖「token 轮换后旧代理续领」场景。）
    """
    from pydantic import SecretStr

    run = _seed_host_run(db_session, poll_settings)
    svc.claim_host_run(presented_token=TOKEN)  # 旧 token 领取 → host_running + 旧 hash
    rotated = poll_settings.model_copy(update={"agent_host_poll_token": SecretStr("rotated-token")})
    monkeypatch.setattr(svc, "_settings", lambda: rotated)
    with pytest.raises(svc.AgentsServiceError) as ei:
        svc.claim_host_run(presented_token="rotated-token", run_id=run.id)
    assert ei.value.code == "host_claim_conflict"


def test_claim_empty_queue_404(db_session, poll_settings):
    with pytest.raises(svc.AgentsServiceError) as ei:
        svc.claim_host_run(presented_token=TOKEN)
    assert ei.value.status == 404


def test_claim_skips_sandbox_runs(db_session, poll_settings):
    """execution_provider=sandbox 的 run 不进宿主领取面（通道隔离）。"""
    _seed_host_run(db_session, poll_settings, provider="sandbox")
    with pytest.raises(svc.AgentsServiceError) as ei:
        svc.claim_host_run(presented_token=TOKEN)
    assert ei.value.status == 404


# ---------------------------------------------------------------------------
# 回执：终态对齐 / 产物指纹直录 / 幂等 / 令牌绑定
# ---------------------------------------------------------------------------


def _receipt_payload(*, exit_code=0, artifacts=None, status=None):
    payload = {
        "exit_code": exit_code,
        "summary": SUMMARY,
        "artifacts": artifacts or [],
    }
    if status:
        payload["status"] = status
    return payload


def test_receipt_completed_with_artifacts(db_session, poll_settings):
    run = _seed_host_run(db_session, poll_settings)
    svc.claim_host_run(presented_token=TOKEN)
    arts = [
        {"path": "report.md", "kind": "doc", "source_refs": ["task-1"], "sha256": "a" * 64},
        {"path": "patch.diff", "kind": "diff", "source_refs": ["task-1"], "sha256": "b" * 64},
    ]
    out = svc.submit_host_receipt(presented_token=TOKEN, run_id=run.id, payload=_receipt_payload(artifacts=arts))
    assert out["status"] == "completed" and out["duplicate"] is False and out["failures"] == []
    db_session.expire_all()  # receipt 在另一 session 提交
    row = db_session.get(AgentRun, run.id)
    assert row.status == "completed"
    assert row.host_receipt_at is not None
    assert row.token_cost == 30  # billable_units：投影 totalTokenCount 优先
    arts_rows = db_session.scalars(select(AgentArtifact).where(AgentArtifact.run_id == run.id)).all()
    assert len(arts_rows) == 2
    assert all(a.storage_ref.startswith(f"host:{run.id}/") for a in arts_rows)
    assert all(a.sha256 in ("a" * 64, "b" * 64) for a in arts_rows)
    assert all(a.reviewed is False and a.linked_solution_id is None for a in arts_rows)
    assert all(a.derived_summary is None for a in arts_rows)  # 服务端无原件：诚实置空


def test_receipt_nonzero_exit_failed(db_session, poll_settings):
    run = _seed_host_run(db_session, poll_settings)
    svc.claim_host_run(presented_token=TOKEN)
    out = svc.submit_host_receipt(presented_token=TOKEN, run_id=run.id, payload=_receipt_payload(exit_code=2))
    assert out["status"] == "failed"
    db_session.expire_all()
    assert db_session.get(AgentRun, run.id).status == "failed"


def test_receipt_host_timeout_kept(db_session, poll_settings):
    run = _seed_host_run(db_session, poll_settings)
    svc.claim_host_run(presented_token=TOKEN)
    out = svc.submit_host_receipt(
        presented_token=TOKEN, run_id=run.id, payload=_receipt_payload(exit_code=0, status="timeout")
    )
    assert out["status"] == "timeout"
    db_session.expire_all()
    assert db_session.get(AgentRun, run.id).status == "timeout"


def test_receipt_idempotent_duplicate(db_session, poll_settings):
    run = _seed_host_run(db_session, poll_settings)
    svc.claim_host_run(presented_token=TOKEN)
    first = svc.submit_host_receipt(presented_token=TOKEN, run_id=run.id, payload=_receipt_payload())
    second = svc.submit_host_receipt(presented_token=TOKEN, run_id=run.id, payload=_receipt_payload())
    assert first["duplicate"] is False and second["duplicate"] is True
    assert second["status"] == "completed"


def test_receipt_rejects_after_token_rotation(db_session, poll_settings, monkeypatch):
    """token 轮换后旧代理回执 ⇒ host_poll_forbidden（hash 分支可辨）。"""
    from pydantic import SecretStr

    run = _seed_host_run(db_session, poll_settings)
    svc.claim_host_run(presented_token=TOKEN)
    rotated = poll_settings.model_copy(update={"agent_host_poll_token": SecretStr("rotated-token")})
    monkeypatch.setattr(svc, "_settings", lambda: rotated)
    with pytest.raises(svc.AgentsServiceError) as ei:
        svc.submit_host_receipt(presented_token="rotated-token", run_id=run.id, payload=_receipt_payload())
    assert ei.value.code == "host_poll_forbidden"


def test_receipt_rejects_wrong_token(db_session, poll_settings):
    run = _seed_host_run(db_session, poll_settings)
    svc.claim_host_run(presented_token=TOKEN)
    with pytest.raises(svc.AgentsServiceError) as ei:
        svc.submit_host_receipt(presented_token="other", run_id=run.id, payload=_receipt_payload())
    assert ei.value.code == "host_poll_forbidden"


def test_receipt_rejects_unclaimed_run(db_session, poll_settings):
    """queued（未领取）run 的回执 ⇒ invalid_state（鉴权通过后状态闸）。"""
    run = _seed_host_run(db_session, poll_settings)  # 仍 queued，host_token_hash=None
    with pytest.raises(svc.AgentsServiceError) as ei:
        svc.submit_host_receipt(presented_token=TOKEN, run_id=run.id, payload=_receipt_payload())
    assert ei.value.code == "host_receipt_invalid_state"


def test_receipt_failure_details_not_fatal(db_session, poll_settings):
    """产物校验失败只记 failures 不改终态（H4：人工按明细处置）。"""
    run = _seed_host_run(db_session, poll_settings)
    svc.claim_host_run(presented_token=TOKEN)
    arts = [
        {"path": "../evil.md", "kind": "doc", "source_refs": ["t"], "sha256": "a" * 64},  # unsafe_path
        {"path": "x.md", "kind": "doc", "source_refs": [], "sha256": "a" * 64},  # missing refs
        {"path": "y.md", "kind": "doc", "source_refs": ["t"], "sha256": "short"},  # sha256 缺失
    ]
    out = svc.submit_host_receipt(presented_token=TOKEN, run_id=run.id, payload=_receipt_payload(artifacts=arts))
    assert out["status"] == "completed"  # 终态不被校验失败劫持
    reasons = {r for item in out["failures"] for r in item["reasons"]}
    assert "unsafe_path" in reasons and "missing_source_refs" in reasons and "sha256_missing_in_receipt" in reasons


# ---------------------------------------------------------------------------
# H4：失联只标记
# ---------------------------------------------------------------------------


def test_mark_host_lost_only_marks(db_session, poll_settings):
    old = datetime.now(timezone.utc) - timedelta(minutes=45)
    run = _seed_host_run(db_session, poll_settings, status="host_running", claimed=old)
    out = svc.mark_host_lost()
    assert out["count"] == 1 and out["marked"] == [run.id]
    db_session.expire_all()  # mark 在另一 session 提交——过期本 session 旧快照
    row = db_session.get(AgentRun, run.id)
    assert row.host_lost_at is not None
    assert row.status == "host_running"  # 不迁移状态（H4）
    # 幂等：再扫不重打
    assert svc.mark_host_lost()["count"] == 0


def test_mark_host_lost_young_run_skipped(db_session, poll_settings):
    fresh = datetime.now(timezone.utc) - timedelta(minutes=5)
    _seed_host_run(db_session, poll_settings, status="host_running", claimed=fresh)
    assert svc.mark_host_lost()["count"] == 0


# ---------------------------------------------------------------------------
# HTTP 面烟测（路由→service 接线 + 错误投影）
# ---------------------------------------------------------------------------


def test_host_routes_http_smoke(db_session, poll_settings, d4_settings, monkeypatch):
    from fde_api.app import create_app

    app = create_app(poll_settings)
    app.config.update(TESTING=True)
    client = app.test_client()
    headers = {"X-Host-Poll-Token": TOKEN}

    # 关闭态 → 403（注意：poll_settings fixture 的 svc._settings monkeypatch
    # 在本测试内仍生效——off_app 的路由面走真实 create_app settings，但其
    # service 内部 _settings 被 patch ⇒ 先还原再测关闭态）
    monkeypatch.setattr(svc, "_settings", lambda: d4_settings)
    off_app = create_app(d4_settings)
    off_app.config.update(TESTING=True)
    assert off_app.test_client().get("/api/v1/agents/host/status", headers=headers).status_code == 403
    assert off_app.test_client().get("/api/v1/agents/host/status").status_code == 403  # 无头

    # 开启态：status→claim→receipt 全链（恢复 poll settings 注入）
    monkeypatch.setattr(svc, "_settings", lambda: poll_settings)
    run = _seed_host_run(db_session, poll_settings)
    body = client.get("/api/v1/agents/host/status", headers=headers)
    assert body.status_code == 200 and body.json["data"]["pending"] == 1
    body = client.post("/api/v1/agents/host/claim", headers=headers, json={})
    assert body.status_code == 200 and body.json["data"]["run_id"] == run.id
    body = client.post(
        f"/api/v1/agents/host/runs/{run.id}/receipt",
        headers=headers,
        json=_receipt_payload(artifacts=[{"path": "o.md", "kind": "doc", "source_refs": ["t"], "sha256": "a" * 64}]),
    )
    assert body.status_code == 200 and body.json["data"]["status"] == "completed"
    # 错误投影：坏令牌
    body = client.get("/api/v1/agents/host/status", headers={"X-Host-Poll-Token": "bad"})
    assert body.status_code == 403 and body.json["error"]["code"] == "host_poll_forbidden"
