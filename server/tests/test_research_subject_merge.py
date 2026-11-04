"""V3 T-O4b：subject 合并原语——表单/答案/链接/子对象/备忘录/画像搬迁与跟踪码纪律。

合并语义（单事务全成全败）：
- 表单键不撞 → 整表搬迁；撞键且源无答案 → 让位删除；撞键且源有答案 → 409 点名。
- 链接重指；自环/重复边让位删除。子对象随迁；既有合并链一跳化。
- 共享/个人备忘录带来源头并入（20 000 同尺截断）。机会画像：目标无→迁入，双有→留任+事件留档。
- 跟踪码不回收：归档行永久占号，新号接既有最大值。
- 有意不进 api_catalog（业务对象不走 change_set 双轨，AI 不可合并）。
"""
from dataclasses import dataclass
from datetime import date
from uuid import uuid4

import pytest
from sqlalchemy import select

from fde_api.auth.models import User
from fde_api.auth.passwords import hash_password
from fde_api.auth.tokens import issue_access_token
from fde_api.research.models import (
    ProjectAIOpportunityProfile,
    ProjectResearchAnswer,
    ProjectResearchForm,
    ProjectResearchFormRevision,
    ProjectResearchPersonalMemo,
    ProjectResearchSubject,
    ProjectResearchSubjectLink,
)
from fde_api.research import subject_service
from fde_api.workbench.models import (
    IndustryTemplate,
    IndustryTemplateVersion,
    OperationEvent,
    Project,
    ProjectMember,
)
from conftest import INITIAL_PASSWORD


@dataclass(frozen=True)
class AuthorizedClient:
    client: object
    user: User
    headers: dict[str, str]

    def get(self, *args, **kwargs):
        return self.client.get(*args, headers=self.headers, **kwargs)

    def post(self, *args, **kwargs):
        return self.client.post(*args, headers=self.headers, **kwargs)


