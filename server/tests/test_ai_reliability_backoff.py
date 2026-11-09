"""E6 AI 供应商退避回归钉。

不真实 sleep、不请求真实供应商：用 fake transport + 记录式 sleep 验证

- 429 按 ``Retry-After`` 退避（无该头时用有界指数退避）
- 超时可重试（此前第一次就抛）
- 401/403 等配置错误不盲目重试
- 重试次数有界（不无限重试）
"""
import pytest
import requests

from fde_api.ai.deepseek import DeepSeekClient, DeepSeekError


class _FakeResponse:
    def __init__(self, status_code: int, headers: dict | None = None, payload: dict | None = None):
        self.status_code = status_code
        self.headers = headers or {}
        self._payload = payload or {}

    def json(self):
        return self._payload


class _FakeSession:
    """按脚本返回响应/异常，记录调用次数。"""

    def __init__(self, script):
        self._script = list(script)
        self.calls = 0

    def post(self, url, **kwargs):
        self.calls += 1
        item = self._script.pop(0) if self._script else self._script
        if isinstance(item, Exception):
            raise item
        return item


def _client(script, sleeps):
    session = _FakeSession(script)
    client = DeepSeekClient(
        base_url="https://ai.example.com/v1",
        api_key="sk-test",
        model="test-model",
        timeout_seconds=5,
        session=session,
        sleep=sleeps.append,
    )
    return client, session


def test_rate_limit_retries_with_retry_after_delay():
    sleeps: list[float] = []
    client, session = _client(
        [
            _FakeResponse(429, {"Retry-After": "2"}),
            _FakeResponse(200, payload={"choices": [{"message": {"content": "{}"}}]}),
        ],
        sleeps,
    )

    client.complete_json(messages=[{"role": "user", "content": "x"}], request_id="r1", purpose="unit_test")

    assert session.calls == 2
    assert sleeps == [2.0]


def test_rate_limit_without_retry_after_uses_bounded_exponential_backoff():
    sleeps: list[float] = []
    client, session = _client(
        [
            _FakeResponse(429),
            _FakeResponse(429),
            _FakeResponse(200, payload={"choices": [{"message": {"content": "{}"}}]}),
        ],
        sleeps,
    )

    client.complete_json(messages=[{"role": "user", "content": "x"}], request_id="r2", purpose="unit_test")

    assert session.calls == 3
    assert sleeps == [1.0, 3.0]


def test_rate_limit_exhausts_bounded_retries_then_raises():
    sleeps: list[float] = []
    client, session = _client([_FakeResponse(429), _FakeResponse(429), _FakeResponse(429)], sleeps)

    with pytest.raises(DeepSeekError) as excinfo:
        client.complete_json(messages=[{"role": "user", "content": "x"}], request_id="r3", purpose="unit_test")

    assert excinfo.value.code == "ai_rate_limited"
    assert excinfo.value.retryable is True
    assert session.calls == 3
    assert len(sleeps) == 2


def test_timeout_is_retried_with_backoff():
    sleeps: list[float] = []
    client, session = _client(
        [
            requests.Timeout("slow"),
            _FakeResponse(200, payload={"choices": [{"message": {"content": "{}"}}]}),
        ],
        sleeps,
    )

    client.complete_json(messages=[{"role": "user", "content": "x"}], request_id="r4", purpose="unit_test")

    assert session.calls == 2
    assert sleeps == [1.0]


def test_timeout_exhausting_retries_raises_timeout_error():
    sleeps: list[float] = []
    client, session = _client(
        [requests.Timeout("slow"), requests.Timeout("slow"), requests.Timeout("slow")], sleeps
    )

    with pytest.raises(DeepSeekError) as excinfo:
        client.complete_json(messages=[{"role": "user", "content": "x"}], request_id="r5", purpose="unit_test")

    assert excinfo.value.code == "ai_timeout"
    assert session.calls == 3


def test_authentication_error_is_not_retried():
    sleeps: list[float] = []
    client, session = _client([_FakeResponse(401)], sleeps)

    with pytest.raises(DeepSeekError) as excinfo:
        client.complete_json(messages=[{"role": "user", "content": "x"}], request_id="r6", purpose="unit_test")

    assert excinfo.value.code == "ai_authentication_failed"
    assert excinfo.value.retryable is False
    assert session.calls == 1
    assert sleeps == []


def test_retry_after_is_capped_and_invalid_values_ignored():
    client, _session = _client([], [])
    assert client._retry_after_seconds(_FakeResponse(429, {"Retry-After": "600"})) == 30.0
    assert client._retry_after_seconds(_FakeResponse(429, {"Retry-After": "abc"})) is None
    assert client._retry_after_seconds(_FakeResponse(429, {"Retry-After": "-5"})) is None
    assert client._retry_after_seconds(_FakeResponse(429)) is None


# ---------------------------------------------------------------------------
# E5 降级链：主模型 → 备用模型 → 转人工
# ---------------------------------------------------------------------------

def _fallback_client(script, sleeps, fallback_model="backup-model"):
    session = _FakeSession(script)
    client = DeepSeekClient(
        base_url="https://ai.example.com/v1",
        api_key="sk-test",
        model="primary-model",
        timeout_seconds=5,
        session=session,
        sleep=sleeps.append,
        fallback_model=fallback_model,
    )
    return client, session


def test_primary_failure_falls_back_to_backup_model():
    sleeps: list[float] = []
    client, session = _fallback_client(
        [_FakeResponse(500), _FakeResponse(200, payload={"choices": [{"message": {"content": "{}"}}]})],
        sleeps,
    )

    result = client.complete_json(messages=[{"role": "user", "content": "x"}], request_id="f1", purpose="unit_test")

    assert result == {}
    assert session.calls == 2


def test_both_models_failing_hands_off_to_manual_processing():
    sleeps: list[float] = []
    client, session = _fallback_client([_FakeResponse(500), _FakeResponse(500)], sleeps)

    with pytest.raises(DeepSeekError) as excinfo:
        client.complete_json(messages=[{"role": "user", "content": "x"}], request_id="f2", purpose="unit_test")

    assert excinfo.value.code == "ai_manual_handoff"
    assert excinfo.value.retryable is False
    assert session.calls == 2


def test_non_retryable_errors_do_not_fall_back():
    sleeps: list[float] = []
    client, session = _fallback_client([_FakeResponse(401)], sleeps)

    with pytest.raises(DeepSeekError) as excinfo:
        client.complete_json(messages=[{"role": "user", "content": "x"}], request_id="f3", purpose="unit_test")

    assert excinfo.value.code == "ai_authentication_failed"
    assert session.calls == 1


def test_no_fallback_configured_keeps_original_error():
    sleeps: list[float] = []
    client, session = _fallback_client([_FakeResponse(500)], sleeps, fallback_model=None)

    with pytest.raises(DeepSeekError) as excinfo:
        client.complete_json(messages=[{"role": "user", "content": "x"}], request_id="f4", purpose="unit_test")

    assert excinfo.value.code == "ai_service_unavailable"
    assert excinfo.value.retryable is True
    assert session.calls == 1
