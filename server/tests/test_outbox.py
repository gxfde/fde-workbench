from datetime import UTC, datetime, timedelta

import pytest

from fde_api.jobs.models import BackgroundJob, OutboxEvent
from fde_api.jobs.outbox import dispatch_pending, enqueue_outbox


class _FakeQueue:
    def __init__(self):
        self.enqueued: list[str] = []

    def enqueue(self, job_id: str) -> None:
        self.enqueued.append(job_id)


class _FailingQueue:
    def enqueue(self, job_id: str) -> None:
        raise RuntimeError("redis unavailable")


def test_business_rollback_removes_outbox_event(db_session):
    enqueue_outbox(db_session, "file.scan", "v1", {"version_id": "v1"})
    db_session.rollback()

    assert db_session.query(OutboxEvent).count() == 0


def test_enqueue_outbox_persists_as_pending(db_session):
    enqueue_outbox(db_session, "file.scan", "v1", {"version_id": "v1"})
    db_session.commit()

    event = db_session.query(OutboxEvent).one()
    assert event.status == "pending"
    assert event.attempts == 0
    assert event.available_at is not None


def test_dispatch_pending_marks_dispatched_and_enqueues_job(db_session):
    enqueue_outbox(db_session, "file.scan", "v1", {"version_id": "v1"})
    db_session.commit()
    queue = _FakeQueue()

    result = dispatch_pending(db_session, queue)

    assert result.dispatched == 1
    event = db_session.query(OutboxEvent).one()
    assert event.status == "dispatched"
    assert len(queue.enqueued) == 1
    job = db_session.query(BackgroundJob).one()
    assert job.job_type == "file.scan"
    assert job.target_id == "v1"
    assert queue.enqueued == [job.id]


def test_dispatch_skips_events_not_yet_available(db_session):
    event = enqueue_outbox(db_session, "file.scan", "v1", {"version_id": "v1"})
    event.available_at = datetime.now(UTC) + timedelta(hours=1)
    db_session.commit()

    result = dispatch_pending(db_session, _FakeQueue())

    assert result.dispatched == 0
    assert event.status == "pending"
    assert db_session.query(BackgroundJob).count() == 0


def test_dispatch_rolls_back_when_queue_enqueue_fails(db_session):
    enqueue_outbox(db_session, "file.scan", "v1", {"version_id": "v1"})
    db_session.commit()

    with pytest.raises(RuntimeError, match="redis unavailable"):
        dispatch_pending(db_session, _FailingQueue())

    event = db_session.query(OutboxEvent).one()
    assert event.status == "pending"
    assert db_session.query(BackgroundJob).count() == 0


def test_dispatch_coalesces_same_target_into_one_active_job(db_session):
    enqueue_outbox(db_session, "file.scan", "v1", {"version_id": "v1"})
    enqueue_outbox(db_session, "file.scan", "v1", {"version_id": "v1"})
    db_session.commit()
    queue = _FakeQueue()

    result = dispatch_pending(db_session, queue)

    assert result.dispatched == 2
    assert db_session.query(BackgroundJob).count() == 1
    job = db_session.query(BackgroundJob).one()
    assert queue.enqueued == [job.id, job.id]
