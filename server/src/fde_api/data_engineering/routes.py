"""data_engineering 蓝图（AF2-WP1 画像 + AF2-WP2 TransformPlan 计划面）：
项目域路由，全部不进 api_catalog 治理面——工程台/Agent 消费面沿 quality 先例。

POST  /projects/<id>/data-profiles                multipart 上传→画像（member 级）
POST  /projects/<id>/ontology-data-profiles       连接器侧 DB 内省画像（WP1 第二批/D5，
      经 ontology_client api-spec 1.3.8-af2；本体未启用 fail-closed 503）
GET   /projects/<id>/data-profiles                清单
GET   /projects/<id>/data-profiles/<pid>          详情（快照哈希可复验）
POST  /projects/<id>/transform-plans              类型化转换计划落库（WP2 计划面：
      静态校验不过 ⇒ 400 零落库；无编译无执行）
GET   /projects/<id>/transform-plans              计划清单
GET   /projects/<id>/transform-plans/<plan_id>    计划详情（校验报告 + DAG）

**无 PATCH/DELETE**：画像与计划均 append-only；关系候选无翻产通道（03 §77）。
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


@data_engineering_blueprint.post("/projects/<project_id>/ontology-data-profiles")
@require_auth
def create_ontology_profile(project_id):
    """连接器侧 DB 内省画像（AF2-WP1 第二批 / D5）：JSON body
    ``{ontology_id, version_id, data_source_key, org_id}`` → 经 ontology_client
    （api-spec 1.3.8-af2）取回 runtime 沙箱内已掩码的画像产物并落库。
    本体未启用 fail-closed 503（零出站，§15）；非项目成员 404（S-01）。"""
    payload = request.get_json(silent=True) or {}
    required = ("ontology_id", "version_id", "data_source_key", "org_id")
    missing = [field for field in required if not str(payload.get(field) or "").strip()]
    if missing:
        return error_response("invalid_request", f"缺少必填字段：{'、'.join(missing)}。", 400)
    result = service.create_connector_profile(
        actor=g.current_user,
        project_id=project_id,
        ontology_id=str(payload["ontology_id"]).strip(),
        version_id=str(payload["version_id"]).strip(),
        data_source_key=str(payload["data_source_key"]).strip(),
        org_id=str(payload["org_id"]).strip(),
    )
    return jsonify({"data": result, "error": None}), 201


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


@data_engineering_blueprint.post("/projects/<project_id>/transform-plans")
@require_auth
def create_transform_plan(project_id):
    """类型化转换计划落库（AF2-WP2 计划面）：JSON body ``{plan}`` → 结构静态
    校验（九算子闭集/参数键集精确匹配/值域枚举/DAG 无环）→ 只落已通过校验
    的计划；失败 ⇒ 400 ``invalid_transform_plan`` 且零落库。无编译无执行
    （编译面归 WP3 design-first 门）。"""
    payload = request.get_json(silent=True) or {}
    plan = payload.get("plan")
    if not isinstance(plan, dict):
        return error_response("invalid_request", "缺少 plan 对象。", 400)
    result = service.create_transform_plan(actor=g.current_user, project_id=project_id, plan=plan)
    return jsonify({"data": result, "error": None}), 201


@data_engineering_blueprint.get("/projects/<project_id>/transform-plans")
@require_auth
def list_transform_plans(project_id):
    payload = service.list_transform_plans(actor=g.current_user, project_id=project_id)
    return jsonify({"data": payload, "error": None}), 200


@data_engineering_blueprint.get("/projects/<project_id>/transform-plans/<plan_id>")
@require_auth
def get_transform_plan(project_id, plan_id):
    payload = service.get_transform_plan(
        actor=g.current_user, project_id=project_id, plan_id=plan_id
    )
    return jsonify({"data": payload, "error": None}), 200
