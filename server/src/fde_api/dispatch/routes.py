"""dispatch 蓝图：交付包读/发布/撤回/接单（设计 §8.6/§9.2，P0-1/P0-2）。

§9.2 纪律③：每个读入口先过 require_package_access（无授权 404，不泄露
包存在性）；管理动作（建/发/撤）限平台侧。响应体只走白名单 schema
（access.serialize_package_whitelist），金额字段唯一例外=交付方席位份额。
"""

from __future__ import annotations

from decimal import Decimal

from flask import Blueprint, g, jsonify, request
from sqlalchemy import select

from fde_api.auth.decorators import require_auth
from fde_api.dispatch.access import (
    has_package_access,
    list_accessible_package_ids,
    require_package_access,
    serialize_package_whitelist,
)
from fde_api.dispatch.agent_assisted import declare_agent_assisted
from fde_api.dispatch.disputes import open_dispute, resolve_dispute
from fde_api.dispatch.errors import DispatchServiceError
from fde_api.dispatch.models import DeliveryPackage
from fde_api.dispatch.offer_service import (
    accept_offer_and_handover,
    claim_package,
    create_assign_offers,
    decline_offer,
)
from fde_api.dispatch.matching import match_package, override_required_level
from fde_api.dispatch.packages import (
    accept_package,
    create_package,
    publish_package,
    transition_package,
)
from fde_api.errors import error_response
from fde_api.extensions import db
from fde_api.solutions.models import ProjectSolution
from fde_api.workbench.models import Project

blueprint = Blueprint("dispatch", __name__, url_prefix="/api/v1/dispatch")

_PLATFORM_ROLES = ("admin", "project_lead")


def _dispatch_error(error: DispatchServiceError):
    return error_response(error.code, error.message, error.status)


def _json_body() -> dict | None:
    payload = request.get_json(silent=True)
    return payload if isinstance(payload, dict) else None


def _whitelist_payload(session, package: DeliveryPackage) -> dict:
    solution = session.get(ProjectSolution, package.solution_id)
    project = session.get(Project, package.project_id)
    return serialize_package_whitelist(package, solution=solution, project=project)


@blueprint.get("/packages")
@require_auth
def list_packages_route():
    with db.session() as session:
        ids = list_accessible_package_ids(session, user=g.current_user)
        packages = (
            session.scalars(
                select(DeliveryPackage).where(DeliveryPackage.id.in_(ids))
            ).all()
            if ids
            else []
        )
        return jsonify(
            {
                "data": [_whitelist_payload(session, package) for package in packages],
                "error": None,
            }
        )


@blueprint.get("/packages/<package_id>")
@require_auth
def get_package_route(package_id: str):
    with db.session() as session:
        try:
            package = require_package_access(
                session, user=g.current_user, package_id=package_id
            )
        except DispatchServiceError as error:
            return _dispatch_error(error)
        return jsonify({"data": _whitelist_payload(session, package), "error": None})


@blueprint.post("/packages")
@require_auth
def create_package_route():
    payload = _json_body()
    if not payload or not {"solution_id", "quote_id"} <= set(payload):
        return error_response("invalid_request", "solution_id 与 quote_id 必填。", 400)
    onsite_visits = payload.get("onsite_visits")
    if onsite_visits is not None and (
        type(onsite_visits) is not int or onsite_visits < 0
    ):
        return error_response("invalid_request", "onsite_visits 必须是非负整数。", 400)
    session = db.session()
    try:
        with session.begin():
            package = create_package(
                session,
                actor=g.current_user,
                solution_id=str(payload["solution_id"]),
                quote_id=str(payload["quote_id"]),
                dispatch_mode=str(payload.get("dispatch_mode") or "assign"),
                onsite_visits=onsite_visits,
            )
            result = _whitelist_payload(session, package)
        return jsonify({"data": result, "error": None}), 201
    except DispatchServiceError as error:
        return _dispatch_error(error)
    finally:
        session.close()


