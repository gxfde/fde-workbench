"""V3 B#6：状态归属与对账自检钉（docs/architecture/状态归属与对账-v1.md §3）。

四层对账不变量的跨层钉子——单面行为各有专测（候选挂接/登记幂等/版本不可变/
base_conflict 并发），本文件只钉「跨层对账」：一层写入后，另一层的真相面必须
保持预期形态。六钉：

1. 候选 confirm 前不物化：任务/workflow 两腿挂候选后 ``project_evidence`` 零行、
   清单 claim_status 不动；物化唯一入口 = ``submit_gate_evidence``。
2. 引用-实体一致：清单项只持 evidence_id，(source_uri, content_hash) 必须与被引
   ``ProjectEvidence`` 行逐位一致（对账口径：引用方不复制真相，只持指针）。
3. 快照可重建（workflow 腿）：run 固定 (definition_id, version)，版本行 dag_json
   的重算指纹 == 落库 content_sha256；草稿演进 + 二次发布不动已固定版本。
4. 快照可重建（documents 腿）：``build_document_snapshot`` 纯读确定性——同项目
   两次构建 deep-equal（快照不落库，随时可重建）。
5. 指纹不一致拒绝（ontology 腿）：base 指纹不符 → confirm 409 零物化，真相层
   行数与内容保持漂移赢家的形态（HTTP 面同合同见 test_ontology_registry）。
6. B#21 接线钉：G9 种子 exit_condition 挂评测协议机器可算化公式
   （docs/architecture/交付效果评测协议-v0.md §5 冻结文本）——种子被
   extract-sop-map.py 重生成覆盖即红，强制重挂。
"""
from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from test_agents_d4_harness import make_user
from test_document_drafts_api import _persist_project
from test_workflow_definition import CALL, _call, _dag

from fde_api.documents.snapshots import build_document_snapshot
from fde_api.evidence.models import ProjectEvidence
from fde_api.ontology.models import OntologyChangeSet, OntologyTerm
from fde_api.ontology.service import (
    OntologyServiceError,
    confirm_change_set,
    propose_change_set,
    submit_change_set,
)
from fde_api.projects.gate_service import (
    attach_task_evidence_candidate,
    attach_workflow_evidence_candidate,
    ensure_project_gates,
    submit_gate_evidence,
)
from fde_api.workbench.models import Gate
from fde_api.workflows.definition_service import (
    create_definition,
    dag_sha256,
    publish_definition,
    update_definition_dag,
)
from fde_api.workflows.models import (
    WorkflowDefinition,
    WorkflowDefinitionVersion,
    WorkflowRun,
)

_SERVER_ROOT = Path(__file__).resolve().parents[1]
_REPO_ROOT = _SERVER_ROOT.parent


def _gate_row(db_session, project_id: str, gate_key: str) -> Gate:
    return db_session.scalar(
        select(Gate).where(Gate.project_id == project_id, Gate.gate_key == gate_key)
    )


def _evidence_count(db_session, project_id: str) -> int:
    return (
        db_session.execute(
            select(func.count())
            .select_from(ProjectEvidence)
            .where(ProjectEvidence.project_id == project_id)
        ).scalar_one()
    )


# ---------------------------------------------------------------------------
# 钉 1：候选 confirm 前不物化（跨层：候选 JSON → project_evidence 真相层）
# ---------------------------------------------------------------------------


def test_candidates_never_materialize_evidence_until_human_claim(db_session, settings):
    leader = make_user(db_session, "project_lead")
    project = _persist_project(db_session, leader, code=f"SR{uuid4().hex[:4]}")
    ensure_project_gates(db_session, project)  # 门禁懒实例化：先落 9 行再对账
    gate = _gate_row(db_session, project.id, "G6")
    assert gate is not None
    before_statuses = [item["claim_status"] for item in gate.evidence_checklist]
    assert _evidence_count(db_session, project.id) == 0

    task_uri, task_hash = "fdeops://sr/task.pdf", "a" * 64
    wf_uri, wf_hash = "fdeops://sr/run.pdf", "b" * 64
    assert (
        attach_task_evidence_candidate(
            db_session,
            actor=leader,
            project=project,
            task_id="t-1",
            task_key="TK-1",
            task_name="外勤任务",
            gate_key="G6",
            source_uri=task_uri,
            content_hash=task_hash,
        )
        is True
    )
    assert (
        attach_workflow_evidence_candidate(
            db_session,
            actor=leader,
            project=project,
            run_id="r-1",
            node_key="produce",
            gate_key="G6",
            source_uri=wf_uri,
            content_hash=wf_hash,
            label="产物",
        )
        is True
    )
    db_session.commit()

    # 对账核心：两腿候选各挂一条，但真相层（project_evidence）零行、清单不动
    gate = _gate_row(db_session, project.id, "G6")
    assert len(gate.evidence_candidates) == 2
    assert [item["claim_status"] for item in gate.evidence_checklist] == before_statuses
    assert all(item.get("evidence_id") is None for item in gate.evidence_checklist)
    assert _evidence_count(db_session, project.id) == 0

    # 物化唯一入口 = 真人提交闸：提交后才出现证据行，且恰一条
    label = gate.evidence_checklist[0]["label"]
    submit_gate_evidence(
        actor=leader,
        project_id=project.id,
        gate_key="G6",
        payload={
            "items": [
                {"label": label, "source_uri": task_uri, "content_hash": task_hash}
            ]
        },
    )
    db_session.expire_all()
    assert _evidence_count(db_session, project.id) == 1
    row = db_session.scalars(select(ProjectEvidence)).one()
    assert (row.source_uri, row.content_sha256) == (task_uri, task_hash)


