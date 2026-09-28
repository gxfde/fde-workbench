"""User-owned and public model settings. Plaintext credentials never leave server code."""
from __future__ import annotations

import ipaddress
import os
from base64 import urlsafe_b64encode
from hashlib import sha256
from socket import SOCK_STREAM, getaddrinfo
from typing import Any
from urllib.parse import urlparse

from cryptography.fernet import Fernet, InvalidToken
from flask import current_app
from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Index, String, Text, or_, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from fde_api.auth.models import Base, User
from fde_api.control.access import effective_ai_access
from fde_api.control.service import ControlServiceError
from fde_api.extensions import db
from fde_api.workbench.models import TimestampMixin, VersionedMixin, new_uuid


class ModelPreference(Base, TimestampMixin, VersionedMixin):
    __tablename__ = "ai_model_preferences"
    __table_args__ = (
        CheckConstraint("scope IN ('personal', 'public')", name="ck_model_preferences_scope"),
        Index("ix_model_preferences_owner", "owner_user_id", "scope"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    scope: Mapped[str] = mapped_column(String(20), nullable=False)
    owner_user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    provider: Mapped[str] = mapped_column(String(80), nullable=False)
    base_url: Mapped[str] = mapped_column(String(500), nullable=False)
    model: Mapped[str] = mapped_column(String(160), nullable=False)
    credential_ciphertext: Mapped[str] = mapped_column(Text, nullable=False, default="")
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    supports_tools: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


def _cipher() -> Fernet:
    key = current_app.config.get("MODEL_CREDENTIAL_KEY") or os.environ.get("FDE_MODEL_CREDENTIAL_KEY", "")
    if not key:
        key = urlsafe_b64encode(sha256(current_app.config["SETTINGS"].jwt_secret.encode()).digest())
    try:
        return Fernet(key.encode() if isinstance(key, str) else key)
    except (ValueError, TypeError) as error:
        raise ControlServiceError("credential_storage_unavailable", "服务端尚未配置模型密钥加密，暂不能保存 API Key。", 503) from error


def credentials_ready() -> bool:
    try:
        _cipher()
        return True
    except ControlServiceError:
        return False


def serialize_preference(item: ModelPreference, user: User) -> dict[str, Any]:
    return {"id": item.id, "scope": item.scope, "name": item.name, "provider": item.provider,
            "base_url": item.base_url, "model": item.model, "is_default": item.is_default,
            "supports_tools": item.supports_tools, "credential_configured": bool(item.credential_ciphertext),
            "can_edit": item.owner_user_id == user.id or (item.scope == "public" and effective_ai_access(user)[0] == "system_operator"),
            "version": item.version}


def list_model_preferences(*, user: User) -> list[dict[str, Any]]:
    with db.session() as session:
        items = session.scalars(select(ModelPreference).where(or_(ModelPreference.owner_user_id == user.id, ModelPreference.scope == "public")).order_by(ModelPreference.scope, ModelPreference.is_default.desc(), ModelPreference.name))
        return [serialize_preference(item, user) for item in items]


def _validate_url(value: Any) -> str:
    if not isinstance(value, str) or len(value) > 500:
        raise ControlServiceError("invalid_model", "请输入有效的 HTTPS 模型 API 地址。", 400)
    parsed = urlparse(value)
    host = parsed.hostname or ""
    if parsed.scheme != "https" or not host or parsed.username or parsed.password or parsed.query or parsed.fragment or host.lower() == "localhost" or host.lower().endswith((".localhost", ".local", ".internal")):
        raise ControlServiceError("invalid_model", "模型 API 必须使用公开的 HTTPS 地址。", 400)
    try:
        addresses = [record[4][0] for record in getaddrinfo(host, parsed.port or 443, type=SOCK_STREAM)]
    except (OSError, ValueError) as error:
        raise ControlServiceError("invalid_model", "模型 API 域名无法解析，请检查地址。", 400) from error
    if not addresses or any(not ipaddress.ip_address(address).is_global for address in addresses):
        raise ControlServiceError("invalid_model", "模型 API 不可指向本地或内网地址。", 400)
    return value.rstrip("/")


def save_model_preference(*, user: User, payload: dict[str, Any]) -> dict[str, Any]:
    required = {"scope", "name", "provider", "base_url", "model", "api_key", "is_default", "supports_tools"}
    if not required.issubset(payload) or set(payload) - required - {"id", "version"}:
        raise ControlServiceError("invalid_model", "模型配置参数无效。", 400)
    scope = payload["scope"]
    if scope not in {"personal", "public"}:
        raise ControlServiceError("invalid_model", "模型范围无效。", 400)
    if scope == "public" and effective_ai_access(user)[0] != "system_operator":
        raise ControlServiceError("forbidden", "只有管理员可以管理公共模型。", 403)
    for name, length in (("name", 160), ("provider", 80), ("model", 160)):
        if not isinstance(payload[name], str) or not payload[name].strip() or len(payload[name]) > length:
            raise ControlServiceError("invalid_model", "请完整填写模型名称、供应商与模型标识。", 400)
    if not isinstance(payload["api_key"], str) or len(payload["api_key"]) > 4096 or any(c in payload["api_key"] for c in "\r\n") or not isinstance(payload["is_default"], bool) or not isinstance(payload["supports_tools"], bool):
        raise ControlServiceError("invalid_model", "模型配置参数无效。", 400)
    base_url = _validate_url(payload["base_url"])
    if payload["provider"] == "typesafe" and (payload["model"] != "jev-1.13.0" or base_url != "https://api.typesafe.ai/v1"
                                             or payload["is_default"] or payload["supports_tools"]):
        raise ControlServiceError("invalid_model", "Jev 仅用于 Skill 判断：请使用官方地址与 jev-1.13.0，并取消“默认模型”和“支持工具调用”。", 400)
    with db.session() as session, session.begin():
        # Lock owner before default changes so parallel saves cannot create two defaults.
        owner_lock = select(User).where(User.role == "admin").order_by(User.id).limit(1) if scope == "public" else select(User).where(User.id == user.id)
        session.scalar(owner_lock.with_for_update())
        item = session.get(ModelPreference, payload["id"]) if payload.get("id") else None
        if payload.get("id") and item is None:
            raise ControlServiceError("not_found", "模型配置不存在。", 404)
        if item is not None:
            if not ((item.owner_user_id == user.id and item.scope == "personal") or (item.scope == "public" and effective_ai_access(user)[0] == "system_operator")) or item.scope != scope:
                raise ControlServiceError("forbidden", "无权修改此模型配置。", 403)
            if payload.get("version") != item.version:
                raise ControlServiceError("stale_version", "配置已被更新，请重新打开后再保存。", 409)
            item.version += 1
        else:
            item = ModelPreference(scope=scope, owner_user_id=user.id if scope == "personal" else None)
            session.add(item)
        api_key = payload["api_key"].strip()
        if api_key:
            item.credential_ciphertext = _cipher().encrypt(api_key.encode()).decode()
        elif not item.credential_ciphertext and payload["is_default"]:
            raise ControlServiceError("invalid_model", "未配置 API Key 的模型只能保存为非默认草稿。", 400)
        for name in ("name", "provider", "model"):
            setattr(item, name, payload[name].strip())
        item.base_url, item.supports_tools = base_url, payload["supports_tools"]
        if payload["is_default"]:
            peers = session.scalars(select(ModelPreference).where(ModelPreference.scope == scope, ModelPreference.owner_user_id == item.owner_user_id).with_for_update())
            for peer in peers:
                if peer.id != item.id and peer.is_default:
                    peer.is_default = False
                    peer.version += 1
        item.is_default = payload["is_default"]
        session.flush()
        return serialize_preference(item, user)


def delete_model_preference(*, user: User, preference_id: str, expected_version: int | None = None) -> dict[str, Any]:
    with db.session() as session, session.begin():
        item = session.get(ModelPreference, preference_id, with_for_update=True)
        if item is None:
            raise ControlServiceError("not_found", "模型配置不存在。", 404)
        if expected_version is not None and item.version != expected_version:
            raise ControlServiceError("stale_version", "模型配置已经变化，请重新确认删除。", 409)
        if not ((item.owner_user_id == user.id and item.scope == "personal") or (item.scope == "public" and effective_ai_access(user)[0] == "system_operator")):
            raise ControlServiceError("forbidden", "无权删除此模型配置。", 403)
        session.delete(item)
        return {"id": preference_id, "deleted": True}


def resolve_model_preference(session: Session, user_id: str, preference_id: str | None = None) -> dict[str, Any]:
    """Server-only. Caller must never serialize this result into API responses/logs."""
    user = session.get(User, user_id)
    if user is None or not user.is_active or effective_ai_access(user)[0] == "disabled":
        raise ControlServiceError("forbidden", "当前账户无权使用 AI。", 403)
    query = select(ModelPreference).where(or_(ModelPreference.owner_user_id == user_id, ModelPreference.scope == "public"))
    if preference_id:
        query = query.where(ModelPreference.id == preference_id)
    else:
        query = query.where(ModelPreference.is_default.is_(True)).order_by(ModelPreference.scope, ModelPreference.id)
    item = session.scalar(query.limit(1))
    if item is not None:
        if not item.credential_ciphertext:
            raise ControlServiceError("model_not_configured", "该模型尚未配置 API Key，请在模型管理中补充。", 409)
        try:
            key = _cipher().decrypt(item.credential_ciphertext.encode()).decode()
        except InvalidToken as error:
            raise ControlServiceError("credential_unavailable", "模型密钥无法解密，请联系管理员。", 503) from error
        return {"id": item.id, "provider": item.provider, "base_url": item.base_url, "model": item.model, "api_key": key, "supports_tools": item.supports_tools}
    if preference_id:
        raise ControlServiceError("not_found", "模型配置不存在或无权使用。", 404)
    settings = current_app.config["SETTINGS"]
    key = getattr(settings, "deepseek_api_key", "")
    if not key:
        raise ControlServiceError("model_not_configured", "请先在 AI 与扩展的模型管理中配置模型。", 409)
    plaintext = key.get_secret_value() if hasattr(key, "get_secret_value") else key
    return {"id": "system-default", "provider": "deepseek", "base_url": getattr(settings, "deepseek_base_url", "https://api.deepseek.com"), "model": settings.deepseek_industry_template_model, "api_key": plaintext, "supports_tools": True}
