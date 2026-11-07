"""失败分析与改进提案（G5）。

钉住六条纪律：

1. **失败分类与根因**：低分判据/硬性失败 ⇒ 发现 + 根因候选 + 证据引用；
2. **置信度三档**：confirmed / likely / hypothesis；
3. **只有 confirmed 根因能生成提案**（疑似根因先人工复核）；
4. **状态机止于 approved**——提案表**无 publish/apply 状态与列**；
5. **服务层零生产写路径**——生产模块对改进提案的引用必须为零（静态钉）；
6. **审批需 project_lead/admin + 密码确认 + 理由**；审批 ≠ 发布。
"""
from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import delete, select

from conftest import INITIAL_PASSWORD, SERVER_ROOT
from fde_api.auth.models import User
from fde_api.auth.passwords import hash_password
from fde_api.auth.tokens import issue_access_token
from fde_api.extensions import db
from fde_api.simulation.failure_analyzer import (
    CRITERION_TO_FAILURE,
    FAILURE_CATEGORIES,
    analyze_failures,
)
from fde_api.simulation.models import (
    ImprovementProposal,
    SimulationActor,
    SimulationEvaluation,
    SimulationFinding,
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

    def patch(self, *args, **kwargs):
        return self.client.patch(*args, headers=self.headers, **kwargs)


def _make_client(client, db_session, settings, *, role: str) -> _Client:
    user = User(
        username=f"sim.g5.{role}.{uuid4().hex[:8]}",
        display_name="Simulation improver",
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
    db_session.execute(delete(ImprovementProposal))
    db_session.execute(delete(SimulationFinding))
    db_session.execute(delete(SimulationEvaluation))
    db_session.execute(delete(SimulationTrace))
    db_session.execute(delete(SimulationActor))
    db_session.execute(delete(SimulationRun))
    db_session.execute(delete(SimulationScenario))
    db_session.commit()


def _scenario_payload(case_code: str = "CASE-G5-001"):
    return {
        "name": "改进测试案例",
        "industry": "general_manufacturing",
        "variant": "normal",
        "split": "train",
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
                        "fact_id": "G-F1",
                        "text": "维修记录是纸质的，没有结构化字段",
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


def _run_and_evaluate(operator, *, max_rounds: int = 2) -> dict:
    scenario = operator.post(
        "/api/v1/simulation/scenarios", json=_scenario_payload()
    ).get_json()["data"]
    run = operator.post(
        "/api/v1/simulation/runs",
        json={
            "scenario_id": scenario["id"],
            "adapter_mode": "mock",
            "execute": True,
            "config": {"max_rounds": max_rounds, "probe_quality": 0.0},
        },
    ).get_json()["data"]
    operator.post(f"/api/v1/simulation/runs/{run['id']}/evaluate")
    return run


# ---------------------------------------------------------------------------
# 失败分析
# ---------------------------------------------------------------------------


def test_failure_categories_cover_ten_codes():
    assert len(FAILURE_CATEGORIES) == 10
    assert set(CRITERION_TO_FAILURE.values()) <= set(FAILURE_CATEGORIES)


def test_low_scoring_criterion_produces_a_confirmed_finding():
    evaluation = {
        "scores": {
            "criteria": [
                {
                    "key": "D1-01",
                    "dimension": "D1",
                    "title": "识别出客户真实问题",
                    "score": 0.0,
                    "evidence_refs": [{"kind": "expected_missing", "text": "知识采集前置"}],
                }
            ]
        },
        "hard_failures": [],
    }

    findings = analyze_failures(evaluation=evaluation)

    assert findings
    finding = findings[0]
    assert finding.code == "FA-01"
    assert finding.evidence_refs
    assert finding.confirmed_root is not None
    assert finding.confirmed_root.confidence == "confirmed"


def test_hard_failure_produces_a_confirmed_finding_with_evidence():
    evaluation = {
        "scores": {"criteria": []},
        "hard_failures": [
            {
                "code": "HF-04",
                "title": "关键需求没有验收标准",
                "evidence_refs": [{"kind": "requirement", "key": "REQ-2"}],
            }
        ],
    }

    findings = analyze_failures(evaluation=evaluation)

    codes = {finding.code for finding in findings}
    assert "FA-06" in codes
    finding = next(item for item in findings if item.code == "FA-06")
    assert finding.confirmed_root is not None
    assert finding.evidence_refs


def test_analysis_is_idempotent(operator):
    run = _run_and_evaluate(operator)

    first = operator.post(f"/api/v1/simulation/runs/{run['id']}/analyze")
    second = operator.post(f"/api/v1/simulation/runs/{run['id']}/analyze")

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.get_json()["data"]["created"] == 0


def test_findings_require_an_evaluation_first(operator):
    scenario = operator.post(
        "/api/v1/simulation/scenarios", json=_scenario_payload()
    ).get_json()["data"]
    run = operator.post(
        "/api/v1/simulation/runs",
        json={"scenario_id": scenario["id"], "execute": True, "config": {"max_rounds": 1}},
    ).get_json()["data"]

    response = operator.post(f"/api/v1/simulation/runs/{run['id']}/analyze")

    assert response.status_code == 404


# ---------------------------------------------------------------------------
# 改进提案
# ---------------------------------------------------------------------------


def _proposal_payload(finding_ids: list[str], **overrides) -> dict:
    payload = {
        "finding_ids": finding_ids,
        "target": {"kind": "prompt", "ref": "presurvey.interview.prompt"},
        "change_summary": "在访谈检查清单加入数据接入探针",
        "current_version": "v3",
        "proposed_version": "v4",
        "expected_effect": {"dimension": "D1", "delta": 0.08},
        "impact_scope": ["interview"],
        "regression_plan": {"splits": ["train", "regression", "blind"]},
    }
    payload.update(overrides)
    return payload


def test_proposal_can_be_created_from_a_confirmed_finding(operator):
    run = _run_and_evaluate(operator)
    analysis = operator.post(f"/api/v1/simulation/runs/{run['id']}/analyze").get_json()["data"]
    finding_ids = [item["id"] for item in analysis["items"]]

    response = operator.post(
        "/api/v1/simulation/proposals", json=_proposal_payload(finding_ids)
    )

    assert response.status_code == 201
    data = response.get_json()["data"]
    assert data["status"] == "draft"
    assert data["target"]["kind"] == "prompt"
    assert data["proposed_version"] == "v4"


def test_proposal_requires_a_confirmed_root_cause(operator, db_session):
    """疑似根因（hypothesis）不得变成改进项。"""
    from fde_api.simulation.models import SimulationFinding, SimulationEvaluation

    run = _run_and_evaluate(operator)
    with db.session() as session:
        evaluation = session.scalar(
            select(SimulationEvaluation).where(
                SimulationEvaluation.run_id == run["id"],
                SimulationEvaluation.layer == "deterministic",
            )
        )
        finding = SimulationFinding(
            run_id=run["id"],
            evaluation_id=evaluation.id,
            code="FA-02",
            title="错误理解生产流程",
            severity="low",
            dimension="D2",
            description="疑似",
            evidence_refs_json=[],
            root_causes_json=[
                {"code": "领域知识不足", "confidence": "hypothesis", "analysis": "", "evidence_refs": []}
            ],
            status="open",
            detail_json={},
        )
        session.add(finding)
        session.commit()
        finding_id = finding.id

    response = operator.post(
        "/api/v1/simulation/proposals", json=_proposal_payload([finding_id])
    )

    assert response.status_code == 409
    assert response.get_json()["error"]["code"] == "conflict"


def test_duplicate_proposal_for_same_findings_and_target_is_rejected(operator):
    run = _run_and_evaluate(operator)
    analysis = operator.post(f"/api/v1/simulation/runs/{run['id']}/analyze").get_json()["data"]
    finding_ids = [item["id"] for item in analysis["items"]]

    first = operator.post("/api/v1/simulation/proposals", json=_proposal_payload(finding_ids))
    second = operator.post("/api/v1/simulation/proposals", json=_proposal_payload(finding_ids))

    assert first.status_code == 201
    assert second.status_code == 409


def test_operator_cannot_approve_a_proposal(operator):
    run = _run_and_evaluate(operator)
    analysis = operator.post(f"/api/v1/simulation/runs/{run['id']}/analyze").get_json()["data"]
    finding_ids = [item["id"] for item in analysis["items"]]
    proposal = operator.post(
        "/api/v1/simulation/proposals", json=_proposal_payload(finding_ids)
    ).get_json()["data"]

    response = operator.post(
        f"/api/v1/simulation/proposals/{proposal['id']}/decide",
        json={"approve": True, "password": INITIAL_PASSWORD, "note": "同意"},
    )

    assert response.status_code == 403


def test_approval_requires_password_and_reason(lead):
    run = _run_and_evaluate(lead)
    analysis = lead.post(f"/api/v1/simulation/runs/{run['id']}/analyze").get_json()["data"]
    finding_ids = [item["id"] for item in analysis["items"]]
    proposal = lead.post(
        "/api/v1/simulation/proposals", json=_proposal_payload(finding_ids)
    ).get_json()["data"]

    no_password = lead.post(
        f"/api/v1/simulation/proposals/{proposal['id']}/decide",
        json={"approve": True, "note": "同意"},
    )
    no_note = lead.post(
        f"/api/v1/simulation/proposals/{proposal['id']}/decide",
        json={"approve": True, "password": INITIAL_PASSWORD},
    )
    wrong_password = lead.post(
        f"/api/v1/simulation/proposals/{proposal['id']}/decide",
        json={"approve": True, "password": "wrong-password", "note": "同意"},
    )

    assert no_password.status_code == 400
    assert no_note.status_code == 400
    assert wrong_password.status_code == 403


def test_approval_ends_at_approved_with_no_publish_path(lead):
    run = _run_and_evaluate(lead)
    analysis = lead.post(f"/api/v1/simulation/runs/{run['id']}/analyze").get_json()["data"]
    finding_ids = [item["id"] for item in analysis["items"]]
    proposal = lead.post(
        "/api/v1/simulation/proposals", json=_proposal_payload(finding_ids)
    ).get_json()["data"]

    response = lead.post(
        f"/api/v1/simulation/proposals/{proposal['id']}/decide",
        json={"approve": True, "password": INITIAL_PASSWORD, "note": "证据充分，同意改进"},
    )

    assert response.status_code == 200
    data = response.get_json()["data"]
    assert data["status"] == "approved"
    assert data["decided_by_user_id"] == lead.user.id
    # 状态机**止于** approved：没有 published/applied 之类的状态
    assert data["status"] in ("approved", "rejected")


# ---------------------------------------------------------------------------
# 「只提案不落地」的静态钉
# ---------------------------------------------------------------------------


def test_proposal_table_has_no_publish_or_apply_column():
    columns = {column.name for column in ImprovementProposal.__table__.columns}
    assert not columns & {
        "published_at",
        "published_by_user_id",
        "publish_status",
        "applied_at",
        "applied_by_user_id",
        "apply_status",
    }
    assert {"status", "target_json", "current_version", "proposed_version"} <= columns


def test_no_production_module_writes_improvement_proposals():
    """生产模块（``fde_api`` 下除 ``simulation`` 外）对改进提案**零引用**。

    这是「只提案不落地」的最强静态钉：若将来有人从生产面写提案或落地提案，
    本用例立刻转红。
    """
    package_root = SERVER_ROOT / "src" / "fde_api"
    offenders: list[str] = []
    for path in sorted(package_root.rglob("*.py")):
        relative = path.relative_to(package_root)
        if relative.parts[0] == "simulation":
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        if "improvement_proposals" in text or "ImprovementProposal" in text:
            offenders.append(str(relative))
    assert offenders == [], f"生产模块引用了改进提案：{offenders}"


def test_improvement_service_has_no_publish_function():
    """服务层**不提供**发布/落地函数（静态 AST 钉）。"""
    from fde_api.simulation import improvement_service

    tree = ast.parse(Path(improvement_service.__file__).read_text(encoding="utf-8"))
    names = {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    forbidden = {"publish", "apply", "release", "deploy", "publish_proposal"}
    assert not names & forbidden, f"改进服务出现发布类函数：{names & forbidden}"
