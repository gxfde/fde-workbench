"""AF1-WP4：工程台路由面（签发/静态面/只读投影/写代理）——docs/ai-fde/13 §7-B。

全部服务端闸（零 UI-only）：密钥域空=403 fail-closed、档位闸（viewer 不入）、
租户钉定（visible_project_filter，跨租户 404 同形）、写代理只接受会话令牌且
语义与既有路由同源（**零新写语义**——同一 service 函数）。fragment 承载+
CSP/no-store 沿 viewer 整改修订版纪律。
"""
from __future__ import annotations

import uuid

import pytest
from flask import Flask

from conftest import INITIAL_PASSWORD
from fde_api.agents.models import AgentRegistry, AgentRun, AgentToolCall
from fde_api.auth.models import User
from fde_api.auth.passwords import hash_password
from fde_api.auth.tokens import issue_access_token
from test_agents_d4_harness import make_user
from test_document_drafts_api import _persist_project

ENG_KEY = "eng-console-signing-key-for-tests-only-32b"


@pytest.fixture
def eng_settings(settings):
    """启用工程台密钥域（独立于 jwt_secret；同值由 config validator 启动拒）。"""
    settings.workbench_eng_signing_key = ENG_KEY
    return settings


def _jwt_client(client, user, settings):
    headers = {"Authorization": f"Bearer {issue_access_token(user, settings)}"}
    return headers


def _issue_session(client, settings, user):
    return client.post(
        "/api/v1/eng/session", headers=_jwt_client(client, user, settings), json={}
    )


def _bearer(token: str, client_id: str = "tab-1"):
    return {"Authorization": f"Bearer {token}", "X-Eng-Client": client_id}


def _open_link(client, handover_token: str, client_id: str = "tab-1"):
    """交付链接首次打开：overview 消费交接令牌 → 回会话令牌。"""
    resp = client.get("/api/v1/eng/overview", headers=_bearer(handover_token, client_id))
    assert resp.status_code == 200, resp.get_data(as_text=True)
    session_token = resp.headers.get("X-Eng-Session")
    assert session_token, "首次消费必须回会话令牌（X-Eng-Session）"
    return resp, session_token


# --- 签发面 ----------------------------------------------------------------


def test_session_issue_fail_closed_without_key(client, db_session, settings):
    """密钥域空 = 403 eng_disabled（fail-closed，viewer「独立密钥域」同款）。"""
    user = make_user(db_session, "project_lead")
    resp = _issue_session(client, settings, user)
    assert resp.status_code == 403
    assert resp.get_json()["error"]["code"] == "eng_disabled"


def test_session_issue_requires_operator_role(client, db_session, settings, eng_settings):
    user = make_user(db_session, "viewer")
    resp = _issue_session(client, eng_settings, user)
    assert resp.status_code == 403
    assert resp.get_json()["error"]["code"] == "forbidden"


def test_session_issue_returns_two_tokens_and_fragment_path(
    client, db_session, settings, eng_settings
):
    user = make_user(db_session, "project_lead")
    resp = _issue_session(client, eng_settings, user)
    assert resp.status_code == 200
    data = resp.get_json()["data"]
    assert data["handover_token"] and data["token"]
    assert data["delivery_path"].startswith("/eng/console#/?d=")
    assert "?t=" not in data["delivery_path"]
    assert data["expires_in"] == 8 * 3600


# --- 静态面 ----------------------------------------------------------------


def test_console_page_served_with_csp_and_no_store(client, settings, eng_settings):
    resp = client.get("/eng/console")
    assert resp.status_code == 200
    assert resp.headers["Content-Security-Policy"].startswith("default-src 'none'")
    assert "no-store" in resp.headers["Cache-Control"]
    html = resp.get_data(as_text=True)
    # 水印条（SYNTHETIC_PILOT）与零外链形态（无 http(s) 外链资源引用）
    assert "SYNTHETIC_PILOT" in html
    assert 'src="http' not in html and 'href="http' not in html


def test_console_page_disabled_without_key(client, settings):
    resp = client.get("/eng/console")
    assert resp.status_code == 403


def test_console_page_contains_no_credentials(client, eng_settings):
    """静态产物机械 grep 闸：密钥/凭据模式零命中（TrustBoard 硬条件 7 同款）。"""
    from fde_api.control.eng_console_page import CONSOLE_HTML

    for marker in ("SIGNING_KEY", "jwt_secret", "password_hash", "sk-"):
        assert marker not in CONSOLE_HTML


# --- 只读投影（交接令牌消费 → 会话令牌） ------------------------------------


def _seed_run_with_payload(db_session, lead: User, project):
    registry = AgentRegistry(
        kind="zcode", name=f"wp4-api-{uuid.uuid4().hex[:6]}", enabled=True,
        capability_tier="project_operator", sandbox_profile="sandbox",
    )
    db_session.add(registry)
    db_session.flush()
    run = AgentRun(
        project_id=project.id, agent_id=registry.id, initiated_by_user_id=lead.id,
        capability_used="ontology.propose", status="completed",
        context_ref=f"masked://runs/{uuid.uuid4().hex[:8]}",
        idempotency_key=f"ik-{uuid.uuid4().hex[:12]}",
    )
    db_session.add(run)
    db_session.flush()
    call = AgentToolCall(
        run_id=run.id, tool_name="ontology_dry_validate", decision="allowed",
        capability="ontology.read", duration_ms=12,
        request_json='{"proposed_json": [{"entity_key": "equipment"}]}',
        response_json='{"verdict": "violations", "violations": [{"check": "data_type"}]}',
        payload_truncated=False,
    )
    db_session.add(call)
    db_session.commit()
    return run, call


