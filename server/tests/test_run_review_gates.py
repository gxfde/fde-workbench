"""goal-d5：T2 强制门（U2）——run 状态机产物提交终审前的模板强制钩子。

U2：不召开（无已封存强制纪要）则 run 状态机不放行——迁移被拒返回
review_gate_open（状态机级强制，非 prompt）。门锚点 = solution 绑定的
completed run（artifact 提交终审 = linked_solution_id 落库，技术文档 §6
「T2→artifact 提交终审前」在本同步栈的对应迁移点）；无 solution 绑定的
探索性 run 不进终审通道，门不适用（d4 行为零回归）。
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
from fde_api.agents.models import AgentArtifact, AgentRun
from fde_api.control.api_catalog import CATALOG
from fde_api.solutions.models import ProjectSolution

_MINUTES_OK = {
    "consensus": [{"text": "产物通过评审", "source_refs": []}],
    "disputes": [],
    "todos": [],
}


def _setup(db_session, d4_client, d4_settings):
    leader = api_client(d4_client, db_session, d4_settings, "project_lead")
    project = _persist_project(db_session, leader.user, code=f"D5G{uuid4().hex[:6]}")
    solution = ProjectSolution(project_id=project.id, name="交付方案", owner_user_id=leader.user.id)
    db_session.add(solution)
    db_session.commit()
    agent = seed_agent(db_session, d4_settings)
    return leader, project, solution, agent


def _refs_writer(path: str, refs: tuple[str, ...]):
    def factory(run_id, workspace):
        output = Path(workspace) / "output"
        output.mkdir(parents=True, exist_ok=True)
        (output / path).write_text("产物正文", encoding="utf-8")
        return FakeScanner([ArtifactFile(path=path, kind="doc", source_refs=refs)])

    return factory


def _confirmed_ref(db_session, project, leader) -> None:
    """已知引用集合 = 脱敏上下文里的确认问题引用（src-1），产物校验可过。"""
    from test_goal_d2_s0_closeout import _confirmed_guidance

    _confirmed_guidance(
        db_session,
        project,
        leader.user,
        problems=[{"text": "库存数据割裂", "classification": "数据", "source_refs": ["src-1"], "confirmed": True}],
    )


def _start_run(leader, agent, project, solution) -> Any:
    return leader.post(
        f"/api/v1/agents/{agent.id}/run",
        json={
            "project_id": project.id,
            "solution_id": solution.id,
            "idempotency_key": f"t2:{uuid4().hex}",
        },
    )


def test_t2_gate_blocks_solution_bound_run_u2(db_session, d4_client, d4_settings, d4_app) -> None:
    """U2 跳过尝试：无已封存强制纪要 → 产物提交终审被拒（review_gate_open）。"""
    leader, project, solution, agent = _setup(db_session, d4_client, d4_settings)
    _confirmed_ref(db_session, project, leader)
    prime_run(d4_app, scanner_factory=_refs_writer("plan.md", ("src-1",)))
    body = _start_run(leader, agent, project, solution)
    assert body.status_code == 409, body.json
    error = body.json["error"]
    assert error["code"] == "review_gate_open"
    assert error["details"]["gate"] == "T2"
    assert error["details"]["required"] == "sealed_mandatory_minutes"

    run = db_session.get(AgentRun, error["details"]["run_id"])
    assert run.status == "failed" and run.degraded_reason == "review_gate_open"
    assert run.degraded is True
    # 先落账再拒（C-1 同款）：产物留痕但不进终审通道
    artifact = db_session.scalar(select(AgentArtifact).where(AgentArtifact.run_id == run.id))
    assert artifact is not None and artifact.reviewed is False
    assert artifact.linked_solution_id is None


def test_t2_gate_passes_after_sealed_minutes(db_session, d4_client, d4_settings, d4_app) -> None:
    """过门路径：topic_refs.solution_id 侧链封存纪要后，产物提交终审放行。"""
    leader, project, solution, agent = _setup(db_session, d4_client, d4_settings)
    _confirmed_ref(db_session, project, leader)
    convened = leader.post(
        "/api/v1/meetings",
        json={"project_id": project.id, "template_id": "T2-lite", "solution_id": solution.id},
    )
    assert convened.status_code == 201
    meeting_id = convened.json["data"]["id"]
    sealed = leader.post(f"/api/v1/meetings/{meeting_id}/close", json=_MINUTES_OK)
    assert sealed.status_code == 200, sealed.json

    prime_run(d4_app, scanner_factory=_refs_writer("plan.md", ("src-1",)))
    body = _start_run(leader, agent, project, solution)
    assert body.status_code == 201, body.json
    data = body.json["data"]
    assert data["status"] == "completed"
    artifact = db_session.scalar(select(AgentArtifact).where(AgentArtifact.run_id == data["id"]))
    assert artifact.linked_solution_id == solution.id  # 产物真正进入终审通道
    assert artifact.reviewed is False  # 终审标记仍归人工（AI 不代拍板）


def test_t2_gate_passes_via_run_linked_minutes(db_session, d4_client, d4_settings, d4_app) -> None:
    """过门路径（D7 直链 + 幂等家族）：先跑一次被门拦下，对该 run 召集并封存
    纪要，同键显式 retry 即放行——评审针对产物，不针对单次尝试。"""
    leader, project, solution, agent = _setup(db_session, d4_client, d4_settings)
    _confirmed_ref(db_session, project, leader)
    prime_run(d4_app, scanner_factory=_refs_writer("plan.md", ("src-1",)))
    blocked = leader.post(
        f"/api/v1/agents/{agent.id}/run",
        json={"project_id": project.id, "solution_id": solution.id, "idempotency_key": "t2:family-fixed"},
    )
    assert blocked.status_code == 409
    run_id = blocked.json["error"]["details"]["run_id"]

    convened = leader.post(
        "/api/v1/meetings",
        json={"project_id": project.id, "template_id": "T2-lite", "triggered_by_run_id": run_id},
    )
    assert convened.status_code == 201
    assert convened.json["data"]["triggered_by_run_id"] == run_id
    sealed = leader.post(f"/api/v1/meetings/{convened.json['data']['id']}/close", json=_MINUTES_OK)
    assert sealed.status_code == 200

    prime_run(d4_app, scanner_factory=_refs_writer("plan.md", ("src-1",)))
    retried = leader.post(f"/api/v1/agents/runs/{run_id}/retry", json={})
    assert retried.status_code == 201, retried.json
    data = retried.json["data"]
    assert data["status"] == "completed"
    assert data["retry_of"] == run_id  # 同幂等键家族——封存纪要对家族生效


def test_gate_not_applied_to_unbound_runs(db_session, d4_client, d4_settings, d4_app) -> None:
    """无 solution 绑定的探索性 run：不进终审通道，门不适用（d4 零回归）。"""
    leader, project, _solution, agent = _setup(db_session, d4_client, d4_settings)
    _confirmed_ref(db_session, project, leader)
    prime_run(d4_app, scanner_factory=_refs_writer("plan.md", ("src-1",)))
    body = leader.post(
        f"/api/v1/agents/{agent.id}/run",
        json={"project_id": project.id, "idempotency_key": f"explore:{uuid4().hex}"},
    )
    assert body.status_code == 201, body.json
    assert body.json["data"]["status"] == "completed"


def test_meetings_catalog_readonly_three_only() -> None:
    """api_catalog 只收 meetings 只读三条；召集/发言/收敛写路径不收。"""
    assert {"meetings.templates", "meetings.get", "meetings.minutes"} <= set(CATALOG)
    for key, entry in CATALOG.items():
        if key.startswith("meetings."):
            assert entry["write"] is False, key
    assert not [
        entry
        for entry in CATALOG.values()
        if entry["method"] == "POST" and str(entry["path"]).startswith("/api/v1/meetings")
    ]
