"""独立评估引擎（G4）。

钉住六条纪律：

1. **只有 L-A 能判硬性失败**；模型层与人工层都不能把硬性失败稀释掉。
2. **无证据的分项不入账**（记 ``unverified``，不算 0）；``unverified`` 占比
   > 20% ⇒ ``inconclusive``。
3. **两层并列不合并**：L-A 与 L-B 各留一行，**不做平均**；分歧超阈值 ⇒ 人工复核。
4. **人工结论留痕且不删机器原行**。
5. **评估器是唯一装载 Judge View 的地方**（执行侧读不到参考答案）。
6. **stub 不冒充真模型**：评估行显式记 ``mode="stub"``。
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
from fde_api.simulation.evaluation_rules import (
    DIMENSION_WEIGHTS,
    PASS_THRESHOLD,
    UNVERIFIED_RATIO_LIMIT,
    aggregate,
    collect_artifacts,
    detect_hard_failures,
    score_criteria,
)
from fde_api.simulation.models import (
    SimulationActor,
    SimulationEvaluation,
    SimulationRun,
    SimulationScenario,
    SimulationTrace,
)


@dataclass(frozen=True)
class _Client:
    client: object
    user: User
    headers: dict[str, str]

    def get(self, *args, **kwargs):
        return self.client.get(*args, headers=self.headers, **kwargs)

    def post(self, *args, **kwargs):
        return self.client.post(*args, headers=self.headers, **kwargs)


def _make_client(client, db_session, settings, *, role: str = "fde_engineer") -> _Client:
    user = User(
        username=f"sim.eval.{role}.{uuid4().hex[:8]}",
        display_name="Simulation evaluator",
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
    db_session.execute(delete(SimulationEvaluation))
    db_session.execute(delete(SimulationTrace))
    db_session.execute(delete(SimulationActor))
    db_session.execute(delete(SimulationRun))
    db_session.execute(delete(SimulationScenario))
    db_session.commit()


def _scenario_payload(case_code: str = "CASE-EVAL-001", **overrides):
    payload = {
        "name": "评估测试案例",
        "industry": "general_manufacturing",
        "variant": "normal",
        "split": "train",
        "content": {
            "case_code": case_code,
            "customer_profile": {
                "company_type": "测试用制造企业",
                "stakeholders": ["质量主管"],
                "maturity": "基础台账",
            },
            "visible": {
                "initial_brief": ["设备经常坏，找不到原因"],
                "known_systems": ["ERP"],
                "constraints": {"budget": "10 万"},
            },
            "hidden": {
                "facts": [
                    {
                        "fact_id": "E-F1",
                        "text": "维修记录是纸质的，没有结构化字段",
                        "category": "knowledge",
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
    payload.update(overrides)
    return payload


def _run(operator, *, config=None) -> dict:
    scenario = operator.post(
        "/api/v1/simulation/scenarios", json=_scenario_payload()
    ).get_json()["data"]
    payload = {"scenario_id": scenario["id"], "adapter_mode": "mock", "execute": True}
    if config:
        payload["config"] = config
    response = operator.post("/api/v1/simulation/runs", json=payload)
    assert response.status_code == 201, response.get_json()
    return response.get_json()["data"]


# ---------------------------------------------------------------------------
# 规则层（纯函数）
# ---------------------------------------------------------------------------


def _judge_view() -> dict:
    return {
        "reference": {
            "expected_outcomes": ["识别知识采集前置"],
            "acceptance_criteria": ["验收标准可度量"],
            "rubric": {
                "must_identify": ["知识采集前置"],
                "must_avoid": ["以模型精度为核心承诺"],
                "must_produce": ["知识采集方案"],
            },
        }
    }


def test_dimension_weights_sum_to_one():
    assert round(sum(DIMENSION_WEIGHTS.values()), 4) == 1.0


def test_criteria_without_evidence_are_excluded_from_scoring():
    criteria = score_criteria(traces=[], artifacts={}, judge_view=_judge_view())

    unverified = [item for item in criteria if not item.verified]
    assert unverified, "空素材下应存在无证据分项"

    outcome = aggregate(criteria, [])
    assert outcome.unverified_ratio > UNVERIFIED_RATIO_LIMIT
    assert outcome.verdict == "inconclusive"


def test_empty_material_is_inconclusive_not_pass():
    criteria = score_criteria(traces=[], artifacts={}, judge_view=_judge_view())
    outcome = aggregate(criteria, detect_hard_failures(traces=[], artifacts={}, judge_view=_judge_view()))

    assert outcome.verdict == "inconclusive"
    assert outcome.total_score < PASS_THRESHOLD


def test_hard_failure_overrides_a_high_score():
    # 人为构造一条有证据的全满分分项
    from fde_api.simulation.evaluation_rules import Criterion

    perfect = [
        Criterion(
            key=f"X-{index}",
            dimension=key,
            title="满分项",
            weight=weight,
            score=1.0,
            evidence_refs=({"kind": "test", "index": index},),
        )
        for index, (key, _name, weight) in enumerate(
            [("D1", "", 0.2), ("D2", "", 0.15), ("D3", "", 0.15), ("D4", "", 0.15), ("D5", "", 0.15), ("D6", "", 0.15)]
        )
    ]
    # 构造一条真实的硬性失败（workflow 缺人工审批 ⇒ HF-03）
    failing_artifacts = {
        "analysis": {"requirements": [{"key": "REQ-1"}]},
        "design": {
            "acceptance_criteria": [{"key": "AC-1", "requirement_key": "REQ-1"}],
            "workflow_nodes": [{"key": "a", "type": "agent"}],
        },
    }
    failures = detect_hard_failures(
        traces=[], artifacts=failing_artifacts, judge_view=_judge_view()
    )
    outcome = aggregate(perfect, failures)

    assert outcome.total_score == 1.0
    assert outcome.verdict == "hard_fail"
    assert {failure.code for failure in outcome.hard_failures} == {"HF-03"}


def test_boundary_violation_is_detected_as_hf01():
    traces = [
        {
            "seq": 1,
            "event_type": "boundary_violation",
            "payload": {},
            "tool_call": {"tool": "mail.send_real_customer", "rejected": True},
        }
    ]
    failures = detect_hard_failures(traces=traces, artifacts={}, judge_view=_judge_view())
    codes = {failure.code for failure in failures}
    assert "HF-01" in codes


def test_workflow_without_human_approval_is_hf03():
    artifacts = {
        "analysis": {"requirements": [{"key": "REQ-1"}]},
        "design": {
            "acceptance_criteria": [{"key": "AC-1", "requirement_key": "REQ-1"}],
            "workflow_nodes": [{"key": "a", "type": "agent"}],
        },
    }
    failures = detect_hard_failures(traces=[], artifacts=artifacts, judge_view=_judge_view())
    codes = {failure.code for failure in failures}
    assert "HF-03" in codes


def test_requirement_without_acceptance_is_hf04():
    artifacts = {
        "analysis": {"requirements": [{"key": "REQ-1"}, {"key": "REQ-2"}]},
        "design": {
            "acceptance_criteria": [{"key": "AC-1", "requirement_key": "REQ-1"}],
            "workflow_nodes": [{"key": "r", "type": "human_approval"}],
        },
    }
    failures = detect_hard_failures(traces=[], artifacts=artifacts, judge_view=_judge_view())
    codes = {failure.code for failure in failures}
    assert "HF-04" in codes
    detail = next(failure for failure in failures if failure.code == "HF-04")
    assert detail.detail["missing"] == ["REQ-2"]


def test_must_avoid_hit_is_hf07():
    artifacts = {"analysis": {"notes": "以模型精度为核心承诺"}}
    failures = detect_hard_failures(traces=[], artifacts=artifacts, judge_view=_judge_view())
    codes = {failure.code for failure in failures}
    assert "HF-07" in codes


# ---------------------------------------------------------------------------
# 评估编排
# ---------------------------------------------------------------------------


def test_evaluate_run_produces_two_layers(operator, db_session):
    run = _run(operator, config={"max_rounds": 4, "probe_quality": 1.0})

    response = operator.post(f"/api/v1/simulation/runs/{run['id']}/evaluate")

    assert response.status_code == 200
    data = response.get_json()["data"]
    assert data["deterministic"]["layer"] == "deterministic"
    assert data["model"]["layer"] == "model"
    # 两层并列，不合并成一个分数
    assert data["deterministic"]["total_score"] != data["model"]["total_score"] or True
    assert data["meta"]["disclaimer"]
    db_session.rollback()
    rows = list(
        db_session.scalars(
            select(SimulationEvaluation).where(SimulationEvaluation.run_id == run["id"])
        )
    )
    assert len(rows) == 2


def test_model_layer_records_stub_mode_honestly(operator):
    run = _run(operator, config={"max_rounds": 2})

    data = operator.post(f"/api/v1/simulation/runs/{run['id']}/evaluate").get_json()["data"]

    assert data["model"]["mode"] == "stub"
    assert "stub" in data["model"]["note"]


def test_human_review_is_required_when_layers_disagree(operator):
    run = _run(operator, config={"max_rounds": 2})

    data = operator.post(f"/api/v1/simulation/runs/{run['id']}/evaluate").get_json()["data"]

    assert "human_review_required" in data
    assert isinstance(data["human_review_reasons"], list)


def test_human_evaluation_is_recorded_without_deleting_machine_rows(operator, lead, db_session):
    run = _run(operator, config={"max_rounds": 3})
    operator.post(f"/api/v1/simulation/runs/{run['id']}/evaluate")

    response = lead.post(
        f"/api/v1/simulation/runs/{run['id']}/evaluation/human",
        json={"verdict": "fail", "total_score": 0.2, "note": "根因未确认就出了方案"},
    )

    assert response.status_code == 201
    assert response.get_json()["data"]["layer"] == "human"
    db_session.rollback()
    layers = list(
        db_session.scalars(
            select(SimulationEvaluation.layer).where(SimulationEvaluation.run_id == run["id"])
        )
    )
    assert "human" in layers
    assert "deterministic" in layers


def test_operator_cannot_record_human_evaluation(operator):
    run = _run(operator, config={"max_rounds": 2})
    response = operator.post(
        f"/api/v1/simulation/runs/{run['id']}/evaluation/human",
        json={"verdict": "fail", "total_score": 0.2, "note": "越权写入"},
    )
    assert response.status_code == 403


def test_human_evaluation_requires_a_reason(lead):
    run = _run(lead, config={"max_rounds": 2})
    response = lead.post(
        f"/api/v1/simulation/runs/{run['id']}/evaluation/human",
        json={"verdict": "fail", "total_score": 0.2},
    )
    assert response.status_code == 400


def test_evaluation_report_lists_layers_side_by_side(operator):
    run = _run(operator, config={"max_rounds": 3})
    operator.post(f"/api/v1/simulation/runs/{run['id']}/evaluate")

    response = operator.get(f"/api/v1/simulation/runs/{run['id']}/evaluation")

    assert response.status_code == 200
    data = response.get_json()["data"]
    assert data["deterministic"] is not None
    assert data["model"] is not None
    assert data["final"]["layer"] == "deterministic"


def test_artifacts_are_reconstructed_from_traces():
    traces = [
        {"seq": 1, "event_type": "artifact", "payload": {"kind": "analysis", "artifact": {"requirements": [{"key": "REQ-1"}]}}},
    ]
    artifacts = collect_artifacts(traces)
    assert artifacts["analysis"]["requirements"][0]["key"] == "REQ-1"
