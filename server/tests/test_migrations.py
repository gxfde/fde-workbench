import os
import re
import subprocess
import sys
from importlib.util import module_from_spec, spec_from_file_location
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import DBAPIError

from conftest import SERVER_ROOT
from fde_api.research import models as research_models


def scalar(engine, statement, parameters=None):
    with engine.connect() as connection:
        return connection.execute(
            text(statement), parameters or {}
        ).scalar_one_or_none()


def table_names(engine):
    return set(inspect(engine).get_table_names())


def seed_minimal_project(engine, *, project_code):
    user_id = str(uuid4())
    template_id = str(uuid4())
    template_version_id = str(uuid4())
    project_id = str(uuid4())
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO users "
                "(id, username, display_name, role, password_hash, "
                "must_change_password, is_active, auth_version) "
                "VALUES (:id, :username, 'Migration Admin', 'admin', 'x', 0, 1, 1)"
            ),
            {"id": user_id, "username": f"migration.{project_code.lower()}"},
        )
        connection.execute(
            text(
                "INSERT INTO industry_templates "
                "(id, template_key, name, industry_name, description, status) "
                "VALUES (:id, :template_key, 'Migration template', 'Manufacturing', '', 'active')"
            ),
            {"id": template_id, "template_key": f"template_{template_id.replace('-', '')}"},
        )
        connection.execute(
            text(
                "INSERT INTO industry_template_versions "
                "(id, template_id, name, industry_name, description, version_number, status) "
                "VALUES (:id, :template_id, 'Migration template', 'Manufacturing', '', 1, 'draft')"
            ),
            {"id": template_version_id, "template_id": template_id},
        )
        connection.execute(
            text(
                "INSERT INTO projects "
                "(id, project_code, name, enterprise_name, background, notes, "
                "planned_start_date, leader_user_id, source_template_version_id, template_snapshot) "
                "VALUES (:id, :project_code, 'Retained project', 'Retained enterprise', '', '', "
                "'2026-08-22', :user_id, :template_version_id, JSON_OBJECT())"
            ),
            {
                "id": project_id,
                "project_code": project_code,
                "user_id": user_id,
                "template_version_id": template_version_id,
            },
        )


