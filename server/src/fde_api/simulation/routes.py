"""模拟训练场 API（V3.2 G2）。

蓝图前缀 ``/api/v1/simulation``。**有意不进 api_catalog**——这是训练场治理面
（与 ``ontology`` 全局面、``agents`` admin 面、``expirations`` 投影面同款惯例），
AI 不经此面读写模拟资产。

权限：全部端点要求 ``project_operator`` 档（fde_engineer / project_lead /
admin）；``viewer`` 档无权访问。鉴权走既有 ``require_auth`` 装饰器 + 服务层
能力档判定（服务层是唯一权威，路由层不复制判定逻辑）。
"""
from __future__ import annotations

from flask import Blueprint, g, jsonify, request

from fde_api.auth.decorators import require_auth
from fde_api.errors import error_response
from fde_api.simulation import service

simulation_blueprint = Blueprint("simulation", __name__, url_prefix="/api/v1/simulation")


@simulation_blueprint.errorhandler(service.ScenarioServiceError)
def service_error(error):
    return error_response(error.code, error.message, error.status, error.detail or None)


def _payload() -> dict:
    value = request.get_json(silent=True)
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise service.ScenarioServiceError(
            "invalid_request", "请求内容必须为 JSON 对象。", 400
        )
    return value


def _data(value):
    return jsonify({"data": value, "error": None})


def _int_arg(name: str, default: int | None = None) -> int | None:
    raw = request.args.get(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        raise service.ScenarioServiceError("invalid_request", f"{name} 必须是整数。", 400)


# ---------------------------------------------------------------------------
# 场景库
# ---------------------------------------------------------------------------


@simulation_blueprint.get("/scenarios")
@require_auth
def list_scenarios():
    """场景列表（默认每个分支只返回有效版本；include_history=true 返回全史）。"""
    data = service.list_scenarios(
        actor=g.current_user,
        split=request.args.get("split"),
        industry=request.args.get("industry"),
        variant=request.args.get("variant"),
        status=request.args.get("status"),
        keyword=request.args.get("q"),
        include_history=request.args.get("include_history") == "true",
        limit=_int_arg("limit", service.LIST_PAGE_SIZE) or service.LIST_PAGE_SIZE,
    )
    return _data(data)


@simulation_blueprint.post("/scenarios")
@require_auth
def create_scenario():
    """创建场景（版本 1）。"""
    data = service.create_scenario(actor=g.current_user, payload=_payload())
    return _data(data), 201


@simulation_blueprint.get("/scenarios/<scenario_id>")
@require_auth
def get_scenario(scenario_id):
    """场景详情。"""
    return _data(service.get_scenario(actor=g.current_user, scenario_id=scenario_id))


@simulation_blueprint.patch("/scenarios/<scenario_id>")
@require_auth
def update_scenario(scenario_id):
    """编辑场景 → 追加新版本（既有版本不可变）。"""
    data = service.update_scenario(
        actor=g.current_user, scenario_id=scenario_id, payload=_payload()
    )
    return _data(data), 201


@simulation_blueprint.post("/scenarios/<scenario_id>/duplicate")
@require_auth
def duplicate_scenario(scenario_id):
    """复制场景 → 新业务键。"""
    data = service.duplicate_scenario(
        actor=g.current_user, scenario_id=scenario_id, payload=_payload()
    )
    return _data(data), 201


@simulation_blueprint.post("/scenarios/<scenario_id>/archive")
@require_auth
def archive_scenario(scenario_id):
    """归档场景（追加 archived 新版本）。"""
    data = service.archive_scenario(actor=g.current_user, scenario_id=scenario_id)
    return _data(data)


@simulation_blueprint.get("/scenarios/<scenario_id>/versions")
@require_auth
def list_versions(scenario_id):
    """某案例（业务键）的全部分支与版本历史。"""
    with_version_key = request.args.get("scenario_key")
    if not with_version_key:
        current = service.get_scenario(actor=g.current_user, scenario_id=scenario_id)
        with_version_key = current["scenario_key"]
    return _data(service.list_versions(actor=g.current_user, scenario_key=with_version_key))


@simulation_blueprint.post("/scenarios/import")
@require_auth
def import_scenarios():
    """批量导入场景（逐条校验，非法条目逐条回显）。"""
    return _data(service.import_scenarios(actor=g.current_user, payload=_payload()))


@simulation_blueprint.get("/scenarios/export")
@require_auth
def export_scenarios():
    """导出现场景（有效版本）。"""
    include_reference = request.args.get("include_reference") != "false"
    data = service.export_scenarios(
        actor=g.current_user,
        scenario_key=request.args.get("scenario_key"),
        split=request.args.get("split"),
        variant=request.args.get("variant"),
        include_reference=include_reference,
    )
    return _data(data)
