"""Idempotent job runner with lease semantics."""

from __future__ import annotations

import os
from datetime import timedelta

from fde_api.extensions import db
from fde_api.jobs.handlers import get_handler
from fde_api.jobs.models import BackgroundJob
from fde_api.jobs.outbox import utcnow

LEASE_MINUTES = 5


def run_job(job_id: str) -> str:
    """Run one background job exactly once; replaying a terminal job is a no-op."""
    session = db.session()
    try:
        with session.begin():
            job = session.get(BackgroundJob, job_id, with_for_update=True)
            if job is None:
                return "not_found"
            if job.status in ("succeeded", "failed"):
                return "already_terminal"
            if (
                job.status in ("queued", "running")
                and job.locked_until is not None
                and job.locked_until > utcnow()
            ):
                return "leased"

            handler = get_handler(job.job_type)
            if handler is None:
                job.status = "failed"
                job.attempts += 1
                job.last_error = "no_handler_registered"
                return "no_handler"

            job.status = "running"
            job.attempts += 1
            job.locked_until = utcnow() + timedelta(minutes=LEASE_MINUTES)
            job.locked_by = f"worker-{os.getpid()}"
            session.flush()

            try:
                handler(job)
            except Exception as exc:  # noqa: BLE001 - a job failure must be recorded
                job.status = "failed"
                job.last_error = str(exc)
                return "failed"
            job.status = "succeeded"
            job.locked_until = None
            return "succeeded"
    finally:
        session.close()