@blueprint.post("/packages/<package_id>/publish")
@require_auth
def publish_package_route(package_id: str):
    payload = _json_body() or {}
    candidates_raw = payload.get("candidate_user_ids") or []
    if not isinstance(candidates_raw, list) or not all(
        isinstance(item, str) for item in candidates_raw
    ):
        return error_response(
            "invalid_request", "candidate_user_ids 必须是字符串数组。", 400
        )
    difficulty = payload.get("difficulty")
    if difficulty is not None and difficulty not in ("low", "medium", "high"):
        return error_response(
            "invalid_request", "difficulty 必须是 low/medium/high。", 400
        )
    session = db.session()
    try:
        with session.begin():
            package = publish_package(
                session,
                actor=g.current_user,
                package_id=package_id,
                candidate_user_ids=tuple(candidates_raw),
                difficulty=difficulty,
            )
            result = _whitelist_payload(session, package)
        return jsonify({"data": result, "error": None})
    except DispatchServiceError as error:
        return _dispatch_error(error)
    finally:
        session.close()


@blueprint.post("/packages/<package_id>/agent-assisted")
@require_auth
def declare_agent_assisted_route(package_id: str):
    """D2 裁决三（PRD §6.3）：接单人显式声明/撤销「智能体协同」。

    8 态机零改动——声明只落列 + OperationEvent 留痕，不是状态迁移。
    """
    payload = _json_body()
    if not payload or not isinstance(payload.get("enabled"), bool) or set(payload) - {
        "enabled"
    }:
        return error_response("invalid_request", "enabled 布尔必填（唯一字段）。", 400)
    session = db.session()
    try:
        with session.begin():
            package = declare_agent_assisted(
                session,
                actor=g.current_user,
                package_id=package_id,
                enabled=payload["enabled"],
            )
            result = _whitelist_payload(session, package)
        return jsonify({"data": result, "error": None})
    except DispatchServiceError as error:
        return _dispatch_error(error)
    finally:
        session.close()


@blueprint.post("/packages/<package_id>/withdraw")
@require_auth
def withdraw_package_route(package_id: str):
    if g.current_user.role not in _PLATFORM_ROLES:
        return error_response("forbidden", "只有平台侧可撤回交付包。", 403)
    session = db.session()
    try:
        with session.begin():
            package = transition_package(
                session, actor=g.current_user, package_id=package_id, action="withdraw"
            )
            result = _whitelist_payload(session, package)
        return jsonify({"data": result, "error": None})
    except DispatchServiceError as error:
        return _dispatch_error(error)
    finally:
        session.close()


@blueprint.post("/packages/<package_id>/accept")
@require_auth
def accept_package_route(package_id: str):
    payload = _json_body()
    delivery_user_id = payload.get("delivery_user_id") if payload else None
    if not isinstance(delivery_user_id, str) or not delivery_user_id:
        return error_response("invalid_request", "delivery_user_id 必填。", 400)
    actor = g.current_user
    if actor.role not in _PLATFORM_ROLES:
        # 交付方本人接单：须是被指派人且持该包未撤销 delivery 授权（§9.2）
        if actor.id != delivery_user_id:
            return error_response(
                "forbidden", "只有平台侧或被指派的交付方本人可接单。", 403
            )
        with db.session() as session:
            if not has_package_access(
                session, user=actor, package_id=package_id, roles=("delivery",)
            ):
                return error_response(
                    "package_not_found", "交付包不存在或无权访问。", 404
                )
    try:
        result = accept_package(
            actor=actor, package_id=package_id, delivery_user_id=delivery_user_id
        )
    except DispatchServiceError as error:
        return _dispatch_error(error)
    return jsonify({"data": result, "error": None})


