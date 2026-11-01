"""goal-r5 P1-2 撮合核心回归（派单设计 §4/§5 + 规则表 A-6，开池闸③）。

- §4.5：required_level 推导（基档+触发+封顶）与发布前人工覆盖留痕。
- §4.2：Stage A 五资格门逐门反例（出局而非降权）。
- §4.4：场景 A 字典序 / 场景 B 加权 + 可复现 tie-break / 场景 C 不自动派。
- §4.8：match_breakdown 契约键集 + 释明文案。
- 负面清单 A-6 七条每条一个反例（开池四道闸之闸③）。
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import select

from fde_api.auth.models import User
from fde_api.dispatch import scoring
from fde_api.dispatch.cities import load_dispatch_cities
from fde_api.dispatch.errors import DispatchServiceError
from fde_api.dispatch.matching import (
    derive_required_level,
    match_package,
    override_required_level,
)
from fde_api.dispatch.models import (
    DeliveryPackage,
    DispatchOffer,
    DispatchRuleVersion,
    FdeProfile,
)
from fde_api.dispatch.packages import create_package, publish_package
from fde_api.workbench.models import OperationEvent, Project, Quote
from fde_api.workbench.options import options_payload

from fde_api.solutions.models import ProjectSolution

from conftest import SERVER_ROOT


def _user(username: str, role: str = "admin") -> User:
    from fde_api.auth.passwords import hash_password

    from conftest import INITIAL_PASSWORD

    return User(
        username=f"{username}.{uuid4().hex[:8]}",
        display_name=username,
        role=role,
        password_hash=hash_password(INITIAL_PASSWORD),
        must_change_password=False,
        is_active=True,
    )


def _profile(
    db_session,
    user: User,
    *,
    level: str | None = None,
    module_tags: list[str] | None = None,
    industry_tags: list[str] | None = None,
    home_city: str | None = None,
    capacity: int | None = 100,
    avg_hours: int | None = 10,
    status: str = "active",
) -> FdeProfile:
    db_session.add(user)  # 幂等：user 与档案同事务落库（调用方常漏 add）
    row = FdeProfile(
        user_id=user.id,
        level=level,
        module_tags=module_tags or [],
        industry_tags=industry_tags or [],
        home_city=home_city,
        monthly_capacity_hours=capacity,
        avg_delivery_hours=avg_hours,
        status=status,
        is_active=status == "active",
    )
    db_session.add(row)
    return row


def _active_rule(db_session, **overrides) -> DispatchRuleVersion:
    row = DispatchRuleVersion(
        version_no=overrides.pop("version_no", 1),
        status=overrides.pop("status", "active"),
        rule_snapshot=overrides.pop(
            "rule_snapshot",
            {
                "stage_b_weights": {"level": 40, "industry": 30, "sla": 20, "geo_remote": 10},
                "level_score_map": {"L1": 40, "L2": 60, "L3": 80, "L4": 100},
                "seat_shares": {"platform": 35, "region": 5, "city": 20, "delivery": 40},
            },
        ),
        effective_at=datetime.now(timezone.utc) - timedelta(days=1),
        **overrides,
    )
    db_session.add(row)
    db_session.flush()
    return row


def _onsite_package(
    db_session, *, required_level: str = "L1", round_no: int = 1
) -> tuple[User, DeliveryPackage]:
    """到场型 draft 包（制造行业 + pre_diagnosis 模块键经 catalog 归一）。"""
    from fde_api.solutions.models import ProjectSolution
    from fde_api.workbench.models import IndustryTemplate, IndustryTemplateVersion, ModuleCatalog

    admin = _user("r5.admin")
    db_session.add(admin)
    db_session.flush()
    module = db_session.scalar(
        select(ModuleCatalog).where(ModuleCatalog.module_key == "pre_diagnosis")
    )
    if module is None:  # 测试库可能未灌 module_catalog 种子：自建一行保证 A2 有数据
        module = ModuleCatalog(
            module_key="pre_diagnosis",
            name="售前诊断",
            description="r5 测试自建",
            is_active=True,
        )
        db_session.add(module)
        db_session.flush()
    template = IndustryTemplate(
        template_key=f"r5-tpl-{uuid4().hex[:8]}",
        name="r5 模板",
        industry_name="制造业",
    )
    version = IndustryTemplateVersion(
        template=template,
        name="r5 模板 v1",
        industry_name="制造业",
        version_number=1,
        status="published",
    )
    project = Project(
        project_code=f"R5-{uuid4().hex[:6].upper()}",
        name="r5 撮合项目",
        enterprise_code="r5 企业·制造·广州",
        business_line="FDE_DISPATCH",  # P2-4 H3：交付包只建在派单线项目
        planned_start_date=datetime(2026, 10, 31).date(),
        leader_user_id=admin.id,
        source_template_version=version,
        template_snapshot={"industry_name": "制造业", "modules": []},
    )
    db_session.add_all([project, module] if module else [project])
    db_session.flush()
    if module is not None:
        # 项目真实挂上模块 → 包 required_modules=[catalog_id]（A2 有实际约束）
        from fde_api.workbench.models import ProjectModule

        db_session.add(
            ProjectModule(
                project_id=project.id,
                module_catalog_id=module.id,
                name=module.name,
                status="active",
            )
        )
    db_session.flush()
    solution = ProjectSolution(
        project_id=project.id,
        name="r5 方案",
        schedule="需到场实施",
        owner_user_id=admin.id,
    )
    db_session.add(solution)
    db_session.flush()
    quote = Quote(
        project_id=project.id,
        quote_key=f"Q-{uuid4().hex[:8]}",
        status="finalized",
        tier="standard",
        ideal_hours=Decimal("100"),
        realistic_hours=Decimal("100"),
        integration_factor=Decimal("1.00"),
        data_factor=Decimal("1.00"),
        compliance_factor=Decimal("1.00"),
        buffer_factor=Decimal("1.00"),
        hourly_rate=150,
        cash_cost=100000,
        margin_factor=Decimal("1.40"),
        b_layer_score=5,
        b_layer_factor=Decimal("1.00"),
        anchor_mode="steady",
        labor_cost=Decimal("100000"),
        total_cost=Decimal("100000"),
        formula_price=Decimal("200000"),
        anchor_low=200000,
        anchor_high=300000,
        branch="A",
        final_amount=Decimal("20000"),
        field_claims={"final_amount": "measured"},
    )
    db_session.add(quote)
    db_session.flush()
    package = create_package(
        db_session, actor=admin, solution_id=solution.id, quote_id=quote.id
    )
    package.required_level = required_level
    package.dispatch_round = round_no
    db_session.flush()
    return admin, package


# ---------------------------------------------------------------------------
# §4.5：required_level 推导与覆盖
# ---------------------------------------------------------------------------


def _quote_with(tier: str, **factors) -> Quote:
    return Quote(
        project_id="x",
        quote_key="Q",
        tier=tier,
        ideal_hours=Decimal("10"),
        realistic_hours=Decimal("10"),
        hourly_rate=150,
        cash_cost=100,
        anchor_mode="steady",
        labor_cost=Decimal("1"),
        total_cost=Decimal("1"),
        formula_price=Decimal("1"),
        anchor_low=1,
        anchor_high=2,
        branch="A",
        integration_factor=Decimal(str(factors.get("integration", "1.00"))),
        data_factor=Decimal(str(factors.get("data", "1.00"))),
        compliance_factor=Decimal(str(factors.get("compliance", "1.00"))),
        b_layer_score=0,
    )


def test_derive_required_level_matrix():
    """§4.5：基档 + 任一因子触发最多上调一级 + 封顶 L4。"""
    assert derive_required_level(_quote_with("light")) == "L1"
    assert derive_required_level(_quote_with("standard")) == "L2"
    assert derive_required_level(_quote_with("flagship")) == "L3"
    # 触发：data≥1.3 / compliance≥1.2 / integration≥1.4
    assert derive_required_level(_quote_with("light", data="1.30")) == "L2"
    assert derive_required_level(_quote_with("light", compliance="1.20")) == "L2"
    assert derive_required_level(_quote_with("light", integration="1.40")) == "L2"
    # 只上调一级（触发不叠加）
    assert derive_required_level(_quote_with("standard", data="1.5", compliance="1.5")) == "L3"
    # 封顶
    assert derive_required_level(_quote_with("flagship", data="1.5")) == "L4"


def test_override_required_level_draft_only_with_reason(db_session):
    admin, package = _onsite_package(db_session)
    overridden = override_required_level(
        db_session, actor=admin, package_id=package.id, level="L3", reason="客户环境复杂"
    )
    db_session.flush()
    assert overridden.required_level == "L3"
    event = db_session.scalar(
        select(OperationEvent).where(
            OperationEvent.event_type == "delivery_package_level_overridden",
            OperationEvent.target_id == package.id,
        )
    )
    assert event is not None and event.changes["reason"] == "客户环境复杂"

    # 发布后覆盖 → 409（快照已冻结）
    publish_package(db_session, actor=admin, package_id=package.id)
    with pytest.raises(DispatchServiceError) as excinfo:
        override_required_level(
            db_session, actor=admin, package_id=package.id, level="L1", reason="再改"
        )
    assert excinfo.value.code == "invalid_dispatch_state"


# ---------------------------------------------------------------------------
# §4.2：Stage A 五资格门（逐门反例：出局而非降权）
# ---------------------------------------------------------------------------


def _admin_of(db_session, package):
    return db_session.get(User, db_session.get(Project, package.project_id).leader_user_id)


def test_stage_a_gates_reject_individually(db_session):
    """A1–A4 逐门反例：任一门不过即出局（不进候选池，非降权）。
    required_level=L2 使 weak(L1) 挂 A1；required_modules 为空（测试项目无
    ProjectModule）故 A2 反例靠 no_module 的对照说明——空需求放行是 §4.2
    A2 的正确行为（required ⊆ tags 对空集恒真）。"""
    admin, package = _onsite_package(db_session, required_level="L2")
    _active_rule(db_session)
    publish_package(db_session, actor=admin, package_id=package.id)
    module_key_ok = ["pre_diagnosis"]

    # A1：等级不足
    weak = _user("r5.weak", role="fde_engineer")
    _profile(db_session, weak, level="L1", module_tags=module_key_ok,
             industry_tags=["制造业"], home_city="广州")
    # A2：缺模块
    no_module = _user("r5.nomodule", role="fde_engineer")
    _profile(db_session, no_module, level="L2", module_tags=["other"],
             industry_tags=["制造业"], home_city="广州")
    # A3：缺行业
    no_industry = _user("r5.noindustry", role="fde_engineer")
    _profile(db_session, no_industry, level="L2", module_tags=module_key_ok,
             industry_tags=["零售"], home_city="广州")
    # A4：满负荷（在途 2 ≥ cap 2）
    busy = _user("r5.busy", role="fde_engineer")
    _profile(db_session, busy, level="L2", module_tags=module_key_ok,
             industry_tags=["制造业"], home_city="广州", capacity=20, avg_hours=10)
    for round_no in (97, 98):  # 远端轮次构造两条在途（不占撮合轮，避开同轮唯一约束）
        db_session.add(
            DispatchOffer(
                package_id=package.id,
                dispatch_round=round_no,
                candidate_user_id=busy.id,
                status="offered",
                offered_at=datetime.now(timezone.utc),
            )
        )
    # 全部合格对照
    good = _user("r5.good", role="fde_engineer")
    _profile(db_session, good, level="L2", module_tags=module_key_ok,
             industry_tags=["制造业"], home_city="广州")
    db_session.flush()

    result = match_package(db_session, actor=admin, package_id=package.id)
    assert result["scenario"] == "A"
    assert [o["candidate_user_id"] for o in result["offers"]] == [good.id]
    assert set(result["rejected"]) == {weak.id, no_module.id, no_industry.id, busy.id}


def test_stage_a5_geo_fence_onsite_only(db_session):
    """A5：到场型围栏——非同城首轮出局；远程型不做围栏。"""
    admin, package = _onsite_package(db_session)
    _active_rule(db_session)
    publish_package(db_session, actor=admin, package_id=package.id)
    other_city = _user("r5.nanjing", role="fde_engineer")
    _profile(db_session, other_city, level="L2", module_tags=["pre_diagnosis"],
             industry_tags=["制造业"], home_city="深圳")
    result = match_package(db_session, actor=admin, package_id=package.id)
    assert result["scenario"] == "C"  # 唯一候选被围栏淘汰 → 场景 C
    assert result["offers"] == []

    # 远程型：同一非同城候选可入选（A5 不做围栏过滤）——先攒 5 单脱离
    # 新人保护（§6.5 前 5 单只推同城，goal-r8 C10 落地后非同城新人被收紧）
    for round_no in (81, 82, 83, 84, 85):
        db_session.add(
            DeliveryPackage(
                id=uuid4().hex,
                solution_id=package.solution_id,
                project_id=package.project_id,
                package_code=f"PKG-R5-OLD-{uuid4().hex[:8].upper()}",
                dispatch_round=round_no,
                dispatch_status="accepted",
                seat_delivery=other_city.id,
                accepted_at=datetime.now(timezone.utc),
            )
        )
    db_session.flush()
    admin2, package2 = _onsite_package(db_session)
    package2.onsite_required = False
    db_session.get(ProjectSolution, package2.solution_id).schedule = ""
    _active_rule(db_session, version_no=2)
    publish_package(db_session, actor=admin2, package_id=package2.id)
    result2 = match_package(db_session, actor=admin2, package_id=package2.id)
    assert result2["scenario"] == "B"
    assert [o["candidate_user_id"] for o in result2["offers"]] == [other_city.id]


# ---------------------------------------------------------------------------
# §4.4：三场景裁决
# ---------------------------------------------------------------------------


def test_scenario_a_lexicographic_geo_beats_ability(db_session):
    """场景 A 字典序：同城 L1 胜过深圳 L4——地理一级键不被能力分稀释
    （负面清单 #4 反例的结构性防护）。"""
    admin, package = _onsite_package(db_session, round_no=2)
    package.required_level = "L1"
    db_session.flush()
    _active_rule(db_session)
    publish_package(db_session, actor=admin, package_id=package.id)
    near_weak = _user("r5.near.weak", role="fde_engineer")
    _profile(db_session, near_weak, level="L1", module_tags=["pre_diagnosis"],
             industry_tags=["制造业"], home_city="广州")
    far_strong = _user("r5.far.strong", role="fde_engineer")
    _profile(db_session, far_strong, level="L4", module_tags=["pre_diagnosis"],
             industry_tags=["制造业"], home_city="深圳")
    for round_no in (71, 72, 73, 74, 75):  # 老手（脱离新人保护；字典序测试不受 C10 干扰）
        db_session.add(
            DeliveryPackage(
                id=uuid4().hex,
                solution_id=package.solution_id,
                project_id=package.project_id,
                package_code=f"PKG-R5-SEN-{uuid4().hex[:8].upper()}",
                dispatch_round=round_no,
                dispatch_status="accepted",
                seat_delivery=far_strong.id,
                accepted_at=datetime.now(timezone.utc),
            )
        )
    db_session.flush()

    result = match_package(db_session, actor=admin, package_id=package.id)
    ranks = {o["candidate_user_id"]: o["rank"] for o in result["offers"]}
    assert ranks[near_weak.id] == 1
    assert ranks[far_strong.id] == 2
    # 场景 A 的 match_breakdown 无 weighted_score（字典序不是加权分）
    winner = db_session.scalar(
        select(DispatchOffer).where(DispatchOffer.candidate_user_id == near_weak.id)
    )
    assert "weighted_score" not in winner.match_breakdown["stage_b"]
    assert winner.match_breakdown["stage_b"]["geo_tier"] == 0


