"""Run with ``python -m fde_api.control.weixin_worker`` as the isolated FDE user.

The callback must durably deduplicate event_id and enforce the current user's AI
permissions: app.extensions['fde_weixin_message_handler'](user_id, text, event_id).
Inbox-before-cursor commits prevent message loss; stable reply client IDs make
uncertain send retries safe on the iLink side.
"""
from __future__ import annotations

import logging
import signal
import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import UTC, datetime
from hashlib import sha256

from flask import current_app
from sqlalchemy import select

from fde_api.auth.models import User
from fde_api.control.clawbot_weixin import _enabled, client, seal, unseal
from fde_api.control.models import ChannelBinding
from fde_api.control.service import ControlServiceError
from fde_api.control.weixin_models import WeixinAccount, WeixinInbox
from fde_api.extensions import db

logger = logging.getLogger(__name__)


def _bound(session, account_id: str):
    return session.execute(select(WeixinAccount, ChannelBinding).join(ChannelBinding).join(User, User.id == ChannelBinding.user_id).where(
        WeixinAccount.id == account_id, ChannelBinding.status == "active", ChannelBinding.commands_enabled.is_(True),
        User.is_active.is_(True))).first()


@contextmanager
def _typing_feedback(account_id, credentials_before, credentials, payload):
    """Best-effort iLink typing feedback; never delay or fail the saved reply."""
    app = current_app._get_current_object()
    stopped = threading.Event()

    def run():
        with app.app_context():
            try:
                transport = client()
                common = {"base_url": credentials["base_url"], "token": credentials["bot_token"], "timeout": 2}
                config = transport.call("getconfig", **common, payload={
                    "ilink_user_id": payload["sender"], "context_token": payload.get("context_token", "")})
                ticket = config.get("typing_ticket")
                if not isinstance(ticket, str) or not ticket:
                    return
                while True:
                    with db.session() as session:
                        row = _bound(session, account_id)
                        if not row or row[0].credentials_encrypted != credentials_before:
                            return
                    finishing = stopped.is_set()
                    transport.call("sendtyping", **common, payload={
                        "ilink_user_id": payload["sender"], "typing_ticket": ticket,
                        "status": 2 if finishing else 1})
                    if finishing:
                        return
                    stopped.wait(8)
            except Exception:
                # Progress feedback is optional; never log provider payloads.
                logger.debug("Weixin typing feedback unavailable")

    thread = threading.Thread(target=run, name="weixin-typing", daemon=True)
    thread.start()
    try:
        yield
    finally:
        stopped.set()


def process_account(account_id: str) -> None:
    """One bounded receive/dispatch iteration, protected by a cross-process lock."""
    redis = current_app.extensions["fde_api_redis"]
    lock = redis.lock(f"fde:weixin:poll:{account_id}", timeout=900, blocking=False)
    if not lock.acquire(blocking=False):
        return
    try:
        _process_account(account_id)
    except ControlServiceError as error:
        with db.session() as session, session.begin():
            account = session.get(WeixinAccount, account_id)
            if account:
                account.last_error_code = error.code
                if error.code == "weixin_session_expired":
                    binding = session.get(ChannelBinding, account.binding_id)
                    if binding:
                        binding.status = "paused"
        logger.warning("Weixin channel iteration failed (%s)", error.code)
    except Exception:
        # Provider/handler exception strings can contain credentials or user data.
        logger.error("Weixin channel iteration failed; will retry with the same event id")
    finally:
        try:
            lock.release()
        except Exception:
            logger.warning("Weixin channel lock expired")


