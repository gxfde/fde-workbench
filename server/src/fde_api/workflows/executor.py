"""Workflow 执行器（V3 T-W3，设计 workflow-dag-v1 §3/§5）。

决策 3 落实：workflow 是 background_jobs 的一个 job_type（``workflow.run``，
target_id=workflow_run_id）——编排 handler 在一个 job 内驱动节点循环，复用既有
队列的 lease/token/续租/reconcile/failure-hook 全套机制，绝不复制第二套队列。

§3 红线（每条都有对应实现与测试）：
- **节点独立事务**：每个节点的状态迁移各自提交，产物先落表再前进（崩溃恢复锚点）；
  分派（HTTP/AI 调用）一律发生在任何打开的事务之外（2026-10-30 登录事故的教训）；
- **call 走 execute_api 同闸**：同一鉴权/确认/项目 scope，绝不旁路；权限每节点实时
  校验（发起人当下 AI 档位 ∩ 项目 scope），run 级不冻结；
- **缺占位符键 → 节点 failed + error**，绝不填空串（修 fde-v2 call 节点缺陷）；
- **断链不静默 done**：出现 failed 节点 → run failed（修 FV-F1 的执行侧）；
- **外副作用幂等**：写类（api_catalog write=True）call 节点由执行器强制落节点级
  idempotency_key（与 api_actions.execute_api 同构 sha256），重试/崩溃恢复同键，
  api_execute 层按 action 去重，不二次外呼。

T-W3 范围：call + skill 节点。skill 执行沿用 active 版本语义（与 T-W1 校验口径
一致），T-S1 落地后收敛 published；skill 节点 = 固定版本 instructions 作系统提示的
确定性 AI 调用（use_tools=False——skill 只做文本变换，工具面留在 call 节点）。

T-W4 范围：agent + human_approval 节点。
- agent 节点走 ``agents.service.start_run`` 同闸（实时能力鉴权 / 月度预算 / 试点
  配额 / T1/T6 评审门 / 沙箱 / 产物校验全链），绝不旁路；幂等键
  ``wfnode-{节点行id}:{attempt}``——agents 服务对失败终态 run 拒绝同键重跑（V8：
  重试必须显式），工作流以 attempt 代际表达「显式重试」（resume_run），同 attempt
  重复投递命中 completed 复用；agent 分派失败一律不自动重试（agents 自带重试族）。
- human_approval 节点复用 automation_approvals（run_id 置空 + workflow_node_run_id
  反链，迁移 d5b8e2f4a7c9）：request_key=wfnode:{节点行id}、arguments_sha256 绑定
  输入快照、risk_level=4、15 分钟过期（expires_minutes 节点字段可调）；拍板走既有
  任务中心路由（decide_automation_approval），批准 → 节点 succeeded 并重投
  workflow.run，拒绝/过期 → 节点 failed（断链语义）。等待期间 run =
  waiting_approval（handler 正常返回，靠拍板重投续跑）；无人拍板则挂起可取消。

§6 用例 4 的「paused→resume」精确化为 failed + resume_run（§3 终态语义优先：有
failed → run failed）；resume 的 HTTP 面随 T-W5 与 cancel 一起开，服务层本轮可用。
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
import time
from datetime import timedelta
from typing import TYPE_CHECKING, Any, Sequence
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from fde_api.auth.models import User
from fde_api.extensions import db
from fde_api.jobs.outbox import enqueue_outbox, utcnow
from fde_api.projects.events import record_event
from fde_api.projects.permissions import project_access
from fde_api.workbench.models import Project
from fde_api.workflows.definition_service import (
    PLACEHOLDER_PATTERN,
    serialize_definition,
)
from fde_api.workflows.models import (
    WorkflowDefinition,
    WorkflowDefinitionVersion,
    WorkflowNodeRun,
    WorkflowRun,
)

if TYPE_CHECKING:
    from fde_api.jobs.models import BackgroundJob

logger = logging.getLogger(__name__)

WORKFLOW_JOB_TYPE = "workflow.run"
TERMINAL_RUN_STATUSES = ("succeeded", "failed", "cancelled")
TERMINAL_NODE_STATUSES = ("succeeded", "failed", "skipped", "cancelled")
# 四类节点全部落地（T-W3：call/skill；T-W4：agent/human_approval）；守卫防未来类型漏实现
SUPPORTED_NODE_TYPES = ("call", "skill", "agent", "human_approval")
# 审批材料体上限（与 control.service.create_dsh_approval_request 同口径）
_APPROVAL_PAYLOAD_LIMIT_BYTES = 64_000
# 重试退避（指数，封顶）；测试里 monkeypatch 基数即可归零
_RETRY_BACKOFF_BASE_SECONDS = 1.0
_RETRY_BACKOFF_CAP_SECONDS = 20.0


class WorkflowRunError(Exception):
    """运行生命周期错误（HTTP 面与内部调用共用；shape 同 WorkflowDefinitionError）。"""

    def __init__(
        self, code: str, message: str, status: int, detail: dict[str, Any] | None = None
    ):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status
        self.detail = detail or {}


class _NodeFailure(Exception):
    """节点分派失败（内部信号：由 _settle_node_failure 落表，绝不外抛出 handler）。"""

    def __init__(self, code: str, message: str, *, retryable: bool):
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable


class _MissingPlaceholder(Exception):
    def __init__(self, name: str):
        super().__init__(name)
        self.name = name


# ---------------------------------------------------------------------------
# 运行生命周期：发起 / 详情 / 取消 / 恢复（cancel/resume 的 HTTP 面随 T-W5 开）
# ---------------------------------------------------------------------------


def load_project(session: Session, actor: User, project_id: str, *, manage: bool) -> Project:
    project = session.get(Project, project_id)
    if project is None:
        raise WorkflowRunError("project_not_found", "项目不存在或已被删除。", 404)
    access = project_access(actor, project)
    if not (access.can_manage if manage else access.can_view):
        raise WorkflowRunError("forbidden", "你没有该项目的操作权限。", 403)
    return project


def load_definition(
    session: Session,
    actor: User,
    project_id: str,
    definition_id: str,
    *,
    manage: bool = True,
) -> tuple[Project, WorkflowDefinition]:
    """项目内或平台模板定义；跨项目引用一律 404（不泄露存在性）。"""
    project = load_project(session, actor, project_id, manage=manage)
    definition = session.get(WorkflowDefinition, definition_id)
    if definition is None or (
        definition.project_id is not None and definition.project_id != project.id
    ):
        raise WorkflowRunError("definition_not_found", "工作流定义不存在。", 404)
    return project, definition


def _normalize_idempotency_key(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not 0 < len(value.strip()) <= 120:
        raise WorkflowRunError("invalid_request", "idempotency_key 须为 1–120 字符。", 400)
    return value.strip()


def start_run(
    session: Session,
    *,
    actor: User,
    project_id: str,
    definition_id: str,
    context: dict[str, Any] | None = None,
    idempotency_key: str | None = None,
) -> tuple[WorkflowRun, bool]:
    """发起一次运行（can_manage）。

    幂等键检查先于定义查找（同键重放不因定义归属变化而 404）：同幂等键且同项目
    → 返回既有 run（created=False）；跨项目同键 → 409（幂等键全局唯一是 FV-F3 的
    表级保证，不回显他人 run）。只接受 published 定义；含未知节点类型的 DAG 在此
    422 拒绝（不留必死 run）。
    """
    project = load_project(session, actor, project_id, manage=True)
    clean_key = _normalize_idempotency_key(idempotency_key)
    if clean_key is not None:
        existing = session.scalar(
            select(WorkflowRun).where(WorkflowRun.idempotency_key == clean_key)
        )
        if existing is not None:
            if existing.project_id != project.id:
                raise WorkflowRunError(
                    "idempotency_conflict", "幂等键已被其它项目的运行占用。", 409
                )
            return existing, False
    definition = session.get(WorkflowDefinition, definition_id)
    if definition is None or (
        definition.project_id is not None and definition.project_id != project.id
    ):
        raise WorkflowRunError("definition_not_found", "工作流定义不存在。", 404)
    if definition.status != "published":
        raise WorkflowRunError(
            "definition_not_published", "只有已发布的定义可以发起运行。", 409
        )

    if context is not None and (
        not isinstance(context, dict) or not all(isinstance(k, str) for k in context)
    ):
        raise WorkflowRunError("invalid_request", "context 必须是字符串键的对象。", 400)

    version = _version_row(session, definition, definition.version)
    dag_nodes = _dag_nodes(version.dag_json)
    unsupported = sorted(
        {str(node.get("type")) for node in dag_nodes} - set(SUPPORTED_NODE_TYPES)
    )
    if unsupported:
        raise WorkflowRunError(
            "unsupported_node_type",
            f"执行器不支持节点类型：{'、'.join(unsupported)}。",
            422,
            {"node_types": unsupported},
        )

    run = WorkflowRun(
        definition_id=definition.id,
        definition_version=definition.version,
        project_id=project.id,
        status="queued",
        initiated_by_user_id=actor.id,
        idempotency_key=clean_key or f"run-{uuid4().hex}",
        context_json={},
    )
    session.add(run)
    session.flush()
    # 运行级占位符源：默认三键 + 调用方自定义（定义期校验只认默认键，见 T-W1 记录）
    run.context_json = {
        "project_id": run.project_id,
        "run_id": run.id,
        "initiated_by_user_id": actor.id,
        **(context or {}),
    }
    for node in dag_nodes:
        session.add(
            WorkflowNodeRun(
                run_id=run.id,
                node_key=str(node["key"]),
                node_type=str(node["type"]),
                depends_on=list(node.get("depends_on") or []),
            )
        )
    record_event(
        session,
        actor,
        "workflow_run_created",
        run,
        {
            "definition_id": definition.id,
            "definition_version": definition.version,
            "idempotency_key": run.idempotency_key,
            "node_count": len(dag_nodes),
        },
    )
    # 事务性 outbox：worker 的 dispatch_pending 把它变成 background_jobs 里的
    # workflow.run（ensure_background_job 的单活守卫天然防重复投递）
    enqueue_outbox(session, WORKFLOW_JOB_TYPE, run.id, {})
    session.flush()
    return run, True


def get_run_detail(*, actor: User, project_id: str, run_id: str) -> dict[str, Any]:
    """run + 节点态树（can_view；节点按定义拓扑序）。"""
    with db.session() as session:
        run, _project = _load_run(session, actor, project_id, run_id, manage=False)
        return {"run": serialize_run(run, ordered_nodes(session, run))}


def cancel_run(*, actor: User, project_id: str, run_id: str) -> dict[str, Any]:
    """取消（can_manage）：停未执行节点，已执行外呼不回收（诚实呈现）。幂等。

    waiting 节点一并取消；其挂着的 pending 审批行不动（拍板落点发现节点已不在
    waiting 即不再驱动，审批按既有语义过期或如实记决定）。
    """
    with db.session() as session, session.begin():
        run, _project = _load_run(session, actor, project_id, run_id, manage=True)
        nodes = ordered_nodes(session, run)
        if run.status == "cancelled":
            return {"run": serialize_run(run, nodes), "cancelled": False}
        if run.status in TERMINAL_RUN_STATUSES:
            raise WorkflowRunError(
                "already_terminal", f"运行已终态（{run.status}），不能取消。", 409
            )
        run.status = "cancelled"
        run.finished_at = utcnow()
        for node in nodes:
            if node.status not in TERMINAL_NODE_STATUSES:
                node.status = "cancelled"
        record_event(session, actor, "workflow_run_cancelled", run, {"run_id": run.id})
        return {"run": serialize_run(run, nodes), "cancelled": True}


def resume_run(*, actor: User, project_id: str, run_id: str) -> dict[str, Any]:
    """恢复失败运行（can_manage）：failed/skipped 节点放回 pending（attempt 归零，
    计数按每轮恢复重置），已完成节点原样复用；重新投递 workflow.run。"""
    with db.session() as session, session.begin():
        run, _project = _load_run(session, actor, project_id, run_id, manage=True)
        if run.status != "failed":
            raise WorkflowRunError(
                "not_resumable",
                "只有失败的运行可以恢复（成功/取消为终态；等待审批的运行请先拍板或取消）。",
                409,
            )
        nodes = ordered_nodes(session, run)
        reset = 0
        for node in nodes:
            if node.status in ("failed", "skipped"):
                node.status = "pending"
                node.attempt = 0
                node.error = None
                node.started_at = None
                node.finished_at = None
                reset += 1
        run.status = "running"
        run.error = None
        record_event(session, actor, "workflow_run_resumed", run, {"reset_nodes": reset})
        enqueue_outbox(session, WORKFLOW_JOB_TYPE, run.id, {})
        return {"run": serialize_run(run, nodes), "reset_nodes": reset}


def list_platform_definitions(*, actor: User) -> list[dict[str, Any]]:
    """平台模板定义（project_id NULL；仅 admin）。"""
    if actor.role != "admin":
        raise WorkflowRunError("forbidden", "只有管理员可以查看平台模板工作流。", 403)
    with db.session() as session:
        rows = session.scalars(
            select(WorkflowDefinition)
            .where(WorkflowDefinition.project_id.is_(None))
            .order_by(WorkflowDefinition.created_at.desc(), WorkflowDefinition.id)
        ).all()
        return [serialize_definition(row) for row in rows]


def _load_run(
    session: Session, actor: User, project_id: str, run_id: str, *, manage: bool
) -> tuple[WorkflowRun, Project]:
    project = load_project(session, actor, project_id, manage=manage)
    run = session.get(WorkflowRun, run_id)
    if run is None or run.project_id != project.id:
        raise WorkflowRunError("run_not_found", "运行不存在。", 404)
    return run, project


# ---------------------------------------------------------------------------
# 序列化
# ---------------------------------------------------------------------------


def _iso(value: Any) -> str | None:
    return value.isoformat() if value is not None else None


def serialize_run(
    run: WorkflowRun, nodes: Sequence[WorkflowNodeRun]
) -> dict[str, Any]:
    return {
        "id": run.id,
        "definition_id": run.definition_id,
        "definition_version": run.definition_version,
        "project_id": run.project_id,
        "status": run.status,
        "idempotency_key": run.idempotency_key,
        "initiated_by_user_id": run.initiated_by_user_id,
        "context_json": run.context_json,
        "error": run.error,
        "started_at": _iso(run.started_at),
        "finished_at": _iso(run.finished_at),
        "created_at": _iso(run.created_at),
        "nodes": [_serialize_node(node) for node in nodes],
    }


def _serialize_node(node: WorkflowNodeRun) -> dict[str, Any]:
    return {
        "node_key": node.node_key,
        "node_type": node.node_type,
        "status": node.status,
        "attempt": node.attempt,
        "depends_on": node.depends_on,
        "idempotency_key": node.idempotency_key,
        "input_snapshot": node.input_snapshot,
        "output_json": node.output_json,
        "error": node.error,
        "started_at": _iso(node.started_at),
        "finished_at": _iso(node.finished_at),
    }


# ---------------------------------------------------------------------------
# jobs 接线：handler 注册 + failure hook + 执行主循环
# ---------------------------------------------------------------------------


def register_workflow_handler() -> None:
    from fde_api.jobs.handlers import register_handler, register_job_failure_handler

    register_handler(WORKFLOW_JOB_TYPE, _run_workflow_job)
    register_job_failure_handler(WORKFLOW_JOB_TYPE, _fail_run_on_worker_loss)


def _run_workflow_job(job: BackgroundJob) -> None:
    run_workflow_run(job.target_id)


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


def run_workflow_run(run_id: str) -> None:
    """执行主循环（jobs handler 主体）：幂等（终态直接返回）。

    每轮：取下一个 ready 节点（依赖全 succeeded，或 when 真值裁决放行）→ 独立事务
    执行；无 ready 且全部终态 → run 终态；无 ready 但有断链 → 按规则跳过并继续；
    剩余节点全在等审批 → run = waiting_approval，handler 正常返回（拍板重投续跑）；
    无任何进展且无人等待 → run failed（调度死锁防御）。迭代上限 = 全图最大尝试数 + 余量。
    """
    _recover_interrupted(run_id)
    dag_nodes = _load_version_dag(run_id)
    specs = {str(node["key"]): node for node in dag_nodes}
    order = _topo_order(dag_nodes)
    iteration_limit = (
        sum(int(specs[key].get("max_retries", 0)) + 1 for key in order) + len(order) + 4
    )
    for _ in range(iteration_limit):
        with db.session() as session:
            run = session.get(WorkflowRun, run_id)
            if run is None or run.status in TERMINAL_RUN_STATUSES:
                return
            nodes = {
                node.node_key: node
                for node in session.scalars(
                    select(WorkflowNodeRun).where(WorkflowNodeRun.run_id == run_id)
                )
            }
            context = dict(run.context_json or {})
        outputs = {
            specs[key]["output"]: nodes[key].output_json
            for key in order
            if specs[key].get("output")
            and nodes.get(key) is not None
            and nodes[key].status == "succeeded"
            and nodes[key].output_json is not None
        }
        ready = next(
            (
                key
                for key in order
                if nodes.get(key) is not None
                and nodes[key].status in ("pending", "ready")
                and _deps_green(key, nodes, specs, context, outputs)
            ),
            None,
        )
        if ready is not None:
            if not _execute_node(run_id, ready, specs):
                return  # run 已外部终态（取消）
            continue
        if _finalize_pass(run_id, specs, nodes, context, outputs):
            return
    _settle_run(run_id, "failed", "scheduler_stuck:迭代超限，无可推进节点（疑似调度缺陷）")


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


def _deps_green(
    key: str,
    nodes: dict[str, WorkflowNodeRun],
    specs: dict[str, dict[str, Any]],
    context: dict[str, Any],
    outputs: dict[str, Any],
) -> bool:
    deps = list(nodes[key].depends_on or [])
    if all(dep in nodes and nodes[dep].status == "succeeded" for dep in deps):
        return True
    # when 允许在依赖非全绿但已全部终态时裁决（§3「when 绕过」）；
    # 解析失败按假值处理 → finalize 阶段 skip，不断链。
    when = specs.get(key, {}).get("when")
    if (
        when
        and all(dep in nodes and nodes[dep].status in TERMINAL_NODE_STATUSES for dep in deps)
        and _when_truthy(when, context, outputs)
    ):
        return True
    return False


# ---------------------------------------------------------------------------
# 单节点执行（独立事务链）
# ---------------------------------------------------------------------------


def _execute_node(
    run_id: str, key: str, specs: dict[str, dict[str, Any]]
) -> bool:
    """tx A（running+attempt+input 幂等键）→ 分派（无事务）→ tx B（终态+产物）。

    human_approval 节点分派 = 建审批行（tx 内），落点 tx 把节点置 waiting 并挂
    审批 id 作幂等键。返回 False 仅当 run 已外部终态（取消），主循环随即退出。
    """
    prepared = _begin_node(run_id, key, specs)
    if prepared is None:
        return False
    if not prepared["dispatch"]:
        return True
    node_id = prepared["node_id"]
    attempt = prepared["attempt"]
    node_type = specs[key].get("type")
    if node_type == "human_approval":
        try:
            approval_id = _dispatch_human_approval(
                run_id, key, specs[key], node_id, prepared["input"]
            )
        except _NodeFailure as failure:
            _settle_node_failure(run_id, key, attempt, specs[key], failure)
        except Exception:  # noqa: BLE001
            logger.exception("workflow node dispatch crashed run_id=%s node=%s", run_id, key)
            _settle_node_failure(
                run_id,
                key,
                attempt,
                specs[key],
                _NodeFailure("dispatch_crashed", "节点执行异常，请查看执行器日志。", retryable=True),
            )
        else:
            _settle_node_waiting(run_id, key, approval_id)
        return True
    try:
        payload = _dispatch(run_id, key, specs[key], node_id, prepared["input"], attempt)
    except _NodeFailure as failure:
        _settle_node_failure(run_id, key, attempt, specs[key], failure)
    except Exception:  # noqa: BLE001 —— 未预期异常按失败落表，不让 job 层重投整个 run
        logger.exception("workflow node dispatch crashed run_id=%s node=%s", run_id, key)
        # agent 分派崩溃不自动重试：start_run 可能已拉起沙箱 run，同图重试有二次执行面
        retryable = node_type != "agent"
        _settle_node_failure(
            run_id,
            key,
            attempt,
            specs[key],
            _NodeFailure("dispatch_crashed", "节点执行异常，请查看执行器日志。", retryable=retryable),
        )
    else:
        _settle_node_success(run_id, key, payload)
    return True


def _begin_node(
    run_id: str, key: str, specs: dict[str, dict[str, Any]]
) -> dict[str, Any] | None:
    """tx A：占位符解析 + 标 running；解析失败直接落 failed（绝不填空串）。

    写类 call 节点在此落节点级幂等键（分派前持久化——崩溃恢复同键的前提）。
    """
    with db.session() as session, session.begin():
        run = session.get(WorkflowRun, run_id)
        if run is None or run.status in TERMINAL_RUN_STATUSES:
            return None
        node = session.scalar(
            select(WorkflowNodeRun).where(
                WorkflowNodeRun.run_id == run_id, WorkflowNodeRun.node_key == key
            )
        )
        if node is None or node.status not in ("pending", "ready"):
            return None  # 已取消或并发接管
        all_nodes = {
            row.node_key: row
            for row in session.scalars(
                select(WorkflowNodeRun).where(WorkflowNodeRun.run_id == run_id)
            )
        }
        context = dict(run.context_json or {})
        outputs = {
            specs[dep_key]["output"]: all_nodes[dep_key].output_json
            for dep_key in all_nodes
            if dep_key in specs
            and specs[dep_key].get("output")
            and all_nodes[dep_key].status == "succeeded"
            and all_nodes[dep_key].output_json is not None
        }
        try:
            resolved = _resolve_value(specs[key].get("params") or {}, context, outputs)
        except _MissingPlaceholder as missing:
            node.status = "failed"
            node.error = f"placeholder_missing:{missing.name}"
            node.finished_at = utcnow()
            return {"dispatch": False, "attempt": node.attempt, "node_id": node.id}
        node.attempt = (node.attempt or 0) + 1
        node.status = "running"
        node.started_at = utcnow()
        node.input_snapshot = resolved
        if _is_external_call(specs[key]) and not node.idempotency_key:
            node.idempotency_key = _call_action_identifier(
                run, node, specs[key], resolved
            )
        return {"dispatch": True, "attempt": node.attempt, "node_id": node.id, "input": resolved}


def _settle_node_success(run_id: str, key: str, payload: dict[str, Any]) -> None:
    """tx B：产物先落表再前进（崩溃恢复锚点）。"""
    with db.session() as session, session.begin():
        node = session.scalar(
            select(WorkflowNodeRun).where(
                WorkflowNodeRun.run_id == run_id, WorkflowNodeRun.node_key == key
            )
        )
        if node is None or node.status not in ("pending", "ready", "running"):
            return
        node.status = "succeeded"
        node.output_json = payload
        node.error = None
        node.finished_at = utcnow()


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
    max_retries = int(spec.get("max_retries", 0) or 0)
    will_retry = failure.retryable and attempt <= max_retries
    with db.session() as session, session.begin():
        node = session.scalar(
            select(WorkflowNodeRun).where(
                WorkflowNodeRun.run_id == run_id, WorkflowNodeRun.node_key == key
            )
        )
        if node is None or node.status not in ("pending", "ready", "running"):
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
            _RETRY_BACKOFF_BASE_SECONDS * (2 ** (attempt - 1)),
            _RETRY_BACKOFF_CAP_SECONDS,
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


# ---------------------------------------------------------------------------
# 分派：call（execute_api 同闸）与 skill（pinned 版本 AI 调用）
# ---------------------------------------------------------------------------


def _dispatch(
    run_id: str,
    key: str,
    spec: dict[str, Any],
    node_id: str,
    input_snapshot: dict[str, Any],
    attempt: int,
) -> dict[str, Any]:
    node_type = spec.get("type")
    if node_type == "call":
        return _dispatch_call(run_id, spec, node_id, input_snapshot)
    if node_type == "skill":
        return _dispatch_skill(run_id, spec, node_id, input_snapshot)
    if node_type == "agent":
        return _dispatch_agent(run_id, spec, node_id, input_snapshot, attempt)
    raise _NodeFailure(
        "unsupported_node_type", f"执行器不支持节点类型：{node_type}。", retryable=False
    )


def _dispatch_call(
    run_id: str, spec: dict[str, Any], node_id: str, input_snapshot: dict[str, Any]
) -> dict[str, Any]:
    """call 节点 = api_execute 同一闸（鉴权/确认/项目 scope），绝不旁路。

    参数约定：params 中与 ref 路径模板匹配的键 → path 参数（须为字符串）；
    保留键 body（对象）→ 请求体；其余 → query。写类操作命中确认闸（sensitive）
    时 execute_api 不执行任何变更，节点按 failed 诚实呈现（T-W4 接审批前置）。
    """
    from fde_api.control.access import capabilities_for_level, effective_ai_access
    from fde_api.control.api_actions import execute_api
    from fde_api.control.service import ControlServiceError

    ref = str(spec["ref"])
    parameters, body, query = _split_call_params(ref, input_snapshot)
    with db.session() as session:
        run = session.get(WorkflowRun, run_id)
        user = session.get(User, run.initiated_by_user_id) if run else None
        if run is None or user is None or not user.is_active:
            raise _NodeFailure(
                "initiator_unavailable", "发起人账号不可用，无法执行节点。", retryable=False
            )
        allowed = capabilities_for_level(effective_ai_access(user)[0])
        project_id = run.project_id
    claims = {"execution_id": f"wfnode-{node_id}", "project_id": project_id}
    try:
        result = execute_api(
            user=user,
            claims=claims,
            allowed=allowed,
            operation=ref,
            parameters=parameters,
            body=body,
            query=query,
        )
    except ControlServiceError as error:
        raise _NodeFailure(
            error.code, error.message, retryable=getattr(error, "status", 500) >= 500
        ) from error
    if not isinstance(result, dict):
        raise _NodeFailure("invalid_api_response", "API 执行未返回对象结果。", retryable=False)
    status = result.get("status")
    if status == "awaiting_confirmation":
        raise _NodeFailure(
            "awaiting_confirmation",
            f"该操作需要人工确认（工作流暂无确认通道），未执行；"
            f"action_id={result.get('action_id')}。请走 AI 会话或人工执行。",
            retryable=False,
        )
    if status == "running":
        raise _NodeFailure("action_in_flight", "同名操作正在执行，稍后重试。", retryable=True)
    http_status = result.get("http_status")
    if isinstance(http_status, int) and http_status >= 400:
        raise _NodeFailure(
            f"api_http_{http_status}", f"API 返回 {http_status}。", retryable=http_status >= 500
        )
    return result


def _dispatch_skill(
    run_id: str, spec: dict[str, Any], node_id: str, input_snapshot: dict[str, Any]
) -> dict[str, Any]:
    """skill 节点 = pinned 版本 instructions 作系统提示的确定性 AI 调用。

    use_tools=False：不签发 MCP token，skill 只做文本变换；工具面属于 call 节点。
    execution_id = wfnode-{node 行 id}（跨重试/恢复稳定，审计可回溯）。
    """
    from fde_api.control.ai_server_client import execute_ai_prompt
    from fde_api.control.dsh_runtime import DSHRuntimeError
    from fde_api.control.models import SkillDefinition, SkillVersion
    from fde_api.control.service import ControlServiceError

    key_part, _, version_part = str(spec["ref"]).partition("@")
    with db.session() as session:
        run = session.get(WorkflowRun, run_id)
        if run is None:
            raise _NodeFailure("run_not_found", "运行不存在。", retryable=False)
        rows = session.execute(
            select(SkillDefinition, SkillVersion)
            .join(
                SkillVersion,
                (SkillVersion.skill_id == SkillDefinition.id)
                & (SkillVersion.version_number == int(version_part)),
            )
            .where(
                SkillDefinition.skill_key == key_part,
                SkillDefinition.status == "active",
            )
            .order_by(SkillDefinition.scope.desc(), SkillDefinition.created_at, SkillDefinition.id)
            .limit(1)
        ).first()
        if rows is None:
            raise _NodeFailure(
                "skill_ref_unavailable",
                f"skill 版本不可用：{spec['ref']}（与定义期校验同口径，T-S1 后收敛 published）。",
                retryable=False,
            )
        _skill, version = rows
        instructions = version.instructions_text
        initiator_id, project_id = run.initiated_by_user_id, run.project_id
    if not initiator_id:
        raise _NodeFailure("initiator_unavailable", "发起人账号不可用，无法执行节点。", retryable=False)
    prompt = json.dumps(input_snapshot, ensure_ascii=False)
    try:
        answer = execute_ai_prompt(
            user_id=initiator_id,
            prompt=prompt,
            execution_id=f"wfnode-{node_id}",
            project_id=project_id,
            use_tools=False,
            system_prompt=instructions,
        )
    except DSHRuntimeError as error:
        raise _NodeFailure(error.code, error.public_message, retryable=error.retryable) from error
    except ControlServiceError as error:
        raise _NodeFailure(
            error.code, error.message, retryable=getattr(error, "status", 500) >= 500
        ) from error
    if not isinstance(answer, str):
        answer = json.dumps(answer, ensure_ascii=False)
    return {"text": answer}


def _dispatch_agent(
    run_id: str,
    spec: dict[str, Any],
    node_id: str,
    input_snapshot: dict[str, Any],
    attempt: int,
) -> dict[str, Any]:
    """agent 节点 = agents.start_run 同闸（实时鉴权/预算/试点/T1/T6/沙箱/产物校验）。

    幂等键 ``wfnode-{节点行id}:{attempt}``：agents 服务对失败终态 run 拒绝同键重跑
    （V8：重试必须显式），工作流以 attempt 代际表达「显式重试」（resume_run /
    retryable 崩溃恢复各开新代际）；同 attempt 内重复投递命中 completed 复用。
    params.solution_id（占位符解析后）透传给 run——agent_assisted / T1 等方案闸
    随之生效。失败一律 retryable=False：agents 自带重试族与退避，工作流不叠加。
    """
    from fde_api.agents import service as agents_service

    with db.session() as session:
        run = session.get(WorkflowRun, run_id)
        user = session.get(User, run.initiated_by_user_id) if run else None
        if run is None or user is None or not user.is_active:
            raise _NodeFailure(
                "initiator_unavailable", "发起人账号不可用，无法执行节点。", retryable=False
            )
        project_id = run.project_id
    payload: dict[str, Any] = {
        "project_id": project_id,
        "idempotency_key": f"wfnode-{node_id}:{attempt}",
    }
    solution_id = input_snapshot.get("solution_id")
    if isinstance(solution_id, str) and solution_id.strip():
        payload["solution_id"] = solution_id.strip()
    try:
        data, _status = agents_service.start_run(
            actor=user, agent_id=str(spec["ref"]), payload=payload
        )
    except agents_service.AgentsServiceError as error:
        raise _NodeFailure(error.code, error.message, retryable=False) from error
    if not isinstance(data, dict) or not data.get("id"):
        raise _NodeFailure(
            "invalid_agent_response", "智能体 run 未返回可解析结果。", retryable=False
        )
    agent_status = str(data.get("status"))
    if agent_status != "completed":
        raise _NodeFailure(
            f"agent_run_{agent_status}",
            f"智能体 run 终态为 {agent_status}，未产出 completed 结果。",
            retryable=False,
        )
    return {
        "agent_run_id": data["id"],
        "agent_run_status": agent_status,
        "token_cost": data.get("token_cost"),
        "duration_ms": data.get("duration_ms"),
        "degraded": data.get("degraded"),
        "fallback_level": data.get("fallback_level"),
        "artifacts": data.get("artifacts") or [],
    }


def _dispatch_human_approval(
    run_id: str,
    key: str,
    spec: dict[str, Any],
    node_id: str,
    input_snapshot: dict[str, Any],
) -> str:
    """human_approval 节点 = 复用 automation_approvals（run_id 空 + 节点反链）。

    定义期已闸 capability ∈ 登记表白名单；分派时按 DSH 审批同款实时校验发起人
    当下仍具备该能力。审批材料 = 运行上下文事实（run/节点/输入快照），敏感键命中
    或超 64KB 拒绝入审。幂等：节点幂等键已挂审批 id 或存在同节点 pending 审批时
    直接复用（崩溃恢复不重复建单）。风险档固定 4（人工门 = 保守高险，诚实标注）。
    """
    from fde_api.control.access import authorize_ai_capability, contains_sensitive_argument
    from fde_api.control.models import AutomationApproval

    expires_minutes = int(spec.get("expires_minutes", 15) or 15)
    capability = str(spec["capability"])
    with db.session() as session, session.begin():
        run = session.get(WorkflowRun, run_id)
        node = session.scalar(
            select(WorkflowNodeRun).where(
                WorkflowNodeRun.run_id == run_id, WorkflowNodeRun.node_key == key
            )
        )
        if run is None or node is None:
            raise _NodeFailure("run_not_found", "运行不存在。", retryable=False)
        if node.idempotency_key:
            existing = session.get(AutomationApproval, node.idempotency_key)
            if existing is not None:
                return existing.id  # 崩溃恢复：审批已建，直接复用
        pending = session.scalar(
            select(AutomationApproval).where(
                AutomationApproval.workflow_node_run_id == node.id,
                AutomationApproval.status == "pending",
            )
        )
        if pending is not None:
            return pending.id  # waiting 落表前崩溃：回收既有 pending 审批
        initiator = (
            session.get(User, run.initiated_by_user_id) if run.initiated_by_user_id else None
        )
        if initiator is None or not initiator.is_active:
            raise _NodeFailure(
                "initiator_unavailable", "发起人账号不可用，无法发起审批。", retryable=False
            )
        project = session.get(Project, run.project_id)
        decision = authorize_ai_capability(user=initiator, capability=capability, project=project)
        if not decision.allowed:
            raise _NodeFailure(
                decision.reason or "permission_revoked",
                "发起人已不具备该审批节点所需能力，无法发起审批。",
                retryable=False,
            )
        arguments = {
            "kind": "workflow.human_approval",
            "workflow_run_id": run_id,
            "node_key": key,
            "input": input_snapshot,
        }
        canonical = json.dumps(
            arguments, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
        )
        if len(canonical.encode("utf-8")) > _APPROVAL_PAYLOAD_LIMIT_BYTES:
            raise _NodeFailure(
                "approval_payload_too_large",
                f"审批材料超过 {_APPROVAL_PAYLOAD_LIMIT_BYTES} 字节上限。",
                retryable=False,
            )
        if contains_sensitive_argument(arguments):
            raise _NodeFailure(
                "sensitive_argument_rejected",
                "审批材料包含敏感键，拒绝进入审批（与 DSH 审批同闸）。",
                retryable=False,
            )
        approval = AutomationApproval(
            run_id=None,
            workflow_node_run_id=node.id,
            project_id=run.project_id,
            requested_by_user_id=initiator.id,
            request_key=f"wfnode:{node.id}"[:160],
            capability=capability,
            tool_name="workflow.human_approval",
            arguments_json=arguments,
            arguments_sha256=hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
            risk_level=4,
            status="pending",
            expires_at=utcnow() + timedelta(minutes=expires_minutes),
            decision_reason="",
        )
        session.add(approval)
        session.flush()
        return approval.id


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


# ---------------------------------------------------------------------------
# call 参数拆分与幂等键（与 control/api_actions 同构）
# ---------------------------------------------------------------------------


def _split_call_params(
    ref: str, resolved: dict[str, Any]
) -> tuple[dict[str, str], dict[str, Any], dict[str, Any]]:
    from fde_api.control.api_catalog import CATALOG

    path = str(CATALOG[ref]["path"])
    path_params = set(re.findall(r"\{(\w+)\}", path))
    parameters = {
        key: value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
        for key, value in resolved.items()
        if key in path_params
    }
    raw_body = resolved.get("body")
    body: dict[str, Any] = dict(raw_body) if isinstance(raw_body, dict) else {}
    query = {
        key: value
        for key, value in resolved.items()
        if key not in path_params and key != "body"
    }
    return parameters, body, query


def _is_external_call(spec: dict[str, Any]) -> bool:
    """外副作用推断（T-R2 effect 结构化前）：写类 api_catalog 条目。"""
    from fde_api.control.api_catalog import CATALOG

    return spec.get("type") == "call" and bool(CATALOG[str(spec["ref"])]["write"])


def _call_action_identifier(
    run: WorkflowRun, node: WorkflowNodeRun, spec: dict[str, Any], resolved: dict[str, Any]
) -> str:
    """与 api_actions.execute_api 完全同构的 sha256：
    identifier = sha256(json([user_id, execution_id, data]))，其中 execution_id =
    ``wfnode-{node 行 id}``、data = {operation, parameters, body, query}。
    节点行跨重试/恢复稳定 ⇒ 同键 ⇒ api_execute 层按 action 去重，不二次外呼。"""
    parameters, body, query = _split_call_params(str(spec["ref"]), resolved)
    data = {"operation": str(spec["ref"]), "parameters": parameters, "body": body, "query": query}
    payload = json.dumps(
        [run.initiated_by_user_id, f"wfnode-{node.id}", data],
        ensure_ascii=False,
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# dag / 拓扑 / 占位符（执行器侧纯函数）
# ---------------------------------------------------------------------------


def _dag_nodes(dag: Any) -> list[dict[str, Any]]:
    nodes = dag.get("nodes") if isinstance(dag, dict) else None
    if not isinstance(nodes, list) or not nodes:
        raise WorkflowRunError("dag_invalid", "定义快照损坏：nodes 缺失。", 422)
    return [node for node in nodes if isinstance(node, dict)]


def _topo_order(dag_nodes: list[dict[str, Any]]) -> list[str]:
    """执行器侧确定性拓扑序（Kahn，key 字典序稳定）；定义期已过环检测，
    防御性场景下的部分序由主循环迭代上限兜底。"""
    by_key = {str(node["key"]): node for node in dag_nodes}
    indegree = {key: 0 for key in by_key}
    children: dict[str, list[str]] = {key: [] for key in by_key}
    for key, node in by_key.items():
        for dep in node.get("depends_on") or []:
            dep_key = str(dep)
            if dep_key in by_key:
                indegree[key] += 1
                children[dep_key].append(key)
    queue = sorted(key for key, degree in indegree.items() if degree == 0)
    order: list[str] = []
    while queue:
        key = queue.pop(0)
        order.append(key)
        for child in children[key]:
            indegree[child] -= 1
            if indegree[child] == 0:
                queue.append(child)
                queue.sort()
    return order


def _version_row(
    session: Session, definition: WorkflowDefinition, version_number: int
) -> WorkflowDefinitionVersion:
    version = session.scalar(
        select(WorkflowDefinitionVersion).where(
            WorkflowDefinitionVersion.definition_id == definition.id,
            WorkflowDefinitionVersion.version == version_number,
        )
    )
    if version is None:
        raise WorkflowRunError(
            "definition_not_published", "定义版本快照缺失，请先发布。", 409
        )
    return version


def _version_dag(session: Session, run: WorkflowRun) -> Any:
    version = session.scalar(
        select(WorkflowDefinitionVersion).where(
            WorkflowDefinitionVersion.definition_id == run.definition_id,
            WorkflowDefinitionVersion.version == run.definition_version,
        )
    )
    if version is None:
        raise WorkflowRunError(
            "definition_version_missing", "运行钉住的定义版本快照缺失。", 422
        )
    return version.dag_json


def _load_version_dag(run_id: str) -> list[dict[str, Any]]:
    with db.session() as session:
        run = session.get(WorkflowRun, run_id)
        if run is None:
            raise WorkflowRunError("run_not_found", "运行不存在。", 404)
        return _dag_nodes(_version_dag(session, run))


def ordered_nodes(session: Session, run: WorkflowRun) -> list[WorkflowNodeRun]:
    """节点行按运行钉住版本的拓扑序排列（详情树稳定可读）。"""
    rows = list(
        session.scalars(
            select(WorkflowNodeRun).where(WorkflowNodeRun.run_id == run.id)
        )
    )
    order = {key: index for index, key in enumerate(_topo_order(_dag_nodes(_version_dag(session, run))))}
    return sorted(rows, key=lambda node: order.get(node.node_key, len(order)))


def _lookup(path: str, context: dict[str, Any], outputs: dict[str, Any]) -> Any:
    root, _, rest = path.partition(".")
    if root in context:
        value: Any = context[root]
    elif root in outputs:
        value = outputs[root]
    else:
        raise _MissingPlaceholder(path)
    for part in (part for part in rest.split(".") if part):
        if isinstance(value, dict) and part in value:
            value = value[part]
        elif isinstance(value, list) and part.isdigit() and int(part) < len(value):
            value = value[int(part)]
        else:
            raise _MissingPlaceholder(path)
    return value


def _resolve_value(
    value: Any, context: dict[str, Any], outputs: dict[str, Any]
) -> Any:
    """深解析：整串单占位符 → 原类型替换（不字符串化）；内嵌占位符 → 字符串插值；
    缺键 → _MissingPlaceholder（节点 failed，绝不填空串——修 fde-v2 缺陷）。"""
    if isinstance(value, str):
        whole = PLACEHOLDER_PATTERN.fullmatch(value.strip())
        if whole:
            return _lookup(whole.group(1), context, outputs)

        def _substitute(match: re.Match[str]) -> str:
            resolved = _lookup(match.group(1), context, outputs)
            if isinstance(resolved, str):
                return resolved
            return json.dumps(resolved, ensure_ascii=False)

        return PLACEHOLDER_PATTERN.sub(_substitute, value)
    if isinstance(value, dict):
        return {k: _resolve_value(v, context, outputs) for k, v in value.items()}
    if isinstance(value, list):
        return [_resolve_value(item, context, outputs) for item in value]
    return value


def _when_truthy(when: Any, context: dict[str, Any], outputs: dict[str, Any]) -> bool:
    """T-W3 最小语义：when 仅支持整串单占位符，取其 JSON 值的 Python 真值；
    缺键/其它形态一律 False（诚实不猜）。表达式引擎待真实需求。"""
    if not isinstance(when, str):
        return False
    whole = PLACEHOLDER_PATTERN.fullmatch(when.strip())
    if whole is None:
        return False
    try:
        return bool(_lookup(whole.group(1), context, outputs))
    except _MissingPlaceholder:
        return False
