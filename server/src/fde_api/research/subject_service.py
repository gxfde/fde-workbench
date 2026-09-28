from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session, selectinload

from fde_api.auth.models import User
from fde_api.extensions import db
from fde_api.projects.events import record_event
from fde_api.projects.permissions import project_access
from fde_api.research.models import (
    ProjectAIOpportunityProfile,
    ProjectResearchPersonalMemo,
    ProjectResearchSubject,
    ProjectResearchSubjectLink,
)
from fde_api.research.form_service import (
    SubjectFormInitializationContext,
    initialize_subject_forms,
)
from fde_api.workbench.models import Project, ProjectMember


TRACKING_PREFIX = {"role": "JOB", "opportunity": "OPP"}
CLIENT_SUBJECT_TYPES = frozenset({"department", "role", "process", "opportunity"})
MEMO_SUBJECT_TYPES = frozenset({"project", "department", "role", "process"})
LINK_SUBJECT_TYPES = {
    "opportunity_role": ("opportunity", "role"),
    "opportunity_process": ("opportunity", "process"),
}
_STABLE_KEY = re.compile(r"^[a-z][a-z0-9_]*$")
_TRACKING_CODE = re.compile(r"^(?P<prefix>[A-Z]+)-(?P<number>\d+)$")
_PARENT_TYPES = {
    "department": frozenset({"project"}),
    "role": frozenset({"department"}),
    "process": frozenset({"project", "department", "role"}),
    "opportunity": frozenset({"project", "department", "role", "process"}),
}
_AUTO_TRACKING_CODE = object()


class ResearchSubjectServiceError(Exception):
    def __init__(self, code: str, message: str, status: int):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


def create_subject(
    *,
    actor: User,
    project_id: str,
    expected_project_version: int,
    input: Mapping[str, Any],
) -> dict[str, Any]:
    values = _normalize_create(input)
    session = db.session()
    try:
        with session.begin():
            project = load_subject_project(
                session, actor, project_id, for_update=True
            )
            _require_current_project_version(project, expected_project_version)
            subject = create_subject_in_transaction(
                session=session,
                actor=actor,
                project=project,
                input=values,
            )
            project.version += 1
            result = serialize_subject(subject)
            result["project_version"] = project.version
        return result
    except ResearchSubjectServiceError:
        raise
    except IntegrityError:
        raise ResearchSubjectServiceError(
            "research_subject_conflict",
            "A research subject with that key already exists in this project.",
            409,
        ) from None
    except SQLAlchemyError:
        raise _mutation_failed() from None
    finally:
        session.close()


def update_subject(
    *,
    actor: User,
    project_id: str,
    subject_id: str,
    expected_version: int,
    changes: Mapping[str, Any],
) -> dict[str, Any]:
    values = _normalize_update(changes)
    session = db.session()
    try:
        with session.begin():
            project = _load_project(session, actor, project_id, for_update=True)
            _require_subject_write(actor, project)
            subject = _load_subject(session, project.id, subject_id, for_update=True)
            if subject.version != expected_version:
                raise _stale_version()
            if subject.status == "archived":
                raise ResearchSubjectServiceError(
                    "research_subject_archived",
                    "Archived research subjects cannot be updated.",
                    409,
                )
            if "parent_subject_id" in values:
                parent = _parent_for_input(session, project.id, values["parent_subject_id"])
                if parent is not None and parent.id == subject.id:
                    raise _invalid_request()
                _validate_parent_type(subject.subject_type, parent)
                subject.parent_subject_id = parent.id if parent is not None else None
            for key in ("name", "description", "sort_order"):
                if key in values:
                    setattr(subject, key, values[key])
            if "opportunity_profile" in values:
                if subject.subject_type != "opportunity":
                    raise _invalid_request()
                profile = subject.opportunity_profile
                if profile is None:
                    profile = ProjectAIOpportunityProfile(subject_id=subject.id)
                    session.add(profile)
                    subject.opportunity_profile = profile
                profile_values = values["opportunity_profile"]
                owner_id = profile_values.get("owner_user_id", profile.owner_user_id)
                if owner_id is not None:
                    owner = session.get(User, owner_id)
                    project_user_ids = {project.leader_user_id, *(member.user_id for member in project.members)}
                    if owner is None or not owner.is_active or owner_id not in project_user_ids:
                        raise ResearchSubjectServiceError(
                            "invalid_opportunity_owner",
                            "The opportunity owner must be an active member of this project.",
                            400,
                        )
                for key, value in profile_values.items():
                    setattr(profile, key, value)
            subject.version += 1
            record_event(
                session,
                actor,
                "project_research_subject_updated",
                subject,
                _event_changes(values),
            )
            result = _serialize_subject(subject)
        return result
    except ResearchSubjectServiceError:
        raise
    except IntegrityError:
        raise ResearchSubjectServiceError(
            "research_subject_conflict",
            "A research subject with that key already exists in this project.",
            409,
        ) from None
    except SQLAlchemyError:
        raise _mutation_failed() from None
    finally:
        session.close()


