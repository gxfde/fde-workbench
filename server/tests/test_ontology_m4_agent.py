"""M4-WP3 workbench 薄适配：OntologyClient/Mock M4 方法、项目级 Logic/Action 代理、
MCP 工具分级（D26）测试先行（TDD Red -> Green）。

覆盖条款（工作令 docs/v3.3/m4/00-m4-work-order.md WP3 + D26/D27）：
- §14-2 / 契约 §8：OntologyClient 与 MockOntologyAdapter 同一套 M4 契约测试集
  （run_logic / propose_action / approve_action / get_action_request / execute_action，
  对齐 M1 冻结契约 D28 形态：propose 默认 dry_run_result、审批子表 I4、
  rejected 终态、pending 执行 409 approval_required）
- §13 M4 条 1：项目级代理强制 DB 绑定 pinned_version_id（S-13）与 project.org_id
  （D10/S-01），请求体伪造字段一律无效；D12/D13 开关门控
- §13 M4 条 3 / D26：MCP 网关工具分级——ontology_logic_run（read 档）、
  ontology_action_propose（write_db 档）、ontology_action_execute（执行档，
  AGENT_WRITE_DENIED_TOOLS 恒剥，强授权单独放行）
- workflow §9.3 版本落痕由工具调用链路强制（每次 ontology 工具调用都携带
  服务端注入的 pinned_version_id，见代理层测试）
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
from sqlalchemy.orm import Session

from fde_api.app import create_app
from fde_api.auth.models import Base, User
from fde_api.config import Settings
from fde_api.extensions import db
from fde_api.integrations import service as binding_service
from fde_api.integrations.models import ACTIVE_MARKER, ProjectOntologyBinding
from fde_api.integrations.ontology_client import OntologyClient, OntologyConflict
from fde_api.integrations.ontology_mock import MockOntologyAdapter
from fde_api.workbench.models import Project, ProjectMember

_BASE: dict[str, str] = {
    "redis_url": "redis://127.0.0.1:6379/3",
    "jwt_secret": "test-secret-with-at-least-thirty-two-characters",
}


class _FakeHttpBackendM4:
    """与真实 runtime 同契约的内存 HTTP 桩（M4 增量分支：/logic、/actions、/action-requests）。"""

    def __init__(self) -> None:
        self.mock = MockOntologyAdapter()
        self.last_request: dict[str, Any] = {}

    def request(self, method: str, url: str, **kwargs: Any) -> Any:
        parsed = urlparse(url)
        path = parsed.path
        body = kwargs.get("json") or {}
        self.last_request = {"method": method, "path": path, "json": body}

        class _Resp:
            def __init__(self, status: int, data: dict[str, Any]) -> None:
                self.status_code = status
                cleaned = {k: v for k, v in data.items() if k != "_status"}
                self.content = json.dumps(cleaned).encode("utf-8")
                self.text = self.content.decode("utf-8")

            def json(self) -> dict[str, Any]:
                return json.loads(self.content)  # type: ignore[no-any-return]

        if "/logic/" in path and path.endswith("/run") and method == "POST":
            logic_key = path.split("/api/v1/logic/")[1].rsplit("/run", 1)[0]
            res = self.mock.run_logic(
                actor_id="u1",
                org_id="org-1",
                project_id="proj-1",
                ontology_id="ont-seed-mfg",
                version_id=str(body.get("pinned_version_id", "")),
                logic_key=logic_key,
                input_payload=body.get("input"),
            )
            return _Resp(int(res.get("_status", 200)), res)

        m4_action = path.startswith("/api/v1/actions/") and method == "POST"
        if m4_action and path.endswith("/propose"):
            action_key = path.split("/api/v1/actions/")[1].rsplit("/propose", 1)[0]
            res = self.mock.propose_action(
                actor_id="u1",
                org_id="org-1",
                project_id="proj-1",
                ontology_id="ont-seed-mfg",
                action_key=action_key,
                version_id=str(body.get("pinned_version_id", "")),
                input_payload=body.get("input"),
            )
            return _Resp(int(res.get("_status", 201)), res)
        if m4_action and path.endswith("/execute"):
            action_key = path.split("/api/v1/actions/")[1].rsplit("/execute", 1)[0]
            res = self.mock.execute_action(
                actor_id="u1",
                org_id="org-1",
                project_id="proj-1",
                ontology_id="ont-seed-mfg",
                action_key=action_key,
                request_id=str(body.get("request_id", "")),
            )
            return _Resp(int(res.get("_status", 200)), res)

        if "/action-requests/" in path and method == "POST" and path.endswith("/approvals"):
            request_id = path.split("/api/v1/action-requests/")[1].rsplit("/approvals", 1)[0]
            res = self.mock.approve_action(
                # 传输桩模拟"另一审批人"身份（I4 语义由 runtime 强制，桩不模拟 403 分支）
                actor_id="approver-1",
                org_id="org-1",
                project_id="proj-1",
                ontology_id="ont-seed-mfg",
                request_id=request_id,
                role=str(body.get("role", "")),
                decision=str(body.get("decision", "")),
                comment=body.get("comment"),
            )
            return _Resp(int(res.get("_status", 200)), res)
        if "/action-requests/" in path and method == "GET":
            request_id = path.split("/api/v1/action-requests/")[1]
            res = self.mock.get_action_request(
                actor_id="u1",
                org_id="org-1",
                project_id="proj-1",
                ontology_id="ont-seed-mfg",
                request_id=request_id,
            )
            return _Resp(int(res.get("_status", 200)), res)

        return _Resp(404, {"code": "not_found", "message": "not found"})


@pytest.mark.parametrize("adapter_kind", ["mock", "http_client"])
def test_client_and_mock_pass_identical_m4_contract_suite(
    adapter_kind: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """§14-2：Mock 与 OntologyClient 通过同一套 M4 契约用例（D28 形态）。"""
    if adapter_kind == "mock":
        adapter: Any = MockOntologyAdapter()
    else:
        backend = _FakeHttpBackendM4()
        monkeypatch.setattr(
            "fde_api.integrations.ontology_client.requests.request", backend.request
        )
        adapter = OntologyClient("http://runtime.test", "k", "s")

    kwargs: dict[str, Any] = dict(
        actor_id="u1", org_id="org-1", project_id="proj-1", ontology_id="ont-seed-mfg"
    )

    # 1) run_logic happy path（种子 logic：trace_scope）
    r_logic = adapter.run_logic(
        **kwargs,
        version_id="ver-seed-1-0-0",
        logic_key="trace_scope",
        input_payload={"planned_qty": 100, "stock_qty": 80, "defect_rate": 0.02},
    )
    assert r_logic["_status"] == 200, r_logic
    assert r_logic["result"] == 80
    assert r_logic["pinned_version_id"] == "ver-seed-1-0-0"

    # 2) run_logic：未知 logic 404 / 缺必填 422
    r_unknown = adapter.run_logic(
        **kwargs, version_id="ver-seed-1-0-0", logic_key="no_such", input_payload={}
    )
    assert r_unknown["_status"] == 404
    r_missing = adapter.run_logic(
        **kwargs,
        version_id="ver-seed-1-0-0",
        logic_key="trace_scope",
        input_payload={"planned_qty": 1},
    )
    assert r_missing["_status"] == 422

    # 3) propose_action：pending + dry_run_result（默认 dry-run，零副作用）
    r_propose = adapter.propose_action(
        **kwargs,
        action_key="retention_extension",
        version_id="ver-seed-1-0-0",
        input_payload={
            "object_type_key": "batch",
            "external_pk_value": "BATCH-001",
            "ttl_seconds": 3600,
        },
    )
    assert r_propose["_status"] == 201, r_propose
    assert r_propose["status"] == "pending"
    assert r_propose["dry_run_result"]["simulated"] is True
    rid = r_propose["id"]

    # 4) pending 执行 → 409 approval_required（mock 返回 _status 体；http 路径
    #    客户端按契约将 409 转为 OntologyConflict 异常）
    if adapter_kind == "mock":
        r_early = adapter.execute_action(
            **kwargs, action_key="retention_extension", request_id=rid
        )
        assert r_early["_status"] == 409
        assert r_early["code"] == "approval_required"
    else:
        with pytest.raises(OntologyConflict) as _ei:
            adapter.execute_action(**kwargs, action_key="retention_extension", request_id=rid)
        assert "human approval" in str(_ei.value)

    # 5) I4：requested_by 自批 403（语义由 runtime 强制；传输桩的审批人身份固定
    #    为 approver-1，不模拟 403 分支——mock 是该语义的参照实现）
    if adapter_kind == "mock":
        r_self = adapter.approve_action(
            **kwargs, request_id=rid, role="business_owner", decision="approved", comment=None
        )
        assert r_self["_status"] == 403
    # 审批人 != requester（I4）：两路径都用 approver-1 身份发起审批调用
    r_ok = adapter.approve_action(
        **{**kwargs, "actor_id": "approver-1"},
        request_id=rid,
        role="business_owner",
        decision="approved",
        comment=None,
    )
    assert r_ok["_status"] == 200, r_ok
    assert r_ok["status"] == "approved"

    # 6) execute：completed + pre/post 快照 + 补偿
    r_exec = adapter.execute_action(
        **kwargs, action_key="retention_extension", request_id=rid
    )
    assert r_exec["_status"] == 200, r_exec
    assert r_exec["status"] == "completed"
    assert r_exec["post_snapshot"]["expires_at"]
    assert r_exec["compensation"]["previous_expires_at"]

    # 7) rejected 终态：新 propose → risk 驳回 → execute 409
    r2 = adapter.propose_action(
        **kwargs,
        action_key="retention_extension",
        version_id="ver-seed-1-0-0",
        input_payload={
            "object_type_key": "batch",
            "external_pk_value": "BATCH-001",
            "ttl_seconds": 7200,
        },
    )
    rid2 = r2["id"]
    rej = adapter.approve_action(
        **{**kwargs, "actor_id": "approver-1"},
        request_id=rid2,
        role="risk",
        decision="rejected",
        comment="too long",
    )
    assert rej["_status"] == 200
    assert rej["status"] == "rejected"
    if adapter_kind == "mock":
        r_exec2 = adapter.execute_action(
            **kwargs, action_key="retention_extension", request_id=rid2
        )
        assert r_exec2["_status"] == 409
    else:
        with pytest.raises(OntologyConflict):
            adapter.execute_action(**kwargs, action_key="retention_extension", request_id=rid2)

    # 8) get_action_request 状态机视图
    r_get = adapter.get_action_request(**kwargs, request_id=rid)
    assert r_get["_status"] == 200
    assert r_get["status"] == "completed"
    assert len(r_get["approvals"]) == 1


# ---- 项目级代理与 MCP 分级（app 级） ----


@pytest.fixture
def m4_binding_app(tmp_path: Path) -> Iterator[Flask]:
    base = dict(_BASE)
    base["database_url"] = f"sqlite:///{tmp_path / 'm4_binding.db'}"
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
        for col in table.columns:
            sd = col.server_default
            arg = getattr(sd, "arg", None)
            rendered = str(arg) if arg is not None else ""
            if "TIMESTAMP" in rendered.upper():
                saved[col] = sd
                col.server_default = DefaultClause(event_text())
    try:
        Base.metadata.create_all(engine, tables=tables)
        event.listen(Session, "before_flush", _fill_sqlite_timestamps)
        yield app
    finally:
        event.remove(Session, "before_flush", _fill_sqlite_timestamps)
        for col, sd in saved.items():
            col.server_default = sd


def event_text():
    from sqlalchemy import text as sa_text

    return sa_text("CURRENT_TIMESTAMP")


def _fill_sqlite_timestamps(session: Session, flush_context: Any, instances: Any) -> None:
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
def mcp_agent_app(tmp_path: Path) -> Iterator[Flask]:
    base = dict(_BASE)
    base["database_url"] = f"sqlite:///{tmp_path / 'm4_agent.db'}"
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
        for name in ("users", "projects", "project_members", "operation_events")
    ]
    Base.metadata.create_all(engine, tables=tables)
    event.listen(Session, "before_flush", _fill_sqlite_timestamps)
    try:
        yield app
    finally:
        event.remove(Session, "before_flush", _fill_sqlite_timestamps)


def test_binding_m4_proxies_enforce_pinned_version_and_org(
    m4_binding_app: Flask, monkeypatch: pytest.MonkeyPatch
) -> None:
    """§13 M4 条 1 / D26：Logic/Action 代理强制绑定 pinned_version_id 与 project.org_id。"""
    settings = m4_binding_app.config["SETTINGS"]
    mock_adapter = MockOntologyAdapter()
    captured_calls: list[dict[str, Any]] = []

    orig_propose = mock_adapter.propose_action
    orig_logic = mock_adapter.run_logic

    def spy_propose(**kwargs: Any) -> dict[str, Any]:
        captured_calls.append({"fn": "propose_action", **kwargs})
        return orig_propose(**kwargs)

    def spy_logic(**kwargs: Any) -> dict[str, Any]:
        captured_calls.append({"fn": "run_logic", **kwargs})
        return orig_logic(**kwargs)

    monkeypatch.setattr(mock_adapter, "propose_action", spy_propose)
    monkeypatch.setattr(mock_adapter, "run_logic", spy_logic)
    monkeypatch.setattr(binding_service, "client_from_settings", lambda: mock_adapter)

    with m4_binding_app.app_context():
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

    client = m4_binding_app.test_client()

    # 1) run_logic：伪造 version_id/org_id 被忽略，强制 pinned + org
    r_logic = client.post(
        "/api/v1/projects/proj-alpha/ontology-bindings/bind-alpha-1/logic/trace_scope/run",
        headers={"Authorization": f"Bearer {token_a}"},
        json={
            "input": {"planned_qty": 100, "stock_qty": 80, "defect_rate": 0.02},
            "pinned_version_id": "ver-forged-999",
            "org_id": "org-forged",
        },
    )
    assert r_logic.status_code == 200, r_logic.get_json()
    assert r_logic.get_json()["data"]["result"] == 80
    assert captured_calls[-1]["version_id"] == "ver-seed-1-0-0"
    assert captured_calls[-1]["org_id"] == "org-alpha"

    # 2) propose：同上强制
    r_propose = client.post(
        "/api/v1/projects/proj-alpha/ontology-bindings/bind-alpha-1/actions/retention_extension/propose",
        headers={"Authorization": f"Bearer {token_a}"},
        json={
            "input": {
                "object_type_key": "batch",
                "external_pk_value": "BATCH-001",
                "ttl_seconds": 3600,
            },
            "pinned_version_id": "ver-forged-999",
            "org_id": "org-forged",
        },
    )
    assert r_propose.status_code == 201, r_propose.get_json()
    assert r_propose.get_json()["data"]["status"] == "pending"
    assert captured_calls[-1]["version_id"] == "ver-seed-1-0-0"
    assert captured_calls[-1]["org_id"] == "org-alpha"
    request_id = r_propose.get_json()["data"]["id"]

    # 3) 审批代理：代理把调用方身份映射为 runtime requested_by——同一用户经代理
    #    审批自己的提议 = I4 自批，runtime 403 原样透传（他人审批须换用户调用）
    r_self = client.post(
        f"/api/v1/projects/proj-alpha/ontology-bindings/bind-alpha-1/action-requests/{request_id}/approvals",
        headers={"Authorization": f"Bearer {token_a}"},
        json={"role": "business_owner", "decision": "approved"},
    )
    assert r_self.status_code == 403, r_self.get_json()

    # 4) 跨租户 User B 探测一律 404（S-01 零存在性泄露）
    r_cross = client.post(
        "/api/v1/projects/proj-alpha/ontology-bindings/bind-alpha-1/logic/trace_scope/run",
        headers={"Authorization": f"Bearer {token_b}"},
        json={"input": {"planned_qty": 1, "stock_qty": 2, "defect_rate": 0.5}},
    )
    assert r_cross.status_code == 404
    r_cross_propose = client.post(
        "/api/v1/projects/proj-alpha/ontology-bindings/bind-alpha-1/actions/retention_extension/propose",
        headers={"Authorization": f"Bearer {token_b}"},
        json={"input": {"object_type_key": "batch", "external_pk_value": "B", "ttl_seconds": 60}},
    )
    assert r_cross_propose.status_code == 404

    # 5) GET action request 视图
    r_get = client.get(
        f"/api/v1/projects/proj-alpha/ontology-bindings/bind-alpha-1/action-requests/{request_id}",
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert r_get.status_code == 200, r_get.get_json()
    assert r_get.get_json()["data"]["status"] in ("pending", "approved", "rejected")


def test_mcp_gateway_ontology_tool_tiering(mcp_agent_app: Flask) -> None:
    """D26：MCP 网关 ontology 三工具分级注册 + 执行档 run 面恒剥。"""
    from fde_api.agents.tools import AGENT_WRITE_DENIED_TOOLS
    from fde_api.control.mcp_gateway import TOOLS

    # 1) 注册与分级
    assert "ontology_logic_run" in TOOLS
    assert TOOLS["ontology_logic_run"][3] == "read"
    assert "ontology_action_propose" in TOOLS
    assert TOOLS["ontology_action_propose"][3] == "write_db"
    assert "ontology_action_execute" in TOOLS
    assert TOOLS["ontology_action_execute"][3] == "write_db"

    # 2) 执行档恒剥（强授权单独放行——与 api_execute 同列）
    assert "ontology_action_execute" in AGENT_WRITE_DENIED_TOOLS
    assert "ontology_action_propose" not in AGENT_WRITE_DENIED_TOOLS
    assert "ontology_logic_run" not in AGENT_WRITE_DENIED_TOOLS

    # 3) 工具组种子可装载（组引用未知工具 fail-fast）
    from fde_api.agents.tools import load_tool_groups

    groups = load_tool_groups()
    assert "ontology-agent" in groups
    assert "ontology_logic_run" in groups["ontology-agent"]
    assert "ontology_action_execute" not in groups["ontology-agent"]


def test_auth_error_with_forbidden_code_translates_to_403_not_502(m4_binding_app, monkeypatch):
    """演练 D4 实证缺陷修复：runtime I4 自批 403（body.code=forbidden）经代理必须
    原样 403 透传，不得混入"凭据配置错误 502"（授权拒绝 ≠ 配置错误）。"""
    from fde_api.integrations import service as svc
    from fde_api.integrations.ontology_client import OntologyAuthError

    class _ForbiddenClient:
        def propose_action(self, **kwargs):  # noqa: ANN001, ANN003
            return {"_status": 201, "id": "req-1", "status": "pending"}

        def approve_action(self, **kwargs):  # noqa: ANN001, ANN003
            raise OntologyAuthError({"code": "forbidden", "message": "requester cannot approve own action request (I4)"})

    monkeypatch.setattr(svc, "client_from_settings", lambda: _ForbiddenClient())

    with m4_binding_app.app_context():
        session = svc.db.session()
        user = User(
            id="u-forbidden",
            username="fb@x.test",
            role="project_lead",
            password_hash="x",
            is_active=True,
            must_change_password=False,
            auth_version=1,
            org_id="org-alpha",
        )
        proj = Project(
            id="proj-forbidden",
            project_code="PF-01",
            name="Forbidden Project",
            enterprise_code="ENT-PF",
            leader_user_id="u-forbidden",
            status="active",
            template_snapshot={},
            org_id="org-alpha",
            planned_start_date=date(2026, 11, 14),
        )
        member = ProjectMember(project_id="proj-forbidden", user_id="u-forbidden", role="member")
        binding = ProjectOntologyBinding(
            id="bind-fb-1",
            org_id="org-alpha",
            project_id="proj-forbidden",
            ontology_id="ont-x",
            pinned_version_id="ver-x",
            pinned_version="1.0.0",
            binding_role="primary",
            status="active",
            active_marker=ACTIVE_MARKER,
            bound_by_user_id="u-forbidden",
        )
        session.add_all([user, proj, member, binding])
        session.commit()

        with pytest.raises(svc.BindingError) as raised:
            svc.approve_binding_action(
                actor=user,
                project_id="proj-forbidden",
                binding_id="bind-fb-1",
                request_id="req-1",
                payload={"role": "business_owner", "decision": "approved"},
            )
    assert raised.value.status == 403, f"授权拒绝必须 403，实际 {raised.value.status}"
    assert raised.value.code == "forbidden"
