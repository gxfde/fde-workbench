"""动态 PromptOverlay 两点共用装载（学习闭环 2.0 L5）。

``load_overlays(purpose, prompt_version=None)`` 是 overlay 注入的**唯一装载读面**，
被两点共用（设计稿 v1.1 §2.5C，评审 P0-Ⅱ）：

- ``control/ai_server_client.py::execute_ai_prompt``（DSH/降级分叉**之前**注入，
  防降级路径丢 overlay）；
- ``ai/deepseek.py::DeepSeekClient.complete_json`` 直连腿（DSH 关闭部署下全覆盖）。

纪律（N6 受控例外升格，任务书 L53）：
- **仅追加式**——overlay 片段拼在既有指令源之后，``prompt_registry`` 常量本体
  零触碰；``compute_prompt_fingerprint`` 在注入**之前**算（指纹仍按注册表常量，
  模板身份不变），overlay 归因走 ``AICallAudit.context_payload_json``
  （形如 ``{"overlay_ids": [...], "overlay_sha256": [...]}``，PG JSON 包含查询
  可反查「哪次调用注入了哪几条已发布条款」）。
- **零模块级缓存**——每次现查 ``prompt_overlays`` published 行（按 created_at
  升序），热生效/回滚（release_channel 翻 status）下一次调用即反映，与动态
  Lessons 同纪律。
- **v1 purpose 白名单＝内网面**——由 ``prompt_registry`` 登记闭集派生
  （点号转下划线），排除公网面 ``diagnostics.report``；未登记 purpose 装载
  自然无行（拒发布＋装载空，零回归）。
- **软失败**——DB 故障/无应用上下文回落空列表，静态指令源照常执行（业务不
  因 overlay 设施故障而中断，与 lessons 动态腿同款）。
"""

from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

# ── 白名单（v1 仅内网面，§6-6 拍板：平台级生效，org 作用域 L6 后再议） ─────
_EXCLUDED_PUBLIC_PURPOSES: frozenset[str] = frozenset({"diagnostics_report"})


def _derive_whitelist() -> frozenset[str]:
    """由 prompt_registry 登记闭集派生 overlay purpose 白名单（下划线风格）。

    派生而非硬编码——新增内网面提示词常量登记进 registry 即自动进白名单；
    公网面（``diagnostics.*``）显式排除（评测集污染隔离＋公网写面纪律）。
    """
    from fde_api.ai.prompt_registry import PROMPT_REGISTRATIONS

    return frozenset(
        reg.key.replace(".", "_")
        for reg in PROMPT_REGISTRATIONS
        if reg.key.replace(".", "_") not in _EXCLUDED_PUBLIC_PURPOSES
    )


#: overlay 发布/装载的 purpose 权威闭集（13 key；diagnostics_report 除外）。
OVERLAY_PURPOSE_WHITELIST: frozenset[str] = _derive_whitelist()


def purpose_allowed(purpose_key: str) -> bool:
    """发布闭集校验：未登记 purpose 拒发布（静态钉可引用本函数）。"""
    return purpose_key in OVERLAY_PURPOSE_WHITELIST


# ── 版本后缀解析（min_prompt_version 数字尾缀，防 v10<v2 字符串比较错位） ──
def version_suffix(version: str | None) -> int | None:
    """版本标签的尾部数字后缀（``...-v3``⇒3，``...-v10``⇒10）；不可解析⇒None。"""
    if not version:
        return None
    match = re.search(r"(\d+)$", str(version).strip())
    return int(match.group(1)) if match else None


# ── 注入闸五件套①：句式静态闸（禁祈使/第二人称/模式词，中英双语启发式） ──
# 判据＝「第二人称＋祈使动词」核心族：第二人称（你/您/you/your）与祈使动词
# （务必/切勿/严禁/请勿/please/do not/make sure）命中即拒。
# ★刻意放行「必须/不得/不要/must/should」一类**规范陈述词**——经验条款正文
# 大量使用「不得虚构数据」「必须保留引用编号」等陈述式句式，全量禁模式词会
# 把合规条款全打成违例（误伤）；祈使语义由上述核心族兜住，残余风险由审批面
# 并排呈现终文（五件套③）人工复核收口。
_IMPERATIVE_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        # 中文第二人称＋祈使动词＋注入模式词核心族
        r"请",
        r"你",
        r"您",
        r"务必",
        r"切勿",
        r"严禁",
        r"忽略",
        r"无视",
        r"重新设定",
        r"以上指令",
        # 英文第二人称 / 祈使 / 注入模式词
        r"\byou\b",
        r"\byour\b",
        r"\bplease\b",
        r"\bdo not\b",
        r"\bdon't\b",
        r"\bmake sure\b",
        r"\bignore\b",
        r"\bdisregard\b",
        r"\boverride\b",
        r"\bsystem\s*prompt\b",
        r"\bprevious\s+instructions?\b",
        r"\babove\s+instructions?\b",
    )
)

