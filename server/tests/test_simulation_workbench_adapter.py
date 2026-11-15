"""workbench 执行面（学习闭环 2.0 L4 断点①）。

钉住：

1. **注册两处**：``ADAPTER_MODES`` 闭集含 ``workbench``；``build_adapter``
   未知模式仍报错（不静默退回 mock）。
2. **真模型调用纪律**：probe/analyze/design 走注入执行器——purpose/
   prompt_version 恒定；JSON 契约失败重试一次后回落 ``structured=False``
   （real.py 语义，不静默假定已结构化）。
3. **槽位 fail-closed**：缺 API Key/模型名 ⇒ ``AdapterUnavailable`` ⇒
   运行诚实失败（不静默退回 mock）。
4. **候选载荷通道**：run config ``candidate_payload.prompt_overlay_fragment``
   以追加条款进 system 消息（≤200 字沙箱同尺）。
5. **runner 接线**：逐轮 ctx（disclosed 随轮更新＋history 累积）；mock 忽略
   新键 ⇒ cost_json 键集逐字节不变（零回归）；workbench 档 usage 回填
   cost_json（tokens 不再恒 0）。
6. **异步化**：workbench 单跑经 outbox 入 ``simulation.run`` 后台作业；
   mock 小跑保持同步；handler 幂等（终态运行不重复执行）。
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
from fde_api.extensions import db
from fde_api.simulation.adapters import build_adapter
from fde_api.simulation.adapters.base import AdapterContext, AdapterUnavailable
from fde_api.simulation.adapters.workbench import WorkbenchAdapter
from fde_api.simulation.models import (
    ADAPTER_MODES,
    SimulationActor,
    SimulationRun,
    SimulationScenario,
    SimulationTrace,
)
from fde_api.simulation.run_jobs import handle_simulation_run_job


@dataclass(frozen=True)
class _Client:
    client: object
    user: User
    headers: dict[str, str]

    def get(self, *args, **kwargs):
        return self.client.get(*args, headers=self.headers, **kwargs)

    def post(self, *args, **kwargs):
        return self.client.post(*args, headers=self.headers, **kwargs)


@pytest.fixture
def operator(client, db_session, settings):
    user = User(
        username=f"sim.wb.{uuid4().hex[:8]}",
        display_name="Workbench operator",
        role="fde_engineer",
        password_hash=hash_password(INITIAL_PASSWORD),
        must_change_password=False,
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()
    return _Client(client, user, {"Authorization": f"Bearer {issue_access_token(user, settings)}"})


@pytest.fixture(autouse=True)
def _clean_simulation(db_session):
    from fde_api.jobs.models import OutboxEvent
    from fde_api.simulation.models import ImprovementProposal, SimulationEvaluation, SimulationFinding

    yield
    db_session.rollback()
    db_session.execute(delete(OutboxEvent))
    db_session.execute(delete(ImprovementProposal))
    db_session.execute(delete(SimulationFinding))
    db_session.execute(delete(SimulationEvaluation))
    db_session.execute(delete(SimulationTrace))
    db_session.execute(delete(SimulationActor))
    db_session.execute(delete(SimulationRun))
    db_session.execute(delete(SimulationScenario))
    db_session.commit()


def _scenario_payload(case_code: str = "CASE-WB-001"):
    return {
        "name": "workbench 测试案例",
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
                        "fact_id": "W-F1",
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


def _ctx(**config) -> AdapterContext:
    return AdapterContext(
        run_id="run-wb-test",
        scenario_key="CASE-WB-001",
        variant="normal",
        split="train",
        seed=1,
        brief=("设备经常坏",),
        constraints={"budget": "10 万"},
        disclosed=({"fact_id": "W-F1", "text": "维修记录是纸质的", "category": "knowledge"},),
        config={
            "probe_questions": [
                {"question": "关于维修、记录这块，现在实际是怎么做的？", "fact_id": "W-F1", "keywords": ["维修"], "targeted": True}
            ],
            **config,
        },
    )


class _RecordingExecutor:
    """CI seam：记录每次调用并按脚本返回。"""

    def __init__(self, script: list[str]) -> None:
        self._script = list(script)
        self.calls: list[dict] = []

    def __call__(self, **kwargs) -> dict:
        self.calls.append(kwargs)
        usage = {"complete": True, "calls": [{"prompt_tokens": 100, "completion_tokens": 20}]}
        text = self._script.pop(0) if self._script else "（空）"
        return {"text": text, "model": {"provider": "deepseek", "name": "test"}, "provider_usage": usage}


def _analyze_json() -> str:
    return json.dumps(
        {
            "root_causes": [{"fact_id": "W-F1", "text": "维修记录纸质", "category": "knowledge"}],
            "requirements": [{"key": "REQ-1", "title": "澄清维修记录", "source_fact_id": "W-F1", "acceptance_required": True}],
            "open_questions": [],
            "facts_known": 1,
        },
        ensure_ascii=False,
    )


def _design_json() -> str:
    return json.dumps(
        {
            "solution_sections": [{"heading": "记录结构化", "actions": ["先做台账"]}],
            "tasks": [{"key": "TASK-1", "title": "记录结构化", "depends_on": [], "evidence_required": True}],
            "acceptance_criteria": [{"key": "AC-1", "requirement_key": "REQ-1", "criterion": "台账可度量", "measurable": True}],
            "workflow_nodes": [{"key": "review", "type": "human_approval"}],
        },
        ensure_ascii=False,
    )


# ---------------------------------------------------------------------------
# 注册与契约
# ---------------------------------------------------------------------------


def test_adapter_modes_and_build_adapter_registration():
    assert "workbench" in ADAPTER_MODES
    adapter = build_adapter("workbench", actor_user_id="user-1")
    assert isinstance(adapter, WorkbenchAdapter)
    assert adapter.mode == "workbench"
    with pytest.raises(ValueError):
        build_adapter("nope")


def test_probe_uses_purpose_and_version_and_accumulates_usage():
    executor = _RecordingExecutor(["你们维修记录现在怎么管？"])
    adapter = WorkbenchAdapter(actor_user_id="user-1", executor=executor)
    question = adapter.probe(_ctx(history=({"round": 1, "question": "q", "answer": "a"},)), round_index=2)
    assert "维修" in question
    assert len(executor.calls) == 1
    call = executor.calls[0]
    assert call["purpose"] == "simulation_workbench"
    assert call["prompt_version"].startswith("simulation-workbench-prompt-v")
    assert call["use_tools"] is False
    summary = adapter.usage_summary()
    assert summary == {"model_calls": 1, "prompt_tokens": 100, "completion_tokens": 20, "tokens": 120}


def test_analyze_contract_pass_and_structured_fallback():
    # 契约一次过
    executor = _RecordingExecutor([_analyze_json(), _design_json()])
    adapter = WorkbenchAdapter(actor_user_id="user-1", executor=executor)
    analysis = adapter.analyze(_ctx())
    assert analysis["facts_known"] == 1
    assert analysis["requirements"][0]["key"] == "REQ-1"
    assert "structured" not in analysis  # 结构化成功不落回落键

    # 两次都不是 JSON ⇒ 重试一次后 structured=False 回落（real.py 语义）
    executor2 = _RecordingExecutor(["不是 JSON", "还是不是 JSON"])
    adapter2 = WorkbenchAdapter(actor_user_id="user-1", executor=executor2)
    fallback = adapter2.analyze(_ctx())
    assert fallback["structured"] is False
    assert fallback["requirements"] == []
    assert len(executor2.calls) == 2  # 首调＋拒因重试各一次


def test_implement_and_validate_reuse_deterministic_legs():
    executor = _RecordingExecutor(["你们维修记录现在怎么管？", _analyze_json(), _design_json()])
    adapter = WorkbenchAdapter(actor_user_id="user-1", executor=executor)
    ctx = _ctx()
    analysis = adapter.analyze(ctx)
    design = adapter.design(_ctx(requirements=analysis["requirements"]))
    implementation = adapter.implement(ctx)
    validation = adapter.validate(ctx, {"analysis": analysis, "design": design, "implementation": implementation})
    # 确定性腿产物（mock 同款结构）
    assert implementation["tool_calls"] == []
    assert validation["verdict"] in ("pass", "conditional")


def test_candidate_overlay_fragment_in_system_message_and_cap_200():
    executor = _RecordingExecutor(["下一问？"])
    adapter = WorkbenchAdapter(actor_user_id="user-1", executor=executor)
    overlay = {"prompt_overlay_fragment": {"purpose_key": "simulation_workbench", "fragment": "未确认客户预算前不产出报价方案" * 30}}
    adapter.probe(_ctx(candidate_payload=overlay), round_index=1)
    system = executor.calls[0]["system_prompt"]
    assert "未确认客户预算前不产出报价方案" in system
    assert "追加经验条款" in system
    # 沙箱同尺：≤200 字截断
    fragment_start = system.index("未确认客户预算前")
    assert len(system[fragment_start:]) <= 200 + 10

    # 无候选载荷 ⇒ system＝注册表常量本体
    executor2 = _RecordingExecutor(["下一问？"])
    adapter2 = WorkbenchAdapter(actor_user_id="user-1", executor=executor2)
    adapter2.probe(_ctx(), round_index=1)
    from fde_api.simulation.adapters.workbench import WORKBENCH_SYSTEM_PROMPT

    assert executor2.calls[0]["system_prompt"] == WORKBENCH_SYSTEM_PROMPT


def test_model_slot_fallback_and_fail_closed(app):
    """槽位语义：workbench 槽空 ⇒ 回落评估槽；缺密钥 ⇒ fail-closed 诚实失败。"""
    from pydantic import SecretStr

    adapter = WorkbenchAdapter(actor_user_id="user-1")
    with app.app_context():
        original = app.config["SETTINGS"]
        try:
            no_key = original.model_copy(update={"deepseek_api_key": None})
            app.config["SETTINGS"] = no_key
            with pytest.raises(AdapterUnavailable) as excinfo:
                adapter.probe(_ctx(), round_index=1)
            assert excinfo.value.reason == "workbench_model_slot_incomplete"

            with_key = no_key.model_copy(
                update={
                    "deepseek_api_key": SecretStr("test-key"),
                    "deepseek_base_url": "https://api.minimaxi.com/v1",
                    "deepseek_simulation_workbench_model": "",
                }
            )
            app.config["SETTINGS"] = with_key
            # 缺省回落评估槽位（§6 拍板②）＋直连腿四元组完整
            override = adapter._resolve_model_override()
            assert override == {
                "provider": "openai-compatible",
                "model": original.deepseek_simulation_evaluation_model,
                "base_url": "https://api.minimaxi.com/v1",
                "api_key": "test-key",
            }
            # 直连腿结构校验：无 DSH 时 direct_provider_completion 三必需键在位
            assert override["base_url"] and override["model"] and override["api_key"]

            explicit = with_key.model_copy(
                update={"deepseek_simulation_workbench_model": "MiniMax-M3.1-Flash"}
            )
            app.config["SETTINGS"] = explicit
            assert adapter._resolve_model_override() == {
                "provider": "openai-compatible",
                "model": "MiniMax-M3.1-Flash",
                "base_url": "https://api.minimaxi.com/v1",
                "api_key": "test-key",
            }
        finally:
            app.config["SETTINGS"] = original


# ---------------------------------------------------------------------------
# runner 接线（app.extensions seam 的端到端）
# ---------------------------------------------------------------------------


def _install_seam(app, script: list[str]) -> _RecordingExecutor:
    executor = _RecordingExecutor(script)
    app.extensions["fde_api_simulation_workbench"] = executor
    return executor


def test_runner_workbench_end_to_end_with_usage_backfill(operator, app):
    scenario = operator.post("/api/v1/simulation/scenarios", json=_scenario_payload()).get_json()["data"]
    run = operator.post(
        "/api/v1/simulation/runs",
        json={"scenario_id": scenario["id"], "adapter_mode": "mock", "execute": False, "config": {"max_rounds": 2}},
    ).get_json()["data"]

    # mock 零回归：cost_json 键集不含 usage 新键
    from fde_api.simulation.runner import run_simulation

    run_simulation(run["id"])
    with db.session() as session:
        row = session.get(SimulationRun, run["id"])
        assert row.status == "completed"
        assert set(row.cost_json) == {"tokens", "tool_calls", "rejected_calls", "tool_failures", "rounds"}
        assert row.cost_json["tokens"] == 0

    # workbench 档：usage 回填（tokens≠0、model_calls 在场）——seed 不同 ⇒
    # run_key 不同（config 指纹随 config 变化天然分流）
    wb_run = operator.post(
        "/api/v1/simulation/runs",
        json={
            "scenario_id": scenario["id"],
            "adapter_mode": "workbench",
            "execute": False,
            "config": {"max_rounds": 2},
            "seed": 7,
        },
    ).get_json()["data"]
    script = ["你们维修记录现在怎么管？"] * 2 + [_analyze_json(), _design_json()]
    executor = _install_seam(app, script)
    try:
        outcome = run_simulation(wb_run["id"])
        assert outcome["status"] == "completed"
        with db.session() as session:
            wb = session.get(SimulationRun, wb_run["id"])
            assert wb.adapter_mode == "workbench"
            assert wb.cost_json["tokens"] == 120 * len(executor.calls)
            assert wb.cost_json["model_calls"] == len(executor.calls)
            assert wb.cost_json["prompt_tokens"] == 100 * len(executor.calls)
            # 每次调用的 purpose/版本恒定（CI seam 钉审计面契约）
            purposes = {call["purpose"] for call in executor.calls}
            assert purposes == {"simulation_workbench"}
    finally:
        app.extensions.pop("fde_api_simulation_workbench", None)


def test_runner_probe_unavailable_fails_honestly(operator, app):
    scenario = operator.post("/api/v1/simulation/scenarios", json=_scenario_payload()).get_json()["data"]
    run = operator.post(
        "/api/v1/simulation/runs",
        json={"scenario_id": scenario["id"], "adapter_mode": "workbench", "execute": False, "config": {"max_rounds": 2}},
    ).get_json()["data"]

    def _boom(**kwargs):
        raise RuntimeError("provider_down")

    app.extensions["fde_api_simulation_workbench"] = _boom
    try:
        from fde_api.simulation.runner import run_simulation

        outcome = run_simulation(run["id"])
        assert outcome["status"] == "failed"
        with db.session() as session:
            row = session.get(SimulationRun, run["id"])
            assert row.error_json["code"] == "adapter_unavailable"
            assert row.error_json["phase"] == "interview"
            assert "workbench_model_failed" in row.error_json["reason"]
    finally:
        app.extensions.pop("fde_api_simulation_workbench", None)


def test_history_and_disclosed_flow_round_by_round(operator, app):
    """逐轮 ctx：probe 收到已披露事实与对话历史（mock 忽略 ⇒ 零回归已由上钉）。"""
    scenario = operator.post("/api/v1/simulation/scenarios", json=_scenario_payload()).get_json()["data"]
    run = operator.post(
        "/api/v1/simulation/runs",
        json={"scenario_id": scenario["id"], "adapter_mode": "workbench", "execute": False, "config": {"max_rounds": 2}},
    ).get_json()["data"]
    captured: list[dict] = []

    def _capture_probe(**kwargs):
        captured.append(kwargs)
        usage = {"complete": True, "calls": [{"prompt_tokens": 10, "completion_tokens": 5}]}
        return {"text": "维修记录现在怎么管的？", "model": {}, "provider_usage": usage}

    app.extensions["fde_api_simulation_workbench"] = _capture_probe
    try:
        from fde_api.simulation.runner import run_simulation

        run_simulation(run["id"])
        assert len(captured) >= 2
        # 第 2 轮起历史在场（第 1 轮历史为空）
        assert "【对话历史】" in captured[1]["prompt"]
        assert "第1轮" in captured[1]["prompt"]
    finally:
        app.extensions.pop("fde_api_simulation_workbench", None)


# ---------------------------------------------------------------------------
# 异步化
# ---------------------------------------------------------------------------


def test_workbench_create_run_enqueues_async_job(operator):
    from fde_api.jobs.models import OutboxEvent

    scenario = operator.post("/api/v1/simulation/scenarios", json=_scenario_payload()).get_json()["data"]
    result = operator.post(
        "/api/v1/simulation/runs",
        json={
            "scenario_id": scenario["id"],
            "adapter_mode": "workbench",
            "execute": True,
            "config": {"max_rounds": 2},
        },
    ).get_json()["data"]
    assert result["queued_async"] is True
    assert result["status"] == "queued"
    with db.session() as session:
        events = list(
            session.scalars(
                select(OutboxEvent).where(OutboxEvent.topic == "simulation.run")
            )
        )
        assert len(events) == 1
        assert events[0].aggregate_id == result["id"]
        assert events[0].subject_org is None  # 平台级计量标签


def test_mock_create_run_stays_synchronous(operator):
    from fde_api.jobs.models import OutboxEvent

    scenario = operator.post("/api/v1/simulation/scenarios", json=_scenario_payload()).get_json()["data"]
    result = operator.post(
        "/api/v1/simulation/runs",
        json={"scenario_id": scenario["id"], "adapter_mode": "mock", "execute": True, "config": {"max_rounds": 1}},
    ).get_json()["data"]
    assert "queued_async" not in result
    assert result["status"] == "completed"  # 同步跑完
    with db.session() as session:
        events = list(
            session.scalars(
                select(OutboxEvent).where(OutboxEvent.topic == "simulation.run")
            )
        )
        assert events == []


def test_simulation_run_job_handler_idempotent_on_terminal(operator, app):
    scenario = operator.post("/api/v1/simulation/scenarios", json=_scenario_payload()).get_json()["data"]
    run = operator.post(
        "/api/v1/simulation/runs",
        json={"scenario_id": scenario["id"], "adapter_mode": "mock", "execute": True, "config": {"max_rounds": 1}},
    ).get_json()["data"]

    from fde_api.jobs.models import BackgroundJob

    with db.session() as session:
        job = BackgroundJob(job_type="simulation.run", target_id=run["id"], status="running")
        session.add(job)
        session.flush()
        handle_simulation_run_job(job)
        with db.session() as check:
            traces_before = len(
                list(check.scalars(select(SimulationTrace).where(SimulationTrace.run_id == run["id"])))
            )
        # 幂等：终态运行直接返回，不重复执行
        handle_simulation_run_job(job)
        with db.session() as check:
            traces_after = len(
                list(check.scalars(select(SimulationTrace).where(SimulationTrace.run_id == run["id"])))
            )
        assert traces_before == traces_after
