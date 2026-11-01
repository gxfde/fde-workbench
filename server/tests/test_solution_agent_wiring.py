"""goal-d6：generate-agent 接线 + review-trail（U5/U6）+ SOW agent_trace（V9/V11）
+ U3 T3 自主召集 + U4 修订回路 + U9 checklist。
"""
from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import select

from conftest import INITIAL_PASSWORD
from test_agents_d4_harness import (
    ScriptedEvents,
    api_client,
    prime_run,
    seed_agent,
)
from test_agents_d4_harness import d4_app, d4_client, d4_settings  # noqa: F401  (pytest fixture)
from test_document_drafts_api import _persist_project
from test_goal_d2_s0_closeout import _confirmed_guidance

from fde_api.agents.models import AgentRun
from fde_api.meetings.service import MeetingsServiceError, dispatch_agent_tool
from fde_api.solutions.models import ProjectSolution
from fde_api.workbench.models import OperationEvent


def _project_with_solution(db_session, d4_client, d4_settings, *, with_guidance: bool = True, agent_tools=("read_file",)):
    leader = api_client(d4_client, db_session, d4_settings, "project_lead")
    project = _persist_project(db_session, leader.user, code=f"GA{uuid4().hex[:4]}")
    if with_guidance:
        _confirmed_guidance(
            db_session, project, leader.user,
            problems=[{"text": "数据割裂", "classification": "数据", "source_refs": ["src-1"], "confirmed": True}],
        )
    solution = ProjectSolution(project_id=project.id, name="交付方案", owner_user_id=leader.user.id)
    db_session.add(solution)
    db_session.commit()
    agent = seed_agent(db_session, d4_settings, allowed_tools=agent_tools)
    return leader, project, solution, agent


def _scanner_factory(run_id, workspace):
    from pathlib import Path

    from test_agents_d4_harness import FakeScanner

    from fde_api.agents.adapter import ArtifactFile

    output = Path(workspace) / "output"
    output.mkdir(parents=True, exist_ok=True)
    (output / "plan.md").write_text("接线测试产物", encoding="utf-8")
    return FakeScanner([ArtifactFile(path="plan.md", kind="doc", source_refs=("src-1",))])


def _seed_t1(leader, project, solution_id: str) -> None:
    """goal-d7 T1 前置闸适配（最小侵入）：产物生成 run 前须有已封存 T1
    纪要侧链 solution；断言逻辑零改动。"""
    convened = leader.post(
        "/api/v1/meetings",
        json={"project_id": project.id, "template_id": "T1-lite", "solution_id": solution_id},
    )
    assert convened.status_code == 201, convened.json
    sealed = leader.post(
        f"/api/v1/meetings/{convened.json['data']['id']}/close",
        json={"consensus": [{"text": "计划评审通过", "source_refs": []}], "disputes": [], "todos": []},
    )
    assert sealed.status_code == 200, sealed.json


def _seal_t2(leader, project, solution_id: str, *, disputes: list | None = None) -> str:
    """召集+封存；返回**会议 id**（close 响应体是纪要序列化，其 id 非会议 id）。
    goal-d7：先铺 T1 纪要（T1 闸适配；T1 纪要经门语义分离不满足 T2）。"""
    _seed_t1(leader, project, solution_id)
    convened = leader.post(
        "/api/v1/meetings",
        json={"project_id": project.id, "template_id": "T2-lite", "solution_id": solution_id},
    )
    assert convened.status_code == 201, convened.json
    meeting_id = convened.json["data"]["id"]
    closed = leader.post(
        f"/api/v1/meetings/{meeting_id}/close",
        json={
            "consensus": [{"text": "产物评审通过", "source_refs": []}],
            "disputes": disputes or [],
            "todos": [],
        },
    )
    assert closed.status_code == 200, closed.json
    return meeting_id


# ---------------------------------------------------------------------------
# generate-agent 接线
# ---------------------------------------------------------------------------


def test_generate_agent_wires_solution(db_session, d4_client, d4_app, d4_settings) -> None:
    """completed+过门 → solution.agent_run_id 接线 + generated_by='agent' + 事件。"""
    leader, project, solution, agent = _project_with_solution(db_session, d4_client, d4_settings)
    _seal_t2(leader, project, solution.id)
    prime_run(d4_app, events=ScriptedEvents([[{"type": "done", "exit_code": 0}]]), scanner_factory=_scanner_factory)
    body = leader.post(
        f"/api/v1/projects/{project.id}/solutions/{solution.id}/generate-agent",
        json={"agent_id": agent.id, "idempotency_key": f"ga:{uuid4().hex}"},
    )
    assert body.status_code == 201, body.json
    data = body.json["data"]
    assert data["wired"] is True and data["wired_now"] is True
    assert data["solution"]["generated_by"] == "agent"
    assert data["solution"]["agent_run_id"] == data["agent_run_id"]
    assert data["solution"]["agent_degraded"] is False
    events = db_session.scalars(
        select(OperationEvent).where(OperationEvent.project_id == project.id)
    ).all()
    assert any(event.event_type == "solution_agent_wired" for event in events)


