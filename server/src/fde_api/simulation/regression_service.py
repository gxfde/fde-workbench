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
from fde_api.simulation.evaluation_rules import RUBRIC_VERSION
from fde_api.simulation.models import (
    ADAPTER_MODES,
    RUN_TERMINAL_STATUSES,
    ImprovementProposal,
    RegressionResult,
    RegressionSuite,
    SimulationFinding,
    SimulationRun,
    SimulationScenario,
)
from fde_api.simulation.regression_runner import (
    DEFAULT_NOISE_BAND,
    DEFAULT_NOISE_BAND_AXIS,
    RunSummary,
    compare,
    result_fingerprint,
)
from fde_api.simulation.runner import run_simulation
from fde_api.simulation.service import ScenarioServiceError, _require_level

SUITE_SPLITS = ("train", "regression", "blind", "mixed")
MAX_SUITE_SCENARIOS = 40
SIMULATION_REGRESSION_JOB_TYPE = "simulation.regression"
MODEL_MODES = ("stub", "server")
# 可重试终态（与 run_service.retry_run 闸同闭集：failed 非 hard/timeout/cancelled）
RUN_RETRIABLE_STATUSES = ("failed", "timeout", "cancelled")
# 组内单 run 的重试预算＝「新执行」次数上限（穿越既有失败链不计数）——
# 重复执行回归时每次最多新增 2 个 attempt，成本有界；耗尽即排除 fail-closed。
MAX_GROUP_RUN_RETRIES = 2


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


def _resolve_modes(baseline_config: dict[str, Any]) -> tuple[str, str]:
    adapter_mode = str(baseline_config.get("adapter_mode") or "mock").strip()
    if adapter_mode not in ADAPTER_MODES:
        raise ScenarioServiceError(
            "invalid_request", f"baseline_config.adapter_mode 取值非法：{adapter_mode}"
        )
    model_mode = str(baseline_config.get("model_mode") or "stub").strip()
    if model_mode not in MODEL_MODES:
        raise ScenarioServiceError(
            "invalid_request", f"baseline_config.model_mode 取值非法：{model_mode}"
        )
    return adapter_mode, model_mode


def _resolve_noise_band(
    baseline_config: dict[str, Any], *, model_mode: str
) -> tuple[float | None, str]:
    """解析套件存档噪声带并执行评估轴强绑定比对（L5 §2.4，§6-3 拍板确认）。

    现算轴 ``f"{RUBRIC_VERSION}|model:{model_mode}"`` 与 ``baseline_config.noise_band.axis``
    不符 ⇒ 409 ``noise_band_axis_mismatch`` fail-closed（防错轴带跨轴套用）。

    ★无可用带 ⇒ 返回 ``band=None``（不是缺省带）：缺省带 0.1049 是在
    ``rubric-v1|model:server`` 轴下实测的观测极差，换轴后它不再是本轴的带；
    套用即跨轴套带（假绿家族）⇒ 本轴无实测带时模型层判定一律
    ``insufficient_data``（不可用即不判），待在新轴下实测归档后再跑。
    """
    current_axis = f"{RUBRIC_VERSION}|model:{model_mode}"
    archived = baseline_config.get("noise_band")
    if archived is None:
        if current_axis == DEFAULT_NOISE_BAND_AXIS:
            return DEFAULT_NOISE_BAND, current_axis
        return None, current_axis
    if not isinstance(archived, dict):
        raise ScenarioServiceError(
            "invalid_request", "baseline_config.noise_band 必须是对象。"
        )
    archived_axis = archived.get("axis")
    if isinstance(archived_axis, str) and archived_axis.strip() and archived_axis.strip() != current_axis:
        raise ScenarioServiceError(
            "noise_band_axis_mismatch",
            f"噪声带评估轴不匹配：套件存档轴 {archived_axis.strip()} ≠ 当前评估轴 {current_axis}。",
            409,
            {"archived_axis": archived_axis.strip(), "current_axis": current_axis},
        )
    raw_band = archived.get("band")
    if not (
        isinstance(raw_band, (int, float))
        and not isinstance(raw_band, bool)
        and raw_band >= 0
    ):
        raise ScenarioServiceError(
            "invalid_request",
            f"baseline_config.noise_band.band 非法（缺档案按当前轴 {current_axis} 实测归档）。",
            400,
            {"current_axis": current_axis},
        )
    return float(raw_band), current_axis


