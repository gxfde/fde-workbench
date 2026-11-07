"""V3.2 G2 迁移契约：simulation_scenarios 单表。

钉住：
1. **表形状**：列、CHECK、UNIQUE、索引与模型一致（`alembic check` 另在
   ``test_migrations.py`` 断言元数据与迁移同步）。
2. **两向安全**：downgrade 一步即消失、upgrade 回 head 重建；两向都不碰
   ``projects`` 行（模拟表**没有** project 外键——P1 隔离落点）。
3. **隔离落点**：表结构里**不存在** project_id 列——这不是遗漏，是设计。
"""
from __future__ import annotations

from alembic import command
from sqlalchemy import inspect

from test_migrations import scalar, seed_project, seed_user_and_template, table_names

SIMULATION_TABLE = "simulation_scenarios"
PREVIOUS_HEAD = "e5f1a7c3b9d4"


def test_simulation_scenarios_table_exists_at_head(engine):
    assert SIMULATION_TABLE in table_names(engine)

    columns = {column["name"] for column in inspect(engine).get_columns(SIMULATION_TABLE)}
    assert {
        "id",
        "scenario_key",
        "name",
        "industry",
        "variant",
        "difficulty",
        "split",
        "status",
        "tags",
        "content_json",
        "reference_json",
        "rubric_version",
        "source_kind",
        "source_ref",
        "note",
        "created_by_user_id",
        "version",
        "created_at",
        "updated_at",
    } == columns


def test_simulation_scenarios_has_no_project_column(engine):
    """隔离落点：模拟表**没有** project_id 列（模拟对象不属任何真实项目）。"""
    columns = {column["name"] for column in inspect(engine).get_columns(SIMULATION_TABLE)}
    assert "project_id" not in columns


def test_simulation_scenarios_constraints_and_indexes(engine):
    inspector = inspect(engine)

    unique = {
        tuple(constraint["column_names"])
        for constraint in inspector.get_unique_constraints(SIMULATION_TABLE)
    }
    assert ("scenario_key", "variant", "version") in unique

    checks = {
        constraint["name"]
        for constraint in inspector.get_check_constraints(SIMULATION_TABLE)
    }
    assert {
        "ck_simulation_scenarios_variant",
        "ck_simulation_scenarios_split",
        "ck_simulation_scenarios_status",
        "ck_simulation_scenarios_difficulty",
        "ck_simulation_scenarios_source_kind",
    } <= checks

    indexes = {index["name"] for index in inspector.get_indexes(SIMULATION_TABLE)}
    assert {
        "ix_simulation_scenarios_split_status",
        "ix_simulation_scenarios_industry",
        "ix_simulation_scenarios_key",
    } <= indexes


def test_simulation_scenarios_roundtrip_preserves_projects(alembic_config, engine):
    """downgrade 一步即消失、upgrade 回 head 重建；两向都不碰 projects 行。"""
    command.downgrade(alembic_config, PREVIOUS_HEAD)
    assert SIMULATION_TABLE not in table_names(engine)
    ids = seed_user_and_template(engine, username="migration.v32-sim-keep")
    seed_project(engine, ids, project_code="FDE-V32-SIM-KEEP")

    command.upgrade(alembic_config, "head")

    assert (
        scalar(
            engine,
            "SELECT project_code FROM projects WHERE project_code='FDE-V32-SIM-KEEP'",
        )
        == "FDE-V32-SIM-KEEP"
    )
    assert SIMULATION_TABLE in table_names(engine)

    command.downgrade(alembic_config, PREVIOUS_HEAD)

    assert (
        scalar(
            engine,
            "SELECT project_code FROM projects WHERE project_code='FDE-V32-SIM-KEEP'",
        )
        == "FDE-V32-SIM-KEEP"
    )
    assert SIMULATION_TABLE not in table_names(engine)

    command.upgrade(alembic_config, "head")
