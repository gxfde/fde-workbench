from flask import Blueprint, g, jsonify, request

from fde_api.ai.industry_template_service import (
    IndustryTemplateAIError,
    cancel_generation,
    chat_about_template,
    generate_template_draft,
)
from fde_api.auth.decorators import require_role
from fde_api.ai.research_form_service import (
    ResearchFormAIError,
    generate_project_research_form,
    generate_research_form,
)
from fde_api.errors import error_response
from fde_api.ai.ai_opportunity_service import AIOpportunityDiscoveryError, discover_ai_opportunities
from fde_api.ai.executions import AIExecutionError, get_execution, start_execution
from fde_api.ai.project_draft import ProjectDraftError, draft_from_presurvey


ai_blueprint = Blueprint("ai", __name__, url_prefix="/api/v1/ai")


@ai_blueprint.post("/project-draft/presurvey")
@require_role("admin", "project_lead")
def project_draft_presurvey_route():
    upload = request.files.get("file")
    if upload is None or not upload.filename or not upload.filename.lower().endswith(".docx"):
        return error_response("invalid_file_type", "请上传 DOCX 格式的预调研表。", 422)
    upload.stream.seek(0, 2)
    size = upload.stream.tell()
    upload.stream.seek(0)
    if size > 100 * 1024 * 1024:
        return error_response("file_too_large", "单个文件不能超过 100MB。", 422)
    try:
        data = draft_from_presurvey(stream=upload.stream, filename=upload.filename)
        return jsonify({"data": data, "error": None})
    except ProjectDraftError as error:
        return error_response(error.code, error.message, error.status)


@ai_blueprint.post("/executions")
@require_role("admin", "project_lead", "fde_engineer")
def ai_execution_start_route():
    payload = request.get_json(silent=True) or {}
    try:
        data = start_execution(
            actor=g.current_user,
            operation=payload.get("operation", ""),
            payload=payload.get("payload"),
        )
        return jsonify({"data": data, "error": None}), 202
    except AIExecutionError as error:
        return error_response(error.code, error.message, error.status)


@ai_blueprint.get("/executions/<execution_id>")
@require_role("admin", "project_lead", "fde_engineer")
def ai_execution_get_route(execution_id: str):
    try:
        after = max(0, int(request.args.get("after", "0")))
    except ValueError:
        return error_response("invalid_request", "AI 执行游标不正确。", 400)
    try:
        data = get_execution(actor=g.current_user, execution_id=execution_id, after=after)
        return jsonify({"data": data, "error": None})
    except AIExecutionError as error:
        return error_response(error.code, error.message, error.status)


@ai_blueprint.post("/industry-template/chat")
@require_role("admin")
def industry_template_chat_route():
    try:
        data = chat_about_template(actor=g.current_user, payload=request.get_json(silent=True))
        return jsonify({"data": data, "error": None})
    except IndustryTemplateAIError as error:
        return _error(error)


@ai_blueprint.post("/industry-template/generate")
@require_role("admin")
def industry_template_generate_route():
    try:
        data = generate_template_draft(actor=g.current_user, payload=request.get_json(silent=True))
        return jsonify({"data": data, "error": None}), 201
    except IndustryTemplateAIError as error:
        return _error(error)


@ai_blueprint.delete("/industry-template/generations/<generation_id>")
@require_role("admin")
def industry_template_cancel_route(generation_id: str):
    try:
        data = cancel_generation(actor=g.current_user, generation_id=generation_id)
        return jsonify({"data": data, "error": None})
    except IndustryTemplateAIError as error:
        return _error(error)


@ai_blueprint.post("/industry-template/research-form/generate")
@require_role("admin")
def industry_template_research_form_generate_route():
    try:
        data = generate_research_form(request.get_json(silent=True))
        return jsonify({"data": data, "error": None})
    except ResearchFormAIError as error:
        return error_response(error.code, error.message, error.status)


@ai_blueprint.post("/project-research-form/generate")
@require_role("admin", "project_lead", "fde_engineer")
def project_research_form_generate_route():
    try:
        data = generate_project_research_form(
            actor=g.current_user,
            payload=request.get_json(silent=True),
        )
        return jsonify({"data": data, "error": None})
    except ResearchFormAIError as error:
        return error_response(error.code, error.message, error.status)


@ai_blueprint.post("/project-ai-opportunities/adjust")
@require_role("admin", "project_lead", "fde_engineer")
def project_ai_opportunity_adjust_route():
    from .opportunity_adjustment import adjust_opportunity
    try:
        return jsonify({"data": adjust_opportunity(actor=g.current_user, payload=request.get_json(silent=True)), "error": None})
    except AIOpportunityDiscoveryError as error:
        return error_response(error.code, error.message, error.status)


@ai_blueprint.post("/project-ai-opportunities/discover")
@require_role("admin", "project_lead", "fde_engineer")
def project_ai_opportunity_discover_route():
    try:
        data = discover_ai_opportunities(actor=g.current_user, payload=request.get_json(silent=True))
        return jsonify({"data": data, "error": None})
    except AIOpportunityDiscoveryError as error:
        return error_response(error.code, error.message, error.status)


def _error(error: IndustryTemplateAIError):
    return error_response(error.code, error.message, error.status, error.details)
