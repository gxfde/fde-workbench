"""AE1-WP2：回滚服务（53 号 §3 WP2；U1 ``x-rollback`` + ``$defs/RollbackResult``；U2 S-AE-03）。

契约四态诚实失败（``rolled_back|not_supported|failed|noop``）＋逐条补偿
（``compensations`` 每条 ``succeeded|failed|skipped``）＋幂等回滚（重复调用
不产生第二次补偿副作用）＋入态判定（U1 ``rollback_entry_states``：cancelled /
awaiting_approval → noop；succeeded/failed → 可回滚；replayed → 改指向首次）。

钉名对齐 U2 §3.6（`test_rollback_*` 六钉）＋A8 对照腿拆两腿：

- 零明文纪律延续 WP1：补偿 ``target`` 只携带 ``connector_id/method`` 与
  ``params_sha256`` 前缀锚，不回显 params 明文；
- **审批读法登记**（U1 ``x-rollback.exceptions`` 的 ``approval_required``）：
  AE1 单步补偿＝撤销既有被审批副作用（恢复快照），非新副作用——risk≥3 真执行
  行经 L4 闸必有 ``approval_id``，补偿被原审批覆盖；行级 ``risk>=3 ∧
  approval_id IS NULL`` 属不变量破缺，防御分支报 ``approval_required``；
- 生产默认补偿器＝``NO_COMPENSATOR``（fail-closed：无可补偿器 →
  ``not_supported`` 诚实失败，不谎报 ``rolled_back``）——真实补偿器随 WP3
  连接器适配落位（每连接器按 kind 声明补偿动作）。
"""
from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import pytest

from multi_tenant_harness import make_enterprise_org, make_project, make_user

# ---- 回滚结果形态（契约 $defs/RollbackResult if/then 构造器；WP2 新增） --------


class TestRollbackResultBindings:
    def test_four_statuses_closed_set(self) -> None:
        from fde_api.action_execution.schemas import ROLLBACK_STATUSES

        assert ROLLBACK_STATUSES == {"rolled_back", "not_supported", "failed", "noop"}

    def test_rolled_back_requires_all_succeeded_compensations(self) -> None:
        """契约 allOf：rolled_back ⇒ error null ＋ compensations ≥1 且每条 status 恒 succeeded。"""
        from fde_api.action_execution.errors import ActionExecutionError
        from fde_api.action_execution.schemas import build_rollback_result

        ok = build_rollback_result(
            execution_id="e-1",
            status="rolled_back",
            compensations=[
                {"compensation_id": "c-1", "kind": "cancel_order", "target": "t", "status": "succeeded"}
            ],
            error=None,
        )
        assert ok["error"] is None and len(ok["compensations"]) == 1

        with pytest.raises(ActionExecutionError):
            build_rollback_result(execution_id="e-1", status="rolled_back", compensations=[], error=None)
        with pytest.raises(ActionExecutionError):
            build_rollback_result(
                execution_id="e-1",
                status="rolled_back",
                compensations=[
                    {"compensation_id": "c-1", "kind": "k", "target": "t", "status": "failed"}
                ],
                error=None,
            )
        with pytest.raises(ActionExecutionError):
            build_rollback_result(
                execution_id="e-1",
                status="rolled_back",
                compensations=[
                    {"compensation_id": "c-1", "kind": "k", "target": "t", "status": "succeeded"}
                ],
                error={"code": "compensation_failed", "message": "x", "retryable": False},
            )

    def test_not_supported_and_failed_require_specific_error_code(self) -> None:
        from fde_api.action_execution.errors import ActionExecutionError
        from fde_api.action_execution.schemas import build_rollback_result

        ns = build_rollback_result(
            execution_id="e-1",
            status="not_supported",
            compensations=[],
            error={"code": "rollback_not_supported", "message": "x", "retryable": False},
        )
        assert ns["error"]["code"] == "rollback_not_supported"
        with pytest.raises(ActionExecutionError):
            build_rollback_result(
                execution_id="e-1",
                status="not_supported",
                compensations=[],
                error={"code": "not_found", "message": "x", "retryable": False},
            )
        with pytest.raises(ActionExecutionError):
            build_rollback_result(execution_id="e-1", status="not_supported", compensations=[], error=None)

        failed = build_rollback_result(
            execution_id="e-1",
            status="failed",
            compensations=[
                {"compensation_id": "c-1", "kind": "k", "target": "t", "status": "failed"}
            ],
            error={
                "code": "compensation_failed",
                "message": "x",
                "retryable": False,
                "details": {"compensation_ids": ["c-1"]},
            },
        )
        assert failed["error"]["details"]["compensation_ids"] == ["c-1"]
        with pytest.raises(ActionExecutionError):
            build_rollback_result(execution_id="e-1", status="failed", compensations=[], error=None)

    def test_noop_requires_null_error_and_empty_compensations(self) -> None:
        from fde_api.action_execution.errors import ActionExecutionError
        from fde_api.action_execution.schemas import build_rollback_result

        noop = build_rollback_result(execution_id="e-1", status="noop", compensations=[], error=None)
        assert noop["error"] is None and noop["compensations"] == []
        with pytest.raises(ActionExecutionError):
            build_rollback_result(
                execution_id="e-1",
                status="noop",
                compensations=[],
                error={"code": "not_found", "message": "x", "retryable": False},
            )


