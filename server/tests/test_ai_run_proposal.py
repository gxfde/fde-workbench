"""AI 发起 run 受控提议通道（N5，G-02）——propose→密码确认→落 run。

钉住：①propose 闸＝幂等键必填 400；②propose 只提议不落 run（未确认零
run）；③confirm 端到端审计链（requested/started/finished，密码永不入事件）；
④取消语义反例：同键已终结 run（workflows cancelled／agents 终态失败）⇒
409 run_cancelled_not_revivable＋零新 run（AI 不代重试）；⑤幂等键反例：
双 execution_id 同键双确认 ⇒ run 表恰 1 行；⑥授权绑定反例：scope 不匹配
propose 即 403 零落库／confirm 时授权已失效重跑 _authorized 403／auth_version
变更 409；⑦过期提议 409 零 run；⑧驳回零 run；⑨目录双钉（确认类 risk 3＋
接管/重试永不收编）＋守卫源级顺序钉。
"""
from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import select

from conftest import SERVER_ROOT

from test_agents_d4_harness import d4_settings, make_user, prime_run, seed_agent  # noqa: F401  (pytest fixture)
from test_ai_server_chat_mcp import ai_context, make_project
from test_document_drafts_api import _persist_project
from test_workflow_definition import _call, _dag
from test_workflow_runs import _make_run

from fde_api.agents.models import AgentRun
from fde_api.auth.passwords import hash_password
from fde_api.control.access import capabilities_for_level
from fde_api.control.api_actions import RUN_START_OPERATIONS, decide_action, execute_api, pending_actions
from fde_api.control.api_catalog import CATALOG, CONFIRMATION_KEYS, ENTRIES
from fde_api.control.service import ControlServiceError
from fde_api.workbench.models import OperationEvent
from fde_api.workflows.definition_service import create_definition, publish_definition
from fde_api.workflows.models import WorkflowRun

_CONFIRM_PASSWORD = "n5-run-confirm"


def _invoke(user, operation, parameters=None, body=None, *, execution=None, scope=None, level="system_operator"):
    return execute_api(user=user, claims={"execution_id": execution or str(uuid4()), "project_id": scope},
        allowed=set(capabilities_for_level(level)), operation=operation, parameters=parameters, body=body)


def _set_password(db_session, user) -> None:
    user.password_hash = hash_password(_CONFIRM_PASSWORD)
    db_session.commit()


def _published_definition(db_session, leader, project):
    """纯 call 链定义（call 白名单=api_catalog，无需种子 skill）经真实发布链到 published。"""
    definition = create_definition(
        db_session, actor=leader, project_id=project.id, name=f"编排{uuid4().hex[:4]}",
        dag=_dag(_call("gather", output="subjects"), _call("draft", ["gather"], output="hint")),
    )
    publish_definition(db_session, actor=leader, definition=definition)
    db_session.commit()
    return definition


def _run_count(db_session, model, key: str) -> int:
    return len(db_session.scalars(select(model).where(model.idempotency_key == key)).all())


def _events(db_session, identifier: str) -> list[OperationEvent]:
    return db_session.scalars(
        select(OperationEvent)
        .where(OperationEvent.target_id == identifier)
        .order_by(OperationEvent.created_at)
    ).all()


# ---------------------------------------------------------------- 目录双钉


def test_catalog_pins_run_start_as_confirmation_class():
    """两条 run_start 是确认类（risk 3），且进 CONFIRMATION_KEYS。"""
    assert ENTRIES and len(ENTRIES) == 98
    for key in ("workflows.run_start", "agents.run_start"):
        row = CATALOG[key]
        assert row["confirmation"] is True
        assert row["risk"] == 3
        assert row["write"] is True
        assert key in CONFIRMATION_KEYS
    # 接管/重试类动作永不收编（宿主通道红线④：AI 不代接管/重试）。
    for banned in ("agents.run_takeover", "agents.run_retry", "workflows.run_retry", "workflows.run_cancel"):
        assert banned not in CATALOG