def get_subject_memo(*, actor: User, project_id: str, subject_id: str) -> dict[str, Any]:
    session = db.session()
    try:
        project = _load_project(session, actor, project_id)
        subject = _load_subject(session, project.id, subject_id)
        if subject.subject_type not in MEMO_SUBJECT_TYPES or subject.status == "archived":
            raise _invalid_request()
        return {"memo": subject.memo, "version": subject.version}
    finally:
        session.close()


def update_subject_memo(
    *, actor: User, project_id: str, subject_id: str, expected_version: int, memo: Any
) -> dict[str, Any]:
    try:
        normalized_memo = _bounded_memo_text(memo, 20_000)
    except (TypeError, ValueError):
        raise _invalid_request() from None
    session = db.session()
    try:
        with session.begin():
            project = _load_project(session, actor, project_id, for_update=True)
            _require_subject_write(actor, project)
            subject = _load_subject(session, project.id, subject_id, for_update=True)
            if subject.subject_type not in MEMO_SUBJECT_TYPES or subject.status == "archived":
                raise _invalid_request()
            if subject.version != expected_version:
                raise _stale_version()
            subject.memo = normalized_memo
            subject.version += 1
            record_event(
                session,
                actor,
                "project_research_subject_memo_updated",
                subject,
                {"memo_updated": True},
            )
            result = {"memo": subject.memo, "version": subject.version}
        return result
    except ResearchSubjectServiceError:
        raise
    except SQLAlchemyError:
        raise _mutation_failed() from None
    finally:
        session.close()


def list_subject_personal_memos(
    *, actor: User, project_id: str, subject_id: str
) -> dict[str, Any]:
    session = db.session()
    try:
        project = _load_project(session, actor, project_id)
        subject = _load_subject(session, project.id, subject_id)
        if subject.subject_type not in MEMO_SUBJECT_TYPES or subject.status == "archived":
            raise _invalid_request()
        memos = session.scalars(
            select(ProjectResearchPersonalMemo)
            .options(selectinload(ProjectResearchPersonalMemo.author))
            .where(
                ProjectResearchPersonalMemo.project_id == project.id,
                ProjectResearchPersonalMemo.subject_id == subject.id,
            )
        ).all()
        memo_by_user = {item.user_id: item for item in memos}
        people: list[User] = [project.leader]
        people.extend(member.user for member in project.members)
        people.extend(item.author for item in memos)
        people.append(actor)
        seen: set[str] = set()
        items = []
        for person in people:
            if person.id in seen:
                continue
            seen.add(person.id)
            memo = memo_by_user.get(person.id)
            items.append(
                {
                    "user_id": person.id,
                    "display_name": person.display_name,
                    "memo": memo.memo if memo is not None else "",
                    "version": memo.version if memo is not None else 0,
                    "is_current_user": person.id == actor.id,
                }
            )
        return {"items": items}
    finally:
        session.close()


