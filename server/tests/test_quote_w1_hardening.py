"""报价 W1 零迁移加固回归钉（party 评审 W1-2 / W1-3）。

两条行为变更必须有用例钉住，否则未来重构会被无声回退：

- W1-2：首单判定排除仿真单（quote_key 前缀 Q-SIM-）。仿真器造的 finalized
  报价不得挤掉真实首单——否则真实首单逃过「必须回校」与三条硬约束。
- W1-3：run_simulation 入口从 session 绑定连接读库名，非 _sim/_test 后缀
  的库 fail-fast；测试库 fde_workbench_test（_test 后缀）必须放行。
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from fde_api.auth.models import User
from fde_api.auth.passwords import hash_password
from fde_api.dispatch.simulator import _require_sandbox_session
from fde_api.projects.quote_service import QuoteServiceError, finalize_quote
from fde_api.workbench.models import IndustryTemplate, IndustryTemplateVersion, Project, Quote
from conftest import INITIAL_PASSWORD


def _seed_project(session: Session) -> tuple[Project, User]:
    leader = User(
        username=f"quote.w1.{uuid4().hex[:8]}",
        display_name="W1 报价负责人",
        role="admin",
        password_hash=hash_password(INITIAL_PASSWORD),
        must_change_password=False,
        is_active=True,
    )
    session.add(leader)
    session.flush()
    template = IndustryTemplate(name="W1 模板", industry_name="制造")
    version = IndustryTemplateVersion(
        template=template,
        name=template.name,
        industry_name="制造",
        description="",
        version_number=1,
        status="published",
        published_by=leader,
    )
    session.add_all([template, version])
    session.flush()
    project = Project(
        project_code=f"QW1-{uuid4().hex[:8]}",
        name="W1 加固项目",
        enterprise_code=f"报价企业·制造·{uuid4().hex[:8]}",
        leader=leader,
        source_template_version=version,
        template_snapshot={},
        research_snapshot={},
        planned_start_date=date(2026, 8, 22),
    )
    session.add(project)
    session.commit()
    return project, leader


def _make_finalizable_quote(
    session: Session, project: Project, *, hours: str, quote_key: str
) -> Quote:
    """造一张已回校、可 finalize 的报价；hours>120 用于触首单硬约束③。"""
    quote = Quote(
        project_id=project.id,
        quote_key=quote_key,
        status="draft",
        tier="light",
        ideal_hours=Decimal(hours),
        realistic_hours=Decimal(hours),
        actual_hours=Decimal(hours),
        integration_factor=Decimal("1.00"),
        data_factor=Decimal("1.00"),
        compliance_factor=Decimal("1.00"),
        buffer_factor=Decimal("1.00"),
        hourly_rate=150,
        cash_cost=100000,
        margin_factor=Decimal("0.25"),
        b_layer_score=0,
        b_layer_factor=Decimal("1.00"),
        anchor_mode="steady",
        labor_cost=Decimal("100000"),
        total_cost=Decimal("100000"),
        formula_price=Decimal("200000"),
        anchor_low=200000,
        anchor_high=300000,
        branch="A",
    )
    session.add(quote)
    session.commit()
    return quote


def _insert_sim_finalized(session: Session, project: Project) -> None:
    """插一张仿真器口径的 finalized 报价（Q-SIM- 前缀、已成交）。"""
    sim = _make_finalizable_quote(
        session, project, hours="10", quote_key=f"Q-SIM-{uuid4().hex[:4]}"
    )
    sim.status = "finalized"
    sim.final_amount = Decimal("250000")
    session.commit()


def test_sim_finalized_quote_does_not_displace_real_first_order(db_session):
    """W1-2：仿真 finalized 单不得让真实首单被判成「非首单」。

    库内已有一张 Q-SIM- 的 finalized 单时，finalize 一张违反硬约束③（realistic
    >120h）的报价仍须按首单被 409 拦截。若计数未排除仿真单，则会按非首单放行
    ——用可辨变异保证此测试对回归敏感。
    """
    project, leader = _seed_project(db_session)
    _insert_sim_finalized(db_session, project)
    violating = _make_finalizable_quote(
        db_session, project, hours="150", quote_key=f"Q-{uuid4().hex[:6]}"
    )

    with pytest.raises(QuoteServiceError) as err:
        finalize_quote(
            actor=leader,
            project_id=project.id,
            quote_key=violating.quote_key,
            payload={"final_amount": "250000"},
        )
    assert err.value.code == "first_order_constraint"


class _FakeSession:
    """最小 session 替身：只提供 connection().engine.url.database，不碰真库。"""

    def __init__(self, database: str) -> None:
        self._database = database

    def connection(self):
        return SimpleNamespace(
            engine=SimpleNamespace(url=SimpleNamespace(database=self._database))
        )


def test_run_simulation_rejects_production_database():
    """W1-3 变异组：生产库（无后缀）必须 fail-fast。"""
    with pytest.raises(RuntimeError, match="沙箱库"):
        _require_sandbox_session(_FakeSession("fde_workbench"))


@pytest.mark.parametrize("database", ["fde_workbench_test", "fde_poc_sim"])
def test_run_simulation_allows_sandbox_databases(database):
    """W1-3 对照组：_test / _sim 后缀放行（测试库走的就是这条路径）。"""
    _require_sandbox_session(_FakeSession(database))
