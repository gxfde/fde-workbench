"""goal-crv-fix2 r3 批 D 专项回归套件（QR-055 / QR-056+059 / QR-057 / QR-067）。

覆盖要点：
1. QR-055：激活年度席位必填 `expires_at`（服务层 400），且数据库 `ck_commercial_entitlements_active_requires_expiry`
   阻断 `seat_status='active' AND seat_expires_at IS NULL` 直写。
2. QR-056 + QR-059：商机结算引用的 `project_share` 科目行若 `delivery_package_id IS NULL`（无包行）
   一律 409 `ledger_package_mismatch`（对齐 `regional_service`）；同一笔 `project_share` 行不可被第二条
   商机重复结算（服务层 409 `ledger_already_settled` + DB 唯一部分索引兜底）。
3. QR-057：`commercial_role_assignments.source_uri` 支持 256–500 字符指针完整往返落库（无 `StringDataRightTruncation`）。
4. QR-067（BLOCKED §5 #3A）：`/api/v1/admin/commercial/{fee-configs,split-rules,opportunity-rules,regional-sale-gate}`
   四个治理读面补 `is_platform_operator` 门禁——普通用户与持 `system_operator` AI 档的企业身份均返 403，
   平台管理操作者返 200。
"""
from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from hashlib import sha256
from uuid import uuid4

import pytest
from sqlalchemy.exc import IntegrityError

from conftest import INITIAL_PASSWORD
from fde_api.auth.tokens import issue_access_token
from fde_api.commercial.models import (
    CommercialEntitlement,
    CommercialOpportunity,
    CommercialRevenueLedger,
)
from fde_api.commercial.role_assignment_service import (
    assign_commercial_role,
    list_role_assignments,
)
from fde_api.control.models import UserAIAccessGrant
from fde_api.dispatch.models import DeliveryPackage, DeliverySettlement
from fde_api.solutions.models import ProjectSolution
from fde_api.workbench.models import IndustryTemplate, IndustryTemplateVersion, Project
from multi_tenant_harness import make_enterprise_org, make_user
from test_research_subjects_api import (  # noqa: F401
    admin_client,
    authorized_client_factory,
)


def _sha(label: str) -> str:
    return sha256(label.encode("utf-8")).hexdigest()


def _auth(user, settings) -> dict[str, str]:
    return {"Authorization": f"Bearer {issue_access_token(user, settings)}"}


def _make_package_and_settlement(db_session, leader_id: str, enterprise_code: str):
    tpl = IndustryTemplate(
        template_key=f"crvd-tpl-{uuid4().hex[:8]}",
        name="批D模板",
        industry_name="制造业",
    )
    ver = IndustryTemplateVersion(
        template=tpl,
        name="批D模板 v1",
        industry_name="制造业",
        version_number=1,
        status="published",
    )
    proj = Project(
        project_code=f"CRVD-{uuid4().hex[:6].upper()}",
        name="批D项目",
        enterprise_code=enterprise_code,
        business_line="FDE_DISPATCH",
        planned_start_date=datetime(2026, 11, 1).date(),
        leader_user_id=leader_id,
        source_template_version=ver,
        template_snapshot={"industry_name": "制造业", "modules": []},
    )
    db_session.add_all([tpl, ver, proj])
    db_session.flush()
    sol = ProjectSolution(
        project_id=proj.id,
        name="批D方案",
        schedule="",
        owner_user_id=leader_id,
    )
    db_session.add(sol)
    db_session.flush()
    pkg = DeliveryPackage(
        id=uuid4().hex,
        solution_id=sol.id,
        project_id=proj.id,
        package_code=f"PKG-CRVD-{uuid4().hex[:8].upper()}",
        dispatch_status="published",
        seat_lead=leader_id,
    )
    db_session.add(pkg)
    db_session.flush()
    stl = DeliverySettlement(
        package_id=pkg.id,
        settlement_key="G3",
        base_amount=Decimal("10000.00"),
        platform_amount=Decimal("3500.00"),
        region_amount=Decimal("500.00"),
        city_amount=Decimal("2000.00"),
        delivery_amount=Decimal("4000.00"),
        status="draft",
    )
    db_session.add(stl)
    db_session.commit()
    return proj, pkg, stl