def test_generate_agent_gate_open_not_wired(db_session, d4_client, d4_app, d4_settings) -> None:
    """无封存纪要 → 409 review_gate_open 透传；solution 不接线。"""
    leader, project, solution, agent = _project_with_solution(db_session, d4_client, d4_settings)
    _seed_t1(leader, project, solution.id)  # T1 已过、T2 未过——精确到达 T2 门
    prime_run(d4_app, events=ScriptedEvents([[{"type": "done", "exit_code": 0}]]), scanner_factory=_scanner_factory)
    body = leader.post(
        f"/api/v1/projects/{project.id}/solutions/{solution.id}/generate-agent",
        json={"agent_id": agent.id, "idempotency_key": f"ga:{uuid4().hex}"},
    )
    assert body.status_code == 409, body.json
    assert body.json["error"]["code"] == "review_gate_open"
    db_session.expire_all()
    assert db_session.get(ProjectSolution, solution.id).agent_run_id is None


def test_generate_agent_idempotent_and_failed_shapes(db_session, d4_client, d4_app, d4_settings) -> None:
    """幂等复用已完成 run → 200 wired_now=False 不重复建事件；failed run → wired=False。"""
    leader, project, solution, agent = _project_with_solution(db_session, d4_client, d4_settings)
    _seal_t2(leader, project, solution.id)
    prime_run(d4_app, events=ScriptedEvents([[{"type": "done", "exit_code": 0}]]), scanner_factory=_scanner_factory)
    key = f"ga:{uuid4().hex}"
    first = leader.post(
        f"/api/v1/projects/{project.id}/solutions/{solution.id}/generate-agent",
        json={"agent_id": agent.id, "idempotency_key": key},
    )
    assert first.status_code == 201
    second = leader.post(
        f"/api/v1/projects/{project.id}/solutions/{solution.id}/generate-agent",
        json={"agent_id": agent.id, "idempotency_key": key},
    )
    assert second.status_code == 200, second.json
    assert second.json["data"]["wired_now"] is False
    events = db_session.scalars(
        select(OperationEvent).where(OperationEvent.project_id == project.id)
    ).all()
    assert sum(1 for event in events if event.event_type == "solution_agent_wired") == 1
    # failed run：不接线
    prime_run(d4_app, events=ScriptedEvents([[{"type": "done", "exit_code": 1}]]))
    failed = leader.post(
        f"/api/v1/projects/{project.id}/solutions/{solution.id}/generate-agent",
        json={"agent_id": agent.id, "idempotency_key": f"ga-fail:{uuid4().hex}"},
    )
    assert failed.status_code == 200, failed.json
    assert failed.json["data"]["wired"] is False and failed.json["data"]["run"]["status"] == "failed"


def test_generate_agent_permission_and_validation(db_session, d4_client, d4_app, d4_settings) -> None:
    """非成员 404；缺 agent_id 400；多余字段 400；archive 方案 409。"""
    leader, project, solution, agent = _project_with_solution(db_session, d4_client, d4_settings)
    outsider = api_client(d4_client, db_session, d4_settings, "project_lead")
    url = f"/api/v1/projects/{project.id}/solutions/{solution.id}/generate-agent"
    assert outsider.post(url, json={"agent_id": agent.id}).status_code == 403
    assert leader.post(url, json={}).status_code == 400
    assert leader.post(url, json={"agent_id": agent.id, "extra": 1}).status_code == 400
    archived = leader.post(
        f"/api/v1/projects/{project.id}/solutions/{solution.id}/archive",
        json={"version": solution.version, "password": INITIAL_PASSWORD},
    )
    assert archived.status_code == 200, archived.json
    assert leader.post(url, json={"agent_id": agent.id}).status_code == 409


# ---------------------------------------------------------------------------
# review-trail（U5）
# ---------------------------------------------------------------------------


