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
    "min_difficulty": "high",  # T4：高难度 run 召集本模板时自动升 full 档 + 加座
    "persona_addons": ["persona:finance", "persona:legal", "persona:customer_it"],
    "sections": ["consensus", "disputes", "todos"],  # 三段式
    "description": "S2-lite 产物评审：守卫 + 1 模块智能体，2 话轮；纪要三段式封存后 T2 门放行。",
}

_T1_LITE: dict[str, Any] = {
    "template_id": "T1-lite",
    "name": "计划评审会（lite）",
    "gate": "T1",  # 计划评审强制门（总纲 §2.2 T1）：start_run 带 solution_id
    # 的前置闸——无已封存 T1 纪要侧链该 solution 则 409 t1_gate_open（状态机级）
    "gate_tier": "lite",
    "turn_budget": GATE_TIER_TURN_BUDGETS["lite"],
    "attendees": ["quality_guard", "module_agent"],
    "trigger": "mandatory",
    "min_difficulty": "high",
    "persona_addons": ["persona:finance", "persona:legal", "persona:customer_it"],
    "sections": ["consensus", "disputes", "todos"],
    "description": "T1 计划评审（S2 模板等价，UM-1 试点 lite 档）：方案骨架/任务书过审后才进入产物生成。",
}

_T5_LITE: dict[str, Any] = {
    "template_id": "T5-lite",
    "name": "降级恢复补审会（lite）",
    "gate": "T5",  # 降级恢复补审强制门（总纲 §2.2 T5）：家族含 L1 run 时
    # T2 门只认 T5 纪要——降级期间产物不自动放行（自动交付 §3.3 纪律）
    "gate_tier": "lite",
    "turn_budget": GATE_TIER_TURN_BUDGETS["lite"],
    "attendees": ["quality_guard", "module_agent"],
    "trigger": "mandatory",
    "min_difficulty": "high",
    "persona_addons": ["persona:finance", "persona:legal", "persona:customer_it"],
    "sections": ["consensus", "disputes", "todos"],
    "description": "T5 降级恢复补审：L1 恢复后的产物补审会，补审纪要封存后恢复通道放行。",
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

# ---------------------------------------------------------------------------
# 场景模板 S1–S6（goal-d7，PartyMode §2.1 场景矩阵；M1 判定源）。
# trigger=manual：场景会对齐交付阶段，不作强制门证据（门语义独占 T 系模板，
# goal-d7 报告 §二 决议 1）；班底与议题是预设模板（蔡工可改），D10 蒸馏源
# 标注进 distill_source（内容审定交接随轮交付，D10 五项待拍板清单同附）。
# 到场表键：quality_guard / module:<key> / persona:<key>；S6 空表=自由席。
# ---------------------------------------------------------------------------

_S1_DIAGNOSIS: dict[str, Any] = {
    "template_id": "S1-diagnosis",
    "name": "需求诊断会",
    "gate": None,
    "gate_tier": "lite",
    "turn_budget": GATE_TIER_TURN_BUDGETS["lite"],
    "attendees": ["module:presales", "module:solution", "quality_guard", "module:knowledge"],
    "trigger": "manual",
    "min_difficulty": None,
    "sections": ["consensus", "disputes", "todos"],
    "distill_source": "D10：九卡·S1 预调研卡（进入条件→守卫清单）",
    "description": "售前访谈后：问题清单是否完整、source_refs 是否闭合、severity 定级是否合理。",
}

_S2_SOLUTION_REVIEW: dict[str, Any] = {
    "template_id": "S2-solution-review",
    "name": "方案评审会",
    "gate": None,
    "gate_tier": "std",
    "turn_budget": GATE_TIER_TURN_BUDGETS["std"],
    "attendees": [
        "module:solution",
        "module:pricing",
        "module:deployment",
        "module:acceptance",
        "quality_guard",
    ],
    "trigger": "manual",
    "min_difficulty": None,
    "sections": ["consensus", "disputes", "todos"],
    "distill_source": "D10：九卡·S4 方案卡 + 方案健康度字段",
    "description": "方案草稿后：模板覆盖率、报价档位合法性、SOP 偏离度、实施可行性。",
}

_S3_BUSINESS: dict[str, Any] = {
    "template_id": "S3-business-alignment",
    "name": "商务对齐会",
    "gate": None,
    "gate_tier": "lite",
    "turn_budget": GATE_TIER_TURN_BUDGETS["lite"],
    "attendees": ["module:pricing", "module:solution", "persona:finance", "persona:legal"],
    "trigger": "manual",
    "min_difficulty": None,
    "sections": ["consensus", "disputes", "todos"],
    "distill_source": "D10：报价卡核对要点（只收核对要点不收数值——数值禁区待拍板 ③）",
    "description": "报价确认前：付款里程碑、发票/合同主体、红线条款（角色卡视角受 PM-2 三层防火墙约束）。",
}

_S4_KICKOFF: dict[str, Any] = {
    "template_id": "S4-kickoff",
    "name": "交付启动会（Kickoff）",
    "gate": None,
    "gate_tier": "std",
    "turn_budget": GATE_TIER_TURN_BUDGETS["std"],
    "attendees": ["module:deployment", "module:acceptance", "module:presales", "persona:customer_it"],
    "trigger": "manual",
    "min_difficulty": None,
    "sections": ["consensus", "disputes", "todos"],
    "distill_source": "D10：九卡·S6/S7 实施卡（里程碑/责任人/入场条件）",
    "description": "交付启动前：里程碑、双方责任人、验收标准、入场条件。",
}

_S5_PREACCEPTANCE: dict[str, Any] = {
    "template_id": "S5-preacceptance",
    "name": "预验收会",
    "gate": None,
    "gate_tier": "std",
    "turn_budget": GATE_TIER_TURN_BUDGETS["std"],
    "attendees": ["module:acceptance", "quality_guard", "module:deployment"],
    "trigger": "manual",
    "min_difficulty": None,
    "sections": ["consensus", "disputes", "todos"],
    "distill_source": "D10：门禁验收表 G8/G9 行 + 验收单（证据核对段）",
    "description": "验收前：门禁证据 G1–G9 是否齐、差距项、补证待办。",
}

_S6_FREE: dict[str, Any] = {
    "template_id": "S6-free",
    "name": "自由评审会",
    "gate": None,
    "gate_tier": "lite",
    "turn_budget": GATE_TIER_TURN_BUDGETS["std"],
    "attendees": [],  # 空到场表 = 创业者自定义班底（自由席）
    "trigger": "manual",
    "min_difficulty": None,
    "sections": ["consensus", "disputes", "todos"],
    "distill_source": "D10：无固定来源（自由议题）",
    "description": "任意阶段：创业者自定义班底与议题的自由评审（不占用 agent 限额）。",
}

MEETING_TEMPLATES: dict[str, dict[str, Any]] = {
    "T1-lite": _T1_LITE,
    "T2-lite": _T2_LITE,
    "T3-adhoc": _T3_ADHOC,
    "T5-lite": _T5_LITE,
    "S1-diagnosis": _S1_DIAGNOSIS,
    "S2-solution-review": _S2_SOLUTION_REVIEW,
    "S3-business-alignment": _S3_BUSINESS,
    "S4-kickoff": _S4_KICKOFF,
    "S5-preacceptance": _S5_PREACCEPTANCE,
    "S6-free": _S6_FREE,
}

# 强制门模板键集（gate 语义独占面）：T4 升档/门判定只认这些模板
MANDATORY_GATE_TEMPLATE_IDS: frozenset[str] = frozenset(
    template_id for template_id, tpl in MEETING_TEMPLATES.items() if tpl["trigger"] == "mandatory"
)


def get_template(template_id: str) -> dict[str, Any] | None:
    return MEETING_TEMPLATES.get(template_id)


def list_templates() -> list[dict[str, Any]]:
    """模板列表（GET /meeting-templates 读数；键序稳定）。"""
    return [MEETING_TEMPLATES[key] for key in sorted(MEETING_TEMPLATES)]
