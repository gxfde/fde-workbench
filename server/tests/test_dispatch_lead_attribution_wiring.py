"""F 线 T3：拉单确权接线回归（ADR-011 §3.4/§5-F；任务书 §4 T3——接 ADR-009）。

- lead 席位三态：零商机行 ⇒ 企业自来（vacant + ``no_sourcer``，平台吸收）；
  归属确认 ⇒ 收款人 ＝ ``attribution_owner_user_id``；归属未确认 ⇒ 409
  ``attribution_not_confirmed``（fail-closed，**不得回落平台代持**）。
- 归属是**本域事实**：同企业多行取已确认行（确认即不可改写）；企业自行注册
  不转移归属（ADR-009 §7-3 反例用例在本域测试文件，此处复用同一字段不重造）。
- 拉单资格＝席位费已缴闸（两条路径：席位 active／科目层 seat_fee 有效行），
  **资格不限角色**；lead 由解析器独占裁定，调用方传 lead 键一律 400。
- 比例快照取 T2 初始基线（active v100），分配行记版本溯源。
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import select

from fde_api.auth.models import User
from fde_api.auth.passwords import hash_password
from fde_api.commercial.attribution_service import submit_opportunity
from fde_api.commercial.models import (
    CommercialEntitlement,
    CommercialOpportunity,
    CommercialRevenueLedger,
)
from fde_api.commercial.service import CommercialServiceError
from fde_api.dispatch.errors import DispatchServiceError
from fde_api.dispatch.models import DispatchSettlementAllocation
from fde_api.dispatch.settlements import (
    allocate_five_seats_with_lead_attribution,
    resolve_lead_seat,
)
from fde_api.workbench.models import Project

from conftest import INITIAL_PASSWORD
from test_commercial_opportunity_attribution import _sha
from test_five_seat_allocations import _context, _payees


def _user(username: str, *, role: str = "fde_engineer") -> User:
    return User(
        username=f"{username}.{uuid4().hex[:8]}",
        display_name=username,
        role=role,
        password_hash=hash_password(INITIAL_PASSWORD),
        must_change_password=False,
        is_active=True,
    )


def _enterprise_code(db_session, package) -> str:
    return db_session.get(Project, package.project_id).enterprise_code


def _opportunity(
    db_session,
    reporter: User,
    enterprise_code: str,
    *,
    owner: User | None = None,
    confirmed: bool = False,
) -> CommercialOpportunity:
    row = CommercialOpportunity(
        enterprise_code=enterprise_code,
        title="f3 归属接线用商机",
        status="attribution_confirmed" if confirmed else "submitted",
        reported_by_user_id=reporter.id,
        source_uri=f"fdeops://f-line-t3/leads/{uuid4().hex[:8]}.md",
        content_hash=_sha(f"t3-{uuid4().hex}"),
    )
    if owner is not None:
        row.attribution_owner_user_id = owner.id
        row.attribution_confirmed_by_user_id = owner.id
        row.attribution_confirmed_at = datetime.now(timezone.utc)
        row.attribution_uri = "fdeops://f-line-t3/attribution/x.pdf"
        row.attribution_hash = _sha("attribution")
    db_session.add(row)
    db_session.flush()
    return row


# ---------------------------------------------------------------------------
# lead 席位三态
# ---------------------------------------------------------------------------


def test_no_attribution_row_lead_vacant_platform_absorbs(db_session):
    """企业自来：零商机行 ⇒ lead vacant＋no_sourcer，平台吸收 lead 席份额。"""
    admin, package, settlement, payment, payees = _context(db_session)
    lead_payee, vacant = resolve_lead_seat(db_session, package)
    assert lead_payee is None
    assert vacant == {"lead": "no_sourcer"}

    rows = allocate_five_seats_with_lead_attribution(
        db_session,
        payment,
        package,
        actor=admin,
        seat_payees=_payees(None, payees["delivery"], payees["county"], payees["province"]),
    )
    by_seat = {row.seat_key: row for row in rows}
    assert by_seat["lead"].status == "vacant"
    assert by_seat["lead"].reason_code == "no_sourcer"
    assert by_seat["lead"].amount == Decimal("0.00")
    assert by_seat["lead"].payee_user_id is None
    # 平台行残差吸收 lead（30 份）＝ 36000+25200 ＝ 61200
    # （ADR-011 §3.4 情形六「企业自来」12 万单：平台 61,200，Σ 恒 ＝ T）
    assert by_seat["platform"].amount == Decimal("61200.00")
    assert by_seat["province"].amount == Decimal("8400.00")
    assert sum(row.amount for row in rows) == settlement.base_amount


def test_confirmed_attribution_pays_owner(db_session):
    """归属确认 ⇒ lead 收款人 ＝ attribution_owner_user_id（本域事实）。"""
    admin, package, settlement, payment, payees = _context(db_session)
    owner = _user("f3.owner")
    db_session.add(owner)
    db_session.flush()
    _opportunity(
        db_session,
        admin,
        _enterprise_code(db_session, package),
        owner=owner,
        confirmed=True,
    )

    rows = allocate_five_seats_with_lead_attribution(
        db_session,
        payment,
        package,
        actor=admin,
        seat_payees=_payees(None, payees["delivery"], payees["county"], None),
        vacant_reasons={"province": "no_province_partner"},
        confirm_password=INITIAL_PASSWORD,  # T4：空缺人工确认双闸
    )
    by_seat = {row.seat_key: row for row in rows}
    assert by_seat["lead"].payee_user_id == owner.id
    assert by_seat["lead"].status == "paid"
    assert by_seat["lead"].amount == Decimal("25200.00")  # 池内 30 份 × 840
    assert by_seat["platform"].amount == Decimal("44400.00")  # 36000＋province 吸收 8400（§3.4 情形二）
    assert sum(row.amount for row in rows) == settlement.base_amount


def test_unconfirmed_attribution_fail_closed_409(db_session):
    """归属未确认 ⇒ 409 attribution_not_confirmed，且零写入（fail-closed）。"""
    admin, package, settlement, payment, payees = _context(db_session)
    reporter = _user("f3.reporter")
    db_session.add(reporter)
    db_session.flush()
    _opportunity(db_session, reporter, _enterprise_code(db_session, package))

    with pytest.raises(DispatchServiceError) as excinfo:
        allocate_five_seats_with_lead_attribution(
            db_session,
            payment,
            package,
            actor=admin,
            seat_payees=_payees(None, payees["delivery"], payees["county"], None),
            vacant_reasons={"province": "no_province_partner"},
        )
    assert excinfo.value.code == "attribution_not_confirmed"
    assert excinfo.value.status == 409
    # 零写入：整事务拒绝后不残留任何明细行
    rows = db_session.scalars(
        select(DispatchSettlementAllocation).where(
            DispatchSettlementAllocation.settlement_id == settlement.id
        )
    ).all()
    assert rows == []


def test_confirmed_row_wins_over_later_unconfirmed_row(db_session):
    """归属是本域事实：同企业多行取已确认行（后报的未确认行不夺走归属）。

    企业自行注册不转移归属的保证由 ADR-009 反例用例承载（本域测试文件），
    此处钉住接线层读的是**归属事实字段**而不是「最新报备话语权」。"""
    admin, package, settlement, payment, payees = _context(db_session)
    code = _enterprise_code(db_session, package)
    owner = _user("f3.owner2")
    late_reporter = _user("f3.late")
    db_session.add_all([owner, late_reporter])
    db_session.flush()
    confirmed = _opportunity(
        db_session, admin, code, owner=owner, confirmed=True
    )
    late = _opportunity(db_session, late_reporter, code)
    assert late.created_at >= confirmed.created_at  # 后报的行不改变解析结果

    lead_payee, vacant = resolve_lead_seat(db_session, package)
    assert lead_payee == owner.id
    assert vacant == {}


def test_caller_cannot_specify_lead_seat(db_session):
    """lead 由归属事实独占裁定：调用方传 lead 键一律 400。"""
    admin, package, settlement, payment, payees = _context(db_session)
    with pytest.raises(DispatchServiceError) as excinfo:
        allocate_five_seats_with_lead_attribution(
            db_session,
            payment,
            package,
            actor=admin,
            seat_payees=_payees(payees["lead"], payees["delivery"], payees["county"], None),
            vacant_reasons={"province": "no_province_partner"},
        )
    assert excinfo.value.code == "invalid_request"
    assert excinfo.value.status == 400


def test_allocation_records_active_version_provenance(db_session):
    """T2×T3 接线：分配行 rule_version_id ＝ 当前 active 规则版本（基线 v100）。"""
    from fde_api.dispatch.models import DispatchRuleVersion
    from fde_api.dispatch.rules import active_rule_version

    admin, package, settlement, payment, payees = _context(db_session)
    rows = allocate_five_seats_with_lead_attribution(
        db_session,
        payment,
        package,
        actor=admin,
        seat_payees=_payees(None, payees["delivery"], payees["county"], payees["province"]),
    )
    version = active_rule_version(db_session)
    assert version is not None and version.version_no == 100
    assert all(row.rule_version_id == version.id for row in rows)


# ---------------------------------------------------------------------------
# 拉单资格：席位费已缴闸（两条路径）
# ---------------------------------------------------------------------------


def test_reporter_seat_gate_entitlement_path(db_session):
    """资格闸路径①：席位 active（未分层用户）⇒ 报备放行。"""
    reporter = _user("f3.seat.reporter")
    admin = _user("f3.seat.admin", role="admin")
    db_session.add_all([reporter, admin])
    db_session.flush()
    from fde_api.commercial.service import activate_seat

    activate_seat(
        db_session,
        actor=admin,
        user_id=reporter.id,
        seat_source="bootcamp_practical",
        expires_at="2027-12-31T00:00:00Z",
        confirm_password=INITIAL_PASSWORD,
    )
    data = submit_opportunity(
        db_session,
        actor=reporter,
        enterprise_code="somwyn.hz.demo",
        title="席位费路径报备",
        source_uri="fdeops://f-line-t3/seat-path.md",
        content_hash=_sha("seat-path"),
    )
    assert data["opportunity"]["status"] == "submitted"


def test_reporter_seat_gate_ledger_path(db_session):
    """资格闸路径②：科目层 seat_fee 有效行（无 entitlement 席位）⇒ 放行。"""
    reporter = _user("f3.ledger.reporter")
    db_session.add(reporter)
    db_session.flush()
    db_session.add(
        CommercialRevenueLedger(
            subject_type="seat_fee",
            line_item="software_subscription",
            status="recorded",
            amount=Decimal("3980.00"),
            subject_user_id=reporter.id,
            recorded_by_user_id=reporter.id,
            package_code="first_delivery",
            seat_source="first_delivery",
            source_uri="fdeops://f-line-t3/seat-fee.md",
            content_hash=_sha("seat-fee"),
        )
    )
    db_session.flush()
    data = submit_opportunity(
        db_session,
        actor=reporter,
        enterprise_code="somwyn.hz.demo",
        title="科目层路径报备",
        source_uri="fdeops://f-line-t3/ledger-path.md",
        content_hash=_sha("ledger-path"),
    )
    assert data["opportunity"]["status"] == "submitted"


def test_reporter_seat_gate_fail_closed(db_session):
    """两路径都不成立 ⇒ 403 opportunity_reporter_seat_required（角色不算资格）。"""
    reporter = _user("f3.noseat.reporter")
    db_session.add(reporter)
    db_session.flush()
    db_session.add(
        CommercialEntitlement(user_id=reporter.id, commercial_role="R2")
    )
    db_session.flush()
    with pytest.raises(CommercialServiceError) as excinfo:
        submit_opportunity(
            db_session,
            actor=reporter,
            enterprise_code="somwyn.hz.demo",
            title="无席位报备",
            source_uri="fdeops://f-line-t3/noseat.md",
            content_hash=_sha("noseat"),
        )
    assert excinfo.value.code == "opportunity_reporter_seat_required"
    assert excinfo.value.status == 403


def test_expired_seat_does_not_qualify(db_session):
    """席位 active 但已过期 ⇒ 资格闸不放行（「有效」含未过期）。"""
    from datetime import datetime as dt

    reporter = _user("f3.expired.reporter")
    db_session.add(reporter)
    db_session.flush()
    db_session.add(
        CommercialEntitlement(
            user_id=reporter.id,
            seat_status="active",
            seat_source="bootcamp_practical",
            seat_expires_at=dt.now(timezone.utc) - timedelta(days=1),
        )
    )
    db_session.flush()
    with pytest.raises(CommercialServiceError) as excinfo:
        submit_opportunity(
            db_session,
            actor=reporter,
            enterprise_code="somwyn.hz.demo",
            title="过期席位报备",
            source_uri="fdeops://f-line-t3/expired.md",
            content_hash=_sha("expired"),
        )
    assert excinfo.value.code == "opportunity_reporter_seat_required"
