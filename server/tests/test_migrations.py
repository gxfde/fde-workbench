"""Migration tests for the PostgreSQL revision chain.

The PG chain is a squashed baseline (ebb003a5c3a8) plus four incremental
revisions; the legacy MySQL chain (0002-0042) no longer exists. These tests
exercise the real chain: baseline table coverage, the codename (A2) projects
schema, data preservation across each incremental roundtrip, and the frozen
schema contracts that later runtime code depends on.

Precondition note: the p1 codename migration adds projects.enterprise_code as
NOT NULL without a default, so it is only safe on an empty projects table;
user/template rows are used to prove data preservation across that step.
"""
import os
import re
import subprocess
import sys
from uuid import uuid4

import pytest
from alembic import command
from sqlalchemy import inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError, IntegrityError

from conftest import SERVER_ROOT, seed_reference_data


# f7a2c9e4b1d3 迁移时刻的 gates.json 文件哈希（历史回填值，冻结不随种子演进
# 漂移——迁移文件内同值常量是它的唯一权威；gate 行实例化时的实时哈希由
# gate_service._gates_file_hash() 现算，审计语义=「该行从哪版模板实例化」）。
GATES_JSON_SHA256 = "f52afe884af8026eef28af66abdae0d2c8f7b07a25d100bf0a647276b51647e6"
# WP-E SES 预建新增 mailing_sends / mailing_events 两表（goal-r3 G9）；
# goal-r1 派单引擎：gates 验收分离三列 + delivery_packages/dispatch_offers 骨架表
# goal-r2 派单引擎：fde_profiles / fde_level_evidence / dispatch_rule_versions /
# delivery_settlements 四表 + payments.acceptance_passed_at（P0-3/4/8）
# goal-r3 派单引擎：package_access 表 + delivery_packages.delivery_seat_amount（P0-1/2）
# goal-r6 派单引擎：quotes.owner_user_id + disputes 表（P1-6/P1-7/§8.1 第 8 表）
# goal-r7 派单引擎：business_line 'FDE_DISPATCH' 放行（P2-3）
# goal-d3 交付工作台：agent 五表 + solution_review_checkpoints +
# project_solutions 生成来源四列（template_id 回填自 source_json 骨架指针）
# goal-d8 交付工作台：delivery_packages.agent_assisted + difficulty（D2 合成裁决）
# V3 T-E1：project_evidence 一等证据表（单表增量，零改既有表）
# V3 T-W1：workflow_definitions + workflow_definition_versions 两表
# V3 T-W2：workflow_runs + workflow_node_runs 两表（run 固定版本 + 幂等键）
# V3 T-W4：automation_approvals 审批复用——run_id 放开可空 + workflow_node_run_id 反链
# V3 T-S1：skill 治理态——status 换 draft/in_review/published/deprecated + 版本契约/审核列
# V3 T-O1：ontology_terms + ontology_term_aliases 两表（术语/别名治理底座）
HEAD_REVISION = "a3e7c1f9b5d2"

PLAINTEXT_ENTERPRISE_COLUMNS = (
    "enterprise_name",
    "enterprise_contact_name",
    "enterprise_contact_phone",
    "enterprise_address",
)


def scalar(engine, statement, parameters=None):
    with engine.connect() as connection:
        return connection.execute(
            text(statement), parameters or {}
        ).scalar_one_or_none()


def table_names(engine):
    return set(inspect(engine).get_table_names())


def seed_user_and_template(engine, *, username):
    """Seed user/template rows; valid at the baseline and at head."""
    ids = {
        "user_id": str(uuid4()),
        "template_id": str(uuid4()),
        "template_version_id": str(uuid4()),
    }
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO users "
                "(id, username, display_name, role, password_hash, "
                "must_change_password, is_active) "
                "VALUES (:id, :username, 'Migration Admin', 'admin', 'x', "
                "FALSE, TRUE)"
            ),
            {"id": ids["user_id"], "username": username},
        )
        connection.execute(
            text(
                "INSERT INTO industry_templates "
                "(id, template_key, name, industry_name, description, status) "
                "VALUES (:id, :template_key, 'Migration template', "
                "'Manufacturing', '', 'active')"
            ),
            {
                "id": ids["template_id"],
                "template_key": f"template_{ids['template_id'].replace('-', '')}",
            },
        )
        connection.execute(
            text(
                "INSERT INTO industry_template_versions "
                "(id, template_id, name, industry_name, description, "
                "version_number, status) "
                "VALUES (:id, :template_id, 'Migration template', "
                "'Manufacturing', '', 1, 'draft')"
            ),
            {"id": ids["template_version_id"], "template_id": ids["template_id"]},
        )
    return ids


