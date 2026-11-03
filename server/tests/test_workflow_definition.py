"""V3 T-W1：workflow 定义层——dag_json 校验纯函数 + 定义/不可变版本两表。

覆盖设计 §6 验收用例的定义侧：1 环检测点名、2 未知依赖/引用、3 call.ref 白名单、
7 版本行锁定（发布 v2 后 v1 原样）。执行器用例（4-8、11-12）在 T-W3。
"""
from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import select

from test_agents_d4_harness import make_user, seed_agent
from test_document_drafts_api import _persist_project

from fde_api.control.api_catalog import CATALOG
from fde_api.workbench.models import OperationEvent
from fde_api.workflows.definition_service import (
    WorkflowDefinitionError,
    assert_valid_dag,
    available_agent_refs,
    catalog_call_refs,
    create_definition,
    dag_sha256,
    list_versions,
    publish_definition,
    update_definition_dag,
    validate_dag,
)
from fde_api.workflows.models import WorkflowDefinition, WorkflowDefinitionVersion

CALL = sorted(CATALOG)[0]
REFS = {
    "call_refs": frozenset(CATALOG),
    "skill_refs": frozenset({"workbench-help@3"}),
    "agent_refs": frozenset({"agent-1"}),
}


def _dag(*nodes):
    return {"nodes": list(nodes)}


def _call(key, deps=(), **extra):
    return {"key": key, "type": "call", "ref": CALL, "depends_on": list(deps), **extra}


def _codes(validation):
    return [issue.code for issue in validation.errors]


def test_valid_example_dag_passes_with_topological_order():
    """设计 §2 示例形态全过：call 白名单 / skill 显式版本 / agent 可用 / 审批收口。"""
    dag = _dag(
        _call("gather", output="subjects", params={"project_id": "{{project_id}}"}),
        {"key": "draft", "type": "skill", "ref": "workbench-help@3", "depends_on": ["gather"],
         "output": "hint", "params": {"src": "{{subjects.items}}"}},
        {"key": "classify", "type": "agent", "ref": "agent-1", "depends_on": ["gather"], "max_cost_units": 2},
        {"key": "approve", "type": "human_approval", "depends_on": ["classify"],
         "capability": "workbench.write", "expires_minutes": 15},
    )
    validation = validate_dag(dag, **REFS)
    assert validation.ok, [issue.as_dict() for issue in validation.errors]
    assert validation.warnings == ()
    assert validation.order[0] == "gather"
    assert validation.order.index("approve") > validation.order.index("classify")


def test_cycle_detected_names_cycle_nodes():
    """§6 用例 1：环 DAG → 422 且指明环节点（修 fde-v2 FV-F1 的定义侧）。"""
    dag = _dag(_call("root"), _call("a", ["c"]), _call("b", ["a"]), _call("c", ["b"]))
    validation = validate_dag(dag, **REFS)
    cycle = next(issue for issue in validation.errors if issue.code == "cycle_detected")
    assert set(cycle.detail["nodes"]) == {"a", "b", "c"}
    assert validation.order == ()
    with pytest.raises(WorkflowDefinitionError) as raised:
        assert_valid_dag(validation)
    assert raised.value.status == 422 and raised.value.code == "dag_invalid"
    assert any(issue["code"] == "cycle_detected" for issue in raised.value.detail["errors"])


