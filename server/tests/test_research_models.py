from datetime import date

import pytest
from sqlalchemy import inspect
from sqlalchemy.exc import DBAPIError, IntegrityError

from fde_api.auth.models import Base, User
from fde_api.research.models import (
    ProjectResearchAnswer,
    ProjectResearchImportBatch,
    ProjectResearchForm,
    ProjectResearchFormRevision,
    ProjectResearchSubject,
    ProjectResearchSubjectLink,
    ResearchImmutableError,
    TemplateResearchField,
    TemplateResearchForm,
    TemplateResearchSection,
    assert_revision_mutable,
)
from fde_api.workbench.models import IndustryTemplate, IndustryTemplateVersion, Project


def _persisted_revision(db_session, *, status="confirmed"):
    """Build a persisted revision; changing its status guard must fail tests."""
    leader = User(username="research.lead", password_hash="x", role="project_lead")
    template = IndustryTemplate(name="调研模板", industry_name="制造")
    template_version = IndustryTemplateVersion(
        template=template,
        name=template.name,
        industry_name=template.industry_name,
        description="",
        version_number=1,
        status="published",
        published_by=leader,
    )
    project = Project(
        project_code="FDE-RESEARCH-001",
        name="调研项目",
        enterprise_name="星河制造",
        leader=leader,
        source_template_version=template_version,
        template_snapshot={},
        planned_start_date=date(2026, 8, 22),
    )
    template_form = TemplateResearchForm(
        template_version=template_version,
        form_key="role_interview",
        name="角色访谈",
        subject_type="role",
    )
    section = TemplateResearchSection(
        form=template_form,
        section_key="context",
        name="背景",
    )
    field = TemplateResearchField(
        section=section,
        field_key="main_problem",
        name="主要问题",
        field_type="short_text",
    )
    subject = ProjectResearchSubject(
        project=project,
        subject_type="role",
        subject_key="planner",
        name="计划员",
    )
    form = ProjectResearchForm(
        project=project,
        subject=subject,
        source_template_form=template_form,
        form_key="role_interview",
        name="角色访谈",
    )
    revision = ProjectResearchFormRevision(
        form=form,
        revision_number=1,
        status=status,
    )
    answer = ProjectResearchAnswer(
        revision=revision,
        source_template_field=field,
        field_key="main_problem",
        value_json={"text": "排产信息分散"},
    )
    db_session.add(answer)
    db_session.commit()
    return revision


@pytest.fixture
def confirmed_revision(db_session):
    return _persisted_revision(db_session)


def test_research_models_share_workbench_metadata():
    expected_tables = {
        "template_research_forms",
        "template_research_sections",
        "template_research_fields",
        "project_research_subjects",
        "project_research_subject_links",
        "project_research_forms",
        "project_research_form_revisions",
        "project_research_answers",
        "project_research_import_batches",
    }

    assert expected_tables <= set(Base.metadata.tables)
    assert TemplateResearchForm.metadata is Base.metadata
    assert ProjectResearchImportBatch.metadata is Base.metadata


def test_confirmed_revision_cannot_be_updated(db_session, confirmed_revision):
    """Removing the confirmed-status guard would allow history to be changed."""
    confirmed_revision.answers[0].value_json = {"text": "changed"}

    with pytest.raises(ResearchImmutableError):
        assert_revision_mutable(confirmed_revision)


def test_draft_revision_remains_mutable(db_session):
    """Treating every revision as immutable would block normal draft editing."""
    revision = _persisted_revision(db_session, status="draft")

    assert_revision_mutable(revision)


@pytest.mark.parametrize(
    "field_type",
    [
        "short_text",
        "long_text",
        "rich_text",
        "integer",
        "decimal",
        "date",
        "single_choice",
        "multi_choice",
        "table",
        "file_reference",
    ],
)
def test_database_accepts_each_supported_research_field_type(
    db_session, confirmed_revision, field_type
):
    """A narrower field-type check would reject a documented form control."""
    db_session.add(
        TemplateResearchField(
            section=confirmed_revision.answers[0].source_template_field.section,
            field_key=f"supported_{field_type}",
            name=field_type,
            field_type=field_type,
        )
    )

    db_session.commit()


