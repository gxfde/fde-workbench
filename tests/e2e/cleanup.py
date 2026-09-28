from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
import json
import os
from pathlib import Path
import sys

from alembic import command
from alembic.config import Config
from sqlalchemy import delete, or_, select, text, update
from sqlalchemy.engine import make_url

from fde_api.app import create_app
from fde_api.auth.models import RefreshSession, User
from fde_api.auth.passwords import hash_password
from fde_api.config import Settings
from fde_api.documents.models import (
    DocumentGenerationJob,
    DocumentTemplate,
    DocumentTemplateVersion,
    ProjectDocument,
    ProjectDocumentDraft,
    ProjectDocumentVersion,
)
from fde_api.extensions import db, object_storage
from fde_api.files.models import ProjectFile, ProjectFileVersion, UploadSession
from fde_api.research.models import (
    ProjectResearchAnswer,
    ProjectResearchForm,
    ProjectResearchFormRevision,
    ProjectResearchImportBatch,
    ProjectResearchSubject,
    ProjectResearchSubjectLink,
    TemplateResearchField,
    TemplateResearchForm,
    TemplateResearchSection,
)
from fde_api.workbench.models import (
    IndustryTemplate,
    IndustryTemplateVersion,
    ModuleCatalog,
    OperationEvent,
    Project,
    ProjectMember,
    ProjectModule,
    ProjectTask,
    ProjectTaskCollaborator,
    ProjectTaskDependency,
    TemplateModule,
    TemplateTask,
    TemplateTaskDependency,
)
from fde_api.workbench.seed import seed_workbench


SERVER_ROOT = Path(__file__).resolve().parents[2] / "server"
TEST_DATABASE_NAME = "fde_workbench_test"
PRESERVED_ADMIN_USERNAME = "15818708414"
PRESERVED_ADMIN_ID = "15818708-4140-4000-8000-000000000014"
GENERIC_TEMPLATE_KEY = "generic_enterprise_ai"
UNRELATED_FIXTURE_PROJECT_CODE = "fixture.unrelated.research"
PRESERVATION_FINGERPRINT_MODELS = {
    "admin": User,
    "admin_refresh_sessions": RefreshSession,
    "module_catalog": ModuleCatalog,
    "template": IndustryTemplate,
    "template_versions": IndustryTemplateVersion,
    "template_modules": TemplateModule,
    "template_tasks": TemplateTask,
    "template_dependencies": TemplateTaskDependency,
    "template_research_forms": TemplateResearchForm,
    "template_research_sections": TemplateResearchSection,
    "template_research_fields": TemplateResearchField,
    "template_events": OperationEvent,
    "project": Project,
    "project_members": ProjectMember,
    "project_modules": ProjectModule,
    "project_tasks": ProjectTask,
    "project_dependencies": ProjectTaskDependency,
    "project_collaborators": ProjectTaskCollaborator,
    "project_subjects": ProjectResearchSubject,
    "project_subject_links": ProjectResearchSubjectLink,
    "project_import_receipts": ProjectResearchImportBatch,
    "project_forms": ProjectResearchForm,
    "project_revisions": ProjectResearchFormRevision,
    "project_answers": ProjectResearchAnswer,
    "project_events": OperationEvent,
}


