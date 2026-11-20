"""AE1 出口后补强钉（A 桶：报告 `_ae1-wp5-report.md` §9.1 A 桶逐条）。

**背景**：AE1 出口已 P1 签署（53 号 v0.5-CLOSED）。第 2/3 组评审（负向钉面／
评测工具面）在出口后补跑，逐条对 `fork/main` 真值复核后成立 38 条，按处置桶
分流：**A 桶＝出口后补强项**（新增覆盖面，不影响任何已落结论）、B 桶＝口径
分歧（须 P1 拍板，本文件不涉及）、C 桶＝D4 已决不重开。

**本文件只做 A 桶**（14 条 + 4 条零星），纪律：
- **不改任何出口数字**：不触 84 条冻结断言、不改契约/白名单/任务集三冻结件、
  不改已落证据件；
- **缺口靠真值核实**：每条钉对着 `fork/main` 的实现写，先跑红（证伪「已覆盖」
  的误判）再补实现，最后跑绿；
- **钉本身防假通过**：断言须能被变异打红（删实现即红），不以「函数名像对了」
  「参数没进过系统」充数。

钉名 → 评审条目对照（括号内为报告 §9.1 的条目标题）：

============  ==========================================================
钉名          评审条目
============  ==========================================================
H1            D2 审批绑定（capability/tool_name）缺否定腿
H2            三敏感键零命中扫描近乎恒真 ＋ S-AE-04 七键等值/A3/A5/A6
H3            契约 ②「原执行 status=failed 可回滚」零覆盖
H4            回滚异常集 7 码只触及 2 码
H5            「并发」钉实为 monkeypatch 私有方法造时间窗（真并发）
H6            KD-02 mock.erp ``query_inventory`` 归一化零覆盖
H7            ``test_address_override_rejected_by_l1`` 未断言任何拒绝
H8            审计表 append-only 检查靠函数名字符串扫描
H9            P15 复核人分离无任何断言钉
H10           未知 task_id 静默判失败且与「本无断言」不可区分
H11           文法解析错误被吞，不登记
H12           ``MISSING !=`` 比较恒 False 口径无钉
H13           ``bool`` 与数字不互等的防假通过规则无钉
H14           本地死常量（15 码/五态/四态）零引用——契约漂移不钉红
H15           语法 ident 产出式被关键字收窄（潜在面，须响亮失败）
============  ==========================================================
"""
from __future__ import annotations

import hashlib
import json
import threading
import urllib.parse
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest

import _ae_mock_stack as mock_stack_module
from ae_eval.assertions import (
    AssertionSyntaxError,
    evaluate_all_detailed,
    evaluate_assertion,
    parse_assertion,
)
from ae_eval.scorer import score_records
from fde_api.action_execution import connectors
from fde_api.action_execution import service as ae_service
from fde_api.action_execution.connectors import ConnectorWhitelist, HttpDispatch, load_whitelist
from fde_api.action_execution.errors import ActionExecutionError
from fde_api.action_execution.schemas import validate_request_shape
from multi_tenant_harness import add_member, make_enterprise_org, make_project, make_user

_SERVER_ROOT = Path(__file__).resolve().parents[1]
_SNAPSHOT = _SERVER_ROOT / "src" / "fde_api" / "action_execution" / "whitelist.json"
_TASKSET = _SERVER_ROOT / "tests" / "ae_eval" / "taskset_v1.json"

#: 契约 U1 v1.0.5 ``x-error-codes.codes`` 逐码转写（15 码闭集）——**独立于实现
#: 常量**书写，H14 用它把实现侧 ``ERROR_STATUS`` 钉死（实现漂移即红）。
CONTRACT_ERROR_CODES: dict[str, int] = {
    "validation_failed": 422,
    "approval_required": 403,
    "approval_not_found": 404,
    "approval_not_approved": 409,
    "approval_expired": 409,
    "approval_integrity_failed": 409,
    "self_review_forbidden": 409,
    "permission_revoked": 403,
    "tool_not_allowed": 403,
    "not_found": 404,
    "idempotency_mismatch": 409,
    "idempotency_in_flight": 409,
    "rollback_not_supported": 200,
    "compensation_failed": 200,
    "sensitive_argument_forbidden": 422,
}

#: 契约 U1 v1.0.5 ``x-rollback.exceptions`` 七码（HTTP 状态逐码转写）。
CONTRACT_ROLLBACK_EXCEPTIONS: dict[str, int] = {
    "not_found": 404,
    "validation_failed": 422,
    "permission_revoked": 403,
    "approval_required": 403,
    "idempotency_mismatch": 409,
    "rollback_not_supported": 200,
    "compensation_failed": 200,
}

#: 负向设计 §4.3 A1 的七键集合（等值口径——逐键逐一钉）。
SENSITIVE_KEY_SET_7 = (
    "access_token",
    "refresh_token",
    "client_secret",
    "api_key",
    "password",
    "bearer",
    "authorization",
)

AE_CAPABILITY = "action_execution.invoke"


# ---- 基座 ---------------------------------------------------------------------


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _request(**overrides: Any) -> dict[str, Any]:
    req: dict[str, Any] = {
        "action_id": "mock.email.send",
        "action_type": "send_email",
        "connector_id": "mock.email",
        "method": "send",
        "params": {"to": "ops@example.test", "subject": "s-hard", "body": "b-hard"},
        "idempotency_key": "idem-hard-" + uuid4().hex[:8],
        "org_id": "org-hard",
        "requester_id": "user-hard",
        "dry_run": False,
        "risk_level": 3,
        "timeout_seconds": 30,
        "approval_id": None,
    }
    req.update(overrides)
    return req


class AllowAllWhitelist:
    """L3 门桩：放行任意三元组（白名单面另有专钉）。"""

    def check(self, connector_id: str, method: str) -> None:
        return None


