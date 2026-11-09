"""商业化 G3 服务层（一）：收入科目层 + 费用/周期配置位 + 分成比例结构。

语义钉（ADR-003 §2.1–§2.5 / ADR-008；任务书 §7）：

- **收入科目层独立于 ``delivery_settlements``**（ADR-003 §2.1）：收入类型 →
  金额 → 关联对象；三类科目（席位费/培训费/项目分成）**分别记账可分别核对**。
  本模块**不向** ``delivery_settlements`` 加任何列，也**不重算**席位份额。
- **六项名目只定义归属、不定义计算方式**（ADR-003 §2.4）：归属矩阵
  ``LINE_ITEM_SUBJECTS`` 是代码层权威，写路径校验名目↔科目配对；金额来源
  只有三个：配置位（缺省不可用）、关联收款的实收额、人工录入的线下约定金额
  （必附指针 + sha256 指纹）。
- **分成比例本期不落数**（ADR-003 §2.3）：只落「按角色与项目类型配置」的结构；
  本期表内零行。科目层在分成事件上**引用**既有分账结果（``seat_shares_for``），
  比例行只提供落位与可见性，**不参与金额计算**。
- **高风险写默认人工确认**（ADR-003 §2.5 / ADR-007 §2.1）：本模块全部写原语
  要求 admin 角色 + 当前账号密码确认，逐动作落 ``operation_events``。
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from fde_api.auth.models import ROLE_ADMIN, User
from fde_api.auth.passwords import verify_password
from fde_api.commercial.models import (
    CHARGEABLE_FEE_KEYS,
    FEE_CONFIG_KEYS,
    FEE_CONFIG_VALUE_KIND_BY_KEY,
    FEE_CONFIG_VALUE_KINDS,
    LINE_ITEM_SUBJECTS,
    REVENUE_LINE_ITEMS,
    REVENUE_PACKAGE_CODES,
    REVENUE_PACKAGES,
    REVENUE_SUBJECT_TYPES,
    SEAT_SOURCES,
    CommercialFeeConfig,
    CommercialRevenueLedger,
    CommercialSplitRule,
)
from fde_api.commercial.service import CommercialServiceError
from fde_api.dispatch.models import DeliveryPackage, DeliverySettlement
from fde_api.dispatch.settlements import seat_shares_for
from fde_api.projects.events import record_event
from fde_api.workbench.models import Contract, Payment, Quote

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def _error(code: str, message: str, status: int = 400) -> CommercialServiceError:
    return CommercialServiceError(code, message, status)


def _require_admin(actor: User) -> None:
    if actor.role != ROLE_ADMIN:
        raise _error("commercial_admin_required", "商业科目治理仅系统运维员可用。", 403)


def _confirm_password(session: Session, actor: User, password: object) -> None:
    """单次显式授权：admin 写原语须携带当前账号密码（高风险写人工确认）。"""
    if not isinstance(password, str) or not password:
        raise _error("invalid_request", "confirm_password 必填（高风险写人工确认）。")
    current = session.get(User, actor.id)
    if current is None or not verify_password(current.password_hash, password):
        raise _error("invalid_password", "当前账号密码不正确。", 403)


def _require_sha256(value: object, field: str) -> str:
    """证据指纹闸：只收 64 位小写十六进制 sha256（原件不入库不入仓）。"""
    if not isinstance(value, str) or not _SHA256_RE.match(value.strip().lower()):
        raise _error("invalid_request", f"{field} 必须是 64 位 sha256 十六进制指纹。")
    return value.strip().lower()


def _optional_uri(value: object, field: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > 500:
        raise _error("invalid_request", f"{field} 必须是 ≤500 字符指针字符串或 null。")
    return value.strip()


def _to_amount(value: object, field: str) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise _error("invalid_request", f"{field} 必须是金额数字。")
    try:
        amount = Decimal(str(value)).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError):
        raise _error("invalid_request", f"{field} 必须是金额数字。") from None
    if amount < 0:
        raise _error("invalid_request", f"{field} 不能为负数。")
    return amount


def _require_user(session: Session, user_id: object) -> User:
    if not isinstance(user_id, str) or not user_id:
        raise _error("invalid_request", "user_id 必填。")
    user = session.get(User, user_id)
    if user is None:
        raise _error("user_not_found", "用户不存在。", 404)
    return user


# ══════════════════════════════════════════════════════════════════════════
# 费用/周期配置位（本期全部 unset——缺省不可用）
# ══════════════════════════════════════════════════════════════════════════


def ensure_fee_config(session: Session, key: str) -> CommercialFeeConfig:
    """确保配置位存在（**缺省 unset**）——槽位是结构，缺失即补建。

    迁移已播种三个槽位；此处补建是**自愈**语义（测试清理、运维手工清表后
    仍能保证「缺省不可用」不变量成立）。建出来的行恒为 ``unset``，**不落任何
    业务数值**。
    """
    value_kind = FEE_CONFIG_VALUE_KIND_BY_KEY.get(key)
    if value_kind is None:
        raise _error("fee_config_not_found", f"配置位 {key} 不存在。", 404)
    row = session.get(CommercialFeeConfig, key)
    if row is None:
        row = CommercialFeeConfig(key=key, value_kind=value_kind, status="unset")
        session.add(row)
        session.flush()
    return row


def get_fee_config(session: Session, key: str) -> CommercialFeeConfig:
    return ensure_fee_config(session, key)


def list_fee_configs(session: Session) -> list[CommercialFeeConfig]:
    for key in FEE_CONFIG_KEYS:
        ensure_fee_config(session, key)
    return list(
        session.scalars(
            select(CommercialFeeConfig)
            .where(CommercialFeeConfig.key.in_(FEE_CONFIG_KEYS))
            .order_by(CommercialFeeConfig.key)
        )
    )


def fee_amount(session: Session, key: str) -> Decimal:
    """取配置位金额——**未配置即不可用**（缺省不可收款）。"""
    row = get_fee_config(session, key)
    if row.status != "configured" or row.amount is None:
        raise _error(
            "fee_not_configured",
            f"配置位 {key} 尚未配置，本期不可据此收费（金额待拍板）。",
            409,
        )
    return Decimal(row.amount)


def resolve_mentoring_period_days(session: Session) -> int | None:
    """陪跑期限（与培训周期挂钩）——**本期数值待定**⇒ 返回 None。

    结构先落：配置位在、推导路径在；未配置时陪跑权益的到期日留空（不落默认
    天数），由后续轮次填实数（任务书 §7「陪跑期限与培训周期挂钩：结构先落，
    数值待定」）。
    """
    row = session.get(CommercialFeeConfig, "mentoring_period_days")
    if row is None or row.status != "configured" or row.days is None:
        return None
    return int(row.days)


def resolve_mentoring_valid_until(
    session: Session, valid_from: datetime | None
) -> datetime | None:
    """陪跑权益到期日 = 起始 + 陪跑周期天数；周期未配置 ⇒ None（数值待定）。"""
    days = resolve_mentoring_period_days(session)
    if days is None:
        return None
    start = valid_from or datetime.now(timezone.utc)
    return start + timedelta(days=days)


def configure_fee_config(
    session: Session,
    *,
    actor: User,
    key: object,
    value: object = None,
    source_uri: object = None,
    content_hash: object = None,
    confirm_password: object,
) -> dict[str, Any]:
    """配置费用/周期配置位（admin + 密码确认）。

    ``value=None`` ⇒ 把配置位**退回 unset**（数值待定态）——已配置过的位可以
    被显式清空回到「缺省不可用」，但**清空必须同样留证据**（谁、何时、依据）。
    """
    _require_admin(actor)
    _confirm_password(session, actor, confirm_password)
    if not isinstance(key, str) or key not in FEE_CONFIG_KEYS:
        raise _error("invalid_fee_config_key", f"key 必须是 {'/'.join(FEE_CONFIG_KEYS)} 之一。")
    row = get_fee_config(session, key)
    if row.value_kind not in FEE_CONFIG_VALUE_KINDS:  # pragma: no cover - 数据兜底
        raise _error("invalid_fee_config_key", "配置位 value_kind 非法。")

    uri = _optional_uri(source_uri, "source_uri")
    digest = _require_sha256(content_hash, "content_hash") if content_hash is not None else None
    if uri is None or digest is None:
        raise _error("invalid_request", "配置须附 source_uri 指针与 content_hash 指纹。")

    if value is None:
        row.status = "unset"
        row.amount = None
        row.days = None
        row.threshold = None
    else:
        if row.value_kind == "amount":
            row.amount = _to_amount(value, "value")
            row.days = None
            row.threshold = None
        elif row.value_kind == "days":
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise _error("invalid_request", "days 型配置位必须是正整数。")
            row.days = int(value)
            row.amount = None
            row.threshold = None
        else:
            row.threshold = _to_amount(value, "value")
            row.amount = None
            row.days = None
        row.status = "configured"
    row.source_uri = uri
    row.content_hash = digest
    row.configured_by_user_id = actor.id
    row.configured_at = datetime.now(timezone.utc)
    session.flush()
    record_event(
        session,
        actor,
        "commercial_fee_config_changed",
        actor,
        {
            "request_id": str(uuid4()),
            "key": key,
            "status": row.status,
            "value_kind": row.value_kind,
        },
    )
    return {"fee_config": serialize_fee_config(row), "changed": True}


def serialize_fee_config(row: CommercialFeeConfig) -> dict[str, Any]:
    return {
        "key": row.key,
        "value_kind": row.value_kind,
        "status": row.status,
        "configured": row.status == "configured",
        "amount": float(row.amount) if row.amount is not None else None,
        "days": row.days,
        "threshold": float(row.threshold) if row.threshold is not None else None,
        "source_uri": row.source_uri,
        "content_hash": row.content_hash,
        "configured_by_user_id": row.configured_by_user_id,
        "configured_at": row.configured_at.isoformat() if row.configured_at else None,
    }


# ══════════════════════════════════════════════════════════════════════════
# 分成比例配置结构（按角色 × 项目类型；本期不落数）
# ══════════════════════════════════════════════════════════════════════════


def list_split_rules(session: Session) -> list[CommercialSplitRule]:
    return list(
        session.scalars(
            select(CommercialSplitRule).order_by(
                CommercialSplitRule.role_code, CommercialSplitRule.project_type
            )
        )
    )


def register_split_rule(
    session: Session,
    *,
    actor: User,
    role_code: object,
    project_type: object,
    ratio_bp: object = None,
    source_uri: object = None,
    content_hash: object = None,
    confirm_password: object,
) -> dict[str, Any]:
    """登记/配置「按角色与项目类型」的分成比例维度（admin + 密码确认）。

    ``ratio_bp=None`` ⇒ 登记维度但**比例不定数**（``status='unset'``，
    ``ratio_bp`` 恒 NULL）——本期用这个形态。给比例必须附书面依据指针 +
    sha256 指纹（ADR-003 §2.3：配置位缺省不预写业务数值）。
    """
    _require_admin(actor)
    _confirm_password(session, actor, confirm_password)
    if role_code not in ("R1", "R2", "R3", "R4"):
        raise _error("invalid_role_code", "role_code 必须是 R1/R2/R3/R4 之一。")
    if not isinstance(project_type, str) or not project_type.strip() or len(project_type) > 32:
        raise _error("invalid_project_type", "project_type 必须是 ≤32 字符非空字符串。")
    key = project_type.strip()

    row = session.scalar(
        select(CommercialSplitRule).where(
            CommercialSplitRule.role_code == role_code,
            CommercialSplitRule.project_type == key,
        )
    )
    uri = _optional_uri(source_uri, "source_uri")
    digest = _require_sha256(content_hash, "content_hash") if content_hash is not None else None

    if ratio_bp is None:
        if uri is None or digest is None:
            raise _error("invalid_request", "登记维度须附 source_uri 指针与 content_hash 指纹。")
        ratio_value = None
        status = "unset"
    else:
        if isinstance(ratio_bp, bool) or not isinstance(ratio_bp, int):
            raise _error("invalid_ratio", "ratio_bp 必须是整数（万分比，0–10000）。")
        if ratio_bp < 0 or ratio_bp > 10000:
            raise _error("invalid_ratio", "ratio_bp 必须在 0–10000 之间。")
        if uri is None or digest is None:
            raise _error("invalid_request", "配置比例须附 source_uri 指针与 content_hash 指纹。")
        ratio_value = int(ratio_bp)
        status = "configured"

    if row is None:
        row = CommercialSplitRule(role_code=role_code, project_type=key)
        session.add(row)
    row.ratio_bp = ratio_value
    row.status = status
    row.source_uri = uri
    row.content_hash = digest
    row.configured_by_user_id = actor.id
    row.configured_at = datetime.now(timezone.utc)
    session.flush()
    record_event(
        session,
        actor,
        "commercial_split_rule_registered",
        actor,
        {
            "request_id": str(uuid4()),
            "role_code": role_code,
            "project_type": key,
            "status": status,
        },
    )
    return {"split_rule": serialize_split_rule(row), "changed": True}


def serialize_split_rule(row: CommercialSplitRule) -> dict[str, Any]:
    return {
        "id": row.id,
        "role_code": row.role_code,
        "project_type": row.project_type,
        "ratio_bp": row.ratio_bp,
        "status": row.status,
        "configured": row.status == "configured",
        "source_uri": row.source_uri,
        "content_hash": row.content_hash,
        "configured_by_user_id": row.configured_by_user_id,
        "configured_at": row.configured_at.isoformat() if row.configured_at else None,
    }


# ══════════════════════════════════════════════════════════════════════════
# 收入科目层
# ══════════════════════════════════════════════════════════════════════════


def _check_line_item(subject_type: str, line_item: str) -> None:
    if line_item not in REVENUE_LINE_ITEMS:
        raise _error("invalid_line_item", "line_item 必须是六项计费名目之一。")
    allowed = LINE_ITEM_SUBJECTS.get(line_item, ())
    if subject_type not in allowed:
        raise _error(
            "line_item_subject_mismatch",
            f"名目 {line_item} 不归属科目 {subject_type}（六名目只定义归属）。",
        )


def _resolve_linked_objects(
    session: Session,
    *,
    quote_id: object,
    payment_id: object,
    contract_id: object,
    delivery_settlement_id: object,
    delivery_package_id: object,
    training_entitlement_id: object,
    package_code: object,
) -> dict[str, str | None]:
    """关联对象校验（外键指回既有结算与报价/合同对象，ADR-003 §2.1）。

    关联对象口径＝订单〔套餐〕/席位/分成事件/报价/收款/合同/分账——至少一个非空，
    科目行不得悬空。
    """
    resolved: dict[str, str | None] = {}
    checks: list[tuple[str, object, Any]] = [
        ("quote_id", quote_id, Quote),
        ("payment_id", payment_id, Payment),
        ("contract_id", contract_id, Contract),
        ("delivery_settlement_id", delivery_settlement_id, DeliverySettlement),
        ("delivery_package_id", delivery_package_id, DeliveryPackage),
    ]
    for field, value, model in checks:
        if value is None:
            resolved[field] = None
            continue
        if not isinstance(value, str) or not value:
            raise _error("invalid_request", f"{field} 必须是字符串 id 或 null。")
        if session.get(model, value) is None:
            raise _error("linked_object_not_found", f"{field} 指向的对象不存在。", 404)
        resolved[field] = value
    if training_entitlement_id is None:
        resolved["training_entitlement_id"] = None
    else:
        if not isinstance(training_entitlement_id, str) or not training_entitlement_id:
            raise _error("invalid_request", "training_entitlement_id 必须是字符串 id 或 null。")
        from fde_api.commercial.models import TrainingEntitlement

        if session.get(TrainingEntitlement, training_entitlement_id) is None:
            raise _error("linked_object_not_found", "training_entitlement_id 指向的对象不存在。", 404)
        resolved["training_entitlement_id"] = training_entitlement_id
    resolved["package_code"] = package_code if isinstance(package_code, str) else None
    if not any(resolved.values()):
        raise _error(
            "missing_association",
            "科目行必须关联至少一个既有对象（订单/席位/分成事件/报价/收款/合同/分账）。",
        )
    return resolved


def _split_rule_for(session: Session, role_code: str | None, project_type: str | None):
    if not role_code or not project_type:
        return None
    return session.scalar(
        select(CommercialSplitRule).where(
            CommercialSplitRule.role_code == role_code,
            CommercialSplitRule.project_type == project_type,
        )
    )


def insert_revenue_entry(
    session: Session,
    *,
    actor: User,
    subject_type: str,
    line_item: str,
    amount: Decimal,
    subject_user_id: str | None = None,
    payee_user_id: str | None = None,
    quote_id: str | None = None,
    payment_id: str | None = None,
    contract_id: str | None = None,
    delivery_settlement_id: str | None = None,
    delivery_package_id: str | None = None,
    training_entitlement_id: str | None = None,
    package_code: str | None = None,
    seat_source: str | None = None,
    fee_key: str | None = None,
    role_code: str | None = None,
    project_type: str | None = None,
    seat_shares: dict[str, Any] | None = None,
    basis: dict[str, Any] | None = None,
    source_uri: str | None = None,
    content_hash: str | None = None,
    occurred_at: datetime | None = None,
) -> CommercialRevenueLedger:
    """写入一条科目行（内部原语；对外写路由一律经 :func:`record_revenue_entry`）。"""
    entry = CommercialRevenueLedger(
        subject_type=subject_type,
        line_item=line_item,
        amount=amount,
        subject_user_id=subject_user_id,
        payee_user_id=payee_user_id,
        quote_id=quote_id,
        payment_id=payment_id,
        contract_id=contract_id,
        delivery_settlement_id=delivery_settlement_id,
        delivery_package_id=delivery_package_id,
        training_entitlement_id=training_entitlement_id,
        package_code=package_code,
        seat_source=seat_source,
        fee_key=fee_key,
        role_code=role_code,
        project_type=project_type,
        seat_shares=seat_shares,
        basis=basis,
        source_uri=source_uri,
        content_hash=content_hash,
        recorded_by_user_id=actor.id,
        occurred_at=occurred_at or datetime.now(timezone.utc),
    )
    session.add(entry)
    session.flush()
    return entry


def record_revenue_entry(
    session: Session,
    *,
    actor: User,
    subject_type: object,
    line_item: object,
    amount: object = None,
    fee_key: object = None,
    subject_user_id: object = None,
    payee_user_id: object = None,
    quote_id: object = None,
    payment_id: object = None,
    contract_id: object = None,
    delivery_settlement_id: object = None,
    delivery_package_id: object = None,
    training_entitlement_id: object = None,
    package_code: object = None,
    seat_source: object = None,
    role_code: object = None,
    project_type: object = None,
    source_uri: object = None,
    content_hash: object = None,
    confirm_password: object,
) -> dict[str, Any]:
    """记一笔收入科目（admin + 密码确认的高风险写，ADR-003 §2.5）。

    金额来源三选一（**不定义计算方式**——ADR-003 §2.4）：
    1. ``fee_key`` 配置位（缺省未配置 ⇒ 409 ``fee_not_configured``）；
    2. 关联收款的实收额（``payment_id`` → ``payments.received_amount``）；
    3. 人工录入的线下约定金额（必附 ``source_uri`` + ``content_hash``）。

    项目分成科目**只引用既有分账结果**：金额取 ``delivery_settlements`` 的
    delivery 席位金额（ADR-003 §2.2「不重算」），席位份额快照取
    ``seat_shares_for`` 的结果引用；传入不一致的金额一律 409 拒绝。
    """
    _require_admin(actor)
    _confirm_password(session, actor, confirm_password)
    if subject_type not in REVENUE_SUBJECT_TYPES:
        raise _error("invalid_subject_type", "subject_type 必须是 seat_fee/training_fee/project_share 之一。")
    if not isinstance(line_item, str):
        raise _error("invalid_line_item", "line_item 必须是六项计费名目之一。")
    _check_line_item(subject_type, line_item)

    if fee_key is not None and fee_key not in CHARGEABLE_FEE_KEYS:
        raise _error("invalid_fee_key", f"fee_key 必须是 {'/'.join(CHARGEABLE_FEE_KEYS)} 之一或 null。")

    pkg_code = package_code if isinstance(package_code, str) else None
    seat_src = seat_source if isinstance(seat_source, str) else None
    if seat_src is None and pkg_code is not None:
        seat_src = REVENUE_PACKAGES[pkg_code]["seat_source"]
    if seat_src is not None and seat_src not in SEAT_SOURCES:
        raise _error(
            "invalid_seat_source",
            "seat_source 必须是 first_delivery/bootcamp_practical/bootcamp_mentorship 之一。",
        )
    if pkg_code is not None and pkg_code not in REVENUE_PACKAGE_CODES:
        raise _error("invalid_package_code", f"package_code 必须是 {'/'.join(REVENUE_PACKAGE_CODES)} 之一。")
    if subject_type == "seat_fee" and (
        pkg_code == "first_delivery" or seat_source == "first_delivery"
    ):
        raise _error(
            "first_order_fee_requires_charge_path",
            "首单席位费必须经首单扣费闸记账（验收 + 书面选定 + 不重复收检查）。",
            409,
        )

    linked = _resolve_linked_objects(
        session,
        quote_id=quote_id,
        payment_id=payment_id,
        contract_id=contract_id,
        delivery_settlement_id=delivery_settlement_id,
        delivery_package_id=delivery_package_id,
        training_entitlement_id=training_entitlement_id,
        package_code=pkg_code,
    )

    role = role_code if isinstance(role_code, str) else None
    if role is not None and role not in ("R1", "R2", "R3", "R4"):
        raise _error("invalid_role_code", "role_code 必须是 R1/R2/R3/R4 之一或 null。")
    ptype = project_type.strip() if isinstance(project_type, str) and project_type.strip() else None
    if ptype is not None and len(ptype) > 32:
        raise _error("invalid_project_type", "project_type 必须是 ≤32 字符字符串或 null。")

    uri = _optional_uri(source_uri, "source_uri")
    digest = _require_sha256(content_hash, "content_hash") if content_hash is not None else None

    basis: dict[str, Any] = {}
    seat_shares: dict[str, Any] | None = None

    # ── 金额来源判定 ──
    if fee_key is not None:
        if fee_key == "certification_fee" and linked["training_entitlement_id"]:
            from fde_api.commercial.models import TrainingEntitlement

            training_row = session.get(TrainingEntitlement, linked["training_entitlement_id"])
            if training_row is not None and training_row.item_type != "certification":
                raise _error(
                    "fee_key_entitlement_mismatch",
                    "认证费只能记在认证类培训权益行上（认证费是独立收费项）。",
                )
        resolved_amount = fee_amount(session, fee_key)
        basis["fee_key"] = fee_key
    elif subject_type == "project_share":
        if linked["delivery_settlement_id"] is None:
            raise _error(
                "project_share_requires_settlement",
                "项目分成科目必须挂 delivery_settlement_id（引用既有分账结果，不重算）。",
            )
        settlement = session.get(DeliverySettlement, linked["delivery_settlement_id"])
        assert settlement is not None  # 已由 _resolve_linked_objects 校验
        resolved_amount = Decimal(settlement.delivery_amount)
        if amount is not None:
            requested = _to_amount(amount, "amount")
            if requested != resolved_amount:
                raise _error(
                    "amount_mismatch_settlement",
                    "项目分成金额必须等于既有分账的 delivery 席位金额（科目层不重算）。",
                    409,
                )
        package = session.get(DeliveryPackage, settlement.package_id)
        if package is not None:
            seat_shares = seat_shares_for(session, package)
            basis["seat_shares_source"] = "dispatch/settlements.py::seat_shares_for"
        basis["delivery_settlement_id"] = settlement.id
        basis["settlement_key"] = settlement.settlement_key
    elif linked["payment_id"] is not None:
        payment = session.get(Payment, linked["payment_id"])
        assert payment is not None
        if payment.received_amount is None:
            raise _error("payment_not_received", "关联收款尚未实收，不能按实收额记账。", 409)
        resolved_amount = Decimal(payment.received_amount)
        basis["payment_id"] = payment.id
    else:
        if amount is None:
            raise _error(
                "missing_amount",
                "记账金额缺失：须给 fee_key / 已实收的 payment_id / 线下约定金额三者之一。",
            )
        resolved_amount = _to_amount(amount, "amount")
        if uri is None or digest is None:
            raise _error(
                "invalid_request",
                "线下约定金额记账须附 source_uri 指针与 content_hash 指纹。",
            )
        basis["amount_source"] = "offline_agreement"

    rule = _split_rule_for(session, role, ptype)
    if rule is not None:
        basis["split_rule_id"] = rule.id
        basis["split_ratio_status"] = rule.status
        if rule.ratio_bp is not None:
            basis["split_ratio_bp"] = rule.ratio_bp
    elif role and ptype:
        basis["split_ratio_status"] = "unregistered"

    for field, value in (("subject_user_id", subject_user_id), ("payee_user_id", payee_user_id)):
        if isinstance(value, str) and value and session.get(User, value) is None:
            raise _error("user_not_found", f"{field} 指向的用户不存在。", 404)

    entry = insert_revenue_entry(
        session,
        actor=actor,
        subject_type=subject_type,
        line_item=line_item,
        amount=resolved_amount,
        subject_user_id=subject_user_id if isinstance(subject_user_id, str) else None,
        payee_user_id=payee_user_id if isinstance(payee_user_id, str) else None,
        quote_id=linked["quote_id"],
        payment_id=linked["payment_id"],
        contract_id=linked["contract_id"],
        delivery_settlement_id=linked["delivery_settlement_id"],
        delivery_package_id=linked["delivery_package_id"],
        training_entitlement_id=linked["training_entitlement_id"],
        package_code=pkg_code,
        seat_source=seat_src,
        fee_key=fee_key if isinstance(fee_key, str) else None,
        role_code=role,
        project_type=ptype,
        seat_shares=seat_shares,
        basis=basis or None,
        source_uri=uri,
        content_hash=digest,
    )
    if rule is not None:
        entry.split_rule_id = rule.id
        session.flush()
    event_target = actor
    if entry.subject_user_id:
        subject_row = session.get(User, entry.subject_user_id)
        if subject_row is not None:
            event_target = subject_row
    record_event(
        session,
        actor,
        "commercial_revenue_recorded",
        event_target,
        {
            "request_id": str(uuid4()),
            "entry_id": entry.id,
            "subject_type": entry.subject_type,
            "line_item": entry.line_item,
            "amount": float(entry.amount),
            "subject_user_id": entry.subject_user_id,
        },
    )
    return {"entry": serialize_revenue_entry(entry), "changed": True}


def list_revenue_entries(
    session: Session,
    *,
    actor: User,
    subject_type: object = None,
    subject_user_id: object = None,
    status: object = None,
    limit: object = 100,
) -> dict[str, Any]:
    """科目列表（本人只见自己的；admin 见全量）——「三类科目分别可查」。"""
    statement = select(CommercialRevenueLedger)
    if actor.role != ROLE_ADMIN:
        statement = statement.where(
            (CommercialRevenueLedger.subject_user_id == actor.id)
            | (CommercialRevenueLedger.payee_user_id == actor.id)
        )
    if subject_type is not None:
        if subject_type not in REVENUE_SUBJECT_TYPES:
            raise _error("invalid_subject_type", "subject_type 必须是三类科目之一。")
        statement = statement.where(CommercialRevenueLedger.subject_type == subject_type)
    if status is not None:
        if status not in ("recorded", "reconciled", "voided"):
            raise _error("invalid_status", "status 必须是 recorded/reconciled/voided 之一。")
        statement = statement.where(CommercialRevenueLedger.status == status)
    if subject_user_id is not None:
        if actor.role != ROLE_ADMIN and subject_user_id != actor.id:
            raise _error("commercial_ledger_forbidden", "只能查看本人科目记录。", 403)
        statement = statement.where(CommercialRevenueLedger.subject_user_id == subject_user_id)
    try:
        limit_value = int(str(limit))
    except (TypeError, ValueError):
        raise _error("invalid_request", "limit 必须是整数。") from None
    rows = list(
        session.scalars(
            statement.order_by(
                CommercialRevenueLedger.occurred_at.desc(), CommercialRevenueLedger.id
            ).limit(max(1, min(limit_value, 500)))
        )
    )
    return {
        "entries": [serialize_revenue_entry(row) for row in rows],
        "count": len(rows),
        "scope": "platform" if actor.role == ROLE_ADMIN else "self",
    }


def get_revenue_entry(
    session: Session, *, actor: User, entry_id: str
) -> dict[str, Any]:
    row = session.get(CommercialRevenueLedger, entry_id)
    if row is None:
        raise _error("revenue_entry_not_found", "科目行不存在。", 404)
    if actor.role != ROLE_ADMIN and actor.id not in (row.subject_user_id, row.payee_user_id):
        raise _error("commercial_ledger_forbidden", "只能查看本人科目记录。", 403)
    return {"entry": serialize_revenue_entry(row)}


def reconcile_revenue(
    session: Session,
    *,
    actor: User,
    subject_type: object = None,
    subject_user_id: object = None,
) -> dict[str, Any]:
    """科目对账（按科目×名目汇总 + 与收款台账的差异计数）——「可对账」。

    对账口径：
    - ``total_amount``＝科目层入账金额合计（作废行不计）；
    - ``linked_payment_total``＝这些行所关联收款的实收额合计；
    - ``payment_mismatch_count``＝行金额与关联收款实收额**不一致**的笔数
      （线下约定行不计入分母，也不算差异）；
    - ``unlinked_count``＝未挂收款的行数（线下约定记账）。
    """
    if subject_type is not None and subject_type not in REVENUE_SUBJECT_TYPES:
        raise _error("invalid_subject_type", "subject_type 必须是三类科目之一。")
    if subject_user_id is not None and actor.role != ROLE_ADMIN and subject_user_id != actor.id:
        raise _error("commercial_ledger_forbidden", "只能对账本人科目记录。", 403)

    statement = select(CommercialRevenueLedger).where(CommercialRevenueLedger.status != "voided")
    if actor.role != ROLE_ADMIN:
        statement = statement.where(
            (CommercialRevenueLedger.subject_user_id == actor.id)
            | (CommercialRevenueLedger.payee_user_id == actor.id)
        )
    if subject_type is not None:
        statement = statement.where(CommercialRevenueLedger.subject_type == subject_type)
    if subject_user_id is not None:
        statement = statement.where(CommercialRevenueLedger.subject_user_id == subject_user_id)
    rows = list(session.scalars(statement.order_by(CommercialRevenueLedger.id)))

    buckets: dict[str, dict[str, Any]] = {}
    for row in rows:
        bucket = buckets.setdefault(
            row.subject_type,
            {
                "entry_count": 0,
                "total_amount": Decimal("0.00"),
                "linked_payment_total": Decimal("0.00"),
                "payment_mismatch_count": 0,
                "unlinked_count": 0,
                "by_line_item": {},
            },
        )
        bucket["entry_count"] += 1
        bucket["total_amount"] += Decimal(row.amount)
        line_bucket = bucket["by_line_item"].setdefault(
            row.line_item, {"entry_count": 0, "total_amount": Decimal("0.00")}
        )
        line_bucket["entry_count"] += 1
        line_bucket["total_amount"] += Decimal(row.amount)
        if row.payment_id:
            payment = session.get(Payment, row.payment_id)
            if payment is not None and payment.received_amount is not None:
                received = Decimal(payment.received_amount)
                bucket["linked_payment_total"] += received
                if received != Decimal(row.amount):
                    bucket["payment_mismatch_count"] += 1
            else:
                bucket["unlinked_count"] += 1
        else:
            bucket["unlinked_count"] += 1

    def _dump(value: dict[str, Any]) -> dict[str, Any]:
        return {
            "entry_count": value["entry_count"],
            "total_amount": float(value["total_amount"]),
            "linked_payment_total": float(value["linked_payment_total"]),
            "payment_mismatch_count": value["payment_mismatch_count"],
            "unlinked_count": value["unlinked_count"],
            "by_line_item": {
                key: {
                    "entry_count": item["entry_count"],
                    "total_amount": float(item["total_amount"]),
                }
                for key, item in sorted(value["by_line_item"].items())
            },
        }

    return {
        "scope": "platform" if actor.role == ROLE_ADMIN else "self",
        "subjects": {key: _dump(value) for key, value in sorted(buckets.items())},
        "subject_types": list(REVENUE_SUBJECT_TYPES),
    }


def serialize_revenue_entry(row: CommercialRevenueLedger) -> dict[str, Any]:
    return {
        "id": row.id,
        "subject_type": row.subject_type,
        "line_item": row.line_item,
        "status": row.status,
        "amount": float(row.amount),
        "currency": row.currency,
        "subject_user_id": row.subject_user_id,
        "payee_user_id": row.payee_user_id,
        "associations": {
            "quote_id": row.quote_id,
            "payment_id": row.payment_id,
            "contract_id": row.contract_id,
            "delivery_settlement_id": row.delivery_settlement_id,
            "delivery_package_id": row.delivery_package_id,
            "training_entitlement_id": row.training_entitlement_id,
            "split_rule_id": row.split_rule_id,
        },
        "package_code": row.package_code,
        "seat_source": row.seat_source,
        "fee_key": row.fee_key,
        "role_code": row.role_code,
        "project_type": row.project_type,
        "seat_shares": row.seat_shares,
        "basis": row.basis,
        "source_uri": row.source_uri,
        "content_hash": row.content_hash,
        "recorded_by_user_id": row.recorded_by_user_id,
        "occurred_at": row.occurred_at.isoformat() if row.occurred_at else None,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


__all__ = [
    "CommercialServiceError",
    "configure_fee_config",
    "fee_amount",
    "get_fee_config",
    "insert_revenue_entry",
    "list_fee_configs",
    "list_revenue_entries",
    "list_split_rules",
    "record_revenue_entry",
    "reconcile_revenue",
    "register_split_rule",
    "resolve_mentoring_period_days",
    "resolve_mentoring_valid_until",
    "serialize_fee_config",
    "serialize_revenue_entry",
    "serialize_split_rule",
]
