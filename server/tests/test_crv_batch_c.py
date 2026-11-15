"""goal-crv-fix2 批 C 回归钉：QR-041 / QR-042 / QR-043 / QR-044。"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import select

from conftest import INITIAL_PASSWORD
from fde_api.auth.models import User
from fde_api.auth.passwords import hash_password
from fde_api.auth.tokens import issue_access_token
from fde_api.diagnostics import claim_service, jobs as diag_jobs, service as diag_service
from fde_api.diagnostics.models import LeadDiagnosticSession
from fde_api.guidance.redaction import redact_text_detailed
from fde_api.workbench.models import OperationEvent
from test_diagnostics_mvp import _FakeRedis

TOKEN_HEADER = "X-Diagnostic-Token"
LEADS_PREFIX = "/api/v1/diagnostics/leads"
FIRST_SCREEN_READY = {
    "org.industry": "制造与工业",
    "org.scale": "100–499人",
    "pol.qualification": ["规上工业企业"],
    "pol.declaration_history": "从未申报过",
    "pol.digitalization_project": "已有在推进的数字化改造",
}


class _ExplodingRedis:
    """模拟 Redis 故障——一旦限流先于部署闸调用即暴露。"""

    def __init__(self) -> None:
        self.called = False

    def incr(self, key: str) -> int:
        self.called = True
        raise RuntimeError("redis unavailable")

    def expire(self, key: str, ttl: int) -> None:
        self.called = True
        raise RuntimeError("redis unavailable")

    def ttl(self, key: str) -> int:
        self.called = True
        raise RuntimeError("redis unavailable")


@pytest.fixture
def diag_open_app(app):
    app.config["SETTINGS"] = app.config["SETTINGS"].model_copy(
        update={"diagnostics_enabled": True, "diagnostics_rate_fail_closed": True}
    )
    app.extensions["fde_api_redis"] = _FakeRedis()
    return app


def _make_user(db_session, settings, *, role: str = "fde_engineer") -> tuple[User, dict[str, str]]:
    user = User(
        username=f"crvc.{role}.{uuid4().hex[:8]}",
        display_name=f"CRVC-{role}",
        role=role,
        password_hash=hash_password(INITIAL_PASSWORD),
        email=f"crvc.{uuid4().hex[:8]}@example.test",
        registration_state="active",
        must_change_password=False,
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user, {"Authorization": f"Bearer {issue_access_token(user, settings)}"}


def _create_captured_lead(
    client,
    *,
    contact: str = "13800138000 / owner@example.test",
    name: str | None = "张负责人",
    region: str | None = "苏州",
) -> tuple[str, str]:
    created = client.post(
        "/api/v1/diagnostics/sessions",
        json={"source_type": "direct"},
        environ_base={"REMOTE_ADDR": "203.0.113.10"},
    )
    assert created.status_code == 200, created.get_json()
    sid = created.get_json()["data"]["id"]
    token = created.get_json()["data"]["token"]
    headers = {TOKEN_HEADER: token}

    r1 = client.post(
        "/api/v1/diagnostics/session/assessment",
        headers=headers,
        json={"answers": FIRST_SCREEN_READY},
        environ_base={"REMOTE_ADDR": "203.0.113.10"},
    )
    assert r1.status_code == 200, r1.get_json()

    r2 = client.post(
        "/api/v1/diagnostics/session/lead",
        headers=headers,
        json={
            "contact": {
                "contact": contact,
                "name": name,
                "region": region,
                "consent": True,
            }
        },
        environ_base={"REMOTE_ADDR": "203.0.113.10"},
    )
    assert r2.status_code == 200, r2.get_json()
    return sid, token


# ---------------------------------------------------------------------------
# QR-041：留资行保留联系方式明文，受控读面留痕，普通脱敏默认仍掩码
# ---------------------------------------------------------------------------


def test_qr041_lead_contact_preserves_reach_and_audits_controlled_reveal(
    diag_open_app, db_session, settings
):
    client = diag_open_app.test_client()

    # 默认脱敏维持手机号/邮箱掩码零回归
    default_masked = redact_text_detailed("请联系 13800138000 或 owner@example.test")
    assert "[手机号已脱敏]" in default_masked.text
    assert "[邮箱已脱敏]" in default_masked.text

    sid, token = _create_captured_lead(
        client,
        contact="宏远智造集团 13800138000 / owner@example.test",
        name="宏远智造集团王经理",
    )
    row = db_session.get(LeadDiagnosticSession, sid)
    assert row is not None and row.lead_contact is not None
    # 手机号与邮箱明文保留，企业名仍按词典/疑似名代号化
    assert "13800138000" in row.lead_contact["contact"]
    assert "owner@example.test" in row.lead_contact["contact"]
    assert "宏远智造集团" not in row.lead_contact["contact"]
    assert "宏远智造集团" not in (row.lead_contact["name"] or "")

    # 凭据串在留资通道仍 422 fail-closed（测试用低熵字面量）
    bad_cred = client.post(
        "/api/v1/diagnostics/session/lead",
        headers={TOKEN_HEADER: token},
        json={"contact": {"contact": "口令=aaaaaaaaaaaa1111", "consent": True}},
    )
    assert bad_cred.status_code == 422
    assert bad_cred.get_json()["error"]["code"] == "sensitive_credential_detected"

    # 受控读面：pending 认领人不可读（404），accepted 后本人与 admin 可读且写审计事件
    claimant, claimant_headers = _make_user(db_session, settings, role="fde_engineer")
    outsider, _ = _make_user(db_session, settings, role="fde_engineer")
    admin, admin_headers = _make_user(db_session, settings, role="admin")

    c_resp = client.post(
        f"{LEADS_PREFIX}/{sid}/claims",
        headers=claimant_headers,
        json={"claimant_kind": "r2_entrepreneur", "note": "申请跟进"},
        environ_base={"REMOTE_ADDR": "198.51.100.88"},
    )
    assert c_resp.status_code == 201
    claim_id = c_resp.get_json()["data"]["id"]

    with pytest.raises(claim_service.DiagnosticsServiceError) as pending_err:
        claim_service.reveal_claimed_lead_contact(actor=claimant, claim_id=claim_id)
    assert pending_err.value.status == 404

    acc = client.post(
        f"{LEADS_PREFIX}/claims/{claim_id}/accept",
        headers=admin_headers,
        json={"decision_note": "核准跟进"},
    )
    assert acc.status_code == 200

    with pytest.raises(claim_service.DiagnosticsServiceError) as out_err:
        claim_service.reveal_claimed_lead_contact(actor=outsider, claim_id=claim_id)
    assert out_err.value.status == 404

    revealed = claim_service.reveal_claimed_lead_contact(actor=claimant, claim_id=claim_id)
    assert "13800138000" in revealed["contact"]

    admin_revealed = claim_service.reveal_claimed_lead_contact(actor=admin, claim_id=claim_id)
    assert "owner@example.test" in admin_revealed["contact"]

    events = list(
        db_session.scalars(
            select(OperationEvent).where(
                OperationEvent.event_type == "diagnostic_lead_contact_revealed",
                OperationEvent.target_id == claim_id,
            )
        )
    )
    assert len(events) == 2
    for ev in events:
        assert "13800138000" not in str(ev.changes)


# ---------------------------------------------------------------------------
# QR-042：30 天留存期懒检置 expired 并清空匿名内容（claimed 保全）
# ---------------------------------------------------------------------------


def test_qr042_retention_lazy_expiry_clears_content_and_blocks_writes_and_claims(
    diag_open_app, db_session, settings, monkeypatch
):
    client = diag_open_app.test_client()
    admin, admin_headers = _make_user(db_session, settings, role="admin")
    claimant, claimant_headers = _make_user(db_session, settings, role="fde_engineer")

    # 1) 报告与分享链接已就绪的会话过期后：线索池排除、读分享 404 且内容清空、续写 409
    sid, token = _create_captured_lead(client)
    row = db_session.get(LeadDiagnosticSession, sid)
    assert row is not None
    row.report = {
        "summary": {
            "headline": "测试结论",
            "stage": "识别",
            "one_line": "测试摘要",
        },
        "problems": [{"title": "痛点一", "stage": "识别", "evidence": "纸质排产"}],
        "directions": [{"title": "方向一", "action": "标准化模板"}],
        "boundary": {"human": ["人工拍板"], "ai": ["草稿辅助"]},
        "policy": {"opportunities": []},
        "meta": {"generated_at": datetime.now(UTC).isoformat()},
    }
    row.status = "report_ready"
    db_session.commit()

    share_resp = client.post(
        "/api/v1/diagnostics/session/share",
        headers={TOKEN_HEADER: token},
    )
    assert share_resp.status_code == 200, share_resp.get_json()
    share_token = share_resp.get_json()["data"]["share_token"]

    row.expires_at = datetime.now(UTC) - timedelta(seconds=10)
    db_session.commit()

    pool = client.get(
        f"{LEADS_PREFIX}?claimant_kind=r2_entrepreneur",
        headers=claimant_headers,
    )
    assert pool.status_code == 200
    assert all(item["id"] != sid for item in pool.get_json()["data"])

    s_read = client.get(f"/api/v1/diagnostics/share/{share_token}")
    assert s_read.status_code == 404

    db_session.expire_all()
    expired_row = db_session.get(LeadDiagnosticSession, sid)
    assert expired_row is not None
    assert expired_row.status == "expired"
    assert expired_row.answers == {}
    assert expired_row.assessment is None
    assert expired_row.report is None
    assert expired_row.lead_contact is None
    assert expired_row.subject_fingerprint is None
    assert expired_row.region_name is None
    assert expired_row.share_token_sha256 is None

    w_resp = client.post(
        "/api/v1/diagnostics/session/answers",
        headers={TOKEN_HEADER: token},
        json={"answers": {"org.main_business": "五金加工"}},
    )
    assert w_resp.status_code == 409
    assert w_resp.get_json()["error"]["code"] == "session_closed"

    g_resp = client.get(
        "/api/v1/diagnostics/session",
        headers={TOKEN_HEADER: token},
    )
    assert g_resp.status_code == 200
    assert g_resp.get_json()["data"]["status"] == "expired"
    assert g_resp.get_json()["data"]["lead_captured"] is False
    assert g_resp.get_json()["data"]["answered_slots"] == []

    # 2) 已提交 pending 认领后线索满 30 天过期 ⇒ accept_claim 返 409 lead_expired 并清空内容
    sid2, _ = _create_captured_lead(client)
    c2 = client.post(
        f"{LEADS_PREFIX}/{sid2}/claims",
        headers=claimant_headers,
        json={"claimant_kind": "r2_entrepreneur"},
        environ_base={"REMOTE_ADDR": "198.51.100.89"},
    )
    assert c2.status_code == 201
    claim2_id = c2.get_json()["data"]["id"]

    lead2 = db_session.get(LeadDiagnosticSession, sid2)
    lead2.expires_at = datetime.now(UTC) - timedelta(minutes=1)
    db_session.commit()

    acc2 = client.post(
        f"{LEADS_PREFIX}/claims/{claim2_id}/accept",
        headers=admin_headers,
        json={"decision_note": "逾期裁定应拒"},
    )
    assert acc2.status_code == 409
    assert acc2.get_json()["error"]["code"] == "lead_expired"
    db_session.expire_all()
    assert db_session.get(LeadDiagnosticSession, sid2).lead_contact is None

    # 3) worker 消费已过期会话不调 AI 且清空内容
    sid3, _ = _create_captured_lead(client)
    lead3 = db_session.get(LeadDiagnosticSession, sid3)
    lead3.expires_at = datetime.now(UTC) - timedelta(minutes=1)
    db_session.commit()

    ai_called = False

    def _forbid_ai(**kwargs):
        nonlocal ai_called
        ai_called = True
        raise AssertionError("expired session must not invoke AI")

    monkeypatch.setattr(diag_jobs, "execute_ai_prompt", _forbid_ai)
    with diag_open_app.app_context():
        diag_jobs.handle_diagnostic_report(SimpleNamespace(target_id=sid3))
    assert ai_called is False
    db_session.expire_all()
    assert db_session.get(LeadDiagnosticSession, sid3).status == "expired"
    assert db_session.get(LeadDiagnosticSession, sid3).answers == {}

    # 4) 已认领（claimed）会话过 30 天仍保全
    sid4, token4 = _create_captured_lead(client)
    c4 = client.post(
        f"{LEADS_PREFIX}/{sid4}/claims",
        headers=claimant_headers,
        json={"claimant_kind": "r2_entrepreneur"},
        environ_base={"REMOTE_ADDR": "198.51.100.90"},
    )
    claim4_id = c4.get_json()["data"]["id"]
    assert (
        client.post(
            f"{LEADS_PREFIX}/claims/{claim4_id}/accept",
            headers=admin_headers,
            json={"decision_note": "正式转化"},
        ).status_code
        == 200
    )
    lead4 = db_session.get(LeadDiagnosticSession, sid4)
    lead4.expires_at = datetime.now(UTC) - timedelta(days=5)
    db_session.commit()

    g4 = client.get(
        "/api/v1/diagnostics/session",
        headers={TOKEN_HEADER: token4},
    )
    assert g4.status_code == 200
    assert g4.get_json()["data"]["status"] == "claimed"
    db_session.expire_all()
    assert db_session.get(LeadDiagnosticSession, sid4).lead_contact is not None


# ---------------------------------------------------------------------------
# QR-043：注册面关闭时即使限流超限或 Redis 故障也一律 404（不返 429）
# ---------------------------------------------------------------------------


def test_qr043_closed_registration_surface_returns_404_before_rate_limiter(app, settings):
    exploding_redis = _ExplodingRedis()
    app.extensions["fde_api_redis"] = exploding_redis
    app.config["SETTINGS"] = settings.model_copy(
        update={
            "registration_enabled": False,
            "registration_rate_fail_closed": True,
        }
    )
    client = app.test_client()

    for path in (
        "/api/v1/auth/register/enterprise",
        "/api/v1/auth/registrations/resend",
        "/api/v1/commercial/enterprise-registrations",
    ):
        resp = client.post(path, json={"username": "probe"}, environ_base={"REMOTE_ADDR": "198.51.100.77"})
        assert resp.status_code == 404, f"{path} leaked {resp.status_code} while surface closed"
        assert resp.get_json()["error"]["code"] == "not_found"

    assert exploding_redis.called is False, "部署闸关闭时不得触碰限流器计数"


# ---------------------------------------------------------------------------
# QR-044：认领单详情仅 admin 或认领申请人本人可读，越权一律 404
# ---------------------------------------------------------------------------


def test_qr044_get_claim_enforces_owner_or_admin_and_gate(diag_open_app, db_session, settings):
    client = diag_open_app.test_client()
    owner, owner_headers = _make_user(db_session, settings, role="fde_engineer")
    other, other_headers = _make_user(db_session, settings, role="project_lead")
    admin, admin_headers = _make_user(db_session, settings, role="admin")

    sid, _ = _create_captured_lead(client)
    created = client.post(
        f"{LEADS_PREFIX}/{sid}/claims",
        headers=owner_headers,
        json={"claimant_kind": "r2_entrepreneur", "note": "我的认领"},
        environ_base={"REMOTE_ADDR": "198.51.100.91"},
    )
    assert created.status_code == 201
    claim_id = created.get_json()["data"]["id"]

    # 本人与 admin 可读
    assert client.get(f"{LEADS_PREFIX}/claims/{claim_id}", headers=owner_headers).status_code == 200
    assert client.get(f"{LEADS_PREFIX}/claims/{claim_id}", headers=admin_headers).status_code == 200

    # 他人 HTTP 与服务层直调一律 404
    denied = client.get(f"{LEADS_PREFIX}/claims/{claim_id}", headers=other_headers)
    assert denied.status_code == 404
    assert denied.get_json()["error"]["code"] == "claim_not_found"

    with pytest.raises(claim_service.DiagnosticsServiceError) as svc_err:
        claim_service.get_claim(actor=other, claim_id=claim_id)
    assert svc_err.value.status == 404

    # 部署闸关闭时服务层直调也必 404
    diag_open_app.config["SETTINGS"] = diag_open_app.config["SETTINGS"].model_copy(
        update={"diagnostics_enabled": False}
    )
    with pytest.raises(diag_service.DiagnosticsServiceError) as gate_err:
        claim_service.get_claim(actor=admin, claim_id=claim_id)
    assert gate_err.value.status == 404
