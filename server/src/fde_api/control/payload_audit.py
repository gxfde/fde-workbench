"""AF1-WP4（N1）：工具调用载荷的审计留痕——脱敏 + 截断（工程台回查面的数据前提）。

64KB 上限＝规格 docs/ai-fde/13 §6.2（T1：agent_tool_calls 加列）；超限截断
并置 ``payload_truncated`` 标记——载荷是留痕不是全文存档。best-effort 契约：
不可序列化载荷返回 ``(None, False)``，调用方落 NULL、判定与执行语义零变化
（载荷为附加留痕，任何失败不得改变工具调用本身的结果）。

脱敏（S03 拍板落地，2026-11-18 P1「全部批准」；任务书 §15：凭据不明文存储）：
键名白名单命中（``_SENSITIVE_KEY_FRAGMENTS``，大小写与 ``_``/``-``/空白分隔
归一后匹配）→ 值替换固定掩码，键名保留——掩码后键名可见、值不可见；
截断逻辑与标记语义零变化。

零依赖独立模块：agents/adapter（宿主回执面）与 control/ai_tool_loop（直连
循环面）两侧共用，避免 control↔agents 循环 import。
"""
from __future__ import annotations

import json
from typing import Any, Tuple

MAX_AUDIT_PAYLOAD_BYTES = 64 * 1024
_TRUNCATED_MARK = '…"payload_truncated":true'
_REDACTED_VALUE = "***redacted***"

# S03 键名白名单：片段命中即遮蔽（子串形态覆盖 db_password/apiKey/
# private_key 等组合键）；归一化 = lowercase + 剥 ``_``/``-``/空白分隔符
_SENSITIVE_KEY_FRAGMENTS = (
    "password",
    "secret",
    "token",
    "apikey",
    "authorization",
    "cookie",
    "credential",
    "privatekey",
)


def _is_sensitive_key(key: str) -> bool:
    normalized = "".join(ch for ch in str(key).lower() if ch not in "_- ")
    return any(fragment in normalized for fragment in _SENSITIVE_KEY_FRAGMENTS)


def _redact(value: Any, depth: int = 0) -> Any:
    """递归遮蔽：dict/list 容器内命中白名单键名的值替换为掩码。

    best-effort：深度上限（防自引用递归爆栈）与异常都按「不脱敏原样
    返回」处理——脱敏失败不得改变工具调用结果。
    """
    if depth > 64:
        return value
    try:
        if isinstance(value, dict):
            out: dict[Any, Any] = {}
            for key, item in value.items():
                if isinstance(key, str) and _is_sensitive_key(key):
                    out[key] = _REDACTED_VALUE
                else:
                    out[key] = _redact(item, depth + 1)
            return out
        if isinstance(value, list):
            return [_redact(item, depth + 1) for item in value]
    except (RecursionError, TypeError, ValueError):
        return value
    return value


def audit_payload(value: Any) -> Tuple[str | None, bool]:
    """序列化 *value* 为审计文本： ``(text, truncated)``。

    - ``None`` → ``(None, False)``（无载荷，列落 NULL）；
    - 不可序列化（集合/自引用等）→ ``(None, False)``——不炸判定；
    - 编码后 ≤64KB → 原文（键名命中白名单的值已遮蔽）+ ``False``；
    - 超限 → 按 UTF-8 最坏 3 字节/字符保守截断 + ``True`` 标记。
    """
    if value is None:
        return None, False
    if isinstance(value, str):
        text = value
    else:
        try:
            text = json.dumps(_redact(value), ensure_ascii=False, default=str)
        except (TypeError, ValueError, RecursionError):
            return None, False
    try:
        raw = text.encode("utf-8")
    except UnicodeEncodeError:
        return None, False
    if len(raw) <= MAX_AUDIT_PAYLOAD_BYTES:
        return text, False
    # 字节级安全截断：UTF-8 最坏 4 字节/字符（emoji），按字符数切会越限
    # （评审 edge：21845 字符 × 4B ≈ 87KB > Text 65535）——切字节流后容错解码
    cut = raw[: MAX_AUDIT_PAYLOAD_BYTES - len(_TRUNCATED_MARK.encode("utf-8"))].decode(
        "utf-8", "ignore"
    )
    return cut + _TRUNCATED_MARK, True
