"""delivery_packages 服务层（设计 §2.2/§2.3/§2.5，P0-1）。

快照铁律（§2.3 规则三条）：
1. snapshot_hash = sha256(canonical_json(payload))，发布时算一次即冻结——
   之后改 solution/quote **不回写**已发布包；要改 = 撤回 → 改 → 重新发布，
   新哈希 + dispatch_round 递增（版本对 Unique(project_id, dispatch_round)）。
2. 接单与结算引用 snapshot_hash（争议仲裁看到的是「当时那一版」）。
3. 每次状态迁移写 OperationEvent（P0-6 白名单已注册 delivery_package 目标）。

onsite_required 派生（§4.6 + goal-r3 留注⑥）：schedule 文本含
现场/到场/驻场/驻点 关键词即真——关键词启发式，规则化随 P1-2 场景引擎收口。
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Mapping

from sqlalchemy import select
from sqlalchemy.orm import Session

from fde_api.auth.models import User
from fde_api.dispatch.access import grant_package_access
from fde_api.dispatch.channel_guard import ChannelGuardError, ensure_package_channel
from fde_api.dispatch.errors import DispatchServiceError
from fde_api.dispatch.models import DeliveryPackage, DispatchOffer
from fde_api.extensions import db
from fde_api.projects.events import record_event
from fde_api.solutions.models import ProjectSolution
from fde_api.system_configuration import DISPATCH_CONSTANTS
from fde_api.workbench.models import Project, ProjectModule, Quote

# §2.5 八态状态机：action → {from_status: to_status}。
# publish 的来源含 withdrawn（撤回重发）/rejected（重派）/expired（人工介入
# 后的重发）——三者都走 round+1 新版本对（§2.3 规则 1/3 与 §2.5 图）。
TRANSITIONS: dict[str, dict[str, str]] = {
    "publish": {
        "draft": "published",
        "withdrawn": "published",
        "rejected": "published",
        "expired": "published",
    },
    "offer": {"published": "offered"},
    "assign": {"offered": "assigned"},
    "accept": {"offered": "accepted", "assigned": "accepted"},
    "reject": {"offered": "rejected", "assigned": "rejected"},
    "expire": {"published": "expired", "offered": "expired"},
    "withdraw": {"published": "withdrawn"},
}

_ONSITE_KEYWORDS = ("现场", "到场", "驻场", "驻点")


def canonical_json(payload: Mapping[str, Any]) -> str:
    """§2.3 canonical_json 规则：键字典序、ensure_ascii=False、紧凑分隔符、
    Decimal→str、None→null、required_modules 先排序（调用方负责）。"""
    normalized = {
        key: str(value) if isinstance(value, Decimal) else value
        for key, value in payload.items()
    }
    return json.dumps(
        normalized, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )


def compute_snapshot_hash(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def _snapshot_payload(
    package: DeliveryPackage,
    solution: ProjectSolution,
    project: Project,
    quote: Quote,
    *,
    published_at: datetime,
) -> dict[str, Any]:
    """§2.3 快照字段清单（逐字段对表，勿增删）。"""
    return {
        "package_id": package.id,
        "solution_id": solution.id,
        "solution_version": solution.version,
        "project_id": project.id,
        "name": solution.name,
        "business_category": solution.business_category,
        "design_markdown": solution.design_markdown,
        "deliverables": solution.deliverables,
        "acceptance_criteria": solution.acceptance_criteria,
        "data_systems": solution.data_systems,
        "schedule": solution.schedule,
        "risks_dependencies": solution.risks_dependencies,
        "quote_id": quote.id,
        "quote_version": quote.version,
        "quote_tier": quote.tier,
        "quote_low": quote.quote_low,
        "quote_high": quote.quote_high,
        "b_layer_score": quote.b_layer_score,
        "required_modules": package.required_modules or [],
        "required_industry": package.required_industry,
        "onsite_required": package.onsite_required,
        "seat_lead": package.seat_lead,
        "seat_delivery": package.seat_delivery,
        "seat_consult": package.seat_consult,
        "seat_qa": package.seat_qa,
        "published_at": published_at.astimezone(timezone.utc).isoformat(),
    }


def _derive_onsite_required(schedule: str) -> bool:
    return any(keyword in (schedule or "") for keyword in _ONSITE_KEYWORDS)


def _generate_package_code(session: Session, project: Project, round_no: int) -> str:
    """PKG-{project_code 尾段}-{round:02d}（尾段为 8 位随机十六进制，实际唯一；
    冲突即 409 重试）。"""
    tail = (project.project_code or "").split("-")[-1][:8] or project.id[:8]
    code = f"PKG-{tail}-{round_no:02d}"
    clash = session.scalar(
        select(DeliveryPackage.id).where(DeliveryPackage.package_code == code)
    )
    if clash is not None:
        raise DispatchServiceError("package_code_conflict", "交付包编码冲突，请重试。", 409)
    return code


def _load_context(
    session: Session, solution_id: str
) -> tuple[ProjectSolution, Project, list[str], str | None]:
    solution = session.get(ProjectSolution, solution_id)
    if solution is None or solution.status != "active":
        raise DispatchServiceError("solution_not_found", "方案不存在或已归档。", 404)
    project = session.get(Project, solution.project_id)
    if project is None:
        raise DispatchServiceError("project_not_found", "项目不存在。", 404)
    module_ids = sorted(
        session.scalars(
            select(ProjectModule.module_catalog_id).where(
                ProjectModule.project_id == project.id,
                ProjectModule.status == "active",
            )
        )
    )
    industry = None
    if project.source_template_version is not None:
        industry = project.source_template_version.industry_name
    return solution, project, module_ids, industry


def _assert_transition(package: DeliveryPackage, action: str) -> None:
    table = TRANSITIONS.get(action)
    if table is None:
        raise DispatchServiceError("invalid_request", f"未知动作 {action}。")
    target = table.get(package.dispatch_status)
    if target is None:
        raise DispatchServiceError(
            "invalid_dispatch_state",
            f"状态 {package.dispatch_status} 不允许 {action}（§2.5 状态机）。",
            409,
        )


def create_package(
    session: Session,
    *,
    actor: User,
    solution_id: str,
    quote_id: str,
    dispatch_mode: str = "assign",
    onsite_visits: int | None = None,
) -> DeliveryPackage:
    """draft 落库（§2.5 draft 行：方案+项目+报价要素齐备才可建）。"""
    if dispatch_mode not in ("assign", "claim"):
        raise DispatchServiceError("invalid_request", "dispatch_mode 必须是 assign/claim。")
    if actor.role not in ("admin", "project_lead"):
        raise DispatchServiceError(
            "verifier_role_required", "只有平台侧（admin/project_lead）可建交付包。", 403
        )
    solution, project, module_ids, industry = _load_context(session, solution_id)
    # P2-4 私单封堵（派单设计 §8.5）H3 渠道正交：交付包只能建在派单线项目上。
    try:
        ensure_package_channel(project)
    except ChannelGuardError as error:
        raise DispatchServiceError(error.code, error.message, error.status) from None
    quote = session.get(Quote, quote_id)
    if quote is None or quote.project_id != project.id:
        raise DispatchServiceError("invalid_request", "quote 必须属于同一项目。", 400)
    existing = session.scalar(
        select(DeliveryPackage.id).where(DeliveryPackage.solution_id == solution.id)
    )
    if existing is not None:
        raise DispatchServiceError(
            "package_exists", "该方案已有交付包（撤回/拒绝后重发走同一行）。", 409
        )

    package = DeliveryPackage(
        id=solution.id,
        solution_id=solution.id,
        project_id=project.id,
        package_code=_generate_package_code(session, project, 1),
        quote_id=quote.id,
        # SOW 档（a/b/c/d）随 Contract 定档回填，创建时不猜
        sow_type=None,
        dispatch_mode=dispatch_mode,
        dispatch_status="draft",
        dispatch_round=1,
        response_window_hours=DISPATCH_CONSTANTS["response_window_hours"],
        redispatch_radius_km=25,
        # §4.5（C4 判据）：required_level 由 Quote 系数推导落库；发布前可
        # 经 matching.override_required_level 人工覆盖（必填 reason + 留痕）
        required_modules=module_ids,
        required_industry=industry,
        onsite_required=_derive_onsite_required(solution.schedule),
        onsite_visits=onsite_visits,
    )
    session.add(package)
    session.flush()
    record_event(
        session,
        actor,
        "delivery_package_created",
        package,
        {
            "package_code": package.package_code,
            "dispatch_status": "draft",
            "quote_id": quote.id,
            "required_modules": package.required_modules,
        },
    )
    return package


def publish_package(
    session: Session,
    *,
    actor: User,
    package_id: str,
    candidate_user_ids: tuple[str, ...] = (),
    difficulty: str | None = None,
) -> DeliveryPackage:
    """draft/withdrawn/rejected/expired → published：算快照哈希（一次冻结）+
    物化席位金额 + 授候选只读授权（§9.2：发布即对候选授 delivery 只读）。
    非 draft 来源 = round+1 新版本对（新 package_code + 新 snapshot_hash）。
    goal-d8：发布时平台侧定档订单难度（O-4 low/medium/high——start_run 按
    low→standard/medium→high 映射自动带入 run.difficulty，T4 免手报）。"""
    package = session.get(DeliveryPackage, package_id)
    if package is None:
        raise DispatchServiceError("package_not_found", "交付包不存在。", 404)
    if actor.role not in ("admin", "project_lead"):
        raise DispatchServiceError(
            "verifier_role_required", "只有平台侧可发布交付包。", 403
        )
    if difficulty is not None and difficulty not in ("low", "medium", "high"):
        raise DispatchServiceError(
            "invalid_request", "difficulty 必须是 low/medium/high。"
        )
    _assert_transition(package, "publish")

    solution, project, module_ids, industry = _load_context(session, package.solution_id)
    quote = session.get(Quote, package.quote_id) if package.quote_id else None
    if solution is None or project is None or quote is None:
        raise DispatchServiceError(
            "invalid_request", "发布前置要素缺失（方案/项目/报价）。", 400
        )
    if quote.status != "finalized":
        raise DispatchServiceError("quote_not_finalized", "发布前报价必须 finalized。", 422)

    previous_status = package.dispatch_status
    if previous_status != "draft":
        package.dispatch_round += 1
        package.package_code = _generate_package_code(session, project, package.dispatch_round)
        # §4.7 扩圈序列 25→50→100→0（0=全城哨兵）：每轮重派降一档
        radius_sequence = (25, 50, 100, 0)
        current = (
            radius_sequence.index(package.redispatch_radius_km)
            if package.redispatch_radius_km in radius_sequence
            else 0
        )
        package.redispatch_radius_km = radius_sequence[min(current + 1, len(radius_sequence) - 1)]

    published_at = datetime.now(timezone.utc)
    package.published_at = published_at
    package.published_by_user_id = actor.id
    package.onsite_required = package.onsite_required or _derive_onsite_required(
        solution.schedule
    )
    package.required_modules = module_ids
    package.required_industry = industry
    package.snapshot_hash = compute_snapshot_hash(
        _snapshot_payload(package, solution, project, quote, published_at=published_at)
    )
    # §7.1/§9.2：交付方席位 40% 金额发布时物化（成交额口径=final_amount，
    # 未回填时回落公式价上沿；禁 join 的代价是落库物化——goal-r3 留注⑥）
    base = quote.final_amount if quote.final_amount is not None else quote.quote_high
    if base is not None:
        share = Decimal(str(DISPATCH_CONSTANTS["seat_shares"]["delivery"]))
        package.delivery_seat_amount = (Decimal(str(base)) * share / 100).quantize(
            Decimal("0.01")
        )
    package.dispatch_status = "published"
    if difficulty is not None:
        package.difficulty = difficulty
    session.flush()

    for candidate_id in dict.fromkeys(candidate_user_ids):
        grant_package_access(
            session,
            package_id=package.id,
            user_id=candidate_id,
            role="delivery",
            granted_by_user_id=actor.id,
        )
    record_event(
        session,
        actor,
        "delivery_package_published",
        package,
        {
            "from_status": previous_status,
            "to_status": "published",
            "dispatch_round": package.dispatch_round,
            "snapshot_hash": package.snapshot_hash,
            "candidates_granted": len(set(candidate_user_ids)),
            "delivery_seat_amount": float(package.delivery_seat_amount or 0),
        },
    )
    return package


def transition_package(
    session: Session,
    *,
    actor: User,
    package_id: str,
    action: str,
    seat_delivery_user_id: str | None = None,
) -> DeliveryPackage:
    """§2.5 八态机通用迁移（offer_service P1-1 与本模块共用；每次迁移留痕）。"""
    package = session.get(DeliveryPackage, package_id)
    if package is None:
        raise DispatchServiceError("package_not_found", "交付包不存在。", 404)
    _assert_transition(package, action)

    if action == "withdraw":
        live_offer = session.scalar(
            select(DispatchOffer.id)
            .where(
                DispatchOffer.package_id == package.id,
                DispatchOffer.dispatch_round == package.dispatch_round,
                DispatchOffer.status.in_(("offered", "assigned", "accepted")),
            )
            .limit(1)
        )
        if live_offer is not None:
            raise DispatchServiceError(
                "offer_in_flight", "已有进行中的 offer，不能撤回（§2.5）。", 409
            )

    previous_status = package.dispatch_status
    package.dispatch_status = TRANSITIONS[action][previous_status]
    changes: dict[str, Any] = {
        "from_status": previous_status,
        "to_status": package.dispatch_status,
        "dispatch_round": package.dispatch_round,
    }
    if action == "accept":
        if seat_delivery_user_id is None:
            raise DispatchServiceError(
                "invalid_request", "接单必须带 seat_delivery_user_id。"
            )
        package.accepted_at = datetime.now(timezone.utc)
        package.accepted_user_id = seat_delivery_user_id
        if package.seat_delivery is None:
            package.seat_delivery = seat_delivery_user_id
        changes["accepted_user_id"] = seat_delivery_user_id
    session.flush()
    record_event(session, actor, f"delivery_package_{action}", package, changes)
    return package


def handover_accepted_member(
    project_id: str, delivery_user_id: str
) -> dict[str, Any]:
    """§9.3 鉴权交接（主事务提交后调用）：以项目管理位（leader）为 actor 复用
    add_project_member——接单人本人在交接前无 can_manage（留注⑧），stale_version
    重读一次重试，重复成员幂等。offer_service（P1-1）接单共用本函数。"""
    from fde_api.projects.service import (
        ProjectServiceError,
        add_project_member,
        get_project,
    )

    with db.session() as lookup:
        project_row = lookup.get(Project, project_id)
        leader_id = project_row.leader_user_id if project_row else None
    if leader_id is None:
        return {"added": False}
    with db.session() as session:
        leader = session.get(User, leader_id)
    if leader is None:
        return {"added": False}

    for attempt in range(2):
        project = get_project(actor=leader, project_id=project_id)
        try:
            add_project_member(
                actor=leader,
                project_id=project_id,
                expected_version=project["version"],
                user_id=delivery_user_id,
                role="member",
            )
            return {"added": True}
        except ProjectServiceError as error:
            if error.code == "duplicate_project_member":
                return {"added": False, "duplicate": True}
            if error.code != "stale_version" or attempt == 1:
                raise
    return {"added": False}


def accept_package(
    *,
    actor: User,
    package_id: str,
    delivery_user_id: str,
) -> dict[str, Any]:
    """接单 = accept 迁移 + §9.3 鉴权交接（复用 add_project_member，零新增
    项目内鉴权路径）。交接在主事务提交后执行（该服务自管事务与乐观锁版本）。"""
    session = db.session()
    try:
        with session.begin():
            package = transition_package(
                session,
                actor=actor,
                package_id=package_id,
                action="accept",
                seat_delivery_user_id=delivery_user_id,
            )
            payload = {
                "package_id": package.id,
                "dispatch_status": package.dispatch_status,
                "dispatch_round": package.dispatch_round,
                "snapshot_hash": package.snapshot_hash,
                "accepted_user_id": package.accepted_user_id,
            }
        payload["handover"] = handover_accepted_member(
            package.project_id, delivery_user_id
        )
        return payload
    finally:
        session.close()
