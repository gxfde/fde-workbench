"""AE2-WP3 编排执行器（54 号 v0.2-ACTIVE §3；编排契约 ``_ae2-execution-contract-v1.json`` v1.0.0）。

D1–D3 落地：自造最小 DAG——拓扑求值**零依赖自实现**（Kahn＋字典序稳定就绪
队列，语义对齐 ``workflows.dag_utils`` 口径；该域属 AF1 禁改区，只读对齐、
零导入、零改动）；节点＝**一次 AE1 单步执行**（``submit_action`` 五层门原样
复用，``rollback_supported`` 按节点定义显式置位——缺省 false 陷阱点，54 号
§6.5 已登记）；fail-fast ＋ **逆序补偿**（``rollback_action`` 复用，逆拓扑序
后继先补偿）＋补偿残留诚实登记。

提交期静态校验序（契约 x-validation-order，上层未过即短路）：
``S1 图结构 → S2 节点动作 → S3 租户绑定(404) → S4 能力档位(403) → S5 运行级
幂等(409)``；运行期逐节点走 U1 五层门（L1 结构 → L2 幂等 → L3 白名单 →
L4 审批 → L5 兜底 → 执行 → 审计），编排层不绕过、不内嵌 HTTP、不新增注册面。

状态机读法（契约 x-status-machine）：``queued → running → succeeded``；
失败时 ``failed → compensating →（rolled_back | compensation_failed）``。
``failed`` 仅在**零可补偿节点**（无已成功上游）时为终态——运行级 error 非
null（诚实失败，B1）；有可补偿节点则补偿过程必走 ``compensating``，收口
``rolled_back``（error=null，残留按节点登记）或 ``compensation_failed``。
节点 ``waiting`` 态在本阶段同步执行路径不进入（U1 审批以 approval_id 前置
提供；AE2 无异步审批挂起面）。

零明文：运行行只留 ``definition_sha256``，节点行只留声明面 ``params_sha256``
（解析后实材指纹在 AE1 执行行）；上游产物（output）不落编排表——留在 AE1
执行行，响应/复放按行重建（契约 x-audit-and-cost / S-AE-09 C10）。

派发失败的诚实留痕：节点行 ``action_execution_id`` 恒 null、``error_json``
登记映射后错误；AE1 侧在途锁行（若已落）以节点幂等键可溯（派发段失败的
锁行翻 failed 终态），编排表不复制其明文。
"""
from __future__ import annotations

import json
import re
from hashlib import sha256
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from fde_api.action_execution import service as ae_service
from fde_api.action_execution.errors import ActionExecutionError
from fde_api.action_execution.executor import params_sha256
from fde_api.action_execution.models import ActionExecution, ActionTaskNode, ActionTaskRun
from fde_api.action_execution.schemas import build_error, _unknown_fields_message
from fde_api.auth.models import User
from fde_api.control.access import (
    ACCESS_RANK,
    CAPABILITY_REQUIREMENTS,
    SENSITIVE_ARGUMENT_KEY,
    effective_ai_access,
)
from fde_api.errors import NOT_FOUND_MESSAGE
from fde_api.workbench.models import new_uuid
from fde_api.action_execution.service import AE_CAPABILITY, _ae_session

__all__ = [
    "compensate_task",
    "node_idempotency_key",
    "submit_task",
    "task_definition_digest",
]

# ---- 形状常量（契约 $defs 逐字对齐；漂移即钉红） -------------------------------
_NODE_KEY_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$")
_ACTION_ID_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_.:-]*$")
_ACTION_TYPE_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")
_METHOD_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_.-]*$")
_REF_PATH_PATTERN = re.compile(r"^output(\.[A-Za-z0-9_-]+|\[[0-9]+\])*$")

_TASK_REQUIRED = ("org_id", "requester_id", "idempotency_key", "definition")
_TASK_ALLOWED = frozenset(_TASK_REQUIRED) | {"reason"}
_NODEDEF_REQUIRED = ("node_key", "depends_on", "action", "rollback_supported")
_NODEDEF_ALLOWED = frozenset(_NODEDEF_REQUIRED)
_ACTION_REQUIRED = ("action_id", "connector_id", "method", "params", "dry_run", "risk_level", "timeout_seconds")
_ACTION_ALLOWED = frozenset(_ACTION_REQUIRED) | {"action_type", "approval_id"}  # U1 子集投影

_MAX_NODES = 32
_MAX_DEPENDS = 32
_RUN_TERMINAL = frozenset({"succeeded", "failed", "rolled_back", "compensation_failed"})


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def node_idempotency_key(run_key: str, node_key: str, action: dict[str, Any]) -> str:
    """节点级幂等键（契约 x-idempotency.node_key_derivation 逐字）：
    ``ae2- + sha256(run_key|node_key|canonical(action))`` 前 32 位十六进制。"""
    digest = sha256(f"{run_key}|{node_key}|{_canonical(action)}".encode("utf-8")).hexdigest()
    return f"ae2-{digest[:32]}"


