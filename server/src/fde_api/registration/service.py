"""多客户 M2：四入口统一注册服务层（任务书 §7-M2；ADR-M2 §2/ADR-M4）。

- **四入口**（``ENTRY_TYPES`` 闭集，区域服务商排最后＝sec 评审「入口默认置后」）：
  enterprise（企业客户）/ founder（创业者）/ deliverer（交付者）/ partner
  （区域服务商）。G6 企业自助注册路由自本轮起**委托本服务**（URL 与 K8 限流
  不变，盘点表第 10 行「收拢」处置兑现）——全仓企业自助注册单一语义。
- **部署闸 fail-closed**（OWNER 拍板 2026-11-11）：``surface_open`` = 部署开关
  AND SES 启用 AND 公网根地址——任一缺失一律 404（不确认面存在，诊断线同款）。
  **不允许「无邮箱验证的静默放行」**（ADR-M4 §2）。
- **状态机**（``users.registration_state``，ADR-M4 §1）：pending_email →
  pending_review（仅审核制入口）→ active / rejected；suspended 可恢复
  （admin 动作留痕）。审核制开关＝``FDE_REGISTRATION_REVIEW_ENTRIES``（缺省
  「deliverer,partner」＝任务书 §11-3 拍板值）。
- **初始角色矩阵**（ADR-M2 §2）：enterprise → project_lead（org 内）；
  founder/deliverer/partner → viewer（交付者的 fde_engineer 由供给池审核授予，
  本域零 dispatch 触碰；审核通过前不可接单＝viewer 结构性兜底）。
- **建号即建 org**（ADR-M2 §2）：enterprise 入口按 subject_key get-or-create
  ``orgs`` 行（org_type=enterprise；**同主体幂等**——第二经办人复用同一 org，
  绝不新建绝不重置）；其余入口 org_id=NULL（个人主体；区域机构主体＝机构字段
  存注册行，OWNER 拍板 2026-11-11 不扩 orgs 值域）。
- **邮箱验证**：一次性令牌（sha256 指纹入库、明文只出现在邮件里——诊断匿名
  令牌同形态）；重发即轮换（旧链接失效）；SES 发信（``mailing/`` 复用），
  发送在注册事务提交之后（失败不回滚注册，响应如实标注，走重发路径）。
- **留痕**：逐动作 ``operation_events``（复用既有事件体系，零第二套审计）；
  密码/令牌明文永不落事件（record_event 脱敏 + 本域从不传值）。

本包顶层导入单向：auth / orgs / commercial / mailing / projects(events) /
config——零环（test_architecture_purity 冻结闸不新增条目）。
"""
from __future__ import annotations

import hashlib
import re
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any
from unicodedata import normalize
from urllib.parse import quote

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from fde_api.auth.models import ROLE_PROJECT_LEAD, ROLE_VIEWER, User
from fde_api.commercial.enterprise_service import register_enterprise
from fde_api.commercial.quota_service import normalize_subject_key
from fde_api.config import Settings
from fde_api.mailing.service import MailingServiceError, send_email
from fde_api.orgs.models import ORG_TYPE_ENTERPRISE, Org
from fde_api.projects.events import record_event
from fde_api.registration.models import (
    ENTRY_DELIVERER,
    ENTRY_ENTERPRISE,
    ENTRY_FOUNDER,
    ENTRY_PARTNER,
    ENTRY_TYPES,
    REVIEW_DECISIONS,
    REVIEW_DECISION_APPROVE,
    REVIEW_DECISION_REJECT,
    UserRegistration,
)
from fde_api.users.service import register_self_service_user

# 初始角色矩阵（ADR-M2 §2 表；交付者 fde_engineer 由供给池审核授予，不在注册面）。
INITIAL_ROLES: dict[str, str] = {
    ENTRY_ENTERPRISE: ROLE_PROJECT_LEAD,
    ENTRY_FOUNDER: ROLE_VIEWER,
    ENTRY_DELIVERER: ROLE_VIEWER,
    ENTRY_PARTNER: ROLE_VIEWER,
}

REGISTRATION_STATES: frozenset[str] = frozenset(
    {"pending_email", "pending_review", "active", "suspended", "rejected"}
)

