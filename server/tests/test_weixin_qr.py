from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import select

from fde_api.auth.models import User
from fde_api.auth.tokens import issue_access_token
from fde_api.control.clawbot_weixin import begin_login, poll_login, seal, status, trusted_url, unbind, unseal, weixin_blueprint
from fde_api.control.models import ChannelBinding
from fde_api.control.service import ControlServiceError
from fde_api.control.weixin_models import WeixinAccount, WeixinInbox
from fde_api.control.weixin_worker import _process_account


class FakeClient:
    def __init__(self):
        self.calls = []
        self.result = {"status": "wait"}
        self.messages = []
        self.fail_send = False

    def call(self, endpoint, **kwargs):
        self.calls.append((endpoint, kwargs))
        if endpoint == "get_bot_qrcode":
            return {"qrcode": "secret-provider-qr", "qrcode_img_content": "https://liteapp.weixin.qq.com/q/test?bot_type=3"}
        if endpoint == "get_qrcode_status":
            return self.result
        if endpoint == "getupdates":
            return {"msgs": self.messages, "get_updates_buf": "private-cursor"}
        if endpoint == "sendmessage":
            if self.fail_send:
                raise RuntimeError("network uncertain")
            return {"ret": 0}
        raise AssertionError(endpoint)


@pytest.fixture
def weixin(app, db_session, monkeypatch):
    monkeypatch.setenv("FDE_WEIXIN_ENABLED", "true")
    monkeypatch.setenv("FDE_WEIXIN_CREDENTIAL_KEY", Fernet.generate_key().decode())
    fake = FakeClient()
    app.extensions["fde_weixin_client"] = fake
    if "weixin" not in app.blueprints:
        app.register_blueprint(weixin_blueprint)
    user = User(username=f"wx-{uuid4().hex}", display_name="Tester", password_hash="unused", role="admin", is_active=True, must_change_password=False)
    db_session.add(user)
    db_session.commit()
    with app.app_context():
        yield user, fake


def confirm(user, fake):
    qr = begin_login(user.id)
    fake.result = {"status": "confirmed", "bot_token": "top-secret-token", "ilink_bot_id": "bot-1",
                   "ilink_user_id": "scanner-1", "baseurl": "https://ilinkai.weixin.qq.com"}
    result = poll_login(user.id, qr["login_id"])
    assert result["connected"] is True
    return qr


def test_real_qr_is_encoded_and_tokens_are_encrypted(weixin, db_session):
    user, fake = weixin
    qr = begin_login(user.id)
    assert qr["qr_image"].startswith("data:image/svg+xml;base64,")
    assert "binding_code" not in qr
    assert "secret-provider-qr" not in str(qr)
    account = db_session.scalar(select(WeixinAccount))
    assert "secret-provider-qr" not in account.login_encrypted
    assert unseal(account.login_encrypted)["qrcode"] == "secret-provider-qr"
    assert fake.calls[0][1]["params"] == {"bot_type": "3"}


def test_confirmation_uses_scanner_and_never_returns_credentials(weixin, db_session):
    user, fake = weixin
    qr = confirm(user, fake)
    assert "top-secret-token" not in str(status(user.id))
    account = db_session.scalar(select(WeixinAccount))
    assert "top-secret-token" not in account.credentials_encrypted
    assert "qrcode" not in unseal(account.login_encrypted)
    assert poll_login(user.id, qr["login_id"])["connected"] is True
    assert unbind(user.id)["connected"] is False
    db_session.rollback()
    assert db_session.get(WeixinAccount, account.id).credentials_encrypted == ""


def test_replaced_qr_cannot_complete_or_access_other_account(weixin, db_session):
    user, fake = weixin
    old = begin_login(user.id)
    account = db_session.scalar(select(WeixinAccount))
    account.login_expires_at -= timedelta(seconds=5)
    db_session.commit()
    begin_login(user.id)
    with pytest.raises(ControlServiceError, match="二维码已更新"):
        poll_login(user.id, old["login_id"])
    with pytest.raises(ControlServiceError, match="请先生成"):
        poll_login(str(uuid4()), old["login_id"])


def test_qr_generation_rate_limited(weixin):
    user, fake = weixin
    begin_login(user.id)
    with pytest.raises(ControlServiceError) as error:
        begin_login(user.id)
    assert error.value.status == 429
    assert len(fake.calls) == 1


