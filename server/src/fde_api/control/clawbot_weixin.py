"""Tencent iLink QR login and transport, following Tencent/openclaw-weixin 2.4.8.

Only Tencent-issued QR URLs are encoded. No locally invented pairing codes.
Provider credentials, QR secrets, inbox bodies and cursors are encrypted at rest.
"""
from __future__ import annotations

import base64
import io
import json
import os
import secrets
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from typing import Any
from urllib.parse import urlparse

import requests
from cryptography.fernet import Fernet, InvalidToken
from flask import Blueprint, current_app, g, jsonify, request
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from fde_api.auth.decorators import require_auth
from fde_api.control.models import ChannelBinding
from fde_api.control.service import ControlServiceError
from fde_api.control.weixin_models import WeixinAccount, WeixinInbox
from fde_api.errors import error_response
from fde_api.extensions import db

FIXED_BASE = "https://ilinkai.weixin.qq.com"
weixin_blueprint = Blueprint("weixin", __name__, url_prefix="/api/v1/account/wechat-clawbot/qr")


def _enabled() -> bool:
    settings = current_app.config["SETTINGS"]
    return bool(getattr(settings, "weixin_enabled", False) or os.environ.get("FDE_WEIXIN_ENABLED", "").lower() in {"1", "true", "yes"})


def _cipher() -> Fernet:
    settings = current_app.config["SETTINGS"]
    value = getattr(settings, "weixin_credential_key", None)
    key = value.get_secret_value() if hasattr(value, "get_secret_value") else value
    key = key or os.environ.get("FDE_WEIXIN_CREDENTIAL_KEY", "")
    try:
        return Fernet(key.encode("ascii"))
    except (ValueError, TypeError, UnicodeError):
        raise ControlServiceError("weixin_not_configured", "微信扫码服务尚未完成安全配置，请联系管理员。", 503) from None


def seal(payload: dict) -> str:
    return _cipher().encrypt(json.dumps(payload, ensure_ascii=False).encode()).decode()


def unseal(value: str) -> dict:
    if not value:
        return {}
    try:
        return json.loads(_cipher().decrypt(value.encode()).decode())
    except (InvalidToken, ValueError):
        raise ControlServiceError("weixin_credential_unavailable", "微信凭据暂不可用，请联系管理员检查加密密钥。", 503) from None


def trusted_url(value: str, *, api: bool = False) -> str:
    try:
        parsed = urlparse(value)
        valid = (parsed.scheme == "https" and parsed.hostname is not None
                 and parsed.hostname.endswith(".weixin.qq.com") and parsed.port in {None, 443}
                 and parsed.username is None and parsed.password is None and not parsed.fragment
                 and (not api or (parsed.path in {"", "/"} and not parsed.query)))
    except ValueError:
        valid = False
    if not valid:
        raise ControlServiceError("weixin_invalid_upstream", "微信服务返回了无效的安全地址，请稍后重试。", 502)
    return value.rstrip("/") if api else value


class WeixinClient:
    def call(self, endpoint: str, *, base_url: str = FIXED_BASE, token: str = "", payload: dict | None = None,
             params: dict | None = None, timeout: int = 15, method: str = "POST") -> dict:
        base_url = trusted_url(base_url, api=True)
        headers = {"Content-Type": "application/json", "AuthorizationType": "ilink_bot_token",
                   "X-WECHAT-UIN": base64.b64encode(str(secrets.randbits(32)).encode()).decode(),
                   "iLink-App-Id": "bot", "iLink-App-ClientVersion": str((2 << 16) | (4 << 8) | 8)}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        body = {**(payload or {}), "base_info": {"channel_version": "2.4.8", "bot_agent": "FDE-Workbench/1.0.0"}}
        try:
            with requests.request(method, f"{base_url}/ilink/bot/{endpoint}", headers=headers,
                                  json=body if method == "POST" else None, params=params,
                                  timeout=(5, timeout), allow_redirects=False, stream=True) as response:
                if response.status_code != 200:
                    raise ControlServiceError("weixin_upstream_unavailable", "微信服务暂时不可用，请稍后重试。", 502)
                content = bytearray()
                for chunk in response.iter_content(65536):
                    content.extend(chunk)
                    if len(content) > 2_000_000:
                        raise ValueError("response_too_large")
                data = json.loads(content)
            if not isinstance(data, dict):
                raise ValueError("invalid_response")
            if data.get("errcode") == -14 or data.get("ret") == -14:
                raise ControlServiceError("weixin_session_expired", "微信登录已失效，请重新扫码绑定。", 409)
            if data.get("ret", 0) != 0 or data.get("errcode", 0) != 0:
                raise ControlServiceError("weixin_upstream_rejected", "微信服务暂未接受此操作，请稍后重试。", 502)
            return data
        except requests.Timeout:
            if endpoint == "get_qrcode_status":
                return {"status": "wait"}
            if endpoint == "getupdates":
                return {"msgs": []}
            raise ControlServiceError("weixin_upstream_timeout", "微信服务响应超时，请稍后重试。", 504) from None
        except (requests.RequestException, ValueError):
            # Never include exception strings: they may contain URLs with QR or auth secrets.
            raise ControlServiceError("weixin_upstream_unavailable", "无法连接微信服务，请稍后重试。", 502) from None


