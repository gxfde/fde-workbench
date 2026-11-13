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
        url = f"{self.base_url}{path}"
        headers = self._headers(actor_id, org_id, project_id, idem)
        try:
            resp = requests.request(
                method, url, headers=headers, json=json_body, params=params, timeout=self.timeout
            )
        except (requests.ConnectionError, requests.Timeout) as exc:
            raise OntologyUnavailable(f"ontology runtime unreachable: {url}") from exc
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
        ontology_id: str,
        pinned_version_id: str,
        object_type_key: str,
        filter_expr: dict[str, Any] | None = None,
        limit: int = 50,
    ) -> dict[str, Any]:
        """S-13 版本固定对象引用查询（只返脱敏属性与 ObjectRef，不落库源明细）。"""
        body: dict[str, Any] = {
            "ontology_id": ontology_id,
            "pinned_version_id": pinned_version_id,
            "object_type_key": object_type_key,
            "limit": limit,
        }
        if filter_expr is not None:
            body["filter"] = filter_expr
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
        ontology_id: str,
        pinned_version_id: str,
        object_ref_id: str,
        relation_key: str,
        limit: int = 50,
    ) -> dict[str, Any]:
        """S-13 版本固定一跳关系查询（基于 ObjectRef 游走，禁止任意 SQL）。"""
        return self._request(
            "POST",
            "/api/v1/query/related",
            actor_id=actor_id,
            org_id=org_id,
            project_id=project_id,
            json_body={
                "ontology_id": ontology_id,
                "pinned_version_id": pinned_version_id,
                "object_ref_id": object_ref_id,
                "relation_key": relation_key,
                "limit": limit,
            },
        )