def preservation_fixture_fingerprint(connection):
    project_id = connection.scalar(
        select(Project.id).where(Project.project_code == UNRELATED_FIXTURE_PROJECT_CODE)
    )
    if project_id is None:
        return None
    template_id = connection.scalar(
        select(IndustryTemplate.id).where(IndustryTemplate.template_key == GENERIC_TEMPLATE_KEY)
    )
    if template_id is None:
        raise RuntimeError("The preservation fixture lost its generic seeded template.")
    admin_id = connection.scalar(
        select(User.id).where(User.username == PRESERVED_ADMIN_USERNAME)
    )
    if admin_id is None:
        raise RuntimeError("The preservation fixture lost its seeded administrator.")
    version_ids = list(connection.scalars(
        select(IndustryTemplateVersion.id).where(IndustryTemplateVersion.template_id == template_id)
    ))
    template_module_ids = list(connection.scalars(
        select(TemplateModule.id).where(TemplateModule.template_version_id.in_(version_ids))
    ))
    module_catalog_ids = list(connection.scalars(
        select(TemplateModule.module_catalog_id).where(TemplateModule.id.in_(template_module_ids)).distinct()
    ))
    template_task_ids = list(connection.scalars(
        select(TemplateTask.id).where(TemplateTask.template_module_id.in_(template_module_ids))
    ))
    template_form_ids = list(connection.scalars(
        select(TemplateResearchForm.id).where(TemplateResearchForm.template_version_id.in_(version_ids))
    ))
    template_section_ids = list(connection.scalars(
        select(TemplateResearchSection.id).where(TemplateResearchSection.form_id.in_(template_form_ids))
    ))
    project_module_ids = list(connection.scalars(
        select(ProjectModule.id).where(ProjectModule.project_id == project_id)
    ))
    project_task_ids = list(connection.scalars(
        select(ProjectTask.id).where(ProjectTask.project_module_id.in_(project_module_ids))
    ))
    project_form_ids = list(connection.scalars(
        select(ProjectResearchForm.id).where(ProjectResearchForm.project_id == project_id)
    ))
    revision_ids = list(connection.scalars(
        select(ProjectResearchFormRevision.id).where(ProjectResearchFormRevision.form_id.in_(project_form_ids))
    ))
    fingerprint = {
        "admin": _canonical_table_rows(connection, User, User.username == PRESERVED_ADMIN_USERNAME),
        "admin_refresh_sessions": _canonical_table_rows(connection, RefreshSession, RefreshSession.user_id == admin_id),
        "module_catalog": _canonical_table_rows(connection, ModuleCatalog, ModuleCatalog.id.in_(module_catalog_ids)),
        "template": _canonical_table_rows(connection, IndustryTemplate, IndustryTemplate.id == template_id),
        "template_versions": _canonical_table_rows(connection, IndustryTemplateVersion, IndustryTemplateVersion.id.in_(version_ids)),
        "template_modules": _canonical_table_rows(connection, TemplateModule, TemplateModule.id.in_(template_module_ids)),
        "template_tasks": _canonical_table_rows(connection, TemplateTask, TemplateTask.id.in_(template_task_ids)),
        "template_dependencies": _canonical_table_rows(
            connection,
            TemplateTaskDependency,
            (TemplateTaskDependency.predecessor_task_id.in_(template_task_ids))
            | (TemplateTaskDependency.successor_task_id.in_(template_task_ids)),
        ),
        "template_research_forms": _canonical_table_rows(connection, TemplateResearchForm, TemplateResearchForm.id.in_(template_form_ids)),
        "template_research_sections": _canonical_table_rows(connection, TemplateResearchSection, TemplateResearchSection.id.in_(template_section_ids)),
        "template_research_fields": _canonical_table_rows(connection, TemplateResearchField, TemplateResearchField.section_id.in_(template_section_ids)),
        "template_events": _canonical_table_rows(
            connection,
            OperationEvent,
            (OperationEvent.target_type == "industry_template_version")
            & (OperationEvent.target_id.in_(version_ids)),
        ),
        "project": _canonical_table_rows(connection, Project, Project.id == project_id),
        "project_members": _canonical_table_rows(connection, ProjectMember, ProjectMember.project_id == project_id),
        "project_modules": _canonical_table_rows(connection, ProjectModule, ProjectModule.id.in_(project_module_ids)),
        "project_tasks": _canonical_table_rows(connection, ProjectTask, ProjectTask.id.in_(project_task_ids)),
        "project_dependencies": _canonical_table_rows(
            connection,
            ProjectTaskDependency,
            (ProjectTaskDependency.predecessor_task_id.in_(project_task_ids))
            | (ProjectTaskDependency.successor_task_id.in_(project_task_ids)),
        ),
        "project_collaborators": _canonical_table_rows(connection, ProjectTaskCollaborator, ProjectTaskCollaborator.task_id.in_(project_task_ids)),
        "project_subjects": _canonical_table_rows(connection, ProjectResearchSubject, ProjectResearchSubject.project_id == project_id),
        "project_subject_links": _canonical_table_rows(connection, ProjectResearchSubjectLink, ProjectResearchSubjectLink.project_id == project_id),
        "project_import_receipts": _canonical_table_rows(connection, ProjectResearchImportBatch, ProjectResearchImportBatch.project_id == project_id),
        "project_forms": _canonical_table_rows(connection, ProjectResearchForm, ProjectResearchForm.id.in_(project_form_ids)),
        "project_revisions": _canonical_table_rows(connection, ProjectResearchFormRevision, ProjectResearchFormRevision.id.in_(revision_ids)),
        "project_answers": _canonical_table_rows(connection, ProjectResearchAnswer, ProjectResearchAnswer.revision_id.in_(revision_ids)),
        "project_events": _canonical_table_rows(connection, OperationEvent, OperationEvent.project_id == project_id),
    }
    return json.dumps(fingerprint, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _canonical_table_rows(connection, model, predicate):
    table = model.__table__
    rows = connection.execute(
        select(*table.c).where(predicate).order_by(table.c.id)
    ).mappings()
    return [
        {column.name: _canonical_value(row[column.name]) for column in table.c}
        for row in rows
    ]


def _canonical_value(value):
    if isinstance(value, dict):
        return {str(key): _canonical_value(item) for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))}
    if isinstance(value, (list, tuple)):
        return [_canonical_value(item) for item in value]
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, bytes):
        return value.hex()
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def require_test_settings() -> Settings:
    settings = Settings()
    configured_database_name = make_url(settings.database_url).database
    if configured_database_name != TEST_DATABASE_NAME:
        raise SystemExit(
            "refusing research E2E cleanup outside fde_workbench_test"
        )
    return settings


