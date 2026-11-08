"""商业化 G1 写面路由：admin + 密码确认的高风险权益写原语（六动作）。

- admin 门：服务层 ``_require_admin`` 判 ROLE_ADMIN，非 admin 403。
- 人工确认：每条写路由必填 ``confirm_password``（当前账号密码）——权益变更
  默认需人工确认（ADR-002 §2.5；交付智能化等级 L2+ 下「AI 出初稿、人审核
  后生效」形态：本面是人工审核通道，AI 无直写入口）。
- 留痕：服务层逐动作落 ``operation_events``（Actor/前后状态/来源/请求 ID）。
- 不进 api_catalog：商业治理面，AI 不可调用。
"""

from __future__ import annotations

from flask import Blueprint, g, jsonify, request

from fde_api.auth.decorators import require_auth
from fde_api.commercial.quota_service import complete_diagnosis, grant_or_get_quota
from fde_api.commercial.service import (
    CommercialServiceError,
    activate_seat,
    add_training_entitlement,
    revoke_training_entitlement,
    set_certification,
    set_commercial_role,
    set_delivery_eligibility,
)
from fde_api.extensions import db

admin_commercial_blueprint = Blueprint(
    "admin_commercial", __name__, url_prefix="/api/v1/admin/commercial"
)


@admin_commercial_blueprint.errorhandler(CommercialServiceError)
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


def _json_payload() -> dict:
    payload = request.get_json(silent=True)
    return payload if isinstance(payload, dict) else {}


@admin_commercial_blueprint.post("/users/<user_id>/role")
@require_auth
def set_role_route(user_id: str):
    payload = _json_payload()
    with db.session() as session, session.begin():
        data = set_commercial_role(
            session,
            actor=g.current_user,
            user_id=user_id,
            role=payload.get("role"),
            confirm_password=payload.get("confirm_password"),
        )
        return jsonify({"data": data, "error": None})


@admin_commercial_blueprint.post("/users/<user_id>/training")
@require_auth
def add_training_route(user_id: str):
    payload = _json_payload()
    with db.session() as session, session.begin():
        data = add_training_entitlement(
            session,
            actor=g.current_user,
            user_id=user_id,
            item_type=payload.get("item_type"),
            valid_from=payload.get("valid_from"),
            valid_until=payload.get("valid_until"),
            note=payload.get("note"),
            confirm_password=payload.get("confirm_password"),
        )
        return jsonify({"data": data, "error": None})


@admin_commercial_blueprint.post("/users/<user_id>/training/<training_id>/revoke")
@require_auth
def revoke_training_route(user_id: str, training_id: str):
    payload = _json_payload()
    with db.session() as session, session.begin():
        data = revoke_training_entitlement(
            session,
            actor=g.current_user,
            user_id=user_id,
            training_id=training_id,
            confirm_password=payload.get("confirm_password"),
        )
        return jsonify({"data": data, "error": None})


@admin_commercial_blueprint.post("/users/<user_id>/seat-activation")
@require_auth
def activate_seat_route(user_id: str):
    payload = _json_payload()
    with db.session() as session, session.begin():
        data = activate_seat(
            session,
            actor=g.current_user,
            user_id=user_id,
            seat_source=payload.get("seat_source"),
            expires_at=payload.get("expires_at"),
            confirm_password=payload.get("confirm_password"),
        )
        return jsonify({"data": data, "error": None})


@admin_commercial_blueprint.post("/users/<user_id>/certification")
@require_auth
def set_certification_route(user_id: str):
    payload = _json_payload()
    with db.session() as session, session.begin():
        data = set_certification(
            session,
            actor=g.current_user,
            user_id=user_id,
            certified=payload.get("certified"),
            source=payload.get("source"),
            confirm_password=payload.get("confirm_password"),
        )
        return jsonify({"data": data, "error": None})


@admin_commercial_blueprint.post("/users/<user_id>/delivery-eligibility")
@require_auth
def set_delivery_eligibility_route(user_id: str):
    payload = _json_payload()
    with db.session() as session, session.begin():
        data = set_delivery_eligibility(
            session,
            actor=g.current_user,
            user_id=user_id,
            eligibility=payload.get("eligibility"),
            confirm_password=payload.get("confirm_password"),
        )
        return jsonify({"data": data, "error": None})



# ── 商业化 G2：企业免费额度（治理写：授予/完成=admin+密码确认，ADR-007）──


@admin_commercial_blueprint.post("/enterprise-quota/grant")
@require_auth
def grant_quota_route():
    payload = _json_payload()
    with db.session() as session, session.begin():
        data = grant_or_get_quota(
            session,
            actor=g.current_user,
            subject_key_raw=payload.get("subject_key"),
            display_name=payload.get("display_name"),
            confirm_password=payload.get("confirm_password"),
        )
        return jsonify({"data": data, "error": None})


@admin_commercial_blueprint.post("/enterprise-quota/<subject_key>/complete")
@require_auth
def complete_quota_route(subject_key: str):
    payload = _json_payload()
    with db.session() as session, session.begin():
        data = complete_diagnosis(
            session,
            actor=g.current_user,
            subject_key_raw=subject_key,
            deliverables=payload.get("deliverables"),
            confirm_password=payload.get("confirm_password"),
        )
        return jsonify({"data": data, "error": None})