# 登录被注册状态拦截的（错误码 → 状态）映射：pending_review 可登录（viewer
# 最小面，业务能力由角色闸决定）；suspended/rejected/pending_email 拦截。
LOGIN_BLOCKED_STATES: dict[str, str] = {
    "pending_email": "email_not_verified",
    "suspended": "account_suspended",
    "rejected": "registration_rejected",
}

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_EMAIL_MAX_LENGTH = 255
_MATERIALS_MAX_ITEMS = 10
_MATERIAL_URI_MAX = 500
_REVIEW_NOTE_MAX = 500


class RegistrationError(Exception):
    def __init__(self, code: str, message: str, status: int):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


def _error(code: str, message: str, status: int = 400) -> RegistrationError:
    return RegistrationError(code, message, status)


# ---------------------------------------------------------------------------
# 部署闸与审核制开关
# ---------------------------------------------------------------------------


def surface_open(settings: Settings) -> bool:
    """注册面整体开关（ADR-M4 §2 fail-closed，OWNER 拍板过渡形态）。

    部署闸 AND SES 启用 AND 公网根地址——任一缺失 ⇒ 关闭（404，不确认面存在）。
    没有 SES 就没有邮箱验证；没有邮箱验证就不允许注册放行。
    """
    return (
        settings.registration_enabled
        and settings.ses_enabled
        and bool(settings.public_base_url.strip())
    )


def _ensure_surface_open(settings: Settings) -> None:
    if not surface_open(settings):
        raise _error("not_found", "资源不存在。", 404)


def review_entries(settings: Settings) -> frozenset[str]:
    """审核制开关（任务书 §11-3 拍板值的承载）：需人工审核的入口集。

    未知入口名 = 配置错误，**fail-closed 全部审核**（宁可多审不可漏审）并保留
    原文于异常信息（配置修正后恢复）。
    """
    raw = settings.registration_review_entries.strip()
    if not raw:
        return frozenset()
    parts = {p.strip() for p in raw.split(",") if p.strip()}
    unknown = parts - set(ENTRY_TYPES)
    if unknown:
        return frozenset(ENTRY_TYPES)
    return frozenset(parts)


# ---------------------------------------------------------------------------
# 输入校验
# ---------------------------------------------------------------------------


def _require_email(value: object) -> str:
    if not isinstance(value, str):
        raise _error("invalid_request", "email 必填且必须是字符串。")
    normalized = normalize("NFKC", value).strip().lower()
    if (
        not normalized
        or len(normalized) > _EMAIL_MAX_LENGTH
        or not _EMAIL_RE.match(normalized)
    ):
        raise _error("invalid_email", "email 格式不正确。")
    return normalized


def _require_sha256(value: object, field: str) -> str:
    if not isinstance(value, str):
        raise _error("invalid_request", f"{field} 必须是 64 位十六进制指纹。")
    digest = value.strip().lower()
    if len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest):
        raise _error("invalid_request", f"{field} 必须是 64 位十六进制指纹。")
    return digest


