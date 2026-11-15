"""M6-1 轮：商业域读面 **org 归属隔离** 跨 org 隔离套件。

依据：《多客户工作平台-leader 任务书 v1》§14 M6 行（**验收未完成不打勾**）、
OWNER 2026-11-12 拍板（① 主体归属走 ``user.org_id`` 间接归属＝**零迁移零新表
零新列零新路由**；② 可见性模式沿用 M5 已落模式「本 org 成员或 admin」；
③ G2 额度去重主体仍是 USCC 单键，org 只是**可见性/隔离维度**；④ M3a 隔离
入口语义；⑤ CR-062 商业域读面对「他人」一律 404；⑥ admin 跨 org 代操作仍是
admin 行为＋留痕）。

**本轮实改面＝商业域读面的 org 归属判定接线**（``commercial/org_read_scope.py``
单一 helper ＋ 六个读面接线）。覆盖面：

- **G3 科目层**（``list_revenue_entries``／``get_revenue_entry``／
  ``reconcile_revenue``）：企业身份读别家企业科目行 ⇒ 404（不确认存在性）；
- **G1 权益面**（``get_entitlement_for_view``）／**G3 认证记录面**
  （``list_certification_records``）：企业身份读别家企业账号 ⇒ 403（沿用既有码）；
- **G4 商机面**（``list_opportunities``）：企业身份列表**不含别家企业**的商机；
- **G2 额度账／企业空间面**：**现状核实**（CR-062 的「绑定账号本人或 admin」
  判定天然比 org 维度更严 ⇒ 本轮不改，见 M6 验收对照表）。

**零回归钉**（M1 拍板「存量用户不回填」）：``org_id IS NULL`` 的**平台身份**
用户读面行为**逐位不变**（沿用既有码，不被新判定改写）。

**变异可辨**：本文件断言均针对**新增的 org 判定**（摘除式变异 ⇒ 用例转红，
见 ``docs/commercialization/multi-tenant/M6-验收对照-v1.md`` 的变异证据表）。
"""
from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import select

from fde_api.auth.tokens import issue_access_token
from fde_api.commercial.models import (
    CommercialCertificationRecord,
    CommercialEntitlement,
    CommercialRevenueLedger,
    EnterpriseFreeQuota,
    EnterpriseQuotaSubject,
)
from fde_api.orgs.models import ORG_TYPE_ENTERPRISE, Org
from fde_api.workbench.models import OperationEvent

from conftest import INITIAL_PASSWORD
from multi_tenant_harness import make_enterprise_org, make_user

# GB 32100 mod-31（测试侧独立实现一份——避免「用被测实现造被测输入」的自证循环）
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


def _enterprise_org_for_subject(db_session, subject_key: str, creator) -> Org:
    """建一个**挂主体键**的企业 org（G2 主体 → org 的可见性推导依据）。

    口径并置（拍板③）：**去重维度仍是 USCC 单键**（``enterprise_quota_subjects``
    的 PK），本函数只补 org 与主体的**可见性**关联（``orgs.subject_key``），
    **不改**去重口径。
    """
    org = Org(
        org_type=ORG_TYPE_ENTERPRISE,
        name=f"隔离用例企业·{uuid4().hex[:8]}",
        subject_key=subject_key,
        created_by_user_id=creator.id,
    )
    db_session.add(org)
    db_session.commit()
    return org


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


def _ledger_entry(
    db_session,
    *,
    subject_user_id: str,
    recorded_by_user_id: str,
    subject_type: str = "seat_fee",
) -> CommercialRevenueLedger:
    """造一条科目行（直写模型＝被测路径之外的夹具）。

    归属推导走 ``subject_user_id`` → ``users.org_id``（拍板①：零新增列）。
    """
    entry = CommercialRevenueLedger(
        subject_type=subject_type,
        line_item="software_subscription",
        status="recorded",
        amount="3980.00",
        subject_user_id=subject_user_id,
        package_code="bootcamp_practical",
        recorded_by_user_id=recorded_by_user_id,
        occurred_at=datetime.now(UTC),
    )
    db_session.add(entry)
    db_session.commit()
    return entry


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
# A. G3 科目层：跨 org 读 ⇒ 404（不确认资源存在）
# ---------------------------------------------------------------------------


