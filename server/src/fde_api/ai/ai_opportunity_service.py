from __future__ import annotations

import logging
from typing import Any, Callable
from uuid import uuid4

from flask import current_app
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from fde_api.ai.ai_opportunity_prompt import build_ai_opportunity_messages
from fde_api.ai.deepseek import DeepSeekClient, DeepSeekError
from fde_api.auth.models import User
from fde_api.config import Settings
from fde_api.extensions import db
from fde_api.projects.permissions import project_access
from fde_api.research.models import ProjectResearchForm, ProjectResearchFormRevision, ProjectResearchPersonalMemo, ProjectResearchSubject
from fde_api.workbench.models import Project


logger = logging.getLogger(__name__)

OPPORTUNITY_RESEARCH_ANSWER_KEYS = (
    "current_state",
    "pain_points",
    "business_value",
    "target_scenario",
    "owner_role",
    "technical_prereqs",
)


class AIOpportunityDiscoveryError(Exception):
    def __init__(self, code: str, message: str, status: int):
        super().__init__(message)
        self.code, self.message, self.status = code, message, status


def discover_ai_opportunities(*, actor: User, payload: object, on_event: Callable[[dict[str, str]], None] | None = None) -> dict[str, Any]:
    project_id, subject_id, guidance = _normalize_request(payload)
    references = payload.get("references", ["personal_memos", "shared_memos", "research_forms", "guidance"])
    expand = payload.get("expand", True)
    if not isinstance(references, list) or not references or any(not isinstance(item, str) or item not in {"personal_memos", "shared_memos", "research_forms", "guidance"} for item in references) or type(expand) is not bool:
        raise AIOpportunityDiscoveryError("invalid_request", "请选择有效的参考内容和拓展开关。", 400)
    if "guidance" not in references:
        guidance = ""
    session = db.session()
    try:
        project = session.scalar(select(Project).options(selectinload(Project.members)).where(Project.id == project_id))
        access = project_access(actor, project) if project else None
        if project is None or access is None or not access.can_view:
            raise AIOpportunityDiscoveryError("project_not_found", "项目不存在或无权访问。", 404)
        if not (access.can_manage or access.can_update_assigned_tasks):
            raise AIOpportunityDiscoveryError("forbidden", "你没有权限发现 AI 机会。", 403)
        subjects = session.scalars(
            select(ProjectResearchSubject).where(
                ProjectResearchSubject.project_id == project.id,
                ProjectResearchSubject.status == "active",
            )
        ).all()
        selected = next((item for item in subjects if item.id == subject_id), None)
        if selected is None or selected.subject_type == "opportunity":
            raise AIOpportunityDiscoveryError("research_subject_not_found", "当前调研对象不存在或不支持机会分析。", 404)
        scope_ids = _descendant_ids(subjects, selected.id) | {selected.id}
        forms = session.scalars(
            select(ProjectResearchForm)
            .options(
                selectinload(ProjectResearchForm.subject),
                selectinload(ProjectResearchForm.current_revision).selectinload(ProjectResearchFormRevision.answers),
            )
            .where(ProjectResearchForm.project_id == project.id, ProjectResearchForm.subject_id.in_(scope_ids))
        ).all()
        evidence_forms = [_form_context(form) for form in forms if form.current_revision and form.current_revision.answers] if "research_forms" in references else []
        evidence_memos = [
            _memo_context(subject)
            for subject in subjects
            if "shared_memos" in references and subject.id in scope_ids and (subject.memo or "").strip()
        ]
        subject_by_id = {item.id: item for item in subjects}
        personal_memos = session.scalars(
            select(ProjectResearchPersonalMemo)
            .options(selectinload(ProjectResearchPersonalMemo.author))
            .where(
                ProjectResearchPersonalMemo.project_id == project.id,
                ProjectResearchPersonalMemo.subject_id.in_(scope_ids),
            )
        ).all()
        evidence_memos.extend(
            _personal_memo_context(item, subject_by_id[item.subject_id])
            for item in personal_memos
            if "personal_memos" in references and item.subject_id in subject_by_id and (item.memo or "").strip()
        )
        evidence_sources = [*evidence_forms, *evidence_memos]
        if guidance:
            evidence_sources.append({"form_id": "guidance:" + selected.id, "form_name": "补充想法（待验证）", "subject_id": selected.id, "subject_name": selected.name, "answers": [{"field_key": "guidance", "question": "补充想法（未经验证）", "value": guidance}]})
        if not evidence_sources:
            raise AIOpportunityDiscoveryError("research_answers_required", "当前对象及下级对象还没有可用于分析的调研表或备忘录。", 400)
        existing = [item.name for item in subjects if item.subject_type == "opportunity"]
        context = {
            "project": {"name": project.name, "enterprise_name": project.enterprise_name},
            "scope": {"subject_id": selected.id, "subject_type": selected.subject_type, "name": selected.name},
            "included_forms": evidence_forms,
            "included_memos": evidence_memos,
            "existing_opportunities": existing,
            "user_guidance": guidance,
            "guidance_source": next((item for item in evidence_sources if item["form_id"].startswith("guidance:")), None),
            "expand": expand,
        }
        try:
            raw = _client().complete_json(
                messages=build_ai_opportunity_messages(context),
                request_id=f"ai-opportunity-{uuid4()}", max_tokens=8192,
                on_event=on_event,
                **({"deep_thinking": False} if not expand else {}),
            )
        except DeepSeekError as error:
            status = {"ai_timeout": 504, "ai_output_invalid": 502, "ai_empty_response": 502}.get(error.code, 503)
            raise AIOpportunityDiscoveryError(error.code, error.public_message, status) from error
        candidates = _normalize_candidates(raw, evidence_sources, format_only=not expand)
        logger.info(
            "AI opportunity discovery completed project_id=%s subject_id=%s forms=%s memos=%s candidates=%s has_guidance=%s",
            project.id,
            selected.id,
            len(evidence_forms),
            len(evidence_memos),
            len(candidates),
            bool(guidance),
        )
        return {
            "scope": context["scope"],
            "included_form_count": len(evidence_forms),
            "included_memo_count": len(evidence_memos),
            "candidates": candidates,
        }
    finally:
        session.close()