def test_catalog_paths_resolve_existing_routes_for_run_start(app):
    """两条 ENTRIES 的 path 模板解析到真实路由（防目录悬空）。"""
    paths = {"/api/v1/projects/{project_id}/workflows/{definition_id}/runs", "/api/v1/agents/{agent_id}/run"}
    matched = {row["path"] for row in CATALOG.values() if row["path"] in paths}
    assert matched == paths
    for row in (CATALOG["workflows.run_start"], CATALOG["agents.run_start"]):
        assert row["path"].count("{") == row["path"].count("}")
        assert row["method"] == "POST"


# ---------------------------------------------------------------- propose 闸


def test_run_start_proposals_require_idempotency_key(ai_context, db_session, d4_settings):
    """缺幂等键/空白键 ⇒ 400 run_start_idempotency_required，零提议零 run。"""
    users, _ = ai_context
    admin = users["admin"]
    project = make_project(db_session, admin)
    definition = _published_definition(db_session, admin, project)
    with pytest.raises(ControlServiceError) as wf:
        _invoke(admin, "workflows.run_start", {"project_id": project.id, "definition_id": definition.id}, {"context": {}})
    assert wf.value.code == "run_start_idempotency_required"
    assert wf.value.status == 400
    with pytest.raises(ControlServiceError) as blank:
        _invoke(admin, "workflows.run_start", {"project_id": project.id, "definition_id": definition.id}, {"idempotency_key": "   "})
    assert blank.value.code == "run_start_idempotency_required"
    registry = seed_agent(db_session, d4_settings)
    with pytest.raises(ControlServiceError) as ag:
        _invoke(admin, "agents.run_start", {"agent_id": registry.id}, {"project_id": project.id})
    assert ag.value.code == "run_start_idempotency_required"
    assert db_session.scalars(select(OperationEvent).where(OperationEvent.event_type == "ai.api.requested", OperationEvent.actor_user_id == admin.id)).all() == []


# ---------------------------------------------------------------- 未确认零 run


def test_workflows_propose_awaits_without_creating_run(ai_context, db_session):
    """propose 即 awaiting_confirmation：run 表零行、pending 列表在列、审计 confirmation_required=True。"""
    users, _ = ai_context
    admin = users["admin"]
    project = make_project(db_session, admin)
    definition = _published_definition(db_session, admin, project)
    key = f"n5-wf-{uuid4().hex[:8]}"
    result = _invoke(admin, "workflows.run_start", {"project_id": project.id, "definition_id": definition.id}, {"idempotency_key": key})
    assert result["status"] == "awaiting_confirmation"
    assert _run_count(db_session, WorkflowRun, key) == 0
    assert pending_actions(admin)[0]["operation"] == "workflows.run_start"
    requested = [e for e in _events(db_session, result["action_id"]) if e.event_type == "ai.api.requested"]
    assert len(requested) == 1 and requested[0].changes["confirmation_required"] is True


# ---------------------------------------------------------------- confirm 端到端


def test_workflows_confirm_runs_and_audits_end_to_end(ai_context, db_session):
    """密码确认 ⇒ 经既有发起路由真实落 run；审计链三事件且零密码字段。"""
    users, _ = ai_context
    admin = users["admin"]
    _set_password(db_session, admin)
    project = make_project(db_session, admin)
    definition = _published_definition(db_session, admin, project)
    key = f"n5-wf-{uuid4().hex[:8]}"
    result = _invoke(admin, "workflows.run_start", {"project_id": project.id, "definition_id": definition.id}, {"idempotency_key": key})
    outcome = decide_action(admin, result["action_id"], _CONFIRM_PASSWORD)
    assert outcome["status"] == "completed"
    assert outcome["http_status"] == 201
    run = db_session.scalar(select(WorkflowRun).where(WorkflowRun.idempotency_key == key))
    assert run is not None and run.status == "queued" and run.project_id == project.id
    events = _events(db_session, result["action_id"])
    assert [e.event_type for e in events] == ["ai.api.requested", "ai.api.started", "ai.api.finished"]
    assert all(_CONFIRM_PASSWORD not in json.dumps(e.changes, ensure_ascii=False) for e in events)


