"""跨域到期只读投影（B#13-D；到期语义与主动超时治理 v1 §2/§5）。

裁决落点：**服务层只读 union + admin-only 查询路由，零 DDL**。
不建 SQL view 的决定性理由：api_confirmation 的截止时刻是派生值
（``ai.api.requested.created_at + CONFIRMATION_WINDOW``），SQL view 无法
引用 Python 原语，会把窗口规则复制成第二权威；服务层直接复用
``control.api_actions`` 的同一常量与谓词（单一权威，测试可变异验证）。

只读纪律：本模块不写任何源行、不追加事件、不触发任何域转换器；
``expiry_action`` 只是符号名指针（运营反查用），绝不按名执行。

六字段逻辑视图（立项合同 §2）：``domain`` / ``object_id`` /
``deadline_at`` / ``state`` / ``due`` / ``expiry_action``。``due`` 统一按
``deadline_at <= now`` 判定（等于边界也到期）；dispatch_offer 原生转换器
``expire_stale_offers`` 沿用其严格 ``deadline < now`` 边界（立项 §4
「不替换派单专属原语」），投影在边界瞬间可能先于其收敛一拍——读数先行、
不写回，不据此宣称「已收敛」。

权限：admin-only（运营看板视角，2026-11-06 用户明确指示实施即触发条件）。
只投影元数据，不外泄确认参数 body、审批 arguments、对象存储键或客户资料。
"""
from collections import defaultdict
from datetime import UTC, datetime
from typing import Any

from flask import Blueprint, g, jsonify, request
from sqlalchemy import select

from fde_api.auth.decorators import require_auth
from fde_api.control import api_actions
from fde_api.control.api_actions import _result
from fde_api.control.models import AutomationApproval
from fde_api.dispatch.models import DeliveryPackage, DispatchOffer
from fde_api.dispatch.offer_service import offer_deadline
from fde_api.errors import error_response
from fde_api.extensions import db
from fde_api.files.models import UploadSession
from fde_api.workbench.models import OperationEvent

blueprint = Blueprint("expirations", __name__, url_prefix="/api/v1/expirations")

# 各域到期动作的符号名指针（立项合同 §2：不执行任意字符串命令）。
EXPIRY_ACTIONS: dict[str, str] = {
    "automation_approval": "fde_api.control.service._expire_approval",
    "api_confirmation": "fde_api.control.api_actions.confirmation_expired",
    "dispatch_offer": "fde_api.dispatch.offer_service.expire_stale_offers",
    "upload_session": "fde_api.files.expiration.expire_upload_session",
}

DEFAULT_LIMIT = 100
MAX_LIMIT = 500
# ai.api.requested 扫描上限（防全表；确认事件按 created_at 倒序取最近一批）
CONFIRMATION_SCAN_LIMIT = 500

# 每域投影行的内部形态：(domain, object_id, deadline_at, state)
_RawEntry = tuple[str, str, datetime, str]


def _approval_entries(session, now: datetime, limit: int) -> list[_RawEntry]:
    rows = session.scalars(
        select(AutomationApproval)
        .where(AutomationApproval.status == "pending")
        .order_by(AutomationApproval.expires_at, AutomationApproval.id)
        .limit(limit)
    )
    return [
        ("automation_approval", row.id, row.expires_at, row.status) for row in rows
    ]


def _upload_entries(session, now: datetime, limit: int) -> list[_RawEntry]:
    rows = session.scalars(
        select(UploadSession)
        .where(UploadSession.status == "uploading")
        .order_by(UploadSession.expires_at, UploadSession.id)
        .limit(limit)
    )
    return [("upload_session", row.id, row.expires_at, row.status) for row in rows]


def _offer_entries(session, now: datetime, limit: int) -> list[_RawEntry]:
    rows = session.execute(
        select(DispatchOffer, DeliveryPackage)
        .join(DeliveryPackage, DispatchOffer.package_id == DeliveryPackage.id)
        .where(DispatchOffer.status == "offered")
        .order_by(DispatchOffer.offered_at, DispatchOffer.id)
        .limit(limit)
    )
    entries: list[_RawEntry] = []
    for offer, package in rows:
        deadline = offer_deadline(offer, package)
        if deadline is None:  # 无响应窗口的 offer 无到期语义，不入投影
            continue
        entries.append(("dispatch_offer", offer.id, deadline, offer.status))
    return entries


