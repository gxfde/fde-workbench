"""AE2-WP3：编排执行器（54 号 v0.2-ACTIVE §3；编排契约 ``_ae2-execution-contract-v1.json``）。

S-AE-07 提交期静态拒（A1–A7/A8–A10）＋ S-AE-08 运行期幂等与 fail-fast（B1/B7–B10）
＋ x-validation-order S1–S5 分层短路。补偿面（B2–B6/B11）见
``test_ae_task_compensation.py``。

族纪律（负向设计 §1）：①拒绝路径**零副作用**（外呼计数 == 0 且无运行行落库）；
②环检测在**提交期**完成（不靠运行期迭代上限兜底）；③拒绝消息不回显敏感键名。
"""
from __future__ import annotations

import threading
from typing import Any
from uuid import uuid4

import pytest

from fde_api.action_execution.errors import ActionExecutionError
from multi_tenant_harness import make_enterprise_org, make_user

# ---- 桩与夹具 ----------------------------------------------------------------


class AllowAllWhitelist:
    """提交期预检放行桩（真实白名单门由生产装配；此处只验证编排层自身逻辑）。"""

    def check(self, connector_id: str, method: str) -> None:
        return None


class RejectingWhitelist:
    """白名单未登记桩（A5/A6：提交期预检须把 403 映射为 422 静态拒）。"""

    def __init__(self, *, reject_methods: set[str] | None = None) -> None:
        self.reject_methods = reject_methods  # None＝全拒；集合＝按方法拒

    def check(self, connector_id: str, method: str) -> None:
        if self.reject_methods is None or method in self.reject_methods:
            raise ActionExecutionError("tool_not_allowed", "连接器/方法未在白名单注册（fail-closed）。")
        return None


