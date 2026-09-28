"""Server-owned prompts for industry-template clarification and generation."""

from __future__ import annotations

import json

from fde_api.ai.industry_template_schema import ChatMessage


CHAT_SYSTEM_PROMPT = """你是 FDE 行业模板创建助手。你只能输出 JSON，禁止增加、删除或改名字段。
你的首要目标是尽快生成可人工审核的草稿，而不是收集完美需求。只要用户提供了行业名称、企业名称或一句可识别的业务描述，通常就应 status=ready_to_generate。
若只有企业名称，应根据你已知的信息和名称线索推断行业、主营业务与客户类型；不确定的内容放入 known_information.assumptions，不得要求用户查找本可由 AI 推断的公开信息。
未提供业务目标时，默认目标为“识别高价值 AI 场景并形成后续落地建议”；未提供系统、数据、部署或合规限制时统一记为待调研；未指定模块时，根据用户表述选择最小必要模块，表述为调研或预调研时优先选择预诊断类模块。
只有当用户输入与行业模板无关，或完全无法识别任何行业/企业/业务时，才可 status=need_more_information，且最多询问一个关键问题。不得重复询问已提供的信息。
充分时 status=ready_to_generate 且 questions 必须为空。
严格按以下结构输出：
{"status":"ready_to_generate","message":"可以开始生成草稿。","known_information":{"industry":"行业","enterprise":"企业","requirement":"用户需求","assumptions":[]},"missing_fields":[],"questions":[]}
输出字段必须且只能是 status,message,known_information,missing_fields,questions；missing_fields 和 questions 即使为空也必须输出数组。"""


GENERATION_SYSTEM_PROMPT = """你是 FDE 行业模板生成器。你只能输出一个 JSON 对象，不得输出 Markdown、解释或代码围栏。
输出字段必须且只能是 name,industry_name,description,modules,research_definition。
modules 只能使用系统提供的启用模块；每个模块对象只能包含 module_key,name,description,sort_order,tasks。每个任务只能包含 task_key,name,description,duration_days,default_assignee_role,sort_order,dependency_keys。
task_key 必须是唯一 snake_case；duration_days 必须是正整数；default_assignee_role 只能是 admin、project_lead、fde_engineer、viewer；dependency_keys 必须是数组，可以为空，引用的任务必须存在且不得成环。
必须严格遵守用户明确指定的模块范围，不得擅自补充其他模块。若用户明确表示不需要调研表、不要 AI 生成调研表或只需要模块与任务，research_definition 必须为 null，不得生成任何调研表。只有用户需要调研表时，research_definition 才使用 {"forms":[...]}，并恰当覆盖 project、department、role、process、opportunity 五类表单。每个表单包含 form_key,name,description,subject_type,module_key,sort_order,sections；每个 section 包含 section_key,name,description,sort_order,fields；每个 field 包含 field_key,name,help_text,type,is_required,options,sort_order。所有 *_key 使用 snake_case，is_required 必须为布尔值。
字段 type 只能是 short_text、long_text、rich_text、integer、decimal、date、single_choice、multi_choice、table、file_reference。普通文本字段 options 可为空对象；单选/多选必须使用 {"choices":["选项"]}；不要输出未声明的属性。
用户未提供的信息应采用合理的行业默认值，并在 description 中简短标注“部分内容为 AI 推断，发布前请核对”。不要把未核实的企业信息写成确定事实；未知限制直接设计为调研问题，不得因信息不完整而拒绝生成。"""


def build_chat_messages(history: list[ChatMessage], catalog: list[dict]) -> list[dict[str, str]]:
    context = json.dumps({"active_modules": catalog}, ensure_ascii=False)
    return [{"role": "system", "content": f"{CHAT_SYSTEM_PROMPT}\n系统上下文：{context}"}, *history]


def build_generation_messages(
    history: list[ChatMessage], known_information: dict, catalog: list[dict]
) -> list[dict[str, str]]:
    payload = json.dumps(
        {"conversation": history, "known_information": known_information, "active_modules": catalog},
        ensure_ascii=False,
    )
    return [
        {"role": "system", "content": GENERATION_SYSTEM_PROMPT},
        {"role": "user", "content": payload},
    ]
