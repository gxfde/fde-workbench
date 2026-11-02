"""证据登记服务（V3 T-E1；设计 ontology-registry-v1 §3/§4）。

- ``upsert_evidence``：会话内幂等登记——同 (project, source_uri, sha256) 指纹已
  有则原样返回（证据不可变：不改写 origin / captured_from），否则新建；并发撞
  唯一约束时在保存点内回退后重读，不把 IntegrityError 抛给调用方。
- ``register_evidence`` / ``list_evidence``：HTTP 面。写路径 can_manage（真人会
  话），读路径 can_view；登记路径有意不进 api_catalog（AI 不可写证据，与 signoff
  同纪律）。``referenced_by=gate:G5`` 反查门禁清单项挂接的证据（T-E2 唯一引用方）。
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
from fde_api.workbench.models import Gate, Project

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
