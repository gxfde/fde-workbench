"""撮合仿真器（goal-r9，留注⑳ + BP §11 H2/H3 闸门的内测/仿真口径）。

两件套：

- ``replay_scoring(session)`` —— 历史包只读回放打分：对库内已进入撮合流程的
  交付包，按**当前**供给池与 active 规则版本重跑 Stage A/B（不落 offer、
  不迁状态、不写事件）。这是 P2-1 权重配置「仿真对比」视图的数据源：
  权重调整前后各跑一次即可对照。
- ``run_simulation(session, ...)`` —— 沙箱库全链路仿真：建包→发布→撮合→
  接单（含拒单/超时→重派→场景 C 人工回退）走真实服务函数与真实引擎；
  人工环节（接单意愿、G9 一次通过、工时投入）按**显式假设表**采样。
  产出 BP §11 闸门指标：H2 一次通过率（P3 ≥70%）、H3 平台工时占比 ≤25% 与
  毛利率 ≥70%（P4）——内测/仿真数据先行口径。

诚实纪律（报告 meta 逐字回显）：
- 口径 = simulation：指标是「假设表 × 真实引擎」的合成结果，不冒充真实业务数据；
- 假设全部集中在 DEFAULT_ASSUMPTIONS，可经 params 覆盖，报告逐项回显；
- H2 同时给出「随机派单基线」（同一假设表下按供给池等级混合与需求等级分布
  算期望）——仿真器要回答的是「撮合引擎把一次通过率抬了多少」，不是单点数字；
- 随机性 = random.Random(seed) 单流；报告不含 uuid 与墙钟，同 seed 可复现。
"""

from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Mapping

from sqlalchemy import select
from sqlalchemy.orm import Session

from fde_api.auth.models import User
from fde_api.dispatch import scoring
from fde_api.dispatch.matching import _stage_a, match_package
from fde_api.dispatch.models import (
    DeliveryPackage,
    DispatchOffer,
    DispatchRuleVersion,
    FdeProfile,
    resolve_onsite_required,
)
from fde_api.dispatch.offer_service import (
    accept_offer,
    decline_offer,
    expire_stale_offers,
)
from fde_api.dispatch.packages import (
    create_package,
    publish_package,
)
from fde_api.dispatch.rules import active_rule_version
from fde_api.dispatch.settlements import seat_shares_for
from fde_api.solutions.models import ProjectSolution
from fde_api.system_configuration import DISPATCH_CONSTANTS
from fde_api.workbench.models import (
    IndustryTemplate,
    IndustryTemplateVersion,
    ModuleCatalog,
    Project,
    ProjectModule,
    Quote,
)

SIM_CITIES = ("苏州", "合肥", "佛山", "东莞", "武汉", "成都")
SIM_TIERS = ("light", "standard", "flagship")
# 供给池等级混合（12 人）：仿真输入假设，报告回显
_POOL_LEVEL_MIX = ("L1", "L2", "L2", "L2", "L3", "L3", "L3", "L4", "L1", "L2", "L3", "L4")
# 档位基准成交额（元）：仿真输入假设，报告回显
_TIER_AMOUNT = {"light": 60000, "standard": 100000, "flagship": 180000}
# 档位基准交付工时（小时）：仿真输入假设，报告回显
_TIER_DELIVERY_HOURS = {"light": 60.0, "standard": 100.0, "flagship": 160.0}

DEFAULT_ASSUMPTIONS: dict[str, Any] = {
    # 接单意愿（按 Top3 顺位衰减）；其余概率 = 超时
    "accept_probability_by_rank": {"1": 0.80, "2": 0.65, "3": 0.55},
    "decline_probability_by_rank": {"1": 0.10, "2": 0.15, "3": 0.20},
    # G9 一次通过率：候选等级 − 需求等级 的差额 → 首过概率（申报式假设表，
    # 待真实内测数据校准；引擎 A1 门槛保证 delta ≥ 0）
    "g9_first_pass_by_level_delta": {"0": 0.72, "1": 0.84, "2": 0.91, "3": 0.95},
    "g9_rework_pass_probability": 0.90,
    # 工时投入（小时）：平台侧只做编排+质检（BP R4 缓解：平台不抢交付）；
    # 场景 C 人工回退时平台承担寻源与协调 → ×3
    "platform_hours_auto_min": 6.0,
    "platform_hours_auto_max": 10.0,
    "scenario_c_platform_hours_multiplier": 3.0,
    "delivery_hours_jitter": 0.15,
    # 平台侧工时成本（元/小时）
    "platform_hourly_cost": 150,
    "max_rounds": 3,
}

