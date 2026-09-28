from fde_api.ai.industry_template_prompt import build_chat_messages, build_generation_messages


def test_company_name_is_enough_to_start_a_reviewable_draft():
    messages = build_chat_messages(
        [{"role": "user", "content": "广东华翊智能科技有限公司"}],
        [{"module_key": "pre_diagnosis", "name": "预诊断"}],
    )

    system_prompt = messages[0]["content"]
    assert "企业名称或一句可识别的业务描述" in system_prompt
    assert "最多询问一个关键问题" in system_prompt
    assert "不得重复询问已提供的信息" in system_prompt


def test_generation_can_skip_research_forms_when_user_does_not_need_them():
    messages = build_generation_messages(
        [{"role": "user", "content": "只要预调研和调研模块，调研表不需要 AI 生成"}],
        {"enterprise": "示例制造企业"},
        [{"module_key": "pre_diagnosis", "name": "预调研"}, {"module_key": "diagnosis", "name": "调研"}],
    )

    system_prompt = messages[0]["content"]
    assert "research_definition 必须为 null" in system_prompt
    assert "不得擅自补充其他模块" in system_prompt
