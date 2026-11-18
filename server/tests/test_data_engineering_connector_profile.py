"""AF2-WP1 第二批：连接器侧 DB 内省画像消费（15 号 §2 D5，2026-11-18 P1「全部批准」）。

消费链：``OntologyClient.introspect_data_source``（出站方法，api-spec
1.3.8-af2）→ ``MockOntologyAdapter`` 双胞胎（同契约无网测试）→
``create_connector_profile`` 落既有 ``data_profiles``（``source_kind =
file | connector`` + 版本/快照锚）。

纪律钉：
- 掩码出边界在 ontology-service 连接器沙箱内完成（单一真身）；workbench
  只透传统计 + 掩码样本，不二次脱敏（词表真身=validation.SENSITIVE_PK_RE，
  两仓 SHA 钉对齐，04 §3.2）；
- FK = catalog 硬证据 → ``relation_candidates``（``evidence=fk_catalog``，
  status 恒 ``candidate``，无翻产通道，03 §77）；
- 非项目成员 404（S-01 不泄露存在性）；本体未启用 fail-closed 503（§15
  红线：flag 关时不产生任何出站调用）。
"""
from __future__ import annotations

import uuid
from datetime import date

import pytest

from conftest import INITIAL_PASSWORD as PASSWORD
from fde_api.auth.models import User
from fde_api.auth.passwords import hash_password
from fde_api.auth.tokens import issue_access_token
from fde_api.data_engineering.models import DataProfile
from fde_api.data_engineering.service import DataEngineeringError, create_connector_profile
from fde_api.integrations.ontology_client import OntologyClient
from fde_api.integrations.ontology_mock import (
    SEED_ONTOLOGY_ID,
    SEED_VERSION_ID,
    MockOntologyAdapter,
)
from fde_api.workbench.models import Project

from tests.test_data_engineering_profile import _make_project, _make_user

CTX = {"actor_id": "u1", "org_id": "org-1", "project_id": "proj-1"}



# ---- 出站 Client 形状（路径/幂等键，api-spec 1.3.8-af2 合同）--------------------


class _FakeResponse:
    def __init__(self, status: int, body: bytes) -> None:
        self.status_code = status
        self.content = body
        self.text = body.decode()

    def json(self) -> dict[str, object]:
        import json

        return json.loads(self.content)  # type: ignore[no-any-return]