def _validate_intake(entry: str, value: object) -> dict[str, Any] | None:
    """入口申报材料（**只收指针 + sha256 指纹**——证据原件永不入库）。

    形状按入口闭集校验：deliverer → {"materials": [...]}（R 分层申请，GAP-01
    证据链口径）；partner → {"org_name", "region_name"}（机构字段，个人主体
    拍板）；enterprise/founder 不收材料（给了就 400——闭集拒绝多余面）。
    """
    if entry == ENTRY_DELIVERER:
        if value is None:
            return None
        if not isinstance(value, dict) or set(value) - {"materials"}:
            raise _error("invalid_request", "materials 形状不正确。")
        materials = value.get("materials")
        if not isinstance(materials, list) or len(materials) > _MATERIALS_MAX_ITEMS:
            raise _error(
                "invalid_request", f"materials 必须是列表且至多 {_MATERIALS_MAX_ITEMS} 项。"
            )
        cleaned: list[dict[str, str]] = []
        for item in materials:
            if not isinstance(item, dict) or set(item) - {"kind", "source_uri", "sha256"}:
                raise _error("invalid_request", "materials 项形状不正确。")
            uri = item.get("source_uri")
            if not isinstance(uri, str) or not uri.strip() or len(uri) > _MATERIAL_URI_MAX:
                raise _error("invalid_request", "source_uri 必填且 ≤500 字符。")
            record: dict[str, str] = {
                "source_uri": uri.strip(),
                "sha256": _require_sha256(item.get("sha256"), "sha256"),
            }
            kind = item.get("kind")
            if kind is not None:
                if not isinstance(kind, str) or not kind.strip() or len(kind) > 40:
                    raise _error("invalid_request", "kind 可选且 ≤40 字符。")
                record["kind"] = kind.strip()
            cleaned.append(record)
        return {"materials": cleaned}
    if entry == ENTRY_PARTNER:
        if not isinstance(value, dict) or set(value) - {"org_name", "region_name"}:
            raise _error("invalid_request", "区域服务商注册必须提供 org_name/region_name。")
        org_name = value.get("org_name")
        region_name = value.get("region_name")
        if not isinstance(org_name, str) or not org_name.strip() or len(org_name) > 160:
            raise _error("invalid_request", "org_name 必填且 ≤160 字符。")
        if (
            not isinstance(region_name, str)
            or not region_name.strip()
            or len(region_name) > 120
        ):
            raise _error("invalid_request", "region_name 必填且 ≤120 字符。")
        return {"org_name": org_name.strip(), "region_name": region_name.strip()}
    if value is not None:
        raise _error("invalid_request", "该注册入口不接受申报材料。")
    return None


# ---------------------------------------------------------------------------
# 注册（一个事务：账号 + org + 注册行 + 令牌 + 事件，要么全成要么全败）
# ---------------------------------------------------------------------------


def _get_or_create_enterprise_org(
    session: Session, subject_key: str, display_name: str
) -> Org:
    """按主体键 get-or-create 企业 org（同主体幂等：第二经办人复用同一 org）。

    ``orgs.subject_key`` 唯一（M1）在库层兜底并发；企业代号名冲突（不同主体
    撞同一代号）显式 409——代号化纪律由注册人遵守，撞名是真实信号不自动改名。
    """
    existing = session.scalar(select(Org).where(Org.subject_key == subject_key))
    if existing is not None:
        return existing
    org = Org(
        org_type=ORG_TYPE_ENTERPRISE,
        name=display_name.strip(),
        subject_key=subject_key,
    )
    session.add(org)
    try:
        session.flush()
    except IntegrityError as error:
        # 唯一约束兜底：企业代号撞名（uq_orgs_name）或主体键并发（uq_orgs_subject_key）
        # ——统一 409，代号化纪律由注册人遵守，撞名是真实信号不自动改名。
        raise _error(
            "org_name_conflict", "企业代号已被使用，请更换企业代号。", 409
        ) from error
    return org


def _new_token(settings: Settings) -> tuple[str, str, datetime]:
    """一次性验证令牌：明文只在邮件里，库中只有 sha256 指纹。"""
    raw = secrets.token_urlsafe(32)
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    expires = datetime.now(UTC) + timedelta(hours=settings.registration_token_hours)
    return raw, digest, expires