def cleanup_test_rows(settings: Settings) -> None:
    run_id = os.environ.get("FDE_E2E_RUN_ID", "").strip()
    if not run_id or not all(character in "0123456789abcdef" for character in run_id):
        raise SystemExit("FDE_E2E_RUN_ID must be a non-empty lowercase hexadecimal run ID.")
    exact_usernames = {
        *(
            value
            for name in (
                "FDE_E2E_PHASE1_ADMIN_USERNAME",
                "FDE_E2E_PHASE1_ENGINEER_USERNAME",
                "FDE_E2E_ADMIN_USERNAME",
                "FDE_E2E_ENGINEER_USERNAME",
                "FDE_E2E_LEAD_USERNAME",
                "FDE_E2E_UNRELATED_ENGINEER_USERNAME",
                "FDE_E2E_VIEWER_USERNAME",
            )
            if (value := os.environ.get(name, "").strip())
        ),
    }
    exact_project_codes = {
        value
        for name in ("FDE_E2E_PROJECT_CODE", "FDE_E2E_RESEARCH_PROJECT_CODE")
        if (value := os.environ.get(name, "").strip())
    }
    exact_template_names = {
        f"phase2.{run_id} 制造业 AI 落地",
        value,
    } if (value := os.environ.get("FDE_E2E_RESEARCH_TEMPLATE_NAME", "").strip()) else {
        f"phase2.{run_id} 制造业 AI 落地"
    }

    app = create_app(settings)
    with app.app_context(), db.engine.begin() as connection:
        preservation_fixture_before = preservation_fixture_fingerprint(connection)
        preserved_admin_before = connection.execute(
            select(
                User.id,
                User.username,
                User.role,
                User.password_hash,
                User.is_active,
                User.must_change_password,
            ).where(User.username == PRESERVED_ADMIN_USERNAME)
        ).one_or_none()
        seed_template_before = connection.scalar(
            select(IndustryTemplate.id).where(
                IndustryTemplate.template_key == GENERIC_TEMPLATE_KEY
            )
        )
        phase_user_ids = list(
            connection.scalars(
                select(User.id).where(User.username.in_(exact_usernames))
            )
        )
        phase_project_ids = list(
            connection.scalars(
                select(Project.id).where(Project.project_code.in_(exact_project_codes))
            )
        )
        unrelated_project_ids = set(
            connection.scalars(select(Project.id).where(Project.id.not_in(phase_project_ids)))
        )
        phase_project_module_ids = list(
            connection.scalars(
                select(ProjectModule.id).where(
                    ProjectModule.project_id.in_(phase_project_ids)
                )
            )
        )
        phase_project_task_ids = list(
            connection.scalars(
                select(ProjectTask.id).where(
                    ProjectTask.project_module_id.in_(phase_project_module_ids)
                )
            )
        )
        phase_template_ids = list(
            connection.scalars(
                select(IndustryTemplate.id).where(
                    IndustryTemplate.name.in_(exact_template_names)
                )
            )
        )
        phase_template_version_ids = list(
            connection.scalars(
                select(IndustryTemplateVersion.id).where(
                    IndustryTemplateVersion.template_id.in_(phase_template_ids)
                )
            )
        )
        phase_template_module_ids = list(
            connection.scalars(
                select(TemplateModule.id).where(
                    TemplateModule.template_version_id.in_(phase_template_version_ids)
                )
            )
        )
        phase_template_task_ids = list(
            connection.scalars(
                select(TemplateTask.id).where(
                    TemplateTask.template_module_id.in_(phase_template_module_ids)
                )
            )
        )
        phase_template_research_form_ids = list(
            connection.scalars(
                select(TemplateResearchForm.id).where(
                    TemplateResearchForm.template_version_id.in_(phase_template_version_ids)
                )
            )
        )
        phase_template_research_section_ids = list(
            connection.scalars(
                select(TemplateResearchSection.id).where(
                    TemplateResearchSection.form_id.in_(phase_template_research_form_ids)
                )
            )
        )
        phase_template_research_field_ids = list(
            connection.scalars(
                select(TemplateResearchField.id).where(
                    TemplateResearchField.section_id.in_(phase_template_research_section_ids)
                )
            )
        )
        phase_research_form_ids = list(
            connection.scalars(
                select(ProjectResearchForm.id).where(
                    ProjectResearchForm.project_id.in_(phase_project_ids)
                )
            )
        )
        phase_revision_ids = list(
            connection.scalars(
                select(ProjectResearchFormRevision.id).where(
                    ProjectResearchFormRevision.form_id.in_(phase_research_form_ids)
                )
            )
        )

        # --- Document rows for the run-scoped projects ----------------------
        # Document tables reference their project / versions with ON DELETE
        # RESTRICT, so they must be removed (child-first) before the Project
        # rows they belong to.  ``project_documents.current_version_id`` and
        # ``project_document_versions.parent_version_id`` are circular self-refs
        # and are nulled first.  The generated DOCX file versions live under the
        # project's ProjectFile rows and are removed by the file section below,
        # so the project_document_versions rows must go first (their
        # ``docx_file_version_id`` references those ProjectFileVersion rows).
        phase_project_document_ids = list(
            connection.scalars(
                select(ProjectDocument.id).where(
                    ProjectDocument.project_id.in_(phase_project_ids)
                )
            )
        )
        phase_project_doc_version_ids = list(
            connection.scalars(
                select(ProjectDocumentVersion.id).where(
                    ProjectDocumentVersion.document_id.in_(phase_project_document_ids)
                )
            )
        )
        connection.execute(
            delete(DocumentGenerationJob).where(
                DocumentGenerationJob.document_version_id.in_(phase_project_doc_version_ids)
            )
        )
        connection.execute(
            update(ProjectDocumentVersion)
            .where(ProjectDocumentVersion.id.in_(phase_project_doc_version_ids))
            .values(parent_version_id=None)
        )
        connection.execute(
            delete(ProjectDocumentVersion).where(
                ProjectDocumentVersion.id.in_(phase_project_doc_version_ids)
            )
        )
        connection.execute(
            update(ProjectDocument)
            .where(ProjectDocument.id.in_(phase_project_document_ids))
            .values(current_version_id=None)
        )
        connection.execute(
            delete(ProjectDocumentDraft).where(
                ProjectDocumentDraft.document_id.in_(phase_project_document_ids)
            )
        )
        connection.execute(
            delete(ProjectDocument).where(
                ProjectDocument.id.in_(phase_project_document_ids)
            )
        )
        # The E2E document spec only uses the globally seeded document templates
        # (published v1 for each catalog key), never a run-scoped template, so no
        # document_templates / document_template_versions rows are removed here.
        # If a future spec creates run-scoped document templates, add the same
        # child-first cascade (template_versions then templates) here.

        # --- File / OSS rows for the run-scoped projects ---------------------
        # Files reference their project with ON DELETE RESTRICT, so they must be
        # removed before the Project rows they belong to.  ProjectFileVersion and
        # ProjectFile hold circular self-references (current_version_id /
        # parent_version_id / preview_version_id), so those are nulled first.
        phase_project_file_ids = list(
            connection.scalars(
                select(ProjectFile.id).where(
                    ProjectFile.project_id.in_(phase_project_ids)
                )
            )
        )
        phase_upload_session_ids = list(
            connection.scalars(
                select(UploadSession.id).where(
                    UploadSession.project_id.in_(phase_project_ids)
                )
            )
        )
        phase_file_version_ids = list(
            connection.scalars(
                select(ProjectFileVersion.id).where(
                    ProjectFileVersion.file_id.in_(phase_project_file_ids)
                )
            )
        )
        # Best-effort abort any in-progress uploads so their storage parts are
        # freed; a storage outage must never break cleanup.
        for storage_prefix, multipart_upload_id in connection.execute(
            select(
                UploadSession.storage_prefix, UploadSession.multipart_upload_id
            ).where(
                UploadSession.project_id.in_(phase_project_ids),
                UploadSession.status == "uploading",
            )
        ):
            try:
                object_storage.current.abort_multipart(
                    storage_prefix, multipart_upload_id
                )
            except Exception:
                pass

        connection.execute(
            update(ProjectFile)
            .where(ProjectFile.id.in_(phase_project_file_ids))
            .values(current_version_id=None)
        )
        connection.execute(
            update(ProjectFileVersion)
            .where(ProjectFileVersion.id.in_(phase_file_version_ids))
            .values(parent_version_id=None)
        )
        connection.execute(
            update(ProjectFileVersion)
            .where(ProjectFileVersion.id.in_(phase_file_version_ids))
            .values(preview_version_id=None)
        )
        connection.execute(
            delete(ProjectFileVersion).where(
                ProjectFileVersion.file_id.in_(phase_project_file_ids)
            )
        )
        connection.execute(
            delete(UploadSession).where(
                UploadSession.id.in_(phase_upload_session_ids)
            )
        )
        connection.execute(
            delete(ProjectFile).where(
                ProjectFile.project_id.in_(phase_project_ids)
            )
        )

        connection.execute(
            delete(OperationEvent).where(
                (OperationEvent.project_id.in_(phase_project_ids))
                | (
                    (OperationEvent.target_type == "industry_template_version")
                    & (OperationEvent.target_id.in_(phase_template_version_ids))
                )
            )
        )
        connection.execute(
            delete(ProjectResearchAnswer).where(
                ProjectResearchAnswer.revision_id.in_(phase_revision_ids)
            )
        )
        connection.execute(
            update(ProjectResearchForm)
            .where(ProjectResearchForm.id.in_(phase_research_form_ids))
            .values(current_revision_id=None)
        )
        connection.execute(
            update(ProjectResearchFormRevision)
            .where(ProjectResearchFormRevision.id.in_(phase_revision_ids))
            .values(parent_revision_id=None)
        )
        connection.execute(
            delete(ProjectResearchFormRevision).where(
                ProjectResearchFormRevision.id.in_(phase_revision_ids)
            )
        )
        connection.execute(
            delete(ProjectResearchForm).where(ProjectResearchForm.id.in_(phase_research_form_ids))
        )
        connection.execute(
            delete(ProjectResearchSubjectLink).where(
                ProjectResearchSubjectLink.project_id.in_(phase_project_ids)
            )
        )
        connection.execute(
            delete(ProjectResearchImportBatch).where(
                ProjectResearchImportBatch.project_id.in_(phase_project_ids)
            )
        )
        connection.execute(
            update(ProjectResearchSubject)
            .where(ProjectResearchSubject.project_id.in_(phase_project_ids))
            .values(parent_subject_id=None)
        )
        connection.execute(
            delete(ProjectResearchSubject).where(
                ProjectResearchSubject.project_id.in_(phase_project_ids)
            )
        )
        connection.execute(
            delete(ProjectTaskDependency).where(
                or_(
                    ProjectTaskDependency.predecessor_task_id.in_(
                        phase_project_task_ids
                    ),
                    ProjectTaskDependency.successor_task_id.in_(phase_project_task_ids),
                )
            )
        )
        connection.execute(
            delete(ProjectTaskCollaborator).where(
                ProjectTaskCollaborator.task_id.in_(phase_project_task_ids)
            )
        )
        connection.execute(
            delete(ProjectTask).where(ProjectTask.id.in_(phase_project_task_ids))
        )
        connection.execute(
            delete(ProjectModule).where(ProjectModule.id.in_(phase_project_module_ids))
        )
        connection.execute(
            delete(ProjectMember).where(
                ProjectMember.project_id.in_(phase_project_ids)
            )
        )
        connection.execute(delete(Project).where(Project.id.in_(phase_project_ids)))
        connection.execute(
            delete(TemplateResearchField).where(
                TemplateResearchField.id.in_(phase_template_research_field_ids)
            )
        )
        connection.execute(
            delete(TemplateResearchSection).where(
                TemplateResearchSection.id.in_(phase_template_research_section_ids)
            )
        )
        connection.execute(
            delete(TemplateResearchForm).where(
                TemplateResearchForm.id.in_(phase_template_research_form_ids)
            )
        )
        connection.execute(
            delete(TemplateTaskDependency).where(
                or_(
                    TemplateTaskDependency.predecessor_task_id.in_(
                        phase_template_task_ids
                    ),
                    TemplateTaskDependency.successor_task_id.in_(
                        phase_template_task_ids
                    ),
                )
            )
        )
        connection.execute(
            delete(TemplateTask).where(TemplateTask.id.in_(phase_template_task_ids))
        )
        connection.execute(
            delete(TemplateModule).where(
                TemplateModule.id.in_(phase_template_module_ids)
            )
        )
        connection.execute(
            delete(IndustryTemplateVersion).where(
                IndustryTemplateVersion.id.in_(phase_template_version_ids)
            )
        )
        connection.execute(
            delete(IndustryTemplate).where(IndustryTemplate.id.in_(phase_template_ids))
        )
        connection.execute(
            delete(RefreshSession).where(RefreshSession.user_id.in_(phase_user_ids))
        )
        connection.execute(delete(User).where(User.id.in_(phase_user_ids)))

        remaining_targets = {
            "users": connection.scalar(select(text("COUNT(*)")).select_from(User).where(User.id.in_(phase_user_ids))),
            "projects": connection.scalar(select(text("COUNT(*)")).select_from(Project).where(Project.id.in_(phase_project_ids))),
            "templates": connection.scalar(select(text("COUNT(*)")).select_from(IndustryTemplate).where(IndustryTemplate.id.in_(phase_template_ids))),
            "project_files": connection.scalar(
                select(text("COUNT(*)")).select_from(ProjectFile).where(
                    ProjectFile.project_id.in_(phase_project_ids)
                )
            ),
            "project_file_versions": connection.scalar(
                select(text("COUNT(*)")).select_from(ProjectFileVersion).where(
                    ProjectFileVersion.file_id.in_(phase_project_file_ids)
                )
            ),
            "upload_sessions": connection.scalar(
                select(text("COUNT(*)")).select_from(UploadSession).where(
                    UploadSession.project_id.in_(phase_project_ids)
                )
            ),
            "project_documents": connection.scalar(
                select(text("COUNT(*)")).select_from(ProjectDocument).where(
                    ProjectDocument.project_id.in_(phase_project_ids)
                )
            ),
            "project_document_versions": connection.scalar(
                select(text("COUNT(*)")).select_from(ProjectDocumentVersion).where(
                    ProjectDocumentVersion.document_id.in_(phase_project_document_ids)
                )
            ),
            "project_document_drafts": connection.scalar(
                select(text("COUNT(*)")).select_from(ProjectDocumentDraft).where(
                    ProjectDocumentDraft.document_id.in_(phase_project_document_ids)
                )
            ),
            "document_generation_jobs": connection.scalar(
                select(text("COUNT(*)")).select_from(DocumentGenerationJob).where(
                    DocumentGenerationJob.document_version_id.in_(phase_project_doc_version_ids)
                )
            ),
        }
        if any(remaining_targets.values()):
            raise RuntimeError("Research E2E cleanup left rows owned by the current run.")

        if set(connection.scalars(select(Project.id).where(Project.id.in_(unrelated_project_ids)))) != unrelated_project_ids:
            raise RuntimeError("Research E2E cleanup changed an unrelated fixture project.")
        if preservation_fixture_fingerprint(connection) != preservation_fixture_before:
            raise RuntimeError("Research E2E cleanup changed unrelated fixture contents.")
        if preserved_admin_before is not None:
            preserved_admin_after = connection.execute(
                select(
                    User.id,
                    User.username,
                    User.role,
                    User.password_hash,
                    User.is_active,
                    User.must_change_password,
                ).where(User.username == PRESERVED_ADMIN_USERNAME)
            ).one_or_none()
            if preserved_admin_after is None or tuple(preserved_admin_after) != tuple(preserved_admin_before):
                raise RuntimeError("Research E2E cleanup changed the seeded administrator.")
        if seed_template_before is not None and connection.scalar(
            select(IndustryTemplate.id).where(
                IndustryTemplate.template_key == GENERIC_TEMPLATE_KEY
            )
        ) != seed_template_before:
            raise RuntimeError("Research E2E cleanup changed the unrelated seeded template.")


