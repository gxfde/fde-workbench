"""AF1-WP4：最小工程台路由（独立工程入口，B 版；docs/ai-fde/13 §5-§7）。

- ``POST /api/v1/eng/session``：JWT 会话签发两段式 token（project_operator 起；
  desktop「工程台」一键出链的签发入口）。
- ``GET /eng/console``：自包含 HTML 面（零外链；fragment 承载交接令牌；
  CSP + no-store）。
- ``GET /api/v1/eng/overview`` / ``GET /api/v1/eng/runs/<id>``：只读投影
  （Bearer 工程 token；**白名单逐字段构造，默认拒绝未知字段**——Vex 席纪律
  直移，载荷含 evidence_quote 属工程作业面授权出投影，仅随租户钉定查询）。
- 写代理三钮（cancel/handoff/decision）：**写语义零新增**（N3c 先例）——
  内部调用与既有路由完全相同的 service 函数（``agents.cancellation.cancel_run``
  / ``agents.service.handoff_run`` / task-center ``decide_automation_approval``），
  服务端能力闸与审计面同源；403/409 原样透传不吞。只接受会话令牌（交接令牌
  必须先消费换会话）。

红线：零 UI-only 权限（每路由服务端闸）；不碰 TrustBoard 任何面；凭据零明文
落库（eng_token_marks 只存 jti 派生 key）。
"""
from __future__ import annotations

from datetime import UTC, datetime
from functools import wraps
from typing import TYPE_CHECKING, Any, Callable

from flask import Blueprint, Response, after_this_request, current_app, g, jsonify, request
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from fde_api.auth.decorators import require_auth
from fde_api.auth.models import User
from fde_api.control import eng_console
from fde_api.control.eng_console_page import CONSOLE_HTML
from fde_api.control.models import AutomationApproval, EngTokenMark
from fde_api.control.service import ControlServiceError, decide_automation_approval
from fde_api.extensions import db
from fde_api.projects.permissions import visible_project_filter
from fde_api.workbench.models import Project

if TYPE_CHECKING:
    from fde_api.agents.models import AgentRun, AgentToolCall
    from fde_api.agents.service import AgentsServiceError

# agents 侧 import 一律**函数内惰性**（仓库惯例，app.py 蓝图注册表导语）：
# 本蓝图若顶层引 agents.* 会新增包级顶层导入环 ('agents', 'control')
# （test_architecture_purity 冻结闸红——payload_audit 已被 agents 顶层引用）。
eng_blueprint = Blueprint("eng_console", __name__)

# 工程台可用档（role 闭集=auth models CheckConstraint；viewer 档不入——工程台
# 是作业面，观察面继续由 TrustBoard/AgentsConsole 承载）。
_ENG_ROLES = frozenset({"admin", "project_lead", "fde_engineer"})

_ENG_CSP = (
    "default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; "
    "img-src 'self'; connect-src 'self'; base-uri 'none'; frame-ancestors 'none'"
)

# overview 单列表拉取上限（诚实截断：到量即置 *_truncated 标记——
# 同仓 list_runs limit+1 惯例的对齐形态）
_ENG_OVERVIEW_LIMIT = 50


def _settings():
    return current_app.config["SETTINGS"]


def _eng_secret() -> str:
    secret = (_settings().workbench_eng_signing_key or "").strip()
    if not secret:
        raise ControlServiceError("eng_disabled", "工程台未启用：未配置独立签名密钥域。", 403)
    return secret


def _marks_repo() -> Any:
    """eng_token_marks 的 SQLAlchemy 访问面（eng_console.MarksRepo 协议）。"""
    session = db.session()

    class _Repo:
        def get(self, key: str) -> dict[str, Any] | None:
            row = session.get(EngTokenMark, key)
            return {"kind": row.kind, "client_id": row.client_id} if row else None

        def put(self, key: str, kind: str, client_id: str | None = None) -> None:
            existing = session.get(EngTokenMark, key)
            if existing is None:
                session.add(EngTokenMark(id=key, kind=kind, client_id=client_id))
                try:
                    session.commit()
                except IntegrityError:
                    # 并发首消费（两 worker 同键）：后提交者按既有行结算——
                    # 同客户端放行 / 异客户端由调用方 403（评审 edge #4）
                    session.rollback()
            else:
                existing.client_id = client_id or existing.client_id
                session.commit()

    return _Repo()


