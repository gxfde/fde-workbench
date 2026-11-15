"""商业化 G3：收入科目层与订阅席位计费（T-10 / T-11 / T-13）。

任务书 §7 与 ADR-003 §2.1–§2.5 的验收钉（配 ADR-008）：

1. **科目层**：三类科目（席位费/培训费/项目分成）**分别记账可分别查、可对账**；
   六项名目**只定义归属**（归属矩阵拒绝错配），不定义计算方式。
2. **席位不重复收**（L2 实战营 / L3 陪跑营 / L0 首单三组合）：已购含席位套餐者
   **不再**被收 3980，科目行恒 1 行（反例用例）。
3. **首单扣费闸**：验收前**不触发**；**未书面选定扣费方式不得扣费**；未实现的
   方式 fail-closed；重复扣费拒绝。
4. **扣费方式＝当事人自证**（ADR-007 §2.4）：他人/admin 不得代选定；书面证据
   只存指针 + sha256 指纹。
5. **高风险写双闸**（admin + 密码确认）+ 事件留痕且**不含密码**（ADR-007 §2.1）。
6. **新增路由权限四态**：本人 / admin / 他人 403 / 未认证 401。
7. **认证挂模拟考核**：通过线未配置 ⇒ 停在 pending_threshold、**不判定通过**；
   配置且达标才置 certified。
8. **陪跑期限结构**：周期未配置 ⇒ 到期日留空（数值待定）；配置后按周期推导。
9. **分成比例结构**：本期零行、登记即 unset（不落数）；科目层**不按比例重算**
   ——项目分成金额恒等于既有分账的 delivery 席位金额，份额快照 ≡
   ``seat_shares_for`` 的结果（ADR-003 §2.2）。
10. **结构钉**（ADR-003 §2.1）：``delivery_settlements`` **零加列**；治理面不进
    api_catalog；迁移 additive 往返（downgrade 至**本迁移的父版本**显式
    revision——``-1`` 会被后续叠在头上的迁移顶掉）。
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from sqlalchemy import delete, inspect as sql_inspect, select, text

from fde_api.commercial.models import (
    CHARGEABLE_FEE_KEYS,
    FEE_CONFIG_KEYS,
    FIRST_ORDER_SEAT_FEE,
    LINE_ITEM_SUBJECTS,
    REVENUE_LINE_ITEMS,
    REVENUE_PACKAGES,
    REVENUE_SUBJECT_TYPES,
    CommercialCertificationRecord,
    CommercialRevenueLedger,
)
from fde_api.control.api_catalog import CATALOG

from conftest import INITIAL_PASSWORD
from test_research_subjects_api import (  # noqa: F401  (pytest fixture)
    admin_client,
    authorized_client_factory,
    leader_client,
)

SERVER_ROOT = Path(__file__).resolve().parent.parent
MIGRATION_FILE = (
    SERVER_ROOT / "migrations" / "versions" / "d5f9a3c7e1b4_commercial_g3_revenue_ledger.py"
)


def _pwd() -> str:
    return INITIAL_PASSWORD


def _sha(seed: str) -> str:
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()


def _ledger_url() -> str:
    return "/api/v1/commercial/revenue-ledger"


def _recon_url() -> str:
    return "/api/v1/commercial/revenue-ledger/reconciliation"


def _ledger_admin_url() -> str:
    return "/api/v1/admin/commercial/revenue-ledger"


def _first_order_url() -> str:
    return "/api/v1/admin/commercial/first-order-fee"


def _election_url() -> str:
    return "/api/v1/commercial/deduction-election"


def _packages_url() -> str:
    return "/api/v1/commercial/packages"


def _fee_configs_url() -> str:
    return "/api/v1/admin/commercial/fee-configs"


def _split_rules_url() -> str:
    return "/api/v1/admin/commercial/split-rules"


def _cert_records_url() -> str:
    return "/api/v1/admin/commercial/certification-records"


def _cert_records_read_url(user_id: str) -> str:
    return f"/api/v1/commercial/certification-records/{user_id}"


def _seat_url(user_id: str) -> str:
    return f"/api/v1/admin/commercial/users/{user_id}/seat-activation"


# ---------------------------------------------------------------------------
# 夹具：交付链（项目 + 交付包 + 收款 + 分账）
# ---------------------------------------------------------------------------


def _delivery_chain(
    db_session,
    deliverer,
    *,
    accepted: bool = True,
    received: bool = True,
    base: str = "10000.00",
    milestone_key: str = "G3",
):
    """一条交付链：已验收交付包 + 实收且验收通过的收款 + 分账行。

    企业代号只两段（**无城**）⇒ 冷启动判定不触发，席位份额恒取基线份额，
    科目层的份额快照可与 ``seat_shares_for`` 逐位对照。
    """
    from fde_api.dispatch.models import DeliveryPackage, DeliverySettlement
    from fde_api.solutions.models import ProjectSolution
    from fde_api.workbench.models import (
        IndustryTemplate,
        IndustryTemplateVersion,
        Payment,
        Project,
    )

    template = IndustryTemplate(
        template_key=f"g3-tpl-{uuid4().hex[:8]}", name="g3 模板", industry_name="制造业"
    )
    version = IndustryTemplateVersion(
        template=template,
        name="g3 模板 v1",
        industry_name="制造业",
        version_number=1,
        status="published",
    )
    project = Project(
        project_code=f"G3-{uuid4().hex[:6].upper()}",
        name="g3 交付项目",
        enterprise_code=f"g3 企业·制造",
        business_line="FDE_DISPATCH",
        planned_start_date=datetime(2026, 10, 31).date(),
        leader_user_id=deliverer.id,
        source_template_version=version,
        template_snapshot={"industry_name": "制造业", "modules": []},
    )
    db_session.add_all([template, version, project])
    db_session.flush()
    solution = ProjectSolution(
        project_id=project.id, name="g3 方案", schedule="", owner_user_id=deliverer.id
    )
    db_session.add(solution)
    db_session.flush()
    package = DeliveryPackage(
        id=uuid4().hex,
        solution_id=solution.id,
        project_id=project.id,
        package_code=f"PKG-G3-{uuid4().hex[:8].upper()}",
        dispatch_status="accepted" if accepted else "assigned",
        accepted_at=datetime.now(timezone.utc) if accepted else None,
        seat_delivery=deliverer.id,
    )
    db_session.add(package)
    db_session.flush()
    payment = Payment(
        project_id=project.id,
        milestone_key=milestone_key,
        sow_type="a",
        collects="g3 里程碑",
        timing="按合同",
        amount=Decimal(base),
        received_amount=Decimal(base) if received else None,
        received_at=datetime(2026, 10, 31).date() if received else None,
        acceptance_passed_at=datetime.now(timezone.utc) if accepted else None,
        source_uri=f"fdeops://g3/{package.package_code}/{milestone_key}",
        content_hash=_sha(f"g3-payment-{package.id}"),
    )
    db_session.add(payment)
    db_session.flush()
    settlement = DeliverySettlement(
        package_id=package.id,
        settlement_key=milestone_key,
        base_amount=Decimal(base),
        platform_amount=Decimal(base) * Decimal("0.35"),
        region_amount=Decimal(base) * Decimal("0.05"),
        city_amount=Decimal(base) * Decimal("0.20"),
        delivery_amount=Decimal(base) * Decimal("0.40"),
        status="accrued" if accepted else "draft",
        acceptance_passed_at=datetime.now(timezone.utc) if accepted else None,
    )
    db_session.add(settlement)
    db_session.commit()
    return project, package, payment, settlement


def _elect(client, method: str = "one_time") -> dict:
    response = client.post(
        _election_url(),
        json={
            "method": method,
            "source_uri": f"fdeops://g3/election/{uuid4().hex[:8]}.pdf",
            "content_hash": _sha(f"election-{uuid4().hex}"),
        },
    )
    assert response.status_code == 200, response.get_data(as_text=True)
    return response.json["data"]


@pytest.fixture
def simulation_evaluation(db_session):
    """一条模拟考核评估行（认证挂模拟考核的证据源）。

    模拟域无 ``project_id``、且仓内无全局清理登记——本夹具自带收尾：先删
    引用它的认证记录（FK RESTRICT），再删评估/运行/场景。
    """
    from fde_api.simulation.models import SimulationEvaluation, SimulationRun, SimulationScenario

    scenario = SimulationScenario(
        scenario_key=f"G3-CASE-{uuid4().hex[:8]}",
        name="g3 模拟案例",
        industry="制造业",
    )
    db_session.add(scenario)
    db_session.flush()
    run = SimulationRun(
        run_key=f"g3-run-{uuid4().hex[:12]}",
        scenario_id=scenario.id,
        scenario_version=1,
        status="completed",
        adapter_mode="mock",
        seed=1,
    )
    db_session.add(run)
    db_session.flush()
    evaluation = SimulationEvaluation(
        run_id=run.id,
        layer="human",
        evaluator_id="g3-judge",
        rubric_version="rubric-v1",
        verdict="pass",
        total_score=Decimal("0.9200"),
    )
    db_session.add(evaluation)
    db_session.commit()
    try:
        yield evaluation
    finally:
        db_session.execute(
            delete(CommercialCertificationRecord).where(
                CommercialCertificationRecord.simulation_evaluation_id == evaluation.id
            )
        )
        db_session.execute(
            delete(SimulationEvaluation).where(SimulationEvaluation.id == evaluation.id)
        )
        db_session.execute(delete(SimulationRun).where(SimulationRun.id == run.id))
        db_session.execute(delete(SimulationScenario).where(SimulationScenario.id == scenario.id))
        db_session.commit()


# ---------------------------------------------------------------------------
# 1. 科目层：三类科目分别可查、可对账
# ---------------------------------------------------------------------------


def test_three_subject_types_separately_queryable_and_reconcilable(
    admin_client, db_session, authorized_client_factory
) -> None:
    """三类科目各记一行 ⇒ 各自可查（按 subject_type 过滤）、汇总可对账。"""
    buyer = authorized_client_factory("fde_engineer").user
    trainer = authorized_client_factory("fde_engineer").user
    _project, package, payment, settlement = _delivery_chain(db_session, buyer)

    # 席位费：套餐购买（价格走收款台账实收额）
    seat = admin_client.post(
        _ledger_admin_url(),
        json={
            "subject_type": "seat_fee",
            "line_item": "software_subscription",
            "package_code": "bootcamp_practical",
            "subject_user_id": buyer.id,
            "payment_id": payment.id,
            "confirm_password": _pwd(),
        },
    )
    assert seat.status_code == 200, seat.get_data(as_text=True)
    assert seat.json["data"]["entry"]["amount"] == 10000.0

    # 培训费：挂培训权益 + 收款实收额
    training = admin_client.post(
        f"/api/v1/admin/commercial/users/{trainer.id}/training",
        json={"item_type": "training", "confirm_password": _pwd()},
    )
    assert training.status_code == 200, training.get_data(as_text=True)
    training_id = training.json["data"]["training"]["id"]
    train_fee = admin_client.post(
        _ledger_admin_url(),
        json={
            "subject_type": "training_fee",
            "line_item": "software_service_fee",
            "subject_user_id": trainer.id,
            "training_entitlement_id": training_id,
            "payment_id": payment.id,
            "confirm_password": _pwd(),
        },
    )
    assert train_fee.status_code == 200, train_fee.get_data(as_text=True)

    # 项目分成：引用既有分账结果（金额恒等于 delivery 席位金额）
    share = admin_client.post(
        _ledger_admin_url(),
        json={
            "subject_type": "project_share",
            "line_item": "platform_share",
            "subject_user_id": buyer.id,
            "payee_user_id": buyer.id,
            "delivery_settlement_id": settlement.id,
            "delivery_package_id": package.id,
            "role_code": "R3",
            "project_type": "delivery",
            "confirm_password": _pwd(),
        },
    )
    assert share.status_code == 200, share.get_data(as_text=True)
    assert share.json["data"]["entry"]["amount"] == 4000.0  # 10000 × 40%

    # 分别可查
    for subject in REVENUE_SUBJECT_TYPES:
        listed = admin_client.get(f"{_ledger_url()}?subject_type={subject}")
        assert listed.status_code == 200, listed.get_data(as_text=True)
        entries = listed.json["data"]["entries"]
        assert entries, subject
        assert {item["subject_type"] for item in entries} == {subject}, subject

    # 可对账：三类科目各自成桶，金额与行数对得上
    recon = admin_client.get(_recon_url())
    assert recon.status_code == 200, recon.get_data(as_text=True)
    subjects = recon.json["data"]["subjects"]
    assert set(subjects) == set(REVENUE_SUBJECT_TYPES)
    assert subjects["seat_fee"]["entry_count"] == 1
    assert subjects["training_fee"]["entry_count"] == 1
    assert subjects["project_share"]["entry_count"] == 1
    assert subjects["seat_fee"]["total_amount"] == 10000.0
    assert subjects["project_share"]["total_amount"] == 4000.0
    # 名目归属分桶（只定义归属）
    assert subjects["seat_fee"]["by_line_item"]["software_subscription"]["entry_count"] == 1
    assert subjects["project_share"]["by_line_item"]["platform_share"]["entry_count"] == 1


def test_line_item_attribution_matrix_rejects_mismatch(admin_client) -> None:
    """六名目**只定义归属**：名目↔科目错配一律 400（归属矩阵是代码层权威）。"""
    assert set(LINE_ITEM_SUBJECTS) == set(REVENUE_LINE_ITEMS)
    bad = admin_client.post(
        _ledger_admin_url(),
        json={
            "subject_type": "training_fee",
            "line_item": "platform_share",
            "amount": 1,
            "source_uri": "fdeops://g3/x.pdf",
            "content_hash": _sha("mismatch"),
            "confirm_password": _pwd(),
        },
    )
    assert bad.status_code == 400, bad.get_data(as_text=True)
    assert bad.json["error"]["code"] == "line_item_subject_mismatch"

    unknown = admin_client.post(
        _ledger_admin_url(),
        json={
            "subject_type": "seat_fee",
            "line_item": "not_a_line_item",
            "amount": 1,
            "source_uri": "fdeops://g3/x.pdf",
            "content_hash": _sha("unknown"),
            "confirm_password": _pwd(),
        },
    )
    assert unknown.status_code == 400
    assert unknown.json["error"]["code"] == "invalid_line_item"


def test_ledger_entry_requires_association(admin_client) -> None:
    """科目行不得悬空：必须关联订单/席位/分成事件/报价/收款/合同之一。"""
    response = admin_client.post(
        _ledger_admin_url(),
        json={
            "subject_type": "training_fee",
            "line_item": "software_service_fee",
            "amount": 100,
            "source_uri": "fdeops://g3/x.pdf",
            "content_hash": _sha("orphan"),
            "confirm_password": _pwd(),
        },
    )
    assert response.status_code == 400, response.get_data(as_text=True)
    assert response.json["error"]["code"] == "missing_association"


# ---------------------------------------------------------------------------
# 2. 席位不重复收（L2 实战营 / L3 陪跑营 / L0 首单三组合）
# ---------------------------------------------------------------------------


def _package_seat_purchase(admin_client, db_session, buyer, package_code: str) -> dict:
    """登记一笔含席位套餐购买（席位费科目 + 席位激活）。"""
    _project, _package, payment, _settlement = _delivery_chain(db_session, buyer)
    seat_fee = admin_client.post(
        _ledger_admin_url(),
        json={
            "subject_type": "seat_fee",
            "line_item": "software_subscription",
            "package_code": package_code,
            "subject_user_id": buyer.id,
            "payment_id": payment.id,
            "confirm_password": _pwd(),
        },
    )
    assert seat_fee.status_code == 200, seat_fee.get_data(as_text=True)
    activated = admin_client.post(
        _seat_url(buyer.id),
        json={
            "seat_source": REVENUE_PACKAGES[package_code]["seat_source"],
            "expires_at": "2027-12-31T00:00:00Z",
            "confirm_password": _pwd(),
        },
    )
    assert activated.status_code == 200, activated.get_data(as_text=True)
    return seat_fee.json["data"]["entry"]


@pytest.mark.parametrize(
    "package_code,seat_source",
    [("bootcamp_practical", "bootcamp_practical"), ("bootcamp_mentorship", "bootcamp_mentorship")],
)
def test_package_included_seat_is_not_charged_again(
    admin_client, db_session, authorized_client_factory, package_code: str, seat_source: str
) -> None:
    """**反例用例**：L2 实战营 / L3 陪跑营均含首年席位费 ⇒ 不再收 3980。

    断言两件事：① 首单扣费被拒（409 ``seat_fee_already_included``）；
    ② 该交付者的席位费科目行**恒 1 行**（套餐那一行），没有被记第二笔。
    """
    buyer_client = authorized_client_factory("fde_engineer")
    buyer = buyer_client.user
    _package_seat_purchase(admin_client, db_session, buyer, package_code)
    _elect(buyer_client)  # 扣费方式已书面选定（闸门本身应当放行）

    _project, package, _payment, _settlement = _delivery_chain(db_session, buyer)
    denied = admin_client.post(
        _first_order_url(),
        json={
            "user_id": buyer.id,
            "package_id": package.id,
            "confirm_password": _pwd(),
        },
    )
    assert denied.status_code == 409, denied.get_data(as_text=True)
    assert denied.json["error"]["code"] == "seat_fee_already_included"

    rows = db_session.scalars(
        select(CommercialRevenueLedger).where(
            CommercialRevenueLedger.subject_type == "seat_fee",
            CommercialRevenueLedger.subject_user_id == buyer.id,
        )
    ).all()
    assert len(rows) == 1, "含席位套餐者被重复收了席位费"
    assert rows[0].package_code == package_code
    assert float(rows[0].amount) != float(FIRST_ORDER_SEAT_FEE)


def test_first_order_fee_applies_for_candidate_without_package(
    admin_client, db_session, authorized_client_factory
) -> None:
    """L0 组合：未购含席位套餐的候选交付者 ⇒ 首单扣费成立（3980）＋席位激活。"""
    deliverer_client = authorized_client_factory("fde_engineer")
    deliverer = deliverer_client.user
    _project, package, _payment, _settlement = _delivery_chain(db_session, deliverer)
    _elect(deliverer_client)

    charged = admin_client.post(
        _first_order_url(),
        json={
            "user_id": deliverer.id,
            "package_id": package.id,
            "confirm_password": _pwd(),
        },
    )
    assert charged.status_code == 200, charged.get_data(as_text=True)
    assert charged.json["data"]["amount"] == float(FIRST_ORDER_SEAT_FEE)

    rows = db_session.scalars(
        select(CommercialRevenueLedger).where(
            CommercialRevenueLedger.subject_type == "seat_fee",
            CommercialRevenueLedger.subject_user_id == deliverer.id,
        )
    ).all()
    assert len(rows) == 1
    assert rows[0].package_code == "first_delivery"
    assert float(rows[0].amount) == float(FIRST_ORDER_SEAT_FEE)

    # 席位随首单激活（来源 first_delivery，年度到期）
    from fde_api.commercial.models import CommercialEntitlement

    entitlement = db_session.get(CommercialEntitlement, deliverer.id)
    assert entitlement is not None
    assert entitlement.seat_status == "active"
    assert entitlement.seat_source == "first_delivery"
    assert entitlement.seat_expires_at is not None


def test_first_order_fee_is_not_charged_twice(
    admin_client, db_session, authorized_client_factory
) -> None:
    """重复扣费拒绝（第二个交付包也不许再扣一次）。"""
    deliverer_client = authorized_client_factory("fde_engineer")
    deliverer = deliverer_client.user
    _elect(deliverer_client)
    _project, package, _payment, _settlement = _delivery_chain(db_session, deliverer)
    first = admin_client.post(
        _first_order_url(),
        json={"user_id": deliverer.id, "package_id": package.id, "confirm_password": _pwd()},
    )
    assert first.status_code == 200, first.get_data(as_text=True)

    _project2, package2, _payment2, _settlement2 = _delivery_chain(db_session, deliverer)
    second = admin_client.post(
        _first_order_url(),
        json={"user_id": deliverer.id, "package_id": package2.id, "confirm_password": _pwd()},
    )
    assert second.status_code == 409, second.get_data(as_text=True)
    assert second.json["error"]["code"] in ("seat_already_active", "seat_fee_already_charged")

    rows = db_session.scalars(
        select(CommercialRevenueLedger).where(
            CommercialRevenueLedger.subject_type == "seat_fee",
            CommercialRevenueLedger.subject_user_id == deliverer.id,
        )
    ).all()
    assert len(rows) == 1


# ---------------------------------------------------------------------------
# 3. 首单扣费闸：验收前不触发 / 未选定方案不得扣费
# ---------------------------------------------------------------------------


def test_first_order_fee_blocked_before_acceptance(
    admin_client, db_session, authorized_client_factory
) -> None:
    """交付未完成并验收 ⇒ **不触发**首单扣费（零行零席位）。"""
    deliverer_client = authorized_client_factory("fde_engineer")
    deliverer = deliverer_client.user
    _elect(deliverer_client)
    _project, package, _payment, _settlement = _delivery_chain(
        db_session, deliverer, accepted=False, received=False
    )
    blocked = admin_client.post(
        _first_order_url(),
        json={
            "user_id": deliverer.id,
            "package_id": package.id,
            "confirm_password": _pwd(),
        },
    )
    assert blocked.status_code == 409, blocked.get_data(as_text=True)
    assert blocked.json["error"]["code"] == "acceptance_not_passed"

    rows = db_session.scalars(
        select(CommercialRevenueLedger).where(
            CommercialRevenueLedger.subject_type == "seat_fee"
        )
    ).all()
    assert rows == []


def test_first_order_fee_blocked_without_election(
    admin_client, db_session, authorized_client_factory
) -> None:
    """**未书面选定扣费方式不得扣费**（任务书 §7 验收）。"""
    deliverer = authorized_client_factory("fde_engineer").user
    _project, package, _payment, _settlement = _delivery_chain(db_session, deliverer)
    blocked = admin_client.post(
        _first_order_url(),
        json={
            "user_id": deliverer.id,
            "package_id": package.id,
            "confirm_password": _pwd(),
        },
    )
    assert blocked.status_code == 409, blocked.get_data(as_text=True)
    assert blocked.json["error"]["code"] == "deduction_method_not_selected"

    rows = db_session.scalars(
        select(CommercialRevenueLedger).where(
            CommercialRevenueLedger.subject_type == "seat_fee"
        )
    ).all()
    assert rows == []


def test_first_order_fee_blocked_for_unimplemented_method(
    admin_client, db_session, authorized_client_factory
) -> None:
    """方案 B（年度分期）本期未实现 ⇒ fail-closed 拒绝（不误按方案 A 扣费）。"""
    deliverer_client = authorized_client_factory("fde_engineer")
    deliverer = deliverer_client.user
    elected = _elect(deliverer_client, method="annual_installment")
    assert elected["implemented"] is False

    _project, package, _payment, _settlement = _delivery_chain(db_session, deliverer)
    blocked = admin_client.post(
        _first_order_url(),
        json={
            "user_id": deliverer.id,
            "package_id": package.id,
            "confirm_password": _pwd(),
        },
    )
    assert blocked.status_code == 409, blocked.get_data(as_text=True)
    assert blocked.json["error"]["code"] == "deduction_method_not_implemented"


# ---------------------------------------------------------------------------
# 4. 扣费方式＝当事人自证动作（ADR-007 §2.4）
# ---------------------------------------------------------------------------


def test_election_is_self_action_only(
    admin_client, leader_client, db_session, authorized_client_factory
) -> None:
    """本人选定自己的扣费方式；payload 里的 user_id **不被接受**（杜绝代选定）。"""
    other = authorized_client_factory("fde_engineer").user
    response = leader_client.post(
        _election_url(),
        json={
            "method": "one_time",
            "user_id": other.id,  # 代选定尝试——必须无效
            "source_uri": "fdeops://g3/election/self.pdf",
            "content_hash": _sha("self-action"),
        },
    )
    assert response.status_code == 200, response.get_data(as_text=True)
    assert response.json["data"]["election"]["user_id"] == leader_client.user.id

    from fde_api.commercial.models import CommercialDeductionElection

    rows = db_session.scalars(select(CommercialDeductionElection)).all()
    assert len(rows) == 1
    assert rows[0].user_id == leader_client.user.id


def test_election_requires_written_evidence(leader_client) -> None:
    """书面选定必须附指针 + sha256 指纹（证据红线：原件不入库不入仓）。"""
    missing_hash = leader_client.post(
        _election_url(),
        json={"method": "one_time", "source_uri": "fdeops://g3/election/x.pdf"},
    )
    assert missing_hash.status_code == 400
    assert missing_hash.json["error"]["code"] == "invalid_request"

    bad_hash = leader_client.post(
        _election_url(),
        json={
            "method": "one_time",
            "source_uri": "fdeops://g3/election/x.pdf",
            "content_hash": "not-a-sha256",
        },
    )
    assert bad_hash.status_code == 400

    bad_method = leader_client.post(
        _election_url(),
        json={
            "method": "monthly",
            "source_uri": "fdeops://g3/election/x.pdf",
            "content_hash": _sha("method"),
        },
    )
    assert bad_method.status_code == 400
    assert bad_method.json["error"]["code"] == "invalid_deduction_method"


# ---------------------------------------------------------------------------
# 5. 高风险写双闸 + 事件留痕（ADR-007 §2.1）
# ---------------------------------------------------------------------------


def test_governance_writes_require_admin_and_password(
    leader_client, admin_client, db_session, authorized_client_factory
) -> None:
    """记账/首单扣费/配置位写面：非 admin 403、缺密码 400、错密码 403。"""
    deliverer = authorized_client_factory("fde_engineer").user
    payload = {
        "subject_type": "seat_fee",
        "line_item": "software_subscription",
        "package_code": "bootcamp_practical",
        "subject_user_id": deliverer.id,
        "amount": 9800,
        "source_uri": "fdeops://g3/x.pdf",
        "content_hash": _sha("gate"),
    }
    denied = leader_client.post(_ledger_admin_url(), json={**payload, "confirm_password": _pwd()})
    assert denied.status_code == 403, denied.get_data(as_text=True)
    assert denied.json["error"]["code"] == "commercial_admin_required"

    no_password = admin_client.post(_ledger_admin_url(), json=payload)
    assert no_password.status_code == 400
    assert no_password.json["error"]["code"] == "invalid_request"

    wrong_password = admin_client.post(
        _ledger_admin_url(), json={**payload, "confirm_password": "wrong-password"}
    )
    assert wrong_password.status_code == 403
    assert wrong_password.json["error"]["code"] == "invalid_password"

    fee_denied = leader_client.post(
        _first_order_url(),
        json={"user_id": deliverer.id, "package_id": "x", "confirm_password": _pwd()},
    )
    assert fee_denied.status_code == 403

    cfg_denied = leader_client.post(
        f"{_fee_configs_url()}/certification_fee",
        json={
            "value": 100,
            "source_uri": "fdeops://g3/x.pdf",
            "content_hash": _sha("cfg"),
            "confirm_password": _pwd(),
        },
    )
    assert cfg_denied.status_code == 403


def test_revenue_event_recorded_without_password(
    db_session, admin_client, authorized_client_factory
) -> None:
    """记账事件落 ``operation_events``：带 request_id、**不含密码**。"""
    from fde_api.workbench.models import OperationEvent

    buyer = authorized_client_factory("fde_engineer").user
    _project, _package, payment, _settlement = _delivery_chain(db_session, buyer)
    response = admin_client.post(
        _ledger_admin_url(),
        json={
            "subject_type": "seat_fee",
            "line_item": "software_subscription",
            "package_code": "bootcamp_practical",
            "subject_user_id": buyer.id,
            "payment_id": payment.id,
            "confirm_password": _pwd(),
        },
    )
    assert response.status_code == 200, response.get_data(as_text=True)
    db_session.commit()

    events = db_session.scalars(
        select(OperationEvent).where(
            OperationEvent.event_type == "commercial_revenue_recorded"
        )
    ).all()
    assert events, "记账事件未留痕"
    changes = events[-1].changes
    assert "request_id" in changes
    assert _pwd() not in str(changes)


# ---------------------------------------------------------------------------
# 6. 新增路由权限四态
# ---------------------------------------------------------------------------


def test_ledger_read_scope_and_permissions(
    admin_client, leader_client, db_session, authorized_client_factory, client
) -> None:
    """本人只见自己的科目；他人 403；未认证 401；admin 见全量。"""
    owner = authorized_client_factory("fde_engineer").user
    stranger = authorized_client_factory("fde_engineer").user
    _project, _package, payment, _settlement = _delivery_chain(db_session, owner)
    created = admin_client.post(
        _ledger_admin_url(),
        json={
            "subject_type": "seat_fee",
            "line_item": "software_subscription",
            "package_code": "bootcamp_practical",
            "subject_user_id": owner.id,
            "payment_id": payment.id,
            "confirm_password": _pwd(),
        },
    )
    assert created.status_code == 200, created.get_data(as_text=True)
    entry_id = created.json["data"]["entry"]["id"]

    # 本人可见
    mine = leader_client.get(_ledger_url())
    assert mine.status_code == 200

    # admin 可见全量
    all_rows = admin_client.get(_ledger_url())
    assert all_rows.status_code == 200
    assert all_rows.json["data"]["scope"] == "platform"

    # 他人条目 403
    other_read = leader_client.get(f"{_ledger_url()}/{entry_id}")
    assert other_read.status_code == 403, other_read.get_data(as_text=True)
    assert other_read.json["error"]["code"] == "commercial_ledger_forbidden"

    # 他人筛选 403
    other_filter = leader_client.get(f"{_ledger_url()}?subject_user_id={owner.id}")
    assert other_filter.status_code == 403

    # 未认证 401
    anon = client.get(_ledger_url())
    assert anon.status_code == 401
    anon_post = client.post(_ledger_admin_url(), json={})
    assert anon_post.status_code == 401
    assert stranger.id != owner.id


# ---------------------------------------------------------------------------
# 7. 认证挂模拟考核（通过线本期不设 ⇒ 缺省不判定通过）
# ---------------------------------------------------------------------------


def test_certification_without_threshold_stays_pending(
    admin_client, db_session, authorized_client_factory, simulation_evaluation
) -> None:
    """通过线未配置 ⇒ 记录停在 pending_threshold，**认证状态不变**。"""
    candidate = authorized_client_factory("fde_engineer").user
    response = admin_client.post(
        _cert_records_url(),
        json={
            "user_id": candidate.id,
            "simulation_evaluation_id": simulation_evaluation.id,
            "confirm_password": _pwd(),
        },
    )
    assert response.status_code == 200, response.get_data(as_text=True)
    assert response.json["data"]["certified"] is False
    assert response.json["data"]["record"]["status"] == "pending_threshold"
    assert response.json["data"]["record"]["threshold"] is None

    from fde_api.commercial.models import CommercialEntitlement

    entitlement = db_session.get(CommercialEntitlement, candidate.id)
    assert entitlement is None or entitlement.certification_status == "uncertified"


def test_certification_after_threshold_configured(
    admin_client, db_session, authorized_client_factory, simulation_evaluation
) -> None:
    """通过线配置且考核达标 ⇒ 置 certified 并把认证来源指向考核行。"""
    candidate = authorized_client_factory("fde_engineer").user
    configured = admin_client.post(
        f"{_fee_configs_url()}/certification_pass_threshold",
        json={
            "value": 0.8,
            "source_uri": "fdeops://g3/certification/threshold.pdf",
            "content_hash": _sha("threshold"),
            "confirm_password": _pwd(),
        },
    )
    assert configured.status_code == 200, configured.get_data(as_text=True)

    response = admin_client.post(
        _cert_records_url(),
        json={
            "user_id": candidate.id,
            "simulation_evaluation_id": simulation_evaluation.id,
            "confirm_password": _pwd(),
        },
    )
    assert response.status_code == 200, response.get_data(as_text=True)
    assert response.json["data"]["certified"] is True
    assert response.json["data"]["record"]["status"] == "certified"

    from fde_api.commercial.models import CommercialEntitlement

    entitlement = db_session.get(CommercialEntitlement, candidate.id)
    assert entitlement is not None
    assert entitlement.certification_status == "certified"
    assert entitlement.certification_source == f"simulation_evaluation:{simulation_evaluation.id}"

    # 读面（本人）
    read = admin_client.get(_cert_records_read_url(candidate.id))
    assert read.status_code == 200
    assert read.json["data"]["count"] == 1


def test_certification_fee_cannot_be_charged_before_configured(
    admin_client, db_session, authorized_client_factory
) -> None:
    """认证费金额本期不设 ⇒ **缺省不可收款**（409 fee_not_configured）。"""
    candidate = authorized_client_factory("fde_engineer").user
    training = admin_client.post(
        f"/api/v1/admin/commercial/users/{candidate.id}/training",
        json={"item_type": "certification", "confirm_password": _pwd()},
    )
    assert training.status_code == 200, training.get_data(as_text=True)
    training_id = training.json["data"]["training"]["id"]

    blocked = admin_client.post(
        _ledger_admin_url(),
        json={
            "subject_type": "training_fee",
            "line_item": "software_service_fee",
            "subject_user_id": candidate.id,
            "training_entitlement_id": training_id,
            "fee_key": "certification_fee",
            "confirm_password": _pwd(),
        },
    )
    assert blocked.status_code == 409, blocked.get_data(as_text=True)
    assert blocked.json["error"]["code"] == "fee_not_configured"
    assert "certification_fee" in CHARGEABLE_FEE_KEYS


# ---------------------------------------------------------------------------
# 8. 陪跑期限结构（数值待定）
# ---------------------------------------------------------------------------


def test_mentoring_period_structure_is_pending_by_default(
    admin_client, db_session, authorized_client_factory
) -> None:
    """陪跑期限与培训周期挂钩：周期未配置 ⇒ 到期日留空（数值待定）。"""
    trainee = authorized_client_factory("fde_engineer").user
    created = admin_client.post(
        f"/api/v1/admin/commercial/users/{trainee.id}/training",
        json={"item_type": "mentoring", "confirm_password": _pwd()},
    )
    assert created.status_code == 200, created.get_data(as_text=True)
    assert created.json["data"]["training"]["valid_until"] is None

    # 配置周期后 ⇒ 按周期推导（结构生效）
    configured = admin_client.post(
        f"{_fee_configs_url()}/mentoring_period_days",
        json={
            "value": 90,
            "source_uri": "fdeops://g3/mentoring/period.pdf",
            "content_hash": _sha("mentoring"),
            "confirm_password": _pwd(),
        },
    )
    assert configured.status_code == 200, configured.get_data(as_text=True)

    again = admin_client.post(
        f"/api/v1/admin/commercial/users/{trainee.id}/training",
        json={"item_type": "mentoring", "confirm_password": _pwd()},
    )
    assert again.status_code == 200, again.get_data(as_text=True)
    assert again.json["data"]["training"]["valid_until"] is not None


# ---------------------------------------------------------------------------
# 9. 分成比例结构（本期不落数）+ 科目层不重算
# ---------------------------------------------------------------------------


def test_split_rule_structure_starts_empty_and_unset(
    admin_client, db_session
) -> None:
    """本期分成比例**不落数**：结构表零行；登记维度即 unset（ratio 恒 NULL）。"""
    listed = admin_client.get(_split_rules_url())
    assert listed.status_code == 200
    assert listed.json["data"]["split_rules"] == []

    registered = admin_client.post(
        _split_rules_url(),
        json={
            "role_code": "R3",
            "project_type": "delivery",
            "source_uri": "fdeops://g3/split/rule.pdf",
            "content_hash": _sha("split"),
            "confirm_password": _pwd(),
        },
    )
    assert registered.status_code == 200, registered.get_data(as_text=True)
    rule = registered.json["data"]["split_rule"]
    assert rule["status"] == "unset"
    assert rule["ratio_bp"] is None
    assert rule["configured"] is False


def test_project_share_references_settlement_without_recompute(
    admin_client, db_session, authorized_client_factory
) -> None:
    """项目分成**引用**既有分账结果：金额 ≡ delivery 席位金额；份额快照 ≡
    ``seat_shares_for``；传入不一致金额一律 409（科目层不重算）。"""
    from fde_api.dispatch.settlements import seat_shares_for

    deliverer = authorized_client_factory("fde_engineer").user
    _project, package, _payment, settlement = _delivery_chain(db_session, deliverer)

    mismatch = admin_client.post(
        _ledger_admin_url(),
        json={
            "subject_type": "project_share",
            "line_item": "platform_share",
            "subject_user_id": deliverer.id,
            "delivery_settlement_id": settlement.id,
            "amount": 1234,
            "confirm_password": _pwd(),
        },
    )
    assert mismatch.status_code == 409, mismatch.get_data(as_text=True)
    assert mismatch.json["error"]["code"] == "amount_mismatch_settlement"

    ok = admin_client.post(
        _ledger_admin_url(),
        json={
            "subject_type": "project_share",
            "line_item": "platform_share",
            "subject_user_id": deliverer.id,
            "payee_user_id": deliverer.id,
            "delivery_settlement_id": settlement.id,
            "delivery_package_id": package.id,
            "role_code": "R3",
            "project_type": "delivery",
            "confirm_password": _pwd(),
        },
    )
    assert ok.status_code == 200, ok.get_data(as_text=True)
    entry = ok.json["data"]["entry"]
    assert entry["amount"] == float(settlement.delivery_amount)
    assert entry["seat_shares"] == seat_shares_for(db_session, package)
    assert entry["basis"]["seat_shares_source"] == "dispatch/settlements.py::seat_shares_for"


# ---------------------------------------------------------------------------
# 10. 结构钉：零加列 / 不进 api_catalog / 迁移往返
# ---------------------------------------------------------------------------


def test_delivery_settlements_keeps_its_original_columns(db_session) -> None:
    """ADR-003 §2.1：**禁止**在 ``delivery_settlements`` 上加列硬塞科目。"""
    inspector = sql_inspect(db_session.get_bind())
    columns = {column["name"] for column in inspector.get_columns("delivery_settlements")}
    assert columns == {
        "id",
        "package_id",
        "snapshot_hash",
        "settlement_key",
        "base_amount",
        "seat_platform_user_id",
        "seat_region_agent_user_id",
        "seat_city_partner_user_id",
        "seat_delivery_user_id",
        "platform_amount",
        "region_amount",
        "city_amount",
        "delivery_amount",
        "withholding_tax",
        "status",
        "acceptance_passed_at",
        "paid_proof_source_uri",
        "paid_at",
        "created_at",
        "updated_at",
    }, "delivery_settlements 的列集合被改动——科目层必须独立新建"


def test_governance_face_not_in_api_catalog() -> None:
    """治理面不进 api_catalog（AI 不可调用；G1/G2 同款边界）。"""
    catalog_names = {row[0] for row in CATALOG}
    for path in (
        "commercial.revenue-ledger.record",
        "commercial.first-order-fee.charge",
        "commercial.deduction-election.elect",
        "commercial.fee-configs.configure",
        "commercial.split-rules.register",
        "commercial.certification-records.record",
    ):
        assert path not in catalog_names


def test_fee_config_slots_are_unset_by_default(admin_client) -> None:
    """本期三个配置位**全部 unset**（认证费金额/陪跑期限/通过线都不落数）。"""
    response = admin_client.get(_fee_configs_url())
    assert response.status_code == 200, response.get_data(as_text=True)
    configs = {row["key"]: row for row in response.json["data"]["fee_configs"]}
    assert set(configs) == set(FEE_CONFIG_KEYS)
    for key, row in configs.items():
        assert row["status"] == "unset", key
        assert row["configured"] is False, key
        assert row["amount"] is None, key
        assert row["days"] is None, key
        assert row["threshold"] is None, key


def test_packages_catalog_exposes_no_price(admin_client) -> None:
    """套餐目录只暴露**含席位标记**，不落价目（价格走收款台账）。"""
    response = admin_client.get(_packages_url())
    assert response.status_code == 200, response.get_data(as_text=True)
    packages = response.json["data"]["packages"]
    codes = {row["code"] for row in packages}
    assert codes == set(REVENUE_PACKAGES)
    for row in packages:
        assert "price" not in row
        assert "amount" not in row
        assert row["covers_first_year_fee"] is (
            REVENUE_PACKAGES[row["code"]]["covers_first_year_fee"]
        )
    assert REVENUE_PACKAGES["bootcamp_practical"]["covers_first_year_fee"] is True
    assert REVENUE_PACKAGES["bootcamp_mentorship"]["covers_first_year_fee"] is True


def test_migration_roundtrip_and_head_shape(engine, alembic_config) -> None:
    """迁移 additive 往返：head 上五表与 CHECK 齐备；downgrade 至**本迁移的父
    版本**后五表消失；回 head 恢复（``-1`` 会被后续迁移顶掉）。"""
    inspector = sql_inspect(engine)
    tables = set(inspector.get_table_names())
    for name in (
        "commercial_split_rules",
        "commercial_fee_configs",
        "commercial_deduction_elections",
        "commercial_certification_records",
        "commercial_revenue_ledger",
    ):
        assert name in tables, name

    ledger_columns = {c["name"] for c in inspector.get_columns("commercial_revenue_ledger")}
    assert {
        "subject_type",
        "line_item",
        "amount",
        "payment_id",
        "delivery_settlement_id",
        "package_code",
    } <= ledger_columns

    ledger_checks = {
        c["name"] for c in inspector.get_check_constraints("commercial_revenue_ledger")
    }
    assert {
        "ck_commercial_revenue_ledger_subject_type",
        "ck_commercial_revenue_ledger_line_item",
        "ck_commercial_revenue_ledger_status",
        "ck_commercial_revenue_ledger_amount",
        "ck_commercial_revenue_ledger_association",
        "ck_commercial_revenue_ledger_package_code",
        "ck_commercial_revenue_ledger_seat_source",
        "ck_commercial_revenue_ledger_role_code",
        "ck_commercial_revenue_ledger_fee_key",
    } <= ledger_checks

    election_checks = {
        c["name"] for c in inspector.get_check_constraints("commercial_deduction_elections")
    }
    assert {
        "ck_commercial_deduction_elections_method",
        "ck_commercial_deduction_elections_status",
    } <= election_checks

    command.downgrade(alembic_config, "b3e7c9d1a5f2")
    inspector = sql_inspect(engine)
    gone = set(inspector.get_table_names())
    for name in (
        "commercial_split_rules",
        "commercial_fee_configs",
        "commercial_deduction_elections",
        "commercial_certification_records",
        "commercial_revenue_ledger",
    ):
        assert name not in gone, name
    command.upgrade(alembic_config, "head")
    inspector = sql_inspect(engine)
    back = set(inspector.get_table_names())
    assert "commercial_revenue_ledger" in back
