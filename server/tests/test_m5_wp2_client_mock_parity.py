"""V3.3 M5-WP2：Client/Mock 三新方法同形契约测试（集成契约 §9.1，D29/D31/D32/D33）。

- Client 侧（monkeypatch requests）：验证 GET impact / GET governance-summary（含
  as_of query）/ POST reconcile-references 的路径、params、json_body 与幂等键形状；
- Mock 侧：`_seed_m5_governance` 确定性种子上的 D32 分离指纹、D31 处置闭环与
  D33 七态对账分类；
- Client 透传保形：业务键集以 api-spec v1.3.0-m5 三 Schema required 显式快照
  为合同（IMPACT_KEYS/SUMMARY_KEYS/RECONCILE_KEYS）。
"""

from __future__ import annotations

import json
from typing import cast

import pytest

from fde_api.integrations.ontology_client import OntologyClient
from fde_api.integrations.ontology_mock import (
    MockOntologyAdapter,
    SEED_ONTOLOGY_ID,
    SEED_VERSION_ID,
)

API_KEY = "wb-api-key"
SIGNING_KEY = "wb-signing-key"
CTX = {"actor_id": "u1", "org_id": "org-1", "project_id": "proj-1"}

# 与 runtime api-spec v1.3.0-m5 对齐的三方法响应顶层键（golden parity 合同）
IMPACT_KEYS = {
    "_status",
    "ontology_id",
    "from_version_id",
    "from_version",
    "to_version_id",
    "to_version",
    "compat",
    "domain_schema_sha256_from",
    "domain_schema_sha256_to",
    "domain_schema_changed",
    "site_binding_sha256_from",
    "site_binding_sha256_to",
    "site_binding_changed",
    "breaking_changes",
    "additive_changes",
    "internal_cascades",
    "summary",
}
SUMMARY_KEYS = {
    "_status",
    "ontology_id",
    "ontology_version_id",
    "version",
    "snapshot_sha256",
    "domain_schema_sha256",
    "site_binding_sha256",
    "evaluated_at",
    "sla_threshold_hours",
    "unmapped_required_properties",
    "unbound_object_types",
    "unowned_or_unevidenced_rules",
    "candidate_disposition",
    "sla_aging",
    "compiler_telemetry",
    "gate_ready",
}
RECONCILE_KEYS = {
    "_status",
    "checked_at",
    "cutover_at",
    "total_checked",
    "valid_count",
    "anomaly_count",
    "passed",
    "results",
}


class _FakeResponse:
    def __init__(self, status: int, body: bytes = b"{}") -> None:
        self.status_code = status
        self.content = body
        self.text = body.decode()

    def json(self) -> dict[str, object]:
        return json.loads(self.content)  # type: ignore[no-any-return]


def _client() -> OntologyClient:
    return OntologyClient("http://runtime.test", API_KEY, SIGNING_KEY)


# ---------------------------------------------------------------- Client 形状


