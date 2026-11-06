from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select

from fde_api.control.models import AutomationApproval, AutomationTask, AutomationTaskRun
from fde_api.extensions import db
from fde_api.jobs.outbox import enqueue_outbox


_INTERVAL = re.compile(r"^(\d{1,6})([mhd])$")


def next_schedule_time(*, kind: str, expression: str, timezone: str, after: datetime) -> datetime | None:
    zone = ZoneInfo(timezone)
    if after.tzinfo is None:
        after = after.replace(tzinfo=UTC)
    if kind == "event":
        return None
    if kind == "once":
        try:
            value = datetime.fromisoformat(expression)
        except ValueError as error:
            raise ValueError("invalid_once_schedule") from error
        if value.tzinfo is None:
            value = value.replace(tzinfo=zone)
        return value.astimezone(UTC)
    if kind == "interval":
        match = _INTERVAL.fullmatch(expression.strip())
        if match is None:
            raise ValueError("invalid_interval_schedule")
        amount = int(match.group(1))
        if amount < 1:
            raise ValueError("invalid_interval_schedule")
        delta = {"m": timedelta(minutes=amount), "h": timedelta(hours=amount), "d": timedelta(days=amount)}[match.group(2)]
        return after.astimezone(UTC) + delta
    if kind != "calendar":
        raise ValueError("invalid_schedule_kind")
    fields = expression.split()
    if len(fields) != 5:
        raise ValueError("invalid_calendar_schedule")
    minute, hour, day, month, weekday = (
        _cron_values(fields[0], 0, 59), _cron_values(fields[1], 0, 23),
        _cron_values(fields[2], 1, 31), _cron_values(fields[3], 1, 12), _cron_values(fields[4], 0, 7),
    )
    weekday = {0 if value == 7 else value for value in weekday}
    cursor = after.astimezone(zone).replace(second=0, microsecond=0) + timedelta(minutes=1)
    for _ in range(60 * 24 * 366 * 2):
        cron_weekday = (cursor.weekday() + 1) % 7
        day_match = cursor.day in day
        weekday_match = cron_weekday in weekday
        day_allowed = (day_match or weekday_match) if fields[2] != "*" and fields[4] != "*" else day_match and weekday_match
        if cursor.minute in minute and cursor.hour in hour and cursor.month in month and day_allowed:
            return cursor.astimezone(UTC)
        cursor += timedelta(minutes=1)
    raise ValueError("calendar_schedule_too_sparse")


def dispatch_due_automations(*, now: datetime | None = None, limit: int = 100) -> int:
    current = (now or datetime.now(UTC)).astimezone(UTC)
    session = db.session()
    dispatched = 0
    try:
        with session.begin():
            tasks = list(session.scalars(
                select(AutomationTask)
                .where(AutomationTask.status == "active", AutomationTask.next_run_at.is_not(None), AutomationTask.next_run_at <= current)
                .order_by(AutomationTask.next_run_at, AutomationTask.id)
                .with_for_update(skip_locked=True)
                .limit(limit)
            ))
            for task in tasks:
                scheduled_for = task.next_run_at
                key = f"schedule:{task.id}:{scheduled_for.isoformat()}"
                existing = session.scalar(select(AutomationTaskRun).where(AutomationTaskRun.idempotency_key == key))
                if existing is None:
                    run = AutomationTaskRun(
                        task_id=task.id, requested_by_user_id=task.created_by_user_id, scheduled_for=scheduled_for,
                        status="queued", attempt=0, idempotency_key=key, dsh_runtime_version="",
                        agent_profile_version=task.dsh_profile, result_summary="", external_execution_id="",
                        output_json={}, error_code="", error_message="",
                    )
                    session.add(run)
                    session.flush()
                    enqueue_outbox(session, "automation.execute", run.id, {"run_id": run.id})
                    dispatched += 1
                task.last_run_at = scheduled_for
                task.next_run_at = next_schedule_time(kind=task.schedule_kind, expression=task.schedule_expression, timezone=task.timezone, after=scheduled_for) if task.schedule_kind != "once" else None
        return dispatched
    finally:
        session.close()


