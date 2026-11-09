"""N1 首跑补码轮：短期执行授权票据的生产接线（V3.1 任务书 §9 前置 3）。

背景：D-1 拍板开闸（2026-11-09）后，P1-1 落地的票据纯函数
（``issue_execution_grant`` / ``verify_execution_grant``）此前**全仓零生产
调用方**——5.10 闸未过故 HTTP 发行面不建。本文件钉住「发行 + 校验双接线」：

- 纯函数层：绑定五要素（用户/项目/Run/工作目录/动作）的反例齐备；
- 生产层：宿主通道 run 落 ``authorization_id`` **指纹**（非票据本体），
  校验失败 ⇒ **不 spawn**、503 + L2、零计费；
- 未开通道时零影响（容器路径不签发票据）。
"""
from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from test_agents_d4_harness import (  # noqa: F401  (pytest fixtures)
    d4_app,
    d4_client,
    d4_settings,
    api_client,
    issue_access_token,
    make_user,
    prime_run,
    seed_agent,
)
from test_document_drafts_api import _persist_project

from fde_api.agents import host_channel as hc
from fde_api.agents.execution_authorization import ExecutionGrantError
from fde_api.agents.execution_grants import (
    HOST_CHANNEL_ACTIONS,
    derive_grant_secret,
    grant_fingerprint,
    issue_run_grant,
    verify_run_grant,
)
from fde_api.agents.models import AgentRun

_SECRET = "unit-test-jwt-secret-0123456789abcdef"


# ---------------------------------------------------------------------------
# 纯函数层：绑定与拒绝
# ---------------------------------------------------------------------------


def test_grant_secret_is_domain_separated_and_deterministic() -> None:
    """派生密钥与 JWT 密钥**不同钥**（域分离），且同输入恒同输出。"""
    derived = derive_grant_secret(_SECRET)
    assert derived == derive_grant_secret(_SECRET)
    assert derived != _SECRET.encode("utf-8")
    assert len(derived) == 32  # sha256 摘要——恰好满足 issue 侧 ≥32 字节要求
    with pytest.raises(ExecutionGrantError):
        derive_grant_secret("")


def test_grant_binds_run_actions_and_expiry() -> None:
    """票据绑定 Run 与动作集合；错 run / 缺动作 / 过期 / 篡改四类反例必拒。"""
    now = datetime.now(UTC)
    token = issue_run_grant(
        jwt_secret=_SECRET,
        user_id="u-1",
        project_id="p-1",
        run_id="run-1",
        workspace="C:/ws/run-1",
        issued_at=now,
    )
    payload = verify_run_grant(
        jwt_secret=_SECRET, token=token, run_id="run-1", now=now + timedelta(seconds=5)
    )
    assert payload["user_id"] == "u-1"
    assert payload["project_id"] == "p-1"
    assert payload["workspace"] == "C:/ws/run-1"
    assert payload["actions"] == sorted(HOST_CHANNEL_ACTIONS)

    with pytest.raises(ExecutionGrantError) as exc:
        verify_run_grant(jwt_secret=_SECRET, token=token, run_id="run-2", now=now)
    assert exc.value.code == "run_mismatch"

    with pytest.raises(ExecutionGrantError) as exc:
        verify_run_grant(
            jwt_secret=_SECRET,
            token=token,
            run_id="run-1",
            required_actions=("command.run", "artifact.publish"),
            now=now,
        )
    assert exc.value.code == "action_exceeded"

    with pytest.raises(ExecutionGrantError) as exc:
        verify_run_grant(
            jwt_secret=_SECRET, token=token, run_id="run-1", now=now + timedelta(minutes=16)
        )
    assert exc.value.code == "expired"

    tampered = token[:-1] + ("A" if token[-1] != "A" else "B")
    with pytest.raises(ExecutionGrantError) as exc:
        verify_run_grant(jwt_secret=_SECRET, token=tampered, run_id="run-1", now=now)
    assert exc.value.code == "tampered"

    # 换密钥（域分离派生 ⇒ 另一把密钥签的票据不可用）
    with pytest.raises(ExecutionGrantError) as exc:
        verify_run_grant(
            jwt_secret="another-secret-0123456789abcdefXYZ", token=token, run_id="run-1", now=now
        )
    assert exc.value.code == "tampered"


def test_grant_fingerprint_is_sha256_of_token_not_token() -> None:
    """``authorization_id`` 落的是 sha256 指纹，**不是票据本体**（能力凭证不落盘）。"""
    token = issue_run_grant(
        jwt_secret=_SECRET,
        user_id="u-1",
        project_id="p-1",
        run_id="run-1",
        workspace="C:/ws/run-1",
    )
    fingerprint = grant_fingerprint(token)
    assert len(fingerprint) == 64
    assert fingerprint == hashlib.sha256(token.encode("utf-8")).hexdigest()
    assert token not in fingerprint


