"""Reconciliation for background jobs whose worker died.

The failure this closes
-----------------------
A worker pops a job id off the redis list and is then killed (OOM, deploy,
container restart). The job row keeps whatever state the claim left behind
and **nobody re-enqueues it**: the outbox event is already ``dispatched`` (the
dispatcher never looks at it again) and the redis entry died with the pop.
The business row (a guidance analysis, a chat turn) then stays in
``extracting``/``analyzing``/``running`` forever, and the UI — which polls
every two seconds — polls until the heat death of the universe. The only
cure used to be a hand-written ``RPUSH fde-jobs <id>``.

What the sweep does
-------------------
``reconcile_jobs`` finds the two shapes of "nobody is working on this any
more" and gives each one an owner again:

* ``running`` with an **expired lease** — the worker died holding the claim.
  The lease is renewed while a handler runs (see ``jobs/worker.py``), so an
  expired lease is a death signal, not a slow-job signal;
* ``pending``/``queued`` that nobody picked up for ``ORPHAN_GRACE_SECONDS`` —
  the queue entry was lost before anybody claimed it.

Each candidate is then either **re-queued** (the job type is declared
recoverable) or **failed** (it is not, or it ran out of attempts). Failing is
not the silent half: the business row is pushed to a terminal state through
the registered failure hook, so the UI stops polling and the user sees why.

What is deliberately *not* done
------------------------------
* Re-delivery is never blind. Every handler of a recoverable type already
  skips a business row that reached a terminal state, so a re-run does not
  overwrite a finished result with a second AI call.
* ``automation.execute`` is **not** recoverable: it has external side
  effects (mail, MCP calls). A dead automation run is failed and left for a
  human to re-trigger.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from fde_api.jobs.handlers import get_job_failure_handler
from fde_api.jobs.models import BackgroundJob
from fde_api.jobs.outbox import mark_failed, utcnow

logger = logging.getLogger(__name__)

# A queued/pending job nobody picked up for this long is considered orphaned.
# It has to be comfortably larger than the normal queue latency (seconds) and
# smaller than the "user gives up" threshold.
ORPHAN_GRACE_SECONDS = 300

# Job types that may run again after their worker died. The list is explicit
# on purpose: re-running is a semantic decision per type, not a default.
#
#   project.presurvey.analyze — the analysis is the whole point; its handler
#     skips an analysis that already reached ready/cancelled/failed, so a
#     re-run only happens when the first attempt died mid-flight.
#   ai.chat — a turn stuck in `running` blocks the whole conversation
#     (create_turn refuses a second queued turn), so a stuck turn is worse
#     than a possible duplicate answer.
#   ai.execute — the execution state lives in redis with a TTL; re-running
#     resumes it, and a terminal execution is skipped by the handler.
#   file.scan / file.preview / document.generate — idempotent by construction
#     (terminal file versions and already-generated documents are skipped).
#   research.export — the export row is regenerated from the same request.
#   translator.translate — goal-d9：handler 对 ready/failed 幂等跳过（预调研
#     分析同款语义），重跑只发生在首次尝试中途死亡时。
#   workflow.run — V3 T-W3：节点产物先行落表（succeeded 即恢复锚点），重跑只
#     处理未完成节点；写类 call 节点带 api_execute 同构幂等键，恢复不二次外呼。
#
# automation.execute is intentionally absent: it talks to the outside world.
RECOVERABLE_JOB_TYPES = frozenset({
    "project.presurvey.analyze",
    "ai.chat",
    "ai.execute",
    "file.scan",
    "file.preview",
    "file.upload.cleanup",
    "document.generate",
    "research.export",
    "translator.translate",
    "workflow.run",
})

# Written to `last_error` when a job is given up on, so an operator can tell
# "the worker died" from "the handler raised".
WORKER_LOST_ERROR = "worker_lost"

# How many candidates one sweep looks at.
RECONCILE_LIMIT = 100

# T-J2：due 重投的迟滞窗。退避到期的重试行（queued + available_at 已过）
# 由本 sweep 补投 redis；短窗把「刚 requeue、条目已在 redis 里」的正常行
# 挡在门外（requeue 落库即投递），只有退避等待行才需要它。投递语义是
# at-least-once：重复条目由 claim 侧 already_terminal/not_due 守卫消化。
DUE_REQUEUE_DELAY_SECONDS = 10


@dataclass(frozen=True, slots=True)
class ReconcileResult:
    """What one sweep did."""

    scanned: int
    requeued: int
    failed: int
    # T-J2：退避到期行的 redis 补投数（行不动，只投递）。
    due_enqueued: int = 0

    @property
    def changed(self) -> int:
        return self.requeued + self.failed


def reconcile_jobs(
    session: Session,
    queue: object,
    *,
    now: datetime | None = None,
    limit: int = RECONCILE_LIMIT,
) -> ReconcileResult:
    """Give orphaned jobs an owner again: re-queue them, or fail them.

    ``queue`` only needs an ``enqueue(job_id)`` method (the redis list queue
    has one). Jobs are enqueued *after* the database commit: a queue entry
    that is lost in between is picked up by the next sweep, while a database
    row that never got committed would leave a queue entry pointing at
    nothing.
    """
    current = now or utcnow()
    grace_cutoff = current - timedelta(seconds=ORPHAN_GRACE_SECONDS)
    # due 面下限：晚于孤儿宽限线（与孤儿 shape 不相交）、早于迟滞窗
    # （刚 requeue 的行已投递，不重复投）。
    due_floor = current - timedelta(seconds=DUE_REQUEUE_DELAY_SECONDS)
    requeue_ids: list[str] = []
    due_ids: list[str] = []
    failed = 0
    requeued = 0
    scanned = 0
    try:
        candidates = list(session.scalars(
            select(BackgroundJob)
            # 陈旧身份映射防护（_settle 的 populate_existing 同款）：调用方
            # session 里若残留本行的旧实例（如同事务早前读过的 pending 态），
            # 普通 SELECT 会把行解析到旧实例上，per-row 判定读到内存陈值
            # 走错分支。execution_options 写法兼容 1.4/2.0。
            .execution_options(populate_existing=True)
            .where(
                or_(
                    and_(
                        BackgroundJob.status == "running",
                        or_(
                            BackgroundJob.locked_until.is_(None),
                            BackgroundJob.locked_until < current,
                        ),
                    ),
                    and_(
                        BackgroundJob.status.in_(("pending", "queued")),
                        BackgroundJob.available_at < grace_cutoff,
                    ),
                    # T-J2：退避到期的重试行——redis 条目从未投出（run_job
                    # 的重试分支只落库不投递），这里补投。
                    and_(
                        BackgroundJob.status == "queued",
                        BackgroundJob.available_at < due_floor,
                        BackgroundJob.available_at >= grace_cutoff,
                    ),
                )
            )
            .order_by(BackgroundJob.created_at, BackgroundJob.id)
            # 正在被 worker 处理的行被行锁占着：跳过它，不要等它。
            .with_for_update(skip_locked=True)
            .limit(limit)
        ))
        scanned = len(candidates)
        for job in candidates:
            # due 面：退避到期且仍在迟滞窗内的 queued 行——只补投不改行。
            # 可恢复性在重试分支落库时已判过，这里不再二次淘汰。
            is_due = (
                job.status == "queued"
                and job.available_at < due_floor
                and job.available_at >= grace_cutoff
            )
            if is_due:
                due_ids.append(job.id)
                continue
            if job.attempts >= job.max_attempts:
                _fail_job(session, job, "attempts_exhausted")
                failed += 1
                continue
            if job.job_type not in RECOVERABLE_JOB_TYPES:
                _fail_job(session, job, "not_recoverable")
                failed += 1
                continue
            job.status = "queued"
            job.locked_until = None
            job.locked_by = None
            job.available_at = current
            requeue_ids.append(job.id)
            requeued += 1
        session.commit()
    except Exception:
        session.rollback()
        raise

    for job_id in requeue_ids:
        queue.enqueue(job_id)  # type: ignore[attr-defined]
    for job_id in due_ids:
        queue.enqueue(job_id)  # type: ignore[attr-defined]
    if requeued or failed or due_ids:
        logger.warning(
            "job reconciliation requeued=%s failed=%s due=%s scanned=%s",
            requeued, failed, len(due_ids), scanned,
        )
    return ReconcileResult(
        scanned=scanned, requeued=requeued, failed=failed, due_enqueued=len(due_ids)
    )


def _fail_job(session: Session, job: BackgroundJob, reason: str) -> None:
    """Give up on a job and close out its business row.

    The business row matters as much as the job row: the UI polls the
    business row, not the job. Without the hook the task would keep polling
    forever even though the job is now terminal.
    """
    job.status = "failed"
    job.locked_until = None
    job.locked_by = None
    job.last_error = f"{WORKER_LOST_ERROR}:{reason}"
    # T-J1（WB-DEF-9）：worker 失联终失败同样收口派生 outbox 事件——
    # 与 worker._settle 同一把 (job_type, target_id) 键。
    mark_failed(session, job.job_type, job.target_id, job.last_error)
    handler = get_job_failure_handler(job.job_type)
    if handler is None:
        return
    try:
        handler(session, job)
    except Exception:  # noqa: BLE001 - the job must still reach its terminal state
        logger.warning(
            "job failure hook failed job_type=%s job_id=%s",
            job.job_type, job.id, exc_info=True,
        )