def _normalize_request(payload: object) -> tuple[str, str, str]:
    allowed = {"project_id", "subject_id", "guidance", "references", "expand"}
    if not isinstance(payload, dict) or set(payload) - allowed or not {"project_id", "subject_id"}.issubset(payload):
        raise AIOpportunityDiscoveryError("invalid_request", "AI 机会分析请求格式不正确。", 400)
    project_id, subject_id = payload.get("project_id"), payload.get("subject_id")
    guidance = payload.get("guidance", "")
    if not isinstance(project_id, str) or not project_id.strip() or not isinstance(subject_id, str) or not subject_id.strip():
        raise AIOpportunityDiscoveryError("invalid_request", "项目或调研对象信息不正确。", 400)
    if not isinstance(guidance, str) or len(guidance) > 4000:
        raise AIOpportunityDiscoveryError("invalid_request", "补充想法格式不正确或超过 4000 字。", 400)
    return project_id.strip(), subject_id.strip(), guidance.strip()


def _descendant_ids(subjects, root_id: str) -> set[str]:
    result: set[str] = set()
    queue = [root_id]
    while queue:
        parent = queue.pop(0)
        for subject in subjects:
            if subject.parent_subject_id == parent and subject.subject_type != "opportunity" and subject.id not in result:
                result.add(subject.id); queue.append(subject.id)
    return result


def _form_context(form: ProjectResearchForm) -> dict[str, Any]:
    revision = form.current_revision
    definition = revision.definition_snapshot if revision else {}
    labels: dict[str, str] = {}
    for section in definition.get("sections", []) if isinstance(definition, dict) else []:
        if isinstance(section, dict):
            for field in section.get("fields", []):
                if isinstance(field, dict) and isinstance(field.get("field_key"), str):
                    labels[field["field_key"]] = str(field.get("name") or field["field_key"])
    answers = [] if revision is None else [
        {"field_key": answer.field_key, "question": labels.get(answer.field_key, answer.field_key), "value": answer.value_json}
        for answer in revision.answers if answer.value_json not in (None, "", [], {})
    ]
    return {"form_id": form.id, "form_name": form.name, "subject_id": form.subject_id, "subject_name": form.subject.name, "answers": answers}


def _memo_context(subject: ProjectResearchSubject) -> dict[str, Any]:
    return {
        "form_id": f"memo:{subject.id}",
        "form_name": f"{subject.name}备忘录",
        "subject_id": subject.id,
        "subject_name": subject.name,
        "answers": [{"field_key": "memo", "question": "备忘录", "value": subject.memo}],
    }


def _personal_memo_context(
    memo: ProjectResearchPersonalMemo, subject: ProjectResearchSubject
) -> dict[str, Any]:
    return {
        "form_id": f"personal-memo:{subject.id}:{memo.user_id}",
        "form_name": f"{subject.name}个人备忘录（{memo.author.display_name}）",
        "subject_id": subject.id,
        "subject_name": subject.name,
        "answers": [{"field_key": "memo", "question": "个人备忘录", "value": memo.memo}],
    }


