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
from fde_api.commercial.attribution_service import (
    assign_presales,
    configure_rule,
    confirm_attribution,
    confirm_enterprise_demand,
    list_rules,
    mark_disputed,
    record_customer_choice,
    record_match,
    record_settlement,
    reassign_attribution,
    renew_protection,
    serialize_rule,
    set_protection,
)
from fde_api.commercial.billing_service import (
    charge_first_order_seat_fee,
    record_certification_evaluation,
)
from fde_api.commercial.ledger_service import (
    configure_fee_config,
    list_fee_configs,
    list_split_rules,
    record_revenue_entry,
    register_split_rule,
    serialize_fee_config,
    serialize_split_rule,
)
from fde_api.commercial.quota_service import complete_diagnosis, grant_or_get_quota
from fde_api.commercial.regional_service import (
    get_or_create_gate,
    open_sale_gate,
    promote_partner,
    record_service_settlement,
    register_gate_condition,
    serialize_gate,
)
from fde_api.commercial.org_budget_service import (
    OrgBudgetServiceError,
    get_org_ai_budget,
    set_org_ai_budget,
)
from fde_api.commercial.enterprise_service import (
    record_advisor_note,
    record_triage_decision,
)
from fde_api.commercial.service import (
    CommercialServiceError,
    activate_seat,
    add_training_entitlement,
    revoke_training_entitlement,
    set_certification,
    set_commercial_role,
    set_delivery_eligibility,
)
from fde_api.commercial.readiness_service import commercial_readiness
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


@admin_commercial_blueprint.errorhandler(OrgBudgetServiceError)
def _handle_org_budget_error(error: OrgBudgetServiceError):
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


# ── M4 批次 B：企业 org AI 月度预算治理面（admin+密码双闸；治理面不进 api_catalog）──


@admin_commercial_blueprint.get("/orgs/<org_id>/ai-budget")
@require_auth
def get_org_ai_budget_route(org_id: str):
    with db.session() as session:
        data = get_org_ai_budget(session, actor=g.current_user, org_id=org_id)
        return jsonify({"data": data, "error": None})


@admin_commercial_blueprint.put("/orgs/<org_id>/ai-budget")
@require_auth
def set_org_ai_budget_route(org_id: str):
    payload = _json_payload()
    with db.session() as session, session.begin():
        data = set_org_ai_budget(
            session,
            actor=g.current_user,
            org_id=org_id,
            budget=payload.get("budget"),
            confirm_password=payload.get("confirm_password"),
        )
        return jsonify({"data": data, "error": None})




def _parse_signed_at(value: object):
    """ISO 8601 → aware datetime（无效即 None，由服务层 400）。"""
    from datetime import datetime

    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None

def _json_payload() -> dict:
    payload = request.get_json(silent=True)
    return payload if isinstance(payload, dict) else {}


def _require_platform_operator_read() -> None:
    """QR-067（BLOCKED §5 #3A）：商业治理配置读面只认平台管理操作者（M3b ①-a 单一判定）。"""
    from fde_api.control.access import is_platform_operator

    if not is_platform_operator(g.current_user):
        raise CommercialServiceError(
            "commercial_admin_required", "商业化治理面仅平台管理操作者可用。", 403
        )


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
            ai_draft_adoption=payload.get("ai_draft_adoption"),
        )
        return jsonify({"data": data, "error": None})


# ── 商业化 G3：收入科目层与订阅席位计费（治理写：admin + 密码确认，ADR-007）──


@admin_commercial_blueprint.get("/fee-configs")
@require_auth
def list_fee_configs_route():
    """费用/周期配置位读面（平台管理操作者）——本期全部 unset（缺省不可用）。"""
    _require_platform_operator_read()
    with db.session() as session:
        rows = list_fee_configs(session)
        return jsonify(
            {
                "data": {"fee_configs": [serialize_fee_config(row) for row in rows]},
                "error": None,
            }
        )


