"""真实适配器（G3）——委托 V3.1 既有执行面。

**形状先行、接线后置**：本模块只做「调用既有服务 + 抽结果」，不含任何自建
引擎。V3.1 契约变动（P0-4 workflow 节点契约 / P1-1 agent 执行契约）**只影响
本文件**——这是 G1 §1.3 的隔离边界落点。

**当前限制（G1 §8.4 决策 B / 待集成 IT-01）**：既有 ``AgentRun`` 与
``WorkflowRun`` 的 ``project_id`` 是真实项目的必填外键，模拟运行没有真实项目
⇒ 真实适配面**需要「沙箱项目」**才能落地。在 IT-01（给执行域加「模拟」概念）
落地前，真实适配面**明确不可用**（``AdapterUnavailable``），**不静默退回
mock**——退回与否由调用方显式选择。
"""
from __future__ import annotations

from typing import Any, Literal

from fde_api.simulation.adapters.base import AdapterContext, AdapterUnavailable
from fde_api.simulation.adapters.mock import MockAdapter


class RealAgentAdapter:
    """委托 ``agents.service`` / ``workflows.executor`` 的真实适配器。"""

    mode: Literal["real", "mock"] = "real"

    def __init__(self, *, fallback_shape: MockAdapter | None = None) -> None:
        # fallback_shape 只用于**产出形状**对齐（不是行为退级）：真实适配面
        # 不可用时抛 AdapterUnavailable，绝不拿 mock 结果冒充真实执行。
        self._shape = fallback_shape or MockAdapter()

    def _require_sandbox(self, ctx: AdapterContext) -> str:
        project_id = ctx.config.get("sandbox_project_id")
        if not isinstance(project_id, str) or not project_id.strip():
            raise AdapterUnavailable(
                "sandbox_project_required——真实执行面需要沙箱项目（IT-01 未落地）；"
                "显式改用 mock 模式（run.adapter_mode）而非静默退化"
            )
        return project_id.strip()

    def probe(self, ctx: AdapterContext, *, round_index: int) -> str:
        self._require_sandbox(ctx)
        # 真实追问由 V3.1 顾问 Agent 产出；本轮尚未接线，先给出形状占位。
        raise AdapterUnavailable("real_probe_not_wired")

    def analyze(self, ctx: AdapterContext) -> dict[str, Any]:
        self._require_sandbox(ctx)
        raise AdapterUnavailable("real_analyze_not_wired")

    def design(self, ctx: AdapterContext) -> dict[str, Any]:
        self._require_sandbox(ctx)
        raise AdapterUnavailable("real_design_not_wired")

    def implement(self, ctx: AdapterContext) -> dict[str, Any]:
        self._require_sandbox(ctx)
        raise AdapterUnavailable("real_implement_not_wired")

    def validate(self, ctx: AdapterContext, artifacts: dict[str, Any]) -> dict[str, Any]:
        self._require_sandbox(ctx)
        raise AdapterUnavailable("real_validate_not_wired")
