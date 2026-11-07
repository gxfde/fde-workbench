from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime
from typing import Any, Mapping

from flask import current_app
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload

from fde_api.agents.quota import record_action
from fde_api.auth.models import User
from fde_api.extensions import db
from fde_api.files.models import ProjectFileVersion
from fde_api.guidance.ai_schema import LIST_FIELDS
from fde_api.guidance.models import (
    INTERVIEW_MODES,
    PresurveyIntake,
    ProjectGuidanceAnalysis,
    ProjectPresurveySource,
    REDACTION_EVENT_TYPE,
)
from fde_api.jobs.outbox import enqueue_outbox
from fde_api.projects.events import record_event
from fde_api.projects.permissions import project_access
from fde_api.translator.models import TranslatorTranslation
from fde_api.workbench.models import Gate, OperationEvent, Project


class GuidanceServiceError(Exception):
    def __init__(self, code: str, message: str, status: int):
        super().__init__(message)
        self.code, self.message, self.status = code, message, status


def set_presurvey_source(*, actor: User, project_id: str, file_version_id: str) -> dict[str, Any]:
    session = db.session()
    try:
        with session.begin():
            project = _project(session, actor, project_id, manage=True)
            _require_s3_gate(session, project.id)
            version = session.scalar(select(ProjectFileVersion).options(selectinload(ProjectFileVersion.project_file)).where(ProjectFileVersion.id == file_version_id))
            _valid_source(version, project.id)
            source = session.get(ProjectPresurveySource, project.id)
            if source is None:
                source = ProjectPresurveySource(project_id=project.id, project_file_id=version.file_id, current_file_version_id=version.id)
                session.add(source)
            else:
                source.project_file_id = version.file_id
                source.current_file_version_id = version.id
                source.version += 1
            session.flush()
            return _source_dict(source)
    finally:
        session.close()


def create_analysis(*, actor: User, project_id: str, source_file_version_id: str | None = None) -> dict[str, Any]:
    session = db.session()
    try:
        with session.begin():
            project = _project(session, actor, project_id, manage=True)
            _require_s3_gate(session, project.id)
            source = session.get(ProjectPresurveySource, project.id)
            version_id = source_file_version_id or (source.current_file_version_id if source else None)
            if not version_id:
                raise GuidanceServiceError("presurvey_source_required", "请先在文件库选择一份预调研 DOCX。", 400)
            version = session.scalar(select(ProjectFileVersion).options(selectinload(ProjectFileVersion.project_file)).where(ProjectFileVersion.id == version_id))
            _valid_source(version, project.id)
            number = int(session.scalar(select(func.coalesce(func.max(ProjectGuidanceAnalysis.version_number), 0)).where(ProjectGuidanceAnalysis.project_id == project.id)) or 0) + 1
            analysis = ProjectGuidanceAnalysis(
                project_id=project.id, version_number=number, source_file_id=version.file_id,
                source_file_version_id=version.id, source_filename=version.original_filename,
                source_sha256=version.sha256, status="draft", analysis_state="queued",
                created_by_user_id=actor.id,
            )
            session.add(analysis)
            session.flush()
            enqueue_outbox(session, "project.presurvey.analyze", analysis.id, {"project_id": project.id})
            return serialize_analysis(analysis, source)
    finally:
        session.close()


def list_analyses(*, actor: User, project_id: str) -> list[dict[str, Any]]:
    session = db.session()
    try:
        _project(session, actor, project_id)
        source = session.get(ProjectPresurveySource, project_id)
        rows = session.scalars(select(ProjectGuidanceAnalysis).where(ProjectGuidanceAnalysis.project_id == project_id).order_by(ProjectGuidanceAnalysis.version_number.desc())).all()
        return [serialize_analysis(row, source) for row in rows]
    finally:
        session.close()


def get_analysis(*, actor: User, project_id: str, analysis_id: str) -> dict[str, Any]:
    session = db.session()
    try:
        _project(session, actor, project_id)
        row = session.get(ProjectGuidanceAnalysis, analysis_id)
        if row is None or row.project_id != project_id:
            raise GuidanceServiceError("guidance_not_found", "项目指引版本不存在。", 404)
        data = serialize_analysis(row, session.get(ProjectPresurveySource, project_id))
        # T-A2 复核读面：复核清单是 #160 落的 operation_events 派生投影——
        # 方案审核人复核的可见入口（桌面呈现随 T-A4/B#9 面接线）。
        data["redaction_review"] = _redaction_review_entries(session, row.id)
        return data
    finally:
        session.close()


