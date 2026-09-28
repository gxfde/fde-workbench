"""Deterministic weekday scheduling for template and project tasks."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
import heapq
from typing import Iterable, Mapping


@dataclass(frozen=True, slots=True)
class ScheduleTask:
    key: str
    duration_days: int
    dependency_keys: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ScheduledTask:
    key: str
    start_date: date
    end_date: date


class SchedulingError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def normalize_workday(value: date) -> date:
    """Return ``value`` or the following Monday when it is a weekend."""
    while value.weekday() >= 5:
        value += timedelta(days=1)
    return value


def add_workdays(start: date, days: int) -> date:
    """Return the final date when ``start`` is counted as workday one."""
    current = normalize_workday(start)
    remaining = days - 1
    while remaining:
        current += timedelta(days=1)
        if current.weekday() < 5:
            remaining -= 1
    return current


def validate_acyclic(tasks: Iterable[ScheduleTask]) -> None:
    """Reject invalid task durations, dependency references, and cycles."""
    _topological_order(tasks)


def schedule_tasks(
    tasks: Iterable[ScheduleTask], start_date: date
) -> dict[str, ScheduledTask]:
    """Schedule all tasks in dependency order using weekdays only."""
    task_list = tuple(tasks)
    tasks_by_key = _tasks_by_key(task_list)
    order = _topological_order(task_list)
    baseline = normalize_workday(start_date)
    scheduled: dict[str, ScheduledTask] = {}

    for key in order:
        task = tasks_by_key[key]
        task_start = baseline
        if task.dependency_keys:
            latest_end = max(
                scheduled[dependency].end_date for dependency in task.dependency_keys
            )
            task_start = _next_workday(latest_end)
        scheduled[key] = ScheduledTask(
            key=key,
            start_date=task_start,
            end_date=add_workdays(task_start, task.duration_days),
        )

    return scheduled


def reschedule_descendants(
    existing: Mapping[str, ScheduledTask],
    tasks: Iterable[ScheduleTask],
    changed_keys: set[str],
) -> dict[str, ScheduledTask]:
    """Recalculate only the descendants of manually changed task schedules."""
    task_list = tuple(tasks)
    tasks_by_key = _tasks_by_key(task_list)
    order = _topological_order(task_list)
    _require_scheduled_tasks(existing, tasks_by_key)

    unknown_changed = changed_keys - tasks_by_key.keys()
    if unknown_changed:
        raise KeyError(f"Unknown changed task keys: {', '.join(sorted(unknown_changed))}")

    descendants = _descendant_keys(tasks_by_key, changed_keys)
    updated = dict(existing)
    for key in order:
        if key not in descendants:
            continue
        task = tasks_by_key[key]
        latest_end = max(updated[dependency].end_date for dependency in task.dependency_keys)
        task_start = _next_workday(latest_end)
        updated[key] = ScheduledTask(
            key=key,
            start_date=task_start,
            end_date=add_workdays(task_start, task.duration_days),
        )

    return updated


def _tasks_by_key(tasks: tuple[ScheduleTask, ...]) -> dict[str, ScheduleTask]:
    tasks_by_key = {task.key: task for task in tasks}
    if len(tasks_by_key) != len(tasks):
        raise ValueError("Task keys must be unique")
    return tasks_by_key


def _topological_order(tasks: Iterable[ScheduleTask]) -> list[str]:
    task_list = tuple(tasks)
    tasks_by_key = _tasks_by_key(task_list)
    dependents: dict[str, list[str]] = defaultdict(list)
    indegree = {key: 0 for key in tasks_by_key}

    for task in task_list:
        if (
            not isinstance(task.duration_days, int)
            or isinstance(task.duration_days, bool)
            or task.duration_days < 1
        ):
            raise SchedulingError(
                "invalid_duration",
                f"Task '{task.key}' must have a positive whole-day duration",
            )
        for dependency in task.dependency_keys:
            if dependency not in tasks_by_key:
                raise SchedulingError(
                    "missing_dependency",
                    f"Task '{task.key}' depends on missing task '{dependency}'",
                )
            dependents[dependency].append(task.key)
            indegree[task.key] += 1

    ready = [key for key, count in indegree.items() if count == 0]
    heapq.heapify(ready)
    order: list[str] = []
    while ready:
        key = heapq.heappop(ready)
        order.append(key)
        for dependent in sorted(dependents[key]):
            indegree[dependent] -= 1
            if indegree[dependent] == 0:
                heapq.heappush(ready, dependent)

    if len(order) != len(task_list):
        raise SchedulingError("cyclic_dependency", "Task dependency cycle detected")
    return order


def _next_workday(value: date) -> date:
    return normalize_workday(value + timedelta(days=1))


def _descendant_keys(
    tasks_by_key: Mapping[str, ScheduleTask], changed_keys: set[str]
) -> set[str]:
    dependents: dict[str, list[str]] = defaultdict(list)
    for task in tasks_by_key.values():
        for dependency in task.dependency_keys:
            dependents[dependency].append(task.key)

    descendants: set[str] = set()
    pending = list(changed_keys)
    while pending:
        key = pending.pop()
        for dependent in dependents[key]:
            if dependent not in descendants and dependent not in changed_keys:
                descendants.add(dependent)
                pending.append(dependent)
    return descendants


def _require_scheduled_tasks(
    existing: Mapping[str, ScheduledTask], tasks_by_key: Mapping[str, ScheduleTask]
) -> None:
    missing = sorted(set(tasks_by_key) - existing.keys())
    if missing:
        raise KeyError(f"Missing existing schedules for: {', '.join(missing)}")