def seed_project(engine, ids, *, project_code):
    """Seed a project row against the codename (head) projects schema.

    projects.sop_phase references sop_nodes.node_key, and migrations create
    that table empty (seeding is an app-level step), so an S3 node row is
    required. When reference seeds are present (node_key is unique), the real
    S3 row is borrowed instead and reported as None so cleanup keeps it.
    """
    project_id = str(uuid4())
    with engine.begin() as connection:
        sop_node_id = connection.execute(
            text("SELECT id FROM sop_nodes WHERE node_key = 'S3'")
        ).scalar_one_or_none()
        if sop_node_id is None:
            sop_node_id = str(uuid4())
            connection.execute(
                text(
                    "INSERT INTO sop_nodes (id, node_key, name, segment, "
                    "source_uri, content_hash) "
                    "VALUES (:id, 'S3', '需求确认', '交付段', "
                    "'test://migration-seed/s3', :content_hash)"
                ),
                {"id": sop_node_id, "content_hash": uuid4().hex * 2},
            )
        else:
            sop_node_id = None
        connection.execute(
            text(
                "INSERT INTO projects "
                "(id, project_code, name, enterprise_code, background, notes, "
                "status, planned_start_date, leader_user_id, "
                "source_template_version_id, template_snapshot, research_snapshot) "
                "VALUES (:id, :project_code, 'Retained project', :enterprise_code, "
                "'', '', 'active', '2026-08-22', :user_id, :template_version_id, "
                "'{}'::json, '{}'::json)"
            ),
            {
                "id": project_id,
                "project_code": project_code,
                "enterprise_code": f"s-test-{project_code.lower()}",
                "user_id": ids["user_id"],
                "template_version_id": ids["template_version_id"],
            },
        )
    return project_id, sop_node_id


def cleanup_seeded_rows(engine, ids, *, project_id=None, sop_node_id=None):
    with engine.begin() as connection:
        if project_id is not None:
            connection.execute(
                text("DELETE FROM projects WHERE id = :id"), {"id": project_id}
            )
        if sop_node_id is not None:
            connection.execute(
                text("DELETE FROM sop_nodes WHERE id = :id"), {"id": sop_node_id}
            )
        connection.execute(
            text("DELETE FROM industry_template_versions WHERE id = :id"),
            {"id": ids["template_version_id"]},
        )
        connection.execute(
            text("DELETE FROM industry_templates WHERE id = :id"),
            {"id": ids["template_id"]},
        )
        connection.execute(
            text("DELETE FROM users WHERE id = :id"), {"id": ids["user_id"]}
        )


def test_model_metadata_tables_all_exist_in_migrated_schema(engine):
    from fde_api.auth.models import Base

    model_tables = set(Base.metadata.tables)
    migrated_tables = table_names(engine)

    assert not model_tables - migrated_tables, (
        "tables in models but missing from schema: "
        f"{sorted(model_tables - migrated_tables)}"
    )
    assert not migrated_tables - model_tables - {"alembic_version"}, (
        "tables in schema but missing from models: "
        f"{sorted(migrated_tables - model_tables - {'alembic_version'})}"
    )


def test_head_projects_schema_is_codename_only(engine):
    columns = {column["name"] for column in inspect(engine).get_columns("projects")}

    assert "enterprise_code" in columns
    assert not (set(PLAINTEXT_ENTERPRISE_COLUMNS) & columns), (
        "plaintext enterprise columns must not reappear at head"
    )


def test_p1_sop_migration_preserves_users_and_adds_codename_column(
    alembic_config, engine
):
    command.downgrade(alembic_config, "ebb003a5c3a8")
    ids = seed_user_and_template(engine, username="migration.fde-keep")

    command.upgrade(alembic_config, "head")

    assert (
        scalar(
            engine,
            "SELECT username FROM users WHERE id = :id",
            {"id": ids["user_id"]},
        )
        == "migration.fde-keep"
    )
    columns = {column["name"] for column in inspect(engine).get_columns("projects")}
    assert "enterprise_code" in columns
    assert not (set(PLAINTEXT_ENTERPRISE_COLUMNS) & columns)
    assert table_names(engine) >= {
        "sop_nodes",
        "gates",
    }
    cleanup_seeded_rows(engine, ids)
    # downgrade 到 baseline 清空了引用种子表；回到 head 后重灌，
    # 否则本文件之后的所有建项目测试撞 fk_projects_sop_phase_sop_nodes。
    seed_reference_data(engine.url.render_as_string(hide_password=False))


