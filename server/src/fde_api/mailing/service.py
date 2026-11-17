"""WP-E SES 发送编排与 SNS 回调处理（goal-r3 G9 预建）。

两层职责：

``send_email`` —— 发送路径。闸门顺序 = policy.decide_send（开关 → 幂等 →
抑制 → 限额），全过才打 SES；throttle 记事件并抛可重试错误（调用方按
policy.retry_allows/next_retry_delay 退避重试）。

``handle_sns_envelope`` —— SNS 退信/投诉回调端点的处理核。鉴权 = SNS
消息签名校验（Signature v1，RSA-SHA256，签名证书必须来自 sns.*.amazonaws.com）
+ TopicArn 白名单——SNS 回调不可能携带工作台 JWT，签名即鉴权。事件按
event_key 幂等落库（SNS at-least-once 投递，重放不重复计）。

模块关闭（FDE_SES_ENABLED!=true）时两个入口一律拒绝——预建不动现有行为。
"""
from __future__ import annotations

import base64
import hashlib
import json
import re
from datetime import UTC, datetime, time
from typing import Any, Callable
from urllib.request import urlopen

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from fde_api.config import Settings
from fde_api.mailing import policy
from fde_api.mailing.channel import (
    CHANNEL_SES,
    CHANNEL_SMTP,
    MailChannelConflictError,
    resolve_channel,
)
from fde_api.mailing.models import (
    SUPPRESSING_TYPES,
    MailingEvent,
    MailingSend,
)
from fde_api.mailing.ses_client import SesClient, SesSendError, create_ses_client
from fde_api.mailing.smtp_client import create_smtp_client

SNS_CERT_URL_PATTERN = re.compile(r"^https://sns\.[a-z0-9-]+\.amazonaws\.com(:443)?/")
# SNS Signature-1 的字段拼接顺序（AWS 文档固定）：Notification 无 Subject 时为
# Message, MessageId, Timestamp, TopicArn, Type；确认类再加 SubscribeURL。
_SNS_NOTIFICATION_ORDER = ("Message", "MessageId", "Timestamp", "TopicArn", "Type")
_SNS_SUBSCRIPTION_ORDER = (
    "Message",
    "MessageId",
    "SubscribeURL",
    "Timestamp",
    "TopicArn",
    "Type",
)


