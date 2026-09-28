"""Project document version lifecycle service.

Implements the Task 6 version workflow on top of the immutable
``ProjectDocumentVersion`` chain. Every user-addressable failure is raised as
:class:`DocumentVersionServiceError` so the routes can wrap it with
:func:`fde_api.errors.error_response`.

Writes are single-transaction and reuse ``record_event`` (project-scoped events,
never the document body), ``project_access`` and ``enqueue_outbox``. Manual
revisions never overwrite an existing OSS object — they always allocate a fresh
``storage_key`` derived from the new version number.
"""

from __future__ import annotations

import copy
import hashlib
import io
import zipfile
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from docx import Document
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session, selectinload

from fde_api.auth.models import User
from fde_api.documents.models import (
    DocumentGenerationJob,
    DocumentTemplateVersion,
    ProjectDocument,
    ProjectDocumentVersion,
)
from fde_api.extensions import db, object_storage
from fde_api.files.models import ProjectFile, ProjectFileVersion
from fde_api.files.names import document_key, extension_of, safe_filename
from fde_api.files.service import create_direct_file_version
from fde_api.jobs.outbox import enqueue_outbox
from fde_api.projects.events import record_event
from fde_api.projects.permissions import project_access
from fde_api.workbench.models import Project, ProjectMember

DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
DOCX_EXTENSION = ".docx"
DOWNLOAD_EXPIRES_SECONDS = 300
_CONTENT_SNAPSHOT_KEYS = ("field_overrides", "rich_text", "list_selections")
_DOWNLOADABLE_SCAN_STATUSES = frozenset({"clean", "not_required"})


class DocumentVersionServiceError(Exception):
    """A stable, user-facing document version failure."""

    def __init__(self, code: str, message: str, status: int):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


def list_document_versions(
    *, actor: User, project_id: str, document_id: str
) -> list[dict[str, Any]]:
    """Return the document's version history (view allowed), newest first."""
    session = db.session()
    try:
        project = _load_project_for_view(session, actor, project_id)
        document = _load_document(session, project.id, document_id)
        if document is None:
            raise DocumentVersionServiceError(
                "document_not_found", "Document was not found.", 404
            )
        versions = list(
            session.scalars(
                select(ProjectDocumentVersion)
                .options(
                    selectinload(ProjectDocumentVersion.docx_file),
                    selectinload(ProjectDocumentVersion.preview_file),
                    selectinload(ProjectDocumentVersion.generated_by),
                    selectinload(ProjectDocumentVersion.confirmed_by),
                )
                .where(ProjectDocumentVersion.document_id == document.id)
                .order_by(ProjectDocumentVersion.version_number.desc())
            )
        )
        return [_serialize_version_report(version) for version in versions]
    finally:
        session.close()


