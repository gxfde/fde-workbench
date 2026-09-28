"""Generate one validated research form without persisting it."""

from __future__ import annotations

import re
from typing import Any, Callable

from flask import current_app
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from fde_api.ai.deepseek import DeepSeekClient, DeepSeekError
from fde_api.ai.research_form_prompt import build_research_form_messages
from fde_api.config import Settings
from fde_api.extensions import db
from fde_api.projects.permissions import project_access
from fde_api.research.definitions import validate_research_definition
from fde_api.research.models import (
    FIELD_TYPES,
    SUBJECT_TYPES,
    ProjectResearchForm,
    ProjectResearchSubject,
    TemplateResearchForm,
)
from fde_api.auth.models import User
from fde_api.workbench.models import (
    IndustryTemplateVersion,
    Project,
    ProjectModule,
    TemplateModule,
)


class ResearchFormAIError(Exception):
    def __init__(self, code: str, message: str, status: int):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


def generate_research_form(payload: object, *, on_event: Callable[[dict[str, str]], None] | None = None) -> dict[str, Any]:
    parsed = _validate_payload(payload)
    session = db.session()
    try:
        version = session.scalar(
            select(IndustryTemplateVersion)
            .where(
                IndustryTemplateVersion.id == parsed["version_id"],
                IndustryTemplateVersion.template_id == parsed["template_id"],
            )
            .options(
                selectinload(IndustryTemplateVersion.template),
                selectinload(IndustryTemplateVersion.modules).selectinload(TemplateModule.module_catalog),
                selectinload(IndustryTemplateVersion.research_forms),
            )
        )
        if version is None:
            raise ResearchFormAIError("template_version_not_found", "行业模板版本不存在。", 404)
        if version.status != "draft":
            raise ResearchFormAIError("template_version_not_editable", "只能为草稿版本生成调研表。", 409)

        module_keys = [module.module_catalog.module_key for module in version.modules]
        existing = _merged_existing_forms(version.research_forms, parsed["existing_forms"])
        context = {
            "template": {
                "name": version.name,
                "industry_name": version.industry_name,
                "description": version.description,
            },
            "modules": [
                {
                    "module_key": module.module_catalog.module_key,
                    "name": module.name,
                    "description": module.description,
                }
                for module in version.modules
            ],
            "existing_forms": existing,
            "requirement": parsed["requirement"] or "请根据当前模板自动生成下一份最有价值且不重复的调研表。",
        }
        messages = build_research_form_messages(context)
        existing_keys = {item["form_key"] for item in existing}
        for attempt in range(2):
            try:
                raw = _call_ai(messages, on_event=on_event)
            except ResearchFormAIError as error:
                if attempt == 0 and error.code in {"ai_empty_response", "ai_output_invalid"}:
                    messages = _retry_messages(messages)
                    continue
                raise
            normalized = _normalize_generated_form(raw)
            if normalized is not None and _valid_generated_form(normalized, module_keys, existing_keys):
                return normalized
            if attempt == 0:
                messages = _retry_messages(messages)
        raise ResearchFormAIError(
            "ai_output_invalid",
            "AI 生成的调研表结构不符合要求，请调整描述后重试。",
            502,
        )
    finally:
        session.close()