@blueprint.post("/packages/<package_id>/offers")
@require_auth
def create_offers_route(package_id: str):
    payload = _json_body() or {}
    if g.current_user.role not in _PLATFORM_ROLES:
        return error_response("forbidden", "只有平台侧可指派。", 403)
    candidates_raw = payload.get("candidate_user_ids") or []
    if not isinstance(candidates_raw, list) or not candidates_raw or not all(
        isinstance(item, str) for item in candidates_raw
    ):
        return error_response(
            "invalid_request", "candidate_user_ids 必须是非空字符串数组。", 400
        )
    session = db.session()
    try:
        with session.begin():
            offers = create_assign_offers(
                session,
                actor=g.current_user,
                package_id=package_id,
                candidate_user_ids=tuple(candidates_raw),
            )
            data = [
                {
                    "offer_id": offer.id,
                    "candidate_user_id": offer.candidate_user_id,
                    "dispatch_round": offer.dispatch_round,
                    "status": offer.status,
                    "version": offer.version,
                }
                for offer in offers
            ]
        return jsonify({"data": data, "error": None}), 201
    except DispatchServiceError as error:
        return _dispatch_error(error)
    finally:
        session.close()


@blueprint.post("/offers/<offer_id>/accept")
@require_auth
def accept_offer_route(offer_id: str):
    payload = _json_body() or {}
    expected_version = payload.get("version")
    if type(expected_version) is not int:
        return error_response("invalid_request", "version（乐观锁）必填。", 400)
    try:
        result = accept_offer_and_handover(
            actor=g.current_user, offer_id=offer_id, expected_version=expected_version
        )
    except DispatchServiceError as error:
        return _dispatch_error(error)
    return jsonify({"data": result, "error": None})


@blueprint.post("/offers/<offer_id>/decline")
@require_auth
def decline_offer_route(offer_id: str):
    payload = _json_body() or {}
    expected_version = payload.get("version")
    if type(expected_version) is not int:
        return error_response("invalid_request", "version（乐观锁）必填。", 400)
    reason = payload.get("reason")
    if reason is not None and not isinstance(reason, str):
        return error_response("invalid_request", "reason 必须是字符串。", 400)
    session = db.session()
    try:
        with session.begin():
            offer = decline_offer(
                session,
                actor=g.current_user,
                offer_id=offer_id,
                expected_version=expected_version,
                reason=reason,
            )
            data = {
                "offer_id": offer.id,
                "status": offer.status,
                "version": offer.version,
            }
        return jsonify({"data": data, "error": None})
    except DispatchServiceError as error:
        return _dispatch_error(error)
    finally:
        session.close()


@blueprint.get("/offers/mine")
@require_auth
def list_my_offers_route():
    """我的 offer 收件箱（接单工作台，B1）。

    只含 candidate_user_id=当前用户的行（§6.3 全量留痕语义：offered 之外的
    已决历史一并可见，前端据此展示收件箱+历史）；deadline=§6.2 窗口现算
    （claim 15 分钟确认窗 / assign 包响应窗）；match_breakdown 是 §4.8
    对被派方本人的释明数据，只回本人。包侧走同一白名单 payload（§9.2）。
    """
    from fde_api.dispatch.models import DispatchOffer
    from fde_api.dispatch.offer_service import offer_deadline

    session = db.session()
    try:
        rows = session.execute(
            select(DispatchOffer, DeliveryPackage)
            .join(DeliveryPackage, DeliveryPackage.id == DispatchOffer.package_id)
            .where(DispatchOffer.candidate_user_id == g.current_user.id)
            .order_by(
                DispatchOffer.offered_at.desc().nullslast(),
                DispatchOffer.created_at.desc(),
            )
        ).all()
        data = []
        for offer, package in rows:
            mode = (offer.match_breakdown or {}).get("mode") or package.dispatch_mode
            deadline = offer_deadline(offer, package)
            data.append(
                {
                    "offer_id": offer.id,
                    "status": offer.status,
                    "version": offer.version,
                    "dispatch_round": offer.dispatch_round,
                    "mode": mode,
                    "offered_at": offer.offered_at.isoformat()
                    if offer.offered_at
                    else None,
                    "responded_at": offer.responded_at.isoformat()
                    if offer.responded_at
                    else None,
                    "deadline": deadline.isoformat() if deadline else None,
                    "match_breakdown": offer.match_breakdown,
                    "package": _whitelist_payload(session, package),
                }
            )
        return jsonify({"data": data, "error": None})
    finally:
        session.close()


