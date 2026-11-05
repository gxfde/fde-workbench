"""Reconciliation of background jobs whose worker died.

The incident this pins down (2026-10-30): a worker was killed while holding
an AI chat job. The redis entry died with the pop, the outbox event was
already ``dispatched`` (the dispatcher never looks at it again), and the job
stayed ``running`` forever — the only cure was a hand-written
``RPUSH fde-jobs <id>``. The sweep in ``jobs/reconcile.py`` gives such jobs
an owner again, and closes out the business row so the UI stops polling.
"""

from __future__ import annotations

import time
from datetime import UTC, date, datetime, timedelta
from uuid import uuid4

from sqlalchemy import select

from fde_api.auth.models import User
from fde_api.control.chat import AIChatTurn, AIConversation
from fde_api.extensions import db
from fde_api.files.models import ProjectFile, ProjectFileVersion
from fde_api.guidance.models import ProjectGuidanceAnalysis
from fde_api.jobs.handlers import clear_handlers, register_handler
from fde_api.jobs.models import BackgroundJob
from fde_api.jobs.reconcile import ORPHAN_GRACE_SECONDS, reconcile_jobs
from fde_api.jobs.worker import run_job
from fde_api.workbench.models import Project


class _FakeQueue:
    def __init__(self):
        self.enqueued: list[str] = []

    def enqueue(self, job_id: str) -> None:
        self.enqueued.append(job_id)


def _past(**kwargs) -> datetime:
    return datetime.now(UTC) - timedelta(**kwargs)


def _future(**kwargs) -> datetime:
    return datetime.now(UTC) + timedelta(**kwargs)


def _job(db_session, **kwargs) -> BackgroundJob:
    job = BackgroundJob(
        job_type=kwargs.pop("job_type", "project.presurvey.analyze"),
        target_id=kwargs.pop("target_id", "target-1"),
        status=kwargs.pop("status", "pending"),
        **kwargs,
    )
    db_session.add(job)
    db_session.commit()
    return job


def _seed_guidance_analysis(db_session) -> tuple[ProjectGuidanceAnalysis, BackgroundJob]:
    """A guidance analysis stuck in `analyzing` plus its job."""
    leader = User(
        username=f"reconcile.lead.{uuid4().hex}",
        display_name="对账负责人",
        role="project_lead",
        password_hash="x",
        must_change_password=False,
        is_active=True,
    )
    project_id, file_id, version_id = uuid4().hex, uuid4().hex, uuid4().hex
    project = Project(
        id=project_id,
        project_code=f"FDE-RECON-{uuid4().hex[:8]}",
        name="对账项目",
        enterprise_code="星河制造·制造·苏州",
        leader=leader,
        template_snapshot={},
        planned_start_date=date(2026, 8, 22),
    )
    project_file = ProjectFile(
        id=file_id, project=project, category="attachment",
        display_name="预调研表", description="", created_by=leader,
    )
    version = ProjectFileVersion(
        id=version_id, project_file=project_file, version_number=1,
        source="upload", original_filename="预调研表.docx",
        safe_filename="presurvey.docx", extension="docx", mime_type="",
        bucket="local", storage_key=f"projects/{project_id}/presurvey/presurvey.docx",
        size_bytes=0, etag="", sha256="", uploaded_by=leader,
        status="available", scan_status="clean", preview_status="none",
    )
    analysis = ProjectGuidanceAnalysis(
        id=uuid4().hex, project_id=project_id, version_number=1,
        source_file_id=file_id, source_file_version_id=version_id,
        source_filename="预调研表.docx", source_sha256="",
        status="draft", analysis_state="analyzing", created_by_user_id=leader.id,
    )
    job = BackgroundJob(
        job_type="project.presurvey.analyze", target_id=analysis.id,
        status="running", locked_until=_past(minutes=1),
    )
    db_session.add_all([leader, project, project_file, version])
    db_session.flush()
    db_session.add_all([analysis, job])
    db_session.commit()
    return analysis, job


