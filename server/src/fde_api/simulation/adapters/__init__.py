"""模拟适配层（G3）：real 委托 V3.1，mock 为脚本化替身。"""

from typing import Any

from fde_api.simulation.adapters.base import (
    AdapterContext,
    AdapterUnavailable,
    SimulationAdapter,
)
from fde_api.simulation.adapters.mock import MockAdapter
from fde_api.simulation.adapters.real import RealAgentAdapter

__all__ = [
    "AdapterContext",
    "AdapterUnavailable",
    "MockAdapter",
    "RealAgentAdapter",
    "SimulationAdapter",
    "build_adapter",
]


def build_adapter(mode: str, **config: Any) -> SimulationAdapter:
    """按模式构造适配器。未知模式直接报错（不静默退回 mock）。"""
    if mode == "mock":
        return MockAdapter(
            probe_quality=float(config.get("probe_quality", 1.0)),
            max_rounds=int(config.get("max_rounds", 6)),
        )
    if mode == "real":
        return RealAgentAdapter()
    raise ValueError(f"未知适配模式：{mode}")
