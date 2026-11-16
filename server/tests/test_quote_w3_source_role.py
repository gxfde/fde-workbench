"""W3 回归钉：Quote.source 仿真隔离正式化 + role_hours 角色工时明细。

W3-1（迁移 d8b4f6a2c9e7）：source 列（manual/simulation）。finalize 首单计数
改为 source != 'simulation'（Q-SIM- 前缀保留双保险）——比 W1-2 的纯前缀启发
式更稳：即使仿真行 key 不带前缀也不会污染首单判定。
W3-2（P7）：role_hours 可选 JSON（角色名→工时）。服务层校验：非空对象、
键 1–40 字符、值非负、合计==ideal_hours（明细与总量互证防两张皮）。
未填＝None，行为与存量逐位一致。

服务级直调（同既有 quote 测试模式），含一条迁移列存在性钉（information_schema）。
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from fde_api.auth.models import User
from fde_api.auth.passwords import hash_password
from fde_api.projects.quote_service import (
    QuoteServiceError,
    create_quote,
    finalize_quote,
)
from fde_api.workbench.models import (
    IndustryTemplate,
    IndustryTemplateVersion,
    Project,
    Quote,
)
from conftest import INITIAL_PASSWORD


def _seed_project(db_session: Session) -> tuple[Project, User]:
    leader = User(
        username=f"w3.lead.{uuid4().hex[:8]}",
        display_name="W3 测试员",
        role="admin",
        password_hash=hash_password(INITIAL_PASSWORD),
        must_change_password=False,
        is_active=True,
    )
    db_session.add(leader)
    db_session.flush()
    template = IndustryTemplate(name="W3 模板", industry_name="制造")
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
        project_code=f"W3-{uuid4().hex[:8]}",
        name="W3 项目",
        enterprise_code=f"W3企业·制造·{uuid4().hex[:8]}",
        leader=leader,
        source_template_version=version,
        template_snapshot={},
        research_snapshot={},
        planned_start_date=date(2026, 11, 16),
    )
    db_session.add(project)
    db_session.commit()
    return project, leader


def _create(db_session: Session, project: Project, actor: User, **extra) -> dict:
    return create_quote(
        actor=actor,
        project_id=project.id,
        payload={
            "tier": "light",
            "ideal_hours": "25",
            "hourly_rate": 150,
            "anchor_mode": "steady",
            **extra,
        },
    )


class TestMigrationColumns:
    def test_source_and_role_hours_columns_exist(self, db_session: Session):
        """迁移列存在性钉：quotes.source not null default 'manual'；role_hours 可空。"""
        rows = db_session.execute(
            text(
                "SELECT column_name, is_nullable, column_default "
                "FROM information_schema.columns "
                "WHERE table_schema='public' AND table_name='quotes' "
                "AND column_name IN ('source','role_hours')"
            )
        ).fetchall()
        by_name = {r[0]: r for r in rows}
        assert set(by_name) == {"source", "role_hours"}
        assert by_name["source"][1] == "NO"  # not null
        assert "manual" in (by_name["source"][2] or "")
        assert by_name["role_hours"][1] == "YES"  # nullable

    def test_create_defaults_source_manual(self, db_session: Session):
        """人工创建的报价 source 恒 manual、role_hours 缺省 None。"""
        project, leader = _seed_project(db_session)
        data = _create(db_session, project, leader)
        assert data["source"] == "manual"
        assert data["inputs"]["role_hours"] is None


class TestRoleHours:
    def test_valid_role_hours_persisted(self, db_session: Session):
        """合法明细（合计==ideal）落库并回显；浮点数入参转 Decimal。"""
        project, leader = _seed_project(db_session)
        data = _create(
            db_session,
            project,
            leader,
            role_hours={"architect": 5, "engineer": 15, "review": 5},
        )
        assert data["inputs"]["role_hours"] == {
            "architect": 5.0,
            "engineer": 15.0,
            "review": 5.0,
        }
        row = db_session.scalar(
            select(Quote).where(
                Quote.project_id == project.id,
                Quote.quote_key == data["quote_key"],
            )
        )
        assert row is not None
        assert row.role_hours == {"architect": "5", "engineer": "15", "review": "5"} or (
            row.role_hours == {"architect": 5, "engineer": 15, "review": 5}
        )

    def test_rejects_negative_hours(self, db_session: Session):
        project, leader = _seed_project(db_session)
        with pytest.raises(QuoteServiceError) as excinfo:
            _create(db_session, project, leader, role_hours={"engineer": -1, "architect": 26})
        assert excinfo.value.status == 400
        assert excinfo.value.code == "invalid_role_hours"

    def test_rejects_sum_mismatch(self, db_session: Session):
        """合计 != ideal_hours → 400（明细与总量互证）。"""
        project, leader = _seed_project(db_session)
        with pytest.raises(QuoteServiceError) as excinfo:
            _create(db_session, project, leader, role_hours={"engineer": 10, "architect": 10})
        assert excinfo.value.status == 400
        assert excinfo.value.code == "invalid_role_hours"
        assert "ideal_hours" in excinfo.value.message

    def test_rejects_empty_and_non_dict(self, db_session: Session):
        project, leader = _seed_project(db_session)
        bad_inputs: list[object] = [{}, [], "25", 25]
        for bad in bad_inputs:
            with pytest.raises(QuoteServiceError) as excinfo:
                _create(db_session, project, leader, role_hours=bad)  # type: ignore[arg-type]
            assert excinfo.value.status == 400
            assert excinfo.value.code == "invalid_role_hours"


class TestSourceExclusion:
    def test_simulation_quote_excluded_from_first_order_count(self, db_session: Session):
        """source='simulation' 的 finalized 单（不带 Q-SIM 前缀）不挤掉真实首单。

        变异可辨：若 finalize 仍按全局 count 判首单，此用例里真实首单的
        三条硬约束会被跳过 → finalize 放行 → 断言失败。
        """
        project, leader = _seed_project(db_session)

        # 仿真单：不带 Q-SIM 前缀（排除只能靠 source 生效——可辨变异点）
        sim = Quote(
            project_id=project.id,
            quote_key=f"Q-XXX-{uuid4().hex[:6]}",
            status="finalized",
            source="simulation",
            tier="light",
            ideal_hours=Decimal("10"),
            realistic_hours=Decimal("10"),
            integration_factor=Decimal("1.00"),
            data_factor=Decimal("1.00"),
            compliance_factor=Decimal("1.00"),
            buffer_factor=Decimal("1.00"),
            hourly_rate=150,
            cash_cost=0,
            margin_factor=Decimal("1.40"),
            b_layer_score=0,
            b_layer_factor=Decimal("1.00"),
            anchor_mode="steady",
            labor_cost=Decimal("0"),
            total_cost=Decimal("0"),
            formula_price=Decimal("0"),
            anchor_low=28000,
            anchor_high=38000,
            branch="A",
            final_amount=Decimal("20000"),
            field_claims={},
        )
        db_session.add(sim)
        db_session.commit()

        # 真实首单：故意违反硬约束①（integration=1.40）——若仿真单被正确排除，
        # 本单仍判定为首单 → finalize 拒 409 first_order_constraint。
        data = _create(
            db_session, project, leader, integration_factor="1.40", c_handling=None
        )
        # light 档 ×1.40 仍可能落 A/B 分支；finalize 需先 calibrate（首单义务）
        quote = db_session.scalar(
            select(Quote).where(
                Quote.project_id == project.id,
                Quote.quote_key == data["quote_key"],
            )
        )
        assert quote is not None
        quote.actual_hours = Decimal("25")  # 免 calibrate 闸（本用例只验首单判定）
        db_session.commit()

        with pytest.raises(QuoteServiceError) as excinfo:
            finalize_quote(
                actor=leader,
                project_id=project.id,
                quote_key=data["quote_key"],
                payload={"final_amount": "30000"},
            )
        assert excinfo.value.status == 409
        assert excinfo.value.code == "first_order_constraint"