@admin_commercial_blueprint.post("/fee-configs/<key>")
@require_auth
def configure_fee_config_route(key: str):
    payload = _json_payload()
    with db.session() as session, session.begin():
        data = configure_fee_config(
            session,
            actor=g.current_user,
            key=key,
            value=payload.get("value"),
            source_uri=payload.get("source_uri"),
            content_hash=payload.get("content_hash"),
            confirm_password=payload.get("confirm_password"),
        )
        return jsonify({"data": data, "error": None})


@admin_commercial_blueprint.get("/split-rules")
@require_auth
def list_split_rules_route():
    """分成比例配置结构读面（平台管理操作者）——本期零行（比例不定数）。"""
    _require_platform_operator_read()
    with db.session() as session:
        rows = list_split_rules(session)
        return jsonify(
            {
                "data": {"split_rules": [serialize_split_rule(row) for row in rows]},
                "error": None,
            }
        )


@admin_commercial_blueprint.post("/split-rules")
@require_auth
def register_split_rule_route():
    payload = _json_payload()
    with db.session() as session, session.begin():
        data = register_split_rule(
            session,
            actor=g.current_user,
            role_code=payload.get("role_code"),
            project_type=payload.get("project_type"),
            ratio_bp=payload.get("ratio_bp"),
            source_uri=payload.get("source_uri"),
            content_hash=payload.get("content_hash"),
            confirm_password=payload.get("confirm_password"),
        )
        return jsonify({"data": data, "error": None})


@admin_commercial_blueprint.post("/revenue-ledger")
@require_auth
def record_revenue_route():
    """记一笔收入科目（高风险写：admin + 密码确认）。"""
    payload = _json_payload()
    with db.session() as session, session.begin():
        data = record_revenue_entry(
            session,
            actor=g.current_user,
            subject_type=payload.get("subject_type"),
            line_item=payload.get("line_item"),
            amount=payload.get("amount"),
            fee_key=payload.get("fee_key"),
            subject_user_id=payload.get("subject_user_id"),
            payee_user_id=payload.get("payee_user_id"),
            quote_id=payload.get("quote_id"),
            payment_id=payload.get("payment_id"),
            contract_id=payload.get("contract_id"),
            delivery_settlement_id=payload.get("delivery_settlement_id"),
            delivery_package_id=payload.get("delivery_package_id"),
            training_entitlement_id=payload.get("training_entitlement_id"),
            package_code=payload.get("package_code"),
            seat_source=payload.get("seat_source"),
            role_code=payload.get("role_code"),
            project_type=payload.get("project_type"),
            source_uri=payload.get("source_uri"),
            content_hash=payload.get("content_hash"),
            confirm_password=payload.get("confirm_password"),
        )
        return jsonify({"data": data, "error": None})


@admin_commercial_blueprint.post("/first-order-fee")
@require_auth
def charge_first_order_fee_route():
    """首单扣费闸（高风险写：admin + 密码确认）。

    闸门在服务层：验收前不触发、未书面选定扣费方式不得扣费、已购含席位套餐
    不重复收（任务书 §7）。
    """
    payload = _json_payload()
    with db.session() as session, session.begin():
        data = charge_first_order_seat_fee(
            session,
            actor=g.current_user,
            user_id=payload.get("user_id"),
            package_id=payload.get("package_id"),
            confirm_password=payload.get("confirm_password"),
        )
        return jsonify({"data": data, "error": None})


@admin_commercial_blueprint.post("/certification-records")
@require_auth
def record_certification_route():
    """挂模拟考核结果为认证依据（高风险写：admin + 密码确认）。"""
    payload = _json_payload()
    with db.session() as session, session.begin():
        data = record_certification_evaluation(
            session,
            actor=g.current_user,
            user_id=payload.get("user_id"),
            simulation_evaluation_id=payload.get("simulation_evaluation_id"),
            source_uri=payload.get("source_uri"),
            content_hash=payload.get("content_hash"),
            confirm_password=payload.get("confirm_password"),
        )
        return jsonify({"data": data, "error": None})


# ── 商业化 G4：商机归属与渠道保护（治理写：admin + 密码确认，ADR-007）──


