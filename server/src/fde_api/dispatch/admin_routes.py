"""Admin 规则版本显式管理面（CR-027 修复轮）：发布 + 激活两个显式动作。

背景（CR-027）：`dispatch/rules.py` 的 `create_rule_version`（发布）与
`activate_due_versions`（激活）此前**只有测试引用、零生产入口**——规则版本
永远停在 draft/published，`active_rule_version` 恒 None，于是撮合路径
`match_package` 恒 422 `rule_version_required`（§11.1 降级态变永久态）。
用户 2026-11-05 拍板：**显式管理动作**——激活节奏由人控制，与「名单≠开闸」
裁决一致（撮合开闸成为显式人工决定；不做请求路径惰性触发、不做 scheduler
自动激活，自动化节奏不在本轮范围）。

设计纪律：

- **公示窗不绕过**：发布端仍强制 `effective_at ≥ published_at + 30 天`（§6.2，
  `create_rule_version` 内建校验）；激活端只激活**已到生效日**的 published
  版本——人工也加速不了公示期。
- **admin 门**：service 层 role 判（`ROLE_ADMIN`），非 admin 403（平台治理面，
  与「规则版本只能由平台方发布」既有口径一致）。
- **留痕**：发布事件 `dispatch_rule_published`（`create_rule_version` 内建），
  激活事件 `dispatch_rule_activated`（target=admin 用户，changes 只落元数据：
  版本号/激活数/激活时刻，E7 纪律——审计只落元数据不落规则正文）。
- **不进 api_catalog**：平台治理面，AI 不可调用（本体治理/证据登记同款边界）。
- 零迁移零桌面改动（业务路由 +2）。
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from flask import Blueprint, g, jsonify, request

from fde_api.auth.decorators import require_auth
from fde_api.auth.models import ROLE_ADMIN, User
from fde_api.dispatch.errors import DispatchServiceError
from fde_api.dispatch.rules import (
    activate_due_versions,
    active_rule_version,
    create_rule_version,
    default_rule_snapshot,
)
from fde_api.extensions import db
from fde_api.workbench.models import OperationEvent

admin_dispatch_blueprint = Blueprint(
    "admin_dispatch", __name__, url_prefix="/api/v1/admin/dispatch"
)


def _error(code: str, message: str, status: int = 400) -> DispatchServiceError:
    return DispatchServiceError(code, message, status)


@admin_dispatch_blueprint.errorhandler(DispatchServiceError)
def _handle_service_error(error: DispatchServiceError):
    return (
        jsonify(
            {
                "data": None,
                "error": {"code": error.code, "message": error.message, "details": None},
            }
        ),
        error.status,
    )


def _require_admin(actor: User) -> None:
    if actor.role != ROLE_ADMIN:
        raise _error("rule_admin_required", "规则版本管理仅系统运维员可用。", 403)


def _parse_effective_at(raw: object) -> datetime:
    if not isinstance(raw, str) or not raw.strip():
        raise _error("invalid_request", "effective_at 必填（ISO 8601 时间）。")
    text = raw.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        raise _error("invalid_request", "effective_at 不是合法 ISO 8601 时间。") from None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def publish_rule_version(*, actor: User, version_no: object, effective_at: object,
                         rule_snapshot: object) -> dict[str, Any]:
    """发布新规则版本（admin）：公示窗 ≥30 天由服务层强制；快照缺省取当前
    默认规则投影（发布「当前口径」而非手抄正文——改正文走显式传快照）。"""
    _require_admin(actor)
    if type(version_no) is not int or version_no < 1:
        raise _error("invalid_request", "version_no 必须是 ≥1 整数。")
    effective = _parse_effective_at(effective_at)
    if rule_snapshot is None:
        snapshot = default_rule_snapshot()
    elif isinstance(rule_snapshot, dict):
        snapshot = rule_snapshot
    else:
        raise _error("invalid_request", "rule_snapshot 必须是对象。")
    with db.session() as session, session.begin():
        row = create_rule_version(
            session,
            actor=actor,
            version_no=version_no,
            rule_snapshot=snapshot,
            effective_at=effective,
        )
        return {
            "version_no": row.version_no,
            "status": row.status,
            "effective_at": row.effective_at.isoformat() if row.effective_at else None,
            "published_at": row.published_at.isoformat() if row.published_at else None,
        }


def activate_rule_versions(*, actor: User) -> dict[str, Any]:
    """激活到点版本（admin，幂等）：published 且 effective_at 已到 → active，
    原 active 版本转 retired；无到期版本则零变更（activated=0）。"""
    _require_admin(actor)
    with db.session() as session, session.begin():
        activated = activate_due_versions(session)
        current = active_rule_version(session)
        if activated:
            session.add(
                OperationEvent(
                    actor_user_id=actor.id,
                    project_id=None,
                    target_type="user",
                    target_id=actor.id,
                    event_type="dispatch_rule_activated",
                    changes={
                        "activated": activated,
                        "active_version_no": current.version_no if current else None,
                    },
                )
            )
        return {
            "activated": activated,
            "active_version_no": current.version_no if current else None,
            "active_effective_at": (
                current.effective_at.isoformat()
                if current is not None and current.effective_at
                else None
            ),
        }


@admin_dispatch_blueprint.post("/rules/versions")
@require_auth
def publish_rule_version_route():
    """发布规则版本（admin）。公示窗 ≥30 天不绕过。"""
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        payload = {}
    data = publish_rule_version(
        actor=g.current_user,
        version_no=payload.get("version_no"),
        effective_at=payload.get("effective_at"),
        rule_snapshot=payload.get("rule_snapshot"),
    )
    return jsonify({"data": data, "error": None})


@admin_dispatch_blueprint.post("/rules/activate")
@require_auth
def activate_rule_versions_route():
    """激活到点规则版本（admin，幂等；无到期版本零变更）。"""
    data = activate_rule_versions(actor=g.current_user)
    return jsonify({"data": data, "error": None})
