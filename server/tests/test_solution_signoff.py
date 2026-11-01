"""goal-d9：终审台拍板收口（PRD §3.2 P3 / 总纲 U5）。

- signoff checkpoint 只有 handoff（E-2）创建的 pending 态可收口；无 pending 409。
- 权限档闸 = checkpoint.required_level（effective_ai_access），低档 403。
- approved/rejected 落 solution_signoff_resolved 事件：attempt=此前 rejected 数+1，
  run_id 经 checkpoint.handoff_run_id 软链携带（资深介入时长配对键）。
- review-trail 合并视图：artifacts（幂等键家族）+ signoff 状态。
- 拍板是人工动作——本路径不进 api_catalog（红线），用例钉住。
"""
from __future__ import annotations

from uuid import uuid4

from test_agents_d4_harness import api_client, d4_app, d4_client, d4_settings  # noqa: F401  (pytest fixture)
from test_document_drafts_api import _persist_project

from test_agents_d4_harness import seed_agent

from fde_api.agents.models import AgentArtifact, AgentRun, SolutionReviewCheckpoint
from fde_api.control.api_catalog import CATALOG
from fde_api.solutions.models import ProjectSolution
from fde_api.workbench.models import OperationEvent


def _solution(db_session, project, owner) -> ProjectSolution:
    solution = ProjectSolution(project_id=project.id, name="终审方案", owner_user_id=owner.id)
    db_session.add(solution)
    db_session.commit()
    return solution


def _checkpoint(db_session, solution, *, required_level: str = "project_manager", status: str = "pending", run_id: str | None = None) -> SolutionReviewCheckpoint:
    checkpoint = SolutionReviewCheckpoint(
        solution_id=solution.id, checkpoint_type="signoff",
        required_level=required_level, status=status, handoff_run_id=run_id,
    )
    db_session.add(checkpoint)
    db_session.commit()
    return checkpoint


def _signoff(client_wrapper, project, solution, payload):
    return client_wrapper.post(
        f"/api/v1/projects/{project.id}/solutions/{solution.id}/signoff", json=payload
    )


def test_signoff_requires_auth(d4_client, db_session, d4_settings) -> None:
    leader = api_client(d4_client, db_session, d4_settings, "project_lead")
    project = _persist_project(db_session, leader.user, code=f"SG{uuid4().hex[:4]}")
    solution = _solution(db_session, project, leader.user)
    body = d4_client.post(f"/api/v1/projects/{project.id}/solutions/{solution.id}/signoff", json={"decision": "approved"})
    assert body.status_code == 401
    # 静默护栏：已登录也不该 405（路由存在性核对）
    assert leader.get(f"/api/v1/projects/{project.id}/solutions/{solution.id}/review-trail").status_code == 200


def test_signoff_without_pending_checkpoint_409(d4_client, db_session, d4_settings) -> None:
    leader = api_client(d4_client, db_session, d4_settings, "project_lead")
    project = _persist_project(db_session, leader.user, code=f"SG{uuid4().hex[:4]}")
    solution = _solution(db_session, project, leader.user)
    body = _signoff(leader, project, solution, {"decision": "approved"})
    assert body.status_code == 409, body.json
    assert body.json["error"]["code"] == "signoff_not_pending"


def test_signoff_rejects_low_access_level(d4_client, db_session, d4_settings) -> None:
    leader = api_client(d4_client, db_session, d4_settings, "project_lead")
    project = _persist_project(db_session, leader.user, code=f"SG{uuid4().hex[:4]}")
    solution = _solution(db_session, project, leader.user)
    _checkpoint(db_session, solution, required_level="system_operator")
    body = _signoff(leader, project, solution, {"decision": "approved"})
    assert body.status_code == 403, body.json
    assert body.json["error"]["code"] == "signoff_level_required"


def test_signoff_decision_validated(d4_client, db_session, d4_settings) -> None:
    leader = api_client(d4_client, db_session, d4_settings, "project_lead")
    project = _persist_project(db_session, leader.user, code=f"SG{uuid4().hex[:4]}")
    solution = _solution(db_session, project, leader.user)
    _checkpoint(db_session, solution)
    assert _signoff(leader, project, solution, {"decision": "maybe"}).status_code == 400
    assert _signoff(leader, project, solution, {"decision": "approved", "evidence_ref": "x" * 256}).status_code == 400
    assert _signoff(leader, project, solution, {"decision": "approved", "extra": 1}).status_code == 400


def test_signoff_approve_records_attempt1_event(d4_client, db_session, d4_settings) -> None:
    leader = api_client(d4_client, db_session, d4_settings, "project_lead")
    project = _persist_project(db_session, leader.user, code=f"SG{uuid4().hex[:4]}")
    solution = _solution(db_session, project, leader.user)
    checkpoint = _checkpoint(db_session, solution)
    body = _signoff(leader, project, solution, {"decision": "approved", "evidence_ref": "reviews/signoff-1.pdf"})
    assert body.status_code == 200, body.json
    assert body.json["data"]["status"] == "approved"
    assert body.json["data"]["checkpoint_id"] == checkpoint.id
    db_session.refresh(checkpoint)
    assert checkpoint.status == "approved"
    assert checkpoint.reviewer_user_id == leader.user.id
    event = db_session.query(OperationEvent).filter(
        OperationEvent.event_type == "solution_signoff_resolved",
        OperationEvent.project_id == project.id,
    ).one()
    assert event.changes["solution_id"] == solution.id
    assert event.changes["decision"] == "approved"
    assert event.changes["attempt"] == 1
    assert event.changes["run_id"] is None  # 无 handoff 软链 → run_id 缺席


