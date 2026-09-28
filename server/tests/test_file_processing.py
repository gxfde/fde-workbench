from __future__ import annotations

import io
from datetime import date
from uuid import uuid4

from fde_api.auth.models import User
from fde_api.extensions import object_storage
from fde_api.files.models import ProjectFile, ProjectFileVersion
from fde_api.files.names import extension_of, safe_filename
from fde_api.files.processors import process_file, register_file_scan_handler
from fde_api.files.scanner import ScanResult
from fde_api.jobs.handlers import get_handler
from fde_api.workbench.models import IndustryTemplate, IndustryTemplateVersion, Project


class CleanScanner:
    def scan(self, stream):
        return ScanResult(clean=True, status="clean", signature=None)


class InfectedScanner:
    def scan(self, stream):
        return ScanResult(clean=False, status="infected", signature="Eicar-Test-Signature")


class ErrorScanner:
    def scan(self, stream):
        return ScanResult(clean=False, status="error", signature=None)


CLEAN_ZIP = b"PK\x03\x04" + b"\x00" * 128
VALID_PDF = b"%PDF-1.7\n" + b"\x00" * 128


def _seed_version(db_session, *, filename, data, status="uploading", scan_status="pending"):
    leader = User(
        username=f"files.lead.{uuid4().hex}",
        display_name="文件负责人",
        role="project_lead",
        password_hash="x",
        must_change_password=False,
        is_active=True,
    )
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
        id="p1",
        project_code=f"FDE-FP-{uuid4().hex[:8]}",
        name="文件项目",
        enterprise_name="星河制造",
        leader=leader,
        source_template_version=template_version,
        template_snapshot={},
        planned_start_date=date(2026, 8, 22),
    )
    db_session.add_all([leader, template, template_version, project])
    db_session.flush()

    project_file = ProjectFile(
        id="f1",
        project=project,
        category="attachment",
        display_name=filename,
        description="",
        created_by=leader,
    )
    db_session.add(project_file)
    db_session.flush()

    safe = safe_filename(filename)
    storage_key = f"projects/{project.id}/temporary/{leader.id}/{safe}"
    version = ProjectFileVersion(
        id="v1",
        project_file=project_file,
        version_number=1,
        source="upload",
        original_filename=filename,
        safe_filename=safe,
        extension=extension_of(filename),
        mime_type="",
        bucket="local",
        storage_key=storage_key,
        size_bytes=len(data),
        etag="",
        sha256="",
        uploaded_by=leader,
        status=status,
        scan_status=scan_status,
        preview_status="none",
    )
    db_session.add(version)
    db_session.flush()
    project_file.current_version_id = version.id
    db_session.commit()

    object_storage.current.put_stream(
        storage_key, io.BytesIO(data), "application/octet-stream", {}
    )
    return project_file, version


def test_clean_file_is_promoted_to_available(db_session):
    project_file, version = _seed_version(
        db_session, filename="report.docx", data=CLEAN_ZIP
    )

    result = process_file(version_id=version.id, scanner=CleanScanner())

    assert result.status == "available"
    assert result.scan_status == "clean"
    assert result.error_code == ""
    db_session.refresh(version)
    assert version.status == "available"
    assert version.scan_status == "clean"
    assert version.storage_key == "projects/p1/attachments/f1/versions/v1/report.docx"
    assert version.storage_key.startswith("projects/p1/attachments/")
    assert version.sha256 != ""
    assert version.etag != ""
    assert version.size_bytes == len(CLEAN_ZIP)
    db_session.refresh(project_file)
    assert project_file.current_version_id == version.id


def test_infected_file_remains_unavailable(db_session):
    project_file, version = _seed_version(
        db_session, filename="report.pdf", data=VALID_PDF
    )

    result = process_file(version_id=version.id, scanner=InfectedScanner())

    assert result.status == "rejected"
    assert result.scan_status == "infected"
    assert result.error_code == "infected"
    db_session.refresh(version)
    assert version.status == "rejected"
    assert version.scan_status == "infected"
    assert version.storage_key.startswith("projects/p1/temporary/")
    assert not version.storage_key.startswith("projects/p1/attachments/")


def test_extension_magic_mismatch_is_rejected(db_session):
    project_file, version = _seed_version(
        db_session, filename="report.pdf", data=b"MZ" + b"0" * 512
    )

    result = process_file(version_id=version.id, scanner=CleanScanner())

    assert result.status == "rejected"
    assert result.error_code == "file_type_mismatch"
    db_session.refresh(version)
    assert version.status == "rejected"
    assert version.scan_status == "error"
    assert version.storage_key.startswith("projects/p1/temporary/")


def test_scanner_error_keeps_quarantined(db_session):
    project_file, version = _seed_version(
        db_session, filename="report.pdf", data=VALID_PDF
    )

    result = process_file(version_id=version.id, scanner=ErrorScanner())

    assert result.status == "quarantined"
    assert result.scan_status == "error"
    db_session.refresh(version)
    assert version.status == "quarantined"
    assert version.scan_status == "error"
    assert not version.storage_key.startswith("projects/p1/attachments/")


def test_registered_file_scan_handler_is_idempotent(db_session, monkeypatch):
    register_file_scan_handler()
    assert get_handler("file.scan") is not None

    project_file, version = _seed_version(
        db_session, filename="report.docx", data=CLEAN_ZIP
    )

    storage = object_storage.current
    real_copy = storage.copy
    calls = {"count": 0}

    def counting_copy(source_key: str, target_key: str):
        calls["count"] += 1
        return real_copy(source_key, target_key)

    monkeypatch.setattr(storage, "copy", counting_copy)

    first = process_file(version_id=version.id, scanner=CleanScanner())
    second = process_file(version_id=version.id, scanner=CleanScanner())

    assert first.status == "available"
    assert second.status == "available"
    assert first.storage_key == second.storage_key == "projects/p1/attachments/f1/versions/v1/report.docx"
    assert calls["count"] == 1
    db_session.refresh(version)
    assert version.status == "available"
    assert version.scan_status == "clean"
