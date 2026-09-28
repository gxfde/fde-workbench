from __future__ import annotations

from datetime import UTC, datetime
import re
from typing import Any, TypedDict

from sqlalchemy import delete, func, or_, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session, selectinload

from fde_api.auth.models import User, VALID_ROLES
from fde_api.extensions import db
from fde_api.workbench.models import (
    IndustryTemplate,
    IndustryTemplateVersion,
    ModuleCatalog,
    TemplateModule,
    TemplateTask,
    TemplateTaskDependency,
)
from fde_api.workbench.scheduling import ScheduleTask, SchedulingError, validate_acyclic


STABLE_KEY_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")


class TemplateTaskInput(TypedDict):
    task_key: str
    name: str
    description: str
    duration_days: int
    default_assignee_role: str
    sort_order: int
    dependency_keys: list[str]


class TemplateModuleInput(TypedDict):
    module_key: str
    name: str
    description: str
    sort_order: int
    tasks: list[TemplateTaskInput]


class TemplateVersionInput(TypedDict):
    modules: list[TemplateModuleInput]


class TemplateServiceError(Exception):
    def __init__(self, code: str, message: str, status: int, details: dict | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status
        self.details = details


def list_template_versions(
    *,
    template_id: str | None,
    include_unpublished: bool,
    page: int,
    page_size: int,
) -> tuple[list[dict[str, Any]], int]:
    session = db.session()
    try:
        filters = []
        if template_id is not None:
            filters.append(IndustryTemplateVersion.template_id == template_id)
        if not include_unpublished:
            filters.extend(
                [
                    IndustryTemplateVersion.status == "published",
                    IndustryTemplate.status == "active",
                ]
            )
        statement = (
            select(IndustryTemplateVersion)
            .join(IndustryTemplateVersion.template)
            .where(*filters)
            .order_by(
                IndustryTemplateVersion.name,
                IndustryTemplateVersion.version_number.desc(),
                IndustryTemplateVersion.id,
            )
        )
        versions = list(
            session.scalars(
                statement.offset((page - 1) * page_size).limit(page_size)
            )
        )
        total = session.scalar(
            select(func.count())
            .select_from(IndustryTemplateVersion)
            .join(IndustryTemplateVersion.template)
            .where(*filters)
        )
        return [
            _serialize_template_version(session, _load_version(session, version.id))
            for version in versions
        ], int(total or 0)
    finally:
        session.close()


def get_template_version(*, version_id: str) -> IndustryTemplateVersion:
    session = db.session()
    try:
        version = session.get(IndustryTemplateVersion, version_id)
        if version is None:
            raise _not_found_error()
        return version
    finally:
        session.close()


def get_template_version_dto(
    *, version_id: str, include_unpublished: bool
) -> dict[str, Any]:
    session = db.session()
    try:
        version = _load_version(session, version_id)
        if version is None:
            raise _not_found_error()
        if not include_unpublished and (
            version.status != "published" or version.template.status != "active"
        ):
            raise TemplateServiceError(
                "forbidden", "You do not have permission to access this resource.", 403
            )
        return _serialize_template_version(session, version)
    finally:
        session.close()


def create_template(
    *,
    actor: User,
    name: str,
    industry_name: str,
    description: str,
    modules: list[dict[str, Any]],
) -> IndustryTemplateVersion:
    normalized_name = _required_text(name, maximum=160)
    normalized_industry = _required_text(industry_name, maximum=160)
    normalized_description = _text(description)

    session = db.session()
    try:
        with session.begin():
            normalized_modules, catalogs = _validate_document_input(session, modules)
            template = IndustryTemplate(
                name=normalized_name,
                industry_name=normalized_industry,
                description=normalized_description,
                status="active",
            )
            version = IndustryTemplateVersion(
                template=template,
                name=normalized_name,
                industry_name=normalized_industry,
                description=normalized_description,
                version_number=1,
                status="draft",
            )
            session.add(version)
            session.flush()
            _insert_children(session, version, normalized_modules, catalogs)
            from fde_api.projects.events import record_event

            record_event(
                session,
                actor,
                "industry_template_version_created",
                version,
                {
                    "template_id": version.template_id,
                    "version_number": version.version_number,
                    "status": version.status,
                },
            )
            version_id = version.id
        return get_template_version(version_id=version_id)
    except TemplateServiceError:
        raise
    except IntegrityError:
        raise TemplateServiceError(
            "template_conflict", "The template could not be created due to a conflict.", 409
        ) from None
    except SQLAlchemyError:
        raise TemplateServiceError(
            "template_creation_failed", "Unable to create the template at this time.", 503
        ) from None
    finally:
        session.close()


def create_ai_template_draft(
    *, actor: User, generated: dict[str, Any]
) -> dict[str, Any]:
    """Create an AI-generated v1 draft and optional research forms atomically."""
    session = db.session()
    try:
        with session.begin():
            active_module_keys = set(
                session.scalars(
                    select(ModuleCatalog.module_key).where(ModuleCatalog.is_active.is_(True))
                )
            )
            from fde_api.ai.industry_template_schema import (
                AIContractError,
                validate_generated_template,
            )

            try:
                normalized = validate_generated_template(
                    generated, active_module_keys=active_module_keys
                )
            except AIContractError as error:
                raise TemplateServiceError(
                    "ai_output_invalid",
                    f"AI 生成内容不符合要求：{error.message}",
                    400,
                    {"path": error.path, "issue_code": error.code},
                ) from error
            normalized_modules, catalogs = _validate_document_input(
                session, normalized["modules"]
            )
            template = IndustryTemplate(
                name=normalized["name"],
                industry_name=normalized["industry_name"],
                description=normalized["description"],
                status="active",
            )
            version = IndustryTemplateVersion(
                template=template,
                name=normalized["name"],
                industry_name=normalized["industry_name"],
                description=normalized["description"],
                version_number=1,
                status="draft",
            )
            session.add(version)
            session.flush()
            _insert_children(session, version, normalized_modules, catalogs)
            if normalized["research_definition"] is not None:
                from fde_api.research.template_service import insert_research_definition

                insert_research_definition(
                    session,
                    version_id=version.id,
                    definition=normalized["research_definition"],
                )
            from fde_api.projects.events import record_event

            record_event(
                session,
                actor,
                "industry_template_ai_draft_created",
                version,
                {"template_id": version.template_id, "version_number": 1},
            )
            version_id = version.id
        return get_template_version_dto(
            version_id=version_id, include_unpublished=True
        )
    except TemplateServiceError:
        raise
    except IntegrityError:
        raise TemplateServiceError(
            "template_conflict", "模板创建发生冲突，请修改名称或重试。", 409
        ) from None
    except SQLAlchemyError:
        raise TemplateServiceError(
            "template_creation_failed", "暂时无法创建模板草稿，请稍后重试。", 503
        ) from None
    finally:
        session.close()


def update_draft_version(
    *,
    actor: User,
    version_id: str,
    expected_version: int,
    name: str | None = None,
    industry_name: str | None = None,
    description: str | None = None,
    modules: list[dict[str, Any]] | None = None,
) -> IndustryTemplateVersion:
    normalized_name = _required_text(name, maximum=160) if name is not None else None
    normalized_industry = (
        _required_text(industry_name, maximum=160)
        if industry_name is not None
        else None
    )
    normalized_description = _text(description) if description is not None else None

    session = db.session()
    try:
        with session.begin():
            version = session.scalar(
                select(IndustryTemplateVersion)
                .where(IndustryTemplateVersion.id == version_id)
                .with_for_update()
            )
            if version is None:
                raise _not_found_error()
            if version.status not in {"draft", "published"}:
                raise _immutable_error()
            if version.version != expected_version:
                raise TemplateServiceError(
                    "stale_version",
                    "The template draft has been updated. Refresh and try again.",
                    409,
                )
            normalized_modules: list[TemplateModuleInput] | None = None
            catalogs: dict[str, ModuleCatalog] | None = None
            if modules is not None:
                normalized_modules, catalogs = _validate_document_input(session, modules)
            applied_changes: dict[str, Any] = {}
            if normalized_name is not None:
                applied_changes["name"] = {"from": version.name, "to": normalized_name}
                version.name = normalized_name
            if normalized_industry is not None:
                applied_changes["industry_name"] = {
                    "from": version.industry_name,
                    "to": normalized_industry,
                }
                version.industry_name = normalized_industry
            if normalized_description is not None:
                applied_changes["description"] = {
                    "from": version.description,
                    "to": normalized_description,
                }
                version.description = normalized_description
            if normalized_modules is not None:
                assert catalogs is not None
                applied_changes["modules_replaced"] = True
                _delete_version_children(session, version.id)
                _insert_children(session, version, normalized_modules, catalogs)
            version.version += 1
            if applied_changes:
                from fde_api.projects.events import record_event

                record_event(
                    session,
                    actor,
                    "industry_template_version_updated",
                    version,
                    applied_changes,
                )
            saved_id = version.id
        return get_template_version(version_id=saved_id)
    except TemplateServiceError:
        raise
    except IntegrityError:
        raise TemplateServiceError(
            "template_conflict", "The template could not be updated due to a conflict.", 409
        ) from None
    except SQLAlchemyError:
        raise TemplateServiceError(
            "template_update_failed", "Unable to update the template at this time.", 503
        ) from None
    finally:
        session.close()


def copy_template_version(*, template_id: str) -> IndustryTemplateVersion:
    session = db.session()
    try:
        with session.begin():
            template = session.scalar(
                select(IndustryTemplate)
                .where(IndustryTemplate.id == template_id)
                .with_for_update()
            )
            if template is None:
                raise TemplateServiceError(
                    "template_not_found", "Template was not found.", 404
                )
            versions = list(
                session.scalars(
                    select(IndustryTemplateVersion)
                    .where(IndustryTemplateVersion.template_id == template_id)
                    .order_by(IndustryTemplateVersion.version_number.desc())
                )
            )
            if not versions:
                raise TemplateServiceError(
                    "template_version_not_found", "Template version was not found.", 404
                )
            if any(version.status == "draft" for version in versions):
                raise TemplateServiceError(
                    "template_draft_exists",
                    "This template already has an editable draft.",
                    409,
                )
            source = versions[0]
            source_snapshot = _snapshot_from_loaded(
                session, _load_version(session, source.id)
            )
            copied = IndustryTemplateVersion(
                template=template,
                name=source.name,
                industry_name=source.industry_name,
                description=source.description,
                version_number=source.version_number + 1,
                status="draft",
            )
            session.add(copied)
            session.flush()
            normalized_modules = _modules_from_snapshot(source_snapshot)
            catalogs = _catalogs_by_key(
                session, [module["module_key"] for module in normalized_modules]
            )
            _insert_children(session, copied, normalized_modules, catalogs)
            from fde_api.research.template_service import copy_research_definition

            copy_research_definition(
                session,
                source_version_id=source.id,
                target_version_id=copied.id,
            )
            copied_id = copied.id
        return get_template_version(version_id=copied_id)
    except TemplateServiceError:
        raise
    except IntegrityError:
        raise TemplateServiceError(
            "template_version_conflict",
            "The next template version could not be created due to a conflict.",
            409,
        ) from None
    except SQLAlchemyError:
        raise TemplateServiceError(
            "template_copy_failed", "Unable to copy the template at this time.", 503
        ) from None
    finally:
        session.close()


def publish_template_version(
    *, actor: User, version_id: str, expected_version: int
) -> IndustryTemplateVersion:
    session = db.session()
    try:
        with session.begin():
            version = session.scalar(
                select(IndustryTemplateVersion)
                .where(IndustryTemplateVersion.id == version_id)
                .with_for_update()
            )
            if version is None:
                raise _not_found_error()
            _require_current_version(version, expected_version)
            if version.status != "draft":
                raise _immutable_error()
            _validate_template_version(session, version)
            from fde_api.research.template_service import (
                validate_persisted_research_definition,
            )

            validate_persisted_research_definition(session, version.id)
            version.status = "published"
            version.published_by_user_id = actor.id
            version.published_at = datetime.now(UTC)
            version.template.status = "active"
            version.template.name = version.name
            version.template.industry_name = version.industry_name
            version.template.description = version.description
            version.template.latest_published_version_number = version.version_number
            version.version += 1
            from fde_api.projects.events import record_event

            record_event(
                session,
                actor,
                "industry_template_version_published",
                version,
                {
                    "status": {"from": "draft", "to": "published"},
                    "version_number": version.version_number,
                },
            )
            saved_id = version.id
        return get_template_version(version_id=saved_id)
    except TemplateServiceError:
        raise
    except SQLAlchemyError:
        raise TemplateServiceError(
            "template_publish_failed", "Unable to publish the template at this time.", 503
        ) from None
    finally:
        session.close()


def deactivate_template_version(
    *, actor: User, version_id: str, expected_version: int
) -> IndustryTemplateVersion:
    session = db.session()
    try:
        with session.begin():
            version = session.scalar(
                select(IndustryTemplateVersion)
                .where(IndustryTemplateVersion.id == version_id)
                .with_for_update()
            )
            if version is None:
                raise _not_found_error()
            _require_current_version(version, expected_version)
            if version.status != "published":
                raise TemplateServiceError(
                    "template_version_not_published",
                    "Only a published template version can be deactivated.",
                    409,
                )
            version.status = "inactive"
            latest = session.scalar(
                select(func.max(IndustryTemplateVersion.version_number)).where(
                    IndustryTemplateVersion.template_id == version.template_id,
                    IndustryTemplateVersion.id != version.id,
                    IndustryTemplateVersion.status == "published",
                )
            )
            version.template.latest_published_version_number = latest
            if latest is None:
                version.template.status = "inactive"
            else:
                previous = session.scalar(
                    select(IndustryTemplateVersion).where(
                        IndustryTemplateVersion.template_id == version.template_id,
                        IndustryTemplateVersion.version_number == latest,
                        IndustryTemplateVersion.status == "published",
                    )
                )
                assert previous is not None
                version.template.name = previous.name
                version.template.industry_name = previous.industry_name
                version.template.description = previous.description
            version.version += 1
            from fde_api.projects.events import record_event

            record_event(
                session,
                actor,
                "industry_template_version_deactivated",
                version,
                {"status": {"from": "published", "to": "inactive"}},
            )
            saved_id = version.id
        return get_template_version(version_id=saved_id)
    except TemplateServiceError:
        raise
    except SQLAlchemyError:
        raise TemplateServiceError(
            "template_deactivate_failed",
            "Unable to deactivate the template at this time.",
            503,
        ) from None
    finally:
        session.close()


def delete_draft_version(*, version_id: str, expected_version: int) -> None:
    session = db.session()
    try:
        with session.begin():
            version = session.scalar(
                select(IndustryTemplateVersion)
                .where(IndustryTemplateVersion.id == version_id)
                .with_for_update()
            )
            if version is None:
                raise _not_found_error()
            _require_current_version(version, expected_version)
            if version.status != "draft":
                raise _immutable_error()
            template = version.template
            other_count = int(
                session.scalar(
                    select(func.count())
                    .select_from(IndustryTemplateVersion)
                    .where(
                        IndustryTemplateVersion.template_id == version.template_id,
                        IndustryTemplateVersion.id != version.id,
                    )
                )
                or 0
            )
            _delete_version_children(session, version.id)
            session.delete(version)
            session.flush()
            if other_count == 0:
                session.delete(template)
    except TemplateServiceError:
        raise
    except SQLAlchemyError:
        raise TemplateServiceError(
            "template_delete_failed", "Unable to delete the draft at this time.", 503
        ) from None
    finally:
        session.close()


def serialize_template_snapshot(
    *, session: Session, version_id: str
) -> dict[str, Any]:
    loaded = _load_version(session, version_id)
    if loaded is None:
        raise _not_found_error()
    return _snapshot_from_loaded(session, loaded)


def read_published_template_snapshot(
    *, session: Session, version_id: str
) -> dict[str, Any]:
    """Lock and serialize one selectable published version in the caller's transaction."""
    loaded = _load_version(session, version_id, for_update=True)
    if loaded is None:
        raise _not_found_error()
    if loaded.status != "published" or loaded.template.status != "active":
        raise TemplateServiceError(
            "template_version_not_published",
            "Only an active published template version can create a project.",
            409,
        )
    return _snapshot_from_loaded(session, loaded)


def serialize_template_version(version: IndustryTemplateVersion) -> dict[str, Any]:
    session = db.session()
    try:
        loaded = _load_version(session, version.id)
        if loaded is None:
            raise _not_found_error()
        return _serialize_template_version(session, loaded)
    finally:
        session.close()


def _validate_document_input(
    session: Session, modules: object
) -> tuple[list[TemplateModuleInput], dict[str, ModuleCatalog]]:
    if not isinstance(modules, list):
        raise _invalid_request_error()
    normalized: list[TemplateModuleInput] = []
    module_keys: set[str] = set()
    task_keys: set[str] = set()
    dependency_references: list[str] = []

    for raw_module in modules:
        if not isinstance(raw_module, dict) or set(raw_module) - {
            "module_key",
            "name",
            "description",
            "sort_order",
            "tasks",
        }:
            raise _invalid_request_error()
        module_key = _stable_key(raw_module.get("module_key"))
        if module_key in module_keys:
            raise TemplateServiceError(
                "duplicate_module_key", "Module keys must be unique in a template.", 400
            )
        module_keys.add(module_key)
        raw_tasks = raw_module.get("tasks")
        if not isinstance(raw_tasks, list):
            raise _invalid_request_error()
        tasks: list[TemplateTaskInput] = []
        for raw_task in raw_tasks:
            if not isinstance(raw_task, dict) or set(raw_task) - {
                "task_key",
                "name",
                "description",
                "duration_days",
                "default_assignee_role",
                "sort_order",
                "dependency_keys",
            }:
                raise _invalid_request_error()
            task_key = _stable_key(raw_task.get("task_key"))
            if task_key in task_keys:
                raise TemplateServiceError(
                    "duplicate_task_key", "Task keys must be unique in a template.", 400
                )
            task_keys.add(task_key)
            duration = raw_task.get("duration_days")
            role = raw_task.get("default_assignee_role")
            sort_order = raw_task.get("sort_order", 0)
            dependencies = raw_task.get("dependency_keys", [])
            if (
                type(duration) is not int
                or duration < 1
                or not isinstance(role, str)
                or role not in VALID_ROLES
                or type(sort_order) is not int
                or not isinstance(dependencies, list)
                or any(not isinstance(key, str) for key in dependencies)
            ):
                raise _invalid_request_error()
            normalized_dependencies = [_stable_key(key) for key in dependencies]
            if len(set(normalized_dependencies)) != len(normalized_dependencies):
                raise _invalid_request_error()
            if task_key in normalized_dependencies:
                raise TemplateServiceError(
                    "cyclic_dependency", "Task dependency cycle detected", 400
                )
            dependency_references.extend(normalized_dependencies)
            tasks.append(
                {
                    "task_key": task_key,
                    "name": _required_text(raw_task.get("name"), maximum=200),
                    "description": _text(raw_task.get("description", "")),
                    "duration_days": duration,
                    "default_assignee_role": role,
                    "sort_order": sort_order,
                    "dependency_keys": normalized_dependencies,
                }
            )
        normalized.append(
            {
                "module_key": module_key,
                "name": _required_text(raw_module.get("name"), maximum=160),
                "description": _text(raw_module.get("description", "")),
                "sort_order": _whole_number(raw_module.get("sort_order", 0)),
                "tasks": tasks,
            }
        )

    missing = set(dependency_references) - task_keys
    if missing:
        raise TemplateServiceError(
            "missing_dependency", "A task dependency does not exist in this version.", 400
        )
    catalogs = _catalogs_by_key(session, list(module_keys))
    if set(catalogs) != module_keys:
        raise TemplateServiceError(
            "module_not_found", "A template module does not exist in the catalog.", 400
        )
    if any(not catalog.is_active for catalog in catalogs.values()):
        raise TemplateServiceError(
            "inactive_module", "Inactive modules cannot be added to a template draft.", 400
        )
    return normalized, catalogs


def _validate_template_version(session: Session, version: IndustryTemplateVersion) -> None:
    loaded = _load_version(session, version.id)
    if loaded is None:
        raise _not_found_error()
    if not loaded.modules:
        raise TemplateServiceError(
            "template_empty", "A published template must contain at least one module.", 400
        )
    task_ids: set[str] = set()
    task_keys: set[str] = set()
    module_keys: set[str] = set()
    tasks_by_id: dict[str, TemplateTask] = {}
    for module in loaded.modules:
        module_key = module.module_catalog.module_key
        if (
            STABLE_KEY_PATTERN.fullmatch(module_key) is None
            or module_key in module_keys
        ):
            raise TemplateServiceError(
                "invalid_module_key",
                "Published template module keys must be valid and unique.",
                400,
            )
        module_keys.add(module_key)
        if not module.module_catalog.is_active:
            raise TemplateServiceError(
                "inactive_module", "Published templates may use only active modules.", 400
            )
        if not module.tasks:
            raise TemplateServiceError(
                "template_empty", "Each published module must contain at least one task.", 400
            )
        for task in module.tasks:
            if STABLE_KEY_PATTERN.fullmatch(task.task_key) is None:
                raise TemplateServiceError(
                    "invalid_task_key",
                    "Published template task keys must be stable identifiers.",
                    400,
                )
            if task.task_key in task_keys:
                raise TemplateServiceError(
                    "duplicate_task_key", "Task keys must be unique in a template.", 400
                )
            task_keys.add(task.task_key)
            task_ids.add(task.id)
            tasks_by_id[task.id] = task
            if task.duration_days < 1:
                raise TemplateServiceError(
                    "invalid_duration", "Task durations must be positive.", 400
                )
            if task.default_assignee_role not in VALID_ROLES:
                raise TemplateServiceError(
                    "invalid_assignee_role", "A task uses an unsupported assignee role.", 400
                )
    dependencies = _dependencies_for_task_ids(session, task_ids)
    dependency_keys: dict[str, list[str]] = {task_id: [] for task_id in task_ids}
    for dependency in dependencies:
        if (
            dependency.predecessor_task_id not in task_ids
            or dependency.successor_task_id not in task_ids
        ):
            raise TemplateServiceError(
                "missing_dependency", "A task dependency is outside this version.", 400
            )
        dependency_keys[dependency.successor_task_id].append(
            tasks_by_id[dependency.predecessor_task_id].task_key
        )
    schedule_tasks = [
        ScheduleTask(
            task.task_key,
            task.duration_days,
            tuple(sorted(dependency_keys[task_id])),
        )
        for task_id, task in (
            (task_id, tasks_by_id[task_id]) for task_id in sorted(task_ids)
        )
    ]
    try:
        validate_acyclic(schedule_tasks)
    except SchedulingError as error:
        raise TemplateServiceError(error.code, error.message, 400) from None
    except ValueError:
        raise TemplateServiceError(
            "duplicate_task_key", "Task keys must be unique in a template.", 400
        ) from None


def _insert_children(
    session: Session,
    version: IndustryTemplateVersion,
    modules: list[TemplateModuleInput],
    catalogs: dict[str, ModuleCatalog],
) -> None:
    tasks_by_key: dict[str, TemplateTask] = {}
    dependency_inputs: list[tuple[str, str]] = []
    for module_input in modules:
        module = TemplateModule(
            template_version_id=version.id,
            module_catalog_id=catalogs[module_input["module_key"]].id,
            name=module_input["name"],
            description=module_input["description"],
            sort_order=module_input["sort_order"],
        )
        session.add(module)
        session.flush()
        for task_input in module_input["tasks"]:
            task = TemplateTask(
                template_module_id=module.id,
                task_key=task_input["task_key"],
                name=task_input["name"],
                description=task_input["description"],
                duration_days=task_input["duration_days"],
                default_assignee_role=task_input["default_assignee_role"],
                sort_order=task_input["sort_order"],
            )
            session.add(task)
            session.flush()
            tasks_by_key[task.task_key] = task
            dependency_inputs.extend(
                (dependency_key, task.task_key)
                for dependency_key in task_input["dependency_keys"]
            )
    for predecessor_key, successor_key in dependency_inputs:
        session.add(
            TemplateTaskDependency(
                predecessor_task_id=tasks_by_key[predecessor_key].id,
                successor_task_id=tasks_by_key[successor_key].id,
            )
        )


def _delete_version_children(session: Session, version_id: str) -> None:
    module_ids = list(
        session.scalars(
            select(TemplateModule.id).where(
                TemplateModule.template_version_id == version_id
            )
        )
    )
    if not module_ids:
        return
    task_ids = list(
        session.scalars(
            select(TemplateTask.id).where(TemplateTask.template_module_id.in_(module_ids))
        )
    )
    if task_ids:
        session.execute(
            delete(TemplateTaskDependency).where(
                or_(
                    TemplateTaskDependency.predecessor_task_id.in_(task_ids),
                    TemplateTaskDependency.successor_task_id.in_(task_ids),
                )
            )
        )
        session.execute(delete(TemplateTask).where(TemplateTask.id.in_(task_ids)))
    session.execute(delete(TemplateModule).where(TemplateModule.id.in_(module_ids)))
    session.flush()


def _load_version(
    session: Session, version_id: str, *, for_update: bool = False
) -> IndustryTemplateVersion | None:
    statement = (
        select(IndustryTemplateVersion)
        .where(IndustryTemplateVersion.id == version_id)
        .options(
            selectinload(IndustryTemplateVersion.template),
            selectinload(IndustryTemplateVersion.modules).selectinload(
                TemplateModule.module_catalog
            ),
            selectinload(IndustryTemplateVersion.modules).selectinload(
                TemplateModule.tasks
            ),
        )
    )
    if for_update:
        statement = statement.with_for_update()
    return session.scalar(statement)


def _serialize_template_version(
    session: Session, version: IndustryTemplateVersion | None
) -> dict[str, Any]:
    if version is None:
        raise _not_found_error()
    snapshot = _snapshot_from_loaded(session, version)
    return {
        **snapshot,
        "status": version.status,
        "version": version.version,
        "published_by_user_id": version.published_by_user_id,
        "published_at": (
            version.published_at.isoformat()
            if version.published_at is not None
            else None
        ),
    }


def _snapshot_from_loaded(
    session: Session, version: IndustryTemplateVersion
) -> dict[str, Any]:
    modules = sorted(version.modules, key=lambda module: (module.sort_order, module.id))
    task_ids = {
        task.id for module in modules for task in module.tasks
    }
    dependencies = _dependencies_for_task_ids(session, task_ids)
    predecessor_keys: dict[str, list[str]] = {task_id: [] for task_id in task_ids}
    task_key_by_id = {
        task.id: task.task_key for module in modules for task in module.tasks
    }
    for dependency in dependencies:
        if (
            dependency.predecessor_task_id in task_ids
            and dependency.successor_task_id in task_ids
        ):
            predecessor_keys[dependency.successor_task_id].append(
                task_key_by_id[dependency.predecessor_task_id]
            )
    return {
        "template_id": version.template.id,
        "template_name": version.name,
        "industry_name": version.industry_name,
        "description": version.description,
        "version_id": version.id,
        "version_number": version.version_number,
        "modules": [
            {
                "id": module.id,
                "module_catalog_id": module.module_catalog_id,
                "module_key": module.module_catalog.module_key,
                "name": module.name,
                "description": module.description,
                "sort_order": module.sort_order,
                "tasks": [
                    {
                        "id": task.id,
                        "task_key": task.task_key,
                        "name": task.name,
                        "description": task.description,
                        "duration_days": task.duration_days,
                        "default_assignee_role": task.default_assignee_role,
                        "sort_order": task.sort_order,
                        "dependency_keys": sorted(predecessor_keys[task.id]),
                    }
                    for task in sorted(
                        module.tasks, key=lambda task: (task.sort_order, task.id)
                    )
                ],
            }
            for module in modules
        ],
    }


def _dependencies_for_task_ids(
    session: Session, task_ids: set[str]
) -> list[TemplateTaskDependency]:
    if not task_ids:
        return []
    return list(
        session.scalars(
            select(TemplateTaskDependency).where(
                or_(
                    TemplateTaskDependency.predecessor_task_id.in_(task_ids),
                    TemplateTaskDependency.successor_task_id.in_(task_ids),
                )
            )
        )
    )


def _modules_from_snapshot(snapshot: dict[str, Any]) -> list[TemplateModuleInput]:
    return [
        {
            "module_key": module["module_key"],
            "name": module["name"],
            "description": module["description"],
            "sort_order": module["sort_order"],
            "tasks": [
                {
                    "task_key": task["task_key"],
                    "name": task["name"],
                    "description": task["description"],
                    "duration_days": task["duration_days"],
                    "default_assignee_role": task["default_assignee_role"],
                    "sort_order": task["sort_order"],
                    "dependency_keys": list(task["dependency_keys"]),
                }
                for task in module["tasks"]
            ],
        }
        for module in snapshot["modules"]
    ]


def _catalogs_by_key(
    session: Session, keys: list[str]
) -> dict[str, ModuleCatalog]:
    if not keys:
        return {}
    return {
        catalog.module_key: catalog
        for catalog in session.scalars(
            select(ModuleCatalog).where(ModuleCatalog.module_key.in_(keys))
        )
    }


def _required_text(value: object, *, maximum: int) -> str:
    if not isinstance(value, str):
        raise _invalid_request_error()
    normalized = value.strip()
    if not normalized or len(normalized) > maximum:
        raise _invalid_request_error()
    return normalized


def _text(value: object) -> str:
    if not isinstance(value, str):
        raise _invalid_request_error()
    return value


def _stable_key(value: object) -> str:
    if (
        not isinstance(value, str)
        or len(value) > 100
        or STABLE_KEY_PATTERN.fullmatch(value) is None
    ):
        raise _invalid_request_error()
    return value


def _whole_number(value: object) -> int:
    if type(value) is not int:
        raise _invalid_request_error()
    return value


def _invalid_request_error() -> TemplateServiceError:
    return TemplateServiceError(
        "invalid_request", "The request body is invalid.", 400
    )


def _not_found_error() -> TemplateServiceError:
    return TemplateServiceError(
        "template_version_not_found", "Template version was not found.", 404
    )


def _immutable_error() -> TemplateServiceError:
    return TemplateServiceError(
        "template_version_immutable",
        "This template version is locked and cannot be changed or deleted.",
        409,
    )


def _require_current_version(
    version: IndustryTemplateVersion, expected_version: int
) -> None:
    if version.version != expected_version:
        raise TemplateServiceError(
            "stale_version",
            "The template version has been updated. Refresh and try again.",
            409,
        )