def task_definition_digest(definition: dict[str, Any]) -> str:
    """图定义指纹（canonical JSON → sha256 hex，64 位小写；S5 同体裁决锚）。"""
    return sha256(_canonical(definition).encode("utf-8")).hexdigest()


# ---- 提交入口 ------------------------------------------------------------------


def submit_task(
    *,
    actor: User,
    payload: Any,
    whitelist_gate: Any,
    dispatch: Any,
    compensator: Any = None,
) -> dict[str, Any]:
    """提交多步任务（S1–S5 静态裁决 → 整图在途锁 → fail-fast 执行 → 逆序补偿）。

    返回契约 ``TaskRunResult`` 形态 dict；S 层拒绝以 ``ActionExecutionError``
    冒泡（WP4 路由转 ``{data,error}`` 信封）。运行期节点失败**不冒泡**——以
    运行终态（rolled_back/compensation_failed/failed）诚实收口。
    """
    if not isinstance(payload, dict):
        raise ActionExecutionError("validation_failed", "请求体须为 JSON 对象。")
    definition = _validate_envelope(payload)  # S1 前置：信封闭集
    graph = _validate_definition(definition, whitelist_gate)  # S1 图结构＋S2 节点动作
    _check_tenant(actor, payload)  # S3 租户绑定（404 不泄露）
    _check_capability(actor)  # S4 能力档位（403）
    order = _topo_order(graph)  # Kahn＋字典序稳定（环已静态拒，此处必全序）
    digest = task_definition_digest(definition)
    claimed_id, replay_id = _claim_run(payload, digest, node_count=len(graph))  # S5 幂等裁决
    if claimed_id is None and replay_id is not None:
        return _run_result(replay_id)  # B7：同键同体复放——快照重建，零新副作用
    assert claimed_id is not None
    return _execute_run(
        run_id=claimed_id,
        actor=actor,
        payload=payload,
        graph=graph,
        order=order,
        whitelist_gate=whitelist_gate,
        dispatch=dispatch,
        compensator=compensator,
    )


# ---- S1/S2 提交期静态校验 ------------------------------------------------------


def _validate_envelope(payload: dict[str, Any]) -> dict[str, Any]:
    """TaskRequest 信封闭集（contract additionalProperties=false）。"""
    unknown = sorted(set(payload) - _TASK_ALLOWED)
    if unknown:
        raise ActionExecutionError("validation_failed", _unknown_fields_message(unknown))
    for field in _TASK_REQUIRED:
        if field not in payload:
            raise ActionExecutionError("validation_failed", f"缺少必填字段：{field}。")
    for field in ("org_id", "requester_id"):
        value = payload[field]
        if not isinstance(value, str) or not (1 <= len(value) <= 64):
            raise ActionExecutionError("validation_failed", f"{field} 须为 1..64 字符。")
    key = payload["idempotency_key"]
    if not isinstance(key, str) or not (1 <= len(key) <= 160):
        raise ActionExecutionError("validation_failed", "idempotency_key 须为 1..160 字符。")
    reason = payload.get("reason")
    if reason is not None and (not isinstance(reason, str) or not (1 <= len(reason) <= 500)):
        raise ActionExecutionError("validation_failed", "reason 须为 1..500 字符或 null。")
    definition = payload["definition"]
    if not isinstance(definition, dict) or set(definition) != {"nodes"}:
        raise ActionExecutionError("validation_failed", "definition 须为恰好含 nodes 的对象。")
    return definition