def _prepare_regression_inputs(
    session,
    *,
    suite_id: str,
    proposal_id: str | None,
) -> tuple[list[str], dict[str, Any], dict[str, Any], str, str, float | None, str]:
    suite = session.get(RegressionSuite, suite_id)
    if suite is None:
        raise ScenarioServiceError("not_found", "回归套件不存在。", 404)
    scenario_ids = [str(item) for item in (suite.scenario_ids_json or [])]
    baseline_config = dict(suite.baseline_config_json or {})
    adapter_mode, model_mode = _resolve_modes(baseline_config)
    band, current_axis = _resolve_noise_band(baseline_config, model_mode=model_mode)
    candidate_config = dict(baseline_config)
    if proposal_id:
        proposal = session.get(ImprovementProposal, proposal_id)
        if proposal is None:
            raise ScenarioServiceError("not_found", "改进提案不存在。", 404)
        override = dict(proposal.override_json or {})
        run_config = override.get("run_config")
        candidate_payload = dict(proposal.candidate_payload_json or {})
        has_run_config = isinstance(run_config, dict) and bool(run_config)
        has_candidate_payload = bool(candidate_payload)
        if not has_run_config and not has_candidate_payload:
            raise ScenarioServiceError(
                "conflict",
                "该提案没有可用的模拟域覆盖载荷（override_json.run_config 或 candidate_payload_json）——"
                "无法在模拟域内验证其效果。",
                409,
            )
        if has_run_config and isinstance(run_config, dict):
            candidate_config.update(run_config)
        if has_candidate_payload:
            # 沙箱同尺（L5 §2.5C）：overlay 候选片段违规在回归入口即 fail-closed 拒跑
            overlay_frag = candidate_payload.get("prompt_overlay_fragment")
            if isinstance(overlay_frag, dict):
                from fde_api.ai.overlays import purpose_allowed, validate_overlay_fragment

                p_key = str(overlay_frag.get("purpose_key") or "").strip()
                if p_key and not purpose_allowed(p_key):
                    raise ScenarioServiceError(
                        "invalid_request",
                        "候选 overlay purpose_key 不在允许白名单内。",
                        409,
                        {"purpose_key": p_key},
                    )
                violation = validate_overlay_fragment(str(overlay_frag.get("fragment") or ""))
                if violation is not None:
                    raise ScenarioServiceError(
                        "invalid_request",
                        f"候选 overlay 未通过句式静态闸（{violation}）。",
                        409,
                        {"violation": violation},
                    )
            candidate_config["candidate_payload"] = candidate_payload
    return (
        scenario_ids,
        baseline_config,
        candidate_config,
        adapter_mode,
        model_mode,
        band,
        current_axis,
    )


def _run_error_code(row: SimulationRun | None) -> str:
    if row is None or not row.error_json:
        return ""
    code = row.error_json.get("code")
    return str(code) if code else ""


def _materialize_group_run(
    *,
    actor: User,
    run: dict[str, Any],
    scenario_id: str,
) -> tuple[str | None, dict[str, Any] | None, list[str]]:
    """确保组内 run 达到可评分状态；不可评分 ⇒ 返回排除明细（不评分）。

    排除纪律（unavailable 不进判定，L6 收尾轮）：执行失败的 run 不得进回归
    判定分母——残缺 transcript 的维度缺席会被 summarize 计 0 分、把执行伪影
    伪装成「regressed」（2026-11-17 实弹：三 run design 阶段截断 ⇒ 假
    regressed）。处置：

    - failed（非 hard）/timeout/cancelled 沿 ``run_service.retry_run`` 文档
      语义**内联重试**（attempt+1 派生新键）；重试预算按「新执行」计数
      （``MAX_GROUP_RUN_RETRIES``）——穿越既有失败链（retry_run 返回
      created=False 的历史失败 attempt）不消耗预算，保证重复执行回归时
      能继续向前派生新 attempt 而不是永久卡死在同一失败链上；
    - ``failed_hard`` 不可重试（重试只会重复烧钱）直接排除；
    - 预算耗尽仍失败 ⇒ 排除（fail-closed）。

    返回 ``(scored_run_id | None, exclusion | None, attempted_ids)``。
    """
    run_id = str(run["id"])
    attempted = [run_id]
    if run.get("status") not in RUN_TERMINAL_STATUSES:
        run_simulation(run_id)
    fresh_executions = 0
    while True:
        with db.session() as session:
            row = session.get(SimulationRun, run_id)
            status = row.status if row is not None else "failed"
            if status == "completed":
                return run_id, None, attempted
            if status not in RUN_RETRIABLE_STATUSES or fresh_executions >= MAX_GROUP_RUN_RETRIES:
                exclusion = {
                    "run_id": str(run["id"]),
                    "retry_run_id": run_id if run_id != str(run["id"]) else None,
                    "scenario_id": scenario_id,
                    "status": status,
                    "error_code": _run_error_code(row),
                }
                return None, exclusion, attempted
        retried = run_service.retry_run(actor=actor, run_id=run_id)
        retried_id = str(retried["id"])
        if retried.get("created"):
            fresh_executions += 1
        if retried_id != run_id:
            attempted.append(retried_id)
        if retried.get("status") not in RUN_TERMINAL_STATUSES:
            run_simulation(retried_id)
        run_id = retried_id


