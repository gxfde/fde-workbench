"""V3.1 P1-2：测试计划/用例/执行（quality 三表）+ 证据完整性校验端点。

验收面（任务书 §10 约束逐条 + docs/v3.1/00-gap-register P1-2 6.3/6.4/6.5）：
- 生成=确定性拼装：每条 accepted 需求一条用例（requirement_key 追溯、
  expected=验收标准聚合、risk=priority 映射、条目序=字典序）；无输入 409；
- 审阅：draft→approved 需求覆盖闸（每条批准需求至少有测试或明确人工验收
  方式，缺失点名 409）；rejected→superseded；双点退位（新 approved 使旧
  approved 退位，历史行不覆盖）；仅 draft 可审阅；
- 执行：append-only（无 PATCH 路由=失败不可被改写为成功的静态钉）；仅
  approved 可执行；production 硬闸 409；报告指针+sha256 成对；跨计划用例 404；
- 证据完整性校验：只读端点，五维检查（存在/项目范围/指纹形状/通道在册/
  操作者留痕）+ 可选 gate_key 类型范围校验；零写入零事件。
"""
from __future__ import annotations

from datetime import UTC, datetime
from hashlib import sha256
from uuid import uuid4

from test_agents_d4_harness import ApiClient, api_client, issue_access_token, make_user
from test_agents_d4_harness import d4_app, d4_client, d4_settings  # noqa: F401  (pytest fixture)
from test_delivery_plans import _module, _seed_requirements
from test_discovery_extraction import _new_project

from fde_api.quality.models import TestCase as QualityCase
from fde_api.quality.models import TestExecution, TestPlan
from fde_api.workbench.models import ModuleCatalog, OperationEvent, ProjectMember, ProjectModule, ProjectTask


def _leader_project(db_session, d4_client, d4_settings, tag: str):
    leader = api_client(d4_client, db_session, d4_settings, "project_lead")
    project = _new_project(db_session, leader.user, tag)
    return leader, project


def _task(db_session, project) -> ProjectTask:
    from test_delivery_plans import _module as make_module

    module = make_module(db_session, project)
    task = ProjectTask(
        project_module_id=module.id,
        task_key=f"t-{uuid4().hex[:8]}",
        name="交付任务",
        planned_start_date=datetime.now(UTC).date(),
        planned_end_date=datetime.now(UTC).date(),
        duration_days=1,
    )
    db_session.add(task)
    db_session.commit()
    return task


def _generate(db_session, leader, project, payload: dict | None = None) -> dict:
    response = leader.post(
        f"/api/v1/projects/{project.id}/test-plans/generate", json=payload or {}
    )
    assert response.status_code == 201, response.get_json()
    return response.get_json()["data"]["plan"]


def _approve(db_session, leader, plan_id: str):
    response = leader.patch(
        f"/api/v1/test-plans/{plan_id}/review", json={"decision": "approved"}
    )
    assert response.status_code == 200, response.get_json()
    return response.get_json()["data"]["plan"]


def _member(db_session, d4_client, d4_settings, leader, project):
    member_user = make_user(db_session, "fde_engineer")
    db_session.add(ProjectMember(project_id=project.id, user_id=member_user.id, role="member"))
    db_session.commit()
    return ApiClient(
        d4_client, member_user, {"Authorization": f"Bearer {issue_access_token(member_user, d4_settings)}"}
    )


# ---------------------------------------------------------------------------
# 生成


def test_generate_deterministic_and_traceability(db_session, d4_client, d4_settings) -> None:
    leader, project = _leader_project(db_session, d4_client, d4_settings, "客户Q1")
    requirements = _seed_requirements(db_session, project, leader.user, 2)
    data = _generate(db_session, leader, project)

    assert data["status"] == "draft" and data["version"] == 1
    cases = data["cases"]
    assert len(cases) == 2, "每条已批准需求一条用例"
    assert [case["requirement_key"] for case in cases] == sorted(r.requirement_key for r in requirements), (
        "条目序=requirement_key 字典序（#209 教训：插入序不可依赖）"
    )
    by_key = {case["requirement_key"]: case for case in cases}
    assert all(case["case_key"].startswith("TC-") for case in cases)
    assert all(case["acceptance_mode"] == "test" and case["automated"] is False for case in cases)
    assert "可验证标准" in by_key[requirements[0].requirement_key]["expected"], "expected=验收标准聚合"
    high = by_key[requirements[0].requirement_key]  # 首条=high
    assert high["risk_level"] == 3 and all(c["risk_level"] == 2 for k, c in by_key.items() if k != requirements[0].requirement_key)
    events = db_session.query(OperationEvent).filter_by(
        target_type="test_plan", target_id=data["id"], event_type="test_plan_generated"
    ).count()
    assert events == 1

    # 再生成=新行 version 递增（历史不覆盖）
    plan_v2 = _generate(db_session, leader, project)
    assert plan_v2["version"] == 2 and plan_v2["id"] != data["id"]


