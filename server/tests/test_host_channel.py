"""T-Z1 裁定 A 实施轮：宿主侧 zcode 代理通道（agents/host_channel.py）。

覆盖面：argv/env 真实契约（T-Z1 §1.1）· workspace 拒绝清单 · --json 解析
fail-closed · 超时熔断 · 预算截断 · 凭据零注入降级 L1 · 失败/成功全路径。
全部免锁纯单元（无 DB / 无 app / 无 docker / 无 zcode）。
"""
from __future__ import annotations

import json

import pytest

from fde_api.agents.adapter import AgentRunContext
from fde_api.agents.host_channel import (
    PROMPT_MODE,
    ZCODE_CJS_ENV,
    HostChannelError,
    HostChannelSettings,
    assert_host_workspace_allowed,
    host_channel_argv,
    host_channel_env,
    parse_host_summary,
    run_host_channel,
    summarize_host_payload,
    task_prompt,
)


# ---------------------------------------------------------------------------
# 假件
# ---------------------------------------------------------------------------


class FakeProc:
    def __init__(self, *, stdout="", stderr="", returncode=0, delay_exceeds=False):
        self.pid = 4242
        self._stdout = stdout
        self._stderr = stderr
        self._returncode = returncode
        self._delay_exceeds = delay_exceeds
        self.killed = False
        self.communicate_calls = 0

    @property
    def returncode(self) -> int:
        return self._returncode

    def kill(self) -> None:
        self.killed = True

    def communicate(self, timeout=None):  # noqa: ANN001 - 测试假件
        self.communicate_calls += 1
        if self._delay_exceeds and timeout is not None:
            import subprocess

            raise subprocess.TimeoutExpired(cmd="zcode", timeout=timeout)
        return self._stdout, self._stderr


class RecordingSpawner:
    def __init__(self, proc: FakeProc):
        self.proc = proc
        self.calls: list[dict] = []

    def __call__(self, argv, *, env, cwd, stdout, stderr, stdin):  # noqa: ANN001
        self.calls.append({"argv": list(argv), "env": dict(env), "cwd": cwd})
        return self.proc


class FakeScanner:
    receipt_state = "ok"

    def __init__(self, artifacts=()):
        self._artifacts = artifacts
        self.scanned = False

    def scan(self):
        self.scanned = True
        return list(self._artifacts)


class FakeClock:
    def __init__(self, step: float = 0.0):
        self._now = 0.0
        self._step = step

    def __call__(self) -> float:
        value = self._now
        self._now += self._step
        return value


def _ctx(*, timeout_ms=300_000, max_cost_units=0, credentials=None, workspace="D:/ws/agent-workspaces/run-1"):
    return AgentRunContext(
        run_id="run-1",
        project_code="somwyn",
        capability="agent.code.write",
        workspace_host=workspace,
        allowed_tools=frozenset({"read_file"}),
        credentials=credentials or {},
        timeout_ms=timeout_ms,
        max_cost_units=max_cost_units,
    )


_SETTINGS = HostChannelSettings(zcode_bin="C:/zcode/ZCode.exe", cjs_path="C:/zcode/resources/glm/zcode.cjs")

_SUMMARY = {
    "sessionId": "sess_abbc2b87",
    "traceId": "tr_1",
    "turnId": "t1",
    "response": "收到",
    "usage": {"outputTokens": 128, "inputTokens": 64, "modelRequestCount": 1},
    "eventCount": 3,
    "projection": {"status": "done"},
}


# ---------------------------------------------------------------------------
# 契约面：argv / env / prompt
# ---------------------------------------------------------------------------


def test_argv_matches_tz1_measured_contract() -> None:
    """argv 与 T-Z1 §1.1 实测契约逐位吻合（-p/--json/--cwd/--mode，无 run 子命令）。"""
    argv = host_channel_argv(
        zcode_bin="C:/zcode/ZCode.exe",
        cjs_path="C:/zcode/resources/glm/zcode.cjs",
        prompt="do it",
        workspace="D:/ws/run-1",
    )
    assert argv[0] == "C:/zcode/ZCode.exe"
    assert argv[1] == "C:/zcode/resources/glm/zcode.cjs"
    assert "-p" in argv and "do it" in argv
    assert "--json" in argv
    assert argv[argv.index("--cwd") + 1] == "D:/ws/run-1"
    assert argv[argv.index("--mode") + 1] == PROMPT_MODE
    assert "run" not in argv  # T-Z1 勘误③：不存在 run 子命令