def online_revise_document(
    *,
    actor: User,
    project_id: str,
    document_id: str,
    expected_version: int,
    draft_changes: Mapping[str, Any],
) -> dict[str, Any]:
    """Create a new draft version that reuses the parent snapshot (engineer/manager).

    The new version is ``source="online_revised"``, copies the current version's
    ``source_snapshot_json`` and overlays ``draft_changes`` onto the content
    snapshot. A placeholder DOCX file version is allocated and a
    ``DocumentGenerationJob`` plus a ``document.generate`` outbox event are
    enqueued so the new draft re-renders asynchronously.
    """
    if not isinstance(draft_changes, Mapping) or set(draft_changes) - set(_CONTENT_SNAPSHOT_KEYS):
        raise DocumentVersionServiceError(
            "invalid_request", "文档修订仅允许修改正文、字段和列表，不能修改来源方案等冻结元数据。", 400
        )
    session = db.session()
    try:
        with session.begin():
            project = _load_project_for_update(session, project_id)
            _require_document_editor(actor, project)
            document = _load_document(session, project.id, document_id)
            if document is None:
                raise DocumentVersionServiceError(
                    "document_not_found", "Document was not found.", 404
                )
            _require_document_version(project, document, expected_version)

            current = document.current_version
            if current is None:
                raise DocumentVersionServiceError(
                    "invalid_document_state",
                    "The document has no version to revise.",
                    409,
                )
            template_version = session.get(
                DocumentTemplateVersion, document.source_template_version_id
            )
            if template_version is None:
                raise DocumentVersionServiceError(
                    "template_version_not_found",
                    "The document template version was not found.",
                    404,
                )

            version_number = _next_document_version_number(session, document.id)
            docx_file_version = _create_placeholder_docx(
                session, project, document, version_number, actor
            )
            source_snapshot = copy.deepcopy(current.source_snapshot_json)
            content_snapshot = {
                **(current.content_snapshot_json or {}),
                **dict(draft_changes),
            }

            version = ProjectDocumentVersion(
                document_id=document.id,
                version_number=version_number,
                source="online_revised",
                status="draft",
                parent_version_id=current.id,
                source_template_version_id=template_version.id,
                source_snapshot_json=source_snapshot,
                content_snapshot_json=content_snapshot,
                docx_file_version_id=docx_file_version.id,
                sha256="",
                generated_by_user_id=actor.id,
            )
            session.add(version)
            session.flush()

            job = DocumentGenerationJob(document_version_id=version.id, status="queued")
            session.add(job)
            session.flush()
            enqueue_outbox(
                session,
                "document.generate",
                version.id,
                {"version_id": version.id, "document_id": document.id},
            )

            document.current_version_id = version.id
            document.version += 1
            record_event(
                session,
                actor,
                "project_document_online_revised",
                project,
                {
                    "document_id": document.id,
                    "version_id": version.id,
                    "version_number": version_number,
                },
            )
            session.flush()
            session.refresh(version)
            return _serialize_version(version) | {
                "project_version": project.version,
                "document_version": document.version,
            }
    except DocumentVersionServiceError:
        raise
    except IntegrityError:
        raise DocumentVersionServiceError(
            "document_conflict", "The document revision could not be created.", 409
        ) from None
    except SQLAlchemyError:
        raise DocumentVersionServiceError(
            "document_revision_failed",
            "Unable to revise the document at this time.",
            503,
        ) from None
    finally:
        session.close()


def upload_manual_revision(
    *,
    actor: User,
    project_id: str,
    document_id: str,
    expected_version: int,
    docx_bytes: bytes,
    note: str,
) -> dict[str, Any]:
    """Upload a hand-authored DOCX as a new immutable current version.

    Validates the bytes are a readable DOCX, writes them to a brand-new storage
    key (never overwriting an existing object) and promotes them in one
    transaction as ``source="manual_upload"`` / ``status="draft"``.
    """
    _validate_docx_bytes(docx_bytes)
    session = db.session()
    try:
        with session.begin():
            project = _load_project_for_update(session, project_id)
            _require_document_editor(actor, project)
            document = _load_document(session, project.id, document_id)
            if document is None:
                raise DocumentVersionServiceError(
                    "document_not_found", "Document was not found.", 404
                )
            _require_document_version(project, document, expected_version)

            version_number = _next_document_version_number(session, document.id)
            parent_version_id = document.current_version_id
            filename = f"{document.business_code}-v{version_number}{DOCX_EXTENSION}"
            storage_key = document_key(
                document.project_id, document.id, f"v{version_number}", filename
            )
            sha256 = hashlib.sha256(docx_bytes).hexdigest()
            stored = object_storage.current.put_stream(
                storage_key, io.BytesIO(docx_bytes), DOCX_MIME, {}
            )
            file_version = create_direct_file_version(
                session,
                document.project_id,
                document.id,
                storage_key,
                filename,
                DOCX_MIME,
                sha256,
                actor,
                size_bytes=stored.size,
                etag=stored.etag,
                file_id=document.library_file_id,
                display_name=document.business_code,
            )
            if document.library_file_id is None:
                document.library_file_id = file_version.file_id
            source_snapshot = (
                copy.deepcopy(document.current_version.source_snapshot_json)
                if document.current_version is not None
                else {}
            )
            content_snapshot = _empty_content_snapshot()
            if isinstance(source_snapshot.get("solution"), dict):
                content_snapshot["solution"] = copy.deepcopy(source_snapshot["solution"])

            version = ProjectDocumentVersion(
                document_id=document.id,
                version_number=version_number,
                source="manual_upload",
                status="draft",
                parent_version_id=parent_version_id,
                source_template_version_id=document.source_template_version_id,
                source_snapshot_json=source_snapshot,
                content_snapshot_json=content_snapshot,
                docx_file_version_id=file_version.id,
                sha256=sha256,
                generated_by_user_id=actor.id,
            )
            session.add(version)
            session.flush()

            document.current_version_id = version.id
            document.version += 1
            record_event(
                session,
                actor,
                "project_document_manual_revision_uploaded",
                project,
                {
                    "document_id": document.id,
                    "version_id": version.id,
                    "version_number": version_number,
                    "note": note or "",
                },
            )
            session.flush()
            session.refresh(version)
            return _serialize_version(version) | {
                "project_version": project.version,
                "document_version": document.version,
            }
    except DocumentVersionServiceError:
        raise
    except IntegrityError:
        raise DocumentVersionServiceError(
            "document_conflict", "The manual revision could not be created.", 409
        ) from None
    except SQLAlchemyError:
        raise DocumentVersionServiceError(
            "document_revision_failed",
            "Unable to upload the manual revision at this time.",
            503,
        ) from None
    finally:
        session.close()


