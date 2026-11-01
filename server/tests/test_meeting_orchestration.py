"""goal-d7：S2 编排中枢——场景模板 S1–S6 / 到场表鉴权 / PM-2 三层防火墙 /
Killjoy 自动收敛 / M5 memlog / M7 中断恢复 / M8 checklist 降级 / M9 会议成本 /
T4 高难度自动升档。

M1：S1–S5 五个模板可配置、可开会（场景模板 convene→turn→close 走通）。
M5：同项目二次开会引用上次纪要结论（memlog 连续性）。
M7：中断恢复 ≤24h，超时自动收场出未完成纪要。
M8：降级为 checklist 模式可用（建会即封 auto 纪要）。
M9：成本按会议归集可查。
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy import select, update

from test_agents_d4_harness import api_client, seed_agent
from test_agents_d4_harness import d4_app, d4_client, d4_settings  # noqa: F401  (pytest fixture)
from test_document_drafts_api import _persist_project

from fde_api.agents.models import AgentRegistry, AgentRun
from fde_api.agents.seeds import ensure_agent_seeds
from fde_api.meetings.models import ReviewMeeting
from fde_api.meetings.service import t2_gate_satisfied

_MINUTES_OK = {
    "consensus": [{"text": "对齐一致", "source_refs": []}],
    "disputes": [],
    "todos": [],
}


def _setup(db_session, d4_client, d4_settings):
    leader = api_client(d4_client, db_session, d4_settings, "project_lead")
    project = _persist_project(db_session, leader.user, code=f"D7O{uuid4().hex[:6]}")
    ensure_agent_seeds(db_session)
    db_session.commit()
    return leader, project


def _module_agent(db_session, tier: str) -> AgentRegistry:
    return db_session.scalar(select(AgentRegistry).where(AgentRegistry.capability_tier == tier))


def _convene(leader, project, template_id: str, **extra):
    body = leader.post(
        "/api/v1/meetings",
        json={"project_id": project.id, "template_id": template_id, **extra},
    )
    assert body.status_code == 201, body.json
    return body.json["data"]


def _turn(leader, meeting_id: str, agent_id: str | None, text: str, user_id: str | None = None):
    payload: dict = {"content": {"text": text}}
    if agent_id is not None:
        payload["speaker_agent_id"] = agent_id
    else:
        payload["speaker_user_id"] = user_id
    return leader.post(f"/api/v1/meetings/{meeting_id}/turns", json=payload)


def _backdate_meeting(db_session, meeting_id: str, hours: float) -> None:
    db_session.execute(
        update(ReviewMeeting)
        .where(ReviewMeeting.id == meeting_id)
        .values(updated_at=datetime.now(timezone.utc) - timedelta(hours=hours))
    )
    db_session.commit()


# ---------------------------------------------------------------------------
# M1：场景模板注册 + 可开会
# ---------------------------------------------------------------------------


def test_m1_scenario_templates_registered(db_session, d4_client, d4_settings) -> None:
    leader, _project = _setup(db_session, d4_client, d4_settings)
    items = {item["template_id"]: item for item in leader.get("/api/v1/meeting-templates").json["data"]["items"]}
    for template_id in (
        "S1-diagnosis", "S2-solution-review", "S3-business-alignment",
        "S4-kickoff", "S5-preacceptance", "S6-free", "T1-lite", "T5-lite",
    ):
        assert template_id in items, template_id
    # 场景模板 manual 不作门证据；门模板 mandatory
    for scenario in ("S1-diagnosis", "S2-solution-review", "S3-business-alignment", "S4-kickoff", "S5-preacceptance", "S6-free"):
        assert items[scenario]["trigger"] == "manual", scenario
        assert items[scenario]["gate"] is None
        assert items[scenario]["distill_source"]  # D10 蒸馏源标注（审定交接随轮）
    assert items["T1-lite"]["gate"] == "T1" and items["T1-lite"]["trigger"] == "mandatory"
    assert items["T5-lite"]["gate"] == "T5" and items["T5-lite"]["trigger"] == "mandatory"
    # PartyMode §2.1 班底：S3 商务对齐会带财务/法务角色卡
    assert set(items["S3-business-alignment"]["attendees"]) >= {"persona:finance", "persona:legal"}


def test_m1_scenario_meeting_convenable(db_session, d4_client, d4_settings) -> None:
    """M1：实际开会走通——S1 召集 → 在册模块智能体发言 → 收敛封存。"""
    leader, project = _setup(db_session, d4_client, d4_settings)
    meeting = _convene(leader, project, "S1-diagnosis")
    assert meeting["trigger"] == "manual"
    presales = _module_agent(db_session, "agent.module.presales")
    body = _turn(leader, meeting["id"], presales.id, "问题清单已核对，来源引用闭合")
    assert body.status_code == 200, body.json
    closed = leader.post(f"/api/v1/meetings/{meeting['id']}/close", json=_MINUTES_OK)
    assert closed.status_code == 200, closed.json


# ---------------------------------------------------------------------------
# 编排中枢 authority：到场表鉴权
# ---------------------------------------------------------------------------


def test_roster_authority_blocks_stranger(db_session, d4_client, d4_settings) -> None:
    """S1 到场表（module:presales/solution/quality_guard/knowledge）外的智能体
    不能发言——具体标签按能力腿精确匹配。"""
    leader, project = _setup(db_session, d4_client, d4_settings)
    meeting = _convene(leader, project, "S1-diagnosis")
    stranger = seed_agent(db_session, d4_settings, capability="agent.code.write")
    body = _turn(leader, meeting["id"], stranger.id, "我不在这个会上")
    assert body.status_code == 403 and body.json["error"]["code"] == "speaker_not_in_roster"


def test_persona_only_enters_via_persona_label(db_session, d4_client, d4_settings) -> None:
    """persona 永不落入泛标签（PM-2 边界）：S1（无 persona 标签）403；
    S3（persona:finance 在册）放行且发言注入常驻徽标（第 1 层）。"""
    leader, project = _setup(db_session, d4_client, d4_settings)
    finance = _module_agent(db_session, "agent.persona.finance")
    s1 = _convene(leader, project, "S1-diagnosis")
    blocked = _turn(leader, s1["id"], finance.id, "财务口径：付款节点惯例是三段式")
    assert blocked.status_code == 403 and blocked.json["error"]["code"] == "speaker_not_in_roster"
    s3 = _convene(leader, project, "S3-business-alignment")
    body = _turn(leader, s3["id"], finance.id, "财务口径：行业惯例是按里程碑分三段回款")
    assert body.status_code == 200, body.json
    content = body.json["data"]["turns"][-1]["content"]
    assert content["disclaimer"] == "AI 模拟视角，非专业意见"  # PM-2 第 1 层（系统注入）
    assert content["persona"] is True and content["speaker_ref"] == f"persona:{finance.id}"


def test_pm2_layer2_prescription_blocked(db_session, d4_client, d4_settings) -> None:
    """PM-2 第 2 层：persona 只讲惯例不开处方——denylist 话术 422 拒收。"""
    leader, project = _setup(db_session, d4_client, d4_settings)
    finance = _module_agent(db_session, "agent.persona.finance")
    s3 = _convene(leader, project, "S3-business-alignment")
    body = _turn(leader, s3["id"], finance.id, "你应该签这份合同，必须签三段回款")
    assert body.status_code == 422 and body.json["error"]["code"] == "persona_prescription_blocked"


def test_pm2_layer3_conclusion_only_into_todos(db_session, d4_client, d4_settings) -> None:
    """PM-2 第 3 层：persona 来源条目进共识/分歧 → 422 拒封存；进待办段 →
    服务端固定文案前缀「提交专业顾问确认：」（系统级封存，进 sealed_sha256）。"""
    leader, project = _setup(db_session, d4_client, d4_settings)
    finance = _module_agent(db_session, "agent.persona.finance")
    s3 = _convene(leader, project, "S3-business-alignment")
    body = _turn(leader, s3["id"], finance.id, "财务口径：回款惯例是里程碑三段式")
    assert body.status_code == 200
    persona_ref = body.json["data"]["turns"][-1]["content"]["speaker_ref"]
    human = leader.user.id
    misplaced = leader.post(
        f"/api/v1/meetings/{s3['id']}/close",
        json={
            "consensus": [{"text": "回款按三段式", "source_refs": [persona_ref]}],
            "disputes": [],
            "todos": [],
        },
    )
    assert misplaced.status_code == 422
    assert misplaced.json["error"]["code"] == "persona_conclusion_misplaced"
    ok = leader.post(
        f"/api/v1/meetings/{s3['id']}/close",
        json={
            "consensus": [{"text": "会议对齐完成", "source_refs": []}],
            "disputes": [],
            "todos": [{"text": "回款按三段式执行", "source_refs": [persona_ref], "owner": human}],
        },
    )
    assert ok.status_code == 200, ok.json
    todo = ok.json["data"]["todos"][0]
    assert todo["text"].startswith("提交专业顾问确认：")
    minutes = leader.get(f"/api/v1/meetings/{s3['id']}/minutes").json["data"]
    assert minutes["todos"][0]["text"] == todo["text"]  # 前缀进封存指纹


# ---------------------------------------------------------------------------
# Killjoy 自动收敛 + auto 纪要不作门证据
# ---------------------------------------------------------------------------


def test_killjoy_duplicate_turn_auto_converges(db_session, d4_client, d4_settings) -> None:
    """PartyMode §7：重复论点检测 → 主持人强制收题（自动封存未完成纪要）。"""
    leader, project = _setup(db_session, d4_client, d4_settings)
    meeting = _convene(leader, project, "T2-lite")
    first = _turn(leader, meeting["id"], None, "报价档位需要复核", user_id=leader.user.id)
    assert first.status_code == 200
    repeat = _turn(leader, meeting["id"], None, "报价档位需要复核", user_id=leader.user.id)
    assert repeat.status_code == 200, repeat.json
    assert repeat.json["data"]["killjoy_converged"] is True
    assert repeat.json["data"]["status"] == "closed"
    minutes = leader.get(f"/api/v1/meetings/{meeting['id']}/minutes").json["data"]
    assert minutes["todos"] and minutes["todos"][0]["auto"] is True  # auto 标记
    # 复读发言未被收录进纪要前 meeting 已关闭：再发言 409
    after = _turn(leader, meeting["id"], None, "继续讨论", user_id=leader.user.id)
    assert after.status_code == 409 and after.json["error"]["code"] == "meeting_not_live"
    # 人工收敛不可重写
    again = leader.post(f"/api/v1/meetings/{meeting['id']}/close", json=_MINUTES_OK)
    assert again.status_code == 409 and again.json["error"]["code"] == "minutes_already_sealed"


def test_auto_minutes_not_gate_evidence(db_session, d4_client, d4_settings, app) -> None:
    """决议 4：Killjoy/超时收场的 auto 纪要永不放行强制门（未完成 ≠ 评审完成）。"""
    leader, project = _setup(db_session, d4_client, d4_settings)
    agent = _module_agent(db_session, "agent.module.solution")
    run = AgentRun(
        project_id=project.id,
        agent_id=agent.id,
        initiated_by_user_id=leader.user.id,
        capability_used=agent.capability_tier,
        status="completed",
        context_ref="agent-workspaces/x/context.md",
        idempotency_key=f"d7auto:{uuid4().hex}",
    )
    db_session.add(run)
    db_session.commit()
    meeting = _convene(leader, project, "T2-lite", triggered_by_run_id=run.id)
    assert _turn(leader, meeting["id"], None, "同一句话", user_id=leader.user.id).status_code == 200
    assert _turn(leader, meeting["id"], None, "同一句话", user_id=leader.user.id).json["data"]["killjoy_converged"]
    assert t2_gate_satisfied(db_session, run_id=run.id, solution_id=None) is False


# ---------------------------------------------------------------------------
# M5 memlog / M7 中断恢复 / M8 checklist 降级 / M9 会议成本
# ---------------------------------------------------------------------------


def test_m5_second_meeting_references_prior_minutes(db_session, d4_client, d4_settings) -> None:
    leader, project = _setup(db_session, d4_client, d4_settings)
    first = _convene(leader, project, "S6-free")
    assert "prior_minutes" not in first["topic_refs"]  # 首会无 prior
    assert leader.post(f"/api/v1/meetings/{first['id']}/close", json=_MINUTES_OK).status_code == 200
    second = _convene(leader, project, "S6-free")
    prior = second["topic_refs"]["prior_minutes"].split(",")
    first_minutes = leader.get(f"/api/v1/meetings/{first['id']}/minutes").json["data"]
    assert first_minutes["id"] in prior  # memlog 连续性：引用上次纪要


def test_m7_pause_resume_within_window(db_session, d4_client, d4_settings) -> None:
    leader, project = _setup(db_session, d4_client, d4_settings)
    meeting = _convene(leader, project, "S6-free")
    paused = leader.post(f"/api/v1/meetings/{meeting['id']}/pause")
    assert paused.status_code == 200 and paused.json["data"]["status"] == "paused"
    resumed = leader.post(f"/api/v1/meetings/{meeting['id']}/resume")
    assert resumed.status_code == 200 and resumed.json["data"]["status"] == "live"
    assert _turn(leader, meeting["id"], None, "恢复后继续", user_id=leader.user.id).status_code == 200


def test_m7_resume_expired_auto_closes_with_unfinished_minutes(db_session, d4_client, d4_settings) -> None:
    """M7：暂停超过恢复窗口（24h）→ 自动收场出未完成纪要，恢复被拒。"""
    leader, project = _setup(db_session, d4_client, d4_settings)
    meeting = _convene(leader, project, "S6-free")
    assert leader.post(f"/api/v1/meetings/{meeting['id']}/pause").status_code == 200
    _backdate_meeting(db_session, meeting["id"], hours=25)
    expired = leader.post(f"/api/v1/meetings/{meeting['id']}/resume")
    assert expired.status_code == 409
    assert expired.json["error"]["code"] == "meeting_resume_expired"
    minutes = leader.get(f"/api/v1/meetings/{meeting['id']}/minutes").json["data"]
    assert minutes["todos"][0]["auto"] is True  # 未完成纪要（不作门证据）


def test_m7_stale_live_meeting_reaped_on_access(db_session, d4_client, d4_settings) -> None:
    """M7：live 超 24h 无活动 → 懒收场（访问点触发）出未完成纪要。"""
    leader, project = _setup(db_session, d4_client, d4_settings)
    stale = _convene(leader, project, "S6-free")
    _backdate_meeting(db_session, stale["id"], hours=30)
    body = leader.get(f"/api/v1/meetings/{stale['id']}")
    assert body.status_code == 200
    assert body.json["data"]["status"] == "closed"
    assert body.json["data"]["degraded"] is True


def test_m8_checklist_mode_meeting(db_session, d4_client, d4_settings) -> None:
    """M8：智能体层不可用 → 整会降级模板清单模式（建会即封 auto 纪要）。"""
    leader, project = _setup(db_session, d4_client, d4_settings)
    body = leader.post(
        "/api/v1/meetings",
        json={"project_id": project.id, "template_id": "S2-solution-review", "mode": "checklist"},
    )
    assert body.status_code == 201, body.json
    data = body.json["data"]
    assert data["mode"] == "checklist" and data["status"] == "closed" and data["degraded"] is True
    texts = [item["text"] for item in data["minutes"]["todos"]]
    assert any("确认评审范围与产物清单" in text for text in texts)
    assert all(item["auto"] is True for item in data["minutes"]["todos"])
    # 非法 mode 拒收
    bad = leader.post(
        "/api/v1/meetings",
        json={"project_id": project.id, "template_id": "S6-free", "mode": "turbo"},
    )
    assert bad.status_code == 400 and bad.json["error"]["code"] == "invalid_request"


def test_m9_meeting_cost_endpoint(db_session, d4_client, d4_settings, app) -> None:
    """M9：成本按会议归集可查——工具面召集计费 2 单位落触发 run；人工开会 0。"""
    leader, project = _setup(db_session, d4_client, d4_settings)
    agent = seed_agent(db_session, d4_settings, allowed_tools=("read_file", "meeting_convene"))
    run = AgentRun(
        project_id=project.id,
        agent_id=agent.id,
        initiated_by_user_id=leader.user.id,
        capability_used=agent.capability_tier,
        status="running",
        context_ref="agent-workspaces/x/context.md",
        idempotency_key=f"m9:{uuid4().hex}",
        token_cost=5,
    )
    db_session.add(run)
    db_session.commit()
    from fde_api.meetings.service import dispatch_agent_tool

    with app.app_context():
        convened = dispatch_agent_tool(
            actor=leader.user, agent_id=agent.id, run_id=run.id,
            tool_name="meeting_convene",
            payload={"template_id": "T3-adhoc", "triggered_by_run_id": run.id, "reason": "M9 成本核对"},
        )
    meeting_id = convened["meeting"]["id"]
    body = leader.get(f"/api/v1/meetings/{meeting_id}/cost")
    assert body.status_code == 200, body.json
    data = body.json["data"]
    assert data["convene_cost_units"] == 2 and data["total_cost_units"] == 2
    assert data["triggering_run_token_cost"] == 7  # 5 + 2（计费落触发 run）
    manual = _convene(leader, project, "S6-free")
    manual_cost = leader.get(f"/api/v1/meetings/{manual['id']}/cost").json["data"]
    assert manual_cost["convene_cost_units"] == 0  # 人工开会免费（不占额度）


# ---------------------------------------------------------------------------
# T4 高难度加座（U10 升档）
# ---------------------------------------------------------------------------


def test_t4_high_difficulty_auto_upgrades_full_tier(db_session, d4_client, d4_settings) -> None:
    """U10：difficulty=high 的 run 召集强制门模板 → 自动升 full（12 轮）+
    角色卡入座（到场表叠加 persona_addons）；standard run 零升档。"""
    leader, project = _setup(db_session, d4_client, d4_settings)
    agent = _module_agent(db_session, "agent.module.solution")
    high_run = AgentRun(
        project_id=project.id,
        agent_id=agent.id,
        initiated_by_user_id=leader.user.id,
        capability_used=agent.capability_tier,
        status="running",
        context_ref="agent-workspaces/x/context.md",
        idempotency_key=f"t4:{uuid4().hex}",
        difficulty="high",
    )
    db_session.add(high_run)
    db_session.commit()
    upgraded = _convene(leader, project, "T2-lite", triggered_by_run_id=high_run.id)
    assert upgraded["gate_tier"] == "full" and upgraded["turn_budget"] == 12
    assert upgraded["min_difficulty"] == "high"
    finance = _module_agent(db_session, "agent.persona.finance")
    body = _turn(leader, upgraded["id"], finance.id, "财务口径：该档位报价惯例需复核")
    assert body.status_code == 200, body.json  # 加座角色卡可发言
    normal_run = AgentRun(
        project_id=project.id,
        agent_id=agent.id,
        initiated_by_user_id=leader.user.id,
        capability_used=agent.capability_tier,
        status="running",
        context_ref="agent-workspaces/x/context.md",
        idempotency_key=f"t4n:{uuid4().hex}",
    )
    db_session.add(normal_run)
    db_session.commit()
    normal = _convene(leader, project, "T2-lite", triggered_by_run_id=normal_run.id)
    assert normal["gate_tier"] == "lite" and normal["turn_budget"] == 2  # 零升档