def test_generate_without_requirements_409(db_session, d4_client, d4_settings) -> None:
    leader, project = _leader_project(db_session, d4_client, d4_settings, "客户Q2")
    response = leader.post(f"/api/v1/projects/{project.id}/test-plans/generate", json={})
    assert response.status_code == 409
    assert response.get_json()["error"]["code"] == "no_approved_requirements"


def test_generate_source_task_gate(db_session, d4_client, d4_settings) -> None:
    leader, project = _leader_project(db_session, d4_client, d4_settings, "客户Q3")
    _seed_requirements(db_session, project, leader.user, 1)
    task = _task(db_session, project)

    ok = leader.post(
        f"/api/v1/projects/{project.id}/test-plans/generate",
        json={"source_task_id": task.id},
    )
    assert ok.status_code == 201
    assert ok.get_json()["data"]["plan"]["source_task_id"] == task.id

    # 跨项目任务 → 404（不泄露存在性）
    other_leader, other_project = _leader_project(db_session, d4_client, d4_settings, "客户Q4")
    other_task = _task(db_session, other_project)
    denied = leader.post(
        f"/api/v1/projects/{project.id}/test-plans/generate",
        json={"source_task_id": other_task.id},
    )
    assert denied.status_code == 404


# ---------------------------------------------------------------------------
# 审阅（覆盖闸 + 退位）


def test_review_coverage_gate_and_supersede(db_session, d4_client, d4_settings) -> None:
    leader, project = _leader_project(db_session, d4_client, d4_settings, "客户Q5")
    requirements = _seed_requirements(db_session, project, leader.user, 2)
    plan_v1 = _generate(db_session, leader, project)

    # 生成后新增一条已批准需求 → 覆盖闸点名缺失键
    from fde_api.discovery.models import DiscoveryExtraction, Requirement

    extraction = db_session.get(DiscoveryExtraction, requirements[0].extraction_id)
    late_requirement = Requirement(
        project_id=project.id,
        extraction_id=extraction.id,
        created_by_user_id=leader.user.id,
        requirement_key=f"R-{uuid4().hex[:8]}",
        title="迟批准需求",
        requirement_type="functional",
        priority="low",
        acceptance_criteria=["迟来标准"],
        status="accepted",
        approved_by_user_id=leader.user.id,
        approved_at=datetime.now(UTC),
    )
    db_session.add(late_requirement)
    db_session.commit()

    denied = leader.patch(f"/api/v1/test-plans/{plan_v1['id']}/review", json={"decision": "approved"})
    assert denied.status_code == 409
    assert denied.get_json()["error"]["code"] == "requirement_coverage_incomplete"
    assert late_requirement.requirement_key in denied.get_json()["error"]["details"]["missing_requirement_keys"]

    # 再生成覆盖全部 → approved；旧 draft（v1）不受影响
    plan_v2 = _generate(db_session, leader, project)
    approved = _approve(db_session, leader, plan_v2["id"])
    assert approved["status"] == "approved" and approved["reviewed_by_user_id"] is not None

    # v3 批准 → v2 退位 superseded（历史行不覆盖）
    plan_v3 = _generate(db_session, leader, project)
    _approve(db_session, leader, plan_v3["id"])
    db_session.expire_all()
    assert db_session.get(TestPlan, plan_v2["id"]).status == "superseded"
    assert db_session.get(TestPlan, plan_v3["id"]).status == "approved"

    # 仅 draft 可审阅；rejected → superseded
    again = leader.patch(f"/api/v1/test-plans/{plan_v3['id']}/review", json={"decision": "approved"})
    assert again.status_code == 409
    plan_v4 = _generate(db_session, leader, project)
    rejected = leader.patch(
        f"/api/v1/test-plans/{plan_v4['id']}/review", json={"decision": "rejected", "comment": "口径不对"}
    )
    assert rejected.status_code == 200
    assert rejected.get_json()["data"]["plan"]["status"] == "superseded"

    # 审阅事件留痕
    events = db_session.query(OperationEvent).filter_by(
        target_type="test_plan", target_id=plan_v3["id"], event_type="test_plan_reviewed"
    ).count()
    assert events == 1


# ---------------------------------------------------------------------------
# 执行（append-only + production 闸 + 报告成对）