def _validate_definition(definition: dict[str, Any], whitelist_gate: Any) -> list[dict[str, Any]]:
    """S1 图结构层＋S2 节点动作层。全部拒绝发生在任何落库/外呼之前（零副作用）。"""
    nodes = definition.get("nodes")
    if not isinstance(nodes, list) or not nodes:
        raise ActionExecutionError("validation_failed", "definition.nodes 须为非空数组。")
    if len(nodes) > _MAX_NODES:
        raise ActionExecutionError("validation_failed", f"节点数超上限（≤{_MAX_NODES}）。")
    # S1：结构形状（node_key 合域唯一／depends_on 域／rollback_supported 布尔）
    graph: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in nodes:
        if not isinstance(raw, dict):
            raise ActionExecutionError("validation_failed", "节点须为对象。")
        unknown = sorted(set(raw) - _NODEDEF_ALLOWED)
        if unknown:
            raise ActionExecutionError("validation_failed", f"节点包含未登记字段：{'、'.join(unknown)}。")
        missing = [field for field in _NODEDEF_REQUIRED if field not in raw]
        if missing:
            raise ActionExecutionError("validation_failed", f"节点缺少必填字段：{'、'.join(missing)}。")
        node_key = raw["node_key"]
        if not isinstance(node_key, str) or not _NODE_KEY_PATTERN.match(node_key) or len(node_key) > 60:
            raise ActionExecutionError("validation_failed", "node_key 非法（1..60，字母或数字开头）。")
        if node_key in seen:
            raise ActionExecutionError("validation_failed", f"node_key 重复：{node_key}。")
        seen.add(node_key)
        depends = raw["depends_on"]
        if not isinstance(depends, list) or len(depends) > _MAX_DEPENDS:
            raise ActionExecutionError("validation_failed", f"depends_on 须为数组（≤{_MAX_DEPENDS}）。")
        for dep in depends:
            if not isinstance(dep, str) or not (1 <= len(dep) <= 60):
                raise ActionExecutionError("validation_failed", "depends_on 项须为 1..60 字符。")
        if type(raw["rollback_supported"]) is not bool:
            raise ActionExecutionError("validation_failed", "rollback_supported 须为布尔。")
        if not isinstance(raw["action"], dict):
            raise ActionExecutionError("validation_failed", "action 须为对象。")
        graph.append(
            {
                "node_key": node_key,
                "depends_on": list(depends),  # 快照逐字（声明面）
                "action": raw["action"],
                "rollback_supported": raw["rollback_supported"],
            }
        )
    by_key = {node["node_key"]: node for node in graph}
    for node in graph:
        for dep in node["depends_on"]:
            if dep not in by_key:
                raise ActionExecutionError("validation_failed", f"depends_on 引用不存在的节点：{dep}。")
    _topo_order(graph)  # A1：Kahn 剩余非空即环（提交期静态拒，不靠运行期兜底）
    # S2：节点动作层（形状／ParamValue／敏感键／白名单预检／ref 上游）
    for node in graph:
        node["action"] = _validate_action(node["action"], node["node_key"], whitelist_gate)
        _validate_refs(node, by_key)
    return graph


def _validate_action(raw: dict[str, Any], node_key: str, whitelist_gate: Any) -> dict[str, Any]:
    """NodeAction＝U1 ``ActionExecutionRequest`` 子集投影（字段/类型/枚举逐字）。"""
    unknown = sorted(set(raw) - _ACTION_ALLOWED)
    if unknown:
        raise ActionExecutionError("validation_failed", _unknown_fields_message(unknown))  # A7＋不回显敏感键名
    missing = [field for field in _ACTION_REQUIRED if field not in raw]
    if missing:
        raise ActionExecutionError("validation_failed", f"节点动作缺少必填字段：{'、'.join(missing)}。")
    action_id = raw["action_id"]
    if not isinstance(action_id, str) or not _ACTION_ID_PATTERN.match(action_id) or len(action_id) > 128:
        raise ActionExecutionError("validation_failed", "action_id 非法（1..128，字母开头）。")
    action_type = raw.get("action_type")
    if action_type is not None and (
        not isinstance(action_type, str) or not _ACTION_TYPE_PATTERN.match(action_type) or len(action_type) > 64
    ):
        raise ActionExecutionError("validation_failed", "action_type 非法（1..64，小写蛇形）。")
    connector_id = raw["connector_id"]
    if not isinstance(connector_id, str) or not _ACTION_ID_PATTERN.match(connector_id) or len(connector_id) > 128:
        raise ActionExecutionError("validation_failed", "connector_id 非法（1..128，字母开头）。")
    method = raw["method"]
    if not isinstance(method, str) or not _METHOD_PATTERN.match(method) or len(method) > 64:
        raise ActionExecutionError("validation_failed", "method 非法（1..64）。")
    params = raw["params"]
    if not isinstance(params, dict):
        raise ActionExecutionError("validation_failed", "params 须为对象。")
    for name, value in params.items():
        _validate_param_value(value, str(name))
    if any(SENSITIVE_ARGUMENT_KEY.search(str(name)) for name in params):
        # C8（七键同源扫描，与 U1 L1 同一真身）：凭据不得进动作材料。
        raise ActionExecutionError("sensitive_argument_forbidden", "参数命中敏感键名（凭据不得进动作材料）。")
    if type(raw["dry_run"]) is not bool:
        raise ActionExecutionError("validation_failed", "dry_run 须为布尔。")
    risk_level = raw["risk_level"]
    if type(risk_level) is not int or not (0 <= risk_level <= 4):
        raise ActionExecutionError("validation_failed", "risk_level 须为 0..4 整数。")
    timeout_seconds = raw["timeout_seconds"]
    if type(timeout_seconds) is not int or not (1 <= timeout_seconds <= 300):
        raise ActionExecutionError("validation_failed", "timeout_seconds 须为 1..300 整数。")
    approval_id = raw.get("approval_id")
    if approval_id is not None and (not isinstance(approval_id, str) or len(approval_id) > 128):
        raise ActionExecutionError("validation_failed", "approval_id 非法（≤128 字符或 null）。")
    # A5/A6：白名单三元组**提交期预检**（未登记即 422 静态拒，不派发到运行期 403）。
    # 映射读法（Q8）：门拒绝（运行期 tool_not_allowed）在提交期静态层转
    # validation_failed ＋ details 标注；运行期 L3 门仍在（防御纵深不撤）。
    try:
        whitelist_gate.check(connector_id, method)
    except ActionExecutionError:
        raise ActionExecutionError(
            "validation_failed",
            "节点动作未通过白名单预检（提交期静态拒）。",
            details={"node_key": node_key, "connector_id": connector_id},
        ) from None
    except Exception as exc:  # 门自身异常亦 fail-closed（不吞不放过）
        raise ActionExecutionError(
            "validation_failed",
            "节点动作未通过白名单预检（提交期静态拒）。",
            details={"node_key": node_key, "connector_id": connector_id, "reason": type(exc).__name__},
        ) from None
    return dict(raw)  # 声明面逐字保留（幂等键派生与 payload 构造共用）