class RecordingDispatch:
    """可计数 dispatch 桩：外呼计数＝副作用计数。"""

    def __init__(self, product: dict[str, Any] | None = None) -> None:
        self.calls = 0
        self.product = product
        self._lock = threading.Lock()

    def call(self, request: dict) -> dict[str, Any]:
        with self._lock:
            self.calls += 1
        return dict(self.product) if self.product is not None else {"message_id": "m-hard", "delivered_count": 1}


@pytest.fixture
def hard_world(db_session):
    """企业 org ＋ leader 发起人 ＋ 项目成员复核人 ＋ 项目 ＋ 旁观者 ＋ viewer。"""
    org = make_enterprise_org(db_session)
    actor = make_user(db_session, "project_lead", org_id=org.id)
    reviewer = make_user(db_session, "project_lead", org_id=org.id)
    outsider = make_user(db_session, "project_lead", org_id=make_enterprise_org(db_session).id)
    viewer = make_user(db_session, "viewer", org_id=org.id)
    project = make_project(db_session, actor, code=f"AEH{uuid4().hex[:6]}", org_id=org.id)
    add_member(db_session, project, reviewer)
    db_session.commit()
    return {
        "org": org,
        "actor": actor,
        "reviewer": reviewer,
        "outsider": outsider,
        "viewer": viewer,
        "project": project,
    }


def _make_approval(
    db_session,
    world: dict[str, Any],
    *,
    params: dict[str, Any],
    capability: str = AE_CAPABILITY,
    tool_name: str = "action_execution.execute",
    requested_by: Any = None,
    reviewed_by: Any = None,
    status: str = "approved",
    risk_level: int = 3,
) -> Any:
    """直造 AE 审批单（run_id=None 直发形态；绑定面可覆写）。"""
    from fde_api.control.models import AutomationApproval

    row = AutomationApproval(
        id=str(uuid4()),
        run_id=None,
        workflow_node_run_id=None,
        project_id=world["project"].id,
        requested_by_user_id=(requested_by or world["actor"]).id,
        reviewed_by_user_id=(reviewed_by or world["reviewer"]).id,
        request_key=f"ae-h-{uuid4().hex[:12]}",
        capability=capability,
        tool_name=tool_name,
        risk_level=risk_level,
        status=status,
        arguments_json=params,
        arguments_sha256=hashlib.sha256(_canonical(params).encode("utf-8")).hexdigest(),
        expires_at=datetime.now(UTC) + timedelta(minutes=30),
    )
    db_session.add(row)
    db_session.commit()
    return row


def _persist_execution(
    db_session,
    world: dict[str, Any],
    *,
    execution_id: str | None = None,
    status: str = "succeeded",
    risk_level: int = 0,
    dry_run: bool = False,
    rollback_supported: bool = False,
    approval_id: str | None = None,
) -> str:
    """直落一条执行记录行（回滚入态/异常集构造面）。"""
    from fde_api.action_execution.models import ActionExecution

    eid = execution_id or str(uuid4())
    db_session.add(
        ActionExecution(
            id=eid,
            idempotency_key="idem-hard-" + uuid4().hex[:8],
            org_id=world["org"].id,
            requester_id=world["actor"].id,
            action_id="mock.email.send",
            connector_id="mock.email",
            method="send",
            params_sha256="a" * 64,
            request_fingerprint="f" * 64,
            dry_run=dry_run,
            risk_level=risk_level,
            approval_id=approval_id,
            status=status,
            output_json={"message_id": "m-hard"},
            error_code="" if status != "failed" else "tool_not_allowed",
            error_json=None if status != "failed" else {"code": "tool_not_allowed", "message": "x", "retryable": False},
            audit_json={},
            cost_json={},
            rollback_json={"supported": rollback_supported, "execution_id": eid},
        )
    )
    db_session.commit()
    return eid


# ---- H1：D2 审批绑定否定腿（capability/tool_name 不得跨动作复用） ----------------


class TestH1ApprovalBindingNegativeLeg:
    """评审条：全仓无一处构造 capability 或 tool_name 不匹配的审批单。

    反证口径：删掉 ``service.py`` 的绑定检查，下面两条钉仍绿 ⇒ 原钉只覆盖
    happy path，「risk≥3 审批单不得跨动作复用」这条 D2 甲案规则未被钉住。
    """

    def _submit(self, world: dict[str, Any], approval_id: str, dispatch: RecordingDispatch):
        payload = _request(
            org_id=world["org"].id,
            requester_id=world["actor"].id,
            risk_level=3,
            dry_run=False,
            approval_id=approval_id,
        )
        return ae_service.submit_action(
            actor=world["actor"],
            payload=payload,
            whitelist_gate=AllowAllWhitelist(),
            dispatch=dispatch,
        )

    @pytest.mark.parametrize(
        ("capability", "tool_name"),
        [
            ("other.capability", "action_execution.execute"),  # capability 不匹配
            (AE_CAPABILITY, "other.tool"),  # tool_name 不匹配
            ("other.capability", "other.tool"),  # 两者皆不匹配
        ],
    )
    def test_binding_mismatch_is_404_not_found(self, db_session, hard_world, capability, tool_name) -> None:
        """绑定不匹配 → 404 approval_not_found（与 not_found 同口径，不泄露）。"""
        dispatch = RecordingDispatch()
        approval = _make_approval(
            db_session,
            hard_world,
            params={"to": "ops@example.test", "subject": "s-hard", "body": "b-hard"},
            capability=capability,
            tool_name=tool_name,
        )
        with pytest.raises(ActionExecutionError) as err:
            self._submit(hard_world, approval.id, dispatch)
        assert err.value.code == "approval_not_found"
        assert err.value.status == 404
        assert dispatch.calls == 0  # 零副作用

    def test_matching_binding_passes_the_binding_leg(self, db_session, hard_world) -> None:
        """对照腿：绑定一致 → 不被绑定检查拦下（证明上两条钉的是绑定面而非其它门）。"""
        dispatch = RecordingDispatch()
        params = {"to": "ops@example.test", "subject": "s-hard", "body": "b-hard"}
        approval = _make_approval(db_session, hard_world, params=params)
        result = self._submit(hard_world, approval.id, dispatch)
        assert result["status"] == "succeeded"
        assert dispatch.calls == 1


