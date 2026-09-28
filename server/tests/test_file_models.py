from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import inspect
from sqlalchemy.exc import DBAPIError, IntegrityError

from fde_api.auth.models import Base, User
from fde_api.files.models import ProjectFile, ProjectFileVersion, UploadSession
from fde_api.workbench.models import IndustryTemplate, IndustryTemplateVersion, Project


def _persisted_project(db_session, *, code="FDE-FILES-001"):
    leader = User(username="files.lead", password_hash="x", role="project_lead")
    template = IndustryTemplate(name="文件模板", industry_name="制造")
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
        name="文件项目",
        enterprise_name="星河制造",
        leader=leader,
        source_template_version=template_version,
        template_snapshot={},
        planned_start_date=date(2026, 8, 22),
    )
    db_session.add(project)
    db_session.commit()
    return project, leader


def _persisted_file(
    db_session,
    project,
    leader,
    *,
    display_name="需求文档.docx",
    version_number=1,
    status="available",
):
    project_file = ProjectFile(
        project=project,
        category="attachment",
        display_name=display_name,
        description="",
        created_by=leader,
    )
    db_session.add(project_file)
    db_session.flush()
    version = ProjectFileVersion(
        project_file=project_file,
        version_number=version_number,
        source="upload",
        original_filename=display_name,
        safe_filename="需求_文档.docx",
        extension=".docx",
        mime_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        bucket="fde-test-bucket",
        storage_key=(
            f"projects/{project.id}/attachments/{project_file.id}/"
            f"versions/v{version_number}/需求_文档.docx"
        ),
        size_bytes=1024,
        uploaded_by=leader,
        status=status,
        scan_status="clean",
        preview_status="none",
    )
    db_session.add(version)
    db_session.flush()
    project_file.current_version_id = version.id
    db_session.commit()
    return project_file, version


def test_file_models_share_workbench_metadata():
    expected_tables = {
        "project_files",
        "project_file_versions",
        "upload_sessions",
    }
    assert expected_tables <= set(Base.metadata.tables)
    assert ProjectFile.metadata is Base.metadata
    assert ProjectFileVersion.metadata is Base.metadata
    assert UploadSession.metadata is Base.metadata


def test_file_version_number_is_unique_per_file(db_session):
    project, leader = _persisted_project(db_session)
    _, first_version = _persisted_file(db_session, project, leader, version_number=1)
    db_session.add(
        ProjectFileVersion(
            project_file=first_version.project_file,
            version_number=1,
            original_filename="重复.docx",
            safe_filename="重复.docx",
            bucket="fde-test-bucket",
            storage_key="projects/p1/attachments/f1/versions/v1/重复.docx",
            size_bytes=1,
            uploaded_by=leader,
        )
    )

    with pytest.raises(IntegrityError):
        db_session.commit()


def test_project_file_is_unique_per_project_category_and_display_name(db_session):
    project, leader = _persisted_project(db_session)
    _persisted_file(db_session, project, leader, display_name="需求文档.docx")
    db_session.add(
        ProjectFile(
            project=project,
            category="attachment",
            display_name="需求文档.docx",
            description="",
            created_by=leader,
        )
    )

    with pytest.raises(IntegrityError):
        db_session.commit()


def test_upload_session_idempotency_key_is_unique_per_project(db_session):
    project, leader = _persisted_project(db_session)
    base = {
        "project": project,
        "name": "需求文档.docx",
        "expected_size_bytes": 1024,
        "bucket": "fde-test-bucket",
        "storage_prefix": f"projects/{project.id}/temporary/up1",
        "multipart_upload_id": "mpu-1",
        "expires_at": datetime.now(UTC) + timedelta(hours=1),
        "requested_by": leader,
        "idempotency_key": "idem-1",
    }
    db_session.add(UploadSession(**base))
    db_session.commit()
    db_session.add(UploadSession(**base))

    with pytest.raises(IntegrityError):
        db_session.commit()


def test_database_rejects_unknown_file_version_status(db_session):
    project, leader = _persisted_project(db_session)
    db_session.add(
        ProjectFileVersion(
            project_file=ProjectFile(
                project=project, category="attachment", display_name="x.exe",
                created_by=leader,
            ),
            version_number=1,
            original_filename="x.exe",
            safe_filename="x.exe",
            bucket="fde-test-bucket",
            storage_key="projects/p1/attachments/f1/versions/v1/x.exe",
            size_bytes=1,
            uploaded_by=leader,
            status="obsolete",
        )
    )

    with pytest.raises(DBAPIError):
        db_session.commit()


def test_database_rejects_unknown_file_scan_status(db_session):
    project, leader = _persisted_project(db_session)
    project_file, _ = _persisted_file(db_session, project, leader)
    version = ProjectFileVersion(
        project_file=project_file,
        version_number=2,
        original_filename="b.pdf",
        safe_filename="b.pdf",
        bucket="fde-test-bucket",
        storage_key="projects/p1/attachments/f1/versions/v2/b.pdf",
        size_bytes=1,
        uploaded_by=leader,
        scan_status="scanned",
    )
    db_session.add(version)

    with pytest.raises(DBAPIError):
        db_session.commit()


def test_database_rejects_nonpositive_file_version_number(db_session):
    project, leader = _persisted_project(db_session)
    project_file, _ = _persisted_file(db_session, project, leader)
    db_session.add(
        ProjectFileVersion(
            project_file=project_file,
            version_number=0,
            original_filename="c.txt",
            safe_filename="c.txt",
            bucket="fde-test-bucket",
            storage_key="projects/p1/attachments/f1/versions/v0/c.txt",
            size_bytes=1,
            uploaded_by=leader,
        )
    )

    with pytest.raises(DBAPIError):
        db_session.commit()


def test_file_database_exposes_indexes_and_restrict_foreign_keys(db_session):
    database = inspect(db_session.bind)

    assert {index["name"] for index in database.get_indexes("project_files")} >= {
        "ix_project_files_project_id",
        "ix_project_files_project_status",
    }
    assert {index["name"] for index in database.get_indexes("project_file_versions")} >= {
        "ix_project_file_versions_file_id",
        "ix_project_file_versions_status",
    }
    assert {index["name"] for index in database.get_indexes("upload_sessions")} >= {
        "ix_upload_sessions_project_status",
        "ix_upload_sessions_expires_at",
    }

    version_foreign_keys = database.get_foreign_keys("project_file_versions")
    file_foreign_key = next(
        fk for fk in version_foreign_keys if fk["constrained_columns"] == ["file_id"]
    )
    assert file_foreign_key["referred_table"] == "project_files"
    assert file_foreign_key["options"].get("ondelete") == "RESTRICT"

    session_foreign_keys = database.get_foreign_keys("upload_sessions")
    project_foreign_key = next(
        fk for fk in session_foreign_keys if fk["constrained_columns"] == ["project_id"]
    )
    assert project_foreign_key["referred_table"] == "projects"
    assert project_foreign_key["options"].get("ondelete") == "RESTRICT"
