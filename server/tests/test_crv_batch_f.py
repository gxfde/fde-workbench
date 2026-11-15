"""goal-crv 修复批 F 回归与契约测试钉（QR-117 + QR-118）。

- QR-117（P1 → 趋 P0）：富文本段落块规范键 `content` 与旧版桌面 `text` 键兼容，
  PATCH 草稿 → GET 回读 → Worker 生成 `.docx` 全链路保留段落正文。
- QR-118（P1）：`complete_upload` 在消费分片目录前预检同名唯一键与目标文件存在性（返回 409/404），
  并发 `IntegrityError` 映射 409 且支持 `head(storage_prefix)` 重放恢复，`abort_upload` 幂等收敛。
"""

from __future__ import annotations

from datetime import date
from io import BytesIO
from urllib.parse import urlparse
from uuid import uuid4

from docx import Document
import pytest

from fde_api.auth.models import User
from fde_api.auth.tokens import issue_access_token
from fde_api.documents.generator import handle_document_generation
from fde_api.documents.models import (
    DocumentTemplate,
    DocumentTemplateVersion,
    ProjectDocumentVersion,
)
from fde_api.documents.qa import extract_docx_xml_text
from fde_api.documents.rich_text import render_rich_text, sanitize_rich_text
from fde_api.extensions import object_storage
from fde_api.files import service as files_service
from fde_api.files.models import ProjectFile, ProjectFileVersion, UploadSession
from fde_api.storage.base import StorageError
from fde_api.workbench.models import IndustryTemplate, IndustryTemplateVersion, Project

DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


class _AuthedClient:
    def __init__(self, client, user: User, settings) -> None:
        self.client = client
        self.user = user
        self.headers = {"Authorization": f"Bearer {issue_access_token(user, settings)}"}

    def get(self, *args, **kwargs):
        return self.client.get(*args, headers=self.headers, **kwargs)

    def post(self, *args, **kwargs):
        return self.client.post(*args, headers=self.headers, **kwargs)

    def put(self, *args, **kwargs):
        return self.client.put(*args, headers=self.headers, **kwargs)

    def patch(self, *args, **kwargs):
        return self.client.patch(*args, headers=self.headers, **kwargs)


def _create_project_and_leader(db_session, *, prefix: str) -> tuple[Project, User]:
    code = f"{prefix}-{uuid4().hex[:8]}"
    leader = User(
        username=f"crv.f.{uuid4().hex[:10]}",
        display_name="批F负责人",
        role="project_lead",
        password_hash="x",
        must_change_password=False,
        is_active=True,
    )
    ind_tpl = IndustryTemplate(name=f"模板-{code}", industry_name="制造")
    ind_ver = IndustryTemplateVersion(
        template=ind_tpl,
        name=ind_tpl.name,
        industry_name=ind_tpl.industry_name,
        description="",
        version_number=1,
        status="published",
        published_by=leader,
    )
    project = Project(
        project_code=code,
        name="批F验证项目",
        enterprise_code=f"星河制造·制造·{code}",
        leader=leader,
        source_template_version=ind_ver,
        template_snapshot={},
        research_snapshot={},
        planned_start_date=date(2026, 11, 13),
    )
    db_session.add(project)
    db_session.commit()
    return project, leader


