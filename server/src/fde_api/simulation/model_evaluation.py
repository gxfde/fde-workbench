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
    """真模型评估（G9 接线轮）：走仓库既有 AI 栈。

    继承的既有纪律（``ai/deepseek.py`` 内建，本层不重复实现）：
    - **月度 token 预算闸**：预算用尽即拒发，且**不发起任何供应商请求**；
    - **审计留痕**：每次调用落 ``ai_call_audits``（含 purpose）；
    - **严格 JSON 契约**：输出经 ``evaluation_schema`` 校验，不合规即丢弃。

    失败语义（**不冒充**）：
    - provider 未配置 ⇒ ``unavailable``；
    - 调用失败（认证/限流/超时/空响应）⇒ ``error``；
    - 输出不合契约 ⇒ ``invalid_output``；
    以上三种都**不产生分数**——模型层没有分数就不参与聚合。
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
        from fde_api.ai.deepseek import DeepSeekError
        from fde_api.simulation.evaluation_prompt import build_evaluation_messages
        from fde_api.simulation.evaluation_schema import (
            EvaluationContractError,
            parse_model_evaluation,
        )

        client = _simulation_client()
        if client is None:
            return ModelEvaluation(
                layer="model",
                mode=self.mode,
                status="unavailable",
                total_score=0.0,
                verdict="unavailable",
                criteria=(),
                note="真模型评估面未配置 provider（缺 API Key）——本层不产生分数。",
            )

        messages = build_evaluation_messages(
            judge_view=judge_view,
            artifacts=artifacts,
            traces=traces,
            rubric_version=rubric_version,
        )
        try:
            raw = client.complete_json(
                messages=messages,
                request_id="simulation-evaluation",
                purpose="simulation_evaluation",
            )
        except DeepSeekError as error:
            return ModelEvaluation(
                layer="model",
                mode=self.mode,
                status="error",
                total_score=0.0,
                verdict="unavailable",
                criteria=(),
                note=f"模型调用失败（{error.code}）：{error.public_message}",
            )

        try:
            parsed = parse_model_evaluation(raw)
        except EvaluationContractError as error:
            return ModelEvaluation(
                layer="model",
                mode=self.mode,
                status="invalid_output",
                total_score=0.0,
                verdict="unavailable",
                criteria=(),
                note=f"模型输出不合契约（{error.code}）：{error.message}",
            )

        criteria = [
            {
                "key": item["key"],
                "dimension": item["dimension"],
                "title": item["title"],
                "score": item["score"],
                "verdict": item["verdict"],
                "evidence_refs": item["evidence_refs"],
                "reason": item["reason"],
            }
            for item in parsed["criteria"]
        ]
        total = round(
            sum(item["score"] for item in criteria) / len(criteria) if criteria else 0.0, 4
        )
        verdict = "pass" if total >= 0.75 else ("conditional" if total >= 0.6 else "fail")
        return ModelEvaluation(
            layer="model",
            mode=self.mode,
            status="evaluated",
            total_score=total,
            verdict=verdict,
            criteria=tuple(criteria),
            note=(
                "模型层为独立第二意见：**不判定终局、不判定硬性失败**——"
                f"结论由规则层（L-A）负责。摘要：{parsed['summary']}"
            ),
        )


def _simulation_client():
    """取模型客户端：优先注入（测试/替换），否则按 Settings 构造；无 Key ⇒ None。"""
    from flask import current_app, has_app_context

    if not has_app_context():
        return None
    injected = current_app.extensions.get("fde_api_simulation_deepseek")
    if injected is not None:
        return injected
    settings = current_app.config["SETTINGS"]
    api_key = getattr(settings, "deepseek_api_key", None)
    if api_key is None or not getattr(api_key, "get_secret_value", lambda: "")():
        return None
    from fde_api.ai.deepseek import DeepSeekClient

    return DeepSeekClient(
        base_url=settings.deepseek_base_url,
        api_key=api_key,
        model=settings.deepseek_simulation_evaluation_model,
        timeout_seconds=settings.deepseek_timeout_seconds,
        fallback_model=settings.deepseek_fallback_model,
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