def _advance_opportunity_to_matched(admin_client, reporter_client, package_id: str, enterprise_code: str) -> str:
    rep = reporter_client.post(
        "/api/v1/commercial/opportunities",
        json={
            "enterprise_code": enterprise_code,
            "title": f"批D商机-{uuid4().hex[:6]}",
            "source_uri": f"fdeops://crv-d/opp/{uuid4().hex[:8]}.md",
            "content_hash": _sha(f"opp-{uuid4().hex}"),
        },
    )
    assert rep.status_code == 200, rep.get_data(as_text=True)
    opp_id = rep.json["data"]["opportunity"]["id"]

    c1 = admin_client.post(
        f"/api/v1/admin/commercial/opportunities/{opp_id}/enterprise-confirm",
        json={
            "confirmation_uri": f"fdeops://crv-d/confirm/{opp_id}.md",
            "confirmation_hash": _sha(f"confirm-{opp_id}"),
            "confirm_password": INITIAL_PASSWORD,
        },
    )
    assert c1.status_code == 200, c1.get_data(as_text=True)

    c2 = admin_client.post(
        f"/api/v1/admin/commercial/opportunities/{opp_id}/attribution",
        json={
            "owner_user_id": reporter_client.user.id,
            "attribution_uri": f"fdeops://crv-d/attr/{opp_id}.md",
            "attribution_hash": _sha(f"attr-{opp_id}"),
            "confirm_password": INITIAL_PASSWORD,
        },
    )
    assert c2.status_code == 200, c2.get_data(as_text=True)

    c3 = admin_client.post(
        f"/api/v1/admin/commercial/opportunities/{opp_id}/presales",
        json={"confirm_password": INITIAL_PASSWORD},
    )
    assert c3.status_code == 200, c3.get_data(as_text=True)

    c4 = admin_client.post(
        f"/api/v1/admin/commercial/opportunities/{opp_id}/match",
        json={"delivery_package_id": package_id, "confirm_password": INITIAL_PASSWORD},
    )
    assert c4.status_code == 200, c4.get_data(as_text=True)
    return opp_id


def test_qr055_seat_activation_requires_expires_at_and_db_check(
    admin_client, authorized_client_factory, db_session
) -> None:
    """QR-055：缺 expires_at 服务层 400，且 DB CHECK 阻断无到期日的 active 行。"""
    target = authorized_client_factory("fde_engineer").user

    missing = admin_client.post(
        f"/api/v1/admin/commercial/users/{target.id}/seat-activation",
        json={"seat_source": "bootcamp_practical", "confirm_password": INITIAL_PASSWORD},
    )
    assert missing.status_code == 400
    assert missing.json["error"]["code"] == "invalid_request"

    # 直写绕过服务层也必须被 PostgreSQL CHECK 拦截
    direct_user = authorized_client_factory("viewer").user
    db_session.add(
        CommercialEntitlement(
            user_id=direct_user.id,
            seat_status="active",
            seat_source="first_delivery",
            seat_activated_at=datetime.now(UTC),
            seat_expires_at=None,
        )
    )
    with pytest.raises(IntegrityError):
        db_session.flush()
    db_session.rollback()

    ok = admin_client.post(
        f"/api/v1/admin/commercial/users/{target.id}/seat-activation",
        json={
            "seat_source": "bootcamp_practical",
            "expires_at": "2027-12-31T00:00:00Z",
            "confirm_password": INITIAL_PASSWORD,
        },
    )
    assert ok.status_code == 200
    assert ok.json["data"]["entitlement"]["subscription"]["seat_expires_at"] is not None


def test_qr056_and_qr059_settlement_rejects_packageless_and_duplicate_ledger(
    admin_client, authorized_client_factory, db_session
) -> None:
    """QR-056 + QR-059：无包 project_share 行 409；同一科目行二次结算 409 + DB 唯一索引兜底。"""
    reporter_client = authorized_client_factory("fde_engineer")
    admin_client.post(
        f"/api/v1/admin/commercial/users/{reporter_client.user.id}/role",
        json={"role": "R2", "confirm_password": INITIAL_PASSWORD},
    )
    admin_client.post(
        f"/api/v1/admin/commercial/users/{reporter_client.user.id}/seat-activation",
        json={
            "seat_source": "bootcamp_practical",
            "expires_at": "2027-12-31T00:00:00Z",
            "confirm_password": INITIAL_PASSWORD,
        },
    )

    enterprise_code = f"somwyn.crvd.{uuid4().hex[:6]}"
    _proj, pkg, stl = _make_package_and_settlement(
        db_session, reporter_client.user.id, enterprise_code
    )
    opp1_id = _advance_opportunity_to_matched(
        admin_client, reporter_client, pkg.id, enterprise_code
    )
    opp2_id = _advance_opportunity_to_matched(
        admin_client, reporter_client, pkg.id, enterprise_code
    )

    # 造一条无 delivery_package_id 的 project_share 科目行（模拟别家/孤立科目行）
    packageless = CommercialRevenueLedger(
        subject_type="project_share",
        line_item="platform_share",
        status="recorded",
        amount=Decimal("3500.00"),
        delivery_package_id=None,
        delivery_settlement_id=stl.id,
        recorded_by_user_id=admin_client.user.id,
        role_code="R3",
        project_type="delivery",
        source_uri="fdeops://crv-d/ledger-packageless.md",
        content_hash=_sha("packageless"),
    )
    db_session.add(packageless)
    db_session.commit()

    # QR-056：引用无包行结算必须 409 ledger_package_mismatch
    bad_pkg = admin_client.post(
        f"/api/v1/admin/commercial/opportunities/{opp1_id}/settlement",
        json={"ledger_entry_id": packageless.id, "confirm_password": INITIAL_PASSWORD},
    )
    assert bad_pkg.status_code == 409, bad_pkg.get_data(as_text=True)
    assert bad_pkg.json["error"]["code"] == "ledger_package_mismatch"

    # 正向创建绑定 pkg.id 的 project_share 科目行并结算 opp1
    valid_ledger = admin_client.post(
        "/api/v1/admin/commercial/revenue-ledger",
        json={
            "subject_type": "project_share",
            "line_item": "platform_share",
            "delivery_settlement_id": stl.id,
            "delivery_package_id": pkg.id,
            "role_code": "R3",
            "project_type": "delivery",
            "confirm_password": INITIAL_PASSWORD,
        },
    )
    assert valid_ledger.status_code == 200, valid_ledger.get_data(as_text=True)
    ledger_id = valid_ledger.json["data"]["entry"]["id"]

    ok1 = admin_client.post(
        f"/api/v1/admin/commercial/opportunities/{opp1_id}/settlement",
        json={"ledger_entry_id": ledger_id, "confirm_password": INITIAL_PASSWORD},
    )
    assert ok1.status_code == 200, ok1.get_data(as_text=True)

    # QR-059：第二条商机复用同一 ledger_id 结算必须 409 ledger_already_settled
    dup = admin_client.post(
        f"/api/v1/admin/commercial/opportunities/{opp2_id}/settlement",
        json={"ledger_entry_id": ledger_id, "confirm_password": INITIAL_PASSWORD},
    )
    assert dup.status_code == 409, dup.get_data(as_text=True)
    assert dup.json["error"]["code"] == "ledger_already_settled"

    # DB 部分唯一索引兜底验证：直接篡改 opp2.settled_ledger_entry_id 触发 IntegrityError
    opp2_row = db_session.get(CommercialOpportunity, opp2_id)
    assert opp2_row is not None
    opp2_row.settled_ledger_entry_id = ledger_id
    with pytest.raises(IntegrityError):
        db_session.flush()
    db_session.rollback()