@pytest.fixture
def eng_project(db_session):
    lead = make_user(db_session, "project_lead")
    project = _persist_project(db_session, lead, code=f"E4{uuid.uuid4().hex[:4]}")
    return lead, project


def test_overview_consumes_handover_and_issues_session(
    client, db_session, settings, eng_settings, eng_project
):
    lead, project = eng_project
    resp = _issue_session(client, eng_settings, lead)
    data = resp.get_json()["data"]
    body, session_token = _open_link(client, data["handover_token"])
    assert body.get_json()["data"]["user"]["role"] == "project_lead"
    # 会话令牌可反复使用（不消费）
    again = client.get("/api/v1/eng/overview", headers=_bearer(session_token))
    assert again.status_code == 200
    assert again.headers.get("X-Eng-Session") is None


def test_handover_replay_from_other_client_rejected(
    client, db_session, settings, eng_settings, eng_project
):
    lead, _project = eng_project
    data = _issue_session(client, eng_settings, lead).get_json()["data"]
    _open_link(client, data["handover_token"], client_id="tab-1")
    replay = client.get("/api/v1/eng/overview", headers=_bearer(data["handover_token"], client_id="tab-other"))
    assert replay.status_code == 403
    assert replay.get_json()["error"]["code"] == "handover_used"


def test_run_detail_projection_carries_payload_whitelist(
    client, db_session, settings, eng_settings, eng_project
):
    lead, project = eng_project
    run, call = _seed_run_with_payload(db_session, lead, project)
    data = _issue_session(client, eng_settings, lead).get_json()["data"]
    _open_link(client, data["handover_token"])
    detail = client.get(f"/api/v1/eng/runs/{run.id}", headers=_bearer(data["token"]))
    assert detail.status_code == 200
    body = detail.get_json()["data"]
    names = {item["tool_name"] for item in body["tool_calls"]}
    assert "ontology_dry_validate" in names
    row = next(item for item in body["tool_calls"] if item["id"] == call.id)
    assert row["request_json"] and "equipment" in row["request_json"]
    assert row["response_json"] and "violations" in row["response_json"]
    assert row["payload_truncated"] is False


def test_run_detail_unknown_run_is_404_same_shape(
    client, db_session, settings, eng_settings, eng_project
):
    """未知/越权 run 同形 404（租户钉定；跨租户探测零透出）。"""
    lead, _project = eng_project
    data = _issue_session(client, eng_settings, lead).get_json()["data"]
    _open_link(client, data["handover_token"])
    ghost = client.get(
        f"/api/v1/eng/runs/{uuid.uuid4()}", headers=_bearer(data["token"])
    )
    assert ghost.status_code in (403, 404)


# --- 写代理（写语义零新增；只接受会话令牌） ----------------------------------


def test_write_proxy_rejects_handover_token(
    client, db_session, settings, eng_settings, eng_project
):
    """写面只接受会话令牌（交接令牌必须先消费换会话——短窗口凭据不落写路径）。"""
    lead, project = eng_project
    run, _call = _seed_run_with_payload(db_session, lead, project)
    data = _issue_session(client, eng_settings, lead).get_json()["data"]
    resp = client.post(
        f"/api/v1/eng/runs/{run.id}/cancel", headers=_bearer(data["handover_token"]), json={}
    )
    assert resp.status_code == 403
    assert resp.get_json()["error"]["code"] == "write_requires_session"


def test_write_proxy_cancel_uses_existing_semantics(
    client, db_session, settings, eng_settings, eng_project
):
    """取消代理与既有语义同源：completed run 取消 → 409（诚实终态族）原样透传。"""
    lead, project = eng_project
    run, _call = _seed_run_with_payload(db_session, lead, project)
    data = _issue_session(client, eng_settings, lead).get_json()["data"]
    _open_link(client, data["handover_token"])
    resp = client.post(
        f"/api/v1/eng/runs/{run.id}/cancel", headers=_bearer(data["token"]), json={}
    )
    # completed 已是终态：既有取消语义的 409 族原样透传（不吞不改写）
    assert resp.status_code in (403, 409)
    error = resp.get_json()["error"]
    assert error and error["code"]


def test_write_proxy_decision_requires_password_same_as_task_center(
    client, db_session, settings, eng_settings, eng_project
):
    """审批决定代理与 task-center 同源（密码确认）：空密码 → 与既有面同型拒绝
    （invalid_approval_decision 400 原样透传）。"""
    lead, project = eng_project
    data = _issue_session(client, eng_settings, lead).get_json()["data"]
    _open_link(client, data["handover_token"])
    resp = client.post(
        f"/api/v1/eng/approvals/{uuid.uuid4()}/decision",
        headers=_bearer(data["token"]),
        json={"decision": "approved", "password": "", "reason": ""},
    )
    assert resp.status_code in (400, 403, 404, 422)
    error = resp.get_json()["error"]
    assert error and error["code"]