def _validate_param_value(value: Any, name: str) -> None:
    """ParamValue（契约 oneOf literal|ref；A8：kind 闭集外即拒）。"""
    if not isinstance(value, dict):
        raise ActionExecutionError("validation_failed", f"params.{name} 取值须为 literal|ref 对象。")
    kind = value.get("kind")
    if kind == "literal":
        if set(value) != {"kind", "value"}:
            raise ActionExecutionError("validation_failed", f"params.{name} literal 只允许 kind/value。")
        return
    if kind == "ref":
        if set(value) != {"kind", "node", "path"}:
            raise ActionExecutionError("validation_failed", f"params.{name} ref 只允许 kind/node/path。")
        node = value["node"]
        if not isinstance(node, str) or not _NODE_KEY_PATTERN.match(node) or len(node) > 60:
            raise ActionExecutionError("validation_failed", f"params.{name} ref.node 非法。")
        path = value["path"]
        # A10：path 仅允许 output 作用域（越权读审计/错误/参数面在提交期拦）。
        if not isinstance(path, str) or not (7 <= len(path) <= 255) or not _REF_PATH_PATTERN.match(path):
            raise ActionExecutionError("validation_failed", f"params.{name} ref.path 越出 output 作用域。")
        return
    raise ActionExecutionError("validation_failed", f"params.{name} kind 非法（仅 literal|ref）。")


def _validate_refs(node: dict[str, Any], by_key: dict[str, dict[str, Any]]) -> None:
    """A9：ref.node 必须是**已声明的直接上游**（数据边＝依赖边，显式声明制）。"""
    upstream = set(node["depends_on"])
    for name, value in node["action"]["params"].items():
        if isinstance(value, dict) and value.get("kind") == "ref" and value["node"] not in upstream:
            raise ActionExecutionError(
                "validation_failed",
                f"params.{name} 引用非直接上游节点（须在 depends_on 声明）。",
                details={"node_key": node["node_key"], "ref_node": str(value["node"])},
            )


def _topo_order(graph: list[dict[str, Any]]) -> list[str]:
    """确定性拓扑序（Kahn＋字典序稳定；语义对齐 ``workflows.dag_utils._topo_order``，
    零导入零改动）。同层节点按 node_key 字典序出队＝同图同输入同派发序。"""
    by_key = {node["node_key"]: node for node in graph}
    indegree = {key: 0 for key in by_key}
    children: dict[str, list[str]] = {key: [] for key in by_key}
    for key, node in by_key.items():
        for dep in node["depends_on"]:
            if dep in by_key:
                indegree[key] += 1
                children[dep].append(key)
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
    if len(order) != len(by_key):
        cycle = sorted(set(by_key) - set(order))
        raise ActionExecutionError("validation_failed", "定义含环（提交期静态拒）。", details={"cycle_nodes": cycle})
    return order


# ---- S3/S4 租户绑定与能力档位 --------------------------------------------------


def _check_tenant(actor: User, payload: dict[str, Any]) -> None:
    """S3：服务端强制 org 绑定（不盲信调用方；不一致 404 不泄露——U1 同口径）。"""
    if payload["org_id"] != actor.org_id:
        raise ActionExecutionError("not_found", NOT_FOUND_MESSAGE)


def _check_capability(actor: User) -> None:
    """S4：与 AE1 提交面同源判定（``effective_ai_access`` ＋注册档位）。"""
    level, _source = effective_ai_access(actor)
    required = CAPABILITY_REQUIREMENTS.get(AE_CAPABILITY)
    if required is None or ACCESS_RANK.get(level, -1) < ACCESS_RANK.get(required, 0):
        raise ActionExecutionError("permission_revoked", "任务发起人不具备该操作权限。")


# ---- S5 运行级幂等（在途锁＝运行行真身） ----------------------------------------


