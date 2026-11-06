"""Create an editable project draft from an uploaded pre-survey document."""

from __future__ import annotations

from typing import Any, BinaryIO
from uuid import uuid4

from flask import current_app
from sqlalchemy import select

from fde_api.ai.kimi import KimiError, KimiFileClient
from fde_api.config import Settings
from fde_api.extensions import db
from fde_api.guidance.enterprise_dict import RedactionConfigError
from fde_api.guidance.redaction import SensitiveCredentialDetected, redact_text
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
        local_extract=settings.kimi_local_docx_extract,
        openai_compatible=settings.kimi_openai_compatible,
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
    except SensitiveCredentialDetected as error:
        # E4：预调研文件里出现疑似密码/密钥/令牌 → 明确拒绝，不把原文送出去。
        raise ProjectDraftError("sensitive_content_detected", str(error), 400) from None
    except RedactionConfigError as error:
        # T-A2 闸①第①层：企业名词典机制性故障 → fail-closed 硬阻断（503）。
        # 放行等于把「企业名可能漏替换」的全文直接送进模型，违反代号化红线。
        raise ProjectDraftError("pseudonym_dict_unavailable", str(error), 503) from None
    return _normalize(result, allowed)


def _messages(content: str, catalog_text: str) -> list[dict[str, str]]:
    # E4 脱敏一致：预调研 DOCX 全文进 LLM 前必须走 guidance 路径同一套
    # redact_text（邮箱/手机/证件/座机脱敏，疑似凭据直接拒绝）——此前这条
    # 路径未脱敏，与 guidance/jobs.py 行为不一致。
    redacted = redact_text(content)
    return [
        {"role": "system", "content": (
            "你是 FDE 项目创建助手。只依据上传预调研表提取项目草稿，不得编造。"
            "输出 JSON：project(name,enterprise_code,background,notes,industry_name)，"
            "其中 enterprise_code 是客户代号（格式「客户A·行业·城市」，行业/城市可用文件信息，客户序号留待人工定），"
            "绝不输出真实企业名/联系人/电话/地址（A2 代号化红线），无法确定留空。"
            f"modules 数组，每项为 module_key,name,description,tasks。module_key 只能从当前系统模块目录选择：{catalog_text}；"
            "tasks 每项为 task_key,name,description,duration_days,default_assignee_role,dependency_keys,sort_order。"
            "无法确认的字符串留空。只输出 JSON。"
        )},
        {"role": "user", "content": f"请从以下预调研文件内容生成可人工调整的项目草稿：\n\n{redacted[:120000]}"},
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
            "name", "enterprise_code", "background", "notes", "industry_name"
        )},
        "modules": normalized_modules,
    }
