"""Project-scoped ontology snapshots exposed to DSH by execution identity."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from fde_api.control.models import AutomationTaskRun, KnowledgeSnapshot
from fde_api.files.models import ProjectFile
from fde_api.research.models import ProjectResearchPersonalMemo, ProjectResearchSubject
from fde_api.workbench.models import Project, ProjectModule, ProjectTask


SCHEMA_VERSION = "fde-ontology-v1"


def build_project_snapshot(
    session: Session, *, project_id: str, actor_user_id: str
) -> KnowledgeSnapshot:
    project = session.scalar(
        select(Project).options(joinedload(Project.leader)).where(Project.id == project_id)
    )
    if project is None:
        raise RuntimeError("project_not_found")
    modules = session.scalars(
        select(ProjectModule)
        .where(ProjectModule.project_id == project_id)
        .order_by(ProjectModule.sort_order, ProjectModule.id)
    ).all()
    tasks = session.scalars(
        select(ProjectTask)
        .join(ProjectModule, ProjectTask.project_module_id == ProjectModule.id)
        .options(joinedload(ProjectTask.project_module), joinedload(ProjectTask.assignee))
        .where(ProjectModule.project_id == project_id)
        .order_by(ProjectModule.sort_order, ProjectTask.sort_order, ProjectTask.id)
    ).all()
    files = session.scalars(
        select(ProjectFile)
        .options(joinedload(ProjectFile.current_version))
        .where(ProjectFile.project_id == project_id, ProjectFile.status == "active")
        .order_by(ProjectFile.display_name, ProjectFile.id)
    ).all()
    subjects = session.scalars(
        select(ProjectResearchSubject)
        .where(ProjectResearchSubject.project_id == project_id, ProjectResearchSubject.status == "active")
        .order_by(ProjectResearchSubject.sort_order, ProjectResearchSubject.id)
    ).all()
    personal_memos = session.scalars(
        select(ProjectResearchPersonalMemo)
        .options(joinedload(ProjectResearchPersonalMemo.author))
        .where(ProjectResearchPersonalMemo.project_id == project_id)
        .order_by(ProjectResearchPersonalMemo.subject_id, ProjectResearchPersonalMemo.user_id)
    ).all()

    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "project": {
            "id": project.id,
            "code": project.project_code,
            "name": project.name,
            "enterprise_name": project.enterprise_name,
            "background": project.background,
            "notes": project.notes,
            "status": project.status,
            "planned_start_date": project.planned_start_date.isoformat(),
            "planned_end_date": project.planned_end_date.isoformat() if project.planned_end_date else None,
            "leader": {"id": project.leader.id, "name": project.leader.display_name},
            "version": project.version,
        },
        "modules": [
            {
                "id": item.id,
                "name": item.name,
                "description": item.description,
                "status": item.status,
                "sort_order": item.sort_order,
            }
            for item in modules
        ],
        "tasks": [
            {
                "id": item.id,
                "module_id": item.project_module_id,
                "name": item.name,
                "description": item.description,
                "status": item.status,
                "progress": item.progress,
                "planned_start_date": item.planned_start_date.isoformat(),
                "planned_end_date": item.planned_end_date.isoformat(),
                "assignee": ({"id": item.assignee.id, "name": item.assignee.display_name} if item.assignee else None),
                "version": item.version,
            }
            for item in tasks
        ],
        "files": [
            {
                "id": item.id,
                "name": item.display_name,
                "description": item.description,
                "category": item.category,
                "business_category": item.business_category,
                "tags": item.tags_json,
                "version": item.version,
                "content_ref": (
                    {
                        "file_version_id": item.current_version.id,
                        "version_number": item.current_version.version_number,
                        "filename": item.current_version.original_filename,
                        "mime_type": item.current_version.mime_type,
                        "size_bytes": item.current_version.size_bytes,
                        "sha256": item.current_version.sha256,
                        "status": item.current_version.status,
                    }
                    if item.current_version and item.current_version.status == "available"
                    else None
                ),
            }
            for item in files
        ],
        "research_subjects": [
            {
                "id": item.id,
                "parent_id": item.parent_subject_id,
                "type": item.subject_type,
                "name": item.name,
                "description": item.description,
                "shared_memo": item.memo,
                "tracking_code": item.tracking_code,
                "version": item.version,
            }
            for item in subjects
        ],
        "personal_memos": [
            {
                "subject_id": item.subject_id,
                "author": {"id": item.user_id, "name": item.author.display_name},
                "memo": item.memo,
                "version": item.version,
            }
            for item in personal_memos
            if item.memo.strip()
        ],
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    digest = hashlib.sha256(encoded).hexdigest()
    existing = session.scalar(
        select(KnowledgeSnapshot).where(
            KnowledgeSnapshot.project_id == project_id,
            KnowledgeSnapshot.content_sha256 == digest,
        )
    )
    if existing is not None:
        return existing
    snapshot = KnowledgeSnapshot(
        project_id=project_id,
        created_by_user_id=actor_user_id,
        schema_version=SCHEMA_VERSION,
        content_sha256=digest,
        payload_json=payload,
    )
    session.add(snapshot)
    session.flush()
    return snapshot


def snapshot_for_run(session: Session, run_id: str) -> KnowledgeSnapshot | None:
    run = session.scalar(
        select(AutomationTaskRun)
        .options(joinedload(AutomationTaskRun.knowledge_snapshot))
        .where(AutomationTaskRun.id == run_id)
    )
    return run.knowledge_snapshot if run is not None else None
