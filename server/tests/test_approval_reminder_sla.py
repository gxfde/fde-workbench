"""V3 P0 先行批 B#5：审批退避提醒 + SLA 统计。

- ``remind_pending_approvals``：pending 按 created_at 起算 10m→1h→4h→24h
  退避序列补发提醒（catch-up 可连升多级），账本 = result_json
  ["approval_reminders"]（零迁移）；幂等（已发等级不重发）；非 pending 零
  触碰；与过期清扫同语义的 skip_locked 并发安全。
- 序列化 SLA 面：审批列表加 pending_seconds / reminder_count /
  next_reminder_at（任务中心呈现，勿新开外发通道）；workflow run 详情
  waiting_approval 态带 waiting_approval_seconds，他态无该键。
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import update
from uuid import uuid4

from test_agents_d4_harness import make_user
from test_document_drafts_api import _persist_project
from test_workflow_definition import CALL, _call, _dag

from fde_api.control.models import AutomationApproval
from fde_api.control.scheduler import (
    APPROVAL_REMINDER_BACKOFF_MINUTES,
    remind_pending_approvals,
)
from fde_api.workflows.definition_service import create_definition
from fde_api.control.service import _serialize_approval
from fde_api.workflows.executor import serialize_run
from fde_api.workflows.models import WorkflowRun


def _seed_approval(db_session, project, *, status: str = "pending",
                   created_at: datetime | None = None) -> AutomationApproval:
    row = AutomationApproval(
        run_id=None,
        workflow_node_run_id=None,
        project_id=project.id,
        requested_by_user_id=project.leader_user_id,
        request_key=f"rk-{uuid4().hex[:8]}",
        capability="task.batch_assign",
        tool_name="project_tasks.batch_assign",
        arguments_json={"task_ids": ["t-1"]},
        arguments_sha256="a" * 64,
        risk_level=3,
        status=status,
        expires_at=datetime.now(UTC) + timedelta(hours=24),
    )
    db_session.add(row)
    db_session.flush()
    if created_at is not None:
        db_session.flush()
        db_session.execute(
            update(AutomationApproval)
            .where(AutomationApproval.id == row.id)
            .values(created_at=created_at)
        )
        db_session.flush()
        db_session.expire(row, ["created_at"])
    return row


def _minutes_ago(minutes: float) -> datetime:
    return datetime.now(UTC) - timedelta(minutes=minutes)


# ---------------------------------------------------------------------------
# 退避序列：未到期零发 / 到档发一级 / 幂等 / catch-up 连升 / 封顶
# ---------------------------------------------------------------------------


def test_backoff_sequence_issues_levels_idempotently(db_session, settings):
    leader = make_user(db_session, "project_lead")
    project = _persist_project(db_session, leader, code=f"AR{uuid4().hex[:4]}")

    # 5 分钟：未到首档（10m）→ 零发
    approval = _seed_approval(db_session, project, created_at=_minutes_ago(5))
    db_session.commit()
    assert remind_pending_approvals() == 0
    db_session.expire_all()
    assert db_session.get(AutomationApproval, approval.id).result_json in (None, {},)

    # 15 分钟：过首档未到次档（1h）→ 恰发 1 级；重复 sweep 幂等
    approval = _seed_approval(db_session, project, created_at=_minutes_ago(15))
    db_session.commit()
    assert remind_pending_approvals() == 1
    assert remind_pending_approvals() == 0
    db_session.expire_all()
    row = db_session.get(AutomationApproval, approval.id)
    ledger = row.result_json["approval_reminders"]
    assert [entry["level"] for entry in ledger] == [1]
    assert ledger[0]["due_at"] == (row.created_at + timedelta(minutes=10)).isoformat()

    # 25 小时：四档全过 → 一次 sweep catch-up 连升 4 级；再扫幂等（封顶）
    approval = _seed_approval(db_session, project, created_at=_minutes_ago(25 * 60))
    db_session.commit()
    assert remind_pending_approvals() == 4
    assert remind_pending_approvals() == 0
    db_session.expire_all()
    row = db_session.get(AutomationApproval, approval.id)
    assert [entry["level"] for entry in row.result_json["approval_reminders"]] == [1, 2, 3, 4]


def test_non_pending_approvals_never_touched(db_session, settings):
    leader = make_user(db_session, "project_lead")
    project = _persist_project(db_session, leader, code=f"AR{uuid4().hex[:4]}")
    stale = _seed_approval(db_session, project, status="executed",
                           created_at=_minutes_ago(30 * 24 * 60))
    db_session.commit()
    assert remind_pending_approvals() == 0
    db_session.expire_all()
    row = db_session.get(AutomationApproval, stale.id)
    assert row.result_json in (None, {})
    assert row.status == "executed"


def test_backoff_thresholds_shape() -> None:
    # 退避序列单调递增且四档（10 分钟起步、24 小时封顶）——钉死口径防误改
    assert APPROVAL_REMINDER_BACKOFF_MINUTES == (10, 60, 240, 1440)
    thresholds = list(APPROVAL_REMINDER_BACKOFF_MINUTES)
    assert all(a < b for a, b in zip(thresholds, thresholds[1:]))


# ---------------------------------------------------------------------------
# 序列化 SLA 面：审批列表 + workflow run 详情
# ---------------------------------------------------------------------------


def test_approval_serializer_sla_fields(db_session, settings):
    leader = make_user(db_session, "project_lead")
    project = _persist_project(db_session, leader, code=f"AR{uuid4().hex[:4]}")
    now = datetime.now(UTC)

    fresh = _seed_approval(db_session, project, created_at=now - timedelta(minutes=5))
    db_session.commit()
    data = _serialize_approval(fresh, now=now)
    assert data["pending_seconds"] == 300
    assert data["reminder_count"] == 0
    assert data["next_reminder_at"] == (fresh.created_at + timedelta(minutes=10)).isoformat()

    # 已发两级：next = 第三档（240m）
    reminded = _seed_approval(db_session, project, created_at=now - timedelta(minutes=90))
    reminded.result_json = {"approval_reminders": [
        {"level": 1, "due_at": "x", "issued_at": "x"},
        {"level": 2, "due_at": "x", "issued_at": "x"},
    ]}
    db_session.commit()
    data = _serialize_approval(reminded, now=now)
    assert data["reminder_count"] == 2
    assert data["next_reminder_at"] == (reminded.created_at + timedelta(minutes=240)).isoformat()

    # 非 pending：无挂起统计、无下一提醒；四级封顶后 next=None
    done = _seed_approval(db_session, project, status="rejected")
    db_session.commit()
    data = _serialize_approval(done, now=now)
    assert data["pending_seconds"] is None
    assert data["next_reminder_at"] is None
    assert data["reminder_count"] == 0

    capped = _seed_approval(db_session, project)
    capped.result_json = {"approval_reminders": [
        {"level": n, "due_at": "x", "issued_at": "x"} for n in range(1, 5)
    ]}
    db_session.commit()
    assert _serialize_approval(capped, now=now)["next_reminder_at"] is None


def test_workflow_run_detail_waiting_approval_seconds(db_session, settings):
    leader = make_user(db_session, "project_lead")
    project = _persist_project(db_session, leader, code=f"AR{uuid4().hex[:4]}")
    definition = create_definition(
        db_session, actor=leader, project_id=project.id, name="SLA 编排",
        dag=_dag(_call("gather", output="subjects")),
    )
    db_session.commit()
    now = datetime.now(UTC)

    waiting = WorkflowRun(
        definition_id=definition.id,
        definition_version=1,
        project_id=project.id,
        initiated_by_user_id=leader.id,
        idempotency_key=f"run-{uuid4().hex}",
        status="waiting_approval",
        context_json={},
    )
    db_session.add(waiting)
    db_session.flush()
    db_session.execute(
        update(WorkflowRun)
        .where(WorkflowRun.id == waiting.id)
        .values(updated_at=now - timedelta(minutes=3))
    )
    db_session.expire(waiting, ["updated_at"])
    db_session.commit()

    data = serialize_run(waiting, [], now=now)
    assert 170 <= data["waiting_approval_seconds"] <= 190  # 锚=updated_at（≈3 分钟前）

    finished = WorkflowRun(
        definition_id=definition.id,
        definition_version=1,
        project_id=project.id,
        initiated_by_user_id=leader.id,
        idempotency_key=f"run-{uuid4().hex}",
        status="succeeded",
        context_json={},
    )
    db_session.add(finished)
    db_session.commit()
    assert "waiting_approval_seconds" not in serialize_run(finished, [], now=now)