def update_own_subject_personal_memo(
    *, actor: User, project_id: str, subject_id: str, expected_version: int, memo: Any
) -> dict[str, Any]:
    try:
        normalized_memo = _bounded_memo_text(memo, 20_000)
    except (TypeError, ValueError):
        raise _invalid_request() from None
    session = db.session()
    try:
        with session.begin():
            project = _load_project(session, actor, project_id, for_update=True)
            subject = _load_subject(session, project.id, subject_id)
            if subject.subject_type not in MEMO_SUBJECT_TYPES or subject.status == "archived":
                raise _invalid_request()
            personal_memo = session.scalar(
                select(ProjectResearchPersonalMemo)
                .where(
                    ProjectResearchPersonalMemo.project_id == project.id,
                    ProjectResearchPersonalMemo.subject_id == subject.id,
                    ProjectResearchPersonalMemo.user_id == actor.id,
                )
                .with_for_update()
            )
            if personal_memo is None:
                if expected_version != 0:
                    raise _stale_version()
                personal_memo = ProjectResearchPersonalMemo(
                    project_id=project.id,
                    subject_id=subject.id,
                    user_id=actor.id,
                    memo=normalized_memo,
                )
                session.add(personal_memo)
                session.flush()
            else:
                if personal_memo.version != expected_version:
                    raise _stale_version()
                personal_memo.memo = normalized_memo
                personal_memo.version += 1
            record_event(
                session,
                actor,
                "project_research_personal_memo_updated",
                subject,
                {"memo_owner_user_id": actor.id, "memo_updated": True},
            )
            result = {
                "user_id": actor.id,
                "display_name": actor.display_name,
                "memo": personal_memo.memo,
                "version": personal_memo.version,
                "is_current_user": True,
            }
        return result
    except ResearchSubjectServiceError:
        raise
    except IntegrityError:
        raise _stale_version() from None
    except SQLAlchemyError:
        raise _mutation_failed() from None
    finally:
        session.close()


def archive_subject(
    *, actor: User, project_id: str, subject_id: str, expected_version: int
) -> dict[str, Any]:
    session = db.session()
    try:
        with session.begin():
            project = _load_project(session, actor, project_id, for_update=True)
            _require_subject_write(actor, project)
            subject = _load_subject(session, project.id, subject_id, for_update=True)
            if subject.version != expected_version:
                raise _stale_version()
            if subject.subject_type == "project":
                raise ResearchSubjectServiceError(
                    "research_subject_root_immutable",
                    "The project research subject cannot be archived.",
                    409,
                )
            if subject.status == "archived":
                raise ResearchSubjectServiceError(
                    "research_subject_already_archived",
                    "The research subject is already archived.",
                    409,
                )
            active_child_id = session.scalar(
                select(ProjectResearchSubject.id).where(
                    ProjectResearchSubject.project_id == project.id,
                    ProjectResearchSubject.parent_subject_id == subject.id,
                    ProjectResearchSubject.status == "active",
                ).limit(1)
            )
            if active_child_id is not None:
                raise ResearchSubjectServiceError(
                    "research_subject_has_active_children",
                    "Research subjects with active children cannot be archived.",
                    409,
                )
            subject.status = "archived"
            subject.version += 1
            record_event(
                session,
                actor,
                "project_research_subject_archived",
                subject,
                {"tracking_code": subject.tracking_code, "subject_key": subject.subject_key},
            )
            result = _serialize_subject(subject)
        return result
    except ResearchSubjectServiceError:
        raise
    except SQLAlchemyError:
        raise _mutation_failed() from None
    finally:
        session.close()


