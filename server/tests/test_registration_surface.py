"""多客户工作平台 M2：四入口统一注册与认证（任务书 §7-M2；ADR-M2 §2/ADR-M4）。

验收钉（任务书 M2 + ADR-M4 §5 判定基线）：
1. **部署闸 fail-closed**（OWNER 拍板 2026-11-11 过渡形态）：默认关闭 ⇒ 公开面
   一律 404（不确认面存在）；开闸前提＝部署开关 AND SES AND 公网根地址——
   不允许「无邮箱验证的静默放行」。
2. **四入口注册**：入口闭集（区域服务商排最后）；初始角色矩阵（enterprise →
   project_lead / 其余 viewer）；建号即建 org（同主体幂等，第二经办人复用）；
   交付者/区域审核制（pending_email → pending_review → active/rejected）。
3. **邮箱验证**：一次性令牌（sha256 指纹入库、明文只在邮件里）；重发即轮换
   （旧链接失效）；同 IP 统一限流（auth:register:{ip}，配置位保守占位）。
4. **登录闸**：pending_email/suspended/rejected 拦截（4xx 且留痕）；
   pending_review 可登录（viewer 最小面）；刷新面同闸。
5. **越权注册场景全部 4xx 且留痕**：重复邮箱/用户名、无效 USCC、无效令牌、
   审核态越权（pending_review 无 fde_engineer 不可接单＝结构性兜底）。
6. **G6 收拢委托**：legacy URL 同一语义（同闸同状态机同角色矩阵）。
7. 可辨变异：部署闸摘除/登录状态闸摘除/令牌复用/角色矩阵翻转/org 复用摘除
   ——逐一摘除必转红（本地变异验证留痕，不入库）。
"""

from __future__ import annotations

import hashlib
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from redis.exceptions import RedisError
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from conftest import INITIAL_PASSWORD, _FakeRedis
from fde_api.auth.models import User
from fde_api.auth.passwords import hash_password
from fde_api.auth.tokens import issue_access_token
from fde_api.commercial.models import (
    CommercialEntitlement,
    EnterpriseFreeQuota,
    EnterpriseQuotaSubject,
)
from fde_api.orgs.models import Org
from fde_api.registration.models import UserRegistration
from fde_api.registration.service import review_entries
from fde_api.workbench.models import OperationEvent
from test_migrations import scalar, seed_user_and_template, table_names  # noqa: F401

SERVER_ROOT = Path(__file__).resolve().parents[1]

PASSWORD = "Registrant!Pass2026"
VALID_USCC = "91350100M000100Y43"  # 公开样本（mod-31 校验通过，同 G2/G6）
REG_URL = "/api/v1/auth/register/{entry}"
VERIFY_URL = "/api/v1/auth/registrations/verify"
RESEND_URL = "/api/v1/auth/registrations/resend"
ENTRIES_URL = "/api/v1/auth/registrations/entries"
ADMIN_LIST_URL = "/api/v1/auth/registrations"
LEGACY_REG_URL = "/api/v1/commercial/enterprise-registrations"


# ---------------------------------------------------------------------------
# 夹具：开注册面（部署闸 + SES + 公网根地址）＋ 假 SES ＋ 可工作假 Redis
# ---------------------------------------------------------------------------


class _FakeSes:
    """内存假 SES 客户端：捕获发送调用（令牌明文只在此处可观测）。"""

    def __init__(self) -> None:
        self.calls: list[dict[str, str]] = []

    def send_text(self, *, sender: str, recipient: str, subject: str, body: str) -> str:
        self.calls.append(
            {"sender": sender, "recipient": recipient, "subject": subject, "body": body}
        )
        return f"ses-msg-{len(self.calls)}"


class _BrokenRedis:
    def incr(self, key: str) -> int:
        raise RedisError("connection refused")

    def expire(self, key: str, seconds: int) -> bool:
        raise RedisError("connection refused")

    def ttl(self, key: str) -> int:
        raise RedisError("connection refused")


@pytest.fixture
def reg_app(app, monkeypatch):
    """注册面开（OWNER 拍板的过渡形态之外）＋假 SES＋假 Redis（限流可测）。"""
    fake = _FakeSes()
    monkeypatch.setattr(
        "fde_api.mailing.service.create_ses_client", lambda settings: fake
    )
    app.config["SETTINGS"] = app.config["SETTINGS"].model_copy(
        update={
            "registration_enabled": True,
            "ses_enabled": True,
            "public_base_url": "https://fde.example.com",
            "ses_send_subdomain": "mail.somwyn.com",
            "ses_from_address": "no-reply@mail.somwyn.com",
        }
    )
    app.extensions["fde_api_redis"] = _FakeRedis()
    app.extensions["registration_fake_ses"] = fake
    return app


@pytest.fixture
def reg_client(reg_app):
    return reg_app.test_client()


@pytest.fixture
def reg_settings(reg_app):
    return reg_app.config["SETTINGS"]


