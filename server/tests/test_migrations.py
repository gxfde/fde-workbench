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
from sqlalchemy.exc import DBAPIError, DataError, IntegrityError

from conftest import (
    SERVER_ROOT,
    _current_alembic_stamp,
    _known_alembic_revisions,
    _reconcile_test_schema,
    seed_reference_data,
)


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
# V3 T-O2：ontology_relation_types 一表（关系/对象类型注册表）
# V3 T-O3：ontology_change_sets 一表（变更集：批量事务单元 + base 指纹并发防护）
# V3 T-O2b：对象类型值域开放——三处 subject_type CHECK 枚举→码格式 + 列宽 32→60
# V3 T-O4b：project_research_subjects +merged_into_subject_id（合并指向，复合外键+CHECK）
# V3 T-G1：gates +evidence_candidates JSON 可空列（任务产物→门禁证据候选，建议性）
# V3 T-D1：document_generation_jobs +ai_request_id（WB-DEF-6 文档血缘：job 行反查 ai_call_audits）
# V3 T-J2：background_jobs 状态值域 +cancelled（admin 取消面，纯 CHECK 置换零列重建）
# T-A9（goal-tb tb1）：transcript_drafts + interview_minutes（草稿区+纪要正式库，additive）
# T-B1（goal-tb tb2）：agent_artifacts 扩列（derived_summary/reviewed_by/reviewed_at + kind CHECK 扩 test_results）
# T-B1 封包半（goal-tb tb4）：handover_packages+handover_package_items（结项交付包两表，additive）
# V3.2 G2：simulation_scenarios（交付模拟训练场案例库，additive 单表）
# V3.2 G3：simulation_runs/simulation_actors/simulation_traces（运行层三表，additive）
# V3.2 G4：simulation_evaluations（评估层单表，additive）
# V3.2 G5：simulation_findings + improvement_proposals（改进层两表，additive）
# V3.2 G6：regression_suites + regression_results（回归层两表）+ proposals 扩列 override_json
# V3.1 P0-1：discovery 四表（discovery_extractions/business_facts/requirements/requirement_sources，additive）
# V3.1 P0-2：project_research_subjects +term_id（ADR-002 稳定 ID 试点，可空 FK RESTRICT）
# V3.1 P0-3：delivery_plans 三表（交付方案版本化+条目+任务映射，additive）
# V3.1 P1-2：test_plans/test_cases/test_executions 三表（质量模块，additive）
# V3.1 P1-1：agent_runs 扩列 +5 / agent_artifacts 扩列 +4（执行面字段，additive）
# 商业化 G1：commercial_entitlements + training_entitlements 两表（权益四分，additive）
# 商业化 G2：enterprise_quota_subjects + enterprise_free_quota 两表（免费额度主体认定，additive）
HEAD_REVISION = "b3e7c9d1a5f2"

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


def test_v311_p11_execution_columns_roundtrip_preserves_projects(alembic_config, engine):
    """V3.1 P1-1：agent_runs/agent_artifacts 扩列（additive）——downgrade 一部
    即退列、upgrade 回 head 即重得；两向都不碰 projects 行（agent_runs FK
    RESTRICT 经用户/项目种子行不动）。"""
    command.downgrade(alembic_config, "d5a8c2f4b7e1")
    run_columns = {column["name"] for column in inspect(engine).get_columns("agent_runs")}
    artifact_columns = {column["name"] for column in inspect(engine).get_columns("agent_artifacts")}
    assert not {"host_agent_id", "authorization_id", "workspace_ref", "resume_session_ref", "policy_snapshot_hash"} & run_columns
    assert not {"size_bytes", "mime_type", "revoked_by_user_id", "revoked_at"} & artifact_columns
    ids = seed_user_and_template(engine, username="migration.v311-p11-keep")
    seed_project(engine, ids, project_code="FDE-V311-P11-KEEP")

    command.upgrade(alembic_config, "head")

    assert (
        scalar(
            engine,
            "SELECT project_code FROM projects WHERE project_code='FDE-V311-P11-KEEP'",
        )
        == "FDE-V311-P11-KEEP"
    )
    run_columns = {column["name"] for column in inspect(engine).get_columns("agent_runs")}
    artifact_columns = {column["name"] for column in inspect(engine).get_columns("agent_artifacts")}
    assert {"host_agent_id", "authorization_id", "workspace_ref", "resume_session_ref", "policy_snapshot_hash"} <= run_columns
    assert {"size_bytes", "mime_type", "revoked_by_user_id", "revoked_at"} <= artifact_columns

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


