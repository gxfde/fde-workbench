from __future__ import annotations

import json
import re
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from secrets import choice
from string import ascii_uppercase, digits
from typing import Any
from uuid import uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import joinedload

from fde_api.auth.models import User
from fde_api.auth.service import AuthServiceError, verify_current_password
from fde_api.control.access import CAPABILITY_REQUIREMENTS, authorize_ai_capability, capabilities_for_level, effective_ai_access
from fde_api.control.models import AutomationApproval, AutomationTask, AutomationTaskRun, ChannelBinding
from fde_api.control.knowledge import snapshot_for_run
from fde_api.extensions import db
from fde_api.jobs.outbox import enqueue_outbox
from fde_api.projects.permissions import project_access
from fde_api.projects.service import ProjectServiceError
from fde_api.projects.task_service import batch_assign_project_tasks_in_session
from fde_api.users.service import DISPLAY_NAME_MAX_LENGTH
from fde_api.workbench.models import Project, ProjectMember, ProjectModule, ProjectTask


class ControlServiceError(Exception):
    def __init__(self, code: str, message: str, status: int):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


DEFAULT_AUTOMATION_CAPABILITIES = ["project.read", "project.summarize", "file.search"]
_SENSITIVE_ARGUMENT_KEY = re.compile(
    r"password|passwd|pwd|token|secret|credential|authorization|bearer|api[_-]?key",
    re.IGNORECASE,
)


def account_summary(user: User) -> dict[str, Any]:
    level, source = effective_ai_access(user)
    session = db.session()
    try:
        binding = session.scalar(
            select(ChannelBinding).where(
                ChannelBinding.user_id == user.id,
                ChannelBinding.channel == "wechat_clawbot",
                ChannelBinding.status != "revoked",
            )
        )
        return {
            "user": _serialize_account_user(user),
            "ai_access": {
                "level": level,
                "source": source,
                "capabilities": capabilities_for_level(level),
                "system_operations_explicit_only": True,
            },
            "wechat_clawbot": _serialize_binding(binding),
        }
    finally:
        session.close()


def update_profile(*, user: User, display_name: str) -> dict[str, Any]:
    normalized = display_name.strip()
    if not normalized or len(normalized) > DISPLAY_NAME_MAX_LENGTH:
        raise ControlServiceError("invalid_display_name", "请输入有效的显示名称。", 400)
    session = db.session()
    try:
        with session.begin():
            current = session.get(User, user.id, with_for_update=True)
            if current is None or not current.is_active:
                raise ControlServiceError("account_inactive", "当前账户不可用。", 403)
            current.display_name = normalized
            session.flush()
            return _serialize_account_user(current)
    finally:
        session.close()


def begin_wechat_binding(*, user: User) -> dict[str, Any]:
    code = "".join(choice(ascii_uppercase + digits) for _ in range(8))
    expires_at = datetime.now(UTC) + timedelta(minutes=10)
    session = db.session()
    try:
        with session.begin():
            binding = session.scalar(
                select(ChannelBinding)
                .where(ChannelBinding.user_id == user.id, ChannelBinding.channel == "wechat_clawbot")
                .with_for_update()
            )
            if binding is None:
                binding = ChannelBinding(user_id=user.id, channel="wechat_clawbot")
                session.add(binding)
                next_version = 1
            else:
                next_version = binding.version + 1
            binding.status = "pending"
            binding.external_subject_hash = None
            binding.channel_display_name = ""
            binding.binding_code_digest = sha256(code.encode("utf-8")).hexdigest()
            binding.binding_expires_at = expires_at
            binding.commands_enabled = True
            binding.notifications_enabled = True
            binding.version = next_version
            session.flush()
            return {**_serialize_binding(binding), "binding_code": code}
    finally:
        session.close()


def update_wechat_binding(*, user: User, action: str) -> dict[str, Any]:
    statuses = {"pause": "paused", "resume": "active", "unbind": "revoked"}
    target_status = statuses.get(action)
    if target_status is None:
        raise ControlServiceError("invalid_binding_action", "不支持的微信绑定操作。", 400)
    session = db.session()
    try:
        with session.begin():
            binding = session.scalar(
                select(ChannelBinding)
                .where(ChannelBinding.user_id == user.id, ChannelBinding.channel == "wechat_clawbot", ChannelBinding.status != "revoked")
                .with_for_update()
            )
            if binding is None:
                raise ControlServiceError("wechat_binding_not_found", "尚未绑定微信 ClawBot。", 404)
            if action == "resume" and not binding.external_subject_hash:
                raise ControlServiceError("wechat_binding_incomplete", "请先完成微信绑定。", 409)
            binding.status = target_status
            binding.version += 1
            if action == "unbind":
                binding.external_subject_hash = None
                binding.binding_code_digest = None
                binding.binding_expires_at = None
                binding.commands_enabled = False
                binding.notifications_enabled = False
            session.flush()
            return _serialize_binding(binding)
    finally:
        session.close()


