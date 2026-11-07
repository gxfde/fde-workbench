"""T-Z1 实施轮准备：zcode 0.17.1 真实 CLI 契约 + `--json` 汇总夹具回放。

夹具形状取自 #191 真机实测样本，内容全部自拟（「收到」），**零客户资料、
零真实凭据、零真实 sessionId**；原始实测样本 `D:\\test\\FDE\\tz1-probe\\*.json`
只留本地、永不进仓（AGENTS.md 红线）。
"""
from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, cast

import pytest

from fde_api.agents.adapter import AgentRunContext, ArtifactFile, ZcodeAdapter
from fde_api.agents.sandbox import SandboxHandle
from fde_api.agents.zcode_contract import (
    ZCODE_CLI_VERSION,
    JsonSummaryEventProvider,
    build_cli_argv,
    parse_json_summary,
    summary_to_events,
)

FIXTURE = Path(__file__).parent / "fixtures" / "zcode_json_summary.json"


def _payload() -> dict[str, Any]:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# 真实 CLI argv（#191 §1.1 实测；防回归到登记原文的虚构契约）
# ---------------------------------------------------------------------------


def test_cli_version_pinned_to_measured_0171() -> None:
    assert ZCODE_CLI_VERSION == "0.17.1"


def test_build_cli_argv_matches_real_contract() -> None:
    assert build_cli_argv(prompt="输出两个计划要点", cwd="D:/agent-ws/run-1") == [
        "zcode",
        "-p",
        "输出两个计划要点",
        "--json",
        "--cwd",
        "D:/agent-ws/run-1",
    ]


def test_build_cli_argv_never_emits_legacy_fiction() -> None:
    """登记原文③的 `run --task --output --events ndjson` 不得再现。"""
    argv = build_cli_argv(prompt="p", cwd="c")
    for forbidden in ("run", "--task", "--output", "--events", "ndjson"):
        assert forbidden not in argv


def test_build_cli_argv_mode_and_resume_are_value_flags() -> None:
    assert build_cli_argv(
        prompt="p",
        cwd="c",
        cli_command="zcode-wrapper",
        mode="plan",
        resume_session_id="sess_abc",
    ) == [
        "zcode-wrapper",
        "-p",
        "p",
        "--json",
        "--cwd",
        "c",
        "--mode",
        "plan",
        "--resume",
        "sess_abc",
    ]


def test_build_cli_argv_rejects_blank_prompt_and_cwd() -> None:
    with pytest.raises(ValueError, match="zcode_cli_prompt_required"):
        build_cli_argv(prompt="   ", cwd="c")
    with pytest.raises(ValueError, match="zcode_cli_cwd_required"):
        build_cli_argv(prompt="p", cwd="")


# ---------------------------------------------------------------------------
# `--json` 单对象汇总解析（#191 §1.1 实测形状）
# ---------------------------------------------------------------------------


def test_parse_json_summary_maps_measured_usage_fields() -> None:
    summary = parse_json_summary(_payload())
    assert summary.session_id == "sess_fixture_0001"
    assert summary.trace_id == "trace_fixture_0001"
    assert summary.status == "completed"
    assert summary.input_tokens == 120
    assert summary.output_tokens == 2
    assert summary.cache_read_tokens == 0
    assert summary.model_request_count == 1
    assert summary.event_count == 2
    assert summary.total_token_count == 122
    assert summary.billable_units == 122


def test_parse_json_summary_tolerates_missing_and_wrong_types() -> None:
    """缺字段/坏类型如实归零，不猜测不发明数字（P3 数据闸同款纪律）。"""
    summary = parse_json_summary(
        {
            "usage": {"inputTokens": "120", "outputTokens": -3},
            "projection": {"totalTokenCount": True},
            "eventCount": None,
        }
    )
    assert summary.input_tokens == 0
    assert summary.output_tokens == 0
    assert summary.total_token_count == 0  # bool 不是合法计数
    assert summary.billable_units == 0
    assert summary.session_id == ""
    assert summary.status == ""


