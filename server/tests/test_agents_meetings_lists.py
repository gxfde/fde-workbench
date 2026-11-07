"""T-A8：agents/meetings 列表路由（GET /api/v1/agents/runs、GET /api/v1/meetings）。

桌面控制台数据源（拍板 §拍板闸 6⑥：与 B#9 界面分离，数据源=智能体运行态）：
- 列表权限 can_view（局外人 403 / 未知项目 404 / 未认证 401）；
- project/status/时间过滤＋有界分页（limit 1..200、offset ≥0、truncated）；
- 列表行不带嵌套详情防 N+1（runs 行无 agent/artifacts 键；meetings 行无
  turns 键、话轮计数预聚合）。
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from urllib.parse import quote
from uuid import uuid4

from test_agents_d4_harness import (
    ApiClient,
    api_client,
    issue_access_token,
    make_user,
    seed_agent,
)
from test_agents_d4_harness import d4_app, d4_client, d4_settings  # noqa: F401  (pytest fixture)
from test_document_drafts_api import _persist_project

from fde_api.agents.models import AgentRun
from fde_api.meetings.models import ReviewMeeting, ReviewMeetingTurn
from fde_api.workbench.models import ProjectMember


def _member_client(db_session, d4_client, d4_settings, project, role: str = "fde_engineer") -> tuple[ApiClient, object]:
    """入项目的普通成员＋其已认证客户端（列表 can_view 面的主角）。"""
    user = make_user(db_session, role)
    db_session.add(ProjectMember(project_id=project.id, user_id=user.id, role="member"))
    db_session.commit()
    return ApiClient(d4_client, user, {"Authorization": f"Bearer {issue_access_token(user, d4_settings)}"}), user


def _seed_run(db_session, project, user, agent_id: str, *, status: str = "completed", age_hours: int = 0, cost: int = 10) -> AgentRun:
    run = AgentRun(
        project_id=project.id,
        agent_id=agent_id,
        initiated_by_user_id=user.id,
        capability_used="agent.code.write",
        status=status,
        context_ref="agent-workspaces/x/context.md",
        token_cost=cost,
        idempotency_key=f"ta8:{uuid4().hex}",
    )
    if age_hours:
        run.created_at = datetime.now(timezone.utc) - timedelta(hours=age_hours)
    db_session.add(run)
    db_session.commit()
    return run


def _seed_meeting(db_session, project, host, *, status: str = "live", turns: int = 0) -> ReviewMeeting:
    meeting = ReviewMeeting(
        project_id=project.id,
        template_id="T2-lite",
        status=status,
        hosted_by_user_id=host.id,
    )
    db_session.add(meeting)
    db_session.flush()
    for seq in range(1, turns + 1):
        db_session.add(
            ReviewMeetingTurn(
                meeting_id=meeting.id,
                seq=seq,
                speaker_user_id=host.id,
                content={"text": f"话轮 {seq}"},
            )
        )
    db_session.commit()
    return meeting


def test_agents_runs_list_scoped_to_visible_projects(db_session, d4_client, d4_settings) -> None:
    """成员只看到可见项目的 run；列表行不带详情键（防 N+1 的形状面）。"""
    leader = api_client(d4_client, db_session, d4_settings, "project_lead")
    project_a = _persist_project(db_session, leader.user, code=f"TA8A{uuid4().hex[:4]}")
    outsider_leader = api_client(d4_client, db_session, d4_settings, "project_lead")
    project_b = _persist_project(db_session, outsider_leader.user, code=f"TA8B{uuid4().hex[:4]}")
    agent = seed_agent(db_session, d4_settings)
    member_client, member = _member_client(db_session, d4_client, d4_settings, project_a)
    run_a1 = _seed_run(db_session, project_a, member, agent.id, status="completed")
    run_a2 = _seed_run(db_session, project_a, leader.user, agent.id, status="failed")
    _seed_run(db_session, project_b, outsider_leader.user, agent.id, status="running")

    response = member_client.get("/api/v1/agents/runs")
    assert response.status_code == 200, response.json
    data = response.json["data"]
    assert {item["id"] for item in data["items"]} == {run_a1.id, run_a2.id}
    assert data["truncated"] is False
    for item in data["items"]:
        assert "agent" not in item  # 详情键不外泄
        assert "artifacts" not in item
        assert item["project_id"] == project_a.id


def test_agents_runs_list_project_filter_and_outsider_403(db_session, d4_client, d4_settings) -> None:
    """project_id 过滤生效；局外人 403；未知项目 404。"""
    leader = api_client(d4_client, db_session, d4_settings, "project_lead")
    project = _persist_project(db_session, leader.user, code=f"TA8C{uuid4().hex[:4]}")
    agent = seed_agent(db_session, d4_settings)
    _seed_run(db_session, project, leader.user, agent.id, status="completed")

    outsider = api_client(d4_client, db_session, d4_settings, "fde_engineer")
    forbidden = outsider.get(f"/api/v1/agents/runs?project_id={project.id}")
    assert forbidden.status_code == 403, forbidden.json
    assert forbidden.json["error"]["code"] == "project_forbidden"

    missing = leader.get("/api/v1/agents/runs?project_id=no-such-project")
    assert missing.status_code == 404, missing.json

    ok = leader.get(f"/api/v1/agents/runs?project_id={project.id}")
    assert ok.status_code == 200, ok.json
    assert len(ok.json["data"]["items"]) == 1


def test_agents_runs_list_filters_pagination_and_validation(db_session, d4_client, d4_settings) -> None:
    """status/时间过滤 + limit 上界/下界/非法值 + offset 负值 + truncated。"""
    leader = api_client(d4_client, db_session, d4_settings, "project_lead")
    project = _persist_project(db_session, leader.user, code=f"TA8D{uuid4().hex[:4]}")
    agent = seed_agent(db_session, d4_settings)
    _seed_run(db_session, project, leader.user, agent.id, status="completed", age_hours=3)
    _seed_run(db_session, project, leader.user, agent.id, status="failed", age_hours=2)
    _seed_run(db_session, project, leader.user, agent.id, status="running", age_hours=1)

    only_failed = leader.get(f"/api/v1/agents/runs?project_id={project.id}&status=failed")
    assert only_failed.status_code == 200
    assert [item["status"] for item in only_failed.json["data"]["items"]] == ["failed"]

    recent = leader.get(
        f"/api/v1/agents/runs?project_id={project.id}"
        f"&created_from={quote((datetime.now(timezone.utc) - timedelta(hours=4)).isoformat())}"
    )
    assert recent.status_code == 200
    assert len(recent.json["data"]["items"]) == 3
    stale_window = leader.get(
        f"/api/v1/agents/runs?project_id={project.id}"
        f"&created_to={quote((datetime.now(timezone.utc) - timedelta(hours=2, minutes=30)).isoformat())}"
    )
    assert stale_window.status_code == 200
    assert [item["status"] for item in stale_window.json["data"]["items"]] == ["completed"]

    paged = leader.get(f"/api/v1/agents/runs?project_id={project.id}&limit=2&offset=0")
    assert paged.status_code == 200
    assert len(paged.json["data"]["items"]) == 2
    assert paged.json["data"]["truncated"] is True
    # offset 翻页：跳过最新一条后取到剩余两条，且无更多（truncated=False）
    paged_next = leader.get(f"/api/v1/agents/runs?project_id={project.id}&limit=2&offset=1")
    assert paged_next.status_code == 200
    assert len(paged_next.json["data"]["items"]) == 2
    assert paged_next.json["data"]["truncated"] is False

    for query in ("limit=0", "limit=201", "limit=abc", "offset=-1", "offset=xyz"):
        bad = leader.get(f"/api/v1/agents/runs?project_id={project.id}&{query}")
        assert bad.status_code == 400, (query, bad.json)
        assert bad.json["error"]["code"] == "invalid_request"

    unauth = d4_client.get("/api/v1/agents/runs")
    assert unauth.status_code == 401


def test_meetings_list_scoped_rows_and_turn_counts(db_session, d4_client, d4_settings) -> None:
    """会议列表：可见项目聚合 + 行不带 turns 键 + 话轮计数预聚合正确。"""
    leader = api_client(d4_client, db_session, d4_settings, "project_lead")
    project_a = _persist_project(db_session, leader.user, code=f"TA8E{uuid4().hex[:4]}")
    outsider_leader = api_client(d4_client, db_session, d4_settings, "project_lead")
    project_b = _persist_project(db_session, outsider_leader.user, code=f"TA8F{uuid4().hex[:4]}")
    meeting_a = _seed_meeting(db_session, project_a, leader.user, turns=3)
    _seed_meeting(db_session, project_b, outsider_leader.user)
    member_client, _member = _member_client(db_session, d4_client, d4_settings, project_a)

    response = member_client.get("/api/v1/meetings")
    assert response.status_code == 200, response.json
    data = response.json["data"]
    assert [item["id"] for item in data["items"]] == [meeting_a.id]
    row = data["items"][0]
    assert "turns" not in row  # 话轮正文不外泄
    assert row["turns_count"] == 3
    assert row["status"] == "live"

    scoped = member_client.get(f"/api/v1/meetings?project_id={project_a.id}")
    assert scoped.status_code == 200
    assert [item["id"] for item in scoped.json["data"]["items"]] == [meeting_a.id]


def test_meetings_list_outsider_403_pagination_and_validation(db_session, d4_client, d4_settings) -> None:
    """局外人 403；未知项目 404；limit/offset 校验；truncated 标记。"""
    leader = api_client(d4_client, db_session, d4_settings, "project_lead")
    project = _persist_project(db_session, leader.user, code=f"TA8G{uuid4().hex[:4]}")
    _seed_meeting(db_session, project, leader.user)
    _seed_meeting(db_session, project, leader.user)
    _seed_meeting(db_session, project, leader.user)

    outsider = api_client(d4_client, db_session, d4_settings, "fde_engineer")
    forbidden = outsider.get(f"/api/v1/meetings?project_id={project.id}")
    assert forbidden.status_code == 403, forbidden.json
    assert forbidden.json["error"]["code"] == "project_forbidden"

    missing = leader.get("/api/v1/meetings?project_id=no-such-project")
    assert missing.status_code == 404, missing.json

    paged = leader.get(f"/api/v1/meetings?project_id={project.id}&limit=2&offset=0")
    assert paged.status_code == 200
    assert len(paged.json["data"]["items"]) == 2
    assert paged.json["data"]["truncated"] is True

    for query in ("limit=0", "limit=201", "limit=abc", "offset=-1", "offset=xyz"):
        bad = leader.get(f"/api/v1/meetings?project_id={project.id}&{query}")
        assert bad.status_code == 400, (query, bad.json)
        assert bad.json["error"]["code"] == "invalid_request"

    unauth = d4_client.get("/api/v1/meetings")
    assert unauth.status_code == 401