def _seed_chat_turn(db_session) -> tuple[AIChatTurn, BackgroundJob]:
    """A chat turn stuck in `running` plus its job."""
    user = User(
        username=f"reconcile.user.{uuid4().hex}",
        display_name="对账用户",
        role="project_lead",
        password_hash="x",
        must_change_password=False,
        is_active=True,
    )
    conversation = AIConversation(user_id=user.id, title="对账会话")
    db_session.add_all([user, conversation])
    db_session.flush()
    turn = AIChatTurn(
        id=uuid4().hex, conversation_id=conversation.id, prompt="你好",
        response="", status="running",
    )
    job = BackgroundJob(
        job_type="ai.chat", target_id=turn.id, status="running",
        locked_until=_past(minutes=1),
    )
    db_session.add_all([turn, job])
    db_session.commit()
    return turn, job


# --- the sweep -------------------------------------------------------------


def test_expired_lease_job_is_requeued(db_session):
    """A running job whose lease expired lost its worker: give it one back."""
    job = _job(db_session, status="running", locked_until=_past(minutes=1))
    queue = _FakeQueue()

    result = reconcile_jobs(db_session, queue)

    db_session.refresh(job)
    assert result.requeued == 1
    assert result.failed == 0
    assert job.status == "queued"
    assert job.locked_until is None
    assert job.locked_by is None
    assert queue.enqueued == [job.id]


def test_live_leased_job_is_left_alone(db_session):
    """A job under a live lease belongs to a running worker."""
    job = _job(db_session, status="running", locked_until=_future(minutes=5))
    queue = _FakeQueue()

    result = reconcile_jobs(db_session, queue)

    db_session.refresh(job)
    assert result.requeued == 0
    assert result.failed == 0
    assert job.status == "running"
    assert queue.enqueued == []


def test_job_locked_by_a_live_worker_is_skipped(db_session):
    """The row lock of a running worker keeps the sweep away from it."""
    job = _job(db_session, status="running", locked_until=_past(minutes=1))
    holder = db.session()
    try:
        holder.execute(
            select(BackgroundJob).where(BackgroundJob.id == job.id).with_for_update()
        )
        result = reconcile_jobs(db_session, _FakeQueue())
    finally:
        holder.rollback()
        holder.close()

    db_session.refresh(job)
    assert result.scanned == 0
    assert job.status == "running"


def test_orphaned_pending_job_is_requeued(db_session):
    """Nobody ever picked it up (the queue entry was lost): re-queue it."""
    job = _job(
        db_session,
        status="pending",
        available_at=_past(seconds=ORPHAN_GRACE_SECONDS + 60),
    )
    queue = _FakeQueue()

    result = reconcile_jobs(db_session, queue)

    db_session.refresh(job)
    assert result.requeued == 1
    assert job.status == "queued"
    assert queue.enqueued == [job.id]


def test_recent_pending_job_is_left_alone(db_session):
    """A job that was just queued is not an orphan yet."""
    job = _job(db_session, status="pending", available_at=datetime.now(UTC))
    queue = _FakeQueue()

    result = reconcile_jobs(db_session, queue)

    db_session.refresh(job)
    assert result.requeued == 0
    assert job.status == "pending"
    assert queue.enqueued == []


def test_requeued_job_is_not_swept_again_immediately(db_session):
    """The re-queue resets the grace window — no hot loop."""
    job = _job(
        db_session,
        status="running",
        locked_until=_past(minutes=1),
        available_at=_past(seconds=ORPHAN_GRACE_SECONDS + 60),
    )
    queue = _FakeQueue()

    reconcile_jobs(db_session, queue)
    second = reconcile_jobs(db_session, queue)

    db_session.refresh(job)
    assert second.requeued == 0
    assert queue.enqueued == [job.id]


