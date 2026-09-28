from datetime import date

import pytest

from fde_api.workbench.scheduling import (
    ScheduleTask,
    ScheduledTask,
    SchedulingError,
    reschedule_descendants,
    schedule_tasks,
    validate_acyclic,
)


def test_schedule_skips_weekend_and_uses_latest_dependency():
    tasks = [
        ScheduleTask("a", 2, ()),
        ScheduleTask("b", 1, ()),
        ScheduleTask("c", 2, ("a", "b")),
    ]

    result = schedule_tasks(tasks, date(2026, 8, 21))  # Friday

    assert result["a"] == ScheduledTask("a", date(2026, 8, 21), date(2026, 8, 24))
    assert result["c"] == ScheduledTask("c", date(2026, 8, 25), date(2026, 8, 26))


def test_schedule_normalizes_a_weekend_start_to_monday():
    result = schedule_tasks([ScheduleTask("a", 1, ())], date(2026, 8, 22))

    assert result["a"] == ScheduledTask("a", date(2026, 8, 24), date(2026, 8, 24))


def test_schedule_orders_independent_tasks_by_key():
    result = schedule_tasks(
        [ScheduleTask("z", 1, ()), ScheduleTask("a", 1, ())],
        date(2026, 8, 21),
    )

    assert list(result) == ["a", "z"]


def test_invalid_duration_is_rejected():
    with pytest.raises(SchedulingError) as error:
        schedule_tasks([ScheduleTask("a", 0, ())], date(2026, 8, 21))

    assert error.value.code == "invalid_duration"


def test_missing_dependency_is_rejected():
    with pytest.raises(SchedulingError) as error:
        validate_acyclic([ScheduleTask("a", 1, ("missing",))])

    assert error.value.code == "missing_dependency"


def test_cycle_is_rejected():
    with pytest.raises(SchedulingError, match="cycle") as error:
        schedule_tasks(
            [ScheduleTask("a", 1, ("b",)), ScheduleTask("b", 1, ("a",))],
            date(2026, 8, 21),
        )

    assert error.value.code == "cyclic_dependency"


def test_reschedule_descendants_keeps_unrelated_dates():
    tasks = [
        ScheduleTask("a", 2, ()),
        ScheduleTask("child", 1, ("a",)),
        ScheduleTask("grandchild", 1, ("child",)),
        ScheduleTask("unrelated", 1, ()),
    ]
    existing = {
        "a": ScheduledTask("a", date(2026, 8, 21), date(2026, 8, 26)),
        "child": ScheduledTask("child", date(2026, 8, 25), date(2026, 8, 25)),
        "grandchild": ScheduledTask(
            "grandchild", date(2026, 8, 26), date(2026, 8, 26)
        ),
        "unrelated": ScheduledTask(
            "unrelated", date(2026, 8, 24), date(2026, 8, 24)
        ),
    }

    updated = reschedule_descendants(existing, tasks, changed_keys={"a"})

    assert updated["a"] == existing["a"]
    assert updated["unrelated"] == existing["unrelated"]
    assert updated["child"] == ScheduledTask(
        "child", date(2026, 8, 27), date(2026, 8, 27)
    )
    assert updated["grandchild"] == ScheduledTask(
        "grandchild", date(2026, 8, 28), date(2026, 8, 28)
    )
