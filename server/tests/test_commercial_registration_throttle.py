"""G6 遗留挂账清偿：注册面节流（公开注册入口的防滥用闸，复用 #250 登录限流模式）。

钉住十件事：
1. 同一来源 IP 的第 11 次注册尝试被 429 拒绝（``registration_rate_limited``）；
2. 限流键按来源 IP 分域——换 IP 不被牵连；
3. 计数发生在载荷解析与 argon2 计算之前——畸形载荷同样消耗配额；
4. 被限的请求**零副作用**（不建账号、不落主体、不留事件）；
5. **成功不清零**——注册成功同样创建账号，成功清零会让「注册→清零→再注册」
   绕过配额（这是容量上限，不是失败锁定）；
6. 首次计数同时落窗口 TTL（1 小时）；
7. Redis 不可用时默认 fail-open（放行＋记 WARNING，绝不静默）；
8. ``FDE_REGISTRATION_RATE_FAIL_CLOSED=1`` 切 fail-closed（一律 429＋WARNING）；
9. ProxyFix 之后取 XFF 的真实客户端 IP；无 XFF 时回落 REMOTE_ADDR；
10. 测试夹具按用例分配独立来源 IP——限流计数落在共享 Redis 上，不隔离则
    用例之间互相牵连（前者挡在 429 上）。
"""

from __future__ import annotations

import logging
from uuid import uuid4

import pytest
from redis.exceptions import RedisError

from conftest import PerTestIPClient
from fde_api.auth.models import User
from fde_api.commercial.models import EnterpriseQuotaSubject
from fde_api.workbench.models import OperationEvent

REG_URL = "/api/v1/commercial/enterprise-registrations"
VALID_USCC = "91350100M000100Y43"  # 公开样本（mod-31 校验通过，同 G6）
SELF_PASSWORD = "Enterprise!Pass2026"
MAX_ATTEMPTS = 10
WINDOW_SECONDS = 3600


class _FakeRedis:
    """最小 incr/expire/ttl 语义，模拟真实 Redis 计数（与 #250 限流用例同款）。"""

    def __init__(self):
        self.counters: dict[str, int] = {}
        self.ttls: dict[str, int] = {}

    def incr(self, key: str) -> int:
        self.counters[key] = self.counters.get(key, 0) + 1
        return self.counters[key]

    def expire(self, key: str, seconds: int) -> None:
        self.ttls[key] = seconds

    def ttl(self, key: str) -> int:
        return self.ttls.get(key, WINDOW_SECONDS)


class _BrokenRedis:
    """所有操作抛 RedisError —— 模拟 Redis 不可用。"""

    def incr(self, key: str) -> int:
        raise RedisError("connection refused")

    def expire(self, key: str, seconds: int) -> None:
        raise RedisError("connection refused")

    def ttl(self, key: str) -> int:
        raise RedisError("connection refused")


def _payload(username: str | None = None) -> dict[str, str]:
    return {
        "username": username or f"ent.{uuid4().hex[:10]}",
        "display_name": "测试企业甲",
        "password": SELF_PASSWORD,
        "email": f"{uuid4().hex[:12]}@example.com",
        "subject_key": VALID_USCC,
        "problem_description": "描述业务问题：订单履约周期过长，需要一次完整诊断。",
    }


def _post_register(client, ip: str, *, payload=None, xff: str | None = None):
    headers = {"X-Forwarded-For": xff} if xff else {}
    return client.post(
        REG_URL,
        json=payload if payload is not None else {},
        environ_base={"REMOTE_ADDR": ip},
        headers=headers,
    )


def _post_raw(client, ip: str, body: str = "not-json"):
    """非 JSON 载荷——请求在解析阶段就拿不到字典（节流必须照样计入）。"""
    return client.post(
        REG_URL,
        data=body,
        content_type="application/json",
        environ_base={"REMOTE_ADDR": ip},
    )


@pytest.fixture
def limited_client(app):
    app.extensions["fde_api_redis"] = _FakeRedis()
    return app.test_client()


