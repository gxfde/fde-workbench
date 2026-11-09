"""商业化 G2 服务层：企业免费额度（ADR-004 主体认定 + ADR-007 人工确认默认）。

语义钉（实施不得越界）：

- **额度键挂主体（规范化统一社会信用代码）而非账号**——「一次一主体、
  长期有效不重置、换账号不重置」的结构性保证（ADR-004 §1.1–1.3）；
- 授予/完成=高风险治理写（admin+密码确认双闸，ADR-007 §2.1）；诊断启动/
  企业确认=当事人自证动作（认证用户路由+事件留痕，不需 admin 密码）；
- **完成判据=恰好六键全真**（FREE_DIAGNOSIS_DELIVERABLES），缺失点名 409；
  企业确认必须在完成之后且由**绑定账号本人**执行（admin 不得代企业确认）；
- 本模块只承载判据账与常量（六项/不免费七项/三档描述/两档上限），**不生成
  诊断内容、不触碰 V3.2 simulation 域**（体验上限消费接线归 G6，显式挂账）。
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from fde_api.auth.models import ROLE_ADMIN, User
from fde_api.auth.passwords import verify_password
from fde_api.commercial.service import CommercialServiceError
from fde_api.commercial.models import (
    DIAGNOSIS_PROJECT_TIERS,
    EXPERIENCE_LIMITS,
    EXPERIENCE_LIMITS_PLACEHOLDER,
    EXPERIENCE_LIMIT_KINDS,
    FREE_DIAGNOSIS_DELIVERABLES,
    FREE_EXCLUSIONS,
    FREE_TRIAL_ENTRIES,
    REGISTRATION_ENTRIES,
    FREE_TRIAL_ENTRY_KEYS,
    EnterpriseFreeQuota,
    EnterpriseQuotaSubject,
)
from fde_api.projects.events import record_event

# 统一社会信用代码字符集（GB 32100-2015：31 个字符，索引即值）与权值
_USCC_CHARS = "0123456789ABCDEFGHJKLMNPQRTUWXY"
_USCC_WEIGHTS = (1, 3, 9, 27, 19, 26, 16, 17, 20, 29, 25, 13, 8, 24, 10, 30, 28)


def _error(code: str, message: str, status: int = 400) -> CommercialServiceError:
    return CommercialServiceError(code, message, status)


def _require_admin(actor: User) -> None:
    if actor.role != ROLE_ADMIN:
        raise _error("commercial_admin_required", "免费额度管理仅系统运维员可用。", 403)


def _confirm_password(session: Session, actor: User, password: object) -> None:
    if not isinstance(password, str) or not password:
        raise _error("invalid_request", "confirm_password 必填（高风险写人工确认）。")
    current = session.get(User, actor.id)
    if current is None or not verify_password(current.password_hash, password):
        raise _error("invalid_password", "当前账号密码不正确。", 403)


def normalize_subject_key(raw: object) -> str:
    """主体认定键规范化（ADR-004 §1.1）：大写去空格连字符 + mod-31 校验位。"""
    if not isinstance(raw, str):
        raise _error("invalid_subject_key", "subject_key 必须是统一社会信用代码字符串。")
    key = raw.strip().upper().replace(" ", "").replace("-", "")
    if len(key) != 18 or any(ch not in _USCC_CHARS for ch in key):
        raise _error(
            "invalid_subject_key",
            "subject_key 必须是 18 位统一社会信用代码（字符集 0-9A-HJ-NPQRTUWXY）。",
        )
    total = sum(_USCC_CHARS.index(key[i]) * weight for i, weight in enumerate(_USCC_WEIGHTS))
    if _USCC_CHARS[(31 - total % 31) % 31] != key[17]:
        raise _error("invalid_subject_key", "统一社会信用代码校验位不正确。")
    return key


def _require_quota(session: Session, subject_key: str) -> EnterpriseFreeQuota:
    row = session.get(EnterpriseFreeQuota, subject_key)
    if row is None:
        raise _error("quota_not_found", "该主体尚无免费额度记录。", 404)
    return row


def _lock_quota(session: Session, subject_key: str) -> EnterpriseFreeQuota:
    """取额度行并**加行锁**（写路径专用）。

    「换账号不重置」是本域的硬不变量——若两个账号并发启动同一主体的诊断，
    无锁时二者都可能读到 ``granted`` 并各自写入绑定账号（后写者静默覆盖
    先写者＝额度被重发）。行锁把并发启动串行化：后到者读到已提交的
    ``in_progress`` 即被 409 ``quota_bound_to_other_account`` 拒。

    ``populate_existing`` 是必需项——本会话的 identity map 里可能还留着
    并发前的旧实例（``expire_on_commit=False`` 时属性不会自动过期）；
    缺了它，行锁只锁住行却不刷新内存视图，等于没锁（CR-021 同款教训：
    「锁在手读必为已提交真值」靠的是行锁＋刷新两者同时成立）。
    """
    statement = (
        select(EnterpriseFreeQuota)
        .where(EnterpriseFreeQuota.subject_key == subject_key)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    row = session.scalars(statement).first()
    if row is None:
        raise _error("quota_not_found", "该主体尚无免费额度记录。", 404)
    return row


def grant_or_get_quota(
    session: Session,
    *,
    actor: User,
    subject_key_raw: object,
    display_name: object,
    confirm_password: object,
) -> dict[str, Any]:
    """授予企业免费额度（admin+密码确认；**同主体幂等**——重复授予返回既有
    行绝不新建第二份，ADR-004 §1.2「一次一主体」）。"""
    _require_admin(actor)
    _confirm_password(session, actor, confirm_password)
    subject_key = normalize_subject_key(subject_key_raw)
    if not isinstance(display_name, str) or not display_name.strip() or len(display_name) > 160:
        raise _error("invalid_request", "display_name 必填且 ≤160 字符。")
    existing = session.get(EnterpriseQuotaSubject, subject_key)
    if existing is not None:
        quota = _require_quota(session, subject_key)
        return {"quota": serialize_quota(quota, existing), "changed": False}
    subject = EnterpriseQuotaSubject(
        subject_key=subject_key,
        display_name=display_name.strip(),
        first_user_id=actor.id,
    )
    session.add(subject)
    quota = EnterpriseFreeQuota(subject_key=subject_key, granted_by_user_id=actor.id)
    session.add(quota)
    session.flush()
    record_event(
        session,
        actor,
        "commercial_quota_granted",
        actor,
        {
            "request_id": str(uuid4()),
            "subject_key": subject_key,
            "display_name": subject.display_name,
        },
    )
    return {"quota": serialize_quota(quota, subject), "changed": True}


def start_diagnosis(session: Session, *, actor: User, subject_key_raw: object) -> dict[str, Any]:
    """启动免费诊断（当事人动作，事件留痕）：granted→in_progress 绑定账号。

    - completed → 409 ``quota_completed``（终态无重启路径，长期有效不重置）；
    - in_progress 且绑定他人 → 409 ``quota_bound_to_other_account``
      （**换账号不得重新开始**——反例用例的正面断言面）。
    """
    subject_key = normalize_subject_key(subject_key_raw)
    quota = _lock_quota(session, subject_key)
    if quota.state == "completed":
        raise _error("quota_completed", "该主体的免费诊断已完成，不能再次启动。", 409)
    if quota.state == "in_progress":
        if quota.bound_user_id == actor.id:
            return {"quota": serialize_quota(quota), "changed": False}
        raise _error(
            "quota_bound_to_other_account",
            "该主体的免费诊断已由其他账号启动，换账号不能重新获得。",
            409,
        )
    quota.state = "in_progress"
    quota.bound_user_id = actor.id
    quota.bound_at = datetime.now(timezone.utc)
    record_event(
        session,
        actor,
        "commercial_quota_started",
        actor,
        {"request_id": str(uuid4()), "subject_key": subject_key},
    )
    return {"quota": serialize_quota(quota), "changed": True}


def complete_diagnosis(
    session: Session,
    *,
    actor: User,
    subject_key_raw: object,
    deliverables: object,
    confirm_password: object,
) -> dict[str, Any]:
    """标记诊断完成（交付咨询环节治理写，admin+密码确认，ADR-007）。

    **恰好六键全真**（FREE_DIAGNOSIS_DELIVERABLES）方可完成：缺失/未真
    逐键点名 409 ``deliverables_incomplete``；多余键 400（闭集拒绝）。
    """
    _require_admin(actor)
    _confirm_password(session, actor, confirm_password)
    subject_key = normalize_subject_key(subject_key_raw)
    quota = _lock_quota(session, subject_key)
    if quota.state != "in_progress":
        raise _error(
            "quota_not_in_progress",
            "免费诊断尚未启动或已完成，不能标记完成。",
            409,
        )
    if not isinstance(deliverables, dict):
        raise _error("invalid_request", "deliverables 必须是对象。")
    extra = sorted(set(deliverables) - set(FREE_DIAGNOSIS_DELIVERABLES))
    if extra:
        raise _error("invalid_request", f"deliverables 含未知键：{', '.join(extra)}。")
    missing = sorted(
        key for key in FREE_DIAGNOSIS_DELIVERABLES if deliverables.get(key) is not True
    )
    if missing:
        raise _error(
            "deliverables_incomplete",
            "六项免费交付物未齐备：" + "、".join(missing) + "。",
            409,
        )
    quota.state = "completed"
    quota.completed_at = datetime.now(timezone.utc)
    quota.deliverables = {key: True for key in FREE_DIAGNOSIS_DELIVERABLES}
    record_event(
        session,
        actor,
        "commercial_quota_completed",
        actor,
        {
            "request_id": str(uuid4()),
            "subject_key": subject_key,
            "deliverables": dict(quota.deliverables),
        },
    )
    return {"quota": serialize_quota(quota), "changed": True}


def confirm_diagnosis(session: Session, *, actor: User, subject_key_raw: object) -> dict[str, Any]:
    """企业确认（**绑定账号本人**——admin 不得代企业确认，「企业自主选择
    不被取消」）：completed 且未确认 → 落确认留痕（终态）。"""
    subject_key = normalize_subject_key(subject_key_raw)
    quota = _lock_quota(session, subject_key)
    if quota.state != "completed" or quota.completed_at is None:
        raise _error(
            "quota_not_completed",
            "六项交付物完成并经交付咨询环节标记后，企业才能确认。",
            409,
        )
    if quota.enterprise_confirmed_at is not None:
        return {"quota": serialize_quota(quota), "changed": False}
    if quota.bound_user_id != actor.id:
        raise _error(
            "quota_confirm_forbidden",
            "只有启动该诊断的企业账号可以确认。",
            403,
        )
    quota.enterprise_confirmed_by_user_id = actor.id
    quota.enterprise_confirmed_at = datetime.now(timezone.utc)
    record_event(
        session,
        actor,
        "commercial_quota_confirmed",
        actor,
        {"request_id": str(uuid4()), "subject_key": subject_key},
    )
    return {"quota": serialize_quota(quota), "changed": True}


def assert_entry_scope_allows(entry: object, scope: object) -> str:
    """三入口隔离闸（任务书 §6 验收「创业者不能取到企业真实商机」）。

    企业入口＝真实业务问题；创业者＝模拟体验；交付者＝脱敏模拟项目考核。
    **非企业入口取用 ``real_business`` 即 403**（``trial_entry_scope_forbidden``）
    ——三入口隔离的结构性保证；商机归属与渠道保护本体归 G4（不在本轮）。

    返回规范化后的 scope（入参合法时）。
    """
    if not isinstance(entry, str) or entry not in FREE_TRIAL_ENTRIES:
        raise _error(
            "invalid_trial_entry",
            "体验入口必须是 " + "/".join(FREE_TRIAL_ENTRY_KEYS) + " 之一。",
        )
    allowed = FREE_TRIAL_ENTRIES[entry]["allowed_scopes"]
    if not isinstance(scope, str) or scope not in allowed:
        raise _error(
            "trial_entry_scope_forbidden",
            f"体验入口 {entry} 不得取用 {scope} 域（允许：" + "、".join(allowed) + "）。",
            403,
        )
    return scope


def check_experience_limit(kind: object, resource: object, used: int) -> None:
    """体验档上限判定（触限即受限：``used >= cap`` 拒绝，409）。

    **按资源分别计数**：``simulation_runs`` 与 ``mentor_sessions`` 是两个
    独立计数器，上限各取各的——不得用同一 ``used`` 同时比所有资源上限
    （否则一档的上限会误伤另一档的计数）。

    结构与数值落 ``EXPERIENCE_LIMITS``（保守占位缺省，试点前须填实数）；
    消费接线归 G6 三入口（ADR-004 §1.8 挂账）。
    """
    if not isinstance(kind, str) or kind not in EXPERIENCE_LIMIT_KINDS:
        raise _error(
            "invalid_experience_kind",
            "体验档必须是 founder/deliverer 之一。",
        )
    caps = EXPERIENCE_LIMITS[kind]
    if not isinstance(resource, str) or resource not in caps:
        raise _error(
            "invalid_experience_resource",
            "体验资源必须是 " + "/".join(sorted(caps)) + " 之一。",
        )
    if not isinstance(used, int) or isinstance(used, bool) or used < 0:
        raise _error("invalid_request", "used 必须是 ≥0 整数。")
    cap = caps[resource]
    if used >= cap:
        raise _error(
            "experience_limit_exceeded",
            f"体验档 {kind} 的 {resource} 已达上限（{cap}），不能再消耗。",
            409,
        )


def get_quota_view(session: Session, *, actor: User, subject_key_raw: object) -> dict[str, Any]:
    """读面：绑定账号本人或 admin；他人 403。"""
    subject_key = normalize_subject_key(subject_key_raw)
    quota = _require_quota(session, subject_key)
    if actor.role != ROLE_ADMIN and quota.bound_user_id != actor.id:
        raise _error("commercial_entitlement_forbidden", "只能查看本人主体的免费额度。", 403)
    subject = session.get(EnterpriseQuotaSubject, subject_key)
    return {"quota": serialize_quota(quota, subject)}


def free_diagnosis_profile() -> dict[str, Any]:
    """免费边界元数据（读面公开呈现：代码层+接口层同时可见，ADR-004 §1.6/1.7/1.8）。"""
    return {
        "deliverables": list(FREE_DIAGNOSIS_DELIVERABLES),
        "exclusions": list(FREE_EXCLUSIONS),
        "project_tiers": DIAGNOSIS_PROJECT_TIERS,
        "trial_entries": {
            key: {
                "label": spec["label"],
                "scope": spec["scope"],
                "allowed_scopes": list(spec["allowed_scopes"]),
                "description": spec["description"],
                "subject_key_required": spec["subject_key_required"],
                "experience_limit_kind": spec["experience_limit_kind"],
            }
            for key, spec in FREE_TRIAL_ENTRIES.items()
        },
        "experience_limits": EXPERIENCE_LIMITS,
        "experience_limits_placeholder": EXPERIENCE_LIMITS_PLACEHOLDER,
        "subject_key_rule": "18 位统一社会信用代码（GB 32100-2015 校验位）",
        "registration_entries": {
            role: dict(spec) for role, spec in REGISTRATION_ENTRIES.items()
        },
    }


def serialize_quota(
    row: EnterpriseFreeQuota,
    subject: EnterpriseQuotaSubject | None = None,
) -> dict[str, Any]:
    return {
        "subject_key": row.subject_key,
        "state": row.state,
        "granted_at": row.granted_at.isoformat() if row.granted_at else None,
        "bound_user_id": row.bound_user_id,
        "bound_at": row.bound_at.isoformat() if row.bound_at else None,
        "completed_at": row.completed_at.isoformat() if row.completed_at else None,
        "deliverables": dict(row.deliverables) if row.deliverables else None,
        "enterprise_confirmed_at": (
            row.enterprise_confirmed_at.isoformat() if row.enterprise_confirmed_at else None
        ),
        "subject_display_name": subject.display_name if subject else None,
    }


__all__ = [
    "CommercialServiceError",
    "assert_entry_scope_allows",
    "check_experience_limit",
    "complete_diagnosis",
    "confirm_diagnosis",
    "free_diagnosis_profile",
    "get_quota_view",
    "grant_or_get_quota",
    "normalize_subject_key",
    "serialize_quota",
    "start_diagnosis",
    "DIAGNOSIS_PROJECT_TIERS",
    "EXPERIENCE_LIMITS",
    "EXPERIENCE_LIMITS_PLACEHOLDER",
    "FREE_DIAGNOSIS_DELIVERABLES",
    "FREE_EXCLUSIONS",
    "FREE_TRIAL_ENTRIES",
    "FREE_TRIAL_ENTRY_KEYS",
]
