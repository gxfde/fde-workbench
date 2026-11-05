"""Admin 取消面：POST /api/v1/admin/jobs/{id}/cancel（V3 T-J2，域 14）。

语义（gap-matrix 域 14 验收口径）：
- **幂等**：已取消的行再取消 → 200 ``cancelled=false``（workflow cancel
  同款）；succeeded/failed → 409 ``already_terminal``。
- **不强杀**：running 且租约未过期 → 409 ``job_running``——线程杀不掉，
  强行落终态只会让 handler 白烧外呼（AI token / 邮件）而结果被丢弃；
  运营者的正确动作是停掉 worker 容器等租约过期。租约**已过期** =
  worker 已死（续租线程活着租约就不会过期），此时取消是安全接管，
  迟到 settle 会被 ``_settle`` 的终态守卫拒绝。
- **留痕**：admin 门 + operation_events ``job_cancelled``（changes 只含
  job_type/target_id/previous_status，E7 纪律：审计只落元数据）。
- **不复活**：同 job 的 outbox 未决事件（pending+dispatched）一并收口，
  否则下一轮 dispatch 会为同键新建 job，已取消的工作被复活；取消之后
  新提交的事件照常新建 job，属合法新工作（见 outbox.cancel_for_job）。

不进 api_catalog：平台运维面，非 AI 可调用能力（evidence/本体治理同款
边界）。零桌面改动。
"""

from __future__ import annotations

from typing import Any

from flask import Blueprint, g, jsonify

from fde_api.auth.decorators import require_auth
from fde_api.auth.models import User
from fde_api.extensions import db
from fde_api.jobs.models import BackgroundJob
from fde_api.jobs.outbox import cancel_for_job, utcnow
from fde_api.workbench.models import OperationEvent

admin_jobs_blueprint = Blueprint("admin_jobs", __name__, url_prefix="/api/v1/admin/jobs")

CANCELLED_BY_ADMIN = "cancelled_by_admin"


class AdminJobsServiceError(Exception):
    def __init__(
        self,
        code: str,
        message: str,
        status: int,
        detail: dict[str, Any] | None = None,
    ):
        super().__init__(message)
        self.code, self.message, self.status = code, message, status
        self.detail = detail or {}


def _error(
    code: str, message: str, status: int = 400, detail: dict[str, Any] | None = None
) -> AdminJobsServiceError:
    return AdminJobsServiceError(code, message, status, detail)


@admin_jobs_blueprint.errorhandler(AdminJobsServiceError)
def _handle_service_error(error: AdminJobsServiceError):
    return (
        jsonify(
            {
                "data": None,
                "error": {
                    "code": error.code,
                    "message": error.message,
                    "details": error.detail or None,
                },
            }
        ),
        error.status,
    )


def cancel_job(*, actor: User, job_id: str) -> dict[str, Any]:
    """取消一个后台 job（admin，幂等；运行中不强杀，同事务收口三面：
    job 行 → 派生 outbox 事件 → operation_events 留痕）。"""
    if actor.role != "admin":
        raise _error("job_cancel_forbidden", "后台任务取消仅系统运维员可用。", 403)
    with db.session() as session, session.begin():
        job = session.get(BackgroundJob, job_id, with_for_update=True)
        if job is None:
            raise _error("job_not_found", "后台任务不存在或已被清理。", 404)
        view = {
            "job_id": job.id,
            "job_type": job.job_type,
            "target_id": job.target_id,
        }
        if job.status == "cancelled":
            # 幂等：重复取消不是错误（workflow cancel 同款 cancelled=false）。
            return {**view, "status": job.status, "cancelled": False}
        if job.status in ("succeeded", "failed"):
            raise _error(
                "already_terminal",
                "后台任务已到达成功/失败终态，不能取消。",
                409,
                detail={"status": job.status},
            )
        if (
            job.status == "running"
            and job.locked_until is not None
            and job.locked_until > utcnow()
        ):
            raise _error(
                "job_running",
                "后台任务正在执行中（租约未过期），不强行终止；"
                "如需停止请先停掉 worker，待租约过期后再取消。",
                409,
                detail={"locked_until": job.locked_until.isoformat()},
            )
        previous_status = job.status
        job.status = "cancelled"
        job.locked_until = None
        job.locked_by = None
        job.last_error = CANCELLED_BY_ADMIN
        closed = cancel_for_job(session, job.job_type, job.target_id, CANCELLED_BY_ADMIN)
        session.add(
            OperationEvent(
                actor_user_id=actor.id,
                project_id=None,
                target_type="background_job",
                target_id=job.id,
                event_type="job_cancelled",
                changes={
                    "job_type": job.job_type,
                    "target_id": job.target_id,
                    "previous_status": previous_status,
                    "outbox_closed": closed,
                },
            )
        )
        # status 用取消后的终态回显（view 在 mutate 前构建，不能透传旧值）
        return {**view, "status": "cancelled", "cancelled": True}


@admin_jobs_blueprint.post("/<job_id>/cancel")
@require_auth
def cancel_job_route(job_id: str):
    """取消后台 job（admin，幂等；运行中不强杀，见模块 docstring）。"""
    return jsonify(
        {"data": cancel_job(actor=g.current_user, job_id=job_id), "error": None}
    )
