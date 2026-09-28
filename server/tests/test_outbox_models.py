import pytest
from sqlalchemy.exc import DBAPIError, IntegrityError

from fde_api.auth.models import Base
from fde_api.jobs.models import BackgroundJob, OutboxEvent


def test_outbox_models_share_workbench_metadata():
    expected_tables = {"outbox_events", "background_jobs"}
    assert expected_tables <= set(Base.metadata.tables)
    assert OutboxEvent.metadata is Base.metadata
    assert BackgroundJob.metadata is Base.metadata


def test_outbox_event_defaults_to_pending_and_zero_attempts(db_session):
    event = OutboxEvent(
        topic="file.scan", aggregate_id="v1", payload_json={"version_id": "v1"}
    )
    db_session.add(event)
    db_session.commit()

    assert event.status == "pending"
    assert event.attempts == 0
    assert event.available_at is not None


def test_database_rejects_unknown_outbox_status(db_session):
    db_session.add(
        OutboxEvent(
            topic="file.scan",
            aggregate_id="v1",
            payload_json={},
            status="abandoned",
        )
    )

    with pytest.raises(DBAPIError):
        db_session.commit()


def test_database_allows_only_one_active_job_per_type_and_target(db_session):
    first = BackgroundJob(job_type="file.scan", target_id="v1", status="pending")
    db_session.add(first)
    db_session.commit()

    second = BackgroundJob(job_type="file.scan", target_id="v1", status="queued")
    db_session.add(second)

    with pytest.raises(IntegrityError):
        db_session.commit()


def test_database_allows_fresh_job_after_previous_terminal_status(db_session):
    first = BackgroundJob(job_type="file.scan", target_id="v1", status="succeeded")
    db_session.add(first)
    db_session.commit()

    second = BackgroundJob(job_type="file.scan", target_id="v1", status="pending")
    db_session.add(second)
    db_session.commit()

    assert second.id is not None


def test_database_rejects_unknown_job_status(db_session):
    db_session.add(
        BackgroundJob(job_type="file.scan", target_id="v1", status="frozen")
    )

    with pytest.raises(DBAPIError):
        db_session.commit()


def test_database_rejects_negative_job_attempts(db_session):
    db_session.add(
        BackgroundJob(
            job_type="file.scan", target_id="v1", status="pending", attempts=-1
        )
    )

    with pytest.raises(DBAPIError):
        db_session.commit()
