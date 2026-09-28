from sqlalchemy import select
from fde_api.extensions import db
from fde_api.projects.events import record_event
from fde_api.research.models import ProjectResearchSubject
from fde_api.research.subject_service import (
    ResearchSubjectServiceError, _load_project, _require_subject_write, serialize_subject,
)


def reorder_subjects(*, actor, project_id, payload):
    if not isinstance(payload, dict) or set(payload) != {"items"} or not isinstance(payload["items"], list) or not payload["items"]:
        raise ResearchSubjectServiceError("invalid_request", "排序请求不正确。", 400)
    items = payload["items"]
    if any(not isinstance(item, dict) or set(item) != {"id", "version"} or not isinstance(item["id"], str) or type(item["version"]) is not int or item["version"] < 1 for item in items):
        raise ResearchSubjectServiceError("invalid_request", "排序请求不正确。", 400)
    ids = [item["id"] for item in items]
    if len(set(ids)) != len(ids):
        raise ResearchSubjectServiceError("invalid_request", "排序中不能包含重复对象。", 400)
    session = db.session()
    try:
        with session.begin():
            project = _load_project(session, actor, project_id, for_update=True)
            _require_subject_write(actor, project)
            rows = session.scalars(select(ProjectResearchSubject).where(
                ProjectResearchSubject.project_id == project.id,
                ProjectResearchSubject.status == "active",
                ProjectResearchSubject.subject_type.in_(["department", "role", "process"]),
            ).with_for_update()).all()
            by_id = {row.id: row for row in rows}
            first = by_id.get(ids[0])
            if first is None or any(key not in by_id for key in ids):
                raise ResearchSubjectServiceError("invalid_request", "调研对象不存在或不可排序。", 400)
            siblings = {row.id for row in rows if row.parent_subject_id == first.parent_subject_id}
            if set(ids) != siblings:
                raise ResearchSubjectServiceError("stale_version", "同级调研对象已变化，请刷新后重新排序。", 409)
            if any(by_id[item["id"]].version != item["version"] for item in items):
                raise ResearchSubjectServiceError("stale_version", "调研对象已更新，请刷新后重新排序。", 409)
            for index, key in enumerate(ids):
                subject = by_id[key]
                old = subject.sort_order
                subject.sort_order = (index + 1) * 10
                subject.version += 1
                record_event(session, actor, "project_research_subject_updated", subject, {"sort_order": subject.sort_order, "previous_sort_order": old})
            return {"items": [serialize_subject(by_id[key]) for key in ids]}
    finally:
        session.close()
