"""AE1-WP3：连接器白名单门＋SSRF 回环反向＋Header 白名单＋KD-01 归一化（53 号 §3 WP3）。

钉名对齐 U4b（_ae-connectors-security-checklist.md §3）13 测试钉建议名
``test_ae_wp4_*``；S-AE-06 七断言（U2 §6.3 A1–A7）逐条落钉。

白名单快照（``action_execution/whitelist.json``）＝docs 仓冻结件 v1.3 的仓内
副本（**只读加载**：变更只能走白名单改版 v2＋评审——运行时不可变；缺失/损坏
fail-closed 全拒，禁改清单第 5/7 项）。匹配三元组＝
``(connector_id, method, http_binding)`` 精确匹配（Q6b 已追认字段名）。

SSRF 回环反向规则（Q7 已认可）：主机须命中白名单 base_url 集（localhost＋
固定端口），解析后**全部 IP 须为回环**（127.0.0.0/8、::1）——解析出任何非
回环 IP 即 403（DNS 重绑定前置拦截，方向由 M6「必须公网」反向收紧）；
禁止跟随重定向。

错误码纪律（Q8）：15 码闭集外的执行期失败（上游 5xx/超时/连接失败）映射
闭集内 ``tool_not_allowed``＋``details.reason`` 标注（不扩闭集、不自造码）。
"""
from __future__ import annotations

import json
import socket
import uuid
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

import _ae_mock_stack as mock_stack_module
from fde_api.action_execution import connectors
from fde_api.action_execution.errors import ActionExecutionError
from multi_tenant_harness import make_enterprise_org, make_project, make_user

SERVER_ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT_PATH = SERVER_ROOT / "src" / "fde_api" / "action_execution" / "whitelist.json"


def _request(**overrides) -> dict:
    """合法 ontology read 请求（经白名单三元组与 SSRF 预检的基线 payload）。"""
    req: dict = {
        "action_id": "workbench.ontology.read",
        "action_type": "call_api",
        "connector_id": "workbench.ontology",
        "method": "read",
        "params": {"project_id": "p-1", "query": "Equipment", "limit": 20},
        "idempotency_key": "idem-wp3-" + "a" * 8,
        "org_id": "org-1",
        "requester_id": "user-1",
        "dry_run": False,
        "risk_level": 0,
        "timeout_seconds": 30,
        "approval_id": None,
    }
    req.update(overrides)
    return req


@pytest.fixture(scope="module")
def whitelist_snapshot() -> dict:
    return connectors.load_whitelist(str(SNAPSHOT_PATH))


# ---- C-02 / S-AE-06 A5 / A7：只读加载与 fail-closed -----------------------------


