from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session, selectinload

from fde_api.auth.models import User
from fde_api.extensions import db
from fde_api.ontology import service as ontology_service  # V3 T-O2 类型注册表
from fde_api.projects.events import record_event
from fde_api.projects.permissions import project_access
from fde_api.research.models import (
    ProjectAIOpportunityProfile,
    ProjectResearchAnswer,
    ProjectResearchForm,
    ProjectResearchFormRevision,
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
# V3 T-O2b：CLIENT_SUBJECT_TYPES 不再是创建面的允许域——创建闸门改为
# 「内置 ∪ 注册表 active 行 − project」（_ensure_subject_type_allowed，取
# ontology_service.usable_subject_type_codes）；本常量只剩内置客户端四类的
# 语义标注价值（历史导入/文档引用），不作运行时校验。
CLIENT_SUBJECT_TYPES = frozenset({"department", "role", "process", "opportunity"})
# 备忘录/合并是功能域白名单而非值域（注册类型的对象暂不进个人备忘录功能）。
MEMO_SUBJECT_TYPES = frozenset({"project", "department", "role", "process"})
LINK_SUBJECT_TYPES = {
    "opportunity_role": ("opportunity", "role"),
    "opportunity_process": ("opportunity", "process"),
}
_STABLE_KEY = re.compile(r"^[a-z][a-z0-9_]*$")
# 与 ontology 注册表 code 同格式（_CODE_PATTERN）同宽（60）。
_SUBJECT_TYPE_CODE = re.compile(r"^[a-z][a-z0-9_]{0,59}$")
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


def merge_subject(
    *,
    actor: User,
    project_id: str,
    source_subject_id: str,
    target_subject_id: str,
    expected_source_version: int,
) -> dict[str, Any]:
    """V3 T-O4b：把 source 合并进 target（同项目同类型，单事务全成全败）。

    表单/答案/链接/子对象/个人备忘录/机会画像按下述纪律搬迁；跟踪码不回收
    （归档行永久占号，新号接既有最大值）。业务对象不走 change_set 双轨
    （T-O3 裁决维持），本原语是唯一合并入口、仅人工路由可达。
    """
    try:
        target_id = _required_text(target_subject_id, 36)
    except (TypeError, ValueError):
        raise _invalid_request() from None
    if target_id == source_subject_id:
        raise _invalid_request()
    session = db.session()
    try:
        with session.begin():
            project = _load_project(session, actor, project_id, for_update=True)
            _require_subject_write(actor, project)
            source = _load_subject(session, project.id, source_subject_id, for_update=True)
            target = _load_subject(session, project.id, target_id, for_update=True)
            if source.version != expected_source_version:
                raise _stale_version()
            if source.subject_type == "project" or target.subject_type == "project":
                raise ResearchSubjectServiceError(
                    "research_subject_root_immutable",
                    "The project research subject cannot be merged.",
                    409,
                )
            if source.subject_type != target.subject_type:
                raise ResearchSubjectServiceError(
                    "merge_subject_type_mismatch",
                    "Research subjects of different types cannot be merged.",
                    409,
                )
            if source.status != "active":
                raise ResearchSubjectServiceError(
                    "merge_source_not_active",
                    "Only active research subjects can be merged.",
                    409,
                )
            if target.status != "active":
                raise ResearchSubjectServiceError(
                    "merge_target_not_active",
                    "Research subjects can only be merged into an active subject.",
                    409,
                )
            summary = _relocate_subject_surfaces(session, project.id, source, target)
            source.status = "archived"
            source.merged_into_subject_id = target.id
            source.version += 1
            target.version += 1
            record_event(
                session,
                actor,
                "project_research_subject_merged",
                source,
                {
                    "target_subject_id": target.id,
                    "target_subject_key": target.subject_key,
                    "target_tracking_code": target.tracking_code,
                    "source_tracking_code": source.tracking_code,
                    **summary,
                },
            )
            session.flush()
            # 序列化前让关系视图失效：搬迁（链接重指/画像迁入）可能改写了
            # target 的集合，缓存里的旧值会漏掉刚搬进来的内容。
            session.expire(target, ["outgoing_links", "opportunity_profile"])
            result = {"subject": _serialize_subject(target), "merge_summary": summary}
        return result
    except ResearchSubjectServiceError:
        raise
    except IntegrityError:
        raise ResearchSubjectServiceError(
            "merge_conflict",
            "The merge collided with existing data. Refresh and try again.",
            409,
        ) from None
    except SQLAlchemyError:
        raise _mutation_failed() from None
    finally:
        session.close()


def _relocate_subject_surfaces(
    session: Session, project_id: str, source: ProjectResearchSubject, target: ProjectResearchSubject
) -> dict[str, Any]:
    """Merge every dependent surface of *source* onto *target* inside the caller's transaction."""
    summary: dict[str, Any] = {}

    # ① 表单：键不撞 → 整表搬迁（连修订与答案随外键同行）；撞键且源从未
    #    采集过答案 → 让位删除；撞键且源有答案 → 409 点名（绝不静默丢采集）。
    target_form_keys = set(
        session.scalars(
            select(ProjectResearchForm.form_key).where(
                ProjectResearchForm.project_id == project_id,
                ProjectResearchForm.subject_id == target.id,
            )
        )
    )
    source_forms = list(
        session.scalars(
            select(ProjectResearchForm).where(
                ProjectResearchForm.project_id == project_id,
                ProjectResearchForm.subject_id == source.id,
            )
        )
    )
    answered_form_ids = set(
        session.scalars(
            select(ProjectResearchFormRevision.form_id)
            .join(
                ProjectResearchAnswer,
                ProjectResearchAnswer.revision_id == ProjectResearchFormRevision.id,
            )
            .where(
                ProjectResearchFormRevision.form_id.in_(
                    [form.id for form in source_forms]
                )
            )
            .distinct()
        )
    ) if source_forms else set()
    conflicting_form_keys = sorted(
        form.form_key
        for form in source_forms
        if form.form_key in target_form_keys and form.id in answered_form_ids
    )
    if conflicting_form_keys:
        raise ResearchSubjectServiceError(
            "merge_form_conflict",
            "Both subjects have answered forms with the same form key: "
            f"{', '.join(conflicting_form_keys)}. Resolve them before merging.",
            409,
        )
    forms_moved = forms_dropped = 0
    for form in source_forms:
        if form.form_key not in target_form_keys:
            form.subject_id = target.id
            forms_moved += 1
        elif form.id not in answered_form_ids:
            form.current_revision_id = None
            session.flush()
            for revision in list(form.revisions):
                session.delete(revision)
            session.flush()
            session.delete(form)
            forms_dropped += 1
    summary["forms_moved"] = forms_moved
    summary["forms_dropped"] = forms_dropped

    # ② 链接：边重指到 target；会变自环或与存续边重复的让位删除。
    surviving_edges = {
        (link.source_subject_id, link.target_subject_id, link.link_type)
        for link in session.scalars(
            select(ProjectResearchSubjectLink).where(
                ProjectResearchSubjectLink.project_id == project_id,
                ProjectResearchSubjectLink.source_subject_id != source.id,
                ProjectResearchSubjectLink.target_subject_id != source.id,
            )
        )
    }
    touching_edges = list(
        session.scalars(
            select(ProjectResearchSubjectLink).where(
                ProjectResearchSubjectLink.project_id == project_id,
                (ProjectResearchSubjectLink.source_subject_id == source.id)
                | (ProjectResearchSubjectLink.target_subject_id == source.id),
            )
        )
    )
    links_repointed = links_dropped = 0
    for link in touching_edges:
        new_source = (
            target.id if link.source_subject_id == source.id else link.source_subject_id
        )
        new_target = (
            target.id if link.target_subject_id == source.id else link.target_subject_id
        )
        if (
            new_source == new_target
            or (new_source, new_target, link.link_type) in surviving_edges
        ):
            session.delete(link)
            links_dropped += 1
        else:
            link.source_subject_id = new_source
            link.target_subject_id = new_target
            surviving_edges.add((new_source, new_target, link.link_type))
            links_repointed += 1
    summary["links_repointed"] = links_repointed
    summary["links_dropped"] = links_dropped

    # ③ 子对象随迁（同类型 ⇒ 父类型规则天然成立）；既有合并链一跳化。
    children = list(
        session.scalars(
            select(ProjectResearchSubject).where(
                ProjectResearchSubject.project_id == project_id,
                ProjectResearchSubject.parent_subject_id == source.id,
            )
        )
    )
    for child in children:
        child.parent_subject_id = target.id
        child.version += 1
    summary["children_reparented"] = len(children)
    prior_merged = list(
        session.scalars(
            select(ProjectResearchSubject).where(
                ProjectResearchSubject.project_id == project_id,
                ProjectResearchSubject.merged_into_subject_id == source.id,
            )
        )
    )
    for row in prior_merged:
        row.merged_into_subject_id = target.id
        row.version += 1
    summary["merged_rows_repointed"] = len(prior_merged)

    # ④ 共享备忘录：非空则带来源头并入（与编辑闸同尺 20 000，超长显式截断）。
    memo_appended = False
    if source.memo.strip():
        header = f"（合并自 {source.name}）"
        if source.tracking_code:
            header = f"（合并自 {source.name} {source.tracking_code}）"
        combined = f"{target.memo}\n\n{header}\n{source.memo}".lstrip("\n")
        if len(combined) > 20_000:
            marker = "\n…（合并内容超长截断）"
            combined = combined[: 20_000 - len(marker)] + marker
        target.memo = combined
        memo_appended = True
    summary["memo_appended"] = memo_appended

    # ⑤ 个人备忘录：目标无同人记录 → 重指；双方都有 → 带头并入后删源行；空文本直接让位。
    personal_moved = personal_appended = personal_dropped = 0
    source_memos = list(
        session.scalars(
            select(ProjectResearchPersonalMemo).where(
                ProjectResearchPersonalMemo.project_id == project_id,
                ProjectResearchPersonalMemo.subject_id == source.id,
            )
        )
    )
    if source_memos:
        target_memos = {
            memo_row.user_id: memo_row
            for memo_row in session.scalars(
                select(ProjectResearchPersonalMemo).where(
                    ProjectResearchPersonalMemo.project_id == project_id,
                    ProjectResearchPersonalMemo.subject_id == target.id,
                )
            )
        }
        for memo_row in source_memos:
            peer = target_memos.get(memo_row.user_id)
            if peer is None:
                memo_row.subject_id = target.id
                personal_moved += 1
            elif memo_row.memo.strip():
                header = f"（合并自 {source.name}）"
                if source.tracking_code:
                    header = f"（合并自 {source.name} {source.tracking_code}）"
                combined = f"{peer.memo}\n\n{header}\n{memo_row.memo}".lstrip("\n")
                if len(combined) > 20_000:
                    marker = "\n…（合并内容超长截断）"
                    combined = combined[: 20_000 - len(marker)] + marker
                peer.memo = combined
                peer.version += 1
                session.delete(memo_row)
                personal_appended += 1
            else:
                session.delete(memo_row)
                personal_dropped += 1
    summary["personal_memos_moved"] = personal_moved
    summary["personal_memos_appended"] = personal_appended
    summary["personal_memos_dropped"] = personal_dropped

    # ⑥ 机会画像（仅 opportunity）：目标无 → 整行迁入；双方都有 → 目标留任，
    #    源画像字段随事件留档后删除（机会画像创建即有，留任是唯一可行语义）。
    summary["opportunity_profile"] = None
    source_profile = session.get(ProjectAIOpportunityProfile, source.id)
    if source_profile is not None:
        target_profile = session.get(ProjectAIOpportunityProfile, target.id)
        if target_profile is None:
            session.add(
                ProjectAIOpportunityProfile(
                    subject_id=target.id,
                    target_audience=source_profile.target_audience,
                    owner_user_id=source_profile.owner_user_id,
                    opportunity_status=source_profile.opportunity_status,
                    priority=source_profile.priority,
                    business_value_score=source_profile.business_value_score,
                    feasibility_score=source_profile.feasibility_score,
                    data_readiness_score=source_profile.data_readiness_score,
                    risk_level=source_profile.risk_level,
                    next_action=source_profile.next_action,
                    evidence_json=source_profile.evidence_json,
                    ai_generated=source_profile.ai_generated,
                )
            )
            session.delete(source_profile)
            summary["opportunity_profile"] = "moved"
        else:
            summary["dropped_opportunity_profile"] = {
                "opportunity_status": source_profile.opportunity_status,
                "priority": source_profile.priority,
                "business_value_score": source_profile.business_value_score,
                "feasibility_score": source_profile.feasibility_score,
                "data_readiness_score": source_profile.data_readiness_score,
                "risk_level": source_profile.risk_level,
                "next_action": source_profile.next_action,
            }
            session.delete(source_profile)
            summary["opportunity_profile"] = "dropped"
    return summary


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
            _validate_link(
                session,
                project_id=project.id,
                source=source,
                target=target,
                link_type=normalized_link_type,
            )
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
    # V3 T-O2b 注册表闸门：人工创建与导入 commit 都汇聚到本原语，一处把守
    # 「内置 ∪ 注册表 active − project」。retired/draft 类型在此被拒（禁新建）。
    _ensure_subject_type_allowed(session, project.id, values["subject_type"])
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


def _ensure_subject_type_allowed(
    session: Session, project_id: str, subject_type: str
) -> None:
    """V3 T-O2b 值域闸门：内置 ∪ 注册表 active 行，且 project 根类型永不可建。

    retired（禁新建、存量只读）与 draft（未拍板提案）都拦在闸外；形状不合法
    的码已在 _normalize_create 拦为 invalid_request。
    """
    allowed = ontology_service.usable_subject_type_codes(session, project_id=project_id)
    if subject_type == "project" or subject_type not in allowed:
        raise ResearchSubjectServiceError(
            "unsupported_subject_type",
            "The subject type is not supported in this project.",
            400,
        )


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


def _available_link_types(session: Session, *, project_id: str) -> list[str]:
    """当前项目可用的关系类型（内置两类 ∪ 注册表中生效的类型）——用于错误提示。"""
    names = set(LINK_SUBJECT_TYPES)
    for row in ontology_service.list_relation_types(session, project_id=project_id):
        if row.kind == "link_type" and row.status == "active":
            names.add(row.code)
    return sorted(names)


def _resolve_link_endpoints(
    session: Session, *, project_id: str, link_type: str
) -> tuple[frozenset[str], frozenset[str]]:
    """解析关系类型的端点约束：内置优先（存量方向语义冻结），再查注册表。

    注册表（V3 T-O2 ontology_relation_types）按「项目内遮蔽全局」解析；
    retired 类型禁新边（409，存量边只读），draft 类型尚未启用（409）；
    类型完全未知 → 422（与既有行为一致）。
    """
    builtin = LINK_SUBJECT_TYPES.get(link_type)
    if builtin is not None:
        # 内置优先：注册表不得放开内置两类的方向校验（backlog T-O2 风险条）
        return frozenset({builtin[0]}), frozenset({builtin[1]})
    row = ontology_service.find_relation_type(
        session, project_id=project_id, kind="link_type", code=link_type
    )
    if row is None:
        raise ResearchSubjectServiceError(
            "invalid_research_subject_link",
            "The research subject link type and direction are invalid. "
            "Allowed link types: "
            f"{', '.join(_available_link_types(session, project_id=project_id))}.",
            422,
        )
    if row.status == "retired":
        raise ResearchSubjectServiceError(
            "link_type_retired",
            "The research subject link type is retired; existing links stay readable "
            "but no new link may be created.",
            409,
        )
    if row.status != "active":
        raise ResearchSubjectServiceError(
            "link_type_inactive",
            "The research subject link type is not active yet.",
            409,
        )
    return (
        frozenset(row.allowed_source_types or []),
        frozenset(row.allowed_target_types or []),
    )


def _validate_link(
    session: Session,
    *,
    project_id: str,
    source: ProjectResearchSubject,
    target: ProjectResearchSubject,
    link_type: str,
) -> None:
    allowed_sources, allowed_targets = _resolve_link_endpoints(
        session, project_id=project_id, link_type=link_type
    )
    if (
        source.subject_type not in allowed_sources
        or target.subject_type not in allowed_targets
    ):
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
        # 只做形状校验（码格式/宽度）；允许域（内置 ∪ 注册表 active − project）
        # 由 create_subject_in_transaction 里的注册表闸门把守（T-O2b）。
        if not isinstance(subject_type, str) or _SUBJECT_TYPE_CODE.fullmatch(subject_type) is None:
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
        "merged_into_subject_id": subject.merged_into_subject_id,
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
