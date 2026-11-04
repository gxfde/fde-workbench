"""run 工具白名单三重交集（goal-d6，自动交付设计 §2.3/§2.4 / 判定 V3/V12）。

§2.3 原文::

    AgentRunContext.allowed_tools
        ⊆ mcp_gateway 工具白名单
        ∩ 该 run 的 capability 允许集（authorize_ai_capability 实时判定）
        ∩ agent_registry.allowed_tools（插件侧声明）

**名字空间裁决（goal-d6 报告 §二.2 登记）**：mcp_gateway TOOLS 是用户 AI
对话面工具集（actor=人），agent run 面的工具名是沙箱/适配器生态（d5 已按
同一事实把会议工具面落 ``meetings.dispatch_agent_tool`` 而非网关）。交集按
名字空间分段求值：

- **平台 deny 集**（腿 1 的 run 面实质）：写类工具默认不授予智能体
  （api_execute / file_send_wechat 要求人在回路上）；会议面二工具不入
  run 面 ctx（会中只读由 meetings 工具面自行判定，U8）。
- **网关名字空间工具**（名字出现在 mcp_gateway.TOOLS）：capability 腿
  实时判定——无能力要求 → 放行；核心 capability →
  ``capabilities_for_level(effective_ai_access(actor))``；插件类 capability
  （出现在任一 PluginPackage.manifest capabilities）→ 等级地板恒生效
  （CAPABILITY_REQUIREMENTS，插件安装绝不放宽门槛）**且**实时要求发起人
  存在 ``status="installed"`` 且插件 ``status="active"`` 的安装（**V12
  白名单同步**；安装是 per-user 语义，run 继承发起人权限天花板）。
- **沙箱生态工具名**（非网关名字）：腿 2 无数据锚点，由声明集 +
  adapter 逐调用判定承载（d4 语义不变，V3 前半）。

在跑的 run 不中断（§2.4 原文）：allowed_tools 在发起时刻冻结进 run 上下文，
运行中不重算——本模块只在 start/retry 时刻被调用。
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping, Sequence

from sqlalchemy import select

from fde_api.control.access import capabilities_for_level, effective_ai_access
from fde_api.control.mcp_gateway import TOOLS
from fde_api.control.models import PluginInstallation, PluginPackage
from fde_api.meetings.templates import MEETING_AGENT_TOOLS

# 写类工具默认不授予智能体（§2.3：要求人在回路上；即便授权也须走密码确认流）
AGENT_WRITE_DENIED_TOOLS: frozenset[str] = frozenset({"api_execute", "file_send_wechat"})

# run 面恒剥集合：写类 + 会议面（会中只读面另有判定，不入沙箱 ctx）
RUN_FACE_DENIED_TOOLS: frozenset[str] = AGENT_WRITE_DENIED_TOOLS | MEETING_AGENT_TOOLS

# ---------------------------------------------------------------------------
# T-R1（agent-policy P1-R1 ToolGroup）：只读工具组目录——种子随代码发布
# （seeds/tool_groups.json，非用户可写，零新表），allowed_tools 支持
# ``group:<name>`` 引用。解析=交集（组永不扩大）：组贡献与直接声明同权进入
# 下方三重交集管线，组引用本身绝不绕过任何闸；未知/停用组贡献为空（只收缩
# 不放宽、运行面不崩溃）。组引用未知工具在装载时拒绝（fail-fast）。
# ---------------------------------------------------------------------------

GROUP_REF_PREFIX = "group:"

_SEEDS_DIR = Path(__file__).resolve().parents[3] / "seeds"

# 沙箱生态工具名（server 侧无 capability 锚点、run 面直通——d4 语义，
# 由声明集 + adapter 逐调用判定承载；当前 read_file 一项，随生态演进扩充）
SANDBOX_TOOL_NAMES: frozenset[str] = frozenset({"read_file"})

# 组种子校验分母（组引用未知工具拒绝的「已知工具」全集）
KNOWN_TOOL_NAMES: frozenset[str] = frozenset(TOOLS) | MEETING_AGENT_TOOLS | SANDBOX_TOOL_NAMES


@lru_cache(maxsize=1)
def load_tool_groups() -> dict[str, tuple[str, ...]]:
    """种子目录（进程级缓存，沿 agents.json 首访装载先例）：组名 → 工具名元组。

    仅返回 ``is_active=true`` 的组（停用组=解析贡献为空的代码侧开关）；
    全部行（含停用）都过校验。
    """
    return _load_tool_groups(_SEEDS_DIR / "tool_groups.json")


def _load_tool_groups(path: Path) -> dict[str, tuple[str, ...]]:
    try:
        with path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, ValueError) as error:
        raise RuntimeError("tool_groups.json seed unavailable") from error
    rows = payload.get("tool_groups") if isinstance(payload, dict) else None
    if not isinstance(rows, list) or not rows:
        raise RuntimeError("tool_groups.json seed empty")
    groups: dict[str, tuple[str, ...]] = {}
    for row in rows:
        name = row.get("name") if isinstance(row, dict) else None
        tools_raw = row.get("tools") if isinstance(row, dict) else None
        if not isinstance(name, str) or not name or name.startswith(GROUP_REF_PREFIX):
            raise RuntimeError("tool_groups.json seed row invalid")
        if name in groups:
            raise RuntimeError("tool_groups.json seed duplicate group")
        if (
            not isinstance(tools_raw, list)
            or not tools_raw
            or not all(isinstance(tool, str) and tool for tool in tools_raw)
        ):
            raise RuntimeError("tool_groups.json seed row invalid")
        # 组引用未知工具拒绝（P1-R1 fail-fast；嵌套 group: 引用因不在工具
        # 全集内同样在此被拒）——坏种子宁可起不来也不静默缩空组
        unknown = sorted(set(tools_raw) - KNOWN_TOOL_NAMES)
        if unknown:
            raise RuntimeError(f"tool group {name} references unknown tools: {','.join(unknown)}")
        if bool(row.get("is_active", True)):
            groups[name] = tuple(dict.fromkeys(tools_raw))
    return groups


def resolve_tool_groups(
    allowed_tools: list[Any] | None,
    *,
    groups: Mapping[str, Sequence[str]] | None = None,
) -> list[str]:
    """声明解析：``group:<name>`` 引用展开为组工具集并入声明集（保序去重）。

    只收窄语义（P1-R1「resolve=交集，组永不扩大」）：组贡献只是声明糖，
    与直接声明同权进入下游三重交集管线；未知/停用组贡献为空。``groups``
    供测试注入；None = 读种子目录。
    """
    source = load_tool_groups() if groups is None else groups
    resolved: list[str] = []
    seen: set[str] = set()
    for entry in allowed_tools or []:
        if not isinstance(entry, str) or not entry:
            continue
        candidates: Sequence[str] = (entry,)
        if entry.startswith(GROUP_REF_PREFIX):
            candidates = source.get(entry[len(GROUP_REF_PREFIX):], ())
        for tool in candidates:
            if tool and tool not in seen:
                seen.add(tool)
                resolved.append(tool)
    return resolved


def _plugin_capabilities(session: Any) -> set[str]:
    """全部插件 manifest 声明的 capability 集（判定「该能力是否插件类」）。"""
    caps: set[str] = set()
    for plugin in session.scalars(select(PluginPackage)).all():
        manifest = plugin.manifest_json if isinstance(plugin.manifest_json, dict) else {}
        declared = manifest.get("capabilities", [])
        if isinstance(declared, list):
            caps.update(item for item in declared if isinstance(item, str) and item)
    return caps


def _actor_plugin_caps(session: Any, user_id: str) -> set[str]:
    """发起人当前生效的插件 capability（installation=installed 且插件 active）。"""
    rows = session.execute(
        select(PluginInstallation, PluginPackage)
        .join(PluginPackage, PluginPackage.id == PluginInstallation.plugin_id)
        .where(PluginInstallation.user_id == user_id)
    ).all()
    caps: set[str] = set()
    for installation, plugin in rows:
        if installation.status != "installed" or plugin.status != "active":
            continue
        granted = installation.granted_capabilities if isinstance(installation.granted_capabilities, list) else []
        caps.update(item for item in granted if isinstance(item, str) and item)
    return caps


def declares_run_tools(allowed_tools: list[Any] | None) -> bool:
    """声明侧是否声明过 run 面工具（解析前原样判定：非空字符串且非会议面）。

    T-R1：``group:`` 引用也算声明——纯未知组声明在服务层报因
    ``tools_unavailable``，而不是把空解析面当成「没声明过 run 面」静默放行。
    """
    return any(
        isinstance(tool, str) and tool and tool not in MEETING_AGENT_TOOLS
        for tool in (allowed_tools or [])
    )


def run_face_declared(
    allowed_tools: list[Any] | None, *, groups: Mapping[str, Sequence[str]] | None = None
) -> frozenset[str]:
    """声明集解析后的 run 面候选（剥会议面；不判合法性）——不可用判定的分母。

    T-R1：``group:`` 引用先解析为组工具集（只收窄；未知/停用组贡献为空），
    组引用字符串本身不再当伪工具混进分母。
    """
    return frozenset(
        tool
        for tool in resolve_tool_groups(allowed_tools, groups=groups)
        if tool not in MEETING_AGENT_TOOLS
    )


def effective_run_tools(
    session: Any,
    *,
    allowed_tools: list[Any] | None,
    actor: Any,
    groups: Mapping[str, Sequence[str]] | None = None,
) -> frozenset[str]:
    """发起时刻的 run 白名单：声明集 ∖ 平台 deny ∖ 能力不可行（V3/V12）。

    ``groups`` 仅测试注入用（沿组解析链整体替换种子目录）；生产恒走种子。
    """
    declared = run_face_declared(allowed_tools, groups=groups) - RUN_FACE_DENIED_TOOLS
    if not declared:
        return frozenset()
    level, _reason = effective_ai_access(actor)
    level_caps = set(capabilities_for_level(level))
    plugin_caps_registry = _plugin_capabilities(session)
    actor_plugin_caps = _actor_plugin_caps(session, actor.id)
    effective: set[str] = set()
    for tool in declared:
        required = TOOLS[tool][1] if tool in TOOLS else None  # 网关名字空间才有能力锚点
        if required is None:
            effective.add(tool)
            continue
        # 等级地板恒生效（CAPABILITY_REQUIREMENTS）——插件安装绝不放宽门槛；
        # 插件类 capability 再加实时安装态闸（V12——disable 后新 run 同步收紧）
        if required not in level_caps:
            continue
        if required in plugin_caps_registry and required not in actor_plugin_caps:
            continue
        effective.add(tool)
    return frozenset(effective)


__all__ = [
    "AGENT_WRITE_DENIED_TOOLS",
    "KNOWN_TOOL_NAMES",
    "RUN_FACE_DENIED_TOOLS",
    "SANDBOX_TOOL_NAMES",
    "declares_run_tools",
    "effective_run_tools",
    "load_tool_groups",
    "resolve_tool_groups",
    "run_face_declared",
]
