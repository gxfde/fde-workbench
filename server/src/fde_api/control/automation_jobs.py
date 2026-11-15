"""Background dispatch of permission-scoped automation runs to DSH."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import joinedload

from fde_api.auth.models import User
from fde_api.control.access import authorize_ai_capability
from fde_api.control.automation_fallback import (
    DegradedFallbackPlan,
    OUTPUT_KEY_PRODUCED,
    plan_degraded_fallback,
)
from fde_api.control.dsh_runtime import DSHRuntimeError, dsh_runtime
from fde_api.control.knowledge import build_project_snapshot
from fde_api.control.models import AutomationTask, AutomationTaskRun
from fde_api.extensions import db
from fde_api.jobs.handlers import register_handler
from fde_api.jobs.models import BackgroundJob


def execute_automation_run(job: BackgroundJob) -> None:
    session = db.session()
    try:
        with session.begin():
            run = session.scalar(
                select(AutomationTaskRun)
                .options(
                    joinedload(AutomationTaskRun.requested_by),
                    joinedload(AutomationTaskRun.task).joinedload(AutomationTask.project),
                )
                .where(AutomationTaskRun.id == job.target_id)
                # PG 拒绝对外连接可空侧 FOR UPDATE，只锁主行。
                .with_for_update(of=AutomationTaskRun)
            )
            if run is None:
                raise RuntimeError("automation_run_not_found")
            if run.status in {"succeeded", "failed", "cancelled", "skipped"}:
                return
            task = run.task
            if task.status != "active":
                run.status = "skipped"
                run.error_code = "automation_inactive"
                run.error_message = "任务已暂停或归档。"
                run.finished_at = datetime.now(UTC)
                return
            for capability in task.requested_capabilities:
                decision = authorize_ai_capability(
                    user=run.requested_by,
                    capability=capability,
                    project=task.project,
                )
                if not decision.allowed:
                    run.status = "failed"
                    run.error_code = "permission_revoked"
                    run.error_message = "执行前权限检查未通过。"
                    run.finished_at = datetime.now(UTC)
                    return
            run.status = "running"
            run.attempt += 1
            run.started_at = run.started_at or datetime.now(UTC)
            runtime = dsh_runtime.current
            run.dsh_runtime_version = (
                runtime.selected_runtime_version(run.id)
                if hasattr(runtime, "selected_runtime_version")
                else runtime.runtime_version
            )
            run.agent_profile_version = task.dsh_profile
            snapshot = build_project_snapshot(
                session,
                project_id=task.project_id,
                actor_user_id=run.requested_by_user_id,
            ) if task.project_id else None
            run.knowledge_snapshot_id = snapshot.id if snapshot else None
        # 显式标注 `dict[str, Any]`：本字典的值类型本就异质（str / list[str] /
        # list[dict]），无标注时 mypy 推断为联合类型并污染全部下标取值
        # （存量 baseline 的 2 条 arg-type 即由此而来）。
        execution: dict[str, Any] = {
            "run_id": run.id,
            "idempotency_key": run.idempotency_key,
            "actor_user_id": run.requested_by_user_id,
            "project_id": task.project_id,
            "prompt": task.prompt,
            "allowed_tools": list(task.requested_capabilities),
            "task_type": task.task_type,
            "context_refs": (
                [{"kind": "knowledge_snapshot", "id": snapshot.id}]
                if snapshot
                else []
            ),
            "agent_profile": task.dsh_profile,
        }
    finally:
        session.close()

    try:
        result = dsh_runtime.current.execute(
            execution_id=execution["run_id"],
            idempotency_key=execution["idempotency_key"],
            actor_user_id=execution["actor_user_id"],
            project_id=execution["project_id"],
            prompt=execution["prompt"],
            allowed_tools=execution["allowed_tools"],
            context_refs=execution["context_refs"],
            agent_profile=execution["agent_profile"],
        )
    except DSHRuntimeError as error:
        # E8（A 轨只读降级，2026-11-13 拍板）：DSH 不可用时**不直接 failed**——
        # 走只读降级层，标 `degraded=true` 并留痕（N3-Q5），产出仍交确认人
        # 人工确认（H1/H11 不自动收敛）。降级不可行时回到既有诚实失败路径。
        plan = plan_degraded_fallback(
            error_code=error.code,
            capabilities=execution["allowed_tools"],
            task_type=execution["task_type"],
        )
        if plan is None:
            _record_dispatch_failure(execution["run_id"], error)
            raise RuntimeError(error.code) from error
        _record_degraded_execution(
            execution["run_id"],
            plan,
            prompt=execution["prompt"],
            actor_user_id=execution["actor_user_id"],
            project_id=execution["project_id"],
            capabilities=execution["allowed_tools"],
        )
        return

    result_session = db.session()
    try:
        with result_session.begin():
            current = result_session.get(AutomationTaskRun, execution["run_id"], with_for_update=True)
            if current is None or current.status in {"succeeded", "failed", "cancelled", "skipped"}:
                return
            current.status = "running" if result.status == "accepted" else result.status
            current.external_execution_id = result.external_execution_id
            current.dsh_runtime_version = result.runtime_version
            current.result_summary = result.summary
            current.output_json = result.output
            if result.status == "failed":
                current.error_code = "dsh_execution_failed"
                current.error_message = "DSH 任务执行失败。"
            if result.status in {"succeeded", "failed", "cancelled"}:
                current.finished_at = datetime.now(UTC)
    finally:
        result_session.close()


def _record_degraded_execution(
    run_id: str,
    plan: DegradedFallbackPlan,
    *,
    prompt: str,
    actor_user_id: str,
    project_id: str | None,
    capabilities: list[str] | tuple[str, ...] | None = None,
) -> None:
    """把一次 A 轨执行落成**只读降级**（E8）：标 `degraded=true` 并留痕。

    边界（N3 拍板）：
    - 降级态**不代发起审批、不代拍板**——产出仍交确认人（蔡工）人工确认；
    - 降级态**不接写类工具**——白名单由 `plan_degraded_fallback` 钉死；
    - 降级态执行面复用既有只读链（`ai_tool_loop.direct_tool_completion`），
      失败则如实落 failed 并记原因，**不吞错、不假装成功**；
    - 提示词正文与工具结果正文**不入库**（只落描述、工具清单与原因码）。
    """
    produced_text = ""
    produced_tools: list[str] = []
    failure_code = ""
    try:
        produced_text, produced_tools = _run_degraded_readonly(
            prompt=prompt,
            actor_user_id=actor_user_id,
            project_id=project_id,
            run_id=run_id,
            capabilities=capabilities,
            allowed_tools=plan.allowed_tools,
        )
    except DSHRuntimeError as error:
        # 降级面自身失败（模型未配置／AI 服务不可达）⇒ 诚实失败，不假装降级成功。
        failure_code = error.code

    session = db.session()
    try:
        with session.begin():
            current = session.get(AutomationTaskRun, run_id, with_for_update=True)
            if current is None or current.status in {"succeeded", "failed", "cancelled", "skipped"}:
                return
            output = dict(plan.output_payload)
            output[OUTPUT_KEY_PRODUCED] = (
                plan.produced_description if not produced_text else produced_text
            )
            if produced_tools:
                output["degraded_tools_used"] = list(produced_tools)
            current.output_json = output
            current.error_code = plan.reason
            current.error_message = "DSH 不可用，本次执行已降级为只读产出，需人工确认。"
            current.result_summary = (
                f"降级执行（{plan.reason}）：只读工具 {len(plan.allowed_tools)} 项可用"
                f"{'；人工确认待办' if plan.confirmation_required else ''}。"
            )
            if failure_code:
                # 降级面也失败 ⇒ 落 failed，但**留痕**（degraded 标记仍在 output 里）。
                current.status = "failed"
                current.error_code = failure_code
                current.error_message = "DSH 与只读降级均不可用。"
                current.finished_at = datetime.now(UTC)
            else:
                # 降级成功 ⇒ run 落 succeeded，但产物带 degraded 标记且待人工确认。
                current.status = "succeeded"
                current.finished_at = datetime.now(UTC)
    finally:
        session.close()


def _run_degraded_readonly(
    *,
    prompt: str,
    actor_user_id: str,
    project_id: str | None,
    run_id: str,
    capabilities: list[str] | tuple[str, ...] | None = None,
    allowed_tools: list[str] | tuple[str, ...] | None = None,
) -> tuple[str, list[str]]:
    """执行降级态的只读产出，返回（产出正文，只读工具清单）。

    复用 `ai_tool_loop.direct_tool_completion`（既有 13 例只读降级模式）：
    同一批工具、同一能力闸，只是没有 DSH 那一跳。
    """
    from fde_api.control.ai_tool_loop import direct_tool_completion
    from fde_api.control.model_preferences import resolve_model_preference

    session = db.session()
    try:
        user = session.get(User, actor_user_id)
        if user is None or not user.is_active:
            raise DSHRuntimeError("ai_access_denied", "账号已停用。", retryable=False)
        try:
            model = resolve_model_preference(session, actor_user_id, None)
        except Exception as error:  # noqa: BLE001 - 无可用模型即诚实失败，不吞错
            raise DSHRuntimeError(
                "ai_model_not_configured", "尚未配置可直连的模型。", retryable=False
            ) from error
        if not model:
            raise DSHRuntimeError("ai_model_not_configured", "尚未配置可直连的模型。", retryable=False)
        text, _usage, trace = direct_tool_completion(
            model=model,
            prompt=prompt,
            user=user,
            project_id=project_id,
            execution_id=run_id,
            system_prompt=(
                "只读降级执行：仅可使用只读工具查询事实，"
                "不得修改任何状态、不得发起审批、不得代替人工确认。"
            ),
            capabilities=capabilities if capabilities else None,
            allowed_tools=allowed_tools,
        )
        used = [
            str(item.get("tool") or "")
            for item in trace
            if isinstance(item, dict) and item.get("tool")
        ]
        return text, used
    finally:
        session.close()


def _record_dispatch_failure(run_id: str, error: DSHRuntimeError) -> None:
    session = db.session()
    try:
        with session.begin():
            run = session.get(AutomationTaskRun, run_id, with_for_update=True)
            if run is None or run.status in {"succeeded", "cancelled", "skipped"}:
                return
            run.status = "failed"
            run.error_code = error.code
            run.error_message = error.public_message
            run.finished_at = datetime.now(UTC)
    finally:
        session.close()


def register_automation_handler() -> None:
    register_handler("automation.execute", execute_automation_run)


def fail_run_on_worker_loss(session, job) -> None:
    """Close out an automation run whose worker died.

    Automation runs are deliberately **not** re-queued after a crash — they
    have external side effects (mail, MCP calls), so a human re-triggers
    them. The run still has to leave the running state, or the task centre
    shows it as running forever.
    """
    run = session.get(AutomationTaskRun, job.target_id)
    if run is None or run.status in {"succeeded", "failed", "cancelled", "skipped"}:
        return
    run.status = "failed"
    run.error_code = "automation_worker_lost"
    run.error_message = "自动化执行进程中断（后台任务进程退出），请重新触发。"
    run.finished_at = datetime.now(UTC)


def register_automation_failure_handler() -> None:
    from fde_api.jobs.handlers import register_job_failure_handler

    register_job_failure_handler("automation.execute", fail_run_on_worker_loss)