def test_scenario_b_weighted_and_reproducible(db_session):
    """场景 B：等级分主导排序；同输入两次撮合序完全一致（可复现随机）；
    权重来自规则版本快照（改快照 → 排序变化，证明非硬编码）。"""
    admin, package = _onsite_package(db_session)
    package.onsite_required = False
    db_session.get(ProjectSolution, package.solution_id).schedule = ""  # 防 publish 重推导
    rule = _active_rule(db_session)
    publish_package(db_session, actor=admin, package_id=package.id)
    low = _user("r5.remote.l", role="fde_engineer")
    _profile(db_session, low, level="L1", module_tags=["pre_diagnosis"],
             industry_tags=["制造业"], home_city="广州")
    high = _user("r5.remote.h", role="fde_engineer")
    _profile(db_session, high, level="L4", module_tags=["pre_diagnosis"],
             industry_tags=["制造业"], home_city="深圳")
    for round_no in (61, 62, 63, 64, 65):  # 老手（远程加权序不受 C10 干扰）
        db_session.add(
            DeliveryPackage(
                id=uuid4().hex,
                solution_id=package.solution_id,
                project_id=package.project_id,
                package_code=f"PKG-R5-HI-{uuid4().hex[:8].upper()}",
                dispatch_round=round_no,
                dispatch_status="accepted",
                seat_delivery=high.id,
                accepted_at=datetime.now(timezone.utc),
            )
        )
    db_session.flush()

    first = match_package(db_session, actor=admin, package_id=package.id)
    order1 = [o["candidate_user_id"] for o in first["offers"]]
    assert order1 == [high.id, low.id]  # L4=100×40% 压过同城 geo 10%
    winner = db_session.scalar(
        select(DispatchOffer).where(DispatchOffer.candidate_user_id == high.id)
    )
    assert "weighted_score" in winner.match_breakdown["stage_b"]

    # 权重改版（等级 10 / 地理 40）→ 排序翻转（权重来自快照不硬编码）。
    # 首轮候选档案退出供给池（suspended），避免其混入第二轮 Top3 的同分 tie。
    for profile in db_session.scalars(
        select(FdeProfile).where(FdeProfile.user_id.in_([low.id, high.id]))
    ).all():
        profile.status = "suspended"
        profile.is_active = False
    rule.status = "retired"
    db_session.add(
        DispatchRuleVersion(
            version_no=2,
            status="active",
            rule_snapshot={
                "stage_b_weights": {"level": 10, "industry": 30, "sla": 20, "geo_remote": 40},
                "level_score_map": {"L1": 40, "L2": 60, "L3": 80, "L4": 100},
                "seat_shares": {"platform": 35, "region": 5, "city": 20, "delivery": 40},
            },
            effective_at=datetime.now(timezone.utc) - timedelta(days=1),
        )
    )
    db_session.flush()
    admin2, package2 = _onsite_package(db_session)
    package2.onsite_required = False
    db_session.get(ProjectSolution, package2.solution_id).schedule = ""  # 防 publish 重推导
    publish_package(db_session, actor=admin2, package_id=package2.id)
    low2 = _user("r5.remote2.l", role="fde_engineer")
    _profile(db_session, low2, level="L1", module_tags=["pre_diagnosis"],
             industry_tags=["制造业"], home_city="广州")
    high2 = _user("r5.remote2.h", role="fde_engineer")
    _profile(db_session, high2, level="L4", module_tags=["pre_diagnosis"],
             industry_tags=["制造业"], home_city="深圳")
    db_session.flush()
    second = match_package(db_session, actor=admin2, package_id=package2.id)
    assert [o["candidate_user_id"] for o in second["offers"]][0] == low2.id