def test_exhausted_job_is_failed_not_requeued(db_session):
    """Out of attempts: fail it instead of looping forever."""
    job = _job(
        db_session,
        status="running",
        locked_until=_past(minutes=1),
        attempts=5,
        max_attempts=5,
    )
    queue = _FakeQueue()

    result = reconcile_jobs(db_session, queue)

    db_session.refresh(job)
    assert result.failed == 1
    assert result.requeued == 0
    assert job.status == "failed"
    assert "worker_lost" in job.last_error
    assert queue.enqueued == []


def test_non_recoverable_job_type_is_failed(db_session):
    """automation.execute has outside-world side effects: never re-run it."""
    job = _job(
        db_session,
        job_type="automation.execute",
        status="running",
        locked_until=_past(minutes=1),
    )
    queue = _FakeQueue()

    result = reconcile_jobs(db_session, queue)

    db_session.refresh(job)
    assert result.failed == 1
    assert job.status == "failed"
    assert queue.enqueued == []


# --- V3 T-J2（域 14）：退避重试的 due 补投面 --------------------------------


def test_due_retry_job_is_reenqueued_without_row_change(db_session):
    """退避到期的重试行补投 redis：行不动（queued/available_at 保持），
    重置等待是 run_job 重试分支的职责，补投只递条目。"""
    job = _job(
        db_session,
        job_type="file.scan",
        status="queued",
        available_at=_past(seconds=60),
    )
    queue = _FakeQueue()

    result = reconcile_jobs(db_session, queue)

    db_session.refresh(job)
    assert result.due_enqueued == 1
    assert result.requeued == 0
    assert result.failed == 0
    assert job.status == "queued"
    assert queue.enqueued == [job.id]


def test_backoff_waiting_job_is_left_alone(db_session):
    """退避等待中（available_at 未来）：不是孤儿、不到 due，零动作。"""
    job = _job(
        db_session,
        job_type="file.scan",
        status="queued",
        available_at=_future(seconds=30),
    )
    queue = _FakeQueue()

    result = reconcile_jobs(db_session, queue)

    db_session.refresh(job)
    assert result.scanned == 0
    assert result.due_enqueued == 0
    assert job.status == "queued"
    assert queue.enqueued == []


def test_cancelled_job_is_never_swept(db_session):
    """域 14 验收：取消后不再被 reconcile 重排或复活（终态不在候选集）。"""
    job = _job(
        db_session,
        job_type="file.scan",
        status="cancelled",
        available_at=_past(seconds=ORPHAN_GRACE_SECONDS + 60),
    )
    queue = _FakeQueue()

    result = reconcile_jobs(db_session, queue)

    db_session.refresh(job)
    assert result.scanned == 0
    assert result.requeued == 0
    assert result.failed == 0
    assert job.status == "cancelled"
    assert queue.enqueued == []


def test_due_sweep_delivers_retry_job_to_completion(db_session):
    """完整闭环：handler 瞬时失败退避 → due 补投 → 二跑成功。"""
    job = _job(db_session, job_type="file.scan", status="pending")
    calls: list[int] = []

    def flaky(current):
        calls.append(current.attempts)
        if len(calls) == 1:
            raise RuntimeError("transient")

    register_handler("file.scan", flaky)
    queue = _FakeQueue()
    try:
        assert run_job(job.id) == "retrying"
        # 模拟退避到期（worker 循环里由 reconcile 的 due 面补投）
        job.available_at = _past(seconds=60)
        db_session.commit()
        result = reconcile_jobs(db_session, queue)
        assert result.due_enqueued == 1
        outcome = run_job(queue.enqueued[0])
    finally:
        clear_handlers()

    db_session.refresh(job)
    assert outcome == "succeeded"
    assert calls == [1, 2]
    assert job.status == "succeeded"


# --- business rows ---------------------------------------------------------


def test_guidance_analysis_is_closed_out_when_the_job_is_given_up_on(db_session):
    """The analysis row is what the UI polls: it must leave the running state."""
    analysis, job = _seed_guidance_analysis(db_session)
    job.attempts = job.max_attempts
    db_session.commit()

    result = reconcile_jobs(db_session, _FakeQueue())

    db_session.refresh(analysis)
    assert result.failed == 1
    assert analysis.analysis_state == "failed"
    assert analysis.failure_code == "analysis_worker_lost"
    assert "重新发起分析" in analysis.failure_message