def _claim_run(payload: dict[str, Any], digest: str, *, node_count: int) -> tuple[str | None, str | None]:
    """落 ``queued`` 运行行占用 ``UNIQUE(org_id, idempotency_key)``（在途锁）。

    ``IntegrityError`` → 重读既有行裁决：异体 409 ``mismatch``／同键在途 409
    ``in_flight``／同键终态 → 复放通道（返回 replay_id，零新副作用）。
    返回 ``(claimed_id, replay_id)``——恰一个非 None。
    """
    key = payload["idempotency_key"]
    org = payload["org_id"]
    try:
        with _ae_session() as session:
            row = ActionTaskRun(
                id=new_uuid(),
                idempotency_key=key,
                org_id=org,
                requester_id=payload["requester_id"],
                definition_sha256=digest,
                node_count=node_count,
                status="queued",  # 在途锁位（尚未执行；终态翻转后锁自然释放为复放通道）
                error_code="",
                error_json=None,
                audit_json={},
                cost_json={},
                rollback_json={},
            )
            session.add(row)
            session.commit()
            return row.id, None
    except IntegrityError:
        pass  # 并发败者或复放——查既有行裁决（autobegin 异常须先废弃本事务）
    with _ae_session() as session:
        existing = session.scalar(
            select(ActionTaskRun).where(ActionTaskRun.idempotency_key == key, ActionTaskRun.org_id == org)
        )
    if existing is None:
        # 撞约束却查无行（极端竞态）——诚实 in-flight 口径退避，不自行重试
        raise ActionExecutionError("idempotency_in_flight", "同键任务在途，请退避后重试。")
    if existing.definition_sha256 != digest:
        raise ActionExecutionError("idempotency_mismatch", "同键任务定义不一致（幂等指纹不符）。")
    if existing.status not in _RUN_TERMINAL:
        raise ActionExecutionError("idempotency_in_flight", "同键任务在途，请退避后重试。")
    return None, existing.id


# ---- 运行期执行（fail-fast ＋ 逆序补偿） ----------------------------------------


def _execute_run(
    *,
    run_id: str,
    actor: User,
    payload: dict[str, Any],
    graph: list[dict[str, Any]],
    order: list[str],
    whitelist_gate: Any,
    dispatch: Any,
    compensator: Any,
) -> dict[str, Any]:
    """主循环：整图节点行预落 → 拓扑序逐节点 ``submit_action`` → 失败即停 →
    未派发节点 skipped → 逆拓扑序补偿 → 运行终态诚实收口。"""
    by_key = {node["node_key"]: node for node in graph}
    org = payload["org_id"]
    requester = payload["requester_id"]
    run_key = payload["idempotency_key"]
    _create_node_rows(run_id, graph, run_key)
    _set_run_status(run_id, "running")
    outputs: dict[str, Any] = {}
    node_ids: dict[str, str] = {}  # 已成功节点 → AE1 execution_id（补偿入参）
    cost = {"tool_calls": 0, "duration_ms": 0, "estimated_usd": 0.0}
    attempted: list[str] = []
    failure: dict[str, Any] | None = None
    for key in order:
        attempted.append(key)
        node = by_key[key]
        _set_node_status(run_id, key, "running", attempt=1)
        action = node["action"]
        try:
            params = _resolve_params(action["params"], outputs)
        except _MissingRef as exc:
            failure = {
                "node_key": key,
                "error": build_error(
                    "validation_failed",
                    "上游产物引用缺键（不猜、不填空）。",
                    retryable=False,
                    details={"ref_node": exc.node, "path": exc.path},
                ),
            }
            break
        node_payload = {
            **action,
            "params": params,  # 声明面 → 解析后实材（U1 L1 敏感键扫描在实材上复跑）
            "org_id": org,
            "requester_id": requester,
            "idempotency_key": node_idempotency_key(run_key, key, action),
        }
        try:
            result = ae_service.submit_action(
                actor=actor,
                payload=node_payload,
                whitelist_gate=whitelist_gate,
                dispatch=dispatch,
                rollback_supported=node["rollback_supported"],  # 显式置位（缺省 false 陷阱）
            )
        except ActionExecutionError as exc:
            failure = {"node_key": key, "error": build_error(exc.code, exc.message, retryable=False, details=exc.details)}
            break
        except Exception as exc:  # service 兜底之外再漏出的裸异常（防御；Q8 映射）
            failure = {
                "node_key": key,
                "error": build_error(
                    "tool_not_allowed", "执行段内部失败。", retryable=False, details={"reason": type(exc).__name__}
                ),
            }
            break
        node_ids[key] = str(result["execution_id"])
        outputs[key] = result.get("output") or {}
        node_cost = result.get("cost") or {}
        cost["tool_calls"] += int(node_cost.get("tool_calls") or 0)
        cost["duration_ms"] += int(node_cost.get("duration_ms") or 0)
        cost["estimated_usd"] += float(node_cost.get("estimated_usd") or 0.0)
        _mark_node_succeeded(run_id, key, node_ids[key])
    audit = {"node_order": list(order), "orchestration": "fail_fast"}
    if failure is None:
        _finalize_run(run_id, status="succeeded", error=None, rollback={}, audit=audit, cost=cost)
        return _run_result(run_id)
    # fail-fast：失败节点标 failed（诚实失败态），未派发节点 → skipped
    # （error=null；原因登记在运行级 error.details——不伪造节点级错误）
    node_error = failure["error"]
    _set_node_failed(run_id, failure["node_key"], node_error)
    remaining = [key for key in order if key not in attempted]
    _mark_nodes_skipped(run_id, remaining)
    run_error = {
        **node_error,
        "details": {**(node_error.get("details") or {}), "node_key": failure["node_key"], "skipped_nodes": remaining},
    }
    _set_run_status(run_id, "failed", error_code=str(run_error["code"]), error_json=run_error)

    if not node_ids:
        # 零可补偿节点：failed 即终态（B1——运行 error 非 null，诚实失败）
        _finalize_run(run_id, status="failed", error=run_error, rollback={}, audit=audit, cost=cost)
        return _run_result(run_id)
    _set_run_status(run_id, "compensating")
    compensable = [key for key in reversed(order) if key in node_ids]  # 逆拓扑序（后继先补偿）
    summary = _compensate_pass(run_id=run_id, actor=actor, compensable=compensable, node_ids=node_ids,
                               compensator=compensator)
    if summary["residual"]:
        error = build_error(
            "compensation_failed",
            "部分节点补偿失败（残留已逐条登记）。",
            retryable=False,
            details={"compensation_ids": summary["compensation_ids"], "residual_nodes": summary["residual"]},
        )
        rollback = {
            "status": "failed",
            "compensated_nodes": summary["compensated"],
            "residual": summary["residual"],
        }
        _finalize_run(run_id, status="compensation_failed", error=error, rollback=rollback, audit=audit, cost=cost)
    else:
        rollback = {"status": "rolled_back", "compensated_nodes": summary["compensated"], "residual": []}
        _finalize_run(run_id, status="rolled_back", error=None, rollback=rollback, audit=audit, cost=cost)
    return _run_result(run_id)


