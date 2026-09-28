"""Administrator-managed runtime configuration for the open-source distribution."""
from __future__ import annotations

import json
from typing import Any
from urllib.parse import urlparse

from flask import Blueprint, current_app, g, request
from sqlalchemy import JSON, String, Text, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Mapped, mapped_column

from fde_api.auth.decorators import require_role
from fde_api.auth.models import Base, ROLE_ADMIN
from fde_api.config import Settings
from fde_api.control.model_preferences import _cipher
from fde_api.errors import error_response
from fde_api.extensions import db, object_storage
from fde_api.control.dsh_runtime import dsh_runtime
from fde_api.workbench.models import TimestampMixin, VersionedMixin


blueprint = Blueprint("system_configuration", __name__, url_prefix="/api/v1/system/configuration")
ROW_ID = "system"


class SystemConfiguration(Base, TimestampMixin, VersionedMixin):
    __tablename__ = "system_configuration"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=ROW_ID)
    values_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    secrets_ciphertext: Mapped[str] = mapped_column(Text, nullable=False, default="")


PUBLIC_FIELDS = {
    "deepseek_base_url", "deepseek_industry_template_model", "deepseek_project_presurvey_model",
    "deepseek_ai_opportunity_model", "deepseek_research_export_model", "deepseek_document_generation_model",
    "deepseek_timeout_seconds", "kimi_base_url", "kimi_project_presurvey_model", "kimi_timeout_seconds",
    "dsh_enabled", "dsh_base_url", "dsh_runtime_version", "dsh_protocol_version", "dsh_timeout_seconds",
    "ai_internal_api_url", "weixin_enabled", "dsh_market_enabled", "dsh_market_registry_url",
    "dsh_market_timeout_seconds", "dsh_market_max_catalog_bytes", "clawbot_enabled", "storage_backend",
    "local_storage_root", "oss_endpoint", "oss_bucket", "clamav_host", "clamav_port",
    "clamav_timeout_seconds", "clamav_socket_timeout_seconds",
}
SECRET_FIELDS = {
    "deepseek_api_key", "kimi_project_presurvey_api_key", "dsh_service_token", "weixin_credential_key",
    "clawbot_gateway_token", "oss_access_key_id", "oss_access_key_secret",
}
BOOL_FIELDS = {"dsh_enabled", "weixin_enabled", "dsh_market_enabled", "clawbot_enabled"}
INT_RANGES = {
    "deepseek_timeout_seconds": (5, 300), "kimi_timeout_seconds": (10, 600),
    "dsh_timeout_seconds": (10, 1800), "dsh_market_timeout_seconds": (3, 60),
    "dsh_market_max_catalog_bytes": (100_000, 100_000_000), "clamav_port": (1, 65535),
    "clamav_timeout_seconds": (1, 300), "clamav_socket_timeout_seconds": (1, 300),
}
URL_FIELDS = {"deepseek_base_url", "kimi_base_url", "dsh_base_url", "ai_internal_api_url", "dsh_market_registry_url", "oss_endpoint"}


def _decrypt(item: SystemConfiguration | None) -> dict[str, str]:
    if item is None or not item.secrets_ciphertext:
        return {}
    try:
        value = json.loads(_cipher().decrypt(item.secrets_ciphertext.encode()).decode())
    except Exception:
        return {}
    return {key: value[key] for key in SECRET_FIELDS if isinstance(value.get(key), str)}


def _serialize(item: SystemConfiguration | None, settings: Settings) -> dict[str, Any]:
    stored = item.values_json if item else {}
    values: dict[str, Any] = {}
    for key in PUBLIC_FIELDS:
        value = stored.get(key, getattr(settings, key))
        values[key] = str(value) if key == "local_storage_root" else value
    secrets = _decrypt(item)
    return {"values": values, "secrets_configured": {key: bool(secrets.get(key)) for key in sorted(SECRET_FIELDS)}, "version": item.version if item else 0,
            "bootstrap_fields": ["database_url", "redis_url", "jwt_secret", "api_host", "api_port", "desktop_api_url"]}


def _valid_url(name: str, value: Any, env: str) -> str | None:
    if value in (None, "") and name == "oss_endpoint":
        return None
    if not isinstance(value, str) or len(value) > 1000:
        raise ValueError(name)
    parsed = urlparse(value)
    if parsed.scheme not in ({"http", "https"} if env != "production" else {"https"}) or not parsed.netloc or parsed.username or parsed.password:
        raise ValueError(name)
    return value.rstrip("/")