# ---- H2：敏感键零命中扫描非恒真 ＋ 七键等值/A3/A5/A6 --------------------------


class TestH2SensitiveKeySurface:
    """评审条：原钉用默认 params 扫描，三个键名从未进过系统（近乎恒真）。

    本组钉把七键**真实送进系统**（L1 拒绝路径），再断言键名在错误消息／
    details／响应体／应用日志／审计行五处零命中——白名单 ``log_redaction``
    条款（「不得出现在日志、错误消息、响应体任何位置」）首次有回归保护。
    """

    @pytest.mark.parametrize("key", SENSITIVE_KEY_SET_7)
    def test_seven_keys_are_rejected_with_closed_set_code(self, key: str) -> None:
        """负向设计 §4.3 A1：七键等值 —— 逐键 422 sensitive_argument_forbidden。"""
        payload = _request(params={"to": "ops@example.test", key: "value-x"})
        with pytest.raises(ActionExecutionError) as err:
            validate_request_shape(payload)
        assert err.value.code == "sensitive_argument_forbidden"
        assert err.value.status == 422

    @pytest.mark.parametrize("key", SENSITIVE_KEY_SET_7)
    def test_key_name_never_echoed_in_error_message_or_details(self, key: str) -> None:
        """A5 口径：错误消息／details 全文不含敏感键名（大小写不敏感）。"""
        payload = _request(params={"to": "ops@example.test", key: "value-x"})
        with pytest.raises(ActionExecutionError) as err:
            validate_request_shape(payload)
        blob = f"{err.value.message} {json.dumps(err.value.details or {}, ensure_ascii=False)}"
        assert key.lower() not in blob.lower()
        for banned in ("access_token", "refresh_token", "client_secret", "authorization", "bearer"):
            assert banned not in blob.lower()

    def test_unknown_top_level_sensitive_field_is_not_echoed(self) -> None:
        """未登记字段清单里混入敏感键名 → 只报「含敏感键名」，不回显键名。"""
        payload = _request(access_token="value-x")
        with pytest.raises(ActionExecutionError) as err:
            validate_request_shape(payload)
        assert err.value.code == "validation_failed"
        assert "access_token" not in err.value.message
        assert "敏感键名" in err.value.message

    def test_plain_unknown_field_is_still_listed(self) -> None:
        """非敏感未登记字段照常列出（可定位性不退化）。"""
        payload = _request(tenant_id="T-999")
        with pytest.raises(ActionExecutionError) as err:
            validate_request_shape(payload)
        assert err.value.code == "validation_failed"
        assert "tenant_id" in err.value.message

    @pytest.mark.parametrize("key", ["Authorization", "BEARER", "Api_Key", "PASSWORD", "Refresh_Token"])
    def test_case_insensitive_key_variants_rejected(self, key: str) -> None:
        """A5 口径的大小写腿：``Authorization``/``Bearer`` 等变体同样命中。"""
        payload = _request(params={"to": "ops@example.test", key: "value-x"})
        with pytest.raises(ActionExecutionError) as err:
            validate_request_shape(payload)
        assert err.value.code == "sensitive_argument_forbidden"

    def test_route_response_body_carries_no_sensitive_key_name(self, client, db_session, hard_world, settings) -> None:
        """响应体零命中（白名单 response_body_zero_echo 口径）：走真路由面。"""
        from fde_api.auth.tokens import issue_access_token

        token = issue_access_token(hard_world["actor"], settings)
        for key in SENSITIVE_KEY_SET_7:
            payload = _request(org_id=hard_world["org"].id, requester_id=hard_world["actor"].id)
            payload["params"] = {"to": "ops@example.test", key: "value-x"}
            res = client.post(
                "/api/v1/action-executions",
                json=payload,
                headers={"Authorization": f"Bearer {token}"},
            )
            assert res.status_code == 422, key
            body = res.get_data(as_text=True)
            assert key.lower() not in body.lower(), key

    def test_app_log_carries_no_sensitive_key_name(self, db_session, hard_world, caplog) -> None:
        """应用日志零命中：键名不得进日志（白名单 log_redaction 口径）。"""
        import logging

        with caplog.at_level(logging.DEBUG, logger="fde_api.action_execution"):
            for key in SENSITIVE_KEY_SET_7:
                payload = _request(org_id=hard_world["org"].id, requester_id=hard_world["actor"].id)
                payload["params"] = {"to": "ops@example.test", key: "value-x"}
                with pytest.raises(ActionExecutionError):
                    validate_request_shape(payload)
        text = caplog.text.lower()
        for key in SENSITIVE_KEY_SET_7:
            assert key.lower() not in text, key

    def test_params_sha256_not_equal_to_plaintext_or_hash_forms(self, db_session, hard_world) -> None:
        """A3 口径：审计指纹 ≠ 参数值明文 **且** ≠ 其 sha1/sha256 原文形式。"""
        params = {"to": "ops@example.test", "subject": "s-hard", "body": "b-hard"}
        dispatch = RecordingDispatch()
        payload = _request(
            org_id=hard_world["org"].id,
            requester_id=hard_world["actor"].id,
            risk_level=0,
            params=params,
        )
        result = ae_service.submit_action(
            actor=hard_world["actor"],
            payload=payload,
            whitelist_gate=AllowAllWhitelist(),
            dispatch=dispatch,
        )
        db_session.expire_all()
        row = ae_service.get_execution_row(result["execution_id"])
        assert row is not None
        fingerprint = row.params_sha256
        for value in params.values():
            assert fingerprint != value
            assert fingerprint != hashlib.sha1(value.encode("utf-8")).hexdigest()
            assert fingerprint != hashlib.sha256(value.encode("utf-8")).hexdigest()

    def test_credential_handle_is_allowed_and_never_leaks(self, db_session, hard_world) -> None:
        """A6 口径：凭据**句柄**（``env://`` 形式）合法可用，句柄与所指值零泄漏。"""
        handle = "env://MOCK_ERP_TOKEN"
        params = {"provider_ref": handle}
        dispatch = RecordingDispatch()
        payload = _request(
            org_id=hard_world["org"].id,
            requester_id=hard_world["actor"].id,
            risk_level=0,
            params=params,
        )
        result = ae_service.submit_action(
            actor=hard_world["actor"],
            payload=payload,
            whitelist_gate=AllowAllWhitelist(),
            dispatch=dispatch,
        )
        assert result["status"] == "succeeded"  # 句柄不是凭据 → 不被敏感键面拦下
        db_session.expire_all()
        row = ae_service.get_execution_row(result["execution_id"])
        assert row is not None
        dumped = json.dumps(row.snapshot(), ensure_ascii=False, default=str)
        assert handle not in dumped  # 审计位只留指纹，句柄明文零落库
        assert row.params_sha256 == hashlib.sha256(_canonical(params).encode("utf-8")).hexdigest()


