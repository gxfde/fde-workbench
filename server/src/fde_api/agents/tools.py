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

from typing import Any

from sqlalchemy import select

from fde_api.control.access import capabilities_for_level, effective_ai_access
from fde_api.control.mcp_gateway import TOOLS
from fde_api.control.models import PluginInstallation, PluginPackage
from fde_api.meetings.templates import MEETING_AGENT_TOOLS

# 写类工具默认不授予智能体（§2.3：要求人在回路上；即便授权也须走密码确认流）
AGENT_WRITE_DENIED_TOOLS: frozenset[str] = frozenset({"api_execute", "file_send_wechat"})

# run 面恒剥集合：写类 + 会议面（会中只读面另有判定，不入沙箱 ctx）
RUN_FACE_DENIED_TOOLS: frozenset[str] = AGENT_WRITE_DENIED_TOOLS | MEETING_AGENT_TOOLS


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


def run_face_declared(allowed_tools: list[Any] | None) -> frozenset[str]:
    """声明集中的 run 面候选（剥会议面；不判合法性）——不可用判定的分母。"""
    return frozenset(
        tool for tool in (allowed_tools or []) if isinstance(tool, str) and tool and tool not in MEETING_AGENT_TOOLS
    )


def effective_run_tools(session: Any, *, allowed_tools: list[Any] | None, actor: Any) -> frozenset[str]:
    """发起时刻的 run 白名单：声明集 ∖ 平台 deny ∖ 能力不可行（V3/V12）。"""
    declared = run_face_declared(allowed_tools) - RUN_FACE_DENIED_TOOLS
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


__all__ = ["AGENT_WRITE_DENIED_TOOLS", "RUN_FACE_DENIED_TOOLS", "effective_run_tools", "run_face_declared"]
