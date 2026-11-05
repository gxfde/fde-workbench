"""V3 T-W7：workflow 节点产物→门禁证据候选（立项 workflow-gate-evidence-candidates-v1 §6 验收 12 八段）。

红线钉子：产物必须由生产方在 output_json 顶层保留键 ``gate_evidence`` 自带
指针+指纹，平台永不自动派生指纹（D1）；坏标记不炸节点、skipped 事件留痕（D2）；
claim_status 恒不动，采纳唯一入口 = 真人提交闸命中指纹剪除（D4）；旧行缺
source_kind 读时缺省 "task"（D5）。八段：出现 / 幂等 / 换指纹并存 / 坏标记跳过 /
无标记零副作用 / 失败路径不登记 / 采纳剪除 / 缺键兼容。
"""
from __future__ import annotations

from uuid import uuid4

from sqlalchemy import func, select

from test_agents_d4_harness import (  # noqa: F401  (pytest fixture 再导出)
    d4_app,
    d4_settings,
    make_user,
)
from test_document_drafts_api import _persist_project
from test_workflow_executor import _make_definition, _node, _node_map, _sha, _start

from fde_api.control.service import ControlServiceError
from fde_api.projects.gate_service import (
    attach_task_evidence_candidate,
    attach_workflow_evidence_candidate,
    ensure_project_gates,
    list_project_gates,
    submit_gate_evidence,
)
from fde_api.workbench.models import Gate, OperationEvent
from fde_api.workflows.executor import resume_run, run_workflow_run
from fde_api.workflows.models import WorkflowRun


def _fake_api_sequence(monkeypatch, outcomes: list):
    """假 execute_api：按序消费 outcomes（Exception 则抛出，dict 则作为产物返回）。"""
    from fde_api.control import api_actions

    calls: list = []

    def fake_execute_api(**kwargs):
        calls.append(kwargs)
        outcome = outcomes[min(len(calls), len(outcomes)) - 1]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    monkeypatch.setattr(api_actions, "execute_api", fake_execute_api)
    return calls


def _gate_row(db_session, project_id: str, gate_key: str) -> Gate:
    return db_session.scalar(
        select(Gate).where(Gate.project_id == project_id, Gate.gate_key == gate_key)
    )


def _candidate_events(db_session, project_id: str) -> list[OperationEvent]:
    return list(
        db_session.scalars(
            select(OperationEvent).where(
                OperationEvent.project_id == project_id,
                OperationEvent.event_type.in_(
                    ("gate_evidence_candidate_attached", "gate_evidence_candidate_skipped")
                ),
            )
        )
    )


# ---------------------------------------------------------------------------
# 段 1 + 5：标记产物挂候选（claim 不动）/ 无标记零副作用
# ---------------------------------------------------------------------------


def test_marker_output_attaches_candidate_and_clean_node_zero_effect(
    db_session, settings, monkeypatch
):
    leader = make_user(db_session, "project_lead")
    project = _persist_project(db_session, leader, code=f"WG{uuid4().hex[:4]}")
    uri, digest = f"fdeops://wg/{uuid4().hex[:6]}/report.pdf", _sha("report")
    _fake_api_sequence(
        monkeypatch,
        [
            {
                "http_status": 200,
                "result": {"ok": True},
                "gate_evidence": {
                    "gate": "G5",
                    "label": "验收报告",
                    "source_uri": uri,
                    "content_sha256": digest,
                },
            },
            {"http_status": 200, "result": {"ok": True}},  # 无标记节点
        ],
    )
    definition = _make_definition(
        db_session,
        leader,
        project,
        _node("produce", output="report"),
        _node("quiet", ["produce"]),
        publish=True,
    )
    run, _ = _start(db_session, leader, project, definition)

    run_workflow_run(run.id)

    db_session.expire_all()
    assert db_session.get(WorkflowRun, run.id).status == "succeeded"
    nodes = _node_map(db_session, run.id)
    assert nodes["produce"].status == "succeeded"
    assert nodes["quiet"].status == "succeeded"
    gate = _gate_row(db_session, project.id, "G5")
    assert gate is not None
    candidates = gate.evidence_candidates or []
    assert len(candidates) == 1  # 无标记节点零贡献
    row = candidates[0]
    assert row["source_kind"] == "workflow"
    assert row["workflow_run_id"] == run.id
    assert row["workflow_node_key"] == "produce"
    assert row["label"] == "验收报告"
    assert row["source_uri"] == uri
    assert row["content_hash"] == digest
    assert row["proposed_by_user_id"] == leader.id
    # D4：候选只是提示——清单项 claim_status 一概不动
    assert all(item["claim_status"] is None for item in gate.evidence_checklist)
    events = _candidate_events(db_session, project.id)
    assert [event.event_type for event in events] == ["gate_evidence_candidate_attached"]
    assert events[0].target_type == "gate" and events[0].target_id == gate.id
    assert events[0].changes["workflow_node_key"] == "produce"