class _FakeSes:
    """注册面开闸后的假 SES（M2 收拢：G6 路由走统一注册面，注册事务提交后
    会真实触发验证邮件发送——测试绝不发真邮件）。"""

    def __init__(self) -> None:
        self.calls: list[dict[str, str]] = []

    def send_text(self, *, sender: str, recipient: str, subject: str, body: str) -> str:
        self.calls.append(
            {"sender": sender, "recipient": recipient, "subject": subject, "body": body}
        )
        return f"ses-msg-{len(self.calls)}"


@pytest.fixture(autouse=True)
def _open_registration_gate(app, monkeypatch):
    """多客户 M2 收拢语义：G6 路由委托统一注册面（同一部署闸/状态机/邮箱验证）。
    本文件测的是 K8 限流闸本身 ⇒ 用例前提＝注册面开（否则全部 404，限流闸
    永远测不到业务校验路径）。"""
    monkeypatch.setattr(
        "fde_api.mailing.service.create_ses_client", lambda settings: _FakeSes()
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


# ---------------------------------------------------------------------------
# 1–2. 阈值与分域
# ---------------------------------------------------------------------------


def test_registration_throttle_blocks_eleventh_attempt(app, db_session, limited_client):
    """同 IP 第 11 次注册尝试 429（前 10 次照常走到业务校验）。"""
    for _ in range(MAX_ATTEMPTS):
        response = _post_register(limited_client, "10.9.9.9")
        assert response.status_code == 400, response.json

    blocked = _post_register(limited_client, "10.9.9.9")
    assert blocked.status_code == 429
    assert blocked.json["error"]["code"] == "registration_rate_limited"
    assert blocked.json["data"] is None


def test_registration_throttle_scoped_to_source_ip(app, db_session, limited_client):
    """键含来源 IP——换 IP 的请求不被另一个 IP 的计数牵连。"""
    for _ in range(MAX_ATTEMPTS):
        assert _post_register(limited_client, "10.9.9.9").status_code == 400
    assert _post_register(limited_client, "10.9.9.9").status_code == 429

    other = _post_register(limited_client, "10.10.10.10")
    assert other.status_code == 400, "换 IP 被牵连 = 限流键粒度回归"


# ---------------------------------------------------------------------------
# 3–4. 计数时机与零副作用
# ---------------------------------------------------------------------------


def test_registration_throttle_counts_before_payload_parse(app, db_session, limited_client):
    """畸形载荷同样计一次——洪泛用坏载荷也逃不掉（计数在解析之前）。"""
    for _ in range(MAX_ATTEMPTS):
        assert _post_raw(limited_client, "10.9.9.9").status_code == 400

    blocked = _post_raw(limited_client, "10.9.9.9")
    assert blocked.status_code == 429
    assert blocked.json["error"]["code"] == "registration_rate_limited"


def test_blocked_registration_has_no_side_effect(app, db_session, limited_client):
    """被限的请求零副作用：不建账号、不落主体、不留事件。"""
    for _ in range(MAX_ATTEMPTS):
        assert _post_register(limited_client, "10.9.9.9").status_code == 400

    username = f"ent.{uuid4().hex[:10]}"
    blocked = _post_register(limited_client, "10.9.9.9", payload=_payload(username))
    assert blocked.status_code == 429

    db_session.expire_all()
    assert db_session.query(User).filter(User.username == username).count() == 0
    assert db_session.query(EnterpriseQuotaSubject).filter(
        EnterpriseQuotaSubject.subject_key == VALID_USCC
    ).count() == 0
    assert (
        db_session.query(OperationEvent)
        .filter(OperationEvent.event_type == "enterprise_self_registered")
        .count()
        == 0
    )


# ---------------------------------------------------------------------------
# 5–6. 成功不清零 + 窗口 TTL
# ---------------------------------------------------------------------------


def test_successful_registration_does_not_clear_counter(app, db_session, limited_client):
    """成功注册不清零——否则「注册→清零→再注册」可绕过配额。"""
    redis = app.extensions["fde_api_redis"]
    username = f"ent.{uuid4().hex[:10]}"
    for _ in range(MAX_ATTEMPTS - 1):
        assert _post_register(limited_client, "10.9.9.9").status_code == 400

    ok = _post_register(limited_client, "10.9.9.9", payload=_payload(username))
    assert ok.status_code == 200, ok.json

    key = "commercial:register:10.9.9.9"
    assert redis.counters[key] == MAX_ATTEMPTS, "成功注册清零了计数 = 配额可被绕过"
    assert (
        _post_register(limited_client, "10.9.9.9").status_code == 429
    ), "清零后仍应被限流"


def test_throttle_sets_window_ttl_on_first_attempt(app, db_session, limited_client):
    """首次计数同时落窗口 TTL（1 小时）——计数随窗口自然过期。"""
    redis = app.extensions["fde_api_redis"]
    assert _post_register(limited_client, "10.9.9.9").status_code == 400
    assert redis.ttls["commercial:register:10.9.9.9"] == WINDOW_SECONDS


# ---------------------------------------------------------------------------
# 7–8. Redis 故障路径（可观测 + 可配置 fail-closed）
# ---------------------------------------------------------------------------


def test_redis_down_fails_open_with_warning(app, db_session, caplog):
    """默认 fail-open：Redis 挂时请求照常走到业务校验，且必须记 WARNING。"""
    app.extensions["fde_api_redis"] = _BrokenRedis()
    client = app.test_client()

    with caplog.at_level(logging.WARNING):
        response = _post_register(client, "10.9.9.9")

    assert response.status_code == 400, "Redis 故障不得伪装成限流"
    # M2 统一注册面：email 是首个必填校验（空载荷先撞 invalid_request）
    assert response.json["error"]["code"] == "invalid_request"
    assert any("rate limiter" in record.message.lower() for record in caplog.records), (
        "Redis 故障放行必须留下 WARNING（不得静默）"
    )


def test_redis_down_fail_closed_when_configured(app, db_session, settings, caplog):
    """FDE_REGISTRATION_RATE_FAIL_CLOSED=1：注册面已开闸前提下 Redis 挂时一律 429（从严），同样记 WARNING。"""
    app.extensions["fde_api_redis"] = _BrokenRedis()
    app.config["SETTINGS"] = app.config["SETTINGS"].model_copy(
        update={"registration_rate_fail_closed": True}
    )
    client = app.test_client()

    with caplog.at_level(logging.WARNING):
        response = _post_register(client, "10.9.9.9")

    assert response.status_code == 429
    assert response.json["error"]["code"] == "registration_rate_limited"
    assert any("rate limiter" in record.message.lower() for record in caplog.records)


# ---------------------------------------------------------------------------
# 9. 来源 IP 取值（ProxyFix 后取真实客户端 IP）
# ---------------------------------------------------------------------------


def test_proxyfix_uses_forwarded_client_ip(app, db_session, limited_client):
    """反代后限流键取 XFF 的真实客户端 IP，不再退化为网关固定值。"""
    redis = app.extensions["fde_api_redis"]

    response = _post_register(limited_client, "172.21.0.1", xff="203.0.113.7")

    assert response.status_code == 400
    assert "commercial:register:203.0.113.7" in redis.counters
    assert "commercial:register:172.21.0.1" not in redis.counters


def test_no_forwarded_header_falls_back_to_remote_addr(app, db_session, limited_client):
    """无 XFF：按 REMOTE_ADDR 计数。"""
    redis = app.extensions["fde_api_redis"]

    response = _post_register(limited_client, "172.21.0.1")

    assert response.status_code == 400
    assert "commercial:register:172.21.0.1" in redis.counters


# ---------------------------------------------------------------------------
# 10. 测试隔离件：限流计数按用例隔离（共享 Redis 上的外部状态）
# ---------------------------------------------------------------------------


def test_rate_limit_source_ip_isolated_per_test(app):
    """限流键含来源 IP 且计数落在共享 Redis——测试必须按用例隔离来源 IP，
    否则一个用例的注册计数会把下一个用例挡在 429 上。"""
    assert app.test_client_class is PerTestIPClient
    client = app.test_client()
    assert isinstance(client, PerTestIPClient)
    assert client._source_ip != "127.0.0.1"
