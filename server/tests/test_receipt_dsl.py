"""借鉴登记 #7：回执 DSL 一期（ask + later）。

- **未知字段拒绝**：DSL 顶层与 action 内任一未知键即拒绝（指出字段名）——
  外部可写结构的白名单纪律（否则多写一个键就能绕过闸门）。
- **容量上限**：整份 DSL 规范化序列化超 64KB 即拒绝（不截断）。
- **ask 落既有 automation_approvals**：零新表零新路由；幂等（同 request_key
  复用既有 pending 审批）；敏感键拒绝；能力不在白名单则拒绝；风险档固定 4。
- **later 落最小到期挂点**（operation_events）：只表达复查时点，**不实现**
  统一到期表/主动超时扫描（那是 B#13 的职责，本条不越界）。
- **失败走 B#2 降级路径**：DSL 不可解析 → ReceiptDslError，调用方据此落
  独立终态 succeeded_but_receipt_invalid（拒绝同键重跑）。
- 红线钉子：①DSL 不进 api_catalog（AI 经既有通道投递，非 catalog 面）；
  ②later 挂点无主动扫描器（本条不引入自动到期动作）；
  ③审批材料与 later 载荷同样受敏感键扫描与 64KB 上限约束。
"""
from __future__ import annotations

import json
from uuid import uuid4

from sqlalchemy import select

from test_gates_api import admin_client, gate_project  # noqa: F401  (pytest fixture)

from fde_api.agents.receipt import (
    RECEIPT_DSL_MAX_BYTES,
    ReceiptDslError,
    as_ask,
    as_later,
    parse_receipt_dsl,
    receipt_dsl_fingerprint,
    request_ask,
    request_later,
)
from fde_api.control.models import AutomationApproval
from fde_api.workbench.models import OperationEvent


def test_dsl_rejects_unknown_fields_and_bad_shapes() -> None:
    # 顶层未知字段
    try:
        parse_receipt_dsl({"action": {"kind": "ask", "capability": "project.read"}, "bogus": 1})
        raise AssertionError("顶层未知字段应被拒绝")
    except ReceiptDslError as exc:
        assert exc.code == "invalid_receipt"
        assert "bogus" in exc.message  # 精确到出错路径（top_extra）
        assert exc.message.count("action.") == 0
    # action 内未知字段
    try:
        parse_receipt_dsl({"action": {"kind": "ask", "capability": "project.read", "x": 1}})
        raise AssertionError("action 未知字段应被拒绝")
    except ReceiptDslError as exc:
        assert "action.ask.x" in exc.message  # 判别联合只报命中分支
    # 非对象
    bad_values: list[object] = [[], "x", 3, None]
    for bad in bad_values:
        try:
            parse_receipt_dsl(bad)
            raise AssertionError(f"非对象应被拒绝：{bad!r}")
        except ReceiptDslError as exc:
            assert exc.code == "invalid_receipt"
    # 未知动作
    try:
        parse_receipt_dsl({"action": {"kind": "whatever"}})
        raise AssertionError("未知动作应被拒绝")
    except ReceiptDslError as exc:
        assert "action.kind" in exc.message
        assert "ask/later" in exc.message  # 合法 kind 集合来自模型自身


def test_dsl_enforces_capacity_limit() -> None:
    ok = {"action": {"kind": "ask", "capability": "project.read", "reason": "x" * 100}}
    assert parse_receipt_dsl(ok).action.kind == "ask"
    # 超限：reason 撑爆 64KB
    big = {"action": {"kind": "ask", "capability": "project.read", "reason": "x" * (RECEIPT_DSL_MAX_BYTES + 10)}}
    try:
        parse_receipt_dsl(big)
        raise AssertionError("超容量应被拒绝")
    except ReceiptDslError as exc:
        assert exc.code == "receipt_too_large"


def test_dsl_fingerprint_is_stable_and_order_insensitive() -> None:
    a = {"action": {"kind": "ask", "capability": "project.read", "reason": "r"}}
    b = {"action": {"reason": "r", "capability": "project.read", "kind": "ask"}}
    assert receipt_dsl_fingerprint(a) == receipt_dsl_fingerprint(b)
    c = {"action": {"kind": "ask", "capability": "project.read", "reason": "r2"}}
    assert receipt_dsl_fingerprint(a) != receipt_dsl_fingerprint(c)


