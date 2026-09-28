import json
from dataclasses import dataclass
from uuid import uuid4

import pytest
import requests
from sqlalchemy import select

from fde_api.control.dsh_market import sync_dsh_market, sync_dsh_market_scheduled
from fde_api.control.models import PluginCatalogSync, PluginPackage, UserAIAccessGrant
from fde_api.control.service import ControlServiceError
from fde_api.auth.models import User
from fde_api.auth.passwords import hash_password
from fde_api.auth.tokens import issue_access_token


@dataclass(frozen=True)
class AuthorizedClient:
    client: object
    user: User
    headers: dict[str, str]

    def get(self, *args, **kwargs):
        return self.client.get(*args, headers=self.headers, **kwargs)


@pytest.fixture
def authorized_client_factory(client, db_session, settings):
    def create(role: str) -> AuthorizedClient:
        user = User(username=f"market.{uuid4().hex}", display_name=role, role=role, password_hash=hash_password("InitialPass!234"), must_change_password=False, is_active=True)
        db_session.add(user)
        db_session.commit()
        return AuthorizedClient(client, user, {"Authorization": f"Bearer {issue_access_token(user, settings)}"})
    return create


class FakeResponse:
    def __init__(self, document):
        self.content = json.dumps(document, ensure_ascii=False).encode("utf-8")

    def raise_for_status(self):
        return None


class FakeHTTP:
    def __init__(self, document):
        self.document = document
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return FakeResponse(self.document)


def catalog(name="Safe plugin"):
    return {
        "updated": "2026-09-04",
        "count": 1,
        "plugins": [{
            "name": name,
            "owner": "example",
            "url": "https://github.com/example/safe-plugin",
            "page": "https://plugins.example.com/plugin/safe-plugin",
            "category": "productivity",
            "description": {"en": "Safe", "zh": "安全示例"},
            "npm": "@example/safe-plugin",
            "stars": 12,
            "downloads": 34,
            "install": "dsh plugin add @example/safe-plugin",
        }],
    }


def test_market_sync_is_operator_only_and_is_idempotent(authorized_client_factory, db_session, app):
    operator = authorized_client_factory("admin")
    viewer = authorized_client_factory("viewer")
    db_session.add(UserAIAccessGrant(user_id=operator.user.id, granted_by_user_id=operator.user.id, access_level="system_operator", reason="market test"))
    db_session.commit()
    app.config["SETTINGS"] = app.config["SETTINGS"].model_copy(update={"dsh_market_enabled": True})
    http = FakeHTTP(catalog())

    with app.app_context():
        first = sync_dsh_market(user=operator.user, http=http)
        second = sync_dsh_market(user=operator.user, http=http)
        with pytest.raises(ControlServiceError) as denied:
            sync_dsh_market(user=viewer.user, http=http)

    assert first["plugin_count"] == second["plugin_count"] == 1
    assert denied.value.status == 403
    db_session.rollback()
    plugin = db_session.scalar(select(PluginPackage).where(PluginPackage.source == "dsh-market"))
    assert plugin is not None
    assert plugin.version == 1
    assert plugin.install_spec == "@example/safe-plugin"
    assert "install" not in plugin.manifest_json

    result = viewer.get("/api/v1/extensions/marketplace/search?q=Safe")
    assert result.status_code == 200
    assert result.json["data"]["total"] == 1
    assert result.json["data"]["items"][0]["install_available"] is False


def test_market_rejects_unsafe_source_without_replacing_previous_catalog(authorized_client_factory, db_session, app):
    operator = authorized_client_factory("admin")
    db_session.add(UserAIAccessGrant(user_id=operator.user.id, granted_by_user_id=operator.user.id, access_level="system_operator", reason="market test"))
    db_session.commit()
    app.config["SETTINGS"] = app.config["SETTINGS"].model_copy(update={"dsh_market_enabled": True})

    with app.app_context():
        sync_dsh_market(user=operator.user, http=FakeHTTP(catalog()))
        unsafe = catalog("Unsafe")
        unsafe["plugins"][0]["url"] = "https://evil.invalid/plugin"
        with pytest.raises(ControlServiceError) as error:
            sync_dsh_market(user=operator.user, http=FakeHTTP(unsafe))

    assert error.value.code == "marketplace_invalid"
    db_session.rollback()
    plugins = list(db_session.scalars(select(PluginPackage).where(PluginPackage.source == "dsh-market")))
    assert [item.name for item in plugins] == ["Safe plugin"]
    state = db_session.scalar(select(PluginCatalogSync).where(PluginCatalogSync.source == "dsh-market"))
    assert state.status == "degraded"
    assert state.plugin_count == 1
    assert state.error_message


def test_scheduled_sync_uses_active_admin_as_audit_actor(authorized_client_factory, db_session, app):
    authorized_client_factory("admin")
    app.config["SETTINGS"] = app.config["SETTINGS"].model_copy(update={"dsh_market_enabled": True})

    with app.app_context():
        result = sync_dsh_market_scheduled(http=FakeHTTP(catalog()))

    assert result["plugin_count"] == 1
