from unittest.mock import Mock
import pytest
from test_ai_server_chat_mcp import ai_context, make_project
from fde_api.ai.opportunity_adjustment import adjust_opportunity, normalize_proposal
from fde_api.ai.ai_opportunity_service import AIOpportunityDiscoveryError
from fde_api.research.models import ProjectResearchSubject


def test_adjustment_is_preview_only_and_version_guarded(ai_context, app, db_session):
    users, _ = ai_context
    project = make_project(db_session, users["admin"])
    subject = ProjectResearchSubject(project_id=project.id, subject_type="opportunity", subject_key="adjust-test", name="原机会", description="原说明")
    db_session.add(subject); db_session.commit()
    model = Mock()
    model.complete_json.return_value = {"name": "调整机会", "description": "新说明", "target_audience": "工程师", "next_action": "验证范围"}
    app.extensions["fde_api_ai_opportunity_deepseek"] = model
    payload = {"project_id": project.id, "subject_id": subject.id, "version": subject.version, "instructions": "缩小范围"}
    try:
        result = adjust_opportunity(actor=users["admin"], payload=payload)
        assert result["subject_id"] == subject.id
        assert result["version"] == subject.version
        assert result["proposal"]["name"] == "调整机会"
        db_session.refresh(subject)
        assert subject.name == "原机会" and subject.description == "原说明"
        assert "原说明" in str(model.complete_json.call_args)
        with pytest.raises(AIOpportunityDiscoveryError) as error:
            adjust_opportunity(actor=users["admin"], payload={**payload, "version": subject.version + 1})
        assert error.value.code == "stale_version"
        with pytest.raises(AIOpportunityDiscoveryError) as error:
            adjust_opportunity(actor=users["admin"], payload={**payload, "project_id": "wrong-project"})
        assert error.value.status == 404
        assert model.complete_json.call_count == 1
    finally:
        app.extensions.pop("fde_api_ai_opportunity_deepseek", None)


@pytest.mark.parametrize("raw", [None, {}, {"name": "x"}, {"name": "x", "description": "", "target_audience": "", "next_action": "", "owner_user_id": "attack"}, {"name": "x" * 161, "description": "", "target_audience": "", "next_action": ""}])
def test_invalid_proposals(raw):
    with pytest.raises(AIOpportunityDiscoveryError) as error:
        normalize_proposal(raw)
    assert error.value.code == "ai_output_invalid"
