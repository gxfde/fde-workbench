"""goal-d4：V6 产物校验（C-1）+ V7 ai_manual_handoff 终审必填（E-2）。

C-1：缺/未知 source_refs、非法 kind、缺文件 → run failed + 422 失败码可见，
产物 reviewed=False 永不进终审；回退补录 = 校正后 retry 重跑。
V7：失败 run 转人工 → 接管人落 run（fallback L3）+ 挂 pending signoff
终审检查点（project_manager 档）。
"""
from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from sqlalchemy import select

from test_agents_d4_harness import (
    FakeScanner,
    ScriptedEvents,
    api_client,
    prime_run,
    seed_agent,
)
from test_document_drafts_api import _persist_project

from fde_api.agents.adapter import ArtifactFile
from fde_api.agents.models import AgentArtifact, AgentRun, SolutionReviewCheckpoint
from test_agents_d4_harness import d4_app, d4_client, d4_settings  # noqa: F401  (pytest fixture)


def _setup(db_session, d4_client, d4_settings, *, with_solution: bool = True):
    leader = api_client(d4_client, db_session, d4_settings, "project_lead")
    project = _persist_project(db_session, leader.user, code=f"D4V{uuid4().hex[:6]}")
    solution = None
    if with_solution:
        from fde_api.solutions.models import ProjectSolution

        solution = ProjectSolution(project_id=project.id, name="交付方案", owner_user_id=leader.user.id)
        db_session.add(solution)
        db_session.commit()
    agent = seed_agent(db_session, d4_settings)
    return leader, project, solution, agent


def _writer(path: str, content: str):
    def factory(run_id, workspace):
        output = Path(workspace) / "output"
        output.mkdir(parents=True, exist_ok=True)
        (output / path).write_text(content, encoding="utf-8")
        return FakeScanner([ArtifactFile(path=path, kind="doc", source_refs=())])

    return factory


def test_c1_artifact_without_source_refs_rejected_and_retry_recovers(
    db_session, d4_client, d4_app, d4_settings
) -> None:
    """C-1：缺 source_refs → 422 + 失败码 + 产物不进终审；校正后 retry 即回退补录。"""
    from test_goal_d2_s0_closeout import _confirmed_guidance

    leader, project, _solution, agent = _setup(db_session, d4_client, d4_settings, with_solution=False)
    # 已知引用集合 = 脱敏上下文里的确认问题引用（src-1）
    _confirmed_guidance(
        db_session,
        project,
        leader.user,
        problems=[{"text": "库存数据割裂", "classification": "数据", "source_refs": ["src-1"], "confirmed": True}],
    )
    prime_run(d4_app, scanner_factory=_writer("plan.md", "初版草案"))
    body = leader.post(
        f"/api/v1/agents/{agent.id}/run",
        json={"project_id": project.id, "idempotency_key": f"c1:{uuid4().hex}"},
    )
    assert body.status_code == 422
    error = body.json["error"]
    assert error["code"] == "artifact_validation_failed"
    assert error["details"]["failures"][0]["reasons"] == ["missing_source_refs"]
    run_id = error["details"]["run_id"]

    stored = db_session.get(AgentRun, run_id)
    assert stored.status == "failed" and stored.degraded_reason == "artifact_validation_failed"
    artifact = db_session.scalar(select(AgentArtifact).where(AgentArtifact.run_id == run_id))
    assert artifact is not None and artifact.reviewed is False  # 留痕但不进终审

    # 回退补录：同一 run 显式 retry，产物补上合法引用 → 放行进正常流
    def fixed_factory(run_id, workspace):
        output = Path(workspace) / "output"
        output.mkdir(parents=True, exist_ok=True)
        (output / "plan.md").write_text("补录后草案", encoding="utf-8")
        return FakeScanner([ArtifactFile(path="plan.md", kind="doc", source_refs=("src-1",))])

    prime_run(d4_app, scanner_factory=fixed_factory)
    retried = leader.post(f"/api/v1/agents/runs/{run_id}/retry", json=None)
    assert retried.status_code == 201, retried.json
    assert retried.json["data"]["status"] == "completed"
    assert retried.json["data"]["artifacts"][0]["reviewed"] is False


