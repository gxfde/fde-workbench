"""D2 合成裁决三：交付包级「智能体协同」显式声明（goal-d8，PRD §6.3）。

接单人（accepted_user_id / seat_delivery）显式声明 agent_assisted 后，
该项目才启用 T1–T6 评审强制门与全链路溯源联动（start_run 准入闸在
agents/service.py）；不声明 = 纯人工交付，行为与 v0.2.0 完全一致。

纪律：
- 8 态机零改动——本模块绝不触碰 dispatch_status / TRANSITIONS；声明只落
  列 + OperationEvent 留痕。
- O-4 三档前置防线（PRD §6.4）：订单难度 high = 不派发给智能体 → 禁止
  声明（409）；难度未定档同样禁止（带入链需要 difficulty 参与映射）。
- 撤销声明只影响后续 run，既有 run 不回溯（报告 §二 登记口径）。
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from fde_api.auth.models import User
from fde_api.dispatch.errors import DispatchServiceError
from fde_api.dispatch.models import DeliveryPackage
from fde_api.projects.events import record_event

ORDER_DIFFICULTY_RUN_MAP = {"low": "standard", "medium": "high"}


def declare_agent_assisted(
    session: Session, *, actor: User, package_id: str, enabled: bool
) -> DeliveryPackage:
    """声明/撤销智能体协同（幂等：同值重复调用直接返回，不重复留痕）。"""
    package = session.get(DeliveryPackage, package_id)
    if package is None:
        raise DispatchServiceError("package_not_found", "交付包不存在。", 404)
    # 接单人显式声明（D2 裁决三：责任主体永远是人——声明权在接单人手中，
    # 平台侧 admin 保留管理通道）；其他人一律 403
    if actor.role != "admin" and actor.id not in {
        package.accepted_user_id,
        package.seat_delivery,
    }:
        raise DispatchServiceError(
            "declarer_required",
            "只有接单人（或平台管理员）可声明智能体协同。",
            403,
        )
    if enabled:
        if package.dispatch_status != "accepted":
            raise DispatchServiceError(
                "package_not_accepted",
                "智能体协同须在接单后声明（dispatch_status=accepted）。",
                409,
            )
        if package.difficulty == "high":
            # O-4 三档处理：难度高=不派发给智能体——声明侧前置禁入
            raise DispatchServiceError(
                "difficulty_excludes_agents",
                "订单难度为 high：按 O-4 三档处理不派发给智能体，禁止协同声明。",
                409,
            )
        if package.difficulty is None:
            raise DispatchServiceError(
                "difficulty_undefined",
                "交付包尚未定档订单难度（发布时定档），先定档再声明协同。",
                409,
            )
        if not package.agent_assisted:
            package.agent_assisted = True
            record_event(
                session,
                actor,
                "agent_assisted_declared",
                package,
                {"difficulty": package.difficulty, "enabled": True},
            )
    elif package.agent_assisted:
        package.agent_assisted = False
        record_event(
            session, actor, "agent_assisted_revoked", package, {"enabled": False}
        )
    session.flush()
    return package
