"""工作流节点/运行的结算面（架构评估 P1-2：从 executor.py 拆出）。

职责边界：**只写终态**——节点成功/失败/跳过/等待审批的落表，以及 run 的终态收敛
与审批拍板落点。分派（外呼/AI 调用）不在本模块（那在 dispatch.py），调度主循环
也不在本模块（那在 executor 门面）。

退避常量经**门面动态读取**（函数内惰性导入 executor）：常量单点仍住在
executor 门面，测试 monkeypatch `executor._RETRY_BACKOFF_BASE_SECONDS` 依旧生效
——这是拆分时最容易丢的一条语义。
"""
from __future__ import annotations

import time
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from fde_api.auth.models import User
from fde_api.extensions import db
from fde_api.jobs.outbox import enqueue_outbox, utcnow
from fde_api.projects.events import record_event
from fde_api.workbench.models import Project
from fde_api.workflows.constants import (
    CANCELLED_AFTER_DISPATCH_MARKER,
    TERMINAL_NODE_STATUSES,
    TERMINAL_RUN_STATUSES,
    WORKFLOW_JOB_TYPE,
    _NodeFailure,
)
from fde_api.workflows.models import WorkflowNodeRun, WorkflowRun


def _attach_gate_evidence_marker(
    session: Session, *, run_id: str, node: WorkflowNodeRun, output: Any
) -> None:
    """V3 T-W7：节点成功同事务读 output_json 顶层保留键 ``gate_evidence`` 挂候选。

    产物要成为候选必须由生产方自带指针+指纹，平台永不自动派生（立项 D1）；标记
    缺失 = 零副作用。坏标记不炸节点：非对象标记在此落 skipped 事件，字段级坏
    形状（gate 非法 / sha 非 64hex / 超长 / 双字段缺一）由 gate_service.
    attach_workflow_evidence_candidate 校验裁决——候选是建议性旁路，绝不改变节点
    成功语义。call 节点产物 = API 响应 dict 是自然生产方；skill/agent 产物为
    平台包装形（{text}/agent 摘要），顶层标记透传留待现实需求（不发明约束）。
    """
    marker = output.get("gate_evidence") if isinstance(output, dict) else None
    if marker is None:
        return
    run = session.get(WorkflowRun, run_id)
    if run is None or run.status in TERMINAL_RUN_STATUSES:
        return
    initiator = (
        session.get(User, run.initiated_by_user_id) if run.initiated_by_user_id else None
    )
    project = session.get(Project, run.project_id) if run.project_id else None
    if initiator is None or project is None:
        return
    if not isinstance(marker, dict):
        record_event(
            session,
            initiator,
            "gate_evidence_candidate_skipped",
            run,
            {
                "gate_key": None,
                "workflow_run_id": run_id,
                "workflow_node_key": node.node_key,
                "reason": "marker_not_object",
            },
        )
        return
    # 延迟导入：gate_service 侧事件/权限链与 executor 初始化顺序解耦
    # （task_service._sync_task_evidence 同款先例）
    from fde_api.projects.gate_service import attach_workflow_evidence_candidate

    attach_workflow_evidence_candidate(
        session,
        actor=initiator,
        project=project,
        run_id=run_id,
        node_key=node.node_key,
        gate_key=marker.get("gate"),
        source_uri=marker.get("source_uri"),
        content_hash=marker.get("content_sha256"),
        label=marker.get("label"),
    )


def _record_cancelled_after_dispatch(
    node: WorkflowNodeRun, payload: Any, *, outcome: str
) -> None:
    """CR-022：在途派发于节点被取消之后返回——「已执行外呼不回收（诚实呈现）」
    从账本事实升级为节点面可读事实：终态**不复活**（节点仍是 cancelled，
    FV-F1「断链不静默 done」不破），但把「确实执行了」落到 output_json：
    标记 + 派发产物 + action_id 指针（写类操作可回 api_actions 反查）。
    node.error 同时落稳定标记——桌面 WorkflowConsole 的「错误」列直接可见，
    零桌面改动即有呈现通道。
    """
    result = payload if isinstance(payload, dict) else {"value": payload}
    action_id = result.get("action_id") if isinstance(result, dict) else None
    node.output_json = {
        "cancelled_after_dispatch": True,
        "dispatch_outcome": outcome,
        "action_id": action_id,
        "dispatch_result": result,
    }
    node.error = CANCELLED_AFTER_DISPATCH_MARKER


def _settle_node_success(run_id: str, key: str, payload: dict[str, Any]) -> None:
    """tx B：产物先落表再前进（崩溃恢复锚点）。"""
    with db.session() as session, session.begin():
        node = session.scalar(
            select(WorkflowNodeRun).where(
                WorkflowNodeRun.run_id == run_id, WorkflowNodeRun.node_key == key
            )
        )
        if node is None:
            return
        if node.status not in ("pending", "ready", "running"):
            # CR-022：节点在派发后被取消——在途成功返回不得静默丢弃，诚实记录
            if node.status == "cancelled":
                _record_cancelled_after_dispatch(node, payload, outcome="succeeded")
            return
        node.status = "succeeded"
        node.output_json = payload
        node.error = None
        node.finished_at = utcnow()
        # V3 T-W7：顶层保留键 gate_evidence → 同事务挂门禁证据候选（call/skill/agent 共用此点）
        _attach_gate_evidence_marker(session, run_id=run_id, node=node, output=payload)