def test_cross_enterprise_revenue_entry_list_hides_other_org_rows(
    client, db_session, settings
):
    """企业甲账号读科目列表 ⇒ **不含**企业乙的科目行（列表级 org 谓词下推）。"""
    org_a = make_enterprise_org(db_session)
    org_b = make_enterprise_org(db_session)
    user_a = make_user(db_session, "viewer", org_id=org_a.id)
    user_b = make_user(db_session, "viewer", org_id=org_b.id)
    entry_b = _ledger_entry(
        db_session, subject_user_id=user_b.id, recorded_by_user_id=user_b.id
    )
    entry_a = _ledger_entry(
        db_session, subject_user_id=user_a.id, recorded_by_user_id=user_a.id
    )

    response = client.get(
        "/api/v1/commercial/revenue-ledger", headers=_auth(user_a, settings)
    )
    assert response.status_code == 200, response.get_data(as_text=True)
    ids = {item["id"] for item in response.get_json()["data"]["entries"]}
    assert entry_b.id not in ids, "别家企业的科目行外泄到企业甲的科目列表"
    assert entry_a.id in ids, "本企业账号的科目行应可见"


def test_cross_enterprise_revenue_entry_read_returns_not_found(
    client, db_session, settings
):
    """企业甲账号读企业乙的**单条科目** ⇒ 404（不确认资源存在）。"""
    org_a = make_enterprise_org(db_session)
    org_b = make_enterprise_org(db_session)
    user_a = make_user(db_session, "viewer", org_id=org_a.id)
    user_b = make_user(db_session, "viewer", org_id=org_b.id)
    entry_b = _ledger_entry(
        db_session, subject_user_id=user_b.id, recorded_by_user_id=user_b.id
    )

    response = client.get(
        f"/api/v1/commercial/revenue-ledger/{entry_b.id}",
        headers=_auth(user_a, settings),
    )
    assert response.status_code == 404, response.get_data(as_text=True)
    assert response.get_json()["error"]["code"] == "revenue_entry_not_found"


def test_cross_enterprise_revenue_entry_probe_is_indistinguishable(
    client, db_session, settings
):
    """**探测不可分辨**：跨 org 读「存在的行」与「不存在的行」错误载荷逐位一致。"""
    org_a = make_enterprise_org(db_session)
    org_b = make_enterprise_org(db_session)
    user_a = make_user(db_session, "viewer", org_id=org_a.id)
    user_b = make_user(db_session, "viewer", org_id=org_b.id)
    entry_b = _ledger_entry(
        db_session, subject_user_id=user_b.id, recorded_by_user_id=user_b.id
    )

    existent = client.get(
        f"/api/v1/commercial/revenue-ledger/{entry_b.id}",
        headers=_auth(user_a, settings),
    )
    missing = client.get(
        f"/api/v1/commercial/revenue-ledger/ghost-{uuid4().hex}",
        headers=_auth(user_a, settings),
    )
    assert existent.status_code == missing.status_code == 404
    assert existent.get_json()["error"] == missing.get_json()["error"], (
        "跨 org 存在性被泄露（存在与不存在的错误载荷不一致）"
    )


def test_cross_enterprise_revenue_entry_filter_returns_not_found(
    client, db_session, settings
):
    """企业甲账号按企业乙的账号**筛选**科目列表 ⇒ 404（不确认主体存在）。"""
    org_a = make_enterprise_org(db_session)
    org_b = make_enterprise_org(db_session)
    user_a = make_user(db_session, "viewer", org_id=org_a.id)
    user_b = make_user(db_session, "viewer", org_id=org_b.id)

    response = client.get(
        f"/api/v1/commercial/revenue-ledger?subject_user_id={user_b.id}",
        headers=_auth(user_a, settings),
    )
    assert response.status_code == 404, response.get_data(as_text=True)
    assert response.get_json()["error"]["code"] == "revenue_entry_not_found"


def test_cross_enterprise_revenue_reconciliation_returns_not_found(
    client, db_session, settings
):
    """企业甲账号按企业乙的账号**对账** ⇒ 404（不确认主体存在）。"""
    org_a = make_enterprise_org(db_session)
    org_b = make_enterprise_org(db_session)
    user_a = make_user(db_session, "viewer", org_id=org_a.id)
    user_b = make_user(db_session, "viewer", org_id=org_b.id)

    response = client.get(
        f"/api/v1/commercial/revenue-ledger/reconciliation?subject_user_id={user_b.id}",
        headers=_auth(user_a, settings),
    )
    assert response.status_code == 404, response.get_data(as_text=True)
    assert response.get_json()["error"]["code"] == "revenue_entry_not_found"


