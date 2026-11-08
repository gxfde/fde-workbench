"""商业化 G1 读面路由：本人/管理员查看权益与对外编号推导（只读零写入）。

- 读权限：本人或 admin；他人 403（权益属个人敏感面）。
- 不进 api_catalog：商业治理面，AI 不可调用（dispatch admin/本体治理同款边界）。
- 写面在 ``admin_routes.py``（admin + 密码确认 + 审计事件）。
"""

from __future__ import annotations

from flask import Blueprint, g, jsonify

from fde_api.auth.decorators import require_auth
from fde_api.commercial.quota_service import (
    confirm_diagnosis,
    free_diagnosis_profile,
    get_quota_view,
    start_diagnosis,
)
from fde_api.commercial.service import CommercialServiceError, get_entitlement_for_view
from fde_api.extensions import db

commercial_blueprint = Blueprint(
    "commercial", __name__, url_prefix="/api/v1/commercial"
)


@commercial_blueprint.errorhandler(CommercialServiceError)
def _handle_service_error(error: CommercialServiceError):
    return (
        jsonify(
            {
                "data": None,
                "error": {
                    "code": error.code,
                    "message": error.message,
                    "details": None,
                },
            }
        ),
        error.status,
    )


@commercial_blueprint.get("/entitlements/<user_id>")
@require_auth
def get_entitlement_route(user_id: str):
    with db.session() as session:
        data = get_entitlement_for_view(session, actor=g.current_user, user_id=user_id)
        return jsonify({"data": data, "error": None})


# ── 商业化 G2：企业免费额度（读面：绑定账号本人或 admin）──


@commercial_blueprint.get("/enterprise-quota/<subject_key>")
@require_auth
def get_quota_route(subject_key: str):
    with db.session() as session:
        data = get_quota_view(session, actor=g.current_user, subject_key_raw=subject_key)
        return jsonify({"data": data, "error": None})


@commercial_blueprint.post("/enterprise-quota/<subject_key>/start")
@require_auth
def start_quota_route(subject_key: str):
    with db.session() as session, session.begin():
        data = start_diagnosis(session, actor=g.current_user, subject_key_raw=subject_key)
        return jsonify({"data": data, "error": None})


@commercial_blueprint.post("/enterprise-quota/<subject_key>/confirm")
@require_auth
def confirm_quota_route(subject_key: str):
    with db.session() as session, session.begin():
        data = confirm_diagnosis(session, actor=g.current_user, subject_key_raw=subject_key)
        return jsonify({"data": data, "error": None})


@commercial_blueprint.get("/free-diagnosis-profile")
@require_auth
def free_diagnosis_profile_route():
    return jsonify({"data": free_diagnosis_profile(), "error": None})