def complete_wechat_binding(
    *, binding_code: str, external_subject: str, display_name: str
) -> dict[str, Any]:
    code = binding_code.strip().upper()
    subject = external_subject.strip()
    if len(code) != 8 or not subject or len(subject) > 512 or len(display_name) > 120:
        raise ControlServiceError("invalid_binding_request", "微信绑定信息无效。", 400)
    now = datetime.now(UTC)
    session = db.session()
    try:
        with session.begin():
            binding = session.scalar(
                select(ChannelBinding)
                .where(
                    ChannelBinding.channel == "wechat_clawbot",
                    ChannelBinding.status == "pending",
                    ChannelBinding.binding_code_digest == sha256(code.encode("utf-8")).hexdigest(),
                    ChannelBinding.binding_expires_at > now,
                )
                .with_for_update()
            )
            if binding is None:
                raise ControlServiceError("binding_code_invalid", "绑定码无效或已过期。", 404)
            binding.external_subject_hash = sha256(subject.encode("utf-8")).hexdigest()
            binding.channel_display_name = display_name.strip()
            binding.status = "active"
            binding.binding_code_digest = None
            binding.binding_expires_at = None
            binding.last_seen_at = now
            binding.version += 1
            session.flush()
            return _serialize_binding(binding)
    except IntegrityError:
        raise ControlServiceError("wechat_already_bound", "该微信已绑定其他账户。", 409) from None
    finally:
        session.close()


def submit_wechat_command(*, payload: dict[str, Any]) -> dict[str, Any]:
    required = {"event_id", "external_subject", "text"}
    if not required <= set(payload):
        raise ControlServiceError("invalid_request", "微信指令参数不完整。", 400)
    event_id = payload["event_id"]
    subject = payload["external_subject"]
    prompt = payload["text"]
    project_id = payload.get("project_id")
    if (
        not isinstance(event_id, str)
        or not event_id.strip()
        or len(event_id) > 160
        or not isinstance(subject, str)
        or not subject.strip()
        or len(subject) > 512
        or not isinstance(prompt, str)
        or not prompt.strip()
        or len(prompt) > 20_000
        or (project_id is not None and not isinstance(project_id, str))
    ):
        raise ControlServiceError("invalid_request", "微信指令参数无效。", 400)

    # Do not persist provider identifiers in plaintext. Scoping the digest by
    # sender also keeps idempotency correct if a gateway uses per-user IDs.
    event_digest = sha256(
        f"{subject.strip()}\0{event_id.strip()}".encode("utf-8")
    ).hexdigest()
    source_event_id = f"wechat:sha256:{event_digest}"
    now = datetime.now(UTC)
    session = db.session()
    try:
        with session.begin():
            existing = session.scalar(
                select(AutomationTask)
                .options(joinedload(AutomationTask.project))
                .where(AutomationTask.source_event_id == source_event_id)
            )
            if existing is not None:
                run = session.scalar(
                    select(AutomationTaskRun).where(
                        AutomationTaskRun.idempotency_key == source_event_id
                    )
                )
                return {
                    "task": _serialize_automation_task(existing, can_run=False),
                    "run": _serialize_automation_run(run) if run else None,
                    "duplicate": True,
                }

            binding = session.scalar(
                select(ChannelBinding)
                .options(joinedload(ChannelBinding.user))
                .where(
                    ChannelBinding.channel == "wechat_clawbot",
                    ChannelBinding.external_subject_hash
                    == sha256(subject.strip().encode("utf-8")).hexdigest(),
                    ChannelBinding.status == "active",
                    ChannelBinding.commands_enabled.is_(True),
                )
                .with_for_update()
            )
            if binding is None or not binding.user.is_active:
                raise ControlServiceError("wechat_binding_not_found", "微信尚未绑定可用账户。", 403)
            resolved_project_id = project_id or binding.default_project_id
            project = session.get(Project, resolved_project_id) if resolved_project_id else None
            if project is None:
                raise ControlServiceError("project_required", "请在指令中选择项目。", 400)
            for capability in DEFAULT_AUTOMATION_CAPABILITIES:
                decision = authorize_ai_capability(
                    user=binding.user, capability=capability, project=project
                )
                if not decision.allowed:
                    raise ControlServiceError("forbidden", "当前账户无权在该项目使用 DSH。", 403)

            normalized_prompt = prompt.strip()
            task = AutomationTask(
                project_id=project.id,
                created_by_user_id=binding.user.id,
                title=normalized_prompt.splitlines()[0][:80],
                description="来自微信 ClawBot 的即时指令",
                source="wechat",
                source_event_id=source_event_id,
                task_type="ai",
                status="active",
                schedule_kind="once",
                schedule_expression=now.isoformat(),
                timezone="Asia/Shanghai",
                prompt=normalized_prompt,
                requested_capabilities=list(DEFAULT_AUTOMATION_CAPABILITIES),
                risk_level=0,
                next_run_at=now,
                notification_policy={"channel": "wechat_clawbot"},
            )
            session.add(task)
            session.flush()
            run = AutomationTaskRun(
                task_id=task.id,
                requested_by_user_id=binding.user.id,
                scheduled_for=now,
                status="queued",
                attempt=0,
                idempotency_key=source_event_id,
                dsh_runtime_version="",
                agent_profile_version=task.dsh_profile,
                result_summary="",
                external_execution_id="",
                output_json={},
                error_code="",
                error_message="",
            )
            session.add(run)
            binding.last_seen_at = now
            session.flush()
            enqueue_outbox(session, "automation.execute", run.id, {"run_id": run.id})
            return {
                "task": _serialize_automation_task(task, can_run=False),
                "run": _serialize_automation_run(run),
                "duplicate": False,
            }
    except IntegrityError:
        # Concurrent delivery of the same event is resolved by the unique
        # source_event_id. The gateway can safely retry and receive the winner.
        session.rollback()
        existing = session.scalar(
            select(AutomationTask)
            .options(joinedload(AutomationTask.project))
            .where(AutomationTask.source_event_id == source_event_id)
        )
        if existing is None:
            raise
        run = session.scalar(
            select(AutomationTaskRun).where(
                AutomationTaskRun.idempotency_key == source_event_id
            )
        )
        return {
            "task": _serialize_automation_task(existing, can_run=False),
            "run": _serialize_automation_run(run) if run else None,
            "duplicate": True,
        }
    finally:
        session.close()


