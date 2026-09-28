import json
from unittest.mock import Mock
from sqlalchemy import select
from test_document_drafts_api import authorized_client_factory, leader_client, _persist_project, _persist_doc_template
from fde_api.documents.models import ProjectDocument
from fde_api.documents.ai_content import generate_document_fields
from fde_api.research.models import ProjectResearchSubject, ProjectAIOpportunityProfile


def test_multi_opportunity_scope_is_frozen_and_does_not_convert_opportunities(app, db_session, leader_client):
    project = _persist_project(db_session, leader_client.user, code='MULTI-SOW')
    _persist_doc_template(db_session, leader_client.user)
    opportunities = [ProjectResearchSubject(project_id=project.id, subject_type='opportunity', subject_key=f'multi_{i}', name=f'机会{i}', description=f'原内容{i}', status='active') for i in range(2)]
    for item in opportunities:
        item.opportunity_profile = ProjectAIOpportunityProfile(opportunity_status='ready')
    db_session.add_all(opportunities); db_session.commit()
    response = leader_client.post(f'/api/v1/projects/{project.id}/documents', json={
        'document_type': 'sow', 'expected_version': project.version,
        'source_opportunity_ids': [item.id for item in opportunities], 'generation_scope': '一期统一交付',
    })
    assert response.status_code == 201, response.json
    result = response.json['data']
    assert len(result['opportunity_scope']['opportunities']) == 2
    assert result['source_opportunity_id'] is None
    for item in opportunities:
        db_session.refresh(item)
        assert item.opportunity_profile.opportunity_status == 'ready'
    opportunities[0].description = '后来修改不应进入旧文档'
    db_session.commit()
    document = db_session.scalar(select(ProjectDocument).where(ProjectDocument.id == result['id']))
    fake = Mock(); fake.complete_json.return_value = {'fields': {'deliverables': '统一交付物'}}
    app.extensions['fde_api_document_generation_deepseek'] = fake
    try:
        assert generate_document_fields(db_session, document)['deliverables'] == '统一交付物'
        payload = json.loads(fake.complete_json.call_args.kwargs['messages'][1]['content'])
        assert payload['instructions'] == '一期统一交付'
        assert payload['opportunities'][0]['opportunity_description'] == '原内容0'
        assert '后来修改' not in str(payload)
    finally:
        app.extensions.pop('fde_api_document_generation_deepseek', None)


def test_rejects_cross_project_opportunity_and_empty_selection(db_session, leader_client):
    project = _persist_project(db_session, leader_client.user, code='MULTI-ONE')
    other = _persist_project(db_session, leader_client.user, code='MULTI-TWO')
    _persist_doc_template(db_session, leader_client.user)
    opportunity = ProjectResearchSubject(project_id=other.id, subject_type='opportunity', subject_key='foreign', name='外部机会', status='active')
    db_session.add(opportunity); db_session.commit()
    for ids in [[], [opportunity.id], [opportunity.id, opportunity.id]]:
        response = leader_client.post(f'/api/v1/projects/{project.id}/documents', json={'document_type': 'sow', 'expected_version': project.version, 'source_opportunity_ids': ids})
        assert response.status_code == 400
    assert not db_session.scalars(select(ProjectDocument).where(ProjectDocument.project_id == project.id)).all()
