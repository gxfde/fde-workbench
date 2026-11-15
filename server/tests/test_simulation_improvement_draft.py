"""AI 蒸馏起草（学习闭环 2.0 L4 断点③：``POST /simulation/findings/draft-ai``）。

钉住（设计稿 §2.3 / §4-L4 验收）：

1. **静态钉**：蒸馏器模块 AST import ⊆ 白名单（禁 scenarios.loader /
   reference 面——蒸馏器在物理上没有装载参考答案的 import 路径）。
2. **输入面动态卡**：蒸馏 payload（提示词）只含允许名单键
   ``{code, dimension, severity, score, description}``——无 evidence_refs /
   reason / note 键，且键集 ∩ ``ANSWER_SIDE_KEYS`` == ∅（键清单从
   ``schemas.py`` 单一真身取）。
3. **输出面动态卡**：返件夹带答案侧键 ⇒ 重试一次仍违 ⇒ 409
   ``ai_draft_contract_failed`` 整批丢弃。
4. **返件零落库**：起草全程业务域表零写入（提案/发现行数不变）。
5. **train split 过滤**：regression/blind 集发现 ⇒ 409。
6. **指纹 payload_sha256**：同 findings 同 target 不同 candidate_payload ⇒
   两案并存（不被旧指纹 409 挡死）；同 payload 重复提交 ⇒ 409 幂等保留。
7. **candidate_payload 形状闸**：未知载体类型/超长 text/fragment ⇒ 400。
"""
from __future__ import annotations

import ast
import json
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
from fde_api.simulation import improvement_draft
from fde_api.simulation.models import (
    ImprovementProposal,
    SimulationEvaluation,
    SimulationFinding,
    SimulationRun,
    SimulationScenario,
    SimulationTrace,
    SimulationActor,
)
from fde_api.simulation.schemas import ANSWER_SIDE_KEYS


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
        username=f"sim.dr.{role}.{uuid4().hex[:8]}",
        display_name="Draft user",
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


