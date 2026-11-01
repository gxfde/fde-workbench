"""翻译器 AI 管道的消息构造（goal-d9，PRD §3.2 P3）。

原文块只有表单三段：诉求原话（translator:vision）/ 阶段目标
（translator:objective）/ 客户画像（translator:profile）。source_refs 白名
单即这三个引用——AI 每条事实/推断都必须落到表单原文，无处可编造。
"""
from __future__ import annotations

import json


def build_translator_messages(
    *,
    vision: str,
    phase_objective: str,
    profile_text: str,
) -> list[dict[str, str]]:
    source = [
        {"source_ref": "translator:vision", "text": vision},
        {"source_ref": "translator:objective", "text": phase_objective},
        {"source_ref": "translator:profile", "text": profile_text},
    ]
    return [
        {"role": "system", "content": (
            "你是 FDE 交付工作台的翻译器助手：把创业者/售前听客户讲出的模糊"
            "诉求，翻译成结构化项目指引草稿。仅依据输入原文输出 JSON，不得"
            "编造数字、范围或承诺。严格区分长期愿景与本阶段目标；缺少基线、"
            "验收指标、授权、部署方式或边界时写入 open_questions。每条事实或"
            "推断必须带 source_refs（只能引用输入给出的 source_ref）。条目字段"
            "固定为 text、classification、source_refs、confirmed；classification"
            " 仅可为 customer_stated、ai_synthesized、ai_inferred、open_question，"
            "confirmed 一律 false（AI 只出草稿，确认是人的动作）。仅"
            " key_business_problems 条目可附 severity（high/medium/low，按业务"
            "影响判断）与 module（交付模块英文键，仅在原文可判断时给出，否则"
            "省略）。顶层字段必须为 customer_vision、current_phase_objective、"
            "key_business_problems、priority_departments、priority_roles、"
            "priority_processes、success_criteria、out_of_scope、"
            "data_security_redlines、systems_and_deployment_constraints、"
            "assumptions、open_questions、next_actions、executive_summary、"
            "evidence。evidence 的键也只能是输入给出的 source_ref。"
        )},
        {"role": "user", "content": json.dumps({"source_blocks": source}, ensure_ascii=False)},
    ]
