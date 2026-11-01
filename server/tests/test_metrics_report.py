"""goal-d8：P0/P1 指标报表（PRD §10 只读聚合）。

- 空库：insufficient_data 指标显式灰态（不编造数值）、零样本指标返回 0。
- 造数据后：确认率 / lite 占比 / 一次通过率 / 降级率 / 成本中位数 /
  当月动作计数逐指标核对。
- 权限：require_auth 登录即可（脱敏聚合无客户数据）。
"""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import select

from test_agents_d4_harness import d4_app, d4_client, d4_settings  # noqa: F401  (pytest fixture)
from test_document_drafts_api import _persist_project

from fde_api.agents.models import AgentRegistry, AgentRun, SeatActionLedger
from fde_api.auth.models import User
from fde_api.auth.passwords import hash_password
from fde_api.auth.tokens import issue_access_token
from fde_api.files.models import ProjectFile, ProjectFileVersion
from fde_api.guidance.models import ProjectGuidanceAnalysis
from fde_api.meetings.models import ReviewMeeting

from conftest import INITIAL_PASSWORD


def _user(username: str, role: str = "admin") -> User:
    return User(
        username=f"{username}.{uuid4().hex[:8]}",
        display_name=username,
        role=role,
        password_hash=hash_password(INITIAL_PASSWORD),
        must_change_password=False,
        is_active=True,
    )


def _get_report(client, user, settings):
    headers = {"Authorization": f"Bearer {issue_access_token(user, settings)}"}
    return client.get("/api/v1/metrics/report", headers=headers)


def _cards(report: dict, section: str) -> dict[str, dict]:
    return {card["key"]: card for card in report["sections"][section]}


def _guidance(db_session, project, leader, *, status: str, version_number: int) -> None:
    """文件版本桩 + 指引分析行（沿 test_goal_d2_s0_closeout 桩模式）。"""
    file_id, version_id = uuid4().hex, uuid4().hex
    project_file = ProjectFile(
        id=file_id, project=project, category="attachment",
        # project_files 有 (project, category, display_name) 唯一约束——
        # 同项目多版本分析时文件名带版本后缀
        display_name=f"预调研表-v{version_number}", description="", created_by=leader,
    )
    db_session.add(project_file)
    db_session.flush()  # 先落文件行（analysis 以裸字符串引用 source_file_id）
    db_session.add(
        ProjectFileVersion(
            id=version_id, project_file=project_file, version_number=1,
            source="upload", original_filename="预调研表.docx",
            safe_filename="presurvey.docx", extension="docx", mime_type="",
            bucket="local", storage_key=f"projects/{project.id}/presurvey.docx",
            size_bytes=10, etag="", sha256="", uploaded_by=leader,
            status="available", scan_status="clean", preview_status="none",
        )
    )
    db_session.flush()  # 版本行先落（analysis 以裸字符串引用两个 FK）
    db_session.add(
        ProjectGuidanceAnalysis(
            project_id=project.id, version_number=version_number,
            source_file_id=file_id, source_file_version_id=version_id,
            source_filename="预调研表.docx", source_sha256="",
            status=status, analysis_state="ready" if status == "confirmed" else "queued",
            created_by_user_id=leader.id,
        )
    )
    db_session.commit()


def test_report_requires_auth(client, d4_settings) -> None:
    body = client.get("/api/v1/metrics/report")
    assert body.status_code == 401


def test_empty_report_flags_insufficient_and_zeroes(db_session, client, d4_settings) -> None:
    """空库：三缺埋点指标 insufficient_data；零样本占比指标显式 0.0。"""
    user = _user("m8.reader")
    db_session.add(user)
    db_session.commit()
    body = _get_report(client, user, d4_settings)
    assert body.status_code == 200, body.json
    report = body.json["data"]
    assert report["generated_at"]
    p0 = _cards(report, "p0")
    p1 = _cards(report, "p1_pilot")
    ongoing = _cards(report, "ongoing")
    # 缺事件埋点三类：显式 insufficient，value 为 None
    for key, card in (
        ("sow_first_pass_rate", p0["sow_first_pass_rate"]),
        ("senior_intervention_hours", p0["senior_intervention_hours"]),
        ("interception_rate", ongoing["interception_rate"]),
    ):
        assert card["status"] == "insufficient_data", (key, card)
        assert card["value"] is None
        assert card["sample_size"] == 0
    # 零样本占比：0.0 + ok 态（口径成立只是没样本）
    assert p0["presurvey_confirm_rate"]["value"] == 0.0
    assert p0["draft_generation_p50_ms"]["value"] is None
    assert p1["lite_meeting_share"]["value"] == 0.0
    assert p1["run_first_pass_rate"]["value"] == 0.0
    assert p1["run_degraded_share"]["value"] == 0.0
    assert ongoing["seat_actions_month"]["value"] == 0
    assert ongoing["seat_actions_month"]["detail"]["over_quota_rows"] == 0


