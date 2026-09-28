"""Background file scanning, type verification, and promotion to available.

The ``file.scan`` handler loads the uploaded version, verifies its magic bytes
against its extension, hashes + scans the object, and either promotes it to a
permanent immutable key (``status=available``) or transitions it to a non
-available state (``rejected`` when infected / mismatched, ``quarantined`` when
the scanner is unavailable).
"""

from __future__ import annotations

import hashlib
import tempfile
from dataclasses import dataclass
from typing import BinaryIO

from flask import current_app
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from fde_api.extensions import db, object_storage
from fde_api.files.models import ProjectFileVersion
from fde_api.files.names import attachment_key, document_key, extension_of
from fde_api.files.scanner import (
    HEAD_BYTES,
    ClamAvScanner,
    FileScanner,
    ScanResult,
    sniff_family,
)
from fde_api.jobs.handlers import register_handler
from fde_api.storage.base import StorageError

_CHUNK_SIZE = 1024 * 1024

#: Version states that must never be reprocessed.
_TERMINAL_STATUSES = ("available", "rejected", "failed")

#: Allowed extensions that impose a magic-byte family expectation.
_EXTENSION_FAMILY = {
    ".pdf": "pdf",
    ".png": "png",
    ".jpg": "jpeg",
    ".jpeg": "jpeg",
    ".zip": "zip",
    ".docx": "zip",
    ".xlsx": "zip",
    ".pptx": "zip",
}


@dataclass
class ProcessingResult:
    """Result of processing one file version."""

    status: str
    scan_status: str
    storage_key: str
    error_code: str
    sha256: str
    size: int
    preview_status: str


def hash_and_scan(
    stream: BinaryIO, scanner: FileScanner
) -> tuple[str, ScanResult]:
    """Stream ``stream`` into a spooled file in 1 MB chunks, hashing as we go.

    Returns ``(sha256_hexdigest, scan_result)``. The stream position is not
    restored; callers pass a freshly opened stream.
    """
    digest = hashlib.sha256()
    with tempfile.SpooledTemporaryFile(max_size=64 * 1024 * 1024) as spool:
        while chunk := stream.read(_CHUNK_SIZE):
            digest.update(chunk)
            spool.write(chunk)
        spool.seek(0)
        result = scanner.scan(spool)
    return digest.hexdigest(), result


def process_file(*, version_id: str, scanner: FileScanner) -> ProcessingResult:
    """Scan and promote one file version; never raises.

    Terminal versions (``available``/``rejected``/``failed``) are returned as-is
    so a replayed job is idempotent. On an unexpected failure the version is
    best-effort marked ``failed`` and a result is still returned.
    """
    session = db.session()
    try:
        return _process_file_core(session, version_id, scanner)
    except StorageError:
        return _mark_quarantined(session, version_id, error_code="storage_error")
    except Exception:
        return _mark_failed(session, version_id)
    finally:
        session.close()


def _process_file_core(
    session, version_id: str, scanner: FileScanner
) -> ProcessingResult:
    version = _load_version(session, version_id)
    if version is None:
        return ProcessingResult(
            status="failed",
            scan_status="error",
            storage_key="",
            error_code="version_not_found",
            sha256="",
            size=0,
            preview_status="none",
        )
    if version.status in _TERMINAL_STATUSES:
        return _result_from_version(version)

    project_file = version.project_file
    filename = version.original_filename

    # Read enough head bytes to sniff the magic signature.
    with object_storage.current.open_stream(version.storage_key) as stream:
        head = stream.read(HEAD_BYTES)

    if _media_type_mismatch(head, filename):
        version.status = "rejected"
        version.scan_status = "error"
        session.commit()
        return ProcessingResult(
            status="rejected",
            scan_status="error",
            storage_key=version.storage_key,
            error_code="file_type_mismatch",
            sha256=version.sha256,
            size=version.size_bytes,
            preview_status=version.preview_status,
        )

    with object_storage.current.open_stream(version.storage_key) as stream:
        digest, scan = hash_and_scan(stream, scanner)

    if scan.status == "infected":
        version.status = "rejected"
        version.scan_status = "infected"
        session.commit()
        return ProcessingResult(
            status="rejected",
            scan_status="infected",
            storage_key=version.storage_key,
            error_code="infected",
            sha256=digest,
            size=version.size_bytes,
            preview_status=version.preview_status,
        )

    if scan.status in ("error", "timeout", "not_checked") or scan.status is None:
        version.status = "quarantined"
        # The DB constraint only allows 'error'; timeout/not_checked map here.
        version.scan_status = "error"
        session.commit()
        return ProcessingResult(
            status="quarantined",
            scan_status=scan.status or "error",
            storage_key=version.storage_key,
            error_code="",
            sha256=digest,
            size=version.size_bytes,
            preview_status=version.preview_status,
        )

    # Clean -> promote to the immutable final key.
    final_key = _final_key(project_file, version)
    object_storage.current.copy(source_key=version.storage_key, target_key=final_key)
    head_obj = object_storage.current.head(final_key)

    version.storage_key = final_key
    version.sha256 = digest
    version.size_bytes = head_obj.size
    version.etag = head_obj.etag
    version.status = "available"
    version.scan_status = "clean"
    project_file.current_version_id = version.id
    session.commit()

    return ProcessingResult(
        status="available",
        scan_status="clean",
        storage_key=final_key,
        error_code="",
        sha256=digest,
        size=head_obj.size,
        preview_status=version.preview_status,
    )