# ---- H3：契约 ②「原执行 status=failed 可回滚」 --------------------------------


class TestH3RollbackEntryStateFailed:
    """评审条：回滚造行只用 succeeded/cancelled/awaiting_approval，缺 failed 行。"""

    def test_failed_execution_row_is_rollbackable(self, db_session, hard_world) -> None:
        """契约 ``rollback_entry_states`` ②：failed 行可回滚（补偿逐条登记）。"""

        class _SucceedingCompensator:
            def compensate(self, record: dict) -> dict:
                return {
                    "compensation_id": "comp-ok",
                    "kind": record["kind"],
                    "target": record["target"],
                    "status": "succeeded",
                    "detail": {},
                }

        eid = _persist_execution(db_session, hard_world, status="failed", rollback_supported=True)
        result = ae_service.rollback_action(
            actor=hard_world["actor"], execution_id=eid, compensator=_SucceedingCompensator()
        )
        assert result["status"] == "rolled_back"
        assert result["error"] is None
        assert [c["status"] for c in result["compensations"]] == ["succeeded"]

    def test_failed_execution_row_without_support_is_not_supported(self, db_session, hard_world) -> None:
        """failed 行同样受 supported 开关约束（不谎报 rolled_back）。"""
        eid = _persist_execution(db_session, hard_world, status="failed", rollback_supported=False)
        result = ae_service.rollback_action(actor=hard_world["actor"], execution_id=eid)
        assert result["status"] == "not_supported"
        assert result["error"] is not None and result["error"]["code"] == "rollback_not_supported"


# ---- H4：回滚异常集七码逐码落地 ----------------------------------------------


class TestH4RollbackExceptionSet:
    """评审条：契约 ``x-rollback.exceptions`` 列七码，钉面只触及两码。

    本组钉把七码逐码走通（异常码 5 个＋诚实失败态 2 个），并断言**七码集合
    与契约逐字相等**——不多不少，避免闭集外码混入。
    """

    def test_not_found_404_for_unknown_execution(self, db_session, hard_world) -> None:
        with pytest.raises(ActionExecutionError) as err:
            ae_service.rollback_action(actor=hard_world["actor"], execution_id=str(uuid4()))
        assert err.value.code == "not_found"
        assert err.value.status == 404

    def test_validation_failed_422_for_illegal_reason(self, db_session, hard_world) -> None:
        """入参非法（reason 超长）→ 422 validation_failed。"""
        eid = _persist_execution(db_session, hard_world, status="succeeded", rollback_supported=True)
        with pytest.raises(ActionExecutionError) as err:
            ae_service.rollback_action(actor=hard_world["actor"], execution_id=eid, reason="x" * 501)
        assert err.value.code == "validation_failed"
        assert err.value.status == 422

    def test_permission_revoked_403_for_revoked_actor(self, db_session, hard_world) -> None:
        """回滚发起人对该动作能力已失权 → 403 permission_revoked。"""
        eid = _persist_execution(db_session, hard_world, status="succeeded", rollback_supported=True)
        with pytest.raises(ActionExecutionError) as err:
            ae_service.rollback_action(actor=hard_world["viewer"], execution_id=eid)
        assert err.value.code == "permission_revoked"
        assert err.value.status == 403

    def test_approval_required_403_for_risk3_row_without_approval(self, db_session, hard_world) -> None:
        """risk≥3 真执行行缺 approval_id → 403 approval_required（既有防御分支）。"""
        eid = _persist_execution(db_session, hard_world, status="succeeded", risk_level=3, rollback_supported=True)
        with pytest.raises(ActionExecutionError) as err:
            ae_service.rollback_action(actor=hard_world["actor"], execution_id=eid)
        assert err.value.code == "approval_required"
        assert err.value.status == 403

    def test_idempotency_mismatch_409_for_same_key_other_execution(self, db_session, hard_world) -> None:
        """同幂等键指向另一执行体（请求体漂移）→ 409 idempotency_mismatch。"""
        first = _persist_execution(db_session, hard_world, status="succeeded", rollback_supported=True)
        second = _persist_execution(db_session, hard_world, status="succeeded", rollback_supported=True)
        ae_service.rollback_action(actor=hard_world["actor"], execution_id=first, idempotency_key="rb-key-1")
        with pytest.raises(ActionExecutionError) as err:
            ae_service.rollback_action(actor=hard_world["actor"], execution_id=second, idempotency_key="rb-key-1")
        assert err.value.code == "idempotency_mismatch"
        assert err.value.status == 409

    def test_rollback_not_supported_honest_state(self, db_session, hard_world) -> None:
        """诚实失败态①：status=not_supported ＋ error.code=rollback_not_supported。"""
        eid = _persist_execution(db_session, hard_world, status="succeeded", rollback_supported=False)
        result = ae_service.rollback_action(actor=hard_world["actor"], execution_id=eid)
        assert result["status"] == "not_supported"
        assert result["error"] is not None and result["error"]["code"] == "rollback_not_supported"

    def test_compensation_failed_honest_state(self, db_session, hard_world) -> None:
        """诚实失败态②：补偿失败 → status=failed ＋ error.code=compensation_failed。"""

        class _FailingCompensator:
            def compensate(self, record: dict) -> dict:
                raise RuntimeError("compensator-boom")

        eid = _persist_execution(db_session, hard_world, status="succeeded", rollback_supported=True)
        result = ae_service.rollback_action(
            actor=hard_world["actor"], execution_id=eid, compensator=_FailingCompensator()
        )
        assert result["status"] == "failed"
        assert result["error"] is not None and result["error"]["code"] == "compensation_failed"

    def test_rollback_exception_codes_are_exactly_the_contract_seven(self) -> None:
        """七码集合与契约逐字相等（闭集纪律：不增不减）。"""
        from fde_api.action_execution.errors import ERROR_STATUS

        assert set(CONTRACT_ROLLBACK_EXCEPTIONS) == {
            "not_found",
            "validation_failed",
            "permission_revoked",
            "approval_required",
            "idempotency_mismatch",
            "rollback_not_supported",
            "compensation_failed",
        }
        for code in CONTRACT_ROLLBACK_EXCEPTIONS:
            assert code in ERROR_STATUS, code  # 回滚异常码必属 15 码闭集