def ensure_preservation_fixtures(settings: Settings) -> None:
    fixture_password = os.environ.get("FDE_E2E_PRESERVED_ADMIN_PASSWORD")
    if not fixture_password:
        raise SystemExit("FDE_E2E_PRESERVED_ADMIN_PASSWORD is required.")
    app = create_app(settings)
    with app.app_context():
        session = db.session()
        try:
            with session.begin():
                admin = session.scalar(
                    select(User).where(User.username == PRESERVED_ADMIN_USERNAME)
                )
                if admin is None:
                    admin = User(
                        id=PRESERVED_ADMIN_ID,
                        username=PRESERVED_ADMIN_USERNAME,
                        display_name="Preserved Administrator",
                        role="admin",
                        password_hash=hash_password(fixture_password),
                        must_change_password=True,
                        is_active=True,
                    )
                    session.add(admin)
                    session.flush()
                project = session.scalar(
                    select(Project).where(
                        Project.project_code == UNRELATED_FIXTURE_PROJECT_CODE
                    )
                )
                if project is not None:
                    return
                template_version = session.scalar(
                    select(IndustryTemplateVersion)
                    .join(
                        IndustryTemplate,
                        IndustryTemplate.id == IndustryTemplateVersion.template_id,
                    )
                    .where(
                        IndustryTemplate.template_key == GENERIC_TEMPLATE_KEY,
                        IndustryTemplateVersion.status == "published",
                    )
                    .order_by(IndustryTemplateVersion.version_number.desc())
                )
                if template_version is None:
                    raise RuntimeError("The unrelated fixture requires the generic seeded template.")
                project = Project(
                    project_code=UNRELATED_FIXTURE_PROJECT_CODE,
                    name="Unrelated research cleanup fixture",
                    enterprise_name="Unrelated fixture enterprise",
                    status="draft",
                    planned_start_date=date(2026, 1, 1),
                    leader_user_id=admin.id,
                    source_template_version_id=template_version.id,
                    template_snapshot={"fixture": True},
                    research_snapshot={"forms": []},
                )
                session.add(project)
                session.flush()
                session.add_all(
                    [
                        ProjectMember(project_id=project.id, user_id=admin.id, role="member"),
                        ProjectResearchSubject(
                            project_id=project.id,
                            subject_type="project",
                            subject_key="project",
                            name=project.name,
                            description="",
                            sort_order=0,
                            status="active",
                        ),
                        OperationEvent(
                            actor_user_id=admin.id,
                            project_id=project.id,
                            target_type="project",
                            target_id=project.id,
                            event_type="unrelated_fixture_created",
                            changes={"fixture": True},
                        ),
                    ]
                )
        finally:
            session.close()


