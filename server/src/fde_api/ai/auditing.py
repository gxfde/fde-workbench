"""E7：AI 调用审计与月度 token 预算。

每次供应商调用落一条 ``ai_call_audits``（模型/耗时/token/结果状态），预算按
「当前自然月、按用户」汇总该表核算。约束：

- 审计只记录元数据，绝不落密钥或提示词/上下文明文。
- 预算默认 0 = 不限额（默认配置不锁死现有用户）；配置正数后，当月已用量
  达到预算即拒绝后续调用（不发起任何供应商请求）。
- 审计写入尽力而为：审计自身的失败不能打断业务 AI 调用。

N2 仪表化（AI 原生化差距台账 G-09/G-16）：

- **purpose 必填**：调用方必须声明这次调用用于什么（``chat_assistant``／
  ``discovery_extract``／``workflow_skill``…）。``purpose`` 在 DB 层 NOT NULL
  （迁移 ``c4f7a2d9e1b6``）——归因账本不允许匿名调用方。兜底：入口漏传时落
  ``unattributed`` 并记 warning（审计失败不打断业务，但异常必须可见）。
- **提示词指纹**：``prompt_fingerprint``＝指令源文本的 sha256（模板身份：
  同模板不同输入同指纹；提示词正文绝不落库）；``prompt_version``＝版本标签
  （未登记版本者留空，随 G-13 版本注册表填充）。
"""
from __future__ import annotations

import hashlib
import json
import logging
import time
from datetime import UTC, datetime
from typing import Any

from flask import g, has_app_context

from fde_api.extensions import db
from fde_api.workbench.models import AICallAudit

logger = logging.getLogger(__name__)

# 入口漏传 purpose 时的兜底标记（DB CHECK 只要求非空串；此值让异常可见）
UNATTRIBUTED_PURPOSE = "unattributed"


def compute_prompt_fingerprint(
    *,
    system_prompt: str | None = None,
    prompt: str | None = None,
    messages: list[dict[str, Any]] | None = None,
) -> str | None:
    """提示词指纹＝**指令源文本**的 sha256（十六进制 64 位）。

    取源优先级：``system_prompt`` → ``messages`` 里的 system 角色 →
    ``messages`` 全文 → ``prompt``。同模板不同输入 ⇒ **同指纹**（可按模板
    聚合归因）；无任何指令源时返回 None（不编造指纹）。

    指纹只标识模板身份，**不落任何提示词正文**（与「门禁证据只存
    source_uri + sha256」同款纪律：原件不入库）。
    """
    source: str | None = None
    if system_prompt and system_prompt.strip():
        source = system_prompt
    elif messages:
        for message in messages:
            if not isinstance(message, dict):
                continue
            if str(message.get("role") or "").lower() == "system":
                content = message.get("content")
                if isinstance(content, str) and content.strip():
                    source = content
                    break
        if source is None:
            source = json.dumps(messages, ensure_ascii=False, sort_keys=True, default=str)
    elif prompt and prompt.strip():
        source = prompt
    if source is None:
        return None
    return hashlib.sha256(source.encode("utf-8")).hexdigest()


def current_actor_id() -> str | None:
    """请求上下文里的当前用户 id；后台任务等无请求场景返回 None。"""
    if has_app_context():
        actor = getattr(g, "current_user", None) or getattr(g, "_current_user", None)
        if actor is not None and getattr(actor, "id", None):
            return str(actor.id)
    return None


def tokens_used_this_month(session: Any, actor_id: str) -> int:
    """当前自然月该用户的 AI token 消耗总量（审计表汇总）。"""
    from sqlalchemy import func, select

    month_start = datetime.now(UTC).replace(
        day=1, hour=0, minute=0, second=0, microsecond=0
    )
    total = session.scalar(
        select(func.coalesce(func.sum(AICallAudit.input_tokens + AICallAudit.output_tokens), 0)).where(
            AICallAudit.actor_user_id == actor_id,
            AICallAudit.created_at >= month_start,
            AICallAudit.status.in_(("succeeded", "budget_blocked")),
        )
    )
    return int(total or 0)


def budget_exceeded(session: Any, actor_id: str | None, budget: int) -> bool:
    """月度预算是否已用尽。actor 未知或预算非正数时一律放行。"""
    if not budget or budget <= 0 or not actor_id:
        return False
    return tokens_used_this_month(session, actor_id) >= budget


def record_audit(
    *,
    request_id: str,
    actor_id: str | None,
    purpose: str,
    model: str,
    used_fallback: bool,
    duration_ms: int,
    input_tokens: int | None,
    output_tokens: int | None,
    status: str,
    error_code: str | None,
    prompt_version: str | None = None,
    prompt_fingerprint: str | None = None,
) -> None:
    """落一条审计。尽力而为：任何失败只记日志，不打断业务调用。

    ``purpose`` 缺失时落 ``unattributed`` 并记 warning——DB CHECK 要求非空，
    但**审计写入不因缺 purpose 而整条丢失**（宁可留一条可见的匿名行，
    也不留无账的调用）。
    """
    label = (purpose or "").strip()
    if not label:
        label = UNATTRIBUTED_PURPOSE
        logger.warning(
            "AI call audit missing purpose request_id=%s status=%s", request_id, status
        )
    try:
        if not has_app_context():
            return
        session = db.session()
        try:
            with session.begin():
                session.add(
                    AICallAudit(
                        request_id=request_id[:120],
                        actor_user_id=actor_id,
                        purpose=label[:60],
                        model=model[:120],
                        used_fallback=used_fallback,
                        duration_ms=int(duration_ms),
                        input_tokens=input_tokens,
                        output_tokens=output_tokens,
                        status=status,
                        error_code=error_code[:60] if error_code else None,
                        prompt_version=prompt_version[:60] if prompt_version else None,
                        prompt_fingerprint=prompt_fingerprint[:64] if prompt_fingerprint else None,
                    )
                )
        finally:
            session.close()
    except Exception:  # noqa: BLE001 - 审计失败不阻塞业务
        logger.warning(
            "AI call audit write failed request_id=%s status=%s", request_id, status,
            exc_info=True,
        )


class Timer:
    """最小耗时计时器（毫秒）。"""

    def __init__(self) -> None:
        self._start = time.monotonic()

    def elapsed_ms(self) -> int:
        return int((time.monotonic() - self._start) * 1000)


def audit_budget_blocked(
    *, request_id: str, actor_id: str | None, purpose: str, model: str,
    prompt_version: str | None = None, prompt_fingerprint: str | None = None,
) -> None:
    """预算拦截统一留痕（CR-006 统一闸）：落一条 ``budget_blocked`` 审计。

    各调用方（deepseek 直连腿 / DSH 主路径 execute_ai_prompt / kimi 本地腿）
    抛各自的 ``ai_budget_exceeded`` 异常前调用，保证「拦截必有账」——预算
    汇总把 budget_blocked 计入已用量（status 过滤含 budget_blocked）。
    """
    record_audit(
        request_id=request_id,
        actor_id=actor_id,
        purpose=purpose,
        model=model,
        used_fallback=False,
        duration_ms=0,
        input_tokens=None,
        output_tokens=None,
        status="budget_blocked",
        error_code="ai_budget_exceeded",
        prompt_version=prompt_version,
        prompt_fingerprint=prompt_fingerprint,
    )
