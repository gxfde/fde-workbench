"""goal-c CR-008：signoff 开闸并发回归钉。

`ensure_pending_signoff` 承诺「同方案至多一个 pending signoff」（AGENTS.md
T-P0-1 / agents/signoff.py docstring）。三处调用来自三个独立事务（run 执行
worker 的 _finalize / handoff / export 兜底），跨事务并发的 SELECT-then-INSERT
在 READ COMMITTED 下会双插 pending——孤儿 pending 永久滞留且终审台口径漂移。

并发防线 = 事务级 advisory lock 按方案串行化「查 pending + 开闸」一段（同仓
`quote_service` 首单闸 fde_quote_first_order 先例，见 test_quote_first_order_concurrency）。
本测试用真实 PostgreSQL 并发（两个独立连接、真实事务、barrier 同步）钉住防线。
"""
import threading
from datetime import date
from uuid import uuid4

from sqlalchemy import create_engine, select

from fde_api.agents.models import SolutionReviewCheckpoint
from fde_api.agents.signoff import ensure_pending_signoff
from fde_api.auth.models import User
from fde_api.auth.passwords import hash_password
from fde_api.solutions.models import ProjectSolution
from fde_api.workbench.models import IndustryTemplate, IndustryTemplateVersion, Project
from conftest import INITIAL_PASSWORD


def _seed_solution(db_session) -> ProjectSolution:
    """admin + 通用模板项目 + 一个方案（signoff 并发用例只关心方案维度）。"""
    leader = User(
        username=f"signoff.lead.{uuid4().hex[:8]}",
        display_name="签核负责人",
        role="admin",
        password_hash=hash_password(INITIAL_PASSWORD),
        must_change_password=False,
        is_active=True,
    )
    db_session.add(leader)
    db_session.flush()
    template = IndustryTemplate(name="签核模板", industry_name="制造")
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
        project_code=f"SGN-{uuid4().hex[:8]}",
        name="signoff 并发项目",
        enterprise_code=f"signoff 企业·{uuid4().hex[:8]}",
        leader=leader,
        source_template_version=version,
        template_snapshot={},
        research_snapshot={},
        planned_start_date=date(2026, 8, 22),
    )
    db_session.add(project)
    db_session.flush()
    solution = ProjectSolution(project_id=project.id, name="并发签核方案", owner_user_id=leader.id)
    db_session.add(solution)
    db_session.commit()
    return solution


def _pending_count(engine, solution_id: str) -> int:
    with engine.connect() as conn:
        return conn.execute(
            select(SolutionReviewCheckpoint).where(
                SolutionReviewCheckpoint.solution_id == solution_id,
                SolutionReviewCheckpoint.checkpoint_type == "signoff",
                SolutionReviewCheckpoint.status == "pending",
            )
        ).fetchall().__len__()


def _open_in_connection(url: str, solution_id: str, run_id: str, barrier, outcome: list, errors: list) -> None:
    """独立连接 + 独立事务里开一次闸（模拟 _finalize / handoff / 兜底调用点之一）。"""
    from sqlalchemy.orm import Session as RawSession

    engine = create_engine(url)
    try:
        barrier.wait(timeout=30)
        with engine.connect() as conn:
            with conn.begin():
                raw = RawSession(bind=conn)
                checkpoint = ensure_pending_signoff(raw, solution_id=solution_id, run_id=run_id)
                raw.flush()
                # id 是 Python 侧 default（new_uuid），flush 后才落位——
                # 必须 flush 后读，读到 None 是测试写法缺陷不是产品缺陷。
                outcome.append(checkpoint.id)
                raw.close()
    except BaseException as exc:  # noqa: BLE001 - 交由主线程断言
        errors.append(exc)
    finally:
        engine.dispose()


def test_concurrent_ensure_pending_signoff_stays_single_row(db_session, test_settings):
    """双线程同方案并发开闸 → 恒一个 pending，且两线程取回同一 checkpoint。

    无锁形态下两事务 READ COMMITTED 各读不到对方的未提交 INSERT，双插；
    advisory lock 让后到者阻塞至先到者提交，SELECT 命中 → 只补软链不新插。
    """
    solution = _seed_solution(db_session)
    url = test_settings.database_url

    barrier = threading.Barrier(2, timeout=30)
    outcome: list[str] = []
    errors: list[BaseException] = []

    threads = [
        threading.Thread(
            target=_open_in_connection,
            args=(url, solution.id, f"run-{tag}", barrier, outcome, errors),
            daemon=True,
        )
        for tag in ("a", "b")
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)

    assert not errors, errors
    assert len(outcome) == 2, outcome
    # 并发防线成立：两线程必取回同一行
    assert len(set(outcome)) == 1, outcome
    engine = create_engine(url)
    try:
        assert _pending_count(engine, solution.id) == 1
    finally:
        engine.dispose()


def test_ensure_pending_signoff_second_call_soft_links_not_duplicate(db_session, test_settings):
    """串行两次开闸幂等：第二次只补 handoff_run_id 软链，不新插行（既有语义钉）。"""
    solution = _seed_solution(db_session)
    engine = create_engine(test_settings.database_url)
    try:
        from sqlalchemy.orm import Session as RawSession

        with engine.connect() as conn:
            with conn.begin():
                raw = RawSession(bind=conn)
                first = ensure_pending_signoff(raw, solution_id=solution.id, run_id="run-1")
                raw.flush()
                second = ensure_pending_signoff(raw, solution_id=solution.id, run_id="run-2")
                raw.flush()
                raw.close()
        assert first.id == second.id
        assert _pending_count(engine, solution.id) == 1
        # 软链补全：先到者 run-1 缺失时由后到者补上；这里 first 已带 run-1，
        # 第二次调用不改已有软链（只补空，绝不覆写）
        assert first.handoff_run_id == "run-1"
    finally:
        engine.dispose()
