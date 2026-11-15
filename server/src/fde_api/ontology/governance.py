"""M5-WP3②：升级爆炸半径聚合报告（D29 两段式第②段，独立新模块）。

职责切分（D29「跨仓两段式影响分析流水线」）：ontology-service 只给纯 schema
级 diff（WP1 ``GET /versions/{fromVer}/impact/{toVer}``，零项目态耦合）；
本模块在 Workbench 侧**本地 Join** 四面引用汇总业务爆炸半径——

1. 活跃本体绑定（``ProjectOntologyBinding``，含 upgrade_pending 切换在途）；
2. S-13 钉版证据（``ProjectEvidence``，``ix_project_evidence_pinned_version``）；
3. Gate 求值回执（``GateEvaluationReceipt``，不可变历史）；
4. WorkflowRun 发起时五元组快照（D27，``pinned_version_id`` 最强键命中；
   写后不可变 ⇒ 升级绝不改写既有 run，只标记需回归）。

Agent 维度：Agent 经项目绑定间接引用本体（Logic/Action 工具桥，无独立引用
列）——并入 binding 维度计数（``agent_via_binding`` 字段显式声明归并口径，
不造无据之数）。

绑定平滑切换审批流**衔接不重建**：``integrations.service.propose_upgrade /
approve_upgrade``（M4 既有流：行锁串行化、pending 唯一、异人
``approved_by_user_id``）是唯一切换执行点；本模块只在报告尾部挂
``OntologyBindingUpgrade`` pending 视图供升级评审入口取用。

门控与诚实缺省：``ontology_enabled=False`` → 整面 404（D12/D13，与绑定面
逐字节同形）；无活跃绑定 → 409（不聚空报告）；diff 拉取失败 → 503（爆炸
半径的核心输入就是 diff，禁降级编报告）。纯函数聚合层 100% 确定性生成。
本模块零 DDL、不触碰 ``ontology/service.py``。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from fde_api.evidence.models import ProjectEvidence
from fde_api.integrations.models import ProjectOntologyBinding
from fde_api.projects.gate_receipt import GateEvaluationReceipt
from fde_api.workbench.models import Project
from fde_api.workflows.models import WorkflowRun

# 报告明细上界（防超项目把报告撑爆；计数不受影响，明细截断透明标注）
_DETAIL_SAMPLE_LIMIT = 20


class GovernanceError(ValueError):
    """爆炸半径聚合失败（code/status 进响应体，形状同 BindingError）。"""

    def __init__(self, message: str, *, status: int = 400, code: str = "invalid_request") -> None:
        super().__init__(message)
        self.status = status
        self.code = code


# ---------------------------------------------------------------- 纯函数层


def summarize_blast_radius(
    impact: Mapping[str, Any],
    *,
    bindings: Sequence[Mapping[str, Any]],
    evidence_refs: Sequence[Mapping[str, Any]],
    gate_receipts: Sequence[Mapping[str, Any]],
    workflow_runs: Sequence[Mapping[str, Any]],
    pinned_version_id: str,
) -> dict[str, Any]:
    """四面本地引用 × WP1 diff 的确定性聚合（纯函数，离线重放同值）。

    workflow 命中判定：run 快照 ``snapshot_pinned_version_id == pinned_version_id``
    （D27 五元组的 opaque 最强键；调用方负责从 ``ontology_snapshot_json`` 提取）。
    """
    breaking = impact.get("breaking_changes")
    breaking = breaking if isinstance(breaking, list) else []
    additive = impact.get("additive_changes")
    additive = additive if isinstance(additive, list) else []
    active = [b for b in bindings if b.get("status") == "active"]
    total = len(active) + len(evidence_refs) + len(gate_receipts) + len(
        [run for run in workflow_runs if run.get("snapshot_pinned_version_id") == pinned_version_id]
    )
    return {
        "breaking_changes": breaking,
        "additive_changes": additive,
        "blast_radius": {
            "active_binding_count": len(active),
            "evidence_pinned_count": len(evidence_refs),
            "gate_receipt_count": len(gate_receipts),
            "workflow_run_pinned_count": len(
                [
                    run
                    for run in workflow_runs
                    if run.get("snapshot_pinned_version_id") == pinned_version_id
                ]
            ),
            "total_references": total,
            # D31 古德哈特护栏反面：有 breaking 或本地有引用 → 升级须异人评审
            # （评审旗标只进报告，绝不直接改 Gate 状态——Gate 唯一结论入口）
            "requires_upgrade_review": bool(breaking) or total > 0,
            # Agent 归并口径声明：无独立引用列，随 binding 间接引用
            "agent_via_binding": True,
            "bindings_detail": [dict(b) for b in bindings[:_DETAIL_SAMPLE_LIMIT]],
            "evidence_detail": [dict(e) for e in evidence_refs[:_DETAIL_SAMPLE_LIMIT]],
            "receipts_detail": [dict(r) for r in gate_receipts[:_DETAIL_SAMPLE_LIMIT]],
            "workflow_runs_detail": [
                dict(run)
                for run in workflow_runs
                if run.get("snapshot_pinned_version_id") == pinned_version_id
            ][:_DETAIL_SAMPLE_LIMIT],
            "detail_truncated": (
                len(bindings) > _DETAIL_SAMPLE_LIMIT
                or len(evidence_refs) > _DETAIL_SAMPLE_LIMIT
                or len(gate_receipts) > _DETAIL_SAMPLE_LIMIT
                or len([run for run in workflow_runs if run.get("snapshot_pinned_version_id") == pinned_version_id])
                > _DETAIL_SAMPLE_LIMIT
            ),
        },
    }


# ---------------------------------------------------------------- 服务层


def _load_blast_project(session: Session, actor: Any, project_id: str) -> Project:
    """S-01：项目不存在或无 view 权 → 统一 404（不泄露存在性）。"""
    from fde_api.projects.permissions import project_access

    project = session.get(Project, project_id)
    if project is None or not project_access(actor, project).can_view:
        raise GovernanceError("project not found", status=404, code="not_found")
    return project


def _pending_upgrade_view(session: Session, binding: ProjectOntologyBinding) -> dict[str, Any]:
    """衔接既有绑定升级审批流：pending 提案视图（无提案 → null）。"""
    from fde_api.integrations.models import OntologyBindingUpgrade

    row = session.scalars(
        select(OntologyBindingUpgrade).where(
            OntologyBindingUpgrade.binding_id == binding.id,
            OntologyBindingUpgrade.status == "proposed",
        )
    ).first()
    return {"pending": row.snapshot() if row is not None else None}


def build_upgrade_blast_radius(
    session: Session,
    *,
    actor: Any,
    project_id: str,
    to_version: str,
    settings: Any,
    client: Any = None,
) -> dict[str, Any]:
    """构建 v→to 升级爆炸半径报告（只读；绑定切换审批走 integrations 既有流）。

    返回 ``{ontology_id, from_version, to_version, impact, blast_radius,
    binding_upgrade}``；``impact`` 为 WP1 diff 响应体（``_status`` 剥离）。
    """
    from fde_api.errors import NOT_FOUND_MESSAGE

    if not getattr(settings, "ontology_enabled", False):
        # D12/D13：禁用面与不存在面不可区分（404 文案逐字节同形）——
        # 门控先于一切参数校验（M8 红队实测钉：无参请求也必须 404 而非 400）
        raise GovernanceError(NOT_FOUND_MESSAGE, status=404, code="not_found")
    project = _load_blast_project(session, actor, project_id)
    binding = session.scalars(
        select(ProjectOntologyBinding).where(
            ProjectOntologyBinding.project_id == project.id,
            ProjectOntologyBinding.status == "active",
        )
    ).first()
    if binding is None:
        raise GovernanceError(
            "项目无活跃本体绑定，无升级影响面可聚合。",
            status=409,
            code="no_active_binding",
        )
    to_version = (to_version or "").strip()
    if not to_version:
        raise GovernanceError("to_version 查询参数必填。")
    if client is None:
        from fde_api.integrations.service import client_from_settings

        client = client_from_settings()
    try:
        impact = client.get_version_impact(
            actor_id=actor.id,
            org_id=binding.org_id,
            project_id=binding.project_id,
            ontology_id=binding.ontology_id,
            from_ver=binding.pinned_version,
            to_ver=to_version,
        )
    except Exception as exc:
        raise GovernanceError(
            "本体运行时不可达，无法聚合升级影响（请稍后重试或联系管理员）。",
            status=503,
            code="ontology_unavailable",
        ) from exc
    if int(impact.get("_status", 200)) != 200:
        raise GovernanceError(
            f"本体运行时升级影响查询失败（status={impact.get('_status')}）。",
            status=502,
            code="runtime_error",
        )
    impact_view = {k: v for k, v in impact.items() if k != "_status"}

    # ---- 本地四面引用聚合（只读） ----
    bindings_rows = session.scalars(
        select(ProjectOntologyBinding).where(
            ProjectOntologyBinding.project_id == project.id,
            ProjectOntologyBinding.ontology_id == binding.ontology_id,
        )
    ).all()
    bindings_view = [
        {
            "id": row.id,
            "status": row.status,
            "pinned_version": row.pinned_version,
            "pinned_version_id": row.pinned_version_id,
        }
        for row in bindings_rows
    ]
    evidence_rows = session.scalars(
        select(ProjectEvidence).where(
            ProjectEvidence.project_id == project.id,
            ProjectEvidence.ontology_id == binding.ontology_id,
            ProjectEvidence.pinned_version_id == binding.pinned_version_id,
        )
    ).all()
    evidence_view = [
        {"evidence_id": row.id, "kind": row.kind, "object_ref_id": row.object_ref_id}
        for row in evidence_rows
    ]
    receipt_rows = session.scalars(
        select(GateEvaluationReceipt).where(
            GateEvaluationReceipt.project_id == project.id,
            GateEvaluationReceipt.ontology_id == binding.ontology_id,
            GateEvaluationReceipt.pinned_version_id == binding.pinned_version_id,
        )
    ).all()
    receipts_view = [
        {"receipt_id": row.id, "gate_key": row.gate_key, "breaker_state": row.breaker_state}
        for row in receipt_rows
    ]
    run_rows = session.scalars(
        select(WorkflowRun).where(
            WorkflowRun.project_id == project.id,
            WorkflowRun.ontology_snapshot_json.is_not(None),
        )
    ).all()
    runs_view = [
        {
            "run_id": row.id,
            "status": row.status,
            "snapshot_pinned_version_id": str(
                (row.ontology_snapshot_json or {}).get("pinned_version_id", "")
            ),
        }
        for row in run_rows
    ]

    report = summarize_blast_radius(
        impact_view,
        bindings=bindings_view,
        evidence_refs=evidence_view,
        gate_receipts=receipts_view,
        workflow_runs=runs_view,
        pinned_version_id=binding.pinned_version_id,
    )
    return {
        "ontology_id": binding.ontology_id,
        "from_version": binding.pinned_version,
        "from_version_id": binding.pinned_version_id,
        "to_version": to_version,
        "impact": impact_view,
        **report,
        "binding_upgrade": _pending_upgrade_view(session, binding),
    }


def build_review_queue(
    session: Session,
    *,
    actor: Any,
    project_id: str,
    settings: Any,
    client: Any = None,
) -> dict[str, Any]:
    """``<0.8``/冲突候选复核分流视图（D31/M5-OPT-3，只读投影）。

    活跃绑定钉版治理摘要的分流出口：未处置候选（重点复核队列）、72h SLA
    账龄预警（runtime UTC ``submitted_at`` 单一权威时钟原样透传——Workbench
    不引入第二时钟）、映射/绑定缺口。runtime 拉取失败 → 503（分流队列的
    核心输入就是治理摘要，禁降级编队列）。**本视图绝不产出 Gate 阻断**
    （D31 古德哈特护栏：Gate 只查处置闭环，WP2 已钉）。
    """
    from fde_api.errors import NOT_FOUND_MESSAGE

    if not getattr(settings, "ontology_enabled", False):
        raise GovernanceError(NOT_FOUND_MESSAGE, status=404, code="not_found")
    project = _load_blast_project(session, actor, project_id)
    binding = session.scalars(
        select(ProjectOntologyBinding).where(
            ProjectOntologyBinding.project_id == project.id,
            ProjectOntologyBinding.status == "active",
        )
    ).first()
    if binding is None:
        raise GovernanceError(
            "项目无活跃本体绑定，无复核队列可分流。",
            status=409,
            code="no_active_binding",
        )
    if client is None:
        from fde_api.integrations.service import client_from_settings

        client = client_from_settings()
    try:
        summary = client.get_version_governance_summary(
            actor_id=actor.id,
            org_id=binding.org_id,
            project_id=binding.project_id,
            ontology_id=binding.ontology_id,
            version_id=binding.pinned_version_id,
        )
    except Exception as exc:
        raise GovernanceError(
            "本体运行时不可达，无法生成分流队列（请稍后重试或联系管理员）。",
            status=503,
            code="ontology_unavailable",
        ) from exc
    if int(summary.get("_status", 200)) != 200:
        raise GovernanceError(
            f"本体运行时治理摘要查询失败（status={summary.get('_status')}）。",
            status=502,
            code="runtime_error",
        )
    disposition = summary.get("candidate_disposition")
    disposition = disposition if isinstance(disposition, Mapping) else {}
    sla = summary.get("sla_aging")
    sla = sla if isinstance(sla, Mapping) else {}
    unmapped = summary.get("unmapped_required_properties")
    unbound = summary.get("unbound_object_types")

    def _safe_int(val: Any) -> int:
        try:
            return int(val or 0)
        except (ValueError, TypeError):
            return 0

    return {
        "ontology_id": binding.ontology_id,
        "pinned_version": binding.pinned_version,
        "pinned_version_id": binding.pinned_version_id,
        "queue": {
            "undisposed": list(disposition.get("undisposed") or []),
            "undisposed_count": _safe_int(disposition.get("undisposed_count")),
            "all_disposed": disposition.get("all_disposed"),
            "overdue": list(sla.get("overdue") or []),
            "overdue_count": _safe_int(sla.get("overdue_count")),
            "oldest_pending_age_hours": sla.get("oldest_pending_age_hours"),
            "sla_threshold_hours": sla.get("threshold_hours"),
            "unmapped_required_properties": list(unmapped or []),
            "unbound_object_types": list(unbound or []),
        },
        "gate_ready": bool(summary.get("gate_ready")),
    }


__all__ = [
    "GovernanceError",
    "build_review_queue",
    "build_upgrade_blast_radius",
    "summarize_blast_radius",
]
