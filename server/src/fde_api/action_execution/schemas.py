"""action_execution 三形态校验与构造（契约 U1 v1.0.6 $defs 的实现侧真身）。

分工：``validate_request_shape``＝五层顺序的第 1 层（结构/类型/枚举/闭集/
敏感键）；``validate_conditional``＝第 5 层兜底（if/then 条件必填——运行时
路径上第 4 层 403 优先于本层 422，U1 s_ae_01_alignment）；``build_result``/
``build_error``＝出口形态构造（status 与 error/output 的 if/then 绑定内建，
「成功必有结果、失败必有原因」在构造层强制）。

字段域与契约 $defs 逐字对齐（漂移即钉红：tests/test_ae_executor.py 常量区）。
敏感键扫描复用 ``control.access.contains_sensitive_argument``（同一真身，不
复刻词表）。

**拒绝消息不回显敏感键名**（评审补强 G2-11）：白名单 ``constraints.
log_redaction`` 要求敏感键「不得出现在日志、错误消息、响应体任何位置」——
未登记字段清单里若混有敏感键名，只报「含敏感键名」不报键名本身。
"""
from __future__ import annotations

import re
from typing import Any

from fde_api.action_execution.errors import ERROR_STATUS, ActionExecutionError
from fde_api.control.access import SENSITIVE_ARGUMENT_KEY, contains_sensitive_argument

EXECUTION_STATUSES = frozenset({"succeeded", "failed", "cancelled", "replayed", "awaiting_approval"})
ROLLBACK_STATUSES = frozenset({"rolled_back", "not_supported", "failed", "noop"})

REQUEST_REQUIRED = (
    "action_id",
    "connector_id",
    "method",
    "params",
    "idempotency_key",
    "org_id",
    "requester_id",
    "dry_run",
    "risk_level",
    "timeout_seconds",
)
# 闭集＝必填 10 ＋ 可选 2（action_type / approval_id）——additionalProperties=false
REQUEST_ALLOWED = frozenset(REQUEST_REQUIRED) | {"action_type", "approval_id"}

_ID_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_.:-]*$")
_ACTION_TYPE_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")
_METHOD_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_.-]*$")

IDEMPOTENCY_KEY_MAX = 160  # 对齐 Workbench 列宽（U1 x-idempotency.key_length）


def _is_str(value: Any) -> bool:
    return isinstance(value, str)


def _reject(code: str, message: str) -> None:
    raise ActionExecutionError(code, message)


def _contains_non_finite_number(value: Any) -> bool:
    """params 树内是否存在 NaN/Infinity 浮点（评审 P7——canonical JSON 拒 nan，
    在 L1 拦下给出 422 而非更深层的裸 ValueError）。"""
    if isinstance(value, float):
        return value != value or value in (float("inf"), float("-inf"))
    if isinstance(value, dict):
        return any(_contains_non_finite_number(v) for v in value.values())
    if isinstance(value, list):
        return any(_contains_non_finite_number(v) for v in value)
    return False


def _unknown_fields_message(unknown: list[str]) -> str:
    """未登记字段清单的消息文案（**不回显敏感键名**）。

    评审补强 G2-11：白名单 ``constraints.log_redaction`` 要求敏感键名不得
    出现在错误消息任何位置——未登记字段里混入 ``access_token`` 之类键名时，
    只报「含敏感键名」不报键名本身（非敏感字段照常列出，便于定位）。
    """
    sensitive = [name for name in unknown if SENSITIVE_ARGUMENT_KEY.search(str(name))]
    plain = [name for name in unknown if name not in sensitive]
    parts: list[str] = []
    if plain:
        parts.append("、".join(plain))
    if sensitive:
        parts.append("含敏感键名")
    return f"请求包含未登记字段：{'、'.join(parts)}。"