def sweep_expired_approvals(*, now: datetime | None = None, limit: int = 100) -> int:
    """过期审批后台清扫（V3 T-P1-5 / WB-DEF-3）。

    此前过期翻转只有两处惰性判定（decide 拍板时 / dsh 状态查询时），无人
    触碰的过期审批永远停在 pending——任务中心一直显示可拍。本清扫与调度
    循环同拍（cli scheduler 命令），批量把 pending+过期行经唯一翻转原语
    ``_expire_approval`` 落 expired（与拍板时的惰性判定完全同语义）。
    返回本轮翻转数；skip_locked 与并发拍板互不阻塞。
    """
    from fde_api.control.service import _expire_approval  # 延迟导入防环（service 反向依赖调度面）

    current = (now or datetime.now(UTC)).astimezone(UTC)
    session = db.session()
    try:
        with session.begin():
            approvals = list(session.scalars(
                select(AutomationApproval)
                .where(AutomationApproval.status == "pending", AutomationApproval.expires_at <= current)
                .order_by(AutomationApproval.expires_at, AutomationApproval.id)
                .with_for_update(skip_locked=True)
                .limit(limit)
            ))
            for approval in approvals:
                _expire_approval(session, approval, reviewer=None, now=current)
            return len(approvals)
    finally:
        session.close()


# B#5 审批退避提醒：pending 挂起按 10m→1h→4h→24h 退避序列升级提醒计数，
# 留痕只进 approval.result_json["approval_reminders"]（零迁移）——呈现面=
# 任务中心审批列表（pending_seconds / reminder_count / next_reminder_at），
# 复用任务中心，勿新开外发通道（红线：不经微信/邮件主动推送）。
APPROVAL_REMINDER_BACKOFF_MINUTES = (10, 60, 240, 1440)


def remind_pending_approvals(*, now: datetime | None = None, limit: int = 100) -> int:
    """挂起审批退避提醒（V3 P0 先行批 B#5）。

    与派单/过期清扫同拍（cli scheduler 循环）。对每条 pending 审批按
    ``created_at`` 起算的退避序列补发已到期等级（catch-up：一次 sweep 可
    连升多级，如过夜后直达 4 级），账本 = result_json["approval_reminders"]
    追加 {level, due_at, issued_at}；已发等级幂等不重发；非 pending 零触碰
    （与 _expire_approval 判定域互斥，skip_locked 与并发拍板互不阻塞）。
    返回本轮发出的提醒条数（非审批条数）。
    """
    current = (now or datetime.now(UTC)).astimezone(UTC)
    session = db.session()
    issued = 0
    try:
        with session.begin():
            approvals = list(session.scalars(
                select(AutomationApproval)
                .where(AutomationApproval.status == "pending")
                .order_by(AutomationApproval.created_at, AutomationApproval.id)
                .with_for_update(skip_locked=True)
                .limit(limit)
            ))
            for approval in approvals:
                ledger = list((approval.result_json or {}).get("approval_reminders") or [])
                age_minutes = (current - approval.created_at).total_seconds() / 60
                while len(ledger) < len(APPROVAL_REMINDER_BACKOFF_MINUTES) and age_minutes >= APPROVAL_REMINDER_BACKOFF_MINUTES[len(ledger)]:
                    level = len(ledger) + 1
                    due_at = approval.created_at + timedelta(
                        minutes=APPROVAL_REMINDER_BACKOFF_MINUTES[level - 1]
                    )
                    ledger.append(
                        {
                            "level": level,
                            "due_at": due_at.isoformat(),
                            "issued_at": current.isoformat(),
                        }
                    )
                    issued += 1
                if ledger:
                    # JSON 列变更检测需整体重赋值（原地 append 不触发 UPDATE）
                    approval.result_json = {
                        **(approval.result_json or {}),
                        "approval_reminders": ledger,
                    }
            return issued
    finally:
        session.close()


def _cron_values(field: str, minimum: int, maximum: int) -> set[int]:
    values: set[int] = set()
    for part in field.split(","):
        step = 1
        if "/" in part:
            part, step_text = part.split("/", 1)
            step = int(step_text)
            if step < 1:
                raise ValueError("invalid_cron_step")
        if part == "*":
            start, end = minimum, maximum
        elif "-" in part:
            start_text, end_text = part.split("-", 1)
            start, end = int(start_text), int(end_text)
        else:
            start = end = int(part)
        if start < minimum or end > maximum or start > end:
            raise ValueError("invalid_cron_range")
        values.update(range(start, end + 1, step))
    if not values:
        raise ValueError("empty_cron_field")
    return values
