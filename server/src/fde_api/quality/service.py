"""quality 服务：测试计划生成/审阅/执行登记（V3.1 P1-2）。

纪律（任务书 §10 约束逐条落地）：
- 生成=确定性拼装无 AI（沿 P0-3 生成器先例；组序/条目序按 requirement_key
  字典序——单事务 created_at 全同+uuid4 id 无序，插入序不可依赖，#209 教训）；
- 「每条批准需求至少有测试或明确人工验收方式」=审核 approved 时的覆盖闸
  （本计划+既有 approved 计划的 cases.requirement_key 并集须覆盖全部 accepted
  需求，缺失点名 409 requirement_coverage_incomplete）；
- 「模型生成用例先审核」=计划 draft→approved 人工闸承载（本轮生成器为确定性
  拼装，AI 用例通道为未来增强，落库即待审核于 draft 计划）；
- 「生产环境测试默认禁止」=execute 服务层硬闸 409 production_forbidden；
- 「失败结果不能被摘要 Agent 改写为成功」=执行 append-only（本服务无任何
  执行更新函数，重跑=新行；钉测试断言无 PATCH 执行路由）；
- 报告只存指针+sha256（成对 CHECK，证据红线）。
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from fde_api.extensions import db
from fde_api.quality.models import (
    EXECUTION_ENVIRONMENTS,
    EXECUTION_RESULTS,
    TestCase,
    TestExecution,
    TestPlan,
)
from fde_api.workbench.models import OperationEvent, ProjectTask

_PRIORITY_TO_RISK = {"high": 3, "medium": 2, "low": 1}
_EXECUTION_FIELDS = {"case_id", "result", "started_at", "finished_at", "report_uri", "report_sha256", "note"}


class QualityServiceError(Exception):
    def __init__(self, code: str, message: str, status: int, detail: dict[str, Any] | None = None):
        super().__init__(message)
        self.code, self.message, self.status = code, message, status
        self.detail = detail or {}


def _error(code: str, message: str, status: int = 400, detail: dict[str, Any] | None = None) -> QualityServiceError:
    return QualityServiceError(code, message, status, detail)


def _require_project(session: Session, actor, project_id: str, *, manage: bool):
    from fde_api.projects.permissions import project_access
    from fde_api.workbench.models import Project

    project = session.get(Project, project_id)
    if project is None:
        raise _error("project_not_found", "项目不存在或已被删除。", 404)
    access = project_access(actor, project)
    if not (access.can_manage if manage else access.can_view):
        raise _error("forbidden", "你没有该项目的操作权限。", 403)
    return project


def _load_plan(session: Session, actor, plan_id: str, *, manage: bool) -> TestPlan:
    plan = session.get(TestPlan, plan_id)
    if plan is None:
        raise _error("plan_not_found", "测试计划不存在。", 404)
    _require_project(session, actor, plan.project_id, manage=manage)
    return plan


# ---------------------------------------------------------------------------
# 生成（确定性拼装，无 AI）


def generate_test_plan(*, actor, project_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    """从已批准需求确定性拼装测试计划草稿（can_manage）。

    每条 accepted 需求一条用例：requirement_key 追溯、expected=验收标准聚合、
    risk_level=priority 映射、acceptance_mode=test；无已批准需求 409 拒绝空壳。
    source_task_id 可选（任务书「按任务生成」语义；必须属于本项目）。
    """
    from fde_api.discovery.models import Requirement

    session = db.session()
    try:
        with session.begin():
            project = _require_project(session, actor, project_id, manage=True)
            source_task_id = payload.get("source_task_id")
            if source_task_id is not None:
                if not isinstance(source_task_id, str):
                    raise _error("invalid_request", "source_task_id 须为字符串。", 400)
                task = session.get(ProjectTask, source_task_id)
                if task is None or task.project_module is None:
                    raise _error("task_not_found", "来源任务不存在。", 404)
                if task.project_module.project_id != project.id:
                    raise _error("task_not_found", "来源任务不存在。", 404)
            requirements = session.scalars(
                select(Requirement)
                .where(Requirement.project_id == project.id, Requirement.status == "accepted")
                .order_by(Requirement.requirement_key)
            ).all()
            if not requirements:
                raise _error(
                    "no_approved_requirements",
                    "尚无已批准需求：先完成需求审阅再生成测试计划。",
                    409,
                )
            previous_version = session.scalar(
                select(TestPlan.version)
                .where(TestPlan.project_id == project.id)
                .order_by(TestPlan.version.desc())
                .limit(1)
            )
            plan = TestPlan(
                project_id=project.id,
                source_task_id=source_task_id,
                created_by_user_id=actor.id,
                title=f"测试计划 v{(previous_version or 0) + 1}",
                version=(previous_version or 0) + 1,
                status="draft",
            )
            session.add(plan)
            session.flush()
            # 条目序按 requirement_key 字典序（确定性；#209 教训）
            for sort_order, requirement in enumerate(requirements):
                session.add(TestCase(
                    plan_id=plan.id,
                    project_id=project.id,
                    created_by_user_id=actor.id,
                    case_key=f"TC-{uuid4().hex[:8]}",
                    title=f"验证：{requirement.title}",
                    preconditions=None,
                    steps=[],
                    expected="；".join(requirement.acceptance_criteria or [])[:2000] or None,
                    risk_level=_PRIORITY_TO_RISK.get(requirement.priority, 2),
                    automated=False,
                    acceptance_mode="test",
                    requirement_key=requirement.requirement_key,
                    sort_order=sort_order,
                ))
            session.add(OperationEvent(
                actor_user_id=actor.id,
                project_id=plan.project_id,
                target_type="test_plan",
                target_id=plan.id,
                event_type="test_plan_generated",
                changes={"version": plan.version, "case_count": len(requirements)},
            ))
            session.flush()
            return {"plan": serialize_plan(session, plan), "created": True}
    finally:
        session.close()


# ---------------------------------------------------------------------------
# 审阅（覆盖闸 + 退位）


def review_test_plan(*, actor, plan_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    """审阅（can_manage）：approved（覆盖闸+旧 approved 退位）/rejected→superseded。"""
    from fde_api.discovery.models import Requirement

    decision = payload.get("decision")
    if decision not in ("approved", "rejected"):
        raise _error("invalid_request", "decision 须为 approved 或 rejected。", 400)
    comment = payload.get("comment")
    if comment is not None and (not isinstance(comment, str) or len(comment) > 500):
        raise _error("invalid_request", "comment 须为 ≤500 字符字符串。", 400)
    session = db.session()
    try:
        with session.begin():
            plan = _load_plan(session, actor, plan_id, manage=True)
            if plan.status != "draft":
                raise _error("not_reviewable", "仅 draft 计划可审阅。", 409)
            if decision == "approved":
                # 覆盖闸：本计划 + 既有 approved 计划的用例并集须覆盖全部 accepted 需求
                accepted_keys = set(session.scalars(
                    select(Requirement.requirement_key).where(
                        Requirement.project_id == plan.project_id, Requirement.status == "accepted"
                    )
                ))
                covered_keys = set(session.scalars(
                    select(TestCase.requirement_key)
                    .join(TestPlan, TestCase.plan_id == TestPlan.id)
                    .where(
                        TestPlan.project_id == plan.project_id,
                        TestPlan.status == "approved",
                    )
                )) | set(session.scalars(
                    select(TestCase.requirement_key).where(TestCase.plan_id == plan.id)
                ))
                missing = sorted(accepted_keys - covered_keys)
                if missing:
                    raise _error(
                        "requirement_coverage_incomplete",
                        "每条批准需求至少需要一条测试用例或明确人工验收方式。",
                        409,
                        {"missing_requirement_keys": missing},
                    )
            # 审核戳两分支同打（驳回也是一次审阅）；须在退位循环前落——该查询
            # autoflush 会提前 flush 本行，approved+无戳撞 ck_test_plans_review_stamp
            plan.reviewed_by_user_id = actor.id
            plan.reviewed_at = datetime.now(UTC)
            plan.review_comment = (comment or "").strip() or None
            if decision == "approved":
                plan.status = "approved"
                # 双点退位：新 approved 使旧 approved 退位 superseded（历史行不覆盖）
                for other in session.scalars(
                    select(TestPlan).where(
                        TestPlan.project_id == plan.project_id,
                        TestPlan.status == "approved",
                        TestPlan.id != plan.id,
                    )
                ):
                    other.status = "superseded"
            else:
                plan.status = "superseded"
            session.add(OperationEvent(
                actor_user_id=actor.id,
                project_id=plan.project_id,
                target_type="test_plan",
                target_id=plan.id,
                event_type="test_plan_reviewed",
                changes={"decision": decision, "status": plan.status},
            ))
            session.flush()
            return {"plan": serialize_plan(session, plan)}
    finally:
        session.close()


# ---------------------------------------------------------------------------
# 执行登记（append-only）


def execute_test_plan(*, actor, plan_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    """登记执行结果（can_manage；append-only，重跑=新行）。

    payload：{environment, executions: [{case_id, result, started_at?, finished_at?,
    report_uri?, report_sha256?, note?}]}；单事务全成全败（沿 discovery 批量先例）。
    """
    environment = payload.get("environment")
    if environment not in EXECUTION_ENVIRONMENTS:
        raise _error(
            "invalid_request",
            f"environment 须为 {'/'.join(EXECUTION_ENVIRONMENTS)}。",
            400,
        )
    if environment == "production":
        raise _error(
            "production_forbidden",
            "生产环境测试默认禁止：先在 dev/staging 完成验证（显式放行属后续拍板项）。",
            409,
        )
    executions = payload.get("executions")
    if not isinstance(executions, list) or not executions:
        raise _error("invalid_request", "executions 须为非空数组。", 400)
    if len(executions) > 100:
        raise _error("invalid_request", "单次最多登记 100 条执行。", 400)
    for row in executions:
        if not isinstance(row, dict) or set(row) - _EXECUTION_FIELDS:
            raise _error("invalid_request", "executions 行字段无效。", 400)
        if not isinstance(row.get("case_id"), str) or not row["case_id"].strip():
            raise _error("invalid_request", "case_id 必填。", 400)
        if row.get("result") not in EXECUTION_RESULTS:
            raise _error(
                "invalid_request",
                f"result 须为 {'/'.join(EXECUTION_RESULTS)}。",
                400,
            )
        for pointer in ("report_uri", "report_sha256"):
            value = row.get(pointer)
            if value is not None and (not isinstance(value, str) or not value.strip()):
                raise _error("invalid_request", f"{pointer} 须为非空字符串。", 400)
        if (row.get("report_uri") is None) != (row.get("report_sha256") is None):
            raise _error("invalid_request", "report_uri 与 report_sha256 须成对提供。", 400)
    session = db.session()
    try:
        with session.begin():
            plan = _load_plan(session, actor, plan_id, manage=True)
            if plan.status != "approved":
                raise _error("not_executable", "仅 approved 计划可登记执行。", 409)
            created = []
            for row in executions:
                case = session.get(TestCase, row["case_id"].strip())
                if case is None or case.plan_id != plan.id:
                    raise _error("case_not_found", f"用例不存在或不属于该计划：{row['case_id']}。", 404)
                execution = TestExecution(
                    plan_id=plan.id,
                    case_id=case.id,
                    project_id=plan.project_id,
                    executed_by_user_id=actor.id,
                    environment=environment,
                    result=row["result"],
                    started_at=_parse_ts(row.get("started_at")),
                    finished_at=_parse_ts(row.get("finished_at")),
                    report_uri=(row.get("report_uri") or "").strip() or None,
                    report_sha256=(row.get("report_sha256") or "").strip() or None,
                    note=(row.get("note") or "").strip() or None,
                )
                session.add(execution)
                session.flush()
                created.append({
                    "execution_id": execution.id,
                    "case_id": case.id,
                    "case_key": case.case_key,
                    "result": execution.result,
                })
            session.add(OperationEvent(
                actor_user_id=actor.id,
                project_id=plan.project_id,
                target_type="test_plan",
                target_id=plan.id,
                event_type="test_plan_executed",
                changes={"environment": environment, "created": len(created)},
            ))
            session.flush()
            return {"created": created, "environment": environment, "count": len(created)}
    finally:
        session.close()


def _parse_ts(value: object) -> datetime | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise _error("invalid_request", "时间戳须为 ISO8601 字符串。", 400)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise _error("invalid_request", "时间戳格式无效。", 400) from error
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


# ---------------------------------------------------------------------------
# 读面与序列化


def get_plan(*, actor, plan_id: str) -> dict[str, Any]:
    session = db.session()
    try:
        with session.begin():
            plan = _load_plan(session, actor, plan_id, manage=False)
            return serialize_plan(session, plan)
    finally:
        session.close()


def list_plans(*, actor, project_id: str, task_id: str | None = None, limit: int = 50) -> dict[str, Any]:
    session = db.session()
    try:
        with session.begin():
            _require_project(session, actor, project_id, manage=False)
            stmt = select(TestPlan).where(TestPlan.project_id == project_id)
            if task_id:
                stmt = stmt.where(TestPlan.source_task_id == task_id)
            rows = session.scalars(stmt.order_by(TestPlan.created_at.desc(), TestPlan.id.desc()).limit(limit)).all()
            return {"items": [serialize_plan(session, row) for row in rows], "limit": limit}
    finally:
        session.close()


def get_execution(*, actor, execution_id: str) -> dict[str, Any]:
    session = db.session()
    try:
        with session.begin():
            execution = session.get(TestExecution, execution_id)
            if execution is None:
                raise _error("execution_not_found", "执行记录不存在。", 404)
            _require_project(session, actor, execution.project_id, manage=False)
            return {"execution": serialize_execution(execution)}
    finally:
        session.close()


def serialize_plan(session: Session, plan: TestPlan) -> dict[str, Any]:
    cases = session.scalars(
        select(TestCase)
        .where(TestCase.plan_id == plan.id)
        .order_by(TestCase.sort_order, TestCase.case_key)
    ).all()
    return {
        "id": plan.id,
        "project_id": plan.project_id,
        "source_task_id": plan.source_task_id,
        "title": plan.title,
        "version": plan.version,
        "status": plan.status,
        "created_by_user_id": plan.created_by_user_id,
        "reviewed_by_user_id": plan.reviewed_by_user_id,
        "reviewed_at": plan.reviewed_at.isoformat() if plan.reviewed_at else None,
        "review_comment": plan.review_comment,
        "cases": [{
            "id": case.id,
            "case_key": case.case_key,
            "title": case.title,
            "preconditions": case.preconditions,
            "steps": case.steps or [],
            "expected": case.expected,
            "risk_level": case.risk_level,
            "automated": case.automated,
            "acceptance_mode": case.acceptance_mode,
            "requirement_key": case.requirement_key,
            "sort_order": case.sort_order,
        } for case in cases],
        "case_count": len(cases),
    }


def serialize_execution(execution: TestExecution) -> dict[str, Any]:
    return {
        "id": execution.id,
        "plan_id": execution.plan_id,
        "case_id": execution.case_id,
        "project_id": execution.project_id,
        "executed_by_user_id": execution.executed_by_user_id,
        "environment": execution.environment,
        "result": execution.result,
        "started_at": execution.started_at.isoformat() if execution.started_at else None,
        "finished_at": execution.finished_at.isoformat() if execution.finished_at else None,
        "report_uri": execution.report_uri,
        "report_sha256": execution.report_sha256,
        "note": execution.note,
        "created_at": execution.created_at.isoformat() if execution.created_at else None,
    }

