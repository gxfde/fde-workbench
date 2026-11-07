"""T-B1（goal-tb tb2）：agent_artifacts 扩列 + 人工接受写路径。

钉住：
- 派生摘要可从原件重建（B#6 纪律）——diff 统计/测试计数纯函数 + 二次派生一致；
- reviewed 写路径（度量表「智能体产物被人工接受率」此前恒 0 的根因=无写路径）
  ——can_manage 闸 + 谁何时留痕 + 撤回清痕 + 事件留痕；
- 扩列只读呈现（run 详情 artifacts 三新键）。
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

from fde_api.agents.artifact_summary import derive_artifact_summary
from fde_api.agents.models import AgentArtifact, AgentRun
from fde_api.workbench.models import OperationEvent, ProjectMember


def _member_client(db_session, d4_client, d4_settings, project, role: str = "fde_engineer") -> tuple[ApiClient, object]:
    user = make_user(db_session, role)
    db_session.add(ProjectMember(project_id=project.id, user_id=user.id, role="member"))
    db_session.commit()
    return ApiClient(d4_client, user, {"Authorization": f"Bearer {issue_access_token(user, d4_settings)}"}), user


def _seed_run_with_artifact(db_session, project, user, agent_id: str) -> tuple[AgentRun, AgentArtifact]:
    run = AgentRun(
        project_id=project.id,
        agent_id=agent_id,
        initiated_by_user_id=user.id,
        capability_used="agent.code.write",
        status="completed",
        context_ref="agent-workspaces/x/context.md",
        token_cost=10,
        idempotency_key=f"tb2:{uuid4().hex}",
    )
    db_session.add(run)
    db_session.flush()
    artifact = AgentArtifact(
        run_id=run.id,
        kind="test_results",
        storage_ref=f"{run.id}/output/report.txt",
        sha256="a" * 64,
        reviewed=False,
    )
    db_session.add(artifact)
    db_session.commit()
    return run, artifact


# ---------------------------------------------------------------------------
# 派生摘要（纯函数）


def test_derive_diff_summary_counts_files_and_lines() -> None:
    diff = (
        "diff --git a/src/app.py b/src/app.py\n"
        "index 111..222 100644\n"
        "--- a/src/app.py\n"
        "+++ b/src/app.py\n"
        "+added line\n"
        "+another added\n"
        "-removed line\n"
        " context line\n"
        "diff --git a/src/other.py b/src/other.py\n"
        "--- a/src/other.py\n"
        "+++ b/src/other.py\n"
        "-old\n"
    ).encode("utf-8")
    summary = derive_artifact_summary("diff", diff)
    assert summary == {"files_changed": 2, "additions": 2, "deletions": 2}
    # 可重建性：同一原件二次派生逐位一致（B#6「可从原件重建」）
    assert derive_artifact_summary("diff", diff) == summary


def test_derive_test_results_counts_and_other_kinds_return_none() -> None:
    output = "============================= 3 failed, 12 passed, 2 skipped in 4.1s =============================".encode("utf-8")
    assert derive_artifact_summary("test_results", output) == {
        "passed": 12, "failed": 3, "errors": 0, "skipped": 2,
    }
    # 自由格式逐条输出也累计（宁多计不漏计，摘要可从原件复核）
    free = "1 passed\n1 error\nok 5 passed".encode("utf-8")
    free_summary = derive_artifact_summary("test_results", free)
    assert free_summary is not None
    assert free_summary["errors"] == 1
    # 非 diff/test_results 零派生（不发明数字）
    assert derive_artifact_summary("code", b"print('hi')") is None
    assert derive_artifact_summary("doc", b"# readme") is None


# ---------------------------------------------------------------------------
# PATCH reviewed 写路径


def test_patch_artifact_reviewed_by_manager_records_who_and_when(
    db_session, d4_client, d4_settings
) -> None:
    leader = api_client(d4_client, db_session, d4_settings, "project_lead")
    project = _persist_project(db_session, leader.user, code=f"TB2A{uuid4().hex[:4]}")
    agent = seed_agent(db_session, d4_settings)
    member, _user = _member_client(db_session, d4_client, d4_settings, project)
    run, artifact = _seed_run_with_artifact(db_session, project, member.user, agent.id)

    # 成员（can_view 非 can_manage）不可复核——终审动作=管理面
    member_response = member.patch(
        f"/api/v1/agents/runs/{run.id}/artifacts/{artifact.id}",
        json={"reviewed": True},
    )
    assert member_response.status_code == 403

    accept = leader.patch(
        f"/api/v1/agents/runs/{run.id}/artifacts/{artifact.id}",
        json={"reviewed": True},
    )
    assert accept.status_code == 200, accept.get_json()
    body = accept.get_json()["data"]
    assert body["reviewed"] is True
    assert body["reviewed_by_user_id"] == leader.user.id
    assert body["reviewed_at"] is not None
    event = (
        db_session.query(OperationEvent)
        .filter_by(event_type="agent_artifact_reviewed")
        .one()
    )
    assert event.changes["artifact_id"] == artifact.id
    assert event.changes["reviewed"] is True

    withdraw = leader.patch(
        f"/api/v1/agents/runs/{run.id}/artifacts/{artifact.id}",
        json={"reviewed": False},
    )
    assert withdraw.status_code == 200
    assert withdraw.get_json()["data"]["reviewed"] is False
    assert withdraw.get_json()["data"]["reviewed_by_user_id"] is None
    assert withdraw.get_json()["data"]["reviewed_at"] is None


def test_patch_artifact_validates_run_artifact_pair_and_body(
    db_session, d4_client, d4_settings
) -> None:
    leader = api_client(d4_client, db_session, d4_settings, "project_lead")
    project = _persist_project(db_session, leader.user, code=f"TB2B{uuid4().hex[:4]}")
    other_project = _persist_project(db_session, leader.user, code=f"TB2C{uuid4().hex[:4]}")
    agent = seed_agent(db_session, d4_settings)
    member, _user = _member_client(db_session, d4_client, d4_settings, project)
    run, artifact = _seed_run_with_artifact(db_session, project, member.user, agent.id)
    other_run, _other_artifact = _seed_run_with_artifact(db_session, other_project, member.user, agent.id)

    # 未知 run / 跨 run 配对 / 非布尔 body
    missing = leader.patch(f"/api/v1/agents/runs/{uuid4().hex}/artifacts/{artifact.id}", json={"reviewed": True})
    assert missing.status_code == 404
    cross = leader.patch(f"/api/v1/agents/runs/{other_run.id}/artifacts/{artifact.id}", json={"reviewed": True})
    assert cross.status_code == 404
    bad_body = leader.patch(f"/api/v1/agents/runs/{run.id}/artifacts/{artifact.id}", json={"reviewed": "yes"})
    assert bad_body.status_code == 400


def test_run_detail_artifacts_expose_acceptance_columns(
    db_session, d4_client, d4_settings
) -> None:
    leader = api_client(d4_client, db_session, d4_settings, "project_lead")
    project = _persist_project(db_session, leader.user, code=f"TB2D{uuid4().hex[:4]}")
    agent = seed_agent(db_session, d4_settings)
    member, _user = _member_client(db_session, d4_client, d4_settings, project)
    run, artifact = _seed_run_with_artifact(db_session, project, member.user, agent.id)

    leader.patch(f"/api/v1/agents/runs/{run.id}/artifacts/{artifact.id}", json={"reviewed": True})
    detail = member.get(f"/api/v1/agents/runs/{run.id}")
    assert detail.status_code == 200
    artifacts = detail.get_json()["data"]["artifacts"]
    assert len(artifacts) == 1
    row = artifacts[0]
    assert row["reviewed"] is True
    assert row["reviewed_by_user_id"] == leader.user.id
    assert row["reviewed_at"] is not None
    # 派生摘要键存在（本行种数据未走 finalize 派生 → null 如实呈现）
    assert "derived_summary" in row and row["derived_summary"] is None