def test_v3_relation_type_table_roundtrip_enforces_scopes(alembic_config, engine):
    """V3 T-O2：类型注册表增量——downgrade 表消失、upgrade 回 head 重建；
    全局行按 (kind, code) 唯一（project_id IS NULL 的部分唯一索引），
    项目内行与全局行同名共存（项目遮蔽全局）；关系类型必须声明端点约束。"""
    command.downgrade(alembic_config, "a3e7c1f9b5d2")
    assert "ontology_relation_types" not in table_names(engine)
    ids = seed_user_and_template(engine, username="migration.v3-type-keep")
    project_id, sop_node_id = seed_project(engine, ids, project_code="FDE-V3-TYPE-KEEP")

    command.upgrade(alembic_config, "head")

    assert "ontology_relation_types" in table_names(engine)
    assert (
        scalar(
            engine,
            "SELECT project_code FROM projects WHERE project_code='FDE-V3-TYPE-KEEP'",
        )
        == "FDE-V3-TYPE-KEEP"
    )

    global_id, scoped_id = str(uuid4()), str(uuid4())
    with engine.begin() as connection:
        # 全局行：project_id 为空
        connection.execute(
            text(
                "INSERT INTO ontology_relation_types "
                "(id, project_id, kind, code, label, description, "
                "allowed_source_types, allowed_target_types, status, created_at, updated_at) "
                "VALUES (:id, NULL, 'link_type', 'global_edge', '全局关系', NULL, "
                "'[\"opportunity\"]', '[\"role\"]', 'active', now(), now())"
            ),
            {"id": global_id},
        )
        # 项目内行与全局行同名共存（不同作用域；项目内遮蔽全局）
        connection.execute(
            text(
                "INSERT INTO ontology_relation_types "
                "(id, project_id, kind, code, label, description, "
                "allowed_source_types, allowed_target_types, status, created_at, updated_at) "
                "VALUES (:id, :project_id, 'link_type', 'global_edge', '项目关系', NULL, "
                "'[\"opportunity\"]', '[\"process\"]', 'active', now(), now())"
            ),
            {"id": scoped_id, "project_id": project_id},
        )
    assert (
        scalar(
            engine,
            "SELECT allowed_target_types FROM ontology_relation_types WHERE id = :id",
            {"id": scoped_id},
        )
        == ["process"]
    )

    # 全局作用域内同 (kind, code) 不可重复
    with pytest.raises(IntegrityError):
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO ontology_relation_types "
                    "(id, project_id, kind, code, label, description, "
                    "allowed_source_types, allowed_target_types, status, created_at, updated_at) "
                    "VALUES (:id, NULL, 'link_type', 'global_edge', '重复全局', NULL, "
                    "'[\"opportunity\"]', '[\"role\"]', 'active', now(), now())"
                ),
                {"id": str(uuid4())},
            )

    # 关系类型必须声明端点约束（空数组被 CHECK 拒）
    with pytest.raises(IntegrityError):
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO ontology_relation_types "
                    "(id, project_id, kind, code, label, description, "
                    "allowed_source_types, allowed_target_types, status, created_at, updated_at) "
                    "VALUES (:id, :project_id, 'link_type', 'no_endpoints', NULL, NULL, "
                    "'[]', '[]', 'active', now(), now())"
                ),
                {"id": str(uuid4()), "project_id": project_id},
            )

    command.downgrade(alembic_config, "a3e7c1f9b5d2")

    assert (
        scalar(
            engine,
            "SELECT project_code FROM projects WHERE project_code='FDE-V3-TYPE-KEEP'",
        )
        == "FDE-V3-TYPE-KEEP"
    )
    assert "ontology_relation_types" not in table_names(engine)

    command.upgrade(alembic_config, "head")
    cleanup_seeded_rows(engine, ids, project_id=project_id, sop_node_id=sop_node_id)
    # 回到 head 后重灌引用种子（幂等），保证后续用例面对标准状态。
    seed_reference_data(engine.url.render_as_string(hide_password=False))


