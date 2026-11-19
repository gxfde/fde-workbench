from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select

from fde_api.auth.models import User
from fde_api.control.models import UserAIAccessGrant
from fde_api.extensions import db
from fde_api.orgs.isolation import is_platform_identity
from fde_api.projects.permissions import project_access
from fde_api.workbench.models import Project


# 审批/操作材料里的敏感键（DSH 审批请求与 workflow 审批共用一道闸）
SENSITIVE_ARGUMENT_KEY = re.compile(
    r"password|passwd|pwd|token|secret|credential|authorization|bearer|api[_-]?key",
    re.IGNORECASE,
)


def contains_sensitive_argument(value: Any) -> bool:
    """递归扫描 dict/list 的键名，命中敏感模式即拒绝进入审批材料。"""
    if isinstance(value, dict):
        return any(
            SENSITIVE_ARGUMENT_KEY.search(str(key))
            or contains_sensitive_argument(child)
            for key, child in value.items()
        )
    if isinstance(value, list):
        return any(contains_sensitive_argument(item) for item in value)
    return False


ACCESS_RANK = {
    "disabled": 0,
    "assistant_read": 1,
    "project_operator": 2,
    "project_manager": 3,
    "system_operator": 4,
}
DEFAULT_ACCESS_BY_ROLE = {
    "viewer": "assistant_read",
    "fde_engineer": "project_operator",
    "project_lead": "project_manager",
    "admin": "system_operator",
}
CAPABILITY_REQUIREMENTS = {
    "workbench.write": "project_operator",
    "project.read": "assistant_read",
    "project.summarize": "assistant_read",
    "file.search": "assistant_read",
    "memo.personal.write": "project_operator",
    "research.draft.generate": "project_operator",
    "opportunity.draft.generate": "project_operator",
    "task.assigned.update": "project_operator",
    "memo.shared.write": "project_manager",
    "task.batch_assign": "project_manager",
    "project.schedule.manage": "project_manager",
    "project.members.manage": "project_manager",
    "system.health": "system_operator",
    "system.logs": "system_operator",
    "system.release": "system_operator",
    "system.database.migrate": "system_operator",
    "system.dsh.switch": "system_operator",
    # F1：立创商城查询属上游 fork 既有能力，不在 FDE 客户交付线内——
    # 收敛到系统运维员门槛，避免任何 AI 授权账号都能触发。
    "lcsc.browse": "system_operator",
    # goal-d3（S1，自动交付 §5.1 建议档位）：agent 四能力。授权档位是上限，
    # 每次 run 仍实时重判（架构方案 §6.4）；agent.meeting.convene 归 d5 工具面。
    "agent.plan.generate": "project_operator",
    "agent.code.write": "project_manager",
    "agent.meeting.convene": "project_operator",
    "agent.system.tool": "system_operator",
    # goal-d7（S2 编排）：质量守卫 + 六模块智能体能力腿（编排中枢到场表按
    # capability_tier 匹配，meetings/service._speaker_roster_ok）；角色卡
    # （agent.persona.*）不进本表——persona 不可执行（start_run 直接拒），
    # 只在会中发言，能力腿匹配由到场表 persona:<key> 承载。
    "agent.quality_guard": "project_operator",
    "agent.module.presales": "project_operator",
    "agent.module.solution": "project_operator",
    "agent.module.pricing": "project_operator",
    "agent.module.deployment": "project_operator",
    "agent.module.acceptance": "project_operator",
    "agent.module.knowledge": "project_operator",
    # AF1-WP1 收口批：ontology 工具面入矩阵。直连循环与 MCP token 派生的
    # allowed 都从 capabilities_for_level 取——缺行时提议档三工具（分级见
    # mcp_gateway.TOOLS：dry_validate/logic_run=read，action_propose/execute
    # =write_db 且真执行另有审批闸）在两张 provider 面上永不可达。
    "ontology.read": "project_operator",
    "ontology.write": "project_manager",
    # AE1-WP1（docs/ai-fde/53 §3）：单步动作执行能力。项目内操作档
    # （project_operator）——执行侧另有审批闸（risk≥3 dry_run=false 须
    # approval_id，L4 复算 AutomationApproval；拍板复核人＝同项目另一成员，
    # 四眼闸由 decide_automation_approval 既有语义承载）。
    "action_execution.invoke": "project_operator",
}


@dataclass(frozen=True, slots=True)
class AIAccessDecision:
    allowed: bool
    access_level: str
    source: str
    reason: str


def effective_ai_access(user: User) -> tuple[str, str]:
    # Administrators always retain full administration rights. Historical role
    # defaults/grants must not silently hide management controls after upgrade.
    if user.role == "admin":
        return "system_operator", "administrator"
    session = db.session()
    try:
        grant = session.scalar(select(UserAIAccessGrant).where(UserAIAccessGrant.user_id == user.id))
    finally:
        session.close()
    if grant is not None:
        return grant.access_level, "explicit"
    return DEFAULT_ACCESS_BY_ROLE.get(user.role, "disabled"), "role_default"


def is_platform_operator(user: User) -> bool:
    """平台管理操作者＝**平台身份** ＋ system_operator AI 档（M3b 批次 ①-a）。

    R1 平台私有／R2 目录写的管理面只认平台身份（``orgs/isolation.py``）——
    企业身份即使被显式授予 ``system_operator`` AI 档也不得操作平台模型、
    供应商、公共目录与插件审批（盘点表维度 2 处置建议「admin-only 保持」的
    org 维度落点；admin 经 ``effective_ai_access`` 恒为 system_operator）。
    """
    return is_platform_identity(user) and effective_ai_access(user)[0] == "system_operator"


def capabilities_for_level(level: str) -> list[str]:
    rank = ACCESS_RANK.get(level, 0)
    return sorted(name for name, required in CAPABILITY_REQUIREMENTS.items() if rank >= ACCESS_RANK[required])


def authorize_ai_capability(*, user: User, capability: str, project: Project | None = None) -> AIAccessDecision:
    level, source = effective_ai_access(user)
    required = CAPABILITY_REQUIREMENTS.get(capability)
    if not user.is_active:
        return AIAccessDecision(False, level, source, "account_inactive")
    if required is None:
        return AIAccessDecision(False, level, source, "capability_unknown")
    if ACCESS_RANK[level] < ACCESS_RANK[required]:
        return AIAccessDecision(False, level, source, "ai_access_insufficient")
    if capability.startswith("system.") or capability == "agent.system.tool":
        # goal-d3：agent.system.tool 是系统级能力（=system_operator，架构方案
        # §6.4 凭证分层），与 system.* 同规则——不要求项目上下文。
        return AIAccessDecision(level == "system_operator", level, source, "allowed" if level == "system_operator" else "system_operator_required")
    if project is None:
        return AIAccessDecision(False, level, source, "project_required")
    access = project_access(user, project)
    if not access.can_view:
        return AIAccessDecision(False, level, source, "project_forbidden")
    if required == "project_manager" and not access.can_manage:
        return AIAccessDecision(False, level, source, "project_manage_required")
    return AIAccessDecision(True, level, source, "allowed")
