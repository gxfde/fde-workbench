import io
from unittest.mock import Mock
from uuid import uuid4

import pytest
from sqlalchemy import select

from fde_api.control.access import capabilities_for_level
from fde_api.control.clawbot_weixin import seal
from fde_api.control.file_delivery import send_file
from fde_api.control.models import ChannelBinding
from fde_api.control.service import ControlServiceError
from fde_api.control.weixin_models import WeixinAccount, WeixinInbox
from fde_api.files.models import ProjectFile, ProjectFileVersion
from fde_api.workbench.models import OperationEvent
from test_ai_server_chat_mcp import make_project
from test_weixin_qr import weixin, confirm


def prepare(weixin, db_session, app, monkeypatch):
    user, transport = weixin
    confirm(user, transport)
    account = db_session.scalar(select(WeixinAccount))
    db_session.add(WeixinInbox(account_id=account.id, event_digest=uuid4().hex * 2,
        payload_encrypted=seal({"sender": "scanner-1", "context_token": "private-context", "text": "请发文件"})))
    project = make_project(db_session, user)
    file = ProjectFile(project_id=project.id, display_name="Export.docx", created_by_user_id=user.id)
    db_session.add(file)
    db_session.flush()
    version = ProjectFileVersion(file_id=file.id, version_number=1, original_filename="Export.docx", safe_filename="Export.docx",
        extension="docx", mime_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document", bucket="test",
        storage_key="generated-export", size_bytes=4, scan_status="not_required", status="available", uploaded_by_user_id=user.id)
    db_session.add(version)
    db_session.flush()
    file.current_version_id = version.id
    db_session.commit()
    storage = Mock()
    storage.open_stream.return_value = io.BytesIO(b"docx")
    app.extensions["fde_api_object_storage"] = storage
    monkeypatch.setattr("fde_api.control.file_delivery.upload_attachment", lambda *_a, **_k: {"type": 4, "file_item": {"file_name": "Export.docx", "media": {"secret": "private-media"}}})
    args = {"user": user, "claims": {"execution_id": str(uuid4()), "ver": user.auth_version}, "allowed": set(capabilities_for_level("system_operator")), "project_id": project.id, "file_id": file.id, "version_id": version.id}
    return args, transport, version


def test_existing_file_delivery_is_owned_and_idempotent(weixin, db_session, app, monkeypatch):
    args, transport, _ = prepare(weixin, db_session, app, monkeypatch)
    result = send_file(**args)
    assert result["delivery_status"] == "accepted_by_wechat"
    assert send_file(**args) == result
    sends = [kwargs for endpoint, kwargs in transport.calls if endpoint == "sendmessage"]
    assert len(sends) == 1
    assert sends[0]["payload"]["msg"]["to_user_id"] == "scanner-1"
    assert sends[0]["payload"]["msg"]["item_list"][0]["type"] == 4
    db_session.rollback()
    assert "private-media" not in str([e.changes for e in db_session.scalars(select(OperationEvent))])


def test_unavailable_file_is_not_sent(weixin, db_session, app, monkeypatch):
    args, transport, version = prepare(weixin, db_session, app, monkeypatch)
    version.status = "uploading"
    db_session.commit()
    with pytest.raises(ControlServiceError):
        send_file(**args)
    assert not any(endpoint == "sendmessage" for endpoint, _ in transport.calls)


def test_binding_revocation_during_upload_prevents_send(weixin, db_session, app, monkeypatch):
    args, transport, _ = prepare(weixin, db_session, app, monkeypatch)
    def upload(*_a, **_k):
        binding = db_session.scalar(select(ChannelBinding))
        binding.status = "paused"
        db_session.commit()
        return {"type": 4}
    monkeypatch.setattr("fde_api.control.file_delivery.upload_attachment", upload)
    with pytest.raises(ControlServiceError):
        send_file(**args)
    assert not any(endpoint == "sendmessage" for endpoint, _ in transport.calls)
