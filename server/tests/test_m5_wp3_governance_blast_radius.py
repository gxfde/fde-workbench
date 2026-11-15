"""V3.3 M5-WP3②：升级爆炸半径聚合报告（D29 两段式第②段，独立新模块 governance）。

验收语义（工作令 §3 WP3 条 2 / D29 / §13 M5 条 5）：
- **跨仓两段式严守边界**：ontology-service 只给纯 schema 级 diff（WP1 impact
  端点，零项目态耦合）；Workbench 侧在本地 Join 活跃绑定、S-13 钉版证据、
  GateEvaluationReceipt、WorkflowRun 五元组快照（D27）汇总**业务爆炸半径**；
- Agent 维度归并说明：Agent 经项目绑定间接引用本体（Logic/Action 工具桥），
  无独立本体引用列——并入 binding 维度计数，不造无据之数；
- **绑定平滑切换审批流衔接**：报告尾部挂既有
  ``OntologyBindingUpgrade``（proposed/approved/rejected）pending 态视图，
  审批本体复用 ``integrations.service.propose_upgrade/approve_upgrade``（M4
  既有流，行锁 + pending 唯一 + 异人 approved_by），不在本模块重建；
- 纯函数聚合层 100% 确定性生成（工作令 §1 条 6）；本模块零 DDL、不触碰
  ``ontology/service.py``。
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from fde_api.evidence.models import ProjectEvidence
from fde_api.integrations.models import ProjectOntologyBinding
from fde_api.integrations.ontology_mock import (
    M5_SEED_VERSION_ID,
    SEED_ONTOLOGY_ID,
    SEED_VERSION_ID,
    MockOntologyAdapter,
)
from fde_api.projects.gate_receipt import GateEvaluationReceipt
from fde_api.workbench.models import Project

from test_gates_api import admin_client, gate_project  # noqa: F401  (fixture 供给方)


# ---------------------------------------------------------------- fixtures


def _blast_env(gate_project, db_session, settings, monkeypatch, *, enabled: bool = True):
    """(project, admin_user, binding) + 钉版证据行 + 钉版回执行。

    binding 钉 seed 1.0.0（SEED_VERSION_ID）——升级目标取种子 1.1.0，
    mock diff 有 1.0.0→1.1.0 现成版本对（parity 种子同款）。
    """
    monkeypatch.setattr(settings, "ontology_enabled", enabled, raising=False)
    project, _gates_url, leader = gate_project
    project_row = db_session.get(Project, project["id"])
    binding = ProjectOntologyBinding(
        org_id=project_row.org_id,
        project_id=project["id"],
        ontology_id=SEED_ONTOLOGY_ID,
        pinned_version_id=SEED_VERSION_ID,
        pinned_version="1.0.0",
        binding_role="primary",
        status="active",
        active_marker="active",
        bound_by_user_id=leader.user.id,
    )
    db_session.add(binding)
    db_session.add(
        ProjectEvidence(
            project_id=project["id"],
            kind="gate",
            source_uri="fdeops://m5/blast-ev",
            content_sha256="a" * 64,
            ontology_id=SEED_ONTOLOGY_ID,
            pinned_version_id=SEED_VERSION_ID,
        )
    )
    db_session.add(
        GateEvaluationReceipt(
            project_id=project["id"],
            gate_key="G5",
            ontology_id=SEED_ONTOLOGY_ID,
            pinned_version_id=SEED_VERSION_ID,
            input_snapshot_sha256="b" * 64,
            breaker_state="closed",
            disposition_closed=True,
            revision=1,
            result="pass",
            input_snapshot_json={},
            ontology_checks_json={"candidate_disposition": {"all_disposed": True}},
            gate_ready=True,
            decided_at=datetime.now(UTC),
            created_by_user_id=leader.user.id,
        )
    )
    db_session.commit()
    return {
        "project": project,
        "project_row": project_row,
        "admin_user": leader.user,
        "binding": binding,
    }


# ---------------------------------------------------------------- 纯函数层


def test_summarize_counts_four_dimensions_and_breaking_flag() -> None:
    """四面聚合计数 + breaking 升审旗标 + Agent 归并说明字段。"""
    from fde_api.ontology.governance import summarize_blast_radius

    impact = {
        "compat": "breaking",
        "breaking_changes": [{"kind": "property_removed", "path": "Product.qc"}],
        "additive_changes": [],
        "internal_cascades": [],
    }
    report = summarize_blast_radius(
        impact,
        bindings=[{"id": "bd-1", "status": "active", "pinned_version": "1.0.0"}],
        evidence_refs=[{"evidence_id": "ev-1", "kind": "gate"}],
        gate_receipts=[{"receipt_id": "rc-1", "gate_key": "G5"}],
        workflow_runs=[
            {
                "run_id": "run-1",
                "snapshot_pinned_version_id": M5_SEED_VERSION_ID,
            },
            {
                "run_id": "run-2",
                "snapshot_pinned_version_id": "ver-other",
            },
        ],
        pinned_version_id=M5_SEED_VERSION_ID,
    )
    radius = report["blast_radius"]
    assert radius["active_binding_count"] == 1
    assert radius["evidence_pinned_count"] == 1
    assert radius["gate_receipt_count"] == 1
    assert radius["workflow_run_pinned_count"] == 1  # run-2 不命中当前钉版
    assert radius["total_references"] == 4
    assert radius["requires_upgrade_review"] is True  # breaking → 必审
    assert "agent_via_binding" in radius  # Agent 归并说明（不造独立计数）


def test_summarize_additive_only_without_refs_is_review_free() -> None:
    """纯 additive 且本地零引用 → 无需升级评审（诚实零计数）。"""
    from fde_api.ontology.governance import summarize_blast_radius

    report = summarize_blast_radius(
        {"compat": "compatible", "breaking_changes": [], "additive_changes": [{"kind": "x"}]},
        bindings=[], evidence_refs=[], gate_receipts=[], workflow_runs=[],
        pinned_version_id="ver-x",
    )
    radius = report["blast_radius"]
    assert radius["total_references"] == 0
    assert radius["requires_upgrade_review"] is False


def test_summarize_truncated_counts_after_pinned_filter() -> None:
    """P6（评审边界）：detail_truncated 按**钉版命中后**的明细数判定。

    大量不命中当前钉版的 run 不构成明细截断——旗标语义与展示口径一致。
    """
    from fde_api.ontology.governance import summarize_blast_radius

    unrelated = [
        {"run_id": f"run-{i}", "snapshot_pinned_version_id": "ver-other"}
        for i in range(25)
    ]
    report = summarize_blast_radius(
        {"compat": "compatible", "breaking_changes": [], "additive_changes": []},
        bindings=[],
        evidence_refs=[],
        gate_receipts=[],
        workflow_runs=unrelated,
        pinned_version_id=M5_SEED_VERSION_ID,
    )
    radius = report["blast_radius"]
    assert radius["workflow_run_pinned_count"] == 0
    assert radius["detail_truncated"] is False  # 25 条不命中 → 明细为空，非截断


# ---------------------------------------------------------------- 服务层


def test_blast_radius_disabled_flag_is_404(
    gate_project, db_session, settings, monkeypatch
):
    """ontology_enabled=False → 整面 404（D12/D13 门控，与绑定面同款语义）。"""
    from fde_api.ontology.governance import GovernanceError, build_upgrade_blast_radius

    env = _blast_env(gate_project, db_session, settings, monkeypatch, enabled=False)
    with pytest.raises(GovernanceError) as excinfo:
        build_upgrade_blast_radius(
            db_session,
            actor=env["admin_user"],
            project_id=env["project"]["id"],
            to_version="1.2.0",
            settings=settings,
        )
    assert excinfo.value.status == 404


def test_blast_radius_without_binding_is_409(
    gate_project, db_session, settings, monkeypatch
):
    """无活跃绑定 → 409 no_active_binding（诚实缺省，不聚空报告）。"""
    from fde_api.ontology.governance import GovernanceError, build_upgrade_blast_radius

    env = _blast_env(gate_project, db_session, settings, monkeypatch)
    db_session.delete(env["binding"])
    db_session.commit()
    with pytest.raises(GovernanceError) as excinfo:
        build_upgrade_blast_radius(
            db_session,
            actor=env["admin_user"],
            project_id=env["project"]["id"],
            to_version="1.2.0",
            settings=settings,
        )
    assert excinfo.value.code == "no_active_binding"


def test_blast_radius_aggregates_local_references(
    gate_project, db_session, settings, monkeypatch
):
    """服务级聚合：mock diff（1.0.0→1.1.0，仅现场绑定变化）× 本地证据/回执计数。"""
    from fde_api.ontology.governance import build_upgrade_blast_radius

    env = _blast_env(gate_project, db_session, settings, monkeypatch)
    report = build_upgrade_blast_radius(
        db_session,
        actor=env["admin_user"],
        project_id=env["project"]["id"],
        to_version="1.1.0",
        settings=settings,
        client=MockOntologyAdapter(),
    )
    assert report["ontology_id"] == SEED_ONTOLOGY_ID
    assert report["from_version"] == "1.0.0"
    assert report["to_version"] == "1.1.0"
    assert report["impact"]  # WP1 diff 原样透传（_status 剥离）
    radius = report["blast_radius"]
    assert radius["evidence_pinned_count"] == 1
    assert radius["gate_receipt_count"] == 1
    assert radius["active_binding_count"] == 1
    # 衔接既有绑定升级审批流（当前无 pending → null）
    assert report["binding_upgrade"]["pending"] is None


def test_blast_radius_counts_only_active_bindings(
    gate_project, db_session, settings, monkeypatch
):
    """P5（评审审计）：非活跃（retired）绑定不计入爆炸半径（§1 条 5 活跃口径）。

    字段名 active_binding_count 名实必须相符——历史/退役绑定虚增引用数会
    误触 requires_upgrade_review 必审旗标。
    """
    from fde_api.integrations.models import ProjectOntologyBinding
    from fde_api.ontology.governance import build_upgrade_blast_radius

    env = _blast_env(gate_project, db_session, settings, monkeypatch)
    project_row = env["project_row"]
    db_session.add(
        ProjectOntologyBinding(
            org_id=project_row.org_id,
            project_id=env["project"]["id"],
            ontology_id=SEED_ONTOLOGY_ID,
            pinned_version_id=SEED_VERSION_ID,
            pinned_version="1.0.0",
            binding_role="primary",
            status="retired",
            active_marker="retired-legacy",
            bound_by_user_id=env["admin_user"].id,
        )
    )
    db_session.commit()
    report = build_upgrade_blast_radius(
        db_session,
        actor=env["admin_user"],
        project_id=env["project"]["id"],
        to_version="1.1.0",
        settings=settings,
        client=MockOntologyAdapter(),
    )
    assert report["blast_radius"]["active_binding_count"] == 1  # retired 行不计入
    db_session.rollback()


def test_blast_radius_runtime_unavailable_is_503(
    gate_project, db_session, settings, monkeypatch
):
    """diff 拉取失败 → 503（爆炸半径的核心输入就是 diff，禁降级编报告）。"""
    from fde_api.ontology.governance import GovernanceError, build_upgrade_blast_radius

    env = _blast_env(gate_project, db_session, settings, monkeypatch)
    adapter = MockOntologyAdapter()
    adapter.inject_fault("unavailable")
    with pytest.raises(GovernanceError) as excinfo:
        build_upgrade_blast_radius(
            db_session,
            actor=env["admin_user"],
            project_id=env["project"]["id"],
            to_version="1.1.0",
            settings=settings,
            client=adapter,
        )
    assert excinfo.value.status == 503


def test_blast_radius_cross_tenant_is_404(
    gate_project, db_session, settings, monkeypatch
):
    """② party 评审钉：启用态跨租户隔离——外企业用户 → 404（S-01 同形）。

    m8 排除登记的理由句承诺「启用态跨租户 404 隔离由本文件专测钉死」，
    本用例兑现该引用（party 六席评审 P1-B：登记不得开空头支票）。
    """
    from fde_api.auth.models import User
    from fde_api.ontology.governance import GovernanceError, build_upgrade_blast_radius
    from fde_api.orgs.models import ORG_TYPE_ENTERPRISE
    from fde_api.orgs.models import Org

    env = _blast_env(gate_project, db_session, settings, monkeypatch)
    db_session.add(Org(id="org-outsider", org_type=ORG_TYPE_ENTERPRISE, name="外企业-爆炸半径隔离"))
    db_session.flush()
    outsider = User(
        username="wp3-blast-outsider",
        role="project_lead",
        org_id="org-outsider",  # 非本项目 org → org_scope_allows 拒绝
        password_hash="x",
        must_change_password=False,
        is_active=True,
    )
    db_session.add(outsider)
    db_session.commit()
    with pytest.raises(GovernanceError) as excinfo:
        build_upgrade_blast_radius(
            db_session,
            actor=outsider,
            project_id=env["project"]["id"],
            to_version="1.1.0",
            settings=settings,
            client=MockOntologyAdapter(),
        )
    assert excinfo.value.status == 404
    db_session.rollback()


# ---------------------------------------------------------------- 路由烟测


def test_blast_radius_route_http(
    gate_project, admin_client, client, db_session, settings, monkeypatch
):
    """GET …/ontology/upgrade-blast-radius?to_version=（can_view 只读面）。"""
    env = _blast_env(gate_project, db_session, settings, monkeypatch)
    # 路由经 client_from_settings 惰性建 client——monkeypatch 到 mock 种子
    monkeypatch.setattr(
        "fde_api.integrations.service.client_from_settings",
        lambda: MockOntologyAdapter(),
    )
    pid = env["project"]["id"]
    response = admin_client.get(
        f"/api/v1/projects/{pid}/ontology/upgrade-blast-radius?to_version=1.1.0"
    )
    assert response.status_code == 200, response.get_data(as_text=True)
    body = response.json["data"]
    assert body["blast_radius"]["evidence_pinned_count"] >= 1
