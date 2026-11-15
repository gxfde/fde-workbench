"""训练场后台运行作业（学习闭环 2.0 L4 §2.1 异步化）。

workbench 档单跑（真模型，30-60s）不再同步卡请求：``run_service`` 经 outbox
入队 ``simulation.run`` 作业（平台级计量标签），worker 拉起后调用既有
``run_simulation``——幂等由 run 终态判定承载（终态运行直接返回，不重复执行、
不重复计费）；模型面不可用 ⇒ 运行行诚实落 ``failed``（作业本身成功），
状态承载复用 ``BackgroundJob``（零迁移，评审裁定）。
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

SIMULATION_RUN_JOB_TYPE = "simulation.run"


def handle_simulation_run_job(job) -> None:
    """执行一次模拟运行（幂等；run 行承载真实状态）。"""
    from fde_api.simulation.runner import SimulationRunnerError, run_simulation

    run_id = str(job.target_id)
    try:
        outcome = run_simulation(run_id)
    except SimulationRunnerError as error:
        if error.code == "not_found":
            # 运行行已不存在（级联删除等）——无事可做，作业按成功收尾。
            logger.warning("simulation.run target missing job_id=%s run_id=%s", job.id, run_id)
            return
        raise
    logger.info(
        "simulation.run finished job_id=%s run_id=%s status=%s",
        job.id,
        run_id,
        outcome.get("status"),
    )


def register_simulation_run_handler() -> None:
    from fde_api.jobs.handlers import register_handler

    register_handler(SIMULATION_RUN_JOB_TYPE, handle_simulation_run_job)