# ---------------------------------------------------------------------------
# 段 2 + 3：同指纹幂等 / 换指纹并存 / 与任务候选共享列表
# ---------------------------------------------------------------------------


def test_workflow_candidate_dedup_and_fingerprint_coexistence(db_session, settings):
    leader = make_user(db_session, "project_lead")
    project = _persist_project(db_session, leader, code=f"WG{uuid4().hex[:4]}")
    assert ensure_project_gates(db_session, project) == 9
    uri = "fdeops://wg/dedup.pdf"

    first = attach_workflow_evidence_candidate(
        db_session,
        actor=leader,
        project=project,
        run_id="r-1",
        node_key="produce",
        gate_key="G6",
        source_uri=uri,
        content_hash=_sha("v1"),
    )
    assert first is True
    # 同位同指纹（哈希大小写归一）→ 幂等跳过
    again = attach_workflow_evidence_candidate(
        db_session,
        actor=leader,
        project=project,
        run_id="r-1",
        node_key="produce",
        gate_key="G6",
        source_uri=uri,
        content_hash=_sha("v1").upper(),
    )
    assert again is False
    # 换指纹 → 新候选并存（两代产物诚实呈现，由人取舍）
    regenerated = attach_workflow_evidence_candidate(
        db_session,
        actor=leader,
        project=project,
        run_id="r-1",
        node_key="produce",
        gate_key="G6",
        source_uri=uri,
        content_hash=_sha("v2"),
    )
    assert regenerated is True
    gate = _gate_row(db_session, project.id, "G6")
    rows = gate.evidence_candidates
    assert [row["content_hash"] for row in rows] == [_sha("v1"), _sha("v2")]
    assert all(row["label"] == "produce" for row in rows)  # label 缺省 = 节点 key
    # dedup 按来源粒度隔离：任务侧同指纹照挂（共享同一列表，互不吞并）
    task_attached = attach_task_evidence_candidate(
        db_session,
        actor=leader,
        project=project,
        task_id="t-1",
        task_key="TK-1",
        task_name="外勤任务",
        gate_key="G6",
        source_uri=uri,
        content_hash=_sha("v1"),
    )
    assert task_attached is True
    assert len(_gate_row(db_session, project.id, "G6").evidence_candidates) == 3


# ---------------------------------------------------------------------------
# 段 4：坏标记跳过——executor 面（不炸节点）+ service 面（形状裁决）
# ---------------------------------------------------------------------------


