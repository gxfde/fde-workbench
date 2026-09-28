"""AI enrichment for PoV and SOW document versions.

The model receives only project-scoped structured data and answered research
fields. It returns a flat field map that is frozen into the document version;
manual draft overrides always win over generated values.
"""

from __future__ import annotations

import json
from typing import Any
from uuid import uuid4

from flask import current_app
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from fde_api.ai.deepseek import DeepSeekClient
from fde_api.config import Settings
from fde_api.documents.models import ProjectDocument
from fde_api.research.models import ProjectResearchForm, ProjectResearchFormRevision, ProjectResearchSubject


def generate_document_fields(
    session: Session,
    document: ProjectDocument,
    requested_fields: list[str] | None = None,
) -> dict[str, Any]:
    if document.document_type not in {"pov_plan", "sow"} or not (document.source_opportunity_id or document.opportunity_scope_json):
        return {}
    opportunity = session.scalar(
        select(ProjectResearchSubject)
        .options(selectinload(ProjectResearchSubject.opportunity_profile))
        .where(ProjectResearchSubject.id == document.source_opportunity_id)
    )
    if opportunity is None and not document.opportunity_scope_json:
        return {}
    forms = session.scalars(
        select(ProjectResearchForm)
        .options(
            selectinload(ProjectResearchForm.subject),
            selectinload(ProjectResearchForm.current_revision).selectinload(ProjectResearchFormRevision.answers),
        )
        .where(ProjectResearchForm.project_id == document.project_id)
        .order_by(ProjectResearchForm.created_at, ProjectResearchForm.id)
    ).all()
    research: list[dict[str, Any]] = []
    answer_count = 0
    for form in forms:
        revision = form.current_revision
        if revision is None:
            continue
        answers = []
        for answer in revision.answers:
            if answer.value_json in (None, "", [], {}):
                continue
            answers.append({"field_key": answer.field_key, "value": answer.value_json})
            answer_count += 1
            if answer_count >= 200:
                break
        if answers:
            research.append({"object": form.subject.name, "form": form.name, "answers": answers})
        if answer_count >= 200:
            break
    profile = opportunity.opportunity_profile if opportunity else None
    payload = {
        "document_type": document.document_type,
        "required_output_fields": requested_fields or [],
        "opportunity": {
            "name": opportunity.name if opportunity else "",
            "description": opportunity.description if opportunity else "",
            "target_audience": profile.target_audience if profile else "",
            "priority": profile.priority if profile else None,
            "business_value_score": profile.business_value_score if profile else None,
            "feasibility_score": profile.feasibility_score if profile else None,
            "data_readiness_score": profile.data_readiness_score if profile else None,
            "risk_level": profile.risk_level if profile else None,
            "next_action": profile.next_action if profile else "",
            "evidence": profile.evidence_json if profile else [],
        },
        "research": research,
    }
    if document.opportunity_scope_json:
        payload.pop("opportunity", None)
        payload.update(document.opportunity_scope_json)
    system = (
        "你是企业 AI 落地项目的 FDE 文档助手。只能依据输入事实生成内容，不得编造。"
        "输出严格 JSON：{\"fields\":{...}}。required_output_fields 中的每个字段都必须原样作为 fields 的键输出；"
        "此外 fields 至少包含 current_situation、business_goal、"
        "solution_scope、deliverables、success_metrics、acceptance_criteria、timeline、exclusions、"
        "assumptions、data_requirements、security_requirements、risk_controls。值使用中文字符串；"
        "信息不足时明确写‘待确认’，不要省略字段。PoV 强调验证假设、样本、指标与退出条件；"
        "SOW 强调范围、交付物、责任边界、验收条件和不包含项。"
        "多机会时以一次项目交付或共同验证目标为主体，整合而不是逐份拼接；逐项列明机会编号与交付物/验证项的对应关系，共享依赖只写一次，冲突及缺失信息标为待确认。不得把机会识别当作已实施成果。"
    )
    result = _client().complete_json(
        messages=[{"role": "system", "content": system}, {"role": "user", "content": json.dumps(payload, ensure_ascii=False)}],
        request_id=f"document-content-{uuid4()}",
        max_tokens=6144,
    )
    fields = result.get("fields")
    if not isinstance(fields, dict):
        return {}
    return {str(key): value for key, value in fields.items() if isinstance(value, (str, int, float, bool, list))}


def _client() -> DeepSeekClient:
    injected = current_app.extensions.get("fde_api_document_generation_deepseek")
    if injected is not None:
        return injected
    settings: Settings = current_app.config["SETTINGS"]
    return DeepSeekClient(
        base_url=settings.deepseek_base_url,
        api_key=settings.deepseek_api_key,
        model=settings.deepseek_document_generation_model,
        timeout_seconds=settings.deepseek_timeout_seconds,
    )