@admin_commercial_blueprint.get("/opportunity-rules")
@require_auth
def list_opportunity_rules_route():
    """规则位读面（平台管理操作者）——本期五个槽位**全部 unset**（规则数值未定数）。"""
    _require_platform_operator_read()
    with db.session() as session:
        rows = list_rules(session)
        return jsonify(
            {
                "data": {"rules": [serialize_rule(row) for row in rows]},
                "error": None,
            }
        )


@admin_commercial_blueprint.post("/opportunity-rules/<key>")
@require_auth
def configure_opportunity_rule_route(key: str):
    """配置/清空规则位（admin + 密码确认；书面依据指针 + sha256 指纹）。"""
    payload = _json_payload()
    with db.session() as session, session.begin():
        data = configure_rule(
            session,
            actor=g.current_user,
            key=key,
            value=payload.get("value"),
            source_uri=payload.get("source_uri"),
            content_hash=payload.get("content_hash"),
            confirm_password=payload.get("confirm_password"),
        )
        return jsonify({"data": data, "error": None})


@admin_commercial_blueprint.post("/opportunities/<opportunity_id>/enterprise-confirm")
@require_auth
def confirm_enterprise_demand_route(opportunity_id: str):
    """② 企业确认有真实需求（平台代录企业书面答复：admin + 密码确认）。"""
    payload = _json_payload()
    with db.session() as session, session.begin():
        data = confirm_enterprise_demand(
            session,
            actor=g.current_user,
            opportunity_id=opportunity_id,
            confirmation_uri=payload.get("confirmation_uri"),
            confirmation_hash=payload.get("confirmation_hash"),
            confirm_password=payload.get("confirm_password"),
        )
        return jsonify({"data": data, "error": None})


@admin_commercial_blueprint.post("/opportunities/<opportunity_id>/attribution")
@require_auth
def confirm_attribution_route(opportunity_id: str):
    """③ 平台确认商机归属（**关键流转**：admin + 密码确认）。"""
    payload = _json_payload()
    with db.session() as session, session.begin():
        data = confirm_attribution(
            session,
            actor=g.current_user,
            opportunity_id=opportunity_id,
            owner_user_id=payload.get("owner_user_id"),
            attribution_uri=payload.get("attribution_uri"),
            attribution_hash=payload.get("attribution_hash"),
            confirm_password=payload.get("confirm_password"),
        )
        return jsonify({"data": data, "error": None})


@admin_commercial_blueprint.post("/opportunities/<opportunity_id>/attribution/reassign")
@require_auth
def reassign_attribution_route(opportunity_id: str):
    """改派归属（**判据规则未成文 ⇒ 不可用**，409 ``rule_not_configured``）。"""
    payload = _json_payload()
    with db.session() as session, session.begin():
        data = reassign_attribution(
            session,
            actor=g.current_user,
            opportunity_id=opportunity_id,
            owner_user_id=payload.get("owner_user_id"),
            reason_uri=payload.get("reason_uri"),
            reason_hash=payload.get("reason_hash"),
            confirm_password=payload.get("confirm_password"),
        )
        return jsonify({"data": data, "error": None})


@admin_commercial_blueprint.post("/opportunities/<opportunity_id>/protection")
@require_auth
def set_protection_route(opportunity_id: str):
    """④ 设定保护期（长度取配置位；未配置 ⇒ 409 ``rule_not_configured``）。"""
    payload = _json_payload()
    with db.session() as session, session.begin():
        data = set_protection(
            session,
            actor=g.current_user,
            opportunity_id=opportunity_id,
            confirm_password=payload.get("confirm_password"),
        )
        return jsonify({"data": data, "error": None})


@admin_commercial_blueprint.post("/opportunities/<opportunity_id>/protection/renew")
@require_auth
def renew_protection_route(opportunity_id: str):
    """续期保护期（**续期条件规则未成文 ⇒ 不可用**）。"""
    payload = _json_payload()
    with db.session() as session, session.begin():
        data = renew_protection(
            session,
            actor=g.current_user,
            opportunity_id=opportunity_id,
            confirm_password=payload.get("confirm_password"),
        )
        return jsonify({"data": data, "error": None})


