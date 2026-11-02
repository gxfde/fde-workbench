"""V3 T-E1：一等证据登记簿 project_evidence（设计 ontology-registry-v1 §2.1/§4/§5.5）。

- 同 (project, source_uri, sha256) 指纹幂等：二次 POST 200 created=false 同 id，
  且不改写 origin/captured_from（证据不可变）；kind 不参与指纹。
- 校验：kind 枚举 / sha256 64hex（invalid_sha256，大写归一小写）/ captured_from
  通道前缀 / 多余字段。
- 权限：can_manage 写、can_view 读——viewer 成员 POST 403 GET 200；外人 GET 403；
  项目不存在 404；跨项目互不可见。
- 查询：?kind= 按种类；?referenced_by=gate:Gx 反查门禁清单项挂接（T-E2 唯一引用方）。
- 红线钉子：登记路径不进 api_catalog（AI 不可写证据，与 signoff 同纪律）。
"""
from __future__ import annotations

import hashlib
from uuid import uuid4

from sqlalchemy import select

from test_document_drafts_api import _persist_project
from test_gates_api import AuthorizedClient, _submit_all_evidence, admin_client, gate_project  # noqa: F401  (pytest fixture)

from conftest import INITIAL_PASSWORD
from fde_api.auth.models import User
from fde_api.auth.passwords import hash_password
from fde_api.auth.tokens import issue_access_token
from fde_api.control.api_catalog import CATALOG
from fde_api.evidence.models import ProjectEvidence
from fde_api.evidence.service import upsert_evidence
from fde_api.workbench.models import OperationEvent, ProjectMember


def _sha(seed: str) -> str:
    return hashlib.sha256(seed.encode()).hexdigest()