def _create_sow_template(
    db_session, project: Project, leader: User
) -> DocumentTemplateVersion:
    buf = BytesIO()
    doc = Document()
    doc.add_heading("工作说明书", level=1)
    doc.save(buf)
    raw = buf.getvalue()
    template_key = f"projects/{project.id}/templates/sow/versions/1/sow-v1.docx"
    stored_tpl = object_storage.current.put_stream(
        template_key, BytesIO(raw), DOCX_MIME, {}
    )
    tpl_file = ProjectFile(
        project=project,
        category="document",
        display_name="sow-v1.docx",
        description="",
        created_by=leader,
    )
    db_session.add(tpl_file)
    db_session.flush()
    tpl_file_ver = ProjectFileVersion(
        project_file=tpl_file,
        version_number=1,
        source="system_generated",
        original_filename="sow-v1.docx",
        safe_filename="sow-v1.docx",
        extension="docx",
        mime_type=DOCX_MIME,
        bucket="local",
        storage_key=template_key,
        size_bytes=stored_tpl.size,
        etag=stored_tpl.etag,
        sha256="",
        scan_status="not_required",
        preview_status="none",
        uploaded_by=leader,
        status="available",
    )
    db_session.add(tpl_file_ver)
    db_session.flush()
    tpl_file.current_version_id = tpl_file_ver.id

    tpl = DocumentTemplate(
        document_type="sow",
        name=f"SOW-{uuid4().hex[:6]}",
        description="",
        industry_name="制造",
    )
    db_session.add(tpl)
    db_session.flush()
    tpl_ver = DocumentTemplateVersion(
        template=tpl,
        version_number=1,
        status="published",
        docx_file_version_id=tpl_file_ver.id,
        mapping_json={
            "document_type": "sow",
            "name": tpl.name,
            "modules": ["pre_diagnosis"],
            "field_map": {},
            "research_keys": [],
        },
        sections_json={"sections": []},
        table_loops_json={},
        required_data_json={},
        source_sha256="",
        created_by=leader,
    )
    db_session.add(tpl_ver)
    db_session.commit()
    return tpl_ver


def _upload_single_part(
    uploader: _AuthedClient, project_id: str, session_id: str, payload: bytes
) -> list[dict[str, object]]:
    sign = uploader.post(
        f"/api/v1/projects/{project_id}/files/{session_id}/parts",
        json={"part_number": 1},
    )
    assert sign.status_code == 200, sign.get_data(as_text=True)
    parsed = urlparse(sign.json["data"]["url"])
    put_resp = uploader.client.put(
        f"{parsed.path}?{parsed.query}",
        data=payload,
        content_type="application/octet-stream",
    )
    assert put_resp.status_code == 200, put_resp.get_data(as_text=True)
    return [{"part_number": 1, "etag": put_resp.headers["ETag"]}]


# ── QR-117 ───────────────────────────────────────────────────────────────────


def test_qr117_sanitize_rich_text_accepts_canonical_content_and_legacy_text_keys():
    sanitized = sanitize_rich_text(
        {
            "type": "doc",
            "content": [
                {"type": "paragraph", "content": "规范正文段落"},
                {"type": "heading", "text": "旧版桌面标题", "marks": ["bold"]},
                {"type": "paragraph", "text": "<script>alert(1)</script>旧版桌面正文"},
                # 同时携带 content 与 text 时以规范键 content 为权威，不被旧键覆盖
                {"type": "paragraph", "content": "权威正文", "text": "旧键影子"},
                # content 显式为空串时视为空段落过滤，不回退到旧键 text
                {"type": "paragraph", "content": "", "text": "不应泄露"},
            ],
        }
    )
    rendered = render_rich_text(sanitized)
    assert rendered == [
        {"type": "paragraph", "content": "规范正文段落", "marks": []},
        {"type": "heading", "content": "旧版桌面标题", "marks": ["bold"]},
        {"type": "paragraph", "content": "alert(1)旧版桌面正文", "marks": []},
        {"type": "paragraph", "content": "权威正文", "marks": []},
    ]


