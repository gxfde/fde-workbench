"""goal-d9：终审台拍板收口（PRD §3.2 P3 / 总纲 U5）。

- signoff checkpoint 只有 handoff（E-2）创建的 pending 态可收口；无 pending 409。
- 权限档闸 = checkpoint.required_level（effective_ai_access），低档 403。
- approved/rejected 落 solution_signoff_resolved 事件：attempt=此前 rejected 数+1，
  run_id 经 checkpoint.handoff_run_id 软链携带（资深介入时长配对键）。
- review-trail 合并视图：artifacts（幂等键家族）+ signoff 状态。
- 拍板是人工动作——本路径不进 api_catalog（红线），用例钉住。
- goal-d13 拍板：approved 翻转终审通道内产物 reviewed=True（拦截留痕不翻）；
  agent_assisted 交付包绑定的方案导出 SOW 前 409 solution_signoff_required。
- V3 T-P0-1（审计 WB-DEF-1）：signoff 死锁修复——正常 completed run 由 _finalize
  即开 pending；export 闸拦下且无 pending 时兜底开闸并在 details 指路；L1 仍走 handoff。
"""
from __future__ import annotations

from uuid import uuid4

from test_agents_d4_harness import ScriptedEvents, api_client, d4_app, d4_client, d4_settings, prime_run  # noqa: F401  (pytest fixture)
from test_document_drafts_api import _persist_doc_template, _persist_project
from test_project_solutions import _opportunity
from test_solution_agent_wiring import _project_with_solution, _scanner_factory, _seal_t2

from test_agents_d4_harness import seed_agent

from fde_api.agents.models import AgentArtifact, AgentRun, SolutionReviewCheckpoint
from fde_api.control.api_catalog import CATALOG
from fde_api.dispatch.models import DeliveryPackage
from fde_api.solutions.models import ProjectSolution, ProjectSolutionOpportunity
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


# ---------------------------------------------------------------------------
# V3 T-P0-1（审计 WB-DEF-1）：signoff 死锁修复
#   completed run 即开 pending（_finalize）/ export 闸拦下兜底开闸 / L1 既有语义零回归


def _checkpoints(db_session, solution) -> list[SolutionReviewCheckpoint]:
    return db_session.query(SolutionReviewCheckpoint).filter(
        SolutionReviewCheckpoint.solution_id == solution.id
    ).order_by(SolutionReviewCheckpoint.created_at.asc(), SolutionReviewCheckpoint.id.asc()).all()


def _agent_assisted_generated(db_session, d4_client, d4_app, d4_settings):
    """goal-d6 接线夹具 + agent_assisted 包 + SOW 导出前置（模板/机会）。
    返回 (leader, project, solution, run_id)；run 为正常 completed（非降级、过 T2 门）。"""
    leader, project, solution, agent = _project_with_solution(db_session, d4_client, d4_settings)
    _package(db_session, project, solution, agent_assisted=True)
    opportunity = _opportunity(db_session, project)
    db_session.add(ProjectSolutionOpportunity(
        solution_id=solution.id, opportunity_id=opportunity.id, sort_order=0, snapshot_json={}
    ))
    db_session.commit()
    _persist_doc_template(db_session, leader.user)
    _seal_t2(leader, project, solution.id)
    prime_run(d4_app, events=ScriptedEvents([[{"type": "done", "exit_code": 0}]]), scanner_factory=_scanner_factory)
    wired = leader.post(
        f"/api/v1/projects/{project.id}/solutions/{solution.id}/generate-agent",
        json={"agent_id": agent.id, "idempotency_key": f"p01:{uuid4().hex}"},
    )
    assert wired.status_code == 201, wired.json
    return leader, project, solution, wired.json["data"]["agent_run_id"]