def _eng_error(error: ControlServiceError | AgentsServiceError):
    """服务错误原样透传（403/409 族不吞不改写——既有路由同纪律）。"""
    return jsonify({"data": None, "error": {"code": error.code, "message": error.message}}), error.status


# --- require_eng：Bearer 工程 token → 实时用户上下文 ------------------------


def require_eng(*, write: bool = False) -> Callable:
    """Bearer 工程 token 鉴权：验签/过期/吊销 + 交接令牌消费 + 实时用户校验。

    交接令牌首次访问 overview/runs 面即消费（响应头 ``X-Eng-Session`` 回会话
    令牌，同客户端重试放行）；**写代理面只接受会话令牌**（交接令牌必须先换
    会话——短窗口凭据不落写路径）。
    """

    def decorator(view: Callable):
        @wraps(view)
        def wrapper(*args: Any, **kwargs: Any):
            try:
                secret = _eng_secret()
            except ControlServiceError as error:
                return _eng_error(error)
            auth = request.headers.get("Authorization", "")
            token = auth[7:] if auth.startswith("Bearer ") else ""
            if not token:
                return jsonify({"data": None, "error": {
                    "code": "eng_missing_token",
                    "message": "缺少工程台访问凭证，请从 Workbench 重新出链。",
                }}), 403
            now = datetime.now(UTC)
            marks = _marks_repo()
            try:
                claims = eng_console.parse_eng_token(token, secret, now=now, marks=marks)
                session_token: str | None = None
                if claims.get("kind") == "eng-handover":
                    if write:
                        return jsonify({"data": None, "error": {
                            "code": "write_requires_session",
                            "message": "请先在页面完成出链验证后再执行操作。",
                        }}), 403
                    raw_client = request.headers.get("X-Eng-Client", "").strip()
                    if not raw_client:
                        # 页面 JS 恒带此头；缺头＝非页面客户端（curl 直打等）——
                        # 一次性消费的客户端绑定对其必须拒绝而非归并 unknown-client
                        raise eng_console.EngConsoleError(
                            "eng_client_missing", "缺少客户端标识，请从 Workbench 重新出链。"
                        )
                    client_id = raw_client[:64]
                    session_token = eng_console.consume_handover(
                        secret, claims, marks, client_id=client_id, now=now
                    )
                    claims = eng_console.parse_eng_token(session_token, secret, now=now, marks=marks)
                elif claims.get("kind") != "eng-session":
                    raise eng_console.EngConsoleError(
                        "malformed", "工程台访问凭证无效，请向交付团队索取新的访问链接。"
                    )
                user = db.session().get(User, str(claims.get("uid") or ""))
                if user is None or not user.is_active:
                    raise eng_console.EngConsoleError(
                        "revoked", "工程台授权已被回收，请向交付团队索取新的访问链接。"
                    )
                if str(user.role) not in _ENG_ROLES:
                    raise eng_console.EngConsoleError(
                        "forbidden", "当前账号不在工程台可用档位（project_operator 起）。"
                    )
            except eng_console.EngConsoleError as error:
                return jsonify({"data": None, "error": {
                    "code": error.code, "message": error.message}}), error.status
            g.eng_user = user
            g.eng_claims = claims
            if session_token is not None:
                @after_this_request
                def _issue_session(response: Response) -> Response:
                    response.headers[eng_console.SESSION_HEADER] = session_token
                    return response
            return view(*args, **kwargs)

        return wrapper

    return decorator


# --- 签发面（JWT；desktop 一键出链入口） ------------------------------------