def generate_project_research_form(*, actor: User, payload: object, on_event: Callable[[dict[str, str]], None] | None = None) -> dict[str, Any]:
    parsed = _validate_project_payload(payload)
    session = db.session()
    try:
        project = session.scalar(
            select(Project)
            .where(Project.id == parsed["project_id"])
            .options(
                selectinload(Project.members),
                selectinload(Project.source_template_version),
                selectinload(Project.modules).selectinload(ProjectModule.module_catalog),
            )
        )
        if project is None or not project_access(actor, project).can_view:
            raise ResearchFormAIError("project_not_found", "项目不存在或无权访问。", 404)
        access = project_access(actor, project)
        if not (access.can_manage or access.can_update_assigned_tasks):
            raise ResearchFormAIError("forbidden", "你没有权限为当前项目生成调研表。", 403)
        subject = session.scalar(
            select(ProjectResearchSubject).where(
                ProjectResearchSubject.id == parsed["subject_id"],
                ProjectResearchSubject.project_id == project.id,
            )
        )
        if subject is None or subject.status != "active":
            raise ResearchFormAIError("research_subject_not_found", "当前调研对象不存在或已停用。", 404)
        persisted = list(
            session.scalars(
                select(ProjectResearchForm).where(
                    ProjectResearchForm.project_id == project.id,
                    ProjectResearchForm.subject_id == subject.id,
                )
            )
        )
        existing = _merged_project_forms(persisted, parsed["existing_forms"])
        active_modules = [module for module in project.modules if module.status == "active"]
        context = {
            "project": {
                "name": project.name,
                "enterprise_name": project.enterprise_name,
                "background": project.background,
                "industry_name": (
                    project.source_template_version.industry_name
                    if project.source_template_version is not None
                    else str((project.template_snapshot or {}).get("industry_name") or "通用")
                ),
            },
            "required_subject": {
                "subject_type": subject.subject_type,
                "name": subject.name,
                "description": subject.description,
            },
            "modules": [
                {
                    "module_key": module.module_catalog.module_key,
                    "name": module.name,
                    "description": module.description,
                }
                for module in active_modules
            ],
            "existing_forms": existing,
            "requirement": parsed["requirement"] or "请针对当前调研对象生成一份实用、不重复的调研表。",
        }
        messages = build_research_form_messages(context)
        module_keys = [module.module_catalog.module_key for module in active_modules]
        existing_keys = {item["form_key"] for item in existing}
        for attempt in range(2):
            try:
                raw = _call_ai(messages, on_event=on_event)
            except ResearchFormAIError as error:
                if attempt == 0 and error.code in {"ai_empty_response", "ai_output_invalid"}:
                    messages = _retry_messages(messages, required_subject_type=subject.subject_type)
                    continue
                raise
            normalized = _normalize_generated_form(raw, required_subject_type=subject.subject_type)
            if _valid_generated_form(
                normalized,
                module_keys,
                existing_keys,
                required_subject_type=subject.subject_type,
            ):
                return normalized
            if attempt == 0:
                messages = _retry_messages(messages, required_subject_type=subject.subject_type)
        raise ResearchFormAIError(
            "ai_output_invalid",
            "AI 生成的调研表结构不符合要求，请调整描述后重试。",
            502,
        )
    finally:
        session.close()


def _validate_payload(payload: object) -> dict[str, Any]:
    if not isinstance(payload, dict) or set(payload) != {
        "template_id", "version_id", "requirement", "existing_forms"
    }:
        raise ResearchFormAIError("invalid_request", "调研表 AI 生成请求格式不正确。", 400)
    template_id = payload.get("template_id")
    version_id = payload.get("version_id")
    requirement = payload.get("requirement")
    existing_forms = payload.get("existing_forms")
    if not isinstance(template_id, str) or not template_id or not isinstance(version_id, str) or not version_id:
        raise ResearchFormAIError("invalid_request", "行业模板版本信息不正确。", 400)
    if not isinstance(requirement, str) or len(requirement) > 4_000:
        raise ResearchFormAIError("invalid_request", "调研表生成要求不能超过 4000 个字。", 400)
    if not isinstance(existing_forms, list) or len(existing_forms) > 100:
        raise ResearchFormAIError("invalid_request", "已有调研表信息不正确。", 400)
    normalized: list[dict[str, str]] = []
    for item in existing_forms:
        if not isinstance(item, dict) or set(item) != {"form_key", "name", "subject_type"}:
            raise ResearchFormAIError("invalid_request", "已有调研表信息不正确。", 400)
        if not all(isinstance(item.get(key), str) for key in ("form_key", "name", "subject_type")):
            raise ResearchFormAIError("invalid_request", "已有调研表信息不正确。", 400)
        normalized.append({key: item[key] for key in ("form_key", "name", "subject_type")})
    return {
        "template_id": template_id,
        "version_id": version_id,
        "requirement": requirement.strip(),
        "existing_forms": normalized,
    }


