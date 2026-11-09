"""G9 接线轮：真实执行面接线 + 真模型评估层接线。

钉住：
1. **沙箱项目**：幂等、admin 专属、代号合规；**场景投影只含已披露事实**，
   **不含**期望结果/验收标准/Rubric（答案不进 Agent 上下文）；
2. **真实适配器**：相位 → V3.1 能力档的映射正确；边界可注入（测试不 spawn 真进程）；
   执行面不可用 ⇒ 运行**诚实失败**（不静默退回 mock）；
3. **真模型评估层**：契约严格（键集闭合/分数区间/**证据强制**）；三种失败态
   （unavailable / error / invalid_output）都**不产生分数**；
4. **模型层不能改写终局**：硬性失败只由 L-A 判。
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
from fde_api.guidance.models import ProjectGuidanceAnalysis
from fde_api.simulation import sandbox
from fde_api.simulation.adapters import build_adapter
from fde_api.simulation.adapters.base import AdapterContext, AdapterUnavailable
from fde_api.simulation.adapters.real import (
    DEFAULT_AGENT_CAPABILITIES,
    RealAgentAdapter,
)
from fde_api.simulation.evaluation_schema import (
    EvaluationContractError,
    parse_model_evaluation,
)
from fde_api.simulation.model_evaluation import (
    ServerModelEvaluation,
    StubModelEvaluation,
    build_model_evaluation,
)
from fde_api.simulation.models import (
    SimulationActor,
    SimulationEvaluation,
    SimulationFinding,
    SimulationRun,
    SimulationScenario,
    SimulationTrace,
)
from fde_api.solutions.models import ProjectSolution
from fde_api.workbench.models import Project


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
        username=f"sim.g9.{role}.{uuid4().hex[:8]}",
        display_name="Simulation wiring",
        role=role,
        password_hash=hash_password(INITIAL_PASSWORD),
        must_change_password=False,
        is_active=True,
    )
    db_session.add(user)
    session_user = user
    db_session.commit()
    return _Client(client, session_user, {"Authorization": f"Bearer {issue_access_token(user, settings)}"})


@pytest.fixture
def admin(client, db_session, settings):
    return _make_client(client, db_session, settings, role="admin")


@pytest.fixture
def engineer(client, db_session, settings):
    return _make_client(client, db_session, settings, role="fde_engineer")


@pytest.fixture(autouse=True)
def _clean(db_session):
    yield
    db_session.rollback()
    db_session.execute(delete(SimulationFinding))
    db_session.execute(delete(SimulationEvaluation))
    db_session.execute(delete(SimulationTrace))
    db_session.execute(delete(SimulationActor))
    db_session.execute(delete(SimulationRun))
    db_session.execute(delete(SimulationScenario))
    db_session.execute(delete(ProjectSolution))
    db_session.execute(delete(ProjectGuidanceAnalysis))
    db_session.execute(delete(Project))
    db_session.commit()


# ---------------------------------------------------------------------------
# 1. 沙箱项目与场景投影
# ---------------------------------------------------------------------------


def test_sandbox_project_is_created_once_and_only_by_admin(admin, engineer):
    with db.session() as session:
        project = sandbox.ensure_sandbox_project(actor=admin.user, session=session)
        session.commit()
        again = sandbox.ensure_sandbox_project(actor=admin.user, session=session)

    assert project.id == again.id
    assert project.project_code == sandbox.SANDBOX_PROJECT_CODE
    # 代号纪律：三段两枚「·」
    assert project.enterprise_code.count("·") == 2
    assert project.enterprise_code.startswith("SIM")

    with pytest.raises(sandbox.SandboxError) as excinfo:
        sandbox.ensure_sandbox_project(actor=engineer.user)
    assert excinfo.value.status == 403


def test_projection_contains_only_disclosed_facts_and_no_answer(admin):
    disclosed = [
        {"fact_id": "F-1", "text": "维修记录是纸质的", "category": "knowledge"},
    ]
    with db.session() as session:
        project = sandbox.ensure_sandbox_project(actor=admin.user, session=session)
        projection = sandbox.project_scenario(
            session=session,
            project=project,
            scenario_key="CASE-TEST",
            variant="normal",
            split="train",
            brief=["设备经常坏"],
            disclosed=disclosed,
            actor=admin.user,
        )
        session.commit()
        analysis = session.get(ProjectGuidanceAnalysis, projection["analysis_id"])
        solution = session.get(ProjectSolution, projection["solution_id"])

    assert analysis is not None
    assert analysis.status == "confirmed"
    texts = [str(item.get("text")) for item in (analysis.key_business_problems_json or [])]
    assert "设备经常坏" in texts
    assert "维修记录是纸质的" in texts

    assert solution is not None
    skeleton = solution.design_markdown
    assert "CASE-TEST" in skeleton
    # **答案不进骨架**：Rubric 条目、期望结果、验收标准原文一律不得出现
    # （任务说明里出现「给出可度量的验收标准」这类**指令**是正常的，不在此禁）。
    forbidden_texts = [
        "must_identify",
        "must_avoid",
        "must_produce",
        "跨系统主键缺失",
        "物料编码不统一",
        "质量库字段非结构化",
        "识别出客户真实需求",
        "可验证的验收标准",
    ]
    for forbidden in forbidden_texts:
        assert forbidden not in skeleton, forbidden


def test_reprojection_supersedes_the_previous_analysis(admin):
    with db.session() as session:
        project = sandbox.ensure_sandbox_project(actor=admin.user, session=session)
        first = sandbox.project_scenario(
            session=session,
            project=project,
            scenario_key="CASE-TEST",
            variant="normal",
            split="train",
            brief=["第一轮"],
            disclosed=[{"fact_id": "F-1", "text": "旧事实"}],
            actor=admin.user,
        )
        second = sandbox.project_scenario(
            session=session,
            project=project,
            scenario_key="CASE-TEST",
            variant="normal",
            split="train",
            brief=["第二轮"],
            disclosed=[{"fact_id": "F-2", "text": "新事实"}],
            actor=admin.user,
        )
        session.commit()
        old = session.get(ProjectGuidanceAnalysis, first["analysis_id"])
        new = session.get(ProjectGuidanceAnalysis, second["analysis_id"])
        solutions = list(
            session.scalars(
                select(ProjectSolution).where(ProjectSolution.project_id == project.id)
            )
        )

    assert old is not None and old.status == "superseded"
    assert new is not None and new.status == "confirmed"
    # 方案骨架**复用同一行**（不删——产物可能挂 solution 外键）
    assert len(solutions) == 1


# ---------------------------------------------------------------------------
# 2. 真实适配器
# ---------------------------------------------------------------------------


def _ctx() -> AdapterContext:
    return AdapterContext(
        run_id="run-1",
        scenario_key="CASE-TEST",
        variant="normal",
        split="train",
        seed=0,
        brief=("设备经常坏",),
        disclosed=({"fact_id": "F-1", "text": "维修记录是纸质的"},),
        config={"probe_questions": [{"question": "维修记录怎么留的？", "targeted": True}]},
    )


def test_real_adapter_maps_phases_to_v31_capabilities():
    calls: list[tuple[str, str]] = []

    def fake_runner(*, ctx, phase, capability):
        calls.append((phase, capability))
        return {"artifacts": [], "tool_calls": [], "evidence_count": 0}

    adapter = RealAgentAdapter(agent_runner=fake_runner)

    adapter.analyze(_ctx())
    adapter.design(_ctx())
    adapter.implement(_ctx())
    adapter.validate(_ctx(), {})

    assert calls == [
        ("analysis", DEFAULT_AGENT_CAPABILITIES["analysis"]),
        ("design", DEFAULT_AGENT_CAPABILITIES["design"]),
        ("implementation", DEFAULT_AGENT_CAPABILITIES["implementation"]),
        ("validation", DEFAULT_AGENT_CAPABILITIES["validation"]),
    ]


def test_real_adapter_marks_not_exercised_when_no_artifact():
    def fake_runner(*, ctx, phase, capability):
        return {
            "artifacts": [],
            "tool_calls": [],
            "evidence_count": 0,
            "integration_status": "wired_not_exercised",
        }

    adapter = RealAgentAdapter(agent_runner=fake_runner)

    result = adapter.implement(_ctx())

    assert result["integration_status"] == "wired_not_exercised"
    assert result["structured"] is False


def test_real_adapter_probe_stays_deterministic():
    """多轮访谈走确定性探针（真实执行面无多轮对话接口）。"""
    adapter = RealAgentAdapter()
    ctx = _ctx()

    first = adapter.probe(ctx, round_index=1)
    second = adapter.probe(ctx, round_index=1)

    assert first == second
    assert first


def test_build_adapter_rejects_unknown_mode():
    with pytest.raises(ValueError):
        build_adapter("quantum")


def test_adapter_unavailable_is_not_swallowed_by_the_runner(engineer):
    """真实执行面不可用 ⇒ 运行诚实失败（**不静默退回 mock**）。"""
    from fde_api.simulation import runner as runner_module

    scenario = SimulationScenario(
        scenario_key="CASE-G9",
        name="接线测试案例",
        industry="general_manufacturing",
        variant="normal",
        split="train",
        status="active",
        tags=[],
        content_json={
            "case_code": "CASE-G9",
            "customer_profile": {"stakeholders": ["生产经理"]},
            "visible": {
                "initial_brief": ["设备经常坏"],
                "known_systems": [],
                "constraints": {},
            },
            "hidden": {"facts": []},
            "misleading_request": "上 AI",
        },
        reference_json=None,
        version=1,
    )
    with db.session() as session:
        session.add(scenario)
        session.flush()
        run = SimulationRun(
            run_key="CASE-G9:normal:v1:seed0:a1:cfgx",
            scenario_id=scenario.id,
            scenario_version=1,
            split="train",
            status="queued",
            adapter_mode="real",
            seed=0,
            attempt=1,
            actor_set_json={},
            context_json={},
            cost_json={},
        )
        session.add(run)
        session.flush()
        run_id = run.id
        session.commit()

    original = runner_module.build_adapter

    def failing_adapter(mode: str, **config):
        adapter = original(mode, **config)

        def unavailable(*, ctx, phase, capability):
            raise AdapterUnavailable(f"agent_not_available:{capability}")

        adapter._agent_runner = unavailable  # noqa: SLF001 - 边界注入（测试用）
        return adapter

    runner_module.build_adapter = failing_adapter  # type: ignore[assignment]
    try:
        outcome = runner_module.run_simulation(run_id)
    finally:
        runner_module.build_adapter = original  # type: ignore[assignment]

    assert outcome["status"] == "failed"
    assert outcome["adapter_unavailable"]["reason"].startswith("agent_not_available")


# ---------------------------------------------------------------------------
# 3. 真模型评估层
# ---------------------------------------------------------------------------


def test_model_evaluation_contract_accepts_a_well_formed_payload():
    raw = {
        "criteria": [
            {
                "key": "M-01",
                "dimension": "D1",
                "title": "是否点到了关键问题",
                "score": 0.5,
                "verdict": "partial",
                "evidence_refs": [{"kind": "artifact", "text": "MES 与质量库之间没有共同主键"}],
                "reason": "提到了主键但未展开映射方案",
            }
        ],
        "summary": "部分命中",
    }

    parsed = parse_model_evaluation(raw)

    assert len(parsed["criteria"]) == 1
    assert parsed["criteria"][0]["score"] == 0.5
    assert parsed["summary"] == "部分命中"


@pytest.mark.parametrize(
    "raw, expected_code",
    [
        ({"criteria": [], "summary": "x", "extra": 1}, "unknown_keys"),
        ({"criteria": []}, "missing_keys"),
        ({"criteria": "not-a-list", "summary": "x"}, "invalid_criteria"),
        (
            {
                "criteria": [
                    {
                        "key": "M-01",
                        "dimension": "D9",
                        "title": "t",
                        "score": 0.5,
                        "verdict": "pass",
                        "evidence_refs": [{"kind": "a", "text": "b"}],
                        "reason": "r",
                    }
                ],
                "summary": "x",
            },
            "invalid_dimension",
        ),
        (
            {
                "criteria": [
                    {
                        "key": "M-01",
                        "dimension": "D1",
                        "title": "t",
                        "score": 1.7,
                        "verdict": "pass",
                        "evidence_refs": [{"kind": "a", "text": "b"}],
                        "reason": "r",
                    }
                ],
                "summary": "x",
            },
            "invalid_score",
        ),
    ],
)
def test_model_evaluation_contract_rejects_malformed_payloads(raw, expected_code):
    with pytest.raises(EvaluationContractError) as excinfo:
        parse_model_evaluation(raw)
    assert excinfo.value.code == expected_code


def test_model_evaluation_drops_criteria_without_evidence():
    raw = {
        "criteria": [
            {
                "key": "M-01",
                "dimension": "D1",
                "title": "无证据",
                "score": 1.0,
                "verdict": "pass",
                "evidence_refs": [],
                "reason": "r",
            }
        ],
        "summary": "x",
    }

    with pytest.raises(EvaluationContractError) as excinfo:
        parse_model_evaluation(raw)

    assert excinfo.value.code == "no_evidence_backed_criteria"


def test_model_evaluation_without_provider_returns_unavailable(app, monkeypatch):
    """无 provider 配置 ⇒ unavailable（**不产生分数**，不冒充）。"""
    settings = app.config["SETTINGS"]
    monkeypatch.setattr(settings, "deepseek_api_key", None)

    result = ServerModelEvaluation().evaluate(judge_view={}, artifacts={}, traces=[])

    assert result.status == "unavailable"
    assert result.total_score == 0.0
    assert result.criteria == ()


def test_model_evaluation_with_injected_client_produces_scores(app):
    """注入客户端 ⇒ 真模型路径可测（不触网）。"""
    from flask import current_app

    captured: dict[str, object] = {}

    class _FakeClient:
        def complete_json(self, *, messages, request_id, purpose=None, **_kwargs):
            captured["messages"] = messages
            captured["purpose"] = purpose
            return {
                "criteria": [
                    {
                        "key": "M-01",
                        "dimension": "D1",
                        "title": "是否点到了关键问题",
                        "score": 0.8,
                        "verdict": "pass",
                        "evidence_refs": [{"kind": "artifact", "text": "MES 与质量库之间没有共同主键"}],
                        "reason": "命中根因",
                    }
                ],
                "summary": "命中",
            }

    current_app.extensions["fde_api_simulation_deepseek"] = _FakeClient()
    try:
        result = ServerModelEvaluation().evaluate(
            judge_view={
                "reference": {
                    "rubric": {"must_identify": ["主键缺失"], "must_avoid": [], "must_produce": []}
                }
            },
            artifacts={"artifacts": [{"name": "a.md", "text": "MES 与质量库之间没有共同主键"}]},
            traces=[{"phase": "interview", "event_type": "actor_turn", "payload": {}}],
        )
    finally:
        current_app.extensions.pop("fde_api_simulation_deepseek", None)

    assert result.status == "evaluated"
    assert result.total_score == 0.8
    assert result.criteria[0]["evidence_refs"]
    messages = captured["messages"]
    assert isinstance(messages, list) and messages[0]["role"] == "system"
    assert captured["purpose"] == "simulation_evaluation"


def test_model_layer_cannot_override_hard_failures(engineer):
    """模型层**不能**改写终局——硬性失败只由 L-A 判（功能级断言）。"""
    from fde_api.simulation.evaluator import evaluate_run
    from fde_api.simulation.run_service import create_run

    scenario = SimulationScenario(
        scenario_key="CASE-HF",
        name="硬失败用例",
        industry="general_manufacturing",
        variant="normal",
        split="train",
        status="active",
        tags=[],
        content_json={
            "case_code": "CASE-HF",
            "customer_profile": {"stakeholders": ["生产经理"]},
            "visible": {
                "initial_brief": ["设备经常坏"],
                "known_systems": [],
                "constraints": {},
            },
            "hidden": {"facts": []},
            "misleading_request": "上 AI",
        },
        reference_json={
            "expected_outcomes": ["x"],
            "acceptance_criteria": ["y"],
            "rubric": {"must_identify": [], "must_avoid": [], "must_produce": []},
        },
        version=1,
    )
    with db.session() as session:
        session.add(scenario)
        session.flush()
        scenario_id = scenario.id
        session.commit()

    run = create_run(
        actor=engineer.user,
        payload={
            "scenario_id": scenario_id,
            "adapter_mode": "mock",
            "execute": True,
            "config": {"max_rounds": 2, "inject_boundary_violation": True},
        },
    )
    assert run["status"] == "failed_hard"

    report = evaluate_run(actor=engineer.user, run_id=run["id"])

    # 终局由规则层（L-A）判：模型层说什么都不改
    assert report["verdict"] == "hard_fail"
    assert report["deterministic"]["verdict"] == "hard_fail"
    codes = {item["code"] for item in report["hard_failures"]}
    assert "HF-01" in codes
    assert StubModelEvaluation().mode == "stub"
    assert ServerModelEvaluation().mode == "server"


def test_model_evaluation_retries_once_on_contract_violation(app):
    """G9b 真机实测补充：模型回显 Rubric 桶键 ⇒ 契约纠偏重试一次 ⇒ evaluated。

    （沿 discovery 管线「契约失败一次自动重试」先例；重试调用带违约反馈。）
    """
    from flask import current_app

    calls: list[dict[str, object]] = []

    class _FakeClient:
        def complete_json(self, *, messages, request_id, purpose=None, **_kwargs):
            calls.append({"request_id": request_id, "messages": messages})
            if len(calls) == 1:
                # 首发违约：把 Rubric 桶当顶层键回显（真机实测的实际形状）
                return {
                    "must_identify": ["主键缺失"],
                    "must_avoid": [],
                    "must_produce": ["主键映射方案"],
                }
            return {
                "criteria": [
                    {
                        "key": "MI-1",
                        "dimension": "D1",
                        "title": "主键缺失",
                        "score": 0.6,
                        "verdict": "partial",
                        "evidence_refs": [{"kind": "quote", "text": "两边对不上，没有共同主键"}],
                        "reason": "命中",
                    }
                ],
                "summary": "重试后合规",
            }

    current_app.extensions["fde_api_simulation_deepseek"] = _FakeClient()
    try:
        result = ServerModelEvaluation().evaluate(
            judge_view={
                "reference": {
                    "rubric": {"must_identify": ["主键缺失"], "must_avoid": [], "must_produce": []}
                }
            },
            artifacts={"artifacts": [{"name": "a.md", "text": "没有共同主键"}]},
            traces=[],
        )
    finally:
        current_app.extensions.pop("fde_api_simulation_deepseek", None)

    assert result.status == "evaluated"
    assert "含一次契约纠偏重试" in (result.note or "")
    assert len(calls) == 2
    assert calls[0]["request_id"] == "simulation-evaluation"
    assert calls[1]["request_id"] == "simulation-evaluation-retry"
    retry_messages = calls[1]["messages"]
    assert retry_messages[-1]["role"] == "user"
    assert "不合契约" in retry_messages[-1]["content"]


def test_model_evaluation_invalid_after_retry_stays_invalid(app):
    """纠偏后仍违约 ⇒ 落 invalid_output，不产生分数（不冒充）。"""
    from flask import current_app

    class _AlwaysBadClient:
        def complete_json(self, *, messages, request_id, purpose=None, **_kwargs):
            return {"must_identify": ["还是桶"]} if request_id == "simulation-evaluation" else {"bad": 1}

    current_app.extensions["fde_api_simulation_deepseek"] = _AlwaysBadClient()
    try:
        result = ServerModelEvaluation().evaluate(
            judge_view={
                "reference": {
                    "rubric": {"must_identify": ["主键缺失"], "must_avoid": [], "must_produce": []}
                }
            },
            artifacts={"artifacts": []},
            traces=[],
        )
    finally:
        current_app.extensions.pop("fde_api_simulation_deepseek", None)

    assert result.status == "invalid_output"
    assert result.total_score == 0.0
    assert result.criteria == ()


def test_model_evaluation_passes_elevated_max_tokens_on_every_call(app):
    """G9b 真机实测（2026-11-09）：评估调用必须显式抬高 max_tokens。

    根因：评估模型是推理模型，reasoning token 与正文**共用 max_tokens 预算**；
    客户端默认 8192 被思考整段烧掉 ⇒ finish_reason=length ⇒ content 为空
    （ai_empty_response）或正文被截断成非法 JSON（ai_output_invalid）。
    本测试钉住三层重试链路（首发 → 瞬时重试 → 契约纠偏重试）的**每一次**
    complete_json 调用都带 EVALUATION_MAX_TOKENS。
    """
    from flask import current_app

    from fde_api.ai.deepseek import DeepSeekError
    from fde_api.simulation.model_evaluation import EVALUATION_MAX_TOKENS

    calls: list[dict[str, object]] = []

    class _FakeClient:
        def complete_json(self, *, messages, request_id, purpose=None, **kwargs):
            calls.append({"request_id": request_id, "kwargs": kwargs})
            if len(calls) == 1:
                # 首发：retryable 瞬时失败（真机形态：空流/坏 JSON/超时）
                raise DeepSeekError("ai_empty_response", "空响应", retryable=True)
            if len(calls) == 2:
                # 瞬时重试：回显 Rubric 桶键（契约违约，真机实测的实际形状）
                return {"must_identify": ["主键缺失"], "must_avoid": [], "must_produce": []}
            # 契约纠偏重试：合规输出
            return {
                "criteria": [
                    {
                        "key": "MI-1",
                        "dimension": "D1",
                        "title": "主键缺失",
                        "score": 0.6,
                        "verdict": "partial",
                        "evidence_refs": [{"kind": "quote", "text": "没有共同主键"}],
                        "reason": "命中",
                    }
                ],
                "summary": "重试后合规",
            }

    current_app.extensions["fde_api_simulation_deepseek"] = _FakeClient()
    try:
        result = ServerModelEvaluation().evaluate(
            judge_view={
                "reference": {
                    "rubric": {"must_identify": ["主键缺失"], "must_avoid": [], "must_produce": []}
                }
            },
            artifacts={"artifacts": [{"name": "a.md", "text": "没有共同主键"}]},
            traces=[],
        )
    finally:
        current_app.extensions.pop("fde_api_simulation_deepseek", None)

    assert result.status == "evaluated"
    assert len(calls) == 3
    assert [c["request_id"] for c in calls] == [
        "simulation-evaluation",
        "simulation-evaluation-retry",
        "simulation-evaluation-retry",
    ]
    for call in calls:
        assert call["kwargs"].get("max_tokens") == EVALUATION_MAX_TOKENS == 16384


def test_evaluation_prompt_carries_phase_keyed_artifact_bodies():
    """G9b 真机实测修正：评估器传的是相位键控产物集合，提示词必须带正文。

    （此前只认顶层 artifacts 列表 ⇒ 真实/mock 相位体全部丢失 ⇒ 模型层
    「没有产物正文可评」——E2E 实测暴露，单测注入形态反而对齐掩盖了它。）
    """
    from fde_api.simulation.evaluation_prompt import build_evaluation_messages

    messages = build_evaluation_messages(
        judge_view={
            "reference": {"rubric": {"must_identify": ["主键缺失"], "must_avoid": [], "must_produce": []}}
        },
        artifacts={
            "analysis": {
                "structured": False,
                "artifacts": [{"name": "a.md", "pointer": "x", "text": "MES 批次与质量库无共同主键"}],
            },
            "design": {"structured": True, "root_causes": [{"text": "R-1"}]},
        },
        traces=[],
    )
    user = messages[1]["content"]
    assert "analysis/a.md" in user
    assert "无共同主键" in user
    assert "design（结构化交付）" in user
    assert "R-1" in user
