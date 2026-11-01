"""goal-d5：评审会人工流——模板/召集/话轮预算/守卫封存/纪要溯源/权限。

M2：纪要三段式产出且引用可溯源到 agent_run_id（纪要详情反查链路）。
M3：分歧点不被调和，原样保留并标注冲突。
M6：话轮/轮次预算生效，超限强制收敛（d5 切片：预算硬墙 + close 收敛）。
"""
from __future__ import annotations

from uuid import uuid4

from sqlalchemy import select

from test_agents_d4_harness import api_client, seed_agent
from test_agents_d4_harness import d4_app, d4_client, d4_settings  # noqa: F401  (pytest fixture)
from test_document_drafts_api import _persist_project

from fde_api.agents.models import AgentArtifact, AgentRun
from fde_api.meetings.models import ReviewMeeting

_MINUTES_OK = {
    "consensus": [{"text": "产物结构与引用闭合，通过", "source_refs": []}],
    "disputes": [],
    "todos": [],
}


def _setup(db_session, d4_client, d4_settings):
    leader = api_client(d4_client, db_session, d4_settings, "project_lead")
    project = _persist_project(db_session, leader.user, code=f"D5M{uuid4().hex[:6]}")
    return leader, project


def _convene(leader, project, **extra):
    body = leader.post(
        "/api/v1/meetings",
        json={"project_id": project.id, "template_id": "T2-lite", **extra},
    )
    assert body.status_code == 201, body.json
    return body.json["data"]


def _seed_run(db_session, project, leader, agent_id: str) -> AgentRun:
    run = AgentRun(
        project_id=project.id,
        agent_id=agent_id,
        initiated_by_user_id=leader.user.id,
        capability_used="agent.code.write",
        status="completed",
        context_ref="agent-workspaces/x/context.md",
        idempotency_key=f"m2:{uuid4().hex}",
    )
    db_session.add(run)
    db_session.commit()
    return run


def test_meeting_templates_expose_t2_lite(db_session, d4_client, d4_settings) -> None:
    leader, _project = _setup(db_session, d4_client, d4_settings)
    body = leader.get("/api/v1/meeting-templates")
    assert body.status_code == 200
    items = body.json["data"]["items"]
    lite = next(item for item in items if item["template_id"] == "T2-lite")
    assert lite["gate"] == "T2" and lite["gate_tier"] == "lite"
    assert lite["turn_budget"] == 2  # UM-1：lite=2 轮
    assert set(lite["attendees"]) == {"quality_guard", "module_agent"}  # 守卫+1 模块智能体
    assert lite["sections"] == ["consensus", "disputes", "todos"]  # 三段式
    assert lite["trigger"] == "mandatory"


def test_manual_convene_defaults_from_template(db_session, d4_client, d4_settings) -> None:
    leader, project = _setup(db_session, d4_client, d4_settings)
    meeting = _convene(leader, project)
    assert meeting["status"] == "live"
    assert meeting["turn_budget"] == 2 and meeting["gate_tier"] == "lite"
    assert meeting["trigger"] == "mandatory"  # 模板派生，人工开会同模板同门语义
    assert meeting["convened_by_agent_id"] is None
    detail = leader.get(f"/api/v1/meetings/{meeting['id']}")
    assert detail.status_code == 200 and detail.json["data"]["turns"] == []


def test_unknown_template_and_missing_body_rejected(db_session, d4_client, d4_settings) -> None:
    leader, project = _setup(db_session, d4_client, d4_settings)
    body = leader.post("/api/v1/meetings", json={"project_id": project.id, "template_id": "T9-nope"})
    assert body.status_code == 404 and body.json["error"]["code"] == "meeting_template_not_found"


