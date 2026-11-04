"""goal-d6：降级链全链（V3 三重交集 / V4 手动触发 / V12 插件联动 / L1 强制人工终审 / 卡死恢复）。

判定锚：自动交付设计 §2.3/§2.4/§3 + §7.1 V3/V4/V12。断言全部落在行为事实
（run 行层级标注、产物挂载、留痕行、报因），不 mock 内部调用计数。
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy import select

from test_agents_d4_harness import (
    FakeClock,
    ScriptedEvents,
    api_client,
    make_user,
    prime_run,
    seed_agent,
)
from test_agents_d4_harness import d4_app, d4_client, d4_settings  # noqa: F401  (pytest fixture)
from test_document_drafts_api import _add_viewer_member, _persist_project
from test_goal_d2_s0_closeout import _confirmed_guidance

from fde_api.agents.models import AgentArtifact, AgentRegistry, AgentRun, SolutionReviewCheckpoint
from fde_api.agents.service import _unavailability
from fde_api.agents.tools import (
    KNOWN_TOOL_NAMES,
    _load_tool_groups,
    effective_run_tools,
    load_tool_groups,
    resolve_tool_groups,
    run_face_declared,
)
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


# ---------------------------------------------------------------------------
# T-R1（agent-policy P1-R1 ToolGroup）：只读工具组目录——group: 引用解析
# ---------------------------------------------------------------------------


def test_tool_group_seed_loads_and_rejects_unknown_tool(tmp_path) -> None:
    """真种子装载干净且全部组工具 ∈ 已知全集；组引用未知工具 fail-fast。"""
    groups = load_tool_groups()
    assert set(groups) == {"research-readonly", "ops-readonly"}
    for name, tools in groups.items():
        assert tools, f"组 {name} 非空"
        assert set(tools) <= KNOWN_TOOL_NAMES, f"组 {name} 引用未知工具"
    # 坏种子：组引用未知工具 → RuntimeError（沿 agents.json 校验先例，宁拒不缩）
    bad = tmp_path / "tool_groups.json"
    bad.write_text(
        json.dumps({"tool_groups": [{"name": "bad", "tools": ["ghost_tool"], "is_active": True}]}),
        encoding="utf-8",
    )
    with pytest.raises(RuntimeError, match="unknown tools"):
        _load_tool_groups(bad)
    # 嵌套组引用（group: 前缀不是工具名）同样被未知工具校验拒绝
    nested = tmp_path / "tool_groups.json"
    nested.write_text(
        json.dumps({"tool_groups": [{"name": "nest", "tools": ["group:other"]}]}),
        encoding="utf-8",
    )
    with pytest.raises(RuntimeError, match="unknown tools"):
        _load_tool_groups(nested)


def test_tool_group_reference_never_widens(db_session) -> None:
    """组不放宽：组贡献与直接声明同权过三重闸——写类/会议面恒剥、档位地板
    恒生效、插件锚点未安装即剥（V12 同构）；组引用绝不绕过任何一腿。"""
    groups = {"bundle": ("read_file", "api_execute", "meeting_convene", "lcsc_search")}
    admin = make_user(db_session, "admin")
    lead = make_user(db_session, "project_lead")
    declared = ["group:bundle"]
    # 会议面在分母即剥（run_face_declared 语义不变，只是先解析组引用）
    assert run_face_declared(declared, groups=groups) == frozenset(
        {"read_file", "api_execute", "lcsc_search"}
    )
    # admin（system_operator）：写类剥除，lcsc.browse 地板放行（无插件目录 → 非插件类）
    assert effective_run_tools(db_session, allowed_tools=declared, actor=admin, groups=groups) == frozenset(
        {"read_file", "lcsc_search"}
    )
    # project_lead（project_manager < system_operator）：lcsc_search 档位地板剥除——组不放宽
    assert effective_run_tools(db_session, allowed_tools=declared, actor=lead, groups=groups) == frozenset(
        {"read_file"}
    )
    # 插件目录声明 lcsc.browse 而发起人未安装 → 即使 admin 也实时剥（V12 安装态闸）
    db_session.add(
        PluginPackage(
            plugin_key=f"lcsc-{uuid4().hex[:6]}",
            name="立创插件",
            current_version="1.0.0",
            package_sha256="0" * 64,
            created_by_user_id=admin.id,
            manifest_json={"capabilities": ["lcsc.browse"]},
        )
    )
    db_session.commit()
    assert effective_run_tools(db_session, allowed_tools=declared, actor=admin, groups=groups) == frozenset(
        {"read_file"}
    )


def test_tool_group_unknown_group_shrinks_only(db_session, d4_settings) -> None:
    """只收窄：未知/停用组引用贡献为空——纯组声明 run 面空 → 明确报因
    tools_unavailable（不静默放空跑）；混入直接声明不受污染。"""
    assert run_face_declared(["group:ghost"]) == frozenset()
    assert resolve_tool_groups(["group:ghost", "read_file"]) == ["read_file"]
    admin = make_user(db_session, "admin")
    dead = seed_agent(db_session, d4_settings, name="死组智能体", allowed_tools=("group:ghost",))
    assert _unavailability(db_session, dead, admin) == "tools_unavailable"
    mixed = seed_agent(
        db_session,
        d4_settings,
        name="混声明智能体",
        credential_ref=f"zcode-{uuid4().hex[:6]}",
        allowed_tools=("group:ghost", "read_file"),
    )
    assert _unavailability(db_session, mixed, admin) is None


def test_tool_group_real_seed_mixed_declaration(db_session) -> None:
    """真种子端到端：组声明解析出完整白名单；混合声明保序去重（直接项
    与组贡献并集）；有效面走完整管线（admin 档位全放行）。"""
    research = list(load_tool_groups()["research-readonly"])
    assert resolve_tool_groups(["read_file", "group:research-readonly"]) == research
    # 组贡献去重：read_file 既是直接声明又在组内 → 只出现一次（保序）
    assert resolve_tool_groups(["read_file", "group:research-readonly"]).count("read_file") == 1
    admin = make_user(db_session, "admin")
    effective = effective_run_tools(db_session, allowed_tools=["group:research-readonly"], actor=admin)
    assert effective == frozenset(research)
    # 停用组（is_active=false）装载即不可见 → 解析贡献为空；注入的活跃组照常展开
    assert resolve_tool_groups(["group:retired"], groups={}) == []
    assert resolve_tool_groups(["group:retired"], groups={"retired": ("read_file",)}) == ["read_file"]