def test_v3_change_set_table_roundtrip_preserves_projects(alembic_config, engine):
    """V3 T-O3：变更集增量——downgrade 表消失、upgrade 回 head 重建；两向都不碰
    projects 行；head 上状态 CHECK 生效（非法状态拒）、载荷 JSON 落行可读。"""
    command.downgrade(alembic_config, "b8d3f1a5c7e2")
    assert "ontology_change_sets" not in table_names(engine)
    ids = seed_user_and_template(engine, username="migration.v3-cs-keep")
    project_id, sop_node_id = seed_project(engine, ids, project_code="FDE-V3-CS-KEEP")

    command.upgrade(alembic_config, "head")

    assert "ontology_change_sets" in table_names(engine)
    assert (
        scalar(
            engine,
            "SELECT project_code FROM projects WHERE project_code='FDE-V3-CS-KEEP'",
        )
        == "FDE-V3-CS-KEEP"
    )

    set_id = str(uuid4())
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO ontology_change_sets "
                "(id, project_id, title, proposed_json, diff_summary, status, "
                "base_snapshot_sha256, captured_from, created_at, updated_at) "
                "VALUES (:id, :project_id, '术语候选一批', "
                "'[{\"action\": \"create_term\", \"term\": \"交付包\", "
                "\"definition\": \"一次交付的物量集合。\"}]', "
                "'新建术语 1', 'in_review', "
                "'0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef', "
                "'agent_run:11111111-1111-4111-8111-111111111111', now(), now())"
            ),
            {"id": set_id, "project_id": project_id},
        )
    row = scalar(
        engine,
        "SELECT proposed_json FROM ontology_change_sets WHERE id = :id",
        {"id": set_id},
    )
    assert row[0]["action"] == "create_term"
    assert row[0]["term"] == "交付包"

    # 状态 CHECK：非法状态被拒
    with pytest.raises(IntegrityError):
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO ontology_change_sets "
                    "(id, project_id, title, proposed_json, status, created_at, updated_at) "
                    "VALUES (:id, :project_id, '坏状态', '[]', 'pending', now(), now())"
                ),
                {"id": str(uuid4()), "project_id": project_id},
            )

    command.downgrade(alembic_config, "b8d3f1a5c7e2")

    assert (
        scalar(
            engine,
            "SELECT project_code FROM projects WHERE project_code='FDE-V3-CS-KEEP'",
        )
        == "FDE-V3-CS-KEEP"
    )
    assert "ontology_change_sets" not in table_names(engine)

    command.upgrade(alembic_config, "head")
    cleanup_seeded_rows(engine, ids, project_id=project_id, sop_node_id=sop_node_id)
    # 回到 head 后重灌引用种子（幂等），保证后续用例面对标准状态。
    seed_reference_data(engine.url.render_as_string(hide_password=False))