def test_unknown_dependency_and_refs_and_shapes():
    """§6 用例 2：未知依赖 / 自依赖 / 重复 key / 未知类型 / 未知字段 / 重复 output。"""
    assert "unknown_dependency" in _codes(validate_dag(_dag(_call("a", ["ghost"])), **REFS))
    assert "self_dependency" in _codes(validate_dag(_dag(_call("a", ["a"])), **REFS))
    dup = validate_dag(_dag(_call("a"), _call("a")), **REFS)
    assert "duplicate_node_key" in _codes(dup)
    assert "unknown_node_type" in _codes(validate_dag(_dag({"key": "x", "type": "wait", "ref": CALL}), **REFS))
    assert "unknown_field" in _codes(validate_dag(_dag({**_call("a"), "cron": "0 9 * * *"}), **REFS))
    assert "unknown_field" in _codes(validate_dag({"nodes": [_call("a")], "version": 3}, **REFS))
    assert "duplicate_output" in _codes(validate_dag(_dag(_call("a", output="x"), _call("b", ["a"], output="x")), **REFS))
    assert "output_shadows_context" in _codes(validate_dag(_dag(_call("a", output="project_id")), **REFS))
    assert "invalid_max_retries" in _codes(validate_dag(_dag(_call("a", max_retries=99)), **REFS))
    assert "invalid_effect" in _codes(validate_dag(_dag(_call("a", effect="write")), **REFS))
    assert "invalid_when" in _codes(validate_dag(_dag(_call("a", when="  ")), **REFS))


def test_refs_whitelists_call_skill_agent():
    """§6 用例 3：call.ref 不在 catalog → 422 白名单生效；skill 显式版本且须已存在；agent 须可用。"""
    assert "call_ref_not_whitelisted" in _codes(
        validate_dag(_dag({"key": "x", "type": "call", "ref": "internal.host.exec"}), **REFS)
    )
    assert "invalid_skill_ref" in _codes(validate_dag(_dag({"key": "x", "type": "skill", "ref": "workbench-help"}), **REFS))
    assert "skill_ref_not_published" in _codes(validate_dag(_dag({"key": "x", "type": "skill", "ref": "workbench-help@9"}), **REFS))
    assert "agent_ref_unavailable" in _codes(validate_dag(_dag({"key": "x", "type": "agent", "ref": "ghost"}), **REFS))
    assert "approval_capability_required" in _codes(
        validate_dag(_dag({"key": "x", "type": "human_approval"}), **REFS)
    )
    assert "invalid_expires_minutes" in _codes(
        validate_dag(_dag({"key": "x", "type": "human_approval", "capability": "c", "expires_minutes": 0}), **REFS)
    )
    assert "unexpected_ref" in _codes(validate_dag(_dag({"key": "x", "type": "human_approval", "capability": "c", "ref": CALL}), **REFS))


def test_human_approval_capability_must_be_registered(db_session):
    """T-W4：生产路径（against_registry）注入能力登记表白名单；system.* 不开放。"""
    from fde_api.workflows.definition_service import (
        APPROVAL_CAPABILITIES,
        validate_dag_against_registry,
    )

    assert "workbench.write" in APPROVAL_CAPABILITIES
    assert not any(capability.startswith("system.") for capability in APPROVAL_CAPABILITIES)
    bad = validate_dag_against_registry(
        db_session, _dag({"key": "x", "type": "human_approval", "capability": "made.up.capability"})
    )
    assert "approval_capability_unknown" in _codes(bad)
    good = validate_dag_against_registry(
        db_session, _dag({"key": "x", "type": "human_approval", "capability": "workbench.write"})
    )
    assert good.ok


def test_placeholders_require_upstream_output():
    """占位符规则：上下文键永远可用；output 须为**传递上游**产物；兄弟节点/未知名 → 422。"""
    dag = _dag(
        _call("a", output="x"),
        _call("b", output="y"),
        _call("c", ["a"], params={"ok": "{{x.v}}", "ctx": "{{run_id}}", "bad": "{{y}}"}),
        _call("d", params={"bad": "{{ghost}}"}, deps=[]),
    )
    codes = _codes(validate_dag(dag, **REFS))
    assert "placeholder_not_upstream" in codes
    assert "unknown_placeholder" in codes
    assert not any(issue.node_key == "c" and issue.code == "unknown_placeholder" for issue in validate_dag(dag, **REFS).errors)
    when_dag = _dag(_call("a", output="x"), _call("b", ["a"], when="{{x.ok}} == '1'"))
    assert validate_dag(when_dag, **REFS).ok
    when_dag_bad = _dag(_call("a"), _call("b", when="{{x.ok}} == '1'"))
    assert "unknown_placeholder" in _codes(validate_dag(when_dag_bad, **REFS))


