"""goal-crv-fix2 r4 批 E 回归钉（QR-071 / QR-072 / QR-073 及宿主通道核销）。

- QR-071（续 CR-028）：published 阶段 seat_delivery=None 生成的 draft 结算行，在接单
  （transition_package accept）、五席位分配（allocate_five_seats）、二次收款刷新及
  accrue_settlements_for_project 兜底四条路径上均同步回填 seat_delivery_user_id，
  保证当期预扣税非零且进入同自然年后续里程碑 past_rows 累计预扣基数。
- QR-072：compiler.py 与 workflow-templates.json 的 solutions.create 节点补齐
  params.project_id 并包裹 params.body；definition_service.py 定义期契约闸
  拦截缺路径参数或写操作散落顶层字段（422 dag_invalid）；编译→定义→发布→执行器
  端到端真实创建 ProjectSolution 行。
- QR-073 及宿主通道核销：is_unsafe_artifact_path 三形态钉（POSIX 绝对 / .. 穿越 /
  Windows 盘符与反斜杠根）+ QR-088/089/092/094/095 在位核验。
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
import inspect
import json
from uuid import uuid4

import pytest
from sqlalchemy import select

from fde_api.agents import adapter as agent_adapter
from fde_api.agents import host_channel
from fde_api.agents.host_receipt import submit_host_receipt
from fde_api.agents.models import AgentRun
from fde_api.agents import service as agent_service
from fde_api.agents.workspace_files import is_unsafe_artifact_path
from fde_api.dispatch.models import DeliverySettlement
from fde_api.dispatch.packages import publish_package, transition_package
from fde_api.dispatch.settlements import (
    accrue_settlements_for_project,
    allocate_five_seats,
    compute_withholding,
    record_receipt_settlements,
)
from fde_api.research.models import ProjectResearchSubject
from fde_api.solutions.models import ProjectSolution
from fde_api.workbench.models import Payment, Project
from fde_api.workflows.compiler import compile_delivery_preview
from fde_api.workflows.definition_service import (
    WorkflowDefinitionError,
    create_definition,
    publish_definition,
    validate_dag_against_registry,
)
from fde_api.workflows.executor import run_workflow_run, start_run
from fde_api.workflows.models import WorkflowNodeRun, WorkflowRun
from fde_api.workflows.templates import seed_workflow_templates

import test_dispatch_p1_r5 as r5
from test_agents_d4_harness import d4_app, d4_client, d4_settings, make_user  # noqa: F401
from test_workflow_executor import _persist_project, _seed_skill
from test_workflow_templates import _publish_seed_skills


def _make_payment(
    db_session,
    *,
    project_id: str,
    package_code: str,
    milestone_key: str,
    amount: str,
    passed_at: datetime | None = None,
) -> Payment:
    payment = Payment(
        project_id=project_id,
        milestone_key=milestone_key,
        sow_type="a",
        collects=f"批E里程碑 {milestone_key}",
        timing="按合同",
        amount=Decimal(amount),
        received_amount=Decimal(amount),
        received_at=datetime(2026, 6, 15).date(),
        acceptance_passed_at=passed_at,
        source_uri=f"fdeops://crv-batch-e/{package_code}/{milestone_key}",
        content_hash="b" * 64,
    )
    db_session.add(payment)
    db_session.flush()
    return payment


def test_qr071_published_receipt_then_accept_accrues_and_accumulates_withholding(
    db_session,
):
    """QR-071 主链：published 态先收款生成 draft 结算（seat_delivery=None）→ 接单回填
    → G8 计提算足当期预扣税 → 同年第二笔里程碑计入累计预扣递进基数。"""
    admin, package = r5._onsite_package(db_session)
    engineer = r5._user("crv.e.eng", role="fde_engineer")
    db_session.add(engineer)
    db_session.flush()

    r5._active_rule(db_session, version_no=1)
    publish_package(db_session, actor=admin, package_id=package.id)
    assert package.seat_delivery is None
    project = db_session.get(Project, package.project_id)
    assert project is not None

    # 里程碑 G3：在包仍处于 published（无交付人）时先回填实收
    pay_g3 = _make_payment(
        db_session,
        project_id=package.project_id,
        package_code=package.package_code,
        milestone_key="G3",
        amount="50000.00",
    )
    record_receipt_settlements(
        db_session, actor=admin, project=project, payment=pay_g3
    )
    s_g3 = db_session.scalar(
        select(DeliverySettlement).where(
            DeliverySettlement.package_id == package.id,
            DeliverySettlement.settlement_key == "G3",
        )
    )
    assert s_g3 is not None
    assert s_g3.status == "draft"
    assert s_g3.seat_delivery_user_id is None

    # 派单发出 offer 后工程师接单（accept_offer / accept_package 唯一汇聚点 transition_package）
    transition_package(
        db_session,
        actor=admin,
        package_id=package.id,
        action="offer",
    )
    transition_package(
        db_session,
        actor=admin,
        package_id=package.id,
        action="accept",
        seat_delivery_user_id=engineer.id,
    )
    db_session.flush()
    assert s_g3.seat_delivery_user_id == engineer.id

    # 验收通过计提 G3：delivery_amount = 50000 * 40% = 20000 > 5000，预扣必 > 0
    june_ts = datetime(2026, 6, 20, 10, 0, tzinfo=timezone.utc)
    pay_g3.acceptance_passed_at = june_ts
    db_session.flush()

    expected_g3_tax = compute_withholding(
        db_session,
        delivery_user_id=engineer.id,
        current_amount=s_g3.delivery_amount,
        now=june_ts,
    )
    assert expected_g3_tax > Decimal("0")

    accrued_count = accrue_settlements_for_project(
        db_session, actor=admin, project_id=package.project_id
    )
    assert accrued_count == 1
    assert s_g3.status == "accrued"
    assert s_g3.withholding_tax == expected_g3_tax

    # 同月第二笔里程碑 G8（再收 50000 → delivery_amount=20000，同月累计收入 40000
    # 跨入更高预扣档位，验证 s_g3 已进入 past_rows 年度累计基数而非漏计！）
    june_later = datetime(2026, 6, 25, 10, 0, tzinfo=timezone.utc)
    pay_g8 = _make_payment(
        db_session,
        project_id=package.project_id,
        package_code=package.package_code,
        milestone_key="G8",
        amount="50000.00",
        passed_at=june_later,
    )
    record_receipt_settlements(
        db_session, actor=admin, project=project, payment=pay_g8
    )
    s_g8 = db_session.scalar(
        select(DeliverySettlement).where(
            DeliverySettlement.package_id == package.id,
            DeliverySettlement.settlement_key == "G8",
        )
    )
    assert s_g8 is not None and s_g8.seat_delivery_user_id == engineer.id

    dummy = r5._user("dummy.fresh")
    db_session.add(dummy)
    db_session.flush()
    standalone_tax = compute_withholding(
        db_session,
        delivery_user_id=dummy.id,
        current_amount=s_g8.delivery_amount,
        now=june_later,
    )
    accrue_settlements_for_project(
        db_session, actor=admin, project_id=package.project_id
    )
    assert s_g8.withholding_tax > standalone_tax


def test_qr071_five_seat_allocation_and_accrue_fallback_backfill_payee(db_session):
    """QR-071 辅链：allocate_five_seats 与 accrue 兜底均回填 seat_delivery_user_id。"""
    admin, package = r5._onsite_package(db_session)
    eng_a = r5._user("crv.e.enga", role="fde_engineer")
    eng_b = r5._user("crv.e.engb", role="fde_engineer")
    lead_u = r5._user("crv.e.lead", role="fde_engineer")
    county_u = r5._user("crv.e.county", role="fde_engineer")
    prov_u = r5._user("crv.e.prov", role="fde_engineer")
    db_session.add_all([eng_a, eng_b, lead_u, county_u, prov_u])
    db_session.flush()

    r5._active_rule(db_session, version_no=1)
    publish_package(db_session, actor=admin, package_id=package.id)
    project = db_session.get(Project, package.project_id)
    assert project is not None

    pay_m1 = _make_payment(
        db_session,
        project_id=package.project_id,
        package_code=package.package_code,
        milestone_key="G3",
        amount="60000.00",
    )
    record_receipt_settlements(
        db_session, actor=admin, project=project, payment=pay_m1
    )
    s_m1 = db_session.scalar(
        select(DeliverySettlement).where(
            DeliverySettlement.package_id == package.id,
            DeliverySettlement.settlement_key == "G3",
        )
    )
    assert s_m1 is not None and s_m1.seat_delivery_user_id is None

    allocate_five_seats(
        db_session,
        pay_m1,
        package,
        actor=admin,
        rule_snapshot={
            "five_seat": {
                "platform_share_percent": 30,
                "pool_shares": {
                    "lead": 30,
                    "delivery": 50,
                    "county": 10,
                    "province": 10,
                },
            }
        },
        seat_payees={
            "platform": None,
            "lead": lead_u.id,
            "delivery": eng_a.id,
            "county": county_u.id,
            "province": prov_u.id,
        },
    )
    assert s_m1.seat_delivery_user_id == eng_a.id

    # 历史遗留 draft 行（seat_delivery_user_id=None 而 package.seat_delivery 已在位）：
    # accrue_settlements_for_project 兜底解析并持久化回写
    pay_m2 = _make_payment(
        db_session,
        project_id=package.project_id,
        package_code=package.package_code,
        milestone_key="G8",
        amount="60000.00",
        passed_at=datetime(2026, 7, 10, 10, 0, tzinfo=timezone.utc),
    )
    record_receipt_settlements(
        db_session, actor=admin, project=project, payment=pay_m2
    )
    s_m2 = db_session.scalar(
        select(DeliverySettlement).where(
            DeliverySettlement.package_id == package.id,
            DeliverySettlement.settlement_key == "G8",
        )
    )
    assert s_m2 is not None and s_m2.seat_delivery_user_id is None
    package.seat_delivery = eng_b.id
    db_session.flush()

    accrue_settlements_for_project(
        db_session, actor=admin, project_id=package.project_id
    )
    assert s_m2.status == "accrued"
    assert s_m2.seat_delivery_user_id == eng_b.id
    assert s_m2.withholding_tax > Decimal("0")


def test_qr072_definition_gate_rejects_missing_path_param_or_unwrapped_body(
    db_session,
):
    """QR-072 定义期契约闸：solutions.create 缺 project_id 或请求体平铺顶层均返 422。"""
    admin = make_user(db_session, "admin")
    leader = make_user(db_session, "project_lead")
    project = _persist_project(db_session, leader, code=f"QE{uuid4().hex[:4]}")
    _publish_seed_skills(db_session, admin)

    broken_dag = {
        "nodes": [
            {
                "key": "solution",
                "type": "call",
                "ref": "solutions.create",
                "params": {
                    "name": "裸顶层字段未进 body 且漏路径参数",
                    "design_markdown": "x",
                },
            }
        ]
    }
    validation = validate_dag_against_registry(db_session, broken_dag)
    assert not validation.ok
    codes = {issue.code for issue in validation.errors}
    assert "call_missing_path_param" in codes
    assert "call_unwrapped_body_params" in codes

    with pytest.raises(WorkflowDefinitionError) as exc_info:
        create_definition(
            db_session,
            actor=leader,
            project_id=project.id,
            name="坏方案节点定义",
            dag=broken_dag,
        )
    assert exc_info.value.status == 422
    assert exc_info.value.code == "dag_invalid"

    invalid_body_dag = {
        "nodes": [
            {
                "key": "solution",
                "type": "call",
                "ref": "solutions.create",
                "params": {"project_id": "{{project_id}}", "body": "not-an-object"},
            }
        ]
    }
    res_invalid_body = validate_dag_against_registry(db_session, invalid_body_dag)
    assert "call_invalid_body" in {i.code for i in res_invalid_body.errors}

    # 种子模板全集（含修复后的 plan_execution）必须通过注册表全量契约校验
    seed_workflow_templates(db_session)
    from fde_api.workflows.templates import load_workflow_template_seeds

    for seed in load_workflow_template_seeds():
        res = validate_dag_against_registry(db_session, seed["dag"])
        assert res.ok, (seed["key"], [i.as_dict() for i in res.errors])


def test_qr072_compiled_delivery_workflow_executes_solutions_create_end_to_end(
    db_session, d4_app, monkeypatch
):
    """QR-072 端到端闭环：compile_delivery_preview → create/publish → run_workflow_run
    真实经过 api_actions.execute_api 落库 ProjectSolution，再停于 review 人工审批。"""
    leader = make_user(db_session, "project_lead")
    project = _persist_project(db_session, leader, code=f"QC{uuid4().hex[:4]}")

    opp_subject = ProjectResearchSubject(
        project_id=project.id,
        subject_type="opportunity",
        subject_key=f"opp-{uuid4().hex[:6]}",
        name="门店动销提升机会",
        description="降低滞销积压",
        status="active",
        tracking_code=f"OPP-{uuid4().hex[:6].upper()}",
    )
    db_session.add(opp_subject)
    db_session.flush()

    skill_key = f"delivery-research-{uuid4().hex[:6]}"
    _seed_skill(
        db_session,
        leader,
        key=skill_key,
        versions=["输出关联机会 ID 列表 JSON。"],
        scope="public",
        required_capabilities=["project.read"],
    )
    skill_ref = f"{skill_key}@1"

    preview = compile_delivery_preview(
        {
            "id": "cs-e2e-1",
            "project_id": project.id,
            "title": "端到端本体定稿",
            "status": "confirmed",
            "proposed_json": [
                {
                    "action": "create_term",
                    "term": "门店动销率",
                    "term_type": "metric",
                    "definition": "月度售罄率。",
                }
            ],
        },
        research_skill_ref=skill_ref,
    )

    defn = create_definition(
        db_session,
        actor=leader,
        project_id=project.id,
        name=preview["workflow_draft"]["name"],
        description=preview["workflow_draft"]["description"],
        dag=preview["workflow_draft"]["dag_json"],
    )
    publish_definition(db_session, actor=leader, definition=defn)
    db_session.commit()

    run, is_new = start_run(
        db_session,
        actor=leader,
        project_id=project.id,
        definition_id=defn.id,
        idempotency_key=f"qr072-e2e-{uuid4().hex[:8]}",
    )
    assert is_new
    db_session.commit()

    # 仅桩化 skill AI 模型调用（输出合法 JSON 文本），让 solutions.create 走真实 Flask 路由与落库！
    from fde_api.control import ai_server_client

    monkeypatch.setattr(
        ai_server_client,
        "execute_ai_prompt",
        lambda **_kw: json.dumps({"opportunity_ids": [opp_subject.id]}),
    )

    with d4_app.app_context():
        run_workflow_run(run.id)

    db_session.expire_all()
    refreshed_run = db_session.get(WorkflowRun, run.id)
    assert refreshed_run is not None
    assert refreshed_run.status == "waiting_approval"

    sol_node = db_session.scalar(
        select(WorkflowNodeRun).where(
            WorkflowNodeRun.run_id == run.id,
            WorkflowNodeRun.node_key == "solution",
        )
    )
    assert sol_node is not None
    assert sol_node.status == "succeeded", sol_node.error

    created_solutions = db_session.scalars(
        select(ProjectSolution).where(ProjectSolution.project_id == project.id)
    ).all()
    assert len(created_solutions) == 1
    assert created_solutions[0].name == preview["solution_skeleton"]["name"]
    assert [link.opportunity_id for link in created_solutions[0].opportunities] == [
        opp_subject.id
    ]


def test_qr073_and_host_channel_absorbed_items_verification(
    monkeypatch,
):
    """QR-073 三形态路径钉 + #422/#433 宿主通道吸收项（QR-088/089/092/094/095）核销。"""
    for unsafe in (
        "/etc/passwd",
        "../secret.txt",
        "reports/../../secret.txt",
        "C:\\Windows\\System32\\drivers\\etc\\hosts",
        "D:/test/FDE/secret.md",
        "\\Windows\\win.ini",
        "\\\\server\\share\\leak.txt",
    ):
        assert is_unsafe_artifact_path(unsafe) is True, unsafe
    assert is_unsafe_artifact_path("reports/summary.md") is False

    assert "with_for_update" in inspect.getsource(agent_service.claim_host_run)
    assert hasattr(AgentRun, "frozen_tools")

    monkeypatch.setenv("FDE_JWT_SECRET", "top-secret-do-not-leak")
    monkeypatch.setenv("CUSTOM_API_TOKEN", "leak-token")
    env = host_channel.host_channel_env(extra={"SAFE_KEY": "1"})
    assert "FDE_JWT_SECRET" not in env
    assert "CUSTOM_API_TOKEN" not in env
    assert env.get("SAFE_KEY") == "1"

    src_listen = inspect.getsource(agent_adapter.ZcodeAdapter._listen_and_reclaim)
    assert 'elif kind == "done":' in src_listen
    assert "break" in src_listen
    src_receipt = inspect.getsource(submit_host_receipt)
    assert "isinstance(raw_exit, bool)" in src_receipt
    assert "exit_code != 0" in src_receipt
