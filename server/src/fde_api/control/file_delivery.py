"""Atomic delivery of an existing authorized file version to the actor's WeChat.

No export or project-plan logic: skills compose those separate operations.
"""
import hashlib
import re

from flask import current_app
from sqlalchemy import select

from fde_api.auth.models import User
from fde_api.control.access import capabilities_for_level, effective_ai_access
from fde_api.control.api_actions import _event, _events, _result
from fde_api.control.clawbot_weixin import client, unseal
from fde_api.control.models import ChannelBinding
from fde_api.control.service import ControlServiceError
from fde_api.control.weixin_files import MAX_ATTACHMENT_BYTES, upload_attachment
from fde_api.control.weixin_models import WeixinAccount, WeixinInbox
from fde_api.extensions import db, object_storage
from fde_api.files.models import ProjectFile, ProjectFileVersion


def send_file(*, user, claims, allowed, project_id=None, file_id=None, version_id=None):
    from fde_api.control.mcp_gateway import _project
    if any(not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", value) for value in (project_id, file_id, version_id)):
        raise ControlServiceError("invalid_parameters", "请提供有效的项目、文件和文件版本 ID。", 400)
    if "workbench.write" not in allowed or "file.search" not in allowed or not claims.get("execution_id"):
        raise ControlServiceError("forbidden", "本次执行没有文件发送权限。", 403)
    identifier = hashlib.sha256(f"send-file:{user.id}:{claims['execution_id']}:{project_id}:{file_id}:{version_id}".encode()).hexdigest()
    lock = current_app.extensions["fde_api_redis"].lock("fde:ai:action:" + identifier, timeout=180, blocking=False)
    if not lock.acquire(blocking=False):
        return {"status": "running", "action_id": identifier}
    try:
        with db.session() as session:
            _project(session, user, claims, project_id)
            current_user = session.get(User, user.id)
            if not current_user.is_active or current_user.must_change_password or current_user.auth_version != claims.get("ver") or "workbench.write" not in capabilities_for_level(effective_ai_access(current_user)[0]):
                raise ControlServiceError("forbidden", "账号授权已改变。", 403)
            previous = _result(_events(session, user.id, identifier))
            if previous:
                return previous
            file = session.get(ProjectFile, file_id)
            version = session.get(ProjectFileVersion, version_id)
            if not file or file.project_id != project_id or file.status != "active" or not version or version.file_id != file.id or version.status != "available" or version.scan_status not in {"clean", "not_required"}:
                raise ControlServiceError("file_unavailable", "文件版本尚未生成完成、不可用或不属于该项目。", 409)
            if version.size_bytes > MAX_ATTACHMENT_BYTES:
                raise ControlServiceError("file_too_large", "附件超过 20 MB，请在文件库下载。", 409)
            bound = session.execute(select(WeixinAccount, ChannelBinding).join(ChannelBinding).where(
                ChannelBinding.user_id == user.id, ChannelBinding.status == "active", ChannelBinding.commands_enabled.is_(True))).first()
            if not bound or not bound[0].credentials_encrypted:
                raise ControlServiceError("wechat_unbound", "请先绑定当前账号的微信 ClawBot。", 409)
            account, binding = bound
            encrypted = account.credentials_encrypted
            credentials = unseal(encrypted)
            inbox = session.scalar(select(WeixinInbox).where(WeixinInbox.account_id == account.id).order_by(WeixinInbox.created_at.desc()).limit(1))
            payload = unseal(inbox.payload_encrypted) if inbox else {}
            if payload.get("sender") != credentials.get("ilink_user_id") or not payload.get("context_token"):
                raise ControlServiceError("wechat_context_required", "请先从绑定的微信发送一条消息，再请求发送文件。", 409)
            account_id, binding_id = account.id, binding.id
            _event(session, user, identifier, "delivery_requested", {"file_id": file.id, "version_id": version.id}, project_id)
            with object_storage.current.open_stream(version.storage_key) as stream:
                content = stream.read(MAX_ATTACHMENT_BYTES + 1)
            media = upload_attachment(client(), credentials=credentials, content=content, filename=version.original_filename)
            _event(session, user, identifier, "delivery_uploaded", {"file_id": file.id, "version_id": version.id}, project_id)
            session.expire_all()
            account = session.get(WeixinAccount, account_id)
            binding = session.get(ChannelBinding, binding_id)
            current_user = session.get(User, user.id)
            _project(session, current_user, claims, project_id)
            session.refresh(version)
            session.refresh(file)
            if (not account or account.credentials_encrypted != encrypted or not binding or binding.status != "active"
                    or not binding.commands_enabled or binding.user_id != user.id or not current_user.is_active
                    or current_user.must_change_password or current_user.auth_version != claims.get("ver")
                    or "workbench.write" not in capabilities_for_level(effective_ai_access(current_user)[0])
                    or file.status != "active" or version.status != "available" or version.scan_status not in {"clean", "not_required"}):
                raise ControlServiceError("forbidden", "文件、账号权限或微信绑定已改变，已停止发送。", 403)
            _event(session, user, identifier, "started", {}, project_id)
            client().call("sendmessage", base_url=credentials["base_url"], token=credentials["bot_token"], payload={"msg": {
                "from_user_id": "", "to_user_id": credentials["ilink_user_id"], "client_id": "fde-file-" + identifier,
                "message_type": 2, "message_state": 2, "context_token": payload["context_token"], "item_list": [media]}})
            outcome = {"status": "completed", "delivery_status": "accepted_by_wechat", "file_id": file.id,
                "version_id": version.id, "filename": version.original_filename,
                "message": "微信接口已接受文件附件发送；不代表用户已阅读。"}
            _event(session, user, identifier, "finished", outcome, project_id)
            return outcome
    finally:
        try:
            lock.release()
        except Exception:
            pass