class TaskDispatch:
    """节点派发桩：按 action_id 给产物、计数、可注入真异常（基础设施失败腿）。"""

    def __init__(
        self,
        *,
        fail_action_ids: set[str] | None = None,
        outputs: dict[str, dict[str, Any]] | None = None,
        delay: float = 0.0,
    ) -> None:
        self._lock = threading.Lock()
        self.calls = 0
        self.seen: list[dict[str, Any]] = []
        self.fail_action_ids = fail_action_ids or set()
        self.outputs = outputs or {}
        self.delay = delay

    def call(self, request: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            self.calls += 1
            self.seen.append(dict(request))
        if self.delay:
            import time

            time.sleep(self.delay)
        if request["action_id"] in self.fail_action_ids:
            raise RuntimeError("dispatch exploded")  # 非域异常 → service 兜底映射
        return dict(self.outputs.get(request["action_id"], {"available": 3, "quantity": 1}))


@pytest.fixture
def task_env(db_session):
    org = make_enterprise_org(db_session)
    actor = make_user(db_session, "project_lead", org_id=org.id)
    org_b = make_enterprise_org(db_session)
    actor_b = make_user(db_session, "project_lead", org_id=org_b.id)
    viewer = make_user(db_session, "viewer", org_id=org.id)
    db_session.commit()
    return {
        "org": org,
        "actor": actor,
        "org_b": org_b,
        "actor_b": actor_b,
        "viewer": viewer,
    }


def _node(key: str, depends: tuple[str, ...] = (), *, rollback: bool = True, **act_over: Any) -> dict[str, Any]:
    action: dict[str, Any] = {
        "action_id": f"mock.erp.{key}",
        "connector_id": "mock.erp",
        "method": "query_inventory",
        "params": {"sku": {"kind": "literal", "value": f"SKU-{key}"}},
        "dry_run": False,
        "risk_level": 1,
        "timeout_seconds": 30,
    }
    action.update(act_over)
    return {"node_key": key, "depends_on": list(depends), "action": action, "rollback_supported": rollback}


def _task(org_id: str, requester_id: str, nodes: list[dict[str, Any]], *, key: str | None = None) -> dict[str, Any]:
    return {
        "org_id": org_id,
        "requester_id": requester_id,
        "idempotency_key": key or ("ae2-task-" + uuid4().hex[:10]),
        "definition": {"nodes": nodes},
    }


def _run_rows_for_key(db_session, key: str) -> int:
    from sqlalchemy import select

    from fde_api.action_execution.models import ActionTaskRun

    return len(
        db_session.scalars(select(ActionTaskRun).where(ActionTaskRun.idempotency_key == key)).all()
    )


def _expect_reject(exc: pytest.ExceptionInfo, *, code: str, status: int) -> None:
    assert isinstance(exc.value, ActionExecutionError)
    assert exc.value.code == code
    assert exc.value.status == status


# ---- S-AE-07 · S1 图结构层（A1–A4；提交期静态拒＋零副作用） --------------------


class TestS1GraphStructure:
    def test_a1_cycle_rejected_at_submit_with_zero_side_effects(self, db_session, task_env) -> None:
        """A1：含环定义提交期 422（Kahn 剩余非空判环），零外呼、零运行行。"""
        from fde_api.action_execution import task_orchestrator as orch

        payload = _task(
            task_env["org"].id,
            task_env["actor"].id,
            [_node("n1", ("n2",)), _node("n2", ("n1",))],
        )
        dispatch = TaskDispatch()
        with pytest.raises(ActionExecutionError) as exc:
            orch.submit_task(
                actor=task_env["actor"], payload=payload, whitelist_gate=AllowAllWhitelist(), dispatch=dispatch
            )
        _expect_reject(exc, code="validation_failed", status=422)
        assert dispatch.calls == 0  # 零外呼
        assert _run_rows_for_key(db_session, payload["idempotency_key"]) == 0  # 零运行行

    def test_a1b_self_dependency_is_a_cycle(self, db_session, task_env) -> None:
        from fde_api.action_execution import task_orchestrator as orch

        payload = _task(task_env["org"].id, task_env["actor"].id, [_node("n1", ("n1",))])
        dispatch = TaskDispatch()
        with pytest.raises(ActionExecutionError) as exc:
            orch.submit_task(
                actor=task_env["actor"], payload=payload, whitelist_gate=AllowAllWhitelist(), dispatch=dispatch
            )
        _expect_reject(exc, code="validation_failed", status=422)
        assert dispatch.calls == 0

    def test_a2_unknown_dependency_rejected(self, db_session, task_env) -> None:
        from fde_api.action_execution import task_orchestrator as orch

        payload = _task(task_env["org"].id, task_env["actor"].id, [_node("n1", ("ghost",))])
        dispatch = TaskDispatch()
        with pytest.raises(ActionExecutionError) as exc:
            orch.submit_task(
                actor=task_env["actor"], payload=payload, whitelist_gate=AllowAllWhitelist(), dispatch=dispatch
            )
        _expect_reject(exc, code="validation_failed", status=422)
        assert dispatch.calls == 0
        assert _run_rows_for_key(db_session, payload["idempotency_key"]) == 0

    def test_a3_duplicate_node_key_rejected(self, db_session, task_env) -> None:
        from fde_api.action_execution import task_orchestrator as orch

        payload = _task(task_env["org"].id, task_env["actor"].id, [_node("n1"), _node("n1")])
        dispatch = TaskDispatch()
        with pytest.raises(ActionExecutionError) as exc:
            orch.submit_task(
                actor=task_env["actor"], payload=payload, whitelist_gate=AllowAllWhitelist(), dispatch=dispatch
            )
        _expect_reject(exc, code="validation_failed", status=422)
        assert dispatch.calls == 0

    def test_a4_empty_nodes_rejected(self, db_session, task_env) -> None:
        from fde_api.action_execution import task_orchestrator as orch

        payload = _task(task_env["org"].id, task_env["actor"].id, [])
        dispatch = TaskDispatch()
        with pytest.raises(ActionExecutionError) as exc:
            orch.submit_task(
                actor=task_env["actor"], payload=payload, whitelist_gate=AllowAllWhitelist(), dispatch=dispatch
            )
        _expect_reject(exc, code="validation_failed", status=422)
        assert dispatch.calls == 0

    def test_node_count_over_32_rejected(self, db_session, task_env) -> None:
        from fde_api.action_execution import task_orchestrator as orch

        payload = _task(task_env["org"].id, task_env["actor"].id, [_node(f"n{i:02d}") for i in range(33)])
        dispatch = TaskDispatch()
        with pytest.raises(ActionExecutionError) as exc:
            orch.submit_task(
                actor=task_env["actor"], payload=payload, whitelist_gate=AllowAllWhitelist(), dispatch=dispatch
            )
        _expect_reject(exc, code="validation_failed", status=422)
        assert dispatch.calls == 0

    def test_node_key_domain_violation_rejected(self, db_session, task_env) -> None:
        from fde_api.action_execution import task_orchestrator as orch

        payload = _task(task_env["org"].id, task_env["actor"].id, [_node("_bad_key")])
        dispatch = TaskDispatch()
        with pytest.raises(ActionExecutionError) as exc:
            orch.submit_task(
                actor=task_env["actor"], payload=payload, whitelist_gate=AllowAllWhitelist(), dispatch=dispatch
            )
        _expect_reject(exc, code="validation_failed", status=422)
        assert dispatch.calls == 0

    def test_envelope_unknown_field_rejected(self, db_session, task_env) -> None:
        """信封 additionalProperties 闭集：未知顶层字段 → 422 零副作用。"""
        from fde_api.action_execution import task_orchestrator as orch

        payload = _task(task_env["org"].id, task_env["actor"].id, [_node("n1")])
        payload["tenant_id"] = "self-made-tenant"  # 禁自造租户字段（契约 x-tenant-isolation）
        dispatch = TaskDispatch()
        with pytest.raises(ActionExecutionError) as exc:
            orch.submit_task(
                actor=task_env["actor"], payload=payload, whitelist_gate=AllowAllWhitelist(), dispatch=dispatch
            )
        _expect_reject(exc, code="validation_failed", status=422)
        assert dispatch.calls == 0


# ---- S-AE-07 · S2 节点动作层（A5–A10＋C8；预检映射与闭集） ----------------------


class TestS2NodeAction:
    def test_a5_whitelist_miss_rejected_at_submit_with_connector_id(self, db_session, task_env) -> None:
        """A5：白名单未登记连接器 → 提交期 422（附 details.connector_id），不得派发到运行期。"""
        from fde_api.action_execution import task_orchestrator as orch

        payload = _task(task_env["org"].id, task_env["actor"].id, [_node("n1")])
        dispatch = TaskDispatch()
        with pytest.raises(ActionExecutionError) as exc:
            orch.submit_task(
                actor=task_env["actor"],
                payload=payload,
                whitelist_gate=RejectingWhitelist(),
                dispatch=dispatch,
            )
        _expect_reject(exc, code="validation_failed", status=422)
        assert exc.value.details is not None
        assert exc.value.details.get("connector_id") == "mock.erp"
        assert dispatch.calls == 0
        assert _run_rows_for_key(db_session, payload["idempotency_key"]) == 0

    def test_a6_unregistered_method_rejected_at_submit(self, db_session, task_env) -> None:
        """A6：方法不在白名单登记方法集 → 提交期 422（按方法拒的门桩）。"""
        from fde_api.action_execution import task_orchestrator as orch

        payload = _task(
            task_env["org"].id,
            task_env["actor"].id,
            [_node("n1"), _node("n2", ("n1",), method="destroy_world")],
        )
        dispatch = TaskDispatch()
        with pytest.raises(ActionExecutionError) as exc:
            orch.submit_task(
                actor=task_env["actor"],
                payload=payload,
                whitelist_gate=RejectingWhitelist(reject_methods={"destroy_world"}),
                dispatch=dispatch,
            )
        _expect_reject(exc, code="validation_failed", status=422)
        assert dispatch.calls == 0
        assert _run_rows_for_key(db_session, payload["idempotency_key"]) == 0

    def test_a7_unregistered_action_field_rejected(self, db_session, task_env) -> None:
        from fde_api.action_execution import task_orchestrator as orch

        payload = _task(
            task_env["org"].id,
            task_env["actor"].id,
            [_node("n1", url="https://evil.example")],  # action 内越界字段
        )
        dispatch = TaskDispatch()
        with pytest.raises(ActionExecutionError) as exc:
            orch.submit_task(
                actor=task_env["actor"], payload=payload, whitelist_gate=AllowAllWhitelist(), dispatch=dispatch
            )
        _expect_reject(exc, code="validation_failed", status=422)
        assert dispatch.calls == 0

    def test_a7b_sensitive_key_in_action_fields_not_echoed(self, db_session, task_env) -> None:
        """A7 族纪律③：未登记字段含敏感键名时消息只报「含敏感键名」不回显键名。"""
        from fde_api.action_execution import task_orchestrator as orch

        payload = _task(
            task_env["org"].id,
            task_env["actor"].id,
            [_node("n1", access_token="should-not-appear")],
        )
        dispatch = TaskDispatch()
        with pytest.raises(ActionExecutionError) as exc:
            orch.submit_task(
                actor=task_env["actor"], payload=payload, whitelist_gate=AllowAllWhitelist(), dispatch=dispatch
            )
        _expect_reject(exc, code="validation_failed", status=422)
        assert "should-not-appear" not in str(exc.value)
        assert "access_token" not in str(exc.value)

    def test_a8_param_kind_non_literal_ref_rejected(self, db_session, task_env) -> None:
        from fde_api.action_execution import task_orchestrator as orch

        payload = _task(
            task_env["org"].id,
            task_env["actor"].id,
            [_node("n1", params={"sku": {"kind": "expr", "expr": "1+1"}})],
        )
        dispatch = TaskDispatch()
        with pytest.raises(ActionExecutionError) as exc:
            orch.submit_task(
                actor=task_env["actor"], payload=payload, whitelist_gate=AllowAllWhitelist(), dispatch=dispatch
            )
        _expect_reject(exc, code="validation_failed", status=422)
        assert dispatch.calls == 0

    @pytest.mark.parametrize("ref_node", ["n2", "ghost"])  # 自身／未知（ref 声明在 n2 上）
    def test_a9_ref_to_non_upstream_rejected(self, db_session, task_env, ref_node: str) -> None:
        from fde_api.action_execution import task_orchestrator as orch

        payload = _task(
            task_env["org"].id,
            task_env["actor"].id,
            [_node("n1"), _node("n2", ("n1",), params={"qty": {"kind": "ref", "node": ref_node,
                                                                   "path": "output.available"}})],
        )
        dispatch = TaskDispatch()
        with pytest.raises(ActionExecutionError) as exc:
            orch.submit_task(
                actor=task_env["actor"], payload=payload, whitelist_gate=AllowAllWhitelist(), dispatch=dispatch
            )
        _expect_reject(exc, code="validation_failed", status=422)
        assert dispatch.calls == 0

    def test_a9b_ref_to_downstream_node_rejected(self, db_session, task_env) -> None:
        """A9 下游腿：n1（无依赖）引用 n2（下游）——引用必须指向已定义的上游。"""
        from fde_api.action_execution import task_orchestrator as orch

        payload = _task(
            task_env["org"].id,
            task_env["actor"].id,
            [_node("n1", params={"qty": {"kind": "ref", "node": "n2", "path": "output.available"}}),
             _node("n2")],
        )
        dispatch = TaskDispatch()
        with pytest.raises(ActionExecutionError) as exc:
            orch.submit_task(
                actor=task_env["actor"], payload=payload, whitelist_gate=AllowAllWhitelist(), dispatch=dispatch
            )
        _expect_reject(exc, code="validation_failed", status=422)
        assert dispatch.calls == 0

    @pytest.mark.parametrize("path", ["audit.trace_id", "error.code", "params.sku", "output..x"])
    def test_a10_ref_path_outside_output_scope_rejected(self, db_session, task_env, path: str) -> None:
        """A10：ref.path 越出 output 作用域（越权读审计/错误/参数面零暴露）。"""
        from fde_api.action_execution import task_orchestrator as orch

        payload = _task(
            task_env["org"].id,
            task_env["actor"].id,
            [_node("n1"), _node("n2", ("n1",), params={"qty": {"kind": "ref", "node": "n1", "path": path}})],
        )
        dispatch = TaskDispatch()
        with pytest.raises(ActionExecutionError) as exc:
            orch.submit_task(
                actor=task_env["actor"], payload=payload, whitelist_gate=AllowAllWhitelist(), dispatch=dispatch
            )
        _expect_reject(exc, code="validation_failed", status=422)
        assert dispatch.calls == 0

    def test_c8_sensitive_param_key_rejected(self, db_session, task_env) -> None:
        """C8（七键同源扫描）：params 键名命中敏感集 → 422 sensitive_argument_forbidden。"""
        from fde_api.action_execution import task_orchestrator as orch

        payload = _task(
            task_env["org"].id,
            task_env["actor"].id,
            [_node("n1", params={"api_key": {"kind": "literal", "value": "secret"}})],
        )
        dispatch = TaskDispatch()
        with pytest.raises(ActionExecutionError) as exc:
            orch.submit_task(
                actor=task_env["actor"], payload=payload, whitelist_gate=AllowAllWhitelist(), dispatch=dispatch
            )
        _expect_reject(exc, code="sensitive_argument_forbidden", status=422)
        assert dispatch.calls == 0
        assert _run_rows_for_key(db_session, payload["idempotency_key"]) == 0


# ---- S3/S4 · 租户绑定与能力档位 ------------------------------------------------


class TestTenantAndCapability:
    def test_c1_org_mismatch_is_404_not_found(self, db_session, task_env) -> None:
        from fde_api.action_execution import task_orchestrator as orch

        payload = _task(task_env["org_b"].id, task_env["actor"].id, [_node("n1")])  # org 与发起人不一致
        dispatch = TaskDispatch()
        with pytest.raises(ActionExecutionError) as exc:
            orch.submit_task(
                actor=task_env["actor"], payload=payload, whitelist_gate=AllowAllWhitelist(), dispatch=dispatch
            )
        _expect_reject(exc, code="not_found", status=404)
        assert dispatch.calls == 0
        assert _run_rows_for_key(db_session, payload["idempotency_key"]) == 0

    def test_c5_viewer_submit_is_403_permission_revoked(self, db_session, task_env) -> None:
        from fde_api.action_execution import task_orchestrator as orch

        payload = _task(task_env["org"].id, task_env["viewer"].id, [_node("n1")])
        dispatch = TaskDispatch()
        with pytest.raises(ActionExecutionError) as exc:
            orch.submit_task(
                actor=task_env["viewer"], payload=payload, whitelist_gate=AllowAllWhitelist(), dispatch=dispatch
            )
        _expect_reject(exc, code="permission_revoked", status=403)
        assert dispatch.calls == 0
        assert _run_rows_for_key(db_session, payload["idempotency_key"]) == 0


# ---- S5 · 运行级幂等（B7/B8/B9）＋ 节点级派生（B10） ---------------------------


class TestRunIdempotency:
    def test_b7_same_key_same_body_replays_verbatim(self, db_session, task_env) -> None:
        """B7：同键同体重提交 → 快照逐字一致（节点执行 ID 不新分配），外呼零增。"""
        from fde_api.action_execution import task_orchestrator as orch

        payload = _task(
            task_env["org"].id,
            task_env["actor"].id,
            [_node("n1"), _node("n2", ("n1",))],
        )
        dispatch = TaskDispatch()
        first = orch.submit_task(
            actor=task_env["actor"], payload=payload, whitelist_gate=AllowAllWhitelist(), dispatch=dispatch
        )
        calls_after_first = dispatch.calls
        assert first["status"] == "succeeded"
        replay = orch.submit_task(
            actor=task_env["actor"], payload=payload, whitelist_gate=AllowAllWhitelist(), dispatch=dispatch
        )
        assert replay == first  # 逐字一致（含 nodes/output/execution_id）
        assert dispatch.calls == calls_after_first  # 零重复外呼

    def test_b8_same_key_different_body_is_409_mismatch(self, db_session, task_env) -> None:
        from fde_api.action_execution import task_orchestrator as orch

        payload = _task(task_env["org"].id, task_env["actor"].id, [_node("n1")])
        dispatch = TaskDispatch()
        orch.submit_task(
            actor=task_env["actor"], payload=payload, whitelist_gate=AllowAllWhitelist(), dispatch=dispatch
        )
        calls_after_first = dispatch.calls
        drifted = _task(
            task_env["org"].id,
            task_env["actor"].id,
            [_node("n1", params={"sku": {"kind": "literal", "value": "SKU-DRIFT"}})],
            key=payload["idempotency_key"],
        )
        with pytest.raises(ActionExecutionError) as exc:
            orch.submit_task(
                actor=task_env["actor"], payload=drifted, whitelist_gate=AllowAllWhitelist(), dispatch=dispatch
            )
        _expect_reject(exc, code="idempotency_mismatch", status=409)
        assert dispatch.calls == calls_after_first  # 零副作用

    def test_b9_concurrent_same_key_executes_exactly_once(self, app, db_session, task_env) -> None:
        """B9：真线程并发同键同体——恰一次真执行（外呼 == 单次运行节点数），
        败者 409 in_flight 或复放通道（真 UNIQUE 约束裁决，非 monkeypatch 时间窗）。
        每线程推 app context＋线程内 fresh actor（``db.session`` 绑 current_app）。"""
        from fde_api.action_execution import task_orchestrator as orch
        from fde_api.auth.models import User
        from fde_api.extensions import db

        payload = _task(task_env["org"].id, task_env["actor"].id, [_node("n1"), _node("n2", ("n1",))])
        dispatch = TaskDispatch(delay=0.2)
        barrier = threading.Barrier(2, timeout=20)
        outcomes: list[Any] = []

        def runner() -> None:
            with app.app_context():
                session = db.session()
                try:
                    actor = session.get(User, task_env["actor"].id)
                    assert actor is not None
                    barrier.wait()
                    outcomes.append(
                        orch.submit_task(
                            actor=actor,
                            payload=payload,
                            whitelist_gate=AllowAllWhitelist(),
                            dispatch=dispatch,
                        )
                    )
                except ActionExecutionError as exc:
                    outcomes.append(exc)
                except Exception as error:  # noqa: BLE001 - 线程内异常回传主线程断言
                    outcomes.append(error)
                finally:
                    session.close()

        threads = [threading.Thread(target=runner) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=30)
            assert not thread.is_alive(), "并发线程未按时结束"

        unexpected = [o for o in outcomes if isinstance(o, Exception) and not isinstance(o, ActionExecutionError)]
        assert not unexpected, f"线程内意外异常：{unexpected!r}"
        succeeded = [o for o in outcomes if isinstance(o, dict)]
        rejected = [o for o in outcomes if isinstance(o, ActionExecutionError)]
        assert len(outcomes) == 2
        assert len(succeeded) >= 1  # 恰一次真执行产出一个终态快照
        assert dispatch.calls == 2  # 两节点各一次——零重复副作用
        run_ids = {o["execution_id"] for o in succeeded}
        assert len(run_ids) == 1
        for exc in rejected:
            # 败者：in_flight（在途撞锁）或复放（赢家已终态后到达）
            assert exc.code in ("idempotency_in_flight",), f"败者错误码意外：{exc.code}"
            assert exc.status == 409

    def test_b10_node_key_derivation_is_deterministic_and_contract_shaped(self) -> None:
        """B10：节点幂等键派生确定（同键同动作同键；动作漂移即变）＋契约形态钉死。"""
        import hashlib
        import json

        from fde_api.action_execution import task_orchestrator as orch

        action = _node("n1")["action"]
        first = orch.node_idempotency_key("run-key-1", "n1", action)
        assert first == orch.node_idempotency_key("run-key-1", "n1", dict(action))  # 确定性
        assert first != orch.node_idempotency_key("run-key-2", "n1", action)  # 运行键参与
        assert first != orch.node_idempotency_key("run-key-1", "n2", action)  # 节点键参与
        drifted = {**action, "params": {"sku": {"kind": "literal", "value": "OTHER"}}}
        assert first != orch.node_idempotency_key("run-key-1", "n1", drifted)  # 动作体参与
        # 契约派生式逐字钉：ae2- + sha256(run_key|node_key|canonical(action)) 前 32 hex
        canonical = json.dumps(action, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        expected = "ae2-" + hashlib.sha256(f"run-key-1|n1|{canonical}".encode("utf-8")).hexdigest()[:32]
        assert first == expected
        assert len(first) == 36 and first.startswith("ae2-")


# ---- 运行期 · 拓扑就绪 / 引用求值 / fail-fast（B1） ----------------------------


class TestRuntimeExecution:
    def test_diamond_executes_in_lexicographic_stable_topo_order(self, db_session, task_env) -> None:
        """拓扑就绪：菱形图 a→(b,c)→d 按字典序稳定拓扑序派发；全部成功 → succeeded。"""
        from fde_api.action_execution import task_orchestrator as orch

        payload = _task(
            task_env["org"].id,
            task_env["actor"].id,
            [_node("d", ("b", "c")), _node("c", ("a",)), _node("b", ("a",)), _node("a")],
        )
        dispatch = TaskDispatch()
        result = orch.submit_task(
            actor=task_env["actor"], payload=payload, whitelist_gate=AllowAllWhitelist(), dispatch=dispatch
        )
        assert result["status"] == "succeeded"
        assert result["error"] is None
        assert dispatch.calls == 4
        assert [req["action_id"] for req in dispatch.seen] == [
            "mock.erp.a",
            "mock.erp.b",
            "mock.erp.c",
            "mock.erp.d",
        ]
        node_keys = [n["node_key"] for n in result["nodes"]]
        assert node_keys == ["a", "b", "c", "d"]  # 结果序列＝拓扑序（确定性）

    def test_ref_resolution_literal_and_ref_paths(self, db_session, task_env) -> None:
        """⑤ 入参求值：literal 保型透传；ref 按 output 路径求值（含下标段）。"""
        from fde_api.action_execution import task_orchestrator as orch

        payload = _task(
            task_env["org"].id,
            task_env["actor"].id,
            [
                _node("n1"),
                _node(
                    "n2",
                    ("n1",),
                    params={
                        "count": {"kind": "ref", "node": "n1", "path": "output.stock.items[0].sku"},
                        "limit": {"kind": "literal", "value": 42},
                    },
                ),
            ],
        )
        # n1 的**产物**（dispatch 返回值）承载被引用结构——ref 读上游 output
        dispatch = TaskDispatch(outputs={"mock.erp.n1": {"stock": {"items": [{"sku": "X1"}]}}})
        result = orch.submit_task(
            actor=task_env["actor"], payload=payload, whitelist_gate=AllowAllWhitelist(), dispatch=dispatch
        )
        assert result["status"] == "succeeded"
        resolved = dispatch.seen[1]["params"]
        assert resolved == {"count": "X1", "limit": 42}  # ref 求值＋literal 保型（不字符串化）

    def test_ref_missing_output_key_fails_node_honestly(self, db_session, task_env) -> None:
        """运行期引用缺键 → 该节点 failed（不填空串不猜），上游补偿、运行收口。"""
        from fde_api.action_execution import task_orchestrator as orch

        payload = _task(
            task_env["org"].id,
            task_env["actor"].id,
            [
                _node("n1"),  # 产物 {"available": 3, ...}——无 echo 键
                _node("n2", ("n1",), params={"e": {"kind": "ref", "node": "n1", "path": "output.echo"}}),
            ],
        )
        dispatch = TaskDispatch()
        result = orch.submit_task(
            actor=task_env["actor"],
            payload=payload,
            whitelist_gate=AllowAllWhitelist(),
            dispatch=dispatch,
            compensator=_AlwaysCompensator(),
        )
        n2 = next(n for n in result["nodes"] if n["node_key"] == "n2")
        assert n2["status"] == "failed"
        assert n2["error"] is not None and n2["error"]["code"] == "validation_failed"
        assert result["status"] == "rolled_back"  # n1 已补偿（补偿面详见 compensation 测试件）

    def test_b1_upstream_failure_fail_fast_skips_downstream(self, db_session, task_env) -> None:
        """B1：首节点失败 → fail-fast：下游 skipped（error=null）、零派发、运行 error 非 null。"""
        from fde_api.action_execution import task_orchestrator as orch

        payload = _task(
            task_env["org"].id,
            task_env["actor"].id,
            [_node("n1"), _node("n2", ("n1",)), _node("n3", ("n2",))],
        )
        dispatch = TaskDispatch(fail_action_ids={"mock.erp.n1"})
        result = orch.submit_task(
            actor=task_env["actor"], payload=payload, whitelist_gate=AllowAllWhitelist(), dispatch=dispatch
        )
        assert result["status"] == "failed"  # 零可补偿节点 → failed 终态（诚实失败）
        assert result["error"] is not None
        assert result["error"]["details"]["skipped_nodes"] == ["n2", "n3"]
        assert dispatch.calls == 1  # 下游零派发
        by_key = {n["node_key"]: n for n in result["nodes"]}
        assert by_key["n1"]["status"] == "failed"
        assert by_key["n2"]["status"] == "skipped" and by_key["n2"]["error"] is None
        assert by_key["n3"]["status"] == "skipped" and by_key["n3"]["error"] is None

    def test_mid_failure_dispatch_infra_maps_to_closed_set_code(self, db_session, task_env) -> None:
        """派发段真异常 → service 兜底映射闭集内码（Q8）：节点 failed＋details.reason。"""
        from fde_api.action_execution import task_orchestrator as orch

        payload = _task(
            task_env["org"].id,
            task_env["actor"].id,
            [_node("n1"), _node("n2", ("n1",))],
        )
        dispatch = TaskDispatch(fail_action_ids={"mock.erp.n2"})
        result = orch.submit_task(
            actor=task_env["actor"],
            payload=payload,
            whitelist_gate=AllowAllWhitelist(),
            dispatch=dispatch,
            compensator=_AlwaysCompensator(),
        )
        n2 = next(n for n in result["nodes"] if n["node_key"] == "n2")
        assert n2["status"] == "failed"
        assert n2["error"] is not None
        assert n2["error"]["code"] == "tool_not_allowed"  # 闭集内映射（不扩闭集）
        assert n2["error"]["details"] == {"reason": "RuntimeError"}

    def test_node_rows_persist_state_and_digests(self, db_session, task_env) -> None:
        """节点行落库：依赖快照＋节点幂等键＋params 指纹＋action_execution_id 指向 AE1 行。"""
        from sqlalchemy import select

        from fde_api.action_execution import task_orchestrator as orch
        from fde_api.action_execution.models import ActionTaskNode, ActionTaskRun

        payload = _task(task_env["org"].id, task_env["actor"].id, [_node("n1"), _node("n2", ("n1",))])
        dispatch = TaskDispatch()
        result = orch.submit_task(
            actor=task_env["actor"], payload=payload, whitelist_gate=AllowAllWhitelist(), dispatch=dispatch
        )
        run_id = result["execution_id"]
        node_rows = db_session.scalars(
            select(ActionTaskNode).where(ActionTaskNode.run_id == run_id).order_by(ActionTaskNode.node_key)
        ).all()
        assert [row.node_key for row in node_rows] == ["n1", "n2"]
        n2_row = node_rows[1]
        assert n2_row.depends_on_json == ["n1"]  # 依赖快照逐字落库
        assert n2_row.status == "succeeded" and n2_row.attempt == 1
        assert n2_row.action_execution_id  # 指向 AE1 执行行
        assert len(n2_row.node_idempotency_key) == 36
        assert len(n2_row.params_sha256) == 64
        run_row = db_session.scalar(select(ActionTaskRun).where(ActionTaskRun.id == run_id))
        assert run_row is not None and run_row.status == "succeeded"
        assert len(run_row.definition_sha256) == 64  # 运行行只留指纹（零明文）
        assert run_row.node_count == 2


class _AlwaysCompensator:
    """补偿桩：一律 succeeded（供运行期失败腿的收口断言；详见 compensation 测试件）。"""

    def __init__(self) -> None:
        self.targets: list[str] = []

    def compensate(self, record: dict[str, Any]) -> dict[str, Any]:
        self.targets.append(record["target"])
        return {
            "compensation_id": f"c-{len(self.targets)}",
            "kind": record["kind"],
            "target": record["target"],
            "status": "succeeded",
            "detail": {},
        }
