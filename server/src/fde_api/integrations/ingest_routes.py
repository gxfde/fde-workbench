"""本体候选直提路由 + 评审包 HTML 路由（V3.3 WP4④ / D8 / D17）。

蓝图**无条件**进 ``_BLUEPRINT_SPECS``（蓝图注册表单一真身机器闸 P2-5）；关闭态判定
收敛在 ``integrations.service.ensure_enabled()``（D12），并由蓝图级 ``before_request``
预闸**先于鉴权**执行（D13：否则未鉴权探针先撞 401＝面存在，与「面不存在」不可区分
的要求相悖）。404 信封与全局「路径不存在」逐字节同形。
"""

from __future__ import annotations

from flask import Blueprint, Response, g, jsonify, request

from fde_api.auth.decorators import require_auth
from fde_api.errors import error_response
from fde_api.integrations.ingest_service import submit_discovery_candidates
from fde_api.integrations.review_package import render_review_package
from fde_api.integrations.service import BindingError, ensure_enabled

ontology_ingest_blueprint = Blueprint(
    "ontology_ingest", __name__, url_prefix="/api/v1/projects"
)


def _binding_error(exc: BindingError):
    return error_response(exc.code, exc.message, exc.status)


def _json_object() -> dict[str, object]:
    payload = request.get_json(silent=True)
    return payload if isinstance(payload, dict) else {}


@ontology_ingest_blueprint.before_request
def _gate_disabled_surface():
    """D13：关闭态判定先于鉴权（未鉴权探针不得据此反推该面存在）。"""
    try:
        ensure_enabled()
    except BindingError as exc:
        return _binding_error(exc)
    return None


@ontology_ingest_blueprint.post("/<project_id>/ontology-candidates")
@require_auth
def submit_candidates_route(project_id: str):
    payload = _json_object()
    ontology_id = str(payload.get("ontology_id", "") or "")
    extraction_id = str(payload.get("extraction_id", "") or "")
    if not ontology_id or not extraction_id:
        return error_response(
            "invalid_request", "ontology_id 与 extraction_id 必填。", 400
        )
    try:
        result = submit_discovery_candidates(
            g.current_user,
            project_id,
            ontology_id=ontology_id,
            extraction_id=extraction_id,
        )
    except BindingError as exc:
        return _binding_error(exc)
    return jsonify({"data": result, "error": None}), 201


@ontology_ingest_blueprint.get("/<project_id>/change-sets/<change_set_id>/review-package")
@require_auth
def review_package_route(project_id: str, change_set_id: str):
    try:
        html = render_review_package(g.current_user, project_id, change_set_id)
    except BindingError as exc:
        return _binding_error(exc)
    return Response(html, mimetype="text/html")
