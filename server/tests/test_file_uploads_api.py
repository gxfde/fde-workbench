from __future__ import annotations

from datetime import date
from urllib.parse import urlparse
from uuid import uuid4

from fde_api.auth.models import User
from fde_api.auth.tokens import issue_access_token
from fde_api.files.models import ProjectFile, ProjectFileVersion, UploadSession
from fde_api.guidance.models import ProjectGuidanceAnalysis, ProjectPresurveySource
from fde_api.jobs.models import OutboxEvent
from fde_api.workbench.models import (
    IndustryTemplate,
    IndustryTemplateVersion,
    Project,
    ProjectMember,
)


def _persisted_project(db_session, *, code="FDE-FILES-API-001"):
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

    def post(self, *args, **kwargs):
        return self.client.post(*args, headers=self.headers, **kwargs)

    def put(self, *args, **kwargs):
        return self.client.put(*args, headers=self.headers, **kwargs)

    def patch(self, *args, **kwargs):
        return self.client.patch(*args, headers=self.headers, **kwargs)


def _authed_client(client, user, settings) -> AuthorizedClient:
    return AuthorizedClient(
        client, user, {"Authorization": f"Bearer {issue_access_token(user, settings)}"}
    )


def _files_base(project_id: str) -> str:
    return f"/api/v1/projects/{project_id}/files"


def _create_upload(
    uploader, project_id, *, name="需求文档.docx", idempotency_key=None,
    business_category=None, size_bytes=1024, display_name=None, file_id=None,
):
    payload = {
        "name": name,
        "size_bytes": size_bytes,
        "mime_type": (
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        ),
        "category": "attachment",
        "idempotency_key": idempotency_key or f"idem-{uuid4().hex}",
    }
    if business_category is not None:
        payload["business_category"] = business_category
    if display_name is not None:
        payload["display_name"] = display_name
    if file_id is not None:
        payload["file_id"] = file_id
    response = uploader.post(_files_base(project_id), json=payload)
    return response


def _post_complete(uploader, project_id, session_id, parts):
    return uploader.post(
        f"{_files_base(project_id)}/{session_id}/complete",
        json={"parts": parts},
    )


def _upload_part_and_complete(uploader, project_id, session_id, data=b"hello"):
    """Sign part 1, PUT the bytes through the local-storage HTTP route, then complete."""
    sign = uploader.post(
        f"{_files_base(project_id)}/{session_id}/parts", json={"part_number": 1}
    )
    assert sign.status_code == 200, sign.get_data(as_text=True)
    signed = sign.json["data"]["url"]
    parsed = urlparse(signed)
    part = uploader.client.put(
        f"{parsed.path}?{parsed.query}",
        data=data,
        content_type="application/octet-stream",
    )
    assert part.status_code == 200, part.get_data(as_text=True)
    etag = part.headers["ETag"]
    return _post_complete(
        uploader, project_id, session_id,
        [{"part_number": 1, "etag": etag}],
    )


def test_create_upload_session_requires_manager(db_session, client, settings):
    project, leader = _persisted_project(db_session)
    leader_client = _authed_client(client, leader, settings)

    # A viewer member may view but not manage the project's files.
    viewer = _make_user(db_session, "viewer")
    db_session.add(ProjectMember(project=project, user=viewer, role="viewer"))
    db_session.commit()
    viewer_client = _authed_client(client, viewer, settings)

    # A non-member engineer is not a manager over this project either.
    outsider = _make_user(db_session, "fde_engineer")
    outsider_client = _authed_client(client, outsider, settings)

    viewer_response = _create_upload(viewer_client, project.id)
    assert viewer_response.status_code == 403, viewer_response.get_data(as_text=True)
    assert viewer_response.json["error"]["code"] == "forbidden"

    outsider_response = _create_upload(outsider_client, project.id)
    assert outsider_response.status_code == 403, outsider_response.get_data(as_text=True)
    assert outsider_response.json["error"]["code"] == "forbidden"

    lead_response = _create_upload(leader_client, project.id)
    assert lead_response.status_code == 201, lead_response.get_data(as_text=True)
    assert lead_response.json["data"]["project_id"] == project.id


