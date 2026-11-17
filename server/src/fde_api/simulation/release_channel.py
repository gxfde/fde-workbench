"""改进提案受控发布通道（AI 原生化 N4，G-11）——全仓唯一的发布/回滚/工单写入点。

**语义收口（N4：静态钉由「零写入」改为「只许经发布通道写」）**：
- 状态机扩展 ``approved → published``（发布）与 ``published → approved``
  （回滚），两态迁移**只许**经本模块；
- **发布 ≠ 自动落地**（任务书 N4 边界）：本通道是**受控、审计、可回滚的
  记账面**——生产提示词 / Skill / 本体**正文零触碰**（N6 纪律：提示词正文
  不入库、不自动改），正文改动仍由人工在治理面实施；
- 发布闸四件：admin ＋ 当前账号密码确认 ＋ 提案须 ``approved`` ＋ 回归计划
  在案（``regression_plan_json`` 非空——没回归计划不给发布，风险③防后门）；
  note 必填留痕；
- 回滚闸：admin ＋ 密码 ＋ note；``published → approved``，``release_json``
  累积 ``rollback`` 子对象（原发布字段保留——审计链不断，可回滚路径有钉）；
- 复审工单（G-14 消费方）：``create_review_ticket`` 生成 draft 提案
  （target=prompt 文本指针），指纹含 UTC 日（每规则每日至多一张），零生产写。

静态钉（``tests/test_simulation_improvement.py``）：全仓 ``ImprovementProposal``
引用面 ⊆ {models, improvement_service, release_channel}；发布/回滚函数只许
住在本模块且必须带密码闸。
"""
from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select

from fde_api.agents.models import AgentLesson
from fde_api.auth.models import User
from fde_api.auth.passwords import verify_password
from fde_api.extensions import db
from fde_api.simulation.improvement_service import _serialize_proposal
from fde_api.simulation.models import ImprovementProposal, RegressionResult
from fde_api.simulation.service import ScenarioServiceError, _require_level
from fde_api.workbench.models import OperationEvent, PromptOverlay

# 模拟域事件类型（直接落 operation_events，project_id 恒 None——模拟对象不属于
# 任何真实项目，service.py 同口径）。
EVENT_RELEASED = "simulation.proposal_released"
EVENT_ROLLED_BACK = "simulation.proposal_release_rolled_back"
EVENT_TICKET_CREATED = "simulation.review_ticket_created"

# 复审工单指纹的来源标识（含 UTC 日 ⇒ 每规则每日至多一张，重复评估幂等）。
_TICKET_SOURCE = "metrics_v31_ticket"

# 三载体候选载荷执行器（L5 热生效；写引用面 ⊆ {各自 models, 本模块}——静态钉
# tests/test_simulation_release_channel.py AST 手法）。lesson/overlay 发布＝落
# status=published 载荷行（热生效，零改码）、回滚＝retired（立即消失）；skill
# 双闸链＝发布仅记账 skill_ref＋test_report_regression_id，热生效走既有
# publish_skill（系统操作员＋密码＋test_report），本模块**不**代发起。
_SKILL_BRANCH = "skill_version_draft"
_LESSON_BRANCH = "lesson_entry"
_OVERLAY_BRANCH = "prompt_overlay_fragment"


def _latest_regression_result(session, proposal_id: str) -> RegressionResult | None:
    """该提案最近一次回归结果行（overfit 闸与 skill test_report 共用取行口径）。"""
    return session.scalars(
        select(RegressionResult).where(RegressionResult.proposal_id == proposal_id).order_by(
            RegressionResult.created_at.desc(), RegressionResult.id.desc()
        )
    ).first()


def _check_overfit_gate(session, row: ImprovementProposal) -> None:
    """过拟合发布闸（评审 P1-1）：最近一次 RegressionResult.overfit_risk=True ⇒ 409。"""
    latest = _latest_regression_result(session, row.id)
    if latest is not None and bool(latest.overfit_risk):
        raise ScenarioServiceError(
            "conflict",
            "发布闸：该提案最近一次回归标记过拟合风险（overfit_risk=True），机械拦截发布。",
            409,
            {"regression_result_id": latest.id, "overfit_risk": True},
        )


def _payload_branches(row: ImprovementProposal) -> dict[str, Any]:
    payload = row.candidate_payload_json or {}
    return {key: payload[key] for key in (_LESSON_BRANCH, _SKILL_BRANCH, _OVERLAY_BRANCH) if payload.get(key)}