def register_file_scan_handler() -> None:
    """Register the ``file.scan`` worker handler (idempotent)."""
    register_handler("file.scan", _file_scan_handler)


def _file_scan_handler(job) -> None:
    """Background job body: process ``job.target_id`` as a file version."""
    try:
        process_file(version_id=job.target_id, scanner=_build_scanner())
    except Exception:  # noqa: BLE001 - never raise; best-effort mark failed
        _mark_version_failed(job.target_id)


def _build_scanner() -> ClamAvScanner:
    try:
        settings = current_app.config.get("SETTINGS")
    except Exception:  # noqa: BLE001 - settings are optional
        settings = None
    return ClamAvScanner(
        host=getattr(settings, "clamav_host", "127.0.0.1") if settings else "127.0.0.1",
        port=getattr(settings, "clamav_port", 3310) if settings else 3310,
        timeout_seconds=(
            getattr(settings, "clamav_timeout_seconds", 10) if settings else 10
        ),
        socket_timeout_seconds=(
            getattr(settings, "clamav_socket_timeout_seconds", 5) if settings else 5
        ),
    )


def _load_version(session, version_id: str) -> ProjectFileVersion | None:
    return session.scalar(
        select(ProjectFileVersion)
        .options(selectinload(ProjectFileVersion.project_file))
        .where(ProjectFileVersion.id == version_id)
    )


def _media_type_mismatch(head: bytes, filename: str) -> bool:
    family = sniff_family(head)
    extension = extension_of(filename)
    expected = _EXTENSION_FAMILY.get(extension)
    if expected is None:
        return False
    return family != expected


def _final_key(project_file, version: ProjectFileVersion) -> str:
    project_id = project_file.project_id
    version_label = f"v{version.version_number}"
    filename = version.original_filename
    if project_file.category == "document":
        return document_key(project_id, version.file_id, version_label, filename)
    return attachment_key(project_id, version.file_id, version_label, filename)


def _result_from_version(version: ProjectFileVersion) -> ProcessingResult:
    return ProcessingResult(
        status=version.status,
        scan_status=version.scan_status,
        storage_key=version.storage_key,
        error_code="",
        sha256=version.sha256,
        size=version.size_bytes,
        preview_status=version.preview_status,
    )


def _mark_quarantined(session, version_id: str, *, error_code: str) -> ProcessingResult:
    try:
        version = session.get(ProjectFileVersion, version_id)
        if version is not None and version.status not in _TERMINAL_STATUSES:
            version.status = "quarantined"
            version.scan_status = "error"
            session.commit()
        storage_key = version.storage_key if version is not None else ""
        sha256 = version.sha256 if version is not None else ""
        size = version.size_bytes if version is not None else 0
        preview = version.preview_status if version is not None else "none"
    except Exception:  # noqa: BLE001 - best effort
        session.rollback()
        storage_key = ""
        sha256 = ""
        size = 0
        preview = "none"
    return ProcessingResult(
        status="quarantined",
        scan_status="error",
        storage_key=storage_key,
        error_code=error_code,
        sha256=sha256,
        size=size,
        preview_status=preview,
    )


def _mark_failed(session, version_id: str) -> ProcessingResult:
    try:
        version = session.get(ProjectFileVersion, version_id)
        if version is not None and version.status not in _TERMINAL_STATUSES:
            version.status = "failed"
            version.scan_status = "error"
            session.commit()
        storage_key = version.storage_key if version is not None else ""
        sha256 = version.sha256 if version is not None else ""
        size = version.size_bytes if version is not None else 0
        preview = version.preview_status if version is not None else "none"
    except Exception:  # noqa: BLE001 - best effort
        session.rollback()
        storage_key = ""
        sha256 = ""
        size = 0
        preview = "none"
    return ProcessingResult(
        status="failed",
        scan_status="error",
        storage_key=storage_key,
        error_code="processing_error",
        sha256=sha256,
        size=size,
        preview_status=preview,
    )


def _mark_version_failed(version_id: str) -> None:
    session = db.session()
    try:
        version = session.get(ProjectFileVersion, version_id)
        if version is not None and version.status not in _TERMINAL_STATUSES:
            version.status = "failed"
            version.scan_status = "error"
            session.commit()
    except Exception:  # noqa: BLE001 - best effort
        session.rollback()
    finally:
        session.close()


# Register the built-in handler on import so `file.scan` is always available,
# regardless of whether `handlers` or `processors` is imported first.
register_file_scan_handler()
