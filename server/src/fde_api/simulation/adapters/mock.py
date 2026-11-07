"""Mock 适配器（G3）——**明确标记**的脚本化替身。

它**不是** Agent，也不复制 V3.1 的执行引擎：无调度、无状态机、无重试、无真实
模型调用。它只做一件事：按**已披露事实集**产出结构正确、**质量随访谈深度变化**
的结构化结果。

为什么这有价值：mock 模式下「顾问追问质量」被折成一个**可控参数**
``probe_quality``（0–1）。访谈越浅 ⇒ 披露的事实越少 ⇒ 产物越薄 ⇒ G4 的评估
有真实信号、G6 的回归有真实对比。**结论仅对该模式有效**（评估报告 meta 段
回显 ``adapter_mode`` 与限定语）。

诚实边界：mock 模式的分数**不代表真实 Agent 的交付质量**——它衡量的是
「训练场机制是否按预期把「问得深 ↔ 知道得多 ↔ 产出更全」这条链路跑通」。
"""
from __future__ import annotations

import random
from typing import Any, Literal

from fde_api.simulation.adapters.base import AdapterContext

# 追问退化时用的通用问题（不含任何事实关键词 ⇒ 不会触发披露）
GENERIC_QUESTIONS = (
    "能先介绍一下你们目前这块业务是怎么跑的吗？",
    "这个问题你们内部一般是怎么看的？",
    "如果让你们自己来推，第一步会从哪里入手？",
    "现在这条线上最费劲的环节是哪个？",
    "有没有一个你们特别想要的结果，可以量化一下吗？",
    "这件事如果做，你们内部谁会最在意？",
    "上次类似的情况是怎么处理的？",
)