def _seed_approved_plan(db_session, leader, project) -> dict:
    _seed_requirements(db_session, project, leader.user, 1)
    plan = _generate(db_session, leader, project)
    return _approve(db_session, leader, plan["id"])


def test_execute_gates_and_append_only(db_session, d4_client, d4_settings, d4_app) -> None:
    leader, project = _leader_project(db_session, d4_client, d4_settings, "客户Q6")
    _seed_requirements(db_session, project, leader.user, 1)
    draft = _generate(db_session, leader, project)
    case_id = draft["cases"][0]["id"]

    # draft 不可执行
    assert leader.post(
        f"/api/v1/test-plans/{draft['id']}/execute",
        json={"environment": "dev", "executions": [{"case_id": case_id, "result": "passed"}]},
    ).status_code == 409

    plan = _seed_approved_plan(db_session, leader, project)
    approved_case = plan["cases"][0]["id"]
    # 跨计划用例：取开头 draft 计划的用例（双点退位语义=同一时刻至多一个
    # approved，不能并行批准两个计划来做跨计划用例）
    foreign_case = draft["cases"][0]["id"]

    # production 硬闸（任务书「生产环境测试默认禁止」）
    production = leader.post(
        f"/api/v1/test-plans/{plan['id']}/execute",
        json={"environment": "production", "executions": [{"case_id": approved_case, "result": "passed"}]},
    )
    assert production.status_code == 409
    assert production.get_json()["error"]["code"] == "production_forbidden"

    # 结果闭集 + 报告成对 + 跨计划用例
    assert leader.post(
        f"/api/v1/test-plans/{plan['id']}/execute",
        json={"environment": "dev", "executions": [{"case_id": approved_case, "result": "成功"}]},
    ).status_code == 400
    pair = leader.post(
        f"/api/v1/test-plans/{plan['id']}/execute",
        json={"environment": "dev", "executions": [{"case_id": approved_case, "result": "passed", "report_uri": "file:///r.txt"}]},
    )
    assert pair.status_code == 400
    foreign = leader.post(
        f"/api/v1/test-plans/{plan['id']}/execute",
        json={"environment": "dev", "executions": [{"case_id": foreign_case, "result": "passed"}]},
    )
    assert foreign.status_code == 404

    # 正常登记（失败结果带报告指针）→ append-only：重跑=新行，旧行结果不可变
    digest = sha256(b"report-content").hexdigest()
    created = leader.post(
        f"/api/v1/test-plans/{plan['id']}/execute",
        json={"environment": "staging", "executions": [
            {"case_id": approved_case, "result": "failed",
             "started_at": "2026-11-08T10:00:00+00:00", "finished_at": "2026-11-08T10:05:00+00:00",
             "report_uri": "file:///d/test/FDE/reports/r1.txt", "report_sha256": digest, "note": "缺陷一"},
            {"case_id": approved_case, "result": "blocked"},
        ]},
    )
    assert created.status_code == 200, created.get_json()
    assert len(created.get_json()["data"]["created"]) == 2
    rows = db_session.query(TestExecution).filter_by(case_id=approved_case).order_by(TestExecution.created_at).all()
    assert len(rows) == 2
    assert rows[0].result == "failed" and rows[0].report_sha256 == digest
    assert rows[1].result == "blocked" and rows[1].report_uri is None

    # 静态钉：执行记录无任何改写入口（失败不可被摘要 Agent 改写为成功）
    mutating = [
        rule
        for rule in d4_app.url_map.iter_rules()
        if "test-executions" in rule.rule and ("PATCH" in rule.methods or "PUT" in rule.methods or "DELETE" in rule.methods)
    ]
    assert mutating == [], "执行记录必须 append-only：不得存在 PATCH/PUT/DELETE 执行路由"

    # GET 执行详情（can_view）；跨项目 stranger 403
    execution_id = created.get_json()["data"]["created"][0]["execution_id"]
    assert leader.get(f"/api/v1/test-executions/{execution_id}").status_code == 200
    stranger = api_client(d4_client, db_session, d4_settings, "project_lead")
    assert stranger.get(f"/api/v1/test-executions/{execution_id}").status_code == 403
    assert leader.get(f"/api/v1/test-executions/{uuid4()}").status_code == 404

    # member（非管理）execute → 403；列表 can_view 可达 + task 过滤
    member = _member(db_session, d4_client, d4_settings, leader, project)
    assert member.post(
        f"/api/v1/test-plans/{plan['id']}/execute",
        json={"environment": "dev", "executions": [{"case_id": approved_case, "result": "passed"}]},
    ).status_code == 403
    assert member.get(f"/api/v1/projects/{project.id}/test-plans").status_code == 200
    assert member.get(f"/api/v1/test-plans/{plan['id']}").status_code == 200
    filtered = leader.get(f"/api/v1/projects/{project.id}/test-plans?task_id=nonexistent")
    assert filtered.status_code == 200 and filtered.get_json()["data"]["items"] == []


