"""agents 蓝图：11 路由（goal-d4 七路由 + goal-d6 演练/恢复/试点报告 + goal-d7 配额）。

api_catalog 只收其中只读 GET（注册表/溯源/工具留痕/成本/配额）；POST run /
handoff / retry / rehearse / recover 属人工授权写路径——AI 不得代发起、
代接管、代重试（沿门禁三路由不进目录的同一红线）。
"""

from datetime import datetime, timezone

from flask import Blueprint, g, jsonify, request

from fde_api.agents import service
from fde_api.auth.decorators import require_auth
from fde_api.errors import error_response

agents_blueprint = Blueprint("agents", __name__, url_prefix="/api/v1/agents")


@agents_blueprint.errorhandler(service.AgentsServiceError)
def service_error(error):
    return error_response(error.code, error.message, error.status, error.detail or None)


def _payload():
    value = request.get_json(silent=True)
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise service.AgentsServiceError("invalid_request", "请求内容必须为 JSON 对象。", 400)
    return value


def _data(value):
    return jsonify({"data": value, "error": None})


@agents_blueprint.get("")
@require_auth
def list_agents():
    """注册表（含不可用原因，P-1 静态半边）。"""
    return _data(service.list_agents(actor=g.current_user))


@agents_blueprint.post("/<agent_id>/run")
@require_auth
def start_run(agent_id):
    """触发 run（实时鉴权 + 幂等 + 预算闸 + 脱敏渲染 + 沙箱执行）。

    201 = 新 run；200 = 幂等复用既有 run（V8：不重复计费不重复落产物）。
    """
    data, status = service.start_run(actor=g.current_user, agent_id=agent_id, payload=_payload())
    return _data(data), status


@agents_blueprint.get("/runs/<run_id>")
@require_auth
def get_run(run_id):
    """溯源：run 状态/成本/降级链 + 产物指纹（V9 反查链的 run 段锚点）。"""
    return _data(service.get_run_detail(actor=g.current_user, run_id=run_id))


_LIST_LIMIT_DEFAULT = 50
_LIST_LIMIT_MAX = 200


def _int_arg(raw: str, name: str) -> int:
    try:
        return int(raw)
    except ValueError:
        raise service.AgentsServiceError("invalid_request", f"{name} 必须是整数。", 400) from None


def _pagination_args() -> tuple[int, int]:
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    limit = _LIST_LIMIT_DEFAULT if raw_limit is None else _int_arg(raw_limit, "limit")
    offset = 0 if raw_offset is None else _int_arg(raw_offset, "offset")
    if not 1 <= limit <= _LIST_LIMIT_MAX:
        raise service.AgentsServiceError(
            "invalid_request", f"limit 须在 1..{_LIST_LIMIT_MAX}。", 400
        )
    if offset < 0:
        raise service.AgentsServiceError("invalid_request", "offset 不能为负。", 400)
    return limit, offset


def _time_arg(name: str) -> datetime | None:
    raw = request.args.get(name)
    if raw is None:
        return None
    try:
        value = datetime.fromisoformat(raw)
    except ValueError:
        raise service.AgentsServiceError(
            "invalid_request", f"{name} 须为 ISO 8601 时间（如 2026-11-07 或 2026-11-07T08:00:00）。", 400
        ) from None
    # 无时区的入参按 UTC 解释（created_at 列一律 UTC 存储）。
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


@agents_blueprint.get("/runs")
@require_auth
def list_runs():
    """Run 列表（T-A8 桌面控制台，只读）：project/status/时间过滤＋有界分页。

    列表行不带详情/产物/工具调用（防 N+1），走既有 /runs/<id> 与
    /runs/<id>/tool-calls 按需取；人工控制台面，不进 api_catalog
    （沿 T-W6 workflow 列表与 B#9 execution-facts 同款先例）。
    """
    limit, offset = _pagination_args()
    return _data(
        service.list_runs(
            actor=g.current_user,
            project_id=request.args.get("project_id"),
            status=request.args.get("status"),
            created_from=_time_arg("created_from"),
            created_to=_time_arg("created_to"),
            limit=limit,
            offset=offset,
        )
    )


@agents_blueprint.post("/runs/<run_id>/handoff")
@require_auth
def handoff_run(run_id):
    """L3 转人工收口（E-2）：接管人落 run，挂 pending signoff 终审检查点。"""
    return _data(service.handoff_run(actor=g.current_user, run_id=run_id, payload=_payload()))


@agents_blueprint.post("/runs/<run_id>/retry")
@require_auth
def retry_run(run_id):
    """幂等重试：共享幂等键，≤2 次指数退避（V8/I-1 语义的显式入口）。"""
    data, status = service.retry_run(actor=g.current_user, run_id=run_id, payload=_payload())
    return _data(data), status


@agents_blueprint.get("/runs/<run_id>/tool-calls")
@require_auth
def list_tool_calls(run_id):
    """工具调用留痕（V3 前半）：?decision=denied 取越权明细。"""
    return _data(
        service.list_tool_calls(actor=g.current_user, run_id=run_id, decision=request.args.get("decision"))
    )


@agents_blueprint.patch("/runs/<run_id>/artifacts/<artifact_id>")
@require_auth
def set_artifact_reviewed(run_id, artifact_id):
    """T-B1 产物人工接受（can_manage；body {"reviewed": bool}）。不进 api_catalog——
    终审动作沿业务对象纪律；失败/撤回均留 agent_artifact_reviewed 事件。"""
    payload = request.get_json(silent=True)
    reviewed = payload.get("reviewed") if isinstance(payload, dict) else None
    if not isinstance(reviewed, bool):
        return error_response("invalid_request", "reviewed 必须是布尔值。", 400, None)
    return _data(
        service.set_artifact_reviewed(
            actor=g.current_user, run_id=run_id, artifact_id=artifact_id, reviewed=reviewed
        )
    )


@agents_blueprint.get("/cost")
@require_auth
def get_cost():
    """成本明细（V10/M-1）：scope=project|seat|platform。"""
    return _data(
        service.get_cost(
            actor=g.current_user,
            scope=request.args.get("scope"),
            project_id=request.args.get("project_id"),
        )
    )


@agents_blueprint.post("/<agent_id>/fallback-rehearsal")
@require_auth
def rehearse_fallback(agent_id):
    """降级链演练（V4 手动触发面，admin）：L1/L2 演练 run，零计费。"""
    return _data(service.rehearse_fallback(actor=g.current_user, agent_id=agent_id, payload=_payload()))


@agents_blueprint.post("/runs/<run_id>/recover")
@require_auth
def recover_run(run_id):
    """run 卡死恢复（d5 挂账）：发起人/管理员把卡死的 queued/running 恢复为 failed。"""
    return _data(service.recover_run(actor=g.current_user, run_id=run_id))


@agents_blueprint.get("/pilot-report")
@require_auth
def pilot_report():
    """试点报告（UM-1，admin）：30 天/20 run 状态 + 拦截率/一次通过率/单会成本等。"""
    return _data(service.get_pilot_report(actor=g.current_user))


@agents_blueprint.get("/quota")
@require_auth
def seat_quota():
    """O-3 配额快照（goal-d7，只读）：本席消耗/≤20% 提醒/超额标注/加油包入口/
    30 天重校窗口；他席 admin 传 ?user_id=。透明只读，无拦截语义（绝不断供）。"""
    return _data(service.get_seat_quota(actor=g.current_user, user_id=request.args.get("user_id")))
