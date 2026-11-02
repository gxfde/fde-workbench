"""终审 signoff 检查点的唯一开闸入口（V3 T-P0-1 / 审计 WB-DEF-1）。

三处调用共用同一幂等语义：同方案至多一个 ``pending`` signoff；已有 pending
时只补 run 软链（``handoff_run_id`` 为空才补、绝不覆写），绝不重复开闸。

- ``agents.service._finalize``：非降级 completed 且绑定 solution 的 run
  （产物进入终审通道）即时开闸。此前唯一开闸点是 handoff_run，而它只收
  失败 / L1 run——正常 completed 的 agent_assisted 方案既不能 handoff 又拿
  不到 pending，export-sow 与 signoff 双 409 永久卡死（WB-DEF-1）。
- ``agents.service.handoff_run``：失败 / L1 降级 run 人工接管（既有语义）。
- ``solutions.service.export_sow``：agent_assisted 方案被闸拦下且方案没有任何
  pending 时兜底开闸（存量死锁解困 + 包声明 agent_assisted 而方案无 run 的
  形态；闸本身不放宽，只保证终审台有东西可拍）。

``handoff_run_id`` 沿 goal-d9 软链语义（无 FK）：终审台按它把「触发 run →
拍板」配对成资深介入时长样本，拍板事件 payload 携带。
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from fde_api.agents.models import SolutionReviewCheckpoint

SIGNOFF_REQUIRED_LEVEL = "project_manager"


def ensure_pending_signoff(session: Session, *, solution_id: str, run_id: str | None) -> SolutionReviewCheckpoint:
    """返回该方案唯一的 pending signoff checkpoint；没有则在当前事务内开出。

    取最早的 pending（与 ``resolve_signoff`` 的收口顺序一致）。
    """
    checkpoint = session.scalar(
        select(SolutionReviewCheckpoint)
        .where(SolutionReviewCheckpoint.solution_id == solution_id)
        .where(SolutionReviewCheckpoint.checkpoint_type == "signoff")
        .where(SolutionReviewCheckpoint.status == "pending")
        .order_by(SolutionReviewCheckpoint.created_at.asc(), SolutionReviewCheckpoint.id.asc())
    )
    if checkpoint is None:
        checkpoint = SolutionReviewCheckpoint(
            solution_id=solution_id,
            checkpoint_type="signoff",
            required_level=SIGNOFF_REQUIRED_LEVEL,
            status="pending",
            handoff_run_id=run_id,
        )
        session.add(checkpoint)
    elif checkpoint.handoff_run_id is None and run_id is not None:
        checkpoint.handoff_run_id = run_id
    return checkpoint
