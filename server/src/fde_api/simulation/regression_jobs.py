"""模拟回归后台作业处理器（学习闭环 2.0 L5 §2.4）。

当回归套件配置 ``adapter_mode == "workbench"`` 或 ``model_mode == "server"`` 时，
``regression_service.run_regression`` 将工作单元经 outbox + ``BackgroundJob``
（``job_type == "simulation.regression"``，``target_id == suite_id``）入队，
由 worker 异步执行基线组＋候选组运行并落 ``RegressionResult``（零迁移）。
"""

from __future__ import annotations

import logging

from sqlalchemy import select

from fde_api.auth.models import User
from fde_api.extensions import db
from fde_api.jobs.handlers import register_handler
from fde_api.jobs.models import BackgroundJob, OutboxEvent
from fde_api.simulation.regression_service import (
    SIMULATION_REGRESSION_JOB_TYPE,
    execute_regression_sync,
)
from fde_api.simulation.service import ScenarioServiceError

logger = logging.getLogger(__name__)


def handle_simulation_regression_job(job: BackgroundJob) -> None:
    """后台 worker 驱动一次套件回归对比。"""
    suite_id = str(job.target_id)
    proposal_id: str | None = None
    actor_user_id: str | None = None
    with db.session() as session:
        event = session.scalars(
            select(OutboxEvent)
            .where(
                OutboxEvent.topic == SIMULATION_REGRESSION_JOB_TYPE,
                OutboxEvent.aggregate_id == suite_id,
            )
            .order_by(OutboxEvent.created_at.desc(), OutboxEvent.id.desc())
        ).first()
        if event is not None and isinstance(event.payload_json, dict):
            raw_prop = event.payload_json.get("proposal_id")
            if isinstance(raw_prop, str) and raw_prop.strip():
                proposal_id = raw_prop.strip()
            raw_actor = event.payload_json.get("actor_user_id")
            if isinstance(raw_actor, str) and raw_actor.strip():
                actor_user_id = raw_actor.strip()
        actor = session.get(User, actor_user_id) if actor_user_id else None
        if actor is None:
            actor = session.scalars(
                select(User).where(User.role == "admin", User.is_active.is_(True))
            ).first()
        if actor is None:
            logger.warning(
                "simulation.regression skipped (no active actor): suite_id=%s job_id=%s",
                suite_id,
                job.id,
            )
            return
        session.expunge(actor)

    try:
        execute_regression_sync(
            actor=actor,
            suite_id=suite_id,
            proposal_id=proposal_id,
        )
    except ScenarioServiceError as error:
        if error.code == "not_found":
            logger.warning(
                "simulation.regression target missing: suite_id=%s code=%s",
                suite_id,
                error.code,
            )
            return
        raise


def register_simulation_regression_handler() -> None:
    register_handler(SIMULATION_REGRESSION_JOB_TYPE, handle_simulation_regression_job)
