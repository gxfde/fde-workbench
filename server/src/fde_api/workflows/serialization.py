"""工作流运行/节点的读取与呈现（架构评估 P1-2：从 executor.py 拆出）。

职责边界：**只读 + 投影**——把 run / node / 定义版本行读出来并投影成 API 形状，
不做任何状态迁移（写面在 settlement.py）。``ordered_nodes`` 是「拓扑序稳定可读」
的唯一实现（详情树与列表行共用）。
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from fde_api.extensions import db
from fde_api.jobs.outbox import utcnow
from fde_api.workflows.constants import WorkflowRunError
from fde_api.workflows.dag_utils import _dag_nodes, _topo_order
from fde_api.workflows.models import (
    WorkflowDefinition,
    WorkflowDefinitionVersion,
    WorkflowNodeRun,
    WorkflowRun,
)


def _iso(value: Any) -> str | None:
    return value.isoformat() if value is not None else None


def serialize_run(
    run: WorkflowRun, nodes: Sequence[WorkflowNodeRun], *, now: datetime | None = None
) -> dict[str, Any]:
    data = {
        "id": run.id,
        "definition_id": run.definition_id,
        "definition_version": run.definition_version,
        "project_id": run.project_id,
        "status": run.status,
        "idempotency_key": run.idempotency_key,
        "initiated_by_user_id": run.initiated_by_user_id,
        "context_json": run.context_json,
        "error": run.error,
        "started_at": _iso(run.started_at),
        "finished_at": _iso(run.finished_at),
        "created_at": _iso(run.created_at),
        "nodes": [_serialize_node(node) for node in nodes],
    }
    # B#5 挂起时长统计进 run 详情：waiting_approval 的挂起秒数（锚=
    # updated_at——状态翻进 waiting 的最近一次落库时刻；该态下无其他
    # 常规写路径，resume 拍板即刻离态）。终态/他态不出该键。
    if run.status == "waiting_approval" and run.updated_at is not None:
        current = now or utcnow()
        data["waiting_approval_seconds"] = int((current - run.updated_at).total_seconds())
    return data


def _serialize_node(node: WorkflowNodeRun) -> dict[str, Any]:
    return {
        "node_key": node.node_key,
        "node_type": node.node_type,
        "status": node.status,
        "attempt": node.attempt,
        "depends_on": node.depends_on,
        "idempotency_key": node.idempotency_key,
        "input_snapshot": node.input_snapshot,
        "output_json": node.output_json,
        "error": node.error,
        "started_at": _iso(node.started_at),
        "finished_at": _iso(node.finished_at),
    }


def serialize_run_summary(run: WorkflowRun) -> dict[str, Any]:
    """run 列表行：serialize_run 去 nodes——列表瘦身，节点树随详情按需取。"""
    data = serialize_run(run, ())
    data.pop("nodes")
    return data


def _version_row(
    session: Session, definition: WorkflowDefinition, version_number: int
) -> WorkflowDefinitionVersion:
    version = session.scalar(
        select(WorkflowDefinitionVersion).where(
            WorkflowDefinitionVersion.definition_id == definition.id,
            WorkflowDefinitionVersion.version == version_number,
        )
    )
    if version is None:
        raise WorkflowRunError(
            "definition_not_published", "定义版本快照缺失，请先发布。", 409
        )
    return version


def _version_dag(session: Session, run: WorkflowRun) -> Any:
    version = session.scalar(
        select(WorkflowDefinitionVersion).where(
            WorkflowDefinitionVersion.definition_id == run.definition_id,
            WorkflowDefinitionVersion.version == run.definition_version,
        )
    )
    if version is None:
        raise WorkflowRunError(
            "definition_version_missing", "运行钉住的定义版本快照缺失。", 422
        )
    return version.dag_json


def _load_version_dag(run_id: str) -> list[dict[str, Any]]:
    with db.session() as session:
        run = session.get(WorkflowRun, run_id)
        if run is None:
            raise WorkflowRunError("run_not_found", "运行不存在。", 404)
        return _dag_nodes(_version_dag(session, run))


def ordered_nodes(session: Session, run: WorkflowRun) -> list[WorkflowNodeRun]:
    """节点行按运行钉住版本的拓扑序排列（详情树稳定可读）。"""
    rows = list(
        session.scalars(
            select(WorkflowNodeRun).where(WorkflowNodeRun.run_id == run.id)
        )
    )
    order = {key: index for index, key in enumerate(_topo_order(_dag_nodes(_version_dag(session, run))))}
    return sorted(rows, key=lambda node: order.get(node.node_key, len(order)))
