"""Workflow 执行器门面（V3 T-W3，设计 workflow-dag-v1 §3/§5）。

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

【架构评估 P1-2 拆分地图（2026-11-08）】本文件从 1562 行收成门面，原实现按职责
拆到五个同包模块，**对外公开名一个不减**（本文件底部 ``__all__`` 即再导出清单）：

===================  ========================================================
子模块                职责
===================  ========================================================
``constants``         异常类与常量（单点真值，依赖图的根）
``dag_utils``         DAG 抽取 / 拓扑序 / 占位符解析 / when 裁决（纯函数）
``serialization``     run·node 读取与投影 + 定义版本行 + 拓扑序节点行
``settlement``        节点与 run 的终态结算（成功/失败/跳过/等待/审批拍板）
``dispatch``          节点调度与分派（tx A → call/skill/agent/human_approval）
``recovery``          worker 侧恢复与终态收敛（崩溃恢复/熔断/丢失收口）
===================  ========================================================

依赖方向单向无环：constants ← dag_utils ← serialization；settlement ← dispatch；
settlement·dag_utils ← recovery；本门面在最上层。跨模块调用有两处**刻意**走
惰性导入——结算面的退避常量与调度面的结算调用点都必须经本门面的属性解析，
否则测试对 ``executor._RETRY_BACKOFF_BASE_SECONDS`` / ``executor._settle_node_success``
的 monkeypatch 会失效（拆分类重构最容易丢的一条语义）。
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from fde_api.auth.models import User
from fde_api.extensions import db
from fde_api.jobs.outbox import enqueue_outbox, utcnow
from fde_api.projects.events import record_event
from fde_api.projects.permissions import project_access
from fde_api.workbench.models import Project
from fde_api.workflows.constants import (
    CANCELLED_AFTER_DISPATCH_MARKER,
    MAX_RUN_HOPS,
    SUPPORTED_NODE_TYPES,
    TERMINAL_NODE_STATUSES,
    TERMINAL_RUN_STATUSES,
    WORKFLOW_JOB_TYPE,
    WorkflowRunError,
    _APPROVAL_PAYLOAD_LIMIT_BYTES,
    _MissingPlaceholder,
    _NodeFailure,
    _RETRY_BACKOFF_BASE_SECONDS,
    _RETRY_BACKOFF_CAP_SECONDS,
)
from fde_api.workflows.dag_utils import (
    _dag_nodes,
    _lookup,
    _resolve_value,
    _topo_order,
    _when_truthy,
)
from fde_api.workflows.definition_service import serialize_definition
from fde_api.workflows.dispatch import (
    _begin_node,
    _call_action_identifier,
    _dispatch,
    _dispatch_agent,
    _dispatch_call,
    _dispatch_human_approval,
    _dispatch_skill,
    _execute_node,
    _is_external_call,
    _split_call_params,
)
from fde_api.workflows.models import (
    WorkflowDefinition,
    WorkflowNodeRun,
    WorkflowRun,
)
from fde_api.workflows.recovery import (
    _fail_run_if_hops_exceeded,
    _fail_run_on_worker_loss,
    _finalize_pass,
    _recover_interrupted,
)
from fde_api.workflows.serialization import (
    _iso,
    _load_version_dag,
    _serialize_node,
    _version_dag,
    _version_row,
    ordered_nodes,
    serialize_run,
    serialize_run_summary,
)
from fde_api.workflows.settlement import (
    _attach_gate_evidence_marker,
    _record_cancelled_after_dispatch,
    _settle_node_failure,
    _settle_node_success,
    _settle_node_waiting,
    _settle_run,
    _skip_node,
    settle_approval_node,
)

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from fde_api.jobs.models import BackgroundJob


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


# run 列表有界扫描（V3 T-W6 桌面控制台补面）：默认 50、上限 200，超出如实 truncated
RUN_LIST_LIMIT_DEFAULT = 50
RUN_LIST_LIMIT_MAX = 200


def list_project_runs(
    *, actor: User, project_id: str, limit: int = RUN_LIST_LIMIT_DEFAULT
) -> dict[str, Any]:
    """项目内 run 列表（can_view，新者在前，有界扫描）——V3 T-W6 桌面控制台最小补面。

    truncated=True 表示已扫到 limit 上限、可能还有更早的 run（诚实标记不静默截断）；
    列表行不带 nodes（N+1 不可取），节点树走 get_run_detail 按需展开。
    """
    with db.session() as session:
        project = load_project(session, actor, project_id, manage=False)
        rows = list(
            session.scalars(
                select(WorkflowRun)
                .where(WorkflowRun.project_id == project.id)
                .order_by(WorkflowRun.created_at.desc(), WorkflowRun.id.desc())
                .limit(limit)
            )
        )
        return {
            "items": [serialize_run_summary(row) for row in rows],
            "truncated": len(rows) >= limit,
        }


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
    """恢复失败运行（can_manage）：failed/skipped 节点放回 pending（attempt
    归零——agent 节点除外，保留 attempt 使分派开新一代际，幂等键
    `wfnode-{行id}:{attempt}` 不复用失败终态；agents V8 对失败终态拒同键
    重跑，归零会让 agent 节点每次 resume 都撞确定性 409），计数按每轮恢复
    重置；已完成节点原样复用；重新投递 workflow.run。"""
    with db.session() as session, session.begin():
        run, _project = _load_run(session, actor, project_id, run_id, manage=True)
        if run.status != "failed":
            raise WorkflowRunError(
                "not_resumable",
                "只有失败的运行可以恢复（成功/取消为终态；等待审批的运行请先拍板或取消）。",
                409,
            )
        # B#1 跳数熔断：拍板重投是「重投代际」边——继承不清零，超限拒绝再投
        # （人工排查触发链后应另起新运行，而不是无限恢复同一条链）。
        if run.hops >= MAX_RUN_HOPS:
            raise WorkflowRunError(
                "hops_exceeded",
                f"重投代际已达上限（{MAX_RUN_HOPS}），熔断。请人工排查触发链后另起新运行。",
                409,
            )
        run.hops += 1
        nodes = ordered_nodes(session, run)
        reset = 0
        for node in nodes:
            if node.status in ("failed", "skipped"):
                node.status = "pending"
                # goal-c CR-019（executor 子代理 F2）：agent 节点保留 attempt——
                # 幂等键 = wfnode-{行id}:{attempt}，agents V8 对失败终态拒同键重跑。
                # 归零 attempt 会让每次 resume 都撞回 `:1` 的 failed 终态 → 确定性
                # 409，agent 节点永远救不活；保留 attempt 使 _begin_node +1 开新
                # 代际（兑现 docstring「resume_run / retryable 崩溃恢复各开新代际」）。
                # 其余节点（call/skill/human）attempt 仅用于退避计数与「每轮恢复
                # 重置」语义，照旧归零。
                if node.node_type != "agent":
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
# jobs 接线：handler 注册 + failure hook + 执行主循环
# ---------------------------------------------------------------------------


def register_workflow_handler() -> None:
    from fde_api.jobs.handlers import register_handler, register_job_failure_handler

    register_handler(WORKFLOW_JOB_TYPE, _run_workflow_job)
    register_job_failure_handler(WORKFLOW_JOB_TYPE, _fail_run_on_worker_loss)


def _run_workflow_job(job: BackgroundJob) -> None:
    run_workflow_run(job.target_id)


def run_workflow_run(run_id: str) -> None:
    """执行主循环（jobs handler 主体）：幂等（终态直接返回）。

    每轮：取下一个 ready 节点（依赖全 succeeded，或 when 真值裁决放行）→ 独立事务
    执行；无 ready 且全部终态 → run 终态；无 ready 但有断链 → 按规则跳过并继续；
    剩余节点全在等审批 → run = waiting_approval，handler 正常返回（拍板重投续跑）；
    无任何进展且无人等待 → run failed（调度死锁防御）。迭代上限 = 全图最大尝试数 + 余量。
    """
    _recover_interrupted(run_id)
    # B#1 跳数熔断（belt）：入口复核重投代际链长——超限 honest failed，不再
    # 分派任何节点（resume_run 已在重投口拒绝，此处兜在途/遗留态）。
    _fail_run_if_hops_exceeded(run_id)
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
# 再导出清单（架构评估 P1-2 拆分：对外公开名一个不减）
#
# 拆分前这些名字都住在 executor.py，调用方（routes / control.service /
# jobs.handlers / 既有测试）一律从 `fde_api.workflows.executor` 取。拆分后
# 名字的真身搬进了子模块，本门面原样再导出——**改这里的清单等于改公开 API**，
# 新增名字必须同时更新本清单与 `__all__`。
# ---------------------------------------------------------------------------

__all__ = [
    # 常量与异常
    "WORKFLOW_JOB_TYPE",
    "TERMINAL_RUN_STATUSES",
    "TERMINAL_NODE_STATUSES",
    "MAX_RUN_HOPS",
    "SUPPORTED_NODE_TYPES",
    "CANCELLED_AFTER_DISPATCH_MARKER",
    "_APPROVAL_PAYLOAD_LIMIT_BYTES",
    "_RETRY_BACKOFF_BASE_SECONDS",
    "_RETRY_BACKOFF_CAP_SECONDS",
    "WorkflowRunError",
    "_NodeFailure",
    "_MissingPlaceholder",
    # 生命周期（本门面自有）
    "load_project",
    "load_definition",
    "_normalize_idempotency_key",
    "_load_run",
    "start_run",
    "get_run_detail",
    "RUN_LIST_LIMIT_DEFAULT",
    "RUN_LIST_LIMIT_MAX",
    "list_project_runs",
    "cancel_run",
    "resume_run",
    "list_platform_definitions",
    "register_workflow_handler",
    "_run_workflow_job",
    "run_workflow_run",
    "_deps_green",
    # 读取与呈现（serialization）
    "_iso",
    "serialize_run",
    "_serialize_node",
    "serialize_run_summary",
    "_version_row",
    "_version_dag",
    "_load_version_dag",
    "ordered_nodes",
    # dag 纯函数（dag_utils）
    "_dag_nodes",
    "_topo_order",
    "_lookup",
    "_resolve_value",
    "_when_truthy",
    # 结算（settlement）
    "_attach_gate_evidence_marker",
    "_record_cancelled_after_dispatch",
    "_settle_node_success",
    "_settle_node_failure",
    "_settle_node_waiting",
    "_skip_node",
    "_settle_run",
    "settle_approval_node",
    # 调度与分派（dispatch）
    "_execute_node",
    "_begin_node",
    "_dispatch",
    "_dispatch_call",
    "_dispatch_skill",
    "_dispatch_agent",
    "_dispatch_human_approval",
    "_split_call_params",
    "_is_external_call",
    "_call_action_identifier",
    # 恢复（recovery）
    "_recover_interrupted",
    "_finalize_pass",
    "_fail_run_if_hops_exceeded",
    "_fail_run_on_worker_loss",
]
