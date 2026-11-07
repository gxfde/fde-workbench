"""改进提案服务（G5，G1 §10.3/§10.4）。

**「只提案不落地」的强制落点（P8）**：
1. 提案表**没有** publish / apply 状态与字段——状态机止于 ``approved``；
2. 本服务**不提供**任何写生产 Prompt / Skill / Workflow / 本体的函数；
3. 发布指引只是**文本**（``target_ref`` + ``change_summary`` + ``proposed_version``），
   人工在 V3.1 的治理面自行实施；
4. 静态钉：生产模块对 ``improvement_proposals`` / 本服务的引用必须为零。

**只有 confirmed 根因能生成提案**——``likely`` / ``hypothesis`` 根因进人工复核
队列，不自动变成「改进项」（否则会把猜测当结论）。
"""
from __future__ import annotations

import hashlib
import json
from typing import Any

from sqlalchemy import select

from fde_api.auth.models import User
from fde_api.auth.passwords import verify_password
from fde_api.extensions import db
from fde_api.simulation.failure_analyzer import FAILURE_CATEGORIES, analyze_failures
from fde_api.simulation.models import (
    ImprovementProposal,
    SimulationEvaluation,
    SimulationFinding,
    SimulationRun,
    SimulationTrace,
)
from fde_api.simulation.service import ScenarioServiceError, _require_level

# 提案状态机：draft → in_review → approved | rejected（**止于 approved**）
PROPOSAL_STATUSES = ("draft", "in_review", "approved", "rejected")
# 提案可指向的改进对象（只提案，不落地）
PROPOSAL_TARGET_KINDS = (
    "prompt",
    "skill",
    "workflow_template",
    "ontology",
    "rule",
    "case",
)
# 发现状态
FINDING_STATUSES = ("open", "confirmed", "rejected")


def _run_split(session, run_id: str) -> str | None:
    """取运行所属数据集（用于「改进只许用 train 集失败」纪律）。"""
    from fde_api.simulation.models import SimulationRun

    row = session.get(SimulationRun, run_id)
    return row.split if row is not None else None


