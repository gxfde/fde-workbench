"""V3.1 P1-3：metrics 报表 v31 节七指标（任务书 §11；00-gap-register 7.1/7.3）。

- 空库：v31 节七卡全 insufficient_data（不编造数值——value 0.0 或 None 灰态）；
- workflow 域（7.3）：完成率（终态 succeeded 占比、非终态不进分母）/
  审批时延（updated_at 近似拍板时刻）/hops 分布（max+avg）；
- V3.1 域速率（7.1）：需求批准率/本体候选采纳率/方案转任务率/自动测试首次
  通过率（每用例只计首条——重试不重复计数）。
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from hashlib import sha256
from uuid import uuid4

from test_agents_d4_harness import d4_app, d4_client, d4_settings  # noqa: F401  (pytest fixture)
from test_metrics_report import _get_report, _user
from test_delivery_plans import _generate as _generate_delivery_plan
from test_delivery_plans import _module as make_delivery_module
from test_quality_test_plans import _approve, _generate, _leader_project, _seed_requirements

from fde_api.control.models import AutomationApproval
from fde_api.discovery.models import BusinessFact, DiscoveryExtraction, Requirement
from fde_api.ontology.models import OntologyChangeSet
from fde_api.workflows.models import WorkflowDefinition, WorkflowRun


def _v31(report: dict) -> dict[str, dict]:
    return {card["key"]: card for card in report["sections"]["v31"]}


def _leader(db_session, d4_client, d4_settings, tag: str):
    leader, project = _leader_project(db_session, d4_client, d4_settings, tag)
    return leader, project


def _task(db_session, project):
    """最小任务行（分解链接的 FK 目标）。"""
    from datetime import datetime

    from fde_api.workbench.models import ProjectTask

    module = make_delivery_module(db_session, project)
    task = ProjectTask(
        project_module_id=module.id,
        task_key=f"t-{uuid4().hex[:8]}",
        name="链接目标任务",
        planned_start_date=datetime.now(UTC).date(),
        planned_end_date=datetime.now(UTC).date(),
        duration_days=1,
    )
    db_session.add(task)
    db_session.commit()
    return task


def test_v31_section_empty_insufficient(db_session, d4_client, d4_settings) -> None:
    user = _user("metrics.v31.empty")
    db_session.add(user)
    db_session.commit()
    report = _get_report(d4_client, user, d4_settings).get_json()["data"]
    cards = _v31(report)
    expected_keys = {
        "workflow_completion_rate", "workflow_approval_latency_minutes",
        "workflow_hops_distribution", "requirement_approval_rate",
        "ontology_candidate_adoption_rate", "plan_task_decomposition_rate",
        "test_first_pass_rate",
    }
    assert set(cards) == expected_keys, "v31 节恰七卡（裁决不建平行指标面）"
    for key, card in cards.items():
        assert card["status"] == "insufficient_data", (key, card)
        assert card["sample_size"] == 0


def _seed_workflow_run(db_session, project, user, *, status: str, hops: int) -> WorkflowRun:
    definition = WorkflowDefinition(
        project_id=project.id, name=f"wf-{uuid4().hex[:6]}",
        dag_json={"nodes": [{"key": "a", "type": "human_approval", "capability": "workbench.write"}]},
        status="draft", version=1, created_by_user_id=user.id,
    )
    db_session.add(definition)
    db_session.flush()
    run = WorkflowRun(
        definition_id=definition.id,
        definition_version=1,
        project_id=project.id,
        status=status,
        idempotency_key=f"wf-{uuid4().hex[:12]}",
        initiated_by_user_id=user.id,
        hops=hops,
    )
    db_session.add(run)
    db_session.flush()
    return run


def test_v31_workflow_domain_metrics(db_session, d4_client, d4_settings) -> None:
    leader, project = _leader(db_session, d4_client, d4_settings, "客户M31")
    user = leader.user
    runs = [
        _seed_workflow_run(db_session, project, user, status=status, hops=hops)
        for status, hops in (("succeeded", 0), ("succeeded", 2), ("failed", 1), ("cancelled", 0), ("running", 0))
    ]
    from fde_api.workflows.models import WorkflowNodeRun

    node_run = WorkflowNodeRun(
        run_id=runs[0].id, node_key="review", node_type="human_approval",
        status="waiting",  # 节点态闭集用 waiting（run 态才是 waiting_approval）
        attempt=0,
    )
    db_session.add(node_run)
    db_session.flush()
    db_session.add(AutomationApproval(
        project_id=project.id,
        requested_by_user_id=user.id,
        workflow_node_run_id=node_run.id,
        request_key=f"wfnode:{uuid4().hex[:8]}",
        capability="workbench.write",
        tool_name="project_tasks.batch_assign",
        arguments_json={},
        arguments_sha256=sha256(b"{}").hexdigest(),
        risk_level=4,
        expires_at=datetime.now(UTC) + timedelta(minutes=30),
        status="approved",
        created_at=datetime.now(UTC) - timedelta(minutes=10),
        updated_at=datetime.now(UTC),
    ))
    db_session.commit()

    user2 = _user("metrics.v31.wf")
    db_session.add(user2)
    db_session.commit()
    cards = _v31(_get_report(d4_client, user2, d4_settings).get_json()["data"])

    wf_done = cards["workflow_completion_rate"]
    assert wf_done["status"] == "ok" and wf_done["sample_size"] == 4, "非终态 running 不进分母"
    assert wf_done["value"] == 0.5, "succeeded 2 / 终态 4"
    wf_hops = cards["workflow_hops_distribution"]
    assert wf_hops["status"] == "ok" and wf_hops["value"]["max"] == 2
    assert abs(wf_hops["value"]["avg"] - 0.6) < 0.01, "（0+2+1+0+0）/5"
    wf_approval = cards["workflow_approval_latency_minutes"]
    assert wf_approval["status"] == "ok" and wf_approval["sample_size"] == 1
    assert 9.0 <= wf_approval["value"] <= 11.0, "≈10 分钟时延"


def test_v31_domain_rate_metrics(db_session, d4_client, d4_settings) -> None:
    leader, project = _leader(db_session, d4_client, d4_settings, "客户M32")
    user = leader.user
    # 需求域：3 条 accepted + 1 条 pending → 批准率 0.75
    requirements = _seed_requirements(db_session, project, user, 3)
    minutes = db_session.get(DiscoveryExtraction, requirements[0].extraction_id)
    db_session.add(Requirement(
        project_id=project.id, extraction_id=minutes.id, created_by_user_id=user.id,
        requirement_key=f"R-{uuid4().hex[:8]}", title="待定需求", requirement_type="functional",
        priority="low", acceptance_criteria=[], status="pending",
    ))
    # 本体候选域：discovery 候选变更集 confirmed×1 + draft×1 → 采纳率 0.5；
    # 非 discovery 来源的变更集不进分母（裁决口径=候选桥采纳率）
    for status in ("confirmed", "draft"):
        db_session.add(OntologyChangeSet(
            project_id=project.id, created_by_user_id=user.id, title=f"候选{status}",
            status=status, captured_from=f"discovery:{uuid4().hex[:6]}",
        ))
    db_session.add(OntologyChangeSet(
        project_id=project.id, created_by_user_id=user.id, title="人工变更集",
        status="confirmed", captured_from=f"agent_run:{uuid4().hex[:6]}",
    ))
    # 方案域（delivery plan）：生成+批准+直插链接（分解 HTTP 链路 P0-3 已覆盖，
    # 此处只造分子样本——规避跨域序列下分解路径的锁等待问题，见 CHANGELOG 注记）
    delivery_plan = _generate_delivery_plan(db_session, leader, project)
    assert leader.patch(
        f"/api/v1/delivery-plans/{delivery_plan['id']}/review", json={"decision": "approved"}
    ).status_code == 200
    from fde_api.plans.models import DeliveryPlanItem, DeliveryPlanTaskLink

    make_delivery_module(db_session, project)
    task = _task(db_session, project)
    first_item = db_session.query(DeliveryPlanItem).filter_by(plan_id=delivery_plan["id"]).first()
    db_session.add(DeliveryPlanTaskLink(
        plan_id=delivery_plan["id"], item_id=first_item.id, task_id=task.id,
        project_id=project.id, created_by_user_id=leader.user.id,
    ))
    db_session.commit()
    # 测试域（quality 计划）：生成+批准 → 用例执行首过样本
    quality_plan = _generate(db_session, leader, project)
    _approve(db_session, leader, quality_plan["id"])
    from fde_api.quality.models import TestExecution

    case_ids = [case["id"] for case in quality_plan["cases"][:2]]
    db_session.add_all([
        TestExecution(plan_id=quality_plan["id"], case_id=case_ids[0], project_id=project.id,
                      executed_by_user_id=user.id, environment="dev", result="passed",
                      created_at=datetime.now(UTC) - timedelta(hours=1)),
        TestExecution(plan_id=quality_plan["id"], case_id=case_ids[0], project_id=project.id,
                      executed_by_user_id=user.id, environment="dev", result="failed"),
        TestExecution(plan_id=quality_plan["id"], case_id=case_ids[1], project_id=project.id,
                      executed_by_user_id=user.id, environment="dev", result="failed"),
    ])
    db_session.commit()

    viewer = _user("metrics.v31.rate")
    db_session.add(viewer)
    db_session.commit()
    cards = _v31(_get_report(d4_client, viewer, d4_settings).get_json()["data"])

    assert cards["requirement_approval_rate"]["value"] == 0.75, "accepted 3 / 全部 4"
    assert cards["requirement_approval_rate"]["sample_size"] == 4
    assert cards["ontology_candidate_adoption_rate"]["value"] == 0.5, "confirmed 1 / 候选 2"
    assert cards["plan_task_decomposition_rate"]["status"] == "ok"
    assert cards["plan_task_decomposition_rate"]["value"] == 0.3333, "3 条目中 1 条已分解"
    assert cards["plan_task_decomposition_rate"]["sample_size"] == 3
    first_pass = cards["test_first_pass_rate"]
    assert first_pass["sample_size"] == 2, "每用例只计首条（case1 的第二条 failed 不重复计数）"
    assert first_pass["value"] == 0.5
