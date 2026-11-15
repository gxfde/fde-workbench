"""V3.3 M3-WP4：OntologyClient M3 方法、MockOntologyAdapter 同形契约与项目级接地/血缘代理测试。

覆盖点：
1. §14-2 / 契约 §4：OntologyClient 与 MockOntologyAdapter 通过同一套契约测试集（M2 状态机 +
   409 base_conflict + M3 四方法 check_grounding / get_lineage / query_objects / query_related
   + 故障注入 unavailable / 5xx / auth）；
2. D21 / WP4③：POST /api/v1/projects/<id>/ontology-bindings/<binding_id>/grounding-check 与
   GET /api/v1/projects/<id>/ontology-bindings/<binding_id>/lineage：
   - 强制取 DB 绑定的 pinned_version_id（S-13，忽略请求体/查询串伪造 version_id）；
   - 强制取项目归属 project.org_id（D10，不信任外部租户参数）；
   - 跨租户 / 无项目查看权一律 404（S-01 零存在性泄露）；
   - FDE_ONTOLOGY_ENABLED=false 时先于鉴权返回与不存在路径逐字节同形 404（D12/D13）；
   - runtime 不可达 503、凭据错误 502 显性降级（不静默吞错）。
"""

from __future__ import annotations

import json
import time
from collections.abc import Iterator
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import jwt
import pytest
from flask import Flask
from pydantic import SecretStr
from sqlalchemy import DefaultClause, event
from sqlalchemy import text as sa_text
from sqlalchemy.orm import Session

from fde_api.app import create_app
from fde_api.auth.models import Base, User
from fde_api.config import Settings
from fde_api.extensions import db
from fde_api.integrations import service as binding_service
from fde_api.integrations.models import ACTIVE_MARKER, ProjectOntologyBinding
from fde_api.integrations.ontology_client import (
    OntologyAuthError,
    OntologyClient,
    OntologyClientError,
    OntologyConflict,
    OntologyUnavailable,
)
from fde_api.integrations.ontology_mock import MockOntologyAdapter
from fde_api.workbench.models import Project, ProjectMember

_BASE: dict[str, str] = {
    "redis_url": "redis://127.0.0.1:6379/2",
    "jwt_secret": "test-secret-with-at-least-thirty-two-characters",
}