def _run_group(
    *,
    actor: User,
    scenario_ids: list[str],
    config: dict[str, Any],
    adapter_mode: str = "mock",
    model_mode: str = "stub",
) -> tuple[list[RunSummary], list[dict[str, Any]], list[str]]:
    """跑一组场景（基线组或候选组）并汇总评估结论。

    参数化支持 mock/workbench 执行面与 stub/server 评估面；在回归批作业内，
    即使 adapter_mode=="workbench" 也直接在当前 worker 同步跑完单题（create_run
    execute=False + run_simulation），避免嵌套入队死锁。

    返回 ``(summaries, excluded, attempted_ids)``：``summaries`` 只含可评分
    （completed）run；``excluded`` 为执行失败 run 的排除明细（进入结果
    deltas_json 留痕）；``attempted_ids`` 为全部尝试过的 run id（含重试）。
    """
    run_config = {
        k: v
        for k, v in config.items()
        if k not in ("adapter_mode", "model_mode", "noise_band")
    }
    summaries: list[RunSummary] = []
    excluded: list[dict[str, Any]] = []
    attempted: list[str] = []
    for scenario_id in scenario_ids:
        run = run_service.create_run(
            actor=actor,
            payload={
                "scenario_id": scenario_id,
                "adapter_mode": adapter_mode,
                "execute": False,
                "config": run_config,
            },
        )
        scored_id, exclusion, attempted_ids = _materialize_group_run(
            actor=actor, run=run, scenario_id=scenario_id
        )
        attempted.extend(attempted_ids)
        if scored_id is None:
            assert exclusion is not None
            excluded.append(exclusion)
            continue
        evaluation = evaluator.evaluate_run(
            actor=actor, run_id=scored_id, model_mode=model_mode
        )
        model_block = evaluation.get("model") if isinstance(evaluation.get("model"), dict) else None
        model_total: float | None = None
        if model_block is not None and model_block.get("verdict") != "unavailable":
            raw_mt = model_block.get("total_score")
            if isinstance(raw_mt, (int, float)) and not isinstance(raw_mt, bool):
                model_total = float(raw_mt)
        rubric_ver = str((evaluation.get("meta") or {}).get("rubric_version") or RUBRIC_VERSION)
        eval_axis = f"{rubric_ver}|model:{model_mode}"
        with db.session() as session:
            run_row = session.get(SimulationRun, scored_id)
            failure_codes = tuple(
                row.code
                for row in session.scalars(
                    select(SimulationFinding).where(SimulationFinding.run_id == scored_id)
                )
            )
            summaries.append(
                RunSummary(
                    run_id=scored_id,
                    scenario_id=scenario_id,
                    split=run_row.split if run_row else "train",
                    total_score=float(evaluation["total_score"]),
                    verdict=str(evaluation["verdict"]),
                    dimension_scores=dict(evaluation["dimension_scores"]),
                    hard_failures=tuple(
                        str(item.get("code"))
                        for item in (evaluation.get("hard_failures") or [])
                    ),
                    cost=dict((run_row.cost_json if run_row else None) or run.get("cost") or {}),
                    failure_codes=failure_codes,
                    model_total=model_total,
                    evaluator_axis=eval_axis,
                )
            )
    return summaries, excluded, attempted