def validate_request_shape(payload: Any) -> None:
    """第 1 层：形状/类型/枚举/闭集/敏感键。不跑条件必填（归第 4/5 层）。"""
    if not isinstance(payload, dict):
        _reject("validation_failed", "请求体须为 JSON 对象。")
    unknown = sorted(set(payload) - REQUEST_ALLOWED)
    if unknown:
        _reject("validation_failed", _unknown_fields_message(unknown))
    for field in REQUEST_REQUIRED:
        if field not in payload:
            _reject("validation_failed", f"缺少必填字段：{field}。")
    action_id = payload["action_id"]
    if not _is_str(action_id) or not _ID_PATTERN.match(action_id) or len(action_id) > 128:
        _reject("validation_failed", "action_id 非法（1..128，字母开头）。")
    action_type = payload.get("action_type")
    if action_type is not None and (
        not _is_str(action_type) or not _ACTION_TYPE_PATTERN.match(action_type) or len(action_type) > 64
    ):
        _reject("validation_failed", "action_type 非法（1..64，小写蛇形）。")
    connector_id = payload["connector_id"]
    if not _is_str(connector_id) or not _ID_PATTERN.match(connector_id) or len(connector_id) > 128:
        _reject("validation_failed", "connector_id 非法（1..128，字母开头）。")
    method = payload["method"]
    if not _is_str(method) or not _METHOD_PATTERN.match(method) or len(method) > 64:
        _reject("validation_failed", "method 非法（1..64）。")
    if not isinstance(payload["params"], dict):
        _reject("validation_failed", "params 须为对象。")
    if contains_sensitive_argument(payload["params"]):
        _reject("sensitive_argument_forbidden", "参数命中敏感键名（凭据不得进动作材料）。")
    if _contains_non_finite_number(payload["params"]):
        # 评审 P7：NaN/Infinity 等非有限数值 → 422（不进指纹/落库链路——
        # canonical JSON allow_nan=False 会在更深处的门之前炸裸 ValueError）
        _reject("validation_failed", "params 含非有限数值（NaN/Infinity）。")
    idem_key = payload["idempotency_key"]
    if not _is_str(idem_key) or not (1 <= len(idem_key) <= IDEMPOTENCY_KEY_MAX):
        _reject("validation_failed", f"idempotency_key 须为 1..{IDEMPOTENCY_KEY_MAX} 字符。")
    for field in ("org_id", "requester_id"):
        value = payload[field]
        if not _is_str(value) or not (1 <= len(value) <= 64):
            _reject("validation_failed", f"{field} 须为 1..64 字符。")
    if type(payload["dry_run"]) is not bool:
        _reject("validation_failed", "dry_run 须为布尔（缺失即 422 显式声明制）。")
    risk_level = payload["risk_level"]
    if type(risk_level) is not int or not (0 <= risk_level <= 4):
        _reject("validation_failed", "risk_level 须为 0..4 整数。")
    timeout_seconds = payload["timeout_seconds"]
    if type(timeout_seconds) is not int or not (1 <= timeout_seconds <= 300):
        _reject("validation_failed", "timeout_seconds 须为 1..300 整数（秒）。")
    approval_id = payload.get("approval_id")
    if approval_id is not None and (not _is_str(approval_id) or len(approval_id) > 128):
        _reject("validation_failed", "approval_id 非法（≤128 字符或 null）。")


def validate_conditional(payload: Any) -> None:
    """第 5 层兜底：dry_run=false ∧ risk≥3 ⇒ approval_id 非空串（422）。"""
    if not isinstance(payload, dict):
        _reject("validation_failed", "请求体须为 JSON 对象。")
    dry_run = payload.get("dry_run")
    risk_level = payload.get("risk_level")
    if dry_run is False and type(risk_level) is int and risk_level >= 3:
        approval_id = payload.get("approval_id")
        if not _is_str(approval_id) or not approval_id.strip():
            _reject("validation_failed", "写型高风险动作缺 approval_id（第 5 层兜底；运行时应为 403 approval_required）。")


def build_error(code: str, message: str, *, retryable: bool, details: dict | None = None) -> dict[str, Any]:
    """契约 $defs/ErrorObject：code 闭集外即拒（Q8：映射不造码）。"""
    if code not in ERROR_STATUS:
        raise ValueError(f"AE 错误码闭集外：{code}")
    if not _is_str(message) or not (1 <= len(message) <= 500):
        raise ValueError("error.message 须为 1..500 字符（脱敏说明）。")
    obj: dict[str, Any] = {"code": code, "message": message, "retryable": bool(retryable)}
    if details is not None:
        obj["details"] = details
    return obj


