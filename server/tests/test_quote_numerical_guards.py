"""goal-c CR-010：报价数值防御回归钉（500 → 400 口径）。

`quote_service` 自述「数值入参的合理上限（工程防御）：超出即视为录入错误拒 400」
（quote_service.py:120）。三处缺口：
1. create 侧 cash_cost 只拒负数无上限（final_amount 早有 MAX_INPUT_MONEY 闸）；
2. calibrate 侧 deviation_pct 先落库（flush）后才被 Numeric(7,4) 上限定界——
   超限抛 DataError 走全局 500；
3. finalize 侧 final_deviation_pct 同型（final≤10⁷、anchor_low≥18000 合法极差下
   deviation < 100%，当前不可击穿，仅钉住列上界语义）。

本文件钉住 1 与 2 的 400 行为；修复=服务层前置 400 拒（零迁移零路由）。
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from fde_api.auth.models import User
from fde_api.auth.passwords import hash_password
from fde_api.projects.quote_service import MAX_INPUT_MONEY, QuoteServiceError, calibrate_quote, create_quote
from fde_api.workbench.models import IndustryTemplate, IndustryTemplateVersion, Project, Quote
from conftest import INITIAL_PASSWORD


def _seed_project(db_session: Session) -> tuple[Project, User]:
    leader = User(
        username=f"qguard.lead.{uuid4().hex[:8]}",
        display_name="报价守门员",
        role="admin",
        password_hash=hash_password(INITIAL_PASSWORD),
        must_change_password=False,
        is_active=True,
    )
    db_session.add(leader)
    db_session.flush()
    template = IndustryTemplate(name="守门模板", industry_name="制造")
    version = IndustryTemplateVersion(
        template=template,
        name=template.name,
        industry_name=template.industry_name,
        description="",
        version_number=1,
        status="published",
        published_by=leader,
    )
    db_session.add_all([template, version])
    db_session.flush()
    project = Project(
        project_code=f"QGD-{uuid4().hex[:8]}",
        name="数值守门项目",
        enterprise_code=f"守门企业·制造·{uuid4().hex[:8]}",
        leader=leader,
        source_template_version=version,
        template_snapshot={},
        research_snapshot={},
        planned_start_date=date(2026, 8, 22),
    )
    db_session.add(project)
    db_session.commit()
    return project, leader


def test_create_quote_rejects_cash_cost_above_input_money_cap(db_session):
    """CR-010①：cash_cost 超 MAX_INPUT_MONEY → 400（与 final_amount 同口径，防 500 溢出）。"""
    project, leader = _seed_project(db_session)

    with pytest.raises(QuoteServiceError) as excinfo:
        create_quote(
            actor=leader,
            project_id=project.id,
            payload={
                "tier": "light",
                "ideal_hours": "25",
                "hourly_rate": 150,
                "cash_cost": int(MAX_INPUT_MONEY) + 1,
                "anchor_mode": "steady",
            },
        )
    assert excinfo.value.status == 400
    assert excinfo.value.code == "invalid_request"
    # 钉住「cash_cost 上限闸」本身（消息区分于其他 400 形态）：
    assert "现金成本不得超过" in excinfo.value.message

    # 边界内取值照常放行（守门不误伤）：cash=10⁷ 使公式价进 C 分支，随单处理
    data = create_quote(
        actor=leader,
        project_id=project.id,
        payload={
            "tier": "light",
            "ideal_hours": "0.5",
            "hourly_rate": 150,
            "cash_cost": int(MAX_INPUT_MONEY),
            "anchor_mode": "steady",
            "c_handling": "split_phases",
        },
    )
    assert data["inputs"]["cash_cost"] == int(MAX_INPUT_MONEY)


def _tiny_realistic_quote(db_session, project) -> Quote:
    """realistic_hours=0.01 的 draft 报价（ideal=0.01 合法路径构造，actual_hours 未回校）。"""
    quote = Quote(
        project_id=project.id,
        quote_key=f"Q-{uuid4().hex[:6]}",
        status="draft",
        tier="light",
        ideal_hours=Decimal("0.01"),
        realistic_hours=Decimal("0.01"),
        actual_hours=None,
        integration_factor=Decimal("1.00"),
        data_factor=Decimal("1.00"),
        compliance_factor=Decimal("1.00"),
        buffer_factor=Decimal("2.00"),
        hourly_rate=150,
        cash_cost=0,
        margin_factor=Decimal("1.40"),
        b_layer_score=0,
        b_layer_factor=Decimal("1.00"),
        anchor_mode="steady",
        labor_cost=Decimal("0"),
        total_cost=Decimal("0"),
        formula_price=Decimal("0"),
        anchor_low=35000,
        anchor_high=50000,
        branch="A",
        field_claims={},
    )
    db_session.add(quote)
    db_session.commit()
    return quote


def test_calibrate_rejects_deviation_beyond_numeric_storage_cap(db_session):
    """CR-010②：deviation ≈ 999,899.99 > Numeric(7,4) 上限 → 400（修复前 500）。"""
    project, leader = _seed_project(db_session)
    quote = _tiny_realistic_quote(db_session, project)

    with pytest.raises(QuoteServiceError) as excinfo:
        calibrate_quote(
            actor=leader,
            project_id=project.id,
            quote_key=quote.quote_key,
            payload={"actual_hours": "9999", "deviation_reason": "极端偏差回归钉"},
        )
    assert excinfo.value.status == 400
    assert excinfo.value.code == "invalid_request"
    # 钉住「deviation 先落库」防线本身（消息区分于既有 calibrated 99.99 闸——
    # calibrated 是 ×2.0 后口径，deviation 是原始工时偏差口径）：
    assert "偏差超出存储上限" in excinfo.value.message
    # 拒后原行不动：actual_hours 仍为 None（409 already_calibrated 语义不触发）
    db_session.expire_all()
    assert db_session.get(Quote, quote.id).actual_hours is None


def test_calibrate_within_storage_cap_still_passes(db_session):
    """对照组：偏差在 Numeric(7,4) 上界内（< 999.9999）照常回校——守门不误伤。"""
    project, leader = _seed_project(db_session)
    quote = _tiny_realistic_quote(db_session, project)
    # actual=2 vs realistic=0.01 → deviation=199.99，calibrated=2.0×2/0.01=400.00
    # 400.00 > 99.99（calibrated 既有闸）会先拒 400——取 actual=0.05：
    # deviation=4.00 ✓，calibrated=2.0×0.05/0.01=10.00 ✓
    data = calibrate_quote(
        actor=leader,
        project_id=project.id,
        quote_key=quote.quote_key,
        payload={"actual_hours": "0.05", "deviation_reason": "对照回校"},
    )
    assert data["calibration"]["deviation_pct"] == 4.0
    assert data["calibration"]["calibrated_buffer_factor"] == 10.0
