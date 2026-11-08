from __future__ import annotations

import logging
import os
import time

import click
from flask import Flask
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from fde_api.auth.models import ROLE_ADMIN, User
from fde_api.auth.passwords import hash_password
from fde_api.auth.service import (
    AuthServiceError,
    validate_username,
    validate_password_strength,
)
from fde_api.extensions import db
from fde_api.workbench.models import ModuleCatalog
from fde_api.workbench.seed import seed_workbench

logger = logging.getLogger(__name__)

# How often the worker sweeps for jobs whose owner died.
RECONCILE_INTERVAL_SECONDS = 60


def register_cli(app: Flask) -> None:
    @app.cli.command("bootstrap-open-source")
    def bootstrap_open_source_command() -> None:
        """Create only generic catalog data and the forced-change initial admin."""
        from fde_api.control.builtin_skills import seed_public_skills
        from fde_api.documents.template_service import (
            SYSTEM_USERNAME,
            seed_document_templates,
        )

        session = db.session()
        try:
            with session.begin():
                seed_workbench(session)
                seed_document_templates(session)
                # seed_document_templates inserts the `system` seed user first and
                # that account carries an empty password hash, so it can never log
                # in. Counting it here would make the initial admin unreachable on
                # a fresh database, leaving the deployment without any usable login.
                existing_users = int(
                    session.scalar(
                        select(func.count())
                        .select_from(User)
                        .where(User.username != SYSTEM_USERNAME)
                    )
                    or 0
                )
                if existing_users == 0:
                    session.add(User(username="admin", display_name="系统管理员", role=ROLE_ADMIN,
                                     password_hash=hash_password("ChangeMe123!"), must_change_password=True, is_active=True))
            skills_created = seed_public_skills()
            click.echo(f"bootstrap_complete initial_admin_created={existing_users == 0} public_skills_created={skills_created}")
            if existing_users == 0:
                click.echo("Initial login: admin / ChangeMe123! (password change is required immediately)")
        finally:
            session.close()

    @app.cli.command("seed-public-skills")
    def seed_public_skills_command() -> None:
        from fde_api.control.builtin_skills import seed_public_skills
        click.echo(f"public_skills_created={seed_public_skills()}")

    @app.cli.command("seed-workflow-templates")
    def seed_workflow_templates_command() -> None:
        """V3.1 P0-4：平台工作流模板幂等落库（先 seed-public-skills——模板引用 published 技能）。"""
        from fde_api.workflows.templates import seed_workflow_templates
        from fde_api.workflows.definition_service import WorkflowDefinitionError

        session = db.session()
        try:
            with session.begin():
                result = seed_workflow_templates(session)
            click.echo(f"workflow_templates_created={result['created']} total={result['total']}")
        except WorkflowDefinitionError as error:
            raise click.ClickException(
                f"{error.code}: {error.message}（部署顺序：先 seed-public-skills 再 seed-workflow-templates）"
            ) from None
        finally:
            session.close()

    @app.cli.command("seed-default-models")
    def seed_default_models_command() -> None:
        from fde_api.control.builtin_skills import seed_default_models
        click.echo(f"public_models_created={seed_default_models()}")

    @app.cli.command("sync-dsh-market")
    def sync_dsh_market_command() -> None:
        from fde_api.control.dsh_market import sync_dsh_market_scheduled
        from fde_api.control.service import ControlServiceError

        try:
            result = sync_dsh_market_scheduled()
        except ControlServiceError as error:
            raise click.ClickException(error.message) from None
        click.echo(
            "source={} status={} plugins={} registry_updated={}".format(
                result["source"], result["status"], result["plugin_count"], result["registry_updated"]
            )
        )

    @app.cli.command("seed-workbench")
    def seed_workbench_command() -> None:
        session = db.session()
        try:
            with session.begin():
                before_count = int(
                    session.scalar(select(func.count()).select_from(ModuleCatalog)) or 0
                )
                seed_workbench(session)
                after_count = int(
                    session.scalar(select(func.count()).select_from(ModuleCatalog)) or 0
                )
            click.echo(f"modules_created={after_count - before_count}")
        finally:
            session.close()

    @app.cli.command("seed-document-templates")
    def seed_document_templates_command() -> None:
        from fde_api.documents.template_service import seed_document_templates

        session = db.session()
        try:
            with session.begin():
                result = seed_document_templates(session)
            click.echo(
                "created={} skipped={} missing={}".format(
                    len(result["created"]),
                    len(result["skipped"]),
                    len(result["missing"]),
                )
            )
            if result["missing"]:
                click.echo("missing_sources={}".format(",".join(result["missing"])))
        finally:
            session.close()

    @app.cli.command("outbox-dispatch")
    @click.option("--limit", default=100, type=int, show_default=True)
    def outbox_dispatch(limit: int) -> None:
        from fde_api.jobs.handlers import ensure_default_handlers
        from fde_api.jobs.outbox import dispatch_pending
        from fde_api.jobs.queue import get_queue

        # 模块导入期的自动注册可能被循环导入吞掉（见 handlers.py 尾部日志）；
        # worker 入口显式补注册，保证任务不会全部 no_handler。
        ensure_default_handlers()

        session = db.session()
        try:
            result = dispatch_pending(session, get_queue(), limit=limit)
            click.echo(f"dispatched={result.dispatched}")
        finally:
            session.close()

    @app.cli.command("worker")
    @click.option("--once", is_flag=True, help="Process a single job with a short wait.")
    def worker(once: bool) -> None:
        from fde_api.health.heartbeat import beat
        from fde_api.jobs.handlers import ensure_default_handlers
        from fde_api.jobs.outbox import dispatch_pending
        from fde_api.jobs.queue import get_queue
        from fde_api.jobs.worker import run_job

        # 同 outbox-dispatch：入口处显式补注册。
        ensure_default_handlers()

        queue = get_queue()
        click.echo("worker started")
        next_reconcile = time.monotonic() + RECONCILE_INTERVAL_SECONDS
        while True:
            # I4：循环每轮写一次心跳（TTL 180s）。卡住时心跳停止刷新，
            # 容器 healthcheck 判 unhealthy——「进程还在」不等于「还在干活」。
            beat("worker")
            # Keep local/desktop deployments self-contained: the worker also
            # dispatches newly committed outbox events before waiting for work.
            dispatch_session = db.session()
            try:
                dispatch_pending(dispatch_session, queue, limit=100)
            finally:
                dispatch_session.close()
            # 对账：worker 被杀（OOM/部署）时弹走的作业没人再投，outbox 已
            # dispatched 也不会再发。这里按固定周期把无主的作业捞回来。
            if time.monotonic() >= next_reconcile:
                next_reconcile = time.monotonic() + RECONCILE_INTERVAL_SECONDS
                _reconcile_jobs(queue)
            job_id = queue.dequeue(timeout=1 if once else 5)
            if job_id is None:
                if once:
                    return
                continue
            click.echo(f"processing job {job_id}")
            run_job(job_id)

    @app.cli.command("reconcile-jobs")
    @click.option("--limit", default=100, type=int, show_default=True)
    def reconcile_jobs_command(limit: int) -> None:
        """Re-queue or fail background jobs whose worker died.

        The worker runs this on a timer; the command is the operator's
        escape hatch (e.g. right after a container was killed).
        """
        from fde_api.jobs.handlers import ensure_default_handlers
        from fde_api.jobs.queue import get_queue
        from fde_api.jobs.reconcile import reconcile_jobs

        ensure_default_handlers()
        session = db.session()
        try:
            result = reconcile_jobs(session, get_queue(), limit=limit)
            click.echo(
                "scanned={} requeued={} failed={}".format(
                    result.scanned, result.requeued, result.failed
                )
            )
        finally:
            session.close()

    _MAINTENANCE_TYPE = "dispatch.maintenance"

    @app.cli.command("scheduler")
    @click.option("--once", is_flag=True, help="Dispatch due tasks once and exit.")
    @click.option("--interval", default=30, type=click.IntRange(5, 300), show_default=True)
    def scheduler(once: bool, interval: int) -> None:
        from fde_api.control.scheduler import (
            dispatch_due_automations,
            remind_pending_approvals,
            sweep_expired_approvals,
        )
        from fde_api.files.expiration import schedule_expired_upload_cleanup
        from fde_api.health.heartbeat import beat
        from fde_api.transcripts.service import purge_expired_drafts

        click.echo("scheduler started")
        from datetime import datetime as _dt

        from fde_api.dispatch.maintenance import maintenance_due
        from fde_api.extensions import db as _db
        from fde_api.jobs.outbox import enqueue_outbox

        while True:
            # I4：同 worker——每轮刷新心跳（TTL 900s，覆盖最大 300s 间隔）。
            beat("scheduler")
            dispatched = dispatch_due_automations()
            if dispatched:
                click.echo(f"dispatched={dispatched}")
            # V3 T-P1-5（WB-DEF-3）：过期审批后台清扫——与派单同拍，
            # 无人工触碰的过期 pending 也按时落 expired。
            expired_approvals = sweep_expired_approvals()
            if expired_approvals:
                click.echo(f"expired_approvals={expired_approvals}")
            # B#5 审批退避提醒：与过期清扫同拍（10m→1h→4h→24h 序列补发）
            approval_reminders = remind_pending_approvals()
            if approval_reminders:
                click.echo(f"approval_reminders={approval_reminders}")
            expired_uploads = schedule_expired_upload_cleanup()
            if expired_uploads:
                click.echo(f"expired_uploads={expired_uploads}")
            # T-A9（goal-tb tb1）：转写草稿 T+7 自动清理——与过期清扫同拍，
            # 无人触碰的到期草稿也按时墓碑化（正文/指纹/复核条目抹除+文件根清空）。
            purged_drafts = purge_expired_drafts()
            if purged_drafts:
                click.echo(f"purged_transcript_drafts={purged_drafts}")
            # goal-r6（P1-7）：派单维护作业 24h 节流到期即投递（超时释放 /
            # 留存扫描 / T+30 对账；topic 即 job_type=dispatch.maintenance，
            # target=当日 token 由 ensure_background_job 天然去重）。
            with _db.session() as _session:
                if maintenance_due(_session):
                    enqueue_outbox(
                        _session,
                        _MAINTENANCE_TYPE,
                        f"daily-{_dt.now():%Y%m%d}",
                        {},
                    )
                    _session.commit()
                    click.echo("dispatch-maintenance enqueued")
            if once:
                return
            time.sleep(interval)

    @app.cli.command("create-admin")
    @click.option("--username", required=True)
    @click.option("--display-name", required=True)
    def create_admin(username: str, display_name: str) -> None:
        initial_password = os.environ.get("FDE_INITIAL_ADMIN_PASSWORD")
        if not initial_password:
            raise click.ClickException(
                "FDE_INITIAL_ADMIN_PASSWORD must be set before creating an admin."
            )
        try:
            validate_password_strength(initial_password)
            normalized_username = validate_username(username)
        except AuthServiceError as error:
            raise click.ClickException(error.message) from None
        session = db.session()
        try:
            existing = session.scalar(
                select(User).where(User.username == normalized_username)
            )
            if existing is not None:
                if existing.role == ROLE_ADMIN and existing.is_active:
                    click.echo(f"Active admin '{normalized_username}' already exists.")
                    return
                raise click.ClickException(
                    f"User '{normalized_username}' already exists but is not an active admin."
                )

            session.add(
                User(
                    username=normalized_username,
                    display_name=display_name,
                    role=ROLE_ADMIN,
                    password_hash=hash_password(initial_password),
                    must_change_password=True,
                    is_active=True,
                )
            )
            session.commit()
            click.echo(f"Created active admin '{normalized_username}'.")
        except IntegrityError:
            session.rollback()
            winner = session.scalar(
                select(User).where(User.username == normalized_username)
            )
            if winner is not None and winner.role == ROLE_ADMIN and winner.is_active:
                click.echo(f"Active admin '{normalized_username}' already exists.")
                return
            raise click.ClickException(
                f"User '{normalized_username}' could not be created as an active admin."
            ) from None
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()


def _reconcile_jobs(queue: object) -> None:
    """One reconciliation sweep; never allowed to kill the worker loop."""
    from fde_api.jobs.reconcile import reconcile_jobs

    session = db.session()
    try:
        reconcile_jobs(session, queue)
    except Exception:  # noqa: BLE001 - a failed sweep must not stop the worker
        session.rollback()
        logger.warning("job reconciliation sweep failed", exc_info=True)
    finally:
        session.close()

