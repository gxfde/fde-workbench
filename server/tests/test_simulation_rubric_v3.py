# -*- coding: utf-8 -*-
"""rubric-v3 规则层口径变更的机械钉（2026-11-20）。

背景（第五批真机取证：训练场 r2 制造行业 25 completed run，真相层
``FA-01FA-02残余真相重估-20261120.md``）：

- D1-01「识别出客户真实问题」与 D2-01「根因覆盖度」在规则层是**同一计算**
  （同一 ``hit_identify``、同一 textmatch，占 D1 权重 0.5 ＋ D2 权重 0.6）——
  用 0.25 字面重叠判「模型是否识别出 ``rubric.must_identify``」。第五批
  89 条 MI 逐条现算：58% 有重叠但低于阈值被拒、完全零重叠仅 7%、传导核对
  （披露事实 3.28/run vs root_causes 3.32/run，0/25 漏条目）证伪「漏识别」
  ⇒ 主体是**判据假阴性**；且 ``CRITERION_TO_FAILURE`` 把两判据挂到 FA-01/
  FA-02 ⇒ 假发现成批入库（第五批 38 条）。
- 处置（蔡工 2026-11-20 拍板「按推荐实施」＝真相重估报告意见 1＋2）：规则层
  **剔除 D1-01/D2-01**（与 #540 剔 D3-01 同构），MI 覆盖的语义判定交模型层
  L-B（评分基准块把 must_identify 整句给模型逐项判，输出契约 ``MI-n`` 即
  落点）；``CRITERION_TO_FAILURE`` 同步摘除 D1-01/D2-01 两映射（D1-02/D2-02
  保留——零披露/零结构化仍应报 FA-01/FA-02）。规则版本升 ``rubric-v3``，
  历史评估按版本双口径并列不改写。

本钉把这次口径变更的边界钉死：

1. 版本升到 rubric-v3；
2. 规则层不再产出 D1-01/D2-01，D1-02/D1-03/D2-02 在位；
3. D1/D2 维度分按剩余判据权重归一（口径变更的可见后果，显式登记）；
4. 失败码映射闭集：D1-01/D2-01 不再触发 FA-01/FA-02，D1-02/D2-02 仍在；
5. 噪声带轴纪律沿用 #540：缺省带标签留在实测轴 ``rubric-v1|model:server``，
   v3 轴无实测带 ⇒ ``band=None`` ⇒ 模型层 ``insufficient_data``。
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
                "must_identify": ["跨系统主键缺失（MES 批次号 ↔ 质量库供应商批号无共同主键）"],
                "must_avoid": [],
                "must_produce": ["数据接入与主键映射方案"],
            }
        }
    }


def _artifacts(root_text: str, with_requirements: bool = True) -> dict:
    return {
        "analysis": {
            "root_causes": [{"text": root_text}],
            "requirements": [{"key": "REQ-1"}] if with_requirements else [],
        },
        "design": {
            "solution_sections": [{"heading": "数据接入与主键映射方案"}],
            "tasks": [{"key": "TASK-1"}],
            "acceptance_criteria": [{"key": "AC-1", "requirement_key": "REQ-1"}],
        },
    }


def _traces(disclosed: list[str]) -> list[dict]:
    return [
        {"event_type": "hidden_fact_disclosed", "payload": {"disclosed": list(disclosed)}}
    ]


# ---------------------------------------------------------------------------
# 1. 版本与判据边界
# ---------------------------------------------------------------------------


def test_rubric_version_is_v3():
    """规则版本升 v3（历史 v1/v2 评估行不改写，靠幂等键含版本天然分列）。"""
    from fde_api.simulation.evaluation_rules import RUBRIC_VERSION

    assert RUBRIC_VERSION == "rubric-v3"


def test_rule_layer_no_longer_emits_d1_01_or_d2_01():
    """规则层不再产出 D1-01/D2-01；D1-02/D1-03/D2-02 仍在位。

    判别面：给「语义对应、措辞不同」的 root_causes（真机假阴性样本同款——
    MI「识别交接班日志是知识保鲜的关键增量源」vs 模型措辞「缺少将交接班日志
    转化为持续更新知识的机制」，0.25 字面重叠只有 0.200）。v2 口径下这条
    MI 不命中 ⇒ D1-01 记 0 并经失败码成 FA-01；v3 规则层根本不产出该判据
    ⇒ 假阴性面不存在。
    """
    from fde_api.simulation.evaluation_rules import score_criteria

    criteria = score_criteria(
        traces=_traces(["F-1"]),
        artifacts=_artifacts("缺少将交接班日志转化为持续更新知识的机制"),
        judge_view=_rubric_view(),
    )
    by_key = {item.key: item for item in criteria}
    assert "D1-01" not in by_key
    assert "D2-01" not in by_key
    assert by_key["D1-02"].dimension == "D1"
    assert by_key["D1-03"].dimension == "D1"
    assert by_key["D2-02"].dimension == "D2"


def test_d1_normalizes_over_remaining_criteria():
    """★口径变更的可见后果：D1 按 D1-02/D1-03 权重归一——两者全满 ⇒ D1=1.0。

    v2 口径同一素材的 D1 = 0.5×D1-01 + 0.3×1 + 0.2×1（D1-01 零字面命中记 0
    ⇒ D1=0.5）；v3 下假阴性不再压分。
    """
    from fde_api.simulation.evaluation_rules import aggregate, score_criteria

    criteria = score_criteria(
        traces=_traces(["F-1"]),
        artifacts=_artifacts("模型自己的措辞，与 MI 无字面重叠"),
        judge_view=_rubric_view(),
    )
    outcome = aggregate(criteria, [])
    assert outcome.dimension_scores["D1"] == 1.0


def test_missing_requirements_become_unverified_not_zero():
    """无需求条目 ⇒ D1-03 无证据不入账（评分纪律 1：unverified，不算 0）——
    维度分仍 1.0 但 unverified_ratio 上升；「关键需求没有验收标准」的硬闸在
    HF-04（需求↔验收映射缺口），不在维度分。
    """
    from fde_api.simulation.evaluation_rules import aggregate, score_criteria

    criteria = score_criteria(
        traces=_traces(["F-1"]),
        artifacts=_artifacts("任意措辞", with_requirements=False),
        judge_view=_rubric_view(),
    )
    by_key = {item.key: item for item in criteria}
    assert "D1-03" in by_key
    assert by_key["D1-03"].verified is False
    outcome = aggregate(criteria, [])
    assert outcome.dimension_scores["D1"] == 1.0
    assert outcome.unverified_ratio > 0


def test_d2_normalizes_to_its_single_remaining_criterion():
    """D2 只剩 D2-02（weight 0.4）⇒ 维度分 = D2-02 分。"""
    from fde_api.simulation.evaluation_rules import aggregate, score_criteria

    criteria = score_criteria(
        traces=_traces(["F-1"]),
        artifacts=_artifacts("任意措辞"),
        judge_view=_rubric_view(),
    )
    outcome = aggregate(criteria, [])
    assert outcome.dimension_scores["D2"] == 1.0


# ---------------------------------------------------------------------------
# 2. 失败码映射闭集
# ---------------------------------------------------------------------------


def test_failure_mapping_drops_d1_01_and_d2_01_keeps_the_rest():
    """D1-01/D2-01 两映射摘除；D1-02→FA-01、D2-02→FA-02 保留（机械面触发）。"""
    from fde_api.simulation.failure_analyzer import CRITERION_TO_FAILURE

    assert "D1-01" not in CRITERION_TO_FAILURE
    assert "D2-01" not in CRITERION_TO_FAILURE
    assert CRITERION_TO_FAILURE["D1-02"] == "FA-01"
    assert CRITERION_TO_FAILURE["D2-02"] == "FA-02"
    assert set(CRITERION_TO_FAILURE.values()) <= {
        "FA-01",
        "FA-02",
        "FA-03",
        "FA-04",
        "FA-05",
        "FA-06",
        "FA-07",
        "FA-08",
    }


# ---------------------------------------------------------------------------
# 3. 硬性失败面不受影响（_rubric/must_avoid 仍在位）
# ---------------------------------------------------------------------------


def test_must_avoid_hard_failure_still_enforced():
    """HF-07（命中案例明令禁止的方向）不受 v3 影响——_rubric 的 must_avoid 消费保留。"""
    from fde_api.simulation.evaluation_rules import detect_hard_failures

    banned = "不得建议直接删除生产数据"
    failures = detect_hard_failures(
        traces=[],
        artifacts={
            "analysis": {"root_causes": [{"text": f"方案包含步骤：{banned}"}]},
            "design": {},
        },
        judge_view={
            "reference": {
                "rubric": {
                    "must_identify": [],
                    "must_avoid": [banned],
                    "must_produce": [],
                }
            }
        },
    )
    assert any(f.code == "HF-07" for f in failures)


# ---------------------------------------------------------------------------
# 4. 噪声带轴纪律（沿用 #540，v3 轴自动继承）
# ---------------------------------------------------------------------------


def test_default_noise_band_axis_stays_at_its_measurement_axis():
    """缺省带的标签必须留在**它实测时的那个轴**——v2/v3 都不改贴。"""
    assert DEFAULT_NOISE_BAND == 0.1049
    assert DEFAULT_NOISE_BAND_AXIS == "rubric-v1|model:server"


def test_v3_axis_resolves_to_none_band():
    """当前轴（rubric-v3）没有实测归档的带 ⇒ 解析结果 band=None（不是缺省带）。"""
    from fde_api.simulation.evaluation_rules import RUBRIC_VERSION
    from fde_api.simulation.regression_service import _resolve_noise_band

    band, axis = _resolve_noise_band({}, model_mode="server")

    assert axis == f"{RUBRIC_VERSION}|model:server"
    assert band is None


def test_compare_forces_insufficient_data_when_band_unavailable_on_v3_axis():
    """本轴无可用带 ⇒ 模型层不判（insufficient_data），即便 Δ 远超缺省带。"""
    before = [_summary(f"b{i}", 0.60, model_total=0.60) for i in range(3)]
    after = [_summary(f"a{i}", 0.90, model_total=0.90) for i in range(3)]

    report = compare(
        before=before,
        after=after,
        noise_band=None,
        noise_band_axis="rubric-v3|model:server",
    )

    assert report["noise_band"] is None
    assert report["noise_band_axis"] == "rubric-v3|model:server"
    assert report["model_verdict"] == "insufficient_data"
    assert report["model_total_delta"] == 0.3


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
