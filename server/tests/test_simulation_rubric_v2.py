# -*- coding: utf-8 -*-
"""rubric-v2 规则层口径变更的机械钉（2026-11-19）。

背景（真机取证：训练场 r2 制造行业 25 场景批跑，2026-11-19）：

- D3-01「方案覆盖 rubric.must_produce」用**精确子串**判「方案是否覆盖交付物
  整句」，而 ``rubric.must_produce`` 本身就是交付物整句 ⇒ 真模型方案几乎不
  逐字复现 ⇒ D3-01 恒 0 分（``verified=true`` 却零命中），把 D3 维度上限压到
  0.2；且 D3-01 **不挂任何失败码**（``failure_analyzer`` 的
  ``CRITERION_TO_FAILURE`` 只挂 D3-02→FA-03）⇒ 只压分、不产可处置信号；
- 处置（蔡工 2026-11-19 拍板）：**规则层剔除 D3-01**，交付物覆盖的语义判定
  交**模型层 L-B**（评分基准块把 must_produce 整句给模型逐项判）；规则版本升
  ``rubric-v2`` 留痕（历史评估不改写，v1 行原样留存）。

本钉把这次口径变更的边界钉死：

1. 版本升到 rubric-v2；
2. 规则层不再产出 D3-01，D3-02/D3-03 在位；
3. D3 维度分按**剩余判据权重**归一（口径变更的可见后果，必须显式登记）；
4. **噪声带不跨轴套用**：缺省带 0.1049 是在 ``rubric-v1|model:server`` 轴下
   实测的观测极差，换轴后**不得**改贴新轴标签（旧轴的带冒充新轴的带＝假绿）；
   本轴没有实测归档的带 ⇒ 模型层判定 ``insufficient_data``（不可用即不判）。
"""
from __future__ import annotations

import pytest

from fde_api.simulation.regression_runner import (
    DEFAULT_NOISE_BAND,
    DEFAULT_NOISE_BAND_AXIS,
    RunSummary,
    compare,
)


def _rubric_view() -> dict:
    return {
        "reference": {
            "rubric": {
                "must_identify": ["跨系统主键缺失"],
                "must_avoid": [],
                "must_produce": ["数据接入与主键映射方案"],
            }
        }
    }


def _artifacts(section_count: int) -> dict:
    return {
        "analysis": {
            "root_causes": [{"text": "跨系统主键缺失"}],
            "requirements": [{"key": "REQ-1"}],
        },
        "design": {
            "solution_sections": [
                {"heading": f"实施段落{i}"} for i in range(section_count)
            ],
            "tasks": [{"key": "TASK-1"}],
            "acceptance_criteria": [{"key": "AC-1", "requirement_key": "REQ-1"}],
        },
    }


def _traces(disclosed: list[str]) -> list[dict]:
    return [
        {"event_type": "hidden_fact_disclosed", "payload": {"disclosed": list(disclosed)}}
    ]


def _summary(
    run_id: str, total: float, model_total: float | None = None
) -> RunSummary:
    return RunSummary(
        run_id=run_id,
        scenario_id="scn",
        split="train",
        total_score=total,
        verdict="pass" if total >= 0.75 else "conditional",
        dimension_scores={"D1": total},
        hard_failures=(),
        cost={"tool_calls": 10},
        failure_codes=(),
        model_total=model_total,
    )


# ---------------------------------------------------------------------------
# 1. 版本与判据边界
# ---------------------------------------------------------------------------


def test_rubric_version_is_v2():
    """规则版本升 v2（历史 v1 评估行不改写，靠幂等键含版本天然分列）。"""
    from fde_api.simulation.evaluation_rules import RUBRIC_VERSION

    assert RUBRIC_VERSION == "rubric-v2"


def test_rule_layer_no_longer_emits_d3_01():
    """规则层不再产出 D3-01；D3-02/D3-03 仍在位。"""
    from fde_api.simulation.evaluation_rules import score_criteria

    criteria = score_criteria(
        traces=_traces(["F-1"]),
        artifacts=_artifacts(section_count=3),
        judge_view=_rubric_view(),
    )
    by_key = {item.key: item for item in criteria}
    assert "D3-01" not in by_key
    assert by_key["D3-02"].dimension == "D3"
    assert by_key["D3-03"].dimension == "D3"


