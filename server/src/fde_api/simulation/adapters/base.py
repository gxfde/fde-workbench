"""适配层契约（G3，G1 §8）。

**适配层是模拟面与 V3.1 之间的唯一跨界**。它吸收 V3.1 契约变动（P0-4 workflow
节点契约、P1-1 agent 执行契约），使 V3.2 其余部分不受影响。

两种实现：
- ``mock``：**明确标记**的脚本化替身。**不得**复制生产 Agent/Workflow 引擎
  （无调度、无状态机、无重试语义），只按**已披露事实集**产出结构化结果。
- ``real``：委托 V3.1 既有服务（``agents.service`` / ``workflows.executor``）。

**被测方不得看到答案**：``AdapterContext`` **不含** Judge View（参考答案/Rubric）。
评分侧由评估器（G4）单独装载。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

from fde_api.simulation.environment import SimulationEnvironment
from fde_api.simulation.trace import TraceWriter


@dataclass(frozen=True)
class AdapterContext:
    """被测方可读的上下文（**不含参考答案**）。"""

    run_id: str
    scenario_key: str
    variant: str
    split: str
    seed: int
    brief: tuple[str, ...] = ()
    constraints: dict[str, Any] = field(default_factory=dict)
    # 已披露的隐藏事实（客户模拟器解锁后才知道的）
    disclosed: tuple[dict[str, Any], ...] = ()
    environment: SimulationEnvironment | None = None
    trace: TraceWriter | None = None
    config: dict[str, Any] = field(default_factory=dict)

    def disclosed_texts(self) -> tuple[str, ...]:
        return tuple(str(fact.get("text") or "") for fact in self.disclosed)

    def disclosed_ids(self) -> tuple[str, ...]:
        return tuple(str(fact.get("fact_id") or "") for fact in self.disclosed)


class SimulationAdapter(Protocol):
    """被测执行面的统一契约。"""

    mode: Literal["real", "mock"]

    def probe(self, ctx: AdapterContext, *, round_index: int) -> str:
        """产出下一轮追问（顾问侧）。"""
        ...

    def analyze(self, ctx: AdapterContext) -> dict[str, Any]:
        """分析阶段产物（根因、需求清单）。"""
        ...

    def design(self, ctx: AdapterContext) -> dict[str, Any]:
        """方案阶段产物（方案骨架、任务拆解、验收标准）。"""
        ...

    def implement(self, ctx: AdapterContext) -> dict[str, Any]:
        """实施阶段产物（执行轨迹与产物清单）。"""
        ...

    def validate(self, ctx: AdapterContext, artifacts: dict[str, Any]) -> dict[str, Any]:
        """独立验收（**不得**采信实施方自评）。"""
        ...


class AdapterUnavailable(Exception):
    """真实适配面不可用——**不静默退回 mock**。"""

    def __init__(self, reason: str) -> None:
        super().__init__(f"真实适配面不可用：{reason}")
        self.code = "adapter_unavailable"
        self.reason = reason