def test_v4_subject_type_domain_roundtrip_preserves_subjects(alembic_config, engine):
    """V3 T-O2b：值域开放——head 上 CHECK 是码格式（注册码过、坏格式拒）、列宽
    60；downgrade 回枚举时存量注册码行会被枚举 CHECK 挡下（保护语义，删行后
    降级才放行）；降级后列宽回 32、项目行不丢、注册码落行被拒；再 upgrade 存量
    内置行原样保留（枚举值是格式的子集，双向兼容）。"""
    # 自愈：上一轮本测试若中途崩溃会留下格式合法但非枚举的行，挡住后续
    # 任何降级——先清掉这类行再开始（内置行不受影响）。
    with engine.begin() as connection:
        connection.execute(
            text(
                "DELETE FROM project_research_subjects WHERE subject_type NOT IN "
                "('project', 'department', 'role', 'process', 'opportunity')"
            )
        )
    command.downgrade(alembic_config, "b8d3f1a5c7e2")
    ids = seed_user_and_template(engine, username="migration.v4-domain-keep")
    project_id, sop_node_id = seed_project(engine, ids, project_code="FDE-V4-DOMAIN")

    command.upgrade(alembic_config, "head")

    # head：列宽 60，注册码（非内置枚举）可落行
    character_max = scalar(
        engine,
        "SELECT character_maximum_length FROM information_schema.columns "
        "WHERE table_schema = current_schema() "
        "AND table_name='project_research_subjects' AND column_name='subject_type'",
    )
    assert character_max == 60
    subject_id = str(uuid4())
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO project_research_subjects "
                "(id, project_id, subject_type, subject_key, name, description, memo, "
                "status, version, sort_order, tracking_code, created_at, updated_at) "
                "VALUES (:id, :project_id, 'vendor_site', 'vendor_site_main', "
                "'供应商站点', '', '', 'active', 1, 0, NULL, now(), now())"
            ),
            {"id": subject_id, "project_id": project_id},
        )
    # head：坏格式被拒——大写开头是 CHECK 违例（IntegrityError）；
    # 61 字符先撞列宽 varchar(60)（DataError）
    with pytest.raises(IntegrityError):
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO project_research_subjects "
                    "(id, project_id, subject_type, subject_key, name, description, memo, "
                    "status, version, sort_order, tracking_code, created_at, updated_at) "
                    "VALUES (:id, :project_id, 'VendorSite', 'bad_case', '坏码', '', '', "
                    "'active', 1, 0, NULL, now(), now())"
                ),
                {"id": str(uuid4()), "project_id": project_id},
            )
    with pytest.raises(DataError):
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO project_research_subjects "
                    "(id, project_id, subject_type, subject_key, name, description, memo, "
                    "status, version, sort_order, tracking_code, created_at, updated_at) "
                    "VALUES (:id, :project_id, :code, 'long_case', '超长码', '', '', "
                    "'active', 1, 0, NULL, now(), now())"
                ),
                {"id": str(uuid4()), "project_id": project_id, "code": "a" * 61},
            )

    # 降级保护语义（迁移 downgrade 的第一撞）：存量注册码行在 → 重加枚举
    # CHECK 被拒。用裸 SQL 事务复现同一 DB 语义（engine.begin 异常即回滚），
    # 不把失败的 alembic 命令包进 pytest.raises——失败的迁移可能泄漏连接/锁，
    # 挡死同一库上的后续迁移命令。
    with pytest.raises(DBAPIError):
        with engine.begin() as connection:
            connection.execute(
                text(
                    "ALTER TABLE project_research_subjects DROP CONSTRAINT "
                    "ck_project_research_subjects_subject_type"
                )
            )
            connection.execute(
                text(
                    "ALTER TABLE project_research_subjects ADD CONSTRAINT "
                    "ck_project_research_subjects_subject_type CHECK (subject_type IN "
                    "('project', 'department', 'role', 'process', 'opportunity'))"
                )
            )
    assert (
        scalar(
            engine,
            "SELECT subject_type FROM project_research_subjects WHERE id = :id",
            {"id": subject_id},
        )
        == "vendor_site"
    )

    # 删掉注册码行后降级放行：列宽回 32，项目行保留，注册码再落行被枚举拒
    with engine.begin() as connection:
        connection.execute(
            text("DELETE FROM project_research_subjects WHERE id = :id"),
            {"id": subject_id},
        )
    command.downgrade(alembic_config, "b8d3f1a5c7e2")

    character_max = scalar(
        engine,
        "SELECT character_maximum_length FROM information_schema.columns "
        "WHERE table_schema = current_schema() "
        "AND table_name='project_research_subjects' AND column_name='subject_type'",
    )
    assert character_max == 32
    with pytest.raises(IntegrityError):
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO project_research_subjects "
                    "(id, project_id, subject_type, subject_key, name, description, memo, "
                    "status, version, sort_order, tracking_code, created_at, updated_at) "
                    "VALUES (:id, :project_id, 'vendor_site', 'vendor_down', '降级站点', '', '', "
                    "'active', 1, 0, NULL, now(), now())"
                ),
                {"id": str(uuid4()), "project_id": project_id},
            )

    command.upgrade(alembic_config, "head")

    # 再升级：内置类型存量行原样保留（枚举 ⊂ 格式，双向兼容）
    builtin_id = str(uuid4())
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO project_research_subjects "
                "(id, project_id, subject_type, subject_key, name, description, memo, "
                "status, version, sort_order, tracking_code, created_at, updated_at) "
                "VALUES (:id, :project_id, 'department', 'dept_main', '销售部', '', '', "
                "'active', 1, 0, NULL, now(), now())"
            ),
            {"id": builtin_id, "project_id": project_id},
        )
    assert (
        scalar(
            engine,
            "SELECT subject_type FROM project_research_subjects WHERE id = :id",
            {"id": builtin_id},
        )
        == "department"
    )
    with engine.begin() as connection:
        connection.execute(
            text("DELETE FROM project_research_subjects WHERE id = :id"),
            {"id": builtin_id},
        )
    cleanup_seeded_rows(engine, ids, project_id=project_id, sop_node_id=sop_node_id)
    # 回到 head 后重灌引用种子（幂等），保证后续用例面对标准状态。
    seed_reference_data(engine.url.render_as_string(hide_password=False))


