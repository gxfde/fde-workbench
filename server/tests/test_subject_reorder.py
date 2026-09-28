import pytest
from test_ai_server_chat_mcp import ai_context, make_project
from fde_api.research.models import ProjectResearchSubject
from fde_api.research.reorder_service import reorder_subjects
from fde_api.research.subject_service import ResearchSubjectServiceError


def test_reorder_persists_and_rejects_stale_or_partial_groups(ai_context, db_session):
    users, _ = ai_context
    project = make_project(db_session, users['admin'])
    root = ProjectResearchSubject(project_id=project.id, subject_type='project', subject_key='root-sort', name='企业')
    db_session.add(root); db_session.flush()
    rows = [ProjectResearchSubject(project_id=project.id, parent_subject_id=root.id, subject_type='department', subject_key=f'sort-{index}', name=f'部门{index}', sort_order=index * 10) for index in range(3)]
    db_session.add_all(rows); db_session.commit()
    payload = {'items': [{'id': row.id, 'version': row.version} for row in reversed(rows)]}
    result = reorder_subjects(actor=users['admin'], project_id=project.id, payload=payload)
    assert [item['id'] for item in result['items']] == [row.id for row in reversed(rows)]
    for index, row in enumerate(reversed(rows)):
        db_session.refresh(row)
        assert row.sort_order == (index + 1) * 10 and row.parent_subject_id == root.id
    with pytest.raises(ResearchSubjectServiceError) as error:
        reorder_subjects(actor=users['admin'], project_id=project.id, payload=payload)
    assert error.value.code == 'stale_version'
    with pytest.raises(ResearchSubjectServiceError):
        reorder_subjects(actor=users['admin'], project_id=project.id, payload={'items': payload['items'][:1]})
    for index, row in enumerate(reversed(rows)):
        db_session.refresh(row)
        assert row.sort_order == (index + 1) * 10


@pytest.mark.parametrize('payload', [None, {}, {'items': []}, {'items': [{'id': 'x', 'version': True}]}, {'items': [{'id': 'x', 'version': 1}, {'id': 'x', 'version': 1}]}])
def test_reorder_invalid_payload(ai_context, payload):
    with pytest.raises(ResearchSubjectServiceError) as error:
        reorder_subjects(actor=ai_context[0]['admin'], project_id='none', payload=payload)
    assert error.value.status == 400
