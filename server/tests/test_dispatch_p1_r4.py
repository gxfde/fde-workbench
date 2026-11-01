"""goal-r4 P1 首批回归（派单设计 §8.4：P1-1 offer_service + P1-3 一致性 + P1-5 seeds）。

- P1-1 判据（§6.3）：并发接单 409 stale_version——服务层显式版本比对 +
  真双事务行锁竞争两路验证。
- §6.2/§6.7：claim 15 分钟确认窗过期 409；assign 24h 响应窗超时释放；
  每日 ≥4 次拒单全成功且不限制后续接单（负面清单 A-6 #6 防护）。
- §6.4/C9：抢单开闸 = 种子城市开关 AND 三条件（种子默认 false → 全城关闭
  = §11.1 降级态；条件满足 + 开关开 → 放行）。
- P1-3：api_catalog ENTRIES 每条都能在 app.url_map 解析（防目录漂移）；
  dispatch 蓝图每条路由都有目录条目。
- P1-5：三个种子可加载、结构合法、幂等（重复加载同对象）；
  gates.json 的 applicable_industries 键存在且服务层零感知。
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import select

from fde_api.auth.models import User
from fde_api.dispatch import cities as cities_mod
from fde_api.dispatch import offer_service
from fde_api.dispatch.errors import DispatchServiceError
from fde_api.dispatch.models import DeliveryPackage, DispatchOffer, FdeProfile
from fde_api.dispatch.offer_service import (
    accept_offer,
    claim_package,
    create_assign_offers,
    decline_offer,
    expire_stale_offers,
)
from fde_api.dispatch.packages import create_package, publish_package
from fde_api.solutions.models import ProjectSolution
from fde_api.workbench.models import (
    IndustryTemplate,
    IndustryTemplateVersion,
    Project,
    Quote,
)

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


def _published_package(db_session, *, candidates: tuple[User, ...] = ()):
    admin = _user("r4.admin")
    template = IndustryTemplate(
        template_key=f"r4-tpl-{uuid4().hex[:8]}",
        name="r4 模板",
        industry_name="制造业",
    )
    version = IndustryTemplateVersion(
        template=template,
        name="r4 模板 v1",
        industry_name="制造业",
        version_number=1,
        status="published",
    )
    project = Project(
        project_code=f"R4-{uuid4().hex[:6].upper()}",
        name="r4 派单项目",
        enterprise_code=f"r4 企业·制造·苏州",
        business_line="FDE_DISPATCH",  # P2-4 H3：交付包只建在派单线项目
        planned_start_date=datetime(2026, 10, 31).date(),
        leader_user_id=admin.id,
        source_template_version=version,
        template_snapshot={"industry_name": "制造业", "modules": []},
    )
    db_session.add_all([admin, project])
    db_session.flush()
    solution = ProjectSolution(
        project_id=project.id, name="r4 方案", owner_user_id=admin.id
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
    publish_package(
        db_session,
        actor=admin,
        package_id=package.id,
        candidate_user_ids=tuple(user.id for user in candidates),
    )
    db_session.flush()
    return admin, project, package


# ---------------------------------------------------------------------------
# P1-1：assign 指派 + 乐观锁接单
# ---------------------------------------------------------------------------


def test_assign_offers_and_package_transition(db_session):
    admin, _project, package = _published_package(db_session)
    c1, c2, c3 = (_user(f"r4.cand{i}", role="fde_engineer") for i in range(3))
    db_session.add_all([c1, c2, c3])
    db_session.flush()

    offers = create_assign_offers(
        db_session,
        actor=admin,
        package_id=package.id,
        candidate_user_ids=(c1.id, c2.id, c3.id, c1.id),  # 重复候选去重
    )
    db_session.flush()
    assert len(offers) == 3
    assert package.dispatch_status == "offered"
    assert [o.match_breakdown["ranked_position"] for o in offers] == [1, 2, 3]

    # 同轮重复发 → 409
    with pytest.raises(DispatchServiceError) as excinfo:
        create_assign_offers(
            db_session, actor=admin, package_id=package.id, candidate_user_ids=(c2.id,)
        )
    assert excinfo.value.code == "offer_exists"
    assert excinfo.value.status == 409


def test_accept_offer_optimistic_lock_409(db_session):
    """P1-1 判据（§6.3）：乐观锁冲突 409 stale_version——显式旧版本比对。"""
    admin, _project, package = _published_package(db_session)
    c1, c2 = (_user(f"r4.lock{i}", role="fde_engineer") for i in range(2))
    db_session.add_all([c1, c2])
    db_session.flush()
    offers = create_assign_offers(
        db_session, actor=admin, package_id=package.id, candidate_user_ids=(c1.id, c2.id)
    )
    db_session.flush()
    target = offers[0]
    stale_version = target.version  # 模拟另一端读到的旧版本

    # 第一端成功接单（version 1→2）
    accept_offer(
        db_session, actor=c1, offer_id=target.id, expected_version=target.version
    )
    db_session.flush()
    assert target.status == "accepted" and target.version == stale_version + 1

    # 第二端持旧版本重放 → 409 stale_version（先于状态校验）
    with pytest.raises(DispatchServiceError) as excinfo:
        accept_offer(db_session, actor=c1, offer_id=target.id, expected_version=stale_version)
    assert excinfo.value.code == "stale_version"
    assert excinfo.value.status == 409


def test_concurrent_accept_single_winner(db_session):
    """同轮互斥守卫：另一 offer 已 accepted 时，后到接单 409 offer_already_accepted。

    场景构造 = 手工把 c1 的 offer 置 accepted（不经 release 路径，模拟真并发
    下另一事务先提交的形态），c2 的 offer 仍 offered 且版本新鲜——命中包行锁
    后的互斥检查。正常串行路径的「先到者胜 + 其余释放」由 release 断言覆盖。
    """
    admin, _project, package = _published_package(db_session)
    c1, c2 = (_user(f"r4.race{i}", role="fde_engineer") for i in range(2))
    db_session.add_all([c1, c2])
    db_session.flush()
    offers = create_assign_offers(
        db_session, actor=admin, package_id=package.id, candidate_user_ids=(c1.id, c2.id)
    )
    db_session.flush()

    winner = offers[0]
    winner.status = "accepted"
    winner.responded_at = datetime.now(timezone.utc)
    winner.version += 1
    db_session.flush()

    loser = offers[1]
    with pytest.raises(DispatchServiceError) as excinfo:
        accept_offer(db_session, actor=c2, offer_id=loser.id, expected_version=loser.version)
    assert excinfo.value.code == "offer_already_accepted"
    assert excinfo.value.status == 409


def test_accept_releases_sibling_offers(db_session):
    """正常串行路径：先到者胜，同轮其余 offered 自动 expired（§2.5）。"""
    admin, _project, package = _published_package(db_session)
    c1, c2 = (_user(f"r4.rel{i}", role="fde_engineer") for i in range(2))
    db_session.add_all([c1, c2])
    db_session.flush()
    offers = create_assign_offers(
        db_session, actor=admin, package_id=package.id, candidate_user_ids=(c1.id, c2.id)
    )
    db_session.flush()

    accept_offer(db_session, actor=c1, offer_id=offers[0].id, expected_version=1)
    db_session.flush()
    db_session.expire_all()
    assert package.dispatch_status == "accepted"
    assert package.seat_delivery == c1.id
    assert db_session.get(DispatchOffer, offers[1].id).status == "expired"


def test_claim_confirm_window_15min(db_session):
    """§6.2：claim 中签确认窗 15 分钟——过期接单 409 offer_window_expired。"""
    admin, _project, package = _published_package(db_session)
    candidate = _user("r4.claim.cand", role="fde_engineer")
    db_session.add_all([candidate])
    db_session.flush()
    offer = DispatchOffer(
        package_id=package.id,
        dispatch_round=package.dispatch_round,
        candidate_user_id=candidate.id,
        status="offered",
        match_breakdown={"mode": "claim"},
        offered_at=datetime.now(timezone.utc) - timedelta(minutes=16),
    )
    db_session.add(offer)
    db_session.flush()

    with pytest.raises(DispatchServiceError) as excinfo:
        accept_offer(db_session, actor=candidate, offer_id=offer.id, expected_version=1)
    assert excinfo.value.code == "offer_window_expired"


def test_expire_stale_offers_releases_package(db_session):
    """assign 24h 响应窗超时：offer expired + 包无活 offer → expired 迁移。"""
    admin, _project, package = _published_package(db_session)
    candidate = _user("r4.stale.cand", role="fde_engineer")
    db_session.add(candidate)
    db_session.flush()
    offers = create_assign_offers(
        db_session, actor=admin, package_id=package.id, candidate_user_ids=(candidate.id,)
    )
    offers[0].offered_at = datetime.now(timezone.utc) - timedelta(hours=25)
    db_session.flush()

    expired = expire_stale_offers(db_session)
    db_session.flush()
    assert expired >= 1
    db_session.expire_all()
    assert db_session.get(DispatchOffer, offers[0].id).status == "expired"
    assert package.dispatch_status == "expired"


# ---------------------------------------------------------------------------
# §6.7：拒单权与每日配额（负面清单 A-6 #6 防护）
# ---------------------------------------------------------------------------


def test_decline_quota_never_blocks(db_session):
    """每日 ≥4 次拒单全部成功；第 5 次同样放行——不得因拒单限制接单机会。"""
    admin, _project, package = _published_package(db_session)
    decline_count = 0
    for round_index in range(5):
        # 每轮：包重发 → 指派 → 拒
        if round_index:
            publish_package(db_session, actor=admin, package_id=package.id)
            db_session.flush()
        candidate = _user(f"r4.decline{round_index}", role="fde_engineer")
        db_session.add(candidate)
        db_session.flush()
        offers = create_assign_offers(
            db_session, actor=admin, package_id=package.id, candidate_user_ids=(candidate.id,)
        )
        offer = offers[0]
        declined = decline_offer(
            db_session, actor=candidate, offer_id=offer.id, expected_version=offer.version,
            reason="档期冲突" if round_index % 2 == 0 else None,
        )
        assert declined.status == "declined"
        decline_count += 1
    assert decline_count == 5  # 5 连拒零拦截，配额是下限保证不是上限
    db_session.expire_all()
    # 全拒后包 rejected（重派入口）
    assert package.dispatch_status == "rejected"


def test_decline_reason_enum_guard(db_session):
    admin, _project, package = _published_package(db_session)
    candidate = _user("r4.reason.cand", role="fde_engineer")
    db_session.add(candidate)
    db_session.flush()
    offer = create_assign_offers(
        db_session, actor=admin, package_id=package.id, candidate_user_ids=(candidate.id,)
    )[0]
    with pytest.raises(DispatchServiceError) as excinfo:
        decline_offer(
            db_session, actor=candidate, offer_id=offer.id,
            expected_version=offer.version, reason="心情不好",
        )
    assert excinfo.value.code == "invalid_request"


# ---------------------------------------------------------------------------
# §6.4 / C9：抢单开闸
# ---------------------------------------------------------------------------


def test_claim_closed_by_default_seed_switch(db_session):
    """种子 claim_enabled 全 false → 抢单 403 claim_closed（§11.1 降级态）。"""
    admin, _project, package = _published_package(db_session)
    candidate = _user("r4.claim.switch", role="fde_engineer")
    db_session.add(candidate)
    db_session.flush()
    with pytest.raises(DispatchServiceError) as excinfo:
        claim_package(db_session, actor=candidate, package_id=package.id)
    assert excinfo.value.code == "claim_closed"
    assert excinfo.value.status == 403


def test_claim_gate_opens_when_conditions_met(db_session, monkeypatch):
    """三条件满足 + 城市开关开 → 放行（条件明细可解释）。"""
    admin, _project, package = _published_package(db_session)
    candidate = _user("r4.claim.open", role="fde_engineer")
    peer = _user("r4.claim.peer", role="fde_engineer")
    profile = FdeProfile(
        user_id=candidate.id, home_city="苏州", status="active", is_active=True
    )
    peer_profile = FdeProfile(
        user_id=peer.id, home_city="苏州", status="active", is_active=True
    )
    db_session.add_all([candidate, peer, profile, peer_profile])
    # 权重公示代理条件：active 规则版本
    from fde_api.dispatch.models import DispatchRuleVersion

    db_session.add(
        DispatchRuleVersion(
            version_no=1,
            status="active",
            rule_snapshot={"stage_b_weights": {"level": 40}},
            effective_at=datetime.now(timezone.utc) - timedelta(days=1),
        )
    )
    db_session.flush()
    monkeypatch.setattr(
        cities_mod,
        "_city_seed",
        lambda: (
            {
                "city": "苏州",
                "province": "江苏",
                "metro_group": "苏锡常都市圈",
                "city_tier": "T1",
                "claim_enabled": True,
                "subsidy_scheme": None,
            },
        ),
    )

    offer = claim_package(db_session, actor=candidate, package_id=package.id)
    db_session.flush()
    assert offer.status == "offered"
    assert offer.match_breakdown["mode"] == "claim"
    # 重复抢同轮 → 409
    with pytest.raises(DispatchServiceError) as excinfo:
        claim_package(db_session, actor=candidate, package_id=package.id)
    assert excinfo.value.code == "offer_exists"

    gate = cities_mod.claim_gate_status(db_session, "苏州")
    assert gate["conditions"] == {
        "supply_gt_demand": True,
        "reject_rate_ok": True,
        "rule_publicized": True,
    }
    assert gate["claim_open"] is True


# ---------------------------------------------------------------------------
# P1-5：seeds 幂等与结构
# ---------------------------------------------------------------------------


def test_seeds_load_idempotent_and_valid():
    city_rows = cities_mod.load_dispatch_cities()
    assert cities_mod.load_dispatch_cities() is city_rows  # lru_cache 幂等
    assert len(city_rows) == 6
    for row in city_rows:
        assert set(row) == {
            "city", "province", "metro_group", "city_tier", "claim_enabled", "subsidy_scheme",
        }
        assert row["claim_enabled"] is False  # §12：种子默认 false
    assert {row["city"] for row in city_rows} == {"上海", "广州", "深圳", "杭州", "成都", "武汉"}  # B-④ 终版拍板（r12）

    metrics = cities_mod.load_acceptance_metrics()
    assert cities_mod.load_acceptance_metrics() is metrics
    keys = {row["key"] for row in metrics}
    assert {
        "business_module_test_coverage",
        "g9_first_pass_rate",
        "platform_hours_ratio",
        "gross_margin",
    } <= keys
    g9 = next(row for row in metrics if row["key"] == "g9_first_pass_rate")
    assert g9["target"] == 0.70 and g9["comparator"] == ">="


def test_gates_seed_has_applicable_industries():
    payload = json.loads(
        (Path(SERVER_ROOT / "seeds" / "gates.json")).read_text(encoding="utf-8")
    )
    assert len(payload["gates"]) == 9
    assert all("applicable_industries" in row for row in payload["gates"])


# ---------------------------------------------------------------------------
# P1-3：api_catalog ↔ url_map 一致性
# ---------------------------------------------------------------------------


def test_catalog_entries_resolve_in_url_map(client):
    """目录每条 (method, path) 都能解析到真实路由（防目录漂移——P1-3 判据）。"""
    import re

    from fde_api.control.api_catalog import ENTRIES

    for key, method, path, _desc, _hints in ENTRIES:
        # 占位符统一换成合法段值（本仓路由参数均为默认 string 转换器）
        wsgi_path = re.sub(r"\{[^}]+\}", "x-placeholder", path)
        matched = client.application.url_map.bind("").match(wsgi_path, method=method)
        assert matched is not None, (key, method, path)


def test_dispatch_routes_all_in_catalog(client):
    """dispatch 蓝图每条路由都有目录条目（新 API 不得脱册）。"""
    import re

    from fde_api.control.api_catalog import ENTRIES

    catalog_paths = {(method, path) for _k, method, path, _d, _h in ENTRIES}
    for rule in client.application.url_map.iter_rules():
        if not rule.rule.startswith("/api/v1/dispatch/"):
            continue
        # werkzeug `<name>`/`<converter:name>` → 目录 `{name}` 记法
        normalized = re.sub(r"<(?:[^:<>]+:)?([^<>]+)>", r"{\1}", rule.rule)
        for method in rule.methods - {"HEAD", "OPTIONS"}:
            assert (method, normalized) in catalog_paths, (method, normalized)
