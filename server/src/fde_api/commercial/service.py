"""商业化 G1 服务层：权益写原语（admin + 密码确认 + 审计事件）与读序列化。

高风险写纪律（ADR-002 §2.5，任务书 §5 约束）：权益变更属高风险写，默认需
人工确认——本层全部写原语要求 admin 角色 + 当前账号密码确认（复用
``auth.passwords.verify_password`` 单点，与方案归档/扩展治理同款）；每次
生效变更落一条 ``operation_events`` 事件（Actor/对象/前后状态/时间/来源/
请求 ID——请求 ID 落 changes.request_id，事件表无该列、不为此扩 schema）。

**四类权益互不推导**（ADR-002）：每个写原语只触碰自己那一类的列组；
席位激活是唯一跨域同步点（``fde_profiles.status`` pending→active 单向
升级，ADR-002 §2.3），同步事实记入同一事件的 changes。
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from fde_api.auth.models import ROLE_ADMIN, User
from fde_api.auth.passwords import verify_password
from fde_api.commercial.ladder import external_ladder_code
from fde_api.commercial.models import (
    CERTIFICATION_STATUSES,
    COMMERCIAL_ROLES,
    DELIVERY_ELIGIBILITIES,
    SEAT_SOURCES,
    SEAT_STATUSES,
    TRAINING_ITEM_TYPES,
    CommercialEntitlement,
    TrainingEntitlement,
)  # noqa: F401 —— CERTIFICATION_STATUSES/SEAT_STATUSES 为 __all__ 再导出
from fde_api.dispatch.models import FdeProfile
from fde_api.projects.events import record_event


class CommercialServiceError(Exception):
    """商业化权益服务错误（code/message/status 三元，路由层统一转 JSON）。"""

    def __init__(self, code: str, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


def _error(code: str, message: str, status: int = 400) -> CommercialServiceError:
    return CommercialServiceError(code, message, status)


def _require_admin(actor: User) -> None:
    if actor.role != ROLE_ADMIN:
        raise _error("commercial_admin_required", "商业权益管理仅系统运维员可用。", 403)


def _confirm_password(session: Session, actor: User, password: object) -> None:
    """单次显式授权：admin 写原语须携带当前账号密码（高风险写默认人工确认）。"""
    if not isinstance(password, str) or not password:
        raise _error("invalid_request", "confirm_password 必填（高风险写人工确认）。")
    current = session.get(User, actor.id)
    if current is None or not verify_password(current.password_hash, password):
        raise _error("invalid_password", "当前账号密码不正确。", 403)


def _require_user(session: Session, user_id: object) -> User:
    if not isinstance(user_id, str) or not user_id:
        raise _error("invalid_request", "user_id 必填。")
    user = session.get(User, user_id)
    if user is None:
        raise _error("user_not_found", "用户不存在。", 404)
    return user


def _parsemoment(value: object, field: str) -> datetime | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise _error("invalid_request", f"{field} 不是合法 ISO 8601 时间。")
    text = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        raise _error("invalid_request", f"{field} 不是合法 ISO 8601 时间。") from None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def ensure_entitlement(session: Session, user_id: str) -> CommercialEntitlement:
    """懒初始化一人一份权益行（读面与写面前共用；缺省全空）。"""
    row = session.get(CommercialEntitlement, user_id)
    if row is None:
        row = CommercialEntitlement(user_id=user_id)
        session.add(row)
        session.flush()
    return row


def _snapshot(row: CommercialEntitlement) -> dict[str, Any]:
    """变更前快照（事件 changes.before 用；四类字段全量）。"""
    return {
        "commercial_role": row.commercial_role,
        "seat_status": row.seat_status,
        "seat_source": row.seat_source,
        "seat_expires_at": row.seat_expires_at.isoformat() if row.seat_expires_at else None,
        "certification_status": row.certification_status,
        "certification_source": row.certification_source,
        "delivery_eligibility": row.delivery_eligibility,
    }


def set_commercial_role(
    session: Session,
    *,
    actor: User,
    user_id: str,
    role: object,
    confirm_password: object,
) -> dict[str, Any]:
    """设置角色分层（R1–R4，可 NULL=清空未分层）。

    值域闸：非 R 系一律 400（含以 L 开头的任何值——ADR-006 §2.1）；同值
    幂等零事件零变更；users.role 平台权限角色不受任何影响（正交裁决）。
    """
    _require_admin(actor)
    _confirm_password(session, actor, confirm_password)
    user = _require_user(session, user_id)
    if role is not None and role not in COMMERCIAL_ROLES:
        raise _error(
            "invalid_commercial_role",
            "角色分层必须是 R1/R2/R3/R4 之一或 null（未分层）。",
        )
    row = ensure_entitlement(session, user_id)
    before = _snapshot(row)
    if row.commercial_role == role:
        return {"entitlement": serialize_entitlement(row), "changed": False}
    row.commercial_role = role  # type: ignore[assignment]
    record_event(
        session,
        actor,
        "commercial_role_changed",
        user,
        {
            "request_id": str(uuid4()),
            "target_user_id": user.id,
            "before": before,
            "after": {**before, "commercial_role": role},
        },
    )
    return {"entitlement": serialize_entitlement(row), "changed": True}


def add_training_entitlement(
    session: Session,
    *,
    actor: User,
    user_id: str,
    item_type: object,
    valid_from: object = None,
    valid_until: object = None,
    note: object = None,
    confirm_password: object = None,
) -> dict[str, Any]:
    """登记培训权益购买行（培训费/认证费/陪跑；有效期可空=待试点数值）。

    陪跑（``mentoring``）未给到期日时，按 G3 的「陪跑期限与培训周期挂钩」
    配置位推导（任务书 §7：结构先落，数值待定——周期未配置则到期日留空）。
    """
    _require_admin(actor)
    _confirm_password(session, actor, confirm_password)
    user = _require_user(session, user_id)
    if item_type not in TRAINING_ITEM_TYPES:
        raise _error(
            "invalid_training_item_type",
            "item_type 必须是 training/certification/mentoring 之一。",
        )
    if note is not None and (not isinstance(note, str) or len(note) > 255):
        raise _error("invalid_request", "note 必须是 ≤255 字符字符串或 null。")
    valid_from_value = _parsemoment(valid_from, "valid_from")
    valid_until_value = _parsemoment(valid_until, "valid_until")
    if item_type == "mentoring" and valid_until_value is None:
        # 陪跑期限与培训周期挂钩（任务书 §7）：周期配置位未设 ⇒ **数值待定**，
        # 到期日留空（结构先落，数值后填）。延迟导入避免 commercial 环。
        from fde_api.commercial.ledger_service import resolve_mentoring_valid_until

        valid_until_value = resolve_mentoring_valid_until(session, valid_from_value)
    row = TrainingEntitlement(
        user_id=user_id,
        item_type=item_type,  # type: ignore[arg-type]
        valid_from=valid_from_value,
        valid_until=valid_until_value,
        granted_by_user_id=actor.id,
        note=note if isinstance(note, str) else None,
    )
    session.add(row)
    session.flush()
    record_event(
        session,
        actor,
        "commercial_training_granted",
        user,
        {
            "request_id": str(uuid4()),
            "target_user_id": user_id,
            "training_id": row.id,
            "item_type": row.item_type,
            "valid_from": row.valid_from.isoformat() if row.valid_from else None,
            "valid_until": row.valid_until.isoformat() if row.valid_until else None,
        },
    )
    return {"training": serialize_training(row), "changed": True}


def revoke_training_entitlement(
    session: Session,
    *,
    actor: User,
    user_id: str,
    training_id: object,
    confirm_password: object,
) -> dict[str, Any]:
    """撤销培训权益行（active→revoked；已撤销行幂等 200 零事件）。"""
    _require_admin(actor)
    _confirm_password(session, actor, confirm_password)
    user = _require_user(session, user_id)
    if not isinstance(training_id, str) or not training_id:
        raise _error("invalid_request", "training_id 必填。")
    row = session.get(TrainingEntitlement, training_id)
    if row is None or row.user_id != user_id:
        raise _error("training_not_found", "培训权益行不存在或不属于该用户。", 404)
    if row.status == "revoked":
        return {"training": serialize_training(row), "changed": False}
    row.status = "revoked"
    record_event(
        session,
        actor,
        "commercial_training_revoked",
        user,
        {
            "request_id": str(uuid4()),
            "target_user_id": user_id,
            "training_id": row.id,
            "item_type": row.item_type,
        },
    )
    return {"training": serialize_training(row), "changed": True}


def activate_seat(
    session: Session,
    *,
    actor: User,
    user_id: str,
    seat_source: object,
    expires_at: object = None,
    confirm_password: object = None,
) -> dict[str, Any]:
    """激活年度席位（订阅权益写原语）。

    - 已激活 → 409 ``seat_already_active``（续期/换源是显式动作，不静默覆盖；
      「套餐已含席位不重复收」的计费不变量在 G3 科目层落，本闸是结构前提）。
    - 唯一跨域同步：``fde_profiles.status`` 为 pending 时升 active（ADR-002
      §2.3；suspended/active 不动，档案行不存在则跳过不创建——档案的创建
      归 dispatch 域认证申请流）。
    """
    _require_admin(actor)
    _confirm_password(session, actor, confirm_password)
    user = _require_user(session, user_id)
    if seat_source not in SEAT_SOURCES:
        raise _error(
            "invalid_seat_source",
            "seat_source 必须是 first_delivery/bootcamp_practical/bootcamp_mentorship 之一。",
        )
    row = ensure_entitlement(session, user_id)
    if row.seat_status == "active":
        raise _error("seat_already_active", "该用户年度席位已激活，不重复激活。", 409)
    before = _snapshot(row)
    row.seat_status = "active"
    row.seat_source = seat_source  # type: ignore[assignment]
    row.seat_activated_at = datetime.now(timezone.utc)
    row.seat_expires_at = _parsemoment(expires_at, "expires_at")
    profile_sync: dict[str, Any] | None = None
    profile = session.get(FdeProfile, user_id)
    if profile is not None and profile.status == "pending":
        profile_sync = {"from": "pending", "to": "active"}
        profile.status = "active"
    record_event(
        session,
        actor,
        "commercial_seat_activated",
        user,
        {
            "request_id": str(uuid4()),
            "target_user_id": user_id,
            "seat_source": row.seat_source,
            "expires_at": row.seat_expires_at.isoformat() if row.seat_expires_at else None,
            "before": before,
            "after": {**before, "seat_status": "active", "seat_source": row.seat_source},
            "fde_profile_status_sync": profile_sync,
        },
    )
    return {"entitlement": serialize_entitlement(row), "changed": True}


def set_certification(
    session: Session,
    *,
    actor: User,
    user_id: str,
    certified: object,
    source: object = None,
    confirm_password: object = None,
) -> dict[str, Any]:
    """设置认证状态（培训出口；source=模拟考核等证据指针，不内嵌正文）。

    与 ``fde_level_evidence`` 等级核验链并存互不替代（ADR-002 §2.4）——
    本原语零触碰 dispatch 域。
    """
    _require_admin(actor)
    _confirm_password(session, actor, confirm_password)
    user = _require_user(session, user_id)
    if not isinstance(certified, bool):
        raise _error("invalid_request", "certified 必须是布尔值。")
    if source is not None and (not isinstance(source, str) or len(source) > 120):
        raise _error("invalid_request", "source 必须是 ≤120 字符指针字符串或 null。")
    target_status = "certified" if certified else "uncertified"
    row = ensure_entitlement(session, user_id)
    before = _snapshot(row)
    if row.certification_status == target_status and row.certification_source == source:
        return {"entitlement": serialize_entitlement(row), "changed": False}
    row.certification_status = target_status
    row.certification_source = source if isinstance(source, str) else None
    record_event(
        session,
        actor,
        "commercial_certification_changed",
        user,
        {
            "request_id": str(uuid4()),
            "target_user_id": user_id,
            "before": before,
            "after": {
                **before,
                "certification_status": row.certification_status,
                "certification_source": row.certification_source,
            },
        },
    )
    return {"entitlement": serialize_entitlement(row), "changed": True}


def set_delivery_eligibility(
    session: Session,
    *,
    actor: User,
    user_id: str,
    eligibility: object,
    confirm_password: object = None,
) -> dict[str, Any]:
    """设置交付资格（商业资格；**不写** ``fde_profiles.status``——并存裁决）。"""
    _require_admin(actor)
    _confirm_password(session, actor, confirm_password)
    user = _require_user(session, user_id)
    if eligibility not in DELIVERY_ELIGIBILITIES:
        raise _error(
            "invalid_delivery_eligibility", "eligibility 必须是 none/eligible 之一。"
        )
    row = ensure_entitlement(session, user_id)
    before = _snapshot(row)
    if row.delivery_eligibility == eligibility:
        return {"entitlement": serialize_entitlement(row), "changed": False}
    row.delivery_eligibility = eligibility  # type: ignore[assignment]
    record_event(
        session,
        actor,
        "commercial_delivery_eligibility_changed",
        user,
        {
            "request_id": str(uuid4()),
            "target_user_id": user_id,
            "before": before,
            "after": {**before, "delivery_eligibility": eligibility},
        },
    )
    return {"entitlement": serialize_entitlement(row), "changed": True}


def get_entitlement_for_view(
    session: Session, *, actor: User, user_id: str
) -> dict[str, Any]:
    """读面（本人或 admin）：权益行 + 培训购买行 + 对外编号推导。"""
    if actor.id != user_id and actor.role != ROLE_ADMIN:
        raise _error("commercial_entitlement_forbidden", "只能查看本人权益。", 403)
    _require_user(session, user_id)
    row = ensure_entitlement(session, user_id)
    trainings = session.scalars(
        select(TrainingEntitlement)
        .where(TrainingEntitlement.user_id == user_id)
        .order_by(TrainingEntitlement.created_at.desc(), TrainingEntitlement.id)
    ).all()
    return {
        "entitlement": serialize_entitlement(row),
        "trainings": [serialize_training(item) for item in trainings],
        "external_ladder_code": external_ladder_code(row),
    }


def serialize_entitlement(row: CommercialEntitlement) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    return {
        "user_id": row.user_id,
        "commercial_role": row.commercial_role,
        "subscription": {
            "seat_status": row.seat_status,
            "seat_source": row.seat_source,
            "seat_activated_at": (
                row.seat_activated_at.isoformat() if row.seat_activated_at else None
            ),
            "seat_expires_at": (
                row.seat_expires_at.isoformat() if row.seat_expires_at else None
            ),
            "seat_expired": bool(
                row.seat_status == "active"
                and row.seat_expires_at is not None
                and row.seat_expires_at <= now
            ),
        },
        "certification": {
            "status": row.certification_status,
            "source": row.certification_source,
        },
        "delivery_eligibility": row.delivery_eligibility,
    }


def serialize_training(row: TrainingEntitlement) -> dict[str, Any]:
    return {
        "id": row.id,
        "user_id": row.user_id,
        "item_type": row.item_type,
        "status": row.status,
        "purchased_at": row.purchased_at.isoformat() if row.purchased_at else None,
        "valid_from": row.valid_from.isoformat() if row.valid_from else None,
        "valid_until": row.valid_until.isoformat() if row.valid_until else None,
        "granted_by_user_id": row.granted_by_user_id,
        "note": row.note,
    }


__all__ = [
    "CommercialServiceError",
    "activate_seat",
    "add_training_entitlement",
    "ensure_entitlement",
    "get_entitlement_for_view",
    "revoke_training_entitlement",
    "serialize_entitlement",
    "serialize_training",
    "set_certification",
    "set_commercial_role",
    "set_delivery_eligibility",
    # 值域闭集再导出（路由层引用单点）
    "CERTIFICATION_STATUSES",
    "COMMERCIAL_ROLES",
    "DELIVERY_ELIGIBILITIES",
    "SEAT_SOURCES",
    "SEAT_STATUSES",
    "TRAINING_ITEM_TYPES",
]