def client() -> WeixinClient:
    return current_app.extensions.get("fde_weixin_client") or WeixinClient()


def _account(session, user_id: str, *, lock: bool = False):
    query = select(WeixinAccount, ChannelBinding).join(ChannelBinding).where(ChannelBinding.user_id == user_id)
    return session.execute(query.with_for_update() if lock else query).first()


def _summary(account: WeixinAccount | None, binding: ChannelBinding | None) -> dict:
    login_status = account.login_status if account else "idle"
    expires = account.login_expires_at if account else None
    if expires and expires <= datetime.now(UTC) and login_status not in {"confirmed", "idle"}:
        login_status = "expired"
    return {"status": binding.status if binding else "unbound", "channel": "wechat_clawbot",
            "commands_enabled": bool(binding and binding.commands_enabled and binding.status == "active"),
            "notifications_enabled": bool(binding and binding.notifications_enabled and binding.status == "active"),
            "login_status": login_status, "enabled": _enabled(),
            "connected": bool(account and account.credentials_encrypted and binding and binding.status == "active"),
            "binding_expires_at": expires.isoformat() if expires else None,
            "last_poll_at": account.last_poll_at.isoformat() if account and account.last_poll_at else None,
            "last_error_code": account.last_error_code if account else ""}


def status(user_id: str) -> dict:
    with db.session() as session:
        row = _account(session, user_id)
        return _summary(*row) if row else _summary(None, None)


def begin_login(user_id: str) -> dict:
    if not _enabled():
        raise ControlServiceError("weixin_disabled", "微信扫码通道尚未启用，请联系管理员。", 503)
    _cipher()
    with db.session() as session:
        row = _account(session, user_id)
        # Bound authenticated generation to protect the upstream from rapid clicks.
        # No QR secrets are copied into rate-limit state or logs.
        if row and row[0].login_expires_at and row[0].login_status in {"wait", "scaned", "scaned_but_redirect", "need_verifycode"}:
            issued_at = row[0].login_expires_at - timedelta(minutes=5)
            if issued_at > datetime.now(UTC) - timedelta(seconds=3):
                raise ControlServiceError("weixin_login_too_frequent", "刚刚已生成二维码，请稍后再试。", 429)
    qr = client().call("get_bot_qrcode", params={"bot_type": "3"}, payload={"local_token_list": []})
    token, url = qr.get("qrcode"), qr.get("qrcode_img_content")
    if not isinstance(token, str) or not token or len(token) > 4096 or not isinstance(url, str) or len(url.encode()) > 2000:
        raise ControlServiceError("weixin_invalid_qr", "微信服务未返回有效二维码，请稍后重试。", 502)
    trusted_url(url)
    # Pure SVG QR, encoded from Tencent's returned URL; does not load remote image origins.
    import qrcode
    import qrcode.image.svg
    image = qrcode.make(url, image_factory=qrcode.image.svg.SvgPathImage, box_size=6, border=4)
    output = io.BytesIO()
    image.save(output)
    with db.session() as session, session.begin():
        binding = session.scalar(select(ChannelBinding).where(ChannelBinding.user_id == user_id, ChannelBinding.channel == "wechat_clawbot").with_for_update())
        if binding is None:
            binding = ChannelBinding(user_id=user_id, channel="wechat_clawbot", status="pending")
            session.add(binding)
            session.flush()
        account = session.scalar(select(WeixinAccount).where(WeixinAccount.binding_id == binding.id))
        if account is None:
            account = WeixinAccount(binding_id=binding.id)
            session.add(account)
        login_id = secrets.token_urlsafe(24)
        account.login_encrypted = seal({"qrcode": token, "url": url, "base_url": FIXED_BASE, "login_id": login_id})
        account.login_expires_at = datetime.now(UTC) + timedelta(minutes=5)
        account.login_status = "wait"
        if binding.status != "active":
            binding.status = "pending"
        session.flush()
        return {**_summary(account, binding), "login_id": login_id,
                "qr_image": "data:image/svg+xml;base64," + base64.b64encode(output.getvalue()).decode()}