# ---------------------------------------------------------------------------
# goal-c CR-002：conftest 外来戳自愈（_reconcile_test_schema 三分支）回归钉
# 共享测试库被另一 worktree 盖成本树之外的 revision 时，downgrade base 会报
# "Can't locate revision" 致全量 DB 用例 setup 即 E。conftest 现按「空/base→
# upgrade、链内→roundtrip、外来→DROP SCHEMA 重建+upgrade」三分支自愈；本三条
# 钉住「本树 revision 集判定」「外来戳识别」两个纯函数面（不依赖 live DB，
# 故 CI/多 worktree 并发下也稳定），外加 T-I1 前置热修面：全新库探测撞缺表
# 吞错后连接必须已回滚（否则会话末解锁撞 InFailedSqlTransaction，CI 必红）。
# ---------------------------------------------------------------------------


def test_known_alembic_revisions_covers_current_head(test_settings):
    """本树判定基准必须包含当前 HEAD_REVISION（含 50 个迁移文件全集）。"""
    from alembic.config import Config

    config = Config(str(SERVER_ROOT / "alembic.ini"))
    known = _known_alembic_revisions(config)
    assert HEAD_REVISION in known
    # 迁移文件全集权威=alembic ScriptDirectory（V3.1 P1-1 e7c4a9d2f6b8 +
    # 商业化 G1 e9c4a1f7b3d2 + 商业化 G2 b3e7c9d1a5f2 之后 = 52）；
    # v3-workbench-inventory.json 的 revision_count 为审计快照（随清单重生成同步）
    assert len(known) == 52
    # 链内任意已落戳都在集内（下探若干历史 revision 抽样）
    for historical in ("b5d9e3f7a1c6", "c9e3a7d1b5f8", "ebb003a5c3a8"):
        assert historical in known, historical


def _parse_migration_graph() -> tuple[set[str], set[str]]:
    """解析迁移目录成 (revision 集, down_revision 集)。

    head 定义与 AGENTS「口径数字引用前现测」一致＝revision 集减 down_revision 集。
    直接读文件而不依赖 alembic ScriptDirectory 内部 API（`versions`/
    `iterate_revisions` 在不同 alembic 版有差异——conftest 同款理由）；
    down_revision 支持三种形态：None（基线）、"id"（单前驱）、("a","b")（合并迁移）。
    """
    versions_dir = SERVER_ROOT / "migrations" / "versions"
    revisions: set[str] = set()
    down_revisions: set[str] = set()
    for path in sorted(versions_dir.glob("*.py")):
        body = path.read_text(encoding="utf-8")
        revision_match = re.search(
            r'^revision(?::\s*[^=]+)?\s*=\s*["\']([a-f0-9]+)["\']',
            body,
            flags=re.MULTILINE,
        )
        assert revision_match is not None, f"{path.name} 未声明 revision"
        revisions.add(revision_match.group(1))
        down_match = re.search(
            r'^down_revision(?::\s*[^=]+)?\s*=\s*(.+)$', body, flags=re.MULTILINE
        )
        if down_match is None:
            continue
        down_revisions.update(re.findall(r'["\']([a-f0-9]+)["\']', down_match.group(1)))
    return revisions, down_revisions


def test_alembic_chain_has_exactly_one_head():
    """迁移链必须恰好一个 head（架构评估 P1-1 机械闸）。

    事故史：#215（e7c4a9d2f6b8）与商业化 G1（e9c4a1f7b3d2）曾同挂一个
    down_revision 形成双头，事后靠人工 rebase 消解——这里把它变成机器闸，
    双头 PR 直接红（宁红不漏）。两个独立来源互校：①文件解析（revision 集
    减 down_revision 集）②alembic 自身 ScriptDirectory.get_heads() 图遍历。
    """
    revisions, down_revisions = _parse_migration_graph()
    heads = revisions - down_revisions
    assert len(heads) == 1, (
        f"迁移链必须恰好一个 head，实测 {len(heads)} 个：{sorted(heads)}"
        "——双头（两条迁移同挂一个 down_revision）会让 alembic upgrade head "
        "的行为不确定（升到哪条取决于字典序）"
    )
    assert next(iter(heads)) == HEAD_REVISION, (
        f"唯一 head {sorted(heads)[0]} != HEAD_REVISION {HEAD_REVISION}"
        "——新增迁移后忘了同步本文件顶部的 HEAD_REVISION 常量"
    )

    from alembic.config import Config
    from alembic.script import ScriptDirectory

    config = Config(str(SERVER_ROOT / "alembic.ini"))
    script_heads = set(ScriptDirectory.from_config(config).get_heads())
    assert script_heads == heads, (
        f"alembic 自身遍历出的 head {sorted(script_heads)} != 文件解析出的 "
        f"{sorted(heads)}——两个来源不一致即链结构异常，先查迁移文件再跑"
    )