def list_task_center(*, user: User) -> dict[str, Any]:
    session = db.session()
    try:
        scope = _project_scope(user)
        project_tasks = list(
            session.scalars(
                select(ProjectTask)
                .join(ProjectModule, ProjectTask.project_module_id == ProjectModule.id)
                .join(Project, ProjectModule.project_id == Project.id)
                .options(
                    joinedload(ProjectTask.project_module).joinedload(ProjectModule.project),
                    joinedload(ProjectTask.assignee),
                )
                .where(scope)
                .order_by(ProjectTask.updated_at.desc(), ProjectTask.id)
            ).unique()
        )
        automation_scope = True if user.role == "admin" else or_(
            AutomationTask.created_by_user_id == user.id,
            AutomationTask.project_id.in_(select(Project.id).where(scope)),
        )
        automation_tasks = list(
            session.scalars(
                select(AutomationTask)
                .options(joinedload(AutomationTask.project), joinedload(AutomationTask.created_by))
                .where(automation_scope)
                .order_by(AutomationTask.updated_at.desc(), AutomationTask.id)
            ).unique()
        )
        items = [_serialize_project_task(item) for item in project_tasks]
        items.extend(
            _serialize_automation_task(
                item,
                can_run=authorize_ai_capability(
                    user=user,
                    capability="project.schedule.manage",
                    project=item.project,
                ).allowed,
            )
            for item in automation_tasks
        )
        items.sort(key=lambda item: (item["updated_at"], item["id"]), reverse=True)
        return {
            "items": items,
            "total": len(items),
            "counts": {
                "project": len(project_tasks),
                "automation": len(automation_tasks),
            },
        }
    finally:
        session.close()


