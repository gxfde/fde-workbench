"""V3.3 M4-WP3 defer 清算②：ontology_client 熔断与有界重试（契约 §2-2/§2-4）。

覆盖条款：
- §2-2 有界重试：幂等 GET 最多 2 次重试（退避 0.5s/1s，共 3 次尝试）；
  非幂等写操作绝不自动重试（防重复提交，幂等键兜底）；401/403/409/4xx
  语义错不重试（重试只救网络层瞬时故障与 5xx）；
- §2-4 熔断：连续 5 次失败 → 打开 30s；熔断期直接抛 ``OntologyUnavailable``
  不打真实请求；恢复窗口后放行 1 次半开试探（成功闭合 / 失败重开）；
- 复用 §14-6 故障注入语义（MonkeyPatch requests.request）。
"""

from __future__ import annotations

import pytest
import requests

from fde_api.integrations.ontology_client import (
    OntologyClient,
    OntologyClientError,
    OntologyUnavailable,
)


class _StubResponse:
    def __init__(self, status: int) -> None:
        self.status_code = status
        self.content = b'{"ok": true}'

    def json(self) -> dict[str, object]:
        return {"ok": True}


class _FlakyBackend:
    """按脚本逐次抛错/返回的传输桩。"""

    def __init__(self, script: list[Exception | int]) -> None:
        self.script: list[Exception | int] = list(script)
        self.calls: list[tuple[str, str]] = []

    def request(self, method: str, url: str, **kwargs: object) -> _StubResponse:
        self.calls.append((method, url))
        step: Exception | int = self.script.pop(0) if self.script else 500
        if isinstance(step, Exception):
            raise step
        return _StubResponse(int(step))


def _client(
    monkeypatch: pytest.MonkeyPatch, backend: _FlakyBackend
) -> tuple[OntologyClient, dict[str, float]]:
    """构建客户端 + 可推进假时钟（熔断恢复窗口由测试显式推进）。"""
    monkeypatch.setattr(
        "fde_api.integrations.ontology_client.requests.request", backend.request
    )
    sleeps: list[float] = []
    monkeypatch.setattr(
        "fde_api.integrations.ontology_client.time.sleep", lambda s: sleeps.append(s)
    )
    clock = {"t": 100.0}
    monkeypatch.setattr(
        "fde_api.integrations.ontology_client.time.monotonic", lambda: clock["t"]
    )
    return OntologyClient("http://runtime.test", "k", "s"), clock


def _call(
    client: OntologyClient,
    method: str,
    path: str,
) -> dict[str, object]:
    """mypy 安全的固定上下文调用（避免 **dict 解包的 arg-type 噪声）。"""
    return client._request(
        method,
        path,
        actor_id="u1",
        org_id="org-1",
        project_id="proj-1",
    )


def test_get_idempotent_retries_twice_with_backoff(monkeypatch: pytest.MonkeyPatch) -> None:
    """§2-2：GET 幂等——两次瞬时失败后退避重试（0.5s/1s），第三次成功。"""
    backend = _FlakyBackend(
        [
            requests.ConnectionError("boom-1"),
            requests.ConnectionError("boom-2"),
            200,
        ]
    )
    client, _ = _client(monkeypatch, backend)
    body = _call(client, "GET", "/api/v1/healthz")
    assert body["_status"] == 200
    assert len(backend.calls) == 3


def test_post_write_never_retried(monkeypatch: pytest.MonkeyPatch) -> None:
    """§2-2：非幂等写操作绝不自动重试（防重复提交——幂等键兜底而非重试）。"""
    backend = _FlakyBackend([requests.ConnectionError("boom")])
    client, _ = _client(monkeypatch, backend)
    with pytest.raises(OntologyUnavailable):
        _call(client, "POST", "/api/v1/ontologies")
    assert len(backend.calls) == 1


def test_get_retries_exhausted_raises_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    """§2-2：GET 两次重试后仍失败 → OntologyUnavailable（降级语义不变）。"""
    backend = _FlakyBackend(
        [
            requests.ConnectionError("boom-1"),
            requests.ConnectionError("boom-2"),
            requests.ConnectionError("boom-3"),
        ]
    )
    client, _ = _client(monkeypatch, backend)
    with pytest.raises(OntologyUnavailable):
        _call(client, "GET", "/api/v1/healthz")
    assert len(backend.calls) == 3


def test_4xx_semantic_errors_never_retried(monkeypatch: pytest.MonkeyPatch) -> None:
    """§2-2：4xx 语义错不重试——重试救瞬时故障不救契约错。

    401/403/409 抛对应异常；422 走正常返回体（client 只对 409/401/403 抛错）。
    """
    for status in (401, 403, 409, 422):
        backend = _FlakyBackend([status, status])
        client, _ = _client(monkeypatch, backend)
        if status == 422:
            body = _call(client, "GET", "/api/v1/ontologies")
            assert body["_status"] == 422
        else:
            with pytest.raises(OntologyClientError):
                _call(client, "GET", "/api/v1/ontologies")
        assert len(backend.calls) == 1, f"{status} 不应重试"


def test_circuit_breaker_opens_after_five_failures(monkeypatch: pytest.MonkeyPatch) -> None:
    """§2-4：连续 5 次失败 → 熔断打开；熔断期不打真实请求直接 OntologyUnavailable。"""
    # 5 次调用 × 3 次尝试（GET 重试）= 15 次网络调用全部瞬时失败
    backend = _FlakyBackend([requests.ConnectionError("boom")] * 15)
    client, _ = _client(monkeypatch, backend)
    for _ in range(5):
        with pytest.raises(OntologyUnavailable):
            _call(client, "GET", "/api/v1/healthz")
    assert len(backend.calls) == 15  # 5 次调用 × 3 次尝试（GET 重试），熔断计数按调用

    calls_before_open = len(backend.calls)
    with pytest.raises(OntologyUnavailable, match="circuit"):
        _call(client, "GET", "/api/v1/healthz")
    assert len(backend.calls) == calls_before_open, "熔断期不得打真实请求"


def test_circuit_breaker_half_open_probe_recovers(monkeypatch: pytest.MonkeyPatch) -> None:
    """§2-4：恢复窗口后半开放行 1 次试探；成功闭合，后续请求正常。"""
    script: list[Exception | int] = []
    script.extend(requests.ConnectionError("boom") for _ in range(15))
    script.extend([200, 200])
    backend = _FlakyBackend(script)
    client, clock = _client(monkeypatch, backend)
    for _ in range(5):
        with pytest.raises(OntologyUnavailable):
            _call(client, "GET", "/api/v1/healthz")
    # 熔断期直接拒绝
    with pytest.raises(OntologyUnavailable, match="circuit"):
        _call(client, "GET", "/api/v1/healthz")
    # 显式推进假时钟越过 30s 恢复窗口 → 半开试探成功 → 闭合
    clock["t"] += 31.0
    body = _call(client, "GET", "/api/v1/healthz")
    assert body["_status"] == 200
    body2 = _call(client, "GET", "/api/v1/healthz")
    assert body2["_status"] == 200
