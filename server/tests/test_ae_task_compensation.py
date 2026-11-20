"""AE2-WP3：编排补偿面（54 号 v0.2-ACTIVE §3；编排契约 x-compensation / x-failure-propagation）。

S-AE-08 补偿族（B2–B6/B11）：逆拓扑序补偿（后继先补偿）、逐条登记、
部分失败诚实残留（不得报 rolled_back）、not_supported/noop 不计残留但运行
不得报 succeeded、重复补偿幂等（沿 U1 ``action_compensations`` 一行一批次）。

补偿实现复用 AE1 ``rollback_action``（D3 拍板：逆序补偿复用单步回滚面）——
节点补偿四态与批次登记语义全部继承单步面既有钉（``test_ae_rollback.py``）。

观测锚：AE1 回滚批次条目 ``kind``＝``rollback_<method>``——各节点配不同
method 即可按 kind 断言补偿调用序与注入失败（target 含指纹后缀不可区分）。
"""
from __future__ import annotations

import threading
from typing import Any
from uuid import uuid4

import pytest

from fde_api.action_execution.errors import ActionExecutionError
from multi_tenant_harness import make_enterprise_org, make_user

# 菱形图各节点 method（kind＝rollback_<method>；字母开头下划线）
M_A = "query_inventory"
M_B = "create_order"
M_C = "update_order"
M_D = "send_receipt"


class AllowAllWhitelist:
    def check(self, connector_id: str, method: str) -> None:
        return None