class MailingServiceError(Exception):
    def __init__(self, code: str, message: str, http_status: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.http_status = http_status


def _today_start_utc(now: datetime) -> datetime:
    return datetime.combine(now.astimezone(UTC).date(), time.min, tzinfo=UTC)


def _sender_domain(address: str) -> str:
    return address.rsplit("@", 1)[-1].strip().rstrip(".").lower()


def create_mail_client(settings: Settings) -> SesClient | None:
    """按生效通道构造发信客户端（SES / SMTP 二选一；都未启用返回 None）。

    **SES 键路径一字未动**：本函数只在既有 ``create_ses_client`` 前面加一道
    通道分支——模块级名字在调用时解析，既有以
    ``fde_api.mailing.service.create_ses_client`` 打桩的测试仍命中同一条 SES 路径。
    """
    try:
        channel = resolve_channel(settings)
    except MailChannelConflictError:
        return None
    if channel == CHANNEL_SMTP:
        return create_smtp_client(settings)
    if channel == CHANNEL_SES:
        return create_ses_client(settings)
    return None


def send_email(
    *,
    settings: Settings,
    session: Session,
    recipient: str,
    subject: str,
    body: str,
    idempotency_key: str,
    client: SesClient | None = None,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> dict[str, Any]:
    """按策略闸门发一封纯文本邮件；返回 {action, message_id?}。

    闸门顺序（policy.decide_send）：开关 → 幂等键 → 收件人抑制 → 当日限额。
    发信域约束在闸门前先查（FROM 必须落在配置子域内，主域不发信）。
    闸门全部通道无关（注册制试用开闸 R1：发信通道 SES 或 SMTP 由配置择一）。
    """
    try:
        channel = resolve_channel(settings)
    except MailChannelConflictError as error:
        raise MailingServiceError(
            policy.DROP_DISABLED, "发信通道配置冲突（SES 与 SMTP 不可同开）。", 409
        ) from error
    resolved = client if client is not None else create_mail_client(settings)
    # 闸门前置拦截顺序与 policy 一致：先「开关」（关闭=disabled，与子域是否
    # 配置无关），再「发信域约束」（FROM 必须落在允许子域，主域不发信）。
    if resolved is None or channel is None:
        raise MailingServiceError(policy.DROP_DISABLED, "发信通道未启用。", 409)
    if channel == CHANNEL_SES:
        sender = settings.ses_from_address
        allowed_root = settings.ses_send_subdomain
    else:
        sender = settings.smtp_from
        allowed_root = settings.smtp_send_subdomain
    domain = _sender_domain(sender)
    if not policy.is_allowed_sender_domain(domain, allowed_root):
        raise MailingServiceError(
            policy.DROP_DOMAIN,
            f"发件域 {domain} 不在允许子域内。",
            409,
        )

    seen_keys = session.scalars(
        select(MailingSend.idempotency_key).where(
            MailingSend.idempotency_key == idempotency_key
        )
    ).all()
    suppressed = _recipient_suppressed(session, recipient)
    today_sent = session.scalar(
        select(func.count())
        .select_from(MailingSend)
        .where(MailingSend.sent_at >= _today_start_utc(now()))
    )
    decision = policy.decide_send(
        enabled=channel is not None,
        message_id=idempotency_key,
        seen_message_ids=seen_keys,
        recipient_suppressed=suppressed,
        today_sent_count=int(today_sent or 0),
        daily_limit=settings.ses_daily_limit,
    )
    if decision.action != policy.SEND:
        raise MailingServiceError(decision.action, f"发送被策略拒绝：{decision.action}", 409)

    try:
        message_id = resolved.send_text(
            sender=sender, recipient=recipient, subject=subject, body=body
        )
    except SesSendError as error:
        _record_event(
            session,
            event_key=f"{idempotency_key}:{error.code}:{recipient}",
            notification_type=(
                "throttle" if error.code == "throttle" else "send_failed"
            ),
            recipient=recipient,
            feedback_type=error.code,
        )
        raise MailingServiceError(
            error.code, error.message, 503 if error.retryable else 502
        ) from error

    session.add(
        MailingSend(
            idempotency_key=idempotency_key,
            message_id=message_id,
            sender=sender,
            recipient=recipient,
            status="sent",
            sent_at=now(),
        )
    )
    session.commit()
    return {"action": policy.SEND, "message_id": message_id}


def _recipient_suppressed(session: Session, recipient: str) -> bool:
    """地址抑制 = 已有 bounce/complaint 事件（bounce/complaint 是地址级死刑）。"""
    if not recipient:
        return False
    hit = session.scalar(
        select(MailingEvent.id)
        .where(
            MailingEvent.recipient == recipient,
            MailingEvent.notification_type.in_(SUPPRESSING_TYPES),
        )
        .limit(1)
    )
    return hit is not None


def _record_event(
    session: Session,
    *,
    event_key: str,
    notification_type: str,
    recipient: str = "",
    feedback_type: str = "",
    message_id: str = "",
    payload: str = "",
    occurred_at: datetime | None = None,
) -> bool:
    """幂等落一条事件；键已存在返回 False（SNS 重放）。"""
    exists = session.scalar(
        select(MailingEvent.id).where(MailingEvent.event_key == event_key).limit(1)
    )
    if exists is not None:
        return False
    session.add(
        MailingEvent(
            event_key=event_key,
            message_id=message_id,
            notification_type=notification_type,
            recipient=recipient,
            feedback_type=feedback_type,
            payload_sha256=hashlib.sha256(payload.encode("utf-8")).hexdigest() if payload else "",
            occurred_at=occurred_at,
        )
    )
    session.commit()
    return True


# --------------------------------------------------------------------------
# SNS 回调处理
# --------------------------------------------------------------------------

Fetcher = Callable[[str], bytes]


def _default_fetch(url: str) -> bytes:
    with urlopen(url, timeout=10) as response:  # noqa: S310 - URL 已过白名单校验
        return response.read()


def _verify_sns_signature(envelope: dict[str, Any], fetch: Fetcher) -> None:
    """校验 SNS 消息签名（Signature-1，RSA-SHA256 over 固定字段序）。"""
    url = envelope.get("SigningCertURL")
    signature_b64 = envelope.get("Signature")
    if not isinstance(url, str) or not SNS_CERT_URL_PATTERN.match(url):
        raise MailingServiceError(
            "invalid_sns_certificate_url", "SNS 证书地址不在 amazonaws 域。", 403
        )
    if not isinstance(signature_b64, str) or not signature_b64:
        raise MailingServiceError("invalid_sns_signature", "缺少签名。", 403)
    message_type = envelope["Type"]
    field_order = (
        _SNS_SUBSCRIPTION_ORDER
        if message_type in ("SubscriptionConfirmation", "UnsubscribeConfirmation")
        else _SNS_NOTIFICATION_ORDER
    )
    # 带 Subject 的通知在其后追加 Subject 字段（当前 SES 配置集不走该形态，兜底）
    fields = list(field_order)
    if message_type == "Notification" and isinstance(envelope.get("Subject"), str):
        fields.insert(fields.index("Timestamp"), "Subject")
    canonical = "".join(str(envelope.get(field, "")) for field in fields)

    cert_pem = fetch(url)
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import padding
    from cryptography.hazmat.primitives.asymmetric.rsa import RSAPublicKey

    try:
        cert = x509.load_pem_x509_certificate(cert_pem)
        public_key = cert.public_key()
        if not isinstance(public_key, RSAPublicKey):
            # SNS 只用 RSA 证书签名；其他类型一律判为校验不过。
            raise TypeError("sns certificate is not RSA")
        public_key.verify(
            base64.b64decode(signature_b64),
            canonical.encode("utf-8"),
            padding.PKCS1v15(),
            hashes.SHA256(),
        )
    except Exception as error:  # noqa: BLE001 - 签名/证书任何失败都归为校验不过
        raise MailingServiceError(
            "invalid_sns_signature", "SNS 签名校验未通过。", 403
        ) from error


def handle_sns_envelope(
    *,
    settings: Settings,
    session: Session,
    envelope: Any,
    fetch: Fetcher | None = None,
) -> dict[str, Any]:
    """SNS 回调入口：签名校验 → 主题白名单 → 按 Type 分发落事件。

    fetch 可注入（测试不外联；路由路径 monkeypatch ``_default_fetch``）。
    返回 {status, recorded, duplicates}；任何校验失败抛 MailingServiceError(403)。
    """
    fetch = fetch or _default_fetch
    if not settings.ses_enabled:
        raise MailingServiceError("mailing_disabled", "SES 发信模块未启用。", 403)
    if not isinstance(envelope, dict):
        raise MailingServiceError("invalid_sns_envelope", "SNS 消息必须是对象。", 400)
    for field in ("Type", "MessageId", "TopicArn", "Timestamp", "Signature", "Message"):
        if not isinstance(envelope.get(field), str) or not envelope[field]:
            raise MailingServiceError(
                "invalid_sns_envelope", f"SNS 消息缺少字段 {field}。", 400
            )
    if envelope["TopicArn"] != settings.ses_topic_arn:
        raise MailingServiceError("unknown_sns_topic", "SNS 主题不在白名单。", 403)
    _verify_sns_signature(envelope, fetch)

    message_type = envelope["Type"]
    if message_type in ("SubscriptionConfirmation", "UnsubscribeConfirmation"):
        # 订阅确认：SNS 要求回访 SubscribeURL 才开始推送。回访 URL 与签名证书
        # 同样只允许 sns.*.amazonaws.com（纵深防御：签名通过也不外访他域）。
        if not SNS_CERT_URL_PATTERN.match(envelope.get("SubscribeURL") or ""):
            raise MailingServiceError(
                "invalid_sns_subscribe_url", "SubscribeURL 不在 amazonaws 域。", 403
            )
        fetch(envelope["SubscribeURL"])
        confirmed = _record_event(
            session,
            event_key=f"{envelope['MessageId']}:{message_type}",
            notification_type="subscription_confirmed",
            message_id=envelope["MessageId"],
            feedback_type=message_type,
            payload=envelope["Message"],
            occurred_at=_parse_sns_timestamp(envelope["Timestamp"]),
        )
        return {"status": "confirmed", "recorded": int(confirmed), "duplicates": 0}

    if message_type != "Notification":
        raise MailingServiceError(
            "unsupported_sns_type", f"不支持的 SNS 消息类型 {message_type}。", 400
        )

    try:
        notification = json.loads(envelope["Message"])
    except (json.JSONDecodeError, ValueError) as error:
        raise MailingServiceError(
            "invalid_sns_notification", "SNS Notification 内容不是合法 JSON。", 400
        ) from error
    if not isinstance(notification, dict):
        raise MailingServiceError(
            "invalid_sns_notification", "SNS Notification 内容必须是对象。", 400
        )
    notification_type = notification.get("notificationType")
    if notification_type not in ("bounce", "complaint", "delivery"):
        raise MailingServiceError(
            "unsupported_notification_type",
            f"不支持的 SES 通知类型 {notification_type!r}。",
            400,
        )
    ses_message_id = str((notification.get("mail") or {}).get("messageId") or "")
    feedback = notification.get(notification_type) or {}
    recipients = [
        str(item.get("emailAddress") or "")
        for item in (feedback.get("bouncedRecipients") or feedback.get("complainedRecipients") or [])
    ]
    if notification_type == "delivery":
        recipients = [
            str(item.get("emailAddress") or "")
            for item in (feedback.get("recipients") or [])
        ]
    feedback_type = str(
        feedback.get("bounceSubType") or feedback.get("complaintFeedbackType") or ""
    )
    recorded = duplicates = 0
    occurred_at = _parse_sns_timestamp(envelope["Timestamp"])
    for recipient in {r for r in recipients if r} or {""}:
        event_key = f"{ses_message_id or envelope['MessageId']}:{notification_type}:{recipient}"
        if _record_event(
            session,
            event_key=event_key,
            notification_type=notification_type,
            recipient=recipient,
            feedback_type=feedback_type,
            message_id=ses_message_id,
            payload=envelope["Message"],
            occurred_at=occurred_at,
        ):
            recorded += 1
        else:
            duplicates += 1
    return {"status": "processed", "recorded": recorded, "duplicates": duplicates}


def _parse_sns_timestamp(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
