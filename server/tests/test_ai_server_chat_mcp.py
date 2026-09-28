"""Security and durable-state contracts for the authenticated AI Server boundary.

All model execution is mocked. These tests never contact a model provider.
"""
from __future__ import annotations

import io
import json
from datetime import UTC, date, datetime, timedelta
from unittest.mock import Mock
from uuid import uuid4

import jwt
import pytest
from sqlalchemy import func, select

from fde_api.auth.models import User
from fde_api.auth.tokens import issue_access_token
from fde_api.control import chat
from fde_api.control.chat import AIChatTurn, AIConversation, create_turn, execute_chat_turn, weixin_message_handler
from fde_api.control.dsh_runtime import DSHRuntimeError
from fde_api.control.mcp_gateway import issue_mcp_token
from fde_api.control.models import SkillDefinition, SkillVersion, UserAIAccessGrant
from fde_api.control.service import ControlServiceError
from fde_api.files.models import ProjectFile, ProjectFileVersion
from fde_api.jobs.models import OutboxEvent
from fde_api.workbench.models import Project, ProjectMember


MCP_PATH = "/api/v1/internal/ai/mcp"
CHAT_PATH = "/api/v1/ai/chat"


@pytest.fixture
def ai_context(app, db_session, monkeypatch):
    users = {}
    for name, role in (("admin", "admin"), ("alice", "viewer"), ("bob", "viewer"), ("lead", "project_lead")):
        user = User(username=f"ai-test-{name}-{uuid4().hex}", display_name=name,
                    password_hash="unused-in-token-auth-tests", role=role, is_active=True, must_change_password=False)
        db_session.add(user)
        users[name] = user
    db_session.commit()
    mock_execute = Mock(return_value="AI Server 已完成查询。")
    monkeypatch.setattr(chat, "execute_ai_prompt", mock_execute)
    with app.app_context():
        yield users, mock_execute


def access_headers(user, settings):
    return {"Authorization": "Bearer " + issue_access_token(user, settings)}


def mcp_request(client, token, method="tools/list", params=None):
    body = {"jsonrpc": "2.0", "id": "request-1", "method": method}
    if params is not None:
        body["params"] = params
    return client.post(MCP_PATH, json=body, headers={"Authorization": "Bearer " + token})


def tool_request(client, token, name, arguments=None):
    return mcp_request(client, token, "tools/call", {"name": name, "arguments": {} if arguments is None else arguments})


def tool_data(response):
    assert response.status_code == 200, response.json
    assert response.json["result"]["isError"] is False, response.json
    return json.loads(response.json["result"]["content"][0]["text"])


def assert_tool_denied(response):
    assert response.status_code == 200, response.json
    assert response.json["result"]["isError"] is True, response.json


def make_project(session, leader, *, member=None, name="Accessible Project"):
    project = Project(project_code=f"AI-{uuid4().hex[:12]}", name=name, enterprise_name=name,
                      planned_start_date=date(2026, 9, 1), leader_user_id=leader.id,
                      status="active", template_snapshot={})
    session.add(project)
    session.flush()
    if member:
        session.add(ProjectMember(project_id=project.id, user_id=member.id, role="viewer"))
    session.commit()
    return project


def make_skill(session, owner, *, scope="personal", capabilities=None, name="Personal guidance"):
    key = uuid4().hex
    skill = SkillDefinition(scope=scope, namespace_key="public" if scope == "public" else owner.id,
        owner_user_id=owner.id if scope == "personal" else None, skill_key=key, name=name,
        description="Test skill", created_by_user_id=owner.id, current_version_number=1, status="active")
    session.add(skill)
    session.flush()
    session.add(SkillVersion(skill_id=skill.id, version_number=1, instructions_text=f"Private instructions for {name}",
        manifest_json={}, required_capabilities=capabilities or [], content_sha256=uuid4().hex * 2, created_by_user_id=owner.id))
    session.commit()
    return skill


def revoke_ai(session, user, admin):
    session.add(UserAIAccessGrant(user_id=user.id, access_level="disabled", granted_by_user_id=admin.id, reason="test revocation"))
    session.commit()


def new_message(text="查看我可以访问的项目", **extra):
    return {"message_id": str(uuid4()), "message": text, **extra}


