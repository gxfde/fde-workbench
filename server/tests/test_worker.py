
from datetime import UTC, datetime, timedelta

from fde_api.extensions import db
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


# --- V3 T-J2（域 14）：handler 自动重试 -------------------------------------


def _register_flaky(topic: str, fail_times: int, state: dict):
    """前 fail_times 次抛错，之后成功（重试恢复面）。"""
    counter = {"n": 0}

    def handler(current):
        counter["n"] += 1
        state["attempts"] = counter["n"]
        if counter["n"] <= fail_times:
            raise RuntimeError(f"transient-{counter['n']}")

    register_handler(topic, handler)
    return counter


def test_recoverable_failure_schedules_backoff_retry(db_session):
    """可恢复类型 handler 抛错 → 退避重投（queued+未来 available_at），不再首败即终。"""
    job = _job_from_outbox(db_session, "file.scan", "t-retry")

    def explode(current):
        raise RuntimeError("boom")

    clear_handlers()
    register_handler("file.scan", explode)
    try:
        result = run_job(job.id)
    finally:
        clear_handlers()

    db_session.refresh(job)
    now = datetime.now(UTC)
    assert result == "retrying"
    assert job.status == "queued"
    assert job.attempts == 1
    assert job.locked_until is None
    assert job.locked_by is None
    assert "boom" in job.last_error
    assert job.available_at > now
    assert job.available_at <= now + timedelta(seconds=65)


def test_retry_keeps_outbox_events_dispatched(db_session):
    """T-J1 红线：中间每一次重试都不得翻转 outbox——事件保持 dispatched。"""
    job = _job_from_outbox(db_session, "file.scan", "t-retry-ob")

    def explode(current):
        raise RuntimeError("boom")

    clear_handlers()
    register_handler("file.scan", explode)
    try:
        result = run_job(job.id)
    finally:
        clear_handlers()

    event = db_session.query(OutboxEvent).one()
    db_session.refresh(event)
    assert result == "retrying"
    assert event.status == "dispatched"


def test_exhausted_retries_settle_failed_and_close_outbox(db_session):
    """attempts 耗尽才终失败；outbox failed 收口只发生在最终失败分支。"""
    job = _job_from_outbox(db_session, "file.scan", "t-exh")
    job.max_attempts = 2
    db_session.commit()

    def explode(current):
        raise RuntimeError(f"boom-{current.attempts}")

    clear_handlers()
    register_handler("file.scan", explode)
    try:
        first = run_job(job.id)
        event = db_session.query(OutboxEvent).one()
        db_session.refresh(event)
        assert first == "retrying"
        assert event.status == "dispatched"  # 红线：首败未终，事件不收口
        # 模拟退避到期（due 重投后的第二次认领）
        job.available_at = datetime.now(UTC) - timedelta(seconds=1)
        db_session.commit()
        second = run_job(job.id)
    finally:
        clear_handlers()

    event = db_session.query(OutboxEvent).one()
    db_session.refresh(job)
    db_session.refresh(event)
    assert second == "failed"
    assert job.status == "failed"
    assert job.attempts == 2
    assert "boom-2" in job.last_error
    assert event.status == "failed"
    assert "boom-2" in event.last_error


def test_success_after_retry_closes_outbox_completed(db_session):
    """瞬时故障恢复全链：失败退避 → 重跑成功 → outbox completed。"""
    job = _job_from_outbox(db_session, "file.scan", "t-flaky")
    state: dict = {}
    clear_handlers()
    _register_flaky("file.scan", fail_times=1, state=state)
    try:
        first = run_job(job.id)
        assert first == "retrying"
        job.available_at = datetime.now(UTC) - timedelta(seconds=1)
        db_session.commit()
        second = run_job(job.id)
    finally:
        clear_handlers()

    event = db_session.query(OutboxEvent).one()
    db_session.refresh(job)
    db_session.refresh(event)
    assert state["attempts"] == 2
    assert second == "succeeded"
    assert job.status == "succeeded"
    assert event.status == "completed"


def test_non_recoverable_failure_fails_immediately(db_session):
    """automation.execute 外副作用类型维持首败即 failed（不强杀语义的镜像）。"""
    job = BackgroundJob(
        job_type="automation.execute", target_id="t-auto", status="pending"
    )
    db_session.add(job)
    db_session.commit()

    def explode(current):
        raise RuntimeError("side effect failed")

    clear_handlers()
    register_handler("automation.execute", explode)
    try:
        result = run_job(job.id)
    finally:
        clear_handlers()

    db_session.refresh(job)
    assert result == "failed"
    assert job.status == "failed"
    assert job.attempts == 1


def test_not_due_queued_job_is_refused(db_session):
    """重复投递的早到条目被认领守卫丢回：不烧 attempts，行保持等待。"""
    job = BackgroundJob(
        job_type="file.scan",
        target_id="t-notdue",
        status="queued",
        available_at=datetime.now(UTC) + timedelta(seconds=30),
    )
    db_session.add(job)
    db_session.commit()

    result = run_job(job.id)

    db_session.refresh(job)
    assert result == "not_due"
    assert job.status == "queued"
    assert job.attempts == 0


def test_late_failure_after_cancel_does_not_overwrite(db_session):
    """取消后的迟到失败回写被终态守卫拒绝——cancelled 不被 handler 结果覆盖。"""

    def handler(current):
        # 模拟 admin 取消（同 update 路径）：终态落库 + 租约清空
        session = db.session()
        row = session.get(BackgroundJob, current.id)
        row.status = "cancelled"
        row.locked_until = None
        row.locked_by = None
        row.last_error = "cancelled_by_admin"
        session.commit()
        session.close()
        raise RuntimeError("late failure")

    job = BackgroundJob(job_type="file.scan", target_id="t-late", status="pending")
    db_session.add(job)
    db_session.commit()
    clear_handlers()
    register_handler("file.scan", handler)
    try:
        result = run_job(job.id)
    finally:
        clear_handlers()

    db_session.refresh(job)
    assert result == "settled_elsewhere"
    assert job.status == "cancelled"
    assert job.last_error == "cancelled_by_admin"