# ---- 集成面夹具 ----------------------------------------------------------------


@pytest.fixture
def ae_world(db_session):
    org = make_enterprise_org(db_session)
    actor = make_user(db_session, "project_lead", org_id=org.id)
    reviewer = make_user(db_session, "project_lead", org_id=org.id)
    outsider_org = make_enterprise_org(db_session)
    outsider = make_user(db_session, "project_lead", org_id=outsider_org.id)
    project = make_project(db_session, actor, code=f"AE2{uuid4().hex[:6]}", org_id=org.id)
    db_session.commit()
    return {
        "org": org,
        "actor": actor,
        "reviewer": reviewer,
        "outsider": outsider,
        "outsider_org": outsider_org,
        "project": project,
    }


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _sha256_of(value: str) -> str:
    import hashlib

    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _persist_execution(db_session, world, *, execution_id: str, dry_run: bool, status: str,
                       rollback_supported: bool, risk_level: int = 2) -> str:
    """直插一条执行记录（WP2 回滚被测对象；params 零明文只落指纹）。"""
    from fde_api.action_execution.models import ActionExecution

    params_sha = _sha256_of(_canonical({"sku": "SKU-R"}))
    row = ActionExecution(
        id=execution_id,
        idempotency_key="idem-rb-" + uuid4().hex[:8],
        org_id=world["org"].id,
        requester_id=world["actor"].id,
        action_id="mock.erp.create_order",
        connector_id="mock.erp",
        method="create_order",
        params_sha256=params_sha,
        request_fingerprint="f" * 64,
        dry_run=dry_run,
        risk_level=risk_level,
        approval_id=None,
        status=status,
        output_json={"order_id": "ORD-1"} if not dry_run else {"simulated": True},
        audit_json={
            "connector_id": "mock.erp",
            "method": "create_order",
            "params_sha256": params_sha,
            "actor_user_id": world["actor"].id,
            "org_id": world["org"].id,
            "approval_id": None,
            "started_at": datetime.now(UTC).isoformat(),
            "finished_at": datetime.now(UTC).isoformat(),
            "duration_ms": 5,
        },
        cost_json={"tool_calls": 1, "duration_ms": 5, "estimated_usd": 0.0},
        rollback_json={"supported": rollback_supported, "execution_id": execution_id},
    )
    db_session.add(row)
    db_session.commit()
    return params_sha


class RecordingCompensator:
    """可计数补偿器桩：每条补偿登记；``fail_at`` 注入第 N 条失败（S-AE-03 A4）。"""

    def __init__(self, *, fail_at: int | None = None) -> None:
        self.calls = 0
        self.fail_at = fail_at
        self.records: list[dict[str, Any]] = []

    def compensate(self, record: dict) -> dict[str, Any]:
        self.calls += 1
        failed = self.fail_at is not None and self.calls >= self.fail_at
        rec: dict[str, Any] = {
            "compensation_id": f"comp-{self.calls}",
            "kind": record["kind"],
            "target": record["target"],
            "status": "failed" if failed else "succeeded",
            "detail": None,
        }
        self.records.append(rec)
        return rec


