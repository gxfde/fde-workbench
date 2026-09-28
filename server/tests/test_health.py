def test_liveness(client):
    response = client.get("/api/v1/health/live")

    assert response.status_code == 200
    assert response.json == {"data": {"status": "ok"}, "error": None}


def test_unknown_route_uses_error_envelope(client):
    response = client.get("/api/v1/not-found")

    assert response.status_code == 404
    assert response.json == {
        "data": None,
        "error": {
            "code": "not_found",
            "message": "请求的接口不存在，请检查客户端与服务端版本是否一致。",
            "details": None,
        },
    }


def test_unexpected_exception_uses_safe_complete_error_envelope(client):
    @client.application.get("/api/v1/test-unexpected-error")
    def raise_unexpected_error():
        raise RuntimeError("test-only secret")

    response = client.get("/api/v1/test-unexpected-error")

    assert response.status_code == 500
    assert response.json == {
        "data": None,
        "error": {
            "code": "internal_error",
            "message": "系统发生异常，请稍后重试。",
            "details": None,
        },
    }
    assert "test-only secret" not in response.get_data(as_text=True)


def test_readiness_reports_redis_degraded_without_failing(monkeypatch, client):
    monkeypatch.setattr("fde_api.health.routes.redis_ping", lambda: False)

    response = client.get("/api/v1/health/ready")

    assert response.status_code == 200
    assert response.json["data"]["mysql"] == "ok"
    assert response.json["data"]["redis"] == "degraded"


def test_readiness_uses_service_unavailable_envelope_when_mysql_is_down(
    monkeypatch, client
):
    def unavailable_mysql():
        raise RuntimeError("database unavailable")

    monkeypatch.setattr("fde_api.health.routes.db.ping", unavailable_mysql)

    response = client.get("/api/v1/health/ready")

    assert response.status_code == 503
    assert response.json == {
        "data": None,
        "error": {
            "code": "service_unavailable",
            "message": "MySQL is unavailable.",
            "details": None,
        },
    }


def test_readiness_degrades_when_redis_connection_errors(monkeypatch, client):
    def unavailable_redis():
        raise RuntimeError("redis unavailable")

    monkeypatch.setattr("fde_api.health.routes.redis_client.ping", unavailable_redis)

    response = client.get("/api/v1/health/ready")

    assert response.status_code == 200
    assert response.json["data"]["mysql"] == "ok"
    assert response.json["data"]["redis"] == "degraded"


def test_redis_client_uses_short_connect_and_socket_timeouts(monkeypatch, test_settings):
    from flask import Flask

    from fde_api.extensions import RedisClient

    captured = {}

    def capture_from_url(url, **kwargs):
        captured.update(url=url, **kwargs)
        return object()

    monkeypatch.setattr("fde_api.extensions.Redis.from_url", capture_from_url)
    app = Flask(__name__)

    RedisClient().init_app(app, test_settings)

    assert captured["socket_connect_timeout"] <= 1
    assert captured["socket_timeout"] <= 1
