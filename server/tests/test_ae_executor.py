"""AE1-WP1：单步执行链 ActionExecutor（53 号 §3 WP1；契约 U1 ``_ae-execution-contract-v1.json`` v1.0.3 FROZEN）。

编排链＝「幂等门 → 白名单门 → 审批闸 → 干跑/真执行 → 审计 → 结果」，按 U1
``x-validation-order`` **固定五层顺序**判定（上层未过即短路，层内错误码唯一）：

1. 结构与类型层（422 ``validation_failed``／敏感键 422 ``sensitive_argument_forbidden``）；
2. 幂等层（409 ``idempotency_mismatch``／409 ``idempotency_in_flight``／复放 ``replayed``）；
3. 白名单层（403 ``tool_not_allowed``；WP1 默认 fail-closed——白名单加载器归 WP3）；
4. 审批层（403 ``approval_required``／404 ``approval_not_found``／409 ``approval_not_approved``
   ／409 ``approval_expired``／409 ``approval_integrity_failed``／403 ``permission_revoked``）；
5. 契约结构闭合层（if/then 条件必填，422 兜底——运行时路径第 4 层 403 优先）。

核心纪律钉：
- **零明文**（U1 x-audit.zero_plaintext）：审计/执行记录只存 ``params_sha256``，
  响应体不回显 params（哨兵扫描钉）；
- **15 码闭集**（U1 $defs/ErrorObject.code enum）：闭集外码不可表达，Q8 口径
  ＝闭集外运行时情形映射闭集内码 + ``details`` 标注（默认未接线 dispatch →
  ``tool_not_allowed`` + ``connector_adapter_not_wired``）;
- **干跑默认**（U1 x-dry-run）：对外请求 ``dry_run`` 必填（缺失 422）；服务端
  内部构造补 true 路径不产生隐式真写；写型 risk≥3 缺 ``approval_id`` 运行时
  403（第 4 层）、schema 静态 422（第 5 层）——两腿分别断言（U1
  s_ae_01_alignment）；
- **审批面复用**（U1 x-approval.reuse）：AE 审批单落 ``AutomationApproval``
  （``run_id=None``＋``workflow_node_run_id=None``），拍板复用
  ``decide_automation_approval`` 本体（禁改面零触碰；``_settle_workflow_node``
  对空节点行是 no-op）；
- **租户面**（U1 x-tenant-isolation）：请求体 ``org_id`` 与服务端上下文
  不一致按 404（Q15 口径）；跨租户审批/执行一律 404 不泄露存在性；
- **冻结断言对齐**（U3 ``_ae-tasks-v1.json`` T4-003/T4-004）：复放
  ``status=="replayed"``＋``replayed_from_execution_id`` 指向首次＋output 逐字
  复现首次；干跑 ``output.simulated==true``＋``cost.tool_calls==1``＋
  ``audit.approval_id==null``。

audit.approval_id 读法登记（U1 $defs AuditObject vs x-validation-order
audit_binding_note 张力的调和）：risk≥3 写型真执行 → 必非 null 且等于提交值
（S-AE-01 A9 语境）；低风险（risk<3）写型真执行无审批面介入 → 可 null。
"""
from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import pytest

from conftest import INITIAL_PASSWORD as PASSWORD
from fde_api.auth.tokens import issue_access_token
from fde_api.control.service import ControlServiceError, decide_automation_approval
from multi_tenant_harness import add_member, make_enterprise_org, make_project, make_user

# ---- 契约常量（与 U1 v1.0.3 $defs 逐字对齐；漂移即钉红） -----------------------

REQUEST_REQUIRED = (
    "action_id",
    "connector_id",
    "method",
    "params",
    "idempotency_key",
    "org_id",
    "requester_id",
    "dry_run",
    "risk_level",
    "timeout_seconds",
)

EXECUTION_STATUSES = {"succeeded", "failed", "cancelled", "replayed", "awaiting_approval"}
ROLLBACK_STATUSES = {"rolled_back", "not_supported", "failed", "noop"}