# ---------------------------------------------------------------------------
# B. G1 权益面 / G3 认证记录面：跨 org 读 ⇒ 403（沿用既有码）
# ---------------------------------------------------------------------------


def test_cross_enterprise_entitlement_read_forbidden(client, db_session, settings):
    """企业甲账号读企业乙的**商业权益** ⇒ 403（沿用既有既有码，不自造）。"""
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


def test_cross_enterprise_certification_records_read_forbidden(
    client, db_session, settings
):
    """企业甲账号读企业乙的**认证记录** ⇒ 403（沿用既有码）。"""
    org_a = make_enterprise_org(db_session)
    org_b = make_enterprise_org(db_session)
    user_a = make_user(db_session, "viewer", org_id=org_a.id)
    user_b = make_user(db_session, "viewer", org_id=org_b.id)

    response = client.get(
        f"/api/v1/commercial/certification-records/{user_b.id}",
        headers=_auth(user_a, settings),
    )
    assert response.status_code == 403, response.get_data(as_text=True)
    assert (
        response.get_json()["error"]["code"]
        == "commercial_certification_forbidden"
    )


# ---------------------------------------------------------------------------
# C. G4 商机面：企业身份列表不含别家企业商机
# ---------------------------------------------------------------------------


def test_cross_enterprise_opportunity_list_excludes_other_org(
    client, db_session, settings
):
    """企业甲账号读商机列表 ⇒ **不含**企业乙报备的商机（SQL 下推 org 谓词）。"""
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
            "source_uri": "pointer://m6/opportunity-list",
            "content_hash": "c" * 64,
        },
        headers=_auth(user_b, settings),
    )
    assert reported.status_code == 200, reported.get_data(as_text=True)
    opportunity_id = reported.get_json()["data"]["opportunity"]["id"]

    listed = client.get(
        "/api/v1/commercial/opportunities", headers=_auth(user_a, settings)
    )
    assert listed.status_code == 200, listed.get_data(as_text=True)
    ids = {item["id"] for item in listed.get_json()["data"]["opportunities"]}
    assert opportunity_id not in ids, "别家企业的商机外泄到企业甲的商机列表"


# ---------------------------------------------------------------------------
# D. 同企业成员互相可见（M5 已落模式「本 org 成员或 admin」）
# ---------------------------------------------------------------------------


def test_same_enterprise_two_accounts_see_each_other(
    client, db_session, settings
):
    """**同企业**两个账号互相可见（科目层）——M5 已落模式的企业空间读面口径。"""
    org_a = make_enterprise_org(db_session)
    user_a = make_user(db_session, "viewer", org_id=org_a.id)
    user_a2 = make_user(db_session, "viewer", org_id=org_a.id)
    entry_a = _ledger_entry(
        db_session, subject_user_id=user_a.id, recorded_by_user_id=user_a.id
    )

    listed = client.get(
        "/api/v1/commercial/revenue-ledger", headers=_auth(user_a2, settings)
    )
    assert listed.status_code == 200, listed.get_data(as_text=True)
    ids = {item["id"] for item in listed.get_json()["data"]["entries"]}
    assert entry_a.id in ids, "同企业成员看不到本企业同事的科目行"

    detail = client.get(
        f"/api/v1/commercial/revenue-ledger/{entry_a.id}",
        headers=_auth(user_a2, settings),
    )
    assert detail.status_code == 200, detail.get_data(as_text=True)


def test_same_enterprise_entitlement_read_succeeds(client, db_session, settings):
    """同企业成员读同企业账号的**商业权益** ⇒ 200（M5 模式）。"""
    org_a = make_enterprise_org(db_session)
    user_a = make_user(db_session, "viewer", org_id=org_a.id)
    user_a2 = make_user(db_session, "viewer", org_id=org_a.id)

    response = client.get(
        f"/api/v1/commercial/entitlements/{user_a.id}",
        headers=_auth(user_a2, settings),
    )
    assert response.status_code == 200, response.get_data(as_text=True)


# ---------------------------------------------------------------------------
# E. 平台身份存量用户零回归（M1 拍板「存量用户不回填」）
# ---------------------------------------------------------------------------


