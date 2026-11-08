"""V3.1 P0-3：交付方案生成/审阅/发布/任务分解（plans 三表）。

验收面（任务书 §7 + docs/v3.1/00-gap-register P0-3）：
- 生成器确定性拼装：只消费 accepted 需求/事实 + confirmed 术语；无输入 409；
- 审阅流：draft→approved（决策留痕；新批准使旧 published 退位 superseded、
  历史行内容不覆盖）/rejected→superseded；仅 draft 可审阅；
- 发布：仅 approved 可 published（旧 published 同步退位）；
- 任务分解：dry_run 预览/选择性创建/幂等跳过（每条目至多一任务）；
  任务必须挂项目既有模块；未指派=待认领；
- 权限：写=can_manage、读=can_view、跨项目 403/404。
"""
from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from test_agents_d4_harness import api_client, make_user
from test_agents_d4_harness import d4_app, d4_client, d4_settings  # noqa: F401  (pytest fixture)
from test_discovery_extraction import _minutes, _new_project

from fde_api.discovery.models import BusinessFact, DiscoveryExtraction, Requirement
from fde_api.plans.models import DeliveryPlan, DeliveryPlanTaskLink
from fde_api.workbench.models import OperationEvent, ProjectMember, ProjectModule, ProjectTask


def _leader_project(db_session, d4_client, d4_settings, tag: str):
    leader = api_client(d4_client, db_session, d4_settings, "project_lead")
    project = _new_project(db_session, leader.user, tag)
    return leader, project


def _module(db_session, project) -> ProjectModule:
    from fde_api.workbench.models import ModuleCatalog

    catalog = db_session.query(ModuleCatalog).filter_by(name="交付模块").one_or_none()
    if catalog is None:
        catalog = ModuleCatalog(
            module_key=f"cat-{uuid4().hex[:8]}", name=f"交付模块-{uuid4().hex[:6]}",
        )
        db_session.add(catalog)
        db_session.flush()
    module = ProjectModule(
        project_id=project.id,
        module_catalog_id=catalog.id,
        name="交付模块",
        sort_order=0,
    )
    db_session.add(module)
    db_session.commit()
    return module


def _seed_requirements(db_session, project, leader_user, count: int = 2) -> list[Requirement]:
    minutes = _minutes(db_session, project, leader_user)
    extraction = DiscoveryExtraction(
        project_id=project.id,
        created_by_user_id=leader_user.id,
        source_type="interview_minutes",
        source_id=minutes.id,
        source_sha256=minutes.content_sha256,
        status="review_required",
    )
    db_session.add(extraction)
    db_session.flush()
    rows = []
    for index in range(count):
        row = Requirement(
            project_id=project.id,
            extraction_id=extraction.id,
            created_by_user_id=leader_user.id,
            requirement_key=f"R-{uuid4().hex[:8]}",
            title=f"需求{index + 1}",
            requirement_type="functional",
            priority="high" if index == 0 else "medium",
            acceptance_criteria=["可验证标准"],
            status="accepted",
            approved_by_user_id=leader_user.id,
            approved_at=datetime.now(UTC),
        )
        rows.append(row)
    db_session.add_all(rows)
    db_session.commit()
    return rows


def _generate(db_session, leader, project) -> dict:
    response = leader.post(f"/api/v1/projects/{project.id}/delivery-plans/generate")
    assert response.status_code == 201, response.get_json()
    return response.get_json()["data"]


# ---------------------------------------------------------------------------
# 生成器


