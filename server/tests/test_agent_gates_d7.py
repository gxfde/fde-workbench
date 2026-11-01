"""goal-d7：T1/T4/T5 强制门（状态机级，非 prompt）+ 角色卡不可执行 + 种子装载。

T1（总纲 §2.2）：start_run 带 solution_id 前置闸——无已封存 T1 纪要侧链该
solution → 409 t1_gate_open；T1 纪要与 T2 门语义分离（计划评审 ≠ 产物评审）。
T4（U10）：difficulty=high 的 run 需满档（full）加座纪要，lite 纪要放不高难度。
T5：家族含 L1 降级 run 时门只认 T5 补审纪要（降级产物不自动放行）。
"""
from __future__ import annotations

from pathlib import Path
from typing import Any
from uuid import uuid4

from sqlalchemy import select

from test_agents_d4_harness import (
    FakeScanner,
    api_client,
    prime_run,
    seed_agent,
)
from test_agents_d4_harness import d4_app, d4_client, d4_settings  # noqa: F401  (pytest fixture)
from test_document_drafts_api import _persist_project

from fde_api.agents.adapter import ArtifactFile
from fde_api.agents.models import AgentArtifact, AgentRegistry, AgentRun
from fde_api.agents.seeds import ensure_agent_seeds
from fde_api.meetings.service import t2_gate_satisfied
from fde_api.solutions.models import ProjectSolution

_MINUTES_OK = {
    "consensus": [{"text": "评审通过", "source_refs": []}],
    "disputes": [],
    "todos": [],
}


def _setup(db_session, d4_client, d4_settings, *, capability: str = "agent.code.write"):
    leader = api_client(d4_client, db_session, d4_settings, "project_lead")
    project = _persist_project(db_session, leader.user, code=f"D7G{uuid4().hex[:6]}")
    solution = ProjectSolution(project_id=project.id, name="交付方案", owner_user_id=leader.user.id)
    db_session.add(solution)
    db_session.commit()
    agent = seed_agent(db_session, d4_settings, capability=capability)
    return leader, project, solution, agent


def _confirmed_ref(db_session, project, leader) -> None:
    from test_goal_d2_s0_closeout import _confirmed_guidance

    _confirmed_guidance(
        db_session,
        project,
        leader.user,
        problems=[{"text": "库存数据割裂", "classification": "数据", "source_refs": ["src-1"], "confirmed": True}],
    )


def _refs_writer(path: str, refs: tuple[str, ...]):
    def factory(run_id, workspace):
        output = Path(workspace) / "output"
        output.mkdir(parents=True, exist_ok=True)
        (output / path).write_text("产物正文", encoding="utf-8")
        return FakeScanner([ArtifactFile(path=path, kind="doc", source_refs=refs)])

    return factory


def _seed_t1(leader, project, solution) -> None:
    convened = leader.post(
        "/api/v1/meetings",
        json={"project_id": project.id, "template_id": "T1-lite", "solution_id": solution.id},
    )
    assert convened.status_code == 201, convened.json
    sealed = leader.post(f"/api/v1/meetings/{convened.json['data']['id']}/close", json=_MINUTES_OK)
    assert sealed.status_code == 200, sealed.json


def _seed_gate_minutes(leader, project, solution, template_id: str, *, run_id: str | None = None) -> str:
    payload: dict[str, Any] = {"project_id": project.id, "template_id": template_id, "solution_id": solution.id}
    if run_id is not None:
        payload = {"project_id": project.id, "template_id": template_id, "triggered_by_run_id": run_id}
    convened = leader.post("/api/v1/meetings", json=payload)
    assert convened.status_code == 201, convened.json
    sealed = leader.post(f"/api/v1/meetings/{convened.json['data']['id']}/close", json=_MINUTES_OK)
    assert sealed.status_code == 200, sealed.json
    return convened.json["data"]["id"]


def _start(leader, agent, project, solution, *, difficulty: str | None = None, key: str | None = None):
    payload: dict[str, Any] = {
        "project_id": project.id,
        "solution_id": solution.id,
        "idempotency_key": key or f"d7g:{uuid4().hex}",
    }
    if difficulty is not None:
        payload["difficulty"] = difficulty
    return leader.post(f"/api/v1/agents/{agent.id}/run", json=payload)