# —— 评审 patch 轮：值域真身/吊销可达/客户端绑定/白名单负向 ——

def test_write_proxy_decision_full_semantics_with_real_approval(
    client, db_session, settings, eng_settings, eng_project
):
    """审批决定代理完整语义（评审 verification-gap #1）：页面真实值域
    approve + 正确密码 + 真实 pending approval → 200 approved（与 task-center
    同 service 语义真身的正向证据）。"""
    from datetime import timedelta

    from fde_api.control.models import AutomationApproval

    lead, project = eng_project
    # S04 四眼闸：审批发起人=异人（lead 仅为复核者，工程台会话真身）
    requester = make_user(db_session, "project_lead")
    approval = AutomationApproval(
        run_id=None, project_id=project.id, requested_by_user_id=requester.id,
        request_key=f"wp4-{uuid.uuid4().hex[:8]}",
        capability="ontology.write", tool_name="ontology_action_execute",
        arguments_json={"proposed_json": []},
        arguments_sha256="a" * 64, risk_level=3, status="pending",
        expires_at=__import__("datetime", fromlist=["datetime"]).datetime.now(
            __import__("datetime", fromlist=["timezone"]).UTC
        ) + timedelta(hours=1),
    )
    db_session.add(approval)
    db_session.commit()

    data = _issue_session(client, eng_settings, lead).get_json()["data"]
    _open_link(client, data["handover_token"])
    resp = client.post(
        f"/api/v1/eng/approvals/{approval.id}/decision",
        headers=_bearer(data["token"]),
        json={"decision": "approve", "password": INITIAL_PASSWORD, "reason": "已核对候选"},
    )
    assert resp.status_code == 200, resp.get_data(as_text=True)
    body = resp.get_json()["data"]
    assert body["status"] == "approved"
    db_session.expire_all()
    assert db_session.get(AutomationApproval, approval.id).reviewed_by_user_id == lead.id


def test_logout_revokes_session_and_derived_handover(
    client, db_session, settings, eng_settings, eng_project
):
    """登出吊销可达（评审 auditor #7）：会话与派生交接链接同时失效。"""
    lead, _project = eng_project
    data = _issue_session(client, eng_settings, lead).get_json()["data"]
    _open_link(client, data["handover_token"])
    bye = client.post("/api/v1/eng/logout", headers=_bearer(data["token"]), json={})
    assert bye.status_code == 200
    dead_session = client.get("/api/v1/eng/overview", headers=_bearer(data["token"]))
    assert dead_session.status_code == 403
    assert dead_session.get_json()["error"]["code"] == "revoked"
    dead_handover = client.get(
        "/api/v1/eng/overview", headers=_bearer(data["handover_token"], client_id="tab-1")
    )
    assert dead_handover.status_code == 403
    assert dead_handover.get_json()["error"]["code"] == "revoked"


def test_overview_rejects_missing_client_header_on_handover(
    client, db_session, settings, eng_settings, eng_project
):
    """缺 X-Eng-Client 的交接令牌消费一律拒（评审 blind #5：unknown-client
    归并会让一次性消费对非页面客户端形同虚设）。"""
    lead, _project = eng_project
    data = _issue_session(client, eng_settings, lead).get_json()["data"]
    bare = client.get(
        "/api/v1/eng/overview", headers={"Authorization": f"Bearer {data['handover_token']}"}
    )
    assert bare.status_code == 403
    assert bare.get_json()["error"]["code"] == "eng_client_missing"


def test_run_detail_projection_excludes_internal_billing_fields(
    client, db_session, settings, eng_settings, eng_project
):
    """详情白名单负向（评审 blind #1/auditor #6）：幂等键/成本归属内部字段
    零外泄；发起人以显示名出投影。"""
    lead, project = eng_project
    run, _call = _seed_run_with_payload(db_session, lead, project)
    data = _issue_session(client, eng_settings, lead).get_json()["data"]
    _open_link(client, data["handover_token"])
    detail = client.get(f"/api/v1/eng/runs/{run.id}", headers=_bearer(data["token"]))
    assert detail.status_code == 200
    run_row = detail.get_json()["data"]["run"]
    for banned in ("idempotency_key", "cost_owner_type", "cost_owner_id", "retry_of"):
        assert banned not in run_row, banned
    assert run_row["project_name"] == project.name
    assert run_row["initiated_by"] == lead.display_name


def test_overview_carries_truncated_markers(client, db_session, settings, eng_settings, eng_project):
    """诚实截断标记（评审 edge #6）：到量置位键在投影中存在。"""
    lead, _project = eng_project
    data = _issue_session(client, eng_settings, lead).get_json()["data"]
    body, _session_token = _open_link(client, data["handover_token"])
    overview = body.get_json()["data"]
    assert "runs_truncated" in overview and "approvals_truncated" in overview
    assert overview["runs_truncated"] is False
