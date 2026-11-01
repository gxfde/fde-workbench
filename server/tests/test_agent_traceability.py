"""goal-d4：V9 溯源反查链（T-1）。

链路：solution（SOW 母体，agent_run_id 锚）→ GET run 溯源 → 产物 sha256
指纹 → context_ref（脱敏上下文文件）→ ProblemItem.source_refs 反查。
SOW export 行段随 d6 generate-agent 接线；本锚用 solution 段同链验证。
"""
from __future__ import annotations

import hashlib
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
from test_goal_d2_s0_closeout import _confirmed_guidance

from fde_api.agents.adapter import ArtifactFile
from fde_api.control.api_catalog import CATALOG
from fde_api.solutions.models import ProjectSolution
from test_agents_d4_harness import d4_app, d4_client, d4_settings  # noqa: F401  (pytest fixture)


def _scanner_factory(run_id, workspace):
    output = Path(workspace) / "output"
    output.mkdir(parents=True, exist_ok=True)
    (output / "plan.md").write_text("部署计划草案（由脱敏上下文衍生）", encoding="utf-8")
    return FakeScanner([ArtifactFile(path="plan.md", kind="doc", source_refs=("src-1",))])


def test_t1_reverse_chain_from_solution_to_problem_refs(db_session, d4_client, d4_app, d4_settings) -> None:
    """T-1：solution → run → 产物指纹 → context 文件 → source_refs 全链可反查。"""
    leader = api_client(d4_client, db_session, d4_settings, "project_lead")
    project = _persist_project(db_session, leader.user, code=f"T1{uuid4().hex[:4]}")
    _confirmed_guidance(
        db_session,
        project,
        leader.user,
        problems=[{"text": "库存与订单数据割裂", "classification": "数据", "source_refs": ["src-1"], "confirmed": True}],
    )
    solution = ProjectSolution(project_id=project.id, name="交付方案", owner_user_id=leader.user.id)
    db_session.add(solution)
    db_session.commit()
    agent = seed_agent(db_session, d4_settings)
    # goal-d7 T1 前置闸适配：产物生成 run 前须有已封存 T1 纪要侧链 solution
    # （T1 纪要与 T2 门语义分离，不替代下方 T2 纪要）
    t1_convened = leader.post(
        "/api/v1/meetings",
        json={"project_id": project.id, "template_id": "T1-lite", "solution_id": solution.id},
    )
    assert t1_convened.status_code == 201, t1_convened.json
    t1_sealed = leader.post(
        f"/api/v1/meetings/{t1_convened.json['data']['id']}/close",
        json={"consensus": [{"text": "计划评审通过", "source_refs": []}], "disputes": [], "todos": []},
    )
    assert t1_sealed.status_code == 200, t1_sealed.json
    # goal-d5 T2 强制门：solution 绑定的 run 须先有已封存强制纪要（d3→d4
    # allowlist 断言升级同款演进；空引用三段式 = 守卫复核平凡闭合）
    convened = leader.post(
        "/api/v1/meetings",
        json={"project_id": project.id, "template_id": "T2-lite", "solution_id": solution.id},
    )
    assert convened.status_code == 201, convened.json
    sealed = leader.post(
        f"/api/v1/meetings/{convened.json['data']['id']}/close",
        json={"consensus": [{"text": "产物评审通过", "source_refs": []}], "disputes": [], "todos": []},
    )
    assert sealed.status_code == 200, sealed.json
    prime_run(
        d4_app,
        events=ScriptedEvents([[{"type": "tool_call", "tool": "read_file"}], [{"type": "done", "exit_code": 0}]]),
        scanner_factory=_scanner_factory,
    )

    body = leader.post(
        f"/api/v1/agents/{agent.id}/run",
        json={"project_id": project.id, "solution_id": solution.id, "idempotency_key": f"t1:{uuid4().hex}"},
    )
    assert body.status_code == 201, body.json
    run = body.json["data"]
    assert run["status"] == "completed"
    # 产物段：sha256 与文件内容一致、reviewed=False（终审人工）、挂 solution
    artifact = run["artifacts"][0]
    content = "部署计划草案（由脱敏上下文衍生）".encode("utf-8")
    assert artifact["sha256"] == hashlib.sha256(content).hexdigest()
    assert len(artifact["sha256"]) == 64 and artifact["reviewed"] is False
    assert artifact["linked_solution_id"] == solution.id

    # solution 段（SOW 母体锚）：agent_run_id 指回 run
    solution.agent_run_id = run["id"]
    db_session.commit()
    assert solution.agent_run_id == run["id"]

    # run 段（溯源接口）→ context 段（脱敏文件）→ 问题引用段
    detail = leader.get(f"/api/v1/agents/runs/{run['id']}")
    assert detail.status_code == 200
    context_ref = detail.json["data"]["context_ref"]
    context_path = Path(d4_settings.agent_workspace_root) / run["id"] / "context.md"
    assert context_ref.endswith(f"{run['id']}/context.md")
    rendered = context_path.read_text(encoding="utf-8")
    assert "src-1" in rendered and "库存与订单数据割裂" in rendered
    assert project.project_code in rendered
    assert "[REDACTED" not in rendered  # 干净输入零遮蔽占位

    # 问题引用段（反查终点）：引用可回到访谈证据锚
    from fde_api.guidance.models import ProjectGuidanceAnalysis

    row = db_session.scalar(
        select(ProjectGuidanceAnalysis).where(ProjectGuidanceAnalysis.project_id == project.id)
    )
    refs_in_problem = row.key_business_problems_json[0]["source_refs"]
    assert refs_in_problem == ["src-1"]


def test_agents_catalog_exposes_readonly_four_only() -> None:
    """api_catalog 只收 agents 只读（goal-d7 起 5 条：+agents.quota O-3 配额）；
    写路径（run/handoff/retry/rehearse/recover）不收。"""
    readonly = {"agents.list", "agents.run_get", "agents.tool_calls", "agents.cost", "agents.quota"}
    assert readonly <= set(CATALOG)
    for key in readonly:
        assert CATALOG[key]["method"] == "GET"
        assert CATALOG[key]["write"] is False
    for key in CATALOG:
        assert not key.startswith("agents.") or key in readonly
