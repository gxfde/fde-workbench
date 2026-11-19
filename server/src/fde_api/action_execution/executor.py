"""action_execution 执行器：五层编排骨架 + ``ActionExecutor``（53 号 §3 WP1）。

编排顺序（契约 U1 ``x-validation-order``，上层未过即短路）：
``L1 结构 → L2 幂等 → L3 白名单 → L4 审批 → L5 闭合兜底 → 干跑/真执行 → 审计
→ 结果``。四门（幂等/白名单/审批/派发）为注入面——WP1 生产装配＝白名单
fail-closed（加载器归 WP3）＋派发未接线 fail-closed（连接器适配归 WP3）；
测试经桩门穿透到执行段。

指纹覆盖 10 个语义字段（U1 ``body_fingerprint.coverage_rule``：漏字段会造成
异体请求被静默复放）；``idempotency_key``/``org_id`` 不入指纹（前者是判定
本体，后者已是唯一约束组成部分）。
"""
from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Callable, Protocol

from fde_api.action_execution.schemas import build_result, validate_conditional, validate_request_shape
from fde_api.workbench.models import new_uuid

if TYPE_CHECKING:
    from fde_api.action_execution.models import ActionExecution

# 指纹语义字段（10；U1 v1.0.2 补 action_type + timeout_seconds）
FINGERPRINT_FIELDS = (
    "action_id",
    "action_type",
    "connector_id",
    "method",
    "params",
    "dry_run",
    "risk_level",
    "approval_id",
    "requester_id",
    "timeout_seconds",
)

Clock = Callable[[], datetime]


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def params_sha256(params: dict) -> str:
    """参数指纹（canonical JSON → sha256 hex）；审计与执行记录只存它，零明文。"""
    return hashlib.sha256(_canonical(params).encode("utf-8")).hexdigest()


def request_fingerprint(request: dict) -> str:
    """幂等体指纹：10 语义字段 canonical JSON → sha256（键序无关）。"""
    payload = {field: request.get(field) for field in FINGERPRINT_FIELDS}
    return hashlib.sha256(_canonical(payload).encode("utf-8")).hexdigest()


def simulate_output(request: dict) -> dict[str, Any]:
    """干跑仿真产物（T4-004 冻结断言 ``output.simulated==true``）；零 params 回显。"""
    return {
        "simulated": True,
        "action_id": request["action_id"],
        "connector_id": request["connector_id"],
        "method": request["method"],
        "params_sha256": params_sha256(request["params"]),
    }


class IdempotencyGate(Protocol):
    """L2 门：命中即裁决（mismatch/in_flight 由实现 raise；同体终态返回复放快照）。"""

    def lookup(self, idempotency_key: str, org_id: str, fingerprint: str) -> dict | None: ...


class WhitelistGate(Protocol):
    """L3 门：命中放行（返回 None）；未命中 raise 403 ``tool_not_allowed``（fail-closed）。"""

    def check(self, connector_id: str, method: str) -> None: ...


class ApprovalGate(Protocol):
    """L4 门：写型 risk≥3 实质校验（不通过 raise）；干跑/低风险返回 None 直通。"""

    def verify(self, request: dict) -> dict | None: ...


class Dispatch(Protocol):
    """执行段：连接器派发（WP3 前生产装配＝未接线 fail-closed）。"""

    def call(self, request: dict) -> dict: ...


class ActionExecutor:
    """单步 T4 执行链编排（「幂等门 → 白名单门 → 审批闸 → 干跑/真执行 → 审计
    → 结果」；G-AE-5 结构化动作载体的运行时真身）。"""

    def __init__(
        self,
        *,
        idempotency_gate: IdempotencyGate,
        whitelist_gate: WhitelistGate,
        approval_gate: ApprovalGate,
        dispatch: Dispatch,
        clock: Clock | None = None,
    ) -> None:
        self._idempotency = idempotency_gate
        self._whitelist = whitelist_gate
        self._approval = approval_gate
        self._dispatch = dispatch
        self._clock = clock or (lambda: datetime.now(UTC))

    def execute(self, request: dict) -> dict[str, Any]:
        validate_request_shape(request)  # L1（含敏感键扫描）
        fingerprint = request_fingerprint(request)
        prior = self._idempotency.lookup(request["idempotency_key"], request["org_id"], fingerprint)  # L2
        if prior is not None:
            # 复放：零新副作用、零新外呼——audit/cost 均复现首次（U3 T4-003）
            return build_result(
                execution_id=prior["execution_id"],
                idempotency_key=request["idempotency_key"],
                status="replayed",
                output=prior["output"],
                audit=prior["audit"],
                cost=prior["cost"],
                rollback=prior["rollback"],
                replayed_from_execution_id=prior["execution_id"],
            )
        self._whitelist.check(request["connector_id"], request["method"])  # L3
        approval = self._approval.verify(request)  # L4
        validate_conditional(request)  # L5 兜底（异常直连路径 422）
        started = self._clock()
        execution_id = new_uuid()
        if request["dry_run"]:
            output = simulate_output(request)
        else:
            output = self._dispatch.call(request)
        finished = self._clock()
        audit = {
            "connector_id": request["connector_id"],
            "method": request["method"],
            "params_sha256": params_sha256(request["params"]),
            "actor_user_id": request["requester_id"],
            "org_id": request["org_id"],
            # 干跑 approval_id 恒 null；低风险真执行无审批面介入亦 null（模块头读法）
            "approval_id": request.get("approval_id") if not request["dry_run"] else None,
            "started_at": started.isoformat(),
            "finished_at": finished.isoformat(),
            "duration_ms": max(int((finished - started).total_seconds() * 1000), 0),
        }
        if approval is not None and not request["dry_run"]:
            # 审批门返回的快照优先（执行侧以审批单登记面为准）
            audit["approval_id"] = approval.get("approval_id", audit["approval_id"])
        cost = {
            "tool_calls": 1,  # 干跑也计一次执行器调用（U3 T4-004 冻结断言口径）
            "duration_ms": audit["duration_ms"],
            "estimated_usd": 0.0,
        }
        rollback = {"supported": False, "execution_id": execution_id}
        return build_result(
            execution_id=execution_id,
            idempotency_key=request["idempotency_key"],
            status="succeeded",
            output=output,
            audit=audit,
            cost=cost,
            rollback=rollback,
        )


def replay_payload_from_row(row: "ActionExecution") -> dict | None:
    """从执行记录行构造 L2 复放快照（非 succeeded 终态行由调用方按原态构造）。"""
    return {
        "execution_id": row.id,
        "output": row.output_json,
        "audit": row.audit_json,
        "cost": row.cost_json,
        "rollback": row.rollback_json,
    }


__all__ = [
    "ActionExecutor",
    "ApprovalGate",
    "Dispatch",
    "FINGERPRINT_FIELDS",
    "IdempotencyGate",
    "WhitelistGate",
    "params_sha256",
    "request_fingerprint",
    "replay_payload_from_row",
    "simulate_output",
]