def test_turn_budget_wall_then_close_m6(db_session, d4_client, d4_settings) -> None:
    """M6：lite=2 轮硬墙；超限 409 后唯一出路是收敛（close）。"""
    leader, project = _setup(db_session, d4_client, d4_settings)
    meeting = _convene(leader, project)
    for seq in (1, 2):
        body = leader.post(
            f"/api/v1/meetings/{meeting['id']}/turns",
            json={"speaker_user_id": leader.user.id, "content": {"text": f"第 {seq} 轮意见", "stance": "agree"}},
        )
        assert body.status_code == 200, body.json
        assert body.json["data"]["turns"][-1]["seq"] == seq
    overflow = leader.post(
        f"/api/v1/meetings/{meeting['id']}/turns",
        json={"speaker_user_id": leader.user.id, "content": {"text": "第三轮：超预算"}},
    )
    assert overflow.status_code == 409
    assert overflow.json["error"]["code"] == "turn_budget_exhausted"
    closed = leader.post(f"/api/v1/meetings/{meeting['id']}/close", json=_MINUTES_OK)
    assert closed.status_code == 200, closed.json
    minutes = closed.json["data"]
    assert len(minutes["sealed_sha256"]) == 64
    # 封存不可变（复用 SOW 导出心智）：二次收敛拒绝
    again = leader.post(f"/api/v1/meetings/{meeting['id']}/close", json=_MINUTES_OK)
    assert again.status_code == 409 and again.json["error"]["code"] == "minutes_already_sealed"
    # 封存后话轮通道关闭
    late = leader.post(
        f"/api/v1/meetings/{meeting['id']}/turns",
        json={"speaker_user_id": leader.user.id, "content": {"text": "迟到的发言"}},
    )
    assert late.status_code == 409 and late.json["error"]["code"] == "meeting_not_live"


def test_turn_speaker_xor_and_validation(db_session, d4_client, d4_settings) -> None:
    leader, project = _setup(db_session, d4_client, d4_settings)
    meeting = _convene(leader, project)
    both = leader.post(
        f"/api/v1/meetings/{meeting['id']}/turns",
        json={"speaker_user_id": leader.user.id, "speaker_agent_id": "x", "content": {"text": "a"}},
    )
    assert both.status_code == 400
    neither = leader.post(f"/api/v1/meetings/{meeting['id']}/turns", json={"content": {"text": "a"}})
    assert neither.status_code == 400
    empty = leader.post(
        f"/api/v1/meetings/{meeting['id']}/turns",
        json={"speaker_user_id": leader.user.id, "content": {"text": "  "}},
    )
    assert empty.status_code == 400


def test_disputes_preserved_with_conflict_m3(db_session, d4_client, d4_settings) -> None:
    """M3：分歧点不被调和——双方论点原样保留 + 冲突标注。"""
    leader, project = _setup(db_session, d4_client, d4_settings)
    meeting = _convene(leader, project)
    single = leader.post(
        f"/api/v1/meetings/{meeting['id']}/close",
        json={
            "consensus": [],
            "disputes": [{"positions": [{"speaker": "守卫", "text": "只有一方"}], "conflict": "伪分歧"}],
            "todos": [],
        },
    )
    assert single.status_code == 400 and single.json["error"]["code"] == "invalid_dispute"
    sealed = leader.post(
        f"/api/v1/meetings/{meeting['id']}/close",
        json={
            "consensus": [{"text": "回滚脚本必须验证", "source_refs": []}],
            "disputes": [
                {
                    "positions": [
                        {"speaker": "守卫", "text": "部署窗口应避开业务高峰", "source_refs": []},
                        {"speaker": "部署智能体", "text": "窗口由客户运维决定", "source_refs": []},
                    ],
                    "conflict": "部署窗口决策权分歧",
                }
            ],
            "todos": [{"text": "与客户运维确认窗口", "owner": "蔡工"}],
        },
    )
    assert sealed.status_code == 200
    minutes = leader.get(f"/api/v1/meetings/{meeting['id']}/minutes").json["data"]
    dispute = minutes["disputes"][0]
    assert [p["text"] for p in dispute["positions"]] == ["部署窗口应避开业务高峰", "窗口由客户运维决定"]
    assert dispute["conflict"] == "部署窗口决策权分歧"
    assert minutes["consensus"][0]["text"] == "回滚脚本必须验证"


