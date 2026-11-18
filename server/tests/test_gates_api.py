"""门禁引擎回归测试（G8/G9/decision 三类控制，goal §批次A 硬性判据）。

A1 修复的回归钉：G8 + conditional_pass 必须被拒（gate_result_not_allowed），
G9 + conditional_pass 不被误伤，G8 + pass 无 decision 必须被拒（gate_decision_required）。

goal-c CR-009：G8 stop 结算联动（flag_g8_stop_settlement）两条分支补载体——
有尾款行打 settlement_reason='g8_stop' + 事件；无尾款行只留事件不落标记。
"""
from __future__ import annotations

import hashlib
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from threading import Event
from time import monotonic, sleep
from uuid import uuid4

import pytest
from sqlalchemy import event, func, inspect, select, text, update

from fde_api.auth.models import User
from fde_api.auth.passwords import hash_password
from fde_api.auth.tokens import issue_access_token
from fde_api.evidence.models import ProjectEvidence
from fde_api.projects import gate_service
from fde_api.workbench.models import (
    Gate,
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


def _gate_snapshot(client, gates_url, gate_key):
    view = client.get(gates_url).json["data"]
    assert view["write_preconditions"] == "v1"
    return next(g for g in view["gates"] if g["gate_key"] == gate_key)


def test_gate_authorizes_after_locking_project_and_loading_members(
    admin_client, gate_project, app, monkeypatch
):
    """记录合法请求的 SQL 顺序，验证鉴权读到的是项目锁内的成员关系。"""
    _project, gates_url, leader_client = gate_project
    engine = app.extensions["fde_api_db"]
    if engine.dialect.name != "postgresql":
        pytest.skip("需要 PostgreSQL 的行锁查询")
    steps = []
    original_access = gate_service.project_access

    def after_execute(conn, cursor, statement, parameters, context, executemany):
        if "FROM projects" in statement and "FOR NO KEY UPDATE" in statement:
            steps.append("project_lock")
        if "FROM project_members" in statement:
            steps.append("members_loaded")

    def checked_access(actor, project):
        assert steps[-2:] == ["project_lock", "members_loaded"]
        assert "members" not in inspect(project).unloaded
        steps.append("authorized")
        return original_access(actor, project)

    monkeypatch.setattr(gate_service, "project_access", checked_access)
    event.listen(engine, "after_cursor_execute", after_execute)
    try:
        revision = _submit_all_evidence(admin_client, gates_url, "G6")
        response = leader_client.post(
            f"{gates_url}/G6/decision", json={"result": "pass", "expected_revision": revision}
        )
        assert response.status_code == 200, response.get_data(as_text=True)
    finally:
        event.remove(engine, "after_cursor_execute", after_execute)
    assert steps.count("authorized") == 3  # GET、提交、裁定


def _submit_all_evidence(admin_client, gates_url: str, gate_key: str) -> int:
    gate = _gate_snapshot(admin_client, gates_url, gate_key)
    response = admin_client.post(
        f"{gates_url}/{gate_key}/evidence",
        json={
            "expected_revision": gate["revision"],
            "items": [
                {
                    "label": item["label"],
                    "source_uri": f"fdeops://p3/{gate_key}/{index}",
                    "content_hash": hashlib.sha256(item["label"].encode()).hexdigest(),
                }
                for index, item in enumerate(gate["checklist"])
            ]
        },
    )
    assert response.status_code == 200, response.get_data(as_text=True)
    revision = response.json["data"]["revision"]
    assert revision == gate["revision"] + 1
    return revision


def test_g8_conditional_pass_is_rejected(admin_client, gate_project):
    """G8 试点毕业门不允许 conditional_pass：必须书面三态拍板（A1 回归钉）。"""
    _project, gates_url, leader_client = gate_project
    revision = _submit_all_evidence(admin_client, gates_url, "G8")

    response = leader_client.post(
        f"{gates_url}/G8/decision", json={"expected_revision": revision, "result": "conditional_pass"}
    )

    assert response.status_code == 400
    assert response.json["error"]["code"] == "gate_result_not_allowed"
    gates = leader_client.get(gates_url).json["data"]["gates"]
    assert next(g for g in gates if g["gate_key"] == "G8")["status"] == "evidence"


def test_g9_conditional_pass_still_allowed(admin_client, gate_project):
    """conditional_pass 仅限 G9 上线门：修复不得误伤。"""
    _project, gates_url, leader_client = gate_project
    revision = _submit_all_evidence(admin_client, gates_url, "G9")

    response = leader_client.post(
        f"{gates_url}/G9/decision", json={"expected_revision": revision, "result": "conditional_pass"}
    )

    assert response.status_code == 200
    assert response.json["data"]["status"] == "conditional_pass"


def test_g8_pass_requires_written_decision(admin_client, gate_project):
    """G8 过门必须带 proceed/pivot/stop 三态拍板。"""
    _project, gates_url, leader_client = gate_project
    revision = _submit_all_evidence(admin_client, gates_url, "G8")

    response = leader_client.post(f"{gates_url}/G8/decision", json={"expected_revision": revision, "result": "pass"})

    assert response.status_code == 400
    assert response.json["error"]["code"] == "gate_decision_required"


def test_g8_pass_with_decision_proceeds(admin_client, gate_project):
    """G8 + pass + decision 正常过门，decision 落库。"""
    _project, gates_url, leader_client = gate_project
    revision = _submit_all_evidence(admin_client, gates_url, "G8")

    response = leader_client.post(
        f"{gates_url}/G8/decision", json={"expected_revision": revision, "result": "pass", "decision": "proceed"}
    )

    assert response.status_code == 200, response.get_data(as_text=True)
    assert response.json["data"]["status"] == "passed"
    assert response.json["data"]["decision"] == "proceed"


def test_non_g8_gate_rejects_conditional_pass(admin_client, gate_project):
    """非 G8/G9 门禁的 conditional_pass 一律拒绝。"""
    _project, gates_url, leader_client = gate_project
    revision = _submit_all_evidence(admin_client, gates_url, "G6")

    response = leader_client.post(
        f"{gates_url}/G6/decision", json={"expected_revision": revision, "result": "conditional_pass"}
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
    revision = _submit_all_evidence(admin_client, gates_url, "G8")

    response = leader_client.post(
        f"{gates_url}/G8/decision", json={"expected_revision": revision, "result": "pass", "decision": "stop"}
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
    revision = _submit_all_evidence(admin_client, gates_url, "G8")

    response = leader_client.post(
        f"{gates_url}/G8/decision", json={"expected_revision": revision, "result": "pass", "decision": "stop"}
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


def test_template_outdated_flags_drift_and_tolerates_unknown(
    admin_client, gate_project, db_session
):
    """V3 T-G2（WB-DEF-5）：序列化比对冻结 template_hash vs 现行 gates.json sha256。

    存量行（迁移 f7a2c9e4b1d3 回填 f52afe88…）与现行模板已漂移 → template_outdated=true；
    按现行文件实例化的行 → false；template_hash=NULL（未知出处）→ false 不误报。
    """
    project, gates_url, _leader_client = gate_project
    # 首次访问触发懒实例化：按现行 gates.json 冻结 → 全部不漂移
    gates = admin_client.get(gates_url).json["data"]["gates"]
    assert len(gates) == 9
    assert all(gate["template_outdated"] is False for gate in gates)

    db_session.execute(
        update(Gate)
        .where(Gate.project_id == project["id"], Gate.gate_key == "G1")
        .values(template_hash="0" * 64)
    )
    db_session.execute(
        update(Gate)
        .where(Gate.project_id == project["id"], Gate.gate_key == "G2")
        .values(template_hash=None)
    )
    db_session.commit()

    by_key = {
        gate["gate_key"]: gate
        for gate in admin_client.get(gates_url).json["data"]["gates"]
    }
    assert by_key["G1"]["template_outdated"] is True
    assert by_key["G2"]["template_outdated"] is False
    assert by_key["G3"]["template_outdated"] is False


def test_gate_decision_stale_expected_revision_conflicts(admin_client, gate_project, db_session):
    """B#28 CAS：expected_revision 落后于当前 version → 409 且零变更（状态不动）。"""
    _project, gates_url, leader_client = gate_project
    _submit_all_evidence(admin_client, gates_url, "G8")
    current = db_session.scalar(
        select(Gate.version).where(
            Gate.project_id == _project["id"], Gate.gate_key == "G8"
        )
    )

    response = leader_client.post(
        f"{gates_url}/G8/decision",
        json={"result": "pass", "decision": "proceed", "expected_revision": current + 1},
    )

    assert response.status_code == 409, response.get_data(as_text=True)
    assert response.json["error"]["code"] == "gate_revision_conflict"
    db_session.expire_all()
    row = db_session.scalar(
        select(Gate).where(Gate.project_id == _project["id"], Gate.gate_key == "G8")
    )
    assert row.status == "evidence"  # 拍板未生效
    assert row.version == current  # revision 不动
    assert row.decided_at is None


def test_gate_decision_matching_expected_revision_passes_and_bumps(
    admin_client, gate_project, db_session
):
    """B#28 CAS：expected_revision 与当前 version 相等 → 拍板生效 + revision 推进。"""
    _project, gates_url, leader_client = gate_project
    _submit_all_evidence(admin_client, gates_url, "G8")
    current = db_session.scalar(
        select(Gate.version).where(
            Gate.project_id == _project["id"], Gate.gate_key == "G8"
        )
    )

    response = leader_client.post(
        f"{gates_url}/G8/decision",
        json={"result": "pass", "decision": "proceed", "expected_revision": current},
    )

    assert response.status_code == 200, response.get_data(as_text=True)
    assert response.json["data"]["status"] == "passed"
    db_session.expire_all()
    row = db_session.scalar(
        select(Gate).where(Gate.project_id == _project["id"], Gate.gate_key == "G8")
    )
    assert row.version == current + 1
    assert row.decided_by_user_id is not None


def test_gate_missing_preconditions_strict_default(admin_client, gate_project):
    _project, gates_url, leader_client = gate_project
    gate = _gate_snapshot(admin_client, gates_url, "G6")
    submitted = admin_client.post(f"{gates_url}/G6/evidence", json={"items": [{
        "label": gate["checklist"][0]["label"], "source_uri": "fdeops://g6/test", "content_hash": "a" * 64,
    }]})
    assert submitted.status_code == 428
    assert submitted.json["error"]["code"] == "gate_revision_required"
    assert _gate_snapshot(admin_client, gates_url, "G6") == gate

    _submit_all_evidence(admin_client, gates_url, "G6")
    fresh = _gate_snapshot(admin_client, gates_url, "G6")
    decided = leader_client.post(f"{gates_url}/G6/decision", json={"result": "pass"})
    assert decided.status_code == 428
    assert decided.json["error"]["code"] == "gate_revision_required"
    assert _gate_snapshot(admin_client, gates_url, "G6") == fresh


def test_gate_compatibility_still_validates_supplied_revision(admin_client, gate_project, settings, monkeypatch):
    monkeypatch.setattr(settings, "ux_write_preconditions_required", False)
    _project, gates_url, leader_client = gate_project
    gate = _gate_snapshot(admin_client, gates_url, "G6")
    items = [{"label": item["label"], "source_uri": "fdeops://legacy", "content_hash": "a" * 64}
             for item in gate["checklist"]]
    submitted = admin_client.post(f"{gates_url}/G6/evidence", json={"items": items})
    assert submitted.status_code == 200
    assert submitted.json["data"]["revision"] == gate["revision"] + 1
    denied = leader_client.post(f"{gates_url}/G6/decision", json={"result": "pass", "expected_revision": gate["revision"]})
    assert denied.status_code == 409
    invalid = admin_client.post(f"{gates_url}/G6/evidence", json={"items": items, "expected_revision": None})
    assert invalid.status_code == 400
    decided = leader_client.post(f"{gates_url}/G6/decision", json={"result": "pass"})
    assert decided.status_code == 200


def test_gate_compatibility_leaves_a_trace_for_every_skipped_precondition(
    admin_client, gate_project, settings, monkeypatch, db_session
):
    """兼容期放行必须留痕：否则事后无法区分「确认过」与「未确认」。"""
    monkeypatch.setattr(settings, "ux_write_preconditions_required", False)
    _project, gates_url, leader_client = gate_project
    gate = _gate_snapshot(admin_client, gates_url, "G6")
    items = [{"label": item["label"], "source_uri": "fdeops://legacy", "content_hash": "a" * 64}
             for item in gate["checklist"]]
    assert admin_client.post(f"{gates_url}/G6/evidence", json={"items": items}).status_code == 200
    assert leader_client.post(f"{gates_url}/G6/decision", json={"result": "pass"}).status_code == 200

    skipped = db_session.scalars(
        select(OperationEvent)
        .where(OperationEvent.event_type == "gate_write_precondition_skipped")
        .order_by(OperationEvent.occurred_at)
    ).all()
    assert [event.changes["action"] for event in skipped] == ["evidence", "decision"]
    assert {event.changes["gate_key"] for event in skipped} == {"G6"}


def test_gate_strict_mode_records_no_skipped_precondition(
    admin_client, gate_project, db_session
):
    """严格模式（默认）下所有写都带条件，不得出现放行留痕。"""
    _project, gates_url, leader_client = gate_project
    gate = _gate_snapshot(admin_client, gates_url, "G6")
    items = [{"label": item["label"], "source_uri": "fdeops://strict", "content_hash": "b" * 64}
             for item in gate["checklist"]]
    submitted = admin_client.post(
        f"{gates_url}/G6/evidence",
        json={"items": items, "expected_revision": gate["revision"]},
    )
    assert submitted.status_code == 200
    revision = submitted.json["data"]["revision"]
    assert leader_client.post(
        f"{gates_url}/G6/decision",
        json={"result": "pass", "expected_revision": revision},
    ).status_code == 200
    assert db_session.scalar(
        select(func.count())
        .select_from(OperationEvent)
        .where(OperationEvent.event_type == "gate_write_precondition_skipped")
    ) == 0


def test_gate_writes_are_paused_for_every_entrypoint(
    admin_client, gate_project, settings, monkeypatch, db_session
):
    """发布回退窗口：三条写入在同一开关下被拒，且不落业务成功事件。

    桌面直连、脚本、网页代理都打同一个 API，因此这里断言的是「服务端单点收口」。
    """
    monkeypatch.setattr(settings, "ux_write_paused", True)
    _project, gates_url, leader_client = gate_project
    gate = _gate_snapshot(admin_client, gates_url, "G6")
    items = [{"label": item["label"], "source_uri": "fdeops://paused", "content_hash": "c" * 64}
             for item in gate["checklist"]]

    evidence = admin_client.post(
        f"{gates_url}/G6/evidence",
        json={"items": items, "expected_revision": gate["revision"]},
    )
    assert evidence.status_code == 503
    assert evidence.json["error"]["code"] == "write_preconditions_paused"
    decision = leader_client.post(
        f"{gates_url}/G6/decision",
        json={"result": "pass", "expected_revision": gate["revision"]},
    )
    assert decision.status_code == 503
    assert decision.json["error"]["code"] == "write_preconditions_paused"

    # 暂停不等于成功：证据未登记、门禁版本未变、无成功事件。
    assert db_session.scalar(
        select(func.count())
        .select_from(OperationEvent)
        .where(OperationEvent.event_type.in_(["gate_evidence_submitted", "gate_decided"]))
    ) == 0
    assert _gate_snapshot(admin_client, gates_url, "G6")["revision"] == gate["revision"]


def test_paused_gate_write_keeps_unauthorized_requests_at_their_original_status(
    admin_client, client, gate_project, settings, monkeypatch, db_session
):
    """暂停不得改变未授权口径：无项目关系者仍得 403，不因暂停看到资源存在。"""
    monkeypatch.setattr(settings, "ux_write_paused", True)
    _project, gates_url, _leader_client = gate_project
    outsider = User(
        username=f"gate.outsider.{uuid4().hex[:8]}",
        display_name="Gate Outsider",
        role="fde_engineer",
        password_hash=hash_password(INITIAL_PASSWORD),
        must_change_password=False,
        is_active=True,
    )
    db_session.add(outsider)
    db_session.commit()
    outsider_client = AuthorizedClient(
        client, outsider, {"Authorization": f"Bearer {issue_access_token(outsider, settings)}"}
    )
    response = outsider_client.post(
        f"{gates_url}/G6/evidence",
        json={"items": [{"label": "x", "source_uri": "fdeops://x", "content_hash": "d" * 64}],
              "expected_revision": 1},
    )
    assert response.status_code == 403


def test_gate_decision_rejects_non_integer_expected_revision(admin_client, gate_project):
    """B#28 形状闸：expected_revision 非正整数（bool/字符串/0）→ 400。"""
    _project, gates_url, leader_client = gate_project
    _submit_all_evidence(admin_client, gates_url, "G6")

    for bad in ("1", True, 0, None):
        response = leader_client.post(
            f"{gates_url}/G6/decision", json={"result": "pass", "expected_revision": bad}
        )
        assert response.status_code == 400, response.get_data(as_text=True)
        assert response.json["error"]["code"] == "invalid_request"


def test_gate_view_exposes_revision_and_decision_accepts_it(
    admin_client, gate_project, db_session
):
    """B#28 桌面接线：门禁视图回传当前 revision，桌面据此做 CAS 版本复核。

    服务端 CAS 本身早已落地（decide_gate 收可选 expected_revision），但视图
    不回传 revision ⇒ 桌面无从得知当前值、CAS 实际从未被启用。本用例钉住
    「视图 revision ≡ 行 version」＋「用视图里的 revision 拍板可生效」。
    """
    project, gates_url, leader_client = gate_project
    gates = admin_client.get(gates_url).json["data"]["gates"]
    assert gates, "门禁视图不应为空"
    by_key = {gate["gate_key"]: gate for gate in gates}
    for gate in gates:
        assert isinstance(gate["revision"], int)
        assert gate["revision"] >= 1

    db_session.expire_all()
    row = db_session.scalar(
        select(Gate).where(
            Gate.project_id == project["id"], Gate.gate_key == by_key["G8"]["gate_key"]
        )
    )
    assert row is not None
    assert row.version == by_key["G8"]["revision"]

    _submit_all_evidence(admin_client, gates_url, "G8")
    fresh = {
        gate["gate_key"]: gate
        for gate in admin_client.get(gates_url).json["data"]["gates"]
    }["G8"]
    response = leader_client.post(
        f"{gates_url}/G8/decision",
        json={
            "result": "pass",
            "decision": "proceed",
            "expected_revision": fresh["revision"],
        },
    )
    assert response.status_code == 200, response.get_data(as_text=True)
    assert response.json["data"]["status"] == "passed"
    # 拍板生效即推进 revision（与既有 B#28 语义一致）
    assert response.json["data"]["revision"] == fresh["revision"] + 1


@pytest.mark.parametrize("already_decided", [False, True], ids=["awaiting-review", "passed"])
def test_gate_evidence_superseded_flag_detects_recollected_source(
    admin_client, gate_project, db_session, already_decided
):
    """B#30-A 前置复核：同一 source_uri 被重新采集（换 hash）⇒ 项级证据已换版。

    场景：清单项拍板引用 E1(hash=h1)；其后同一 source_uri 重新登记产生 E2(hash=h2)
    （T-G1 幂等语义：新行并存）⇒ 清单项仍指向 E1，平台须如实提示「证据已换版」。

    判据（立项文档 §2-A）：序列化必含 evidence_superseded=true，且**四不动**——
    门禁状态机五值、claim_status、拍板有效性均不变（呈现即提示）。
    """
    project, gates_url, leader_client = gate_project
    revision = _submit_all_evidence(admin_client, gates_url, "G8")

    g8 = _gate_snapshot(admin_client, gates_url, "G8")
    item = g8["checklist"][0]
    assert item["evidence_superseded"] is False
    if already_decided:
        decided = leader_client.post(
            f"{gates_url}/G8/decision",
            json={"result": "pass", "decision": "proceed", "expected_revision": revision},
        )
        assert decided.status_code == 200, decided.get_data(as_text=True)
        g8 = decided.json["data"]
    original_uri = item["source_uri"]
    original_hash = item["content_hash"]
    original_evidence_id = item["evidence_id"]

    # 同一 source_uri 重新采集 → 换 hash 的新证据行（kind=gate，与清单项同域）
    response = admin_client.post(
        f"/api/v1/projects/{project['id']}/evidence",
        json={
            "kind": "gate",
            "source_uri": original_uri,
            "content_sha256": hashlib.sha256(b"recollected").hexdigest(),
            "origin": "gate:G8/recollected",
            "captured_from": "human",
        },
    )
    assert response.status_code == 201, response.get_data(as_text=True)
    new_evidence = response.json["data"]["evidence"]
    assert new_evidence["id"] != original_evidence_id
    assert new_evidence["content_sha256"] != original_hash  # 换版前提：指纹确已不同

    db_session.expire_all()
    after = admin_client.get(gates_url).json["data"]["gates"]
    after_g8 = next(gate for gate in after if gate["gate_key"] == "G8")
    after_item = after_g8["checklist"][0]

    # 呈现即提示：该项标记证据已换版
    assert after_item["evidence_superseded"] is True
    assert after_item["evidence_id"] == original_evidence_id  # 仍指向原行（不自动改指针）
    # 四不动：状态机五值 / claim_status / 拍板有效性 均不变
    assert after_g8["status"] == g8["status"]
    assert after_item["claim_status"] == g8["checklist"][0]["claim_status"]
    assert after_g8["decision"] == g8["decision"]
    assert after_g8["revision"] == g8["revision"]  # 只读换版提示
    # 不携带新行指针（跳转走既有 evidence 登记簿面）
    assert "superseded_evidence_id" not in after_item


def test_gate_evidence_superseded_flag_stays_false_without_recollection(
    admin_client, gate_project
):
    """B#30-A 阴性：无重新采集时不得误报「证据已换版」。"""
    _project, gates_url, _leader_client = gate_project
    _submit_all_evidence(admin_client, gates_url, "G8")

    gates = admin_client.get(gates_url).json["data"]["gates"]
    g8 = next(gate for gate in gates if gate["gate_key"] == "G8")
    assert all(item["evidence_superseded"] is False for item in g8["checklist"])
    # 未提交的清单项（无 evidence_id）不得带此键为真
    pending = next(gate for gate in gates if gate["gate_key"] == "G1")
    assert all(item["evidence_superseded"] is False for item in pending["checklist"])


@pytest.mark.parametrize("initially_empty", [True, False], ids=["first-fill", "replace"])
def test_stale_evidence_leaves_gate_candidate_registry_and_audit_unchanged(
    admin_client, gate_project, db_session, initially_empty
):
    project, gates_url, leader_client = gate_project
    if not initially_empty:
        _submit_all_evidence(admin_client, gates_url, "G6")
    old = _gate_snapshot(admin_client, gates_url, "G6")
    label = old["checklist"][0]["label"]
    candidate = {"source_uri": "fdeops://g6/candidate", "content_hash": "c" * 64}
    db_session.execute(update(Gate).where(Gate.project_id == project["id"], Gate.gate_key == "G6")
                       .values(evidence_candidates=[candidate]))
    db_session.commit()
    winning_item = {"label": label, "source_uri": "fdeops://g6/winning", "content_hash": "b" * 64}
    winner = leader_client.post(f"{gates_url}/G6/evidence", json={
        "items": [winning_item], "expected_revision": old["revision"],
    })
    assert winner.status_code == 200
    view = admin_client.get(gates_url).json["data"]
    before_count = _evidence_count(db_session, project["id"])
    loser = admin_client.post(f"{gates_url}/G6/evidence", json={
        "items": [{"label": label, **candidate}], "expected_revision": old["revision"],
    })
    assert loser.status_code == 409
    assert loser.json["error"]["code"] == "gate_revision_conflict"
    assert admin_client.get(gates_url).json["data"] == view
    assert _evidence_count(db_session, project["id"]) == before_count
    assert _gate_snapshot(admin_client, gates_url, "G6")["evidence_candidates"]


def _evidence_count(session, project_id):
    return session.scalar(select(func.count()).select_from(ProjectEvidence)
                          .where(ProjectEvidence.project_id == project_id))


def test_same_evidence_with_new_submitter_invalidates_open_decision(admin_client, gate_project):
    _project, gates_url, leader_client = gate_project
    old_revision = _submit_all_evidence(leader_client, gates_url, "G6")
    old = _gate_snapshot(admin_client, gates_url, "G6")
    new_revision = _submit_all_evidence(admin_client, gates_url, "G6")
    fresh = _gate_snapshot(leader_client, gates_url, "G6")
    assert fresh["checklist"] == old["checklist"]
    assert fresh["submitted_by_user_id"] != old["submitted_by_user_id"]
    denied = leader_client.post(f"{gates_url}/G6/decision", json={
        "result": "pass", "expected_revision": old_revision,
    })
    assert denied.status_code == 409
    assert denied.json["error"]["code"] == "gate_revision_conflict"
    assert _gate_snapshot(leader_client, gates_url, "G6") == fresh
    accepted = leader_client.post(f"{gates_url}/G6/decision", json={
        "result": "pass", "expected_revision": new_revision,
        "accepted_labels": [item["label"] for item in fresh["checklist"]],
    })
    assert accepted.status_code == 200
    assert accepted.json["data"]["status"] == "passed"


@pytest.mark.parametrize("contender_action", ["evidence", "decision"])
def test_gate_writes_overlap_in_postgres(admin_client, gate_project, db_session, app, contender_action):
    """确认竞争写请求在 PostgreSQL 上等待证据写入事务。"""
    project, gates_url, leader_client = gate_project
    engine = app.extensions["fde_api_db"]
    if engine.dialect.name != "postgresql":
        pytest.skip("需要 PostgreSQL 的 pg_blocking_pids 实证")

    revision = _submit_all_evidence(admin_client, gates_url, "G6")
    gate = _gate_snapshot(admin_client, gates_url, "G6")
    label = gate["checklist"][0]["label"]
    writer_flushed = Event()
    release_writer = Event()
    contender_waiting = Event()
    pids = {}

    def before_execute(conn, cursor, statement, parameters, context, executemany):
        if (
            conn.info.get("ux_gate_test_role") == "contender"
            and "FROM projects" in statement
            and "FOR NO KEY UPDATE" in statement
        ):
            contender_waiting.set()

    def after_execute(conn, cursor, statement, parameters, context, executemany):
        # 门禁 UPDATE 已真正执行，事务尚未提交。
        if conn.info.get("ux_gate_test_role") == "evidence" and statement.startswith("UPDATE gates SET"):
            writer_flushed.set()
            assert release_writer.wait(10), "未释放证据写事务"

    def tag_connection(conn):
        from threading import current_thread

        role = current_thread().name.split("_")[0]
        if role in ("evidence", "contender"):
            conn.info["ux_gate_test_role"] = role
            pids[role] = conn.connection.driver_connection.info.backend_pid
        else:
            conn.info.pop("ux_gate_test_role", None)

    def post(person, action, payload):
        return app.test_client().post(f"{gates_url}/G6/{action}", json=payload, headers=person.headers)

    event.listen(engine, "engine_connect", tag_connection)
    event.listen(engine, "before_cursor_execute", before_execute)
    event.listen(engine, "after_cursor_execute", after_execute)
    try:
        with ThreadPoolExecutor(max_workers=1, thread_name_prefix="evidence") as winners,              ThreadPoolExecutor(max_workers=1, thread_name_prefix="contender") as losers:
            evidence = winners.submit(post, admin_client, "evidence", {
                "expected_revision": revision,
                "items": [{"label": label, "source_uri": "fdeops://g6/concurrent", "content_hash": "d" * 64}],
            })
            try:
                assert writer_flushed.wait(10), "证据写入未到达 UPDATE"
                contender_payload = {"expected_revision": revision}
                if contender_action == "decision":
                    contender_payload.update(result="pass", accepted_labels=[label])
                else:
                    contender_payload["items"] = [{
                        "label": gate["checklist"][1]["label"],
                        "source_uri": "fdeops://g6/stale-concurrent",
                        "content_hash": "e" * 64,
                    }]
                contender = losers.submit(post, leader_client, contender_action, contender_payload)
                assert contender_waiting.wait(10), "竞争事务未发起加锁查询"
                with engine.connect() as connection:
                    deadline = monotonic() + 4
                    while monotonic() < deadline:
                        blocking = connection.scalar(text("SELECT pg_blocking_pids(:pid)"), {"pid": pids["contender"]})
                        if pids["evidence"] in blocking:
                            break
                        sleep(0.01)
                    else:
                        pytest.fail("未观察到竞争事务被证据写入事务锁阻塞")
            finally:
                release_writer.set()
            assert evidence.result(timeout=10).status_code == 200
            denied = contender.result(timeout=10)
            assert denied.status_code == 409
            assert denied.json["error"]["code"] == "gate_revision_conflict"
    finally:
        event.remove(engine, "engine_connect", tag_connection)
        event.remove(engine, "before_cursor_execute", before_execute)
        event.remove(engine, "after_cursor_execute", after_execute)

    view = admin_client.get(gates_url).json["data"]
    gate = next(gate for gate in view["gates"] if gate["gate_key"] == "G6")
    assert gate["revision"] == revision + 1
    assert gate["status"] == "evidence"
    assert gate["checklist"][0]["claim_status"] == "claimed"
    assert not any(row["event_type"] == "gate_decided" for row in view["events"])
    assert sum(row["event_type"] == "gate_evidence_submitted" for row in view["events"]) == 2
    assert _evidence_count(db_session, project["id"]) == len(gate["checklist"]) + 1
