"""provider 无关 SMTP 发信客户端（注册制试用开闸 R1，2026-11-17）。

与 SES 通道同构：实现 :class:`~fde_api.mailing.ses_client.SesClient` 协议
（``send_text`` 返回 message-id 头形态标识），错误分类沿用 ``SesSendError``
（throttle 可重试 / message_rejected 不可重试）——``mailing/service.py`` 的五步
闸门与 ``mailing/policy.py`` 全部通道无关，**换通道不改闸门**。

运行形态（AI外贸获客线同款，2026-11-09 实发验证过）：标准库 smtplib 走
``smtp.zoho.com:587`` ＋ STARTTLS ＋ 账号登录。

TLS 纪律：一律加密——端口 465 走隐式 TLS（``SMTP_SSL``），其余端口走
STARTTLS；STARTTLS 不可用即失败（**不回落明文**：凭据不落明面）。

构造不建连接（连接在发送时建立）：配置错在启动期由 Settings 校验器拦，
连接错在发送期按 throttle/rejected 分类落事件。
"""
from __future__ import annotations

import smtplib
import ssl
from contextlib import contextmanager
from email.message import EmailMessage
from email.utils import make_msgid
from typing import Iterator

from pydantic import SecretStr

from fde_api.config import Settings
from fde_api.mailing.ses_client import SesClient, SesSendError

SMTP_TIMEOUT_SECONDS = 30
# 隐式 TLS 端口（465）；其余端口走 STARTTLS（587 等）。
IMPLICIT_TLS_PORT = 465


def _new_message_id(sender: str) -> str:
    """message-id 头形态标识（台账 message_id 语义不变＝发送方给的唯一标识）。"""
    domain = sender.rsplit("@", 1)[-1].strip() or "localhost"
    try:
        return make_msgid(domain=domain)
    except (UnicodeError, ValueError):
        return make_msgid()


def _build_message(
    *, sender: str, recipient: str, subject: str, body: str
) -> EmailMessage:
    """纯文本邮件（UTF-8）；Message-ID 头随信发出＝回执标识与台账一致。"""
    message = EmailMessage()
    message["From"] = sender
    message["To"] = recipient
    message["Subject"] = subject
    message["Message-ID"] = _new_message_id(sender)
    message.set_content(body, charset="utf-8")
    return message


def _secret_value(password: SecretStr | str | None) -> str:
    """取口令明文（SecretStr 为主；model_copy 旁路校验时可能是裸 str）。"""
    if password is None:
        return ""
    if isinstance(password, SecretStr):
        return password.get_secret_value()
    return str(password)


class SmtplibClient:
    """SMTP 真客户端（标准库 smtplib；发送时建连，构造零网络）。"""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def send_text(self, *, sender: str, recipient: str, subject: str, body: str) -> str:
        message = _build_message(
            sender=sender, recipient=recipient, subject=subject, body=body
        )
        message_id = message["Message-ID"]
        try:
            with self._connect() as client:
                client.send_message(message)
        except smtplib.SMTPAuthenticationError as error:
            raise SesSendError(
                "message_rejected", "SMTP 认证被拒。", retryable=False
            ) from error
        except smtplib.SMTPRecipientsRefused as error:
            raise SesSendError(
                "message_rejected", "SMTP 收件人被拒。", retryable=False
            ) from error
        except smtplib.SMTPSenderRefused as error:
            raise SesSendError(
                "message_rejected", "SMTP 发件人被拒。", retryable=False
            ) from error
        except smtplib.SMTPResponseException as error:
            code = getattr(error, "smtp_code", 0) or 0
            if 400 <= code < 500:
                raise SesSendError(
                    "throttle", f"SMTP 临时失败（{code}）。", retryable=True
                ) from error
            raise SesSendError(
                "message_rejected", f"SMTP 拒收（{code}）。", retryable=False
            ) from error
        except smtplib.SMTPNotSupportedError as error:
            raise SesSendError(
                "send_failed",
                "SMTP 服务端不支持必要扩展（STARTTLS/AUTH）——不回落明文、不降级认证。",
                retryable=False,
            ) from error
        except (
            smtplib.SMTPConnectError,
            smtplib.SMTPServerDisconnected,
            TimeoutError,
            OSError,
        ) as error:
            raise SesSendError(
                "throttle", "SMTP 连接失败。", retryable=True
            ) from error
        except smtplib.SMTPException as error:
            raise SesSendError(
                "send_failed", "SMTP 发送失败。", retryable=False
            ) from error
        return message_id

    @contextmanager
    def _connect(self) -> Iterator[smtplib.SMTP]:
        settings = self._settings
        host = settings.smtp_host
        port = int(settings.smtp_port)
        secret = _secret_value(settings.smtp_password)
        if port == IMPLICIT_TLS_PORT:
            client: smtplib.SMTP = smtplib.SMTP_SSL(
                host, port, timeout=SMTP_TIMEOUT_SECONDS
            )
        else:
            client = smtplib.SMTP(host, port, timeout=SMTP_TIMEOUT_SECONDS)
        try:
            if port != IMPLICIT_TLS_PORT:
                client.starttls(context=ssl.create_default_context())
            client.login(settings.smtp_username, secret)
            yield client
        finally:
            try:
                client.quit()
            except (smtplib.SMTPException, OSError):
                pass


def create_smtp_client(settings: Settings) -> SesClient | None:
    """工厂：SMTP 通道关闭返回 None（调用方落 drop_disabled）。"""
    if not settings.smtp_enabled:
        return None
    return SmtplibClient(settings)