def _validated_values(payload: Any, settings: Settings) -> dict[str, Any]:
    if not isinstance(payload, dict) or set(payload) != PUBLIC_FIELDS:
        raise ValueError("fields")
    result: dict[str, Any] = {}
    for key, value in payload.items():
        if key in BOOL_FIELDS:
            if not isinstance(value, bool): raise ValueError(key)
        elif key in INT_RANGES:
            low, high = INT_RANGES[key]
            if type(value) is not int or not low <= value <= high: raise ValueError(key)
        elif key in URL_FIELDS:
            value = _valid_url(key, value, settings.env)
        elif value is not None and (not isinstance(value, str) or len(value) > 1000 or "\x00" in value):
            raise ValueError(key)
        result[key] = value
    if result["storage_backend"] not in {"local", "oss"}: raise ValueError("storage_backend")
    if result["storage_backend"] == "oss" and not all(result.get(key) for key in ("oss_endpoint", "oss_bucket")): raise ValueError("oss")
    return result


def _apply(app, item: SystemConfiguration | None) -> None:
    if item is None:
        return
    settings: Settings = app.config["SETTINGS"]
    updates = dict(item.values_json)
    updates.update(_decrypt(item))
    try:
        next_settings = Settings.model_validate({**settings.model_dump(), **updates})
    except Exception:
        return
    app.config["SETTINGS"] = next_settings
    dsh_runtime.init_app(app, next_settings)
    object_storage.init_app(app, next_settings)


def apply_persisted_configuration(app) -> None:
    try:
        with app.app_context(), db.session() as session:
            _apply(app, session.get(SystemConfiguration, ROW_ID))
    except SQLAlchemyError:
        # Fresh installations call Alembic before the first normal server start.
        return


@blueprint.get("")
@require_role(ROLE_ADMIN)
def get_configuration():
    with db.session() as session:
        return _serialize(session.get(SystemConfiguration, ROW_ID), current_app.config["SETTINGS"]), 200


@blueprint.put("")
@require_role(ROLE_ADMIN)
def put_configuration():
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict) or set(payload) != {"values", "secrets", "clear_secrets", "version"}:
        return error_response("invalid_configuration", "系统配置参数不完整。", 400)
    try:
        values = _validated_values(payload["values"], current_app.config["SETTINGS"])
        secrets_payload = payload["secrets"]
        clear = payload["clear_secrets"]
        if not isinstance(secrets_payload, dict) or set(secrets_payload) - SECRET_FIELDS or not isinstance(clear, list) or set(clear) - SECRET_FIELDS:
            raise ValueError("secrets")
        if any(not isinstance(value, str) or len(value) > 4096 or any(c in value for c in "\r\n\x00") for value in secrets_payload.values()):
            raise ValueError("secrets")
    except ValueError:
        return error_response("invalid_configuration", "系统配置格式无效，请检查地址、端口和必填项。", 400)
    with db.session() as session, session.begin():
        item = session.scalar(select(SystemConfiguration).where(SystemConfiguration.id == ROW_ID).with_for_update())
        if item is None:
            if payload["version"] != 0:
                return error_response("stale_version", "配置已变更，请刷新后重试。", 409)
            item = SystemConfiguration(id=ROW_ID, values_json={})
            session.add(item)
        elif payload["version"] != item.version:
            return error_response("stale_version", "配置已变更，请刷新后重试。", 409)
        secrets = _decrypt(item)
        for key in clear: secrets.pop(key, None)
        for key, value in secrets_payload.items():
            if value.strip(): secrets[key] = value.strip()
        if values["dsh_enabled"] and not secrets.get("dsh_service_token"):
            return error_response("invalid_configuration", "启用 AI Server 前必须配置服务令牌。", 400)
        if values["clawbot_enabled"] and not secrets.get("clawbot_gateway_token"):
            return error_response("invalid_configuration", "启用 ClawBot 前必须配置网关令牌。", 400)
        if values["storage_backend"] == "oss" and not all(secrets.get(key) for key in ("oss_access_key_id", "oss_access_key_secret")):
            return error_response("invalid_configuration", "使用 OSS 前必须配置 AccessKey。", 400)
        item.values_json = values
        item.secrets_ciphertext = _cipher().encrypt(json.dumps(secrets, ensure_ascii=False).encode()).decode() if secrets else ""
        item.version = (item.version or 0) + 1
        session.flush()
        result = _serialize(item, current_app.config["SETTINGS"])
    _apply(current_app._get_current_object(), item)
    return result, 200