def _scenario_payload(case_code: str = "CASE-DR-001", split: str = "train"):
    return {
        "name": "蒸馏测试案例",
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
                        "fact_id": "D-F1",
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


def _make_findings(operator, *, split: str = "train") -> list[str]:
    """造 confirmed 发现（走 L-C 真实链：跑题→评估→人工终裁 fail→analyze）。"""
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
    with db.session() as session:
        session.add(
            SimulationEvaluation(
                run_id=run["id"],
                layer="human",
                evaluator_id="human:drafter",
                mode="manual",
                rubric_version="rubric-v1",
                scores_json={"criteria": []},
                hard_failures_json=[],
                total_score=0.2,
                verdict="fail",
                unverified_ratio=0.0,
                evidence_refs_json=[],
                note="终裁不通过：访谈与方案都浅。",
            )
        )
        session.commit()
    data = operator.post(f"/api/v1/simulation/runs/{run['id']}/analyze").get_json()["data"]
    return [item["id"] for item in data["items"]]


class _ScriptAI:
    """替身 execute_ai_prompt：按脚本返件并记录提示词。"""

    def __init__(self, script: list) -> None:
        self._script = list(script)
        self.prompts: list[str] = []

    def __call__(self, **kwargs) -> str:
        self.prompts.append(str(kwargs.get("prompt") or ""))
        item = self._script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def _good_draft(code: str = "FA-C1") -> dict:
    return {
        "groups": [
            {
                "code": code,
                "lesson_entry": {
                    "text": "终裁不通过类失败先补访谈深度再谈方案。",
                    "anti_pattern": "浅访谈直接出方案",
                    "actionable_rule": "隐藏事实未披露过半不出方案",
                    "capability_tags": ["agent.module.presales"],
                },
                "skill_version_draft": {
                    "title": "访谈深度自检技能",
                    "instructions": "每轮访谈后核对披露事实数，未达半数不出方案。",
                },
                "prompt_overlay_fragment": {
                    "purpose_key": "simulation_workbench",
                    "fragment": "未确认客户核心约束前不产出正式方案稿。",
                },
            }
        ]
    }


@pytest.fixture
def script_ai(monkeypatch):
    holder = {}

    def _install(script: list) -> _ScriptAI:
        ai = _ScriptAI(script)
        monkeypatch.setattr(improvement_draft, "execute_ai_prompt", ai)
        holder["ai"] = ai
        return ai

    return _install


# ---------------------------------------------------------------------------
# 静态钉：蒸馏器 import ⊆ 白名单
# ---------------------------------------------------------------------------


def test_distiller_imports_within_whitelist():
    """蒸馏器模块 AST import ⊆ 白名单（禁 scenarios.loader / reference 面）。"""
    module_path = SERVER_ROOT / "src" / "fde_api" / "simulation" / "improvement_draft.py"
    tree = ast.parse(Path(module_path).read_text(encoding="utf-8"))
    targets: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            targets.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            targets.add(node.module)
    allowed_prefixes = (
        "__future__",
        "typing",
        "json",
        "hashlib",
        "re",
        "sqlalchemy",
        "fde_api.ai.prompt_registry",
        "fde_api.control.ai_server_client",
        "fde_api.extensions",
        "fde_api.guidance.enterprise_dict",
        "fde_api.guidance.redaction",
        "fde_api.simulation.models",
        "fde_api.simulation.schemas",
        "fde_api.simulation.service",
    )
    violations = sorted(target for target in targets if not target.startswith(allowed_prefixes))
    assert violations == [], f"蒸馏器出现白名单外 import：{violations}"
    # 显式禁入面（即便未来扩白名单也钉死）
    for forbidden in ("scenarios.loader", "scenarios.reference", "evaluator", "evaluation_prompt"):
        assert all(forbidden not in target for target in targets), forbidden


# ---------------------------------------------------------------------------
# 输入面污染卡（允许名单投影）
# ---------------------------------------------------------------------------


def test_draft_input_projection_allowlist_only(operator, script_ai):
    finding_ids = _make_findings(operator)
    ai = script_ai([json.dumps(_good_draft("FA-C1"), ensure_ascii=False)])
    response = operator.post(
        "/api/v1/simulation/findings/draft-ai", json={"finding_ids": finding_ids}
    )
    assert response.status_code == 200, response.get_json()
    assert len(ai.prompts) == 1
    prompt = ai.prompts[0]
    # 允许名单投影：提示词中的发现对象只含五字段
    start = prompt.index("[")
    end = prompt.index("]", start)
    projected = json.loads(prompt[start : end + 1])
    assert projected, "提示词中应含发现投影清单"
    allowed = set(improvement_draft.FINDING_PROJECTION_KEYS)
    for item in projected:
        assert set(item) == allowed, set(item) - allowed
    # 禁入字段物理不在
    for banned in ("evidence_refs", "reason", "note", "root_causes"):
        assert banned not in prompt
    # 答案侧键零交集（键清单从 schemas 单一真身取）
    assert set(item) & ANSWER_SIDE_KEYS == set()


def test_draft_train_split_only(operator, script_ai):
    finding_ids = _make_findings(operator, split="regression")
    script_ai([json.dumps(_good_draft())])
    response = operator.post(
        "/api/v1/simulation/findings/draft-ai", json={"finding_ids": finding_ids}
    )
    assert response.status_code == 409
    assert response.get_json()["error"]["code"] == "conflict"


# ---------------------------------------------------------------------------
# 输出面污染卡＋契约重试
# ---------------------------------------------------------------------------


def test_draft_output_answer_key_smuggled_rejected_whole_batch(operator, script_ai):
    finding_ids = _make_findings(operator)
    smuggled = _good_draft("FA-C1")
    smuggled["groups"][0]["lesson_entry"]["must_identify"] = ["知识采集前置"]
    script_ai([json.dumps(smuggled), json.dumps(smuggled)])
    response = operator.post(
        "/api/v1/simulation/findings/draft-ai", json={"finding_ids": finding_ids}
    )
    assert response.status_code == 409
    assert response.get_json()["error"]["code"] == "ai_draft_contract_failed"


def test_draft_contract_retry_then_success(operator, script_ai):
    finding_ids = _make_findings(operator)
    ai = script_ai(["不是 JSON", json.dumps(_good_draft("FA-C1"), ensure_ascii=False)])
    response = operator.post(
        "/api/v1/simulation/findings/draft-ai", json={"finding_ids": finding_ids}
    )
    assert response.status_code == 200, response.get_json()
    assert len(ai.prompts) == 2  # 首调＋带拒因重试各一次
    assert "不合契约" in ai.prompts[1]
    data = response.get_json()["data"]
    assert data["zero_persistence"] is True
    assert data["payload_sha256"]
    group = data["draft"]["groups"][0]
    assert group["prompt_overlay_fragment"]["fragment"]


def test_draft_zero_business_writes(operator, script_ai):
    finding_ids = _make_findings(operator)
    script_ai([json.dumps(_good_draft("FA-C1"), ensure_ascii=False)])
    with db.session() as session:
        proposals_before = len(list(session.scalars(select(ImprovementProposal))))
        findings_before = len(list(session.scalars(select(SimulationFinding))))
    response = operator.post(
        "/api/v1/simulation/findings/draft-ai", json={"finding_ids": finding_ids}
    )
    assert response.status_code == 200
    with db.session() as session:
        assert len(list(session.scalars(select(ImprovementProposal)))) == proposals_before
        assert len(list(session.scalars(select(SimulationFinding)))) == findings_before


def test_draft_dict_failure_fail_closed(operator, script_ai, monkeypatch):
    finding_ids = _make_findings(operator)

    def _boom(value, *, project_code=""):
        raise improvement_draft.RedactionConfigError("dict down")

    monkeypatch.setattr(improvement_draft, "redact_text_detailed", _boom)
    script_ai([json.dumps(_good_draft("FA-C1"))])
    response = operator.post(
        "/api/v1/simulation/findings/draft-ai", json={"finding_ids": finding_ids}
    )
    assert response.status_code == 422
    assert response.get_json()["error"]["code"] == "pseudonym_dict_unavailable"


# ---------------------------------------------------------------------------
# 指纹 payload_sha256 与 candidate_payload 形状闸
# ---------------------------------------------------------------------------


def _create_proposal(lead, finding_ids: list[str], *, candidate_payload=None):
    payload = {
        "finding_ids": finding_ids,
        "target": {"kind": "rule", "ref": "acceptance/dimension-1"},
        "change_summary": "按蒸馏候选改进验收口径",
    }
    if candidate_payload is not None:
        payload["candidate_payload"] = candidate_payload
    return lead.post("/api/v1/simulation/proposals", json=payload)


_PAYLOAD_A = {
    "lesson_entry": {
        "text": "候选 A：终裁不通过类失败先补访谈深度。",
        "anti_pattern": "浅访谈直接出方案",
        "actionable_rule": "隐藏事实未披露过半不出方案",
    }
}
_PAYLOAD_B = {
    "prompt_overlay_fragment": {
        "purpose_key": "simulation_workbench",
        "fragment": "候选 B：未确认核心约束前不产正式方案稿。",
    }
}


def test_fingerprint_payload_sha256_different_payloads_coexist(operator, lead, script_ai):
    finding_ids = _make_findings(operator)
    script_ai([json.dumps(_good_draft("FA-C1"), ensure_ascii=False)])
    draft = operator.post(
        "/api/v1/simulation/findings/draft-ai", json={"finding_ids": finding_ids}
    ).get_json()["data"]

    first = _create_proposal(lead, finding_ids, candidate_payload=_PAYLOAD_A)
    assert first.status_code == 201, first.get_json()
    # 同 findings 同 target 不同候选载荷 ⇒ 不同指纹 ⇒ 不被 409 挡死（P0-Ⅶ）
    second = _create_proposal(lead, finding_ids, candidate_payload=_PAYLOAD_B)
    assert second.status_code == 201, second.get_json()
    assert first.get_json()["data"]["id"] != second.get_json()["data"]["id"]
    # 同 payload 重复提交 ⇒ 409 幂等保留
    again = _create_proposal(lead, finding_ids, candidate_payload=_PAYLOAD_A)
    assert again.status_code == 409
    # 入档载荷可读回
    assert second.get_json()["data"]["candidate_payload"] == _PAYLOAD_B
    # 返件指纹＝服务端同真身计算
    from fde_api.simulation.improvement_service import _finding_fingerprint

    expected = _finding_fingerprint(
        finding_ids,
        {"kind": "rule", "ref": "acceptance/dimension-1"},
        payload_sha256=improvement_draft.candidate_payload_sha256(_PAYLOAD_A),
    )
    assert first.get_json()["data"]["proposal_key"] == f"PROP-{expected[:8].upper()}"
    assert draft["payload_sha256"] == improvement_draft.candidate_payload_sha256(draft["draft"])


def test_candidate_payload_shape_gate(operator, lead):
    finding_ids = _make_findings(operator)
    bad_kind = _create_proposal(
        lead, finding_ids, candidate_payload={"lesson": {"text": "x"}}
    )
    assert bad_kind.status_code == 400
    too_long = _create_proposal(
        lead,
        finding_ids,
        candidate_payload={"lesson_entry": {"text": "长" * 301}},
    )
    assert too_long.status_code == 400
    overlay_long = _create_proposal(
        lead,
        finding_ids,
        candidate_payload={"prompt_overlay_fragment": {"purpose_key": "p", "fragment": "条" * 201}},
    )
    assert overlay_long.status_code == 400