def test_t_p0_1_completed_run_opens_pending_signoff_and_unblocks_export(db_session, d4_client, d4_app, d4_settings) -> None:
    """WB-DEF-1 复现→修复：正常 completed 的 agent_assisted 方案此前既不能 handoff
    （只收失败/L1）又无其它开闸点 → export-sow 与 signoff 双 409 永久死锁。修复后：
    _finalize 即开 pending（软链 run）→ export 409 携 checkpoint_id/remedy →
    终审台拍板 approved → export 200；全程方案只有一个 checkpoint（幂等）。"""
    leader, project, solution, run_id = _agent_assisted_generated(db_session, d4_client, d4_app, d4_settings)
    # 死锁的另一半语义不变：正常 completed 仍不可 handoff
    denied = leader.post(f"/api/v1/agents/runs/{run_id}/handoff", json={"solution_id": solution.id})
    assert denied.status_code == 409 and denied.json["error"]["code"] == "agent_handoff_not_allowed"
    rows = _checkpoints(db_session, solution)
    assert len(rows) == 1
    assert rows[0].status == "pending" and rows[0].checkpoint_type == "signoff"
    assert rows[0].required_level == "project_manager" and rows[0].handoff_run_id == run_id
    db_session.expire_all()
    version = db_session.get(ProjectSolution, solution.id).version
    url = f"/api/v1/projects/{project.id}/solutions/{solution.id}/export-sow"
    blocked = leader.post(url, json={"version": version})
    assert blocked.status_code == 409, blocked.json
    assert blocked.json["error"]["code"] == "solution_signoff_required"
    details = blocked.json["error"]["details"]
    assert details["signoff_checkpoint_id"] == rows[0].id and details["signoff_status"] == "pending"
    assert details["remedy"] == "resolve_pending_signoff"
    assert details["remedy_path"].endswith(f"/solutions/{solution.id}/signoff")
    assert len(_checkpoints(db_session, solution)) == 1  # 兜底不重复开闸
    trail = leader.get(f"/api/v1/projects/{project.id}/solutions/{solution.id}/review-trail")
    assert trail.status_code == 200 and trail.json["data"]["signoff"]["status"] == "pending"
    approved = _signoff(leader, project, solution, {"decision": "approved"})
    assert approved.status_code == 200, approved.json
    assert approved.json["data"]["handoff_run_id"] == run_id
    patched = leader.patch(
        f"/api/v1/projects/{project.id}/solutions/{solution.id}",
        json={"version": version, "design_markdown": "导出用方案设计正文"},
    )
    assert patched.status_code == 200, patched.json
    db_session.expire_all()
    version = db_session.get(ProjectSolution, solution.id).version
    exported = leader.post(url, json={"version": version})
    assert exported.status_code == 200, exported.json
    assert exported.json["data"]["document_version_id"]


def test_t_p0_1_export_gate_opens_pending_signoff_when_none_exists(d4_client, db_session, d4_settings) -> None:
    """无 run 形态（包声明 agent_assisted、方案从未跑过 run → 无 handoff 可走）与存量
    形态同构：export 409 时兜底开出 pending（handoff_run_id=None）并在 details 指路；
    重复导出不重复开闸；approved 后闸开（落下一道业务校验）。闸本身不放宽。"""
    leader = api_client(d4_client, db_session, d4_settings, "project_lead")
    project = _persist_project(db_session, leader.user, code=f"SG{uuid4().hex[:4]}")
    solution = _solution(db_session, project, leader.user)
    _package(db_session, project, solution, agent_assisted=True)
    url = f"/api/v1/projects/{project.id}/solutions/{solution.id}/export-sow"
    blocked = leader.post(url, json={"version": 1})
    assert blocked.status_code == 409, blocked.json
    assert blocked.json["error"]["code"] == "solution_signoff_required"
    checkpoint_id = blocked.json["error"]["details"]["signoff_checkpoint_id"]
    checkpoint = db_session.get(SolutionReviewCheckpoint, checkpoint_id)
    assert checkpoint.solution_id == solution.id and checkpoint.status == "pending"
    assert checkpoint.handoff_run_id is None and checkpoint.required_level == "project_manager"
    again = leader.post(url, json={"version": 1})
    assert again.status_code == 409
    assert again.json["error"]["details"]["signoff_checkpoint_id"] == checkpoint_id
    assert len(_checkpoints(db_session, solution)) == 1
    assert _signoff(leader, project, solution, {"decision": "approved"}).status_code == 200
    opened = leader.post(url, json={"version": 1})
    assert opened.status_code == 400, opened.json
    assert opened.json["error"]["code"] == "solution_design_required"