@blueprint.get("/settlements/mine")
@require_auth
def list_my_settlements_route():
    """我的席位结算（§7.2，接单工作台，B1）。

    隔离纪律：只回当前用户占据席位的行，且只回**自己席位**的角色与金额——
    其他席位的存在与金额不出现（§9.5 同源；工程师只看自己的分成）。
    withholding_tax 原样透出、不算净额（预扣口径=B-③ 待法务确认，不发明）。
    """
    from fde_api.dispatch.models import DeliverySettlement

    me = g.current_user.id
    session = db.session()
    try:
        rows = session.execute(
            select(DeliverySettlement, DeliveryPackage.package_code)
            .join(
                DeliveryPackage,
                DeliveryPackage.id == DeliverySettlement.package_id,
            )
            .where(
                (DeliverySettlement.seat_platform_user_id == me)
                | (DeliverySettlement.seat_region_agent_user_id == me)
                | (DeliverySettlement.seat_city_partner_user_id == me)
                | (DeliverySettlement.seat_delivery_user_id == me)
            )
            .order_by(DeliverySettlement.created_at.desc())
        ).all()
        data = []
        for settlement, package_code in rows:
            my_roles: list[str] = []
            my_amount = 0.0
            for role, seat_user, amount in (
                (
                    "platform",
                    settlement.seat_platform_user_id,
                    settlement.platform_amount,
                ),
                (
                    "region",
                    settlement.seat_region_agent_user_id,
                    settlement.region_amount,
                ),
                (
                    "city",
                    settlement.seat_city_partner_user_id,
                    settlement.city_amount,
                ),
                (
                    "delivery",
                    settlement.seat_delivery_user_id,
                    settlement.delivery_amount,
                ),
            ):
                if seat_user == me:
                    my_roles.append(role)
                    my_amount += float(amount)
            data.append(
                {
                    "settlement_id": settlement.id,
                    "package_code": package_code,
                    "settlement_key": settlement.settlement_key,
                    "status": settlement.status,
                    "base_amount": float(settlement.base_amount),
                    "my_roles": my_roles,
                    "my_amount": round(my_amount, 2),
                    "withholding_tax": float(settlement.withholding_tax),
                    "acceptance_passed_at": settlement.acceptance_passed_at.isoformat()
                    if settlement.acceptance_passed_at
                    else None,
                    "paid_at": settlement.paid_at.isoformat()
                    if settlement.paid_at
                    else None,
                }
            )
        return jsonify({"data": data, "error": None})
    finally:
        session.close()


@blueprint.get("/profiles/me")
@require_auth
def read_my_profile_route():
    """我的能力档案自助视图（§3 供给池；接单工作台，B1）。

    平台侧 list_profiles 是档案互见的管理视角（403 防「他人在途计数」
    泄露）；本人看自己档案零泄露，产能上限口径与其一致（§6.5）。
    """
    from fde_api.dispatch.models import DispatchOffer, FdeProfile
    from sqlalchemy import func

    session = db.session()
    try:
        profile = session.scalar(
            select(FdeProfile).where(FdeProfile.user_id == g.current_user.id)
        )
        if profile is None:
            return error_response(
                "profile_not_found", "尚无能力档案（由平台创建/晋级流程建立）。", 404
            )
        in_hand = (
            session.execute(
                select(func.count(DispatchOffer.id))
                .where(DispatchOffer.candidate_user_id == g.current_user.id)
                .where(DispatchOffer.status.in_(("offered", "accepted")))
            ).scalar_one()
        )
        cap = (
            (profile.monthly_capacity_hours or 0)
            // max(profile.avg_delivery_hours or 0, 1)
            if profile.monthly_capacity_hours
            else 0
        )
        data = {
            "level": profile.level,
            "status": profile.status,
            "scores": {
                "biz_cognition": profile.biz_cognition_score,
                "scenario_eng": profile.scenario_eng_score,
                "ai_tech": profile.ai_tech_score,
                "delivery_assure": profile.delivery_assure_score,
            },
            "industry_tags": profile.industry_tags or [],
            "module_tags": profile.module_tags or [],
            "home_city": profile.home_city,
            "geo_fence_km": profile.geo_fence_km,
            "monthly_capacity_hours": profile.monthly_capacity_hours,
            "avg_delivery_hours": profile.avg_delivery_hours,
            "in_hand": in_hand,
            "capacity_cap": cap,
        }
        return jsonify({"data": data, "error": None})
    finally:
        session.close()


