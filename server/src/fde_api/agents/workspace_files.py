"""沙箱工作区红线三件套的落盘（G9b 从 service.py 机械拆出，行为零变化）。

``agents/service.py`` 是架构评估 P1-2 的行数预算钉热点（只许不变或变小）——
G9b 真机实测需要在任务书头部补 manifest 回执契约行（B#2 形状说明，见
``_write_workspace`` 内注），为不推高热点体量，把工作区写出块（五常量 +
``_write_workspace``）原样搬到此模块；service.py 经导入回引（名字不变，
调用点与 monkeypatch 语义零改动）。
"""
from __future__ import annotations

from pathlib import Path

from fde_api.agents.context import SANDBOX_AGENT_DISCIPLINE

_CONTEXT_FILE = "context.md"
_TASK_FILE = "task.md"
_DISCIPLINE_FILE = "AGENTS.md"
_OUTPUT_DIR = "output"
_MANIFEST_FILE = "manifest.json"
_RUN_HEADER_LIMIT = 400  # 任务书正文上限（上下文本体在 context.md）；G9 起含 manifest 回执契约行


def _write_workspace(workspace: Path, *, context_text: str, project_code: str, capability: str) -> None:
    """渲染产物落 workspace（挂进沙箱的唯一目录；红线段三文件）。"""
    (workspace / _OUTPUT_DIR).mkdir(parents=True, exist_ok=True)
    (workspace / _CONTEXT_FILE).write_text(context_text, encoding="utf-8")
    header = "\n".join(
        (
            "# 任务书",
            "",
            f"- 项目代号: {project_code}",
            f"- 能力: {capability}",
            "请阅读 context.md 与 AGENTS.md 后执行；产物写入 output/ 并附 manifest.json。",
            # B#2 回执契约必须写明形状（G9 真机实测 2026-11-09：不写明则智能体
            # 合理自拟富格式对象 ⇒ manifest_invalid ⇒ succeeded_but_receipt_invalid；
            # path 前缀错 ⇒ file_missing；自创引用 ⇒ unknown_source_refs）。
            "manifest.json 必须是 JSON 数组（不是对象），每条形如 "
            '{"path": "<文件名>", "kind": "doc|code|diff|config", "source_refs": ["…"]}：'
            "path 相对 output/ 目录（不带 output/ 前缀）；source_refs 只能取 "
            "context.md 已确认业务问题的 source_refs 值，不要自创引用；"
            # N1 重跑二（run a5773e26 实测）：无确认问题态必须明示空数组合法，
            # 否则智能体依「不要自创引用」写空引用 ⇒ C-1 死锁（服务端已同步放行）。
            "context.md 显示「暂无已确认业务问题」时，source_refs 写空数组 []。",
            "",
            "",
        )
    )
    (workspace / _TASK_FILE).write_text(header[:_RUN_HEADER_LIMIT], encoding="utf-8")
    (workspace / _DISCIPLINE_FILE).write_text(SANDBOX_AGENT_DISCIPLINE, encoding="utf-8")
