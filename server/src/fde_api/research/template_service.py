from __future__ import annotations

from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, selectinload

from fde_api.auth.models import User
from fde_api.extensions import db
from fde_api.research.definitions import DefinitionIssue, validate_research_definition
from fde_api.research.models import (
    TemplateResearchField,
    TemplateResearchForm,
    TemplateResearchSection,
)
from fde_api.templates.service import TemplateServiceError
from fde_api.workbench.models import IndustryTemplateVersion
from fde_api.workbench.models import ModuleCatalog, TemplateModule


def snapshot_research_definition(
    *,
    version_id: str,
    session: Session,
    template_id: str | None = None,
    published_only: bool = False,
) -> dict[str, Any]:
    version = _load_version(session, version_id)
    if version is None:
        raise _not_found()
    if template_id is not None and version.template_id != template_id:
        raise _not_found()
    if published_only and (version.status != "published" or version.template.status != "active"):
        raise TemplateServiceError(
            "forbidden", "You do not have permission to access this resource.", 403
        )
    return _snapshot_from_version(version)


def create_research_form(
    *,
    actor: User,
    template_id: str,
    version_id: str,
    expected_version: int,
    form: dict[str, Any],
) -> dict[str, Any]:
    session = db.session()
    try:
        with session.begin():
            version = _load_version(session, version_id, for_update=True)
            _assert_editable_version(version, template_id)
            assert version is not None
            _require_current_version(version, expected_version)
            definition = _snapshot_from_version(version)
            definition["forms"].append(form)
            _raise_definition_issues(validate_research_definition(definition))
            _validate_definition_module_keys(session, version.id, definition)
            _insert_form(session, version.id, form)
            version.version += 1
            saved_id = version.id
            saved_version = version.version
            _record_definition_event(
                session, actor, "industry_template_research_definition_created", version
            )
        session.expire_all()
        return _mutation_snapshot(session, saved_id, saved_version)
    except TemplateServiceError:
        raise
    except SQLAlchemyError:
        raise _mutation_failed() from None
    finally:
        session.close()


def replace_research_definition(
    *,
    actor: User,
    template_id: str,
    version_id: str,
    expected_version: int,
    definition: dict[str, Any],
) -> dict[str, Any]:
    session = db.session()
    try:
        with session.begin():
            version = _load_version(session, version_id, for_update=True)
            _assert_editable_version(version, template_id)
            assert version is not None
            _require_current_version(version, expected_version)
            _raise_definition_issues(validate_research_definition(definition))
            _validate_definition_module_keys(session, version.id, definition)
            _assert_ids_keep_stable_keys(version, definition["forms"])
            _sync_forms(session, version, definition["forms"])
            version.version += 1
            saved_id = version.id
            saved_version = version.version
            _record_definition_event(
                session, actor, "industry_template_research_definition_replaced", version
            )
        session.expire_all()
        return _mutation_snapshot(session, saved_id, saved_version)
    except TemplateServiceError:
        raise
    except SQLAlchemyError:
        raise _mutation_failed() from None
    finally:
        session.close()


def delete_research_definition(
    *, actor: User, template_id: str, version_id: str, expected_version: int
) -> int:
    session = db.session()
    try:
        with session.begin():
            version = _load_version(session, version_id, for_update=True)
            _assert_editable_version(version, template_id)
            assert version is not None
            _require_current_version(version, expected_version)
            _delete_forms(session, version.id)
            version.version += 1
            saved_version = version.version
            _record_definition_event(
                session, actor, "industry_template_research_definition_deleted", version
            )
        return saved_version
    except TemplateServiceError:
        raise
    except SQLAlchemyError:
        raise _mutation_failed() from None
    finally:
        session.close()


def validate_persisted_research_definition(session: Session, version_id: str) -> None:
    definition = snapshot_research_definition(version_id=version_id, session=session)
    _raise_definition_issues(validate_research_definition(definition))
    _validate_definition_module_keys(session, version_id, definition)