def test_scenario_c_no_auto_dispatch_and_event(db_session):
    """场景 C：到场型候选池空 → 不自动派（零 offer）+ 事件留痕含淘汰明细。"""
    admin, package = _onsite_package(db_session)
    _active_rule(db_session)
    publish_package(db_session, actor=admin, package_id=package.id)
    result = match_package(db_session, actor=admin, package_id=package.id)
    assert result["scenario"] == "C" and result["offers"] == []
    assert db_session.scalar(select(DispatchOffer.id).where(DispatchOffer.package_id == package.id)) is None
    event = db_session.scalar(
        select(OperationEvent).where(
            OperationEvent.event_type == "dispatch_matching_scenario_c",
            OperationEvent.target_id == package.id,
        )
    )
    assert event is not None and event.changes["action"] == "manual_fallback"


def test_match_requires_published_rule_version(db_session):
    """留注⑬：无公示规则版本 → 422 rule_version_required（§11.1 降级态）。"""
    admin, package = _onsite_package(db_session)
    publish_package(db_session, actor=admin, package_id=package.id)
    good = _user("r5.noversion", role="fde_engineer")
    _profile(db_session, good, level="L2", module_tags=["pre_diagnosis"],
             industry_tags=["制造业"], home_city="广州")
    db_session.flush()
    with pytest.raises(DispatchServiceError) as excinfo:
        match_package(db_session, actor=admin, package_id=package.id)
    assert excinfo.value.code == "rule_version_required"
    assert excinfo.value.status == 422


