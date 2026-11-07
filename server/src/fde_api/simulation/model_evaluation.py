"""模型评估层（L-B，G1 §9.2 的第二层）。

**独立性纪律**：L-B 只看「产物 + 场景评分基准」，**不读**实施方的自评字段；它
**无权**判定硬性失败（只有 L-A 有）。

两种实现：
- ``stub``：**确定性替身**，按「产物整体覆盖度」给出保守评分。用于让三层机制
  端到端可跑、可测（尤其是「分歧 ⇒ 触发人工复核」这条链路）。评估行显式记
  ``mode="stub"``——**不冒充真模型评分**。
- ``server``：接仓库既有 AI 服务做真正的模型评分。**本轮未接线**（需 provider
  配置与出网），返回 ``status="unavailable"``，**不以 stub 冒充**。

两种实现都**不与 L-A 取平均**（G1 §9.2）：两层并列呈现，分歧超阈值 ⇒ 人工终裁。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from fde_api.simulation.evaluation_rules import DIMENSIONS, RUBRIC_VERSION

# 分歧阈值：|L-A 总分 − L-B 总分| 超过即触发人工复核
DISAGREEMENT_THRESHOLD = 0.2


@dataclass(frozen=True)
class ModelEvaluation:
    """模型层评估结论。"""

    layer: str
    mode: str
    status: str
    total_score: float
    verdict: str
    criteria: tuple[dict[str, Any], ...]
    note: str = ""

    def to_json(self) -> dict[str, Any]:
        return {
            "layer": self.layer,
            "mode": self.mode,
            "status": self.status,
            "total_score": self.total_score,
            "verdict": self.verdict,
            "criteria": [dict(item) for item in self.criteria],
            "note": self.note,
        }


class ModelEvaluationAdapter(Protocol):
    """模型层评估适配器。"""

    mode: str

    def evaluate(
        self,
        *,
        judge_view: dict[str, Any],
        artifacts: dict[str, Any],
        traces: list[dict[str, Any]],
        rubric_version: str = RUBRIC_VERSION,
    ) -> ModelEvaluation:
        ...


class StubModelEvaluation:
    """确定性替身：按**产物整体覆盖度**给分（与 L-A 的逐判据结构化视角不同源）。

    它刻意**不判硬性失败**——硬性失败只能由 L-A 判（G1 §9.3）。
    """

    mode = "stub"

    def evaluate(
        self,
        *,
        judge_view: dict[str, Any],
        artifacts: dict[str, Any],
        traces: list[dict[str, Any]],
        rubric_version: str = RUBRIC_VERSION,
    ) -> ModelEvaluation:
        reference = judge_view.get("reference")
        rubric = reference.get("rubric") if isinstance(reference, dict) else None
        rubric = rubric if isinstance(rubric, dict) else {}
        must_identify = [str(item) for item in (rubric.get("must_identify") or [])]
        must_produce = [str(item) for item in (rubric.get("must_produce") or [])]
        must_avoid = [str(item) for item in (rubric.get("must_avoid") or [])]

        blob = " ".join(str(value) for value in artifacts.values())
        identified = [text for text in must_identify if text and text in blob]
        produced = [text for text in must_produce if text and text in blob]
        violated = [text for text in must_avoid if text and text in blob]

        criteria: list[dict[str, Any]] = []
        coverage_identify = (
            len(identified) / len(must_identify) if must_identify else 0.0
        )
        criteria.append(
            {
                "key": "M-01",
                "dimension": "D1",
                "title": "交付整体是否点到了关键问题",
                "score": coverage_identify,
                "evidence_refs": [{"kind": "rubric", "text": text} for text in identified],
            }
        )
        coverage_produce = len(produced) / len(must_produce) if must_produce else 0.0
        criteria.append(
            {
                "key": "M-02",
                "dimension": "D3",
                "title": "交付整体是否覆盖了必备产物",
                "score": coverage_produce,
                "evidence_refs": [{"kind": "rubric", "text": text} for text in produced],
            }
        )
        criteria.append(
            {
                "key": "M-03",
                "dimension": "D5",
                "title": "是否存在禁区命中",
                "score": 0.0 if violated else 1.0,
                "evidence_refs": [{"kind": "rubric", "text": text} for text in violated]
                or ([{"kind": "rubric", "note": "未命中禁区"}] if must_avoid else []),
            }
        )
        criteria.append(
            {
                "key": "M-04",
                "dimension": "D7",
                "title": "过程留痕是否完整",
                "score": 1.0 if traces else 0.0,
                "evidence_refs": ([{"kind": "trace", "count": len(traces)}] if traces else []),
            }
        )

        verified = [item for item in criteria if item["evidence_refs"]]
        weight_total = len(criteria) or 1
        total = (
            sum(item["score"] for item in verified) / weight_total if verified else 0.0
        )
        verdict = "pass" if total >= 0.75 else ("conditional" if total >= 0.6 else "fail")
        return ModelEvaluation(
            layer="model",
            mode=self.mode,
            status="evaluated",
            total_score=round(total, 4),
            verdict=verdict,
            criteria=tuple(criteria),
            note="stub 模式：确定性替身，非真模型评分；不得据此宣称模型评估结论。",
        )


class ServerModelEvaluation:
    """真模型评估的接线面（本轮未接线）。

    缺 provider 配置时**明确**返回 ``unavailable``——不以 stub 冒充真模型。
    """

    mode = "server"

    def evaluate(
        self,
        *,
        judge_view: dict[str, Any],
        artifacts: dict[str, Any],
        traces: list[dict[str, Any]],
        rubric_version: str = RUBRIC_VERSION,
    ) -> ModelEvaluation:
        return ModelEvaluation(
            layer="model",
            mode=self.mode,
            status="unavailable",
            total_score=0.0,
            verdict="unavailable",
            criteria=(),
            note="真模型评估面未接线（需 AI provider 配置与出网授权）；本轮以 stub 模式运行。",
        )


def build_model_evaluation(mode: str = "stub") -> ModelEvaluationAdapter:
    if mode == "stub":
        return StubModelEvaluation()
    if mode == "server":
        return ServerModelEvaluation()
    raise ValueError(f"未知模型评估模式：{mode}")


__all__ = [
    "DISAGREEMENT_THRESHOLD",
    "DIMENSIONS",
    "ModelEvaluation",
    "ModelEvaluationAdapter",
    "ServerModelEvaluation",
    "StubModelEvaluation",
    "build_model_evaluation",
]
