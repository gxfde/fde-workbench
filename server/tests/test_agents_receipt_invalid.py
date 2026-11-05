"""B#2 回执「写错不重做」：业务成功但回执面损坏 = 独立终态。

契约：completed + exit 0 + 零声明产物 **且** scanner 回执状态 ∈
{files_without_manifest, manifest_invalid}（output/ 有文件没写 manifest /
manifest 不是合法 JSON）→ succeeded_but_receipt_invalid，不进
FAILED_STATUSES ⇒ retry_run 拒同键重跑（业务动作不重执行）。
``no_output``（无 output 目录或零文件）= 合法零产物任务，照旧 completed。

边界钉（C-1 合同兼容）：声明了产物但校验失败仍走既有 failed + retry 恢复
路径（test_c1_artifact_without_source_refs_rejected_and_retry_recovers 钉）。
"""
from __future__ import annotations

from uuid import uuid4

from sqlalchemy.orm import Session

from fde_api.agents.adapter import ArtifactFile, AgentRunResult
from fde_api.agents.models import AgentRegistry, AgentRun
from fde_api.agents.service import FAILED_STATUSES, ManifestOutputScanner, _finalize
from test_agents_d4_harness import make_user
from test_document_drafts_api import _persist_project


def _seed_run(db_session, leader, project) -> AgentRun:
    registry = AgentRegistry(
        kind="zcode",
        name=f"receipt-agent-{uuid4().hex[:6]}",
        enabled=True,
        capability_tier="project_operator",
        sandbox_profile="sandbox",
    )
    db_session.add(registry)
    db_session.flush()
    run = AgentRun(
        project_id=project.id,
        agent_id=registry.id,
        initiated_by_user_id=leader.id,
        capability_used="code.generate",
        status="running",
        context_ref=f"masked://runs/{uuid4().hex[:8]}",
        idempotency_key=f"ik-{uuid4().hex[:12]}",
    )
    db_session.add(run)
    db_session.commit()
    return run


def _result(*artifacts: ArtifactFile, receipt_state: str = "ok", exit_code: int = 0) -> AgentRunResult:
    return AgentRunResult(
        status="completed",
        exit_code=exit_code,
        token_cost=42,
        duration_ms=1500,
        artifacts=tuple(artifacts),
        tool_calls=(),
        degraded=False,
        degraded_reason=None,
        receipt_state=receipt_state,
    )


def test_missing_manifest_lands_receipt_invalid_and_refuses_retry(
    db_session, settings, tmp_path
):
    """output/ 有文件但没写 manifest → 回执终态；重试闸拒绝。"""
    leader = make_user(db_session, "project_lead")
    project = _persist_project(db_session, leader, code=f"RC{uuid4().hex[:4]}")
    run = _seed_run(db_session, leader, project)

    _finalize(
        lambda: Session(db_session.bind),
        run_id=run.id,
        result=_result(receipt_state="files_without_manifest"),
        known_refs=set(),
        workspace=tmp_path,
        solution_id=None,
    )

    db_session.expire_all()
    row = db_session.get(AgentRun, run.id)
    assert row.status == "succeeded_but_receipt_invalid"
    assert row.degraded is True
    assert row.degraded_reason == "receipt_missing"
    assert row.exit_code == 0  # 业务执行确实成功过
    # 回执终态不进 FAILED_STATUSES ⇒ retry_run 的闸（agent_retry_not_allowed）拒绝同键重跑
    assert "succeeded_but_receipt_invalid" not in FAILED_STATUSES


def test_no_output_is_legitimate_and_stays_completed(db_session, settings, tmp_path):
    """合法零产物任务（无 output 目录）照旧 completed——B#2 不误伤。"""
    leader = make_user(db_session, "project_lead")
    project = _persist_project(db_session, leader, code=f"RC{uuid4().hex[:4]}")
    run = _seed_run(db_session, leader, project)

    _finalize(
        lambda: Session(db_session.bind),
        run_id=run.id,
        result=_result(receipt_state="no_output"),
        known_refs=set(),
        workspace=tmp_path,
        solution_id=None,
    )

    db_session.expire_all()
    assert db_session.get(AgentRun, run.id).status == "completed"


def test_declared_artifact_validation_failure_keeps_c1_failed_contract(
    db_session, settings, tmp_path
):
    """C-1 兼容钉：声明产物校验失败（缺 source_refs）→ failed（retry 恢复面不变）。"""
    leader = make_user(db_session, "project_lead")
    project = _persist_project(db_session, leader, code=f"RC{uuid4().hex[:4]}")
    run = _seed_run(db_session, leader, project)

    _finalize(
        lambda: Session(db_session.bind),
        run_id=run.id,
        result=_result(ArtifactFile(path="ghost.py", kind="code", source_refs=())),
        known_refs=set(),
        workspace=tmp_path,
        solution_id=None,
    )

    db_session.expire_all()
    row = db_session.get(AgentRun, run.id)
    assert row.status == "failed"  # C-1 既有合同维持（retry 恢复路径由 test_c1_* 钉住）
    assert row.degraded_reason == "artifact_validation_failed"
    assert "failed" in FAILED_STATUSES  # 重试闸对 C-1 面保持开放


def test_clean_completed_run_keeps_completed_status(db_session, settings, tmp_path):
    """对照组：产物全干净 → 照旧 completed（B#2 不改变健康路径）。"""
    leader = make_user(db_session, "project_lead")
    project = _persist_project(db_session, leader, code=f"RC{uuid4().hex[:4]}")
    run = _seed_run(db_session, leader, project)

    output_dir = tmp_path / "output"
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "main.py").write_text("print('ok')\n", encoding="utf-8")

    _finalize(
        lambda: Session(db_session.bind),
        run_id=run.id,
        result=_result(
            ArtifactFile(path="main.py", kind="code", source_refs=("src/base.py",))
        ),
        known_refs={"src/base.py"},
        workspace=tmp_path,
        solution_id=None,
    )

    db_session.expire_all()
    assert db_session.get(AgentRun, run.id).status == "completed"


def test_manifest_scanner_receipt_states(tmp_path):
    """scanner 回执状态五态：no_output / files_without_manifest / manifest_invalid / ok。"""
    # 无 output 目录
    scanner = ManifestOutputScanner(tmp_path / "absent")
    assert scanner.scan() == []
    assert scanner.receipt_state == "no_output"

    # 空目录
    empty = tmp_path / "empty"
    empty.mkdir()
    scanner = ManifestOutputScanner(empty)
    assert scanner.scan() == []
    assert scanner.receipt_state == "no_output"

    # 有文件无 manifest
    messy = tmp_path / "messy"
    (messy / "nested").mkdir(parents=True)
    (messy / "nested" / "build.docx").write_bytes(b"x")
    scanner = ManifestOutputScanner(messy)
    assert scanner.scan() == []
    assert scanner.receipt_state == "files_without_manifest"

    # manifest 不是合法 JSON
    broken = tmp_path / "broken"
    broken.mkdir()
    (broken / "manifest.json").write_text("{not json", encoding="utf-8")
    scanner = ManifestOutputScanner(broken)
    assert scanner.scan() == []
    assert scanner.receipt_state == "manifest_invalid"

    # 合法 manifest → ok + 清单
    ok = tmp_path / "ok"
    ok.mkdir()
    (ok / "manifest.json").write_text(
        '[{"path": "a.py", "kind": "code", "source_refs": []}]', encoding="utf-8"
    )
    scanner = ManifestOutputScanner(ok)
    items = scanner.scan()
    assert scanner.receipt_state == "ok"
    assert [a.path for a in items] == ["a.py"]