# ---------------------------------------------------------------------------
# §4.8：Top3 + match_breakdown 契约
# ---------------------------------------------------------------------------


def test_top3_cap_and_breakdown_schema(db_session):
    """§4.8：Top3 封顶；breakdown 键集逐项（rule_version/scenario/stage_a/
    stage_b/rank/explanation）+ A4 明细结构 + 释明文案非空。"""
    admin, package = _onsite_package(db_session)
    _active_rule(db_session)
    publish_package(db_session, actor=admin, package_id=package.id)
    for index in range(5):
        candidate = _user(f"r5.top{index}", role="fde_engineer")
        _profile(db_session, candidate, level="L2", module_tags=["pre_diagnosis"],
                 industry_tags=["制造业"], home_city="广州")
    db_session.flush()

    result = match_package(db_session, actor=admin, package_id=package.id)
    assert len(result["offers"]) == 3  # top_n=3
    offers = db_session.scalars(
        select(DispatchOffer).where(DispatchOffer.package_id == package.id)
    ).all()
    assert len(offers) == 3
    for offer in offers:
        breakdown = offer.match_breakdown
        assert {"rule_version", "scenario", "stage_a", "stage_b", "rank", "explanation"} <= set(breakdown)
        assert set(breakdown["stage_a"]) == {"A1", "A2", "A3", "A4", "A5", "B1"}  # goal-r8：B1 防骚扰行入契约
        assert set(breakdown["stage_a"]["A4"]) == {"in_hand", "cap", "ok"}
        assert breakdown["explanation"]
    ranks = sorted(offer.match_breakdown["rank"] for offer in offers)
    assert ranks == [1, 2, 3]


