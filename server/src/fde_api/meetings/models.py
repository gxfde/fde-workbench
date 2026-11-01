"""meetings 模型：S1 评审会最小闭环三表（goal-d5，技术实施方案 §2 / PartyMode §6）。

字段来源：PartyMode §6 原文（review_meetings / review_meeting_turns /
review_meeting_minutes）+ 技术文档 §2 决议增量（gate_tier 三档门、
triggered_by_run_id 回链（D7：关联落会议侧）、trigger、min_difficulty）。

溯源红线：纪要 sealed_sha256 封存后不可变（复用 SOW 导出心智）；话轮与
纪要的 source_refs 只指向评审对象的只读引用，评审输入不注入原始客户资料
（PartyMode §5 只读上下文注入）。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from fde_api.workbench.models import Base, TimestampMixin, new_uuid

MEETING_STATUSES = ("live", "paused", "closed")
GATE_TIERS = ("lite", "std", "full")  # UM-1/PM-5：三档门 2/8/12 轮
MEETING_TRIGGERS = ("mandatory", "adhoc", "manual")  # 强制门 / 自主召集 / 人工开会


class ReviewMeeting(Base, TimestampMixin):
    """评审会实例（PartyMode §6 原文 + D7 回链增量）。"""

    __tablename__ = "review_meetings"
    __table_args__ = (
        CheckConstraint(
            "status IN ('live', 'paused', 'closed')",
            name="ck_review_meetings_status",
        ),
        CheckConstraint(
            "gate_tier IN ('lite', 'std', 'full')",
            name="ck_review_meetings_gate_tier",
        ),
        CheckConstraint(
            "trigger IN ('mandatory', 'adhoc', 'manual')",
            name="ck_review_meetings_trigger",
        ),
        CheckConstraint("turn_budget >= 0", name="ck_review_meetings_turn_budget"),
        Index("ix_review_meetings_project_status", "project_id", "status"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False)
    # 模板键（如 "T2-lite"）；模板注册表见 meetings/templates.py（技术文档 §2：
    # 会议模板入 templates 体系或独立种子表实现时定——本轮取常量注册表）
    template_id: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="live", server_default="live")
    # 评审对象只读引用（solution_id/problem refs + sha256 快照指针）；不挂
    # FK——允许指向未落库的引用形态，守卫在封存时复核闭合
    topic_refs: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    turn_budget: Mapped[int] = mapped_column(Integer, nullable=False, default=2, server_default="2")
    hosted_by_user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    # —— 技术文档 §2 决议增量 ——
    # 三档门（UM-1）：lite/std/full
    gate_tier: Mapped[str] = mapped_column(String(16), nullable=False, default="lite", server_default="lite")
    # 召集缘由：强制门（T2-lite 模板）/ 自主召集（T3）/ 人工开会
    trigger: Mapped[str] = mapped_column(String(16), nullable=False, default="manual", server_default="manual")
    # D7：关联落会议侧。软引用不设 FK——run 允许被归档清理，硬 RESTRICT 会
    # 制造清理死锁（沿 agent_runs.retry_of 同款偏离，goal-d3 报告 §二 先例）
    triggered_by_run_id: Mapped[str | None] = mapped_column(String(36))
    # T4 高难度加座阈值（d7 启用，先落列）
    min_difficulty: Mapped[str | None] = mapped_column(String(16))
    # 工具面召集时落召集 agent（人工开会为 NULL）；主人永远是自然人
    convened_by_agent_id: Mapped[str | None] = mapped_column(
        ForeignKey("agent_registry.id", ondelete="RESTRICT")
    )
    # 守卫复核引用闭合失败的降级标注（拒封存标 degraded，技术文档 §6）
    degraded: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")


class ReviewMeetingTurn(Base, TimestampMixin):
    """话轮与发言（PartyMode §6 原文）：agent 发言与创业者插话二选一。"""

    __tablename__ = "review_meeting_turns"
    __table_args__ = (
        CheckConstraint("seq >= 1", name="ck_review_meeting_turns_seq"),
        # 发言者恰好一方：agent 或人（创业者插话/点名角色）
        CheckConstraint(
            "(speaker_agent_id IS NOT NULL) <> (speaker_user_id IS NOT NULL)",
            name="ck_review_meeting_turns_speaker",
        ),
        UniqueConstraint("meeting_id", "seq", name="uq_review_meeting_turns_meeting_seq"),
        Index("ix_review_meeting_turns_meeting", "meeting_id", "seq"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    meeting_id: Mapped[str] = mapped_column(
        ForeignKey("review_meetings.id", ondelete="CASCADE"), nullable=False
    )
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    speaker_agent_id: Mapped[str | None] = mapped_column(
        ForeignKey("agent_registry.id", ondelete="RESTRICT")
    )
    speaker_user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    # 正文 + source_refs + 立场标注（PartyMode §6 原文）
    content: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)


class ReviewMeetingMinutes(Base, TimestampMixin):
    """会议纪要（PartyMode §6 原文）：不可变，复用 SOW 导出心智。

    三段式（共识/分歧/待办）由收敛时守卫复核 source_refs 闭合后一次性写入；
    sealed_sha256 = sha256(meeting_id + 三段规范化 JSON)，封存后不可变。
    """

    __tablename__ = "review_meeting_minutes"
    __table_args__ = (
        CheckConstraint(
            "char_length(sealed_sha256) = 64",
            name="ck_review_meeting_minutes_sealed_len",
        ),
        UniqueConstraint("meeting_id", name="uq_review_meeting_minutes_meeting"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    meeting_id: Mapped[str] = mapped_column(
        ForeignKey("review_meetings.id", ondelete="RESTRICT"), nullable=False
    )
    # 共识点（各带 source_refs）
    consensus: Mapped[list[Any]] = mapped_column(JSON, nullable=False, default=list)
    # 分歧点（双方论点原样保留 + 冲突标注）
    disputes: Mapped[list[Any]] = mapped_column(JSON, nullable=False, default=list)
    # 待办（owner 建议 + 关联待办 id）
    todos: Mapped[list[Any]] = mapped_column(JSON, nullable=False, default=list)
    sealed_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
