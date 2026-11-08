"""plans 服务：生成器（确定性拼装）+ 审阅流 + 任务分解（V3.1 P0-3）。

权限：生成/审阅/发布/任务分解=can_manage；读=can_view。
审阅纪律：approve 终态留痕（reviewed_by/at）；published 需显式发布动作；
新版本=新行不覆盖历史（approve 新行时 supersede 旧 published）。
任务分解：预览（dry_run）+选择性创建+幂等（UNIQUE(item,task) 防重复）；
未定负责人走 default_assignee_role（不指派具体人——任务书 §7 原文）。
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select

from fde_api.extensions import db
from fde_api.plans.models import (
    DeliveryPlan,
    DeliveryPlanItem,
    DeliveryPlanTaskLink,
)
from fde_api.projects.permissions import project_access
from fde_api.workbench.models import OperationEvent, Project, ProjectModule, ProjectTask

MAX_ITEMS = 100
MAX_COMMENT_CHARS = 500


class PlansServiceError(Exception):
    def __init__(self, code: str, message: str, status: int, detail: dict[str, Any] | None = None):
        super().__init__(message)
        self.code, self.message, self.status = code, message, status
        self.detail = detail or {}


def _error(code: str, message: str, status: int = 400, detail: dict[str, Any] | None = None) -> PlansServiceError:
    return PlansServiceError(code, message, status, detail)


def _require_project(session, actor, project_id: str, *, manage: bool) -> Project:
    project = session.get(Project, project_id)
    if project is None:
        raise _error("project_not_found", "项目不存在。", 404)
    access = project_access(actor, project)
    if manage and not access.can_manage:
        raise _error("forbidden", "无此项目的管理权限。", 403)
    if not access.can_view:
        raise _error("forbidden", "无此项目的访问权限。", 403)
    return project


def _object_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, ensure_ascii=False)
    except (TypeError, ValueError):
        return str(value)


# ---------------------------------------------------------------------------
# 生成器（确定性拼装，无 AI 调用）


def _next_version(session, project_id: str) -> int:
    current = session.scalar(
        select(func.max(DeliveryPlan.version)).where(DeliveryPlan.project_id == project_id)
    )
    return int(current or 0) + 1


def generate_plan(*, actor, project_id: str) -> dict[str, Any]:
    """从已批准需求 + 已接受事实 + confirmed 术语确定性拼装方案草稿。

    无任何输入（无已批准需求且无已接受事实）→ 409（拒绝空壳方案）。
    """
    from fde_api.discovery.models import BusinessFact, Requirement
    from fde_api.ontology.models import OntologyTerm

    session = db.session()
    try:
        with session.begin():
            project = _require_project(session, actor, project_id, manage=True)
            requirements = session.scalars(
                select(Requirement)
                .where(Requirement.project_id == project.id, Requirement.status == "accepted")
                .order_by(Requirement.priority, Requirement.created_at)
            ).all()
            facts = session.scalars(
                select(BusinessFact)
                .where(BusinessFact.project_id == project.id, BusinessFact.review_status == "accepted")
                .order_by(BusinessFact.created_at)
            ).all()
            terms = session.scalars(
                select(OntologyTerm.term).where(
                    OntologyTerm.project_id == project.id, OntologyTerm.status == "confirmed"
                )
            ).all()
            if not requirements and not facts:
                raise _error(
                    "no_approved_inputs",
                    "尚无已批准需求或已接受事实：先完成访谈事实/需求审阅再生成方案。",
                    409,
                )
            items: list[dict[str, Any]] = []
            # ① 需求条目（每条已批准需求一个，验收标准随行）
            for requirement in requirements:
                items.append({
                    "item_type": "requirement",
                    "title": requirement.title,
                    "detail": requirement.description
                    or "；".join(requirement.acceptance_criteria or [])[:2000],
                    "priority": requirement.priority,
                    "requirement_keys": [requirement.requirement_key],
                })
            # ② 目标条目（领域术语清单=方案范围快照）
            if terms:
                items.append({
                    "item_type": "objective",
                    "title": "领域对象范围（confirmed 术语）",
                    "detail": "、".join(sorted(terms))[:2000],
                    "priority": "medium",
                })
            # ③ 风险条目（needs_clarification 事实聚合——「待澄清」本身是
            # 审阅结论之一，作为风险素材独立于 accepted 集查询）
            open_facts = session.scalars(
                select(BusinessFact)
                .where(
                    BusinessFact.project_id == project.id,
                    BusinessFact.review_status == "needs_clarification",
                )
                .order_by(BusinessFact.created_at)
            ).all()
            if open_facts:
                items.append({
                    "item_type": "risk",
                    "title": "待澄清项（来自访谈事实）",
                    "detail": "；".join(f"{f.subject}·{f.predicate}" for f in open_facts)[:2000],
                    "priority": "high",
                    "fact_ids": [f.id for f in open_facts],
                })
            items = items[:MAX_ITEMS]
            plan = DeliveryPlan(
                project_id=project.id,
                created_by_user_id=actor.id,
                title=f"交付方案 v{_next_version(session, project.id)}（自动拼装草稿）",
                summary=f"需求 {len(requirements)} 条 · 事实 {len(facts)} 条 · 术语 {len(terms)} 个",
                status="draft",
                version=_next_version(session, project.id),
            )
            session.add(plan)
            session.flush()
            for order, spec in enumerate(items):
                session.add(DeliveryPlanItem(
                    plan_id=plan.id,
                    project_id=project.id,
                    item_type=spec["item_type"],
                    title=spec["title"][:200],
                    detail=spec.get("detail"),
                    priority=spec.get("priority", "medium"),
                    requirement_keys=spec.get("requirement_keys"),
                    fact_ids=spec.get("fact_ids"),
                    sort_order=order,
                ))
            session.add(OperationEvent(
                actor_user_id=actor.id,
                project_id=project.id,
                target_type="delivery_plan",
                target_id=plan.id,
                event_type="delivery_plan_generated",
                changes={"items": len(items), "requirements": len(requirements), "facts": len(facts)},
            ))
            session.flush()
            return serialize_plan(session, plan)
    finally:
        session.close()


# ---------------------------------------------------------------------------
# 审阅与发布


def review_plan(*, actor, plan_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    session = db.session()
    try:
        with session.begin():
            plan = _owned_plan(session, actor, plan_id, manage=True)
            decision = payload.get("decision")
            if decision not in ("approved", "rejected"):
                raise _error("invalid_decision", "decision 仅可为 approved/rejected。", 400)
            comment = payload.get("comment")
            if comment is not None and (not isinstance(comment, str) or len(comment) > MAX_COMMENT_CHARS):
                raise _error("invalid_comment", "审阅备注必须是 ≤500 字的文本。", 400)
            if plan.status != "draft":
                raise _error("plan_not_draft", "仅草稿态方案可审阅。", 409)
            if decision == "approved":
                # 新版本批准 ⇒ 旧 published 行退位 superseded（不覆盖历史行内容）
                session.execute(
                    _supersede_published(project_id=plan.project_id, exclude_id=plan.id)
                )
                plan.status = "approved"
            else:
                plan.status = "superseded"
            plan.reviewed_by_user_id = actor.id
            plan.reviewed_at = datetime.now(UTC)
            if comment is not None:
                plan.review_comment = comment
            session.add(OperationEvent(
                actor_user_id=actor.id,
                project_id=plan.project_id,
                target_type="delivery_plan",
                target_id=plan.id,
                event_type="delivery_plan_reviewed",
                changes={"decision": decision, "comment": comment or ""},
            ))
            session.flush()
            return serialize_plan(session, plan)
    finally:
        session.close()


def publish_plan(*, actor, plan_id: str) -> dict[str, Any]:
    session = db.session()
    try:
        with session.begin():
            plan = _owned_plan(session, actor, plan_id, manage=True)
            if plan.status != "approved":
                raise _error("plan_not_approved", "仅已批准（approved）方案可发布。", 409)
            session.execute(_supersede_published(project_id=plan.project_id, exclude_id=plan.id))
            plan.status = "published"
            plan.published_by_user_id = actor.id
            plan.published_at = datetime.now(UTC)
            session.add(OperationEvent(
                actor_user_id=actor.id,
                project_id=plan.project_id,
                target_type="delivery_plan",
                target_id=plan.id,
                event_type="delivery_plan_published",
                changes={"version": plan.version},
            ))
            session.flush()
            return serialize_plan(session, plan)
    finally:
        session.close()


def _supersede_published(project_id: str, exclude_id: str):
    from sqlalchemy import update

    return (
        update(DeliveryPlan)
        .where(
            DeliveryPlan.project_id == project_id,
            DeliveryPlan.id != exclude_id,
            DeliveryPlan.status == "published",
        )
        .values(status="superseded")
    )


# ---------------------------------------------------------------------------
# 任务分解（预览 + 选择性创建 + 幂等）


def _plan_items(session, plan: DeliveryPlan, item_ids: list[str] | None) -> list[DeliveryPlanItem]:
    stmt = select(DeliveryPlanItem).where(DeliveryPlanItem.plan_id == plan.id).order_by(DeliveryPlanItem.sort_order)
    if item_ids:
        stmt = stmt.where(DeliveryPlanItem.id.in_(item_ids))
    return list(session.scalars(stmt).all())


def _task_draft(item: DeliveryPlanItem) -> dict[str, Any]:
    # 不传指派人与角色：create_project_task 落 default_assignee_role=None
    # =待认领（任务书 §7「未确定负责人时不随意指派员工」——指派归后续人工）
    return {
        "item_id": item.id,
        "item_type": item.item_type,
        "name": item.title[:160],
        "description": (item.detail or "")[:2000],
        "duration_days": 1,
    }


def create_plan_tasks(
    *, actor, plan_id: str, payload: dict[str, Any]
) -> dict[str, Any]:
    """条目→既有 project_tasks（dry_run 预览 / 选择性创建 / 幂等跳过）。

    幂等锚=UNIQUE(item,task) + 每 item 至多一条 link；已链接条目在预览与
    创建中都回 skipped。任务必须挂项目既有模块（module_id 必填）。
    """
    from fde_api.projects.task_service import create_project_task

    session = db.session()
    try:
        with session.begin():
            plan = _owned_plan(session, actor, plan_id, manage=True)
            if plan.status not in ("approved", "published"):
                raise _error("plan_not_approved", "仅已批准/已发布方案可分解任务。", 409)
            item_ids = payload.get("item_ids")
            if item_ids is not None and (
                not isinstance(item_ids, list) or any(not isinstance(i, str) for i in item_ids)
            ):
                raise _error("invalid_request", "item_ids 必须为字符串数组。", 400)
            module_id = payload.get("module_id")
            module = session.get(ProjectModule, module_id) if isinstance(module_id, str) else None
            if module is None or module.project_id != plan.project_id:
                raise _error("module_not_found", "目标模块不存在或不属于该项目。", 404)
            dry_run = payload.get("dry_run", True)
            if not isinstance(dry_run, bool):
                raise _error("invalid_request", "dry_run 必须为布尔。", 400)
            items = _plan_items(session, plan, item_ids)
            if not items:
                raise _error("no_items", "没有可分解的条目。", 409)
            created, skipped, preview = [], [], []
            for item in items:
                existing_link = session.scalar(
                    select(DeliveryPlanTaskLink).where(DeliveryPlanTaskLink.item_id == item.id)
                )
                if existing_link is not None:
                    skipped.append({"item_id": item.id, "task_id": existing_link.task_id, "reason": "已分解"})
                    continue
                draft = _task_draft(item)
                if dry_run:
                    preview.append(draft)
                    continue
                result = create_project_task(
                    actor=actor,
                    project_id=plan.project_id,
                    module_identifier=module.id,
                    input=draft,
                )
                task = session.get(ProjectTask, result["id"])
                if task is None:  # pragma: no cover - create_project_task 返回必存在
                    raise _error("task_missing", "任务创建结果不可读。", 500)
                session.add(DeliveryPlanTaskLink(
                    plan_id=plan.id,
                    item_id=item.id,
                    task_id=task.id,
                    project_id=plan.project_id,
                    created_by_user_id=actor.id,
                ))
                created.append({"item_id": item.id, "task_id": task.id})
            session.add(OperationEvent(
                actor_user_id=actor.id,
                project_id=plan.project_id,
                target_type="delivery_plan",
                target_id=plan.id,
                event_type="delivery_plan_tasks_created" if not dry_run else "delivery_plan_tasks_previewed",
                changes={"created": len(created), "skipped": len(skipped), "module_id": module.id},
            ))
            session.flush()
            return {
                "dry_run": dry_run,
                "created": created,
                "skipped": skipped,
                "preview": preview,
            }
    finally:
        session.close()


# ---------------------------------------------------------------------------
# 读面与序列化


def get_plan(*, actor, plan_id: str) -> dict[str, Any]:
    session = db.session()
    try:
        with session.begin():
            plan = _owned_plan(session, actor, plan_id, manage=False)
            return serialize_plan(session, plan)
    finally:
        session.close()


def list_plans(*, actor, project_id: str, status: str | None = None, limit: int = 50) -> dict[str, Any]:
    session = db.session()
    try:
        with session.begin():
            _require_project(session, actor, project_id, manage=False)
            stmt = select(DeliveryPlan).where(DeliveryPlan.project_id == project_id)
            if status:
                stmt = stmt.where(DeliveryPlan.status == status)
            rows = session.scalars(stmt.order_by(DeliveryPlan.created_at.desc()).limit(limit)).all()
            return {"items": [serialize_plan(session, row) for row in rows], "limit": limit}
    finally:
        session.close()


def _owned_plan(session, actor, plan_id: str, *, manage: bool) -> DeliveryPlan:
    plan = session.get(DeliveryPlan, plan_id)
    if plan is None:
        raise _error("plan_not_found", "交付方案不存在。", 404)
    _require_project(session, actor, plan.project_id, manage=manage)
    return plan


def serialize_plan(session, plan: DeliveryPlan) -> dict[str, Any]:
    items = session.scalars(
        select(DeliveryPlanItem).where(DeliveryPlanItem.plan_id == plan.id).order_by(DeliveryPlanItem.sort_order)
    ).all()
    links = session.scalars(
        select(DeliveryPlanTaskLink).where(DeliveryPlanTaskLink.plan_id == plan.id)
    ).all()
    linked_by_item: dict[str, str] = {link.item_id: link.task_id for link in links}
    return {
        "id": plan.id,
        "project_id": plan.project_id,
        "title": plan.title,
        "summary": plan.summary,
        "status": plan.status,
        "version": plan.version,
        "source_extraction_id": plan.source_extraction_id,
        "created_by_user_id": plan.created_by_user_id,
        "reviewed_by_user_id": plan.reviewed_by_user_id,
        "reviewed_at": plan.reviewed_at.isoformat() if plan.reviewed_at else None,
        "review_comment": plan.review_comment,
        "published_by_user_id": plan.published_by_user_id,
        "published_at": plan.published_at.isoformat() if plan.published_at else None,
        "items": [{
            "id": item.id,
            "item_type": item.item_type,
            "title": item.title,
            "detail": item.detail,
            "priority": item.priority,
            "requirement_keys": item.requirement_keys or [],
            "fact_ids": item.fact_ids or [],
            "sort_order": item.sort_order,
            "task_id": linked_by_item.get(item.id),
        } for item in items],
        "task_link_count": len(links),
    }
