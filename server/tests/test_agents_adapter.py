"""goal-d4：zcode 适配器三段 + V1 注册可见 + V3 前半 denied 留痕。

三段（技术文档 §5）：spawn（凭据经沙箱 exec 注入拉起 CLI）/ 监听（结构化
事件 → 白名单判定 + 成本累计 + 超时/预算熔断）/ 回收（kill + 产物扫描）。
"""
from __future__ import annotations

import pytest

from test_agents_d4_harness import (
    FakeClock,
    FakeScanner,
    ScriptedEvents,
    api_client,
    seed_agent,
)
from fde_api.agents.adapter import AgentRunContext, ArtifactFile, ZcodeAdapter, spawn_argv
from fde_api.agents.sandbox import SandboxError
from fde_api.agents.service import list_agents

from test_agents_d4_harness import d4_app, d4_client, d4_settings  # noqa: F401  (pytest fixture)


class FakeHandle:
    """适配器单元测试的沙箱替身：只记录 exec/kill 行为。"""

    def __init__(self, *, fail_exec: str | None = None) -> None:
        self.execs: list[tuple[dict, list[str]]] = []
        self.kill_count = 0
        self.fail_exec = fail_exec

    def exec(self, credentials, command) -> None:
        if self.fail_exec:
            raise SandboxError(self.fail_exec)
        self.execs.append((dict(credentials), list(command)))

    def kill(self) -> None:
        self.kill_count += 1


def _ctx(*, allowed=("read_file",), timeout_ms=300_000, max_cost_units=0):
    return AgentRunContext(
        run_id="run-adapter",
        project_code="somwyn",
        capability="agent.code.write",
        workspace_host="/tmp/ws",
        allowed_tools=frozenset(allowed),
        credentials={"FDE_AGENT_ZCODE_PROD": "zkey-1234567890"},
        timeout_ms=timeout_ms,
        max_cost_units=max_cost_units,
    )


def _run(adapter_ctx, handle, events, *, scanner=None, clock=None, sleeper=None):
    adapter = ZcodeAdapter()
    return adapter.run(
        adapter_ctx,
        handle,
        event_provider=events,
        output_scanner=scanner or FakeScanner([]),
        clock=clock or FakeClock(),
        sleeper=sleeper or (lambda _seconds: None),
    )


# ---------------------------------------------------------------------------
# 三段单元行为
# ---------------------------------------------------------------------------


def test_spawn_listen_reclaim_completed_path() -> None:
    """完成路径：spawn argv 口径 → 事件记账 → 回收 kill + 产物扫描。"""
    handle = FakeHandle()
    events = ScriptedEvents(
        [
            [{"type": "tool_call", "tool": "read_file", "duration_ms": 12}, {"type": "cost", "units": 40}],
            [{"type": "done", "exit_code": 0}],
        ]
    )
    result = _run(_ctx(), handle, events, scanner=FakeScanner([ArtifactFile(path="plan.md", kind="doc", source_refs=("src-1",))]))

    # ① spawn：容器内 CLI 参数口径，凭据经 handle.exec（env 内存管道）
    assert len(handle.execs) == 1
    credentials, command = handle.execs[0]
    assert command == [
        "zcode", "run", "--task", "/workspace/task.md",
        "--output", "/workspace/output", "--events", "ndjson",
    ]
    assert credentials == {"FDE_AGENT_ZCODE_PROD": "zkey-1234567890"}
    assert spawn_argv(cli_command="zcode", task_file="task.md", output_dir="output") == command
    # ② 监听：成本与白名单判定
    assert result.token_cost == 40
    assert result.tool_calls[0].decision == "allowed"
    # ③ 回收：kill 恰一次，completed 才认产物
    assert handle.kill_count == 1
    assert result.status == "completed" and result.exit_code == 0
    assert len(result.artifacts) == 1 and result.artifacts[0].path == "plan.md"
    assert result.degraded is False


def test_tool_outside_allowlist_denied_and_run_degraded() -> None:
    """V3 前半 / D-1：越权调用 denied 留痕，run 继续但标 degraded。"""
    handle = FakeHandle()
    events = ScriptedEvents(
        [
            [{"type": "tool_call", "tool": "write_file", "duration_ms": 5}],
            [{"type": "tool_call", "tool": "read_file"}],
            [{"type": "done", "exit_code": 0}],
        ]
    )
    result = _run(_ctx(allowed=("read_file",)), handle, events)
    denied, allowed = result.tool_calls
    assert (denied.tool_name, denied.decision, denied.reason) == ("write_file", "denied", "not_in_allowlist")
    assert (allowed.tool_name, allowed.decision) == ("read_file", "allowed")
    assert result.degraded is True and result.degraded_reason == "tool_denied"
    assert result.status == "completed"