# ---------------------------------------------------------------------------
# T1 计划评审强制门
# ---------------------------------------------------------------------------


def test_t1_gate_blocks_solution_run_u2(db_session, d4_client, d4_settings, d4_app) -> None:
    """无已封存 T1 纪要 → start_run 带 solution 被状态机拒绝（不创建 run）。"""
    leader, project, solution, agent = _setup(db_session, d4_client, d4_settings)
    _confirmed_ref(db_session, project, leader)
    prime_run(d4_app, scanner_factory=_refs_writer("plan.md", ("src-1",)))
    body = _start(leader, agent, project, solution)
    assert body.status_code == 409, body.json
    error = body.json["error"]
    assert error["code"] == "t1_gate_open"
    assert error["details"]["gate"] == "T1"
    runs = list(db_session.scalars(select(AgentRun).where(AgentRun.project_id == project.id)))
    assert runs == []  # 闸在发起前：零 run 落库


def test_t1_gate_passes_then_t2_still_open(db_session, d4_client, d4_settings, d4_app) -> None:
    """T1 封存后 run 放行创建；T1 纪要与 T2 门语义分离——产物提交终审仍被
    T2 拦（review_gate_open），证明计划评审不能替代产物评审。"""
    leader, project, solution, agent = _setup(db_session, d4_client, d4_settings)
    _confirmed_ref(db_session, project, leader)
    _seed_t1(leader, project, solution)
    prime_run(d4_app, scanner_factory=_refs_writer("plan.md", ("src-1",)))
    body = _start(leader, agent, project, solution)
    assert body.status_code == 409, body.json
    error = body.json["error"]
    assert error["code"] == "review_gate_open"  # 到达 T2 门（T1 已放行）
    run = db_session.get(AgentRun, error["details"]["run_id"])
    assert run is not None and run.degraded_reason == "review_gate_open"
    # 无 solution 绑定的探索性 run 不受 T1 约束（d4 零回归）
    prime_run(d4_app, scanner_factory=_refs_writer("plan.md", ("src-1",)))
    explore = leader.post(
        f"/api/v1/agents/{agent.id}/run",
        json={"project_id": project.id, "idempotency_key": f"explore:{uuid4().hex}"},
    )
    assert explore.status_code == 201, explore.json


def test_t1_retry_does_not_regate(db_session, d4_client, d4_settings, d4_app) -> None:
    """retry 不复 T1 闸：家族首 run 已被闸，重试沿 d4 语义（修订回路/退避）。"""
    leader, project, solution, agent = _setup(db_session, d4_client, d4_settings)
    _confirmed_ref(db_session, project, leader)
    _seed_t1(leader, project, solution)
    prime_run(d4_app, scanner_factory=_refs_writer("plan.md", ("src-1",)))
    key = f"t1r:{uuid4().hex}"
    blocked = _start(leader, agent, project, solution, key=key)
    assert blocked.status_code == 409 and blocked.json["error"]["code"] == "review_gate_open"
    run_id = blocked.json["error"]["details"]["run_id"]
    # retry 不隐式携带 solution（d4 语义）→ T2 纪要经 run 家族直挂
    _seed_gate_minutes(leader, project, solution, "T2-lite", run_id=run_id)
    prime_run(d4_app, scanner_factory=_refs_writer("plan.md", ("src-1",)))
    retried = leader.post(f"/api/v1/agents/runs/{run_id}/retry", json={})
    assert retried.status_code == 201, retried.json  # T1 未复闸，家族 T2 纪要放行


# ---------------------------------------------------------------------------
# T4 高难度加座门（difficulty=high 需满档纪要）
# ---------------------------------------------------------------------------


