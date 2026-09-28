"""Immutable source snapshots for project document generation.

``build_document_snapshot`` gathers the deterministic, frozen state of a project
that the DOCX generator consumes: the project identity and contact block, the
confirmed research answers, the research subjects (grouped by subject type and
keyed by their stable ``id``, never by name), the scheduled tasks, and the
project members. Every value is plain JSON-serializable data; raw ORM objects,
secrets, and binary blobs never cross this boundary.

Used by both Task 4 (``request_document_generation``) and the document engine's
worker, so the snapshot builder is deliberately ``session``-parameterised and
side-effect free: it reads only.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from fde_api.guidance.models import ProjectGuidanceAnalysis

from fde_api.research.models import (
    SUBJECT_TYPES,
    ProjectResearchAnswer,
    ProjectResearchForm,
    ProjectResearchFormRevision,
    ProjectResearchSubject,
)
from fde_api.workbench.models import (
    Project,
    ProjectMember,
    ProjectModule,
    ProjectTask,
    ProjectTaskDependency,
)


class DocumentSnapshotError(Exception):
    """A stable, user-facing document snapshot failure."""

    def __init__(self, code: str, message: str, status: int):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


def build_document_snapshot(
    session: Session, project_id: str, mapping: dict[str, Any]
) -> dict[str, Any]:
    """Produce the deterministic, immutable snapshot dict for a project document.

    ``mapping`` is the declarative mapping stored on the document's source
    template version (``mapping_json``); its ``research_keys`` select which
    confirmed research forms are embedded in the snapshot.
    """
    project = session.get(Project, project_id)
    if project is None or project_id is None:
        raise DocumentSnapshotError("project_not_found", "Project was not found.", 404)

    research_keys = _normalize_research_keys(mapping.get("research_keys", []))

    return {
        "project": _serialize_project(project),
        "enterprise": _serialize_enterprise(project),
        "guidance": _serialize_guidance(session, project_id),
        "research": confirmed_research_values(session, project_id, research_keys),
        "subjects": _serialize_subjects(session, project_id),
        "tasks": _serialize_tasks(session, project_id),
        "members": _serialize_members(session, project_id),
        "captured_at": datetime.now(UTC).isoformat(),
    }


def confirmed_research_values(
    session: Session, project_id: str, research_keys: list[str] | dict
) -> dict[str, dict[str, Any]]:
    """Load confirmed research answers keyed by ``form_key`` -> ``field_key``.

    For each ``form_key`` in ``research_keys`` the project's confirmed
    ``ProjectResearchFormRevision`` is located and its answers are collapsed into
    ``{field_key: value_json}``. Forms without a confirmed revision or without
    answers are skipped (never stale or draft content).
    """
    result: dict[str, dict[str, Any]] = {}
    for form_key in _normalize_research_keys(research_keys):
        form = session.scalar(
            select(ProjectResearchForm).where(
                ProjectResearchForm.project_id == project_id,
                ProjectResearchForm.form_key == form_key,
            )
        )
        if form is None:
            continue
        revision = session.scalar(
            select(ProjectResearchFormRevision)
            .where(
                ProjectResearchFormRevision.form_id == form.id,
                ProjectResearchFormRevision.status == "confirmed",
            )
            .order_by(ProjectResearchFormRevision.revision_number.desc())
            .limit(1)
        )
        if revision is None:
            continue
        answers = session.scalars(
            select(ProjectResearchAnswer).where(
                ProjectResearchAnswer.revision_id == revision.id
            )
        )
        result[form_key] = {
            answer.field_key: answer.value_json for answer in answers
        }
    return result


def _normalize_research_keys(research_keys: Any) -> list[str]:
    """Normalise ``research_keys`` into a de-duplicated list of form key strings.

    Accepts the declarative forms stored on a mapping: a list of ``{"form_key":
    ..., "subject_type": ...}`` dicts, a plain list of strings, or a ``{form_key:
    subject_type}`` dict.
    """
    raw: Any = research_keys
    if isinstance(raw, dict):
        raw = list(raw.keys())
    if not isinstance(raw, list):
        return []

    keys: list[str] = []
    for entry in raw:
        if isinstance(entry, dict) and isinstance(entry.get("form_key"), str):
            keys.append(entry["form_key"])
        elif isinstance(entry, str):
            keys.append(entry)

    seen: set[str] = set()
    result: list[str] = []
    for key in keys:
        if key not in seen:
            seen.add(key)
            result.append(key)
    return result


def _serialize_project(project: Project) -> dict[str, Any]:
    template_snapshot = project.template_snapshot if isinstance(project.template_snapshot, dict) else {}
    return {
        "id": project.id,
        "project_code": project.project_code,
        "name": project.name,
        "enterprise_name": project.enterprise_name,
        "contact_name": project.enterprise_contact_name,
        "contact_phone": project.enterprise_contact_phone,
        "address": project.enterprise_address,
        "industry_name": str(template_snapshot.get("industry_name") or ""),
        "background": project.background,
        "notes": project.notes,
        "leader_name": project.leader.display_name if project.leader is not None else "",
        "status": project.status,
        "planned_start_date": project.planned_start_date.isoformat(),
        "planned_end_date": (
            project.planned_end_date.isoformat()
            if project.planned_end_date is not None
            else None
        ),
    }


def _serialize_enterprise(project: Project) -> dict[str, Any]:
    return {
        "name": project.enterprise_name,
        "contact_name": project.enterprise_contact_name,
        "contact_phone": project.enterprise_contact_phone,
        "address": project.enterprise_address,
    }


def _serialize_guidance(session: Session, project_id: str) -> dict[str, Any]:
    row = session.scalar(
        select(ProjectGuidanceAnalysis)
        .where(
            ProjectGuidanceAnalysis.project_id == project_id,
            ProjectGuidanceAnalysis.status == "confirmed",
        )
        .order_by(ProjectGuidanceAnalysis.version_number.desc())
        .limit(1)
    )
    if row is None:
        return {}

    def item_texts(value: Any) -> list[str]:
        if not isinstance(value, list):
            return []
        return [str(item.get("text") or "").strip() for item in value if isinstance(item, dict) and str(item.get("text") or "").strip()]

    return {
        "customer_vision": row.customer_vision,
        "current_phase_objective": row.current_phase_objective,
        "executive_summary": row.executive_summary,
        "key_business_problems": item_texts(row.key_business_problems_json),
        "priority_departments": item_texts(row.priority_departments_json),
        "priority_roles": item_texts(row.priority_roles_json),
        "priority_processes": item_texts(row.priority_processes_json),
        "success_criteria": item_texts(row.success_criteria_json),
        "next_actions": item_texts(row.next_actions_json),
    }


def _serialize_subjects(session: Session, project_id: str) -> dict[str, list[dict[str, Any]]]:
    """Group the project's research subjects by subject type, keyed by stable id."""
    subjects = list(
        session.scalars(
            select(ProjectResearchSubject)
            .where(ProjectResearchSubject.project_id == project_id)
            .order_by(ProjectResearchSubject.sort_order, ProjectResearchSubject.id)
        )
    )
    grouped: dict[str, list[dict[str, Any]]] = {}
    for subject_type in SUBJECT_TYPES:
        rows = [subject for subject in subjects if subject.subject_type == subject_type]
        if rows:
            grouped[subject_type] = [_serialize_subject(subject) for subject in rows]
    return grouped


