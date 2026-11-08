"""V3.1 P0-4：Workflow 平台模板种子通道 / draft-from-plan / validate 干跑 / 模板只读面。

验收面（任务书 §8 + docs/v3.1/00-gap-register P0-4 4.4~4.10）：
- 种子文件形状闭合 + 三套模板 dag 在真实白名单下全绿（call 目录/skill 显式版本/capability）；
- seed_workflow_templates 幂等（二轮 created=0）+ 种子↔DB 对账；缺 published 技能 fail-fast；
- 节点契约扩展字段（timeout/input_schema/output_schema/failure_class/plan_ref）草稿期校验；
  补偿动作等未拍板字段仍被 unknown_field 拒绝；
- compile_plan_workflow 纯函数：只收 approved/published、确定性输出、标题 {{}} 剔除防占位符误判；
- draft-from-plan 路由：走既有 create_definition 通道（落库不建平行入口）、权限/归属/状态闸；
- validate 干跑端点：can_view 只读、零副作用、坏 dag 明细可读；
- 模板只读面：已认证可见 published 平台模板、draft 不外泄；admin 平台列表权限不变（D-2 维持）。
"""
from __future__ import annotations

from datetime import UTC, datetime
from hashlib import sha256
from uuid import uuid4

import pytest
from test_agents_d4_harness import api_client, make_user
from test_agents_d4_harness import d4_app, d4_client, d4_settings  # noqa: F401  (pytest fixture)
from test_delivery_plans import _generate, _leader_project, _seed_requirements

from fde_api.control.models import SkillDefinition, SkillVersion
from fde_api.extensions import db
from fde_api.workflows.compiler import DeliveryCompileError, compile_plan_workflow
from fde_api.workflows.definition_service import (
    APPROVAL_CAPABILITIES,
    MAX_NODE_TIMEOUT_SECONDS,
    WorkflowDefinitionError,
    catalog_call_effects,
    validate_dag,
)
from fde_api.workflows.models import WorkflowDefinition, WorkflowDefinitionVersion
from fde_api.workflows.templates import (
    load_workflow_template_seeds,
    list_published_templates,
    seed_workflow_templates,
)

_TEMPLATE_SKILLS = ("research-brief", "workbench-record-management", "document-production")


def _publish_seed_skills(db_session, admin_user) -> None:
    """种子模板引用的三枚 published 技能（显式版本 @1）。"""
    for key in _TEMPLATE_SKILLS:
        if db_session.query(SkillDefinition).filter_by(namespace_key="public", skill_key=key).one_or_none():
            continue
        definition = SkillDefinition(
            scope="public",
            namespace_key="public",
            skill_key=key,
            name=key,
            description="种子模板测试技能",
            status="published",
            current_version_number=1,
            created_by_user_id=admin_user.id,
            published_by_user_id=admin_user.id,
            published_at=datetime.now(UTC),
        )
        db_session.add(definition)
        db_session.flush()
        db_session.add(SkillVersion(
            skill_id=definition.id,
            version_number=1,
            instructions_text=f"{key} 测试指令",
            manifest_json={"version": "1", "source": "test"},
            required_capabilities=[],
            content_sha256=sha256(key.encode()).hexdigest(),
            created_by_user_id=admin_user.id,
        ))
    db_session.commit()


def _seed_admin(db_session):
    return make_user(db_session, "admin")


# ---------------------------------------------------------------------------
# 种子文件与装载


def test_seed_file_shapes_and_dag_validity() -> None:
    seeds = load_workflow_template_seeds()
    assert len(seeds) == 3, "任务书 §8 第一批三套模板"
    keys = [seed["key"] for seed in seeds]
    assert keys == ["requirement_discovery", "plan_execution", "automated_delivery"]
    assert len(set(seed["name"] for seed in seeds)) == 3

    skill_refs = {
        node["ref"]
        for seed in seeds
        for node in seed["dag"]["nodes"]
        if node.get("type") == "skill"
    }
    assert skill_refs == {"research-brief@1", "workbench-record-management@1", "document-production@1"}
    for seed in seeds:
        validation = validate_dag(
            seed["dag"],
            call_refs=frozenset({"solutions.create"}), agent_refs=frozenset(),
            skill_refs=skill_refs,
            capabilities=APPROVAL_CAPABILITIES,
            call_effects=catalog_call_effects(),
        )
        assert validation.errors == (), (seed["key"], validation.errors)
        assert validation.warnings == (), (seed["key"], validation.warnings)
        assert len(validation.order) == len(seed["dag"]["nodes"])


