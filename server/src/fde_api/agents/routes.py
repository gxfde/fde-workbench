"""agents 蓝图：11 路由（goal-d4 七路由 + goal-d6 演练/恢复/试点报告 + goal-d7 配额）。

api_catalog 只收其中只读 GET（注册表/溯源/工具留痕/成本/配额）；POST run /
handoff / retry / rehearse / recover 属人工授权写路径——AI 不得代发起、
代接管、代重试（沿门禁三路由不进目录的同一红线）。
"""

from datetime import datetime, timezone

from flask import Blueprint, g, jsonify, request

from fde_api.agents import cancellation, service
from fde_api.auth.decorators import require_auth
from fde_api.errors import error_response
from fde_api.extensions import db

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


@agents_blueprint.post("/runs/<run_id>/cancel")
@require_auth
def cancel_run(run_id):
    """取消 run（AF1-WP1 定参①，09 §1）：幂等 + 诚实终态。

    queued 直接取消（启动守卫拦未开始的执行）；running 沙箱经监听段
    cancel check 收口（kill 恒定发生，CR-015）；host_running 显式 409。
    语义真身与启动守卫见 agents/cancellation.py（service 热点钉边界）。
    """
    return _data(cancellation.cancel_run(actor=g.current_user, run_id=run_id))


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


@agents_blueprint.get("/runs/<run_id>/artifacts/<artifact_id>/content")
@require_auth
def get_artifact_content(run_id, artifact_id):
    """T-A10 产物内容读取（can_manage；N3c 轮合批交付）：桌面就地预览/下载。

    逐字节 sha256 对库行指纹自证（不符 503 fail-closed）；原件不在服务端
    可见工作区（容器部署态常态）⇒ 显式 404 不静默；只读零写零事件——
    预览不新增外发通道。不进 api_catalog（复核面沿业务对象纪律）。
    """
    from fde_api.agents.artifact_content import ArtifactContentError, read_artifact_content

    session = db.session()
    try:
        return _data(
            read_artifact_content(
                session, actor=g.current_user, run_id=run_id, artifact_id=artifact_id
            )
        )
    except ArtifactContentError as error:
        return error_response(error.code, error.message, error.status, None)
    finally:
        session.close()


@agents_blueprint.post("/runs/<run_id>/artifacts/<artifact_id>/adopt-solution")
@require_auth
def adopt_artifact_as_solution(run_id, artifact_id):
    """产物采纳为方案（人工动作；can_manage；采纳流反向入口）。

    族内先例同尺：AI 只产候选、**人工点确认**才进方案台账（translator_draft
    adopt / ontology candidate confirm / workflow draft publish 同族）——本
    路由是人工显式动作，不存在自动采纳路径。幂等：同产物重复采纳返回既有
    方案。不进 api_catalog（终审动作沿业务对象纪律）。
    """
    from fde_api.agents.artifact_adoption import ArtifactAdoptionError, adopt_artifact_as_solution

    try:
        return _data(
            adopt_artifact_as_solution(
                actor=g.current_user,
                run_id=run_id,
                artifact_id=artifact_id,
                payload=_payload(),
            )
        )
    except ArtifactAdoptionError as error:
        return error_response(error.code, error.message, error.status, error.detail)


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


# ---------------------------------------------------------------------------
# E11 智能体凭据管理面（2026-11-13）。此前 `agent_credentials` 表**无任何
# HTTP 路由**（唯一创建点是本地脚本）⇒ 种子 agent 的 credential_ref 全为 null
# ⇒ run 发起 409 credential_missing。写入只存 Fernet 密文、绝不回显；平台管理面
# 只认平台身份 ＋ system_operator AI 档（M3b 批次 ①-a 单一判定）。
# 不进 api_catalog（凭据面同「人工授权写路径」不进目录的红线）。
# ---------------------------------------------------------------------------


@agents_blueprint.get("/credentials")
@require_auth
def list_credentials():
    """凭据清单（只出名字与「是否已配置」，绝不出密文/明文）。"""
    from fde_api.agents import credentials as credentials_service

    try:
        return _data(credentials_service.list_credentials(actor=g.current_user))
    except credentials_service.CredentialsError as error:
        return credentials_service.error_response_for(error)


