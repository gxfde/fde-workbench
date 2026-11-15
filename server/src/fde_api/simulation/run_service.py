"""模拟运行服务（G3）——创建 / 执行 / 查询 / 取消 / 重试 / Trace 读取。

幂等与终态纪律：
- ``run_key`` = ``scenario_key:variant:version:seed:attempt`` ⇒ 同键重放返回既有
  运行（不重复执行、不重复计费）。
- 终态运行不可再推进；``failed``（非 hard）可重试（``attempt+1`` 派生新键）；
  ``failed_hard`` **不可重试**（同一场景重复硬失败须改场景或改能力）。
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import select

from fde_api.auth.models import User
from fde_api.extensions import db
from fde_api.simulation.models import (
    ADAPTER_MODES,
    RUN_TERMINAL_STATUSES,
    SimulationRun,
    SimulationScenario,
    SimulationTrace,
)
from fde_api.simulation.runner import SimulationRunnerError, run_simulation
from fde_api.simulation.service import ScenarioServiceError

LIST_PAGE_SIZE = 50
MAX_LIST_PAGE_SIZE = 200
TRACE_PAGE_SIZE = 200
MAX_TRACE_PAGE_SIZE = 500
# 异步档位（学习闭环 2.0 L4 §2.1）：真模型单跑 30-60s 会卡请求 ⇒ 走后台队列；
# mock/real 小跑保持同步（零回归）。
ASYNC_ADAPTER_MODES = ("workbench",)


def _enqueue_run_job(session, run: SimulationRun) -> None:
    """经 outbox 入后台作业（topic＝job_type＝simulation.run；平台级计量）。"""
    from fde_api.jobs.outbox import enqueue_outbox

    enqueue_outbox(
        session,
        "simulation.run",
        run.id,
        {"run_id": run.id},
        subject_org=None,
    )


def _require_operator(user: User) -> None:
    # 权限档与场景库同尺（project_operator 档）；复用场景库服务的判定入口，
    # 避免两处口径漂移。
    from fde_api.simulation.service import _require_level

    _require_level(user)


def _config_fingerprint(config: dict[str, Any] | None) -> str:
    """配置指纹：同配置同 seed ⇒ 同一运行（幂等）；配置变了 ⇒ 另一条运行。

    指纹进 run_key，避免「改了访谈参数却被当成同一次运行」这种静默复用。
    """
    import hashlib
    import json

    canonical = json.dumps(config or {}, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:8]


def _run_key(
    *,
    scenario_key: str,
    variant: str,
    version: int,
    seed: int,
    attempt: int,
    config_fingerprint: str,
) -> str:
    return (
        f"{scenario_key}:{variant}:v{version}:seed{seed}"
        f":a{attempt}:cfg{config_fingerprint}"
    )


def _serialize_run(row: SimulationRun, *, include_context: bool = False) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "id": row.id,
        "run_key": row.run_key,
        "scenario_id": row.scenario_id,
        "scenario_version": row.scenario_version,
        "split": row.split,
        "status": row.status,
        "adapter_mode": row.adapter_mode,
        "seed": row.seed,
        "attempt": row.attempt,
        "actor_set": dict(row.actor_set_json or {}),
        "cost": dict(row.cost_json or {}),
        "error": dict(row.error_json) if row.error_json else None,
        "created_by_user_id": row.created_by_user_id,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "started_at": row.started_at,
        "finished_at": row.finished_at,
    }
    if include_context:
        payload["context"] = dict(row.context_json or {})
    return payload


def create_run(*, actor: User, payload: dict[str, Any]) -> dict[str, Any]:
    """创建模拟运行（不执行）。``execute=True`` 时立即跑一次（mock 模式同步）。"""
    _require_operator(actor)
    scenario_id = payload.get("scenario_id")
    if not isinstance(scenario_id, str) or not scenario_id:
        raise ScenarioServiceError("invalid_request", "scenario_id 必填。")
    adapter_mode = payload.get("adapter_mode") or "mock"
    if adapter_mode not in ADAPTER_MODES:
        raise ScenarioServiceError("invalid_request", "adapter_mode 取值非法。")
    seed = payload.get("seed")
    if seed is not None and (not isinstance(seed, int) or isinstance(seed, bool)):
        raise ScenarioServiceError("invalid_request", "seed 必须是整数。")
    config = payload.get("config")
    if config is not None and not isinstance(config, dict):
        raise ScenarioServiceError("invalid_request", "config 必须是对象。")

    with db.session() as session:
        scenario = session.get(SimulationScenario, scenario_id)
        if scenario is None:
            raise ScenarioServiceError("not_found", "场景不存在。", 404)
        version = payload.get("scenario_version")
        if version is not None:
            if not isinstance(version, int) or isinstance(version, bool):
                raise ScenarioServiceError("invalid_request", "scenario_version 必须是整数。")
            if version != scenario.version:
                raise ScenarioServiceError(
                    "not_found",
                    "该场景版本不存在（只支持运行当前版本）。",
                    404,
                )
        effective_seed = int(seed) if seed is not None else 0
        run_key = _run_key(
            scenario_key=scenario.scenario_key,
            variant=scenario.variant,
            version=scenario.version,
            seed=effective_seed,
            attempt=1,
            config_fingerprint=_config_fingerprint(config),
        )
        existing = session.scalar(select(SimulationRun).where(SimulationRun.run_key == run_key))
        if existing is not None:
            return {**_serialize_run(existing), "created": False}
        run = SimulationRun(
            run_key=run_key,
            scenario_id=scenario.id,
            scenario_version=scenario.version,
            split=scenario.split,
            status="queued",
            adapter_mode=adapter_mode,
            seed=effective_seed,
            attempt=1,
            actor_set_json={},
            context_json=dict(config or {}),
            cost_json={},
            created_by_user_id=actor.id,
        )
        session.add(run)
        session.flush()
        if payload.get("execute") and adapter_mode in ASYNC_ADAPTER_MODES:
            _enqueue_run_job(session, run)
            async_queued = True
        else:
            async_queued = False
        session.commit()
        result = {**_serialize_run(run), "created": True}
        if async_queued:
            return {**result, "queued_async": True}

    if payload.get("execute"):
        execute_run(actor=actor, run_id=result["id"])
        with db.session() as session:
            refreshed = session.get(SimulationRun, result["id"])
            if refreshed is not None:
                result = {**_serialize_run(refreshed), "created": True}
    return result


def execute_run(*, actor: User, run_id: str) -> dict[str, Any]:
    """执行一次模拟运行。workbench 档转后台作业（异步）；其余同步。

    真实适配面不可用时明确报错，不静默退回 mock。"""
    _require_operator(actor)
    with db.session() as session:
        row = session.get(SimulationRun, run_id)
        if row is None:
            raise ScenarioServiceError("not_found", "模拟运行不存在。", 404)
        if row.adapter_mode in ASYNC_ADAPTER_MODES:
            if row.status in RUN_TERMINAL_STATUSES:
                return {
                    **_serialize_run(row),
                    "outcome": {"run_id": row.id, "status": row.status, "idempotent": True},
                }
            _enqueue_run_job(session, row)
            session.commit()
            return {**_serialize_run(row), "queued_async": True}
    try:
        outcome = run_simulation(run_id)
    except SimulationRunnerError as error:
        raise ScenarioServiceError(error.code, error.message, error.status) from error
    with db.session() as session:
        row = session.get(SimulationRun, run_id)
        if row is None:
            raise ScenarioServiceError("not_found", "模拟运行不存在。", 404)
        return {**_serialize_run(row), "outcome": outcome}


def list_runs(
    *,
    actor: User,
    scenario_id: str | None = None,
    status: str | None = None,
    split: str | None = None,
    limit: int = LIST_PAGE_SIZE,
) -> dict[str, Any]:
    """运行列表。"""
    _require_operator(actor)
    capped = max(1, min(int(limit), MAX_LIST_PAGE_SIZE))
    with db.session() as session:
        stmt = select(SimulationRun)
        if scenario_id:
            stmt = stmt.where(SimulationRun.scenario_id == scenario_id)
        if status:
            stmt = stmt.where(SimulationRun.status == status)
        if split:
            stmt = stmt.where(SimulationRun.split == split)
        rows = list(
            session.scalars(stmt.order_by(SimulationRun.created_at.desc(), SimulationRun.id))
        )
        total = len(rows)
        page = rows[:capped]
        return {
            "items": [_serialize_run(row) for row in page],
            "total": total,
            "truncated": total > len(page),
        }


def get_run(*, actor: User, run_id: str, include_context: bool = False) -> dict[str, Any]:
    """运行详情。"""
    _require_operator(actor)
    with db.session() as session:
        row = session.get(SimulationRun, run_id)
        if row is None:
            raise ScenarioServiceError("not_found", "模拟运行不存在。", 404)
        return _serialize_run(row, include_context=include_context)


def cancel_run(*, actor: User, run_id: str) -> dict[str, Any]:
    """取消运行。终态运行不可取消（409）。"""
    _require_operator(actor)
    with db.session() as session:
        row = session.get(SimulationRun, run_id)
        if row is None:
            raise ScenarioServiceError("not_found", "模拟运行不存在。", 404)
        if row.status in RUN_TERMINAL_STATUSES:
            raise ScenarioServiceError(
                "conflict", "运行已处于终态，不可取消。", 409, {"status": row.status}
            )
        row.status = "cancelled"
        row.finished_at = row.finished_at or _now_iso()
        session.commit()
        return _serialize_run(row)


def retry_run(*, actor: User, run_id: str) -> dict[str, Any]:
    """重试运行：``attempt+1`` 派生新 run_key（同键不串号）。

    ``failed_hard`` **不可重试**——同一场景反复硬失败说明是能力/场景问题，
    重试只会重复烧钱。
    """
    _require_operator(actor)
    with db.session() as session:
        row = session.get(SimulationRun, run_id)
        if row is None:
            raise ScenarioServiceError("not_found", "模拟运行不存在。", 404)
        if row.status == "failed_hard":
            raise ScenarioServiceError(
                "conflict",
                "硬性失败运行不可重试：须先改场景或改能力。",
                409,
                {"status": row.status},
            )
        if row.status not in ("failed", "timeout", "cancelled"):
            raise ScenarioServiceError(
                "conflict", "只有失败/超时/取消的运行可重试。", 409, {"status": row.status}
            )
        scenario = session.get(SimulationScenario, row.scenario_id)
        if scenario is None:
            raise ScenarioServiceError("not_found", "场景不存在。", 404)
        attempt = int(row.attempt) + 1
        run_key = _run_key(
            scenario_key=scenario.scenario_key,
            variant=scenario.variant,
            version=scenario.version,
            seed=int(row.seed),
            attempt=attempt,
            config_fingerprint=_config_fingerprint(row.context_json),
        )
        existing = session.scalar(select(SimulationRun).where(SimulationRun.run_key == run_key))
        if existing is not None:
            return {**_serialize_run(existing), "created": False}
        retry = SimulationRun(
            run_key=run_key,
            scenario_id=row.scenario_id,
            scenario_version=row.scenario_version,
            split=row.split,
            status="queued",
            adapter_mode=row.adapter_mode,
            seed=int(row.seed),
            attempt=attempt,
            actor_set_json={},
            context_json=dict(row.context_json or {}),
            cost_json={},
            created_by_user_id=actor.id,
        )
        session.add(retry)
        session.flush()
        session.commit()
        return {**_serialize_run(retry), "created": True}


def list_traces(
    *,
    actor: User,
    run_id: str,
    phase: str | None = None,
    after_seq: int | None = None,
    limit: int = TRACE_PAGE_SIZE,
) -> dict[str, Any]:
    """读取运行 Trace（按 seq 游标分页）。"""
    _require_operator(actor)
    capped = max(1, min(int(limit), MAX_TRACE_PAGE_SIZE))
    with db.session() as session:
        run = session.get(SimulationRun, run_id)
        if run is None:
            raise ScenarioServiceError("not_found", "模拟运行不存在。", 404)
        stmt = select(SimulationTrace).where(SimulationTrace.run_id == run_id)
        if phase:
            stmt = stmt.where(SimulationTrace.phase == phase)
        if after_seq is not None:
            stmt = stmt.where(SimulationTrace.seq > after_seq)
        rows = list(session.scalars(stmt.order_by(SimulationTrace.seq)))
        total = len(rows)
        page = rows[:capped]
        return {
            "items": [
                {
                    "seq": row.seq,
                    "parent_seq": row.parent_seq,
                    "actor_id": row.actor_id,
                    "phase": row.phase,
                    "event_type": row.event_type,
                    "payload": dict(row.payload_json or {}),
                    "tool_call": dict(row.tool_call_json) if row.tool_call_json else None,
                    "evidence": dict(row.evidence_json) if row.evidence_json else None,
                    "cost": dict(row.cost_json) if row.cost_json else None,
                    "created_at": row.created_at.isoformat() if row.created_at else None,
                }
                for row in page
            ],
            "total": total,
            "truncated": total > len(page),
            "next_seq": page[-1].seq if page else None,
        }


def _now_iso() -> str:
    from datetime import UTC, datetime

    return datetime.now(UTC).isoformat()
