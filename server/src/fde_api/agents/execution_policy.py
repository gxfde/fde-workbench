"""执行策略层（V3.1 P1-1，任务书 §9 前置 4/5/8 宿主侧结构化；00-gap-register 5.4）。

纯函数模块（零 IO、零时钟、零随机——快照确定性沿 #209 字典序/规范化纪律）：

1. **工作目录规范化校验**（前置 5）：``normalize_workspace_under_root``——
   ``Path.resolve()`` 后必须落在根内（防 ``..`` 与符号链接逃逸），并叠加
   ``FORBIDDEN_MOUNT_MARKERS`` 拒绝清单（真相层/.env/fdeops/openfde 同源）；
2. **命令锚定**（前置 4）：``assert_command_allowed``——argv 受控构造（无
   shell 拼接）之外，首元素必须白名单锚定 + 参数个数上限（防超长参数行）；
3. **超时上限钳制**（前置 8 的静态半边；运行期熔断在 host_channel/容器版各自实现）；
4. **策略快照 hash**（5.6 ``policy_snapshot_hash`` 列的数据源）：canonical
   JSON（sort_keys）sha256——同输入恒同输出，审计可重算。

通道闸纪律（5.10）：本模块只是策略**库**；宿主通道 ``agent_host_channel_enabled``
默认 False 不变——闸未过（商用条款书面确认等 12 条前置）前通道保持关闭。
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from fde_api.agents.sandbox import FORBIDDEN_MOUNT_MARKERS

MAX_HOST_TIMEOUT_MS = 30 * 60 * 1000
MAX_ARGV_LENGTH = 64


class ExecutionPolicyError(RuntimeError):
    """策略拒绝（异常 A 类语义：不发起执行、不计费）。"""


def normalize_workspace_under_root(root: str | Path, candidate: str | Path) -> Path:
    """候选工作目录规范化：resolve 后必须落在根内，且不命中拒绝清单。

    ``resolve(strict=False)``（不要求已存在）+ ``is_relative_to``（防 ``..``
    与符号链接逃逸）；拒绝清单大小写不敏感子串匹配（Windows 盘符两种分隔
    符同覆盖——``assert_host_workspace_allowed`` 同款语义，此处升级为根锚定）。
    """
    root_path = Path(root).resolve()
    candidate_path = Path(candidate).resolve()
    try:
        candidate_path.relative_to(root_path)
    except ValueError as error:
        raise ExecutionPolicyError(
            f"workspace 逃逸根目录：{candidate!r} 不在 {str(root_path)!r} 内"
        ) from error
    lowered = str(candidate_path).lower()
    for marker in FORBIDDEN_MOUNT_MARKERS:
        if marker in lowered:
            raise ExecutionPolicyError(f"workspace 命中拒绝清单标记 {marker!r}")
    return candidate_path


def assert_command_allowed(argv: list[str], *, allowed_bin: str) -> None:
    """spawn 前命令锚定：首元素必须等于白名单 bin（大小写不敏感），长度上限。"""
    if not argv:
        raise ExecutionPolicyError("argv 为空")
    if len(argv) > MAX_ARGV_LENGTH:
        raise ExecutionPolicyError(f"argv 超长（{len(argv)} > {MAX_ARGV_LENGTH}）")
    first = argv[0]
    if not isinstance(first, str) or first.lower() != str(allowed_bin).lower():
        raise ExecutionPolicyError(f"命令首元素不在白名单：{first!r}（允许 {allowed_bin!r}）")


def clamp_timeout_ms(timeout_ms: int) -> int:
    """超时上限钳制（负值/零按 1 处理——熔断至少给一次机会窗口）。"""
    if timeout_ms <= 0:
        return 1
    return min(timeout_ms, MAX_HOST_TIMEOUT_MS)


def policy_snapshot(
    *,
    provider: str,
    workspace_ref: str,
    allowed_tools: list[str] | tuple[str, ...],
    timeout_ms: int,
    max_cost_units: int | None,
) -> str:
    """策略快照 hash：canonical JSON（sort_keys、工具名排序）sha256。

    同输入恒同输出（快照可重算审计）；工具集合顺序无关（排序后入哈希——
    集合语义不该因声明顺序抖动指纹）。
    """
    payload = json.dumps(
        {
            "provider": provider,
            "workspace_ref": workspace_ref,
            "allowed_tools": sorted(allowed_tools),
            "timeout_ms": clamp_timeout_ms(int(timeout_ms)),
            "max_cost_units": int(max_cost_units) if max_cost_units is not None else None,
        },
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