def seed_submitted_research_revision_at_0007(engine):
    ids = {
        key: str(uuid4())
        for key in (
            "user",
            "template",
            "template_version",
            "project",
            "template_form",
            "template_section",
            "template_field",
            "subject",
            "project_form",
            "revision",
            "answer",
        )
    }
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO users "
                "(id, username, display_name, role, password_hash, "
                "must_change_password, is_active, auth_version) "
                "VALUES (:id, :username, 'Roundtrip Admin', 'admin', 'x', 0, 1, 1)"
            ),
            {
                "id": ids["user"],
                "username": f"migration.roundtrip.{ids['user']}",
            },
        )
        connection.execute(
            text(
                "INSERT INTO industry_templates "
                "(id, template_key, name, industry_name, description, status) "
                "VALUES (:id, :template_key, 'Roundtrip template', "
                "'Manufacturing', '', 'active')"
            ),
            {
                "id": ids["template"],
                "template_key": f"template_{ids['template'].replace('-', '')}",
            },
        )
        connection.execute(
            text(
                "INSERT INTO industry_template_versions "
                "(id, template_id, name, industry_name, description, "
                "version_number, status) "
                "VALUES (:id, :template_id, 'Roundtrip template', "
                "'Manufacturing', '', 1, 'draft')"
            ),
            {"id": ids["template_version"], "template_id": ids["template"]},
        )
        connection.execute(
            text(
                "INSERT INTO projects "
                "(id, project_code, name, enterprise_name, background, notes, "
                "planned_start_date, leader_user_id, source_template_version_id, "
                "template_snapshot, research_snapshot) "
                "VALUES (:id, :project_code, 'Roundtrip project', "
                "'Roundtrip enterprise', '', '', '2026-08-22', :user_id, "
                ":template_version_id, JSON_OBJECT(), JSON_OBJECT())"
            ),
            {
                "id": ids["project"],
                "project_code": f"FDE-ROUNDTRIP-{ids['project'][:8]}",
                "user_id": ids["user"],
                "template_version_id": ids["template_version"],
            },
        )
        connection.execute(
            text(
                "INSERT INTO template_research_forms "
                "(id, template_version_id, form_key, name, description, "
                "subject_type, module_key, sort_order) "
                "VALUES (:id, :template_version_id, 'migration_form', "
                "'Migration form', '', 'project', NULL, 10)"
            ),
            {
                "id": ids["template_form"],
                "template_version_id": ids["template_version"],
            },
        )
        connection.execute(
            text(
                "INSERT INTO template_research_sections "
                "(id, form_id, section_key, name, description, sort_order) "
                "VALUES (:id, :form_id, 'context', 'Context', '', 10)"
            ),
            {"id": ids["template_section"], "form_id": ids["template_form"]},
        )
        connection.execute(
            text(
                "INSERT INTO template_research_fields "
                "(id, section_id, field_key, name, help_text, field_type, "
                "is_required, options_json, sort_order) "
                "VALUES (:id, :section_id, 'retained_field', 'Retained field', "
                "'', 'short_text', 1, JSON_OBJECT(), 10)"
            ),
            {"id": ids["template_field"], "section_id": ids["template_section"]},
        )
        connection.execute(
            text(
                "INSERT INTO project_research_subjects "
                "(id, project_id, subject_type, subject_key, name, description, "
                "sort_order, status, version) "
                "VALUES (:id, :project_id, 'project', 'migration_subject', "
                "'Migration subject', '', 10, 'active', 1)"
            ),
            {"id": ids["subject"], "project_id": ids["project"]},
        )
        connection.execute(
            text(
                "INSERT INTO project_research_forms "
                "(id, project_id, subject_id, source_template_research_form_id, "
                "form_key, name, description, current_revision_id, version) "
                "VALUES (:id, :project_id, :subject_id, :template_form_id, "
                "'migration_form', 'Migration form', '', NULL, 1)"
            ),
            {
                "id": ids["project_form"],
                "project_id": ids["project"],
                "subject_id": ids["subject"],
                "template_form_id": ids["template_form"],
            },
        )
        connection.execute(
            text(
                "INSERT INTO project_research_form_revisions "
                "(id, form_id, revision_number, status, parent_revision_id, "
                "version, definition_snapshot) "
                "VALUES (:id, :form_id, 1, 'submitted', NULL, 3, "
                "JSON_OBJECT('form_key', 'migration_form'))"
            ),
            {"id": ids["revision"], "form_id": ids["project_form"]},
        )
        connection.execute(
            text(
                "UPDATE project_research_forms SET current_revision_id = :revision_id "
                "WHERE id = :form_id"
            ),
            {"revision_id": ids["revision"], "form_id": ids["project_form"]},
        )
        connection.execute(
            text(
                "INSERT INTO project_research_answers "
                "(id, revision_id, source_template_research_field_id, field_key, "
                "value_json) VALUES (:id, :revision_id, :template_field_id, "
                "'retained_field', JSON_OBJECT('text', 'preserved', 'score', 7))"
            ),
            {
                "id": ids["answer"],
                "revision_id": ids["revision"],
                "template_field_id": ids["template_field"],
            },
        )
    return ids


def research_roundtrip_rows(engine, ids):
    with engine.connect() as connection:
        revision = connection.execute(
            text(
                "SELECT id, form_id, revision_number, status, version, "
                "JSON_UNQUOTE(JSON_EXTRACT(definition_snapshot, '$.form_key')) "
                "FROM project_research_form_revisions WHERE id = :id"
            ),
            {"id": ids["revision"]},
        ).one()
        answer = connection.execute(
            text(
                "SELECT id, revision_id, source_template_research_field_id, "
                "field_key, JSON_UNQUOTE(JSON_EXTRACT(value_json, '$.text')), "
                "CAST(JSON_UNQUOTE(JSON_EXTRACT(value_json, '$.score')) AS SIGNED) "
                "FROM project_research_answers WHERE id = :id"
            ),
            {"id": ids["answer"]},
        ).one()
    return tuple(revision), tuple(answer)


