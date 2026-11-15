"""诊断域服务层：匿名会话生命周期 + 配额闸 + 测算卡落库。

**匿名面纪律**（本域是本仓第一个公网免注册写面）：

1. **部署闸默认关闭**：``FDE_DIAGNOSTICS_ENABLED`` 默认 False——主部署不暴露
   匿名写面（D-3 独立轻部署：诊断面单独 compose / 单独库 / 单独域名）。关闭时
   路由返回 **404**（不是 403——不确认面存在）。
2. **令牌只存指纹**：客户端持明文，库里只有 sha256；库泄漏 ≠ 会话被接管。
3. **IP 只存假名**：sha256(ip + 密钥，域分隔)，不是明文 IP。
4. **配额双闸**：每 IP 每日上限 + 每匿名令牌配额。Redis 不可用时的策略由
   ``FDE_DIAGNOSTICS_RATE_FAIL_CLOSED`` 决定——**公开写面默认 fail-closed**
   （与登录面默认 fail-open 相反：公开面被刷的代价高得多）。
5. **答案过脱敏管线**：企业自填文本落库前先过 T-A2（企业名 → 代号）；词典
   机制性异常 fail-closed（同码）。
"""
from __future__ import annotations

import hashlib
import re
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any

from flask import current_app
from redis.exceptions import RedisError
from sqlalchemy import select

from fde_api.diagnostics.assessment import compute_assessment
from fde_api.diagnostics.models import (
    CLAIM_WINDOW_DAYS,
    SESSION_RETENTION_DAYS,
    SOURCE_TYPES,
    LeadDiagnosticSession,
)
from fde_api.diagnostics.questionnaire import (
    DIAGNOSTIC_SLOTS,
    FIRST_SCREEN_SLOTS,
    MAX_ANSWER_CHARS,
    MAX_CONTACT_CHARS,
    SLOT_BY_KEY,
)
from fde_api.extensions import db
from fde_api.guidance.enterprise_dict import RedactionConfigError
from fde_api.guidance.redaction import (
    SensitiveCredentialDetected,
    redact_text_detailed,
)

_RATE_WINDOW_SECONDS = 24 * 3600

# 留资「区域」字段长度上限（T-11：R4 本区域认领的判定基准）
MAX_REGION_CHARS = 120


