"""Project-scoped document draft service.

Implements the Task 4 document draft lifecycle inside one transaction per write:
``list``/``get`` (view access), ``create`` (project manager), ``patch_draft``
(engineer/manager, optimistic lock on the draft ``version``), and
``request_generation`` (engineer/manager) which freezes a source snapshot into an
immutable ``ProjectDocumentVersion`` and enqueues an async generation job.

Every user-addressable failure is raised as :class:`DocumentDraftServiceError` so
the routes can wrap it with :func:`fde_api.errors.error_response`. Writes reuse
``record_event`` (project-scoped events, never the document body),
``project_access``, ``enqueue_outbox`` and ``sanitize_rich_text``.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session, selectinload

from fde_api.auth.models import User
from fde_api.documents.catalog import DOCUMENT_TYPES
from fde_api.documents.models import (
    DocumentGenerationJob,
    DocumentTemplate,
    DocumentTemplateVersion,
    ProjectDocument,
    ProjectDocumentDraft,
    ProjectDocumentVersion,
)
from fde_api.documents.rich_text import (
    RichTextSanitizationError,
    render_rich_text,
    sanitize_rich_text,
)
from fde_api.documents.snapshots import DocumentSnapshotError, build_document_snapshot
from fde_api.extensions import db, object_storage
from fde_api.files.models import (
    BUSINESS_CATEGORIES,
    BUSINESS_CATEGORY_UNCATEGORIZED_LABEL,
    ProjectFile,
    ProjectFileVersion,
)
from fde_api.files.names import extension_of, safe_filename
from fde_api.jobs.outbox import enqueue_outbox
from fde_api.projects.events import record_event
from fde_api.projects.permissions import project_access
from fde_api.research.models import ProjectAIOpportunityProfile, ProjectResearchSubject
from fde_api.workbench.models import Project, ProjectMember

DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
DOCX_EXTENSION = ".docx"

# Document type -> business code prefix. Unmapped types fall back to the
# uppercase type key (e.g. ``contract`` -> ``CONTRACT``).
_BUSINESS_CODE_PREFIXES = {
    "project_plan_progress": "PLAN",
    "sow": "SOW",
    "change_request": "CR",
    "acceptance": "ACC",
}

_DRAFT_FIELD_KEYS = ("field_overrides", "rich_text", "list_selections")


class DocumentDraftServiceError(Exception):
    """A stable, user-facing document draft/version failure."""

    def __init__(self, code: str, message: str, status: int):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


def list_project_documents(
    *, actor: User, project_id: str, business_category: str | None = None
) -> list[dict[str, Any]]:
    """Return a minimal summary of the project's documents (view allowed).

    ``business_category`` optionally filters to one business stage; the literal
    ``未分类`` token (``BUSINESS_CATEGORY_UNCATEGORIZED_LABEL``) selects items
    that are not assigned a business stage.
    """
    session = db.session()
    try:
        project = _load_project_for_view(session, actor, project_id)
        query = (
            select(ProjectDocument)
            .options(
                selectinload(ProjectDocument.current_version).selectinload(
                    ProjectDocumentVersion.generation_jobs
                ),
                selectinload(ProjectDocument.current_version).selectinload(
                    ProjectDocumentVersion.docx_file
                ),
                selectinload(ProjectDocument.owner),
            )
            .where(ProjectDocument.project_id == project.id)
        )
        if business_category is not None:
            query = _apply_business_category_filter(query, business_category)
        documents = list(
            session.scalars(
                query.order_by(ProjectDocument.created_at.desc(), ProjectDocument.id)
            )
        )
        return [_serialize_document_summary(document) for document in documents]
    finally:
        session.close()


def create_project_document(
    *, actor: User, project_id: str, input: Mapping[str, Any]
) -> dict[str, Any]:
    """Create a draft document plus an empty draft attachment (manager only)."""
    document_type, template_version_id, expected_version, business_category, source_opportunity_id = (
        _normalize_create_input(input)
    )
    ids = input.get("source_opportunity_ids")
    scope_text = input.get("generation_scope", "")
    if ids is not None and (document_type not in {"pov_plan", "sow"} or source_opportunity_id is not None or not isinstance(ids, list) or not 1 <= len(ids) <= 100 or any(not isinstance(value, str) or not value for value in ids) or len(set(ids)) != len(ids)):
        raise DocumentDraftServiceError("invalid_source_opportunity", "请选择本项目的 AI 机会（最多 100 个）。", 400)
    if not isinstance(scope_text, str) or len(scope_text) > 4000:
        raise DocumentDraftServiceError("invalid_request", "本次范围说明不能超过 4000 字。", 400)
    session = db.session()
    try:
        with session.begin():
            project = _load_project_for_update(session, project_id)
            _require_project_manager(actor, project)
            _require_project_version(project, expected_version)
            template_version = (
                _load_published_template_version(session, template_version_id)
                if template_version_id is not None
                else _load_latest_published_template_version(session, document_type)
            )
            if template_version.template.document_type != document_type:
                raise DocumentDraftServiceError(
                    "template_document_type_mismatch",
                    "The template version does not match the requested document type.",
                    400,
                )

            source_opportunity = _load_source_opportunity(
                session, project.id, document_type, source_opportunity_id
            )
            opportunity_scope = None
            if ids is not None:
                from fde_api.ai.ai_opportunity_service import _form_context
                from fde_api.research.models import ProjectResearchForm, ProjectResearchFormRevision
                selected = [_load_source_opportunity(session, project.id, document_type, key) for key in ids]
                forms = session.scalars(select(ProjectResearchForm).options(
                    selectinload(ProjectResearchForm.subject),
                    selectinload(ProjectResearchForm.current_revision).selectinload(ProjectResearchFormRevision.answers),
                ).where(ProjectResearchForm.project_id == project.id, ProjectResearchForm.subject_id.in_(ids))).all()
                opportunity_scope = {"instructions": scope_text.strip(), "opportunities": [
                    {**_opportunity_snapshot(item), "version": item.version} for item in selected
                ], "research": [_form_context(form) for form in forms]}

            existing = _load_opportunity_document_for_update(
                session,
                project_id=project.id,
                document_type=document_type,
                source_opportunity_id=source_opportunity.id if source_opportunity else None,
            )
            if existing is None and document_type == "project_plan_progress":
                existing = _load_singleton_document_for_update(
                    session, project_id=project.id, document_type=document_type
                )
            if existing is not None:
                existing.source_template_version_id = template_version.id
                existing.business_category = business_category
                existing.status = "draft"
                existing.version += 1
                if existing.draft is None:
                    existing.draft = ProjectDocumentDraft(
                        document_id=existing.id,
                        field_overrides_json=_opportunity_snapshot(source_opportunity)
                    )
                else:
                    existing.draft.field_overrides_json = {
                        **(existing.draft.field_overrides_json or {}),
                        **_opportunity_snapshot(source_opportunity),
                    }
                    existing.draft.version += 1
                session.flush()
                loaded = _load_document(session, project.id, existing.id)
                assert loaded is not None
                return _serialize_document(loaded) | {
                    "project_version": project.version,
                    "reused": True,
                }

            business_code = _suggest_business_code(
                session,
                project=project,
                document_type=document_type,
                source_opportunity=source_opportunity,
            )
            document = ProjectDocument(
                project_id=project.id,
                document_type=document_type,
                business_code=business_code,
                business_category=business_category,
                status="draft",
                source_template_version_id=template_version.id,
                source_opportunity_id=source_opportunity.id if source_opportunity else None,
                owner_user_id=actor.id,
                opportunity_scope_json=opportunity_scope,
            )
            session.add(document)
            session.flush()
            session.add(ProjectDocumentDraft(
                document_id=document.id,
                field_overrides_json=_opportunity_snapshot(source_opportunity),
            ))
            if source_opportunity is not None and source_opportunity.opportunity_profile is not None:
                source_opportunity.opportunity_profile.opportunity_status = "converted"
            session.flush()

            project.version += 1
            record_event(
                session,
                actor,
                "project_document_created",
                project,
                {
                    "document_id": document.id,
                    "business_code": business_code,
                    "document_type": document_type,
                },
            )
            session.flush()
            loaded = _load_document(session, project.id, document.id)
            assert loaded is not None
            return _serialize_document(loaded) | {"project_version": project.version}
    except DocumentDraftServiceError:
        raise
    except IntegrityError:
        raise DocumentDraftServiceError(
            "document_conflict",
            "The document could not be created due to a conflict.",
            409,
        ) from None
    except SQLAlchemyError:
        raise DocumentDraftServiceError(
            "document_create_failed",
            "Unable to create the document at this time.",
            503,
        ) from None
    finally:
        session.close()


def get_project_document(
    *, actor: User, project_id: str, document_id: str
) -> dict[str, Any]:
    """Return the full document detail (view allowed)."""
    session = db.session()
    try:
        project = _load_project_for_view(session, actor, project_id)
        document = _load_document(session, project.id, document_id)
        if document is None:
            raise DocumentDraftServiceError(
                "document_not_found", "Document was not found.", 404
            )
        return _serialize_document(document)
    finally:
        session.close()


def rename_project_document(
    *, actor: User, project_id: str, document_id: str, expected_version: int, name: object
) -> dict[str, Any]:
    """Rename one document identity without creating or changing a file version."""
    normalized = _normalize_document_name(name)
    session = db.session()
    try:
        with session.begin():
            project = _load_project_for_update(session, project_id)
            _require_document_editor(actor, project)
            document = _load_document(session, project.id, document_id)
            if document is None:
                raise DocumentDraftServiceError("document_not_found", "Document was not found.", 404)
            if document.version != expected_version:
                raise DocumentDraftServiceError("stale_version", "The document has been updated. Refresh and try again.", 409)
            if document.business_code == normalized:
                return _serialize_document(document)
            duplicate = session.scalar(
                select(ProjectDocument.id).where(
                    ProjectDocument.project_id == project.id,
                    ProjectDocument.business_code == normalized,
                    ProjectDocument.id != document.id,
                )
            )
            if duplicate is not None:
                raise DocumentDraftServiceError("document_name_conflict", "项目中已存在同名文档。", 409)
            old_name = document.business_code
            document.business_code = normalized
            document.version += 1
            if document.library_file_id:
                library_file = session.get(ProjectFile, document.library_file_id)
                if library_file is not None:
                    library_file.display_name = normalized
                    library_file.version += 1
            record_event(
                session,
                actor,
                "project_document_renamed",
                project,
                {"document_id": document.id, "old_name": old_name, "new_name": normalized},
            )
            session.flush()
            loaded = _load_document(session, project.id, document.id)
            assert loaded is not None
            return _serialize_document(loaded)
    except DocumentDraftServiceError:
        raise
    except IntegrityError:
        raise DocumentDraftServiceError("document_name_conflict", "项目中已存在同名文档。", 409) from None
    except SQLAlchemyError:
        raise DocumentDraftServiceError("document_rename_failed", "文档重命名失败，请稍后重试。", 503) from None
    finally:
        session.close()


def patch_project_document_draft(
    *,
    actor: User,
    project_id: str,
    document_id: str,
    expected_version: int,
    changes: Mapping[str, Any],
) -> dict[str, Any]:
    """Apply editor-authored changes to the draft under optimistic locking.

    ``expected_version`` is the client's view of the draft ``version``. A
    mismatch yields ``stale_version`` (409). Rich text is sanitized before it is
    persisted; an invalid payload is rejected as a 400.
    """
    session = db.session()
    try:
        with session.begin():
            project = _load_project_for_update(session, project_id)
            _require_document_editor(actor, project)
            document = _load_document(session, project.id, document_id)
            if document is None:
                raise DocumentDraftServiceError(
                    "document_not_found", "Document was not found.", 404
                )
            draft = document.draft
            if document.opportunity_scope_json and isinstance(document.opportunity_scope_json.get("solution"), dict):
                raise DocumentDraftServiceError("solution_source_readonly", "该 SOW 来自已保存方案，请回到方案设计修改后再导出；文档层修订请使用在线修订或人工上传。", 409)
            if draft is None:
                raise DocumentDraftServiceError(
                    "document_draft_missing", "Document has no draft.", 404
                )
            if draft.version != expected_version:
                raise DocumentDraftServiceError(
                    "stale_version",
                    "The document draft has been updated. Refresh and try again.",
                    409,
                )

            for key in _DRAFT_FIELD_KEYS:
                if key not in changes:
                    continue
                value = changes[key]
                if key == "rich_text":
                    value = _sanitize_rich_text_value(value)
                _assign_draft_field(draft, key, value)

            draft.version += 1
            record_event(
                session,
                actor,
                "project_document_draft_updated",
                project,
                {"document_id": document.id, "draft_version": draft.version},
            )
            session.flush()
            return _serialize_draft(draft) | {
                "project_version": project.version,
                "document_version": document.version,
            }
    except DocumentDraftServiceError:
        raise
    except SQLAlchemyError:
        raise DocumentDraftServiceError(
            "document_draft_update_failed",
            "Unable to update the document draft at this time.",
            503,
        ) from None
    finally:
        session.close()


def request_document_generation(
    *,
    actor: User,
    project_id: str,
    document_id: str,
    expected_version: int,
) -> dict[str, Any]:
    """Freeze a source snapshot into a draft version and enqueue its job.

    Only a draft document can be generated. The snapshot builder runs against the
    document's source template version mapping; the generated ``ProjectDocument``
    version is ``source="generated"`` and receives ``DocumentGenerationJob`` plus
    a ``document.generate`` outbox event. Actual rendering is Task 5.
    """
    session = db.session()
    try:
        with session.begin():
            project = _load_project_for_update(session, project_id)
            _require_document_editor(actor, project)
            document = _load_document(session, project.id, document_id)
            if document is None:
                raise DocumentDraftServiceError(
                    "document_not_found", "Document was not found.", 404
                )
            if document.status != "draft":
                raise DocumentDraftServiceError(
                    "invalid_document_state",
                    "Only a draft document can be generated.",
                    409,
                )
            if document.opportunity_scope_json and isinstance(document.opportunity_scope_json.get("solution"), dict):
                raise DocumentDraftServiceError("solution_source_readonly", "该 SOW 来自已保存方案，请从方案设计导出，不能重新调用 AI 生成。", 409)
            if document.version != expected_version:
                raise DocumentDraftServiceError(
                    "stale_version",
                    "The document has been updated. Refresh and try again.",
                    409,
                )

            template_version = session.get(
                DocumentTemplateVersion, document.source_template_version_id
            )
            if template_version is None:
                raise DocumentDraftServiceError(
                    "template_version_not_found",
                    "The document template version was not found.",
                    404,
                )
            try:
                snapshot = build_document_snapshot(
                    session, project.id, template_version.mapping_json
                )
            except DocumentSnapshotError as error:
                raise DocumentDraftServiceError(
                    error.code, error.message, error.status
                ) from None

            version_number = _next_document_version_number(session, document.id)
            parent_version_id = document.current_version_id
            docx_file_version = _create_placeholder_docx(
                session, project, document, version_number, actor
            )
            content_snapshot = _content_snapshot(document.draft)
            if document.opportunity_scope_json and isinstance(document.opportunity_scope_json.get("solution"), dict):
                from copy import deepcopy
                content_snapshot["solution"] = deepcopy(document.opportunity_scope_json["solution"])
                content_snapshot["opportunity_scope"] = deepcopy(document.opportunity_scope_json)
                snapshot["solution"] = deepcopy(document.opportunity_scope_json["solution"])

            version = ProjectDocumentVersion(
                document_id=document.id,
                version_number=version_number,
                source="generated",
                status="draft",
                parent_version_id=parent_version_id,
                source_template_version_id=template_version.id,
                source_snapshot_json=snapshot,
                content_snapshot_json=content_snapshot,
                docx_file_version_id=docx_file_version.id,
                sha256="",
                generated_by_user_id=actor.id,
            )
            session.add(version)
            session.flush()

            job = DocumentGenerationJob(
                document_version_id=version.id,
                status="queued",
            )
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
                "project_document_generation_requested",
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
    except DocumentDraftServiceError:
        raise
    except SQLAlchemyError:
        raise DocumentDraftServiceError(
            "document_generation_failed",
            "Unable to request document generation at this time.",
            503,
        ) from None
    finally:
        session.close()


# ---------------------------------------------------------------------------
# Validation / helpers
# ---------------------------------------------------------------------------


def _normalize_create_input(
    input: Mapping[str, Any],
) -> tuple[str, str | None, int, str | None, str | None]:
    document_type = input.get("document_type")
    if not isinstance(document_type, str) or document_type not in DOCUMENT_TYPES:
        raise DocumentDraftServiceError(
            "unknown_document_type", "The document type is not supported.", 400
        )
    template_version_id = input.get("template_version_id")
    if template_version_id is not None and (
        not isinstance(template_version_id, str) or not template_version_id
    ):
        raise DocumentDraftServiceError(
            "invalid_request", "The template version is invalid.", 400
        )
    expected_version = input.get("expected_version")
    if type(expected_version) is not int or expected_version < 1:
        raise DocumentDraftServiceError(
            "invalid_request", "expected_version is required.", 400
        )
    business_category = _normalize_business_category(
        input.get("business_category")
    )
    source_opportunity_id = input.get("source_opportunity_id")
    if source_opportunity_id is not None and (
        not isinstance(source_opportunity_id, str) or not source_opportunity_id
    ):
        raise DocumentDraftServiceError("invalid_source_opportunity", "The source AI opportunity is invalid.", 400)
    return document_type, template_version_id, expected_version, business_category, source_opportunity_id


def _load_source_opportunity(
    session: Session, project_id: str, document_type: str, opportunity_id: str | None
) -> ProjectResearchSubject | None:
    if opportunity_id is None:
        return None
    if document_type not in {"pov_plan", "pov_report", "sow"}:
        raise DocumentDraftServiceError("invalid_source_opportunity", "Only PoV and SOW drafts can be created from an AI opportunity.", 400)
    opportunity = session.scalar(
        select(ProjectResearchSubject)
        .options(selectinload(ProjectResearchSubject.opportunity_profile).selectinload(ProjectAIOpportunityProfile.owner))
        .where(
            ProjectResearchSubject.id == opportunity_id,
            ProjectResearchSubject.project_id == project_id,
            ProjectResearchSubject.subject_type == "opportunity",
            ProjectResearchSubject.status == "active",
        )
    )
    if opportunity is None:
        raise DocumentDraftServiceError("invalid_source_opportunity", "The source AI opportunity is invalid.", 400)
    return opportunity


def _load_opportunity_document_for_update(
    session: Session,
    *,
    project_id: str,
    document_type: str,
    source_opportunity_id: str | None,
) -> ProjectDocument | None:
    """Return the latest reusable PoV/SOW identity for one AI opportunity.

    Re-generating a business document must append a version to the same file
    identity instead of creating another card in the project library.
    """
    if source_opportunity_id is None or document_type not in {"pov_plan", "pov_report", "sow"}:
        return None
    return session.scalar(
        select(ProjectDocument)
        .options(
            selectinload(ProjectDocument.current_version),
            selectinload(ProjectDocument.draft),
            selectinload(ProjectDocument.owner),
            selectinload(ProjectDocument.versions),
        )
        .where(
            ProjectDocument.project_id == project_id,
            ProjectDocument.document_type == document_type,
            ProjectDocument.source_opportunity_id == source_opportunity_id,
        )
        .order_by(ProjectDocument.created_at.desc(), ProjectDocument.id.desc())
        .with_for_update()
        .limit(1)
    )


def _load_singleton_document_for_update(
    session: Session, *, project_id: str, document_type: str
) -> ProjectDocument | None:
    """Reuse one project-level document identity while appending export versions."""
    return session.scalar(
        select(ProjectDocument)
        .options(
            selectinload(ProjectDocument.current_version),
            selectinload(ProjectDocument.draft),
            selectinload(ProjectDocument.owner),
            selectinload(ProjectDocument.versions),
        )
        .where(
            ProjectDocument.project_id == project_id,
            ProjectDocument.document_type == document_type,
        )
        .order_by(ProjectDocument.created_at.desc(), ProjectDocument.id.desc())
        .with_for_update()
        .limit(1)
    )


def _opportunity_snapshot(opportunity: ProjectResearchSubject | None) -> dict[str, Any]:
    if opportunity is None:
        return {}
    profile = opportunity.opportunity_profile
    return {
        "source_opportunity_id": opportunity.id,
        "opportunity_tracking_code": opportunity.tracking_code or "",
        "opportunity_name": opportunity.name,
        "opportunity_description": opportunity.description,
        "target_audience": profile.target_audience if profile else "",
        "opportunity_owner": profile.owner.display_name if profile and profile.owner else "",
        "opportunity_status": profile.opportunity_status if profile else "discovered",
        "opportunity_priority": profile.priority if profile else None,
        "business_value_score": profile.business_value_score if profile else None,
        "feasibility_score": profile.feasibility_score if profile else None,
        "data_readiness_score": profile.data_readiness_score if profile else None,
        "risk_level": profile.risk_level if profile else None,
        "next_action": profile.next_action if profile else "",
    }


def _normalize_business_category(value: Any) -> str | None:
    """Return a storable business category or ``None`` for uncategorized."""
    if value is None:
        return None
    if isinstance(value, str) and value == "":
        return None
    if value in BUSINESS_CATEGORIES:
        return value
    raise DocumentDraftServiceError(
        "invalid_business_category",
        "The business category is not supported.",
        400,
    )


def _apply_business_category_filter(query, business_category: str):
    """Restrict a ``ProjectDocument`` select to one business stage or uncategorized."""
    if business_category == BUSINESS_CATEGORY_UNCATEGORIZED_LABEL:
        return query.where(
            ProjectDocument.business_category.is_(None)
            | (ProjectDocument.business_category == "")
        )
    if business_category not in BUSINESS_CATEGORIES:
        raise DocumentDraftServiceError(
            "invalid_business_category",
            "The business category is not supported.",
            400,
        )
    return query.where(ProjectDocument.business_category == business_category)


def _assign_draft_field(draft: ProjectDocumentDraft, key: str, value: Any) -> None:
    if key == "field_overrides":
        draft.field_overrides_json = value if isinstance(value, dict) else {}
    elif key == "rich_text":
        draft.rich_text_json = value
    elif key == "list_selections":
        draft.list_selections_json = value if isinstance(value, dict) else {}


def _sanitize_rich_text_value(value: Any) -> Any:
    try:
        document = sanitize_rich_text(value)
    except RichTextSanitizationError:
        raise DocumentDraftServiceError(
            "invalid_rich_text", "The rich-text content is invalid.", 400
        ) from None
    return render_rich_text(document)


def _next_business_code(session: Session, project_id: str, document_type: str) -> str:
    prefix = _BUSINESS_CODE_PREFIXES.get(document_type, document_type.upper())
    existing_codes = set(
        session.scalars(
            select(ProjectDocument.business_code).where(
                ProjectDocument.project_id == project_id
            )
        )
    )
    sequence = 1
    while f"{prefix}-{sequence}" in existing_codes:
        sequence += 1
    return f"{prefix}-{sequence}"


def _suggest_business_code(
    session: Session,
    *,
    project: Project,
    document_type: str,
    source_opportunity: ProjectResearchSubject | None,
) -> str:
    if source_opportunity is not None and document_type in {"pov_plan", "pov_report", "sow"}:
        prefix = "SOW" if document_type == "sow" else "PoV"
        return _unique_document_name(session, project.id, f"{prefix}-{source_opportunity.name}")
    if document_type == "project_plan_progress":
        return _unique_document_name(session, project.id, f"项目计划及进度-{project.name}")
    return _next_business_code(session, project.id, document_type)


def _unique_document_name(session: Session, project_id: str, suggested: str) -> str:
    existing = set(
        session.scalars(
            select(ProjectDocument.business_code).where(ProjectDocument.project_id == project_id)
        )
    )
    base = _normalize_document_name(suggested)
    if base not in existing:
        return base
    sequence = 2
    while True:
        suffix = f"-{sequence}"
        candidate = f"{base[:80 - len(suffix)].rstrip()}{suffix}"
        if candidate not in existing:
            return candidate
        sequence += 1


def _normalize_document_name(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise DocumentDraftServiceError("document_name_invalid", "请填写文档名称。", 422)
    normalized = " ".join(value.split())
    if len(normalized) > 80:
        raise DocumentDraftServiceError("document_name_invalid", "文档名称不能超过 80 个字符。", 422)
    if any(ord(character) < 32 for character in normalized):
        raise DocumentDraftServiceError("document_name_invalid", "文档名称包含不可用字符。", 422)
    return normalized


def _next_document_version_number(session: Session, document_id: str) -> int:
    current = session.scalar(
        select(func.max(ProjectDocumentVersion.version_number)).where(
            ProjectDocumentVersion.document_id == document_id
        )
    )
    return int(current or 0) + 1


def _load_published_template_version(
    session: Session, template_version_id: str
) -> DocumentTemplateVersion:
    template_version = session.scalar(
        select(DocumentTemplateVersion)
        .options(selectinload(DocumentTemplateVersion.template))
        .where(
            DocumentTemplateVersion.id == template_version_id,
            DocumentTemplateVersion.status == "published",
        )
    )
    if template_version is None:
        raise DocumentDraftServiceError(
            "template_version_not_published",
            "The document template version is not published.",
            422,
        )
    return template_version


def _load_latest_published_template_version(
    session: Session, document_type: str
) -> DocumentTemplateVersion:
    template_version = session.scalar(
        select(DocumentTemplateVersion)
        .join(DocumentTemplate, DocumentTemplateVersion.template_id == DocumentTemplate.id)
        .options(selectinload(DocumentTemplateVersion.template))
        .where(
            DocumentTemplate.document_type == document_type,
            DocumentTemplateVersion.status == "published",
        )
        .order_by(DocumentTemplateVersion.version_number.desc(), DocumentTemplateVersion.id)
    )
    if template_version is None:
        raise DocumentDraftServiceError(
            "document_template_not_published",
            f"No published template exists for document type '{document_type}'.",
            422,
        )
    return template_version


def _document_display_name(document: ProjectDocument) -> str:
    solution = (document.opportunity_scope_json or {}).get("solution", {})
    if document.document_type == "sow" and solution.get("name"):
        return f"SOW-{solution['name']}"
    return document.business_code


def _available_document_file_name(session: Session, project_id: str, name: str,
                                  file_id: str | None = None) -> str:
    """Keep historical files untouched; distinguish new same-named exports."""
    base = name[:255]
    candidate = base
    number = 2
    while True:
        query = select(ProjectFile.id).where(
            ProjectFile.project_id == project_id,
            ProjectFile.category == "document",
            ProjectFile.display_name == candidate,
        )
        if file_id:
            query = query.where(ProjectFile.id != file_id)
        if session.scalar(query) is None:
            return candidate
        suffix = f"（{number}）"
        candidate = base[:255 - len(suffix)] + suffix
        number += 1


def _create_placeholder_docx(
    session: Session,
    project: Project,
    document: ProjectDocument,
    version_number: int,
    actor: User,
) -> ProjectFileVersion:
    display_name = "项目计划及进度" if document.document_type == "project_plan_progress" else document.business_code
    solution = (document.opportunity_scope_json or {}).get("solution", {})
    if document.document_type == "sow" and solution.get("name"):
        display_name = f"SOW-{solution['name']}"
    filename = f"{display_name}-v{version_number}{DOCX_EXTENSION}"
    safe = safe_filename(filename)
    project_file = session.get(ProjectFile, document.library_file_id) if document.library_file_id else None
    # Include deprecated rows: they still participate in the unique constraint.
    # Lock the project while allocating a name so concurrent exports serialize.
    session.execute(select(Project.id).where(Project.id == project.id).with_for_update())
    library_name = _available_document_file_name(
        session, project.id, display_name, project_file.id if project_file else None,
    )
    if project_file is None:
        project_file = ProjectFile(
            project_id=project.id,
            category="document",
            business_category=document.business_category,
            display_name=library_name,
            description="",
            created_by_user_id=actor.id,
        )
        session.add(project_file)
        session.flush()
        document.library_file_id = project_file.id
    elif document.document_type == "sow" and solution.get("name"):
        project_file.display_name = library_name
    file_version = ProjectFileVersion(
        file_id=project_file.id,
        version_number=version_number,
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


def _content_snapshot(draft: ProjectDocumentDraft | None) -> dict[str, Any]:
    if draft is None:
        return {"field_overrides": {}, "rich_text": {}, "list_selections": {}}
    return {
        "field_overrides": draft.field_overrides_json or {},
        "rich_text": draft.rich_text_json or {},
        "list_selections": draft.list_selections_json or {},
    }


def _storage_bucket() -> str:
    storage = object_storage.current
    bucket = getattr(storage, "bucket_name", None)
    return bucket or "local"


# ---------------------------------------------------------------------------
# Loading
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
        raise DocumentDraftServiceError("project_not_found", "Project was not found.", 404)
    if not project_access(actor, project).can_view:
        raise DocumentDraftServiceError(
            "forbidden", "You do not have permission to access this project.", 403
        )
    return project


def _require_project_view(project: Project | None) -> Project:
    if project is None:
        raise DocumentDraftServiceError("project_not_found", "Project was not found.", 404)
    return project


def _require_project_manager(actor: User, project: Project) -> Project:
    if not project_access(actor, project).can_manage:
        raise DocumentDraftServiceError(
            "forbidden", "You do not have permission to manage this project.", 403
        )
    return project


def _require_document_editor(actor: User, project: Project) -> Project:
    access = project_access(actor, project)
    if not (access.can_manage or access.can_update_assigned_tasks):
        raise DocumentDraftServiceError(
            "forbidden",
            "You do not have permission to edit documents in this project.",
            403,
        )
    return project


def _require_project_version(project: Project, expected_version: int) -> None:
    if project.version != expected_version:
        raise DocumentDraftServiceError(
            "stale_version", "The project has been updated. Refresh and try again.", 409
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


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------


def _serialize_document_summary(document: ProjectDocument) -> dict[str, Any]:
    generation_job = None
    if document.current_version is not None and document.current_version.generation_jobs:
        generation_job = max(
            document.current_version.generation_jobs,
            key=lambda item: (item.created_at, item.id),
        )
    return {
        "id": document.id,
        "project_id": document.project_id,
        "document_type": document.document_type,
        "business_code": document.business_code,
        "display_name": _document_display_name(document),
        "business_category": document.business_category,
        "source_opportunity_id": document.source_opportunity_id,
        "opportunity_scope": document.opportunity_scope_json,
        "library_file_id": document.library_file_id,
        "status": document.status,
        "version": document.version,
        "current_version_id": document.current_version_id,
        "current_version": (
            _serialize_version_summary(document.current_version)
            if document.current_version is not None
            else None
        ),
        "generation_status": generation_job.status if generation_job is not None else None,
        "generation_message": generation_job.last_error if generation_job is not None else "",
        "created_at": document.created_at.isoformat(),
        "updated_at": document.updated_at.isoformat(),
    }


def _serialize_document(document: ProjectDocument) -> dict[str, Any]:
    versions = sorted(document.versions, key=lambda item: item.version_number, reverse=True)
    return {
        "id": document.id,
        "project_id": document.project_id,
        "document_type": document.document_type,
        "business_code": document.business_code,
        "display_name": _document_display_name(document),
        "business_category": document.business_category,
        "source_opportunity_id": document.source_opportunity_id,
        "opportunity_scope": document.opportunity_scope_json,
        "library_file_id": document.library_file_id,
        "status": document.status,
        "version": document.version,
        "source_template_version_id": document.source_template_version_id,
        "current_version_id": document.current_version_id,
        "owner": (
            {
                "id": document.owner.id,
                "display_name": document.owner.display_name,
            }
            if document.owner is not None
            else None
        ),
        "current_version": (
            _serialize_version(document.current_version)
            if document.current_version is not None
            else None
        ),
        "draft": (
            _serialize_draft(document.draft) if document.draft is not None else None
        ),
        "history": [
            _serialize_version_summary(version) for version in versions
        ],
        "created_at": document.created_at.isoformat(),
        "updated_at": document.updated_at.isoformat(),
    }


def _serialize_draft(draft: ProjectDocumentDraft) -> dict[str, Any]:
    return {
        "id": draft.id,
        "document_id": draft.document_id,
        "version": draft.version,
        "field_overrides": draft.field_overrides_json,
        "rich_text": draft.rich_text_json,
        "list_selections": draft.list_selections_json,
        "created_at": draft.created_at.isoformat(),
        "updated_at": draft.updated_at.isoformat(),
    }


def _serialize_version(version: ProjectDocumentVersion) -> dict[str, Any]:
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
        "generated_by": (
            {
                "id": version.generated_by.id,
                "display_name": version.generated_by.display_name,
            }
            if version.generated_by is not None
            else None
        ),
        "created_at": version.created_at.isoformat(),
        "updated_at": version.updated_at.isoformat(),
    }


def _serialize_version_summary(version: ProjectDocumentVersion) -> dict[str, Any]:
    docx_file = version.docx_file
    return {
        **_generation_status(version),
        "id": version.id,
        "version_number": version.version_number,
        "source": version.source,
        "status": version.status,
        "docx_file_version_id": version.docx_file_version_id,
        "preview_file_version_id": version.preview_file_version_id or (
            docx_file.preview_version_id if docx_file is not None else None
        ),
        "preview_status": (
            docx_file.preview_status if docx_file is not None else "none"
        ),
        "parent_version_id": version.parent_version_id,
        "created_at": version.created_at.isoformat(),
    }


def _generation_status(version: ProjectDocumentVersion) -> dict[str, Any]:
    jobs = version.generation_jobs
    if version.sha256:
        return {"generation_status": "succeeded", "generation_message": ""}
    active = [job for job in jobs if job.status in {"queued", "running"}]
    latest = max(active or jobs, key=lambda job: (job.created_at, job.id)) if jobs else None
    return {"generation_status": latest.status if latest else None,
            "generation_message": (latest.last_error if latest else version.generation_error) or ""}