def _serialize_subject(subject: ProjectResearchSubject) -> dict[str, Any]:
    return {
        "id": subject.id,
        "subject_type": subject.subject_type,
        "subject_key": subject.subject_key,
        "name": subject.name,
        "description": subject.description,
        "status": subject.status,
        "sort_order": subject.sort_order,
    }


def _serialize_tasks(session: Session, project_id: str) -> list[dict[str, Any]]:
    tasks = list(
        session.scalars(
            select(ProjectTask)
            .join(ProjectModule)
            .where(ProjectModule.project_id == project_id)
            .options(selectinload(ProjectTask.assignee), selectinload(ProjectTask.project_module))
            .order_by(ProjectTask.sort_order, ProjectTask.id)
        )
    )
    names = {task.id: task.name for task in tasks}
    predecessor_ids: dict[str, list[str]] = {task.id: [] for task in tasks}
    task_ids = list(names)
    if task_ids:
        for edge in session.scalars(
            select(ProjectTaskDependency).where(ProjectTaskDependency.successor_task_id.in_(task_ids))
        ):
            predecessor_ids.setdefault(edge.successor_task_id, []).append(edge.predecessor_task_id)
    return [
        _serialize_task(task)
        | {"dependencies": [names[item] for item in predecessor_ids.get(task.id, []) if item in names]}
        for task in tasks
    ]


def _serialize_task(task: ProjectTask) -> dict[str, Any]:
    return {
        "id": task.id,
        "task_key": task.task_key,
        "name": task.name,
        "description": task.description,
        "module_name": task.project_module.name,
        "status": task.status,
        "progress": task.progress,
        "planned_start_date": task.planned_start_date.isoformat(),
        "planned_end_date": task.planned_end_date.isoformat(),
        "duration_days": task.duration_days,
        "assignee": (
            {
                "id": task.assignee.id,
                "display_name": task.assignee.display_name,
            }
            if task.assignee is not None
            else None
        ),
    }


def _serialize_members(session: Session, project_id: str) -> list[dict[str, Any]]:
    members = list(
        session.scalars(
            select(ProjectMember)
            .where(ProjectMember.project_id == project_id)
            .options(selectinload(ProjectMember.user))
            .order_by(ProjectMember.id)
        )
    )
    return [
        {
            "id": member.id,
            "user_id": member.user_id,
            "display_name": member.user.display_name if member.user is not None else None,
            "role": member.role,
        }
        for member in members
    ]
