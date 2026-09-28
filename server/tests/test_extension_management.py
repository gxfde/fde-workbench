from unittest.mock import Mock

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import delete, select

from fde_api.control.extension_management_routes import management_blueprint
from fde_api.control.model_preferences import ModelPreference, resolve_model_preference
from fde_api.control.models import PluginInstallation, PluginPackage, UserAIAccessGrant
from fde_api.extensions import db
from test_control_plane_api import authorized_client_factory  # noqa: F401


@pytest.fixture(autouse=True)
def management_setup(app, db_session, monkeypatch):
    if "extension_management" not in app.blueprints:
        app.register_blueprint(management_blueprint)
    app.config["MODEL_CREDENTIAL_KEY"] = Fernet.generate_key().decode()
    monkeypatch.setattr("fde_api.control.model_preferences.getaddrinfo", lambda *a, **k: [(2, 1, 6, "", ("8.8.8.8", 443))])
    yield
    db_session.rollback()
    db_session.execute(delete(ModelPreference))
    db_session.commit()


def preference(scope="personal", **changes):
    return {"scope": scope, "name": "我的模型", "provider": "deepseek", "model": "deepseek-v4-pro", "base_url": "https://api.deepseek.com", "api_key": "example-private-test-key", "is_default": True, "supports_tools": True, **changes}


def test_model_delete_requires_own_password_and_ownership(authorized_client_factory):
    from test_control_plane_api import PASSWORD
    owner, other = authorized_client_factory("fde_engineer"), authorized_client_factory("admin")
    item = owner.post("/api/v1/extensions/model-preferences", json=preference()).json["data"]
    path = "/api/v1/extensions/model-preferences/" + item["id"]
    assert owner.client.delete(path, headers=owner.headers, json={}).status_code == 400
    assert owner.client.delete(path, headers=owner.headers, json={"password": "wrong"}).status_code == 403
    assert other.client.delete(path, headers=other.headers, json={"password": PASSWORD}).status_code in (403, 404)
    assert len(owner.get("/api/v1/extensions/model-preferences").json["data"]["items"]) == 1
    assert owner.client.delete(path, headers=owner.headers, json={"password": PASSWORD}).status_code == 200
    assert owner.get("/api/v1/extensions/model-preferences").json["data"]["items"] == []


def test_personal_credentials_encrypted_private_and_resolved_only_server_side(authorized_client_factory, app, db_session):
    owner, other = authorized_client_factory("fde_engineer"), authorized_client_factory("admin")
    response = owner.post("/api/v1/extensions/model-preferences", json=preference())
    assert response.status_code == 200, response.json
    item = response.json["data"]
    assert item["credential_configured"] is True
    assert "api_key" not in item and "example-private-test-key" not in response.get_data(as_text=True)
    assert other.get("/api/v1/extensions/model-preferences").json["data"]["items"] == []
    db_session.rollback()
    stored = db_session.get(ModelPreference, item["id"])
    assert "example-private-test-key" not in stored.credential_ciphertext
    with app.app_context(), db.session() as session:
        resolved = resolve_model_preference(session, owner.user.id)
        assert resolved["api_key"] == "example-private-test-key"
    changed = owner.post("/api/v1/extensions/model-preferences", json=preference(id=item["id"], version=item["version"], api_key="", name="新名称"))
    assert changed.status_code == 200
    assert changed.json["data"]["name"] == "新名称"
    stolen = other.post("/api/v1/extensions/model-preferences", json=preference(id=item["id"], version=2))
    assert stolen.status_code == 403


def test_public_model_permissions_defaults_and_stale_version(authorized_client_factory, app):
    admin, member = authorized_client_factory("admin"), authorized_client_factory("viewer")
    assert member.post("/api/v1/extensions/model-preferences", json=preference("public")).status_code == 403
    public = admin.post("/api/v1/extensions/model-preferences", json=preference("public")).json["data"]
    personal = member.post("/api/v1/extensions/model-preferences", json=preference(model="personal-model")).json["data"]
    with app.app_context(), db.session() as session:
        assert resolve_model_preference(session, member.user.id)["id"] == personal["id"]
    visible = member.get("/api/v1/extensions/model-preferences").json["data"]["items"]
    assert len(visible) == 2
    assert next(item for item in visible if item["id"] == public["id"])["can_edit"] is False
    assert admin.post("/api/v1/extensions/model-preferences", json=preference("public", id=public["id"], version=0)).status_code == 409