# ---- H5：真并发（真实 UNIQUE 约束／在途锁机制上） -----------------------------


class TestH5TrueConcurrency:
    """评审条：原「并发」钉是 monkeypatch 私有方法造时间窗，无真竞态。

    本钉用**两个真线程**同时提交同键同体，落在真实 ``UNIQUE(org_id,
    idempotency_key)`` 与在途锁机制上——败者零副作用（副作用计数恒 1）。
    """

    def test_two_threads_same_key_single_side_effect(self, app, db_session, hard_world) -> None:
        from fde_api.auth.models import User
        from fde_api.extensions import db

        payload = _request(
            org_id=hard_world["org"].id,
            requester_id=hard_world["actor"].id,
            risk_level=0,
            dry_run=False,  # 真执行（干跑不派发，副作用计数不成立）
        )
        dispatch = RecordingDispatch()
        barrier = threading.Barrier(2, timeout=20)
        outcomes: list[Any] = []

        def _worker() -> None:
            with app.app_context():
                session = db.session()
                try:
                    actor = session.get(User, hard_world["actor"].id)
                    assert actor is not None
                    barrier.wait()
                    outcomes.append(
                        ae_service.submit_action(
                            actor=actor,
                            payload=payload,
                            whitelist_gate=AllowAllWhitelist(),
                            dispatch=dispatch,
                        )
                    )
                except ActionExecutionError as error:
                    outcomes.append(error)
                except Exception as error:  # noqa: BLE001 - 线程内异常回传主线程
                    outcomes.append(error)
                finally:
                    session.close()

        threads = [threading.Thread(target=_worker, name=f"ae-hard-conc-{index}") for index in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=30)
            assert not thread.is_alive(), "并发线程未按时结束"

        assert len(outcomes) == 2
        assert dispatch.calls == 1, f"副作用计数应为 1，实为 {dispatch.calls}（线程结果：{outcomes}）"
        succeeded = [item for item in outcomes if isinstance(item, dict) and item["status"] == "succeeded"]
        assert len(succeeded) == 1, "同键同体并发只允许一次真执行"
        loser = [item for item in outcomes if item is not succeeded[0]][0]
        if isinstance(loser, ActionExecutionError):
            # 败者要么撞在途锁（409 in_flight），要么读到已终态行走复放通道
            assert loser.code in {"idempotency_in_flight", "idempotency_mismatch"}, loser.code
        else:
            assert loser["status"] == "replayed"


# ---- H6：KD-02 mock.erp query_inventory 归一化 --------------------------------


class TestH6Kd02Normalization:
    """评审条：``normalize_output`` 有 mock.erp ``items[0]`` 展开分支，零断言。"""

    def test_inventory_row_expanded_to_flat_shape(self) -> None:
        """KD-02（白名单 v1.3.2 登记）：``{items:[…]}`` → ``{sku,quantity,available}``。"""
        payload = {"items": [{"sku": "SKU-1", "quantity": 42, "available": 42, "warehouse": "wh-default"}]}
        out = connectors.normalize_output(
            connector_id="mock.erp", method="query_inventory", payload_json=payload, org_id="org-x"
        )
        assert out == {"sku": "SKU-1", "quantity": 42, "available": 42}

    def test_inventory_first_item_wins(self) -> None:
        """items[0] 展开（多行取首行——契约登记口径）。"""
        payload = {"items": [{"sku": "A", "quantity": 1, "available": 1}, {"sku": "B", "quantity": 2, "available": 2}]}
        out = connectors.normalize_output(
            connector_id="mock.erp", method="query_inventory", payload_json=payload, org_id="org-x"
        )
        assert out["sku"] == "A"

    def test_inventory_empty_items_returns_empty_object(self) -> None:
        """空库存 → 空对象（不伪造零值行）。"""
        out = connectors.normalize_output(
            connector_id="mock.erp", method="query_inventory", payload_json={"items": []}, org_id="org-x"
        )
        assert out == {}

    def test_other_connectors_keep_minimal_result(self) -> None:
        """非 mock.erp 形态不被 KD-02 分支误吞（剥信封外壳）。"""
        out = connectors.normalize_output(
            connector_id="mock.email", method="send", payload_json={"data": {"message_id": "m-1"}}, org_id="org-x"
        )
        assert out == {"message_id": "m-1"}


