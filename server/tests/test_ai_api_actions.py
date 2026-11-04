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


def test_catalog_effect_risk_invariants(app):
    """T-R2（agent-policy P1-R2）：结构化 effect/risk 全目录一致性扫描。

    risk 0–4 与 automation_approvals.risk_level 同尺度；GET ⟺ read ⟺ risk=0；
    确认类 risk>=3；external 至少 2 且必为写面。WB-DEF-10：异步文档生成类
    = external + 确认类（AI 不得无确认排队 worker 内模型调用）。
    """
    from fde_api.control.api_catalog import CATALOG
    for spec in CATALOG.values():
        assert spec["effect"] in {"read", "write_db", "external"}, spec["id"]
        assert type(spec["risk"]) is int and 0 <= spec["risk"] <= 4, spec["id"]
        assert (spec["effect"] == "read") == (spec["method"] == "GET"), spec["id"]
        assert spec["write"] == (spec["effect"] != "read"), spec["id"]
        if spec["confirmation"]:
            assert spec["risk"] >= 3, spec["id"]
        if spec["effect"] == "external":
            assert spec["write"] and spec["risk"] >= 2, spec["id"]
    # 派生规则锁定：只读 0 / 普通写 1 / 非确认 external 2 / 确认类 3
    assert CATALOG["projects.read"]["risk"] == 0
    assert CATALOG["projects.update"]["effect"] == "write_db" and CATALOG["projects.update"]["risk"] == 1
    assert CATALOG["forms.export"]["effect"] == "external" and CATALOG["forms.export"]["risk"] == 2
    assert CATALOG["research.delete"]["risk"] == 3
    for key in ("solutions.export_sow", "documents.generate"):
        assert CATALOG[key]["effect"] == "external", key
        assert CATALOG[key]["confirmation"] is True, key
        assert CATALOG[key]["risk"] == 3, key


def test_wb_def_10_generation_ops_require_confirmation_before_run(ai_context, db_session):
    """WB-DEF-10（T-R2）：export_sow / documents.generate 是确认类——AI 发起即
    awaiting_confirmation（密码确认通道后才触发 worker 作业），绝不直接执行；
    确认前 pending 队列可见（人工可拒绝）。"""
    users, _ = ai_context
    user = users["admin"]
    project = make_project(db_session, user)
    for operation, parameters in (
        ("documents.generate", {"project_id": project.id, "document_id": str(uuid4())}),
        ("solutions.export_sow", {"project_id": project.id, "solution_id": str(uuid4())}),
    ):
        result = invoke(user, operation, parameters, {"version": 1})
        assert result["status"] == "awaiting_confirmation", (operation, result)
        assert any(item["operation"] == operation for item in pending_actions(user))


def test_wechat_password_commands_never_reach_model(ai_context):
    from fde_api.control.chat import weixin_message_handler
    users, execute = ai_context
    response = weixin_message_handler(users["admin"].id, "确认操作 " + "a" * 64 + " secret-not-for-ai", "event-confirm")
    assert "过期" in response
    execute.assert_not_called()


__all__ = [
    "ai_context",
    "make_project",
]
