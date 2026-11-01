"""goal-r8 收口轮回归（C10 新人保护 / B1 防骚扰不重复推送 / §4.7 扩圈半径
自动推进 + 闸④覆盖率口径产出）。

- C10（§6.5）：前 5 单新人只推同城——非同城候选对新人轮出局（推送范围
  收紧，非资格淘汰；超时不写档案不惩罚）。
- B1（规则表 B1）：同一拒单者跨轮不重复主动推送；与负面清单 #6 正交
  （本人仍可经 claim 主动抢）。
- §4.7：重派轮次推进时 redispatch_radius_km 按 25→50→100→0 自动降档。
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import select

from fde_api.dispatch.models import DeliveryPackage, DispatchOffer, FdeProfile
from fde_api.dispatch.packages import create_package, publish_package
from fde_api.solutions.models import ProjectSolution

from test_dispatch_p1_r5 import _active_rule, _onsite_package, _profile, _user


def test_newcomer_protection_city_only(db_session):
    """C10：新人（完成单 < 5）只推同城——深圳老手可入，深圳新人出局；
    完成单 ≥5 后同一非同城候选恢复入围。"""
    admin, package = _onsite_package(db_session)
    _active_rule(db_session)
    publish_package(db_session, actor=admin, package_id=package.id)
    city_newcomer = _user("r8.np.city", role="fde_engineer")
    _profile(db_session, city_newcomer, level="L2", module_tags=["pre_diagnosis"],
             industry_tags=["制造业"], home_city="广州")
    far_newcomer = _user("r8.np.far", role="fde_engineer")
    _profile(db_session, far_newcomer, level="L4", module_tags=["pre_diagnosis"],
             industry_tags=["制造业"], home_city="深圳")
    db_session.flush()

    result = match_package_helper(db_session, admin, package)
    assert city_newcomer.id in [o["candidate_user_id"] for o in result["offers"]]
    assert far_newcomer.id not in [o["candidate_user_id"] for o in result["offers"]]
    # A5 明细带 newcomer 标记（释明义务）；部分淘汰明细随返回值可诊断
    offer = db_session.scalar(
        select(DispatchOffer).where(DispatchOffer.candidate_user_id == city_newcomer.id)
    )
    assert offer.match_breakdown["stage_a"]["A5"]["newcomer_city_only"] is True
    assert far_newcomer.id in result["rejected"]  # 淘汰名单含新人异城者

    # 老手（完成单 = 5）：非同城恢复入围
    senior = _user("r8.np.senior", role="fde_engineer")
    _profile(db_session, senior, level="L4", module_tags=["pre_diagnosis"],
             industry_tags=["制造业"], home_city="深圳")
    db_session.flush()
    for round_no in (91, 92, 93, 94, 95):  # 远端轮次（唯一约束=project+round，避开主包 round 1）
        db_session.add(
            DeliveryPackage(
                id=uuid4().hex,
                solution_id=package.solution_id,  # 复用真实方案行（FK RESTRICT）
                project_id=package.project_id,
                package_code=f"PKG-OLD-{uuid4().hex[:8].upper()}",
                dispatch_round=round_no,
                dispatch_status="accepted",
                seat_delivery=senior.id,
                accepted_at=datetime.now(timezone.utc),
            )
        )
    db_session.flush()
    # 老手对照用远程包（到场包 round 1 围栏本就限同城，与新人保护无关）
    _admin2, package2 = _onsite_package(db_session)
    package2.onsite_required = False
    db_session.get(ProjectSolution, package2.solution_id).schedule = ""
    publish_package(db_session, actor=_admin2, package_id=package2.id)
    result2 = match_package_helper(db_session, _admin2, package2)
    assert senior.id in [o["candidate_user_id"] for o in result2["offers"]]


def match_package_helper(db_session, admin, package):
    from fde_api.dispatch.matching import match_package

    return match_package(db_session, actor=admin, package_id=package.id)


def _rejected_gate(db_session, package_id: str, user_id: str, gate_key: str):
    """从场景 C/淘汰留痕读某候选的某门明细（事件 changes.rejected 列表）。"""
    from fde_api.workbench.models import OperationEvent

    event = db_session.scalar(
        select(OperationEvent).where(
            OperationEvent.target_id == package_id,
            OperationEvent.event_type == "dispatch_matching_scenario_c",
        )
    )
    assert event is not None, "候选全灭应落场景 C 事件"
    for item in event.changes["rejected"]:
        if item["user_id"] == user_id:
            return item["gates"][gate_key]
    raise AssertionError(f"{user_id} 不在淘汰明细中")


def test_b1_no_repush_to_earlier_decliners(db_session):
    """B1：更早轮拒过的候选，本轮撮合不推（事件明细 B1 行可释明）。"""
    admin, package = _onsite_package(db_session)
    _active_rule(db_session)
    publish_package(db_session, actor=admin, package_id=package.id)
    decliner = _user("r8.b1.decliner", role="fde_engineer")
    _profile(db_session, decliner, level="L2", module_tags=["pre_diagnosis"],
             industry_tags=["制造业"], home_city="广州")
    # declined 落在「更早轮」：包置于 round 2、拒单在 round 1
    package.dispatch_round = 2
    db_session.add(
        DispatchOffer(
            package_id=package.id,
            dispatch_round=1,
            candidate_user_id=decliner.id,
            status="declined",
            offered_at=datetime.now(timezone.utc) - timedelta(days=1),
        )
    )
    db_session.flush()
    # B1：更早轮拒过 → 本轮不推（唯一候选被 B1 拦 → 全灭走场景 C，事件可释明）
    result = match_package_helper(db_session, admin, package)
    assert result["scenario"] == "C"
    gate = _rejected_gate(db_session, package.id, decliner.id, "B1")
    assert gate["declined_earlier"] is True and gate["ok"] is False

    # 同轮语义对照：declined 在本轮（round 2）→ 先撞「本轮已有 offer」守卫 409
    package.dispatch_round = 3
    db_session.add(
        DispatchOffer(
            package_id=package.id,
            dispatch_round=package.dispatch_round,
            candidate_user_id=decliner.id,
            status="declined",
            offered_at=datetime.now(timezone.utc) - timedelta(days=1),
        )
    )
    db_session.flush()
    from fde_api.dispatch.errors import DispatchServiceError

    import pytest

    with pytest.raises(DispatchServiceError) as excinfo:
        match_package_helper(db_session, admin, package)
    assert excinfo.value.code == "offer_exists"


def test_redispatch_radius_auto_progression(db_session):
    """§4.7：重派轮次 radius 25→50→100→0（全城哨兵）自动降档。"""
    admin, package = _onsite_package(db_session)
    assert package.redispatch_radius_km == 25
    publish_package(db_session, actor=admin, package_id=package.id)
    assert package.redispatch_radius_km == 25

    package.dispatch_status = "rejected"
    db_session.flush()
    publish_package(db_session, actor=admin, package_id=package.id)  # round 2
    assert package.redispatch_radius_km == 50

    package.dispatch_status = "rejected"
    db_session.flush()
    publish_package(db_session, actor=admin, package_id=package.id)  # round 3
    assert package.redispatch_radius_km == 100

    package.dispatch_status = "rejected"
    db_session.flush()
    publish_package(db_session, actor=admin, package_id=package.id)  # round 4
    assert package.redispatch_radius_km == 0  # 全城哨兵
    assert package.dispatch_round == 4
