"""M7：区域面跨 org 隔离用例（多客户工作平台 M7 轮；OWNER 2026-11-12 拍板）。

**主体归属口径**（OWNER 2026-11-12 拍板，勿改）：G4/G5 六表**无 org_id 列**，
主体归属走 ``users.org_id`` **间接归属**——**不新增 org_id 列、不新增迁移、
不改表结构**。区域伙伴的 org 归属经 ``applicant_user_id`` → ``users.org_id``
推导。

**与 M6 的分工边界**（重要）：

- M6 负责**商业域读面按 org 隔离的通用接线**（科目层／额度账／企业空间／
  权益／认证记录／**商机列表**的跨 org 读面隔离）；
- 本文件**只补区域面特有部分**（``regional_partners`` 列表／详情／
  ``regional_partner_tiers`` 目录），**不重复实现 M6 的通用 org 隔离**；
- 商机读面的用例**只覆盖 M7 新增的客户名单归属权约束**（区域服务商身份
  × 企业确认闸），**不重复 M6 的通用 org 收敛断言**。

钉住六件事：

1. **区域伙伴列表跨 org 收敛**：企业甲账号只读得到**本 org 申请**的伙伴行，
   企业乙的行不外泄（M3a 口径：同 org 无权操作 ⇒ 403；跨 org ⇒ 404
   不确认资源存在——读面按 CR-062 商业域一律 404）。
2. **区域伙伴详情跨 org ⇒ 404**：他人申请的伙伴行不确认存在性。
3. **区域档目录读面**：``GET /commercial/regional-partner-tiers`` **任意认证
   用户可见**（既有行为，**不是漏洞**）——目录可见 ≠ 可签约；售卖闸状态
   ``sale_gate_status`` 一并透出且恒为 ``closed``（本期）。
4. **区域服务商的客户名单硬约束**（M7 A 组）：企业确认前，区域服务商
   不得读到他人的客户识别字段（``enterprise_code`` 遮蔽）。
5. **企业确认后双方按授权可见**：确认闸打开后客户识别字段恢复可见。
6. **枚举探针关闭**：``?enterprise_code=`` 对区域服务商在企业确认前 ⇒ 403
   ``opportunity_customer_list_not_confirmed``（含命中自报行——探针会回答
   「该企业代号在平台是否存在」）。
"""

from __future__ import annotations

import hashlib
from uuid import uuid4

from fde_api.auth.tokens import issue_access_token
from fde_api.commercial.models import RegionalPartner

from conftest import INITIAL_PASSWORD
from multi_tenant_harness import make_enterprise_org, make_user


def _auth(user, settings) -> dict[str, str]:
    return {"Authorization": f"Bearer {issue_access_token(user, settings)}"}


def _sha(seed: str) -> str:
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()


def _partners_url() -> str:
    return "/api/v1/commercial/regional-partners"


def _tiers_url() -> str:
    return "/api/v1/commercial/regional-partner-tiers"


def _opp_url(opportunity_id: str = "") -> str:
    base = "/api/v1/commercial/opportunities"
    return f"{base}/{opportunity_id}" if opportunity_id else base


def _apply_partner(client, partner_code: str, region: str = "杭州"):
    """申请成为城市观察伙伴（免费；当事人自证）。"""
    response = client.post(
        _partners_url(),
        json={"partner_code": partner_code, "region_name": region},
    )
    assert response.status_code == 200, response.get_data(as_text=True)
    return response.json["data"]["partner"]


def _partner_row(db_session, user, partner_code: str) -> RegionalPartner:
    """直写一条区域伙伴行（夹具：跨 org 读面用例的构造器）。"""
    row = RegionalPartner(
        partner_code=partner_code,
        region_name="隔离用例区域",
        stage="city_observer",
        applicant_user_id=user.id,
    )
    db_session.add(row)
    db_session.commit()
    return row


def _active_seat(db_session, user) -> None:
    """给账号一条生效席位（商机报备资格闸：缴费或席位 active 任一即可）。"""
    from datetime import UTC, datetime

    from fde_api.commercial.models import CommercialEntitlement

    db_session.add(
        CommercialEntitlement(
            user_id=user.id,
            seat_status="active",
            seat_source="first_delivery",
            seat_activated_at=datetime.now(UTC),
            seat_expires_at=datetime(2027, 12, 31, tzinfo=UTC),
        )
    )
    db_session.commit()