def test_t4_lite_minutes_insufficient_for_high_difficulty(db_session, d4_client, d4_settings, d4_app) -> None:
    """T4：difficulty=high 的 run，lite 档 T2 纪要（solution 侧链、无升档）
    不放行——满档加座纪要才有效。"""
    leader, project, solution, agent = _setup(db_session, d4_client, d4_settings)
    _confirmed_ref(db_session, project, leader)
    _seed_t1(leader, project, solution)
    _seed_gate_minutes(leader, project, solution, "T2-lite")  # 侧链封存（lite 档）
    prime_run(d4_app, scanner_factory=_refs_writer("plan.md", ("src-1",)))
    body = _start(leader, agent, project, solution, difficulty="high")
    assert body.status_code == 409, body.json
    assert body.json["error"]["code"] == "review_gate_open"  # lite 纪要放不高难度


def test_t4_full_tier_minutes_satisfy_high_difficulty(db_session, d4_client, d4_settings, d4_app) -> None:
    """T4 全链：高难度 run 先被门拦 → 对该 run 召集 T2-lite（自动升 full）→
    封存 → retry 放行且产物进终审通道。"""
    leader, project, solution, agent = _setup(db_session, d4_client, d4_settings)
    _confirmed_ref(db_session, project, leader)
    _seed_t1(leader, project, solution)
    prime_run(d4_app, scanner_factory=_refs_writer("plan.md", ("src-1",)))
    key = f"t4f:{uuid4().hex}"
    blocked = _start(leader, agent, project, solution, difficulty="high", key=key)
    assert blocked.status_code == 409, blocked.json
    run_id = blocked.json["error"]["details"]["run_id"]
    _seed_gate_minutes(leader, project, solution, "T2-lite", run_id=run_id)  # 触发 T4 升档
    prime_run(d4_app, scanner_factory=_refs_writer("plan.md", ("src-1",)))
    retried = leader.post(f"/api/v1/agents/runs/{run_id}/retry", json={})
    assert retried.status_code == 201, retried.json
    assert retried.json["data"]["status"] == "completed"
    assert retried.json["data"]["fallback_level"] is None  # 满档纪要放行 = 正常路径
    artifact = db_session.scalar(select(AgentArtifact).where(AgentArtifact.run_id == retried.json["data"]["id"]))
    assert artifact is not None
    # solution 绑定随 generate-agent 接线（d4 语义：retry 不隐式带 solution）
    assert artifact.linked_solution_id is None


def test_t4_standard_run_unaffected_by_full_tier_rule(db_session, d4_client, d4_settings) -> None:
    """standard 难度 run：lite 纪要照常放行（T4 只对 high 生效——d5 零回归）。"""
    leader, project, solution, agent = _setup(db_session, d4_client, d4_settings)
    _confirmed_ref(db_session, project, leader)
    _seed_t1(leader, project, solution)
    _seed_gate_minutes(leader, project, solution, "T2-lite")
    run = AgentRun(
        project_id=project.id,
        agent_id=agent.id,
        initiated_by_user_id=leader.user.id,
        capability_used=agent.capability_tier,
        status="completed",
        context_ref="agent-workspaces/x/context.md",
        idempotency_key=f"t4s:{uuid4().hex}",
    )
    db_session.add(run)
    db_session.commit()
    assert t2_gate_satisfied(db_session, run_id=run.id, solution_id=solution.id) is True


# ---------------------------------------------------------------------------
# T5 降级恢复补审门
# ---------------------------------------------------------------------------


def _seed_l1_family(db_session, project, leader, agent) -> AgentRun:
    """家族首个 run = L1 降级 completed（决议①形态）；第二个 run = 门拦截失败。"""
    key = f"t5:{uuid4().hex}"
    l1 = AgentRun(
        project_id=project.id,
        agent_id=agent.id,
        initiated_by_user_id=leader.user.id,
        capability_used=agent.capability_tier,
        status="completed",
        degraded=True,
        degraded_reason="tool_denied",
        fallback_level="L1",
        context_ref="agent-workspaces/x/context.md",
        idempotency_key=key,
    )
    gated = AgentRun(
        project_id=project.id,
        agent_id=agent.id,
        initiated_by_user_id=leader.user.id,
        capability_used=agent.capability_tier,
        status="failed",
        degraded=True,
        degraded_reason="review_gate_open",
        context_ref="agent-workspaces/x/context.md",
        idempotency_key=key,
    )
    db_session.add_all([l1, gated])
    db_session.commit()
    return gated


