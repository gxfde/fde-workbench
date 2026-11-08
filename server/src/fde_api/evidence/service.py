"""证据登记服务（V3 T-E1；设计 ontology-registry-v1 §3/§4）。

- ``upsert_evidence``：会话内幂等登记——同 (project, source_uri, sha256) 指纹已
  有则原样返回（证据不可变：不改写 origin / captured_from），否则新建；并发撞
  唯一约束时在保存点内回退后重读，不把 IntegrityError 抛给调用方。
- ``register_evidence`` / ``list_evidence``：HTTP 面。写路径 can_manage（真人会
  话），读路径 can_view；登记路径有意不进 api_catalog（AI 不可写证据，与 signoff
  同纪律）。``referenced_by=gate:G5`` 反查门禁清单项挂接的证据（T-E2 唯一引用方）。
- ``execution_facts``（借鉴登记 #9，只读执行事实链）：三源时间线归并——
  project_evidence（项目维度）＋ operation_events（项目维度）＋ ai_call_audits
  （**账号维度**：该表无项目外键，只能按 actor 归并，响应明示 scope=actor，
  不得假装项目维度）。外部完成无真实回执＝未知，模型自述不作完成证据。
"""
from __future__ import annotations

import re
from typing import Any, Mapping

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from fde_api.auth.models import User
from fde_api.evidence.models import CAPTURED_FROM_PREFIXES, EVIDENCE_KINDS, ProjectEvidence
from fde_api.extensions import db
from fde_api.projects.events import record_event
from fde_api.projects.permissions import project_access
from fde_api.workbench.models import AICallAudit, Gate, OperationEvent, Project

_HEX64_PATTERN = re.compile(r"[0-9a-fA-F]{64}")
_GATE_REF_PATTERN = re.compile(r"gate:(G[1-9])")
_REGISTER_FIELDS = {"kind", "source_uri", "content_sha256", "origin", "captured_from"}
_ORIGIN_MAX_LENGTH = 2000


class EvidenceServiceError(Exception):
    def __init__(self, code: str, message: str, status: int):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


# ---------------------------------------------------------------------------
# 输入归一化（HTTP 面与内部调用共用）
# ---------------------------------------------------------------------------


def normalize_sha256(value: object) -> str:
    if not isinstance(value, str) or not _HEX64_PATTERN.fullmatch(value.strip()):
        raise EvidenceServiceError(
            "invalid_sha256", "content_sha256 必须是 64 位十六进制 sha256。", 400
        )
    return value.strip().lower()


def normalize_kind(value: object) -> str:
    if not isinstance(value, str) or value not in EVIDENCE_KINDS:
        raise EvidenceServiceError(
            "invalid_request", f"kind 仅可为 {'/'.join(EVIDENCE_KINDS)}。", 400
        )
    return value


def normalize_source_uri(value: object) -> str:
    if not isinstance(value, str) or not 0 < len(value.strip()) <= 500:
        raise EvidenceServiceError(
            "invalid_request", "source_uri 必须是 1–500 字符的出处指针。", 400
        )
    return value.strip()


