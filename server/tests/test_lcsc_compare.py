from unittest.mock import Mock
from uuid import uuid4

from fde_api.auth.models import User
from fde_api.auth.tokens import issue_access_token
from fde_api.control.lcsc_skills import LcscSkillRun


def test_comparison_is_account_scoped_and_does_not_rerun_browser(client, db_session, settings, monkeypatch):
    user = User(username='compare-' + uuid4().hex, display_name='Compare', password_hash='unused', role='viewer', is_active=True, must_change_password=False)
    db_session.add(user); db_session.commit()
    headers = {'Authorization': 'Bearer ' + issue_access_token(user, settings)}
    monkeypatch.setattr('fde_api.control.lcsc_desktop.resolve_model_preference', lambda *args: {'provider':'deepseek','model':'deepseek-flash','base_url':'https://api.deepseek.com','api_key':'test'})
    monkeypatch.setattr('fde_api.control.lcsc_desktop._jev_key', lambda *_: 'test')
    ids = []
    for variant in ('lcsc-browser-baseline', 'lcsc-browser-jev'):
        response = client.post('/api/v1/ai/lcsc-runs/desktop/start', headers=headers,
            json={'skill_key': variant, 'query':'STM32F103C8T6', 'fields':['parameters'], 'track':False})
        assert response.status_code == 200
        ids.append(response.json['data']['id'])
    for identifier, model_name in zip(ids, ('deepseek-flash', 'jev-1.13.0')):
        run = db_session.get(LcscSkillRun, identifier)
        run.steps_json = [
            {'action':'navigate','detail':'打开首页','duration_ms':500,'model':None,'usage':{'input_tokens':0,'output_tokens':0},'cost':{'cny_estimate':'0'}},
            {'action':'judge','detail':'候选商品判断完成','duration_ms':100,'model':model_name,'usage':{'input_tokens':200,'output_tokens':10},'cost':{'cny_estimate':'0.002'}},
            {'action':'goal_check','detail':'核验每项目的及完整性，决定继续或结束','duration_ms':300,'model':'deepseek-flash','usage':{'input_tokens':400,'output_tokens':20},'cost':{'cny_estimate':'0.003'}},
        ]
    db_session.commit()
    monkeypatch.setattr('fde_api.control.model_preferences.resolve_model_preference', lambda *args: {'provider':'deepseek','model':'deepseek-flash','base_url':'https://api.deepseek.com','api_key':'test'})
    reply = Mock()
    reply.json.return_value = {'model':'deepseek-flash','choices':[{'message':{'content':'{"summary":"两条均未完成","comparability":"条件相同","quality":"无法比较结果","efficiency":"不能证明提速","decision":"候选判断不同，核验相同","limitations":"需完成查询","recommendation":"同条件重试"}'}}]}
    post = Mock(return_value=reply)
    monkeypatch.setattr('fde_api.control.lcsc_skills.requests.post', post)
    endpoint = '/api/v1/ai/lcsc-runs/compare'
    result = client.post(endpoint, headers=headers, json={'baseline_id': ids[0], 'jev_id': ids[1]})
    assert result.status_code == 200, result.json
    assert result.json['data']['comparable'] is True
    assert result.json['data']['analysis']['summary'] == '两条均未完成'
    phases = result.json['data']['decision_phases']
    assert phases['baseline'][0]['input_tokens'] == 200
    assert phases['baseline'][0]['cost_cny_estimate'] == '0.002'
    assert phases['jev'][0]['models'] == ['jev-1.13.0']
    assert phases['jev'][1]['models'] == ['deepseek-flash']
    assert sum(group['calls'] for group in phases['baseline']) == 2  # browser excluded
    assert post.call_count == 1
    assert client.post(endpoint, headers=headers, json={'baseline_id': ids[1], 'jev_id': ids[0]}).status_code == 400
    assert client.post(endpoint, headers=headers, json={'baseline_id': ids[0], 'jev_id': str(uuid4())}).status_code == 404
