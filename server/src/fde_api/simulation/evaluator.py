"""独立评估引擎（G4，G1 §9）。

三层机制：
- **L-A 确定性规则**（``evaluation_rules.py``）：**唯一**有权判定硬性失败。
- **L-B 模型评估**（``model_evaluation.py``）：独立第二意见，**不与 L-A 取平均**。
- **L-C 人工抽检**：触发条件＝高风险案例 / 总分低于阈值 / 两层分歧超阈值；
  人工结论**覆盖**机器结论，但**机器原行保留**（留痕）。

**评估器是唯一装载 Judge View（参考答案/Rubric）的地方**——执行侧（G3）在物理上
读不到它（G3 的 AST 静态钉）。
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import select

from fde_api.auth.models import User
from fde_api.extensions import db
from fde_api.simulation.evaluation_rules import (
    DIMENSIONS,
    PASS_THRESHOLD,
    RUBRIC_VERSION,
    aggregate,
    collect_artifacts,
    detect_hard_failures,
    score_criteria,
)
from fde_api.simulation.model_evaluation import (
    DISAGREEMENT_THRESHOLD,
    build_model_evaluation,
)
from fde_api.simulation.models import SimulationEvaluation, SimulationRun, SimulationScenario, SimulationTrace
from fde_api.simulation.scenarios.loader import load_view

# L-A 评估器标识（确定性规则）
DETERMINISTIC_EVALUATOR = "rules"
# L-B 评估器标识前缀
MODEL_EVALUATOR_PREFIX = "model:"
# 人工抽检触发：L-A 总分低于此值
HUMAN_REVIEW_LOW_SCORE = PASS_THRESHOLD
# 人工抽检触发：命中任一硬性失败
HUMAN_REVIEW_ON_HARD_FAILURE = True


class EvaluationError(Exception):
    """评估层错误。"""

    def __init__(self, code: str, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


def _load_run_and_traces(session, run_id: str):
    run = session.get(SimulationRun, run_id)
    if run is None:
        raise EvaluationError("not_found", "模拟运行不存在。", 404)
    traces = list(
        session.scalars(
            select(SimulationTrace)
            .where(SimulationTrace.run_id == run_id)
            .order_by(SimulationTrace.seq)
        )
    )
    trace_dicts = [
        {
            "seq": row.seq,
            "phase": row.phase,
            "event_type": row.event_type,
            "actor_id": row.actor_id,
            "payload": dict(row.payload_json or {}),
            "tool_call": dict(row.tool_call_json) if row.tool_call_json else None,
            "evidence": dict(row.evidence_json) if row.evidence_json else None,
        }
        for row in traces
    ]
    return run, trace_dicts


def _judge_view(session, run: SimulationRun) -> dict[str, Any]:
    """装载 Judge View（**评分侧专属**）。"""
    scenario = session.get(SimulationScenario, run.scenario_id)
    if scenario is None:
        raise EvaluationError("not_found", "场景不存在。", 404)
    content = dict(scenario.content_json or {})
    reference = dict(scenario.reference_json) if scenario.reference_json else None
    return load_view(content, reference, "judge")


def _serialize_evaluation(row: SimulationEvaluation) -> dict[str, Any]:
    return {
        "id": row.id,
        "run_id": row.run_id,
        "layer": row.layer,
        "evaluator_id": row.evaluator_id,
        "mode": row.mode,
        "rubric_version": row.rubric_version,
        "total_score": float(row.total_score or 0),
        "verdict": row.verdict,
        "unverified_ratio": float(row.unverified_ratio or 0),
        "scores": dict(row.scores_json or {}),
        "hard_failures": list(row.hard_failures_json or []),
        "evidence_refs": list(row.evidence_refs_json or []),
        "decided_by_user_id": row.decided_by_user_id,
        "note": row.note,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def evaluate_run(
    *,
    actor: User,
    run_id: str,
    include_model: bool = True,
    model_mode: str = "stub",
) -> dict[str, Any]:
    """评估一次运行：跑 L-A（+ 可选 L-B），落评估行，返回评估报告。"""
    from fde_api.simulation.service import _require_level

    _require_level(actor)
    with db.session() as session:
        run, traces = _load_run_and_traces(session, run_id)
        judge_view = _judge_view(session, run)
        artifacts = collect_artifacts(traces)

        criteria = score_criteria(traces=traces, artifacts=artifacts, judge_view=judge_view)
        hard_failures = detect_hard_failures(
            traces=traces, artifacts=artifacts, judge_view=judge_view
        )
        outcome = aggregate(criteria, hard_failures, rubric_version=RUBRIC_VERSION)

        deterministic_row = SimulationEvaluation(
            run_id=run.id,
            layer="deterministic",
            evaluator_id=DETERMINISTIC_EVALUATOR,
            mode="rules",
            rubric_version=outcome.rubric_version,
            scores_json={
                "criteria": [dict(item) for item in _criteria_json(outcome)],
                "dimension_scores": dict(outcome.dimension_scores),
                "dimensions": [
                    {"key": key, "name": name, "weight": weight}
                    for key, name, weight in DIMENSIONS
                ],
            },
            hard_failures_json=[failure.to_json() for failure in outcome.hard_failures],
            total_score=outcome.total_score,
            verdict=outcome.verdict,
            unverified_ratio=outcome.unverified_ratio,
            evidence_refs_json=[],
        )
        session.add(deterministic_row)
        session.flush()

        model_payload: dict[str, Any] | None = None
        if include_model:
            model_adapter = build_model_evaluation(model_mode)
            model_result = model_adapter.evaluate(
                judge_view=judge_view,
                artifacts=artifacts,
                traces=traces,
                rubric_version=RUBRIC_VERSION,
            )
            model_row = SimulationEvaluation(
                run_id=run.id,
                layer="model",
                evaluator_id=f"{MODEL_EVALUATOR_PREFIX}{model_result.mode}",
                mode=model_result.mode,
                rubric_version=RUBRIC_VERSION,
                scores_json={"criteria": [dict(item) for item in model_result.criteria]},
                hard_failures_json=[],
                total_score=model_result.total_score,
                verdict=model_result.verdict,
                unverified_ratio=0.0,
                evidence_refs_json=[],
                note=model_result.note,
            )
            session.add(model_row)
            session.flush()
            model_payload = _serialize_evaluation(model_row)

        disagreement = 0.0
        human_review_required = False
        reasons: list[str] = []
        if model_payload is not None and model_payload["verdict"] != "unavailable":
            disagreement = round(
                abs(outcome.total_score - float(model_payload["total_score"])), 4
            )
            if disagreement > DISAGREEMENT_THRESHOLD:
                human_review_required = True
                reasons.append("layer_disagreement")
        if outcome.verdict == "hard_fail" and HUMAN_REVIEW_ON_HARD_FAILURE:
            human_review_required = True
            reasons.append("hard_failure")
        if outcome.total_score < HUMAN_REVIEW_LOW_SCORE:
            human_review_required = True
            reasons.append("low_score")

        session.commit()
        return {
            "run_id": run.id,
            "verdict": outcome.verdict,
            "total_score": outcome.total_score,
            "unverified_ratio": outcome.unverified_ratio,
            "dimension_scores": dict(outcome.dimension_scores),
            "hard_failures": [failure.to_json() for failure in outcome.hard_failures],
            "deterministic": _serialize_evaluation(deterministic_row),
            "model": model_payload,
            "disagreement": disagreement,
            "human_review_required": human_review_required,
            "human_review_reasons": reasons,
            "meta": {
                "rubric_version": RUBRIC_VERSION,
                "adapter_mode": run.adapter_mode,
                "scenario_key": judge_view.get("case_code"),
                "disclaimer": "本评分为模拟环境的合成结果（假设 × 引擎），不冒充真实项目交付质量。",
            },
        }


def _criteria_json(outcome: Any) -> list[dict[str, Any]]:
    return [
        {
            "key": criterion.key,
            "dimension": criterion.dimension,
            "title": criterion.title,
            "weight": criterion.weight,
            "score": criterion.score,
            "verified": criterion.verified,
            "evidence_refs": [dict(ref) for ref in criterion.evidence_refs],
            "detail": dict(criterion.detail),
        }
        for criterion in outcome.criteria
    ]


def get_evaluation_report(*, actor: User, run_id: str) -> dict[str, Any]:
    """读取某次运行的评估报告（按层列出，**并列不合并**）。"""
    from fde_api.simulation.service import _require_level

    _require_level(actor)
    with db.session() as session:
        run = session.get(SimulationRun, run_id)
        if run is None:
            raise EvaluationError("not_found", "模拟运行不存在。", 404)
        rows = list(
            session.scalars(
                select(SimulationEvaluation)
                .where(SimulationEvaluation.run_id == run_id)
                .order_by(SimulationEvaluation.created_at, SimulationEvaluation.id)
            )
        )
        layers = [_serialize_evaluation(row) for row in rows]
        deterministic = next((item for item in layers if item["layer"] == "deterministic"), None)
        human = [item for item in layers if item["layer"] == "human"]
        model = next((item for item in layers if item["layer"] == "model"), None)
        disagreement = 0.0
        if deterministic and model and model["verdict"] != "unavailable":
            disagreement = round(abs(deterministic["total_score"] - model["total_score"]), 4)
        return {
            "run_id": run_id,
            "layers": layers,
            "deterministic": deterministic,
            "model": model,
            "human": human,
            "final": human[-1] if human else deterministic,
            "disagreement": disagreement,
            "human_review_required": bool(human) is False
            and (disagreement > DISAGREEMENT_THRESHOLD
                 or (deterministic or {}).get("verdict") == "hard_fail"),
            "meta": {
                "rubric_version": RUBRIC_VERSION,
                "adapter_mode": run.adapter_mode,
                "disclaimer": "本评分为模拟环境的合成结果（假设 × 引擎），不冒充真实项目交付质量。",
            },
        }


def record_human_evaluation(
    *, actor: User, run_id: str, payload: dict[str, Any]
) -> dict[str, Any]:
    """人工抽检结论（L-C）：落一条 human 层评估行。

    **不删除机器原行**——机器结论与人工结论并列留痕（留痕纪律）。
    """
    from fde_api.simulation.service import _require_level

    _require_level(actor)
    if actor.role not in ("admin", "project_lead"):
        raise EvaluationError("forbidden", "人工抽检结论需项目负责人或管理员。", 403)
    verdict = payload.get("verdict")
    allowed = ("pass", "conditional", "fail", "hard_fail", "inconclusive")
    if verdict not in allowed:
        raise EvaluationError("invalid_request", "verdict 取值非法。")
    total_score = payload.get("total_score")
    if not isinstance(total_score, (int, float)) or isinstance(total_score, bool):
        raise EvaluationError("invalid_request", "total_score 必须是数字。")
    if not 0.0 <= float(total_score) <= 1.0:
        raise EvaluationError("invalid_request", "total_score 必须在 0–1 之间。")
    note = payload.get("note")
    if not isinstance(note, str) or not note.strip():
        raise EvaluationError("invalid_request", "note 必填（人工结论必须留理由）。")

    with db.session() as session:
        run = session.get(SimulationRun, run_id)
        if run is None:
            raise EvaluationError("not_found", "模拟运行不存在。", 404)
        row = SimulationEvaluation(
            run_id=run.id,
            layer="human",
            evaluator_id=f"human:{actor.id}",
            mode="manual",
            rubric_version=RUBRIC_VERSION,
            scores_json={"criteria": list(payload.get("criteria") or [])},
            hard_failures_json=list(payload.get("hard_failures") or []),
            total_score=round(float(total_score), 4),
            verdict=str(verdict),
            unverified_ratio=float(payload.get("unverified_ratio") or 0.0),
            evidence_refs_json=list(payload.get("evidence_refs") or []),
            decided_by_user_id=actor.id,
            note=note.strip(),
        )
        session.add(row)
        session.flush()
        session.commit()
        return _serialize_evaluation(row)