@eng_blueprint.post("/api/v1/eng/session")
@require_auth
def create_eng_session():
    """签发两段式工程台 token（project_operator 起；密钥域空 = 403 fail-closed）。"""
    try:
        secret = _eng_secret()
    except ControlServiceError as error:
        return _eng_error(error)
    user = g.current_user
    if str(user.role) not in _ENG_ROLES:
        return jsonify({"data": None, "error": {
            "code": "forbidden", "message": "当前账号不在工程台可用档位（project_operator 起）。"}}), 403
    out = eng_console.mint_eng_tokens(
        secret, user_id=user.id, org_id=user.org_id, level=str(user.role),
        now=datetime.now(UTC),
    )
    return jsonify({
        "data": {
            "token": out["token"],
            "handover_token": out["handover_token"],
            "delivery_path": out["delivery_path"],
            "expires_in": eng_console.ENG_SESSION_TTL,
        },
        "error": None,
    })


@eng_blueprint.post("/api/v1/eng/logout")
@require_eng()
def eng_logout():
    """吊销当前会话（出链页「登出」；会话与派生交接链接同时失效）。

    只吊销 Bearer token 自带的 jti——不存在按他人 jti 吊销的越权面。
    """
    from fde_api.agents.service import AgentsServiceError as _AgentsError  # noqa: F401

    secret = _eng_secret()
    claims = g.eng_claims
    eng_console.revoke_eng_session(
        secret, _marks_repo(), org_id=claims.get("org"), session_jti=str(claims.get("jti") or "")
    )
    return jsonify({"data": {"revoked": True}, "error": None})


# --- 静态面（自包含 HTML） --------------------------------------------------


@eng_blueprint.get("/eng/console")
def eng_console_page():
    try:
        _eng_secret()
    except ControlServiceError:
        return jsonify({"data": None, "error": {
            "code": "eng_disabled", "message": "工程台未启用。"}}), 403
    response = Response(CONSOLE_HTML, mimetype="text/html")
    response.headers["Content-Security-Policy"] = _ENG_CSP
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    return response


# --- 只读投影（白名单逐字段） ------------------------------------------------