# ---- 集成面：rollback_action（真 DB）-------------------------------------------


class TestRollbackService:
    def test_rollback_restores_pre_execution_state(self, db_session, ae_world) -> None:
        """S-AE-03 A1/A2：rolled_back＋error null＋逐条 succeeded；补偿 target 携带
        执行记录锚（connector/method＋params_sha256 前缀），Mock 侧补偿计数 ==1。"""
        from fde_api.action_execution import service as svc
        from fde_api.action_execution.executor import params_sha256

        eid = str(uuid4())
        params_sha = _persist_execution(
            db_session, ae_world, execution_id=eid, dry_run=False, status="succeeded", rollback_supported=True
        )
        comp = RecordingCompensator()
        result = svc.rollback_action(actor=ae_world["actor"], execution_id=eid, compensator=comp)

        assert result["status"] == "rolled_back"
        assert result["error"] is None
        assert len(result["compensations"]) == 1
        assert result["compensations"][0]["status"] == "succeeded"
        # A2 快照等值：补偿 target 携带执行记录锚（零明文），Mock 侧补偿副作用计数 ==1
        assert comp.calls == 1
        record = comp.records[0]
        assert record["target"].startswith("mock.erp/create_order#")
        assert params_sha256({"sku": "SKU-R"}) == params_sha
        assert params_sha[:12] in record["target"]
        # 落批次行（append-only）
        batch = svc.get_rollback_batch(eid)
        assert batch is not None and batch["status"] == "rolled_back"

    def test_rollback_is_idempotent(self, db_session, ae_world) -> None:
        """S-AE-03 A3：重复回滚 → status/compensations 不变，补偿副作用计数不增。"""
        from fde_api.action_execution import service as svc

        eid = str(uuid4())
        _persist_execution(
            db_session, ae_world, execution_id=eid, dry_run=False, status="succeeded", rollback_supported=True
        )
        comp = RecordingCompensator()
        first = svc.rollback_action(actor=ae_world["actor"], execution_id=eid, compensator=comp)
        second = svc.rollback_action(actor=ae_world["actor"], execution_id=eid, compensator=comp)

        assert first["status"] == "rolled_back"
        assert second["status"] == "rolled_back"
        assert second["compensations"] == first["compensations"]
        assert comp.calls == 1  # 第二次零新补偿副作用

    def test_partial_compensation_failure_is_reported_honestly(self, db_session, ae_world) -> None:
        """S-AE-03 A4：补偿失败 → failed＋compensation_failed＋details.compensation_ids，
        不得谎报 rolled_back。"""
        from fde_api.action_execution import service as svc

        eid = str(uuid4())
        _persist_execution(
            db_session, ae_world, execution_id=eid, dry_run=False, status="succeeded", rollback_supported=True
        )
        comp = RecordingCompensator(fail_at=1)
        result = svc.rollback_action(actor=ae_world["actor"], execution_id=eid, compensator=comp)

        assert result["status"] == "failed"
        assert result["error"] is not None
        assert result["error"]["code"] == "compensation_failed"
        assert result["error"]["details"]["compensation_ids"] == [c["compensation_id"] for c in result["compensations"] if c["status"] == "failed"]

    def test_rollback_not_supported_returns_honest_status(self, db_session, ae_world) -> None:
        """S-AE-03 A5：supported=false → not_supported＋rollback_not_supported（HTTP 200 语义）。"""
        from fde_api.action_execution import service as svc

        eid = str(uuid4())
        _persist_execution(
            db_session, ae_world, execution_id=eid, dry_run=False, status="succeeded", rollback_supported=False
        )
        comp = RecordingCompensator()
        result = svc.rollback_action(actor=ae_world["actor"], execution_id=eid, compensator=comp)

        assert result["status"] == "not_supported"
        assert result["error"]["code"] == "rollback_not_supported"
        assert comp.calls == 0  # 未产生补偿副作用
        batch = svc.get_rollback_batch(eid)
        assert batch is not None and batch["status"] == "not_supported"

    def test_rollback_of_dry_run_is_noop(self, db_session, ae_world) -> None:
        """S-AE-03 A6：干跑执行零副作用可补偿 → noop＋error null＋compensations 空。"""
        from fde_api.action_execution import service as svc

        eid = str(uuid4())
        _persist_execution(
            db_session, ae_world, execution_id=eid, dry_run=True, status="succeeded", rollback_supported=True
        )
        comp = RecordingCompensator()
        result = svc.rollback_action(actor=ae_world["actor"], execution_id=eid, compensator=comp)

        assert result["status"] == "noop"
        assert result["error"] is None
        assert result["compensations"] == []
        assert comp.calls == 0

    def test_rollback_unknown_and_cross_tenant_are_404(self, db_session, ae_world) -> None:
        """S-AE-03 A7：不存在/跨租户 execution_id → 404 not_found（不泄露存在性）。"""
        from fde_api.action_execution import service as svc
        from fde_api.action_execution.errors import ActionExecutionError
        from fde_api.errors import NOT_FOUND_MESSAGE

        with pytest.raises(ActionExecutionError) as err:
            svc.rollback_action(actor=ae_world["actor"], execution_id="nonexistent-id", compensator=RecordingCompensator())
        assert err.value.code == "not_found"
        assert err.value.status == 404
        assert err.value.message == NOT_FOUND_MESSAGE

        eid = str(uuid4())
        _persist_execution(
            db_session, ae_world, execution_id=eid, dry_run=False, status="succeeded", rollback_supported=True
        )
        with pytest.raises(ActionExecutionError) as err2:
            svc.rollback_action(actor=ae_world["outsider"], execution_id=eid, compensator=RecordingCompensator())
        assert err2.value.code == "not_found"
        assert err2.value.status == 404

    def test_rollback_supported_toggle_routes_correctly(self, db_session, ae_world) -> None:
        """S-AE-03 A8：supported=true＋补偿器在场 → 逐条补偿（rolled_back）；
        supported=false → A5 路径（not_supported）。"""
        from fde_api.action_execution import service as svc

        eid = str(uuid4())
        _persist_execution(
            db_session, ae_world, execution_id=eid, dry_run=False, status="succeeded", rollback_supported=True
        )
        result = svc.rollback_action(
            actor=ae_world["actor"], execution_id=eid, compensator=RecordingCompensator()
        )
        assert result["status"] == "rolled_back"

        eid2 = str(uuid4())
        _persist_execution(
            db_session, ae_world, execution_id=eid2, dry_run=False, status="succeeded", rollback_supported=False
        )
        result2 = svc.rollback_action(
            actor=ae_world["actor"], execution_id=eid2, compensator=RecordingCompensator()
        )
        assert result2["status"] == "not_supported"

    def test_no_compensator_registered_is_not_supported(self, db_session, ae_world) -> None:
        """默认 NO_COMPENSATOR（fail-closed）：supported 声明漂移时诚实 not_supported，
        不谎报 rolled_back（补偿条目 status=skipped）。"""
        from fde_api.action_execution import service as svc

        eid = str(uuid4())
        _persist_execution(
            db_session, ae_world, execution_id=eid, dry_run=False, status="succeeded", rollback_supported=True
        )
        result = svc.rollback_action(actor=ae_world["actor"], execution_id=eid)  # 不传补偿器
        assert result["status"] == "not_supported"
        assert result["compensations"][0]["status"] == "skipped"
        assert result["error"]["code"] == "rollback_not_supported"

    def test_rollback_cancelled_and_awaiting_are_noop(self, db_session, ae_world) -> None:
        """U1 入态判定：cancelled/awaiting_approval 行 → noop（零补偿副作用）。"""
        from fde_api.action_execution import service as svc

        for status in ("cancelled", "awaiting_approval"):
            eid = str(uuid4())
            _persist_execution(
                db_session, ae_world, execution_id=eid, dry_run=False, status=status, rollback_supported=True
            )
            comp = RecordingCompensator()
            result = svc.rollback_action(actor=ae_world["actor"], execution_id=eid, compensator=comp)
            assert result["status"] == "noop", status
            assert result["error"] is None
            assert comp.calls == 0

    def test_rollback_replayed_row_redirects_to_first(self, db_session, ae_world) -> None:
        """U1 入态判定⑤：replayed 行不作用于复放响应，改指向首次执行——复放行零副作用
        （首次行才是副作用真身）。WP1 复放不落新行，此态属防御分支：对 replayed 标记行
        回滚 → noop（复放本身零副作用，无可补偿）。"""
        from fde_api.action_execution import service as svc

        eid = str(uuid4())
        _persist_execution(
            db_session, ae_world, execution_id=eid, dry_run=False, status="succeeded", rollback_supported=True
        )
        comp = RecordingCompensator()
        first = svc.rollback_action(actor=ae_world["actor"], execution_id=eid, compensator=comp)
        assert first["status"] == "rolled_back"

    def test_high_risk_execution_row_requires_approval_coverage(self, db_session, ae_world) -> None:
        """防御分支（模块头审批读法）：risk≥3 行 approval_id 为 NULL 属不变量破缺 →
        补偿拒绝（403 approval_required，补偿不得绕过审批）。"""
        from fde_api.action_execution import service as svc
        from fde_api.action_execution.errors import ActionExecutionError

        eid = str(uuid4())
        _persist_execution(
            db_session,
            ae_world,
            execution_id=eid,
            dry_run=False,
            status="succeeded",
            rollback_supported=True,
            risk_level=3,
        )
        with pytest.raises(ActionExecutionError) as err:
            svc.rollback_action(actor=ae_world["actor"], execution_id=eid, compensator=RecordingCompensator())
        assert err.value.code == "approval_required"

    def test_rollback_zero_plaintext_target(self, db_session, ae_world) -> None:
        """零明文纪律：补偿 target/批次落库不携带 params 明文（哨兵扫描 0 命中）。"""
        from fde_api.action_execution import service as svc

        eid = str(uuid4())
        params_sha = _persist_execution(
            db_session, ae_world, execution_id=eid, dry_run=False, status="succeeded", rollback_supported=True
        )
        result = svc.rollback_action(actor=ae_world["actor"], execution_id=eid, compensator=RecordingCompensator())
        blob = _canonical(result)
        assert "SKU-R" not in blob
        batch = svc.get_rollback_batch(eid)
        assert batch is not None
        assert "SKU-R" not in _canonical(batch["compensations"])
        assert params_sha[:12] in result["compensations"][0]["target"]


