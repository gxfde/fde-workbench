"""AE1-WP5 评测记录（落盘记录形态）——观测包络的数据载体。

对齐 `_ae-tasks-v1.md` §4 观测包络：契约字段原样取 ``_ae-execution-contract-v1.json``
的 ``$defs/ActionExecutionResult``（``attempts.first`` 等），另加两类派生/观测
字段（``task.total_cost_usd`` 评分器派生、``task.external_state.*`` harness 观测）。

纪律（05:41「评分器只消费落盘记录，不改断言」）：
- 本模块**只存**运行记录，**不改**任务集断言文本；
- 记录可 JSON 往返（``to_json`` / ``from_json``）——落盘与再消费同形态，
  避免「跑时一套、判时另一套」的错位；
- ``total_cost_usd`` 恒由 attempts 的 ``cost.estimated_usd`` 求和派生
  （§4「评分器派生：Σ attempts.*.cost.estimated_usd」），不独立录入。
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

__all__ = ["RunRecord", "load_records", "write_records"]


@dataclass
class RunRecord:
    """一次任务运行的落盘记录。"""

    task_id: str
    run_index: int
    #: ``{"first": <ActionExecutionResult>, "replay2": ..., "replay3": ...}``
    #: ——``replay2``/``replay3`` 仅任务定义了任务内复放语义时存在（T4-003/T4-005，
    #: 任务集 §4「仅 T4-003 / T4-005 存在」）。
    attempts: dict[str, dict[str, Any]] = field(default_factory=dict)
    #: harness 对外部系统状态的只读快照（键由任务声明，见任务集断言的
    #: ``task.external_state.*`` 绑定）。
    external_state: dict[str, Any] = field(default_factory=dict)
    #: 运行备注（非断言输入；如失败归因、基础设施错误说明）。
    note: str = ""

    @property
    def total_cost_usd(self) -> float:
        """``Σ attempts.*.cost.estimated_usd``（§4 派生口径）。"""
        total = 0.0
        for result in self.attempts.values():
            cost = result.get("cost") or {}
            total += float(cost.get("estimated_usd") or 0.0)
        return total

    def envelope(self) -> dict[str, Any]:
        """评分用观测包络（形状对齐任务集 §4）。"""
        return {
            "attempts": self.attempts,
            "task": {
                "total_cost_usd": self.total_cost_usd,
                "external_state": dict(self.external_state),
            },
        }

    def to_json(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "run_index": self.run_index,
            "attempts": self.attempts,
            "external_state": self.external_state,
            "total_cost_usd": self.total_cost_usd,
            "note": self.note,
        }

    @classmethod
    def from_json(cls, payload: dict[str, Any]) -> RunRecord:
        return cls(
            task_id=str(payload["task_id"]),
            run_index=int(payload["run_index"]),
            attempts=dict(payload.get("attempts") or {}),
            external_state=dict(payload.get("external_state") or {}),
            note=str(payload.get("note") or ""),
        )


def write_records(records: list[RunRecord], path: str | Path) -> Path:
    """落盘记录（JSONL，一行一条——追加友好、可 diff）。"""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8", newline="\n") as handle:
        for record in records:
            handle.write(json.dumps(record.to_json(), ensure_ascii=False, sort_keys=True) + "\n")
    return target


def load_records(path: str | Path) -> list[RunRecord]:
    """读回落盘记录（与写入同形态）。"""
    records: list[RunRecord] = []
    with Path(path).open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            records.append(RunRecord.from_json(json.loads(line)))
    return records
