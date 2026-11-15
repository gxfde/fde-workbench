"""多客户 M2：四入口统一注册路由（任务书 §7-M2；ADR-M4）。

公开面（部署闸内）：``POST /register/<entry>`` 四入口、``POST
/registrations/verify``、``POST /registrations/resend``、``GET
/registrations/entries``；admin 审核簿记面（不过部署闸——已注册账号的生命
周期管理独立于公开入口的可达性）：``GET /registrations``、``POST
/registrations/<user_id>/{review,suspend,reinstate}``。

治理面**不进 api_catalog**（G6/诊断线同款纪律）。部署闸关闭时公开面一律
404（不确认面存在——OWNER 拍板 fail-closed 过渡形态）。
"""
from __future__ import annotations

from typing import Any

from flask import Blueprint, current_app, g, jsonify, request
from redis.exceptions import RedisError

from fde_api.auth.decorators import require_role
from fde_api.commercial.service import CommercialServiceError
from fde_api.config import Settings
from fde_api.errors import error_response
from fde_api.extensions import db
from fde_api.users.service import UserServiceError
from fde_api.registration.models import ENTRY_TYPES
from fde_api.registration.service import (
    RegistrationError,
    _ensure_surface_open,
    dispatch_verification_email,
    list_registrations,
    register_account,
    reinstate_registration,
    resend_verification,
    review_entries,
    review_registration,
    suspend_registration,
    verify_email,
)

registration_blueprint = Blueprint("registration", __name__, url_prefix="/api/v1/auth")

# 四入口统一注册限流（ADR-M4 §3-2；盘点表 K8「扩展此模式」）：键族
# ``auth:register:{ip}``，按 IP 每日计数——上限 = 配置位
# ``registration_ip_daily_limit``（**保守占位缺省，试点前须填实数**）。
# register 与 resend 共桶（resend 逐请求都撞库，同属注册面滥用面）；verify
# 不限（令牌本身即一次性凭据，无放大效应）。Redis 不可用行为复用既有
# ``registration_rate_fail_closed`` 配置（G6 K8 同款语义，不得静默）。
REGISTER_RATE_WINDOW_SECONDS = 86400


def _register_rate_key(remote_addr: str | None) -> str:
    ip = remote_addr or "unknown"
    return f"auth:register:{ip}"


def _register_throttle(remote_addr: str | None) -> int | None:
    """记一次注册面尝试；超限返回应等待秒数（未超限返回 None）。"""
    try:
        redis = current_app.extensions["fde_api_redis"]
    except KeyError:
        return None
    settings = current_app.config["SETTINGS"]
    key = _register_rate_key(remote_addr)
    limit = settings.registration_ip_daily_limit
    try:
        attempts = redis.incr(key)
        if attempts == 1:
            redis.expire(key, REGISTER_RATE_WINDOW_SECONDS)
        if attempts > limit:
            return max(int(redis.ttl(key) or REGISTER_RATE_WINDOW_SECONDS), 1)
    except RedisError:
        current_app.logger.warning(
            "unified registration rate limiter unavailable (ip=%s); failing %s",
            remote_addr,
            "closed" if settings.registration_rate_fail_closed else "open",
        )
        if settings.registration_rate_fail_closed:
            return REGISTER_RATE_WINDOW_SECONDS
        return None
    return None


@registration_blueprint.errorhandler(RegistrationError)
def _registration_error(error: RegistrationError):
    return error_response(error.code, error.message, error.status)


@registration_blueprint.errorhandler(CommercialServiceError)
def _commercial_error(error: CommercialServiceError):
    """enterprise 入口委托 G6 服务层（register_enterprise）——其商业语义错误
    （invalid_subject_key 等）原样透传为 4xx，不得 500 化。"""
    return error_response(error.code, error.message, error.status)


@registration_blueprint.errorhandler(UserServiceError)
def _user_service_error(error: UserServiceError):
    """非企业入口直接调用账号原语（register_self_service_user）——重复用户名/
    邮箱等账号语义错误原样透传为 4xx，不得 500 化。"""
    return error_response(error.code, error.message, error.status)


def _settings() -> Settings:
    settings = current_app.config.get("SETTINGS")
    assert isinstance(settings, Settings)
    return settings


def _json_payload() -> dict[str, Any]:
    payload = request.get_json(silent=True)
    return payload if isinstance(payload, dict) else {}


def _positive_int(value: str) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