def confirm_document_version(
    *,
    actor: User,
    project_id: str,
    document_id: str,
    expected_version: int,
    target_version_number: int,
) -> dict[str, Any]:
    """Confirm a draft version and archive any previously confirmed one.

    Admin / project-lead only. Only a ``draft`` version can be confirmed. The
    target becomes ``confirmed`` (stamped with the actor and time), every other
    previously confirmed version is moved to ``archived``, and the document
    becomes ``confirmed`` with its current version advanced to the target.
    """
    session = db.session()
    try:
        with session.begin():
            project = _load_project_for_update(session, project_id)
            _require_project_lead(actor, project)
            document = _load_document(session, project.id, document_id)
            if document is None:
                raise DocumentVersionServiceError(
                    "document_not_found", "Document was not found.", 404
                )
            _require_document_version(project, document, expected_version)

            target = _find_version(session, document.id, target_version_number)
            if target is None:
                raise DocumentVersionServiceError(
                    "version_not_found", "Document version was not found.", 404
                )
            if target.status != "draft":
                raise DocumentVersionServiceError(
                    "invalid_document_state",
                    "Only a draft version can be confirmed.",
                    409,
                )

            all_versions = list(
                session.scalars(
                    select(ProjectDocumentVersion).where(
                        ProjectDocumentVersion.document_id == document.id
                    )
                )
            )
            for version in all_versions:
                if version.id != target.id and version.status == "confirmed":
                    version.status = "archived"

            target.status = "confirmed"
            target.confirmed_by_user_id = actor.id
            target.confirmed_at = datetime.now(UTC)

            document.current_version_id = target.id
            document.status = "confirmed"
            document.version += 1
            record_event(
                session,
                actor,
                "project_document_version_confirmed",
                project,
                {
                    "document_id": document.id,
                    "version_id": target.id,
                    "version_number": target.version_number,
                },
            )
            session.flush()
            session.refresh(target)
            return _serialize_version(target) | {
                "project_version": project.version,
                "document_version": document.version,
            }
    except DocumentVersionServiceError:
        raise
    except IntegrityError:
        raise DocumentVersionServiceError(
            "document_conflict", "The document version could not be confirmed.", 409
        ) from None
    except SQLAlchemyError:
        raise DocumentVersionServiceError(
            "document_confirm_failed",
            "Unable to confirm the document version at this time.",
            503,
        ) from None
    finally:
        session.close()