def test_agents_confirm_runs_and_audits_end_to_end(ai_context, db_session, d4_settings, app):
    """agents 链同构：propose→密码确认⇒agent_runs 落行（201；沙箱经 prime_run 假件）。"""
    users, _ = ai_context
    admin = users["admin"]
    _set_password(db_session, admin)
    project = make_project(db_session, admin)
    registry = seed_agent(db_session, d4_settings)
    prime_run(app)  # 注入假沙箱后端（测试环境无 zcode 运行时）
    key = f"n5-ag-{uuid4().hex[:8]}"
    result = _invoke(admin, "agents.run_start", {"agent_id": registry.id}, {"project_id": project.id, "idempotency_key": key})
    assert result["status"] == "awaiting_confirmation"
    outcome = decide_action(admin, result["action_id"], _CONFIRM_PASSWORD)
    assert outcome["status"] == "completed"
    assert outcome["http_status"] == 201
    run = db_session.scalar(select(AgentRun).where(AgentRun.idempotency_key == key))
    assert run is not None and run.project_id == project.id and run.agent_id == registry.id
    assert _run_count(db_session, AgentRun, key) == 1


# ---------------------------------------------------------------- 反例①取消语义


def test_cancelled_workflow_run_is_not_revivable(ai_context, db_session):
    """propose 后人工取消同键 run ⇒ confirm 409 run_cancelled_not_revivable＋零新 run。"""
    users, _ = ai_context
    admin = users["admin"]
    _set_password(db_session, admin)
    project = make_project(db_session, admin)
    definition = _published_definition(db_session, admin, project)
    key = f"n5-wf-{uuid4().hex[:8]}"
    result = _invoke(admin, "workflows.run_start", {"project_id": project.id, "definition_id": definition.id}, {"idempotency_key": key})
    assert result["status"] == "awaiting_confirmation"
    human = _make_run(db_session, definition, project, admin, key=key)
    human.status = "cancelled"
    db_session.commit()
    with pytest.raises(ControlServiceError) as denied:
        decide_action(admin, result["action_id"], _CONFIRM_PASSWORD)
    assert denied.value.code == "run_cancelled_not_revivable"
    assert denied.value.status == 409
    assert _run_count(db_session, WorkflowRun, key) == 1  # 只有人工取消那行，确认未复活


def test_failed_agent_run_is_not_revivable(ai_context, db_session, d4_settings):
    """agents 无取消路由：同键终态失败 run 经确认 ⇒ 409（AI 不代重试）＋零新 run。"""
    users, _ = ai_context
    admin = users["admin"]
    _set_password(db_session, admin)
    project = make_project(db_session, admin)
    registry = seed_agent(db_session, d4_settings)
    key = f"n5-ag-{uuid4().hex[:8]}"
    result = _invoke(admin, "agents.run_start", {"agent_id": registry.id}, {"project_id": project.id, "idempotency_key": key})
    assert result["status"] == "awaiting_confirmation"
    db_session.add(AgentRun(project_id=project.id, agent_id=registry.id, initiated_by_user_id=admin.id,
        capability_used=registry.capability_tier, status="failed", context_ref="human-first-attempt",
        idempotency_key=key, cost_owner_type="project"))
    db_session.commit()
    with pytest.raises(ControlServiceError) as denied:
        decide_action(admin, result["action_id"], _CONFIRM_PASSWORD)
    assert denied.value.code == "run_cancelled_not_revivable"
    assert _run_count(db_session, AgentRun, key) == 1


# ---------------------------------------------------------------- 反例②幂等键