def test_attachment_complete_is_idempotent(db_session, client, settings):
    project, leader = _persisted_project(db_session)
    uploader = _authed_client(client, leader, settings)

    create = _create_upload(uploader, project.id)
    assert create.status_code == 201, create.get_data(as_text=True)
    session_id = create.json["data"]["id"]

    first = _upload_part_and_complete(uploader, project.id, session_id)
    assert first.status_code == 202, first.get_data(as_text=True)
    version_id = first.json["data"]["version_id"]

    # Completing the same session again replays the same version id.
    second = _post_complete(
        uploader, project.id, session_id, [{"part_number": 1, "etag": "replay"}]
    )
    assert second.status_code == 202, second.get_data(as_text=True)
    assert second.json["data"]["version_id"] == version_id

    assert db_session.query(ProjectFileVersion).count() == 1


def test_complete_creates_immediately_available_file_version(
    db_session, client, settings
):
    project, leader = _persisted_project(db_session)
    uploader = _authed_client(client, leader, settings)

    create = _create_upload(uploader, project.id)
    assert create.status_code == 201, create.get_data(as_text=True)
    session_id = create.json["data"]["id"]

    complete = _upload_part_and_complete(uploader, project.id, session_id)
    assert complete.status_code == 202, complete.get_data(as_text=True)

    project_file = db_session.query(ProjectFile).one()
    version = db_session.query(ProjectFileVersion).one()
    assert version.file_id == project_file.id
    assert version.scan_status == "not_required"
    assert version.status == "available"
    assert project_file.current_version_id == version.id

    assert db_session.query(OutboxEvent).filter_by(topic="file.scan").count() == 0


def test_manager_can_queue_preview_regeneration_for_available_version(
    db_session, client, settings
):
    project, leader = _persisted_project(db_session)
    uploader = _authed_client(client, leader, settings)
    create = _create_upload(uploader, project.id)
    complete = _upload_part_and_complete(
        uploader, project.id, create.json["data"]["id"]
    )
    version_id = complete.json["data"]["version_id"]
    version = db_session.get(ProjectFileVersion, version_id)
    version.preview_status = "failed"
    db_session.commit()
    before = db_session.query(OutboxEvent).filter_by(topic="file.preview").count()

    response = uploader.post(
        f"{_files_base(project.id)}/{version_id}/preview"
    )

    assert response.status_code == 202, response.get_data(as_text=True)
    assert response.json["data"] == {"preview_status": "pending"}
    db_session.rollback()
    events = db_session.query(OutboxEvent).filter_by(topic="file.preview").all()
    assert len(events) == before + 1
    assert any(
        event.payload_json.get("requested_by_user_id") == leader.id
        for event in events
    )


def test_viewer_cannot_queue_preview_regeneration(db_session, client, settings):
    project, leader = _persisted_project(db_session)
    uploader = _authed_client(client, leader, settings)
    create = _create_upload(uploader, project.id)
    complete = _upload_part_and_complete(
        uploader, project.id, create.json["data"]["id"]
    )
    viewer = _make_user(db_session, "viewer")
    db_session.add(ProjectMember(project=project, user=viewer, role="viewer"))
    db_session.commit()

    response = _authed_client(client, viewer, settings).post(
        f"{_files_base(project.id)}/{complete.json['data']['version_id']}/preview"
    )

    assert response.status_code == 403
    assert response.json["error"]["code"] == "forbidden"


def test_generated_file_can_be_renamed_without_changing_its_version(db_session, client, settings):
    project, leader = _persisted_project(db_session, code="FDE-FILE-RENAME-001")
    project_file = ProjectFile(
        project_id=project.id,
        category="document",
        business_category="调研",
        display_name="调研结果-销售部-岗位调研",
        created_by_user_id=leader.id,
    )
    db_session.add(project_file)
    db_session.commit()
    uploader = _authed_client(client, leader, settings)

    response = uploader.patch(
        f"{_files_base(project.id)}/items/{project_file.id}",
        json={"name": "调研结果-销售业务诊断"},
    )

    assert response.status_code == 200, response.get_data(as_text=True)
    assert response.json["data"]["display_name"] == "调研结果-销售业务诊断"
    assert db_session.query(ProjectFileVersion).filter_by(file_id=project_file.id).count() == 0