def _settle_node_failure(
    run_id: str,
    key: str,
    attempt: int,
    spec: dict[str, Any],
    failure: _NodeFailure,
) -> None:
    """失败落表：可重试且未超 max_retries → ready（退避后重派）；否则 failed。

    attempt 语义：首次尝试 attempt=1，重试条件 attempt <= max_retries，
    总尝试次数 = 1 + max_retries。
    """
    from fde_api.workflows import executor  # 惰性导入：退避常量单点在门面

    max_retries = int(spec.get("max_retries", 0) or 0)
    will_retry = failure.retryable and attempt <= max_retries
    with db.session() as session, session.begin():
        node = session.scalar(
            select(WorkflowNodeRun).where(
                WorkflowNodeRun.run_id == run_id, WorkflowNodeRun.node_key == key
            )
        )
        if node is None:
            return
        if node.status not in ("pending", "ready", "running"):
            # CR-022：节点在派发后被取消——在途失败同样不得静默丢弃（外呼可能
            # 已产生部分效果）；记录「取消后派发失败」+ 失败原因
            if node.status == "cancelled":
                _record_cancelled_after_dispatch(
                    node,
                    {"error": f"{failure.code}:{failure.message}"},
                    outcome="failed",
                )
            return
        node.error = f"{failure.code}:{failure.message}"
        if will_retry:
            node.status = "ready"
            node.finished_at = None
        else:
            node.status = "failed"
            node.finished_at = utcnow()
    if will_retry:
        delay = min(
            executor._RETRY_BACKOFF_BASE_SECONDS * (2 ** (attempt - 1)),
            executor._RETRY_BACKOFF_CAP_SECONDS,
        )
        if delay > 0:
            time.sleep(delay)


def _skip_node(run_id: str, key: str, reason: str) -> None:
    with db.session() as session, session.begin():
        node = session.scalar(
            select(WorkflowNodeRun).where(
                WorkflowNodeRun.run_id == run_id, WorkflowNodeRun.node_key == key
            )
        )
        if node is None or node.status in TERMINAL_NODE_STATUSES:
            return
        node.status = "skipped"
        node.error = reason
        node.finished_at = utcnow()


def _settle_run(run_id: str, status: str, error: str | None = None) -> None:
    with db.session() as session, session.begin():
        run = session.get(WorkflowRun, run_id)
        if run is None or run.status in TERMINAL_RUN_STATUSES:
            return
        run.status = status
        run.error = error
        # waiting_approval 不是终态：run 还没跑完，不盖 finished_at
        run.finished_at = utcnow() if status in TERMINAL_RUN_STATUSES else None
        actor = (
            session.get(User, run.initiated_by_user_id)
            if run.initiated_by_user_id
            else None
        )
        if actor is not None:
            record_event(
                session,
                actor,
                f"workflow_run_{status}",
                run,
                {"error": error} if error else {},
            )


def _settle_node_waiting(run_id: str, key: str, approval_id: str) -> None:
    """审批已建/复用 → 节点 waiting；审批 id 挂节点幂等键（崩溃恢复锚点）。"""
    with db.session() as session, session.begin():
        node = session.scalar(
            select(WorkflowNodeRun).where(
                WorkflowNodeRun.run_id == run_id, WorkflowNodeRun.node_key == key
            )
        )
        if node is None or node.status not in ("pending", "ready", "running"):
            return
        node.status = "waiting"
        node.idempotency_key = approval_id


def settle_approval_node(
    session: Session,
    approval: Any,
    *,
    approved: bool | None,
    reviewer: User | None,
) -> None:
    """审批拍板落点（control.decide_automation_approval 事务内调用，同事务提交）。

    approved=True → 节点 succeeded（output 携审批事实）并重投 workflow.run；
    False=拒绝 / None=过期 → 节点 failed（断链语义，重投后主循环收敛 run failed
    + 下游 skipped）。节点已不在 waiting（被取消/恢复重派）或 run 已终态时不动
    ——审批不再驱动节点（取消后补拍板只落审批行，如实记录）。
    """
    node = (
        session.get(WorkflowNodeRun, approval.workflow_node_run_id)
        if approval.workflow_node_run_id
        else None
    )
    if node is None or node.status != "waiting":
        return
    run = session.get(WorkflowRun, node.run_id)
    if run is None or run.status in TERMINAL_RUN_STATUSES:
        return
    node.finished_at = utcnow()
    if approved is True:
        node.status = "succeeded"
        node.error = None
        node.output_json = {
            "approval_id": approval.id,
            "decision": "approved",
            "reviewed_by_user_id": reviewer.id if reviewer else None,
            "decision_reason": approval.decision_reason,
        }
        # V3 T-W7：批准产物同事务读标记——现合同 output 无 gate_evidence → 零副作用；
        # 与 _settle_node_success 一致接线，未来包装层自带标记时零改生效。
        _attach_gate_evidence_marker(
            session, run_id=run.id, node=node, output=node.output_json
        )
    else:
        node.status = "failed"
        node.output_json = None
        node.error = (
            "approval_expired:操作审批已过期。"
            if approved is None
            else f"approval_rejected:{approval.decision_reason or '操作审批被拒绝。'}"
        )
    run.status = "running"
    run.error = None
    decision_label = "approved" if approved is True else ("expired" if approved is None else "rejected")
    if reviewer is not None:
        record_event(
            session,
            reviewer,
            "workflow_run_approval_decided",
            run,
            {
                "node_key": node.node_key,
                "decision": decision_label,
                "approval_id": approval.id,
            },
        )
    enqueue_outbox(session, WORKFLOW_JOB_TYPE, run.id, {})