def test_client_introspect_shape(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    def fake_request(method: str, url: str, **kwargs: object) -> _FakeResponse:
        captured["method"] = method
        captured["url"] = url
        captured["kwargs"] = kwargs
        return _FakeResponse(200, b'{"tables": {}, "_status": 200}')

    monkeypatch.setattr("requests.request", fake_request)
    body = OntologyClient("http://runtime.test", "k", "s").introspect_data_source(
        **CTX,  # type: ignore[arg-type]
        ontology_id=SEED_ONTOLOGY_ID,
        version_id=SEED_VERSION_ID,
        data_source_key="mes_sql",
    )
    assert captured["method"] == "POST"
    assert captured["url"] == (
        f"http://runtime.test/api/v1/ontologies/{SEED_ONTOLOGY_ID}"
        f"/versions/{SEED_VERSION_ID}/data-sources/mes_sql/introspect"
    )
    assert body["_status"] == 200  # type: ignore[typeddict-item]


# ---- Mock 双胞胎（同契约无网）--------------------------------------------------


def test_mock_introspect_contract() -> None:
    adapter = MockOntologyAdapter()
    out = adapter.introspect_data_source(
        **CTX,  # type: ignore[arg-type]
        ontology_id=SEED_ONTOLOGY_ID,
        version_id=SEED_VERSION_ID,
        data_source_key="mes_sql",
    )
    assert out["_status"] == 200
    # 快照锚五件齐（画像钉版本，D5 ③）
    for key in ("ontology_id", "ontology_version_id", "version", "snapshot_sha256", "data_source_key"):
        assert key in out
    assert out["snapshot_sha256"]
    tables = out["tables"]
    wo = tables["work_order"]
    assert wo["foreign_keys"] == [
        {"column": "eq_id", "references_table": "equipment", "references_column": "eq_id"}
    ]
    assert wo["row_sample"] is not None
    # 未绑定表只出结构不出样本（最小暴露）
    assert tables["raw_archive"]["row_sample"] is None
    # 掩码样本无敏感原文（沙箱侧已脱敏）
    assert "tok-alpha" not in str(out)


def test_mock_introspect_unknown_source_404() -> None:
    adapter = MockOntologyAdapter()
    out = adapter.introspect_data_source(
        **CTX,  # type: ignore[arg-type]
        ontology_id=SEED_ONTOLOGY_ID,
        version_id=SEED_VERSION_ID,
        data_source_key="no_such_ds",
    )
    assert out["_status"] == 404
    assert out["code"] == "not_found"


# ---- 服务层：落库锚 + FK 硬证据候选 + 审计 ---------------------------------------


def test_create_connector_profile_persists_with_anchor(db_session) -> None:
    leader = _make_user(db_session, "project_lead")
    project = _make_project(db_session, leader)

    payload = create_connector_profile(
        actor=leader,
        project_id=project.id,
        ontology_id=SEED_ONTOLOGY_ID,
        version_id=SEED_VERSION_ID,
        data_source_key="mes_sql",
        org_id="org-1",
        adapter=MockOntologyAdapter(),
    )
    assert payload["source_kind"] == "connector"
    assert payload["source_name"] == "connector:mes_sql"
    assert payload["ontology_id"] == SEED_ONTOLOGY_ID
    assert payload["ontology_version_id"] == SEED_VERSION_ID
    assert payload["snapshot_sha256"]
    # FK 硬证据 → 关系候选（evidence=fk_catalog，status 恒 candidate 无翻产）
    candidates = payload["relation_candidates"]
    assert candidates == [
        {
            "left_table": "work_order",
            "right_table": "equipment",
            "left_column": "eq_id",
            "right_column": "eq_id",
            "basis": "fk_catalog",
            "status": "candidate",
        }
    ]
    # 掩码样本透传（不二次脱敏）
    assert payload["samples"]["equipment"]["rows_scanned"] >= 1

    row = db_session.get(DataProfile, payload["id"])
    assert row is not None
    assert row.source_kind == "connector"
    assert row.snapshot_sha256 == payload["snapshot_sha256"]


def test_create_connector_profile_maps_runtime_errors(db_session) -> None:
    leader = _make_user(db_session, "project_lead")
    project = _make_project(db_session, leader)
    adapter = MockOntologyAdapter()

    with pytest.raises(DataEngineeringError) as not_found:
        create_connector_profile(
            actor=leader,
            project_id=project.id,
            ontology_id=SEED_ONTOLOGY_ID,
            version_id=SEED_VERSION_ID,
            data_source_key="no_such_ds",
            org_id="org-1",
            adapter=adapter,
        )
    assert not_found.value.status == 404


def test_create_connector_profile_requires_membership(db_session) -> None:
    leader = _make_user(db_session, "project_lead")
    project = _make_project(db_session, leader)
    outsider = _make_user(db_session, "fde_engineer")

    with pytest.raises(DataEngineeringError) as forbidden:
        create_connector_profile(
            actor=outsider,
            project_id=project.id,
            ontology_id=SEED_ONTOLOGY_ID,
            version_id=SEED_VERSION_ID,
            data_source_key="mes_sql",
            org_id="org-1",
            adapter=MockOntologyAdapter(),
        )
    assert forbidden.value.status == 404  # S-01 不泄露存在性


# ---- 回归：资料侧画像 source_kind=file -----------------------------------------


def test_file_profile_default_source_kind(db_session) -> None:
    leader = _make_user(db_session, "project_lead")
    project = _make_project(db_session, leader)
    row = DataProfile(
        project_id=project.id,
        source_name="samples.csv",
        input_sha256="a" * 64,
        created_by_user_id=leader.id,
    )
    db_session.add(row)
    db_session.commit()
    assert row.source_kind == "file"  # 既有资料侧画像语义不变
    snap = row.snapshot()
    assert snap["source_kind"] == "file"


# ---- 路由层：fail-closed 与 201 端到端 ------------------------------------------


def _headers(user: User, settings) -> dict[str, str]:
    return {"Authorization": f"Bearer {issue_access_token(user, settings)}"}


def test_route_ontology_profile_fail_closed_disabled(client, db_session, settings, monkeypatch) -> None:
    leader = _make_user(db_session, "project_lead")
    project = _make_project(db_session, leader)
    monkeypatch.setattr(settings, "ontology_enabled", False, raising=False)

    response = client.post(
        f"/api/v1/projects/{project.id}/ontology-data-profiles",
        json={"ontology_id": SEED_ONTOLOGY_ID, "version_id": SEED_VERSION_ID,
              "data_source_key": "mes_sql", "org_id": "org-1"},
        headers=_headers(leader, settings),
    )
    assert response.status_code == 503
    # flag 关 = 零出站调用（fail-closed，§15）：画像行未落库
    assert db_session.query(DataProfile).count() == 0


def test_route_ontology_profile_created(client, db_session, settings, monkeypatch) -> None:
    leader = _make_user(db_session, "project_lead")
    project = _make_project(db_session, leader)
    monkeypatch.setattr(settings, "ontology_enabled", True, raising=False)
    monkeypatch.setattr(
        "fde_api.data_engineering.service._adapter_from_app",
        lambda: MockOntologyAdapter(),
    )

    response = client.post(
        f"/api/v1/projects/{project.id}/ontology-data-profiles",
        json={"ontology_id": SEED_ONTOLOGY_ID, "version_id": SEED_VERSION_ID,
              "data_source_key": "mes_sql", "org_id": "org-1"},
        headers=_headers(leader, settings),
    )
    assert response.status_code == 201, response.get_data(as_text=True)
    payload = response.get_json()["data"]
    assert payload["source_kind"] == "connector"
    assert payload["snapshot_sha256"]

    # body 缺字段 → 400
    bad = client.post(
        f"/api/v1/projects/{project.id}/ontology-data-profiles",
        json={"ontology_id": SEED_ONTOLOGY_ID},
        headers=_headers(leader, settings),
    )
    assert bad.status_code == 400
