"""V3.3 M5-WP3④：``<0.8`` 复核分流视图 + ``≥80%`` 免改率后台遥测（D31）。

验收语义（工作令 §3 WP3 条 4 / D31 / M5-OPT-3）：
- **复核分流视图**：项目级只读投影——活跃绑定钉版的治理摘要分流出
  低置信度（``<0.8``）/冲突候选**未处置明细**（重点复核队列）、72h SLA
  账龄预警、映射/绑定缺口；72h 结算锚 runtime UTC ``submitted_at`` 单一
  权威时钟（runtime ``sla_aging`` 原样透传，Workbench 不引入第二时钟）；
- **古德哈特护栏双向钉死**：免改率遥测是后台内部 SLO（``target=0.80``），
  绝不进项目 Gate 准入（Gate 只查 100% 处置闭环，WP2 已钉）；
- **遥测数据源 = 本地不可变回执快照**（D29 口径）：从
  ``GateEvaluationReceipt.summary_json.compiler_telemetry`` 聚合——历史重放
  免疫实时网络抖动，零 runtime 依赖；每 (project, gate) 取最新回执防重复计数。
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from fde_api.integrations.models import ProjectOntologyBinding
from fde_api.integrations.ontology_mock import (
    M5_SEED_VERSION_ID,
    SEED_ONTOLOGY_ID,
    MockOntologyAdapter,
)
from fde_api.projects.gate_receipt import GateEvaluationReceipt
from fde_api.workbench.models import Project

from test_gates_api import admin_client, gate_project  # noqa: F401  (fixture 供给方)


# ---------------------------------------------------------------- fixtures


def _queue_env(gate_project, db_session, settings, monkeypatch, *, enabled: bool = True):
    """(project, admin_user, binding 钉 M5 演示版 1.1.0 + 注入未处置候选)。

    mock 种子候选按 org 过滤（硬编码 org-1）——往 adapter._change_sets 注入
    一条**匹配项目 org** 的待处置候选（形状照抄种子 cs-m5-draft，白盒同形），
    分流视图才有可复核队列。
    """
    monkeypatch.setattr(settings, "ontology_enabled", enabled, raising=False)
    project, _url, leader = gate_project
    project_row = db_session.get(Project, project["id"])
    binding = ProjectOntologyBinding(
        org_id=project_row.org_id,
        project_id=project["id"],
        ontology_id=SEED_ONTOLOGY_ID,
        pinned_version_id=M5_SEED_VERSION_ID,
        pinned_version="1.1.0",
        binding_role="primary",
        status="active",
        active_marker="active",
        bound_by_user_id=leader.user.id,
    )
    db_session.add(binding)
    db_session.commit()
    return {"project": project, "admin_user": leader.user, "binding": binding}


def _adapter_with_pending_candidate(org_id: str) -> MockOntologyAdapter:
    adapter = MockOntologyAdapter()
    adapter._change_sets["cs-test-pending"] = {
        "id": "cs-test-pending",
        "ontology_id": SEED_ONTOLOGY_ID,
        "org_id": org_id,
        "project_id": "proj-any",
        "title": "测试注入：待处置候选",
        "description": "",
        "status": "draft",
        "proposed_json": [
            {
                "entity_type": "object_types",
                "key": "defect_v2",
                "op": "create",
                "captured_from": {"agent_run": "ar-test", "confidence": 0.5, "conflicts": []},
            }
        ],
        "captured_from": "agent_run:ar-test",
        "approvals": {},
        "created_by": "u1",
        "submitted_at": "2026-11-01T00:00:00+00:00",
        "_status": 200,
    }
    return adapter


# ---------------------------------------------------------------- 复核分流视图


def test_review_queue_projects_disposition_and_sla(
    gate_project, db_session, settings, monkeypatch
):
    """分流视图：未处置候选明细 + SLA 账龄 + 缺口 + all_disposed 透传。"""
    from fde_api.ontology.governance import build_review_queue

    env = _queue_env(gate_project, db_session, settings, monkeypatch)
    report = build_review_queue(
        db_session,
        actor=env["admin_user"],
        project_id=env["project"]["id"],
        settings=settings,
        client=_adapter_with_pending_candidate(str(env["binding"].org_id)),
    )
    assert report["ontology_id"] == SEED_ONTOLOGY_ID
    assert report["pinned_version"] == "1.1.0"
    # mock 种子：一个未处置低置信度 draft 候选（D31 口径，parity 测试同款钉）
    assert report["queue"]["all_disposed"] is False
    assert len(report["queue"]["undisposed"]) >= 1
    assert report["queue"]["sla_threshold_hours"] == 72
    assert report["gate_ready"] is False


def test_review_queue_disabled_is_404_and_no_binding_409(
    gate_project, db_session, settings, monkeypatch
):
    """门控三态：disabled → 404（D12/D13）；无绑定 → 409 诚实缺省。"""
    from fde_api.ontology.governance import GovernanceError, build_review_queue

    env = _queue_env(gate_project, db_session, settings, monkeypatch, enabled=False)
    with pytest.raises(GovernanceError) as excinfo:
        build_review_queue(
            db_session, actor=env["admin_user"],
            project_id=env["project"]["id"], settings=settings,
        )
    assert excinfo.value.status == 404

    monkeypatch.setattr(settings, "ontology_enabled", True, raising=False)
    db_session.delete(env["binding"])
    db_session.commit()
    with pytest.raises(GovernanceError) as excinfo:
        build_review_queue(
            db_session, actor=env["admin_user"],
            project_id=env["project"]["id"], settings=settings,
        )
    assert excinfo.value.code == "no_active_binding"


def test_review_queue_cross_tenant_is_404(
    gate_project, db_session, settings, monkeypatch
):
    """② party 评审钉：启用态跨租户隔离——外企业用户 → 404（S-01 同形）。

    m8 排除登记的理由句承诺「启用态跨租户 404 隔离由本文件专测钉死」，
    本用例兑现该引用（party 六席评审 P1-B：登记不得开空头支票）。
    """
    from fde_api.auth.models import User
    from fde_api.ontology.governance import GovernanceError, build_review_queue
    from fde_api.orgs.models import ORG_TYPE_ENTERPRISE
    from fde_api.orgs.models import Org

    env = _queue_env(gate_project, db_session, settings, monkeypatch)
    db_session.add(Org(id="org-outsider", org_type=ORG_TYPE_ENTERPRISE, name="外企业-分流队列隔离"))
    db_session.flush()
    outsider = User(
        username="wp3-queue-outsider",
        role="project_lead",
        org_id="org-outsider",
        password_hash="x",
        must_change_password=False,
        is_active=True,
    )
    db_session.add(outsider)
    db_session.commit()
    with pytest.raises(GovernanceError) as excinfo:
        build_review_queue(
            db_session,
            actor=outsider,
            project_id=env["project"]["id"],
            settings=settings,
            client=_adapter_with_pending_candidate(str(env["binding"].org_id)),
        )
    assert excinfo.value.status == 404
    db_session.rollback()


# ---------------------------------------------------------------- 遥测指标


def _receipt(db_session, project_id: str, gate_key: str, rate: float, *, minutes: int) -> None:
    db_session.add(
        GateEvaluationReceipt(
            project_id=project_id,
            gate_key=gate_key,
            ontology_id=SEED_ONTOLOGY_ID,
            pinned_version_id=M5_SEED_VERSION_ID,
            input_snapshot_sha256="c" * 64,
            breaker_state="closed",
            disposition_closed=True,
            revision=1,
            result="pass",
            input_snapshot_json={},
            ontology_checks_json={
                "compiler_telemetry": {
                    "unmodified_accept_rate": rate,
                    "accepted_count": 10,
                    "unmodified_count": int(rate * 10),
                    "rejected_count": 1,
                }
            },
            gate_ready=True,
            decided_at=datetime.now(UTC).replace(minute=minutes % 60),
        )
    )


def test_telemetry_aggregates_latest_receipt_snapshots(
    gate_project, db_session, settings, monkeypatch
):
    """免改率遥测：每 (project, gate) 最新回执快照均值 + target 0.80。"""
    from fde_api.metrics.service import build_metrics_report

    monkeypatch.setattr(settings, "ontology_enabled", False, raising=False)
    project, _url, _leader = gate_project
    _receipt(db_session, project["id"], "G5", 0.9, minutes=5)
    _receipt(db_session, project["id"], "G5", 0.7, minutes=2)  # 旧回执 → 不计入
    _receipt(db_session, project["id"], "G9", 0.5, minutes=3)
    db_session.commit()
    report = build_metrics_report(db_session)
    m5 = report["sections"]["m5_governance"]
    metric = next(m for m in m5 if m["key"] == "ontology_compiler_unmodified_accept_rate")
    assert metric["sample_size"] == 2  # (G5 最新 0.9) + (G9 0.5)
    assert metric["value"] == 0.7  # (0.9 + 0.5) / 2
    assert metric["target"] == 0.80
    assert "Gate" in metric["definition"]  # 古德哈特护栏口径写进指标定义


def test_telemetry_without_receipts_is_insufficient(
    gate_project, db_session, settings, monkeypatch
):
    """零回执 → insufficient_data（不伪造分母）。"""
    from fde_api.metrics.service import build_metrics_report

    monkeypatch.setattr(settings, "ontology_enabled", False, raising=False)
    project, _url, _leader = gate_project
    db_session.commit()
    report = build_metrics_report(db_session)
    m5 = report["sections"]["m5_governance"]
    metric = next(m for m in m5 if m["key"] == "ontology_compiler_unmodified_accept_rate")
    assert metric["status"] == "insufficient_data"


# ---------------------------------------------------------------- 路由烟测


def test_review_queue_route_http(
    gate_project, admin_client, client, db_session, settings, monkeypatch
):
    """GET …/ontology/review-queue（can_view 只读面）。"""
    env = _queue_env(gate_project, db_session, settings, monkeypatch)
    monkeypatch.setattr(
        "fde_api.integrations.service.client_from_settings",
        lambda: _adapter_with_pending_candidate(str(env["binding"].org_id)),
    )
    pid = env["project"]["id"]
    response = admin_client.get(f"/api/v1/projects/{pid}/ontology/review-queue")
    assert response.status_code == 200, response.get_data(as_text=True)
    body = response.json["data"]
    assert body["queue"]["all_disposed"] is False
