"""Create an editable project draft from an uploaded pre-survey document."""

from __future__ import annotations

from typing import Any, BinaryIO
from uuid import uuid4

from flask import current_app
from sqlalchemy import select

from fde_api.ai.kimi import KimiError, KimiFileClient
from fde_api.config import Settings
from fde_api.extensions import db
from fde_api.workbench.models import ModuleCatalog


class ProjectDraftError(Exception):
    def __init__(self, code: str, message: str, status: int):
        super().__init__(message)
        self.code, self.message, self.status = code, message, status


def draft_from_presurvey(*, stream: BinaryIO, filename: str) -> dict[str, Any]:
    settings: Settings = current_app.config["SETTINGS"]
    client = KimiFileClient(
        base_url=settings.kimi_base_url,
        api_key=settings.kimi_project_presurvey_api_key,
        model=settings.kimi_project_presurvey_model,
        timeout_seconds=settings.kimi_timeout_seconds,
    )
    session = db.session()
    try:
        catalogs = list(
            session.scalars(
                select(ModuleCatalog)
                .where(ModuleCatalog.is_active.is_(True))
                .order_by(ModuleCatalog.sort_order, ModuleCatalog.name)
            )
        )
    finally:
        session.close()
    allowed = {item.module_key for item in catalogs}
    catalog_text = "、".join(f"{item.module_key}（{item.name}）" for item in catalogs)
    try:
        result = client.analyze_docx_json(
            stream=stream,
            filename=filename,
            request_id=f"project-draft-{uuid4()}",
            build_messages=lambda content: _messages(content, catalog_text),
        )
    except KimiError as error:
        status = {"ai_timeout": 504, "ai_rate_limited": 429, "ai_output_invalid": 502}.get(error.code, 503)
        raise ProjectDraftError(error.code, error.public_message, status) from error
    return _normalize(result, allowed)


def _messages(content: str, catalog_text: str) -> list[dict[str, str]]:
    return [
        {"role": "system", "content": (
            "你是 FDE 项目创建助手。只依据上传预调研表提取项目草稿，不得编造。"
            "输出 JSON：project(name,enterprise_name,contact_name,contact_phone,address,background,notes,industry_name)，"
            f"modules 数组，每项为 module_key,name,description,tasks。module_key 只能从当前系统模块目录选择：{catalog_text}；"
            "tasks 每项为 task_key,name,description,duration_days,default_assignee_role,dependency_keys,sort_order。"
            "无法确认的字符串留空。只输出 JSON。"
        )},
        {"role": "user", "content": f"请从以下预调研文件内容生成可人工调整的项目草稿：\n\n{content[:120000]}"},
    ]


def _normalize(value: dict[str, Any], allowed: set[str]) -> dict[str, Any]:
    project = value.get("project") if isinstance(value.get("project"), dict) else {}
    modules = value.get("modules") if isinstance(value.get("modules"), list) else []
    normalized_modules = [item for item in modules if isinstance(item, dict) and item.get("module_key") in allowed]
    if not normalized_modules:
        fallback_key = "pre_diagnosis" if "pre_diagnosis" in allowed else next(iter(sorted(allowed)), "")
        normalized_modules = ([{"module_key": fallback_key, "name": "预调研", "description": "整理并确认已有预调研信息。", "tasks": []}] if fallback_key else [])
    return {
        "project": {key: str(project.get(key) or "")[:4000] for key in (
            "name", "enterprise_name", "contact_name", "contact_phone", "address", "background", "notes", "industry_name"
        )},
        "modules": normalized_modules,
    }