def test_new_presurvey_upload_deprecates_all_previous_versions(
    db_session, client, settings
):
    project, leader = _persisted_project(db_session, code="FDE-PRESURVEY-VERSIONS-001")
    uploader = _authed_client(client, leader, settings)

    first_upload = _create_upload(
        uploader,
        project.id,
        name="预调研表-v1.docx",
        display_name="预调研表",
        business_category="预调研",
    )
    assert first_upload.status_code == 201, first_upload.get_data(as_text=True)
    first_complete = _upload_part_and_complete(
        uploader, project.id, first_upload.json["data"]["id"], data=b"first"
    )
    assert first_complete.status_code == 202, first_complete.get_data(as_text=True)

    second_upload = _create_upload(
        uploader,
        project.id,
        name="预调研表-v2.docx",
        display_name="预调研表",
        business_category="预调研",
        file_id=first_complete.json["data"]["file_id"],
    )
    assert second_upload.status_code == 201, second_upload.get_data(as_text=True)
    second_complete = _upload_part_and_complete(
        uploader, project.id, second_upload.json["data"]["id"], data=b"second"
    )
    assert second_complete.status_code == 202, second_complete.get_data(as_text=True)

    versions = (
        db_session.query(ProjectFileVersion)
        .order_by(ProjectFileVersion.version_number)
        .all()
    )
    assert [version.status for version in versions] == ["deprecated", "available"]
    assert versions[0].deprecation_reason == "已上传新的预调研表版本"
    project_file = db_session.get(ProjectFile, first_complete.json["data"]["file_id"])
    assert project_file.current_version_id == versions[1].id


def test_deprecated_latest_version_is_listed_and_can_be_restored(db_session, client, settings):
    project, leader = _persisted_project(db_session, code="FDE-FILES-RESTORE-001")
    uploader = _authed_client(client, leader, settings)
    create = _create_upload(uploader, project.id, name="补充协议.docx")
    complete = _upload_part_and_complete(uploader, project.id, create.json["data"]["id"])
    version_id = complete.json["data"]["version_id"]

    deprecated = uploader.post(f"{_files_base(project.id)}/versions/{version_id}/deprecate", json={"reason": "测试弃用"})
    assert deprecated.status_code == 200, deprecated.get_data(as_text=True)
    listed = uploader.get(_files_base(project.id))
    latest = listed.json["data"]["items"][0]["latest_version"]
    assert latest["id"] == version_id
    assert latest["status"] == "deprecated"
    assert latest["uploaded_at"]
    assert "preview_status" in latest

    restored = uploader.post(f"{_files_base(project.id)}/versions/{version_id}/restore")
    assert restored.status_code == 200, restored.get_data(as_text=True)
    assert restored.json["data"]["status"] == "available"
    db_session.refresh(db_session.get(ProjectFile, complete.json["data"]["file_id"]))
    assert db_session.get(ProjectFile, complete.json["data"]["file_id"]).current_version_id == version_id


def test_file_card_deprecates_all_versions_and_restores_only_the_latest(
    db_session, client, settings
):
    project, leader = _persisted_project(db_session, code="FDE-FILES-CARD-001")
    uploader = _authed_client(client, leader, settings)
    first_upload = _create_upload(uploader, project.id, name="方案-v1.docx")
    first = _upload_part_and_complete(
        uploader, project.id, first_upload.json["data"]["id"], data=b"first"
    )
    second_upload = _create_upload(
        uploader,
        project.id,
        name="方案-v2.docx",
        file_id=first.json["data"]["file_id"],
    )
    second = _upload_part_and_complete(
        uploader, project.id, second_upload.json["data"]["id"], data=b"second"
    )
    file_id = first.json["data"]["file_id"]

    archived = uploader.post(
        f"{_files_base(project.id)}/items/{file_id}/deprecate",
        json={"reason": "整份文件弃用"},
    )

    assert archived.status_code == 200, archived.get_data(as_text=True)
    assert archived.json["data"]["current_version"] is None
    db_session.expire_all()
    versions = (
        db_session.query(ProjectFileVersion)
        .filter_by(file_id=file_id)
        .order_by(ProjectFileVersion.version_number)
        .all()
    )
    assert [item.status for item in versions] == ["deprecated", "deprecated"]

    restored = uploader.post(f"{_files_base(project.id)}/items/{file_id}/restore")

    assert restored.status_code == 200, restored.get_data(as_text=True)
    assert restored.json["data"]["current_version_id"] == second.json["data"]["version_id"]
    db_session.rollback()
    versions = (
        db_session.query(ProjectFileVersion)
        .filter_by(file_id=file_id)
        .order_by(ProjectFileVersion.version_number)
        .all()
    )
    assert [item.status for item in versions] == ["deprecated", "available"]