def _merge_review_entries(events: Any) -> list[dict[str, Any]]:
    """复核条目聚合（单一口径）：同名跨事件 occurrences 累加、matched_dict 求并，
    按名称排序输出——写入条目形状（name/occurrences/matched_dict）不在此二次
    推导文本。分析面（_redaction_review_entries）与翻译采纳交接（D2）共用。"""
    merged: dict[str, dict[str, Any]] = {}
    for event in events:
        for item in (event.changes or {}).get("entries", []):
            name = str(item.get("name", ""))
            if not name:
                continue
            slot = merged.setdefault(
                name, {"name": name, "occurrences": 0, "matched_dict": bool(item.get("matched_dict"))}
            )
            slot["occurrences"] += int(item.get("occurrences", 1) or 0)
            slot["matched_dict"] = slot["matched_dict"] or bool(item.get("matched_dict"))
    return [merged[key] for key in sorted(merged)]


def _redaction_review_entries(session: Any, analysis_id: str) -> list[dict[str, Any]]:
    """按分析聚合复核清单（消费 #160 落的 guidance.redaction_review 事件）。"""
    events = session.scalars(
        select(OperationEvent).where(
            OperationEvent.target_type == "project_guidance_analysis",
            OperationEvent.target_id == analysis_id,
            OperationEvent.event_type == REDACTION_EVENT_TYPE,
        )
    ).all()
    return _merge_review_entries(events)


def _translation_redaction_entries(session: Any, translation_id: str) -> list[dict[str, Any]]:
    """翻译链复核条目：translator 创建/落库两阶段落在 translator_translation
    目标上的 guidance.redaction_review 事件（架构评估 2026-11-07 D2 交接源）。"""
    events = session.scalars(
        select(OperationEvent).where(
            OperationEvent.target_type == "translator_translation",
            OperationEvent.target_id == translation_id,
            OperationEvent.event_type == REDACTION_EVENT_TYPE,
        )
    ).all()
    return _merge_review_entries(events)


def update_analysis(*, actor: User, project_id: str, analysis_id: str, expected_version: int, changes: Mapping[str, Any]) -> dict[str, Any]:
    session = db.session()
    try:
        with session.begin():
            _project(session, actor, project_id, manage=True)
            row = session.get(ProjectGuidanceAnalysis, analysis_id, with_for_update=True)
            if row is None or row.project_id != project_id:
                raise GuidanceServiceError("guidance_not_found", "项目指引版本不存在。", 404)
            if row.status != "draft" or row.analysis_state != "ready":
                raise GuidanceServiceError("guidance_not_editable", "只有分析完成的草稿可以修改。", 409)
            if row.version != expected_version:
                raise GuidanceServiceError("stale_version", "项目指引已被他人更新，请刷新后重试。", 409)
            for field in ("customer_vision", "current_phase_objective", "executive_summary"):
                if field in changes:
                    value = changes[field]
                    if not isinstance(value, str) or not value.strip():
                        raise GuidanceServiceError("invalid_guidance", f"{field} 不能为空。", 400)
                    setattr(row, field, value.strip())
            for field in LIST_FIELDS:
                if field in changes:
                    value = changes[field]
                    if not isinstance(value, list):
                        raise GuidanceServiceError("invalid_guidance", f"{field} 格式不正确。", 400)
                    setattr(row, f"{field}_json", value)
            row.version += 1
            session.flush()
            return serialize_analysis(row, session.get(ProjectPresurveySource, project_id))
    finally:
        session.close()


