from datetime import UTC, datetime

import jwt

from fde_api.auth.models import User
from fde_api.auth.tokens import issue_access_token, new_refresh_token


def test_refresh_token_returns_distinct_raw_and_digest():
    raw, digest = new_refresh_token()

    assert len(raw) >= 43
    assert len(digest) == 64
    assert raw != digest


def test_access_token_has_required_claims_and_forced_change_flag(settings):
    user = User(
        id="b1f04e32-a243-49b5-a67f-1d1c7a64bd57",
        username="sample_user",
        password_hash="x",
        role="project_lead",
        must_change_password=True,
    )

    token = issue_access_token(user, settings)
    claims = jwt.decode(token, settings.jwt_secret, algorithms=["HS256"], issuer="fde-workbench")

    assert claims["sub"] == user.id
    assert claims["role"] == "project_lead"
    assert claims["pwd"] is False
    assert claims["ver"] == 1
    assert claims["iss"] == "fde-workbench"
    assert isinstance(claims["iat"], int)
    assert isinstance(claims["exp"], int)
    assert datetime.fromtimestamp(claims["iat"], UTC) < datetime.fromtimestamp(claims["exp"], UTC)


def test_access_token_marks_changed_password_as_permitted(settings):
    user = User(username="sample_user", password_hash="x", role="viewer", must_change_password=False)

    claims = jwt.decode(
        issue_access_token(user, settings),
        settings.jwt_secret,
        algorithms=["HS256"],
        issuer="fde-workbench",
    )

    assert claims["pwd"] is True
    assert claims["ver"] == 1


def test_access_token_carries_the_user_auth_version(settings):
    user = User(
        username="sample_user",
        password_hash="x",
        role="viewer",
        must_change_password=False,
        auth_version=7,
    )

    claims = jwt.decode(
        issue_access_token(user, settings),
        settings.jwt_secret,
        algorithms=["HS256"],
        issuer="fde-workbench",
    )

    assert claims["ver"] == 7
