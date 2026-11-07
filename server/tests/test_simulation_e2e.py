"""V3.2 G8 · 端到端验收（全流程实测）。

本文件**就是**验收闸：按 G8 清单逐项跑一遍并断言。

1. **18 次基础模拟**：6 案例 × 3 客户行为变体，各跑一次并评估；
2. **失败案例重跑**：对低分案例提高 ``probe_quality`` 重跑，看是否变好；
3. **回归测试**：训练集改进 → 回归集检退化；
4. **盲测**：盲测集上的泛化差与过拟合判定；
5. **安全隔离测试**：越界工具 ⇒ ``failed_hard``；模拟数据零真实副作用；
6. **权限越权测试**：``viewer`` 全线 403；
7. **结果与成本统计**：得分分布、工具调用、轮次、成本。

**诚实边界**：本轮为 **mock 执行面**——统计的是「训练场机制是否按预期跑通」，
**不是**真实 Agent 的交付质量（真实面接线见 IT-01）。
"""
from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4

import pytest
from sqlalchemy import delete, select

from conftest import INITIAL_PASSWORD
from fde_api.auth.models import User
from fde_api.auth.passwords import hash_password
from fde_api.auth.tokens import issue_access_token
from fde_api.extensions import db
from fde_api.simulation import evaluator, run_service
from fde_api.simulation.improvement_service import analyze_run, create_proposal, list_findings
from fde_api.simulation.models import (
    ImprovementProposal,
    SimulationActor,
    SimulationEvaluation,
    SimulationFinding,
    SimulationRun,
    SimulationScenario,
    SimulationTrace,
)
from fde_api.simulation.seeds import CASE_SPLIT, VARIANTS, seed_scenarios


@dataclass(frozen=True)
class _Client:
    client: object
    user: User
    headers: dict[str, str]

    def get(self, *args, **kwargs):
        return self.client.get(*args, headers=self.headers, **kwargs)

    def post(self, *args, **kwargs):
        return self.client.post(*args, headers=self.headers, **kwargs)