def test_research_field_default_type_is_supported(db_session, confirmed_revision):
    """Restoring the old text default would create an invalid field definition."""
    field = TemplateResearchField(
        section=confirmed_revision.answers[0].source_template_field.section,
        field_key="default_field_type",
        name="默认字段",
    )
    db_session.add(field)
    db_session.commit()

    assert field.field_type == "short_text"


def test_database_rejects_unknown_research_field_type(db_session, confirmed_revision):
    """Dropping the field-type check would admit values no renderer can handle."""
    db_session.add(
        TemplateResearchField(
            section=confirmed_revision.answers[0].source_template_field.section,
            field_key="unsupported_field_type",
            name="未知字段",
            field_type="text",
        )
    )

    with pytest.raises(DBAPIError):
        db_session.commit()


def test_research_aggregate_versions_default_to_one(confirmed_revision):
    """Removing aggregate version defaults would break optimistic-concurrency clients."""
    assert confirmed_revision.form.version == 1
    assert confirmed_revision.form.subject.version == 1
    assert confirmed_revision.version == 1


@pytest.mark.parametrize(
    "target_name, version",
    [
        ("subject", 0),
        ("form", -1),
        ("revision", 0),
    ],
)
def test_database_rejects_nonpositive_research_aggregate_versions(
    db_session, confirmed_revision, target_name, version
):
    """Dropping a version check would allow stale-write counters below one."""
    target = {
        "subject": confirmed_revision.form.subject,
        "form": confirmed_revision.form,
        "revision": confirmed_revision,
    }[target_name]
    target.version = version

    with pytest.raises(DBAPIError):
        db_session.commit()


def _second_project_form(db_session, confirmed_revision):
    source_form = confirmed_revision.form.source_template_form
    project = Project(
        project_code="FDE-RESEARCH-002",
        name="第二调研项目",
        enterprise_name="银河制造",
        leader=confirmed_revision.form.project.leader,
        source_template_version=confirmed_revision.form.project.source_template_version,
        template_snapshot={},
        planned_start_date=date(2026, 8, 22),
    )
    subject = ProjectResearchSubject(
        project=project,
        subject_type="role",
        subject_key="second_planner",
        name="第二计划员",
    )
    form = ProjectResearchForm(
        project=project,
        subject=subject,
        source_template_form=source_form,
        form_key="role_interview",
        name="角色访谈",
    )
    revision = ProjectResearchFormRevision(
        form=form,
        revision_number=1,
        status="draft",
    )
    db_session.add(revision)
    db_session.commit()
    return subject, form, revision


def test_relationship_subject_link_assigns_its_project_scope(
    db_session, confirmed_revision
):
    """Missing ORM synchronization would leave a valid link with a null project key."""
    source_subject = confirmed_revision.form.subject
    target_subject = ProjectResearchSubject(
        project=confirmed_revision.form.project,
        subject_type="process",
        subject_key="production_planning",
        name="生产计划流程",
    )
    db_session.add(target_subject)
    db_session.commit()

    link = ProjectResearchSubjectLink(
        source_subject=source_subject,
        target_subject=target_subject,
        link_type="supports",
    )
    db_session.add(link)
    db_session.commit()

    assert link.project_id == source_subject.project_id


def test_relationship_subject_link_rejects_cross_project_subjects(
    db_session, confirmed_revision
):
    """Removing ownership validation would link ORM subjects from different projects."""
    second_subject, _, _ = _second_project_form(db_session, confirmed_revision)

    with pytest.raises(ValueError, match="same project"):
        ProjectResearchSubjectLink(
            source_subject=confirmed_revision.form.subject,
            target_subject=second_subject,
            link_type="relates_to",
        )