def test_review_trail_lists_family_and_side_link(db_session, d4_client, d4_app, d4_settings) -> None:
    """U5：家族会议（triggered_by_run_id）+ solution 侧链会议都可见；未封存
    不吐纪要；封存吐三段。"""
    leader, project, solution, agent = _project_with_solution(db_session, d4_client, d4_settings)
    side_sealed = _seal_t2(leader, project, solution.id)  # solution 侧链（topic_refs）
    # 侧链第二会（同 solution，live 未封存）
    side_live = leader.post(
        "/api/v1/meetings", json={"project_id": project.id, "template_id": "T2-lite", "solution_id": solution.id}
    )
    assert side_live.status_code == 201
    # 家族锚 run + 直挂会议（triggered_by_run_id 路径）
    run = AgentRun(
        project_id=project.id, agent_id=agent.id, initiated_by_user_id=leader.user.id,
        capability_used=agent.capability_tier, status="completed",
        context_ref="agent-workspaces/t/context.md", idempotency_key=f"trail:{uuid4().hex}",
    )
    db_session.add(run)
    db_session.commit()
    solution.agent_run_id = run.id
    db_session.commit()
    family = leader.post(
        "/api/v1/meetings",
        json={"project_id": project.id, "template_id": "T2-lite", "triggered_by_run_id": run.id},
    )
    assert family.status_code == 201, family.json
    family_meeting_id = family.json["data"]["id"]
    closed = leader.post(
        f"/api/v1/meetings/{family_meeting_id}/close",
        json={"consensus": [{"text": "家族会评审通过", "source_refs": []}], "disputes": [], "todos": []},
    )
    assert closed.status_code == 200, closed.json
    body = leader.get(f"/api/v1/projects/{project.id}/solutions/{solution.id}/review-trail")
    assert body.status_code == 200, body.json
    data = body.json["data"]
    assert data["agent_run_id"] == run.id
    ids = {item["id"] for item in data["meetings"]}
    assert {side_sealed, side_live.json["data"]["id"], family_meeting_id} <= ids
    sealed_item = next(item for item in data["meetings"] if item["id"] == family_meeting_id)
    assert sealed_item["sealed"] is True and len(sealed_item["sealed_sha256"]) == 64
    assert sealed_item["triggered_by_run_id"] == run.id
    assert sealed_item["minutes"]["consensus"][0]["text"] == "家族会评审通过"
    live_item = next(item for item in data["meetings"] if item["id"] == side_live.json["data"]["id"])
    assert live_item["sealed"] is False and "minutes" not in live_item


def test_review_trail_outsider_forbidden(db_session, d4_client, d4_app, d4_settings) -> None:
    leader, project, solution, agent = _project_with_solution(db_session, d4_client, d4_settings)
    outsider = api_client(d4_client, db_session, d4_settings, "project_lead")
    body = outsider.get(f"/api/v1/projects/{project.id}/solutions/{solution.id}/review-trail")
    assert body.status_code == 403  # 项目不可见（_load_project_for_view 分档 403）


# ---------------------------------------------------------------------------
# U3：T3-adhoc 自主召集（reason 必填、计入纪要回链）
# ---------------------------------------------------------------------------


def _seed_tool_run(db_session, project, leader, agent) -> AgentRun:
    run = AgentRun(
        project_id=project.id, agent_id=agent.id, initiated_by_user_id=leader.user.id,
        capability_used=agent.capability_tier, status="running",
        context_ref="agent-workspaces/t3/context.md", idempotency_key=f"t3:{uuid4().hex}",
    )
    db_session.add(run)
    db_session.commit()
    return run


def test_u3_t3_adhoc_requires_reason(db_session, d4_client, d4_app, d4_settings) -> None:
    """工具面自主召集：缺 reason 400 reason_required；带 reason 建会且落
    topic_refs；人工对 T2-lite 带 reason → 400（键集纪律）。"""
    leader, project, solution, agent = _project_with_solution(
        db_session, d4_client, d4_settings,
        agent_tools=("read_file", "meeting_convene", "meeting_get_minutes"),
    )
    run = _seed_tool_run(db_session, project, leader, agent)
    denied = pytest.raises(
        MeetingsServiceError,
        lambda: dispatch_agent_tool(
            actor=leader.user, agent_id=agent.id, run_id=run.id,
            tool_name="meeting_convene",
            payload={"template_id": "T3-adhoc", "triggered_by_run_id": run.id},
        ),
    )
    assert denied.value.code == "reason_required"
    meeting = dispatch_agent_tool(
        actor=leader.user, agent_id=agent.id, run_id=run.id,
        tool_name="meeting_convene",
        payload={"template_id": "T3-adhoc", "triggered_by_run_id": run.id, "reason": "产物改动了验收口径，需自主复核"},
    )
    assert meeting["meeting"]["trigger"] == "adhoc"
    assert meeting["meeting"]["topic_refs"]["reason"] == "产物改动了验收口径，需自主复核"
    human = leader.post(
        "/api/v1/meetings",
        json={"project_id": project.id, "template_id": "T2-lite", "reason": "不该带"},
    )
    assert human.status_code == 400 and human.json["error"]["code"] == "invalid_request"