def test_same_key_double_confirmation_yields_single_run(ai_context, db_session):
    """双 execution_id 同键双提议双确认 ⇒ 生产幂等复用，run 表恰 1 行。"""
    users, _ = ai_context
    admin = users["admin"]
    _set_password(db_session, admin)
    project = make_project(db_session, admin)
    definition = _published_definition(db_session, admin, project)
    key = f"n5-wf-{uuid4().hex[:8]}"
    first = _invoke(admin, "workflows.run_start", {"project_id": project.id, "definition_id": definition.id}, {"idempotency_key": key}, execution=str(uuid4()))
    second = _invoke(admin, "workflows.run_start", {"project_id": project.id, "definition_id": definition.id}, {"idempotency_key": key}, execution=str(uuid4()))
    assert first["action_id"] != second["action_id"]  # execution_id 参与 identifier：两条独立提议
    assert decide_action(admin, first["action_id"], _CONFIRM_PASSWORD)["http_status"] == 201
    replay = decide_action(admin, second["action_id"], _CONFIRM_PASSWORD)
    assert replay["status"] == "completed"
    assert replay["http_status"] == 200  # 幂等复用既有 run（V8：不重复落行）
    assert _run_count(db_session, WorkflowRun, key) == 1


# ---------------------------------------------------------------- 反例③授权绑定


def test_scope_mismatch_rejected_at_propose(ai_context, db_session):
    """scope 与 body.project_id 不一致 ⇒ propose 403，零提议零审计。"""
    users, _ = ai_context
    admin = users["admin"]
    project = make_project(db_session, admin)
    definition = _published_definition(db_session, admin, project)
    key = f"n5-wf-{uuid4().hex[:8]}"
    with pytest.raises(ControlServiceError) as denied:
        _invoke(admin, "workflows.run_start", {"project_id": project.id, "definition_id": definition.id},
            {"idempotency_key": key}, scope=str(uuid4()))
    assert denied.value.status == 403
    assert db_session.scalars(select(OperationEvent).where(OperationEvent.target_type == "ai_api_action")).all() == []
    assert _run_count(db_session, WorkflowRun, key) == 0


def test_agents_scope_ticket_binds_body_project(ai_context, db_session, d4_settings):
    """安全评审 C 项：agents.run_start 的 project_id 在 body——票据 scope 与
    body.project_id 不一致 ⇒ propose 403 零提议零 run（AI 不得借确认通道发起
    票据授权范围之外项目的 run）。"""
    users, _ = ai_context
    admin = users["admin"]
    project = make_project(db_session, admin)
    registry = seed_agent(db_session, d4_settings)
    key = f"n5-ag-{uuid4().hex[:8]}"
    with pytest.raises(ControlServiceError) as denied:
        _invoke(admin, "agents.run_start", {"agent_id": registry.id},
            {"project_id": project.id, "idempotency_key": key}, scope=str(uuid4()))
    assert denied.value.status == 403
    assert db_session.scalars(select(OperationEvent).where(
        OperationEvent.event_type == "ai.api.requested", OperationEvent.actor_user_id == admin.id)).all() == []
    assert _run_count(db_session, AgentRun, key) == 0


def test_confirm_reauthorizes_after_account_disabled(ai_context, db_session):
    """propose 后账号停用 ⇒ confirm 重跑 _authorized 403，run 零行（授权绑定在确认时重判）。"""
    users, _ = ai_context
    admin = users["admin"]
    _set_password(db_session, admin)
    project = make_project(db_session, admin)
    definition = _published_definition(db_session, admin, project)
    key = f"n5-wf-{uuid4().hex[:8]}"
    result = _invoke(admin, "workflows.run_start", {"project_id": project.id, "definition_id": definition.id}, {"idempotency_key": key})
    admin.is_active = False
    db_session.commit()
    with pytest.raises(ControlServiceError) as denied:
        decide_action(admin, result["action_id"], _CONFIRM_PASSWORD)
    assert denied.value.status == 403
    assert _run_count(db_session, WorkflowRun, key) == 0


