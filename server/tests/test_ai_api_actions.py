from uuid import uuid4

import pytest
from sqlalchemy import select

from fde_api.auth.passwords import hash_password
from fde_api.control.api_actions import decide_action, execute_api, pending_actions
from fde_api.control.access import capabilities_for_level
from fde_api.control.service import ControlServiceError
from fde_api.workbench.models import OperationEvent
from test_ai_server_chat_mcp import ai_context, make_project


def invoke(user, operation, parameters=None, body=None, *, execution=None, scope=None, level="system_operator"):
    return execute_api(user=user, claims={"execution_id": execution or str(uuid4()), "project_id": scope},
        allowed=set(capabilities_for_level(level)), operation=operation, parameters=parameters, body=body)


def test_write_uses_real_api_and_replay_does_not_repeat(ai_context, db_session):
    users, _ = ai_context
    user = users["admin"]
    project = make_project(db_session, user)
    execution = str(uuid4())
    args = {"project_id": project.id}
    body = {"version": project.version, "name": "Updated by API"}
    result = invoke(user, "projects.update", args, body, execution=execution)
    assert result["status"] == "completed", result
    replay = invoke(user, "projects.update", args, body, execution=execution)
    assert replay == result
    db_session.refresh(project)
    assert project.name == "Updated by API"
    assert project.version == body["version"] + 1
    events = db_session.scalars(select(OperationEvent).where(OperationEvent.target_id == result["action_id"])).all()
    assert {e.event_type for e in events} == {"ai.api.requested", "ai.api.started", "ai.api.finished"}


def test_read_only_and_scoped_tokens_cannot_write_or_escape(ai_context, db_session):
    users, _ = ai_context
    project = make_project(db_session, users["admin"], member=users["alice"])
    with pytest.raises(ControlServiceError):
        invoke(users["alice"], "projects.update", {"project_id": project.id}, {"version": 1, "name": "No"}, level="assistant_read")
    with pytest.raises(ControlServiceError):
        invoke(users["admin"], "projects.read", {"project_id": project.id}, scope=str(uuid4()))
    with pytest.raises(ControlServiceError):
        invoke(users["admin"], "projects.list", scope=project.id)
    assert invoke(users["alice"], "projects.read", {"project_id": project.id}, level="assistant_read")["http_status"] == 200


def test_password_confirmation_is_bound_and_never_audits_password(ai_context, db_session):
    users, _ = ai_context
    user = users["admin"]
    user.password_hash = hash_password("test-confirm-only")
    db_session.commit()
    project = make_project(db_session, user)
    result = invoke(user, "projects.update", {"project_id": project.id}, {"version": project.version, "status": "cancelled"})
    identifier = result["action_id"]
    assert result["status"] == "awaiting_confirmation"
    db_session.refresh(project)
    assert project.status == "active"
    assert pending_actions(user)[0]["id"] == identifier
    with pytest.raises(ControlServiceError):
        decide_action(users["bob"], identifier, "test-confirm-only")
    with pytest.raises(ControlServiceError):
        decide_action(user, identifier, "wrong-password")
    assert decide_action(user, identifier, "test-confirm-only")["status"] == "completed"
    assert decide_action(user, identifier, "not-needed-for-completed-result")["status"] == "completed"
    db_session.rollback()  # End the test connection's repeatable-read snapshot.
    db_session.refresh(project)
    assert project.status == "cancelled"
    assert pending_actions(user) == []
    events = db_session.scalars(select(OperationEvent).where(OperationEvent.target_id == identifier)).all()
    assert "test-confirm-only" not in str([e.changes for e in events])


@pytest.mark.parametrize("body", [{"password": "bad"}, {"notes": {"api_key": "bad"}}, {"items": [{"access_token": "bad"}]}])
def test_credentials_rejected_recursively(ai_context, body):
    with pytest.raises(ControlServiceError, match="专用安全"):
        invoke(ai_context[0]["admin"], "projects.create", body=body)


def test_arbitrary_paths_and_operations_rejected(ai_context):
    user = ai_context[0]["admin"]
    with pytest.raises(ControlServiceError):
        invoke(user, "auth.password", body={})
    with pytest.raises(ControlServiceError):
        invoke(user, "projects.read", {"project_id": "../auth/users"})


def test_model_can_be_saved_without_key_as_nondefault_draft(ai_context, monkeypatch):
    monkeypatch.setattr("fde_api.control.model_preferences._validate_url", lambda value: value)
    result = invoke(ai_context[0]["admin"], "models.save", body={"scope": "public", "name": "Draft model", "provider": "openai-compatible", "base_url": "https://api.example.com/v1", "model": "user-supplied-model-id", "is_default": False, "supports_tools": True})
    assert result["status"] == "completed", result
    data = result["result"]["data"]
    assert not data["is_default"]
    assert "credential_ciphertext" not in data


def test_catalog_paths_resolve_existing_api_routes(app):
    import re
    from fde_api.control.api_catalog import CATALOG
    adapter = app.url_map.bind("localhost")
    for spec in CATALOG.values():
        path = re.sub(r"\{\w+\}", str(uuid4()), spec["path"])
        endpoint, _ = adapter.match(path, method=spec["method"])
        assert endpoint


def test_wechat_password_commands_never_reach_model(ai_context):
    from fde_api.control.chat import weixin_message_handler
    users, execute = ai_context
    response = weixin_message_handler(users["admin"].id, "确认操作 " + "a" * 64 + " secret-not-for-ai", "event-confirm")
    assert "过期" in response
    execute.assert_not_called()
