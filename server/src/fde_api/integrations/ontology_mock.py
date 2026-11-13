"""V3.3 MockOntologyAdapter（集成契约 §4 + §7，满足任务书 §14-2 同契约测试）。

职责：
- 提供与 OntologyClient 完全一致的公开方法签名、返回结构（含 `_status`）与异常层级；
- 内置 ChangeSet 状态机（draft → submitted → approved → published）与同一本体单锁 409 `base_conflict`；
- 预置制造业质量追溯种子（product / batch / inspection / defect）及 M3 数据接地/血缘/引用查询响应；
- 支持故障注入（延迟 / 不可达 / 5xx / 鉴权失败），支撑 §14-4 与前端/单测离线验证。
"""

from __future__ import annotations

import hashlib
import time
import uuid
from datetime import UTC, datetime
from typing import Any

from fde_api.integrations.ontology_client import (
    OntologyAuthError,
    OntologyClientError,
    OntologyConflict,
    OntologyUnavailable,
)

SEED_ONTOLOGY_ID = "ont-seed-mfg"
SEED_VERSION_ID = "ver-seed-1-0-0"


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _ref_id(org_id: str, ontology_id: str, version_id: str, ot_key: str, pk_val: str) -> str:
    raw = f"{org_id}:{ontology_id}:{version_id}:{ot_key}:{pk_val}"
    return "ref-" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