def archive_document_version(
    *,
    actor: User,
    project_id: str,
    document_id: str,
    expected_version: int,
    target_version_number: int,
) -> dict[str, Any]:
    """Mark a draft or confirmed version as archived (admin / project-lead only).

    The current version may be archived deliberately: the document keeps the
    pointer so its bytes and history remain available, while its top-level
    status becomes ``archived`` and it no longer appears as an active output.
    """
    session = db.session()
    try:
        with session.begin():
            project = _load_project_for_update(session, project_id)
            _require_project_lead(actor, project)
            document = _load_document(session, project.id, document_id)
            if document is None:
                raise DocumentVersionServiceError(
                    "document_not_found", "业务文档不存在。", 404
                )
            _require_document_version(project, document, expected_version)

            target = _find_version(session, document.id, target_version_number)
            if target is None:
                raise DocumentVersionServiceError(
                    "version_not_found", "业务文档版本不存在。", 404
                )
            if target.status == "archived":
                return _serialize_version(target) | {
                    "project_version": project.version,
                    "document_version": document.version,
                }
            if target.status not in {"draft", "confirmed"}:
                raise DocumentVersionServiceError(
                    "invalid_document_state",
                    "只有草稿或已确认的业务文档版本可以标记为弃用。",
                    409,
                )

            target.status = "archived"
            remaining = max(
                (item for item in document.versions if item.status in {"draft", "confirmed"}),
                key=lambda item: item.version_number,
                default=None,
            )
            if remaining is None:
                document.current_version_id = target.id
                document.status = "archived"
            else:
                document.current_version_id = remaining.id
                document.status = remaining.status
            document.version += 1
            record_event(
                session,
                actor,
                "project_document_version_archived",
                project,
                {
                    "document_id": document.id,
                    "version_id": target.id,
                    "version_number": target.version_number,
                },
            )
            session.flush()
            session.refresh(target)
            return _serialize_version(target) | {
                "project_version": project.version,
                "document_version": document.version,
            }
    except DocumentVersionServiceError:
        raise
    except SQLAlchemyError:
        raise DocumentVersionServiceError(
            "document_archive_failed",
            "暂时无法标记该业务文档版本为弃用，请稍后重试。",
            503,
        ) from None
    finally:
        session.close()


def archive_all_document_versions(
    *, actor: User, project_id: str, document_id: str, expected_version: int
) -> dict[str, Any]:
    session = db.session()
    try:
        with session.begin():
            project = _load_project_for_update(session, project_id)
            _require_project_lead(actor, project)
            document = _load_document(session, project.id, document_id)
            if document is None:
                raise DocumentVersionServiceError("document_not_found", "业务文档不存在。", 404)
            _require_document_version(project, document, expected_version)
            changed = [item for item in document.versions if item.status in {"draft", "confirmed"}]
            for item in changed:
                item.status = "archived"
            latest = max(document.versions, key=lambda item: item.version_number, default=None)
            document.current_version_id = latest.id if latest is not None else None
            document.status = "archived"
            document.version += 1
            record_event(
                session, actor, "project_document_archived", project,
                {"document_id": document.id, "version_ids": [item.id for item in changed]},
            )
            session.flush()
            return {
                "document_id": document.id,
                "document_version": document.version,
                "archived_count": len(changed),
            }
    except DocumentVersionServiceError:
        raise
    except SQLAlchemyError:
        raise DocumentVersionServiceError(
            "document_archive_failed",
            "暂时无法标记该业务文档为弃用，请稍后重试。",
            503,
        ) from None
    finally:
        session.close()


