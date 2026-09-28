from __future__ import annotations

import io
from datetime import date
from urllib.parse import urlparse
from uuid import uuid4

from fde_api.auth.models import User
from fde_api.auth.tokens import issue_access_token
from fde_api.extensions import object_storage
from fde_api.files.models import ProjectFile, ProjectFileVersion
from fde_api.files.names import attachment_key, extension_of, safe_filename
from fde_api.workbench.models import (
    IndustryTemplate,
    IndustryTemplateVersion,
    Project,
    ProjectMember,
)

VALID_PDF = b"%PDF-1.7\n" + b"\x00" * 128


def _persisted_project(db_session, *, code="FDE-FILE-DL-001"):
    leader = User(
        username=f"files.lead.{uuid4().hex}",
        display_name="项目负责人",
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


def _make_user(db_session, role: str, *, active: bool = True) -> User:
    user = User(
        username=f"{role}.{uuid4().hex}",
        display_name=role,
        role=role,
        password_hash="x",
        must_change_password=False,
        is_active=active,
    )
    db_session.add(user)
    db_session.commit()
    return user


class AuthorizedClient:
    def __init__(self, client, user, headers):
        self.client = client
        self.user = user
        self.headers = headers

    def get(self, *args, **kwargs):
        return self.client.get(*args, headers=self.headers, **kwargs)


def _authed_client(client, user, settings) -> AuthorizedClient:
    return AuthorizedClient(
        client, user, {"Authorization": f"Bearer {issue_access_token(user, settings)}"}
    )


def _files_base(project_id: str) -> str:
    return f"/api/v1/projects/{project_id}/files"


def _seed_available_version(
    db_session,
    *,
    project,
    leader,
    filename="report.pdf",
    data=VALID_PDF,
    status="available",
    scan_status="clean",
    file_id=None,
    version_id=None,
    version_number=1,
):
    file_id = file_id or f"f-{uuid4().hex}"
    version_id = version_id or f"v-{uuid4().hex}"
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
    storage_key = attachment_key(
        project.id, file_id, f"v{version_number}", safe
    )
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


def test_download_url_is_five_minutes_and_rechecks_membership(
    db_session, client, settings, monkeypatch
):
    project, leader = _persisted_project(db_session)
    project_file, version = _seed_available_version(db_session, project=project, leader=leader)

    storage = object_storage.current
    real_sign_download = storage.sign_download
    calls = []

    def spy_sign_download(key, filename, expires_seconds=300):
        calls.append((key, filename, expires_seconds))
        return real_sign_download(key, filename, expires_seconds)

    monkeypatch.setattr(storage, "sign_download", spy_sign_download)
    lead_client = _authed_client(client, leader, settings)

    response = lead_client.get(
        f"{_files_base(project.id)}/{version.id}/download-url"
    )

    assert response.status_code == 200, response.get_data(as_text=True)
    data = response.json["data"]
    assert isinstance(data["url"], str)
    assert urlparse(data["url"]).scheme == "http"
    assert data["expires_seconds"] == 300
    assert calls == [(version.storage_key, version.original_filename, 300)]


def test_download_url_keeps_deprecated_history_downloadable(
    db_session, client, settings
):
    project, leader = _persisted_project(db_session)
    project_file, version = _seed_available_version(
        db_session, project=project, leader=leader, status="deprecated"
    )
    lead_client = _authed_client(client, leader, settings)

    response = lead_client.get(
        f"{_files_base(project.id)}/{version.id}/download-url"
    )

    assert response.status_code == 200, response.get_data(as_text=True)
    assert isinstance(response.json["data"]["url"], str)


def test_download_url_denied_for_quarantined(db_session, client, settings):
    project, leader = _persisted_project(db_session)
    project_file, version = _seed_available_version(
        db_session,
        project=project,
        leader=leader,
        status="quarantined",
        scan_status="error",
    )
    lead_client = _authed_client(client, leader, settings)

    response = lead_client.get(
        f"{_files_base(project.id)}/{version.id}/download-url"
    )

    assert response.status_code == 409, response.get_data(as_text=True)
    assert response.json["error"]["code"] == "file_not_available"


def test_download_url_cross_project_404(db_session, client, settings):
    project, leader = _persisted_project(db_session)
    project_file, version = _seed_available_version(db_session, project=project, leader=leader)

    outsider = _make_user(db_session, "fde_engineer")
    outsider_client = _authed_client(client, outsider, settings)
    response = outsider_client.get(
        f"{_files_base(project.id)}/{version.id}/download-url"
    )
    assert response.status_code == 404, response.get_data(as_text=True)
    assert response.json["error"]["code"] == "project_not_found"

    viewer = _make_user(db_session, "viewer")
    db_session.add(ProjectMember(project=project, user=viewer, role="viewer"))
    db_session.commit()

    version.status = "quarantined"
    version.scan_status = "error"
    db_session.commit()

    viewer_client = _authed_client(client, viewer, settings)
    member_response = viewer_client.get(
        f"{_files_base(project.id)}/{version.id}/download-url"
    )
    assert member_response.status_code == 409, member_response.get_data(as_text=True)
    assert member_response.json["error"]["code"] == "file_not_available"


def test_preview_url_rejects_non_available(db_session, client, settings):
    project, leader = _persisted_project(db_session)
    project_file, version = _seed_available_version(
        db_session,
        project=project,
        leader=leader,
        status="quarantined",
        scan_status="error",
    )
    lead_client = _authed_client(client, leader, settings)

    response = lead_client.get(
        f"{_files_base(project.id)}/{version.id}/preview-url"
    )

    assert response.status_code == 409, response.get_data(as_text=True)
    assert response.json["error"]["code"] == "file_not_available"