def test_research_migration_preserves_projects_and_adds_tables(alembic_config, engine):
    command.upgrade(alembic_config, "0005_add_template_key")
    seed_minimal_project(engine, project_code="FDE-KEEP")
    command.upgrade(alembic_config, "head")

    assert scalar(
        engine, "SELECT project_code FROM projects WHERE project_code='FDE-KEEP'"
    ) == "FDE-KEEP"
    assert scalar(
        engine,
        "SELECT JSON_UNQUOTE(JSON_EXTRACT(research_snapshot, '$')) "
        "FROM projects WHERE project_code='FDE-KEEP'",
    ) == "{}"
    research_snapshot = next(
        column
        for column in inspect(engine).get_columns("projects")
        if column["name"] == "research_snapshot"
    )
    assert research_snapshot["nullable"] is False
    assert research_snapshot["default"] is not None
    assert table_names(engine) >= {
        "template_research_forms",
        "project_research_subjects",
        "project_research_form_revisions",
    }


def test_research_snapshot_column_is_removed_and_restored_by_migration_cycle(
    alembic_config, engine
):
    command.downgrade(alembic_config, "0005_add_template_key")

    assert "research_snapshot" not in {
        column["name"] for column in inspect(engine).get_columns("projects")
    }

    command.upgrade(alembic_config, "head")

    restored = next(
        column
        for column in inspect(engine).get_columns("projects")
        if column["name"] == "research_snapshot"
    )
    assert restored["nullable"] is False
    assert restored["default"] is not None


def test_test_database_schema_is_at_alembic_head_via_percent_encoded_url(
    db_session, test_settings
):
    version = db_session.execute(text("SELECT version_num FROM alembic_version")).scalar_one()

    assert "%5F" in test_settings.database_url
    assert version == "0042_system_configuration"


def test_research_import_batch_receipt_schema_is_project_scoped(db_session):
    """Idempotency recovery requires one database-authored receipt per preview."""
    database = inspect(db_session.bind)
    columns = {
        column["name"]: column
        for column in database.get_columns("project_research_import_batches")
    }
    foreign_keys = database.get_foreign_keys("project_research_import_batches")

    assert set(columns) == {
        "id",
        "project_id",
        "subject_type",
        "expected_project_version",
        "committed_project_version",
        "result_json",
        "created_at",
        "updated_at",
    }
    assert all(columns[name]["nullable"] is False for name in columns)
    assert any(
        foreign_key["referred_table"] == "projects"
        and foreign_key["constrained_columns"] == ["project_id"]
        for foreign_key in foreign_keys
    )


def test_research_migration_field_type_contract_is_frozen_from_live_models(
    monkeypatch,
):
    """A later runtime field type must not rewrite a fresh 0006 database."""
    monkeypatch.setattr(research_models, "FIELD_TYPES", ("future_control",))
    monkeypatch.setattr(
        research_models,
        "FIELD_TYPE_CHECK_SQL",
        "field_type IN ('future_control')",
    )
    migration_path = SERVER_ROOT / "migrations/versions/0006_research_data.py"
    migration_spec = spec_from_file_location("research_migration_contract", migration_path)
    assert migration_spec is not None
    assert migration_spec.loader is not None
    migration = module_from_spec(migration_spec)
    migration_spec.loader.exec_module(migration)

    assert migration.FIELD_TYPES == (
        "short_text",
        "long_text",
        "rich_text",
        "integer",
        "decimal",
        "date",
        "single_choice",
        "multi_choice",
        "table",
        "file_reference",
    )
    assert migration.FIELD_TYPE_CHECK_SQL == (
        "field_type IN ('short_text', 'long_text', 'rich_text', 'integer', "
        "'decimal', 'date', 'single_choice', 'multi_choice', 'table', "
        "'file_reference')"
    )
    assert migration.FIELD_TYPE_DEFAULT == "short_text"


