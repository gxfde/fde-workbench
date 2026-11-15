"""M3b 批次 ②（商业域 43 端点）越权与留痕套件。

依据：《M3a-隔离入口与装饰器扩展规格-v1》§3（服务层校验／fail-closed／
跨 org 留痕 §3.4／失败码闭集 §3.5／逐批验证方法 §3.6）＋ 2026-11-11 拍板
（留痕触发面＝**企业 org 之间才算**；read-only 核验＝域级代表性用例进 CI）。

覆盖面＝《全局面盘点表》② 商业域 43 条（27 写面＋16 读面）：

- **本批唯一实改面＝共享事件记录器单点接线**（``projects/events.py::record_event``）：
  目标为**用户**且 actor 作用于**别家企业**账号 ⇒ 事件名带 ``cross_org_``
  前缀且 ``org_id`` 取被作用账号归属（规格 §3.4）。商业域 admin 代操作面
  （角色分层／席位激活／认证判定／交付资格／培训授予）**零调用点改动即接线**；
  平台身份目标判定恒 False ⇒ 存量事件名逐字节不变（零回归）。
- **R1 admin-only 保持**：企业身份打商业治理面 ⇒ 403 ``commercial_admin_required``。
- **R3 主体归属**：自助面（额度启动／确认／付费选项／商机报备·撤回／
  权益读面）只认当事人本人；跨企业一律 403/404（不确认主体存在）。
- **读面收敛核验**：域级代表用例（企业空间读面、商机列表、权益读面）。

**机器判定的人工纠正（诚实留痕）**：盘点表把 ``POST /api/v1/mailing/sns/events``
列为「R1 admin-only 保持」属机器误判——该端点是 **SES 回调服务间面**（SNS
服务器不可能携带工作台 JWT；鉴权＝签名校验＋TopicArn 白名单，见
``mailing/routes.py`` 模块 docstring），其隔离面由既有 ``test_mailing_ses.py``
覆盖（坏签名／外来证书 URL／错误 Topic 三连），本批只核验不重复造例；
同域 ``diagnostics`` 四条是**公网免注册写面**（部署闸默认关 ⇒ 404），
其隔离面由既有 ``test_diagnostics_mvp.py`` 覆盖。
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import select

from fde_api.auth.tokens import issue_access_token
from fde_api.commercial.models import (
    CommercialEntitlement,
    EnterpriseFreeQuota,
    EnterpriseQuotaSubject,
)
from fde_api.workbench.models import OperationEvent

from conftest import INITIAL_PASSWORD
from multi_tenant_harness import make_enterprise_org, make_user

# GB 32100 mod-31（与 ``commercial/quota_service.py`` 同算法——测试侧独立实现
# 一份，避免「用被测实现造被测输入」的自证循环）
_USCC_CHARS = "0123456789ABCDEFGHJKLMNPQRTUWXY"
_USCC_WEIGHTS = (1, 3, 9, 27, 19, 26, 16, 17, 20, 29, 25, 13, 8, 24, 10, 30, 28)


def _uscc(body17: str) -> str:
    """补全 18 位统一社会信用代码的 mod-31 校验位（body17＝前 17 位）。"""
    body = body17.upper()
    assert len(body) == 17
    total = sum(_USCC_CHARS.index(body[i]) * w for i, w in enumerate(_USCC_WEIGHTS))
    return body + _USCC_CHARS[(31 - total % 31) % 31]


def _auth(user, settings) -> dict[str, str]:
    return {"Authorization": f"Bearer {issue_access_token(user, settings)}"}


def _quota(
    db_session,
    *,
    subject_key: str,
    owner,
    bound_user,
    state: str = "in_progress",
) -> EnterpriseFreeQuota:
    """造一条主体额度行（直写模型＝被测路径之外的夹具，不走业务原语）。"""
    subject = EnterpriseQuotaSubject(
        subject_key=subject_key,
        display_name=f"隔离用例主体·{subject_key[-4:]}",
        first_user_id=owner.id,
        problem_description="隔离用例主体问题描述",
    )
    db_session.add(subject)
    quota = EnterpriseFreeQuota(
        subject_key=subject_key,
        state=state,
        granted_by_user_id=owner.id,
        bound_user_id=bound_user.id,
        bound_at=datetime.now(UTC),
        completed_at=datetime.now(UTC) if state == "completed" else None,
    )
    db_session.add(quota)
    db_session.commit()
    return quota


def _active_seat(db_session, user) -> CommercialEntitlement:
    """给账号一条生效席位（商机报备资格闸：缴费或席位 active 任一即可）。"""
    row = CommercialEntitlement(
        user_id=user.id,
        seat_status="active",
        seat_source="first_delivery",
        seat_activated_at=datetime.now(UTC),
        seat_expires_at=datetime(2027, 12, 31, tzinfo=UTC),
    )
    db_session.add(row)
    db_session.commit()
    return row


def _events(db_session, actor, target_id: str) -> list[OperationEvent]:
    return list(
        db_session.scalars(
            select(OperationEvent)
            .where(
                OperationEvent.actor_user_id == actor.id,
                OperationEvent.target_type == "user",
                OperationEvent.target_id == target_id,
            )
            .order_by(OperationEvent.created_at, OperationEvent.id)
        ).all()
    )


# ---------------------------------------------------------------------------
# A. 跨 org 留痕（规格 §3.4；本批实改面＝共享事件记录器单点接线）
# ---------------------------------------------------------------------------


def test_admin_cross_org_commercial_role_leaves_cross_org_event(
    client, db_session, settings
):
    """admin 代改**别家企业**账号角色分层 ⇒ ``cross_org_`` 前缀＋org 维度。"""
    admin = make_user(db_session, "admin")
    org_b = make_enterprise_org(db_session)
    user_b = make_user(db_session, "viewer", org_id=org_b.id)

    response = client.post(
        f"/api/v1/admin/commercial/users/{user_b.id}/role",
        json={"role": "R1", "confirm_password": INITIAL_PASSWORD},
        headers=_auth(admin, settings),
    )
    assert response.status_code == 200, response.get_data(as_text=True)

    events = _events(db_session, admin, user_b.id)
    assert [event.event_type for event in events] == [
        "cross_org_commercial_role_changed"
    ], "跨 org 代操作未留痕（缺 cross_org_ 前缀事件）"
    assert events[0].org_id == org_b.id, "跨 org 事件的 org 维度须取被作用账号归属"
    assert events[0].changes["target_user_id"] == user_b.id


def test_admin_cross_org_entitlement_writes_leave_cross_org_events(
    client, db_session, settings
):
    """admin 代改**别家企业**账号席位／认证／交付资格 ⇒ 三个前缀事件同族。"""
    admin = make_user(db_session, "admin")
    org_b = make_enterprise_org(db_session)
    user_b = make_user(db_session, "viewer", org_id=org_b.id)
    headers = _auth(admin, settings)

    seat = client.post(
        f"/api/v1/admin/commercial/users/{user_b.id}/seat-activation",
        json={
            "seat_source": "first_delivery",
            "expires_at": "2027-12-31T00:00:00Z",
            "confirm_password": INITIAL_PASSWORD,
        },
        headers=headers,
    )
    assert seat.status_code == 200, seat.get_data(as_text=True)
    certification = client.post(
        f"/api/v1/admin/commercial/users/{user_b.id}/certification",
        json={
            "certified": True,
            "source": "probe-pointer",
            "confirm_password": INITIAL_PASSWORD,
        },
        headers=headers,
    )
    assert certification.status_code == 200, certification.get_data(as_text=True)
    eligibility = client.post(
        f"/api/v1/admin/commercial/users/{user_b.id}/delivery-eligibility",
        json={"eligibility": "eligible", "confirm_password": INITIAL_PASSWORD},
        headers=headers,
    )
    assert eligibility.status_code == 200, eligibility.get_data(as_text=True)

    events = _events(db_session, admin, user_b.id)
    assert {event.event_type for event in events} == {
        "cross_org_commercial_seat_activated",
        "cross_org_commercial_certification_changed",
        "cross_org_commercial_delivery_eligibility_changed",
    }
    assert all(event.org_id == org_b.id for event in events)


def test_admin_cross_org_training_grant_leaves_cross_org_event(
    client, db_session, settings
):
    """admin 代授**别家企业**账号培训权益 ⇒ ``cross_org_`` 前缀事件。"""
    admin = make_user(db_session, "admin")
    org_b = make_enterprise_org(db_session)
    user_b = make_user(db_session, "viewer", org_id=org_b.id)

    response = client.post(
        f"/api/v1/admin/commercial/users/{user_b.id}/training",
        json={"item_type": "training", "confirm_password": INITIAL_PASSWORD},
        headers=_auth(admin, settings),
    )
    assert response.status_code == 200, response.get_data(as_text=True)

    events = _events(db_session, admin, user_b.id)
    assert [event.event_type for event in events] == [
        "cross_org_commercial_training_granted"
    ]
    assert events[0].org_id == org_b.id


def test_admin_platform_target_commercial_event_names_unchanged(
    client, db_session, settings
):
    """admin 改**平台身份**账号 ⇒ 事件名逐字节不变、org 维度为空（零回归钉）。"""
    admin = make_user(db_session, "admin")
    user_p = make_user(db_session, "viewer")

    response = client.post(
        f"/api/v1/admin/commercial/users/{user_p.id}/role",
        json={"role": "R1", "confirm_password": INITIAL_PASSWORD},
        headers=_auth(admin, settings),
    )
    assert response.status_code == 200, response.get_data(as_text=True)

    events = _events(db_session, admin, user_p.id)
    assert [event.event_type for event in events] == ["commercial_role_changed"]
    assert all(event.org_id is None for event in events)


def test_same_enterprise_admin_action_is_not_cross_org(client, db_session, settings):
    """拍板口径＝**企业 org 之间才算**：同企业内 admin 代操作 ⇒ 不算跨 org。"""
    org_a = make_enterprise_org(db_session)
    admin_a = make_user(db_session, "admin", org_id=org_a.id)
    user_a = make_user(db_session, "viewer", org_id=org_a.id)

    response = client.post(
        f"/api/v1/admin/commercial/users/{user_a.id}/role",
        json={"role": "R1", "confirm_password": INITIAL_PASSWORD},
        headers=_auth(admin_a, settings),
    )
    assert response.status_code == 200, response.get_data(as_text=True)

    events = _events(db_session, admin_a, user_a.id)
    assert [event.event_type for event in events] == ["commercial_role_changed"]
    assert all(event.org_id is None for event in events)


def test_cross_enterprise_admin_action_leaves_cross_org_event(
    client, db_session, settings
):
    """拍板口径＝**企业 org 之间才算**：企业甲 admin 作用于企业乙账号 ⇒ 算。"""
    org_a = make_enterprise_org(db_session)
    org_b = make_enterprise_org(db_session)
    admin_a = make_user(db_session, "admin", org_id=org_a.id)
    user_b = make_user(db_session, "viewer", org_id=org_b.id)

    response = client.post(
        f"/api/v1/admin/commercial/users/{user_b.id}/role",
        json={"role": "R1", "confirm_password": INITIAL_PASSWORD},
        headers=_auth(admin_a, settings),
    )
    assert response.status_code == 200, response.get_data(as_text=True)

    events = _events(db_session, admin_a, user_b.id)
    assert [event.event_type for event in events] == [
        "cross_org_commercial_role_changed"
    ]
    assert events[0].org_id == org_b.id


# ---------------------------------------------------------------------------
# B. R1：admin-only 保持（企业身份不得进入商业治理面）
# ---------------------------------------------------------------------------


def test_enterprise_identity_blocked_from_commercial_governance_writes(
    client, db_session, settings
):
    """企业身份 ⇒ 商业治理写面全 403（``commercial_admin_required``）。"""
    org_a = make_enterprise_org(db_session)
    user_a = make_user(db_session, "viewer", org_id=org_a.id)
    headers = _auth(user_a, settings)
    paths = [
        "/api/v1/admin/commercial/fee-configs/enterprise_certification_fee",
        "/api/v1/admin/commercial/split-rules",
        "/api/v1/admin/commercial/revenue-ledger",
        "/api/v1/admin/commercial/opportunity-rules/protection_days",
        f"/api/v1/admin/commercial/opportunities/{uuid4()}/attribution/reassign",
        f"/api/v1/admin/commercial/opportunities/{uuid4()}/customer-choice",
        f"/api/v1/admin/commercial/opportunities/{uuid4()}/dispute",
        f"/api/v1/admin/commercial/opportunities/{uuid4()}/protection",
        f"/api/v1/admin/commercial/opportunities/{uuid4()}/protection/renew",
        f"/api/v1/admin/commercial/regional-partners/{uuid4()}/promote",
        "/api/v1/admin/commercial/regional-sale-gate/conditions/disclosure",
        "/api/v1/admin/commercial/regional-sale-gate/open",
    ]
    for path in paths:
        response = client.post(path, json={}, headers=headers)
        assert response.status_code == 403, (path, response.status_code)
        assert response.get_json()["error"]["code"] == "commercial_admin_required", path


def test_enterprise_identity_blocked_from_commercial_admin_user_writes(
    client, db_session, settings
):
    """企业身份 ⇒ 商业 admin 用户面（代操作六端点）全 403。"""
    org_a = make_enterprise_org(db_session)
    user_a = make_user(db_session, "viewer", org_id=org_a.id)
    user_b = make_user(db_session, "viewer")
    headers = _auth(user_a, settings)
    paths = [
        f"/api/v1/admin/commercial/users/{user_b.id}/role",
        f"/api/v1/admin/commercial/users/{user_b.id}/seat-activation",
        f"/api/v1/admin/commercial/users/{user_b.id}/certification",
        f"/api/v1/admin/commercial/users/{user_b.id}/delivery-eligibility",
        f"/api/v1/admin/commercial/users/{user_b.id}/training",
        f"/api/v1/admin/commercial/users/{user_b.id}/training/{uuid4()}/revoke",
    ]
    for path in paths:
        response = client.post(path, json={}, headers=headers)
        assert response.status_code == 403, (path, response.status_code)
        assert response.get_json()["error"]["code"] == "commercial_admin_required", path


# ---------------------------------------------------------------------------
# C. R3：主体归属（跨企业一律 403/404，不确认主体存在）
# ---------------------------------------------------------------------------


def test_cross_enterprise_space_read_returns_not_found(client, db_session, settings):
    """企业甲账号读企业乙的企业空间 ⇒ 404（CR-062：不透主体存在性）。"""
    org_a = make_enterprise_org(db_session)
    org_b = make_enterprise_org(db_session)
    user_a = make_user(db_session, "viewer", org_id=org_a.id)
    user_b = make_user(db_session, "viewer", org_id=org_b.id)
    subject_key = _uscc("91350100M000200Y4")
    _quota(db_session, subject_key=subject_key, owner=user_b, bound_user=user_b)

    response = client.get(
        f"/api/v1/commercial/enterprise-spaces/{subject_key}",
        headers=_auth(user_a, settings),
    )
    assert response.status_code == 404, response.get_data(as_text=True)
    assert response.get_json()["error"]["code"] == "enterprise_space_not_found"


def test_cross_enterprise_paid_option_choice_forbidden(client, db_session, settings):
    """企业甲账号为企业乙主体选付费选项 ⇒ 403（只认绑定账号本人）。"""
    org_a = make_enterprise_org(db_session)
    org_b = make_enterprise_org(db_session)
    user_a = make_user(db_session, "viewer", org_id=org_a.id)
    user_b = make_user(db_session, "viewer", org_id=org_b.id)
    subject_key = _uscc("91350100M000201Y4")
    _quota(
        db_session,
        subject_key=subject_key,
        owner=user_b,
        bound_user=user_b,
        state="completed",
    )

    response = client.post(
        f"/api/v1/commercial/enterprise-spaces/{subject_key}/paid-option-choices",
        json={"option_key": "standardized", "request_id": f"m3b-{uuid4().hex[:8]}"},
        headers=_auth(user_a, settings),
    )
    assert response.status_code == 403, response.get_data(as_text=True)
    assert response.get_json()["error"]["code"] == "enterprise_choice_forbidden"


def test_cross_enterprise_quota_start_and_confirm_forbidden(client, db_session, settings):
    """企业甲账号启动／确认企业乙的额度 ⇒ 409／403（换账号不重置·不得代确认）。"""
    org_a = make_enterprise_org(db_session)
    org_b = make_enterprise_org(db_session)
    user_a = make_user(db_session, "viewer", org_id=org_a.id)
    user_b = make_user(db_session, "viewer", org_id=org_b.id)
    admin = make_user(db_session, "admin")
    subject_key = _uscc("91350100M000202Y4")
    _quota(db_session, subject_key=subject_key, owner=user_b, bound_user=user_b)

    started = client.post(
        f"/api/v1/commercial/enterprise-quota/{subject_key}/start",
        json={},
        headers=_auth(user_a, settings),
    )
    assert started.status_code == 409, started.get_data(as_text=True)
    assert (
        started.get_json()["error"]["code"] == "quota_bound_to_other_account"
    )

    _quota(
        db_session,
        subject_key=_uscc("91350100M000203Y4"),
        owner=user_b,
        bound_user=user_b,
        state="completed",
    )
    completed_key = _uscc("91350100M000203Y4")
    confirmed = client.post(
        f"/api/v1/commercial/enterprise-quota/{completed_key}/confirm",
        json={},
        headers=_auth(user_a, settings),
    )
    assert confirmed.status_code == 403, confirmed.get_data(as_text=True)
    assert confirmed.get_json()["error"]["code"] == "quota_confirm_forbidden"

    admin_confirm = client.post(
        f"/api/v1/commercial/enterprise-quota/{completed_key}/confirm",
        json={},
        headers=_auth(admin, settings),
    )
    assert admin_confirm.status_code == 403, admin_confirm.get_data(as_text=True)
    assert admin_confirm.get_json()["error"]["code"] == "quota_confirm_forbidden"


def test_cross_enterprise_opportunity_withdraw_forbidden(client, db_session, settings):
    """企业甲账号撤回企业乙报备的商机 ⇒ 403（只有报备人本人可撤回）。"""
    org_a = make_enterprise_org(db_session)
    org_b = make_enterprise_org(db_session)
    user_a = make_user(db_session, "viewer", org_id=org_a.id)
    user_b = make_user(db_session, "viewer", org_id=org_b.id)
    _active_seat(db_session, user_b)

    reported = client.post(
        "/api/v1/commercial/opportunities",
        json={
            "enterprise_code": "隔离用例企业代号",
            "title": "隔离用例商机标题",
            "note": "隔离用例商机备注",
            "source_uri": "pointer://m3b/opportunity",
            "content_hash": "a" * 64,
        },
        headers=_auth(user_b, settings),
    )
    assert reported.status_code == 200, reported.get_data(as_text=True)
    opportunity_id = reported.get_json()["data"]["opportunity"]["id"]

    withdrawn = client.post(
        f"/api/v1/commercial/opportunities/{opportunity_id}/withdraw",
        json={},
        headers=_auth(user_a, settings),
    )
    assert withdrawn.status_code == 403, withdrawn.get_data(as_text=True)
    assert withdrawn.get_json()["error"]["code"] == "opportunity_forbidden"


def test_cross_enterprise_entitlement_read_forbidden(client, db_session, settings):
    """企业甲账号读企业乙的商业权益 ⇒ 403（读面＝本人或 admin）。"""
    org_a = make_enterprise_org(db_session)
    org_b = make_enterprise_org(db_session)
    user_a = make_user(db_session, "viewer", org_id=org_a.id)
    user_b = make_user(db_session, "viewer", org_id=org_b.id)

    response = client.get(
        f"/api/v1/commercial/entitlements/{user_b.id}",
        headers=_auth(user_a, settings),
    )
    assert response.status_code == 403, response.get_data(as_text=True)
    assert (
        response.get_json()["error"]["code"] == "commercial_entitlement_forbidden"
    )


# ---------------------------------------------------------------------------
# D. 读面收敛核验（域级代表用例）
# ---------------------------------------------------------------------------


def test_opportunity_list_scoped_to_reporter(client, db_session, settings):
    """商机列表：本人只见自己报备的（他人行不外泄）。"""
    org_a = make_enterprise_org(db_session)
    org_b = make_enterprise_org(db_session)
    user_a = make_user(db_session, "viewer", org_id=org_a.id)
    user_b = make_user(db_session, "viewer", org_id=org_b.id)
    _active_seat(db_session, user_b)

    reported = client.post(
        "/api/v1/commercial/opportunities",
        json={
            "enterprise_code": "隔离用例企业代号",
            "title": "隔离用例商机标题",
            "source_uri": "pointer://m3b/opportunity-list",
            "content_hash": "b" * 64,
        },
        headers=_auth(user_b, settings),
    )
    assert reported.status_code == 200, reported.get_data(as_text=True)
    opportunity_id = reported.get_json()["data"]["opportunity"]["id"]

    listed_a = client.get(
        "/api/v1/commercial/opportunities", headers=_auth(user_a, settings)
    ).get_json()
    ids_a = {item["id"] for item in listed_a["data"]["opportunities"]}
    assert opportunity_id not in ids_a

    listed_b = client.get(
        "/api/v1/commercial/opportunities", headers=_auth(user_b, settings)
    ).get_json()
    ids_b = {item["id"] for item in listed_b["data"]["opportunities"]}
    assert opportunity_id in ids_b