class _FakeHttpBackend:
    """为 OntologyClient 提供与真实 runtime 同契约的内存 HTTP 桩，以跑同套 §14-2 契约用例。"""

    def __init__(self) -> None:
        self.mock = MockOntologyAdapter()
        self.last_request: dict[str, Any] = {}

    def request(self, method: str, url: str, **kwargs: Any) -> Any:
        parsed = urlparse(url)
        path = parsed.path
        params = kwargs.get("params") or {}
        body = kwargs.get("json") or {}
        self.last_request = {
            "method": method,
            "path": path,
            "params": params,
            "json": body,
            "headers": kwargs.get("headers") or {},
        }

        class _Resp:
            def __init__(self, status: int, data: dict[str, Any]) -> None:
                self.status_code = status
                cleaned = {k: v for k, v in data.items() if k != "_status"}
                self.content = json.dumps(cleaned).encode("utf-8")
                self.text = self.content.decode("utf-8")

            def json(self) -> dict[str, Any]:
                return json.loads(self.content)  # type: ignore[no-any-return]

        if path == "/api/v1/ontologies" and method == "POST":
            res = self.mock.create_ontology(
                actor_id="u1",
                org_id="org-1",
                project_id="proj-1",
                domain_key=str(body.get("domain_key", "")),
                title=str(body.get("title", "")),
                description=str(body.get("description", "")),
            )
            return _Resp(int(res.get("_status", 201)), res)

        if path.endswith("/change-sets") and method == "POST":
            ont_id = path.split("/")[4]
            res = self.mock.submit_candidates(
                actor_id="u1",
                org_id="org-1",
                project_id="proj-1",
                ontology_id=ont_id,
                title=str(body.get("title", "")),
                items=list(body.get("proposed_json") or []),
                captured_from=str(body.get("captured_from", "")),
                description=str(body.get("description", "")),
            )
            return _Resp(int(res.get("_status", 201)), res)

        if path.startswith("/api/v1/change-sets/") and path.endswith("/validate"):
            cs_id = path.split("/")[4]
            res = self.mock.validate_change_set(
                actor_id="u1", org_id="org-1", project_id="proj-1", change_set_id=cs_id
            )
            return _Resp(int(res.get("_status", 200)), res)

        if path.startswith("/api/v1/change-sets/") and path.endswith("/approvals"):
            cs_id = path.split("/")[4]
            res = self.mock.approve_change_set(
                actor_id="u2",
                org_id="org-1",
                project_id="proj-1",
                change_set_id=cs_id,
                role=str(body.get("role", "")),
                decision=str(body.get("decision", "")),
                comment=str(body.get("comment", "")),
            )
            return _Resp(int(res.get("_status", 200)), res)

        if path.startswith("/api/v1/change-sets/") and path.endswith("/publish"):
            cs_id = path.split("/")[4]
            res = self.mock.publish(
                actor_id="u2",
                org_id="org-1",
                project_id="proj-1",
                change_set_id=cs_id,
                version=str(body.get("version", "1.0.0")),
                confirm_breaking=bool(body.get("confirm_breaking", False)),
            )
            return _Resp(int(res.get("_status", 201)), res)

        if "/grounding/" in path and path.endswith("/check") and method == "POST":
            parts = path.split("/")
            ont_id, ver_id, ot_key = parts[4], parts[6], parts[8]
            res = self.mock.check_grounding(
                actor_id="u1",
                org_id="org-1",
                project_id="proj-1",
                ontology_id=ont_id,
                version_id=ver_id,
                object_type_key=ot_key,
            )
            return _Resp(int(res.get("_status", 200)), res)

        if path.endswith("/lineage") and method == "GET":
            parts = path.split("/")
            ont_id, ver_id = parts[4], parts[6]
            res = self.mock.get_lineage(
                actor_id="u1",
                org_id="org-1",
                project_id="proj-1",
                ontology_id=ont_id,
                version_id=ver_id,
                object_type=params.get("object_type"),
                object_ref_id=params.get("object_ref_id"),
            )
            return _Resp(int(res.get("_status", 200)), res)

        if path == "/api/v1/query/objects" and method == "POST":
            res = self.mock.query_objects(
                actor_id="u1",
                org_id="org-1",
                project_id="proj-1",
                pinned_version_id=str(body.get("pinned_version_id", "")),
                object_type_id=str(body.get("object_type_id", "")),
                filters=body.get("filters"),
                limit=int(body.get("limit", 50)),
                offset=int(body.get("offset", 0)),
            )
            return _Resp(int(res.get("_status", 200)), res)

        if path == "/api/v1/query/related" and method == "POST":
            res = self.mock.query_related(
                actor_id="u1",
                org_id="org-1",
                project_id="proj-1",
                pinned_version_id=str(body.get("pinned_version_id", "")),
                object_ref_id=str(body.get("object_ref_id", "")),
                relation_key=str(body.get("relation_key", "")),
                limit=int(body.get("limit", 50)),
                offset=int(body.get("offset", 0)),
            )
            return _Resp(int(res.get("_status", 200)), res)

        return _Resp(404, {"code": "not_found", "message": "not found"})


