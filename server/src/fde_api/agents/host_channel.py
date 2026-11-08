"""宿主侧 zcode 代理通道（T-Z1 裁定 A 方案实施轮，2026-11-07）。

裁定依据：``docs/audit/T-Z1-zcode真机实测与通道裁定提案-2026-11-07.md``
（#191）——容器内直连被四重阻断否决（node 版本 / provider 配置 / 登录态
凭据 / ``network_mode: none`` 零 egress），宿主侧代理与 bridge-poll 宿主
纪律同构、零 sandbox 基座变更。商用范围：**仅开发自用**（用户拍板
2026-11-07：尚未推向市场暂不申请商用授权；**推向市场前须取得 zcode
供应商书面授予**，挂账见 backlog T-Z1）。

与容器适配器（``agents/adapter.py``）的三点差异：

1. **spawn 面不同**：容器版 spawn 虚构契约（``zcode run --task --events``，
   T-Z1 勘误确认该 CLI 形态不存在，容器路径维持 ``adapter_missing`` 降级
   现状）；宿主版按 0.17.1 **实测契约**：
   ``ELECTRON_RUN_AS_NODE=1 <ZCode.exe> <zcode.cjs> -p <prompt> --json
   --cwd <workspace> --mode build``。
2. **观察面不同**：容器版是 ndjson 事件流轮询（tool_call 白名单 / 成本 /
   done 三类事件）；宿主版 ``--json`` 只有**单对象汇总**（逐事件只有
   app-server stdio 协议一条路，本轮不做）：超时用进程级熔断兜底；工具
   白名单无从逐事件执行 ⇒ 白名单语义由任务书文字面承载（与容器版任务书
   同源）；运行期逐工具留痕诚实缺失（``tool_calls`` 恒空表）。
3. **凭据面不同**：容器版 Fernet 解密经沙箱 env 内存管道注入；宿主版
   **零凭据注入**（zcode 用宿主自身登录态；平台凭据解密结果不进 argv /
   env / 磁盘——出现解密凭据而未被使用的 run 标 ``degraded``，经
   ``_finalize`` 走 L1 强制人工终审，语义错配不静默）。

安全边界（sandbox.py 四条硬边界的宿主侧对应物）：

- 只锚 run workspace（``--cwd`` 指向 ``agent_workspace_root/<run_id>``；
  ``FORBIDDEN_MOUNT_MARKERS`` 同款拒绝清单）；
- 超时 = kill + reap（deadline 由 ``ctx.timeout_ms`` 与注入 ``clock`` 推算；
  stdout/stderr 用 ``communicate`` 回收，PIPE 缓冲不死锁）；
- 回收 = 进程退出即天然回收（无容器残留；workspace 目录保留供产物扫描
  与溯源）；预算 = 汇总后计账，超 ``max_cost_units`` 报
  ``budget_exceeded`` 且成本按上限截断（对齐容器版 B-2「越界不入账」）。

测试注入：``spawner`` 返回假进程对象（``communicate``/``kill``/``pid``），
``clock`` 可注入——CI 无 zcode、无 Electron 也能断言 argv/env/超时/解析
全行为。
"""

from __future__ import annotations

import json
import os
import subprocess
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Protocol

from fde_api.agents import zcode_contract as zc
from fde_api.agents.adapter import AgentRunContext, AgentRunResult
from fde_api.agents.execution_policy import assert_command_allowed, clamp_timeout_ms
from fde_api.agents.sandbox import FORBIDDEN_MOUNT_MARKERS

# zcode CLI 契约（T-Z1 实测 0.17.1 §1.1）：Electron 壳 + cjs 入口；
# ELECTRON_RUN_AS_NODE=1 把壳转成 node 运行时（裸调会拉起 GUI）。
ZCODE_CJS_ENV = "ELECTRON_RUN_AS_NODE"
PROMPT_MODE = "build"


class HostChannelError(RuntimeError):
    """宿主通道错误（异常 A 类：不发起 run，降级 L2 零计费，同 SandboxError 语义）。"""


@dataclass(frozen=True)
class HostChannelSettings:
    """宿主通道配置快照（``_execute_run`` 执行时从 Settings 摘取）。"""

    zcode_bin: str  # ZCode.exe 全路径
    cjs_path: str  # zcode.cjs 全路径（相对安装根 resources/glm/zcode.cjs）


class HostProcess(Protocol):
    """子进程最小面（``subprocess.Popen`` 同构；测试假件按此实现）。"""

    pid: int
    returncode: int | None

    def kill(self) -> None: ...

    def communicate(self, input: str | None = None, timeout: float | None = None) -> tuple[str, str]: ...  # noqa: A002 - 对齐 subprocess.Popen 签名


class HostSpawner(Protocol):
    """进程拉起器：argv/env/cwd/stdout/stderr → 进程句柄。"""

    def __call__(
        self,
        argv: list[str],
        *,
        env: Mapping[str, str],
        cwd: str,
        stdout: int,
        stderr: int,
        stdin: int,
    ) -> HostProcess: ...


