"""商业化 G4：商机归属与渠道保护（T-09，任务书 §8；ADR-009 验收钉）。

钉住九件事：

1. **七步链路完整**（报备→企业确认→平台确认归属→保护期→售前→撮合→结算）：
   逐步状态迁移与引用落库，步序不可跳跃。
2. **归属确认后企业自行注册，商机不自动易主**（§8 验收①，**反例**）：企业以
   同一企业代号直签立项后，归属人／归属时刻／保护期状态**逐项不变**；读面派生
   呈现「企业已自助注册」，使反例非空洞。
3. **保护期为空时行为是「未配置」**（§8 验收②）：``unconfigured`` / ``active`` /
   ``expired`` 三态**可区分**，且行为各异（未配置→不封堵、active→直签封堵、
   expired→放行）——**既非永久保护也非立即失效**。
4. **规则文件与代码配置位一一对应**（§8 验收③）：解析成文规则文件的机器可读
   槽位块，与代码常量**双向相等**，并核对配置表每行 unset。
5. **规则未配置 ⇒ 相关动作 fail-closed**（409 ``rule_not_configured``）：续期／
   客户自主选择／争议／归属改派四条。
6. **高风险写双闸**（admin 门＋密码确认）+ 事件带 request_id 且**无密码**。
7. **新增路由权限四态**（本人/admin/他人 403/未认证 401）＋ 报备仅 R2 创业者。
8. **结构钉**：``delivery_settlements`` 零加列；治理面不进 api_catalog；迁移
   additive 往返（downgrade 至**本迁移的父版本**显式 revision）。
9. **复用优先**：撮合引用既有 ``delivery_packages``、结算引用 G3 科目层的
   ``project_share`` 行——不建第二套撮合/结算引擎。
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
from alembic import command
from sqlalchemy import inspect as sql_inspect, select, update

from fde_api.commercial.models import (
    OPPORTUNITY_PROTECTION_STATUSES,
    OPPORTUNITY_RULE_KEYS,
    OPPORTUNITY_RULE_VALUE_KINDS,
    CommercialOpportunity,
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
    / "opportunity-attribution-rules.md"
)

ENTERPRISE_CODE = "g4 企业·制造·广州"


def _pwd() -> str:
    return INITIAL_PASSWORD


def _sha(seed: str) -> str:
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()


def _opp_url(opportunity_id: str = "") -> str:
    base = "/api/v1/commercial/opportunities"
    return f"{base}/{opportunity_id}" if opportunity_id else base


def _admin_opp_url(opportunity_id: str, action: str = "") -> str:
    base = f"/api/v1/admin/commercial/opportunities/{opportunity_id}"
    return f"{base}/{action}" if action else base


def _rules_url() -> str:
    return "/api/v1/admin/commercial/opportunity-rules"


# ---------------------------------------------------------------------------
# 夹具
# ---------------------------------------------------------------------------


def _activate_seat(app, admin_user_id: str, user_id: str) -> None:
    """经服务原语激活席位（admin 动作，bootcamp_practical 源、未设到期）。

    F 线 T3 起报备资格走席位费闸（ADR-011 §5-F），夹具用真实服务路径激活。
    ``app`` 形参接 AuthorizedClient（其 ``.client`` 才是 Flask test client）。

    ★ **M6 注记（2026-11-12）**：本夹具是**测试态激活**——**非商用态**、
    **不触发真实计费**（不经首单扣费闸、不产生科目行、不落金额）；
    它只把 ``commercial_entitlements.seat_status`` 置为 ``active`` 以满足
    报备资格闸，避免用例为「造一个 active 席位」而新增激活路径。
    此处**不与** §17-1「有真实外部交付者前不激活」的商用态纪律打架：
    后者约束的是**商用态的席位激活与计费**，本夹具只服务于测试断言。"""
    from fde_api.auth.models import User as UserModel
    from fde_api.commercial.service import activate_seat
    from fde_api.extensions import db

    with app.client.application.app_context():
        session = db.session()
        admin = session.get(UserModel, admin_user_id)
        assert admin is not None
        activate_seat(
            session,
            actor=admin,
            user_id=user_id,
            seat_source="bootcamp_practical",
            expires_at="2027-12-31T00:00:00Z",
            confirm_password=INITIAL_PASSWORD,
        )
        session.commit()


def _layer_as_r2(admin_client, client) -> str:
    """把用户分层为 R2 **并激活席位**——F 线 T3 起报备资格走席位费闸
    （ADR-011 §5-F 补充拍板 12：资格不限角色，缴 3980 即可）。"""
    response = admin_client.post(
        f"/api/v1/admin/commercial/users/{client.user.id}/role",
        json={"role": "R2", "confirm_password": _pwd()},
    )
    assert response.status_code == 200, response.get_data(as_text=True)
    _activate_seat(admin_client, admin_client.user.id, client.user.id)
    return client.user.id


def _report(client, enterprise_code: str = ENTERPRISE_CODE, title: str = "g4 商机线索"):
    response = client.post(
        _opp_url(),
        json={
            "enterprise_code": enterprise_code,
            "title": title,
            "source_uri": f"fdeops://g4/leads/{uuid4().hex[:8]}.md",
            "content_hash": _sha(f"lead-{uuid4().hex}"),
        },
    )
    assert response.status_code == 200, response.get_data(as_text=True)
    return response.json["data"]["opportunity"]


def _enterprise_confirm(admin_client, opportunity_id: str):
    return admin_client.post(
        _admin_opp_url(opportunity_id, "enterprise-confirm"),
        json={
            "confirmation_uri": f"fdeops://g4/confirmations/{opportunity_id}.pdf",
            "confirmation_hash": _sha(f"confirm-{opportunity_id}"),
            "confirm_password": _pwd(),
        },
    )


def _confirm_attribution(admin_client, opportunity_id: str, owner_user_id: str):
    return admin_client.post(
        _admin_opp_url(opportunity_id, "attribution"),
        json={
            "owner_user_id": owner_user_id,
            "attribution_uri": f"fdeops://g4/attribution/{opportunity_id}.pdf",
            "attribution_hash": _sha(f"attribution-{opportunity_id}"),
            "confirm_password": _pwd(),
        },
    )


def _configure_rule(admin_client, key: str, value):
    return admin_client.post(
        f"{_rules_url()}/{key}",
        json={
            "value": value,
            "source_uri": f"fdeops://g4/rules/{key}.md",
            "content_hash": _sha(f"rule-{key}-{uuid4().hex[:6]}"),
            "confirm_password": _pwd(),
        },
    )


def _delivery_package(
    db_session, leader_user_id: str, enterprise_code: str = ENTERPRISE_CODE
):
    """同企业代号下的交付包 + 分账行（复用既有 dispatch 结构，不建第二套）。"""
    from fde_api.dispatch.models import DeliveryPackage, DeliverySettlement
    from fde_api.solutions.models import ProjectSolution
    from fde_api.workbench.models import (
        IndustryTemplate,
        IndustryTemplateVersion,
        Project,
    )

    template = IndustryTemplate(
        template_key=f"g4-tpl-{uuid4().hex[:8]}", name="g4 模板", industry_name="制造业"
    )
    version = IndustryTemplateVersion(
        template=template,
        name="g4 模板 v1",
        industry_name="制造业",
        version_number=1,
        status="published",
    )
    project = Project(
        project_code=f"G4-{uuid4().hex[:6].upper()}",
        name="g4 交付项目",
        enterprise_code=enterprise_code,
        business_line="FDE_DISPATCH",
        planned_start_date=datetime(2026, 10, 31).date(),
        leader_user_id=leader_user_id,
        source_template_version=version,
        template_snapshot={"industry_name": "制造业", "modules": []},
    )
    db_session.add_all([template, version, project])
    db_session.flush()
    solution = ProjectSolution(
        project_id=project.id, name="g4 方案", schedule="", owner_user_id=leader_user_id
    )
    db_session.add(solution)
    db_session.flush()
    package = DeliveryPackage(
        id=uuid4().hex,
        solution_id=solution.id,
        project_id=project.id,
        package_code=f"PKG-G4-{uuid4().hex[:8].upper()}",
        dispatch_status="published",
        seat_lead=leader_user_id,
    )
    db_session.add(package)
    db_session.flush()
    settlement = DeliverySettlement(
        package_id=package.id,
        settlement_key="G3",
        base_amount=Decimal("10000.00"),
        platform_amount=Decimal("3500.00"),
        region_amount=Decimal("500.00"),
        city_amount=Decimal("2000.00"),
        delivery_amount=Decimal("4000.00"),
        status="draft",
    )
    db_session.add(settlement)
    db_session.commit()
    return project, package, settlement


def _project_share_entry(admin_client, package, settlement):
    """G3 科目层的项目分成行（引用既有分账结果）。"""
    response = admin_client.post(
        "/api/v1/admin/commercial/revenue-ledger",
        json={
            "subject_type": "project_share",
            "line_item": "platform_share",
            "delivery_settlement_id": settlement.id,
            "delivery_package_id": package.id,
            "role_code": "R3",
            "project_type": "delivery",
            "confirm_password": _pwd(),
        },
    )
    assert response.status_code == 200, response.get_data(as_text=True)
    return response.json["data"]["entry"]


def _create_direct_project(
    admin_client, leader_client, db_session, enterprise_code: str = ENTERPRISE_CODE
):
    """企业**直签立项**（business_line 缺省＝FDE）——「企业自行注册」的真实路径。"""
    from fde_api.workbench.seed import seed_workbench

    seed_workbench(db_session)
    db_session.commit()
    return admin_client.post(
        "/api/v1/projects",
        json={
            "name": "企业自行注册的项目",
            "enterprise_code": enterprise_code,
            "planned_start_date": "2026-11-01",
            "leader_user_id": leader_client.user.id,
            "creation_source": "manual",
            "module_keys": ["pre_diagnosis"],
            "project_snapshot": {
                "industry_name": "通用",
                "description": "企业自行注册",
                "modules": [
                    {
                        "module_key": "pre_diagnosis",
                        "name": "预诊断",
                        "description": "确认范围",
                        "tasks": [
                            {
                                "task_key": "manual_scope",
                                "name": "确认项目范围",
                                "description": "整理输入和验收口径",
                                "duration_days": 2,
                                "default_assignee_role": "project_lead",
                                "dependency_keys": [],
                                "sort_order": 0,
                            }
                        ],
                    }
                ],
            },
        },
    )


# ---------------------------------------------------------------------------
# 1. 规则文件 ↔ 代码配置位一一对应（§8 验收③）
# ---------------------------------------------------------------------------


def test_rule_document_slots_match_code_bidirectionally(db_session) -> None:
    """成文规则文件的机器可读槽位块 ↔ 代码常量**双向相等**（验收③）。"""
    body = RULE_DOC.read_text(encoding="utf-8")
    begin = body.index("<!-- rule-slots:begin -->")
    end = body.index("<!-- rule-slots:end -->")
    block = body[begin:end]
    match = re.search(r"```json\s*(\{.*?\})\s*```", block, flags=re.DOTALL)
    assert match is not None, "规则文件缺少 ```json 机器可读槽位代码块"
    payload = json.loads(match.group(1))
    doc_slots = payload["slots"]
    doc_keys = [slot["key"] for slot in doc_slots]

    assert set(doc_keys) == set(OPPORTUNITY_RULE_KEYS), "规则文件与代码配置位集合不等"
    assert len(doc_keys) == len(set(doc_keys)), "规则文件槽位有重复"
    for slot in doc_slots:
        assert slot["value_kind"] == OPPORTUNITY_RULE_VALUE_KINDS[slot["key"]]
        assert slot["default_status"] == "unset"

    from fde_api.commercial.attribution_service import ensure_rule

    for key in OPPORTUNITY_RULE_KEYS:
        row = ensure_rule(db_session, key)
        assert row.status == "unset", key
        assert row.days is None, key
        assert row.criteria is None, key
        assert row.value_kind == OPPORTUNITY_RULE_VALUE_KINDS[key], key


def test_rule_slots_are_unset_by_default(admin_client) -> None:
    """本期五个规则位**全部 unset**（规则数值未定数）。"""
    response = admin_client.get(_rules_url())
    assert response.status_code == 200, response.get_data(as_text=True)
    rules = {row["key"]: row for row in response.json["data"]["rules"]}
    assert set(rules) == set(OPPORTUNITY_RULE_KEYS)
    for key, row in rules.items():
        assert row["status"] == "unset", key
        assert row["configured"] is False, key
        assert row["days"] is None, key
        assert row["criteria"] is None, key


# ---------------------------------------------------------------------------
# 2. 七步链路完整
# ---------------------------------------------------------------------------


def test_seven_step_chain_completes(
    admin_client, authorized_client_factory, db_session
) -> None:
    """七步链路逐步落库（状态迁移 + 引用），结算引用 G3 科目层。"""
    founder_client = authorized_client_factory("fde_engineer")
    founder_id = _layer_as_r2(admin_client, founder_client)

    opportunity = _report(founder_client)
    opportunity_id = opportunity["id"]
    assert opportunity["status"] == "submitted"
    assert opportunity["protection"]["status"] == "unconfigured"

    confirmed = _enterprise_confirm(admin_client, opportunity_id)
    assert confirmed.status_code == 200, confirmed.get_data(as_text=True)
    assert confirmed.json["data"]["opportunity"]["status"] == "enterprise_confirmed"

    attributed = _confirm_attribution(admin_client, opportunity_id, founder_id)
    assert attributed.status_code == 200, attributed.get_data(as_text=True)
    body = attributed.json["data"]["opportunity"]
    assert body["status"] == "attribution_confirmed"
    assert body["attribution"]["owner_user_id"] == founder_id

    # ④ 保护期：规则位未配置 ⇒ 不可设定（先配置）
    blocked = admin_client.post(
        _admin_opp_url(opportunity_id, "protection"), json={"confirm_password": _pwd()}
    )
    assert blocked.status_code == 409, blocked.get_data(as_text=True)
    assert blocked.json["error"]["code"] == "rule_not_configured"

    configured = _configure_rule(admin_client, "protection_period_days", 30)
    assert configured.status_code == 200, configured.get_data(as_text=True)
    protected = admin_client.post(
        _admin_opp_url(opportunity_id, "protection"), json={"confirm_password": _pwd()}
    )
    assert protected.status_code == 200, protected.get_data(as_text=True)
    body = protected.json["data"]["opportunity"]
    assert body["protection"]["status"] == "active"
    assert body["protection"]["effective_status"] == "active"
    assert body["protection"]["days_remaining"] == 30

    # ⑤ 售前与客户关系（默认＝归属人）
    presales = admin_client.post(
        _admin_opp_url(opportunity_id, "presales"), json={"confirm_password": _pwd()}
    )
    assert presales.status_code == 200, presales.get_data(as_text=True)
    body = presales.json["data"]["opportunity"]
    assert body["status"] == "presales"
    assert body["presales_owner_user_id"] == founder_id

    # ⑥ 撮合交付者（引用既有 dispatch 交付包）
    _project, package, settlement = _delivery_package(db_session, founder_id)
    matched = admin_client.post(
        _admin_opp_url(opportunity_id, "match"),
        json={"delivery_package_id": package.id, "confirm_password": _pwd()},
    )
    assert matched.status_code == 200, matched.get_data(as_text=True)
    body = matched.json["data"]["opportunity"]
    assert body["status"] == "matched"
    assert body["matched_delivery_package_id"] == package.id

    # ⑦ 按既定分成规则结算（引用 G3 科目层的 project_share 行）
    entry = _project_share_entry(admin_client, package, settlement)
    settled = admin_client.post(
        _admin_opp_url(opportunity_id, "settlement"),
        json={"ledger_entry_id": entry["id"], "confirm_password": _pwd()},
    )
    assert settled.status_code == 200, settled.get_data(as_text=True)
    body = settled.json["data"]["opportunity"]
    assert body["status"] == "settled"
    assert body["settled_ledger_entry_id"] == entry["id"]


def test_step_order_is_enforced(
    admin_client, authorized_client_factory, db_session
) -> None:
    """步序不可跳跃：未企业确认不可确认归属；未售前不可撮合；未撮合不可结算。"""
    founder_client = authorized_client_factory("fde_engineer")
    founder_id = _layer_as_r2(admin_client, founder_client)
    opportunity_id = _report(founder_client)["id"]

    early_attribution = _confirm_attribution(admin_client, opportunity_id, founder_id)
    assert early_attribution.status_code == 409
    assert early_attribution.json["error"]["code"] == "invalid_opportunity_state"

    _enterprise_confirm(admin_client, opportunity_id)
    _confirm_attribution(admin_client, opportunity_id, founder_id)

    _project, package, settlement = _delivery_package(db_session, founder_id)
    early_match = admin_client.post(
        _admin_opp_url(opportunity_id, "match"),
        json={"delivery_package_id": package.id, "confirm_password": _pwd()},
    )
    assert early_match.status_code == 409
    assert early_match.json["error"]["code"] == "invalid_opportunity_state"

    entry = _project_share_entry(admin_client, package, settlement)
    early_settle = admin_client.post(
        _admin_opp_url(opportunity_id, "settlement"),
        json={"ledger_entry_id": entry["id"], "confirm_password": _pwd()},
    )
    assert early_settle.status_code == 409
    assert early_settle.json["error"]["code"] == "invalid_opportunity_state"


def test_attribution_cannot_be_silently_overwritten(
    admin_client, authorized_client_factory
) -> None:
    """归属已确认 ⇒ 再次确认**不得静默改写**（409 ``attribution_already_confirmed``）。"""
    founder_client = authorized_client_factory("fde_engineer")
    founder_id = _layer_as_r2(admin_client, founder_client)
    other = authorized_client_factory("fde_engineer")
    opportunity_id = _report(founder_client)["id"]
    _enterprise_confirm(admin_client, opportunity_id)
    _confirm_attribution(admin_client, opportunity_id, founder_id)

    again = _confirm_attribution(admin_client, opportunity_id, other.user.id)
    assert again.status_code == 409, again.get_data(as_text=True)
    assert again.json["error"]["code"] == "attribution_already_confirmed"

    current = admin_client.get(_opp_url(opportunity_id)).json["data"]["opportunity"]
    assert current["attribution"]["owner_user_id"] == founder_id


def test_settlement_requires_project_share_entry(
    admin_client, authorized_client_factory, db_session
) -> None:
    """结算必须引用**项目分成**科目行（非分成科目／已作废行一律拒绝）。"""
    founder_client = authorized_client_factory("fde_engineer")
    founder_id = _layer_as_r2(admin_client, founder_client)
    opportunity_id = _report(founder_client)["id"]
    _enterprise_confirm(admin_client, opportunity_id)
    _confirm_attribution(admin_client, opportunity_id, founder_id)
    admin_client.post(
        _admin_opp_url(opportunity_id, "presales"), json={"confirm_password": _pwd()}
    )
    _project, package, settlement = _delivery_package(db_session, founder_id)
    admin_client.post(
        _admin_opp_url(opportunity_id, "match"),
        json={"delivery_package_id": package.id, "confirm_password": _pwd()},
    )

    # 非分成科目（培训费）不得用于结算
    training = admin_client.post(
        f"/api/v1/admin/commercial/users/{founder_id}/training",
        json={"item_type": "training", "confirm_password": _pwd()},
    )
    training_id = training.json["data"]["training"]["id"]
    training_fee = admin_client.post(
        "/api/v1/admin/commercial/revenue-ledger",
        json={
            "subject_type": "training_fee",
            "line_item": "software_service_fee",
            "subject_user_id": founder_id,
            "training_entitlement_id": training_id,
            "amount": 100,
            "source_uri": "fdeops://g4/fee.pdf",
            "content_hash": _sha("fee"),
            "confirm_password": _pwd(),
        },
    )
    assert training_fee.status_code == 200, training_fee.get_data(as_text=True)
    wrong = admin_client.post(
        _admin_opp_url(opportunity_id, "settlement"),
        json={
            "ledger_entry_id": training_fee.json["data"]["entry"]["id"],
            "confirm_password": _pwd(),
        },
    )
    assert wrong.status_code == 409, wrong.get_data(as_text=True)
    assert wrong.json["error"]["code"] == "ledger_subject_mismatch"


def test_match_requires_same_enterprise_package(
    admin_client, authorized_client_factory, db_session
) -> None:
    """撮合的交付包必须挂在**同一企业代号**的项目上（不得张冠李戴）。"""
    founder_client = authorized_client_factory("fde_engineer")
    founder_id = _layer_as_r2(admin_client, founder_client)
    opportunity_id = _report(founder_client)["id"]
    _enterprise_confirm(admin_client, opportunity_id)
    _confirm_attribution(admin_client, opportunity_id, founder_id)
    admin_client.post(
        _admin_opp_url(opportunity_id, "presales"), json={"confirm_password": _pwd()}
    )

    _project, other_package, _settlement = _delivery_package(
        db_session, founder_id, enterprise_code="别的 企业·制造·深圳"
    )
    mismatch = admin_client.post(
        _admin_opp_url(opportunity_id, "match"),
        json={"delivery_package_id": other_package.id, "confirm_password": _pwd()},
    )
    assert mismatch.status_code == 409, mismatch.get_data(as_text=True)
    assert mismatch.json["error"]["code"] == "package_enterprise_mismatch"


# ---------------------------------------------------------------------------
# 3. 归属不因企业自行注册而转移（§8 验收①，反例）
# ---------------------------------------------------------------------------


def test_attribution_not_transferred_when_enterprise_registers_directly(
    admin_client, leader_client, authorized_client_factory, db_session
) -> None:
    """**反例**：归属确认后企业以同一企业代号直签立项 ⇒ 商机归属**逐项不变**。

    归属与保护期是本域事实，企业侧立项路径**没有任何写路径**可触碰商机行。
    """
    founder_client = authorized_client_factory("fde_engineer")
    founder_id = _layer_as_r2(admin_client, founder_client)
    opportunity_id = _report(founder_client)["id"]
    _enterprise_confirm(admin_client, opportunity_id)
    _confirm_attribution(admin_client, opportunity_id, founder_id)

    # 保护期**未配置**（本期数值未定数）⇒ 企业可以自行直签注册；
    # 正因为不被封堵，注册后的归属才必须**逐项不变**——这才是「不自动易主」。
    before = admin_client.get(_opp_url(opportunity_id)).json["data"]["opportunity"]
    assert before["attribution"]["owner_user_id"] == founder_id
    assert before["protection"]["status"] == "unconfigured"
    assert before["enterprise_registered"] is False

    # 企业自行注册（直签立项）——**归属不得易主**
    created = _create_direct_project(admin_client, leader_client, db_session)
    assert created.status_code == 201, created.get_data(as_text=True)

    after = admin_client.get(_opp_url(opportunity_id)).json["data"]["opportunity"]
    assert after["attribution"]["owner_user_id"] == founder_id
    assert after["attribution"]["confirmed_at"] == before["attribution"]["confirmed_at"]
    assert after["status"] == before["status"]
    assert after["protection"]["status"] == before["protection"]["status"]
    assert after["protection"]["expires_at"] == before["protection"]["expires_at"]
    # 派生事实：企业确已自助注册（反例**非空洞**）
    assert after["enterprise_registered"] is True


# ---------------------------------------------------------------------------
# 4. 保护期三态可区分（§8 验收②）
# ---------------------------------------------------------------------------


def test_protection_three_states_are_distinguishable(
    admin_client, leader_client, authorized_client_factory, db_session
) -> None:
    """``unconfigured`` / ``active`` / ``expired`` 三态可区分且行为各异。"""
    founder_client = authorized_client_factory("fde_engineer")
    founder_id = _layer_as_r2(admin_client, founder_client)
    opportunity_id = _report(founder_client)["id"]
    _enterprise_confirm(admin_client, opportunity_id)
    _confirm_attribution(admin_client, opportunity_id, founder_id)

    # ① 未配置：既非永久保护，也非立即失效——保护期不生效，直签不被封堵
    unconfigured = admin_client.get(_opp_url(opportunity_id)).json["data"]["opportunity"]
    assert unconfigured["protection"]["status"] == "unconfigured"
    assert unconfigured["protection"]["effective_status"] == "unconfigured"
    assert unconfigured["protection"]["expires_at"] is None
    _assert_direct_project_allowed(
        admin_client, leader_client, db_session, "g4 未配置企业·制造·广州"
    )

    # ② 配置后：active（必有到期时刻）
    _configure_rule(admin_client, "protection_period_days", 30)
    protected = admin_client.post(
        _admin_opp_url(opportunity_id, "protection"), json={"confirm_password": _pwd()}
    )
    assert protected.status_code == 200
    body = protected.json["data"]["opportunity"]
    assert body["protection"]["status"] == "active"
    assert body["protection"]["effective_status"] == "active"
    assert body["protection"]["expires_at"] is not None

    # ③ 过期：派生 expired（到期即放行——不得永久锁定企业）
    #   注：起止时刻一并回拨（库层 CHECK 要求 expires_at > started_at——保护窗口
    #   必须形状完好，只是已过到期时刻）。
    db_session.execute(
        update(CommercialOpportunity)
        .where(CommercialOpportunity.id == opportunity_id)
        .values(
            protection_started_at=datetime.now(timezone.utc) - timedelta(days=40),
            protection_expires_at=datetime.now(timezone.utc) - timedelta(days=10),
        )
    )
    db_session.commit()
    expired = admin_client.get(_opp_url(opportunity_id)).json["data"]["opportunity"]
    assert expired["protection"]["status"] == "active"
    assert expired["protection"]["effective_status"] == "expired"
    _assert_direct_project_allowed(
        admin_client, leader_client, db_session, "g4 过期企业·制造·广州"
    )


def test_active_protection_blocks_direct_project_creation(
    admin_client, leader_client, authorized_client_factory, db_session
) -> None:
    """保护期内该企业**直签立项被封堵**（422 opportunity_protection_active）。"""
    founder_client = authorized_client_factory("fde_engineer")
    founder_id = _layer_as_r2(admin_client, founder_client)
    opportunity_id = _report(founder_client)["id"]
    _enterprise_confirm(admin_client, opportunity_id)
    _confirm_attribution(admin_client, opportunity_id, founder_id)
    _configure_rule(admin_client, "protection_period_days", 30)
    admin_client.post(
        _admin_opp_url(opportunity_id, "protection"), json={"confirm_password": _pwd()}
    )

    blocked = _create_direct_project(admin_client, leader_client, db_session)
    assert blocked.status_code == 422, blocked.get_data(as_text=True)
    assert blocked.json["error"]["code"] == "opportunity_protection_active"


def _assert_direct_project_allowed(
    admin_client, leader_client, db_session, enterprise_code: str
) -> None:
    response = _create_direct_project(admin_client, leader_client, db_session, enterprise_code)
    assert response.status_code == 201, response.get_data(as_text=True)


# ---------------------------------------------------------------------------
# 5. 规则未配置 ⇒ fail-closed
# ---------------------------------------------------------------------------


def test_actions_gated_by_unconfigured_rules(
    admin_client, authorized_client_factory, db_session
) -> None:
    """续期／客户自主选择／争议／归属改派：规则未配置 ⇒ 409 ``rule_not_configured``。"""
    founder_client = authorized_client_factory("fde_engineer")
    founder_id = _layer_as_r2(admin_client, founder_client)
    opportunity_id = _report(founder_client)["id"]
    _enterprise_confirm(admin_client, opportunity_id)
    _confirm_attribution(admin_client, opportunity_id, founder_id)
    _configure_rule(admin_client, "protection_period_days", 30)
    admin_client.post(
        _admin_opp_url(opportunity_id, "protection"), json={"confirm_password": _pwd()}
    )
    admin_client.post(
        _admin_opp_url(opportunity_id, "presales"), json={"confirm_password": _pwd()}
    )
    _project, package, _settlement = _delivery_package(db_session, founder_id)

    renew = admin_client.post(
        _admin_opp_url(opportunity_id, "protection/renew"),
        json={"confirm_password": _pwd()},
    )
    assert renew.status_code == 409
    assert renew.json["error"]["code"] == "rule_not_configured"

    choice = admin_client.post(
        _admin_opp_url(opportunity_id, "customer-choice"),
        json={"delivery_package_id": package.id, "confirm_password": _pwd()},
    )
    assert choice.status_code == 409
    assert choice.json["error"]["code"] == "rule_not_configured"

    dispute = admin_client.post(
        _admin_opp_url(opportunity_id, "dispute"),
        json={
            "dispute_uri": "fdeops://g4/dispute/x.pdf",
            "dispute_hash": _sha("dispute"),
            "confirm_password": _pwd(),
        },
    )
    assert dispute.status_code == 409
    assert dispute.json["error"]["code"] == "rule_not_configured"

    reassign = admin_client.post(
        _admin_opp_url(opportunity_id, "attribution/reassign"),
        json={
            "owner_user_id": founder_id,
            "reason_uri": "fdeops://g4/reassign/x.pdf",
            "reason_hash": _sha("reassign"),
            "confirm_password": _pwd(),
        },
    )
    assert reassign.status_code == 409
    assert reassign.json["error"]["code"] == "rule_not_configured"


def test_actions_enabled_after_rules_configured(
    admin_client, authorized_client_factory, db_session
) -> None:
    """规则配置后相关动作可用；**客户自主选择不改归属**。"""
    founder_client = authorized_client_factory("fde_engineer")
    founder_id = _layer_as_r2(admin_client, founder_client)
    opportunity_id = _report(founder_client)["id"]
    _enterprise_confirm(admin_client, opportunity_id)
    _confirm_attribution(admin_client, opportunity_id, founder_id)
    admin_client.post(
        _admin_opp_url(opportunity_id, "presales"), json={"confirm_password": _pwd()}
    )
    _project, package, _settlement = _delivery_package(db_session, founder_id)

    _configure_rule(admin_client, "customer_choice", "客户可在撮合候选中自主指定交付者")
    _configure_rule(admin_client, "renewal_conditions", "客户关系延续且无违约时可续期")
    _configure_rule(admin_client, "protection_period_days", 30)
    _configure_rule(admin_client, "attribution_criteria", "按报备顺序与履约记录判定归属")

    choice = admin_client.post(
        _admin_opp_url(opportunity_id, "customer-choice"),
        json={"delivery_package_id": package.id, "confirm_password": _pwd()},
    )
    assert choice.status_code == 200, choice.get_data(as_text=True)
    body = choice.json["data"]["opportunity"]
    assert body["customer_choice_package_id"] == package.id
    assert body["attribution"]["owner_user_id"] == founder_id, "客户自主选择不得改归属"

    protected = admin_client.post(
        _admin_opp_url(opportunity_id, "protection"), json={"confirm_password": _pwd()}
    )
    assert protected.status_code == 200
    renew = admin_client.post(
        _admin_opp_url(opportunity_id, "protection/renew"),
        json={"confirm_password": _pwd()},
    )
    assert renew.status_code == 200, renew.get_data(as_text=True)
    assert renew.json["data"]["opportunity"]["protection"]["renewal_count"] == 1

    reassign = admin_client.post(
        _admin_opp_url(opportunity_id, "attribution/reassign"),
        json={
            "owner_user_id": founder_id,
            "reason_uri": "fdeops://g4/reassign/x.pdf",
            "reason_hash": _sha("reassign"),
            "confirm_password": _pwd(),
        },
    )
    assert reassign.status_code == 200, reassign.get_data(as_text=True)


def test_dispute_freezes_downstream_steps(
    admin_client, authorized_client_factory, db_session
) -> None:
    """争议期间链路冻结：撮合拒绝（409 ``opportunity_disputed``）。"""
    founder_client = authorized_client_factory("fde_engineer")
    founder_id = _layer_as_r2(admin_client, founder_client)
    opportunity_id = _report(founder_client)["id"]
    _enterprise_confirm(admin_client, opportunity_id)
    _confirm_attribution(admin_client, opportunity_id, founder_id)
    admin_client.post(
        _admin_opp_url(opportunity_id, "presales"), json={"confirm_password": _pwd()}
    )
    _configure_rule(admin_client, "dispute_handling", "争议由平台运营与双方协商处理")
    disputed = admin_client.post(
        _admin_opp_url(opportunity_id, "dispute"),
        json={
            "dispute_uri": "fdeops://g4/dispute/x.pdf",
            "dispute_hash": _sha("dispute"),
            "confirm_password": _pwd(),
        },
    )
    assert disputed.status_code == 200, disputed.get_data(as_text=True)
    assert disputed.json["data"]["opportunity"]["status"] == "disputed"

    _project, package, _settlement = _delivery_package(db_session, founder_id)
    blocked = admin_client.post(
        _admin_opp_url(opportunity_id, "match"),
        json={"delivery_package_id": package.id, "confirm_password": _pwd()},
    )
    assert blocked.status_code == 409, blocked.get_data(as_text=True)
    assert blocked.json["error"]["code"] == "opportunity_disputed"


# ---------------------------------------------------------------------------
# 6. 权限与高风险写闸
# ---------------------------------------------------------------------------


def test_report_requires_paid_seat_not_role(admin_client, authorized_client_factory) -> None:
    """报备资格＝席位费已缴闸（ADR-011 §5-F 补充拍板 12，F 线 T3）。

    资格**不限角色**：R2 角色本身不算资格（角色在、席位缺 ⇒ 仍 403）；
    未分层用户席位 active ⇒ 放行。"""
    denied = authorized_client_factory("fde_engineer").post(
        _opp_url(),
        json={
            "enterprise_code": ENTERPRISE_CODE,
            "title": "无角色无席位报备",
            "source_uri": "fdeops://g4/leads/x.md",
            "content_hash": _sha("no-role"),
        },
    )
    assert denied.status_code == 403, denied.get_data(as_text=True)
    assert denied.json["error"]["code"] == "opportunity_reporter_seat_required"

    # 角色在、席位缺：R2 分层不构成报备资格
    role_only = authorized_client_factory("fde_engineer")
    role_only_id = role_only.user.id
    role_only_post = admin_client.post(
        f"/api/v1/admin/commercial/users/{role_only_id}/role",
        json={"role": "R2", "confirm_password": _pwd()},
    )
    assert role_only_post.status_code == 200, role_only_post.get_data(as_text=True)
    denied_role_only = role_only.post(
        _opp_url(),
        json={
            "enterprise_code": ENTERPRISE_CODE,
            "title": "R2 角色未缴席位",
            "source_uri": "fdeops://g4/leads/role-only.md",
            "content_hash": _sha("role-only"),
        },
    )
    assert denied_role_only.status_code == 403
    assert denied_role_only.json["error"]["code"] == "opportunity_reporter_seat_required"

    # 未分层 + 席位 active ⇒ 资格不限角色，放行
    deliverer = authorized_client_factory("fde_engineer")
    _activate_seat(admin_client, admin_client.user.id, deliverer.user.id)
    allowed = deliverer.post(
        _opp_url(),
        json={
            "enterprise_code": ENTERPRISE_CODE,
            "title": "缴席位者报备",
            "source_uri": "fdeops://g4/leads/y.md",
            "content_hash": _sha("seat"),
        },
    )
    assert allowed.status_code == 200, allowed.get_data(as_text=True)


def test_admin_actions_require_admin_and_password(
    leader_client, admin_client, authorized_client_factory
) -> None:
    """治理写面：admin 门＋密码确认双闸（非 admin 403／缺密码 400／错密码 403）。"""
    founder_client = authorized_client_factory("fde_engineer")
    _layer_as_r2(admin_client, founder_client)
    opportunity_id = _report(founder_client)["id"]

    not_admin = leader_client.post(
        _admin_opp_url(opportunity_id, "enterprise-confirm"),
        json={
            "confirmation_uri": "fdeops://g4/c.pdf",
            "confirmation_hash": _sha("c"),
            "confirm_password": _pwd(),
        },
    )
    assert not_admin.status_code == 403
    assert not_admin.json["error"]["code"] == "commercial_admin_required"

    no_password = admin_client.post(
        _admin_opp_url(opportunity_id, "enterprise-confirm"),
        json={
            "confirmation_uri": "fdeops://g4/c.pdf",
            "confirmation_hash": _sha("c"),
        },
    )
    assert no_password.status_code == 400
    assert no_password.json["error"]["code"] == "invalid_request"

    wrong_password = admin_client.post(
        _admin_opp_url(opportunity_id, "enterprise-confirm"),
        json={
            "confirmation_uri": "fdeops://g4/c.pdf",
            "confirmation_hash": _sha("c"),
            "confirm_password": "wrong-password",
        },
    )
    assert wrong_password.status_code == 403
    assert wrong_password.json["error"]["code"] == "invalid_password"

    rules_denied = leader_client.post(
        f"{_rules_url()}/protection_period_days",
        json={
            "value": 30,
            "source_uri": "fdeops://g4/rules/x.md",
            "content_hash": _sha("r"),
            "confirm_password": _pwd(),
        },
    )
    assert rules_denied.status_code == 403


def test_rule_configuration_requires_evidence(admin_client) -> None:
    """规则位配置须附书面依据指针 + sha256 指纹；天数须为正整数。"""
    no_evidence = admin_client.post(
        f"{_rules_url()}/protection_period_days",
        json={"value": 30, "confirm_password": _pwd()},
    )
    assert no_evidence.status_code == 400
    assert no_evidence.json["error"]["code"] == "invalid_request"

    bad_days = admin_client.post(
        f"{_rules_url()}/protection_period_days",
        json={
            "value": 0,
            "source_uri": "fdeops://g4/rules/x.md",
            "content_hash": _sha("r"),
            "confirm_password": _pwd(),
        },
    )
    assert bad_days.status_code == 400
    assert bad_days.json["error"]["code"] == "invalid_rule_value"

    ok = _configure_rule(admin_client, "protection_period_days", 30)
    assert ok.status_code == 200
    assert ok.json["data"]["rule"]["status"] == "configured"
    assert ok.json["data"]["rule"]["days"] == 30

    # 可清回 unset（数值待定态）——清空同样要留依据
    cleared = admin_client.post(
        f"{_rules_url()}/protection_period_days",
        json={
            "value": None,
            "source_uri": "fdeops://g4/rules/reset.md",
            "content_hash": _sha("reset"),
            "confirm_password": _pwd(),
        },
    )
    assert cleared.status_code == 200
    assert cleared.json["data"]["rule"]["status"] == "unset"
    assert cleared.json["data"]["rule"]["days"] is None


def test_read_scope_and_permissions(
    admin_client, leader_client, authorized_client_factory, client
) -> None:
    """读面权限四态：本人/admin/他人 403/未认证 401。"""
    founder_client = authorized_client_factory("fde_engineer")
    _layer_as_r2(admin_client, founder_client)
    opportunity_id = _report(founder_client)["id"]

    mine = founder_client.get(_opp_url())
    assert mine.status_code == 200
    assert mine.json["data"]["scope"] == "self"
    assert mine.json["data"]["count"] == 1

    everything = admin_client.get(_opp_url())
    assert everything.status_code == 200
    assert everything.json["data"]["scope"] == "platform"

    other_read = leader_client.get(_opp_url(opportunity_id))
    assert other_read.status_code == 403, other_read.get_data(as_text=True)
    assert other_read.json["error"]["code"] == "opportunity_forbidden"

    anon = client.get(_opp_url())
    assert anon.status_code == 401
    anon_post = client.post(_opp_url(), json={})
    assert anon_post.status_code == 401


def test_withdraw_only_by_reporter(admin_client, authorized_client_factory) -> None:
    """撤回＝报备人自证动作；他人 403。"""
    founder_client = authorized_client_factory("fde_engineer")
    _layer_as_r2(admin_client, founder_client)
    opportunity_id = _report(founder_client)["id"]

    stranger = authorized_client_factory("fde_engineer")
    denied = stranger.post(f"{_opp_url(opportunity_id)}/withdraw", json={})
    assert denied.status_code == 403, denied.get_data(as_text=True)

    withdrawn = founder_client.post(f"{_opp_url(opportunity_id)}/withdraw", json={})
    assert withdrawn.status_code == 200, withdrawn.get_data(as_text=True)
    assert withdrawn.json["data"]["opportunity"]["status"] == "withdrawn"


def test_attribution_event_recorded_without_password(
    admin_client, authorized_client_factory, db_session
) -> None:
    """归属确认事件留痕：带 request_id、**不含密码**（ADR-007）。"""
    from fde_api.workbench.models import OperationEvent

    founder_client = authorized_client_factory("fde_engineer")
    founder_id = _layer_as_r2(admin_client, founder_client)
    opportunity_id = _report(founder_client)["id"]
    _enterprise_confirm(admin_client, opportunity_id)
    _confirm_attribution(admin_client, opportunity_id, founder_id)
    db_session.commit()

    events = db_session.scalars(
        select(OperationEvent).where(
            OperationEvent.event_type == "commercial_opportunity_attribution_confirmed"
        )
    ).all()
    assert events, "归属确认事件未留痕"
    changes = events[-1].changes
    assert "request_id" in changes
    assert changes["owner_user_id"] == founder_id
    assert _pwd() not in str(changes)


def test_governance_face_not_in_api_catalog() -> None:
    """治理面不进 api_catalog（AI 不可调用；G1–G3 同款边界）。"""
    catalog_names = {row[0] for row in CATALOG}
    for path in (
        "commercial.opportunity.report",
        "commercial.opportunity.attribution.confirm",
        "commercial.opportunity.protection.set",
        "commercial.opportunity.match.record",
        "commercial.opportunity.settlement.record",
        "commercial.opportunity-rule.configure",
    ):
        assert path not in catalog_names


# ---------------------------------------------------------------------------
# 7. 结构与迁移
# ---------------------------------------------------------------------------


def test_delivery_settlements_keeps_its_original_columns(db_session) -> None:
    """**不得**往既有结算表硬塞商机字段（ADR-003 §2.1 精神延续）。"""
    inspector = sql_inspect(db_session.get_bind())
    columns = {column["name"] for column in inspector.get_columns("delivery_settlements")}
    assert "opportunity_id" not in columns
    assert "commercial_opportunity_id" not in columns


def test_migration_roundtrip_and_head_shape(engine, alembic_config) -> None:
    """迁移 additive 往返：head 上两表与 CHECK 齐备；downgrade 至**本迁移的父
    版本**后两表消失；回 head 恢复（``-1`` 会被后续叠在头上的迁移顶掉）。"""
    inspector = sql_inspect(engine)
    tables = set(inspector.get_table_names())
    assert "commercial_opportunities" in tables
    assert "commercial_opportunity_rules" in tables

    opportunity_checks = {
        c["name"] for c in inspector.get_check_constraints("commercial_opportunities")
    }
    assert {
        "ck_commercial_opportunities_status",
        "ck_commercial_opportunities_protection_status",
        "ck_commercial_opportunities_attribution_shape",
        "ck_commercial_opportunities_stage_requires_owner",
        "ck_commercial_opportunities_protection_window",
        "ck_commercial_opportunities_protection_order",
    } <= opportunity_checks

    rule_checks = {
        c["name"] for c in inspector.get_check_constraints("commercial_opportunity_rules")
    }
    assert {
        "ck_commercial_opportunity_rules_status",
        "ck_commercial_opportunity_rules_value_kind",
        "ck_commercial_opportunity_rules_unset_has_no_value",
        "ck_commercial_opportunity_rules_configured_shape",
        "ck_commercial_opportunity_rules_configured_has_evidence",
    } <= rule_checks

    command.downgrade(alembic_config, "c4f7a2d9e1b6")
    inspector = sql_inspect(engine)
    gone = set(inspector.get_table_names())
    assert "commercial_opportunities" not in gone
    assert "commercial_opportunity_rules" not in gone
    command.upgrade(alembic_config, "head")
    inspector = sql_inspect(engine)
    back = set(inspector.get_table_names())
    assert "commercial_opportunities" in back
    assert "commercial_opportunity_rules" in back


def test_protection_status_values_are_closed() -> None:
    """保护期状态闭集（不得出现第五种语义）。"""
    assert OPPORTUNITY_PROTECTION_STATUSES == (
        "unconfigured",
        "active",
        "expired",
        "revoked",
    )
