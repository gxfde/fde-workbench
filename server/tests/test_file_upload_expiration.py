from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import select, update

from fde_api.extensions import db, object_storage
from fde_api.files.expiration import (
    UPLOAD_CLEANUP_JOB_TYPE,
    cleanup_expired_upload_job,
    expire_upload_session,
    schedule_expired_upload_cleanup,
)
from fde_api.files.models import UploadSession
from fde_api.files.service import _load_upload_session
from fde_api.jobs.handlers import clear_handlers
from fde_api.jobs.models import BackgroundJob, OutboxEvent
from fde_api.jobs.outbox import dispatch_pending
from fde_api.jobs.queue import ensure_background_job
from fde_api.jobs.reconcile import RECOVERABLE_JOB_TYPES
from fde_api.jobs.worker import run_job
from fde_api.storage.base import StorageError

from test_file_uploads_api import _authed_client, _create_upload, _persisted_project


def _expired_session(db_session, *, project, leader, client, settings):
    uploader = _authed_client(client, leader, settings)
    response = _create_upload(uploader, project.id, name="expired.docx")
    assert response.status_code == 201, response.get_data(as_text=True)
    session_id = response.json["data"]["id"]
    db_session.execute(
        update(UploadSession)
        .where(UploadSession.id == session_id)
        .values(expires_at=datetime.now(UTC) - timedelta(seconds=1))
    )
    db_session.commit()
    return uploader, session_id


def test_expired_sign_marks_session_and_returns_conflict(
    db_session, client, settings
):
    project, leader = _persisted_project(db_session, code=f"FDE-EXP-{uuid4().hex[:8]}")
    uploader, session_id = _expired_session(
        db_session, project=project, leader=leader, client=client, settings=settings
    )

    response = uploader.post(
        f"/api/v1/projects/{project.id}/files/{session_id}/parts",
        json={"part_number": 1},
    )

    assert response.status_code == 409
    assert response.json["error"]["code"] == "upload_session_expired"
    db_session.expire_all()
    row = db_session.get(UploadSession, session_id)
    assert row.status == "expired"
    assert row.completion_json["expiry_cleanup"]["status"] == "queued"
    assert db_session.query(OutboxEvent).filter_by(
        topic=UPLOAD_CLEANUP_JOB_TYPE, aggregate_id=session_id
    ).count() == 1


def test_expired_complete_has_no_file_side_effect(
    db_session, client, settings
):
    project, leader = _persisted_project(db_session, code=f"FDE-EXPC-{uuid4().hex[:8]}")
    uploader, session_id = _expired_session(
        db_session, project=project, leader=leader, client=client, settings=settings
    )

    response = uploader.post(
        f"/api/v1/projects/{project.id}/files/{session_id}/complete",
        json={"parts": [{"part_number": 1, "etag": "late"}]},
    )

    assert response.status_code == 409
    assert response.json["error"]["code"] == "upload_session_expired"
    assert db_session.query(OutboxEvent).filter_by(topic="file.preview").count() == 0


def test_sign_part_shrinks_transport_signature_to_session_deadline(
    db_session, client, settings, monkeypatch
):
    project, leader = _persisted_project(db_session, code=f"FDE-TTL-{uuid4().hex[:8]}")
    uploader = _authed_client(client, leader, settings)
    create = _create_upload(uploader, project.id, name="short.docx")
    session_id = create.json["data"]["id"]
    expires_at = datetime.now(UTC) + timedelta(seconds=41)
    db_session.execute(
        update(UploadSession).where(UploadSession.id == session_id).values(expires_at=expires_at)
    )
    db_session.commit()

    captured: dict[str, int] = {}
    storage = object_storage.current
    original = storage.sign_part

    def sign_part(key, upload_id, part_number, expires_seconds=300):
        captured["expires_seconds"] = expires_seconds
        return original(key, upload_id, part_number, expires_seconds=expires_seconds)

    monkeypatch.setattr(storage, "sign_part", sign_part)
    response = uploader.post(
        f"/api/v1/projects/{project.id}/files/{session_id}/parts",
        json={"part_number": 1},
    )

    assert response.status_code == 200
    assert 1 <= captured["expires_seconds"] <= 41
    assert response.json["data"]["expires_seconds"] == captured["expires_seconds"]


def test_expire_claim_includes_exact_deadline(db_session, client, settings):
    project, leader = _persisted_project(db_session, code=f"FDE-EQ-{uuid4().hex[:8]}")
    _uploader, session_id = _expired_session(
        db_session, project=project, leader=leader, client=client, settings=settings
    )
    db_session.expire_all()
    row = db_session.get(UploadSession, session_id)
    exact = row.expires_at
    db_session.refresh(row)
    assert expire_upload_session(db_session, row, now=exact) is True
    db_session.commit()
    assert db_session.get(UploadSession, session_id).status == "expired"