def test_ask_creates_approval_and_is_idempotent(admin_client, gate_project, db_session) -> None:
    project, _gates_url, _leader = gate_project
    action = as_ask(parse_receipt_dsl(
        {"action": {"kind": "ask", "capability": "project.read", "reason": "需人工确认"}}
    ).action)
    first = request_ask(
        project_id=project["id"], requested_by=admin_client.user, action=action
    )
    assert first["created"] is True and first["status"] == "pending"
    second = request_ask(
        project_id=project["id"], requested_by=admin_client.user, action=action
    )
    # 幂等：同 request_key 复用既有 pending 审批，不重复建单
    assert second["created"] is False
    assert second["approval_id"] == first["approval_id"]

    row = db_session.get(AutomationApproval, first["approval_id"])
    assert row is not None
    assert row.tool_name == "agent.receipt.ask"
    assert row.capability == "project.read"
    assert row.risk_level == 4  # 人工门 = 保守高险
    assert row.status == "pending"
    assert row.arguments_sha256 and len(row.arguments_sha256) == 64
    assert row.arguments_json["kind"] == "agent.receipt.ask"
    # 敏感键不得进审批材料
    assert "password" not in json.dumps(row.arguments_json, ensure_ascii=False).lower()


def test_ask_rejects_unknown_capability(admin_client, gate_project) -> None:
    project, _gates_url, _leader = gate_project
    # 能力不在白名单 → 解析层允许（字符串合法）但授权层拒绝
    action = as_ask(parse_receipt_dsl(
        {"action": {"kind": "ask", "capability": "definitely.not.a.capability"}}
    ).action)
    try:
        request_ask(project_id=project["id"], requested_by=admin_client.user, action=action)
        raise AssertionError("未知能力应被拒绝")
    except ReceiptDslError as exc:
        assert exc.code in ("capability_unknown", "permission_revoked")


def test_ask_rejects_sensitive_arguments(admin_client, gate_project) -> None:
    project, _gates_url, _leader = gate_project
    action = as_ask(parse_receipt_dsl(
        {"action": {"kind": "ask", "capability": "project.read", "reason": "r"}}
    ).action)
    try:
        request_ask(
            project_id=project["id"],
            requested_by=admin_client.user,
            action=action,
            context={"api_key": "super-secret"},
        )
        raise AssertionError("敏感键应被拒绝")
    except ReceiptDslError as exc:
        assert exc.code == "sensitive_argument_rejected"


def test_later_records_minimal_due_hook_only(admin_client, gate_project, db_session) -> None:
    project, _gates_url, _leader = gate_project
    action = as_later(parse_receipt_dsl(
        {"action": {"kind": "later", "delay_minutes": 60, "reason": "等客户回信"}}
    ).action)
    result = request_later(
        project_id=project["id"], requested_by=admin_client.user, action=action
    )
    assert result["delay_minutes"] == 60
    assert result["due_at"]
    event = db_session.get(OperationEvent, result["event_id"])
    assert event is not None
    assert event.event_type == "agent.receipt.later_requested"
    assert event.target_type == "agent_receipt"
    assert event.project_id == project["id"]
    assert event.changes["delay_minutes"] == 60
    assert event.changes["due_at"] == result["due_at"]
    # 边界：later 只表达时点，**不得**引入主动扫描器/到期动作
    assert set(event.changes) == {"due_at", "delay_minutes", "reason", "sha256"}


def test_later_rejects_out_of_range_delay() -> None:
    # 解析层即拒：delay_minutes 超出上限（永不复查伪装成延后）
    try:
        parse_receipt_dsl({"action": {"kind": "later", "delay_minutes": 0}})
        raise AssertionError("delay=0 应被拒绝")
    except ReceiptDslError as exc:
        assert "action.later.delay_minutes" in exc.message
    try:
        parse_receipt_dsl({"action": {"kind": "later", "delay_minutes": 60 * 24 * 31}})
        raise AssertionError("超上限 delay 应被拒绝")
    except ReceiptDslError as exc:
        assert "action.later.delay_minutes" in exc.message
