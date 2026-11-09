"""N1 首跑补码轮：G-07——agent run 产物自动登记为建议性证据候选。

台账 G-07 判据：``captured_from`` 的 ``agent_run:`` 前缀虽在
``evidence/models.py:18`` 的 ``CAPTURED_FROM_PREFIXES`` 中定义，但**全仓零
生产者**（已落库的 agent 产物无一登记为候选）。本文件钉住新生产者：

- **登记**：completed run 的产物落一行 ``project_evidence``
  （``captured_from=agent_run:<run_id>``，指针 + sha256 指纹）；
- **只登记不采纳**：门禁状态机与清单项 ``claim_status`` 一律不动，
  ``gate.evidence_candidates`` 不被写——采纳仍走人工提交闸；
- **幂等**：同指纹重复登记不新增行（证据不可变）；
- **非 completed 不登记**：失败/超时 run 的产物是「留痕」不是「候选」。
"""
from __future__ import annotations

import hashlib
from pathlib import Path
from uuid import uuid4

from sqlalchemy import select

from test_agents_d4_harness import (  # noqa: F401  (pytest fixtures)
    FakeScanner,
    ScriptedEvents,
    api_client,
    d4_app,
    d4_client,
    d4_settings,
    prime_run,
    seed_agent,
)
from test_document_drafts_api import _persist_project
from test_goal_d2_s0_closeout import _confirmed_guidance

from fde_api.agents.adapter import ArtifactFile
from fde_api.agents.evidence_candidates import (
    AGENT_RUN_CAPTURED_FROM_PREFIX,
    evidence_kind_for_agent_run,
    register_agent_run_evidence_candidate,
)
from fde_api.evidence.models import CAPTURED_FROM_PREFIXES, EVIDENCE_KINDS, ProjectEvidence
from fde_api.workbench.models import Gate

_ARTIFACT_TEXT = "产物草案（由脱敏上下文衍生，无真实客户资料）"


def _scanner_factory(run_id, workspace):
    output = Path(workspace) / "output"
    output.mkdir(parents=True, exist_ok=True)
    (output / "draft.md").write_text(_ARTIFACT_TEXT, encoding="utf-8")
    return FakeScanner([ArtifactFile(path="draft.md", kind="doc", source_refs=("src-1",))])


def _prepare(db_session, d4_client, d4_settings, code: str):
    leader = api_client(d4_client, db_session, d4_settings, "project_lead")
    project = _persist_project(db_session, leader.user, code=code)
    _confirmed_guidance(
        db_session,
        project,
        leader.user,
        problems=[{"text": "库存与订单数据割裂", "classification": "数据", "source_refs": ["src-1"], "confirmed": True}],
    )
    agent = seed_agent(db_session, d4_settings)
    return leader, project, agent


def test_completed_run_registers_evidence_candidate(db_session, d4_client, d4_app, d4_settings):
    """completed run 的产物 ⇒ project_evidence 行（captured_from=agent_run:<run_id>）。"""
    leader, project, agent = _prepare(db_session, d4_client, d4_settings, f"EV1{uuid4().hex[:4]}")
    prime_run(
        d4_app,
        events=ScriptedEvents([[{"type": "done", "exit_code": 0}]]),
        scanner_factory=_scanner_factory,
    )

    body = leader.post(
        f"/api/v1/agents/{agent.id}/run",
        json={"project_id": project.id, "idempotency_key": f"ev1:{uuid4().hex}"},
    )
    assert body.status_code == 201, body.json
    run = body.json["data"]
    assert run["status"] == "completed"
    artifact = run["artifacts"][0]

    db_session.commit()
    rows = db_session.scalars(
        select(ProjectEvidence).where(
            ProjectEvidence.project_id == project.id,
            ProjectEvidence.captured_from == f"agent_run:{run['id']}",
        )
    ).all()
    assert len(rows) == 1, "completed run 的产物必须登记一行建议性证据候选"
    row = rows[0]
    assert row.source_uri == artifact["storage_ref"]
    assert row.content_sha256 == artifact["sha256"]
    assert row.content_sha256 == hashlib.sha256(_ARTIFACT_TEXT.encode("utf-8")).hexdigest()
    assert row.kind == "workflow"  # 未绑定方案 ⇒ workflow
    assert row.kind in EVIDENCE_KINDS
    assert row.created_by_user_id is None  # 系统登记不伪装成人工提交


def test_candidate_registration_is_idempotent(db_session, d4_client, d4_app, d4_settings):
    """同指纹重复登记 ⇒ 仍是一行（证据不可变：同指纹幂等，不覆盖不改写）。"""
    leader, project, agent = _prepare(db_session, d4_client, d4_settings, f"EV2{uuid4().hex[:4]}")
    prime_run(
        d4_app,
        events=ScriptedEvents([[{"type": "done", "exit_code": 0}]]),
        scanner_factory=_scanner_factory,
    )
    body = leader.post(
        f"/api/v1/agents/{agent.id}/run",
        json={"project_id": project.id, "idempotency_key": f"ev2:{uuid4().hex}"},
    )
    assert body.status_code == 201, body.json
    run_id = body.json["data"]["id"]
    artifact = body.json["data"]["artifacts"][0]
    db_session.commit()

    with db_session.begin():
        for _ in range(2):
            evidence_id, created = register_agent_run_evidence_candidate(
                db_session,
                project_id=project.id,
                run_id=run_id,
                storage_ref=artifact["storage_ref"],
                content_sha256=artifact["sha256"],
                kind="workflow",
            )
    assert created is False  # 指纹已存在 ⇒ 幂等命中
    rows = db_session.scalars(
        select(ProjectEvidence).where(ProjectEvidence.project_id == project.id)
    ).all()
    assert len(rows) == 1
    assert rows[0].id == evidence_id