def normalize_origin(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or len(value) > _ORIGIN_MAX_LENGTH:
        raise EvidenceServiceError(
            "invalid_request", f"origin 必须是 ≤{_ORIGIN_MAX_LENGTH} 字符的出处说明。", 400
        )
    return value.strip() or None


def normalize_captured_from(value: object) -> str:
    """来源通道：human | bridge_sync:{id} | agent_run:{id} | job:{id} | workflow_node:{id}。"""
    if value is None:
        return "human"
    if isinstance(value, str) and 0 < len(value) <= 64:
        if value == "human":
            return value
        if any(
            value.startswith(prefix) and len(value) > len(prefix)
            for prefix in CAPTURED_FROM_PREFIXES
            if prefix.endswith(":")
        ):
            return value
    raise EvidenceServiceError(
        "invalid_request",
        "captured_from 须为 human 或 bridge_sync:/agent_run:/job:/workflow_node: 前缀加标识。",
        400,
    )


# ---------------------------------------------------------------------------
# 会话内幂等登记（gate_service 等内部调用方直接用）
# ---------------------------------------------------------------------------


def _find(session: Session, project_id: str, source_uri: str, content_sha256: str) -> ProjectEvidence | None:
    return session.scalar(
        select(ProjectEvidence).where(
            ProjectEvidence.project_id == project_id,
            ProjectEvidence.source_uri == source_uri,
            ProjectEvidence.content_sha256 == content_sha256,
        )
    )


def upsert_evidence(
    session: Session,
    *,
    project_id: str,
    kind: str,
    source_uri: str,
    content_sha256: str,
    origin: str | None = None,
    captured_from: str | None = "human",
    created_by_user_id: str | None = None,
) -> tuple[ProjectEvidence, bool]:
    """返回 (row, created)。同指纹已有则原样返回（不改写任何列——证据不可变）。"""
    existing = _find(session, project_id, source_uri, content_sha256)
    if existing is not None:
        return existing, False
    row = ProjectEvidence(
        project_id=project_id,
        kind=kind,
        source_uri=source_uri,
        content_sha256=content_sha256,
        origin=origin,
        captured_from=captured_from,
        created_by_user_id=created_by_user_id,
    )
    try:
        with session.begin_nested():
            session.add(row)
            session.flush()
    except IntegrityError:
        # 并发登记撞唯一指纹：保存点已回退，读回赢家
        existing = _find(session, project_id, source_uri, content_sha256)
        if existing is None:
            raise
        return existing, False
    return row, True


def serialize_evidence(row: ProjectEvidence) -> dict[str, Any]:
    return {
        "id": row.id,
        "project_id": row.project_id,
        "kind": row.kind,
        "source_uri": row.source_uri,
        "content_sha256": row.content_sha256,
        "origin": row.origin,
        "captured_from": row.captured_from,
        "created_by_user_id": row.created_by_user_id,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


# ---------------------------------------------------------------------------
# HTTP 面
# ---------------------------------------------------------------------------


def _load_project(session: Session, actor: User, project_id: str, *, manage: bool) -> Project:
    project = session.get(Project, project_id)
    if project is None:
        raise EvidenceServiceError("project_not_found", "项目不存在或已被删除。", 404)
    access = project_access(actor, project)
    if not (access.can_manage if manage else access.can_view):
        raise EvidenceServiceError("forbidden", "你没有该项目证据的操作权限。", 403)
    return project


def register_evidence(*, actor: User, project_id: str, payload: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, Mapping) or set(payload) - _REGISTER_FIELDS:
        raise EvidenceServiceError("invalid_request", "请求字段无效。", 400)
    kind = normalize_kind(payload.get("kind"))
    source_uri = normalize_source_uri(payload.get("source_uri"))
    content_sha256 = normalize_sha256(payload.get("content_sha256"))
    origin = normalize_origin(payload.get("origin"))
    captured_from = normalize_captured_from(payload.get("captured_from"))
    with db.session() as session, session.begin():
        project = _load_project(session, actor, project_id, manage=True)
        row, created = upsert_evidence(
            session,
            project_id=project.id,
            kind=kind,
            source_uri=source_uri,
            content_sha256=content_sha256,
            origin=origin,
            captured_from=captured_from,
            created_by_user_id=actor.id,
        )
        if created:
            record_event(
                session,
                actor,
                "evidence_registered",
                project,
                {
                    "evidence_id": row.id,
                    "kind": kind,
                    "source_uri": source_uri,
                    "content_sha256": content_sha256,
                    "captured_from": captured_from,
                },
            )
        return {"evidence": serialize_evidence(row), "created": created}


def validate_evidence(*, actor: User, project_id: str, payload: Mapping[str, Any]) -> dict[str, Any]:
    """证据完整性只读校验（V3.1 P1-2 6.5；任务书「证据完整性检查」语义）。

    校验面（五维，任务书 P0-4 Gate 规则「类型/来源/时间/操作者/项目范围」）：
    ①exists_in_project——行存在且属于本项目（项目范围，跨项目即失败不泄露）；
    ②fingerprint_shape——sha256 64 位十六进制；③pointer_shape——source_uri
    非空 ≤500；④channel_registered——captured_from 在登记通道闭集
    （human 或 CAPTURED_FROM_PREFIXES 前缀）；⑤operator_registered——人工通道
    必须留操作者（机器通道允许 created_by 空，T-E3 语义）。
    可选 ``gate_key``：该门禁行须存在于本项目且证据 kind='gate'（类型/范围正确
    ——「Gate 只接收类型和项目范围正确的证据」）。零写入零事件（只读干跑）。
    """
    evidence_ids = payload.get("evidence_ids")
    if not isinstance(evidence_ids, list) or not evidence_ids:
        raise EvidenceServiceError("invalid_request", "evidence_ids 须为非空数组。", 400)
    if len(evidence_ids) > 100:
        raise EvidenceServiceError("invalid_request", "单次最多校验 100 条证据。", 400)
    if not all(isinstance(item, str) and item.strip() for item in evidence_ids):
        raise EvidenceServiceError("invalid_request", "evidence_ids 须为非空字符串数组。", 400)
    gate_key = payload.get("gate_key")
    if gate_key is not None and (not isinstance(gate_key, str) or not gate_key.strip()):
        raise EvidenceServiceError("invalid_request", "gate_key 须为非空字符串。", 400)

    import re as _re

    sha_pattern = _re.compile(r"^[0-9a-f]{64}$")
    session = db.session()
    try:
        with session.begin():
            _load_project(session, actor, project_id, manage=False)
            gate: Gate | None = None
            if gate_key:
                gate = session.scalar(
                    select(Gate).where(
                        Gate.project_id == project_id, Gate.gate_key == gate_key.strip()
                    )
                )
            results = []
            for evidence_id in dict.fromkeys(evidence_ids):  # 去重保序
                row = session.get(ProjectEvidence, evidence_id.strip())
                failures = []
                if row is None or row.project_id != project_id:
                    failures.append({"check": "exists_in_project", "detail": "行不存在或不属于本项目"})
                else:
                    if not sha_pattern.fullmatch(row.content_sha256 or ""):
                        failures.append({"check": "fingerprint_shape", "detail": "sha256 形状不合法"})
                    if not row.source_uri or len(row.source_uri) > 500:
                        failures.append({"check": "pointer_shape", "detail": "source_uri 缺失或超长"})
                    captured = row.captured_from or ""
                    channel_ok = captured == "human" or any(
                        captured.startswith(prefix) and len(captured) > len(prefix)
                        for prefix in CAPTURED_FROM_PREFIXES
                        if prefix.endswith(":")
                    )
                    if not channel_ok:
                        failures.append({"check": "channel_registered", "detail": f"来源通道不在册：{captured!r}"})
                    if row.created_at is None:
                        failures.append({"check": "timestamp_present", "detail": "缺登记时间"})
                    if row.created_by_user_id is None and captured == "human":
                        failures.append({"check": "operator_registered", "detail": "人工通道缺操作者"})
                    if gate_key is not None:
                        if gate is None:
                            failures.append({"check": "gate_scope", "detail": "门禁行不存在于本项目"})
                        elif row.kind != "gate":
                            failures.append({"check": "evidence_kind_for_gate", "detail": f"kind={row.kind!r} 非 gate 类证据"})
                results.append({
                    "evidence_id": evidence_id,
                    "valid": not failures,
                    "failures": failures,
                })
            return {
                "valid": all(item["valid"] for item in results),
                "gate_key": gate_key.strip() if gate_key else None,
                "results": results,
                "checked": len(results),
            }
    finally:
        session.close()


def list_evidence(
    *,
    actor: User,
    project_id: str,
    kind: str | None = None,
    referenced_by: str | None = None,
) -> dict[str, Any]:
    kind_filter = normalize_kind(kind) if kind else None
    gate_key: str | None = None
    if referenced_by:
        match = _GATE_REF_PATTERN.fullmatch(referenced_by)
        if match is None:
            raise EvidenceServiceError(
                "invalid_request", "referenced_by 目前仅支持 gate:G1–G9。", 400
            )
        gate_key = match.group(1)
    with db.session() as session:
        project = _load_project(session, actor, project_id, manage=False)
        query = select(ProjectEvidence).where(ProjectEvidence.project_id == project.id)
        if kind_filter is not None:
            query = query.where(ProjectEvidence.kind == kind_filter)
        if gate_key is not None:
            gate = session.scalar(
                select(Gate).where(Gate.project_id == project.id, Gate.gate_key == gate_key)
            )
            referenced_ids = sorted(
                {
                    item["evidence_id"]
                    for item in (gate.evidence_checklist if gate is not None else [])
                    if isinstance(item, dict) and item.get("evidence_id")
                }
            )
            if not referenced_ids:
                return {"items": []}
            query = query.where(ProjectEvidence.id.in_(referenced_ids))
        rows = session.scalars(
            query.order_by(ProjectEvidence.created_at.asc(), ProjectEvidence.id.asc())
        ).all()
        return {"items": [serialize_evidence(row) for row in rows]}


# ---------------------------------------------------------------------------
# 只读执行事实链（借鉴登记 #9；AGH「外部完成无真实回执=未知」纪律的我方落法）
# ---------------------------------------------------------------------------

_FACT_LIMIT_DEFAULT = 50
_FACT_LIMIT_MAX = 200
_FACT_TYPES = ("evidence", "operation_event", "ai_call_audit")


def serialize_fact_event(row: OperationEvent) -> dict[str, Any]:
    """operation_events 时间线条目——只投影元数据，不回传 changes 大载荷。"""
    return {
        "fact_type": "operation_event",
        "id": row.id,
        "actor_user_id": row.actor_user_id,
        "target_type": row.target_type,
        "target_id": row.target_id,
        "event_type": row.event_type,
        "occurred_at": row.occurred_at.isoformat() if row.occurred_at else None,
    }


def serialize_fact_ai_audit(row: AICallAudit) -> dict[str, Any]:
    """ai_call_audits 时间线条目——**账号维度**（无项目外键，scope 明示 actor）。"""
    return {
        "fact_type": "ai_call_audit",
        "id": row.id,
        "request_id": row.request_id,
        "actor_user_id": row.actor_user_id,
        "purpose": row.purpose,
        "model": row.model,
        "used_fallback": row.used_fallback,
        "status": row.status,
        "error_code": row.error_code,
        "duration_ms": row.duration_ms,
        "input_tokens": row.input_tokens,
        "output_tokens": row.output_tokens,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def execution_facts(
    *,
    actor: User,
    project_id: str,
    fact_type: str | None = None,
    limit: int | None = None,
) -> dict[str, Any]:
    """三源只读时间线（can_view）。

    - project_evidence / operation_events：项目维度，过滤下推 SQL。
    - ai_call_audits：无项目外键，按当前 actor 过滤（scope="actor"，响应明示；
      跨项目共用一条 AI 审计流——这是账本真实形态，不作项目切分）。
    - 归并后按时间倒序取前 N 条（有界 + truncated）；「外部完成无真实回执=
      未知」在本视图的落法：ai_call_audit 只投影调用事实（status 三值 CHECK），
      evidence 只存 sha256 指纹指针——无回执即无行，面板呈现为「无记录」，
      不由模型自述或时间线推断拼装任何「已完成」语义。
    """
    effective_limit = _FACT_LIMIT_DEFAULT if limit is None else limit
    if not isinstance(effective_limit, int) or not 0 < effective_limit <= _FACT_LIMIT_MAX:
        raise EvidenceServiceError(
            "invalid_request", f"limit 须为 1–{_FACT_LIMIT_MAX} 的整数。", 400
        )
    if fact_type is not None and fact_type not in _FACT_TYPES:
        raise EvidenceServiceError(
            "invalid_request",
            "fact_type 仅可为 evidence/operation_event/ai_call_audit。",
            400,
        )
    with db.session() as session:
        project = _load_project(session, actor, project_id, manage=False)
        items: list[dict[str, Any]] = []
        counts = {"evidence": 0, "operation_event": 0, "ai_call_audit": 0}
        if fact_type in (None, "evidence"):
            evidence_rows = session.scalars(
                select(ProjectEvidence)
                .where(ProjectEvidence.project_id == project.id)
                .order_by(ProjectEvidence.created_at.desc(), ProjectEvidence.id.desc())
            ).all()
            counts["evidence"] = len(evidence_rows)
            items.extend({"fact_type": "evidence", **serialize_evidence(row)} for row in evidence_rows)
        if fact_type in (None, "operation_event"):
            event_rows = session.scalars(
                select(OperationEvent)
                .where(OperationEvent.project_id == project.id)
                .order_by(OperationEvent.occurred_at.desc(), OperationEvent.id.desc())
            ).all()
            counts["operation_event"] = len(event_rows)
            items.extend(serialize_fact_event(row) for row in event_rows)
        if fact_type in (None, "ai_call_audit"):
            # 账号维度：actor_user_id 有索引（ix_ai_call_audits_actor_created），过滤下推 SQL。
            audit_rows = session.scalars(
                select(AICallAudit)
                .where(AICallAudit.actor_user_id == actor.id)
                .order_by(AICallAudit.created_at.desc(), AICallAudit.id.desc())
            ).all()
            counts["ai_call_audit"] = len(audit_rows)
            items.extend(serialize_fact_ai_audit(row) for row in audit_rows)
        items.sort(
            key=lambda item: item.get("occurred_at") or item.get("created_at") or "",
            reverse=True,
        )
        truncated = len(items) > effective_limit
        return {
            "project_id": project.id,
            "ai_call_audit_scope": "actor",
            "counts": counts,
            "items": items[:effective_limit],
            "truncated": truncated,
            "limit": effective_limit,
        }