def register_account(
    session: Session,
    *,
    settings: Settings,
    entry: str,
    username: object,
    display_name: object,
    password: object,
    email: object,
    subject_key_raw: object = None,
    problem_description: object = None,
    intake: object = None,
    request_id: object = None,
) -> tuple[dict[str, Any], str]:
    """四入口统一注册（调用方持有事务；返回 (data, 明文令牌)——令牌只进邮件）。

    enterprise 走 ``register_enterprise``（G6 主体/额度/身份分层复用，角色矩阵
    project_lead）；其余入口直接建号（viewer）。注册行随行签发验证令牌；
    邮件发送在事务提交之后（``dispatch_verification_email``）。
    """
    _ensure_surface_open(settings)
    if entry not in ENTRY_TYPES:
        raise _error("invalid_entry", "未知的注册入口。")
    normalized_email = _require_email(email)
    materials = _validate_intake(entry, intake)
    if not isinstance(username, str) or not isinstance(display_name, str) or not isinstance(password, str):
        raise _error("invalid_request", "username/display_name/password 必须是字符串。")

    subject_key: str | None = None
    org_id: str | None = None
    if entry == ENTRY_ENTERPRISE:
        if not isinstance(subject_key_raw, str) or not subject_key_raw.strip():
            raise _error("invalid_request", "subject_key 必填。")
        subject_key = normalize_subject_key(subject_key_raw)
        org = _get_or_create_enterprise_org(session, subject_key, display_name)
        org_id = org.id
        result = register_enterprise(
            session,
            username=username,
            display_name=display_name,
            password=password,
            email=normalized_email,
            subject_key_raw=subject_key,
            problem_description=problem_description,
            org_id=org_id,
            request_id=request_id,
        )
        user = session.get(User, result["user_id"])
        assert user is not None  # 同事务刚建
        data: dict[str, Any] = dict(result)
        data["registration_state"] = user.registration_state
    else:
        user = register_self_service_user(
            session,
            username=username,
            display_name=display_name,
            password=password,
            role=INITIAL_ROLES[entry],
            email=normalized_email,
            org_id=None,
            registration_state="pending_email",
        )
        data = {
            "user_id": user.id,
            "username": user.username,
            "email": normalized_email,
            "org_id": None,
        }

    raw_token, digest, expires = _new_token(settings)
    registration = UserRegistration(
        user_id=user.id,
        entry=entry,
        materials_json=materials,
        token_sha256=digest,
        token_expires_at=expires,
        token_requested_at=datetime.now(UTC),
    )
    session.add(registration)
    record_event(
        session,
        user,
        "registration_submitted",
        user,
        {
            "entry": entry,
            "request_id": request_id if isinstance(request_id, str) else None,
        },
    )
    data["entry"] = entry
    data["email"] = normalized_email
    data["registration_state"] = user.registration_state
    return data, raw_token


def dispatch_verification_email(
    settings: Settings, *, recipient: str, raw_token: str
) -> dict[str, Any]:
    """注册事务提交后发送验证邮件（独立会话——``send_email`` 自管事务提交）。

    发送失败**不回滚注册**：账号已建（pending_email）、令牌已入库，重发路径
    兜底；响应如实标注 failed（不谎报 sent）。
    """
    from fde_api.extensions import db

    session = db.session()
    try:
        return send_verification_email(
            session, settings=settings, recipient=recipient, raw_token=raw_token
        )
    finally:
        session.close()


def send_verification_email(
    session: Session, *, settings: Settings, recipient: str, raw_token: str
) -> dict[str, Any]:
    digest_prefix = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()[:16]
    base = settings.public_base_url.strip().rstrip("/")
    link = f"{base}/verify-email?token={quote(raw_token, safe='')}"
    body = (
        f"欢迎注册{settings.fde_product_name}。\n\n"
        f"邮箱验证令牌（一次性，{settings.registration_token_hours} 小时内有效）：\n"
        f"{raw_token}\n\n"
        f"验证链接：{link}\n\n"
        "如非本人操作，请忽略本邮件。"
    )
    try:
        result = send_email(
            settings=settings,
            session=session,
            recipient=recipient,
            subject=f"邮箱验证——{settings.fde_product_name}",
            body=body,
            idempotency_key=f"registration-verify:{digest_prefix}",
        )
    except MailingServiceError as error:
        return {"status": "failed", "code": error.code}
    return {"status": "sent", "message_id": result.get("message_id")}


# ---------------------------------------------------------------------------
# 邮箱验证与重发
# ---------------------------------------------------------------------------


