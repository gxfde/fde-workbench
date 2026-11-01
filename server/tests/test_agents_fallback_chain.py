"""goal-d6：降级链全链（V3 三重交集 / V4 手动触发 / V12 插件联动 / L1 强制人工终审 / 卡死恢复）。

判定锚：自动交付设计 §2.3/§2.4/§3 + §7.1 V3/V4/V12。断言全部落在行为事实
（run 行层级标注、产物挂载、留痕行、报因），不 mock 内部调用计数。
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy import select

from test_agents_d4_harness import (
    FakeClock,
    ScriptedEvents,
    api_client,
    prime_run,
    seed_agent,
)
from test_agents_d4_harness import d4_app, d4_client, d4_settings  # noqa: F401  (pytest fixture)
from test_document_drafts_api import _add_viewer_member, _persist_project
from test_goal_d2_s0_closeout import _confirmed_guidance

from fde_api.agents.models import AgentArtifact, AgentRegistry, AgentRun, SolutionReviewCheckpoint
from fde_api.agents.tools import effective_run_tools, run_face_declared
from fde_api.control.models import PluginInstallation, PluginPackage
from fde_api.meetings.templates import MEETING_AGENT_TOOLS
from fde_api.solutions.models import ProjectSolution


def _sealed_meeting(leader, project, solution_id: str) -> None:
    """T2 门放行前置：人工开会 + 空引用三段式封存（T-1 先例）。"""
    convened = leader.post(
        "/api/v1/meetings",
        json={"project_id": project.id, "template_id": "T2-lite", "solution_id": solution_id},
    )
    assert convened.status_code == 201, convened.json
    sealed = leader.post(
        f"/api/v1/meetings/{convened.json['data']['id']}/close",
        json={"consensus": [{"text": "产物评审通过", "source_refs": []}], "disputes": [], "todos": []},
    )
    assert sealed.status_code == 200, sealed.json


def _scanner_factory(run_id, workspace):
    from pathlib import Path

    from test_agents_d4_harness import FakeScanner

    from fde_api.agents.adapter import ArtifactFile

    output = Path(workspace) / "output"
    output.mkdir(parents=True, exist_ok=True)
    (output / "plan.md").write_text("降级链测试产物", encoding="utf-8")
    return FakeScanner([ArtifactFile(path="plan.md", kind="doc", source_refs=("src-1",))])


# ---------------------------------------------------------------------------
# V4：演练面（每级手动可触发）
# ---------------------------------------------------------------------------


def test_rehearsal_l1_l2_run_shapes(db_session, d4_client, d4_app, d4_settings) -> None:
    """L1 演练=降级 completed 形态；L2 演练=failed 形态；零计费 + rehearsal 键。"""
    admin = api_client(d4_client, db_session, d4_settings, "admin")
    project = _persist_project(db_session, admin.user, code=f"RH{uuid4().hex[:4]}")
    agent = seed_agent(db_session, d4_settings)
    l1 = admin.post(f"/api/v1/agents/{agent.id}/fallback-rehearsal", json={"level": "L1", "project_id": project.id})
    assert l1.status_code == 200, l1.json
    row = l1.json["data"]
    assert row["status"] == "completed" and row["fallback_level"] == "L1"
    assert row["degraded"] is True and row["degraded_reason"] == "fallback_rehearsal"
    assert row["token_cost"] == 0 and row["idempotency_key"].startswith("rehearsal:")
    l2 = admin.post(f"/api/v1/agents/{agent.id}/fallback-rehearsal", json={"level": "L2", "project_id": project.id})
    assert l2.status_code == 200, l2.json
    row = l2.json["data"]
    assert row["status"] == "failed" and row["fallback_level"] == "L2" and row["token_cost"] == 0


def test_rehearsal_forbidden_and_validation(db_session, d4_client, d4_app, d4_settings) -> None:
    """非 admin 403；level 非法 400；agent/项目不存在 404。"""
    leader = api_client(d4_client, db_session, d4_settings, "project_lead")
    admin = api_client(d4_client, db_session, d4_settings, "admin")
    project = _persist_project(db_session, leader.user, code=f"RH{uuid4().hex[:4]}")
    agent = seed_agent(db_session, d4_settings)
    assert leader.post(f"/api/v1/agents/{agent.id}/fallback-rehearsal", json={"level": "L1", "project_id": project.id}).status_code == 403
    assert admin.post(f"/api/v1/agents/{agent.id}/fallback-rehearsal", json={"level": "L3", "project_id": project.id}).status_code == 400
    assert admin.post(f"/api/v1/agents/none/fallback-rehearsal", json={"level": "L1", "project_id": project.id}).status_code == 404
    assert admin.post(f"/api/v1/agents/{agent.id}/fallback-rehearsal", json={"level": "L1", "project_id": "none"}).status_code == 404


def test_tool_denied_run_lands_l1_forced_manual_review(db_session, d4_client, d4_app, d4_settings) -> None:
    """D 类真实降级：tool_denied → completed + L1；产物即使过 T2 门也
    linked=None（强制人工终审，不可自动放行）。"""
    leader = api_client(d4_client, db_session, d4_settings, "project_lead")
    project = _persist_project(db_session, leader.user, code=f"L1{uuid4().hex[:4]}")
    _confirmed_guidance(
        db_session, project, leader.user,
        problems=[{"text": "数据割裂", "classification": "数据", "source_refs": ["src-1"], "confirmed": True}],
    )
    solution = ProjectSolution(project_id=project.id, name="交付方案", owner_user_id=leader.user.id)
    db_session.add(solution)
    db_session.commit()
    agent = seed_agent(db_session, d4_settings)
    # goal-d7 T1 前置闸适配：产物生成 run 前须有已封存 T1 纪要侧链 solution
    t1 = leader.post(
        "/api/v1/meetings",
        json={"project_id": project.id, "template_id": "T1-lite", "solution_id": solution.id},
    )
    assert t1.status_code == 201, t1.json
    sealed_t1 = leader.post(
        f"/api/v1/meetings/{t1.json['data']['id']}/close",
        json={"consensus": [{"text": "计划评审通过", "source_refs": []}], "disputes": [], "todos": []},
    )
    assert sealed_t1.status_code == 200, sealed_t1.json
    _sealed_meeting(leader, project, solution.id)  # 门已放行——但 L1 仍不得自动进终审
    prime_run(
        d4_app,
        events=ScriptedEvents([[{"type": "tool_call", "tool": "write_file"}], [{"type": "done", "exit_code": 0}]]),
        scanner_factory=_scanner_factory,
    )
    body = leader.post(
        f"/api/v1/agents/{agent.id}/run",
        json={"project_id": project.id, "solution_id": solution.id, "idempotency_key": f"l1:{uuid4().hex}"},
    )
    assert body.status_code == 201, body.json
    run = body.json["data"]
    assert run["status"] == "completed"
    assert run["degraded"] is True and run["fallback_level"] == "L1"
    assert run["artifacts"][0]["linked_solution_id"] is None  # 决议①：L1 永不自动进终审
    assert run["artifacts"][0]["reviewed"] is False


def test_l1_completed_handoff_keeps_l1_facts(db_session, d4_client, d4_app, d4_settings) -> None:
    """L1 completed 可转人工（V7 收口）；fallback_level=L1 与降级原因保留，
    接管事实由 handoff_user_id + signoff checkpoint 承载；二次 handoff 409。"""
    leader = api_client(d4_client, db_session, d4_settings, "project_lead")
    project = _persist_project(db_session, leader.user, code=f"L1{uuid4().hex[:4]}")
    _confirmed_guidance(
        db_session, project, leader.user,
        problems=[{"text": "数据割裂", "classification": "数据", "source_refs": ["src-1"], "confirmed": True}],
    )
    agent = seed_agent(db_session, d4_settings)
    prime_run(
        d4_app,
        events=ScriptedEvents([[{"type": "tool_call", "tool": "write_file"}], [{"type": "done", "exit_code": 0}]]),
        scanner_factory=_scanner_factory,
    )
    body = leader.post(
        f"/api/v1/agents/{agent.id}/run", json={"project_id": project.id, "idempotency_key": f"l1h:{uuid4().hex}"}
    )
    assert body.status_code == 201, body.json
    run = body.json["data"]
    assert run["fallback_level"] == "L1"
    handed = leader.post(f"/api/v1/agents/runs/{run['id']}/handoff", json={})
    assert handed.status_code == 200, handed.json
    row = handed.json["data"]
    assert row["handoff_user_id"] == leader.user.id
    assert row["fallback_level"] == "L1"  # 降级事实不被 L3 覆写（自动交付 §3.5）
    assert row["degraded_reason"] == "tool_denied"
    checkpoint = db_session.scalar(
        select(SolutionReviewCheckpoint).where(SolutionReviewCheckpoint.solution_id.is_(None))
    )
    assert checkpoint is None  # 未带 solution_id → 不挂检查点（与 d4 语义一致）
    again = leader.post(f"/api/v1/agents/runs/{run['id']}/handoff", json={})
    assert again.status_code == 409 and again.json["error"]["code"] == "agent_handoff_exists"


def test_normal_run_handoff_still_l3(db_session, d4_client, d4_app, d4_settings) -> None:
    """L3 语义零回归：失败 run 的 handoff 仍落 L3 + ai_manual_handoff。"""
    leader = api_client(d4_client, db_session, d4_settings, "project_lead")
    project = _persist_project(db_session, leader.user, code=f"L3{uuid4().hex[:4]}")
    agent = seed_agent(db_session, d4_settings)
    prime_run(d4_app, events=ScriptedEvents([[{"type": "done", "exit_code": 1}]]))
    run = leader.post(
        f"/api/v1/agents/{agent.id}/run", json={"project_id": project.id, "idempotency_key": f"l3:{uuid4().hex}"}
    ).json["data"]
    assert run["status"] == "failed" and run["fallback_level"] == "L2"  # 决议②：B 类失败去向 L2
    handed = leader.post(f"/api/v1/agents/runs/{run['id']}/handoff", json={})
    assert handed.status_code == 200
    row = handed.json["data"]
    assert row["fallback_level"] == "L3" and row["degraded_reason"] == "ai_manual_handoff"


def test_timeout_run_lands_l2(db_session, d4_client, d4_app, d4_settings) -> None:
    """B-1 超时：kill 后 fallback_level=L2（无产物 → 模板填空）。"""
    leader = api_client(d4_client, db_session, d4_settings, "project_lead")
    project = _persist_project(db_session, leader.user, code=f"TO{uuid4().hex[:4]}")
    agent = seed_agent(db_session, d4_settings, max_duration_ms=100)
    prime_run(
        d4_app,
        events=ScriptedEvents([[{"type": "cost", "units": 1}]]),
        clock=FakeClock(),
    )
    body = leader.post(
        f"/api/v1/agents/{agent.id}/run", json={"project_id": project.id, "idempotency_key": f"to:{uuid4().hex}"}
    )
    assert body.status_code == 201, body.json
    run = body.json["data"]
    assert run["status"] == "timeout" and run["fallback_level"] == "L2"
    assert run["artifacts"] == []


# ---------------------------------------------------------------------------
# V3 后半：三重交集（发起时刻 effective_run_tools）
# ---------------------------------------------------------------------------


def test_v3_write_and_meeting_tools_stripped(db_session, d4_client, d4_app, d4_settings) -> None:
    """写类默认不授予（§2.3）；会议面二工具不入 run 面（U8 落点分离）。"""
    leader = api_client(d4_client, db_session, d4_settings, "project_lead")
    declared = ["read_file", "api_execute", "file_send_wechat", *MEETING_AGENT_TOOLS]
    effective = effective_run_tools(db_session, allowed_tools=declared, actor=leader.user)
    assert effective == frozenset({"read_file"})
    assert run_face_declared(declared) == frozenset({"read_file", "api_execute", "file_send_wechat"})


def test_v12_plugin_disable_shrinks_new_run_allowlist(db_session, d4_client, d4_app, d4_settings) -> None:
    """V12：插件安装态实时闸——installed → 工具在；disable → 新 run 收紧；
    等级地板恒生效（非 system_operator 即使有安装也不放行 lcsc.browse）。"""
    admin = api_client(d4_client, db_session, d4_settings, "admin")
    lead = api_client(d4_client, db_session, d4_settings, "project_lead")
    plugin = PluginPackage(plugin_key=f"lcsc-{uuid4().hex[:6]}", name="立创插件", current_version="1.0.0", package_sha256="0" * 64, created_by_user_id=admin.user.id, manifest_json={"capabilities": ["lcsc.browse"]})
    db_session.add(plugin)
    db_session.commit()
    installation = PluginInstallation(
        plugin_id=plugin.id, user_id=admin.user.id, installed_version="1.0.0",
        granted_capabilities=["lcsc.browse"], status="installed",
    )
    db_session.add(installation)
    db_session.commit()
    declared = ["lcsc_search", "read_file"]
    assert effective_run_tools(db_session, allowed_tools=declared, actor=admin.user) == frozenset(declared)
    # 等级地板：project_lead（project_manager < system_operator）有安装也不放行
    lead_install = PluginInstallation(
        plugin_id=plugin.id, user_id=lead.user.id, installed_version="1.0.0",
        granted_capabilities=["lcsc.browse"], status="installed",
    )
    db_session.add(lead_install)
    db_session.commit()
    assert "lcsc_search" not in effective_run_tools(db_session, allowed_tools=declared, actor=lead.user)
    # 插件 disable → 实时收紧（V12 白名单同步）
    installation.status = "disabled"
    db_session.commit()
    assert effective_run_tools(db_session, allowed_tools=declared, actor=admin.user) == frozenset({"read_file"})


def test_v12_all_tools_dead_marks_agent_unavailable(db_session, d4_client, d4_app, d4_settings) -> None:
    """声明工具全部失效 → GET /agents 明确报因 tools_unavailable；start 409。"""
    admin = api_client(d4_client, db_session, d4_settings, "admin")
    plugin = PluginPackage(plugin_key=f"lcsc-{uuid4().hex[:6]}", name="立创插件", current_version="1.0.0", package_sha256="0" * 64, created_by_user_id=admin.user.id, manifest_json={"capabilities": ["lcsc.browse"]})
    db_session.add(plugin)
    db_session.commit()
    db_session.add(PluginInstallation(
        plugin_id=plugin.id, user_id=admin.user.id, installed_version="1.0.0",
        granted_capabilities=["lcsc.browse"], status="installed",
    ))
    agent = seed_agent(db_session, d4_settings, allowed_tools=("lcsc_search",))
    listing = admin.get("/api/v1/agents").json["data"]["items"]
    row = next(item for item in listing if item["id"] == agent.id)
    assert row["available"] is True and row["unavailable_reason"] is None
    installation = db_session.scalar(select(PluginInstallation).where(PluginInstallation.user_id == admin.user.id))
    installation.status = "disabled"
    db_session.commit()
    listing = admin.get("/api/v1/agents").json["data"]["items"]
    row = next(item for item in listing if item["id"] == agent.id)
    assert row["available"] is False and row["unavailable_reason"] == "tools_unavailable"
    project = _persist_project(db_session, admin.user, code=f"V12{uuid4().hex[:4]}")
    denied = admin.post(
        f"/api/v1/agents/{agent.id}/run", json={"project_id": project.id, "idempotency_key": f"v12:{uuid4().hex}"}
    )
    assert denied.status_code == 409 and denied.json["error"]["details"]["reason"] == "tools_unavailable"


# ---------------------------------------------------------------------------
# run 卡死恢复（d5 挂账）
# ---------------------------------------------------------------------------


def _seed_stuck_run(db_session, project, leader, agent, *, status="running", age_seconds=3600) -> AgentRun:
    run = AgentRun(
        project_id=project.id,
        agent_id=agent.id,
        initiated_by_user_id=leader.user.id,
        capability_used=agent.capability_tier,
        status=status,
        context_ref="agent-workspaces/stuck/context.md",
        idempotency_key=f"stuck:{uuid4().hex}",
    )
    db_session.add(run)
    db_session.commit()
    run.updated_at = datetime.now(timezone.utc) - timedelta(seconds=age_seconds)
    db_session.commit()
    return run


def test_recover_stuck_run(db_session, d4_client, d4_app, d4_settings) -> None:
    """卡死 running 过阈值 → recover 落 failed + stuck_recovered + 事件。"""
    leader = api_client(d4_client, db_session, d4_settings, "project_lead")
    project = _persist_project(db_session, leader.user, code=f"RC{uuid4().hex[:4]}")
    agent = seed_agent(db_session, d4_settings)
    run = _seed_stuck_run(db_session, project, leader, agent)
    body = leader.post(f"/api/v1/agents/runs/{run.id}/recover")
    assert body.status_code == 200, body.json
    row = body.json["data"]
    assert row["status"] == "failed" and row["degraded"] is True and row["degraded_reason"] == "stuck_recovered"
    db_session.expire_all()
    assert db_session.get(AgentRun, run.id).status == "failed"


def test_recover_fresh_window_and_terminal_states(db_session, d4_client, d4_app, d4_settings) -> None:
    """新鲜窗口内 409 not_stale；终态 run 409 not_allowed；他人 run 403。"""
    leader = api_client(d4_client, db_session, d4_settings, "project_lead")
    other = api_client(d4_client, db_session, d4_settings, "admin")  # admin 可恢复（非发起人也放行）
    peer = api_client(d4_client, db_session, d4_settings, "fde_engineer")
    project = _persist_project(db_session, leader.user, code=f"RC{uuid4().hex[:4]}")
    _add_viewer_member(db_session, project, peer.user)  # 项目成员（非发起人）→ recover_forbidden
    agent = seed_agent(db_session, d4_settings)
    fresh = _seed_stuck_run(db_session, project, leader, agent, age_seconds=0)
    body = leader.post(f"/api/v1/agents/runs/{fresh.id}/recover")
    assert body.status_code == 409 and body.json["error"]["code"] == "agent_recover_not_stale"
    done = _seed_stuck_run(db_session, project, leader, agent, status="completed")
    body = leader.post(f"/api/v1/agents/runs/{done.id}/recover")
    assert body.status_code == 409 and body.json["error"]["code"] == "agent_recover_not_allowed"
    stale = _seed_stuck_run(db_session, project, leader, agent)
    body = peer.post(f"/api/v1/agents/runs/{stale.id}/recover")
    assert body.status_code == 403 and body.json["error"]["code"] == "agent_recover_forbidden"  # 成员但非发起人
    assert other.post(f"/api/v1/agents/runs/{stale.id}/recover").status_code == 200  # admin 兜底
