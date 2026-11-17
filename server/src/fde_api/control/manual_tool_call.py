"""S-SERV A 案（批5 决策单，2026-11-18 P1「全部批准」）：手动工具调用档的
请求构造与响应解析。

评测实证（docs/ai-fde/09 §4.2 四轮决定性探测）：Ollama 系 serving 的原生
工具解析器对结构破损的 tool-call JSON **静默整段吞**（token 记账在、零
emission、done=stop）——即 v1 35% 空返的本质；qwen3 在复杂候选上产出
破损 JSON（多处未闭合 ``{`` + 收尾漏 closer）的概率可观。手动档把工具
调用降到**文本面**：剥 ``tools``、格式指令随 system 注入、响应按
``<tool_call>`` 文本块自解析（tolerant 链：直解析→括号平衡修复→尾逗号
清理）——文本面永不被 serving 解析器吞；破损可见、可修、计入测量。

循环/审批/审计面零变化（ai_tool_loop 消费本模块的纯函数输出，兼容形
``tool_calls`` 与原生响应同构）。
"""
from __future__ import annotations

import json
import re
from typing import Any

_TOOL_CALL_RE = re.compile(r"<tool_call>\s*(\{.*?\})\s*</tool_call>", re.DOTALL)
_TRAILING_COMMA_RE = re.compile(r",\s*([\]}])")


def tool_format_instruction(tool_schemas: list[dict[str, Any]]) -> str:
    """随 system 注入的格式指令：列出工具清单 + ``<tool_call>`` 块格式。

    工具 schema 以紧凑 JSON 随列（模型据此生成 name/arguments）——描述
    文本本身已按批5 G2 前置收口（无内嵌 JSON 示例，≤300 字符）。
    """
    lines = [
        "你可以使用下方列出的工具。需要调用工具时，只输出一个工具调用块，格式：",
        '<tool_call>{"name": "工具名", "arguments": {实参对象}}</tool_call>',
        "块外不要附加任何文字；工具结果会以 tool 消息回填后再继续。",
        "不需要工具时，直接用一两句话回答。",
        "可用工具：",
    ]
    for schema in tool_schemas:
        function = (schema.get("function") or {}) if isinstance(schema, dict) else {}
        name = str(function.get("name") or "")
        if not name:
            continue
        description = str(function.get("description") or "")
        parameters = function.get("parameters") or {}
        line = f"- {name}: {description}"
        props = (parameters or {}).get("properties") or {}
        if props:
            # 类型提示随列（v3 作废根因修复：只列参数名丢了 array 等类型
            # 信息，模型把 proposed_json 输出成字符串被 gateway 422——
            # 结构形状提示是实参形态正确的必要条件）
            parts = []
            for key, spec in props.items():
                type_hint = ""
                if isinstance(spec, dict):
                    type_hint = str(spec.get("type") or "")
                    if type_hint == "array":
                        items = spec.get("items") or {}
                        item_type = str(items.get("type") or "")
                        type_hint = f"array of {item_type}" if item_type else "array"
                parts.append(f"{key}({type_hint})" if type_hint else str(key))
            line += "；参数(类型): " + ", ".join(parts)
        lines.append(line)
    return "\n".join(lines)


def _repair_json_brackets(raw: str) -> str | None:
    """括号栈扫描修复：错配 closer 前插入期望 closer（可多层）；结尾补齐
    未闭合括号与截断字符串。

    qwen3 实测破损形态（docs/ai-fde/09 §4.2）：多处多余未闭合 ``{`` +
    收尾漏 closer——修复=逐字符重构造输出，错配 closer 处先闭掉栈顶的
    多余 opener（插入其 closer）直到栈顶与本 closer 匹配。修复失败
    （closer 无对应 opener）返回 None——由调用方走 tolerant 链下一跳
    或降级，不伪造成功。
    """
    stack: list[str] = []
    out: list[str] = []
    in_str = False
    esc = False
    expected = {"}": "{", "]": "["}
    closes = {"{": "}", "[": "]"}
    for ch in raw:
        if esc:
            out.append(ch)
            esc = False
            continue
        if in_str:
            out.append(ch)
            if ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
            out.append(ch)
        elif ch in "{[":
            stack.append(ch)
            out.append(ch)
        elif ch in "}]":
            want = expected[ch]
            # 错配：先插入 closers 闭掉栈顶多余 opener（可多层），
            # 直到栈顶与本 closer 匹配；栈空则本 closer 无主 → 修复失败
            while stack and stack[-1] != want:
                out.append(closes[stack.pop()])
            if not stack:
                return None
            stack.pop()
            out.append(ch)
        else:
            out.append(ch)
    if in_str:
        out.append('"')
    # 补齐剩余未闭合括号（收尾漏 closer 形态）
    out.extend(closes[opener] for opener in reversed(stack))
    return "".join(out)


def json_loads_tolerant(raw: str) -> dict[str, Any] | None:
    """tolerant 解析链：直解析 → 括号修复 → 尾逗号清理 → 组合。

    全败返回 None（不抛、不伪造）；调用方据 None 走重试/降级。
    """
    attempts = [raw]
    repaired = _repair_json_brackets(raw)
    if repaired is not None:
        attempts.append(repaired)
    attempts.append(_TRAILING_COMMA_RE.sub(r"\1", raw))
    if repaired is not None:
        attempts.append(_TRAILING_COMMA_RE.sub(r"\1", repaired))
    for attempt in attempts:
        try:
            data = json.loads(attempt)
        except (ValueError, RecursionError):
            continue
        if isinstance(data, dict):
            return data
    return None


def parse_tool_call_blocks(text: str) -> tuple[list[dict[str, Any]], str]:
    """从模型文本中解析全部 ``<tool_call>`` 块 → 兼容形 tool_calls。

    返回 ``(calls, residue)``：calls 元素与原生响应 ``tool_calls`` 同构
    （``{"id","type","function":{"name","arguments(json-str)"}}``）；
    residue=块外文本（块解析失败时保留原文，不伪造成功）。
    """
    calls: list[dict[str, Any]] = []

    def _replace(match: re.Match[str]) -> str:
        data = json_loads_tolerant(match.group(1))
        if data is None:
            return match.group(0)  # 保留原文：破损可见、计入测量
        name = str(data.get("name") or "")
        if name:
            calls.append({
                "id": f"manual_call_{len(calls)}",
                "type": "function",
                "function": {
                    "name": name,
                    "arguments": json.dumps(data.get("arguments") or {}, ensure_ascii=False),
                },
            })
            return ""
        return match.group(0)

    residue = _TOOL_CALL_RE.sub(_replace, text)
    return calls, residue