def test_guidance_confirm_rate_counts_projects(db_session, client, d4_settings) -> None:
    """确认率：confirmed 版按 project 去重；draft 不计。"""
    leader = _user("m8.leader", role="project_lead")
    db_session.add(leader)
    db_session.commit()
    project_a = _persist_project(db_session, leader, code=f"M8A{uuid4().hex[:6]}")
    project_b = _persist_project(db_session, leader, code=f"M8B{uuid4().hex[:6]}")
    _guidance(db_session, project_a, leader, status="confirmed", version_number=1)
    _guidance(db_session, project_a, leader, status="confirmed", version_number=2)
    _guidance(db_session, project_b, leader, status="draft", version_number=1)
    body = _get_report(client, leader, d4_settings)
    card = _cards(body.json["data"], "p0")["presurvey_confirm_rate"]
    assert card["sample_size"] == 2  # 出现过分析版的项目数
    assert card["value"] == 0.5  # 只有 project_a confirmed
    assert card["target"] == 0.90


def test_run_metrics_medians_and_shares(db_session, client, d4_settings) -> None:
    """run 指标：一次通过率（终态占比）、降级率、成本中位数、草稿耗时中位数。"""
    leader = _user("m8.leader2", role="project_lead")
    db_session.add(leader)
    db_session.commit()
    project = _persist_project(db_session, leader, code=f"M8C{uuid4().hex[:6]}")
    from fde_api.agents.seeds import ensure_agent_seeds

    ensure_agent_seeds(db_session)
    db_session.commit()
    agent = db_session.scalar(select(AgentRegistry).where(AgentRegistry.kind != "persona").limit(1))
    assert agent is not None

    def _run(status: str, *, duration: int = 0, cost: int = 0, degraded: bool = False) -> AgentRun:
        return AgentRun(
            project_id=project.id,
            agent_id=agent.id,
            initiated_by_user_id=leader.id,
            capability_used=agent.capability_tier,
            status=status,
            duration_ms=duration,
            token_cost=cost,
            degraded=degraded,
            degraded_reason="tool_denied" if degraded else None,
            fallback_level="L1" if degraded else None,
            context_ref="agent-workspaces/x/context.md",
            idempotency_key=f"m8:{uuid4().hex}",
        )

    db_session.add_all(
        [
            _run("completed", duration=100, cost=3),
            _run("completed", duration=300, cost=7),
            _run("failed"),
            _run("timeout"),
            _run("completed", degraded=True),
        ]
    )
    db_session.commit()
    body = _get_report(client, leader, d4_settings)
    report = body.json["data"]
    p0 = _cards(report, "p0")
    p1 = _cards(report, "p1_pilot")
    ongoing = _cards(report, "ongoing")
    # completed durations=[100,300,0（降级 completed 未计时）] → median 100
    assert p0["draft_generation_p50_ms"]["value"] == 100
    assert p1["run_first_pass_rate"]["value"] == 0.6  # 3 completed / 5 终态
    assert p1["run_degraded_share"]["value"] == round(1 / 3, 4)
    assert ongoing["run_cost_median_units"]["value"] == 0  # median(3,7,0,0,0)=0


def test_lite_meeting_share_and_quota_month(db_session, client, d4_settings) -> None:
    """lite 占比 + 当月动作台账计数（含 over_quota 行）。"""
    leader = _user("m8.leader3", role="project_lead")
    db_session.add(leader)
    db_session.commit()
    project = _persist_project(db_session, leader, code=f"M8D{uuid4().hex[:6]}")
    db_session.add_all(
        [
            ReviewMeeting(
                project_id=project.id, template_id="T2-lite",
                hosted_by_user_id=leader.id, status="closed",
                gate_tier="lite", turn_budget=2, trigger="mandatory",
            ),
            ReviewMeeting(
                project_id=project.id, template_id="S2-solution-review",
                hosted_by_user_id=leader.id, status="closed",
                gate_tier="std", turn_budget=8, trigger="manual",
            ),
            SeatActionLedger(
                project_id=project.id, user_id=leader.id, action_type="agent_run",
                ref_id="r1", units=1, over_quota=False,
            ),
            SeatActionLedger(
                project_id=project.id, user_id=leader.id, action_type="agent_run",
                ref_id="r2", units=1, over_quota=True,
            ),
        ]
    )
    db_session.commit()
    body = _get_report(client, leader, d4_settings)
    report = body.json["data"]
    p1 = _cards(report, "p1_pilot")
    ongoing = _cards(report, "ongoing")
    assert p1["lite_meeting_share"]["value"] == 0.5
    assert p1["lite_meeting_share"]["sample_size"] == 2
    assert ongoing["seat_actions_month"]["value"] == 2
    assert ongoing["seat_actions_month"]["detail"]["over_quota_rows"] == 1
