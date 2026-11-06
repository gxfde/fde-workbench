"""Multipart upload expiration claims and cleanup jobs (B#13-B)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from fde_api.extensions import db, object_storage
from fde_api.files.models import UploadSession
from fde_api.jobs.outbox import enqueue_outbox, utcnow
from fde_api.storage.base import StorageError

UPLOAD_CLEANUP_JOB_TYPE = "file.upload.cleanup"
EXPIRY_CLEANUP_KEY = "expiry_cleanup"
CLEANUP_RETRY_BASE_MINUTES = 5
CLEANUP_RETRY_MAX_MINUTES = 60


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat()


def _cleanup_record(upload_session: UploadSession) -> dict[str, Any]:
    value = upload_session.completion_json.get(EXPIRY_CLEANUP_KEY)
    return dict(value) if isinstance(value, dict) else {}


def _set_cleanup_record(
    upload_session: UploadSession, record: dict[str, Any]
) -> None:
    upload_session.completion_json = {
        **(upload_session.completion_json or {}),
        EXPIRY_CLEANUP_KEY: record,
    }


def _retry_at(*, now: datetime, attempts: int) -> datetime:
    minutes = min(
        CLEANUP_RETRY_BASE_MINUTES * 2 ** max(attempts - 1, 0),
        CLEANUP_RETRY_MAX_MINUTES,
    )
    return now + timedelta(minutes=minutes)


def _queue_cleanup_in_session(
    session: Session, upload_session: UploadSession, *, now: datetime
) -> bool:
    """Queue cleanup using the caller's transaction/session."""
    record = _cleanup_record(upload_session)
    status = record.get("status")
    if status in {"queued", "running", "succeeded"}:
        return False
    next_retry_at = record.get("next_retry_at")
    if status == "failed" and isinstance(next_retry_at, str):
        try:
            if datetime.fromisoformat(next_retry_at) > now:
                return False
        except ValueError:
            pass

    attempts = int(record.get("attempts", 0) or 0)
    _set_cleanup_record(
        upload_session,
        {
            "status": "queued",
            "attempts": attempts,
            "queued_at": _iso(now),
            "next_retry_at": None,
            "last_error_code": "",
        },
    )
    enqueue_outbox(
        session,
        UPLOAD_CLEANUP_JOB_TYPE,
        upload_session.id,
        {"upload_session_id": upload_session.id},
    )
    return True


def expire_upload_session(
    session: Session, upload_session: UploadSession, *, now: datetime
) -> bool:
    """Move one locked uploading row to expired and queue cleanup."""
    current = now.astimezone(UTC)
    if upload_session.status != "uploading" or upload_session.expires_at > current:
        return False
    upload_session.status = "expired"
    _set_cleanup_record(
        upload_session,
        {
            "status": "queued",
            "attempts": 0,
            "queued_at": _iso(current),
            "next_retry_at": None,
            "last_error_code": "",
        },
    )
    enqueue_outbox(
        session,
        UPLOAD_CLEANUP_JOB_TYPE,
        upload_session.id,
        {"upload_session_id": upload_session.id},
    )
    return True


def schedule_expired_upload_cleanup(
    *, now: datetime | None = None, limit: int = 100
) -> int:
    """Claim expired upload rows and enqueue one cleanup event per row."""
    current = (now or datetime.now(UTC)).astimezone(UTC)
    session = db.session()
    queued = 0
    try:
        with session.begin():
            rows = list(
                session.scalars(
                    select(UploadSession)
                    .where(
                        or_(
                            (UploadSession.status == "uploading")
                            & (UploadSession.expires_at <= current),
                            UploadSession.status == "expired",
                        )
                    )
                    .order_by(UploadSession.expires_at, UploadSession.id)
                    .with_for_update(skip_locked=True)
                    .limit(limit)
                )
            )
            for upload_session in rows:
                if upload_session.status == "uploading":
                    if expire_upload_session(session, upload_session, now=current):
                        queued += 1
                elif _queue_cleanup_in_session(session, upload_session, now=current):
                    queued += 1
        return queued
    finally:
        session.close()


def cleanup_expired_upload_job(job) -> None:
    """Abort remote multipart state outside a DB transaction, then finalize."""
    session = db.session()
    try:
        with session.begin():
            upload_session = session.get(
                UploadSession, job.target_id, with_for_update=True
            )
            if upload_session is None or upload_session.status != "expired":
                return
            record = _cleanup_record(upload_session)
            if record.get("status") == "succeeded":
                return
            attempts = max(int(record.get("attempts", 0) or 0), int(job.attempts or 0))
            _set_cleanup_record(
                upload_session,
                {
                    **record,
                    "status": "running",
                    "attempts": attempts,
                    "started_at": _iso(utcnow()),
                    "last_error_code": "",
                },
            )
            storage_prefix = upload_session.storage_prefix
            multipart_upload_id = upload_session.multipart_upload_id

        try:
            object_storage.current.abort_multipart(
                storage_prefix, multipart_upload_id
            )
        except StorageError as error:
            if error.code != "multipart_upload_not_found":
                _record_cleanup_failure(job.target_id, error.code, attempts)
                raise

        with session.begin():
            upload_session = session.get(
                UploadSession, job.target_id, with_for_update=True
            )
            if upload_session is None or upload_session.status != "expired":
                return
            record = _cleanup_record(upload_session)
            _set_cleanup_record(
                upload_session,
                {
                    **record,
                    "status": "succeeded",
                    "completed_at": _iso(utcnow()),
                    "next_retry_at": None,
                    "last_error_code": "",
                },
            )
    finally:
        session.close()


def _record_cleanup_failure(
    upload_session_id: str, error_code: str, attempts: int
) -> None:
    session = db.session()
    try:
        with session.begin():
            upload_session = session.get(
                UploadSession, upload_session_id, with_for_update=True
            )
            if upload_session is None or upload_session.status != "expired":
                return
            now = utcnow()
            record = _cleanup_record(upload_session)
            _set_cleanup_record(
                upload_session,
                {
                    **record,
                    "status": "failed",
                    "attempts": attempts,
                    "failed_at": _iso(now),
                    "next_retry_at": _iso(
                        _retry_at(now=now, attempts=max(attempts, 1))
                    ),
                    "last_error_code": error_code,
                },
            )
    finally:
        session.close()


def fail_expired_upload_cleanup(session: Session, job) -> None:
    """Record a retryable cleanup failure after worker loss/exhaustion."""
    upload_session = session.get(UploadSession, job.target_id, with_for_update=True)
    if upload_session is None or upload_session.status != "expired":
        return
    now = utcnow()
    record = _cleanup_record(upload_session)
    attempts = max(int(record.get("attempts", 0) or 0), int(job.attempts or 0))
    _set_cleanup_record(
        upload_session,
        {
            **record,
            "status": "failed",
            "attempts": attempts,
            "failed_at": _iso(now),
            "next_retry_at": _iso(_retry_at(now=now, attempts=max(attempts, 1))),
            "last_error_code": "worker_failed",
        },
    )


def register_upload_expiration_handlers() -> None:
    from fde_api.jobs.handlers import register_handler, register_job_failure_handler

    register_handler(UPLOAD_CLEANUP_JOB_TYPE, cleanup_expired_upload_job)
    register_job_failure_handler(
        UPLOAD_CLEANUP_JOB_TYPE, fail_expired_upload_cleanup
    )
