from datetime import date

import pytest
from sqlalchemy import inspect
from sqlalchemy.exc import DBAPIError, IntegrityError

from fde_api.auth.models import Base, User
from fde_api.documents.models import (
    DOCUMENT_TYPE_KEYS,
    DOCUMENT_VERSION_SOURCES,
    DocumentGenerationJob,
    DocumentTemplate,
    DocumentTemplateVersion,
    ProjectDocument,
    ProjectDocumentDraft,
    ProjectDocumentVersion,
)
from fde_api.files.models import ProjectFile, ProjectFileVersion
from fde_api.workbench.models import IndustryTemplate, IndustryTemplateVersion, Project


def _persisted_project(db_session, *, code="FDE-DOC-001"):
    leader = User(username="doc.lead", password_hash="x", role="project_lead")
    template = IndustryTemplate(name="文档模板", industry_name="制造")
    template_version = IndustryTemplateVersion(
        template=template,
        name=template.name,
        industry_name=template.industry_name,
        description="",
        version_number=1,
        status="published",
        published_by=leader,
    )
    project = Project(
        project_code=code,
        name="文档项目",
        enterprise_name="星河制造",
        leader=leader,
        source_template_version=template_version,
        template_snapshot={},
        planned_start_date=date(2026, 8, 22),
    )
    db_session.add(project)
    db_session.commit()
    return project, leader


def _doc_template(db_session, leader, *, document_type="sow", version_number=1):
    template = DocumentTemplate(
        document_type=document_type,
        name="SOW 模板",
        description="",
        industry_name="制造",
    )
    db_session.add(template)
    db_session.flush()
    template_version = DocumentTemplateVersion(
        template=template,
        version_number=version_number,
        status="published",
        created_by=leader,
    )
    db_session.add(template_version)
    db_session.flush()
    return template, template_version


def _persisted_doc_grant(
    db_session, project, leader, *, template_version, business_code="SOW-0001"
):
    document = ProjectDocument(
        project=project,
        document_type=template_version.template.document_type,
        business_code=business_code,
        source_template_version=template_version,
        owner=leader,
    )
    db_session.add(document)
    db_session.commit()
    return document


def _persisted_docx_version(
    db_session, project, leader, *, original="需求文档.docx"
):
    project_file = ProjectFile(
        project=project,
        category="document",
        display_name=original,
        description="",
        created_by=leader,
    )
    db_session.add(project_file)
    db_session.flush()
    file_version = ProjectFileVersion(
        project_file=project_file,
        version_number=1,
        source="upload",
        original_filename=original,
        safe_filename=original,
        extension=".docx",
        mime_type=(
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        ),
        bucket="fde-test-bucket",
        storage_key=(
            f"projects/{project.id}/documents/{project_file.id}/versions/v1/{original}"
        ),
        size_bytes=1024,
        uploaded_by=leader,
        status="available",
        scan_status="clean",
        preview_status="none",
    )
    db_session.add(file_version)
    db_session.flush()
    project_file.current_version_id = file_version.id
    db_session.commit()
    return project_file, file_version


def _persisted_document_version(
    db_session,
    document,
    leader,
    *,
    template_version,
    docx_file_version,
    version_number=1,
    source="generated",
    status="draft",
):
    version = ProjectDocumentVersion(
        document=document,
        version_number=version_number,
        source=source,
        status=status,
        source_template_version=template_version,
        source_snapshot_json={},
        content_snapshot_json={},
        docx_file=docx_file_version,
        sha256="",
        generated_by=leader,
    )
    db_session.add(version)
    db_session.commit()
    return version


def test_document_models_share_workbench_metadata():
    expected_tables = {
        "document_templates",
        "document_template_versions",
        "project_documents",
        "project_document_drafts",
        "project_document_versions",
        "document_generation_jobs",
    }
    assert expected_tables <= set(Base.metadata.tables)
    assert DocumentTemplate.metadata is Base.metadata
    assert DocumentGenerationJob.metadata is Base.metadata


def test_document_type_keys_and_version_sources_are_frozen():
    assert len(DOCUMENT_TYPE_KEYS) == 17
    assert set(DOCUMENT_VERSION_SOURCES) == {"generated", "online_revised", "manual_upload"}