def restore_latest_document_version(
    *, actor: User, project_id: str, document_id: str, expected_version: int
) -> dict[str, Any]:
    session = db.session()
    try:
        with session.begin():
            project = _load_project_for_update(session, project_id)
            _require_project_lead(actor, project)
            document = _load_document(session, project.id, document_id)
            if document is None:
                raise DocumentVersionServiceError("document_not_found", "业务文档不存在。", 404)
            _require_document_version(project, document, expected_version)
            target = max(
                (item for item in document.versions if item.status == "archived"),
                key=lambda item: item.version_number,
                default=None,
            )
            if target is None:
                raise DocumentVersionServiceError("invalid_document_state", "没有可恢复的弃用版本。", 409)
            for item in document.versions:
                if item.id != target.id and item.status == "confirmed":
                    item.status = "archived"
            target.status = "confirmed"
            document.current_version_id = target.id
            document.status = "confirmed"
            document.version += 1
            record_event(
                session, actor, "project_document_latest_version_restored", project,
                {"document_id": document.id, "version_id": target.id},
            )
            session.flush()
            return _serialize_version(target) | {
                "project_version": project.version,
                "document_version": document.version,
            }
    except DocumentVersionServiceError:
        raise
    except SQLAlchemyError:
        raise DocumentVersionServiceError(
            "document_restore_failed",
            "暂时无法恢复该业务文档，请稍后重试。",
            503,
        ) from None
    finally:
        session.close()


def restore_document_version(
    *, actor: User, project_id: str, document_id: str,
    expected_version: int, target_version_number: int,
) -> dict[str, Any]:
    session = db.session()
    try:
        with session.begin():
            project = _load_project_for_update(session, project_id)
            _require_project_lead(actor, project)
            document = _load_document(session, project.id, document_id)
            if document is None:
                raise DocumentVersionServiceError("document_not_found", "业务文档不存在。", 404)
            session.refresh(document)
            _require_document_version(project, document, expected_version)
            target = _find_version(session, document.id, target_version_number)
            if target is None:
                raise DocumentVersionServiceError("version_not_found", "业务文档版本不存在。", 404)
            session.refresh(target)
            if target.status == "confirmed":
                return _serialize_version(target) | {"project_version": project.version, "document_version": document.version}
            if target.status != "archived":
                raise DocumentVersionServiceError("invalid_document_state", "只有已弃用的业务文档版本可以恢复。", 409)
            for other in document.versions:
                if other.id != target.id and other.status == "confirmed":
                    other.status = "archived"
            target.status = "confirmed"
            document.current_version_id = target.id
            document.status = "confirmed"
            document.version += 1
            record_event(
                session, actor, "project_document_version_restored", project,
                {"document_id": document.id, "version_id": target.id, "version_number": target.version_number},
            )
            session.flush()
            session.refresh(target)
            return _serialize_version(target) | {"project_version": project.version, "document_version": document.version}
    except DocumentVersionServiceError:
        raise
    except SQLAlchemyError:
        raise DocumentVersionServiceError("document_restore_failed", "暂时无法恢复该业务文档版本，请稍后重试。", 503) from None
    finally:
        session.close()


def get_document_download_url(
    *, actor: User, project_id: str, document_id: str, version_number: int
) -> str:
    """Sign a short-lived download URL for an available version DOCX (view)."""
    session = db.session()
    try:
        project = _load_project_for_view(session, actor, project_id)
        document = _load_document(session, project.id, document_id)
        if document is None:
            raise DocumentVersionServiceError(
                "document_not_found", "Document was not found.", 404
            )
        version = _find_version(session, document.id, version_number)
        if version is None:
            raise DocumentVersionServiceError(
                "version_not_found", "Document version was not found.", 404
            )
        docx_file = _load_docx_file(session, version)
        if docx_file is None or not _is_downloadable(docx_file):
            raise DocumentVersionServiceError(
                "file_not_available", "The document version is not available.", 409
            )
        return object_storage.current.sign_download(
            docx_file.storage_key,
            docx_file.original_filename,
            expires_seconds=DOWNLOAD_EXPIRES_SECONDS,
        )
    finally:
        session.close()


