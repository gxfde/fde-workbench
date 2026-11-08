"""工作流运行的恢复与收敛（架构评估 P1-2：从 executor.py 拆出）。

职责边界：**worker 侧的失败兜底与终态收敛**——handler 入口恢复（崩溃遗留的
running 节点放回 pending）、跳数熔断复核、worker 丢失收口，以及「一轮走到无可
推进」的终态收敛/断链跳过。

人工面的取消/恢复（cancel_run / resume_run）留在 executor 门面——它们是 HTTP
生命周期动作，与 worker 恢复是两件事。
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from fde_api.extensions import db
from fde_api.jobs.outbox import utcnow
from fde_api.workflows.constants import (
    MAX_RUN_HOPS,
    TERMINAL_NODE_STATUSES,
    TERMINAL_RUN_STATUSES,
)
from fde_api.workflows.dag_utils import _when_truthy
from fde_api.workflows.models import WorkflowNodeRun, WorkflowRun
from fde_api.workflows.settlement import _settle_run, _skip_node

if TYPE_CHECKING:
    from fde_api.jobs.models import BackgroundJob


def _fail_run_if_hops_exceeded(run_id: str) -> None:
    """B#1 跳数熔断入口复核（outbox 上下文无 actor，语义同 worker 丢失收口：
    error 落行即留痕，resume 重跑面由 resume_run 的 hops 闸拒绝）。"""
    with db.session() as session, session.begin():
        run = session.get(WorkflowRun, run_id)
        if run is None or run.status in TERMINAL_RUN_STATUSES:
            return
        if run.hops <= MAX_RUN_HOPS:
            return
        run.status = "failed"
        run.error = f"hops_exceeded:重投代际超上限（{MAX_RUN_HOPS}），熔断。"
        run.finished_at = utcnow()


def _fail_run_on_worker_loss(session: Session, job: BackgroundJob) -> None:
    """reconcile 放弃（尝试耗尽/不可恢复）时把 run 与悬挂节点推到终态。

    悬挂的 running 节点标 failed（产物未落表即未发生——诚实呈现，resume 可重跑）。
    """
    run = session.get(WorkflowRun, job.target_id)
    if run is None or run.status in TERMINAL_RUN_STATUSES:
        return
    run.status = "failed"
    run.error = "worker_lost:job_attempts_exhausted"
    run.finished_at = utcnow()
    for node in session.scalars(
        select(WorkflowNodeRun).where(WorkflowNodeRun.run_id == run.id)
    ):
        if node.status == "running":
            node.status = "failed"
            node.error = "worker_lost"


def _recover_interrupted(run_id: str) -> None:
    """handler 入口恢复：queued / waiting_approval → running；worker 死亡遗留的
    running 节点放回 pending（attempt 保留）。重跑安全由「succeeded 即锚点 +
    写节点幂等键 / 审批幂等键」保证。"""
    with db.session() as session, session.begin():
        run = session.get(WorkflowRun, run_id)
        if run is None or run.status in TERMINAL_RUN_STATUSES:
            return
        if run.status in ("queued", "waiting_approval"):
            run.status = "running"
        if run.started_at is None:
            run.started_at = utcnow()
        for node in session.scalars(
            select(WorkflowNodeRun).where(
                WorkflowNodeRun.run_id == run_id, WorkflowNodeRun.status == "running"
            )
        ):
            node.status = "pending"
            node.error = "interrupted:recovered"


def _finalize_pass(
    run_id: str,
    specs: dict[str, dict[str, Any]],
    nodes: dict[str, WorkflowNodeRun],
    context: dict[str, Any],
    outputs: dict[str, Any],
) -> bool:
    """一轮走到无可推进：终态收敛或断链跳过。返回 True 表示主循环应停止。"""
    non_terminal = [key for key, node in nodes.items() if node.status not in TERMINAL_NODE_STATUSES]
    if not non_terminal:
        failed = any(node.status == "failed" for node in nodes.values())
        _settle_run(run_id, "failed" if failed else "succeeded")
        return True
    progressed = False
    for key in non_terminal:
        node = nodes[key]
        if node.status == "waiting":
            continue  # 审批外挂中：永不 skip、不算进展（拍板落点负责推动）
        deps = list(node.depends_on or [])
        if not all(dep in nodes and nodes[dep].status in TERMINAL_NODE_STATUSES for dep in deps):
            continue  # 还有依赖未终态：交给下一轮
        if _when_truthy(specs.get(key, {}).get("when"), context, outputs):
            # 真值裁决成立却未被 ready 选中：本轮依赖刚终态，回到主循环重判
            continue
        _skip_node(run_id, key, "upstream_not_succeeded")
        progressed = True
    if not progressed:
        if any(node.status == "waiting" for node in nodes.values()):
            # 有 failed 先断链收敛（FV-F1）；否则整 run 挂起等拍板（重投续跑）
            if any(node.status == "failed" for node in nodes.values()):
                _settle_run(run_id, "failed")
            else:
                _settle_run(run_id, "waiting_approval")
            return True
        _settle_run(run_id, "failed", "scheduler_stuck:无可推进节点且无终态路径")
        return True
    return False  # 有节点被跳过：下游 may become ready/可继续收敛
