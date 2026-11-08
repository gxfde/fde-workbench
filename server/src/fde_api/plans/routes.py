"""plans 蓝图：6 路由（V3.1 P0-3，全部不进 api_catalog——治理审阅面）。"""

from flask import Blueprint, g, jsonify, request

from fde_api.auth.decorators import require_auth
from fde_api.errors import error_response
from fde_api.plans import service

plans_blueprint = Blueprint("plans", __name__, url_prefix="/api/v1")


@plans_blueprint.errorhandler(service.PlansServiceError)
def service_error(error):
    return error_response(error.code, error.message, error.status, error.detail or None)


def _payload():
    value = request.get_json(silent=True)
    return value if isinstance(value, dict) else {}


@plans_blueprint.post("/projects/<project_id>/delivery-plans/generate")
@require_auth
def generate_plan(project_id):
    """从已批准需求/已接受事实/confirmed 术语确定性拼装方案草稿（can_manage）。"""
    data = service.generate_plan(actor=g.current_user, project_id=project_id)
    return jsonify({"data": data, "error": None}), 201


@plans_blueprint.get("/projects/<project_id>/delivery-plans")
@require_auth
def list_plans(project_id):
    """方案清单（can_view）：?status= 过滤。"""
    data = service.list_plans(
        actor=g.current_user, project_id=project_id, status=request.args.get("status")
    )
    return jsonify({"data": data, "error": None})


@plans_blueprint.get("/delivery-plans/<plan_id>")
@require_auth
def get_plan(plan_id):
    """方案详情（can_view）：条目+任务映射。"""
    data = service.get_plan(actor=g.current_user, plan_id=plan_id)
    return jsonify({"data": data, "error": None})


@plans_blueprint.patch("/delivery-plans/<plan_id>/review")
@require_auth
def review_plan(plan_id):
    """审阅（can_manage）：approved/rejected；approved 使旧 published 退位。"""
    data = service.review_plan(actor=g.current_user, plan_id=plan_id, payload=_payload())
    return jsonify({"data": data, "error": None})


@plans_blueprint.post("/delivery-plans/<plan_id>/publish")
@require_auth
def publish_plan(plan_id):
    """发布（can_manage）：approved → published；旧 published 退位 superseded。"""
    data = service.publish_plan(actor=g.current_user, plan_id=plan_id)
    return jsonify({"data": data, "error": None})


@plans_blueprint.post("/delivery-plans/<plan_id>/tasks")
@require_auth
def create_plan_tasks(plan_id):
    """条目→既有任务（can_manage）：dry_run 预览 / 选择性创建 / 幂等跳过。"""
    data = service.create_plan_tasks(actor=g.current_user, plan_id=plan_id, payload=_payload())
    return jsonify({"data": data, "error": None})
