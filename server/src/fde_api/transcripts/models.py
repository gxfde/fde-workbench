"""transcripts 模型：草稿区（transcript_drafts）+ 访谈纪要正式库（interview_minutes）。

物理隔离三件（T-A9 验收面）：
1. 两张独立表——草稿区与正式库不共表；
2. 草稿独立文件根（Settings.transcript_draft_root，与 .fde-storage 上传存储不共根）；
3. 正式库**零外键引用草稿行**——``interview_minutes.draft_id`` 是纯字符串指针
   （B#6 不变量「引用方永不复制真相，只持指针」；无 FK 无级联，``test_
   transcript_drafts`` 用 metadata 扫描钉死「草稿不可被正式库引用」）。

草稿行终态（promoted/expired/discarded）为墓碑：content/sha/复核条目整组置空，
只留指针与时间戳供 T+7 合规对账；正文本体随清理语义一并抹除。

T-A2 代号化：content/title/确认人文本均在 service 层先过 ``redact_text_detailed``
再落库（不因「草稿」或「人工整理」豁免）；草稿行携带复核条目（与 #160
``guidance.redaction_review`` 同形状：name/occurrences/matched_dict）供人工校对，
墓碑时一并抹除；正式库只留命中计数（不留疑似名元数据）。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from fde_api.auth.models import UTCDateTime
from fde_api.workbench.models import Base, TimestampMixin, new_uuid

DRAFT_STATUSES = ("draft", "promoted", "expired", "discarded")
SOURCE_KINDS = ("manual", "asr")
CONFIRMATION_METHODS = ("verbal", "written", "meeting")


class TranscriptDraft(Base, TimestampMixin):
    """转写草稿行（T+7 临时区）：状态机 draft → promoted | expired | discarded。"""

    __tablename__ = "transcript_drafts"
    __table_args__ = (
        CheckConstraint(
            "status IN ('draft', 'promoted', 'expired', 'discarded')",
            name="ck_transcript_drafts_status",
        ),
        CheckConstraint(
            "source_kind IN ('manual', 'asr')",
            name="ck_transcript_drafts_source_kind",
        ),
        CheckConstraint(
            "client_confirmation_method IS NULL OR client_confirmation_method IN ('verbal', 'written', 'meeting')",
            name="ck_transcript_drafts_confirmation_method",
        ),
        # asr 来源必须标注引擎；manual 来源不标注（两者恰好一一对应）
        CheckConstraint(
            "(source_kind = 'manual') = (engine IS NULL)",
            name="ck_transcript_drafts_engine_presence",
        ),
        # 活动草稿必有正文与指纹；墓碑（非 draft）必无三者
        CheckConstraint(
            "(status <> 'draft') OR (content IS NOT NULL AND content_sha256 IS NOT NULL AND redaction_entries IS NOT NULL)",
            name="ck_transcript_drafts_active_content",
        ),
        CheckConstraint(
            "(status = 'draft') OR (content IS NULL AND content_sha256 IS NULL AND redaction_entries IS NULL)",
            name="ck_transcript_drafts_tombstone_content",
        ),
        # 晋升墓碑必须带客户确认三要素 + 晋升指针（T-A9 验收：无确认无法进正式库）
        CheckConstraint(
            "(status <> 'promoted') OR ("
            "client_confirmed_by IS NOT NULL AND client_confirmed_at IS NOT NULL "
            "AND client_confirmation_method IS NOT NULL AND promoted_ref IS NOT NULL)",
            name="ck_transcript_drafts_promoted_triple",
        ),
        CheckConstraint("char_length(content_sha256) = 64", name="ck_transcript_drafts_sha_len"),
        Index("ix_transcript_drafts_project_status", "project_id", "status"),
        Index("ix_transcript_drafts_purge_due", "status", "expires_at"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False)
    created_by_user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    # 代号化后的标题/正文（service 层先过 T-A2 管线再落库；墓碑置空）
    title: Mapped[str | None] = mapped_column(String(200))
    content: Mapped[str | None] = mapped_column(Text)
    content_sha256: Mapped[str | None] = mapped_column(String(64))
    # 复核条目（#160 guidance.redaction_review 同形状）；墓碑置空。
    # none_as_null：None 必须落 SQL NULL（墓碑 CHECK 用 IS NULL 判定——JSON
    # 默认把 None 编码为 json 'null' 字面量，会撞 ck_transcript_drafts_tombstone_content）
    redaction_entries: Mapped[list[Any] | None] = mapped_column(JSON(none_as_null=True))
    source_kind: Mapped[str] = mapped_column(String(16), nullable=False, default="manual", server_default="manual")
    # asr 来源的引擎标注（如 faster-whisper:base）；引擎不进平台依赖，纯来源标注
    engine: Mapped[str | None] = mapped_column(String(60))
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="draft", server_default="draft")
    # —— 客户确认三要素（晋升时必填；确认人是客户侧人名的代号化文本，非平台用户）——
    client_confirmed_by: Mapped[str | None] = mapped_column(String(160))
    client_confirmed_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    client_confirmation_method: Mapped[str | None] = mapped_column(String(16))
    # 晋升指针（如 interview_minutes:<id>）；B#6 纪律：只持指针
    promoted_ref: Mapped[str | None] = mapped_column(String(80))
    # T+7 清理到期（service 层按 created_at + Settings.transcript_draft_retention_days 写入）
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    cleaned_at: Mapped[datetime | None] = mapped_column(UTCDateTime())


class InterviewMinutes(Base, TimestampMixin):
    """访谈纪要（正式库）：人工整理 + 客户确认三要素齐备后的唯一正式形态。

    draft_id 为纯字符串指针（无 FK）：正式库引用的是「晋升指针」，不引用草稿
    行本体（物理隔离验收的机械面——metadata 扫描钉死零外键指向 transcript_drafts）。
    """

    __tablename__ = "interview_minutes"
    __table_args__ = (
        CheckConstraint(
            "client_confirmation_method IN ('verbal', 'written', 'meeting')",
            name="ck_interview_minutes_confirmation_method",
        ),
        CheckConstraint("char_length(content_sha256) = 64", name="ck_interview_minutes_sha_len"),
        # 一次晋升至多一条纪要（草稿指针为空=纯手工直录，允许多条）
        UniqueConstraint("draft_id", name="uq_interview_minutes_draft"),
        Index("ix_interview_minutes_project_created", "project_id", "created_at"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False)
    created_by_user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    draft_id: Mapped[str | None] = mapped_column(String(36))
    # 代号化后的纪要标题/正文（人工整理稿同样过 T-A2 管线）
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    # 正式库只留命中计数（疑似名元数据不进正式库）
    redaction_hits: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    client_confirmed_by: Mapped[str] = mapped_column(String(160), nullable=False)
    client_confirmed_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    client_confirmation_method: Mapped[str] = mapped_column(String(16), nullable=False)