def create_manual_revision(*, actor: User, project_id: str, analysis_id: str, expected_version: int) -> dict[str, Any]:
    """Create an editable revision without overwriting a confirmed guidance version."""
    session = db.session()
    try:
        with session.begin():
            project = _project(session, actor, project_id, manage=True)
            source_row = session.get(ProjectGuidanceAnalysis, analysis_id, with_for_update=True)
            if source_row is None or source_row.project_id != project.id:
                raise GuidanceServiceError("guidance_not_found", "项目指引版本不存在。", 404)
            if source_row.analysis_state != "ready":
                raise GuidanceServiceError("guidance_not_ready", "项目指引尚未分析完成，暂时不能编辑。", 409)
            if source_row.version != expected_version:
                raise GuidanceServiceError("stale_version", "项目指引已被更新，请刷新后重试。", 409)
            if source_row.status == "draft":
                return serialize_analysis(source_row, session.get(ProjectPresurveySource, project.id))

            number = int(session.scalar(
                select(func.coalesce(func.max(ProjectGuidanceAnalysis.version_number), 0))
                .where(ProjectGuidanceAnalysis.project_id == project.id)
            ) or 0) + 1
            revision = ProjectGuidanceAnalysis(
                project_id=project.id,
                version_number=number,
                source_file_id=source_row.source_file_id,
                source_file_version_id=source_row.source_file_version_id,
                source_filename=source_row.source_filename,
                source_sha256=source_row.source_sha256,
                status="draft",
                analysis_state="ready",
                customer_vision=source_row.customer_vision,
                current_phase_objective=source_row.current_phase_objective,
                executive_summary=source_row.executive_summary,
                evidence_json=deepcopy(source_row.evidence_json),
                ai_model=source_row.ai_model,
                ai_generated_at=source_row.ai_generated_at,
                created_by_user_id=actor.id,
            )
            for field in LIST_FIELDS:
                setattr(revision, f"{field}_json", deepcopy(getattr(source_row, f"{field}_json")))
            session.add(revision)
            session.flush()
            return serialize_analysis(revision, session.get(ProjectPresurveySource, project.id))
    finally:
        session.close()


def confirm_analysis(
    *, actor: User, project_id: str, analysis_id: str, expected_version: int,
    redaction_reviewed: bool = False,
) -> dict[str, Any]:
    session = db.session()
    try:
        with session.begin():
            project = _project(session, actor, project_id, manage=True)
            row = session.get(ProjectGuidanceAnalysis, analysis_id, with_for_update=True)
            if row is None or row.project_id != project_id:
                raise GuidanceServiceError("guidance_not_found", "项目指引版本不存在。", 404)
            if row.analysis_state != "ready" or row.status != "draft":
                raise GuidanceServiceError("guidance_not_confirmable", "只有分析完成的草稿可以确认。", 409)
            if row.version != expected_version:
                raise GuidanceServiceError("stale_version", "项目指引已被更新，请刷新后重试。", 409)
            # T-A2 复核闸（拍板 6①「方案审核人 confirm 前必须复核」的机械强制，
            # 补齐 #160 缺口）：复核清单从写入方同一事件源聚合取得；清单非空且
            # 请求未显式 redaction_reviewed=true（路由只认字面 true，fail 向
            # 安全侧）→ 409 拦下。复核动作随确认事件留痕，不新增状态面。
            review = _redaction_review_entries(session, row.id)
            if review and not redaction_reviewed:
                raise GuidanceServiceError(
                    "redaction_review_required",
                    f"存在 {len(review)} 个企业名替换待复核：请查看复核清单确认替换恰当，或修改正文后重试。",
                    409,
                )
            for old in session.scalars(select(ProjectGuidanceAnalysis).where(ProjectGuidanceAnalysis.project_id == project_id, ProjectGuidanceAnalysis.status == "confirmed")).all():
                old.status = "superseded"
                old.version += 1
            row.status = "confirmed"
            row.reviewed_by_user_id = actor.id
            row.reviewed_at = datetime.now(UTC)
            row.version += 1
            source = session.get(ProjectPresurveySource, project_id)
            if row.source_kind != "translator_draft":
                # goal-d10 决议③：只有预调研 DOCX 来源才回写源指针——翻译器
                # 草稿没有源文件，若把 ProjectPresurveySource 指到空引用会
                # 击穿 NOT NULL 且污染预调研源（旧源也不得被假源 deprecate）。
                # 建模不变量（source_file 双列 nullable 后仍成立）：非 translator
                # 来源必有源文件；显式守卫同时完成 mypy 类型收窄。
                if row.source_file_id is None or row.source_file_version_id is None:
                    raise GuidanceServiceError(
                        "guidance_source_missing",
                        "预调研来源的项目指引缺少源文件引用，无法确认。",
                        409,
                    )
                old_version_id = source.current_file_version_id if source else None
                if source is None:
                    source = ProjectPresurveySource(
                        project_id=project_id, project_file_id=row.source_file_id,
                        current_file_version_id=row.source_file_version_id,
                    )
                    session.add(source)
                else:
                    source.project_file_id = row.source_file_id
                    source.current_file_version_id = row.source_file_version_id
                    source.version += 1
                if old_version_id and old_version_id != row.source_file_version_id:
                    old_version = session.get(ProjectFileVersion, old_version_id)
                    if old_version is not None and old_version.status == "available":
                        old_version.status = "deprecated"
                        old_version.deprecated_by_user_id = actor.id
                        old_version.deprecated_at = datetime.now(UTC)
                        old_version.deprecation_reason = "预调研表新版本已确认"
            # goal-d2 P0 指标①埋点：售前「独立完成录入+确认」的确认侧事件
            # （录入侧为 presurvey_intake_saved）。纯增量审计，不影响返回值。
            # T-A2：复核动作随事件留痕（redaction_reviewed / 命中数）——不新增状态面。
            record_event(session, actor, "guidance_analysis_confirmed", project, {
                "analysis_id": row.id, "version_number": row.version_number,
                "source_file_version_id": row.source_file_version_id,
                "source_kind": row.source_kind,
                "redaction_reviewed": redaction_reviewed,
                "redaction_review_hits": len(review),
            })
            session.flush()
            data = serialize_analysis(row, source)
            data["redaction_review"] = review
            return data
    finally:
        session.close()


