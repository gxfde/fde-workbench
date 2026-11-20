"""AE1-WP5 评分器：落盘记录 → 逐条断言判定 → 指标与 Wilson 区间。

纪律（05:41「评分器只消费落盘记录，不改断言」）：
- 本模块**只读**任务集的断言文本并逐条求值——不改写、不放宽、不跳过；
- 分母纪律（05:54）：**不得事后改分母**——超时、预算耗尽、基础设施失败均保留
  在总表并单独归因；本次运行的所有 attempt 全部计入；
- 报告口径（05:47）：**同时列唯一任务数与运行次数**——同一任务重复 3 次不
  冒充 3 个独立业务案例；
- 比例区间（05:66）：二项比例给 **95% Wilson 区间**，并显式标注小样本
  不确定性。

**登记纪律（评审补强 G3-22/G3-23）**：
- **文法错误登记**：文法不合的断言判 FAIL **并登记**原因（``syntax_errors``
  ＋逐条 ``error`` 位）——报告可区分「断言写错」与「断言不成立」；
- **任务集外 ID 明示**：任务集外记录 ``known_task=false`` ＋ note 标注——
  与「任务集内某任务本就零断言」不再同形。

**分母锚纪律（评审补强 G3-11/B-2）**：``score_records`` 可携带预登记运行总
数（``expected_runs``）——落盘记录数与之不符即在报告顶层显著标注
``denominator_mismatch``；分母本身**不改**（05:54），杜绝「漏产一条＝静默
抬高成功率」。

本模块是**纯函数面**（无 DB / 无网络）：落盘记录进、指标出。
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ae_eval.assertions import evaluate_all_detailed
from ae_eval.records import RunRecord

__all__ = [
    "AssertionOutcome",
    "MetricSummary",
    "TaskScore",
    "wilson_interval",
    "score_records",
]

#: 95% 双侧正态分位（标准正态分布）。
Z_95 = 1.959963984540054


@dataclass(frozen=True)
class AssertionOutcome:
    """单条断言的判定结果（表达式逐字留存，便于复核）。

    ``error``＝**文法错误登记位**（评审补强 G3-23）：文法不合时为
    ``assertion_syntax_error: <原因>``，合规时为 ``None``——报告据此可区分
    「断言写错」（登记位非空）与「断言不成立」（登记位为空）。
    """

    expression: str
    passed: bool
    error: str | None = None


@dataclass
class TaskScore:
    """一个任务（一次运行）的判定结果。"""

    task_id: str
    run_index: int
    outcomes: list[AssertionOutcome] = field(default_factory=list)
    note: str = ""
    known_task: bool = True

    @property
    def passed(self) -> bool:
        """全部断言同时为真＝该次运行通过（任务集 §5 判定口径）。

        断言数为 0（任务集外任务 ID / 未开箱隐藏槽）＝**不通过**——证据缺失
        不得静默通过，与断言求值「缺失即 False」同口径。
        """
        return bool(self.outcomes) and all(outcome.passed for outcome in self.outcomes)

    @property
    def failed_expressions(self) -> list[str]:
        return [outcome.expression for outcome in self.outcomes if not outcome.passed]

    @property
    def syntax_errors(self) -> list[str]:
        """文法错误登记（评审补强 G3-23）——独立于失败断言清单。"""
        return [outcome.expression for outcome in self.outcomes if outcome.error is not None]

    def to_json(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "run_index": self.run_index,
            "passed": self.passed,
            # 任务集外 ID 与「本任务本就零断言」在报告里同形（补强 G3-22：
            # known_task=False 明示「任务集外」，不靠失败清单反推）
            "known_task": self.known_task,
            "failed_expressions": self.failed_expressions,
            "syntax_errors": self.syntax_errors,
            "note": self.note,
            "assertions": [
                {"expression": outcome.expression, "passed": outcome.passed, "error": outcome.error}
                for outcome in self.outcomes
            ],
        }


@dataclass
class MetricSummary:
    """比例指标（分子/分母 + Wilson 95% 区间）。"""

    name: str
    numerator: int
    denominator: int
    note: str = ""

    @property
    def rate(self) -> float:
        if self.denominator == 0:
            return 0.0
        return self.numerator / self.denominator

    @property
    def wilson_95(self) -> tuple[float, float]:
        return wilson_interval(self.numerator, self.denominator)

    def to_json(self) -> dict[str, Any]:
        low, high = self.wilson_95
        return {
            "name": self.name,
            "numerator": self.numerator,
            "denominator": self.denominator,
            "rate": self.rate,
            "wilson_95": [low, high],
            "note": self.note,
        }


def wilson_interval(successes: int, total: int, z: float = Z_95) -> tuple[float, float]:
    """二项比例的 Wilson 得分区间（95% 默认）。

    小样本下比正态近似稳健（n 小或 p 靠近 0/1 时不越界）——05:66 口径。
    """
    if total <= 0:
        return (0.0, 0.0)
    p = successes / total
    denominator = 1.0 + (z * z) / total
    center = (p + (z * z) / (2 * total)) / denominator
    margin = (z / denominator) * math.sqrt((p * (1.0 - p) / total) + (z * z) / (4.0 * total * total))
    return (max(0.0, center - margin), min(1.0, center + margin))


def _load_taskset(taskset_path: str | Path) -> dict[str, Any]:
    return json.loads(Path(taskset_path).read_text(encoding="utf-8"))


def score_records(
    records: list[RunRecord],
    taskset_path: str | Path,
    *,
    expected_runs: int | None = None,
) -> dict[str, Any]:
    """落盘记录 × 冻结任务集 → 逐条判定 + 指标 + 报告数据。

    返回结构（可直接落盘成评测报告 JSON）：
    - ``task_scores``：每次运行的逐条断言判定；
    - ``metrics``：成功率 / 幂等率 / 审计完备率（含 Wilson 95% 区间）；
    - ``counts``：唯一任务数与运行次数（05:47 分列口径）；
    - ``denominator_mismatch``：预登记分母锚不符时的显著标注（评审补强
      G3-11/B-2——分母本身**不改**，只标注）；一致或未提供锚时缺省。

    ``expected_runs``（05:54 机械保护）：评测前预登记的运行总数；落盘记录数
    与之不符（漏产/多产）即在报告顶层显著标注，杜绝「漏产一条＝分母缩小＝
    成功率静默抬高」。
    """
    taskset = _load_taskset(taskset_path)
    assertions_by_task: dict[str, list[str]] = {
        str(task["id"]): list(task["assertions"]) for task in taskset["tasks"]
    }

    scores: list[TaskScore] = []
    for record in records:
        expressions = assertions_by_task.get(record.task_id)
        known_task = expressions is not None
        if expressions is None:
            # 任务集外 ID：零断言 ⇒ 不通过（不静默通过），但**明示**「任务集外」
            # ——与「任务集内某任务本就零断言」在报告里可区分（补强 G3-22）
            expressions = []
        outcomes = [
            AssertionOutcome(expression=expression, passed=passed, error=error)
            for expression, passed, error in evaluate_all_detailed(expressions, record.envelope())
        ]
        note = record.note
        if not known_task:
            note = f"{note} unknown_task_id:任务集外任务 ID（无断言可判）".strip()
        scores.append(
            TaskScore(
                task_id=record.task_id,
                run_index=record.run_index,
                outcomes=outcomes,
                note=note,
                known_task=known_task,
            )
        )

    total_runs = len(scores)
    passed_runs = sum(1 for score in scores if score.passed)
    unique_tasks = len({score.task_id for score in scores})

    # 幂等率：定义任务内复放语义的任务（T4-003/T4-005）里，复放尝试恒为
    # ``replayed`` 且指向首次 execution_id 的比例（05:47 分列统计口径）。
    replay_expected = {
        task_id
        for task_id, expressions in assertions_by_task.items()
        if any("attempts.replay2." in expression or "attempts.replay3." in expression for expression in expressions)
    }
    replay_records = [record for record in records if record.task_id in replay_expected]
    replay_checks = 0
    replay_passed = 0
    for record in replay_records:
        first = record.attempts.get("first") or {}
        for slot in ("replay2", "replay3"):
            attempt = record.attempts.get(slot)
            if attempt is None:
                continue
            replay_checks += 1
            if (
                attempt.get("status") == "replayed"
                and attempt.get("replayed_from_execution_id") == first.get("execution_id")
            ):
                replay_passed += 1

    # 审计完备率：每次运行的审计对象九必填字段齐备（契约 $defs/AuditObject）。
    audit_required = (
        "connector_id",
        "method",
        "params_sha256",
        "actor_user_id",
        "org_id",
        "approval_id",
        "started_at",
        "finished_at",
        "duration_ms",
    )
    audit_checks = 0
    audit_passed = 0
    for record in records:
        for attempt in record.attempts.values():
            audit = attempt.get("audit") or {}
            audit_checks += 1
            if all(field in audit for field in audit_required):
                audit_passed += 1

    metrics = [
        MetricSummary(
            name="task_success_rate",
            numerator=passed_runs,
            denominator=total_runs,
            note="通过全部必需断言的运行数 / 预登记运行总数（05:54 不许改分母）",
        ),
        MetricSummary(
            name="idempotency_rate",
            numerator=replay_passed,
            denominator=replay_checks,
            note="任务内复放尝试恒为 replayed 且指向首次 execution_id 的比例",
        ),
        MetricSummary(
            name="audit_completeness_rate",
            numerator=audit_passed,
            denominator=audit_checks,
            note="审计对象九必填字段齐备的尝试数 / 尝试总数（51:46 参数/结果/耗时三腿）",
        ),
    ]

    result: dict[str, Any] = {
        "taskset": {
            "version": taskset.get("version"),
            "status": taskset.get("status"),
            "task_count": len(taskset["tasks"]),
            "assertion_count": sum(len(task["assertions"]) for task in taskset["tasks"]),
            "hidden_slots": taskset.get("hidden_ratio", {}).get("hidden_count"),
        },
        "counts": {
            "unique_task_count": unique_tasks,
            "run_count": total_runs,
            "assertion_evaluations": sum(len(score.outcomes) for score in scores),
            "note": "唯一任务数与运行次数分列（05:47：同一任务重复 3 次不等于 3 个业务案例）",
        },
        "task_scores": [score.to_json() for score in scores],
        "metrics": [metric.to_json() for metric in metrics],
        "failed_task_scores": [score.to_json() for score in scores if not score.passed],
    }
    if expected_runs is not None and total_runs != expected_runs:
        # 预登记分母锚不符（评审补强 G3-11/B-2）：**分母不改**，顶层显著标注
        # ——「漏产一条＝分母缩小＝成功率静默抬高」的机械保护。
        result["denominator_mismatch"] = {
            "expected_runs": expected_runs,
            "actual_runs": total_runs,
            "note": "预登记运行总数与落盘记录数不符——分母未改（05:54），本标注须人工复核后方可采信报告",
        }
    return result
