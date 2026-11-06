"""B#13-D：跨域到期只读投影（admin-only 只读 union，零 DDL）合同钉。

立项契约 §2 六字段逻辑视图 + §5 B#13-D 触发条件（2026-11-06 用户明确
指示实施）：只读纪律（投影不写回、不触发转换器）；api_confirmation
截止时刻复用 B#13-C 单一窗口常量（模块属性访问，变异敏感）；
admin-only；元数据白名单（不外泄 body/arguments/对象键）。
"""
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from fde_api.control import api_actions
from fde_api.control.models import AutomationApproval
from fde_api.dispatch.models import DeliveryPackage, DispatchOffer
from fde_api.expirations import EXPIRY_ACTIONS, collect_expiration_entries
from fde_api.files.models import UploadSession
from fde_api.solutions.models import ProjectSolution
from test_api_confirmation_expiry import _awaiting_action
from test_ai_server_chat_mcp import access_headers, ai_context, make_project

REQUIRED_KEYS = {"domain", "object_id", "deadline_at", "state", "due", "expiry_action"}


def _upload(db_session, project, user, *, expires_at, status="uploading"):
    row = UploadSession(project_id=project.id, name="projection-upload.bin",
        expected_size_bytes=10, bucket="test-bucket", storage_prefix=f"tmp/{uuid4().hex}",
        multipart_upload_id=uuid4().hex, expires_at=expires_at, status=status,
        requested_by_user_id=user.id, idempotency_key=uuid4().hex)
    db_session.add(row)
    db_session.commit()  # 投影/路由走独立会话（读已提交），必须先提交
    return row


def _approval(db_session, project, user, *, expires_at, status="pending"):
    row = AutomationApproval(project_id=project.id, requested_by_user_id=user.id,
        request_key=f"req-{uuid4().hex[:12]}", capability="solutions.export_sow",
        tool_name="export_sow", arguments_json={}, arguments_sha256="a" * 64,
        risk_level=3, status=status, expires_at=expires_at)
    db_session.add(row)
    db_session.commit()
    return row


def _offer(db_session, project, candidate, *, mode="assign", offered_at,
           response_window_hours=24, status="offered"):
    solution = ProjectSolution(project_id=project.id, name="投影测试方案",
        owner_user_id=project.leader_user_id)
    db_session.add(solution)
    db_session.flush()
    package = DeliveryPackage(id=uuid4().hex, solution_id=solution.id,
        project_id=project.id, package_code="PKJ-" + uuid4().hex[:8].upper(),
        dispatch_status="offered", response_window_hours=response_window_hours)
    db_session.add(package)
    db_session.flush()
    offer = DispatchOffer(package_id=package.id, dispatch_round=1,
        candidate_user_id=candidate.id, status=status, offered_at=offered_at,
        match_breakdown={"mode": mode})
    db_session.add(offer)
    db_session.commit()
    return offer, package


def _by_domain(entries):
    return {entry["domain"]: entry for entry in entries}


def test_admin_only_and_six_field_shape(ai_context, client, settings, db_session):
    users, _execute = ai_context
    admin = users["admin"]
    project = make_project(db_session, admin)
    _upload(db_session, project, admin,
            expires_at=datetime.now(UTC) - timedelta(minutes=1))
    denied = client.get("/api/v1/expirations", headers=access_headers(users["alice"], settings))
    assert denied.status_code == 403
    assert denied.json["error"]["code"] == "forbidden"
    allowed = client.get("/api/v1/expirations", headers=access_headers(admin, settings))
    assert allowed.status_code == 200
    items = allowed.json["data"]["items"]
    assert len(items) == allowed.json["data"]["total"] == 1
    assert set(items[0]) == REQUIRED_KEYS
    assert items[0]["domain"] == "upload_session"
    assert items[0]["expiry_action"] == EXPIRY_ACTIONS["upload_session"]


def test_four_domains_projected_with_native_states(ai_context, db_session):
    users, _execute = ai_context
    admin = users["admin"]
    now = datetime.now(UTC)
    project = make_project(db_session, admin)
    _upload(db_session, project, admin, expires_at=now - timedelta(minutes=5))
    _approval(db_session, project, admin, expires_at=now + timedelta(hours=2))
    _offer(db_session, project, users["alice"], mode="assign",
           offered_at=now - timedelta(hours=1), response_window_hours=24)
    _awaiting_action(ai_context, db_session)
    entries = collect_expiration_entries()
    assert {entry["domain"] for entry in entries} == set(EXPIRY_ACTIONS)
    view = _by_domain(entries)
    assert view["upload_session"]["state"] == "uploading"
    assert view["upload_session"]["due"] is True
    assert view["automation_approval"]["state"] == "pending"
    assert view["automation_approval"]["due"] is False
    assert view["dispatch_offer"]["state"] == "offered"
    assert view["dispatch_offer"]["due"] is False
    assert view["api_confirmation"]["state"] == "awaiting_confirmation"
    # 稳定排序：deadline_at 升序（due 的上传会话在最前）
    assert entries[0]["domain"] == "upload_session"