# ---- H7：目标地址覆盖（address_override）真正不可改写 ------------------------


@pytest.fixture(scope="module")
def stacks():
    """两座桩栈：白名单 base 落点（good）＋注入地址落点（evil，可达以证伪）。"""
    good = mock_stack_module.MockStack(erp_port=0, email_port=0)
    good.start()
    evil = mock_stack_module.MockStack(erp_port=0, email_port=0)
    evil.start()
    yield good, evil
    evil.stop()
    good.stop()


class TestH7AddressOverride:
    """评审条：原钉名与 docstring 承诺 422，实际只断言 URL 以白名单 base 开头。

    负向设计 §6.3 A3「须先固定其一」：本实现走的是**第二支**——目标地址恒
    来自白名单 base_url（params 无法改写），故 L1 无须也不应为此新增拒绝码。
    本组钉把「目标主机未收到任何请求」这半条钉住（注入地址可达时亦零请求）。
    """

    def _gates(self, stack: Any) -> tuple[ConnectorWhitelist, HttpDispatch]:
        snapshot = load_whitelist(str(_SNAPSHOT))
        for conn in snapshot["connectors"]:
            if conn.get("id") == "mock.email":
                conn["base_url"] = f"http://127.0.0.1:{stack.email_port}"
            elif conn.get("id") == "mock.erp":
                conn["base_url"] = f"http://127.0.0.1:{stack.erp_port}"
        gate = ConnectorWhitelist(snapshot)
        return gate, HttpDispatch(whitelist=gate, whitelist_snapshot=snapshot, timeout_seconds=5.0)

    def test_injected_address_never_receives_request(self, db_session, hard_world, stacks) -> None:
        """注入 ``url`` 指向可达主机 → 该主机请求计数恒 0（目标地址不可改写）。"""
        good, evil = stacks
        evil_url = f"http://127.0.0.1:{evil.erp_port}/mock-erp/inventory?sku=stolen"
        gate, dispatch = self._gates(good)
        payload = _request(
            action_id="mock.erp.query_inventory",
            action_type="call_api",
            connector_id="mock.erp",
            method="query_inventory",
            org_id=hard_world["org"].id,
            requester_id=hard_world["actor"].id,
            risk_level=0,
            params={"sku": "SKU-HARD", "url": evil_url},
        )
        result = ae_service.submit_action(
            actor=hard_world["actor"], payload=payload, whitelist_gate=gate, dispatch=dispatch
        )
        assert result["status"] == "succeeded"
        assert evil.erp_requests == 0, "注入地址不得收到任何请求"
        assert good.erp_requests == 1, "请求恒落白名单 base_url"

    def test_request_target_host_is_always_whitelist_base(self, db_session, hard_world, stacks) -> None:
        """URL 的 host:port 恒等于白名单 base（注入值至多进 body/query）。"""
        good, _evil = stacks
        gate, dispatch = self._gates(good)
        spec = gate.check("mock.email", "send")
        params = {"to": "ops@example.test", "url": "http://evil.test/steal"}
        url, remaining = connectors.expand_path_template(spec, params, gate.binding_for(spec, "send"))
        assert urllib.parse.urlsplit(url).netloc == urllib.parse.urlsplit(str(spec["base_url"])).netloc
        assert "evil.test" not in url
        assert remaining["url"] == "http://evil.test/steal"  # 只作业务参数随 body 走


# ---- H8：append-only 的路由级结构保证 ----------------------------------------


class TestH8AppendOnlyRouteLevel:
    """评审条：原钉拼 ``deferred_functions.__name__`` 扫「log/audit」子串。

    该法可被「名字不含 log/audit 的写端点」蒙混，也会被无害的 ``list_audit``
    路由误红——它并未真正建立「无 PATCH/DELETE 面」。本钉改用**路由表**判定。
    """

    def test_no_write_method_routes_on_action_execution_surface(self, app) -> None:
        """AE 路由面零 PATCH/PUT/DELETE（append-only 的结构保证）。"""
        rules = [rule for rule in app.url_map.iter_rules() if rule.endpoint.startswith("action_execution.")]
        assert rules, "AE 路由面未注册——钉失真"
        for rule in rules:
            assert not ({"PATCH", "PUT", "DELETE"} & set(rule.methods)), rule

    def test_no_audit_surface_route_at_all(self, app) -> None:
        """审计表无任何独立路由（写入只在执行链内部）。"""
        rules = [rule for rule in app.url_map.iter_rules() if rule.endpoint.startswith("action_execution.")]
        for rule in rules:
            assert "audit" not in rule.rule and "log" not in rule.rule, rule

    def test_audit_row_is_not_mutated_by_replay(self, db_session, hard_world) -> None:
        """复放零新行且零改写（append-only 的数据面保证）。"""
        from fde_api.action_execution.models import ActionExecutionLog

        dispatch = RecordingDispatch()
        payload = _request(
            org_id=hard_world["org"].id,
            requester_id=hard_world["actor"].id,
            risk_level=0,
        )
        first = ae_service.submit_action(
            actor=hard_world["actor"],
            payload=payload,
            whitelist_gate=AllowAllWhitelist(),
            dispatch=dispatch,
        )
        ae_service.submit_action(
            actor=hard_world["actor"],
            payload=payload,
            whitelist_gate=AllowAllWhitelist(),
            dispatch=dispatch,
        )
        db_session.expire_all()
        rows = db_session.query(ActionExecutionLog).filter_by(execution_id=first["execution_id"]).all()
        assert len(rows) == 1
        assert rows[0].created_at == rows[0].updated_at  # 无改写


# ---- H9：P15 四眼闸（复核人 ≠ 发起人） ----------------------------------------