def verify_email(session: Session, *, settings: Settings, raw_token: object) -> dict[str, Any]:
    """一次性令牌消费：验证邮箱 → 推进状态机（自助入口→active；审核入口→pending_review）。

    令牌错误/过期/已用/状态不符全部 4xx；消费动作落事件。pending_review 的
    后续推进只能由 admin review 动作完成（审核制开关拍板语义）。
    """
    _ensure_surface_open(settings)
    if not isinstance(raw_token, str) or not raw_token.strip():
        raise _error("invalid_request", "token 必填。")
    digest = hashlib.sha256(raw_token.strip().encode("utf-8")).hexdigest()
    registration = session.scalar(
        select(UserRegistration).where(UserRegistration.token_sha256 == digest)
    )
    if registration is None:
        raise _error("invalid_token", "验证令牌无效。", 400)
    now = datetime.now(UTC)
    if registration.token_consumed_at is not None:
        raise _error("token_already_used", "验证令牌已被使用。", 409)
    if registration.token_expires_at is None or registration.token_expires_at <= now:
        raise _error("token_expired", "验证令牌已过期，请重发验证邮件。", 400)
    user = session.get(User, registration.user_id)
    if user is None:
        raise _error("registration_not_found", "注册不存在。", 404)
    if user.registration_state != "pending_email":
        raise _error("invalid_registration_state", "当前注册状态不允许邮箱验证。", 409)
    registration.token_consumed_at = now
    user.email_verified_at = now
    needs_review = registration.entry in review_entries(settings)
    user.registration_state = "pending_review" if needs_review else "active"
    record_event(
        session,
        user,
        "registration_email_verified",
        user,
        {"entry": registration.entry},
    )
    return {
        "user_id": user.id,
        "entry": registration.entry,
        "registration_state": user.registration_state,
    }


def resend_verification(
    session: Session, *, settings: Settings, username: object
) -> tuple[str | None, str | None]:
    """轮换并重发验证令牌。返回 (新明文令牌, 收件人)——两者任一为 None＝无操作。

    **防枚举**：用户名不存在 / 已验证 / 无注册行的请求与真实重发返回同一响应
    形状（路由层统一 202 accepted）；真实发送以事件留痕为准。同账号最小重发
    间隔＋同 IP 每日上限（路由层）构成重发双闸。
    """
    _ensure_surface_open(settings)
    if not isinstance(username, str) or not username.strip():
        raise _error("invalid_request", "username 必填。")
    normalized = normalize("NFKC", username).strip().lower()
    user = session.scalar(select(User).where(User.username == normalized))
    if user is None or user.registration_state != "pending_email":
        return None, None
    registration = session.scalar(
        select(UserRegistration).where(UserRegistration.user_id == user.id)
    )
    if registration is None:
        return None, None
    now = datetime.now(UTC)
    min_interval = timedelta(seconds=settings.registration_resend_min_seconds)
    if registration.token_requested_at is not None:
        elapsed = now - registration.token_requested_at
        if elapsed < min_interval:
            retry_after = max(int((min_interval - elapsed).total_seconds()), 1)
            raise _error(
                "resend_throttled", f"验证邮件重发过于频繁，请约 {retry_after} 秒后再试。", 429
            )
    raw_token, digest, expires = _new_token(settings)
    registration.token_sha256 = digest
    registration.token_expires_at = expires
    registration.token_requested_at = now
    registration.token_consumed_at = None
    record_event(
        session,
        user,
        "registration_verification_resent",
        user,
        {"entry": registration.entry},
    )
    recipient = user.email
    if recipient is None:
        # 待验证账号必有邮箱（注册必填）；无邮箱的 pending_email 行属异常态，
        # 诚实不发送（令牌已轮换——旧链接失效，可由 admin 排查）。
        return None, None
    return raw_token, recipient


# ---------------------------------------------------------------------------
# admin 审核簿记
# ---------------------------------------------------------------------------


def list_registrations(
    session: Session,
    *,
    state: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[dict[str, Any]], int]:
    """admin 注册清单（状态过滤 + 分页；join users 取账号口径）。"""
    if state is not None and state not in REGISTRATION_STATES:
        raise _error("invalid_request", "未知的注册状态。")
    conditions = []
    if state is not None:
        conditions.append(User.registration_state == state)
    total = session.scalar(
        select(func.count())
        .select_from(UserRegistration)
        .join(User, User.id == UserRegistration.user_id)
        .where(*conditions)
    )
    rows = session.execute(
        select(UserRegistration, User)
        .join(User, User.id == UserRegistration.user_id)
        .where(*conditions)
        .order_by(UserRegistration.created_at.desc())
        .limit(page_size)
        .offset((page - 1) * page_size)
    ).all()
    items: list[dict[str, Any]] = []
    for registration, user in rows:
        items.append(
            {
                "user_id": user.id,
                "username": user.username,
                "display_name": user.display_name,
                "email": user.email,
                "entry": registration.entry,
                "registration_state": user.registration_state,
                "email_verified_at": (
                    user.email_verified_at.isoformat()
                    if user.email_verified_at is not None
                    else None
                ),
                "reviewed_at": (
                    registration.reviewed_at.isoformat()
                    if registration.reviewed_at is not None
                    else None
                ),
                "review_note": registration.review_note,
                "created_at": registration.created_at.isoformat(),
            }
        )
    return items, int(total or 0)


