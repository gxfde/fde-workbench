import pytest

from fde_api.auth.models import User
from fde_api.auth.passwords import hash_password
from fde_api.auth.tokens import issue_access_token
from fde_api.system_configuration import PUBLIC_FIELDS


class AuthorizedClient:
    def __init__(self, client, headers): self.client, self.headers = client, headers
    def get(self, *args, **kwargs): return self.client.get(*args, headers=self.headers, **kwargs)


@pytest.fixture
def authorized_client(client, db_session, settings):
    def build(role: str):
        user = User(username=f"{role}.settings", display_name=role, role=role,
                    password_hash=hash_password("InitialPass!234"), must_change_password=False, is_active=True)
        db_session.add(user); db_session.commit()
        return AuthorizedClient(client, {"Authorization": f"Bearer {issue_access_token(user, settings)}"})
    return build


def test_only_admin_can_read_system_configuration(authorized_client):
    engineer_client = authorized_client("fde_engineer")
    response = engineer_client.get("/api/v1/system/configuration")
    assert response.status_code == 403


def test_admin_can_save_runtime_configuration_without_secret_echo(authorized_client):
    admin_client = authorized_client("admin")
    current = admin_client.get("/api/v1/system/configuration")
    assert current.status_code == 200
    payload = current.json
    assert set(payload["values"]) == PUBLIC_FIELDS

    values = dict(payload["values"])
    values.update({
        "deepseek_base_url": "https://models.example.com/v1",
        "dsh_enabled": True,
        "dsh_base_url": "https://ai-server.example.com",
        "dsh_runtime_version": "1.0.0",
        "storage_backend": "local",
        "local_storage_root": ".fde-storage",
    })
    response = admin_client.client.put(
        "/api/v1/system/configuration",
        headers=admin_client.headers,
        json={"values": values, "secrets": {"dsh_service_token": "secret-runtime-token"}, "clear_secrets": [], "version": payload["version"]},
    )
    assert response.status_code == 200
    result = response.json
    assert result["values"]["dsh_enabled"] is True
    assert result["secrets_configured"]["dsh_service_token"] is True
    assert "secret-runtime-token" not in response.get_data(as_text=True)


def test_enabling_runtime_without_token_is_rejected(authorized_client):
    admin_client = authorized_client("admin")
    current = admin_client.get("/api/v1/system/configuration").json
    values = dict(current["values"])
    values["dsh_enabled"] = True
    response = admin_client.client.put(
        "/api/v1/system/configuration",
        headers=admin_client.headers,
        json={"values": values, "secrets": {}, "clear_secrets": ["dsh_service_token"], "version": current["version"]},
    )
    assert response.status_code == 400
    assert response.json["error"]["code"] == "invalid_configuration"