def _validate_project_payload(payload: object) -> dict[str, Any]:
    if not isinstance(payload, dict) or set(payload) != {
        "project_id", "subject_id", "requirement", "existing_forms"
    }:
        raise ResearchFormAIError("invalid_request", "项目调研表 AI 生成请求格式不正确。", 400)
    common = _validate_existing_and_requirement(payload)
    project_id = payload.get("project_id")
    subject_id = payload.get("subject_id")
    if not isinstance(project_id, str) or not project_id or not isinstance(subject_id, str) or not subject_id:
        raise ResearchFormAIError("invalid_request", "项目或调研对象信息不正确。", 400)
    return {"project_id": project_id, "subject_id": subject_id, **common}


def _validate_existing_and_requirement(payload: dict[str, Any]) -> dict[str, Any]:
    requirement = payload.get("requirement")
    existing_forms = payload.get("existing_forms")
    if not isinstance(requirement, str) or len(requirement) > 4_000:
        raise ResearchFormAIError("invalid_request", "调研表生成要求不能超过 4000 个字。", 400)
    if not isinstance(existing_forms, list) or len(existing_forms) > 100:
        raise ResearchFormAIError("invalid_request", "已有调研表信息不正确。", 400)
    normalized: list[dict[str, str]] = []
    for item in existing_forms:
        if not isinstance(item, dict) or set(item) != {"form_key", "name", "subject_type"}:
            raise ResearchFormAIError("invalid_request", "已有调研表信息不正确。", 400)
        if not all(isinstance(item.get(key), str) for key in ("form_key", "name", "subject_type")):
            raise ResearchFormAIError("invalid_request", "已有调研表信息不正确。", 400)
        normalized.append({key: item[key] for key in ("form_key", "name", "subject_type")})
    return {"requirement": requirement.strip(), "existing_forms": normalized}


def _merged_existing_forms(
    persisted: list[TemplateResearchForm], incoming: list[dict[str, str]]
) -> list[dict[str, str]]:
    merged = {
        form.form_key: {
            "form_key": form.form_key,
            "name": form.name,
            "subject_type": form.subject_type,
        }
        for form in persisted
    }
    for item in incoming:
        if item["form_key"]:
            merged[item["form_key"]] = item
    return list(merged.values())


def _merged_project_forms(
    persisted: list[ProjectResearchForm], incoming: list[dict[str, str]]
) -> list[dict[str, str]]:
    merged = {
        form.form_key: {
            "form_key": form.form_key,
            "name": form.name,
            "subject_type": form.subject.subject_type if form.subject is not None else "project",
        }
        for form in persisted
    }
    for item in incoming:
        if item["form_key"]:
            merged[item["form_key"]] = item
    return list(merged.values())


def _valid_generated_form(
    value: object,
    module_keys: list[str],
    existing_keys: set[str],
    *,
    required_subject_type: str | None = None,
) -> bool:
    if not isinstance(value, dict) or set(value) != {
        "form_key", "name", "description", "subject_type", "module_key", "sections"
    }:
        return False
    if value.get("subject_type") not in SUBJECT_TYPES:
        return False
    if required_subject_type is not None and value.get("subject_type") != required_subject_type:
        return False
    if value.get("module_key") is not None and value.get("module_key") not in module_keys:
        return False
    if value.get("form_key") in existing_keys:
        return False
    sections = value.get("sections")
    if not isinstance(sections, list) or not sections:
        return False
    for section in sections:
        if not isinstance(section, dict) or set(section) != {"section_key", "name", "description", "fields"}:
            return False
        fields = section.get("fields")
        if not isinstance(fields, list) or not fields:
            return False
        for field in fields:
            if not isinstance(field, dict) or set(field) != {
                "field_key", "name", "help_text", "type", "is_required", "options"
            }:
                return False
            if field.get("type") not in FIELD_TYPES:
                return False
    return not validate_research_definition({"forms": [value]})