def test_bad_marker_skips_but_node_still_succeeds(db_session, settings, monkeypatch):
    leader = make_user(db_session, "project_lead")
    project = _persist_project(db_session, leader, code=f"WG{uuid4().hex[:4]}")
    _fake_api_sequence(
        monkeypatch,
        [
            # 坏 gate：G99 不在 G1..G9
            {
                "http_status": 200,
                "result": {"ok": True},
                "gate_evidence": {
                    "gate": "G99",
                    "source_uri": "fdeops://wg/bad.pdf",
                    "content_sha256": _sha("bad"),
                },
            },
            # 非对象标记
            {"http_status": 200, "result": {"ok": True}, "gate_evidence": "oops"},
        ],
    )
    definition = _make_definition(
        db_session,
        leader,
        project,
        _node("bad_gate", output="a"),
        _node("bad_shape", ["bad_gate"], output="b"),
        publish=True,
    )
    run, _ = _start(db_session, leader, project, definition)

    run_workflow_run(run.id)

    db_session.expire_all()
    assert db_session.get(WorkflowRun, run.id).status == "succeeded"
    nodes = _node_map(db_session, run.id)
    assert nodes["bad_gate"].status == "succeeded"  # 坏标记不炸节点
    assert nodes["bad_shape"].status == "succeeded"
    # 坏 gate 在校验层拦下 → 懒初始化都不触发；非对象在 executor 层拦下
    assert (
        db_session.scalar(
            select(func.count()).select_from(Gate).where(Gate.project_id == project.id)
        )
        == 0
    )
    events = _candidate_events(db_session, project.id)
    reasons = {event.changes["reason"] for event in events}
    assert reasons == {"gate", "marker_not_object"}
    assert {event.target_type for event in events} == {"project", "workflow_run"}


def test_bad_marker_shapes_rejected_at_service_level(db_session, settings):
    leader = make_user(db_session, "project_lead")
    project = _persist_project(db_session, leader, code=f"WG{uuid4().hex[:4]}")
    assert ensure_project_gates(db_session, project) == 9
    good_uri, good_sha = "fdeops://wg/shape.pdf", _sha("shape")
    cases = [
        ("G0", good_uri, good_sha, None, "gate"),
        (123, good_uri, good_sha, None, "gate"),
        ("G6", "", good_sha, None, "source_uri"),  # 双字段缺一（uri 空）
        ("G6", None, good_sha, None, "source_uri"),
        ("G6", good_uri, None, None, "content_sha256"),  # 双字段缺一（sha 缺）
        ("G6", good_uri, "deadbeef", None, "content_sha256"),  # 非 64hex
        ("G6", "u" * 1025, good_sha, None, "source_uri"),  # 超长指针
        ("G6", good_uri, good_sha, "L" * 121, "label"),  # 超长 label
    ]
    for gate_key, uri, digest, label, _reason in cases:
        assert (
            attach_workflow_evidence_candidate(
                db_session,
                actor=leader,
                project=project,
                run_id="r-9",
                node_key="produce",
                gate_key=gate_key,
                source_uri=uri,
                content_hash=digest,
                label=label,
            )
            is False
        )
    gate = _gate_row(db_session, project.id, "G6")
    assert gate.evidence_candidates in (None, [])
    skipped = [
        event
        for event in _candidate_events(db_session, project.id)
        if event.event_type == "gate_evidence_candidate_skipped"
    ]
    assert len(skipped) == len(cases)
    assert {event.changes["reason"] for event in skipped} == {
        "gate",
        "source_uri",
        "content_sha256",
        "label",
    }


# ---------------------------------------------------------------------------
# 段 6 + 段 2（恢复腿）：失败路径零登记；resume 后成功挂上恰好一条
# ---------------------------------------------------------------------------


