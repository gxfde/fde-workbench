"""handover 服务：结项交付包生命周期（goal-tb tb4）。

权限（D11 草案 §二原文）：seal/unseal/编辑=项目负责人+admin（can_manage）；
**deliver（登记对外交付）=admin**；查看=项目成员（can_view）。
审计：handover_package_sealed / _unsealed / _delivered OperationEvent
（target=项目，changes 只带 id 与元数据，不复制产物内容）。
明确不做（草案原文）：自动打包 zip、对外下载链接签名、与合同条款联动。
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select

from fde_api.agents.models import AgentArtifact, AgentRun
from fde_api.extensions import db
from fde_api.projects.events import record_event
from fde_api.projects.permissions import project_access, visible_project_ids
from fde_api.handover.models import HandoverPackage, HandoverPackageItem
from fde_api.workbench.models import Project, User

MAX_LABEL_CHARS = 200
MAX_ITEMS = 200
MAX_DISPLAY_NAME = 255
_LIST_LIMIT_DEFAULT = 50
_LIST_LIMIT_MAX = 200


class HandoverServiceError(Exception):
    def __init__(self, code: str, message: str, status: int, detail: dict[str, Any] | None = None):
        super().__init__(message)
        self.code, self.message, self.status = code, message, status
        self.detail = detail or {}


def _error(code: str, message: str, status: int = 400, detail: dict[str, Any] | None = None) -> HandoverServiceError:
    return HandoverServiceError(code, message, status, detail)


def _session() -> Any:
    return db.session()


def _load_project_for(session: Any, actor: User, project_id: str, *, manage: bool) -> Project:
    project = session.get(Project, project_id)
    access = project_access(actor, project) if project else None
    if project is None or access is None:
        raise _error("project_not_found", "项目不存在或无权访问。", 404)
    if manage and not access.can_manage:
        raise _error("project_forbidden", "需要项目管理权限。", 403)
    if not manage and not access.can_view:
        raise _error("project_forbidden", "无权访问该项目。", 403)
    return project


def _load_package_for(session: Any, actor: User, package_id: str, *, manage: bool) -> tuple[HandoverPackage, Project]:
    package = session.get(HandoverPackage, package_id)
    if package is None:
        raise _error("package_not_found", "交付包不存在。", 404)
    project = _load_project_for(session, actor, package.project_id, manage=manage)
    return package, project


def _require_admin(actor: User) -> None:
    if actor.role != "admin":
        raise _error("admin_required", "交付登记（delivered）仅管理员可执行（D11 草案权限）。", 403)


# ---------------------------------------------------------------------------
# 快照与清单


def _snapshot_item(artifact: AgentArtifact, display_name: str) -> dict[str, Any]:
    return {
        "item_type": "artifact",
        "artifact_id": artifact.id,
        "run_id": artifact.run_id,
        "kind": artifact.kind,
        "display_name": display_name[:MAX_DISPLAY_NAME],
        "storage_ref": artifact.storage_ref,
        "sha256": artifact.sha256,
    }


def _validate_item_payloads(session: Any, project_id: str, raw_items: Any) -> list[dict[str, Any]]:
    """draft 清单编辑的形状与归属校验：快照取 live 产物行的当前指纹。"""
    if not isinstance(raw_items, list) or not raw_items:
        raise _error("invalid_items", "items 必须是非空数组。", 422)
    if len(raw_items) > MAX_ITEMS:
        raise _error("invalid_items", f"items 上限 {MAX_ITEMS} 行。", 422, {"limit": MAX_ITEMS})
    seen: set[str] = set()
    snapshots: list[dict[str, Any]] = []
    for raw in raw_items:
        if not isinstance(raw, dict):
            raise _error("invalid_items", "items 元素必须是对象。", 422)
        artifact_id = raw.get("artifact_id")
        if not isinstance(artifact_id, str) or not artifact_id:
            raise _error("invalid_items", "items[].artifact_id 必填。", 422)
        if artifact_id in seen:
            raise _error("invalid_items", "同一产物在清单内重复。", 422)
        seen.add(artifact_id)
        artifact = session.get(AgentArtifact, artifact_id)
        if artifact is None:
            raise _error("artifact_not_found", f"产物不存在：{artifact_id}", 404)
        run = session.get(AgentRun, artifact.run_id)
        if run is None or run.project_id != project_id:
            raise _error("artifact_foreign_project", "产物不属于该项目（跨项目封包拒绝）。", 409)
        display_name = raw.get("display_name")
        if display_name is None:
            display_name = artifact.storage_ref.rsplit("/", 1)[-1]
        if not isinstance(display_name, str) or not display_name.strip():
            raise _error("invalid_items", "display_name 必须是非空字符串。", 422)
        snapshots.append(_snapshot_item(artifact, display_name.strip()))
    return snapshots


def _canonical_manifest(package: HandoverPackage, items: list[HandoverPackageItem]) -> dict[str, Any]:
    return {
        "package_id": package.id,
        "label": package.label,
        "sealed_at": package.sealed_at.isoformat() if package.sealed_at else None,
        "items": sorted(
            (
                {
                    "item_type": item.item_type,
                    "artifact_id": item.artifact_id,
                    "run_id": item.run_id,
                    "kind": item.kind,
                    "display_name": item.display_name,
                    "storage_ref": item.storage_ref,
                    "sha256": item.sha256,
                }
                for item in items
            ),
            key=lambda row: row["artifact_id"] or "",
        ),
    }


def _manifest_digest(manifest: dict[str, Any]) -> str:
    canonical = json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _replace_items(session: Any, package: HandoverPackage, snapshots: list[dict[str, Any]]) -> None:
    session.query(HandoverPackageItem).filter(HandoverPackageItem.package_id == package.id).delete()
    for snapshot in snapshots:
        session.add(HandoverPackageItem(package_id=package.id, **snapshot))
    session.flush()  # 序列化前落库（session autoflush 可能被配置关闭）


# ---------------------------------------------------------------------------
# 序列化


def _serialize_package(row: HandoverPackage, *, detail: bool, session: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "id": row.id,
        "project_id": row.project_id,
        "label": row.label,
        "status": row.status,
        "created_by_user_id": row.created_by_user_id,
        "created_at": row.created_at.isoformat(),
        "sealed_by_user_id": row.sealed_by_user_id,
        "sealed_at": row.sealed_at.isoformat() if row.sealed_at else None,
        "unsealed_count": row.unsealed_count,
        "delivered_by_user_id": row.delivered_by_user_id,
        "delivered_at": row.delivered_at.isoformat() if row.delivered_at else None,
    }
    if row.status != "draft":
        data["manifest_sha256"] = row.manifest_sha256
    if detail:
        items = list(session_items(session, row.id))
        data["items"] = [
            {
                "id": item.id,
                "item_type": item.item_type,
                "artifact_id": item.artifact_id,
                "run_id": item.run_id,
                "kind": item.kind,
                "display_name": item.display_name,
                "storage_ref": item.storage_ref,
                "sha256": item.sha256,
            }
            for item in items
        ]
        if row.status != "draft":
            data["manifest"] = _canonical_manifest(row, items)
    return data


def session_items(session: Any, package_id: str) -> Any:
    """清单行查询（**必须传当前事务 session**——db.session() 每次新建会话，
    新会话看不到事务内未提交行）。"""
    return session.scalars(
        select(HandoverPackageItem)
        .where(HandoverPackageItem.package_id == package_id)
        .order_by(HandoverPackageItem.display_name, HandoverPackageItem.id)
    )


# ---------------------------------------------------------------------------
# 生命周期


def create_package(*, actor: User, payload: dict[str, Any]) -> dict[str, Any]:
    session = _session()
    project_id = payload.get("project_id")
    if not isinstance(project_id, str) or not project_id:
        raise _error("invalid_request", "project_id 必填。", 400)
    label = payload.get("label")
    if label is not None and (not isinstance(label, str) or len(label) > MAX_LABEL_CHARS):
        raise _error("invalid_request", f"label 须为 ≤{MAX_LABEL_CHARS} 字符的字符串。", 422)
    with session.begin():
        project = _load_project_for(session, actor, project_id, manage=True)
        snapshots = _validate_item_payloads(session, project.id, payload.get("items"))
        package = HandoverPackage(
            project_id=project.id,
            created_by_user_id=actor.id,
            label=label.strip() if isinstance(label, str) and label.strip() else None,
            status="draft",
        )
        session.add(package)
        session.flush()
        _replace_items(session, package, snapshots)
        record_event(session, actor, "handover_package_created", project, {
            "package_id": package.id,
            "item_count": len(snapshots),
        })
        return _serialize_package(package, detail=True, session=session)


def list_packages(*, actor: User, project_id: str | None, limit: int, offset: int) -> dict[str, Any]:
    session = _session()
    rows_query = select(HandoverPackage).order_by(HandoverPackage.created_at.desc(), HandoverPackage.id)
    if project_id is not None:
        project = _load_project_for(session, actor, project_id, manage=False)
        rows_query = rows_query.where(HandoverPackage.project_id == project.id)
    else:
        visible = visible_project_ids(session, actor)
        if not visible:
            return {"items": [], "total": None, "limit": limit, "offset": offset, "truncated": False}
        rows_query = rows_query.where(HandoverPackage.project_id.in_(visible))
    rows = list(session.scalars(rows_query.offset(offset).limit(limit + 1)))
    truncated = len(rows) > limit
    return {
        "items": [_serialize_package(row, detail=False, session=session) for row in rows[:limit]],
        "total": None,
        "limit": limit,
        "offset": offset,
        "truncated": truncated,
    }


def get_package(*, actor: User, package_id: str) -> dict[str, Any]:
    session = _session()
    with session.begin():
        package, _project = _load_package_for(session, actor, package_id, manage=False)
        return _serialize_package(package, detail=True, session=session)


def update_package(*, actor: User, package_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    session = _session()
    with session.begin():
        package, _project = _load_package_for(session, actor, package_id, manage=True)
        if package.status != "draft":
            raise _error("package_not_draft", "只有草稿包可编辑（封存后清单冻结；解封后回草稿再编辑）。", 409)
        if "label" in payload:
            label = payload.get("label")
            if label is None:
                package.label = None
            elif isinstance(label, str) and label.strip() and len(label) <= MAX_LABEL_CHARS:
                package.label = label.strip()
            else:
                raise _error("invalid_request", f"label 须为 ≤{MAX_LABEL_CHARS} 字符的字符串。", 422)
        if "items" in payload:
            snapshots = _validate_item_payloads(session, package.project_id, payload.get("items"))
            _replace_items(session, package, snapshots)
        return _serialize_package(package, detail=True, session=session)


def seal_package(*, actor: User, package_id: str) -> dict[str, Any]:
    """封存：冻结清单 + 逐项校验（存在/本项目/已人工复核/指纹一致）+ manifest 规范化哈希。"""
    session = _session()
    now = datetime.now(UTC)
    with session.begin():
        package, project = _load_package_for(session, actor, package_id, manage=True)
        if package.status != "draft":
            raise _error("package_not_draft", "只有草稿包可封存。", 409)
        items = list(session_items(session, package.id))
        if not items:
            raise _error("empty_package", "空清单不可封存。", 422)
        for item in items:
            artifact = session.get(AgentArtifact, item.artifact_id) if item.artifact_id else None
            if artifact is None:
                raise _error("artifact_missing", f"清单产物已不存在：{item.artifact_id}", 409)
            run = session.get(AgentRun, artifact.run_id)
            if run is None or run.project_id != package.project_id:
                raise _error("artifact_foreign_project", "产物不属于该项目（跨项目封包拒绝）。", 409)
            if not artifact.reviewed:
                raise _error(
                    "artifact_not_reviewed",
                    "清单含未人工复核的产物——封包仅接受已复核产物（与 D11 草案 status 闸同构）。",
                    409,
                    {"artifact_id": artifact.id},
                )
            if artifact.sha256 != item.sha256:
                raise _error(
                    "fingerprint_drift",
                    "清单快照指纹与产物现行指纹不一致。",
                    409,
                    {"artifact_id": artifact.id},
                )
        # 先落封存态再算 manifest（sealed_at 必须在清单里，否则摘要与呈现不一致）
        package.status = "sealed"
        package.sealed_by_user_id = actor.id
        package.sealed_at = now
        manifest = _canonical_manifest(package, items)
        package.manifest_sha256 = _manifest_digest(manifest)
        record_event(session, actor, "handover_package_sealed", project, {
            "package_id": package.id,
            "item_count": len(items),
            "manifest_sha256": package.manifest_sha256,
        })
        return _serialize_package(package, detail=True, session=session)


def unseal_package(*, actor: User, package_id: str) -> dict[str, Any]:
    session = _session()
    now = datetime.now(UTC)
    with session.begin():
        package, project = _load_package_for(session, actor, package_id, manage=True)
        if package.status != "sealed":
            raise _error("package_not_sealed", "只有已封存包可解封（draft 无需解封；delivered 不可逆）。", 409)
        package.status = "draft"
        package.sealed_by_user_id = None
        package.sealed_at = None
        package.manifest_sha256 = None
        package.unsealed_count += 1
        package.unsealed_by_user_id = actor.id
        package.unsealed_at = now
        record_event(session, actor, "handover_package_unsealed", project, {
            "package_id": package.id,
            "unsealed_count": package.unsealed_count,
        })
        return _serialize_package(package, detail=True, session=session)


def deliver_package(*, actor: User, package_id: str) -> dict[str, Any]:
    """交付登记（admin 专属）：sealed→delivered，终态不可逆（指纹链已出系统，需人工处置）。"""
    session = _session()
    now = datetime.now(UTC)
    with session.begin():
        package, project = _load_package_for(session, actor, package_id, manage=True)
        _require_admin(actor)
        if package.status == "delivered":
            raise _error("already_delivered", "该包已登记交付（终态不可逆）。", 409)
        if package.status != "sealed":
            raise _error("package_not_sealed", "只有已封存包可登记交付。", 409)
        package.status = "delivered"
        package.delivered_by_user_id = actor.id
        package.delivered_at = now
        record_event(session, actor, "handover_package_delivered", project, {
            "package_id": package.id,
            "manifest_sha256": package.manifest_sha256,
        })
        return _serialize_package(package, detail=True, session=session)


def available_artifacts(*, actor: User, project_id: str) -> dict[str, Any]:
    """封包挑选面：本项目**已人工复核**产物投影（指针+指纹，不进 api_catalog）。"""
    session = _session()
    with session.begin():
        project = _load_project_for(session, actor, project_id, manage=False)
        rows = list(session.scalars(
            select(AgentArtifact)
            .join(AgentRun, AgentArtifact.run_id == AgentRun.id)
            .where(AgentRun.project_id == project.id, AgentArtifact.reviewed.is_(True))
            .order_by(AgentArtifact.created_at.desc())
            .limit(_LIST_LIMIT_MAX)
        ))
        return {
            "items": [
                {
                    "artifact_id": row.id,
                    "run_id": row.run_id,
                    "kind": row.kind,
                    "storage_ref": row.storage_ref,
                    "sha256": row.sha256,
                    "reviewed_at": row.reviewed_at.isoformat() if row.reviewed_at else None,
                }
                for row in rows
            ],
            "truncated": len(rows) >= _LIST_LIMIT_MAX,
        }