def test_generate_happy_path_and_event(db_session, d4_client, d4_settings) -> None:
    leader, project = _leader_project(db_session, d4_client, d4_settings, "客户X")
    requirements = _seed_requirements(db_session, project, leader.user, 2)
    # 一条 open_question 事实 → 风险条目素材
    minutes = db_session.get(DiscoveryExtraction, requirements[0].extraction_id)
    db_session.add(BusinessFact(
        project_id=project.id, extraction_id=minutes.id,
        fact_type="open_question", classification="open_question",
        subject="预算", predicate="待确认", object_value="?",
        source_ref=f"interview_minutes:{minutes.source_id}",
        source_locator={"type": "line", "line": 1},
        review_status="needs_clarification",
    ))
    db_session.commit()

    data = _generate(db_session, leader, project)
    assert data["status"] == "draft" and data["version"] == 1
    types = [item["item_type"] for item in data["items"]]
    assert types.count("requirement") == 2, "每条已批准需求一个条目"
    assert "risk" in types, "待澄清事实聚合为风险条目"
    requirement_item = next(item for item in data["items"] if item["item_type"] == "requirement")
    assert requirement_item["requirement_keys"] == [requirements[0].requirement_key]
    events = db_session.query(OperationEvent).filter_by(
        target_type="delivery_plan", target_id=data["id"], event_type="delivery_plan_generated"
    ).count()
    assert events == 1


def test_generate_without_inputs_409(db_session, d4_client, d4_settings) -> None:
    leader, project = _leader_project(db_session, d4_client, d4_settings, "客户Y")
    response = leader.post(f"/api/v1/projects/{project.id}/delivery-plans/generate")
    assert response.status_code == 409
    assert response.get_json()["error"]["code"] == "no_approved_inputs"


# ---------------------------------------------------------------------------
# 审阅与发布


def test_review_and_publish_flow_with_supersede(db_session, d4_client, d4_settings) -> None:
    leader, project = _leader_project(db_session, d4_client, d4_settings, "客户Z")
    _seed_requirements(db_session, project, leader.user, 1)
    plan_v1 = _generate(db_session, leader, project)
    plan_v2 = _generate(db_session, leader, project)
    assert plan_v2["version"] == 2, "新版本=新行，版本号递增"

    # v2 审阅批准 → v2 approved
    approved = leader.patch(
        f"/api/v1/delivery-plans/{plan_v2['id']}/review",
        json={"decision": "approved", "comment": "口径齐备"},
    )
    assert approved.status_code == 200
    assert approved.get_json()["data"]["status"] == "approved"
    assert approved.get_json()["data"]["reviewed_by_user_id"] is not None

    # v2 发布 → published；v1 仍是独立 draft（不覆盖历史）
    published = leader.post(f"/api/v1/delivery-plans/{plan_v2['id']}/publish")
    assert published.status_code == 200
    assert published.get_json()["data"]["status"] == "published"

    # v1 也批准+发布 → 旧 published（v2）退位 superseded
    assert leader.patch(
        f"/api/v1/delivery-plans/{plan_v1['id']}/review", json={"decision": "approved"}
    ).status_code == 200
    assert leader.post(f"/api/v1/delivery-plans/{plan_v1['id']}/publish").status_code == 200
    db_session.expire_all()
    assert db_session.get(DeliveryPlan, plan_v2["id"]).status == "superseded"
    assert db_session.get(DeliveryPlan, plan_v1["id"]).status == "published"

    # 仅 draft 可审阅；仅 approved 可发布
    assert leader.patch(
        f"/api/v1/delivery-plans/{plan_v1['id']}/review", json={"decision": "approved"}
    ).status_code == 409
    assert leader.post(f"/api/v1/delivery-plans/{plan_v1['id']}/publish").status_code == 409

    # rejected → superseded
    plan_v3 = _generate(db_session, leader, project)
    rejected = leader.patch(
        f"/api/v1/delivery-plans/{plan_v3['id']}/review",
        json={"decision": "rejected", "comment": "需求未齐"},
    )
    assert rejected.status_code == 200
    assert rejected.get_json()["data"]["status"] == "superseded"


# ---------------------------------------------------------------------------
# 任务分解