def test_p2_bridge_tables_roundtrip_preserves_projects(alembic_config, engine):
    command.downgrade(alembic_config, "b4e8c1a7d2f6")
    assert not {"bridge_engagements", "bridge_sync_runs"} & table_names(engine)
    ids = seed_user_and_template(engine, username="migration.fde-bridge-keep")
    project_id, sop_node_id = seed_project(
        engine, ids, project_code="FDE-BRIDGE-KEEP"
    )

    command.upgrade(alembic_config, "head")

    assert (
        scalar(
            engine,
            "SELECT project_code FROM projects WHERE project_code='FDE-BRIDGE-KEEP'",
        )
        == "FDE-BRIDGE-KEEP"
    )
    assert {"bridge_engagements", "bridge_sync_runs"} <= table_names(engine)

    command.downgrade(alembic_config, "b4e8c1a7d2f6")

    assert (
        scalar(
            engine,
            "SELECT project_code FROM projects WHERE project_code='FDE-BRIDGE-KEEP'",
        )
        == "FDE-BRIDGE-KEEP"
    )
    assert not {"bridge_engagements", "bridge_sync_runs"} & table_names(engine)

    command.upgrade(alembic_config, "head")
    cleanup_seeded_rows(
        engine, ids, project_id=project_id, sop_node_id=sop_node_id
    )
    # 回到 head 后重灌引用种子（幂等）；即使本 roundtrip 未清表，
    # 也保证后续用例面对的是「迁移完成 + 种子就绪」的标准状态。
    seed_reference_data(engine.url.render_as_string(hide_password=False))


def test_p4_commercial_tables_roundtrip_preserves_projects(alembic_config, engine):
    command.downgrade(alembic_config, "d7a3e8c5f1b9")
    assert not {"quotes", "payments", "contracts"} & table_names(engine)
    ids = seed_user_and_template(engine, username="migration.fde-comm-keep")
    project_id, sop_node_id = seed_project(engine, ids, project_code="FDE-COMM-KEEP")

    command.upgrade(alembic_config, "head")

    assert (
        scalar(
            engine,
            "SELECT project_code FROM projects WHERE project_code='FDE-COMM-KEEP'",
        )
        == "FDE-COMM-KEEP"
    )
    assert {"quotes", "payments", "contracts"} <= table_names(engine)

    command.downgrade(alembic_config, "d7a3e8c5f1b9")

    assert (
        scalar(
            engine,
            "SELECT project_code FROM projects WHERE project_code='FDE-COMM-KEEP'",
        )
        == "FDE-COMM-KEEP"
    )
    assert not {"quotes", "payments", "contracts"} & table_names(engine)

    command.upgrade(alembic_config, "head")
    cleanup_seeded_rows(
        engine, ids, project_id=project_id, sop_node_id=sop_node_id
    )
    seed_reference_data(engine.url.render_as_string(hide_password=False))


def test_gate_template_hash_migration_backfills_existing_gate_rows(
    alembic_config, engine
):
    command.downgrade(alembic_config, "c9f2d4e8a1b7")
    assert "template_hash" not in {
        column["name"] for column in inspect(engine).get_columns("gates")
    }
    ids = seed_user_and_template(engine, username="migration.fde-gate-keep")
    project_id, sop_node_id = seed_project(
        engine, ids, project_code="FDE-GATE-KEEP"
    )
    gate_id = str(uuid4())
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO gates (id, project_id, gate_key) "
                "VALUES (:id, :project_id, 'G1')"
            ),
            {"id": gate_id, "project_id": project_id},
        )

    command.upgrade(alembic_config, "head")

    assert (
        scalar(
            engine,
            "SELECT template_hash FROM gates WHERE id = :id",
            {"id": gate_id},
        )
        == GATES_JSON_SHA256
    )
    cleanup_seeded_rows(
        engine, ids, project_id=project_id, sop_node_id=sop_node_id
    )
    seed_reference_data(engine.url.render_as_string(hide_password=False))


def test_test_database_schema_is_at_alembic_head(test_settings, db_session):
    version = db_session.execute(
        text("SELECT version_num FROM alembic_version")
    ).scalar_one()

    assert make_url(test_settings.database_url).database.endswith("_test")
    assert version == HEAD_REVISION


