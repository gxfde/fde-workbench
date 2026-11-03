"""本体注册表路由（V3 T-O2；设计 ontology-registry-v1 §4）。

术语面（§4 的 GET /ontology/terms 与 change-set 变更面）随 T-O3 的 routes.py
一并开；本轮先开**关系类型注册表**这一面：

- ``GET  /api/v1/projects/<id>/ontology/relation-types``（can_view）：列出对项目
  生效的类型（全局 ∪ 项目内，项目内遮蔽同名全局）。
- ``POST /api/v1/projects/<id>/ontology/relation-types``（can_manage）：登记类型；
  ``scope=global`` 另需管理员。人工路径——**有意不进 api_catalog**（AI 候选
  走 change_set，T-O3）。
- ``POST /api/v1/projects/<id>/ontology/relation-types/<id>/retire``（can_manage）：
  停用类型（禁新边、存量边只读）。设计 §4 的表格未列本条，是为让 §5 用例 7
  的「retired 后建边 409」在人工路径上可达——偏差见 backlog T-O2 实施记录。
"""
from __future__ import annotations

from flask import Blueprint, g, jsonify, request

from fde_api.auth.decorators import require_auth
from fde_api.errors import error_response
from fde_api.ontology import service

ontology_blueprint = Blueprint(
    "project_ontology", __name__, url_prefix="/api/v1/projects/<project_id>/ontology"
)


@ontology_blueprint.errorhandler(service.OntologyServiceError)
def service_error(error):
    return error_response(error.code, error.message, error.status)


@ontology_blueprint.get("/relation-types")
@require_auth
def list_relation_types(project_id: str):
    """类型注册表（can_view）：?kind= 按种类过滤（subject_type / link_type）。"""
    data = service.list_project_relation_types(
        actor=g.current_user,
        project_id=project_id,
        kind=request.args.get("kind"),
    )
    return jsonify({"data": data, "error": None})


@ontology_blueprint.post("/relation-types")
@require_auth
def create_relation_type(project_id: str):
    """登记类型（can_manage；scope=global 另需管理员）。人工路径——不进 api_catalog。"""
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        raise service.OntologyServiceError(
            "invalid_request", "请求内容必须为 JSON 对象。", 400
        )
    data = service.create_relation_type(
        actor=g.current_user, project_id=project_id, payload=payload
    )
    return jsonify({"data": data, "error": None}), 201


@ontology_blueprint.post("/relation-types/<relation_type_id>/retire")
@require_auth
def retire_relation_type(project_id: str, relation_type_id: str):
    """停用类型（can_manage）：禁新边、存量边只读。"""
    data = service.retire_project_relation_type(
        actor=g.current_user,
        project_id=project_id,
        relation_type_id=relation_type_id,
    )
    return jsonify({"data": data, "error": None})
