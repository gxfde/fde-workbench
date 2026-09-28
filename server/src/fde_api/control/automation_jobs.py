"""Background dispatch of permission-scoped automation runs to DSH."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import joinedload

from fde_api.control.access import authorize_ai_capability
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
                .with_for_update()
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
            execution = {
                "run_id": run.id,
                "idempotency_key": run.idempotency_key,
                "actor_user_id": run.requested_by_user_id,
                "project_id": task.project_id,
                "prompt": task.prompt,
                "allowed_tools": list(task.requested_capabilities),
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
        _record_dispatch_failure(execution["run_id"], error)
        raise RuntimeError(error.code) from error

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