def verify_preservation_fingerprint(settings: Settings) -> None:
    app = create_app(settings)
    with app.app_context(), db.engine.connect() as connection:
        serialized = preservation_fixture_fingerprint(connection)
    if serialized is None:
        raise RuntimeError("The unrelated preservation fixture is missing.")
    fingerprint = json.loads(serialized)
    if set(fingerprint) != set(PRESERVATION_FINGERPRINT_MODELS):
        raise RuntimeError("The preservation fingerprint table coverage is incomplete.")
    for key, model in PRESERVATION_FINGERPRINT_MODELS.items():
        expected_columns = {column.name for column in model.__table__.c}
        if any(set(row) != expected_columns for row in fingerprint[key]):
            raise RuntimeError(f"The preservation fingerprint column coverage is incomplete for {key}.")
    required_counts = {
        "admin": 1,
        "template": 1,
        "project": 1,
        "project_members": 1,
        "project_subjects": 1,
        "project_events": 1,
    }
    if any(len(fingerprint.get(key, [])) != count for key, count in required_counts.items()):
        raise RuntimeError("The unrelated preservation fixture is incomplete.")
    if not fingerprint.get("template_versions") or not fingerprint.get("template_modules"):
        raise RuntimeError("The generic template preservation fixture is incomplete.")
    print("preservation_fingerprint=ok canonical_json=true full_columns=true")