def create_automation_task(*, user: User, payload: dict[str, Any]) -> dict[str, Any]:
    required = {"title", "schedule_kind", "schedule_expression", "timezone", "prompt"}
    if not required <= set(payload) or set(payload) - (required | {"project_id", "source", "risk_level", "notification_policy", "requested_capabilities"}):
        raise ControlServiceError("invalid_request", "定时任务参数不完整。", 400)
    if any(not isinstance(payload[field], str) or not payload[field].strip() for field in required):
        raise ControlServiceError("invalid_request", "定时任务参数不完整。", 400)
    if payload["schedule_kind"] not in {"once", "calendar", "interval", "event"}:
        raise ControlServiceError("invalid_schedule", "不支持的调度方式。", 400)
    try:
        ZoneInfo(payload["timezone"])
    except ZoneInfoNotFoundError:
        raise ControlServiceError("invalid_timezone", "请使用有效的 IANA 时区。", 400) from None
    from fde_api.control.scheduler import next_schedule_time
    try:
        next_run_at = next_schedule_time(
            kind=payload["schedule_kind"], expression=payload["schedule_expression"],
            timezone=payload["timezone"], after=datetime.now(UTC),
        )
    except (ValueError, OverflowError):
        raise ControlServiceError("invalid_schedule", "定时表达式无效。", 400) from None
    risk_level = payload.get("risk_level", 0)
    if type(risk_level) is not int or risk_level < 0 or risk_level > 4:
        raise ControlServiceError("invalid_risk_level", "任务风险等级无效。", 400)
    source = payload.get("source", "desktop")
    if source not in {"desktop", "wechat"}:
        raise ControlServiceError("invalid_source", "任务来源无效。", 400)
    requested_capabilities = payload.get("requested_capabilities", DEFAULT_AUTOMATION_CAPABILITIES)
    if (
        not isinstance(requested_capabilities, list)
        or not requested_capabilities
        or any(not isinstance(item, str) or item not in CAPABILITY_REQUIREMENTS or item.startswith("system.") for item in requested_capabilities)
    ):
        raise ControlServiceError("invalid_capabilities", "定时任务的能力范围无效。", 400)
    requested_capabilities = list(dict.fromkeys(requested_capabilities))

    session = db.session()
    try:
        with session.begin():
            project = session.get(Project, payload.get("project_id")) if payload.get("project_id") else None
            decision = authorize_ai_capability(user=user, capability="project.schedule.manage", project=project)
            if not decision.allowed:
                raise ControlServiceError("forbidden", "当前账户无权创建该定时任务。", 403)
            if risk_level >= 3:
                raise ControlServiceError("scheduled_risk_not_allowed", "高风险操作不允许自动定时执行。", 400)
            for capability in requested_capabilities:
                decision = authorize_ai_capability(user=user, capability=capability, project=project)
                if not decision.allowed:
                    raise ControlServiceError("forbidden", "当前账户无权授予该任务所需能力。", 403)
            task = AutomationTask(
                project_id=project.id if project else None,
                created_by_user_id=user.id,
                title=payload["title"].strip()[:200],
                description="",
                source=source,
                task_type="ai",
                status="active",
                schedule_kind=payload["schedule_kind"],
                schedule_expression=payload["schedule_expression"].strip()[:255],
                timezone=payload["timezone"],
                prompt=payload["prompt"].strip(),
                requested_capabilities=requested_capabilities,
                risk_level=risk_level,
                next_run_at=next_run_at,
                notification_policy=payload.get("notification_policy") if isinstance(payload.get("notification_policy"), dict) else {},
            )
            session.add(task)
            session.flush()
            session.refresh(task)
            return _serialize_automation_task(task, can_run=True)
    finally:
        session.close()


def request_automation_run(*, user: User, task_id: str, idempotency_key: str | None) -> dict[str, Any]:
    session = db.session()
    try:
        with session.begin():
            task = session.scalar(
                select(AutomationTask)
                .options(joinedload(AutomationTask.project))
                .where(AutomationTask.id == task_id)
                .with_for_update()
            )
            if task is None:
                raise ControlServiceError("automation_not_found", "定时任务不存在。", 404)
            if task.status != "active":
                raise ControlServiceError("automation_inactive", "该任务当前不可执行。", 409)
            decision = authorize_ai_capability(user=user, capability="project.schedule.manage", project=task.project)
            if not decision.allowed:
                raise ControlServiceError("forbidden", "当前账户无权执行该任务。", 403)
            for capability in task.requested_capabilities:
                decision = authorize_ai_capability(user=user, capability=capability, project=task.project)
                if not decision.allowed:
                    raise ControlServiceError("forbidden", "当前账户已不具备该任务所需权限。", 403)
            normalized_key = (idempotency_key or f"manual:{task.id}:{uuid4()}").strip()
            if not normalized_key or len(normalized_key) > 160:
                raise ControlServiceError("invalid_idempotency_key", "幂等标识无效。", 400)
            existing = session.scalar(select(AutomationTaskRun).where(AutomationTaskRun.idempotency_key == normalized_key))
            if existing is not None:
                if existing.task_id != task.id:
                    raise ControlServiceError("idempotency_conflict", "幂等标识已被其他任务使用。", 409)
                return _serialize_automation_run(existing)
            run = AutomationTaskRun(
                task_id=task.id,
                requested_by_user_id=user.id,
                scheduled_for=datetime.now(UTC),
                status="queued",
                attempt=0,
                idempotency_key=normalized_key,
                dsh_runtime_version="",
                agent_profile_version=task.dsh_profile,
                result_summary="",
                external_execution_id="",
                output_json={},
                error_code="",
                error_message="",
            )
            session.add(run)
            session.flush()
            enqueue_outbox(session, "automation.execute", run.id, {"run_id": run.id})
            return _serialize_automation_run(run)
    finally:
        session.close()


