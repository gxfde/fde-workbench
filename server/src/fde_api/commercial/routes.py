"""商业化 G1 读面路由：本人/管理员查看权益与对外编号推导（只读零写入）。

- 读权限：本人或 admin；他人 403（权益属个人敏感面）。
- 不进 api_catalog：商业治理面，AI 不可调用（dispatch admin/本体治理同款边界）。
- 写面在 ``admin_routes.py``（admin + 密码确认 + 审计事件）。
"""

from __future__ import annotations

from flask import Blueprint, g, jsonify, request

from fde_api.auth.decorators import require_auth
from fde_api.commercial.billing_service import (
    elect_deduction_method,
    get_active_election,
    list_certification_records,
    list_packages,
    serialize_election,
)
from fde_api.commercial.ledger_service import (
    get_revenue_entry,
    list_revenue_entries,
    reconcile_revenue,
)
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


# ── 商业化 G3：收入科目层读面 + 扣费方式自证面 ──


@commercial_blueprint.get("/packages")
@require_auth
def packages_route():
    """套餐目录（**不含价目**——价格走 quotes/payments 收款台账）。"""
    return jsonify({"data": {"packages": list_packages()}, "error": None})


@commercial_blueprint.get("/revenue-ledger")
@require_auth
def list_revenue_ledger_route():
    """科目列表（本人只见自己的；admin 见全量）——「三类科目分别可查」。"""
    with db.session() as session:
        data = list_revenue_entries(
            session,
            actor=g.current_user,
            subject_type=request.args.get("subject_type"),
            subject_user_id=request.args.get("subject_user_id"),
            status=request.args.get("status"),
            limit=request.args.get("limit", 100),
        )
        return jsonify({"data": data, "error": None})


@commercial_blueprint.get("/revenue-ledger/reconciliation")
@require_auth
def reconcile_revenue_route():
    """科目对账汇总（按科目×名目 + 与收款台账差异计数）。"""
    with db.session() as session:
        data = reconcile_revenue(
            session,
            actor=g.current_user,
            subject_type=request.args.get("subject_type"),
            subject_user_id=request.args.get("subject_user_id"),
        )
        return jsonify({"data": data, "error": None})


@commercial_blueprint.get("/revenue-ledger/<entry_id>")
@require_auth
def get_revenue_ledger_route(entry_id: str):
    with db.session() as session:
        data = get_revenue_entry(session, actor=g.current_user, entry_id=entry_id)
        return jsonify({"data": data, "error": None})


@commercial_blueprint.get("/deduction-election")
@require_auth
def get_deduction_election_route():
    """本人扣费方式选定状态（未选定 ⇒ 首单扣费闸不放行）。"""
    with db.session() as session:
        row = get_active_election(session, g.current_user.id)
        return jsonify(
            {
                "data": {
                    "elected": row is not None,
                    "election": serialize_election(row) if row is not None else None,
                },
                "error": None,
            }
        )


@commercial_blueprint.post("/deduction-election")
@require_auth
def elect_deduction_route():
    """本人**书面选定**扣费方式（当事人自证动作，ADR-007 §2.4）。

    他人/admin 不得代选定——本路由不接受 user_id 参数，actor 即被计费人。
    """
    payload = request.get_json(silent=True)
    payload = payload if isinstance(payload, dict) else {}
    with db.session() as session, session.begin():
        data = elect_deduction_method(
            session,
            actor=g.current_user,
            method=payload.get("method"),
            source_uri=payload.get("source_uri"),
            content_hash=payload.get("content_hash"),
        )
        return jsonify({"data": data, "error": None})


@commercial_blueprint.get("/certification-records/<user_id>")
@require_auth
def certification_records_route(user_id: str):
    """认证记录读面（本人或 admin）——认证挂模拟考核的可见入口。"""
    with db.session() as session:
        data = list_certification_records(
            session, actor=g.current_user, user_id=user_id
        )
        return jsonify({"data": data, "error": None})
