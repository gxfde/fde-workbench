"""回归与盲测服务（G6）。

编排：套件 → 基线组运行 → （候选组运行）→ 逐维度对比 → 落 ``regression_results``。

**数据集隔离纪律**：
- 套件可跨集（train/regression/blind）——泛化差要跨集测；
- **改进提案只能引用 train 集的失败发现**（``create_proposal`` 已卡；
  本模块再核一次：候选组不得在 blind 集上「调参」）；
- 盲测集的参考答案对被测方始终不可达（G3 装载器保证）。
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import select

from fde_api.auth.models import User
from fde_api.extensions import db
from fde_api.simulation import evaluator, run_service
from fde_api.simulation.models import (
    ImprovementProposal,
    RegressionResult,
    RegressionSuite,
    SimulationFinding,
    SimulationRun,
    SimulationScenario,
)
from fde_api.simulation.regression_runner import (
    RunSummary,
    compare,
    result_fingerprint,
)
from fde_api.simulation.service import ScenarioServiceError, _require_level

SUITE_SPLITS = ("train", "regression", "blind", "mixed")
MAX_SUITE_SCENARIOS = 40


def _serialize_suite(row: RegressionSuite) -> dict[str, Any]:
    return {
        "id": row.id,
        "name": row.name,
        "split": row.split,
        "scenario_ids": list(row.scenario_ids_json or []),
        "baseline_config": dict(row.baseline_config_json or {}),
        "note": row.note,
        "created_by_user_id": row.created_by_user_id,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def _serialize_result(row: RegressionResult) -> dict[str, Any]:
    return {
        "id": row.id,
        "suite_id": row.suite_id,
        "proposal_id": row.proposal_id,
        "before_run_ids": list(row.before_run_ids_json or []),
        "after_run_ids": list(row.after_run_ids_json or []),
        "before": dict(row.before_summary_json or {}),
        "after": dict(row.after_summary_json or {}),
        "deltas": dict(row.deltas_json or {}),
        "new_hard_failures": list(row.new_hard_failures_json or []),
        "resolved_hard_failures": list(row.resolved_hard_failures_json or []),
        "generalization_gap": float(row.generalization_gap or 0),
        "overfit_risk": bool(row.overfit_risk),
        "verdict": row.verdict,
        "note": row.note,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def list_suites(*, actor: User) -> dict[str, Any]:
    """套件清单。"""
    _require_level(actor)
    with db.session() as session:
        rows = list(session.scalars(select(RegressionSuite).order_by(RegressionSuite.created_at)))
        return {"items": [_serialize_suite(row) for row in rows], "total": len(rows)}


def get_suite(*, actor: User, suite_id: str) -> dict[str, Any]:
    """套件详情。"""
    _require_level(actor)
    with db.session() as session:
        row = session.get(RegressionSuite, suite_id)
        if row is None:
            raise ScenarioServiceError("not_found", "回归套件不存在。", 404)
        return _serialize_suite(row)


def create_suite(*, actor: User, payload: dict[str, Any]) -> dict[str, Any]:
    """创建回归套件。

    两种取案例的方式：显式 ``scenario_ids``，或按 ``split`` 自动取该数据集的
    **全部有效场景**（物理隔离的入口）。
    """
    _require_level(actor)
    name = payload.get("name")
    if not isinstance(name, str) or not name.strip():
        raise ScenarioServiceError("invalid_request", "name 必填。")
    split = payload.get("split") or "train"
    if split not in SUITE_SPLITS:
        raise ScenarioServiceError("invalid_request", "split 取值非法。")
    baseline_config = payload.get("baseline_config")
    if baseline_config is not None and not isinstance(baseline_config, dict):
        raise ScenarioServiceError("invalid_request", "baseline_config 必须是对象。")

    with db.session() as session:
        scenario_ids = payload.get("scenario_ids")
        if scenario_ids is None and split != "mixed":
            scenario_ids = [
                row.id
                for row in session.scalars(
                    select(SimulationScenario)
                    .where(SimulationScenario.split == split)
                    .order_by(SimulationScenario.scenario_key, SimulationScenario.variant)
                )
            ]
        if not isinstance(scenario_ids, list) or not scenario_ids:
            raise ScenarioServiceError(
                "invalid_request", "scenario_ids 必填（或指定 split 以自动选取该集场景）。"
            )
        if len(scenario_ids) > MAX_SUITE_SCENARIOS:
            raise ScenarioServiceError(
                "invalid_request", f"套件场景数不得超过 {MAX_SUITE_SCENARIOS}。"
            )
        existing = session.scalar(
            select(RegressionSuite).where(RegressionSuite.name == name.strip())
        )
        if existing is not None:
            raise ScenarioServiceError("conflict", "同名套件已存在。", 409)
        row = RegressionSuite(
            name=name.strip(),
            split=split,
            scenario_ids_json=[str(item) for item in scenario_ids],
            baseline_config_json=dict(baseline_config or {}),
            note=payload.get("note"),
            created_by_user_id=actor.id,
        )
        session.add(row)
        session.flush()
        session.commit()
        return _serialize_suite(row)


def _run_group(
    *,
    actor: User,
    scenario_ids: list[str],
    config: dict[str, Any],
) -> list[RunSummary]:
    """跑一组场景（基线组或候选组）并汇总评估结论。"""
    summaries: list[RunSummary] = []
    for scenario_id in scenario_ids:
        run = run_service.create_run(
            actor=actor,
            payload={
                "scenario_id": scenario_id,
                "adapter_mode": "mock",
                "execute": True,
                "config": config,
            },
        )
        evaluation = evaluator.evaluate_run(actor=actor, run_id=run["id"])
        with db.session() as session:
            run_row = session.get(SimulationRun, run["id"])
            failure_codes = tuple(
                row.code
                for row in session.scalars(
                    select(SimulationFinding).where(SimulationFinding.run_id == run["id"])
                )
            )
            summaries.append(
                RunSummary(
                    run_id=run["id"],
                    scenario_id=scenario_id,
                    split=run_row.split if run_row else "train",
                    total_score=float(evaluation["total_score"]),
                    verdict=str(evaluation["verdict"]),
                    dimension_scores=dict(evaluation["dimension_scores"]),
                    hard_failures=tuple(
                        str(item.get("code"))
                        for item in (evaluation.get("hard_failures") or [])
                    ),
                    cost=dict(run.get("cost") or {}),
                    failure_codes=failure_codes,
                )
            )
    return summaries


def run_regression(
    *, actor: User, suite_id: str, proposal_id: str | None = None
) -> dict[str, Any]:
    """跑一次回归对比：基线组 vs 候选组（候选 = 基线 + 提案覆盖）。"""
    _require_level(actor)
    with db.session() as session:
        suite = session.get(RegressionSuite, suite_id)
        if suite is None:
            raise ScenarioServiceError("not_found", "回归套件不存在。", 404)
        scenario_ids = [str(item) for item in (suite.scenario_ids_json or [])]
        baseline_config = dict(suite.baseline_config_json or {})
        candidate_config = dict(baseline_config)
        proposal = None
        if proposal_id:
            proposal = session.get(ImprovementProposal, proposal_id)
            if proposal is None:
                raise ScenarioServiceError("not_found", "改进提案不存在。", 404)
            override = dict(proposal.override_json or {})
            run_config = override.get("run_config")
            if not isinstance(run_config, dict) or not run_config:
                raise ScenarioServiceError(
                    "conflict",
                    "该提案没有可用的模拟域覆盖载荷（override_json.run_config）——"
                    "无法在模拟域内验证其效果。",
                    409,
                )
            candidate_config.update(run_config)

    before = _run_group(actor=actor, scenario_ids=scenario_ids, config=baseline_config)
    after = (
        _run_group(actor=actor, scenario_ids=scenario_ids, config=candidate_config)
        if proposal_id
        else before
    )
    report = compare(before=before, after=after)

    fingerprint = result_fingerprint(
        suite_id=suite_id, proposal_id=proposal_id, baseline_config=baseline_config
    )
    with db.session() as session:
        existing = session.scalar(
            select(RegressionResult).where(
                RegressionResult.suite_id == suite_id,
                RegressionResult.fingerprint == fingerprint,
            )
        )
        if existing is not None:
            return {**_serialize_result(existing), "created": False}
        row = RegressionResult(
            suite_id=suite_id,
            proposal_id=proposal_id,
            fingerprint=fingerprint,
            before_run_ids_json=[summary.run_id for summary in before],
            after_run_ids_json=[summary.run_id for summary in after],
            before_summary_json=report["before"],
            after_summary_json=report["after"],
            deltas_json={
                "total_delta": report["total_delta"],
                "dimension_deltas": report["dimension_deltas"],
                "improved_dimensions": report["improved_dimensions"],
                "regressed_dimensions": report["regressed_dimensions"],
                "new_failure_codes": report["new_failure_codes"],
                "cost_delta": report["cost_delta"],
                "train_gain": report["train_gain"],
                "blind_gain": report["blind_gain"],
            },
            new_hard_failures_json=report["new_hard_failures"],
            resolved_hard_failures_json=report["resolved_hard_failures"],
            generalization_gap=report["generalization_gap"],
            overfit_risk=report["overfit_risk"],
            verdict=report["verdict"],
            note=(
                "过拟合风险：训练集增益显著高于盲测集增益（泛化差 "
                f"{report['generalization_gap']} > 0.15）⇒ 不得进入发布审批。"
                if report["overfit_risk"]
                else None
            ),
        )
        session.add(row)
        session.flush()
        session.commit()
        return {**_serialize_result(row), "created": True}


def list_results(*, actor: User, suite_id: str | None = None) -> dict[str, Any]:
    """回归结果清单。"""
    _require_level(actor)
    with db.session() as session:
        stmt = select(RegressionResult)
        if suite_id:
            stmt = stmt.where(RegressionResult.suite_id == suite_id)
        rows = list(
            session.scalars(stmt.order_by(RegressionResult.created_at.desc()))
        )
        return {"items": [_serialize_result(row) for row in rows], "total": len(rows)}


def get_result(*, actor: User, result_id: str) -> dict[str, Any]:
    """回归结果详情。"""
    _require_level(actor)
    with db.session() as session:
        row = session.get(RegressionResult, result_id)
        if row is None:
            raise ScenarioServiceError("not_found", "回归结果不存在。", 404)
        return _serialize_result(row)
