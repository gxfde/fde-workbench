"""上下文脱敏渲染器（goal-d4，技术实施方案 §5 红线段）。

服务端负责把「能进沙箱的事实」渲染成任务上下文：只写项目代号 + 已确认
ProblemItem（带 source_refs）+ 模板骨架 + 知识检索片段；真相层路径、真实
客户名、凭证原文永不出现。两道闸：

1. 模式遮蔽（自动）：Windows 盘符路径 / PEM 私钥 / 常见 API 令牌 →
   ``[REDACTED_*]`` 占位（原文绝不进渲染产物）。
2. 术语熔断（fail-closed）：配置的禁区词（真实客户名等，
   ``FDE_AGENT_FORBIDDEN_TERMS``）在任何输入片段命中 →
   :class:`SanitizationError`，run 拒绝发起——宁可不跑，不赌脱敏。

CI 脱敏断言：毒化输入渲染后 grep 真实客户名/盘符/凭证模式零命中
（tests/test_agent_context_sanitization.py，技术文档 §5「gitleaks 旁再
加一条脱敏断言」）。
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

# Windows 盘符路径（C:\… 与 C:/… 两种写法）→ [REDACTED_PATH]
_DRIVE_PATH = re.compile(r"[A-Za-z]:[\\/][^\s\"'<>|*]*")
# PEM 私钥整块 → [REDACTED_KEY]
_PEM_KEY = re.compile(
    r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----.*?-----END [A-Z0-9 ]*PRIVATE KEY-----",
    re.DOTALL,
)
# 常见 API 令牌形态（OpenAI/ GitHub / Slack / AWS）→ [REDACTED_TOKEN]
_API_TOKEN = re.compile(
    r"\b(?:sk-[A-Za-z0-9_-]{8,}|gh[pousr]_[A-Za-z0-9]{16,}"
    r"|xox[baprs]-[A-Za-z0-9-]{10,}|AKIA[0-9A-Z]{16})\b"
)

REDACTED_PATH = "[REDACTED_PATH]"
REDACTED_KEY = "[REDACTED_KEY]"
REDACTED_TOKEN = "[REDACTED_TOKEN]"

# 沙箱内纪律摘要：spawn 段随任务书写进 workspace 的 AGENTS.md（红线原地生效）
SANDBOX_AGENT_DISCIPLINE = """# 沙箱纪律（不可协商）

