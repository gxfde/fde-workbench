import pytest

from fde_api.ai.industry_template_schema import (
    AIContractError,
    parse_chat_decision,
    validate_chat_messages,
    validate_generated_template,
)


def field(key):
    return {
        "field_key": key,
        "name": key,
        "help_text": "",
        "type": "short_text",
        "is_required": False,
        "options": {},
        "sort_order": 1,
    }


def research_definition():
    forms = []
    for index, subject_type in enumerate(("project", "department", "role", "process", "opportunity"), 1):
        forms.append(
            {
                "form_key": f"{subject_type}_form",
                "name": f"{subject_type} form",
                "description": "",
                "subject_type": subject_type,
                "module_key": "pre_diagnosis",
                "sort_order": index,
                "sections": [
                    {
                        "section_key": "basics",
                        "name": "基础信息",
                        "description": "",
                        "sort_order": 1,
                        "fields": [field(f"{subject_type}_name")],
                    }
                ],
            }
        )
    return {"forms": forms}


def generated_template(tasks=None):
    return {
        "name": "制造业模板",
        "industry_name": "制造业",
        "description": "测试",
        "modules": [
            {
                "module_key": "pre_diagnosis",
                "name": "预诊断",
                "description": "",
                "sort_order": 1,
                "tasks": tasks
                or [
                    {
                        "task_key": "collect_info",
                        "name": "收集信息",
                        "description": "",
                        "duration_days": 1,
                        "default_assignee_role": "project_lead",
                        "sort_order": 1,
                        "dependency_keys": [],
                    }
                ],
            }
        ],
        "research_definition": research_definition(),
    }


def task(key, dependencies):
    return {
        "task_key": key,
        "name": key,
        "description": "",
        "duration_days": 1,
        "default_assignee_role": "fde_engineer",
        "sort_order": 1,
        "dependency_keys": dependencies,
    }


def test_chat_messages_reject_excessive_history():
    with pytest.raises(AIContractError) as caught:
        validate_chat_messages([{"role": "user", "content": "x"}] * 41)
    assert caught.value.path == "messages"


def test_chat_decision_allows_at_most_three_questions():
    with pytest.raises(AIContractError) as caught:
        parse_chat_decision(
            {
                "status": "need_more_information",
                "message": "继续补充",
                "known_information": {},
                "missing_fields": [],
                "questions": ["1", "2", "3", "4"],
            }
        )
    assert caught.value.path == "questions"


def test_generated_template_rejects_dependency_cycle():
    payload = generated_template([task("a", ["b"]), task("b", ["a"])])
    with pytest.raises(AIContractError) as caught:
        validate_generated_template(payload, active_module_keys={"pre_diagnosis"})
    assert caught.value.code == "cyclic_dependency"


def test_generated_template_requires_all_five_research_subject_types():
    payload = generated_template()
    payload["research_definition"]["forms"].pop()
    with pytest.raises(AIContractError) as caught:
        validate_generated_template(payload, active_module_keys={"pre_diagnosis"})
    assert caught.value.code == "missing_research_subject_type"


def test_generated_template_returns_normalized_payload():
    result = validate_generated_template(
        generated_template(), active_module_keys={"pre_diagnosis"}
    )
    assert result["name"] == "制造业模板"
    assert result["modules"][0]["tasks"][0]["task_key"] == "collect_info"
