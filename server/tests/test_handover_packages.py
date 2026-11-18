"""T-B1 封包半（goal-tb tb4）：结项交付包 handover_packages。

验收面（backlog 登记原文 + D11 草案）：
- 一次 run 的产物可封包为 handover_packages 且逐项 sha256 可校验；原件不进库
  （items=指针+快照，零外键指向 agent_artifacts——metadata 扫描钉死）；
- seal 冻结清单 + manifest 规范化哈希；sealed 编辑 409；unseal 仅 sealed→draft；
- delivered（admin 专属）终态不可逆；
- 封包仅接受已人工复核产物（与 D11 草案 status 闸同构）；跨项目产物拒绝；
- item_type 三态（SME 交付尾巴轮）：document=confirmed 文档版本 / file=
  available 文件版本（状态闸与 reviewed 同构；跨项目同拒；指纹漂移同拒）。
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from threading import Event
from time import monotonic, sleep
from uuid import uuid4

import pytest
from sqlalchemy import text

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
from fde_api.documents.models import (
    DocumentTemplate,
    DocumentTemplateVersion,
    ProjectDocument,
    ProjectDocumentVersion,
)
from fde_api.files.models import ProjectFile, ProjectFileVersion
from fde_api.handover import service as handover_service
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


def _delivery_conditions(snapshot: dict) -> dict:
    return {
        "expected_manifest_sha256": snapshot["manifest_sha256"],
        "expected_unsealed_count": snapshot["unsealed_count"],
    }


@pytest.fixture
def delivery_case(db_session, d4_client, d4_settings):
    leader = api_client(d4_client, db_session, d4_settings, "project_lead")
    project = _persist_project(db_session, leader.user, code=f"G3{uuid4().hex[:8]}")
    agent = seed_agent(db_session, d4_settings)
    artifact = _seed_reviewed_artifact(db_session, project, leader.user, agent.id)
    package = _create_package(leader, project, [artifact.id])
    return leader, _make_admin_client(db_session, d4_client, d4_settings), f"/api/v1/handover-packages/{package['id']}"


def test_reseal_same_digest_invalidates_old_confirmation(delivery_case, db_session, monkeypatch) -> None:
    leader, admin, path = delivery_case
    frozen = datetime.now(UTC)

    class FrozenDateTime:
        @staticmethod
        def now(_tz):
            return frozen

    monkeypatch.setattr(handover_service, "datetime", FrozenDateTime)
    first = leader.post(f"{path}/seal").get_json()["data"]
    assert leader.post(f"{path}/unseal").status_code == 200
    second = leader.post(f"{path}/seal").get_json()["data"]
    assert first["manifest_sha256"] == second["manifest_sha256"]
    assert second["unsealed_count"] == first["unsealed_count"] + 1
    for conditions in (_delivery_conditions(first), {**_delivery_conditions(second), "expected_manifest_sha256": "0" * 64}):
        stale = admin.post(f"{path}/deliver", json=conditions)
        assert stale.status_code == 409
        assert stale.get_json()["error"]["code"] == "handover_snapshot_conflict"
    assert admin.get(path).get_json()["data"] == second
    assert db_session.query(OperationEvent).filter_by(event_type="handover_package_delivered").count() == 0
    assert admin.post(f"{path}/deliver", json=_delivery_conditions(second)).status_code == 200
    event = db_session.query(OperationEvent).filter_by(event_type="handover_package_delivered").one()
    assert event.changes["manifest_sha256"] == second["manifest_sha256"]
    assert event.changes["unsealed_count"] == second["unsealed_count"]


def test_compatibility_only_allows_absent_conditions(delivery_case, d4_app, monkeypatch) -> None:
    leader, admin, path = delivery_case
    monkeypatch.setattr(d4_app.config["SETTINGS"], "ux_write_preconditions_required", False)
    sealed = leader.post(f"{path}/seal").get_json()["data"]
    assert admin.get(path).get_json()["data"]["write_preconditions"] == "v1"
    assert admin.post(f"{path}/deliver", json={"expected_unsealed_count": 0}).status_code == 422
    assert admin.post(f"{path}/deliver", data="null", content_type="application/json").status_code == 400
    assert admin.post(f"{path}/deliver", json={**_delivery_conditions(sealed), "expected_unsealed_count": 1}).status_code == 409
    assert admin.post(f"{path}/deliver").status_code == 200


def test_compatibility_records_a_trace_when_conditions_are_absent(
    delivery_case, d4_app, db_session, monkeypatch
) -> None:
    """兼容期放行必须留痕：否则该终态与「确认过」在审计里不可区分。"""
    leader, admin, path = delivery_case
    monkeypatch.setattr(d4_app.config["SETTINGS"], "ux_write_preconditions_required", False)
    package_id = path.rsplit("/", 1)[-1]
    leader.post(f"{path}/seal")
    assert admin.post(f"{path}/deliver").status_code == 200
    skipped = db_session.query(OperationEvent).filter_by(event_type="handover_precondition_skipped").one()
    assert skipped.changes["package_id"] == package_id
    assert db_session.query(OperationEvent).filter_by(event_type="handover_package_delivered").count() == 1


def test_strict_mode_records_no_skipped_precondition(delivery_case, db_session) -> None:
    """严格模式（默认）登记带条件，不得出现放行留痕。"""
    leader, admin, path = delivery_case
    sealed = leader.post(f"{path}/seal").get_json()["data"]
    assert admin.post(f"{path}/deliver", json=_delivery_conditions(sealed)).status_code == 200
    assert db_session.query(OperationEvent).filter_by(event_type="handover_precondition_skipped").count() == 0


def test_delivery_is_paused_and_writes_no_terminal_state(
    delivery_case, d4_app, db_session, monkeypatch
) -> None:
    """发布回退窗口：登记被拒，包仍封存、无成功事件、无放行留痕。"""
    leader, admin, path = delivery_case
    sealed = leader.post(f"{path}/seal").get_json()["data"]
    monkeypatch.setattr(d4_app.config["SETTINGS"], "ux_write_paused", True)
    response = admin.post(f"{path}/deliver", json=_delivery_conditions(sealed))
    assert response.status_code == 503
    assert response.get_json()["error"]["code"] == "write_preconditions_paused"
    assert admin.get(path).get_json()["data"]["status"] == "sealed"
    assert db_session.query(OperationEvent).filter_by(event_type="handover_package_delivered").count() == 0
    assert db_session.query(OperationEvent).filter_by(event_type="handover_precondition_skipped").count() == 0


def test_paused_delivery_keeps_non_admin_at_403(delivery_case, d4_app, monkeypatch) -> None:
    """暂停不得改变授权口径：非管理员仍是 403，不会因暂停得到 503。"""
    leader, _admin, path = delivery_case
    leader.post(f"{path}/seal")
    monkeypatch.setattr(d4_app.config["SETTINGS"], "ux_write_paused", True)
    assert leader.post(f"{path}/deliver").status_code == 403


@pytest.mark.parametrize(("first_action", "second_action", "error_code"), [
    ("seal", "edit", "package_not_draft"),
    ("unseal", "deliver", "package_not_sealed"),
    ("deliver", "unseal", "package_not_sealed"),
    ("deliver", "deliver", "already_delivered"),
])
def test_package_mutations_serialize_in_postgres(
    delivery_case, d4_app, db_session, monkeypatch, first_action, second_action, error_code,
) -> None:
    leader, admin, path = delivery_case
    conditions = {}
    if first_action != "seal":
        sealed = leader.post(f"{path}/seal").get_json()["data"]
        conditions = _delivery_conditions(sealed)

    entered, release = Event(), Event()
    blocker_pid: list[int] = []
    original = handover_service.record_event

    def pause_before_commit(session, actor, event_type, *args, **kwargs):
        if event_type == f"handover_package_{first_action}ed" and not blocker_pid:
            blocker_pid.append(session.scalar(text("SELECT pg_backend_pid()")))
            entered.set()
            assert release.wait(12), "first mutation was not released"
        return original(session, actor, event_type, *args, **kwargs)

    monkeypatch.setattr(handover_service, "record_event", pause_before_commit)

    def request(action, client):
        with d4_app.test_client() as http:
            if action == "edit":
                return http.patch(path, headers=client.headers, json={"label": "不应覆盖封存包"})
            return http.post(f"{path}/{action}", headers=client.headers, json=conditions)

    second_admin = admin
    if first_action == second_action == "deliver":
        second_admin = _make_admin_client(db_session, d4_app.test_client(), d4_app.config["SETTINGS"])
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(request, first_action, admin if first_action == "deliver" else leader)
        try:
            assert entered.wait(8), "first mutation did not reach the held transaction"
            second = pool.submit(request, second_action, second_admin if second_action == "deliver" else leader)
            deadline = monotonic() + 8
            # PostgreSQL confirms overlap without relying on a timing-only assertion.
            while monotonic() < deadline:
                db_session.commit()  # pg_stat_activity is cached until observer transaction ends
                if db_session.scalar(text("""
                    SELECT EXISTS (SELECT 1 FROM pg_stat_activity
                    WHERE :blocker = ANY(pg_blocking_pids(pid)))
                """), {"blocker": blocker_pid[0]}):
                    break
                assert not second.done(), "second mutation finished before first committed"
                sleep(0.02)
            else:
                pytest.fail("second mutation never blocked on first transaction")
        finally:
            release.set()
        assert first.result(timeout=8).status_code == 200
        rejected = second.result(timeout=8)
    assert rejected.status_code == 409
    assert rejected.get_json()["error"]["code"] == error_code
    final = admin.get(path).get_json()["data"]
    expected = {"seal": "sealed", "unseal": "draft", "deliver": "delivered"}
    assert final["status"] == expected[first_action]
    assert final["label"] == "结项交付包"
    delivered_events = db_session.query(OperationEvent).filter_by(event_type="handover_package_delivered").all()
    assert len(delivered_events) == int(first_action == "deliver")
    if delivered_events:
        assert delivered_events[0].changes["manifest_sha256"] == final["manifest_sha256"]
        assert delivered_events[0].changes["unsealed_count"] == final["unsealed_count"]


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

    path = f"/api/v1/handover-packages/{package['id']}"
    assert leader.post(f"{path}/seal").status_code == 200
    sealed = admin.get(path).get_json()["data"]
    assert sealed["write_preconditions"] == "v1"
    missing = admin.post(f"{path}/deliver")
    assert missing.status_code == 428
    assert missing.get_json()["error"]["code"] == "write_preconditions_required"
    conditions = _delivery_conditions(sealed)
    for invalid in (
        {"expected_manifest_sha256": conditions["expected_manifest_sha256"]},
        {**conditions, "expected_unsealed_count": False},
        {**conditions, "expected_unsealed_count": -1},
        {**conditions, "expected_manifest_sha256": "a" * 12},
    ):
        assert admin.post(f"{path}/deliver", json=invalid).status_code == 422
    assert db_session.query(OperationEvent).filter_by(event_type="handover_package_delivered").count() == 0
    delivered = admin.post(f"{path}/deliver", json=conditions)
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


# ---------------------------------------------------------------------------
# SME 交付尾巴轮：item_type 三态（artifact/document/file）


def _seed_available_file_version(
    db_session, project, user, *, status: str = "available", sha: str | None = None
) -> ProjectFileVersion:
    project_file = ProjectFile(
        project_id=project.id,
        category="document",
        display_name=f"交付文件-{uuid4().hex[:6]}",
        status="active",
        created_by_user_id=user.id,
    )
    db_session.add(project_file)
    db_session.flush()
    version = ProjectFileVersion(
        file_id=project_file.id,
        version_number=1,
        source="manual_upload",
        original_filename=f"deliverable-{uuid4().hex[:6]}.docx",
        safe_filename="deliverable.docx",
        extension=".docx",
        mime_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        bucket="project-files",
        storage_key=f"project-files/{project_file.id}/v1/deliverable.docx",
        size_bytes=1024,
        etag="etag",
        sha256=sha if sha is not None else ("c" * 63) + "f",
        scan_status="clean",
        preview_status="none",
        status=status,
        uploaded_by_user_id=user.id,
    )
    db_session.add(version)
    db_session.commit()
    return version


def _seed_confirmed_document_version(
    db_session, project, leader_user, *, version_status: str = "confirmed", sha: str | None = None
) -> tuple[ProjectDocument, ProjectDocumentVersion]:
    doc_template = DocumentTemplate(
        document_type=f"sow-{uuid4().hex[:8]}",
        name="sow 模板",
        description="",
        industry_name="制造",
    )
    db_session.add(doc_template)
    db_session.flush()
    template_version = DocumentTemplateVersion(
        template_id=doc_template.id,
        version_number=1,
        status="published",
        mapping_json={"document_type": "sow", "name": "sow 模板", "modules": [], "field_map": {}, "research_keys": []},
        sections_json={"sections": []},
        table_loops_json={},
        required_data_json={},
        source_sha256="",
        created_by_user_id=leader_user.id,
    )
    db_session.add(template_version)
    db_session.flush()
    document = ProjectDocument(
        project_id=project.id,
        document_type="sow",
        business_code=f"SOW-{uuid4().hex[:6].upper()}",
        source_template_version_id=template_version.id,
        status="confirmed",
        owner_user_id=leader_user.id,
    )
    db_session.add(document)
    db_session.flush()
    docx = _seed_available_file_version(db_session, project, leader_user)
    version = ProjectDocumentVersion(
        document_id=document.id,
        version_number=1,
        source="manual_upload",
        status=version_status,
        source_template_version_id=template_version.id,
        source_snapshot_json={},
        content_snapshot_json={},
        docx_file_version_id=docx.id,
        sha256=sha if sha is not None else ("d" * 63) + "e",
        generated_by_user_id=leader_user.id,
    )
    db_session.add(version)
    db_session.commit()
    return document, version


def test_document_and_file_items_end_to_end(db_session, d4_client, d4_settings) -> None:
    """三态混合清单：快照投影 / seal 过闸 / manifest 带三指针 / 挑选面三态。"""
    leader = api_client(d4_client, db_session, d4_settings, "project_lead")
    project = _persist_project(db_session, leader.user, code=f"TB4I{uuid4().hex[:4]}")
    agent = seed_agent(db_session, d4_settings)
    member, _user = _member_client(db_session, d4_client, d4_settings, project)
    artifact = _seed_reviewed_artifact(db_session, project, member.user, agent.id)
    document, doc_version = _seed_confirmed_document_version(db_session, project, leader.user)
    file_version = _seed_available_file_version(db_session, project, member.user)

    response = leader.post(
        "/api/v1/handover-packages",
        json={
            "project_id": project.id,
            "items": [
                {"artifact_id": artifact.id},
                {"document_version_id": doc_version.id},
                {"file_version_id": file_version.id, "display_name": "验收报告原件"},
            ],
        },
    )
    assert response.status_code == 201, response.get_json()
    package = response.get_json()["data"]
    by_type = {row["item_type"]: row for row in package["items"]}
    assert set(by_type) == {"artifact", "document", "file"}
    assert by_type["document"]["sha256"] == doc_version.sha256
    assert by_type["document"]["storage_ref"] == f"document-version:{doc_version.id}"
    assert by_type["document"]["display_name"] == f"{document.business_code} v{doc_version.version_number}"
    assert by_type["file"]["sha256"] == file_version.sha256
    assert by_type["file"]["display_name"] == "验收报告原件"
    assert by_type["file"]["storage_ref"] == file_version.storage_key

    sealed = leader.post(f"/api/v1/handover-packages/{package['id']}/seal")
    assert sealed.status_code == 200, sealed.get_json()
    manifest_items = sealed.get_json()["data"]["manifest"]["items"]
    assert any(row["document_version_id"] == doc_version.id for row in manifest_items)
    assert any(row["file_version_id"] == file_version.id for row in manifest_items)

    # 挑选面三态：document 回 confirmed 版本 / file 回 available 版本
    docs = leader.get(f"/api/v1/handover-packages/artifacts?project_id={project.id}&type=document")
    assert docs.status_code == 200, docs.get_json()
    assert any(row["document_version_id"] == doc_version.id for row in docs.get_json()["data"]["items"])
    files = leader.get(f"/api/v1/handover-packages/artifacts?project_id={project.id}&type=file")
    assert files.status_code == 200, files.get_json()
    assert any(row["file_version_id"] == file_version.id for row in files.get_json()["data"]["items"])
    bogus = leader.get(f"/api/v1/handover-packages/artifacts?project_id={project.id}&type=bogus")
    assert bogus.status_code == 400
    assert bogus.get_json()["error"]["code"] == "invalid_request"


def test_document_file_gates(db_session, d4_client, d4_settings) -> None:
    """document/file 入包闸：状态闸 409 / 跨项目 409 / 缺指纹 422 / 闭集与去重 422。"""
    leader = api_client(d4_client, db_session, d4_settings, "project_lead")
    project = _persist_project(db_session, leader.user, code=f"TB4J{uuid4().hex[:4]}")
    other = _persist_project(db_session, leader.user, code=f"TB4K{uuid4().hex[:4]}")
    member, _user = _member_client(db_session, d4_client, d4_settings, project)
    other_member, _u2 = _member_client(db_session, d4_client, d4_settings, other)

    _doc, draft_version = _seed_confirmed_document_version(db_session, project, leader.user, version_status="draft")
    rejected = leader.post(
        "/api/v1/handover-packages",
        json={"project_id": project.id, "items": [{"item_type": "document", "document_version_id": draft_version.id}]},
    )
    assert rejected.status_code == 409
    assert rejected.get_json()["error"]["code"] == "document_not_confirmed"

    _foreign_doc, foreign_version = _seed_confirmed_document_version(db_session, other, leader.user)
    foreign = leader.post(
        "/api/v1/handover-packages",
        json={"project_id": project.id, "items": [{"item_type": "document", "document_version_id": foreign_version.id}]},
    )
    assert foreign.status_code == 409
    assert foreign.get_json()["error"]["code"] == "document_foreign_project"

    _no_sha_doc, no_sha_version = _seed_confirmed_document_version(db_session, project, leader.user, sha="")
    no_sha = leader.post(
        "/api/v1/handover-packages",
        json={"project_id": project.id, "items": [{"item_type": "document", "document_version_id": no_sha_version.id}]},
    )
    assert no_sha.status_code == 422
    assert no_sha.get_json()["error"]["code"] == "document_fingerprint_missing"

    deprecated_file = _seed_available_file_version(db_session, project, member.user, status="deprecated")
    file_gate = leader.post(
        "/api/v1/handover-packages",
        json={"project_id": project.id, "items": [{"item_type": "file", "file_version_id": deprecated_file.id}]},
    )
    assert file_gate.status_code == 409
    assert file_gate.get_json()["error"]["code"] == "file_not_available"

    foreign_file = _seed_available_file_version(db_session, other, other_member.user)
    file_foreign = leader.post(
        "/api/v1/handover-packages",
        json={"project_id": project.id, "items": [{"item_type": "file", "file_version_id": foreign_file.id}]},
    )
    assert file_foreign.status_code == 409
    assert file_foreign.get_json()["error"]["code"] == "file_foreign_project"

    bogus = leader.post(
        "/api/v1/handover-packages",
        json={"project_id": project.id, "items": [{"item_type": "bogus", "artifact_id": "x"}]},
    )
    assert bogus.status_code == 422
    dup_source = _seed_available_file_version(db_session, project, member.user)
    duplicate = leader.post(
        "/api/v1/handover-packages",
        json={
            "project_id": project.id,
            "items": [
                {"item_type": "file", "file_version_id": dup_source.id},
                {"item_type": "file", "file_version_id": dup_source.id},
            ],
        },
    )
    assert duplicate.status_code == 422


def test_file_fingerprint_drift_rejected_at_seal(db_session, d4_client, d4_settings) -> None:
    """file 指纹漂移：封包窗口内文件版本指纹变化 → 409 fingerprint_drift。"""
    leader = api_client(d4_client, db_session, d4_settings, "project_lead")
    project = _persist_project(db_session, leader.user, code=f"TB4L{uuid4().hex[:4]}")
    member, _user = _member_client(db_session, d4_client, d4_settings, project)
    file_version = _seed_available_file_version(db_session, project, member.user)
    package = leader.post(
        "/api/v1/handover-packages",
        json={"project_id": project.id, "items": [{"item_type": "file", "file_version_id": file_version.id}]},
    ).get_json()["data"]
    file_version.sha256 = "f" * 64
    db_session.commit()
    sealed = leader.post(f"/api/v1/handover-packages/{package['id']}/seal")
    assert sealed.status_code == 409
    assert sealed.get_json()["error"]["code"] == "fingerprint_drift"