def test_alembic_metadata_matches_project_workbench_head(test_settings):
    environment = os.environ.copy()
    environment.update(
        {
            "FDE_ENV": "test",
            "FDE_DATABASE_URL": test_settings.database_url,
            "FDE_REDIS_URL": test_settings.redis_url,
            "FDE_JWT_SECRET": test_settings.jwt_secret,
        }
    )

    result = subprocess.run(
        [sys.executable, "-m", "alembic", "check"],
        cwd=SERVER_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "SAWarning" not in result.stderr


def test_template_definition_foreign_keys_are_restrict(db_session):
    database = inspect(db_session.bind)
    expected_parent_columns = {
        "template_modules": "template_version_id",
        "template_tasks": "template_module_id",
        "template_task_dependencies": "predecessor_task_id",
    }

    for table_name, constrained_column in expected_parent_columns.items():
        foreign_keys = database.get_foreign_keys(table_name)
        matching = [
            foreign_key
            for foreign_key in foreign_keys
            if foreign_key["constrained_columns"] == [constrained_column]
        ]
        assert len(matching) == 1
        assert matching[0]["options"].get("ondelete") == "RESTRICT"

    successor_foreign_key = next(
        foreign_key
        for foreign_key in database.get_foreign_keys("template_task_dependencies")
        if foreign_key["constrained_columns"] == ["successor_task_id"]
    )
    assert successor_foreign_key["options"].get("ondelete") == "RESTRICT"


def test_project_workbench_migration_preserves_existing_user(test_settings):
    config = Config(str(SERVER_ROOT / "alembic.ini"))
    config.attributes["settings"] = test_settings
    engine = create_engine(test_settings.database_url)
    user_id = str(uuid4())
    refresh_session_id = str(uuid4())
    token_digest = uuid4().hex * 2

    try:
        command.downgrade(config, "0002_add_user_auth_version")
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO users "
                    "(id, username, display_name, role, password_hash, "
                    "must_change_password, is_active, auth_version) "
                    "VALUES (:id, 'migration.admin', 'Migration Admin', 'admin', "
                    "'x', 0, 1, 1)"
                ),
                {"id": user_id},
            )
            connection.execute(
                text(
                    "INSERT INTO refresh_sessions "
                    "(id, user_id, token_digest, expires_at, device_label) "
                    "VALUES (:id, :user_id, :token_digest, "
                    "DATE_ADD(UTC_TIMESTAMP(), INTERVAL 1 DAY), 'Migration Mac')"
                ),
                {
                    "id": refresh_session_id,
                    "user_id": user_id,
                    "token_digest": token_digest,
                },
            )

        command.upgrade(config, "head")

        with engine.connect() as connection:
            username = connection.execute(
                text(
                    "SELECT username FROM users "
                    "WHERE username = 'migration.admin'"
                )
            ).scalar_one()
            refresh_session_count = connection.execute(
                text(
                    "SELECT COUNT(*) FROM refresh_sessions "
                    "WHERE id = :refresh_session_id AND user_id = :user_id"
                ),
                {"refresh_session_id": refresh_session_id, "user_id": user_id},
            ).scalar_one()
            table_names = set(inspect(connection).get_table_names())

        assert username == "migration.admin"
        assert refresh_session_count == 1
        assert table_names >= {
            "module_catalog",
            "industry_templates",
            "projects",
            "project_tasks",
        }
    finally:
        command.upgrade(config, "head")
        with engine.begin() as connection:
            connection.execute(
                text("DELETE FROM refresh_sessions WHERE user_id = :user_id"),
                {"user_id": user_id},
            )
            connection.execute(
                text("DELETE FROM users WHERE username = 'migration.admin'")
            )
        engine.dispose()


def test_template_version_metadata_and_stable_key_are_backfilled(test_settings):
    config = Config(str(SERVER_ROOT / "alembic.ini"))
    config.attributes["settings"] = test_settings
    engine = create_engine(test_settings.database_url)
    template_id = str(uuid4())
    version_id = str(uuid4())

    try:
        command.downgrade(config, "0003_project_workbench")
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO industry_templates "
                    "(id, name, industry_name, description, status) "
                    "VALUES (:id, 'Legacy template', 'Manufacturing', "
                    "'Legacy description', 'active')"
                ),
                {"id": template_id},
            )
            connection.execute(
                text(
                    "INSERT INTO industry_template_versions "
                    "(id, template_id, version_number, status) "
                    "VALUES (:id, :template_id, 1, 'draft')"
                ),
                {"id": version_id, "template_id": template_id},
            )

        command.upgrade(config, "head")

        with engine.connect() as connection:
            metadata = connection.execute(
                text(
                    "SELECT name, industry_name, description "
                    "FROM industry_template_versions WHERE id = :id"
                ),
                {"id": version_id},
            ).one()
            template_key = connection.execute(
                text("SELECT template_key FROM industry_templates WHERE id = :id"),
                {"id": template_id},
            ).scalar_one()

        assert metadata == (
            "Legacy template",
            "Manufacturing",
            "Legacy description",
        )
        assert template_key == f"template_{template_id.replace('-', '')}"
    finally:
        command.upgrade(config, "head")
        with engine.begin() as connection:
            connection.execute(
                text("DELETE FROM industry_template_versions WHERE id = :id"),
                {"id": version_id},
            )
            connection.execute(
                text("DELETE FROM industry_templates WHERE id = :id"),
                {"id": template_id},
            )
        engine.dispose()


