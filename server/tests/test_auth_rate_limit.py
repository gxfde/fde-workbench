"""WP23/G7：登录限流键含来源 IP + Redis 故障路径可观测、可配置 fail-closed。

缺陷基线（5d82de1）：限流键只有 username —— 单 IP 连错 5 次即可定向锁死任意
用户名（含 admin）15 分钟；except RedisError 静默放行（docstring 自认），
无任何断言钉住 fail-open 行为。

修复口径：限流键改 username + 来源 IP 复合（单 IP 只锁「该 IP→该用户」对）；
Redis 不可用时记 WARNING（可观测），并可用 FDE_LOGIN_RATE_FAIL_CLOSED=1
切为 fail-closed（对外暴露部署从严）。默认 fail-open 维持本机回环部署语义。
"""

import logging

import pytest
from redis.exceptions import RedisError

from fde_api.auth.models import User
from fde_api.auth.passwords import hash_password


class _FakeRedis:
    """最小 incr/expire/ttl/delete 语义，模拟真实 Redis 计数。"""

    def __init__(self):
        self.counters: dict[str, int] = {}
        self.ttls: dict[str, int] = {}

    def incr(self, key: str) -> int:
        self.counters[key] = self.counters.get(key, 0) + 1
        return self.counters[key]

    def expire(self, key: str, seconds: int) -> None:
        self.ttls[key] = seconds

    def ttl(self, key: str) -> int:
        return self.ttls.get(key, 900)

    def delete(self, *keys: str) -> None:
        for key in keys:
            self.counters.pop(key, None)
            self.ttls.pop(key, None)


class _BrokenRedis:
    """所有操作抛 RedisError —— 模拟 Redis 不可用。"""

    def incr(self, key: str) -> int:
        raise RedisError("connection refused")

    def expire(self, key: str, seconds: int) -> None:
        raise RedisError("connection refused")

    def ttl(self, key: str) -> int:
        raise RedisError("connection refused")

    def delete(self, *keys: str) -> None:
        raise RedisError("connection refused")


PASSWORD = "Correct-Horse-1"


@pytest.fixture
def login_user_row(db_session):
    """一个可登录的真实用户（密码已知）。"""

    def create(username: str):
        user = User(
            username=username,
            display_name=username,
            role="viewer",
            password_hash=hash_password(PASSWORD),
            must_change_password=False,
            is_active=True,
        )
        db_session.add(user)
        db_session.commit()
        return user

    return create


def _post_login(
    client,
    username: str,
    ip: str,
    password: str = "wrong-password",
    xff: str | None = None,
):
    headers = {"X-Forwarded-For": xff} if xff else {}
    return client.post(
        "/api/v1/auth/login",
        json={"username": username, "password": password, "device_label": "pytest"},
        environ_base={"REMOTE_ADDR": ip},
        headers=headers,
    )


@pytest.fixture
def limited_client(app):
    app.extensions["fde_api_redis"] = _FakeRedis()
    return app.test_client()


def test_rate_limit_locks_same_username_same_ip(app, db_session, limited_client, login_user_row):
    """同 IP 同用户名：5 次错密码后第 6 次 429（连对的密码也被锁）。"""
    login_user_row("rate.victim")

    for _ in range(5):
        response = _post_login(limited_client, "rate.victim", "10.9.9.9")
        assert response.status_code == 401

    locked = _post_login(limited_client, "rate.victim", "10.9.9.9")
    assert locked.status_code == 429
    assert locked.json["error"]["code"] == "login_rate_limited"


def test_rate_limit_is_scoped_to_source_ip(app, db_session, limited_client, login_user_row):
    """复合键：同用户名换来源 IP 不得被另一个 IP 的失败牵连（防定向锁死）。"""
    login_user_row("rate.victim")

    for _ in range(5):
        assert _post_login(limited_client, "rate.victim", "10.9.9.9").status_code == 401
    assert _post_login(limited_client, "rate.victim", "10.9.9.9").status_code == 429

    other_ip = _post_login(limited_client, "rate.victim", "10.10.10.10")
    assert other_ip.status_code == 401, "同用户名不同 IP 被定向锁死 = G7 缺陷回归"


