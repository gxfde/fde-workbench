"""AgentAdapter 规范与首个 zcode 适配器（goal-d4，技术实施方案 §5 / 决议 D5）。

适配器只管「进程三段」，不碰数据库：spawn（凭据经沙箱 env 内存管道拉起
CLI）、监听（结构化事件 → 白名单判定/成本累计/超时预算熔断）、回收
（kill 沙箱 + 扫描 output 产物清单）。持久化（agent_runs 状态迁移、
agent_tool_calls denied 留痕、agent_artifacts 指纹）全部归 service 层。

CI 无 docker/真实 CLI：事件源与产物扫描器可注入（协议见
RunEventProvider/OutputScanner），超时/退避时钟可注入——断言全部落在
行为事实（状态、记录、argv 序列）上。

架构方案 §6.2 原文为 async 签名；本仓库服务端为同步 Flask 栈，适配器按
同步 ``run`` 实装（偏离原文处，goal-d4 报告 §二 登记，接口形态不变）。
"""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol

from fde_api.agents.sandbox import WORKSPACE_MOUNT_POINT, SandboxHandle

ADAPTER_KINDS: frozenset[str] = frozenset({"zcode", "codex", "claude_code", "opencode"})

# 单条监听轮询间隔（秒）；测试注入 sleeper 时可 zero-out
POLL_INTERVAL_SECONDS = 0.25


@dataclass(frozen=True)
class ToolCallRecord:
    """一次工具调用的判定结果（service 层落 agent_tool_calls）。"""

    tool_name: str
    decision: str  # allowed / denied
    capability: str
    reason: str | None = None
    duration_ms: int = 0


@dataclass(frozen=True)
class ArtifactFile:
    """output 产物清单条目（回收段扫描 manifest.json 所得）。"""

    path: str  # 相对 workspace 的 POSIX 相对路径
    kind: str  # code / doc / diff / config
    source_refs: tuple[str, ...] = ()


@dataclass(frozen=True)
class AgentRunContext:
    """一次 run 的执行输入（全部可序列化事实，绝不含真实客户资料）。"""

    run_id: str
    project_code: str
    capability: str
    workspace_host: str
    allowed_tools: frozenset[str] = frozenset()
    credentials: Mapping[str, str] = field(default_factory=dict)
    timeout_ms: int = 300_000
    max_cost_units: int = 0  # 0 = 单 run 不限额（月度预算在 service 层前置闸）


@dataclass(frozen=True)
class AgentRunResult:
    """适配器执行终态（service 层据此迁移 agent_runs 与明细表）。"""

    status: str  # completed / timeout / budget_exceeded / failed
    exit_code: int | None
    token_cost: int
    duration_ms: int
    artifacts: tuple[ArtifactFile, ...]
    tool_calls: tuple[ToolCallRecord, ...]
    degraded: bool
    degraded_reason: str | None
    # B#2 回执状态面（ManifestOutputScanner.receipt_state；其余 scanner 视为 ok）
    receipt_state: str = "ok"


class RunEventProvider(Protocol):
    """结构化事件源：poll 返回自上次以来新事件（无新事件返回空表）。"""

    def poll(self) -> Sequence[Mapping[str, Any]]: ...


class OutputScanner(Protocol):
    """产物扫描器：回收段扫描 output 目录 → 清单条目。"""

    def scan(self) -> Sequence[ArtifactFile]: ...


# TODO(T-Z1 实施轮 / D1=A)：本函数仍是登记期的「容器内 zcode run」虚构契约，
# 与真机实测的 0.17.1 不符。真实 argv 与 `--json` 单对象汇总解析已独立落在
# `agents/zcode_contract.py`（纯函数、夹具回放），供宿主侧代理与实施轮共用。
# A 通道裁定后 zcode **不进容器**：本段连同其 `sandbox.exec` 的 spawn 位置，
# 须在「宿主代理 ↔ agent_runs 状态机咬合方式」拍板后整体重划——在此之前
# 只改 argv 会制造「契约修好了但执行位置仍错」的假象，故此处刻意不预改。
def spawn_argv(*, cli_command: str, task_file: str, output_dir: str) -> list[str]:
    """容器内 CLI 启动参数（三段之①；经 SandboxHandle.exec 注入凭据）。

    ⚠️ 现存形态为占位契约，**不得**据此断言真实 zcode CLI；见上方 TODO。
    """
    return [
        cli_command,
        "run",
        "--task",
        f"{WORKSPACE_MOUNT_POINT}/{task_file}",
        "--output",
        f"{WORKSPACE_MOUNT_POINT}/{output_dir}",
        "--events",
        "ndjson",
    ]