def get_document_preview_url(
    *, actor: User, project_id: str, document_id: str, version_number: int
) -> str:
    """Sign a short-lived URL for a ready version preview (view)."""
    session = db.session()
    try:
        project = _load_project_for_view(session, actor, project_id)
        document = _load_document(session, project.id, document_id)
        if document is None:
            raise DocumentVersionServiceError(
                "document_not_found", "Document was not found.", 404
            )
        version = _find_version(session, document.id, version_number)
        if version is None:
            raise DocumentVersionServiceError(
                "version_not_found", "Document version was not found.", 404
            )
        docx_file = _load_docx_file(session, version)
        # The file-version pointer is authoritative because previews may be
        # regenerated independently. Older document rows can still reference a
        # superseded/colliding preview id from before preview keys were unique.
        preview_file_version_id = (
            docx_file.preview_version_id if docx_file is not None else None
        ) or version.preview_file_version_id
        if not preview_file_version_id:
            raise DocumentVersionServiceError(
                "preview_not_available", "The document preview is not available.", 409
            )
        preview_file = session.get(
            ProjectFileVersion, preview_file_version_id
        )
        if (
            preview_file is None
            or not preview_file.storage_key
            or docx_file is None
            or preview_file.parent_version_id != docx_file.id
            or preview_file.source != "preview"
            or preview_file.mime_type != "application/pdf"
        ):
            raise DocumentVersionServiceError(
                "preview_not_available", "The document preview is not available.", 409
            )
        try:
            object_storage.current.head(preview_file.storage_key)
        except Exception:  # noqa: BLE001 - any storage miss => no preview
            raise DocumentVersionServiceError(
                "preview_not_available", "The document preview is not available.", 409
            ) from None
        return object_storage.current.sign_download(
            preview_file.storage_key,
            preview_file.original_filename,
            expires_seconds=DOWNLOAD_EXPIRES_SECONDS,
        )
    finally:
        session.close()


def resolve_document_version(version_id: str) -> tuple[str, int]:
    """Resolve a version id to ``(document_id, version_number)`` (404 if missing)."""
    session = db.session()
    try:
        version = session.get(ProjectDocumentVersion, version_id)
        if version is None:
            raise DocumentVersionServiceError(
                "version_not_found", "Document version was not found.", 404
            )
        return version.document_id, version.version_number
    finally:
        session.close()


# ---------------------------------------------------------------------------
# Validation / helpers
# ---------------------------------------------------------------------------


def _validate_docx_bytes(docx_bytes: bytes) -> None:
    if not docx_bytes:
        raise DocumentVersionServiceError(
            "invalid_docx", "The uploaded revision is not a valid DOCX file.", 422
        )
    stream = io.BytesIO(docx_bytes)
    if not zipfile.is_zipfile(stream):
        raise DocumentVersionServiceError(
            "invalid_docx", "The uploaded revision is not a valid DOCX file.", 422
        )
    try:
        with zipfile.ZipFile(stream) as archive:
            if archive.testzip() is not None:
                raise DocumentVersionServiceError(
                    "invalid_docx", "The uploaded DOCX file is corrupted.", 422
                )
    except zipfile.BadZipFile:
        raise DocumentVersionServiceError(
            "invalid_docx", "The uploaded revision is not a valid DOCX file.", 422
        ) from None
    try:
        Document(io.BytesIO(docx_bytes))
    except Exception:  # noqa: BLE001 - python-docx rejects malformed documents
        raise DocumentVersionServiceError(
            "invalid_docx", "The uploaded revision is not a valid DOCX file.", 422
        ) from None