# ---------------------------------------------------------------------------
# 钉 2：引用-实体一致（清单项 ↔ 被引证据行逐位对账）
# ---------------------------------------------------------------------------


def test_claimed_checklist_reconciles_with_evidence_row(db_session, settings):
    leader = make_user(db_session, "project_lead")
    project = _persist_project(db_session, leader, code=f"SR{uuid4().hex[:4]}")
    ensure_project_gates(db_session, project)
    db_session.commit()  # 先落盘再走提交闸（另开会话，未提交行锁会堵死查询）
    gate = _gate_row(db_session, project.id, "G9")
    label = gate.evidence_checklist[0]["label"]
    uri, digest = "fdeops://sr/golive.pdf", "c" * 64

    submit_gate_evidence(
        actor=leader,
        project_id=project.id,
        gate_key="G9",
        payload={"items": [{"label": label, "source_uri": uri, "content_hash": digest}]},
    )
    db_session.expire_all()

    gate = _gate_row(db_session, project.id, "G9")
    item = next(
        row for row in gate.evidence_checklist if row.get("evidence_id") is not None
    )
    evidence = db_session.get(ProjectEvidence, item["evidence_id"])
    assert evidence is not None
    # 引用方不复制真相：指针+指纹必须与证据实体逐位一致，两处漂移即对账失败
    assert item["source_uri"] == evidence.source_uri == uri
    assert item["content_hash"] == evidence.content_sha256 == digest
    assert evidence.project_id == project.id


# ---------------------------------------------------------------------------
# 钉 3：快照可重建（workflow 腿）——版本行指纹可重算 + run 固定版本不被演进污染
# ---------------------------------------------------------------------------


def test_workflow_run_snapshot_recomputes_from_immutable_version(db_session, settings):
    leader = make_user(db_session, "project_lead")
    project = _persist_project(db_session, leader, code=f"SR{uuid4().hex[:4]}")
    dag1 = _dag(_call("gather", output="subjects"))
    definition = create_definition(
        db_session, actor=leader, project_id=project.id, name="对账编排", dag=dag1
    )
    publish_definition(db_session, actor=leader, definition=definition)
    run = WorkflowRun(
        definition_id=definition.id,
        definition_version=1,
        project_id=project.id,
        initiated_by_user_id=leader.id,
        idempotency_key=f"run-{uuid4().hex}",
        context_json={"project_id": project.id},
    )
    db_session.add(run)
    db_session.commit()

    # 草稿演进 + 二次发布：版本行不可变，run 固定 (definition_id, 1)
    dag2 = _dag(_call("gather", output="subjects"), _call("draft", ["gather"]))
    update_definition_dag(db_session, actor=leader, definition=definition, dag=dag2)
    v2 = publish_definition(db_session, actor=leader, definition=definition)
    db_session.commit()

    pinned = (
        db_session.query(WorkflowDefinitionVersion)
        .filter_by(definition_id=run.definition_id, version=run.definition_version)
        .one()
    )
    assert pinned.version == 1
    assert pinned.dag_json == dag1  # v2 发布未污染 v1
    # 可重建判据：重算指纹 == 落库指纹（run 随时可从版本行重装出同一张图）
    assert dag_sha256(pinned.dag_json) == pinned.content_sha256
    assert dag_sha256(v2.dag_json) == v2.content_sha256
    assert v2.dag_json == dag2
    assert db_session.get(WorkflowDefinition, definition.id).version == 2


# ---------------------------------------------------------------------------
# 钉 4：快照可重建（documents 腿）——纯读确定性，两次构建 deep-equal
# ---------------------------------------------------------------------------


