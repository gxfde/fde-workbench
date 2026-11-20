"""AE1-WP4：审计日志与成本登记（53 号 §3 WP4；契约 U1 ``$defs/AuditObject`` /
``$defs/CostObject`` v1.0.6 FROZEN）。

WP4 交付面＝``action_execution_logs`` 表（append-only 迁移）＋审计写入函数＋
本文件钉＋敏感键 grep 闸。验收六条逐条落钉（53 号 §3 WP4 行）：

1. **9 必填字段齐备**（契约 ``$defs/AuditObject``，``additionalProperties=false``
   ／``required`` 九项）——写型真执行 ``approval_id`` 非 null、干跑可 null；
2. **三敏感键**（``access_token`` / ``refresh_token`` / ``client_secret``）在
   应用日志、审计表、响应体三处**全文 0 命中**（51:142、U4b ``:79-89``）；
3. **哨兵值**（``AE-SENTINEL-SECRET-0001``）同样三处 0 命中（U2:283）；
4. ``params_sha256`` 为 64 位小写 hex 且**不等于任何参数值明文**（U2:284）；
5. 上游响应体**整段不回显**进审计/错误/输出——审计表是窄列结构，无 params
   与 output 的 JSON 自由载体（白名单 ``constraints.response_body_zero_echo``）；
6. 成本登记 ``tool_calls`` / ``duration_ms`` / ``estimated_usd``，T4 单任务
   累计 ≤ $0.10（51:213、契约 ``$defs/CostObject``）。

纪律：审计表**只增不改**（无 PATCH/DELETE 面；复放不落新行；同一
``execution_id`` 恰一行）；租户面按 ``org_id`` 值存（复用 orgs 标识体系，
禁自造 ``tenant_id``）。
"""
from __future__ import annotations

import hashlib
import json
import logging
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import pytest

from multi_tenant_harness import make_enterprise_org, make_project, make_user

AUDIT_REQUIRED = (
    "connector_id",
    "method",
    "params_sha256",
    "actor_user_id",
    "org_id",
    "approval_id",
    "started_at",
    "finished_at",
    "duration_ms",
)
COST_REQUIRED = ("tool_calls", "duration_ms", "estimated_usd")

SENSITIVE_KEYS = ("access_token", "refresh_token", "client_secret")
SENTINEL = "AE-SENTINEL-SECRET-0001"
SHA256_HEX = __import__("re").compile(r"^[0-9a-f]{64}$")

