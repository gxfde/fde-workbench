"""Encrypted Tencent iLink bindings; business actor remains ChannelBinding.user_id."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from fde_api.auth.models import Base, UTCDateTime
from fde_api.workbench.models import TimestampMixin, new_uuid


class WeixinAccount(Base, TimestampMixin):
    __tablename__ = "weixin_accounts"
    __table_args__ = (UniqueConstraint("binding_id", name="uq_weixin_binding"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    binding_id: Mapped[str] = mapped_column(ForeignKey("channel_bindings.id", ondelete="CASCADE"), nullable=False)
    credentials_encrypted: Mapped[str] = mapped_column(Text, nullable=False, default="")
    login_encrypted: Mapped[str] = mapped_column(Text, nullable=False, default="")
    login_status: Mapped[str] = mapped_column(String(32), nullable=False, default="idle")
    login_expires_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    cursor_encrypted: Mapped[str] = mapped_column(Text, nullable=False, default="")
    last_poll_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    last_error_code: Mapped[str] = mapped_column(String(64), nullable=False, default="")


class WeixinInbox(Base, TimestampMixin):
    __tablename__ = "weixin_inbox"
    __table_args__ = (
        UniqueConstraint("account_id", "event_digest", name="uq_weixin_inbox_event"),
        Index("ix_weixin_inbox_pending", "account_id", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    account_id: Mapped[str] = mapped_column(ForeignKey("weixin_accounts.id", ondelete="CASCADE"), nullable=False)
    event_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    payload_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    reply_encrypted: Mapped[str] = mapped_column(Text, nullable=False, default="")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