_REPORT_DISCIPLINE = (
    "口径=simulation（假设表×真实引擎的合成结果，非真实业务数据）；"
    "随机性=random.Random(seed) 单流，同 seed 可复现；"
    "撮合/席位/时间常数走真实引擎与规则版本。"
)


# ---------------------------------------------------------------- 回放打分

def _rank_readonly(
    session: Session,
    package: DeliveryPackage,
    quote: Quote | None,
    version: DispatchRuleVersion,
) -> dict[str, Any]:
    """只读 Stage A/B（与 match_package 同管线，不落 offer）。"""
    passed, rejected = _stage_a(session, package, quote)
    # F 线 T5：到场型判定走唯一权威原语（NULL＝未设置⇒默认到场型）。
    scenario = (
        "onsite" if resolve_onsite_required(package) else "remote"
    )
    if not passed:
        return {
            "scenario": "C",
            "stage_a_pass": False,
            "candidates": 0,
            "rejected": len(rejected),
            "top": [],
        }
    rule = dict(version.rule_snapshot or {})
    rule["_required_industry"] = package.required_industry
    seed = scoring.tie_break_seed(package.id, package.dispatch_round, version.version_no)
    ranked: list[tuple[tuple, dict[str, Any]]] = []
    for entry in passed:
        profile = entry["profile"]
        industry = scoring.industry_score(
            profile.industry_tags, package.required_industry
        )
        if scenario == "onsite":
            key = scoring.sort_key_onsite(
                tier=entry["tier"],
                level=profile.level,
                industry=industry,
                sla=scoring.sla_score(),
            )
            score = None
        else:
            score = scoring.weighted_score(
                level=profile.level,
                industry_tags=profile.industry_tags,
                tier=entry["tier"],
                rule=rule,
            )
            key = scoring.sort_key_remote(
                weighted=score,
                in_fence=scoring.in_fence(
                    profile.home_city, entry["client_city"], profile.geo_fence_km
                ),
                seed=seed,
                candidate_key=profile.user_id,
            )
        ranked.append((key, {"level": profile.level, "weighted": score}))
    ranked.sort(key=lambda item: item[0])
    top_n = int(DISPATCH_CONSTANTS["top_n"])
    return {
        "scenario": "A" if scenario == "onsite" else "B",
        "stage_a_pass": True,
        "candidates": len(passed),
        "rejected": len(rejected),
        "top": [item for _, item in ranked[:top_n]],
    }


def replay_scoring(session: Session) -> dict[str, Any]:
    """历史包回放打分（只读）：当前池 × 当前规则版本的再撮合画像。"""
    version = active_rule_version(session)
    packages = session.scalars(
        select(DeliveryPackage).where(
            DeliveryPackage.dispatch_status.in_(
                ("published", "offered", "assigned", "accepted")
            )
        )
    ).all()
    rows: list[dict[str, Any]] = []
    scenario_counts = {"A": 0, "B": 0, "C": 0}
    top1_scores: list[int] = []
    candidate_counts: list[int] = []
    for package in packages:
        quote = session.get(Quote, package.quote_id) if package.quote_id else None
        if version is None:
            rows.append(
                {
                    "package_code": package.package_code,
                    "round": package.dispatch_round,
                    "skipped": "no_active_rule_version",
                }
            )
            continue
        result = _rank_readonly(session, package, quote, version)
        scenario_counts[result["scenario"]] = (
            scenario_counts.get(result["scenario"], 0) + 1
        )
        if result["top"]:
            first = result["top"][0].get("weighted")
            if first is not None:
                top1_scores.append(int(first))
            candidate_counts.append(result["candidates"])
        rows.append(
            {
                "package_code": package.package_code,
                "round": package.dispatch_round,
                "scenario": result["scenario"],
                "stage_a_pass": result["stage_a_pass"],
                "candidates": result["candidates"],
                "rejected": result["rejected"],
                "top": result["top"],
            }
        )
    return {
        "mode": "replay",
        "rule_version": version.version_no if version else None,
        "packages": rows,
        "summary": {
            "replayed": len(packages),
            "scenario_counts": scenario_counts,
            "stage_a_pass_rate": (
                round(
                    sum(1 for r in rows if r.get("stage_a_pass")) / len(packages), 4
                )
                if packages
                else None
            ),
            "avg_candidates_when_passable": (
                round(sum(candidate_counts) / len(candidate_counts), 2)
                if candidate_counts
                else None
            ),
            "avg_top1_weighted_remote": (
                round(sum(top1_scores) / len(top1_scores), 1)
                if top1_scores
                else None
            ),
        },
    }