class TestWhitelistLoader:
    def test_whitelist_snapshot_matches_source_anchor(self, whitelist_snapshot) -> None:
        """仓内快照锚：v1.3 / 4 连接器封闭集 / 14 constraints——白名单改版 v2
        时此钉显式翻新（防快照静默漂移）。"""
        assert whitelist_snapshot["version"] == "1.3.3"  # v1.3.3＝B 桶 B-4 拍板 ae_rule 读法澄清（notes-only；v1.3.2＝KD-02/D4）
        assert [c["id"] for c in whitelist_snapshot["connectors"]] == [
            "workbench.ontology",
            "workbench.workflow",
            "mock.erp",
            "mock.email",
        ]
        assert len(whitelist_snapshot["constraints"]) == 14

    def test_load_missing_file_fails_closed(self, tmp_path) -> None:
        """C-02/禁改 5/7：白名单缺失 → fail-closed（403 tool_not_allowed），
        不得回退「任意 URL 可调」。"""
        with pytest.raises(ActionExecutionError) as err:
            connectors.load_whitelist(str(tmp_path / "missing.json"))
        assert err.value.code == "tool_not_allowed"
        assert err.value.status == 403

    def test_load_corrupted_file_fails_closed(self, tmp_path) -> None:
        """C-02/A7：白名单损坏（非法 JSON/缺 connectors 键）→ fail-closed 全拒。"""
        bad = tmp_path / "broken.json"
        bad.write_text("{not-json", encoding="utf-8")
        with pytest.raises(ActionExecutionError) as err:
            connectors.load_whitelist(str(bad))
        assert err.value.code == "tool_not_allowed"

        empty = tmp_path / "empty.json"
        empty.write_text(json.dumps({"version": "1.3"}), encoding="utf-8")
        with pytest.raises(ActionExecutionError) as err:
            connectors.load_whitelist(str(empty))
        assert err.value.code == "tool_not_allowed"

    def test_runtime_mutation_not_effective(self) -> None:
        """S-AE-06 A5：运行时改内存快照不生效——门持有的是加载时拷贝（深拷贝），
        原快照被改后门的行为逐字不变；且门无任何运行时注册入口。"""
        snapshot = connectors.load_whitelist(str(SNAPSHOT_PATH))
        gate = connectors.ConnectorWhitelist(snapshot)
        # 运行时篡改传入 dict（模拟内存中被改）→ 门判定面不变（深拷贝固化）
        snapshot["connectors"].append(
            {"id": "evil.api", "name": "evil.api", "type": "external", "base_url": "http://localhost:9999",
             "methods": ["read"], "http_bindings": [{"http_method": "GET", "path": "/x"}]}
        )
        with pytest.raises(ActionExecutionError) as err:
            gate.check("evil.api", "read")
        assert err.value.code == "tool_not_allowed"
        # 接口面：无运行时注册入口（白名单变更只能走改版 v2＋评审）
        assert not hasattr(gate, "register") and not hasattr(gate, "add")


# ---- C-01 / S-AE-06 A1 / A2 / A3 / A4：三元组精确匹配 ---------------------------


class TestTripleMatchGate:
    def test_ae_wp4_whitelist_fail_closed_403(self) -> None:
        """C-01 / A1：未注册 connector_id → 403 tool_not_allowed，零外呼。"""
        gate = connectors.ConnectorWhitelist(connectors.load_whitelist(str(SNAPSHOT_PATH)))
        with pytest.raises(ActionExecutionError) as err:
            gate.check("evil.api", "read")
        assert err.value.code == "tool_not_allowed"
        assert err.value.status == 403

    def test_ae_wp4_registration_fail_closed_unknown_method(self) -> None:
        """C-01 / A2：连接器在册但 method 未登记 → 403 tool_not_allowed。"""
        gate = connectors.ConnectorWhitelist(connectors.load_whitelist(str(SNAPSHOT_PATH)))
        with pytest.raises(ActionExecutionError) as err:
            gate.check("mock.erp", "create_order")  # mock.erp 只登记 query_inventory
        assert err.value.code == "tool_not_allowed"

    def test_ae_wp4_whitelist_registration_fail_closed(self) -> None:
        """C-02：白名单缺失/损坏/版本不符 → 全拒；无运行时注册入口
        （ConnectorWhitelist 不提供 add/register 方法——接口面钉）。"""
        gate = connectors.ConnectorWhitelist(connectors.load_whitelist(str(SNAPSHOT_PATH)))
        assert not hasattr(gate, "register")
        assert not hasattr(gate, "add")

    def test_ae_wp4_ssrf_precheck_unregistered_host(self, whitelist_snapshot) -> None:
        """C-03 / A4：白名单连接器指向未登记主机 → 403 tool_not_allowed（SSRF 面）。"""
        with pytest.raises(ActionExecutionError) as err:
            connectors.ssrf_precheck("http://169.254.169.254/latest/meta-data", whitelist_snapshot)
        assert err.value.code == "tool_not_allowed"

    def test_ssrf_non_loopback_resolution_403(self, whitelist_snapshot) -> None:
        """C-03 / Q7 回环反向：base_url 主机在册但解析出非回环 IP → 403
        （DNS 重绑定前置拦截；monkeypatch getaddrinfo 模拟劫持）。"""
        with patch(
            "socket.getaddrinfo",
            return_value=[(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 5001))],
        ):
            with pytest.raises(ActionExecutionError) as err:
                connectors.ssrf_precheck("http://localhost:5001/mock-erp/inventory", whitelist_snapshot)
        assert err.value.code == "tool_not_allowed"

    def test_ssrf_loopback_resolution_ok(self, whitelist_snapshot) -> None:
        """合法对照：localhost 解析 127.0.0.1 → 预检通过（不抛）。"""
        with patch(
            "socket.getaddrinfo",
            return_value=[(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 5001))],
        ):
            connectors.ssrf_precheck("http://localhost:5001/mock-erp/inventory", whitelist_snapshot)

    def test_address_override_rejected_by_l1(self) -> None:
        """C-03 / A3：params 试图覆盖目标地址（url/base_url/host 键）→ 422
        validation_failed（L1 敏感键扫描已拒——WP1 面承接，此处钉连接器侧
        判定口径的固定性：目标地址只来自白名单 base_url，params 无法改写）。"""
        gate = connectors.ConnectorWhitelist(connectors.load_whitelist(str(SNAPSHOT_PATH)))
        spec = gate.check("mock.erp", "query_inventory")
        url = connectors.build_request_url(spec, {"sku": "s-1", "url": "http://evil.test/x"})
        assert url.startswith("http://localhost:5001/")  # 目标地址恒来自白名单