def _default_spawner(
    argv: list[str],
    *,
    env: Mapping[str, str],
    cwd: str,
    stdout: int,
    stderr: int,
    stdin: int,
) -> HostProcess:
    return subprocess.Popen(  # noqa: S603 - argv 受控构造，无 shell
        argv,
        env=dict(env),
        cwd=cwd,
        stdout=stdout,
        stderr=stderr,
        stdin=stdin,
        text=True,  # communicate 返回 str（--json 文本解析面；与 HostProcess 协议对齐）
    )


def host_channel_argv(
    *,
    zcode_bin: str,
    cjs_path: str,
    prompt: str,
    workspace: str,
) -> list[str]:
    """宿主 spawn 参数——**委托 ``zcode_contract.build_cli_argv``**（#193 拍板：唯一 argv 形状来源）。

    本函数只补宿主壳前缀（``<ZCode.exe> <zcode.cjs>``——Electron 转 node
    运行时，T-Z1 §1.1 实测）与 ``--mode`` 档位；核心 ``-p <prompt> --json
    --cwd <workspace>`` 由契约层生成（含 prompt/cwd 空值守卫）。prompt
    文字面携带任务书路径（workspace 内 ``task.md``）——避免超长参数行。
    """
    core_argv = zc.build_cli_argv(prompt=prompt, cwd=workspace, cli_command=zcode_bin, mode=PROMPT_MODE)
    # 契约层 argv = [zcode_bin, -p, prompt, --json, --cwd, workspace, --mode, mode]
    # 宿主壳形态在 bin 与子命令之间插 cjs 入口：[bin, cjs, -p, ...]
    return [core_argv[0], cjs_path, *core_argv[1:]]


def host_channel_env(extra: Mapping[str, str] | None = None) -> dict[str, str]:
    """宿主进程 env：继承系统 env（PATH 等 node 运行时所需）+ 转 node 开关。

    平台凭据**绝不**进入 env（差异 3）：``extra`` 仅测试注入用，生产调用
    不传。
    """
    env = dict(os.environ)
    env[ZCODE_CJS_ENV] = "1"
    if extra:
        env.update(extra)
    return env


def assert_host_workspace_allowed(workspace: str) -> None:
    """宿主 ``--cwd`` 锚定校验（sandbox 红线 2 的宿主侧对应物）。

    拒绝清单与容器挂载红线同源（``FORBIDDEN_MOUNT_MARKERS``：真相层 /
    ``.env`` / fdeops / openfde）；大小写不敏感子串匹配，Windows 盘符
    两种分隔符全覆盖。``cjs_path`` 不在此校验（属运行时入口而非数据面）。
    """
    lowered = workspace.lower()
    for marker in FORBIDDEN_MOUNT_MARKERS:
        if marker in lowered:
            raise HostChannelError(f"workspace 命中拒绝清单标记 {marker!r}（宿主 --cwd 红线）")


def task_prompt(workspace: str) -> str:
    """任务书文字面（工具白名单语义由任务书承载——模块 docstring 差异 2）。"""
    task_path = f"{workspace}/task.md"
    return (
        "请阅读并执行当前工作区 task.md 中的任务书，产物一律写入 output/ 子目录；"
        "任务书即完整需求与工具边界，超出任务书的动作一律不做。"
        f"任务书路径：{task_path}"
    )


def parse_host_summary(stdout_text: str) -> Mapping[str, Any]:
    """``--json`` 汇总解析：整体 loads 失败时取首 ``{`` 到末 ``}`` 再试。

    两次都失败 → ``HostChannelError``（fail-closed：不伪造 completed）。
    """
    text = stdout_text.strip()
    if not text:
        raise HostChannelError("--json 汇总为空（fail-closed）")
    candidates = [text]
    first, last = text.find("{"), text.rfind("}")
    if first != -1 and last > first:
        candidates.append(text[first : last + 1])
    for candidate in candidates:
        try:
            payload = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            return payload
    raise HostChannelError("--json 汇总不是对象（fail-closed，不伪造 completed）")


def summarize_host_payload(payload: Mapping[str, Any]) -> int:
    """汇总 → token 成本——**委托 ``zcode_contract.parse_json_summary``**。

    计账口径取 ``billable_units``（优先投影 totalTokenCount，缺失回落
    input+output——与容器版 cost 事件同口径）；缺失/坏类型诚实归 0，
    不猜数字（契约层 P3 数据闸同款纪律）。``parse_host_summary`` 的
    fail-closed 外壳（空/非对象拒绝）仍由本模块承担——契约层只在
    payload 为对象后接管。
    """
    return zc.parse_json_summary(payload).billable_units


