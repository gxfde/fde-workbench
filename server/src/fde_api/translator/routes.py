"""翻译器门户路由（goal-d9，PRD §3.2 P3）。

api_catalog 收编口径（报告 §二 登记）：translator.translate（POST，创作类
写——AI 只出草稿，无拍板语义）与 translator.translations（GET 只读）两条；
人工拍板类路径永不收编（红线）。
"""
from __future__ import annotations

from flask import Blueprint, g, jsonify, request

from fde_api.auth.decorators import require_auth
from fde_api.errors import error_response
from fde_api.guidance.service import GuidanceServiceError, adopt_translator_draft
from fde_api.translator import service
from fde_api.translator.service import TranslatorServiceError

translator_blueprint = Blueprint("translator", __name__, url_prefix="/api/v1/translator")


@translator_blueprint.errorhandler(TranslatorServiceError)
def service_error(error: TranslatorServiceError):
    return error_response(error.code, error.message, error.status)


@translator_blueprint.errorhandler(GuidanceServiceError)
def guidance_error(error: GuidanceServiceError):
    # adopt 的闸（项目权限/ready/重复采纳）在 guidance 域，错误口径一致透出。
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


@translator_blueprint.post("/translations/<translation_id>/adopt")
@require_auth
def adopt_translation(translation_id: str):
    """采纳翻译草稿为项目指引新版本（goal-d10 采纳流；O-3 额度随路落）。

    编辑/逐条确认/确认（PATCH/confirm）统一在项目侧 guidance 既有端点——
    一份指引一处编辑权；本端点只负责「进项目」这一步。
    """
    payload = _payload()
    project_id = payload.get("project_id")
    if not isinstance(project_id, str) or not project_id.strip():
        raise TranslatorServiceError("invalid_request", "project_id 必须是非空字符串。", 400)
    return _data(adopt_translator_draft(
        actor=g.current_user, project_id=project_id.strip(), translation_id=translation_id,
    ))
