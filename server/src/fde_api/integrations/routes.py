"""项目本体绑定路由（V3.3 WP4 段 1；任务书 §5.2 API 路径）。

蓝图无条件进 _BLUEPRINT_SPECS（蓝图注册表单一真身机器闸 P2-5，禁止
app.py 出现绕注册表的直接注册）；FDE_ONTOLOGY_ENABLED 门控收敛在
integrations.service.ensure_enabled()——关闭 ⇒ 全部路由 404 not_found，
禁用面与不存在面不可区分（对齐 diagnostics_enabled 先例，D12）。

D13：门控判定**先于**鉴权（蓝图级 before_request 预闸）——本蓝图四入口
挂 @require_auth，若只在服务层设闸，未鉴权探针得 401（=面存在）而非
404（=面不存在），构成存在性泄露。
"""

from __future__ import annotations

from typing import Any

from flask import Blueprint, g, jsonify, request

from fde_api.auth.decorators import require_auth
from fde_api.errors import error_response
from fde_api.integrations.service import (
    BindingError,
    approve_upgrade,
    check_binding_grounding,
    create_binding,
    ensure_enabled,
    get_binding_lineage,
    list_bindings,
    propose_upgrade,
)

ontology_bindings_blueprint = Blueprint(
    "ontology_bindings", __name__, url_prefix="/api/v1/projects"
)


def _binding_error(exc: BindingError):
    return error_response(exc.code, exc.message, exc.status)


@ontology_bindings_blueprint.before_request
def _gate_disabled_surface():
    """D13：关闭态判定**先于**鉴权。

    D12 把门控收敛在服务层，而本蓝图四入口挂 `@require_auth` ⇒ 未鉴权探针
    先撞鉴权（401）而非 404——「该面存在」被泄露（与 M8 红队扫描面冲突）。
    蓝图级预闸把判定提到鉴权之前：关闭态下无论是否鉴权，一律与「路径不
    存在」同形（404 not_found，同一文案）。服务层闸保留作纵深防御（绕
    过蓝图直调服务层仍 404）。
    """
    try:
        ensure_enabled()
    except BindingError as exc:
        return _binding_error(exc)
    return None


def _json_object() -> dict[str, Any]:
    """请求体必须是 JSON object（评审 W-E：数组/标量体此前 AttributeError→500）。"""
    payload = request.get_json(silent=True)
    return payload if isinstance(payload, dict) else {}


@ontology_bindings_blueprint.get("/<project_id>/ontology-bindings")
@require_auth
def list_bindings_route(project_id: str):
    try:
        bindings = list_bindings(actor=g.current_user, project_id=project_id)
    except BindingError as exc:
        return _binding_error(exc)
    return jsonify({"data": bindings, "error": None})


@ontology_bindings_blueprint.post("/<project_id>/ontology-bindings")
@require_auth
def create_binding_route(project_id: str):
    try:
        binding = create_binding(actor=g.current_user, project_id=project_id, payload=_json_object())
    except BindingError as exc:
        return _binding_error(exc)
    return jsonify({"data": binding, "error": None}), 201


@ontology_bindings_blueprint.post(
    "/<project_id>/ontology-bindings/<binding_id>/upgrade-proposal"
)
@require_auth
def propose_upgrade_route(project_id: str, binding_id: str):
    try:
        upgrade = propose_upgrade(
            actor=g.current_user, project_id=project_id, binding_id=binding_id, payload=_json_object()
        )
    except BindingError as exc:
        return _binding_error(exc)
    return jsonify({"data": upgrade, "error": None}), 201


@ontology_bindings_blueprint.post(
    "/<project_id>/ontology-bindings/<binding_id>/approve-upgrade/<upgrade_id>"
)
@require_auth
def approve_upgrade_route(project_id: str, binding_id: str, upgrade_id: str):
    payload = _json_object()
    decision = str(payload.get("decision", ""))
    annotation = payload.get("annotation")
    try:
        result = approve_upgrade(
            actor=g.current_user,
            project_id=project_id,
            binding_id=binding_id,
            upgrade_id=upgrade_id,
            decision=decision,
            annotation=annotation,
        )
    except BindingError as exc:
        return _binding_error(exc)
    return jsonify({"data": result, "error": None})


@ontology_bindings_blueprint.post(
    "/<project_id>/ontology-bindings/<binding_id>/grounding-check"
)
@require_auth
def check_binding_grounding_route(project_id: str, binding_id: str):
    """D21 / WP4③：触发项目已固定本体版本的对象类型接地质量检查。"""
    try:
        report = check_binding_grounding(
            actor=g.current_user,
            project_id=project_id,
            binding_id=binding_id,
            payload=_json_object(),
        )
    except BindingError as exc:
        return _binding_error(exc)
    return jsonify({"data": report, "error": None})


@ontology_bindings_blueprint.get(
    "/<project_id>/ontology-bindings/<binding_id>/lineage"
)
@require_auth
def get_binding_lineage_route(project_id: str, binding_id: str):
    """D21 / WP4③：只读获取项目已固定本体版本的双层血缘（定义血缘 + 实例引用追溯）。"""
    try:
        lineage = get_binding_lineage(
            actor=g.current_user,
            project_id=project_id,
            binding_id=binding_id,
            object_type=request.args.get("object_type"),
            object_ref_id=request.args.get("object_ref_id"),
        )
    except BindingError as exc:
        return _binding_error(exc)
    return jsonify({"data": lineage, "error": None})