def test_deprecating_guidance_source_keeps_confirmed_guidance_and_moves_to_available_version(
    db_session, client, settings
):
    project, leader = _persisted_project(db_session, code="FDE-PRESURVEY-GUIDANCE-001")
    uploader = _authed_client(client, leader, settings)
    first = _create_upload(
        uploader, project.id, name="预调研表-v1.docx", display_name="预调研表", business_category="预调研"
    )
    first_complete = _upload_part_and_complete(uploader, project.id, first.json["data"]["id"], data=b"first")
    first_version_id = first_complete.json["data"]["version_id"]
    second = _create_upload(
        uploader, project.id, name="预调研表-v2.docx", display_name="预调研表", business_category="预调研",
        file_id=first_complete.json["data"]["file_id"],
    )
    second_complete = _upload_part_and_complete(uploader, project.id, second.json["data"]["id"], data=b"second")
    second_version_id = second_complete.json["data"]["version_id"]
    first_version = db_session.get(ProjectFileVersion, first_version_id)
    first_version.status = "available"
    first_version.deprecated_by_user_id = None
    first_version.deprecated_at = None
    first_version.deprecation_reason = ""
    source = ProjectPresurveySource(
        project_id=project.id,
        project_file_id=first_complete.json["data"]["file_id"],
        current_file_version_id=first_version_id,
    )
    guidance = ProjectGuidanceAnalysis(
        project_id=project.id, version_number=1, source_file_id=first_complete.json["data"]["file_id"],
        source_file_version_id=first_version_id, source_filename="预调研表-v1.docx", source_sha256="",
        status="confirmed", analysis_state="ready", customer_vision="建设智能工厂",
        current_phase_objective="完成诊断", executive_summary="已确认指引", created_by_user_id=leader.id,
    )
    db_session.add_all([source, guidance])
    db_session.commit()

    deprecated = uploader.post(
        f"{_files_base(project.id)}/versions/{first_version_id}/deprecate", json={"reason": "人工弃用"}
    )

    assert deprecated.status_code == 200, deprecated.get_data(as_text=True)
    db_session.expire_all()
    assert db_session.get(ProjectPresurveySource, project.id).current_file_version_id == second_version_id
    assert db_session.get(ProjectGuidanceAnalysis, guidance.id).status == "confirmed"
    current = uploader.get(f"/api/v1/projects/{project.id}/guidance")
    assert current.status_code == 200
    assert current.json["data"]["customer_vision"] == "建设智能工厂"
    assert current.json["data"]["source_is_stale"] is True
    db_session.delete(db_session.get(ProjectPresurveySource, project.id))
    db_session.delete(db_session.get(ProjectGuidanceAnalysis, guidance.id))
    db_session.commit()


def test_sign_part_returns_url(db_session, client, settings):
    project, leader = _persisted_project(db_session)
    uploader = _authed_client(client, leader, settings)

    create = _create_upload(uploader, project.id)
    assert create.status_code == 201, create.get_data(as_text=True)
    session_id = create.json["data"]["id"]

    response = uploader.post(
        f"{_files_base(project.id)}/{session_id}/parts", json={"part_number": 1}
    )
    assert response.status_code == 200, response.get_data(as_text=True)
    data = response.json["data"]
    assert data["part_number"] == 1
    assert data["expires_seconds"] == 300
    assert isinstance(data["url"], str)
    assert urlparse(data["url"]).scheme == "http"


def test_abort_marks_session_aborted(db_session, client, settings):
    project, leader = _persisted_project(db_session)
    uploader = _authed_client(client, leader, settings)

    create = _create_upload(uploader, project.id)
    assert create.status_code == 201, create.get_data(as_text=True)
    session_id = create.json["data"]["id"]

    response = uploader.post(f"{_files_base(project.id)}/{session_id}/abort")
    assert response.status_code == 200, response.get_data(as_text=True)

    upload_session = db_session.get(UploadSession, session_id)
    assert upload_session.status == "aborted"