@blueprint.get("/packages/<package_id>/offers")
@require_auth
def list_package_offers_route(package_id: str):
    """包侧 offer 留痕（调度台操作面，B2；平台侧——全量留痕含候选人身份）。

    调度台需要据此运营：看本轮谁被派、谁接了/拒了、确认窗还剩多久，
    再决定代接单（accept）/重派（rejected/expired → publish round+1）。
    deadline=§6.2 窗口现算（claim 15 分钟确认窗 / assign 包响应窗）；
    rank/explanation 取自 match_breakdown（§4.8 释明对平台侧同可见）。
    """
    if g.current_user.role not in _PLATFORM_ROLES:
        return error_response("forbidden", "只有平台侧可查看包的 offer 留痕。", 403)
    from fde_api.dispatch.models import DispatchOffer
    from fde_api.dispatch.offer_service import offer_deadline
    from fde_api.workbench.models import User as UserModel

    session = db.session()
    try:
        package = session.get(DeliveryPackage, package_id)
        if package is None:
            return error_response("package_not_found", "交付包不存在。", 404)
        rows = session.execute(
            select(DispatchOffer, UserModel.username, UserModel.display_name)
            .join(UserModel, UserModel.id == DispatchOffer.candidate_user_id)
            .where(DispatchOffer.package_id == package.id)
            .order_by(
                DispatchOffer.dispatch_round.desc(),
                DispatchOffer.offered_at.desc().nullslast(),
                DispatchOffer.created_at.desc(),
            )
        ).all()
        data = []
        for offer, username, display_name in rows:
            mode = (offer.match_breakdown or {}).get("mode") or package.dispatch_mode
            breakdown = offer.match_breakdown or {}
            deadline = offer_deadline(offer, package)
            data.append(
                {
                    "offer_id": offer.id,
                    "candidate_user_id": offer.candidate_user_id,
                    "candidate_username": username,
                    "candidate_display_name": display_name,
                    "dispatch_round": offer.dispatch_round,
                    "mode": mode,
                    "status": offer.status,
                    "version": offer.version,
                    "rank": breakdown.get("rank"),
                    "explanation": breakdown.get("explanation"),
                    "offered_at": offer.offered_at.isoformat()
                    if offer.offered_at
                    else None,
                    "responded_at": offer.responded_at.isoformat()
                    if offer.responded_at
                    else None,
                    "deadline": deadline.isoformat() if deadline else None,
                }
            )
        return jsonify({"data": data, "error": None})
    finally:
        session.close()


@blueprint.post("/packages/<package_id>/claim")
@require_auth
def claim_package_route(package_id: str):
    session = db.session()
    try:
        with session.begin():
            offer = claim_package(session, actor=g.current_user, package_id=package_id)
            data = {
                "offer_id": offer.id,
                "candidate_user_id": offer.candidate_user_id,
                "dispatch_round": offer.dispatch_round,
                "status": offer.status,
                "version": offer.version,
            }
        return jsonify({"data": data, "error": None}), 201
    except DispatchServiceError as error:
        return _dispatch_error(error)
    finally:
        session.close()


