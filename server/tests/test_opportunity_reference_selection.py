from unittest.mock import Mock
import json
import pytest
from test_ai_server_chat_mcp import ai_context, make_project
from fde_api.ai.ai_opportunity_service import discover_ai_opportunities, AIOpportunityDiscoveryError
from fde_api.research.models import ProjectResearchSubject


def test_unselected_shared_notes_never_reach_model_and_format_mode_disables_thinking(ai_context, app, db_session):
    users, _ = ai_context
    project = make_project(db_session, users["admin"])
    subject = ProjectResearchSubject(project_id=project.id, subject_type="department",
        subject_key="sales", name="销售部", memo="UNSELECTED_SHARED_SECRET")
    db_session.add(subject)
    db_session.commit()
    model = Mock()
    model.complete_json.return_value = {"candidates": []}
    app.extensions["fde_api_ai_opportunity_deepseek"] = model
    try:
        discover_ai_opportunities(actor=users["admin"], payload={"project_id": project.id, "subject_id": subject.id,
            "guidance": "SELECTED_IDEA", "references": ["guidance"], "expand": False})
        arguments = model.complete_json.call_args.kwargs
        assert arguments["deep_thinking"] is False
        assert "UNSELECTED_SHARED_SECRET" not in str(arguments["messages"])
        assert "SELECTED_IDEA" in str(arguments["messages"])
        context = json.loads(arguments["messages"][1]["content"].split("\n", 1)[1])
        assert context["included_memos"] == [] and context["included_forms"] == []
    finally:
        app.extensions.pop("fde_api_ai_opportunity_deepseek", None)


@pytest.mark.parametrize("references", [[], [None], [{}], ["unknown"]])
def test_invalid_references_fail_cleanly(ai_context, references):
    users, _ = ai_context
    with pytest.raises(AIOpportunityDiscoveryError) as error:
        discover_ai_opportunities(actor=users["admin"], payload={"project_id": "p", "subject_id": "s", "references": references})
    assert error.value.status == 400
