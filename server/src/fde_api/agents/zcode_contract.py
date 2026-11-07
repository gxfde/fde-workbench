"""zcode 0.17.1 真实 CLI 契约（T-Z1 实施轮准备；2026-11-07 D1 拍板 A 通道）。

事实来源：`docs/audit/T-Z1-zcode真机实测与通道裁定提案-2026-11-07.md` §1.1
（2026-11-07 真机直测，非文档转述）：

- **无 `run` 子命令、无 `--task` / `--events`**；单发执行为 `-p/--prompt <text>`。
- `--json` 输出**单对象汇总**（sessionId/traceId/turnId/response/usage/
  eventCount/projection），**不是 ndjson 事件流**；粒度事件流只在
  `app-server`（stdio ZCode Protocol）模式。
- `--resume <sessionId>` 是**取值开关**（实测同 sessionId 上下文携带）。
- 真实 CLI = `ELECTRON_RUN_AS_NODE=1 ZCode.exe resources/glm/zcode.cjs <args>`
  或宿主侧等价 wrapper；0.17.1 装在 Windows 宿主。

职责边界：本模块只做「argv 生成 + 汇总解析 + 汇总→监听段事件映射」三件纯事，
**不 spawn 进程、不读真相层、不持凭据、不落库、不发起 run**。A 通道裁定后
zcode 落在 Windows 宿主侧代理进程空间，服务端 Linux 容器不得直连宿主 CLI
（`bridge/__init__.py:3-8`）；本模块生成的 argv 由**宿主侧代理**消费。
`agents/adapter.py::spawn_argv` 的容器内 spawn 段仍待 P2′ 架构决策整体重划，
此处不预设其接线形态。
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ZCODE_CLI_VERSION = "0.17.1"


def build_cli_argv(
    *,
    prompt: str,
    cwd: str,
    cli_command: str = "zcode",
    mode: str | None = None,
    resume_session_id: str | None = None,
) -> list[str]:
    """生成 zcode 0.17.1 单发执行的真实 argv（宿主侧代理消费）。

    ``mode`` 缺省不传——权限档位（build/edit/plan/yolo/guarded）属授权前置，
    由调用方按人已拍板的档位显式给出，本函数不预设业务语义。
    """
    if not prompt or not prompt.strip():
        raise ValueError("zcode_cli_prompt_required")
    if not cwd or not cwd.strip():
        raise ValueError("zcode_cli_cwd_required")
    argv = [cli_command, "-p", prompt, "--json", "--cwd", cwd]
    if mode:
        argv.extend(["--mode", mode])
    if resume_session_id:
        argv.extend(["--resume", resume_session_id])
    return argv


@dataclass(frozen=True)
class ZcodeJsonSummary:
    """`--json` 单对象汇总的**结构化事实**（只留可计账字段，不复制正文）。"""

    session_id: str
    trace_id: str
    turn_id: str
    status: str
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    model_request_count: int
    event_count: int
    total_token_count: int

    @property
    def billable_units(self) -> int:
        """监听段 `cost` 事件口径：优先投影总量，缺失则回落输入+输出。"""
        if self.total_token_count > 0:
            return self.total_token_count
        return self.input_tokens + self.output_tokens


def _as_int(value: object) -> int:
    if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
        return value
    return 0


def _as_str(value: object) -> str:
    return value if isinstance(value, str) else ""


def parse_json_summary(payload: Mapping[str, Any]) -> ZcodeJsonSummary:
    """把真机实测的 `--json` 单对象汇总解析为结构化事实。

    缺字段／坏类型一律归零或空串并如实保留，**不猜测、不发明数字**（P3 数据闸
    同款纪律）；`response` 正文与 `usage.provider` 等文本字段一律不收，
    避免客户资料或被审内容经由汇总面渗进仓库与数据库。
    """
    usage = payload.get("usage")
    projection = payload.get("projection")
    usage_map: Mapping[str, Any] = usage if isinstance(usage, Mapping) else {}
    projection_map: Mapping[str, Any] = projection if isinstance(projection, Mapping) else {}
    return ZcodeJsonSummary(
        session_id=_as_str(payload.get("sessionId")),
        trace_id=_as_str(payload.get("traceId")),
        turn_id=_as_str(payload.get("turnId")),
        status=_as_str(projection_map.get("status")),
        input_tokens=_as_int(usage_map.get("inputTokens")),
        output_tokens=_as_int(usage_map.get("outputTokens")),
        cache_read_tokens=_as_int(usage_map.get("cacheReadTokens")),
        model_request_count=_as_int(usage_map.get("modelRequestCount")),
        event_count=_as_int(payload.get("eventCount")),
        total_token_count=_as_int(projection_map.get("totalTokenCount")),
    )


def summary_to_events(
    summary: ZcodeJsonSummary, *, exit_code: int = 0
) -> tuple[Mapping[str, Any], ...]:
    """汇总 → 适配器监听段可消费的事件序列（`cost` 记账 + `done` 终态）。

    `--json` 只有终态汇总、没有逐工具事件 ⇒ **不伪造 `tool_call`**；白名单判定
    与 `degraded` 语义维持适配器既有实现，逐事件流式须走 `app-server` stdio。
    """
    return (
        {"type": "cost", "units": summary.billable_units},
        {"type": "done", "exit_code": exit_code},
    )


class JsonSummaryEventProvider:
    """满足 `RunEventProvider` 协议（结构子类型，不继承以免与适配器环依赖）。

    一次性吐完 `cost`/`done`，之后恒为空表——与单对象汇总（非事件流）的
    事实形状一致；供 B#14 固定夹具回放与宿主代理回传复用。
    """

    def __init__(self, summary: ZcodeJsonSummary, *, exit_code: int = 0) -> None:
        self._events: tuple[Mapping[str, Any], ...] = summary_to_events(
            summary, exit_code=exit_code
        )
        self._emitted = False

    @classmethod
    def from_payload(
        cls, payload: Mapping[str, Any], *, exit_code: int = 0
    ) -> JsonSummaryEventProvider:
        return cls(parse_json_summary(payload), exit_code=exit_code)

    @classmethod
    def from_file(cls, path: Path, *, exit_code: int = 0) -> JsonSummaryEventProvider:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError("zcode_json_summary_must_be_object")
        return cls.from_payload(raw, exit_code=exit_code)

    def poll(self) -> Sequence[Mapping[str, Any]]:
        if self._emitted:
            return ()
        self._emitted = True
        return self._events


__all__ = [
    "ZCODE_CLI_VERSION",
    "JsonSummaryEventProvider",
    "ZcodeJsonSummary",
    "build_cli_argv",
    "parse_json_summary",
    "summary_to_events",
]
