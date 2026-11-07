"""模拟执行器（G3，G1 §1.2 的流程落点）。

一次运行 = 七相位流程：

```text
setup → interview → analysis → design → implementation → validation → wrapup
```

每一步都落 Trace（工具调用 / 状态变化 / 产物 / 证据 / 越界拦截）⇒ 任何一次
模拟都可逐条回放与复算。

**硬性失败**：环境出现越界调用（真实工具）⇒ 运行直接落 ``failed_hard``
（不可被其他维度高分抵消、不可重试）。

**独立性**：验收阶段的上下文**不含** Rubric / 参考答案，也不含实施方的自评
字段——验收 Agent 只看产物本身。
"""
from __future__ import annotations

import dataclasses
from typing import Any

from sqlalchemy import select

from fde_api.simulation.actors.customer_simulator import CustomerSimulator, CustomerState
from fde_api.simulation.actors.role_manager import actor_ids, build_actor_set
from fde_api.simulation.adapters import AdapterContext, build_adapter
from fde_api.simulation.environment import SimulationBoundaryViolation, SimulationEnvironment
from fde_api.simulation.models import SimulationActor, SimulationRun, SimulationScenario
from fde_api.simulation.scenarios.loader import load_view
from fde_api.simulation.trace import TraceWriter
from fde_api.extensions import db

# 访谈阶段允许披露的事实阶段
INTERVIEW_STAGES = ("setup", "interview", "analysis", "design", "late")
# 通用追问（不含任何事实关键词 ⇒ 不触发披露）
GENERIC_PROBE = "这个问题你们内部一般是怎么看的？"
# 目标化追问的模板：只含**探针关键词**，不含事实正文（顾问知道问什么方向，
# 不知道答案）
TARGETED_PROBE_TEMPLATE = "关于{keywords}这块，现在实际是怎么做的？"


