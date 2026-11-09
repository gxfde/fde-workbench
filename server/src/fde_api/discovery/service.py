"""discovery 服务：抽取生命周期 + 事实/需求审阅（V3.1 P0-1）。

权限：创建抽取（触发 AI 花费）与全部审阅写操作=can_manage；读面=can_view。
幂等：(project, source_type, source_id, extractor_version, prompt_version)
唯一——同源同版本重复创建返回既有行（created=False）；重跑仅 failed。
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select

from fde_api.extensions import db
from fde_api.projects.permissions import project_access
from fde_api.transcripts.models import InterviewMinutes, TranscriptDraft
from fde_api.workbench.models import OperationEvent, Project

from fde_api.discovery.models import (
    BusinessFact,
    DiscoveryExtraction,
    EXTRACTOR_VERSION,
    PROMPT_VERSION,
    Requirement,
    RequirementSource,
)

MAX_COMMENT_CHARS = 500
EXTRACTION_EVENT_TARGET = "discovery_extraction"
FACT_EVENT_TARGET = "business_fact"
REQUIREMENT_EVENT_TARGET = "requirement"


class DiscoveryServiceError(Exception):
    def __init__(self, code: str, message: str, status: int, detail: dict[str, Any] | None = None):
        super().__init__(message)
        self.code, self.message, self.status = code, message, status
        self.detail = detail or {}


def _error(code: str, message: str, status: int = 400, detail: dict[str, Any] | None = None) -> DiscoveryServiceError:
    return DiscoveryServiceError(code, message, status, detail)


def _session() -> Any:
    return db.session()


def _require_project(session, actor, project_id: str, *, manage: bool):
    project = session.get(Project, project_id)
    if project is None:
        raise _error("project_not_found", "项目不存在。", 404)
    access = project_access(actor, project)
    if manage and not access.can_manage:
        raise _error("forbidden", "无此项目的管理权限。", 403)
    if not access.can_view:
        raise _error("forbidden", "无此项目的访问权限。", 403)
    return project


# ---------------------------------------------------------------------------
# 抽取生命周期


def _load_source(session, project_id: str, source_type: str, source_id: str):
    """读源行并回填 (content, sha256)；草稿必须处于 draft 态（墓碑无正文）。"""
    if source_type == "interview_minutes":
        row = session.get(InterviewMinutes, source_id)
        if row is None or row.project_id != project_id:
            raise _error("source_not_found", "访谈纪要不存在或不属于该项目。", 404)
        return row.content, row.content_sha256
    if source_type == "transcript_draft":
        row = session.get(TranscriptDraft, source_id)
        if row is None or row.project_id != project_id:
            raise _error("source_not_found", "转写草稿不存在或不属于该项目。", 404)
        if row.status != "draft":
            raise _error("source_not_draft", "转写草稿已晋升/弃置/过期，不能作为抽取源。", 409)
        if row.content is None or row.content_sha256 is None:
            raise _error("source_not_draft", "转写草稿正文不可用。", 409)
        return row.content, row.content_sha256
    raise _error("invalid_source_type", "source_type 仅可为 interview_minutes 或 transcript_draft。", 400)


def create_extraction(actor, project_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    session = _session()
    try:
        _require_project(session, actor, project_id, manage=True)
        source_type = payload.get("source_type")
        source_id = payload.get("source_id")
        if not isinstance(source_type, str) or not isinstance(source_id, str) or not source_id:
            raise _error("invalid_request", "source_type 与 source_id 必填。", 400)
        _, source_sha = _load_source(session, project_id, source_type, source_id)
        # 幂等键含版本（与唯一约束同形）：版本升级（v1→v2）后同源再抽生成**新行**，
        # 旧版本行保留为历史事实。漏掉版本过滤会让 rerun 永远拿回陈旧代际的行。
        existing = session.scalar(
            select(DiscoveryExtraction).where(
                DiscoveryExtraction.project_id == project_id,
                DiscoveryExtraction.source_type == source_type,
                DiscoveryExtraction.source_id == source_id,
                DiscoveryExtraction.extractor_version == EXTRACTOR_VERSION,
                DiscoveryExtraction.prompt_version == PROMPT_VERSION,
            )
        )
        if existing is not None:
            return {**serialize_extraction(existing), "created": False}
        extraction = DiscoveryExtraction(
            project_id=project_id,
            created_by_user_id=actor.id,
            source_type=source_type,
            source_id=source_id,
            source_sha256=source_sha,
            status="queued",
        )
        session.add(extraction)
        session.flush()
        _event(
            session, actor.id, project_id, EXTRACTION_EVENT_TARGET, extraction.id,
            "discovery_extraction_created",
            {"source_type": source_type, "source_id": source_id},
        )
        from fde_api.jobs.outbox import enqueue_outbox

        enqueue_outbox(session, "project.discovery.extract", extraction.id, {})
        session.commit()
        return {**serialize_extraction(extraction), "created": True}
    finally:
        session.close()


def rerun_extraction(actor, extraction_id: str) -> dict[str, Any]:
    """重跑：仅 failed（review_required 行已带人工审阅痕迹，重跑会抹审阅）。"""
    session = _session()
    try:
        extraction = _owned_extraction(session, actor, extraction_id, manage=True)
        if extraction.status != "failed":
            raise _error(
                "extraction_not_failed",
                "只有失败的抽取可以重跑；已完成抽取的审阅痕迹不可被覆盖。",
                409,
            )
        # 版本升代：重跑由**当前代**的抽取器与提示词执行，行标签必须如实换代
        # （幂等键的语义＝「同代同果」）；同源已有当前版本行时拒绝（唯一约束
        # 会撞），指路新行，旧失败行保留为历史。
        if (extraction.extractor_version, extraction.prompt_version) != (EXTRACTOR_VERSION, PROMPT_VERSION):
            clash = session.scalar(
                select(DiscoveryExtraction.id).where(
                    DiscoveryExtraction.project_id == extraction.project_id,
                    DiscoveryExtraction.source_type == extraction.source_type,
                    DiscoveryExtraction.source_id == extraction.source_id,
                    DiscoveryExtraction.extractor_version == EXTRACTOR_VERSION,
                    DiscoveryExtraction.prompt_version == PROMPT_VERSION,
                    DiscoveryExtraction.id != extraction.id,
                )
            )
            if clash is not None:
                raise _error(
                    "extraction_version_conflict",
                    "同源已存在当前版本的抽取行（%s）；请在新行上操作，本行保留为历史。" % clash,
                    409,
                )
            extraction.extractor_version = EXTRACTOR_VERSION
            extraction.prompt_version = PROMPT_VERSION
        # 清除旧失败痕迹（若此前写入过部分行——按管线设计失败零写入，此处防御）
        # 子表先清：sources → requirements → facts（FK 顺序）
        session.query(RequirementSource).filter(
            RequirementSource.requirement_id.in_(
                select(Requirement.id).where(Requirement.extraction_id == extraction.id)
            )
        ).delete(synchronize_session=False)
        session.query(Requirement).filter(Requirement.extraction_id == extraction.id).delete(synchronize_session=False)
        session.query(BusinessFact).filter(BusinessFact.extraction_id == extraction.id).delete(synchronize_session=False)
        extraction.status = "queued"
        extraction.failure_code = None
        extraction.failure_message = None
        extraction.redaction_entries = None
        session.flush()
        _event(
            session, actor.id, extraction.project_id, EXTRACTION_EVENT_TARGET, extraction.id,
            "discovery_extraction_rerun", {},
        )
        from fde_api.jobs.outbox import enqueue_outbox

        enqueue_outbox(session, "project.discovery.extract", extraction.id, {})
        session.commit()
        return serialize_extraction(extraction)
    finally:
        session.close()


def get_extraction(actor, extraction_id: str) -> dict[str, Any]:
    session = _session()
    try:
        return serialize_extraction(_owned_extraction(session, actor, extraction_id, manage=False))
    finally:
        session.close()


def list_extractions(actor, project_id: str, limit: int = 50, offset: int = 0) -> dict[str, Any]:
    session = _session()
    try:
        _require_project(session, actor, project_id, manage=False)
        rows = session.scalars(
            select(DiscoveryExtraction)
            .where(DiscoveryExtraction.project_id == project_id)
            .order_by(DiscoveryExtraction.created_at.desc())
            .offset(offset)
            .limit(limit)
        ).all()
        return {"items": [serialize_extraction(row) for row in rows], "limit": limit, "offset": offset}
    finally:
        session.close()


# ---------------------------------------------------------------------------
# 事实/需求读面与审阅


def list_facts(
    actor, project_id: str, *, review_status: str | None = None,
    fact_type: str | None = None, limit: int = 100, offset: int = 0,
) -> dict[str, Any]:
    session = _session()
    try:
        _require_project(session, actor, project_id, manage=False)
        stmt = select(BusinessFact).where(BusinessFact.project_id == project_id)
        if review_status:
            stmt = stmt.where(BusinessFact.review_status == review_status)
        if fact_type:
            stmt = stmt.where(BusinessFact.fact_type == fact_type)
        rows = session.scalars(
            stmt.order_by(BusinessFact.created_at.desc(), BusinessFact.id).offset(offset).limit(limit)
        ).all()
        return {
            "items": [serialize_fact(row) for row in rows],
            "limit": limit, "offset": offset,
        }
    finally:
        session.close()


def review_fact(actor, fact_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    session = _session()
    try:
        fact = session.get(BusinessFact, fact_id)
        if fact is None:
            raise _error("fact_not_found", "事实不存在。", 404)
        _require_project(session, actor, fact.project_id, manage=True)
        target = payload.get("review_status")
        if target not in {"accepted", "rejected", "needs_clarification"}:
            raise _error("invalid_review_status", "review_status 仅可为 accepted/rejected/needs_clarification。", 400)
        comment = payload.get("comment")
        if comment is not None and (not isinstance(comment, str) or len(comment) > MAX_COMMENT_CHARS):
            raise _error("invalid_comment", "审阅备注必须是 ≤500 字的文本。", 400)
        if fact.review_status in {"accepted", "rejected"}:
            raise _error(
                "fact_review_final",
                "该事实已审阅定案（accepted/rejected 为终态）；needs_clarification 条目可继续流转。",
                409,
            )
        from_status = fact.review_status
        fact.review_status = target
        fact.reviewed_by_user_id = actor.id
        fact.reviewed_at = datetime.now(UTC)
        if comment is not None:
            fact.review_comment = comment
        session.flush()
        _event(
            session, actor.id, fact.project_id, FACT_EVENT_TARGET, fact.id,
            "business_fact_reviewed",
            {"from": from_status, "to": target, "comment": comment or ""},
        )
        session.commit()
        return serialize_fact(fact)
    finally:
        session.close()


def list_requirements(
    actor, project_id: str, *, status: str | None = None, limit: int = 100, offset: int = 0,
) -> dict[str, Any]:
    session = _session()
    try:
        _require_project(session, actor, project_id, manage=False)
        stmt = select(Requirement).where(Requirement.project_id == project_id)
        if status:
            stmt = stmt.where(Requirement.status == status)
        rows = session.scalars(
            stmt.order_by(Requirement.created_at.desc(), Requirement.id).offset(offset).limit(limit)
        ).all()
        return {
            "items": [serialize_requirement(session, row) for row in rows],
            "limit": limit, "offset": offset,
        }
    finally:
        session.close()


def review_requirement(actor, requirement_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    session = _session()
    try:
        requirement = session.get(Requirement, requirement_id)
        if requirement is None:
            raise _error("requirement_not_found", "需求不存在。", 404)
        _require_project(session, actor, requirement.project_id, manage=True)
        target = payload.get("status")
        if target not in {"accepted", "rejected", "needs_clarification"}:
            raise _error("invalid_status", "status 仅可为 accepted/rejected/needs_clarification。", 400)
        comment = payload.get("comment")
        if comment is not None and (not isinstance(comment, str) or len(comment) > MAX_COMMENT_CHARS):
            raise _error("invalid_comment", "审阅备注必须是 ≤500 字的文本。", 400)
        if requirement.status in {"accepted", "rejected"}:
            raise _error("requirement_review_final", "该需求已审阅定案（终态不可流转）。", 409)
        from_status = requirement.status
        requirement.status = target
        requirement.approved_by_user_id = actor.id
        requirement.approved_at = datetime.now(UTC)
        if comment is not None:
            requirement.review_comment = comment
        session.flush()
        _event(
            session, actor.id, requirement.project_id, REQUIREMENT_EVENT_TARGET, requirement.id,
            "requirement_reviewed",
            {"from": from_status, "to": target, "comment": comment or ""},
        )
        session.commit()
        return serialize_requirement(session, requirement)
    finally:
        session.close()


# ---------------------------------------------------------------------------
# 序列化


def serialize_extraction(row: DiscoveryExtraction) -> dict[str, Any]:
    return {
        "id": row.id,
        "project_id": row.project_id,
        "created_by_user_id": row.created_by_user_id,
        "source_type": row.source_type,
        "source_id": row.source_id,
        "source_sha256": row.source_sha256,
        "status": row.status,
        "extractor_version": row.extractor_version,
        "prompt_version": row.prompt_version,
        "ai_model": row.ai_model,
        "ai_generated_at": row.ai_generated_at.isoformat() if row.ai_generated_at else None,
        "completed_at": row.completed_at.isoformat() if row.completed_at else None,
        "failure_code": row.failure_code,
        "failure_message": row.failure_message,
        "redaction_entries": row.redaction_entries or [],
    }


def serialize_fact(row: BusinessFact) -> dict[str, Any]:
    return {
        "id": row.id,
        "project_id": row.project_id,
        "extraction_id": row.extraction_id,
        "fact_type": row.fact_type,
        "classification": row.classification,
        "subject": row.subject,
        "predicate": row.predicate,
        "object_value": row.object_value,
        "confidence": float(row.confidence) if row.confidence is not None else None,
        "source_ref": row.source_ref,
        "source_locator": row.source_locator,
        "review_status": row.review_status,
        "reviewed_by_user_id": row.reviewed_by_user_id,
        "reviewed_at": row.reviewed_at.isoformat() if row.reviewed_at else None,
        "review_comment": row.review_comment,
    }


def serialize_requirement(session, row: Requirement) -> dict[str, Any]:
    sources = session.scalars(
        select(RequirementSource).where(RequirementSource.requirement_id == row.id)
    ).all()
    return {
        "id": row.id,
        "project_id": row.project_id,
        "extraction_id": row.extraction_id,
        "requirement_key": row.requirement_key,
        "title": row.title,
        "description": row.description,
        "requirement_type": row.requirement_type,
        "priority": row.priority,
        "acceptance_criteria": row.acceptance_criteria or [],
        "status": row.status,
        "approved_by_user_id": row.approved_by_user_id,
        "approved_at": row.approved_at.isoformat() if row.approved_at else None,
        "review_comment": row.review_comment,
        "source_fact_ids": [s.fact_id for s in sources if s.fact_id],
        "source_count": len(sources),
    }


def extraction_review_summary(session, extraction_id: str) -> dict[str, int]:
    """全量审阅完成度（派生态，不物化——B#13-C 先例）。"""
    rows = session.execute(
        select(BusinessFact.review_status, func.count())
        .where(BusinessFact.extraction_id == extraction_id)
        .group_by(BusinessFact.review_status)
    ).all()
    counts = {status: count for status, count in rows}
    return {
        "pending": counts.get("pending", 0),
        "accepted": counts.get("accepted", 0),
        "rejected": counts.get("rejected", 0),
        "needs_clarification": counts.get("needs_clarification", 0),
    }


# ---------------------------------------------------------------------------
# 内部


def _owned_extraction(session, actor, extraction_id: str, *, manage: bool) -> DiscoveryExtraction:
    row = session.get(DiscoveryExtraction, extraction_id)
    if row is None:
        raise _error("extraction_not_found", "抽取不存在。", 404)
    _require_project(session, actor, row.project_id, manage=manage)
    return row


def _event(session, actor_id: str, project_id: str, target_type: str, target_id: str, event_type: str, changes: dict[str, Any]) -> None:
    """直落 OperationEvent（guidance/jobs.py 先例：治理目标类型不入 record_event 注册表）。"""
    session.add(
        OperationEvent(
            actor_user_id=actor_id,
            project_id=project_id,
            target_type=target_type,
            target_id=target_id,
            event_type=event_type,
            changes=changes,
        )
    )