# ---------------------------------------------------------------- 仿真

def _seed_supply_pool(
    session: Session, rng: random.Random, module_key: str
) -> tuple[User, list[User]]:
    """平台账号 + 12 人供给池（等级/城市/模块假设分布，报告回显）。

    module_key 取自库内 active 模块目录（仿真不发明模块键）。"""
    admin = User(
        username=f"sim-admin.{rng.randrange(10**8):08d}",
        display_name="sim 平台管理员",
        role="admin",
        password_hash="!",
        must_change_password=False,
        is_active=True,
    )
    session.add(admin)
    candidates: list[User] = []
    for idx, level in enumerate(_POOL_LEVEL_MIX):
        user = User(
            username=f"sim-fde-{idx}.{rng.randrange(10**8):08d}",
            display_name=f"sim 交付方 {idx}",
            role="fde_engineer",
            password_hash="!",
            must_change_password=False,
            is_active=True,
        )
        session.add(user)
        session.flush()
        profile = FdeProfile(
            user_id=user.id,
            level=level,
            level_verified_at=datetime(2026, 10, 1, tzinfo=timezone.utc),
            biz_cognition_score=3,
            scenario_eng_score=3,
            ai_tech_score=3,
            delivery_assure_score=3,
            industry_tags=["制造业"],
            module_tags=[module_key, "solution_design"],
            service_cities=[SIM_CITIES[idx % len(SIM_CITIES)]],
            home_city=SIM_CITIES[idx % len(SIM_CITIES)],
            geo_fence_km=100,
            monthly_capacity_hours=160,
            avg_delivery_hours=80,
            is_active=True,
            status="active",
        )
        session.add(profile)
        candidates.append(user)
    session.flush()
    return admin, candidates


def _seed_rule_version(session: Session) -> DispatchRuleVersion:
    """active 规则版本（首版快照 = DISPATCH_CONSTANTS 的 §6.2/§7.1 取值）。"""
    existing = active_rule_version(session)
    if existing is not None:
        return existing
    row = DispatchRuleVersion(
        version_no=1,
        status="active",
        rule_snapshot={
            "stage_b_weights": dict(DISPATCH_CONSTANTS["stage_b_weights"]),
            "level_score_map": dict(DISPATCH_CONSTANTS["level_score_map"]),
            "seat_shares": dict(DISPATCH_CONSTANTS["seat_shares"]),
        },
        published_at=datetime(2026, 9, 1, tzinfo=timezone.utc),
        effective_at=datetime(2026, 10, 1, tzinfo=timezone.utc),
    )
    session.add(row)
    session.flush()
    return row


def _seed_template(session: Session, rng: random.Random) -> IndustryTemplateVersion:
    template = IndustryTemplate(
        template_key=f"sim-tpl-{rng.randrange(10**8):08d}",
        name="sim 模板",
        industry_name="制造业",
    )
    version = IndustryTemplateVersion(
        template=template,
        name="sim 模板 v1",
        industry_name="制造业",
        version_number=1,
        status="published",
    )
    session.add(version)
    session.flush()
    return version


