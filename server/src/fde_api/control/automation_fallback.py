"""A 轨（automation）只读降级层 —— E8 实施轮（2026-11-13）。

## 为什么有这个模块

`control/automation_jobs.py` 的 `execute_automation_run` 直接调
`dsh_runtime.current.execute(...)`；一旦 DSH 不可用就抛 `DSHRuntimeError`
→ `_record_dispatch_failure` → run 直接落 `failed`。**这是 A 轨「无 fallback」
的确切位置**（复评 §2.4-2 标为高严重度韧性缺口）。

而 `control/ai_server_client.py` 早就有成熟的降级链：
`DEGRADABLE_DSH_CODES` 命中时不抛错，而是走 `_degraded_direct_result`
（`degraded=True` + `degraded_reason`），再由 `ai_tool_loop.direct_tool_completion`
以**只读工具白名单**在进程内执行。E8 复用这条既有链，**不另造一套执行面**。

## 本模块的职责边界

**只做「能不能降级 + 降级成什么样」的纯决策**，不 spawn、不联网、不落库：

- `plan_degraded_fallback(...)` → `DegradedFallbackPlan | None`
- 决策输入：DSH 错误码、任务请求的能力集、任务类型、是否已产出过结果
- 决策输出：能否降级、降级原因、降级态的允许工具集、降级态的产出描述模板

执行面（调 provider、跑只读工具、落账）在既有 `ai_server_client` /
`ai_tool_loop` / `automation_jobs` 里，本模块不重复实现。

## 不可放宽的边界（N3 五问 2026-11-12 拍板）

1. **降级白名单＝`ai_tool_loop.READ_ONLY_TOOLS` 全量 13 个**——写类工具、
   外部副作用动作**不进降级**。
2. **失败语义＝标 `degraded=true` 并留痕**，不是静默成功，也不直接 failed。
3. **H1／H11 人工节点不自动收敛**：降级只产出「只读产物 + 明确降级标记」，
   产出仍交由**确认人（蔡工）**人工确认；降级层**不代拍板、不代确认**。
4. **A 轨任务封闭集＝仅 `pilot-001` 编码类 run**（N3-Q1）；其余任务类型
   不在降级范围内 ⇒ 诚实失败而非扩大降级面。
5. **不接 MCP 写工具、不碰审批、不代拍板**（沿用
   `test_ai_server_direct_fallback.py` 13 例的只读降级模式）。

## 为什么降级要用「计划」而不是直接执行

降级决策必须**可测、可静态审查**：能不能降级是纯函数，命中哪些错误码、
产出什么形状、降级原因写什么，全部可以在不碰数据库与网络的前提下断言。
执行面复用既有链，避免降级路径与主路径产生行为漂移。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from fde_api.control.ai_tool_loop import READ_ONLY_TOOLS
from fde_api.control.ai_server_client import DEGRADABLE_DSH_CODES
from fde_api.control.mcp_gateway import TOOLS

# A 轨任务类型封闭集（N3-Q1 拍板）：只有「ai」类定时任务可降级。
# 其余类型（若有）不在降级范围内 —— 诚实失败，不扩大降级面。
DEGRADABLE_TASK_TYPES = frozenset({"ai"})

# 降级产出物在 `AutomationTaskRun.output_json` 里的稳定键。
OUTPUT_KEY_DEGRADED = "degraded"
OUTPUT_KEY_REASON = "degraded_reason"
OUTPUT_KEY_ALLOWED_TOOLS = "degraded_allowed_tools"
OUTPUT_KEY_PRODUCED = "degraded_produced"
OUTPUT_KEY_CONFIRMATION = "degraded_confirmation_required"

# 降级态产出物的固定描述（N3-Q2：产出物＝产物 + 汇总）。
# 降级态没有宿主代理产物目录可指 ⇒ 只落描述与工具清单，不编造产物指针。
DEGRADED_PRODUCED_DESCRIPTION = (
    "只读降级产出：依据只读工具读取的事实生成的结论与清单；"
    "无宿主代理产物目录，无 sha256 产物指针。"
)

# 降级态必须由人确认（N3-Q3 ＋ H1/H11 不自动收敛）。
DEGRADED_CONFIRMATION_REQUIRED = True


@dataclass(frozen=True, slots=True)
class DegradedFallbackPlan:
    """降级决策结果（纯数据，不含任何执行副作用）。"""

    reason: str
    allowed_tools: tuple[str, ...]
    produced_description: str
    confirmation_required: bool = DEGRADED_CONFIRMATION_REQUIRED
    output_payload: dict[str, Any] = field(default_factory=dict)

    @property
    def degradable(self) -> bool:
        return True


def _build_capability_read_only_map() -> tuple[dict[str, frozenset[str]], frozenset[str]]:
    """由 `mcp_gateway.TOOLS` 单一真身派生点分能力名→只读工具白名单映射。"""
    by_cap: dict[str, set[str]] = {}
    unscoped: set[str] = set()
    for name, entry in TOOLS.items():
        if name not in READ_ONLY_TOOLS:
            continue
        capability = entry[1]
        if capability is None:
            unscoped.add(name)
        else:
            by_cap.setdefault(capability, set()).add(name)
    # `project.summarize`（`assistant_read` 档、`DEFAULT_AUTOMATION_CAPABILITIES` 成员）
    # 是纯只读项目摘要能力，无独立同名 MCP 工具但依赖读取项目事实。
    if "project.read" in by_cap:
        by_cap["project.summarize"] = set(by_cap["project.read"])
    frozen_map = {cap: frozenset(names) for cap, names in by_cap.items()}
    return frozen_map, frozenset(unscoped)


CAPABILITY_READ_ONLY_TOOLS, UNSCOPED_READ_ONLY_TOOLS = _build_capability_read_only_map()


def _read_only_tools_for(capabilities: list[str] | tuple[str, ...] | None) -> tuple[str, ...]:
    """从任务请求的能力集里挑出**属于只读白名单**的工具。

    - 能力集为空（未限定）⇒ 给出 `READ_ONLY_TOOLS` 全量（降级面最宽但仍是只读）；
    - 能力集含点分只读能力名（如 `project.read`、`file.search`）⇒ 按 `mcp_gateway.TOOLS`
      派生映射展开为对应只读工具集，并附带无能力门槛的通用只读辅助工具；
    - 能力集直传只读工具名（如 `project_read`）⇒ 仅保留同名只读白名单工具；
    - 仅含写类／编排类能力（零只读映射）⇒ 空集 ⇒ 不可降级（诚实失败，不放宽）。
    """
    if not capabilities:
        return tuple(sorted(READ_ONLY_TOOLS))
    wanted = {str(capability) for capability in capabilities}
    selected: set[str] = {name for name in READ_ONLY_TOOLS if name in wanted}
    matched_dotted_cap = False
    for cap in wanted:
        mapped = CAPABILITY_READ_ONLY_TOOLS.get(cap)
        if mapped:
            selected.update(mapped)
            matched_dotted_cap = True
    if matched_dotted_cap:
        selected.update(UNSCOPED_READ_ONLY_TOOLS)
    return tuple(sorted(selected))


def plan_degraded_fallback(
    *,
    error_code: str,
    capabilities: list[str] | tuple[str, ...] | None = None,
    task_type: str = "ai",
    already_succeeded: bool = False,
) -> DegradedFallbackPlan | None:
    """判断一次 A 轨执行失败能否降级为只读执行，并给出降级计划。

    返回 ``None`` 表示**不可降级**（调用方应走既有诚实失败路径）。
    """
    # 1) 已是终态成功的 run 不再降级（避免重复产出）。
    if already_succeeded:
        return None

    # 2) 任务类型不在封闭集内 ⇒ 不降级。
    if task_type not in DEGRADABLE_TASK_TYPES:
        return None

    # 3) 错误码不在既有可降级集合内 ⇒ 不降级。
    #    （`dsh_response_invalid` / `dsh_execution_conflict` 等不降级：
    #     前者是返回形状坏，后者是状态冲突，降级会掩盖真实问题。）
    if error_code not in DEGRADABLE_DSH_CODES:
        return None

    # 4) 降级白名单为空 ⇒ 无只读面可降级，诚实失败。
    tools = _read_only_tools_for(capabilities)
    if not tools:
        return None

    return DegradedFallbackPlan(
        reason=error_code,
        allowed_tools=tools,
        produced_description=DEGRADED_PRODUCED_DESCRIPTION,
        confirmation_required=DEGRADED_CONFIRMATION_REQUIRED,
        output_payload={
            OUTPUT_KEY_DEGRADED: True,
            OUTPUT_KEY_REASON: error_code,
            OUTPUT_KEY_ALLOWED_TOOLS: list(tools),
            OUTPUT_KEY_PRODUCED: DEGRADED_PRODUCED_DESCRIPTION,
            OUTPUT_KEY_CONFIRMATION: DEGRADED_CONFIRMATION_REQUIRED,
        },
    )


__all__ = [
    "CAPABILITY_READ_ONLY_TOOLS",
    "DEGRADABLE_TASK_TYPES",
    "DEGRADED_CONFIRMATION_REQUIRED",
    "DEGRADED_PRODUCED_DESCRIPTION",
    "DegradedFallbackPlan",
    "OUTPUT_KEY_ALLOWED_TOOLS",
    "OUTPUT_KEY_CONFIRMATION",
    "OUTPUT_KEY_DEGRADED",
    "OUTPUT_KEY_PRODUCED",
    "OUTPUT_KEY_REASON",
    "UNSCOPED_READ_ONLY_TOOLS",
    "plan_degraded_fallback",
]