class MockAdapter:
    """脚本化替身：产出取决于已披露事实集。"""

    mode: Literal["real", "mock"] = "mock"

    def __init__(self, *, probe_quality: float = 1.0, max_rounds: int = 6) -> None:
        self._probe_quality = max(0.0, min(1.0, probe_quality))
        self._max_rounds = max(1, max_rounds)

    # -- 追问 --------------------------------------------------------------

    def probe(self, ctx: AdapterContext, *, round_index: int) -> str:
        """产出下一问。

        ``ctx.config["probe_questions"]`` 是 runner 依客户视图生成的**候选问法**
        （每条带 fact_id 与探针关键词）——顾问知道该问什么方向，但**不知道答案**。
        ``probe_quality`` 决定它有多大概率问出**命中关键词**的问题。
        """
        candidates = list(ctx.config.get("probe_questions") or [])
        rng = random.Random(ctx.seed * 1000 + round_index)
        targeted = [item for item in candidates if item.get("targeted")]
        generic = [item for item in candidates if not item.get("targeted")]
        if not targeted:
            pool = generic
        elif not generic:
            pool = targeted
        else:
            # 质量参数决定「问准」还是「泛问」
            if rng.random() <= self._probe_quality:
                pool = targeted
            else:
                pool = generic
        if not pool:
            return GENERIC_QUESTIONS[round_index % len(GENERIC_QUESTIONS)]
        choice = pool[rng.randrange(len(pool))]
        return str(choice.get("question") or GENERIC_QUESTIONS[round_index % len(GENERIC_QUESTIONS)])

    # -- 分析 --------------------------------------------------------------

    def analyze(self, ctx: AdapterContext) -> dict[str, Any]:
        """分析产物：根因与需求**只覆盖已披露的事实**。"""
        disclosed = list(ctx.disclosed)
        root_causes = [
            {"fact_id": fact.get("fact_id"), "text": fact.get("text"), "category": fact.get("category")}
            for fact in disclosed
        ]
        requirements = [
            {
                "key": f"REQ-{index + 1}",
                "title": f"澄清「{str(fact.get('text'))[:24]}」相关的前置条件",
                "source_fact_id": fact.get("fact_id"),
                "acceptance_required": True,
            }
            for index, fact in enumerate(disclosed)
        ]
        if not requirements:
            requirements = [
                {
                    "key": "REQ-1",
                    "title": "确认客户诉求背后的真实问题",
                    "source_fact_id": None,
                    "acceptance_required": True,
                }
            ]
        return {
            "root_causes": root_causes,
            "requirements": requirements,
            "open_questions": [
                item.get("fact_id")
                for item in ctx.config.get("probe_questions") or []
                if item.get("targeted") and item.get("fact_id") not in ctx.disclosed_ids()
            ],
            "facts_known": len(disclosed),
        }

    # -- 方案 --------------------------------------------------------------

    def design(self, ctx: AdapterContext) -> dict[str, Any]:
        """方案产物：方案骨架 + 任务拆解 + 验收标准（均随披露深度变化）。"""
        analysis_requirements = list(ctx.config.get("requirements") or [])
        solution_sections = []
        for fact in ctx.disclosed:
            solution_sections.append(
                {
                    "heading": f"针对「{str(fact.get('text'))[:20]}」",
                    "actions": [
                        f"核实与 {fact.get('category') or '业务'} 相关的现状",
                        "给出可度量的处理口径",
                    ],
                }
            )
        if not solution_sections:
            solution_sections = [
                {
                    "heading": "先做一次现状核对",
                    "actions": ["确认客户描述与系统现状是否一致"],
                }
            ]
        tasks = [
            {
                "key": f"TASK-{index + 1}",
                "title": section["heading"],
                "depends_on": [],
                "evidence_required": True,
            }
            for index, section in enumerate(solution_sections)
        ]
        acceptance = [
            {
                "key": f"AC-{index + 1}",
                "requirement_key": requirement.get("key"),
                "criterion": f"「{requirement.get('title')}」有可度量结论并附证据指针",
                "measurable": True,
            }
            for index, requirement in enumerate(analysis_requirements)
        ]
        if not acceptance:
            acceptance = [
                {
                    "key": "AC-1",
                    "requirement_key": None,
                    "criterion": "交付含可度量的验收结论",
                    "measurable": True,
                }
            ]
        return {
            "solution_sections": solution_sections,
            "tasks": tasks,
            "acceptance_criteria": acceptance,
            "workflow_nodes": [
                {"key": "interview", "type": "agent"},
                {"key": "design", "type": "agent"},
                {"key": "review", "type": "human_approval"},
            ],
        }

    # -- 实施 --------------------------------------------------------------

    def implement(self, ctx: AdapterContext) -> dict[str, Any]:
        """实施产物：按脚本走一遍虚拟工具，产出证据指针。"""
        environment = ctx.environment
        artifacts: list[dict[str, Any]] = []
        calls: list[dict[str, Any]] = []
        # 故障注入钩子：用于验证「越界调用 ⇒ 硬性失败」这条链路（测试专用，
        # 由运行配置显式开启，不在生产路径自动触发）。
        if ctx.config.get("inject_boundary_violation") and environment is not None:
            environment.call_tool("mail.send_real_customer", {"to": "someone"})
        if environment is not None:
            for tool in environment.list_tools():
                try:
                    result = environment.call_tool(tool, {})
                except Exception as error:  # noqa: BLE001 - 工具故障是场景内既有语义
                    calls.append({"tool": tool, "error": getattr(error, "code", "error")})
                    continue
                calls.append({"tool": tool, "ok": True})
                artifacts.append(
                    {
                        "kind": "sim_evidence",
                        "tool": tool,
                        "rows": len(result.get("data") or [])
                        if isinstance(result.get("data"), list)
                        else 1,
                        "simulation_only": True,
                    }
                )
        return {
            "artifacts": artifacts,
            "tool_calls": calls,
            "evidence_count": len(artifacts),
        }

    # -- 独立验收 ----------------------------------------------------------

    def validate(self, ctx: AdapterContext, artifacts: dict[str, Any]) -> dict[str, Any]:
        """独立验收：**只看产物本身**，不采信任何自评字段。

        验收上下文由 runner 构造，**不含** Rubric / 参考答案；本方法只做
        **结构性**检查（需求↔验收是否配对、是否有产物、是否有证据）。
        """
        checks: list[dict[str, Any]] = []
        analysis = artifacts.get("analysis") or {}
        design = artifacts.get("design") or {}
        implementation = artifacts.get("implementation") or {}
        requirements = list(analysis.get("requirements") or [])
        acceptance = list(design.get("acceptance_criteria") or [])
        covered = {item.get("requirement_key") for item in acceptance if item.get("requirement_key")}
        for requirement in requirements:
            checks.append(
                {
                    "check": "requirement_has_acceptance",
                    "requirement_key": requirement.get("key"),
                    "ok": requirement.get("key") in covered,
                }
            )
        checks.append(
            {
                "check": "artifacts_present",
                "ok": bool(implementation.get("artifacts")),
                "count": implementation.get("evidence_count", 0),
            }
        )
        checks.append(
            {
                "check": "acceptance_measurable",
                "ok": all(bool(item.get("measurable")) for item in acceptance) if acceptance else False,
            }
        )
        passed = sum(1 for check in checks if check.get("ok"))
        return {
            "checks": checks,
            "passed": passed,
            "total": len(checks),
            "verdict": "pass" if passed == len(checks) and checks else "conditional",
        }
