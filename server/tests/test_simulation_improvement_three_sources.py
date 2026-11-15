"""analyze_run 三源化（学习闭环 2.0 L4 断点②）。

钉住（设计稿 §2.2 / §4-L4 验收 U1/U2/U3）：

- **U1 L-C confirmed 分流**：人工终裁最新行（created_at 收敛）⇒ ``FA-C1``
  confirmed 发现 ⇒ 可解锁提案；note 全文先过答案句黑名单（终裁人看过
  reference，整句抄答案 ⇒ description 洗刷＋``note_redacted`` 留痕）。
- **U2 L-B likely 分流**：查询钉 ``layer=="model" AND evaluator_id==
  "model:server"``（stub 替身行不进）＋``verdict!="unavailable"`` 二道 ⇒
  低分判据产 ``likely`` 发现——单独提案 409（不解锁）；模型自写
  evidence/reason 不采信（evidence_refs 恒空、description 只含判据键与分数）。
- **U3 幂等**：重跑分析不增殖（三源各挂各的评估行，(evaluation_id, code)
  唯一约束分流）；多 human 行只按最新行产发现。
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
from fde_api.simulation.failure_analyzer import (
    analyze_human_layer,
    analyze_model_layer,
    scrub_answer_sentences,
)
from fde_api.simulation.models import (
    ImprovementProposal,
    SimulationEvaluation,
    SimulationFinding,
    SimulationRun,
    SimulationScenario,
    SimulationTrace,
    SimulationActor,
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


def _make_client(client, db_session, settings, *, role: str) -> _Client:
    user = User(
        username=f"sim.3s.{role}.{uuid4().hex[:8]}",
        display_name="Three-source user",
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


def _scenario_payload(case_code: str = "CASE-3S-001", split: str = "train"):
    return {
        "name": "三源化测试案例",
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
                        "fact_id": "S-F1",
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
                "must_identify": ["知识采集前置是隐含前提"],
                "must_avoid": ["以模型精度为核心承诺"],
                "must_produce": ["知识采集方案"],
            },
        },
    }


def _run_and_evaluate(operator, *, split: str = "train") -> dict:
    scenario = operator.post(
        "/api/v1/simulation/scenarios", json=_scenario_payload(split=split)
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
    return run


def _add_evaluation(
    run_id: str,
    *,
    layer: str,
    evaluator_id: str,
    verdict: str = "fail",
    criteria: list | None = None,
    note: str | None = None,
    rubric_version: str = "rubric-v1",
) -> str:
    row = SimulationEvaluation(
        run_id=run_id,
        layer=layer,
        evaluator_id=evaluator_id,
        mode="server" if evaluator_id.startswith("model:") else "manual",
        rubric_version=rubric_version,
        scores_json={"criteria": criteria or []},
        hard_failures_json=[],
        total_score=0.3,
        verdict=verdict,
        unverified_ratio=0.0,
        evidence_refs_json=[],
        note=note,
    )
    with db.session() as session:
        session.add(row)
        session.commit()
        return row.id


_LOW_CRITERIA = [
    {
        "key": "D1-01",
        "dimension": "D1",
        "title": "识别出客户真实问题",
        "score": 0.1,
        "evidence_refs": [{"kind": "expected_missing", "text": "知识采集前置是隐含前提"}],
        "reason": "未识别出必须识别的知识采集前置是隐含前提",
    }
]


# ---------------------------------------------------------------------------
# 纯函数层
# ---------------------------------------------------------------------------


def test_scrub_answer_sentences_replaces_rubric_verbatim():
    blacklist = ("知识采集前置是隐含前提", "以模型精度为核心承诺")
    note = "终裁不通过：顾问未识别出知识采集前置是隐含前提，方案方向跑偏。"
    scrubbed, hits = scrub_answer_sentences(note, blacklist)
    assert "知识采集前置是隐含前提" not in scrubbed
    assert "［答案句已洗刷］" in scrubbed
    assert hits == ["知识采集前置是隐含前提"]
    # 过短句子不拦（误伤面）
    assert scrub_answer_sentences("含六字内短句", ("短句",)) == ("含六字内短句", [])


def test_analyze_model_layer_likely_and_no_evidence_adoption():
    findings = analyze_model_layer(evaluation={"scores": {"criteria": _LOW_CRITERIA}})
    assert len(findings) == 1
    finding = findings[0]
    assert finding.code == "FA-01"
    assert finding.root_causes[0].confidence == "likely"
    # 模型自写 evidence/reason 不采信：evidence_refs 恒空、description 无 reason 原文
    assert finding.evidence_refs == ()
    assert "未识别出必须识别的" not in finding.description
    assert finding.detail["source"] == "model_server"


def test_analyze_human_layer_confirmed_and_blacklist():
    findings = analyze_human_layer(
        evaluation={"verdict": "fail", "note": "终裁不通过：漏了知识采集前置是隐含前提。", "hard_failures": []},
        blacklist=("知识采集前置是隐含前提",),
    )
    assert [item.code for item in findings] == ["FA-C1"]
    finding = findings[0]
    assert finding.root_causes[0].confidence == "confirmed"
    assert "知识采集前置是隐含前提" not in finding.description
    assert finding.detail["note_redacted"] is True
    # pass/conditional 不产发现
    assert (
        analyze_human_layer(evaluation={"verdict": "pass", "note": "ok", "hard_failures": []})
        == []
    )
    # 硬性失败映射 confirmed
    hard = analyze_human_layer(
        evaluation={"verdict": "hard_fail", "note": "越界", "hard_failures": [{"code": "HF-07", "title": "越界"}]},
        blacklist=(),
    )
    codes = {item.code for item in hard}
    assert "FA-08" in codes and "FA-C1" in codes


# ---------------------------------------------------------------------------
# analyze_run 三源接线
# ---------------------------------------------------------------------------


def test_lb_pins_model_server_and_excludes_stub(operator):
    run = _run_and_evaluate(operator)
    # stub 行不得被当真模型层（evaluate 缺省落 model:stub 行；再插一条带低分
    # 判据的 stub 行——若查询只按 layer=='model' 过滤（v1 式）必误当真模型层）
    _add_evaluation(
        run["id"],
        layer="model",
        evaluator_id="model:stub",
        verdict="fail",
        criteria=_LOW_CRITERIA,
        rubric_version="rubric-v0.9-stub",
    )
    data = operator.post(f"/api/v1/simulation/runs/{run['id']}/analyze").get_json()["data"]
    sources = {item["detail"].get("source") for item in data["items"]}
    assert "model_server" not in sources

    # server 行（verdict=unavailable）二道过滤
    _add_evaluation(
        run["id"],
        layer="model",
        evaluator_id="model:server",
        verdict="unavailable",
        criteria=_LOW_CRITERIA,
        rubric_version="rubric-v0.9-unavailable",
    )
    data = operator.post(f"/api/v1/simulation/runs/{run['id']}/analyze").get_json()["data"]
    sources = {item["detail"].get("source") for item in data["items"]}
    assert "model_server" not in sources

    # 真模型层（fail＋低分）⇒ likely 发现挂 model 评估行
    _add_evaluation(run["id"], layer="model", evaluator_id="model:server", verdict="fail", criteria=_LOW_CRITERIA)
    data = operator.post(f"/api/v1/simulation/runs/{run['id']}/analyze").get_json()["data"]
    lb = [item for item in data["items"] if item["detail"].get("source") == "model_server"]
    assert lb and lb[0]["code"] == "FA-01"
    assert all(cause["confidence"] == "likely" for cause in lb[0]["root_causes"])
    assert lb[0]["evidence_refs"] == []


def test_lc_latest_human_row_generates_confirmed_and_unlocks(operator, lead):
    run = _run_and_evaluate(operator)
    _add_evaluation(
        run["id"],
        layer="human",
        evaluator_id="human:u1",
        verdict="fail",
        note="终裁不通过：整段抄了知识采集前置是隐含前提这句参考答案。",
    )
    data = operator.post(f"/api/v1/simulation/runs/{run['id']}/analyze").get_json()["data"]
    lc = [item for item in data["items"] if item["code"] == "FA-C1"]
    assert lc and lc[0]["detail"]["source"] == "human"
    assert lc[0]["detail"]["note_redacted"] is True
    assert "知识采集前置是隐含前提" not in lc[0]["description"]
    assert all(cause["confidence"] == "confirmed" for cause in lc[0]["root_causes"])

    # L-C confirmed 可解锁提案（既有 confirmed 闸不扩不动）
    finding_id = lc[0]["id"]
    response = lead.post(
        "/api/v1/simulation/proposals",
        json={
            "finding_ids": [finding_id],
            "target": {"kind": "rule", "ref": "acceptance/dimension-1"},
            "change_summary": "按人工终裁补验收口径",
        },
    )
    assert response.status_code == 201, response.get_json()
    payload = response.get_json()["data"]
    assert payload["status"] == "draft"
    assert payload["candidate_payload"] == {}


def test_lb_likely_alone_cannot_create_proposal(operator, lead):
    run = _run_and_evaluate(operator)
    _add_evaluation(run["id"], layer="model", evaluator_id="model:server", verdict="fail", criteria=_LOW_CRITERIA)
    data = operator.post(f"/api/v1/simulation/runs/{run['id']}/analyze").get_json()["data"]
    lb = [item for item in data["items"] if item["detail"].get("source") == "model_server"]
    assert lb
    response = lead.post(
        "/api/v1/simulation/proposals",
        json={
            "finding_ids": [lb[0]["id"]],
            "target": {"kind": "rule", "ref": "acceptance/dimension-1"},
            "change_summary": "按模型层意见补验收口径",
        },
    )
    assert response.status_code == 409  # 只有 confirmed 根因可生成改进提案


def test_analyze_idempotent_and_latest_human_wins(operator):
    run = _run_and_evaluate(operator)
    first_eval = _add_evaluation(
        run["id"], layer="human", evaluator_id="human:u1", verdict="fail", note="第一轮终裁不通过"
    )
    data1 = operator.post(f"/api/v1/simulation/runs/{run['id']}/analyze").get_json()["data"]
    data2 = operator.post(f"/api/v1/simulation/runs/{run['id']}/analyze").get_json()["data"]
    assert len(data1["items"]) == len(data2["items"])  # U3：重跑不增殖
    fa_c1_rows = [item for item in data2["items"] if item["code"] == "FA-C1"]
    assert len({item["evaluation_id"] for item in fa_c1_rows}) == 1
    assert fa_c1_rows[0]["evaluation_id"] == first_eval

    # 更晚的人工行 ⇒ 新 FA-C1 挂最新行（收敛语义）；旧行发现留痕不删
    second_eval = _add_evaluation(
        run["id"], layer="human", evaluator_id="human:u2", verdict="fail", note="第二轮终裁仍不通过"
    )
    data3 = operator.post(f"/api/v1/simulation/runs/{run['id']}/analyze").get_json()["data"]
    fa_c1_rows = [item for item in data3["items"] if item["code"] == "FA-C1"]
    evaluation_ids = {item["evaluation_id"] for item in fa_c1_rows}
    assert second_eval in evaluation_ids
    data4 = operator.post(f"/api/v1/simulation/runs/{run['id']}/analyze").get_json()["data"]
    assert len(data4["items"]) == len(data3["items"])  # 再跑仍不增殖
