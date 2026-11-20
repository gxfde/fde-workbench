"""action_execution 路由（AE1-WP1）：提交执行 + 执行详情。

POST /api/v1/action-executions             提交单步动作（幂等键必填；契约 U1
     ``ActionExecutionRequest`` 形态；默认门＝白名单 fail-closed ＋ 未接线
     派发 fail-closed——WP3 接白名单加载器与连接器适配）
POST /api/v1/action-executions/<id>/rollback   回滚（契约 U1 ``x-rollback``：
     四态诚实失败——``rolled_back|not_supported|failed|noop`` 均以 HTTP 200
     ＋ ``data.error`` 对象返回〔exceptions_note：诚实失败态不冒充成功〕；
     幂等——同 execution_id 重复调用复用既有批次，零重复补偿副作用）
GET  /api/v1/action-executions/<id>        执行详情（同租户；跨租户 404 不泄露）

错误信封沿 Workbench ``{data:null,error:{code,message,details}}``（契约
x-error-codes.http_status_note：AE 以 Workbench 侧为准）。
"""
from __future__ import annotations

from flask import Blueprint, current_app, g, jsonify, request

from fde_api.action_execution import service
from fde_api.action_execution.connectors import ConnectorWhitelist, HttpDispatch, load_whitelist
from fde_api.action_execution.errors import ActionExecutionError
from fde_api.auth.decorators import require_auth
from fde_api.auth.tokens import issue_access_token
from fde_api.errors import error_response

action_execution_blueprint = Blueprint("action_execution", __name__, url_prefix="/api/v1")

# WP3 生产装配：白名单门＝仓内快照只读加载（加载期固化，运行时不可变——
# 禁改清单第 5/7 项：缺失/损坏 fail-closed；惰性构造＝首次请求时加载并
# 缓存，快照缺失时在请求面 403 而非蓝本导入崩溃）。
# 评审 P10：快照同源缓存——门与 SSRF 预检共用同一份深拷贝快照，杜绝
# 「门缓存 vs 磁盘现读」双源 TOCTOU 与每请求重读盘。
_WHITELIST_GATE: ConnectorWhitelist | None = None
_WHITELIST_SNAPSHOT: dict | None = None


def _whitelist_snapshot() -> dict:
    global _WHITELIST_SNAPSHOT
    if _WHITELIST_SNAPSHOT is None:
        _WHITELIST_SNAPSHOT = load_whitelist()
    return _WHITELIST_SNAPSHOT


def _whitelist_gate() -> ConnectorWhitelist:
    global _WHITELIST_GATE
    if _WHITELIST_GATE is None:
        _WHITELIST_GATE = ConnectorWhitelist(_whitelist_snapshot())
    return _WHITELIST_GATE


@action_execution_blueprint.errorhandler(ActionExecutionError)
def service_error(error: ActionExecutionError):
    return error_response(error.code, error.message, error.status, error.details or None)


@action_execution_blueprint.post("/action-executions")
@require_auth
def submit_action():
    """提交单步动作执行：契约 U1 ``ActionExecutionRequest`` → ``ActionExecutionResult``。

    成功（含复放 ``replayed``）→ 201 ``{data: result, error: null}``（复放返回
    首次执行的载荷与状态码——U1 x-idempotency.same_key_same_body「HTTP 状态码
    与响应体逐字一致」读法；域内 status=replayed 语义见契约 $defs if/then）。
    """
    payload = request.get_json(silent=True)
    gate = _whitelist_gate()
    dispatch = HttpDispatch(
        whitelist=gate,
        token=issue_access_token(g.current_user, current_app.config["SETTINGS"]),
        whitelist_snapshot=_whitelist_snapshot(),
        timeout_seconds=300.0,  # 评审 P8：服务端超时上限＝契约 timeout_seconds 域上界
    )
    result = service.submit_action(actor=g.current_user, payload=payload, whitelist_gate=gate, dispatch=dispatch)
    return jsonify({"data": result, "error": None}), 201


@action_execution_blueprint.post("/action-executions/<execution_id>/rollback")
@require_auth
def rollback_execution(execution_id: str):
    """回滚（U1 ``x-rollback``）：body ``{reason?}`` → ``RollbackResult``。

    四态均 HTTP 200（诚实失败态以 ``data.error`` 对象承载，不冒充成功；
    ``not_found`` 404 仍走信封）。幂等：同 execution_id 重复调用复用既有批次。
    补偿器生产装配＝``NO_COMPENSATOR``（fail-closed → ``not_supported``）；
    真实补偿器随 WP3 连接器适配按 kind 注册。
    """
    payload = request.get_json(silent=True) or {}
    reason = payload.get("reason")
    if isinstance(reason, str) and len(reason) > 500:
        # U1 x-rollback.exceptions：reason 超长 → 422 validation_failed（评审 P17，
        # 不让超长串直达 varchar(500) 列炸 DataError）
        raise ActionExecutionError("validation_failed", "回滚原因超长（≤500 字符）。")
    result = service.rollback_action(
        actor=g.current_user, execution_id=execution_id, reason=reason if isinstance(reason, str) else None
    )
    return jsonify({"data": result, "error": None}), 200


@action_execution_blueprint.get("/action-executions/<execution_id>")
@require_auth
def get_execution(execution_id: str):
    payload = service.get_execution(actor=g.current_user, execution_id=execution_id)
    return jsonify({"data": payload, "error": None}), 200