def adopt_translator_draft(*, actor: User, project_id: str, translation_id: str) -> dict[str, Any]:
    """翻译草稿「采纳流」（goal-d10，PRD §3.2 P3 收口）：ready 草稿升格为
    项目指引新版本（version_number 递增，status=draft——确认仍走人工）。

    决议①：草稿是个人席位资产，可采纳到多个项目；同项目由
    (project_id, translation_id) 唯一约束防重复（查询友好报错 + IntegrityError
    兜底并发双击）。决议②：O-3 额度随采纳落账（action_type='translation'，
    seat=采纳发起人；翻译时无项目维度不计，采纳时刻项目上下文齐备随路落）。
    决议③：产出的版本 source_kind='translator_draft'，确认时预调研源指针
    不被回写（见 confirm_analysis）。
    """
    session = db.session()
    try:
        with session.begin():
            # 闸序与读侧 GET /translations/{id} 一致：先翻译记录闸（owner/admin，
            # 404 不泄露草稿存在性），再项目闸。
            translation = session.get(TranslatorTranslation, translation_id)
            if translation is None or (
                translation.created_by_user_id != actor.id and actor.role != "admin"
            ):
                raise GuidanceServiceError("translation_not_found", "翻译记录不存在。", 404)
            project = _project(session, actor, project_id, manage=True)
            if translation.status != "ready" or not isinstance(translation.result_json, dict):
                raise GuidanceServiceError(
                    "translation_not_ready", "只有翻译完成的草稿可以采纳。", 409
                )
            existing = session.scalar(
                select(ProjectGuidanceAnalysis.id).where(
                    ProjectGuidanceAnalysis.project_id == project.id,
                    ProjectGuidanceAnalysis.translation_id == translation.id,
                )
            )
            if existing is not None:
                raise GuidanceServiceError(
                    "already_adopted", "该草稿已采纳到本项目，请直接编辑或确认。", 409
                )
            draft = translation.result_json
            number = int(session.scalar(
                select(func.coalesce(func.max(ProjectGuidanceAnalysis.version_number), 0))
                .where(ProjectGuidanceAnalysis.project_id == project.id)
            ) or 0) + 1
            row = ProjectGuidanceAnalysis(
                project_id=project.id,
                version_number=number,
                source_kind="translator_draft",
                translation_id=translation.id,
                source_file_id=None,
                source_file_version_id=None,
                source_filename=f"translator:{translation.id}",
                source_sha256="",
                status="draft",
                analysis_state="ready",
                customer_vision=str(draft.get("customer_vision") or ""),
                current_phase_objective=str(draft.get("current_phase_objective") or ""),
                executive_summary=str(draft.get("executive_summary") or ""),
                evidence_json=deepcopy(draft.get("evidence") or {}),
                ai_model=translation.ai_model or "",
                ai_generated_at=translation.ai_generated_at,
                created_by_user_id=actor.id,
            )
            for field in LIST_FIELDS:
                setattr(row, f"{field}_json", deepcopy(draft.get(field) or []))
            session.add(row)
            session.flush()
            record_action(
                session,
                project_id=project.id,
                user_id=actor.id,
                action_type="translation",
                ref_id=translation.id,
                quota_monthly=int(getattr(current_app.config["SETTINGS"], "seat_action_quota_monthly", 100) or 0),
            )
            record_event(session, actor, "translator_draft_adopted", project, {
                "translation_id": translation.id, "analysis_id": row.id,
                "version_number": row.version_number,
            })
            # T-A2 复核闸交接（架构评估 2026-11-07 D2）：翻译创建/落库两阶段
            # 落在 translator_translation 上的复核条目，采纳时搬到本分析——
            # confirm 闸按分析聚合，无需知道翻译链的存在即自动覆盖。
            carried = _translation_redaction_entries(session, translation.id)
            if carried:
                session.add(
                    OperationEvent(
                        actor_user_id=actor.id,
                        project_id=project.id,
                        target_type="project_guidance_analysis",
                        target_id=row.id,
                        event_type=REDACTION_EVENT_TYPE,
                        changes={"stage": "adopted", "entries": carried},
                    )
                )
                session.flush()
            data = serialize_analysis(row, session.get(ProjectPresurveySource, project.id))
            data["redaction_review"] = _redaction_review_entries(session, row.id)
            return data
    except IntegrityError:
        # 并发双击走到唯一约束：与预检查同语义（409，不泄露约束名）。
        raise GuidanceServiceError(
            "already_adopted", "该草稿已采纳到本项目，请直接编辑或确认。", 409
        ) from None
    finally:
        session.close()


