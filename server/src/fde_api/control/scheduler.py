from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select

from fde_api.control.models import AutomationTask, AutomationTaskRun
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
