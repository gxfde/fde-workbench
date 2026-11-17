"""SMTP 发信通道（注册制试用开闸 R1）——纯 mock 覆盖，**绝不发送真实邮件**。

红线：smtplib 面全部打桩（假 SMTP/SMTP_SSL 类），断言只落在「行为与错误分类」，
不触网、不连库发信。

覆盖面：
- SmtplibClient：STARTTLS 路径（587）与隐式 TLS 路径（465）、Message-ID 头形态
  标识、错误分类（认证拒收/4xx 节流/5xx 拒收/连接失败节流/STARTTLS 不支持）；
- 工厂与通道解析：SMTP 生效、SES 生效（**SES 键路径零改动**）、两通道同开 fail-closed；
- 配置校验器：缺键必填齐、FROM 必须落在允许发信域根内（主域不发信）、两开关互斥；
- 服务层：send_email 通道无关（发件人取自通道配置、发信域闸复用、幂等台账不变）；
- 注册面开闸三条件通道无关（surface_open）。
"""
from __future__ import annotations

import smtplib
from email.message import EmailMessage
from typing import Any

import pytest
from sqlalchemy import select

from fde_api.config import Settings
from fde_api.mailing import channel as channel_module
from fde_api.mailing import service
from fde_api.mailing.channel import (
    CHANNEL_SES,
    CHANNEL_SMTP,
    MailChannelConflictError,
    channel_enabled,
    resolve_channel,
)
from fde_api.mailing.models import MailingSend
from fde_api.mailing.ses_client import SesSendError
from fde_api.mailing.service import MailingServiceError, send_email
from fde_api.mailing.smtp_client import SmtplibClient, create_smtp_client
from fde_api.registration.service import surface_open

SMTP_FROM = "no-reply@fde18.com"
SMTP_ROOT = "fde18.com"


# ---------------------------------------------------------------------------
# 假 SMTP 客户端（零网络）
# ---------------------------------------------------------------------------


class FakeSMTP:
    """假 SMTP 连接：记录调用，可按钩子抛异常。"""

    instances: list["FakeSMTP"] = []

    def __init__(self, host: str, port: int, timeout: float | None = None) -> None:
        self.host = host
        self.port = port
        self.timeout = timeout
        self.starttls_calls = 0
        self.login_calls: list[tuple[str, str]] = []
        self.sent: list[EmailMessage] = []
        self.quit_calls = 0
        self.hooks: dict[str, Exception] = {}
        FakeSMTP.instances.append(self)

    def _maybe_raise(self, hook: str) -> None:
        error = self.hooks.get(hook)
        if error is not None:
            raise error

    def starttls(self, context: Any = None) -> tuple[int, bytes]:
        self.starttls_calls += 1
        self._maybe_raise("starttls")
        return (220, b"Ready to start TLS")

    def login(self, user: str, password: str) -> tuple[int, bytes]:
        self.login_calls.append((user, password))
        self._maybe_raise("login")
        return (235, b"Authentication successful")

    def send_message(self, message: EmailMessage) -> dict[str, Any]:
        self._maybe_raise("send_message")
        self.sent.append(message)
        return {}

    def quit(self) -> tuple[int, bytes]:
        self.quit_calls += 1
        return (221, b"Bye")


@pytest.fixture
def fake_smtp(monkeypatch):
    """把 smtplib.SMTP / smtplib.SMTP_SSL 换成假实现。"""
    FakeSMTP.instances = []
    monkeypatch.setattr(smtplib, "SMTP", FakeSMTP)
    monkeypatch.setattr(smtplib, "SMTP_SSL", FakeSMTP)
    return FakeSMTP


def smtp_settings(test_settings: Settings, **overrides: Any) -> Settings:
    """SMTP 通道启用态配置（model_copy 跳过校验器——非法面由此构造）。"""
    return test_settings.model_copy(
        update={
            "smtp_enabled": True,
            "smtp_host": "smtp.zoho.com",
            "smtp_port": 587,
            "smtp_username": "trial@fde18.com",
            "smtp_password": "Smtp-Secret-Value-1",
            "smtp_from": SMTP_FROM,
            "smtp_send_subdomain": SMTP_ROOT,
            "ses_enabled": False,
            **overrides,
        }
    )


# ---------------------------------------------------------------------------
# SmtplibClient：连与 TLS 纪律
# ---------------------------------------------------------------------------