def test_t5_t2_minutes_insufficient_after_l1_recovery(db_session, d4_client, d4_settings) -> None:
    """T5：家族含 L1 run 时，T2 纪要不再满足门——只认 T5 补审纪要（服务层
    断言；T2-first 场景不发起 API run，避免重试上限耦合）。"""
    leader, project, solution, agent = _setup(db_session, d4_client, d4_settings)
    gated = _seed_l1_family(db_session, project, leader, agent)
    _seed_gate_minutes(leader, project, solution, "T2-lite")
    assert t2_gate_satisfied(db_session, run_id=gated.id, solution_id=solution.id) is False
    _seed_gate_minutes(leader, project, solution, "T5-lite")
    assert t2_gate_satisfied(db_session, run_id=gated.id, solution_id=solution.id) is True


def test_t5_minutes_satisfy_recovery_retry(db_session, d4_client, d4_settings, d4_app) -> None:
    """T5 API 全链：T5 纪要封存后，恢复家族的 retry 放行且产物进终审通道。"""
    leader, project, solution, agent = _setup(db_session, d4_client, d4_settings)
    _confirmed_ref(db_session, project, leader)  # retry 渲染上下文需确认问题引用（src-1）
    _seed_t1(leader, project, solution)
    gated = _seed_l1_family(db_session, project, leader, agent)
    # retry 不隐式携带 solution（d4 语义）→ T5 补审纪要经 run 家族直挂
    _seed_gate_minutes(leader, project, solution, "T5-lite", run_id=gated.id)
    prime_run(d4_app, scanner_factory=_refs_writer("plan.md", ("src-1",)))
    retried = leader.post(f"/api/v1/agents/runs/{gated.id}/retry", json={})
    assert retried.status_code == 201, retried.json
    assert retried.json["data"]["status"] == "completed"
    artifact = db_session.scalar(select(AgentArtifact).where(AgentArtifact.run_id == retried.json["data"]["id"]))
    assert artifact is not None and artifact.linked_solution_id is None


# ---------------------------------------------------------------------------
# 角色卡不可执行 + 种子装载
# ---------------------------------------------------------------------------


def test_persona_not_executable(db_session, d4_client, d4_settings) -> None:
    """角色卡（persona）不能发起 run：只提供评审会模拟视角（PartyMode §4.2）。"""
    leader, _project, _solution, _agent = _setup(db_session, d4_client, d4_settings)
    ensure_agent_seeds(db_session)
    db_session.commit()
    persona = db_session.scalar(select(AgentRegistry).where(AgentRegistry.kind == "persona"))
    assert persona is not None
    body = leader.post(
        f"/api/v1/agents/{persona.id}/run",
        json={"project_id": _project.id, "idempotency_key": f"persona:{uuid4().hex}"},
    )
    assert body.status_code == 409 and body.json["error"]["code"] == "persona_not_executable"


def test_difficulty_enum_validated(db_session, d4_client, d4_settings, d4_app) -> None:
    leader, project, solution, agent = _setup(db_session, d4_client, d4_settings)
    _confirmed_ref(db_session, project, leader)
    _seed_t1(leader, project, solution)
    body = _start(leader, agent, project, solution, difficulty="extreme")
    assert body.status_code == 400 and body.json["error"]["code"] == "invalid_request"


def test_agent_seeds_loaded_and_idempotent(db_session, d4_client, d4_settings) -> None:
    """S2 编排种子懒装载：守卫 + 六模块 + 三角色卡；重复装载零新增。"""
    leader, _project, _solution, _agent = _setup(db_session, d4_client, d4_settings)
    items = leader.get("/api/v1/agents").json["data"]["items"]
    tiers = {item["capability_tier"] for item in items}
    assert "agent.quality_guard" in tiers
    for module in ("presales", "solution", "pricing", "deployment", "acceptance", "knowledge"):
        assert f"agent.module.{module}" in tiers
    personas = [item for item in items if item["kind"] == "persona"]
    assert len(personas) == 3
    assert all(item["name"].startswith("模拟") for item in personas)  # PM-2 命名纪律
    again = leader.get("/api/v1/agents").json["data"]["items"]
    assert len(again) == len(items)  # 幂等
