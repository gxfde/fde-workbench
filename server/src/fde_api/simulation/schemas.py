"""场景内容的字段契约与装载视图定义（V3.2 G2）。

本模块只放**常量与纯函数**：视图键集合、禁用泄漏键、阶段枚举、字段规范化。
任何形状校验规则放 ``scenarios/validator.py``，装载与切分放 ``scenarios/loader.py``。

**装载视图（G1 §4.3 的技术落点）**：

============  ==========================================================
视图          可见内容
============  ==========================================================
``tester``    被测方（FDE 顾问 / 实施 / 验收）初始可见面：客户**初始简报**、
              客户自述的已知系统与**既定约束**。其余一切（隐藏事实、客户画像、
              参考答案、Rubric、故障注入、虚拟种子数据）**不可见**——必须靠追问
              与执行获得。
``customer``  客户模拟器可见面：客户侧全部真相（画像/简报/隐藏事实/变体覆盖/
              故障注入/虚拟种子数据）。**不含**参考答案与 Rubric。
``judge``     评分方可见面：``content`` + ``reference`` 全量。
============  ==========================================================
"""
from __future__ import annotations

from typing import Any

# ---------------------------------------------------------------------------
# 视图
# ---------------------------------------------------------------------------

SCENARIO_VIEWS = ("tester", "customer", "judge")

# Tester View 允许出现的顶层键（白名单，非黑名单——新增顶层键默认对被测方不可见，
# 避免「顺手把答案放进 content」这类泄漏在结构层被静默放行）
TESTER_VIEW_KEYS = ("brief", "known_systems", "constraints")

# Judge View 专属键（reference_json 内）：被测方与客户模拟器一律不可见
ANSWER_SIDE_KEYS = frozenset(
    {
        "reference",
        "rubric",
        "must_identify",
        "must_avoid",
        "must_produce",
        "expected_outcomes",
        "acceptance_criteria",
        "reference_solution_outline",
        "reference_workflow",
    }
)

# 客户侧专属键（content_json 内）：被测方初始不可见（须靠追问/执行获得）
CUSTOMER_SIDE_KEYS = frozenset(
    {
        "hidden",
        "variant_overrides",
        "fault_injection",
        "seed_data",
        "customer_profile",
        "misleading_request",
    }
)

# 递归泄漏检查的禁用键集合（按视图分别适用，见 loader.load_view）
LEAK_FORBIDDEN_KEYS = ANSWER_SIDE_KEYS | CUSTOMER_SIDE_KEYS

# ---------------------------------------------------------------------------
# 内容结构
# ---------------------------------------------------------------------------

# 隐藏事实的披露阶段（G1 §5.3 状态机）
DISCLOSURE_STAGES = (
    "setup",
    "interview",
    "analysis",
    "design",
    "implementation",
    "late",
)

# content_json 顶层必需键
CONTENT_REQUIRED_KEYS = (
    "case_code",
    "customer_profile",
    "visible",
    "hidden",
    "misleading_request",
)

# visible 段必需键
VISIBLE_REQUIRED_KEYS = ("initial_brief", "known_systems", "constraints")

# hidden 段必需键
HIDDEN_REQUIRED_KEYS = ("facts",)

# hidden.facts[] 元素必需键
HIDDEN_FACT_REQUIRED_KEYS = ("fact_id", "text", "disclosure_stage")

# reference_json 顶层必需键
REFERENCE_REQUIRED_KEYS = (
    "expected_outcomes",
    "acceptance_criteria",
    "rubric",
)

# rubric 三桶
RUBRIC_REQUIRED_KEYS = ("must_identify", "must_avoid", "must_produce")

# 故障注入的错误类型（G3 用）
FAULT_ERRORS = (
    "sim_tool_timeout",
    "sim_permission_denied",
    "sim_data_conflict",
    "sim_tool_crash",
)

# 标签规范化：去空白、去重、保序、限长
MAX_TAGS = 12
MAX_TAG_LENGTH = 32


def normalize_tags(value: Any) -> list[str]:
    """标签规范化：只接受字符串列表，去空白/去重/保序，截断到上限。

    非列表一律视为空列表（不猜、不放宽）——非法形状由 validator 报错，此处
    只保证写入侧的值域安全。
    """
    if not isinstance(value, list):
        return []
    seen: set[str] = set()
    out: list[str] = []
    for item in value:
        if not isinstance(item, str):
            continue
        tag = item.strip()
        if not tag or tag in seen:
            continue
        seen.add(tag)
        out.append(tag[:MAX_TAG_LENGTH])
        if len(out) >= MAX_TAGS:
            break
    return out


def contains_forbidden_keys(payload: Any, forbidden: frozenset[str] = LEAK_FORBIDDEN_KEYS) -> list[str]:
    """递归检查 payload 是否含禁用键（泄漏自检）。

    返回**命中路径**列表（点号路径），空列表 = 未泄漏。键名大小写敏感
    （场景 JSON 键约定为 snake_case，大小写变体视为不同键——不猜）。
    """
    hits: list[str] = []

    def walk(node: Any, path: str) -> None:
        if isinstance(node, dict):
            for key, child in node.items():
                child_path = f"{path}.{key}" if path else str(key)
                if key in forbidden:
                    hits.append(child_path)
                walk(child, child_path)
        elif isinstance(node, list):
            for index, child in enumerate(node):
                walk(child, f"{path}[{index}]")

    walk(payload, "")
    return hits