def _compensate_pass(
    *, run_id: str, actor: User, compensable: list[str], node_ids: dict[str, str], compensator: Any
) -> dict[str, Any]:
    """逆序补偿：逐节点调用 U1 ``rollback_action``（四态逐字同义转写登记）。

    单节点补偿面自身拒绝（审批防御/失权等 ``ActionExecutionError``）＝该节点
    补偿 failed（诚实），补偿过程对其余节点照常推进。"""
    if compensator is None:
        compensator = ae_service.NO_COMPENSATOR
    compensated: list[str] = []
    residual: list[str] = []
    compensation_ids: list[str] = []
    for key in compensable:
        try:
            batch = ae_service.rollback_action(actor=actor, execution_id=node_ids[key], compensator=compensator)
            comp_status = str(batch["status"])  # rolled_back|noop|not_supported|failed
            failed_ids = [
                str(c.get("compensation_id")) for c in (batch.get("compensations") or []) if c.get("status") == "failed"
            ]
        except ActionExecutionError:
            comp_status = "failed"
            failed_ids = [f"node:{key}"]
        _set_node_compensation(run_id, key, comp_status)
        if comp_status == "rolled_back":
            compensated.append(key)
        elif comp_status == "failed":
            residual.append(key)
            compensation_ids.extend(failed_ids)
        # noop / not_supported：诚实失败态非补偿失败——不计残留（B5/B6）
    return {"compensated": compensated, "residual": residual, "compensation_ids": compensation_ids}


# ---- 回滚触发（B11 幂等；WP4 路由的服务面） ------------------------------------