def _report(client, user, settings, enterprise_code: str, title: str = "M7 隔离用例商机"):
    """以指定账号身份报备商机（走真实写面：席位闸＋事件留痕）。"""
    response = client.post(
        _opp_url(),
        json={
            "enterprise_code": enterprise_code,
            "title": title,
            "source_uri": f"pointer://m7/cross-org/{uuid4().hex[:8]}",
            "content_hash": _sha(f"m7-{uuid4().hex}"),
        },
        headers=_auth(user, settings),
    )
    assert response.status_code == 200, response.get_data(as_text=True)
    return response.json["data"]["opportunity"]


# ---------------------------------------------------------------------------
# 1. 区域伙伴读面跨 org 收敛（区域面特有；通用 org 隔离接线归 M6）
# ---------------------------------------------------------------------------


def test_regional_partner_list_scoped_to_own_org(client, db_session, settings):
    """区域伙伴列表：只读得到**本 org 申请**的行（他人行不外泄）。"""
    org_a = make_enterprise_org(db_session)
    org_b = make_enterprise_org(db_session)
    user_a = make_user(db_session, "viewer", org_id=org_a.id)
    user_b = make_user(db_session, "viewer", org_id=org_b.id)
    partner_a = _partner_row(db_session, user_a, f"m7 伙伴·隔离·甲{uuid4().hex[:6]}")
    _partner_row(db_session, user_b, f"m7 伙伴·隔离·乙{uuid4().hex[:6]}")

    listed = client.get(_partners_url(), headers=_auth(user_a, settings))
    assert listed.status_code == 200, listed.get_data(as_text=True)
    rows = listed.json["data"]
    codes = {row["partner_code"] for row in rows}
    assert partner_a.partner_code in codes
    assert all(code.startswith("m7 伙伴·隔离·甲") for code in codes), codes


def test_regional_partner_detail_cross_org_returns_not_found(
    client, db_session, settings
):
    """企业甲账号读企业乙申请的伙伴详情 ⇒ 404（不确认资源存在）。"""
    org_a = make_enterprise_org(db_session)
    org_b = make_enterprise_org(db_session)
    user_a = make_user(db_session, "viewer", org_id=org_a.id)
    user_b = make_user(db_session, "viewer", org_id=org_b.id)
    partner_b = _partner_row(db_session, user_b, f"m7 伙伴·隔离·乙{uuid4().hex[:6]}")

    response = client.get(
        f"{_partners_url()}/{partner_b.id}", headers=_auth(user_a, settings)
    )
    assert response.status_code == 404, response.get_data(as_text=True)
    assert response.get_json()["error"]["code"] == "partner_not_found"


def test_regional_partner_detail_same_org_visible(client, db_session, settings):
    """**同 org** 伙伴详情可见（同 org 不构成越权；M3a 口径）。"""
    org_a = make_enterprise_org(db_session)
    user_a = make_user(db_session, "viewer", org_id=org_a.id)
    user_a2 = make_user(db_session, "viewer", org_id=org_a.id)
    partner_a = _partner_row(db_session, user_a, f"m7 伙伴·隔离·甲{uuid4().hex[:6]}")

    response = client.get(
        f"{_partners_url()}/{partner_a.id}", headers=_auth(user_a2, settings)
    )
    assert response.status_code == 200, response.get_data(as_text=True)
    assert response.json["data"]["partner_code"] == partner_a.partner_code


# ---------------------------------------------------------------------------
# 2. 区域档目录读面（售卖闸关闭态下**仍可见**——既有行为，不是漏洞）
# ---------------------------------------------------------------------------


