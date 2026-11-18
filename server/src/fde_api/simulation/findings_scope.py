"""失败发现有效域单一真身（条款③写面，设计稿 §2.1）。

**再终裁收敛口径**：同 run 取最新 human 层评估行；finding 派生自其他（更旧的）
human 行 ⇒ superseded（旧裁决不得借尸还魂进蒸馏面/提案）；非 human 层
（deterministic/model）派生 ⇒ 恒有效。查询口径收敛，零写面零迁移——旧 findings
行原样留痕（评估行不可变纪律不破）。

消费点三处（设计稿 §2.1）：draft-ai 输入投影（过滤）／create_proposal 引用闸
（409 finding_superseded）／list_findings 投影（superseded 字段）。

模块纪律：只读评估/发现元数据（id/layer/run_id），零答案材料访问——蒸馏器
白名单内合法 import（test_simulation_improvement_draft 显式扩白名单登记）。
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import select

from fde_api.simulation.models import SimulationEvaluation, SimulationFinding


def superseded_finding_ids(session: Any, findings: list[SimulationFinding]) -> set[str]:
    """给定一组 findings，返回其中被再终裁淘汰（旧 human 行派生）的 id 集。"""
    if not findings:
        return set()
    owner_ids = {str(f.evaluation_id) for f in findings if f.evaluation_id}
    owner_layer: dict[str, tuple[str, str]] = {}
    if owner_ids:
        for eval_id, layer, eval_run in session.execute(
            select(
                SimulationEvaluation.id,
                SimulationEvaluation.layer,
                SimulationEvaluation.run_id,
            ).where(SimulationEvaluation.id.in_(owner_ids))
        ):
            owner_layer[str(eval_id)] = (str(layer), str(eval_run))
    latest_human: dict[str, str] = {}
    for eval_id, (layer, eval_run) in owner_layer.items():
        if layer != "human" or eval_run in latest_human:
            continue
        newest = session.scalar(
            select(SimulationEvaluation.id)
            .where(
                SimulationEvaluation.run_id == eval_run,
                SimulationEvaluation.layer == "human",
            )
            .order_by(SimulationEvaluation.created_at.desc(), SimulationEvaluation.id.desc())
            .limit(1)
        )
        if newest is not None:
            latest_human[eval_run] = str(newest)
    superseded: set[str] = set()
    for finding in findings:
        owner = str(finding.evaluation_id) if finding.evaluation_id else ""
        info = owner_layer.get(owner)
        if info is None or info[0] != "human":
            continue
        if latest_human.get(info[1]) != owner:
            superseded.add(str(finding.id))
    return superseded