def _normalize_generated_form(
    value: object,
    *,
    required_subject_type: str | None = None,
) -> dict[str, Any] | None:
    """Repair harmless model formatting drift while keeping semantic validation strict."""
    if not isinstance(value, dict):
        return None
    for wrapper_key in ("form", "research_form", "data", "result"):
        wrapped = value.get(wrapper_key)
        if isinstance(wrapped, dict):
            value = wrapped
            break
    sections = value.get("sections")
    if not isinstance(sections, list) or not sections:
        return None
    normalized_sections: list[dict[str, Any]] = []
    for section_index, section in enumerate(sections):
        if not isinstance(section, dict):
            return None
        fields = section.get("fields")
        if not isinstance(fields, list) or not fields:
            return None
        normalized_fields: list[dict[str, Any]] = []
        for field_index, field in enumerate(fields):
            if not isinstance(field, dict):
                return None
            field_type = field.get("type")
            options = field.get("options")
            if not isinstance(field_type, str):
                return None
            if not isinstance(options, dict):
                options = {}
            if field_type == "file_reference" and not isinstance(options.get("max_files"), int):
                options = {"max_files": 5}
            required = field.get("is_required", False)
            if isinstance(required, str) and required.lower() in {"true", "false"}:
                required = required.lower() == "true"
            normalized_fields.append({
                "field_key": _stable_key(field.get("field_key"), f"question_{section_index + 1}_{field_index + 1}"),
                "name": field.get("name"),
                "help_text": field.get("help_text") if isinstance(field.get("help_text"), str) else "",
                "type": field_type,
                "is_required": required,
                "options": options,
            })
        normalized_sections.append({
            "section_key": _stable_key(section.get("section_key"), f"section_{section_index + 1}"),
            "name": section.get("name"),
            "description": section.get("description") if isinstance(section.get("description"), str) else "",
            "fields": normalized_fields,
        })
    return {
        "form_key": _stable_key(value.get("form_key"), "generated_research_form"),
        "name": value.get("name"),
        "description": value.get("description") if isinstance(value.get("description"), str) else "",
        "subject_type": required_subject_type or value.get("subject_type"),
        "module_key": value.get("module_key") if isinstance(value.get("module_key"), str) else None,
        "sections": normalized_sections,
    }


def _stable_key(value: object, fallback: str) -> str:
    if not isinstance(value, str) or not value.strip():
        return fallback
    key = re.sub(r"[^a-z0-9]+", "_", value.strip().lower()).strip("_")
    if not key or not key[0].isalpha():
        key = f"item_{key}" if key else fallback
    return key[:100]


def _retry_messages(
    messages: list[dict[str, str]],
    *,
    required_subject_type: str | None = None,
) -> list[dict[str, str]]:
    subject_instruction = (
        f" subject_type 必须严格为 {required_subject_type}。"
        if required_subject_type is not None
        else ""
    )
    return [
        *messages,
        {
            "role": "user",
            "content": (
                "上一次结果未通过结构校验。请重新生成完整 JSON；不要增加包装层或额外字段，"
                "所有 name 必须是非空字符串，所有稳定标识使用小写 snake_case，"
                "每个字段必须包含 help_text、is_required 和 options。"
                "限制为 2 至 4 个章节、总共不超过 20 个问题，直接输出闭合的 JSON 对象。"
                f"{subject_instruction}"
            ),
        },
    ]


def _call_ai(messages: list[dict[str, str]], *, on_event: Callable[[dict[str, str]], None] | None = None) -> dict[str, Any]:
    try:
        return _client().complete_json(
            messages=messages,
            request_id="industry-research-form-generate",
            max_tokens=12_000,
            on_event=on_event,
        )
    except DeepSeekError as error:
        status = {
            "ai_service_not_configured": 503,
            "ai_authentication_failed": 503,
            "ai_rate_limited": 429,
            "ai_timeout": 504,
            "ai_empty_response": 502,
            "ai_output_invalid": 502,
        }.get(error.code, 503)
        raise ResearchFormAIError(error.code, error.public_message, status) from error


def _client() -> DeepSeekClient:
    injected = current_app.extensions.get("fde_api_industry_deepseek")
    if injected is not None:
        return injected
    settings: Settings = current_app.config["SETTINGS"]
    return DeepSeekClient(
        base_url=settings.deepseek_base_url,
        api_key=settings.deepseek_api_key,
        model=settings.deepseek_industry_template_model,
        timeout_seconds=settings.deepseek_timeout_seconds,
    )