def test_stable_key_migration_rejects_duplicate_legacy_generic_roots_safely(
    test_settings,
):
    """A pre-constraint seed race must stop before schema mutation with repair guidance."""
    config = Config(str(SERVER_ROOT / "alembic.ini"))
    config.attributes["settings"] = test_settings
    engine = create_engine(test_settings.database_url)
    template_ids = [str(uuid4()), str(uuid4())]
    version_ids = [str(uuid4()), str(uuid4())]

    try:
        command.downgrade(config, "0004_version_template_metadata")
        with engine.begin() as connection:
            for template_id, version_id in zip(template_ids, version_ids, strict=True):
                connection.execute(
                    text(
                        "INSERT INTO industry_templates "
                        "(id, name, industry_name, description, status, "
                        "latest_published_version_number) "
                        "VALUES (:id, '通用企业 AI 落地模板', '通用', "
                        "'legacy duplicate', 'active', 1)"
                    ),
                    {"id": template_id},
                )
                connection.execute(
                    text(
                        "INSERT INTO industry_template_versions "
                        "(id, template_id, name, industry_name, description, "
                        "version_number, status, published_at) "
                        "VALUES (:id, :template_id, '通用企业 AI 落地模板', "
                        "'通用', 'legacy duplicate', 1, 'published', "
                        "UTC_TIMESTAMP(6))"
                    ),
                    {"id": version_id, "template_id": template_id},
                )

        with pytest.raises(
            RuntimeError,
            match="multiple legacy generic template roots.*rename.*rerun",
        ):
            command.upgrade(config, "head")

        assert "template_key" not in {
            column["name"] for column in inspect(engine).get_columns("industry_templates")
        }
        with engine.connect() as connection:
            preserved_count = connection.execute(
                text(
                    "SELECT COUNT(*) FROM industry_templates "
                    "WHERE id IN (:first_id, :second_id)"
                ),
                {"first_id": template_ids[0], "second_id": template_ids[1]},
            ).scalar_one()
        assert preserved_count == 2
    finally:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "DELETE FROM industry_template_versions "
                    "WHERE id IN (:first_id, :second_id)"
                ),
                {"first_id": version_ids[0], "second_id": version_ids[1]},
            )
            connection.execute(
                text(
                    "DELETE FROM industry_templates "
                    "WHERE id IN (:first_id, :second_id)"
                ),
                {"first_id": template_ids[0], "second_id": template_ids[1]},
            )
        if "template_key" in {
            column["name"] for column in inspect(engine).get_columns("industry_templates")
        }:
            with engine.begin() as connection:
                connection.execute(
                    text("ALTER TABLE industry_templates DROP COLUMN template_key")
                )
        command.upgrade(config, "head")
        engine.dispose()