def test_expired_cleanup_claim_is_idempotent(db_session, client, settings):
    project, leader = _persisted_project(db_session, code=f"FDE-CLM-{uuid4().hex[:8]}")
    _uploader, session_id = _expired_session(
        db_session, project=project, leader=leader, client=client, settings=settings
    )

    now = datetime.now(UTC)
    assert schedule_expired_upload_cleanup(now=now) == 1
    assert schedule_expired_upload_cleanup(now=now + timedelta(seconds=1)) == 0
    assert db_session.query(OutboxEvent).filter_by(
        topic=UPLOAD_CLEANUP_JOB_TYPE, aggregate_id=session_id
    ).count() == 1


def test_cleanup_not_found_is_success_and_storage_failure_records_retry(
    db_session, client, settings, monkeypatch
):
    project, leader = _persisted_project(db_session, code=f"FDE-CLN-{uuid4().hex[:8]}")
    _uploader, session_id = _expired_session(
        db_session, project=project, leader=leader, client=client, settings=settings
    )
    assert schedule_expired_upload_cleanup(now=datetime.now(UTC)) == 1
    db_session.commit()
    job = BackgroundJob(
        job_type=UPLOAD_CLEANUP_JOB_TYPE,
        target_id=session_id,
        status="running",
        attempts=1,
    )
    db_session.add(job)
    db_session.commit()

    monkeypatch.setattr(
        object_storage.current,
        "abort_multipart",
        lambda key, upload_id: (_ for _ in ()).throw(
            StorageError("multipart_upload_not_found")
        ),
    )
    cleanup_expired_upload_job(SimpleNamespace(target_id=session_id, attempts=1))
    db_session.expire_all()
    row = db_session.get(UploadSession, session_id)
    assert row.completion_json["expiry_cleanup"]["status"] == "succeeded"

    project2, leader2 = _persisted_project(db_session, code=f"FDE-CLF-{uuid4().hex[:8]}")
    _uploader2, session_id2 = _expired_session(
        db_session, project=project2, leader=leader2, client=client, settings=settings
    )
    assert schedule_expired_upload_cleanup(now=datetime.now(UTC)) == 1
    db_session.commit()

    monkeypatch.setattr(
        object_storage.current,
        "abort_multipart",
        lambda key, upload_id: (_ for _ in ()).throw(StorageError("storage_backend_error")),
    )
    with pytest.raises(StorageError):
        cleanup_expired_upload_job(SimpleNamespace(target_id=session_id2, attempts=1))
    db_session.expire_all()
    row2 = db_session.get(UploadSession, session_id2)
    record = row2.completion_json["expiry_cleanup"]
    assert record["status"] == "failed"
    assert record["last_error_code"] == "storage_backend_error"


def test_cleanup_job_is_recoverable_and_failure_hook_updates_ledger(
    db_session, client, settings, monkeypatch
):
    project, leader = _persisted_project(db_session, code=f"FDE-REC-{uuid4().hex[:8]}")
    _uploader, session_id = _expired_session(
        db_session, project=project, leader=leader, client=client, settings=settings
    )
    assert UPLOAD_CLEANUP_JOB_TYPE in RECOVERABLE_JOB_TYPES
    assert schedule_expired_upload_cleanup(now=datetime.now(UTC)) == 1
    db_session.commit()
    job = BackgroundJob(
        job_type=UPLOAD_CLEANUP_JOB_TYPE,
        target_id=session_id,
        status="pending",
        max_attempts=1,
    )
    db_session.add(job)
    db_session.commit()

    monkeypatch.setattr(
        object_storage.current,
        "abort_multipart",
        lambda key, upload_id: (_ for _ in ()).throw(StorageError("storage_backend_error")),
    )
    try:
        assert run_job(job.id) == "failed"
    finally:
        clear_handlers()
    db_session.expire_all()
    row = db_session.get(UploadSession, session_id)
    assert row.completion_json["expiry_cleanup"]["status"] == "failed"
    assert row.completion_json["expiry_cleanup"]["last_error_code"] == "storage_backend_error"


def test_cleanup_job_uses_existing_outbox_and_active_job_dedup(db_session, client, settings):
    project, leader = _persisted_project(db_session, code=f"FDE-JOB-{uuid4().hex[:8]}")
    _uploader, session_id = _expired_session(
        db_session, project=project, leader=leader, client=client, settings=settings
    )
    assert schedule_expired_upload_cleanup(now=datetime.now(UTC)) == 1
    db_session.commit()
    queue = SimpleNamespace(enqueued=[])
    queue.enqueue = lambda job_id: queue.enqueued.append(job_id)
    dispatch_pending(db_session, queue)
    job = db_session.scalar(
        select(BackgroundJob).where(
            BackgroundJob.job_type == UPLOAD_CLEANUP_JOB_TYPE,
            BackgroundJob.target_id == session_id,
        )
    )
    assert job is not None
    assert queue.enqueued == [job.id]
    assert ensure_background_job(db_session, UPLOAD_CLEANUP_JOB_TYPE, session_id).id == job.id