def test_regional_tier_catalog_visible_to_any_authenticated_user(
    client, db_session, settings
):
    """区域档目录**任意认证用户可见**；售卖闸关闭态下仍可见（既有行为钉）。

    **口径**：目录可见 ≠ 可签约——对外收费签约被 ``regional_sale_gate``
    全局闸住（默认 closed）。本用例把这条边界**显式钉住**，避免后续被误读
    成「售卖闸失效」。
    """
    org_a = make_enterprise_org(db_session)
    user_a = make_user(db_session, "viewer", org_id=org_a.id)

    response = client.get(_tiers_url(), headers=_auth(user_a, settings))
    assert response.status_code == 200, response.get_data(as_text=True)
    data = response.json["data"]
    assert {row["tier_code"] for row in data["tiers"]} == {"T1", "T2", "T3"}
    assert data["sale_gate_status"] == "closed", "本期售卖闸恒为 closed"


def test_regional_tier_catalog_requires_authentication(client):
    """未认证读区域档目录 ⇒ 401（目录虽公开可见面，仍需认证身份）。"""
    response = client.get(_tiers_url())
    assert response.status_code == 401, response.get_data(as_text=True)


# ---------------------------------------------------------------------------
# 3. M7 客户名单硬约束 × 区域服务商身份（跨 org 视角）
# ---------------------------------------------------------------------------


def test_regional_partner_cannot_read_other_org_customer_identity(
    client, db_session, settings
):
    """区域服务商（企业甲 org）读企业乙报备的商机 ⇒ 客户识别字段被遮蔽。

    **M7 A 组**：企业确认前，客户识别数据由平台托管——区域服务商不得取得
    客户名单。遮蔽字段（非删除）＋显式 ``customer_identity_visible=False``。
    """
    org_a = make_enterprise_org(db_session)
    org_b = make_enterprise_org(db_session)
    user_a = make_user(db_session, "viewer", org_id=org_a.id)
    user_b = make_user(db_session, "viewer", org_id=org_b.id)
    _partner_row(db_session, user_a, f"m7 伙伴·隔离·甲{uuid4().hex[:6]}")
    _active_seat(db_session, user_b)
    reported = _report(client, user_b, settings, f"m7 隔离企业·制造·{uuid4().hex[:6]}")

    # 区域服务商甲**不是**该商机的报备人/归属人/售前人 ⇒ 详情本就不可读
    detail = client.get(
        _opp_url(reported["id"]), headers=_auth(user_a, settings)
    )
    assert detail.status_code == 403, detail.get_data(as_text=True)
    assert detail.get_json()["error"]["code"] == "opportunity_forbidden"

    # 列表面：甲看不见乙的行（既有 reporter 收敛）⇒ 无客户名单可取
    listed = client.get(_opp_url(), headers=_auth(user_a, settings))
    assert listed.status_code == 200, listed.get_data(as_text=True)
    ids = {row["id"] for row in listed.json["data"]["opportunities"]}
    assert reported["id"] not in ids


def test_regional_partner_enumeration_probe_blocked_before_confirmation(
    client, db_session, settings
):
    """区域服务商用 ``?enterprise_code=`` 枚举客户名单 ⇒ 403（企业确认前）。

    **枚举探针关闭**（M7 A 组）：按企业代号取数＝客户名单导出尝试；命中
    **域外 ＋ 未企业确认**的行 ⇒ 403 ``opportunity_customer_list_not_confirmed``
    ——存在性旁路（「这个企业代号在平台存在」）被关闭。
    """
    org_a = make_enterprise_org(db_session)
    org_b = make_enterprise_org(db_session)
    user_a = make_user(db_session, "viewer", org_id=org_a.id)
    user_b = make_user(db_session, "viewer", org_id=org_b.id)
    _partner_row(db_session, user_a, f"m7 伙伴·隔离·甲{uuid4().hex[:6]}")
    _active_seat(db_session, user_b)
    enterprise_code = f"m7 隔离企业·制造·{uuid4().hex[:6]}"
    _report(client, user_b, settings, enterprise_code)

    probe = client.get(
        f"{_opp_url()}?enterprise_code={enterprise_code}",
        headers=_auth(user_a, settings),
    )
    assert probe.status_code == 403, probe.get_data(as_text=True)
    assert (
        probe.get_json()["error"]["code"] == "opportunity_customer_list_not_confirmed"
    )