def test_platform_identity_user_reads_own_ledger_entries(
    client, db_session, settings
):
    """``org_id IS NULL`` 的**平台身份**用户读本人科目行 ⇒ 200（零回归）。"""
    user_p = make_user(db_session, "viewer")
    assert user_p.org_id is None, "夹具前提：平台身份（org_id IS NULL）"
    entry_p = _ledger_entry(
        db_session, subject_user_id=user_p.id, recorded_by_user_id=user_p.id
    )

    response = client.get(
        "/api/v1/commercial/revenue-ledger", headers=_auth(user_p, settings)
    )
    assert response.status_code == 200, response.get_data(as_text=True)
    ids = {item["id"] for item in response.get_json()["data"]["entries"]}
    assert entry_p.id in ids


def test_platform_identity_user_reading_other_stays_existing_403(
    client, db_session, settings
):
    """**平台身份**读他人科目行 ⇒ 仍 403（既有码逐位不变，不被新判定改写）。"""
    user_p = make_user(db_session, "viewer")
    user_q = make_user(db_session, "viewer")
    entry_q = _ledger_entry(
        db_session, subject_user_id=user_q.id, recorded_by_user_id=user_q.id
    )

    response = client.get(
        f"/api/v1/commercial/revenue-ledger/{entry_q.id}",
        headers=_auth(user_p, settings),
    )
    assert response.status_code == 403, response.get_data(as_text=True)
    assert response.get_json()["error"]["code"] == "commercial_ledger_forbidden"


def test_platform_identity_user_reading_other_entitlement_stays_403(
    client, db_session, settings
):
    """**平台身份**读他人权益 ⇒ 仍 403（存量口径逐位不变）。"""
    user_p = make_user(db_session, "viewer")
    user_q = make_user(db_session, "viewer")

    response = client.get(
        f"/api/v1/commercial/entitlements/{user_q.id}",
        headers=_auth(user_p, settings),
    )
    assert response.status_code == 403, response.get_data(as_text=True)
    assert (
        response.get_json()["error"]["code"] == "commercial_entitlement_forbidden"
    )


# ---------------------------------------------------------------------------
# F. admin 全量（拍板⑥：admin 跨 org 仍是 admin 行为 ＋ 留痕）
# ---------------------------------------------------------------------------


def test_admin_sees_all_orgs_ledger_entries(client, db_session, settings):
    """admin 读科目列表 ⇒ **仍见**别家企业的行（平台能力逐位不变）。"""
    org_a = make_enterprise_org(db_session)
    org_b = make_enterprise_org(db_session)
    user_a = make_user(db_session, "viewer", org_id=org_a.id)
    user_b = make_user(db_session, "viewer", org_id=org_b.id)
    admin = make_user(db_session, "admin")
    entry_a = _ledger_entry(
        db_session, subject_user_id=user_a.id, recorded_by_user_id=user_a.id
    )
    entry_b = _ledger_entry(
        db_session, subject_user_id=user_b.id, recorded_by_user_id=user_b.id
    )

    response = client.get(
        "/api/v1/commercial/revenue-ledger", headers=_auth(admin, settings)
    )
    assert response.status_code == 200, response.get_data(as_text=True)
    data = response.get_json()["data"]
    assert data["scope"] == "platform"
    ids = {item["id"] for item in data["entries"]}
    assert {entry_a.id, entry_b.id} <= ids, "admin 看不到别家企业的科目行"


def test_admin_reads_other_org_revenue_entry(client, db_session, settings):
    """admin 读别家企业的**单条科目** ⇒ 200（平台能力逐位不变）。"""
    org_b = make_enterprise_org(db_session)
    user_b = make_user(db_session, "viewer", org_id=org_b.id)
    admin = make_user(db_session, "admin")
    entry_b = _ledger_entry(
        db_session, subject_user_id=user_b.id, recorded_by_user_id=user_b.id
    )

    response = client.get(
        f"/api/v1/commercial/revenue-ledger/{entry_b.id}",
        headers=_auth(admin, settings),
    )
    assert response.status_code == 200, response.get_data(as_text=True)


def test_admin_cross_org_write_still_leaves_cross_org_event(
    client, db_session, settings
):
    """admin 跨 org 代改别家企业账号角色 ⇒ 仍留 ``cross_org_`` 事件（拍板⑥不推翻）。"""
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
    ], "跨 org 代操作的留痕语义被本轮改写（拍板⑥不推翻 M3b 批次②先例）"
    assert events[0].org_id == org_b.id


# ---------------------------------------------------------------------------
# G. G2 额度账／企业空间面：现状核实（CR-062 绑定账号判定天然更严）
# ---------------------------------------------------------------------------