def test_candidate_is_not_auto_adopted(db_session, d4_client, d4_app, d4_settings):
    """**只登记不采纳**：门禁状态机不动、清单项不被 claim、候选不自动挂门禁。"""
    leader, project, agent = _prepare(db_session, d4_client, d4_settings, f"EV3{uuid4().hex[:4]}")
    prime_run(
        d4_app,
        events=ScriptedEvents([[{"type": "done", "exit_code": 0}]]),
        scanner_factory=_scanner_factory,
    )
    body = leader.post(
        f"/api/v1/agents/{agent.id}/run",
        json={"project_id": project.id, "idempotency_key": f"ev3:{uuid4().hex}"},
    )
    assert body.status_code == 201, body.json
    db_session.commit()

    evidence_ids = {
        row.id
        for row in db_session.scalars(
            select(ProjectEvidence).where(ProjectEvidence.project_id == project.id)
        ).all()
    }
    assert evidence_ids  # 候选已登记

    # 门禁行是懒实例化的——显式物化 9 行，否则断言会落在空集上（假绿）。
    from fde_api.projects.gate_service import ensure_project_gates

    db_session.commit()
    with db_session.begin():
        assert ensure_project_gates(db_session, project) == 9
    gates = db_session.scalars(select(Gate).where(Gate.project_id == project.id)).all()
    assert len(gates) == 9
    for gate in gates:
        # 门禁状态机不动（未进入 evidence/passed）
        assert gate.status in ("pending",)
        # 清单项未被 claim
        for item in gate.evidence_checklist or []:
            assert item.get("claim_status") != "claimed"
            assert item.get("evidence_id") not in evidence_ids
        # 候选**未**自动挂到门禁（那是人工领用面）
        assert not gate.evidence_candidates


def test_failed_run_registers_no_candidate(db_session, d4_client, d4_app, d4_settings):
    """失败 run（exit_code≠0）⇒ 不登记候选（产物是留痕，不是候选）。"""
    leader, project, agent = _prepare(db_session, d4_client, d4_settings, f"EV4{uuid4().hex[:4]}")
    prime_run(
        d4_app,
        events=ScriptedEvents([[{"type": "done", "exit_code": 3}]]),
        scanner_factory=_scanner_factory,
    )
    body = leader.post(
        f"/api/v1/agents/{agent.id}/run",
        json={"project_id": project.id, "idempotency_key": f"ev4:{uuid4().hex}"},
    )
    assert body.status_code == 201, body.json
    assert body.json["data"]["status"] == "failed"

    db_session.commit()
    rows = db_session.scalars(
        select(ProjectEvidence).where(ProjectEvidence.project_id == project.id)
    ).all()
    assert rows == []


def test_prefix_alignment_and_kind_mapping() -> None:
    """生产者前缀必须落在 ``CAPTURED_FROM_PREFIXES`` 内（台账 G-07 判据的静态半边）。"""
    assert AGENT_RUN_CAPTURED_FROM_PREFIX in CAPTURED_FROM_PREFIXES
    assert evidence_kind_for_agent_run(linked_solution_id="sol-1") == "solution"
    assert evidence_kind_for_agent_run(linked_solution_id=None) == "workflow"
    assert evidence_kind_for_agent_run(linked_solution_id=None) in EVIDENCE_KINDS


def test_mime_type_is_derived_from_each_artifacts_own_path(monkeypatch):
    """顺带修复钉：mime 按产物**自身**扩展名推断。

    拆分前 ``service.py`` 内联版引用校验循环遗留的 ``file_path``（循环外残留
    绑定）——多产物 run 的所有行都拿到**最后一个**产物的 MIME；搬运时改用
    ``Path(artifact.path).name``，本钉防回退。
    """
    from fde_api.agents import artifact_persistence as ap
    from fde_api.agents.models import AgentArtifact

    registered: list[str] = []

    def _register(session, **kwargs):  # noqa: ANN001, ANN003
        registered.append(kwargs["storage_ref"])
        return None, True

    monkeypatch.setattr(ap, "register_agent_run_evidence_candidate", _register)

    class _Run:
        id = "run-mime"
        project_id = "p-mime"
        status = "completed"

    rows: list[AgentArtifact] = []

    class _Session:
        def add(self, row):  # noqa: ANN001
            rows.append(row)

    prepared = [
        (ArtifactFile(path="result.md", kind="doc"), "a" * 64, b"# hi"),
        (ArtifactFile(path="config.json", kind="config"), "b" * 64, b'{"ok": true}'),
    ]
    ap.persist_completed_run_artifacts(
        _Session(),
        _Run(),
        prepared,
        result_exit_code=0,
        solution_id=None,
        gate_open=False,
        l1_path=False,
    )
    assert [row.mime_type for row in rows] == ["text/markdown", "application/json"]
    assert [row.storage_ref for row in rows] == ["run-mime/output/result.md", "run-mime/output/config.json"]
    assert len(registered) == 2