def _validate_definition_module_keys(session: Session, version_id: str, definition: dict[str, Any]) -> None:
    valid = set(session.scalars(select(ModuleCatalog.module_key).join(TemplateModule).where(TemplateModule.template_version_id == version_id)))
    issues = [
        DefinitionIssue("unknown_form_module_key", f"forms[{index}].module_key", "Form module_key must belong to this template version.")
        for index, form in enumerate(definition.get("forms", []))
        if isinstance(form, dict) and form.get("module_key") is not None and form.get("module_key") not in valid
    ]
    _raise_definition_issues(issues)


def copy_research_definition(
    session: Session, *, source_version_id: str, target_version_id: str
) -> None:
    """Copy immutable definition rows while the caller owns the version transaction."""
    source = _load_version(session, source_version_id)
    if source is None:
        raise _not_found()
    for form in _snapshot_from_version(source)["forms"]:
        _insert_form(session, target_version_id, _without_ids(form))


def insert_research_definition(
    session: Session, *, version_id: str, definition: dict[str, Any]
) -> None:
    """Validate and insert a complete definition inside the caller's transaction."""
    _raise_definition_issues(validate_research_definition(definition))
    _validate_definition_module_keys(session, version_id, definition)
    for form in definition["forms"]:
        _insert_form(session, version_id, form)


def _mutation_snapshot(
    session: Session, version_id: str, version: int
) -> dict[str, Any]:
    snapshot = snapshot_research_definition(version_id=version_id, session=session)
    snapshot["version"] = version
    return snapshot


def _record_definition_event(
    session: Session, actor: User, event_type: str, version: IndustryTemplateVersion
) -> None:
    from fde_api.projects.events import record_event

    record_event(session, actor, event_type, version, {"research_definition": event_type})


def _load_version(session: Session, version_id: str, *, for_update: bool = False) -> IndustryTemplateVersion | None:
    statement = (
        select(IndustryTemplateVersion)
        .where(IndustryTemplateVersion.id == version_id)
        .options(
            selectinload(IndustryTemplateVersion.template),
            selectinload(IndustryTemplateVersion.research_forms).selectinload(TemplateResearchForm.sections).selectinload(TemplateResearchSection.fields),
        )
    )
    if for_update:
        statement = statement.with_for_update()
    return session.scalar(statement)


def _snapshot_from_version(version: IndustryTemplateVersion) -> dict[str, Any]:
    return {
        "forms": [
            {
                "id": form.id,
                "form_key": form.form_key,
                "name": form.name,
                "description": form.description,
                "subject_type": form.subject_type,
                "module_key": form.module_key,
                "sort_order": form.sort_order,
                "sections": [
                    {
                        "id": section.id,
                        "section_key": section.section_key,
                        "name": section.name,
                        "description": section.description,
                        "sort_order": section.sort_order,
                        "fields": [
                            _serialize_field(field)
                            for field in sorted(
                                section.fields,
                                key=lambda item: (item.sort_order, item.field_key),
                            )
                        ],
                    }
                    for section in sorted(
                        form.sections,
                        key=lambda item: (item.sort_order, item.section_key),
                    )
                ],
            }
            for form in sorted(
                version.research_forms,
                key=lambda item: (item.sort_order, item.form_key),
            )
        ]
    }


def _serialize_field(field: TemplateResearchField) -> dict[str, Any]:
    config = field.options_json or {}
    result = {
        "id": field.id,
        "field_key": field.field_key,
        "name": field.name,
        "help_text": field.help_text,
        "type": field.field_type,
        "is_required": field.is_required,
        "options": config.get("options", {}),
        "sort_order": field.sort_order,
    }
    if "condition" in config:
        result["condition"] = config["condition"]
    return result


