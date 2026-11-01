"""goal-r2 P0 簇②表建设回归（派单设计 §8.3：P0-3/P0-4/P0-7/P0-8）。

- P0-3（§3.3）：L1/L2 晋级证据链用例——判据不足 422，全过写
  fde_level_evidence + 更新 fde_profiles.level + 审计事件。
- P0-4（§7.2/§7.4）：7 条里程碑 × 四席位拆分（Σ四席位=实收基数）+
  累计预扣链 + 状态机 draft→accrued→payable→paid/disputed + G8 过门联动。
- P0-7（§6.2）：派单常数只读节 + PUT 可写集精确等值拒绝。
- P0-8（§6.2/规则表 B9）：30 天公示窗强制 + 版本切换后旧 offer 仍指旧版权本。
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import select

from fde_api.auth.models import User
from fde_api.auth.passwords import hash_password
from fde_api.auth.tokens import issue_access_token
from fde_api.dispatch.errors import DispatchServiceError
from fde_api.dispatch.models import (
    DeliveryPackage,
    DeliverySettlement,
    DispatchOffer,
    DispatchRuleVersion,
    FdeLevelEvidence,
    FdeProfile,
)
from fde_api.dispatch.profiles import promote_user
from fde_api.meetings.models import ReviewMeeting, ReviewMeetingMinutes
from fde_api.dispatch.rules import (
    activate_due_versions,
    active_rule_snapshot,
    create_rule_version,
    default_rule_snapshot,
)
from fde_api.dispatch.settlements import (
    compute_withholding,
    mark_disputed,
    mark_paid,
    mark_payable,
    record_receipt_settlements,
    seat_shares_for,
    split_four_seats,
)
from fde_api.projects.payment_service import (
    mark_acceptance_passed,
    update_payment,
)
from fde_api.solutions.models import ProjectSolution
from fde_api.system_configuration import DISPATCH_CONSTANTS, PUBLIC_FIELDS
from fde_api.workbench.models import (
    Gate,
    IndustryTemplate,
    IndustryTemplateVersion,
    OperationEvent,
    Payment,
    Project,
    Quote,
)
from fde_api.workbench.seed import GENERIC_TEMPLATE_KEY, seed_workbench

from conftest import INITIAL_PASSWORD

SHA256 = hashlib.sha256(b"goal-r2-evidence").hexdigest()
BASE_SHARES = {"platform": 35, "region": 5, "city": 20, "delivery": 40}
COLD_SHARES = {"platform": 40, "region": 5, "city": 15, "delivery": 40}


@dataclass(frozen=True)
class AuthorizedClient:
    client: object
    user: User
    headers: dict[str, str]

    def get(self, *args, **kwargs):
        return self.client.get(*args, headers=self.headers, **kwargs)

    def post(self, *args, **kwargs):
        return self.client.post(*args, headers=self.headers, **kwargs)

    def patch(self, *args, **kwargs):
        return self.client.patch(*args, headers=self.headers, **kwargs)

    def put(self, *args, **kwargs):
        return self.client.put(*args, headers=self.headers, **kwargs)


def _user(username: str, role: str = "admin") -> User:
    return User(
        username=f"{username}.{uuid4().hex[:8]}",
        display_name=username,
        role=role,
        password_hash=hash_password(INITIAL_PASSWORD),
        must_change_password=False,
        is_active=True,
    )


def _authorized(client, settings, user: User) -> AuthorizedClient:
    return AuthorizedClient(
        client, user, {"Authorization": f"Bearer {issue_access_token(user, settings)}"}
    )


def _template(db_session) -> IndustryTemplateVersion:
    template = IndustryTemplate(
        template_key=f"r2-tpl-{uuid4().hex[:8]}",
        name="r2 模板",
        industry_name="制造业",
    )
    version = IndustryTemplateVersion(
        template=template,
        name="r2 模板 v1",
        industry_name="制造业",
        version_number=1,
        status="published",
    )
    db_session.add(version)
    db_session.flush()
    return version


def _project(db_session, template, *, enterprise_code: str, leader: User) -> Project:
    project = Project(
        project_code=f"R2-{uuid4().hex[:6].upper()}",
        name=f"r2 项目 {enterprise_code}",
        enterprise_code=enterprise_code,
        planned_start_date=date(2026, 10, 31),
        leader_user_id=leader.id,
        source_template_version=template,
        template_snapshot={"industry_name": "制造业", "modules": []},
    )
    db_session.add(project)
    db_session.flush()
    return project


def _package(
    db_session,
    project: Project,
    *,
    seat_delivery: str,
    sow_type: str | None,
    quote: Quote | None = None,
    accepted: bool = True,
    accepted_at: datetime | None = None,
) -> DeliveryPackage:
    solution = ProjectSolution(
        project_id=project.id,
        name=f"方案 {project.project_code}",
        owner_user_id=project.leader_user_id,
    )
    db_session.add(solution)
    db_session.flush()
    package = DeliveryPackage(
        id=solution.id,
        solution_id=solution.id,
        project_id=project.id,
        package_code=f"PKG-{uuid4().hex[:10].upper()}",
        quote_id=quote.id if quote is not None else None,
        sow_type=sow_type,
        dispatch_status="accepted" if accepted else "draft",
        accepted_at=accepted_at or datetime.now(timezone.utc),
        accepted_user_id=seat_delivery,
        seat_delivery=seat_delivery,
    )
    db_session.add(package)
    db_session.flush()
    return package


def _quote(
    db_session,
    project: Project,
    *,
    branch: str = "A",
    b_layer_score: int = 0,
    status: str = "finalized",
    measured: bool = True,
) -> Quote:
    quote = Quote(
        project_id=project.id,
        quote_key=f"Q-{uuid4().hex[:8]}",
        status=status,
        tier="light",
        ideal_hours=Decimal("100"),
        realistic_hours=Decimal("100"),
        integration_factor=Decimal("1.00"),
        data_factor=Decimal("1.00"),
        compliance_factor=Decimal("1.00"),
        buffer_factor=Decimal("1.00"),
        hourly_rate=150,
        cash_cost=100000,
        margin_factor=Decimal("1.40"),
        b_layer_score=b_layer_score,
        b_layer_factor=Decimal("1.00"),
        anchor_mode="steady",
        labor_cost=Decimal("100000"),
        total_cost=Decimal("100000"),
        formula_price=Decimal("200000"),
        anchor_low=200000,
        anchor_high=300000,
        branch=branch,
        final_amount=Decimal("250000") if status == "finalized" else None,
        field_claims={"final_amount": "measured"} if measured else {},
    )
    db_session.add(quote)
    db_session.flush()
    return quote


def _payment(
    db_session,
    project: Project,
    milestone_key: str,
    sow_type: str,
    *,
    amount: str = "10000",
    received: bool = True,
    invoice_no: str | None = None,
) -> Payment:
    row = Payment(
        project_id=project.id,
        milestone_key=milestone_key,
        sow_type=sow_type,
        collects="r2 里程碑",
        timing="按合同",
        amount=Decimal(amount),
        received_amount=Decimal(amount) if received else None,
        received_at=date(2026, 10, 31) if received else None,
        invoice_no=invoice_no,
        source_uri=f"fdeops://goal-r2/{project.project_code}/{milestone_key}",
        content_hash=SHA256,
    )
    db_session.add(row)
    db_session.flush()
    return row


def _g8_passed(db_session, project: Project) -> Gate:
    gate = Gate(project_id=project.id, gate_key="G8", status="passed")
    db_session.add(gate)
    db_session.flush()
    return gate


# ---------------------------------------------------------------------------
# P0-3：L1/L2 晋级证据链（§3.3）
# ---------------------------------------------------------------------------


def _l1_context(db_session):
    admin = _user("r2.promoter", role="admin")
    fde = _user("r2.fde.candidate", role="fde_engineer")
    template = _template(db_session)
    db_session.add_all([admin, fde])
    profile = FdeProfile(
        user_id=fde.id,
        biz_cognition_score=2,
        scenario_eng_score=3,
        ai_tech_score=2,
        delivery_assure_score=2,
    )
    db_session.add(profile)
    project = _project(
        db_session, template, enterprise_code=f"r2 企业·{uuid4().hex[:6]}", leader=admin
    )
    quote = _quote(db_session, project)
    _package(db_session, project, seat_delivery=fde.id, sow_type="a", quote=quote)
    _g8_passed(db_session, project)
    db_session.flush()
    return admin, fde, profile, project, template


def test_l1_promotion_evidence_chain(db_session):
    """P0-3 判据：单据客观记录全过 → 证据链落库 + 档案更新 + 审计事件。"""
    admin, fde, profile, project, _template = _l1_context(db_session)

    evidence = promote_user(
        db_session,
        actor=admin,
        user_id=fde.id,
        to_level="L1",
        source_uri="fdeops://goal-r2/promotion/L1",
        source_sha256=SHA256,
    )
    db_session.flush()

    assert evidence.from_level is None
    assert evidence.to_level == "L1"
    assert evidence.verified_by_user_id == admin.id
    assert evidence.evidence_summary["independent_deliveries"] == 1
    assert evidence.evidence_summary["finalized_quote_deliveries"] == 1
    db_session.refresh(profile)
    assert profile.level == "L1"
    assert profile.level_verified_at is not None
    assert profile.level_evidence_id == evidence.id

    event = db_session.scalar(
        select(OperationEvent).where(
            OperationEvent.event_type == "fde_level_promoted",
            OperationEvent.target_id == fde.id,
        )
    )
    assert event is not None
    assert event.target_type == "user"
    assert event.changes["to_level"] == "L1"
    assert event.changes["evidence_id"] == evidence.id


def test_l1_promotion_rejected_without_delivered_fact(db_session):
    """判据不足 → 422 level_evidence_insufficient，deficits 指明缺口。"""
    admin, fde, profile, project, _template = _l1_context(db_session)
    # 拆掉唯一一单的 G8 过门事实（dispatch_status 回 draft）
    package = db_session.scalar(select(DeliveryPackage).where(DeliveryPackage.project_id == project.id))
    package.dispatch_status = "draft"
    db_session.flush()

    with pytest.raises(DispatchServiceError) as excinfo:
        promote_user(
            db_session,
            actor=admin,
            user_id=fde.id,
            to_level="L1",
            source_uri="fdeops://goal-r2/promotion/L1",
            source_sha256=SHA256,
        )
    assert excinfo.value.code == "level_evidence_insufficient"
    assert excinfo.value.status == 422
    assert "independent_deliveries<1" in excinfo.value.message


def test_promotion_verifier_must_be_platform_side(db_session):
    admin, fde, _profile, _project, _template = _l1_context(db_session)
    with pytest.raises(DispatchServiceError) as excinfo:
        promote_user(
            db_session,
            actor=_user("r2.not.verifier", role="fde_engineer"),
            user_id=fde.id,
            to_level="L1",
            source_uri="fdeops://x",
            source_sha256=SHA256,
        )
    assert excinfo.value.code == "verifier_role_required"
    assert excinfo.value.status == 403
    assert admin.id  # 上下文保活：admin 仅用于建数据


def test_l2_promotion_requires_repurchase_and_mentee(db_session):
    """P0-3 判据：L2 三单 + 复购 + 带教 + 四域下限，缺带教 422，补齐后晋级。"""
    admin, fde, profile, project1, template = _l1_context(db_session)
    promote_user(
        db_session,
        actor=admin,
        user_id=fde.id,
        to_level="L1",
        source_uri="fdeops://goal-r2/promotion/L1",
        source_sha256=SHA256,
    )
    enterprise = project1.enterprise_code
    # 第 2 单：同企业（凑复购）+ 第 3 单：新企业
    project2 = _project(db_session, template, enterprise_code=enterprise, leader=admin)
    quote2 = _quote(db_session, project2)
    _package(db_session, project2, seat_delivery=fde.id, sow_type="a", quote=quote2)
    _g8_passed(db_session, project2)
    project3 = _project(db_session, template, enterprise_code=f"r2 新企业·{uuid4().hex[:6]}", leader=admin)
    _quote(db_session, project3)
    _package(db_session, project3, seat_delivery=fde.id, sow_type="a")
    _g8_passed(db_session, project3)
    db_session.flush()

    with pytest.raises(DispatchServiceError) as excinfo:
        promote_user(
            db_session,
            actor=admin,
            user_id=fde.id,
            to_level="L2",
            source_uri="fdeops://goal-r2/promotion/L2",
            source_sha256=SHA256,
        )
    assert excinfo.value.code == "level_evidence_insufficient"
    assert "mentees<1" in excinfo.value.message

    mentee = _user("r2.mentee", role="fde_engineer")
    db_session.add(mentee)
    db_session.flush()
    db_session.add(
        FdeLevelEvidence(
            user_id=mentee.id,
            from_level=None,
            to_level="L1",
            verified_by_user_id=fde.id,
            verified_at=datetime.now(timezone.utc),
            source_uri="fdeops://goal-r2/mentee/L1",
            source_sha256=SHA256,
        )
    )
    db_session.flush()

    evidence = promote_user(
        db_session,
        actor=admin,
        user_id=fde.id,
        to_level="L2",
        source_uri="fdeops://goal-r2/promotion/L2",
        source_sha256=SHA256,
    )
    db_session.flush()
    assert evidence.from_level == "L1"
    assert evidence.to_level == "L2"
    summary = evidence.evidence_summary
    assert summary["independent_deliveries"] == 3
    assert summary["repurchase_ok"] is True
    assert summary["mentees"]["any"] == 1
    db_session.refresh(profile)
    assert profile.level == "L2"


# ---------------------------------------------------------------------------
# P0-4：7 里程碑 × 四席位 + 累计预扣 + 状态机
# ---------------------------------------------------------------------------


def _settlement_context(db_session, *, with_profile_city: bool = False):
    """4 个项目（SOW a/b/c/d）× 已接交付包 × G8 过门 × 7 条里程碑实收。

    with_profile_city=True 时：档案 home_city 故意取「深圳」≠ 包侧客户城「杭州」
    （三段代号第三段）——留注⑤ 终版口径的回归钉：冷启动判定只认包侧城市，
    若实现回退到 home_city 代理，序号口径即错（第 4 单误判冷启动）。"""
    admin = _user("r2.settle.admin")
    fde = _user("r2.settle.fde", role="fde_engineer")
    template = _template(db_session)
    db_session.add_all([admin, fde])
    if with_profile_city:
        db_session.add(FdeProfile(user_id=fde.id, home_city="深圳"))
    context = {}
    for sow, keys in (
        ("a", ("G3",)),
        ("b", ("G4", "G8")),
        ("c", ("SOW-C M1", "SOW-C M2", "SOW-C M3")),
        ("d", ("D",)),
    ):
        project = _project(
            db_session,
            template,
            enterprise_code=(
                f"r2 结算{sow}·行业·杭州" if with_profile_city else f"r2 结算 {sow}·{uuid4().hex[:6]}"
            ),
            leader=admin,
        )
        _package(db_session, project, seat_delivery=fde.id, sow_type=sow)
        _g8_passed(db_session, project)
        context[sow] = {
            "project": project,
            "payments": [
                _payment(db_session, project, key, sow) for key in keys
            ],
        }
    db_session.flush()
    return admin, fde, context


def test_seven_milestones_four_seats_and_cumulative_withholding(db_session):
    """P0-4 判据：7 条里程碑逐笔四席位拆分（Σ=基数）+ §7.4 累计预扣链。"""
    admin, fde, context = _settlement_context(db_session)

    for sow in ("a", "b", "c", "d"):
        block = context[sow]
        for payment in block["payments"]:
            record_receipt_settlements(
                db_session, actor=admin, project=block["project"], payment=payment
            )
        db_session.flush()
        # G8 过门 → 验收打标 + 计提（按里程碑键序，可复算）
        result = mark_acceptance_passed(db_session, admin, block["project"].id)
        db_session.flush()
        assert result["payments_marked"] == len(block["payments"])

    settlements = db_session.scalars(
        select(DeliverySettlement).order_by(DeliverySettlement.created_at, DeliverySettlement.settlement_key)
    ).all()
    assert len(settlements) == 7

    by_key = {row.settlement_key: row for row in settlements}
    # 四席位 35/5/20/40（项目代号两段=无包侧客户城 → 无冷启动例外）
    for key in ("G3", "G4", "G8", "SOW-C M1", "SOW-C M2", "SOW-C M3", "D"):
        row = by_key[key]
        assert row.status == "accrued"
        assert row.base_amount == Decimal("10000")
        assert (row.platform_amount, row.region_amount, row.city_amount, row.delivery_amount) == (
            Decimal("3500"),
            Decimal("500"),
            Decimal("2000"),
            Decimal("4000"),
        )
        assert (
            row.platform_amount + row.region_amount + row.city_amount + row.delivery_amount
            == row.base_amount
        )

    # §7.4 累计预扣链（计提序 G3→G4→G8→M1→M2→M3→D，同月 5000 减除）
    expected_withholding = {
        "G3": Decimal("0"),    # 4000×80% − 5000 < 0
        "G4": Decimal("42"),   # 8000×80% − 5000 = 1400 × 3%
        "G8": Decimal("96"),
        "SOW-C M1": Decimal("96"),
        "SOW-C M2": Decimal("96"),
        "SOW-C M3": Decimal("96"),
        "D": Decimal("96"),
    }
    for key, expected in expected_withholding.items():
        assert by_key[key].withholding_tax == expected, key

    total = sum((row.withholding_tax for row in settlements), Decimal(0))
    assert total == Decimal("522")  # 28000×80% − 5000 = 17400 × 3%
    assert by_key["D"].acceptance_passed_at is not None


def test_cold_start_shares_first_three_city_orders(db_session):
    """§7.1 冷启动：同城（包侧客户城，留注⑤ 终版口径）前 3 单 40/5/15/40
    （上浮自城市合伙人扣），第 4 单回基准。档案 home_city（深圳）≠包侧城（杭州）
    ——判定只认包侧，home_city 代理已退役。"""
    admin, fde, context = _settlement_context(db_session, with_profile_city=True)
    now = datetime.now(timezone.utc)
    packages = db_session.scalars(
        select(DeliveryPackage).order_by(DeliveryPackage.created_at)
    ).all()
    assert len(packages) == 4
    for offset, package in enumerate(packages):
        package.accepted_at = now - timedelta(hours=5 - offset)
    db_session.flush()

    shares = [seat_shares_for(db_session, package) for package in packages]
    assert shares[0] == COLD_SHARES
    assert shares[1] == COLD_SHARES
    assert shares[2] == COLD_SHARES
    assert shares[3] == BASE_SHARES

    split = split_four_seats(Decimal("10000"), COLD_SHARES)
    assert split == {
        "platform": Decimal("4000"),
        "region": Decimal("500"),
        "city": Decimal("1500"),
        "delivery": Decimal("4000"),
    }
    assert sum(split.values(), Decimal(0)) == Decimal("10000")
    assert admin.id  # 上下文保活


def test_settlement_state_machine_invoice_proof_dispute(db_session):
    """§7.2 状态机：accrued→payable 须发票；paid 须凭证指针；争议挂 disputed。"""
    admin, fde, context = _settlement_context(db_session)
    block = context["b"]
    for payment in block["payments"]:
        record_receipt_settlements(
            db_session, actor=admin, project=block["project"], payment=payment
        )
    mark_acceptance_passed(db_session, admin, block["project"].id)
    db_session.flush()
    rows = {
        row.settlement_key: row
        for row in db_session.scalars(
            select(DeliverySettlement).where(
                DeliverySettlement.package_id.in_(
                    select(DeliveryPackage.id).where(
                        DeliveryPackage.project_id == block["project"].id
                    )
                )
            )
        )
    }
    g8_row = rows["G8"]
    assert g8_row.status == "accrued"

    # 发票前置：未登记发票 → 422
    with pytest.raises(DispatchServiceError) as excinfo:
        mark_payable(db_session, actor=admin, settlement_id=g8_row.id)
    assert excinfo.value.code == "invoice_required"
    assert excinfo.value.status == 422

    g8_payment = next(p for p in block["payments"] if p.milestone_key == "G8")
    g8_payment.invoice_no = "INV-2026-888"
    db_session.flush()
    payable = mark_payable(db_session, actor=admin, settlement_id=g8_row.id)
    assert payable["status"] == "payable"

    paid = mark_paid(
        db_session,
        actor=admin,
        settlement_id=g8_row.id,
        paid_proof_source_uri="fdeops://goal-r2/paid/G8",
    )
    assert paid["status"] == "paid"
    db_session.refresh(g8_row)
    assert g8_row.paid_proof_source_uri == "fdeops://goal-r2/paid/G8"
    assert g8_row.paid_at is not None

    with pytest.raises(DispatchServiceError) as excinfo:
        mark_paid(
            db_session,
            actor=admin,
            settlement_id=g8_row.id,
            paid_proof_source_uri="fdeops://again",
        )
    assert excinfo.value.code == "invalid_settlement_state"

    # 争议入口：draft 也可 disputed；disputed 不能再转 payable
    g4_row = rows["G4"]
    disputed = mark_disputed(
        db_session, actor=admin, settlement_id=g4_row.id, reason="对账差异 > ±1 元"
    )
    assert disputed["status"] == "disputed"
    g4_payment = next(p for p in block["payments"] if p.milestone_key == "G4")
    g4_payment.invoice_no = "INV-2026-889"
    db_session.flush()
    with pytest.raises(DispatchServiceError) as excinfo:
        mark_payable(db_session, actor=admin, settlement_id=g4_row.id)
    assert excinfo.value.code == "invalid_settlement_state"


def test_withholding_zero_for_small_first_settlement(db_session):
    """§7.4：首笔小额（累计应纳税所得额 ≤0）预扣为 0，不产生负数。"""
    admin = _user("r2.tax.admin")
    db_session.add(admin)
    tax = compute_withholding(
        db_session, delivery_user_id=uuid4().hex, current_amount=Decimal("4000")
    )
    assert tax == Decimal("0")
    assert admin.id  # 上下文保活


# ---------------------------------------------------------------------------
# P0-4：G8 过门 → 验收打标 → 计提（API 级全链路）
# ---------------------------------------------------------------------------


@pytest.fixture
def g8_project(client, db_session, settings):
    """admin 建项（leader 双主体）+ 已接包 + B 型两条收款计划。"""
    seed_workbench(db_session)
    db_session.commit()
    template = db_session.scalar(
        select(IndustryTemplateVersion)
        .join(IndustryTemplate)
        .where(
            IndustryTemplateVersion.status == "published",
            IndustryTemplate.template_key == GENERIC_TEMPLATE_KEY,
        )
    )
    admin = _user("r2.g8.admin")
    leader = _user("r2.g8.lead", role="project_lead")
    fde = _user("r2.g8.fde", role="fde_engineer")
    db_session.add_all([admin, leader, fde])
    db_session.commit()

    admin_client = _authorized(client, settings, admin)
    response = admin_client.post(
        "/api/v1/projects",
        json={
            "name": "r2 G8 联动项目",
            # 服务层代号格式校验：三段两枚「·」（客户·行业·城市）
            "enterprise_code": f"r2 企业·制造·{uuid4().hex[:8]}",
            "template_version_id": template.id,
            "leader_user_id": leader.id,
            "planned_start_date": "2026-08-21",
            "module_keys": ["pre_diagnosis"],
        },
    )
    assert response.status_code == 201, response.get_data(as_text=True)
    project = response.json["data"]
    activated = admin_client.patch(
        f"/api/v1/projects/{project['id']}",
        json={"version": project["version"], "status": "active"},
    )
    assert activated.status_code == 200, activated.get_data(as_text=True)
    gates_url = f"/api/v1/projects/{project['id']}/gates"
    assert admin_client.get(gates_url).status_code == 200
    db_session.commit()

    project_row = db_session.scalar(
        select(Project).where(Project.id == project["id"])
    )
    _package(db_session, project_row, seat_delivery=fde.id, sow_type="b")
    _payment(db_session, project_row, "G4", "b", received=False)
    _payment(db_session, project_row, "G8", "b", received=False)
    db_session.commit()
    return {
        "admin": admin,
        "leader": leader,
        "fde": fde,
        "admin_client": admin_client,
        "leader_client": _authorized(client, settings, leader),
        "project_id": project["id"],
        "gates_url": gates_url,
    }


def _submit_all_evidence(authorized: AuthorizedClient, gates_url: str, gate_key: str):
    gates = authorized.get(gates_url).json["data"]["gates"]
    gate = next(g for g in gates if g["gate_key"] == gate_key)
    response = authorized.post(
        f"{gates_url}/{gate_key}/evidence",
        json={
            "items": [
                {
                    "label": item["label"],
                    "source_uri": f"fdeops://goal-r2/{gate_key}",
                    "content_hash": hashlib.sha256(item["label"].encode()).hexdigest(),
                }
                for item in gate["checklist"]
            ]
        },
    )
    assert response.status_code == 200, response.get_data(as_text=True)


def test_g8_pass_marks_acceptance_and_accrues_settlements(g8_project, db_session):
    """P0-4 全链路：实收→草稿；G8 过门→打标+计提；晚到尾款→收款即补计提。"""
    project_id = g8_project["project_id"]

    # ① G4 实收 → 结算草稿（四席位 35/5/20/40）
    update_payment(
        actor=g8_project["admin"],
        project_id=project_id,
        milestone_key="G4",
        payload={"received_amount": 10000},
    )
    g4_settlement = db_session.scalar(
        select(DeliverySettlement).where(DeliverySettlement.settlement_key == "G4")
    )
    assert g4_settlement is not None
    assert g4_settlement.status == "draft"
    assert g4_settlement.delivery_amount == Decimal("4000")

    # ② 执行人 admin 提交证据，leader 拍板过门（P0-5 分离 + P0-4 联动）
    _submit_all_evidence(g8_project["admin_client"], g8_project["gates_url"], "G8")
    decided = g8_project["leader_client"].post(
        f"{g8_project['gates_url']}/G8/decision",
        json={"result": "pass", "decision": "proceed"},
    )
    assert decided.status_code == 200, decided.get_data(as_text=True)
    acceptance = decided.json["data"]["acceptance_marked"]
    assert acceptance == {"payments_marked": 1, "settlements_accrued": 1}

    db_session.expire_all()
    g4_settlement = db_session.scalar(
        select(DeliverySettlement).where(DeliverySettlement.settlement_key == "G4")
    )
    assert g4_settlement.status == "accrued"
    assert g4_settlement.acceptance_passed_at is not None
    assert g4_settlement.withholding_tax == Decimal("0")

    # ③ 尾款晚到：收款回填时 G8 已过门 → 立即打标并补计提
    update_payment(
        actor=g8_project["admin"],
        project_id=project_id,
        milestone_key="G8",
        payload={"received_amount": 10000},
    )
    db_session.expire_all()
    g8_settlement = db_session.scalar(
        select(DeliverySettlement).where(DeliverySettlement.settlement_key == "G8")
    )
    assert g8_settlement is not None
    assert g8_settlement.status == "accrued"
    # 累计 8000×80% − 5000 = 1400 × 3% − 已预扣 0
    assert g8_settlement.withholding_tax == Decimal("42")
    g8_payment = db_session.scalar(
        select(Payment).where(Payment.project_id == project_id, Payment.milestone_key == "G8")
    )
    assert g8_payment.acceptance_passed_at is not None


# ---------------------------------------------------------------------------
# P0-7：派单常数只读节 + PUT 精确等值拒绝
# ---------------------------------------------------------------------------


def test_dispatch_constants_readonly_via_configuration_api(client, db_session, settings):
    admin = _user("r2.config.admin")
    db_session.add(admin)
    db_session.commit()
    admin_client = _authorized(client, settings, admin)

    current = admin_client.get("/api/v1/system/configuration")
    assert current.status_code == 200
    payload = current.json["data"]

    # 只读节暴露 §6.2/§7.1 全部常数
    constants = payload["dispatch_constants"]
    assert constants["response_window_hours"] == 24
    assert constants["appeal_sla_hours"] == 48
    assert constants["weight_public_notice_days"] == 30
    assert constants["seat_shares"] == BASE_SHARES
    assert constants["cold_start_seat_shares"] == COLD_SHARES
    assert constants["stage_b_weights"] == {
        "level": 40,
        "industry": 30,
        "sla": 20,
        "geo_remote": 10,
    }
    # 派单常数不进 PUT 可写集（P0-7「锁定不可运行时改」）
    assert "dispatch_constants" not in payload["values"]
    assert set(payload["values"]) == PUBLIC_FIELDS
    assert not (set(PUBLIC_FIELDS) & set(DISPATCH_CONSTANTS))

    # PUT 多带派单常数键 → set 等值校验拒 400
    values = dict(payload["values"])
    values["response_window_hours"] = 48
    response = admin_client.put(
        "/api/v1/system/configuration",
        json={"values": values, "secrets": {}, "clear_secrets": [], "version": payload["version"]},
    )
    assert response.status_code == 400
    assert response.json["error"]["code"] == "invalid_configuration"

    # 源码级只读：MappingProxyType 禁改
    with pytest.raises(TypeError):
        DISPATCH_CONSTANTS["response_window_hours"] = 48  # type: ignore[index]


# ---------------------------------------------------------------------------
# P0-8：规则版本 30 天公示窗 + 旧 offer 永指当时版本
# ---------------------------------------------------------------------------


def test_rule_version_notice_window_and_role_guard(db_session):
    admin = _user("r2.rules.admin")
    lead = _user("r2.rules.lead", role="project_lead")
    db_session.add_all([admin, lead])
    db_session.flush()
    now = datetime.now(timezone.utc)

    with pytest.raises(DispatchServiceError) as excinfo:
        create_rule_version(
            db_session,
            actor=lead,
            version_no=1,
            rule_snapshot=default_rule_snapshot(),
            effective_at=now + timedelta(days=40),
        )
    assert excinfo.value.code == "verifier_role_required"
    assert excinfo.value.status == 403

    # 公示窗强制：生效日早于发布日 + 30 天 → 422
    with pytest.raises(DispatchServiceError) as excinfo:
        create_rule_version(
            db_session,
            actor=admin,
            version_no=1,
            rule_snapshot=default_rule_snapshot(),
            published_at=now,
            effective_at=now + timedelta(days=29),
        )
    assert excinfo.value.code == "notice_window_required"
    assert excinfo.value.status == 422

    v1 = create_rule_version(
        db_session,
        actor=admin,
        version_no=1,
        rule_snapshot=default_rule_snapshot(),
        published_at=now - timedelta(days=40),
        effective_at=now - timedelta(days=10),
    )
    db_session.flush()
    assert v1.status == "published"
    assert activate_due_versions(db_session, now=now) == 1
    db_session.refresh(v1)
    assert v1.status == "active"
    assert (active_rule_snapshot(db_session) or {})["seat_shares"] == BASE_SHARES


def test_rule_version_switch_keeps_old_offer_on_old_version(db_session):
    """P0-8 判据：版本切换后，旧 offer 的 match_breakdown 仍指旧版权本。"""
    admin = _user("r2.offer.admin")
    candidate = _user("r2.offer.candidate", role="fde_engineer")
    template = _template(db_session)
    db_session.add_all([admin, candidate])
    project = _project(
        db_session, template, enterprise_code=f"r2 版本·{uuid4().hex[:6]}", leader=admin
    )
    package = _package(
        db_session, project, seat_delivery=candidate.id, sow_type="a", accepted=False
    )
    db_session.flush()
    now = datetime.now(timezone.utc)

    v1 = create_rule_version(
        db_session,
        actor=admin,
        version_no=1,
        rule_snapshot=default_rule_snapshot(),
        published_at=now - timedelta(days=40),
        effective_at=now - timedelta(days=10),
    )
    activate_due_versions(db_session, now=now)
    db_session.flush()

    # 模拟 P1-1 offer 服务落 offer：rule_version 记当时 active 版本
    offer = DispatchOffer(
        package_id=package.id,
        dispatch_round=1,
        candidate_user_id=candidate.id,
        match_breakdown={"rule_version": v1.id, "version_no": 1, "score": 90},
    )
    db_session.add(offer)
    db_session.flush()

    v2_snapshot = default_rule_snapshot()
    v2_snapshot["stage_b_weights"] = {
        "level": 50,
        "industry": 25,
        "sla": 15,
        "geo_remote": 10,
    }
    v2 = create_rule_version(
        db_session,
        actor=admin,
        version_no=2,
        rule_snapshot=v2_snapshot,
        published_at=now,
        effective_at=now + timedelta(days=31),
    )
    db_session.flush()
    # 未到生效日：v2 不生效
    assert activate_due_versions(db_session, now=now + timedelta(days=5)) == 0
    # 到生效日：v2 active，v1 retired
    assert activate_due_versions(db_session, now=now + timedelta(days=32)) == 1
    db_session.refresh(v1)
    db_session.refresh(v2)
    assert v1.status == "retired"
    assert v1.retired_at is not None
    assert v2.status == "active"
    assert (active_rule_snapshot(db_session) or {})["stage_b_weights"] == v2_snapshot[
        "stage_b_weights"
    ]

    # 旧 offer 不回写：match_breakdown 仍指 v1
    db_session.refresh(offer)
    assert offer.match_breakdown["rule_version"] == v1.id
    assert offer.match_breakdown["version_no"] == 1


# --- goal-d10 M10：评审会产出作为 Stage A/B 闸门证据引用（PartyMode §8 M10）---


def _sealed_minutes(db_session, project, host, *, sha: str) -> ReviewMeetingMinutes:
    meeting = ReviewMeeting(
        project_id=project.id, template_id="T2-lite", hosted_by_user_id=host.id,
    )
    db_session.add(meeting)
    db_session.flush()
    minutes = ReviewMeetingMinutes(
        meeting_id=meeting.id, consensus=[], disputes=[], todos=[], sealed_sha256=sha,
    )
    db_session.add(minutes)
    db_session.commit()
    return minutes


def test_m10_promotion_with_workbench_minutes_evidence(db_session):
    """等级证据链引用工作台封存纪要 → 落库 + 事件标注 evidence_form。"""
    admin, fde, _profile, project, _template = _l1_context(db_session)
    minutes = _sealed_minutes(db_session, project, admin, sha=SHA256)

    evidence = promote_user(
        db_session,
        actor=admin,
        user_id=fde.id,
        to_level="L1",
        source_uri=f"workbench-minutes:{minutes.meeting_id}",
        source_sha256=minutes.sealed_sha256,
    )
    db_session.flush()

    assert evidence.to_level == "L1"
    assert evidence.source_uri == f"workbench-minutes:{minutes.meeting_id}"
    assert evidence.source_sha256 == minutes.sealed_sha256
    event = db_session.scalar(
        select(OperationEvent).where(
            OperationEvent.event_type == "fde_level_promoted",
            OperationEvent.target_id == fde.id,
        )
    )
    assert event is not None
    assert event.changes["evidence_form"] == "workbench_minutes"
    assert event.changes["minutes_id"] == minutes.meeting_id


def test_m10_minutes_fingerprint_mismatch_rejected(db_session):
    """引用纪要必须携带真实封存指纹——伪造 sha256 422。"""
    admin, fde, _profile, project, _template = _l1_context(db_session)
    minutes = _sealed_minutes(db_session, project, admin, sha=SHA256)

    with pytest.raises(DispatchServiceError) as excinfo:
        promote_user(
            db_session,
            actor=admin,
            user_id=fde.id,
            to_level="L1",
            source_uri=f"workbench-minutes:{minutes.meeting_id}",
            source_sha256=hashlib.sha256(b"forged").hexdigest(),
        )
    assert excinfo.value.code == "minutes_fingerprint_mismatch"
    # check 异常属性存在（routes 转错误响应用）
    assert excinfo.value.status == 422


def test_m10_minutes_not_found_rejected(db_session):
    """引用不存在的纪要（或未封存会话）→ 422 minutes_not_found。"""
    admin, fde, _profile, _project, _template = _l1_context(db_session)

    with pytest.raises(DispatchServiceError) as excinfo:
        promote_user(
            db_session,
            actor=admin,
            user_id=fde.id,
            to_level="L1",
            source_uri=f"workbench-minutes:{uuid4()}",
            source_sha256=SHA256,
        )
    assert excinfo.value.code == "minutes_not_found"
