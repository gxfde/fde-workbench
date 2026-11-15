from __future__ import annotations

from typing import Any

from flask import Blueprint, current_app, g, jsonify, request
from redis.exceptions import RedisError

from fde_api.auth.confirm_throttle import (
    confirm_attempts_blocked,
    record_confirm_failure,
)
from fde_api.auth.decorators import require_auth
from fde_api.auth.models import User
from fde_api.auth.service import (
    AuthServiceError,
    INVALID_CURRENT_PASSWORD,
    TokenPair,
    change_password as change_user_password,
    login as login_user,
    normalize_username,
    record_state_blocked_login,
    revoke_refresh_token,
    rotate_refresh_token,
    verify_current_password,
)
from fde_api.errors import error_response


auth_blueprint = Blueprint("auth", __name__, url_prefix="/api/v1/auth")

# 登录失败限流（Redis 计数，按「用户名 + 来源 IP」复合键，G7）：连续失败 5 次锁
# 15 分钟，成功即清零。复合键保证单 IP 的连错只锁「该 IP → 该用户」对，无法再
# 从一个 IP 定向锁死任意用户名。API 已只绑回环，这层是纵深防御。
LOGIN_RATE_MAX_ATTEMPTS = 5
LOGIN_RATE_WINDOW_SECONDS = 900


def _login_fail_key(username: str, remote_addr: str | None) -> str:
    ip = remote_addr or "unknown"
    return f"auth:login_fail:{normalize_username(username)}:{ip}"


def _login_throttle(username: str, remote_addr: str | None) -> int | None:
    """记一次尝试；若已超限返回应等待秒数（未超限返回 None）。

    在校验密码之前调用：被锁的请求不再做 argon2 计算。

    Redis 不可用时的行为可配置（G7，不得静默）：
      fail-open（默认，FDE_LOGIN_RATE_FAIL_CLOSED 未设）→ 记 WARNING 后放行，
        认证不依赖限流器，本机回环部署下 Redis 挂了不挡业务登录；
      fail-closed（FDE_LOGIN_RATE_FAIL_CLOSED=1，对外暴露部署从严）→ 记 WARNING
        后一律按超限处理（429）。
    """
    try:
        redis = current_app.extensions["fde_api_redis"]
    except KeyError:
        return None
    settings = current_app.config["SETTINGS"]
    key = _login_fail_key(username, remote_addr)
    try:
        attempts = redis.incr(key)
        if attempts == 1:
            redis.expire(key, LOGIN_RATE_WINDOW_SECONDS)
        if attempts > LOGIN_RATE_MAX_ATTEMPTS:
            return max(int(redis.ttl(key) or LOGIN_RATE_WINDOW_SECONDS), 1)
    except RedisError:
        current_app.logger.warning(
            "login rate limiter unavailable (username=%s ip=%s); failing %s",
            username,
            remote_addr,
            "closed" if settings.login_rate_fail_closed else "open",
        )
        if settings.login_rate_fail_closed:
            return LOGIN_RATE_WINDOW_SECONDS
        return None
    return None


def _login_clear(username: str, remote_addr: str | None) -> None:
    """登录成功清零「该用户名 + 该 IP」的失败计数。"""
    try:
        redis = current_app.extensions["fde_api_redis"]
    except KeyError:
        return
    try:
        redis.delete(_login_fail_key(username, remote_addr))
    except RedisError:
        pass


@auth_blueprint.post("/login")
def login_route():
    payload = _json_payload()
    values = _required_strings(payload, "username", "password", "device_label")
    if values is None:
        return _invalid_request()
    retry_after = _login_throttle(values[0], request.remote_addr)
    if retry_after is not None:
        return error_response(
            "login_rate_limited",
            f"登录失败次数过多，请约 {retry_after // 60 + 1} 分钟后再试。",
            429,
        )
    try:
        user, pair = login_user(*values)
    except AuthServiceError as error:
        # 多客户 M2（ADR-M4 §5）：注册状态拦截的登录 4xx 且留痕（尽力而为）。
        record_state_blocked_login(values[0], error.code)
        return _service_error(error)
    _login_clear(values[0], request.remote_addr)
    return jsonify(
        {
            "data": {"user": _serialize_user(user), **_serialize_token_pair(pair)},
            "error": None,
        }
    )