#: 注入闸② n-gram 防洗稿上限：候选片段与既有静态提示词 12-gram 重叠率超过阈值⇒拒发布。
MAX_NGRAM_OVERLAP_RATIO: float = 0.50


def validate_overlay_fragment(fragment: str) -> str | None:
    """句式静态闸：返回违例码或 None（合规）。

    发布侧（release_channel overlay 执行器）与回归沙箱共用本闸（同尺纪律）；
    命中⇒``imperative_or_second_person``。
    """
    text = (fragment or "").strip()
    if not text:
        return "empty_fragment"
    if len(text) > 200:
        return "fragment_too_long"
    for pattern in _IMPERATIVE_PATTERNS:
        if pattern.search(text):
            return "imperative_or_second_person"
    return None


def ngram_overlap_ratio(fragment: str, reference: str, n: int = 12) -> float:
    """注入闸② n-gram 防洗稿：fragment 字符 n-gram 命中既有指令源的比例。

    比例高＝overlay 是既有提示词换措辞复述（非独立新条款），发布侧据此拒；
    纯函数，无 I/O。
    """
    fragment = fragment or ""
    reference = reference or ""
    if len(fragment) < n or len(reference) < n:
        return 0.0
    grams = {fragment[i : i + n] for i in range(len(fragment) - n + 1)}
    if not grams:
        return 0.0
    reference_text = reference
    hits = sum(1 for gram in grams if gram in reference_text)
    return hits / len(grams)


# ── 装载（两点共用唯一读面） ──
_SECTION_HEADER = "\n\n【平台动态经验条款】\n"


def apply_overlays_to_system_prompt(
    system_prompt: str | None, fragments: list[str]
) -> str | None:
    """execute_ai_prompt 侧注入：追加式拼在既有 system_prompt 之后。"""
    if not fragments:
        return system_prompt
    suffix = _SECTION_HEADER + "\n".join(fragments)
    if system_prompt:
        return system_prompt + suffix
    return suffix.strip()


def apply_overlays_to_messages(
    messages: list[dict[str, Any]], fragments: list[str]
) -> list[dict[str, Any]]:
    """deepseek 直连腿注入：追加进 system 角色（无 system 行则前插），浅拷贝不回写原列表。"""
    if not fragments:
        return messages
    suffix = _SECTION_HEADER + "\n".join(fragments)
    result: list[dict[str, Any]] = []
    injected = False
    for message in messages:
        if not injected and isinstance(message, dict) and message.get("role") == "system":
            updated = dict(message)
            content = str(updated.get("content") or "")
            updated["content"] = content + suffix
            result.append(updated)
            injected = True
        else:
            result.append(message)
    if not injected:
        overlay_system_content = suffix.strip()
        result.insert(0, {"role": "system", "content": overlay_system_content})
    return result