def test_business_code_is_unique_per_project(db_session):
    project, leader = _persisted_project(db_session)
    _, template_version = _doc_template(db_session, leader)
    _persisted_doc_grant(
        db_session, project, leader, template_version=template_version, business_code="SOW-0001"
    )
    db_session.add(
        ProjectDocument(
            project=project,
            document_type="sow",
            business_code="SOW-0001",
            source_template_version=template_version,
            owner=leader,
        )
    )

    with pytest.raises(IntegrityError):
        db_session.commit()


def test_document_version_number_is_unique_per_document(db_session):
    project, leader = _persisted_project(db_session)
    _, template_version = _doc_template(db_session, leader)
    document = _persisted_doc_grant(
        db_session, project, leader, template_version=template_version
    )
    _, docx_file_version = _persisted_docx_version(db_session, project, leader)
    _persisted_document_version(
        db_session,
        document,
        leader,
        template_version=template_version,
        docx_file_version=docx_file_version,
        version_number=1,
    )
    db_session.add(
        ProjectDocumentVersion(
            document=document,
            version_number=1,
            source_template_version=template_version,
            docx_file=docx_file_version,
            generated_by=leader,
        )
    )

    with pytest.raises(IntegrityError):
        db_session.commit()


def test_document_template_version_is_unique_per_template(db_session):
    project, leader = _persisted_project(db_session)
    template, _ = _doc_template(db_session, leader)
    db_session.add(
        DocumentTemplateVersion(
            template=template,
            version_number=1,
            status="published",
            created_by=leader,
        )
    )

    with pytest.raises(IntegrityError):
        db_session.commit()


def test_database_rejects_unknown_document_version_source(db_session):
    project, leader = _persisted_project(db_session)
    _, template_version = _doc_template(db_session, leader)
    document = _persisted_doc_grant(
        db_session, project, leader, template_version=template_version
    )
    _, docx_file_version = _persisted_docx_version(db_session, project, leader)
    db_session.add(
        ProjectDocumentVersion(
            document=document,
            version_number=1,
            source="overwritten",
            source_template_version=template_version,
            docx_file=docx_file_version,
            generated_by=leader,
        )
    )

    with pytest.raises(DBAPIError):
        db_session.commit()


def test_database_rejects_unknown_document_version_status(db_session):
    project, leader = _persisted_project(db_session)
    _, template_version = _doc_template(db_session, leader)
    document = _persisted_doc_grant(
        db_session, project, leader, template_version=template_version
    )
    _, docx_file_version = _persisted_docx_version(db_session, project, leader)
    db_session.add(
        ProjectDocumentVersion(
            document=document,
            version_number=1,
            status="published",
            source_template_version=template_version,
            docx_file=docx_file_version,
            generated_by=leader,
        )
    )

    with pytest.raises(DBAPIError):
        db_session.commit()


def test_document_draft_is_unique_per_document(db_session):
    project, leader = _persisted_project(db_session)
    _, template_version = _doc_template(db_session, leader)
    document = _persisted_doc_grant(
        db_session, project, leader, template_version=template_version
    )
    db_session.add(ProjectDocumentDraft(document=document))
    db_session.commit()
    db_session.add(ProjectDocumentDraft(document=document))

    with pytest.raises(IntegrityError):
        db_session.commit()


def test_document_fks_are_restrict(db_session):
    database = inspect(db_session.bind)

    template_version_foreign_keys = database.get_foreign_keys("document_template_versions")
    template_docx_foreign_key = next(
        foreign_key
        for foreign_key in template_version_foreign_keys
        if foreign_key["constrained_columns"] == ["docx_file_version_id"]
    )
    assert template_docx_foreign_key["referred_table"] == "project_file_versions"
    assert template_docx_foreign_key["options"].get("ondelete") == "RESTRICT"

    version_foreign_keys = database.get_foreign_keys("project_document_versions")
    version_docx_foreign_key = next(
        foreign_key
        for foreign_key in version_foreign_keys
        if foreign_key["constrained_columns"] == ["docx_file_version_id"]
    )
    assert version_docx_foreign_key["referred_table"] == "project_file_versions"
    assert version_docx_foreign_key["options"].get("ondelete") == "RESTRICT"

    document_foreign_keys = database.get_foreign_keys("project_documents")
    project_foreign_key = next(
        foreign_key
        for foreign_key in document_foreign_keys
        if foreign_key["constrained_columns"] == ["project_id"]
    )
    assert project_foreign_key["referred_table"] == "projects"
    assert project_foreign_key["options"].get("ondelete") == "RESTRICT"
