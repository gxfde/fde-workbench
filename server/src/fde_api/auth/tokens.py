import hashlib
import secrets
from datetime import UTC, datetime, timedelta

import jwt

from fde_api.auth.models import User
from fde_api.config import Settings


def issue_access_token(user: User, settings: Settings) -> str:
    issued_at = datetime.now(UTC)
    expires_at = issued_at + timedelta(minutes=settings.access_token_minutes)
    claims = {
        "sub": user.id,
        "role": user.role,
        "pwd": not user.must_change_password,
        "ver": user.auth_version,
        "iat": issued_at,
        "exp": expires_at,
        "iss": "fde-workbench",
    }
    return jwt.encode(claims, settings.jwt_secret, algorithm="HS256")


def new_refresh_token() -> tuple[str, str]:
    raw_token = secrets.token_urlsafe(32)
    token_digest = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
    return raw_token, token_digest