class DiagnosticsServiceError(Exception):
    """诊断域业务错误（code + 面向访客的文案 + HTTP 状态）。"""

    def __init__(
        self,
        code: str,
        message: str,
        status: int = 400,
        detail: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status
        self.detail = detail or {}


def _error(code: str, message: str, status: int = 400, **detail: Any) -> DiagnosticsServiceError:
    return DiagnosticsServiceError(code, message, status, detail or None)


# ── 部署闸 ───────────────────────────────────────────────────────────


def ensure_enabled() -> None:
    """诊断面未启用 ⇒ 404（不确认面存在）。"""
    settings = current_app.config["SETTINGS"]
    if not getattr(settings, "diagnostics_enabled", False):
        raise _error("not_found", "资源不存在。", 404)


# ── 指纹 ─────────────────────────────────────────────────────────────


def hash_ip(ip_address: str | None) -> str:
    """来源 IP 的稳定假名（域分隔 sha256；不是明文 IP）。"""
    settings = current_app.config["SETTINGS"]
    secret = str(settings.jwt_secret)
    raw = f"fde-diagnostics-ip-v1:{secret}:{ip_address or 'unknown'}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def hash_token(token: str) -> str:
    """匿名令牌指纹（域分隔 sha256）。"""
    return hashlib.sha256(f"fde-diagnostics-token-v1:{token}".encode("utf-8")).hexdigest()


def hash_share_token(token: str) -> str:
    """分享令牌指纹（**独立域分隔**）。

    分享令牌与匿名会话令牌**权限域不同**：会话令牌是写权限凭证（只走请求头，
    URL 会进访问日志）；分享令牌是**只读**凭证（可入 URL，因为它就是要被分享
    的链接）。两者指纹域也分开——任一泄漏都不越界。
    """
    return hashlib.sha256(f"fde-diagnostics-share-v1:{token}".encode("utf-8")).hexdigest()


def subject_fingerprint(contact: str) -> str:
    """主体指纹（T-11 自认领判定用）：sha256(域分隔 ＋ 规范化联系方式)。

    **明文不入库**——库里只有指纹（与匿名令牌/IP 假名同款手法）。规范化口径
    ＝去空白 ＋ 小写（比对口径，不改写留资行里的原文）。
    """
    normalized = re.sub(r"\s+", "", (contact or "").strip().lower())
    return hashlib.sha256(f"fde-diagnostics-subject-v1:{normalized}".encode("utf-8")).hexdigest()


def resolve_ai_actor(session: Any) -> Any:
    """解析 AI 调用主体（平台服务账号）。

    ``execute_ai_prompt`` 要求真实 ``users`` 行（active + AI 权限）——预算闸与
    归因台账都要有主体。匿名访客没有账号，故用**服务账号**：配置项指向一个
    既有用户名，AI 用量与审计**如实记在它头上**（不伪造匿名用户，也不让预算
    无主地飘）。未配置 / 账号不存在 / 已停用 ⇒ **fail-closed**（503），不静默
    降级成「没有报告」。
    """
    from unicodedata import normalize

    from fde_api.auth.models import User

    settings = current_app.config["SETTINGS"]
    raw = str(getattr(settings, "diagnostics_ai_actor_username", "") or "").strip()
    if not raw:
        raise _error(
            "diagnostic_ai_unavailable",
            "报告生成服务暂不可用，请稍后再试。",
            503,
        )
    username = normalize("NFKC", raw).strip().lower()
    user = session.scalar(select(User).where(User.username == username))
    if user is None or not user.is_active:
        raise _error(
            "diagnostic_ai_unavailable",
            "报告生成服务暂不可用，请稍后再试。",
            503,
        )
    return user


# ── 配额闸 ───────────────────────────────────────────────────────────


def _redis_client() -> Any | None:
    try:
        return current_app.extensions["fde_api_redis"]
    except KeyError:
        return None


def _bump(key: str, limit: int) -> int:
    """Redis 计数 +1 并返回当前值；超限抛 429。Redis 故障按 fail-closed 决定。"""
    settings = current_app.config["SETTINGS"]
    fail_closed = bool(getattr(settings, "diagnostics_rate_fail_closed", True))
    redis = _redis_client()
    if redis is None:
        if fail_closed:
            raise _error(
                "diagnostics_rate_limited",
                "限流服务暂不可用，请稍后再试。",
                429,
            )
        return 0
    try:
        count = int(redis.incr(key))
        if count == 1:
            redis.expire(key, _RATE_WINDOW_SECONDS)
    except RedisError:
        current_app.logger.warning("diagnostics rate limiter unavailable key=%s", key, exc_info=True)
        if fail_closed:
            raise _error(
                "diagnostics_rate_limited",
                "限流服务暂不可用，请稍后再试。",
                429,
            ) from None
        return 0
    if count > limit:
        raise _error(
            "diagnostics_rate_limited",
            "今天的使用次数已达上限，请明天再试。",
            429,
            limit=limit,
        )
    return count


def enforce_ip_daily_limit(ip_hash: str) -> None:
    """每 IP 每日动作上限（创建会话 / 测算 / 答题 / 留资 共用一个计数）。"""
    settings = current_app.config["SETTINGS"]
    limit = int(getattr(settings, "diagnostics_daily_ip_limit", 20))
    day = datetime.now(UTC).date().isoformat()
    _bump(f"fde:diagnostics:ip:{ip_hash}:{day}", limit)


def enforce_session_quota(token_sha256: str) -> None:
    """每匿名令牌的动作配额。"""
    settings = current_app.config["SETTINGS"]
    limit = int(getattr(settings, "diagnostics_session_quota", 3))
    day = datetime.now(UTC).date().isoformat()
    _bump(f"fde:diagnostics:token:{token_sha256}:{day}", limit)


# ── 答案校验 ─────────────────────────────────────────────────────────


def _validate_slot(slot_key: str, value: Any) -> Any:
    """按槽位定义校验单个值；空串视为未答（返回 None）。"""
    slot = SLOT_BY_KEY[slot_key]
    if slot.kind == "multi":
        if not isinstance(value, list):
            raise _error("invalid_answers", f"{slot_key} 必须是数组。", 400)
        cleaned: list[str] = []
        for item in value:
            if not isinstance(item, str):
                raise _error("invalid_answers", f"{slot_key} 的选项必须为字符串。", 400)
            text = item.strip()
            if not text:
                continue
            if slot.options and text not in slot.options:
                raise _error("invalid_answers", f"{slot_key} 含未定义选项。", 400)
            if text not in cleaned:
                cleaned.append(text)
        return cleaned
    if slot.kind == "single":
        if not isinstance(value, str):
            raise _error("invalid_answers", f"{slot_key} 必须是字符串。", 400)
        text = value.strip()
        if not text:
            return None
        if slot.options and text not in slot.options:
            raise _error("invalid_answers", f"{slot_key} 含未定义选项。", 400)
        return text
    if not isinstance(value, str):
        raise _error("invalid_answers", f"{slot_key} 必须是字符串。", 400)
    text = value.strip()
    if not text:
        return None
    limit = min(slot.max_chars or MAX_ANSWER_CHARS, MAX_ANSWER_CHARS)
    if len(text) > limit:
        raise _error("invalid_answers", f"{slot_key} 超长（上限 {limit} 字符）。", 400)
    return text


def validate_answers(payload: dict[str, Any], *, scope: str) -> dict[str, Any]:
    """校验一组答案。

    ``scope`` 为 ``first_screen`` 或 ``diagnostic``——**未知槽位键一律拒绝**
    （防脏数据与越权写入）；空串按未答处理。
    """
    if scope == "first_screen":
        allowed = {slot.key for slot in FIRST_SCREEN_SLOTS}
    elif scope == "diagnostic":
        allowed = {slot.key for slot in DIAGNOSTIC_SLOTS}
    else:  # pragma: no cover - 调用方内部值
        raise _error("invalid_answers", "scope 非法。", 400)

    unknown = sorted(set(payload) - allowed)
    if unknown:
        raise _error("invalid_answers", "含未定义槽位。", 400, unknown=unknown)

    cleaned: dict[str, Any] = {}
    for key, value in payload.items():
        checked = _validate_slot(key, value)
        if checked is None or (isinstance(checked, list) and not checked):
            continue
        cleaned[key] = checked
    return cleaned


def _redact_text(value: str, *, mask_pii: bool = True) -> str:
    """单段文本过脱敏管线（T-A2）：企业名 → 代号；词典异常 fail-closed。"""
    try:
        result = redact_text_detailed(value, mask_pii=mask_pii)
    except RedactionConfigError:
        raise _error(
            "pseudonym_dict_unavailable",
            "暂时无法处理这份内容，请稍后再试。",
            503,
        ) from None
    except SensitiveCredentialDetected:
        raise _error(
            "sensitive_credential_detected",
            "内容中疑似包含密码、密钥或令牌，请移除后重试。",
            422,
        ) from None
    return result.text


def _redact_answers(answers: dict[str, Any]) -> dict[str, Any]:
    """文本答案过脱敏管线（T-A2）：企业名 → 代号；词典异常 fail-closed。"""
    redacted: dict[str, Any] = {}
    for key, value in answers.items():
        slot = SLOT_BY_KEY[key]
        if slot.kind in {"single", "multi"}:
            redacted[key] = value
            continue
        redacted[key] = _redact_text(str(value))
    return redacted


# ── 会话生命周期 ─────────────────────────────────────────────────────


def _enforce_retention(
    session: Any,
    row: LeadDiagnosticSession,
    *,
    now: datetime | None = None,
    commit: bool = True,
) -> bool:
    """30 天留存期懒检查（QR-042，个保法留存期兑现）：

    未认领（``status != 'claimed'``）且 ``expires_at <= now`` 的匿名会话在读写边界
    立即转为 ``expired`` 并匿名化清空内容字段（答案、测算卡、报告、留资、主体指纹、
    区域与分享令牌指纹），不要求新增后台定时清扫器。已认领线索受业务台账保护不在此处置。
    """
    if row.status == "claimed":
        return False
    ref_now = now or datetime.now(UTC)
    if row.expires_at is None or ref_now < row.expires_at:
        return row.status == "expired"
    mutated = (
        row.status != "expired"
        or bool(row.answers)
        or row.assessment is not None
        or row.report is not None
        or row.lead_contact is not None
        or row.subject_fingerprint is not None
        or row.region_name is not None
        or row.share_token_sha256 is not None
    )
    if mutated:
        row.status = "expired"
        row.answers = {}
        row.assessment = None
        row.report = None
        row.lead_contact = None
        row.subject_fingerprint = None
        row.region_name = None
        row.share_token_sha256 = None
        row.failure_code = None
        row.failure_message = None
        if commit:
            session.commit()
    return True


def _load_by_token(session: Any, token: str) -> LeadDiagnosticSession:
    row = session.scalars(
        select(LeadDiagnosticSession).where(
            LeadDiagnosticSession.token_sha256 == hash_token(token)
        )
    ).first()
    if row is None:
        raise _error("session_not_found", "会话不存在或已失效。", 404)
    _enforce_retention(session, row)
    return row


def create_session(
    *,
    ip_address: str | None,
    source_type: str = "direct",
    channel_ref: str | None = None,
) -> tuple[LeadDiagnosticSession, str]:
    """新建匿名会话；返回（行, 明文令牌）——**明文只此一次**。

    **归因接线（T-15 机械归因）**：

    - ``source_type='partner'`` **不接受客户端声明**——渠道报备归因只能由
      有效渠道链接服务端推导（否则 A 档〔收费档〕可被任意伪造）；
    - ``channel_ref`` 在场时按**渠道链接 token** 解析：命中在用链接 ⇒
      ``source_type='partner'``＋``channel_ref=链接行 UUID``；未命中
      （过期/停用/伪造）⇒ **fail-closed 降档**——会话照常建（stale 链接不拦
      真实线索）但落 ``direct``，``channel_ref`` 原样留存（诚实审计线索）；
    - ``source_type='channel'``（协会活动等免费名目）保持客户端声明 ＋
      自由文本 ``channel_ref``——不涉收费档，无伪造收益。

    停用链接的历史归因**不改写**：A 档在会话创建时刻定格。
    """
    if source_type not in SOURCE_TYPES:
        raise _error("invalid_source_type", "来源类型非法。", 400)
    if source_type == "partner":
        raise _error(
            "partner_source_forbidden",
            "渠道报备归因由平台渠道链接自动落，不接受直接声明。",
            400,
        )
    if source_type != "direct" and not (channel_ref or "").strip():
        raise _error(
            "channel_ref_required",
            "渠道来源必须带渠道链接标识（归因自动落，不手工记账）。",
            400,
        )
    ip_hash = hash_ip(ip_address)
    enforce_ip_daily_limit(ip_hash)

    # 渠道链接解析（T-15）：channel_ref 视作链接 token 尝试归一；
    # 命中即机械落 partner；未命中降 direct（channel_ref 留痕不改写）。
    # 函数内懒导入（热点行数预算 + 与 claim_service 同款域内引用习惯）。
    from fde_api.diagnostics.channel_links import resolve_link

    resolved = source_type
    resolved_ref = (channel_ref or "").strip() or None
    if resolved_ref:
        link = resolve_link(resolved_ref)
        if link is not None:
            resolved = "partner"
            resolved_ref = link.id

    token = secrets.token_urlsafe(32)
    now = datetime.now(UTC)
    with db.session() as session:
        row = LeadDiagnosticSession(
            token_sha256=hash_token(token),
            status="draft",
            answers={},
            assessment=None,
            source_type=resolved,
            channel_ref=resolved_ref,
            created_ip_hash=ip_hash,
            claim_window_expires_at=now + timedelta(days=CLAIM_WINDOW_DAYS),
            expires_at=now + timedelta(days=SESSION_RETENTION_DAYS),
        )
        session.add(row)
        session.commit()
        return row, token


def submit_first_screen(token: str, answers: dict[str, Any]) -> LeadDiagnosticSession:
    """提交首屏答案 → 纯规则算出政策补贴测算卡（零 AI）。"""
    cleaned = validate_answers(answers, scope="first_screen")
    missing = [
        slot.key
        for slot in FIRST_SCREEN_SLOTS
        if slot.required and not cleaned.get(slot.key)
    ]
    if missing:
        raise _error("incomplete_answers", "必答题未作答。", 400, missing=missing)

    token_sha = hash_token(token)
    enforce_session_quota(token_sha)
    safe = _redact_answers(cleaned)
    assessment = compute_assessment(safe)

    with db.session() as session:
        row = _load_by_token(session, token)
        if row.status in {"claimed", "expired"}:
            raise _error("session_closed", "该会话已结束。", 409)
        enforce_ip_daily_limit(row.created_ip_hash)
        merged = dict(row.answers or {})
        merged.update(safe)
        row.answers = merged
        row.assessment = assessment
        row.status = "submitted"
        row.submitted_at = row.submitted_at or datetime.now(UTC)
        session.commit()
        return row


def submit_answers(token: str, answers: dict[str, Any]) -> LeadDiagnosticSession:
    """提交诊断问卷答案（续填）。"""
    cleaned = validate_answers(answers, scope="diagnostic")
    if not cleaned:
        raise _error("incomplete_answers", "没有可保存的答案。", 400)
    token_sha = hash_token(token)
    enforce_session_quota(token_sha)
    safe = _redact_answers(cleaned)

    with db.session() as session:
        row = _load_by_token(session, token)
        if row.status in {"claimed", "expired"}:
            raise _error("session_closed", "该会话已结束。", 409)
        if not row.assessment:
            raise _error(
                "first_screen_required",
                "请先完成首屏测算，再继续填写诊断问卷。",
                409,
            )
        enforce_ip_daily_limit(row.created_ip_hash)
        merged = dict(row.answers or {})
        merged.update(safe)
        row.answers = merged
        session.commit()
        return row


def capture_lead(token: str, contact: dict[str, Any]) -> LeadDiagnosticSession:
    """留资：提交联系方式 + 隐私政策同意（留资闸）。"""
    if contact.get("consent") is not True:
        raise _error(
            "consent_required",
            "需同意隐私政策与用途说明后才能获取完整报告。",
            400,
        )
    reach = contact.get("contact")
    if not isinstance(reach, str) or not reach.strip():
        raise _error("contact_required", "请填写联系方式。", 400)
    reach = reach.strip()
    if len(reach) > MAX_CONTACT_CHARS:
        raise _error("contact_too_long", "联系方式过长。", 400)
    name = contact.get("name")
    if name is not None and not isinstance(name, str):
        raise _error("invalid_contact", "联系人必须是字符串。", 400)
    name = (name or "").strip()
    if len(name) > 80:
        raise _error("invalid_contact", "联系人过长。", 400)
    # 区域（T-11）：R4 区域合作商**仅可认领本区域线索**——判定基准必须是
    # 线索自己的区域。**可空**＝线索未登记区域 ⇒ R4 认领 fail-closed 拒
    # （无法判定本区域即不许认领）；R2 创业者不按区域分，不受影响。
    region = contact.get("region")
    if region is not None and not isinstance(region, str):
        raise _error("invalid_region", "区域必须是字符串。", 400)
    region = (region or "").strip()
    if len(region) > MAX_REGION_CHARS:
        raise _error("invalid_region", "区域名称过长。", 400)
    region = region or None

    token_sha = hash_token(token)
    enforce_session_quota(token_sha)
    safe_name = _redact_text(name) if name else None
    safe_region = _redact_text(region) if region else None
    payload = {
        "contact": _redact_text(reach, mask_pii=False),
        "name": safe_name,
        "consent": True,
        "captured_at": datetime.now(UTC).isoformat(),
    }

    with db.session() as session:
        row = _load_by_token(session, token)
        if row.status in {"claimed", "expired"}:
            raise _error("session_closed", "该会话已结束。", 409)
        if not row.assessment:
            raise _error("first_screen_required", "请先完成首屏测算。", 409)
        enforce_ip_daily_limit(row.created_ip_hash)
        row.lead_contact = payload
        # 主体指纹（T-11 自认领判定）：**只存指纹**，明文仍在留资行里
        row.subject_fingerprint = subject_fingerprint(reach)
        row.region_name = safe_region
        session.commit()
        return row


def get_session(token: str) -> LeadDiagnosticSession:
    with db.session() as session:
        return _load_by_token(session, token)


# ── 报告受理（异步，T-10b） ───────────────────────────────────────────


def request_report(token: str) -> LeadDiagnosticSession:
    """受理报告生成请求（**异步**）：只入队，不同步调 AI。

    **留资闸**：完整报告要联系方式 + 隐私政策同意 + 用途明示（D-2）——既是商业
    闸也是**成本闸**（免注册白烧 AI token 的代价远高于留资转化）。
    """
    from fde_api.diagnostics.jobs import DIAGNOSTIC_REPORT_JOB_TYPE
    from fde_api.jobs.outbox import enqueue_outbox  # noqa: PLC0415

    token_sha = hash_token(token)
    enforce_session_quota(token_sha)
    with db.session() as session:
        row = _load_by_token(session, token)
        if row.status in {"claimed", "expired"}:
            raise _error("session_closed", "该会话已结束。", 409)
        if not row.assessment:
            raise _error("first_screen_required", "请先完成首屏测算。", 409)
        if not row.lead_contact:
            raise _error(
                "lead_required",
                "请先留下联系方式并同意隐私政策，再获取完整报告。",
                409,
            )
        if row.report:
            raise _error("report_already_ready", "报告已生成。", 409)
        if row.report_requested_at is not None and not row.failure_code:
            # 已在生成中 ⇒ 幂等返回（不重复入队，不重复计费）
            return row
        enforce_ip_daily_limit(row.created_ip_hash)
        row.report_requested_at = datetime.now(UTC)
        row.failure_code = None
        row.failure_message = None
        # 入队与业务写**同事务**（outbox 纪律）：业务回滚则不入队。
        enqueue_outbox(
            session,
            topic=DIAGNOSTIC_REPORT_JOB_TYPE,
            aggregate_id=row.id,
            payload={},
            subject_org=None,  # 公网匿名面：无 org 归属（平台级）
        )
        session.commit()
        return row


def report_state(row: LeadDiagnosticSession) -> str:
    """报告状态（对外）：none / requested / ready / failed。"""
    if row.report:
        return "ready"
    if row.failure_code:
        return "failed"
    if row.report_requested_at is not None:
        return "requested"
    return "none"


# ── 分享链接（只读，T-10b） ───────────────────────────────────────────


def create_share_link(token: str) -> tuple[LeadDiagnosticSession, str]:
    """生成分享链接（**只读**凭证，明文只此一次）。

    每次调用**轮换**分享令牌（旧链接立即失效）——明文只在库里存指纹，返回一次
    就再也拿不回来；不轮换就没法重发链接。
    """
    token_sha = hash_token(token)
    enforce_session_quota(token_sha)
    with db.session() as session:
        row = _load_by_token(session, token)
        if row.status in {"claimed", "expired"}:
            raise _error("session_closed", "该会话已结束。", 409)
        if not row.lead_contact:
            raise _error(
                "lead_required",
                "请先留下联系方式并同意隐私政策，再获取报告。",
                409,
            )
        if not row.report:
            raise _error("report_not_ready", "报告还没生成好，请稍后再试。", 409)
        enforce_ip_daily_limit(row.created_ip_hash)
        share_token = secrets.token_urlsafe(24)
        row.share_token_sha256 = hash_share_token(share_token)
        session.commit()
        return row, share_token


def read_share(share_token: str) -> dict[str, Any]:
    """读分享视图（**摘要层**：不含企业自填原文与联系方式）。"""
    from fde_api.diagnostics.report_contract import report_share_view

    if not share_token or not share_token.strip():
        raise _error("share_not_found", "链接不存在或已失效。", 404)
    with db.session() as session:
        row = session.scalars(
            select(LeadDiagnosticSession).where(
                LeadDiagnosticSession.share_token_sha256 == hash_share_token(share_token)
            )
        ).first()
        if row is None or _enforce_retention(session, row):
            raise _error("share_not_found", "链接不存在或已失效。", 404)
        view = report_share_view(row.report)
        if view is None:
            raise _error("share_not_found", "链接不存在或已失效。", 404)
        return view


def serialize_session(row: LeadDiagnosticSession, *, include_report: bool | None = None) -> dict[str, Any]:
    """序列化（对外形态）。报告只在**已留资**时可见（留资闸）。"""
    captured = bool(row.lead_contact)
    if include_report is None:
        include_report = captured
    answers = row.answers or {}
    return {
        "id": row.id,
        "status": row.status,
        "assessment": row.assessment,
        "answered_slots": sorted(answers.keys()),
        "lead_captured": captured,
        "report": row.report if include_report else None,
        "report_state": report_state(row),
        "report_requested_at": (
            row.report_requested_at.isoformat() if row.report_requested_at else None
        ),
        "report_failure": (
            {"code": row.failure_code, "message": row.failure_message}
            if row.failure_code
            else None
        ),
        "share_available": bool(row.share_token_sha256),
        "source_type": row.source_type,
        "expires_at": row.expires_at.isoformat() if row.expires_at else None,
        "claim_window_expires_at": (
            row.claim_window_expires_at.isoformat() if row.claim_window_expires_at else None
        ),
    }