class SimulationRunnerError(Exception):
    """运行器错误。"""

    def __init__(self, code: str, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


def _build_probe_questions(customer_view: dict[str, Any]) -> list[dict[str, Any]]:
    """由客户视图生成候选问法（**只用关键词**，不泄漏事实正文）。"""
    hidden = customer_view.get("hidden")
    facts = hidden.get("facts") if isinstance(hidden, dict) else None
    questions: list[dict[str, Any]] = []
    if isinstance(facts, list):
        for fact in facts:
            if not isinstance(fact, dict):
                continue
            keywords = [
                str(kw).strip()
                for kw in (fact.get("probe_keywords") or [])
                if str(kw).strip()
            ]
            if not keywords:
                continue
            questions.append(
                {
                    "question": TARGETED_PROBE_TEMPLATE.format(keywords="、".join(keywords)),
                    "fact_id": str(fact.get("fact_id") or ""),
                    "keywords": keywords,
                    "targeted": True,
                }
            )
    questions.append({"question": GENERIC_PROBE, "fact_id": None, "keywords": [], "targeted": False})
    return questions


def _load_scenario_views(session, scenario_id: str, scenario_version: int) -> tuple[Any, dict, dict]:
    """装载场景的**被测方视图**与**客户视图**。

    **执行器根本不装载 Judge View**——不是「装了就别传」，而是**连读都不读**
    ``reference_json``。这是「参考答案绝不泄漏给被测方」（G1 §4.3 P4）最强的
    形态：执行面在物理上没有接触答案的路径。评分侧（G4）自行装载 Judge View。
    """
    row = session.scalar(
        select(SimulationScenario).where(
            SimulationScenario.id == scenario_id,
            SimulationScenario.version == scenario_version,
        )
    )
    if row is None:
        raise SimulationRunnerError("not_found", "场景版本不存在。", 404)
    content = dict(row.content_json or {})
    # 参考答案只在此处被「刻意不取」——执行器全程不读 reference_json。
    reference = None
    tester_view = load_view(content, reference, "tester")
    customer_view = load_view(content, None, "customer")
    return row, tester_view, customer_view


def run_simulation(run_id: str) -> dict[str, Any]:
    """执行一次模拟运行（同步）。幂等：终态运行直接返回。"""
    with db.session() as session:
        run = session.get(SimulationRun, run_id)
        if run is None:
            raise SimulationRunnerError("not_found", "模拟运行不存在。", 404)
        if run.status in ("completed", "failed", "failed_hard", "timeout", "cancelled"):
            return {"run_id": run.id, "status": run.status, "idempotent": True}

        scenario_row, tester_view, customer_view = _load_scenario_views(
            session, run.scenario_id, run.scenario_version
        )
        config = dict(run.context_json or {})
        adapter = build_adapter(run.adapter_mode, **config)

        actors = {
            actor.role: actor
            for actor in session.scalars(
                select(SimulationActor).where(SimulationActor.run_id == run.id)
            )
        }
        if not actors:
            actors = build_actor_set(session, run_id=run.id, config=config)
        trace = TraceWriter(session, run.id, actor_ids(actors))

        run.status = "running"
        session.flush()

        trace.record(
            phase="setup",
            event_type="run_started",
            payload={
                "run_id": run.id,
                "scenario_key": scenario_row.scenario_key,
                "scenario_version": scenario_row.version,
                "variant": scenario_row.variant,
                "adapter_mode": run.adapter_mode,
                "seed": run.seed,
            },
            cost={"tokens": 0, "calls": 0},
        )

        environment = SimulationEnvironment(
            seed_data=(customer_view.get("seed_data") or {}),
            trace=trace,
            faults=(customer_view.get("fault_injection") or []),
        )

        probe_questions = _build_probe_questions(customer_view)
        escalate_after = int(config.get("escalate_after") or 0)
        customer = CustomerSimulator(
            customer_view=customer_view,
            state=CustomerState(),
            escalate_after=escalate_after,
        )

        base_ctx = AdapterContext(
            run_id=run.id,
            scenario_key=scenario_row.scenario_key,
            variant=scenario_row.variant,
            split=run.split,
            seed=run.seed,
            brief=tuple(tester_view.get("brief") or []),
            constraints=dict(tester_view.get("constraints") or {}),
            disclosed=(),
            environment=environment,
            trace=trace,
            config={**config, "probe_questions": probe_questions},
        )

        # ---- 访谈 --------------------------------------------------------
        max_rounds = int(config.get("max_rounds") or 6)
        for round_index in range(1, max_rounds + 1):
            question = adapter.probe(base_ctx, round_index=round_index)
            trace.record(
                phase="interview",
                event_type="actor_turn",
                actor_role="fde_consultant",
                payload={"round": round_index, "role": "fde_consultant", "text": question},
            )
            reply = customer.respond(question, allowed_stages=INTERVIEW_STAGES)
            trace.record(
                phase="interview",
                event_type="actor_turn",
                actor_role="customer",
                payload={
                    "round": round_index,
                    "role": "customer",
                    "persona": reply.persona,
                    "text": reply.text,
                    "matched": reply.matched,
                    "escalated": reply.escalated,
                    "unanswered": reply.unanswered,
                },
                state_before={"disclosed": list(customer.state.disclosed_fact_ids[:-1])},
                state_after={"disclosed": list(customer.state.disclosed_fact_ids)},
            )
            if reply.disclosed:
                trace.record(
                    phase="interview",
                    event_type="hidden_fact_disclosed",
                    actor_role="customer",
                    payload={
                        "round": round_index,
                        "disclosed": list(reply.disclosed),
                        "trigger": "probe_keywords_hit" if reply.matched else "escalated",
                    },
                )

        disclosed = customer.disclosed_facts
        ctx = dataclasses.replace(base_ctx, disclosed=disclosed)

        # ---- 分析 / 方案 / 实施 -----------------------------------------
        analysis = adapter.analyze(ctx)
        trace.record(
            phase="analysis",
            event_type="artifact",
            actor_role="fde_consultant",
            payload={"kind": "analysis", "artifact": analysis},
            evidence={"facts_known": len(disclosed)},
        )
        design_ctx = dataclasses.replace(
            ctx, config={**ctx.config, "requirements": analysis.get("requirements") or []}
        )
        design = adapter.design(design_ctx)
        trace.record(
            phase="design",
            event_type="artifact",
            actor_role="fde_consultant",
            payload={"kind": "design", "artifact": design},
            evidence={"acceptance_count": len(design.get("acceptance_criteria") or [])},
        )
        implementation: dict[str, Any]
        boundary_violation: SimulationBoundaryViolation | None = None
        try:
            implementation = adapter.implement(ctx)
        except SimulationBoundaryViolation as violation:
            # 越界调用：环境已落 Trace；这里**不吞**——直接把运行打成硬失败。
            boundary_violation = violation
            implementation = {"artifacts": [], "tool_calls": [], "evidence_count": 0}
        trace.record(
            phase="implementation",
            event_type="artifact",
            actor_role="implementer",
            payload={"kind": "implementation", "artifact": implementation},
            evidence={"artifact_count": implementation.get("evidence_count", 0)},
        )

        # ---- 独立验收（只看产物；无 rubric / 无自评） ---------------------
        artifacts = {
            "analysis": analysis,
            "design": design,
            "implementation": implementation,
        }
        validation_ctx = dataclasses.replace(
            ctx, config={key: value for key, value in ctx.config.items() if key != "probe_questions"}
        )
        validation = adapter.validate(validation_ctx, artifacts)
        trace.record(
            phase="validation",
            event_type="artifact",
            actor_role="acceptance_reviewer",
            payload={"kind": "validation", "artifact": validation},
            evidence={"checks": validation.get("total", 0), "passed": validation.get("passed", 0)},
        )

        # ---- 收尾 --------------------------------------------------------
        violations = environment.rejected_calls
        if boundary_violation is not None and not violations:
            violations = [
                {
                    "tool": boundary_violation.tool,
                    "rejected": True,
                    "reason": boundary_violation.reason,
                }
            ]
        if violations:
            run.status = "failed_hard"
            run.error_json = {
                "code": "boundary_violation",
                "tools": [str(call.get("tool")) for call in violations],
            }
            trace.record(
                phase="wrapup",
                event_type="hard_failure",
                payload={"code": "boundary_violation", "count": len(violations)},
            )
        else:
            run.status = "completed"

        run.cost_json = {
            "tokens": 0,
            "tool_calls": len(environment.calls),
            "rejected_calls": len(violations),
            "rounds": customer.state.probe_count,
        }
        run.actor_set_json = {
            role: {
                "actor_id": actor.id,
                "display_name": actor.display_name,
                "config": dict(actor.config_json or {}),
            }
            for role, actor in actors.items()
        }
        run.finished_at = _now_iso()
        customer_actor = actors.get("customer")
        if customer_actor is not None:
            customer_actor.state_json = customer.state.to_json()

        trace.record(
            phase="wrapup",
            event_type="run_finished",
            payload={"status": run.status},
            cost=run.cost_json,
        )
        session.commit()
        return {
            "run_id": run.id,
            "status": run.status,
            "disclosed": [str(fact.get("fact_id")) for fact in disclosed],
            "cost": dict(run.cost_json),
        }


def _now_iso() -> str:
    from datetime import UTC, datetime

    return datetime.now(UTC).isoformat()
