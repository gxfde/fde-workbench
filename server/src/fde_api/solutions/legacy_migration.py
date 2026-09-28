"""Explicit, idempotent copy of legacy opportunity delivery answers.

Not run at startup or by Alembic: operators first review the dry-run, then run
inside a backed-up maintenance window. Every original answer/revision and all
historical documents remain untouched, even after a successful copy.
"""
from __future__ import annotations

from copy import deepcopy
import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from fde_api.auth.models import User
from fde_api.documents import draft_service as documents
from fde_api.extensions import db
from fde_api.projects.events import record_event
from fde_api.research.models import ProjectResearchForm, ProjectResearchFormRevision, ProjectResearchSubject
from fde_api.solutions.models import ProjectSolution
from fde_api.solutions.service import _set_opportunities

LEGACY_FIELDS = ("delivery_scope", "deliverables", "acceptance_criteria", "data_systems", "schedule", "risks_dependencies")


def delivery_field_labels(definition: dict[str, Any]) -> dict[str, str]:
    """Include administrator-defined fields before the old delivery section hides."""
    labels = {key: key for key in LEGACY_FIELDS}
    sections = definition.get("sections", []) if isinstance(definition, dict) else []
    for section in sections if isinstance(sections, list) else []:
        if not isinstance(section, dict) or not (section.get("section_key") == "delivery" or section.get("name") == "交付说明"):
            continue
        fields = section.get("fields", [])
        for field in fields if isinstance(fields, list) else []:
            if isinstance(field, dict) and isinstance(field.get("field_key"), str):
                labels[field["field_key"]] = str(field.get("name") or field["field_key"])
    return labels


def _meaningful(value: Any) -> bool:
    return value not in (None, "", [], {}) and (not isinstance(value, str) or value.strip() not in {"", "待确认", "待填写"})


def _text(value: Any) -> str:
    return value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)


def migrate_legacy_opportunity_delivery(*, actor: User, project_id: str, dry_run: bool = True) -> dict[str, Any]:
    """Copy one solution per opportunity, never infer how old opportunities merge."""
    with db.session() as session, session.begin():
        project = documents._load_project_for_update(session, project_id)
        documents._require_project_manager(actor, project)
        subjects = session.scalars(select(ProjectResearchSubject).options(selectinload(ProjectResearchSubject.opportunity_profile)).where(
            ProjectResearchSubject.project_id == project.id, ProjectResearchSubject.subject_type == "opportunity")).all()
        forms = session.scalars(select(ProjectResearchForm).options(selectinload(ProjectResearchForm.current_revision).selectinload(ProjectResearchFormRevision.answers)).where(
            ProjectResearchForm.project_id == project.id, ProjectResearchForm.subject_id.in_([item.id for item in subjects]))).all()
        by_subject: dict[str, list[ProjectResearchForm]] = {}
        for form in forms:
            by_subject.setdefault(form.subject_id, []).append(form)
        existing = set(session.scalars(select(ProjectSolution.legacy_source_key).where(ProjectSolution.project_id == project.id)).all())
        results = []
        for subject in subjects:
            source_key = f"opportunity:{subject.id}"
            if source_key in existing:
                continue
            sources = []
            values: dict[str, list[str]] = {}
            supplemental: list[str] = []
            for form in sorted(by_subject.get(subject.id, []), key=lambda item: (item.created_at, item.id)):
                revision = form.current_revision
                if revision is None:
                    continue
                labels = delivery_field_labels(revision.definition_snapshot)
                answers = {answer.field_key: deepcopy(answer.value_json) for answer in revision.answers if answer.field_key in labels and _meaningful(answer.value_json)}
                if not answers:
                    continue
                sources.append({"form_id": form.id, "form_name": form.name, "revision_id": revision.id, "revision_number": revision.revision_number, "answers": answers, "field_labels": {key: labels[key] for key in answers}})
                for field, answer in answers.items():
                    if field in LEGACY_FIELDS:
                        values.setdefault(field, []).append(_text(answer))
                    else:
                        supplemental.append(f"### {labels[field]}（{form.name}）\n\n{_text(answer)}")
            if not sources:
                continue
            merged = {field: "\n\n".join(dict.fromkeys(contents)) for field, contents in values.items()}
            if supplemental:
                original_scope = merged.get("delivery_scope", "")
                merged["delivery_scope"] = "\n\n".join(filter(None, [original_scope, "## 历史补充交付内容", *supplemental]))
            entry = {"opportunity_id": subject.id, "opportunity_name": subject.name, "source_forms": len(sources), "fields": list(merged), "solution_id": None}
            if not dry_run:
                solution = ProjectSolution(project_id=project.id, owner_user_id=actor.id,
                    name=f"{subject.name[:144]} · 历史交付说明", status=subject.status,
                    design_markdown=merged.pop("delivery_scope", ""), **merged,
                    legacy_source_key=source_key, source_json={"kind": "legacy_opportunity_delivery", "opportunity_id": subject.id, "forms": sources})
                _set_opportunities(solution, [subject])
                session.add(solution)
                session.flush()
                entry["solution_id"] = solution.id
                record_event(session, actor, "project_solution_legacy_copied", project, {"solution_id": solution.id, "opportunity_id": subject.id, "source_revision_ids": [item["revision_id"] for item in sources]})
            results.append(entry)
        if results and not dry_run:
            project.version += 1
        return {"dry_run": dry_run, "items": results, "count": len(results), "original_answers_unchanged": True}