def _create_placeholder_docx(
    session: Session,
    project: Project,
    document: ProjectDocument,
    version_number: int,
    actor: User,
) -> ProjectFileVersion:
    filename = f"{document.business_code}-v{version_number}{DOCX_EXTENSION}"
    safe = safe_filename(filename)
    project_file = ProjectFile(
        project_id=project.id,
        category="document",
        display_name=filename,
        description="",
        created_by_user_id=actor.id,
    )
    session.add(project_file)
    session.flush()
    file_version = ProjectFileVersion(
        file_id=project_file.id,
        version_number=1,
        source="system_generated",
        original_filename=filename,
        safe_filename=safe,
        extension=extension_of(filename),
        mime_type=DOCX_MIME,
        bucket=_storage_bucket(),
        storage_key=(
            f"projects/{project.id}/documents/{document.id}/versions/"
            f"{version_number}/{safe}"
        ),
        size_bytes=0,
        sha256="",
        scan_status="not_required",
        preview_status="none",
        uploaded_by_user_id=actor.id,
        status="uploading",
    )
    session.add(file_version)
    session.flush()
    project_file.current_version_id = file_version.id
    return file_version


def _empty_content_snapshot() -> dict[str, Any]:
    return {key: {} for key in _CONTENT_SNAPSHOT_KEYS}


def _next_document_version_number(session: Session, document_id: str) -> int:
    current = session.scalar(
        select(func.max(ProjectDocumentVersion.version_number)).where(
            ProjectDocumentVersion.document_id == document_id
        )
    )
    return int(current or 0) + 1


def _is_downloadable(file_version: ProjectFileVersion) -> bool:
    return (
        file_version.status == "available"
        and file_version.scan_status in _DOWNLOADABLE_SCAN_STATUSES
    )


def _storage_bucket() -> str:
    storage = object_storage.current
    bucket = getattr(storage, "bucket_name", None)
    return bucket or "local"


# ---------------------------------------------------------------------------
# Loading / permission helpers
# ---------------------------------------------------------------------------


def _load_project_for_update(session: Session, project_id: str) -> Project:
    return _require_project_view(
        session.scalar(
            select(Project)
            .options(
                selectinload(Project.members).selectinload(ProjectMember.user),
                selectinload(Project.leader),
            )
            .where(Project.id == project_id)
            .with_for_update()
        )
    )


def _load_project_for_view(session: Session, actor: User, project_id: str) -> Project:
    project = session.scalar(
        select(Project)
        .options(
            selectinload(Project.members).selectinload(ProjectMember.user),
            selectinload(Project.leader),
        )
        .where(Project.id == project_id)
    )
    if project is None:
        raise DocumentVersionServiceError(
            "project_not_found", "Project was not found.", 404
        )
    if not project_access(actor, project).can_view:
        raise DocumentVersionServiceError(
            "forbidden", "You do not have permission to access this project.", 403
        )
    return project


def _require_project_view(project: Project | None) -> Project:
    if project is None:
        raise DocumentVersionServiceError("project_not_found", "Project was not found.", 404)
    return project


def _require_document_editor(actor: User, project: Project) -> Project:
    access = project_access(actor, project)
    if not (access.can_manage or access.can_update_assigned_tasks):
        raise DocumentVersionServiceError(
            "forbidden",
            "You do not have permission to edit documents in this project.",
            403,
        )
    return project


def _require_project_lead(actor: User, project: Project) -> Project:
    if not project_access(actor, project).can_manage:
        raise DocumentVersionServiceError(
            "forbidden",
            "You do not have permission to confirm or archive documents.",
            403,
        )
    return project


def _require_document_version(
    project: Project, document: ProjectDocument, expected_version: int
) -> None:
    if type(expected_version) is not int or expected_version < 1:
        raise DocumentVersionServiceError(
            "invalid_request", "A valid document version is required.", 400
        )
    if document.version != expected_version:
        raise DocumentVersionServiceError(
            "stale_version", "The document has been updated. Refresh and try again.", 409
        )


def _load_document(session: Session, project_id: str, document_id: str):
    return session.scalar(
        select(ProjectDocument)
        .options(
            selectinload(ProjectDocument.current_version),
            selectinload(ProjectDocument.draft),
            selectinload(ProjectDocument.owner),
            selectinload(ProjectDocument.versions),
        )
        .where(
            ProjectDocument.id == document_id,
            ProjectDocument.project_id == project_id,
        )
    )