def test_seed_workflow_templates_idempotent_and_reconciles(db_session) -> None:
    admin = _seed_admin(db_session)
    _publish_seed_skills(db_session, admin)

    first = seed_workflow_templates(db_session)
    assert first == {"created": 3, "total": 3}
    second = seed_workflow_templates(db_session)
    assert second == {"created": 0, "total": 3}, "幂等：已存在即跳过"

    rows = db_session.query(WorkflowDefinition).filter(WorkflowDefinition.project_id.is_(None)).all()
    assert len(rows) == 3
    assert all(row.status == "published" for row in rows)
    assert all(row.published_by_user_id == admin.id for row in rows)
    versions = db_session.query(WorkflowDefinitionVersion).count()
    assert versions == 3, "每套模板一条锁版快照"
    # 种子↔DB 对账：行名与 dag 逐字节一致（canonical 序列化由 dag_sha256 锚定）
    seeds_by_name = {seed["name"]: seed for seed in load_workflow_template_seeds()}
    for row in rows:
        seed = seeds_by_name[row.name]
        assert row.dag_json == seed["dag"]
        assert row.description == seed["description"]


def test_seed_missing_published_skill_fails_fast(db_session) -> None:
    _seed_admin(db_session)  # 有 admin、无 published 技能
    try:
        seed_workflow_templates(db_session)
        raise AssertionError("缺 published 技能应 fail-fast")
    except WorkflowDefinitionError as error:
        codes = [issue["code"] for issue in error.detail.get("errors", [])]
        assert "skill_ref_not_published" in codes


# ---------------------------------------------------------------------------
# 节点契约扩展字段（4.4）


def _single_skill_node(**extra):
    node = {"key": "n1", "type": "skill", "ref": "s@1", "depends_on": []}
    node.update(extra)
    return {"nodes": [node]}


def test_node_contract_fields_valid_and_invalid() -> None:
    valid = _single_skill_node(
        timeout_seconds=3600,
        failure_class="retryable",
        input_schema={"type": "object"},
        output_schema={"type": "object"},
        plan_ref="plan-1",
    )
    result = validate_dag(valid, call_refs=frozenset(), skill_refs=frozenset({"s@1"}), agent_refs=frozenset())
    assert result.errors == ()

    cases = [
        (_single_skill_node(timeout_seconds=0), "invalid_timeout_seconds"),
        (_single_skill_node(timeout_seconds=MAX_NODE_TIMEOUT_SECONDS + 1), "invalid_timeout_seconds"),
        (_single_skill_node(timeout_seconds="600"), "invalid_timeout_seconds"),
        (_single_skill_node(timeout_seconds=True), "invalid_timeout_seconds"),
        (_single_skill_node(failure_class="bogus"), "invalid_failure_class"),
        (_single_skill_node(input_schema=[]), "invalid_input_schema"),
        (_single_skill_node(output_schema="x"), "invalid_output_schema"),
        (_single_skill_node(plan_ref=""), "invalid_plan_ref"),
        (_single_skill_node(plan_ref=42), "invalid_plan_ref"),
        (_single_skill_node(compensation="rollback"), "unknown_field"),
    ]
    for dag, expected_code in cases:
        result = validate_dag(dag, call_refs=frozenset(), skill_refs=frozenset({"s@1"}), agent_refs=frozenset())
        codes = [issue.code for issue in result.errors]
        assert expected_code in codes, (expected_code, codes)


# ---------------------------------------------------------------------------
# compile_plan_workflow 纯函数（4.8）


def _plan_payload(status: str = "published") -> dict:
    return {
        "id": str(uuid4()),
        "title": "测试交付方案",
        "status": status,
        "version": 2,
        "items": [
            {"id": "i1", "item_type": "requirement", "title": "需求一", "priority": "high"},
            {"id": "i2", "item_type": "requirement", "title": "需求二", "priority": "medium"},
            {"id": "i3", "item_type": "risk", "title": "预算待澄清", "priority": "high"},
            {"id": "i4", "item_type": "acceptance", "title": "验收口径", "priority": "medium"},
        ],
    }


def test_compile_plan_workflow_pure_and_deterministic() -> None:
    plan = _plan_payload()
    first = compile_plan_workflow(plan, implementation_skill_ref="research-brief@1")
    assert first["kind"] == "plan_workflow_draft"
    assert first["workflow_draft"]["name"].startswith("交付执行：")
    nodes = first["workflow_draft"]["dag_json"]["nodes"]
    assert [node["key"] for node in nodes] == ["plan_review", "implement", "acceptance_review"]
    assert all(node.get("plan_ref") == plan["id"] for node in nodes)
    implement = nodes[1]
    assert implement["ref"] == "research-brief@1"
    assert implement["timeout_seconds"] == 3600 and implement["failure_class"] == "retryable"
    assert "需求一；需求二" in implement["params"]["objective"]
    assert "预算待澄清" in implement["params"]["risk_notes"]

    second = compile_plan_workflow(plan, implementation_skill_ref="research-brief@1")
    assert first == second, "确定性：同一输入恒同输出"

    validation = validate_dag(
        first["workflow_draft"]["dag_json"],
        call_refs=frozenset(), agent_refs=frozenset(),
        skill_refs=frozenset({"research-brief@1"}),
        capabilities=APPROVAL_CAPABILITIES,
    )
    assert validation.errors == (), validation.errors