def test_foreign_stamp_recognized_as_outside_tree(engine, test_settings):
    """外来戳（本树 34 revision 之外）必被判为外来；当前 live 头在集内。"""
    from alembic.config import Config

    config = Config(str(SERVER_ROOT / "alembic.ini"))
    known = _known_alembic_revisions(config)
    # 构造一个本树必然不存在的 revision 形
    foreign = "9" * 12
    assert foreign not in known
    # live DB 当前戳（会话 fixture 已迁移到 head）必在集内
    live_stamp = _current_alembic_stamp(engine.connect())
    assert live_stamp is not None
    assert live_stamp in known


def test_stamp_probe_missing_table_rolls_back_connection(engine):
    """fresh-DB 路径回归钉（CR-002 首版 CI 红根因，T-I1 前置热修）：把
    search_path 指到无 alembic_version 的 pg_catalog，复现 CI 全新库「探测
    撞缺表」——探测须返回 None 且吞错后连接已回滚（否则持锁连接留在
    aborted 态，会话末 pg_advisory_unlock 撞 InFailedSqlTransaction，服务端
    CI 整列必红）。不动真实 alembic_version：会话 fixture 的持锁事务持有其
    ACCESS SHARE 直至会话结束，RENAME 会自锁死等。"""
    with engine.connect() as conn:
        conn.execute(text("SET search_path = pg_catalog"))
        try:
            assert _current_alembic_stamp(conn) is None
            # 探测吞错后同一连接仍可执行语句（未被留在 aborted 态）
            assert conn.execute(text("SELECT 1")).scalar() == 1
        finally:
            conn.execute(text("RESET search_path"))


def _column_names(engine, table: str) -> set[str]:
    from sqlalchemy import inspect

    return {col["name"] for col in inspect(engine).get_columns(table)}


def _agent_status_check_ddl(engine) -> str:
    # 按当前 schema 限定命名空间：pg_constraint / pg_class / pg_namespace 跨库可见，
    # 同库若存在兄弟 schema（并行跑的遗留 schema）同名约束会一并命中——
    # scalar_one_or_none() 将抛 MultipleResultsFound（与被测迁移无关的假失败）。
    return scalar(
        engine,
        "SELECT pg_get_constraintdef(c.oid) FROM pg_constraint c "
        "JOIN pg_class t ON t.oid = c.conrelid "
        "JOIN pg_namespace n ON n.oid = t.relnamespace "
        "WHERE c.conname = 'ck_agent_runs_status' "
        "AND n.nspname = current_schema()",
    )


def test_p0_code_batch_columns_roundtrip_preserves_projects(alembic_config, engine):
    """B#1/B#28/B#2 合并迁移（b2e8f4a6c9d3）：两列增量 + 回执终态 CHECK 两向
    可逆——downgrade 列消失且 CHECK 收紧（回执终态归位 failed），projects 行
    与既有业务表全程不受影响。"""
    command.upgrade(alembic_config, "head")
    assert {"hops"} <= _column_names(engine, "workflow_runs")
    assert {"lifecycle_version"} <= _column_names(engine, "gates")
    assert "succeeded_but_receipt_invalid" in _agent_status_check_ddl(engine)
    ids = seed_user_and_template(engine, username="migration.p0-code-keep")
    seed_project(engine, ids, project_code="FDE-V3-P0-CODE-KEEP")

    command.downgrade(alembic_config, "d9f4a7c2e6b1")

    assert not {"hops"} & _column_names(engine, "workflow_runs")
    assert not {"lifecycle_version"} & _column_names(engine, "gates")
    assert "succeeded_but_receipt_invalid" not in _agent_status_check_ddl(engine)
    assert (
        scalar(
            engine,
            "SELECT project_code FROM projects WHERE project_code='FDE-V3-P0-CODE-KEEP'",
        )
        == "FDE-V3-P0-CODE-KEEP"
    )

    command.upgrade(alembic_config, "head")

    assert {"hops"} <= _column_names(engine, "workflow_runs")
    assert {"lifecycle_version"} <= _column_names(engine, "gates")
    assert "succeeded_but_receipt_invalid" in _agent_status_check_ddl(engine)
    assert (
        scalar(
            engine,
            "SELECT project_code FROM projects WHERE project_code='FDE-V3-P0-CODE-KEEP'",
        )
        == "FDE-V3-P0-CODE-KEEP"
    )