def test_regional_partner_enumeration_of_own_scope_is_allowed(
    client, db_session, settings
):
    """区域服务商枚举**自己可见域内**的行 ⇒ 放行（无新信息泄露）。

    存在性旁路的精确口径：命中行全在 actor 可见域内 ⇒ actor 本就能看见，
    探针不产生任何新信息 ⇒ 不构成导出尝试。
    """
    org_a = make_enterprise_org(db_session)
    user_a = make_user(db_session, "viewer", org_id=org_a.id)
    _partner_row(db_session, user_a, f"m7 伙伴·隔离·甲{uuid4().hex[:6]}")
    _active_seat(db_session, user_a)
    enterprise_code = f"m7 隔离企业·制造·{uuid4().hex[:6]}"
    reported = _report(client, user_a, settings, enterprise_code)

    probe = client.get(
        f"{_opp_url()}?enterprise_code={enterprise_code}",
        headers=_auth(user_a, settings),
    )
    assert probe.status_code == 200, probe.get_data(as_text=True)
    rows = probe.json["data"]["opportunities"]
    assert [item["id"] for item in rows] == [reported["id"]]
    # 客户识别字段按闸遮蔽（企业未确认）
    assert rows[0]["enterprise_code"] is None
    assert rows[0]["customer_identity_visible"] is False


def test_regional_partner_customer_identity_visible_after_confirmation(
    client, db_session, settings
):
    """**企业确认后**双方按授权可见 ⇒ 客户识别字段恢复可见（M7 A 组正例）。

    场景：区域服务商本人报备的商机——企业确认前客户代号被闸遮蔽（平台
    托管），企业确认后可见（双方按授权可见）。
    """
    from fde_api.commercial.models import CommercialOpportunity

    org_a = make_enterprise_org(db_session)
    user_a = make_user(db_session, "viewer", org_id=org_a.id)
    _partner_row(db_session, user_a, f"m7 伙伴·隔离·甲{uuid4().hex[:6]}")
    _active_seat(db_session, user_a)
    enterprise_code = f"m7 隔离企业·制造·{uuid4().hex[:6]}"
    reported = _report(client, user_a, settings, enterprise_code)

    # 企业确认前：客户识别字段被遮蔽
    before = client.get(
        f"{_opp_url()}?enterprise_code={enterprise_code}",
        headers=_auth(user_a, settings),
    )
    assert before.status_code == 200, before.get_data(as_text=True)
    before_row = before.json["data"]["opportunities"][0]
    assert before_row["enterprise_code"] is None
    assert before_row["customer_identity_visible"] is False

    # 直写确认时刻（模拟平台代录企业书面答复后的状态——**不经写面**，
    # 避免把 admin 双闸流程引入归属权用例的断言焦点）
    row = db_session.get(CommercialOpportunity, reported["id"])
    assert row is not None
    row.enterprise_confirmed_at = row.reported_at
    row.status = "enterprise_confirmed"
    db_session.commit()

    # 企业确认后：双方按授权可见 ⇒ 客户识别字段恢复
    after = client.get(
        f"{_opp_url()}?enterprise_code={enterprise_code}",
        headers=_auth(user_a, settings),
    )
    assert after.status_code == 200, after.get_data(as_text=True)
    after_row = after.json["data"]["opportunities"][0]
    assert after_row["enterprise_code"] == enterprise_code
    assert after_row["customer_identity_visible"] is True


def test_admin_custodian_retains_full_customer_visibility(
    client, db_session, settings
):
    """**托管方例外**：admin（平台托管方）全量可见，含未企业确认商机。

    M7 A 组：admin 是平台方（托管方），全量可见**保持不变**——与 M3b
    「admin 跨 org 代操作留痕不阻断」一致；硬约束针对的是区域服务商这一
    外部角色。
    """
    admin = make_user(db_session, "admin")
    user_b = make_user(db_session, "viewer")
    _active_seat(db_session, user_b)
    enterprise_code = f"m7 隔离企业·制造·{uuid4().hex[:6]}"
    _report(client, user_b, settings, enterprise_code)

    listed = client.get(
        f"{_opp_url()}?enterprise_code={enterprise_code}",
        headers=_auth(admin, settings),
    )
    assert listed.status_code == 200, listed.get_data(as_text=True)
    rows = listed.json["data"]["opportunities"]
    assert rows[0]["enterprise_code"] == enterprise_code
    assert rows[0]["customer_identity_visible"] is True