@pytest.fixture
def admin_api(client, db_session, settings):
    """admin API 客户端（审核簿记面走普通 client——admin 面不过部署闸）。"""
    user = User(
        username=f"admin.{uuid4().hex[:10]}",
        display_name="admin",
        role="admin",
        password_hash=hash_password(INITIAL_PASSWORD),
        must_change_password=False,
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()
    headers = {"Authorization": f"Bearer {issue_access_token(user, settings)}"}

    class _AdminApi:
        def get(self, path, **kwargs):
            return client.get(path, headers=headers, **kwargs)

        def post(self, path, **kwargs):
            return client.post(path, headers=headers, **kwargs)

        @property
        def id(self) -> str:
            return user.id

    return _AdminApi()


def _email() -> str:
    return f"{uuid4().hex[:12]}@example.com"


def _register(
    reg_client,
    entry: str = "founder",
    *,
    username: str | None = None,
    email: str | None = None,
    password: str = PASSWORD,
    display_name: str = "注册人甲",
    subject_key: str | None = None,
    problem_description: str | None = "描述业务问题：订单履约周期过长。",
    intake: object = None,
) -> dict:
    payload: dict = {
        "username": username or f"reg.{uuid4().hex[:10]}",
        "display_name": display_name,
        "password": password,
        "email": email or _email(),
    }
    if entry == "enterprise":
        payload["subject_key"] = subject_key or VALID_USCC
        payload["problem_description"] = problem_description
    if intake is not None:
        payload["intake"] = intake
    response = reg_client.post(REG_URL.format(entry=entry), json=payload)
    assert response.status_code in (200, 201, 400, 409, 429), response.get_json()
    return response


def _verify_token(reg_client, raw_token: str) -> dict:
    return reg_client.post(VERIFY_URL, json={"token": raw_token})


def _latest_token(reg_app) -> str:
    """从假 SES 捕获的邮件正文提取最新令牌（令牌明文只出现在邮件里）。"""
    fake = reg_app.extensions["registration_fake_ses"]
    assert fake.calls, "没有捕获到任何 SES 发送"
    body = fake.calls[-1]["body"]
    match = re.search(r"^([A-Za-z0-9_\-]{40,})$", body, flags=re.MULTILINE)
    assert match is not None, body
    return match.group(1)


def _get_user(db_session: Session, user_id: str) -> User:
    user = db_session.get(User, user_id)
    assert user is not None
    db_session.refresh(user)
    return user


def _registration_by_user(db_session: Session, user_id: str) -> UserRegistration:
    registration = db_session.scalar(
        select(UserRegistration).where(UserRegistration.user_id == user_id)
    )
    assert registration is not None
    return registration


def _backdate_token_request(db_session: Session, seconds: int = 61) -> None:
    """把最近一次注册的 token_requested_at 回拨——注册后立即重发会被最小间隔
    节流（这是设计行为），重发语义用例须从「间隔已过」的起点测。"""
    registration = db_session.scalars(
        select(UserRegistration).order_by(UserRegistration.created_at.desc()).limit(1)
    ).first()
    assert registration is not None
    registration.token_requested_at = (
        registration.token_requested_at or datetime.now(UTC).replace(microsecond=0)
    ) - timedelta(seconds=seconds)
    db_session.commit()


def _login(client, username: str, password: str = PASSWORD):
    return client.post(
        "/api/v1/auth/login",
        json={"username": username, "password": password, "device_label": "test"},
    )


# ---------------------------------------------------------------------------
# 1. 出厂默认与部署闸（fail-closed）
# ---------------------------------------------------------------------------


def test_shipped_defaults_are_safe(test_settings):
    """**出厂默认**必须是安全值（诊断线同款「测默认值」钉）：注册面关闭、
    审核制缺省＝拍板值、限流上限为保守占位（试点前须填实数）。"""
    assert test_settings.registration_enabled is False
    assert test_settings.registration_review_entries == "deliverer,partner"
    assert test_settings.registration_ip_daily_limit == 20  # 保守占位，试点前填实数
    assert test_settings.registration_token_hours == 72
    assert test_settings.registration_resend_min_seconds == 60


def test_surface_closed_by_default_returns_404(client):
    """默认关闭 ⇒ 公开面不存在（404，不是 403）。"""
    for path, method in (
        (REG_URL.format(entry="founder"), "post"),
        (REG_URL.format(entry="enterprise"), "post"),
        (VERIFY_URL, "post"),
        (RESEND_URL, "post"),
        (ENTRIES_URL, "get"),
    ):
        response = getattr(client, method)(path, json={} if method == "post" else None)
        assert response.status_code == 404, path
        assert response.get_json()["error"]["code"] == "not_found"


def test_legacy_g6_route_closed_by_default_returns_404(client):
    """G6 legacy URL 收拢后同闸：默认关闭 ⇒ 404（不确认面存在）。"""
    response = client.post(
        LEGACY_REG_URL,
        json={
            "username": "reg.legacy",
            "display_name": "测试企业甲",
            "password": PASSWORD,
            "email": _email(),
            "subject_key": VALID_USCC,
            "problem_description": "问题",
        },
    )
    assert response.status_code == 404


@pytest.mark.parametrize(
    "overrides",
    [
        {"registration_enabled": False},
        {"ses_enabled": False},
        {"public_base_url": ""},
    ],
)
def test_gate_requires_all_three_conditions(reg_app, overrides):
    """开闸三条件缺一即关（404）：部署开关 AND SES AND 公网根地址。"""
    reg_app.config["SETTINGS"] = reg_app.config["SETTINGS"].model_copy(
        update=overrides
    )
    client = reg_app.test_client()
    response = client.post(REG_URL.format(entry="founder"), json={})
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# 2. 入口清单（区域服务商默认置后）
# ---------------------------------------------------------------------------


def test_entries_order_partner_last_and_review_flags(reg_client, reg_settings):
    response = reg_client.get(ENTRIES_URL)
    assert response.status_code == 200
    entries = response.get_json()["data"]["entries"]
    assert [item["entry"] for item in entries] == [
        "enterprise",
        "founder",
        "deliverer",
        "partner",
    ], "区域服务商入口必须排在最后（sec 评审「入口默认置后」）"
    assert [item["review_required"] for item in entries] == [
        False,
        False,
        True,
        True,
    ], "审核制缺省＝拍板值（交付者与区域审核、企业与创业者自助激活）"


def test_review_switch_is_configurable(reg_settings):
    """审核制开关生效：置空 ⇒ 全部自助激活；未知入口名 ⇒ fail-closed 全审核。"""
    empty = reg_settings.model_copy(update={"registration_review_entries": ""})
    assert review_entries(empty) == frozenset()

    unknown = reg_settings.model_copy(
        update={"registration_review_entries": "deliverer, mystery_entry"}
    )
    assert review_entries(unknown) == frozenset(
        {"enterprise", "founder", "deliverer", "partner"}
    ), "配置错误宁可多审不可漏审"


# ---------------------------------------------------------------------------
# 3. 四入口注册流
# ---------------------------------------------------------------------------


def test_founder_self_activates_after_email_verification(
    reg_client, reg_app, db_session
):
    response = _register(reg_client, "founder")
    assert response.status_code == 201, response.get_json()
    data = response.get_json()["data"]
    assert data["registration_state"] == "pending_email"
    assert data["verification_email"]["status"] == "sent"

    user = _get_user(db_session, data["user_id"])
    assert user.role == "viewer"
    assert user.org_id is None
    assert user.email == data["email"]
    assert user.email_verified_at is None

    registration = _registration_by_user(db_session, user.id)
    assert registration is not None
    assert registration.entry == "founder"
    assert registration.materials_json is None
    assert registration.token_consumed_at is None
    assert re.fullmatch(r"[0-9a-f]{64}", registration.token_sha256 or "")

    verify = _verify_token(reg_client, _latest_token(reg_app))
    assert verify.status_code == 200, verify.get_json()
    assert verify.get_json()["data"]["registration_state"] == "active"

    user = _get_user(db_session, data["user_id"])
    assert user.registration_state == "active"
    assert user.email_verified_at is not None

    login = _login(reg_app.test_client(), user.username)
    assert login.status_code == 200, login.get_json()


def test_enterprise_registration_creates_org_full_stack(
    reg_client, reg_app, db_session
):
    response = _register(reg_client, "enterprise", display_name="测试企业甲")
    assert response.status_code == 201, response.get_json()
    data = response.get_json()["data"]
    assert data["subject_key"] == VALID_USCC
    assert data["quota_created"] is True
    assert data["verification_email"]["status"] == "sent"

    user = _get_user(db_session, data["user_id"])
    # ADR-M2 §2 初始角色矩阵：企业客户 → project_lead（org 内）
    assert user.role == "project_lead"
    assert user.registration_state == "pending_email"

    org = db_session.get(Org, user.org_id)
    assert org is not None
    assert org.org_type == "enterprise"
    assert org.subject_key == VALID_USCC
    assert org.name == "测试企业甲"

    subject = db_session.get(EnterpriseQuotaSubject, VALID_USCC)
    assert subject is not None
    quota = db_session.get(EnterpriseFreeQuota, VALID_USCC)
    assert quota is not None
    entitlement = db_session.scalar(
        select(CommercialEntitlement).where(CommercialEntitlement.user_id == user.id)
    )
    assert entitlement is not None
    assert entitlement.commercial_role == "R1"

    verify = _verify_token(reg_client, _latest_token(reg_app))
    assert verify.status_code == 200
    assert verify.get_json()["data"]["registration_state"] == "active"


def test_deliverer_requires_review_after_verification(reg_client, reg_app, db_session):
    materials = {
        "materials": [
            {
                "kind": "fde_level_evidence",
                "source_uri": "file:///evidence/deliverer-a/case-01.pdf",
                "sha256": hashlib.sha256(b"evidence-a").hexdigest(),
            }
        ]
    }
    response = _register(reg_client, "deliverer", intake=materials)
    assert response.status_code == 201, response.get_json()
    data = response.get_json()["data"]

    verify = _verify_token(reg_client, _latest_token(reg_app))
    assert verify.status_code == 200
    assert verify.get_json()["data"]["registration_state"] == "pending_review"

    user = _get_user(db_session, data["user_id"])
    assert user.role == "viewer", "审核通过前不授 fde_engineer（供给池审核授予）"
    assert user.org_id is None
    registration = _registration_by_user(db_session, user.id)
    assert registration.materials_json == materials
    assert registration.reviewed_at is None

    # pending_review 可登录（viewer 最小面）但越权面被既有角色闸兜住
    client = reg_app.test_client()
    login = _login(client, user.username)
    assert login.status_code == 200
    token = login.get_json()["data"]["access_token"]
    admin_probe = client.get(
        "/api/v1/users",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert admin_probe.status_code == 403


def test_partner_registration_stores_org_fields_not_org_row(
    reg_client, reg_app, db_session
):
    """区域服务商＝个人主体＋机构字段（OWNER 拍板 2026-11-11，不落 orgs 行）。"""
    before = db_session.scalar(select(func.count()).select_from(Org))
    response = _register(
        reg_client,
        "partner",
        intake={"org_name": "区域服务商甲", "region_name": "华东"},
    )
    assert response.status_code == 201, response.get_json()
    data = response.get_json()["data"]

    verify = _verify_token(reg_client, _latest_token(reg_app))
    assert verify.get_json()["data"]["registration_state"] == "pending_review"

    user = _get_user(db_session, data["user_id"])
    assert user.role == "viewer"
    assert user.org_id is None
    registration = _registration_by_user(db_session, user.id)
    assert registration.materials_json == {
        "org_name": "区域服务商甲",
        "region_name": "华东",
    }
    after = db_session.scalar(select(func.count()).select_from(Org))
    assert after == before, "partner 注册不得建 org 行"


def test_enterprise_intake_rejected(reg_client):
    response = _register(reg_client, "enterprise", intake={"materials": []})
    assert response.status_code == 400
    assert response.get_json()["error"]["code"] == "invalid_request"


def test_deliverer_materials_reject_bad_shapes(reg_client):
    bad_hash = {
        "materials": [{"source_uri": "file:///x", "sha256": "nothex"}]
    }
    response = _register(reg_client, "deliverer", intake=bad_hash)
    assert response.status_code == 400

    missing_uri = {"materials": [{"sha256": "a" * 64}]}
    response = _register(reg_client, "deliverer", intake=missing_uri)
    assert response.status_code == 400

    extra_keys = {
        "materials": [
            {
                "source_uri": "file:///x",
                "sha256": "a" * 64,
                "answer": "评测集答案永不入库",
            }
        ]
    }
    response = _register(reg_client, "deliverer", intake=extra_keys)
    assert response.status_code == 400

    too_many = {
        "materials": [
            {"source_uri": f"file:///x{i}", "sha256": "a" * 64} for i in range(11)
        ]
    }
    response = _register(reg_client, "deliverer", intake=too_many)
    assert response.status_code == 400


# ---------------------------------------------------------------------------
# 4. 主体幂等与冲突（ADR-M4 §5 判定基线）
# ---------------------------------------------------------------------------


def test_second_registrant_same_subject_reuses_org_and_quota(
    reg_client, reg_app, db_session
):
    first = _register(reg_client, "enterprise", display_name="测试企业甲")
    assert first.status_code == 201
    second = _register(reg_client, "enterprise", display_name="测试企业甲")
    assert second.status_code == 201, second.get_json()

    first_data = first.get_json()["data"]
    second_data = second.get_json()["data"]
    assert second_data["quota_created"] is False, "同主体幂等：额度绝不新建/重置"

    user_a = _get_user(db_session, first_data["user_id"])
    user_b = _get_user(db_session, second_data["user_id"])
    assert user_a.org_id is not None
    assert user_b.org_id == user_a.org_id, "第二经办人复用同一 org"

    orgs = db_session.scalars(select(Org).where(Org.subject_key == VALID_USCC)).all()
    assert len(orgs) == 1


def test_org_name_conflict_rejected(reg_client):
    """不同主体撞同一企业代号 → 409（代号化纪律由注册人遵守，不自动改名）。"""
    first = _register(reg_client, "enterprise", display_name="同名企业")
    assert first.status_code == 201
    other_uscc = "91350100M0001001YM"  # 公开样本（mod-31 校验通过，现算）
    second = _register(
        reg_client, "enterprise", display_name="同名企业", subject_key=other_uscc
    )
    assert second.status_code == 409
    assert second.get_json()["error"]["code"] == "org_name_conflict"


def test_duplicate_email_rejected_with_event(reg_client, db_session):
    email = _email()
    first = _register(reg_client, "founder", email=email)
    assert first.status_code == 201
    second = _register(reg_client, "founder", email=email)
    assert second.status_code == 409
    assert second.get_json()["error"]["code"] == "email_already_exists"


def test_duplicate_username_rejected(reg_client):
    username = f"reg.{uuid4().hex[:10]}"
    first = _register(reg_client, "founder", username=username)
    assert first.status_code == 201
    second = _register(reg_client, "founder", username=username)
    assert second.status_code == 409
    assert second.get_json()["error"]["code"] == "username_already_exists"


def test_email_normalized_and_duplicate_detected(reg_client):
    """NFKC + 去空白 + 小写归一：'A@Example.com' 与 'a@example.com' 同一邮箱。"""
    first = _register(reg_client, "founder", email="  A@Example.COM ")
    assert first.status_code == 201
    assert first.get_json()["data"]["email"] == "a@example.com"
    second = _register(reg_client, "founder", email="a@example.com")
    assert second.status_code == 409


def test_invalid_email_and_invalid_entry_rejected(reg_client):
    response = _register(reg_client, "founder", email="not-an-email")
    assert response.status_code == 400
    assert response.get_json()["error"]["code"] == "invalid_email"

    response = reg_client.post(REG_URL.format(entry="mystery"), json={})
    assert response.status_code == 400
    assert response.get_json()["error"]["code"] == "invalid_entry"


def test_invalid_uscc_rejected(reg_client):
    response = _register(
        reg_client, "enterprise", subject_key="91350100M000100Y99"
    )
    assert response.status_code == 400
    assert response.get_json()["error"]["code"] == "invalid_subject_key"


# ---------------------------------------------------------------------------
# 5. 邮箱验证与重发
# ---------------------------------------------------------------------------


def test_verify_token_one_time_only(reg_client, reg_app):
    _register(reg_client, "founder")
    token = _latest_token(reg_app)
    first = _verify_token(reg_client, token)
    assert first.status_code == 200
    second = _verify_token(reg_client, token)
    assert second.status_code == 409
    assert second.get_json()["error"]["code"] == "token_already_used"


def test_verify_invalid_and_expired_tokens(reg_client, reg_app, db_session):
    _register(reg_client, "founder")
    garbage = _verify_token(reg_client, "not-a-real-token")
    assert garbage.status_code == 400
    assert garbage.get_json()["error"]["code"] == "invalid_token"

    registration = db_session.scalars(select(UserRegistration)).all()[-1]
    registration.token_expires_at = datetime.now(UTC) - timedelta(hours=1)
    db_session.commit()
    expired = _verify_token(reg_client, _latest_token(reg_app))
    assert expired.status_code == 400
    assert expired.get_json()["error"]["code"] == "token_expired"


def test_verify_wrong_state_rejected(reg_client, reg_app, db_session):
    """防御分支钉：令牌未消费但状态已推进（并发消费/人工干预）→ 409。"""
    _register(reg_client, "founder")
    registration = db_session.scalars(select(UserRegistration)).all()[-1]
    user = db_session.get(User, registration.user_id)
    user.registration_state = "suspended"
    db_session.commit()
    response = _verify_token(reg_client, _latest_token(reg_app))
    assert response.status_code == 409
    assert response.get_json()["error"]["code"] == "invalid_registration_state"


def test_resend_rotates_token_and_kills_old_link(reg_client, reg_app, db_session):
    _register(reg_client, "founder")
    _backdate_token_request(db_session)
    old_token = _latest_token(reg_app)
    resent = reg_client.post(RESEND_URL, json={"username": _pending_username(db_session)})
    assert resent.status_code == 202
    new_token = _latest_token(reg_app)
    assert new_token != old_token, "重发即轮换"

    stale = _verify_token(reg_client, old_token)
    assert stale.status_code == 400, "旧链接必须失效"
    fresh = _verify_token(reg_client, new_token)
    assert fresh.status_code == 200


def _pending_username(db_session: Session) -> str:
    row = db_session.scalars(
        select(User.username)
        .join(UserRegistration, UserRegistration.user_id == User.id)
        .where(User.registration_state == "pending_email")
        .order_by(UserRegistration.created_at.desc())
        .limit(1)
    ).first()
    assert row is not None
    return row


def test_resend_throttled_within_min_interval(reg_client, reg_app, db_session):
    _register(reg_client, "founder")
    username = _pending_username(db_session)
    _backdate_token_request(db_session)
    first = reg_client.post(RESEND_URL, json={"username": username})
    assert first.status_code == 202
    second = reg_client.post(RESEND_URL, json={"username": username})
    assert second.status_code == 429
    assert second.get_json()["error"]["code"] == "resend_throttled"


def test_resend_never_enumerates(reg_client, reg_app, db_session):
    """防枚举：未知用户名 / 已验证账号 / 真实重发——响应形状恒同 202 accepted。"""
    shapes = []
    shapes.append(reg_client.post(RESEND_URL, json={"username": "ghost.user"}).get_json())
    _register(reg_client, "founder")
    username = _pending_username(db_session)
    _backdate_token_request(db_session)
    _verify_token(reg_client, _latest_token(reg_app))
    shapes.append(reg_client.post(RESEND_URL, json={"username": username}).get_json())
    assert all(
        shape == {"data": {"status": "accepted"}, "error": None} for shape in shapes
    ), shapes


def test_resend_real_dispatch_records_event(reg_client, reg_app, db_session):
    _register(reg_client, "founder")
    username = _pending_username(db_session)
    _backdate_token_request(db_session)
    response = reg_client.post(RESEND_URL, json={"username": username})
    assert response.status_code == 202
    events = db_session.scalars(
        select(OperationEvent).where(
            OperationEvent.event_type == "registration_verification_resent"
        )
    ).all()
    assert len(events) == 1


# ---------------------------------------------------------------------------
# 6. 登录闸与刷新闸（4xx 且留痕）
# ---------------------------------------------------------------------------


def test_pending_email_login_blocked_with_audit_event(reg_client, reg_app, db_session):
    response = _register(reg_client, "founder")
    username = response.get_json()["data"]["username"]
    client = reg_app.test_client()
    login = _login(client, username)
    assert login.status_code == 403
    assert login.get_json()["error"]["code"] == "email_not_verified"
    events = db_session.scalars(
        select(OperationEvent).where(
            OperationEvent.event_type == "login_blocked_registration_state"
        )
    ).all()
    assert len(events) == 1, "未验证邮箱登录必须留痕（ADR-M4 §5）"


def test_suspended_login_blocked_and_reinstate_restores(reg_client, reg_app, db_session, admin_api):
    response = _register(reg_client, "founder")
    data = response.get_json()["data"]
    _verify_token(reg_client, _latest_token(reg_app))
    user = _get_user(db_session, data["user_id"])

    suspended = admin_api.post(f"{ADMIN_LIST_URL}/{user.id}/suspend", json={})
    assert suspended.status_code == 200
    assert suspended.get_json()["data"]["registration_state"] == "suspended"

    client = reg_app.test_client()
    login = _login(client, user.username)
    assert login.status_code == 403
    assert login.get_json()["error"]["code"] == "account_suspended"

    reinstate = admin_api.post(f"{ADMIN_LIST_URL}/{user.id}/reinstate", json={})
    assert reinstate.status_code == 200
    assert reinstate.get_json()["data"]["registration_state"] == "active"
    assert _login(client, user.username).status_code == 200


def test_rejected_login_blocked(reg_client, reg_app, db_session, admin_api):
    response = _register(reg_client, "deliverer")
    data = response.get_json()["data"]
    _verify_token(reg_client, _latest_token(reg_app))
    user = _get_user(db_session, data["user_id"])

    rejected = admin_api.post(
        f"{ADMIN_LIST_URL}/{user.id}/review",
        json={"decision": "reject", "note": "材料不完整"},
    )
    assert rejected.status_code == 200
    assert rejected.get_json()["data"]["registration_state"] == "rejected"

    login = _login(reg_app.test_client(), user.username)
    assert login.status_code == 403
    assert login.get_json()["error"]["code"] == "registration_rejected"


def test_refresh_blocked_for_suspended_account(
    reg_client, reg_app, db_session, admin_api
):
    """刷新面同闸：active 时登录拿到的 refresh 在 suspended 后不得续期。"""
    response = _register(reg_client, "founder")
    data = response.get_json()["data"]
    _verify_token(reg_client, _latest_token(reg_app))
    user = _get_user(db_session, data["user_id"])

    client = reg_app.test_client()
    login = _login(client, user.username)
    refresh_token = login.get_json()["data"]["refresh_token"]

    assert admin_api.post(f"{ADMIN_LIST_URL}/{user.id}/suspend", json={}).status_code == 200
    refresh = client.post("/api/v1/auth/refresh", json={"refresh_token": refresh_token})
    assert refresh.status_code == 403
    assert refresh.get_json()["error"]["code"] == "account_suspended"


# ---------------------------------------------------------------------------
# 7. admin 审核簿记
# ---------------------------------------------------------------------------


def test_review_approve_activates_deliverer(reg_client, reg_app, db_session, admin_api):
    response = _register(reg_client, "deliverer")
    data = response.get_json()["data"]
    _verify_token(reg_client, _latest_token(reg_app))
    user = _get_user(db_session, data["user_id"])

    wrong_decision = admin_api.post(
        f"{ADMIN_LIST_URL}/{user.id}/review", json={"decision": "maybe"}
    )
    assert wrong_decision.status_code == 400

    approved = admin_api.post(
        f"{ADMIN_LIST_URL}/{user.id}/review", json={"decision": "approve"}
    )
    assert approved.status_code == 200, approved.get_json()
    assert approved.get_json()["data"]["registration_state"] == "active"

    registration = _registration_by_user(db_session, user.id)
    assert registration.reviewed_by_user_id == admin_api.id
    assert registration.reviewed_at is not None


def test_review_reject_requires_note_and_is_terminal(
    reg_client, reg_app, db_session, admin_api
):
    response = _register(reg_client, "deliverer")
    data = response.get_json()["data"]
    _verify_token(reg_client, _latest_token(reg_app))
    user = _get_user(db_session, data["user_id"])

    no_note = admin_api.post(
        f"{ADMIN_LIST_URL}/{user.id}/review", json={"decision": "reject"}
    )
    assert no_note.status_code == 400
    assert no_note.get_json()["error"]["code"] == "review_note_required"

    rejected = admin_api.post(
        f"{ADMIN_LIST_URL}/{user.id}/review",
        json={"decision": "reject", "note": "R 分层材料缺失"},
    )
    assert rejected.status_code == 200

    again = admin_api.post(
        f"{ADMIN_LIST_URL}/{user.id}/review", json={"decision": "approve"}
    )
    assert again.status_code == 409, "rejected 终态不得复活"

    reinstate = admin_api.post(f"{ADMIN_LIST_URL}/{user.id}/reinstate", json={})
    assert reinstate.status_code == 409, "仅 suspended 可恢复"


def test_suspend_reinstate_derives_pending_review(
    reg_client, reg_app, db_session, admin_api
):
    """审核入口未审核即停用 → 恢复按事实推导回 pending_review（不存「停用前态」）。"""
    response = _register(reg_client, "deliverer")
    data = response.get_json()["data"]
    _verify_token(reg_client, _latest_token(reg_app))
    user = _get_user(db_session, data["user_id"])

    assert admin_api.post(f"{ADMIN_LIST_URL}/{user.id}/suspend", json={}).status_code == 200
    reinstate = admin_api.post(f"{ADMIN_LIST_URL}/{user.id}/reinstate", json={})
    assert reinstate.status_code == 200
    assert reinstate.get_json()["data"]["registration_state"] == "pending_review"


def test_reinstate_unverified_returns_pending_email(
    reg_client, reg_app, db_session, admin_api
):
    """防御分支钉：未验证即被停用（人工干预态）→ 恢复回 pending_email。"""
    response = _register(reg_client, "founder")
    data = response.get_json()["data"]
    user = _get_user(db_session, data["user_id"])
    user.registration_state = "suspended"  # 直接落库构造（API 不允许停用 pending_email）
    db_session.commit()

    reinstate = admin_api.post(f"{ADMIN_LIST_URL}/{user.id}/reinstate", json={})
    assert reinstate.status_code == 200
    assert reinstate.get_json()["data"]["registration_state"] == "pending_email"


def test_admin_routes_require_admin(client, db_session, settings):
    """非 admin 403（admin 簿记面不过部署闸但过角色闸）。"""
    user = User(
        username=f"leader.{uuid4().hex[:10]}",
        display_name="leader",
        role="project_lead",
        password_hash=hash_password(INITIAL_PASSWORD),
        must_change_password=False,
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()
    headers = {"Authorization": f"Bearer {issue_access_token(user, settings)}"}
    assert client.get(ADMIN_LIST_URL, headers=headers).status_code == 403
    assert (
        client.post(f"{ADMIN_LIST_URL}/nobody/review", headers=headers, json={}).status_code
        == 403
    )


def test_admin_list_filters_by_state_and_unknown_user_404(
    reg_client, reg_app, db_session, admin_api
):
    founder = _register(reg_client, "founder")
    _verify_token(reg_client, _latest_token(reg_app))
    _register(reg_client, "deliverer")  # 保持 pending_email（未验证）

    listed = admin_api.get(f"{ADMIN_LIST_URL}?state=pending_review")
    assert listed.status_code == 200
    payload = listed.get_json()["data"]
    assert payload["total"] == 0  # founder 已 active；deliverer 未验证仍在 pending_email

    listed_all = admin_api.get(ADMIN_LIST_URL)
    assert listed_all.get_json()["data"]["total"] == 2

    missing = admin_api.post(
        f"{ADMIN_LIST_URL}/{founder.get_json()['data']['user_id']}x/review",
        json={"decision": "approve"},
    )
    assert missing.status_code == 404


# ---------------------------------------------------------------------------
# 8. 统一注册限流（auth:register:{ip}）
# ---------------------------------------------------------------------------


def test_unified_register_ip_daily_limit(reg_app, reg_settings):
    reg_app.config["SETTINGS"] = reg_settings.model_copy(
        update={"registration_ip_daily_limit": 3}
    )
    client = reg_app.test_client()
    for _ in range(3):
        response = _register(client, "founder")
        assert response.status_code == 201
    blocked = client.post(REG_URL.format(entry="founder"), json={})
    assert blocked.status_code == 429
    assert blocked.get_json()["error"]["code"] == "registration_rate_limited"

    other_ip = client.post(
        REG_URL.format(entry="founder"),
        json={},
        environ_base={"REMOTE_ADDR": "10.9.8.7"},
    )
    assert other_ip.status_code == 400, "限流按 IP 分域，换 IP 不被牵连"


def test_unified_limit_shared_bucket_with_legacy_url(reg_app, reg_settings):
    """legacy G6 URL 与统一四入口共用同一桶——收拢不产生限流旁路。"""
    reg_app.config["SETTINGS"] = reg_settings.model_copy(
        update={"registration_ip_daily_limit": 2}
    )
    client = reg_app.test_client()
    for _ in range(2):
        assert client.post(REG_URL.format(entry="founder"), json={}).status_code == 400
    legacy = client.post(
        LEGACY_REG_URL,
        json={
            "username": "reg.shared",
            "display_name": "测试企业甲",
            "password": PASSWORD,
            "email": _email(),
            "subject_key": VALID_USCC,
            "problem_description": "问题",
        },
    )
    assert legacy.status_code == 429, "统一限流必须覆盖 legacy URL"


def test_register_rate_limit_fail_open_by_default_broken_redis(
    reg_app, reg_settings, monkeypatch, caplog
):
    import logging

    reg_app.config["SETTINGS"] = reg_settings.model_copy(
        update={"registration_rate_fail_closed": False}
    )
    reg_app.extensions["fde_api_redis"] = _BrokenRedis()
    client = reg_app.test_client()
    with caplog.at_level(logging.WARNING):
        response = client.post(REG_URL.format(entry="founder"), json={})
    assert response.status_code == 400, "Redis 故障默认 fail-open（G6 K8 同款）"
    assert any("rate limiter" in r.message.lower() for r in caplog.records)


def test_register_rate_limit_fail_closed_when_configured(
    reg_app, reg_settings, monkeypatch, caplog
):
    import logging

    reg_app.config["SETTINGS"] = reg_settings.model_copy(
        update={"registration_rate_fail_closed": True}
    )
    reg_app.extensions["fde_api_redis"] = _BrokenRedis()
    client = reg_app.test_client()
    with caplog.at_level(logging.WARNING):
        response = client.post(REG_URL.format(entry="founder"), json={})
    assert response.status_code == 429
    assert response.get_json()["error"]["code"] == "registration_rate_limited"
    assert any("rate limiter" in r.message.lower() for r in caplog.records)


# ---------------------------------------------------------------------------
# 9. G6 收拢委托（legacy URL 同语义）
# ---------------------------------------------------------------------------


def test_g6_route_delegates_to_unified_semantics(
    client, db_session, monkeypatch
):
    """legacy URL：同部署闸、同状态机、同角色矩阵（viewer→project_lead）、
    建号即建 org；URL 与 K8 限流保持不变（ADR-M4「收拢」处置）。"""
    fake = _FakeSes()
    monkeypatch.setattr(
        "fde_api.mailing.service.create_ses_client", lambda settings: fake
    )
    app = client.application
    app.config["SETTINGS"] = app.config["SETTINGS"].model_copy(
        update={
            "registration_enabled": True,
            "ses_enabled": True,
            "public_base_url": "https://fde.example.com",
            "ses_send_subdomain": "mail.somwyn.com",
            "ses_from_address": "no-reply@mail.somwyn.com",
        }
    )
    app.extensions["fde_api_redis"] = _FakeRedis()

    response = client.post(
        LEGACY_REG_URL,
        json={
            "username": "reg.legacy.delegate",
            "display_name": "测试企业甲",
            "password": PASSWORD,
            "email": _email(),
            "subject_key": VALID_USCC,
            "problem_description": "描述业务问题：需要一次完整诊断。",
        },
    )
    assert response.status_code == 200, response.get_json()
    data = response.get_json()["data"]
    assert data["registration_state"] == "pending_email"
    assert data["quota_created"] is True
    assert data["verification_email"]["status"] == "sent"

    user = _get_user(db_session, data["user_id"])
    assert user.role == "project_lead"
    org = db_session.get(Org, user.org_id)
    assert org is not None and org.org_type == "enterprise"


def test_registration_events_never_carry_secrets(reg_client, reg_app, db_session):
    """事件脱敏钉：注册域事件载荷零密码零令牌（明文只在邮件里）。"""
    _register(reg_client, "enterprise")
    events = db_session.scalars(
        select(OperationEvent).where(
            OperationEvent.event_type.in_(
                ["registration_submitted", "enterprise_self_registered"]
            )
        )
    ).all()
    assert events
    sensitive = re.compile(
        r"password|passwd|pwd|token|secret|credential", re.IGNORECASE
    )
    for event in events:
        changes = event.changes or {}
        assert not any(sensitive.search(str(key)) for key in changes), changes


# ---------------------------------------------------------------------------
# 10. 治理面不进 api_catalog（G6/诊断线同款纪律）
# ---------------------------------------------------------------------------


def test_registration_surface_not_in_api_catalog(app):
    """治理面不进 api_catalog（app 夹具取 url_map——**裸 create_app() 在 CI 无
    .env 必炸**〔G6 已知教训〕；蓝图注册无条件在位，部署闸只影响请求期行为，
    不影响 url_map）。"""
    from fde_api.control.api_catalog import CATALOG

    registered = {
        rule.rule
        for rule in app.url_map.iter_rules()
        if "register" in rule.rule or "registrations" in rule.rule
    }
    catalog_paths = {row["path"] for row in CATALOG.values()}
    assert registered and not (registered & catalog_paths)


# ---------------------------------------------------------------------------
# 11. 迁移往返（additive；存量行 server_default active；对称可逆）
# ---------------------------------------------------------------------------


def _users_columns(engine) -> set[str]:
    with engine.connect() as connection:
        return {
            row[0]
            for row in connection.execute(
                text(
                    "SELECT column_name FROM information_schema.columns"
                    " WHERE table_name = 'users' AND table_schema = current_schema()"
                )
            )
        }


def test_migration_roundtrip_registration_columns(alembic_config, engine):
    """downgrade 到 M1 → 升回 head：存量用户落 active（零回填语句）、列对称。"""
    from alembic import command

    command.downgrade(alembic_config, "a5e9c3f1b7d4")
    assert "user_registrations" not in table_names(engine)
    columns = _users_columns(engine)
    assert "email" not in columns
    assert "registration_state" not in columns

    seed_user_and_template(engine, username="migration.m2-keep")

    command.upgrade(alembic_config, "head")

    assert "user_registrations" in table_names(engine)
    columns = _users_columns(engine)
    assert {"email", "email_verified_at", "registration_state"} <= columns
    legacy_state = scalar(
        engine,
        "SELECT registration_state FROM users WHERE username = 'migration.m2-keep'",
    )
    assert legacy_state == "active", "存量行由 server_default 落 active，零回填语句"
    legacy_email = scalar(
        engine, "SELECT email FROM users WHERE username = 'migration.m2-keep'"
    )
    assert legacy_email is None, "存量用户无邮箱（不回填）"
