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
POST  /projects/<id>/transform-plans/<plan_id>/runs   提交隔离执行（WP3：幂等键必填；
      files 版本锚输入；账本零行值原文；append-only）
GET   /projects/<id>/transform-runs               执行记录清单
GET   /projects/<id>/transform-runs/<run_id>      执行详情（守恒/账本/血缘/质量报告）
GET   /projects/<id>/transform-runs/<run_id>/preview          样本预览受控窗口（WP4：
      limit 封顶；样本性质 note 显式声明——预览≠完整断言，04 §3.2）
GET   /projects/<id>/transform-runs/<run_id>/diff             行数去向对照（WP4：产出/
      拒绝 reason 分组/溢出；质量条目单列 quality_flags；弱守恒口径）
GET   /projects/<id>/transform-runs/<run_id>/lineage          两级血缘拼装（WP4：计划
      DAG + 执行 per-step 统计；步序不一致如实标 steps_alignment=false）
GET   /projects/<id>/transform-runs/<run_id>/quality-feedback 质量断言结构化反馈
      （WP4：Agent/工程台可消费；零行值原文）

**无 PATCH/DELETE**：画像/计划/执行记录均 append-only；关系候选无翻产通道（03 §77）。
"""
from __future__ import annotations

from flask import Blueprint, g, jsonify, request

from fde_api.auth.decorators import require_auth
from fde_api.data_engineering import service
from fde_api.errors import error_response

data_engineering_blueprint = Blueprint("data_engineering", __name__, url_prefix="/api/v1")

MAX_UPLOAD_BYTES = 5 * 1024 * 1024  # 与 profiling.MAX_PROFILE_BYTES 对齐

PREVIEW_DEFAULT_LIMIT = 20
PREVIEW_MAX_LIMIT = 100


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


@data_engineering_blueprint.post("/projects/<project_id>/transform-plans/<plan_id>/runs")
@require_auth
def submit_transform_run(project_id, plan_id):
    """提交隔离执行（AF2-WP3，17 号 v1.0）：``Idempotency-Key`` 必填（幂等重放
    返回既有 run）；body ``{input: {kind: file_version, file_version_id}}``。
    执行闸链沿 17 号 §4.1：S-01 → 计划归属 → 纵深再校验 → 快照锚 → 纯函数
    执行 → 落库+审计。产物 append-only；账本零行值原文。"""
    idem = str(request.headers.get("Idempotency-Key") or "").strip()
    if not idem or len(idem) > 80:
        return error_response("invalid_request", "缺少或非法 Idempotency-Key（≤80 字符）。", 400)
    payload = request.get_json(silent=True) or {}
    input_ref = payload.get("input")
    if not isinstance(input_ref, dict):
        return error_response("invalid_request", "缺少 input 对象。", 400)
    result = service.submit_transform_run(
        actor=g.current_user,
        project_id=project_id,
        plan_id=plan_id,
        input_ref=input_ref,
        idempotency_key=idem,
    )
    return jsonify({"data": result, "error": None}), 201


@data_engineering_blueprint.get("/projects/<project_id>/transform-runs")
@require_auth
def list_transform_runs(project_id):
    payload = service.list_transform_runs(actor=g.current_user, project_id=project_id)
    return jsonify({"data": payload, "error": None}), 200


@data_engineering_blueprint.get("/projects/<project_id>/transform-runs/<run_id>")
@require_auth
def get_transform_run(project_id, run_id):
    payload = service.get_transform_run(
        actor=g.current_user, project_id=project_id, run_id=run_id
    )
    return jsonify({"data": payload, "error": None}), 200


def _preview_limit() -> int | None:
    """解析 preview ``limit`` 查询参数：缺省=默认窗口；非整数或 <1 ⇒ None
    （由调用方回 400）；超上限封顶 ``PREVIEW_MAX_LIMIT``。"""
    raw = request.args.get("limit")
    if raw is None or raw == "":
        return PREVIEW_DEFAULT_LIMIT
    try:
        limit = int(raw)
    except ValueError:
        return None
    if limit < 1:
        return None
    return min(limit, PREVIEW_MAX_LIMIT)


@data_engineering_blueprint.get("/projects/<project_id>/transform-runs/<run_id>/preview")
@require_auth
def preview_transform_run(project_id, run_id):
    """样本预览受控窗口（AF2-WP4 预览面）：产物行集 ``limit`` 封顶读法，
    样本性质随 ``note`` 显式声明（预览＝早期检查，完整断言走全量统计件）。"""
    limit = _preview_limit()
    if limit is None:
        return error_response("invalid_request", "limit 须为 ≥1 的整数。", 400)
    payload = service.preview_transform_run(
        actor=g.current_user, project_id=project_id, run_id=run_id, limit=limit
    )
    return jsonify({"data": payload, "error": None}), 200


@data_engineering_blueprint.get("/projects/<project_id>/transform-runs/<run_id>/diff")
@require_auth
def diff_transform_run(project_id, run_id):
    """行数去向对照（AF2-WP4 差异面）：弱守恒口径呈现产出/拒绝/溢出去向，
    质量条目单列 quality_flags。"""
    payload = service.diff_transform_run(
        actor=g.current_user, project_id=project_id, run_id=run_id
    )
    return jsonify({"data": payload, "error": None}), 200


@data_engineering_blueprint.get("/projects/<project_id>/transform-runs/<run_id>/lineage")
@require_auth
def lineage_transform_run(project_id, run_id):
    """两级血缘拼装（AF2-WP4 血缘呈现）：计划 DAG + 执行 per-step 统计。"""
    payload = service.lineage_transform_run(
        actor=g.current_user, project_id=project_id, run_id=run_id
    )
    return jsonify({"data": payload, "error": None}), 200


@data_engineering_blueprint.get("/projects/<project_id>/transform-runs/<run_id>/quality-feedback")
@require_auth
def quality_feedback_transform_run(project_id, run_id):
    """质量断言结构化反馈（AF2-WP4 反馈面）：Agent/工程台可消费；零行值原文。"""
    payload = service.quality_feedback_transform_run(
        actor=g.current_user, project_id=project_id, run_id=run_id
    )
    return jsonify({"data": payload, "error": None}), 200