@auth_blueprint.post("/refresh")
def refresh_route():
    values = _required_strings(_json_payload(), "refresh_token")
    if values is None:
        return _invalid_request()
    try:
        user, pair = rotate_refresh_token(values[0])
    except AuthServiceError as error:
        return _service_error(error)
    return jsonify(
        {
            "data": {"user": _serialize_user(user), **_serialize_token_pair(pair)},
            "error": None,
        }
    )


@auth_blueprint.post("/logout")
def logout_route():
    values = _required_strings(_json_payload(), "refresh_token")
    if values is None:
        return _invalid_request()
    revoke_refresh_token(values[0])
    return jsonify({"data": {"revoked": True}, "error": None})


@auth_blueprint.get("/me")
@require_auth
def me_route():
    return jsonify({"data": _serialize_user(g.current_user), "error": None})


@auth_blueprint.post("/verify-password")
@require_auth
def verify_password_route():
    values = _required_strings(_json_payload(), "password")
    if values is None:
        return _invalid_request()
    # CR-047：密码确认尝试限流（沿 ai 确认闸同 key 同阈值——持会话不等于可无限试错）。
    if confirm_attempts_blocked(g.current_user.id):
        return _service_error(
            AuthServiceError(
                "too_many_attempts",
                "密码错误次数过多，请 15 分钟后重试。",
                429,
            )
        )
    try:
        valid = verify_current_password(g.current_user, values[0])
    except AuthServiceError as error:
        return _service_error(error)
    if not valid:
        record_confirm_failure(g.current_user.id)
        return error_response(*INVALID_CURRENT_PASSWORD)
    return jsonify({"data": {"valid": True}, "error": None})


@auth_blueprint.post("/change-password")
@require_auth
def change_password_route():
    values = _required_strings(
        _json_payload(), "current_password", "new_password"
    )
    if values is None:
        return _invalid_request()
    try:
        user, pair = change_user_password(g.current_user, *values)
    except AuthServiceError as error:
        return _service_error(error)
    return jsonify(
        {
            "data": {"user": _serialize_user(user), **_serialize_token_pair(pair)},
            "error": None,
        }
    )


def _json_payload() -> dict[str, Any] | None:
    payload = request.get_json(silent=True)
    return payload if isinstance(payload, dict) else None


def _required_strings(
    payload: dict[str, Any] | None, *fields: str
) -> tuple[str, ...] | None:
    if payload is None:
        return None
    values = tuple(payload.get(field) for field in fields)
    if any(not isinstance(value, str) or not value for value in values):
        return None
    return values


def _serialize_user(user: User) -> dict[str, Any]:
    return {
        "id": user.id,
        "username": user.username,
        "display_name": user.display_name,
        "role": user.role,
        # 多客户 M2：注册生命周期字段（email 可空＝存量/admin 建号用户）。
        "email": user.email,
        "registration_state": user.registration_state,
        "must_change_password": user.must_change_password,
        "is_active": user.is_active,
    }


def _serialize_token_pair(pair: TokenPair) -> dict[str, str]:
    return {
        "access_token": pair.access_token,
        "refresh_token": pair.refresh_token,
        "access_expires_at": pair.access_expires_at.isoformat(),
        "refresh_expires_at": pair.refresh_expires_at.isoformat(),
    }


def _invalid_request():
    return error_response(
        "invalid_request", "The request body is missing required fields.", 400
    )


def _service_error(error: AuthServiceError):
    return error_response(error.code, error.message, error.status)