def test_c1_unknown_refs_and_invalid_kind_rejected(db_session, d4_client, d4_app, d4_settings) -> None:
    """未知引用 → unknown_source_refs；非法 kind → invalid_kind。"""
    leader, project, _solution, agent = _setup(db_session, d4_client, d4_settings, with_solution=False)

    def factory(run_id, workspace):
        output = Path(workspace) / "output"
        output.mkdir(parents=True, exist_ok=True)
        (output / "plan.md").write_text("内容", encoding="utf-8")
        return FakeScanner(
            [
                ArtifactFile(path="plan.md", kind="doc", source_refs=("ghost-ref",)),
                ArtifactFile(path="extra.bin", kind="binary", source_refs=()),
            ]
        )

    prime_run(d4_app, scanner_factory=factory)
    body = leader.post(
        f"/api/v1/agents/{agent.id}/run",
        json={"project_id": project.id, "idempotency_key": f"c1b:{uuid4().hex}"},
    )
    assert body.status_code == 422
    failures = {entry["path"]: set(entry["reasons"]) for entry in body.json["error"]["details"]["failures"]}
    assert failures["plan.md"] == {"unknown_source_refs"}
    # extra.bin 声明了但文件没写 → kind/指纹两处不过；本用例未铺 confirmed
    # guidance（known_refs=∅），空引用不再单列 missing（N1 重跑二语义修正）
    assert failures["extra.bin"] == {"invalid_kind", "file_missing"}


def test_c1_missing_file_rejected(db_session, d4_client, d4_app, d4_settings) -> None:
    """manifest 声明了产物但文件不存在 → file_missing（指纹无法成立）。"""
    from test_goal_d2_s0_closeout import _confirmed_guidance

    leader, project, _solution, agent = _setup(db_session, d4_client, d4_settings, with_solution=False)
    _confirmed_guidance(
        db_session,
        project,
        leader.user,
        problems=[{"text": "引用锚", "classification": "数据", "source_refs": ["src-1"], "confirmed": True}],
    )
    prime_run(
        d4_app,
        scanner_factory=lambda run_id, workspace: FakeScanner(
            [ArtifactFile(path="ghost.md", kind="doc", source_refs=("src-1",))]
        ),
    )
    body = leader.post(
        f"/api/v1/agents/{agent.id}/run",
        json={"project_id": project.id, "idempotency_key": f"c1c:{uuid4().hex}"},
    )
    assert body.status_code == 422
    assert body.json["error"]["details"]["failures"][0]["reasons"] == ["file_missing"]


def test_v7_handoff_closes_run_and_requires_signoff(db_session, d4_client, d4_app, d4_settings) -> None:
    """V7/E-2：失败 run 转人工 → 接管人 + L3 + pending signoff 终审检查点。"""
    leader, project, solution, agent = _setup(db_session, d4_client, d4_settings)
    prime_run(d4_app, events=ScriptedEvents([[{"type": "done", "exit_code": 1}]]))
    run_id = leader.post(
        f"/api/v1/agents/{agent.id}/run",
        json={"project_id": project.id, "idempotency_key": f"v7:{uuid4().hex}"},
    ).json["data"]["id"]

    # 第二条 run 用成功事件流（每次 run 拿全新克隆流，重挂工厂即可换脚本）
    prime_run(d4_app, events=ScriptedEvents([[{"type": "done", "exit_code": 0}]]))
    completed_run = leader.post(
        f"/api/v1/agents/{agent.id}/run",
        json={"project_id": project.id, "idempotency_key": f"v7ok:{uuid4().hex}"},
    )
    assert completed_run.status_code == 201
    # completed run 不可转人工
    bad = leader.post(f"/api/v1/agents/runs/{completed_run.json['data']['id']}/handoff", json={"solution_id": solution.id})
    assert bad.status_code == 409
    assert bad.json["error"]["code"] == "agent_handoff_not_allowed"

    handed = leader.post(f"/api/v1/agents/runs/{run_id}/handoff", json={"solution_id": solution.id})
    assert handed.status_code == 200
    data = handed.json["data"]
    assert data["handoff_user_id"] == leader.user.id
    assert data["fallback_level"] == "L3"
    assert data["degraded"] is True and data["degraded_reason"] == "ai_manual_handoff"
    assert data["signoff_checkpoint_id"] is not None

    checkpoint = db_session.get(SolutionReviewCheckpoint, data["signoff_checkpoint_id"])
    assert checkpoint.status == "pending"
    assert checkpoint.checkpoint_type == "signoff"
    assert checkpoint.required_level == "project_manager"

    # 终审必填的幂等边：重复接管 409；同 solution 不重复挂检查点
    again = leader.post(f"/api/v1/agents/runs/{run_id}/handoff", json={"solution_id": solution.id})
    assert again.status_code == 409
    assert again.json["error"]["code"] == "agent_handoff_exists"