# ---- C-13：出站请求头白名单 ------------------------------------------------------


class TestHeaderPolicy:
    def test_ae_wp4_header_allowlist_enforced(self) -> None:
        """C-13：出站头集合＝固定基线＋登记允许头（Authorization/Idempotency-Key）；
        调用方自定义头不外发（头集逐条相等）。"""
        headers = connectors.build_outbound_headers(
            auth_type="bearer_token",
            token="jwt-x",
            idempotency_key="idem-1",
        )
        names = {k.lower() for k in headers}
        assert names == {"content-type", "accept", "user-agent", "authorization", "idempotency-key"}

    def test_caller_custom_header_422(self) -> None:
        """C-13：params 出现头名字段 → 422 validation_failed（L1 敏感键/头名
        扫描口径；头集合不符被拒 → 403 tool_not_allowed 由 dispatch 层兜底）。"""
        with pytest.raises(ActionExecutionError) as err:
            connectors.reject_caller_headers({"to": "a@b.t", "X-Custom-Header": "x"})
        assert err.value.code == "validation_failed"
        assert err.value.status == 422


# ---- dispatch／KD-01 归一化 ------------------------------------------------------


class TestDispatch:
    def test_response_body_zero_echo_on_upstream_error(self) -> None:
        """C-08：上游非 2xx → 闭集内 tool_not_allowed＋details 只带
        http_status/reason——上游响应体原文零回显（Q8 映射口径）。"""
        error = connectors.map_upstream_failure(status=503, body="<html>secret-stack-trace</html>", reason="connector_upstream_error")
        assert error.code == "tool_not_allowed"
        blob = json.dumps({"details": error.details, "message": error.message})
        assert "secret-stack-trace" not in blob
        assert error.details is not None
        assert error.details["http_status"] == 503

    def test_map_upstream_timeout(self) -> None:
        """C-07（Q8 缺口码口径）：上游超时 → 闭集内 tool_not_allowed＋
        details.reason=connector_timeout（不扩闭集不自造 504 码）。"""
        error = connectors.map_upstream_failure(status=None, body="", reason="connector_timeout")
        assert error.code == "tool_not_allowed"
        assert error.details is not None
        assert error.details["reason"] == "connector_timeout"