def test_rate_limit_scoped_per_username(app, db_session, limited_client, login_user_row):
    """同 IP 不同用户名互不影响（既有正确行为，钉住防回归）。"""
    login_user_row("rate.victim")
    login_user_row("rate.other")

    for _ in range(6):
        assert _post_login(limited_client, "rate.victim", "10.9.9.9").status_code in (401, 429)

    untouched = _post_login(limited_client, "rate.other", "10.9.9.9")
    assert untouched.status_code == 401, "跨用户名牵连 = 限流键粒度回归"


def test_success_resets_only_that_ip_counter(app, db_session, limited_client, login_user_row):
    """成功登录会清零计数：4 错 → 成功 → 再 5 错必须全 401（清零失效则第 1 错即 429）。"""
    login_user_row("rate.victim")

    for _ in range(4):
        assert _post_login(limited_client, "rate.victim", "10.9.9.9").status_code == 401
    success = _post_login(limited_client, "rate.victim", "10.9.9.9", PASSWORD)
    assert success.status_code == 200

    for i in range(5):
        response = _post_login(limited_client, "rate.victim", "10.9.9.9")
        assert response.status_code == 401, f"第 {i + 1} 次错密被 429 = 成功登录未清零计数"


def test_redis_down_fails_open_with_warning(app, db_session, login_user_row, caplog):
    """默认 fail-open：Redis 挂时登录走凭据校验（401），且必须记 WARNING 可观测。"""
    login_user_row("rate.victim")
    app.extensions["fde_api_redis"] = _BrokenRedis()
    client = app.test_client()

    with caplog.at_level(logging.WARNING):
        response = _post_login(client, "rate.victim", "10.9.9.9")

    assert response.status_code == 401, "Redis 故障不得伪装成限流"
    assert response.json["error"]["code"] == "invalid_credentials"
    assert any("rate limiter" in record.message.lower() for record in caplog.records), (
        "Redis 故障放行必须留下 WARNING（G7：不得静默）"
    )


def test_redis_down_fail_closed_when_configured(app, db_session, settings, login_user_row, caplog):
    """FDE_LOGIN_RATE_FAIL_CLOSED=1：Redis 挂时一律 429（从严模式），同样记 WARNING。"""
    login_user_row("rate.victim")
    app.extensions["fde_api_redis"] = _BrokenRedis()
    app.config["SETTINGS"] = settings.model_copy(update={"login_rate_fail_closed": True})
    client = app.test_client()

    with caplog.at_level(logging.WARNING):
        response = _post_login(client, "rate.victim", "10.9.9.9")

    assert response.status_code == 429
    assert response.json["error"]["code"] == "login_rate_limited"
    assert any("rate limiter" in record.message.lower() for record in caplog.records)


def test_proxyfix_uses_forwarded_client_ip(app, db_session, limited_client, login_user_row):
    """反代后限流键取 XFF 的真实客户端 IP，不再退化为 Docker 网桥网关固定值。"""
    login_user_row("rate.victim")
    redis = app.extensions["fde_api_redis"]

    response = _post_login(limited_client, "rate.victim", "172.21.0.1", xff="203.0.113.7")

    assert response.status_code == 401
    assert "auth:login_fail:rate.victim:203.0.113.7" in redis.counters
    assert "auth:login_fail:rate.victim:172.21.0.1" not in redis.counters


def test_proxyfix_takes_last_hop_of_forwarded_chain(app, db_session, limited_client, login_user_row):
    """多段 XFF 只取最后一个可信跳，防止用伪造前缀绕过限流。"""
    login_user_row("rate.victim")
    redis = app.extensions["fde_api_redis"]

    response = _post_login(
        limited_client, "rate.victim", "172.21.0.1", xff="198.51.100.1, 203.0.113.7"
    )

    assert response.status_code == 401
    assert "auth:login_fail:rate.victim:203.0.113.7" in redis.counters
    assert "auth:login_fail:rate.victim:198.51.100.1" not in redis.counters


def test_no_forwarded_header_falls_back_to_remote_addr(app, db_session, limited_client, login_user_row):
    """宿主回环运维请求无 XFF：仍按 REMOTE_ADDR 计数，值守/复位链路不受影响。"""
    login_user_row("rate.victim")
    redis = app.extensions["fde_api_redis"]

    response = _post_login(limited_client, "rate.victim", "172.21.0.1")

    assert response.status_code == 401
    assert "auth:login_fail:rate.victim:172.21.0.1" in redis.counters
