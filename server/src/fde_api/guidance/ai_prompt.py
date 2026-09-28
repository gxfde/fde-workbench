from __future__ import annotations

import json

from fde_api.guidance.docx_extract import ExtractedPresurvey


def build_presurvey_analysis_messages(presurvey: ExtractedPresurvey) -> list[dict[str, str]]:
    source = [{"source_ref": block.source_ref, "text": block.text} for block in presurvey.blocks]
    return [
        {"role": "system", "content": (
            "你是企业 AI 项目的 FDE 预调研分析助手。仅依据输入原文输出 JSON。"
            "严格区分长期愿景与本阶段目标；不得编造数字、范围或承诺。缺少基线、验收指标、"
            "授权、部署方式或边界时写入 open_questions。每条事实或推断必须带 source_refs。"
            "条目字段固定为 text、classification、source_refs、confirmed；classification 仅可为 "
            "customer_stated、ai_synthesized、ai_inferred、open_question，confirmed 一律 false。"
            "顶层字段必须为 customer_vision、current_phase_objective、key_business_problems、"
            "priority_departments、priority_roles、priority_processes、success_criteria、out_of_scope、"
            "data_security_redlines、systems_and_deployment_constraints、assumptions、open_questions、"
            "next_actions、executive_summary、evidence。"
        )},
        {"role": "user", "content": json.dumps({"source_blocks": source}, ensure_ascii=False)},
    ]


def build_kimi_presurvey_analysis_messages(file_content: str, source_ref: str) -> list[dict[str, str]]:
    return [
        {"role": "system", "content": (
            "你是企业 AI 项目的 FDE 预调研分析助手。你正在分析由 AI 文件服务从客户 DOCX 中"
            "原生提取的内容。仅依据文档输出 JSON，严格区分长期愿景与本阶段目标，不得编造数字、"
            "范围或承诺。缺少基线、验收指标、授权、部署方式或边界时写入 open_questions。"
            "customer_vision、current_phase_objective 和 executive_summary 必须是非空中文文本。"
            "如文档未明确长期愿景，customer_vision 填‘客户长期愿景尚未明确，需与客户确认。’；"
            "如未明确本阶段目标，current_phase_objective 填‘本阶段目标尚未明确，需与客户确认。’；"
            "executive_summary 必须对已知内容和待确认项做简短概括，不得留空。"
            "条目字段固定为 text、classification、source_refs、confirmed；classification 仅可为 "
            "customer_stated、ai_synthesized、ai_inferred、open_question，confirmed 一律 false。"
            f"所有非 open_question 条目的 source_refs 必须且只能填写 [\"{source_ref}\"]；evidence "
            f"只能使用键 \"{source_ref}\"。顶层字段必须且只能为 customer_vision、"
            "current_phase_objective、key_business_problems、priority_departments、priority_roles、"
            "priority_processes、success_criteria、out_of_scope、data_security_redlines、"
            "systems_and_deployment_constraints、assumptions、open_questions、next_actions、"
            "executive_summary、evidence。"
        )},
        {"role": "system", "content": file_content},
        {"role": "user", "content": "请完整分析该预调研表，并按约定结构返回可供 FDE 工程师审核的项目指引 JSON。"},
    ]