def _finding_fingerprint(finding_ids: list[str], target: dict[str, Any]) -> str:
    canonical = json.dumps(
        {"findings": sorted(finding_ids), "target": target},
        sort_keys=True,
        ensure_ascii=False,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def _serialize_finding(row: SimulationFinding) -> dict[str, Any]:
    return {
        "id": row.id,
        "run_id": row.run_id,
        "evaluation_id": row.evaluation_id,
        "code": row.code,
        "title": row.title,
        "severity": row.severity,
        "dimension": row.dimension,
        "description": row.description,
        "evidence_refs": list(row.evidence_refs_json or []),
        "root_causes": list(row.root_causes_json or []),
        "status": row.status,
        "detail": dict(row.detail_json or {}),
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def _serialize_proposal(row: ImprovementProposal) -> dict[str, Any]:
    return {
        "id": row.id,
        "proposal_key": row.proposal_key,
        "title": row.title,
        "problem": row.problem,
        "finding_ids": list(row.finding_ids_json or []),
        "finding_codes": list(row.finding_codes_json or []),
        "target": dict(row.target_json or {}),
        "current_version": row.current_version,
        "proposed_version": row.proposed_version,
        "change_summary": row.change_summary,
        "expected_effect": dict(row.expected_effect_json or {}),
        "impact_scope": list(row.impact_scope_json or []),
        "regression_plan": dict(row.regression_plan_json or {}),
        "override_json": dict(row.override_json or {}),
        "status": row.status,
        "decided_by_user_id": row.decided_by_user_id,
        "decided_at": row.decided_at,
        "note": row.note,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def list_findings(*, actor: User, run_id: str | None = None) -> dict[str, Any]:
    """失败发现清单。"""
    _require_level(actor)
    with db.session() as session:
        stmt = select(SimulationFinding)
        if run_id:
            stmt = stmt.where(SimulationFinding.run_id == run_id)
        rows = list(session.scalars(stmt.order_by(SimulationFinding.created_at, SimulationFinding.id)))
        return {"items": [_serialize_finding(row) for row in rows], "total": len(rows)}


def analyze_run(*, actor: User, run_id: str) -> dict[str, Any]:
    """对一次运行做失败分析，落 ``simulation_findings`` 行。

    幂等：同 (run_id, evaluation_id, code) 只留一行（重跑分析不增殖）。
    """
    _require_level(actor)
    with db.session() as session:
        run = session.get(SimulationRun, run_id)
        if run is None:
            raise ScenarioServiceError("not_found", "模拟运行不存在。", 404)
        evaluation = session.scalar(
            select(SimulationEvaluation)
            .where(
                SimulationEvaluation.run_id == run_id,
                SimulationEvaluation.layer == "deterministic",
            )
            .order_by(SimulationEvaluation.created_at.desc())
        )
        if evaluation is None:
            raise ScenarioServiceError(
                "not_found", "该运行尚无规则层评估结论，先执行评估。", 404
            )
        traces = [
            {
                "seq": row.seq,
                "event_type": row.event_type,
                "payload": dict(row.payload_json or {}),
                "tool_call": dict(row.tool_call_json) if row.tool_call_json else None,
            }
            for row in session.scalars(
                select(SimulationTrace)
                .where(SimulationTrace.run_id == run_id)
                .order_by(SimulationTrace.seq)
            )
        ]
        evaluation_payload = {
            "scores": dict(evaluation.scores_json or {}),
            "hard_failures": list(evaluation.hard_failures_json or []),
        }
        findings = analyze_failures(
            evaluation=evaluation_payload, traces=traces
        )

        existing = {
            (row.evaluation_id, row.code)
            for row in session.scalars(
                select(SimulationFinding).where(SimulationFinding.run_id == run_id)
            )
        }
        created: list[SimulationFinding] = []
        for finding in findings:
            if (evaluation.id, finding.code) in existing:
                continue
            row = SimulationFinding(
                run_id=run.id,
                evaluation_id=evaluation.id,
                code=finding.code,
                title=finding.title,
                severity=finding.severity,
                dimension=finding.dimension,
                description=finding.description,
                evidence_refs_json=[dict(ref) for ref in finding.evidence_refs],
                root_causes_json=[cause.to_json() for cause in finding.root_causes],
                status="open",
                detail_json=dict(finding.detail),
            )
            session.add(row)
            created.append(row)
        session.flush()
        session.commit()
        return {
            "run_id": run_id,
            "created": len(created),
            "items": [
                _serialize_finding(row)
                for row in session.scalars(
                    select(SimulationFinding)
                    .where(SimulationFinding.run_id == run_id)
                    .order_by(SimulationFinding.code)
                )
            ],
        }


def create_proposal(*, actor: User, payload: dict[str, Any]) -> dict[str, Any]:
    """由失败发现生成改进提案（**只提案，不落地**）。"""
    _require_level(actor)
    finding_ids = payload.get("finding_ids")
    if not isinstance(finding_ids, list) or not finding_ids:
        raise ScenarioServiceError("invalid_request", "finding_ids 必填且必须是非空数组。")
    target = payload.get("target")
    if not isinstance(target, dict):
        raise ScenarioServiceError("invalid_request", "target 必填且必须是对象。")
    target_kind = target.get("kind")
    if target_kind not in PROPOSAL_TARGET_KINDS:
        raise ScenarioServiceError(
            "invalid_request", "target.kind 取值非法。", 400, {"allowed": list(PROPOSAL_TARGET_KINDS)}
        )
    target_ref = target.get("ref")
    if not isinstance(target_ref, str) or not target_ref.strip():
        raise ScenarioServiceError("invalid_request", "target.ref 必填。")

    with db.session() as session:
        rows = list(
            session.scalars(
                select(SimulationFinding).where(SimulationFinding.id.in_(finding_ids))
            )
        )
        if len(rows) != len(set(finding_ids)):
            raise ScenarioServiceError("not_found", "部分失败发现不存在。", 404)
        # 数据集纪律（G6）：改进只能基于**训练集**的失败——用回归/盲测集的失败
        # 去提改进等于在评测集上调参，会让回归与盲测失去意义。
        non_train = [
            row.code
            for row in rows
            if row.run_id
            and _run_split(session, row.run_id) not in (None, "train")
        ]
        if non_train:
            raise ScenarioServiceError(
                "conflict",
                "改进提案只能引用训练集（train）的失败发现；"
                "回归集与盲测集的失败只用于检验，不得据此调参。",
                409,
                {"finding_codes": non_train},
            )
        confirmed = [
            row
            for row in rows
            if any(
                str(cause.get("confidence")) == "confirmed"
                for cause in (row.root_causes_json or [])
                if isinstance(cause, dict)
            )
        ]
        if not confirmed:
            raise ScenarioServiceError(
                "conflict",
                "只有 confirmed 根因可生成改进提案；疑似根因请先人工复核。",
                409,
                {"finding_codes": [row.code for row in rows]},
            )

        fingerprint = _finding_fingerprint(
            [row.id for row in rows], {"kind": target_kind, "ref": target_ref.strip()}
        )
        clash = session.scalar(
            select(ImprovementProposal).where(
                ImprovementProposal.fingerprint == fingerprint
            )
        )
        if clash is not None:
            raise ScenarioServiceError(
                "conflict", "同一组失败发现与改进对象已有提案。", 409, {"proposal_id": clash.id}
            )

        codes = sorted({row.code for row in rows})
        meta = FAILURE_CATEGORIES.get(codes[0], {})
        title = payload.get("title") or f"改进：{meta.get('title', codes[0])}"
        current_version = str(payload.get("current_version") or "v1")
        proposed_version = str(payload.get("proposed_version") or "v2")
        if proposed_version == current_version:
            raise ScenarioServiceError(
                "invalid_request", "proposed_version 必须与 current_version 不同。"
            )
        change_summary = payload.get("change_summary")
        if not isinstance(change_summary, str) or not change_summary.strip():
            raise ScenarioServiceError("invalid_request", "change_summary 必填。")
        override = payload.get("override_json")
        if override is not None and not isinstance(override, dict):
            raise ScenarioServiceError("invalid_request", "override_json 必须是对象。")
        if isinstance(override, dict) and override:
            run_config = override.get("run_config")
            if not isinstance(run_config, dict):
                raise ScenarioServiceError(
                    "invalid_request", "override_json 只接受 {'run_config': {...}} 形状。"
                )

        row = ImprovementProposal(
            proposal_key=f"PROP-{fingerprint[:8].upper()}",
            title=str(title)[:160],
            problem=str(payload.get("problem") or meta.get("title") or "")[:2000],
            finding_ids_json=[row_id for row_id in finding_ids],
            finding_codes_json=codes,
            fingerprint=fingerprint,
            target_json={"kind": target_kind, "ref": target_ref.strip()},
            current_version=current_version,
            proposed_version=proposed_version,
            change_summary=change_summary.strip(),
            expected_effect_json=dict(payload.get("expected_effect") or {}),
            impact_scope_json=list(payload.get("impact_scope") or [meta.get("target_scope", "")]),
            regression_plan_json=dict(payload.get("regression_plan") or {}),
            override_json=dict(override or {}),
            status="draft",
            created_by_user_id=actor.id,
        )
        session.add(row)
        session.flush()
        session.commit()
        return _serialize_proposal(row)


def list_proposals(
    *, actor: User, status: str | None = None, target_kind: str | None = None
) -> dict[str, Any]:
    """改进提案清单。"""
    _require_level(actor)
    if status is not None and status not in PROPOSAL_STATUSES:
        raise ScenarioServiceError("invalid_request", "status 取值非法。")
    with db.session() as session:
        stmt = select(ImprovementProposal)
        if status:
            stmt = stmt.where(ImprovementProposal.status == status)
        rows = list(session.scalars(stmt.order_by(ImprovementProposal.created_at.desc())))
        if target_kind:
            rows = [
                row
                for row in rows
                if str((row.target_json or {}).get("kind")) == target_kind
            ]
        return {"items": [_serialize_proposal(row) for row in rows], "total": len(rows)}


def get_proposal(*, actor: User, proposal_id: str) -> dict[str, Any]:
    """提案详情。"""
    _require_level(actor)
    with db.session() as session:
        row = session.get(ImprovementProposal, proposal_id)
        if row is None:
            raise ScenarioServiceError("not_found", "改进提案不存在。", 404)
        return _serialize_proposal(row)


def update_proposal(*, actor: User, proposal_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    """编辑提案（仅 draft 态）。"""
    _require_level(actor)
    with db.session() as session:
        row = session.get(ImprovementProposal, proposal_id)
        if row is None:
            raise ScenarioServiceError("not_found", "改进提案不存在。", 404)
        if row.status != "draft":
            raise ScenarioServiceError(
                "conflict", "只有草稿态提案可编辑。", 409, {"status": row.status}
            )
        if "title" in payload:
            row.title = str(payload["title"])[:160]
        if "problem" in payload:
            row.problem = str(payload["problem"])[:2000]
        if "change_summary" in payload:
            row.change_summary = str(payload["change_summary"])
        if "expected_effect" in payload and isinstance(payload["expected_effect"], dict):
            row.expected_effect_json = dict(payload["expected_effect"])
        if "impact_scope" in payload and isinstance(payload["impact_scope"], list):
            row.impact_scope_json = list(payload["impact_scope"])
        if "regression_plan" in payload and isinstance(payload["regression_plan"], dict):
            row.regression_plan_json = dict(payload["regression_plan"])
        if "override_json" in payload and isinstance(payload["override_json"], dict):
            row.override_json = dict(payload["override_json"])
        if payload.get("status") == "in_review":
            row.status = "in_review"
        session.flush()
        session.commit()
        return _serialize_proposal(row)


def decide_proposal(
    *, actor: User, proposal_id: str, payload: dict[str, Any]
) -> dict[str, Any]:
    """审批提案：approve / reject。

    **审批 ≠ 发布**——approved 之后仍**没有**任何自动落地路径（G1 §10.4）。
    需 project_lead/admin + **当前账号密码确认**（比照 `control/api_actions` 范式）。
    """
    _require_level(actor)
    if actor.role not in ("admin", "project_lead"):
        raise ScenarioServiceError("forbidden", "提案审批需项目负责人或管理员。", 403)
    approve = payload.get("approve")
    if not isinstance(approve, bool):
        raise ScenarioServiceError("invalid_request", "approve 必须是布尔值。")
    password = payload.get("password")
    if not isinstance(password, str) or not password or len(password) > 1024:
        raise ScenarioServiceError("invalid_request", "password 必填（当前账号密码确认）。")
    note = payload.get("note")
    if not isinstance(note, str) or not note.strip():
        raise ScenarioServiceError("invalid_request", "note 必填（审批必须留理由）。")

    with db.session() as session:
        row = session.get(ImprovementProposal, proposal_id)
        if row is None:
            raise ScenarioServiceError("not_found", "改进提案不存在。", 404)
        if row.status not in ("draft", "in_review"):
            raise ScenarioServiceError(
                "conflict", "该提案已审批过，不可重复审批。", 409, {"status": row.status}
            )
        if not verify_password(actor.password_hash, password):
            raise ScenarioServiceError("invalid_password", "当前账号密码不正确。", 403)
        row.status = "approved" if approve else "rejected"
        row.decided_by_user_id = actor.id
        row.decided_at = _now_iso()
        row.note = note.strip()
        session.flush()
        session.commit()
        return _serialize_proposal(row)


def _now_iso() -> str:
    from datetime import UTC, datetime

    return datetime.now(UTC).isoformat()
