"""改进提案服务（G5，G1 §10.3/§10.4；N4 G-11 语义收口）。

**「只提案，落地只许经发布通道记账」的强制落点（P8，N4 改语义不删钉）**：
1. 提案状态机 ``draft → in_review → approved → published``——``published``
   **只许**由 ``release_channel`` 写入（发布/回滚都是受控记账，可回滚）；
2. 本服务**不提供**任何写生产 Prompt / Skill / Workflow / 本体的函数；发布/
   回滚也不触碰正文（N4 边界「不自动上线提示词改动」——正文仍由人工在治理
   面实施，``target_ref`` + ``change_summary`` + ``proposed_version`` 只是文本）；
3. 静态钉（N4 新语义）：全仓 ``ImprovementProposal`` 引用面 ⊆
   {models, improvement_service, release_channel}——生产模块要动提案只能走
   ``release_channel`` 单点；
4. 复审工单（G-14）的写入执行点也在 ``release_channel.create_review_ticket``。

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
from fde_api.simulation.failure_analyzer import (
    FAILURE_CATEGORIES,
    analyze_failures,
    analyze_human_layer,
    analyze_model_layer,
)
from fde_api.simulation.improvement_draft import (
    MAX_LESSON_TEXT,
    MAX_OVERLAY_FRAGMENT,
    PAYLOAD_KINDS,
    candidate_payload_sha256,
)
from fde_api.simulation.models import (
    ImprovementProposal,
    SimulationEvaluation,
    SimulationFinding,
    SimulationRun,
    SimulationScenario,
    SimulationTrace,
)
from fde_api.simulation.service import ScenarioServiceError, _require_level

# 提案状态机：draft → in_review → approved → published | rejected
# （published 仅经 release_channel；回滚 published → approved）
PROPOSAL_STATUSES = ("draft", "in_review", "approved", "rejected", "published")
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


def _finding_fingerprint(
    finding_ids: list[str], target: dict[str, Any], *, payload_sha256: str = ""
) -> str:
    """幂等指纹（学习闭环 2.0 L4 指纹修正，评审 P0-Ⅶ）：canonical 增
    ``payload_sha256``（无 payload 取固定空值）——「同 findings 同 target 不同
    候选载荷」的 AI 重新起草不再被旧指纹 409 挡死；老提案指纹（无该键）与新
    格式互不碰撞（老提案互不误伤、同 payload 重复提交幂等保留）。"""
    canonical = json.dumps(
        {
            "findings": sorted(finding_ids),
            "target": target,
            "payload_sha256": payload_sha256,
        },
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
    release = dict(row.release_json or {})
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
        "candidate_payload": dict(row.candidate_payload_json or {}),
        "status": row.status,
        "release": release or None,
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
    """对一次运行做失败分析（三源化，学习闭环 2.0 L4 断点②）。

    - **L-A 规则层**：既有 FA-01..10 映射不动（唯一可判硬性失败的来源）；
    - **L-B 模型层**：查询钉 ``layer=="model" AND evaluator_id=="model:server"``
      （stub 替身行有真实 verdict，不钉 evaluator 会误当真模型层——评审 P0-Ⅵ），
      ``verdict!="unavailable"`` 二道 ⇒ 低分产 ``likely`` 发现（不解锁提案）；
    - **L-C 人工层**：``layer=="human"`` 按 ``created_at`` 最新一行（人工插行
      无幂等，按 get_evaluation_report 同语义收敛为最新）⇒ 产 ``confirmed``
      发现；note 全文先过答案句黑名单。

    幂等：同 (run_id, evaluation_id, code) 只留一行（重跑分析不增殖；三源各挂
    各的评估行，唯一约束天然分流）。
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
        findings = list(
            analyze_failures(evaluation=evaluation_payload, traces=traces)
        )

        # ---- L-B：真模型层（model:server 钉死；unavailable 二道） ------------
        model_evaluation = session.scalar(
            select(SimulationEvaluation)
            .where(
                SimulationEvaluation.run_id == run_id,
                SimulationEvaluation.layer == "model",
                SimulationEvaluation.evaluator_id == "model:server",
                SimulationEvaluation.verdict != "unavailable",
            )
            .order_by(
                SimulationEvaluation.created_at.desc(), SimulationEvaluation.id.desc()
            )
        )
        if model_evaluation is not None:
            findings.extend(
                analyze_model_layer(
                    evaluation={
                        "scores": dict(model_evaluation.scores_json or {}),
                        "hard_failures": [],
                    }
                )
            )

        # ---- L-C：人工终裁最新行（created_at 收敛） --------------------------
        human_evaluation = session.scalar(
            select(SimulationEvaluation)
            .where(
                SimulationEvaluation.run_id == run_id,
                SimulationEvaluation.layer == "human",
            )
            .order_by(
                SimulationEvaluation.created_at.desc(), SimulationEvaluation.id.desc()
            )
        )
        if human_evaluation is not None:
            findings.extend(
                analyze_human_layer(
                    evaluation={
                        "scores": dict(human_evaluation.scores_json or {}),
                        "hard_failures": list(human_evaluation.hard_failures_json or []),
                        "verdict": human_evaluation.verdict,
                        "note": human_evaluation.note or "",
                    },
                    blacklist=_answer_blacklist(session, run),
                )
            )

        existing = {
            (row.evaluation_id, row.code)
            for row in session.scalars(
                select(SimulationFinding).where(SimulationFinding.run_id == run_id)
            )
        }
        created: list[SimulationFinding] = []
        evaluation_ids = {
            "deterministic": evaluation.id,
            "model": model_evaluation.id if model_evaluation is not None else None,
            "human": human_evaluation.id if human_evaluation is not None else None,
        }
        for finding in findings:
            source = str((finding.detail or {}).get("source") or "deterministic")
            layer = {"model_server": "model", "human": "human"}.get(source, "deterministic")
            owner_id = evaluation_ids.get(layer) or evaluation.id
            if (owner_id, finding.code) in existing:
                continue
            row = SimulationFinding(
                run_id=run.id,
                evaluation_id=owner_id,
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


def _answer_blacklist(session: Any, run: SimulationRun) -> tuple[str, ...]:
    """答案句黑名单：该 run 场景 reference 的 rubric 三桶＋期望结果＋验收标准
    原文句（L-C note 洗刷用；评分侧数据，只进黑名单比对，不落 finding）。"""
    scenario = session.get(SimulationScenario, run.scenario_id)
    if scenario is None or not scenario.reference_json:
        return ()
    reference = dict(scenario.reference_json or {})
    rubric = reference.get("rubric") if isinstance(reference.get("rubric"), dict) else {}
    sentences: list[str] = []
    for bucket in ("must_identify", "must_avoid", "must_produce"):
        items = rubric.get(bucket) if isinstance(rubric, dict) else None
        if isinstance(items, list):
            sentences.extend(str(item) for item in items)
    for key in ("expected_outcomes", "acceptance_criteria"):
        items = reference.get(key)
        if isinstance(items, list):
            sentences.extend(str(item) for item in items)
    return tuple(sentence for sentence in sentences if sentence.strip())


def create_proposal(*, actor: User, payload: dict[str, Any]) -> dict[str, Any]:
    """由失败发现生成改进提案（**只提案；落地只许经发布通道记账**）。"""
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
        # 三载体候选载荷（L4）：AI 蒸馏返件经人工采纳后随提案入档——与
        # override_json 分工：override＝run 参数；candidate_payload＝三载体载荷
        # （L5 发布通道的执行输入）。只做形状与长度校验；发布闸在 release_channel。
        candidate_payload = payload.get("candidate_payload")
        if candidate_payload is not None and not isinstance(candidate_payload, dict):
            raise ScenarioServiceError("invalid_request", "candidate_payload 必须是对象。")
        if isinstance(candidate_payload, dict) and candidate_payload:
            unknown_kinds = set(candidate_payload) - set(PAYLOAD_KINDS)
            if unknown_kinds:
                raise ScenarioServiceError(
                    "invalid_request",
                    "candidate_payload 键闭集为三载体载荷类型。",
                    400,
                    {"allowed": list(PAYLOAD_KINDS), "unknown": sorted(unknown_kinds)},
                )
            lesson = candidate_payload.get("lesson_entry")
            if isinstance(lesson, dict) and len(str(lesson.get("text") or "")) > MAX_LESSON_TEXT:
                raise ScenarioServiceError(
                    "invalid_request", f"lesson_entry.text 超长（≤{MAX_LESSON_TEXT} 字）。"
                )
            overlay = candidate_payload.get("prompt_overlay_fragment")
            if isinstance(overlay, dict) and len(
                str(overlay.get("fragment") or "")
            ) > MAX_OVERLAY_FRAGMENT:
                raise ScenarioServiceError(
                    "invalid_request",
                    f"prompt_overlay_fragment.fragment 超长（≤{MAX_OVERLAY_FRAGMENT} 字）。",
                )
            skill_draft = candidate_payload.get("skill_version_draft")
            if isinstance(skill_draft, dict):
                # Skill 双闸链（L5 §2.5B，评审 P0-Ⅳ）：AI 蒸馏与提案候选载荷禁 personal
                # scope——personal Skill 保存即 published 零闸会绕过全套回归与密码闸。
                if str(skill_draft.get("scope") or "").strip().lower() == "personal":
                    raise ScenarioServiceError(
                        "invalid_request",
                        "skill_version_draft 禁止 personal scope（个人 Skill 保存即生效，必须走公共受控治理链）。",
                        400,
                        {"forbidden_scope": "personal"},
                    )
                skill_ref = skill_draft.get("skill_ref")
                if isinstance(skill_ref, str) and skill_ref.strip():
                    from fde_api.control.models import SkillDefinition

                    skill_row = session.get(SkillDefinition, skill_ref.strip())
                    if skill_row is not None and skill_row.scope == "personal":
                        raise ScenarioServiceError(
                            "conflict",
                            "skill_version_draft.skill_ref 不得指向个人（personal）Skill。",
                            409,
                            {"skill_ref": skill_ref.strip(), "scope": "personal"},
                        )

        fingerprint = _finding_fingerprint(
            [row.id for row in rows],
            {"kind": target_kind, "ref": target_ref.strip()},
            payload_sha256=candidate_payload_sha256(candidate_payload),
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
            candidate_payload_json=dict(candidate_payload or {}),
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

    **审批 ≠ 发布**——approved 之后发布须经 ``release_channel`` 受控通道
    （admin＋密码＋回归计划在案＋审计＋可回滚；N4 G-11）。
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
