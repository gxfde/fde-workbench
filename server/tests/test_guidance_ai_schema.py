import pytest

from fde_api.guidance.ai_schema import GuidanceContractError, validate_guidance_output


def _valid():
    item = {"text": "缩短报价周期", "classification": "customer_stated", "source_refs": ["paragraph-1"], "confirmed": False}
    return {
        "customer_vision": "形成可持续的数字化运营能力",
        "current_phase_objective": "完成现状诊断并确定 PoV 范围",
        "key_business_problems": [item], "priority_departments": [], "priority_roles": [],
        "priority_processes": [], "success_criteria": [], "out_of_scope": [],
        "data_security_redlines": [], "systems_and_deployment_constraints": [],
        "assumptions": [], "open_questions": [], "next_actions": [],
        "executive_summary": "围绕客户目标开展诊断。", "evidence": {"paragraph-1": "客户目标"},
    }


def test_rejects_claim_with_unknown_source_ref():
    value = _valid()
    value["key_business_problems"][0]["source_refs"] = ["paragraph-999"]
    with pytest.raises(GuidanceContractError) as caught:
        validate_guidance_output(value, source_refs={"paragraph-1"})
    assert caught.value.code == "unknown_source_ref"


def test_accepts_structured_guidance():
    result = validate_guidance_output(_valid(), source_refs={"paragraph-1"})
    assert result["current_phase_objective"].startswith("完成")