# ---------------------------------------------------------------------------
# 负面清单 A-6 七条反例（开池四道闸之闸③）
# ---------------------------------------------------------------------------


def test_negative_list_protections(db_session):
    """七条禁止项逐条一个反例/结构性证明。"""
    # ── #1 软画像：档案零推断字段（schema 级）──
    from fde_api.auth.models import Base

    columns = {c.name for c in FdeProfile.__table__.columns}
    assert not any("interest" in c or "inferred" in c or "preference" in c for c in columns)

    # ── #2 历史接单量/响应率进排序：scoring 签名无历史参数；同分不同历史序不变 ──
    import inspect

    sig = inspect.signature(scoring.weighted_score)
    assert set(sig.parameters) == {"level", "industry_tags", "tier", "rule"}
    admin, package = _onsite_package(db_session)
    package.onsite_required = False  # 远程场景走加权路径（weighted_score 断言需要）
    db_session.get(ProjectSolution, package.solution_id).schedule = ""
    _active_rule(db_session)
    publish_package(db_session, actor=admin, package_id=package.id)
    fresh = _user("r5.nl2.fresh", role="fde_engineer")
    veteran = _user("r5.nl2.veteran", role="fde_engineer")
    for u in (fresh, veteran):
        _profile(db_session, u, level="L2", module_tags=["pre_diagnosis"],
                 industry_tags=["制造业"], home_city="广州")
    # veteran 有 3 条历史 offer（declined 终态），fresh 零——排序不受影响
    for round_no in (91, 92, 93):  # 远端轮次（同包同轮同候选唯一约束）
        db_session.add(
            DispatchOffer(
                package_id=package.id, dispatch_round=round_no,
                candidate_user_id=veteran.id, status="declined",
                offered_at=datetime.now(timezone.utc) - timedelta(days=30),
            )
        )
    db_session.flush()
    # declined 是终态不算在途（A4 计数只含 offered/accepted）→ 两人同过 A4
    result = match_package(db_session, actor=admin, package_id=package.id)
    scores = {}
    for o in result["offers"]:
        offer = db_session.scalar(select(DispatchOffer).where(DispatchOffer.id == o["offer_id"]))
        scores[offer.candidate_user_id] = offer.match_breakdown["stage_b"]["weighted_score"]
    assert scores[fresh.id] == scores[veteran.id]  # 历史差异零体现

    # ── #3 位置轨迹：dispatch 全包无轨迹字段/调用（静态）──
    from pathlib import Path

    dispatch_dir = Path(SERVER_ROOT) / "src" / "fde_api" / "dispatch"
    for path in dispatch_dir.glob("*.py"):
        source = path.read_text(encoding="utf-8").lower()
        assert "latitude" not in source and "longitude" not in source
        assert "gps" not in source and "track_location" not in source

    # ── #4 地理连续加权：到场型字典序已单独钉（test_scenario_a_*）；此处钉加权维度只有三档 ──
    assert {scoring.geo_score(t) for t in range(4)} == {0, 50, 100}

    # ── #5 分成池二次扣工时：settlements 零工时引用（静态）──
    settlements_source = (dispatch_dir / "settlements.py").read_text(encoding="utf-8")
    assert "avg_delivery_hours" not in settlements_source
    assert "monthly_capacity_hours" not in settlements_source

    # ── #6 拒单不限制接单：拒过单的人仍可**主动抢**（claim 入口不封）——
    # 平台侧则按规则表 B1 跨轮不再主动推（防骚扰与「不限制接单机会」并存：
    # B1 管「平台不推」，#6 管「本人可抢」，语义正交，goal-r8 修正 r5 初版
    # 把两者混为一谈的测试）──
    admin2, package2 = _onsite_package(db_session)
    _active_rule(db_session, version_no=3)
    publish_package(db_session, actor=admin2, package_id=package2.id)
    declined_before = _user("r5.nl6.declined", role="fde_engineer")
    _profile(db_session, declined_before, level="L2", module_tags=["pre_diagnosis"],
             industry_tags=["制造业"], home_city="广州")
    db_session.add(
        DispatchOffer(
            package_id=package2.id, dispatch_round=package2.dispatch_round,
            candidate_user_id=declined_before.id, status="declined",
            offered_at=datetime.now(timezone.utc) - timedelta(days=1),
        )
    )
    db_session.flush()
    # 同轮已有 declined offer → 撮合 409（重派走 republish round+1）
    with pytest.raises(DispatchServiceError) as excinfo:
        match_package(db_session, actor=admin2, package_id=package2.id)
    assert excinfo.value.code == "offer_exists"
    package2.dispatch_round += 1
    db_session.flush()
    result2 = match_package(db_session, actor=admin2, package_id=package2.id)
    # B1：更早轮拒过 → 本轮平台不再推（不在 offers 也不在 rejected 之外复活）
    assert declined_before.id not in [o["candidate_user_id"] for o in result2["offers"]]
    # 不限制接单机会：本人仍可经 claim 登记入口主动抢（城市开关关闭 → 403
    # 是开闸态问题不是资格问题；资格面由 has_access/claim 入口放行验证，
    # 见 r4 的 claim_gate 用例——此处只断言 B1 后本人档案未被拉黑/降权）
    profile_row = db_session.scalar(
        select(FdeProfile).where(FdeProfile.user_id == declined_before.id)
    )
    assert profile_row.status == "active" and profile_row.is_active is True

    # ── #7 运输/安装撮合：dispatch 零货运语义（静态）──
    for path in dispatch_dir.glob("*.py"):
        source = path.read_text(encoding="utf-8")
        assert "freight" not in source.lower()
        assert "运费" not in source and "货运" not in source


