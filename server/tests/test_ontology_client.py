"""OntologyClient 单元测试（纯 mock，不依赖 MySQL/runtime）。"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
from urllib.parse import urlparse

import pytest

from fde_api.integrations.ontology_client import (
    OntologyAuthError,
    OntologyClient,
    OntologyClientError,
    OntologyConflict,
    OntologyUnavailable,
    build_context_header,
)

API_KEY = "wb-api-key"
SIGNING_KEY = "wb-signing-key"


def _verify_header(header: str, signing_key: str) -> dict[str, object]:
    head, sig = header.split(".", 1)
    expected = hmac.new(
        signing_key.encode(), head.encode(), hashlib.sha256
    ).digest()
    padded = sig + "=" * (-len(sig) % 4)
    assert hmac.compare_digest(base64.urlsafe_b64decode(padded), expected)
    raw = base64.urlsafe_b64decode(head + "=" * (-len(head) % 4))
    return json.loads(raw)  # type: ignore[no-any-return]


def test_context_header_roundtrip() -> None:
    header = build_context_header("u1", "org1", "p1", SIGNING_KEY, ts=1700000000, nonce="abcd1234")
    payload = _verify_header(header, SIGNING_KEY)
    assert payload["actor_id"] == "u1"
    assert payload["org_id"] == "org1"
    assert payload["project_id"] == "p1"
    assert payload["ts"] == 1700000000
    assert payload["nonce"] == "abcd1234"


def test_context_header_wrong_key_fails() -> None:
    header = build_context_header("u1", "org1", "p1", "other-key")
    with pytest.raises(AssertionError):
        _verify_header(header, SIGNING_KEY)


class _FakeResponse:
    def __init__(self, status: int, body: bytes = b"{}") -> None:
        self.status_code = status
        self.content = body
        self.text = body.decode()

    def json(self) -> dict[str, object]:
        return json.loads(self.content)


def _client() -> OntologyClient:
    return OntologyClient("http://runtime.test", API_KEY, SIGNING_KEY)


def test_submit_candidates_payload_and_idempotency(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    def fake_request(method: str, url: str, **kwargs: object) -> _FakeResponse:
        captured["method"] = method
        captured["url"] = url
        captured["headers"] = kwargs.get("headers")
        captured["json"] = kwargs.get("json")
        return _FakeResponse(201, json.dumps({"id": "cs-1"}).encode())

    monkeypatch.setattr("fde_api.integrations.ontology_client.requests.request", fake_request)
    client = _client()
    items = [{"op": "create", "entity_type": "object_types", "entity_key": "stage", "payload": {}}]
    first = client.submit_candidates(
        actor_id="u1", org_id="org1", project_id="p1",
        ontology_id="ont-1", title="候选", items=items, captured_from="discovery:doc-9",
    )
    assert first["id"] == "cs-1"
    headers = captured["headers"]
    assert isinstance(headers, dict)
    assert headers["X-API-Key"] == API_KEY
    payload = _verify_header(headers["X-FDE-Context"], SIGNING_KEY)
    assert payload["org_id"] == "org1"
    body = captured["json"]
    assert isinstance(body, dict)
    assert body["captured_from"] == "discovery:doc-9"
    assert body["proposed_json"] == items
    # 内容寻址幂等：同 items 再提交 → 同幂等键
    idem1 = headers["X-Idempotency-Key"]
    client.submit_candidates(
        actor_id="u1", org_id="org1", project_id="p1",
        ontology_id="ont-1", title="候选", items=items, captured_from="discovery:doc-9",
    )
    assert isinstance(captured["headers"], dict)
    assert captured["headers"]["X-Idempotency-Key"] == idem1


def test_health_false_when_unreachable(monkeypatch: pytest.MonkeyPatch) -> None:
    import requests as _requests

    def fake_get(*args: object, **kwargs: object) -> object:
        raise _requests.ConnectionError("refused")

    monkeypatch.setattr("fde_api.integrations.ontology_client.requests.get", fake_get)
    assert _client().health() is False


def test_request_unavailable_maps_to_ontology_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    import requests as _requests

    def fake_request(*args: object, **kwargs: object) -> object:
        raise _requests.ConnectionError("refused")

    monkeypatch.setattr("fde_api.integrations.ontology_client.requests.request", fake_request)
    with pytest.raises(OntologyUnavailable):
        _client().get_change_set(actor_id="u", org_id="o", project_id="p", change_set_id="cs")


def test_5xx_maps_to_client_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_request(*args: object, **kwargs: object) -> _FakeResponse:
        return _FakeResponse(502)

    monkeypatch.setattr("fde_api.integrations.ontology_client.requests.request", fake_request)
    with pytest.raises(OntologyClientError):
        _client().get_change_set(actor_id="u", org_id="o", project_id="p", change_set_id="cs")


def test_409_conflict_maps_to_ontology_conflict(monkeypatch: pytest.MonkeyPatch) -> None:
    """契约 §2-5：409 base_conflict 分型（并发/漂移 → 业务层提示重试）。"""

    def fake_request(*args: object, **kwargs: object) -> _FakeResponse:
        return _FakeResponse(409, json.dumps({"code": "base_conflict"}).encode())

    monkeypatch.setattr("fde_api.integrations.ontology_client.requests.request", fake_request)
    with pytest.raises(OntologyConflict) as excinfo:
        _client().get_change_set(actor_id="u", org_id="o", project_id="p", change_set_id="cs")
    assert excinfo.value.body["code"] == "base_conflict"


def test_401_403_map_to_auth_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """契约 §2-5：401/403 分型（配置错误告警，不伪装领域错误）。"""
    for status in (401, 403):
        payload = json.dumps({"message": "denied"}).encode()

        def _make(_s: int = status, _body: bytes = payload) -> object:
            def fake_request(*args: object, **kwargs: object) -> _FakeResponse:
                return _FakeResponse(_s, _body)

            return fake_request

        monkeypatch.setattr(
            "fde_api.integrations.ontology_client.requests.request", _make()
        )
        with pytest.raises(OntologyAuthError):
            _client().get_change_set(actor_id="u", org_id="o", project_id="p", change_set_id="cs")


def test_4xx_passthrough_with_status(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_request(*args: object, **kwargs: object) -> _FakeResponse:
        return _FakeResponse(400, json.dumps({"code": "validation_failed"}).encode())

    monkeypatch.setattr("fde_api.integrations.ontology_client.requests.request", fake_request)
    body = _client().get_change_set(actor_id="u", org_id="o", project_id="p", change_set_id="cs")
    assert body["_status"] == 400
    assert body["code"] == "validation_failed"


def test_non_dict_body_wrapped(monkeypatch: pytest.MonkeyPatch) -> None:
    """runtime 返回数组/标量体不得 TypeError（评审 W-D）。"""

    def fake_request(*args: object, **kwargs: object) -> _FakeResponse:
        return _FakeResponse(200, json.dumps([1, 2]).encode())

    monkeypatch.setattr("fde_api.integrations.ontology_client.requests.request", fake_request)
    body = _client().get_change_set(actor_id="u", org_id="o", project_id="p", change_set_id="cs")
    assert body["_status"] == 200
    assert body["raw"] == [1, 2]


def test_approval_idem_deterministic_and_decision_sensitive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ap- 幂等键含 decision：异决定重试不得复放首票；同参重试同键（评审 W-D）。"""
    captured: list[str] = []

    def fake_request(method: str, url: str, **kwargs: object) -> _FakeResponse:
        headers = kwargs.get("headers")
        assert isinstance(headers, dict)
        captured.append(headers["X-Idempotency-Key"])
        return _FakeResponse(200, b"{}")

    monkeypatch.setattr("fde_api.integrations.ontology_client.requests.request", fake_request)
    client = _client()
    kw: dict[str, object] = {
        "actor_id": "u",
        "org_id": "o",
        "project_id": "p",
        "change_set_id": "cs-9",
        "role": "business_owner",
    }
    client.approve_change_set(**kw, decision="approved")  # type: ignore[arg-type]
    client.approve_change_set(**kw, decision="approved")  # type: ignore[arg-type]
    client.approve_change_set(**kw, decision="rejected")  # type: ignore[arg-type]
    assert captured[0] == captured[1]
    assert captured[0] != captured[2]
    assert len(captured[0]) <= 64