def test_revision_status_migration_roundtrip_preserves_revision_and_answer_rows(
    test_settings,
):
    """Rebuilding the live MySQL status check must not replace research rows."""
    config = Config(str(SERVER_ROOT / "alembic.ini"))
    config.attributes["settings"] = test_settings
    engine = create_engine(test_settings.database_url)
    ids = None

    try:
        command.downgrade(config, "0007_research_form_snapshot")
        ids = seed_submitted_research_revision_at_0007(engine)
        before_revision, before_answer = research_roundtrip_rows(engine, ids)
        assert before_revision == (
            ids["revision"],
            ids["project_form"],
            1,
            "submitted",
            3,
            "migration_form",
        )
        assert before_answer == (
            ids["answer"],
            ids["revision"],
            ids["template_field"],
            "retained_field",
            "preserved",
            7,
        )

        command.upgrade(config, "0008_research_revision_status")

        upgraded_revision, upgraded_answer = research_roundtrip_rows(engine, ids)
        assert upgraded_revision == before_revision[:3] + ("draft",) + before_revision[4:]
        assert upgraded_answer == before_answer
        status_constraint = next(
            constraint
            for constraint in inspect(engine).get_check_constraints(
                "project_research_form_revisions"
            )
            if constraint["name"] == "ck_project_research_form_revisions_status"
        )
        assert set(re.findall(r"'([^']+)'", status_constraint["sqltext"])) == {
            "draft",
            "confirmed",
            "archived",
        }
        for allowed_status in ("draft", "confirmed", "archived"):
            with engine.begin() as connection:
                connection.execute(
                    text(
                        "UPDATE project_research_form_revisions SET status = :status "
                        "WHERE id = :id"
                    ),
                    {"status": allowed_status, "id": ids["revision"]},
                )
            assert scalar(
                engine,
                "SELECT status FROM project_research_form_revisions "
                "WHERE id = :id",
                {"id": ids["revision"]},
            ) == allowed_status
        with pytest.raises(DBAPIError):
            with engine.begin() as connection:
                connection.execute(
                    text(
                        "UPDATE project_research_form_revisions "
                        "SET status = 'submitted' WHERE id = :id"
                    ),
                    {"id": ids["revision"]},
                )

        command.downgrade(config, "0007_research_form_snapshot")

        downgraded_revision, downgraded_answer = research_roundtrip_rows(engine, ids)
        assert downgraded_revision == before_revision[:3] + ("draft",) + before_revision[4:]
        assert downgraded_answer == before_answer
    finally:
        command.upgrade(config, "head")
        if ids is not None:
            with engine.begin() as connection:
                connection.execute(
                    text(
                        "UPDATE project_research_forms SET current_revision_id = NULL "
                        "WHERE id = :id"
                    ),
                    {"id": ids["project_form"]},
                )
                for table_name, key in (
                    ("project_research_answers", "answer"),
                    ("project_research_form_revisions", "revision"),
                    ("project_research_forms", "project_form"),
                    ("project_research_subjects", "subject"),
                    ("template_research_fields", "template_field"),
                    ("template_research_sections", "template_section"),
                    ("template_research_forms", "template_form"),
                    ("projects", "project"),
                    ("industry_template_versions", "template_version"),
                    ("industry_templates", "template"),
                    ("users", "user"),
                ):
                    connection.execute(
                        text(f"DELETE FROM {table_name} WHERE id = :id"),
                        {"id": ids[key]},
                    )
        engine.dispose()


def test_file_migration_preserves_existing_data_and_adds_file_tables(
    alembic_config, engine
):
    """The file/outbox schema must extend 0009 without replacing prior data."""
    command.downgrade(alembic_config, "0009_research_import_batches")
    seed_minimal_project(engine, project_code="FDE-FILES-KEEP")
    command.upgrade(alembic_config, "head")

    assert scalar(
        engine, "SELECT project_code FROM projects WHERE project_code='FDE-FILES-KEEP'"
    ) == "FDE-FILES-KEEP"
    assert table_names(engine) >= {
        "project_files",
        "project_file_versions",
        "upload_sessions",
        "outbox_events",
        "background_jobs",
    }


def test_document_migration_preserves_files(alembic_config, engine):
    """The document schema must extend 0010 without replacing file data."""
    command.downgrade(alembic_config, "0010_project_files_and_outbox")
    seed_minimal_project(engine, project_code="FDE-DOC-KEEP")

    project_id = scalar(
        engine, "SELECT id FROM projects WHERE project_code='FDE-DOC-KEEP'"
    )
    user_id = scalar(
        engine, "SELECT id FROM users WHERE username='migration.fde-doc-keep'"
    )
    file_id = str(uuid4())
    file_version_id = str(uuid4())
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO project_files "
                "(id, project_id, category, display_name, description, tags_json, "
                "status, created_by_user_id) "
                "VALUES (:id, :project_id, 'document', 'keep.docx', '', "
                "JSON_OBJECT(), 'active', :user_id)"
            ),
            {"id": file_id, "project_id": project_id, "user_id": user_id},
        )
        connection.execute(
            text(
                "INSERT INTO project_file_versions "
                "(id, file_id, version_number, source, original_filename, "
                "safe_filename, extension, mime_type, bucket, storage_key, "
                "size_bytes, etag, sha256, scan_status, preview_status, "
                "uploaded_by_user_id, status) "
                "VALUES (:id, :file_id, 1, 'upload', 'keep.docx', 'keep.docx', "
                "'.docx', 'application/vnd.openxmlformats-officedocument."
                "wordprocessingml.document', 'fde-test-bucket', :storage_key, 1024, "
                "'', '', 'clean', 'none', :user_id, 'available')"
            ),
            {
                "id": file_version_id,
                "file_id": file_id,
                "user_id": user_id,
                "storage_key": (
                    f"projects/{project_id}/documents/{file_id}/versions/v1/keep.docx"
                ),
            },
        )

    command.upgrade(alembic_config, "head")

    assert scalar(
        engine,
        "SELECT original_filename FROM project_file_versions "
        "WHERE original_filename='keep.docx'",
    ) == "keep.docx"
    assert scalar(
        engine, "SELECT project_code FROM projects WHERE project_code='FDE-DOC-KEEP'"
    ) == "FDE-DOC-KEEP"
    assert table_names(engine) >= {
        "document_templates",
        "document_template_versions",
        "project_documents",
        "project_document_versions",
        "document_generation_jobs",
        "project_document_drafts",
    }


