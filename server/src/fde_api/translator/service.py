"""翻译器门户服务（goal-d9，PRD §3.2 P3）。

翻译草稿是**个人席位资产**（created_by 归集，无项目维度）：创建人本人或
admin 可读。创建即投递 translator.translate 任务（outbox → worker），AI 只
出草稿（result_json 的 confirmed 一律 False，由 validate_guidance_output+
system prompt 双重钉住），人工确认/采纳流挂账。

T-A2 同源红线（架构评估 2026-11-07 D2）：翻译输入是表单自由文本——与
presurvey DOCX 同属「外部文字」，**原文不落库**（仓库/数据库只存代号）。
创建面先过企业名替换（闸①分层语义同源：词典机制性异常 fail-closed 422、
疑似名替换+复核清单、通用词零改动），替换命中落 guidance.redaction_review
事件（target_type=translator_translation），采纳时交接给项目指引分析（见
guidance/service.adopt_translator_draft），confirm 复核闸自动覆盖翻译链。
"""
from __future__ import annotations

from typing import Any, Mapping

from sqlalchemy import select

from fde_api.auth.models import User
from fde_api.extensions import db
from fde_api.guidance.enterprise_dict import DICT_FAILURE_CODE, RedactionConfigError
from fde_api.guidance.models import INTERVIEW_MODES, ProjectGuidanceAnalysis, REDACTION_EVENT_TYPE
from fde_api.guidance.redaction import (
    RedactionResult,
    SensitiveCredentialDetected,
    fingerprint_review_entries,
    redact_text_detailed,
)
from fde_api.jobs.outbox import enqueue_outbox, subject_org_of_user
from fde_api.translator.jobs import TRANSLATOR_JOB_TYPE
from fde_api.translator.models import TranslatorTranslation
from fde_api.workbench.models import OperationEvent

_PROFILE_TEXT_LIMIT = 120
_VISION_LIMIT = 10_000
_OBJECTIVE_LIMIT = 2_000
_LIST_LIMIT = 20

_DICT_FAILURE_MESSAGE = "企业名词典不可用，为守住「客户名不入库」红线已阻断本次翻译，请联系管理员修复词典配置。"


class TranslatorServiceError(Exception):
    def __init__(self, code: str, message: str, status: int):
        super().__init__(message)
        self.code, self.message, self.status = code, message, status


def _merge_redaction_entries(results: list[RedactionResult]) -> list[dict[str, Any]]:
    """逐字段 RedactionResult 合并成复核条目（同名 occurrences 累加、matched_dict
    求并），按名称排序——与 confirm 复核闸的聚合口径同构。"""
    merged: dict[str, dict[str, Any]] = {}
    for result in results:
        for suspect in result.suspects:
            slot = merged.setdefault(
                suspect.name, {"name": suspect.name, "occurrences": 0, "matched_dict": False}
            )
            slot["occurrences"] += suspect.occurrences
        for name in result.replaced:
            slot = merged.setdefault(name, {"name": name, "occurrences": 0, "matched_dict": True})
            slot["matched_dict"] = True
            slot["occurrences"] += 1
    return [merged[key] for key in sorted(merged)]


