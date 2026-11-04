"""门禁引擎回归测试（G8/G9/decision 三类控制，goal §批次A 硬性判据）。

A1 修复的回归钉：G8 + conditional_pass 必须被拒（gate_result_not_allowed），
G9 + conditional_pass 不被误伤，G8 + pass 无 decision 必须被拒（gate_decision_required）。

goal-c CR-009：G8 stop 结算联动（flag_g8_stop_settlement）两条分支补载体——
有尾款行打 settlement_reason='g8_stop' + 事件；无尾款行只留事件不落标记。
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from fde_api.auth.models import User
from fde_api.auth.passwords import hash_password
from fde_api.auth.tokens import issue_access_token
from fde_api.evidence.models import ProjectEvidence
from fde_api.workbench.models import (
    IndustryTemplate,
    IndustryTemplateVersion,
    OperationEvent,
    Payment,
)
from fde_api.workbench.seed import GENERIC_TEMPLATE_KEY, seed_workbench

from conftest import INITIAL_PASSWORD


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
        username="gate.admin",
        display_name="Gate Admin",
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
def gate_project(admin_client, client, db_session, settings):
    """已激活项目 + 懒实例化的 9 门。

    P0-5 门禁验收分离后拍板人 ≠ 执行人：admin 只当证据执行人，
    拍板统一走 leader_client（项目管理位）。
    """
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
    leader = User(
        username=f"gate.leader.{uuid4().hex[:8]}",
        display_name="Gate Leader",
        role="project_lead",
        password_hash=hash_password(INITIAL_PASSWORD),
        must_change_password=False,
        is_active=True,
    )
    db_session.add(leader)
    db_session.commit()
    leader_client = AuthorizedClient(
        client, leader, {"Authorization": f"Bearer {issue_access_token(leader, settings)}"}
    )

    response = admin_client.post(
        "/api/v1/projects",
        json={
            "name": "门禁回归项目",
            "enterprise_code": f"门禁·回归·{uuid4().hex[:8]}",
            "template_version_id": template.id,
            "leader_user_id": leader.id,
            "planned_start_date": "2026-08-21",
            "module_keys": ["pre_diagnosis"],
        },
    )
    assert response.status_code == 201, response.get_data(as_text=True)
    project = response.json["data"]
    activated = admin_client.patch(
        f"/api/v1/projects/{project['id']}",
        json={"version": project["version"], "status": "active"},
    )
    assert activated.status_code == 200, activated.get_data(as_text=True)
    return (
        activated.json["data"],
        f"/api/v1/projects/{project['id']}/gates",
        leader_client,
    )


def _submit_all_evidence(admin_client, gates_url: str, gate_key: str) -> None:
    gates = admin_client.get(gates_url).json["data"]["gates"]
    gate = next(g for g in gates if g["gate_key"] == gate_key)
    response = admin_client.post(
        f"{gates_url}/{gate_key}/evidence",
        json={
            "items": [
                {
                    "label": item["label"],
                    "source_uri": f"fdeops://p3/{gate_key}",
                    "content_hash": hashlib.sha256(item["label"].encode()).hexdigest(),
                }
                for item in gate["checklist"]
            ]
        },
    )
    assert response.status_code == 200, response.get_data(as_text=True)


def test_g8_conditional_pass_is_rejected(admin_client, gate_project):
    """G8 试点毕业门不允许 conditional_pass：必须书面三态拍板（A1 回归钉）。"""
    _project, gates_url, leader_client = gate_project
    _submit_all_evidence(admin_client, gates_url, "G8")

    response = leader_client.post(
        f"{gates_url}/G8/decision", json={"result": "conditional_pass"}
    )

    assert response.status_code == 400
    assert response.json["error"]["code"] == "gate_result_not_allowed"
    gates = leader_client.get(gates_url).json["data"]["gates"]
    assert next(g for g in gates if g["gate_key"] == "G8")["status"] == "evidence"


def test_g9_conditional_pass_still_allowed(admin_client, gate_project):
    """conditional_pass 仅限 G9 上线门：修复不得误伤。"""
    _project, gates_url, leader_client = gate_project
    _submit_all_evidence(admin_client, gates_url, "G9")

    response = leader_client.post(
        f"{gates_url}/G9/decision", json={"result": "conditional_pass"}
    )

    assert response.status_code == 200
    assert response.json["data"]["status"] == "conditional_pass"


def test_g8_pass_requires_written_decision(admin_client, gate_project):
    """G8 过门必须带 proceed/pivot/stop 三态拍板。"""
    _project, gates_url, leader_client = gate_project
    _submit_all_evidence(admin_client, gates_url, "G8")

    response = leader_client.post(f"{gates_url}/G8/decision", json={"result": "pass"})

    assert response.status_code == 400
    assert response.json["error"]["code"] == "gate_decision_required"


def test_g8_pass_with_decision_proceeds(admin_client, gate_project):
    """G8 + pass + decision 正常过门，decision 落库。"""
    _project, gates_url, leader_client = gate_project
    _submit_all_evidence(admin_client, gates_url, "G8")

    response = leader_client.post(
        f"{gates_url}/G8/decision", json={"result": "pass", "decision": "proceed"}
    )

    assert response.status_code == 200, response.get_data(as_text=True)
    assert response.json["data"]["status"] == "passed"
    assert response.json["data"]["decision"] == "proceed"


def test_non_g8_gate_rejects_conditional_pass(admin_client, gate_project):
    """非 G8/G9 门禁的 conditional_pass 一律拒绝。"""
    _project, gates_url, leader_client = gate_project
    _submit_all_evidence(admin_client, gates_url, "G6")

    response = leader_client.post(
        f"{gates_url}/G6/decision", json={"result": "conditional_pass"}
    )

    assert response.status_code == 400
    assert response.json["error"]["code"] == "gate_result_not_allowed"


def test_submit_evidence_registers_first_class_evidence(admin_client, gate_project, db_session):
    """V3 T-E2：提交门禁证据 → 每项登记 project_evidence（kind=gate、origin=gate:Gx/<label>、
    captured_from=human）→ 清单项挂 evidence_id → 事件 items 携 evidence_id；未提交的清单项
    evidence_id=null（旧行读时合并，零迁移）；二次提交同指纹幂等（行数不增、id 不变）。"""
    project, gates_url, _leader_client = gate_project
    before = next(g for g in admin_client.get(gates_url).json["data"]["gates"] if g["gate_key"] == "G1")
    assert before["checklist"] and all(item["evidence_id"] is None for item in before["checklist"])

    _submit_all_evidence(admin_client, gates_url, "G1")
    after = next(g for g in admin_client.get(gates_url).json["data"]["gates"] if g["gate_key"] == "G1")
    ids = [item["evidence_id"] for item in after["checklist"]]
    assert all(ids) and len(set(ids)) == len(ids)
    rows = db_session.scalars(
        select(ProjectEvidence).where(ProjectEvidence.project_id == project["id"])
    ).all()
    assert {row.id for row in rows} == set(ids)
    assert all(
        row.kind == "gate" and row.captured_from == "human" and row.created_by_user_id == admin_client.user.id
        for row in rows
    )
    assert {row.origin for row in rows} == {f"gate:G1/{item['label']}" for item in after["checklist"]}
    assert {(row.source_uri, row.content_sha256) for row in rows} == {
        (item["source_uri"], item["content_hash"]) for item in after["checklist"]
    }
    event = db_session.scalars(
        select(OperationEvent)
        .where(OperationEvent.project_id == project["id"], OperationEvent.event_type == "gate_evidence_submitted")
        .order_by(OperationEvent.occurred_at.desc())
    ).first()
    assert [item["evidence_id"] for item in event.changes["items"]] == ids

    # 二次提交同指纹：幂等——清单项 evidence_id 不变、证据行数不增
    _submit_all_evidence(admin_client, gates_url, "G1")
    again = next(g for g in admin_client.get(gates_url).json["data"]["gates"] if g["gate_key"] == "G1")
    assert [item["evidence_id"] for item in again["checklist"]] == ids
    db_session.expire_all()
    assert db_session.scalar(
        select(func.count()).select_from(ProjectEvidence).where(ProjectEvidence.project_id == project["id"])
    ) == len(ids)


def _g8_stop_payment_row(db_session, project) -> Payment:
    """G8 尾款行（SOW C 里程碑）：金额真相留台账（本用例只关心结算标记）。"""
    row = Payment(
        project_id=project["id"],
        milestone_key="G8",
        sow_type="c",
        collects="G8 尾款",
        timing="验收通过",
        amount=Decimal("30000"),
        source_uri="fdeops://g8-stop/G8",
        content_hash=hashlib.sha256(b"g8-stop-test").hexdigest(),
        note="",
    )
    db_session.add(row)
    db_session.commit()
    return row


def test_g8_stop_flags_g8_settlement_when_row_exists(admin_client, gate_project, db_session):
    """CR-009：G8 + pass + decision=stop 有尾款行 → 打 settlement_reason='g8_stop'
    + 事件 flagged=true + note 追加结算说明；B 尾款照收（不因 stop 免除）。"""
    project, gates_url, leader_client = gate_project
    row = _g8_stop_payment_row(db_session, project)
    _submit_all_evidence(admin_client, gates_url, "G8")

    response = leader_client.post(
        f"{gates_url}/G8/decision", json={"result": "pass", "decision": "stop"}
    )
    assert response.status_code == 200, response.get_data(as_text=True)
    assert response.json["data"]["g8_stop_settlement"] == {"flagged": True, "milestone_key": "G8"}

    db_session.expire_all()
    db_session.refresh(row)
    assert row.settlement_reason == "g8_stop"
    assert row.note.endswith("G8 stop：按合同结算尾款")
    event = db_session.scalars(
        select(OperationEvent)
        .where(
            OperationEvent.project_id == project["id"],
            OperationEvent.event_type == "payment_settlement_flagged",
        )
        .order_by(OperationEvent.occurred_at.desc())
    ).first()
    assert event is not None
    assert event.changes["flagged"] is True and event.changes["reason"] == "g8_stop"


def test_g8_stop_without_settlement_row_only_records_event(admin_client, gate_project, db_session):
    """CR-009：无 G8 尾款行（计划未建）→ 只留事件 flagged=false，不落标记（建计划时人工确认）。"""
    project, gates_url, leader_client = gate_project
    _submit_all_evidence(admin_client, gates_url, "G8")

    response = leader_client.post(
        f"{gates_url}/G8/decision", json={"result": "pass", "decision": "stop"}
    )
    assert response.status_code == 200, response.get_data(as_text=True)
    assert response.json["data"]["g8_stop_settlement"] == {"flagged": False, "milestone_key": "G8"}

    assert db_session.scalar(
        select(func.count())
        .select_from(Payment)
        .where(Payment.project_id == project["id"], Payment.milestone_key == "G8")
    ) == 0
    event = db_session.scalars(
        select(OperationEvent)
        .where(
            OperationEvent.project_id == project["id"],
            OperationEvent.event_type == "payment_settlement_flagged",
        )
        .order_by(OperationEvent.occurred_at.desc())
    ).first()
    assert event is not None
    assert event.changes["flagged"] is False