@admin_commercial_blueprint.post("/opportunities/<opportunity_id>/presales")
@require_auth
def assign_presales_route(opportunity_id: str):
    """⑤ 创业者负责售前与客户关系（默认＝归属人，可显式改派）。"""
    payload = _json_payload()
    with db.session() as session, session.begin():
        data = assign_presales(
            session,
            actor=g.current_user,
            opportunity_id=opportunity_id,
            owner_user_id=payload.get("owner_user_id"),
            confirm_password=payload.get("confirm_password"),
        )
        return jsonify({"data": data, "error": None})


@admin_commercial_blueprint.post("/opportunities/<opportunity_id>/match")
@require_auth
def record_match_route(opportunity_id: str):
    """⑥ 平台撮合交付者（引用既有 dispatch 交付包）。"""
    payload = _json_payload()
    with db.session() as session, session.begin():
        data = record_match(
            session,
            actor=g.current_user,
            opportunity_id=opportunity_id,
            delivery_package_id=payload.get("delivery_package_id"),
            confirm_password=payload.get("confirm_password"),
        )
        return jsonify({"data": data, "error": None})


@admin_commercial_blueprint.post("/opportunities/<opportunity_id>/customer-choice")
@require_auth
def record_customer_choice_route(opportunity_id: str):
    """客户自主选择交付包（**选择权规则未成文 ⇒ 不可用**；不改归属）。"""
    payload = _json_payload()
    with db.session() as session, session.begin():
        data = record_customer_choice(
            session,
            actor=g.current_user,
            opportunity_id=opportunity_id,
            delivery_package_id=payload.get("delivery_package_id"),
            confirm_password=payload.get("confirm_password"),
        )
        return jsonify({"data": data, "error": None})


@admin_commercial_blueprint.post("/opportunities/<opportunity_id>/settlement")
@require_auth
def record_settlement_route(opportunity_id: str):
    """⑦ 按既定分成规则结算（引用 G3 科目层的 project_share 行）。"""
    payload = _json_payload()
    with db.session() as session, session.begin():
        data = record_settlement(
            session,
            actor=g.current_user,
            opportunity_id=opportunity_id,
            ledger_entry_id=payload.get("ledger_entry_id"),
            confirm_password=payload.get("confirm_password"),
        )
        return jsonify({"data": data, "error": None})


@admin_commercial_blueprint.post("/opportunities/<opportunity_id>/dispute")
@require_auth
def mark_disputed_route(opportunity_id: str):
    """发起争议（**争议处理机制未成文 ⇒ 不可用**）。"""
    payload = _json_payload()
    with db.session() as session, session.begin():
        data = mark_disputed(
            session,
            actor=g.current_user,
            opportunity_id=opportunity_id,
            dispute_uri=payload.get("dispute_uri"),
            dispute_hash=payload.get("dispute_hash"),
            confirm_password=payload.get("confirm_password"),
        )
        return jsonify({"data": data, "error": None})



@admin_commercial_blueprint.get("/readiness")
@require_auth
def commercial_readiness_route():
    """商业化就绪度汇总读面（admin，只读）——配置缺口 ＋ 售卖闸条件登记态。

    **不落任何数值**：只报状态（unset/configured）与键名；证据只出指针。
    治理面不进 api_catalog（与既有 commercial admin 面同款）。
    """
    with db.session() as session:
        data = commercial_readiness(session, actor=g.current_user)
        return jsonify({"data": data, "error": None})


@admin_commercial_blueprint.get("/regional-sale-gate")
@require_auth
def get_regional_sale_gate_route():
    """售卖开关读面（平台管理操作者：状态 + 四项合规条件登记态，只出指针）。"""
    _require_platform_operator_read()
    with db.session() as session:
        return jsonify({"data": serialize_gate(get_or_create_gate(session)), "error": None})