def test_smtp_sends_over_starttls_and_returns_message_id(fake_smtp, test_settings):
    client = SmtplibClient(smtp_settings(test_settings))
    message_id = client.send_text(
        sender=SMTP_FROM, recipient="lead@example.com", subject="邮箱验证", body="正文"
    )
    conn = fake_smtp.instances[-1]
    assert conn.host == "smtp.zoho.com"
    assert conn.port == 587
    assert conn.starttls_calls == 1
    assert conn.login_calls == [("trial@fde18.com", "Smtp-Secret-Value-1")]
    assert len(conn.sent) == 1
    sent = conn.sent[0]
    assert sent["To"] == "lead@example.com"
    assert sent["From"] == SMTP_FROM
    assert sent["Subject"] == "邮箱验证"
    # message-id 头形态标识＝随信发出的 Message-ID（台账语义不变）
    assert message_id == sent["Message-ID"]
    assert message_id.startswith("<") and message_id.endswith(">")


def test_smtp_implicit_tls_port_uses_ssl_socket(fake_smtp, test_settings):
    client = SmtplibClient(smtp_settings(test_settings, smtp_port=465))
    client.send_text(
        sender=SMTP_FROM, recipient="lead@example.com", subject="s", body="b"
    )
    conn = fake_smtp.instances[-1]
    assert conn.port == 465
    # 隐式 TLS 端口不再叠加 STARTTLS
    assert conn.starttls_calls == 0
    assert conn.login_calls


def test_smtp_quits_connection_after_send(fake_smtp, test_settings):
    client = SmtplibClient(smtp_settings(test_settings))
    client.send_text(sender=SMTP_FROM, recipient="lead@example.com", subject="s", body="b")
    assert fake_smtp.instances[-1].quit_calls == 1


def test_smtp_starttls_unsupported_fails_closed_without_login(fake_smtp, test_settings):
    """STARTTLS 不可用 ⇒ 失败且**不 login**（凭据不落明面）。"""
    client = SmtplibClient(smtp_settings(test_settings))
    fake_smtp.instances.clear()
    original_init = FakeSMTP.__init__

    def _init_with_hook(self, host, port, timeout=None):
        original_init(self, host, port, timeout)
        self.hooks["starttls"] = smtplib.SMTPNotSupportedError("STARTTLS not supported")

    FakeSMTP.__init__ = _init_with_hook  # type: ignore[method-assign]
    try:
        with pytest.raises(SesSendError) as err:
            client.send_text(
                sender=SMTP_FROM, recipient="lead@example.com", subject="s", body="b"
            )
    finally:
        FakeSMTP.__init__ = original_init  # type: ignore[method-assign]
    assert err.value.code == "send_failed"
    assert err.value.retryable is False
    assert fake_smtp.instances[-1].login_calls == []


# ---------------------------------------------------------------------------
# SmtplibClient：错误分类（throttle 可重试 / 拒收不可重试）
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("error", "expected_code", "expected_retryable"),
    [
        (smtplib.SMTPAuthenticationError(535, b"bad credentials"), "message_rejected", False),
        (smtplib.SMTPRecipientsRefused({"lead@example.com": (550, b"no such user")}), "message_rejected", False),
        (smtplib.SMTPSenderRefused(550, b"sender denied", SMTP_FROM), "message_rejected", False),
        (smtplib.SMTPResponseException(451, b"try later"), "throttle", True),
        (smtplib.SMTPResponseException(550, b"mailbox unavailable"), "message_rejected", False),
    ],
)
def test_smtp_error_classification(
    fake_smtp, test_settings, error, expected_code, expected_retryable
):
    client = SmtplibClient(smtp_settings(test_settings))
    fake_smtp.instances.clear()
    original_init = FakeSMTP.__init__

    def _init_with_hook(self, host, port, timeout=None):
        original_init(self, host, port, timeout)
        self.hooks["send_message"] = error

    FakeSMTP.__init__ = _init_with_hook  # type: ignore[method-assign]
    try:
        with pytest.raises(SesSendError) as err:
            client.send_text(
                sender=SMTP_FROM, recipient="lead@example.com", subject="s", body="b"
            )
    finally:
        FakeSMTP.__init__ = original_init  # type: ignore[method-assign]
    assert err.value.code == expected_code
    assert err.value.retryable is expected_retryable