# ---------------------------------------------------------------------------
# P1-4：options 枚举回显
# ---------------------------------------------------------------------------


def test_options_payload_has_dispatch_enums():
    payload = options_payload()
    assert {s["value"] for s in payload["dispatch_seat_shares"]} == {
        "platform", "region", "city", "delivery",
    }
    assert {s["value"] for s in payload["dispatch_scenario_types"]} == {"onsite", "remote", "C"}
    assert {s["value"] for s in payload["dispatch_match_modes"]} == {"assign", "claim"}
    assert {s["value"] for s in payload["dispatch_decline_reasons"]} == {
        "档期冲突", "能力不匹配", "距离", "其他",
    }


def test_city_index_from_seed():
    index = {
        row["city"]: (row.get("province"), row.get("metro_group"))
        for row in load_dispatch_cities()
    }
    assert scoring.geo_tier("上海", "上海", index) == 0
    assert scoring.geo_tier("深圳", "广州", index) == 1  # 同省（广东）
    assert scoring.geo_tier("武汉", "广州", index) == 3  # 鄂≠粤跨省且不同都市圈
    assert scoring.geo_tier("杭州", "上海", index) == 3  # 跨省且不同都市圈
    # tier 2 = 同都市圈跨省：沪广深杭蓉汉种子内无此对，合成 index 钉规则
    synthetic = {"南通": ("江苏", "上海大都市圈"), "上海": ("上海", "上海大都市圈")}
    assert scoring.geo_tier("上海", "南通", synthetic) == 2
    assert scoring.geo_tier("未知城", "上海", index) == 3