def test_u3_adhoc_minutes_not_gate_evidence(db_session, d4_client, d4_app, d4_settings) -> None:
    """T3-adhoc 封存纪要不计入 T2 门（trigger=adhoc 不放行强制门）。"""
    leader, project, solution, agent = _project_with_solution(
        db_session, d4_client, d4_settings,
        agent_tools=("read_file", "meeting_convene", "meeting_get_minutes"),
    )
    run = _seed_tool_run(db_session, project, leader, agent)
    meeting = dispatch_agent_tool(
        actor=leader.user, agent_id=agent.id, run_id=run.id,
        tool_name="meeting_convene",
        payload={"template_id": "T3-adhoc", "triggered_by_run_id": run.id, "reason": "复核"},
    )
    closed = leader.post(
        f"/api/v1/meetings/{meeting['meeting']['id']}/close",
        json={"consensus": [{"text": "无异议", "source_refs": []}], "disputes": [], "todos": []},
    )
    assert closed.status_code == 200
    minutes = leader.get(f"/api/v1/meetings/{meeting['meeting']['id']}/minutes").json["data"]
    assert minutes["topic_refs"]["reason"] == "复核"  # 计入纪要回链（U3）
    _seed_t1(leader, project, solution.id)  # T1 已过、T2 未过——精确到达 T2 门
    prime_run(d4_app, events=ScriptedEvents([[{"type": "done", "exit_code": 0}]]), scanner_factory=_scanner_factory)
    body = leader.post(
        f"/api/v1/projects/{project.id}/solutions/{solution.id}/generate-agent",
        json={"agent_id": agent.id, "idempotency_key": f"t3gate:{uuid4().hex}"},
    )
    assert body.status_code == 409 and body.json["error"]["code"] == "review_gate_open"  # 门未被 adhoc 放行


# ---------------------------------------------------------------------------
# U4：修订回路（未决分歧升级人工）
# ---------------------------------------------------------------------------


def _dispute() -> dict:
    return {
        "positions": [
            {"speaker": "守卫", "text": "产物引用不足", "source_refs": []},
            {"speaker": "模块智能体", "text": "引用充分", "source_refs": []},
        ],
        "conflict": "引用闭合口径不一致",
    }


def _seal_family_meeting(leader, project, run_id: str, *, disputes: list | None = None) -> str:
    """家族直挂会议（triggered_by_run_id）：修订回路的纪要输入面——agent 只能
    经 meeting_get_minutes 读自己触发的会（所有权语义与 U4 一致）。"""
    convened = leader.post(
        "/api/v1/meetings",
        json={"project_id": project.id, "template_id": "T2-lite", "triggered_by_run_id": run_id},
    )
    assert convened.status_code == 201, convened.json
    meeting_id = convened.json["data"]["id"]
    sealed = leader.post(
        f"/api/v1/meetings/{meeting_id}/close",
        json={
            "consensus": [{"text": "评审意见已记录", "source_refs": []}],
            "disputes": disputes or [],
            "todos": [],
        },
    )
    assert sealed.status_code == 200, sealed.json
    return meeting_id


def test_u4_open_disputes_block_revision_retry(db_session, d4_client, d4_app, d4_settings) -> None:
    """门拦截 → 封存含未决分歧的家族纪要 → retry 409 revision_disputes_open。"""
    leader, project, solution, agent = _project_with_solution(db_session, d4_client, d4_settings)
    _seed_t1(leader, project, solution.id)  # T1 闸适配
    prime_run(d4_app, events=ScriptedEvents([[{"type": "done", "exit_code": 0}]]), scanner_factory=_scanner_factory)
    key = f"u4:{uuid4().hex}"
    blocked = leader.post(
        f"/api/v1/agents/{agent.id}/run",
        json={"project_id": project.id, "solution_id": solution.id, "idempotency_key": key},
    )
    assert blocked.status_code == 409 and blocked.json["error"]["code"] == "review_gate_open"
    blocked_run = blocked.json["error"]["details"]["run_id"]
    _seal_family_meeting(leader, project, blocked_run, disputes=[_dispute()])
    retried = leader.post(f"/api/v1/agents/runs/{blocked_run}/retry")
    assert retried.status_code == 409, retried.json
    assert retried.json["error"]["code"] == "revision_disputes_open"
    assert retried.json["error"]["details"]["minutes_id"]  # 纪要行 id（非会议 id）
    assert retried.json["error"]["details"]["run_id"] == blocked_run


