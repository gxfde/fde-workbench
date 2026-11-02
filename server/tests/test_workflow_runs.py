"""V3 T-W2：workflow 运行层两表——run 固定版本 + 幂等键 + 节点状态机。

覆盖 workflow-dag-v1 §2 的表契约：run 级 idempotency_key 全局唯一（修 fde-v2
FV-F3）、UNIQUE(run_id, node_key)、status/node_type CHECK、CASCADE（run→node_runs、
project→runs）与 RESTRICT（definitions←runs）。执行器行为在 T-W3。
"""
from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError

from test_agents_d4_harness import make_user
from test_document_drafts_api import _persist_project
from test_workflow_definition import _dag, _call

from fde_api.workbench.models import Project
from fde_api.workflows.definition_service import create_definition
from fde_api.workflows.models import (
    WorkflowDefinition,
    WorkflowNodeRun,
    WorkflowRun,
)


def _make_definition(db_session, leader, project) -> WorkflowDefinition:
    # 带库校验走 registry（call 白名单=api_catalog，无需种子 skill），用纯 call 链
    dag = _dag(
        _call("gather", output="subjects"),
        _call("draft", ["gather"], output="hint"),
    )
    definition = create_definition(
        db_session, actor=leader, project_id=project.id, name=f"编排{uuid4().hex[:4]}", dag=dag
    )
    db_session.commit()
    return definition


def _make_run(db_session, definition, project, leader, key=None) -> WorkflowRun:
    run = WorkflowRun(
        definition_id=definition.id,
        definition_version=definition.version,
        project_id=project.id,
        initiated_by_user_id=leader.id,
        idempotency_key=key or f"run-{uuid4().hex}",
        context_json={"project_id": project.id},
    )
    db_session.add(run)
    db_session.flush()
    return run


def _make_node(run, key, *, node_type="call", depends_on=(), **extra) -> WorkflowNodeRun:
    return WorkflowNodeRun(
        run_id=run.id,
        node_key=key,
        node_type=node_type,
        depends_on=list(depends_on),
        **extra,
    )


def test_run_defaults_pin_version_and_carry_context(db_session, settings):
    """新建 run：status=queued、context 落库、definition_version 固定为创建时版本；
    节点行默认 pending / attempt=0，depends_on 快照原样保留。"""
    leader = make_user(db_session, "project_lead")
    project = _persist_project(db_session, leader, code=f"WR{uuid4().hex[:4]}")
    definition = _make_definition(db_session, leader, project)

    run = _make_run(db_session, definition, project, leader)
    db_session.add(_make_node(run, "gather", input_snapshot={"params": {"q": "x"}}))
    db_session.add(_make_node(run, "draft", node_type="skill", depends_on=["gather"], status="ready"))
    db_session.commit()

    stored = db_session.execute(select(WorkflowRun).where(WorkflowRun.id == run.id)).scalar_one()
    assert stored.status == "queued"
    assert stored.definition_version == definition.version == 1
    assert stored.context_json == {"project_id": project.id}
    assert stored.error is None and stored.started_at is None and stored.finished_at is None

    nodes = {
        n.node_key: n
        for n in db_session.execute(
            select(WorkflowNodeRun).where(WorkflowNodeRun.run_id == run.id)
        ).scalars()
    }
    assert set(nodes) == {"gather", "draft"}
    assert nodes["gather"].status == "pending" and nodes["gather"].attempt == 0
    assert nodes["gather"].input_snapshot == {"params": {"q": "x"}}
    assert nodes["draft"].node_type == "skill" and nodes["draft"].status == "ready"
    assert nodes["draft"].depends_on == ["gather"]


def test_run_idempotency_key_is_globally_unique(db_session, settings):
    """FV-F3 修复的表级保证：同 key 跨定义/项目也不允许建第二个 run。"""
    leader = make_user(db_session, "project_lead")
    project = _persist_project(db_session, leader, code=f"WR{uuid4().hex[:4]}")
    definition = _make_definition(db_session, leader, project)

    key = f"idem-{uuid4().hex}"
    _make_run(db_session, definition, project, leader, key=key)
    db_session.commit()

    other = _make_definition(db_session, leader, project)
    with pytest.raises(IntegrityError):
        _make_run(db_session, other, project, leader, key=key)
        db_session.flush()
    db_session.rollback()