@blueprint.post("/packages/<package_id>/match")
@require_auth
def match_package_route(package_id: str):
    """撮合 Top3（§4.1–§4.8；平台侧；无公示规则版本 422=降级态人工排序）。"""
    if g.current_user.role not in _PLATFORM_ROLES:
        return error_response("forbidden", "只有平台侧可执行撮合。", 403)
    session = db.session()
    try:
        with session.begin():
            result = match_package(session, actor=g.current_user, package_id=package_id)
        return jsonify({"data": result, "error": None})
    except DispatchServiceError as error:
        return _dispatch_error(error)
    finally:
        session.close()


@blueprint.post("/packages/<package_id>/required-level")
@require_auth
def override_required_level_route(package_id: str):
    """发布前人工覆盖 required_level（§4.5；必填 reason，留痕）。"""
    payload = _json_body() or {}
    if g.current_user.role not in _PLATFORM_ROLES:
        return error_response("forbidden", "只有平台侧可覆盖等级门槛。", 403)
    level, reason = payload.get("level"), payload.get("reason")
    if not isinstance(level, str) or not isinstance(reason, str) or not reason.strip():
        return error_response("invalid_request", "level 与非空 reason 必填。", 400)
    session = db.session()
    try:
        with session.begin():
            package = override_required_level(
                session,
                actor=g.current_user,
                package_id=package_id,
                level=level,
                reason=reason,
            )
            data = {
                "package_id": package.id,
                "required_level": package.required_level,
                "dispatch_status": package.dispatch_status,
            }
        return jsonify({"data": data, "error": None})
    except DispatchServiceError as error:
        return _dispatch_error(error)
    finally:
        session.close()


@blueprint.get("/profiles")
@require_auth
def list_profiles_route():
    """能力档案 + 产能看板数据（P2-1/§3.2/§6.5；平台侧——档案含他人在途计数）。"""
    if g.current_user.role not in _PLATFORM_ROLES:
        return error_response("forbidden", "只有平台侧可查看供给池档案。", 403)
    from fde_api.dispatch.models import DispatchOffer, FdeProfile
    from fde_api.workbench.models import User as UserModel
    from sqlalchemy import func

    with db.session() as session:
        in_hand = dict(
            session.execute(
                select(
                    DispatchOffer.candidate_user_id,
                    func.count(DispatchOffer.id),
                )
                .where(
                    DispatchOffer.status.in_(("offered", "accepted")),
                )
                .group_by(DispatchOffer.candidate_user_id)
            ).all()
        )
        rows = session.execute(
            select(FdeProfile, UserModel.username, UserModel.display_name)
            .join(UserModel, UserModel.id == FdeProfile.user_id)
            .order_by(FdeProfile.user_id)
        ).all()
        data = []
        for profile, username, display_name in rows:
            cap = (
                (profile.monthly_capacity_hours or 0)
                // max(profile.avg_delivery_hours or 0, 1)
                if profile.monthly_capacity_hours
                else 0
            )
            data.append(
                {
                    "user_id": profile.user_id,
                    "username": username,
                    "display_name": display_name,
                    "level": profile.level,
                    "status": profile.status,
                    "scores": {
                        "biz_cognition": profile.biz_cognition_score,
                        "scenario_eng": profile.scenario_eng_score,
                        "ai_tech": profile.ai_tech_score,
                        "delivery_assure": profile.delivery_assure_score,
                    },
                    "industry_tags": profile.industry_tags or [],
                    "module_tags": profile.module_tags or [],
                    "home_city": profile.home_city,
                    "geo_fence_km": profile.geo_fence_km,
                    "monthly_capacity_hours": profile.monthly_capacity_hours,
                    "avg_delivery_hours": profile.avg_delivery_hours,
                    "in_hand": in_hand.get(profile.user_id, 0),
                    "capacity_cap": cap,
                }
            )
        return jsonify({"data": data, "error": None})