def verify_research_history(settings: Settings) -> None:
    project_code = os.environ.get("FDE_E2E_RESEARCH_PROJECT_CODE", "").strip()
    if not project_code:
        raise SystemExit("FDE_E2E_RESEARCH_PROJECT_CODE is required.")
    app = create_app(settings)
    with app.app_context(), db.engine.connect() as connection:
        project = connection.execute(
            select(Project.id, Project.research_snapshot).where(
                Project.project_code == project_code
            )
        ).one_or_none()
        if project is None:
            raise RuntimeError("Research E2E history verification could not find the project.")
        form = connection.execute(
            select(ProjectResearchForm.id, ProjectResearchForm.current_revision_id).where(
                ProjectResearchForm.project_id == project.id,
                ProjectResearchForm.form_key == "role_profile",
            )
        ).one_or_none()
        if form is None:
            raise RuntimeError("Research E2E history verification could not find the role form.")
        revisions = connection.execute(
            select(
                ProjectResearchFormRevision.id,
                ProjectResearchFormRevision.revision_number,
                ProjectResearchFormRevision.status,
                ProjectResearchFormRevision.parent_revision_id,
            )
            .where(ProjectResearchFormRevision.form_id == form.id)
            .order_by(ProjectResearchFormRevision.revision_number)
        ).all()
        if len(revisions) != 2:
            raise RuntimeError("Research E2E history verification expected exactly two revisions.")
        parent, child = revisions
        if (
            parent.revision_number != 1
            or parent.status != "confirmed"
            or parent.parent_revision_id is not None
            or child.revision_number != 2
            or child.status != "confirmed"
            or child.parent_revision_id != parent.id
            or form.current_revision_id != child.id
        ):
            raise RuntimeError("Research E2E revision lineage or confirmed status changed.")
        answer_rows = connection.execute(
            select(
                ProjectResearchAnswer.revision_id,
                ProjectResearchAnswer.value_json,
            ).where(
                ProjectResearchAnswer.revision_id.in_([parent.id, child.id]),
                ProjectResearchAnswer.field_key == "legacy_role_note",
            )
        ).all()
        answers = {row.revision_id: row.value_json for row in answer_rows}
        if answers != {
            parent.id: "优化出入库协同",
            child.id: "修订后的岗位答案",
        }:
            raise RuntimeError("Research E2E confirmed parent answer was modified.")
        names = {
            field.get("name")
            for form_snapshot in project.research_snapshot.get("forms", [])
            for section in form_snapshot.get("sections", [])
            for field in section.get("fields", [])
            if isinstance(field, dict)
        }
        if "旧版岗位字段" not in names or "新版岗位字段" in names:
            raise RuntimeError("Research E2E project snapshot did not remain frozen.")


