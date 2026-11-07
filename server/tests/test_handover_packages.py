"""T-B1 封包半（goal-tb tb4）：结项交付包 handover_packages。

验收面（backlog 登记原文 + D11 草案）：
- 一次 run 的产物可封包为 handover_packages 且逐项 sha256 可校验；原件不进库
  （items=指针+快照，零外键指向 agent_artifacts——metadata 扫描钉死）；
- seal 冻结清单 + manifest 规范化哈希；sealed 编辑 409；unseal 仅 sealed→draft；
- delivered（admin 专属）终态不可逆；
- 封包仅接受已人工复核产物（与 D11 草案 status 闸同构）；跨项目产物拒绝。
"""
from __future__ import annotations

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

from fde_api.agents.models import AgentArtifact, AgentRun
from fde_api.auth.models import Base
from fde_api.handover.models import HandoverPackage, HandoverPackageItem
from fde_api.workbench.models import OperationEvent, ProjectMember


def _member_client(db_session, d4_client, d4_settings, project, role: str = "fde_engineer") -> tuple[ApiClient, object]:
    user = make_user(db_session, role)
    db_session.add(ProjectMember(project_id=project.id, user_id=user.id, role="member"))
    db_session.commit()
    return ApiClient(d4_client, user, {"Authorization": f"Bearer {issue_access_token(user, d4_settings)}"}), user


def _seed_reviewed_artifact(db_session, project, user, agent_id: str, *, reviewed: bool = True) -> AgentArtifact:
    run = AgentRun(
        project_id=project.id,
        agent_id=agent_id,
        initiated_by_user_id=user.id,
        capability_used="agent.code.write",
        status="completed",
        context_ref="agent-workspaces/x/context.md",
        token_cost=10,
        idempotency_key=f"tb4:{uuid4().hex}",
    )
    db_session.add(run)
    db_session.flush()
    artifact = AgentArtifact(
        run_id=run.id,
        kind="diff",
        storage_ref=f"{run.id}/output/change.diff",
        sha256=("b" * 63) + ("c" if not reviewed else "d"),
        reviewed=reviewed,
        reviewed_by_user_id=user.id if reviewed else None,
    )
    db_session.add(artifact)
    db_session.commit()
    return artifact


def _make_admin_client(db_session, d4_client, d4_settings) -> ApiClient:
    user = make_user(db_session, "admin")
    return ApiClient(d4_client, user, {"Authorization": f"Bearer {issue_access_token(user, d4_settings)}"})


def _create_package(client: ApiClient, project, artifact_ids: list[str], *, label: str = "结项交付包") -> dict:
    response = client.post(
        "/api/v1/handover-packages",
        json={"project_id": project.id, "label": label, "items": [{"artifact_id": aid} for aid in artifact_ids]},
    )
    assert response.status_code == 201, response.get_json()
    return response.get_json()["data"]


