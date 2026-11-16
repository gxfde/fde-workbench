"""AgentRun 取消（AF1-WP1 定参①，docs/ai-fde/09 §1；P1 戊单已批 2026-11-16）。

沿 WorkflowRun cancel_run 语义（workflows/executor.py:327）：幂等重入 +
终态 409 + 事件留痕，不新造第二套取消语义。独立模块的边界原因：``agents/
service.py`` 是热点钉（``test_source_size_budgets.HOTSPOT_BUDGETS``——只许
不变或变小），取消面作为增量放新文件。

- 路由：POST /api/v1/agents/runs/{id}/cancel（routes.py 薄面）；
- 副作用停止：``service._execute_run`` 装配 should_cancel（默认本模块
  ``_make_cancel_check`` 短会话读行；测试经 ``fde_agent_cancel_check_factory``
  扩展注入，与 clock/sleeper 注入缝同构）→ 监听段轮询到取消行即诚实终态
  cancelled（产物沿 B-1 非 completed 不入库；kill 恒定发生 CR-015）；
- 启动守卫：``_raise_if_cancelled`` 先于 SandboxHandle.create——取消后的
  行永不拉起新容器（避免「取消后仍 spawn」的泄漏窗口）；
- host_running 显式 409（宿主通道回执语义未含取消——WP1 收口批处置）；
- resume_session_ref 不接线 = 戊单②「明写不做」（docs/ai-fde/09 §1）。
"""
from __future__ import annotations

from typing import Any, Callable

from fde_api.agents.models import AgentRun
from fde_api.auth.models import User
from fde_api.extensions import db
from fde_api.projects.events import record_event
from fde_api.projects.permissions import project_access


def _raise_if_cancelled(run_id: str) -> None:
    """启动守卫：cancelled 行在沙箱创建之前拦下（409 ``agent_run_cancelled``）。"""
    with db.session() as session:
        row = session.get(AgentRun, run_id)
        if row is not None and row.status == "cancelled":
            from fde_api.agents.service import _error  # 懒解反向依赖（service 装配本模块守卫）

            raise _error(
                "agent_run_cancelled",
                "run 已被取消，沙箱未启动、不计费。",
                409,
                detail={"run_id": run_id},
            )


def _make_cancel_check(run_id: str) -> Callable[[], bool]:
    """默认取消检查：短会话重读 run 状态（生产库并发读安全）。

    测试经 ``fde_agent_cancel_check_factory`` 扩展注入假检查（与
    clock/sleeper 注入缝同构），使监听段收口路径可用按轮计数等确定性
    假件驱动，不依赖真实并发时序。
    """

    def _check() -> bool:
        with db.session() as session:
            row = session.get(AgentRun, run_id)
            return bool(row is not None and row.status == "cancelled")

    return _check


def cancel_run(*, actor: User, run_id: str) -> dict[str, Any]:
    """取消 run：幂等 + 诚实终态，沿 WorkflowRun cancel_run 语义。

    - queued：直接取消（启动守卫拦住未开始的执行）；
    - running（沙箱）：写行后监听段 should_cancel 收口，kill 恒定发生；
    - host_running：宿主通道回执语义未含取消，本版显式拒绝（409）；
    - 已 cancelled：幂等返回 cancelled=False；其余终态：409 already_terminal。
    权限 = 发起人（``initiated_by_user_id``，架构方案 §6.4 发起人即责任人）
    或项目 ``can_manage``。
    """
    from fde_api.agents.service import (  # 懒解反向依赖（service 装配本模块守卫）
        IN_FLIGHT_STATUSES,
        _error,
        _require_run_access,
        _serialize_run,
    )

    with db.session() as session, session.begin():
        run, project = _require_run_access(session, actor, run_id)
        access = project_access(actor, project)
        may_cancel = run.initiated_by_user_id == actor.id or bool(access and access.can_manage)
        if not may_cancel:
            raise _error("run_cancel_forbidden", "仅发起人或项目管理员可取消 run。", 403)
        if run.status == "cancelled":
            return {"run": _serialize_run(session, run), "cancelled": False}
        if run.status == "host_running":
            raise _error(
                "cancel_provider_unsupported",
                "宿主通道 run 暂不支持取消（回执语义未含取消）；请等待回执或失联恢复。",
                409,
            )
        if run.status not in IN_FLIGHT_STATUSES:
            raise _error("already_terminal", f"运行已终态（{run.status}），不能取消。", 409)
        run.status = "cancelled"
        record_event(session, actor, "agent_run_cancelled", project, {"run_id": run.id})
        return {"run": _serialize_run(session, run), "cancelled": True}