def _confirmation_entries(session, now: datetime, limit: int) -> list[_RawEntry]:
    requested = session.scalars(
        select(OperationEvent)
        .where(
            OperationEvent.target_type == "ai_api_action",
            OperationEvent.event_type == "ai.api.requested",
        )
        .order_by(OperationEvent.created_at.desc(), OperationEvent.id.desc())
        .limit(CONFIRMATION_SCAN_LIMIT)
    )
    candidates = [row for row in requested if row.changes.get("confirmation_required")]
    if not candidates:
        return []
    related = session.scalars(
        select(OperationEvent)
        .where(
            OperationEvent.target_type == "ai_api_action",
            OperationEvent.target_id.in_([row.target_id for row in candidates]),
        )
        .order_by(OperationEvent.created_at, OperationEvent.id)
    )
    by_id: dict[str, list[OperationEvent]] = defaultdict(list)
    for row in related:
        by_id[row.target_id].append(row)
    entries: list[_RawEntry] = []
    for row in candidates:
        # 与 pending_actions 同则：已有结果（finished/cancelled/started=
        # uncertain 防重放态）的确认不再属于可到期等待集。
        if _result(by_id.get(row.target_id, [])) is not None:
            continue
        # 窗口常量取模块属性而非 from-import 绑定：与 B#13-C 保持单一权威，
        # monkeypatch CONFIRMATION_WINDOW 时投影与三路径同步位移。
        deadline = row.created_at + api_actions.CONFIRMATION_WINDOW
        entries.append(("api_confirmation", row.target_id, deadline, "awaiting_confirmation"))
    return entries


_COLLECTORS = {
    "automation_approval": _approval_entries,
    "api_confirmation": _confirmation_entries,
    "dispatch_offer": _offer_entries,
    "upload_session": _upload_entries,
}


def collect_expiration_entries(
    *,
    now: datetime | None = None,
    domain: str | None = None,
    due: bool | None = None,
    limit: int = DEFAULT_LIMIT,
) -> list[dict[str, Any]]:
    """只读 union：跨域到期投影，六字段逻辑视图（立项合同 §2）。

    每域最多取 ``limit`` 行，合并后按 (deadline_at, domain, object_id) 稳定
    排序，先做 due 过滤再截断；注入 ``now`` 供测试固定边界。
    """
    current = (now or datetime.now(UTC)).astimezone(UTC)
    session = db.session()
    try:
        collectors = _COLLECTORS.values() if domain is None else [_COLLECTORS[domain]]
        raw: list[_RawEntry] = []
        for collector in collectors:
            raw.extend(collector(session, current, limit))
        if due is not None:
            raw = [row for row in raw if (row[2] <= current) is due]
        raw.sort(key=lambda row: (row[2], row[0], row[1]))
        return [
            {
                "domain": name,
                "object_id": object_id,
                "deadline_at": deadline.astimezone(UTC).isoformat(),
                "state": state,
                "due": deadline <= current,
                "expiry_action": EXPIRY_ACTIONS[name],
            }
            for name, object_id, deadline, state in raw[:limit]
        ]
    finally:
        session.close()


@blueprint.get("")
@require_auth
def list_expirations_route():
    if g.current_user.role != "admin":
        return error_response("forbidden", "跨域到期投影仅平台管理员可读。", 403)
    args = request.args
    domain = args.get("domain")
    if domain is not None and domain not in EXPIRY_ACTIONS:
        return error_response(
            "invalid_domain",
            "domain 只接受 " + "/".join(sorted(EXPIRY_ACTIONS)) + "。",
            400,
        )
    due: bool | None = None
    due_raw = args.get("due")
    if due_raw is not None:
        normalized = due_raw.lower()
        if normalized not in {"true", "false"}:
            return error_response("invalid_request", "due 只接受 true/false。", 400)
        due = normalized == "true"
    limit = DEFAULT_LIMIT
    limit_raw = args.get("limit")
    if limit_raw is not None:
        try:
            limit = int(limit_raw)
        except ValueError:
            return error_response("invalid_request", "limit 必须是整数。", 400)
        if not 1 <= limit <= MAX_LIMIT:
            return error_response("invalid_request", f"limit 须在 1..{MAX_LIMIT}。", 400)
    items = collect_expiration_entries(domain=domain, due=due, limit=limit)
    return jsonify({"data": {"items": items, "total": len(items)}, "error": None})