def test_timeout_circuit_kills_and_discards_artifacts() -> None:
    """B-1 单元面：deadline 触发 timeout → kill，扫描到的产物一律作废。"""
    clock = FakeClock()
    handle = FakeHandle()
    events = ScriptedEvents([[{"type": "tool_call", "tool": "read_file"}]])  # 耗尽后空转
    result = _run(
        _ctx(timeout_ms=1000),
        handle,
        events,
        scanner=FakeScanner([ArtifactFile(path="late.md", kind="doc", source_refs=("src-1",))]),
        clock=clock,
        sleeper=clock.sleep,
    )
    assert result.status == "timeout"
    assert result.token_cost == 0 and result.artifacts == ()
    assert handle.kill_count == 1
    assert result.duration_ms >= 1000


def test_budget_circuit_keeps_cost_under_cap() -> None:
    """B-2 单元面：越界事件不入账直接熔断——成本停在阈值内。"""
    handle = FakeHandle()
    events = ScriptedEvents([[{"type": "cost", "units": 5}], [{"type": "cost", "units": 10}]])
    result = _run(_ctx(max_cost_units=10), handle, events, clock=FakeClock(), sleeper=lambda _s: None)
    assert result.status == "budget_exceeded"
    assert result.token_cost == 5  # 5 + 10 > 10：第二条不应用
    assert handle.kill_count == 1


def test_spawn_sandbox_error_propagates_as_class_a() -> None:
    """沙箱注入失败（A 类）：异常上抛，由 service 落 L2 零计费。"""
    handle = FakeHandle(fail_exec="sandbox_command_failed")
    with pytest.raises(SandboxError, match="sandbox_command_failed"):
        _run(_ctx(), handle, ScriptedEvents([]))


# ---------------------------------------------------------------------------
# V1：注册表可见性（GET /agents 含不可用原因）
# ---------------------------------------------------------------------------


def test_get_agents_lists_registry_with_availability_reasons(db_session, d4_client, d4_app, d4_settings) -> None:
    """V1：zcode 注册成功且接口可见；disabled/adapter_missing/credential_missing 报因。"""
    available = seed_agent(db_session, d4_settings)
    seed_agent(db_session, d4_settings, name="停用智能体", enabled=False, credential_ref=None)
    seed_agent(db_session, d4_settings, kind="codex", name="Codex 预留", credential_ref=None)
    seed_agent(db_session, d4_settings, name="缺凭据", credential_ref=None)

    leader = api_client(d4_client, db_session, d4_settings, "project_lead")
    body = leader.get("/api/v1/agents")
    assert body.status_code == 200
    items = {item["name"]: item for item in body.json["data"]["items"]}
    # goal-d7：list_agents 懒装载编排种子（守卫+六模块智能体+三角色卡）+10
    assert len(items) == 4 + 10
    assert items["ZCode 沙箱智能体"]["available"] is True
    assert items["ZCode 沙箱智能体"]["id"] == available.id
    assert items["停用智能体"]["unavailable_reason"] == "disabled"
    assert items["Codex 预留"]["unavailable_reason"] == "adapter_missing"
    assert items["缺凭据"]["unavailable_reason"] == "credential_missing"
    # 未认证不可见
    assert d4_client.get("/api/v1/agents").status_code == 401


def test_registry_service_view_matches_api_shape(db_session, d4_settings) -> None:
    """服务层视图（list_agents）与路由同形——unavailable 原因枚举收口。"""
    from test_agents_d4_harness import make_user

    seed_agent(db_session, d4_settings, enabled=False, credential_ref=None)
    viewer = make_user(db_session, "project_lead")
    view = list_agents(actor=viewer)  # actor 不参与注册表读取（只读公共面）
    assert set(view["items"][0]) >= {"available", "unavailable_reason", "allowed_tools"}


def test_sandbox_failure_lands_l2_without_billing(db_session, d4_client, d4_app, d4_settings) -> None:
    """A-1 接线：沙箱拉起失败 → 503 agent_unavailable + run 落 L2 + 零计费。"""
    from sqlalchemy import select

    from fde_api.agents.models import AgentRun
    from test_agents_d4_harness import RecordingBackend, prime_run
    from test_document_drafts_api import _persist_project

    leader = api_client(d4_client, db_session, d4_settings, "project_lead")
    project = _persist_project(db_session, leader.user, code="D4A1")
    agent = seed_agent(db_session, d4_settings)
    prime_run(d4_app, backend=RecordingBackend(fail="sandbox_runtime_missing"))

    body = leader.post(f"/api/v1/agents/{agent.id}/run", json={"project_id": project.id, "idempotency_key": "a1-1"})
    assert body.status_code == 503
    error = body.json["error"]
    assert error["code"] == "agent_unavailable"
    assert error["details"]["fallback_level"] == "L2"

    stored = db_session.scalar(select(AgentRun).where(AgentRun.idempotency_key == "a1-1"))
    assert stored is not None  # run 落库作为降级证据
    assert stored.fallback_level == "L2"
    assert stored.status == "failed"
    assert stored.degraded is True
    assert stored.degraded_reason == "sandbox_runtime_missing"
    assert stored.token_cost == 0  # 零计费
