from __future__ import annotations

import io
import subprocess
from datetime import date
from uuid import uuid4

from fde_api.auth.models import User
from fde_api.extensions import object_storage
from fde_api.files.models import ProjectFile, ProjectFileVersion
from fde_api.files.names import attachment_key, extension_of, safe_filename
from fde_api.files.previews import generate_preview
from fde_api.files.service import _next_version_number, list_file_versions
from fde_api.workbench.models import IndustryTemplate, IndustryTemplateVersion, Project

VALID_PDF = b"%PDF-1.7\n" + b"\x00" * 128


def _seed_version(
    db_session,
    *,
    filename,
    data,
    status="available",
    scan_status="clean",
    project_id="p1",
    file_id="f1",
    version_id="v1",
    version_number=1,
):
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
        id=project_id,
        project_code=f"FDE-PREV-{uuid4().hex[:8]}",
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
        id=file_id,
        project=project,
        category="attachment",
        display_name=filename,
        description="",
        created_by=leader,
    )
    db_session.add(project_file)
    db_session.flush()

    safe = safe_filename(filename)
    storage_key = attachment_key(project.id, file_id, f"v{version_number}", safe)
    version = ProjectFileVersion(
        id=version_id,
        project_file=project_file,
        version_number=version_number,
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


def _timeout_runner(input_path, output_dir):
    raise subprocess.TimeoutExpired(cmd="libreoffice", timeout=120)


def test_libreoffice_timeout_preserves_downloadable_original(db_session):
    project_file, version = _seed_version(
        db_session, filename="report.docx", data=b"docx-bytes"
    )

    result = generate_preview(version.id, runner=_timeout_runner)

    assert result["preview_status"] == "failed"
    db_session.refresh(version)
    assert version.status == "available"
    assert version.preview_status == "failed"


def test_direct_pdf_preview_sets_ready(db_session):
    project_file, version = _seed_version(
        db_session, filename="report.pdf", data=VALID_PDF
    )

    result = generate_preview(version.id)

    assert result["preview_status"] == "ready"
    db_session.refresh(version)
    assert version.preview_status == "ready"
    assert version.preview_version_id is not None
    assert version.status == "available"

    preview_version = db_session.get(ProjectFileVersion, version.preview_version_id)
    assert preview_version is not None
    assert preview_version.source == "preview"
    assert preview_version.version_number > 1_000_000_000
    assert _next_version_number(db_session, project_file.id) == 2
    assert preview_version.status == "available"
    assert preview_version.scan_status == "not_required"
    assert preview_version.storage_key.startswith("projects/p1/previews/")


def test_generated_preview_is_hidden_from_user_version_history(db_session):
    project_file, version = _seed_version(
        db_session, filename="report.pdf", data=VALID_PDF
    )
    actor = version.uploaded_by
    generate_preview(version.id)

    visible = list_file_versions(
        actor=actor, project_id=project_file.project_id, file_id=project_file.id
    )

    assert [item["id"] for item in visible] == [version.id]
    assert all(item["source"] != "preview" for item in visible)


def test_preview_not_generated_for_quarantined(db_session):
    project_file, version = _seed_version(
        db_session,
        filename="report.pdf",
        data=VALID_PDF,
        status="quarantined",
        scan_status="error",
    )

    result = generate_preview(version.id)

    assert result["preview_status"] != "ready"
    db_session.refresh(version)
    assert version.preview_status != "ready"
    assert version.preview_version_id is None