def _eng_run_row(row: AgentRun, project_name: str | None) -> dict[str, Any]:
    """run 列表白名单行（逐字段构造；默认拒绝未知字段——新列自动不外泄）。"""
    return {
        "id": row.id,
        "status": row.status,
        "agent_id": row.agent_id,
        "project_id": row.project_id,
        "project_name": project_name,
        "capability_used": row.capability_used,
        "token_cost": row.token_cost,
        "duration_ms": row.duration_ms,
        "degraded": row.degraded,
        "degraded_reason": row.degraded_reason,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def _eng_run_detail_row(session, run, *, project_name: str | None) -> dict[str, Any]:
    """run 详情**工程口径白名单行**（逐字段构造——滤幂等键/成本归属等内部
    计费链字段；agent/发起人/项目以显示名出投影；新列自动不外泄）。"""
    from fde_api.agents.models import AgentArtifact, AgentRegistry

    agent = session.get(AgentRegistry, run.agent_id)
    initiator = session.get(User, run.initiated_by_user_id) if run.initiated_by_user_id else None
    return {
        "id": run.id,
        "project_id": run.project_id,
        "project_name": project_name,
        "agent_id": run.agent_id,
        "agent": {"name": agent.name, "kind": agent.kind} if agent else None,
        "status": run.status,
        "capability_used": run.capability_used,
        "initiated_by_user_id": run.initiated_by_user_id,
        "initiated_by": initiator.display_name if initiator else None,
        "context_ref": run.context_ref,
        "token_cost": run.token_cost,
        "duration_ms": run.duration_ms,
        "exit_code": run.exit_code,
        "degraded": run.degraded,
        "degraded_reason": run.degraded_reason,
        "fallback_level": run.fallback_level,
        "handoff_user_id": run.handoff_user_id,
        "difficulty": run.difficulty,
        "execution_provider": run.execution_provider,
        "host_claimed_at": run.host_claimed_at.isoformat() if run.host_claimed_at else None,
        "host_receipt_at": run.host_receipt_at.isoformat() if run.host_receipt_at else None,
        "created_at": run.created_at.isoformat() if run.created_at else None,
        "updated_at": run.updated_at.isoformat() if run.updated_at else None,
        "artifacts": [
            {
                "id": artifact.id,
                "kind": artifact.kind,
                "storage_ref": artifact.storage_ref,
                "sha256": artifact.sha256,
                "reviewed": artifact.reviewed,
                "linked_solution_id": artifact.linked_solution_id,
            }
            for artifact in session.scalars(
                select(AgentArtifact).where(AgentArtifact.run_id == run.id)
                .order_by(AgentArtifact.created_at)
            )
        ],
    }


def _eng_tool_call_row(row: AgentToolCall) -> dict[str, Any]:
    """工具调用白名单行（AF1-WP4 N1：含载荷——工程台 Diff/校验错误数据源）。"""
    return {
        "id": row.id,
        "tool_name": row.tool_name,
        "decision": row.decision,
        "capability": row.capability,
        "reason": row.reason,
        "duration_ms": row.duration_ms,
        "request_json": row.request_json,
        "response_json": row.response_json,
        "payload_truncated": row.payload_truncated,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def _eng_approval_row(row: AutomationApproval) -> dict[str, Any]:
    """待审白名单行（工程口径；arguments/指纹等内部明细不出投影）。"""
    return {
        "id": row.id,
        "status": row.status,
        "task_name": row.tool_name,
        "capability": row.capability,
        "project_id": row.project_id,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


@eng_blueprint.get("/api/v1/eng/overview")
@require_eng()
def eng_overview():
    """一屏首拉：用户/组织 + 可见 run 列表 + 待审停点（全部白名单投影）。"""
    from fde_api.agents.models import AgentRun

    user = g.eng_user
    session = db.session()
    runs = (
        session.scalars(
            select(AgentRun)
            .join(Project, AgentRun.project_id == Project.id)
            .where(visible_project_filter(user))
            .order_by(AgentRun.created_at.desc(), AgentRun.id)
            .limit(_ENG_OVERVIEW_LIMIT + 1)
        )
        .unique()
        .all()
    )
    runs_truncated_over = len(runs) > _ENG_OVERVIEW_LIMIT
    runs = runs[:_ENG_OVERVIEW_LIMIT]
    approvals = (
        session.scalars(
            select(AutomationApproval)
            .join(Project, AutomationApproval.project_id == Project.id)
            .where(visible_project_filter(user), AutomationApproval.status == "pending")
            .order_by(AutomationApproval.created_at.desc(), AutomationApproval.id)
            .limit(_ENG_OVERVIEW_LIMIT + 1)
        )
        .unique()
        .all()
    )
    approvals_truncated_over = len(approvals) > _ENG_OVERVIEW_LIMIT
    approvals = approvals[:_ENG_OVERVIEW_LIMIT]
    org_name = None
    if user.org_id:
        from fde_api.orgs.models import Org

        org_row = session.get(Org, user.org_id)
        org_name = org_row.name if org_row is not None else None
    project_ids = {row.project_id for row in runs}
    project_names = {
        row.id: row.name
        for row in session.scalars(select(Project).where(Project.id.in_(project_ids or {""})))
    }
    return jsonify({"data": {
        "user": {"id": user.id, "display_name": user.display_name, "role": user.role},
        "org_name": org_name,
        "runs": [_eng_run_row(row, project_names.get(row.project_id)) for row in runs],
        "runs_truncated": runs_truncated_over,
        "approvals": [_eng_approval_row(row) for row in approvals],
        "approvals_truncated": approvals_truncated_over,
    }, "error": None})


@eng_blueprint.get("/api/v1/eng/runs/<run_id>")
@require_eng()
def eng_run_detail(run_id: str):
    """run 详情 + 工具调用载荷（时间线数据源）。

    访问闸与既有 get_run_detail 同源（``_require_run_access``：未知 404 /
    跨租户 403 ``project_forbidden``——与桌面 AgentsConsole 同语义，跨租户
    404 同形化归 agents 域统一处置，工程台不自造第二套语义）；投影为工程
    口径白名单行（整包透传会使 desktop 未来新列自动流入本面）。"""
    from fde_api.agents import service as agents_service
    from fde_api.agents.models import AgentRun, AgentToolCall
    from fde_api.agents.service import AgentsServiceError as _AgentsError

    try:
        agents_service.get_run_detail(actor=g.eng_user, run_id=run_id)
    except (ControlServiceError, _AgentsError) as error:
        return _eng_error(error)
    session = db.session()
    run = session.scalars(
        select(AgentRun)
        .join(Project, AgentRun.project_id == Project.id)
        .where(AgentRun.id == run_id, visible_project_filter(g.eng_user))
    ).first()
    if run is None:
        return jsonify({"data": None, "error": {
            "code": "agent_run_not_found", "message": "运行不存在或不在可见范围。"}}), 404
    project_row = session.get(Project, run.project_id)
    calls = session.scalars(
        select(AgentToolCall)
        .join(AgentRun, AgentToolCall.run_id == AgentRun.id)
        .join(Project, AgentRun.project_id == Project.id)
        .where(AgentToolCall.run_id == run_id, visible_project_filter(g.eng_user))
        .order_by(AgentToolCall.created_at, AgentToolCall.id)
    ).all()
    return jsonify({"data": {
        "run": _eng_run_detail_row(session, run, project_name=project_row.name if project_row else None),
        "tool_calls": [_eng_tool_call_row(row) for row in calls],
    }, "error": None})


# --- 写代理三钮（写语义零新增；只接受会话令牌） ------------------------------


@eng_blueprint.post("/api/v1/eng/runs/<run_id>/cancel")
@require_eng(write=True)
def eng_cancel_run(run_id: str):
    """取消：与既有 POST /agents/runs/<id>/cancel 同一 service 语义真身
    （agents.cancellation.cancel_run——幂等/409 族/发起人 OR can_manage 同源）。"""
    from fde_api.agents.cancellation import cancel_run
    from fde_api.agents.service import AgentsServiceError as _AgentsError

    try:
        data = cancel_run(actor=g.eng_user, run_id=run_id)
    except (ControlServiceError, _AgentsError) as error:
        return _eng_error(error)
    return jsonify({"data": data, "error": None})


@eng_blueprint.post("/api/v1/eng/runs/<run_id>/handoff")
@require_eng(write=True)
def eng_handoff_run(run_id: str):
    """转人工：与既有 POST /agents/runs/<id>/handoff 同一 service 语义真身
    （payload 闭集 {solution_id} 由既有 service 校验，越界字段原样被拒）。"""
    from fde_api.agents import service as agents_service
    from fde_api.agents.service import AgentsServiceError as _AgentsError

    payload = request.get_json(silent=True) or {}
    if not isinstance(payload, dict):
        payload = {}
    try:
        data = agents_service.handoff_run(actor=g.eng_user, run_id=run_id, payload=payload)
    except (ControlServiceError, _AgentsError) as error:
        return _eng_error(error)
    return jsonify({"data": data, "error": None})


@eng_blueprint.post("/api/v1/eng/approvals/<approval_id>/decision")
@require_eng(write=True)
def eng_approval_decision(approval_id: str):
    """审批决定：与既有 task-center 同一 service 语义真身（密码确认/审计同源；
    密码只在内存比对，零日志零落库）。"""
    payload = request.get_json(silent=True) or {}
    if not isinstance(payload, dict):
        payload = {}
    try:
        data = decide_automation_approval(
            user=g.eng_user,
            approval_id=approval_id,
            decision_value=str(payload.get("decision", "")),
            password=str(payload.get("password", "")),
            reason=str(payload.get("reason", "")),
        )
    except ControlServiceError as error:
        return _eng_error(error)
    return jsonify({"data": data, "error": None})