def test_billable_units_falls_back_to_io_tokens() -> None:
    summary = parse_json_summary(
        {"usage": {"inputTokens": 40, "outputTokens": 7}, "projection": {}}
    )
    assert summary.total_token_count == 0
    assert summary.billable_units == 47


def test_summary_to_events_cost_then_done_without_fabricated_tool_calls() -> None:
    events = summary_to_events(parse_json_summary(_payload()))
    assert [event["type"] for event in events] == ["cost", "done"]
    assert events[0]["units"] == 122
    assert events[1]["exit_code"] == 0
    assert all(event["type"] != "tool_call" for event in events)


def test_fixture_shape_matches_measured_summary_keys() -> None:
    """夹具形状钉：与 #191 实测汇总同键集，防止后续轮悄悄改形状。"""
    payload = _payload()
    assert {"sessionId", "traceId", "turnId", "response", "usage", "eventCount", "projection"} <= set(payload)
    assert {"modelRequestCount", "inputTokens", "outputTokens", "cacheReadTokens"} <= set(payload["usage"])
    assert {"status", "turnCount", "totalTokenCount"} <= set(payload["projection"])
    text = FIXTURE.read_text(encoding="utf-8")
    assert "D:\\test\\FDE" not in text and "FDE_AGENT" not in text


# ---------------------------------------------------------------------------
# 固定夹具回放（B#14 组织方式）与既有监听段咬合
# ---------------------------------------------------------------------------


def test_json_summary_provider_polls_once_then_empty() -> None:
    provider = JsonSummaryEventProvider.from_payload(_payload())
    first = provider.poll()
    assert [event["type"] for event in first] == ["cost", "done"]
    assert provider.poll() == ()
    assert provider.poll() == ()


def test_json_summary_provider_from_file_replays_fixture() -> None:
    provider = JsonSummaryEventProvider.from_file(FIXTURE)
    assert [event["units"] for event in provider.poll() if event["type"] == "cost"] == [122]


def test_from_file_rejects_non_object_payload(tmp_path: Path) -> None:
    bad = tmp_path / "not-object.json"
    bad.write_text("[1, 2]", encoding="utf-8")
    with pytest.raises(ValueError, match="zcode_json_summary_must_be_object"):
        JsonSummaryEventProvider.from_file(bad)


class _Handle:
    def __init__(self) -> None:
        self.commands: list[Sequence[str]] = []
        self.kills = 0

    def exec(self, credentials: Mapping[str, str], command: Sequence[str]) -> None:
        self.commands.append(list(command))

    def kill(self) -> None:
        self.kills += 1


class _Scanner:
    def scan(self) -> tuple[ArtifactFile, ...]:
        return ()


def test_summary_events_drive_existing_adapter_listen_loop() -> None:
    """汇总回放能直接喂给既有 `ZcodeAdapter` 监听段（同一 cost/done 语义）。

    证明新契约模块与适配器既有超时/成本/回收逻辑咬合，无需先改 spawn 段；
    `sandbox` 用结构替身 + cast，避免连带拉起真实容器。
    """
    handle = _Handle()
    ctx = AgentRunContext(
        run_id="run-zcode-contract",
        project_code="somwyn",
        capability="agent.code.write",
        workspace_host="agent-workspaces/run-zcode-contract",
    )
    result = ZcodeAdapter().run(
        ctx,
        cast(SandboxHandle, handle),
        event_provider=JsonSummaryEventProvider.from_file(FIXTURE),
        output_scanner=_Scanner(),
        clock=lambda: 0.0,
        sleeper=lambda _seconds: None,
    )
    assert result.status == "completed"
    assert result.token_cost == 122
    assert result.degraded is False
    assert result.tool_calls == ()
    assert handle.kills == 1