def _materialize_payload(session, row: ImprovementProposal) -> dict[str, Any]:
    """发布执行器：按 candidate_payload_json 在场键各支独立落表（热生效）。

    各支缺省（键不在场）＝零写入；全支不在场＝纯记账发布（N4 语义不变）。
    载荷键形状以 improvement_draft._validate_group 为准（允许名单投影）。
    """
    branches = _payload_branches(row)
    materialized: dict[str, Any] = {}
    latest = _latest_regression_result(session, row.id)
    if _LESSON_BRANCH in branches:
        from fde_api.agents.lessons import seed_ids_and_hashes

        entry = branches[_LESSON_BRANCH]
        text = str(entry.get("text") or "").strip()
        if not text:
            raise ScenarioServiceError(
                "invalid_request", "lesson_entry.text 不得为空。", 409
            )
        entry_id = f"LESS-DYN-{row.proposal_key}"
        text_sha = hashlib.sha256(text.encode("utf-8")).hexdigest()
        seed_ids, seed_hashes = seed_ids_and_hashes()
        if entry_id in seed_ids:
            raise ScenarioServiceError(
                "conflict",
                "动态经验卡 ID 与静态 seeds 条目冲突，拒绝写入。",
                409,
                {"entry_id": entry_id},
            )
        if text_sha in seed_hashes:
            raise ScenarioServiceError(
                "conflict",
                "动态经验卡正文 sha256 与静态 seeds 条目重复，拒绝写入。",
                409,
                {"text_sha256": text_sha},
            )
        existing_lesson = session.scalar(
            select(AgentLesson).where(AgentLesson.text_sha256 == text_sha)
        )
        if existing_lesson is not None and existing_lesson.source_proposal_id != row.id:
            raise ScenarioServiceError(
                "conflict",
                "动态经验卡正文 sha256 已存在，拒绝重复写入。",
                409,
                {"existing_entry_id": existing_lesson.entry_id},
            )
        raw_tags = entry.get("capability_tags")
        if isinstance(raw_tags, list) and raw_tags:
            tags = [str(t) for t in raw_tags if str(t).strip()]
        elif isinstance(entry.get("tier"), str) and str(entry.get("tier")).strip():
            tags = [str(entry.get("tier")).strip()]
        else:
            tags = []
        raw_industries = entry.get("industries")
        industries = (
            [str(ind) for ind in raw_industries if str(ind).strip() and str(ind).strip() != "general"]
            if isinstance(raw_industries, list)
            else []
        )
        if existing_lesson is not None and existing_lesson.source_proposal_id == row.id:
            existing_lesson.status = "published"
            lesson = existing_lesson
        else:
            lesson = AgentLesson(
                entry_id=entry_id,
                capability_tags=tags,
                industries=industries,
                text=text,
                text_sha256=text_sha,
                source_ref=row.proposal_key,
                source_proposal_id=row.id,
                status="published",
            )
            session.add(lesson)
        session.flush()
        materialized["lesson"] = {"entry_id": lesson.entry_id, "text_sha256": lesson.text_sha256}
    if _OVERLAY_BRANCH in branches:
        from fde_api.ai.overlays import (
            MAX_NGRAM_OVERLAP_RATIO,
            ngram_overlap_ratio,
            purpose_allowed,
            resolve_base_prompt_for_purpose,
            validate_overlay_fragment,
        )

        entry = branches[_OVERLAY_BRANCH]
        purpose_key = str(entry.get("purpose_key") or "").strip()
        if not purpose_allowed(purpose_key):
            raise ScenarioServiceError(
                "invalid_request",
                "prompt_overlay_fragment.purpose_key 不在允许的内网 purpose 白名单内。",
                409,
                {"purpose_key": purpose_key},
            )
        fragment = str(entry.get("fragment") or "").strip()
        violation = validate_overlay_fragment(fragment)
        if violation is not None:
            raise ScenarioServiceError(
                "invalid_request",
                f"prompt_overlay_fragment 未通过句式静态闸（{violation}）。",
                409,
                {"violation": violation},
            )
        base_prompt, _ = resolve_base_prompt_for_purpose(purpose_key)
        overlap = ngram_overlap_ratio(fragment, base_prompt) if base_prompt else 0.0
        if overlap > MAX_NGRAM_OVERLAP_RATIO:
            raise ScenarioServiceError(
                "conflict",
                "prompt_overlay_fragment 与既有静态提示词 n-gram 重叠率过高（防洗稿闸拦截）。",
                409,
                {"ngram_overlap_ratio": round(overlap, 4)},
            )
        min_version = entry.get("min_prompt_version")
        existing_overlay = session.scalar(
            select(PromptOverlay).where(PromptOverlay.source_proposal_id == row.id)
        )
        if existing_overlay is not None:
            existing_overlay.status = "published"
            overlay = existing_overlay
        else:
            overlay = PromptOverlay(
                purpose_key=purpose_key,
                fragment=fragment,
                content_sha256=hashlib.sha256(fragment.encode("utf-8")).hexdigest(),
                min_prompt_version=str(min_version).strip() if isinstance(min_version, str) and min_version.strip() else None,
                source_proposal_id=row.id,
                status="published",
            )
            session.add(overlay)
        session.flush()
        materialized["overlay"] = {"overlay_id": overlay.id, "content_sha256": overlay.content_sha256}
    if _SKILL_BRANCH in branches:
        entry = branches[_SKILL_BRANCH]
        if str(entry.get("scope") or "").strip().lower() == "personal":
            raise ScenarioServiceError(
                "invalid_request",
                "skill_version_draft 禁止 personal scope。",
                409,
            )
        # 双闸链记账支：只记账 skill_ref＋test_report_regression_id（最近一次回归结果），
        # 不 materialize 版本行、不代发起 publish_skill——热生效须人工走既有闸。
        skill_id = entry.get("skill_ref")
        if not isinstance(skill_id, str) or not skill_id:
            raise ScenarioServiceError(
                "invalid_request",
                "skill_version_draft 载荷须含 skill_ref（目标 SkillDefinition.id）。",
                409,
            )
        from fde_api.control.models import SkillDefinition

        skill_row = session.get(SkillDefinition, skill_id)
        if skill_row is not None and skill_row.scope == "personal":
            raise ScenarioServiceError(
                "conflict",
                "skill_version_draft.skill_ref 不得指向个人（personal）Skill。",
                409,
                {"skill_ref": skill_id, "scope": "personal"},
            )
        materialized["skill"] = {
            "skill_ref": skill_id,
            "test_report_regression_id": latest.id if latest is not None else None,
            "publish_via": "publish_skill",
            "note": "发布通道仅记账；热生效须经既有 publish_skill 闸（系统操作员＋密码）。",
        }
    return materialized