def _user_client(client, db_session, settings, *, role: str) -> AuthorizedClient:
    user = User(
        username=f"evidence.{role}.{uuid4().hex[:8]}",
        display_name=f"Evidence {role}",
        role=role,
        password_hash=hash_password(INITIAL_PASSWORD),
        must_change_password=False,
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()
    return AuthorizedClient(
        client, user, {"Authorization": f"Bearer {issue_access_token(user, settings)}"}
    )


def _evidence_rows(db_session, project_id: str) -> list[ProjectEvidence]:
    return list(
        db_session.scalars(
            select(ProjectEvidence)
            .where(ProjectEvidence.project_id == project_id)
            .order_by(ProjectEvidence.created_at.asc(), ProjectEvidence.id.asc())
        )
    )


def test_register_is_idempotent_on_fingerprint(admin_client, gate_project, db_session) -> None:
    project, _gates_url, _leader = gate_project
    url = f"/api/v1/projects/{project['id']}/evidence"
    payload = {
        "kind": "gate",
        "source_uri": "fdeops://somwyn/.fde/gates/G5-客户成功案例.md",
        "content_sha256": _sha("case-a"),
        "origin": "G5 清单项 A（首版）",
        "captured_from": "human",
    }
    first = admin_client.post(url, json=payload)
    assert first.status_code == 201, first.get_data(as_text=True)
    assert first.json["data"]["created"] is True
    evidence = first.json["data"]["evidence"]
    assert evidence["project_id"] == project["id"] and evidence["kind"] == "gate"
    assert evidence["content_sha256"] == _sha("case-a")
    assert evidence["created_by_user_id"] == admin_client.user.id
    assert evidence["captured_from"] == "human" and evidence["created_at"]

    # 同指纹二次登记：幂等且不可变（origin 换了也不改写）
    again = admin_client.post(url, json={**payload, "origin": "试图改写出处"})
    assert again.status_code == 200, again.get_data(as_text=True)
    assert again.json["data"]["created"] is False
    assert again.json["data"]["evidence"]["id"] == evidence["id"]
    assert again.json["data"]["evidence"]["origin"] == "G5 清单项 A（首版）"

    # 同 uri 不同指纹 = 新证据（文件改了就是新证据，历史指针不覆写）
    other = admin_client.post(url, json={**payload, "content_sha256": _sha("case-a-v2")})
    assert other.status_code == 201 and other.json["data"]["evidence"]["id"] != evidence["id"]

    listed = admin_client.get(url)
    assert listed.status_code == 200
    assert [item["id"] for item in listed.json["data"]["items"]] == [
        evidence["id"], other.json["data"]["evidence"]["id"]
    ]
    registered = db_session.scalars(
        select(OperationEvent).where(
            OperationEvent.project_id == project["id"],
            OperationEvent.event_type == "evidence_registered",
        )
    ).all()
    assert len(registered) == 2  # 幂等命中不重复记事件
    assert {row.changes["evidence_id"] for row in registered} == {
        evidence["id"], other.json["data"]["evidence"]["id"]
    }


def test_register_validation(admin_client, gate_project) -> None:
    project, _gates_url, _leader = gate_project
    url = f"/api/v1/projects/{project['id']}/evidence"
    base = {"kind": "task", "source_uri": "fdeops://x/task.md", "content_sha256": _sha("t")}

    bad_sha = admin_client.post(url, json={**base, "content_sha256": "abc123"})
    assert bad_sha.status_code == 400 and bad_sha.json["error"]["code"] == "invalid_sha256"
    upper = admin_client.post(url, json={**base, "content_sha256": _sha("t").upper()})
    assert upper.status_code == 201 and upper.json["data"]["evidence"]["content_sha256"] == _sha("t")

    assert admin_client.post(url, json={**base, "kind": "nope"}).status_code == 400
    assert admin_client.post(url, json={**base, "captured_from": "robot"}).status_code == 400
    assert admin_client.post(url, json={**base, "captured_from": "agent_run:"}).status_code == 400
    assert admin_client.post(url, json={**base, "extra": 1}).status_code == 400
    assert admin_client.post(url, json={"kind": "task", "content_sha256": _sha("t")}).status_code == 400
    assert admin_client.post(url, json={**base, "source_uri": "x" * 501}).status_code == 400
    assert admin_client.post(url, json={**base, "origin": "o" * 2001}).status_code == 400
    assert admin_client.post(url, data="[]", content_type="application/json").status_code == 400

    channel = admin_client.post(
        url, json={**base, "content_sha256": _sha("bridge"), "captured_from": "bridge_sync:run-1"}
    )
    assert channel.status_code == 201
    assert channel.json["data"]["evidence"]["captured_from"] == "bridge_sync:run-1"


def test_permissions_and_cross_project_isolation(client, db_session, settings, admin_client, gate_project) -> None:
    project, _gates_url, leader_client = gate_project
    url = f"/api/v1/projects/{project['id']}/evidence"
    payload = {"kind": "research", "source_uri": "fdeops://iso/a.md", "content_sha256": _sha("iso-a")}
    assert leader_client.post(url, json=payload).status_code == 201  # 项目 leader = can_manage

    viewer = _user_client(client, db_session, settings, role="fde_engineer")
    db_session.add(ProjectMember(project_id=project["id"], user_id=viewer.user.id, role="viewer"))
    db_session.commit()
    denied = viewer.post(url, json={**payload, "content_sha256": _sha("iso-b")})
    assert denied.status_code == 403 and denied.json["error"]["code"] == "forbidden"
    assert viewer.get(url).status_code == 200  # can_view 可读

    outsider = _user_client(client, db_session, settings, role="project_lead")
    assert outsider.get(url).status_code == 403
    assert outsider.post(url, json=payload).status_code == 403
    assert admin_client.get("/api/v1/projects/nope/evidence").status_code == 404
    assert client.get(url).status_code == 401

    # 跨项目：另一个项目的证据互不可见（同指纹在另一项目是另一行）
    other_project = _persist_project(db_session, outsider.user, code=f"EV{uuid4().hex[:4]}")
    other_url = f"/api/v1/projects/{other_project.id}/evidence"
    mirrored = outsider.post(other_url, json=payload)
    assert mirrored.status_code == 201
    assert {item["id"] for item in admin_client.get(url).json["data"]["items"]} != {
        mirrored.json["data"]["evidence"]["id"]
    }
    assert [item["source_uri"] for item in outsider.get(other_url).json["data"]["items"]] == ["fdeops://iso/a.md"]
    assert len(_evidence_rows(db_session, project["id"])) == 1


def test_filters_kind_and_referenced_by_gate(admin_client, gate_project, db_session) -> None:
    """?referenced_by=gate:Gx 只返回该门清单项挂接的证据（T-E2）；?kind= 按种类。"""
    project, gates_url, _leader = gate_project
    url = f"/api/v1/projects/{project['id']}/evidence"
    standalone = admin_client.post(
        url, json={"kind": "task", "source_uri": "fdeops://t/1.md", "content_sha256": _sha("task-1")}
    )
    assert standalone.status_code == 201
    _submit_all_evidence(admin_client, gates_url, "G1")
    g1 = next(
        g for g in admin_client.get(gates_url).json["data"]["gates"] if g["gate_key"] == "G1"
    )
    linked_ids = {item["evidence_id"] for item in g1["checklist"]}
    assert linked_ids and None not in linked_ids

    by_gate = admin_client.get(f"{url}?referenced_by=gate:G1").json["data"]["items"]
    assert {item["id"] for item in by_gate} == linked_ids
    assert {item["kind"] for item in by_gate} == {"gate"}
    assert admin_client.get(f"{url}?referenced_by=gate:G2").json["data"]["items"] == []
    assert admin_client.get(f"{url}?referenced_by=task:1").status_code == 400
    assert admin_client.get(f"{url}?kind=nope").status_code == 400

    tasks = admin_client.get(f"{url}?kind=task").json["data"]["items"]
    assert [item["id"] for item in tasks] == [standalone.json["data"]["evidence"]["id"]]
    everything = admin_client.get(url).json["data"]["items"]
    assert len(everything) == len(linked_ids) + 1


def test_upsert_evidence_fingerprint_ignores_kind_and_is_immutable(db_session, gate_project) -> None:
    """服务层入口：指纹 = (project, uri, sha)，kind/origin 不参与；命中即原样返回。"""
    project, _gates_url, _leader = gate_project
    first, created = upsert_evidence(
        db_session, project_id=project["id"], kind="gate",
        source_uri="fdeops://u/x.md", content_sha256=_sha("x"), origin="第一次出处",
    )
    db_session.commit()
    assert created is True and first.id
    second, created_again = upsert_evidence(
        db_session, project_id=project["id"], kind="task",
        source_uri="fdeops://u/x.md", content_sha256=_sha("x"), origin="第二次出处",
        captured_from="job:1",
    )
    db_session.commit()
    assert created_again is False and second.id == first.id
    assert second.kind == "gate" and second.origin == "第一次出处" and second.captured_from == "human"
    assert len(_evidence_rows(db_session, project["id"])) == 1


def test_evidence_registry_never_in_catalog() -> None:
    """红线钉子：证据登记是人工路径，永不进 api_catalog（AI 不可写证据）。"""
    assert not any("evidence" in key for key in CATALOG)
    assert not any("/evidence" in str(entry["path"]) for entry in CATALOG.values())