def compensate_task(
    *,
    actor: User,
    execution_id: str,
    compensator: Any = None,
    reason: str | None = None,
) -> dict[str, Any]:
    """对既有运行触发补偿。幂等：终态运行直接快照重建（零新补偿副作用）；
    ``failed`` 运行补跑未登记补偿的节点（inline 流已全登记 → 恒零新增）；
    在途 409；succeeded 422（状态机不含 succeeded→compensating 边）。
    ``reason`` 透传 U1 批次登记面。"""
    _check_capability(actor)
    with _ae_session() as session:
        run = session.scalar(select(ActionTaskRun).where(ActionTaskRun.id == execution_id))
        if run is None or run.org_id != actor.org_id:
            raise ActionExecutionError("not_found", NOT_FOUND_MESSAGE)
        status = run.status
    if status == "succeeded":
        raise ActionExecutionError("validation_failed", "运行已成功：补偿只对失败运行开放（状态机 failed→compensating）。")
    if status in ("queued", "running", "compensating"):
        raise ActionExecutionError("idempotency_in_flight", "同键任务在途，请退避后重试。")
    if status == "failed":
        rows = _node_rows(execution_id)
        order = _topo_from_rows(rows)
        by_key = {row.node_key: row for row in rows}
        compensable = [
            key
            for key in reversed(order)
            if by_key[key].status == "succeeded"
            and by_key[key].action_execution_id
            and by_key[key].compensation_status is None
        ]
        if compensable:
            _set_run_status(execution_id, "compensating")
            node_ids = {key: str(by_key[key].action_execution_id) for key in compensable}
            summary = _compensate_pass(
                run_id=execution_id, actor=actor, compensable=compensable, node_ids=node_ids, compensator=compensator
            )
            if summary["residual"]:
                error = build_error(
                    "compensation_failed",
                    "部分节点补偿失败（残留已逐条登记）。",
                    retryable=False,
                    details={"compensation_ids": summary["compensation_ids"], "residual_nodes": summary["residual"]},
                )
                rollback = {"status": "failed", "compensated_nodes": summary["compensated"], "residual": summary["residual"]}
                _finalize_run(execution_id, status="compensation_failed", error=error, rollback=rollback)
            else:
                rollback = {"status": "rolled_back", "compensated_nodes": summary["compensated"], "residual": []}
                _finalize_run(execution_id, status="rolled_back", error=None, rollback=rollback)
    return _run_result(execution_id)  # 终态（rolled_back/compensation_failed）：幂等短路复用


# ---- 落库辅助（每位点短事务；``_ae_session`` 用后即还） --------------------------


def _create_node_rows(run_id: str, graph: list[dict[str, Any]], run_key: str) -> None:
    """整图节点行预落（pending；``UNIQUE(run_id, node_key)`` 整图占位）。

    ``params_sha256``＝**声明面**指纹（ParamValue 规格的 canonical sha256，
    创建期即确定）；解析后实材指纹在 AE1 执行行（零明文分层）。"""
    with _ae_session() as session:
        for node in graph:
            action = node["action"]
            session.add(
                ActionTaskNode(
                    run_id=run_id,
                    node_key=node["node_key"],
                    depends_on_json=list(node["depends_on"]),  # 依赖快照冗余（逐字）
                    status="pending",
                    attempt=0,
                    node_idempotency_key=node_idempotency_key(run_key, node["node_key"], action),
                    params_sha256=params_sha256(action["params"]),
                )
            )
        session.commit()


def _set_run_status(
    run_id: str, status: str, *, error_code: str = "", error_json: dict[str, Any] | None = None
) -> None:
    with _ae_session() as session:
        row = session.scalar(select(ActionTaskRun).where(ActionTaskRun.id == run_id))
        if row is None:
            return
        row.status = status
        row.error_code = error_code
        row.error_json = error_json
        session.commit()


def _finalize_run(
    run_id: str,
    *,
    status: str,
    error: dict[str, Any] | None,
    rollback: dict[str, Any],
    audit: dict[str, Any] | None = None,
    cost: dict[str, Any] | None = None,
) -> None:
    with _ae_session() as session:
        row = session.scalar(select(ActionTaskRun).where(ActionTaskRun.id == run_id))
        if row is None:
            return
        row.status = status
        row.error_code = (error or {}).get("code", "")
        row.error_json = error
        row.rollback_json = rollback
        if audit is not None:
            row.audit_json = audit
        if cost is not None:
            row.cost_json = cost
        session.commit()


def _set_node_status(run_id: str, node_key: str, status: str, *, attempt: int | None = None) -> None:
    with _ae_session() as session:
        row = session.scalar(
            select(ActionTaskNode).where(ActionTaskNode.run_id == run_id, ActionTaskNode.node_key == node_key)
        )
        if row is None:
            return
        row.status = status
        if attempt is not None:
            row.attempt = attempt
        session.commit()


def _mark_node_succeeded(run_id: str, node_key: str, execution_id: str) -> None:
    with _ae_session() as session:
        row = session.scalar(
            select(ActionTaskNode).where(ActionTaskNode.run_id == run_id, ActionTaskNode.node_key == node_key)
        )
        if row is None:
            return
        row.status = "succeeded"
        row.action_execution_id = execution_id
        session.commit()


def _set_node_failed(run_id: str, node_key: str, error: dict[str, Any]) -> None:
    """失败节点行 → failed（error_json 登记；``action_execution_id`` 恒 null）。"""
    with _ae_session() as session:
        row = session.scalar(
            select(ActionTaskNode).where(ActionTaskNode.run_id == run_id, ActionTaskNode.node_key == node_key)
        )
        if row is None:
            return
        row.status = "failed"
        row.error_code = str(error.get("code", ""))
        row.error_json = error
        session.commit()


