"""借鉴登记 #9：只读执行事实链 /projects/{id}/execution-facts（can_view）。

- 三源归并：project_evidence + operation_events（项目维度，过滤下推 SQL）+
  ai_call_audits（**账号维度**——该表无项目外键，响应明示 scope="actor"，
  不得假装项目维度）。
- 时间倒序、limit 有界（默认 50 / 上限 200）+ truncated；非法 limit/fact_type 400。
- 权限：can_view 读（viewer 成员 200）、外人 403、项目不存在 404。
- 红线钉子：①operation_events 的 changes 大载荷不外泄（响应无 changes 键）；
  ②ai_call_audit 只投影调用事实元数据，无明文上下文；③只读面——无任何写路径；
  ④有意不进 api_catalog（AI 不经此面读审计原始流，与证据登记同纪律）。
- 「外部完成无真实回执=未知」：ai_call_audit.status 只有
  succeeded/failed/budget_blocked 三值，模型自述不作完成证据——断言响应
  不存在"completed/ok"类编造字段。
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy import update

from test_document_drafts_api import _persist_project
from test_evidence_registry import _user_client
from test_gates_api import AuthorizedClient, admin_client, gate_project  # noqa: F401  (pytest fixture)

from conftest import INITIAL_PASSWORD
from fde_api.auth.models import User
from fde_api.auth.passwords import hash_password
from fde_api.auth.tokens import issue_access_token
from fde_api.control.api_catalog import CATALOG
from fde_api.evidence.models import ProjectEvidence
from fde_api.evidence.service import upsert_evidence
from fde_api.workbench.models import AICallAudit, OperationEvent, ProjectMember


def _sha(seed: str) -> str:
    return hashlib.sha256(seed.encode()).hexdigest()


def _outsider_client(client, db_session, settings) -> AuthorizedClient:
    user = User(
        username=f"facts.outsider.{uuid4().hex[:8]}",
        display_name="Facts Outsider",
        role="fde_engineer",
        password_hash=hash_password(INITIAL_PASSWORD),
        must_change_password=False,
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()
    return AuthorizedClient(
        client, user, {"Authorization": f"Bearer {issue_access_token(user, settings)}"}
    )


def _add_operation_event(db_session, project_id: str, actor_id: str, *, occurred_at: datetime, marker: str) -> OperationEvent:
    row = OperationEvent(
        actor_user_id=actor_id,
        project_id=project_id,
        target_type="gate",
        target_id=f"gate-{marker}",
        event_type=f"gate.status_changed.{marker}",
        occurred_at=occurred_at,
        changes={"secret_payload": marker, "before": "x", "after": "y"},
    )
    db_session.add(row)
    db_session.commit()
    return row


def _add_ai_audit(db_session, actor_id: str, *, created_at: datetime, status: str = "succeeded") -> AICallAudit:
    row = AICallAudit(
        request_id=f"req-{uuid4().hex[:12]}",
        actor_user_id=actor_id,
        purpose="chat",
        model="test-model",
        used_fallback=False,
        duration_ms=120,
        input_tokens=10,
        output_tokens=20,
        status=status,
    )
    db_session.add(row)
    db_session.flush()
    # 绕过 server_default：直接写时间做排序锚点
    db_session.execute(
        update(AICallAudit)
        .where(AICallAudit.id == row.id)
        .values(created_at=created_at, updated_at=created_at)
    )
    db_session.commit()
    return row


def test_facts_merge_three_sources_desc_and_hide_changes(admin_client, gate_project, db_session) -> None:
    project, _gates_url, leader_client = gate_project
    base = f"/api/v1/projects/{project['id']}/execution-facts"
    old = datetime(2027, 1, 1, 8, 0, 0, tzinfo=timezone.utc)
    new = datetime(2027, 1, 5, 9, 0, 0, tzinfo=timezone.utc)
    ev_row, _created = upsert_evidence(
        db_session, project_id=project["id"], kind="gate",
        source_uri="fdeops://somwyn/.fde/gates/G1.md", content_sha256=_sha("ev-old"),
    )
    db_session.flush()
    db_session.execute(
        update(ProjectEvidence)
        .where(ProjectEvidence.id == ev_row.id)
        .values(created_at=old, updated_at=old)
    )
    db_session.commit()
    _add_operation_event(db_session, project["id"], leader_client.user.id, occurred_at=old, marker="old")
    _add_operation_event(db_session, project["id"], leader_client.user.id, occurred_at=new, marker="new")
    _add_ai_audit(db_session, admin_client.user.id, created_at=new + timedelta(hours=1))

    resp = admin_client.get(base)
    assert resp.status_code == 200, resp.get_data(as_text=True)
    data = resp.json["data"]
    assert data["project_id"] == project["id"]
    assert data["ai_call_audit_scope"] == "actor"
    assert data["counts"]["evidence"] == 1
    assert data["counts"]["ai_call_audit"] == 1
    my_ops = [
        i for i in data["items"]
        if i["fact_type"] == "operation_event" and i["event_type"].startswith("gate.status_changed.")
    ]
    assert len(my_ops) == 2
    assert data["truncated"] is False

    # 时间倒序：AI 审计（最新）在首；两条自插事件 new 在 old 前
    items = data["items"]
    assert items[0]["fact_type"] == "ai_call_audit"
    assert my_ops[0]["event_type"].endswith(".new") and my_ops[1]["event_type"].endswith(".old")

    # 红线钉子①：changes 大载荷不外泄
    op_items = [i for i in items if i["fact_type"] == "operation_event"]
    assert all("changes" not in i for i in op_items)
    assert all("secret_payload" not in str(i) for i in op_items)

    # 红线钉子②：AI 审计无明文上下文字段
    ai_items = [i for i in items if i["fact_type"] == "ai_call_audit"]
    assert all(set(i) <= {
        "fact_type", "id", "request_id", "actor_user_id", "purpose", "model",
        "used_fallback", "status", "error_code", "duration_ms",
        "input_tokens", "output_tokens", "created_at",
    } for i in ai_items)
    # 「未知不编造」：响应不存在完成类编造字段
    assert all("completed" not in i and "outcome" not in i for i in ai_items)


def test_facts_actor_scope_isolates_ai_audits(admin_client, gate_project, db_session) -> None:
    project, _gates_url, leader_client = gate_project
    base = f"/api/v1/projects/{project['id']}/execution-facts"
    # admin 名下一条约：viewer/leader 名下的 AI 审计不应出现在 admin 的账号维度流里
    _add_ai_audit(db_session, leader_client.user.id, created_at=datetime(2027, 1, 3, 10, 0, 0, tzinfo=timezone.utc))
    resp = admin_client.get(base)
    assert resp.status_code == 200
    data = resp.json["data"]
    # leader 名下的审计不进 admin 的账号维度流；counts.ai_call_audit 也按 actor 过滤后计数
    assert data["counts"]["ai_call_audit"] == 0
    ai_items = [i for i in data["items"] if i["fact_type"] == "ai_call_audit"]
    # 账号维度过滤下推：admin 只看到自己的（此处无 → 空），scope 明示 actor
    assert ai_items == []
    assert data["ai_call_audit_scope"] == "actor"

    # fact_type=ai_call_audit 时同样只回 actor 自己的
    resp2 = admin_client.get(f"{base}?fact_type=ai_call_audit")
    assert resp2.status_code == 200
    assert resp2.json["data"]["items"] == []
    assert resp2.json["data"]["counts"]["ai_call_audit"] == 0


def test_facts_filter_and_limit(admin_client, gate_project, db_session) -> None:
    project, _gates_url, leader_client = gate_project
    base = f"/api/v1/projects/{project['id']}/execution-facts"
    for n in range(3):
        _add_operation_event(
            db_session, project["id"], leader_client.user.id,
            occurred_at=datetime(2027, 1, 2, 10, n, 0, tzinfo=timezone.utc), marker=f"n{n}",
        )
    resp = admin_client.get(f"{base}?fact_type=operation_event&limit=2")
    assert resp.status_code == 200
    data = resp.json["data"]
    assert data["counts"]["operation_event"] >= 3  # fixture 流程事件 + 自插 3 条
    my_ops = [i for i in data["items"] if i["event_type"].startswith("gate.status_changed.")]
    assert len(my_ops) == 2 and data["truncated"] is True and data["limit"] == 2
    # 倒序取最新两条
    assert my_ops[0]["event_type"].endswith(".n2") and my_ops[1]["event_type"].endswith(".n1")

    # 非法参数
    assert admin_client.get(f"{base}?limit=0").status_code == 400
    assert admin_client.get(f"{base}?limit=201").status_code == 400
    assert admin_client.get(f"{base}?fact_type=nope").status_code == 400


def test_facts_permissions_and_catalog_exclusion(admin_client, gate_project, db_session, client, settings) -> None:
    project, _gates_url, _leader = gate_project
    base = f"/api/v1/projects/{project['id']}/execution-facts"
    # viewer 成员 can_view 200
    viewer_client = _user_client(client, db_session, settings, role="fde_engineer")
    db_session.add(ProjectMember(project_id=project["id"], user_id=viewer_client.user.id, role="viewer"))
    db_session.commit()
    assert viewer_client.get(base).status_code == 200
    # 外人 403
    assert _outsider_client(client, db_session, settings).get(base).status_code == 403
    # 项目不存在 404
    assert admin_client.get(f"/api/v1/projects/{uuid4()}/execution-facts").status_code == 404
    # 红线钉子④：不进 api_catalog（CATALOG 是 id→row 映射，row 带 path）
    assert not any(
        "execution-facts" in str(row.get("path", ""))
        for row in CATALOG.values()
    )