def test_u4_clean_minutes_retry_passes(db_session, d4_client, d4_app, d4_settings) -> None:
    """无分歧封存 → 家族放行（d5 家族语义 × U4 零回归）。"""
    leader, project, solution, agent = _project_with_solution(db_session, d4_client, d4_settings)
    _seed_t1(leader, project, solution.id)  # T1 闸适配
    prime_run(d4_app, events=ScriptedEvents([[{"type": "done", "exit_code": 0}]]), scanner_factory=_scanner_factory)
    key = f"u4c:{uuid4().hex}"
    blocked = leader.post(
        f"/api/v1/agents/{agent.id}/run",
        json={"project_id": project.id, "solution_id": solution.id, "idempotency_key": key},
    )
    assert blocked.status_code == 409
    blocked_run = blocked.json["error"]["details"]["run_id"]
    _seal_family_meeting(leader, project, blocked_run)
    retried = leader.post(f"/api/v1/agents/runs/{blocked_run}/retry")
    assert retried.status_code == 201, retried.json
    assert retried.json["data"]["retry_of"] == blocked_run


# ---------------------------------------------------------------------------
# U9：checklist 降级面
# ---------------------------------------------------------------------------


def test_u9_checklist_endpoint(db_session, d4_client, d4_app, d4_settings) -> None:
    """强制门模板的静态人工执行单；未知模板 404。"""
    leader, project, solution, agent = _project_with_solution(db_session, d4_client, d4_settings, with_guidance=False)
    body = leader.get("/api/v1/meeting-templates/T2-lite/checklist")
    assert body.status_code == 200, body.json
    data = body.json["data"]
    assert data["mode"] == "manual_checklist" and data["gate"] == "T2"
    steps = [item["step"] for item in data["items"]]
    assert steps == list(range(1, len(steps) + 1)) and len(steps) >= 5
    assert any("quality_guard" in item["action"] for item in data["items"])
    assert leader.get("/api/v1/meeting-templates/nope/checklist").status_code == 404


# ---------------------------------------------------------------------------
# SOW agent_trace（V9 尾环 + V11 导出标注）
# ---------------------------------------------------------------------------


def test_sow_export_carries_agent_trace(db_session, d4_client, d4_app, d4_settings) -> None:
    """接线后 SOW 导出 content_snapshot 带 agent_trace（run + 产物指纹 + 降级）。"""
    from test_project_solutions import _opportunity, _persist_doc_template

    leader, project, solution, agent = _project_with_solution(db_session, d4_client, d4_settings)
    opportunity = _opportunity(db_session, project)
    solution.opportunities = []  # 直接建.solution 无关联；导出前补一条（SOW 测试先例需 ≥1）
    from fde_api.solutions.models import ProjectSolutionOpportunity

    db_session.add(ProjectSolutionOpportunity(
        solution_id=solution.id, opportunity_id=opportunity.id, sort_order=0, snapshot_json={}
    ))
    _persist_doc_template(db_session, leader.user)
    _seal_t2(leader, project, solution.id)
    prime_run(d4_app, events=ScriptedEvents([[{"type": "done", "exit_code": 0}]]), scanner_factory=_scanner_factory)
    wired = leader.post(
        f"/api/v1/projects/{project.id}/solutions/{solution.id}/generate-agent",
        json={"agent_id": agent.id, "idempotency_key": f"sow:{uuid4().hex}"},
    )
    assert wired.status_code == 201, wired.json
    patched = leader.patch(
        f"/api/v1/projects/{project.id}/solutions/{solution.id}",
        json={"version": solution.version, "design_markdown": "导出用方案设计正文"},
    )
    assert patched.status_code == 200, patched.json
    db_session.expire_all()
    current_version = db_session.get(ProjectSolution, solution.id).version
    exported = leader.post(
        f"/api/v1/projects/{project.id}/solutions/{solution.id}/export-sow",
        json={"version": current_version},
    )
    assert exported.status_code == 200, exported.json
    from fde_api.documents.models import ProjectDocumentVersion

    version = db_session.get(ProjectDocumentVersion, exported.json["data"]["document_version_id"])
    trace = version.content_snapshot_json["agent_trace"]
    assert trace["agent_run_id"] == wired.json["data"]["agent_run_id"]
    assert trace["degraded"] is False and trace["generated_by"] == "agent"
    assert trace["artifacts"] and len(trace["artifacts"][0]["sha256"]) == 64