T4_TASK_BUDGET_USD = 0.10  # 51 号 §6.2 T4 单任务预算上限


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _sha(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _request(**overrides) -> dict[str, Any]:
    req: dict[str, Any] = {
        "action_id": "mock.email.send",
        "action_type": "send_email",
        "connector_id": "mock.email",
        "method": "send",
        "params": {"to": "ops@example.test", "subject": "s-1", "body": "b-1"},
        "idempotency_key": "idem-wp4-" + uuid4().hex[:8],
        "org_id": "pending",
        "requester_id": "pending",
        "dry_run": False,
        "risk_level": 2,
        "timeout_seconds": 30,
        "approval_id": None,
    }
    req.update(overrides)
    return req


class RecordingDispatch:
    """可计数 dispatch 桩：外呼计数即副作用计数。"""

    def __init__(self, product: dict[str, Any] | None = None) -> None:
        self.calls = 0
        self.product = product

    def call(self, request: dict) -> dict[str, Any]:
        self.calls += 1
        if self.product is not None:
            return dict(self.product)
        return {"message_id": f"msg-{self.calls}", "delivered_count": 1}


class AllowAllWhitelist:
    def check(self, connector_id: str, method: str) -> None:
        return None


@pytest.fixture
def ae_world(db_session):
    org = make_enterprise_org(db_session)
    actor = make_user(db_session, "project_lead", org_id=org.id)
    org_b = make_enterprise_org(db_session)
    actor_b = make_user(db_session, "project_lead", org_id=org_b.id)
    project = make_project(db_session, actor, code=f"AEL{uuid4().hex[:6]}", org_id=org.id)
    db_session.commit()
    return {"org": org, "actor": actor, "org_b": org_b, "actor_b": actor_b, "project": project}


def _rows(session) -> list[Any]:
    from fde_api.action_execution.models import ActionExecutionLog

    return list(session.query(ActionExecutionLog).all())


def _row_for(session, execution_id: str):
    from fde_api.action_execution.models import ActionExecutionLog

    return (
        session.query(ActionExecutionLog)
        .filter(ActionExecutionLog.execution_id == execution_id)
        .one_or_none()
    )


def _row_dump(row: Any) -> str:
    """审计行的全列序列化（用于「明文 0 命中」扫描）。"""
    return _canonical(
        {
            "id": row.id,
            "execution_id": row.execution_id,
            "connector_id": row.connector_id,
            "method": row.method,
            "params_sha256": row.params_sha256,
            "actor_user_id": row.actor_user_id,
            "org_id": row.org_id,
            "approval_id": row.approval_id,
            "started_at": str(row.started_at),
            "finished_at": str(row.finished_at),
            "duration_ms": row.duration_ms,
            "tool_calls": row.tool_calls,
            "estimated_usd": float(row.estimated_usd),
        }
    )


def _submit(world, *, dispatch: Any = None, **overrides) -> tuple[dict[str, Any], Any]:
    from fde_api.action_execution import service as svc

    payload = _request(org_id=world["org"].id, requester_id=world["actor"].id, **overrides)
    dispatcher = dispatch if dispatch is not None else RecordingDispatch()
    result = svc.submit_action(
        actor=world["actor"], payload=payload, whitelist_gate=AllowAllWhitelist(), dispatch=dispatcher
    )
    return result, dispatcher


def _make_approval(db_session, world, *, params: dict[str, Any]) -> Any:
    from fde_api.control.models import AutomationApproval

    approval = AutomationApproval(
        run_id=None,
        workflow_node_run_id=None,
        project_id=world["project"].id,
        requested_by_user_id=world["actor"].id,
        reviewed_by_user_id=world["actor"].id,
        request_key=f"ae-{uuid4().hex[:12]}",
        capability="action_execution.invoke",
        tool_name="action_execution.execute",  # 评审 D2 甲案：审批绑定比对
        arguments_json=params,
        arguments_sha256=_sha(params),
        risk_level=3,
        status="approved",
        expires_at=datetime.now(UTC) + timedelta(days=1),
    )
    db_session.add(approval)
    db_session.commit()
    return approval


# ---- ① 9 必填字段齐备 --------------------------------------------------------


class TestAuditObjectShape:
    def test_audit_log_row_carries_nine_required_fields(self, db_session, ae_world) -> None:
        """契约 $defs/AuditObject：九必填字段逐项落库且与结果对象一致。"""
        result, _ = _submit(ae_world)
        db_session.expire_all()
        row = _row_for(db_session, result["execution_id"])
        assert row is not None, "成功执行必须落一条审计行"
        for field in AUDIT_REQUIRED:
            assert hasattr(row, field), f"审计表缺列：{field}"
        assert row.connector_id == result["audit"]["connector_id"]
        assert row.method == result["audit"]["method"]
        assert row.params_sha256 == result["audit"]["params_sha256"]
        assert row.actor_user_id == result["audit"]["actor_user_id"]
        assert row.org_id == result["audit"]["org_id"]
        assert row.started_at is not None and row.finished_at is not None
        assert row.duration_ms >= 0

    def test_audit_object_has_exactly_nine_keys_no_extra(self, db_session, ae_world) -> None:
        """``additionalProperties=false``：审计对象不得夹带额外键。"""
        result, _ = _submit(ae_world)
        assert set(result["audit"]) == set(AUDIT_REQUIRED), sorted(result["audit"])

    def test_audit_approval_id_null_for_dry_run(self, db_session, ae_world) -> None:
        """干跑可 null（契约 ``:108`` 口径）。"""
        result, _ = _submit(ae_world, dry_run=True)
        db_session.expire_all()
        row = _row_for(db_session, result["execution_id"])
        assert row is not None
        assert result["audit"]["approval_id"] is None
        assert row.approval_id is None

    def test_audit_approval_id_non_null_for_risk3_real_execution(self, db_session, ae_world) -> None:
        """写型真执行（risk≥3）``approval_id`` **不得**为 null（契约 ``:108``）。"""
        params = {"to": "ops@example.test", "subject": "s-1", "body": "b-1"}
        approval = _make_approval(db_session, ae_world, params=params)
        result, dispatch = _submit(
            ae_world, risk_level=3, approval_id=approval.id, dry_run=False
        )
        db_session.expire_all()
        row = _row_for(db_session, result["execution_id"])
        assert dispatch.calls == 1
        assert row is not None
        assert result["audit"]["approval_id"] == approval.id
        assert row.approval_id == approval.id


# ---- ② 三敏感键 + ③ 哨兵值：三处 0 命中 -------------------------------------


class TestZeroPlaintext:
    def test_sentinel_zero_hit_in_audit_and_response(self, db_session, ae_world) -> None:
        """哨兵值进 params → 审计行与响应体全文 0 命中（U2:283）。"""
        result, _ = _submit(ae_world, params={"to": SENTINEL, "subject": SENTINEL, "body": SENTINEL})
        db_session.expire_all()
        row = _row_for(db_session, result["execution_id"])
        assert row is not None
        assert SENTINEL not in _canonical(result)
        assert SENTINEL not in _row_dump(row)

    def test_sentinel_zero_hit_in_application_log(self, db_session, ae_world, caplog) -> None:
        """哨兵值不得进应用日志（caplog 全文扫描）。"""
        with caplog.at_level(logging.DEBUG, logger="fde_api.action_execution"):
            _submit(ae_world, params={"to": SENTINEL, "subject": SENTINEL, "body": SENTINEL})
        assert SENTINEL not in caplog.text

    def test_three_sensitive_keys_zero_hit_everywhere(self, db_session, ae_world, caplog) -> None:
        """三敏感键在响应体、审计行、应用日志三处 0 命中（51:142、U4b ``:79-89``）。"""
        with caplog.at_level(logging.DEBUG, logger="fde_api.action_execution"):
            result, _ = _submit(ae_world)
        db_session.expire_all()
        rows = _rows(db_session)
        blob = _canonical(result) + "".join(_row_dump(r) for r in rows) + caplog.text
        for key in SENSITIVE_KEYS:
            assert key not in blob, f"敏感键命中：{key}"

    def test_sensitive_key_in_params_rejected_before_audit(self, db_session, ae_world) -> None:
        """敏感键进 params → 422 ``sensitive_argument_forbidden``，审计零落行。"""
        from fde_api.action_execution.errors import ActionExecutionError

        before = len(_rows(db_session))
        with pytest.raises(ActionExecutionError) as err:
            _submit(ae_world, params={"to": "ops@example.test", "access_token": "tok"})
        assert err.value.code == "sensitive_argument_forbidden"
        db_session.expire_all()
        assert len(_rows(db_session)) == before, "拒绝路径不得落审计行"


# ---- ④ params_sha256 形态与不可逆 --------------------------------------------


class TestParamsFingerprint:
    def test_params_sha256_is_64_lowercase_hex(self, db_session, ae_world) -> None:
        """U2:284：64 位小写 hex。"""
        result, _ = _submit(ae_world)
        db_session.expire_all()
        row = _row_for(db_session, result["execution_id"])
        assert row is not None
        assert SHA256_HEX.match(row.params_sha256), row.params_sha256
        assert row.params_sha256 == row.params_sha256.lower()

    def test_params_sha256_not_equal_to_any_param_value(self, db_session, ae_world) -> None:
        """U2:284：指纹不等于任何参数值明文，且等于 canonical 重算值。"""
        params = {"to": "ops@example.test", "subject": "s-1", "body": "b-1"}
        result, _ = _submit(ae_world, params=params)
        db_session.expire_all()
        row = _row_for(db_session, result["execution_id"])
        assert row is not None
        assert row.params_sha256 not in {str(v) for v in params.values()}
        assert row.params_sha256 == _sha(params)

    def test_params_sha256_stable_across_key_order(self, db_session, ae_world) -> None:
        """同参数不同键序 → 同一指纹（canonical JSON 键序无关）。"""
        first, _ = _submit(ae_world, params={"b": 2, "a": 1})
        second, _ = _submit(ae_world, params={"a": 1, "b": 2})
        db_session.expire_all()
        row_a = _row_for(db_session, first["execution_id"])
        row_b = _row_for(db_session, second["execution_id"])
        assert row_a is not None and row_b is not None
        assert row_a.params_sha256 == row_b.params_sha256


# ---- ⑤ 上游响应体整段不回显 --------------------------------------------------


class TestResponseBodyZeroEcho:
    def test_audit_table_has_no_free_form_json_column(self, db_session) -> None:
        """审计表是窄列结构：无 params / output 的 JSON 自由载体（C-08 结构保证）。"""
        from fde_api.action_execution.models import ActionExecutionLog

        json_columns = [
            column.name
            for column in ActionExecutionLog.__table__.columns
            if column.type.__class__.__name__ in {"JSON", "JSONB"}
        ]
        assert json_columns == [], f"审计表不得含 JSON 自由列：{json_columns}"

    def test_upstream_product_sentinel_absent_from_audit_row(self, db_session, ae_world) -> None:
        """上游产物里的标记串不得渗入审计行（审计只留指纹与计数）。"""
        result, _ = _submit(
            ae_world, dispatch=RecordingDispatch(product={"body": SENTINEL, "delivered_count": 1})
        )
        db_session.expire_all()
        row = _row_for(db_session, result["execution_id"])
        assert row is not None
        assert SENTINEL not in _row_dump(row)

    def test_failed_execution_writes_no_fabricated_audit_row(self, db_session, ae_world) -> None:
        """失败路径不落审计行（无真实起止时间即不伪造；失败留痕在 action_executions）。"""
        from fde_api.action_execution.errors import ActionExecutionError

        class FailingDispatch:
            calls = 0

            def call(self, request: dict) -> dict[str, Any]:
                FailingDispatch.calls += 1
                raise ActionExecutionError(
                    "tool_not_allowed",
                    "上游返回异常。",
                    details={"reason": "connector_upstream_error", "http_status": 503},
                )

        before = len(_rows(db_session))
        with pytest.raises(ActionExecutionError):
            _submit(ae_world, dispatch=FailingDispatch())
        db_session.expire_all()
        assert len(_rows(db_session)) == before


# ---- ⑥ 成本登记与 T4 预算 ----------------------------------------------------


class TestCostRegistration:
    def test_cost_three_fields_persisted(self, db_session, ae_world) -> None:
        """契约 $defs/CostObject 三字段逐项落库。"""
        result, _ = _submit(ae_world)
        db_session.expire_all()
        row = _row_for(db_session, result["execution_id"])
        assert row is not None
        assert set(result["cost"]) == set(COST_REQUIRED)
        assert row.tool_calls == result["cost"]["tool_calls"]
        assert row.duration_ms == result["cost"]["duration_ms"]
        assert float(row.estimated_usd) == pytest.approx(float(result["cost"]["estimated_usd"]))

    def test_cost_non_negative(self, db_session, ae_world) -> None:
        """三字段均非负（契约 ``minimum: 0``）。"""
        result, _ = _submit(ae_world)
        db_session.expire_all()
        row = _row_for(db_session, result["execution_id"])
        assert row is not None
        assert row.tool_calls >= 0
        assert row.duration_ms >= 0
        assert float(row.estimated_usd) >= 0.0

    def test_t4_single_task_cost_under_budget(self, db_session, ae_world) -> None:
        """51:213：T4 单任务累计成本 ≤ $0.10（3 次独立运行累加）。"""
        total = 0.0
        for _ in range(3):
            result, _ = _submit(ae_world)
            total += float(result["cost"]["estimated_usd"])
        assert total <= T4_TASK_BUDGET_USD, f"T4 单任务成本超预算：{total}"


# ---- ⑦ append-only 与幂等 ----------------------------------------------------


class TestAuditAppendOnly:
    def test_replay_does_not_add_audit_row(self, db_session, ae_world) -> None:
        """复放零新行：同键同体三连发 → 该 execution_id 恒 1 行审计。"""
        from fde_api.action_execution import service as svc

        payload = _request(org_id=ae_world["org"].id, requester_id=ae_world["actor"].id)
        dispatch = RecordingDispatch()
        first = svc.submit_action(
            actor=ae_world["actor"], payload=payload, whitelist_gate=AllowAllWhitelist(), dispatch=dispatch
        )
        svc.submit_action(
            actor=ae_world["actor"], payload=payload, whitelist_gate=AllowAllWhitelist(), dispatch=dispatch
        )
        svc.submit_action(
            actor=ae_world["actor"], payload=payload, whitelist_gate=AllowAllWhitelist(), dispatch=dispatch
        )
        db_session.expire_all()
        matching = [r for r in _rows(db_session) if r.execution_id == first["execution_id"]]
        assert len(matching) == 1, f"复放新增审计行：{len(matching)}"

    def test_one_audit_row_per_execution(self, db_session, ae_world) -> None:
        """execution_id 唯一：一次执行恰一条审计行。"""
        a, _ = _submit(ae_world)
        b, _ = _submit(ae_world)
        db_session.expire_all()
        ids = [r.execution_id for r in _rows(db_session)]
        assert len(ids) == len(set(ids)), "审计行 execution_id 重复"
        assert a["execution_id"] in ids and b["execution_id"] in ids

    def test_audit_log_table_is_append_only_no_mutation_route(self) -> None:
        """append-only：路由面无审计日志的写改删端点（仅执行链内部写入）。"""
        from fde_api.action_execution.routes import action_execution_blueprint

        paths: list[str] = []
        for function in action_execution_blueprint.deferred_functions:
            function_name = getattr(function, "__name__", "")
            paths.append(function_name)
        joined = " ".join(paths).lower()
        assert "log" not in joined and "audit" not in joined

    def test_audit_row_tenant_isolated(self, db_session, ae_world) -> None:
        """租户面按 org_id 值存；跨租户执行各落各自行，互不串。"""
        from fde_api.action_execution import service as svc

        a, _ = _submit(ae_world)
        payload_b = _request(org_id=ae_world["org_b"].id, requester_id=ae_world["actor_b"].id)
        b = svc.submit_action(
            actor=ae_world["actor_b"],
            payload=payload_b,
            whitelist_gate=AllowAllWhitelist(),
            dispatch=RecordingDispatch(),
        )
        db_session.expire_all()
        row_a = _row_for(db_session, a["execution_id"])
        row_b = _row_for(db_session, b["execution_id"])
        assert row_a is not None and row_b is not None
        assert row_a.org_id == ae_world["org"].id
        assert row_b.org_id == ae_world["org_b"].id
        assert row_a.org_id != row_b.org_id