def test_cross_project_file_request_returns_404(db_session, client, settings):
    project, _ = _persisted_project(db_session)
    outsider = _make_user(db_session, "fde_engineer")
    outsider_client = _authed_client(client, outsider, settings)

    response = outsider_client.get(_files_base(project.id))
    assert response.status_code == 404, response.get_data(as_text=True)
    assert response.json["error"]["code"] == "project_not_found"


def test_rejects_executable_extension(db_session, client, settings):
    project, leader = _persisted_project(db_session)
    uploader = _authed_client(client, leader, settings)

    response = _create_upload(uploader, project.id, name="run.exe")
    assert response.status_code == 422, response.get_data(as_text=True)
    assert response.json["error"]["code"] == "file_type_not_allowed"


def test_accepts_markdown_and_other_archive_extensions(db_session, client, settings):
    project, leader = _persisted_project(db_session)
    uploader = _authed_client(client, leader, settings)

    for name in ("项目说明.md", "设计源文件.psd", "无扩展名"):
        response = _create_upload(uploader, project.id, name=name)
        assert response.status_code == 201, response.get_data(as_text=True)


def test_rejects_file_larger_than_100_mb(db_session, client, settings):
    project, leader = _persisted_project(db_session)
    uploader = _authed_client(client, leader, settings)

    response = _create_upload(
        uploader,
        project.id,
        name="超大归档.zip",
        size_bytes=100 * 1024 * 1024 + 1,
    )
    assert response.status_code == 422, response.get_data(as_text=True)
    assert response.json["error"]["code"] == "file_too_large"


def test_accepts_file_at_100_mb_limit(db_session, client, settings):
    project, leader = _persisted_project(db_session)
    uploader = _authed_client(client, leader, settings)

    response = _create_upload(
        uploader,
        project.id,
        name="边界归档.zip",
        size_bytes=100 * 1024 * 1024,
    )
    assert response.status_code == 201, response.get_data(as_text=True)


def test_upload_roundtrips_business_category(db_session, client, settings):
    """A category set on the upload session persists onto the created file and is
    exposed in the list DTO, and the list endpoint filters by it."""
    project, leader = _persisted_project(db_session)
    uploader = _authed_client(client, leader, settings)

    create = _create_upload(uploader, project.id, business_category="调研")
    assert create.status_code == 201, create.get_data(as_text=True)
    assert create.json["data"]["business_category"] == "调研"
    session_id = create.json["data"]["id"]

    complete = _upload_part_and_complete(uploader, project.id, session_id)
    assert complete.status_code == 202, complete.get_data(as_text=True)

    listed = uploader.get(_files_base(project.id))
    assert listed.status_code == 200, listed.get_data(as_text=True)
    items = listed.json["data"]["items"]
    assert len(items) == 1
    assert items[0]["business_category"] == "调研"

    filtered = uploader.get(f"{_files_base(project.id)}?business_category=调研")
    assert filtered.status_code == 200, filtered.get_data(as_text=True)
    assert [item["id"] for item in filtered.json["data"]["items"]] == [
        items[0]["id"]
    ]

    other = uploader.get(f"{_files_base(project.id)}?business_category=商务合约")
    assert other.status_code == 200, other.get_data(as_text=True)
    assert other.json["data"]["items"] == []


def test_upload_table_roundtrips_uncategorized_and_filters_uncategorized(
    db_session, client, settings
):
    """An upload with no category is uncategorized; the 未分类 filter matches it."""
    project, leader = _persisted_project(db_session)
    uploader = _authed_client(client, leader, settings)

    create = _create_upload(uploader, project.id)
    assert create.status_code == 201, create.get_data(as_text=True)
    assert create.json["data"]["business_category"] is None
    session_id = create.json["data"]["id"]

    complete = _upload_part_and_complete(uploader, project.id, session_id)
    assert complete.status_code == 202, complete.get_data(as_text=True)

    filtered = uploader.get(f"{_files_base(project.id)}?business_category=未分类")
    assert filtered.status_code == 200, filtered.get_data(as_text=True)
    items = filtered.json["data"]["items"]
    assert len(items) == 1
    assert items[0]["business_category"] is None


def test_upload_rejects_invalid_business_category(db_session, client, settings):
    project, leader = _persisted_project(db_session)
    uploader = _authed_client(client, leader, settings)

    response = _create_upload(uploader, project.id, business_category="不存在")
    assert response.status_code == 400, response.get_data(as_text=True)
    assert response.json["data"] is None
    assert response.json["error"]["code"] == "invalid_business_category"