def test_d3_dimension_score_normalizes_over_remaining_criteria():
    """★口径变更的可见后果：D3 内部按剩余判据权重归一（0.3×0 + 0.2×1）/ 0.5 = 0.4。"""
    from fde_api.simulation.evaluation_rules import aggregate, score_criteria

    criteria = score_criteria(
        traces=_traces(["F-1"]),
        artifacts=_artifacts(section_count=3),
        judge_view=_rubric_view(),
    )
    by_key = {item.key: item for item in criteria}
    # 3 个实施章节 > 1 条已披露事实 ⇒ 规模失配（D3-02 = 0）
    assert by_key["D3-02"].score == 0.0
    # 方案产物存在 ⇒ 既定约束被带进方案（D3-03 = 1）
    assert by_key["D3-03"].score == 1.0

    outcome = aggregate(criteria, [])
    assert outcome.dimension_scores["D3"] == 0.4


# ---------------------------------------------------------------------------
# 2. 噪声带轴绑定（不跨轴套用）
# ---------------------------------------------------------------------------


def test_default_noise_band_axis_stays_at_its_measurement_axis():
    """缺省带的标签必须留在**它实测时的那个轴**——改贴新轴＝把旧带冒充新带。"""
    assert DEFAULT_NOISE_BAND == 0.1049
    assert DEFAULT_NOISE_BAND_AXIS == "rubric-v1|model:server"


def test_noise_band_unavailable_on_new_axis_resolves_to_none():
    """当前轴（rubric-v2）没有实测归档的带 ⇒ 解析结果 band=None（不是缺省带）。"""
    from fde_api.simulation.regression_service import _resolve_noise_band

    band, axis = _resolve_noise_band({}, model_mode="server")

    assert axis == "rubric-v2|model:server"
    assert band is None


def test_noise_band_default_still_resolved_on_its_own_axis(monkeypatch):
    """旧轴（实测轴）上缺省带照常解析（历史套件不被本轮变更打断）。"""
    from fde_api.simulation import regression_service

    monkeypatch.setattr(regression_service, "RUBRIC_VERSION", "rubric-v1")
    band, axis = regression_service._resolve_noise_band({}, model_mode="server")

    assert axis == "rubric-v1|model:server"
    assert band == DEFAULT_NOISE_BAND


def test_invalid_archived_noise_band_fails_closed():
    """存档带的值非法 ⇒ 400 fail-closed（不得回落成缺省带跨轴套用）。"""
    from fde_api.simulation.regression_service import _resolve_noise_band
    from fde_api.simulation.service import ScenarioServiceError

    with pytest.raises(ScenarioServiceError) as excinfo:
        _resolve_noise_band(
            {"noise_band": {"axis": "rubric-v2|model:server", "band": "not-a-number"}},
            model_mode="server",
        )

    assert excinfo.value.code == "invalid_request"
    assert excinfo.value.status == 400


def test_compare_forces_insufficient_data_when_band_unavailable_on_axis():
    """本轴无可用带 ⇒ 模型层不判（insufficient_data），即便 Δ 远超缺省带。"""
    before = [_summary(f"b{i}", 0.60, model_total=0.60) for i in range(3)]
    after = [_summary(f"a{i}", 0.90, model_total=0.90) for i in range(3)]

    report = compare(
        before=before,
        after=after,
        noise_band=None,
        noise_band_axis="rubric-v2|model:server",
    )

    assert report["noise_band"] is None
    assert report["noise_band_axis"] == "rubric-v2|model:server"
    assert report["model_verdict"] == "insufficient_data"
    assert report["model_total_delta"] == 0.3


def test_compare_keeps_default_band_when_no_axis_given():
    """未给轴的直调用路径保持既有语义（缺省带照常生效）。"""
    before = [_summary(f"b{i}", 0.60, model_total=0.60) for i in range(3)]
    after = [_summary(f"a{i}", 0.90, model_total=0.90) for i in range(3)]

    report = compare(before=before, after=after)

    assert report["noise_band"] == DEFAULT_NOISE_BAND
    assert report["model_verdict"] == "improved"
