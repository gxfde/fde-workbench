from uuid import uuid4
from unittest.mock import Mock
import pytest

from fde_api.auth.models import User
from fde_api.auth.tokens import issue_access_token
from fde_api.control.lcsc_desktop import browser_steps, general_select
from fde_api.control.service import ControlServiceError


@pytest.fixture
def desktop_user(db_session, settings, monkeypatch):
    user = User(username='desktop-' + uuid4().hex, display_name='Test', password_hash='unused', role='viewer', is_active=True, must_change_password=False)
    db_session.add(user); db_session.commit()
    monkeypatch.setattr('fde_api.control.lcsc_desktop.resolve_model_preference', lambda *args: {'provider': 'deepseek', 'model': 'deepseek-flash', 'api_key': 'not-real', 'base_url': 'https://api.deepseek.com'})
    monkeypatch.setattr('fde_api.control.lcsc_desktop._jev_key', lambda *args: 'not-real')
    return user, {'Authorization': 'Bearer ' + issue_access_token(user, settings)}


@pytest.mark.parametrize('variant', ['lcsc-browser-baseline', 'lcsc-browser-jev'])
def test_desktop_run_persists_server_usage_and_private_results(client, desktop_user, monkeypatch, variant):
    _, headers = desktop_user
    root = '/api/v1/ai/lcsc-runs/desktop'
    start = client.post(root + '/start', headers=headers, json={'skill_key': variant, 'query': 'STM32F103C8T6', 'fields': ['pins', 'parameters'], 'track': True})
    assert start.status_code == 200, start.json
    identifier = start.json['data']['id']
    cost = {'cny_estimate': '0.002'}
    model_call = Mock(return_value=({'index': 0}, {'input_tokens': 120, 'output_tokens': 4}, 'deepseek-flash', cost, 30))
    monkeypatch.setattr('fde_api.control.lcsc_desktop.general_select', model_call)
    jev_call = Mock(return_value=({'index': 0, 'confidence': 0.7}, {'input_tokens': 80, 'output_tokens': 6}, 'jev-1.13.0'))
    monkeypatch.setattr('fde_api.control.lcsc_desktop._jev_select', jev_call)
    monkeypatch.setattr('fde_api.control.lcsc_desktop._cost', lambda _: cost)
    step = {'at_ms': 0, 'duration_ms': 5, 'action': 'navigate', 'detail': '打开商城', 'usage': {'input_tokens': 999}}
    data = {'at_ms': 5, 'steps': [step], 'candidates': [{'title': 'STM32F103C8T6', 'url': 'https://item.szlcsc.com/9243.html', 'visible_text': '48 pins'}]}
    selected = client.post(f'{root}/{identifier}/select', headers=headers, json=data)
    assert selected.status_code == 200, selected.json
    assert selected.json['data']['steps'][0]['usage']['input_tokens'] == 0
    again = client.post(f'{root}/{identifier}/select', headers=headers, json=data)
    assert again.json['data']['id'] == identifier
    assert (jev_call if variant.endswith('jev') else model_call).call_count == 1
    assert (model_call if variant.endswith('jev') else jev_call).call_count == 0
    completed = client.post(f'{root}/{identifier}/complete', headers=headers, json={'steps': [step], 'duration_ms': 100, 'result': {'pins': {'count': 48}, 'missing': []}})
    assert completed.json['data']['status'] == 'succeeded'
    assert completed.json['data']['cost']['cny_estimate'] == '0.002'
    assert completed.json['data']['result']['details']['pins']['count'] == 48
    assert completed.json['data']['steps'][1]['model']
    assert client.post(f'{root}/{uuid4()}/complete', headers=headers, json={'steps': [], 'duration_ms': 1}).status_code == 404


def test_missing_fields_and_invalid_timing_are_rejected(client, desktop_user):
    _, headers = desktop_user
    assert client.post('/api/v1/ai/lcsc-runs/desktop/start', headers=headers, json={'skill_key': 'lcsc-browser-baseline', 'query': 'C1', 'fields': [], 'track': True}).status_code == 400
    with pytest.raises(ControlServiceError):
        browser_steps([{'at_ms': -1, 'duration_ms': 10, 'detail': 'bad'}])


def test_desktop_runs_have_no_workbench_hourly_limit(client, desktop_user):
    _, headers = desktop_user
    endpoint = '/api/v1/ai/lcsc-runs/desktop/start'
    for index in range(13):
        response = client.post(endpoint, headers=headers, json={
            'skill_key': 'lcsc-browser-baseline' if index % 2 == 0 else 'lcsc-browser-jev',
            'query': f'C{index}', 'fields': ['parameters'], 'track': False,
        })
        assert response.status_code == 200, response.json