class ZcodeAdapter:
    """zcode CLI 适配器：spawn → 监听 → 回收（技术文档 §5 三段）。"""

    kind = "zcode"

    def __init__(self, *, cli_command: str = "zcode", task_file: str = "task.md", output_dir: str = "output") -> None:
        self.cli_command = cli_command
        self.task_file = task_file
        self.output_dir = output_dir

    @property
    def agent_id(self) -> str:
        return f"adapter-{self.kind}"

    def run(
        self,
        ctx: AgentRunContext,
        sandbox: SandboxHandle,
        *,
        event_provider: RunEventProvider,
        output_scanner: OutputScanner,
        clock: Callable[[], float] = time.monotonic,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> AgentRunResult:
        """三段执行；超时/预算熔断在本段强制（B-1/B-2），kill 恒定发生。"""
        started = clock()

        # ① spawn：AGENTS.md 纪律已由 service 写入 workspace；此处拉起 CLI
        sandbox.exec(ctx.credentials, spawn_argv(cli_command=self.cli_command, task_file=self.task_file, output_dir=self.output_dir))
        try:
            return self._listen_and_reclaim(
                ctx,
                sandbox,
                started=started,
                event_provider=event_provider,
                output_scanner=output_scanner,
                clock=clock,
                sleeper=sleeper,
            )
        finally:
            # goal-c CR-015：回收走 finally——监听段任何非 SandboxError 异常
            # （事件流解析炸 / 扫描器 IO 异常）逃出时，容器（sleep infinity）
            # 不悬挂；正常路径 kill 唯一发生在此（幂等，V2-④）。
            sandbox.kill()

    def _listen_and_reclaim(
        self,
        ctx: AgentRunContext,
        sandbox: SandboxHandle,
        *,
        started: float,
        event_provider: RunEventProvider,
        output_scanner: OutputScanner,
        clock: Callable[[], float],
        sleeper: Callable[[float], None],
    ) -> AgentRunResult:
        """② 监听（超时/预算熔断）→ ③ 产物扫描；回收 kill 由调用方 finally 保证。"""
        deadline = started + ctx.timeout_ms / 1000
        token_cost = 0
        tool_calls: list[ToolCallRecord] = []
        degraded = False
        degraded_reason: str | None = None
        exit_code: int | None = None
        status = "failed"  # 无 done 事件且未熔断 → 上游异常退出的保守终态

        while True:
            now = clock()
            if now >= deadline:
                status = "timeout"
                break
            events = event_provider.poll()
            terminal = False
            for event in events:
                kind = event.get("type")
                if kind == "tool_call":
                    record = self._judge_tool_call(ctx, event)
                    tool_calls.append(record)
                    if record.decision == "denied":
                        degraded = True
                        degraded_reason = "tool_denied"
                elif kind == "cost":
                    units = event.get("units")
                    if isinstance(units, int) and units > 0:
                        if ctx.max_cost_units and token_cost + units > ctx.max_cost_units:
                            # B-2：成本停在阈值内——越界事件不入账，直接熔断
                            status = "budget_exceeded"
                            terminal = True
                            break
                        token_cost += units
                elif kind == "done":
                    exit_code = event.get("exit_code") if isinstance(event.get("exit_code"), int) else None
                    status = "completed" if exit_code == 0 else "failed"
                    terminal = True
            if terminal:
                break
            sleeper(POLL_INTERVAL_SECONDS)

        duration_ms = int((clock() - started) * 1000)

        # ③ 只有 completed 才认产物（B-1 超时产物不入库）；回收 kill 由调用方
        # finally 保证（goal-c CR-015）——此处异常逃出同样安全。
        artifacts: tuple[ArtifactFile, ...] = ()
        receipt_state = "ok"
        if status == "completed":
            artifacts = tuple(output_scanner.scan())
            # B#2：回执判定随 scanner 走（自定义 scanner 无该属性时视为 ok）
            receipt_state = str(getattr(output_scanner, "receipt_state", "ok"))

        return AgentRunResult(
            status=status,
            exit_code=exit_code,
            token_cost=token_cost,
            duration_ms=duration_ms,
            artifacts=artifacts,
            tool_calls=tuple(tool_calls),
            degraded=degraded,
            degraded_reason=degraded_reason,
            receipt_state=receipt_state,
        )

    def _judge_tool_call(self, ctx: AgentRunContext, event: Mapping[str, Any]) -> ToolCallRecord:
        """白名单判定（V3 前半）：不在 run 白名单 → denied，run 继续但标降级。"""
        tool = event.get("tool")
        tool_name = tool if isinstance(tool, str) and tool else "unknown_tool"
        raw_duration = event.get("duration_ms")
        duration = raw_duration if isinstance(raw_duration, int) and raw_duration >= 0 else 0
        if tool_name in ctx.allowed_tools:
            return ToolCallRecord(
                tool_name=tool_name,
                decision="allowed",
                capability=ctx.capability,
                duration_ms=duration,
            )
        return ToolCallRecord(
            tool_name=tool_name,
            decision="denied",
            capability=ctx.capability,
            reason="not_in_allowlist",
            duration_ms=duration,
        )


__all__ = [
    "ADAPTER_KINDS",
    "AgentRunContext",
    "AgentRunResult",
    "ArtifactFile",
    "OutputScanner",
    "RunEventProvider",
    "ToolCallRecord",
    "ZcodeAdapter",
    "spawn_argv",
]