def test_cross_enterprise_quota_view_returns_not_found(
    client, db_session, settings
):
    """企业甲账号读企业乙的**额度账** ⇒ 404（CR-062 现状：绑定账号判定天然更严）。"""
    org_a = make_enterprise_org(db_session)
    org_b = make_enterprise_org(db_session)
    user_a = make_user(db_session, "viewer", org_id=org_a.id)
    user_b = make_user(db_session, "viewer", org_id=org_b.id)
    subject_key = _uscc("91350100M000210Y4")
    _enterprise_org_for_subject(db_session, subject_key, user_b)
    _quota(db_session, subject_key=subject_key, owner=user_b, bound_user=user_b)

    response = client.get(
        f"/api/v1/commercial/enterprise-quota/{subject_key}",
        headers=_auth(user_a, settings),
    )
    assert response.status_code == 404, response.get_data(as_text=True)
    assert response.get_json()["error"]["code"] == "quota_not_found"


def test_cross_enterprise_enterprise_space_returns_not_found(
    client, db_session, settings
):
    """企业甲账号读企业乙的**企业空间** ⇒ 404（CR-062 现状：不透主体存在性）。"""
    org_a = make_enterprise_org(db_session)
    org_b = make_enterprise_org(db_session)
    user_a = make_user(db_session, "viewer", org_id=org_a.id)
    user_b = make_user(db_session, "viewer", org_id=org_b.id)
    subject_key = _uscc("91350100M000211Y4")
    _enterprise_org_for_subject(db_session, subject_key, user_b)
    _quota(db_session, subject_key=subject_key, owner=user_b, bound_user=user_b)

    response = client.get(
        f"/api/v1/commercial/enterprise-spaces/{subject_key}",
        headers=_auth(user_a, settings),
    )
    assert response.status_code == 404, response.get_data(as_text=True)
    assert response.get_json()["error"]["code"] == "enterprise_space_not_found"


def test_cross_enterprise_quota_probe_is_indistinguishable(
    client, db_session, settings
):
    """**探测不可分辨**：跨 org 读「存在的主体」与「不存在的主体」载荷逐位一致。"""
    org_a = make_enterprise_org(db_session)
    org_b = make_enterprise_org(db_session)
    user_a = make_user(db_session, "viewer", org_id=org_a.id)
    user_b = make_user(db_session, "viewer", org_id=org_b.id)
    subject_key = _uscc("91350100M000212Y4")
    _enterprise_org_for_subject(db_session, subject_key, user_b)
    _quota(db_session, subject_key=subject_key, owner=user_b, bound_user=user_b)

    existent = client.get(
        f"/api/v1/commercial/enterprise-quota/{subject_key}",
        headers=_auth(user_a, settings),
    )
    missing = client.get(
        f"/api/v1/commercial/enterprise-quota/{_uscc('91350100M000213Y4')}",
        headers=_auth(user_a, settings),
    )
    assert existent.status_code == missing.status_code == 404
    assert existent.get_json()["error"] == missing.get_json()["error"], (
        "跨 org 主体存在性被泄露（CR-062 不透主体存在性被破坏）"
    )


# ---------------------------------------------------------------------------
# H. G2 额度去重口径未被 org 维度污染（拍板③）
# ---------------------------------------------------------------------------


def test_uscc_dedup_key_unchanged_by_org_dimension(db_session):
    """**去重维度仍是 USCC 单键**——同主体不因 org 维度而得第二份额度。

    口径并置（拍板③）：USCC ＝**去重维度**（额度行唯一）；org ＝**可见性/隔离
    维度**（读面隔离）。本用例钉住前者未被本轮改写。
    """
    subject_key = _uscc("91350100M000214Y4")
    owner = make_user(db_session, "viewer")
    _enterprise_org_for_subject(db_session, subject_key, owner)
    _quota(db_session, subject_key=subject_key, owner=owner, bound_user=owner)

    rows = list(
        db_session.scalars(
            select(EnterpriseFreeQuota).where(
                EnterpriseFreeQuota.subject_key == subject_key
            )
        ).all()
    )
    assert len(rows) == 1, "同主体的额度行数不是 1（USCC 单键去重口径被改写）"
    subjects = list(
        db_session.scalars(
            select(EnterpriseQuotaSubject).where(
                EnterpriseQuotaSubject.subject_key == subject_key
            )
        ).all()
    )
    assert len(subjects) == 1, "同主体的主体行数不是 1（USCC 单键去重口径被改写）"
