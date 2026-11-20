"""AE1-WP2：幂等三态端到端（53 号 §3 WP2；U1 ``x-idempotency``；U2 S-AE-02 九断言）。

WP1 已落幂等门（``_DbIdempotencyGate``：同键异体 409 / 在途 409 / 终态复放）
与 ``UNIQUE(org_id, idempotency_key)`` 约束；WP2 增量＝**在途锁**（dispatch 前
落 ``awaiting_approval`` 锁行占唯一约束——并发败者在零副作用窗口即被 409，
对齐 U2 A9「副作用计数 == 1」与契约 ``scope_limit``）＋ IntegrityError 败者
重读（先例 ``agents/service.py:649-664``）。

钉名对齐 U2 §2.6 七钉；A6/A9 展开为独立钉；A5 参数化覆盖 U1 十语义字段
（超出 U2 八字段下限——``coverage_rule`` 漏字段＝静默复放教训）。

断言口径（U2 A1 与 T4-003 冻结断言的调和）：复放响应**载荷逐字复现首次**
（output/audit/cost 三腿逐字），``status`` 字段按契约五态＝``replayed``（U2
A2 单列），``execution_id`` 不新分配（A3）。
"""
from __future__ import annotations

import json
from typing import Any
from uuid import uuid4

import pytest

from multi_tenant_harness import make_enterprise_org, make_project, make_user


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _request(**overrides) -> dict[str, Any]:
    req: dict[str, Any] = {
        "action_id": "mock.email.send",
        "action_type": "send_email",
        "connector_id": "mock.email",
        "method": "send",
        "params": {"to": "ops@example.test", "subject": "s-1", "body": "b-1"},
        "idempotency_key": "idem-wp2-" + uuid4().hex[:8],
        "org_id": "pending",
        "requester_id": "pending",
        "dry_run": False,
        "risk_level": 2,
        "timeout_seconds": 30,
        "approval_id": None,
    }
    req.update(overrides)
    return req


@pytest.fixture
def ae_world(db_session):
    org = make_enterprise_org(db_session)
    actor = make_user(db_session, "project_lead", org_id=org.id)
    org_b = make_enterprise_org(db_session)
    actor_b = make_user(db_session, "project_lead", org_id=org_b.id)
    project = make_project(db_session, actor, code=f"AEI{uuid4().hex[:6]}", org_id=org.id)
    db_session.commit()
    return {"org": org, "actor": actor, "org_b": org_b, "actor_b": actor_b, "project": project}


class RecordingDispatch:
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