1. 任务上下文已脱敏：只含项目代号与已确认事实；不要尝试推断或拼接真实客户身份。
2. 你只产出草稿：任何「确认/拍板/导出」类动作都由人工完成，你无权也无入口。
3. 工具白名单外的调用一律被拒绝并留痕（agent_tool_calls.denied）；不要重试越权调用。
4. 产物写到 /workspace/output，并在 manifest.json 里为每个产物标注 source_refs。
5. 超时与预算熔断是硬边界：到达上限会被强制终止，产物可能作废。
"""


class SanitizationError(RuntimeError):
    """脱敏闸门错误（fail-closed）：code ∈ forbidden_term_detected/invalid_context_item。"""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class RenderedContext:
    """渲染产物：text 写入 workspace/context.md，problem_refs 供产物校验对账。"""

    text: str
    problem_refs: tuple[str, ...]
    redactions: int


def redact_patterns(text: str) -> tuple[str, int]:
    """模式遮蔽：盘符路径/PEM/令牌 → 占位符；返回 (新文本, 遮蔽次数)。"""
    hits = 0

    def _swap(pattern: re.Pattern[str], replacement: str, value: str) -> str:
        nonlocal hits
        value, count = pattern.subn(replacement, value)
        hits += count
        return value

    text = _swap(_PEM_KEY, REDACTED_KEY, text)
    text = _swap(_API_TOKEN, REDACTED_TOKEN, text)
    text = _swap(_DRIVE_PATH, REDACTED_PATH, text)
    return text, hits


def assert_sanitized(text: str, forbidden_terms: Sequence[str]) -> None:
    """禁区词熔断：命中即抛（fail-closed），绝不静默放行。"""
    lowered = text.lower()
    for term in forbidden_terms:
        needle = term.strip().lower()
        if needle and needle in lowered:
            raise SanitizationError(
                "forbidden_term_detected",
                "上下文命中禁区词，run 拒绝发起；请核对数据来源后重试。",
            )


def _clean(value: object, forbidden_terms: Sequence[str]) -> tuple[str, int]:
    if not isinstance(value, str):
        raise SanitizationError("invalid_context_item", "上下文条目必须是字符串。")
    redacted, hits = redact_patterns(value)
    assert_sanitized(redacted, forbidden_terms)
    return redacted, hits


def render_masked_context(
    *,
    project_code: str,
    agent_name: str,
    capability: str,
    confirmed_items: Sequence[Mapping[str, object]],
    template_skeleton: str = "",
    knowledge_snippets: Sequence[Mapping[str, object]] = (),
    forbidden_terms: Sequence[str] = (),
) -> RenderedContext:
    """渲染脱敏任务上下文（技术文档 §5：代号 + 确认问题 + 骨架 + 知识片段）。

    confirmed_items 为已确认 ProblemItem 字典列表（text/classification/
    source_refs[/severity/module]）；未确认条目直接丢弃（AI 不得看到未拍板
    内容）。所有动态文本过模式遮蔽 + 禁区词熔断。
    """
    total_hits = 0
    lines: list[str] = []
    refs: list[str] = []

    code, hits = _clean(project_code, forbidden_terms)
    total_hits += hits
    agent, hits = _clean(agent_name, forbidden_terms)
    total_hits += hits
    cap, hits = _clean(capability, forbidden_terms)
    total_hits += hits
    lines.extend(
        (
            "# 任务上下文（脱敏）",
            "",
            f"- 项目代号: {code}",
            f"- 执行智能体: {agent}（能力: {cap}）",
            "",
            SANDBOX_AGENT_DISCIPLINE,
            "## 已确认业务问题",
            "",
        )
    )

    included = 0
    for item in confirmed_items:
        if item.get("confirmed") is not True:
            continue
        text, hits = _clean(item.get("text"), forbidden_terms)
        total_hits += hits
        classification, hits = _clean(item.get("classification", ""), forbidden_terms)
        total_hits += hits
        raw_refs = item.get("source_refs")
        item_refs = []
        for ref in raw_refs if isinstance(raw_refs, list) else []:
            if not isinstance(ref, str):
                continue
            # goal-c CR-017：引用与正文同尺——source_ref 是数据不是纯标识，
            # 可能携带盘符/凭证形态（毒化时点不同来源同一路径）：先过模式遮蔽，
            # 再进 problem_refs（产物校验对账只比对已遮蔽形态，两侧同规）。
            masked_ref, ref_hits = redact_patterns(ref)
            total_hits += ref_hits
            if masked_ref not in refs:
                refs.append(masked_ref)
                item_refs.append(masked_ref)
        extras = ""
        severity = item.get("severity")
        module = item.get("module")
        if isinstance(severity, str) and severity:
            extras += f"（severity={severity}）"
        if isinstance(module, str) and module:
            extras += f"（module={module}）"
        rendered_refs = ",".join(item_refs) if item_refs else "无引用"
        lines.append(f"- [{rendered_refs}] {text}（{classification}）{extras}")
        included += 1
    if included == 0:
        lines.append("-（暂无已确认业务问题）")

    lines.extend(("", "## 模板骨架", ""))
    if template_skeleton:
        skeleton, hits = _clean(template_skeleton, forbidden_terms)
        total_hits += hits
        lines.append(skeleton)
    else:
        lines.append("（未提供模板骨架）")

    lines.extend(("", "## 知识片段", ""))
    if knowledge_snippets:
        for snippet in knowledge_snippets:
            snippet_id, hits = _clean(snippet.get("id", ""), forbidden_terms)
            total_hits += hits
            snippet_text, hits = _clean(snippet.get("text"), forbidden_terms)
            total_hits += hits
            lines.append(f"[{snippet_id}] {snippet_text}")
    else:
        lines.append("（未检索到知识片段）")

    text = "\n".join(lines).rstrip() + "\n"
    # 终检：整篇再过一次禁区词（任何路径漏进来的都拦在 workspace 落盘前）
    assert_sanitized(text, forbidden_terms)
    return RenderedContext(text=text, problem_refs=tuple(refs), redactions=total_hits)
