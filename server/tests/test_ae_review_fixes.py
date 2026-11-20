"""AE1 评审修复轮钉（bmad-code-review 2026-11-20，P1–P17/D1/D2/D5 甲案落地守护）。

钉名与 `_ae1-wp5-report.md` §8 评审发现一一对应；每钉注释标注评审组号。
第 2/3 组评审（负向钉面/评测工具面）待本轮处置后续跑。
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from json import dumps as _json_dumps
from typing import Any

import pytest

import _ae_mock_stack as mock_stack_module
from fde_api.action_execution import connectors
from fde_api.action_execution import service as ae_service
from fde_api.action_execution.connectors import ConnectorWhitelist, HttpDispatch, load_whitelist
from fde_api.action_execution.errors import ActionExecutionError
from fde_api.action_execution.schemas import validate_request_shape
from fde_api.control.service import APPROVABLE_DSH_TOOLS
from multi_tenant_harness import make_enterprise_org, make_user

_SERVER_ROOT = __file__.rsplit("server", 1)[0]
_SNAPSHOT = _SERVER_ROOT + "server/src/fde_api/action_execution/whitelist.json"


def _request(**overrides: Any) -> dict:
    req: dict = {
        "action_id": "mock.email.send",
        "action_type": "send_email",
        "connector_id": "mock.email",
        "method": "send",
        "params": {"to": "ops@example.test", "subject": "s-fix", "body": "b-fix"},
        "idempotency_key": "idem-fix-" + uuid.uuid4().hex[:8],
        "org_id": "org-fix",
        "requester_id": "user-fix",
        "dry_run": False,
        "risk_level": 3,
        "timeout_seconds": 300,
        "approval_id": None,
    }
    req.update(overrides)
    return req


def _erp_request(actor: Any, sku: str, *, key: str | None = None, **overrides: Any) -> dict:
    payload = _request(
        connector_id="mock.erp",
        method="query_inventory",
        action_id="mock.erp.query-inventory",
        action_type="call_api",
        params={"sku": sku},
        idempotency_key=key or ("idem-fix-" + uuid.uuid4().hex[:8]),
        org_id=actor.org_id,
        requester_id=actor.id,
        risk_level=0,
        dry_run=False,
    )
    payload.update(overrides)
    return payload


@pytest.fixture(scope="module")
def mock_stack():
    stack = mock_stack_module.MockStack(erp_port=0, email_port=0)
    stack.start()
    yield stack
    stack.stop()


@pytest.fixture(scope="module")
def wb_service(test_settings):
    svc = mock_stack_module.WorkbenchService(test_settings)
    svc.start()
    yield svc
    svc.stop()


@pytest.fixture(scope="module")
def wb_port(wb_service):
    return wb_service.port


def _gates(stack: Any, *, timeout_seconds: float = 5.0) -> tuple[ConnectorWhitelist, HttpDispatch]:
    """白名单门＋dispatch（桩端口注入面——WP5 runner ``_live_gates`` 同款装置级
    快照构造：快照 base_url 注入本进程桩实际端口；生产门仍用冻结快照原文）。"""
    snapshot = load_whitelist(_SNAPSHOT)
    for conn in snapshot["connectors"]:
        cid = conn.get("id")
        if cid == "mock.erp":
            conn["base_url"] = f"http://127.0.0.1:{stack.erp_port}"
        elif cid == "mock.email":
            conn["base_url"] = f"http://127.0.0.1:{stack.email_port}"
    gate = ConnectorWhitelist(snapshot)
    dispatch = HttpDispatch(whitelist=gate, whitelist_snapshot=snapshot, timeout_seconds=timeout_seconds)
    return gate, dispatch


@pytest.fixture
def fix_world(db_session):
    org = make_enterprise_org(db_session)
    actor = make_user(db_session, "project_lead", org_id=org.id)
    viewer = make_user(db_session, "viewer", org_id=org.id)
    db_session.commit()
    return {"org": org, "actor": actor, "viewer": viewer}


# ---- P1：finalize 只翻本请求锁行（mismatch 路径零误伤） ------------------------


class TestP1FinalizeScope:
    def test_mismatch_reject_does_not_poison_prior_row(self, db_session, fix_world, mock_stack, wb_service, wb_port):
        """P1：同键异体 409 后，先前已 succeeded 行原样保留（终态不可变）。"""
        actor = fix_world["actor"]
        gate, dispatch = _gates(mock_stack)
        key = "idem-p1-" + uuid.uuid4().hex[:8]
        first = ae_service.submit_action(
            actor=actor,
            payload=_erp_request(actor, "SKU-P1", key=key),
            whitelist_gate=gate,
            dispatch=dispatch,
        )
        assert first["status"] == "succeeded"
        # 异体提交（同键异参）→ 409 mismatch；先前行不得被 finalize 污染
        with pytest.raises(ActionExecutionError) as err:
            ae_service.submit_action(
                actor=actor,
                payload=_erp_request(actor, "SKU-P1-OTHER", key=key),
                whitelist_gate=gate,
                dispatch=dispatch,
            )
        assert err.value.code == "idempotency_mismatch"
        db_session.expire_all()
        row_after = ae_service.get_execution_row(first["execution_id"])
        assert row_after is not None and row_after.status == "succeeded"  # 评审 P1 主断言
        assert row_after.error_json is None


# ---- P2：risk_level 白名单对齐（自声明不得低于登记值） ------------------------


class TestP2RiskAlignment:
    def test_declared_lower_than_registered_requires_approval(self, db_session, fix_world, mock_stack, wb_service, wb_port):
        """P2：mock.email send（登记 risk 3）自报 risk 2 无审批 → 403 approval_required。"""
        actor = fix_world["actor"]
        gate, dispatch = _gates(mock_stack)
        with pytest.raises(ActionExecutionError) as err:
            ae_service.submit_action(
                actor=actor,
                payload=_request(
                    idempotency_key="idem-p2-" + uuid.uuid4().hex[:8],
                    org_id=actor.org_id,
                    requester_id=actor.id,
                    risk_level=2,  # 自声明低于登记 3
                    approval_id=None,
                ),
                whitelist_gate=gate,
                dispatch=dispatch,
            )
        assert err.value.code == "approval_required"


# ---- P3：KD-01 失败腿（error 非 null / data 缺失 → 不产出伪 output） ----------


class TestP3Kd01FailureLeg:
    @pytest.mark.parametrize(
        "payload",
        [
            {"data": {"items": []}, "error": {"code": "x"}},  # error 非 null
            {"error": None},  # data 缺失
        ],
    )
    def test_kd01_failure_maps_to_closed_set(self, payload) -> None:
        with pytest.raises(ActionExecutionError) as err:
            connectors.normalize_output(connector_id="workbench.ontology", method="read", payload_json=payload, org_id="o")
        assert err.value.code == "tool_not_allowed"
        assert err.value.details is not None
        assert err.value.details["reason"] == "normalization_failed"


# ---- P6：闭集外异常兜底（防裸 500/锁残留） ------------------------------------


class TestP6BareExceptionClosure:
    def test_bare_exception_maps_and_finalizes_failed(self, db_session, fix_world, mock_stack, wb_service, wb_port):
        """P6：dispatch 抛非 ActionExecutionError → 闭集映射＋锁行翻 failed（不残留 awaiting）。"""

        class _ExplodingDispatch:
            def call(self, request: dict) -> dict:
                raise RuntimeError("boom-not-a-domain-error")

        actor = fix_world["actor"]
        gate = ConnectorWhitelist(load_whitelist(_SNAPSHOT))
        key = "idem-p6-" + uuid.uuid4().hex[:8]
        with pytest.raises(ActionExecutionError) as err:
            ae_service.submit_action(
                actor=actor,
                payload=_erp_request(actor, "SKU-P6", key=key),
                whitelist_gate=gate,
                dispatch=_ExplodingDispatch(),
            )
        assert err.value.code == "tool_not_allowed"
        assert err.value.details is not None and err.value.details["reason"] == "RuntimeError"
        row = ae_service.get_execution_row(
            ae_service._in_flight_row({"idempotency_key": key, "org_id": actor.org_id}).id
        )
        assert row is not None and row.status == "failed"  # 锁行诚实 failed（不残留 awaiting_approval）


# ---- D1：failed 行同键重试复放原失败响应 --------------------------------------


class _FailingDispatch:
    """恒失败（模拟上游 503 → 闭集映射）；与桩计数无耦合。"""

    def call(self, request: dict) -> dict:
        raise ActionExecutionError(
            "tool_not_allowed", "上游失败（模拟 503）。", details={"reason": "connector_upstream_error", "http_status": 503}
        )


class TestD1FailedReplay:
    def test_failed_row_replay_returns_original_error(self, db_session, fix_world, mock_stack, wb_service, wb_port):
        actor = fix_world["actor"]
        gate, dispatch = _gates(mock_stack)
        key = "idem-d1-" + uuid.uuid4().hex[:8]
        with pytest.raises(ActionExecutionError) as first:
            ae_service.submit_action(
                actor=actor,
                payload=_erp_request(actor, "SKU-D1", key=key),
                whitelist_gate=gate,
                dispatch=_FailingDispatch(),
            )
        assert first.value.code == "tool_not_allowed"
        # 同键同体重试 → 复放**原失败响应**（评审 D1 甲案）：status=failed＋原 error
        result = ae_service.submit_action(
            actor=actor,
            payload=_erp_request(actor, "SKU-D1", key=key),
            whitelist_gate=gate,
            dispatch=dispatch,  # 恢复正常 dispatch——仍按快照复放原失败态
        )
        assert result["status"] == "failed"
        assert result["error"] is not None and result["error"]["code"] == "tool_not_allowed"


# ---- D5：capability 主路径接线（org 域档位校验） ------------------------------


class TestD5CapabilityWiring:
    def test_viewer_submit_is_permission_revoked(self, db_session, fix_world, mock_stack, wb_service, wb_port):
        """D5 甲案：viewer（assistant_read < project_operator）提交 → 403 permission_revoked。"""
        viewer = fix_world["viewer"]
        gate, dispatch = _gates(mock_stack)
        with pytest.raises(ActionExecutionError) as err:
            ae_service.submit_action(
                actor=viewer,
                payload=_erp_request(viewer, "SKU-D5", dry_run=True),  # 连干跑也须档位
                whitelist_gate=gate,
                dispatch=dispatch,
            )
        assert err.value.code == "permission_revoked"


# ---- P7：连接器防御面 ---------------------------------------------------------


class TestP7ConnectorDefenses:
    def test_deep_shape_fail_closed(self, tmp_path) -> None:
        """P7a：白名单深层形态破缺（元素非 dict／base_url 非法／bindings 非 dict）→ fail-closed。"""
        for mutate in (
            lambda snap: snap["connectors"].append("not-a-dict"),
            lambda snap: snap["connectors"][0].__setitem__("base_url", "http://[bad"),
            lambda snap: snap["connectors"][0].__setitem__("http_bindings", ["not-a-dict"]),
        ):
            snap = load_whitelist(_SNAPSHOT)
            mutate(snap)
            target = tmp_path / "broken.json"
            target.write_text(_json_dumps(snap), encoding="utf-8")
            with pytest.raises(ActionExecutionError) as err:
                load_whitelist(str(target))
            assert err.value.code == "tool_not_allowed"
            assert err.value.details is not None and err.value.details["reason"] == "whitelist_shape_invalid"

    def test_unknown_auth_type_fails_closed(self) -> None:
        """P7b：登记外 auth_type → fail-closed（不得静默无凭据头外呼）。"""
        with pytest.raises(ActionExecutionError) as err:
            connectors.build_outbound_headers(auth_type="hmac", token=None, idempotency_key="k")
        assert err.value.code == "tool_not_allowed"
        assert err.value.details is not None and err.value.details["reason"] == "auth_type_not_registered"

    def test_path_param_non_scalar_422(self) -> None:
        """P7c：路径模板参数非标量（None）→ 422 validation_failed。"""
        spec = {"base_url": "http://127.0.0.1:5001", "http_bindings": [{"http_method": "GET", "path": "/x/{id}"}]}
        with pytest.raises(ActionExecutionError) as err:
            connectors.expand_path_template(spec, {"id": None})
        assert err.value.code == "validation_failed"
        assert err.value.details is not None and err.value.details["reason"] == "path_param_not_scalar"

    def test_non_finite_number_422(self) -> None:
        """P7：params 含 NaN → 422（L1 拦下，不在指纹链路炸裸 ValueError）。"""
        payload = _request(params={"to": "a@b.t", "weight": float("nan")})
        with pytest.raises(ActionExecutionError) as err:
            validate_request_shape(payload)
        assert err.value.code == "validation_failed"


# ---- P8：timeout_seconds 接线 -------------------------------------------------


class TestP8TimeoutWiring:
    def test_request_timeout_wired_to_dispatch(self, db_session, fix_world, mock_stack, wb_service, wb_port):
        """P8：请求 timeout_seconds=1 < 上游 delay 2s → connector_timeout（声明字段生效）。"""
        actor = fix_world["actor"]
        gate, dispatch = _gates(mock_stack, timeout_seconds=300.0)
        with pytest.raises(ActionExecutionError) as err:
            ae_service.submit_action(
                actor=actor,
                payload=_erp_request(actor, "__timeout__", timeout_seconds=1),
                whitelist_gate=gate,
                dispatch=dispatch,
            )
        assert err.value.code == "tool_not_allowed"
        assert err.value.details is not None and err.value.details["reason"] == "connector_timeout"

    def test_server_cap_binds_request_declaration(self, db_session, fix_world, mock_stack, wb_service, wb_port):
        """P8 反向：服务端上限 0.3s < 请求声明 300 → 服务端上限生效（min 语义）。"""
        actor = fix_world["actor"]
        gate = ConnectorWhitelist(load_whitelist(_SNAPSHOT))
        dispatch = HttpDispatch(whitelist=gate, whitelist_snapshot=load_whitelist(_SNAPSHOT), timeout_seconds=0.3)
        with pytest.raises(ActionExecutionError) as err:
            ae_service.submit_action(
                actor=actor,
                payload=_erp_request(actor, "__timeout__", timeout_seconds=300),
                whitelist_gate=gate,
                dispatch=dispatch,
            )
        # CI 环境连接阶段即可能耗尽 0.3s cap（代理 env/IPv6 解析慢）→ ConnectTimeout 映射
        # connector_connect_failed；两码同属「服务端上限生效」的诚实映射（钉意图=cap min 语义，
        # 非读阶段细分），故双码接受。本机直连快，稳定复现 connector_timeout。
        assert err.value.details is not None and err.value.details["reason"] in (
            "connector_timeout",
            "connector_connect_failed",
        )


# ---- P9：多 binding 三元组对齐 ------------------------------------------------


class TestP9MultiBinding:
    def test_second_method_uses_second_binding_path(self) -> None:
        """P9：两 method 两 binding——第二 method 的 URL 取第二 binding 的 path。"""
        spec = {
            "base_url": "http://127.0.0.1:5001",
            "methods": ["read", "detail"],
            "http_bindings": [
                {"http_method": "GET", "path": "/first"},
                {"http_method": "GET", "path": "/second/{id}"},
            ],
        }
        gate = ConnectorWhitelist(
            {"version": "test", "connectors": [dict(spec, id="probe.conn", auth_type="api_key", risk_level=0)]}
        )
        binding = gate.binding_for(spec, "detail")
        url, rest = connectors.expand_path_template(spec, {"id": "9"}, binding)
        assert url.endswith("/second/9")  # 评审 P9 主断言（先前恒取 bindings[0] → /first）
        assert rest == {}


# ---- P11：禁跟随重定向钉 ------------------------------------------------------


class TestP11NoRedirect:
    def test_upstream_302_not_followed(self, db_session, fix_world, mock_stack, wb_service, wb_port):
        """P11：上游 302 → 不跟随（零二次外呼）＋闭集映射 details.http_status=302。"""
        actor = fix_world["actor"]
        gate, dispatch = _gates(mock_stack)
        before = mock_stack.erp_requests
        with pytest.raises(ActionExecutionError) as err:
            ae_service.submit_action(
                actor=actor,
                payload=_erp_request(actor, "__redirect__"),
                whitelist_gate=gate,
                dispatch=dispatch,
            )
        assert err.value.code == "tool_not_allowed"
        assert err.value.details is not None and err.value.details["http_status"] == 302
        assert mock_stack.erp_requests == before + 1  # 恰一次外呼：302 目标未被跟随


# ---- P5：G-AE-1 注册表值派发（端到端） ----------------------------------------


class TestP5RegistryDispatch:
    def test_registry_entry_routes_to_its_executor(self, db_session, fix_world):
        """P5：注册 probe 执行器 → execute_approved_dsh_tool 按注册表值派发（死派发已修）。"""
        from fde_api.control import service as control_svc
        from fde_api.control import access as control_access
        from fde_api.control.models import AutomationApproval
        from multi_tenant_harness import make_project

        org = fix_world["org"]
        actor = fix_world["actor"]
        project = make_project(db_session, actor, code=f"AE1FIX{uuid.uuid4().hex[:6]}", org_id=org.id)
        db_session.commit()
        probe_calls: list[str] = []

        def _probe_executor(*, session: Any, approval: Any) -> dict[str, Any]:
            probe_calls.append(approval.id)
            return {"probed": True}

        key = ("ae1.eval.probe", "ae1.eval.probe.tool")
        APPROVABLE_DSH_TOOLS[key] = _probe_executor
        control_access.CAPABILITY_REQUIREMENTS[key[0]] = "project_operator"  # probe 能力临时注册
        try:
            approval = AutomationApproval(
                id=str(uuid.uuid4()),
                run_id=None,
                workflow_node_run_id=None,
                project_id=project.id,
                requested_by_user_id=actor.id,
                request_key=f"ae1-fix-p5-{uuid.uuid4().hex[:10]}",
                capability=key[0],
                tool_name=key[1],
                risk_level=3,  # ck_automation_approvals_risk：审批行域 3..4
                status="approved",
                arguments_json={},
                arguments_sha256=sha256(b"{}").hexdigest(),
                expires_at=datetime.now(UTC) + timedelta(hours=1),
            )
            db_session.add(approval)
            db_session.commit()
            control_svc.execute_approved_dsh_tool(approval_id=approval.id)
            assert probe_calls == [approval.id]  # 评审 P5 主断言：派发走注册表值
        finally:
            APPROVABLE_DSH_TOOLS.pop(key, None)
            control_access.CAPABILITY_REQUIREMENTS.pop(key[0], None)


# ---- P14：replayed 行回滚入态（noop） -----------------------------------------


class TestP14ReplayedRollback:
    def test_replayed_row_rollback_is_noop(self, db_session, fix_world):
        """P14：replayed 行 rollback → noop（先前零覆盖的入态判定分支）。"""
        from fde_api.action_execution.models import ActionExecution

        row = ActionExecution(
            id=str(uuid.uuid4()),
            idempotency_key="idem-p14-" + uuid.uuid4().hex[:8],
            org_id=fix_world["org"].id,
            requester_id=fix_world["actor"].id,
            action_id="mock.erp.query-inventory",
            connector_id="mock.erp",
            method="query_inventory",
            params_sha256="a" * 64,
            request_fingerprint="f" * 64,
            dry_run=False,
            risk_level=0,
            status="succeeded",
            replayed_from_execution_id=str(uuid.uuid4()),  # 复放行
            audit_json={},
            cost_json={},
            rollback_json={"supported": False},
        )
        db_session.add(row)
        db_session.commit()
        result = ae_service.rollback_action(actor=fix_world["actor"], execution_id=row.id)
        assert result["status"] == "noop"