def _find_version(
    session: Session, document_id: str, version_number: int
) -> ProjectDocumentVersion | None:
    return session.scalar(
        select(ProjectDocumentVersion)
        .options(
            selectinload(ProjectDocumentVersion.docx_file),
            selectinload(ProjectDocumentVersion.preview_file),
            selectinload(ProjectDocumentVersion.generated_by),
            selectinload(ProjectDocumentVersion.confirmed_by),
        )
        .where(
            ProjectDocumentVersion.document_id == document_id,
            ProjectDocumentVersion.version_number == version_number,
        )
    )


def _load_docx_file(
    session: Session, version: ProjectDocumentVersion
) -> ProjectFileVersion | None:
    if not version.docx_file_version_id:
        return None
    return session.get(ProjectFileVersion, version.docx_file_version_id)


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------


def _serialize_version(version: ProjectDocumentVersion) -> dict[str, Any]:
    from fde_api.documents.draft_service import _generation_status
    docx_file = version.docx_file
    return {
        **_generation_status(version),
        "id": version.id,
        "document_id": version.document_id,
        "version_number": version.version_number,
        "source": version.source,
        "status": version.status,
        "parent_version_id": version.parent_version_id,
        "source_template_version_id": version.source_template_version_id,
        "source_snapshot_json": version.source_snapshot_json,
        "content_snapshot_json": version.content_snapshot_json,
        "docx_file_version_id": version.docx_file_version_id,
        "preview_file_version_id": version.preview_file_version_id or (
            docx_file.preview_version_id if docx_file is not None else None
        ),
        "preview_status": (
            docx_file.preview_status if docx_file is not None else "none"
        ),
        "sha256": version.sha256,
        "download_url": _signed_download(docx_file),
        "generated_by": (
            _serialize_user(version.generated_by)
            if version.generated_by is not None
            else None
        ),
        "confirmed_by": (
            _serialize_user(version.confirmed_by)
            if version.confirmed_by is not None
            else None
        ),
        "confirmed_at": (
            version.confirmed_at.isoformat() if version.confirmed_at is not None else None
        ),
        "created_at": version.created_at.isoformat(),
        "updated_at": version.updated_at.isoformat(),
    }


def _serialize_version_report(version: ProjectDocumentVersion) -> dict[str, Any]:
    from fde_api.documents.draft_service import _generation_status
    docx_file = version.docx_file
    return {
        **_generation_status(version),
        "id": version.id,
        "document_id": version.document_id,
        "version_number": version.version_number,
        "source": version.source,
        "status": version.status,
        "parent_version_id": version.parent_version_id,
        "docx_file_version_id": version.docx_file_version_id,
        "preview_file_version_id": version.preview_file_version_id or (
            docx_file.preview_version_id if docx_file is not None else None
        ),
        "preview_status": (
            docx_file.preview_status if docx_file is not None else "none"
        ),
        "sha256": version.sha256,
        "download_url": _signed_download(docx_file),
        "generated_by": (
            _serialize_user(version.generated_by)
            if version.generated_by is not None
            else None
        ),
        "confirmed_by": (
            _serialize_user(version.confirmed_by)
            if version.confirmed_by is not None
            else None
        ),
        "confirmed_at": (
            version.confirmed_at.isoformat() if version.confirmed_at is not None else None
        ),
        "created_at": version.created_at.isoformat(),
        "updated_at": version.updated_at.isoformat(),
    }


def _signed_download(docx_file: ProjectFileVersion | None) -> str | None:
    if docx_file is None or not _is_downloadable(docx_file):
        return None
    try:
        return object_storage.current.sign_download(
            docx_file.storage_key,
            docx_file.original_filename,
            expires_seconds=DOWNLOAD_EXPIRES_SECONDS,
        )
    except Exception:  # noqa: BLE001 - signed URL is best-effort in a listing
        return None


def _serialize_user(user: User) -> dict[str, Any]:
    return {
        "id": user.id,
        "display_name": user.display_name,
    }