def _insert_form(session: Session, version_id: str, form_input: dict[str, Any]) -> None:
    form = TemplateResearchForm(
        template_version_id=version_id,
        form_key=form_input["form_key"],
        name=form_input["name"].strip(),
        description=form_input.get("description", ""),
        subject_type=form_input["subject_type"],
        module_key=form_input.get("module_key"),
        sort_order=form_input.get("sort_order", 0),
    )
    session.add(form)
    session.flush()
    for section_input in form_input["sections"]:
        section = TemplateResearchSection(
            form_id=form.id,
            section_key=section_input["section_key"],
            name=section_input["name"].strip(),
            description=section_input.get("description", ""),
            sort_order=section_input.get("sort_order", 0),
        )
        session.add(section)
        session.flush()
        for field_input in section_input["fields"]:
            config: dict[str, Any] = {"options": field_input["options"]}
            if "condition" in field_input:
                config["condition"] = field_input["condition"]
            session.add(
                TemplateResearchField(
                    section_id=section.id,
                    field_key=field_input["field_key"],
                    name=field_input["name"].strip(),
                    help_text=field_input.get("help_text", ""),
                    field_type=field_input["type"],
                    is_required=field_input["is_required"],
                    options_json=config,
                    sort_order=field_input.get("sort_order", 0),
                )
            )


def _without_ids(form: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in form.items()
        if key != "id"
    } | {
        "sections": [
            {key: value for key, value in section.items() if key != "id"}
            | {
                "fields": [
                    {key: value for key, value in field.items() if key != "id"}
                    for field in section["fields"]
                ]
            }
            for section in form["sections"]
        ]
    }


def _assert_ids_keep_stable_keys(
    version: IndustryTemplateVersion, forms: list[dict[str, Any]]
) -> None:
    forms_by_id = {form.id: form for form in version.research_forms}
    for form_input in forms:
        form = _by_id(forms_by_id, form_input.get("id"))
        if form is None:
            continue
        if form.form_key != form_input["form_key"]:
            raise _stable_key_error()
        sections_by_id = {section.id: section for section in form.sections}
        for section_input in form_input["sections"]:
            section = _by_id(sections_by_id, section_input.get("id"))
            if section is None:
                continue
            if section.section_key != section_input["section_key"]:
                raise _stable_key_error()
            fields_by_id = {field.id: field for field in section.fields}
            for field_input in section_input["fields"]:
                field = _by_id(fields_by_id, field_input.get("id"))
                if field is not None and field.field_key != field_input["field_key"]:
                    raise _stable_key_error()


def _by_id(items: dict[str, Any], value: object) -> Any | None:
    if value is None:
        return None
    if not isinstance(value, str) or value not in items:
        raise _stable_key_error()
    return items[value]


def _sync_forms(
    session: Session, version: IndustryTemplateVersion, form_inputs: list[dict[str, Any]]
) -> None:
    forms_by_id = {form.id: form for form in version.research_forms}
    forms_by_key = {form.form_key: form for form in version.research_forms}
    seen: set[str] = set()
    for form_input in form_inputs:
        form = _by_id(forms_by_id, form_input.get("id")) or forms_by_key.get(
            form_input["form_key"]
        )
        if form is None:
            _insert_form(session, version.id, form_input)
            continue
        seen.add(form.id)
        form.name = form_input["name"].strip()
        form.description = form_input.get("description", "")
        form.subject_type = form_input["subject_type"]
        form.module_key = form_input.get("module_key")
        form.sort_order = form_input.get("sort_order", 0)
        _sync_sections(session, form, form_input["sections"])
    _delete_form_ids(session, [form.id for form in version.research_forms if form.id not in seen])


def _sync_sections(
    session: Session, form: TemplateResearchForm, section_inputs: list[dict[str, Any]]
) -> None:
    sections_by_id = {section.id: section for section in form.sections}
    sections_by_key = {section.section_key: section for section in form.sections}
    seen: set[str] = set()
    for section_input in section_inputs:
        section = _by_id(sections_by_id, section_input.get("id")) or sections_by_key.get(
            section_input["section_key"]
        )
        if section is None:
            _insert_section(session, form.id, section_input)
            continue
        seen.add(section.id)
        section.name = section_input["name"].strip()
        section.description = section_input.get("description", "")
        section.sort_order = section_input.get("sort_order", 0)
        _sync_fields(session, section, section_input["fields"])
    _delete_section_ids(session, [section.id for section in form.sections if section.id not in seen])