def test_task_decomposition_preview_commit_idempotent(db_session, d4_client, d4_settings) -> None:
    leader, project = _leader_project(db_session, d4_client, d4_settings, "客户AA")
    _seed_requirements(db_session, project, leader.user, 2)
    plan = _generate(db_session, leader, project)
    module = _module(db_session, project)
    item_ids = [item["id"] for item in plan["items"]]

    # 未批准方案 → 409
    denied = leader.post(
        f"/api/v1/delivery-plans/{plan['id']}/tasks",
        json={"module_id": module.id, "dry_run": True},
    )
    assert denied.status_code == 409

    assert leader.patch(
        f"/api/v1/delivery-plans/{plan['id']}/review", json={"decision": "approved"}
    ).status_code == 200

    # 预览（dry_run=true 默认）：不落任务
    preview = leader.post(
        f"/api/v1/delivery-plans/{plan['id']}/tasks",
        json={"module_id": module.id, "dry_run": True},
    )
    assert preview.status_code == 200
    body = preview.get_json()["data"]
    assert body["dry_run"] is True and len(body["preview"]) >= 2
    assert db_session.query(ProjectTask).join(ProjectModule).filter(ProjectModule.project_id == project.id).count() == 0

    # 选择性创建（只取第一个条目）
    commit = leader.post(
        f"/api/v1/delivery-plans/{plan['id']}/tasks",
        json={"module_id": module.id, "dry_run": False, "item_ids": [item_ids[0]]},
    )
    assert commit.status_code == 200
    assert len(commit.get_json()["data"]["created"]) == 1
    task = db_session.query(ProjectTask).join(ProjectModule).filter(ProjectModule.project_id == project.id).one()
    assert task.default_assignee_role is None and task.assignee_user_id is None, "未指派=待认领"
    link = db_session.query(DeliveryPlanTaskLink).filter_by(item_id=item_ids[0]).one()
    assert link.task_id == task.id

    # 幂等：同条目重复创建 → skipped
    again = leader.post(
        f"/api/v1/delivery-plans/{plan['id']}/tasks",
        json={"module_id": module.id, "dry_run": False, "item_ids": [item_ids[0]]},
    )
    assert again.status_code == 200
    assert again.get_json()["data"]["created"] == []
    assert again.get_json()["data"]["skipped"][0]["reason"] == "已分解"
    assert db_session.query(ProjectTask).join(ProjectModule).filter(ProjectModule.project_id == project.id).count() == 1

    # 事件留痕：每次分解动作各一条（含幂等跳过那次 created=0——审计诚实）
    events = db_session.query(OperationEvent).filter_by(
        target_type="delivery_plan", target_id=plan["id"], event_type="delivery_plan_tasks_created"
    ).all()
    assert len(events) == 2
    assert events[0].changes["created"] == 1 and events[1].changes["created"] == 0


def test_task_decomposition_module_and_access_gates(db_session, d4_client, d4_settings) -> None:
    leader, project = _leader_project(db_session, d4_client, d4_settings, "客户AB")
    _seed_requirements(db_session, project, leader.user, 1)
    plan = _generate(db_session, leader, project)
    assert leader.patch(
        f"/api/v1/delivery-plans/{plan['id']}/review", json={"decision": "approved"}
    ).status_code == 200
    module = _module(db_session, project)

    # 未知/跨项目模块 → 404
    assert leader.post(
        f"/api/v1/delivery-plans/{plan['id']}/tasks",
        json={"module_id": str(uuid4()), "dry_run": True},
    ).status_code == 404

    # member（非管理）→ 403
    member_user = make_user(db_session, "fde_engineer")
    db_session.add(ProjectMember(project_id=project.id, user_id=member_user.id, role="member"))
    db_session.commit()
    from test_agents_d4_harness import ApiClient, issue_access_token

    member = ApiClient(d4_client, member_user, {"Authorization": f"Bearer {issue_access_token(member_user, d4_settings)}"})
    assert member.post(
        f"/api/v1/delivery-plans/{plan['id']}/tasks",
        json={"module_id": module.id, "dry_run": True},
    ).status_code == 403
    assert member.get(f"/api/v1/projects/{project.id}/delivery-plans").status_code == 200

    # 跨项目 stranger → 403/404
    stranger = api_client(d4_client, db_session, d4_settings, "project_lead")
    assert stranger.get(f"/api/v1/delivery-plans/{plan['id']}").status_code == 403
    other_leader, other_project = _leader_project(db_session, d4_client, d4_settings, "客户AC")
    assert other_leader.post(
        f"/api/v1/projects/{other_project.id}/delivery-plans/generate"
    ).status_code == 409  # 其他项目无输入，正常走 409
    assert stranger.get(f"/api/v1/projects/{project.id}/delivery-plans").status_code == 403