@registration_blueprint.post("/register/<entry>")
def register_route(entry: str):
    """四入口统一注册（公开自助；部署闸内；响应 201）。

    响应携带 ``verification_email`` 状态（sent/failed 如实标注——发送失败不
    回滚注册，账号停在 pending_email 走重发路径）。
    """
    settings = _settings()
    _ensure_surface_open(settings)
    retry_after = _register_throttle(request.remote_addr)
    if retry_after is not None:
        return error_response(
            "registration_rate_limited",
            f"注册尝试过于频繁，请明日再试（每 IP 每日上限见部署配置）。",
            429,
        )
    payload = _json_payload()
    with db.session() as session, session.begin():
        data, raw_token = register_account(
            session,
            settings=settings,
            entry=entry,
            username=payload.get("username"),
            display_name=payload.get("display_name"),
            password=payload.get("password"),
            email=payload.get("email"),
            subject_key_raw=payload.get("subject_key"),
            problem_description=payload.get("problem_description"),
            intake=payload.get("intake"),
            request_id=payload.get("request_id"),
        )
    data["verification_email"] = dispatch_verification_email(
        settings, recipient=str(data["email"]), raw_token=raw_token
    )
    return jsonify({"data": data, "error": None}), 201


@registration_blueprint.post("/registrations/verify")
def verify_route():
    """邮箱验证（令牌一次性；公开；部署闸内）。"""
    payload = _json_payload()
    with db.session() as session, session.begin():
        data = verify_email(
            session, settings=_settings(), raw_token=payload.get("token")
        )
    return jsonify({"data": data, "error": None})


@registration_blueprint.post("/registrations/resend")
def resend_route():
    """重发验证邮件（**防枚举**：响应形状恒同 202 accepted；真实发送以事件留痕）。"""
    settings = _settings()
    _ensure_surface_open(settings)
    retry_after = _register_throttle(request.remote_addr)
    if retry_after is not None:
        return error_response(
            "registration_rate_limited",
            "注册面尝试过于频繁，请明日再试。",
            429,
        )
    payload = _json_payload()
    with db.session() as session, session.begin():
        raw_token, recipient = resend_verification(
            session, settings=settings, username=payload.get("username")
        )
    if raw_token is not None and recipient is not None:
        dispatch_verification_email(
            settings, recipient=recipient, raw_token=raw_token
        )
    return jsonify({"data": {"status": "accepted"}, "error": None}), 202


@registration_blueprint.get("/registrations/entries")
def entries_route():
    """四入口清单（公开；部署闸内；**区域服务商排最后**＝sec 评审「入口默认置后」）。"""
    settings = _settings()
    _ensure_surface_open(settings)
    review_set = review_entries(settings)
    items = [
        {"entry": entry, "review_required": entry in review_set}
        for entry in ENTRY_TYPES
    ]
    return jsonify({"data": {"entries": items}, "error": None})


@registration_blueprint.get("/registrations")
@require_role("admin")
def list_registrations_route():
    state = request.args.get("state")
    page = _positive_int(request.args.get("page", "1"))
    page_size = _positive_int(request.args.get("page_size", "20"))
    if page is None or page_size is None or page_size > 100:
        return error_response("invalid_request", "The request is invalid.", 400)
    with db.session() as session:
        items, total = list_registrations(
            session, state=state, page=page, page_size=page_size
        )
    return jsonify(
        {
            "data": {
                "items": items,
                "page": page,
                "page_size": page_size,
                "total": total,
            },
            "error": None,
        }
    )


@registration_blueprint.post("/registrations/<user_id>/review")
@require_role("admin")
def review_route(user_id: str):
    payload = _json_payload()
    with db.session() as session, session.begin():
        data = review_registration(
            session,
            actor=g.current_user,
            user_id=user_id,
            decision=payload.get("decision"),
            note=payload.get("note"),
        )
    return jsonify({"data": data, "error": None})


@registration_blueprint.post("/registrations/<user_id>/suspend")
@require_role("admin")
def suspend_route(user_id: str):
    with db.session() as session, session.begin():
        data = suspend_registration(session, actor=g.current_user, user_id=user_id)
    return jsonify({"data": data, "error": None})


@registration_blueprint.post("/registrations/<user_id>/reinstate")
@require_role("admin")
def reinstate_route(user_id: str):
    with db.session() as session, session.begin():
        data = reinstate_registration(
            session, actor=g.current_user, settings=_settings(), user_id=user_id
        )
    return jsonify({"data": data, "error": None})
