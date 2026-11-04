"""V3 T-G1：任务产物→门禁证据候选（WB-DEF-8 候选闭环）。

语义钉：任务 status=completed 且 gate ∈ G1-9 + evidence_uri + evidence_hash
齐备 → gate 行挂候选（建议性，claim_status 与门禁状态机一概不动）；同
(uri, hash, task_key) 幂等；采纳走既有提交闸、命中指纹即剪除；拍板闸对
候选零感知（decide 不回归）。顺序无关：三要素在任意次更新里凑齐即挂
（完成在前/在后皆可）。
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from uuid import uuid4

import pytest
from sqlalchemy import select

from fde_api.auth.models import User
from fde_api.auth.passwords import hash_password
from fde_api.auth.tokens import issue_access_token
from fde_api.workbench.models import IndustryTemplate, IndustryTemplateVersion, OperationEvent
from fde_api.workbench.seed import GENERIC_TEMPLATE_KEY, seed_workbench

from conftest import INITIAL_PASSWORD

URI_A = "fdeops://engagements/demo/.fde/gates/G6/diagnosis.pdf"
URI_B = "fdeops://engagements/demo/.fde/gates/G6/baseline.xlsx"
HASH_A = hashlib.sha256(b"candidate-a").hexdigest()
HASH_B = hashlib.sha256(b"candidate-b").hexdigest()


@dataclass(frozen=True)
class AuthorizedClient:
    client: object
    user: User
    headers: dict[str, str]

    def get(self, *args, **kwargs):
        return self.client.get(*args, headers=self.headers, **kwargs)

    def post(self, *args, **kwargs):
        return self.client.post(*args, headers=self.headers, **kwargs)

    def patch(self, *args, **kwargs):
        return self.client.patch(*args, headers=self.headers, **kwargs)


@pytest.fixture
def admin_client(client, db_session, settings):
    user = User(
        username=f"cand.admin.{uuid4().hex[:8]}",
        display_name="Candidate Admin",
        role="admin",
        password_hash=hash_password(INITIAL_PASSWORD),
        must_change_password=False,
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()
    return AuthorizedClient(
        client, user, {"Authorization": f"Bearer {issue_access_token(user, settings)}"}
    )


@pytest.fixture
def leader_client(client, db_session, settings):
    leader = User(
        username=f"cand.leader.{uuid4().hex[:8]}",
        display_name="Candidate Leader",
        role="project_lead",
        password_hash=hash_password(INITIAL_PASSWORD),
        must_change_password=False,
        is_active=True,
    )
    db_session.add(leader)
    db_session.commit()
    return AuthorizedClient(
        client, leader, {"Authorization": f"Bearer {issue_access_token(leader, settings)}"}
    )


@pytest.fixture
def candidate_project(admin_client, leader_client, client, db_session):
    """草稿项目（模块任务随创建生成）+ 懒实例化 9 门；P0-5 下 admin 执行、leader 拍板。"""
    seed_workbench(db_session)
    db_session.commit()
    template = db_session.scalar(
        select(IndustryTemplateVersion)
        .join(IndustryTemplate)
        .where(
            IndustryTemplateVersion.status == "published",
            IndustryTemplate.template_key == GENERIC_TEMPLATE_KEY,
        )
    )
    response = admin_client.post(
        "/api/v1/projects",
        json={
            "name": "证据候选项目",
            "enterprise_code": f"候选·回归·{uuid4().hex[:8]}",
            "template_version_id": template.id,
            "leader_user_id": leader_client.user.id,
            "planned_start_date": "2026-08-21",
            "module_keys": ["pre_diagnosis"],
        },
    )
    assert response.status_code == 201, response.get_data(as_text=True)
    return response.json["data"]


def _tasks(admin_client, project_id: str) -> list[dict]:
    response = admin_client.get(f"/api/v1/projects/{project_id}/tasks")
    assert response.status_code == 200, response.get_data(as_text=True)
    return response.json["data"]["items"]


def _patch_task(admin_client, project_id: str, task: dict, **changes) -> dict:
    response = admin_client.patch(
        f"/api/v1/projects/{project_id}/tasks/{task['id']}",
        json={"version": task["version"], **changes},
    )
    assert response.status_code == 200, response.get_data(as_text=True)
    return response.json["data"]


def _gate(admin_client, project_id: str, gate_key: str) -> dict:
    response = admin_client.get(f"/api/v1/projects/{project_id}/gates")
    assert response.status_code == 200, response.get_data(as_text=True)
    return next(g for g in response.json["data"]["gates"] if g["gate_key"] == gate_key)


def _candidate_events(db_session, project_id: str) -> list[OperationEvent]:
    db_session.rollback()
    db_session.expire_all()
    return list(
        db_session.scalars(
            select(OperationEvent).where(
                OperationEvent.project_id == project_id,
                OperationEvent.event_type == "gate_evidence_candidate_attached",
            )
        )
    )


def test_completed_task_with_gate_evidence_attaches_candidate(
    admin_client, candidate_project, db_session
):
    """完成 + 挂点 + 指针+指纹 → 候选挂接；claim_status 与门禁状态机不动；事件留痕。"""
    project = candidate_project
    task = _patch_task(
        admin_client,
        project["id"],
        _tasks(admin_client, project["id"])[0],
        gate="G6",
        evidence_uri=URI_A,
        evidence_hash=HASH_A,
        status="completed",
    )

    gate = _gate(admin_client, project["id"], "G6")
    assert gate["status"] == "pending"
    assert all(item["claim_status"] is None for item in gate["checklist"])
    candidates = gate["evidence_candidates"]
    assert len(candidates) == 1
    entry = candidates[0]
    assert entry["source_uri"] == URI_A
    assert entry["content_hash"] == HASH_A  # 指纹统一小写落库
    assert entry["task_id"] == task["id"]
    assert entry["task_key"] == task["task_key"]
    assert entry["task_name"] == task["name"]
    assert entry["proposed_by_user_id"] == admin_client.user.id
    assert entry["proposed_at"]

    events = _candidate_events(db_session, project["id"])
    assert len(events) == 1
    payload = events[0].changes
    assert payload["gate_key"] == "G6"
    assert payload["task_key"] == task["task_key"]
    assert payload["source_uri"] == URI_A
    assert payload["content_hash"] == HASH_A


def test_candidate_requires_completed_status_and_full_fingerprint(
    admin_client, candidate_project, db_session
):
    """三缺一（未完成 / 缺挂点 / 缺指纹）都不挂——候选只在产物可承诺存在时出现。"""
    project = candidate_project
    tasks = _tasks(admin_client, project["id"])

    # 任务 A：挂点+证据齐但未完成 → 不挂
    _patch_task(
        admin_client, project["id"], tasks[0],
        gate="G6", evidence_uri=URI_A, evidence_hash=HASH_A,
    )
    # 任务 B：完成+证据但无挂点 → 不挂
    _patch_task(
        admin_client, project["id"], tasks[1],
        evidence_uri=URI_B, evidence_hash=HASH_B, status="completed",
    )
    # 任务 C：完成+挂点但只有指针无指纹 → 不挂
    _patch_task(
        admin_client, project["id"], tasks[2],
        gate="G6", evidence_uri=URI_A, status="completed",
    )

    gate = _gate(admin_client, project["id"], "G6")
    assert gate["evidence_candidates"] == []
    assert _candidate_events(db_session, project["id"]) == []


def test_candidate_attach_order_independent_and_deduped(
    admin_client, candidate_project, db_session
):
    """三要素任意更新次序凑齐即挂；重复更新同指纹幂等（候选与事件都不重复）。"""
    project = candidate_project
    task = _patch_task(
        admin_client, project["id"], _tasks(admin_client, project["id"])[0],
        gate="G6", evidence_uri=URI_A, evidence_hash=HASH_A,
    )
    assert _gate(admin_client, project["id"], "G6")["evidence_candidates"] == []

    # 后补完成 → 候选出现（effective 值 = 变更键 ∪ 既有任务字段）
    task = _patch_task(admin_client, project["id"], task, status="completed")
    assert len(_gate(admin_client, project["id"], "G6")["evidence_candidates"]) == 1

    # 同指纹再触发（改 progress）→ 幂等：候选仍 1 条、事件仍 1 条
    _patch_task(admin_client, project["id"], task, progress=100)
    gate = _gate(admin_client, project["id"], "G6")
    assert len(gate["evidence_candidates"]) == 1
    assert len(_candidate_events(db_session, project["id"])) == 1


def test_adoption_prunes_candidate_and_claims_item(admin_client, leader_client, candidate_project):
    """采纳走既有提交闸：指纹命中（hash 忽略大小写）→ 候选剪除、清单项 claimed+evidence_id。"""
    project = candidate_project
    _patch_task(
        admin_client, project["id"], _tasks(admin_client, project["id"])[0],
        gate="G6", evidence_uri=URI_A, evidence_hash=HASH_A, status="completed",
    )
    label = _gate(admin_client, project["id"], "G6")["checklist"][0]["label"]

    response = admin_client.post(
        f"/api/v1/projects/{project['id']}/gates/G6/evidence",
        json={
            "items": [
                {"label": label, "source_uri": URI_A, "content_hash": HASH_A.upper()}
            ]
        },
    )
    assert response.status_code == 200, response.get_data(as_text=True)
    gate = response.json["data"]
    assert gate["status"] == "evidence"
    assert gate["evidence_candidates"] == []
    claimed = next(item for item in gate["checklist"] if item["label"] == label)
    assert claimed["claim_status"] == "claimed"
    assert claimed["source_uri"] == URI_A
    assert claimed["evidence_id"]


def test_partial_adoption_keeps_other_candidates(admin_client, candidate_project):
    """提交指纹只剪命中者；另一任务的候选原样保留。"""
    project = candidate_project
    tasks = _tasks(admin_client, project["id"])
    _patch_task(
        admin_client, project["id"], tasks[0],
        gate="G6", evidence_uri=URI_A, evidence_hash=HASH_A, status="completed",
    )
    _patch_task(
        admin_client, project["id"], tasks[1],
        gate="G6", evidence_uri=URI_B, evidence_hash=HASH_B, status="completed",
    )
    gate = _gate(admin_client, project["id"], "G6")
    assert {entry["content_hash"] for entry in gate["evidence_candidates"]} == {HASH_A, HASH_B}
    label = gate["checklist"][0]["label"]

    response = admin_client.post(
        f"/api/v1/projects/{project['id']}/gates/G6/evidence",
        json={"items": [{"label": label, "source_uri": URI_A, "content_hash": HASH_A}]},
    )
    assert response.status_code == 200, response.get_data(as_text=True)
    remaining = response.json["data"]["evidence_candidates"]
    assert len(remaining) == 1
    assert remaining[0]["content_hash"] == HASH_B


def test_decide_gate_ignores_candidates(admin_client, leader_client, candidate_project):
    """拍板闸对候选零感知：候选在场时全清单提交+拍板照常过门，未采纳候选不剪除。"""
    project = candidate_project
    _patch_task(
        admin_client, project["id"], _tasks(admin_client, project["id"])[0],
        gate="G6", evidence_uri=URI_A, evidence_hash=HASH_A, status="completed",
    )
    gate = _gate(admin_client, project["id"], "G6")
    labels = [item["label"] for item in gate["checklist"]]

    response = admin_client.post(
        f"/api/v1/projects/{project['id']}/gates/G6/evidence",
        json={
            "items": [
                {
                    "label": label,
                    "source_uri": f"fdeops://engagements/demo/.fde/gates/G6/{index}",
                    "content_hash": hashlib.sha256(label.encode()).hexdigest(),
                }
                for index, label in enumerate(labels)
            ]
        },
    )
    assert response.status_code == 200, response.get_data(as_text=True)
    # 候选指纹不在本次提交里 → 保留（采纳是唯一剪除入口）
    assert len(response.json["data"]["evidence_candidates"]) == 1

    decide = leader_client.post(
        f"/api/v1/projects/{project['id']}/gates/G6/decision",
        json={"result": "pass", "accepted_labels": labels},
    )
    assert decide.status_code == 200, decide.get_data(as_text=True)
    assert decide.json["data"]["status"] == "passed"
    final = _gate(admin_client, project["id"], "G6")
    assert final["status"] == "passed"
    assert len(final["evidence_candidates"]) == 1