def link_subjects(
    *,
    actor: User,
    project_id: str,
    source_subject_id: str,
    expected_source_version: int,
    target_subject_id: str,
    link_type: str,
) -> dict[str, Any]:
    try:
        target_id = _required_text(target_subject_id, 36)
        normalized_link_type = _required_text(link_type, 60)
    except (TypeError, ValueError):
        raise _invalid_request() from None
    session = db.session()
    try:
        with session.begin():
            project = _load_project(session, actor, project_id, for_update=True)
            _require_subject_write(actor, project)
            source = _load_subject(session, project.id, source_subject_id, for_update=True)
            target = _load_subject(session, project.id, target_id, for_update=True)
            if source.version != expected_source_version:
                raise _stale_version()
            _validate_link(source, target, normalized_link_type)
            link = ProjectResearchSubjectLink(
                source_subject=source,
                target_subject=target,
                link_type=normalized_link_type,
            )
            session.add(link)
            session.flush()
            source.version += 1
            record_event(
                session,
                actor,
                "project_research_subject_linked",
                source,
                {
                    "target_subject_id": target.id,
                    "link_type": link.link_type,
                },
            )
            result = _serialize_link(link)
            result["source_version"] = source.version
        return result
    except ResearchSubjectServiceError:
        raise
    except IntegrityError:
        raise ResearchSubjectServiceError(
            "research_subject_link_exists",
            "The research subject link already exists.",
            409,
        ) from None
    except SQLAlchemyError:
        raise _mutation_failed() from None
    finally:
        session.close()


def list_subjects(*, actor: User, project_id: str) -> list[dict[str, Any]]:
    session = db.session()
    try:
        project = _load_project(session, actor, project_id)
        subjects = list(
            session.scalars(
                select(ProjectResearchSubject)
                .where(ProjectResearchSubject.project_id == project_id)
                .options(
                    selectinload(ProjectResearchSubject.outgoing_links),
                    selectinload(ProjectResearchSubject.opportunity_profile).selectinload(ProjectAIOpportunityProfile.owner),
                )
                .order_by(
                    ProjectResearchSubject.sort_order,
                    ProjectResearchSubject.created_at,
                    ProjectResearchSubject.id,
                )
            )
        )
        items = [_serialize_subject(subject) for subject in subjects]
        # The project subject is a projection of the project aggregate. Keeping
        # the read model authoritative also repairs the display for records
        # created before project-name synchronization was introduced.
        for item in items:
            if item["subject_type"] == "project":
                item["name"] = project.name
                item["description"] = project.background
        return items
    finally:
        session.close()


def load_subject_project(
    session: Session,
    actor: User,
    project_id: str,
    *,
    for_update: bool = False,
) -> Project:
    """Load a visible project and enforce the shared subject-write capability."""
    project = _load_project(session, actor, project_id, for_update=for_update)
    _require_subject_write(actor, project)
    return project


def create_subject_in_transaction(
    *,
    session: Session,
    actor: User,
    project: Project,
    input: Mapping[str, Any],
    tracking_code: str | None | object = _AUTO_TRACKING_CODE,
    form_context: SubjectFormInitializationContext | None = None,
) -> ProjectResearchSubject:
    """Create one subject inside the caller-owned project transaction."""
    values = _normalize_create(input)
    parent = _parent_for_input(session, project.id, values["parent_subject_id"])
    _validate_parent_type(values["subject_type"], parent)
    subject = ProjectResearchSubject(
        project_id=project.id,
        parent_subject_id=parent.id if parent is not None else None,
        subject_type=values["subject_type"],
        subject_key=values["subject_key"],
        name=values["name"],
        description=values["description"],
        sort_order=values["sort_order"],
        status="active",
        tracking_code=(
            next_tracking_code(session, project.id, values["subject_type"])
            if tracking_code is _AUTO_TRACKING_CODE
            else tracking_code
        ),
    )
    session.add(subject)
    session.flush()
    if subject.subject_type == "opportunity":
        subject.opportunity_profile = ProjectAIOpportunityProfile(subject_id=subject.id)
        session.flush()
    initialize_subject_forms(
        session,
        project,
        subject,
        context=form_context,
        subject_is_new=True,
    )
    record_event(
        session,
        actor,
        "project_research_subject_created",
        subject,
        {
            "subject_type": subject.subject_type,
            "subject_key": subject.subject_key,
            "tracking_code": subject.tracking_code,
        },
    )
    return subject