class TaskDispatch:
    def __init__(self, *, fail_action_ids: set[str] | None = None) -> None:
        self._lock = threading.Lock()
        self.calls = 0
        self.fail_action_ids = fail_action_ids or set()

    def call(self, request: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            self.calls += 1
        if request["action_id"] in self.fail_action_ids:
            raise RuntimeError("dispatch exploded")
        return {"available": 3, "quantity": 1}


class TaskCompensator:
    """补偿桩：按 kind 登记补偿调用序（逆序补偿钉的观测面）；可按 kind 注入失败。"""

    def __init__(self, *, fail_kinds: set[str] | None = None) -> None:
        self._lock = threading.Lock()
        self.kinds: list[str] = []
        self.fail_kinds = fail_kinds or set()

    def compensate(self, record: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            self.kinds.append(record["kind"])
            index = len(self.kinds)
        status = "failed" if record["kind"] in self.fail_kinds else "succeeded"
        return {
            "compensation_id": f"c-{index}",
            "kind": record["kind"],
            "target": record["target"],
            "status": status,
            "detail": {},
        }


@pytest.fixture
def comp_env(db_session):
    org = make_enterprise_org(db_session)
    actor = make_user(db_session, "project_lead", org_id=org.id)
    org_b = make_enterprise_org(db_session)
    actor_b = make_user(db_session, "project_lead", org_id=org_b.id)
    db_session.commit()
    return {"org": org, "actor": actor, "org_b": org_b, "actor_b": actor_b}


def _node(key: str, depends: tuple[str, ...] = (), *, method: str, rollback: bool = True,
          dry_run: bool = False) -> dict[str, Any]:
    return {
        "node_key": key,
        "depends_on": list(depends),
        "action": {
            "action_id": f"mock.erp.{key}",
            "connector_id": "mock.erp",
            "method": method,
            "params": {"sku": {"kind": "literal", "value": f"SKU-{key}"}},
            "dry_run": dry_run,
            "risk_level": 1,
            "timeout_seconds": 30,
        },
        "rollback_supported": rollback,
    }


def _linear(task_id: str, org_id: str, requester_id: str) -> dict[str, Any]:
    """线性三节点 n1→n2→n3（各节点不同 method）。"""
    return {
        "org_id": org_id,
        "requester_id": requester_id,
        "idempotency_key": f"ae2-comp-{task_id}",
        "definition": {
            "nodes": [
                _node("n1", method=M_A),
                _node("n2", ("n1",), method=M_B),
                _node("n3", ("n2",), method=M_C),
            ]
        },
    }


def _diamond(org_id: str, requester_id: str) -> dict[str, Any]:
    """菱形四节点 a→(b,c)→d（各节点不同 method；d 处注入派发失败）。"""
    return {
        "org_id": org_id,
        "requester_id": requester_id,
        "idempotency_key": "ae2-comp-" + uuid4().hex[:10],
        "definition": {
            "nodes": [
                _node("d", ("b", "c"), method=M_D),
                _node("c", ("a",), method=M_C),
                _node("b", ("a",), method=M_B),
                _node("a", method=M_A),
            ]
        },
    }


def _by_key(result: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {n["node_key"]: n for n in result["nodes"]}


# ---- B2 · 中间节点失败 → 逆序补偿 ----------------------------------------------


class TestB2ReverseCompensation:
    def test_mid_failure_compensates_upstream_with_batch_registered(self, db_session, comp_env) -> None:
        """B2：中间节点失败 → 已成功上游被补偿；补偿条目逐条登记；下游 skipped。"""
        from fde_api.action_execution import service as ae_service
        from fde_api.action_execution import task_orchestrator as orch

        payload = _linear("b2", comp_env["org"].id, comp_env["actor"].id)
        dispatch = TaskDispatch(fail_action_ids={"mock.erp.n2"})
        compensator = TaskCompensator()
        result = orch.submit_task(
            actor=comp_env["actor"],
            payload=payload,
            whitelist_gate=AllowAllWhitelist(),
            dispatch=dispatch,
            compensator=compensator,
        )
        assert result["status"] == "rolled_back"
        assert result["error"] is None  # 补偿全成功 → error null（B4 同源）
        nodes = _by_key(result)
        assert nodes["n3"]["status"] == "skipped"
        assert nodes["n1"]["compensation_status"] == "rolled_back"
        assert compensator.kinds == [f"rollback_{M_A}"]  # 仅 n1 可补偿
        summary = result["rollback"]
        assert summary is not None
        assert summary["status"] == "rolled_back"
        assert summary["residual"] == []
        assert summary["compensated_nodes"] == ["n1"]
        # 补偿条目逐条登记（U1 一行一批次：n1 的 AE1 回滚批次在场）
        batch = ae_service.get_rollback_batch(nodes["n1"]["action_execution_id"])
        assert batch is not None
        assert batch["status"] == "rolled_back"
        assert len(batch["compensations"]) == 1

    def test_diamond_failure_compensates_in_reverse_topo_order(self, db_session, comp_env) -> None:
        """补偿顺序＝逆拓扑序（后继先补偿）：菱形在 d 失败 → 补偿序 [c, b, a]。"""
        from fde_api.action_execution import task_orchestrator as orch

        payload = _diamond(comp_env["org"].id, comp_env["actor"].id)
        dispatch = TaskDispatch(fail_action_ids={"mock.erp.d"})
        compensator = TaskCompensator()
        result = orch.submit_task(
            actor=comp_env["actor"],
            payload=payload,
            whitelist_gate=AllowAllWhitelist(),
            dispatch=dispatch,
            compensator=compensator,
        )
        assert result["status"] == "rolled_back"
        # 逆拓扑序：d(failed, 不补偿) → c → b → a
        assert compensator.kinds == [f"rollback_{M_C}", f"rollback_{M_B}", f"rollback_{M_A}"]
        summary = result["rollback"]
        assert summary is not None
        assert sorted(summary["compensated_nodes"]) == ["a", "b", "c"]
        assert summary["residual"] == []


# ---- B3 · 补偿部分失败 → 诚实残留 ----------------------------------------------


class TestB3Residual:
    def test_partial_compensation_failure_is_honest(self, db_session, comp_env) -> None:
        """B3：某节点补偿 failed → 运行 compensation_failed＋details.compensation_ids
        ＋残留逐条登记；不得报 rolled_back；其余补偿照常推进。"""
        from fde_api.action_execution import task_orchestrator as orch

        payload = _diamond(comp_env["org"].id, comp_env["actor"].id)
        dispatch = TaskDispatch(fail_action_ids={"mock.erp.d"})
        compensator = TaskCompensator(fail_kinds={f"rollback_{M_B}"})  # 节点 b 补偿失败
        result = orch.submit_task(
            actor=comp_env["actor"],
            payload=payload,
            whitelist_gate=AllowAllWhitelist(),
            dispatch=dispatch,
            compensator=compensator,
        )
        assert result["status"] == "compensation_failed"
        assert result["error"] is not None
        assert result["error"]["code"] == "compensation_failed"
        assert result["error"]["details"]["compensation_ids"]  # 失败条目 id 非空
        summary = result["rollback"]
        assert summary is not None
        assert summary["status"] == "failed"
        assert summary["residual"] == ["b"]  # 残留逐条登记
        assert sorted(summary["compensated_nodes"]) == ["a", "c"]  # 其余补偿照常推进
        nodes = _by_key(result)
        assert nodes["b"]["compensation_status"] == "failed"
        assert nodes["a"]["compensation_status"] == "rolled_back"
        assert nodes["c"]["compensation_status"] == "rolled_back"


# ---- B4/B5/B6 · 补偿四态 honest 登记 --------------------------------------------


class TestCompensationOutcomes:
    def test_b5_not_supported_not_residual_and_run_not_succeeded(self, db_session, comp_env) -> None:
        """B5：节点 rollback_supported=false → not_supported 不计残留；运行不得报 succeeded。"""
        from fde_api.action_execution import task_orchestrator as orch

        payload = _linear("b5", comp_env["org"].id, comp_env["actor"].id)
        payload["definition"]["nodes"][0]["rollback_supported"] = False
        dispatch = TaskDispatch(fail_action_ids={"mock.erp.n2"})
        compensator = TaskCompensator()
        result = orch.submit_task(
            actor=comp_env["actor"],
            payload=payload,
            whitelist_gate=AllowAllWhitelist(),
            dispatch=dispatch,
            compensator=compensator,
        )
        nodes = _by_key(result)
        assert nodes["n1"]["compensation_status"] == "not_supported"
        assert result["status"] != "succeeded"  # 诚实：不得报成功
        assert result["status"] == "rolled_back"  # 补偿过程无失败 → 状态机 rolled_back
        summary = result["rollback"]
        assert summary is not None
        assert summary["residual"] == []  # not_supported 不计入残留
        assert summary["compensated_nodes"] == []
        assert compensator.kinds == []  # not_supported 由单步面判定，补偿器未被调用

    def test_b6_dry_run_node_compensation_is_noop(self, db_session, comp_env) -> None:
        """B6：零副作用节点（干跑）补偿 → noop 不计残留；运行不得报 succeeded。"""
        from fde_api.action_execution import task_orchestrator as orch

        payload = _linear("b6", comp_env["org"].id, comp_env["actor"].id)
        payload["definition"]["nodes"][0]["action"]["dry_run"] = True
        dispatch = TaskDispatch(fail_action_ids={"mock.erp.n2"})
        compensator = TaskCompensator()
        result = orch.submit_task(
            actor=comp_env["actor"],
            payload=payload,
            whitelist_gate=AllowAllWhitelist(),
            dispatch=dispatch,
            compensator=compensator,
        )
        nodes = _by_key(result)
        assert nodes["n1"]["compensation_status"] == "noop"
        assert result["status"] != "succeeded"
        summary = result["rollback"]
        assert summary is not None
        assert summary["residual"] == []
        assert summary["compensated_nodes"] == []


# ---- B11 · 重复补偿幂等 --------------------------------------------------------


class TestCompensationIdempotency:
    def test_b11_repeat_compensation_reuses_state_zero_new_side_effects(
        self, db_session, comp_env
    ) -> None:
        """B11：对同一运行再请求回滚 → 条目数与各条 status 不变，补偿副作用计数不增。"""
        from fde_api.action_execution import task_orchestrator as orch

        payload = _linear("b11", comp_env["org"].id, comp_env["actor"].id)
        dispatch = TaskDispatch(fail_action_ids={"mock.erp.n2"})
        compensator = TaskCompensator()
        first = orch.submit_task(
            actor=comp_env["actor"],
            payload=payload,
            whitelist_gate=AllowAllWhitelist(),
            dispatch=dispatch,
            compensator=compensator,
        )
        assert first["status"] == "rolled_back"
        kinds_after_first = list(compensator.kinds)
        dispatch_calls_after_first = dispatch.calls

        again = orch.compensate_task(
            actor=comp_env["actor"], execution_id=first["execution_id"], compensator=compensator
        )
        assert again == first  # 快照逐字一致（节点结果/补偿登记零漂移）
        assert compensator.kinds == kinds_after_first  # 零新补偿副作用
        assert dispatch.calls == dispatch_calls_after_first  # 零新外呼

    def test_compensate_task_cross_tenant_is_404(self, db_session, comp_env) -> None:
        from fde_api.action_execution import task_orchestrator as orch

        payload = _linear("xt", comp_env["org"].id, comp_env["actor"].id)
        dispatch = TaskDispatch(fail_action_ids={"mock.erp.n2"})
        result = orch.submit_task(
            actor=comp_env["actor"],
            payload=payload,
            whitelist_gate=AllowAllWhitelist(),
            dispatch=dispatch,
            compensator=TaskCompensator(),
        )
        with pytest.raises(ActionExecutionError) as exc:
            orch.compensate_task(actor=comp_env["actor_b"], execution_id=result["execution_id"])
        assert exc.value.code == "not_found"
        assert exc.value.status == 404

    def test_compensate_task_on_succeeded_run_is_rejected_by_state_machine(
        self, db_session, comp_env
    ) -> None:
        """状态机不含 succeeded→compensating 边：对成功运行触发回滚 → 422 拒绝。"""
        from fde_api.action_execution import task_orchestrator as orch

        payload = _linear("ok", comp_env["org"].id, comp_env["actor"].id)
        result = orch.submit_task(
            actor=comp_env["actor"],
            payload=payload,
            whitelist_gate=AllowAllWhitelist(),
            dispatch=TaskDispatch(),
            compensator=TaskCompensator(),
        )
        assert result["status"] == "succeeded"
        with pytest.raises(ActionExecutionError) as exc:
            orch.compensate_task(actor=comp_env["actor"], execution_id=result["execution_id"])
        assert exc.value.code == "validation_failed"
        assert exc.value.status == 422