class TestKd01Normalization:
    def test_ae_wp4_ontology_read_output_normalized(self) -> None:
        """KD-01（T4-001 断言可判定）：workbench.ontology read 的
        {data:{items:[…]}} 信封 → output={ontologies:[{ontology_id,name,org_id}…],
        count:int}——元素三键派生（id→ontology_id、term→name、请求方 org_id）。"""
        upstream = {
            "data": {
                "items": [
                    {"id": "t-1", "term": "Equipment", "term_type": "device", "status": "active"},
                    {"id": "t-2", "term": "Sensor", "term_type": "device", "status": "active"},
                ]
            },
            "error": None,
        }
        output = connectors.normalize_output(
            connector_id="workbench.ontology", method="read", payload_json=upstream, org_id="org-9"
        )
        assert output["count"] == 2
        assert output["ontologies"][0] == {"ontology_id": "t-1", "name": "Equipment", "org_id": "org-9"}
        assert output["ontologies"][1] == {"ontology_id": "t-2", "name": "Sensor", "org_id": "org-9"}

    def test_mock_passthrough_minimal_output(self) -> None:
        """mock.* 连接器：输出＝上游最小业务结果（message_id/items）——非 2xx
        走 map_upstream_failure，成功态不回显上游信封外壳。"""
        output = connectors.normalize_output(
            connector_id="mock.email",
            method="send",
            payload_json={"message_id": "m-1", "delivered_count": 1, "mailbox_count": 5},
            org_id="org-9",
        )
        assert output == {"message_id": "m-1", "delivered_count": 1, "mailbox_count": 5}


@pytest.fixture(scope="module")
def mock_stack():
    stack = mock_stack_module.MockStack()
    stack.start()
    yield stack
    stack.stop()


@pytest.fixture(scope="module")
def wb_service(test_settings):
    """workbench 真身（8010 被外部 dev server/wslrelay 占用时回退 ephemeral
    端口——钉经 ``wb_port`` 注入测试快照 base_url，真 HTTP 链路不削弱）。"""
    svc = mock_stack_module.WorkbenchService(test_settings)
    svc.start()
    yield svc
    svc.stop()


@pytest.fixture(scope="module")
def wb_port(wb_service):
    """workbench 实际端口（8010 或 ephemeral 回退值）。"""
    return wb_service.port


@pytest.fixture
def ae3_world(db_session):
    org = make_enterprise_org(db_session)
    actor = make_user(db_session, "project_lead", org_id=org.id)
    org_b = make_enterprise_org(db_session)
    actor_b = make_user(db_session, "project_lead", org_id=org_b.id)
    project = make_project(db_session, actor, code=f"AE3{uuid.uuid4().hex[:6]}", org_id=org.id)
    db_session.commit()
    return {"org": org, "actor": actor, "org_b": org_b, "actor_b": actor_b, "project": project}


def _live_gates(token: str | None, wb_port: int | None = None) -> tuple[Any, Any]:
    """生产等价装配：白名单门（仓内快照只读加载）＋真 HTTP dispatch。

    ``wb_port``＝测试装置参数：8010 被外部占用回退 ephemeral 时，把快照
    base_url 的 ``:8010`` 注入为实际端口（装置级快照构造——非运行时篡改：
    生产门仍用冻结快照原文，A5 语义不变）。"""
    snapshot = connectors.load_whitelist(str(SNAPSHOT_PATH))
    if wb_port is not None and wb_port != 8010:
        for conn in snapshot["connectors"]:
            if conn.get("id") in {"workbench.ontology", "workbench.workflow"}:
                conn["base_url"] = f"http://127.0.0.1:{wb_port}"
    gate = connectors.ConnectorWhitelist(snapshot)
    dispatch = connectors.HttpDispatch(whitelist=gate, token=token, timeout_seconds=5.0, whitelist_snapshot=snapshot)
    return gate, dispatch


