"""E8：A 轨只读降级的**接线点**测试（`automation_jobs.execute_automation_run`）。

覆盖三件事：
1. DSH 抛可降级错误 ⇒ run 落 `succeeded` + `output_json.degraded=True`
   + 待人工确认标记（**不是**直接 failed）；
2. DSH 抛不可降级错误 ⇒ 走既有诚实失败路径（run 落 `failed`）；
3. 降级面自身失败（模型未配置）⇒ 落 `failed` 但**仍留 degraded 痕迹**
   （不假装成功、不静默吞错）。

全部 mock，**不联网、不碰真实 provider**。
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import patch
from uuid import uuid4

import pytest

from fde_api.auth.models import User
from fde_api.auth.passwords import hash_password
from fde_api.auth.tokens import issue_access_token
from fde_api.control.models import AutomationTask, AutomationTaskRun
from fde_api.control.dsh_runtime import DSHRuntimeError

PASSWORD = "Passw0rd!demo"


class _Client:
    """最小 HTTP 封装（够本文件用：get/post/patch/delete）。"""

    def __init__(self, client, user, headers) -> None:
        self.client = client
        self.user = user
        self.headers = headers

    def get(self, *args, **kwargs):
        return self.client.get(*args, headers=self.headers, **kwargs)

    def post(self, *args, **kwargs):
        return self.client.post(*args, headers=self.headers, **kwargs)

    def patch(self, *args, **kwargs):
        return self.client.patch(*args, headers=self.headers, **kwargs)

    def delete(self, *args, **kwargs):
        return self.client.delete(*args, headers=self.headers, **kwargs)


@pytest.fixture
def make_account(client, db_session, settings):
    """造账号的工厂（**fixture 名与测试参数名不同**，避免同名遮蔽）。"""

    def create(role: str) -> _Client:
        user = User(
            username=f"{role}.{uuid4().hex}",
            display_name=role,
            role=role,
            password_hash=hash_password(PASSWORD),
            must_change_password=False,
            is_active=True,
        )
        db_session.add(user)
        db_session.commit()
        headers = {"Authorization": f"Bearer {issue_access_token(user, settings)}"}
        return _Client(client, user, headers)

    return create


def _make_task(db_session, user, *, task_type="ai", capabilities=None):
    """建一条 A 轨任务。

    **不挂 project**（`project_id` 可空）：本测试只验证降级落账语义，不需要
    项目上下文；而建项目会走 `projects` 删除链，撞上测试库清理序的既有缺口
    （`automation_approvals.run_id` RESTRICT 引用 `automation_task_runs`，而
    清理列表里 `AutomationTaskRun` 在 `AutomationApproval` 之前 —— 与本轮
    改动无关的既有基建问题，不在本轮修）。
    """
    task = AutomationTask(
        project_id=None,
        created_by_user_id=user.id,
        title="A 轨降级检查",
        source="desktop",
        task_type=task_type,
        status="active",
        schedule_kind="interval",
        schedule_expression="1d",
        timezone="Asia/Shanghai",
        prompt="检查项目现状并给出清单",
        next_run_at=datetime.now(UTC) + timedelta(days=1),
        requested_capabilities=list(capabilities or []),
    )
    db_session.add(task)
    db_session.commit()
    return task


def _make_run(db_session, task, user):
    run = AutomationTaskRun(
        task_id=task.id,
        requested_by_user_id=user.id,
        scheduled_for=datetime.now(UTC),
        status="queued",
        idempotency_key=f"e8-test-{task.id}",
    )
    db_session.add(run)
    db_session.commit()
    return run


def _job(run_id: str):
    class _Job:
        def __init__(self) -> None:
            self.target_id = run_id

    return _Job()


# --- 降级路径 ---------------------------------------------------------


def test_degradable_dsh_error_lands_degraded_success(app, db_session, make_account):
    """DSH 不可用 ⇒ run 落 succeeded 但带 degraded 标记与待人工确认。"""
    leader = make_account("project_lead")
    task = _make_task(db_session, leader.user)
    run = _make_run(db_session, task, leader.user)

    from fde_api.control import automation_jobs

    with patch.object(
        automation_jobs.dsh_runtime.current, "execute",
        side_effect=DSHRuntimeError("dsh_unavailable", "DSH 服务暂时不可用。", retryable=True),
    ), patch.object(
        automation_jobs, "_run_degraded_readonly",
        return_value=("项目现状清单：3 个任务待办。", ["project_read"]),
    ):
        automation_jobs.execute_automation_run(_job(run.id))

    db_session.expire_all()
    stored = db_session.get(AutomationTaskRun, run.id)
    assert stored is not None
    assert stored.status == "succeeded"
    assert stored.output_json["degraded"] is True
    assert stored.output_json["degraded_reason"] == "dsh_unavailable"
    assert stored.output_json["degraded_confirmation_required"] is True
    assert stored.output_json["degraded_tools_used"] == ["project_read"]
    assert "降级执行" in stored.result_summary
    assert stored.error_code == "dsh_unavailable"


def test_degraded_output_never_contains_prompt_body(app, db_session, make_account):
    """降级留痕只落描述与工具清单，**不落提示词正文**（提示词正文不入库纪律）。"""
    leader = make_account("project_lead")
    task = _make_task(db_session, leader.user)
    run = _make_run(db_session, task, leader.user)

    from fde_api.control import automation_jobs

    with patch.object(
        automation_jobs.dsh_runtime.current, "execute",
        side_effect=DSHRuntimeError("dsh_timeout", "DSH 执行超时。", retryable=True),
    ), patch.object(
        automation_jobs, "_run_degraded_readonly", return_value=("清单内容", []),
    ):
        automation_jobs.execute_automation_run(_job(run.id))

    db_session.expire_all()
    stored = db_session.get(AutomationTaskRun, run.id)
    assert stored is not None
    serialized = repr(stored.output_json)
    assert task.prompt not in serialized


# --- 不可降级路径 ------------------------------------------------------


def test_non_degradable_dsh_error_keeps_honest_failure_path(app, db_session, make_account):
    """返回形状坏 ⇒ 不降级，走既有诚实失败（run 落 failed）。"""
    leader = make_account("project_lead")
    task = _make_task(db_session, leader.user)
    run = _make_run(db_session, task, leader.user)

    from fde_api.control import automation_jobs

    with patch.object(
        automation_jobs.dsh_runtime.current, "execute",
        side_effect=DSHRuntimeError("dsh_response_invalid", "DSH 返回了无效结果。", retryable=True),
    ), patch.object(automation_jobs, "_run_degraded_readonly") as degraded:
        with pytest.raises(RuntimeError):
            automation_jobs.execute_automation_run(_job(run.id))
        degraded.assert_not_called()

    db_session.expire_all()
    stored = db_session.get(AutomationTaskRun, run.id)
    assert stored is not None
    assert stored.status == "failed"
    assert stored.error_code == "dsh_response_invalid"


def test_task_type_outside_closed_set_keeps_honest_failure_path(app, db_session, make_account):
    """任务类型不在 A 轨封闭集内（`system`）⇒ 不降级（诚实失败）。"""
    leader = make_account("project_lead")
    task = _make_task(db_session, leader.user, task_type="system")
    run = _make_run(db_session, task, leader.user)

    from fde_api.control import automation_jobs

    with patch.object(
        automation_jobs.dsh_runtime.current, "execute",
        side_effect=DSHRuntimeError("dsh_unavailable", "DSH 服务暂时不可用。", retryable=True),
    ), patch.object(automation_jobs, "_run_degraded_readonly") as degraded:
        with pytest.raises(RuntimeError):
            automation_jobs.execute_automation_run(_job(run.id))
        degraded.assert_not_called()

    db_session.expire_all()
    stored = db_session.get(AutomationTaskRun, run.id)
    assert stored is not None
    assert stored.status == "failed"


# --- 降级面自身失败 ---------------------------------------------------


def test_degraded_surface_failure_is_reported_not_swallowed(app, db_session, make_account):
    """降级面自身失败 ⇒ run 落 failed，但 degraded 痕迹仍在（不假装成功）。"""
    leader = make_account("project_lead")
    task = _make_task(db_session, leader.user)
    run = _make_run(db_session, task, leader.user)

    from fde_api.control import automation_jobs

    with patch.object(
        automation_jobs.dsh_runtime.current, "execute",
        side_effect=DSHRuntimeError("dsh_unavailable", "DSH 服务暂时不可用。", retryable=True),
    ), patch.object(
        automation_jobs, "_run_degraded_readonly",
        side_effect=DSHRuntimeError("ai_model_not_configured", "尚未配置可直连的模型。", retryable=False),
    ):
        automation_jobs.execute_automation_run(_job(run.id))

    db_session.expire_all()
    stored = db_session.get(AutomationTaskRun, run.id)
    assert stored is not None
    assert stored.status == "failed"
    assert stored.error_code == "ai_model_not_configured"
    # 降级痕迹仍留痕（可追查「曾经尝试降级」）
    assert stored.output_json["degraded"] is True
    assert stored.output_json["degraded_reason"] == "dsh_unavailable"


def test_real_api_task_with_dotted_capabilities_degrades_and_narrows_tools(
    app, db_session, make_account, monkeypatch
):
    """经真实 POST /task-center/automations 创建的点分能力任务，在 DSH 未启用时走通只读降级并收窄白名单。"""
    from datetime import date
    from fde_api.control import automation_jobs
    from fde_api.control.service import DEFAULT_AUTOMATION_CAPABILITIES
    from fde_api.workbench.models import Project

    admin = make_account("admin")
    project = Project(
        project_code=f"E8-R6-{uuid4().hex[:8]}",
        name="E8 R6 Degrade Project",
        enterprise_code="pilot-001",
        planned_start_date=date(2026, 11, 1),
        leader_user_id=admin.user.id,
        status="active",
        template_snapshot={},
    )
    db_session.add(project)
    db_session.commit()

    created = admin.post(
        "/api/v1/task-center/automations",
        json={
            "title": "只读项目巡检",
            "project_id": project.id,
            "source": "desktop",
            "schedule_kind": "once",
            "schedule_expression": "2026-11-20T09:00:00+08:00",
            "timezone": "Asia/Shanghai",
            "prompt": "汇总项目门禁与风险项。",
            "requested_capabilities": list(DEFAULT_AUTOMATION_CAPABILITIES) + ["workbench.write"],
        },
    )
    assert created.status_code == 201, created.json
    task_id = created.json["data"]["id"]
    queued = admin.client.post(
        f"/api/v1/task-center/automations/{task_id}/runs",
        headers={**admin.headers, "Idempotency-Key": f"r6-real-api-{task_id}"},
    )
    assert queued.status_code == 202, queued.json
    run_id = queued.json["data"]["id"]

    captured: dict[str, object] = {}

    def fake_direct_tool_completion(
        *,
        model,
        prompt,
        user,
        project_id,
        execution_id,
        system_prompt=None,
        max_tokens=16384,
        timeout_seconds=300,
        session=None,
        capabilities=None,
        allowed_tools=None,
    ):
        captured["capabilities"] = list(capabilities) if capabilities is not None else None
        captured["allowed_tools"] = tuple(allowed_tools) if allowed_tools is not None else None
        captured["execution_id"] = execution_id
        captured["project_id"] = project_id
        return "只读核查完成：共 2 项风险。", {"complete": True, "calls": []}, [{"tool": "project_read", "ok": True}]

    monkeypatch.setattr(
        "fde_api.control.model_preferences.resolve_model_preference",
        lambda *_args, **_kwargs: {
            "id": "pref-r6",
            "provider": "openai-compatible",
            "base_url": "https://api.minimaxi.com/v1",
            "model": "MiniMax-M3.1-Flash",
            "api_key": "sk-r6-test",
            "supports_tools": True,
        },
    )
    monkeypatch.setattr(
        "fde_api.control.ai_tool_loop.direct_tool_completion",
        fake_direct_tool_completion,
    )

    with patch.object(
        automation_jobs.dsh_runtime.current,
        "execute",
        side_effect=DSHRuntimeError("dsh_not_enabled", "DSH 服务尚未启用。", retryable=False),
    ):
        automation_jobs.execute_automation_run(_job(run_id))

    db_session.expire_all()
    stored = db_session.get(AutomationTaskRun, run_id)
    assert stored is not None
    assert stored.status == "succeeded", (stored.error_code, stored.error_message, stored.output_json)
    assert stored.output_json["degraded"] is True
    assert stored.output_json["degraded_reason"] == "dsh_not_enabled"
    assert stored.output_json["degraded_confirmation_required"] is True
    assert stored.output_json["degraded_tools_used"] == ["project_read"]
    assert captured["project_id"] == project.id
    assert captured["capabilities"] == list(DEFAULT_AUTOMATION_CAPABILITIES) + ["workbench.write"]
    assert captured["allowed_tools"] is not None
    assert "project_read" in captured["allowed_tools"]
    assert "system_status" not in captured["allowed_tools"]
    assert "api_execute" not in captured["allowed_tools"]
