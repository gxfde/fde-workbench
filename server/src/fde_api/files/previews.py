"""Preview generation and protected preview/download URL signing for files.

The ``file.preview`` background handler renders an uploaded document into a PDF
copy on object storage, while the ``preview-url`` / ``download-url`` endpoints
hand out short-lived signed URLs that recheck the actor's project access and
the version's availability on every request. A preview failure never makes the
original version unusable.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from fde_api.auth.models import User
from fde_api.extensions import db, object_storage
from fde_api.files.models import ProjectFileVersion
from fde_api.files.names import extension_of, preview_key
from fde_api.files.service import (
    FileServiceError,
    _get_project_for_upload,
    _get_project_viewable,
)
from fde_api.jobs.outbox import enqueue_outbox

#: Formats that can be previewed directly without a conversion pass.
_DIRECT_PREVIEW_EXTENSIONS = frozenset(
    {
        ".pdf",
        ".png",
        ".jpg",
        ".jpeg",
        ".gif",
        ".webp",
        ".txt",
        ".csv",
        ".md",
        ".json",
        ".log",
    }
)
#: Formats rendered through LibreOffice into a PDF preview.
_OFFICE_PREVIEW_EXTENSIONS = frozenset({".docx", ".xlsx", ".pptx"})
#: Scan states that are considered safe to render a preview from.
_PREVIEWABLE_SCAN_STATUSES = frozenset({"clean", "not_required"})

_PREVIEW_MIME_TYPE = "application/pdf"
_PREVIEW_VERSION_OFFSET = 1_000_000_000
_PREVIEW_EXPIRES_SECONDS = 300
_LIBREOFFICE_TIMEOUT_SECONDS = 120


def libreoffice_command(input_path: Path, output_dir: Path) -> list[str]:
    """Build the headless LibreOffice PDF-conversion command."""
    return [
        shutil.which("libreoffice") or shutil.which("soffice") or "libreoffice",
        "--headless",
        "--nologo",
        "--nodefault",
        "--nofirststartwizard",
        "--convert-to",
        "pdf",
        "--outdir",
        str(output_dir),
        str(input_path),
    ]


def generate_preview(version_id: str, *, runner=None) -> dict:
    """Prepare a PDF preview for one file version; never raises.

    On success the version is marked ``preview_status="ready"`` and
    ``preview_version_id`` points at a derived ``source="preview"`` version. On
    a conversion failure the version is marked ``preview_status="failed"`` but
    keeps ``status="available"`` so the original remains downloadable.
    """
    session = db.session()
    try:
        with session.begin():
            version = _load_version(session, version_id)
            if version is None:
                return {"preview_status": "none"}
            if not _is_previewable(version):
                return {"preview_status": version.preview_status}
            if version.preview_status == "ready" and version.preview_version_id:
                preview = session.get(ProjectFileVersion, version.preview_version_id)
                expected_key = _preview_object_key(version.project_file.project_id, version)
                if preview is not None and preview.parent_version_id == version.id and preview.storage_key == expected_key:
                    return {"preview_status": "ready"}

            project_id = version.project_file.project_id
            extension = extension_of(version.original_filename)
            if extension in _OFFICE_PREVIEW_EXTENSIONS:
                return _convert_office_preview(
                    session, version, project_id, runner
                )
            if extension in _DIRECT_PREVIEW_EXTENSIONS:
                return _direct_preview(session, version, project_id)

            version.preview_status = "failed"
            session.flush()
            return {"preview_status": "failed"}
    except Exception:
        session.rollback()
        return {"preview_status": "failed"}
    finally:
        session.close()


def get_preview_url(*, actor: User, project_id: str, version_id: str) -> str:
    """Sign a short-lived URL for a ready preview (or the source as a PDF)."""
    session = db.session()
    try:
        version = _load_version(session, version_id)
        if version is None or version.project_file.project_id != project_id:
            raise FileServiceError(
                "project_file_not_found", "The file was not found.", 404
            )
        _get_project_viewable(session, actor, project_id)
        if version.status not in {"available", "deprecated"}:
            raise FileServiceError(
                "file_not_available", "The file is not available.", 409
            )
        extension = extension_of(version.original_filename)
        # Directly previewable files must retain their original bytes, MIME type,
        # and filename. Treating TXT/images as a derived PDF makes Electron render
        # an empty frame because the response metadata no longer matches content.
        if extension in _DIRECT_PREVIEW_EXTENSIONS:
            return object_storage.current.sign_download(
                version.storage_key,
                version.original_filename,
                expires_seconds=_PREVIEW_EXPIRES_SECONDS,
            )
        preview_storage_key = None
        if version.preview_status == "ready" and version.preview_version_id:
            preview_version = session.get(
                ProjectFileVersion, version.preview_version_id
            )
            if preview_version is not None:
                preview_storage_key = preview_version.storage_key
        if preview_storage_key is None and extension not in _DIRECT_PREVIEW_EXTENSIONS:
            # An office preview that is not "ready" would otherwise hand back the
            # source bytes (e.g. a .docx) mislabeled as .pdf, which renders blank
            # in the renderer's iframe. Surface a clear error instead so the UI can
            # degrade to a message + download link.
            raise FileServiceError(
                "preview_not_available",
                "The preview is not ready. Download the original file instead.",
                409,
            )
        key = preview_storage_key or version.storage_key
        filename = f"{version.safe_filename}.pdf"
        return object_storage.current.sign_download(
            key, filename, expires_seconds=_PREVIEW_EXPIRES_SECONDS
        )
    except FileServiceError:
        raise
    finally:
        session.close()


def get_download_url(*, actor: User, project_id: str, version_id: str) -> str:
    """Sign a short-lived URL for retained original version bytes."""
    session = db.session()
    try:
        version = _load_version(session, version_id)
        if version is None or version.project_file.project_id != project_id:
            raise FileServiceError(
                "project_file_not_found", "The file was not found.", 404
            )
        _get_project_viewable(session, actor, project_id)
        if version.status not in {"available", "deprecated"}:
            raise FileServiceError(
                "file_not_available", "The file is not available.", 409
            )
        return object_storage.current.sign_download(
            version.storage_key,
            version.original_filename,
            expires_seconds=_PREVIEW_EXPIRES_SECONDS,
        )
    except FileServiceError:
        raise
    finally:
        session.close()


def request_preview_regeneration(
    *, actor: User, project_id: str, version_id: str
) -> dict:
    """Queue a fresh preview for an available, safe file version."""
    session = db.session()
    try:
        with session.begin():
            _get_project_for_upload(session, actor, project_id)
            version = session.scalar(
                select(ProjectFileVersion)
                .options(selectinload(ProjectFileVersion.project_file))
                .where(ProjectFileVersion.id == version_id)
                .with_for_update()
            )
            if version is None or version.project_file.project_id != project_id:
                raise FileServiceError(
                    "project_file_not_found", "The file was not found.", 404
                )
            if not _is_previewable(version):
                raise FileServiceError(
                    "file_not_previewable",
                    "Only an available file that passed security checks can be previewed.",
                    409,
                )
            extension = extension_of(version.original_filename)
            if extension not in _DIRECT_PREVIEW_EXTENSIONS | _OFFICE_PREVIEW_EXTENSIONS:
                raise FileServiceError(
                    "file_type_not_previewable",
                    "This file type does not support preview generation.",
                    409,
                )
            version.preview_status = "pending"
            version.preview_version_id = None
            enqueue_outbox(
                session,
                "file.preview",
                version.id,
                {"version_id": version.id, "requested_by_user_id": actor.id},
            )
            session.flush()
            return {"preview_status": "pending"}
    finally:
        session.close()


def register_file_preview_handler() -> None:
    """Register the ``file.preview`` worker handler (idempotent)."""
    from fde_api.jobs.handlers import register_handler

    register_handler("file.preview", _file_preview_handler)


def _file_preview_handler(job) -> None:
    """Background job body: render ``job.target_id`` as a preview; never raises."""
    try:
        generate_preview(job.target_id)
    except Exception:  # noqa: BLE001 - best effort; a preview must never raise
        pass


def _load_version(session, version_id: str) -> ProjectFileVersion | None:
    return session.scalar(
        select(ProjectFileVersion)
        .options(selectinload(ProjectFileVersion.project_file))
        .where(ProjectFileVersion.id == version_id)
    )


def _is_previewable(version: ProjectFileVersion) -> bool:
    return (
        version.status == "available"
        and version.scan_status in _PREVIEWABLE_SCAN_STATUSES
    )


def _preview_object_key(project_id: str, version: ProjectFileVersion) -> str:
    # Version numbers restart for every file. Use the immutable version id so
    # previews from different files in one project can never overwrite each other.
    return preview_key(project_id, version.id, f"preview-{version.id}")


def _direct_preview(session, version: ProjectFileVersion, project_id: str) -> dict:
    """Copy an already-previewable format onto its immutable preview key."""
    target_key = _preview_object_key(project_id, version)
    stored = object_storage.current.copy(
        source_key=version.storage_key, target_key=target_key
    )
    preview_version = _create_preview_version(
        session, version, target_key, stored
    )
    version.preview_status = "ready"
    version.preview_version_id = preview_version.id
    session.flush()
    return {"preview_status": "ready"}


def _convert_office_preview(
    session, version: ProjectFileVersion, project_id: str, runner
) -> dict:
    """Render an office document to PDF, then store it on the preview key."""
    target_key = _preview_object_key(project_id, version)
    with tempfile.TemporaryDirectory() as temp_dir:
        try:
            input_path = Path(temp_dir) / version.safe_filename
            with object_storage.current.open_stream(
                version.storage_key
            ) as stream:
                input_path.write_bytes(stream.read())
            output_dir = Path(temp_dir) / "out"
            output_dir.mkdir()
            converter = runner or _default_libreoffice_runner
            converter(input_path, output_dir)
            pdf_path = _find_converted_pdf(output_dir, input_path)
            if pdf_path is None:
                raise RuntimeError("libreoffice produced no PDF")
            with pdf_path.open("rb") as pdf_stream:
                stored = object_storage.current.put_stream(
                    target_key, pdf_stream, _PREVIEW_MIME_TYPE, {}
                )
            preview_version = _create_preview_version(
                session, version, target_key, stored
            )
            version.preview_status = "ready"
            version.preview_version_id = preview_version.id
            session.flush()
            return {"preview_status": "ready"}
        except Exception:  # noqa: BLE001 - timeout/error/failure => failed preview
            version.preview_status = "failed"
            session.flush()
            return {"preview_status": "failed"}


def _create_preview_version(
    session,
    source_version: ProjectFileVersion,
    target_key: str,
    stored,
) -> ProjectFileVersion:
    existing = (
        session.get(ProjectFileVersion, source_version.preview_version_id)
        if source_version.preview_version_id
        else None
    )
    if existing is not None and existing.source == "preview":
        existing.storage_key = target_key
        existing.size_bytes = stored.size
        existing.etag = stored.etag
        existing.status = "available"
        existing.parent_version_id = source_version.id
        session.flush()
        return existing
    version_number = _next_preview_version_number(session, source_version.file_id)
    preview_version = ProjectFileVersion(
        file_id=source_version.file_id,
        version_number=version_number,
        source="preview",
        original_filename=source_version.original_filename,
        safe_filename=source_version.safe_filename,
        extension=".pdf",
        mime_type=_PREVIEW_MIME_TYPE,
        bucket=source_version.bucket,
        storage_key=target_key,
        size_bytes=stored.size,
        etag=stored.etag,
        sha256="",
        scan_status="not_required",
        preview_status="none",
        uploaded_by_user_id=source_version.uploaded_by_user_id,
        parent_version_id=source_version.id,
        status="available",
    )
    session.add(preview_version)
    session.flush()
    return preview_version


def _next_preview_version_number(session, file_id: str) -> int:
    current = session.scalar(
        select(func.max(ProjectFileVersion.version_number)).where(
            ProjectFileVersion.file_id == file_id,
            ProjectFileVersion.source == "preview",
        )
    )
    return max(int(current or 0), _PREVIEW_VERSION_OFFSET) + 1


def _find_converted_pdf(output_dir: Path, input_path: Path) -> Path | None:
    expected = output_dir / f"{input_path.stem}.pdf"
    if expected.is_file():
        return expected
    candidates = sorted(output_dir.glob("*.pdf"))
    return candidates[0] if candidates else None


def _default_libreoffice_runner(input_path: Path, output_dir: Path) -> None:
    command = libreoffice_command(input_path, output_dir)
    result = subprocess.run(
        command,
        shell=False,
        timeout=_LIBREOFFICE_TIMEOUT_SECONDS,
        capture_output=True,
        cwd=str(output_dir),
    )
    if result.returncode != 0:
        raise subprocess.CalledProcessError(result.returncode, command)


# Register on import so `file.preview` is available even if the worker registry
# is not reached through the handlers module, mirroring the scan handler.
register_file_preview_handler()
