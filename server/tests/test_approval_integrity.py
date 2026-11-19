"""审批参数完整性负向钉（AF1-WP5 批1 · T7-02/S07-AF1）。

``execute_approved_dsh_tool`` 在执行前重算 ``arguments_json`` canonical
sha256 并与 ``approval.arguments_sha256`` 比对（control/service.py 完整性
闸）——审批后参数漂移（审批所基于的批量分配参数被改）必须
409 ``approval_integrity_failed`` 且零副作用、业务替身零调用。该闸实现
此前已有但全测试树零覆盖（AF1-WP5 负向集盘点 S07-AF1 缺口①）。

正向对照腿：参数完整时闸放行并到达业务层（替身抛业务错转
``ControlServiceError``，状态不误置 executed）——证明负向腿不是「闸恒拒」
的假绿。
"""
from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from fde_api.control.service import (
    ControlServiceError,
    execute_approved_dsh_tool,
)
from fde_api.control.models import AutomationApproval
from fde_api.projects.service import ProjectServiceError
from test_agents_d4_harness import make_user
from test_document_drafts_api import _persist_project

ARGUMENTS: dict[str, Any] = {
    "member_user_id": "ghost-member",
    "mode": "assignee",
    "assignments": [{"task_id": "ghost-task", "version": 1}],
}


def _canonical(arguments: dict[str, Any]) -> str:
    return json.dumps(
        arguments, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    )


def _make_approved_approval(db_session, leader, *, arguments: dict[str, Any]) -> AutomationApproval:
    approval = AutomationApproval(
        project_id=_persist_project(db_session, leader, code=f"integ-{leader.id[:8]}").id,
        requested_by_user_id=leader.id,
        request_key="integrity-probe-1",
        capability="task.batch_assign",
        tool_name="project_tasks.batch_assign",
        arguments_json=arguments,
        arguments_sha256=hashlib.sha256(_canonical(arguments).encode("utf-8")).hexdigest(),
        risk_level=3,
        status="approved",
        expires_at=datetime.now(UTC) + timedelta(minutes=15),
        decision_reason="",
    )
    db_session.add(approval)
    db_session.commit()
    return approval


def test_drifted_arguments_rejected_with_zero_side_effects(
    db_session, app, monkeypatch: pytest.MonkeyPatch
) -> None:
    """审批后参数漂移 → 409 approval_integrity_failed；业务替身零调用、
    状态不误置 executed（零副作用）。"""
    leader = make_user(db_session, "project_lead")
    approval = _make_approved_approval(db_session, leader, arguments=ARGUMENTS)

    calls: list[dict[str, Any]] = []

    def _spy_batch_assign(**kwargs: Any) -> dict[str, Any]:
        calls.append(kwargs)
        return {"assigned": 0}

    from fde_api.control import service as control_service

    monkeypatch.setattr(control_service, "batch_assign_project_tasks_in_session", _spy_batch_assign)

    # 漂移：审批落库后 arguments_json 被改（模拟审批所基于参数变更）
    approval.arguments_json = {**ARGUMENTS, "mode": "collaborator"}
    db_session.commit()

    with app.app_context():
        with pytest.raises(ControlServiceError) as drifted:
            execute_approved_dsh_tool(approval_id=approval.id)

    assert drifted.value.code == "approval_integrity_failed"
    assert drifted.value.status == 409
    assert calls == [], "完整性闸必须先拦，业务替身不得被调用"
    db_session.expire_all()
    persisted = db_session.get(AutomationApproval, approval.id)
    assert persisted is not None and persisted.status == "approved"
    assert persisted.executed_at is None


def test_intact_arguments_pass_integrity_gate_and_reach_execution(
    db_session, app, monkeypatch: pytest.MonkeyPatch
) -> None:
    """参数完整 → 闸放行到达业务层（替身抛业务错→透传 ControlServiceError），
    业务失败不误置 executed——排除「闸恒拒」假绿。"""
    leader = make_user(db_session, "project_lead")
    approval = _make_approved_approval(db_session, leader, arguments=ARGUMENTS)

    from fde_api.control import service as control_service

    def _business_failure(**kwargs: Any) -> dict[str, Any]:
        raise ProjectServiceError("task_cancelled", "Cancelled tasks cannot be assigned.", 409)

    monkeypatch.setattr(control_service, "batch_assign_project_tasks_in_session", _business_failure)

    with app.app_context():
        with pytest.raises(ControlServiceError) as reached:
            execute_approved_dsh_tool(approval_id=approval.id)

    assert reached.value.code == "task_cancelled", "完整性闸应放行（业务层错误）"
    assert reached.value.code != "approval_integrity_failed"
    db_session.expire_all()
    persisted = db_session.get(AutomationApproval, approval.id)
    assert persisted is not None and persisted.status == "approved"
    assert persisted.executed_at is None