@agents_blueprint.post("/credentials")
@require_auth
def save_credential():
    """写入/覆盖一条凭据（同名即更新）。明文只在请求内存中出现，落库是密文。"""
    from fde_api.agents import credentials as credentials_service

    try:
        return _data(
            credentials_service.save_credential(actor=g.current_user, payload=_payload())
        )
    except credentials_service.CredentialsError as error:
        return credentials_service.error_response_for(error)


@agents_blueprint.delete("/credentials/<name>")
@require_auth
def delete_credential(name):
    """删除一条凭据。"""
    from fde_api.agents import credentials as credentials_service

    try:
        return _data(credentials_service.delete_credential(actor=g.current_user, name=name))
    except credentials_service.CredentialsError as error:
        return credentials_service.error_response_for(error)


# ---------------------------------------------------------------------------
# P2′① 宿主轮询领取面（§11.3；2026-11-08）。鉴权 = FDE_AGENT_HOST_POLL_TOKEN
# （X-Host-Poll-Token 头；宿主代理非用户，不走 JWT）。三条写/读面均 fail-closed
# （开关/令牌未配置 403）。不进 api_catalog（宿主机器面，与 bridge 同族）。
# ---------------------------------------------------------------------------


def _host_token() -> str:
    token = request.headers.get("X-Host-Poll-Token", "")
    if not token.strip():
        from flask import jsonify

        resp = jsonify({"data": None, "error": {"code": "host_poll_token_missing", "message": "缺少 X-Host-Poll-Token 头。"}})
        resp.status_code = 403
        return ""
    return token


def _host_error_response(error):
    from flask import jsonify

    resp = jsonify({"data": None, "error": {"code": error.code, "message": error.message, "details": error.detail}})
    resp.status_code = error.status
    return resp


@agents_blueprint.get("/host/status")
def host_status():
    """轮询探测：待领取数 + 失联标记顺带触发（约束 3：宿主在，标记就在）。"""
    token = _host_token()
    if not token:
        return _host_error_response(service.AgentsServiceError("host_poll_token_missing", "缺少令牌。", 403))
    try:
        return _data(service.host_poll_status(presented_token=token))
    except service.AgentsServiceError as error:
        return _host_error_response(error)


@agents_blueprint.post("/host/claim")
def host_claim():
    """领取一个待执行 run（幂等；token 一致的重复领取返回同一载荷）。"""
    token = _host_token()
    if not token:
        return _host_error_response(service.AgentsServiceError("host_poll_token_missing", "缺少令牌。", 403))
    body = _payload()
    run_id = body.get("run_id") if isinstance(body, dict) else None
    if run_id is not None and not isinstance(run_id, str):
        raise service.AgentsServiceError("invalid_request", "run_id 须为字符串。", 400)
    try:
        return _data(service.claim_host_run(presented_token=token, run_id=run_id))
    except service.AgentsServiceError as error:
        return _host_error_response(error)


@agents_blueprint.post("/host/runs/<run_id>/receipt")
def host_receipt(run_id):
    """回执落账（幂等；终态语义与容器对齐；H4 不自动重试）。"""
    token = _host_token()
    if not token:
        return _host_error_response(service.AgentsServiceError("host_poll_token_missing", "缺少令牌。", 403))
    try:
        return _data(service.submit_host_receipt(presented_token=token, run_id=run_id, payload=_payload()))
    except service.AgentsServiceError as error:
        return _host_error_response(error)


@agents_blueprint.get("/host/runs/<run_id>/context")
def host_run_context(run_id):
    """任务书面料读取（goal-sprint r3：宿主代理领取后 spawn 前取三件渲染产物）。"""
    from fde_api.agents.host_context import fetch_host_run_context

    token = _host_token()
    if not token:
        return _host_error_response(service.AgentsServiceError("host_poll_token_missing", "缺少令牌。", 403))
    try:
        return _data(fetch_host_run_context(presented_token=token, run_id=run_id))
    except service.AgentsServiceError as error:
        return _host_error_response(error)