class TestIdempotencyEndToEnd:
    def test_same_key_same_body_replays_original_response(self, db_session, ae_world) -> None:
        """S-AE-02 A1/A2/A3：同键同体三连发——载荷逐字复现首次、status=replayed、
        replayed_from 指向首次、execution_id 不新分配、副作用计数 == 1。"""
        from fde_api.action_execution import service as svc

        payload = _request(org_id=ae_world["org"].id, requester_id=ae_world["actor"].id)
        dispatch = RecordingDispatch({"message_id": "m-first", "delivered_count": 1})

        first = svc.submit_action(
            actor=ae_world["actor"], payload=payload, whitelist_gate=AllowAllWhitelist(), dispatch=dispatch
        )
        r2 = svc.submit_action(
            actor=ae_world["actor"], payload=payload, whitelist_gate=AllowAllWhitelist(), dispatch=dispatch
        )
        r3 = svc.submit_action(
            actor=ae_world["actor"], payload=payload, whitelist_gate=AllowAllWhitelist(), dispatch=dispatch
        )

        assert first["status"] == "succeeded"
        for replay in (r2, r3):
            assert replay["status"] == "replayed"  # A2
            assert replay["replayed_from_execution_id"] == first["execution_id"]  # A2
            assert replay["execution_id"] == first["execution_id"]  # A3 复放不新分配 ID
            assert replay["output"] == first["output"]  # A1 载荷逐字复现
            assert replay["audit"] == first["audit"]
            assert replay["cost"] == first["cost"]
        assert dispatch.calls == 1  # A1 副作用仅一次

    def test_same_key_different_body_returns_409(self, db_session, ae_world) -> None:
        """S-AE-02 A4：同键异体 → 409 idempotency_mismatch，副作用计数仍 == 1。"""
        from fde_api.action_execution import service as svc
        from fde_api.action_execution.errors import ActionExecutionError

        payload = _request(org_id=ae_world["org"].id, requester_id=ae_world["actor"].id)
        dispatch = RecordingDispatch()
        svc.submit_action(actor=ae_world["actor"], payload=payload, whitelist_gate=AllowAllWhitelist(), dispatch=dispatch)
        assert dispatch.calls == 1

        drifted = _request(params={"to": "other@example.test"}, org_id=ae_world["org"].id, requester_id=ae_world["actor"].id)
        drifted["idempotency_key"] = payload["idempotency_key"]
        with pytest.raises(ActionExecutionError) as err:
            svc.submit_action(actor=ae_world["actor"], payload=drifted, whitelist_gate=AllowAllWhitelist(), dispatch=dispatch)
        assert err.value.code == "idempotency_mismatch"
        assert err.value.status == 409
        assert dispatch.calls == 1

    def test_idempotency_fingerprint_covers_all_semantic_fields(self, db_session, ae_world) -> None:
        """S-AE-02 A5（超集口径）：异体比较覆盖 U1 全部 10 语义字段——逐一改动均 409。"""
        from fde_api.action_execution import service as svc
        from fde_api.action_execution.errors import ActionExecutionError
        from fde_api.action_execution.executor import FINGERPRINT_FIELDS

        payload = _request(org_id=ae_world["org"].id, requester_id=ae_world["actor"].id)
        dispatch = RecordingDispatch()
        svc.submit_action(actor=ae_world["actor"], payload=payload, whitelist_gate=AllowAllWhitelist(), dispatch=dispatch)
        baseline_calls = dispatch.calls

        for field in FINGERPRINT_FIELDS:  # 10 字段逐一异体
            drifted = json.loads(_canonical(payload))
            if field == "params":
                drifted[field] = {"to": "x@y.test", "subject": "s-1", "body": "b-1", "extra": 1}
            elif field == "action_type":
                # L1 先于 L2（U1 x-validation-order）：drift 须为合法蛇形值，
                # 否则 422 挡在 L1、指纹比较不可达
                drifted[field] = "update_status"
            elif isinstance(payload.get(field), bool):
                drifted[field] = not payload[field]
            elif isinstance(payload.get(field), int):
                drifted[field] = payload[field] + 1
            elif field == "approval_id":
                drifted[field] = None if payload.get("approval_id") else "ap-x"
            else:
                drifted[field] = f"{payload.get(field)}-drift"
            drifted["idempotency_key"] = payload["idempotency_key"]
            with pytest.raises(ActionExecutionError) as err:
                svc.submit_action(
                    actor=ae_world["actor"], payload=drifted, whitelist_gate=AllowAllWhitelist(), dispatch=dispatch
                )
            assert err.value.code == "idempotency_mismatch", field
        assert dispatch.calls == baseline_calls  # 全部异体零副作用

    def test_same_key_different_org_is_independent(self, db_session, ae_world) -> None:
        """S-AE-02 A6：跨租户同键同体 → 不触发 409，各自独立执行（org_id 入约束）。"""
        from fde_api.action_execution import service as svc

        key = "idem-cross-org-" + uuid4().hex[:8]
        dispatch_a = RecordingDispatch({"message_id": "a-1", "delivered_count": 1})
        dispatch_b = RecordingDispatch({"message_id": "b-1", "delivered_count": 1})

        payload_a = _request(idempotency_key=key, org_id=ae_world["org"].id, requester_id=ae_world["actor"].id)
        payload_b = _request(idempotency_key=key, org_id=ae_world["org_b"].id, requester_id=ae_world["actor_b"].id)

        ra = svc.submit_action(actor=ae_world["actor"], payload=payload_a, whitelist_gate=AllowAllWhitelist(), dispatch=dispatch_a)
        rb = svc.submit_action(actor=ae_world["actor_b"], payload=payload_b, whitelist_gate=AllowAllWhitelist(), dispatch=dispatch_b)

        assert ra["status"] == "succeeded"
        assert rb["status"] == "succeeded"  # 不触发 409：org 隔离的独立约束域
        assert dispatch_a.calls == 1 and dispatch_b.calls == 1
        assert ra["execution_id"] != rb["execution_id"]

    def test_missing_idempotency_key_is_422(self, client, db_session, ae_world, settings) -> None:
        """S-AE-02 A7：缺 idempotency_key → 422 validation_failed，零副作用（L1 短路）。"""
        from fde_api.auth.tokens import issue_access_token

        payload = _request(org_id=ae_world["org"].id, requester_id=ae_world["actor"].id)
        payload.pop("idempotency_key")
        res = client.post(
            "/api/v1/action-executions", json=payload, headers={"Authorization": f"Bearer {issue_access_token(ae_world['actor'], settings)}"}
        )
        assert res.status_code == 422
        assert res.get_json()["error"]["code"] == "validation_failed"

    def test_idempotency_key_length_boundary_160_161(self, db_session, ae_world) -> None:
        """S-AE-02 A8：键长 160 接受 / 161 → 422 validation_failed。"""
        from fde_api.action_execution import service as svc
        from fde_api.action_execution.errors import ActionExecutionError

        ok_payload = _request(
            idempotency_key="k" * 160, org_id=ae_world["org"].id, requester_id=ae_world["actor"].id
        )
        result = svc.submit_action(
            actor=ae_world["actor"], payload=ok_payload, whitelist_gate=AllowAllWhitelist(), dispatch=RecordingDispatch()
        )
        assert result["status"] == "succeeded"

        over = _request(
            idempotency_key="k" * 161, org_id=ae_world["org"].id, requester_id=ae_world["actor"].id
        )
        with pytest.raises(ActionExecutionError) as err:
            svc.submit_action(
                actor=ae_world["actor"], payload=over, whitelist_gate=AllowAllWhitelist(), dispatch=RecordingDispatch()
            )
        assert err.value.code == "validation_failed"
        assert err.value.status == 422

    def test_concurrent_same_key_single_side_effect(self, db_session, ae_world, monkeypatch) -> None:
        """S-AE-02 A9：并发同键（竞态窗口模拟：败者 lookup 穿透，时序等价于败者
        查询先于首次锁行落库）→ 在途锁落库撞 UNIQUE 兜底 → 败者 409
        ``idempotency_in_flight``，副作用计数 == 1（败者未到 dispatch）。"""
        from fde_api.action_execution import service as svc
        from fde_api.action_execution.errors import ActionExecutionError

        payload = _request(org_id=ae_world["org"].id, requester_id=ae_world["actor"].id)
        dispatch = RecordingDispatch({"message_id": "m-1", "delivered_count": 1})

        first = svc.submit_action(
            actor=ae_world["actor"], payload=payload, whitelist_gate=AllowAllWhitelist(), dispatch=dispatch
        )
        assert first["status"] == "succeeded"
        assert dispatch.calls == 1

        # 竞态窗口：败者 lookup 穿透（返回 None，时序＝败者查询先于锁行可见）
        real_lookup = svc._DbIdempotencyGate.lookup
        state = {"racer_done": False}

        def racing_lookup(self, key, org, fingerprint):  # noqa: ANN001
            if not state["racer_done"]:
                state["racer_done"] = True
                return None
            return real_lookup(self, key, org, fingerprint)

        monkeypatch.setattr(svc._DbIdempotencyGate, "lookup", racing_lookup)

        with pytest.raises(ActionExecutionError) as err:
            svc.submit_action(
                actor=ae_world["actor"], payload=payload, whitelist_gate=AllowAllWhitelist(), dispatch=dispatch
            )
        assert err.value.code == "idempotency_in_flight"
        assert err.value.status == 409
        assert dispatch.calls == 1  # 败者未到 dispatch：副作用仍 == 1

    def test_in_flight_lock_released_to_terminal_state(self, db_session, ae_world) -> None:
        """在途锁释放：终态行（succeeded）之后同键提交走复放而非 409（锁随终态释放）。"""
        from fde_api.action_execution import service as svc

        payload = _request(org_id=ae_world["org"].id, requester_id=ae_world["actor"].id)
        dispatch = RecordingDispatch({"message_id": "m-1", "delivered_count": 1})
        first = svc.submit_action(
            actor=ae_world["actor"], payload=payload, whitelist_gate=AllowAllWhitelist(), dispatch=dispatch
        )
        replay = svc.submit_action(
            actor=ae_world["actor"], payload=payload, whitelist_gate=AllowAllWhitelist(), dispatch=dispatch
        )
        assert first["status"] == "succeeded"
        assert replay["status"] == "replayed"  # 终态复放，非 in_flight

    def test_existing_constraints_untouched(self) -> None:
        """53 号 WP2 验收①：既有幂等约束逐字未动（禁改清单第 6 项的机械复核）。

        路径锚：按 ``__file__`` 解析（评审补强 G2-26/G2-27：原先用 CWD 相对
        路径，从仓根运行即 ``FileNotFoundError``——同批其它文件均用
        ``Path(__file__)``，此处对齐）。
        """
        from pathlib import Path

        src_root = Path(__file__).resolve().parents[1] / "src" / "fde_api"
        control = (src_root / "control" / "models.py").read_text(encoding="utf-8")
        agents = (src_root / "agents" / "models.py").read_text(encoding="utf-8")
        assert 'UniqueConstraint("idempotency_key", name="uq_automation_task_runs_idempotency")' in control
        assert "uq_agent_runs_idempotency_active" in agents