def test_compile_plan_workflow_input_gates() -> None:
    with pytest.raises(DeliveryCompileError) as exc:
        compile_plan_workflow(_plan_payload("draft"), implementation_skill_ref="research-brief@1")
    assert "plan_not_approved" in str(exc.value)
    with pytest.raises(DeliveryCompileError) as exc:
        compile_plan_workflow(_plan_payload(), implementation_skill_ref="bad ref")
    assert "invalid_skill_ref" in str(exc.value)
    with pytest.raises(DeliveryCompileError) as exc:
        compile_plan_workflow(_plan_payload(), implementation_skill_ref="research-brief@1", approval_capability="system.run")
    assert "invalid_capability" in str(exc.value)
    broken = _plan_payload()
    broken["items"] = "not-a-list"
    with pytest.raises(DeliveryCompileError) as exc:
        compile_plan_workflow(broken, implementation_skill_ref="research-brief@1")
    assert "invalid_plan_items" in str(exc.value)


def test_compile_plan_workflow_title_braces_stripped() -> None:
    plan = _plan_payload()
    plan["title"] = "方案 {{evil.x}} 测试"
    compiled = compile_plan_workflow(plan, implementation_skill_ref="research-brief@1")
    validation = validate_dag(
        compiled["workflow_draft"]["dag_json"],
        call_refs=frozenset(), agent_refs=frozenset(),
        skill_refs=frozenset({"research-brief@1"}),
        capabilities=APPROVAL_CAPABILITIES,
    )
    assert validation.errors == (), "标题中的花括号已剔除，不产生占位符误判"
    joined = str(compiled["workflow_draft"]["dag_json"])
    assert "{{evil" not in joined


# ---------------------------------------------------------------------------
# draft-from-plan 路由（4.8）


def test_draft_from_plan_route_full_gates(db_session, d4_client, d4_settings) -> None:
    leader, project = _leader_project(db_session, d4_client, d4_settings, "客户P4")
    _publish_seed_skills(db_session, leader.user)
    _seed_requirements(db_session, project, leader.user, 1)
    plan = _generate(db_session, leader, project)
    plan_id = plan["id"]

    # 草稿方案 → 409 plan_not_approved（只收 approved/published）
    denied = leader.post(
        f"/api/v1/projects/{project.id}/workflows/draft-from-plan",
        json={"plan_id": plan_id, "implementation_skill_ref": "research-brief@1"},
    )
    assert denied.status_code == 409
    assert denied.get_json()["error"]["code"] == "plan_not_approved"

    assert leader.patch(
        f"/api/v1/delivery-plans/{plan_id}/review", json={"decision": "approved"}
    ).status_code == 200
    assert leader.post(f"/api/v1/delivery-plans/{plan_id}/publish").status_code == 200

    # 未发布技能引用 → 422 dag_invalid（create_definition 全量复校）
    bad_ref = leader.post(
        f"/api/v1/projects/{project.id}/workflows/draft-from-plan",
        json={"plan_id": plan_id, "implementation_skill_ref": "nosuch-skill@1"},
    )
    assert bad_ref.status_code == 422

    created = leader.post(
        f"/api/v1/projects/{project.id}/workflows/draft-from-plan",
        json={"plan_id": plan_id, "implementation_skill_ref": "research-brief@1"},
    )
    assert created.status_code == 201, created.get_json()
    body = created.get_json()["data"]
    assert body["definition"]["status"] == "draft"
    node_keys = [node["key"] for node in body["definition"]["dag_json"]["nodes"]]
    assert node_keys == ["plan_review", "implement", "acceptance_review"]
    assert body["provenance"][0]["source"] == f"delivery_plan:{plan_id}"
    definition_id = body["definition"]["id"]

    # 干跑校验通过（同一 API 面）
    validated = leader.post(
        f"/api/v1/projects/{project.id}/workflows/{definition_id}/validate"
    )
    assert validated.status_code == 200
    assert validated.get_json()["data"]["valid"] is True

    # 跨项目方案 → 404（不泄露存在性）
    other_leader, other_project = _leader_project(db_session, d4_client, d4_settings, "客户P5")
    assert other_leader.post(
        f"/api/v1/projects/{other_project.id}/workflows/draft-from-plan",
        json={"plan_id": plan_id, "implementation_skill_ref": "research-brief@1"},
    ).status_code == 404

    # 项目 member（非管理）→ 403
    from test_agents_d4_harness import ApiClient, issue_access_token
    from fde_api.workbench.models import ProjectMember

    member_user = make_user(db_session, "fde_engineer")
    db_session.add(ProjectMember(project_id=project.id, user_id=member_user.id, role="member"))
    db_session.commit()
    member = ApiClient(d4_client, member_user, {"Authorization": f"Bearer {issue_access_token(member_user, d4_settings)}"})
    assert member.post(
        f"/api/v1/projects/{project.id}/workflows/draft-from-plan",
        json={"plan_id": plan_id, "implementation_skill_ref": "research-brief@1"},
    ).status_code == 403


