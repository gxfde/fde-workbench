"""quality 蓝图：5 路由（V3.1 P1-2，全部不进 api_catalog——治理审阅面）。

任务书 §10 API 目标语义的项目域落法（偏差注记见 CHANGELOG）：生成/列表挂
项目域（与 delivery-plans 同惯例），review/execute 保留任务书全局路径
（项目范围经行加载校验，沿 /delivery-plans/{id}/review 先例）。
"""

from flask import Blueprint, g, jsonify, request

from fde_api.auth.decorators import require_auth
from fde_api.errors import error_response
from fde_api.quality import service

quality_blueprint = Blueprint("quality", __name__, url_prefix="/api/v1")


@quality_blueprint.errorhandler(service.QualityServiceError)
def service_error(error):
    return error_response(error.code, error.message, error.status, error.detail or None)


def _payload():
    value = request.get_json(silent=True)
    return value if isinstance(value, dict) else {}


@quality_blueprint.post("/projects/<project_id>/test-plans/generate")
@require_auth
def generate_test_plan(project_id):
    """从已批准需求确定性拼装测试计划草稿（can_manage）；可带 source_task_id。"""
    data = service.generate_test_plan(actor=g.current_user, project_id=project_id, payload=_payload())
    return jsonify({"data": data, "error": None}), 201


@quality_blueprint.get("/projects/<project_id>/test-plans")
@require_auth
def list_test_plans(project_id):
    """计划清单（can_view）：?task_id= 按来源任务过滤（任务书 GET /tasks/{id}/test-plans 语义）。"""
    data = service.list_plans(
        actor=g.current_user, project_id=project_id, task_id=request.args.get("task_id")
    )
    return jsonify({"data": data, "error": None})


@quality_blueprint.get("/test-plans/<plan_id>")
@require_auth
def get_test_plan(plan_id):
    """计划详情（can_view）：用例全量。"""
    data = service.get_plan(actor=g.current_user, plan_id=plan_id)
    return jsonify({"data": data, "error": None})


@quality_blueprint.patch("/test-plans/<plan_id>/review")
@require_auth
def review_test_plan(plan_id):
    """审阅（can_manage）：approved（需求覆盖闸+旧 approved 退位）/rejected→superseded。"""
    data = service.review_test_plan(actor=g.current_user, plan_id=plan_id, payload=_payload())
    return jsonify({"data": data, "error": None})


@quality_blueprint.post("/test-plans/<plan_id>/execute")
@require_auth
def execute_test_plan(plan_id):
    """登记执行结果（can_manage）：append-only；production 硬闸；报告指针+sha256 成对。"""
    data = service.execute_test_plan(actor=g.current_user, plan_id=plan_id, payload=_payload())
    return jsonify({"data": data, "error": None})


@quality_blueprint.get("/test-executions/<execution_id>")
@require_auth
def get_test_execution(execution_id):
    """执行记录（can_view）。"""
    data = service.get_execution(actor=g.current_user, execution_id=execution_id)
    return jsonify({"data": data, "error": None})