def test_dsh_execution_migration_preserves_and_backfills_existing_runs(
    alembic_config, engine
):
    """0025 must extend an already-used 0024 control plane without data loss."""
    command.downgrade(alembic_config, "0024_control_plane_foundation")
    seed_minimal_project(engine, project_code="FDE-DSH-KEEP")

    project_id = scalar(
        engine, "SELECT id FROM projects WHERE project_code='FDE-DSH-KEEP'"
    )
    user_id = scalar(
        engine, "SELECT id FROM users WHERE username='migration.fde-dsh-keep'"
    )
    task_id = str(uuid4())
    run_id = str(uuid4())
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO automation_tasks "
                "(id, project_id, created_by_user_id, title, description, source, "
                "task_type, status, schedule_kind, schedule_expression, timezone, "
                "prompt, dsh_profile, risk_level, notification_policy, version) "
                "VALUES (:id, :project_id, :user_id, 'Retained DSH task', '', "
                "'desktop', 'ai', 'active', 'once', '', 'Asia/Shanghai', "
                "'Summarize the project', 'fde-operator', 0, JSON_OBJECT(), 1)"
            ),
            {"id": task_id, "project_id": project_id, "user_id": user_id},
        )
        connection.execute(
            text(
                "INSERT INTO automation_task_runs "
                "(id, task_id, scheduled_for, status, attempt, idempotency_key, "
                "dsh_runtime_version, agent_profile_version, result_summary, "
                "error_code, error_message) "
                "VALUES (:id, :task_id, UTC_TIMESTAMP(6), 'queued', 0, :key, "
                "'', '', '', '', '')"
            ),
            {"id": run_id, "task_id": task_id, "key": f"legacy:{run_id}"},
        )

    command.upgrade(alembic_config, "head")

    with engine.connect() as connection:
        retained = connection.execute(
            text(
                "SELECT requested_by_user_id, external_execution_id, output_json "
                "FROM automation_task_runs WHERE id = :id"
            ),
            {"id": run_id},
        ).mappings().one()
        capabilities = connection.execute(
            text(
                "SELECT requested_capabilities FROM automation_tasks WHERE id = :id"
            ),
            {"id": task_id},
        ).scalar_one()

    assert retained["requested_by_user_id"] == user_id
    assert retained["external_execution_id"] == ""
    assert retained["output_json"] in ({}, "{}")
    assert "project.read" in str(capabilities)
    assert "file.search" in str(capabilities)


def test_business_category_migration_adds_columns_and_constraints(engine):
    """The 0013 migration adds a nullable business_category column plus a frozen
    value check to both project_files and project_documents."""
    database = inspect(engine)

    for table_name in ("project_files", "project_documents"):
        columns = {
            column["name"]: column
            for column in database.get_columns(table_name)
        }
        assert "business_category" in columns
        assert columns["business_category"]["nullable"] is True
        constraint = next(
            constraint
            for constraint in database.get_check_constraints(table_name)
            if constraint["name"] == f"ck_{table_name}_business_category"
        )
        assert set(re.findall(r"'([^']+)'", constraint["sqltext"])) == {
            "商务合约",
            "预调研",
            "调研",
            "PoV验证",
            "生产部署",
            "培训预交接",
        }
