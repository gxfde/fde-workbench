"""goal-d9：终审台拍板收口（PRD §3.2 P3 / 总纲 U5）。

- signoff checkpoint 只有 handoff（E-2）创建的 pending 态可收口；无 pending 409。
- 权限档闸 = checkpoint.required_level（effective_ai_access），低档 403。
- approved/rejected 落 solution_signoff_resolved 事件：attempt=此前 rejected 数+1，
  run_id 经 checkpoint.handoff_run_id 软链携带（资深介入时长配对键）。
- review-trail 合并视图：artifacts（幂等键家族）+ signoff 状态。
- 拍板是人工动作——本路径不进 api_catalog（红线），用例钉住。
- goal-d13 拍板：approved 翻转终审通道内产物 reviewed=True（拦截留痕不翻）；
  agent_assisted 交付包绑定的方案导出 SOW 前 409 solution_signoff_required。
"""
from __future__ import annotations

from uuid import uuid4

from test_agents_d4_harness import api_client, d4_app, d4_client, d4_settings  # noqa: F401  (pytest fixture)
from test_document_drafts_api import _persist_project

from test_agents_d4_harness import seed_agent

from fde_api.agents.models import AgentArtifact, AgentRun, SolutionReviewCheckpoint
from fde_api.control.api_catalog import CATALOG
from fde_api.dispatch.models import DeliveryPackage
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


# ---------------------------------------------------------------------------
# goal-d13 拍板实施：approved 翻转 reviewed + agent_assisted 导出闸

def _package(db_session, project, solution, *, agent_assisted: bool) -> DeliveryPackage:
    package = DeliveryPackage(
        id=solution.id, solution_id=solution.id, project_id=project.id,
        package_code=f"PKG-{uuid4().hex[:10].upper()}",
        dispatch_status="draft", agent_assisted=agent_assisted,
    )
    db_session.add(package)
    db_session.commit()
    return package


def _completed_run_with_artifacts(db_session, project, solution, leader, settings) -> None:
    run = AgentRun(
        project_id=project.id, agent_id=_agent(db_session, settings).id,
        initiated_by_user_id=leader.user.id, capability_used="agent.plan.generate",
        status="completed", context_ref="ctx", idempotency_key=f"{solution.id}:fp",
    )
    db_session.add(run)
    db_session.commit()
    db_session.add_all([
        AgentArtifact(run_id=run.id, kind="doc", storage_ref=f"{run.id}/output/plan.md",
                      sha256="a" * 64, reviewed=False, linked_solution_id=solution.id),
        AgentArtifact(run_id=run.id, kind="code", storage_ref=f"{run.id}/output/bad.py",
                      sha256="b" * 64, reviewed=False, linked_solution_id=None),  # 拦截留痕
    ])
    db_session.commit()


def test_approved_flips_reviewed_on_linked_artifacts(d4_client, db_session, d4_settings) -> None:
    """goal-d13 拍板：approved = 人工核验完成 → 终审通道内产物（linked 绑定）
    reviewed=False → True；拦截/降级留痕（linked=None）不翻转；事件携翻转计数。"""
    leader = api_client(d4_client, db_session, d4_settings, "project_lead")
    project = _persist_project(db_session, leader.user, code=f"SG{uuid4().hex[:4]}")
    solution = _solution(db_session, project, leader.user)
    _completed_run_with_artifacts(db_session, project, solution, leader, d4_settings)
    _checkpoint(db_session, solution)
    body = _signoff(leader, project, solution, {"decision": "approved"})
    assert body.status_code == 200, body.json
    artifacts = db_session.query(AgentArtifact).filter(
        AgentArtifact.linked_solution_id == solution.id).all()
    assert len(artifacts) == 1 and artifacts[0].reviewed is True
    blocked = db_session.query(AgentArtifact).filter(
        AgentArtifact.linked_solution_id.is_(None),
        AgentArtifact.sha256 == "b" * 64).one()
    assert blocked.reviewed is False
    event = db_session.query(OperationEvent).filter(
        OperationEvent.event_type == "solution_signoff_resolved",
        OperationEvent.project_id == project.id,
    ).one()
    assert event.changes["artifacts_reviewed_flipped"] == 1


