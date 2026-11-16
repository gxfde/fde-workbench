"""Ontology Runtime 薄客户端（V3.3 WP4 段 1；契约 = Fde-Ontology docs/v3.3/m1/ontology-integration-contract.md）。

职责（契约 §2）：注入 X-API-Key + 签名上下文头 + X-Idempotency-Key，
业务代码不手拼头；超时/5xx/降级语义见契约 §3。**本客户端不缓存本体
数据**（运行时数据一律以 pinned_version 查询）。

配置（env_prefix=FDE_，沿 config.py 惯例）：
- FDE_ONTOLOGY_ENABLED（默认 false：关闭时路由不挂载、discovery 不推候选）
- FDE_ONTOLOGY_BASE_URL
- FDE_ONTOLOGY_API_KEY / FDE_ONTOLOGY_SIGNING_KEY
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
import uuid
from typing import Any

import requests

DEFAULT_TIMEOUT_SECONDS = 10.0

# ---- 契约 §2-2 / §2-4：有界重试与熔断参数（M4 defer 清算） ----
MAX_GET_RETRIES = 2  # 幂等 GET 最多重试 2 次（共 3 次尝试）
RETRY_BACKOFF_SECONDS = (0.5, 1.0)
CIRCUIT_FAILURE_THRESHOLD = 5  # 连续 5 次失败 → 打开
CIRCUIT_RECOVERY_SECONDS = 30.0  # 打开 30s 后放行 1 次半开试探


class OntologyClientError(RuntimeError):
    """runtime 不可用/5xx——调用方按契约 §3 降级（只读功能降级，不阻塞主流程）。"""


class OntologyUnavailable(OntologyClientError):
    """连接失败/超时（契约 §3 依赖等级：审计最强=拒写，查询=降级空结果）。"""


class OntologyConflict(OntologyClientError):
    """runtime 409 base_conflict（契约 §2-5：并发/漂移冲突 → 业务层提示重试）。"""

    def __init__(self, body: dict[str, Any]) -> None:
        super().__init__(str(body.get("message", "ontology conflict")))
        self.body = body


class OntologyAuthError(OntologyClientError):
    """runtime 401/403（契约 §2-5：配置错误 → 告警，不自动重试）。"""

    def __init__(self, body: dict[str, Any]) -> None:
        super().__init__(f"ontology auth rejected: {body.get('message', '')}")
        self.body = body


def _b64e(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def build_context_header(
    actor_id: str,
    org_id: str,
    project_id: str,
    signing_key: str,
    *,
    ts: int | None = None,
    nonce: str | None = None,
) -> str:
    """与 runtime 侧参考实现同规格（base64url(json)+HMAC-SHA256）。"""
    payload = json.dumps(
        {
            "actor_id": actor_id,
            "org_id": org_id,
            "project_id": project_id,
            "ts": int(ts if ts is not None else time.time()),
            "nonce": nonce or secrets.token_hex(8),
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    raw = _b64e(payload.encode())
    sig = _b64e(hmac.new(signing_key.encode(), raw.encode(), hashlib.sha256).digest())
    return f"{raw}.{sig}"


class OntologyClient:
    """线程安全（requests.Session 非线程安全，按需创建；此处无状态）。"""

    def __init__(
        self,
        base_url: str,
        api_key: str,
        signing_key: str,
        *,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.signing_key = signing_key
        self.timeout = timeout
        # §2-4 熔断器状态（实例级；连续失败计数按 _request 调用粒度）
        self._failure_count = 0
        self._opened_at: float | None = None

    # ---- 熔断器（契约 §2-4）----

    def _breaker_check(self) -> None:
        """熔断打开期直接抛 OntologyUnavailable，不打真实请求；恢复窗口后放行半开试探。"""
        if self._opened_at is None:
            return
        elapsed = time.monotonic() - self._opened_at
        if elapsed < CIRCUIT_RECOVERY_SECONDS:
            raise OntologyUnavailable(
                f"ontology runtime circuit open for {CIRCUIT_RECOVERY_SECONDS - elapsed:.0f}s "
                "(circuit breaker §2-4)"
            )
        # 半开：放行 1 次试探（关闭 opened_at；试探失败会立即重新打开）

    def _breaker_record(self, failure: bool) -> None:
        if failure:
            self._failure_count += 1
            if self._failure_count >= CIRCUIT_FAILURE_THRESHOLD:
                self._opened_at = time.monotonic()
        else:
            self._failure_count = 0
            self._opened_at = None

    @property
    def breaker_state(self) -> str:
        """熔断态只读视图：closed | open | half_open（零副作用）。

        M5-WP2 消费方：``GateEvaluationReceipt`` 固化「求值瞬间熔断态」
        （D29）与 S-12「熔断窗口禁下调」——两者都只观察，不允许本视图改变
        任何状态（状态变更只发生在 _breaker_check/_breaker_record 请求路径）。
        """
        if self._opened_at is None:
            return "closed"
        if time.monotonic() - self._opened_at < CIRCUIT_RECOVERY_SECONDS:
            return "open"
        return "half_open"

    # ---- 有界重试（契约 §2-2）----

    def _attempt_with_retry(
        self,
        method: str,
        send: Any,
    ) -> dict[str, Any]:
        """幂等 GET 最多重试 2 次（退避 0.5s/1s）；写操作/4xx 语义错绝不重试。"""
        retries = MAX_GET_RETRIES if method.upper() == "GET" else 0
        for attempt in range(retries + 1):
            try:
                return send()
            except (OntologyConflict, OntologyAuthError):
                raise  # 4xx 语义错：调用方契约错，重试无意义（§2-2）
            except (requests.ConnectionError, requests.Timeout, OntologyClientError):
                # 瞬时网络故障/超时/5xx 对幂等 GET 重试（契约 §2-2：最多 2 次、
                # 退避 0.5s/1s）
                if attempt >= retries:
                    raise
                time.sleep(RETRY_BACKOFF_SECONDS[attempt])
        raise OntologyUnavailable("unreachable")  # pragma: no cover — 循环必 return/raise

    # ---- 核心请求（私有）----

    def _headers(self, actor_id: str, org_id: str, project_id: str, idem: str | None) -> dict[str, str]:
        headers = {
            "X-API-Key": self.api_key,
            "X-FDE-Context": build_context_header(actor_id, org_id, project_id, self.signing_key),
            "Content-Type": "application/json",
        }
        if idem:
            # runtime 对 >64 键 422 拒收（e9efb54 起），此处保证不超长：超长截断
            # 会使不同键互撞引发错误复放（评审 W-D），故按 sha256 收敛
            if len(idem) > 64:
                idem = "h-" + hashlib.sha256(idem.encode()).hexdigest()[:30]
            headers["X-Idempotency-Key"] = idem
        return headers

    def _request(
        self,
        method: str,
        path: str,
        *,
        actor_id: str,
        org_id: str,
        project_id: str,
        idem: str | None = None,
        json_body: dict[str, Any] | list[dict[str, Any]] | None = None,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self._breaker_check()
        url = f"{self.base_url}{path}"
        headers = self._headers(actor_id, org_id, project_id, idem)

        def send() -> dict[str, Any]:
            try:
                resp = requests.request(
                    method, url, headers=headers, json=json_body, params=params, timeout=self.timeout
                )
            except (requests.ConnectionError, requests.Timeout) as exc:
                # Vex 13:22 M6 放行条件(a)（S-07 边角闭环）：文案禁带内网 URL——该消息
                # 会经 integrations/service.py 管理面 5 处透出至报错面；拓扑细节只留异常链
                # （__cause__，服务端日志可见），不进对客/管理面文案。
                raise OntologyUnavailable("ontology runtime unreachable") from exc
            if resp.status_code >= 500:
                raise OntologyClientError(f"ontology runtime 5xx: {resp.status_code} {path}")
            body: dict[str, Any] = {}
            if resp.content:
                try:
                    decoded = resp.json()
                except ValueError:
                    decoded = {"raw": resp.text}
                # runtime 非对象体（数组/标量） defensively 包裹（评审 W-D）
                body = decoded if isinstance(decoded, dict) else {"raw": decoded}
            if resp.status_code == 409:
                raise OntologyConflict(body)
            if resp.status_code in (401, 403):
                raise OntologyAuthError(body)
            body["_status"] = resp.status_code
            return body

        try:
            body = self._attempt_with_retry(method, send)
        except (OntologyUnavailable, OntologyClientError):
            self._breaker_record(failure=True)
            raise
        except (OntologyConflict, OntologyAuthError):
            # 4xx 语义错：不重试、不计入熔断（服务在正常应答，是调用方契约错）
            self._breaker_record(failure=False)
            raise
        self._breaker_record(failure=False)
        return body

    # ---- M2 闭环方法（契约 §2 方法清单的 M2 子集）----

    def health(self) -> bool:
        try:
            resp = requests.get(f"{self.base_url}/healthz", timeout=self.timeout)
            return resp.status_code == 200
        except (requests.ConnectionError, requests.Timeout):
            return False

    def create_ontology(
        self, *, actor_id: str, org_id: str, project_id: str, domain_key: str, title: str, description: str = ""
    ) -> dict[str, Any]:
        idem = uuid.uuid4().hex
        return self._request(
            "POST", "/api/v1/ontologies", actor_id=actor_id, org_id=org_id, project_id=project_id,
            idem=idem, json_body={"domain_key": domain_key, "title": title, "description": description},
        )

    def issue_trustboard_delivery_link(
        self, *, actor_id: str, org_id: str, project_id: str, ontology_id: str
    ) -> dict[str, Any]:
        """向本体运行时签发 TrustBoard 客户只读看板交付链接（M6-WP6）。

        每次调用使用**新幂等键**：交付链接内嵌的是**一次性消费的交接令牌**
        （M6-WP6-R4 硬条件 12）——同一枚链接被客户打开一次即失效，换设备/浏览器
        须重新签发；复用幂等键会拿回同一枚已消费的链接，故此处不得复用。
        """
        idem = uuid.uuid4().hex
        return self._request(
            "POST", "/api/v1/ui/session", actor_id=actor_id, org_id=org_id, project_id=project_id,
            idem=idem, json_body={"ontology_id": ontology_id},
        )

    def submit_candidates(
        self,
        *,
        actor_id: str,
        org_id: str,
        project_id: str,
        ontology_id: str,
        title: str,
        items: list[dict[str, Any]],
        captured_from: str,
        description: str = "",
    ) -> dict[str, Any]:
        """discovery 候选直提（决议 2/D5/D6）。items 每条须含 §6.2 六件套（captured_from 条目）。"""
        # 内容寻址幂等：同候选重推=复放；纳入 ontology_id+title（评审 W-D：
        # 同 items 异目标复用键会重放错目标）
        idem = "cs-" + hashlib.sha256(
            json.dumps(
                {"ontology_id": ontology_id, "title": title, "items": items},
                sort_keys=True,
                ensure_ascii=False,
                default=str,
            ).encode()
        ).hexdigest()[:28]
        return self._request(
            "POST", f"/api/v1/ontologies/{ontology_id}/change-sets",
            actor_id=actor_id, org_id=org_id, project_id=project_id, idem=idem,
            json_body={"title": title, "description": description, "proposed_json": items, "captured_from": captured_from},
        )

    def validate_change_set(self, *, actor_id: str, org_id: str, project_id: str, change_set_id: str) -> dict[str, Any]:
        return self._request(
            "POST", f"/api/v1/change-sets/{change_set_id}/validate",
            actor_id=actor_id, org_id=org_id, project_id=project_id, idem=uuid.uuid4().hex,
        )

    def get_change_set(self, *, actor_id: str, org_id: str, project_id: str, change_set_id: str) -> dict[str, Any]:
        return self._request(
            "GET", f"/api/v1/change-sets/{change_set_id}",
            actor_id=actor_id, org_id=org_id, project_id=project_id,
        )

    def approve_change_set(
        self, *, actor_id: str, org_id: str, project_id: str, change_set_id: str,
        role: str, decision: str, comment: str = "", annotation_evidence_id: str | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {"role": role, "decision": decision, "comment": comment}
        if annotation_evidence_id:
            payload["annotation_evidence_id"] = annotation_evidence_id
        # 确定性幂等：含 decision（异决定重试不得复放首票，评审 W-D）
        idem = "ap-" + hashlib.sha256(
            f"{change_set_id}|{role}|{actor_id}|{decision}".encode()
        ).hexdigest()[:28]
        return self._request(
            "POST", f"/api/v1/change-sets/{change_set_id}/approvals",
            actor_id=actor_id, org_id=org_id, project_id=project_id, idem=idem, json_body=payload,
        )

    def publish(
        self, *, actor_id: str, org_id: str, project_id: str, change_set_id: str, version: str,
        confirm_breaking: bool = False,
    ) -> dict[str, Any]:
        idem = "pb-" + hashlib.sha256(
            f"{change_set_id}|{version}|{confirm_breaking}".encode()
        ).hexdigest()[:28]
        return self._request(
            "POST", f"/api/v1/change-sets/{change_set_id}/publish",
            actor_id=actor_id, org_id=org_id, project_id=project_id, idem=idem,
            json_body={"version": version, "confirm_breaking": confirm_breaking},
        )

    def get_version_snapshot(
        self, *, actor_id: str, org_id: str, project_id: str, ontology_id: str, version_id: str
    ) -> dict[str, Any]:
        """S-13 版本固定读取：Agent/Workflow 一律读快照并校验 ETag。"""
        return self._request(
            "GET", f"/api/v1/ontologies/{ontology_id}/versions/{version_id}/snapshot",
            actor_id=actor_id, org_id=org_id, project_id=project_id,
        )

    # ---- M3 数据接地与血缘只读方法（契约 §7 增量方法）----

    def check_grounding(
        self,
        *,
        actor_id: str,
        org_id: str,
        project_id: str,
        ontology_id: str,
        version_id: str,
        object_type_key: str,
    ) -> dict[str, Any]:
        """D21：触发指定已发布版本下对象类型的接地数据质量检查（§14-9 四类必检）。"""
        return self._request(
            "POST",
            f"/api/v1/ontologies/{ontology_id}/versions/{version_id}/grounding/{object_type_key}/check",
            actor_id=actor_id,
            org_id=org_id,
            project_id=project_id,
            idem=uuid.uuid4().hex,
        )

    def get_lineage(
        self,
        *,
        actor_id: str,
        org_id: str,
        project_id: str,
        ontology_id: str,
        version_id: str,
        object_type: str | None = None,
        object_ref_id: str | None = None,
    ) -> dict[str, Any]:
        """D21 / ADR §5：查询版本双层血缘（定义血缘 + 可选对象实例引用追溯）。"""
        params: dict[str, Any] = {}
        if object_type:
            params["object_type"] = object_type
        if object_ref_id:
            params["object_ref_id"] = object_ref_id
        return self._request(
            "GET",
            f"/api/v1/ontologies/{ontology_id}/versions/{version_id}/lineage",
            actor_id=actor_id,
            org_id=org_id,
            project_id=project_id,
            params=params or None,
        )

    def query_objects(
        self,
        *,
        actor_id: str,
        org_id: str,
        project_id: str,
        pinned_version_id: str,
        object_type_id: str,
        filters: dict[str, Any] | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        """S-13 版本固定对象引用查询（对齐 runtime QueryObjectsInput：object_type_id
        + filters AST，extra=forbid，不送 ontology_id/别名键）。"""
        body: dict[str, Any] = {
            "object_type_id": object_type_id,
            "pinned_version_id": pinned_version_id,
            "limit": limit,
            "offset": offset,
        }
        if filters is not None:
            body["filters"] = filters
        return self._request(
            "POST",
            "/api/v1/query/objects",
            actor_id=actor_id,
            org_id=org_id,
            project_id=project_id,
            json_body=body,
        )

    def query_related(
        self,
        *,
        actor_id: str,
        org_id: str,
        project_id: str,
        pinned_version_id: str,
        object_ref_id: str,
        relation_key: str,
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        """S-13 版本固定一跳关系查询（对齐 runtime QueryRelatedInput：
        object_ref_id + relation_key + pinned_version_id，禁任意 SQL）。"""
        return self._request(
            "POST",
            "/api/v1/query/related",
            actor_id=actor_id,
            org_id=org_id,
            project_id=project_id,
            json_body={
                "object_ref_id": object_ref_id,
                "relation_key": relation_key,
                "pinned_version_id": pinned_version_id,
                "limit": limit,
                "offset": offset,
            },
        )

    # ---- M4 Logic / Action 方法（冻结契约 D28 形态）----

    def run_logic(
        self,
        *,
        actor_id: str,
        org_id: str,
        project_id: str,
        ontology_id: str,
        version_id: str,
        logic_key: str,
        input_payload: dict[str, Any] | None,
    ) -> dict[str, Any]:
        """D24 / §8.1：按固定版本执行受限声明式 Logic（S-13；Schema 由 runtime 强校验）。"""
        return self._request(
            "POST",
            f"/api/v1/logic/{logic_key}/run",
            actor_id=actor_id,
            org_id=org_id,
            project_id=project_id,
            idem=uuid.uuid4().hex,
            json_body={"pinned_version_id": version_id, "input": input_payload},
        )

    def propose_action(
        self,
        *,
        actor_id: str,
        org_id: str,
        project_id: str,
        ontology_id: str,
        action_key: str,
        version_id: str,
        input_payload: dict[str, Any] | None,
    ) -> dict[str, Any]:
        """D25/D28：提议受控动作（runtime 默认 dry-run 出 dry_run_result，零副作用）。"""
        return self._request(
            "POST",
            f"/api/v1/actions/{action_key}/propose",
            actor_id=actor_id,
            org_id=org_id,
            project_id=project_id,
            idem=uuid.uuid4().hex,
            json_body={"pinned_version_id": version_id, "input": input_payload},
        )

    def dry_validate_change_set(
        self,
        *,
        actor_id: str,
        org_id: str,
        project_id: str,
        ontology_id: str,
        version_id: str,
        proposed_json: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """AF0-C1 / api-spec 1.3.6-af0：纯候选预检（零状态变更只读校验）。

        verdict/violations/conflicting_entities 以 200 结果返回（violations 是
        结果不是 HTTP 错误）；无幂等域——契约不要求 X-Idempotency-Key（零副
        作用）。ontology_id/pinned_version 由调用方服务端从项目绑定注入
        （S-13），本方法不接受调用方自报版本。proposed_json 为候选条目数组
        （与 ChangeSet.proposed_json 同形；WP1 收口批随实装对齐，原对象形状
        会被真服务 422 拒收）。
        """
        return self._request(
            "POST",
            "/api/v1/mcp/tools/dry_validate_change_set",
            actor_id=actor_id,
            org_id=org_id,
            project_id=project_id,
            idem=None,
            json_body={
                "ontology_id": ontology_id,
                "pinned_version": version_id,
                "proposed_json": proposed_json,
            },
        )

    def approve_action(
        self,
        *,
        actor_id: str,
        org_id: str,
        project_id: str,
        ontology_id: str,
        request_id: str,
        role: str,
        decision: str,
        comment: str | None = None,
    ) -> dict[str, Any]:
        """D28 / 红线 6：审批子表（I4 自批由 runtime 403 强制；rejected 即终态）。"""
        payload: dict[str, Any] = {"role": role, "decision": decision}
        if comment:
            payload["comment"] = comment
        return self._request(
            "POST",
            f"/api/v1/action-requests/{request_id}/approvals",
            actor_id=actor_id,
            org_id=org_id,
            project_id=project_id,
            idem=uuid.uuid4().hex,
            json_body=payload,
        )

    def get_action_request(
        self,
        *,
        actor_id: str,
        org_id: str,
        project_id: str,
        ontology_id: str,
        request_id: str,
    ) -> dict[str, Any]:
        """D28：查询 ActionRequest 状态机当前态 + 审批留痕。"""
        return self._request(
            "GET",
            f"/api/v1/action-requests/{request_id}",
            actor_id=actor_id,
            org_id=org_id,
            project_id=project_id,
        )

    def execute_action(
        self,
        *,
        actor_id: str,
        org_id: str,
        project_id: str,
        ontology_id: str,
        action_key: str,
        request_id: str,
    ) -> dict[str, Any]:
        """D28 / §13 M4 条 6：仅 approved 可执行（runtime 强制；执行前重验 S-13）。"""
        return self._request(
            "POST",
            f"/api/v1/actions/{action_key}/execute",
            actor_id=actor_id,
            org_id=org_id,
            project_id=project_id,
            idem=uuid.uuid4().hex,
            json_body={"request_id": request_id},
        )

    # ---- M5 治理只读方法（契约 §9.1，D29/D31/D32/D33）----

    def get_version_impact(
        self,
        *,
        actor_id: str,
        org_id: str,
        project_id: str,
        ontology_id: str,
        from_ver: str,
        to_ver: str,
    ) -> dict[str, Any]:
        """D29/D32：纯 Schema 级升级影响分析（Breaking/Additive + D32 分离指纹；
        S-07 零句柄回显——报告只含实体标识与字段名）。零项目态耦合（Workbench
        侧治理服务在本地聚合爆炸半径）。"""
        return self._request(
            "GET",
            f"/api/v1/ontologies/{ontology_id}/versions/{from_ver}/impact/{to_ver}",
            actor_id=actor_id,
            org_id=org_id,
            project_id=project_id,
        )

    def get_version_governance_summary(
        self,
        *,
        actor_id: str,
        org_id: str,
        project_id: str,
        ontology_id: str,
        version_id: str,
        as_of: str | None = None,
    ) -> dict[str, Any]:
        """D31/D32：版本治理完整度摘要（缺口 + <0.8/冲突候选 100% 处置闭环 +
        72h SLA 账龄 + 编译器遥测解耦）。as_of 为可选 ISO-8601 UTC 时刻。"""
        params: dict[str, Any] | None = {"as_of": as_of} if as_of else None
        return self._request(
            "GET",
            f"/api/v1/ontologies/{ontology_id}/versions/{version_id}/governance-summary",
            actor_id=actor_id,
            org_id=org_id,
            project_id=project_id,
            params=params,
        )

    def reconcile_references(
        self,
        *,
        actor_id: str,
        org_id: str,
        project_id: str,
        references: list[dict[str, Any]],
        cutover_at: str | None = None,
        idem_key: str,
    ) -> dict[str, Any]:
        """D33：双独立 PG 恢复切点 T 只读跨库引用对账（逐条七态分类）。
        idem_key 必带——同批引用重放复用同键（恢复演练重跑幂等）。"""
        body: dict[str, Any] = {"references": references}
        if cutover_at is not None:
            body["cutover_at"] = cutover_at
        return self._request(
            "POST",
            "/api/v1/maintenance/reconcile-references",
            actor_id=actor_id,
            org_id=org_id,
            project_id=project_id,
            idem=idem_key,
            json_body=body,
        )