def test_smtp_connection_failure_is_throttle(fake_smtp, test_settings):
    """连不上（拒绝/超时）⇒ 节流可重试，不是永久拒收。"""
    client = SmtplibClient(smtp_settings(test_settings))
    fake_smtp.instances.clear()
    original_init = FakeSMTP.__init__

    def _init_refused(self, host, port, timeout=None):
        raise ConnectionRefusedError("connection refused")

    FakeSMTP.__init__ = _init_refused  # type: ignore[method-assign]
    try:
        with pytest.raises(SesSendError) as err:
            client.send_text(
                sender=SMTP_FROM, recipient="lead@example.com", subject="s", body="b"
            )
    finally:
        FakeSMTP.__init__ = original_init  # type: ignore[method-assign]
    assert err.value.code == "throttle"
    assert err.value.retryable is True


# ---------------------------------------------------------------------------
# 工厂与通道解析
# ---------------------------------------------------------------------------


def test_create_smtp_client_disabled_returns_none(test_settings):
    assert create_smtp_client(test_settings) is None


def test_create_smtp_client_enabled_returns_client(test_settings):
    assert isinstance(create_smtp_client(smtp_settings(test_settings)), SmtplibClient)


def test_resolve_channel_prefers_nothing_when_disabled(test_settings):
    assert resolve_channel(test_settings) is None
    assert channel_enabled(test_settings) is False


def test_resolve_channel_smtp(test_settings):
    assert resolve_channel(smtp_settings(test_settings)) == CHANNEL_SMTP
    assert channel_enabled(smtp_settings(test_settings)) is True


def test_resolve_channel_conflict_raises(test_settings):
    settings = smtp_settings(test_settings, ses_enabled=True)
    with pytest.raises(MailChannelConflictError):
        resolve_channel(settings)


def test_service_factory_keeps_ses_path_untouched(monkeypatch, test_settings):
    """SMTP 生效时**不**走 SES 工厂；SES 生效时照旧走——SES 键路径零改动。"""
    calls: list[object] = []

    def _fake_ses(settings):
        calls.append(settings)
        return None

    monkeypatch.setattr(service, "create_ses_client", _fake_ses)
    monkeypatch.setattr(
        service, "create_smtp_client", lambda settings: SmtplibClient(settings)
    )
    service.create_mail_client(smtp_settings(test_settings))
    assert calls == []
    service.create_mail_client(
        test_settings.model_copy(update={"ses_enabled": True, "smtp_enabled": False})
    )
    assert len(calls) == 1


# ---------------------------------------------------------------------------
# 配置校验器
# ---------------------------------------------------------------------------


def _smtp_base(test_settings: Settings) -> dict[str, Any]:
    return dict(
        env="test",
        database_url=test_settings.database_url,
        redis_url="redis://127.0.0.1:16379/2",
        jwt_secret="test-secret-with-at-least-thirty-two-characters",
        smtp_enabled=True,
        smtp_host="smtp.zoho.com",
        smtp_port=587,
        smtp_username="trial@fde18.com",
        smtp_password="Smtp-Secret-Value-1",
        smtp_from=SMTP_FROM,
        smtp_send_subdomain=SMTP_ROOT,
    )


def test_settings_validator_accepts_complete_smtp_configuration(test_settings):
    settings = Settings(**_smtp_base(test_settings))
    assert settings.smtp_enabled is True
    assert settings.smtp_port == 587
    # 口令走 SecretStr：repr 不外泄
    assert "Smtp-Secret-Value-1" not in repr(settings)


@pytest.mark.parametrize(
    "missing",
    ["smtp_host", "smtp_username", "smtp_password", "smtp_from", "smtp_send_subdomain"],
)
def test_settings_validator_requires_smtp_fields(test_settings, missing):
    base = _smtp_base(test_settings)
    base[missing] = "" if missing != "smtp_password" else ""
    with pytest.raises(ValueError, match="missing_smtp_configuration"):
        Settings(**base)


def test_settings_validator_rejects_main_domain_sender(test_settings):
    base = _smtp_base(test_settings)
    base["smtp_from"] = "no-reply@somwyn.com"  # 主域不发信
    with pytest.raises(ValueError, match="smtp_sender_domain_forbidden"):
        Settings(**base)