def test_node_key_unique_within_run_only(db_session, settings):
    """UNIQUE(run_id, node_key)：同一 run 内重复 node_key 拒绝；不同 run 同名允许。"""
    leader = make_user(db_session, "project_lead")
    project = _persist_project(db_session, leader, code=f"WR{uuid4().hex[:4]}")
    definition = _make_definition(db_session, leader, project)

    run = _make_run(db_session, definition, project, leader)
    db_session.add(_make_node(run, "gather"))
    db_session.commit()

    with pytest.raises(IntegrityError):
        db_session.add(_make_node(run, "gather"))
        db_session.flush()
    db_session.rollback()

    second = _make_run(db_session, definition, project, leader)
    db_session.add(_make_node(second, "gather"))
    db_session.commit()  # 不同 run 同名节点合法


@pytest.mark.parametrize(
    ("column", "value"),
    [
        ("status", "flying"),
        ("status", None),
        ("idempotency_key", None),
        ("definition_version", 0),
    ],
)
def test_run_column_guards(db_session, settings, column, value):
    """status 白名单 / idempotency_key 非空 / definition_version 非零由 DB 层拒绝。"""
    leader = make_user(db_session, "project_lead")
    project = _persist_project(db_session, leader, code=f"WR{uuid4().hex[:4]}")
    definition = _make_definition(db_session, leader, project)

    run = _make_run(db_session, definition, project, leader)
    with pytest.raises(IntegrityError):
        setattr(run, column, value)
        db_session.flush()
    db_session.rollback()


def test_node_run_type_and_status_guards(db_session, settings):
    """node_type 白名单四类、status 白名单八态由 CHECK 拒绝。"""
    leader = make_user(db_session, "project_lead")
    project = _persist_project(db_session, leader, code=f"WR{uuid4().hex[:4]}")
    definition = _make_definition(db_session, leader, project)
    run = _make_run(db_session, definition, project, leader)

    with pytest.raises(IntegrityError):
        db_session.add(_make_node(run, "wait", node_type="wait"))
        db_session.flush()
    db_session.rollback()

    with pytest.raises(IntegrityError):
        db_session.add(_make_node(run, "go", status="queued"))
        db_session.flush()
    db_session.rollback()


def test_deleting_run_cascades_node_runs(db_session, settings):
    """run 删除 → 其 node_runs 随之消失（恢复/清理语义）。"""
    leader = make_user(db_session, "project_lead")
    project = _persist_project(db_session, leader, code=f"WR{uuid4().hex[:4]}")
    definition = _make_definition(db_session, leader, project)
    run = _make_run(db_session, definition, project, leader)
    db_session.add(_make_node(run, "gather"))
    db_session.commit()

    db_session.execute(delete(WorkflowRun).where(WorkflowRun.id == run.id))
    db_session.commit()
    assert (
        db_session.execute(
            select(WorkflowNodeRun).where(WorkflowNodeRun.run_id == run.id)
        ).scalar_one_or_none()
        is None
    )


def test_definition_delete_restricted_while_runs_exist(db_session, settings):
    """runs.definition_id RESTRICT：执行史在，定义不可静默删除（先清 runs）。"""
    leader = make_user(db_session, "project_lead")
    project = _persist_project(db_session, leader, code=f"WR{uuid4().hex[:4]}")
    definition = _make_definition(db_session, leader, project)
    _make_run(db_session, definition, project, leader)
    db_session.commit()

    with pytest.raises(IntegrityError):
        db_session.execute(delete(WorkflowDefinition).where(WorkflowDefinition.id == definition.id))
        db_session.flush()
    db_session.rollback()


def test_project_delete_cascades_runs(db_session, settings):
    """runs.project_id CASCADE：项目删除在 DB 层带走其 runs 与 node_runs（项目隔离
    约定）；平台模板定义（project_id NULL）不阻拦项目删除。"""
    leader = make_user(db_session, "project_lead")
    project = _persist_project(db_session, leader, code=f"WR{uuid4().hex[:4]}")
    # 平台模板：定义挂在项目外（project_id NULL）
    template = create_definition(
        db_session,
        actor=leader,
        project_id=None,
        name=f"模板{uuid4().hex[:4]}",
        dag=_dag(_call("gather")),
    )
    run = _make_run(db_session, template, project, leader)
    db_session.add(_make_node(run, "gather"))
    db_session.commit()
    run_id = run.id

    db_session.execute(delete(Project).where(Project.id == project.id))
    db_session.commit()

    assert (
        db_session.execute(select(WorkflowRun).where(WorkflowRun.id == run_id)).scalar_one_or_none()
        is None
    )
    assert (
        db_session.execute(
            select(WorkflowNodeRun).where(WorkflowNodeRun.run_id == run_id)
        ).scalar_one_or_none()
        is None
    )