# ---------------------------------------------------------------------------
# validate 干跑端点（4.9）


def test_validate_endpoint_dry_run_and_broken_dag(db_session, d4_client, d4_settings) -> None:
    leader, project = _leader_project(db_session, d4_client, d4_settings, "客户P6")
    created = leader.post(
        f"/api/v1/projects/{project.id}/workflows",
        json={"name": "干跑校验定义", "dag": {"nodes": [{"key": "review", "type": "human_approval", "capability": "workbench.write"}]}},
    )
    assert created.status_code == 201, created.get_json()
    definition_id = created.get_json()["data"]["definition"]["id"]

    ok = leader.post(f"/api/v1/projects/{project.id}/workflows/{definition_id}/validate")
    assert ok.status_code == 200
    assert ok.get_json()["data"]["valid"] is True
    assert ok.get_json()["data"]["errors"] == []

    # 直接落坏 dag（绕过创建闸）→ validate 如实报明细
    definition = db_session.get(WorkflowDefinition, definition_id)
    definition.dag_json = {"nodes": [{"key": "review", "type": "mystery"}]}
    db_session.commit()
    broken = leader.post(f"/api/v1/projects/{project.id}/workflows/{definition_id}/validate")
    assert broken.status_code == 200
    data = broken.get_json()["data"]
    assert data["valid"] is False
    assert any(issue["code"] == "unknown_node_type" for issue in data["errors"])

    # can_view 只读可达；陌生人 403；未知定义 404
    from test_agents_d4_harness import ApiClient, issue_access_token
    from fde_api.workbench.models import ProjectMember

    member_user = make_user(db_session, "fde_engineer")
    db_session.add(ProjectMember(project_id=project.id, user_id=member_user.id, role="member"))
    db_session.commit()
    member = ApiClient(d4_client, member_user, {"Authorization": f"Bearer {issue_access_token(member_user, d4_settings)}"})
    assert member.post(f"/api/v1/projects/{project.id}/workflows/{definition_id}/validate").status_code == 200
    stranger = api_client(d4_client, db_session, d4_settings, "project_lead")
    assert stranger.post(f"/api/v1/projects/{project.id}/workflows/{definition_id}/validate").status_code == 403
    assert leader.post(f"/api/v1/projects/{project.id}/workflows/{uuid4()}/validate").status_code == 404


# ---------------------------------------------------------------------------
# 模板只读面（4.7）与既有 admin 面不变（4.10/D-2）


def test_templates_list_route_and_admin_route_permissions(db_session, d4_client, d4_settings) -> None:
    admin = _seed_admin(db_session)
    _publish_seed_skills(db_session, admin)
    seed_workflow_templates(db_session)

    # draft 平台定义不外泄
    db_session.add(WorkflowDefinition(
        project_id=None, name="草稿平台定义", dag_json={"nodes": [{"key": "a", "type": "human_approval", "capability": "workbench.write"}]},
        status="draft", version=1, created_by_user_id=admin.id,
    ))
    db_session.commit()

    leader = api_client(d4_client, db_session, d4_settings, "project_lead")
    listed = leader.get("/api/v1/workflow-templates")
    assert listed.status_code == 200
    items = listed.get_json()["data"]["items"]
    assert len(items) == 3, "draft 不进只读面"
    assert all(item["status"] == "published" for item in items)
    assert all(isinstance(item["dag_json"], dict) and item["nodes"] for item in items)
    names = {item["name"] for item in items}
    assert names == {"需求发现模板", "方案实施模板", "自动化交付模板"}

    # 未认证 → 401
    assert d4_client.get("/api/v1/workflow-templates").status_code == 401

    # 既有 admin 平台列表权限不变：非 admin 403（D-2 维持 admin-only 发布/管理面）
    assert leader.get("/api/v1/workflows").status_code == 403

    # 只读投影服务面独立可用（无 session 泄漏风险的最小钉）
    with db.session() as session:
        assert len(list_published_templates(session)) == 3