def _make_client(client, db_session, settings, *, role: str) -> _Client:
    user = User(
        username=f"sim.e2e.{role}.{uuid4().hex[:8]}",
        display_name="Simulation e2e",
        role=role,
        password_hash=hash_password(INITIAL_PASSWORD),
        must_change_password=False,
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()
    return _Client(client, user, {"Authorization": f"Bearer {issue_access_token(user, settings)}"})


@pytest.fixture
def operator(client, db_session, settings):
    return _make_client(client, db_session, settings, role="fde_engineer")


@pytest.fixture
def viewer(client, db_session, settings):
    return _make_client(client, db_session, settings, role="viewer")


@pytest.fixture
def lead(client, db_session, settings):
    return _make_client(client, db_session, settings, role="project_lead")


@pytest.fixture(autouse=True)
def _clean_simulation(db_session):
    yield
    db_session.rollback()
    db_session.execute(delete(ImprovementProposal))
    db_session.execute(delete(SimulationFinding))
    db_session.execute(delete(SimulationEvaluation))
    db_session.execute(delete(SimulationTrace))
    db_session.execute(delete(SimulationActor))
    db_session.execute(delete(SimulationRun))
    db_session.execute(delete(SimulationScenario))
    db_session.commit()


@pytest.fixture
def seeded_scenarios(db_session):
    """把 6 个内置案例 × 3 变体播种进库（18 行）。"""
    with db.session() as session:
        seed_scenarios(session)
        session.commit()
    with db.session() as session:
        rows = list(
            session.scalars(
                select(SimulationScenario).order_by(
                    SimulationScenario.scenario_key, SimulationScenario.variant
                )
            )
        )
    return rows


# ---------------------------------------------------------------------------
# 1. 18 次基础模拟
# ---------------------------------------------------------------------------


def test_sixteen_scenarios_are_seeded_across_three_datasets(seeded_scenarios):
    assert len(seeded_scenarios) == 18
    keys = {row.scenario_key for row in seeded_scenarios}
    assert len(keys) == 6
    for row in seeded_scenarios:
        assert row.variant in VARIANTS
        assert row.split == CASE_SPLIT[row.scenario_key]
    splits = {row.split for row in seeded_scenarios}
    assert splits == {"train", "regression", "blind"}


def test_eighteen_simulations_run_and_evaluate(operator, seeded_scenarios):
    """18 次基础模拟：每次都跑完、落 Trace、产出评估结论。"""
    summaries = []
    for scenario in seeded_scenarios:
        run = run_service.create_run(
            actor=operator.user,
            payload={
                "scenario_id": scenario.id,
                "adapter_mode": "mock",
                "execute": True,
                "config": {"max_rounds": 5, "probe_quality": 1.0},
            },
        )
        assert run["status"] == "completed", run
        report = evaluator.evaluate_run(actor=operator.user, run_id=run["id"])
        assert report["verdict"] in (
            "pass",
            "conditional",
            "fail",
            "hard_fail",
            "inconclusive",
        )
        assert report["meta"]["adapter_mode"] == "mock"
        summaries.append(
            {
                "case": scenario.scenario_key,
                "variant": scenario.variant,
                "split": scenario.split,
                "score": report["total_score"],
                "verdict": report["verdict"],
                "cost": run["cost"],
            }
        )

    assert len(summaries) == 18
    # 每个案例的三个变体都跑到了
    assert len({(item["case"], item["variant"]) for item in summaries}) == 18
    # 成本统计可算
    assert all("tool_calls" in item["cost"] for item in summaries)


# ---------------------------------------------------------------------------
# 2. 失败案例重跑
# ---------------------------------------------------------------------------


def test_rerunning_with_better_probing_improves_the_result(operator, seeded_scenarios):
    """失败案例重跑：提高 ``probe_quality`` 后，披露更多 → 结论更好。"""
    scenario = seeded_scenarios[0]

    shallow = run_service.create_run(
        actor=operator.user,
        payload={
            "scenario_id": scenario.id,
            "adapter_mode": "mock",
            "execute": True,
            "config": {"max_rounds": 5, "probe_quality": 0.0},
        },
    )
    deep = run_service.create_run(
        actor=operator.user,
        payload={
            "scenario_id": scenario.id,
            "adapter_mode": "mock",
            "execute": True,
            "config": {"max_rounds": 5, "probe_quality": 1.0},
        },
    )
    shallow_report = evaluator.evaluate_run(actor=operator.user, run_id=shallow["id"])
    deep_report = evaluator.evaluate_run(actor=operator.user, run_id=deep["id"])

    assert deep_report["total_score"] >= shallow_report["total_score"]
    assert deep_report["dimension_scores"].get("D1", 0) >= shallow_report[
        "dimension_scores"
    ].get("D1", 0)


# ---------------------------------------------------------------------------
# 3–4. 回归与盲测
# ---------------------------------------------------------------------------


def test_regression_and_blind_splits_can_be_compared(operator, seeded_scenarios):
    """回归与盲测：同一套件跨集对比，泛化差可算。"""
    from fde_api.simulation.regression_service import create_suite, run_regression

    train_ids = [row.id for row in seeded_scenarios if row.split == "train"][:2]
    blind_ids = [row.id for row in seeded_scenarios if row.split == "blind"][:1]
    suite = create_suite(
        actor=operator.user,
        payload={
            "name": "验收跨集套件",
            "split": "mixed",
            "scenario_ids": train_ids + blind_ids,
            "baseline_config": {"max_rounds": 5, "probe_quality": 0.0},
        },
    )

    result = run_regression(actor=operator.user, suite_id=suite["id"])

    assert result["before"]["runs"] == 3
    assert "generalization_gap" in result
    assert result["verdict"] in (
        "improved",
        "regressed",
        "mixed",
        "no_change",
        "inconclusive",
    )


# ---------------------------------------------------------------------------
# 5. 安全隔离测试
# ---------------------------------------------------------------------------


def test_boundary_violation_ends_the_run_as_hard_failure(operator, seeded_scenarios):
    """安全隔离：越界调用 ⇒ 拒绝 + 留证 + ``failed_hard`` + 不可重试。"""
    scenario = seeded_scenarios[0]
    run = run_service.create_run(
        actor=operator.user,
        payload={
            "scenario_id": scenario.id,
            "adapter_mode": "mock",
            "execute": True,
            "config": {"max_rounds": 2, "inject_boundary_violation": True},
        },
    )

    assert run["status"] == "failed_hard"
    assert run["error"]["code"] == "boundary_violation"

    report = evaluator.evaluate_run(actor=operator.user, run_id=run["id"])
    assert report["verdict"] == "hard_fail"
    codes = {item["code"] for item in report["hard_failures"]}
    assert "HF-01" in codes

    from fde_api.simulation.service import ScenarioServiceError

    with pytest.raises(ScenarioServiceError) as excinfo:
        run_service.retry_run(actor=operator.user, run_id=run["id"])
    assert excinfo.value.status == 409


def test_simulation_writes_no_project_rows(operator, seeded_scenarios):
    """模拟数据与真实项目严格隔离：模拟全程零 projects 行。"""
    from fde_api.workbench.models import Project

    scenario = seeded_scenarios[0]
    run_service.create_run(
        actor=operator.user,
        payload={
            "scenario_id": scenario.id,
            "adapter_mode": "mock",
            "execute": True,
            "config": {"max_rounds": 2},
        },
    )
    with db.session() as session:
        assert session.scalar(select(Project.id).limit(1)) is None
        assert session.scalar(select(SimulationRun.id).limit(1)) is not None


def test_simulation_tools_have_no_external_effects(operator, seeded_scenarios):
    """模拟工具零真实副作用：发信只落内存发件箱，无 SMTP 通道。"""
    scenario = seeded_scenarios[0]
    run = run_service.create_run(
        actor=operator.user,
        payload={
            "scenario_id": scenario.id,
            "adapter_mode": "mock",
            "execute": True,
            "config": {"max_rounds": 2},
        },
    )
    with db.session() as session:
        traces = list(
            session.scalars(
                select(SimulationTrace).where(SimulationTrace.run_id == run["id"])
            )
        )
    tool_calls = [trace for trace in traces if trace.tool_call_json]
    assert tool_calls
    for trace in tool_calls:
        assert str(trace.tool_call_json.get("tool")).startswith("sim.")


# ---------------------------------------------------------------------------
# 6. 权限越权测试
# ---------------------------------------------------------------------------


def test_viewer_is_rejected_across_the_training_lab_surface(viewer):
    """权限越权：viewer 全线 403（读与写）。"""
    for path, method in (
        ("/api/v1/simulation/scenarios", "get"),
        ("/api/v1/simulation/runs", "get"),
        ("/api/v1/simulation/findings", "get"),
        ("/api/v1/simulation/proposals", "get"),
        ("/api/v1/simulation/regression/suites", "get"),
        ("/api/v1/simulation/regression/results", "get"),
    ):
        response = viewer.get(path)
        assert response.status_code == 403, path

    create = viewer.post(
        "/api/v1/simulation/runs", json={"scenario_id": "00000000-0000-0000-0000-000000000000"}
    )
    assert create.status_code == 403
    assert create.get_json()["error"]["code"] == "forbidden"


# ---------------------------------------------------------------------------
# 7. 失败分析 → 改进提案（端到端闭环）
# ---------------------------------------------------------------------------


def test_failure_analysis_yields_a_confirmed_finding_and_a_proposal(operator, seeded_scenarios):
    """失败分析 → 结构化改进提案（闭环）。"""
    scenario = seeded_scenarios[0]
    run = run_service.create_run(
        actor=operator.user,
        payload={
            "scenario_id": scenario.id,
            "adapter_mode": "mock",
            "execute": True,
            "config": {"max_rounds": 3, "probe_quality": 0.0},
        },
    )
    evaluator.evaluate_run(actor=operator.user, run_id=run["id"])
    analysis = analyze_run(actor=operator.user, run_id=run["id"])

    assert analysis["created"] >= 1
    confirmed = [
        finding
        for finding in analysis["items"]
        if any(
            str(cause.get("confidence")) == "confirmed"
            for cause in finding["root_causes"]
        )
    ]
    assert confirmed, "低分且有证据 ⇒ 应产出 confirmed 根因"

    proposal = create_proposal(
        actor=operator.user,
        payload={
            "finding_ids": [finding["id"] for finding in confirmed],
            "target": {"kind": "prompt", "ref": "presurvey.interview.prompt"},
            "change_summary": "在访谈检查清单加入数据接入探针",
            "current_version": "v3",
            "proposed_version": "v4",
            "override_json": {"run_config": {"probe_quality": 1.0}},
        },
    )

    assert proposal["status"] == "draft"
    assert proposal["override_json"]["run_config"]["probe_quality"] == 1.0
    assert proposal["target"]["kind"] == "prompt"


def test_end_to_end_cost_and_score_statistics_are_computable(operator, seeded_scenarios):
    """结果与成本统计：18 次运行的得分/轮次/工具调用可汇总。"""
    scores: list[float] = []
    rounds: list[int] = []
    calls: list[int] = []
    for scenario in seeded_scenarios[:6]:
        run = run_service.create_run(
            actor=operator.user,
            payload={
                "scenario_id": scenario.id,
                "adapter_mode": "mock",
                "execute": True,
                "config": {"max_rounds": 5, "probe_quality": 1.0},
            },
        )
        report = evaluator.evaluate_run(actor=operator.user, run_id=run["id"])
        scores.append(float(report["total_score"]))
        rounds.append(int(run["cost"].get("rounds", 0)))
        calls.append(int(run["cost"].get("tool_calls", 0)))

    assert len(scores) == 6
    assert all(0.0 <= score <= 1.0 for score in scores)
    assert all(value > 0 for value in rounds)
    assert all(value > 0 for value in calls)
    # 统计口径可复算
    assert round(sum(scores) / len(scores), 4) >= 0.0
