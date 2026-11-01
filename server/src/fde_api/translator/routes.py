"""翻译器门户路由（goal-d9，PRD §3.2 P3）。

api_catalog 收编口径（报告 §二 登记）：translator.translate（POST，创作类
写——AI 只出草稿，无拍板语义）与 translator.translations（GET 只读）两条；
人工拍板类路径永不收编（红线）。
"""
from __future__ import annotations

from flask import Blueprint, g, jsonify, request

from fde_api.auth.decorators import require_auth
from fde_api.errors import error_response
from fde_api.translator import service
from fde_api.translator.service import TranslatorServiceError

translator_blueprint = Blueprint("translator", __name__, url_prefix="/api/v1/translator")


@translator_blueprint.errorhandler(TranslatorServiceError)
def service_error(error: TranslatorServiceError):
    return error_response(error.code, error.message, error.status)


def _payload() -> dict:
    value = request.get_json(silent=True)
    if not isinstance(value, dict):
        raise TranslatorServiceError("invalid_request", "请求内容必须为 JSON 对象。", 400)
    return value


def _data(value):
    return jsonify({"data": value, "error": None})


@translator_blueprint.post("/translations")
@require_auth
def create_translation():
    """创建翻译请求并投递 AI 翻译管道（AI 只出草稿）。"""
    return _data(service.create_translation(actor=g.current_user, payload=_payload())), 201


@translator_blueprint.get("/translations")
@require_auth
def list_translations():
    """本人翻译草稿列表（最近 20 条）。"""
    return _data({"items": service.list_translations(actor=g.current_user)})


@translator_blueprint.get("/translations/<translation_id>")
@require_auth
def get_translation(translation_id: str):
    """翻译草稿详情（轮询就绪/失败态；创建人或 admin）。"""
    return _data(service.get_translation(actor=g.current_user, translation_id=translation_id))