def test_mcp_rejects_normal_login_token_and_missing_auth(ai_context, client, settings):
    users, _ = ai_context
    assert mcp_request(client, issue_access_token(users["alice"], settings)).status_code == 401
    assert client.post(MCP_PATH, json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"}).status_code == 401


def test_lcsc_skill_tool_is_visible_and_callable_from_ai_chat(ai_context, client, monkeypatch):
    users, _ = ai_context
    token = issue_mcp_token(users["alice"], execution_id=str(uuid4()))
    listed = mcp_request(client, token)
    assert any(item["name"] == "lcsc_search" for item in listed.json["result"]["tools"])
    called = Mock(return_value={"id": "run-1", "status": "succeeded", "skill_key": "lcsc-browser-jev"})
    monkeypatch.setattr("fde_api.control.lcsc_skills.run_lcsc_skill", called)
    response = tool_request(client, token, "lcsc_search", {"skill_key": "lcsc-browser-jev", "query": "STM32F103C8T6"})
    assert tool_data(response)["id"] == "run-1"
    assert called.call_args.kwargs["skill_key"] == "lcsc-browser-jev"


def test_lcsc_record_read_is_owner_scoped_and_omits_image_payload(ai_context, client, db_session):
    from fde_api.control.lcsc_skills import LcscSkillRun
    users, _ = ai_context
    own=LcscSkillRun(user_id=users['alice'].id,execution_id=str(uuid4()),request_sha256='a'*64,skill_key='lcsc-browser-baseline',query='C1',started_at=datetime.now(UTC),result_json={'details':{'pins':{'count':2,'screenshot':'data:image/png;base64,LARGE'}},'evidence_pool':[{'text':'internal intermediate'}]})
    foreign=LcscSkillRun(user_id=users['bob'].id,execution_id=str(uuid4()),request_sha256='b'*64,skill_key='lcsc-browser-jev',query='C2',started_at=datetime.now(UTC))
    db_session.add_all([own,foreign]);db_session.commit()
    token=issue_mcp_token(users['alice'])
    listed=mcp_request(client,token)
    assert any(t['name']=='lcsc_runs_read' for t in listed.json['result']['tools'])
    result=tool_data(tool_request(client,token,'lcsc_runs_read',{'run_ids':[own.id]}))
    assert result['items'][0]['id']==own.id
    assert result['items'][0]['result']['details']['pins']=={'count':2,'screenshot_available':True}
    assert 'evidence_pool' not in result['items'][0]['result']
    denied=tool_request(client,token,'lcsc_runs_read',{'run_ids':[foreign.id]})
    assert 'result' not in denied.json or denied.json['result'].get('isError')


@pytest.mark.parametrize("claim,value", [("aud", "fde-api"), ("iss", "other-service"), ("exp", 1)])
def test_mcp_rejects_wrong_audience_issuer_and_expired_tokens(ai_context, client, settings, claim, value):
    users, _ = ai_context
    token = issue_mcp_token(users["alice"])
    claims = jwt.decode(token, options={"verify_signature": False})
    claims[claim] = value
    altered = jwt.encode(claims, settings.jwt_secret, algorithm="HS256")
    assert mcp_request(client, altered).status_code == 401


@pytest.mark.parametrize("field,value", [("auth_version", 99), ("is_active", False), ("must_change_password", True)])
def test_mcp_rechecks_account_state_after_token_issuance(ai_context, client, db_session, field, value):
    users, _ = ai_context
    user = users["alice"]
    token = issue_mcp_token(user)
    setattr(user, field, value)
    db_session.commit()
    assert mcp_request(client, token).status_code == 401


def test_mcp_revoked_ai_access_invalidates_existing_token(ai_context, client, db_session):
    users, _ = ai_context
    token = issue_mcp_token(users["alice"])
    revoke_ai(db_session, users["alice"], users["admin"])
    assert_tool_denied(mcp_request(client, token))


def test_mcp_token_capabilities_are_attenuated_not_promoted(ai_context, client):
    users, _ = ai_context
    token = issue_mcp_token(users["admin"], capabilities=["project.read"])
    tools = mcp_request(client, token).json["result"]["tools"]
    names = {item["name"] for item in tools}
    assert "project_list" in names
    assert "file_read" not in names and "system_status" not in names
    assert_tool_denied(tool_request(client, token, "system_status"))


def test_mcp_project_scope_and_membership_are_enforced(ai_context, client, db_session):
    users, _ = ai_context
    visible = make_project(db_session, users["lead"], member=users["alice"])
    hidden = make_project(db_session, users["lead"], name="Secret Other Project")
    token = issue_mcp_token(users["alice"])
    assert {row["id"] for row in tool_data(tool_request(client, token, "project_list"))["items"]} == {visible.id}
    assert tool_data(tool_request(client, token, "project_read", {"project_id": visible.id}))["project"]["id"] == visible.id
    assert_tool_denied(tool_request(client, token, "project_read", {"project_id": hidden.id}))
    # Even an administrator's actor token can be narrowed to one project.
    scoped = issue_mcp_token(users["admin"], project_id=visible.id)
    assert_tool_denied(tool_request(client, scoped, "project_read", {"project_id": hidden.id}))
    assert {row["id"] for row in tool_data(tool_request(client, scoped, "project_list"))["items"]} == {visible.id}


def test_mcp_membership_removal_takes_effect_for_existing_token(ai_context, client, db_session):
    users, _ = ai_context
    project = make_project(db_session, users["lead"], member=users["alice"])
    token = issue_mcp_token(users["alice"], project_id=project.id)
    member = db_session.scalar(select(ProjectMember).where(ProjectMember.project_id == project.id, ProjectMember.user_id == users["alice"].id))
    db_session.delete(member)
    db_session.commit()
    assert_tool_denied(tool_request(client, token, "project_read", {"project_id": project.id}))


def test_mcp_only_lists_own_and_public_skills_allowed_by_capability(ai_context, client, db_session):
    users, _ = ai_context
    own = make_skill(db_session, users["alice"], name="Alice only")
    other = make_skill(db_session, users["bob"], name="Bob secret")
    public = make_skill(db_session, users["admin"], scope="public", name="Public reader", capabilities=["project.read"])
    admin_skill = make_skill(db_session, users["admin"], scope="public", name="System operator", capabilities=["system.health"])
    token = issue_mcp_token(users["alice"])
    rows = tool_data(tool_request(client, token, "skill_list"))["items"]
    assert {item["id"] for item in rows} == {own.id, public.id}
    assert "Private instructions" in tool_data(tool_request(client, token, "skill_read", {"skill_id": own.id}))["instructions"]
    assert_tool_denied(tool_request(client, token, "skill_read", {"skill_id": other.id}))
    assert_tool_denied(tool_request(client, token, "skill_read", {"skill_id": admin_skill.id}))


@pytest.mark.parametrize("params", [[], "invalid", {"name": []}, {"name": {}}, {"name": "project_list", "arguments": []}, {"name": "project_list", "arguments": {"actor_user_id": "someone-else"}}, {"name": "shell", "arguments": {"command": "whoami"}}])
def test_mcp_bad_params_return_tool_error_not_internal_error(ai_context, client, params):
    users, _ = ai_context
    assert_tool_denied(mcp_request(client, issue_mcp_token(users["alice"]), "tools/call", params))


def test_mcp_protocol_negotiation_and_invalid_envelope(ai_context, client):
    users, _ = ai_context
    token = issue_mcp_token(users["alice"])
    assert mcp_request(client, token, "initialize").json["result"]["capabilities"] == {"tools": {}}
    assert mcp_request(client, token, "notifications/initialized").status_code == 202
    assert mcp_request(client, token, "unknown").json["error"]["code"] == -32601
    assert client.post(MCP_PATH, json=[]).status_code == 400


def test_mcp_file_parse_failure_is_safe_tool_result(ai_context, client, db_session, app):
    users, _ = ai_context
    project = make_project(db_session, users["lead"], member=users["alice"])
    file = ProjectFile(project_id=project.id, display_name="broken.docx", created_by_user_id=users["lead"].id)
    db_session.add(file)
    db_session.flush()
    version = ProjectFileVersion(file_id=file.id, version_number=1, original_filename="broken.docx", safe_filename="broken.docx",
        extension="docx", mime_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document", bucket="test",
        storage_key="untrusted-broken-archive", size_bytes=12, scan_status="clean", status="available", uploaded_by_user_id=users["lead"].id)
    db_session.add(version)
    db_session.flush()
    file.current_version_id = version.id
    db_session.commit()
    storage = Mock()
    storage.open_stream.return_value = io.BytesIO(b"not-a-zip")
    app.extensions["fde_api_object_storage"] = storage
    result = tool_request(client, issue_mcp_token(users["alice"]), "file_read", {"project_id": project.id, "file_id": file.id})
    assert_tool_denied(result)
    assert "文件正文读取失败" in str(result.json)
    assert "untrusted-broken-archive" not in str(result.json)


def test_chat_requires_auth_and_rejects_invalid_payloads(ai_context, client, settings):
    users, execute = ai_context
    assert client.post(CHAT_PATH + "/messages", json=new_message()).status_code == 401
    for body in ([], {}, new_message(""), new_message("x" * 16001), {"message_id": "invalid", "message": "hello"}):
        response = client.post(CHAT_PATH + "/messages", json=body, headers=access_headers(users["alice"], settings))
        assert response.status_code == 400
    execute.assert_not_called()


def test_chat_idempotently_enqueues_one_turn_and_one_outbox(ai_context, client, settings, db_session):
    users, execute = ai_context
    message = new_message()
    first = client.post(CHAT_PATH + "/messages", json=message, headers=access_headers(users["alice"], settings))
    second = client.post(CHAT_PATH + "/messages", json=message, headers=access_headers(users["alice"], settings))
    assert first.status_code == second.status_code == 202
    assert first.json["data"] == second.json["data"]
    assert first.json["data"]["status"] == "queued"
    assert db_session.scalar(select(func.count()).select_from(AIChatTurn)) == 1
    assert db_session.scalar(select(func.count()).select_from(OutboxEvent).where(OutboxEvent.topic == "ai.chat")) == 1
    execute.assert_not_called()


def test_chat_conflicting_message_id_cannot_change_text_or_owner(ai_context):
    users, _ = ai_context
    payload = new_message()
    create_turn(user=users["alice"], payload=payload)
    for user, replacement in ((users["alice"], {**payload, "message": "different"}), (users["bob"], payload)):
        with pytest.raises(ControlServiceError) as error:
            create_turn(user=user, payload=replacement)
        assert error.value.status == 409


def test_chat_explicit_conversation_mismatch_is_idempotency_conflict(ai_context):
    users, _ = ai_context
    payload = new_message(conversation_id=str(uuid4()))
    create_turn(user=users["alice"], payload=payload)
    with pytest.raises(ControlServiceError) as error:
        create_turn(user=users["alice"], payload={**payload, "conversation_id": str(uuid4())})
    assert error.value.status == 409


def test_chat_isolated_by_user_in_list_details_and_sends(ai_context, client, settings):
    users, _ = ai_context
    turn = create_turn(user=users["alice"], payload=new_message("Alice private question"))
    bob_headers = access_headers(users["bob"], settings)
    listing = client.get(CHAT_PATH + "/conversations", headers=bob_headers)
    assert listing.json["data"]["items"] == []
    assert client.get(CHAT_PATH + "/conversations/" + turn["conversation_id"], headers=bob_headers).status_code == 404
    sent = client.post(CHAT_PATH + "/messages", headers=bob_headers, json=new_message(conversation_id=turn["conversation_id"]))
    assert sent.status_code == 404
    assert "Alice private question" not in str(sent.json)


def test_chat_project_selection_must_be_authorized(ai_context, db_session):
    users, execute = ai_context
    project = make_project(db_session, users["lead"])
    with pytest.raises(ControlServiceError) as error:
        create_turn(user=users["alice"], payload=new_message(project_id=project.id))
    assert error.value.status == 403
    execute.assert_not_called()


def test_thinking_flag_is_persisted_forwarded_and_idempotent(ai_context):
    users, execute = ai_context
    payload = new_message(deep_thinking=True)
    turn = create_turn(user=users["alice"], payload=payload)
    assert turn["deep_thinking"] is True
    with pytest.raises(ControlServiceError):
        create_turn(user=users["alice"], payload={**payload, "deep_thinking": False})
    execute_chat_turn(turn["id"])
    assert execute.call_args.kwargs["deep_thinking"] is True


def test_progress_cannot_be_read_by_another_account(ai_context, client, settings):
    users, _ = ai_context
    turn = create_turn(user=users["alice"], payload=new_message())
    response = client.get(CHAT_PATH + "/messages/" + turn["id"] + "/progress",
        headers=access_headers(users["bob"], settings))
    assert response.status_code == 404


def test_chat_rejects_second_pending_turn_then_preserves_own_history(ai_context, db_session):
    users, execute = ai_context
    first = create_turn(user=users["alice"], payload=new_message("Remember Alice context"))
    other = create_turn(user=users["bob"], payload=new_message("Bob secret context"))
    execute_chat_turn(other["id"])
    with pytest.raises(ControlServiceError) as error:
        create_turn(user=users["alice"], payload=new_message(conversation_id=first["conversation_id"]))
    assert error.value.code == "chat_busy"
    execute_chat_turn(first["id"])
    second = create_turn(user=users["alice"], payload=new_message("Continue", conversation_id=first["conversation_id"]))
    execute_chat_turn(second["id"])
    call = execute.call_args.kwargs
    assert call["user_id"] == users["alice"].id and call["execution_id"] == second["id"]
    assert "Remember Alice context" in call["prompt"] and "Continue" in call["prompt"]
    assert "Bob secret context" not in call["prompt"]
    db_session.rollback()
    assert db_session.get(AIChatTurn, second["id"]).status == "completed"


def test_completed_chat_retry_returns_saved_answer_without_upstream_call(ai_context):
    users, execute = ai_context
    turn = create_turn(user=users["alice"], payload=new_message())
    first = execute_chat_turn(turn["id"])
    assert execute_chat_turn(turn["id"]) == first
    execute.assert_called_once()


def test_chat_upstream_failure_is_persisted_and_retry_uses_same_execution_id(ai_context, db_session):
    users, execute = ai_context
    turn = create_turn(user=users["alice"], payload=new_message())
    execute.side_effect = DSHRuntimeError("ai_timeout", "AI Server 暂时不可用。", retryable=True)
    with pytest.raises(DSHRuntimeError):
        execute_chat_turn(turn["id"])
    db_session.rollback()
    failed = db_session.get(AIChatTurn, turn["id"])
    assert failed.status == "failed" and failed.error_message == "AI Server 暂时不可用。"
    execute.side_effect = None
    assert execute_chat_turn(turn["id"]) == "AI Server 已完成查询。"
    assert [call.kwargs["execution_id"] for call in execute.call_args_list] == [turn["id"], turn["id"]]
    db_session.rollback()
    assert db_session.get(AIChatTurn, turn["id"]).status == "completed"


def test_chat_unexpected_exception_does_not_leave_permanent_running_state(ai_context, db_session):
    users, execute = ai_context
    turn = create_turn(user=users["alice"], payload=new_message())
    execute.side_effect = RuntimeError("private-token-must-not-be-persisted")
    with pytest.raises(Exception):
        execute_chat_turn(turn["id"])
    db_session.rollback()
    current = db_session.get(AIChatTurn, turn["id"])
    assert current.status == "failed"
    assert "private-token" not in current.error_message


def test_chat_rechecks_ai_permission_before_queued_execution(ai_context, db_session):
    users, execute = ai_context
    turn = create_turn(user=users["alice"], payload=new_message())
    revoke_ai(db_session, users["alice"], users["admin"])
    response = execute_chat_turn(turn["id"])
    assert "AI 权限" in response
    execute.assert_not_called()
    db_session.rollback()
    assert db_session.get(AIChatTurn, turn["id"]).status == "failed"


def test_weixin_callback_has_durable_per_user_idempotency(ai_context, db_session):
    users, execute = ai_context
    response = weixin_message_handler(users["alice"].id, "hello", "same-provider-event")
    assert weixin_message_handler(users["alice"].id, "hello", "same-provider-event") == response
    assert execute.call_count == 1
    weixin_message_handler(users["bob"].id, "hello", "same-provider-event")
    assert execute.call_count == 2
    rows = db_session.scalars(select(AIConversation)).all()
    assert len(rows) == 2 and {c.user_id for c in rows} == {users["alice"].id, users["bob"].id}
    assert all(c.source == "wechat" for c in rows)