def test_qr057_role_assignment_supports_long_source_uri_up_to_500(
    admin_client, authorized_client_factory, db_session
) -> None:
    """QR-057：256–500 字符的 source_uri 可正常持久化，不再被 String(255) 截断报错。"""
    target = authorized_client_factory("fde_engineer").user
    long_uri = "fdeops://engagements/somwyn/roles/" + ("a" * 380) + ".md"
    assert 255 < len(long_uri) <= 500

    result = assign_commercial_role(
        db_session,
        actor=admin_client.user,
        user_id=target.id,
        commercial_role="R3",
        valid_from="2026-11-01T00:00:00Z",
        valid_until=None,
        source_uri=long_uri,
        content_hash=_sha("qr057-long-uri"),
        confirm_password=INITIAL_PASSWORD,
    )
    db_session.commit()
    assert result["source_uri"] == long_uri

    listed = list_role_assignments(db_session, actor=admin_client.user, user_id=target.id)
    assert any(item["source_uri"] == long_uri for item in listed["assignments"])


def test_qr067_admin_commercial_four_get_routes_require_platform_operator(
    client, db_session, settings
) -> None:
    """QR-067：四个治理读面仅平台管理操作者可读；普通用户与企业高 AI 档身份均 403。"""
    platform_admin = make_user(db_session, "admin")
    plain_viewer = make_user(db_session, "viewer")
    ent_org = make_enterprise_org(db_session)
    ent_sysop = make_user(db_session, "project_lead", org_id=ent_org.id)
    db_session.add(
        UserAIAccessGrant(
            user_id=ent_sysop.id,
            access_level="system_operator",
            granted_by_user_id=platform_admin.id,
            reason="QR-067 企业身份持 system_operator 反例",
        )
    )
    # 平台身份但未授 system_operator AI 档的 FDE 工程师，以及持 system_operator 的企业身份，均不可读
    platform_non_op = make_user(db_session, "fde_engineer")
    db_session.commit()

    routes = (
        "/api/v1/admin/commercial/fee-configs",
        "/api/v1/admin/commercial/split-rules",
        "/api/v1/admin/commercial/opportunity-rules",
        "/api/v1/admin/commercial/regional-sale-gate",
    )

    for path in routes:
        r_plain = client.get(path, headers=_auth(plain_viewer, settings))
        assert r_plain.status_code == 403, (path, r_plain.status_code)
        assert r_plain.get_json()["error"]["code"] == "commercial_admin_required"

        r_ent_sysop = client.get(path, headers=_auth(ent_sysop, settings))
        assert r_ent_sysop.status_code == 403, (path, r_ent_sysop.status_code)
        assert r_ent_sysop.get_json()["error"]["code"] == "commercial_admin_required"

        r_non_op = client.get(path, headers=_auth(platform_non_op, settings))
        assert r_non_op.status_code == 403, (path, r_non_op.status_code)
        assert r_non_op.get_json()["error"]["code"] == "commercial_admin_required"

        r_ok = client.get(path, headers=_auth(platform_admin, settings))
        assert r_ok.status_code == 200, (path, r_ok.get_data(as_text=True))