def test_signoff_reject_then_approve_attempt_grows(d4_client, db_session, d4_settings) -> None:
    leader = api_client(d4_client, db_session, d4_settings, "project_lead")
    project = _persist_project(db_session, leader.user, code=f"SG{uuid4().hex[:4]}")
    solution = _solution(db_session, project, leader.user)
    first = _checkpoint(db_session, solution)
    rejected = _signoff(leader, project, solution, {"decision": "rejected"})
    assert rejected.status_code == 200
    db_session.refresh(first)
    assert first.status == "rejected"
    # 驳回后重新走 handoff 通道产生新 pending checkpoint（此处 ORM 等价造数）
    _checkpoint(db_session, solution)
    approved = _signoff(leader, project, solution, {"decision": "approved"})
    assert approved.status_code == 200
    event = db_session.query(OperationEvent).filter(
        OperationEvent.event_type == "solution_signoff_resolved",
        OperationEvent.project_id == project.id,
    ).order_by(OperationEvent.created_at.asc(), OperationEvent.id.asc()).all()
    assert [row.changes["attempt"] for row in event] == [1, 2]
    assert [row.changes["decision"] for row in event] == ["rejected", "approved"]


def test_signoff_event_carries_run_link(d4_client, db_session, d4_settings) -> None:
    leader = api_client(d4_client, db_session, d4_settings, "project_lead")
    project = _persist_project(db_session, leader.user, code=f"SG{uuid4().hex[:4]}")
    solution = _solution(db_session, project, leader.user)
    run = AgentRun(
        project_id=project.id, agent_id=_agent(db_session, d4_settings).id,
        initiated_by_user_id=leader.user.id, capability_used="agent.plan.generate",
        status="failed", context_ref="ctx", idempotency_key=f"{solution.id}:fp",
    )
    db_session.add(run)
    db_session.commit()
    _checkpoint(db_session, solution, run_id=run.id)
    body = _signoff(leader, project, solution, {"decision": "approved"})
    assert body.status_code == 200
    assert body.json["data"]["handoff_run_id"] == run.id
    event = db_session.query(OperationEvent).filter(
        OperationEvent.event_type == "solution_signoff_resolved",
        OperationEvent.project_id == project.id,
    ).one()
    assert event.changes["run_id"] == run.id


def test_review_trail_merges_artifacts_and_signoff(d4_client, db_session, d4_settings) -> None:
    leader = api_client(d4_client, db_session, d4_settings, "project_lead")
    project = _persist_project(db_session, leader.user, code=f"SG{uuid4().hex[:4]}")
    solution = ProjectSolution(
        project_id=project.id, name="终审方案", owner_user_id=leader.user.id,
        agent_run_id=None,
    )
    db_session.add(solution)
    db_session.commit()
    agent = _agent(db_session, d4_settings)
    anchor = AgentRun(
        project_id=project.id, agent_id=agent.id, initiated_by_user_id=leader.user.id,
        capability_used="agent.plan.generate", status="completed", context_ref="ctx",
        idempotency_key=f"{solution.id}:fp",
    )
    db_session.add(anchor)
    db_session.commit()
    db_session.add(AgentArtifact(
        run_id=anchor.id, kind="doc", storage_ref=f"{anchor.id}/output/plan.md",
        sha256="a" * 64, reviewed=False, linked_solution_id=solution.id,
    ))
    db_session.add(AgentArtifact(
        run_id=anchor.id, kind="code", storage_ref=f"{anchor.id}/output/bad.py",
        sha256="b" * 64, reviewed=False, linked_solution_id=None,  # 拦截/降级留痕
    ))
    checkpoint = _checkpoint(db_session, solution, run_id=anchor.id)
    body = leader.get(f"/api/v1/projects/{project.id}/solutions/{solution.id}/review-trail")
    assert body.status_code == 200
    data = body.json["data"]
    kinds = {item["kind"] for item in data["artifacts"]}
    assert kinds == {"doc", "code"}
    assert all(item["run_id"] == anchor.id for item in data["artifacts"])
    assert data["signoff"]["checkpoint_id"] == checkpoint.id
    assert data["signoff"]["status"] == "pending"
    assert data["signoff"]["handoff_run_id"] == anchor.id


def test_signoff_never_in_catalog() -> None:
    """红线钉子：人工拍板路径永不进 api_catalog（不收代拍板写路径）。"""
    assert not any("signoff" in key for key in CATALOG)


def _agent(db_session, settings):
    return seed_agent(db_session, settings, name="终审沙箱智能体", credential_ref=f"zcode-{uuid4().hex[:8]}")