def test_expired_qr_cannot_activate(weixin, db_session):
    user, fake = weixin
    qr = begin_login(user.id)
    account = db_session.scalar(select(WeixinAccount))
    account.login_expires_at = datetime.now(UTC) - timedelta(seconds=1)
    db_session.commit()
    assert poll_login(user.id, qr["login_id"])["login_status"] == "expired"
    assert len(fake.calls) == 1


def test_failed_rebinding_keeps_current_connection(weixin, db_session):
    user, fake = weixin
    confirm(user, fake)
    account = db_session.scalar(select(WeixinAccount))
    original = account.credentials_encrypted
    qr = begin_login(user.id)
    assert qr["connected"] is True
    fake.result = {"status": "expired"}
    assert poll_login(user.id, qr["login_id"])["connected"] is True
    db_session.rollback()
    assert db_session.get(WeixinAccount, account.id).credentials_encrypted == original


@pytest.mark.parametrize("url", ["https://evil.test", "http://ilinkai.weixin.qq.com", "https://ilinkai.weixin.qq.com.evil.test", "https://ilinkai.weixin.qq.com@127.0.0.1", "https://ilinkai.weixin.qq.com:9999"])
def test_untrusted_provider_urls_rejected(url):
    with pytest.raises(ControlServiceError):
        trusted_url(url, api=True)


def test_redirect_and_phone_verification_flow(weixin):
    user, fake = weixin
    qr = begin_login(user.id)
    fake.result = {"status": "scaned_but_redirect", "redirect_host": "ilinkai-gw.weixin.qq.com"}
    assert poll_login(user.id, qr["login_id"])["login_status"] == "scaned_but_redirect"
    fake.result = {"status": "need_verifycode"}
    assert poll_login(user.id, qr["login_id"])["login_status"] == "need_verifycode"
    poll_login(user.id, qr["login_id"], "123456")
    assert fake.calls[-1][1]["params"]["verify_code"] == "123456"
    assert fake.calls[-1][1]["base_url"] == "https://ilinkai-gw.weixin.qq.com"


def test_missing_scanner_cannot_activate(weixin):
    user, fake = weixin
    qr = begin_login(user.id)
    fake.result = {"status": "confirmed", "bot_token": "secret", "ilink_bot_id": "bot"}
    with pytest.raises(ControlServiceError, match="扫码者身份"):
        poll_login(user.id, qr["login_id"])
    assert status(user.id)["connected"] is False


def test_binding_endpoints_require_auth_and_are_current_user_scoped(weixin, app, client, settings):
    user, fake = weixin
    assert client.post("/api/v1/account/wechat-clawbot/qr", json={}).status_code == 401
    headers = {"Authorization": "Bearer " + issue_access_token(user, settings)}
    result = client.post("/api/v1/account/wechat-clawbot/qr", json={}, headers=headers)
    assert result.status_code == 201
    assert client.post("/api/v1/account/wechat-clawbot/qr/poll", json={"login_id": result.json["data"]["login_id"], "verify_code": "not digits"}, headers=headers).status_code == 400


def test_messages_persist_before_cursor_ignore_others_and_retry_send_without_reexecution(weixin, app, db_session):
    user, fake = weixin
    confirm(user, fake)
    account = db_session.scalar(select(WeixinAccount))
    message = {"message_id": 7, "from_user_id": "scanner-1", "message_type": 1,
               "context_token": "secret-context", "item_list": [{"type": 1, "text_item": {"text": "请查项目"}}]}
    fake.messages = [message, message, {**message, "message_id": 8, "from_user_id": "stranger"}]
    events = []
    app.extensions["fde_weixin_message_handler"] = lambda actor, text, event: events.append((actor, text, event)) or "已查到项目"
    fake.fail_send = True
    with pytest.raises(RuntimeError):
        _process_account(account.id)
    db_session.rollback()
    items = db_session.scalars(select(WeixinInbox)).all()
    assert len(items) == 1 and items[0].status == "ready"
    assert "请查项目" not in items[0].payload_encrypted
    assert unseal(db_session.get(WeixinAccount, account.id).cursor_encrypted)["cursor"] == "private-cursor"
    fake.fail_send = False
    _process_account(account.id)
    _process_account(account.id)
    assert len(events) == 1 and events[0][0] == user.id
    db_session.rollback()
    assert db_session.get(WeixinInbox, items[0].id).status == "replied"
    sent = [args["payload"]["msg"] for endpoint, args in fake.calls if endpoint == "sendmessage"]
    assert sent[0]["client_id"] == sent[1]["client_id"]
    assert sent[-1]["to_user_id"] == "scanner-1"
