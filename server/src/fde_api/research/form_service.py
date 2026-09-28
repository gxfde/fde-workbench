from __future__ import annotations

from copy import deepcopy
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any
from datetime import datetime, timezone

from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session, selectinload

from fde_api.auth.models import User
from fde_api.extensions import db
from fde_api.projects import events as project_events
from fde_api.projects.permissions import project_access
from fde_api.research.answers import (
    DEFAULT_FILE_REFERENCE_VALIDATOR,
    FileReferenceValidator,
    ResearchValidationError,
    normalize_text,
    validate_answer,
)
from fde_api.research.models import (
    ProjectResearchAnswer,
    ProjectResearchForm,
    ProjectResearchFormRevision,
    ProjectResearchSubject,
    ResearchImmutableError,
    assert_revision_mutable,
)
from fde_api.workbench.models import ModuleCatalog, Project, ProjectModule, new_uuid
from fde_api.research.definitions import DefinitionIssue, validate_research_definition


class ResearchFormServiceError(Exception):
    def __init__(self, code: str, message: str, status: int, details: object = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status
        self.details = details


# Default, self-contained AI opportunity definition used when a project's frozen
# template snapshot does not already declare an opportunity research form. This
# keeps newly discovered opportunities expressive even for decoupled projects.
DEFAULT_OPPORTUNITY_FORM_KEY = "ai_opportunity_definition"
OPPORTUNITY_SECTION_DISCOVERY_KEY = "discovery"
OPPORTUNITY_SECTION_DELIVERY_KEY = "delivery"
OPPORTUNITY_DELIVERY_FIELD_KEYS = frozenset({
    "delivery_scope", "deliverables", "acceptance_criteria", "data_systems",
    "schedule", "risks_dependencies",
})


_DEFAULT_OPPORTUNITY_DEFINITION: dict[str, Any] = {
    "form_key": DEFAULT_OPPORTUNITY_FORM_KEY,
    "name": "AI 机会调研",
    "description": "识别业务中的 AI 机会，记录现状、痛点、价值和依据；交付内容在方案设计中维护。",
    "subject_type": "opportunity",
    "module_key": None,
    "sort_order": 0,
    "sections": [
        {
            "section_key": OPPORTUNITY_SECTION_DISCOVERY_KEY,
            "name": "发现",
            "description": "描述机会的现状、痛点与业务价值，明确目标和前提。",
            "sort_order": 0,
            "fields": [
                {"field_key": "current_state", "name": "现状描述", "help_text": "描述当前业务如何运作，以及 AI 将介入的环节。", "type": "long_text", "is_required": False, "options": {}, "sort_order": 0},
                {"field_key": "pain_points", "name": "痛点/问题", "help_text": "现在最困扰的业务痛点或亟待解决的问题。", "type": "long_text", "is_required": True, "options": {}, "sort_order": 1},
                {"field_key": "business_value", "name": "业务价值", "help_text": "预期带来的业务价值，例如效率、质量或营收提升。", "type": "long_text", "is_required": True, "options": {}, "sort_order": 2},
                {"field_key": "target_scenario", "name": "目标场景", "help_text": "AI 将覆盖的具体业务场景与使用对象。", "type": "long_text", "is_required": False, "options": {}, "sort_order": 3},
                {"field_key": "owner_role", "name": "负责人/角色", "help_text": "推动该项机会落地的负责人或角色。", "type": "short_text", "is_required": False, "options": {}, "sort_order": 4},
                {"field_key": "technical_prereqs", "name": "技术前提", "help_text": "实现该机会所需的技术与数据前提。", "type": "long_text", "is_required": False, "options": {}, "sort_order": 5},
            ],
        },
    ],
}


@dataclass(frozen=True, slots=True)
class SubjectFormInitializationContext:
    definitions_by_type: dict[str, tuple[dict[str, Any], ...]]
    active_modules: frozenset[str]


def build_subject_form_context(
    session: Session, project: Project
) -> SubjectFormInitializationContext:
    """Resolve immutable form definitions and active modules once per transaction."""
    snapshot = project.research_snapshot
    definitions = snapshot.get("forms") if isinstance(snapshot, dict) else None
    if not isinstance(definitions, list):
        raise ResearchFormServiceError(
            "research_form_definition_missing",
            "Research form definition is unavailable.",
            409,
        )
    by_type: dict[str, list[dict[str, Any]]] = {}
    for item in definitions:
        if isinstance(item, dict) and isinstance(item.get("subject_type"), str):
            by_type.setdefault(item["subject_type"], []).append(item)
    active_modules = frozenset(
        session.scalars(
            select(ModuleCatalog.module_key)
            .join(ProjectModule)
            .where(ProjectModule.project_id == project.id, ProjectModule.status == "active")
        )
    )
    return SubjectFormInitializationContext(
        {
            subject_type: tuple(
                sorted(
                    items,
                    key=lambda item: (
                        item.get("sort_order")
                        if type(item.get("sort_order")) is int
                        else 0,
                        str(item.get("form_key", "")),
                    ),
                )
            )
            for subject_type, items in by_type.items()
        },
        active_modules,
    )


def initialize_subject_forms(
    session: Session,
    project: Project,
    subject: Any,
    *,
    context: SubjectFormInitializationContext | None = None,
    subject_is_new: bool = False,
) -> list[ProjectResearchForm]:
    """Materialize the frozen forms applicable to one subject inside its caller's transaction."""
    context = context or build_subject_form_context(session, project)
    existing: set[str] = set()
    if not subject_is_new:
        existing = set(
            session.scalars(
                select(ProjectResearchForm.form_key).where(
                    ProjectResearchForm.subject_id == subject.id
                )
            )
        )
    forms: list[ProjectResearchForm] = []
    for definition in context.definitions_by_type.get(subject.subject_type, ()):
        # Old project template snapshots remain immutable, while new opportunity
        # forms adopt the identification-only boundary.
        definition = _opportunity_identification_definition(definition)
        module_key = definition.get("module_key")
        if module_key is not None and module_key not in context.active_modules:
            continue
        form_key = definition.get("form_key")
        source_id = definition.get("id")
        if not isinstance(form_key, str) or not isinstance(source_id, str):
            raise ResearchFormServiceError(
                "research_form_definition_missing", "Research form definition is unavailable.", 409
            )
        if form_key in existing:
            continue
        form = ProjectResearchForm(
            project_id=project.id,
            subject_id=subject.id,
            source_template_research_form_id=source_id,
            form_key=form_key,
            name=definition.get("name") if isinstance(definition.get("name"), str) else form_key,
            description=definition.get("description") if isinstance(definition.get("description"), str) else "",
        )
        session.add(form)
        session.flush()
        revision = ProjectResearchFormRevision(
            form=form,
            revision_number=1,
            status="draft",
            definition_snapshot=deepcopy(definition),
        )
        session.add(revision)
        session.flush()
        form.current_revision = revision
        forms.append(form)
    if (
        subject.subject_type == "opportunity"
        and not forms
        and not existing
        and DEFAULT_OPPORTUNITY_FORM_KEY not in existing
    ):
        definition = _opportunity_default_definition()
        project_form = ProjectResearchForm(
            project_id=project.id,
            subject_id=subject.id,
            source_template_research_form_id=None,
            form_key=definition["form_key"],
            name=definition["name"],
            description=definition["description"],
        )
        session.add(project_form)
        session.flush()
        revision = ProjectResearchFormRevision(
            form=project_form,
            revision_number=1,
            status="draft",
            definition_snapshot=definition,
        )
        session.add(revision)
        session.flush()
        project_form.current_revision = revision
        forms.append(project_form)
    return forms


def list_forms(*, actor: User, project_id: str) -> list[dict[str, Any]]:
    session = db.session()
    try:
        project = _load_project(session, actor, project_id)
        forms = list(
            session.scalars(
                select(ProjectResearchForm)
                .where(ProjectResearchForm.project_id == project.id)
                .options(
                    selectinload(ProjectResearchForm.current_revision).selectinload(
                        ProjectResearchFormRevision.answers
                    )
                )
            )
        )
        return [
            _serialize_form(form, _active_definition(project, form))
            for form in sorted(forms, key=lambda form: _form_sort_key(project, form))
        ]
    finally:
        session.close()


def get_form(*, actor: User, project_id: str, form_id: str) -> dict[str, Any]:
    session = db.session()
    try:
        project = _load_project(session, actor, project_id)
        form = _load_form(session, project.id, form_id)
        return _serialize_form(form, _active_definition(project, form))
    finally:
        session.close()


def patch_form_revision(
    *,
    actor: User,
    project_id: str,
    form_id: str,
    expected_version: int,
    changes: Mapping[str, Any],
    file_reference_validator: FileReferenceValidator = DEFAULT_FILE_REFERENCE_VALIDATOR,
) -> dict[str, Any]:
    _require_answers_mapping(changes)
    session = db.session()
    try:
        with session.begin():
            project = _load_project(session, actor, project_id, for_update=True)
            _require_fill(actor, project)
            form = _load_form(session, project.id, form_id, for_update=True)
            revision = _load_current_revision(session, form, for_update=True)
            _require_current_version(revision, expected_version)
            definition = _active_definition(project, form)
            revision = _ensure_working_revision(session, form, revision, definition)
            fields = _fields_by_key(definition)
            if set(changes) - set(fields):
                raise _invalid_answer("Unknown research field.", sorted(set(changes) - set(fields))[0])
            deleted = {key for key, value in changes.items() if value is None}
            normalized = {
                key: _validate_field_answer(
                    fields[key], value, file_reference_validator=file_reference_validator
                )
                for key, value in changes.items() if value is not None
            }
            prior = {answer.field_key: answer.value_json for answer in revision.answers}
            candidate = {**prior, **normalized}
            for key in deleted:
                candidate.pop(key, None)
            visible = _visible_field_keys(fields, candidate)
            if set(normalized) - visible:
                raise _invalid_answer(
                    "Hidden research fields cannot be updated.",
                    sorted(set(normalized) - visible)[0],
                )
            answers_by_key = {answer.field_key: answer for answer in revision.answers}
            for key in deleted:
                answer = answers_by_key.get(key)
                if answer is not None:
                    session.delete(answer)
            for key, value in normalized.items():
                answer = answers_by_key.get(key)
                if answer is None:
                    answer = ProjectResearchAnswer(
                        revision=revision,
                        source_template_research_field_id=(
                            fields[key]["id"] if form.source_template_research_form_id is not None else None
                        ),
                        field_key=key,
                        value_json=value,
                    )
                    session.add(answer)
                else:
                    answer.value_json = value
            if normalized or deleted:
                revision.returned_by_user_id = None
                revision.returned_at = None
                revision.return_comment = None
            revision.version += 1
            session.flush()
            if deleted:
                session.expire(revision, ["answers"])
            project_events.record_event(
                session,
                actor,
                "project_research_form_patched",
                form,
                {"revision_number": revision.revision_number, "answered_field_count": len(revision.answers)},
            )
            result = _serialize_form(form, definition)
        return result
    except ResearchFormServiceError:
        raise
    except (ResearchValidationError, ResearchImmutableError):
        raise _invalid_answer() from None
    except IntegrityError:
        raise _conflict() from None
    except SQLAlchemyError:
        raise _mutation_failed() from None
    except Exception:
        raise _mutation_failed() from None
    finally:
        session.close()


def confirm_form_revision(
    *, actor: User, project_id: str, form_id: str, expected_version: int
) -> dict[str, Any]:
    session = db.session()
    try:
        with session.begin():
            project = _load_project(session, actor, project_id, for_update=True)
            _require_confirm(actor, project)
            form = _load_form(session, project.id, form_id, for_update=True)
            revision = _load_current_revision(session, form, for_update=True)
            definition = _active_definition(project, form)
            _require_mutable_current(revision)
            _require_current_version(revision, expected_version)
            fields = _fields_by_key(definition)
            answers = {answer.field_key: answer.value_json for answer in revision.answers}
            visible = _visible_field_keys(fields, answers)
            missing = [
                key for key in visible
                if fields[key].get("is_required") is True and _answer_is_empty(answers.get(key))
            ]
            if missing:
                raise ResearchFormServiceError(
                    "research_required_fields_missing",
                    "Visible required research answers are missing.",
                    422,
                    {"fields": [{"field_key": key, "reason": "required"} for key in sorted(missing)]},
                )
            revision.status = "confirmed"
            revision.version += 1
            project_events.record_event(
                session,
                actor,
                "project_research_form_confirmed",
                form,
                {"revision_number": revision.revision_number, "answered_field_count": len(answers)},
            )
            result = _serialize_form(form, definition)
        return result
    except ResearchFormServiceError:
        raise
    except ResearchImmutableError:
        raise _immutable() from None
    except SQLAlchemyError:
        raise _mutation_failed() from None
    finally:
        session.close()


def update_project_form_definition(
    *,
    actor: User,
    project_id: str,
    form_id: str,
    expected_version: int,
    input_mapping: Mapping[str, Any],
) -> dict[str, Any]:
    """Replace the current form structure while preserving answers by field key."""
    form_input = _normalize_project_form(input_mapping)
    session = db.session()
    try:
        with session.begin():
            project = _load_project(session, actor, project_id, for_update=True)
            _require_fill(actor, project)
            form = _load_form(session, project.id, form_id, for_update=True)
            subject = _load_subject(session, project.id, form.subject_id)
            revision = _load_current_revision(session, form, for_update=True)
            _require_current_version(revision, expected_version)
            if form_input.get("form_key") != form.form_key:
                raise ResearchFormServiceError(
                    "research_form_key_immutable",
                    "The research form stable key cannot be changed.",
                    409,
                )
            if form_input.get("subject_type") != subject.subject_type:
                raise ResearchFormServiceError(
                    "research_form_subject_type_mismatch",
                    "The research form subject type must match the selected subject.",
                    400,
                )
            stored_definition = _stored_definition(project, form)
            previous_definition = _active_definition(project, form)
            retired_keys = set(_fields_by_key(stored_definition)) - set(_fields_by_key(previous_definition))
            if stored_definition.get("subject_type") == "opportunity":
                # A prior definition edit may already have retired the delivery
                # fields. Preserve those carried-forward answers on later edits.
                retired_keys.update(
                    answer.field_key for answer in revision.answers
                    if answer.field_key not in _fields_by_key(stored_definition)
                )
            revision = _fork_working_revision(session, form, revision, previous_definition)
            definition = _opportunity_identification_definition(_make_fields_optional(_inject_definition_ids(form_input)))
            _raise_definition_issues(validate_research_definition({"forms": [definition]}))
            current_keys = set(_fields_by_key(definition))
            for answer in list(revision.answers):
                if answer.field_key not in current_keys and answer.field_key not in retired_keys:
                    session.delete(answer)
            revision.definition_snapshot = deepcopy(definition)
            revision.returned_by_user_id = None
            revision.returned_at = None
            revision.return_comment = None
            revision.version += 1
            form.name = definition["name"]
            form.description = definition["description"]
            form.version += 1
            session.flush()
            session.expire(revision, ["answers"])
            project_events.record_event(
                session,
                actor,
                "project_research_form_definition_updated",
                form,
                {"revision_number": revision.revision_number, "form_key": form.form_key},
            )
            result = _serialize_form(form, definition)
        return result
    except ResearchFormServiceError:
        raise
    except IntegrityError:
        raise _conflict() from None
    except SQLAlchemyError:
        raise _mutation_failed() from None
    finally:
        session.close()


def delete_project_form(
    *, actor: User, project_id: str, form_id: str, expected_version: int
) -> None:
    session = db.session()
    try:
        with session.begin():
            project = _load_project(session, actor, project_id, for_update=True)
            _require_confirm(actor, project)
            form = _load_form(session, project.id, form_id, for_update=True)
            if form.version != expected_version:
                raise ResearchFormServiceError(
                    "stale_version", "Research form has changed. Refresh and try again.", 409
                )
            project_events.record_event(
                session,
                actor,
                "project_research_form_deleted",
                form,
                {"subject_id": form.subject_id, "form_key": form.form_key},
            )
            form.current_revision_id = None
            session.flush()
            revision_ids = select(ProjectResearchFormRevision.id).where(
                ProjectResearchFormRevision.form_id == form.id
            )
            session.execute(
                delete(ProjectResearchAnswer).where(
                    ProjectResearchAnswer.revision_id.in_(revision_ids)
                )
            )
            session.execute(
                update(ProjectResearchFormRevision)
                .where(ProjectResearchFormRevision.form_id == form.id)
                .values(parent_revision_id=None)
            )
            session.execute(
                delete(ProjectResearchFormRevision).where(
                    ProjectResearchFormRevision.form_id == form.id
                )
            )
            session.execute(
                delete(ProjectResearchForm).where(ProjectResearchForm.id == form.id)
            )
    except ResearchFormServiceError:
        raise
    except IntegrityError:
        raise _conflict() from None
    except SQLAlchemyError:
        raise _mutation_failed() from None
    finally:
        session.close()


def reject_form_revision(
    *, actor: User, project_id: str, form_id: str, expected_version: int, review_comment: str
) -> dict[str, Any]:
    """Record a lead/admin review rejection while leaving the draft editable."""
    session = db.session()
    try:
        with session.begin():
            project = _load_project(session, actor, project_id, for_update=True)
            _require_confirm(actor, project)
            form = _load_form(session, project.id, form_id, for_update=True)
            revision = _load_current_revision(session, form, for_update=True)
            definition = _active_definition(project, form)
            _require_mutable_current(revision)
            _require_current_version(revision, expected_version)
            if not isinstance(review_comment, str) or not review_comment.strip():
                raise ResearchFormServiceError("invalid_request", "A return comment is required.", 400)
            revision.returned_by_user_id = actor.id
            revision.returned_at = datetime.now(timezone.utc)
            revision.return_comment = review_comment.strip()
            revision.version += 1
            project_events.record_event(
                session,
                actor,
                "project_research_form_rejected",
                form,
                {"revision_number": revision.revision_number},
            )
            result = _serialize_form(form, definition)
        return result
    except ResearchFormServiceError:
        raise
    except SQLAlchemyError:
        raise _mutation_failed() from None
    finally:
        session.close()


def revise_form(
    *, actor: User, project_id: str, form_id: str, expected_version: int
) -> dict[str, Any]:
    session = db.session()
    try:
        with session.begin():
            project = _load_project(session, actor, project_id, for_update=True)
            _require_fill(actor, project)
            form = _load_form(session, project.id, form_id, for_update=True)
            parent = _load_current_revision(session, form, for_update=True)
            definition = _active_definition(project, form)
            if parent.status != "confirmed":
                raise ResearchFormServiceError(
                    "research_form_not_confirmed",
                    "Only confirmed research forms can be revised.",
                    409,
                )
            _require_current_version(parent, expected_version)
            revision_number = session.scalar(
                select(func.max(ProjectResearchFormRevision.revision_number)).where(
                    ProjectResearchFormRevision.form_id == form.id
                )
            ) or 0
            child = ProjectResearchFormRevision(
                form=form,
                revision_number=revision_number + 1,
                status="draft",
                parent_revision=parent,
                definition_snapshot=deepcopy(
                    parent.definition_snapshot or definition
                ),
            )
            session.add(child)
            session.flush()
            for answer in sorted(parent.answers, key=lambda item: (item.field_key, item.id)):
                session.add(
                    ProjectResearchAnswer(
                        revision=child,
                        source_template_research_field_id=answer.source_template_research_field_id,
                        field_key=answer.field_key,
                        value_json=deepcopy(answer.value_json),
                    )
                )
            form.current_revision = child
            form.version += 1
            session.flush()
            project_events.record_event(
                session,
                actor,
                "project_research_form_revised",
                form,
                {"parent_revision_number": parent.revision_number, "revision_number": child.revision_number},
            )
            result = _serialize_form(form, definition)
        return result
    except ResearchFormServiceError:
        raise
    except IntegrityError:
        raise _conflict() from None
    except SQLAlchemyError:
        raise _mutation_failed() from None
    finally:
        session.close()


def create_project_form(
    *,
    actor: User,
    project_id: str,
    subject_id: str,
    input_mapping: Mapping[str, Any],
) -> dict[str, Any]:
    """Create a self-contained research form bound to a project subject (no template).

    Unlike template-materialized forms, the definition is authored entirely on the
    project and stored in the first revision snapshot, so projects can add forms
    after the immutable template snapshot is frozen.
    """
    form_input = _normalize_project_form(input_mapping)
    session = db.session()
    try:
        with session.begin():
            project = _load_project(session, actor, project_id, for_update=True)
            _require_fill(actor, project)
            subject = _load_subject(session, project.id, subject_id)
            if subject.status == "archived":
                raise ResearchFormServiceError(
                    "research_form_subject_archived",
                    "Archived research subjects cannot receive new forms.",
                    409,
                )
            if subject.subject_type != form_input["subject_type"]:
                raise ResearchFormServiceError(
                    "research_form_subject_type_mismatch",
                    "The research form subject type must match the selected subject.",
                    400,
                )
            definition = _opportunity_identification_definition(_make_fields_optional(_inject_definition_ids(form_input)))
            _raise_definition_issues(
                validate_research_definition({"forms": [definition]})
            )
            project_form = ProjectResearchForm(
                project_id=project.id,
                subject_id=subject.id,
                source_template_research_form_id=None,
                form_key=definition["form_key"],
                name=definition["name"],
                description=definition["description"],
            )
            session.add(project_form)
            session.flush()
            revision = ProjectResearchFormRevision(
                form=project_form,
                revision_number=1,
                status="draft",
                definition_snapshot=deepcopy(definition),
            )
            session.add(revision)
            session.flush()
            project_form.current_revision = revision
            project_events.record_event(
                session,
                actor,
                "project_research_form_created",
                project_form,
                {"subject_id": subject.id, "form_key": project_form.form_key},
            )
            result = _serialize_form(project_form, definition)
        return result
    except ResearchFormServiceError:
        raise
    except IntegrityError:
        raise _conflict() from None
    except SQLAlchemyError:
        raise _mutation_failed() from None
    finally:
        session.close()


def _load_project(session: Session, actor: User, project_id: str, *, for_update: bool = False) -> Project:
    statement = select(Project).where(Project.id == project_id).options(selectinload(Project.members))
    if for_update:
        statement = statement.with_for_update()
    project = session.scalar(statement)
    if project is None or not project_access(actor, project).can_view:
        raise ResearchFormServiceError("project_not_found", "Project was not found.", 404)
    return project


def _load_form(session: Session, project_id: str, form_id: str, *, for_update: bool = False) -> ProjectResearchForm:
    statement = (
        select(ProjectResearchForm)
        .where(ProjectResearchForm.id == form_id, ProjectResearchForm.project_id == project_id)
        .options(selectinload(ProjectResearchForm.current_revision).selectinload(ProjectResearchFormRevision.answers))
    )
    if for_update:
        statement = statement.with_for_update()
    form = session.scalar(statement)
    if form is None:
        raise ResearchFormServiceError("research_form_not_found", "Research form was not found.", 404)
    return form


def _load_current_revision(session: Session, form: ProjectResearchForm, *, for_update: bool) -> ProjectResearchFormRevision:
    if form.current_revision_id is None:
        raise ResearchFormServiceError("research_form_not_found", "Research form has no current revision.", 404)
    statement = (
        select(ProjectResearchFormRevision)
        .where(ProjectResearchFormRevision.id == form.current_revision_id, ProjectResearchFormRevision.form_id == form.id)
        .options(selectinload(ProjectResearchFormRevision.answers))
    )
    if for_update:
        statement = statement.with_for_update()
    revision = session.scalar(statement)
    if revision is None:
        raise ResearchFormServiceError("research_form_not_found", "Research form revision was not found.", 404)
    return revision


def _definition_for_form(project: Project, form: ProjectResearchForm) -> dict[str, Any]:
    snapshot = project.research_snapshot
    forms = snapshot.get("forms") if isinstance(snapshot, dict) else None
    if not isinstance(forms, list):
        raise ResearchFormServiceError("research_form_definition_missing", "Research form definition is unavailable.", 409)
    definition = next((item for item in forms if isinstance(item, dict) and item.get("form_key") == form.form_key), None)
    if definition is None:
        raise ResearchFormServiceError("research_form_definition_missing", "Research form definition is unavailable.", 409)
    return definition


def _stored_definition(project: Project, form: ProjectResearchForm) -> dict[str, Any]:
    revision = form.current_revision
    if revision is not None and isinstance(revision.definition_snapshot, dict) and revision.definition_snapshot:
        return revision.definition_snapshot
    return _definition_for_form(project, form)


def _opportunity_identification_definition(definition: dict[str, Any]) -> dict[str, Any]:
    """Project legacy opportunity forms without mutating historical snapshots.

    Delivery answers remain stored for solution migration and audit. Removing
    them from this projection also excludes obsolete required fields from
    opportunity completion/confirmation and rejects new delivery answer writes.
    """
    if definition.get("subject_type") != "opportunity":
        return definition
    result = deepcopy(definition)
    result["description"] = _DEFAULT_OPPORTUNITY_DEFINITION["description"]
    sections = []
    for section in result.get("sections", []):
        if not isinstance(section, dict):
            continue
        if section.get("section_key") == OPPORTUNITY_SECTION_DELIVERY_KEY or section.get("name") == "交付说明":
            continue
        section["fields"] = [
            field for field in section.get("fields", [])
            if not isinstance(field, dict) or field.get("field_key") not in OPPORTUNITY_DELIVERY_FIELD_KEYS
        ]
        if section["fields"]:
            sections.append(section)
    result["sections"] = sections
    return result


def _active_definition(project: Project, form: ProjectResearchForm) -> dict[str, Any]:
    return _opportunity_identification_definition(_stored_definition(project, form))


def _fields_by_key(definition: dict[str, Any]) -> dict[str, dict[str, Any]]:
    fields: dict[str, dict[str, Any]] = {}
    sections = definition.get("sections")
    if not isinstance(sections, list):
        raise _invalid_answer("Research form definition is invalid.")
    for section in sections:
        if not isinstance(section, dict) or not isinstance(section.get("fields"), list):
            raise _invalid_answer("Research form definition is invalid.")
        for field in section["fields"]:
            if not isinstance(field, dict) or not isinstance(field.get("field_key"), str) or not isinstance(field.get("id"), str):
                raise _invalid_answer("Research form definition is invalid.")
            fields[field["field_key"]] = field
    return fields


def _validate_field_answer(
    field: dict[str, Any], value: object, *, file_reference_validator: FileReferenceValidator
) -> object:
    try:
        return validate_answer(field, value, file_reference_validator=file_reference_validator)
    except ResearchValidationError:
        raise _invalid_answer(field_key=field.get("field_key")) from None


def _visible_field_keys(fields: dict[str, dict[str, Any]], answers: Mapping[str, object]) -> set[str]:
    cache: dict[str, bool] = {}

    def visible(key: str) -> bool:
        if key in cache:
            return cache[key]
        field = fields.get(key)
        if field is None:
            return False
        cache[key] = False
        cache[key] = matches(field.get("condition"))
        return cache[key]

    def matches(condition: object) -> bool:
        if condition is None:
            return True
        if not isinstance(condition, dict):
            return False
        operator = condition.get("operator")
        if operator == "all":
            children = condition.get("conditions")
            return isinstance(children, list) and all(matches(item) for item in children)
        if operator == "any":
            children = condition.get("conditions")
            return isinstance(children, list) and any(matches(item) for item in children)
        key = condition.get("field_key")
        if not isinstance(key, str) or not visible(key):
            return False
        answer = answers.get(key)
        if operator == "is_empty":
            return _answer_is_empty(answer)
        expected = condition.get("value")
        if operator == "equals":
            return answer == expected
        if operator == "not_equals":
            return answer != expected
        if operator == "contains":
            return expected in answer if isinstance(answer, (str, list, dict)) else False
        return False

    return {key for key in fields if visible(key)}


def _condition_matches(condition: object, answers: Mapping[str, object]) -> bool:
    if condition is None:
        return True
    if not isinstance(condition, dict):
        return False
    operator = condition.get("operator")
    if operator == "all":
        children = condition.get("conditions")
        return isinstance(children, list) and all(_condition_matches(item, answers) for item in children)
    if operator == "any":
        children = condition.get("conditions")
        return isinstance(children, list) and any(_condition_matches(item, answers) for item in children)
    key = condition.get("field_key")
    if not isinstance(key, str):
        return False
    answer = answers.get(key)
    if operator == "is_empty":
        return _answer_is_empty(answer)
    expected = condition.get("value")
    if operator == "equals":
        return answer == expected
    if operator == "not_equals":
        return answer != expected
    if operator == "contains":
        return expected in answer if isinstance(answer, (str, list, dict)) else False
    return False


def _answer_is_empty(value: object) -> bool:
    if value is None or value == "" or value == [] or value == {}:
        return True
    if isinstance(value, dict) and value.get("type") == "doc" and isinstance(value.get("content"), list):
        for paragraph in value["content"]:
            if not isinstance(paragraph, dict) or not isinstance(paragraph.get("content"), list):
                return False
            for node in paragraph["content"]:
                if not isinstance(node, dict) or not isinstance(node.get("text"), str):
                    return False
                if normalize_text(node["text"]):
                    return False
        return True
    return False


def _require_mutable_current(revision: ProjectResearchFormRevision) -> None:
    try:
        assert_revision_mutable(revision)
    except ResearchImmutableError:
        raise _immutable() from None
    if revision.status != "draft":
        raise ResearchFormServiceError("research_form_not_draft", "Research form revision is not a draft.", 409)


def _ensure_working_revision(
    session: Session,
    form: ProjectResearchForm,
    revision: ProjectResearchFormRevision,
    definition: dict[str, Any],
) -> ProjectResearchFormRevision:
    """Return an editable revision, copying a legacy confirmed revision on demand."""
    if revision.status == "draft":
        return revision
    return _fork_working_revision(session, form, revision, definition)


def _fork_working_revision(
    session: Session,
    form: ProjectResearchForm,
    revision: ProjectResearchFormRevision,
    definition: dict[str, Any],
) -> ProjectResearchFormRevision:
    revision_number = session.scalar(
        select(func.max(ProjectResearchFormRevision.revision_number)).where(
            ProjectResearchFormRevision.form_id == form.id
        )
    ) or 0
    child = ProjectResearchFormRevision(
        form=form,
        revision_number=revision_number + 1,
        status="draft",
        parent_revision=revision,
        definition_snapshot=deepcopy(revision.definition_snapshot or definition),
    )
    session.add(child)
    session.flush()
    for answer in sorted(revision.answers, key=lambda item: (item.field_key, item.id)):
        session.add(ProjectResearchAnswer(
            revision=child,
            source_template_research_field_id=answer.source_template_research_field_id,
            field_key=answer.field_key,
            value_json=deepcopy(answer.value_json),
        ))
    form.current_revision = child
    form.version += 1
    session.flush()
    session.refresh(child, ["answers"])
    return child


def _require_current_version(revision: ProjectResearchFormRevision, expected_version: int) -> None:
    if revision.version != expected_version:
        raise ResearchFormServiceError("stale_version", "Research form has changed. Refresh and try again.", 409)


def _require_fill(actor: User, project: Project) -> None:
    access = project_access(actor, project)
    if not (access.can_manage or access.can_update_assigned_tasks):
        raise ResearchFormServiceError("forbidden", "You do not have permission to modify this project.", 403)


def _require_confirm(actor: User, project: Project) -> None:
    if not project_access(actor, project).can_manage:
        raise ResearchFormServiceError("forbidden", "You do not have permission to confirm this research form.", 403)


def _require_answers_mapping(changes: Mapping[str, Any]) -> None:
    if not isinstance(changes, Mapping):
        raise _invalid_answer()


def _form_sort_key(project: Project, form: ProjectResearchForm) -> tuple[int, str, str]:
    definition = _active_definition(project, form)
    sort_order = definition.get("sort_order")
    return (sort_order if type(sort_order) is int else 0, form.form_key, form.id)


def _serialize_form(form: ProjectResearchForm, definition: dict[str, Any]) -> dict[str, Any]:
    definition = _opportunity_identification_definition(definition)
    revision = form.current_revision
    fields = _fields_by_key(definition)
    answers = [] if revision is None else [
        {"field_key": answer.field_key, "value": answer.value_json}
        for answer in sorted(revision.answers, key=lambda item: (item.field_key, item.id))
        if definition.get("subject_type") != "opportunity" or answer.field_key in fields
    ]
    values = {item["field_key"]: item["value"] for item in answers}
    visible = _visible_field_keys(fields, values)
    required = sorted(key for key in visible if fields[key].get("is_required") is True)
    return {
        "id": form.id,
        "project_id": form.project_id,
        "subject_id": form.subject_id,
        "form_key": form.form_key,
        "name": form.name,
        "description": definition.get("description", form.description) if definition.get("subject_type") == "opportunity" else form.description,
        "version": form.version,
        "current_revision": None if revision is None else {
            "id": revision.id,
            "revision_number": revision.revision_number,
            "parent_revision_id": revision.parent_revision_id,
            "status": revision.status,
            "version": revision.version,
            "returned_by_user_id": revision.returned_by_user_id,
            "returned_at": revision.returned_at.isoformat() if revision.returned_at else None,
            "return_comment": revision.return_comment,
            "answers": answers,
        },
        "completion": {
            "visible_total": len(visible),
            "answered_visible": sum(1 for key in visible if not _answer_is_empty(values.get(key))),
            "required_total": len(required),
            "required_answered": sum(1 for key in required if not _answer_is_empty(values.get(key))),
            "missing_required_count": sum(1 for key in required if _answer_is_empty(values.get(key))),
            "completion_rate": 100 if not visible else round(100 * sum(1 for key in visible if not _answer_is_empty(values.get(key))) / len(visible)),
            "visible_required_field_keys": required,
            "missing_required_field_keys": [key for key in required if _answer_is_empty(values.get(key))],
            "answered_visible_field_count": sum(1 for key in visible if not _answer_is_empty(values.get(key))),
        },
        "definition_snapshot": deepcopy(definition),
    }


def _invalid_answer(message: str = "The research answer is invalid.", field_key: object = None) -> ResearchFormServiceError:
    details = {"field_key": field_key, "reason": "invalid_value"} if isinstance(field_key, str) else None
    return ResearchFormServiceError("invalid_research_answer", message, 422, details)


def _immutable() -> ResearchFormServiceError:
    return ResearchFormServiceError("research_form_immutable", "Confirmed research revisions are immutable.", 409)


def _conflict() -> ResearchFormServiceError:
    return ResearchFormServiceError("research_form_conflict", "Research form update conflicted with another change.", 409)


def _mutation_failed() -> ResearchFormServiceError:
    return ResearchFormServiceError("research_form_mutation_failed", "Unable to update research form at this time.", 503)


_PROJECT_FORM_KEYS = frozenset(
    {"form_key", "name", "description", "subject_type", "module_key", "sort_order", "sections"}
)


def _normalize_project_form(input_mapping: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(input_mapping, Mapping) or set(input_mapping) - _PROJECT_FORM_KEYS:
        raise _invalid_definition()
    form = dict(input_mapping)
    if not isinstance(form.get("subject_type"), str):
        raise _invalid_definition()
    if type(form.get("sort_order", 0)) is not int:
        raise _invalid_definition()
    return form


def _inject_definition_ids(form_input: dict[str, Any]) -> dict[str, Any]:
    definition = deepcopy(form_input)
    definition.setdefault("id", new_uuid())
    definition.setdefault("sort_order", 0)
    sections_in = definition.get("sections")
    sections: list[dict[str, Any]] = []
    if isinstance(sections_in, list):
        for section_index, section_in in enumerate(sections_in):
            if not isinstance(section_in, dict):
                continue
            section: dict[str, Any] = deepcopy(section_in)
            section.setdefault("id", new_uuid())
            section.setdefault("sort_order", (section_index + 1) * 10)
            fields_in = section.get("fields")
            fields: list[dict[str, Any]] = []
            if isinstance(fields_in, list):
                for field_index, field_in in enumerate(fields_in):
                    if not isinstance(field_in, dict):
                        continue
                    field: dict[str, Any] = deepcopy(field_in)
                    field.setdefault("id", new_uuid())
                    field.setdefault("sort_order", (field_index + 1) * 10)
                    fields.append(field)
            section["fields"] = fields
            sections.append(section)
    definition["sections"] = sections
    return definition


def _make_fields_optional(definition: dict[str, Any]) -> dict[str, Any]:
    normalized = deepcopy(definition)
    for section in normalized.get("sections", []):
        if not isinstance(section, dict):
            continue
        for field in section.get("fields", []):
            if isinstance(field, dict):
                field["is_required"] = False
    return normalized


def _opportunity_default_definition() -> dict[str, Any]:
    return _inject_definition_ids(_DEFAULT_OPPORTUNITY_DEFINITION)


def _load_subject(
    session: Session, project_id: str, subject_id: str, *, for_update: bool = False
) -> ProjectResearchSubject:
    statement = select(ProjectResearchSubject).where(
        ProjectResearchSubject.project_id == project_id,
        ProjectResearchSubject.id == subject_id,
    )
    if for_update:
        statement = statement.with_for_update()
    subject = session.scalar(statement)
    if subject is None:
        raise ResearchFormServiceError(
            "research_subject_not_found",
            "Research subject was not found.",
            404,
        )
    return subject


def _raise_definition_issues(issues: list[DefinitionIssue]) -> None:
    if issues:
        raise ResearchFormServiceError(
            "invalid_research_definition",
            "The research form definition is invalid.",
            400,
            {"issues": [{"code": issue.code, "path": issue.path} for issue in issues]},
        )


def _invalid_definition() -> ResearchFormServiceError:
    return ResearchFormServiceError(
        "invalid_request", "The research form definition is invalid.", 400
    )
