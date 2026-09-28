"""A minimal Redis-list job queue plus single-active-job guard."""

from __future__ import annotations

import time

from flask import current_app
from redis import Redis
from sqlalchemy import select
from sqlalchemy.orm import Session

from fde_api.jobs.models import BackgroundJob

ACTIVE_JOB_STATUSES = ("pending", "queued", "running")


class JobQueue:
    """A FIFO job queue backed by a Redis list.

    Kept deliberately dependency-light (no RQ) while preserving the
    outbox contract: `enqueue(job_id)` records work and `dequeue()` hands
    one job id to the worker loop.
    """

    def __init__(self, connection: Redis, name: str = "fde-jobs") -> None:
        self.connection = connection
        self.name = name

    def enqueue(self, job_id: str) -> None:
        self.connection.rpush(self.name, job_id)

    def dequeue(self, timeout: int = 5) -> str | None:
        # The shared Redis client deliberately has a short socket timeout for
        # health checks. Use a non-blocking pop and pace the worker locally so
        # an idle queue never terminates the worker with a socket timeout.
        item = self.connection.lpop(self.name)
        if item is None:
            time.sleep(max(0.0, min(float(timeout), 0.25)))
            return None
        return item.decode()

    def __len__(self) -> int:
        return int(self.connection.llen(self.name))


def get_queue() -> JobQueue:
    redis: Redis = current_app.extensions["fde_api_redis"]
    return JobQueue(redis)


def ensure_background_job(
    session: Session, job_type: str, target_id: str
) -> BackgroundJob:
    """Return the existing active job for (job_type, target_id) or create one.

    A terminal job frees the slot, so a fresh event for the same target
    starts a new job rather than re-enqueueing a completed one.
    """
    existing = session.scalar(
        select(BackgroundJob)
        .where(
            BackgroundJob.job_type == job_type,
            BackgroundJob.target_id == target_id,
            BackgroundJob.status.in_(ACTIVE_JOB_STATUSES),
        )
        .limit(1)
    )
    if existing is not None:
        return existing
    job = BackgroundJob(job_type=job_type, target_id=target_id, status="pending")
    session.add(job)
    session.flush()
    return job