def test_env_carries_electron_run_as_node_and_no_platform_credentials() -> None:
    env = host_channel_env()
    assert env[ZCODE_CJS_ENV] == "1"


def test_prompt_carries_task_file_path() -> None:
    prompt = task_prompt("D:/ws/run-1")
    assert "task.md" in prompt and "D:/ws/run-1" in prompt


# ---------------------------------------------------------------------------
# workspace 拒绝清单
# ---------------------------------------------------------------------------


def test_workspace_forbidden_markers_rejected() -> None:
    for bad in ("D:/test/fde/agent-workspaces/r1", "C:/proj/.env/run", "D:/fdeops/ws", "D:/openfde/ws"):
        with pytest.raises(HostChannelError, match="拒绝清单"):
            assert_host_workspace_allowed(bad)


def test_workspace_agent_root_allowed() -> None:
    assert_host_workspace_allowed("D:/ws/agent-workspaces/run-1")


# ---------------------------------------------------------------------------
# --json 汇总解析（fail-closed）
# ---------------------------------------------------------------------------


def test_parse_summary_happy_path() -> None:
    payload = parse_host_summary(json.dumps(_SUMMARY))
    assert summarize_host_payload(payload) == 192  # billable_units = input 64 + output 128


def test_parse_summary_tolerates_prefix_noise() -> None:
    noisy = "zcode 0.17.1\n" + json.dumps(_SUMMARY) + "\n"
    assert summarize_host_payload(parse_host_summary(noisy)) == 192


def test_parse_summary_empty_is_fail_closed() -> None:
    with pytest.raises(HostChannelError):
        parse_host_summary("")


def test_parse_summary_non_object_is_fail_closed() -> None:
    with pytest.raises(HostChannelError):
        parse_host_summary("plain text without json")


def test_usage_missing_or_invalid_counts_zero_honestly() -> None:
    assert summarize_host_payload({"sessionId": "s"}) == 0
    assert summarize_host_payload({"usage": {"outputTokens": -5}}) == 0
    assert summarize_host_payload({"usage": "weird"}) == 0


# ---------------------------------------------------------------------------
# run 全路径
# ---------------------------------------------------------------------------


def test_completed_path_scans_artifacts_and_returns_summary() -> None:
    proc = FakeProc(stdout=json.dumps(_SUMMARY), returncode=0)
    spawner = RecordingSpawner(proc)
    scanner = FakeScanner()
    clock = FakeClock(step=1.0)
    result = run_host_channel(
        _ctx(),
        _SETTINGS,
        output_scanner=scanner,
        spawner=spawner,
        clock=clock,
    )
    assert result.status == "completed"
    assert result.exit_code == 0
    assert result.token_cost == 192  # billable_units 口径
    assert result.duration_ms == 2000  # started + argv 构造两跳
    assert result.artifacts == () and scanner.scanned is True
    assert result.degraded is False and result.degraded_reason is None
    # spawn 事实：env 转 node、cwd 锚 workspace、prompt 携带任务书
    call = spawner.calls[0]
    assert call["env"][ZCODE_CJS_ENV] == "1"
    assert call["cwd"] == "D:/ws/agent-workspaces/run-1"
    assert "task.md" in " ".join(call["argv"])


def test_timeout_kills_and_reports_timeout() -> None:
    proc = FakeProc(delay_exceeds=True)
    spawner = RecordingSpawner(proc)
    clock = FakeClock(step=301.0)  # 第二跳已过 300s deadline
    result = run_host_channel(
        _ctx(timeout_ms=300_000),
        _SETTINGS,
        output_scanner=FakeScanner(),
        spawner=spawner,
        clock=clock,
    )
    assert result.status == "timeout"
    assert proc.killed is True
    assert proc.communicate_calls == 2  # 超时后仍回收 stdout/stderr（缓冲不悬挂）
    assert result.artifacts == ()


