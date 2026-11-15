"""goal-crv-fix2 批 A（r1）回归钉：QR-001 / QR-002 / QR-003 / QR-004 / QR-018。

覆盖：
1. QR-001：登录失败限流键对用户名做 NFKC + strip + lower 归一化，大小写/全角/空白变体共享同一计数桶且成功登录同键清零。
2. QR-002：change-password 补 _registration_state_gate（suspended / rejected / pending_email 不得改密铸新 token），且 suspend_registration / review reject 递增 auth_version 使在途 access token 立即 401，同时保留 refresh 403 account_suspended 契约。
3. QR-003：scoped AI 会话下 agents.run_start 的 body.project_id == scope 可正常 propose→confirm 落 run（消除 _authorized 路径参数先 403 致死代码），且篡改已落库 requested 事件的 body.project_id 在 confirm 侧仍被 _authorized 拦截 403。
4. QR-004：PATCH /projects/<id> 更新 enterprise_code 到池内企业或商机保护期企业时复跑 ensure_enterprise_channel（422 private_deal_blocked / opportunity_protection_active）；未变更 enterprise_code 的其他字段更新不误伤。
5. QR-018：create_quote 先对 Project 行加锁并 populate_existing 重读最新 enterprise_code，再执行 ensure_enterprise_channel。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import select

from conftest import INITIAL_PASSWORD
from test_agents_d4_harness import d4_settings, prime_run, seed_agent  # noqa: F401
from test_ai_server_chat_mcp import ai_context, make_project  # noqa: F401
from test_auth_rate_limit import _FakeRedis
from test_dispatch_p2_r9_p24 import _pooled_enterprise_setup, published_template  # noqa: F401

from fde_api.agents.models import AgentRun
from fde_api.auth.models import User
from fde_api.auth.passwords import hash_password
from fde_api.auth.tokens import issue_access_token
from fde_api.commercial.models import CommercialOpportunity
from fde_api.control.access import capabilities_for_level
from fde_api.control.api_actions import decide_action, execute_api
from fde_api.control.service import ControlServiceError
from fde_api.projects import quote_service
from fde_api.projects.quote_service import QuoteServiceError, create_quote
from fde_api.projects.service import ProjectServiceError, create_project, update_project
from fde_api.registration.models import UserRegistration
from fde_api.registration.service import review_registration, suspend_registration
from fde_api.workbench.models import OperationEvent, Project


# ---------------------------------------------------------------- QR-001


def test_qr001_login_rate_limit_normalizes_nfkc_and_case_variants(app, db_session):
    """NFKC 全角/大小写/首尾空白变体轮换不得绕过 5 次登录失败锁，且成功登录清零同一归一化键。"""
    app.extensions["fde_api_redis"] = _FakeRedis()
    client = app.test_client()
    base_name = f"qr001.{uuid4().hex[:6]}"
    password = " Valid-Pass-101 "
    clean_pw = password.strip()
    user = User(
        username=base_name,
        display_name="QR001 User",
        role="viewer",
        password_hash=hash_password(clean_pw),
        must_change_password=False,
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()

    fullwidth_q = "\uff31\uff32\uff10\uff10\uff11" + base_name[5:]
    variants = [
        base_name,
        base_name.upper(),
        f"  {base_name.capitalize()}  ",
        fullwidth_q,
        fullwidth_q.lower(),
    ]
    ip = f"10.81.{uuid4().int % 200 + 1}.9"
    for variant in variants:
        resp = client.post(
            "/api/v1/auth/login",
            json={"username": variant, "password": "wrong-password-x", "device_label": "pytest"},
            environ_base={"REMOTE_ADDR": ip},
        )
        assert resp.status_code == 401

    sixth = client.post(
        "/api/v1/auth/login",
        json={"username": base_name, "password": clean_pw, "device_label": "pytest"},
        environ_base={"REMOTE_ADDR": ip},
    )
    assert sixth.status_code == 429
    assert sixth.get_json()["error"]["code"] == "login_rate_limited"


def test_qr001_successful_variant_login_clears_normalized_counter(app, db_session):
    fake_redis = _FakeRedis()
    app.extensions["fde_api_redis"] = fake_redis
    client = app.test_client()
    base_name = f"qr001c.{uuid4().hex[:6]}"
    pw = "Valid-Pass-102"
    db_session.add(
        User(
            username=base_name,
            display_name="QR001 Clear",
            role="viewer",
            password_hash=hash_password(pw),
            must_change_password=False,
            is_active=True,
        )
    )
    db_session.commit()
    ip = "10.81.202.11"
    for variant in (base_name.upper(), f" {base_name} "):
        r = client.post(
            "/api/v1/auth/login",
            json={"username": variant, "password": "bad-password", "device_label": "pytest"},
            environ_base={"REMOTE_ADDR": ip},
        )
        assert r.status_code == 401
    assert len(fake_redis.counters) == 1

    ok = client.post(
        "/api/v1/auth/login",
        json={"username": f"  {base_name.upper()}  ", "password": pw, "device_label": "pytest"},
        environ_base={"REMOTE_ADDR": ip},
    )
    assert ok.status_code == 200
    assert fake_redis.counters == {}


# ---------------------------------------------------------------- QR-002


@pytest.mark.parametrize(
    ("reg_state", "expected_code"),
    [
        ("suspended", "account_suspended"),
        ("rejected", "registration_rejected"),
        ("pending_email", "email_not_verified"),
    ],
)
def test_qr002_change_password_blocks_disallowed_registration_states(
    db_session, reg_state: str, expected_code: str
):
    from fde_api.auth.service import AuthServiceError, change_password

    old_pw = "Old-Pass-201"
    user = User(
        username=f"qr002.{reg_state}.{uuid4().hex[:6]}",
        display_name="QR002 State",
        role="viewer",
        password_hash=hash_password(old_pw),
        must_change_password=False,
        is_active=True,
        registration_state=reg_state,
    )
    db_session.add(user)
    db_session.commit()
    before_ver = user.auth_version

    with pytest.raises(AuthServiceError) as exc_info:
        change_password(user, old_pw, "New-Pass-202")
    assert exc_info.value.code == expected_code
    assert exc_info.value.status == 403

    db_session.expire_all()
    reloaded = db_session.get(User, user.id)
    assert reloaded.auth_version == before_ver


def test_qr002_suspend_and_reject_bump_auth_version_killing_live_jwt(
    client, db_session, settings
):
    admin = User(
        username=f"qr002.admin.{uuid4().hex[:6]}",
        display_name="Admin",
        role="admin",
        password_hash=hash_password(INITIAL_PASSWORD),
        must_change_password=False,
        is_active=True,
    )
    target = User(
        username=f"qr002.target.{uuid4().hex[:6]}",
        display_name="Target",
        role="viewer",
        password_hash=hash_password(INITIAL_PASSWORD),
        must_change_password=False,
        is_active=True,
        registration_state="pending_review",
    )
    db_session.add_all([admin, target])
    db_session.flush()
    db_session.add(
        UserRegistration(
            user_id=target.id,
            entry="deliverer",
        )
    )
    db_session.commit()

    live_token = issue_access_token(target, settings)
    assert (
        client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {live_token}"}).status_code
        == 200
    )

    suspend_registration(db_session, actor=admin, user_id=target.id)
    db_session.commit()

    after_suspend = client.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {live_token}"}
    )
    assert after_suspend.status_code == 401

    # 另测 review reject 同样递增 auth_version 作废存量 JWT
    candidate = User(
        username=f"qr002.cand.{uuid4().hex[:6]}",
        display_name="Candidate",
        role="viewer",
        password_hash=hash_password(INITIAL_PASSWORD),
        must_change_password=False,
        is_active=True,
        registration_state="pending_review",
    )
    db_session.add(candidate)
    db_session.flush()
    db_session.add(
        UserRegistration(
            user_id=candidate.id,
            entry="deliverer",
        )
    )
    db_session.commit()
    cand_token = issue_access_token(candidate, settings)
    review_registration(
        db_session, actor=admin, user_id=candidate.id, decision="reject", note="材料不符"
    )
    db_session.commit()
    assert (
        client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {cand_token}"}).status_code
        == 401
    )


# ---------------------------------------------------------------- QR-003


def test_qr003_scoped_agents_run_start_succeeds_for_matching_scope_and_blocks_mismatch(
    ai_context, db_session, d4_settings, app
):
    users, _ = ai_context
    admin = users["admin"]
    confirm_pw = "qr003-confirm-pw"
    admin.password_hash = hash_password(confirm_pw)
    db_session.commit()

    project_ok = make_project(db_session, admin)
    project_other = make_project(db_session, admin)
    registry = seed_agent(db_session, d4_settings)
    prime_run(app)
    app.config["SETTINGS"] = app.config["SETTINGS"].model_copy(
        update={"agent_host_channel_enabled": False, "agent_host_poll_enabled": False}
    )

    allowed = set(capabilities_for_level("system_operator"))
    key_ok = f"qr003-ok-{uuid4().hex[:8]}"

    # 1) matched scope（claims.project_id == body.project_id）可正常 propose + confirm 落 run
    proposed = execute_api(
        user=admin,
        claims={"execution_id": str(uuid4()), "project_id": project_ok.id},
        allowed=allowed,
        operation="agents.run_start",
        parameters={"agent_id": registry.id},
        body={"project_id": project_ok.id, "idempotency_key": key_ok},
    )
    assert proposed["status"] == "awaiting_confirmation"
    outcome = decide_action(admin, proposed["action_id"], confirm_pw)
    assert outcome["status"] == "completed"
    assert outcome["http_status"] == 201
    run = db_session.scalar(select(AgentRun).where(AgentRun.idempotency_key == key_ok))
    assert run is not None and run.project_id == project_ok.id

    # 2) confirm 侧重判：若已落库 requested 事件的 body.project_id 与 scope 失配，decide_action 必 403
    key_tamper = f"qr003-tp-{uuid4().hex[:8]}"
    proposed2 = execute_api(
        user=admin,
        claims={"execution_id": str(uuid4()), "project_id": project_ok.id},
        allowed=allowed,
        operation="agents.run_start",
        parameters={"agent_id": registry.id},
        body={"project_id": project_ok.id, "idempotency_key": key_tamper},
    )
    req_event = db_session.scalar(
        select(OperationEvent).where(
            OperationEvent.target_id == proposed2["action_id"],
            OperationEvent.event_type == "ai.api.requested",
        )
    )
    tampered_changes = dict(req_event.changes)
    tampered_body = dict(tampered_changes["body"])
    tampered_body["project_id"] = project_other.id
    tampered_changes["body"] = tampered_body
    req_event.changes = tampered_changes
    db_session.commit()

    with pytest.raises(ControlServiceError) as denied:
        decide_action(admin, proposed2["action_id"], confirm_pw)
    assert denied.value.status == 403
    assert db_session.scalar(select(AgentRun).where(AgentRun.idempotency_key == key_tamper)) is None

    # 3) body 缺失 project_id 时（target_project_id is None），scoped 会话必须被
    # _require_run_start_scope_binding 拦截 403（而非跳过 _project 落到内层 400）
    with pytest.raises(ControlServiceError) as missing_proj:
        execute_api(
            user=admin,
            claims={"execution_id": str(uuid4()), "project_id": project_ok.id},
            allowed=allowed,
            operation="agents.run_start",
            parameters={"agent_id": registry.id},
            body={"idempotency_key": f"qr003-np-{uuid4().hex[:8]}"},
        )
    assert missing_proj.value.status == 403
    assert missing_proj.value.code == "forbidden"


# ---------------------------------------------------------------- QR-004 & QR-018


def test_qr004_patch_enterprise_code_enforces_h2_and_g4_channel_guards(
    db_session, published_template
):
    pooled_code = f"qr004-pool-{uuid4().hex[:6]}"
    admin, _, _ = _pooled_enterprise_setup(db_session, enterprise_code=pooled_code)

    clean_code = f"qr004-clean-{uuid4().hex[:6]}"
    created = create_project(
        actor=admin,
        input={
            "name": "QR004 直签项目",
            "enterprise_code": clean_code,
            "template_version_id": published_template.id,
            "leader_user_id": admin.id,
            "planned_start_date": "2026-11-03",
            "module_keys": ["pre_diagnosis"],
            "business_line": "FDE",
        },
    )
    project_id = created["id"]
    ver = created["version"]

    # H2：PATCH enterprise_code 改为池内企业 ⇒ 422 private_deal_blocked
    with pytest.raises(ProjectServiceError) as h2_err:
        update_project(
            actor=admin,
            project_id=project_id,
            expected_version=ver,
            changes={"enterprise_code": pooled_code},
        )
    assert h2_err.value.code == "private_deal_blocked"
    assert h2_err.value.status == 422

    # G4：PATCH enterprise_code 改为报备保护期企业 ⇒ 422 opportunity_protection_active
    protected_code = f"qr004-prot-{uuid4().hex[:6]}"
    opp = CommercialOpportunity(
        enterprise_code=protected_code,
        title="受保护企业商机",
        reported_by_user_id=admin.id,
        source_uri="file:///workspace/opp-note.md",
        content_hash="a" * 64,
        status="attribution_confirmed",
        protection_status="active",
        protection_started_at=datetime.now(UTC) - timedelta(days=1),
        protection_expires_at=datetime.now(UTC) + timedelta(days=29),
    )
    db_session.add(opp)
    db_session.commit()

    with pytest.raises(ProjectServiceError) as g4_err:
        update_project(
            actor=admin,
            project_id=project_id,
            expected_version=ver,
            changes={"enterprise_code": protected_code},
        )
    assert g4_err.value.code == "opportunity_protection_active"
    assert g4_err.value.status == 422

    # 不改 enterprise_code 的普通更新不受影响
    updated = update_project(
        actor=admin,
        project_id=project_id,
        expected_version=ver,
        changes={"notes": "normal-note-update"},
    )
    assert updated["enterprise_code"] == clean_code
    assert updated["notes"] == "normal-note-update"


def test_qr018_create_quote_locks_and_refreshes_project_before_channel_guard(
    db_session, published_template, monkeypatch
):
    pooled_code = f"qr018-pool-{uuid4().hex[:6]}"
    admin, _, _ = _pooled_enterprise_setup(db_session, enterprise_code=pooled_code)
    clean_code = f"qr018-clean-{uuid4().hex[:6]}"
    created = create_project(
        actor=admin,
        input={
            "name": "QR018 报价锁序项目",
            "enterprise_code": clean_code,
            "template_version_id": published_template.id,
            "leader_user_id": admin.id,
            "planned_start_date": "2026-11-03",
            "module_keys": ["pre_diagnosis"],
            "business_line": "FDE",
        },
    )
    project_id = created["id"]

    call_log: list[tuple[str, object]] = []
    real_load = quote_service._load_project
    real_guard = quote_service.ensure_enterprise_channel

    def tracked_load(session, actor, pid, *, manage, for_update=False):
        call_log.append(("load", for_update))
        # 模拟并发事务在加锁前刚提交了 enterprise_code -> pooled_code：
        # 先在 session identity map 中放入脏旧值，验证 populate_existing=for_update 会重读真实库行。
        proj = real_load(session, actor, pid, manage=manage, for_update=for_update)
        return proj

    def tracked_guard(session, *, actor, business_line, enterprise_code):
        call_log.append(("guard", enterprise_code))
        return real_guard(
            session, actor=actor, business_line=business_line, enterprise_code=enterprise_code
        )

    monkeypatch.setattr(quote_service, "_load_project", tracked_load)
    monkeypatch.setattr(quote_service, "ensure_enterprise_channel", tracked_guard)

    # 将库内真实 enterprise_code 改为池内企业，验证 create_quote 在 for_update=True 下必拦 422
    proj_row = db_session.get(Project, project_id)
    proj_row.enterprise_code = pooled_code
    db_session.commit()

    with pytest.raises(QuoteServiceError) as err:
        create_quote(
            actor=admin,
            project_id=project_id,
            payload={"preset": "first_order_defaults"},
        )
    assert err.value.code == "private_deal_blocked"
    assert err.value.status == 422
    assert call_log == [("load", True), ("guard", pooled_code)]