def test_rejected_keeps_reviewed_false(d4_client, db_session, d4_settings) -> None:
    """rejected 不翻转任何产物（人工核验未完成）；事件翻转计数为 0。"""
    leader = api_client(d4_client, db_session, d4_settings, "project_lead")
    project = _persist_project(db_session, leader.user, code=f"SG{uuid4().hex[:4]}")
    solution = _solution(db_session, project, leader.user)
    _completed_run_with_artifacts(db_session, project, solution, leader, d4_settings)
    _checkpoint(db_session, solution)
    body = _signoff(leader, project, solution, {"decision": "rejected"})
    assert body.status_code == 200, body.json
    assert db_session.query(AgentArtifact).filter(
        AgentArtifact.linked_solution_id == solution.id).one().reviewed is False
    event = db_session.query(OperationEvent).filter(
        OperationEvent.event_type == "solution_signoff_resolved",
        OperationEvent.project_id == project.id,
    ).one()
    assert event.changes["artifacts_reviewed_flipped"] == 0


def test_export_sow_requires_signoff_only_for_agent_assisted(d4_client, db_session, d4_settings) -> None:
    """goal-d13 拍板：agent_assisted 包绑定方案未 approved → 409
    solution_signoff_required（闸在复用路径之前，严格口径）；纯人工方案不受影响。"""
    leader = api_client(d4_client, db_session, d4_settings, "project_lead")
    project = _persist_project(db_session, leader.user, code=f"SG{uuid4().hex[:4]}")
    solution = _solution(db_session, project, leader.user)
    _package(db_session, project, solution, agent_assisted=True)
    url = f"/api/v1/projects/{project.id}/solutions/{solution.id}/export-sow"
    blocked = leader.post(url, json={"version": 1})
    assert blocked.status_code == 409, blocked.json
    assert blocked.json["error"]["code"] == "solution_signoff_required"


def test_export_sow_unaffected_without_agent_assisted(d4_client, db_session, d4_settings) -> None:
    """纯人工方案（无包或 agent_assisted=False）不碰终审闸：错误码越过
    signoff 直落业务校验（solution_design_required）。"""
    leader = api_client(d4_client, db_session, d4_settings, "project_lead")
    project = _persist_project(db_session, leader.user, code=f"SG{uuid4().hex[:4]}")
    solution = _solution(db_session, project, leader.user)
    _package(db_session, project, solution, agent_assisted=False)
    url = f"/api/v1/projects/{project.id}/solutions/{solution.id}/export-sow"
    plain = leader.post(url, json={"version": 1})
    assert plain.status_code == 400, plain.json
    assert plain.json["error"]["code"] == "solution_design_required"


def test_export_sow_gate_opens_after_approval(d4_client, db_session, d4_settings) -> None:
    """approved 后闸开：同一 agent_assisted 方案越过 signoff 闸落下一道业务校验。"""
    leader = api_client(d4_client, db_session, d4_settings, "project_lead")
    project = _persist_project(db_session, leader.user, code=f"SG{uuid4().hex[:4]}")
    solution = _solution(db_session, project, leader.user)
    _package(db_session, project, solution, agent_assisted=True)
    _checkpoint(db_session, solution)
    url = f"/api/v1/projects/{project.id}/solutions/{solution.id}/export-sow"
    assert _signoff(leader, project, solution, {"decision": "approved"}).status_code == 200
    opened = leader.post(url, json={"version": 1})
    assert opened.status_code == 400, opened.json
    assert opened.json["error"]["code"] == "solution_design_required"


def _agent(db_session, settings):
    return seed_agent(db_session, settings, name="终审沙箱智能体", credential_ref=f"zcode-{uuid4().hex[:8]}")