@admin_commercial_blueprint.post("/regional-sale-gate/conditions/<key>")
@require_auth
def register_regional_gate_condition_route(key: str):
    """登记一项合规条件的签署证据（admin+密码；**登记 ≠ 开启**）。"""
    payload = _json_payload()
    with db.session() as session, session.begin():
        data = register_gate_condition(
            session,
            actor=g.current_user,
            key=key,
            source_uri=payload.get("source_uri"),
            content_hash=payload.get("content_hash"),
            signed_at=_parse_signed_at(payload.get("signed_at")),
            confirm_password=payload.get("confirm_password"),
        )
        return jsonify({"data": data, "error": None})


@admin_commercial_blueprint.post("/regional-sale-gate/open")
@require_auth
def open_regional_sale_gate_route():
    """开启售卖开关（**关键流转**：admin+密码；四项合规条件证据齐备才可）。"""
    payload = _json_payload()
    with db.session() as session, session.begin():
        data = open_sale_gate(
            session,
            actor=g.current_user,
            confirm_password=payload.get("confirm_password"),
        )
        return jsonify({"data": data, "error": None})


@admin_commercial_blueprint.post("/regional-partners/<partner_id>/promote")
@require_auth
def promote_regional_partner_route(partner_id: str):
    """区域伙伴阶段升级（admin+密码+书面依据；**正式档必先过售卖闸**）。"""
    payload = _json_payload()
    with db.session() as session, session.begin():
        data = promote_partner(
            session,
            actor=g.current_user,
            partner_id=partner_id,
            to_stage=payload.get("to_stage"),
            tier_code=payload.get("tier_code"),
            exclusive_territory=payload.get("exclusive_territory"),
            source_uri=payload.get("source_uri"),
            content_hash=payload.get("content_hash"),
            confirm_password=payload.get("confirm_password"),
        )
        return jsonify({"data": data, "error": None})


@admin_commercial_blueprint.post("/regional-partners/<partner_id>/settlements")
@require_auth
def record_regional_settlement_route(partner_id: str):
    """城市服务伙伴按项目结算（一单一结；admin+密码；引用 G3 科目行）。"""
    payload = _json_payload()
    with db.session() as session, session.begin():
        data = record_service_settlement(
            session,
            actor=g.current_user,
            partner_id=partner_id,
            project_id=payload.get("project_id"),
            ledger_entry_id=payload.get("ledger_entry_id"),
            note=payload.get("note"),
            confirm_password=payload.get("confirm_password"),
        )
        return jsonify({"data": data, "error": None})


# ── 商业化 G6：企业空间治理写面（admin+密码双闸；ADR-010；不进 api_catalog）──


@admin_commercial_blueprint.post("/enterprise-spaces/<subject_key>/triage-decisions")
@require_auth
def record_triage_decision_route(subject_key: str):
    """三档分流人工判定（交付咨询环节；admin+密码；诊断完成后才可判定）。"""
    payload = _json_payload()
    with db.session() as session, session.begin():
        data = record_triage_decision(
            session,
            actor=g.current_user,
            subject_key_raw=subject_key,
            tier=payload.get("tier"),
            rationale=payload.get("rationale"),
            basis_uri=payload.get("basis_uri"),
            basis_sha256=payload.get("basis_sha256"),
            request_id=payload.get("request_id"),
            confirm_password=payload.get("confirm_password"),
        )
        return jsonify({"data": data, "error": None})


@admin_commercial_blueprint.post(
    "/enterprise-spaces/<subject_key>/paid-option-choices/<choice_id>/advisor-note"
)
@require_auth
def record_advisor_note_route(subject_key: str, choice_id: str):
    """顾问跟进注记（admin+密码；只能补注记三元组，不能动选择本体）。"""
    payload = _json_payload()
    with db.session() as session, session.begin():
        data = record_advisor_note(
            session,
            actor=g.current_user,
            subject_key_raw=subject_key,
            choice_id=choice_id,
            note=payload.get("note"),
            confirm_password=payload.get("confirm_password"),
            request_id=payload.get("request_id"),
        )
        return jsonify({"data": data, "error": None})