def test_nonzero_exit_maps_to_failed_with_zero_artifacts() -> None:
    proc = FakeProc(stdout="", stderr="boom", returncode=2)
    result = run_host_channel(
        _ctx(),
        _SETTINGS,
        output_scanner=FakeScanner(),
        spawner=RecordingSpawner(proc),
        clock=FakeClock(step=0.5),
    )
    assert result.status == "failed"
    assert result.exit_code == 2
    assert result.artifacts == ()


def test_exit_zero_with_unparsable_summary_fails_closed() -> None:
    """退出码 0 但汇总不可解析：HostChannelError 冒泡（L2 降级），不伪造 completed。"""
    proc = FakeProc(stdout="not json", returncode=0)
    with pytest.raises(HostChannelError):
        run_host_channel(
            _ctx(),
            _SETTINGS,
            output_scanner=FakeScanner(),
            spawner=RecordingSpawner(proc),
            clock=FakeClock(),
        )


def test_budget_exceeded_truncates_cost_and_discards_artifacts() -> None:
    """B-2 宿主版：成本超上限按上限截断 + budget_exceeded（越界不入账）。"""
    proc = FakeProc(stdout=json.dumps(_SUMMARY), returncode=0)  # billable 192
    result = run_host_channel(
        _ctx(max_cost_units=150),
        _SETTINGS,
        output_scanner=FakeScanner(),
        spawner=RecordingSpawner(proc),
        clock=FakeClock(),
    )
    assert result.status == "budget_exceeded"
    assert result.token_cost == 150
    assert result.artifacts == ()


def test_budget_within_cap_is_completed() -> None:
    proc = FakeProc(stdout=json.dumps(_SUMMARY), returncode=0)
    result = run_host_channel(
        _ctx(max_cost_units=192),
        _SETTINGS,
        output_scanner=FakeScanner(),
        spawner=RecordingSpawner(proc),
        clock=FakeClock(),
    )
    assert result.status == "completed"


def test_decrypted_credentials_mark_degraded_l1_not_injected() -> None:
    """差异 3：平台凭据解密结果未被宿主通道使用 ⇒ degraded（L1 强制人工终审）。"""
    proc = FakeProc(stdout=json.dumps(_SUMMARY), returncode=0)
    spawner = RecordingSpawner(proc)
    result = run_host_channel(
        _ctx(credentials={"FDE_AGENT_ZCODE_PROD": "zkey-secret"}),
        _SETTINGS,
        output_scanner=FakeScanner(),
        spawner=spawner,
        clock=FakeClock(),
    )
    assert result.status == "completed"
    assert result.degraded is True
    assert result.degraded_reason == "host_channel_no_credential_injection"
    # 凭据值零外泄：spawn env 只有系统 env + ELECTRON_RUN_AS_NODE，无凭据键
    assert "FDE_AGENT_ZCODE_PROD" not in spawner.calls[0]["env"]
    assert "zkey-secret" not in json.dumps(spawner.calls[0]["env"])


def test_spawner_os_error_raises_host_channel_error() -> None:
    def bad_spawner(argv, *, env, cwd, stdout, stderr, stdin):  # noqa: ANN001
        raise OSError("no such binary")

    with pytest.raises(HostChannelError, match="拉起失败"):
        run_host_channel(
            _ctx(),
            _SETTINGS,
            output_scanner=FakeScanner(),
            spawner=bad_spawner,
            clock=FakeClock(),
        )


def test_workspace_marker_checked_before_spawn() -> None:
    """红线先于 spawn：拒绝清单命中时根本不拉进程。"""
    ran = False

    def guard_spawner(argv, *, env, cwd, stdout, stderr, stdin):  # noqa: ANN001
        nonlocal ran
        ran = True
        raise AssertionError("不应到达 spawn")

    with pytest.raises(HostChannelError):
        run_host_channel(
            _ctx(workspace="D:/test/fde/ws"),
            _SETTINGS,
            output_scanner=FakeScanner(),
            spawner=guard_spawner,
            clock=FakeClock(),
        )
    assert ran is False
