"""G-07：agent run 产物 → 建议性证据候选的自动登记（AI 原生化 N1 首跑轮，2026-11-09）。

台账 G-07 的判据：``captured_from`` 的 ``agent_run:`` 前缀虽在
``evidence/models.py:18`` 的 ``CAPTURED_FROM_PREFIXES`` 中已定义，但**全仓零
生产者**——已落库的 agent 产物无一登记为证据候选（链断在「产物只写不读」）。

本模块补上这个生产者：**run 终态为 completed 时，逐个产物登记一行
``project_evidence``**（``captured_from=agent_run:<run_id>``，只存指针 +
sha256 指纹——原件永不入库）。

**只登记，不采纳**（红线：AI 不代拍板）：

- 不触碰任何门禁的 ``evidence_checklist`` 清单项 ``claim_status``；
- 不触碰门禁状态机（``gates.status``）；
- **不写** ``gate.evidence_candidates``——那是人工领用面
  （``gate_service.attach_task_evidence_candidate`` 要求 task 侧的 gate 挂点，
  agent run 产物没有该挂点，故此处不自动挂候选）；
- 采纳的唯一路径仍是人工提交闸 ``submit_gate_evidence``（显式 source_uri +
  content_hash）。

**幂等**：``upsert_evidence`` 以 ``(project_id, source_uri, content_sha256)``
为唯一指纹——同指纹重复登记返回原行（证据不可变：不覆盖、不改写）。
"""
from __future__ import annotations

from typing import Any

# 与 ``evidence/models.py::CAPTURED_FROM_PREFIXES`` 对齐的来源通道前缀
# （「前缀 + 标识」形态，见 evidence/service.py::normalize_captured_from）。
AGENT_RUN_CAPTURED_FROM_PREFIX = "agent_run:"

# 产物→证据种类的映射：绑定方案的产物记 ``solution``，其余记 ``workflow``
# （EVIDENCE_KINDS 的闭集内取值；不新增种类——新增要动 CHECK 约束与迁移，
# 且「agent」在语义上更接近交付工作流产物）。
AGENT_RUN_EVIDENCE_KINDS = ("workflow", "solution")


def evidence_kind_for_agent_run(*, linked_solution_id: str | None) -> str:
    """产物→证据种类：绑定方案→``solution``；未绑定→``workflow``。"""
    return "solution" if linked_solution_id else "workflow"


def register_agent_run_evidence_candidate(
    session: Any,
    *,
    project_id: str,
    run_id: str,
    storage_ref: str,
    content_sha256: str,
    kind: str,
) -> tuple[str | None, bool]:
    """把一个 agent run 产物登记为建议性证据候选（幂等）。

    返回 ``(evidence_id, created)``；``created=False`` 表示同指纹已存在
    （幂等命中，原行原样返回——证据不可变）。

    延迟导入 ``evidence.service``：该模块依赖 ``projects.events`` /
    ``projects.permissions``，模块级互导会拉长初始化环（沿
    ``projects/task_service.py`` 延迟导入同款先例）。
    """
    if kind not in AGENT_RUN_EVIDENCE_KINDS:
        raise ValueError(f"agent run 证据种类无效：{kind!r}")
    from fde_api.evidence.service import upsert_evidence

    captured_from = f"{AGENT_RUN_CAPTURED_FROM_PREFIX}{run_id}"
    row, created = upsert_evidence(
        session,
        project_id=project_id,
        kind=kind,
        source_uri=storage_ref,
        content_sha256=content_sha256,
        origin=f"agent_run:{run_id}",
        captured_from=captured_from,
        # created_by_user_id 留空：登记是**平台侧**行为，不是人工提交动作
        # （人工提交走 submit_gate_evidence）；run 行已记 initiated_by_user_id，
        # 责任主体可回溯——此处不把系统动作伪装成人的动作。
        created_by_user_id=None,
    )
    return (row.id if row is not None else None), created


__all__ = [
    "AGENT_RUN_CAPTURED_FROM_PREFIX",
    "AGENT_RUN_EVIDENCE_KINDS",
    "evidence_kind_for_agent_run",
    "register_agent_run_evidence_candidate",
]
