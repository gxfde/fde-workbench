import json

import pytest

from fde_api.ai.ai_opportunity_prompt import build_ai_opportunity_messages
from fde_api.ai.ai_opportunity_service import OPPORTUNITY_RESEARCH_ANSWER_KEYS, AIOpportunityDiscoveryError, _memo_context, _normalize_candidates, _normalize_request
from fde_api.research.models import ProjectResearchSubject


def test_user_guidance_is_supplied_as_direction_without_replacing_evidence():
    context = {
        "project": {"name": "AI 项目"},
        "included_forms": [{"form_id": "form-1", "answers": [{"value": "订单排程耗时"}]}],
        "user_guidance": "优先看销售预测与生产排程",
    }

    messages = build_ai_opportunity_messages(context)

    assert "不能将其当作已验证事实" in messages[0]["content"]
    assert "不能替代调研证据" in messages[0]["content"]
    assert "已填调研表或备忘录" in messages[0]["content"]
    assert "research_answers" in messages[0]["content"]
    assert "此阶段只识别机会，不设计交付方案" in messages[0]["content"]
    assert "6 个字符串字段" in messages[0]["content"]
    assert json.loads(messages[1]["content"].split("\n", 1)[1])["user_guidance"] == "优先看销售预测与生产排程"


def test_format_only_preserves_blanks_and_uses_unassessed_defaults():
    messages = build_ai_opportunity_messages({"expand": False})
    assert "仅格式整理" in str(messages)
    raw = {"candidates": [{
        "name": "智能报价", "description": "整理报价", "target_audience": "", "next_action": "",
        "priority": "high", "risk_level": "high", "business_value_score": 5,
        "feasibility_score": 5, "data_readiness_score": 5,
        "research_answers": {"pain_points": "手工报价"},
        "evidence": [{"form_id": "source", "form_name": "补充想法", "field_key": "guidance",
            "question": "想法", "answer_excerpt": "手工报价", "reason": "待验证"}],
    }]}
    candidate = _normalize_candidates(raw, [{"form_id": "source", "answers": [{"value": "手工报价"}]}], format_only=True)[0]
    assert candidate["research_answers"]["pain_points"] == "手工报价"
    assert candidate["research_answers"]["technical_prereqs"] == ""
    assert set(candidate["research_answers"]) == set(OPPORTUNITY_RESEARCH_ANSWER_KEYS)
    assert candidate["next_action"] == ""
    assert candidate["priority"] == "medium"
    assert candidate["business_value_score"] == 3


def test_subject_memo_is_converted_to_traceable_ai_evidence():
    subject = ProjectResearchSubject(id="subject-sales", name="销售部", memo="# 现场记录\n\n- 报价依赖人工经验")

    context = _memo_context(subject)

    assert context["form_id"] == "memo:subject-sales"
    assert context["form_name"] == "销售部备忘录"
    assert context["answers"] == [{
        "field_key": "memo",
        "question": "备忘录",
        "value": "# 现场记录\n\n- 报价依赖人工经验",
    }]


def test_ai_opportunity_candidate_accepts_memo_as_its_only_evidence():
    raw = {"candidates": [{
        "name": "智能报价", "description": "辅助销售快速形成报价。", "target_audience": "销售部",
        "priority": "high", "business_value_score": 4, "feasibility_score": 3,
        "data_readiness_score": 2, "risk_level": "medium", "next_action": "整理历史报价规则。",
        "evidence": [{
            "form_id": "memo:subject-sales", "form_name": "销售部备忘录", "field_key": "memo",
            "question": "备忘录", "answer_excerpt": "报价依赖人工经验", "reason": "备忘录记录了当前做法",
        }],
    }]}

    candidate = _normalize_candidates(raw, [{"form_id": "memo:subject-sales"}])[0]

    assert candidate["name"] == "智能报价"
    assert candidate["evidence"][0]["form_name"] == "销售部备忘录"


def test_ai_opportunity_request_accepts_optional_trimmed_guidance():
    assert _normalize_request({"project_id": " project-1 ", "subject_id": " subject-1 ", "guidance": " 聚焦客服 \n"}) == (
        "project-1",
        "subject-1",
        "聚焦客服",
    )
    assert _normalize_request({"project_id": "project-1", "subject_id": "subject-1"}) == ("project-1", "subject-1", "")


@pytest.mark.parametrize("guidance", [None, 1, "x" * 4001])
def test_ai_opportunity_request_rejects_invalid_guidance(guidance):
    with pytest.raises(AIOpportunityDiscoveryError) as caught:
        _normalize_request({"project_id": "project-1", "subject_id": "subject-1", "guidance": guidance})
    assert caught.value.code == "invalid_request"


def test_ai_opportunity_candidates_include_complete_research_answers():
    research_answers = {
        "current_state": "当前人工汇总订单。",
        "pain_points": "排程耗时且易错。",
        "business_value": "缩短排程时间。",
        "target_scenario": "销售预测与生产排程。",
        "owner_role": "计划部门负责人。",
        "technical_prereqs": "需确认订单与产能数据。",
        "delivery_scope": "先验证一个工厂。",
        "deliverables": "预测与排程验证原型。",
        "acceptance_criteria": "排程耗时下降且结果可追溯。",
        "data_systems": "ERP 订单与产能数据。",
        "risks_dependencies": "依赖历史数据完整性。",
    }
    raw = {"candidates": [{
        "name": "智能排程",
        "description": "结合销售预测辅助生产排程。",
        "target_audience": "计划部门",
        "priority": "high",
        "business_value_score": 5,
        "feasibility_score": 4,
        "data_readiness_score": 3,
        "risk_level": "medium",
        "next_action": "核验历史订单与排程数据。",
        "research_answers": research_answers,
        "evidence": [{
            "form_id": "form-1", "form_name": "岗位调研", "field_key": "pain",
            "question": "当前痛点", "answer_excerpt": "排程耗时", "reason": "直接描述现状",
        }],
    }]}

    candidates = _normalize_candidates(raw, [{"form_id": "form-1"}])

    assert candidates[0]["research_answers"] == {
        key: research_answers[key] for key in OPPORTUNITY_RESEARCH_ANSWER_KEYS
    }
    assert "delivery_scope" not in candidates[0]["research_answers"]


def test_ai_opportunity_candidates_fill_missing_research_answers_for_format_tolerance():
    raw = {"candidates": [{
        "name": "智能排程", "description": "解决人工排程耗时问题。", "target_audience": "计划部门",
        "priority": "high", "business_value_score": 5, "feasibility_score": 4,
        "data_readiness_score": 3, "risk_level": "medium", "next_action": "核验订单数据。",
        "research_answers": {"pain_points": "人工排程耗时。"},
        "evidence": [{
            "form_id": "form-1", "form_name": "岗位调研", "field_key": "pain",
            "question": "当前痛点", "answer_excerpt": "人工排程耗时", "reason": "直接描述现状",
        }],
    }]}

    candidate = _normalize_candidates(raw, [{"form_id": "form-1"}])[0]

    assert candidate["research_answers"]["pain_points"] == "人工排程耗时。"
    assert candidate["research_answers"]["current_state"] == "人工排程耗时"
    assert "待进一步确认" in candidate["research_answers"]["technical_prereqs"]
    assert set(candidate["research_answers"]) == set(OPPORTUNITY_RESEARCH_ANSWER_KEYS)
