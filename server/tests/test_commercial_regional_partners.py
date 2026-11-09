"""商业化 G5：区域合作商能力建设（T-12a，任务书 §9；ADR-005 验收钉）。

钉住九件事：

1. **售卖能力默认关闭**（§9 验收①，核心）：迁移播种 ``regional_sale_gate``
   单行 ``closed``；**进入正式区域合作商（对外收费签约的开始）的唯一路径
   ``promote_partner`` 先过 ``require_sale_gate_open``**——闸关 ⇒ 409
   ``regional_sale_gate_closed``；源码扫描钉住「``formal_partner`` 写点唯一
   且在过闸函数内」。
2. **合规条件清单四项**：登记证据（指针+sha256+签署时刻）≠ 开启；缺任一项
   开启 409 ``gate_condition_missing``；四项齐备 + admin+密码 ⇒ 开启成功；
   DB CHECK ``ck_regional_sale_gate_opened_complete`` 结构性排除缺件开门。
3. **四阶段与「暂不启用」标注正确落库**（§9 验收②）：阶段闭集；区域代理
   保留位置、读面派生注记「暂不启用」、任何进入动作 409
   ``regional_agent_not_enabled``。
4. **前两阶段不授予独家区域权**：服务层 409 ``exclusive_not_allowed`` ＋
   DB CHECK ``ck_regional_partners_first_two_stages_no_exclusive`` 双重封死。
5. **城市服务伙伴按项目结算，无固定年费**（§9 验收③）：结算关联引用既有
   G3 科目层 ``project_share`` 行（一单一结，UNIQUE 防重复）；正式档不得写
   按项目结算（409 ``settlement_channel_mismatch``）；档位目录只收 T1/T2/T3。
6. **三档定价以 BP v4.0 为唯一基准**：规则文件机器可读块 ↔ 代码常量 ↔
   迁移种子三方逐位一致。
7. **试运营升级指标与首期金额本期不定数**：哨兵钉——G5 域文件（模型/迁移/
   服务）不出现示例数值 9800／20000（首期/补差），规则槽显式 ``unset``。
8. **高风险写双闸**（admin 门＋密码确认）+ 事件带 request_id 且**无密码**。
9. **结构钉**：治理面不进 api_catalog；读面权限（本人/admin/他人 404/未认证
   401）；证据只存指针+指纹。
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import select

from fde_api.commercial.models import (
    REGIONAL_GATE_CONDITION_KEYS,
    REGIONAL_PARTNER_STAGES,
    REGIONAL_TIER_CODES,
    RegionalPartner,
    RegionalPartnerTier,
    RegionalSaleGate,
)
from fde_api.control.api_catalog import CATALOG

from conftest import INITIAL_PASSWORD
from test_research_subjects_api import (  # noqa: F401  (pytest fixture)
    admin_client,
    authorized_client_factory,
    leader_client,
)

SERVER_ROOT = Path(__file__).resolve().parent.parent
RULE_DOC = (
    SERVER_ROOT.parent
    / "docs"
    / "commercialization"
    / "rules"
    / "regional-partner-program-rules.md"
)

PARTNER_CODE = "g5 伙伴·集成·杭州"


def _pwd() -> str:
    return INITIAL_PASSWORD


def _sha(seed: str) -> str:
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()


def _partners_url() -> str:
    return "/api/v1/commercial/regional-partners"


def _admin_partner_url(partner_id: str, action: str = "") -> str:
    base = f"/api/v1/admin/commercial/regional-partners/{partner_id}"
    return f"{base}/{action}" if action else base


def _gate_url(action: str = "") -> str:
    base = "/api/v1/admin/commercial/regional-sale-gate"
    return f"{base}/{action}" if action else base


def _tiers_url() -> str:
    return "/api/v1/commercial/regional-partner-tiers"


# ---------------------------------------------------------------------------
# 夹具助手
# ---------------------------------------------------------------------------


def _apply(client, partner_code: str = PARTNER_CODE, region: str = "杭州"):
    """申请成为城市观察伙伴（免费；当事人自证）。"""
    response = client.post(
        _partners_url(),
        json={"partner_code": partner_code, "region_name": region},
    )
    assert response.status_code == 200, response.get_data(as_text=True)
    return response.json["data"]["partner"]


def _promote(admin_client, partner_id: str, to_stage: str, **extra):
    payload = {
        "to_stage": to_stage,
        "source_uri": f"fdeops://g5/promotions/{partner_id}-{to_stage}.md",
        "content_hash": _sha(f"promote-{partner_id}-{to_stage}"),
        "confirm_password": _pwd(),
    }
    payload.update(extra)
    return admin_client.post(_admin_partner_url(partner_id, "promote"), json=payload)


def _register_condition(admin_client, key: str):
    return admin_client.post(
        f"{_gate_url('conditions')}/{key}",
        json={
            "source_uri": f"fdeops://g5/compliance/{key}.pdf",
            "content_hash": _sha(f"compliance-{key}"),
            "signed_at": "2026-11-01T00:00:00+00:00",
            "confirm_password": _pwd(),
        },
    )


def _open_gate(admin_client):
    return admin_client.post(_gate_url("open"), json={"confirm_password": _pwd()})


def _gate_opened(admin_client) -> bool:
    response = admin_client.get(_gate_url())
    assert response.status_code == 200
    return response.json["data"]["status"] == "opened"


def _city_service_partner(admin_client, client) -> dict:
    """观察 → 服务伙伴（书面依据；不涉及售卖闸）。"""
    partner = _apply(client)
    response = _promote(admin_client, partner["id"], "city_service")
    assert response.status_code == 200, response.get_data(as_text=True)
    return response.json["data"]["partner"]


def _formal_partner(admin_client, client, tier: str = "T1") -> dict:
    """观察 → 服务 → 正式（**先开闸**）。"""
    partner = _city_service_partner(admin_client, client)
    response = _promote(
        admin_client, partner["id"], "formal_partner", tier_code=tier
    )
    assert response.status_code == 200, response.get_data(as_text=True)
    return response.json["data"]["partner"]


def _project_with_share_entry(db_session, admin_client, leader_user_id: str):
    """交付项目 + G3 ``project_share`` 科目行（复用 G4 夹具形态，不建第二套）。"""
    from datetime import datetime as _dt

    from fde_api.commercial.models import CommercialRevenueLedger
    from fde_api.dispatch.models import DeliveryPackage, DeliverySettlement
    from fde_api.solutions.models import ProjectSolution
    from fde_api.workbench.models import (
        IndustryTemplate,
        IndustryTemplateVersion,
        Project,
    )

    template = IndustryTemplate(
        template_key=f"g5-tpl-{uuid4().hex[:8]}", name="g5 模板", industry_name="制造业"
    )
    version = IndustryTemplateVersion(
        template=template,
        name="g5 模板 v1",
        industry_name="制造业",
        version_number=1,
        status="published",
    )
    project = Project(
        project_code=f"G5-{uuid4().hex[:6].upper()}",
        name="g5 城市服务项目",
        enterprise_code=PARTNER_CODE,
        business_line="FDE_DISPATCH",
        planned_start_date=_dt(2026, 11, 1).date(),
        leader_user_id=leader_user_id,
        source_template_version=version,
        template_snapshot={"industry_name": "制造业", "modules": []},
    )
    db_session.add_all([template, version, project])
    db_session.flush()
    solution = ProjectSolution(
        project_id=project.id, name="g5 方案", schedule="", owner_user_id=leader_user_id
    )
    db_session.add(solution)
    db_session.flush()
    package = DeliveryPackage(
        id=uuid4().hex,
        solution_id=solution.id,
        project_id=project.id,
        package_code=f"PKG-G5-{uuid4().hex[:8].upper()}",
        dispatch_status="published",
        seat_lead=leader_user_id,
    )
    db_session.add(package)
    db_session.flush()
    settlement = DeliverySettlement(
        package_id=package.id,
        settlement_key="G3",
        base_amount=Decimal("8000.00"),
        platform_amount=Decimal("2800.00"),
        region_amount=Decimal("400.00"),
        city_amount=Decimal("1600.00"),
        delivery_amount=Decimal("3200.00"),
        status="draft",
    )
    db_session.add(settlement)
    db_session.commit()

    entry = CommercialRevenueLedger(
        subject_type="project_share",
        line_item="platform_share",
        amount=Decimal("2800.00"),
        recorded_by_user_id=admin_client.user.id,
        delivery_settlement_id=settlement.id,
        delivery_package_id=package.id,
        role_code="R3",
        project_type="delivery",
    )
    db_session.add(entry)
    db_session.commit()
    return project, entry


# ---------------------------------------------------------------------------
# 1. 规则文件 ↔ 代码 ↔ 种子（机器闸）
# ---------------------------------------------------------------------------


def _rule_slots() -> dict:
    text = RULE_DOC.read_text(encoding="utf-8")
    match = re.search(
        r"<!-- regional-rule-slots:begin -->\s*```json\s*(.*?)\s*```",
        text,
        re.DOTALL,
    )
    assert match, "机器可读槽位块缺失"
    return json.loads(match.group(1))


def test_rule_document_slots_match_code_bidirectionally():
    """规则文件机器块 ↔ 代码常量双向相等（阶段/条件/档位）。"""
    slots = _rule_slots()
    assert [s["stage"] for s in slots["stages"]] == list(REGIONAL_PARTNER_STAGES)
    assert [c["key"] for c in slots["gate_conditions"]] == list(
        REGIONAL_GATE_CONDITION_KEYS
    )
    assert [t["tier_code"] for t in slots["tiers"]] == list(REGIONAL_TIER_CODES)
    # 「暂不启用」是区域代理的落库要求（任务书 §9）
    agent = next(s for s in slots["stages"] if s["stage"] == "regional_agent")
    assert agent["enabled"] is False
    assert agent["note"] == "暂不启用"


def test_tier_seed_matches_rule_document(db_session):
    """档位目录（迁移播种＋惰性补建同源）与规则文件逐位一致（BP v4.0 唯一基准）。"""
    from fde_api.commercial.models import REGIONAL_TIER_SEED
    from fde_api.commercial.regional_service import ensure_tier_catalog

    ensure_tier_catalog(db_session)
    rows = list(db_session.scalars(select(RegionalPartnerTier)))
    assert {r.tier_code for r in rows} == {"T1", "T2", "T3"}
    # 代码权威与迁移播种同源（同一常量），与文档块逐位一致
    assert {s["tier_code"] for s in REGIONAL_TIER_SEED} == {"T1", "T2", "T3"}
    by_code = {r.tier_code: r for r in rows}
    doc_tiers = {t["tier_code"]: t for t in _rule_slots()["tiers"]}
    for code, row in by_code.items():
        doc = doc_tiers[code]
        assert Decimal(str(doc["annual_fee_amount"])) == row.annual_fee_amount
        assert doc["included_seats"] == row.included_seats
        assert doc["transfer_quota_seats"] == row.transfer_quota_seats
        assert row.basis_reference.strip()


def test_gate_default_closed_lazy_seeded(db_session):
    """售卖开关缺省 closed（迁移播种；惰性补建恒 closed——**默认关闭**，§9 验收①）。"""
    from fde_api.commercial.regional_service import get_or_create_gate

    gate = get_or_create_gate(db_session)
    assert gate.status == "closed"
    # 补建出来的行同样 closed（幂等）
    assert get_or_create_gate(db_session).status == "closed"


def test_trial_upgrade_metrics_unset():
    """试运营升级指标与首期金额本期不定数：规则槽显式 unset。"""
    metrics = _rule_slots()["trial_upgrade_metrics"]
    assert metrics["status"] == "unset"


def test_trial_example_numbers_absent_from_g5_code():
    """哨兵：原文示例数值（首期 9800／补 20000）不落 G5 域任何代码与迁移。"""
    targets = [
        SERVER_ROOT / "src" / "fde_api" / "commercial" / "regional_service.py",
        SERVER_ROOT / "src" / "fde_api" / "commercial" / "models.py",
        SERVER_ROOT / "migrations"
        / "versions"
        / "b3e8a6c2d4f7_commercial_g5_regional_partners.py",
    ]
    # 档位金额 29800/59800/98000 是合法的 v4.0 目录数据——哨兵只抓**独立出现**的
    # 示例数值（数字边界，避免误伤档位金额的子串）
    patterns = (re.compile(r"(?<![0-9])9800(?![0-9])"), re.compile(r"(?<![0-9])20000(?![0-9])"))
    for path in targets:
        text = path.read_text(encoding="utf-8")
        for pattern in patterns:
            hit = pattern.search(text)
            assert hit is None, f"{path.name} 不应出现示例数值 {pattern.pattern!r}"


# ---------------------------------------------------------------------------
# 2. 售卖开关（默认关闭 → 条件登记 → 开启）
# ---------------------------------------------------------------------------


def test_gate_read_face_default_closed(admin_client):
    response = admin_client.get(_gate_url())
    assert response.status_code == 200
    data = response.json["data"]
    assert data["status"] == "closed"
    assert set(data["conditions"]) == set(REGIONAL_GATE_CONDITION_KEYS)
    assert all(info["registered"] is False for info in data["conditions"].values())


def test_gate_condition_registration_requires_admin_and_password(
    admin_client, leader_client
):
    for key in ("filing",):
        # 非 admin 403
        response = leader_client.post(
            f"{_gate_url('conditions')}/{key}",
            json={
                "source_uri": "fdeops://g5/compliance/x.pdf",
                "content_hash": _sha("x"),
                "signed_at": "2026-11-01T00:00:00+00:00",
                "confirm_password": _pwd(),
            },
        )
        assert response.status_code == 403
        # admin 但密码错 403
        response = admin_client.post(
            f"{_gate_url('conditions')}/{key}",
            json={
                "source_uri": "fdeops://g5/compliance/x.pdf",
                "content_hash": _sha("x"),
                "signed_at": "2026-11-01T00:00:00+00:00",
                "confirm_password": "wrong-password",
            },
        )
        assert response.status_code == 403
        # 缺指纹/缺签署时刻 400
        response = admin_client.post(
            f"{_gate_url('conditions')}/{key}",
            json={"source_uri": "fdeops://g5/x.pdf", "confirm_password": _pwd()},
        )
        assert response.status_code == 400


def test_opening_requires_all_four_conditions(admin_client):
    """缺任一项 ⇒ 409 ``gate_condition_missing``（结构性排除缺件开门）。"""
    # 登记前三项
    for key in ("filing", "disclosure", "cooling_off"):
        response = _register_condition(admin_client, key)
        assert response.status_code == 200
        # **登记 ≠ 开启**：每登记一项，开关仍是 closed
        assert _gate_opened(admin_client) is False
    response = _open_gate(admin_client)
    assert response.status_code == 409
    assert response.json["error"]["code"] == "gate_condition_missing"
    assert "qualification" in response.json["error"]["message"]
    assert _gate_opened(admin_client) is False


def test_gate_opens_after_all_conditions(admin_client):
    """四项齐备 + admin+密码 ⇒ 开启成功（关键流转留痕）。"""
    for key in REGIONAL_GATE_CONDITION_KEYS:
        assert _register_condition(admin_client, key).status_code == 200
    response = _open_gate(admin_client)
    assert response.status_code == 200, response.get_data(as_text=True)
    assert response.json["data"]["gate"]["status"] == "opened"
    assert _gate_opened(admin_client) is True
    # 重复开启 409；开启后条件不可再变更
    assert _open_gate(admin_client).status_code == 409
    response = _register_condition(admin_client, "filing")
    assert response.status_code == 409
    assert response.json["error"]["code"] == "gate_already_opened"


# ---------------------------------------------------------------------------
# 3. 阶段阶梯与「暂不启用」
# ---------------------------------------------------------------------------


def test_apply_city_observer_is_self_service(leader_client):
    """免费申请＝当事人自证（任何认证用户；不走 admin 门）。"""
    partner = _apply(leader_client, partner_code="g5 伙伴·咨询·苏州")
    assert partner["stage"] == "city_observer"
    assert partner["exclusive_territory"] is False


def test_apply_duplicate_partner_code_conflict(leader_client):
    _apply(leader_client)
    response = leader_client.post(
        _partners_url(),
        json={"partner_code": PARTNER_CODE, "region_name": "杭州"},
    )
    assert response.status_code == 409
    assert response.json["error"]["code"] == "partner_already_exists"


def test_regional_agent_is_not_enterable(admin_client, leader_client):
    """区域代理「暂不启用」：任何进入动作 409 ``regional_agent_not_enabled``。"""
    partner = _apply(leader_client)
    response = _promote(admin_client, partner["id"], "regional_agent")
    assert response.status_code == 409
    assert response.json["error"]["code"] == "regional_agent_not_enabled"
    # 读面派生注记可见「暂不启用」语义（阶段闭集保留位置）
    assert "regional_agent" in REGIONAL_PARTNER_STAGES


def test_promotion_requires_evidence_and_admin_password(admin_client, leader_client):
    partner = _apply(leader_client)
    # 非 admin 403
    response = leader_client.post(
        _admin_partner_url(partner["id"], "promote"),
        json={
            "to_stage": "city_service",
            "source_uri": "fdeops://g5/x.md",
            "content_hash": _sha("x"),
            "confirm_password": _pwd(),
        },
    )
    assert response.status_code == 403
    # 缺书面依据 400
    response = admin_client.post(
        _admin_partner_url(partner["id"], "promote"),
        json={"to_stage": "city_service", "confirm_password": _pwd()},
    )
    assert response.status_code == 400
    # 密码错 403
    response = _promote(admin_client, partner["id"], "city_service", confirm_password="nope")
    assert response.status_code == 403


def test_stage_ladder_observer_to_service(admin_client, leader_client):
    """观察 → 服务（书面依据；不涉及售卖闸——按项目结算是内部能力）。"""
    partner = _city_service_partner(admin_client, leader_client)
    assert partner["stage"] == "city_service"
    assert partner["stage_changed_at"] is not None
    assert partner["stage_note"] and "一单一结" in partner["stage_note"]


def test_exclusive_territory_rejected_for_first_two_stages(admin_client, leader_client):
    """前两阶段不授予独家区域权（服务层 409；DB CHECK 另钉）。"""
    partner = _apply(leader_client)
    response = _promote(
        admin_client, partner["id"], "city_service", exclusive_territory=True
    )
    assert response.status_code == 409
    assert response.json["error"]["code"] == "exclusive_not_allowed"


def test_db_check_first_two_stages_no_exclusive(db_session):
    """DB CHECK ``ck_regional_partners_first_two_stages_no_exclusive`` 在位。"""
    from sqlalchemy import inspect as sql_inspect

    checks = {
        c["name"]
        for c in sql_inspect(db_session.bind).get_check_constraints("regional_partners")
    }
    assert "ck_regional_partners_first_two_stages_no_exclusive" in checks
    assert "ck_regional_partners_formal_evidence" in checks


# ---------------------------------------------------------------------------
# 4. 售卖闸 × 正式档（核心验收：无路径可在闸关时收费签约）
# ---------------------------------------------------------------------------


def test_formal_partner_blocked_while_gate_closed(admin_client, leader_client):
    """**§9 验收①**：闸关 ⇒ 进入正式档（收费签约）409 ``regional_sale_gate_closed``。"""
    partner = _city_service_partner(admin_client, leader_client)
    assert _gate_opened(admin_client) is False
    response = _promote(
        admin_client, partner["id"], "formal_partner", tier_code="T1"
    )
    assert response.status_code == 409
    assert response.json["error"]["code"] == "regional_sale_gate_closed"
    # 即便跳级直接从观察档进正式档，同样被闸 + 阶梯双重封死
    fresh = _apply(leader_client, partner_code="g5 伙伴·制造·宁波")
    response = _promote(
        admin_client, fresh["id"], "formal_partner", tier_code="T1"
    )
    assert response.status_code == 409


def test_formal_partner_allowed_after_gate_open(admin_client, leader_client):
    """四项齐备开闸后，正式档进入成功并带档位。"""
    for key in REGIONAL_GATE_CONDITION_KEYS:
        assert _register_condition(admin_client, key).status_code == 200
    assert _open_gate(admin_client).status_code == 200
    partner = _formal_partner(admin_client, leader_client, tier="T2")
    assert partner["stage"] == "formal_partner"
    assert partner["tier_code"] == "T2"
    assert partner["exclusive_territory"] is False


def test_formal_partner_requires_tier(admin_client, leader_client):
    for key in REGIONAL_GATE_CONDITION_KEYS:
        assert _register_condition(admin_client, key).status_code == 200
    assert _open_gate(admin_client).status_code == 200
    partner = _city_service_partner(admin_client, leader_client)
    response = _promote(admin_client, partner["id"], "formal_partner")
    assert response.status_code == 400


def test_no_signing_path_bypasses_gate_source_scan():
    """**结构性钉**：``formal_partner`` 的写点唯一（promote_partner）且在过闸函数内。

    「无任何代码路径可在开关未开启时对外收费签约」的机械化形态：G5 服务层
    源码里把 ``stage`` 赋成 ``formal_partner`` 的位置只有一个；且该函数体内
    先调用 ``require_sale_gate_open``。
    """
    source = (
        SERVER_ROOT / "src" / "fde_api" / "commercial" / "regional_service.py"
    ).read_text(encoding="utf-8")
    writes = [
        m.start()
        for m in re.finditer(r"\.stage\s*=\s*to_stage", source)
    ]
    assert len(writes) == 1, "formal_partner 阶段写点必须唯一"
    gate_call = source.find("require_sale_gate_open(session)")
    assert 0 <= gate_call < writes[0], "写点之前必须先过售卖闸"
    # require_sale_gate_open 是唯一闸门函数：闸关即 409（fail-closed）
    assert "regional_sale_gate_closed" in source


# ---------------------------------------------------------------------------
# 5. 城市服务伙伴按项目结算（一单一结，无固定年费）
# ---------------------------------------------------------------------------


def _settle(admin_client, partner_id: str, project_id: str, entry_id: str, **extra):
    payload = {
        "project_id": project_id,
        "ledger_entry_id": entry_id,
        "confirm_password": _pwd(),
    }
    payload.update(extra)
    return admin_client.post(
        _admin_partner_url(partner_id, "settlements"), json=payload
    )


def test_city_service_per_project_settlement(
    admin_client, leader_client, db_session
):
    """一单一结：引用既有 G3 ``project_share`` 科目行；重复引用被拒。"""
    partner = _city_service_partner(admin_client, leader_client)
    project, entry = _project_with_share_entry(
        db_session, admin_client, leader_client.user.id
    )
    response = _settle(admin_client, partner["id"], project.id, entry.id)
    assert response.status_code == 200, response.get_data(as_text=True)
    assert response.json["data"]["settlement"]["ledger_entry_id"] == entry.id
    # 一单一结：同一科目行至多关联一次
    response = _settle(admin_client, partner["id"], project.id, entry.id)
    assert response.status_code == 409
    assert response.json["error"]["code"] == "ledger_entry_already_settled"


def test_settlement_requires_matching_project(
    admin_client, leader_client, db_session
):
    """科目行归属与结算项目不一致 ⇒ 409（不张冠李戴）。"""
    partner = _city_service_partner(admin_client, leader_client)
    project, entry = _project_with_share_entry(
        db_session, admin_client, leader_client.user.id
    )
    other_project, _ = _project_with_share_entry(
        db_session, admin_client, leader_client.user.id
    )
    response = _settle(admin_client, partner["id"], other_project.id, entry.id)
    assert response.status_code == 409
    assert response.json["error"]["code"] == "ledger_project_mismatch"


def test_settlement_rejected_for_formal_stage(admin_client, leader_client, db_session):
    """正式档不得写按项目结算（两档收费形态互斥）。"""
    for key in REGIONAL_GATE_CONDITION_KEYS:
        assert _register_condition(admin_client, key).status_code == 200
    assert _open_gate(admin_client).status_code == 200
    partner = _formal_partner(admin_client, leader_client)
    project, entry = _project_with_share_entry(
        db_session, admin_client, leader_client.user.id
    )
    response = _settle(admin_client, partner["id"], project.id, entry.id)
    assert response.status_code == 409
    assert response.json["error"]["code"] == "settlement_channel_mismatch"


def test_tier_catalog_has_no_city_service_row(db_session):
    """「不设固定年费」的结构性证据：档位目录只收正式档三行。"""
    from fde_api.commercial.regional_service import list_tiers

    rows = list_tiers(db_session)
    assert {r.tier_code for r in rows} == {"T1", "T2", "T3"}


# ---------------------------------------------------------------------------
# 6. 读面权限与目录可见性
# ---------------------------------------------------------------------------


def test_partner_read_scopes(admin_client, leader_client, authorized_client_factory):
    applicant = authorized_client_factory("fde_engineer")
    partner = _apply(applicant)
    # 本人可见
    response = applicant.get(f"{_partners_url()}/{partner['id']}")
    assert response.status_code == 200
    # admin 全量
    response = admin_client.get(_partners_url())
    assert response.status_code == 200
    ids = [row["id"] for row in response.json["data"]]
    assert partner["id"] in ids
    # 他人 404（不透 existence）
    response = leader_client.get(f"{_partners_url()}/{partner['id']}")
    assert response.status_code == 404
    # 非 admin 列表只见本人（本人的伙伴在列；他人申请的不在列）
    response = applicant.get(_partners_url())
    assert response.status_code == 200
    own_list = [row["id"] for row in response.json["data"]]
    assert partner["id"] in own_list
    response = leader_client.get(_partners_url())
    assert response.status_code == 200
    assert all(row["id"] != partner["id"] for row in response.json["data"])


def test_partner_read_requires_auth(client):
    """未认证 401（裸 client＝未认证会话）。"""
    response = client.get(_partners_url())
    assert response.status_code == 401
    assert client.post(_partners_url(), json={}).status_code == 401


def test_tier_catalog_visible_with_gate_status(admin_client):
    """目录读面带售卖开关状态（目录可见 ≠ 可签约）。"""
    response = admin_client.get(_tiers_url())
    assert response.status_code == 200
    data = response.json["data"]
    assert [t["tier_code"] for t in data["tiers"]] == ["T1", "T2", "T3"]
    assert data["sale_gate_status"] in ("closed", "opened")


# ---------------------------------------------------------------------------
# 7. 事件留痕（密码不落事件）与治理面边界
# ---------------------------------------------------------------------------


def test_gate_events_recorded_without_password(admin_client, db_session):
    from fde_api.workbench.models import OperationEvent

    for key in REGIONAL_GATE_CONDITION_KEYS:
        assert _register_condition(admin_client, key).status_code == 200
    assert _open_gate(admin_client).status_code == 200
    events = list(
        db_session.scalars(
            select(OperationEvent).where(
                OperationEvent.event_type.in_(
                    ["regional_sale_gate_condition_registered", "regional_sale_gate_opened"]
                )
            )
        )
    )
    types = {e.event_type for e in events}
    assert "regional_sale_gate_opened" in types
    assert "regional_sale_gate_condition_registered" in types
    for event in events:
        assert "request_id" in (event.changes or {})
        blob = json.dumps(event.changes, ensure_ascii=False)
        assert INITIAL_PASSWORD not in blob
        assert "confirm_password" not in blob


def test_promotion_event_carries_stage_transition(admin_client, leader_client, db_session):
    from fde_api.workbench.models import OperationEvent

    _city_service_partner(admin_client, leader_client)  # 触发升级留痕
    events = list(
        db_session.scalars(
            select(OperationEvent).where(
                OperationEvent.event_type == "regional_partner_promoted"
            )
        )
    )
    assert events, "升级动作必须留痕"
    changes = events[-1].changes or {}
    assert changes["to_stage"] == "city_service"
    assert changes["from_stage"] == "city_observer"
    assert changes["partner_code"] == PARTNER_CODE


def test_governance_face_not_in_api_catalog():
    """商业治理面（区域伙伴/售卖开关）不进 api_catalog——AI 不可调用。"""
    catalog_names = {row[0] for row in CATALOG}
    for leaked in [name for name in catalog_names if "regional" in name]:
        raise AssertionError(f"治理面泄漏进 api_catalog：{leaked}")


# ---------------------------------------------------------------------------
# 8. 迁移结构钉（additive；四表在位）
# ---------------------------------------------------------------------------


def test_g5_tables_and_constraints_exist(db_session):
    from sqlalchemy import inspect as sql_inspect

    inspector = sql_inspect(db_session.bind)
    tables = set(inspector.get_table_names())
    for table in (
        "regional_partner_tiers",
        "regional_partners",
        "regional_sale_gate",
        "regional_service_settlements",
    ):
        assert table in tables
    gate_checks = {
        c["name"] for c in inspector.get_check_constraints("regional_sale_gate")
    }
    assert "ck_regional_sale_gate_opened_complete" in gate_checks
    assert "ck_regional_sale_gate_condition_atomic" in gate_checks