def test_research_field_type_contract_is_frozen_from_live_models():
    """The live research field types must match the frozen baseline check."""
    from fde_api.research import models as research_models

    expected_types = (
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
    assert research_models.FIELD_TYPES == expected_types
    assert research_models.FIELD_TYPE_CHECK_SQL == (
        "field_type IN ('short_text', 'long_text', 'rich_text', 'integer', "
        "'decimal', 'date', 'single_choice', 'multi_choice', 'table', "
        "'file_reference')"
    )


def test_research_field_type_check_constraint_matches_live_contract(db_session):
    constraint = next(
        constraint
        for constraint in inspect(db_session.bind).get_check_constraints(
            "template_research_fields"
        )
        if constraint["name"] == "ck_template_research_fields_field_type"
    )
    assert set(re.findall(r"'([^']+)'", constraint["sqltext"])) == {
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
    }


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


def test_business_category_check_constraint_is_frozen(engine):
    """The frozen business_category value check applies to files and documents."""
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


def test_stable_template_key_uniqueness_rejects_duplicates(engine):
    """The legacy duplicate generic-root race is closed by a unique constraint."""
    first_id = str(uuid4())
    second_id = str(uuid4())
    template_key = f"template_{first_id.replace('-', '')}"

    with pytest.raises(IntegrityError):
        with engine.begin() as connection:
            for row_id in (first_id, second_id):
                connection.execute(
                    text(
                        "INSERT INTO industry_templates "
                        "(id, template_key, name, industry_name, description, status) "
                        "VALUES (:id, :template_key, '通用企业 AI 落地模板', "
                        "'通用', 'legacy duplicate', 'active')"
                    ),
                    {"id": row_id, "template_key": template_key},
                )


def test_research_revision_status_check_constraint_rejects_legacy_status(
    db_session,
):
    """The pre-0008 'submitted' status must stay rejected by the head check."""
    with pytest.raises(DBAPIError, match="ck_project_research_form_revisions_status"):
        with db_session.begin():
            db_session.execute(
                text(
                    "INSERT INTO project_research_form_revisions "
                    "(id, form_id, revision_number, status, version, "
                    "definition_snapshot) "
                    "VALUES (:id, :form_id, 1, 'submitted', 1, "
                    "'{}'::json)"
                ),
                {"id": str(uuid4()), "form_id": str(uuid4())},
            )
    db_session.rollback()


def test_v3_project_evidence_roundtrip_preserves_projects(alembic_config, engine):
    """V3 T-E1：project_evidence 单表增量——downgrade 一步即消失、upgrade 回 head
    即重建；两向都不碰 projects 行（新表零外键依赖方，回滚安全）。"""
    command.downgrade(alembic_config, "c3e7a9b1d5f4")
    assert "project_evidence" not in table_names(engine)
    ids = seed_user_and_template(engine, username="migration.v3-evidence-keep")
    seed_project(engine, ids, project_code="FDE-V3-EVID-KEEP")

    command.upgrade(alembic_config, "head")

    assert (
        scalar(
            engine,
            "SELECT project_code FROM projects WHERE project_code='FDE-V3-EVID-KEEP'",
        )
        == "FDE-V3-EVID-KEEP"
    )
    assert "project_evidence" in table_names(engine)

    command.downgrade(alembic_config, "c3e7a9b1d5f4")

    assert (
        scalar(
            engine,
            "SELECT project_code FROM projects WHERE project_code='FDE-V3-EVID-KEEP'",
        )
        == "FDE-V3-EVID-KEEP"
    )
    assert "project_evidence" not in table_names(engine)

    command.upgrade(alembic_config, "head")


def test_v3_workflow_definition_tables_roundtrip_preserves_projects(alembic_config, engine):
    """V3 T-W1：workflow 定义两表增量——downgrade 子表先行即消失、upgrade 回 head
    重建；两向都不碰 projects 行。"""
    command.downgrade(alembic_config, "e1f3a5c7b9d2")
    assert not {"workflow_definitions", "workflow_definition_versions"} & table_names(engine)
    ids = seed_user_and_template(engine, username="migration.v3-workflow-keep")
    seed_project(engine, ids, project_code="FDE-V3-WF-KEEP")

    command.upgrade(alembic_config, "head")

    assert (
        scalar(
            engine,
            "SELECT project_code FROM projects WHERE project_code='FDE-V3-WF-KEEP'",
        )
        == "FDE-V3-WF-KEEP"
    )
    assert {"workflow_definitions", "workflow_definition_versions"} <= table_names(engine)

    command.downgrade(alembic_config, "e1f3a5c7b9d2")

    assert (
        scalar(
            engine,
            "SELECT project_code FROM projects WHERE project_code='FDE-V3-WF-KEEP'",
        )
        == "FDE-V3-WF-KEEP"
    )
    assert not {"workflow_definitions", "workflow_definition_versions"} & table_names(engine)

    command.upgrade(alembic_config, "head")


def test_v3_workflow_runs_tables_roundtrip_preserves_projects(alembic_config, engine):
    """V3 T-W2：运行两表增量——downgrade 子表先行即消失、upgrade 回 head 重建；
    两向都不碰 projects 行，定义两表保持存在。"""
    command.downgrade(alembic_config, "f2a4c6e8b1d3")
    assert not {"workflow_runs", "workflow_node_runs"} & table_names(engine)
    assert {"workflow_definitions", "workflow_definition_versions"} <= table_names(engine)
    ids = seed_user_and_template(engine, username="migration.v3-wfrun-keep")
    seed_project(engine, ids, project_code="FDE-V3-WFRUN-KEEP")

    command.upgrade(alembic_config, "head")

    assert (
        scalar(
            engine,
            "SELECT project_code FROM projects WHERE project_code='FDE-V3-WFRUN-KEEP'",
        )
        == "FDE-V3-WFRUN-KEEP"
    )
    assert {"workflow_runs", "workflow_node_runs"} <= table_names(engine)

    command.downgrade(alembic_config, "f2a4c6e8b1d3")

    assert (
        scalar(
            engine,
            "SELECT project_code FROM projects WHERE project_code='FDE-V3-WFRUN-KEEP'",
        )
        == "FDE-V3-WFRUN-KEEP"
    )
    assert not {"workflow_runs", "workflow_node_runs"} & table_names(engine)
    assert {"workflow_definitions", "workflow_definition_versions"} <= table_names(engine)

    command.upgrade(alembic_config, "head")


def test_v3_ontology_tables_roundtrip_preserves_projects(alembic_config, engine):
    """V3 T-O1：术语两表增量——downgrade 别名表先行消失、upgrade 回 head 重建；
    两向都不碰 projects 行；head 上自引用外键可用（merged 行指向保留行）。"""
    command.downgrade(alembic_config, "c1e5f9a3d7b2")
    assert not {"ontology_terms", "ontology_term_aliases"} & table_names(engine)
    ids = seed_user_and_template(engine, username="migration.v3-term-keep")
    project_id, sop_node_id = seed_project(engine, ids, project_code="FDE-V3-TERM-KEEP")

    command.upgrade(alembic_config, "head")

    assert (
        scalar(
            engine,
            "SELECT project_code FROM projects WHERE project_code='FDE-V3-TERM-KEEP'",
        )
        == "FDE-V3-TERM-KEEP"
    )
    assert {"ontology_terms", "ontology_term_aliases"} <= table_names(engine)

    # head 上落一对 canonical/merged 行：自引用外键 + merged 必须指向保留行
    kept_id, merged_id = str(uuid4()), str(uuid4())
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO ontology_terms "
                "(id, project_id, term, term_type, definition, status, created_at, updated_at) "
                "VALUES (:kept, :project_id, '交付包', 'entity', "
                "'一次交付的物量集合。', 'confirmed', now(), now())"
            ),
            {"kept": kept_id, "project_id": project_id},
        )
        connection.execute(
            text(
                "INSERT INTO ontology_terms "
                "(id, project_id, term, term_type, definition, status, canonical_term_id, created_at, updated_at) "
                "VALUES (:merged, :project_id, '交付物量', 'entity', "
                "'同「交付包」。', 'merged', :kept, now(), now())"
            ),
            {"merged": merged_id, "project_id": project_id, "kept": kept_id},
        )
    assert (
        scalar(
            engine,
            "SELECT canonical_term_id FROM ontology_terms WHERE id = :id",
            {"id": merged_id},
        )
        == kept_id
    )

    command.downgrade(alembic_config, "c1e5f9a3d7b2")

    assert (
        scalar(
            engine,
            "SELECT project_code FROM projects WHERE project_code='FDE-V3-TERM-KEEP'",
        )
        == "FDE-V3-TERM-KEEP"
    )
    assert not {"ontology_terms", "ontology_term_aliases"} & table_names(engine)

    command.upgrade(alembic_config, "head")
    cleanup_seeded_rows(engine, ids, project_id=project_id, sop_node_id=sop_node_id)
    # 回到 head 后重灌引用种子（幂等），保证后续用例面对标准状态。
    seed_reference_data(engine.url.render_as_string(hide_password=False))
