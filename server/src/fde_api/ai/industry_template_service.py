"""Industry-template AI orchestration without conversation persistence."""

from __future__ import annotations

import json
from typing import Any, Callable
from uuid import UUID

from flask import current_app
from sqlalchemy import select

from fde_api.ai.deepseek import DeepSeekClient, DeepSeekError
from fde_api.ai.industry_template_prompt import (
    build_chat_messages,
    build_generation_messages,
)
from fde_api.ai.industry_template_schema import (
    AIContractError,
    parse_chat_decision,
    validate_chat_messages,
    validate_generated_template,
)
from fde_api.auth.models import User
from fde_api.config import Settings
from fde_api.extensions import db
from fde_api.templates.service import TemplateServiceError, create_ai_template_draft
from fde_api.workbench.models import ModuleCatalog


class IndustryTemplateAIError(Exception):
    def __init__(self, code: str, message: str, status: int, details: dict | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status
        self.details = details


def chat_about_template(*, actor: User, payload: object, on_event: Callable[[dict[str, str]], None] | None = None) -> dict[str, Any]:
    del actor
    if not isinstance(payload, dict) or set(payload) != {"messages"}:
        raise _invalid_request()
    try:
        history = validate_chat_messages(payload["messages"])
    except AIContractError as error:
        raise _contract_error(error) from error
    catalog = _active_catalog()
    raw = _call_ai(build_chat_messages(history, catalog), request_id="industry-chat", on_event=on_event)
    try:
        return parse_chat_decision(raw)
    except AIContractError:
        # Chat output is advisory and does not write data. Recover safely from
        # harmless model variations (extra keys, omitted empty arrays, etc.) so
        # a useful user request is not blocked before draft generation.
        return _repair_chat_decision(raw, history)


def generate_template_draft(*, actor: User, payload: object, on_event: Callable[[dict[str, str]], None] | None = None) -> dict[str, Any]:
    raw = generate_project_configuration(actor=actor, payload=payload, on_event=on_event)
    try:
        return create_ai_template_draft(actor=actor, generated=raw)
    except TemplateServiceError as error:
        raise IndustryTemplateAIError(error.code, error.message, error.status, error.details) from error


def generate_project_configuration(*, actor: User, payload: object, on_event: Callable[[dict[str, str]], None] | None = None) -> dict[str, Any]:
    if not isinstance(payload, dict) or set(payload) != {
        "generation_id", "messages", "known_information"
    }:
        raise _invalid_request()
    generation_id = _generation_id(payload.get("generation_id"))
    known = payload.get("known_information")
    if not isinstance(known, dict):
        raise _invalid_request()
    try:
        history = validate_chat_messages(payload["messages"])
    except AIContractError as error:
        raise _contract_error(error) from error
    if _is_cancelled(actor.id, generation_id):
        raise _cancelled()

    catalog = _active_catalog()
    raw: dict[str, Any] | None = None
    last_contract_error: AIContractError | None = None
    generation_messages = build_generation_messages(history, known, catalog)
    for attempt in range(2):
        raw = _call_ai(
            generation_messages,
            request_id=f"industry-generate-{generation_id}-{attempt + 1}",
            on_event=on_event,
        )
        try:
            validate_generated_template(
                raw, active_module_keys={item["module_key"] for item in catalog}
            )
            last_contract_error = None
            break
        except AIContractError as error:
            last_contract_error = error
            generation_messages = [
                *build_generation_messages(history, known, catalog),
                {"role": "assistant", "content": json.dumps(raw, ensure_ascii=False)},
                {
                    "role": "user",
                    "content": (
                        f"上一版 JSON 校验失败：路径 {error.path or '根对象'}，原因：{error.message}。"
                        "请修正这一项以及所有同类问题，保持业务内容不变，并重新输出完整 JSON。"
                    ),
                },
            ]
    if last_contract_error is not None or raw is None:
        assert last_contract_error is not None
        raise _contract_error(last_contract_error)
    if _is_cancelled(actor.id, generation_id):
        raise _cancelled()
    return raw


def cancel_generation(*, actor: User, generation_id: str) -> dict[str, bool]:
    normalized = _generation_id(generation_id)
    redis = current_app.extensions["fde_api_redis"]
    redis.setex(_cancel_key(actor.id, normalized), 900, "1")
    return {"cancelled": True}


def _call_ai(messages: list[dict[str, str]], *, request_id: str, on_event: Callable[[dict[str, str]], None] | None = None) -> dict[str, Any]:
    try:
        return _client().complete_json(messages=messages, request_id=request_id, on_event=on_event)
    except DeepSeekError as error:
        status = {
            "ai_service_not_configured": 503,
            "ai_authentication_failed": 503,
            "ai_rate_limited": 429,
            "ai_timeout": 504,
            "ai_empty_response": 502,
            "ai_output_invalid": 502,
        }.get(error.code, 503)
        raise IndustryTemplateAIError(error.code, error.public_message, status) from error


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


def _repair_chat_decision(raw: dict[str, Any], history: list[dict[str, str]]) -> dict[str, Any]:
    latest_user = next((item["content"] for item in reversed(history) if item["role"] == "user"), "")
    known = raw.get("known_information") if isinstance(raw.get("known_information"), dict) else {}
    known = dict(known)
    if latest_user:
        known.setdefault("user_requirement", latest_user)
    raw_status = raw.get("status")
    status = raw_status if raw_status in {"need_more_information", "ready_to_generate"} else "ready_to_generate"
    questions = [item.strip() for item in raw.get("questions", []) if isinstance(item, str) and item.strip()][:1] if isinstance(raw.get("questions"), list) else []
    if status == "need_more_information" and not questions:
        # A missing question cannot help the user; proceed with assumptions.
        status = "ready_to_generate"
    if status == "ready_to_generate":
        questions = []
    missing = [item.strip() for item in raw.get("missing_fields", []) if isinstance(item, str) and item.strip()][:20] if isinstance(raw.get("missing_fields"), list) else []
    message = raw.get("message")
    if not isinstance(message, str) or not message.strip():
        message = "信息已记录，可以开始生成可修改的草稿。"
    return {
        "status": status,
        "message": message.strip()[:2000],
        "known_information": known,
        "missing_fields": missing,
        "questions": questions,
    }


def _active_catalog() -> list[dict[str, Any]]:
    session = db.session()
    try:
        modules = list(
            session.scalars(
                select(ModuleCatalog)
                .where(ModuleCatalog.is_active.is_(True))
                .order_by(ModuleCatalog.sort_order, ModuleCatalog.module_key)
            )
        )
        return [
            {
                "module_key": module.module_key,
                "name": module.name,
                "description": module.description,
            }
            for module in modules
        ]
    finally:
        session.close()


def _generation_id(value: object) -> str:
    if not isinstance(value, str):
        raise _invalid_request()
    try:
        return str(UUID(value))
    except ValueError as error:
        raise _invalid_request() from error


def _is_cancelled(user_id: str, generation_id: str) -> bool:
    redis = current_app.extensions["fde_api_redis"]
    return redis.get(_cancel_key(user_id, generation_id)) is not None


def _cancel_key(user_id: str, generation_id: str) -> str:
    return f"ai:industry-template:generation:{user_id}:{generation_id}"


def _contract_error(error: AIContractError) -> IndustryTemplateAIError:
    return IndustryTemplateAIError(
        "ai_output_invalid",
        f"AI 生成内容不符合要求：{error.message}",
        400,
        {"path": error.path, "issue_code": error.code},
    )


def _invalid_request() -> IndustryTemplateAIError:
    return IndustryTemplateAIError("invalid_request", "请求内容不符合要求。", 400)


def _cancelled() -> IndustryTemplateAIError:
    return IndustryTemplateAIError("generation_cancelled", "生成已取消，未创建草稿。", 409)