# ---------------------------------------------------------------------------
# 证据完整性校验端点（6.5）


def _register_evidence(leader, project_id: str, kind: str = "gate") -> dict:
    response = leader.post(
        f"/api/v1/projects/{project_id}/evidence",
        json={
            "kind": kind,
            "source_uri": f"file:///d/test/FDE/{uuid4().hex[:6]}.txt",
            "content_sha256": sha256(uuid4().hex.encode()).hexdigest(),
        },
    )
    assert response.status_code == 201, response.get_json()
    return response.get_json()["data"]["evidence"]


def test_validate_evidence_endpoint(db_session, d4_client, d4_settings) -> None:
    leader, project = _leader_project(db_session, d4_client, d4_settings, "客户Q7")
    evidence = _register_evidence(leader, project.id, kind="gate")

    ok = leader.post(
        f"/api/v1/projects/{project.id}/evidence/validate",
        json={"evidence_ids": [evidence["id"]]},
    )
    assert ok.status_code == 200
    body = ok.get_json()["data"]
    assert body["valid"] is True and body["checked"] == 1
    assert body["results"][0]["failures"] == []

    # 校验零写入零事件：重复校验不产生新事件
    before = db_session.query(OperationEvent).filter_by(target_type="project").count()
    leader.post(f"/api/v1/projects/{project.id}/evidence/validate", json={"evidence_ids": [evidence["id"], evidence["id"]]})
    after = db_session.query(OperationEvent).filter_by(target_type="project").count()
    assert before == after

    # gate_key：类型正确（kind=gate）+ 门禁在项目 → 通过；错误类型 → 失败
    # 先经只读门禁面触发该项目的门禁懒初始化（validate 本身零写入不代实例化）
    assert leader.get(f"/api/v1/projects/{project.id}/gates").status_code == 200
    gated = leader.post(
        f"/api/v1/projects/{project.id}/evidence/validate",
        json={"evidence_ids": [evidence["id"]], "gate_key": "G1"},
    )
    assert gated.status_code == 200
    assert gated.get_json()["data"]["valid"] is True, gated.get_json()["data"]
    wrong_kind = _register_evidence(leader, project.id, kind="task")
    gated_wrong = leader.post(
        f"/api/v1/projects/{project.id}/evidence/validate",
        json={"evidence_ids": [wrong_kind["id"]], "gate_key": "G1"},
    )
    failures = gated_wrong.get_json()["data"]["results"][0]["failures"]
    assert any(f["check"] == "evidence_kind_for_gate" for f in failures)
    unknown_gate = leader.post(
        f"/api/v1/projects/{project.id}/evidence/validate",
        json={"evidence_ids": [evidence["id"]], "gate_key": "G99"},
    )
    assert any(f["check"] == "gate_scope" for f in unknown_gate.get_json()["data"]["results"][0]["failures"])

    # 跨项目证据 → 项目范围失败（不泄露存在性）
    other_leader, other_project = _leader_project(db_session, d4_client, d4_settings, "客户Q8")
    foreign = _register_evidence(other_leader, other_project.id)
    crossed = leader.post(
        f"/api/v1/projects/{project.id}/evidence/validate",
        json={"evidence_ids": [foreign["id"], evidence["id"]]},
    )
    results = {item["evidence_id"]: item for item in crossed.get_json()["data"]["results"]}
    assert results[foreign["id"]]["valid"] is False
    assert results[evidence["id"]]["valid"] is True

    # 形状闸：空数组/非字符串/超量 → 400；未认证 → 401
    assert leader.post(f"/api/v1/projects/{project.id}/evidence/validate", json={"evidence_ids": []}).status_code == 400
    assert leader.post(f"/api/v1/projects/{project.id}/evidence/validate", json={"evidence_ids": [42]}).status_code == 400
    assert leader.post(
        f"/api/v1/projects/{project.id}/evidence/validate",
        json={"evidence_ids": [str(uuid4())] * 101},
    ).status_code == 400
    assert d4_client.post(f"/api/v1/projects/{project.id}/evidence/validate", json={"evidence_ids": [evidence["id"]]}).status_code == 401


def test_quality_routes_never_in_catalog() -> None:
    """治理面红线钉：quality/validate 路由不进 api_catalog（沿 discovery/plans 先例）。"""
    from fde_api.control.api_catalog import CATALOG

    assert not any(key.startswith("quality.") for key in CATALOG)
    assert not any(key.startswith("evidence.") for key in CATALOG)
