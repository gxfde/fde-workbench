"""project-scoped file upload service: multipart upload session lifecycle.

The service owns the multipart upload conversation between the client and the
object storage adapter, and promotes a completed upload into an immutable
``ProjectFile`` + ``ProjectFileVersion`` pair. Files in the internal workbench
become available immediately after storage confirms the multipart upload.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session, selectinload

from fde_api.auth.models import User
from fde_api.extensions import db, object_storage
from fde_api.files.models import (
    BUSINESS_CATEGORIES,
    BUSINESS_CATEGORY_UNCATEGORIZED_LABEL,
    ProjectFile,
    ProjectFileVersion,
    UploadSession,
)
from fde_api.files.names import (
    FileNameError,
    extension_of,
    safe_filename,
    temporary_key,
)
from fde_api.jobs.outbox import enqueue_outbox
from fde_api.projects.events import record_event
from fde_api.projects.permissions import project_access
from fde_api.storage.base import StorageError, UploadedPart, normalize_parts
from fde_api.workbench.models import Project, ProjectMember

PART_SIZE = 5 * 1024 * 1024  # 5 MB
MAX_FILE_SIZE_BYTES = 100 * 1024 * 1024  # 100 MB
PART_URL_EXPIRES_SECONDS = 300  # 5 minutes
UPLOAD_SESSION_TTL_HOURS = 1
FILE_CATEGORIES = ("attachment", "document")


class FileServiceError(Exception):
    """A stable, user-facing file subsystem failure."""

    def __init__(self, code: str, message: str, status: int):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


def create_upload_session(
    *, actor: User, project_id: str, input: Mapping[str, Any]
) -> dict[str, Any]:
    """Begin a multipart upload session, honoring idempotency by key."""
    values = _normalize_upload_input(input)
    session = db.session()
    try:
        with session.begin():
            project = _get_project_for_upload(session, actor, project_id)
            existing = session.scalar(
                select(UploadSession).where(
                    UploadSession.project_id == project.id,
                    UploadSession.idempotency_key == values["idempotency_key"],
                )
            )
            if existing is not None:
                return _serialize_upload_session(existing)

            upload_id = str(uuid4())
            content_type = values["mime_type"] or "application/octet-stream"
            temp_key = temporary_key(project.id, upload_id, values["name"])
            multipart = object_storage.current.begin_multipart(
                temp_key, content_type
            )
            upload_session = UploadSession(
                project_id=project.id,
                file_id=values["file_id"],
                name=values["name"],
                expected_size_bytes=values["size_bytes"],
                expected_mime_type=values["mime_type"],
                bucket=_storage_bucket(),
                storage_prefix=temp_key,
                multipart_upload_id=multipart.upload_id,
                expires_at=datetime.now(UTC)
                + timedelta(hours=UPLOAD_SESSION_TTL_HOURS),
                status="uploading",
                requested_by_user_id=actor.id,
                idempotency_key=values["idempotency_key"],
                completion_json={
                    "category": values["category"],
                    "business_category": values["business_category"],
                    "display_name": values["display_name"],
                },
            )
            session.add(upload_session)
            session.flush()
            return _serialize_upload_session(upload_session)
    except FileServiceError:
        raise
    except StorageError as error:
        raise FileServiceError(error.code, "Object storage error.", 400) from None
    finally:
        session.close()


def sign_upload_part(
    *, actor: User, project_id: str, session_id: str, part_number: int
) -> dict[str, Any]:
    """Return a signed PUT URL for one part of an active upload session."""
    session = db.session()
    try:
        with session.begin():
            project = _get_project_for_upload(session, actor, project_id)
            upload_session = _load_upload_session(
                session, project.id, session_id
            )
            if upload_session.status != "uploading":
                raise FileServiceError(
                    "invalid_upload_state",
                    "The upload session is not accepting parts.",
                    409,
                )
            url = object_storage.current.sign_part(
                upload_session.storage_prefix,
                upload_session.multipart_upload_id,
                part_number,
            )
            return {
                "url": url,
                "part_number": part_number,
                "expires_seconds": PART_URL_EXPIRES_SECONDS,
            }
    except FileServiceError:
        raise
    except StorageError as error:
        raise FileServiceError(error.code, "Object storage error.", 400) from None
    finally:
        session.close()


def complete_upload(
    *, actor: User, project_id: str, session_id: str, parts: list[Mapping[str, Any]]
) -> dict[str, Any]:
    """Promote a completed multipart upload into an immutable file version.

    Idempotent: completing a session that has already been completed returns the
    originally created version without touching storage again.
    """
    session = db.session()
    try:
        with session.begin():
            project = _get_project_for_upload(session, actor, project_id)
            upload_session = _load_upload_session(
                session, project.id, session_id
            )
            category = upload_session.completion_json.get("category", "attachment")
            business_category = upload_session.completion_json.get("business_category")

            replay = _completed_replay(upload_session)
            if replay is not None:
                return replay

            if upload_session.status != "uploading":
                raise FileServiceError(
                    "invalid_upload_state",
                    "The upload session is not accepting completion.",
                    409,
                )

            normalized_parts = _normalize_part_input(parts)
            stored = object_storage.current.complete_multipart(
                upload_session.storage_prefix,
                upload_session.multipart_upload_id,
                normalized_parts,
            )

            project_file = _resolve_or_create_file(
                session, upload_session, project.id, category, business_category, actor
            )
            version_number = _next_version_number(session, project_file.id)
            safe = safe_filename(upload_session.name)
            version = ProjectFileVersion(
                file_id=project_file.id,
                version_number=version_number,
                source="upload",
                original_filename=upload_session.name,
                safe_filename=safe,
                extension=extension_of(upload_session.name),
                mime_type=upload_session.expected_mime_type,
                bucket=upload_session.bucket,
                storage_key=upload_session.storage_prefix,
                size_bytes=stored.size or upload_session.expected_size_bytes,
                etag=stored.etag,
                scan_status="not_required",
                preview_status="none",
                uploaded_by_user_id=actor.id,
                status="available",
            )
            session.add(version)
            session.flush()
            if (
                project_file.display_name == "预调研表"
                and project_file.business_category == "预调研"
            ):
                _deprecate_previous_presurvey_versions(
                    session,
                    project_file=project_file,
                    keep_version_id=version.id,
                    actor=actor,
                )
            project_file.current_version_id = version.id
            session.flush()

            upload_session.status = "completed"
            upload_session.completion_json = {
                "version_id": version.id,
                "file_id": project_file.id,
                "category": category,
                "business_category": business_category,
                "status": "available",
                "scan_status": version.scan_status,
            }
            record_event(
                session,
                actor,
                "project_file_uploaded",
                project_file,
                {
                    "file_id": project_file.id,
                    "version_id": version.id,
                    "version_number": version_number,
                    "size_bytes": version.size_bytes,
                    "category": category,
                    "business_category": business_category,
                },
            )
            enqueue_outbox(
                session,
                "file.preview",
                version.id,
                {"version_id": version.id},
            )
            return {
                "version_id": version.id,
                "file_id": project_file.id,
                "status": "available",
                "scan_status": version.scan_status,
            }
    except FileServiceError:
        raise
    except StorageError:
        raise FileServiceError(
            "invalid_parts", "The uploaded parts are invalid.", 422
        ) from None
    finally:
        session.close()


def abort_upload(
    *, actor: User, project_id: str, session_id: str
) -> None:
    """Abort an in-progress multipart upload, freeing its storage parts."""
    session = db.session()
    try:
        with session.begin():
            project = _get_project_for_upload(session, actor, project_id)
            upload_session = _load_upload_session(
                session, project.id, session_id
            )
            if upload_session.status == "uploading":
                object_storage.current.abort_multipart(
                    upload_session.storage_prefix,
                    upload_session.multipart_upload_id,
                )
                upload_session.status = "aborted"
    except FileServiceError:
        raise
    except StorageError as error:
        raise FileServiceError(error.code, "Object storage error.", 400) from None
    finally:
        session.close()


def _deprecate_previous_presurvey_versions(
    session: Session,
    *,
    project_file: ProjectFile,
    keep_version_id: str,
    actor: User,
) -> None:
    """Keep exactly one active version for the project's pre-survey form.

    A new pre-survey upload is already durable at this point, so older versions
    can be deprecated in the same transaction.  This is deliberately enforced
    on the server instead of relying on the desktop client to issue a series of
    best-effort mutations.
    """
    deprecated_at = datetime.now(UTC)
    previous = session.scalars(
        select(ProjectFileVersion)
        .join(ProjectFile, ProjectFileVersion.file_id == ProjectFile.id)
        .where(
            ProjectFile.project_id == project_file.project_id,
            ProjectFile.display_name == "预调研表",
            ProjectFile.business_category == "预调研",
            ProjectFileVersion.id != keep_version_id,
            ProjectFileVersion.status == "available",
        )
    ).all()
    for old_version in previous:
        old_version.status = "deprecated"
        old_version.deprecated_by_user_id = actor.id
        old_version.deprecated_at = deprecated_at
        old_version.deprecation_reason = "已上传新的预调研表版本"


def list_project_files(
    *, actor: User, project_id: str, business_category: str | None = None
) -> list[dict[str, Any]]:
    """Return a minimal summary of the project's files with their current version.

    ``business_category`` optionally filters to one business stage; the literal
    ``未分类`` token (``BUSINESS_CATEGORY_UNCATEGORIZED_LABEL``) selects items
    that are not assigned a business stage.
    """
    session = db.session()
    try:
        project = _get_project_viewable(session, actor, project_id)
        query = (
            select(ProjectFile)
            .options(
                selectinload(ProjectFile.current_version),
                selectinload(ProjectFile.created_by),
                selectinload(ProjectFile.versions).selectinload(ProjectFileVersion.uploaded_by),
                selectinload(ProjectFile.versions).selectinload(ProjectFileVersion.deprecated_by),
            )
            .where(ProjectFile.project_id == project.id)
        )
        if business_category is not None:
            query = _apply_business_category_filter(query, business_category)
        files = session.scalars(
            query.order_by(ProjectFile.created_at.desc(), ProjectFile.id)
        ).all()
        from fde_api.research.models import ProjectResearchExport

        latest_exports: dict[str, ProjectResearchExport] = {}
        if files:
            exports = session.scalars(
                select(ProjectResearchExport)
                .where(ProjectResearchExport.project_file_id.in_([file.id for file in files]))
                .order_by(ProjectResearchExport.created_at.desc())
            ).all()
            for export in exports:
                if export.project_file_id:
                    latest_exports.setdefault(export.project_file_id, export)
        return [_serialize_file(file, latest_exports.get(file.id)) for file in files]
    finally:
        session.close()


def rename_project_file(
    *, actor: User, project_id: str, file_id: str, name: object
) -> dict[str, Any]:
    normalized = _normalize_display_name(name, "")
    session = db.session()
    try:
        with session.begin():
            project = _get_project_for_upload(session, actor, project_id)
            project_file = session.scalar(
                select(ProjectFile)
                .options(
                    selectinload(ProjectFile.current_version),
                    selectinload(ProjectFile.created_by),
                    selectinload(ProjectFile.versions).selectinload(ProjectFileVersion.uploaded_by),
                    selectinload(ProjectFile.versions).selectinload(ProjectFileVersion.deprecated_by),
                )
                .where(ProjectFile.id == file_id, ProjectFile.project_id == project.id)
                .with_for_update()
            )
            if project_file is None:
                raise FileServiceError("project_file_not_found", "文件不存在。", 404)
            if project_file.display_name == normalized:
                return _serialize_file(project_file)
            old_name = project_file.display_name
            project_file.display_name = normalized
            project_file.version += 1
            record_event(
                session,
                actor,
                "project_file_renamed",
                project_file,
                {"file_id": project_file.id, "old_name": old_name, "new_name": normalized},
            )
            session.flush()
            return _serialize_file(project_file)
    except FileServiceError:
        raise
    except IntegrityError:
        raise FileServiceError("file_name_conflict", "项目中已存在同名文件。", 409) from None
    except SQLAlchemyError:
        raise FileServiceError("file_rename_failed", "文件重命名失败，请稍后重试。", 503) from None
    finally:
        session.close()


def list_file_versions(*, actor: User, project_id: str, file_id: str) -> list[dict[str, Any]]:
    session = db.session()
    try:
        project = _get_project_viewable(session, actor, project_id)
        project_file = session.scalar(
            select(ProjectFile).where(
                ProjectFile.id == file_id, ProjectFile.project_id == project.id
            )
        )
        if project_file is None:
            raise FileServiceError("project_file_not_found", "文件不存在。", 404)
        versions = session.scalars(
            select(ProjectFileVersion)
            .options(
                selectinload(ProjectFileVersion.uploaded_by),
                selectinload(ProjectFileVersion.deprecated_by),
            )
            .where(
                ProjectFileVersion.file_id == project_file.id,
                ProjectFileVersion.source != "preview",
            )
            .order_by(ProjectFileVersion.version_number.desc())
        ).all()
        return [_serialize_version(version) for version in versions]
    finally:
        session.close()


def deprecate_file_version(
    *, actor: User, project_id: str, version_id: str, reason: str = ""
) -> dict[str, Any]:
    session = db.session()
    try:
        with session.begin():
            project = _get_project_for_upload(session, actor, project_id)
            version = session.scalar(
                select(ProjectFileVersion)
                .options(selectinload(ProjectFileVersion.project_file))
                .where(ProjectFileVersion.id == version_id)
                .with_for_update()
            )
            if version is None or version.project_file.project_id != project.id:
                raise FileServiceError("file_version_not_found", "文件版本不存在。", 404)
            if version.source == "preview":
                raise FileServiceError("file_version_not_found", "文件版本不存在。", 404)
            if version.status == "deprecated":
                return _serialize_version(version)
            if version.status != "available":
                raise FileServiceError("file_version_not_available", "只有可用版本可以标记为弃用。", 409)
            version.status = "deprecated"
            version.deprecated_by_user_id = actor.id
            version.deprecated_at = datetime.now(UTC)
            version.deprecation_reason = reason.strip()[:500]
            project_file = version.project_file
            replacement = _available_file_version(
                session, project_file=project_file, exclude_version_id=version.id
            )
            if project_file.current_version_id == version.id:
                project_file.current_version_id = replacement.id if replacement else None
                project_file.version += 1
            # Deprecating a source file version must not delete or supersede a
            # confirmed project guidance analysis. Point the active pre-survey
            # source at the best remaining version and let the guidance become
            # visibly stale until the replacement is analyzed and confirmed.
            from fde_api.guidance.models import ProjectPresurveySource
            presurvey_source = session.get(ProjectPresurveySource, project.id)
            if presurvey_source is not None and presurvey_source.current_file_version_id == version.id:
                if replacement is None:
                    session.delete(presurvey_source)
                else:
                    presurvey_source.project_file_id = replacement.file_id
                    presurvey_source.current_file_version_id = replacement.id
                    presurvey_source.version += 1
            record_event(
                session, actor, "project_file_version_deprecated", project_file,
                {"file_id": project_file.id, "version_id": version.id, "reason": version.deprecation_reason},
            )
            session.flush()
            return _serialize_version(version)
    finally:
        session.close()


def _available_file_version(
    session: Session, *, project_file: ProjectFile, exclude_version_id: str
) -> ProjectFileVersion | None:
    current = (
        session.get(ProjectFileVersion, project_file.current_version_id)
        if project_file.current_version_id and project_file.current_version_id != exclude_version_id
        else None
    )
    if current is not None and current.status == "available" and current.source != "preview":
        return current
    return session.scalar(
        select(ProjectFileVersion)
        .where(
            ProjectFileVersion.file_id == project_file.id,
            ProjectFileVersion.id != exclude_version_id,
            ProjectFileVersion.status == "available",
            ProjectFileVersion.source != "preview",
        )
        .order_by(ProjectFileVersion.version_number.desc())
        .limit(1)
    )


def restore_file_version(*, actor: User, project_id: str, version_id: str) -> dict[str, Any]:
    session = db.session()
    try:
        with session.begin():
            project = _get_project_for_upload(session, actor, project_id)
            version = session.scalar(
                select(ProjectFileVersion)
                .options(selectinload(ProjectFileVersion.project_file))
                .where(ProjectFileVersion.id == version_id)
                .with_for_update()
            )
            if version is None or version.project_file.project_id != project.id:
                raise FileServiceError("file_version_not_found", "文件版本不存在。", 404)
            if version.source == "preview":
                raise FileServiceError("file_version_not_found", "文件版本不存在。", 404)
            if version.status == "available":
                return _serialize_version(version)
            if version.status != "deprecated":
                raise FileServiceError("file_version_not_restorable", "只有已弃用的文件版本可以恢复。", 409)
            version.status = "available"
            version.deprecated_by_user_id = None
            version.deprecated_at = None
            version.deprecation_reason = ""
            project_file = version.project_file
            current = session.get(ProjectFileVersion, project_file.current_version_id) if project_file.current_version_id else None
            if current is None or version.version_number >= current.version_number:
                project_file.current_version_id = version.id
            project_file.status = "active"
            project_file.version += 1
            record_event(
                session, actor, "project_file_version_restored", project_file,
                {"file_id": project_file.id, "version_id": version.id},
            )
            session.flush()
            return _serialize_version(version)
    finally:
        session.close()


def deprecate_project_file(
    *, actor: User, project_id: str, file_id: str, reason: str = "", expected_version: int | None = None
) -> dict[str, Any]:
    """Deprecate every user-visible available version in one file identity."""
    session = db.session()
    try:
        with session.begin():
            project = _get_project_for_upload(session, actor, project_id)
            project_file = session.scalar(
                select(ProjectFile)
                .options(selectinload(ProjectFile.versions))
                .where(ProjectFile.id == file_id, ProjectFile.project_id == project.id)
                .with_for_update()
            )
            if project_file is None:
                raise FileServiceError("project_file_not_found", "文件不存在。", 404)
            if expected_version is not None and project_file.version != expected_version:
                raise FileServiceError("stale_version", "文件已经变化，请重新确认。", 409)
            changed_at = datetime.now(UTC)
            for version in project_file.versions:
                if version.source != "preview" and version.status == "available":
                    version.status = "deprecated"
                    version.deprecated_by_user_id = actor.id
                    version.deprecated_at = changed_at
                    version.deprecation_reason = reason.strip()[:500]
            project_file.current_version_id = None
            project_file.status = "archived"
            project_file.version += 1
            from fde_api.guidance.models import ProjectPresurveySource
            source = session.get(ProjectPresurveySource, project.id)
            if source is not None and source.project_file_id == project_file.id:
                session.delete(source)
            record_event(
                session, actor, "project_file_deprecated", project_file,
                {"file_id": project_file.id, "reason": reason.strip()[:500]},
            )
            session.flush()
            return _serialize_file(project_file)
    finally:
        session.close()


def restore_latest_project_file_version(
    *, actor: User, project_id: str, file_id: str
) -> dict[str, Any]:
    """Restore only the newest deprecated user-visible version of a file."""
    session = db.session()
    try:
        with session.begin():
            project = _get_project_for_upload(session, actor, project_id)
            project_file = session.scalar(
                select(ProjectFile)
                .options(selectinload(ProjectFile.versions))
                .where(ProjectFile.id == file_id, ProjectFile.project_id == project.id)
                .with_for_update()
            )
            if project_file is None:
                raise FileServiceError("project_file_not_found", "文件不存在。", 404)
            target = max(
                (
                    version for version in project_file.versions
                    if version.source != "preview" and version.status == "deprecated"
                ),
                key=lambda version: version.version_number,
                default=None,
            )
            if target is None:
                raise FileServiceError("file_version_not_restorable", "没有可恢复的弃用版本。", 409)
            target.status = "available"
            target.deprecated_by_user_id = None
            target.deprecated_at = None
            target.deprecation_reason = ""
            project_file.current_version_id = target.id
            project_file.status = "active"
            project_file.version += 1
            record_event(
                session, actor, "project_file_latest_version_restored", project_file,
                {"file_id": project_file.id, "version_id": target.id},
            )
            session.flush()
            return _serialize_file(project_file)
    finally:
        session.close()


def _normalize_upload_input(input: Mapping[str, Any]) -> dict[str, Any]:
    name = input.get("name")
    if not isinstance(name, str) or not name:
        raise FileServiceError(
            "file_name_invalid", "A file name is required.", 422
        )
    size_bytes = input.get("size_bytes")
    if type(size_bytes) is not int or size_bytes <= 0:
        raise FileServiceError(
            "invalid_request", "文件大小必须大于 0。", 400
        )
    if size_bytes > MAX_FILE_SIZE_BYTES:
        raise FileServiceError(
            "file_too_large", "单个文件不能超过 100MB。", 422
        )
    category = input.get("category", "attachment")
    if category not in FILE_CATEGORIES:
        raise FileServiceError(
            "invalid_request", "category is invalid.", 400
        )
    business_category = _normalize_business_category(input.get("business_category"))
    mime_type = input.get("mime_type", "")
    if not isinstance(mime_type, str):
        mime_type = ""
    idempotency_key = input.get("idempotency_key")
    if not isinstance(idempotency_key, str) or not idempotency_key:
        raise FileServiceError(
            "invalid_request", "An idempotency key is required.", 400
        )
    file_id = input.get("file_id")
    if file_id is not None and not isinstance(file_id, str):
        raise FileServiceError("invalid_request", "file_id is invalid.", 400)

    try:
        safe_filename(name)
    except FileNameError as error:
        code = (
            "file_type_not_allowed"
            if error.code == "file_type_not_allowed"
            else "file_name_invalid"
        )
        raise FileServiceError(
            code,
            "不允许上传可执行文件或脚本文件。"
            if code == "file_type_not_allowed"
            else "文件名不合法。",
            422,
        ) from None
    return {
        "name": name,
        "display_name": _normalize_display_name(input.get("display_name"), name),
        "size_bytes": size_bytes,
        "category": category,
        "business_category": business_category,
        "mime_type": mime_type,
        "idempotency_key": idempotency_key,
        "file_id": file_id,
    }


def _normalize_display_name(value: Any, filename: str) -> str:
    if value is None:
        value = filename.rsplit(".", 1)[0]
    if not isinstance(value, str) or not value.strip():
        raise FileServiceError("file_display_name_invalid", "请填写文件名称。", 422)
    normalized = value.strip()
    if len(normalized) > 255:
        raise FileServiceError("file_display_name_invalid", "文件名称不能超过 255 个字符。", 422)
    return normalized


def _normalize_business_category(value: Any) -> str | None:
    """Return a storable business category or ``None`` for uncategorized.

    ``None``/empty/``未分类`` all map to the uncategorized ``NULL`` column value
    so the API is forgiving on input while the database stays canonical.
    """
    if value is None:
        return None
    if isinstance(value, str) and value == "":
        return None
    if value in BUSINESS_CATEGORIES:
        return value
    raise FileServiceError(
        "invalid_business_category",
        "The business category is not supported.",
        400,
    )


def _apply_business_category_filter(query, business_category: str):
    """Restrict a ``ProjectFile`` select to one business stage or uncategorized.

    The literal ``未分类`` token selects items whose ``business_category`` is
    ``NULL`` (uncategorized); any of the six stage names matches exactly.
    """
    if business_category == BUSINESS_CATEGORY_UNCATEGORIZED_LABEL:
        return query.where(
            ProjectFile.business_category.is_(None)
            | (ProjectFile.business_category == "")
        )
    if business_category not in BUSINESS_CATEGORIES:
        raise FileServiceError(
            "invalid_business_category",
            "The business category is not supported.",
            400,
        )
    return query.where(ProjectFile.business_category == business_category)


def _normalize_part_input(
    parts: list[Mapping[str, Any]],
) -> list[UploadedPart]:
    if not isinstance(parts, list) or not parts:
        raise FileServiceError(
            "invalid_parts", "At least one uploaded part is required.", 422
        )
    normalized: list[UploadedPart] = []
    for part in parts:
        if (
            not isinstance(part, Mapping)
            or "part_number" not in part
            or "etag" not in part
        ):
            raise FileServiceError(
                "invalid_parts", "Uploaded parts are invalid.", 422
            )
        normalized.append(UploadedPart(part["part_number"], part["etag"]))
    return normalize_parts(normalized)


def _resolve_or_create_file(
    session,
    upload_session: UploadSession,
    project_id: str,
    category: str,
    business_category: str | None,
    actor: User,
) -> ProjectFile:
    if upload_session.file_id is not None:
        project_file = session.get(ProjectFile, upload_session.file_id)
        if project_file is None or project_file.project_id != project_id:
            raise FileServiceError(
                "project_file_not_found",
                "The target file was not found.",
                404,
            )
        if business_category is not None:
            project_file.business_category = business_category
        return project_file
    project_file = ProjectFile(
        project_id=project_id,
        category=category,
        business_category=business_category,
        display_name=upload_session.completion_json.get("display_name") or upload_session.name.rsplit(".", 1)[0],
        description="",
        created_by_user_id=actor.id,
    )
    session.add(project_file)
    session.flush()
    return project_file


def _next_version_number(session, file_id: str) -> int:
    current = session.scalar(
        select(func.max(ProjectFileVersion.version_number)).where(
            ProjectFileVersion.file_id == file_id,
            ProjectFileVersion.source != "preview",
        )
    )
    return int(current or 0) + 1


def create_direct_file_version(
    session,
    project_id: str,
    document_id: str,
    storage_key: str,
    filename: str,
    mime: str,
    sha256: str,
    actor: User,
    *,
    size_bytes: int = 0,
    etag: str = "",
    file_id: str | None = None,
    display_name: str | None = None,
) -> ProjectFileVersion:
    """Create an immutable, immediately-available document file version.

    Manual document revisions push bytes straight to object storage and promote
    them in one transaction. ``document_id`` is accepted for traceability; the
    ``storage_key`` already encodes it. The returned version is ``available``
    with ``scan_status`` "not_required", so it is downloadable immediately.
    Each call allocates a fresh ``ProjectFile``, never reusing (or overwriting)
    an existing object.
    """
    safe = safe_filename(filename)
    project_file = session.get(ProjectFile, file_id) if file_id else None
    if project_file is not None and project_file.project_id != project_id:
        raise FileServiceError("project_file_not_found", "文件条目不存在。", 404)
    if project_file is None:
        project_file = ProjectFile(
            project_id=project_id,
            category="document",
            display_name=display_name or filename.rsplit(".", 1)[0],
            description="",
            created_by_user_id=actor.id,
        )
        session.add(project_file)
        session.flush()
    version_number = _next_version_number(session, project_file.id)
    file_version = ProjectFileVersion(
        file_id=project_file.id,
        version_number=version_number,
        source="manual_upload",
        original_filename=filename,
        safe_filename=safe,
        extension=extension_of(filename),
        mime_type=mime,
        bucket=_storage_bucket(),
        storage_key=storage_key,
        size_bytes=size_bytes,
        etag=etag,
        sha256=sha256,
        scan_status="not_required",
        preview_status="none",
        uploaded_by_user_id=actor.id,
        status="available",
    )
    session.add(file_version)
    session.flush()
    project_file.current_version_id = file_version.id
    return file_version


def _completed_replay(upload_session: UploadSession) -> dict[str, Any] | None:
    if upload_session.status != "completed":
        return None
    stored = upload_session.completion_json
    if not isinstance(stored, dict) or not stored.get("version_id"):
        return None
    return {
        "version_id": stored["version_id"],
        "file_id": stored.get("file_id"),
        "status": stored.get("status", "uploading"),
        "scan_status": stored.get("scan_status", "pending"),
    }


def _get_project_for_upload(
    session, actor: User, project_id: str
) -> Project:
    project = _load_project_with_members(session, project_id)
    if project is None:
        raise FileServiceError("project_not_found", "Project was not found.", 404)
    if not project_access(actor, project).can_manage:
        raise FileServiceError(
            "forbidden",
            "You do not have permission to manage files in this project.",
            403,
        )
    return project


def _get_project_viewable(session, actor: User, project_id: str) -> Project:
    project = _load_project_with_members(session, project_id)
    if project is None or not project_access(actor, project).can_view:
        raise FileServiceError("project_not_found", "Project was not found.", 404)
    return project


def _load_project_with_members(session, project_id: str) -> Project | None:
    return session.scalar(
        select(Project)
        .options(
            selectinload(Project.members).selectinload(ProjectMember.user),
            selectinload(Project.leader),
        )
        .where(Project.id == project_id)
    )


def _load_upload_session(
    session, project_id: str, session_id: str
) -> UploadSession:
    upload_session = session.scalar(
        select(UploadSession).where(
            UploadSession.id == session_id,
            UploadSession.project_id == project_id,
        )
    )
    if upload_session is None:
        raise FileServiceError(
            "upload_session_not_found", "Upload session was not found.", 404
        )
    return upload_session


def _storage_bucket() -> str:
    storage = object_storage.current
    bucket = getattr(storage, "bucket_name", None)
    return bucket or "local"


def _serialize_upload_session(
    upload_session: UploadSession,
) -> dict[str, Any]:
    return {
        "id": upload_session.id,
        "project_id": upload_session.project_id,
        "name": upload_session.name,
        "category": upload_session.completion_json.get("category", "attachment"),
        "business_category": upload_session.completion_json.get("business_category"),
        "size_bytes": upload_session.expected_size_bytes,
        "mime_type": upload_session.expected_mime_type,
        "part_size": PART_SIZE,
        "upload_id": upload_session.multipart_upload_id,
        "expires_at": upload_session.expires_at.isoformat(),
        "idempotency_key": upload_session.idempotency_key,
    }


def _serialize_file(file: ProjectFile, generation=None) -> dict[str, Any]:
    current = (
        next(
            (version for version in file.versions if version.id == file.current_version_id),
            None,
        )
        if file.current_version_id
        else None
    )
    if current is None or current.source == "preview" or current.status != "available":
        current = max(
            (
                version
                for version in file.versions
                if version.source != "preview" and version.status == "available"
            ),
            key=lambda item: item.version_number,
            default=None,
        )
    # Preview PDFs are derived artifacts, not user-visible file revisions.
    # Including them as ``latest_version`` makes the desktop treat PDF bytes as
    # the original DOCX and then fail during DOCX parsing.
    latest = max(
        (version for version in file.versions if version.source != "preview"),
        key=lambda item: item.version_number,
        default=None,
    )
    return {
        "id": file.id,
        "project_id": file.project_id,
        "display_name": file.display_name,
        "category": file.category,
        "business_category": file.business_category,
        "status": file.status,
        "current_version_id": current.id if current is not None else None,
        "current_version": _serialize_version(current) if current is not None else None,
        "latest_version": _serialize_version(latest) if latest is not None else None,
        "created_by": (
            file.created_by.display_name if file.created_by is not None else None
        ),
        "generation_status": generation.status if generation is not None else None,
        "generation_message": generation.failure_message if generation is not None else "",
        "generation_export_id": generation.id if generation is not None else None,
        "generation_form_id": generation.form_id if generation is not None else None,
        "generation_updated_at": generation.updated_at.isoformat() if generation is not None and generation.updated_at else None,
    }


def _serialize_version(version: ProjectFileVersion) -> dict[str, Any]:
    return {
        "id": version.id,
        "version_number": version.version_number,
        "status": version.status,
        "scan_status": version.scan_status,
        "preview_status": version.preview_status,
        "source": version.source,
        "original_filename": version.original_filename,
        "mime_type": version.mime_type,
        "size_bytes": version.size_bytes,
        "uploaded_by": version.uploaded_by.display_name if version.uploaded_by else None,
        "uploaded_at": version.created_at.isoformat(),
        "deprecated_by": version.deprecated_by.display_name if version.deprecated_by else None,
        "deprecated_at": version.deprecated_at.isoformat() if version.deprecated_at else None,
        "deprecation_reason": version.deprecation_reason,
    }
