"""工作流节点的调度与分派（架构评估 P1-2：从 executor.py 拆出）。

职责边界：**tx A（占位符解析 + 占 running）→ 分派（无事务）**。结算（终态落表）
在 settlement.py，主循环在 executor 门面。分派一律发生在任何打开的事务之外
（2026-10-30 登录事故的教训）。

节点类型四选一：call（execute_api 同闸）/ skill（pinned 版本 AI 调用）/
agent（agents.start_run 同闸）/ human_approval（复用 automation_approvals）。

结算调用点经**门面动态解析**（函数内惰性导入 executor）：结算函数定义在
settlement.py，但调用点必须走 executor 门面的属性——测试 monkeypatch
`executor._settle_node_success` 模拟「tx B 崩溃」时才能真的拦截到
（test_workflow_executor_adversarial 的 tx B 崩溃族钉的就是这条）。
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
from datetime import timedelta
from typing import Any

from sqlalchemy import select

from fde_api.auth.models import User
from fde_api.extensions import db
from fde_api.jobs.outbox import utcnow
from fde_api.workbench.models import Project
from fde_api.workflows.constants import (
    TERMINAL_RUN_STATUSES,
    _APPROVAL_PAYLOAD_LIMIT_BYTES,
    _MissingPlaceholder,
    _NodeFailure,
)
from fde_api.workflows.dag_utils import _resolve_value
from fde_api.workflows.models import WorkflowNodeRun, WorkflowRun

logger = logging.getLogger(__name__)


def _execute_node(
    run_id: str, key: str, specs: dict[str, dict[str, Any]]
) -> bool:
    """tx A（running+attempt+input 幂等键）→ 分派（无事务）→ tx B（终态+产物）。

    human_approval 节点分派 = 建审批行（tx 内），落点 tx 把节点置 waiting 并挂
    审批 id 作幂等键。返回 False 仅当 run 已外部终态（取消），主循环随即退出。
    """
    from fde_api.workflows import executor  # 惰性导入：结算调用点走门面（可 monkeypatch）

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
            executor._settle_node_failure(run_id, key, attempt, specs[key], failure)
        except Exception:  # noqa: BLE001
            logger.exception("workflow node dispatch crashed run_id=%s node=%s", run_id, key)
            executor._settle_node_failure(
                run_id,
                key,
                attempt,
                specs[key],
                _NodeFailure("dispatch_crashed", "节点执行异常，请查看执行器日志。", retryable=True),
            )
        else:
            executor._settle_node_waiting(run_id, key, approval_id)
        return True
    try:
        payload = _dispatch(run_id, key, specs[key], node_id, prepared["input"], attempt)
    except _NodeFailure as failure:
        executor._settle_node_failure(run_id, key, attempt, specs[key], failure)
    except Exception:  # noqa: BLE001 —— 未预期异常按失败落表，不让 job 层重投整个 run
        logger.exception("workflow node dispatch crashed run_id=%s node=%s", run_id, key)
        # agent 分派崩溃不自动重试：start_run 可能已拉起沙箱 run，同图重试有二次执行面
        retryable = node_type != "agent"
        executor._settle_node_failure(
            run_id,
            key,
            attempt,
            specs[key],
            _NodeFailure("dispatch_crashed", "节点执行异常，请查看执行器日志。", retryable=retryable),
        )
    else:
        executor._settle_node_success(run_id, key, payload)
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
    # goal-c CR-020（executor 子代理 F3）：写类节点结果未确认（started 无 finished
    # → uncertain；被 cancelled）不得折叠为 succeeded——FV-F1「断链不静默 done」
    # 红线；结果未知按失败断链，同键去重在 api_actions 层兜底不二次外呼。
    if status in ("uncertain", "cancelled"):
        raise _NodeFailure(
            "action_not_confirmed",
            f"写操作已开始但结果未确认（status={status}，action_id={result.get('action_id')}），"
            "不自动重试；请人工核实目标状态后处置。",
            retryable=False,
        )
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
    from fde_api.control.access import capabilities_for_level, effective_ai_access
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
                SkillDefinition.status == "published",
            )
            .order_by(SkillDefinition.scope.desc(), SkillDefinition.created_at, SkillDefinition.id)
            .limit(1)
        ).first()
        if rows is None:
            raise _NodeFailure(
                "skill_ref_unavailable",
                f"skill 版本不可用：{spec['ref']}（只接受已发布（published）技能，与定义期白名单同口径）。",
                retryable=False,
            )
        _skill, version = rows
        instructions = version.instructions_text
        skill_id = _skill.id
        initiator_id, project_id = run.initiated_by_user_id, run.project_id
        # agent-policy-v1 §T-S1 消费面两闸（与 mcp_gateway._skills 同口径）：
        # 个人技能仅所有者可消费；required_capabilities ⊆ 发起人实时 AI 档位。
        initiator = session.get(User, initiator_id) if initiator_id else None
        if initiator is None or not initiator.is_active:
            raise _NodeFailure(
                "initiator_unavailable", "发起人账号不可用，无法执行节点。", retryable=False
            )
        initiator_id = initiator.id
        if _skill.scope != "public" and _skill.owner_user_id != initiator.id:
            raise _NodeFailure(
                "skill_ref_forbidden",
                f"技能 {spec['ref']} 为个人技能，仅所有者可在工作流中消费。",
                retryable=False,
            )
        allowed = capabilities_for_level(effective_ai_access(initiator)[0])
        missing = sorted(set(version.required_capabilities or []) - set(allowed))
        if missing:
            raise _NodeFailure(
                "ai_access_insufficient",
                f"发起人 AI 档位不足以消费该技能（缺少：{'、'.join(missing)}）。",
                retryable=False,
            )
    prompt = json.dumps(input_snapshot, ensure_ascii=False)
    try:
        answer = execute_ai_prompt(
            user_id=initiator_id,
            prompt=prompt,
            execution_id=f"wfnode-{node_id}",
            project_id=project_id,
            use_tools=False,
            system_prompt=instructions,
            purpose="workflow_skill",
        )
    except DSHRuntimeError as error:
        raise _NodeFailure(error.code, error.public_message, retryable=error.retryable) from error
    except ControlServiceError as error:
        raise _NodeFailure(
            error.code, error.message, retryable=getattr(error, "status", 500) >= 500
        ) from error
    if not isinstance(answer, str):
        answer = json.dumps(answer, ensure_ascii=False)
    parsed_fields: dict[str, Any] = {}
    try:
        decoded = json.loads(answer)
    except (TypeError, ValueError):
        decoded = None
    if isinstance(decoded, dict):
        parsed_fields = {k: v for k, v in decoded.items() if k != "text"}
    # V3 T-S2：pinned 版本完成一次确定性调用即消费——独立微事务计数，
    # 节点失败（AI 异常/重试）不计；attempt 代际各自计一次（每次都真消费了）。
    # CR-013：计数侧故障不升级消费侧——AI 已成功，计数失败只记 warning 不冒泡
    # （否则 _execute_node 兜底 catch 为 dispatch_crashed(retryable=True)：
    # 已成功的 AI 调用被丢弃重跑成双份成本、节点误标 failed；chat 面
    # ai_tool_loop 对工具异常同型有守卫，唯此处曾裸露）。
    from fde_api.control.extensions_service import record_skill_usage
    try:
        record_skill_usage(actor_id=initiator_id, skill_id=skill_id, surface="workflow",
                           version=int(version_part))
    except Exception as error:  # noqa: BLE001 —— 计数失败是噪声不是效果（T-S2 对称语义）
        logger.warning(
            "workflow skill usage count failed node=%s skill=%s error_type=%s",
            node_id, skill_id, type(error).__name__,
        )
    return {**parsed_fields, "text": answer}


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
            if existing is not None and existing.status == "pending":
                return existing.id  # 崩溃恢复：审批已建且仍在等拍板，直接复用
            # goal-c CR-014：键所指的审批已终态（reject/expired/approved/executed）
            # ——resume 是全新分派而非崩溃恢复，不能把节点重新挂到终态审批上
            # （否则 waiting_approval 无人可拍板，run 唯一出口只剩 cancel）。
            # 清掉过期键，落到下方按 workflow_node_run_id 复用 pending / 或新建。
            node.idempotency_key = None
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
    """外副作用判定（T-R2 起消费目录结构化 effect：非 read 即有副作用面）。"""
    from fde_api.control.api_catalog import CATALOG

    return spec.get("type") == "call" and CATALOG[str(spec["ref"])]["effect"] != "read"


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