def _normalize_candidates(raw: dict[str, Any], forms: list[dict[str, Any]], *, format_only=False) -> list[dict[str, Any]]:
    items = raw.get("candidates")
    if not isinstance(items, list):
        raise AIOpportunityDiscoveryError("ai_output_invalid", "AI 返回的机会候选格式不正确，请重试。", 502)
    valid_form_ids = {item["form_id"] for item in forms}
    result = []
    for item in items[:8]:
        if not isinstance(item, dict): continue
        text_fields = ("name", "description", "target_audience", "next_action")
        if not all(isinstance(item.get(key), str) and (item[key].strip() or (format_only and key in {"target_audience", "next_action"})) for key in text_fields): continue
        if item.get("priority") not in {"high", "medium", "low"} or item.get("risk_level") not in {"high", "medium", "low"}: continue
        scores = [item.get(key) for key in ("business_value_score", "feasibility_score", "data_readiness_score")]
        if not all(type(score) is int and 1 <= score <= 5 for score in scores): continue
        evidence = item.get("evidence")
        if not isinstance(evidence, list): continue
        normalized_evidence = [entry for entry in evidence if isinstance(entry, dict) and entry.get("form_id") in valid_form_ids and all(isinstance(entry.get(key), str) for key in ("form_name", "field_key", "question", "answer_excerpt", "reason"))]
        if format_only:
            # Format-only is extractive: generated claims are never silently
            # accepted as user-supplied facts. Validate against selected sources.
            source_texts = [str(answer.get("value", "")) for source in forms for answer in source.get("answers", [])]
            def quoted(value):
                return isinstance(value, str) and bool(value.strip()) and any(value.strip() in source for source in source_texts)
            normalized_evidence = [entry for entry in normalized_evidence if quoted(entry["answer_excerpt"])]
            if normalized_evidence:
                excerpt = normalized_evidence[0]["answer_excerpt"].strip()
                item = dict(item)
                item["name"] = item["name"].strip() if quoted(item["name"]) else excerpt[:160]
                item["description"] = item["description"].strip() if quoted(item["description"]) else excerpt
                for key in ("target_audience", "next_action"):
                    item[key] = item[key].strip() if quoted(item[key]) else ""
                original_answers = item.get("research_answers") if isinstance(item.get("research_answers"), dict) else {}
                item["research_answers"] = {key: value.strip() if quoted(value) else "" for key, value in original_answers.items()}
        if not normalized_evidence: continue
        supplied = item.get("research_answers") if isinstance(item.get("research_answers"), dict) else {}
        normalized_research_answers = ({key: supplied[key].strip() if isinstance(supplied.get(key), str) else "" for key in OPPORTUNITY_RESEARCH_ANSWER_KEYS} if format_only else _normalize_research_answers(item, normalized_evidence))
        result.append({
            "id": str(uuid4()), **{key: item[key].strip() for key in text_fields},
            "priority": "medium" if format_only else item["priority"], "risk_level": "medium" if format_only else item["risk_level"],
            "business_value_score": 3 if format_only else scores[0], "feasibility_score": 3 if format_only else scores[1], "data_readiness_score": 3 if format_only else scores[2],
            "research_answers": normalized_research_answers,
            "evidence": normalized_evidence[:10],
        })
    if items and not result:
        raise AIOpportunityDiscoveryError("ai_output_invalid", "AI 返回的机会候选缺少有效调研证据，请重试。", 502)
    return result


def _normalize_research_answers(item: dict[str, Any], evidence: list[dict[str, Any]]) -> dict[str, str]:
    raw = item.get("research_answers")
    supplied = raw if isinstance(raw, dict) else {}
    evidence_summary = "；".join(
        entry["answer_excerpt"].strip()
        for entry in evidence[:3]
        if isinstance(entry.get("answer_excerpt"), str) and entry["answer_excerpt"].strip()
    )
    defaults = {
        "current_state": evidence_summary or "待进一步调研确认当前业务现状。",
        "pain_points": item["description"].strip(),
        "business_value": f"{item['description'].strip()}（业务价值评分 {item['business_value_score']}/5，具体收益口径待进一步确认。）",
        "target_scenario": f"{item['description'].strip()}；目标使用对象：{item['target_audience'].strip()}。",
        "owner_role": "待进一步调研确认该机会的业务负责人和协作角色。",
        "technical_prereqs": f"待进一步确认具体技术前提；当前数据准备度评分为 {item['data_readiness_score']}/5。",
    }
    return {
        key: supplied[key].strip()
        if isinstance(supplied.get(key), str) and supplied[key].strip()
        else defaults[key]
        for key in OPPORTUNITY_RESEARCH_ANSWER_KEYS
    }


def _client() -> DeepSeekClient:
    injected = current_app.extensions.get("fde_api_ai_opportunity_deepseek")
    if injected is not None: return injected
    settings: Settings = current_app.config["SETTINGS"]
    return DeepSeekClient(
        base_url=settings.deepseek_base_url,
        api_key=settings.deepseek_api_key,
        model=settings.deepseek_ai_opportunity_model,
        timeout_seconds=settings.deepseek_timeout_seconds,
    )