def current_guidance(*, actor: User, project_id: str) -> dict[str, Any] | None:
    session = db.session()
    try:
        _project(session, actor, project_id)
        source = session.get(ProjectPresurveySource, project_id)
        row = session.scalar(select(ProjectGuidanceAnalysis).where(ProjectGuidanceAnalysis.project_id == project_id, ProjectGuidanceAnalysis.status == "confirmed").order_by(ProjectGuidanceAnalysis.version_number.desc()).limit(1))
        return serialize_analysis(row, source) if row else None
    finally:
        session.close()


def serialize_analysis(row: ProjectGuidanceAnalysis, source: ProjectPresurveySource | None = None) -> dict[str, Any]:
    data = {
        "id": row.id, "project_id": row.project_id, "version_number": row.version_number,
        "source_file_id": row.source_file_id, "source_file_version_id": row.source_file_version_id,
        "source_kind": row.source_kind, "translation_id": row.translation_id,
        "source_filename": row.source_filename, "status": row.status, "analysis_state": row.analysis_state,
        "customer_vision": row.customer_vision, "current_phase_objective": row.current_phase_objective,
        "executive_summary": row.executive_summary, "evidence": row.evidence_json,
        "ai_model": row.ai_model, "failure_code": row.failure_code, "failure_message": row.failure_message,
        "reviewed_by_user_id": row.reviewed_by_user_id, "reviewed_at": row.reviewed_at.isoformat() if row.reviewed_at else None,
        "version": row.version,
    }
    for field in LIST_FIELDS:
        data[field] = getattr(row, f"{field}_json")
    if row.source_kind == "translator_draft":
        # 翻译器来源没有「源文件」概念，无从过期（决议③）。
        data["source_is_stale"] = False
    else:
        data["source_is_stale"] = source is None or source.current_file_version_id != row.source_file_version_id
    return data


def _source_dict(source: ProjectPresurveySource) -> dict[str, Any]:
    return {"project_id": source.project_id, "project_file_id": source.project_file_id, "current_file_version_id": source.current_file_version_id, "version": source.version}


def get_presurvey_intake(*, actor: User, project_id: str) -> dict[str, Any]:
    session = db.session()
    try:
        _project(session, actor, project_id)
        return _intake_dict(session.get(PresurveyIntake, project_id))
    finally:
        session.close()


def save_presurvey_intake(*, actor: User, project_id: str, changes: Mapping[str, Any]) -> dict[str, Any]:
    session = db.session()
    try:
        with session.begin():
            project = _project(session, actor, project_id, manage=True)
            fields = _validated_intake_fields(changes)
            row = session.get(PresurveyIntake, project.id)
            if row is None:
                row = PresurveyIntake(project_id=project.id, updated_by_user_id=actor.id, **fields)
                session.add(row)
            else:
                for key, value in fields.items():
                    setattr(row, key, value)
                row.updated_by_user_id = actor.id
            session.flush()
            record_event(session, actor, "presurvey_intake_saved", project, {"fields": sorted(fields)})
            return _intake_dict(row)
    finally:
        session.close()