def run_host_channel(
    ctx: AgentRunContext,
    settings: HostChannelSettings,
    *,
    output_scanner: Any,
    spawner: HostSpawner | None = None,
    clock: Callable[[], float] = time.monotonic,
    sleeper: Callable[[float], None] = time.sleep,  # noqa: ARG001 - 预留：与容器适配器签名对齐
    env_extra: Mapping[str, str] | None = None,
) -> AgentRunResult:
    """宿主通道执行：校验 → spawn → 超时熔断 → 解析汇总 → 预算 → 产物扫描。

    返回与容器适配器同构的 ``AgentRunResult`` ⇒ ``_finalize`` 零改动复用
    （completed/timeout/failed 终态、C-1 产物校验、T2 门、回执缺失独立
    终态全部沿用）。``tool_calls`` 恒空（--json 无逐事件流，诚实缺失）。
    ``spawner=None`` 时取模块级 ``_default_spawner``（运行时解析——测试
    monkeypatch 该模块属性即可全链替换，不受默认参数定义时绑定影响）。
    """
    del sleeper  # 单发进程模型无轮询间隔；保留形参对齐容器适配器注入面
    if spawner is None:
        spawner = _default_spawner
    assert_host_workspace_allowed(ctx.workspace_host)
    started = clock()
    argv = host_channel_argv(
        zcode_bin=settings.zcode_bin,
        cjs_path=settings.cjs_path,
        prompt=task_prompt(ctx.workspace_host),
        workspace=ctx.workspace_host,
    )
    # V3.1 P1-1 策略层（前置 4/8）：spawn 前命令锚定（argv 首元素=白名单 bin、
    # 长度上限）+ 超时上限钳制（运行期熔断窗口仍以钳后值为准）。
    assert_command_allowed(argv, allowed_bin=settings.zcode_bin)
    effective_timeout_ms = clamp_timeout_ms(ctx.timeout_ms)
    try:
        proc = spawner(
            argv,
            env=host_channel_env(env_extra),
            cwd=ctx.workspace_host,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            stdin=subprocess.DEVNULL,
        )
    except OSError as error:
        raise HostChannelError(f"zcode 进程拉起失败：{error}") from error

    timed_out = False
    exit_code: int | None
    stdout_text = ""
    stderr_text = ""
    try:
        try:
            remaining = effective_timeout_ms / 1000 - (clock() - started)
            stdout_text, stderr_text = proc.communicate(timeout=max(remaining, 0.0))
            exit_code = proc.returncode
        except subprocess.TimeoutExpired:
            timed_out = True
            proc.kill()
            stdout_text, stderr_text = proc.communicate()
            exit_code = proc.returncode
    except OSError as error:
        raise HostChannelError(f"zcode 进程回收失败：{error}") from error

    duration_ms = int((clock() - started) * 1000)
    if timed_out:
        return AgentRunResult(
            status="timeout",
            exit_code=None,
            token_cost=0,
            duration_ms=duration_ms,
            artifacts=(),
            tool_calls=(),
            degraded=False,
            degraded_reason=None,
            policy_snapshot_hash=ctx.policy_snapshot_hash,
        )

    degraded = bool(ctx.credentials)  # 平台凭据解密结果未被宿主通道使用 ⇒ L1
    degraded_reason = "host_channel_no_credential_injection" if degraded else None

    try:
        payload = parse_host_summary(stdout_text)
        tokens = summarize_host_payload(payload)
    except HostChannelError:
        if exit_code == 0:
            raise  # 退出码成功但汇总不可解析：fail-closed，不伪造 completed
        tokens = 0  # 进程本就失败：终态诚实为 failed，汇总缺失不掩盖

    if exit_code != 0:
        # 失败终态：stderr 仅供诊断，不进 result（AgentRunResult 无该字段；
        # 失败原因由 exit_code + run 层 summary 承载）。
        del stderr_text
        return AgentRunResult(
            status="failed",
            exit_code=exit_code,
            token_cost=tokens,
            duration_ms=duration_ms,
            artifacts=(),
            tool_calls=(),
            degraded=degraded,
            degraded_reason=degraded_reason,
            policy_snapshot_hash=ctx.policy_snapshot_hash,
        )

    # B-2 宿主版：成本汇总后计账；超上限按上限截断 + budget_exceeded
    # （对齐容器版「越界事件不入账」——宿主侧无法事中熔断，事后诚实降档）
    if ctx.max_cost_units and tokens > ctx.max_cost_units:
        return AgentRunResult(
            status="budget_exceeded",
            exit_code=exit_code,
            token_cost=ctx.max_cost_units,
            duration_ms=duration_ms,
            artifacts=(),  # 只有 completed 认产物（B-1 同款）
            tool_calls=(),
            degraded=degraded,
            degraded_reason=degraded_reason,
            policy_snapshot_hash=ctx.policy_snapshot_hash,
        )

    artifacts = tuple(output_scanner.scan())
    return AgentRunResult(
        status="completed",
        exit_code=exit_code,
        token_cost=tokens,
        duration_ms=duration_ms,
        artifacts=artifacts,
        tool_calls=(),
        degraded=degraded,
        degraded_reason=degraded_reason,
        receipt_state=str(getattr(output_scanner, "receipt_state", "ok")),
        policy_snapshot_hash=ctx.policy_snapshot_hash,
    )


__all__ = [
    "HostChannelError",
    "HostChannelSettings",
    "HostProcess",
    "HostSpawner",
    "PROMPT_MODE",
    "ZCODE_CJS_ENV",
    "assert_host_workspace_allowed",
    "host_channel_argv",
    "host_channel_env",
    "parse_host_summary",
    "run_host_channel",
    "summarize_host_payload",
    "task_prompt",
]
