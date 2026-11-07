"""模拟 Trace 写入器（G3，G1 §5.4）。

Trace 是模拟的**唯一过程证据源**：工具调用、状态变化、产物、证据、越界拦截
全部落库，且按 ``(run_id, seq)`` 严格有序 ⇒ 任何一次模拟都可逐条回放。

写入器只负责**顺序 + 落库**，不含业务语义（业务语义在 runner / actors / 评估层）。
"""
from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from fde_api.simulation.models import SimulationTrace


class TraceWriter:
    """按运行内单调递增 seq 写 Trace 行。"""

    def __init__(self, session: Session, run_id: str, actor_ids: dict[str, str] | None = None) -> None:
        self._session = session
        self._run_id = run_id
        self._actor_ids = dict(actor_ids or {})
        self._seq = 0
        self._max_seq = self._current_max_seq()

    def _current_max_seq(self) -> int:
        from sqlalchemy import func, select

        current = self._session.scalar(
            select(func.max(SimulationTrace.seq)).where(SimulationTrace.run_id == self._run_id)
        )
        return int(current or 0)

    @property
    def seq(self) -> int:
        return self._seq

    def record(
        self,
        *,
        phase: str,
        event_type: str,
        actor_role: str | None = None,
        payload: dict[str, Any] | None = None,
        parent_seq: int | None = None,
        tool_call: dict[str, Any] | None = None,
        state_before: dict[str, Any] | None = None,
        state_after: dict[str, Any] | None = None,
        evidence: dict[str, Any] | None = None,
        cost: dict[str, Any] | None = None,
    ) -> int:
        """写一条 Trace，返回该条的 seq（父条用 parent_seq 挂树）。"""
        self._seq += 1
        row = SimulationTrace(
            run_id=self._run_id,
            seq=self._seq,
            parent_seq=parent_seq,
            actor_id=self._actor_ids.get(actor_role) if actor_role else None,
            phase=phase,
            event_type=event_type,
            payload_json=dict(payload or {}),
            tool_call_json=tool_call,
            state_before_json=state_before,
            state_after_json=state_after,
            evidence_json=evidence,
            cost_json=cost,
        )
        self._session.add(row)
        self._session.flush()
        return self._seq

    def bind_actor(self, role: str, actor_id: str) -> None:
        """绑定角色 → actor 行 id（角色建好后回填）。"""
        self._actor_ids[role] = actor_id