def _client_for(client, db_session, settings, role: str) -> AuthorizedClient:
    user = User(
        username=f"merge.{role}.{uuid4().hex}",
        display_name=role,
        role=role,
        password_hash=hash_password(INITIAL_PASSWORD),
        must_change_password=False,
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()
    return AuthorizedClient(
        client, user, {"Authorization": f"Bearer {issue_access_token(user, settings)}"}
    )


@pytest.fixture
def leader_client(client, db_session, settings):
    return _client_for(client, db_session, settings, "project_lead")


@pytest.fixture
def viewer_client(client, db_session, settings):
    return _client_for(client, db_session, settings, "fde_engineer")


@pytest.fixture
def outsider_client(client, db_session, settings):
    return _client_for(client, db_session, settings, "project_lead")


class MergeStage:
    """ORM-built project with two same-type subjects carrying every merge surface."""

    def __init__(self, db_session, *, subject_type: str = "role", leader_user_id: str):
        template = IndustryTemplate(
            template_key=f"tpl_{uuid4().hex[:8]}", name="Merge template", industry_name="通用制造业"
        )
        version = IndustryTemplateVersion(
            template=template, name="Merge template v1", industry_name="通用制造业",
            version_number=1, status="published",
        )
        project = Project(
            project_code=f"FDE-MERGE-{uuid4().hex[:10]}",
            name="合并原语验证项目",
            enterprise_code="星河制造·制造·苏州",
            leader_user_id=leader_user_id,
            source_template_version=version,
            template_snapshot={},
            research_snapshot={},
            planned_start_date=date(2026, 8, 22),
        )
        db_session.add(version)
        db_session.flush()
        self.root = ProjectResearchSubject(
            project=project, subject_type="project", subject_key="root", name=project.name
        )
        if subject_type == "role":
            parent = ProjectResearchSubject(
                project=project, subject_type="department", subject_key="dept", name="部门"
            )
            db_session.add(parent)
            db_session.flush()
        else:
            parent = None
        parent_id = parent.id if parent is not None else None
        self.source = ProjectResearchSubject(
            project=project, subject_type=subject_type,
            subject_key=f"{subject_type}_a", name="对象甲",
            parent_subject_id=parent_id,
            tracking_code="JOB-0004" if subject_type == "role" else None,
        )
        self.target = ProjectResearchSubject(
            project=project, subject_type=subject_type,
            subject_key=f"{subject_type}_b", name="对象乙",
            parent_subject_id=parent_id,
            tracking_code="JOB-0003" if subject_type == "role" else None,
        )
        self.project = project
        self._session = db_session
        db_session.add_all([self.root, self.source, self.target])
        db_session.flush()

    def add_form(self, subject, form_key: str, *, with_answers: bool) -> ProjectResearchForm:
        form = ProjectResearchForm(
            project=self.project, subject=subject, form_key=form_key, name=form_key
        )
        revision = ProjectResearchFormRevision(
            form=form, revision_number=1, status="draft", definition_snapshot={}
        )
        form.current_revision = revision
        self._session.add(form)
        self._session.flush()
        if with_answers:
            self._session.add(
                ProjectResearchAnswer(
                    revision=revision, field_key="note", value_json={"text": "采集内容"}
                )
            )
        return form


@pytest.fixture
def stage(db_session, leader_client):
    return MergeStage(db_session, leader_user_id=leader_client.user.id)


def _merge_url(stage, subject=None) -> str:
    subject_id = (subject or stage.source).id
    return f"/api/v1/projects/{stage.project.id}/research/subjects/{subject_id}/merge"


def _assert_error(response, status: int, code: str):
    assert response.status_code == status, response.get_data(as_text=True)
    assert response.json["data"] is None
    assert response.json["error"]["code"] == code


def _merge_payload(stage, **overrides):
    payload = {"version": stage.source.version, "target_subject_id": stage.target.id}
    payload.update(overrides)
    return payload


def test_merge_moves_every_surface_and_never_recycles_tracking_codes(
    db_session, stage, leader_client
):
    db_session.add(
        ProjectMember(project=stage.project, user=leader_client.user, role="member")
    )

    child = ProjectResearchSubject(
        project=stage.project, subject_type="role", subject_key="child_of_a",
        name="甲的子岗位", parent_subject_id=stage.source.id, tracking_code="JOB-0007",
    )
    peer = ProjectResearchSubject(
        project=stage.project, subject_type="role", subject_key="peer_of_b",
        name="乙的子岗位", parent_subject_id=stage.target.id, tracking_code="JOB-0002",
    )
    db_session.add_all([child, peer])
    db_session.flush()

    moved_form = stage.add_form(stage.source, "interview", with_answers=True)
    dropped_form = stage.add_form(stage.source, "checklist", with_answers=False)
    moved_form_id, dropped_form_id = moved_form.id, dropped_form.id
    stage.add_form(stage.target, "checklist", with_answers=True)
    stage.add_form(stage.target, "summary", with_answers=True)

    opp = ProjectResearchSubject(
        project=stage.project, subject_type="opportunity", subject_key="opp_1",
        name="机会一", parent_subject_id=stage.source.id,
    )
    db_session.add(opp)
    db_session.flush()
    keep_edge = ProjectResearchSubjectLink(
        project_id=stage.project.id, source_subject_id=opp.id,
        target_subject_id=stage.source.id, link_type="opportunity_role",
    )
    duplicate_edge = ProjectResearchSubjectLink(
        project_id=stage.project.id, source_subject_id=stage.target.id,
        target_subject_id=stage.source.id, link_type="opportunity_role",
    )
    self_edge = ProjectResearchSubjectLink(
        project_id=stage.project.id, source_subject_id=stage.source.id,
        target_subject_id=stage.target.id, link_type="opportunity_role",
    )
    db_session.add_all([keep_edge, duplicate_edge, self_edge])

    stage.source.memo = "源共享备忘"
    stage.target.memo = "目标共享备忘"
    memo_only_on_source = User(
        username=f"memo.src.{uuid4().hex}", display_name="src", role="fde_engineer",
        password_hash=hash_password(INITIAL_PASSWORD), must_change_password=False, is_active=True,
    )
    memo_on_both = User(
        username=f"memo.both.{uuid4().hex}", display_name="both", role="fde_engineer",
        password_hash=hash_password(INITIAL_PASSWORD), must_change_password=False, is_active=True,
    )
    memo_empty = User(
        username=f"memo.empty.{uuid4().hex}", display_name="empty", role="fde_engineer",
        password_hash=hash_password(INITIAL_PASSWORD), must_change_password=False, is_active=True,
    )
    db_session.add_all([memo_only_on_source, memo_on_both, memo_empty])
    db_session.flush()
    db_session.add_all(
        [
            ProjectResearchPersonalMemo(
                project_id=stage.project.id, subject_id=stage.source.id,
                user_id=memo_only_on_source.id, memo="源独有",
            ),
            ProjectResearchPersonalMemo(
                project_id=stage.project.id, subject_id=stage.source.id,
                user_id=memo_on_both.id, memo="源侧备注",
            ),
            ProjectResearchPersonalMemo(
                project_id=stage.project.id, subject_id=stage.target.id,
                user_id=memo_on_both.id, memo="目标侧备注",
            ),
            ProjectResearchPersonalMemo(
                project_id=stage.project.id, subject_id=stage.source.id,
                user_id=memo_empty.id, memo="",
            ),
            ProjectResearchPersonalMemo(
                project_id=stage.project.id, subject_id=stage.target.id,
                user_id=memo_empty.id, memo="目标已有",
            ),
        ]
    )
    db_session.commit()

    response = leader_client.post(_merge_url(stage), json=_merge_payload(stage))
    assert response.status_code == 200, response.get_data(as_text=True)
    payload = response.json["data"]
    summary = payload["merge_summary"]
    assert summary == {
        "forms_moved": 1,
        "forms_dropped": 1,
        "links_repointed": 1,
        "links_dropped": 2,
        "children_reparented": 2,
        "merged_rows_repointed": 0,
        "memo_appended": True,
        "personal_memos_moved": 1,
        "personal_memos_appended": 1,
        "personal_memos_dropped": 1,
        "opportunity_profile": None,
    }
    serialized = payload["subject"]
    assert serialized["id"] == stage.target.id
    assert serialized["merged_into_subject_id"] is None

    db_session.expire_all()
    assert "目标共享备忘" in stage.target.memo and "源共享备忘" in stage.target.memo
    assert "（合并自 对象甲 JOB-0004）" in stage.target.memo
    source_row = db_session.get(ProjectResearchSubject, stage.source.id)
    assert source_row.status == "archived"
    assert source_row.merged_into_subject_id == stage.target.id
    assert source_row.tracking_code == "JOB-0004"

    moved = db_session.get(ProjectResearchForm, moved_form_id)
    assert moved.subject_id == stage.target.id
    revision = db_session.scalar(
        select(ProjectResearchFormRevision).where(ProjectResearchFormRevision.form_id == moved.id)
    )
    answers = db_session.scalars(
        select(ProjectResearchAnswer).where(ProjectResearchAnswer.revision_id == revision.id)
    ).all()
    assert [answer.field_key for answer in answers] == ["note"]
    assert db_session.get(ProjectResearchForm, dropped_form_id) is None

    edges = db_session.scalars(
        select(ProjectResearchSubjectLink).where(
            ProjectResearchSubjectLink.project_id == stage.project.id
        )
    ).all()
    assert {(edge.source_subject_id, edge.target_subject_id) for edge in edges} == {
        (opp.id, stage.target.id)
    }

    child_row = db_session.get(ProjectResearchSubject, child.id)
    assert child_row.parent_subject_id == stage.target.id

    both_memo = db_session.scalar(
        select(ProjectResearchPersonalMemo).where(
            ProjectResearchPersonalMemo.subject_id == stage.target.id,
            ProjectResearchPersonalMemo.user_id == memo_on_both.id,
        )
    )
    assert "目标侧备注" in both_memo.memo and "源侧备注" in both_memo.memo
    source_memo_count = len(
        list(
            db_session.scalars(
                select(ProjectResearchPersonalMemo).where(
                    ProjectResearchPersonalMemo.subject_id == stage.source.id
                )
            )
        )
    )
    assert source_memo_count == 0

    # 跟踪码不回收：归档行永久占号，下一个岗位拿到 JOB-0008（越过 0007 之上的 0004）
    assert (
        subject_service.next_tracking_code(db_session, stage.project.id, "role") == "JOB-0008"
    )

    event = db_session.scalar(
        select(OperationEvent).where(
            OperationEvent.event_type == "project_research_subject_merged",
            OperationEvent.target_id == stage.source.id,
        )
    )
    assert event is not None
    assert event.changes["target_subject_id"] == stage.target.id
    assert event.changes["forms_moved"] == 1
    assert event.changes["source_tracking_code"] == "JOB-0004"

    listing = leader_client.get(
        f"/api/v1/projects/{stage.project.id}/research/subjects"
    )
    items = {item["id"]: item for item in listing.json["data"]["items"]}
    assert items[stage.source.id]["merged_into_subject_id"] == stage.target.id
    assert items[stage.source.id]["status"] == "archived"


def test_merge_blocks_on_answered_form_key_conflict_then_succeeds_after_resolution(
    db_session, stage, leader_client
):
    db_session.add(ProjectMember(project=stage.project, user=leader_client.user, role="member"))
    conflicting = stage.add_form(stage.source, "shared", with_answers=True)
    stage.add_form(stage.target, "shared", with_answers=True)
    db_session.commit()

    response = leader_client.post(_merge_url(stage), json=_merge_payload(stage))
    _assert_error(response, 409, "merge_form_conflict")
    assert "shared" in response.json["error"]["message"]
    db_session.expire_all()
    assert db_session.get(ProjectResearchSubject, stage.source.id).status == "active"

    revision = db_session.scalar(
        select(ProjectResearchFormRevision).where(ProjectResearchFormRevision.form_id == conflicting.id)
    )
    for answer in db_session.scalars(
        select(ProjectResearchAnswer).where(ProjectResearchAnswer.revision_id == revision.id)
    ):
        db_session.delete(answer)
    conflicting.current_revision_id = None
    db_session.flush()
    db_session.delete(revision)
    db_session.flush()
    db_session.delete(conflicting)
    db_session.commit()

    db_session.expire_all()
    source_row = db_session.get(ProjectResearchSubject, stage.source.id)
    response = leader_client.post(
        _merge_url(stage), json={"version": source_row.version, "target_subject_id": stage.target.id}
    )
    assert response.status_code == 200, response.get_data(as_text=True)
    assert response.json["data"]["merge_summary"]["forms_moved"] == 0


def test_merge_rejects_type_mismatch_root_self_and_stale_versions(
    db_session, stage, leader_client
):
    db_session.add(ProjectMember(project=stage.project, user=leader_client.user, role="member"))
    other_type = ProjectResearchSubject(
        project=stage.project, subject_type="department", subject_key="dept_x", name="异类型"
    )
    db_session.add(other_type)
    db_session.commit()

    _assert_error(
        leader_client.post(
            _merge_url(stage),
            json={"version": stage.source.version, "target_subject_id": other_type.id},
        ),
        409,
        "merge_subject_type_mismatch",
    )
    _assert_error(
        leader_client.post(
            _merge_url(stage),
            json={"version": stage.source.version, "target_subject_id": stage.root.id},
        ),
        409,
        "research_subject_root_immutable",
    )
    _assert_error(
        leader_client.post(
            _merge_url(stage),
            json={"version": stage.source.version, "target_subject_id": stage.source.id},
        ),
        400,
        "invalid_request",
    )
    _assert_error(
        leader_client.post(_merge_url(stage), json=_merge_payload(stage, version=99)),
        409,
        "stale_version",
    )

    archived = ProjectResearchSubject(
        project=stage.project, subject_type="role", subject_key="role_archived",
        name="已归档", status="archived",
    )
    db_session.add(archived)
    db_session.commit()
    _assert_error(
        leader_client.post(
            _merge_url(stage, archived),
            json={"version": archived.version, "target_subject_id": stage.target.id},
        ),
        409,
        "merge_source_not_active",
    )
    _assert_error(
        leader_client.post(
            _merge_url(stage),
            json={"version": stage.source.version, "target_subject_id": archived.id},
        ),
        409,
        "merge_target_not_active",
    )
    assert db_session.scalar(
        select(ProjectResearchSubject.status).where(ProjectResearchSubject.id == stage.source.id)
    ) == "active"


def test_merge_flattens_prior_merge_chains(db_session, stage, leader_client):
    db_session.add(ProjectMember(project=stage.project, user=leader_client.user, role="member"))
    earlier_source = ProjectResearchSubject(
        project=stage.project, subject_type="role", subject_key="role_older", name="更早让位者",
        status="archived", merged_into_subject_id=stage.source.id,
    )
    db_session.add(earlier_source)
    db_session.commit()

    response = leader_client.post(_merge_url(stage), json=_merge_payload(stage))
    assert response.status_code == 200, response.get_data(as_text=True)
    assert response.json["data"]["merge_summary"]["merged_rows_repointed"] == 1
    db_session.expire_all()
    assert (
        db_session.get(ProjectResearchSubject, earlier_source.id).merged_into_subject_id
        == stage.target.id
    )


def test_merge_moves_or_drops_opportunity_profiles(db_session, leader_client):
    stage = MergeStage(db_session, subject_type="opportunity", leader_user_id=leader_client.user.id)
    db_session.add(ProjectMember(project=stage.project, user=leader_client.user, role="member"))
    stage.source.opportunity_profile = ProjectAIOpportunityProfile(
        subject_id=stage.source.id, opportunity_status="assessing", priority="high",
        next_action="补齐数据",
    )
    stage.target.opportunity_profile = ProjectAIOpportunityProfile(
        subject_id=stage.target.id, opportunity_status="ready",
    )
    db_session.commit()

    response = leader_client.post(_merge_url(stage), json=_merge_payload(stage))
    assert response.status_code == 200, response.get_data(as_text=True)
    summary = response.json["data"]["merge_summary"]
    assert summary["opportunity_profile"] == "dropped"
    db_session.expire_all()
    assert db_session.get(ProjectAIOpportunityProfile, stage.source.id) is None
    assert db_session.get(ProjectAIOpportunityProfile, stage.target.id).opportunity_status == "ready"
    event = db_session.scalar(
        select(OperationEvent).where(
            OperationEvent.event_type == "project_research_subject_merged",
            OperationEvent.target_id == stage.source.id,
        )
    )
    assert event.changes["dropped_opportunity_profile"]["priority"] == "high"

    # 「迁入」分支需要无画像的目标：另起一对全新机会对象
    third = ProjectResearchSubject(
        project=stage.project, subject_type="opportunity", subject_key="opp_later",
        name="后来者",
    )
    fourth = ProjectResearchSubject(
        project=stage.project, subject_type="opportunity", subject_key="opp_blank",
        name="无画像目标",
    )
    db_session.add_all([third, fourth])
    db_session.flush()
    db_session.add(
        ProjectAIOpportunityProfile(
            subject_id=third.id, opportunity_status="discovered", next_action="初评",
        )
    )
    db_session.commit()
    response = leader_client.post(
        _merge_url(stage, third),
        json={"version": third.version, "target_subject_id": fourth.id},
    )
    assert response.status_code == 200, response.get_data(as_text=True)
    assert response.json["data"]["merge_summary"]["opportunity_profile"] == "moved"
    db_session.expire_all()
    kept = db_session.get(ProjectAIOpportunityProfile, stage.target.id)
    assert kept.opportunity_status == "ready"  # 第一段合并：目标留任，不被迁入者覆盖
    migrated = db_session.get(ProjectAIOpportunityProfile, fourth.id)
    assert migrated is not None and migrated.next_action == "初评"
    assert db_session.get(ProjectAIOpportunityProfile, third.id) is None


def test_merge_is_denied_to_viewers_and_outsiders(db_session, stage, leader_client, viewer_client, outsider_client):
    db_session.add_all(
        [
            ProjectMember(project=stage.project, user=leader_client.user, role="member"),
            ProjectMember(project=stage.project, user=viewer_client.user, role="viewer"),
        ]
    )
    db_session.commit()

    _assert_error(
        viewer_client.post(_merge_url(stage), json=_merge_payload(stage)), 403, "forbidden"
    )
    # 非成员：调研域隐藏项目存在性（404 而非 403）
    _assert_error(
        outsider_client.post(_merge_url(stage), json=_merge_payload(stage)), 404, "project_not_found"
    )
    db_session.expire_all()
    assert db_session.get(ProjectResearchSubject, stage.source.id).status == "active"


def test_merge_route_never_in_catalog() -> None:
    """红线钉子：合并是人工治理动作，AI 不可执行（T-O3 双轨裁决维持）。"""
    from fde_api.control.api_catalog import CATALOG

    paths = {str(entry["path"]) for entry in CATALOG.values()}
    assert not any("/merge" in path and "/research/subjects" in path for path in paths)
