"""角色编排（G3）——一次运行的六类角色实例（G1 §5.1）。

角色**不是** AgentRegistry persona（persona 不可执行，见 G0 §4.2）：它们是模拟域
内的独立角色实例，状态落在 ``simulation_actors``。

**隔离纪律**：角色之间**不共享**隐藏信息——只有 ``customer`` 角色持有
``hidden`` 读取权；其余角色只能看到「已披露」的事实集。
"""
from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from fde_api.simulation.models import ACTOR_ROLES, SimulationActor

ROLE_PROFILES: dict[str, dict[str, Any]] = {
    "customer": {
        "display_name": "客户",
        "holds_hidden": True,
        "description": "按案例设定回答并逐步披露；不主动给方案。",
    },
    "fde_consultant": {
        "display_name": "FDE 主顾问",
        "holds_hidden": False,
        "description": "与客户沟通、识别真实问题、组织访谈与交付。",
    },
    "domain_expert": {
        "display_name": "领域专家",
        "holds_hidden": False,
        "description": "检查业务流程、术语与业务规则，标出领域错误。",
    },
    "architect": {
        "display_name": "架构师",
        "holds_hidden": False,
        "description": "审查架构、数据流、集成、权限与成本。",
    },
    "implementer": {
        "display_name": "实施",
        "holds_hidden": False,
        "description": "按已批准方案在虚拟环境执行并产出交付物。",
    },
    "acceptance_reviewer": {
        "display_name": "独立验收",
        "holds_hidden": False,
        "description": "独立检查目标满足、证据充分性与越权行为；不采信实施方自评。",
    },
}


def build_actor_set(
    session: Session,
    *,
    run_id: str,
    config: dict[str, Any] | None = None,
) -> dict[str, SimulationActor]:
    """创建一次运行的全部角色实例，返回 ``role -> actor 行``。"""
    config = config or {}
    actors: dict[str, SimulationActor] = {}
    for role in ACTOR_ROLES:
        profile = ROLE_PROFILES[role]
        actor = SimulationActor(
            run_id=run_id,
            role=role,
            display_name=str(profile["display_name"]),
            state_json={},
            config_json=dict(config.get(role) or {}),
        )
        session.add(actor)
        actors[role] = actor
    session.flush()
    return actors


def actor_ids(actors: dict[str, SimulationActor]) -> dict[str, str]:
    return {role: actor.id for role, actor in actors.items()}
