"""失败分析与改进提案（G5；N4 G-11 语义收口）。

钉住六条纪律：

1. **失败分类与根因**：低分判据/硬性失败 ⇒ 发现 + 根因候选 + 证据引用；
2. **置信度三档**：confirmed / likely / hypothesis；
3. **只有 confirmed 根因能生成提案**（疑似根因先人工复核）；
4. **状态机 draft→in_review→approved→published**——``published`` 仅经
   ``release_channel``（发布/回滚受控记账可回滚）；发布状态只许住
   ``release_json`` 一列（散列发布列禁名单原样保留）；
5. **只许经发布通道写**（N4 改语义，不删钉）——全仓 ``ImprovementProposal``
   引用面 ⊆ {models, improvement_service, release_channel}；发布/回滚/工单
   函数只许住 release_channel 且必须带密码闸＋admin 判定；
6. **审批需 project_lead/admin + 密码确认 + 理由**；审批 ≠ 发布（发布另走
   release_channel：admin＋密码＋回归计划在案）。
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

@pytest.fixture
def admin(client, db_session, settings):
    return _make_client(client, db_session, settings, role="admin")


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
                    "key": "D1-02",
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


def test_proposal_can_be_created_from_a_confirmed_finding(operator, admin):
    run = _run_and_evaluate(operator)
    analysis = operator.post(f"/api/v1/simulation/runs/{run['id']}/analyze").get_json()["data"]
    # rubric-v3 换代：mock 零披露只产 hypothesis（D1-01 的 expected_missing
    # 「永远 confirmed」链路正是本轮剔除的假发现机制）⇒ 走 L-C 裁定面显式 confirm。
    for item in analysis["items"]:
        resp = admin.post(
            f"/api/v1/simulation/findings/{item['id']}/adjudicate",
            json={"action": "confirm", "note": "夹具裁定：rubric-v3 换代"},
        )
        assert resp.status_code == 200, resp.get_json()
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


def test_duplicate_proposal_for_same_findings_and_target_is_rejected(operator, admin):
    run = _run_and_evaluate(operator)
    analysis = operator.post(f"/api/v1/simulation/runs/{run['id']}/analyze").get_json()["data"]
    # rubric-v3 换代：mock 零披露只产 hypothesis（D1-01 的 expected_missing
    # 「永远 confirmed」链路正是本轮剔除的假发现机制）⇒ 走 L-C 裁定面显式 confirm。
    for item in analysis["items"]:
        resp = admin.post(
            f"/api/v1/simulation/findings/{item['id']}/adjudicate",
            json={"action": "confirm", "note": "夹具裁定：rubric-v3 换代"},
        )
        assert resp.status_code == 200, resp.get_json()
    finding_ids = [item["id"] for item in analysis["items"]]

    first = operator.post("/api/v1/simulation/proposals", json=_proposal_payload(finding_ids))
    second = operator.post("/api/v1/simulation/proposals", json=_proposal_payload(finding_ids))

    assert first.status_code == 201
    assert second.status_code == 409


def test_operator_cannot_approve_a_proposal(operator, admin):
    run = _run_and_evaluate(operator)
    analysis = operator.post(f"/api/v1/simulation/runs/{run['id']}/analyze").get_json()["data"]
    # rubric-v3 换代：mock 零披露只产 hypothesis（D1-01 的 expected_missing
    # 「永远 confirmed」链路正是本轮剔除的假发现机制）⇒ 走 L-C 裁定面显式 confirm。
    for item in analysis["items"]:
        resp = admin.post(
            f"/api/v1/simulation/findings/{item['id']}/adjudicate",
            json={"action": "confirm", "note": "夹具裁定：rubric-v3 换代"},
        )
        assert resp.status_code == 200, resp.get_json()
    finding_ids = [item["id"] for item in analysis["items"]]
    proposal = operator.post(
        "/api/v1/simulation/proposals", json=_proposal_payload(finding_ids)
    ).get_json()["data"]

    response = operator.post(
        f"/api/v1/simulation/proposals/{proposal['id']}/decide",
        json={"approve": True, "password": INITIAL_PASSWORD, "note": "同意"},
    )

    assert response.status_code == 403


def test_approval_requires_password_and_reason(lead, admin):
    run = _run_and_evaluate(lead)
    analysis = lead.post(f"/api/v1/simulation/runs/{run['id']}/analyze").get_json()["data"]
    # rubric-v3 换代：mock 零披露只产 hypothesis（D1-01 的 expected_missing
    # 「永远 confirmed」链路正是本轮剔除的假发现机制）⇒ 走 L-C 裁定面显式 confirm。
    for item in analysis["items"]:
        resp = admin.post(
            f"/api/v1/simulation/findings/{item['id']}/adjudicate",
            json={"action": "confirm", "note": "夹具裁定：rubric-v3 换代"},
        )
        assert resp.status_code == 200, resp.get_json()
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


def test_approval_ends_at_approved_without_publishing(lead, admin):
    run = _run_and_evaluate(lead)
    analysis = lead.post(f"/api/v1/simulation/runs/{run['id']}/analyze").get_json()["data"]
    # rubric-v3 换代：mock 零披露只产 hypothesis（D1-01 的 expected_missing
    # 「永远 confirmed」链路正是本轮剔除的假发现机制）⇒ 走 L-C 裁定面显式 confirm。
    for item in analysis["items"]:
        resp = admin.post(
            f"/api/v1/simulation/findings/{item['id']}/adjudicate",
            json={"action": "confirm", "note": "夹具裁定：rubric-v3 换代"},
        )
        assert resp.status_code == 200, resp.get_json()
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
    # 审批 ≠ 发布：decide 后停 approved（release=None）；发布须另走
    # release_channel 受控通道（admin＋密码＋回归计划在案）。
    assert data["status"] == "approved"
    assert data["release"] is None


# ---------------------------------------------------------------------------
# 「只许经发布通道写」的静态钉（N4 改语义，不删钉）
# ---------------------------------------------------------------------------


def test_proposal_table_has_no_publish_or_apply_column():
    """发布状态只许住 ``release_json`` 一列；散列发布列禁名单原样保留（N4）。"""
    columns = {column.name for column in ImprovementProposal.__table__.columns}
    assert not columns & {
        "published_at",
        "published_by_user_id",
        "publish_status",
        "applied_at",
        "applied_by_user_id",
        "apply_status",
    }
    assert {"status", "target_json", "current_version", "proposed_version", "release_json"} <= columns


def test_improvement_proposal_reference_surface_is_closed():
    """全仓 ``ImprovementProposal`` 引用面 ⊆ {models, improvement_service,
    release_channel}（N4 新语义：生产模块要动提案只能走发布通道单点）。

    任何新文件出现提案引用（直接构造/写状态/绕开通道）即转红。
    """
    package_root = SERVER_ROOT / "src" / "fde_api"
    allowed = {
        Path("simulation") / "models.py",
        Path("simulation") / "improvement_service.py",
        Path("simulation") / "release_channel.py",
        # 回归验证面只读消费（G6：跑回归时读提案 override_json / candidate_payload_json，非状态写）。
        Path("simulation") / "regression_service.py",
    }
    # 学习闭环 2.0 L5：三载体表 AgentLesson / PromptOverlay 的 source_proposal_id
    # 外键声明指向 "improvement_proposals.id"（仅限 ORM ForeignKey 字面量，禁导入/构造 ImprovementProposal）。
    fk_only_allowed = {
        Path("agents") / "models.py",
        Path("workbench") / "models.py",
    }
    offenders: list[str] = []
    for path in sorted(package_root.rglob("*.py")):
        relative = path.relative_to(package_root)
        text = path.read_text(encoding="utf-8", errors="replace")
        if relative in fk_only_allowed:
            assert "ImprovementProposal" not in text, f"{relative} 仅允许表名 FK 声明，不得引用 ImprovementProposal 类"
            continue
        if "improvement_proposals" in text or "ImprovementProposal" in text:
            if relative not in allowed:
                offenders.append(relative.as_posix())
    assert offenders == [], f"提案引用面泄漏（要动提案只能经 release_channel）：{offenders}"


def test_release_functions_live_only_in_release_channel_with_gates():
    """发布/回滚/工单函数只许住 ``release_channel``，且该模块必须带密码闸
    ＋admin 判定（N4 新语义：发布闸有测试钉——比照 decide 密码确认范式）。"""
    package_root = SERVER_ROOT / "src" / "fde_api"
    forbidden_names = {"release_proposal", "rollback_release", "create_review_ticket"}
    owners: dict[str, set[str]] = {}
    for path in sorted(package_root.rglob("*.py")):
        relative = path.relative_to(package_root)
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        hits = {
            node.name
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name in forbidden_names
        }
        if hits:
            owners[relative.as_posix()] = hits
    # 服务层三函数必须全住 release_channel；routes.py 只许有两条薄路由包装
    # （无工单路由——工单只经 CLI 评估器产生）。
    assert set(owners) <= {"simulation/release_channel.py", "simulation/routes.py"}, owners
    assert owners["simulation/release_channel.py"] == forbidden_names
    assert "create_review_ticket" not in owners.get("simulation/routes.py", set())
    channel_text = (package_root / "simulation" / "release_channel.py").read_text(
        encoding="utf-8"
    )
    # 发布/回滚闸的源级证据：密码确认 + admin 判定必须在通道模块内。
    assert "verify_password" in channel_text
    assert 'role != "admin"' in channel_text
