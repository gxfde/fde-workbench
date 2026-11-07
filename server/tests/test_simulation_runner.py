"""模拟执行引擎（G3）。

钉住四组纪律：

1. **工具白名单是强制的**：``sim.*`` 之外的工具在调用瞬间被拒 → 落 Trace →
   运行直接落 ``failed_hard``（不可被其他维度高分抵消、不可重试）。
2. **客户模拟器不编造**：未命中探针关键词 ⇒ 不披露；回答内容只来自场景事实集；
   命中 ⇒ 恰好披露对应事实。
3. **访谈深度决定产物厚度**：问得深（披露多）⇒ 需求/验收/证据更多。**这是
   mock 模式的刻意设计**——它让「问得深 ↔ 知道得多 ↔ 产出更全」这条链路可测。
4. **验收独立**：验收阶段的上下文不含 Rubric / 参考答案，也不含实施方自评。
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
from fde_api.simulation.actors.customer_simulator import CustomerSimulator, CustomerState
from fde_api.simulation.environment import (
    SimulationBoundaryViolation,
    SimulationEnvironment,
    SimulationToolError,
)
from fde_api.simulation.models import (
    SimulationActor,
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
        username=f"sim.{role}.{uuid4().hex[:8]}",
        display_name="Simulation user",
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


@pytest.fixture(autouse=True)
def _clean_simulation(db_session):
    """模拟域三表 + 场景表自清理（不碰共享 conftest 的清理清单）。"""
    yield
    db_session.rollback()
    db_session.execute(delete(SimulationTrace))
    db_session.execute(delete(SimulationActor))
    db_session.execute(delete(SimulationRun))
    db_session.execute(delete(SimulationScenario))
    db_session.commit()


def _scenario_payload(case_code: str = "CASE-RUNNER-001", **overrides):
    payload = {
        "name": "运行测试案例",
        "industry": "general_manufacturing",
        "variant": "normal",
        "split": "train",
        "content": {
            "case_code": case_code,
            "customer_profile": {
                "company_type": "测试用制造企业",
                "stakeholders": ["生产经理", "质量主管"],
                "maturity": "基础台账",
            },
            "visible": {
                "initial_brief": ["设备经常坏，找不到原因"],
                "known_systems": ["ERP"],
                "constraints": {"budget": "10 万", "timeline": "1 个月"},
            },
            "hidden": {
                "facts": [
                    {
                        "fact_id": "R-F1",
                        "text": "维修记录是纸质的，没有结构化字段",
                        "category": "knowledge",
                        "disclosure_stage": "interview",
                        "probe_keywords": ["记录", "维修", "工单"],
                    },
                    {
                        "fact_id": "R-F2",
                        "text": "设备型号命名混乱，手册对不上",
                        "category": "data",
                        "disclosure_stage": "interview",
                        "probe_keywords": ["型号", "编码", "手册"],
                    },
                ]
            },
            "misleading_request": "上 AI 预测性维护",
            "seed_data": {
                "crm": {"leads": [{"company": "示例客户", "source": "expo"}]},
                "mes": {"batches": [{"batch_no": "B-1"}]},
            },
        },
        "reference": {
            "expected_outcomes": ["识别真问题是知识缺失"],
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


def _create_scenario(operator, case_code: str = "CASE-RUNNER-001") -> dict:
    response = operator.post("/api/v1/simulation/scenarios", json=_scenario_payload(case_code))
    assert response.status_code == 201, response.get_json()
    return response.get_json()["data"]


# ---------------------------------------------------------------------------
# 1. 工具白名单
# ---------------------------------------------------------------------------


def test_sim_tools_are_callable_with_seed_data():
    environment = SimulationEnvironment(seed_data={"crm": {"leads": [{"company": "示例"}]}})

    result = environment.call_tool("sim.crm.list_leads", {})

    assert result["ok"] is True
    assert result["data"][0]["company"] == "示例"


def test_non_sim_tool_is_rejected_and_recorded():
    environment = SimulationEnvironment(seed_data={})

    with pytest.raises(SimulationBoundaryViolation) as excinfo:
        environment.call_tool("mail.send_real_customer", {"to": "x"})

    assert excinfo.value.code == "boundary_violation"
    assert environment.rejected_calls
    assert environment.rejected_calls[0]["tool"] == "mail.send_real_customer"


def test_unknown_sim_tool_is_rejected():
    environment = SimulationEnvironment(seed_data={})
    with pytest.raises(SimulationBoundaryViolation):
        environment.call_tool("sim.not_registered", {})


def test_fault_injection_raises_sim_tool_error():
    environment = SimulationEnvironment(
        seed_data={},
        faults=[{"match": {"tool": "sim.mes.list_batches"}, "error": "sim_tool_timeout"}],
    )
    with pytest.raises(SimulationToolError) as excinfo:
        environment.call_tool("sim.mes.list_batches", {})
    assert excinfo.value.code == "sim_tool_timeout"


def test_sim_mail_only_writes_to_the_in_memory_mailbox():
    environment = SimulationEnvironment(seed_data={})

    environment.call_tool("sim.mail.send", {"to": "buyer", "subject": "hi", "body": "x"})

    assert len(environment.mailbox) == 1
    assert environment.mailbox[0]["simulation_only"] is True


# ---------------------------------------------------------------------------
# 2. 客户模拟器：不编造
# ---------------------------------------------------------------------------


def _customer_view() -> dict:
    return {
        "customer_profile": {"stakeholders": ["质量主管"]},
        "hidden": {
            "facts": [
                {
                    "fact_id": "R-F1",
                    "text": "维修记录是纸质的，没有结构化字段",
                    "disclosure_stage": "interview",
                    "probe_keywords": ["记录", "维修"],
                },
                {
                    "fact_id": "R-F2",
                    "text": "设备型号命名混乱，手册对不上",
                    "disclosure_stage": "interview",
                    "probe_keywords": ["型号", "手册"],
                },
            ]
        },
    }


def test_probe_keywords_unlock_the_matching_fact_only():
    simulator = CustomerSimulator(customer_view=_customer_view())

    reply = simulator.respond("你们平时的维修记录是怎么留的？")

    assert reply.matched is True
    assert reply.disclosed == ("R-F1",)
    assert simulator.disclosed_facts[0]["fact_id"] == "R-F1"


def test_unmatched_question_discloses_nothing_and_invents_nothing():
    simulator = CustomerSimulator(customer_view=_customer_view())

    reply = simulator.respond("这个项目大概什么时候开始？")

    assert reply.matched is False
    assert reply.unanswered is True
    assert reply.disclosed == ()
    assert simulator.disclosed_facts == ()
    # 回答里不得出现任何未披露事实的正文
    assert "维修记录是纸质的" not in reply.text
    assert "设备型号命名混乱" not in reply.text


def test_disclosure_is_stage_gated():
    simulator = CustomerSimulator(customer_view=_customer_view())

    reply = simulator.respond("维修记录怎么留的？", allowed_stages=("setup",))

    assert reply.disclosed == ()
    assert simulator.disclosed_facts == ()


def test_escalate_after_makes_the_customer_volunteer():
    simulator = CustomerSimulator(customer_view=_customer_view(), escalate_after=1)

    simulator.respond("这个项目大概什么时候开始？")
    reply = simulator.respond("这个项目大概什么时候开始？")

    assert reply.escalated is True
    assert reply.disclosed != ()
    assert simulator.disclosed_facts


def test_customer_state_roundtrips_through_json():
    simulator = CustomerSimulator(customer_view=_customer_view())
    simulator.respond("维修记录怎么留的？")

    state = CustomerState.from_json(simulator.state.to_json())

    assert state.disclosed_fact_ids == ["R-F1"]
    assert state.probe_count == 1


# ---------------------------------------------------------------------------
# 3. 运行器：全流程与「深度决定厚度」
# ---------------------------------------------------------------------------


def _run_once(operator, scenario: dict, **config) -> dict:
    payload = {"scenario_id": scenario["id"], "adapter_mode": "mock", "execute": True}
    if config:
        payload["config"] = config
    response = operator.post("/api/v1/simulation/runs", json=payload)
    assert response.status_code == 201, response.get_json()
    return response.get_json()["data"]


def test_a_mock_run_completes_and_records_every_phase(operator, db_session):
    scenario = _create_scenario(operator)

    run = _run_once(operator, scenario, max_rounds=4, probe_quality=1.0)

    assert run["status"] == "completed"
    assert run["adapter_mode"] == "mock"
    db_session.rollback()
    phases = list(
        db_session.scalars(
            select(SimulationTrace.phase)
            .where(SimulationTrace.run_id == run["id"])
            .order_by(SimulationTrace.seq)
        )
    )
    for phase in ("setup", "interview", "analysis", "design", "implementation", "validation", "wrapup"):
        assert phase in phases


def test_deeper_interview_discloses_more_and_produces_more(operator, db_session):
    scenario = _create_scenario(operator)

    shallow = _run_once(operator, scenario, max_rounds=4, probe_quality=0.0, seed=7)
    deep = _run_once(operator, scenario, max_rounds=6, probe_quality=1.0, seed=7)

    assert shallow["cost"]["rounds"] == 4
    assert deep["cost"]["rounds"] == 6
    db_session.rollback()
    deep_facts = len(
        list(
            db_session.scalars(
                select(SimulationTrace).where(
                    SimulationTrace.run_id == deep["id"],
                    SimulationTrace.event_type == "hidden_fact_disclosed",
                )
            )
        )
    )
    shallow_facts = len(
        list(
            db_session.scalars(
                select(SimulationTrace).where(
                    SimulationTrace.run_id == shallow["id"],
                    SimulationTrace.event_type == "hidden_fact_disclosed",
                )
            )
        )
    )
    assert deep_facts > shallow_facts


def test_run_is_idempotent_for_the_same_key(operator):
    scenario = _create_scenario(operator)

    first = operator.post(
        "/api/v1/simulation/runs",
        json={"scenario_id": scenario["id"], "seed": 42},
    ).get_json()["data"]
    second = operator.post(
        "/api/v1/simulation/runs",
        json={"scenario_id": scenario["id"], "seed": 42},
    ).get_json()["data"]

    assert first["id"] == second["id"]
    assert second["created"] is False


def test_terminal_run_cannot_be_cancelled(operator):
    scenario = _create_scenario(operator)
    run = _run_once(operator, scenario)

    response = operator.post(f"/api/v1/simulation/runs/{run['id']}/cancel")

    assert response.status_code == 409
    assert response.get_json()["error"]["code"] == "conflict"


def test_failed_run_can_be_retried_with_a_new_attempt(operator):
    scenario = _create_scenario(operator)
    run = operator.post(
        "/api/v1/simulation/runs", json={"scenario_id": scenario["id"], "seed": 5}
    ).get_json()["data"]
    operator.post(f"/api/v1/simulation/runs/{run['id']}/cancel")

    retry = operator.post(f"/api/v1/simulation/runs/{run['id']}/retry")

    assert retry.status_code == 201
    data = retry.get_json()["data"]
    assert data["attempt"] == 2
    assert data["id"] != run["id"]


def test_trace_is_readable_in_seq_order(operator):
    scenario = _create_scenario(operator)
    run = _run_once(operator, scenario, max_rounds=3)

    response = operator.get(f"/api/v1/simulation/runs/{run['id']}/trace")

    assert response.status_code == 200
    items = response.get_json()["data"]["items"]
    assert items
    seqs = [item["seq"] for item in items]
    assert seqs == sorted(seqs)
    assert seqs[0] == 1


# ---------------------------------------------------------------------------
# 4. 权限与边界
# ---------------------------------------------------------------------------


def test_viewer_cannot_start_a_simulation(viewer):
    scenario_id = uuid4().hex
    response = viewer.post("/api/v1/simulation/runs", json={"scenario_id": scenario_id})
    assert response.status_code == 403


def test_boundary_violation_makes_the_run_fail_hard(operator):
    """越界调用 ⇒ 硬性失败：不可被高分抵消、不可重试、Trace 留证。"""
    scenario = _create_scenario(operator)

    run = _run_once(operator, scenario, inject_boundary_violation=True, max_rounds=2)

    assert run["status"] == "failed_hard"
    assert run["error"]["code"] == "boundary_violation"
    assert run["error"]["tools"] == ["mail.send_real_customer"]

    traces = operator.get(f"/api/v1/simulation/runs/{run['id']}/trace").get_json()["data"]["items"]
    assert any(item["event_type"] == "boundary_violation" for item in traces)

    retry = operator.post(f"/api/v1/simulation/runs/{run['id']}/retry")
    assert retry.status_code == 409
    assert retry.get_json()["error"]["code"] == "conflict"


def test_runner_never_touches_the_reference_answer():
    """执行器在**物理上**没有接触参考答案的路径（静态钉）。

    G1 §4.3 P4：参考答案绝不泄漏给被测方。实现落点不是「装了就别传」，而是
    **执行器根本不读** ``reference_json``——用 AST 钉死：模块里不得出现
    ``reference_json`` 属性访问，也不得出现 ``judge`` 视图字符串。
    """
    import ast
    import inspect

    from fde_api.simulation import runner as runner_module

    tree = ast.parse(inspect.getsource(runner_module))
    attributes: set[str] = set()
    literals: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute):
            attributes.add(node.attr)
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            literals.add(node.value)
    assert "reference_json" not in attributes
    assert "judge" not in literals


def test_run_rows_carry_no_project_reference(operator, db_session):
    scenario = _create_scenario(operator)
    run = _run_once(operator, scenario)

    db_session.rollback()
    row = db_session.get(SimulationRun, run["id"])
    assert row is not None
    assert not hasattr(row, "project_id")
