from __future__ import annotations

import json
from typing import Any


def build_ai_opportunity_messages(context: dict[str, Any]) -> list[dict[str, str]]:
    messages = [
        {
            "role": "system",
            "content": (
                "你是企业 AI 落地项目的 FDE 机会分析助手。只能依据提供的调研资料（已填调研表或备忘录）发现机会，"
                "不得臆造事实。user_guidance 是用户的初步想法或分析方向，可用于聚焦候选、补全问题和提出验证动作，"
                "但不能替代调研证据，不能将其当作已验证事实。guidance_source可作为用户想法的来源，必须注明待验证；只参考给出的来源，未提供的资料不可自行补充。"
                "输出 JSON 对象，根字段 candidates。每个候选必须包含 name、description、"
                "target_audience、priority(high/medium/low)、business_value_score、feasibility_score、"
                "data_readiness_score、risk_level(high/medium/low)、next_action、research_answers、evidence。"
                "research_answers 用于预填该候选的 AI 机会调研表，必须包含 current_state（现状描述）、"
                "pain_points（痛点/问题）、business_value（业务价值）、target_scenario（目标场景）、"
                "owner_role（负责人/角色）、technical_prereqs（技术前提）这 6 个字符串字段。内容必须依据调研表或备忘录；资料不足的字段应明确写明"
                "尚待确认的具体内容，不得臆造。此阶段只识别机会，不设计交付方案，不输出交付范围、交付物、验收标准或计划排期；这些内容由关联机会的方案设计承担。"
                "三个评分均为 1-5 整数。evidence 是数组，每项包含 form_id、form_name、field_key、"
                "question、answer_excerpt、reason。没有充分证据时返回空 candidates。最多 8 个候选，"
                "候选之间应去重，也不要重复已有机会。"
            ),
        },
        {
            "role": "user",
            "content": "请分析以下项目调研资料：\n" + json.dumps(context, ensure_ascii=False),
        },
    ]
    if context.get("expand") is False:
        messages[0]["content"] = (
            "你是仅格式整理器，不是机会分析顾问。任务只是从给定来源摘录原文并填入表单，禁止拓展、推理、补充建议或价值判断。"
            "每个非空字段必须逐字摘自 included_forms、included_memos 或 guidance_source 的 answers.value，不能润色、添加词语或拼接成新结论。"
            "原文未提及就输出空字符串，禁止填写‘待确认’‘可能’等解释。name也从原文摘取短标题。"
            "输出JSON对象candidates数组，最多8项；每项包含name、description、target_audience、next_action字符串；"
            "priority与risk_level固定medium，business_value_score、feasibility_score、data_readiness_score固定3（待人工评估）。"
            "research_answers只包含6个字符串字段：current_state现状、pain_points痛点、business_value价值、target_scenario场景、"
            "owner_role负责人、technical_prereqs技术前提。没有对应原文的字段为空，不能以常识补齐；不输出交付方案字段。"
            "evidence保留form_id、form_name、field_key、question、answer_excerpt、reason，answer_excerpt必须逐字摘录来源，"
            "reason填写‘原文摘录，待验证’。没有事实资料时，补充想法也可以作为待验证的原文来源。不调用工具。"
        )
    return messages
