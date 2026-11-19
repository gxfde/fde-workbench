"""action_execution 服务面：真门装配 + 执行记录落库（AE1-WP1）。

门装配（WP1 生产默认）：
- **幂等门**＝查 ``action_executions``（UNIQUE(org_id, idempotency_key)）——
  同键异体 409 ``idempotency_mismatch``；同体在途（awaiting_approval 行在场）
  409 ``idempotency_in_flight``；同体终态复放（不落新行，零副作用）；
- **白名单门**＝fail-closed（无注册连接器一律 403 ``tool_not_allowed``；
  只读加载器与三元组匹配归 AE1-WP3，禁改清单第 7 项：缺失/损坏不得回退
  「任意 URL 可调」）；
- **审批门**＝复用 ``AutomationApproval``（``run_id=None`` 直发形态）+ 指纹
  复算沿 ``control/service.py`` 先例；拍板面 ``decide_automation_approval``
  本体零改动（禁改清单第 1 项）；
- **派发**＝未接线 fail-closed（403 + ``details.connector_adapter_not_wired``，
  Q8 闭集外映射口径）；连接器适配归 AE1-WP3。
"""
from __future__ import annotations

import json
from datetime import UTC, datetime
from hashlib import sha256
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import joinedload

from fde_api.action_execution.executor import ActionExecutor, replay_payload_from_row, request_fingerprint
from fde_api.action_execution.errors import ActionExecutionError
from fde_api.action_execution.models import ActionExecution
from fde_api.auth.models import User
from fde_api.control.access import authorize_ai_capability
from fde_api.control.models import AutomationApproval
from fde_api.errors import NOT_FOUND_MESSAGE
from fde_api.extensions import db

AE_CAPABILITY = "action_execution.invoke"  # CAPABILITY_REQUIREMENTS：project_operator（AE1-WP1 注册）


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


class _DbIdempotencyGate:
    """L2 门：``action_executions`` 表上的幂等裁决。"""

    def lookup(self, idempotency_key: str, org_id: str, fingerprint: str) -> dict | None:
        session = db.session()
        row = session.scalar(
            select(ActionExecution).where(
                ActionExecution.idempotency_key == idempotency_key,
                ActionExecution.org_id == org_id,
            )
        )
        if row is None:
            return None
        if row.request_fingerprint != fingerprint:
            raise ActionExecutionError("idempotency_mismatch", "同键请求体不一致（幂等指纹不符）。")
        if row.status == "awaiting_approval":
            raise ActionExecutionError("idempotency_in_flight", "同键执行在途，请退避后重试。")
        if row.status == "succeeded":
            return replay_payload_from_row(row)
        # failed/cancelled 终态行：复放原失败态（WP1 执行段不产此类行；腿留 WP2+）
        return {
            "execution_id": row.id,
            "output": row.output_json or {},
            "audit": row.audit_json,
            "cost": row.cost_json,
            "rollback": row.rollback_json,
        }


class _FailClosedWhitelist:
    """L3 门（WP1 默认）：无白名单装配＝全拒（fail-closed 默认关，Q7/禁改 7）。"""

    def check(self, connector_id: str, method: str) -> None:
        raise ActionExecutionError("tool_not_allowed", "连接器未在白名单注册（fail-closed）。")


class _UnwiredDispatch:
    """执行段（WP1 默认）：连接器适配未接线 → fail-closed 拒绝（Q8 映射+details）。"""

    def call(self, request: dict) -> dict:
        raise ActionExecutionError(
            "tool_not_allowed",
            "连接器适配未接线（AE1-WP3 落位前拒绝一切外呼）。",
            details={"reason": "connector_adapter_not_wired"},
        )


