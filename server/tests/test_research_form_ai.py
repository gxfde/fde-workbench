from fde_api.ai.research_form_service import _normalize_generated_form, _valid_generated_form


def generated_form():
    return {
        "form_key": "production_lead_interview",
        "name": "生产部门负责人访谈",
        "description": "了解生产计划、质量异常和数据现状。",
        "subject_type": "department",
        "module_key": "pre_diagnosis",
        "sections": [
            {
                "section_key": "business_context",
                "name": "业务现状",
                "description": "",
                "fields": [
                    {
                        "field_key": "current_process",
                        "name": "当前流程",
                        "help_text": "请描述当前的业务流程。",
                        "type": "long_text",
                        "is_required": True,
                        "options": {},
                    }
                ],
            }
        ],
    }


def test_generated_research_form_must_be_editable_and_non_duplicate():
    value = generated_form()

    assert _valid_generated_form(value, ["pre_diagnosis"], set()) is True
    assert _valid_generated_form(value, ["pre_diagnosis"], {value["form_key"]}) is False


def test_generated_research_form_rejects_unknown_module_and_extra_fields():
    value = generated_form()
    value["module_key"] = "unknown"
    assert _valid_generated_form(value, ["pre_diagnosis"], set()) is False

    value = generated_form()
    value["unexpected"] = "not allowed"
    assert _valid_generated_form(value, ["pre_diagnosis"], set()) is False


def test_generated_research_form_normalizes_common_model_format_drift():
    value = generated_form()
    value["form_key"] = "Production Lead Interview"
    value["subject_type"] = "project"
    value["unexpected"] = "ignored"
    value["sections"][0].pop("description")
    field = value["sections"][0]["fields"][0]
    field.pop("help_text")
    field["is_required"] = "true"
    field["unexpected"] = "ignored"

    normalized = _normalize_generated_form(
        {"research_form": value},
        required_subject_type="department",
    )

    assert normalized is not None
    assert normalized["form_key"] == "production_lead_interview"
    assert normalized["subject_type"] == "department"
    assert normalized["sections"][0]["description"] == ""
    assert normalized["sections"][0]["fields"][0]["help_text"] == ""
    assert normalized["sections"][0]["fields"][0]["is_required"] is True
    assert _valid_generated_form(normalized, ["pre_diagnosis"], set(), required_subject_type="department") is True