def test_general_model_keeps_reported_usage_if_output_is_invalid(app, desktop_user, monkeypatch):
    user, _ = desktop_user
    response = Mock(); response.json.return_value = {'model': 'deepseek-flash', 'usage': {'prompt_tokens': 100, 'completion_tokens': 3, 'prompt_cache_hit_tokens': 0}, 'choices': [{'message': {'content': '{"index":999}'}}]}
    monkeypatch.setattr('fde_api.control.lcsc_desktop.requests.post', Mock(return_value=response))
    monkeypatch.setattr('fde_api.control.lcsc_desktop.estimate_chat_cost', lambda _: {'cny_estimate': '0.01'})
    with app.app_context(), pytest.raises(ControlServiceError) as caught:
        general_select('C1', [{'title': 'C1', 'visible_text': 'C1'}], user.id, None)
    assert caught.value.usage['input_tokens'] == 100
    assert caught.value.cost['cny_estimate'] == '0.01'


@pytest.mark.parametrize('variant', ['lcsc-browser-baseline', 'lcsc-browser-jev'])
def test_other_real_time_decisions_are_bounded_idempotent_and_accounted(client, desktop_user, monkeypatch, variant):
    _, headers = desktop_user
    root = '/api/v1/ai/lcsc-runs/desktop'
    body = {'skill_key': variant, 'query': 'C8734', 'fields': ['other'], 'track': False}
    assert client.post(root + '/start', headers=headers, json=body).status_code == 400
    body['purpose'] = '查询包装数量'
    started = client.post(root + '/start', headers=headers, json=body).json['data']
    path = root + '/' + started['id']
    default = Mock(return_value=({'index': 0}, {'input_tokens': 100, 'output_tokens': 5}, 'default-model', {'cny_estimate': '0.001'}, 40))
    jev = Mock(return_value=({'index': 0}, {'input_tokens': 100, 'output_tokens': 5}, 'jev-1.13.0'))
    monkeypatch.setattr('fde_api.control.lcsc_desktop.general_select', default)
    monkeypatch.setattr('fde_api.control.lcsc_desktop._jev_select', jev)
    monkeypatch.setattr('fde_api.control.lcsc_desktop._cost', lambda _: {'cny_estimate': '0.001'})
    assert client.post(path + '/select', headers=headers, json={'at_ms': 0, 'steps': [], 'candidates': [{'title': 'C8734', 'url': 'https://item.szlcsc.com/9243.html', 'visible_text': 'C8734'}]}).status_code == 200
    checker = Mock()
    def assess(**kwargs):
        kwargs['calls'].append({'source':'server_model','detail':'核验','action':'goal_check','model':'goal-model','usage':{'input_tokens':100,'output_tokens':5},'cost':{'cny_estimate':'0.001'},'duration_ms':50,'status':'succeeded','at_ms':0})
        return {'purpose':body['purpose'],'complete':False,'stop':False,'reason':'包装数量未展示','items':[]}, {'index':0}, []
    checker.side_effect = assess
    monkeypatch.setattr('fde_api.control.lcsc_desktop.assess_other', checker)
    request = {'sequence': 1, 'at_ms': 100, 'steps': [], 'options': [{'title': '查看包装信息', 'visible_text': 'click packaging'}], 'context': {'page': '公开商品资料', 'url':'https://item.szlcsc.com/9243.html', 'history': []}}
    next_run = client.post(path + '/next', headers=headers, json=request)
    assert next_run.status_code == 200, next_run.json
    assert next_run.json['data']['usage'] == {'input_tokens': 200, 'output_tokens': 10}
    assert next_run.json['data']['cost']['cny_estimate'] == '0.002'
    assert next_run.json['data']['result']['next_action']['index'] == 0
    judge = jev if variant.endswith('jev') else default
    assert checker.call_args.kwargs['context'] == request['context']
    assert client.post(path + '/next', headers=headers, json=request).status_code == 200
    assert judge.call_count == 1  # initial product only; goal verification is separate
    assert checker.call_count == 1
    request['sequence'] = 13
    assert client.post(path + '/next', headers=headers, json=request).status_code == 409
    finish = client.post(path + '/complete', headers=headers, json={'duration_ms': 300, 'steps': [], 'result': {'other': {'purpose': body['purpose'], 'text': '100件/包', 'url': 'https://item.szlcsc.com/9243.html'}, 'missing': []}})
    assert finish.json['data']['status'] == 'partial'
    assert finish.json['data']['result']['details']['other']['complete'] is False
    assert 'text' not in finish.json['data']['result']['details']['other']  # client cannot forge completion
    assert finish.json['data']['usage']['input_tokens'] == 200
    request['sequence'] = 2
    assert client.post(path + '/next', headers=headers, json=request).status_code == 409