def _mark_nodes_skipped(run_id: str, node_keys: list[str]) -> None:
    if not node_keys:
        return
    with _ae_session() as session:
        rows = session.scalars(
            select(ActionTaskNode).where(ActionTaskNode.run_id == run_id, ActionTaskNode.node_key.in_(node_keys))
        ).all()
        for row in rows:
            row.status = "skipped"  # error=null：失败原因登记在运行级（不伪造节点级错误）
        session.commit()


def _set_node_compensation(run_id: str, node_key: str, compensation_status: str) -> None:
    with _ae_session() as session:
        row = session.scalar(
            select(ActionTaskNode).where(ActionTaskNode.run_id == run_id, ActionTaskNode.node_key == node_key)
        )
        if row is None:
            return
        row.compensation_status = compensation_status
        session.commit()


def _node_rows(run_id: str) -> list[Any]:
    with _ae_session() as session:
        return list(
            session.scalars(select(ActionTaskNode).where(ActionTaskNode.run_id == run_id)).all()
        )


# ---- 结果重建（响应/复放/补偿共用单一出口 ⇒ 同键复放逐字一致） -------------------


def _topo_from_rows(rows: list[Any]) -> list[str]:
    """从节点行依赖快照重建拓扑序（与派发序确定同构——复放逐字一致的基底）。"""
    pseudo = [{"node_key": row.node_key, "depends_on": list(row.depends_on_json or [])} for row in rows]
    return _topo_order(pseudo)


def _run_result(run_id: str) -> dict[str, Any]:
    """契约 ``TaskRunResult`` 重建：运行行 ＋ 节点行 ＋ AE1 执行行产物。

    output 只从 AE1 执行行读取（编排表零产物复制——C10 分层留痕）；响应在
    终态落库后统一走本出口，复放同构（B7 逐字一致）。"""
    with _ae_session() as session:
        run = session.scalar(select(ActionTaskRun).where(ActionTaskRun.id == run_id))
        if run is None:
            raise ActionExecutionError("not_found", NOT_FOUND_MESSAGE)
        rows = list(session.scalars(select(ActionTaskNode).where(ActionTaskNode.run_id == run_id)).all())
        outputs: dict[str, Any] = {}
        for row in rows:
            if row.action_execution_id:
                exec_row = session.scalar(
                    select(ActionExecution).where(ActionExecution.id == row.action_execution_id)
                )
                outputs[row.node_key] = exec_row.output_json if exec_row is not None else None
    order = _topo_from_rows(rows)
    by_key = {row.node_key: row for row in rows}
    nodes: list[dict[str, Any]] = []
    for key in order:
        row = by_key[key]
        nodes.append(
            {
                "node_key": row.node_key,
                "status": row.status,
                "attempt": row.attempt,
                "action_execution_id": row.action_execution_id,
                "output": outputs.get(row.node_key) if row.status == "succeeded" else None,
                "error": row.error_json,
                "compensation_status": row.compensation_status,
            }
        )
    return {
        "execution_id": run.id,
        "idempotency_key": run.idempotency_key,
        "status": run.status,
        "nodes": nodes,
        "error": run.error_json,
        "rollback": run.rollback_json or None,
    }


# ---- 运行期引用求值（仅 output 作用域；声明面已在 S2 拦越权） --------------------


class _MissingRef(Exception):
    """上游产物引用缺键（运行期数据面缺失——节点诚实 failed，不猜不填空）。"""

    def __init__(self, node: str, path: str) -> None:
        super().__init__(f"missing ref: {node} {path}")
        self.node = node
        self.path = path


def _resolve_params(params: dict[str, Any], outputs: dict[str, Any]) -> dict[str, Any]:
    """声明面 ParamValue → 解析后实材：literal 保型透传；ref 整值替换（不字符串化）。"""
    resolved: dict[str, Any] = {}
    for name, value in params.items():
        if isinstance(value, dict) and value.get("kind") == "ref":
            resolved[str(name)] = _lookup_ref(str(value["node"]), str(value["path"]), outputs)
        else:
            resolved[str(name)] = value.get("value")
    return resolved


def _lookup_ref(node: str, path: str, outputs: dict[str, Any]) -> Any:
    """路径求值：``output`` 根 ＋ ``.段``/``[idx]`` 段（段法式已在提交期钉死）。"""
    if node not in outputs:
        raise _MissingRef(node, path)
    value: Any = outputs[node]
    rest = path[len("output"):]
    for key, index in re.findall(r"\.([A-Za-z0-9_-]+)|\[([0-9]+)\]", rest):
        if key:
            if isinstance(value, dict) and key in value:
                value = value[key]
            else:
                raise _MissingRef(node, path)
        else:
            position = int(index)
            if isinstance(value, list) and position < len(value):
                value = value[position]
            else:
                raise _MissingRef(node, path)
    return value