def test_create_draft_snapshots_and_seal_freezes(db_session, d4_client, d4_settings) -> None:
    """草稿快照指针+指纹 → seal 冻结+manifest 规范化哈希+事件；sealed 拒编辑。"""
    leader = api_client(d4_client, db_session, d4_settings, "project_lead")
    project = _persist_project(db_session, leader.user, code=f"TB4A{uuid4().hex[:4]}")
    agent = seed_agent(db_session, d4_settings)
    member, _user = _member_client(db_session, d4_client, d4_settings, project)
    artifact = _seed_reviewed_artifact(db_session, project, member.user, agent.id)

    package = _create_package(leader, project, [artifact.id])
    assert package["status"] == "draft"
    assert package["items"][0]["sha256"] == artifact.sha256
    assert package["items"][0]["storage_ref"] == artifact.storage_ref

    sealed = leader.post(f"/api/v1/handover-packages/{package['id']}/seal")
    assert sealed.status_code == 200, sealed.get_json()
    body = sealed.get_json()["data"]
    assert body["status"] == "sealed"
    manifest = body["manifest"]
    assert manifest["items"][0]["artifact_id"] == artifact.id
    import hashlib
    import json as jsonlib

    expected = hashlib.sha256(
        jsonlib.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    assert body["manifest_sha256"] == expected, "manifest_sha256 = 清单规范化 JSON 哈希（可复算）"
    event = db_session.query(OperationEvent).filter_by(event_type="handover_package_sealed").one()
    assert event.changes["package_id"] == package["id"]

    # sealed 冻结：编辑与重复封存均 409
    patch = leader.patch(
        f"/api/v1/handover-packages/{package['id']}",
        json={"items": [{"artifact_id": artifact.id}]},
    )
    assert patch.status_code == 409
    reseal = leader.post(f"/api/v1/handover-packages/{package['id']}/seal")
    assert reseal.status_code == 409


def test_unseal_returns_to_draft_with_trace(db_session, d4_client, d4_settings) -> None:
    leader = api_client(d4_client, db_session, d4_settings, "project_lead")
    project = _persist_project(db_session, leader.user, code=f"TB4B{uuid4().hex[:4]}")
    agent = seed_agent(db_session, d4_settings)
    member, _user = _member_client(db_session, d4_client, d4_settings, project)
    artifact = _seed_reviewed_artifact(db_session, project, member.user, agent.id)
    package = _create_package(leader, project, [artifact.id])
    assert leader.post(f"/api/v1/handover-packages/{package['id']}/seal").status_code == 200

    unsealed = leader.post(f"/api/v1/handover-packages/{package['id']}/unseal")
    assert unsealed.status_code == 200
    body = unsealed.get_json()["data"]
    assert body["status"] == "draft"
    assert body["unsealed_count"] == 1
    assert "manifest_sha256" not in body, "草稿无 manifest（封存三痕已清）"
    # 解封后可再编辑再封存
    redraft = leader.patch(
        f"/api/v1/handover-packages/{package['id']}",
        json={"label": "结项交付包 v2"},
    )
    assert redraft.status_code == 200
    assert redraft.get_json()["data"]["label"] == "结项交付包 v2"


def test_seal_gates_reviewed_and_foreign_and_empty(db_session, d4_client, d4_settings) -> None:
    """封包三闸：未复核产物 409 / 跨项目产物 409 / 空清单 422。"""
    leader = api_client(d4_client, db_session, d4_settings, "project_lead")
    project = _persist_project(db_session, leader.user, code=f"TB4C{uuid4().hex[:4]}")
    other = _persist_project(db_session, leader.user, code=f"TB4D{uuid4().hex[:4]}")
    agent = seed_agent(db_session, d4_settings)
    member, _user = _member_client(db_session, d4_client, d4_settings, project)
    other_member, _u2 = _member_client(db_session, d4_client, d4_settings, other)
    unreviewed = _seed_reviewed_artifact(db_session, project, member.user, agent.id, reviewed=False)
    foreign = _seed_reviewed_artifact(db_session, other, other_member.user, agent.id)

    # 未复核 → 409
    pkg_unreviewed = _create_package(leader, project, [unreviewed.id])
    sealed = leader.post(f"/api/v1/handover-packages/{pkg_unreviewed['id']}/seal")
    assert sealed.status_code == 409
    assert sealed.get_json()["error"]["code"] == "artifact_not_reviewed"

    # 跨项目产物 → 409（创建时即拒）
    foreign = leader.post(
        "/api/v1/handover-packages",
        json={"project_id": project.id, "items": [{"artifact_id": foreign.id}]},
    )
    assert foreign.status_code == 409
    assert foreign.get_json()["error"]["code"] == "artifact_foreign_project"

    # 空清单创建 → 422
    empty = leader.post("/api/v1/handover-packages", json={"project_id": project.id, "items": []})
    assert empty.status_code == 422


def test_fingerprint_drift_rejected_at_seal(db_session, d4_client, d4_settings) -> None:
    """清单快照指纹与产物现行指纹不一致 → 409 fingerprint_drift（逐项 sha256 可校验的负例）。"""
    leader = api_client(d4_client, db_session, d4_settings, "project_lead")
    project = _persist_project(db_session, leader.user, code=f"TB4E{uuid4().hex[:4]}")
    agent = seed_agent(db_session, d4_settings)
    member, _user = _member_client(db_session, d4_client, d4_settings, project)
    artifact = _seed_reviewed_artifact(db_session, project, member.user, agent.id)
    package = _create_package(leader, project, [artifact.id])
    # 直接改产物行指纹模拟封包窗口内的漂移（快照已冻结旧值）
    artifact.sha256 = "f" * 64
    db_session.commit()
    sealed = leader.post(f"/api/v1/handover-packages/{package['id']}/seal")
    assert sealed.status_code == 409
    assert sealed.get_json()["error"]["code"] == "fingerprint_drift"


def test_deliver_admin_only_and_irreversible(db_session, d4_client, d4_settings) -> None:
    """交付登记=admin 专属（D11 草案权限）；delivered 终态不可逆。"""
    leader = api_client(d4_client, db_session, d4_settings, "project_lead")
    project = _persist_project(db_session, leader.user, code=f"TB4F{uuid4().hex[:4]}")
    agent = seed_agent(db_session, d4_settings)
    member, _user = _member_client(db_session, d4_client, d4_settings, project)
    admin = _make_admin_client(db_session, d4_client, d4_settings)
    artifact = _seed_reviewed_artifact(db_session, project, member.user, agent.id)
    package = _create_package(leader, project, [artifact.id])

    # 未封存不可交付；负责人（非 admin）不可交付
    draft_deliver = admin.post(f"/api/v1/handover-packages/{package['id']}/deliver")
    assert draft_deliver.status_code == 409
    manager_deliver = leader.post(f"/api/v1/handover-packages/{package['id']}/deliver")
    assert manager_deliver.status_code == 403
    assert manager_deliver.get_json()["error"]["code"] == "admin_required"

    assert leader.post(f"/api/v1/handover-packages/{package['id']}/seal").status_code == 200
    delivered = admin.post(f"/api/v1/handover-packages/{package['id']}/deliver")
    assert delivered.status_code == 200
    body = delivered.get_json()["data"]
    assert body["status"] == "delivered"
    assert body["delivered_at"] is not None

    # 终态不可逆：再交付/解封/编辑均 409
    assert admin.post(f"/api/v1/handover-packages/{package['id']}/deliver").status_code == 409
    assert leader.post(f"/api/v1/handover-packages/{package['id']}/unseal").status_code == 409
    assert leader.patch(f"/api/v1/handover-packages/{package['id']}", json={"label": "x"}).status_code == 409


def test_read_faces_permissions_and_isolation_pin(db_session, d4_client, d4_settings) -> None:
    """查看=成员（外人 403/未知 404/未认证 401）；挑选面只回已复核产物；零外键指向 agent_artifacts。"""
    leader = api_client(d4_client, db_session, d4_settings, "project_lead")
    project = _persist_project(db_session, leader.user, code=f"TB4G{uuid4().hex[:4]}")
    other = _persist_project(db_session, leader.user, code=f"TB4H{uuid4().hex[:4]}")
    agent = seed_agent(db_session, d4_settings)
    member, _user = _member_client(db_session, d4_client, d4_settings, project)
    reviewed = _seed_reviewed_artifact(db_session, project, member.user, agent.id)
    _seed_reviewed_artifact(db_session, project, member.user, agent.id, reviewed=False)
    _create_package(leader, project, [reviewed.id])

    listing = member.get(f"/api/v1/handover-packages?project_id={project.id}")
    assert listing.status_code == 200
    assert len(listing.get_json()["data"]["items"]) == 1
    assert "items" not in listing.get_json()["data"]["items"][0], "列表行不带清单（详情按需取）"

    outsider, _o = _member_client(db_session, d4_client, d4_settings, other)
    assert outsider.get(f"/api/v1/handover-packages?project_id={project.id}").status_code == 403
    assert member.get("/api/v1/handover-packages/missing-package").status_code == 404
    assert d4_client.get(f"/api/v1/handover-packages?project_id={project.id}").status_code == 401

    picker = member.get(f"/api/v1/handover-packages/artifacts?project_id={project.id}")
    assert picker.status_code == 200
    rows = picker.get_json()["data"]["items"]
    assert len(rows) == 1 and rows[0]["artifact_id"] == reviewed.id, "挑选面只回已复核产物"

    # B#6 隔离钉：handover 两表零外键指向 agent_artifacts（items=纯指针+快照）
    refs = [
        constraint.referred_table
        for table in Base.metadata.tables.values()
        if table.name.startswith("handover")
        for constraint in table.foreign_key_constraints
    ]
    assert "agent_artifacts" not in refs
    package_row = db_session.query(HandoverPackage).one()
    assert db_session.query(HandoverPackageItem).filter_by(package_id=package_row.id).count() == 1