def _retire_payload_rows(session, row: ImprovementProposal) -> dict[str, Any]:
    """回滚执行器：本提案产生的 lesson/overlay 行 status⇒retired（立即消失）。

    skill 支无本模块写行（双闸链走 publish_skill 独立闸）——回滚＝release_json
    累积 rollback 子对象，skill 版本行不可变、指针不动（审计链不断）。
    """
    retired: dict[str, Any] = {"lesson": [], "overlay": []}
    for lesson in session.scalars(
        select(AgentLesson).where(AgentLesson.source_proposal_id == row.id)
    ):
        lesson.status = "retired"
        retired["lesson"].append(lesson.entry_id)
    for overlay in session.scalars(
        select(PromptOverlay).where(PromptOverlay.source_proposal_id == row.id)
    ):
        overlay.status = "retired"
        retired["overlay"].append(overlay.id)
    session.flush()
    return retired


def _require_admin(actor: User) -> None:
    _require_level(actor)
    if actor.role != "admin":
        raise ScenarioServiceError(
            "forbidden", "提案发布/回滚需平台管理员。", 403
        )


def _require_confirmation(
    payload: dict[str, Any], *, actor: User
) -> str:
    """密码＋note 双必填（比照 decide_proposal：密码确认范式，note 必须留理由）。"""
    password = payload.get("password")
    if not isinstance(password, str) or not password or len(password) > 1024:
        raise ScenarioServiceError(
            "invalid_request", "password 必填（当前账号密码确认）。"
        )
    note = payload.get("note")
    if not isinstance(note, str) or not note.strip():
        raise ScenarioServiceError("invalid_request", "note 必填（发布必须留理由）。")
    if not verify_password(actor.password_hash, password):
        raise ScenarioServiceError("invalid_password", "当前账号密码不正确。", 403)
    return note.strip()


