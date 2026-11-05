from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    Computed,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from fde_api.auth.models import UTCDateTime, UTC_TIMESTAMP_SQL
from fde_api.workbench.models import Base, TimestampMixin, VersionedMixin, new_uuid

OUTBOX_STATUSES = ("pending", "dispatched", "completed", "failed")
BACKGROUND_JOB_STATUSES = (
    "pending",
    "queued",
    "running",
    "succeeded",
    "failed",
    "cancelled",
)
# V3 T-J2（域 14）：cancelled 是独立终态——幂等取消要能区分「已取消」
# （200 cancelled=false）与「跑完/失败」（409 already_terminal），不能靠
# failed+last_error 前缀猜。槽位语义与 succeeded/failed 一致（释放
# (job_type, target_id)，active_key 生成列对一切非活跃态本就取 NULL，
# 故迁移只需置换 CHECK 约束，无需重建生成列）。
TERMINAL_JOB_STATUSES = ("succeeded", "failed", "cancelled")

# Terminal statuses free the (job_type, target_id) slot for a fresh active job.
# v0.2 (PG 迁移): 原用 CONCAT(job_type, ':', target_id)。PG 的 concat() 是 STABLE
# 而非 IMMUTABLE，而 PG 要求生成列（GENERATED ... AS ... STORED）的表达式必须
# immutable —— 迁移会直接报 "generation expression is not immutable"。
# 改用 || 运算符拼接：MySQL 与 PG 下 || 均为 immutable（MySQL 需非 PIPES_AS_CONCAT
# 模式；SQLAlchemy 的 concat 运算符在两个方言下都翻译为各自的可变表达式）。
_ACTIVE_JOB_SQL_EXPR = (
    "CASE WHEN status IN ('pending', 'queued', 'running') "
    "THEN job_type || ':' || target_id ELSE NULL END"
)


class OutboxEvent(Base, TimestampMixin):
    """A transactional change record dispatched to the background worker."""

    __tablename__ = "outbox_events"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'dispatched', 'completed', 'failed')",
            name="ck_outbox_events_status",
        ),
        Index("ix_outbox_events_status_available", "status", "available_at"),
        Index("ix_outbox_events_aggregate_id", "aggregate_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    topic: Mapped[str] = mapped_column(String(80), nullable=False)
    aggregate_id: Mapped[str] = mapped_column(String(36), nullable=False)
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="pending", server_default="pending"
    )
    attempts: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    available_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), nullable=False, server_default=UTC_TIMESTAMP_SQL
    )
    last_error: Mapped[str] = mapped_column(Text, nullable=False, default="")


class BackgroundJob(Base, TimestampMixin, VersionedMixin):
    """A queue entry with lease semantics and a single-active-per-target guard."""

    __tablename__ = "background_jobs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'queued', 'running', 'succeeded', 'failed', 'cancelled')",
            name="ck_background_jobs_status",
        ),
        CheckConstraint("attempts >= 0", name="ck_background_jobs_attempts"),
        UniqueConstraint("active_key", name="uq_background_jobs_active_key"),
        Index("ix_background_jobs_status_available", "status", "available_at"),
        Index("ix_background_jobs_job_type_target", "job_type", "target_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    job_type: Mapped[str] = mapped_column(String(80), nullable=False)
    target_id: Mapped[str] = mapped_column(String(36), nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="pending", server_default="pending"
    )
    attempts: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    max_attempts: Mapped[int] = mapped_column(
        Integer, nullable=False, default=5, server_default=text("5")
    )
    available_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), nullable=False, server_default=UTC_TIMESTAMP_SQL
    )
    locked_until: Mapped[datetime | None] = mapped_column(UTCDateTime())
    locked_by: Mapped[str | None] = mapped_column(String(64))
    last_error: Mapped[str] = mapped_column(Text, nullable=False, default="")
    active_key: Mapped[str | None] = mapped_column(
        String(150), Computed(_ACTIVE_JOB_SQL_EXPR, persisted=True), nullable=True
    )