def test_qr117_draft_patch_roundtrip_and_docx_generation_keep_paragraphs(
    db_session, client, settings
):
    project, leader = _create_project_and_leader(db_session, prefix="CRVF-117")
    tpl_ver = _create_sow_template(db_session, project, leader)
    authed = _AuthedClient(client, leader, settings)

    created = authed.post(
        f"/api/v1/projects/{project.id}/documents",
        json={
            "document_type": "sow",
            "template_version_id": tpl_ver.id,
            "expected_version": project.version,
        },
    )
    assert created.status_code == 201, created.get_data(as_text=True)
    doc_id = created.json["data"]["id"]
    doc_version = created.json["data"]["version"]

    # 1) 旧版桌面载荷 `{type:"paragraph", text:"..."}` 不再被静默清空
    legacy_patch = authed.patch(
        f"/api/v1/projects/{project.id}/documents/{doc_id}/draft",
        json={
            "version": 1,
            "rich_text": {
                "type": "doc",
                "content": [
                    {"type": "paragraph", "text": "兼容旧桌面第一段"},
                    {"type": "paragraph", "text": "兼容旧桌面第二段"},
                ],
            },
        },
    )
    assert legacy_patch.status_code == 200, legacy_patch.get_data(as_text=True)
    assert legacy_patch.json["data"]["rich_text"] == [
        {"type": "paragraph", "content": "兼容旧桌面第一段", "marks": []},
        {"type": "paragraph", "content": "兼容旧桌面第二段", "marks": []},
    ]
    next_draft_ver = legacy_patch.json["data"]["version"]

    # 2) 新版规范载荷 `{type:"paragraph", content:"..."}` 落库 → GET 回读 → 生成真实 DOCX
    canonical_patch = authed.patch(
        f"/api/v1/projects/{project.id}/documents/{doc_id}/draft",
        json={
            "version": next_draft_ver,
            "rich_text": {
                "type": "doc",
                "content": [
                    {"type": "paragraph", "content": "规范桌面第一段交付范围"},
                    {"type": "paragraph", "content": "规范桌面第二段里程碑验收"},
                ],
            },
        },
    )
    assert canonical_patch.status_code == 200, canonical_patch.get_data(as_text=True)
    expected_blocks = [
        {"type": "paragraph", "content": "规范桌面第一段交付范围", "marks": []},
        {"type": "paragraph", "content": "规范桌面第二段里程碑验收", "marks": []},
    ]
    assert canonical_patch.json["data"]["rich_text"] == expected_blocks

    detail = authed.get(f"/api/v1/projects/{project.id}/documents/{doc_id}")
    assert detail.status_code == 200
    assert detail.json["data"]["draft"]["rich_text"] == expected_blocks

    gen = authed.post(
        f"/api/v1/projects/{project.id}/documents/{doc_id}/generate",
        json={"version": doc_version},
    )
    assert gen.status_code == 200, gen.get_data(as_text=True)
    version_id = gen.json["data"]["id"]

    # handle_document_generation 使用独立 db.session()，先释放测试会话读锁
    db_session.rollback()
    result = handle_document_generation(version_id=version_id)
    assert result["status"] == "succeeded", result

    db_session.expire_all()
    version = db_session.get(ProjectDocumentVersion, version_id)
    assert version is not None and version.docx_file_version_id
    docx_ver = db_session.get(ProjectFileVersion, version.docx_file_version_id)
    assert docx_ver is not None and docx_ver.status == "available"
    stream = object_storage.current.open_stream(docx_ver.storage_key)
    try:
        docx_text = extract_docx_xml_text(BytesIO(stream.read()))
    finally:
        stream.close()
    assert "规范桌面第一段交付范围" in docx_text
    assert "规范桌面第二段里程碑验收" in docx_text


# ── QR-118 ───────────────────────────────────────────────────────────────────