def _process_account(account_id: str) -> None:
    with db.session() as session:
        row = _bound(session, account_id)
        if not row or not row[0].credentials_encrypted:
            return
        account, binding = row
        credentials = unseal(account.credentials_encrypted)
        cursor = unseal(account.cursor_encrypted).get("cursor", "")
        credentials_before = account.credentials_encrypted
        pending = session.scalar(select(WeixinInbox.id).where(WeixinInbox.account_id == account_id, WeixinInbox.status.in_(["pending", "ready"])).limit(1))

    if not pending:
        response = client().call("getupdates", base_url=credentials["base_url"], token=credentials["bot_token"],
                                 payload={"get_updates_buf": cursor}, timeout=35)
        messages = response.get("msgs", [])
        if not isinstance(messages, list) or len(messages) > 1000:
            raise ControlServiceError("weixin_invalid_messages", "微信消息格式无效。", 502)
        with db.session() as session, session.begin():
            row = _bound(session, account_id)
            if not row or row[0].credentials_encrypted != credentials_before:
                return
            account, binding = row
            for message in messages:
                # A QR login authorizes exactly the person who scanned it, not every bot sender.
                if (not isinstance(message, dict) or message.get("from_user_id") != credentials["ilink_user_id"]
                        or message.get("message_type") != 1 or message.get("group_id")):
                    continue
                message_id = message.get("message_id") or message.get("client_id")
                if message_id is None:
                    continue
                event_digest = sha256(f"{credentials['ilink_user_id']}\0{message_id}".encode()).hexdigest()
                if session.scalar(select(WeixinInbox.id).where(WeixinInbox.account_id == account_id, WeixinInbox.event_digest == event_digest)):
                    continue
                items = message.get("item_list", [])
                text_parts = []
                for item in items if isinstance(items, list) else []:
                    if not isinstance(item, dict) or item.get("type") != 1:
                        continue
                    text_item = item.get("text_item")
                    if isinstance(text_item, dict) and isinstance(text_item.get("text"), str):
                        text_parts.append(text_item["text"])
                text = "\n".join(text_parts)
                session.add(WeixinInbox(account_id=account_id, event_digest=event_digest,
                    payload_encrypted=seal({"text": text[:20000], "sender": credentials["ilink_user_id"],
                                            "context_token": message.get("context_token", "")})))
            if isinstance(response.get("get_updates_buf"), str):
                account.cursor_encrypted = seal({"cursor": response["get_updates_buf"]})
            account.last_poll_at = datetime.now(UTC)
            account.last_error_code = ""
            binding.last_seen_at = datetime.now(UTC)
    with db.session() as session:
        row = _bound(session, account_id)
        if not row or row[0].credentials_encrypted != credentials_before:
            return
        account, binding = row
        item = session.scalar(select(WeixinInbox).where(WeixinInbox.account_id == account_id,
            WeixinInbox.status.in_(["pending", "ready"])).order_by(WeixinInbox.created_at, WeixinInbox.id).limit(1))
        if not item:
            return
        payload = unseal(item.payload_encrypted)
        item_id, event_id, user_id = item.id, f"weixin:{account_id}:{item.event_digest}", binding.user_id
        reply = unseal(item.reply_encrypted).get("text", "")
        if payload.get("sender") != credentials["ilink_user_id"]:
            item.status = "cancelled"
            session.commit()
            return
    if not reply:
        if not payload["text"]:
            reply = "当前支持文字指令。图片、文件和语音请在工作台中上传，再通过文字告诉 AI Server 要做什么。"
        else:
            handler = current_app.extensions.get("fde_weixin_message_handler")
            if not handler:
                raise ControlServiceError("weixin_handler_unavailable", "AI Server 对话服务暂不可用。", 503)
            with _typing_feedback(account_id, credentials_before, credentials, payload):
                reply = handler(user_id, payload["text"], event_id)
            if not isinstance(reply, str) or not reply.strip():
                raise ControlServiceError("weixin_empty_reply", "AI Server 暂未返回内容。", 502)
        with db.session() as session, session.begin():
            item = session.get(WeixinInbox, item_id, with_for_update=True)
            item.reply_encrypted = seal({"text": reply[:20000]})
            if payload.get("text", "").startswith(("确认操作 ", "取消操作 ")):
                item.payload_encrypted = seal({**payload, "text": "[安全确认消息已处理]"})
            item.status = "ready"
    # Re-check revocation and identity after potentially long AI execution.
    with db.session() as session:
        row = _bound(session, account_id)
        if not row or row[0].credentials_encrypted != credentials_before:
            return
    client().call("sendmessage", base_url=credentials["base_url"], token=credentials["bot_token"], payload={"msg": {
        "from_user_id": "", "to_user_id": payload["sender"], "client_id": f"fde-weixin-{item_id}",
        "message_type": 2, "message_state": 2, "context_token": payload.get("context_token", ""),
        "item_list": [{"type": 1, "text_item": {"text": reply[:20000]}}],
    }})
    with db.session() as session, session.begin():
        item = session.get(WeixinInbox, item_id, with_for_update=True)
        item.status = "replied"


def main() -> None:
    from fde_api.app import create_app
    app = create_app()
    stopping = threading.Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: stopping.set())
    logging.basicConfig(level=logging.INFO)
    futures = {}

    def run(account_id):
        with app.app_context():
            process_account(account_id)

    with ThreadPoolExecutor(max_workers=8, thread_name_prefix="weixin") as pool:
        while not stopping.is_set():
            with app.app_context(), db.session() as session:
                ids = session.scalars(select(WeixinAccount.id).join(ChannelBinding).where(
                    ChannelBinding.status == "active", WeixinAccount.credentials_encrypted != "")).all() if _enabled() else []
            futures = {key: future for key, future in futures.items() if not future.done()}
            for account_id in ids:
                if account_id not in futures and len(futures) < 8:
                    futures[account_id] = pool.submit(run, account_id)
            stopping.wait(1)


if __name__ == "__main__":
    main()
