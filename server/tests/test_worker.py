import pytest

from fde_api.jobs.handlers import clear_handlers, register_handler
from fde_api.jobs.models import BackgroundJob
from fde_api.jobs.worker import run_job


def test_run_job_runs_registered_handler_and_succeeds(db_session):
    job = BackgroundJob(job_type="worker_ok", target_id="t-ok", status="pending")
    db_session.add(job)
    db_session.commit()
    called: list[str] = []
    register_handler("worker_ok", lambda current: called.append(current.id))
    try:
        result = run_job(job.id)
    finally:
        clear_handlers()

    db_session.refresh(job)
    assert result == "succeeded"
    assert job.status == "succeeded"
    assert job.locked_until is None
    assert called == [job.id]


def test_worker_replay_does_not_repeat_completed_handler(db_session):
    job = BackgroundJob(job_type="worker_done", target_id="t-done", status="succeeded")
    db_session.add(job)
    db_session.commit()
    called: list[str] = []
    register_handler("worker_done", lambda current: called.append(current.id))
    try:
        result = run_job(job.id)
    finally:
        clear_handlers()

    assert result == "already_terminal"
    assert called == []


def test_run_job_marks_failed_when_handler_raises(db_session):
    job = BackgroundJob(job_type="worker_fail", target_id="t-fail", status="pending")
    db_session.add(job)
    db_session.commit()

    def explode(current):
        raise RuntimeError("boom")

    register_handler("worker_fail", explode)
    try:
        result = run_job(job.id)
    finally:
        clear_handlers()

    db_session.refresh(job)
    assert result == "failed"
    assert job.status == "failed"
    assert "boom" in job.last_error


def test_run_job_returns_not_found_for_missing_job(db_session):
    assert run_job("does-not-exist") == "not_found"


def test_run_job_fails_when_no_handler_is_registered(db_session):
    job = BackgroundJob(job_type="no_handler_job", target_id="t-nh", status="pending")
    db_session.add(job)
    db_session.commit()

    result = run_job(job.id)

    db_session.refresh(job)
    assert result == "no_handler"
    assert job.status == "failed"
