"""Transactional outbox: enqueue change events in the business transaction."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from fde_api.jobs.models import OutboxEvent


def utcnow() -> datetime:
    return datetime.now(UTC)


# MySQL DATETIME stores second precision and rounds fractional seconds up, so a
# freshly created event can carry an available_at one second in the future.
# Allow that rounding window so events are dispatchable immediately.
AVAILABLE_AT_GRACE = timedelta(seconds=1)


@dataclass(frozen=True, slots=True)
class DispatchResult:
    dispatched: int


def enqueue_outbox(
    session: Session, topic: str, aggregate_id: str, payload: dict
) -> OutboxEvent:
    """Insert an outbox event in the caller's transaction.

    The event is flushed but never committed here, so it shares the
    business write's fate: a business rollback removes it too.
    """
    event = OutboxEvent(
        topic=topic,
        aggregate_id=aggregate_id,
        payload_json=payload,
        status="pending",
        attempts=0,
        available_at=utcnow(),
    )
    session.add(event)
    session.flush()
    return event


def dispatch_pending(
    session: Session, queue: object, limit: int = 100
) -> DispatchResult:
    """Claim the oldest due events and enqueue one job per target.

    A leading read forces a fresh consistent snapshot so the caller's already
    committed events are always visible under MySQL REPEATABLE READ, then a
    conditional UPDATE claims each event so concurrent workers cannot
    double-dispatch it. If any enqueue fails the batch rolls back and events
    stay pending.
    """
    from fde_api.jobs.queue import ensure_background_job

    session.execute(select(OutboxEvent.id).limit(1))
    events = session.scalars(
        select(OutboxEvent)
        .where(
            OutboxEvent.status == "pending",
            OutboxEvent.available_at <= utcnow() + AVAILABLE_AT_GRACE,
        )
        .order_by(OutboxEvent.available_at, OutboxEvent.id)
        .limit(limit)
    ).all()

    dispatched = 0
    try:
        for event in events:
            claimed = session.execute(
                update(OutboxEvent)
                .where(OutboxEvent.id == event.id, OutboxEvent.status == "pending")
                .values(status="dispatched")
            )
            if claimed.rowcount != 1:
                continue
            job = ensure_background_job(session, event.topic, event.aggregate_id)
            queue.enqueue(job.id)  # type: ignore[attr-defined]
            dispatched += 1
        session.commit()
    except Exception:
        session.rollback()
        raise
    return DispatchResult(dispatched=dispatched)
