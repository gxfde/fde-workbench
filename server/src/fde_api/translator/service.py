"""翻译器门户服务（goal-d9，PRD §3.2 P3）。

翻译草稿是**个人席位资产**（created_by 归集，无项目维度）：创建人本人或
admin 可读。创建即投递 translator.translate 任务（outbox → worker），AI 只
出草稿（result_json 的 confirmed 一律 False，由 validate_guidance_output+
system prompt 双重钉住），人工确认/采纳流挂账。
"""
from __future__ import annotations

from typing import Any, Mapping

from sqlalchemy import select

from fde_api.auth.models import User
from fde_api.extensions import db
from fde_api.guidance.models import INTERVIEW_MODES, ProjectGuidanceAnalysis
from fde_api.jobs.outbox import enqueue_outbox
from fde_api.translator.jobs import TRANSLATOR_JOB_TYPE
from fde_api.translator.models import TranslatorTranslation

_PROFILE_TEXT_LIMIT = 120
_VISION_LIMIT = 10_000
_OBJECTIVE_LIMIT = 2_000
_LIST_LIMIT = 20


class TranslatorServiceError(Exception):
    def __init__(self, code: str, message: str, status: int):
        super().__init__(message)
        self.code, self.message, self.status = code, message, status


def create_translation(*, actor: User, payload: Mapping[str, Any]) -> dict[str, Any]:
    session = db.session()
    try:
        with session.begin():
            data = _validate_payload(payload)
            row = TranslatorTranslation(
                created_by_user_id=actor.id,
                profile_json=data["profile"],
                customer_vision=data["customer_vision"],
                phase_objective=data["phase_objective"],
                status="pending",
            )
            session.add(row)
            session.flush()
            enqueue_outbox(session, TRANSLATOR_JOB_TYPE, row.id, {"translation_id": row.id})
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