def test_encryption_fail_closed_and_rejects_internal_models(authorized_client_factory, app, monkeypatch):
    owner = authorized_client_factory("viewer")
    app.config["MODEL_CREDENTIAL_KEY"] = "invalid"
    response = owner.post("/api/v1/extensions/model-preferences", json=preference())
    assert response.status_code == 503
    assert "example-private-test-key" not in response.get_data(as_text=True)
    monkeypatch.setattr("fde_api.control.model_preferences.getaddrinfo", lambda *a, **k: [(2, 1, 6, "", ("127.0.0.1", 443))])
    assert owner.post("/api/v1/extensions/model-preferences", json=preference(base_url="https://internal.example.com")).status_code == 400


def test_jev_credential_preset_cannot_be_used_as_chat_model(authorized_client_factory):
    owner = authorized_client_factory("viewer")
    jev = preference(provider="typesafe", model="jev-1.13.0", base_url="https://api.typesafe.ai/v1",
                     is_default=False, supports_tools=False)
    assert owner.post("/api/v1/extensions/model-preferences", json=jev).status_code == 200
    assert owner.post("/api/v1/extensions/model-preferences", json={**jev, "is_default": True}).status_code == 400
    assert owner.post("/api/v1/extensions/model-preferences", json={**jev, "supports_tools": True}).status_code == 400
    assert owner.post("/api/v1/extensions/model-preferences", json={**jev, "base_url": "https://other.example.com"}).status_code == 400


def test_admin_can_assign_all_accounts_ai_access_but_admin_retains_full(authorized_client_factory, db_session):
    admin, member = authorized_client_factory("admin"), authorized_client_factory("viewer")
    path = f"/api/v1/users/{member.user.id}/ai-access"
    assert member.patch(path, json={"level": "system_operator"}).status_code == 403
    assert admin.patch(path, json={"level": "project_manager"}).status_code == 200
    result = admin.get(path).json["data"]
    assert result["label"] == "AI 项目管理员"
    assert "task.batch_assign" in result["capabilities"]
    assert admin.patch(f"/api/v1/users/{admin.user.id}/ai-access", json={"level": "disabled"}).status_code == 409
    db_session.rollback()
    assert db_session.scalar(select(UserAIAccessGrant).where(UserAIAccessGrant.user_id == member.user.id)).access_level == "project_manager"


def test_plugin_registration_waits_for_verified_runtime_result(authorized_client_factory, db_session, app):
    admin = authorized_client_factory("admin")
    plugin = PluginPackage(plugin_key="test.runtime", name="运行插件", description="说明", publisher="FDE", current_version="catalog", manifest_json={}, package_sha256="", verified=False, status="active", created_by_user_id=admin.user.id)
    db_session.add(plugin); db_session.commit()
    detail = admin.get(f"/api/v1/extensions/plugins/{plugin.id}")
    assert detail.status_code == 200
    request = admin.post(f"/api/v1/extensions/plugins/{plugin.id}/requests", json={"action": "install", "target_version": "", "reason": "测试"}).json["data"]
    path = f"/api/v1/extensions/plugin-requests/{request['id']}/decision"
    app.extensions.pop("fde_plugin_executor", None)
    assert admin.post(path, json={"decision": "approve", "reason": "测试"}).status_code == 503
    db_session.rollback()
    assert db_session.scalar(select(PluginInstallation)) is None
    app.extensions["fde_plugin_executor"] = Mock(return_value={"status": "installed", "version": "1.2.3", "runtime_version": "test"})
    result = admin.post(path, json={"decision": "approve", "reason": "测试"})
    assert result.status_code == 200, result.json
    assert result.json["data"]["target_version"] == "1.2.3"


def test_public_skill_can_be_edited_disabled_and_read_back(authorized_client_factory):
    admin = authorized_client_factory("admin")
    payload = {"key": "public-summary", "name": "项目总结", "description": "", "instructions": "只依照项目资料总结", "manifest": {}, "required_capabilities": ["project.read"]}
    created = admin.post("/api/v1/extensions/skills/public", json=payload).json["data"]
    assert created["can_edit"] is True
    detail = admin.get(f"/api/v1/extensions/skills/{created['id']}").json["data"]
    assert detail["instructions"] == payload["instructions"]
    assert admin.patch(f"/api/v1/extensions/skills/{created['id']}", json={"status": "disabled"}).json["data"]["status"] == "disabled"
    updated = admin.post("/api/v1/extensions/skills/public", json={**payload, "name": "新版项目总结"}).json["data"]
    assert updated["current_version"] == 1
    assert updated["name"] == "新版项目总结"