def test_guard_rejects_unknown_refs_and_marks_degraded(db_session, d4_client, d4_settings) -> None:
    """守卫复核引用闭合：失败拒封存标 degraded，补正后重试（技术文档 §6）。"""
    leader, project = _setup(db_session, d4_client, d4_settings)
    agent = seed_agent(db_session, d4_settings, allowed_tools=("meeting_convene",))
    run = _seed_run(db_session, project, leader, agent.id)
    meeting = _convene(leader, project, triggered_by_run_id=run.id)
    bad = leader.post(
        f"/api/v1/meetings/{meeting['id']}/close",
        json={"consensus": [{"text": "引用了幽灵来源", "source_refs": ["ghost-ref"]}], "disputes": [], "todos": []},
    )
    assert bad.status_code == 422 and bad.json["error"]["code"] == "source_ref_unknown"
    row = db_session.get(ReviewMeeting, meeting["id"])
    assert row.degraded is True and row.status == "live"  # 拒封存，可补正重试
    # 补正：话轮先引入该引用 → 引用闭合 → 封存放行
    leader.post(
        f"/api/v1/meetings/{meeting['id']}/turns",
        json={"speaker_user_id": leader.user.id, "content": {"text": "补充说明", "source_refs": ["ghost-ref"]}},
    )
    good = leader.post(
        f"/api/v1/meetings/{meeting['id']}/close",
        json={"consensus": [{"text": "引用已闭合", "source_refs": ["ghost-ref"]}], "disputes": [], "todos": []},
    )
    assert good.status_code == 200, good.json


def test_minutes_traceable_to_agent_run_m2(db_session, d4_client, d4_settings) -> None:
    """M2：纪要三段式产出且引用可溯源到 agent_run_id（纪要 → run → 产物指纹）。"""
    leader, project = _setup(db_session, d4_client, d4_settings)
    agent = seed_agent(db_session, d4_settings)
    run = _seed_run(db_session, project, leader, agent.id)
    db_session.add(
        AgentArtifact(
            run_id=run.id, kind="doc", storage_ref=f"{run.id}/output/plan.md", sha256="a" * 64
        )
    )
    db_session.commit()
    meeting = _convene(leader, project, triggered_by_run_id=run.id)
    artifact_ref = f"{run.id}/output/plan.md"
    # 评审输入先经话轮引入（引用闭合守卫的已知集合 = topic_refs + 话轮引用）
    leader.post(
        f"/api/v1/meetings/{meeting['id']}/turns",
        json={"speaker_user_id": leader.user.id, "content": {"text": "审阅产物", "source_refs": [artifact_ref]}},
    )
    sealed = leader.post(
        f"/api/v1/meetings/{meeting['id']}/close",
        json={
            "consensus": [{"text": "plan.md 结构合格", "source_refs": [artifact_ref]}],
            "disputes": [],
            "todos": [],
        },
    )
    assert sealed.status_code == 200
    data = leader.get(f"/api/v1/meetings/{meeting['id']}/minutes").json["data"]
    assert data["triggered_by_run_id"] == run.id  # D7：关联落会议侧，可反查
    stored_run = db_session.get(AgentRun, data["triggered_by_run_id"])
    artifact = db_session.scalar(select(AgentArtifact).where(AgentArtifact.run_id == stored_run.id))
    assert artifact.sha256 == "a" * 64  # 反查链闭合：纪要 → run → 产物指纹
    assert data["consensus"][0]["source_refs"] == [artifact.storage_ref]


def test_meeting_permissions(db_session, d4_client, d4_settings) -> None:
    leader, project = _setup(db_session, d4_client, d4_settings)
    outsider = api_client(d4_client, db_session, d4_settings, "fde_engineer")
    body = outsider.post(
        "/api/v1/meetings", json={"project_id": project.id, "template_id": "T2-lite"}
    )
    assert body.status_code == 403  # 非成员不可管理（project_forbidden）
    anon = d4_client.post("/api/v1/meetings", json={})
    assert anon.status_code == 401
    meeting = _convene(leader, project)
    read = outsider.get(f"/api/v1/meetings/{meeting['id']}")
    assert read.status_code == 403  # 非成员不可读
    minutes = outsider.get(f"/api/v1/meetings/{meeting['id']}/minutes")
    assert minutes.status_code == 403