def next_tracking_code(
    session: Session, project_id: str, subject_type: str
) -> str | None:
    """Allocate a project-scoped tracking code while the project row is locked."""
    prefix = TRACKING_PREFIX.get(subject_type)
    if prefix is None:
        return None
    project = session.scalar(
        select(Project).where(Project.id == project_id).with_for_update()
    )
    if project is None:
        raise ResearchSubjectServiceError("project_not_found", "Project was not found.", 404)
    current_codes = list(
        session.scalars(
            select(ProjectResearchSubject.tracking_code).where(
                ProjectResearchSubject.project_id == project_id,
                ProjectResearchSubject.tracking_code.like(f"{prefix}-%"),
            )
        )
    )
    numbers = [
        int(match.group("number"))
        for code in current_codes
        if code is not None
        for match in [_TRACKING_CODE.fullmatch(code)]
        if match is not None and match.group("prefix") == prefix
    ]
    number = max(numbers, default=0) + 1
    return f"{prefix}-{number:04d}"


def allocate_tracking_codes(
    session: Session, project_id: str, subject_type: str, count: int
) -> list[str | None]:
    """Allocate a batch after the caller has locked the owning project row."""
    prefix = TRACKING_PREFIX.get(subject_type)
    if prefix is None:
        return [None] * count
    current_codes = list(
        session.scalars(
            select(ProjectResearchSubject.tracking_code).where(
                ProjectResearchSubject.project_id == project_id,
                ProjectResearchSubject.tracking_code.like(f"{prefix}-%"),
            )
        )
    )
    numbers = [
        int(match.group("number"))
        for code in current_codes
        if code is not None
        for match in [_TRACKING_CODE.fullmatch(code)]
        if match is not None and match.group("prefix") == prefix
    ]
    start = max(numbers, default=0) + 1
    return [f"{prefix}-{number:04d}" for number in range(start, start + count)]


def _load_project(
    session: Session, actor: User, project_id: str, *, for_update: bool = False
) -> Project:
    if for_update:
        project = _lock_project(session, project_id)
    else:
        project = session.scalar(_project_statement(project_id))
    if project is None or not project_access(actor, project).can_view:
        raise ResearchSubjectServiceError("project_not_found", "Project was not found.", 404)
    return project


def _lock_project(session: Session, project_id: str) -> Project | None:
    """Read one project under the row lock used by subject aggregate writes."""
    return session.scalar(_project_statement(project_id).with_for_update())


def _project_statement(project_id: str):
    return (
        select(Project)
        .where(Project.id == project_id)
        .options(selectinload(Project.members).selectinload(ProjectMember.user))
    )


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
        raise ResearchSubjectServiceError(
            "research_subject_not_found", "Research subject was not found.", 404
        )
    return subject


def _parent_for_input(
    session: Session, project_id: str, parent_subject_id: str | None
) -> ProjectResearchSubject | None:
    if parent_subject_id is None:
        return None
    return _load_subject(session, project_id, parent_subject_id, for_update=True)


def _validate_parent_type(
    subject_type: str, parent: ProjectResearchSubject | None
) -> None:
    if parent is None:
        return
    allowed = _PARENT_TYPES.get(subject_type)
    if allowed is None or parent.subject_type not in allowed:
        raise ResearchSubjectServiceError(
            "invalid_subject_parent",
            "The parent subject type is not valid for this subject.",
            400,
        )


def _validate_link(
    source: ProjectResearchSubject,
    target: ProjectResearchSubject,
    link_type: str,
) -> None:
    allowed_types = LINK_SUBJECT_TYPES.get(link_type)
    if allowed_types != (source.subject_type, target.subject_type):
        raise ResearchSubjectServiceError(
            "invalid_research_subject_link",
            "The research subject link type and direction are invalid.",
            422,
        )


def _require_subject_write(actor: User, project: Project) -> None:
    access = project_access(actor, project)
    if not (access.can_manage or access.can_update_assigned_tasks):
        raise ResearchSubjectServiceError(
            "forbidden", "You do not have permission to modify this project.", 403
        )


