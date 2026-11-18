# -*- coding: utf-8 -*-
"""条款③写面：L-C 再终裁收敛口径（supersede）＋发现人工裁定（adjudicate）。

钉住（设计稿 v1 §2.1/§2.2，四拍板 2026-11-18：查询口径收敛／detail_json 追加／
不加事件／W1+W2 实施）：
①再终裁（新增 human 评估行）后，旧 human 行派生 findings 失効——查询口径
  收敛：draft-ai 投影过滤／create_proposal 409 finding_superseded／list 投影
  superseded=true；非 human 层（deterministic/model）发现恒有效；
②adjudicate 单向状态机 open→confirmed|rejected（幂等 409
  finding_already_adjudicated＋note 必填＋角色闸 admin/lead＋
  detail_json.adjudications[] 留痕；不落 operation_event）；
③confirmed 双轨解锁：归因 confidence=confirmed 或人工裁定 status=confirmed
  （L-B likely 发现的单点人工确认正道）。
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from uuid import uuid4

import pytest
from sqlalchemy import delete, select

from conftest import INITIAL_PASSWORD
from fde_api.auth.models import User
from fde_api.auth.passwords import hash_password
from fde_api.auth.tokens import issue_access_token
from fde_api.simulation import improvement_draft
from fde_api.simulation.models import (
    ImprovementProposal,
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


def _make_client(client, db_session, settings, *, role: str, tag: str = "lc") -> _Client:
    user = User(
        username=f"sim.{tag}.{role}.{uuid4().hex[:8]}",
        display_name="L-C adjudicator",
        role=role,
        password_hash=hash_password(INITIAL_PASSWORD),
        must_change_password=False,
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()
    return _Client(client, user, {"Authorization": f"Bearer {issue_access_token(user, settings)}"})


@pytest.fixture
def admin(client, db_session, settings):
    return _make_client(client, db_session, settings, role="admin")


@pytest.fixture
def engineer(client, db_session, settings):
    return _make_client(client, db_session, settings, role="fde_engineer")


@pytest.fixture(autouse=True)
def _clean_simulation(db_session):
    yield
    db_session.rollback()
    db_session.execute(delete(SimulationTrace))
    db_session.execute(delete(SimulationFinding))
    db_session.execute(delete(SimulationEvaluation))
    db_session.execute(delete(SimulationRun))
    db_session.execute(delete(SimulationScenario))
    db_session.execute(delete(ImprovementProposal))
    db_session.commit()


def _scenario_payload(case_code: str) -> dict:
    return {
        "name": f"改判案例 {case_code}",
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
                        "fact_id": f"{case_code}-F1",
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


@dataclass(frozen=True)
class _Run:
    scenario_id: str
    run_id: str
    human_row_ids: list[str]
    findings_by_owner: dict[str, list[dict]]


def _make_run_with_two_readjudications(admin: _Client) -> _Run:
    """一个 train run：评估 → 终裁 H1 → 分析 → 再终裁 H2 → 再分析。"""
    scenario = admin.post(
        "/api/v1/simulation/scenarios", json=_scenario_payload("CASE-LCRJ")
    ).get_json()["data"]
    run = admin.post(
        "/api/v1/simulation/runs",
        json={
            "scenario_id": scenario["id"],
            "adapter_mode": "mock",
            "execute": True,
            "config": {"max_rounds": 4, "probe_quality": 0.0},
        },
    ).get_json()["data"]
    assert admin.post(f"/api/v1/simulation/runs/{run['id']}/evaluate").status_code in (200, 201)

    human_row_ids: list[str] = []
    for verdict, score, note in (
        ("fail", 0.4, "第一轮终裁：访谈不足判定不达标"),
        ("fail", 0.5, "第二轮终裁（改判）：仍不达标，但根因指向追问方式而非次数"),
    ):
        resp = admin.post(
            f"/api/v1/simulation/runs/{run['id']}/evaluation/human",
            json={"verdict": verdict, "total_score": score, "note": note},
        )
        assert resp.status_code == 201, resp.get_json()
        human_row_ids.append(resp.get_json()["data"]["id"])
        analyze_resp = admin.post(f"/api/v1/simulation/runs/{run['id']}/analyze")
        assert analyze_resp.status_code == 200, analyze_resp.get_json()

    listed = admin.get(f"/api/v1/simulation/findings?run_id={run['id']}").get_json()["data"]
    findings_by_owner: dict[str, list[dict]] = {}
    for item in listed["items"]:
        findings_by_owner.setdefault(str(item["evaluation_id"]), []).append(item)
    return _Run(scenario["id"], run["id"], human_row_ids, findings_by_owner)


def _finding_for_owner(run: _Run, owner_index: int) -> dict:
    owner_id = run.human_row_ids[owner_index]
    items = run.findings_by_owner.get(owner_id) or []
    assert items, f"human 行 {owner_index} 应派生至少一条发现"
    return items[0]


# ---------------------------------------------------------------------------
# ① supersede：再终裁收敛口径（查询口径，零写面零迁移）
# ---------------------------------------------------------------------------


def test_readjudication_supersedes_old_human_findings_only(admin):
    """旧 human 行派生发现 superseded=true；现行 human 行派生与非 human 层发现
    恒有效——查询口径收敛，旧行零改写。"""
    run = _make_run_with_two_readjudications(admin)
    old_finding = _finding_for_owner(run, 0)
    new_finding = _finding_for_owner(run, 1)

    listed = admin.get(f"/api/v1/simulation/findings?run_id={run.run_id}").get_json()["data"]
    flags = {item["id"]: item["superseded"] for item in listed["items"]}
    assert flags[old_finding["id"]] is True
    assert flags[new_finding["id"]] is False
    # 非 human 层发现（deterministic 派生）不受再终裁影响
    non_human = [
        item
        for item in listed["items"]
        if item["evaluation_id"] not in run.human_row_ids
    ]
    assert non_human, "运行应至少有一条非 human 层发现（规则层归因）"
    assert all(item["superseded"] is False for item in non_human)
    # 旧行本体零改写：status 仍 open（收敛是查询口径不是写面）
    with admin.client.application.app_context():
        from fde_api.extensions import db

        from fde_api.simulation.models import SimulationFinding as Row

        with db.session() as session:
            row = session.get(Row, old_finding["id"])
            assert row is not None
            assert row.status == "open"


def test_draft_ai_filters_superseded_and_rejects_all_superseded(admin, monkeypatch):
    """draft-ai 消费点：混合输入投影过滤（只蒸馏现行发现）；全被取代 ⇒ 409
    finding_superseded（发生在 AI 调用之前——零模型消耗）。"""
    run = _make_run_with_two_readjudications(admin)
    old_finding = _finding_for_owner(run, 0)
    new_finding = _finding_for_owner(run, 1)

    calls: list[str] = []
    expected_code = str(new_finding["code"])

    def fake_execute(**kwargs):
        calls.append(str(kwargs.get("prompt")))
        return json.dumps(
            {
                "groups": [
                    {
                        "code": expected_code,
                        "lesson_entry": {
                            "text": "终裁不通过类失败先补访谈深度再谈方案。",
                            "anti_pattern": "浅访谈直接出方案",
                            "actionable_rule": "隐藏事实未披露过半不出方案",
                            "capability_tags": ["agent.module.presales"],
                        },
                        "skill_version_draft": {"title": "追问清单", "instructions": "按清单追问。"},
                        "prompt_overlay_fragment": {
                            "purpose_key": "simulation_workbench",
                            "fragment": "访谈阶段须逐项核对跨系统主键与物料编码。",
                        },
                    }
                ]
            },
            ensure_ascii=False,
        )

    monkeypatch.setattr(improvement_draft, "execute_ai_prompt", fake_execute)

    # 混合输入：superseded 被过滤，只蒸馏现行发现
    mixed = admin.post(
        "/api/v1/simulation/findings/draft-ai",
        json={"finding_ids": [old_finding["id"], new_finding["id"]]},
    )
    assert mixed.status_code == 200, mixed.get_json()
    assert len(calls) == 1
    start = calls[0].index("[")
    end = calls[0].index("]", start)
    projected = json.loads(calls[0][start : end + 1])
    assert len(projected) == 1, "被取代的发现不得进蒸馏投影"

    # 全部被取代 ⇒ 409（AI 调用前拦截）
    solo = admin.post(
        "/api/v1/simulation/findings/draft-ai", json={"finding_ids": [old_finding["id"]]}
    )
    assert solo.status_code == 409
    assert solo.get_json()["error"]["code"] == "finding_superseded"
    assert len(calls) == 1, "409 拦截不得触发 AI 调用"


def test_create_proposal_rejects_superseded_finding(admin):
    """create_proposal 消费点：引用被取代发现建提案 ⇒ 409 finding_superseded。"""
    run = _make_run_with_two_readjudications(admin)
    old_finding = _finding_for_owner(run, 0)

    response = admin.post(
        "/api/v1/simulation/proposals",
        json={
            "finding_ids": [old_finding["id"]],
            "target": {"kind": "prompt", "ref": "presurvey.interview.prompt"},
            "change_summary": "用旧裁决建提案",
            "current_version": "v1",
            "proposed_version": "v2",
        },
    )
    assert response.status_code == 409
    assert response.get_json()["error"]["code"] == "finding_superseded"


# ---------------------------------------------------------------------------
# ② adjudicate：单向状态机＋detail_json 追加留痕（拍板②③）
# ---------------------------------------------------------------------------


def _insert_open_finding(db_session, run_id: str, evaluation_id: str, *, code: str) -> str:
    row = SimulationFinding(
        run_id=run_id,
        evaluation_id=evaluation_id,
        code=code,
        title="多厂物料码不一致（likely）",
        severity="medium",
        dimension="D1",
        description="模型层判据 M-2 得分 0.30 ⇒ 待人工确认",
        evidence_refs_json=[],
        root_causes_json=[
            {"code": "访谈追问不足", "title": "访谈追问不足", "confidence": "likely", "analysis": "独立第二意见，待人工复核。", "evidence_refs": []}
        ],
        status="open",
        detail_json={"criterion": "M-2", "score": 0.3, "source": "model_server"},
    )
    db_session.add(row)
    db_session.commit()
    return str(row.id)


def test_adjudicate_confirm_then_one_way_lock(admin, db_session):
    """confirm：open→confirmed＋adjudications 追加留痕；重复裁定 ⇒ 409
    finding_already_adjudicated（单向不可回迁）。"""
    run = _make_run_with_two_readjudications(admin)
    eval_id = db_session.scalar(
        select(SimulationEvaluation.id).where(SimulationEvaluation.run_id == run.run_id)
    )
    finding_id = _insert_open_finding(db_session, run.run_id, str(eval_id), code="FA-90")

    confirm = admin.post(
        f"/api/v1/simulation/findings/{finding_id}/adjudicate",
        json={"action": "confirm", "note": "人工核对原文：主键缺失属实，确认根因。"},
    )
    assert confirm.status_code == 200, confirm.get_json()
    data = confirm.get_json()["data"]
    assert data["status"] == "confirmed"
    assert data["detail"]["adjudications"][0]["action"] == "confirm"
    assert data["detail"]["adjudications"][0]["note"].startswith("人工核对原文")

    again = admin.post(
        f"/api/v1/simulation/findings/{finding_id}/adjudicate",
        json={"action": "reject", "note": "想改判"},
    )
    assert again.status_code == 409
    assert again.get_json()["error"]["code"] == "finding_already_adjudicated"


def test_adjudicate_reject_path(admin, db_session):
    """reject：open→rejected（发现退出有效集，提案引用被拒）。"""
    run = _make_run_with_two_readjudications(admin)
    eval_id = db_session.scalar(
        select(SimulationEvaluation.id).where(SimulationEvaluation.run_id == run.run_id)
    )
    finding_id = _insert_open_finding(db_session, run.run_id, str(eval_id), code="FA-91")

    reject = admin.post(
        f"/api/v1/simulation/findings/{finding_id}/adjudicate",
        json={"action": "reject", "note": "人工核对原文：该判据不成立，驳回。"},
    )
    assert reject.status_code == 200
    assert reject.get_json()["data"]["status"] == "rejected"

    proposal = admin.post(
        "/api/v1/simulation/proposals",
        json={
            "finding_ids": [finding_id],
            "target": {"kind": "prompt", "ref": "presurvey.interview.prompt"},
            "change_summary": "用被驳回发现建提案",
            "current_version": "v1",
            "proposed_version": "v2",
        },
    )
    assert proposal.status_code == 409


def test_adjudicate_requires_note_and_role(admin, engineer, db_session):
    """note 必填（400）＋角色闸（fde_engineer 403——终裁同尺）。"""
    run = _make_run_with_two_readjudications(admin)
    eval_id = db_session.scalar(
        select(SimulationEvaluation.id).where(SimulationEvaluation.run_id == run.run_id)
    )
    finding_id = _insert_open_finding(db_session, run.run_id, str(eval_id), code="FA-92")

    no_note = admin.post(
        f"/api/v1/simulation/findings/{finding_id}/adjudicate",
        json={"action": "confirm"},
    )
    assert no_note.status_code == 400
    assert no_note.get_json()["error"]["code"] == "invalid_request"

    forbidden = engineer.post(
        f"/api/v1/simulation/findings/{finding_id}/adjudicate",
        json={"action": "confirm", "note": "工程师想确认"},
    )
    assert forbidden.status_code == 403
    assert forbidden.get_json()["error"]["code"] == "forbidden"


# ---------------------------------------------------------------------------
# ③ confirmed 双轨解锁：人工裁定 status=confirmed ＝ L-B likely 的建案正道
# ---------------------------------------------------------------------------


def test_status_confirmed_unlocks_proposal_for_likely_root_cause(admin, db_session):
    """root_causes confidence=likely 但人工裁定 status=confirmed ⇒ create_proposal
    放行（双轨判据：归因快照 OR 人工裁定）。"""
    run = _make_run_with_two_readjudications(admin)
    eval_id = db_session.scalar(
        select(SimulationEvaluation.id).where(SimulationEvaluation.run_id == run.run_id)
    )
    finding_id = _insert_open_finding(db_session, run.run_id, str(eval_id), code="FA-93")

    blocked = admin.post(
        "/api/v1/simulation/proposals",
        json={
            "finding_ids": [finding_id],
            "target": {"kind": "prompt", "ref": "presurvey.interview.prompt"},
            "change_summary": "裁定前：likely 不放行",
            "current_version": "v1",
            "proposed_version": "v2",
        },
    )
    assert blocked.status_code == 409

    confirm = admin.post(
        f"/api/v1/simulation/findings/{finding_id}/adjudicate",
        json={"action": "confirm", "note": "人工核对原文属实，单点确认。"},
    )
    assert confirm.status_code == 200

    unlocked = admin.post(
        "/api/v1/simulation/proposals",
        json={
            "finding_ids": [finding_id],
            "target": {"kind": "prompt", "ref": "presurvey.interview.prompt"},
            "change_summary": "人工确认后建案",
            "current_version": "v1",
            "proposed_version": "v2",
            "override_json": {"run_config": {"probe_quality": 1.0}},
        },
    )
    assert unlocked.status_code == 201, unlocked.get_json()