def test_qr118_duplicate_name_precheck_returns_409_preserves_parts_and_recovers(
    db_session, client, settings
):
    project, leader = _create_project_and_leader(db_session, prefix="CRVF-118A")
    authed = _AuthedClient(client, leader, settings)
    base = f"/api/v1/projects/{project.id}/files"

    first = authed.post(
        base,
        json={
            "name": "实施计划.docx",
            "size_bytes": 16,
            "mime_type": DOCX_MIME,
            "category": "attachment",
            "idempotency_key": f"idem-{uuid4().hex}",
        },
    )
    assert first.status_code == 201
    first_sid = first.json["data"]["id"]
    first_parts = _upload_single_part(authed, project.id, first_sid, b"first-body")
    first_done = authed.post(f"{base}/{first_sid}/complete", json={"parts": first_parts})
    assert first_done.status_code == 202, first_done.get_data(as_text=True)
    first_file_id = first_done.json["data"]["file_id"]

    # 第二个新文件会话使用同名 `实施计划.docx`（file_id=None）
    second = authed.post(
        base,
        json={
            "name": "实施计划.docx",
            "size_bytes": 17,
            "mime_type": DOCX_MIME,
            "category": "attachment",
            "idempotency_key": f"idem-{uuid4().hex}",
        },
    )
    assert second.status_code == 201
    second_sid = second.json["data"]["id"]
    second_parts = _upload_single_part(authed, project.id, second_sid, b"second-body")

    conflict = authed.post(f"{base}/{second_sid}/complete", json={"parts": second_parts})
    assert conflict.status_code == 409, conflict.get_data(as_text=True)
    assert conflict.json["error"]["code"] == "file_name_conflict"

    # 预检必须在消费分片前拦截：此时目标 storage_prefix 对象尚未提前合成落盘
    db_session.expire_all()
    second_sess = db_session.get(UploadSession, second_sid)
    assert second_sess is not None and second_sess.status == "uploading"
    with pytest.raises(StorageError):
        object_storage.current.head(second_sess.storage_prefix)

    # 原文件改名腾出唯一键后，同一上传会话因分片目录未被提前消费，可直接重试 complete 成功
    renamed = authed.patch(
        f"{base}/items/{first_file_id}",
        json={"name": "实施计划-历史版.docx"},
    )
    assert renamed.status_code == 200, renamed.get_data(as_text=True)

    retried = authed.post(f"{base}/{second_sid}/complete", json={"parts": second_parts})
    assert retried.status_code == 202, retried.get_data(as_text=True)


def test_qr118_duplicate_name_conflict_allows_clean_abort(db_session, client, settings):
    project, leader = _create_project_and_leader(db_session, prefix="CRVF-118B")
    authed = _AuthedClient(client, leader, settings)
    base = f"/api/v1/projects/{project.id}/files"

    for idx in range(2):
        created = authed.post(
            base,
            json={
                "name": "架构清单.docx",
                "size_bytes": 12,
                "mime_type": DOCX_MIME,
                "category": "attachment",
                "idempotency_key": f"idem-{uuid4().hex}",
            },
        )
        assert created.status_code == 201
        sid = created.json["data"]["id"]
        parts = _upload_single_part(authed, project.id, sid, f"body-{idx}".encode())
        done = authed.post(f"{base}/{sid}/complete", json={"parts": parts})
        if idx == 0:
            assert done.status_code == 202
        else:
            assert done.status_code == 409
            assert done.json["error"]["code"] == "file_name_conflict"
            aborted = authed.post(f"{base}/{sid}/abort")
            assert aborted.status_code == 200, aborted.get_data(as_text=True)
            assert aborted.json == {"data": None, "error": None}
            db_session.expire_all()
            sess_row = db_session.get(UploadSession, sid)
            assert sess_row is not None and sess_row.status == "aborted"


