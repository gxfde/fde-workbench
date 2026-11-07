"""回归与盲测系统（G6）。

钉住六条纪律：

1. **数据集三分按案例切**（同案例三变体同属一个集）；
2. **套件可跨集**（泛化差要跨集测）；
3. **前后对比不只看总分**：逐维度 Δ、硬性失败集合差异、成本 Δ；
4. **泛化差 = gain_train − gain_blind**；> 0.15 ⇒ 过拟合风险；
5. **改进只许用 train 集的失败**（回归/盲测集的失败不得用于提改进）；
6. **候选改进只在模拟域内生效**（override_json.run_config），生产配置零改动。
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
from fde_api.simulation.models import (
    ImprovementProposal,
    RegressionResult,
    RegressionSuite,
    SimulationActor,
    SimulationEvaluation,
    SimulationFinding,
    SimulationRun,
    SimulationScenario,
    SimulationTrace,
)
from fde_api.simulation.regression_runner import (
    OVERFIT_GAP_THRESHOLD,
    RunSummary,
    compare,
)
from fde_api.simulation.seeds import CASE_SPLIT


@dataclass(frozen=True)
class _Client:
    client: object
    user: User
    headers: dict[str, str]

    def get(self, *args, **kwargs):
        return self.client.get(*args, headers=self.headers, **kwargs)

    def post(self, *args, **kwargs):
        return self.client.post(*args, headers=self.headers, **kwargs)

    def patch(self, *args, **kwargs):
        return self.client.patch(*args, headers=self.headers, **kwargs)


def _make_client(client, db_session, settings, *, role: str = "fde_engineer") -> _Client:
    user = User(
        username=f"sim.g6.{role}.{uuid4().hex[:8]}",
        display_name="Simulation regressor",
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
def lead(client, db_session, settings):
    return _make_client(client, db_session, settings, role="project_lead")


@pytest.fixture(autouse=True)
def _clean_simulation(db_session):
    yield
    db_session.rollback()
    db_session.execute(delete(RegressionResult))
    db_session.execute(delete(RegressionSuite))
    db_session.execute(delete(ImprovementProposal))
    db_session.execute(delete(SimulationFinding))
    db_session.execute(delete(SimulationEvaluation))
    db_session.execute(delete(SimulationTrace))
    db_session.execute(delete(SimulationActor))
    db_session.execute(delete(SimulationRun))
    db_session.execute(delete(SimulationScenario))
    db_session.commit()


def _scenario_payload(case_code: str, *, split: str = "train", fact_text: str = "维修记录是纸质的，没有结构化字段"):
    return {
        "name": f"回归案例 {case_code}",
        "industry": "general_manufacturing",
        "variant": "normal",
        "split": split,
        "content": {
            "case_code": case_code,
            "customer_profile": {"stakeholders": ["质量主管"]},
            "visible": {
                "initial_brief": ["设备经常坏"],
                "known_systems": ["ERP"],
                "constraints": {"budget": "10 万"},
            },
            "hidden": {
                "facts": [
                    {
                        "fact_id": f"{case_code}-F1",
                        "text": fact_text,
                        "disclosure_stage": "interview",
                        "probe_keywords": ["维修", "记录"],
                    }
                ]
            },
            "misleading_request": "上 AI 预测性维护",
            "seed_data": {"crm": {"leads": [{"company": "示例"}]}},
        },
        "reference": {
            "expected_outcomes": ["识别知识采集前置"],
            "acceptance_criteria": ["验收标准可度量"],
            "rubric": {
                "must_identify": ["知识采集前置"],
                "must_avoid": ["以模型精度为核心承诺"],
                "must_produce": ["知识采集方案"],
            },
        },
    }


# ---------------------------------------------------------------------------
# 1. 数据集三分
# ---------------------------------------------------------------------------


def test_builtin_cases_are_split_across_three_datasets():
    assert set(CASE_SPLIT.values()) == {"train", "regression", "blind"}
    # 同案例的三个变体必须同属一个集（否则对比失去可比性）
    for case_code, split in CASE_SPLIT.items():
        assert split in ("train", "regression", "blind")
        assert case_code.startswith("CASE-")


def test_seeded_rows_carry_the_case_level_split():
    from fde_api.simulation.seeds import build_seed_rows

    rows = build_seed_rows()
    for row in rows:
        assert row["split"] == CASE_SPLIT[row["scenario_key"]]


# ---------------------------------------------------------------------------
# 2. 套件
# ---------------------------------------------------------------------------


def test_suite_can_be_created_from_a_split(operator):
    operator.post(
        "/api/v1/simulation/scenarios",
        json=_scenario_payload("CASE-G6-TRAIN", split="train"),
    )
    operator.post(
        "/api/v1/simulation/scenarios",
        json=_scenario_payload("CASE-G6-BLIND", split="blind"),
    )

    response = operator.post(
        "/api/v1/simulation/regression/suites",
        json={"name": "盲测套件", "split": "blind"},
    )

    assert response.status_code == 201
    data = response.get_json()["data"]
    assert data["split"] == "blind"
    assert len(data["scenario_ids"]) == 1


def test_suite_name_must_be_unique(operator):
    scenario = operator.post(
        "/api/v1/simulation/scenarios", json=_scenario_payload("CASE-G6-UNIQ")
    ).get_json()["data"]
    operator.post(
        "/api/v1/simulation/regression/suites",
        json={"name": "套件A", "scenario_ids": [scenario["id"]]},
    )
    response = operator.post(
        "/api/v1/simulation/regression/suites",
        json={"name": "套件A", "scenario_ids": [scenario["id"]]},
    )
    assert response.status_code == 409


# ---------------------------------------------------------------------------
# 3. 前后对比（纯函数）
# ---------------------------------------------------------------------------


def _summary(
    run_id: str, split: str, total: float, dims: dict[str, float], hard: tuple[str, ...] = ()
) -> RunSummary:
    return RunSummary(
        run_id=run_id,
        scenario_id="scn",
        split=split,
        total_score=total,
        verdict="pass" if total >= 0.75 else "conditional",
        dimension_scores=dims,
        hard_failures=hard,
        cost={"tool_calls": 10},
        failure_codes=(),
    )


def test_compare_reports_dimension_deltas_and_verdict():
    before = [_summary("b1", "train", 0.60, {"D1": 0.5, "D5": 0.7})]
    after = [_summary("a1", "train", 0.80, {"D1": 0.9, "D5": 0.7})]

    report = compare(before=before, after=after)

    assert report["total_delta"] == 0.2
    assert report["dimension_deltas"]["D1"] == 0.4
    assert report["verdict"] == "improved"


def test_new_hard_failure_downgrades_the_verdict():
    before = [_summary("b1", "train", 0.80, {"D1": 0.8})]
    after = [_summary("a1", "train", 0.90, {"D1": 0.9}, hard=("HF-01",))]

    report = compare(before=before, after=after)

    assert report["new_hard_failures"] == ["HF-01"]
    assert report["verdict"] == "mixed"


def test_dimension_regression_is_reported_even_when_total_rises():
    before = [_summary("b1", "train", 0.70, {"D1": 0.9, "D6": 0.9})]
    after = [_summary("a1", "train", 0.80, {"D1": 0.9, "D6": 0.5})]

    report = compare(before=before, after=after)

    assert report["regressed_dimensions"] == ["D6"]
    assert report["verdict"] == "mixed"


def test_overfit_risk_is_detected_from_the_generalization_gap():
    before = [
        _summary("b1", "train", 0.50, {"D1": 0.5}),
        _summary("b2", "blind", 0.50, {"D1": 0.5}),
    ]
    after = [
        _summary("a1", "train", 0.90, {"D1": 0.9}),
        _summary("a2", "blind", 0.52, {"D1": 0.5}),
    ]

    report = compare(before=before, after=after)

    assert report["train_gain"] == 0.4
    assert report["blind_gain"] == 0.02
    assert report["generalization_gap"] == 0.38
    assert report["generalization_gap"] > OVERFIT_GAP_THRESHOLD
    assert report["overfit_risk"] is True


# ---------------------------------------------------------------------------
# 4. 端到端回归跑
# ---------------------------------------------------------------------------


def _proposal(operator, *, run_split: str = "train") -> dict:
    """造一个带模拟域覆盖载荷的提案（覆盖 = 提高追问命中率）。"""
    scenario = operator.post(
        "/api/v1/simulation/scenarios",
        json=_scenario_payload("CASE-G6-PROPOSAL", split=run_split),
    ).get_json()["data"]
    run = operator.post(
        "/api/v1/simulation/runs",
        json={
            "scenario_id": scenario["id"],
            "adapter_mode": "mock",
            "execute": True,
            "config": {"max_rounds": 4, "probe_quality": 0.0},
        },
    ).get_json()["data"]
    operator.post(f"/api/v1/simulation/runs/{run['id']}/evaluate")
    analysis = operator.post(f"/api/v1/simulation/runs/{run['id']}/analyze").get_json()["data"]
    finding_ids = [item["id"] for item in analysis["items"]]
    response = operator.post(
        "/api/v1/simulation/proposals",
        json={
            "finding_ids": finding_ids,
            "target": {"kind": "prompt", "ref": "presurvey.interview.prompt"},
            "change_summary": "提高访谈追问命中率",
            "current_version": "v3",
            "proposed_version": "v4",
            "override_json": {"run_config": {"probe_quality": 1.0}},
        },
    )
    assert response.status_code == 201, response.get_json()
    return response.get_json()["data"]


def test_regression_run_compares_baseline_and_candidate(operator):
    scenario = operator.post(
        "/api/v1/simulation/scenarios", json=_scenario_payload("CASE-G6-RUN")
    ).get_json()["data"]
    suite = operator.post(
        "/api/v1/simulation/regression/suites",
        json={
            "name": "回归套件",
            "split": "train",
            "scenario_ids": [scenario["id"]],
            "baseline_config": {"max_rounds": 4, "probe_quality": 0.0},
        },
    ).get_json()["data"]
    proposal = _proposal(operator)

    response = operator.post(
        f"/api/v1/simulation/regression/suites/{suite['id']}/run",
        json={"proposal_id": proposal["id"]},
    )

    assert response.status_code == 201
    data = response.get_json()["data"]
    assert data["before"]["runs"] == 1
    assert data["after"]["runs"] == 1
    assert data["verdict"] in ("improved", "mixed", "no_change", "regressed")
    assert "total_delta" in data["deltas"]
    assert data["before_run_ids"] and data["after_run_ids"]
    assert data["before_run_ids"] != data["after_run_ids"]


def test_regression_requires_a_proposal_with_a_sim_domain_override(operator):
    scenario = operator.post(
        "/api/v1/simulation/scenarios", json=_scenario_payload("CASE-G6-NOOVERRIDE")
    ).get_json()["data"]
    suite = operator.post(
        "/api/v1/simulation/regression/suites",
        json={"name": "无覆盖套件", "scenario_ids": [scenario["id"]]},
    ).get_json()["data"]
    proposal = _proposal(operator)
    # 去掉覆盖载荷
    from fde_api.extensions import db

    with db.session() as session:
        row = session.get(ImprovementProposal, proposal["id"])
        row.override_json = {}
        session.commit()

    response = operator.post(
        f"/api/v1/simulation/regression/suites/{suite['id']}/run",
        json={"proposal_id": proposal["id"]},
    )

    assert response.status_code == 409
    assert response.get_json()["error"]["code"] == "conflict"


def test_proposal_from_blind_set_findings_is_rejected(operator):
    """改进只许用 train 集的失败——盲测集不得用于调参。"""
    scenario = operator.post(
        "/api/v1/simulation/scenarios",
        json=_scenario_payload("CASE-G6-BLINDFIND", split="blind"),
    ).get_json()["data"]
    run = operator.post(
        "/api/v1/simulation/runs",
        json={
            "scenario_id": scenario["id"],
            "adapter_mode": "mock",
            "execute": True,
            "config": {"max_rounds": 2, "probe_quality": 0.0},
        },
    ).get_json()["data"]
    operator.post(f"/api/v1/simulation/runs/{run['id']}/evaluate")
    analysis = operator.post(f"/api/v1/simulation/runs/{run['id']}/analyze").get_json()["data"]
    finding_ids = [item["id"] for item in analysis["items"]]

    response = operator.post(
        "/api/v1/simulation/proposals",
        json={
            "finding_ids": finding_ids,
            "target": {"kind": "prompt", "ref": "presurvey.interview.prompt"},
            "change_summary": "在盲测集上找改进",
        },
    )

    assert response.status_code == 409
    assert "盲测" in response.get_json()["error"]["message"]


def test_regression_result_is_idempotent(operator):
    scenario = operator.post(
        "/api/v1/simulation/scenarios", json=_scenario_payload("CASE-G6-IDEM")
    ).get_json()["data"]
    suite = operator.post(
        "/api/v1/simulation/regression/suites",
        json={"name": "幂等套件", "scenario_ids": [scenario["id"]]},
    ).get_json()["data"]

    first = operator.post(f"/api/v1/simulation/regression/suites/{suite['id']}/run", json={})
    second = operator.post(f"/api/v1/simulation/regression/suites/{suite['id']}/run", json={})

    assert first.status_code == 201
    assert first.get_json()["data"]["created"] is True
    assert second.get_json()["data"]["created"] is False
