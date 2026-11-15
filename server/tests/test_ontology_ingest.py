"""discovery 直提 + 评审包 HTML 路由测试（WP4④ / D17）。

sqlite 文件库 + 真实 Settings + 假 ontology 客户端；不依赖 CI PostgreSQL。
红线钉：
- 只推**人工审阅定案**（review_status=accepted）的事实，且 evidence_quote 必须逐字原文；
- 无可直提候选 ⇒ 400/404 且**不建** change-set（不产生空壳写面）；
- 跨项目 source_ref 绝不读取他项目正文（§15 项目隔离）；
- 权限：无访问权 ⇒ 404（S-01），仅查看权（viewer/member）直提 ⇒ 403；
- runtime 404 / 不可达显性转译，绝不渲染幽灵 200 HTML；
- 评审包必须含逐项 evidence_quote + source_location + 内容寻址包 ID + 水印 + 审计事件；
- 租户上下文随项目（org_id 从项目归属推导，不来自外部配置）。
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pytest
from flask import Flask
from pydantic import SecretStr
from sqlalchemy import DefaultClause, event, select
from sqlalchemy import text as sa_text
from sqlalchemy.orm import Session

from fde_api.app import create_app
from fde_api.auth.models import Base, User
from fde_api.auth.tokens import issue_access_token
from fde_api.config import Settings
from fde_api.discovery.models import BusinessFact, DiscoveryExtraction
from fde_api.extensions import db
from fde_api.integrations import ingest_service, review_package
from fde_api.integrations.ontology_client import OntologyUnavailable
from fde_api.transcripts.models import InterviewMinutes
from fde_api.workbench.models import OperationEvent, Project, ProjectMember

_BASE: dict[str, str] = {
    "redis_url": "redis://127.0.0.1:6379/2",
    "jwt_secret": "test-secret-with-at-least-thirty-two-characters",
}

_CONTENT = "会议开场\n客户经理负责线索跟进\n客户确认验收口径\n"


class FakeClient:
    """假 ontology 客户端：记录直提调用，返回可预期的 change-set 详情。"""

    def __init__(self, *, cs_status: int = 200, unavailable: bool = False) -> None:
        self.calls: list[dict[str, Any]] = []
        self.cs_status = cs_status
        self.unavailable = unavailable

    def submit_candidates(self, **kwargs: Any) -> dict[str, Any]:
        if self.unavailable:
            raise OntologyUnavailable("connection refused")
        self.calls.append(kwargs)
        return {"id": "cs-123", "status": "draft", "_status": 201}

    def get_change_set(self, **kwargs: Any) -> dict[str, Any]:
        if self.unavailable:
            raise OntologyUnavailable("connection refused")
        self.calls.append(kwargs)
        if self.cs_status == 404:
            return {"_status": 404}
        return {
            "id": "cs-123",
            "status": "pending_review",
            "diff_summary": "新增角色与流程",
            "proposed_json": [
                {
                    "op": "create",
                    "entity_type": "object_types",
                    "entity_key": "role_f1234567890",
                    "payload": {
                        "display_name": "客户经理",
                        "evidence_quote": "客户经理负责线索跟进",
                        "source_location": "interview_minutes:min-1#line=2&type=line",
                        "confidence": 0.9,
                        "fact_or_inference": "fact",
                        "suggested_owner": "business_owner",
                    },
                }
            ],
            "approvals": [{"role": "business_owner", "decision": "approved"}],
            "_status": 200,
        }


def _fill_sqlite_timestamps(
    session: Session, flush_context: object, instances: object
) -> None:
    """sqlite 无 UTC_TIMESTAMP(6)（MySQL 专有 server_default）：flush 前显式
    回填时间戳列。方言守卫保证 PG 路径零影响。"""
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


@pytest.fixture
def ingest_app(tmp_path: Path) -> Iterator[Flask]:
    base = dict(_BASE)
    base["database_url"] = f"sqlite:///{tmp_path / 'ingest.db'}"
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
            "interview_minutes",
            "transcript_drafts",
            "discovery_extractions",
            "business_facts",
            "operation_events",
        )
    ]
    saved: dict[Any, Any] = {}
    for table in tables:
        for col in table.columns:
            sd = col.server_default
            arg = getattr(sd, "arg", None)
            rendered = str(arg) if arg is not None else ""
            if "TIMESTAMP" in rendered.upper():
                saved[col] = sd
                col.server_default = DefaultClause(sa_text("CURRENT_TIMESTAMP"))

    @event.listens_for(engine, "checkout")
    def _register_char_length(dbapi_connection, *_args):
        dbapi_connection.create_function(
            "char_length", 1, lambda value: len(value) if value is not None else None
        )

    try:
        Base.metadata.create_all(engine, tables=tables)
        event.listen(Session, "before_flush", _fill_sqlite_timestamps)
        _seed(app)
        yield app
    finally:
        event.remove(Session, "before_flush", _fill_sqlite_timestamps)
        for col, sd in saved.items():
            col.server_default = sd


def _seed(app: Flask) -> None:
    reviewed_at = datetime(2026, 1, 3, tzinfo=UTC)
    with app.app_context():
        session = db.session()
        session.add_all(
            [
                User(
                    id="u-leader",
                    username="leader@test",
                    role="project_lead",
                    org_id="org-1",
                    password_hash="x",
                    must_change_password=False,
                    is_active=True,
                ),
                User(
                    id="u-viewer",
                    username="viewer@test",
                    role="viewer",
                    org_id="org-1",
                    password_hash="x",
                    must_change_password=False,
                    is_active=True,
                ),
                User(
                    id="u-other",
                    username="other@test",
                    role="project_lead",
                    org_id="org-2",
                    password_hash="x",
                    must_change_password=False,
                    is_active=True,
                ),
                Project(
                    id="p-1",
                    project_code="PRJ-1",
                    name="项目一",
                    enterprise_code="ENT-1",
                    leader_user_id="u-leader",
                    status="active",
                    planned_start_date=date(2026, 1, 1),
                    planned_end_date=date(2026, 12, 31),
                    template_snapshot={},
                    org_id="org-1",
                ),
                Project(
                    id="p-2",
                    project_code="PRJ-2",
                    name="项目二",
                    enterprise_code="ENT-2",
                    leader_user_id="u-other",
                    status="active",
                    planned_start_date=date(2026, 1, 1),
                    planned_end_date=date(2026, 12, 31),
                    template_snapshot={},
                    org_id="org-2",
                ),
                ProjectMember(
                    project_id="p-1",
                    user_id="u-viewer",
                    role="viewer",
                ),
                InterviewMinutes(
                    id="min-1",
                    project_id="p-1",
                    created_by_user_id="u-leader",
                    title="访谈纪要",
                    content=_CONTENT,
                    content_sha256="b" * 64,
                    client_confirmed_by="客户",
                    client_confirmed_at=datetime(2026, 1, 2, tzinfo=UTC),
                    client_confirmation_method="written",
                ),
                InterviewMinutes(
                    id="min-other",
                    project_id="p-2",
                    created_by_user_id="u-other",
                    title="他项目纪要",
                    content="第一行\n机密跨项目角色描述\n",
                    content_sha256="c" * 64,
                    client_confirmed_by="客户乙",
                    client_confirmed_at=datetime(2026, 1, 2, tzinfo=UTC),
                    client_confirmation_method="written",
                ),
                DiscoveryExtraction(
                    id="ex-1",
                    project_id="p-1",
                    created_by_user_id="u-leader",
                    source_type="interview_minutes",
                    source_id="min-1",
                    source_sha256="b" * 64,
                    status="review_required",
                ),
                DiscoveryExtraction(
                    id="ex-cross",
                    project_id="p-1",
                    created_by_user_id="u-leader",
                    source_type="interview_minutes",
                    source_id="min-1",
                    extractor_version="v-cross",
                    prompt_version="p-cross",
                    source_sha256="b" * 64,
                    status="review_required",
                ),
                BusinessFact(
                    id="f-1",
                    project_id="p-1",
                    extraction_id="ex-1",
                    fact_type="role",
                    classification="customer_stated",
                    subject="客户经理",
                    predicate="负责",
                    object_value="线索跟进",
                    confidence=0.9,
                    source_ref="interview_minutes:min-1",
                    source_locator={"type": "line", "line": 2},
                    review_status="accepted",
                    reviewed_by_user_id="u-leader",
                    reviewed_at=reviewed_at,
                ),
                BusinessFact(
                    id="f-2",
                    project_id="p-1",
                    extraction_id="ex-1",
                    fact_type="pain_point",
                    classification="customer_stated",
                    subject="线索丢失",
                    predicate="发生",
                    object_value="频繁",
                    confidence=0.8,
                    source_ref="interview_minutes:min-1",
                    source_locator={"type": "line", "line": 3},
                    review_status="pending",
                ),
                BusinessFact(
                    id="f-cross",
                    project_id="p-1",
                    extraction_id="ex-cross",
                    fact_type="role",
                    classification="customer_stated",
                    subject="越权探针",
                    predicate="尝试读取",
                    object_value="他项目纪要",
                    confidence=0.9,
                    source_ref="interview_minutes:min-other",
                    source_locator={"type": "line", "line": 2},
                    review_status="accepted",
                    reviewed_by_user_id="u-leader",
                    reviewed_at=reviewed_at,
                ),
            ]
        )
        session.commit()


def _auth_headers(app: Flask, user_id: str = "u-leader") -> dict[str, str]:
    with app.app_context():
        session = db.session()
        user = session.scalar(select(User).where(User.id == user_id))
        assert user is not None
        settings = app.config["SETTINGS"]
        return {"Authorization": f"Bearer {issue_access_token(user, settings)}"}


def test_submit_candidates_pushes_accepted_fact_only(
    ingest_app: Flask, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = FakeClient()
    monkeypatch.setattr(ingest_service, "client_from_settings", lambda: fake)
    monkeypatch.setattr(review_package, "client_from_settings", lambda: fake)
    client = ingest_app.test_client()

    response = client.post(
        "/api/v1/projects/p-1/ontology-candidates",
        json={"ontology_id": "ont-1", "extraction_id": "ex-1"},
        headers=_auth_headers(ingest_app),
    )

    assert response.status_code == 201, response.get_json()
    body = response.get_json()["data"]
    assert body["change_set_id"] == "cs-123"
    assert body["item_count"] == 1
    assert [entry["reason"] for entry in body["skipped"]] == ["not_accepted"]

    call = fake.calls[0]
    assert call["org_id"] == "org-1"
    assert call["captured_from"] == "discovery:ex-1"
    item = call["items"][0]
    assert "." not in item["entity_key"]
    payload = item["payload"]
    assert "status" not in payload
    assert payload["evidence_quote"] == "客户经理负责线索跟进"
    assert payload["source_location"] == "interview_minutes:min-1#line=2&type=line"
    assert payload["confidence"] == 0.9
    assert payload["fact_or_inference"] == "fact"
    assert payload["suggested_owner"] == "business_owner"

    with ingest_app.app_context():
        ev = db.session().scalar(
            select(OperationEvent).where(
                OperationEvent.event_type == "ontology_candidates_submitted"
            )
        )
        assert ev is not None
        assert ev.project_id == "p-1"


def test_submit_candidates_without_facts_is_404(
    ingest_app: Flask, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = FakeClient()
    monkeypatch.setattr(ingest_service, "client_from_settings", lambda: fake)
    client = ingest_app.test_client()

    response = client.post(
        "/api/v1/projects/p-1/ontology-candidates",
        json={"ontology_id": "ont-1", "extraction_id": "ex-missing"},
        headers=_auth_headers(ingest_app),
    )

    assert response.status_code == 404
    assert response.get_json()["error"]["code"] == "facts_not_found"
    assert fake.calls == []


def test_submit_candidates_rejects_cross_project_source_and_viewer_write(
    ingest_app: Flask, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = FakeClient()
    monkeypatch.setattr(ingest_service, "client_from_settings", lambda: fake)
    client = ingest_app.test_client()

    # 1) viewer 无管理权 ⇒ 403
    r_viewer = client.post(
        "/api/v1/projects/p-1/ontology-candidates",
        json={"ontology_id": "ont-1", "extraction_id": "ex-1"},
        headers=_auth_headers(ingest_app, "u-viewer"),
    )
    assert r_viewer.status_code == 403

    # 2) 跨租户用户访问 p-1 ⇒ 404（S-01）
    r_other = client.post(
        "/api/v1/projects/p-1/ontology-candidates",
        json={"ontology_id": "ont-1", "extraction_id": "ex-1"},
        headers=_auth_headers(ingest_app, "u-other"),
    )
    assert r_other.status_code == 404

    # 3) source_ref 指向 p-2 的纪要 ⇒ 被项目隔离过滤，不可直提（400 no_pushable_candidates，零出站）
    r_cross = client.post(
        "/api/v1/projects/p-1/ontology-candidates",
        json={"ontology_id": "ont-1", "extraction_id": "ex-cross"},
        headers=_auth_headers(ingest_app),
    )
    assert r_cross.status_code == 400
    assert r_cross.get_json()["error"]["code"] == "no_pushable_candidates"
    assert fake.calls == []


def test_review_package_renders_evidence_and_package_id(
    ingest_app: Flask, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = FakeClient()
    monkeypatch.setattr(review_package, "client_from_settings", lambda: fake)
    client = ingest_app.test_client()

    response = client.get(
        "/api/v1/projects/p-1/change-sets/cs-123/review-package",
        headers=_auth_headers(ingest_app),
    )

    assert response.status_code == 200
    assert response.mimetype == "text/html"
    html = response.get_data(as_text=True)
    assert "客户经理负责线索跟进" in html
    assert "interview_minutes:min-1#line=2&amp;type=line" in html
    assert "review_package_id" in html
    assert "项目代号 PRJ-1" in html


def test_review_package_id_is_stable_and_handles_runtime_errors(
    ingest_app: Flask, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = FakeClient()
    monkeypatch.setattr(review_package, "client_from_settings", lambda: fake)
    client = ingest_app.test_client()
    headers = _auth_headers(ingest_app)

    first = client.get(
        "/api/v1/projects/p-1/change-sets/cs-123/review-package", headers=headers
    ).get_data(as_text=True)
    second = client.get(
        "/api/v1/projects/p-1/change-sets/cs-123/review-package", headers=headers
    ).get_data(as_text=True)
    assert first == second

    # runtime 404 ⇒ 404 JSON，不渲染幽灵 200 HTML
    monkeypatch.setattr(
        review_package, "client_from_settings", lambda: FakeClient(cs_status=404)
    )
    r_404 = client.get(
        "/api/v1/projects/p-1/change-sets/cs-missing/review-package", headers=headers
    )
    assert r_404.status_code == 404

    # runtime 不可达 ⇒ 503 ontology_unavailable
    monkeypatch.setattr(
        review_package, "client_from_settings", lambda: FakeClient(unavailable=True)
    )
    r_503 = client.get(
        "/api/v1/projects/p-1/change-sets/cs-123/review-package", headers=headers
    )
    assert r_503.status_code == 503
    assert r_503.get_json()["error"]["code"] == "ontology_unavailable"
