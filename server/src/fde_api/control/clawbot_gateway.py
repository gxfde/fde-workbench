"""Authenticated gateway boundary for ClawBot callbacks."""

from __future__ import annotations

from hmac import compare_digest

from flask import current_app


def verify_gateway_token(candidate: str | None) -> bool:
    settings = current_app.config["SETTINGS"]
    configured = settings.clawbot_gateway_token
    if not settings.clawbot_enabled or configured is None or not candidate:
        return False
    return compare_digest(configured.get_secret_value(), candidate)
