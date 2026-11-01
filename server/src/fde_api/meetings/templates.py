"""评审会模板注册表（goal-d5，技术实施方案 §1 S1-5 / §2 模板落地决议）。

技术文档 §2：「会议模板（S1–S6 + gate_tier）入 templates 体系或独立种子表，
实现时定」——本轮取常量注册表（心智沿 control/access.CAPABILITY_REQUIREMENTS）：
模板是门禁语义（强制门/话轮预算/到场表），不是内容数据，随代码评审演进；
内容蒸馏（D10：SOP 九卡/报价卡/门禁验收表）随 d7 S2 全模板落地。

三档门（总纲 UM-1 / PartyMode PM-5）：lite=2 / std=8 / full=12 轮。
T2-lite 随 d5 首发；goal-d6 增 T3-adhoc（智能体自主召集，U3：reason 必填、
计入纪要回链）；T1/T4/T5 与 std/full 随 d7（PM-1 内容蒸馏待蔡工审定）。
"""

from __future__ import annotations

from typing import Any

GATE_TIER_TURN_BUDGETS = {"lite": 2, "std": 8, "full": 12}

# 工具面白名单（U8/M4 d5 切片）：会中 agent 只读子集，恒等此二面；
# 写类工具一律 denied 落 agent_tool_calls（技术文档 §6「会中只读」）
MEETING_AGENT_TOOLS: frozenset[str] = frozenset({"meeting_convene", "meeting_get_minutes"})

# meeting_convene 单次召集计费（成本单位，与 agent token_cost 同口径累计到
# 触发 run——「只读发起；计费+占预算」，技术文档 §3.2）
MEETING_CONVENE_COST_UNITS = 2

# 每 run 召集限额（总纲 U7）
MEETING_CONVENE_LIMIT_PER_RUN = 2

_T2_LITE: dict[str, Any] = {
    "template_id": "T2-lite",
    "name": "产物评审会（lite）",
    "gate": "T2",  # 产物提交终审前的强制门（技术文档 §6 状态机钩子）
    "gate_tier": "lite",
    "turn_budget": GATE_TIER_TURN_BUDGETS["lite"],
    "attendees": ["quality_guard", "module_agent"],  # 守卫 + 1 模块智能体
    "trigger": "mandatory",
    "min_difficulty": None,
    "sections": ["consensus", "disputes", "todos"],  # 三段式
    "description": "S2-lite 产物评审：守卫 + 1 模块智能体，2 话轮；纪要三段式封存后 T2 门放行。",
}

_T3_ADHOC: dict[str, Any] = {
    "template_id": "T3-adhoc",
    "name": "自主评审会（adhoc）",
    "gate": "T3",  # 自主召集门：不产门证据（trigger=adhoc 不入 t2_gate_satisfied）
    "gate_tier": "lite",
    "turn_budget": GATE_TIER_TURN_BUDGETS["lite"],
    "attendees": ["quality_guard", "module_agent"],
    "trigger": "adhoc",
    "min_difficulty": None,
    "sections": ["consensus", "disputes", "todos"],
    # U3（总纲 §5）：自主召集必须给 reason，缺失即拒；reason 落
    # topic_refs["reason"]，经纪要回链（get_minutes → topic_refs）计入纪要
    "requires_reason": True,
    "description": "智能体自主召集的评审讨论会：须声明召集理由；adhoc 纪要不作强制门证据。",
}

MEETING_TEMPLATES: dict[str, dict[str, Any]] = {"T2-lite": _T2_LITE, "T3-adhoc": _T3_ADHOC}


def get_template(template_id: str) -> dict[str, Any] | None:
    return MEETING_TEMPLATES.get(template_id)


def list_templates() -> list[dict[str, Any]]:
    """模板列表（GET /meeting-templates 读数；键序稳定）。"""
    return [MEETING_TEMPLATES[key] for key in sorted(MEETING_TEMPLATES)]