def _sync_fields(
    session: Session, section: TemplateResearchSection, field_inputs: list[dict[str, Any]]
) -> None:
    fields_by_id = {field.id: field for field in section.fields}
    fields_by_key = {field.field_key: field for field in section.fields}
    seen: set[str] = set()
    for field_input in field_inputs:
        field = _by_id(fields_by_id, field_input.get("id")) or fields_by_key.get(
            field_input["field_key"]
        )
        if field is None:
            _insert_field(session, section.id, field_input)
            continue
        seen.add(field.id)
        _update_field(field, field_input)
    missing_ids = [field.id for field in section.fields if field.id not in seen]
    if missing_ids:
        session.execute(delete(TemplateResearchField).where(TemplateResearchField.id.in_(missing_ids)))


def _insert_section(
    session: Session, form_id: str, section_input: dict[str, Any]
) -> None:
    section = TemplateResearchSection(
        form_id=form_id,
        section_key=section_input["section_key"],
        name=section_input["name"].strip(),
        description=section_input.get("description", ""),
        sort_order=section_input.get("sort_order", 0),
    )
    session.add(section)
    session.flush()
    for field_input in section_input["fields"]:
        _insert_field(session, section.id, field_input)


def _insert_field(
    session: Session, section_id: str, field_input: dict[str, Any]
) -> None:
    field = TemplateResearchField(section_id=section_id, field_key=field_input["field_key"])
    _update_field(field, field_input)
    session.add(field)


def _update_field(field: TemplateResearchField, field_input: dict[str, Any]) -> None:
    field.name = field_input["name"].strip()
    field.help_text = field_input.get("help_text", "")
    field.field_type = field_input["type"]
    field.is_required = field_input["is_required"]
    field.sort_order = field_input.get("sort_order", 0)
    field.options_json = {
        "options": field_input["options"],
        **({"condition": field_input["condition"]} if "condition" in field_input else {}),
    }


def _delete_forms(session: Session, version_id: str) -> None:
    form_ids = list(session.scalars(select(TemplateResearchForm.id).where(TemplateResearchForm.template_version_id == version_id)))
    _delete_form_ids(session, form_ids)


def _delete_form_ids(session: Session, form_ids: list[str]) -> None:
    if not form_ids:
        return
    section_ids = list(
        session.scalars(
            select(TemplateResearchSection.id).where(
                TemplateResearchSection.form_id.in_(form_ids)
            )
        )
    )
    _delete_section_ids(session, section_ids)
    session.execute(
        delete(TemplateResearchForm).where(TemplateResearchForm.id.in_(form_ids))
    )
    session.flush()


def _delete_section_ids(session: Session, section_ids: list[str]) -> None:
    if not section_ids:
        return
    session.execute(
        delete(TemplateResearchField).where(
            TemplateResearchField.section_id.in_(section_ids)
        )
    )
    session.execute(
        delete(TemplateResearchSection).where(
            TemplateResearchSection.id.in_(section_ids)
        )
    )
    session.flush()


def _assert_editable_version(version: IndustryTemplateVersion | None, template_id: str) -> None:
    if version is None or version.template_id != template_id:
        raise _not_found()
    if version.status != "draft":
        raise TemplateServiceError(
            "template_version_immutable",
            "Published and inactive template versions cannot be changed or deleted.",
            409,
        )


def _raise_definition_issues(issues: list[DefinitionIssue]) -> None:
    if issues:
        raise TemplateServiceError(
            "invalid_research_definition",
            "The research definition is invalid.",
            400,
            {"issues": [{"code": issue.code, "path": issue.path} for issue in issues]},
        )


def _not_found() -> TemplateServiceError:
    return TemplateServiceError("template_version_not_found", "Template version was not found.", 404)


def _stable_key_error() -> TemplateServiceError:
    return TemplateServiceError("stable_key_immutable", "Stable keys cannot be changed after creation.", 400)


def _require_current_version(
    version: IndustryTemplateVersion, expected_version: int
) -> None:
    if version.version != expected_version:
        raise TemplateServiceError(
            "stale_version",
            "The template version has been updated. Refresh and try again.",
            409,
        )


def _mutation_failed() -> TemplateServiceError:
    return TemplateServiceError(
        "template_research_update_failed",
        "Unable to update the research definition at this time.",
        503,
    )