@blueprint.get("/rules")
@require_auth
def list_rules_route():
    """规则版本与只读常数（P2-1 权重配置页；平台侧）。"""
    if g.current_user.role not in _PLATFORM_ROLES:
        return error_response("forbidden", "只有平台侧可查看规则版本。", 403)
    from fde_api.dispatch.models import DispatchRuleVersion
    from fde_api.system_configuration import DISPATCH_CONSTANTS

    with db.session() as session:
        versions = session.scalars(
            select(DispatchRuleVersion).order_by(DispatchRuleVersion.version_no)
        ).all()
        return jsonify(
            {
                "data": {
                    "versions": [
                        {
                            "id": row.id,
                            "version_no": row.version_no,
                            "status": row.status,
                            "rule_snapshot": row.rule_snapshot,
                            "published_at": row.published_at.isoformat()
                            if row.published_at
                            else None,
                            "effective_at": row.effective_at.isoformat()
                            if row.effective_at
                            else None,
                            "retired_at": row.retired_at.isoformat()
                            if row.retired_at
                            else None,
                        }
                        for row in versions
                    ],
                    "constants": dict(DISPATCH_CONSTANTS),
                },
                "error": None,
            }
        )


@blueprint.get("/disputes")
@require_auth
def list_disputes_route():
    """争议单列表（B3 运维页簇；平台侧——§6.6 处罚类动作 100% 人工的前置视图）。

    L0 草稿由 T+30 对账自动产（L0 禁人工打开）；L1/L2 人工打开、人工裁决。
    l0_report_source_uri 是指针红线字段：只透出指针本身，永不内联对账单本体。
    """
    if g.current_user.role not in _PLATFORM_ROLES:
        return error_response("forbidden", "只有平台侧可查看争议单。", 403)
    from fde_api.dispatch.models import Dispute
    from fde_api.workbench.models import User as UserModel

    session = db.session()
    try:
        rows = session.execute(
            select(Dispute, DeliveryPackage.package_code)
            .join(DeliveryPackage, DeliveryPackage.id == Dispute.package_id)
            .order_by(Dispute.created_at.desc())
        ).all()
        user_ids = {
            dispute.opened_by_user_id for dispute, _ in rows
        } | {dispute.handled_by_user_id for dispute, _ in rows}
        user_ids.discard(None)
        names = (
            dict(
                session.execute(
                    select(UserModel.id, UserModel.display_name).where(
                        UserModel.id.in_(user_ids)
                    )
                ).all()
            )
            if user_ids
            else {}
        )
        data = [
            {
                "dispute_id": dispute.id,
                "package_id": dispute.package_id,
                "package_code": package_code,
                "settlement_key": dispute.settlement_key,
                "layer": dispute.layer,
                "status": dispute.status,
                "amount": float(dispute.amount) if dispute.amount is not None else None,
                "reason": dispute.reason,
                "resolution": dispute.resolution,
                "l0_report_source_uri": dispute.l0_report_source_uri,
                "snapshot_hash": dispute.snapshot_hash,
                "opened_by": names.get(dispute.opened_by_user_id),
                "handled_by": names.get(dispute.handled_by_user_id),
                "resolved_at": dispute.resolved_at.isoformat()
                if dispute.resolved_at
                else None,
                "created_at": dispute.created_at.isoformat()
                if dispute.created_at
                else None,
            }
            for dispute, package_code in rows
        ]
        return jsonify({"data": data, "error": None})
    finally:
        session.close()