def test_long_idem_key_clamped_not_truncated() -> None:
    """超 64 字符键按 sha256 收敛（截断会使不同长键互撞，评审 W-D）；
    防御性兜底——现有方法的键长恒 ≤64。"""
    client = _client()
    headers = client._headers("u", "o", "p", "x" * 100)
    key = headers["X-Idempotency-Key"]
    assert len(key) <= 64
    assert key != "x" * 100
    short = client._headers("u", "o", "p", "short-key")
    assert short["X-Idempotency-Key"] == "short-key"


def test_health_true_on_200(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_get(url: str, **kwargs: object) -> _FakeResponse:
        assert urlparse(url).path == "/healthz"
        return _FakeResponse(200)

    monkeypatch.setattr("fde_api.integrations.ontology_client.requests.get", fake_get)
    assert _client().health() is True


def test_unavailable_message_carries_no_intranet_url(monkeypatch: pytest.MonkeyPatch) -> None:
    """Vex 13:22 M6 放行条件(a)（S-07 边角闭环）：OntologyUnavailable 文案禁回显内网 URL。

    该消息曾带 ``f"{url}"`` 并经 integrations/service.py 管理面 5 处 ``{exc}`` 透出至
    报错面；修复后拓扑细节只留在异常链（__cause__，服务端日志可见），不进文案。
    """
    import requests as _requests

    intranet = "http://10.203.7.42:8902"
    client = OntologyClient(intranet, API_KEY, SIGNING_KEY)

    def fake_request(*args: object, **kwargs: object) -> object:
        raise _requests.ConnectionError("refused")

    monkeypatch.setattr("fde_api.integrations.ontology_client.requests.request", fake_request)
    with pytest.raises(OntologyUnavailable) as excinfo:
        client.get_change_set(actor_id="u", org_id="o", project_id="p", change_set_id="cs")
    assert intranet not in str(excinfo.value)
    assert "10.203.7.42" not in str(excinfo.value)


def test_dry_validate_change_set_payload_and_no_idempotency(monkeypatch: pytest.MonkeyPatch) -> None:
    """AF0-C1：纯预检——路径/请求体按 1.3.6-af0 契约；零副作用无幂等键。"""
    captured: dict[str, object] = {}

    def fake_request(method: str, url: str, **kwargs: object) -> _FakeResponse:
        captured["method"] = method
        captured["url"] = url
        captured["headers"] = kwargs.get("headers")
        captured["json"] = kwargs.get("json")
        return _FakeResponse(200, json.dumps(
            {"verdict": "violations", "violations": [{"code": "validation_failed"}],
             "conflicting_entities": []},
        ).encode())

    monkeypatch.setattr("fde_api.integrations.ontology_client.requests.request", fake_request)
    client = _client()
    candidate_items: list[dict[str, object]] = [
        {"op": "create", "entity_type": "object_types", "entity_key": "batch", "payload": {}},
    ]
    out = client.dry_validate_change_set(
        actor_id="u1", org_id="org1", project_id="p1",
        ontology_id="ont-1", version_id="1.0.0",
        proposed_json=candidate_items,
    )
    assert out["verdict"] == "violations"
    assert out["_status"] == 200
    assert captured["method"] == "POST"
    assert isinstance(captured["url"], str) and captured["url"].endswith(
        "/api/v1/mcp/tools/dry_validate_change_set"
    )
    headers = captured["headers"]
    assert isinstance(headers, dict)
    # 零副作用契约：不要求 X-Idempotency-Key（1.3.6-af0 头注「刻意差异」）
    assert "X-Idempotency-Key" not in headers
    body = captured["json"]
    assert isinstance(body, dict)
    assert body["ontology_id"] == "ont-1"
    assert body["pinned_version"] == "1.0.0"
    # WP1 收口批对齐实装语义：候选条目数组（与 ChangeSet.proposed_json 同形）
    assert body["proposed_json"] == candidate_items
