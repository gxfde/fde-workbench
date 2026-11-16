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

from fde_api.auth.decorators import require_auth, require_role
from fde_api.errors import error_response
from fde_api.integrations.service import (
    BindingError,
    approve_binding_action,
    approve_upgrade,
    check_binding_grounding,
    create_binding,
    ensure_enabled,
    execute_binding_action,
    get_binding_action,
    get_binding_lineage,
    issue_trustboard_delivery_link,
    list_bindings,
    propose_binding_action,
    propose_upgrade,
    run_binding_logic,
)

ontology_bindings_blueprint = Blueprint(
    "ontology_bindings", __name__, url_prefix="/api/v1/projects"
)


def _binding_error(exc: BindingError):
    return error_response(exc.code, exc.message, exc.status)


def _no_store_json(payload: dict[str, Any]):
    """含凭据的响应一律 no-store（禁缓存）+ Pragma no-cache。

    交付链接是**一次性消费的凭据**（M6-WP6-R4）：落进浏览器/代理缓存即等于
    把凭据再发一次。
    """
    resp = jsonify(payload)
    resp.headers["Cache-Control"] = "no-store"
    resp.headers["Pragma"] = "no-cache"
    return resp


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


@ontology_bindings_blueprint.post("/<project_id>/ontology-bindings/trustboard/delivery-link")
@require_role("admin", "project_lead")
def issue_trustboard_delivery_link_route(project_id: str):
    """签发 TrustBoard 客户只读看板交付链接（M6-WP6；M6-WP6-R4 一次性消费）。

    响应体含凭据（交付链接）⇒ **no-store**（禁缓存）；链接不落库、不进日志。
    每次调用换一枚新链接——交付链接一次性消费，换设备/浏览器须重新签发。
    角色闸限 admin / project_lead（客户关系责任角色；工程师如需签发再单开决策单）。
    """
    try:
        link = issue_trustboard_delivery_link(actor=g.current_user, project_id=project_id)
    except BindingError as exc:
        return _binding_error(exc)
    return _no_store_json({"data": link, "error": None})


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



@ontology_bindings_blueprint.post(
    "/<project_id>/ontology-bindings/<binding_id>/logic/<logic_key>/run"
)
@require_auth
def run_binding_logic_route(project_id: str, binding_id: str, logic_key: str):
    """D24 / §13 M4 条 1：项目已固定版本的 Logic 执行（D26 注入守卫在 runtime 侧）。"""
    try:
        result = run_binding_logic(
            actor=g.current_user,
            project_id=project_id,
            binding_id=binding_id,
            logic_key=logic_key,
            payload=_json_object(),
        )
    except BindingError as exc:
        return _binding_error(exc)
    return jsonify({"data": result, "error": None})


@ontology_bindings_blueprint.post(
    "/<project_id>/ontology-bindings/<binding_id>/actions/<action_key>/propose"
)
@require_auth
def propose_binding_action_route(project_id: str, binding_id: str, action_key: str):
    """D25/D28 / 条 5：提议受控动作（默认 dry-run，零副作用）。"""
    try:
        result = propose_binding_action(
            actor=g.current_user,
            project_id=project_id,
            binding_id=binding_id,
            action_key=action_key,
            payload=_json_object(),
        )
    except BindingError as exc:
        return _binding_error(exc)
    return jsonify({"data": result, "error": None}), 201


@ontology_bindings_blueprint.post(
    "/<project_id>/ontology-bindings/<binding_id>/action-requests/<request_id>/approvals"
)
@require_auth
def approve_binding_action_route(project_id: str, binding_id: str, request_id: str):
    """D28 / 条 6：审批子表代理（I4 自批 403 由 runtime 强制）。"""
    try:
        result = approve_binding_action(
            actor=g.current_user,
            project_id=project_id,
            binding_id=binding_id,
            request_id=request_id,
            payload=_json_object(),
        )
    except BindingError as exc:
        return _binding_error(exc)
    return jsonify({"data": result, "error": None})


@ontology_bindings_blueprint.get(
    "/<project_id>/ontology-bindings/<binding_id>/action-requests/<request_id>"
)
@require_auth
def get_binding_action_route(project_id: str, binding_id: str, request_id: str):
    """D28：只读查询 ActionRequest 状态机当前态 + 审批留痕。"""
    try:
        result = get_binding_action(
            actor=g.current_user,
            project_id=project_id,
            binding_id=binding_id,
            request_id=request_id,
        )
    except BindingError as exc:
        return _binding_error(exc)
    return jsonify({"data": result, "error": None})


@ontology_bindings_blueprint.post(
    "/<project_id>/ontology-bindings/<binding_id>/actions/<action_key>/execute"
)
@require_auth
def execute_binding_action_route(project_id: str, binding_id: str, action_key: str):
    """D28 / 条 6：执行代理（仅 approved；runtime 执行前重验 S-13）。"""
    try:
        result = execute_binding_action(
            actor=g.current_user,
            project_id=project_id,
            binding_id=binding_id,
            action_key=action_key,
            payload=_json_object(),
        )
    except BindingError as exc:
        return _binding_error(exc)
    return jsonify({"data": result, "error": None})