def load_overlays(
    purpose: str,
    prompt_version: str | None = None,
    session: Any | None = None,
) -> tuple[list[str], dict[str, Any] | None]:
    """装载某 purpose 的全部已发布 overlay 片段。

    返回 ``(fragments, payload)``：
    - ``fragments``＝注入用条款正文（按 created_at 升序）；空⇒零回归（调用方
      既有指令源逐字节不变）；
    - ``payload``＝归因载荷 ``{"overlay_ids": [...], "overlay_sha256": [...]}``
      写入 ``AICallAudit.context_payload_json``（空⇒None，审计行该列留 NULL）。

    ``session=None`` 时惰性取 ``db.session()``（无应用上下文⇒空，软失败不
    raise）；``min_prompt_version`` 数字尾缀闸：current<required 的行跳过，
    任一侧不可解析 fail-open（可用性优先）。
    """
    key = (purpose or "").strip()
    if not purpose_allowed(key):
        return [], None
    if session is None:
        try:
            from flask import has_app_context

            if not has_app_context():
                return [], None
            from fde_api.extensions import db

            session = db.session()
        except Exception:  # noqa: BLE001 - overlay 设施故障不阻塞业务
            return [], None
    try:
        from sqlalchemy import select

        from fde_api.workbench.models import PromptOverlay

        rows = session.scalars(
            select(PromptOverlay)
            .where(
                PromptOverlay.purpose_key == key,
                PromptOverlay.status == "published",
            )
            .order_by(PromptOverlay.created_at.asc(), PromptOverlay.id.asc())
        ).all()
        current = version_suffix(prompt_version)
        fragments: list[str] = []
        payload_ids: list[str] = []
        payload_shas: list[str] = []
        for row in rows:
            required = version_suffix(row.min_prompt_version)
            if (
                required is not None
                and current is not None
                and current < required
            ):
                continue
            fragments.append(str(row.fragment))
            payload_ids.append(str(row.id))
            payload_shas.append(str(row.content_sha256))
        if not fragments:
            return [], None
        return fragments, {
            "overlay_ids": payload_ids,
            "overlay_sha256": payload_shas,
        }
    except Exception:  # noqa: BLE001 - overlay 设施故障不阻塞业务
        logger.warning("prompt overlay load failed purpose=%s", key, exc_info=True)
        return [], None


def resolve_base_prompt_for_purpose(purpose_key: str) -> tuple[str, str | None]:
    """按 purpose_key 解析 prompt_registry 中对应的静态基座提示词正文与版本号。

    用于发布前 n-gram 防洗稿比对（五件套②）与审批面并排呈现（五件套③）。
    未命中或模块导入异常回落空串，不修改注册表常量本体。
    """
    import importlib

    from fde_api.ai.prompt_registry import PROMPT_REGISTRATIONS

    key = (purpose_key or "").strip()
    for reg in PROMPT_REGISTRATIONS:
        if reg.key.replace(".", "_") == key:
            try:
                mod = importlib.import_module(reg.module)
                value = getattr(mod, reg.constant, "")
                return (str(value) if isinstance(value, str) else "", reg.version)
            except Exception:  # noqa: BLE001
                return ("", reg.version)
    return ("", None)


def preview_overlay_effect(
    purpose_key: str,
    fragment: str,
    *,
    session: Any | None = None,
) -> dict[str, Any]:
    """注入闸五件套③：生成审批面并排呈现的「基座提示词 vs 注入终文＋近 30 天调用量」。"""
    from datetime import UTC, datetime, timedelta

    key = (purpose_key or "").strip()
    base_prompt, prompt_version = resolve_base_prompt_for_purpose(key)
    existing_fragments, _ = load_overlays(key, prompt_version=prompt_version, session=session)
    candidate_clean = (fragment or "").strip()
    merged_fragments = [*existing_fragments, *([candidate_clean] if candidate_clean else [])]
    effective_prompt = apply_overlays_to_system_prompt(base_prompt, merged_fragments) or ""
    violation = validate_overlay_fragment(candidate_clean) if candidate_clean else "empty_fragment"
    overlap = ngram_overlap_ratio(candidate_clean, base_prompt) if base_prompt and candidate_clean else 0.0

    calls_30d = 0
    active_session = session
    if active_session is None:
        try:
            from flask import has_app_context

            if has_app_context():
                from fde_api.extensions import db

                active_session = db.session()
        except Exception:  # noqa: BLE001
            active_session = None
    if active_session is not None:
        try:
            from sqlalchemy import func, select

            from fde_api.workbench.models import AICallAudit

            cutoff = datetime.now(UTC) - timedelta(days=30)
            count = active_session.scalar(
                select(func.count())
                .select_from(AICallAudit)
                .where(
                    AICallAudit.purpose == key,
                    AICallAudit.created_at >= cutoff,
                )
            )
            calls_30d = int(count or 0)
        except Exception:  # noqa: BLE001
            calls_30d = 0

    return {
        "purpose_key": key,
        "purpose_allowed": purpose_allowed(key),
        "prompt_version": prompt_version,
        "base_prompt": base_prompt,
        "existing_overlay_count": len(existing_fragments),
        "candidate_fragment": candidate_clean,
        "effective_prompt": effective_prompt,
        "syntax_violation": violation,
        "ngram_overlap_ratio": round(overlap, 4),
        "ngram_blocked": overlap > MAX_NGRAM_OVERLAP_RATIO,
        "calls_last_30d": calls_30d,
    }