def test_settings_validator_rejects_both_channels_enabled(test_settings):
    base = _smtp_base(test_settings)
    base["ses_enabled"] = True
    base["ses_send_subdomain"] = "mail.somwyn.com"
    base["ses_from_address"] = "no-reply@mail.somwyn.com"
    base["ses_topic_arn"] = "arn:aws:sns:us-east-1:111122223333:fde-mail-events"
    with pytest.raises(ValueError, match="smtp_and_ses_enabled_conflict"):
        Settings(**base)


# ---------------------------------------------------------------------------
# 服务层：send_email 通道无关
# ---------------------------------------------------------------------------


class FakeMailClient:
    """内存假客户端（通道无关协议面）。"""

    def __init__(self, message_id: str = "smtp-msg-1"):
        self.calls: list[dict[str, str]] = []
        self.message_id = message_id

    def send_text(self, *, sender: str, recipient: str, subject: str, body: str) -> str:
        self.calls.append(
            {"sender": sender, "recipient": recipient, "subject": subject, "body": body}
        )
        return self.message_id


def test_send_email_uses_smtp_sender_and_records_send(test_settings, db_session):
    fake = FakeMailClient()
    result = send_email(
        settings=smtp_settings(test_settings),
        session=db_session,
        recipient="lead@example.com",
        subject="邮箱验证",
        body="正文",
        idempotency_key="regtrial-smtp-1",
        client=fake,
    )
    assert result == {"action": "send", "message_id": "smtp-msg-1"}
    assert fake.calls[0]["sender"] == SMTP_FROM
    row = db_session.scalar(
        select(MailingSend).where(MailingSend.idempotency_key == "regtrial-smtp-1")
    )
    assert row is not None
    assert row.message_id == "smtp-msg-1"
    assert row.sender == SMTP_FROM


def test_send_email_rejects_sender_outside_allowed_domain(test_settings, db_session):
    fake = FakeMailClient()
    with pytest.raises(MailingServiceError) as err:
        send_email(
            settings=smtp_settings(test_settings, smtp_from="no-reply@somwyn.com"),
            session=db_session,
            recipient="lead@example.com",
            subject="s",
            body="b",
            idempotency_key="regtrial-smtp-2",
            client=fake,
        )
    assert err.value.code == "drop_sender_domain_forbidden"
    assert fake.calls == []


def test_send_email_conflicting_channels_fails_closed(test_settings, db_session):
    """两开关同开（绕过校验器构造）⇒ fail-closed，不静默择一。"""
    fake = FakeMailClient()
    settings = smtp_settings(test_settings, ses_enabled=True)
    with pytest.raises(MailingServiceError) as err:
        send_email(
            settings=settings,
            session=db_session,
            recipient="lead@example.com",
            subject="s",
            body="b",
            idempotency_key="regtrial-smtp-3",
            client=fake,
        )
    assert err.value.code == "drop_disabled"
    assert fake.calls == []


# ---------------------------------------------------------------------------
# 注册面开闸三条件（通道无关）
# ---------------------------------------------------------------------------


def test_registration_surface_open_with_smtp_channel(test_settings):
    settings = smtp_settings(
        test_settings,
        registration_enabled=True,
        public_base_url="https://app.fde18.com",
    )
    assert surface_open(settings) is True


def test_registration_surface_open_with_ses_channel_unchanged(test_settings):
    settings = test_settings.model_copy(
        update={
            "registration_enabled": True,
            "ses_enabled": True,
            "public_base_url": "https://app.fde18.com",
        }
    )
    assert surface_open(settings) is True


def test_registration_surface_closed_without_send_channel(test_settings):
    settings = test_settings.model_copy(
        update={
            "registration_enabled": True,
            "ses_enabled": False,
            "smtp_enabled": False,
            "public_base_url": "https://app.fde18.com",
        }
    )
    assert surface_open(settings) is False


def test_registration_surface_closed_without_public_base_url(test_settings):
    settings = smtp_settings(
        test_settings, registration_enabled=True, public_base_url=""
    )
    assert surface_open(settings) is False


def test_channel_module_is_single_authority(test_settings):
    """通道解析只有一处权威（channel 模块）——mailing 与 registration 同源。"""
    settings = smtp_settings(test_settings)
    assert channel_module.resolve_channel(settings) == CHANNEL_SMTP
    assert channel_module.channel_enabled(settings) is True