class MockOntologyAdapter:
    """与 OntologyClient 同签名的内存态契约适配器。"""

    def __init__(self) -> None:
        self._fault_mode: str | None = None
        self._latency_ms: int = 0
        self._ontologies: dict[str, dict[str, Any]] = {}
        self._change_sets: dict[str, dict[str, Any]] = {}
        self._locked_by_ontology: dict[str, str] = {}
        self._versions: dict[tuple[str, str], dict[str, Any]] = {}
        self._action_requests: dict[str, dict[str, Any]] = {}
        self._action_approvals: dict[str, list[dict[str, Any]]] = {}
        self._action_seq: int = 0
        self._seed_manufacturing_domain()
        self._seed_m4_logic_and_materialization()

    def inject_fault(self, mode: str | None, *, latency_ms: int = 0) -> None:
        """注入故障：`None` | `'unavailable'` | `'5xx'` | `'auth'` | `'conflict'`。"""
        self._fault_mode = mode
        self._latency_ms = max(0, latency_ms)

    def clear_fault(self) -> None:
        self._fault_mode = None
        self._latency_ms = 0

    def _maybe_fault(self) -> None:
        if self._latency_ms > 0:
            time.sleep(self._latency_ms / 1000.0)
        if self._fault_mode == "unavailable":
            raise OntologyUnavailable("mock injected runtime unavailable")
        if self._fault_mode == "5xx":
            raise OntologyClientError("mock injected runtime 5xx")
        if self._fault_mode == "auth":
            raise OntologyAuthError({"code": "unauthorized", "message": "mock auth error"})
        if self._fault_mode == "conflict":
            raise OntologyConflict({"code": "base_conflict", "message": "mock conflict"})

    def _seed_manufacturing_domain(self) -> None:
        self._ontologies[SEED_ONTOLOGY_ID] = {
            "id": SEED_ONTOLOGY_ID,
            "org_id": "org-1",
            "project_id": "proj-1",
            "domain_key": "mfg_quality",
            "title": "制造业质量追溯本体",
            "description": "预置种子：product / batch / inspection / defect",
        }
        snapshot = {
            "version": "1.0.0",
            "object_types": [
                {"key": "product", "title": "产品", "pk_key": "product_code"},
                {"key": "batch", "title": "生产批次", "pk_key": "batch_no"},
                {"key": "inspection", "title": "质检单", "pk_key": "inspection_id"},
                {"key": "defect", "title": "缺陷记录", "pk_key": "defect_id"},
            ],
            "relation_types": [
                {
                    "key": "batch_has_inspection",
                    "from_key": "batch",
                    "to_key": "inspection",
                    "cardinality": "1:n",
                },
                {
                    "key": "inspection_has_defect",
                    "from_key": "inspection",
                    "to_key": "defect",
                    "cardinality": "1:n",
                },
            ],
            "data_sources": [
                {
                    "id": "ds-seed-mes",
                    "key": "mes_readonly_pg",
                    "kind": "postgres",
                    "connection_ref": "env://FDE_MES_READONLY_DSN",
                    "read_only": True,
                }
            ],
            "object_bindings": [
                {
                    "id": "ob-seed-batch",
                    "object_type_key": "batch",
                    "data_source_key": "mes_readonly_pg",
                    "source_locator": "mes.production_batches",
                    "pk_column": "batch_no",
                    "field_mappings": [
                        {
                            "property_key": "batch_no",
                            "source_field": "batch_no",
                            "transform": "trim",
                            "mask_policy": "none",
                        },
                        {
                            "property_key": "operator_phone",
                            "source_field": "operator_phone",
                            "transform": "trim",
                            "mask_policy": "partial",
                        },
                    ],
                }
            ],
        }
        raw = repr(snapshot).encode("utf-8")
        etag = f'"{hashlib.sha256(raw).hexdigest()}"'
        self._versions[(SEED_ONTOLOGY_ID, SEED_VERSION_ID)] = {
            "id": SEED_VERSION_ID,
            "ontology_id": SEED_ONTOLOGY_ID,
            "version": "1.0.0",
            "etag": etag,
            "snapshot": snapshot,
            "published_at": _now_iso(),
        }

    def _seed_m4_logic_and_materialization(self) -> None:
        """M4 种子：trace_scope Logic + 受控物化 batch/BATCH-001（D24/D25 契约面）。"""
        self._logics: dict[str, dict[str, Any]] = {
            "trace_scope": {
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "planned_qty": {"type": "number"},
                        "stock_qty": {"type": "number"},
                        "defect_rate": {"type": "number"},
                    },
                    "required": ["planned_qty", "stock_qty", "defect_rate"],
                },
                "output_type": "number",
                "fn": lambda x: (
                    min(x["planned_qty"], x["stock_qty"]) if x["defect_rate"] < 0.05 else 0
                ),
            }
        }
        self._materialized: dict[tuple[str, str, str], dict[str, Any]] = {
            (SEED_VERSION_ID, "batch", "BATCH-001"): {
                "expires_at": _now_iso(),
                "payload_masked": {"batch_no": "B***01"},
            }
        }

    def _action_view(self, req: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": req["id"],
            "org_id": req["org_id"],
            "ontology_id": req["ontology_id"],
            "pinned_version_id": req["pinned_version_id"],
            "action_definition_id": req["action_key"],
            "action_kind": req["action_key"],
            "status": req["status"],
            "requested_by_user_id": req["requested_by_user_id"],
            "dry_run_result": req.get("dry_run_result"),
            "approvals": list(self._action_approvals.get(req["id"], [])),
            "idempotency_key": req.get("idempotency_key"),
            "executed_at": req.get("executed_at"),
            "pre_snapshot": req.get("pre_snapshot"),
            "post_snapshot": req.get("post_snapshot"),
            "compensation": req.get("compensation"),
            "error_text": req.get("error_text"),
            "created_at": req.get("created_at"),
        }

    # ---- M4 方法（D28 冻结契约形态）----

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
        self._maybe_fault()
        spec = self._logics.get(logic_key)
        if spec is None:
            return {
                "_status": 404,
                "code": "not_found",
                "message": "logic not found in pinned version",
            }
        values = input_payload if isinstance(input_payload, dict) else {}
        for name in spec["input_schema"].get("required", []):
            if name not in values:
                return {
                    "_status": 422,
                    "code": "validation_failed",
                    "message": f"missing required input field: {name}",
                }
        props = spec["input_schema"].get("properties", {})
        for name in values:
            if name not in props:
                return {
                    "_status": 422,
                    "code": "validation_failed",
                    "message": f"unknown input field: {name}",
                }
        result = spec["fn"](values)
        return {
            "_status": 200,
            "logic_key": logic_key,
            "ontology_id": ontology_id,
            "pinned_version_id": version_id,
            "result": result,
        }

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
        self._maybe_fault()
        if action_key != "retention_extension":
            return {
                "_status": 422,
                "code": "validation_failed",
                "message": f"unknown action_key {action_key!r}",
            }
        values = input_payload if isinstance(input_payload, dict) else {}
        ot_key = str(values.get("object_type_key", ""))
        pk_val = str(values.get("external_pk_value", ""))
        ttl = values.get("ttl_seconds")
        if (
            not ot_key
            or not pk_val
            or isinstance(ttl, bool)
            or not isinstance(ttl, int)
            or not (60 <= ttl <= 86400 * 30)
        ):
            return {
                "_status": 422,
                "code": "validation_failed",
                "message": "invalid retention_extension input",
            }
        mat = self._materialized.get((version_id, ot_key, pk_val))
        if mat is None:
            return {
                "_status": 404,
                "code": "not_found",
                "message": "materialized object not found in pinned version",
            }
        self._action_seq += 1
        req_id = f"act-req-{self._action_seq:04d}"
        dry = {"simulated": True, "extended_by_seconds": ttl, "expires_at": mat["expires_at"]}
        req: dict[str, Any] = {
            "id": req_id,
            "org_id": org_id,
            "ontology_id": ontology_id,
            "pinned_version_id": version_id,
            "action_key": action_key,
            "status": "pending",
            "requested_by_user_id": actor_id,
            "dry_run_result": dry,
            "input_payload": values,
            "created_at": _now_iso(),
        }
        self._action_requests[req_id] = req
        self._action_approvals[req_id] = []
        return {"_status": 201, **self._action_view(req)}

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
        self._maybe_fault()
        req = self._action_requests.get(request_id)
        if req is None:
            return {"_status": 404, "code": "not_found", "message": "action request not found"}
        if req["status"] != "pending":
            return {
                "_status": 409,
                "code": "base_conflict",
                "message": f"status={req['status']}; only pending approvable",
            }
        if actor_id == req["requested_by_user_id"]:
            return {
                "_status": 403,
                "code": "forbidden",
                "message": "requester cannot approve own action request (I4)",
            }
        if role not in ("business_owner", "model_consultant", "data_owner", "risk"):
            return {"_status": 422, "code": "validation_failed", "message": "invalid role"}
        if decision not in ("approved", "rejected"):
            return {
                "_status": 422,
                "code": "validation_failed",
                "message": "decision must be approved|rejected",
            }
        self._action_approvals[request_id].append(
            {"role": role, "reviewer_user_id": actor_id, "decision": decision, "comment": comment}
        )
        req["status"] = "rejected" if decision == "rejected" else "approved"
        return {"_status": 200, **self._action_view(req)}

    def get_action_request(
        self, *, actor_id: str, org_id: str, project_id: str, ontology_id: str, request_id: str
    ) -> dict[str, Any]:
        self._maybe_fault()
        req = self._action_requests.get(request_id)
        if req is None:
            return {"_status": 404, "code": "not_found", "message": "action request not found"}
        return {"_status": 200, **self._action_view(req)}

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
        self._maybe_fault()
        req = self._action_requests.get(request_id)
        if req is None:
            return {"_status": 404, "code": "not_found", "message": "action request not found"}
        if req["status"] == "pending":
            return {
                "_status": 409,
                "code": "approval_required",
                "message": "action request requires human approval before execution",
            }
        if req["status"] != "approved":
            return {
                "_status": 409,
                "code": "base_conflict",
                "message": f"status={req['status']}; only approved executable",
            }
        values = req["input_payload"]
        mat_key = (
            req["pinned_version_id"],
            str(values["object_type_key"]),
            str(values["external_pk_value"]),
        )
        mat = self._materialized.get(mat_key)
        if mat is None:
            req["status"] = "failed"
            req["error_text"] = "not_found: materialized object missing at execute time"
            req["compensation"] = {"reversible": False}
            return {"_status": 200, **self._action_view(req)}
        prev = mat["expires_at"]
        new_iso = _now_iso()
        req["status"] = "executing"
        req["pre_snapshot"] = {
            "expires_at": prev,
            "object_type_key": values["object_type_key"],
            "external_pk_value": values["external_pk_value"],
        }
        req["post_snapshot"] = {"expires_at": new_iso}
        req["compensation"] = {"previous_expires_at": prev, "reversible": True}
        req["dry_run_result"] = {
            "simulated": False,
            "extended_by_seconds": values["ttl_seconds"],
            "expires_at": new_iso,
        }
        req["executed_at"] = new_iso
        mat["expires_at"] = new_iso
        req["status"] = "completed"
        return {"_status": 200, **self._action_view(req)}

    # ---- M2 方法 ----


    def health(self) -> bool:
        if self._fault_mode == "unavailable":
            return False
        return True

    def create_ontology(
        self,
        *,
        actor_id: str,
        org_id: str,
        project_id: str,
        domain_key: str,
        title: str,
        description: str = "",
    ) -> dict[str, Any]:
        self._maybe_fault()
        ont_id = f"ont-{uuid.uuid4().hex[:12]}"
        rec = {
            "id": ont_id,
            "org_id": org_id,
            "project_id": project_id,
            "domain_key": domain_key,
            "title": title,
            "description": description,
            "created_by": actor_id,
            "_status": 201,
        }
        self._ontologies[ont_id] = rec
        return dict(rec)

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
        self._maybe_fault()
        cs_id = f"cs-{uuid.uuid4().hex[:12]}"
        rec = {
            "id": cs_id,
            "ontology_id": ontology_id,
            "org_id": org_id,
            "project_id": project_id,
            "title": title,
            "description": description,
            "status": "draft",
            "proposed_json": list(items),
            "captured_from": captured_from,
            "approvals": {},
            "created_by": actor_id,
            "_status": 201,
        }
        self._change_sets[cs_id] = rec
        return dict(rec)

    def validate_change_set(
        self, *, actor_id: str, org_id: str, project_id: str, change_set_id: str
    ) -> dict[str, Any]:
        self._maybe_fault()
        cs = self._change_sets.get(change_set_id)
        if cs is None:
            return {"code": "not_found", "message": "change set not found", "_status": 404}
        ont_id = cs["ontology_id"]
        locked = self._locked_by_ontology.get(ont_id)
        if locked is not None and locked != change_set_id:
            raise OntologyConflict(
                {
                    "code": "base_conflict",
                    "message": f"ontology {ont_id} already has locked change_set {locked}",
                }
            )
        self._locked_by_ontology[ont_id] = change_set_id
        cs["status"] = "submitted"
        return {
            "change_set_id": change_set_id,
            "status": "submitted",
            "valid": True,
            "errors": [],
            "_status": 200,
        }

    def get_change_set(
        self, *, actor_id: str, org_id: str, project_id: str, change_set_id: str
    ) -> dict[str, Any]:
        self._maybe_fault()
        cs = self._change_sets.get(change_set_id)
        if cs is None:
            return {"code": "not_found", "message": "change set not found", "_status": 404}
        out = dict(cs)
        out["_status"] = 200
        return out

    def approve_change_set(
        self,
        *,
        actor_id: str,
        org_id: str,
        project_id: str,
        change_set_id: str,
        role: str,
        decision: str,
        comment: str = "",
        annotation_evidence_id: str | None = None,
    ) -> dict[str, Any]:
        self._maybe_fault()
        cs = self._change_sets.get(change_set_id)
        if cs is None:
            return {"code": "not_found", "message": "change set not found", "_status": 404}
        cs["approvals"][role] = {
            "actor_id": actor_id,
            "decision": decision,
            "comment": comment,
            "annotation_evidence_id": annotation_evidence_id,
        }
        if {"fde", "business_owner", "data_steward"}.issubset(cs["approvals"].keys()) and all(
            v["decision"] == "approved" for v in cs["approvals"].values()
        ):
            cs["status"] = "approved"
        return {
            "change_set_id": change_set_id,
            "status": cs["status"],
            "role": role,
            "decision": decision,
            "_status": 200,
        }

    def publish(
        self,
        *,
        actor_id: str,
        org_id: str,
        project_id: str,
        change_set_id: str,
        version: str,
        confirm_breaking: bool = False,
    ) -> dict[str, Any]:
        self._maybe_fault()
        cs = self._change_sets.get(change_set_id)
        if cs is None:
            return {"code": "not_found", "message": "change set not found", "_status": 404}
        # 与 runtime 同契约：publish 仅接受 approved 状态（否则 409 base_conflict）
        if cs["status"] != "approved":
            raise OntologyConflict(
                {"code": "base_conflict", "message": f"publish requires approved (now={cs['status']})"}
            )
        ont_id = cs["ontology_id"]
        ver_id = f"ver-{uuid.uuid4().hex[:12]}"
        snapshot = {"version": version, "items": cs["proposed_json"]}
        etag = f'"{hashlib.sha256(repr(snapshot).encode()).hexdigest()}"'
        ver_rec = {
            "id": ver_id,
            "ontology_id": ont_id,
            "version": version,
            "etag": etag,
            "snapshot": snapshot,
            "published_at": _now_iso(),
            "_status": 201,
        }
        self._versions[(ont_id, ver_id)] = ver_rec
        cs["status"] = "published"
        if self._locked_by_ontology.get(ont_id) == change_set_id:
            del self._locked_by_ontology[ont_id]
        return dict(ver_rec)

    def get_version_snapshot(
        self,
        *,
        actor_id: str,
        org_id: str,
        project_id: str,
        ontology_id: str,
        version_id: str,
    ) -> dict[str, Any]:
        self._maybe_fault()
        ver = self._versions.get((ontology_id, version_id))
        if ver is None:
            return {"code": "not_found", "message": "version not found", "_status": 404}
        return {
            "id": ver["id"],
            "ontology_id": ver["ontology_id"],
            "version": ver["version"],
            "etag": ver["etag"],
            "snapshot": ver["snapshot"],
            "_status": 200,
        }

    # ---- M3 数据接地与血缘方法 ----

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
        self._maybe_fault()
        if (ontology_id, version_id) not in self._versions:
            return {"code": "not_found", "message": "version not found", "_status": 404}
        valid_keys = {"product", "batch", "inspection", "defect"}
        if ontology_id == SEED_ONTOLOGY_ID and object_type_key not in valid_keys:
            return {"code": "not_found", "message": "object_type not bound", "_status": 404}
        return {
            "ontology_id": ontology_id,
            "version_id": version_id,
            "object_type_key": object_type_key,
            "total_rows": 2,
            "valid_rows": 2,
            "passed": True,
            "null_required_count": 0,
            "duplicate_pk_count": 0,
            "type_error_count": 0,
            "missing_pk_count": 0,
            "anomalies": [],
            "checked_at": _now_iso(),
            "_status": 200,
        }

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
        self._maybe_fault()
        if (ontology_id, version_id) not in self._versions:
            return {"code": "not_found", "message": "version not found", "_status": 404}
        def_lineage = [
            {
                "object_type_key": object_type or "batch",
                "binding_id": "ob-seed-batch",
                "data_source_key": "mes_readonly_pg",
                "data_source_kind": "postgres",
                "connection_ref": "env://FDE_MES_READONLY_DSN",
                "read_only": True,
                "source_locator": "mes.production_batches",
                "pk_column": "batch_no",
                "captured_from": "discovery:cand-seed-batch",
                "field_lineage": [
                    {
                        "property_key": "batch_no",
                        "source_field": "batch_no",
                        "transform": "trim",
                        "mask_policy": "none",
                        "captured_from": "discovery:cand-seed-batch",
                    },
                    {
                        "property_key": "operator_phone",
                        "source_field": "operator_phone",
                        "transform": "trim",
                        "mask_policy": "partial",
                        "captured_from": "discovery:cand-seed-batch",
                    },
                ],
            }
        ]
        inst_lineage: list[dict[str, Any]] = []
        ref_trace: dict[str, Any] | None = None
        if object_ref_id:
            pk_hash = hashlib.sha256(b"BATCH-202611-01").hexdigest()
            ref_trace = {
                "object_ref_id": object_ref_id,
                "object_type_key": object_type or "batch",
                "external_pk_sha256": pk_hash,
                "data_source_key": "mes_readonly_pg",
                "data_source_kind": "postgres",
                "connection_ref": "env://FDE_MES_READONLY_DSN",
                "source_locator": "mes.production_batches",
                "pinned_version_id": version_id,
            }
            inst_lineage.append(ref_trace)
        return {
            "ontology_id": ontology_id,
            "version_id": version_id,
            "version": "1.0.0",
            "definition_lineage": def_lineage,
            "instance_lineage": inst_lineage,
            "instance_ref_trace": ref_trace,
            "_status": 200,
        }

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
        self._maybe_fault()
        if (SEED_ONTOLOGY_ID, pinned_version_id) not in self._versions:
            return {"code": "not_found", "message": "version not found", "_status": 404}
        rows = [
            {
                "object_ref_id": _ref_id(
                    org_id, SEED_ONTOLOGY_ID, pinned_version_id, object_type_id, "BATCH-202611-01"
                ),
                "object_type_id": object_type_id,
                "pinned_version_id": pinned_version_id,
                "display": "BATCH-202611-01",
                "properties": {
                    "batch_no": "BATCH-202611-01",
                    "operator_phone": "138****5678",
                },
            },
            {
                "object_ref_id": _ref_id(
                    org_id, SEED_ONTOLOGY_ID, pinned_version_id, object_type_id, "BATCH-202611-02"
                ),
                "object_type_id": object_type_id,
                "pinned_version_id": pinned_version_id,
                "display": "BATCH-202611-02",
                "properties": {
                    "batch_no": "BATCH-202611-02",
                    "operator_phone": "139****9999",
                },
            },
        ]
        return {
            "pinned_version_id": pinned_version_id,
            "object_type_id": object_type_id,
            "items": rows[offset : offset + max(1, limit)],
            "_status": 200,
        }

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
        self._maybe_fault()
        if (SEED_ONTOLOGY_ID, pinned_version_id) not in self._versions:
            return {"code": "not_found", "message": "version not found", "_status": 404}
        insp_ref = _ref_id(
            org_id, SEED_ONTOLOGY_ID, pinned_version_id, "inspection", "INSP-202611-001"
        )
        return {
            "pinned_version_id": pinned_version_id,
            "source_object_ref_id": object_ref_id,
            "relation_key": relation_key,
            "items": [
                {
                    "object_ref_id": insp_ref,
                    "object_type_id": "inspection",
                    "pinned_version_id": pinned_version_id,
                    "display": "INSP-202611-001",
                    "properties": {
                        "inspection_id": "INSP-202611-001",
                        "batch_no": "BATCH-202611-01",
                        "result": "PASS",
                    },
                }
            ][offset : offset + max(1, limit)],
            "_status": 200,
        }