def test_boundary_due_is_inclusive_in_projection(ai_context, db_session):
    users, _execute = ai_context
    project = make_project(db_session, users["admin"])
    moment = datetime(2026, 11, 6, 9, 0, 0, tzinfo=UTC)
    row = _upload(db_session, project, users["admin"], expires_at=moment)
    at_boundary = collect_expiration_entries(now=moment, domain="upload_session")
    assert [entry["due"] for entry in at_boundary] == [True]  # 等于边界也到期
    before = collect_expiration_entries(
        now=moment - timedelta(microseconds=1), domain="upload_session")
    assert [entry["due"] for entry in before] == [False]
    assert before[0]["object_id"] == row.id


def test_api_confirmation_deadline_shares_window_constant(ai_context, db_session, monkeypatch):
    _awaiting_action(ai_context, db_session)
    first = collect_expiration_entries(domain="api_confirmation")
    assert len(first) == 1
    monkeypatch.setattr(
        "fde_api.control.api_actions.CONFIRMATION_WINDOW", timedelta(minutes=30))
    second = collect_expiration_entries(domain="api_confirmation")
    assert second[0]["object_id"] == first[0]["object_id"]
    from datetime import datetime as _dt
    shift = (_dt.fromisoformat(second[0]["deadline_at"])
             - _dt.fromisoformat(first[0]["deadline_at"]))
    assert shift == timedelta(minutes=15)  # 窗口放大 15 分钟 ⇒ 投影同步位移


def test_terminal_states_are_excluded(ai_context, db_session):
    users, _execute = ai_context
    admin = users["admin"]
    now = datetime.now(UTC)
    project = make_project(db_session, admin)
    _upload(db_session, project, admin, expires_at=now - timedelta(minutes=1),
            status="completed")
    _approval(db_session, project, admin, expires_at=now - timedelta(minutes=1),
              status="approved")
    _offer(db_session, project, users["alice"], offered_at=now - timedelta(hours=1),
           status="accepted")
    _user, _project, identifier, password = _awaiting_action(ai_context, db_session)
    from fde_api.control.api_actions import decide_action
    assert decide_action(admin, identifier, password)["status"] == "completed"
    entries = collect_expiration_entries()
    assert entries == []


def test_started_confirmation_not_projected(ai_context, db_session):
    """started-but-uncertain 不属于可到期等待集（与 pending 列表同则）。"""
    users, _execute = ai_context
    _user, project, identifier, _password = _awaiting_action(ai_context, db_session)
    from fde_api.workbench.models import OperationEvent
    db_session.add(OperationEvent(actor_user_id=users["admin"].id,
        project_id=project.id, target_type="ai_api_action", target_id=identifier,
        event_type="ai.api.started", changes={}))
    db_session.commit()
    assert collect_expiration_entries(domain="api_confirmation") == []


def test_filters_and_validation(ai_context, client, settings, db_session):
    users, _execute = ai_context
    admin = users["admin"]
    project = make_project(db_session, admin)
    now = datetime.now(UTC)
    _upload(db_session, project, admin, expires_at=now - timedelta(minutes=1))
    _upload(db_session, project, admin, expires_at=now + timedelta(hours=1))
    _approval(db_session, project, admin, expires_at=now + timedelta(hours=2))

    only_domain = client.get("/api/v1/expirations?domain=upload_session",
                             headers=access_headers(admin, settings))
    assert only_domain.status_code == 200
    assert {row["domain"] for row in only_domain.json["data"]["items"]} == {"upload_session"}
    assert only_domain.json["data"]["total"] == 2

    only_due = client.get("/api/v1/expirations?due=true",
                          headers=access_headers(admin, settings))
    items = only_due.json["data"]["items"]
    assert len(items) == 1 and items[0]["domain"] == "upload_session"
    assert items[0]["due"] is True

    limited = client.get("/api/v1/expirations?limit=1",
                         headers=access_headers(admin, settings))
    assert limited.json["data"]["total"] == 1

    for query, code in (("domain=bogus", "invalid_domain"), ("due=maybe", "invalid_request"),
                        ("limit=abc", "invalid_request"), ("limit=501", "invalid_request")):
        response = client.get(f"/api/v1/expirations?{query}",
                              headers=access_headers(admin, settings))
        assert response.status_code == 400, query
        assert response.json["error"]["code"] == code, query


def test_dispatch_offer_deadline_uses_response_window(ai_context, db_session):
    users, _execute = ai_context
    now = datetime.now(UTC)
    project = make_project(db_session, users["admin"])
    offer, _package = _offer(db_session, project, users["alice"], mode="assign",
                             offered_at=now - timedelta(hours=1), response_window_hours=24)
    entries = collect_expiration_entries(domain="dispatch_offer")
    assert len(entries) == 1 and entries[0]["object_id"] == offer.id
    from datetime import datetime as _dt
    deadline = _dt.fromisoformat(entries[0]["deadline_at"])
    assert deadline == (now - timedelta(hours=1) + timedelta(hours=24)).astimezone(UTC)
    assert entries[0]["due"] is False
    assert entries[0]["expiry_action"] == \
        "fde_api.dispatch.offer_service.expire_stale_offers"