def test_failed_node_registers_nothing_and_resume_attaches_once(
    db_session, settings, monkeypatch
):
    leader = make_user(db_session, "project_lead")
    project = _persist_project(db_session, leader, code=f"WG{uuid4().hex[:4]}")
    uri, digest = f"fdeops://wg/{uuid4().hex[:6]}/acceptance.pdf", _sha("acceptance")
    marker_payload = {
        "http_status": 200,
        "result": {"ok": True},
        "gate_evidence": {
            "gate": "G5",
            "label": "验收报告",
            "source_uri": uri,
            "content_sha256": digest,
        },
    }
    calls = _fake_api_sequence(
        monkeypatch,
        [ControlServiceError("transient", "临时失败。", 503), marker_payload],
    )
    definition = _make_definition(
        db_session,
        leader,
        project,
        _node("produce", output="report"),
        publish=True,
    )
    run, _ = _start(db_session, leader, project, definition)

    run_workflow_run(run.id)

    db_session.expire_all()
    # 段 6：失败路径无产物可读——连门禁行都未实例化，候选面零登记
    assert db_session.get(WorkflowRun, run.id).status == "failed"
    assert _node_map(db_session, run.id)["produce"].status == "failed"
    assert (
        db_session.scalar(
            select(func.count()).select_from(Gate).where(Gate.project_id == project.id)
        )
        == 0
    )
    assert _candidate_events(db_session, project.id) == []

    resume_run(actor=leader, project_id=project.id, run_id=run.id)
    run_workflow_run(run.id)

    db_session.expire_all()
    assert db_session.get(WorkflowRun, run.id).status == "succeeded"
    gate = _gate_row(db_session, project.id, "G5")
    rows = gate.evidence_candidates or []
    assert len(rows) == 1  # 恢复成功恰好一条（同指纹不叠加）
    assert rows[0]["workflow_run_id"] == run.id
    assert rows[0]["content_hash"] == digest
    assert len(calls) == 2


# ---------------------------------------------------------------------------
# 段 7 + 8：采纳剪除回归 / source_kind 读时缺省 task
# ---------------------------------------------------------------------------


def test_adoption_prunes_workflow_candidate(db_session, settings):
    leader = make_user(db_session, "project_lead")
    project = _persist_project(db_session, leader, code=f"WG{uuid4().hex[:4]}")
    uri, digest = "fdeops://wg/adopt.pdf", _sha("adopt")
    assert (
        attach_workflow_evidence_candidate(
            db_session,
            actor=leader,
            project=project,
            run_id="r-2",
            node_key="produce",
            gate_key="G6",
            source_uri=uri,
            content_hash=digest,
            label="产物",
        )
        is True
    )
    db_session.commit()
    gate = _gate_row(db_session, project.id, "G6")
    assert len(gate.evidence_candidates) == 1
    # 采纳唯一入口 = 真人提交闸：同指纹提交 → 候选剪除 + 清单项 claimed（T-G1 行为回归）
    checklist_label = gate.evidence_checklist[0]["label"]
    submit_gate_evidence(
        actor=leader,
        project_id=project.id,
        gate_key="G6",
        payload={
            "items": [
                {"label": checklist_label, "source_uri": uri, "content_hash": digest}
            ]
        },
    )
    db_session.expire_all()
    gate = _gate_row(db_session, project.id, "G6")
    assert gate.evidence_candidates in (None, [])
    assert gate.evidence_checklist[0]["claim_status"] == "claimed"
    assert gate.evidence_checklist[0]["evidence_id"] is not None


def test_source_kind_read_time_defaults_task_for_legacy_rows(db_session, settings):
    leader = make_user(db_session, "project_lead")
    project = _persist_project(db_session, leader, code=f"WG{uuid4().hex[:4]}")
    assert ensure_project_gates(db_session, project) == 9
    gate = _gate_row(db_session, project.id, "G6")
    # 旧行无 source_kind 键（T-W7 之前的任务候选）；workflow 行显式带键
    gate.evidence_candidates = [
        {"source_uri": "fdeops://legacy/a.pdf", "content_hash": _sha("a"), "task_key": "TK-1"},
        {
            "source_uri": "fdeops://wf/b.pdf",
            "content_hash": _sha("b"),
            "source_kind": "workflow",
            "workflow_run_id": "r-3",
            "workflow_node_key": "produce",
            "label": "产物",
        },
    ]
    db_session.commit()

    view = list_project_gates(actor=leader, project_id=project.id)
    g6 = next(row for row in view["gates"] if row["gate_key"] == "G6")
    kinds = {row["source_uri"]: row["source_kind"] for row in g6["evidence_candidates"]}
    assert kinds == {
        "fdeops://legacy/a.pdf": "task",  # 读时缺省，任务侧行不回填
        "fdeops://wf/b.pdf": "workflow",
    }