def review_registration(
    session: Session,
    *,
    actor: User,
    user_id: str,
    decision: object,
    note: object,
) -> dict[str, Any]:
    """admin 审核（pending_review → active/rejected；rejected 终态不复活）。"""
    registration = session.scalar(
        select(UserRegistration).where(UserRegistration.user_id == user_id)
    )
    user = session.get(User, user_id)
    if registration is None or user is None:
        raise _error("registration_not_found", "注册不存在。", 404)
    if user.registration_state != "pending_review":
        raise _error("invalid_registration_state", "当前注册状态不允许审核。", 409)
    if decision not in REVIEW_DECISIONS:
        raise _error("invalid_decision", "decision 必须是 approve 或 reject。")
    cleaned_note: str | None = None
    if note is not None:
        if not isinstance(note, str) or len(note.strip()) > _REVIEW_NOTE_MAX:
            raise _error("invalid_request", f"note ≤{_REVIEW_NOTE_MAX} 字符。")
        cleaned_note = note.strip() or None
    if decision == REVIEW_DECISION_REJECT and not cleaned_note:
        raise _error("review_note_required", "拒绝必须附定性理由。")
    now = datetime.now(UTC)
    registration.reviewed_by_user_id = actor.id
    registration.reviewed_at = now
    registration.review_note = cleaned_note
    approved = decision == REVIEW_DECISION_APPROVE
    user.registration_state = "active" if approved else "rejected"
    if not approved:
        user.auth_version += 1
    record_event(
        session,
        actor,
        "registration_review_approved" if approved else "registration_review_rejected",
        user,
        {"entry": registration.entry, "decision": decision},
    )
    return {
        "user_id": user.id,
        "entry": registration.entry,
        "registration_state": user.registration_state,
    }


def suspend_registration(session: Session, *, actor: User, user_id: str) -> dict[str, Any]:
    """admin 停用（active/pending_review → suspended；可恢复）。"""
    registration = session.scalar(
        select(UserRegistration).where(UserRegistration.user_id == user_id)
    )
    user = session.get(User, user_id)
    if registration is None or user is None:
        raise _error("registration_not_found", "注册不存在。", 404)
    if user.registration_state not in ("active", "pending_review"):
        raise _error("invalid_registration_state", "当前注册状态不允许停用。", 409)
    user.registration_state = "suspended"
    user.auth_version += 1
    record_event(
        session,
        actor,
        "registration_suspended",
        user,
        {"entry": registration.entry},
    )
    return {
        "user_id": user.id,
        "entry": registration.entry,
        "registration_state": user.registration_state,
    }


def reinstate_registration(
    session: Session, *, actor: User, settings: Settings, user_id: str
) -> dict[str, Any]:
    """admin 恢复（suspended → 按事实推导：未验证→pending_email；审核入口未
    审核→pending_review；否则 active）。推导自既有列，不保存「停用前状态」。"""
    registration = session.scalar(
        select(UserRegistration).where(UserRegistration.user_id == user_id)
    )
    user = session.get(User, user_id)
    if registration is None or user is None:
        raise _error("registration_not_found", "注册不存在。", 404)
    if user.registration_state != "suspended":
        raise _error("invalid_registration_state", "仅 suspended 状态可恢复。", 409)
    if user.email_verified_at is None:
        target = "pending_email"
    elif registration.entry in review_entries(settings) and registration.reviewed_at is None:
        target = "pending_review"
    else:
        target = "active"
    user.registration_state = target
    record_event(
        session,
        actor,
        "registration_reinstated",
        user,
        {"entry": registration.entry, "to": target},
    )
    return {
        "user_id": user.id,
        "entry": registration.entry,
        "registration_state": user.registration_state,
    }
