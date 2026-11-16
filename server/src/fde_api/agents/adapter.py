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

import json
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from fde_api.agents import zcode_contract as zc
from fde_api.agents.sandbox import SandboxHandle
from fde_api.agents.workspace_files import _MANIFEST_FILE

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
    # V3.1 P1-1：策略快照 hash（execution_policy.policy_snapshot；宿主通道写入，容器版缺省 None）
    policy_snapshot_hash: str | None = None


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
    # V3.1 P1-1：执行策略快照（透传 ctx，_finalize 落 agent_runs.policy_snapshot_hash）
    policy_snapshot_hash: str | None = None
    # ⑦ 出站审计（宿主通道方案 A 专有）：域名级条目（ts/kind/host/port），
    # 容器适配器恒缺省空表——service 层据此落 agent_egress_audit 事件。
    egress_audit: tuple[Mapping[str, Any], ...] = ()
    # goal-sprint r3：`--json` 原始汇总对象（宿主通道 completed/failed 路径
    # 在场，容器骨架恒 None）。宿主代理据此构造回执 `summary` 字段（服务端
    # 再解析计账）——进程只 spawn 一次，payload 不二次提取。
    summary_payload: Mapping[str, Any] | None = None


class RunEventProvider(Protocol):
    """结构化事件源：poll 返回自上次以来新事件（无新事件返回空表）。"""

    def poll(self) -> Sequence[Mapping[str, Any]]: ...


class OutputScanner(Protocol):
    """产物扫描器：回收段扫描 output 目录 → 清单条目。"""

    def scan(self) -> Sequence[ArtifactFile]: ...


class ManifestOutputScanner:
    """回收段产物扫描：output/manifest.json → ArtifactFile 清单。

    B#2 回执状态面：scan() 返回类型不变（OutputScanner Protocol 兼容），
    回执判定落 ``receipt_state`` 属性——``ok``（manifest 可解析）/
    ``no_output``（无 output 目录或零文件=合法零产物任务）/
    ``files_without_manifest``（output/ 有文件但没写 manifest=回执缺失）/
    ``manifest_invalid``（manifest 不是合法 JSON 数组=回执写坏）。
    （goal-sprint r3 自 service.py 机械搬入——行为逐字节不变，service 侧
    经导入回引名字不变。）
    """

    def __init__(self, output_dir: Path) -> None:
        self._output_dir = output_dir
        self.receipt_state = "ok"

    def _classify_missing_manifest(self) -> str:
        if not self._output_dir.exists():
            return "no_output"
        has_files = any(p.is_file() for p in self._output_dir.rglob("*"))
        return "files_without_manifest" if has_files else "no_output"

    def scan(self) -> list[ArtifactFile]:
        manifest = self._output_dir / _MANIFEST_FILE
        if not manifest.exists():
            self.receipt_state = self._classify_missing_manifest()
            return []
        try:
            value = json.loads(manifest.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            self.receipt_state = "manifest_invalid"
            return []
        if not isinstance(value, list):
            self.receipt_state = "manifest_invalid"
            return []
        self.receipt_state = "ok"
        items: list[ArtifactFile] = []
        for entry in value:
            if not isinstance(entry, dict):
                continue
            path = entry.get("path")
            kind = entry.get("kind")
            if not isinstance(path, str) or not isinstance(kind, str):
                continue
            raw_refs = entry.get("source_refs")
            refs = tuple(ref for ref in raw_refs if isinstance(ref, str)) if isinstance(raw_refs, list) else ()
            items.append(ArtifactFile(path=path, kind=kind, source_refs=refs))
        return items


# ---------------------------------------------------------------------------
# spawn 段（goal-sprint r3 整体重划收口——adapter.py 定向警示清偿）
# ---------------------------------------------------------------------------
# 登记期的「容器内 zcode run」虚构契约（`run --task --output --events`，
# T-Z1 勘误确认该 CLI 形态不存在）已删除；原 TODO 说明的清偿条件已齐：
# 「宿主代理 ↔ agent_runs 状态机」咬合方式已于 P2′①（#204）拍板，r3 落地
# 宿主代理本体（agents/host_agent.py）。**生产 spawn 真身 ＝ 宿主侧**
# （dev 直连 run_host_channel / 轮询宿主代理，均经 zcode_contract 唯一
# argv 源）；zcode 不进容器（⑦/A′ 铁证 + Dockerfile 不装 zcode）。本模块
# 保留的容器 spawn 位置只服务 CI 注入骨架（SandboxHandle 替身 + 事件源
# 注入），argv 同样委托契约层生成——「适配器与宿主通道共享同一契约源」
# 由 test_agents_adapter 等价性钉住，两侧不得各写一套。


def spawn_argv(*, cli_command: str, workspace: str) -> list[str]:
    """容器骨架 spawn 参数（三段之①；经 SandboxHandle.exec 注入凭据）。

    **委托 ``zcode_contract.build_cli_argv``**（§11.3 约束 5 同族：唯一
    argv 形状来源）——prompt 文字面用契约层 ``task_prompt``（与宿主通道
    同一任务书载体），``cwd`` 锚定 workspace；宿主壳前缀（bin 与 cjs 之间
    插 cjs 入口）不属容器骨架语义，由宿主通道 ``host_channel_argv`` 承担。
    """
    core = zc.build_cli_argv(prompt=zc.task_prompt(workspace), cwd=workspace, cli_command=cli_command)
    return core


class ZcodeAdapter:
    """zcode CLI 适配器：spawn → 监听 → 回收（技术文档 §5 三段）。"""

    kind = "zcode"

    def __init__(self, *, cli_command: str = "zcode") -> None:
        self.cli_command = cli_command

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
        should_cancel: Callable[[], bool] | None = None,
    ) -> AgentRunResult:
        """三段执行；超时/预算熔断在本段强制（B-1/B-2），kill 恒定发生。

        AF1-WP1 定参①：``should_cancel``（每轮监听轮询调用）轮询到 True 即
        诚实终态 cancelled——外部 cancel API 写行后经此收口，副作用停止仍走
        finally kill（CR-015），不新造第二套回收语义。
        """
        started = clock()

        # ① spawn：AGENTS.md 纪律已由 service 写入 workspace；此处拉起 CLI
        sandbox.exec(ctx.credentials, spawn_argv(cli_command=self.cli_command, workspace=ctx.workspace_host))
        try:
            return self._listen_and_reclaim(
                ctx,
                sandbox,
                started=started,
                event_provider=event_provider,
                output_scanner=output_scanner,
                clock=clock,
                sleeper=sleeper,
                should_cancel=should_cancel,
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
        should_cancel: Callable[[], bool] | None = None,
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
            if should_cancel is not None and should_cancel():
                # AF1-WP1 定参①：外部取消 → 诚实终态 cancelled；产物沿 B-1
                # 非 completed 一律不入库；kill 由 finally 恒定发生（CR-015）。
                status = "cancelled"
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
                    # QR-094（goal-crv r5 发现，goal-sprint r3 吸收）：done 是
                    # 终态事件——立即终止本批遍历，同批后续事件不得翻转终态
                    # （否则 completed 可被同批尾随的越界 cost 翻成
                    # budget_exceeded ⇒ 产物被丢弃）。
                    break
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
    "ManifestOutputScanner",
    "OutputScanner",
    "RunEventProvider",
    "ToolCallRecord",
    "ZcodeAdapter",
    "spawn_argv",
]
