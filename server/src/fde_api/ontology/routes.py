"""本体注册表路由（V3 T-O2/T-O3/T-I1；设计 ontology-registry-v1 §4）。

- ``GET  /api/v1/projects/<id>/ontology/terms``（can_view，T-O1 的公开读面）：
  术语清单，``?q=`` 大小写不敏感匹配规范名或别名（别名命中返回属主行）。
- ``GET  /api/v1/projects/<id>/ontology/terms/<term_id>/impact``（can_view，
  V3 T-I1 影响分析）：引用该术语的研究客体/邻接边/表单清单——名字域纽带
  （规范名 ∪ 别名 ∪ 并入来源名），变集拍板前的人工影响面评审。
- ``GET  /api/v1/projects/<id>/ontology/relation-types``（can_view）：列出对项目
  生效的类型（全局 ∪ 项目内，项目内遮蔽同名全局）。
- ``GET  /api/v1/ontology/relation-types``（require_auth，T-O2c 全局只读面）：
  全局注册类型行（project_id 为空，不含项目内行）——无项目上下文的消费方
  （行业模板/调研定义编辑器）拉取注册类型选项；人工路径，不进 api_catalog。
- ``POST /api/v1/projects/<id>/ontology/relation-types``（can_manage）：登记类型；
  ``scope=global`` 另需管理员。人工路径——**有意不进 api_catalog**（AI 候选
  走 change_set）。
- ``POST /api/v1/projects/<id>/ontology/relation-types/<id>/retire``（can_manage）：
  停用类型（禁新边、存量边只读）。设计 §4 的表格未列本条，是为让 §5 用例 7
  的「retired 后建边 409」在人工路径上可达——偏差见 backlog T-O2 实施记录。
- 变更集（T-O3，AI 候选唯一入口的人工评审面）：
  ``POST   …/ontology/change-sets``（提出，draft，confirm 前不物化）、
  ``GET    …/ontology/change-sets``（清单，?status= 过滤）、
  ``GET    …/ontology/change-sets/<id>``（详情：载荷 + diff 摘要 + 指纹）、
  ``POST   …/ontology/change-sets/<id>/submit``（draft→in_review，算 base 指纹；
  设计 §4 未列本条，状态机的并发防护锚点——偏差见 backlog T-O3 实施记录）、
  ``POST   …/ontology/change-sets/<id>/confirm``（拍板：指纹复核 + 单事务逐项
  物化；验收分离，拍板人 ≠ 提交人）、
  ``POST   …/ontology/change-sets/<id>/reject``（否决，留 reason）。
  七条全部**有意不进 api_catalog**（同 signoff 纪律：AI 不可触达拍板路径）。
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


global_ontology_blueprint = Blueprint(
    "global_ontology", __name__, url_prefix="/api/v1/ontology"
)


@global_ontology_blueprint.errorhandler(service.OntologyServiceError)
def global_service_error(error):
    return error_response(error.code, error.message, error.status)


@global_ontology_blueprint.get("/relation-types")
@require_auth
def list_global_relation_types():
    """全局注册类型只读面（T-O2c）：?kind= 按种类过滤，全状态返回。

    无项目上下文的消费方（行业模板/调研定义编辑器）从此面拉取注册类型
    选项；只收全局行——项目内类型只对本项目生效，进全局模板会在其他项目
    实例化时落空。人工路径——有意不进 api_catalog（沿 T-O2 纪律）。
    """
    data = service.list_global_relation_types(kind=request.args.get("kind"))
    return jsonify({"data": data, "error": None})


@ontology_blueprint.get("/terms")
@require_auth
def list_terms(project_id: str):
    """术语只读面（can_view）：?q= 匹配规范名或别名。"""
    data = service.list_project_terms(
        actor=g.current_user,
        project_id=project_id,
        q=request.args.get("q"),
    )
    return jsonify({"data": data, "error": None})


@ontology_blueprint.get("/terms/<term_id>/impact")
@require_auth
def term_impact(project_id: str, term_id: str):
    """术语影响分析（can_view）：引用它的 subjects/links/forms 清单。

    人工评审读面——有意不进 api_catalog（沿 T-O3 纪律：本体治理面 AI
    不可直达）。
    """
    data = service.impact_project_term(
        actor=g.current_user,
        project_id=project_id,
        term_id=term_id,
    )
    return jsonify({"data": data, "error": None})


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


@ontology_blueprint.get("/change-sets")
@require_auth
def list_change_sets(project_id: str):
    """变更集清单（can_view）：?status= 按状态过滤。"""
    data = service.list_project_change_sets(
        actor=g.current_user,
        project_id=project_id,
        status=request.args.get("status"),
    )
    return jsonify({"data": data, "error": None})


@ontology_blueprint.get("/change-sets/<change_set_id>")
@require_auth
def get_change_set(project_id: str, change_set_id: str):
    """变更集详情（can_view）：diff 评审读载荷、摘要与 base 指纹。"""
    data = service.get_project_change_set(
        actor=g.current_user,
        project_id=project_id,
        change_set_id=change_set_id,
    )
    return jsonify({"data": data, "error": None})


@ontology_blueprint.post("/change-sets")
@require_auth
def create_change_set(project_id: str):
    """提出候选变更集（can_manage）→ draft：confirm 前不物化（§5 用例 1）。"""
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        raise service.OntologyServiceError(
            "invalid_request", "请求内容必须为 JSON 对象。", 400
        )
    data = service.propose_project_change_set(
        actor=g.current_user, project_id=project_id, payload=payload
    )
    return jsonify({"data": data, "error": None}), 201


@ontology_blueprint.post("/change-sets/<change_set_id>/submit")
@require_auth
def submit_change_set(project_id: str, change_set_id: str):
    """draft → in_review（can_manage）：计算 base 指纹（并发防护锚点）。"""
    data = service.submit_project_change_set(
        actor=g.current_user,
        project_id=project_id,
        change_set_id=change_set_id,
    )
    return jsonify({"data": data, "error": None})


@ontology_blueprint.post("/change-sets/<change_set_id>/confirm")
@require_auth
def confirm_change_set(project_id: str, change_set_id: str):
    """拍板确认（can_manage 且 ≠ 提交人）：指纹复核 + 单事务逐项物化。"""
    data = service.confirm_project_change_set(
        actor=g.current_user,
        project_id=project_id,
        change_set_id=change_set_id,
    )
    return jsonify({"data": data, "error": None})


@ontology_blueprint.post("/change-sets/<change_set_id>/reject")
@require_auth
def reject_change_set(project_id: str, change_set_id: str):
    """否决（can_manage 且 ≠ 提交人）：只改状态留 reason。"""
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        raise service.OntologyServiceError(
            "invalid_request", "请求内容必须为 JSON 对象。", 400
        )
    data = service.reject_project_change_set(
        actor=g.current_user,
        project_id=project_id,
        change_set_id=change_set_id,
        payload=payload,
    )
    return jsonify({"data": data, "error": None})