class _DbApprovalGate:
    """L4 门：写型 risk≥3 校验 ``AutomationApproval``（复用拍板面的登记面）。"""

    def __init__(self, actor: User) -> None:
        self._actor = actor

    def verify(self, request: dict) -> dict | None:
        if request["dry_run"] or request["risk_level"] < 3:
            return None  # 干跑/低风险直通（审批闸只管写型高风险）
        approval_id = request.get("approval_id")
        if not isinstance(approval_id, str) or not approval_id.strip():
            raise ActionExecutionError("approval_required", "写型高风险动作缺 approval_id。")
        session = db.session()
        approval = session.scalar(
            select(AutomationApproval)
            .options(joinedload(AutomationApproval.project))
            .where(AutomationApproval.id == approval_id)
        )
        if approval is None:
            raise ActionExecutionError("approval_not_found", "审批请求不存在。", status=404)
        # 归属面：审批单租户链（project.org_id）与请求 org 不符 → 404 不泄露；
        # 审批单请求人与执行 requester 不符 → 404 同口径（跨主体不泄露）。
        project = approval.project
        if project is None or project.org_id != request["org_id"]:
            raise ActionExecutionError("approval_not_found", "审批请求不存在。", status=404)
        if approval.requested_by_user_id != request["requester_id"]:
            raise ActionExecutionError("approval_not_found", "审批请求不存在。", status=404)
        now = datetime.now(UTC)
        if approval.status == "expired" or (approval.status == "pending" and approval.expires_at <= now):
            raise ActionExecutionError("approval_expired", "操作审批已过期。")
        if approval.status != "approved":
            raise ActionExecutionError("approval_not_approved", "该操作尚未获批。")
        # 指纹复算（U1 x-approval.integrity；沿 control/service.py:864-871 先例）：
        # 请求 params 的 canonical sha256 须与审批登记面一致。
        if sha256(_canonical(request["params"]).encode("utf-8")).hexdigest() != approval.arguments_sha256:
            raise ActionExecutionError("approval_integrity_failed", "审批参数完整性校验失败。")
        # 执行前权限重验（U1 x-approval.revocation）
        decision = authorize_ai_capability(user=self._actor, capability=AE_CAPABILITY, project=project)
        if not decision.allowed:
            raise ActionExecutionError("permission_revoked", "任务发起人已不具备该操作权限。")
        return {"approval_id": approval.id}


FAIL_CLOSED_WHITELIST = _FailClosedWhitelist()
UNWIRED_DISPATCH = _UnwiredDispatch()


def submit_action(
    *,
    actor: User,
    payload: Any,
    whitelist_gate=_FailClosedWhitelist(),
    dispatch=_UnwiredDispatch(),
) -> dict[str, Any]:
    """提交单步动作执行（租户绑定 → 五层编排 → 落库 → 契约结果）。

    返回契约 ``ActionExecutionResult`` 形态 dict；复放不落新行。拒绝路径以
    ``ActionExecutionError`` 冒泡（routes 转 ``{data:null,error:{...}}`` 信封）。
    """
    if not isinstance(payload, dict):
        raise ActionExecutionError("validation_failed", "请求体须为 JSON 对象。")
    # 租户绑定（U1 x-tenant-isolation.server_side_binding：不盲信调用方 org_id；
    # 与上下文不一致按 404——Q15 口径，不泄露「存在但无权」与「不存在」的差别）
    request_org = payload.get("org_id")
    if not isinstance(request_org, str) or request_org != actor.org_id:
        raise ActionExecutionError("not_found", NOT_FOUND_MESSAGE)

    executor = ActionExecutor(
        idempotency_gate=_DbIdempotencyGate(),
        whitelist_gate=whitelist_gate,
        approval_gate=_DbApprovalGate(actor),
        dispatch=dispatch,
    )
    result = executor.execute(payload)
    if result["status"] == "replayed":
        return result  # 复放零新行（同键一行真身）
    _persist(payload, result)
    return result


def _persist(payload: dict, result: dict[str, Any]) -> None:
    """执行记录落库（零 params 明文；append-only）。"""
    session = db.session()
    with session.begin():
        session.add(
            ActionExecution(
                id=result["execution_id"],
                idempotency_key=payload["idempotency_key"],
                org_id=payload["org_id"],
                requester_id=payload["requester_id"],
                action_id=payload["action_id"],
                action_type=payload.get("action_type"),
                connector_id=payload["connector_id"],
                method=payload["method"],
                params_sha256=result["audit"]["params_sha256"],
                request_fingerprint=request_fingerprint(payload),
                dry_run=bool(payload["dry_run"]),
                risk_level=int(payload["risk_level"]),
                approval_id=result["audit"]["approval_id"],
                status=result["status"],
                output_json=result["output"],
                error_code=(result["error"] or {}).get("code", ""),
                error_json=result["error"],
                replayed_from_execution_id=result["replayed_from_execution_id"],
                audit_json=result["audit"],
                cost_json=result["cost"],
                rollback_json=result["rollback"],
            )
        )


def get_execution(*, actor, execution_id: str) -> dict[str, Any]:
    """执行详情（本人/同租户；跨租户 404 复用关闭面文案不泄露存在性）。"""
    session = db.session()
    row = session.scalar(select(ActionExecution).where(ActionExecution.id == execution_id))
    if row is None or row.org_id != actor.org_id:
        raise ActionExecutionError("not_found", NOT_FOUND_MESSAGE)
    return row.snapshot()


def get_execution_row(execution_id: str) -> ActionExecution | None:
    """内部辅助（测试/运维检视）：按 id 取原始行，无租户过滤。"""
    return db.session().scalar(select(ActionExecution).where(ActionExecution.id == execution_id))
