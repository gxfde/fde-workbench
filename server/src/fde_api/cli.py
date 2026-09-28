from __future__ import annotations

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
        from fde_api.jobs.outbox import dispatch_pending
        from fde_api.jobs.queue import get_queue

        session = db.session()
        try:
            result = dispatch_pending(session, get_queue(), limit=limit)
            click.echo(f"dispatched={result.dispatched}")
        finally:
            session.close()

    @app.cli.command("worker")
    @click.option("--once", is_flag=True, help="Process a single job with a short wait.")
    def worker(once: bool) -> None:
        from fde_api.jobs.outbox import dispatch_pending
        from fde_api.jobs.queue import get_queue
        from fde_api.jobs.worker import run_job

        queue = get_queue()
        click.echo("worker started")
        while True:
            # Keep local/desktop deployments self-contained: the worker also
            # dispatches newly committed outbox events before waiting for work.
            dispatch_session = db.session()
            try:
                dispatch_pending(dispatch_session, queue, limit=100)
            finally:
                dispatch_session.close()
            job_id = queue.dequeue(timeout=1 if once else 5)
            if job_id is None:
                if once:
                    return
                continue
            click.echo(f"processing job {job_id}")
            run_job(job_id)

    @app.cli.command("scheduler")
    @click.option("--once", is_flag=True, help="Dispatch due tasks once and exit.")
    @click.option("--interval", default=30, type=click.IntRange(5, 300), show_default=True)
    def scheduler(once: bool, interval: int) -> None:
        from fde_api.control.scheduler import dispatch_due_automations

        click.echo("scheduler started")
        while True:
            dispatched = dispatch_due_automations()
            if dispatched:
                click.echo(f"dispatched={dispatched}")
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