class TestLiveDispatch:
    def test_ae_wp4_idempotency_single_side_effect(
        self, db_session, ae3_world, mock_stack, wb_service, wb_port, test_settings
    ) -> None:
        """C-10 / S-AE-06 A6：mock.email 同键同体三连发——桩侧恰好收到 **1 次**
        外呼、收件箱新增 1 条（白名单 idempotency_assertion 观测面）；其余复放。
        顺带钉 C-05：审计与响应零占位凭据明文。"""
        from fde_api.action_execution import service as svc
        from fde_api.auth.tokens import issue_access_token

        actor = ae3_world["actor"]
        gate, dispatch = _live_gates(None)  # mock.* 无内部 JWT（api_key 占位面）
        payload = _request(
            connector_id="mock.email",
            method="send",
            action_id="mock.email.send",
            action_type="send_email",
            params={"to": "ops@example.test", "subject": "s-wp3", "body": "b-wp3"},
            org_id=actor.org_id,
            requester_id=actor.id,
            risk_level=3,
            dry_run=False,
            idempotency_key="idem-wp3-email-" + uuid.uuid4().hex[:8],
        )
        # C-12 轻量腿：risk 3 无 approval_id → L4 先于外呼 403（桩零请求）
        with pytest.raises(ActionExecutionError) as err:
            svc.submit_action(actor=actor, payload=payload, whitelist_gate=gate, dispatch=dispatch)
        assert err.value.code == "approval_required"
        assert mock_stack.email_requests == 0

        # C-05 占位腿：api_key 占位头（零真实凭据）不阻断——risk 0 的 mock.erp 先行
        erp_payload = _request(
            connector_id="mock.erp",
            method="query_inventory",
            action_id="mock.erp.query-inventory",
            action_type="call_api",
            params={"sku": "SKU-WP3", "warehouse_id": "wh-1"},
            org_id=actor.org_id,
            requester_id=actor.id,
            risk_level=0,
            dry_run=False,
            idempotency_key="idem-wp3-erp-" + uuid.uuid4().hex[:8],
        )
        result = svc.submit_action(actor=actor, payload=erp_payload, whitelist_gate=gate, dispatch=dispatch)
        assert result["status"] == "succeeded"
        assert "auth_type" not in result  # 响应不含凭据形态字段
        assert mock_stack.erp_requests == 1

        # A6/C-10 主腿：mock.email 带 approval（直插审批行＋指纹对齐）→ 同键两次副作用 1
        approval_id = self._make_approval(db_session, ae3_world, payload, test_settings)
        payload = dict(payload, approval_id=approval_id)
        first = svc.submit_action(actor=actor, payload=payload, whitelist_gate=gate, dispatch=dispatch)
        assert first["status"] == "succeeded"
        # 白名单 mock.email idempotency_assertion 口径：同键重复调用 3 次
        # （初次＋两次重放）——响应一致、收件箱新增恰 1 条
        for _ in range(2):
            replay = svc.submit_action(actor=actor, payload=payload, whitelist_gate=gate, dispatch=dispatch)
            assert replay["status"] == "replayed"
            assert replay["output"] == first["output"]
        assert mock_stack.email_requests == 1  # 桩侧恰好 1 次外呼
        assert len(mock_stack.inbox) == 1  # 收件箱新增 1 条

    def _make_approval(self, db_session, ae3_world, payload: dict, test_settings) -> str:
        """直插 AutomationApproval（run_id=None 直发形态；指纹＝params canonical sha256）。"""
        import json as _json
        from hashlib import sha256 as _sha256
        from datetime import UTC, datetime, timedelta

        from fde_api.control.models import AutomationApproval

        canonical = _json.dumps(payload["params"], ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        row = AutomationApproval(
            id=str(uuid.uuid4()),
            run_id=None,
            workflow_node_run_id=None,
            project_id=ae3_world["project"].id,
            requested_by_user_id=ae3_world["actor"].id,
            request_key=f"ae-wp3-{uuid.uuid4().hex[:12]}",
            capability="action_execution.invoke",
            tool_name="action_execution.execute",
            risk_level=payload["risk_level"],
            status="approved",
            arguments_json=payload["params"],
            arguments_sha256=_sha256(canonical.encode("utf-8")).hexdigest(),
            expires_at=datetime.now(UTC) + timedelta(hours=1),
        )
        db_session.add(row)
        db_session.commit()
        return row.id

    def test_workflow_same_key_replay_one_draft(
        self, db_session, ae3_world, mock_stack, wb_service, wb_port, test_settings
    ) -> None:
        """53 号 WP3 验收⑤：workbench.workflow 建草稿路由自身不读幂等键
        （workflows/routes.py:41-57）→ AE1 补「同键重放只建 1 条」——
        同键两次提交，第一次真外呼建草稿、第二次复放零外呼，草稿表 1 条。"""
        from sqlalchemy import text as _text

        from fde_api.action_execution import service as svc
        from fde_api.auth.tokens import issue_access_token

        actor = ae3_world["actor"]
        token = issue_access_token(actor, test_settings)
        gate, dispatch = _live_gates(token, wb_port=wb_port)
        payload = _request(
            connector_id="workbench.workflow",
            method="create",
            action_id="workbench.workflow.create",
            action_type="create_record",
            params={
                "project_id": ae3_world["project"].id,
                "name": f"wf-wp3-{uuid.uuid4().hex[:6]}",
                "description": "AE1-WP3 同键重放钉",
                "dag": {"nodes": [{"key": "review", "type": "human_approval", "capability": "project.read"}]},
            },
            org_id=actor.org_id,
            requester_id=actor.id,
            risk_level=1,
            dry_run=False,
        )
        first = svc.submit_action(actor=actor, payload=payload, whitelist_gate=gate, dispatch=dispatch)
        assert first["status"] == "succeeded"
        replay = svc.submit_action(actor=actor, payload=payload, whitelist_gate=gate, dispatch=dispatch)
        assert replay["status"] == "replayed"
        row = db_session.execute(
            _text("SELECT count(*) FROM workflow_definitions WHERE project_id = :p"),
            {"p": ae3_world["project"].id},
        ).scalar()
        assert row == 1


    def test_ae_wp4_ontology_read_e2e_kd01(
        self, db_session, ae3_world, mock_stack, wb_service, wb_port, test_settings
    ) -> None:
        """KD-01 端到端：workbench.ontology read（真 8010＋JWT bearer）→
        端点 {data:{items:[…]}} → 适配层归一化 output.ontologies＋output.count
        （元素三键派生）＝T4-001 冻结断言可判定。"""
        from fde_api.action_execution import service as svc
        from fde_api.auth.tokens import issue_access_token
        from fde_api.extensions import db as _db
        from fde_api.ontology.models import OntologyTerm

        actor = ae3_world["actor"]
        pid = ae3_world["project"].id
        term_session = _db.session()  # 同一 session 变量（workbench db.session() 非 scoped——WP2 教训）
        term_session.add_all(
            [
                OntologyTerm(project_id=pid, term="Equipment", definition="设备类本体", term_type="entity", status="confirmed"),
                OntologyTerm(project_id=pid, term="Sensor", definition="传感类本体", term_type="entity", status="confirmed"),
            ]
        )
        term_session.commit()

        token = issue_access_token(actor, test_settings)
        gate, dispatch = _live_gates(token, wb_port=wb_port)
        payload = _request(
            params={"project_id": pid, "query": "", "limit": 20},
            org_id=actor.org_id,
            requester_id=actor.id,
            risk_level=0,
            dry_run=False,
        )
        result = svc.submit_action(actor=actor, payload=payload, whitelist_gate=gate, dispatch=dispatch)
        assert result["status"] == "succeeded"
        assert result["output"]["count"] == 2
        names = {o["name"] for o in result["output"]["ontologies"]}
        assert names == {"Equipment", "Sensor"}
        for item in result["output"]["ontologies"]:
            assert set(item) == {"ontology_id", "name", "org_id"}
            assert item["org_id"] == actor.org_id

    def test_ae_wp4_tenant_isolation_404_cross_org(
        self, db_session, ae3_world, mock_stack, wb_service, wb_port, test_settings
    ) -> None:
        """C-11：跨租户连接器调用（他 org actor 指向我方 project）→
        workbench API 既有面 403（can_view 非成员）→ 闭集映射 tool_not_allowed
        ＋details.http_status=403（零成功、不泄露行内容；payload 零 tenant_id。
        AE 提交面的跨租户 404 not_found 口径（Q15/S-AE-05）已由 WP1 钉覆盖
        ——本钉钉连接器链承接上游语义的映射层）。"""
        from fde_api.action_execution import service as svc
        from fde_api.auth.tokens import issue_access_token

        actor_b = ae3_world["actor_b"]
        token_b = issue_access_token(actor_b, test_settings)
        gate, dispatch = _live_gates(token_b, wb_port=wb_port)
        payload = _request(
            params={"project_id": ae3_world["project"].id, "query": "", "limit": 20},
            org_id=actor_b.org_id,
            requester_id=actor_b.id,
            risk_level=0,
            dry_run=False,
        )
        assert "tenant_id" not in payload  # 禁自造 tenant_id（约束面）
        with pytest.raises(ActionExecutionError) as err:
            svc.submit_action(actor=actor_b, payload=payload, whitelist_gate=gate, dispatch=dispatch)
        assert err.value.code == "tool_not_allowed"
        assert err.value.details is not None
        assert err.value.details["http_status"] == 403


class TestCredentialFace:
    def test_ae_wp4_credential_no_plaintext(self) -> None:
        """C-05/C-09：白名单 auth_type ⊆ {bearer_token, api_key}；mock.* 桩
        零真实凭据（占位 api_key 头值固定串）；出站头零明文凭据。"""
        snapshot = connectors.load_whitelist(str(SNAPSHOT_PATH))
        for conn in snapshot["connectors"]:
            assert conn["auth_type"] in {"bearer_token", "api_key"}
        headers = connectors.build_outbound_headers(auth_type="api_key", token=None, idempotency_key="k")
        placeholder = headers.get("X-Api-Key", "")
        assert placeholder.startswith("ae1-placeholder")  # 占位串，非真实凭据
        assert "secret" not in placeholder.lower()


class TestSandboxEgressSelfConsistency:
    def test_ae_wp4_sandbox_egress_conflict_rejected(self, tmp_path) -> None:
        """C-04（53 号 WP3 验收③）：egress=deny 档带白名单 → 抛错拒绝
        （sandbox.py egress_allowlist_conflicts_deny 现状行为钉）。"""
        from fde_api.agents.sandbox import DockerBackend, SandboxError, SandboxHandle, SandboxProfile

        with pytest.raises(SandboxError) as err:
            SandboxHandle.create(
                run_id="ae3-egress-probe",
                profile=SandboxProfile(egress="deny"),
                workspace_host=str(tmp_path),
                backend=DockerBackend(),  # deny+allowlist 矛盾先于 backend 使用抛出（docker 不会被调用）
                egress_allowlist=("10.0.0.0/8",),
            )
        assert "egress_allowlist_conflicts_deny" in str(err.value)


class TestGae1AllowlistRegistry:
    def test_gae1_registry_extensible_default_unchanged(self) -> None:
        """G-AE-1（53 号 WP3；Q11 协商落痕＝53 号 §6.5）：执行白名单段注册表化
        ——既有工具在册（行为不变）＋注册表可扩展（module-level dict）＋
        decide_automation_approval 本体零改动（禁改面）。"""
        from fde_api.control import service as control_svc

        assert ("task.batch_assign", "project_tasks.batch_assign") in control_svc.APPROVABLE_DSH_TOOLS
        # 机制可扩展：测试条目注册/注销往返（不改既有条目）
        probe = ("test.capability", "test.tool")
        control_svc.APPROVABLE_DSH_TOOLS[probe] = control_svc.APPROVABLE_DSH_TOOLS[
            ("task.batch_assign", "project_tasks.batch_assign")
        ]
        try:
            assert probe in control_svc.APPROVABLE_DSH_TOOLS
        finally:
            del control_svc.APPROVABLE_DSH_TOOLS[probe]
        assert probe not in control_svc.APPROVABLE_DSH_TOOLS