def test_document_snapshot_deterministic_rebuild(db_session, settings):
    leader = make_user(db_session, "project_lead")
    project = _persist_project(db_session, leader, code=f"SR{uuid4().hex[:4]}")
    first = build_document_snapshot(db_session, project.id, {"research_keys": []})
    second = build_document_snapshot(db_session, project.id, {"research_keys": []})
    # 快照不落库（纯读派生）：除 captured_at 采集时刻外逐位复现，否则证据面/文档面错位
    assert set(first) == set(second) and "captured_at" in first
    first.pop("captured_at"), second.pop("captured_at")
    assert first == second
    assert first["project"]["id"] == project.id


# ---------------------------------------------------------------------------
# 钉 5：指纹不一致拒绝（ontology 腿）——base_conflict 409 且真相层保持赢家形态
# ---------------------------------------------------------------------------


def test_ontology_base_conflict_rejects_and_zero_materializes(db_session, settings):
    leader = make_user(db_session, "project_lead")
    admin = make_user(db_session, "admin")
    project = _persist_project(db_session, leader, code=f"SR{uuid4().hex[:4]}")
    project_id = project.id

    def _create_item(term: str) -> dict:
        return {
            "action": "create_term",
            "term": term,
            "definition": "占位定义。",
            "term_type": "entity",
        }

    # 种子：确认一条术语（拍板人 ≠ 提交人）
    seed = propose_change_set(
        db_session,
        project_id=project_id,
        actor=leader,
        title="种子",
        proposed_json=[_create_item("回款凭证")],
    )
    submit_change_set(db_session, actor=leader, row=seed)
    confirm_change_set(db_session, actor=admin, row=seed)
    db_session.commit()
    seeded = db_session.scalars(
        select(OntologyTerm).where(OntologyTerm.project_id == project_id)
    ).all()
    assert len(seeded) == 1

    # stale 按旧 base 取指纹 → fresh 抢先改写 → stale 拍板必拒
    stale = propose_change_set(
        db_session,
        project_id=project_id,
        actor=leader,
        title="迟到的修订",
        proposed_json=[
            {
                "action": "update_term",
                "term": "回款凭证",
                "definition": "迟到的修订。",
            }
        ],
    )
    submit_change_set(db_session, actor=leader, row=stale)
    fresh = propose_change_set(
        db_session,
        project_id=project_id,
        actor=admin,
        title="抢先修订",
        proposed_json=[
            {
                "action": "update_term",
                "term": "回款凭证",
                "definition": "抢先修订的定义。",
            }
        ],
    )
    submit_change_set(db_session, actor=admin, row=fresh)
    confirm_change_set(db_session, actor=leader, row=fresh)
    db_session.commit()

    with pytest.raises(OntologyServiceError) as raised:
        confirm_change_set(db_session, actor=admin, row=stale)
    assert raised.value.code == "base_conflict"
    assert raised.value.status == 409
    db_session.rollback()
    db_session.expire_all()

    # 零物化：真相层保持漂移赢家形态，stale 停在 in_review
    terms = db_session.scalars(
        select(OntologyTerm).where(OntologyTerm.project_id == project_id)
    ).all()
    assert len(terms) == 1
    assert terms[0].definition == "抢先修订的定义。"
    assert db_session.get(OntologyChangeSet, stale.id).status == "in_review"


# ---------------------------------------------------------------------------
# 钉 6（B#21）：G9 exit_condition 挂评测协议机器可算化公式
# ---------------------------------------------------------------------------


def test_g9_exit_condition_wired_to_evaluation_protocol() -> None:
    gates = json.loads(
        (_SERVER_ROOT / "seeds" / "gates.json").read_text(encoding="utf-8")
    )
    g9 = next(g for g in gates["gates"] if g["gate_key"] == "G9")
    text = g9["exit_condition"]
    # 交付效果评测协议-v0.md §5 冻结文本（缺一即种子被重生成覆盖 → 红，强制重挂）
    assert "验收线达成 ≔ uplift_bounded ≥ 0.8 ∧ incidents = ∅ ∧ 三锚四反例全过" in text
    assert "insufficient_data" in text
    assert "交付效果评测协议-v0.md" in text
    # 原五项出门口径不因接线丢失
    for clause in ("Pilot→Production 子检查五项", "回滚演练过", "客户侧独立跑通", "成本护栏在位"):
        assert clause in text
    # 协议文档本体必须在库（口径与种子互为锚）
    assert (_REPO_ROOT / "docs" / "architecture" / "交付效果评测协议-v0.md").is_file()