def record_dsh_execution_event(*, run_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    allowed = {"accepted", "running", "waiting_approval", "succeeded", "failed", "cancelled"}
    status = payload.get("status")
    if status not in allowed:
        raise ControlServiceError("invalid_dsh_event", "DSH 事件状态无效。", 400)
    output = payload.get("output", {})
    if not isinstance(output, dict):
        raise ControlServiceError("invalid_dsh_event", "DSH 事件输出无效。", 400)
    session = db.session()
    try:
        with session.begin():
            run = session.get(AutomationTaskRun, run_id, with_for_update=True)
            if run is None:
                raise ControlServiceError("automation_run_not_found", "任务执行记录不存在。", 404)
            if run.status in {"succeeded", "failed", "cancelled", "skipped"}:
                return _serialize_automation_run(run)
            run.status = "running" if status == "accepted" else status
            run.external_execution_id = str(payload.get("execution_id", ""))[:120]
            run.dsh_runtime_version = str(payload.get("runtime_version", run.dsh_runtime_version))[:80]
            run.result_summary = str(payload.get("summary", ""))
            run.output_json = output
            if status == "failed":
                run.error_code = str(payload.get("error_code", "dsh_execution_failed"))[:80]
                run.error_message = str(payload.get("error_message", "DSH 任务执行失败。"))
            if status in {"succeeded", "failed", "cancelled"}:
                run.finished_at = datetime.now(UTC)
            session.flush()
            return _serialize_automation_run(run)
    finally:
        session.close()


def dsh_knowledge_for_run(*, run_id: str) -> dict[str, Any]:
    session = db.session()
    try:
        snapshot = snapshot_for_run(session, run_id)
        if snapshot is None:
            raise ControlServiceError("knowledge_snapshot_not_found", "该执行暂无可用的知识快照。", 404)
        return {
            "id": snapshot.id,
            "schema_version": snapshot.schema_version,
            "content_sha256": snapshot.content_sha256,
            "project_id": snapshot.project_id,
            "payload": snapshot.payload_json,
        }
    finally:
        session.close()


def create_dsh_approval_request(*, run_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    required = {"request_id", "capability", "tool_name", "arguments", "risk_level"}
    if set(payload) != required:
        raise ControlServiceError("invalid_approval_request", "审批请求参数无效。", 400)
    request_key = payload["request_id"]
    capability = payload["capability"]
    tool_name = payload["tool_name"]
    arguments = payload["arguments"]
    risk_level = payload["risk_level"]
    if (
        not isinstance(request_key, str)
        or not request_key.strip()
        or len(request_key) > 160
        or not isinstance(capability, str)
        or capability not in CAPABILITY_REQUIREMENTS
        or not isinstance(tool_name, str)
        or not tool_name.strip()
        or len(tool_name) > 120
        or not isinstance(arguments, dict)
        or type(risk_level) is not int
        or risk_level not in {3, 4}
        or _contains_sensitive_argument(arguments)
    ):
        raise ControlServiceError("invalid_approval_request", "审批请求参数无效。", 400)
    try:
        canonical_arguments = json.dumps(
            arguments, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
        )
    except (TypeError, ValueError):
        raise ControlServiceError("invalid_approval_request", "审批参数无法安全记录。", 400) from None
    if len(canonical_arguments.encode("utf-8")) > 64_000:
        raise ControlServiceError("invalid_approval_request", "审批参数过大。", 400)

    session = db.session()
    try:
        with session.begin():
            run = session.scalar(
                select(AutomationTaskRun)
                .options(
                    joinedload(AutomationTaskRun.task).joinedload(AutomationTask.project),
                    joinedload(AutomationTaskRun.requested_by),
                )
                .where(AutomationTaskRun.id == run_id)
                .with_for_update()
            )
            if run is None:
                raise ControlServiceError("automation_run_not_found", "任务执行记录不存在。", 404)
            existing = session.scalar(
                select(AutomationApproval).where(
                    AutomationApproval.run_id == run.id,
                    AutomationApproval.request_key == request_key.strip(),
                )
            )
            if existing is not None:
                return _serialize_approval(existing)
            if run.status not in {"running", "waiting_approval"} or run.task.project is None:
                raise ControlServiceError("approval_not_available", "当前任务不能申请操作审批。", 409)
            if capability not in run.task.requested_capabilities:
                raise ControlServiceError("capability_not_granted", "该能力未授予当前任务。", 403)
            decision = authorize_ai_capability(
                user=run.requested_by,
                capability=capability,
                project=run.task.project,
            )
            if not decision.allowed:
                raise ControlServiceError("permission_revoked", "任务发起人已不具备该操作权限。", 403)
            approval = AutomationApproval(
                run_id=run.id,
                project_id=run.task.project.id,
                requested_by_user_id=run.requested_by_user_id,
                request_key=request_key.strip(),
                capability=capability,
                tool_name=tool_name.strip(),
                arguments_json=arguments,
                arguments_sha256=sha256(canonical_arguments.encode("utf-8")).hexdigest(),
                risk_level=risk_level,
                status="pending",
                expires_at=datetime.now(UTC) + timedelta(minutes=15),
                decision_reason="",
            )
            session.add(approval)
            run.status = "waiting_approval"
            session.flush()
            return _serialize_approval(approval)
    finally:
        session.close()


def list_automation_approvals(*, user: User) -> dict[str, Any]:
    session = db.session()
    try:
        approvals = list(
            session.scalars(
                select(AutomationApproval)
                .join(Project, AutomationApproval.project_id == Project.id)
                .options(
                    joinedload(AutomationApproval.project),
                    joinedload(AutomationApproval.requested_by),
                )
                .where(_project_scope(user), AutomationApproval.status == "pending")
                .order_by(AutomationApproval.created_at.desc(), AutomationApproval.id)
            ).unique()
        )
        return {
            "items": [
                _serialize_approval(
                    approval,
                    can_review=authorize_ai_capability(
                        user=user,
                        capability=approval.capability,
                        project=approval.project,
                    ).allowed,
                )
                for approval in approvals
            ],
            "total": len(approvals),
        }
    finally:
        session.close()


def decide_automation_approval(
    *, user: User, approval_id: str, decision_value: str, password: str, reason: str
) -> dict[str, Any]:
    if decision_value not in {"approve", "reject"} or not isinstance(reason, str) or len(reason) > 500:
        raise ControlServiceError("invalid_approval_decision", "审批决定无效。", 400)
    session = db.session()
    try:
        expired = False
        result: dict[str, Any] | None = None
        with session.begin():
            approval = session.scalar(
                select(AutomationApproval)
                .options(
                    joinedload(AutomationApproval.project),
                    joinedload(AutomationApproval.run),
                )
                .where(AutomationApproval.id == approval_id)
                .with_for_update()
            )
            if approval is None:
                raise ControlServiceError("approval_not_found", "审批请求不存在。", 404)
            if approval.status != "pending":
                return _serialize_approval(approval, can_review=False)
            now = datetime.now(UTC)
            if approval.expires_at <= now:
                approval.status = "expired"
                approval.run.status = "failed"
                approval.run.error_code = "approval_expired"
                approval.run.error_message = "操作审批已过期。"
                approval.run.finished_at = now
                approval.version += 1
                session.flush()
                result = _serialize_approval(approval, can_review=False)
                expired = True
            else:
                access = authorize_ai_capability(
                    user=user,
                    capability=approval.capability,
                    project=approval.project,
                )
                if not access.allowed:
                    raise ControlServiceError("forbidden", "当前账户无权处理该审批。", 403)
                if decision_value == "approve":
                    if not isinstance(password, str):
                        raise ControlServiceError("password_required", "批准高风险操作需要验证当前密码。", 400)
                    try:
                        password_valid = verify_current_password(user, password)
                    except AuthServiceError:
                        password_valid = False
                    if not password_valid:
                        raise ControlServiceError("invalid_password", "当前密码不正确。", 400)
                    approval.status = "approved"
                    approval.run.status = "running"
                else:
                    approval.status = "rejected"
                    approval.run.status = "cancelled"
                    approval.run.error_code = "approval_rejected"
                    approval.run.error_message = "操作审批被拒绝。"
                    approval.run.finished_at = now
                approval.reviewed_by_user_id = user.id
                approval.reviewed_at = now
                approval.decision_reason = reason.strip()
                approval.version += 1
                session.flush()
                result = _serialize_approval(approval, can_review=False)
        if expired:
            raise ControlServiceError("approval_expired", "操作审批已过期。", 409)
        assert result is not None
        return result
    finally:
        session.close()


def dsh_approval_status(*, approval_id: str) -> dict[str, Any]:
    session = db.session()
    try:
        with session.begin():
            approval = session.scalar(
                select(AutomationApproval)
                .options(joinedload(AutomationApproval.run))
                .where(AutomationApproval.id == approval_id)
                .with_for_update()
            )
            if approval is None:
                raise ControlServiceError("approval_not_found", "审批请求不存在。", 404)
            if approval.status == "pending" and approval.expires_at <= datetime.now(UTC):
                approval.status = "expired"
                approval.run.status = "failed"
                approval.run.error_code = "approval_expired"
                approval.run.error_message = "操作审批已过期。"
                approval.run.finished_at = datetime.now(UTC)
            return _serialize_approval(approval, can_review=False, include_arguments=False)
    finally:
        session.close()


def execute_approved_dsh_tool(*, approval_id: str) -> dict[str, Any]:
    """Execute one allow-listed project mutation exactly once after approval."""
    session = db.session()
    try:
        with session.begin():
            approval = session.scalar(
                select(AutomationApproval)
                .options(
                    joinedload(AutomationApproval.run),
                    joinedload(AutomationApproval.project),
                    joinedload(AutomationApproval.requested_by),
                )
                .where(AutomationApproval.id == approval_id)
                .with_for_update()
            )
            if approval is None:
                raise ControlServiceError("approval_not_found", "审批请求不存在。", 404)
            if approval.status == "executed":
                return _serialize_approval(approval, can_review=False, include_arguments=False)
            if approval.status != "approved":
                raise ControlServiceError("approval_not_approved", "该操作尚未获批。", 409)

            canonical_arguments = json.dumps(
                approval.arguments_json,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            )
            if sha256(canonical_arguments.encode("utf-8")).hexdigest() != approval.arguments_sha256:
                raise ControlServiceError("approval_integrity_failed", "审批参数完整性校验失败。", 409)
            access = authorize_ai_capability(
                user=approval.requested_by,
                capability=approval.capability,
                project=approval.project,
            )
            if not access.allowed:
                raise ControlServiceError("permission_revoked", "任务发起人已不具备该操作权限。", 403)

            if approval.capability != "task.batch_assign" or approval.tool_name != "project_tasks.batch_assign":
                raise ControlServiceError("tool_not_allowed", "该 DSH 工具未在工作台启用。", 403)
            arguments = _batch_assign_arguments(approval.arguments_json)
            try:
                result = batch_assign_project_tasks_in_session(
                    session=session,
                    actor=approval.requested_by,
                    project_id=approval.project_id,
                    member_user_id=arguments["member_user_id"],
                    mode=arguments["mode"],
                    assignments=arguments["assignments"],
                )
            except ProjectServiceError as error:
                raise ControlServiceError(error.code, error.message, error.status) from error

            approval.status = "executed"
            approval.executed_at = datetime.now(UTC)
            approval.result_json = result
            approval.version += 1
            session.flush()
            return _serialize_approval(approval, can_review=False, include_arguments=False)
    finally:
        session.close()


def _batch_assign_arguments(arguments: dict[str, Any]) -> dict[str, Any]:
    if set(arguments) != {"member_user_id", "mode", "assignments"}:
        raise ControlServiceError("invalid_tool_arguments", "批量分配任务参数无效。", 400)
    member_user_id = arguments["member_user_id"]
    mode = arguments["mode"]
    assignments = arguments["assignments"]
    if (
        not isinstance(member_user_id, str)
        or not member_user_id
        or mode not in {"assignee", "collaborator"}
        or not isinstance(assignments, list)
        or not assignments
    ):
        raise ControlServiceError("invalid_tool_arguments", "批量分配任务参数无效。", 400)
    normalized: list[dict[str, Any]] = []
    for item in assignments:
        if (
            not isinstance(item, dict)
            or set(item) != {"task_id", "version"}
            or not isinstance(item["task_id"], str)
            or not item["task_id"]
            or type(item["version"]) is not int
            or item["version"] < 1
        ):
            raise ControlServiceError("invalid_tool_arguments", "批量分配任务参数无效。", 400)
        normalized.append({"task_id": item["task_id"], "version": item["version"]})
    return {"member_user_id": member_user_id, "mode": mode, "assignments": normalized}


def _project_scope(user: User):
    if user.role == "admin":
        return Project.id.is_not(None)
    return or_(
        Project.leader_user_id == user.id,
        Project.id.in_(select(ProjectMember.project_id).where(ProjectMember.user_id == user.id)),
    )


def _serialize_account_user(user: User) -> dict[str, Any]:
    return {"id": user.id, "username": user.username, "display_name": user.display_name, "role": user.role, "is_active": user.is_active}


def _serialize_binding(binding: ChannelBinding | None) -> dict[str, Any]:
    if binding is None:
        return {"status": "unbound", "channel": "wechat_clawbot", "commands_enabled": False, "notifications_enabled": False}
    return {
        "id": binding.id,
        "channel": binding.channel,
        "status": binding.status,
        "display_name": binding.channel_display_name,
        "default_project_id": binding.default_project_id,
        "commands_enabled": binding.commands_enabled,
        "notifications_enabled": binding.notifications_enabled,
        "binding_expires_at": binding.binding_expires_at.isoformat() if binding.binding_expires_at else None,
        "last_seen_at": binding.last_seen_at.isoformat() if binding.last_seen_at else None,
        "version": binding.version,
    }


def _serialize_project_task(task: ProjectTask) -> dict[str, Any]:
    project = task.project_module.project
    return {
        "id": task.id,
        "kind": "project",
        "source": "workbench",
        "title": task.name,
        "description": task.description,
        "status": task.status,
        "project_id": project.id,
        "project_name": project.name,
        "assignee_name": task.assignee.display_name if task.assignee else "",
        "schedule": {"kind": "project_dates", "expression": f"{task.planned_start_date.isoformat()} / {task.planned_end_date.isoformat()}"},
        "next_run_at": None,
        "updated_at": task.updated_at.isoformat(),
    }


def _serialize_automation_task(task: AutomationTask, *, can_run: bool = False) -> dict[str, Any]:
    return {
        "id": task.id,
        "kind": "automation",
        "source": task.source,
        "title": task.title,
        "description": task.description,
        "status": task.status,
        "project_id": task.project_id,
        "project_name": task.project.name if task.project else "",
        "assignee_name": "DSH",
        "schedule": {"kind": task.schedule_kind, "expression": task.schedule_expression, "timezone": task.timezone},
        "next_run_at": task.next_run_at.isoformat() if task.next_run_at else None,
        "updated_at": task.updated_at.isoformat(),
        "risk_level": task.risk_level,
        "requested_capabilities": task.requested_capabilities,
        "can_run": can_run and task.status == "active",
    }


def _serialize_automation_run(run: AutomationTaskRun) -> dict[str, Any]:
    return {
        "id": run.id,
        "task_id": run.task_id,
        "status": run.status,
        "scheduled_for": run.scheduled_for.isoformat(),
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "finished_at": run.finished_at.isoformat() if run.finished_at else None,
        "runtime_version": run.dsh_runtime_version,
        "external_execution_id": run.external_execution_id,
        "summary": run.result_summary,
        "error": {"code": run.error_code, "message": run.error_message} if run.error_code else None,
    }


def _serialize_approval(
    approval: AutomationApproval,
    *,
    can_review: bool = False,
    include_arguments: bool = True,
) -> dict[str, Any]:
    data = {
        "id": approval.id,
        "run_id": approval.run_id,
        "project_id": approval.project_id,
        "project_name": approval.project.name if "project" in approval.__dict__ else "",
        "requested_by_name": approval.requested_by.display_name if "requested_by" in approval.__dict__ else "",
        "capability": approval.capability,
        "tool_name": approval.tool_name,
        "arguments_sha256": approval.arguments_sha256,
        "risk_level": approval.risk_level,
        "status": approval.status,
        "expires_at": approval.expires_at.isoformat(),
        "reviewed_at": approval.reviewed_at.isoformat() if approval.reviewed_at else None,
        "executed_at": approval.executed_at.isoformat() if approval.executed_at else None,
        "decision_reason": approval.decision_reason,
        "result": approval.result_json if approval.status == "executed" else None,
        "can_review": can_review and approval.status == "pending",
    }
    if include_arguments:
        data["arguments"] = approval.arguments_json
    return data


def _contains_sensitive_argument(value: Any) -> bool:
    if isinstance(value, dict):
        return any(
            _SENSITIVE_ARGUMENT_KEY.search(str(key))
            or _contains_sensitive_argument(child)
            for key, child in value.items()
        )
    if isinstance(value, list):
        return any(_contains_sensitive_argument(item) for item in value)
    return False