def _normalize_create(input: Mapping[str, Any]) -> dict[str, Any]:
    if set(input) - {"subject_type", "subject_key", "name", "description", "sort_order", "parent_subject_id"}:
        raise _invalid_request()
    try:
        subject_type = input["subject_type"]
        subject_key = _subject_key(input["subject_key"])
        if subject_type not in CLIENT_SUBJECT_TYPES:
            raise ValueError("invalid subject type")
        values = {
            "subject_type": subject_type,
            "subject_key": subject_key,
            "name": _required_text(input["name"], 160),
            "description": _optional_text(input.get("description", "")),
            "sort_order": _sort_order(input.get("sort_order", 0)),
            "parent_subject_id": _optional_identifier(input.get("parent_subject_id")),
        }
        return values
    except (KeyError, TypeError, ValueError):
        raise _invalid_request() from None


def _normalize_update(changes: Mapping[str, Any]) -> dict[str, Any]:
    if not changes or set(changes) - {"name", "description", "sort_order", "parent_subject_id", "opportunity_profile"}:
        raise _invalid_request()
    try:
        values: dict[str, Any] = {}
        if "name" in changes:
            values["name"] = _required_text(changes["name"], 160)
        if "description" in changes:
            values["description"] = _optional_text(changes["description"])
        if "sort_order" in changes:
            values["sort_order"] = _sort_order(changes["sort_order"])
        if "parent_subject_id" in changes:
            values["parent_subject_id"] = _optional_identifier(changes["parent_subject_id"])
        if "opportunity_profile" in changes:
            try:
                values["opportunity_profile"] = _normalize_opportunity_profile(changes["opportunity_profile"])
            except (TypeError, ValueError):
                raise ResearchSubjectServiceError(
                    "invalid_opportunity_profile",
                    "The AI opportunity profile contains an invalid field value.",
                    400,
                ) from None
        return values
    except (TypeError, ValueError):
        raise _invalid_request() from None


def _subject_key(value: object) -> str:
    text = _required_text(value, 100)
    if not _STABLE_KEY.fullmatch(text):
        raise ValueError("invalid subject key")
    return text


def _required_text(value: object, maximum: int) -> str:
    if not isinstance(value, str):
        raise TypeError("text is required")
    text = value.strip()
    if not text or len(text) > maximum:
        raise ValueError("invalid text")
    return text


def _optional_text(value: object) -> str:
    if not isinstance(value, str):
        raise TypeError("text is required")
    return value.strip()


def _optional_identifier(value: object) -> str | None:
    if value is None:
        return None
    return _required_text(value, 36)


def _sort_order(value: object) -> int:
    if type(value) is not int:
        raise TypeError("sort order must be an integer")
    return value


def _normalize_opportunity_profile(value: object) -> dict[str, Any]:
    fields = {"target_audience", "owner_user_id", "opportunity_status", "priority", "business_value_score", "feasibility_score", "data_readiness_score", "risk_level", "next_action", "evidence", "ai_generated"}
    if not isinstance(value, Mapping) or not value or set(value) - fields:
        raise ValueError("invalid opportunity profile")
    result: dict[str, Any] = {}
    if "target_audience" in value:
        result["target_audience"] = _bounded_optional_text(value["target_audience"], 300)
    if "next_action" in value:
        result["next_action"] = _bounded_optional_text(value["next_action"], 1000)
    if "owner_user_id" in value:
        result["owner_user_id"] = _optional_identifier(value["owner_user_id"])
    if "opportunity_status" in value:
        result["opportunity_status"] = _choice(value["opportunity_status"], {"discovered", "assessing", "ready", "converted", "paused"})
    if "evidence" in value:
        evidence = value["evidence"]
        if not isinstance(evidence, list) or len(evidence) > 50 or not all(isinstance(item, dict) for item in evidence):
            raise ValueError("invalid evidence")
        result["evidence_json"] = evidence
    if "ai_generated" in value:
        if type(value["ai_generated"]) is not bool:
            raise ValueError("invalid ai_generated")
        result["ai_generated"] = value["ai_generated"]
    for key in ("priority", "risk_level"):
        if key in value:
            result[key] = None if value[key] is None else _choice(value[key], {"high", "medium", "low"})
    for key in ("business_value_score", "feasibility_score", "data_readiness_score"):
        if key in value:
            score = value[key]
            if score is not None and (type(score) is not int or not 1 <= score <= 5):
                raise ValueError("invalid score")
            result[key] = score
    return result