def test_database_rejects_cross_project_research_subject_link(
    db_session, confirmed_revision
):
    """Missing project-scoped link FKs would connect direct-ID subjects across projects."""
    second_subject, _, _ = _second_project_form(db_session, confirmed_revision)
    link = ProjectResearchSubjectLink(
        source_subject_id=confirmed_revision.form.subject.id,
        target_subject_id=second_subject.id,
        link_type="relates_to",
    )
    link.project_id = confirmed_revision.form.project.id
    db_session.add(link)

    with pytest.raises(DBAPIError):
        db_session.commit()


def test_database_rejects_form_with_subject_from_another_project(
    db_session, confirmed_revision
):
    """Missing composite project/subject ownership would expose another project's subject."""
    second_subject, _, _ = _second_project_form(db_session, confirmed_revision)
    db_session.add(
        ProjectResearchForm(
            project_id=confirmed_revision.form.project.id,
            subject_id=second_subject.id,
            source_template_research_form_id=confirmed_revision.form.source_template_form.id,
            form_key="cross_project_role_interview",
            name="跨项目角色访谈",
        )
    )

    with pytest.raises(DBAPIError):
        db_session.commit()


def test_database_rejects_current_revision_from_another_form(
    db_session, confirmed_revision
):
    """A single-column current-revision FK would let one form point into another's history."""
    _, _, second_revision = _second_project_form(db_session, confirmed_revision)
    confirmed_revision.form.current_revision_id = second_revision.id

    with pytest.raises(DBAPIError):
        db_session.commit()


def test_subject_key_is_unique_within_a_project(db_session, confirmed_revision):
    """Dropping the project/subject key constraint would merge distinct research subjects."""
    project = confirmed_revision.form.project
    db_session.add(
        ProjectResearchSubject(
            project=project,
            subject_type="role",
            subject_key="planner",
            name="重复计划员",
        )
    )

    with pytest.raises(IntegrityError):
        db_session.commit()


def test_answers_are_unique_per_revision_and_field_key(db_session, confirmed_revision):
    """Dropping the revision/field key constraint would create ambiguous answers."""
    answer = confirmed_revision.answers[0]
    db_session.add(
        ProjectResearchAnswer(
            revision=confirmed_revision,
            source_template_field=answer.source_template_field,
            field_key="main_problem",
            value_json={"text": "另一份回答"},
        )
    )

    with pytest.raises(IntegrityError):
        db_session.commit()


def test_database_rejects_unknown_research_subject_type(db_session, confirmed_revision):
    """Removing the subject type check would permit subjects no form can target."""
    db_session.add(
        ProjectResearchSubject(
            project=confirmed_revision.form.project,
            subject_type="team",
            subject_key="unknown-team",
            name="未知对象",
        )
    )

    with pytest.raises(DBAPIError):
        db_session.commit()


def test_research_database_exposes_history_indexes_and_restrict_foreign_keys(db_session):
    database = inspect(db_session.bind)

    assert {index["name"] for index in database.get_indexes("project_research_subjects")} >= {
        "ix_project_research_subjects_project_id",
        "ix_project_research_subjects_subject_type",
    }
    assert {index["name"] for index in database.get_indexes("project_research_forms")} >= {
        "ix_project_research_forms_project_id",
        "ix_project_research_forms_current_revision_id",
    }
    assert {index["name"] for index in database.get_indexes("project_research_form_revisions")} >= {
        "ix_project_research_form_revisions_status"
    }
    form_foreign_keys = database.get_foreign_keys("project_research_forms")
    current_revision_foreign_key = next(
        foreign_key
        for foreign_key in form_foreign_keys
        if foreign_key["constrained_columns"] == ["id", "current_revision_id"]
    )
    assert current_revision_foreign_key["referred_columns"] == ["form_id", "id"]
    assert current_revision_foreign_key["options"].get("ondelete") == "RESTRICT"
    assert ProjectResearchSubjectLink.metadata is Base.metadata