def _synthetic_demand(
    session: Session,
    *,
    index: int,
    admin: User,
    template_version: IndustryTemplateVersion,
    module_catalog_id: str,
    rng: random.Random,
) -> tuple[Project, DeliveryPackage]:
    """一个仿真需求：派单线项目 + active 方案 + finalized 报价 + draft 交付包。"""
    tier = SIM_TIERS[index % len(SIM_TIERS)]
    city = SIM_CITIES[index % len(SIM_CITIES)]
    project = Project(
        # 尾段 = rng 六位（project_code 尾段决定 package_code，须互异）
        project_code=f"SIM-{index:04d}-{rng.randrange(10**6):06d}",
        name=f"sim 需求 {index:04d}",
        enterprise_code=f"sim 客户{index:04d}·制造业·{city}",
        business_line="FDE_DISPATCH",  # P2-4 H3：交付包只建在派单线项目
        planned_start_date=datetime(2026, 11, 3).date(),
        leader_user_id=admin.id,
        source_template_version=template_version,
        template_snapshot={"industry_name": "制造业", "modules": []},
    )
    session.add(project)
    session.flush()
    session.add(
        ProjectModule(
            project_id=project.id,
            module_catalog_id=module_catalog_id,
            name="初步诊断",
            status="active",
        )
    )
    solution = ProjectSolution(
        project_id=project.id,
        name=f"sim 方案 {index:04d}",
        owner_user_id=admin.id,
        status="active",
    )
    session.add(solution)
    session.flush()
    realistic = Decimal(str(_TIER_DELIVERY_HOURS[tier]))
    quote = Quote(
        project_id=project.id,
        quote_key=f"Q-SIM-{index:04d}",
        status="finalized",
        tier=tier,
        ideal_hours=Decimal(str(_TIER_DELIVERY_HOURS[tier] * 0.8)),
        realistic_hours=realistic,
        integration_factor=Decimal("1.00"),
        data_factor=Decimal("1.00"),
        compliance_factor=Decimal("1.00"),
        buffer_factor=Decimal("1.00"),
        hourly_rate=150,
        cash_cost=int(_TIER_AMOUNT[tier] * 0.5),
        margin_factor=Decimal("1.40"),
        b_layer_score=5,
        b_layer_factor=Decimal("1.00"),
        anchor_mode="steady",
        labor_cost=Decimal(str(int(_TIER_AMOUNT[tier] * 0.5))),
        total_cost=Decimal(str(int(_TIER_AMOUNT[tier] * 0.5))),
        formula_price=Decimal(str(_TIER_AMOUNT[tier])),
        anchor_low=int(_TIER_AMOUNT[tier]),
        anchor_high=int(_TIER_AMOUNT[tier] * 1.5),
        branch="A",
        final_amount=Decimal(str(int(_TIER_AMOUNT[tier] * 0.2))),
        field_claims={"final_amount": "measured"},
    )
    session.add(quote)
    session.flush()
    package = create_package(
        session,
        actor=admin,
        solution_id=solution.id,
        quote_id=quote.id,
        dispatch_mode="assign",
    )
    return project, package


def _delta_of(candidate_level: str | None, required_level: str | None) -> int:
    delta = scoring.level_rank(candidate_level) - scoring.level_rank(required_level)
    return max(0, min(delta, 3))


def _random_assignment_baseline(
    required_levels: list[str | None], g9_p: Mapping[str, float]
) -> float | None:
    """随机派单基线：候选等级从池内混合等概率抽（不挑人），对观测到的需求
    等级分布求期望首过率。同一假设表——对比的是「引擎挑人 vs 不挑人」。"""
    if not required_levels:
        return None
    mix = list(_POOL_LEVEL_MIX)
    total = 0.0
    for required in required_levels:
        for candidate in mix:
            delta = _delta_of(candidate, required)
            total += float(g9_p.get(str(delta), 0.72))
    return round(total / (len(required_levels) * len(mix)), 4)


