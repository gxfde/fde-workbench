"""agent_registry 种子装载（goal-d7，S2 编排：模块智能体 + 守卫 + 角色卡）。

沿 projects/gate_service.py 的 seeds 装载先例：seeds/agents.json 烘进镜像，
进程级缓存 + 首访懒初始化幂等装载（按 kind+capability_tier 匹配，已存在则
不动）。角色卡（kind='persona'）不是可执行智能体——start_run 直接拒；
命名纪律（PM-2 提示层）：persona 名称必须带「模拟」前缀（PartyMode §4.2
「命名带'模拟'前缀」，系统级校验）。
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from fde_api.agents.models import AgentRegistry

_SEEDS_DIR = Path(__file__).resolve().parents[3] / "seeds"

# PM-2 提示层（PartyMode §4.2）：角色卡命名必须带「模拟」前缀
PERSONA_NAME_PREFIX = "模拟"

# persona 能力腿前缀（agent.persona.<key>；不进 CAPABILITY_REQUIREMENTS——
# persona 不可执行，能力腿只服务编排中枢到场表匹配）
PERSONA_CAPABILITY_PREFIX = "agent.persona."


@lru_cache(maxsize=1)
def _agent_seeds() -> tuple[dict[str, Any], ...]:
    path = _SEEDS_DIR / "agents.json"
    try:
        with path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, ValueError) as error:
        raise RuntimeError("agents.json seed unavailable") from error
    rows = payload.get("agents") if isinstance(payload, dict) else None
    if not isinstance(rows, list) or not rows:
        raise RuntimeError("agents.json seed empty")
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("capability_tier"), str):
            raise RuntimeError("agents.json seed row invalid")
        if row.get("kind") == "persona" and not str(row.get("name", "")).startswith(PERSONA_NAME_PREFIX):
            raise RuntimeError("persona seed name must carry the 模拟 prefix (PM-2)")
    return tuple(rows)


def ensure_agent_seeds(session: Session) -> int:
    """幂等装载 10 行（7 可执行 + 3 角色卡），返回新建行数。

    匹配键 = (kind, capability_tier)；已存在则零改动（种子演进不覆写现场）。
    """
    existing = {
        (row.kind, row.capability_tier)
        for row in session.scalars(select(AgentRegistry)).all()
    }
    created = 0
    for row in _agent_seeds():
        key = (str(row["kind"]), str(row["capability_tier"]))
        if key in existing:
            continue
        session.add(
            AgentRegistry(
                kind=key[0],
                name=str(row["name"]),
                enabled=True,
                capability_tier=key[1],
                sandbox_profile=str(row["sandbox_profile"]),
                max_cost_units=int(row.get("max_cost_units") or 0),
                max_duration_ms=int(row.get("max_duration_ms") or 0),
                credential_ref=row.get("credential_ref"),
                allowed_tools=list(row.get("allowed_tools") or []),
            )
        )
        created += 1
    if created:
        session.flush()
    return created
