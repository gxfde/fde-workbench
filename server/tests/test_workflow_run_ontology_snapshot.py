"""V3.3 M4-WP3 D27 / 任务书 §9.3：WorkflowRun 本体版本五元组不可变落痕（TDD 红→绿）。

覆盖条款：
- 每次 Workflow Run 发起时冻结实际使用的本体版本五元组：ontology_id /
  ontology_version / tool_logic_action_version / datasource_mapping_version /
  workflow_version（+ org_id 与 pinned_version_id 审计指针）——取自项目活跃
  ``ProjectOntologyBinding``（S-13 语义：run 发起即钉住，后续绑定升级不回写）；
- 无活跃绑定的 run 落 NULL（诚实缺省——未使用本体面不伪造记录）；
- ``workflow_runs.ontology_snapshot_json`` 写后不可变：已落值后再改动即在
  flush 前响亮失败（ORM before_update 守卫，非仅纪律）；
- ``serialize_run`` 详情视图携带 ``ontology_snapshot_json``。

节点类型复用既有四类（D27：零新增节点类型，ontology 能力经 call/skill 工具面表达）。
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from test_agents_d4_harness import make_user
from test_document_drafts_api import _persist_project
from test_workflow_executor import _make_definition, _node, _start

from fde_api.integrations.models import ACTIVE_MARKER, ProjectOntologyBinding
from fde_api.workflows.executor import WorkflowRunError
from fde_api.workflows.models import WorkflowRun
from fde_api.workflows.serialization import serialize_run


def _make_binding(db_session: Session, leader, project, *, version: str) -> ProjectOntologyBinding:
    binding = ProjectOntologyBinding(
        org_id=project.org_id or f"org-{uuid4().hex[:8]}",
        project_id=project.id,
        ontology_id="ont-seed-mfg",
        pinned_version_id=f"ver-seed-{version}",
        pinned_version=version,
        binding_role="primary",
        status="active",
        active_marker=ACTIVE_MARKER,
        bound_by_user_id=leader.id,
    )
    db_session.add(binding)
    db_session.commit()
    return binding


def test_run_stamps_ontology_snapshot_from_active_binding(db_session: Session, settings) -> None:
    """§9.3：发起 run 即从活跃绑定冻结五元组快照，serialize_run 携带。"""
    leader = make_user(db_session, "project_lead")
    project = _persist_project(db_session, leader, code=f"WO{uuid4().hex[:4]}")
    _make_binding(db_session, leader, project, version="1.0.0")
    definition = _make_definition(
        db_session, leader, project, _node("gather", output="subjects"), publish=True
    )

    run, created = _start(db_session, leader, project, definition)
    assert created
    snap = run.ontology_snapshot_json
    assert snap is not None, "有活跃绑定时必须冻结五元组快照（§9.3）"
    assert snap["ontology_id"] == "ont-seed-mfg"
    assert snap["ontology_version"] == "1.0.0"
    assert snap["pinned_version_id"] == "ver-seed-1.0.0"
    for key in (
        "ontology_id",
        "ontology_version",
        "tool_logic_action_version",
        "datasource_mapping_version",
        "workflow_version",
    ):
        assert key in snap, f"§9.3 五元组缺 {key}"

    view = serialize_run(run, ())
    assert view["ontology_snapshot_json"] == snap


def test_run_without_binding_stamps_null(db_session: Session, settings) -> None:
    """无活跃绑定的 run 落 NULL——诚实缺省，不伪造本体记录。"""
    leader = make_user(db_session, "project_lead")
    project = _persist_project(db_session, leader, code=f"WO{uuid4().hex[:4]}")
    definition = _make_definition(
        db_session, leader, project, _node("gather", output="subjects"), publish=True
    )

    run, created = _start(db_session, leader, project, definition)
    assert created
    assert run.ontology_snapshot_json is None
    assert serialize_run(run, ())["ontology_snapshot_json"] is None


def test_snapshot_immutable_after_insert(db_session: Session, settings) -> None:
    """D27 不可变守卫：已落值后再改动即在 flush 前响亮失败（不许悄悄换版本）。"""
    leader = make_user(db_session, "project_lead")
    project = _persist_project(db_session, leader, code=f"WO{uuid4().hex[:4]}")
    _make_binding(db_session, leader, project, version="1.0.0")
    definition = _make_definition(
        db_session, leader, project, _node("gather", output="subjects"), publish=True
    )
    run, _ = _start(db_session, leader, project, definition)
    original = dict(run.ontology_snapshot_json)

    run.ontology_snapshot_json = {**original, "ontology_version": "9.9.9"}
    with pytest.raises(RuntimeError, match="immutable"):
        db_session.commit()
    db_session.rollback()
    assert run.ontology_snapshot_json["ontology_version"] == "1.0.0"


def test_binding_upgrade_does_not_rewrite_existing_runs(db_session: Session, settings) -> None:
    """§9.3：绑定升级（retire 旧 + successor 新版本）后，既有 run 快照保持 v1。"""
    leader = make_user(db_session, "project_lead")
    project = _persist_project(db_session, leader, code=f"WO{uuid4().hex[:4]}")
    old_binding = _make_binding(db_session, leader, project, version="1.0.0")
    definition = _make_definition(
        db_session, leader, project, _node("gather", output="subjects"), publish=True
    )
    run_v1, _ = _start(db_session, leader, project, definition)
    assert run_v1.ontology_snapshot_json["ontology_version"] == "1.0.0"

    # 升级：旧绑定 retire（active_marker 退出唯一键）+ 新版本 successor 入场
    old_binding.active_marker = None
    old_binding.status = "retired"
    _make_binding(db_session, leader, project, version="2.0.0")
    db_session.commit()

    run_v2, _ = _start(db_session, leader, project, definition)
    assert run_v2.ontology_snapshot_json["ontology_version"] == "2.0.0"
    db_session.refresh(run_v1)
    assert run_v1.ontology_snapshot_json["ontology_version"] == "1.0.0"


def test_workflow_run_error_still_carries_status_contract() -> None:
    """回归锚：WorkflowRunError 四元契约不变（守卫变更未波及错误面）。"""
    err = WorkflowRunError("invalid_request", "boom", 400)
    assert err.status == 400 and err.code == "invalid_request"