def _require_sandbox_session(session: Session) -> None:
    """W1-3：仿真只能写沙箱库——守卫下沉到 run_simulation 入口本身。

    此前库名校验只在 CLI main() 读 FDE_DATABASE_URL，任何直接 import 调用
    run_simulation(session) 的路径都能绕过，把仿真 finalized 单写进业务库。
    这里从 session 实际绑定的连接读库名（不是环境变量），因此被测用例传
    fde_workbench_test（_test 后缀）同样放行，不破坏测试；生产库 fde_workbench
    无后缀则 fail-fast。与 conftest._ALLOWED_TEST_DATABASE_NAMES 同口径。
    """
    # connection().engine.url 类型明确（get_bind() 返回 Engine|Connection union，
    # 直接取 .url 会触发 mypy union-attr；Connection 经 .engine 统一到 Engine）。
    database = session.connection().engine.url.database or ""
    if not database.rsplit("/", 1)[-1].split("?")[0].endswith(("_sim", "_test")):
        raise RuntimeError(
            f"拒绝执行：run_simulation 只能绑定沙箱库（库名以 _sim/_test 结尾），"
            f"当前库={database!r}。"
        )


def run_simulation(
    session: Session,
    *,
    scenarios: int = 24,
    seed: int = 42,
    params: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """种子化全链路仿真 → H2/H3 报告（沙箱库执行；结束一次性 commit）。"""
    _require_sandbox_session(session)
    assumptions = dict(DEFAULT_ASSUMPTIONS)
    if params:
        unknown = set(params) - set(assumptions)
        if unknown:
            raise ValueError(f"未知仿真参数：{sorted(unknown)}")
        assumptions.update(params)
    rng = random.Random(seed)
    module = session.scalar(
        select(ModuleCatalog)
        .where(ModuleCatalog.is_active.is_(True))
        .order_by(ModuleCatalog.sort_order)
        .limit(1)
    )
    if module is None:
        raise RuntimeError(
            "module_catalog 为空：先跑 load_seeds.py（仿真前置，不发明模块键）。"
        )
    admin, _candidates = _seed_supply_pool(session, rng, module.module_key)
    _seed_rule_version(session)
    template_version = _seed_template(session, rng)
    rows: list[dict[str, Any]] = []
    accept_p = assumptions["accept_probability_by_rank"]
    decline_p = assumptions["decline_probability_by_rank"]
    g9_p = assumptions["g9_first_pass_by_level_delta"]
    max_rounds = int(assumptions["max_rounds"])

    for index in range(1, scenarios + 1):
        _project, package = _synthetic_demand(
            session,
            index=index,
            admin=admin,
            template_version=template_version,
            module_catalog_id=module.id,
            rng=rng,
        )
        publish_package(session, actor=admin, package_id=package.id, candidate_user_ids=())
        session.flush()
        outcome = "unfilled"
        accepted_level: str | None = None
        required_level = package.required_level
        rounds_used = 0
        for round_no in range(1, max_rounds + 1):
            rounds_used = round_no
            result = match_package(session, actor=admin, package_id=package.id)
            session.flush()
            if result["scenario"] == "C":
                outcome = "scenario_c_manual"
                break
            offer_rows = list(
                session.scalars(
                    select(DispatchOffer).where(
                        DispatchOffer.package_id == package.id,
                        DispatchOffer.dispatch_round == package.dispatch_round,
                        DispatchOffer.status == "offered",
                    )
                ).all()
            )
            offer_rows.sort(key=lambda o: (o.match_breakdown or {}).get("rank", 9))
            taken = False
            for offer in offer_rows:
                rank = str((offer.match_breakdown or {}).get("rank", "3"))
                draw = rng.random()
                accept_p_rank = float(accept_p.get(rank, 0.5))
                if draw < accept_p_rank:
                    candidate = session.get(User, offer.candidate_user_id)
                    if candidate is None:
                        continue
                    accept_offer(
                        session,
                        actor=candidate,
                        offer_id=offer.id,
                        expected_version=offer.version,
                    )
                    session.flush()
                    accepted_level = ((offer.match_breakdown or {}).get("stage_b") or {}).get(
                        "ability", {}
                    ).get("level")
                    outcome = "accepted"
                    taken = True
                    break
                if draw < accept_p_rank + float(decline_p.get(rank, 0.2)):
                    decliner = session.get(User, offer.candidate_user_id)
                    if decliner is None:
                        continue
                    decline_offer(
                        session,
                        actor=decliner,
                        offer_id=offer.id,
                        expected_version=offer.version,
                        reason="档期冲突",
                    )
            if taken:
                break
            session.flush()
            round_before = package.dispatch_round
            expired = expire_stale_offers(
                session, now=datetime.now(timezone.utc) + timedelta(hours=25)
            )
            session.flush()
            if expired == 0 or round_no >= max_rounds:
                break
            # 重派：expired → published（radius 随轮次推进，§4.7）
            # F 线 T5：expire_stale_offers 内已接线「15 分钟逐级自动扩圈」
            # ⇒ 自动扩圈可能已把包推回 published 且轮次+1；此时**不得**再
            # 手工重发（重复重发会被状态机拒绝）。已自动扩圈则跳过。
            if package.dispatch_round > round_before:
                session.flush()
                continue
            publish_package(
                session, actor=admin, package_id=package.id, candidate_user_ids=()
            )
            session.flush()
        # 交付结果（G9 假设表采样）与工时/收入
        delivered = False
        first_pass = False
        platform_hours = 0.0
        delivery_hours = 0.0
        amount = 0
        quote_row = (
            session.get(Quote, package.quote_id) if package.quote_id else None
        )
        tier = quote_row.tier if quote_row is not None else "standard"
        base_hours = _TIER_DELIVERY_HOURS.get(tier, 100.0)
        jitter = 1.0 + rng.uniform(-1.0, 1.0) * float(
            assumptions["delivery_hours_jitter"]
        )
        if outcome == "accepted":
            delta = _delta_of(accepted_level, required_level)
            first_pass = rng.random() < float(g9_p.get(str(delta), 0.72))
            delivered = first_pass or rng.random() < float(
                assumptions["g9_rework_pass_probability"]
            )
            platform_hours = rng.uniform(
                float(assumptions["platform_hours_auto_min"]),
                float(assumptions["platform_hours_auto_max"]),
            )
            delivery_hours = base_hours * jitter + (
                0.0 if first_pass else base_hours * 0.2
            )
            amount = _TIER_AMOUNT.get(tier, 100000)
        elif outcome == "scenario_c_manual":
            # 场景 C 人工回退：平台寻源+协调，人工派单不丢单；一次通过按
            # 零差额档计（人工可挑人，等同于引擎 A1 门槛 + 人工择优）。
            platform_hours = rng.uniform(
                float(assumptions["platform_hours_auto_min"]),
                float(assumptions["platform_hours_auto_max"]),
            ) * float(assumptions["scenario_c_platform_hours_multiplier"])
            delivery_hours = base_hours * jitter
            first_pass = rng.random() < float(g9_p.get("0", 0.72))
            delivered = True
            amount = _TIER_AMOUNT.get(tier, 100000)
        platform_income = Decimal("0")
        platform_cost = Decimal("0")
        if amount:
            shares = seat_shares_for(session, package)
            amount_dec = Decimal(str(amount))
            platform_income = amount_dec * Decimal(shares["platform"]) / Decimal(100)
            platform_cost = Decimal(str(round(platform_hours, 1))) * Decimal(
                str(assumptions["platform_hourly_cost"])
            )
        rows.append(
            {
                "code": f"SIM-{index:04d}",
                "tier": tier,
                "required_level": required_level,
                "accepted_level": accepted_level,
                "rounds": rounds_used,
                "outcome": outcome,
                "g9_first_pass": first_pass,
                "delivered": delivered,
                "platform_hours": round(platform_hours, 1),
                "delivery_hours": round(delivery_hours, 1),
                "amount": amount,
                "platform_income": float(platform_income),
                "platform_cost": float(platform_cost),
            }
        )
    session.commit()
    baseline = _random_assignment_baseline(
        [r["required_level"] for r in rows], g9_p
    )
    return _aggregate(
        rows, scenarios=scenarios, seed=seed, assumptions=assumptions, baseline=baseline
    )


def _aggregate(
    rows: list[dict[str, Any]],
    *,
    scenarios: int,
    seed: int,
    assumptions: Mapping[str, Any],
    baseline: float | None,
) -> dict[str, Any]:
    accepted = [r for r in rows if r["outcome"] == "accepted"]
    delivered = [r for r in rows if r["delivered"]]
    first_pass_delivered = [r for r in delivered if r["g9_first_pass"]]
    total_hours = sum(r["platform_hours"] + r["delivery_hours"] for r in rows)
    platform_hours = sum(r["platform_hours"] for r in rows)
    platform_income = sum(Decimal(str(r["platform_income"])) for r in rows)
    platform_cost = sum(Decimal(str(r["platform_cost"])) for r in rows)
    # H2 分母 = 已交付单（BP 口径「生态交付 G9 一次通过率」）；未成交付进漏斗
    h2_rate = (
        round(len(first_pass_delivered) / len(delivered), 4) if delivered else None
    )
    h3_worktime = round(platform_hours / total_hours, 4) if total_hours else None
    gross_margin = (
        float(round((platform_income - platform_cost) / platform_income, 4))
        if platform_income
        else None
    )
    return {
        "mode": "simulation",
        "meta": {
            "scenarios": scenarios,
            "seed": seed,
            "discipline": _REPORT_DISCIPLINE,
            "bp_gates": {
                "H2_g9_first_pass_target": "≥ 0.70（BP §11 P3 生态起步）",
                "H3_platform_hours_target": "≤ 0.25（BP §11 P4 规模化）",
                "H3_gross_margin_target": "≥ 0.70（BP §11 P4 规模化）",
            },
        },
        "assumptions": dict(assumptions),
        "funnel": {
            "demands": len(rows),
            "engine_accepted": len(accepted),
            "scenario_c_manual": sum(
                1 for r in rows if r["outcome"] == "scenario_c_manual"
            ),
            "unfilled": sum(1 for r in rows if r["outcome"] == "unfilled"),
            "delivered": len(delivered),
            "avg_rounds_accepted": (
                round(sum(r["rounds"] for r in accepted) / len(accepted), 2)
                if accepted
                else None
            ),
        },
        "h2": {
            "g9_first_pass_rate": h2_rate,
            "random_assignment_baseline": baseline,
            "first_pass_count": len(first_pass_delivered),
            "delivered_count": len(delivered),
            "gate_pass": bool(h2_rate is not None and h2_rate >= 0.70),
        },
        "h3": {
            "platform_hours_share": h3_worktime,
            "gross_margin": gross_margin,
            "platform_hours_total": round(platform_hours, 1),
            "total_hours_total": round(total_hours, 1),
            "platform_income_total": float(platform_income),
            "platform_cost_total": float(platform_cost),
            "gate_pass": bool(
                h3_worktime is not None
                and h3_worktime <= 0.25
                and gross_margin is not None
                and gross_margin >= 0.70
            ),
        },
        "scenarios": rows,
    }


def main(argv: list[str] | None = None) -> int:
    """CLI：python -m fde_api.dispatch.simulator --scenarios 24 --seed 42
    [--output report.json]——必须指向沙箱库（FDE_DATABASE_URL，
    命名须带 _sim/_test 后缀，防止误写业务库）。"""
    import argparse
    import json
    import os

    parser = argparse.ArgumentParser(
        description="撮合仿真器（历史包回放 + 全链路仿真 → H2/H3 报告）"
    )
    parser.add_argument("--scenarios", type=int, default=24)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--output", default=None, help="JSON 报告输出路径")
    parser.add_argument(
        "--with-replay",
        action="store_true",
        help="仿真后对本次产生的包跑只读回放打分并并入报告",
    )
    args = parser.parse_args(argv)

    database_url = os.environ.get("FDE_DATABASE_URL", "")
    if not database_url.rsplit("/", 1)[-1].split("?")[0].endswith(("_sim", "_test")):
        raise SystemExit(
            "拒绝执行：FDE_DATABASE_URL 必须指向沙箱库（库名以 _sim/_test 结尾）。"
        )
    from fde_api.app import create_app
    from fde_api.extensions import db

    app = create_app()
    with app.app_context():
        session = db.session()
        try:
            report = run_simulation(
                session, scenarios=args.scenarios, seed=args.seed
            )
            if args.with_replay:
                report["replay"] = replay_scoring(session)
        finally:
            session.close()
    payload = json.dumps(report, ensure_ascii=False, indent=2, default=str)
    if args.output:
        with open(args.output, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(payload + "\n")
        summary = {k: report[k] for k in ("meta", "funnel", "h2", "h3")}
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    else:
        print(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