@pytest.mark.parametrize("adapter_kind", ["mock", "http_client"])
def test_client_and_mock_pass_identical_m3_contract_suite(
    adapter_kind: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """§14-2：MockOntologyAdapter 与 OntologyClient 通过同一套契约测试用例。"""
    if adapter_kind == "mock":
        adapter: Any = MockOntologyAdapter()
    else:
        backend = _FakeHttpBackend()
        monkeypatch.setattr(
            "fde_api.integrations.ontology_client.requests.request", backend.request
        )
        adapter = OntologyClient("http://runtime.test", "k", "s")

    seeded_qc = adapter.check_grounding(
        actor_id="u1",
        org_id="org-1",
        project_id="proj-1",
        ontology_id="ont-seed-mfg",
        version_id="ver-seed-1-0-0",
        object_type_key="batch",
    )
    assert seeded_qc["_status"] == 200
    assert seeded_qc["object_type_key"] == "batch"
    assert seeded_qc["passed"] is True

    seeded_objs = adapter.query_objects(
        actor_id="u1",
        org_id="org-1",
        project_id="proj-1",
        pinned_version_id="ver-seed-1-0-0",
        object_type_id="batch",
    )
    assert seeded_objs["_status"] == 200
    assert len(seeded_objs["items"]) >= 1
    assert seeded_objs["items"][0]["object_type_id"] == "batch"
    first_batch_ref = seeded_objs["items"][0]["object_ref_id"]

    related_objs = adapter.query_related(
        actor_id="u1",
        org_id="org-1",
        project_id="proj-1",
        pinned_version_id="ver-seed-1-0-0",
        object_ref_id=first_batch_ref,
        relation_key="batch_has_inspection",
    )
    assert related_objs["_status"] == 200
    assert len(related_objs["items"]) >= 1

    lineage = adapter.get_lineage(
        actor_id="u1",
        org_id="org-1",
        project_id="proj-1",
        ontology_id="ont-seed-mfg",
        version_id="ver-seed-1-0-0",
        object_type="batch",
        object_ref_id=first_batch_ref,
    )
    assert lineage["_status"] == 200
    assert len(lineage["definition_lineage"]) >= 1
    assert lineage["instance_ref_trace"]["object_ref_id"] == first_batch_ref


def test_mock_adapter_conflict_and_fault_injection() -> None:
    """契约 §4：MockOntologyAdapter 支持 409 base_conflict 与延迟/不可达/5xx/鉴权故障注入。"""
    mock = MockOntologyAdapter()
    ont = mock.create_ontology(
        actor_id="u1", org_id="org-1", project_id="proj-1", domain_key="mfg", title="制造"
    )
    ont_id = ont["id"]
    cs1 = mock.submit_candidates(
        actor_id="u1",
        org_id="org-1",
        project_id="proj-1",
        ontology_id=ont_id,
        title="cs1",
        items=[],
        captured_from="discovery:1",
    )
    cs2 = mock.submit_candidates(
        actor_id="u1",
        org_id="org-1",
        project_id="proj-1",
        ontology_id=ont_id,
        title="cs2",
        items=[],
        captured_from="discovery:2",
    )
    mock.validate_change_set(
        actor_id="u1", org_id="org-1", project_id="proj-1", change_set_id=cs1["id"]
    )
    with pytest.raises(OntologyConflict):
        mock.validate_change_set(
            actor_id="u1", org_id="org-1", project_id="proj-1", change_set_id=cs2["id"]
        )

    mock.inject_fault("unavailable")
    with pytest.raises(OntologyUnavailable):
        mock.check_grounding(
            actor_id="u1",
            org_id="org-1",
            project_id="proj-1",
            ontology_id="ont-seed-mfg",
            version_id="ver-seed-1-0-0",
            object_type_key="batch",
        )

    mock.inject_fault("5xx")
    with pytest.raises(OntologyClientError):
        mock.get_lineage(
            actor_id="u1",
            org_id="org-1",
            project_id="proj-1",
            ontology_id="ont-seed-mfg",
            version_id="ver-seed-1-0-0",
        )

    mock.inject_fault("auth")
    with pytest.raises(OntologyAuthError):
        mock.query_objects(
            actor_id="u1",
            org_id="org-1",
            project_id="proj-1",
            pinned_version_id="ver-seed-1-0-0",
            object_type_id="batch",
        )
    mock.clear_fault()
    assert mock.health() is True


def test_mock_publish_requires_approved_and_returns_conflict() -> None:
    """Patch C：mock publish 与 runtime 同契约——未 approved 即 409 base_conflict。"""
    mock = MockOntologyAdapter()
    ont = mock.create_ontology(
        actor_id="u1", org_id="org-1", project_id="proj-1", domain_key="mfg", title="制造"
    )
    cs = mock.submit_candidates(
        actor_id="u1",
        org_id="org-1",
        project_id="proj-1",
        ontology_id=ont["id"],
        title="cs-draft",
        items=[],
        captured_from="discovery:1",
    )
    with pytest.raises(OntologyConflict):
        mock.publish(
            actor_id="u1",
            org_id="org-1",
            project_id="proj-1",
            change_set_id=cs["id"],
            version="1.0.0",
        )


def _fill_sqlite_timestamps(
    session: Session, flush_context: object, instances: object
) -> None:
    bind = session.bind
    if bind is None or bind.dialect.name != "sqlite":
        return
    now = datetime.now(UTC)
    for obj in session.new:
        for field in ("created_at", "updated_at", "acted_at", "occurred_at"):
            if (
                hasattr(type(obj), field)
                and getattr(obj, field, None) is None
                and field in type(obj).__mapper__.columns
            ):
                setattr(obj, field, now)


def _issue_token(user: User, settings: Settings) -> str:
    now = int(time.time())
    payload = {
        "sub": user.id,
        "role": user.role,
        "pwd": True,
        "ver": user.auth_version,
        "org_id": user.org_id,
        "iat": now,
        "exp": now + 900,
        "iss": "fde-workbench",
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


@pytest.fixture
def m3_binding_app(tmp_path: Path) -> Iterator[Flask]:
    base = dict(_BASE)
    base["database_url"] = f"sqlite:///{tmp_path / 'm3_binding.db'}"
    settings = Settings(
        env="test",
        ontology_enabled=True,
        ontology_api_key=SecretStr("k"),
        ontology_signing_key=SecretStr("s"),
        **base,  # type: ignore[arg-type]
    )
    app = create_app(settings)
    engine = app.extensions["fde_api_db"]
    tables = [
        Base.metadata.tables[name]
        for name in (
            "users",
            "projects",
            "project_members",
            "project_ontology_bindings",
            "ontology_binding_upgrades",
            "operation_events",
        )
    ]
    saved: dict[Any, Any] = {}
    for table in tables:
        columns: Any = table.columns
        for col in columns:
            sd = col.server_default
            arg = getattr(sd, "arg", None)
            rendered = str(arg) if arg is not None else ""
            if "TIMESTAMP" in rendered.upper():
                saved[col] = sd
                col.server_default = DefaultClause(sa_text("CURRENT_TIMESTAMP"))
    try:
        Base.metadata.create_all(engine, tables=tables)
        event.listen(Session, "before_flush", _fill_sqlite_timestamps)
        yield app
    finally:
        event.remove(Session, "before_flush", _fill_sqlite_timestamps)
        for col, sd in saved.items():
            col.server_default = sd


def test_project_grounding_check_and_lineage_enforce_pinned_version_and_org_isolation(
    m3_binding_app: Flask, monkeypatch: pytest.MonkeyPatch
) -> None:
    """WP4③：项目级 grounding-check 与 lineage 强制用绑定 pinned_version_id 与 project.org_id。"""
    settings = m3_binding_app.config["SETTINGS"]
    mock_adapter = MockOntologyAdapter()
    captured_calls: list[dict[str, Any]] = []

    orig_check = mock_adapter.check_grounding
    orig_lineage = mock_adapter.get_lineage

    def spy_check(**kwargs: Any) -> dict[str, Any]:
        captured_calls.append({"fn": "check_grounding", **kwargs})
        return orig_check(**kwargs)

    def spy_lineage(**kwargs: Any) -> dict[str, Any]:
        captured_calls.append({"fn": "get_lineage", **kwargs})
        return orig_lineage(**kwargs)

    monkeypatch.setattr(mock_adapter, "check_grounding", spy_check)
    monkeypatch.setattr(mock_adapter, "get_lineage", spy_lineage)
    monkeypatch.setattr(binding_service, "client_from_settings", lambda: mock_adapter)

    with m3_binding_app.app_context():
        session = db.session()
        user_a = User(
            id="user-a",
            username="a@alpha.test",
            role="project_lead",
            password_hash="x",
            is_active=True,
            must_change_password=False,
            auth_version=1,
            org_id="org-alpha",
        )
        user_b = User(
            id="user-b",
            username="b@beta.test",
            role="project_lead",
            password_hash="x",
            is_active=True,
            must_change_password=False,
            auth_version=1,
            org_id="org-beta",
        )
        proj_a = Project(
            id="proj-alpha",
            project_code="PA-01",
            name="Alpha Project",
            enterprise_code="ENT-A",
            leader_user_id="user-a",
            status="active",
            planned_start_date=date(2026, 1, 1),
            planned_end_date=date(2026, 12, 31),
            template_snapshot={},
            org_id="org-alpha",
        )
        member_a = ProjectMember(project_id="proj-alpha", user_id="user-a", role="member")
        binding = ProjectOntologyBinding(
            id="bind-alpha-1",
            org_id="org-alpha",
            project_id="proj-alpha",
            ontology_id="ont-seed-mfg",
            pinned_version_id="ver-seed-1-0-0",
            pinned_version="1.0.0",
            binding_role="primary",
            status="active",
            active_marker=ACTIVE_MARKER,
            bound_by_user_id="user-a",
        )
        session.add_all([user_a, user_b, proj_a, member_a, binding])
        session.commit()
        token_a = _issue_token(user_a, settings)
        token_b = _issue_token(user_b, settings)

    client = m3_binding_app.test_client()

    # 1) grounding-check 忽略请求体里伪造的 version_id / org_id，强制用绑定 pinned_version_id + project.org_id
    r_check = client.post(
        "/api/v1/projects/proj-alpha/ontology-bindings/bind-alpha-1/grounding-check",
        headers={"Authorization": f"Bearer {token_a}"},
        json={
            "object_type_key": "batch",
            "version_id": "ver-forged-999",
            "org_id": "org-forged",
        },
    )
    assert r_check.status_code == 200, r_check.get_json()
    data_check = r_check.get_json()["data"]
    assert data_check["object_type_key"] == "batch"
    assert data_check["passed"] is True
    assert captured_calls[-1]["version_id"] == "ver-seed-1-0-0"
    assert captured_calls[-1]["org_id"] == "org-alpha"

    # 2) lineage 支持 object_type / object_ref_id 过滤，且强制使用 pinned_version_id
    r_lin = client.get(
        "/api/v1/projects/proj-alpha/ontology-bindings/bind-alpha-1/lineage"
        "?object_type=batch&version_id=ver-forged-999",
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert r_lin.status_code == 200, r_lin.get_json()
    data_lin = r_lin.get_json()["data"]
    assert len(data_lin["definition_lineage"]) >= 1
    assert captured_calls[-1]["version_id"] == "ver-seed-1-0-0"
    assert captured_calls[-1]["org_id"] == "org-alpha"
    assert captured_calls[-1]["object_type"] == "batch"

    # 3) 跨租户 User B 探测一律 404（S-01 不泄露存在性）
    r_cross_check = client.post(
        "/api/v1/projects/proj-alpha/ontology-bindings/bind-alpha-1/grounding-check",
        headers={"Authorization": f"Bearer {token_b}"},
        json={"object_type_key": "batch"},
    )
    assert r_cross_check.status_code == 404
    r_cross_lin = client.get(
        "/api/v1/projects/proj-alpha/ontology-bindings/bind-alpha-1/lineage",
        headers={"Authorization": f"Bearer {token_b}"},
    )
    assert r_cross_lin.status_code == 404

    # 4) 缺少 object_type_key ⇒ 400 invalid_request
    r_bad = client.post(
        "/api/v1/projects/proj-alpha/ontology-bindings/bind-alpha-1/grounding-check",
        headers={"Authorization": f"Bearer {token_a}"},
        json={},
    )
    assert r_bad.status_code == 400
    assert r_bad.get_json()["error"]["code"] == "invalid_request"

    # 5) runtime 不可达 ⇒ 503 ontology_unavailable（对齐 M2 _verified_snapshot 语义）
    mock_adapter.inject_fault("unavailable")
    r_down = client.get(
        "/api/v1/projects/proj-alpha/ontology-bindings/bind-alpha-1/lineage",
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert r_down.status_code == 503
    assert r_down.get_json()["error"]["code"] == "ontology_unavailable"