def test_external_effect_without_approval_is_warning_not_error():
    """规则 9（P1 告警）：effect=external 无审批后继 → 只警告；有审批 → 无警告。"""
    warned = validate_dag(_dag(_call("pay", effect="external")), **REFS)
    assert warned.ok
    assert [issue.code for issue in warned.warnings] == ["external_effect_without_approval"]
    gated = validate_dag(
        _dag(
            _call("pay", effect="external"),
            {"key": "gate", "type": "human_approval", "capability": "c", "depends_on": ["pay"]},
        ),
        **REFS,
    )
    assert gated.ok and gated.warnings == ()


def test_definition_publish_locks_immutable_version_rows(db_session, settings):
    """§6 用例 7（定义侧）：draft v1 → publish 锁版本行 → 改动自动开 draft v2（v1 原样）→
    publish v2；already_published 409；非法 dag 更新 422 且不动原定义；白名单从库装配。"""
    leader = make_user(db_session, "project_lead")
    project = _persist_project(db_session, leader, code=f"WF{uuid4().hex[:4]}")
    agent = seed_agent(db_session, settings)
    assert agent.id in available_agent_refs(db_session)
    assert catalog_call_refs() == frozenset(CATALOG)

    dag1 = _dag(_call("gather", output="subjects", params={"project_id": "{{project_id}}"}))
    definition = create_definition(
        db_session, actor=leader, project_id=project.id, name="周报编排", dag=dag1
    )
    db_session.commit()
    assert definition.status == "draft" and definition.version == 1
    assert definition.content_sha256 == dag_sha256(dag1)

    v1 = publish_definition(db_session, actor=leader, definition=definition)
    db_session.commit()
    assert definition.status == "published" and definition.published_at is not None
    assert v1.version == 1 and v1.dag_json == dag1 and v1.content_sha256 == dag_sha256(dag1)

    with pytest.raises(WorkflowDefinitionError) as raised:
        publish_definition(db_session, actor=leader, definition=definition)
    assert raised.value.code == "already_published" and raised.value.status == 409

    dag2 = _dag(_call("gather", output="subjects"), _call("more", ["gather"]))
    update_definition_dag(db_session, actor=leader, definition=definition, dag=dag2)
    db_session.commit()
    assert definition.status == "draft" and definition.version == 2 and definition.published_at is None

    bad = _dag(_call("a", ["a"]))
    with pytest.raises(WorkflowDefinitionError) as raised:
        update_definition_dag(db_session, actor=leader, definition=definition, dag=bad)
    assert raised.value.status == 422
    db_session.rollback()
    db_session.expire_all()
    unchanged = db_session.get(WorkflowDefinition, definition.id)
    assert unchanged.version == 2 and unchanged.status == "draft"

    publish_definition(db_session, actor=leader, definition=unchanged)
    db_session.commit()
    versions = list_versions(db_session, definition.id)
    assert [row.version for row in versions] == [1, 2]
    assert versions[0].dag_json == dag1  # 旧版本行原样（跑动中定义被改不影响已固定版本的 run）

    # 事件断言必须显式定序：operation_events 无 order_by 的裸查返回堆物理序（CI 实测
    # 翻转过一次）；occurred_at 是事务级时间戳（各事件分属独立 commit，微秒互异），
    # id 是 uuid4 随机不可作决胜键。
    events = db_session.scalars(
        select(OperationEvent)
        .where(OperationEvent.target_id == definition.id)
        .order_by(OperationEvent.occurred_at, OperationEvent.id)
    ).all()
    assert [row.event_type for row in events] == [
        "workflow_definition_created", "workflow_definition_published",
        "workflow_definition_updated", "workflow_definition_published",
    ]
