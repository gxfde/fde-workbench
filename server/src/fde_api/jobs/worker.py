"""Idempotent job runner with lease semantics.

Lease model
-----------
The claim (``status=running`` + lease) is committed **before** the handler
runs, and the lease is renewed while the handler is alive. Two properties
follow, and the reconciliation sweep (``jobs/reconcile.py``) depends on both:

* an in-flight job is visible to other processes as ``running`` with a future
  ``locked_until`` — so "someone is working on this" is distinguishable from
  "the worker died holding it";
* the row lock is held only for the short claim transaction, never across the
  handler — a long handler must not pin a connection inside an open
  transaction (that is exactly how the 2026-10-30 login outage happened).

The previous shape (claim + handler + terminal write inside one transaction)
had neither property: the running state was never committed, the row stayed
locked for the whole handler, and a dead worker left nothing behind to detect.
"""

from __future__ import annotations

import logging
import os
import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta

from flask import current_app, has_app_context
from sqlalchemy import update

from fde_api.extensions import db
from fde_api.jobs.handlers import get_handler
from fde_api.jobs.models import BackgroundJob
from fde_api.jobs.outbox import mark_completed, mark_failed, utcnow

logger = logging.getLogger(__name__)

LEASE_MINUTES = 5
# How often the lease is renewed while a handler runs. Well below the lease
# itself, so a live job never looks expired to the reconciler.
LEASE_RENEW_SECONDS = 60


@dataclass(slots=True)
class _Claim:
    """Outcome of the claim transaction."""

    kind: str
    job: BackgroundJob | None = None
    handler: Callable[[BackgroundJob], None] | None = None
    token: str = ""


def run_job(job_id: str) -> str:
    """Run one background job; replaying a terminal job is a no-op."""
    session = db.session()
    try:
        claim = _claim(session, job_id)
        if claim.kind != "claimed" or claim.handler is None or claim.job is None:
            return claim.kind

        stop = threading.Event()
        renewer: threading.Thread | None = None
        if has_app_context():
            renewer = threading.Thread(
                target=_renew_lease,
                args=(current_app._get_current_object(), job_id, claim.token, stop),  # type: ignore[attr-defined]
                name=f"lease-{job_id[:8]}",
                daemon=True,
            )
            renewer.start()
        try:
            claim.handler(claim.job)
        except Exception as exc:  # noqa: BLE001 - a job failure must be recorded
            stop.set()
            if renewer is not None:
                renewer.join(timeout=1)
            settled = _settle(
                session, job_id, claim.token, status="failed", last_error=str(exc)
            )
            return "failed" if settled else "settled_elsewhere"
        stop.set()
        if renewer is not None:
            renewer.join(timeout=1)
        _settle(session, job_id, claim.token, status="succeeded")
        return "succeeded"
    finally:
        session.close()


def _claim(session, job_id: str) -> _Claim:
    """Take the job under a lease and commit that fact.

    The claim is a short transaction of its own: the running state has to be
    durable before the handler starts, otherwise a dead worker leaves nothing
    but an untouched pending row behind.
    """
    with session.begin():
        job = session.get(BackgroundJob, job_id, with_for_update=True)
        if job is None:
            return _Claim("not_found")
        if job.status in ("succeeded", "failed"):
            return _Claim("already_terminal")
        if (
            job.status in ("queued", "running")
            and job.locked_until is not None
            and job.locked_until > utcnow()
        ):
            return _Claim("leased")

        handler = get_handler(job.job_type)
        if handler is None:
            job.status = "failed"
            job.attempts += 1
            job.last_error = "no_handler_registered"
            # T-J1（WB-DEF-9）：本 claim 事务内同步收口派生 outbox 事件，
            # 否则 dispatched 行永远无人翻转。
            mark_failed(session, job.job_type, job.target_id, "no_handler_registered")
            return _Claim("no_handler")

        job.status = "running"
        job.attempts += 1
        job.locked_until = utcnow() + timedelta(minutes=LEASE_MINUTES)
        # The token carries the job id so a renewal only ever extends the
        # lease of the claim it belongs to.
        token = f"worker-{os.getpid()}-{job_id[:8]}"
        job.locked_by = token
        session.flush()
    return _Claim("claimed", job=job, handler=handler, token=token)


def _settle(
    session, job_id: str, token: str, *, status: str, last_error: str = ""
) -> bool:
    """Write the terminal state and release the lease.

    Guarded by the claim token: if the reconciler re-queued this job while
    the (renewal-broken) handler was still running and another worker
    claimed it, the stale worker must not overwrite the new claim's state.
    Returns whether the write happened.

    T-J1（WB-DEF-9）：终态落库与派生 outbox 事件收口同事务——job 行与
    outbox 行要么一起翻转，要么一起留在原状。
    """
    # 结束可能残留的隐式事务（handler 若碰过同一 session）：`session.begin()`
    # 要求当前没有活动事务。
    session.rollback()
    with session.begin():
        job = session.get(
            BackgroundJob, job_id, with_for_update=True, populate_existing=True
        )
        if job is None:
            return False
        if job.locked_by is not None and job.locked_by != token:
            return False
        if job.status in ("succeeded", "failed"):
            return False
        job.status = status
        job.locked_until = None
        job.locked_by = None
        if last_error:
            job.last_error = last_error
        if status == "succeeded":
            mark_completed(session, job.job_type, job.target_id)
        else:
            mark_failed(session, job.job_type, job.target_id, last_error)
        return True


def _renew_lease(app, job_id: str, token: str, stop: threading.Event) -> None:
    """Extend the lease of a running job until the handler returns.

    A renewal that finds no matching claim (the job was settled or taken
    over) stops the loop — the lease belongs to whoever holds the claim now.
    """
    while not stop.wait(LEASE_RENEW_SECONDS):
        try:
            with app.app_context():
                session = db.session()
                try:
                    with session.begin():
                        updated = session.execute(
                            update(BackgroundJob)
                            .where(
                                BackgroundJob.id == job_id,
                                BackgroundJob.status == "running",
                                BackgroundJob.locked_by == token,
                            )
                            .values(
                                locked_until=utcnow() + timedelta(minutes=LEASE_MINUTES)
                            )
                        ).rowcount  # type: ignore[attr-defined]
                finally:
                    session.close()
        except Exception:  # noqa: BLE001 - a failed renewal must not kill the job
            # 续租失败只记录：真正判断 worker 是否存活的是租约本身，
            # 续租偶发失败下一轮会补上。
            logger.warning("lease renewal failed job_id=%s", job_id, exc_info=True)
            continue
        if updated == 0:
            return
