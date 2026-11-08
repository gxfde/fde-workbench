"""真实执行面适配器（G9 接线轮 · IT-01 落地）。

把 V3.1 的既有执行面（``agents.service.start_run``）接进模拟运行：
案例 → **沙箱项目投影** → 真实智能体在沙箱工作区执行 → 产物回读 → 模拟产物。

**为什么访谈仍是确定性探针**：真实执行面是「**一次性任务型**」智能体（spawn
CLI + 任务书 + 工作区），**没有多轮对话接口**；且训练场要求「同一 seed 复现同
一结果」。因此：**多轮访谈用确定性探针**，**一次性产物生成用真实执行面**——
这是能力形态的客观差异，不是偷懒。

**诚实标注**：本模块能证明「接线正确」（边界可测），**不能**在本机证明「真实
执行可用」——真实执行需要宿主上的 zcode CLI（或容器沙箱）与模型凭据。运行结果
里的 ``integration_status`` 明确区分：
- ``exercised``：真实 run 走到终态且产出产物；
- ``wired_not_exercised``：接线在、但本次没有真实执行（如降级/失败）。
"""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Callable, Literal

from fde_api.simulation.adapters.base import AdapterContext, AdapterUnavailable
from fde_api.simulation.adapters.mock import MockAdapter

# 相位 → V3.1 注册表能力档（server/seeds/agents.json 的 kind=zcode 智能体）
DEFAULT_AGENT_CAPABILITIES: dict[str, str] = {
    "analysis": "agent.module.presales",
    "design": "agent.module.solution",
    "implementation": "agent.module.deployment",
    "validation": "agent.module.acceptance",
}

# 单个产物读回的最大字符数（仿真域保存**摘录**；原件留在工作区，不搬进库）
MAX_ARTIFACT_EXCERPT = 4000


class RealAgentAdapter:
    """委托 V3.1 既有执行面的适配器。"""

    mode: Literal["real", "mock"] = "real"

    def __init__(
        self,
        *,
        probe_helper: MockAdapter | None = None,
        agent_capabilities: dict[str, str] | None = None,
        agent_runner: Callable[..., Any] | None = None,
    ) -> None:
        # 探针复用确定性实现（能力形态差异，见模块文档）；真实执行用注入点。
        self._probe = probe_helper or MockAdapter()
        self._capabilities = dict(agent_capabilities or DEFAULT_AGENT_CAPABILITIES)
        self._agent_runner = agent_runner

    # -- 追问（确定性探针） ----------------------------------------------

    def probe(self, ctx: AdapterContext, *, round_index: int) -> str:
        """多轮追问仍走确定性探针（真实执行面无多轮对话接口）。"""
        return self._probe.probe(ctx, round_index=round_index)

    # -- 一次性产物（真实执行面） ----------------------------------------

    def analyze(self, ctx: AdapterContext) -> dict[str, Any]:
        return self._run_phase(ctx, phase="analysis")

    def design(self, ctx: AdapterContext) -> dict[str, Any]:
        return self._run_phase(ctx, phase="design")

    def implement(self, ctx: AdapterContext) -> dict[str, Any]:
        return self._run_phase(ctx, phase="implementation")

    def validate(self, ctx: AdapterContext, artifacts: dict[str, Any]) -> dict[str, Any]:
        """独立验收：走验收智能体；其结论**仅作参考**——终局仍由 L-A 判定。"""
        result = self._run_phase(ctx, phase="validation")
        return {
            "checks": result.get("checks") or [],
            "passed": 0,
            "total": len(result.get("checks") or []),
            "verdict": "advisory",
            "note": "验收智能体结论仅供参考；终局由规则层（L-A）判定。",
            "agent_run_id": result.get("agent_run_id"),
            "integration_status": result.get("integration_status"),
        }

    # -- 内部：一次真实执行 ----------------------------------------------

    def _run_phase(self, ctx: AdapterContext, *, phase: str) -> dict[str, Any]:
        capability = self._capabilities.get(phase)
        if not capability:
            raise AdapterUnavailable(f"no_agent_capability_for_phase:{phase}")
        runner = self._agent_runner or _default_agent_runner()
        outcome = runner(ctx=ctx, phase=phase, capability=capability)
        # 归一化产物契约（真实面默认：自由文本 ⇒ 无结构化字段；未真正执行 ⇒
        # wired_not_exercised）。**不静默假定「已执行」。**
        if not isinstance(outcome, dict):
            raise AdapterUnavailable("agent_runner_returned_non_object")
        outcome.setdefault("artifacts", [])
        outcome.setdefault("tool_calls", [])
        outcome.setdefault("evidence_count", len(outcome.get("artifacts") or []))
        outcome.setdefault("structured", False)
        outcome.setdefault("integration_status", "wired_not_exercised")
        return outcome


