import pytest

from fde_api.auth.models import InvalidRoleError, User
from fde_api.auth.passwords import hash_password
from fde_api.auth.permissions import role_at_least
from fde_api.auth.tokens import issue_access_token


@pytest.mark.parametrize(
    ("actual", "required", "allowed"),
    [
        ("admin", "viewer", True),
        ("project_lead", "fde_engineer", True),
        ("fde_engineer", "viewer", True),
        ("viewer", "fde_engineer", False),
        ("fde_engineer", "project_lead", False),
    ],
)
def test_role_hierarchy_inherits_only_downward(actual, required, allowed):
    """A role can perform work assigned to roles below it, never above it."""
    assert role_at_least(actual, required) is allowed


@pytest.fixture
def client_factory(app, db_session, settings):
    from fde_api.auth.decorators import require_minimum_role

    @app.get("/test-min-engineer")
    @require_minimum_role("fde_engineer")
    def minimum_engineer_route():
        return {"data": {"ok": True}, "error": None}

    def create_client(role):
        user = User(
            username=f"{role}.user",
            display_name=role,
            role=role,
            password_hash=hash_password("InitialPass!234"),
            must_change_password=False,
            is_active=True,
        )
        db_session.add(user)
        db_session.commit()
        token = issue_access_token(user, settings)
        return app.test_client(), {"Authorization": f"Bearer {token}"}

    return create_client


def test_minimum_engineer_route_allows_project_lead_and_admin(client_factory):
    """Replacing inherited comparison with equality would block senior roles."""
    project_lead_client, project_lead_headers = client_factory("project_lead")
    admin_client, admin_headers = client_factory("admin")

    assert project_lead_client.get("/test-min-engineer", headers=project_lead_headers).status_code == 200
    assert admin_client.get("/test-min-engineer", headers=admin_headers).status_code == 200


def test_minimum_engineer_route_rejects_viewer(client_factory):
    """A viewer must not receive an engineer route through role inheritance."""
    client, headers = client_factory("viewer")

    response = client.get("/test-min-engineer", headers=headers)

    assert response.status_code == 403
    assert response.json["error"]["code"] == "forbidden"


def test_minimum_role_rejects_invalid_declared_role():
    """Unsupported route declarations must fail during application setup."""
    from fde_api.auth.decorators import require_minimum_role

    with pytest.raises(InvalidRoleError):
        require_minimum_role("owner")