@blueprint.post("/disputes")
@require_auth
def open_dispute_route():
    """人工打开争议（L1 平台运营 / L2 双人复核入口；L0 只由对账自动产）。"""
    payload = _json_body() or {}
    if g.current_user.role not in _PLATFORM_ROLES:
        return error_response("forbidden", "只有平台侧可打开争议。", 403)
    package_id = payload.get("package_id")
    layer, reason = payload.get("layer"), payload.get("reason")
    if not isinstance(package_id, str) or not package_id:
        return error_response("invalid_request", "package_id 必填。", 400)
    if not isinstance(layer, str) or not isinstance(reason, str) or not reason.strip():
        return error_response("invalid_request", "layer 与非空 reason 必填。", 400)
    amount_raw = payload.get("amount")
    amount = None
    if amount_raw is not None:
        try:
            amount = Decimal(str(amount_raw))
        except Exception:
            return error_response("invalid_request", "amount 必须是数字。", 400)
    settlement_key = payload.get("settlement_key")
    source_uri = payload.get("l0_report_source_uri")
    if settlement_key is not None and not isinstance(settlement_key, str):
        return error_response("invalid_request", "settlement_key 必须是字符串。", 400)
    if source_uri is not None and not isinstance(source_uri, str):
        return error_response("invalid_request", "l0_report_source_uri 必须是字符串。", 400)
    session = db.session()
    try:
        with session.begin():
            dispute = open_dispute(
                session,
                actor=g.current_user,
                package_id=package_id,
                layer=layer,
                reason=reason,
                settlement_key=settlement_key,
                amount=amount,
                l0_report_source_uri=source_uri,
            )
            data = {
                "dispute_id": dispute.id,
                "package_id": dispute.package_id,
                "layer": dispute.layer,
                "status": dispute.status,
                "snapshot_hash": dispute.snapshot_hash,
            }
        return jsonify({"data": data, "error": None}), 201
    except DispatchServiceError as error:
        return _dispatch_error(error)
    finally:
        session.close()


@blueprint.post("/disputes/<dispute_id>/resolve")
@require_auth
def resolve_dispute_route(dispute_id: str):
    """人工裁决（§6.6：结论必填；close=true 直接关闭，否则转 resolved 待复核收口）。"""
    payload = _json_body() or {}
    if g.current_user.role not in _PLATFORM_ROLES:
        return error_response("forbidden", "裁决是人工动作，仅平台侧可执行。", 403)
    resolution = payload.get("resolution")
    close = payload.get("close", False)
    if not isinstance(resolution, str) or not resolution.strip():
        return error_response("invalid_request", "裁决结论必填。", 400)
    if type(close) is not bool:
        return error_response("invalid_request", "close 必须是布尔值。", 400)
    session = db.session()
    try:
        with session.begin():
            dispute = resolve_dispute(
                session,
                actor=g.current_user,
                dispute_id=dispute_id,
                resolution=resolution,
                close=close,
            )
            data = {
                "dispute_id": dispute.id,
                "status": dispute.status,
                "resolution": dispute.resolution,
            }
        return jsonify({"data": data, "error": None})
    except DispatchServiceError as error:
        return _dispatch_error(error)
    finally:
        session.close()


@blueprint.post("/simulator/replay")
@require_auth
def simulator_replay_route():
    """历史包回放打分（B5 仿真对比入口；平台侧；只读）。

    只暴露 replay_scoring（当前池 × 当前规则版本的再撮合画像）。全链路
    种子化仿真留在 CLI（simulator.py 自建引擎连沙箱库，库名须 _sim/_test
    结尾）——绝不可经 HTTP 触发写库，口径=仿真不作为真实成绩。
    """
    if g.current_user.role not in _PLATFORM_ROLES:
        return error_response("forbidden", "只有平台侧可执行回放。", 403)
    from fde_api.dispatch.simulator import replay_scoring

    session = db.session()
    try:
        return jsonify({"data": replay_scoring(session), "error": None})
    finally:
        session.close()


@blueprint.get("/claim-gates")
@require_auth
def list_claim_gates_route():
    """城市开闸看板（B6 运维页簇；平台侧；只读）。

    §6.4 三条件 + 种子开关逐城评估（claim_gate_status 输出可解释明细）。
    种子开关在 seeds/dispatch_cities.json（文件权威）——本路由只读展示，
    改开关走代码流程，不提供 HTTP 翻转。
    """
    if g.current_user.role not in _PLATFORM_ROLES:
        return error_response("forbidden", "只有平台侧可查看开闸看板。", 403)
    from fde_api.dispatch.cities import claim_gate_status, load_dispatch_cities

    session = db.session()
    try:
        data = [
            claim_gate_status(session, str(row["city"]))
            for row in load_dispatch_cities()
        ]
        return jsonify({"data": data, "error": None})
    finally:
        session.close()
