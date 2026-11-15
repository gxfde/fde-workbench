"""M7：商机数据归属权与导出权硬约束（多客户工作平台 M7 轮；ADR-M7）。

sec 评审硬条件（评审记录 :35「归属权与导出权**须在 M7 写死**」；leader
任务书 §7 M7）原文：

    **商机数据归属权写死：平台托管、企业确认前区域服务商不可导出客户名单、
    双方按授权可见**

本文件钉住八件事：

1. **规则文件 ↔ 代码常量 ↔ 测试三方一致**（§9 机器可读块；成文规则是
   唯一成文处，代码侧只提供可配置结构）；
2. **企业确认前区域服务商不可导出客户名单**（枚举面关闭）：
   ``?enterprise_code=`` 命中「域外 ＋ 未企业确认」的行 ⇒ 403
   ``opportunity_customer_list_not_confirmed``；
3. **客户识别字段遮蔽**（序列化层）：``enterprise_code`` 与
   ``enterprise_registered`` 输出 ``None`` ＋ 显式
   ``customer_identity_visible=False``；
4. **双方按授权可见**（企业确认后）：客户识别字段恢复可见；
5. **托管方例外**：admin 全量可见（含未企业确认商机）——平台托管方口径
   不变，与 M3b「admin 跨 org 代操作留痕不阻断」一致；
6. **零新表零新列零新路由**：本轮不新增任何授权表/列/路由——授权可见范围
   由既有列（``enterprise_confirmed_at`` ＋ 三列 FK）＋ ``users.org_id``
   推导（源码扫描哨兵）；
7. **错误码闭集**：新增错误码只增不改（既有码逐位不变）；
8. **区域服务商身份判定**：经既有 ``regional_partners.applicant_user_id``
   推导——不新增授权表（源码扫描哨兵）。
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from uuid import uuid4

from fde_api.auth.tokens import issue_access_token
from fde_api.commercial.attribution_service import (
    OPPORTUNITY_CUSTOMER_IDENTITY_FIELDS,
    customer_identity_visible,
    is_opportunity_custodian,
    is_regional_partner,
    require_enterprise_confirmed_for_customer_list,
)
from fde_api.commercial.models import CommercialOpportunity

from conftest import INITIAL_PASSWORD
from multi_tenant_harness import make_enterprise_org, make_user

SERVER_ROOT = Path(__file__).resolve().parent.parent
RULE_DOC = (
    SERVER_ROOT.parent
    / "docs"
    / "commercialization"
    / "rules"
    / "opportunity-attribution-rules.md"
)
ATTRIBUTION_SERVICE = (
    SERVER_ROOT / "src" / "fde_api" / "commercial" / "attribution_service.py"
)
MODELS_SOURCE = SERVER_ROOT / "src" / "fde_api" / "commercial" / "models.py"

# M7 错误码闭集（新增码在此登记；既有码不得改动）
M7_ERROR_CODES = ("opportunity_customer_list_not_confirmed",)


def _auth(user, settings) -> dict[str, str]:
    return {"Authorization": f"Bearer {issue_access_token(user, settings)}"}


def _sha(seed: str) -> str:
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()


def _opp_url(opportunity_id: str = "") -> str:
    base = "/api/v1/commercial/opportunities"
    return f"{base}/{opportunity_id}" if opportunity_id else base


def _partner_row(db_session, user, partner_code: str):
    """直写一条区域伙伴行（夹具：构造「区域服务商身份」）。"""
    from fde_api.commercial.models import RegionalPartner

    row = RegionalPartner(
        partner_code=partner_code,
        region_name="M7 隔离用例区域",
        stage="city_observer",
        applicant_user_id=user.id,
    )
    db_session.add(row)
    db_session.commit()
    return row


def _active_seat(db_session, user) -> None:
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


def _report(client, user, settings, enterprise_code: str, title: str = "M7 归属权商机"):
    response = client.post(
        _opp_url(),
        json={
            "enterprise_code": enterprise_code,
            "title": title,
            "source_uri": f"pointer://m7/ownership/{uuid4().hex[:8]}",
            "content_hash": _sha(f"m7-own-{uuid4().hex}"),
        },
        headers=_auth(user, settings),
    )
    assert response.status_code == 200, response.get_data(as_text=True)
    return response.json["data"]["opportunity"]


def _confirm_enterprise(db_session, opportunity_id: str) -> None:
    """直写企业确认时刻（模拟平台代录企业书面答复后的状态）。"""
    row = db_session.get(CommercialOpportunity, opportunity_id)
    assert row is not None
    row.enterprise_confirmed_at = row.reported_at
    row.status = "enterprise_confirmed"
    db_session.commit()


# ---------------------------------------------------------------------------
# 1. 规则文件 ↔ 代码常量 ↔ 测试三方一致（§9 机器可读块）
# ---------------------------------------------------------------------------


def test_ownership_rule_document_block_matches_code_bidirectionally() -> None:
    """§9 机器可读块 ↔ 代码常量**双向相等**（文档／代码／测试三方一致）。"""
    body = RULE_DOC.read_text(encoding="utf-8")
    begin = body.index("<!-- ownership-rules:begin -->")
    end = body.index("<!-- ownership-rules:end -->")
    block = body[begin:end]
    match = re.search(r"```json\s*(\{.*?\})\s*```", block, flags=re.DOTALL)
    assert match is not None, "规则文件缺少 §9 ```json 机器可读代码块"
    payload = json.loads(match.group(1))

    doc_fields = payload["customer_identity_fields"]
    assert doc_fields == list(OPPORTUNITY_CUSTOMER_IDENTITY_FIELDS), (
        "规则文件与代码常量的客户识别字段集合不等"
    )
    doc_codes = payload["error_codes"]
    assert set(doc_codes) == set(M7_ERROR_CODES), "规则文件与测试的错误码闭集不等"
    assert payload["custodian"] == "admin", "托管方口径必须是 admin（平台方）"
    assert payload["confirmation_gate_column"] == "enterprise_confirmed_at", (
        "企业确认闸必须落在既有列 enterprise_confirmed_at（零新列）"
    )
    assert payload["external_role_source"] == "regional_partners.applicant_user_id", (
        "区域服务商身份必须经既有列推导（零新表）"
    )


def test_ownership_rule_doc_states_no_new_table_or_route() -> None:
    """规则文件 §9 明文「零新表零新列零新路由」——不得口径漂移。"""
    body = RULE_DOC.read_text(encoding="utf-8")
    section = body[body.index("## 9.") : body.index("<!-- ownership-rules:begin -->")]
    assert "零新表" in section
    assert "零新列" in section
    assert "零新路由" in section


# ---------------------------------------------------------------------------
# 2. 零新表零新列零新路由（源码扫描哨兵）
# ---------------------------------------------------------------------------


def test_no_new_authorization_table_or_column_or_route() -> None:
    """本轮**零新表零新列零新路由**——源码扫描哨兵。

    授权可见范围由**既有列**推导：
    ``commercial_opportunities.enterprise_confirmed_at`` ＋ 三列 FK
    （``reported_by_user_id``／``attribution_owner_user_id``／
    ``presales_owner_user_id``）＋ ``users.org_id``。
    """
    models_source = MODELS_SOURCE.read_text(encoding="utf-8")
    # 不得出现任何 M7 新增的授权模型
    for forbidden in (
        "class OpportunityOwnership",
        "class OpportunityExportGrant",
        "class CustomerListAccess",
        "class OpportunityVisibilityGrant",
    ):
        assert forbidden not in models_source, f"M7 不得新增授权表：{forbidden}"
    # 不得出现 org_id 加列到 G4/G5 六表
    for table in (
        "commercial_opportunities",
        "commercial_opportunity_rules",
        "regional_partner_tiers",
        "regional_partners",
        "regional_sale_gate",
        "regional_service_settlements",
    ):
        block = models_source.split(f'__tablename__ = "{table}"', 1)[1]
        block = block.split("class ", 1)[0]
        assert "org_id" not in block, f"{table} 不得新增 org_id 列"


def test_no_new_export_route_in_commercial_domain() -> None:
    """**无 export 端点**——本轮不新增任何导出路由（硬约束落在读面层）。

    客户名单导出面**就是**既有列表读面（``GET /commercial/opportunities``
    支持 ``?enterprise_code=`` 枚举），故硬约束落在读面与序列化层，
    **不是**另开一个 export 端点。
    """
    routes_source = (
        SERVER_ROOT / "src" / "fde_api" / "commercial" / "routes.py"
    ).read_text(encoding="utf-8")
    for forbidden in ("/export", "/download", "/customer-list", "/customers"):
        assert forbidden not in routes_source, f"不得新增导出路由：{forbidden}"


def test_no_new_authorization_model_in_attribution_service() -> None:
    """归属权原语**不落新模型**——只用既有列与既有表。"""
    source = ATTRIBUTION_SERVICE.read_text(encoding="utf-8")
    # 服务层不得引入新的 Base 派生模型
    assert "class " not in source, "服务层不得新增模型类（零新表）"
    # 授权判定只依赖既有列
    for column in (
        "enterprise_confirmed_at",
        "reported_by_user_id",
        "attribution_owner_user_id",
        "presales_owner_user_id",
    ):
        assert column in source, f"授权判定须依赖既有列 {column}"


# ---------------------------------------------------------------------------
# 3. 企业确认前区域服务商不可导出客户名单（枚举面关闭）
# ---------------------------------------------------------------------------


def test_regional_partner_cannot_enumerate_customer_list_before_confirmation(
    client, db_session, settings
) -> None:
    """区域服务商枚举客户名单 ⇒ 403（企业确认前）——**存在性旁路关闭**。"""
    org_a = make_enterprise_org(db_session)
    org_b = make_enterprise_org(db_session)
    user_a = make_user(db_session, "viewer", org_id=org_a.id)
    user_b = make_user(db_session, "viewer", org_id=org_b.id)
    _partner_row(db_session, user_a, f"m7 伙伴·归属·甲{uuid4().hex[:6]}")
    _active_seat(db_session, user_b)
    enterprise_code = f"m7 客户·制造·{uuid4().hex[:6]}"
    _report(client, user_b, settings, enterprise_code)

    probe = client.get(
        f"{_opp_url()}?enterprise_code={enterprise_code}",
        headers=_auth(user_a, settings),
    )
    assert probe.status_code == 403, probe.get_data(as_text=True)
    assert (
        probe.get_json()["error"]["code"] == "opportunity_customer_list_not_confirmed"
    )


def test_regional_partner_cannot_read_other_customer_identity_field(
    client, db_session, settings
) -> None:
    """区域服务商读**他人**未确认商机 ⇒ 客户识别字段被遮蔽。"""
    org_a = make_enterprise_org(db_session)
    org_b = make_enterprise_org(db_session)
    user_a = make_user(db_session, "viewer", org_id=org_a.id)
    user_b = make_user(db_session, "viewer", org_id=org_b.id)
    _partner_row(db_session, user_a, f"m7 伙伴·归属·甲{uuid4().hex[:6]}")
    _active_seat(db_session, user_b)
    enterprise_code = f"m7 客户·制造·{uuid4().hex[:6]}"
    reported = _report(client, user_b, settings, enterprise_code)

    # 详情读面：区域服务商甲对乙报备的商机 ⇒ 403（读面不外泄）
    detail = client.get(
        _opp_url(reported["id"]), headers=_auth(user_a, settings)
    )
    assert detail.status_code == 403, detail.get_data(as_text=True)
    assert detail.get_json()["error"]["code"] == "opportunity_forbidden"

    # 列表读面：甲看不见乙的行（既有 reporter 收敛）
    listed = client.get(_opp_url(), headers=_auth(user_a, settings))
    assert listed.status_code == 200, listed.get_data(as_text=True)
    assert all(
        row["id"] != reported["id"]
        for row in listed.json["data"]["opportunities"]
    )


def test_enterprise_confirmation_is_the_gate_for_customer_identity(
    client, db_session, settings
) -> None:
    """**双方按授权可见**：企业确认后客户识别字段恢复（正例）。"""
    org_a = make_enterprise_org(db_session)
    user_a = make_user(db_session, "viewer", org_id=org_a.id)
    _partner_row(db_session, user_a, f"m7 伙伴·归属·甲{uuid4().hex[:6]}")
    _active_seat(db_session, user_a)
    enterprise_code = f"m7 客户·制造·{uuid4().hex[:6]}"
    reported = _report(client, user_a, settings, enterprise_code)

    before = client.get(_opp_url(), headers=_auth(user_a, settings))
    assert before.status_code == 200, before.get_data(as_text=True)
    before_row = next(
        row
        for row in before.json["data"]["opportunities"]
        if row["id"] == reported["id"]
    )
    assert before_row["enterprise_code"] is None
    assert before_row["customer_identity_visible"] is False

    _confirm_enterprise(db_session, reported["id"])

    after = client.get(_opp_url(), headers=_auth(user_a, settings))
    assert after.status_code == 200, after.get_data(as_text=True)
    after_row = next(
        row
        for row in after.json["data"]["opportunities"]
        if row["id"] == reported["id"]
    )
    assert after_row["enterprise_code"] == enterprise_code
    assert after_row["customer_identity_visible"] is True


# ---------------------------------------------------------------------------
# 4. 托管方例外（admin 全量可见）
# ---------------------------------------------------------------------------


def test_admin_custodian_sees_every_customer_identity(
    client, db_session, settings
) -> None:
    """admin（平台托管方）全量可见——含未企业确认商机（口径不变）。"""
    admin = make_user(db_session, "admin")
    user_b = make_user(db_session, "viewer")
    _active_seat(db_session, user_b)
    enterprise_code = f"m7 客户·制造·{uuid4().hex[:6]}"
    reported = _report(client, user_b, settings, enterprise_code)

    detail = client.get(_opp_url(reported["id"]), headers=_auth(admin, settings))
    assert detail.status_code == 200, detail.get_data(as_text=True)
    row = detail.json["data"]["opportunity"]
    assert row["enterprise_code"] == enterprise_code
    assert row["customer_identity_visible"] is True


def test_non_partner_role_visibility_is_unchanged(
    client, db_session, settings
) -> None:
    """**非区域服务商**账号的既有可见性语义**逐位不变**。

    本轮硬约束的作用对象是**外部角色**——不越界改写既有读面口径
    （与 M6 的 org 隔离接线分工正交）。
    """
    user = make_user(db_session, "viewer")
    _active_seat(db_session, user)
    enterprise_code = f"m7 客户·制造·{uuid4().hex[:6]}"
    reported = _report(client, user, settings, enterprise_code)

    detail = client.get(_opp_url(reported["id"]), headers=_auth(user, settings))
    assert detail.status_code == 200, detail.get_data(as_text=True)
    row = detail.json["data"]["opportunity"]
    assert row["enterprise_code"] == enterprise_code, "非区域服务商语义逐位不变"
    assert row["customer_identity_visible"] is True


# ---------------------------------------------------------------------------
# 5. 原语层判定（服务原语直接调用）
# ---------------------------------------------------------------------------


def test_primitive_layer_judgements(db_session) -> None:
    """原语层判定逐项核对（托管方／区域服务商身份／可见性／枚举闸）。"""
    org_a = make_enterprise_org(db_session)
    user_a = make_user(db_session, "viewer", org_id=org_a.id)
    admin = make_user(db_session, "admin")
    _partner_row(db_session, user_a, f"m7 伙伴·原语·{uuid4().hex[:6]}")

    # 托管方判定：只看 role
    assert is_opportunity_custodian(admin) is True
    assert is_opportunity_custodian(user_a) is False

    # 区域服务商身份：经既有 regional_partners 行推导
    assert is_regional_partner(db_session, user_a) is True
    assert is_regional_partner(db_session, admin) is False
    outsider = make_user(db_session, "viewer")
    assert is_regional_partner(db_session, outsider) is False

    # 可见性：未确认 ⇒ 区域服务商不可见；已确认 ⇒ 可见
    row = CommercialOpportunity(
        enterprise_code="m7 客户·制造·原语",
        title="原语判定用例",
        status="submitted",
        reported_by_user_id=user_a.id,
        reported_at=__import__("datetime").datetime.now(
            __import__("datetime").timezone.utc
        ),
        source_uri="pointer://m7/primitive",
        content_hash="c" * 64,
        protection_status="unconfigured",
        protection_renewal_count=0,
    )
    db_session.add(row)
    db_session.commit()

    assert (
        customer_identity_visible(row, actor=user_a, external_partner=True) is False
    )
    assert (
        customer_identity_visible(row, actor=user_a, external_partner=False) is True
    )
    assert customer_identity_visible(row, actor=admin, external_partner=True) is True

    # 枚举闸：未确认 ＋ **域外**（不在 actor 可见域内）⇒ 拒绝
    try:
        require_enterprise_confirmed_for_customer_list(
            db_session,
            actor=user_a,
            enterprise_code=row.enterprise_code,
            scoped_ids=set(),
        )
    except Exception as error:  # noqa: BLE001 - 断言错误码
        assert getattr(error, "code", None) == (
            "opportunity_customer_list_not_confirmed"
        )
    else:
        raise AssertionError("未企业确认的枚举闸未拒绝")

    # 枚举闸：**可见域内** ⇒ 放行（无新信息泄露）
    require_enterprise_confirmed_for_customer_list(
        db_session,
        actor=user_a,
        enterprise_code=row.enterprise_code,
        scoped_ids={row.id},
    )

    # 托管方 ⇒ 放行
    require_enterprise_confirmed_for_customer_list(
        db_session,
        actor=admin,
        enterprise_code=row.enterprise_code,
        scoped_ids=set(),
    )


# ---------------------------------------------------------------------------
# 6. 错误码闭集（新增码只增不改）
# ---------------------------------------------------------------------------


def test_m7_error_code_is_registered_in_service_source() -> None:
    """M7 新增错误码在服务层有定义（闭集登记）。"""
    source = ATTRIBUTION_SERVICE.read_text(encoding="utf-8")
    for code in M7_ERROR_CODES:
        assert f'"{code}"' in source, f"错误码 {code} 未在服务层定义"


def test_existing_error_codes_are_unchanged() -> None:
    """**既有错误码逐位不变**——本轮只新增，不改动既有码。"""
    source = ATTRIBUTION_SERVICE.read_text(encoding="utf-8")
    for code in (
        "opportunity_not_found",
        "opportunity_forbidden",
        "rule_not_configured",
        "opportunity_reporter_seat_required",
        "attribution_already_confirmed",
        "invalid_opportunity_state",
        "opportunity_disputed",
        "package_enterprise_mismatch",
        "ledger_subject_mismatch",
    ):
        assert f'"{code}"' in source, f"既有错误码 {code} 丢失"
