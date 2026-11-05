
from fde_api.jobs.handlers import clear_handlers, register_handler
from fde_api.jobs.models import BackgroundJob, OutboxEvent
from fde_api.jobs.outbox import dispatch_pending, enqueue_outbox
from fde_api.jobs.worker import run_job


class _Queue:
    def __init__(self):
        self.enqueued: list[str] = []

    def enqueue(self, job_id: str) -> None:
        self.enqueued.append(job_id)


def _job_from_outbox(db_session, topic: str, target: str) -> BackgroundJob:
    """走真实派发链造 job：enqueue → dispatch（outbox 行随派发改 dispatched）。"""
    enqueue_outbox(db_session, topic, target, {"target": target})
    db_session.commit()
    dispatch_pending(db_session, _Queue())
    return db_session.query(BackgroundJob).one()


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


def test_job_success_closes_outbox_events(db_session):
    """V3 T-J1（WB-DEF-9）：job 成功终态与派生 outbox 事件同事务收口。"""
    job = _job_from_outbox(db_session, "worker_ok_ob", "t-ob")

    register_handler("worker_ok_ob", lambda current: None)
    try:
        result = run_job(job.id)
    finally:
        clear_handlers()

    event = db_session.query(OutboxEvent).one()
    db_session.refresh(event)
    assert result == "succeeded"
    assert event.status == "completed"
    assert event.last_error == ""


def test_job_failure_marks_outbox_failed_with_error(db_session):
    """V3 T-J1：失败终态把错误摘要落 outbox（failed + last_error）。"""

    def explode(current):
        raise RuntimeError("boom")

    job = _job_from_outbox(db_session, "worker_fail_ob", "t-obf")
    register_handler("worker_fail_ob", explode)
    try:
        result = run_job(job.id)
    finally:
        clear_handlers()

    event = db_session.query(OutboxEvent).one()
    db_session.refresh(event)
    assert result == "failed"
    assert event.status == "failed"
    assert "boom" in event.last_error


def test_no_handler_job_closes_outbox_events(db_session):
    """V3 T-J1：no_handler 终失败在 claim 事务内同步收口派生 outbox 事件。"""
    job = _job_from_outbox(db_session, "never_registered_ob", "t-nh-ob")

    result = run_job(job.id)

    event = db_session.query(OutboxEvent).one()
    db_session.refresh(event)
    assert result == "no_handler"
    assert event.status == "failed"
    assert event.last_error == "no_handler_registered"