def execute_regression_sync(
    *, actor: User, suite_id: str, proposal_id: str | None = None
) -> dict[str, Any]:
    """同步执行一次回归对比并落 RegressionResult（供小跑直调与后台 worker 复用）。"""
    with db.session() as session:
        (
            scenario_ids,
            baseline_config,
            candidate_config,
            adapter_mode,
            model_mode,
            band,
            current_axis,
        ) = _prepare_regression_inputs(session, suite_id=suite_id, proposal_id=proposal_id)

    before, before_excluded, before_ids = _run_group(
        actor=actor,
        scenario_ids=scenario_ids,
        config=baseline_config,
        adapter_mode=adapter_mode,
        model_mode=model_mode,
    )
    if proposal_id:
        after, after_excluded, after_ids = _run_group(
            actor=actor,
            scenario_ids=scenario_ids,
            config=candidate_config,
            adapter_mode=adapter_mode,
            model_mode=model_mode,
        )
        excluded_runs = [*before_excluded, *after_excluded]
    else:
        after, after_ids = before, before_ids
        excluded_runs = list(before_excluded)
    report = compare(
        before=before,
        after=after,
        noise_band=band,
        noise_band_axis=current_axis,
    )
    if excluded_runs:
        # 幸存者偏差闸（L6 收尾轮）：候选组执行失败可能与候选本身相关
        # （如注入后输出变长触发截断），只在幸存样本上判「无回归」＝伪装
        # 达成 ⇒ 排除纪律触发时一律 fail-closed 判 inconclusive。
        report["verdict"] = "inconclusive"
    report["excluded_runs"] = excluded_runs

    fingerprint = result_fingerprint(
        suite_id=suite_id,
        proposal_id=proposal_id,
        baseline_config={**baseline_config, "_candidate": candidate_config if proposal_id else {}},
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
        note: str | None = None
        if excluded_runs:
            detail = "；".join(
                f"{item.get('run_id', '')[:8]}({item.get('status')}:{item.get('error_code') or 'n/a'})"
                for item in excluded_runs
            )
            note = (
                f"{len(excluded_runs)} 个 run 执行失败被排除（unavailable 不进判定，"
                f"防残缺 transcript 伪装判定）：{detail} ⇒ 判据不可信，verdict 强制 inconclusive。"
            )
        if report["overfit_risk"]:
            overfit_note = (
                "过拟合风险：训练集增益显著高于盲测集增益（泛化差 "
                f"{report['generalization_gap']} > 0.15）⇒ 不得进入发布审批。"
            )
            note = f"{note} {overfit_note}" if note else overfit_note
        row = RegressionResult(
            suite_id=suite_id,
            proposal_id=proposal_id,
            fingerprint=fingerprint,
            before_run_ids_json=before_ids,
            after_run_ids_json=after_ids,
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
                "model_verdict": report["model_verdict"],
                "model_total_delta": report["model_total_delta"],
                "noise_band": report["noise_band"],
                "noise_band_axis": report["noise_band_axis"],
                "excluded_runs": excluded_runs,
            },
            new_hard_failures_json=report["new_hard_failures"],
            resolved_hard_failures_json=report["resolved_hard_failures"],
            generalization_gap=report["generalization_gap"],
            overfit_risk=report["overfit_risk"],
            verdict=report["verdict"],
            note=note,
        )
        session.add(row)
        session.flush()
        session.commit()
        return {**_serialize_result(row), "created": True}


def run_regression(
    *,
    actor: User,
    suite_id: str,
    proposal_id: str | None = None,
    force_sync: bool = False,
) -> dict[str, Any]:
    """跑一次回归对比：stub+mock 同步返回结果；model:server 或 workbench 转 BackgroundJob 异步。"""
    _require_level(actor)
    with db.session() as session:
        (
            _scenario_ids,
            _baseline_config,
            _candidate_config,
            adapter_mode,
            model_mode,
            _band,
            _current_axis,
        ) = _prepare_regression_inputs(session, suite_id=suite_id, proposal_id=proposal_id)
        needs_async = (not force_sync) and (
            adapter_mode == "workbench" or model_mode == "server"
        )
        if needs_async:
            from fde_api.jobs.outbox import enqueue_outbox
            from fde_api.jobs.queue import ensure_background_job

            event = enqueue_outbox(
                session,
                SIMULATION_REGRESSION_JOB_TYPE,
                suite_id,
                {
                    "suite_id": suite_id,
                    "proposal_id": proposal_id,
                    "actor_user_id": actor.id,
                },
                subject_org=None,
            )
            job = ensure_background_job(
                session,
                SIMULATION_REGRESSION_JOB_TYPE,
                suite_id,
                subject_org=None,
            )
            session.commit()
            return {
                "queued_async": True,
                "job_id": job.id,
                "outbox_event_id": event.id,
                "job_status": job.status,
                "suite_id": suite_id,
                "proposal_id": proposal_id,
                "adapter_mode": adapter_mode,
                "model_mode": model_mode,
            }

    return execute_regression_sync(
        actor=actor, suite_id=suite_id, proposal_id=proposal_id
    )


def get_regression_job_status(*, actor: User, job_id: str) -> dict[str, Any]:
    """查询异步回归 BackgroundJob 状态（供桌面端轮询，零新表零迁移）。"""
    from fde_api.jobs.models import BackgroundJob

    _require_level(actor)
    with db.session() as session:
        job = session.get(BackgroundJob, job_id)
        if job is None or job.job_type != SIMULATION_REGRESSION_JOB_TYPE:
            raise ScenarioServiceError("not_found", "回归后台作业不存在。", 404)
        latest_result = session.scalars(
            select(RegressionResult)
            .where(RegressionResult.suite_id == job.target_id)
            .order_by(RegressionResult.created_at.desc(), RegressionResult.id.desc())
        ).first()
        return {
            "job_id": job.id,
            "suite_id": job.target_id,
            "status": job.status,
            "attempts": job.attempts,
            "last_error": job.last_error or None,
            "latest_result": _serialize_result(latest_result) if latest_result is not None else None,
        }


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