def test_client_get_version_impact_shape(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    def fake_request(method: str, url: str, **kwargs: object) -> _FakeResponse:
        captured["method"] = method
        captured["url"] = url
        captured["kwargs"] = kwargs
        return _FakeResponse(200, json.dumps({"compat": "compatible"}).encode())

    monkeypatch.setattr("requests.request", fake_request)
    body = _client().get_version_impact(
        **CTX, ontology_id=SEED_ONTOLOGY_ID, from_ver="1.0.0", to_ver="1.1.0"
    )
    assert captured["method"] == "GET"
    assert captured["url"] == (
        f"http://runtime.test/api/v1/ontologies/{SEED_ONTOLOGY_ID}"
        "/versions/1.0.0/impact/1.1.0"
    )
    assert body["_status"] == 200  # type: ignore[typeddict-item]


def test_client_get_version_governance_summary_as_of_query(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    def fake_request(method: str, url: str, **kwargs: object) -> _FakeResponse:
        captured["params"] = kwargs.get("params")
        return _FakeResponse(200, json.dumps({"gate_ready": True}).encode())

    monkeypatch.setattr("requests.request", fake_request)
    _client().get_version_governance_summary(
        **CTX,
        ontology_id=SEED_ONTOLOGY_ID,
        version_id=SEED_VERSION_ID,
        as_of="2026-11-14T00:00:00Z",
    )
    assert captured["params"] == {"as_of": "2026-11-14T00:00:00Z"}


def test_client_reconcile_references_post_body_and_idem(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    def fake_request(method: str, url: str, **kwargs: object) -> _FakeResponse:
        captured["method"] = method
        captured["url"] = url
        headers = cast("dict[str, str]", kwargs.get("headers") or {})
        captured["idem"] = headers.get("X-Idempotency-Key")
        captured["json_body"] = kwargs.get("json")
        return _FakeResponse(200, json.dumps({"total": 0, "valid": 0}).encode())

    monkeypatch.setattr("requests.request", fake_request)
    references = [
        {
            "ref_key": "ev-1",
            "ontology_id": SEED_ONTOLOGY_ID,
            "pinned_version_id": SEED_VERSION_ID,
        }
    ]
    _client().reconcile_references(
        **CTX, references=references, cutover_at="2026-11-14T00:00:00Z", idem_key="rec-1"
    )
    assert captured["method"] == "POST"
    assert captured["url"] == "http://runtime.test/api/v1/maintenance/reconcile-references"
    assert captured["idem"] == "rec-1"
    assert captured["json_body"] == {"references": references, "cutover_at": "2026-11-14T00:00:00Z"}


# ---------------------------------------------------------------- Mock 契约


def _mock() -> MockOntologyAdapter:
    return MockOntologyAdapter()


def test_mock_impact_d32_fingerprint_split_and_zero_handle_echo() -> None:
    """1.0.0 → 1.1.0 只改现场绑定：domain 指纹不变、site 指纹变化、零 connection_ref 回显。"""
    body = _mock().get_version_impact(
        **CTX, ontology_id=SEED_ONTOLOGY_ID, from_ver="1.0.0", to_ver="1.1.0"
    )
    assert set(body) == IMPACT_KEYS
    assert body["domain_schema_changed"] is False
    assert body["site_binding_changed"] is True
    assert body["compat"] == "compatible"
    text = json.dumps(body, ensure_ascii=False)
    assert "connection_ref" not in text and "env://" not in text  # S-07 零句柄回显


def test_mock_governance_summary_d31_disposition_keys() -> None:
    body = _mock().get_version_governance_summary(
        **CTX, ontology_id=SEED_ONTOLOGY_ID, version_id="ver-seed-1-1-0"
    )
    assert set(body) == SUMMARY_KEYS
    assert body["sla_threshold_hours"] == 72
    # 种子里留有一个未处置低置信度 draft 候选 → all_disposed=False（D31 口径）
    disposition = body["candidate_disposition"]
    assert disposition["all_disposed"] is False
    assert disposition["undisposed_count"] >= 1
    assert body["gate_ready"] is False
    # D32 双指纹出现在摘要
    assert body["domain_schema_sha256"] and body["site_binding_sha256"]
    # 嵌套键对齐 runtime compute_sla_aging / compiler_telemetry
    assert set(body["sla_aging"]) == {
        "threshold_hours", "pending_review_count", "overdue_count", "overdue",
        "oldest_pending_age_hours",
    }
    assert set(body["compiler_telemetry"]) == {
        "unmodified_accept_rate", "accepted_count", "unmodified_count", "rejected_count",
    }
    assert set(body["candidate_disposition"]) == {
        "tracked_count", "disposed_count", "undisposed_count", "undisposed", "all_disposed",
    }


def test_mock_reconcile_reference_states() -> None:
    """D33 七态抽样：valid / orphan_version / tenant_mismatch。"""
    mock = _mock()
    references = [
        {
            "ref_key": "r-valid",
            "ontology_id": SEED_ONTOLOGY_ID,
            "pinned_version_id": SEED_VERSION_ID,
        },
        {
            "ref_key": "r-orphan-ver",
            "ontology_id": SEED_ONTOLOGY_ID,
            "pinned_version_id": "ver-not-exist",
        },
        {
            "ref_key": "r-tenant",
            "ontology_id": "ont-not-seeded",
            "pinned_version_id": "ver-any",
        },
    ]
    body = mock.reconcile_references(**CTX, references=references, idem_key="rec-mock-1")
    assert set(body) == RECONCILE_KEYS
    assert body["total_checked"] == 3
    assert body["valid_count"] == 1 and body["anomaly_count"] == 2
    assert body["passed"] is False
    by_key = {item["ref_key"]: item["status"] for item in body["results"]}
    assert by_key["r-valid"] == "valid"
    assert by_key["r-orphan-ver"] == "orphan_version"
    assert by_key["r-tenant"] == "tenant_mismatch"
    # 条目四键对齐 runtime（ref_key/ontology_id/pinned_version_id/status）
    assert set(body["results"][0]) == {"ref_key", "ontology_id", "pinned_version_id", "status"}


# ---------------------------------------------------------------- Golden parity


def test_client_passthrough_preserves_contract_keys(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Client 对契约响应只透传不改写：以 Mock 响应为 fixture，业务键集逐位保留
    （跨仓机械闸 = ontology-service test_m4_1_contract_parity + WP4 E2E；本侧键集
    合同为 api-spec v1.3.0-m5 三 Schema required 的显式快照，见文件头常量注释）。"""
    mock = _mock()
    client = _client()
    cases: list[tuple[str, dict[str, object], dict[str, object]]] = [
        (
            "get_version_impact",
            mock.get_version_impact(
                **CTX, ontology_id=SEED_ONTOLOGY_ID, from_ver="1.0.0", to_ver="1.1.0"
            ),
            {"ontology_id": SEED_ONTOLOGY_ID, "from_ver": "1.0.0", "to_ver": "1.1.0"},
        ),
        (
            "get_version_governance_summary",
            mock.get_version_governance_summary(
                **CTX, ontology_id=SEED_ONTOLOGY_ID, version_id="ver-seed-1-1-0"
            ),
            {"ontology_id": SEED_ONTOLOGY_ID, "version_id": "ver-seed-1-1-0"},
        ),
        (
            "reconcile_references",
            mock.reconcile_references(
                **CTX,
                references=[
                    {
                        "ref_key": "r1",
                        "ontology_id": SEED_ONTOLOGY_ID,
                        "pinned_version_id": SEED_VERSION_ID,
                    }
                ],
                idem_key="k",
            ),
            {
                "references": [
                    {
                        "ref_key": "r1",
                        "ontology_id": SEED_ONTOLOGY_ID,
                        "pinned_version_id": SEED_VERSION_ID,
                    }
                ],
                "idem_key": "k",
            },
        ),
    ]
    for method_name, mock_body, call_kwargs in cases:
        monkeypatch.setattr(
            "requests.request",
            lambda m, u, _body=mock_body, **kw: _FakeResponse(
                200, json.dumps(_body).encode()
            ),
        )
        via_client = getattr(client, method_name)(**CTX, **call_kwargs)
        via_client.pop("_status", None)
        mock_keys = set(mock_body) - {"_status"}
        assert set(via_client) == mock_keys, method_name
    monkeypatch.undo()
