from __future__ import annotations

from dataclasses import dataclass

import pytest

from fde_api.auth.models import User
from fde_api.auth.passwords import hash_password
from fde_api.auth.tokens import issue_access_token


INITIAL_PASSWORD = "InitialPass!234"


@dataclass(frozen=True)
class AuthorizedClient:
    client: object
    headers: dict[str, str]

    def get(self, *args, **kwargs):
        return self.client.get(*args, headers=self.headers, **kwargs)

    def post(self, *args, **kwargs):
        return self.client.post(*args, headers=self.headers, **kwargs)

    def patch(self, *args, **kwargs):
        return self.client.patch(*args, headers=self.headers, **kwargs)


@pytest.fixture
def authorized_client_factory(client, db_session, settings):
    def create(role: str) -> AuthorizedClient:
        user = User(
            username=f"{role}.module",
            display_name=role,
            role=role,
            password_hash=hash_password(INITIAL_PASSWORD),
            must_change_password=False,
            is_active=True,
        )
        db_session.add(user)
        db_session.commit()
        return AuthorizedClient(
            client,
            {"Authorization": f"Bearer {issue_access_token(user, settings)}"},
        )

    return create


@pytest.fixture
def admin_client(authorized_client_factory):
    return authorized_client_factory("admin")


@pytest.fixture
def project_lead_client(authorized_client_factory):
    return authorized_client_factory("project_lead")


def assert_error(response, status: int, code: str) -> None:
    assert response.status_code == status
    assert response.json["data"] is None
    assert response.json["error"]["code"] == code


def create_module(admin_client, **overrides):
    payload = {
        "name": "数据治理",
        "description": "数据准备",
        "sort_order": 60,
    }
    payload.update(overrides)
    return admin_client.post("/api/v1/modules", json=payload)


def test_only_admin_can_create_module(admin_client, project_lead_client):
    """Changing the route guard to allow a non-admin would create catalog records."""
    payload = {"name": "数据治理", "description": "数据准备", "sort_order": 60}

    assert admin_client.post("/api/v1/modules", json=payload).status_code == 201
    assert_error(
        project_lead_client.post("/api/v1/modules", json=payload), 403, "forbidden"
    )


def test_create_normalizes_key_once_and_patch_keeps_existing_key(admin_client):
    """Regenerating a key after a rename would break references to the catalog item."""
    created = create_module(admin_client, name="  PoV  ").json["data"]

    response = admin_client.patch(
        f"/api/v1/modules/{created['id']}",
        json={
            "version": created["version"],
            "name": "生产验证",
            "description": "已更新",
            "sort_order": 70,
        },
    )

    assert response.status_code == 200
    assert response.json["data"] == {
        "id": created["id"],
        "key": "pov",
        "name": "生产验证",
        "description": "已更新",
        "sort_order": 70,
        "is_active": True,
        "version": 2,
    }


def test_module_patch_rejects_a_stale_second_editor_without_overwriting(
    admin_client,
):
    """A row lock without a version comparison would serialize two silent overwrites."""
    created = create_module(admin_client).json["data"]

    first = admin_client.patch(
        f"/api/v1/modules/{created['id']}",
        json={"version": created["version"], "name": "第一位编辑者"},
    )
    stale = admin_client.patch(
        f"/api/v1/modules/{created['id']}",
        json={"version": created["version"], "name": "过期编辑者"},
    )
    current = admin_client.get("/api/v1/modules?page=1&page_size=20").json[
        "data"
    ]["items"][0]

    assert first.status_code == 200
    assert first.json["data"]["version"] == created["version"] + 1
    assert_error(stale, 409, "stale_version")
    assert current["name"] == "第一位编辑者"
    assert current["version"] == created["version"] + 1


@pytest.mark.parametrize("version", [None, True, 0, -1, 1.5, "1"])
def test_module_patch_requires_a_positive_integer_version(admin_client, version):
    """Missing or coercible concurrency tokens would bypass the write contract."""
    created = create_module(admin_client).json["data"]
    payload = {"name": "不应保存"}
    if version is not None:
        payload["version"] = version

    response = admin_client.patch(
        f"/api/v1/modules/{created['id']}", json=payload
    )

    assert_error(response, 400, "invalid_request")


def test_list_uses_stable_sort_order_and_id_pagination(admin_client):
    """Ordering only by sort_order makes equal-priority page results nondeterministic."""
    first = create_module(admin_client, name="模块乙", sort_order=10).json["data"]
    second = create_module(admin_client, name="模块甲", sort_order=10).json["data"]
    create_module(admin_client, name="模块丙", sort_order=20)

    first_page = admin_client.get("/api/v1/modules?page=1&page_size=2")
    second_page = admin_client.get("/api/v1/modules?page=2&page_size=2")

    assert first_page.status_code == 200
    assert [item["id"] for item in first_page.json["data"]["items"]] == sorted(
        [first["id"], second["id"]]
    )
    assert [item["name"] for item in second_page.json["data"]["items"]] == ["模块丙"]
    assert first_page.json["data"]["page"] == 1
    assert first_page.json["data"]["page_size"] == 2
    assert first_page.json["data"]["total"] == 3


@pytest.mark.parametrize(
    "overrides",
    [
        {"name": "数据治理"},
        {"name": "另一个名称", "key": "数据治理"},
    ],
)
def test_duplicate_module_name_or_key_returns_stable_conflict(admin_client, overrides):
    """Leaking a database duplicate error would make duplicate handling unstable."""
    assert create_module(admin_client).status_code == 201

    response = create_module(admin_client, **overrides)

    assert_error(response, 409, "module_already_exists")
