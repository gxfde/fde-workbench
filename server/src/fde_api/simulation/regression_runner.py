"""回归与盲测系统（G6，G1 §11）。

三数据集**物理隔离**（按**案例**切，同案例三变体同属一个集）：
- ``train``：允许用于提改进；
- ``regression``：检退化；
- ``blind``：最终盲测——**不允许**用它的失败案例去提改进（否则等于在盲测集上调参）。

对比纪律（不只看总分）：
- 逐维度 Δ；负向维度单独列出；
- **硬性失败集合差异**（新增 / 消除）；
- 成本与时长 Δ；
- **泛化差** = ``gain_train − gain_blind``；> **0.15** ⇒ 过拟合风险 ⇒
  提案**不得进入发布审批**。

候选改进的生效方式（G1 §11.3）：提案的 ``override_json.run_config`` 只覆盖
**模拟域内**的运行参数（例：`probe_quality`），**不触及任何生产配置**——
这是「验证改进效果」与「发布改进」之间的那道闸。
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

# 维度回归阈值（某一维度 Δ 低于此值即算「该维度退步」）
DIMENSION_REGRESSION_DELTA = -0.1
# 总分有意义变化的阈值
TOTAL_SIGNIFICANT_DELTA = 0.02
# 泛化差阈值：train 增益 − blind 增益 超过此值 ⇒ 过拟合风险
OVERFIT_GAP_THRESHOLD = 0.15

# L-B 模型层噪声带闸（学习闭环 2.0 L5 §2.4，§6-3 拍板确认）：
# 缺省值锚定 L2 底册 `docs/audit/训练场分布读数-L2底册-1.md` 锚点观测极差 0.1049
# （评估轴 `rubric-v1|model:server`，anchor_n=3）。样本数 n < 3 ⇒ insufficient_data；
# n ≥ 3 且 |model_total_delta| ≤ band ⇒ within_noise（严格大于才可判 improved/regressed）。
DEFAULT_NOISE_BAND = 0.1049
DEFAULT_NOISE_BAND_AXIS = "rubric-v1|model:server"
MIN_NOISE_BAND_SAMPLES = 3
MODEL_VERDICTS = ("improved", "regressed", "within_noise", "insufficient_data")


@dataclass(frozen=True)
class RunSummary:
    """一次运行的评估摘要（回归对比的输入单元）。"""

    run_id: str
    scenario_id: str
    split: str
    total_score: float
    verdict: str
    dimension_scores: dict[str, float]
    hard_failures: tuple[str, ...]
    cost: dict[str, Any]
    failure_codes: tuple[str, ...] = ()
    model_total: float | None = None
    evaluator_axis: str = ""

    def to_json(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "scenario_id": self.scenario_id,
            "split": self.split,
            "total_score": self.total_score,
            "verdict": self.verdict,
            "dimension_scores": dict(self.dimension_scores),
            "hard_failures": list(self.hard_failures),
            "cost": dict(self.cost),
            "failure_codes": list(self.failure_codes),
            "model_total": self.model_total,
            "evaluator_axis": self.evaluator_axis,
        }


def _mean(values: list[float]) -> float:
    return round(sum(values) / len(values), 4) if values else 0.0


def summarize(summaries: list[RunSummary]) -> dict[str, Any]:
    """把一组运行摘要聚合成可比对的一组数字。"""
    by_split: dict[str, list[RunSummary]] = {}
    for summary in summaries:
        by_split.setdefault(summary.split, []).append(summary)
    dimensions: set[str] = set()
    for summary in summaries:
        dimensions.update(summary.dimension_scores)
    hard_failures: set[str] = set()
    failure_codes: set[str] = set()
    for summary in summaries:
        hard_failures.update(summary.hard_failures)
        failure_codes.update(summary.failure_codes)
    cost_totals: dict[str, float] = {}
    for summary in summaries:
        for key, value in summary.cost.items():
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                cost_totals[key] = cost_totals.get(key, 0.0) + float(value)
    return {
        "runs": len(summaries),
        "mean_total": _mean([summary.total_score for summary in summaries]),
        "mean_model_total": (
            _mean([float(summary.model_total) for summary in summaries if summary.model_total is not None])
            if any(summary.model_total is not None for summary in summaries)
            else None
        ),
        "model_runs": sum(1 for summary in summaries if summary.model_total is not None),
        "dimension_scores": {
            dimension: _mean(
                [
                    summary.dimension_scores.get(dimension, 0.0)
                    for summary in summaries
                    if dimension in summary.dimension_scores
                ]
            )
            for dimension in sorted(dimensions)
        },
        "hard_failures": sorted(hard_failures),
        "failure_codes": sorted(failure_codes),
        "cost": {key: round(value, 4) for key, value in sorted(cost_totals.items())},
        "by_split": {
            split: {
                "runs": len(items),
                "mean_total": _mean([item.total_score for item in items]),
            }
            for split, items in sorted(by_split.items())
        },
    }


def _compute_model_verdict(
    *,
    before: list[RunSummary],
    after: list[RunSummary],
    band: float,
) -> tuple[str, float | None]:
    """L-B 模型层独立判定（不动顶层 L-A verdict 闭集）。

    规则（delta-noise-band 同构，设计稿 §2.4）：
    - 参与对比的两组有效模型分样本数任一 < MIN_NOISE_BAND_SAMPLES (3) ⇒ insufficient_data；
    - |Δ| <= band ⇒ within_noise（严格大于才脱离噪声域）；
    - Δ > band ⇒ improved；Δ < -band ⇒ regressed。
    """
    before_vals = [float(item.model_total) for item in before if item.model_total is not None]
    after_vals = [float(item.model_total) for item in after if item.model_total is not None]
    if not before_vals or not after_vals:
        return "insufficient_data", None
    model_delta = round(_mean(after_vals) - _mean(before_vals), 4)
    if len(before_vals) < MIN_NOISE_BAND_SAMPLES or len(after_vals) < MIN_NOISE_BAND_SAMPLES:
        return "insufficient_data", model_delta
    if abs(model_delta) <= band:
        return "within_noise", model_delta
    return ("improved" if model_delta > band else "regressed"), model_delta


def compare(
    *,
    before: list[RunSummary],
    after: list[RunSummary],
    noise_band: float | None = None,
    noise_band_axis: str | None = None,
) -> dict[str, Any]:
    """基线组 vs 候选组 ⇒ 差异报告。"""
    before_summary = summarize(before)
    after_summary = summarize(after)

    total_delta = round(
        float(after_summary["mean_total"]) - float(before_summary["mean_total"]), 4
    )
    dimension_deltas: dict[str, float] = {}
    for dimension in set(before_summary["dimension_scores"]) | set(
        after_summary["dimension_scores"]
    ):
        dimension_deltas[dimension] = round(
            float(after_summary["dimension_scores"].get(dimension, 0.0))
            - float(before_summary["dimension_scores"].get(dimension, 0.0)),
            4,
        )
    regressed_dimensions = sorted(
        dimension
        for dimension, delta in dimension_deltas.items()
        if delta < DIMENSION_REGRESSION_DELTA
    )
    improved_dimensions = sorted(
        dimension
        for dimension, delta in dimension_deltas.items()
        if delta > TOTAL_SIGNIFICANT_DELTA
    )

    new_hard_failures = sorted(
        set(after_summary["hard_failures"]) - set(before_summary["hard_failures"])
    )
    resolved_hard_failures = sorted(
        set(before_summary["hard_failures"]) - set(after_summary["hard_failures"])
    )
    new_failure_codes = sorted(
        set(after_summary["failure_codes"]) - set(before_summary["failure_codes"])
    )

    cost_delta = {
        key: round(
            float(after_summary["cost"].get(key, 0.0))
            - float(before_summary["cost"].get(key, 0.0)),
            4,
        )
        for key in set(before_summary["cost"]) | set(after_summary["cost"])
    }

    # ---- 结论 ----------------------------------------------------------
    if not before or not after:
        verdict = "inconclusive"
    elif new_hard_failures:
        verdict = "mixed" if total_delta > 0 else "regressed"
    elif regressed_dimensions:
        verdict = "mixed"
    elif total_delta > TOTAL_SIGNIFICANT_DELTA:
        verdict = "improved"
    elif total_delta < -TOTAL_SIGNIFICANT_DELTA:
        verdict = "regressed"
    else:
        verdict = "no_change"

    # ---- 泛化差（跨集测量） --------------------------------------------
    train_gain = 0.0
    blind_gain = 0.0
    train_before = before_summary["by_split"].get("train", {}).get("mean_total")
    train_after = after_summary["by_split"].get("train", {}).get("mean_total")
    blind_before = before_summary["by_split"].get("blind", {}).get("mean_total")
    blind_after = after_summary["by_split"].get("blind", {}).get("mean_total")
    if train_before is not None and train_after is not None:
        train_gain = float(train_after) - float(train_before)
    if blind_before is not None and blind_after is not None:
        blind_gain = float(blind_after) - float(blind_before)
    generalization_gap = round(train_gain - blind_gain, 4)
    overfit_risk = (
        generalization_gap > OVERFIT_GAP_THRESHOLD
        and train_gain > TOTAL_SIGNIFICANT_DELTA
    )

    effective_band = float(DEFAULT_NOISE_BAND if noise_band is None else noise_band)
    effective_axis = str(noise_band_axis or "")
    model_verdict, model_total_delta = _compute_model_verdict(
        before=before, after=after, band=effective_band
    )

    return {
        "before": before_summary,
        "after": after_summary,
        "total_delta": total_delta,
        "dimension_deltas": dimension_deltas,
        "improved_dimensions": improved_dimensions,
        "regressed_dimensions": regressed_dimensions,
        "new_hard_failures": new_hard_failures,
        "resolved_hard_failures": resolved_hard_failures,
        "new_failure_codes": new_failure_codes,
        "cost_delta": cost_delta,
        "train_gain": round(train_gain, 4),
        "blind_gain": round(blind_gain, 4),
        "generalization_gap": generalization_gap,
        "overfit_risk": overfit_risk,
        "verdict": verdict,
        "model_verdict": model_verdict,
        "model_total_delta": model_total_delta,
        "noise_band": effective_band,
        "noise_band_axis": effective_axis,
    }


def result_fingerprint(
    *, suite_id: str, proposal_id: str | None, baseline_config: dict[str, Any]
) -> str:
    """回归结果幂等指纹：同套件 + 同提案 + 同基线参数 ⇒ 同一条结果。"""
    canonical = json.dumps(
        {
            "suite": suite_id,
            "proposal": proposal_id or "",
            "config": baseline_config or {},
        },
        sort_keys=True,
        ensure_ascii=False,
        default=str,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]