def test_v7_handoff_without_solution_skips_checkpoint_and_blocks_outsiders(
    db_session, d4_client, d4_app, d4_settings
) -> None:
    """无 solution 的 handoff 只收口 run；项目外人员 403。"""
    leader, project, _solution, agent = _setup(db_session, d4_client, d4_settings)
    prime_run(d4_app, events=ScriptedEvents([[{"type": "done", "exit_code": 1}]]))
    run_id = leader.post(
        f"/api/v1/agents/{agent.id}/run",
        json={"project_id": project.id, "idempotency_key": f"v7b:{uuid4().hex}"},
    ).json["data"]["id"]

    handed = leader.post(f"/api/v1/agents/runs/{run_id}/handoff", json={})
    assert handed.status_code == 200
    assert handed.json["data"]["signoff_checkpoint_id"] is None

    prime_run(d4_app, events=ScriptedEvents([[{"type": "done", "exit_code": 1}]]))
    outsider_run = leader.post(
        f"/api/v1/agents/{agent.id}/run",
        json={"project_id": project.id, "idempotency_key": f"v7c:{uuid4().hex}"},
    ).json["data"]["id"]
    outsider = api_client(d4_client, db_session, d4_settings, "fde_engineer")
    assert outsider.post(f"/api/v1/agents/runs/{outsider_run}/handoff", json={}).status_code == 403


def test_c1_no_confirmed_problems_allows_empty_source_refs(
    db_session, d4_client, d4_app, d4_settings
) -> None:
    """N1 重跑二回归钉（run a5773e26，2026-11-09 实测）：无确认问题
    （known_refs=∅）是售前发现期合法态——空 source_refs 放行进正常流；
    自创引用仍拦（known_refs=∅ 下任何非空引用都越界）。有确认问题时的
    追溯义务不减（missing/unknown 由既有两用例覆盖）。"""
    leader, project, _solution, agent = _setup(db_session, d4_client, d4_settings, with_solution=False)

    def factory(run_id, workspace):
        output = Path(workspace) / "output"
        output.mkdir(parents=True, exist_ok=True)
        (output / "brief.md").write_text("售前简报（无确认问题态）", encoding="utf-8")
        return FakeScanner([ArtifactFile(path="brief.md", kind="doc", source_refs=())])

    prime_run(d4_app, scanner_factory=factory)
    body = leader.post(
        f"/api/v1/agents/{agent.id}/run",
        json={"project_id": project.id, "idempotency_key": f"c1e:{uuid4().hex}"},
    )
    assert body.status_code == 201, body.json
    assert body.json["data"]["status"] == "completed"
    assert body.json["data"]["artifacts"][0]["reviewed"] is False  # 留痕待人工接受

    def ghost_factory(run_id, workspace):
        output = Path(workspace) / "output"
        output.mkdir(parents=True, exist_ok=True)
        (output / "ghost.md").write_text("自创引用草稿", encoding="utf-8")
        return FakeScanner([ArtifactFile(path="ghost.md", kind="doc", source_refs=("ghost-ref",))])

    prime_run(d4_app, scanner_factory=ghost_factory)
    ghost = leader.post(
        f"/api/v1/agents/{agent.id}/run",
        json={"project_id": project.id, "idempotency_key": f"c1e2:{uuid4().hex}"},
    )
    assert ghost.status_code == 422
    failures = ghost.json["error"]["details"]["failures"]
    assert failures[0]["reasons"] == ["unknown_source_refs"]