def build_result(
    *,
    execution_id: str,
    idempotency_key: str,
    status: str,
    output: dict | None,
    audit: dict,
    cost: dict,
    rollback: dict,
    error: dict | None = None,
    replayed_from_execution_id: str | None = None,
) -> dict[str, Any]:
    """契约 $defs/ActionExecutionResult：status 与 error/output 的 if/then 绑定在构造层强制。"""
    if status not in EXECUTION_STATUSES:
        raise ValueError(f"执行状态闭集外：{status}")
    result: dict[str, Any] = {
        "execution_id": execution_id,
        "idempotency_key": idempotency_key,
        "status": status,
    }
    if status == "succeeded":
        if error is not None:
            raise ActionExecutionError("validation_failed", "succeeded 态 error 必须为 null。")
        if not isinstance(output, dict):
            raise ActionExecutionError("validation_failed", "succeeded 态 output 必为对象。")
    elif status == "failed":
        if error is None:
            raise ActionExecutionError("validation_failed", "failed 态 error 必须非 null。")
        if output is not None and not isinstance(output, dict):
            raise ActionExecutionError("validation_failed", "failed 态 output 只能为对象或 null。")
    elif status == "cancelled":
        if error is None:
            raise ActionExecutionError("validation_failed", "cancelled 必带取消原因（error 非 null）。")
    elif status == "awaiting_approval":
        if error is not None:
            raise ActionExecutionError("validation_failed", "awaiting_approval 尚未执行，error 恒为 null。")
    elif status == "replayed":
        if not replayed_from_execution_id:
            raise ActionExecutionError("validation_failed", "replayed 必带 replayed_from_execution_id。")
        if not isinstance(output, dict):
            raise ActionExecutionError("validation_failed", "replayed 态 output 必为对象（复现首次产物）。")
    if error is not None and not isinstance(error, dict):
        raise ActionExecutionError("validation_failed", "error 须为对象或 null。")
    result["output"] = output
    result["error"] = error
    result["audit"] = audit
    result["cost"] = cost
    result["rollback"] = rollback
    if status == "replayed":
        result["replayed_from_execution_id"] = replayed_from_execution_id
    else:
        result["replayed_from_execution_id"] = None
    return result


def _validate_compensation(comp: Any) -> None:
    if not isinstance(comp, dict):
        raise ActionExecutionError("validation_failed", "compensations 条目须为对象。")
    missing = [k for k in ("compensation_id", "kind", "target", "status") if not comp.get(k)]
    if missing:
        raise ActionExecutionError("validation_failed", f"补偿条目缺必填字段：{'、'.join(missing)}。")
    if comp["status"] not in ("succeeded", "failed", "skipped"):
        raise ActionExecutionError("validation_failed", f"补偿条目状态闭集外：{comp['status']}。")


def build_rollback_result(
    *,
    execution_id: str,
    status: str,
    compensations: list[dict],
    error: dict | None,
    output: dict | None = None,
) -> dict[str, Any]:
    """契约 $defs/RollbackResult：四态与 error/compensations 的 if/then 绑定在构造层强制。

    - ``rolled_back`` ⇒ error null ＋ compensations ≥1 且每条恒 ``succeeded``
      （任一条 failed/skipped 只能走 ``failed``——部分补偿不得谎报整体成功）；
    - ``not_supported`` ⇒ error.code 恒 ``rollback_not_supported``；
    - ``failed`` ⇒ error.code 恒 ``compensation_failed``（details.compensation_ids
      由调用方列出失败条目）；
    - ``noop`` ⇒ error null 且 compensations 空数组（不省略——省略与空数组不可区分）。
    """
    if status not in ROLLBACK_STATUSES:
        raise ValueError(f"回滚状态闭集外：{status}")
    for comp in compensations:
        _validate_compensation(comp)
    result: dict[str, Any] = {"execution_id": execution_id, "status": status}
    if status == "rolled_back":
        if error is not None:
            raise ActionExecutionError("validation_failed", "rolled_back 态 error 必须为 null。")
        if len(compensations) < 1 or any(c["status"] != "succeeded" for c in compensations):
            raise ActionExecutionError(
                "validation_failed", "rolled_back 要求补偿 ≥1 条且每条恒 succeeded。"
            )
    elif status == "noop":
        if error is not None:
            raise ActionExecutionError("validation_failed", "noop 态 error 必须为 null。")
        if compensations:
            raise ActionExecutionError("validation_failed", "noop 态 compensations 必须为空数组。")
    elif status == "not_supported":
        if error is None or error.get("code") != "rollback_not_supported":
            raise ActionExecutionError("validation_failed", "not_supported 态 error.code 恒 rollback_not_supported。")
    elif status == "failed":
        if error is None or error.get("code") != "compensation_failed":
            raise ActionExecutionError("validation_failed", "failed 态 error.code 恒 compensation_failed。")
        if not any(c["status"] == "failed" for c in compensations):
            raise ActionExecutionError("validation_failed", "failed 态须含至少一条 failed 补偿。")
    result["compensations"] = compensations
    result["output"] = output
    result["error"] = error
    return result