def _bounded_optional_text(value: object, maximum: int) -> str:
    text = _optional_text(value)
    if len(text) > maximum:
        raise ValueError("text too long")
    return text


def _bounded_memo_text(value: object, maximum: int) -> str:
    if not isinstance(value, str):
        raise TypeError("memo must be text")
    if len(value) > maximum:
        raise ValueError("text too long")
    text = value.replace("\r\n", "\n").replace("\r", "\n")
    return text if text.strip() else ""


def _choice(value: object, choices: set[str]) -> str:
    if not isinstance(value, str) or value not in choices:
        raise ValueError("invalid choice")
    return value


def _event_changes(values: Mapping[str, Any]) -> dict[str, Any]:
    result = {key: value for key, value in values.items() if key != "opportunity_profile"}
    if "opportunity_profile" in values:
        result["opportunity_profile"] = {
            key: value for key, value in values["opportunity_profile"].items()
            if key not in {"target_audience", "next_action"}
        }
    return result


def _serialize_subject(subject: ProjectResearchSubject) -> dict[str, Any]:
    return {
        "id": subject.id,
        "project_id": subject.project_id,
        "parent_subject_id": subject.parent_subject_id,
        "subject_type": subject.subject_type,
        "subject_key": subject.subject_key,
        "name": subject.name,
        "description": subject.description,
        "sort_order": subject.sort_order,
        "status": subject.status,
        "tracking_code": subject.tracking_code,
        "version": subject.version,
        "opportunity_profile": _serialize_opportunity_profile(subject.opportunity_profile),
        "links": [
            _serialize_link(link)
            for link in sorted(
                subject.outgoing_links,
                key=lambda item: (item.link_type, item.target_subject_id, item.id),
            )
        ],
    }


def _serialize_opportunity_profile(profile: ProjectAIOpportunityProfile | None) -> dict[str, Any] | None:
    if profile is None:
        return None
    return {
        "target_audience": profile.target_audience,
        "owner_user_id": profile.owner_user_id,
        "owner_display_name": profile.owner.display_name if profile.owner is not None else None,
        "opportunity_status": profile.opportunity_status,
        "priority": profile.priority,
        "business_value_score": profile.business_value_score,
        "feasibility_score": profile.feasibility_score,
        "data_readiness_score": profile.data_readiness_score,
        "risk_level": profile.risk_level,
        "next_action": profile.next_action,
        "evidence": profile.evidence_json,
        "ai_generated": profile.ai_generated,
    }


def serialize_subject(subject: ProjectResearchSubject) -> dict[str, Any]:
    """Serialize a subject for API responses owned by the research domain."""
    return _serialize_subject(subject)


def _serialize_link(link: ProjectResearchSubjectLink) -> dict[str, Any]:
    return {
        "id": link.id,
        "project_id": link.project_id,
        "source_subject_id": link.source_subject_id,
        "target_subject_id": link.target_subject_id,
        "link_type": link.link_type,
    }


def _invalid_request() -> ResearchSubjectServiceError:
    return ResearchSubjectServiceError(
        "invalid_request", "The request body is invalid.", 400
    )


def _stale_version() -> ResearchSubjectServiceError:
    return ResearchSubjectServiceError(
        "stale_version", "The research subject has been updated. Refresh and try again.", 409
    )


def _require_current_project_version(project: Project, expected_version: int) -> None:
    if project.version != expected_version:
        raise ResearchSubjectServiceError(
            "stale_version", "The project has been updated. Refresh and try again.", 409
        )


def _mutation_failed() -> ResearchSubjectServiceError:
    return ResearchSubjectServiceError(
        "research_subject_mutation_failed",
        "Unable to update research subjects at this time.",
        503,
    )
