"""data_engineering 蓝图（AF2-WP1）：资料画像三路由（项目域，全部不进
api_catalog 治理面——工程台/Agent 消费面沿 quality 先例）。

POST  /projects/<id>/data-profiles           multipart 上传→画像（member 级）
GET   /projects/<id>/data-profiles           清单
GET   /projects/<id>/data-profiles/<pid>     详情（快照哈希可复验）

**无 PATCH/DELETE**：画像报告 append-only；关系候选无翻产通道（03 §77）。
"""
from __future__ import annotations

from flask import Blueprint, g, jsonify, request

from fde_api.auth.decorators import require_auth
from fde_api.data_engineering import service
from fde_api.errors import error_response

data_engineering_blueprint = Blueprint("data_engineering", __name__, url_prefix="/api/v1")

MAX_UPLOAD_BYTES = 5 * 1024 * 1024  # 与 profiling.MAX_PROFILE_BYTES 对齐


@data_engineering_blueprint.errorhandler(service.DataEngineeringError)
def service_error(error):
    return error_response(error.code, error.message, error.status, error.detail or None)


@data_engineering_blueprint.post("/projects/<project_id>/data-profiles")
@require_auth
def create_profile(project_id):
    """multipart 上传（字段名 ``file``）→ 只读画像（member 级 can_view）。"""
    upload = request.files.get("file")
    if upload is None or not upload.filename:
        return error_response("file_missing", "缺少 file 字段。", 400)
    data = upload.read()
    if not data:
        return error_response("empty_file", "空文件无可画像内容。", 400)
    if len(data) > MAX_UPLOAD_BYTES:
        return error_response("file_too_large", f"画像输入超上限（>{MAX_UPLOAD_BYTES} 字节）。", 400)
    payload = service.create_profile(
        actor=g.current_user, project_id=project_id, filename=upload.filename, data=data
    )
    return jsonify({"data": payload, "error": None}), 201


@data_engineering_blueprint.get("/projects/<project_id>/data-profiles")
@require_auth
def list_profiles(project_id):
    payload = service.list_profiles(actor=g.current_user, project_id=project_id)
    return jsonify({"data": payload, "error": None}), 200


@data_engineering_blueprint.get("/projects/<project_id>/data-profiles/<profile_id>")
@require_auth
def get_profile(project_id, profile_id):
    payload = service.get_profile(
        actor=g.current_user, project_id=project_id, profile_id=profile_id
    )
    return jsonify({"data": payload, "error": None}), 200