class TestH9ReviewerSeparation:
    """评审条：``reviewed_by`` 改回发起人或 ``None``，15 次运行与计数锚仍绿。"""

    def test_eval_approval_separates_reviewer_from_requester(self, db_session) -> None:
        """评测签发的审批单：复核人非空且 ≠ 发起人（四眼闸形式）。"""
        from ae_eval import runner
        from fde_api.control.models import AutomationApproval

        runner.provision_pinned_world(db_session)  # 字面 ID 世界（org/user/project 真身）
        params = {"sku": "SKU-P15"}
        approval_id = runner._make_email_approval(db_session, params, 3)
        row = db_session.query(AutomationApproval).filter_by(id=approval_id).one()
        assert row.requested_by_user_id == runner.USER_ID
        assert row.reviewed_by_user_id == runner.REVIEWER_ID
        assert row.reviewed_by_user_id is not None
        assert row.reviewed_by_user_id != row.requested_by_user_id

    def test_reviewer_row_is_a_separate_user(self, db_session) -> None:
        """复核人是独立用户行（不是发起人别名）。"""
        from ae_eval import runner
        from fde_api.auth.models import User

        runner.provision_pinned_world(db_session)
        runner._ensure_reviewer(db_session)
        db_session.commit()
        reviewer = db_session.get(User, runner.REVIEWER_ID)
        initiator = db_session.get(User, runner.USER_ID)
        assert reviewer is not None and initiator is not None
        assert reviewer.id != initiator.id


# ---- H10：未知 task_id 与「本无断言」可区分 ----------------------------------