def test_ready_analysis_is_not_touched_by_the_sweep(db_session):
    """A finished analysis keeps its result — the sweep must not overwrite it."""
    analysis, job = _seed_guidance_analysis(db_session)
    analysis.analysis_state = "ready"
    job.attempts = job.max_attempts
    db_session.commit()

    reconcile_jobs(db_session, _FakeQueue())

    db_session.refresh(analysis)
    assert analysis.analysis_state == "ready"
    assert analysis.failure_code == ""


def test_chat_turn_is_closed_out_when_the_job_is_given_up_on(db_session):
    """A turn left running blocks the whole conversation (chat_busy)."""
    turn, job = _seed_chat_turn(db_session)
    job.attempts = job.max_attempts
    db_session.commit()

    result = reconcile_jobs(db_session, _FakeQueue())

    db_session.refresh(turn)
    assert result.failed == 1
    assert turn.status == "failed"
    assert "中断" in turn.error_message


def test_completed_chat_turn_is_not_touched_by_the_sweep(db_session):
    turn, job = _seed_chat_turn(db_session)
    turn.status = "completed"
    turn.response = "答完了"
    job.attempts = job.max_attempts
    db_session.commit()

    reconcile_jobs(db_session, _FakeQueue())

    db_session.refresh(turn)
    assert turn.status == "completed"
    assert turn.response == "答完了"


# --- end to end ------------------------------------------------------------


def test_orphaned_job_runs_after_the_sweep(db_session):
    """The whole point: a job that lost its worker still gets done.

    The type has to be one of the declared recoverable ones — the sweep never
    guesses.
    """
    job = _job(
        db_session,
        job_type="project.presurvey.analyze",
        status="pending",
        available_at=_past(seconds=ORPHAN_GRACE_SECONDS + 60),
    )
    called: list[str] = []
    register_handler(
        "project.presurvey.analyze", lambda current: called.append(current.id)
    )
    queue = _FakeQueue()
    try:
        reconcile_jobs(db_session, queue)
        assert queue.enqueued == [job.id]
        outcome = run_job(queue.enqueued[0])
    finally:
        clear_handlers()

    db_session.refresh(job)
    assert outcome == "succeeded"
    assert called == [job.id]
    assert job.status == "succeeded"


def test_run_job_commits_the_running_claim(db_session):
    """The claim has to be durable: the sweep can only see a running job."""
    seen: list[tuple[str, object]] = []

    def handler(current):
        observer = db.session()
        try:
            row = observer.get(BackgroundJob, current.id)
            seen.append((row.status, row.locked_until))
        finally:
            observer.close()

    job = _job(db_session, job_type="worker_visible", status="pending")
    register_handler("worker_visible", handler)
    try:
        outcome = run_job(job.id)
    finally:
        clear_handlers()

    assert outcome == "succeeded"
    assert len(seen) == 1
    status, locked_until = seen[0]
    assert status == "running"
    assert locked_until is not None and locked_until > datetime.now(UTC)


def test_lease_is_renewed_while_the_handler_runs(db_session, monkeypatch):
    """A live job must never look expired to the sweep."""
    from fde_api.jobs import worker as worker_module

    monkeypatch.setattr(worker_module, "LEASE_RENEW_SECONDS", 0.05)
    observed: list[datetime] = []

    def handler(current):
        observer = db.session()
        try:
            observed.append(observer.get(BackgroundJob, current.id).locked_until)
            time.sleep(0.4)
            observed.append(observer.get(BackgroundJob, current.id).locked_until)
        finally:
            observer.close()

    job = _job(db_session, job_type="worker_renew", status="pending")
    register_handler("worker_renew", handler)
    try:
        outcome = run_job(job.id)
    finally:
        clear_handlers()

    assert outcome == "succeeded"
    assert len(observed) == 2
    assert observed[1] > observed[0]