def poll_login(user_id: str, login_id: str, verify_code: str = "") -> dict:
    if not _enabled():
        raise ControlServiceError("weixin_disabled", "微信扫码通道尚未启用，请联系管理员。", 503)
    with db.session() as session:
        row = _account(session, user_id)
        if not row or not row[0].login_encrypted:
            raise ControlServiceError("weixin_login_missing", "请先生成微信登录二维码。", 404)
        account, binding = row
        login = unseal(account.login_encrypted)
        if not secrets.compare_digest(login.get("login_id", ""), login_id):
            raise ControlServiceError("weixin_login_changed", "二维码已更新，请扫描最新二维码。", 409)
        if account.login_expires_at <= datetime.now(UTC):
            return {**_summary(account, binding), "login_status": "expired"}
        encrypted_before = account.login_encrypted
        if account.login_status == "confirmed":
            return _summary(account, binding)
    params = {"qrcode": login["qrcode"]}
    if verify_code:
        params["verify_code"] = verify_code
    result = client().call("get_qrcode_status", base_url=login["base_url"], params=params, method="GET", timeout=12)
    upstream_status = result.get("status", "wait")
    allowed = {"wait", "scaned", "confirmed", "expired", "scaned_but_redirect", "need_verifycode", "verify_code_blocked", "binded_redirect"}
    if upstream_status not in allowed:
        raise ControlServiceError("weixin_invalid_status", "微信返回未知绑定状态，请稍后重试。", 502)
    try:
        with db.session() as session, session.begin():
            row = _account(session, user_id, lock=True)
            if not row or row[0].login_encrypted != encrypted_before:
                raise ControlServiceError("weixin_login_changed", "二维码已更新，请扫描最新二维码。", 409)
            account, binding = row
            account.login_status = upstream_status
            if upstream_status == "scaned_but_redirect":
                redirect = result.get("redirect_host", "")
                login["base_url"] = trusted_url("https://" + redirect, api=True)
                account.login_encrypted = seal(login)
            elif upstream_status == "confirmed":
                required = ("bot_token", "ilink_bot_id", "ilink_user_id")
                if any(not isinstance(result.get(key), str) or not result[key] or len(result[key]) > 4096 for key in required):
                    raise ControlServiceError("weixin_identity_missing", "微信未返回完整的扫码者身份，请重新扫码。", 502)
                base_url = trusted_url(result.get("baseurl") or FIXED_BASE, api=True)
                account.credentials_encrypted = seal({**{key: result[key] for key in required}, "base_url": base_url})
                account.cursor_encrypted = ""
                account.last_error_code = ""
                binding.external_subject_hash = sha256(result["ilink_user_id"].encode()).hexdigest()
                binding.status = "active"
                binding.commands_enabled = binding.notifications_enabled = True
                binding.channel_display_name = "微信 ClawBot"
                binding.binding_code_digest = None
                binding.binding_expires_at = None
                binding.last_seen_at = datetime.now(UTC)
                binding.version += 1
                # Destroy the provider QR secret after successful binding.
                account.login_encrypted = seal({"login_id": login_id})
            elif upstream_status == "binded_redirect":
                # No fresh credentials are supplied; never claim a different account is bound.
                if not account.credentials_encrypted or binding.status != "active":
                    raise ControlServiceError("weixin_rebind_required", "微信提示已有连接，但本账户无可用凭据。请在微信中解除旧连接后重新扫码。", 409)
                account.login_status = "confirmed"
            session.flush()
            return _summary(account, binding)
    except IntegrityError:
        raise ControlServiceError("wechat_already_bound", "该微信已绑定其他工作台账户，请先解除原绑定。", 409) from None


def unbind(user_id: str) -> dict:
    with db.session() as session, session.begin():
        row = _account(session, user_id, lock=True)
        if not row:
            return _summary(None, None)
        account, binding = row
        account.credentials_encrypted = account.login_encrypted = account.cursor_encrypted = ""
        account.login_status = "idle"
        account.login_expires_at = None
        binding.status = "revoked"
        binding.external_subject_hash = None
        binding.commands_enabled = binding.notifications_enabled = False
        binding.version += 1
        return _summary(account, binding)


@weixin_blueprint.get("")
@require_auth
def status_route():
    return jsonify({"data": status(g.current_user.id), "error": None})


@weixin_blueprint.post("")
@require_auth
def begin_route():
    try:
        return jsonify({"data": begin_login(g.current_user.id), "error": None}), 201
    except ControlServiceError as error:
        return error_response(error.code, error.message, error.status)


@weixin_blueprint.post("/poll")
@require_auth
def poll_route():
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict) or not isinstance(payload.get("login_id"), str) or not 20 <= len(payload["login_id"]) <= 100:
        return error_response("invalid_request", "登录会话无效。", 400)
    verify = payload.get("verify_code", "")
    if not isinstance(verify, str) or (verify and (not verify.isascii() or not verify.isdigit() or not 4 <= len(verify) <= 12)):
        return error_response("invalid_request", "请输入手机微信显示的数字验证码。", 400)
    try:
        return jsonify({"data": poll_login(g.current_user.id, payload["login_id"], verify), "error": None})
    except ControlServiceError as error:
        return error_response(error.code, error.message, error.status)


@weixin_blueprint.post("/unbind")
@require_auth
def unbind_route():
    return jsonify({"data": unbind(g.current_user.id), "error": None})
