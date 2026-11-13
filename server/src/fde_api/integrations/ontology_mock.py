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
        self._seed_manufacturing_domain()

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
        ontology_id: str,
        pinned_version_id: str,
        object_type_key: str,
        filter_expr: dict[str, Any] | None = None,
        limit: int = 50,
    ) -> dict[str, Any]:
        self._maybe_fault()
        if (ontology_id, pinned_version_id) not in self._versions:
            return {"code": "not_found", "message": "version not found", "_status": 404}
        rows = [
            {
                "object_ref_id": _ref_id(
                    org_id, ontology_id, pinned_version_id, object_type_key, "BATCH-202611-01"
                ),
                "object_type_key": object_type_key,
                "pinned_version_id": pinned_version_id,
                "display": "BATCH-202611-01",
                "properties": {
                    "batch_no": "BATCH-202611-01",
                    "operator_phone": "138****5678",
                },
            },
            {
                "object_ref_id": _ref_id(
                    org_id, ontology_id, pinned_version_id, object_type_key, "BATCH-202611-02"
                ),
                "object_type_key": object_type_key,
                "pinned_version_id": pinned_version_id,
                "display": "BATCH-202611-02",
                "properties": {
                    "batch_no": "BATCH-202611-02",
                    "operator_phone": "139****9999",
                },
            },
        ]
        return {
            "ontology_id": ontology_id,
            "pinned_version_id": pinned_version_id,
            "object_type_key": object_type_key,
            "items": rows[: max(1, limit)],
            "_status": 200,
        }

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
        self._maybe_fault()
        if (ontology_id, pinned_version_id) not in self._versions:
            return {"code": "not_found", "message": "version not found", "_status": 404}
        insp_ref = _ref_id(
            org_id, ontology_id, pinned_version_id, "inspection", "INSP-202611-001"
        )
        return {
            "ontology_id": ontology_id,
            "pinned_version_id": pinned_version_id,
            "source_object_ref_id": object_ref_id,
            "relation_key": relation_key,
            "items": [
                {
                    "object_ref_id": insp_ref,
                    "object_type_key": "inspection",
                    "pinned_version_id": pinned_version_id,
                    "display": "INSP-202611-001",
                    "properties": {
                        "inspection_id": "INSP-202611-001",
                        "batch_no": "BATCH-202611-01",
                        "result": "PASS",
                    },
                }
            ][: max(1, limit)],
            "_status": 200,
        }