def test_t_p0_1_export_after_rejection_reopens_pending(d4_client, db_session, d4_settings) -> None:
    """驳回后再导出：无 approved 也无 pending → 兜底开出新一轮 pending（不复用
    rejected 行），方案留痕 rejected + pending 两行；拍板 attempt 口径随之为 2。"""
    leader = api_client(d4_client, db_session, d4_settings, "project_lead")
    project = _persist_project(db_session, leader.user, code=f"SG{uuid4().hex[:4]}")
    solution = _solution(db_session, project, leader.user)
    _package(db_session, project, solution, agent_assisted=True)
    first = _checkpoint(db_session, solution)
    assert _signoff(leader, project, solution, {"decision": "rejected"}).status_code == 200
    url = f"/api/v1/projects/{project.id}/solutions/{solution.id}/export-sow"
    blocked = leader.post(url, json={"version": 1})
    assert blocked.status_code == 409, blocked.json
    reopened_id = blocked.json["error"]["details"]["signoff_checkpoint_id"]
    assert reopened_id != first.id
    db_session.expire_all()  # first 在测试会话里仍是 pending 快照，拍板发生在服务端会话
    assert sorted(row.status for row in _checkpoints(db_session, solution)) == ["pending", "rejected"]
    approved = _signoff(leader, project, solution, {"decision": "approved"})
    assert approved.status_code == 200, approved.json
    assert approved.json["data"]["checkpoint_id"] == reopened_id
    events = db_session.query(OperationEvent).filter(
        OperationEvent.event_type == "solution_signoff_resolved",
        OperationEvent.project_id == project.id,
    ).order_by(OperationEvent.created_at.asc(), OperationEvent.id.asc()).all()
    assert [row.changes["attempt"] for row in events] == [1, 2]


def test_t_p0_1_l1_degraded_completed_does_not_auto_open_signoff(db_session, d4_client, d4_app, d4_settings) -> None:
    """L1（降级 completed）产物不进终审通道，_finalize 不开闸——仍由人工接管
    handoff 开出 pending（既有语义零回归），且接管后同方案仍只有一个 checkpoint。"""
    leader, project, solution, agent = _project_with_solution(db_session, d4_client, d4_settings)  # 工具面只有 read_file
    _seal_t2(leader, project, solution.id)
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
    assert run["status"] == "completed" and run["fallback_level"] == "L1"
    assert _checkpoints(db_session, solution) == []
    handed = leader.post(f"/api/v1/agents/runs/{run['id']}/handoff", json={"solution_id": solution.id})
    assert handed.status_code == 200, handed.json
    rows = _checkpoints(db_session, solution)
    assert len(rows) == 1 and rows[0].id == handed.json["data"]["signoff_checkpoint_id"]
    assert rows[0].status == "pending" and rows[0].handoff_run_id == run["id"]


def test_ensure_pending_signoff_idempotent_and_backfills_run_link(d4_client, db_session, d4_settings) -> None:
    """统一开闸入口：同方案至多一个 pending；已有 pending 只补空的 run 软链、不覆写；
    approved/rejected 不算 pending（新一轮可再开）。"""
    from fde_api.agents.signoff import ensure_pending_signoff  # 局部导入：本文件其余用例可对旧代码先红

    leader = api_client(d4_client, db_session, d4_settings, "project_lead")
    project = _persist_project(db_session, leader.user, code=f"SG{uuid4().hex[:4]}")
    solution = _solution(db_session, project, leader.user)
    first = ensure_pending_signoff(db_session, solution_id=solution.id, run_id=None)
    db_session.commit()
    assert first.status == "pending" and first.handoff_run_id is None
    second = ensure_pending_signoff(db_session, solution_id=solution.id, run_id="run-a")
    db_session.commit()
    assert second.id == first.id and second.handoff_run_id == "run-a"
    third = ensure_pending_signoff(db_session, solution_id=solution.id, run_id="run-b")
    db_session.commit()
    assert third.id == first.id and third.handoff_run_id == "run-a"  # 不覆写既有软链
    assert len(_checkpoints(db_session, solution)) == 1
    first.status = "approved"
    db_session.commit()
    fourth = ensure_pending_signoff(db_session, solution_id=solution.id, run_id=None)
    db_session.commit()
    assert fourth.id != first.id
    assert len(_checkpoints(db_session, solution)) == 2