def test_list_files_rejects_invalid_business_category_filter(
    db_session, client, settings
):
    project, leader = _persisted_project(db_session)
    uploader = _authed_client(client, leader, settings)

    response = uploader.get(f"{_files_base(project.id)}?business_category=不存在")
    assert response.status_code == 400, response.get_data(as_text=True)
    assert response.json["error"]["code"] == "invalid_business_category"


def test_single_part_upload_via_signed_url_completes_and_promotes(
    db_session, client, settings
):
    """The renderer PUTs the signed URL cross-origin; the response must expose the
    ETag and the whole single-part upload must promote into a file version."""
    from fde_api.files.models import ProjectFile, ProjectFileVersion
    from fde_api.jobs.models import OutboxEvent

    project, leader = _persisted_project(db_session, code="FDE-FILES-CORS-001")
    headers = {"Authorization": f"Bearer {issue_access_token(leader, settings)}"}
    base = f"/api/v1/projects/{project.id}/files"

    create = client.post(
        base,
        headers=headers,
        json={
            "name": "需求文档.docx",
            "size_bytes": 1024,
            "mime_type": "application/octet-stream",
            "category": "attachment",
            "idempotency_key": f"idem-{uuid4().hex}",
        },
    )
    assert create.status_code == 201, create.get_data(as_text=True)
    session_id = create.json["data"]["id"]

    sign = client.post(
        f"{base}/{session_id}/parts", headers=headers, json={"part_number": 1}
    )
    assert sign.status_code == 200
    signed = sign.json["data"]["url"]

    # Browser-style PUT with an Origin header (the renderer is cross-origin to 127.0.0.1).
    browser_headers = {"Origin": "http://127.0.0.1:5173"}
    put = client.put(
        signed,
        headers=browser_headers,
        data=b"hello",
        content_type="application/octet-stream",
    )
    assert put.status_code == 200, put.get_data(as_text=True)
    assert put.headers["Access-Control-Allow-Origin"] == "http://127.0.0.1:5173"
    assert "ETag" in put.headers.get("Access-Control-Expose-Headers", "")
    etag = put.headers["ETag"]

    complete = client.post(
        f"{base}/{session_id}/complete",
        headers=headers,
        json={"parts": [{"part_number": 1, "etag": etag}]},
    )
    assert complete.status_code == 202, complete.get_data(as_text=True)
    assert complete.json["data"]["status"] == "available"

    project_file = db_session.query(ProjectFile).one()
    version = db_session.query(ProjectFileVersion).one()
    assert version.file_id == project_file.id
    assert project_file.current_version_id == version.id
    assert version.scan_status == "not_required"
    assert db_session.query(OutboxEvent).filter_by(topic="file.scan").count() == 0


def test_local_storage_preflight_answers_cors_for_put(db_session, client, settings):
    """OPTIONS preflight to the signed part path must return CORS headers."""
    project, leader = _persisted_project(db_session, code="FDE-FILES-CORS-002")
    headers = {"Authorization": f"Bearer {issue_access_token(leader, settings)}"}
    base = f"/api/v1/projects/{project.id}/files"
    create = client.post(
        base,
        headers=headers,
        json={
            "name": "a.docx",
            "size_bytes": 1024,
            "mime_type": "application/octet-stream",
            "category": "attachment",
            "idempotency_key": f"idem-{uuid4().hex}",
        },
    )
    session_id = create.json["data"]["id"]
    sign = client.post(
        f"{base}/{session_id}/parts", headers=headers, json={"part_number": 1}
    )
    signed = sign.json["data"]["url"]

    preflight = client.options(
        signed,
        headers={
            "Origin": "http://127.0.0.1:5173",
            "Access-Control-Request-Method": "PUT",
            "Access-Control-Request-Headers": "content-type",
        },
    )
    assert preflight.status_code == 200
    assert preflight.headers["Access-Control-Allow-Origin"] == "http://127.0.0.1:5173"
    assert "PUT" in preflight.headers.get("Access-Control-Allow-Methods", "")
    assert "content-type" in preflight.headers.get("Access-Control-Allow-Headers", "").lower()