def _redact_translation_input(data: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """创建面企业名替换：原文不落库（T-A2 同源红线）。

    翻译器无项目维度，替换目标统一落「客户代号」占位（redact_text_detailed
    的 project_code 缺省别名）。分层失败语义（闸①拍板）与 presurvey 一致：
    - RedactionConfigError（词典机制性故障）→ 422 pseudonym_dict_unavailable，
      行不落库（fail-closed，与 _render_context 422 先例同构）；
    - SensitiveCredentialDetected → 422 sensitive_credential_detected；
    - 疑似名 → 替换 + 记入复核清单（放行=不留库口径）；
    - 通用词 → 零改动、不进清单。
    """
    results: list[RedactionResult] = []
    try:
        vision = redact_text_detailed(data["customer_vision"])
        objective = redact_text_detailed(data["phase_objective"])
        profile: dict[str, str] = {}
        for key, value in data["profile"].items():
            field = redact_text_detailed(value)
            profile[key] = field.text
            results.append(field)
    except RedactionConfigError as error:
        raise TranslatorServiceError(DICT_FAILURE_CODE, _DICT_FAILURE_MESSAGE, 422) from error
    except SensitiveCredentialDetected as error:
        raise TranslatorServiceError("sensitive_credential_detected", str(error), 422) from error
    results.extend([vision, objective])
    return (
        {"profile": profile, "customer_vision": vision.text, "phase_objective": objective.text},
        _merge_redaction_entries(results),
    )


def create_translation(*, actor: User, payload: Mapping[str, Any]) -> dict[str, Any]:
    session = db.session()
    try:
        with session.begin():
            data = _validate_payload(payload)
            redacted, entries = _redact_translation_input(data)
            row = TranslatorTranslation(
                created_by_user_id=actor.id,
                profile_json=redacted["profile"],
                customer_vision=redacted["customer_vision"],
                phase_objective=redacted["phase_objective"],
                status="pending",
            )
            session.add(row)
            session.flush()
            if entries:
                # 疑似/替换清单随事件留痕（append-only）；采纳流把条目交接给
                # 项目指引分析，confirm 复核闸按分析聚合后强制人工复核。
                # QR-133 指纹化：确证命中只存指纹、疑似只留计数（零真名）。
                fingerprinted, suspect_count = fingerprint_review_entries(entries)
                event_changes: dict[str, Any] = {"stage": "input", "entries": fingerprinted}
                if suspect_count:
                    event_changes["suspect_count"] = suspect_count
                session.add(
                    OperationEvent(
                        actor_user_id=actor.id,
                        project_id=None,
                        target_type="translator_translation",
                        target_id=row.id,
                        event_type=REDACTION_EVENT_TYPE,
                        changes=event_changes,
                    )
                )
            enqueue_outbox(
                session, TRANSLATOR_JOB_TYPE, row.id, {"translation_id": row.id},
                subject_org=subject_org_of_user(session, row.created_by_user_id),
            )
        # 提交后再序列化：created_at 是 server_default，flush 后行内尚未回填。
        return serialize_translation(row)
    finally:
        session.close()


def list_translations(*, actor: User) -> list[dict[str, Any]]:
    session = db.session()
    try:
        rows = session.scalars(
            select(TranslatorTranslation)
            .where(TranslatorTranslation.created_by_user_id == actor.id)
            .order_by(TranslatorTranslation.created_at.desc(), TranslatorTranslation.id.desc())
            .limit(_LIST_LIMIT)
        ).all()
        adopted = _adopted_index(session, [row.id for row in rows])
        return [serialize_translation(row, adopted_into=adopted.get(row.id, [])) for row in rows]
    finally:
        session.close()


def get_translation(*, actor: User, translation_id: str) -> dict[str, Any]:
    session = db.session()
    try:
        row = session.get(TranslatorTranslation, translation_id)
        if row is None or (row.created_by_user_id != actor.id and actor.role != "admin"):
            raise TranslatorServiceError("translation_not_found", "翻译记录不存在。", 404)
        adopted = _adopted_index(session, [row.id])
        return serialize_translation(row, adopted_into=adopted.get(row.id, []))
    finally:
        session.close()


def _adopted_index(session, translation_ids: list[str]) -> dict[str, list[dict[str, str]]]:
    """goal-d10 挂账 #1：门户侧采纳状态透出——按 translation_id 反查已采纳
    的项目指引版本（(project_id, translation_id) 唯一约束保证无重复）。"""
    if not translation_ids:
        return {}
    rows = session.execute(
        select(
            ProjectGuidanceAnalysis.translation_id,
            ProjectGuidanceAnalysis.project_id,
            ProjectGuidanceAnalysis.id,
        ).where(ProjectGuidanceAnalysis.translation_id.in_(translation_ids))
    ).all()
    index: dict[str, list[dict[str, str]]] = {}
    for translation_id, project_id, analysis_id in rows:
        index.setdefault(translation_id, []).append(
            {"project_id": project_id, "analysis_id": analysis_id}
        )
    return index


def _validate_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, Mapping) or set(payload) != {
        "industry", "scale", "region", "interview_mode", "customer_vision", "phase_objective"
    }:
        raise TranslatorServiceError("invalid_request", "翻译请求字段不完整或不合法。", 400)
    profile: dict[str, str] = {}
    for key in ("industry", "scale", "region"):
        value = payload[key]
        if not isinstance(value, str) or len(value.strip()) > _PROFILE_TEXT_LIMIT:
            raise TranslatorServiceError("invalid_request", f"{key} 字段过长或类型不合法。", 400)
        profile[key] = value.strip()
    mode = payload["interview_mode"]
    if not isinstance(mode, str) or mode not in INTERVIEW_MODES:
        raise TranslatorServiceError("invalid_request", "interview_mode 取值不合法。", 400)
    profile["interview_mode"] = mode
    vision = payload["customer_vision"]
    if not isinstance(vision, str) or not vision.strip() or len(vision.strip()) > _VISION_LIMIT:
        raise TranslatorServiceError("invalid_request", "客户诉求原话不能为空且长度受限。", 400)
    objective = payload["phase_objective"]
    if not isinstance(objective, str) or len(objective.strip()) > _OBJECTIVE_LIMIT:
        raise TranslatorServiceError("invalid_request", "阶段目标长度受限。", 400)
    return {
        "profile": profile,
        "customer_vision": vision.strip(),
        "phase_objective": objective.strip(),
    }


def serialize_translation(
    row: TranslatorTranslation, *, adopted_into: list[dict[str, str]] | None = None
) -> dict[str, Any]:
    return {
        "adopted_into": adopted_into or [],
        "id": row.id,
        "created_by_user_id": row.created_by_user_id,
        "profile": row.profile_json or {},
        "customer_vision": row.customer_vision,
        "phase_objective": row.phase_objective,
        "status": row.status,
        "result": row.result_json,
        "ai_model": row.ai_model,
        "ai_generated_at": row.ai_generated_at.isoformat() if row.ai_generated_at else None,
        "failure_code": row.failure_code or None,
        "failure_message": row.failure_message or None,
        "created_at": row.created_at.isoformat(),
        "updated_at": row.updated_at.isoformat(),
    }
