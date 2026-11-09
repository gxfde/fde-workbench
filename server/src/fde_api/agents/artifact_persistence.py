"""completed run 产物入库与 G-07 证据候选登记（自 agents/service.py 拆出，2026-11-09）。

热点文件预算闸（``test_source_size_budgets.py``，「只许拆、不许长」）的拆分
去处之一：``_finalize`` 的产物持久化循环（AgentArtifact 行构造 + 可重建派生
摘要 + size/mime + G-07 证据候选登记）整体搬到本模块，``agents/service.py``
只留调用点。

语义零变化（搬运不重写）：

- **超时/熔断产物不入库**（B-1）；completed 的产物含校验失败者一律留痕
  ``reviewed=False``（C-1：拒绝进终审但不丢证据）；T2 门开着时产物同样留痕
  但不挂 solution（不进终审通道，``review_gate_open`` 收口后重试）；L1 降级
  产物恒不挂 solution（强制人工终审，handoff 后人工收口）；
- G-07：产物自动登记为**建议性证据候选**（``captured_from=agent_run:<run_id>``）。
  **只登记，不采纳**——采纳仍走人工提交闸（``gate_service.submit_gate_evidence``），
  本登记不触碰清单项 ``claim_status`` 与门禁状态机（红线：AI 不代拍板）。
  仅 completed run 的产物登记：校验失败/门拦截的 run 状态为 failed，其产物是
  「留痕」不是「候选」。
"""
from __future__ import annotations

import mimetypes
from pathlib import Path
from typing import Any

from fde_api.agents.models import AgentArtifact
from fde_api.agents.evidence_candidates import (
    evidence_kind_for_agent_run,
    register_agent_run_evidence_candidate,
)


def _derive_summary(kind: str, content: bytes, exit_code: int | None) -> dict[str, int] | None:
    """T-B1：入库时从原件内容派生结构化摘要（可重建，B#6 纪律）。

    计数来自原件解析；exit_code 来自 run 结果（非原件内容）合入同一摘要。
    非 diff/test_results 种类零派生（None）——不发明数字。
    """
    from fde_api.agents.artifact_summary import derive_artifact_summary

    summary = derive_artifact_summary(kind, content)
    if summary is None:
        return None
    return {**summary, "exit_code": exit_code if exit_code is not None else -1}


def persist_completed_run_artifacts(
    session: Any,
    run: Any,
    prepared: Any,
    *,
    result_exit_code: int | None,
    solution_id: str | None,
    gate_open: bool,
    l1_path: bool,
) -> None:
    """把 completed run 的已校验产物逐个落 ``agent_artifacts`` 行并登记 G-07 候选。

    ``prepared`` 是 ``(artifact, digest, content)`` 三元组序列（校验通过的
    产物，由调用方在写库前准备）；``run.status`` 须已是终态——只有
    ``completed``（非门拦截、非校验失败）才登记证据候选。
    """
    for artifact, digest, content in prepared:
        storage_ref = f"{run.id}/output/{artifact.path}"[:255]
        linked_solution_id = None if (gate_open or l1_path) else solution_id
        session.add(
            AgentArtifact(
                run_id=run.id,
                kind=artifact.kind,
                storage_ref=storage_ref,
                sha256=digest,
                reviewed=False,
                linked_solution_id=linked_solution_id,
                # T-B1：可重建派生摘要（exit_code 来自 run 结果，计数来自原件解析）
                derived_summary=_derive_summary(artifact.kind, content, result_exit_code),
                # V3.1 P1-1（5.7）：原件大小 + MIME 推断（guess_type 纯形状，不读内容）。
                # 顺带修复：原 service.py 内联版引用校验循环遗留的 ``file_path``
                # （循环外残留绑定 ⇒ 多产物 run 全部拿到**最后一个**产物的 MIME）——
                # 本版改用产物自身路径（``Path(artifact.path).name``），逐行正确。
                size_bytes=len(content),
                mime_type=mimetypes.guess_type(Path(artifact.path).name)[0],
            )
        )
        if run.status == "completed":
            register_agent_run_evidence_candidate(
                session,
                project_id=run.project_id,
                run_id=run.id,
                storage_ref=storage_ref,
                content_sha256=digest,
                kind=evidence_kind_for_agent_run(linked_solution_id=linked_solution_id),
            )


__all__ = ["persist_completed_run_artifacts"]
