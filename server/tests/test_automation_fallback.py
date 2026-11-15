"""E8：A 轨（automation）只读降级层 —— 决策纯函数 + 落账语义。

覆盖三层：
1. `plan_degraded_fallback` 的决策矩阵（哪些错误码可降级、哪些任务类型可降级、
   白名单怎么算、终态成功不再降级）；
2. 降级态白名单**恒为只读**（写类工具永不出现在降级面）；
3. `automation_jobs._record_degraded_execution` 的落账语义
   （degraded 标记、待人工确认、降级面自身失败时诚实 failed）。

这些测试**不联网、不碰真实 provider**。
"""
from __future__ import annotations

import pytest

from fde_api.control.ai_tool_loop import READ_ONLY_TOOLS
from fde_api.control.ai_server_client import DEGRADABLE_DSH_CODES
from fde_api.control.automation_fallback import (
    DEGRADABLE_TASK_TYPES,
    OUTPUT_KEY_ALLOWED_TOOLS,
    OUTPUT_KEY_CONFIRMATION,
    OUTPUT_KEY_DEGRADED,
    OUTPUT_KEY_PRODUCED,
    OUTPUT_KEY_REASON,
    DegradedFallbackPlan,
    plan_degraded_fallback,
)

# --- 决策矩阵 ---------------------------------------------------------


def test_degradable_codes_all_produce_a_plan():
    """既有可降级错误码集合里每一个都应能产出降级计划。"""
    assert DEGRADABLE_DSH_CODES, "既有降级码集合不应为空"
    for code in DEGRADABLE_DSH_CODES:
        plan = plan_degraded_fallback(error_code=code)
        assert plan is not None, code
        assert plan.reason == code


def test_non_degradable_error_codes_are_refused():
    """返回形状坏／状态冲突等不降级 —— 降级会掩盖真实问题。"""
    for code in ("dsh_response_invalid", "dsh_execution_conflict", "ai_output_invalid", ""):
        assert plan_degraded_fallback(error_code=code) is None, code


def test_task_type_outside_closed_set_is_refused():
    """A 轨任务封闭集＝仅 ai 类（N3-Q1）；其余类型诚实失败。"""
    assert DEGRADABLE_TASK_TYPES == frozenset({"ai"})
    assert plan_degraded_fallback(error_code="dsh_unavailable", task_type="ai") is not None
    for task_type in ("email", "external", "sync", ""):
        assert (
            plan_degraded_fallback(error_code="dsh_unavailable", task_type=task_type) is None
        ), task_type


def test_already_succeeded_run_is_not_degraded_again():
    """已是终态成功的 run 不再降级 —— 避免重复产出。"""
    assert (
        plan_degraded_fallback(error_code="dsh_unavailable", already_succeeded=True) is None
    )


# --- 白名单：恒为只读 --------------------------------------------------


def test_empty_capability_set_yields_full_read_only_whitelist():
    """能力集为空（未限定）⇒ 给出全量只读白名单（仍是只读）。"""
    plan = plan_degraded_fallback(error_code="dsh_unavailable", capabilities=[])
    assert plan is not None
    assert set(plan.allowed_tools) == set(READ_ONLY_TOOLS)
    assert len(plan.allowed_tools) == 13


def test_degraded_whitelist_never_contains_write_tools():
    """写类工具永不出现在降级面（N3-Q4 ＋ 只读降级边界）。"""
    plan = plan_degraded_fallback(error_code="dsh_unavailable")
    assert plan is not None
    for name in plan.allowed_tools:
        assert name in READ_ONLY_TOOLS, name
    # 既有确认面工具（写类/审批类）必须不在白名单里
    for write_tool in (
        "workflow_run_start",
        "workflows_run_start",
        "agents_run_start",
        "gate_decide",
        "project_create",
    ):
        assert write_tool not in plan.allowed_tools, write_tool


def test_capability_set_without_read_only_overlap_refuses_to_degrade():
    """能力集与只读工具名无交集 ⇒ 降级面为空 ⇒ 诚实失败（不猜、不放宽）。"""
    plan = plan_degraded_fallback(
        error_code="dsh_unavailable",
        capabilities=["agent.code.write", "agent.meeting.convene"],
    )
    assert plan is None


def test_capability_set_matching_read_only_tool_is_kept():
    """能力名恰好命中只读工具名时保留该工具。"""
    plan = plan_degraded_fallback(
        error_code="dsh_unavailable", capabilities=["project_read", "agent.code.write"]
    )
    assert plan is not None
    assert plan.allowed_tools == ("project_read",)


# --- 降级语义 ---------------------------------------------------------


def test_plan_payload_carries_degraded_marker_and_confirmation():
    """降级计划必须带 degraded 标记、原因码、工具清单与「待人工确认」标记。"""
    plan = plan_degraded_fallback(error_code="dsh_timeout")
    assert plan is not None
    payload = plan.output_payload
    assert payload[OUTPUT_KEY_DEGRADED] is True
    assert payload[OUTPUT_KEY_REASON] == "dsh_timeout"
    assert payload[OUTPUT_KEY_CONFIRMATION] is True
    assert payload[OUTPUT_KEY_ALLOWED_TOOLS] == list(plan.allowed_tools)
    assert payload[OUTPUT_KEY_PRODUCED]


def test_plan_is_immutable_dataclass():
    """降级计划是不可变数据 —— 不能在执行中被就地改宽。"""
    plan = plan_degraded_fallback(error_code="dsh_unavailable")
    assert plan is not None
    with pytest.raises(Exception):
        plan.reason = "anything"  # type: ignore[misc]


def test_degraded_plan_is_marked_degradable():
    plan = plan_degraded_fallback(error_code="dsh_unavailable")
    assert isinstance(plan, DegradedFallbackPlan)
    assert plan.degradable is True


def test_dotted_capabilities_map_to_read_only_tools():
    """真实 A 轨任务存点分能力名（如 DEFAULT_AUTOMATION_CAPABILITIES）时必须产出对应只读工具集。"""
    from fde_api.control.service import DEFAULT_AUTOMATION_CAPABILITIES

    plan = plan_degraded_fallback(
        error_code="dsh_not_enabled",
        capabilities=DEFAULT_AUTOMATION_CAPABILITIES,
    )
    assert plan is not None
    allowed = set(plan.allowed_tools)
    assert allowed <= READ_ONLY_TOOLS
    # project.read + file.search + 无能力门槛通用只读工具在列；system.health / lcsc.browse 未授权工具不在列
    assert {"project_list", "project_read", "gates_read", "quote_list"} <= allowed
    assert {"file_search", "file_read"} <= allowed
    assert {"ontology_read", "api_catalog", "skill_list", "skill_read", "help_fetch"} <= allowed
    assert "system_status" not in allowed
    assert "lcsc_runs_read" not in allowed


def test_summarize_only_dotted_capability_maps_to_project_read_only_tools():
    """project.summarize（assistant_read 只读摘要能力）单独或与写能力并存时仅映射只读项目工具。"""
    plan = plan_degraded_fallback(
        error_code="dsh_unavailable",
        capabilities=["project.summarize", "workbench.write"],
    )
    assert plan is not None
    allowed = set(plan.allowed_tools)
    assert allowed <= READ_ONLY_TOOLS
    assert {"project_list", "project_read", "gates_read", "quote_list"} <= allowed
    assert "file_search" not in allowed
    assert "system_status" not in allowed
