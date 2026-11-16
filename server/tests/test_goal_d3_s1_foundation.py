"""goal-d3：S1 表簇 + capability +4 + 沙箱基座的基础断言。

V2 四断言在 test_sandbox_isolation.py；本文件钉表簇约束/默认值、
project_solutions 生成来源列与骨架回填、agent.* 能力档位。
"""
from __future__ import annotations

import json
from datetime import date
from uuid import uuid4

import pytest
from alembic import command
from sqlalchemy import inspect, select, text
from sqlalchemy.exc import IntegrityError

from conftest import INITIAL_PASSWORD
from test_document_drafts_api import _persist_project
from test_migrations import (
    cleanup_seeded_rows,
    seed_project,
    seed_user_and_template,
)

from fde_api.agents.models import (
    AgentArtifact,
    AgentRegistry,
    AgentRun,
    AgentToolCall,
    SolutionReviewCheckpoint,
)
from fde_api.auth.models import User
from fde_api.auth.passwords import hash_password
from fde_api.control.access import (
    CAPABILITY_REQUIREMENTS,
    authorize_ai_capability,
    capabilities_for_level,
)
from fde_api.solutions.models import ProjectSolution
from fde_api.workbench.models import Project


def _user(db_session, *, role: str) -> User:
    user = User(
        username=f"d3.{role}.{uuid4().hex}",
        display_name=role,
        role=role,
        password_hash=hash_password(INITIAL_PASSWORD),
        must_change_password=False,
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()
    return user


def _registry_row(**overrides) -> AgentRegistry:
    payload = {
        "kind": "zcode",
        "name": "ZCode 沙箱智能体",
        "capability_tier": "agent.code.write",
        "sandbox_profile": "default",
    }
    payload.update(overrides)
    return AgentRegistry(**payload)


def _run_row(db_session, *, registry: AgentRegistry | None = None, **overrides) -> AgentRun:
    leader = overrides.pop("leader", None) or _user(db_session, role="project_lead")
    project = overrides.pop("project", None)
    if project is None:
        project = _persist_project(db_session, leader, code=f"D3RUN{uuid4().hex[:6]}")
    registry = registry or _registry_row()
    db_session.add(registry)
    db_session.flush()
    payload = {
        "project_id": project.id,
        "agent_id": registry.id,
        "initiated_by_user_id": leader.id,
        "capability_used": "agent.code.write",
        "context_ref": "sandbox-workspaces/run-1/context.md",
        "idempotency_key": f"solution:{uuid4().hex}",
    }
    payload.update(overrides)
    return AgentRun(**payload)


def _solution(db_session, leader_user, *, code: str) -> ProjectSolution:
    project = _persist_project(db_session, leader_user, code=code)
    solution = ProjectSolution(
        project_id=project.id,
        name="交付方案",
        owner_user_id=leader_user.id,
    )
    db_session.add(solution)
    db_session.commit()
    return solution


def test_agent_run_defaults_and_status_check(db_session) -> None:
    row = _run_row(db_session)
    db_session.add(row)
    db_session.commit()
    stored = db_session.get(AgentRun, row.id)
    # 自动交付 §5.1 / §9 原文默认值
    assert stored.status == "queued"
    assert stored.degraded is False
    assert stored.degraded_reason is None
    assert stored.fallback_level is None
    assert stored.retry_of is None
    assert stored.token_cost == 0
    assert stored.duration_ms == 0
    assert stored.cost_owner_type == "project"
    assert stored.handoff_user_id is None

    stored.status = "exploded"
    with pytest.raises(IntegrityError, match="ck_agent_runs_status"):
        db_session.commit()
    db_session.rollback()

    stored = db_session.get(AgentRun, row.id)
    stored.fallback_level = "L9"
    with pytest.raises(IntegrityError, match="ck_agent_runs_fallback_level"):
        db_session.commit()
    db_session.rollback()


def test_agent_registry_kind_check_and_allowed_tools_default(db_session) -> None:
    row = _registry_row(allowed_tools=["read_file", "meeting_convene"])
    db_session.add(row)
    db_session.commit()
    stored = db_session.get(AgentRegistry, row.id)
    assert stored.enabled is False
    assert stored.allowed_tools == ["read_file", "meeting_convene"]
    assert stored.max_cost_units == 0
    assert stored.max_duration_ms == 0

    db_session.add(_registry_row(kind="gpt_wrapper"))
    with pytest.raises(IntegrityError, match="ck_agent_registry_kind"):
        db_session.commit()
    db_session.rollback()


def test_agent_artifact_sha256_and_kind_checks(db_session) -> None:
    run = _run_row(db_session)
    db_session.add(run)
    db_session.commit()
    artifact = AgentArtifact(
        run_id=run.id,
        kind="code",
        storage_ref="engagements/somwyn/.fde/artifacts/run-1/main.py",
        sha256="a" * 64,
    )
    db_session.add(artifact)
    db_session.commit()
    assert db_session.get(AgentArtifact, artifact.id).reviewed is False

    db_session.add(
        AgentArtifact(
            run_id=run.id,
            kind="code",
            storage_ref="engagements/somwyn/.fde/artifacts/run-1/short.py",
            sha256="deadbeef",
        )
    )
    with pytest.raises(IntegrityError, match="ck_agent_artifacts_sha256_len"):
        db_session.commit()
    db_session.rollback()

    db_session.add(
        AgentArtifact(
            run_id=run.id,
            kind="binary",
            storage_ref="engagements/somwyn/.fde/artifacts/run-1/x.bin",
            sha256="b" * 64,
        )
    )
    with pytest.raises(IntegrityError, match="ck_agent_artifacts_kind"):
        db_session.commit()
    db_session.rollback()


def test_agent_tool_call_decision_check(db_session) -> None:
    run = _run_row(db_session)
    db_session.add(run)
    db_session.commit()
    db_session.add(
        AgentToolCall(
            run_id=run.id,
            tool_name="write_file",
            decision="blocked",
            capability="agent.code.write",
        )
    )
    with pytest.raises(IntegrityError, match="ck_agent_tool_calls_decision"):
        db_session.commit()
    db_session.rollback()
    # denied 合法（留痕主场景）
    db_session.add(
        AgentToolCall(
            run_id=run.id,
            tool_name="write_file",
            decision="denied",
            capability="agent.code.write",
            reason="not_in_allowlist",
        )
    )
    db_session.commit()


def test_solution_review_checkpoint_checks_and_default(db_session) -> None:
    leader = _user(db_session, role="project_lead")
    solution = _solution(db_session, leader, code=f"D3CP{uuid4().hex[:6]}")
    row = SolutionReviewCheckpoint(
        solution_id=solution.id,
        checkpoint_type="signoff",
        required_level="project_manager",
    )
    db_session.add(row)
    db_session.commit()
    stored = db_session.get(SolutionReviewCheckpoint, row.id)
    assert stored.status == "pending"
    assert stored.reviewer_user_id is None

    for field, bad in (
        ("checkpoint_type", "vibe"),
        ("required_level", "disabled"),
        ("status", "skipped"),
    ):
        setattr(stored, field, bad)
        with pytest.raises(IntegrityError):
            db_session.commit()
        db_session.rollback()
        stored = db_session.get(SolutionReviewCheckpoint, row.id)


def test_project_solution_generated_by_columns(db_session) -> None:
    leader = _user(db_session, role="project_lead")
    solution = _solution(db_session, leader, code=f"D3GB{uuid4().hex[:6]}")
    # d2 骨架语义列化后的默认：人写草稿，溯源列可空
    assert solution.generated_by == "human"
    assert solution.agent_run_id is None
    assert solution.template_id is None
    assert solution.confidence is None

    solution.generated_by = "ai"
    with pytest.raises(IntegrityError, match="ck_project_solutions_generated_by"):
        db_session.commit()
    db_session.rollback()


def test_agent_run_project_link_from_solution(db_session) -> None:
    """ProjectSolution.agent_run_id ↔ agent_runs 的 RESTRICT 链（清理序依据）。"""
    leader = _user(db_session, role="project_lead")
    run = _run_row(db_session)
    db_session.add(run)
    db_session.commit()
    solution = _solution(db_session, leader, code=f"D3LK{uuid4().hex[:6]}")
    solution.agent_run_id = run.id
    db_session.commit()
    # 被 solution 引用的 run 不可删（RESTRICT）
    with pytest.raises(IntegrityError):
        db_session.delete(run)
        db_session.commit()
    db_session.rollback()


def test_skeleton_template_backfill_from_source_json(engine, alembic_config) -> None:
    """d2 骨架行的行业模板指针列化：升级即回填，generated_by 保持 human。"""
    ids = seed_user_and_template(engine, username="d3-backfill")
    project_id, sop_node_id = seed_project(engine, ids, project_code="D3BACKFILL")
    stale_version_id = str(uuid4())
    solution_rows = [
        (
            str(uuid4()),
            json.dumps(
                {
                    "kind": "skeleton",
                    "industry_template_version_id": ids["template_version_id"],
                }
            ),
        ),
        (
            str(uuid4()),
            json.dumps(
                {
                    "kind": "skeleton",
                    "industry_template_version_id": stale_version_id,
                }
            ),
        ),
        (str(uuid4()), json.dumps({"kind": "manual"})),
    ]
    try:
        # 回到 d2 时的 head：表上还没有生成来源四列（生产升级路径）
        command.downgrade(alembic_config, "c5d7e9f1a3b7")
        with engine.begin() as connection:
            for solution_id, source_json in solution_rows:
                connection.execute(
                    text(
                        "INSERT INTO project_solutions "
                        "(id, project_id, name, design_markdown, deliverables, "
                        "acceptance_criteria, data_systems, schedule, "
                        "risks_dependencies, owner_user_id, source_json) "
                        "VALUES (:id, :project_id, '骨架方案', '', '', '', '', '', "
                        "'', :user_id, CAST(:source_json AS json))"
                    ),
                    {
                        "id": solution_id,
                        "project_id": project_id,
                        "user_id": ids["user_id"],
                        "source_json": source_json,
                    },
                )
        command.upgrade(alembic_config, "head")

        with engine.connect() as connection:
            rows = connection.execute(
                text(
                    "SELECT id, generated_by, template_id, confidence "
                    "FROM project_solutions WHERE project_id = :project_id"
                ),
                {"project_id": project_id},
            ).fetchall()
        by_id = {row[0]: row for row in rows}
        valid, stale, manual = (by_id[row[0]] for row in solution_rows)
        # 有效指针回填；陈旧指针防御性跳过；非骨架行不动
        assert valid[1] == "human"
        assert valid[2] == ids["template_version_id"]
        assert stale[2] is None
        assert manual[2] is None
        for row in (valid, stale, manual):
            assert row[3] is None
    finally:
        with engine.begin() as connection:
            connection.execute(
                text("DELETE FROM project_solutions WHERE project_id = :id"),
                {"id": project_id},
            )
        cleanup_seeded_rows(engine, ids, project_id=project_id, sop_node_id=sop_node_id)


def test_capability_requirements_agent_entries() -> None:
    assert CAPABILITY_REQUIREMENTS["agent.plan.generate"] == "project_operator"
    assert CAPABILITY_REQUIREMENTS["agent.code.write"] == "project_manager"
    assert CAPABILITY_REQUIREMENTS["agent.meeting.convene"] == "project_operator"
    assert CAPABILITY_REQUIREMENTS["agent.system.tool"] == "system_operator"

    operator = capabilities_for_level("project_operator")
    assert "agent.plan.generate" in operator
    assert "agent.meeting.convene" in operator
    assert "agent.code.write" not in operator
    assert "agent.system.tool" not in operator

    manager = capabilities_for_level("project_manager")
    assert "agent.code.write" in manager
    assert "agent.system.tool" not in manager

    system = capabilities_for_level("system_operator")
    for capability in (
        "agent.plan.generate",
        "agent.code.write",
        "agent.meeting.convene",
        "agent.system.tool",
    ):
        assert capability in system


def test_capability_requirements_ontology_entries() -> None:
    """AF1-WP1 收口批：ontology.* 两行入能力矩阵。

    直连循环（ai_tool_loop）与 MCP token 派生（mcp_gateway.issue_mcp_token）
    的 allowed 都从 ``capabilities_for_level`` 取——矩阵缺行时提议档三工具
    在两张 provider 面上被定义过滤/能力闸双重拦死，永远不可达（WP1 第二批
    单元用例被 provider 假件掩盖，真模型端到端必然 0 次工具调用）。
    分级沿工具风险列：dry_validate/logic_run（effect=read）挂 read 行，
    action_propose/execute（write_db，且真执行另有审批闸）挂 write 行。
    """
    assert CAPABILITY_REQUIREMENTS["ontology.read"] == "project_operator"
    assert CAPABILITY_REQUIREMENTS["ontology.write"] == "project_manager"

    viewer = capabilities_for_level("assistant_read")
    assert "ontology.read" not in viewer
    assert "ontology.write" not in viewer

    operator = capabilities_for_level("project_operator")
    assert "ontology.read" in operator
    assert "ontology.write" not in operator

    manager = capabilities_for_level("project_manager")
    assert "ontology.read" in manager
    assert "ontology.write" in manager

    # 可达性非假件钉（verification-gap⑤）：直连循环定义面以真矩阵派生组合——
    # 矩阵缺行时本断言即红（batch-2 既有用例手写注入 allowed，掩盖了该缺口）
    from fde_api.control.ai_tool_loop import tool_definitions

    names = {
        item["function"]["name"]
        for item in tool_definitions(
            capabilities_for_level("project_manager"),
            allowed_tools=[
                "ontology_dry_validate", "ontology_action_propose",
                "ontology_logic_run", "ontology_action_execute",
            ],
        )
    }
    assert {"ontology_dry_validate", "ontology_action_propose", "ontology_logic_run"} <= names
    assert "ontology_action_execute" not in names


def test_authorize_agent_system_tool_is_system_operator_only(db_session) -> None:
    # 档位 = system_operator（架构方案 §6.4 凭证分层），且不要求项目上下文
    operator = _user(db_session, role="admin")
    decision = authorize_ai_capability(user=operator, capability="agent.system.tool")
    assert decision.allowed is True

    leader = _user(db_session, role="project_lead")
    decision = authorize_ai_capability(user=leader, capability="agent.system.tool")
    assert decision.allowed is False
    # 档位不足在 rank 检查处拦截（与既有 system.* 行为一致）
    assert decision.reason == "ai_access_insufficient"


def test_authorize_agent_code_write_requires_manage(db_session) -> None:
    leader = _user(db_session, role="project_lead")
    project = _persist_project(db_session, leader, code=f"D3AUTH{uuid4().hex[:6]}")
    # 项目负责人（project_manager 档）+ 可管理 → 放行
    decision = authorize_ai_capability(
        user=leader, capability="agent.code.write", project=project
    )
    assert decision.allowed is True

    operator = _user(db_session, role="fde_engineer")
    decision = authorize_ai_capability(
        user=operator, capability="agent.code.write", project=project
    )
    assert decision.allowed is False
    assert decision.reason == "ai_access_insufficient"