def verify_upgrade_preservation(settings: Settings) -> None:
    fixture_password = os.environ.get("FDE_E2E_PRESERVED_ADMIN_PASSWORD")
    if not fixture_password:
        raise SystemExit("FDE_E2E_PRESERVED_ADMIN_PASSWORD is required.")

    config = Config(str(SERVER_ROOT / "alembic.ini"))
    config.attributes["settings"] = settings
    engine = None
    try:
        command.downgrade(config, "0002_add_user_auth_version")
        from sqlalchemy import create_engine

        engine = create_engine(settings.database_url)
        with engine.begin() as connection:
            fixture = connection.execute(
                text(
                    "SELECT id, username, role, password_hash, is_active, "
                    "must_change_password FROM users WHERE username = :username"
                ),
                {"username": PRESERVED_ADMIN_USERNAME},
            ).one_or_none()
            if fixture is None:
                connection.execute(
                    text(
                        "INSERT INTO users "
                        "(id, username, display_name, role, password_hash, "
                        "must_change_password, is_active, auth_version) "
                        "VALUES (:id, :username, 'Preserved Administrator', 'admin', "
                        ":password_hash, 1, 1, 1)"
                    ),
                    {
                        "id": PRESERVED_ADMIN_ID,
                        "username": PRESERVED_ADMIN_USERNAME,
                        "password_hash": hash_password(fixture_password),
                    },
                )
                fixture = connection.execute(
                    text(
                        "SELECT id, username, role, password_hash, is_active, "
                        "must_change_password FROM users WHERE username = :username"
                    ),
                    {"username": PRESERVED_ADMIN_USERNAME},
                ).one()
            before = tuple(fixture)

        command.upgrade(config, "head")
        app = create_app(settings)
        with app.app_context():
            session = db.session()
            try:
                with session.begin():
                    seed_workbench(session)
            finally:
                session.close()

        with engine.connect() as connection:
            after = connection.execute(
                text(
                    "SELECT id, username, role, password_hash, is_active, "
                    "must_change_password FROM users WHERE username = :username"
                ),
                {"username": PRESERVED_ADMIN_USERNAME},
            ).one_or_none()
        if after is None or tuple(after) != before:
            raise RuntimeError(
                "Upgrade preservation failed for the existing administrator fixture."
            )
        print(
            "upgrade_preservation=ok "
            "fields=id,username,role,password_hash,is_active,must_change_password"
        )
    finally:
        command.upgrade(config, "head")
        if engine is not None:
            engine.dispose()


settings = require_test_settings()
if sys.argv[1:] == ["--verify-upgrade-preservation"]:
    verify_upgrade_preservation(settings)
elif sys.argv[1:] == ["--ensure-preservation-fixtures"]:
    ensure_preservation_fixtures(settings)
elif sys.argv[1:] == ["--verify-preservation-fingerprint"]:
    verify_preservation_fingerprint(settings)
elif sys.argv[1:] == ["--verify-research-history"]:
    verify_research_history(settings)
elif sys.argv[1:]:
    raise SystemExit("Unsupported cleanup.py arguments.")
else:
    cleanup_test_rows(settings)