ERROR_STATUS = {
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

AE_CAPABILITY = "action_execution.invoke"


def _sha256_of(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


# ---- 请求基座 -----------------------------------------------------------------


def _request(**overrides):
    """合法请求基座（缺省走干跑读路径——最浅合法形态）。"""
    req: dict[str, Any] = {
        "action_id": "mock.erp.query_inventory",
        "action_type": "call_api",
        "connector_id": "mock.erp",
        "method": "query_inventory",
        "params": {"sku": "SKU-001"},
        "idempotency_key": "idem-ae-wp1-" + uuid4().hex[:8],
        "org_id": "test-org-001",
        "requester_id": "test-user-001",
        "dry_run": True,
        "risk_level": 0,
        "timeout_seconds": 30,
        "approval_id": None,
    }
    req.update(overrides)
    return req


# ---- 纯函数面：五层结构校验（schemas.validate_request_shape / validate_conditional） ----


class TestRequestShapeValidation:
    """第 1 层（结构/类型/枚举/闭集）＋第 5 层（条件必填兜底）。"""

    def test_valid_request_passes(self) -> None:
        from fde_api.action_execution.schemas import validate_request_shape

        validate_request_shape(_request())

    @pytest.mark.parametrize("field", REQUEST_REQUIRED)
    def test_missing_required_field_rejected(self, field: str) -> None:
        from fde_api.action_execution.errors import ActionExecutionError
        from fde_api.action_execution.schemas import validate_request_shape

        req = _request()
        req.pop(field)
        with pytest.raises(ActionExecutionError) as err:
            validate_request_shape(req)
        assert err.value.code == "validation_failed"
        assert err.value.status == 422

    def test_additional_property_tenant_id_rejected(self) -> None:
        """additionalProperties=false 闭集：禁自造 tenant_id（红线钉）。"""
        from fde_api.action_execution.errors import ActionExecutionError
        from fde_api.action_execution.schemas import validate_request_shape

        req = _request(tenant_id="T-999")
        with pytest.raises(ActionExecutionError) as err:
            validate_request_shape(req)
        assert err.value.code == "validation_failed"

    @pytest.mark.parametrize("risk", [-1, 5, "3", None])
    def test_risk_level_out_of_domain_rejected(self, risk: Any) -> None:
        from fde_api.action_execution.errors import ActionExecutionError
        from fde_api.action_execution.schemas import validate_request_shape

        with pytest.raises(ActionExecutionError) as err:
            validate_request_shape(_request(risk_level=risk))
        assert err.value.code == "validation_failed"

    @pytest.mark.parametrize("timeout", [0, 301, -5, "30"])
    def test_timeout_out_of_domain_rejected(self, timeout: Any) -> None:
        from fde_api.action_execution.errors import ActionExecutionError
        from fde_api.action_execution.schemas import validate_request_shape

        with pytest.raises(ActionExecutionError):
            validate_request_shape(_request(timeout_seconds=timeout))

    def test_timeout_bounds_accepted(self) -> None:
        from fde_api.action_execution.schemas import validate_request_shape

        validate_request_shape(_request(timeout_seconds=1))
        validate_request_shape(_request(timeout_seconds=300))

    @pytest.mark.parametrize("key", ["", "x" * 161])
    def test_idempotency_key_bounds_rejected(self, key: str) -> None:
        from fde_api.action_execution.errors import ActionExecutionError
        from fde_api.action_execution.schemas import validate_request_shape

        with pytest.raises(ActionExecutionError) as err:
            validate_request_shape(_request(idempotency_key=key))
        assert err.value.code == "validation_failed"

    def test_idempotency_key_160_accepted(self) -> None:
        from fde_api.action_execution.schemas import validate_request_shape

        validate_request_shape(_request(idempotency_key="x" * 160))

    def test_action_id_pattern_rejected(self) -> None:
        from fde_api.action_execution.errors import ActionExecutionError
        from fde_api.action_execution.schemas import validate_request_shape

        with pytest.raises(ActionExecutionError):
            validate_request_shape(_request(action_id="1startswith-digit"))
        with pytest.raises(ActionExecutionError):
            validate_request_shape(_request(action_id="a" * 129))

    def test_sensitive_argument_rejected(self) -> None:
        """params 命中敏感键名 → 422 sensitive_argument_forbidden（U1 params 描述）。"""
        from fde_api.action_execution.errors import ActionExecutionError
        from fde_api.action_execution.schemas import validate_request_shape

        req = _request(params={"access_token": "AE-SENTINEL-SECRET-0001"})
        with pytest.raises(ActionExecutionError) as err:
            validate_request_shape(req)
        assert err.value.code == "sensitive_argument_forbidden"
        assert err.value.status == 422

    def test_layer5_conditional_missing_approval_id_422(self) -> None:
        """第 5 层兜底：dry_run=false ∧ risk≥3 缺/null approval_id → 422（静态路径）。"""
        from fde_api.action_execution.errors import ActionExecutionError
        from fde_api.action_execution.schemas import validate_conditional

        base = {"dry_run": False, "risk_level": 3}
        for approval_id in (None, "  "):
            req = _request(**base, approval_id=approval_id)
            with pytest.raises(ActionExecutionError) as err:
                validate_conditional(req)
            assert err.value.code == "validation_failed"
        # approval_id 字段整体缺失同样兜底拒绝
        req = _request(**base)
        req.pop("approval_id")
        with pytest.raises(ActionExecutionError):
            validate_conditional(req)

    def test_conditional_low_risk_write_without_approval_ok(self) -> None:
        from fde_api.action_execution.schemas import validate_conditional

        validate_conditional(_request(dry_run=False, risk_level=2, approval_id=None))


# ---- 纯函数面：指纹（body_fingerprint 10 字段覆盖） ----------------------------


class TestRequestFingerprint:
    """指纹必须覆盖全部语义字段；漏字段会造成异体请求被静默复放（U1 coverage_rule）。"""

    FIELDS = [
        "action_id",
        "action_type",
        "connector_id",
        "method",
        "params",
        "dry_run",
        "risk_level",
        "approval_id",
        "requester_id",
        "timeout_seconds",
    ]

    def test_stable_and_key_order_insensitive(self) -> None:
        from fde_api.action_execution.executor import request_fingerprint

        req = _request()
        reordered = dict(reversed(list(req.items())))
        assert request_fingerprint(req) == request_fingerprint(dict(req))
        assert request_fingerprint(req) == request_fingerprint(reordered)
        assert len(request_fingerprint(req)) == 64

    def test_every_semantic_field_changes_fingerprint(self) -> None:
        from fde_api.action_execution.executor import request_fingerprint

        base = _request()
        base_fp = request_fingerprint(base)
        for field in self.FIELDS:
            drifted = dict(base)
            if field == "params":
                drifted[field] = {"sku": "SKU-002"}
            elif field == "dry_run":
                drifted[field] = not base[field]
            elif isinstance(base[field], int):
                drifted[field] = base[field] + 1
            elif field == "approval_id":
                drifted[field] = "ap-0001"
            else:
                drifted[field] = f"{base[field]}-drift"
            assert request_fingerprint(drifted) != base_fp, field

    def test_fingerprint_excludes_idempotency_key_and_org(self) -> None:
        """org_id 不入指纹（已是约束组成部分）；idempotency_key 不入（同键判定本体）。"""
        from fde_api.action_execution.executor import (
            FINGERPRINT_FIELDS,
            request_fingerprint,
        )

        assert "idempotency_key" not in FINGERPRINT_FIELDS
        assert "org_id" not in FINGERPRINT_FIELDS
        assert request_fingerprint(_request(idempotency_key="other-key")) == request_fingerprint(
            _request()
        )


# ---- 纯函数面：结果/回滚构造器（status 与 error/output 的 if/then 绑定） -------


class TestResultBindings:
    def test_succeeded_requires_output_and_null_error(self) -> None:
        from fde_api.action_execution.errors import ActionExecutionError
        from fde_api.action_execution.schemas import build_result

        result = build_result(
            execution_id="e-1",
            idempotency_key="k-1",
            status="succeeded",
            output={"simulated": True},
            audit={"k": "a"},
            cost={"k": "c"},
            rollback={"supported": False, "execution_id": "e-1"},
        )
        assert result["error"] is None
        assert result["replayed_from_execution_id"] is None
        with pytest.raises(ActionExecutionError):
            build_result(
                execution_id="e-1",
                idempotency_key="k-1",
                status="succeeded",
                output={"simulated": True},
                audit={"k": "a"},
                cost={"k": "c"},
                rollback={"supported": False, "execution_id": "e-1"},
                error={"code": "not_found", "message": "x", "retryable": False},
            )

    def test_failed_requires_error(self) -> None:
        from fde_api.action_execution.errors import ActionExecutionError
        from fde_api.action_execution.schemas import build_result

        result = build_result(
            execution_id="e-1",
            idempotency_key="k-1",
            status="failed",
            output=None,
            error={"code": "tool_not_allowed", "message": "拒绝", "retryable": False},
            audit={"k": "a"},
            cost={"k": "c"},
            rollback={"supported": False, "execution_id": "e-1"},
        )
        assert result["status"] == "failed"
        with pytest.raises(ActionExecutionError):
            build_result(
                execution_id="e-1",
                idempotency_key="k-1",
                status="failed",
                output=None,
                error=None,
                audit={"k": "a"},
                cost={"k": "c"},
                rollback={"supported": False, "execution_id": "e-1"},
            )

    def test_replayed_requires_source_execution(self) -> None:
        from fde_api.action_execution.errors import ActionExecutionError
        from fde_api.action_execution.schemas import build_result

        result = build_result(
            execution_id="first-1",
            idempotency_key="k-1",
            status="replayed",
            output={"simulated": True},
            audit={"k": "a"},
            cost={"k": "c"},
            rollback={"supported": False, "execution_id": "first-1"},
            replayed_from_execution_id="first-1",
        )
        assert result["replayed_from_execution_id"] == "first-1"
        with pytest.raises(ActionExecutionError):
            build_result(
                execution_id="first-1",
                idempotency_key="k-1",
                status="replayed",
                output={"simulated": True},
                audit={"k": "a"},
                cost={"k": "c"},
                rollback={"supported": False, "execution_id": "first-1"},
                replayed_from_execution_id=None,
            )

    def test_awaiting_approval_error_must_be_null(self) -> None:
        from fde_api.action_execution.errors import ActionExecutionError
        from fde_api.action_execution.schemas import build_result

        result = build_result(
            execution_id="e-1",
            idempotency_key="k-1",
            status="awaiting_approval",
            output=None,
            audit={"k": "a"},
            cost={"k": "c"},
            rollback={"supported": False, "execution_id": "e-1"},
        )
        assert result["error"] is None
        with pytest.raises(ActionExecutionError):
            build_result(
                execution_id="e-1",
                idempotency_key="k-1",
                status="awaiting_approval",
                output=None,
                error={"code": "not_found", "message": "x", "retryable": False},
                audit={"k": "a"},
                cost={"k": "c"},
                rollback={"supported": False, "execution_id": "e-1"},
            )

    def test_cancelled_requires_error(self) -> None:
        from fde_api.action_execution.errors import ActionExecutionError
        from fde_api.action_execution.schemas import build_result

        build_result(
            execution_id="e-1",
            idempotency_key="k-1",
            status="cancelled",
            output=None,
            error={"code": "permission_revoked", "message": "撤权", "retryable": False},
            audit={"k": "a"},
            cost={"k": "c"},
            rollback={"supported": False, "execution_id": "e-1"},
        )
        with pytest.raises(ActionExecutionError):
            build_result(
                execution_id="e-1",
                idempotency_key="k-1",
                status="cancelled",
                output=None,
                error=None,
                audit={"k": "a"},
                cost={"k": "c"},
                rollback={"supported": False, "execution_id": "e-1"},
            )

    def test_error_code_closed_set(self) -> None:
        """15 码闭集逐码在册；闭集外码构造 ErrorObject 拒绝（Q8：映射不造码）。"""
        from fde_api.action_execution.schemas import ERROR_STATUS, build_error

        assert set(ERROR_STATUS) == set(ERROR_STATUS)  # 15 码
        assert len(ERROR_STATUS) == 15
        assert ERROR_STATUS["rollback_not_supported"] == 200
        assert ERROR_STATUS["compensation_failed"] == 200
        for code, status in ERROR_STATUS.items():
            obj = build_error(code, "脱敏说明", retryable=False)
            assert obj["code"] == code
        with pytest.raises(ValueError):
            build_error("timeout", "闭集外码不得表达", retryable=False)
        with pytest.raises(ValueError):
            build_error("rate_limited", "闭集外码不得表达", retryable=False)


class TestRollbackBindings:
    def test_four_statuses(self) -> None:
        from fde_api.action_execution.schemas import ROLLBACK_STATUSES

        assert ROLLBACK_STATUSES == {"rolled_back", "not_supported", "failed", "noop"}


# ---- 集成面夹具 ----------------------------------------------------------------


@pytest.fixture
def ae_world(db_session):
    """企业 org ＋ leader 账号 ＋ 同项目成员复核人（四眼闸第二人）＋项目。"""
    org = make_enterprise_org(db_session)
    actor = make_user(db_session, "project_lead", org_id=org.id)
    reviewer = make_user(db_session, "project_lead", org_id=org.id)
    outsider = make_user(db_session, "project_lead", org_id=make_enterprise_org(db_session).id)
    project = make_project(db_session, actor, code=f"AE1{uuid4().hex[:6]}", org_id=org.id)
    # reviewer＝项目成员（拍板复核人；project_operator 档能力只要求 can_view）
    add_member(db_session, project, reviewer)
    db_session.commit()
    return {"org": org, "actor": actor, "reviewer": reviewer, "outsider": outsider, "project": project}


def _auth(user, settings) -> dict[str, str]:
    return {"Authorization": f"Bearer {issue_access_token(user, settings)}"}


class RecordingDispatch:
    """可计数 dispatch 桩：外呼计数即副作用计数（S-AE-02 口径的 WP1 前身）。"""

    def __init__(self, product: dict[str, Any] | None = None) -> None:
        self.calls = 0
        self.product = product

    def call(self, request: dict) -> dict[str, Any]:
        self.calls += 1
        if self.product is not None:
            return dict(self.product)
        return {"message_id": f"msg-{self.calls}", "delivered_count": 1}


class AllowAllWhitelist:
    """白名单放行桩（WP3 前的测试穿透面；生产默认 fail-closed）。"""

    def check(self, connector_id: str, method: str) -> None:
        return None


class DenyAllWhitelist:
    def check(self, connector_id: str, method: str) -> None:
        from fde_api.action_execution.errors import ActionExecutionError

        raise ActionExecutionError("tool_not_allowed", "连接器不在白名单。", 403)


# ---- 集成面：service.submit_action（真门 + DB） --------------------------------


class TestSubmitAction:
    def _svc(self):
        from fde_api.action_execution import service

        return service

    def test_dry_run_read_end_to_end(self, db_session, ae_world) -> None:
        """干跑读路径全链：succeeded + output.simulated + audit 9 字段 + cost 3 字段
        （T4-001/T4-004 冻结断言的 WP1 对齐腿）。"""
        svc = self._svc()
        result = svc.submit_action(
            actor=ae_world["actor"],
            payload=_request(org_id=ae_world["org"].id, requester_id=ae_world["actor"].id),
            whitelist_gate=AllowAllWhitelist(),
        )
        assert result["status"] == "succeeded"
        assert result["error"] is None
        assert result["output"]["simulated"] is True
        audit = result["audit"]
        assert set(audit) >= {
            "connector_id",
            "method",
            "params_sha256",
            "actor_user_id",
            "org_id",
            "approval_id",
            "started_at",
            "finished_at",
            "duration_ms",
        }
        assert audit["approval_id"] is None
        assert audit["params_sha256"] == _sha256_of(_canonical({"sku": "SKU-001"}))
        assert len(audit["params_sha256"]) == 64
        cost = result["cost"]
        assert set(cost) == {"tool_calls", "duration_ms", "estimated_usd"}
        assert cost["tool_calls"] == 1
        assert result["rollback"]["supported"] is False
        assert result["rollback"]["execution_id"] == result["execution_id"]

    def test_zero_plaintext_sentinel_scan(self, db_session, ae_world) -> None:
        """零明文纪律：结果与落库行均不含 params 明文（哨兵值全文 0 命中）。"""
        svc = self._svc()
        sentinel = "AE-SENTINEL-SECRET-0001"
        payload = _request(
            params={"sku": sentinel},
            org_id=ae_world["org"].id,
            requester_id=ae_world["actor"].id,
        )
        result = svc.submit_action(actor=ae_world["actor"], payload=payload, whitelist_gate=AllowAllWhitelist())
        blob = _canonical(result)
        assert sentinel not in blob
        row = svc.get_execution_row(result["execution_id"])
        assert sentinel not in _canonical(row.snapshot())
        assert row.params_sha256 == _sha256_of(_canonical({"sku": sentinel}))

    def test_low_risk_write_real_dispatch_succeeds(self, db_session, ae_world) -> None:
        """risk<3 写型真执行：无审批闸介入（audit.approval_id 可 null——见模块头读法登记）。"""
        svc = self._svc()
        dispatch = RecordingDispatch({"message_id": "m-1", "delivered_count": 1})
        result = svc.submit_action(
            actor=ae_world["actor"],
            payload=_request(
                action_id="mock.email.send",
                connector_id="mock.email",
                method="send",
                dry_run=False,
                risk_level=2,
                approval_id=None,
                org_id=ae_world["org"].id,
                requester_id=ae_world["actor"].id,
            ),
            whitelist_gate=AllowAllWhitelist(),
            dispatch=dispatch,
        )
        assert result["status"] == "succeeded"
        assert dispatch.calls == 1
        assert result["audit"]["approval_id"] is None

    def test_replay_same_key_same_body(self, db_session, ae_world) -> None:
        """同键同体复放：replayed + 指向首次 + output 逐字复现 + 副作用不增
        （T4-003 冻结断言腿）。"""
        svc = self._svc()
        payload = _request(
            connector_id="mock.email",
            method="send",
            action_id="mock.email.send",
            dry_run=False,
            risk_level=2,
            org_id=ae_world["org"].id,
            requester_id=ae_world["actor"].id,
        )
        dispatch = RecordingDispatch({"message_id": "m-first", "delivered_count": 1})
        first = svc.submit_action(actor=ae_world["actor"], payload=payload, whitelist_gate=AllowAllWhitelist(), dispatch=dispatch)
        replay = svc.submit_action(actor=ae_world["actor"], payload=payload, whitelist_gate=AllowAllWhitelist(), dispatch=dispatch)
        assert first["status"] == "succeeded"
        assert replay["status"] == "replayed"
        assert replay["replayed_from_execution_id"] == first["execution_id"]
        assert replay["output"] == first["output"]
        assert dispatch.calls == 1  # 副作用仅一次

    def test_idempotency_mismatch_same_key_different_body(self, db_session, ae_world) -> None:
        """同键异体（真执行腿）：409 且零第二次副作用。"""
        svc = self._svc()
        payload = _request(
            connector_id="mock.email",
            method="send",
            action_id="mock.email.send",
            dry_run=False,
            risk_level=2,
            org_id=ae_world["org"].id,
            requester_id=ae_world["actor"].id,
        )
        dispatch = RecordingDispatch()
        svc.submit_action(actor=ae_world["actor"], payload=payload, whitelist_gate=AllowAllWhitelist(), dispatch=dispatch)
        assert dispatch.calls == 1
        drifted = _request(
            connector_id="mock.email",
            method="send",
            action_id="mock.email.send",
            dry_run=False,
            risk_level=2,
            params={"sku": "SKU-DRIFT"},
            org_id=ae_world["org"].id,
            requester_id=ae_world["actor"].id,
        )
        drifted["idempotency_key"] = payload["idempotency_key"]
        from fde_api.action_execution.errors import ActionExecutionError

        with pytest.raises(ActionExecutionError) as err:
            svc.submit_action(actor=ae_world["actor"], payload=drifted, whitelist_gate=AllowAllWhitelist(), dispatch=dispatch)
        assert err.value.code == "idempotency_mismatch"
        assert err.value.status == 409
        assert dispatch.calls == 1  # 异体拒绝不产生第二次副作用

    def test_idempotency_in_flight_awaiting_row(self, db_session, ae_world) -> None:
        """同键在途（awaiting_approval 行在场）→ 409 退避（U1 x-idempotency.in_flight）。"""
        from fde_api.action_execution import service as ae_service
        from fde_api.action_execution.errors import ActionExecutionError
        from fde_api.action_execution.executor import request_fingerprint
        from fde_api.action_execution.models import ActionExecution

        svc = self._svc()
        payload = _request(org_id=ae_world["org"].id, requester_id=ae_world["actor"].id)
        row = ActionExecution(
            id=uuid4().hex,
            idempotency_key=payload["idempotency_key"],
            org_id=payload["org_id"],
            requester_id=payload["requester_id"],
            action_id=payload["action_id"],
            connector_id=payload["connector_id"],
            method=payload["method"],
            params_sha256=_sha256_of(_canonical(payload["params"])),
            request_fingerprint=request_fingerprint(payload),  # 同体指纹（在途判定前提）
            dry_run=True,
            risk_level=0,
            approval_id=None,
            status="awaiting_approval",
            audit_json={},
            cost_json={},
            rollback_json={},
        )
        db_session.add(row)
        db_session.commit()
        with pytest.raises(ActionExecutionError) as err:
            svc.submit_action(
                actor=ae_world["actor"],
                payload=payload,
                whitelist_gate=AllowAllWhitelist(),
                dispatch=RecordingDispatch(),
            )
        assert err.value.code == "idempotency_in_flight"
        assert err.value.status == 409

    def test_whitelist_fail_closed_default(self, db_session, ae_world) -> None:
        """白名单缺失/未配置 → 403 且零外呼零落库（禁改清单第 7 项 fail-closed）。"""
        from fde_api.action_execution.errors import ActionExecutionError
        from fde_api.action_execution.models import ActionExecution

        svc = self._svc()
        payload = _request(org_id=ae_world["org"].id, requester_id=ae_world["actor"].id)
        dispatch = RecordingDispatch()
        with pytest.raises(ActionExecutionError) as err:
            svc.submit_action(actor=ae_world["actor"], payload=payload, dispatch=dispatch)
        assert err.value.code == "tool_not_allowed"
        assert err.value.status == 403
        assert dispatch.calls == 0
        assert db_session.query(ActionExecution).count() == 0

    def test_whitelist_deny_zero_calls(self, db_session, ae_world) -> None:
        from fde_api.action_execution.errors import ActionExecutionError

        svc = self._svc()
        dispatch = RecordingDispatch()
        with pytest.raises(ActionExecutionError) as err:
            svc.submit_action(
                actor=ae_world["actor"],
                payload=_request(org_id=ae_world["org"].id, requester_id=ae_world["actor"].id),
                whitelist_gate=DenyAllWhitelist(),
                dispatch=dispatch,
            )
        assert err.value.code == "tool_not_allowed"
        assert dispatch.calls == 0


# ---- 集成面：审批闸（第 4 层；复用 AutomationApproval + decide_automation_approval） --


def _make_approval(db_session, world, *, params: dict | None = None, status: str = "approved",
                   risk_level: int = 3, expires_in: int = 30, requested_by=None,
                   reviewed_by=None) -> Any:
    """直造 AE 审批单（run_id=None；拍板面复用兼容由专用钉验证）。"""
    from datetime import datetime

    from fde_api.control.models import AutomationApproval

    arguments = params or {"sku": "SKU-001"}
    return AutomationApproval(
        run_id=None,
        workflow_node_run_id=None,
        project_id=world["project"].id,
        requested_by_user_id=(requested_by or world["actor"]).id,
        reviewed_by_user_id=reviewed_by.id if reviewed_by is not None else (world["reviewer"].id if status == "approved" else None),
        request_key=f"ae-{uuid4().hex[:12]}",
        capability=AE_CAPABILITY,
        tool_name="mock.erp.query_inventory",
        arguments_json=arguments,
        arguments_sha256=_sha256_of(_canonical(arguments)),
        risk_level=risk_level,
        status=status,
        expires_at=datetime.now(UTC) + timedelta(minutes=expires_in),
    )


class TestApprovalGate:
    def _write_request(self, world, approval_id):
        return _request(
            connector_id="mock.email",
            method="send",
            action_id="mock.email.send",
            dry_run=False,
            risk_level=3,
            approval_id=approval_id,
            org_id=world["org"].id,
            requester_id=world["actor"].id,
        )

    def test_missing_approval_id_403(self, db_session, ae_world) -> None:
        """写型 risk≥3 缺 approval_id → 运行时第 4 层 403（先于第 5 层 422）。"""
        from fde_api.action_execution.errors import ActionExecutionError

        from fde_api.action_execution import service as svc_mod

        with pytest.raises(ActionExecutionError) as err:
            svc_mod.submit_action(
                actor=ae_world["actor"],
                payload=self._write_request(ae_world, None),
                whitelist_gate=AllowAllWhitelist(),
            )
        assert err.value.code == "approval_required"
        assert err.value.status == 403

    def test_approval_not_found_404(self, db_session, ae_world) -> None:
        from fde_api.action_execution import service as svc_mod
        from fde_api.action_execution.errors import ActionExecutionError

        with pytest.raises(ActionExecutionError) as err:
            svc_mod.submit_action(
                actor=ae_world["actor"],
                payload=self._write_request(ae_world, "ap-not-exist"),
                whitelist_gate=AllowAllWhitelist(),
            )
        assert err.value.code == "approval_not_found"

    def test_cross_tenant_approval_404(self, db_session, ae_world) -> None:
        """审批单挂乙 org 项目、请求为甲 org → 404 不泄露（S-AE-05 家族）。"""
        from fde_api.action_execution import service as svc_mod
        from fde_api.action_execution.errors import ActionExecutionError

        foreign_world_org = make_enterprise_org(db_session)
        foreign_user = make_user(db_session, "project_lead", org_id=foreign_world_org.id)
        foreign_project = make_project(
            db_session, foreign_user, code=f"AEB{uuid4().hex[:6]}", org_id=foreign_world_org.id
        )
        db_session.commit()
        approval = _make_approval(db_session, ae_world, status="approved")
        approval.project_id = foreign_project.id
        db_session.add(approval)
        db_session.commit()
        with pytest.raises(ActionExecutionError) as err:
            svc_mod.submit_action(
                actor=ae_world["actor"],
                payload=self._write_request(ae_world, approval.id),
                whitelist_gate=AllowAllWhitelist(),
            )
        assert err.value.code == "approval_not_found"

    def test_pending_409_and_rejected_409(self, db_session, ae_world) -> None:
        from fde_api.action_execution import service as svc_mod
        from fde_api.action_execution.errors import ActionExecutionError

        for status in ("pending", "rejected"):
            approval = _make_approval(db_session, ae_world, status=status)
            db_session.add(approval)
            db_session.commit()
            with pytest.raises(ActionExecutionError) as err:
                svc_mod.submit_action(
                    actor=ae_world["actor"],
                    payload=self._write_request(ae_world, approval.id),
                    whitelist_gate=AllowAllWhitelist(),
                )
            assert err.value.code == "approval_not_approved", status

    def test_expired_409(self, db_session, ae_world) -> None:
        from fde_api.action_execution import service as svc_mod
        from fde_api.action_execution.errors import ActionExecutionError

        for status in ("expired", "pending"):
            approval = _make_approval(db_session, ae_world, status=status, expires_in=-1)
            db_session.add(approval)
            db_session.commit()
            with pytest.raises(ActionExecutionError) as err:
                svc_mod.submit_action(
                    actor=ae_world["actor"],
                    payload=self._write_request(ae_world, approval.id),
                    whitelist_gate=AllowAllWhitelist(),
                )
            assert err.value.code == "approval_expired", status

    def test_integrity_mismatch_409(self, db_session, ae_world) -> None:
        """审批参数指纹复算不符 → 409（沿 control/service.py:864-871 先例）。"""
        from fde_api.action_execution import service as svc_mod
        from fde_api.action_execution.errors import ActionExecutionError

        approval = _make_approval(db_session, ae_world, status="approved", params={"sku": "SKU-REAL"})
        db_session.add(approval)
        db_session.commit()
        payload = self._write_request(ae_world, approval.id)
        payload["params"] = {"sku": "SKU-DRIFT"}
        with pytest.raises(ActionExecutionError) as err:
            svc_mod.submit_action(actor=ae_world["actor"], payload=payload, whitelist_gate=AllowAllWhitelist())
        assert err.value.code == "approval_integrity_failed"

    def test_wrong_requester_404(self, db_session, ae_world) -> None:
        """审批单归属他人（requested_by ≠ 请求 requester）→ 404 不泄露。"""
        from fde_api.action_execution import service as svc_mod
        from fde_api.action_execution.errors import ActionExecutionError

        approval = _make_approval(db_session, ae_world, status="approved", requested_by=ae_world["reviewer"])
        db_session.add(approval)
        db_session.commit()
        payload = self._write_request(ae_world, approval.id)
        with pytest.raises(ActionExecutionError) as err:
            svc_mod.submit_action(actor=ae_world["actor"], payload=payload, whitelist_gate=AllowAllWhitelist())
        assert err.value.code == "approval_not_found"

    def test_permission_revoked_403(self, db_session, ae_world) -> None:
        """执行前权限重验失败 → 403（viewer 无 AE 能力档位）。"""
        from fde_api.action_execution import service as svc_mod
        from fde_api.action_execution.errors import ActionExecutionError

        viewer = make_user(db_session, "viewer", org_id=ae_world["org"].id)
        db_session.commit()
        approval = _make_approval(db_session, ae_world, status="approved", requested_by=viewer)
        db_session.add(approval)
        db_session.commit()
        payload = self._write_request(ae_world, approval.id)
        payload["requester_id"] = viewer.id
        with pytest.raises(ActionExecutionError) as err:
            svc_mod.submit_action(actor=viewer, payload=payload, whitelist_gate=AllowAllWhitelist())
        assert err.value.code == "permission_revoked"

    def test_approved_high_risk_write_full_chain(self, db_session, ae_world) -> None:
        """approved 审批全链：succeeded + audit.approval_id 非 null 且等于提交值
        （S-AE-01 A9 语境腿）＋副作用一次。"""
        from fde_api.action_execution import service as svc_mod

        approval = _make_approval(db_session, ae_world, status="approved")
        db_session.add(approval)
        db_session.commit()
        payload = self._write_request(ae_world, approval.id)
        dispatch = RecordingDispatch({"message_id": "m-9", "delivered_count": 1})
        result = svc_mod.submit_action(
            actor=ae_world["actor"], payload=payload, whitelist_gate=AllowAllWhitelist(), dispatch=dispatch
        )
        assert result["status"] == "succeeded"
        assert result["audit"]["approval_id"] == approval.id
        assert dispatch.calls == 1


# ---- 集成面：租户绑定 + 查询 + 路由 --------------------------------------------


class TestTenantAndRoutes:
    def test_org_mismatch_404(self, db_session, ae_world) -> None:
        """请求体 org_id 与服务端上下文不一致 → 404（U1 request_org_source / Q15）。"""
        from fde_api.action_execution import service as svc_mod
        from fde_api.action_execution.errors import ActionExecutionError

        with pytest.raises(ActionExecutionError) as err:
            svc_mod.submit_action(
                actor=ae_world["actor"],
                payload=_request(org_id=ae_world["outsider"].org_id, requester_id=ae_world["actor"].id),
                whitelist_gate=AllowAllWhitelist(),
            )
        assert err.value.code == "not_found"
        assert err.value.status == 404

    def test_get_execution_owner_and_cross_tenant(self, client, db_session, ae_world, settings) -> None:
        from fde_api.action_execution import service as svc_mod
        from fde_api.action_execution.models import ActionExecution

        row = ActionExecution(
            id=uuid4().hex,
            idempotency_key="idem-get-" + uuid4().hex[:6],
            org_id=ae_world["org"].id,
            requester_id=ae_world["actor"].id,
            action_id="mock.erp.query_inventory",
            connector_id="mock.erp",
            method="query_inventory",
            params_sha256="a" * 64,
            request_fingerprint="b" * 64,
            dry_run=True,
            risk_level=0,
            approval_id=None,
            status="succeeded",
            output_json={"simulated": True},
            audit_json={},
            cost_json={},
            rollback_json={},
        )
        db_session.add(row)
        db_session.commit()

        ok = client.get(f"/api/v1/action-executions/{row.id}", headers=_auth(ae_world["actor"], settings))
        assert ok.status_code == 200
        assert ok.get_json()["data"]["status"] == "succeeded"

        denied = client.get(f"/api/v1/action-executions/{row.id}", headers=_auth(ae_world["outsider"], settings))
        assert denied.status_code == 404
        assert denied.get_json()["error"]["code"] == "not_found"

    def test_post_route_default_fail_closed_envelope(self, client, db_session, ae_world, settings) -> None:
        """路由默认门（无白名单装配）→ 403 tool_not_allowed 信封（fail-closed 红线）。"""
        res = client.post(
            "/api/v1/action-executions",
            json=_request(org_id=ae_world["org"].id, requester_id=ae_world["actor"].id),
            headers=_auth(ae_world["actor"], settings),
        )
        assert res.status_code == 403
        body = res.get_json()
        assert body["data"] is None
        assert body["error"]["code"] == "tool_not_allowed"

    def test_post_route_missing_key_422_envelope(self, client, db_session, ae_world, settings) -> None:
        payload = _request(org_id=ae_world["org"].id, requester_id=ae_world["actor"].id)
        payload.pop("idempotency_key")
        res = client.post(
            "/api/v1/action-executions", json=payload, headers=_auth(ae_world["actor"], settings)
        )
        assert res.status_code == 422
        assert res.get_json()["error"]["code"] == "validation_failed"

    def test_unauthenticated_403_or_401(self, client, db_session, ae_world) -> None:
        res = client.post("/api/v1/action-executions", json=_request())
        assert res.status_code in (401, 403)


# ---- 审批面复用兼容钉（禁改面零触碰证明） --------------------------------------


class TestApprovalPlaneReuse:
    def test_decide_automation_approval_accepts_ae_approval(self, db_session, ae_world) -> None:
        """AE 审批单（run_id=None）经既有拍板面异人复核 approve 成功——
        decide_automation_approval 本体零改动即兼容（U1 x-approval.reuse）。"""
        approval = _make_approval(db_session, ae_world, status="pending")
        db_session.add(approval)
        db_session.commit()
        result = decide_automation_approval(
            user=ae_world["reviewer"],
            approval_id=approval.id,
            decision_value="approve",
            password=PASSWORD,
            reason="AE1 复用钉",
        )
        assert result["status"] == "approved"

    def test_four_eyes_self_review_forbidden(self, db_session, ae_world) -> None:
        """四眼闸：AE 审批单自提自批 → 409 self_review_forbidden（拍板面既有语义）。"""
        approval = _make_approval(db_session, ae_world, status="pending")
        db_session.add(approval)
        db_session.commit()
        with pytest.raises(ControlServiceError) as err:
            decide_automation_approval(
                user=ae_world["actor"],
                approval_id=approval.id,
                decision_value="approve",
                password=PASSWORD,
                reason="自批应被拦",
            )
        assert err.value.code == "self_review_forbidden"


# ---- 能力注册钉（CAPABILITY_REQUIREMENTS additive 条目） -----------------------


class TestCapabilityRegistration:
    def test_ae_capability_registered(self) -> None:
        from fde_api.control.access import CAPABILITY_REQUIREMENTS

        assert CAPABILITY_REQUIREMENTS.get(AE_CAPABILITY) == "project_operator"
