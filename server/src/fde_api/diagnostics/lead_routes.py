"""诊断域**员工侧**路由（获客诊断 T-11：线索池 ＋ 认领 ＋ 平台裁定）。

**为什么另起一个蓝图**：``fde_api.diagnostics.routes`` 是本仓第一个**公网
免注册写面**（无 JWT、令牌走请求头、部署闸默认关）。认领面是**员工侧**面
（必须有身份），把它塞进匿名蓝图会让「谁能写」的边界糊掉——所以这里单独一个
蓝图、单独一条 URL 前缀：

- 匿名面：``/api/v1/diagnostics/*``（免注册）
- 员工面：``/api/v1/diagnostics/leads/*``（**必须登录**）

**闸门先于鉴权**：诊断面未启用 ⇒ **404**（不确认面存在），再谈登录——顺序
反了就成了「没启用也告诉你这面要登录」。

**认领 ≠ 生效**（P-6）：``POST .../claims`` 只是**申请**；真正生效要走
``.../claims/<id>/accept``（**admin 角色**＝平台接受）。
"""
from __future__ import annotations

from functools import wraps
from typing import Any

from flask import Blueprint, jsonify, request

from fde_api.auth.decorators import require_auth, require_role
from fde_api.diagnostics import claim_service, service
from fde_api.errors import error_response

diagnostics_leads_blueprint = Blueprint(
    "diagnostics_leads", __name__, url_prefix="/api/v1/diagnostics/leads"
)

# 线索池分页上限（服务端强制；不给客户端无限拉的口子）
MAX_POOL_LIMIT = 200


def _gate_first(view):
    """部署闸先判（未启用 ⇒ 404），再进鉴权。"""

    @wraps(view)
    def wrapped(*args: Any, **kwargs: Any):
        service.ensure_enabled()
        return view(*args, **kwargs)

    return wrapped


def _payload() -> dict[str, Any]:
    value = request.get_json(silent=True)
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise service.DiagnosticsServiceError("invalid_request", "请求内容必须为 JSON 对象。", 400)
    return value


def _data(value: Any):
    return jsonify({"data": value, "error": None})


@diagnostics_leads_blueprint.get("")
@_gate_first
@require_auth
def list_leads_route():
    """线索池（**按区可见**：R4 只看本区域；池内不含联系方式与姓名）。"""
    kind = (request.args.get("claimant_kind") or "").strip()
    region = request.args.get("region_name") or None
    raw_limit = request.args.get("limit") or "50"
    try:
        limit = int(raw_limit)
    except (TypeError, ValueError):
        limit = 50
    limit = max(1, min(limit, MAX_POOL_LIMIT))
    items = claim_service.list_leads(
        actor=_actor(),
        claimant_kind=kind,
        region_name=region,
        limit=limit,
    )
    return _data(items)


@diagnostics_leads_blueprint.post("/<session_id>/claims")
@_gate_first
@require_auth
def create_claim_route(session_id: str):
    """发起认领申请（**不生效**——平台接受才生效）。"""
    claim = claim_service.create_claim(
        actor=_actor(),
        session_id=session_id,
        payload=_payload(),
        ip_address=request.remote_addr,
    )
    return _data(claim_service.serialize_claim(claim)), 201


@diagnostics_leads_blueprint.get("/claims")
@_gate_first
@require_auth
def list_claims_route():
    """认领单列表（**两段可见性**：admin＝全量裁定队列；非 admin＝只看自己的申请）。

    ``status`` 闭集过滤（pending/accepted/rejected/all，缺省 all）；桌面裁定面
    传 ``pending`` 拿待裁定队列。投影＝认领单 ＋ 线索摘要（**代号化**，不含
    联系方式与姓名）＋ 认领人账号名。
    """
    status = (request.args.get("status") or "all").strip()
    raw_limit = request.args.get("limit") or "50"
    try:
        limit = int(raw_limit)
    except (TypeError, ValueError):
        limit = 50
    items = claim_service.list_claims(actor=_actor(), status=status, limit=limit)
    return _data(items)


@diagnostics_leads_blueprint.get("/claims/<claim_id>")
@_gate_first
@require_auth
def get_claim_route(claim_id: str):
    """读认领单（含台账行——**代号化九字段**；admin 全量，非 admin 仅本人申请）。"""
    claim = claim_service.get_claim(actor=_actor(), claim_id=claim_id)
    return _data(claim_service.serialize_claim(claim))


# ── 渠道链接（T-15：R4 专属链接 ＝ 归因凭证；admin 专属） ────────────────


@diagnostics_leads_blueprint.post("/channel-links")
@_gate_first
@require_role("admin")
def create_channel_link_route():
    """发一条 R4 专属链接（**明文 token 只此一次**——拼进链接后交付渠道方）。"""
    from fde_api.diagnostics import channel_links

    link, token = channel_links.create_link(actor=_actor(), payload=_payload())
    return _data({**channel_links.serialize_link(link), "token": token}), 201


@diagnostics_leads_blueprint.get("/channel-links")
@_gate_first
@require_role("admin")
def list_channel_links_route():
    """渠道链接清单（**无明文 token**；带在册线索数——渠道方对账可见）。"""
    from fde_api.diagnostics import channel_links

    raw_limit = request.args.get("limit") or "100"
    try:
        limit = int(raw_limit)
    except (TypeError, ValueError):
        limit = 100
    return _data(channel_links.list_links(limit=limit))


@diagnostics_leads_blueprint.post("/channel-links/<link_id>/deactivate")
@_gate_first
@require_role("admin")
def deactivate_channel_link_route(link_id: str):
    """停用链接（软撤：历史归因不改写，新会话不再解析为 partner）。"""
    from fde_api.diagnostics import channel_links

    link = channel_links.deactivate_link(actor=_actor(), link_id=link_id)
    return _data(channel_links.serialize_link(link))


@diagnostics_leads_blueprint.post("/claims/<claim_id>/accept")
@_gate_first
@require_role("admin")
def accept_claim_route(claim_id: str):
    """平台接受认领（**此刻认领才生效**；落档位 ＋ 出台账行）。"""
    claim = claim_service.accept_claim(
        actor=_actor(),
        claim_id=claim_id,
        payload=_payload(),
    )
    return _data(claim_service.serialize_claim(claim))


@diagnostics_leads_blueprint.post("/claims/<claim_id>/reject")
@_gate_first
@require_role("admin")
def reject_claim_route(claim_id: str):
    """平台驳回认领（**不改线索状态**——线索仍可被他人认领）。"""
    claim = claim_service.reject_claim(
        actor=_actor(),
        claim_id=claim_id,
        payload=_payload(),
    )
    return _data(claim_service.serialize_claim(claim))


def _actor():
    """当前登录用户（``require_auth`` 已注入 ``g.current_user``）。"""
    from flask import g

    return g.current_user


@diagnostics_leads_blueprint.app_errorhandler(service.DiagnosticsServiceError)
def handle_service_error(error: service.DiagnosticsServiceError):
    return error_response(error.code, error.message, error.status, error.detail or None)