def _release_event(
    session, actor: User, row: ImprovementProposal, event_type: str, changes: dict[str, Any]
) -> None:
    session.add(
        OperationEvent(
            actor_user_id=actor.id,
            project_id=None,
            target_type="improvement_proposal",
            target_id=row.id,
            event_type=event_type,
            changes=changes,
        )
    )


def release_proposal(*, actor: User, proposal_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    """发布已批准提案（G-11 受控发布通道；admin＋密码＋回归计划在案）。"""
    _require_admin(actor)
    note = _require_confirmation(payload, actor=actor)
    with db.session() as session:
        row = session.get(ImprovementProposal, proposal_id)
        if row is None:
            raise ScenarioServiceError("not_found", "改进提案不存在。", 404)
        if row.status == "published":
            raise ScenarioServiceError(
                "conflict", "该提案已发布。", 409, {"status": row.status}
            )
        if row.status != "approved":
            raise ScenarioServiceError(
                "conflict", "只有已批准（approved）的提案可发布。", 409, {"status": row.status}
            )
        if not (row.regression_plan_json or {}):
            raise ScenarioServiceError(
                "conflict",
                "发布闸：提案须附回归计划（regression_plan 非空）方可发布。",
                409,
                {"required": "regression_plan"},
            )
        _check_overfit_gate(session, row)
        release: dict[str, Any] = {
            "released_at": datetime.now(UTC).isoformat(),
            "released_by_user_id": actor.id,
            "released_version": row.proposed_version,
            "release_note": note,
            "rollback": None,
        }
        row.status = "published"
        materialized = _materialize_payload(session, row)
        if materialized:
            release["materialized"] = materialized
        # 落库赋值须在 materialized 合入之后：JSON 列非 mutable，_materialize_payload
        # 内部的 flush 会先把当前值写库，flush 后的原地变更对 DB 不可见
        # （2026-11-17 实弹：活库 release_json 缺 materialized 段——lesson 实际落表）。
        row.release_json = release
        _release_event(
            session,
            actor,
            row,
            EVENT_RELEASED,
            {
                "proposal_key": row.proposal_key,
                "target": dict(row.target_json or {}),
                "fingerprint": row.fingerprint,
                "released_version": release["released_version"],
                "release_note": note,
            },
        )
        session.flush()
        session.commit()
        return _serialize_proposal(row)


def rollback_release(*, actor: User, proposal_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    """回滚已发布提案（published → approved；原发布字段保留，审计链不断）。

    三载体回滚语义：lesson/overlay 载荷行 status⇒retired（下一 run 立即消失）；
    skill 版本行不可变、指针不动（双闸链回滚走既有 rollback_skill 同尺闸）。
    """
    _require_admin(actor)
    note = _require_confirmation(payload, actor=actor)
    with db.session() as session:
        row = session.get(ImprovementProposal, proposal_id)
        if row is None:
            raise ScenarioServiceError("not_found", "改进提案不存在。", 404)
        if row.status != "published":
            raise ScenarioServiceError(
                "conflict", "只有已发布（published）的提案可回滚。", 409, {"status": row.status}
            )
        release = dict(row.release_json or {})
        if release.get("rollback"):
            raise ScenarioServiceError(
                "conflict", "该提案已回滚，不可重复回滚。", 409
            )
        release["rollback"] = {
            "rolled_back_at": datetime.now(UTC).isoformat(),
            "rolled_back_by_user_id": actor.id,
            "rollback_note": note,
        }
        row.status = "approved"
        retired = _retire_payload_rows(session, row)
        if retired["lesson"] or retired["overlay"]:
            release["rollback"]["retired_payload"] = retired
        # 同 release_proposal：赋值须在 retired_payload 合入后（flush 后原地变更不可见）
        row.release_json = release
        _release_event(
            session,
            actor,
            row,
            EVENT_ROLLED_BACK,
            {
                "proposal_key": row.proposal_key,
                "target": dict(row.target_json or {}),
                "fingerprint": row.fingerprint,
                "rollback_note": note,
            },
        )
        session.flush()
        session.commit()
        return _serialize_proposal(row)


def create_review_ticket(
    *, rule: dict[str, Any], evidence: dict[str, Any]
) -> tuple[dict[str, Any] | None, str]:
    """按越限规则生成提示词复审工单（draft 提案；G-14 的唯一写入执行点）。

    指纹 = sha256(规则本体 + UTC 日)——同一规则同日重复评估幂等（已存在 ⇒
    返回 ``(None, "exists")`` 不重复建单）；次日仍越限则生成新工单（自然节
    奔）。工单是 draft 提案：**不触发任何生产写**，人工复核后才走既有审批/
    发布链。
    """
    canonical = json.dumps(
        {"source": _TICKET_SOURCE, "rule": rule, "date": evidence["utc_date"]},
        sort_keys=True,
        ensure_ascii=False,
    )
    fingerprint = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]
    with db.session() as session:
        clash = session.scalar(
            select(ImprovementProposal).where(
                ImprovementProposal.fingerprint == fingerprint
            )
        )
        if clash is not None:
            return None, "exists"
        metric = str(rule["metric"])
        row = ImprovementProposal(
            proposal_key=f"TICKET-{fingerprint[:8].upper()}",
            title=f"指标复审工单：{metric} {rule['op']} {rule['threshold']}"[:160],
            problem=(
                f"v31 指标 {metric} 实测 {evidence['value']}"
                f"（样本 {evidence['sample_size']}）越限"
                f"（规则：{rule['op']} {rule['threshold']}，报告 {evidence['report_generated_at']}）"
                "——按复审规则自动生成，请人工复核对应提示词面。"
            )[:2000],
            finding_ids_json=[],
            finding_codes_json=["metrics_v31_breach"],
            fingerprint=fingerprint,
            target_json={"kind": "prompt", "ref": str(rule["prompt_ref"])},
            current_version="v1",
            proposed_version="v2",
            change_summary=json.dumps(evidence, sort_keys=True, ensure_ascii=False),
            expected_effect_json={},
            impact_scope_json=["metrics_v31"],
            regression_plan_json={},
            override_json={},
            status="draft",
            created_by_user_id=None,
        )
        session.add(row)
        session.flush()
        session.commit()
        return _serialize_proposal(row), "created"


def preview_proposal_release(*, actor: User, proposal_id: str) -> dict[str, Any]:
    """注入闸五件套③：发布前只读预览（呈现三载体落地效果＋Overlay 注入终文并排对比＋近 30 天调用量＋过拟合闸状态）。"""
    _require_level(actor)
    with db.session() as session:
        row = session.get(ImprovementProposal, proposal_id)
        if row is None:
            raise ScenarioServiceError("not_found", "改进提案不存在。", 404)
        branches = _payload_branches(row)
        latest = _latest_regression_result(session, row.id)
        overlay_preview: dict[str, Any] | None = None
        if _OVERLAY_BRANCH in branches:
            from fde_api.ai.overlays import preview_overlay_effect

            entry = branches[_OVERLAY_BRANCH]
            overlay_preview = preview_overlay_effect(
                str(entry.get("purpose_key") or ""),
                str(entry.get("fragment") or ""),
                session=session,
            )
        lesson_preview: dict[str, Any] | None = None
        if _LESSON_BRANCH in branches:
            entry = branches[_LESSON_BRANCH]
            text = str(entry.get("text") or "").strip()
            lesson_preview = {
                "entry_id": f"LESS-DYN-{row.proposal_key}",
                "text": text,
                "text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest() if text else "",
                "capability_tags": list(entry.get("capability_tags") or ([entry["tier"]] if entry.get("tier") else [])),
                "industries": list(entry.get("industries") or []),
            }
        skill_preview: dict[str, Any] | None = None
        if _SKILL_BRANCH in branches:
            entry = branches[_SKILL_BRANCH]
            skill_preview = {
                "skill_ref": entry.get("skill_ref"),
                "summary": entry.get("summary") or entry.get("title"),
                "instructions_delta": entry.get("instructions_delta") or entry.get("instructions"),
                "test_report_regression_id": latest.id if latest is not None else None,
            }
        return {
            "proposal_id": row.id,
            "proposal_key": row.proposal_key,
            "status": row.status,
            "overfit_blocked": bool(latest is not None and latest.overfit_risk),
            "latest_regression_id": latest.id if latest is not None else None,
            "latest_regression_verdict": latest.verdict if latest is not None else None,
            "branches": list(branches.keys()),
            "overlay_preview": overlay_preview,
            "lesson_preview": lesson_preview,
            "skill_preview": skill_preview,
        }