class TestH10UnknownTaskDistinguishable:
    """评审条：任务集外 ID 空断言 → passed=False 但 failed_expressions 亦空。

    「任务 ID 漂移」与「该任务本就没有断言」在报告里同形——无法复核。本钉
    要求评分器明示 ``known_task``，两者不再同形。
    """

    def _record(self, task_id: str) -> Any:
        from ae_eval.records import RunRecord

        attempt = {
            "execution_id": "exec-1",
            "idempotency_key": "test-idem-t4-001-a",
            "status": "succeeded",
            "output": {"count": 2},
            "error": None,
            "audit": {
                "connector_id": "workbench.ontology",
                "method": "read",
                "params_sha256": "a" * 64,
                "actor_user_id": "test-user-001",
                "org_id": "test-org-001",
                "approval_id": None,
                "started_at": "2026-11-20T00:00:00+00:00",
                "finished_at": "2026-11-20T00:00:01+00:00",
                "duration_ms": 1000,
            },
            "cost": {"tool_calls": 1, "duration_ms": 1000, "estimated_usd": 0.0},
            "rollback": {"supported": False, "execution_id": "exec-1"},
            "replayed_from_execution_id": None,
        }
        return RunRecord(task_id=task_id, run_index=1, attempts={"first": attempt}, external_state={})

    def test_unknown_task_id_is_flagged(self) -> None:
        """任务集外 ID：known_task=False ＋ note 标注，且仍不通过。"""
        result = score_records([self._record("T4-999")], _TASKSET)
        score = result["task_scores"][0]
        assert score["known_task"] is False
        assert "unknown_task_id" in score["note"]
        assert score["passed"] is False
        assert score["assertions"] == []

    def test_known_task_with_zero_assertions_is_distinguishable(self, tmp_path: Path) -> None:
        """任务集内但零断言的任务：known_task=True（与任务集外不同形）。"""
        taskset = tmp_path / "taskset_zero.json"
        taskset.write_text(
            json.dumps(
                {
                    "version": "test-zero",
                    "status": "test",
                    "tasks": [{"id": "T4-900", "assertions": []}],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        result = score_records([self._record("T4-900")], taskset)
        score = result["task_scores"][0]
        assert score["known_task"] is True
        assert "unknown_task_id" not in score["note"]
        assert score["passed"] is False  # 零断言仍不通过（证据缺失＝不通过）

    def test_known_task_is_true_for_taskset_member(self) -> None:
        result = score_records([self._record("T4-001")], _TASKSET)
        score = result["task_scores"][0]
        assert score["known_task"] is True
        assert "unknown_task_id" not in score["note"]


# ---- H11：文法解析错误必须登记（不得静默吞掉） --------------------------------


class TestH11SyntaxErrorRegistered:
    """评审条：模块 docstring 承诺「文法不合＝判 FAIL **并登记**」，登记缺失。"""

    def test_syntax_error_is_registered_not_swallowed(self) -> None:
        """语法错误 → 判 FAIL ＋ 登记原因（报告可区分「写错」与「不成立」）。"""
        detailed = evaluate_all_detailed(["attempts.first.output === 1"], {"attempts": {"first": {}}})
        assert len(detailed) == 1
        expression, passed, error = detailed[0]
        assert expression == "attempts.first.output === 1"
        assert passed is False
        assert error is not None and "assertion_syntax_error" in error

    def test_valid_assertion_carries_no_error(self) -> None:
        detailed = evaluate_all_detailed(["attempts.first.status == \"succeeded\""], {"attempts": {"first": {"status": "succeeded"}}})
        assert detailed[0][1] is True
        assert detailed[0][2] is None

    def test_scorer_registers_syntax_errors_in_report(self, tmp_path: Path) -> None:
        """评分器把文法错误登记进报告（syntax_errors 段＋逐条 error 位）。"""
        from ae_eval.records import RunRecord

        taskset = tmp_path / "taskset_broken.json"
        taskset.write_text(
            json.dumps(
                {
                    "version": "test-broken",
                    "status": "test",
                    "tasks": [
                        {"id": "T4-901", "assertions": ["attempts.first.status === \"succeeded\""]},
                    ],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        attempt = {
            "execution_id": "exec-1",
            "idempotency_key": "test-idem-t4-001-a",
            "status": "succeeded",
            "output": {"count": 2},
            "error": None,
            "audit": {},
            "cost": {"tool_calls": 1, "duration_ms": 1000, "estimated_usd": 0.0},
            "rollback": {"supported": False, "execution_id": "exec-1"},
            "replayed_from_execution_id": None,
        }
        record = RunRecord(task_id="T4-901", run_index=1, attempts={"first": attempt}, external_state={})
        result = score_records([record], taskset)
        score = result["task_scores"][0]
        assert score["passed"] is False
        assert score["syntax_errors"] == ['attempts.first.status === "succeeded"']
        assert score["assertions"][0]["error"] is not None


# ---- H12/H13：缺失路径与 bool/数字的防假通过口径 ------------------------------


class TestH12MissingNotEqual:
    """评审条：``!=`` 遇 MISSING 的口径无钉（变异实验仅 sha 锚钉红）。"""

    def test_missing_key_not_equal_literal_is_false(self) -> None:
        """键整个不存在时，``!= null`` 判 **False**（不得真空通过）。"""
        scope: dict[str, Any] = {"attempts": {"first": {"status": "succeeded"}}}
        assert evaluate_assertion("attempts.first.output != null", scope) is False

    def test_present_value_not_equal_literal_is_true(self) -> None:
        """键存在且非 null → ``!= null`` 判 True（口径不被误钉死）。"""
        scope: dict[str, Any] = {"attempts": {"first": {"output": {"count": 2}}}}
        assert evaluate_assertion("attempts.first.output != null", scope) is True

    def test_null_value_not_equal_null_is_false(self) -> None:
        scope: dict[str, Any] = {"attempts": {"first": {"output": None}}}
        assert evaluate_assertion("attempts.first.output != null", scope) is False

    def test_missing_key_equality_is_false(self) -> None:
        scope: dict[str, Any] = {"attempts": {"first": {}}}
        assert evaluate_assertion("attempts.first.output == null", scope) is False


class TestH13BoolNumberStrictEquality:
    """评审条：``_strict_equal`` 的 bool/数字守卫零用例覆盖（删掉不红）。"""

    def test_number_does_not_equal_true(self) -> None:
        """``1 == true`` 判 False（避免布尔字段以 1/0 交付时假通过）。"""
        scope: dict[str, Any] = {"attempts": {"first": {"output": {"simulated": 1}}}}
        assert evaluate_assertion("attempts.first.output.simulated == true", scope) is False

    def test_bool_does_not_equal_number(self) -> None:
        scope: dict[str, Any] = {"attempts": {"first": {"output": {"simulated": True}}}}
        assert evaluate_assertion("attempts.first.output.simulated == 1", scope) is False

    def test_bool_equals_bool(self) -> None:
        scope: dict[str, Any] = {"attempts": {"first": {"output": {"simulated": True}}}}
        assert evaluate_assertion("attempts.first.output.simulated == true", scope) is True

    def test_number_equals_number(self) -> None:
        scope: dict[str, Any] = {"attempts": {"first": {"output": {"count": 2}}}}
        assert evaluate_assertion("attempts.first.output.count == 2", scope) is True


# ---- H14：本地闭集常量不得漂移（契约逐字对齐） --------------------------------


class TestH14ClosedSetConstants:
    """评审条：``EXECUTION_STATUSES``/``ERROR_STATUS`` 本地副本零引用。

    契约五态/15 码漂移不钉红＝事实源漂移无保护。本钉把实现侧常量对着契约
    **独立转写**的期望值钉死（实现改一处即红）。
    """

    def test_error_status_matches_contract_registry(self) -> None:
        from fde_api.action_execution.errors import ERROR_STATUS

        assert ERROR_STATUS == CONTRACT_ERROR_CODES

    def test_error_code_set_is_closed_at_fifteen(self) -> None:
        from fde_api.action_execution.errors import ERROR_STATUS

        assert len(ERROR_STATUS) == 15

    def test_execution_statuses_match_contract(self) -> None:
        from fde_api.action_execution.schemas import EXECUTION_STATUSES

        assert EXECUTION_STATUSES == {"succeeded", "failed", "cancelled", "replayed", "awaiting_approval"}

    def test_rollback_statuses_match_contract(self) -> None:
        from fde_api.action_execution.schemas import ROLLBACK_STATUSES

        assert ROLLBACK_STATUSES == {"rolled_back", "not_supported", "failed", "noop"}

    def test_contract_codes_are_all_reachable_in_error_constructor(self) -> None:
        """闭集纪律：构造层拒闭集外码（自造新码的通道不存在）。"""
        from fde_api.action_execution.errors import ActionExecutionError

        with pytest.raises(ValueError):
            ActionExecutionError("ae_made_up_code", "x")


# ---- H15：关键字收窄的 ident（潜在面须响亮失败） ------------------------------


class TestH15KeywordIdentSurface:
    """评审条：冻结文法的 ``ident`` 未排除 ``len/not/true`` 等关键字。

    84 条冻结断言未踩到该面（潜在面）。本钉要求：关键字名路径段**不得静默
    通过**——须以文法错误登记为 FAIL（对齐冻结文法 ``ident`` 词法与解析器
    当前口径的分歧已登记待 P1 拍板，钉只保证「响亮失败不真空通过」）。
    """

    def test_keyword_named_segment_raises_syntax_error(self) -> None:
        with pytest.raises(AssertionSyntaxError):
            parse_assertion("attempts.not == 1")

    def test_keyword_named_segment_is_registered_as_fail(self) -> None:
        """潜在面不得真空通过：判 FAIL ＋ 登记文法错误。"""
        detailed = evaluate_all_detailed(["attempts.not == 1"], {"attempts": {"not": 1}})
        expression, passed, error = detailed[0]
        assert passed is False
        assert error is not None and "assertion_syntax_error" in error
        assert expression == "attempts.not == 1"