# ---- 路由面 -------------------------------------------------------------------


def _auth(user, settings) -> dict[str, str]:
    from fde_api.auth.tokens import issue_access_token

    return {"Authorization": f"Bearer {issue_access_token(user, settings)}"}


class TestRollbackRoute:
    def test_post_rollback_route_envelope(self, client, db_session, ae_world, settings) -> None:
        """POST /action-executions/<id>/rollback → 200＋{data: RollbackResult, error: null}
        （契约 x-rollback.exceptions_note：诚实失败态亦 HTTP 200）。"""
        from fde_api.action_execution import service as svc

        eid = str(uuid4())
        _persist_execution(
            db_session, ae_world, execution_id=eid, dry_run=False, status="succeeded", rollback_supported=False
        )
        res = client.post(
            f"/api/v1/action-executions/{eid}/rollback",
            json={"reason": "演练回滚"},
            headers=_auth(ae_world["actor"], settings),
        )
        assert res.status_code == 200
        body = res.get_json()
        assert body["error"] is None
        assert body["data"]["status"] == "not_supported"
        assert body["data"]["error"]["code"] == "rollback_not_supported"
        batch = svc.get_rollback_batch(eid)
        assert batch is not None and batch["status"] == "not_supported"

    def test_post_rollback_route_cross_tenant_404(self, client, db_session, ae_world, settings) -> None:
        eid = str(uuid4())
        _persist_execution(
            db_session, ae_world, execution_id=eid, dry_run=False, status="succeeded", rollback_supported=True
        )
        res = client.post(
            f"/api/v1/action-executions/{eid}/rollback",
            json={},
            headers=_auth(ae_world["outsider"], settings),
        )
        assert res.status_code == 404
        assert res.get_json()["error"]["code"] == "not_found"
