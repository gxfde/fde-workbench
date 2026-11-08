"""短期执行授权票据（V3.1 P1-1，任务书 §9 前置 3；00-gap-register 5.3）。

HMAC-SHA256 票据（MCP 15min JWT 原型的 agent_run 域对应物）：绑定用户/项目/
run/工作目录/允许动作 + 短 TTL + 撤销语义=验证时必传 run_id 与所需动作集合
（票据本身无状态，撤销经 run 终态/策略层拒绝承载——发行面 HTTP 端点随通道
开放轮落地，5.10 闸未过前不提供，避免「结构存在但永远 409」的死面）。

与 MCP JWT 的差异：非 JWT（无签名算法协商面——单一 HMAC-SHA256 闭集）、
载荷为 canonical JSON（sort_keys，#209 确定性纪律）、签名恒比较
（``hmac.compare_digest``）。

纯函数模块（时钟经 ``now``/``issued_at`` 注入；密钥由调用方注入，绝不入
argv/env/日志——前置 9）。
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
from datetime import UTC, datetime
from typing import Any

EXECUTION_ACTIONS = frozenset({"workspace.read", "workspace.write", "command.run", "artifact.publish"})
GRANT_TTL_SECONDS = 15 * 60
_SECRET_MIN_BYTES = 32


class ExecutionGrantError(RuntimeError):
    """票据拒绝（code：malformed/tampered/expired/run_mismatch/action_exceeded）。"""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _b64url_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64url_decode(text: str) -> bytes:
    padding = "=" * (-len(text) % 4)
    try:
        return base64.urlsafe_b64decode(text + padding)
    except (ValueError, TypeError) as error:
        raise ExecutionGrantError("malformed", "票据段不是合法 base64url。") from error


def _signature(secret: bytes, payload_segment: str) -> str:
    digest = hmac.new(secret, payload_segment.encode("ascii"), hashlib.sha256).digest()
    return _b64url_encode(digest)


def issue_execution_grant(
    secret: bytes,
    *,
    user_id: str,
    project_id: str,
    run_id: str,
    workspace: str,
    actions: list[str] | tuple[str, ...],
    issued_at: datetime,
    ttl_seconds: int = GRANT_TTL_SECONDS,
) -> str:
    """签发绑定票据：payload(base64url).signature(base64url)。"""
    if len(secret) < _SECRET_MIN_BYTES:
        raise ExecutionGrantError("malformed", f"签名密钥须 ≥{_SECRET_MIN_BYTES} 字节。")
    unknown = set(actions) - EXECUTION_ACTIONS
    if unknown:
        raise ExecutionGrantError("malformed", f"未注册动作：{'、'.join(sorted(unknown))}。")
    if not actions:
        raise ExecutionGrantError("malformed", "actions 不能为空（最小权限：至少一个动作）。")
    if ttl_seconds <= 0 or ttl_seconds > GRANT_TTL_SECONDS:
        raise ExecutionGrantError("malformed", f"ttl_seconds 须为 1..{GRANT_TTL_SECONDS}。")
    issued = issued_at if issued_at.tzinfo else issued_at.replace(tzinfo=UTC)
    payload = {
        "user_id": user_id,
        "project_id": project_id,
        "run_id": run_id,
        "workspace": workspace,
        "actions": sorted(actions),  # 集合语义顺序无关（#209 确定性纪律）
        "iat": int(issued.timestamp()),
        "exp": int(issued.timestamp()) + ttl_seconds,
    }
    payload_segment = _b64url_encode(
        json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    )
    return f"{payload_segment}.{_signature(secret, payload_segment)}"


def verify_execution_grant(
    token: str,
    secret: bytes,
    *,
    run_id: str,
    now: datetime,
    required_actions: list[str] | tuple[str, ...],
) -> dict[str, Any]:
    """验证票据：形状 → 签名 → 过期 → run 绑定 → 动作覆盖；通过返回载荷。"""
    parts = token.split(".")
    if len(parts) != 2 or not all(parts):
        raise ExecutionGrantError("malformed", "票据须为 payload.signature 两段。")
    payload_segment, signature = parts
    expected = _signature(secret, payload_segment)
    if not hmac.compare_digest(signature, expected):
        raise ExecutionGrantError("tampered", "票据签名不匹配。")
    try:
        payload = json.loads(_b64url_decode(payload_segment).decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ExecutionGrantError("malformed", "票据载荷不是合法 JSON。") from error
    if not isinstance(payload, dict):
        raise ExecutionGrantError("malformed", "票据载荷不是对象。")
    current = now.timestamp() if now.tzinfo else now.replace(tzinfo=UTC).timestamp()
    if current > int(payload.get("exp", 0)):
        raise ExecutionGrantError("expired", "票据已过期。")
    if payload.get("run_id") != run_id:
        raise ExecutionGrantError("run_mismatch", "票据不绑定当前 run。")
    granted = set(payload.get("actions") or [])
    missing = set(required_actions) - granted
    if missing:
        raise ExecutionGrantError(
            "action_exceeded", f"所需动作未获授权：{'、'.join(sorted(missing))}。"
        )
    return payload