def test_qr118_concurrent_integrity_error_maps_to_409_and_replays_or_aborts_cleanly(
    db_session, client, settings, monkeypatch
):
    project, leader = _create_project_and_leader(db_session, prefix="CRVF-118C")
    authed = _AuthedClient(client, leader, settings)
    base = f"/api/v1/projects/{project.id}/files"

    # 先落一个同名文件
    first = authed.post(
        base,
        json={
            "name": "并发冲突.docx",
            "size_bytes": 10,
            "mime_type": DOCX_MIME,
            "category": "attachment",
            "idempotency_key": f"idem-{uuid4().hex}",
        },
    )
    first_sid = first.json["data"]["id"]
    first_parts = _upload_single_part(authed, project.id, first_sid, b"winner")
    first_done = authed.post(f"{base}/{first_sid}/complete", json={"parts": first_parts})
    assert first_done.status_code == 202
    winner_file_id = first_done.json["data"]["file_id"]

    # 模拟并发 TOCTOU：预检放行后，complete_multipart 先消费分片目录，随后 DB flush 撞唯一键抛 IntegrityError
    monkeypatch.setattr(files_service, "_preflight_upload_target", lambda *_a, **_kw: None)

    # 分支 1：并发 409 → 解除冲突后同一 session 重试通过 head(storage_prefix) 重放恢复 202
    race_replay = authed.post(
        base,
        json={
            "name": "并发冲突.docx",
            "size_bytes": 12,
            "mime_type": DOCX_MIME,
            "category": "attachment",
            "idempotency_key": f"idem-{uuid4().hex}",
        },
    )
    replay_sid = race_replay.json["data"]["id"]
    replay_parts = _upload_single_part(authed, project.id, replay_sid, b"replay-bytes")

    race_resp = authed.post(f"{base}/{replay_sid}/complete", json={"parts": replay_parts})
    assert race_resp.status_code == 409, race_resp.get_data(as_text=True)
    assert race_resp.json["error"]["code"] == "file_name_conflict"

    # 改名解除冲突后重试 complete（此时 .multipart 目录已被前次消费，靠 head 兜底恢复）
    renamed_winner = authed.patch(
        f"{base}/items/{winner_file_id}", json={"name": "并发冲突-让位.docx"}
    )
    assert renamed_winner.status_code == 200, renamed_winner.get_data(as_text=True)
    recovered = authed.post(f"{base}/{replay_sid}/complete", json={"parts": replay_parts})
    assert recovered.status_code == 202, recovered.get_data(as_text=True)
    recovered_ver_id = recovered.json["data"]["version_id"]

    db_session.expire_all()
    rec_ver = db_session.get(ProjectFileVersion, recovered_ver_id)
    assert rec_ver is not None
    stream = object_storage.current.open_stream(rec_ver.storage_key)
    try:
        assert stream.read() == b"replay-bytes"
    finally:
        stream.close()

    # 此时 recovered 已占据 display_name="并发冲突"，再发起同名会话验证并发 409 后 abort_upload 幂等清理孤儿对象
    race_abort = authed.post(
        base,
        json={
            "name": "并发冲突.docx",
            "size_bytes": 11,
            "mime_type": DOCX_MIME,
            "category": "attachment",
            "idempotency_key": f"idem-{uuid4().hex}",
        },
    )
    abort_sid = race_abort.json["data"]["id"]
    abort_parts = _upload_single_part(authed, project.id, abort_sid, b"abort-bytes")

    race_abort_resp = authed.post(f"{base}/{abort_sid}/complete", json={"parts": abort_parts})
    assert race_abort_resp.status_code == 409

    db_session.expire_all()
    sess_row = db_session.get(UploadSession, abort_sid)
    assert sess_row is not None
    orphan_prefix = sess_row.storage_prefix

    abort_resp = authed.post(f"{base}/{abort_sid}/abort")
    assert abort_resp.status_code == 200, abort_resp.get_data(as_text=True)
    assert abort_resp.json == {"data": None, "error": None}
    db_session.expire_all()
    aborted_sess = db_session.get(UploadSession, abort_sid)
    assert aborted_sess is not None and aborted_sess.status == "aborted"
    with pytest.raises(StorageError):
        object_storage.current.head(orphan_prefix)


def test_qr118_unuploaded_parts_without_assembled_object_still_returns_422(
    db_session, client, settings
):
    project, leader = _create_project_and_leader(db_session, prefix="CRVF-118D")
    authed = _AuthedClient(client, leader, settings)
    base = f"/api/v1/projects/{project.id}/files"

    created = authed.post(
        base,
        json={
            "name": "未传分片.docx",
            "size_bytes": 10,
            "mime_type": DOCX_MIME,
            "category": "attachment",
            "idempotency_key": f"idem-{uuid4().hex}",
        },
    )
    sid = created.json["data"]["id"]
    # 模拟 multipart_upload_id 已失效且目标对象从未合成的场景，必须维持 422 invalid_parts
    sess = db_session.get(UploadSession, sid)
    assert sess is not None
    sess.multipart_upload_id = f"missing-{uuid4().hex}"
    db_session.commit()

    resp = authed.post(
        f"{base}/{sid}/complete",
        json={"parts": [{"part_number": 1, "etag": "fake-etag"}]},
    )
    assert resp.status_code == 422, resp.get_data(as_text=True)
    assert resp.json["error"]["code"] == "invalid_parts"