# ---------------------------------------------------------------------------
# 生产层：宿主通道接线
# ---------------------------------------------------------------------------


class _Proc:
    pid = 9

    def kill(self) -> None:
        pass

    def communicate(self, timeout=None):  # noqa: ANN001
        return json.dumps({"usage": {"outputTokens": 7}}), ""

    @property
    def returncode(self) -> int:
        return 0


class _NoArtifactScanner:
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


def test_host_channel_run_records_authorization_fingerprint(db_session, d4_settings, monkeypatch):
    """宿主通道 run：``authorization_id`` 落指纹（非明文）、``workspace_ref`` 落工作区。"""
    from fde_api.app import create_app

    settings = _host_settings(d4_settings)
    app = create_app(settings)
    app.config.update(TESTING=True)
    app.extensions["fde_agent_output_scanner_factory"] = lambda run_id, workspace: _NoArtifactScanner()
    monkeypatch.setattr(hc, "_default_spawner", lambda argv, **kwargs: _Proc())

    leader = api_client(app.test_client(), db_session, settings, "project_lead")
    project = _persist_project(db_session, leader.user, code="GRT1")
    agent = seed_agent(db_session, settings)

    body = leader.post(
        f"/api/v1/agents/{agent.id}/run",
        json={"project_id": project.id, "idempotency_key": "grant-1"},
    )
    assert body.status_code == 201, body.json
    assert body.json["data"]["status"] == "completed"

    db_session.commit()
    stored = db_session.scalar(select(AgentRun).where(AgentRun.idempotency_key == "grant-1"))
    assert stored is not None
    assert stored.authorization_id is not None
    assert len(stored.authorization_id) == 64  # sha256 指纹
    assert stored.workspace_ref is not None and stored.workspace_ref.endswith(stored.id)


def test_grant_rejection_blocks_spawn_and_lands_l2(db_session, d4_settings, monkeypatch):
    """校验失败 ⇒ **不 spawn** + 503 + L2 + 零计费（fail-closed，不裸奔）。"""
    from fde_api.app import create_app

    settings = _host_settings(d4_settings)
    app = create_app(settings)
    app.config.update(TESTING=True)
    app.extensions["fde_agent_output_scanner_factory"] = lambda run_id, workspace: _NoArtifactScanner()

    spawned: list[object] = []

    def _spawner(argv, **kwargs):  # noqa: ANN001
        spawned.append(argv)
        return _Proc()

    monkeypatch.setattr(hc, "_default_spawner", _spawner)

    def _reject(**kwargs):  # noqa: ANN003
        raise ExecutionGrantError("expired", "票据已过期。")

    # patch 在**使用点**：authorize_host_run（execution_grants 内）调用 verify 的位置
    from fde_api.agents import execution_grants as grants_module

    monkeypatch.setattr(grants_module, "verify_run_grant", _reject)

    leader = api_client(app.test_client(), db_session, settings, "project_lead")
    project = _persist_project(db_session, leader.user, code="GRT2")
    agent = seed_agent(db_session, settings)

    body = leader.post(
        f"/api/v1/agents/{agent.id}/run",
        json={"project_id": project.id, "idempotency_key": "grant-2"},
    )
    assert body.status_code == 503, body.json
    assert body.json["error"]["details"]["reason"] == "execution_grant_rejected:expired"
    assert spawned == []  # **未 spawn**——校验在 spawn 之前

    db_session.commit()
    stored = db_session.scalar(select(AgentRun).where(AgentRun.idempotency_key == "grant-2"))
    assert stored is not None and stored.fallback_level == "L2"
    assert stored.token_cost == 0


def test_container_path_issues_no_grant(db_session, d4_client, d4_app, d4_settings):
    """宿主通道未开（默认）：走容器沙箱路径，**不签发票据**（零行为变化）。"""
    from test_agents_d4_harness import FakeClock, ScriptedEvents

    leader = api_client(d4_client, db_session, d4_settings, "project_lead")
    project = _persist_project(db_session, leader.user, code="GRT3")
    agent = seed_agent(db_session, d4_settings)
    prime_run(
        d4_app,
        events=ScriptedEvents([[{"type": "done", "exit_code": 0}]]),
        clock=FakeClock(),
    )

    body = leader.post(
        f"/api/v1/agents/{agent.id}/run",
        json={"project_id": project.id, "idempotency_key": "grant-3"},
    )
    assert body.status_code == 201, body.json
    assert body.json["data"]["status"] == "completed"

    db_session.commit()
    stored = db_session.scalar(select(AgentRun).where(AgentRun.idempotency_key == "grant-3"))
    assert stored is not None
    assert stored.authorization_id is None  # 容器路径零新增留痕