def _require_s3_gate(session, project_id: str) -> None:
    """G3 诊断开工门前置闸（PRD F1 / 决议 D16）：DOCX 分析链路仅限 S3 之后。

    G3 的证据清单即 SOW-A 签署 + A 款预付到账 + 数据授权书四项勾选
    （seeds/gates.json，SOP 原文），status=passed 表示三件套已人工核验；
    G3 的 decision 语义只有 pass/fail，无 conditional_pass。轻量录入卡
    （presurvey_intakes）不受此闸——S1–S2 即可填（PRD D16）。
    """
    gate = session.scalar(select(Gate).where(Gate.project_id == project_id, Gate.gate_key == "G3"))
    if gate is None or gate.status != "passed":
        raise GuidanceServiceError(
            "presurvey_s3_gate_open",
            "需先通过 G3 诊断开工门（SOW-A 签署、A 款到账、数据授权书四项勾选），才能上传预调研文件或发起 AI 分析。",
            409,
        )


_INTAKE_TEXT_LIMITS: dict[str, int] = {
    "industry": 80, "scale": 80, "region": 80,
    "customer_vision": 2000, "phase_objective": 2000, "notes": 2000,
}


def _validated_intake_fields(changes: Mapping[str, Any]) -> dict[str, Any]:
    text_limits = _INTAKE_TEXT_LIMITS
    allowed = set(text_limits) | {"interview_mode", "interviewee_roles"}
    unknown = set(changes) - allowed
    if unknown:
        raise GuidanceServiceError("unknown_field", f"不支持的录入卡字段：{sorted(unknown)}。", 400)
    fields: dict[str, Any] = {}
    for name, limit in text_limits.items():
        if name not in changes:
            continue
        value = changes[name]
        if not isinstance(value, str) or len(value.strip()) > limit:
            raise GuidanceServiceError("invalid_request", f"{name} 必须是不超过 {limit} 字的文本。", 400)
        fields[name] = value.strip()
    if "interview_mode" in changes:
        mode = changes["interview_mode"]
        if mode not in INTERVIEW_MODES:
            raise GuidanceServiceError("invalid_request", "interview_mode 仅支持 onsite/remote/hybrid。", 400)
        fields["interview_mode"] = mode
    if "interviewee_roles" in changes:
        roles = changes["interviewee_roles"]
        if not isinstance(roles, list) or len(roles) > 20 or any(
            not isinstance(role, str) or not role.strip() or len(role.strip()) > 80 for role in roles
        ):
            raise GuidanceServiceError("invalid_request", "interviewee_roles 必须是不超过 20 条、每条 80 字以内的文本数组。", 400)
        fields["interviewee_roles"] = [role.strip() for role in roles]
    if not fields:
        raise GuidanceServiceError("invalid_request", "没有可保存的录入卡字段。", 400)
    return fields


def _intake_dict(row: PresurveyIntake | None) -> dict[str, Any]:
    if row is None:
        return {
            "industry": "", "scale": "", "region": "", "interview_mode": "onsite",
            "interviewee_roles": [], "customer_vision": "", "phase_objective": "", "notes": "",
            "updated_by_user_id": None, "updated_at": None,
        }
    return {
        "industry": row.industry, "scale": row.scale, "region": row.region,
        "interview_mode": row.interview_mode, "interviewee_roles": row.interviewee_roles,
        "customer_vision": row.customer_vision, "phase_objective": row.phase_objective,
        "notes": row.notes, "updated_by_user_id": row.updated_by_user_id,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def _project(session, actor: User, project_id: str, *, manage: bool = False) -> Project:
    project = session.scalar(select(Project).options(selectinload(Project.members)).where(Project.id == project_id))
    access = project_access(actor, project) if project else None
    if project is None or access is None or not access.can_view:
        raise GuidanceServiceError("project_not_found", "项目不存在或无权访问。", 404)
    if manage and not access.can_manage:
        raise GuidanceServiceError("forbidden", "只有项目负责人或管理员可以执行此操作。", 403)
    return project


def _valid_source(version: ProjectFileVersion | None, project_id: str) -> None:
    if version is None or version.project_file.project_id != project_id:
        raise GuidanceServiceError("presurvey_file_not_found", "预调研文件版本不存在。", 404)
    if version.source == "preview" or version.extension.lower() != ".docx" or version.status != "available" or version.scan_status not in {"clean", "not_required"}:
        raise GuidanceServiceError("presurvey_file_unavailable", "请选择已完成安全检查的 DOCX 文件。", 400)