def _default_agent_runner() -> Callable[..., Any]:
    """默认执行器：沙箱投影 → 真实智能体 run → 产物回读。"""

    def run(*, ctx: AdapterContext, phase: str, capability: str) -> dict[str, Any]:
        from fde_api.agents import service as agents_service
        from fde_api.agents.models import AgentArtifact, AgentRegistry, AgentRun
        from fde_api.extensions import db
        from fde_api.simulation import sandbox
        from sqlalchemy import select

        with db.session() as session:
            actor = _sandbox_actor(session)
            project = sandbox.ensure_sandbox_project(actor=actor, session=session)
            projection = sandbox.project_scenario(
                session=session,
                project=project,
                scenario_key=ctx.scenario_key,
                variant=ctx.variant,
                split=ctx.split,
                brief=list(ctx.brief),
                disclosed=[dict(fact) for fact in ctx.disclosed],
                actor=actor,
            )
            agent = session.scalar(
                select(AgentRegistry).where(
                    AgentRegistry.capability_tier == capability,
                    AgentRegistry.kind == "zcode",
                )
            )
            if agent is None or not agent.enabled:
                session.rollback()
                raise AdapterUnavailable(f"agent_not_available:{capability}")
            session.commit()

            try:
                run_payload, _status = agents_service.start_run(
                    actor=actor,
                    agent_id=agent.id,
                    payload={
                        "project_id": project.id,
                        "solution_id": projection["solution_id"],
                        "idempotency_key": f"sim:{ctx.run_id}:{phase}",
                    },
                )
            except Exception as error:  # noqa: BLE001 - V3.1 侧错误按不可用处理
                code = getattr(error, "code", None)
                raise AdapterUnavailable(
                    f"agent_run_failed:{code or type(error).__name__}"
                ) from error

            with db.session() as session:
                agent_run = session.get(AgentRun, run_payload.get("id"))
                artifacts = list(
                    session.scalars(
                        select(AgentArtifact).where(
                            AgentArtifact.run_id == run_payload.get("id")
                        )
                    )
                )
                status = agent_run.status if agent_run else "unknown"
                entries = [_artifact_entry(item) for item in artifacts]

            exercised = status in ("completed", "succeeded") and bool(entries)
            return {
                "artifacts": entries,
                "tool_calls": [
                    {"tool": "agent.run", "agent": capability, "status": status}
                ],
                "evidence_count": len(entries),
                # 真实产物是自由文本：**结构化字段不可得** ⇒ 依赖结构化字段的
                # 判据在规则层按「无证据」处理（不入账），语义判断交给模型层。
                "structured": False,
                "agent_run_id": run_payload.get("id"),
                "agent_status": status,
                "integration_status": "exercised" if exercised else "wired_not_exercised",
                "phase": phase,
                "projection": {
                    "project_id": projection["project_id"],
                    "context_sha256": projection["context_sha256"],
                },
            }

    return run


def _sandbox_actor(session: Any):
    """沙箱执行主体：平台管理员（admin 对任意项目有完整权限，无需成员行）。"""
    from sqlalchemy import select

    from fde_api.auth.models import User

    actor = session.scalar(select(User).where(User.role == "admin").limit(1))
    if actor is None:
        raise AdapterUnavailable("sandbox_admin_missing")
    return actor


def _artifact_entry(artifact: Any) -> dict[str, Any]:
    """把 V3.1 产物行转成仿真产物条目（**摘录 + 指纹 + 指针**）。"""
    text = ""
    try:
        from flask import current_app

        settings = current_app.config["SETTINGS"]
        root = Path(settings.agent_workspace_root)
        candidate = root / str(artifact.storage_ref)
        if candidate.exists():
            text = candidate.read_text(encoding="utf-8", errors="replace")[
                :MAX_ARTIFACT_EXCERPT
            ]
    except Exception:  # noqa: BLE001 - 读不到原文不阻断（留指针与指纹）
        text = ""
    return {
        "kind": str(artifact.kind),
        "name": str(artifact.storage_ref),
        "pointer": str(artifact.storage_ref),
        "sha256": str(artifact.sha256),
        "text": text,
        "content_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest() if text else "",
        "simulation_only": True,
    }