def test_confirm_rejects_after_auth_version_change(ai_context, db_session):
    """propose 后 auth_version 变更（改密等）⇒ confirm 409 action_expired，提议作废。"""
    users, _ = ai_context
    admin = users["admin"]
    _set_password(db_session, admin)
    project = make_project(db_session, admin)
    definition = _published_definition(db_session, admin, project)
    key = f"n5-wf-{uuid4().hex[:8]}"
    result = _invoke(admin, "workflows.run_start", {"project_id": project.id, "definition_id": definition.id}, {"idempotency_key": key})
    admin.auth_version += 1
    db_session.commit()
    with pytest.raises(ControlServiceError) as stale:
        decide_action(admin, result["action_id"], _CONFIRM_PASSWORD)
    assert stale.value.code == "action_expired"
    assert _run_count(db_session, WorkflowRun, key) == 0


# ---------------------------------------------------------------- 过期与驳回


def test_expired_proposal_never_creates_run(ai_context, db_session):
    """确认窗（15min）外 confirm ⇒ 409 action_expired；过期不是静默放行。"""
    users, _ = ai_context
    admin = users["admin"]
    _set_password(db_session, admin)
    project = make_project(db_session, admin)
    definition = _published_definition(db_session, admin, project)
    key = f"n5-wf-{uuid4().hex[:8]}"
    result = _invoke(admin, "workflows.run_start", {"project_id": project.id, "definition_id": definition.id}, {"idempotency_key": key})
    requested = next(e for e in _events(db_session, result["action_id"]) if e.event_type == "ai.api.requested")
    requested.created_at = datetime.now(UTC) - timedelta(minutes=16)
    db_session.commit()
    with pytest.raises(ControlServiceError) as expired:
        decide_action(admin, result["action_id"], _CONFIRM_PASSWORD)
    assert expired.value.code == "action_expired"
    assert _run_count(db_session, WorkflowRun, key) == 0


def test_reject_decision_never_creates_run(ai_context, db_session):
    """approve=False ⇒ cancelled 留痕，run 零行。"""
    users, _ = ai_context
    admin = users["admin"]
    _set_password(db_session, admin)
    project = make_project(db_session, admin)
    definition = _published_definition(db_session, admin, project)
    key = f"n5-wf-{uuid4().hex[:8]}"
    result = _invoke(admin, "workflows.run_start", {"project_id": project.id, "definition_id": definition.id}, {"idempotency_key": key})
    assert decide_action(admin, result["action_id"], _CONFIRM_PASSWORD, approve=False)["status"] == "cancelled"
    events = _events(db_session, result["action_id"])
    assert any(e.event_type == "ai.api.cancelled" for e in events)
    assert _run_count(db_session, WorkflowRun, key) == 0


# ---------------------------------------------------------------- 守卫源级钉


def test_guard_source_order_pins():
    """源级钉：propose 闸在 _authorized 之后（先权限后形状）；confirm 闸在
    verify_password 之后（先验人再判状态）；复活拒因字面量在场。"""
    source = (SERVER_ROOT / "src" / "fde_api" / "control" / "api_actions.py").read_text(encoding="utf-8")
    assert source.index("_authorized(user, spec, parameters, claims.get(\"project_id\"), operation=operation, body=body)") < source.index("    _require_run_start_idempotency_key(operation, body)")
    assert source.index("verify_password(current.password_hash, password)") < source.index("    _run_start_confirm_guard(session, data)")
    assert "run_cancelled_not_revivable" in source
    assert "run_start_idempotency_required" in source
    assert RUN_START_OPERATIONS == frozenset({"workflows.run_start", "agents.run_start"})
    # 安全评审 C 项 / QR-003 源钉：票据绑定闸并入 _authorized 单点，propose 与 confirm 双侧必经。
    assert source.count("_require_run_start_scope_binding(") >= 2  # def + _authorized 单点调用
    assert source.count("operation=") >= 3  # _authorized def + propose 调用 + confirm 调用
    # 源级复钉：目录行确实是确认类（CONFIRMATION_KEYS 的两个新键）。
    catalog_source = (SERVER_ROOT / "src" / "fde_api" / "control" / "api_catalog.py").read_text(encoding="utf-8")
    assert catalog_source.count('"workflows.run_start"') == 2  # ENTRIES + CONFIRMATION_KEYS
    assert catalog_source.count('"agents.run_start"') == 2
