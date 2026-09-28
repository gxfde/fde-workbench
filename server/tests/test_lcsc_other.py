from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from fde_api.control.lcsc_other import assess_other, goals_for, ask_questions
from fde_api.control.service import ControlServiceError
from fde_api.control.builtin_skills import SKILLS, _LCSC_V1, _is_unchanged_builtin


def test_compound_goal_keeps_inventory_question_intact():
    assert goals_for('看一下优惠活动和有没有现货，库存还有多少') == ['看一下优惠活动', '有没有现货', '库存还有多少']


@pytest.mark.parametrize('variant',['lcsc-browser-baseline','lcsc-browser-jev'])
@pytest.mark.parametrize('goal,evidence,mode,reply,expected',[
    ('有没有现货','库存总量 · (单位：个) · 现货：4,955','existence','yes','有。'),
    ('库存还有多少','库存总量 · (单位：个) · 现货：4,955','quantity','value_2','查询结果：现货：4,955（单位：个）。'),
    ('看一下优惠活动','￥1.4566 · ￥4369.8 · 优惠活动','details','value_0','尚未确认'),
    ('有没有现货','库存总量 · 现货：0 · 单位：个','existence','no','没有。'),
])
def test_direct_answers_and_price_heading_false_positive(monkeypatch,variant,goal,evidence,mode,reply,expected):
    def ask(user,mode_key,model,state,questions,label,calls):
        if 'fact_0' in questions:return {'fact_0':{'choice':'0'}}
        if 'reply_0' in questions:return {'reply_0':{'choice':reply},'mode_0':{'choice':mode}, **({'next':{'choice':'stop'}} if 'next' in questions else {})}
        return {k:({'noul':0.99} if q['type']=='noul' else {'choice':'stop' if k=='next' else 'insufficient'}) for k,q in questions.items()}
    monkeypatch.setattr('fde_api.control.lcsc_other.ask_questions',ask)
    monkeypatch.setattr('fde_api.control.lcsc_other.collect_facts',lambda *_:[{'text':evidence,'url':'https://item.szlcsc.com/1.html'}])
    result,_,_=assess_other(user=None,variant=variant,config={'purpose':goal},context={'page':evidence,'url':'https://item.szlcsc.com/1.html'},options=[],sequence=12,calls=[])
    assert result['items'][0]['answer']==expected
    assert result['complete'] is (expected!='尚未确认')


@pytest.mark.parametrize('variant', ['lcsc-browser-jev','lcsc-browser-baseline'])
@pytest.mark.parametrize('full', [False, True])
def test_completion_requires_independent_check_of_every_goal(monkeypatch, variant, full):
    stages=[]
    routes=[]
    def ask(user, mode, model_id, state, questions, label, calls):
        routes.append(mode)
        if "reply_0" in questions:
            assert mode == ('lcsc-browser-baseline' if variant.endswith('jev') else variant)
            return {k:{"choice":"0" if k=='next' else "existence" if k.startswith("mode_") else "yes" if "yes" in q["criteria"] else "unknown"} for k,q in questions.items()}
        assert mode == ('lcsc-browser-baseline' if variant.endswith('jev') and label.startswith('复核') else variant)
        stages.append(label)
        if 'safe' in questions:
            return {'safe': {'noul': 0.99}}
        if 'fact_0' in questions:
            return {key:{'choice':'0'} for key in questions}
        return {key:({'noul':0.99 if full or key=='verify_1' else 0.1} if q['type']=='noul' else {'choice':'0' if key=='next' else 'different_scope'}) for key,q in questions.items()}
    monkeypatch.setattr('fde_api.control.lcsc_other.ask_questions', ask)
    config={'purpose':'看一下优惠活动和有没有现货，库存还有多少', 'selected_product':{'title':'C385040'}}
    result, selection, facts=assess_other(user=SimpleNamespace(id='test'),variant=variant,config=config,context={'page':'嘉立创库存5232\n下单最高享92折','url':'https://item.szlcsc.com/1.html'},options=[{'visible_text':'查看库存说明'}],sequence=1,calls=[])
    assert len(stages)==(2 if full else 3)
    if full and variant.endswith('jev'):
        assert routes == ['lcsc-browser-jev', 'lcsc-browser-baseline', 'lcsc-browser-jev']
    assert result['complete'] is full
    assert result['stop'] is full
    assert (selection['index'] is None) is full
    assert len(result['items'])==3
    if not full:
        assert result['items'][0]['answer']=='尚未确认'
        assert '口径' in result['items'][0]['reason']


def test_budget_stop_explains_unfinished_items(monkeypatch):
    def ask(user,mode,model_id,state,questions,label,calls):
        if "reply_0" in questions:
            return {k:{"choice":"0" if k=='next' else "existence" if k.startswith("mode_") else "yes" if "yes" in q["criteria"] else "unknown"} for k,q in questions.items()}
        return {key:({'noul':0.1} if q['type']=='noul' else {'choice': 'missing' if key.startswith('fact') else '0' if key=='next' else 'not_public'}) for key,q in questions.items()}
    monkeypatch.setattr('fde_api.control.lcsc_other.ask_questions', ask)
    result, _, _=assess_other(user=None,variant='lcsc-browser-jev',config={'purpose':'查库存'},context={'page':'商品标题','url':'https://item.szlcsc.com/1.html'},options=[{'visible_text':'查看详情'}],sequence=12,calls=[])
    assert result['stop'] and not result['complete']
    assert '12 步' in result['reason']
    assert result['items'][0]['status']=='unresolved'


def test_unchanged_page_reuses_goal_checks_and_only_asks_for_next_action(monkeypatch):
    calls_seen=[]
    def ask(user, variant, model_id, state, questions, label, calls):
        calls_seen.append((variant, list(questions), state))
        if 'fact_0' in questions:
            return {'fact_0':{'choice':'missing'}}
        if 'reply_0' in questions:
            return {'reply_0':{'choice':'unknown'}, 'mode_0':{'choice':'details'}}
        if list(questions)==['next']:
            return {'next':{'choice':'0'}}
        return {key:({'noul':0.1} if q['type']=='noul' else {'choice':'0' if key=='next' else 'insufficient'}) for key,q in questions.items()}
    monkeypatch.setattr('fde_api.control.lcsc_other.ask_questions',ask)
    context={'page':'商品详情\n暂无目标信息','url':'https://item.szlcsc.com/1.html','history':[]}
    options=[{'kind':'hover','visible_text':'查看当前商品说明'}]
    first,_,facts=assess_other(user=None,variant='lcsc-browser-jev',config={'purpose':'查询其他说明'},context=context,options=options,sequence=1,calls=[])
    assert [v for v,_,_ in calls_seen]==['lcsc-browser-jev','lcsc-browser-baseline','lcsc-browser-jev']
    assert 'facts' not in calls_seen[1][2] and 'facts' not in calls_seen[2][2]
    calls_seen.clear()
    second,action,_=assess_other(user=None,variant='lcsc-browser-jev',config={'purpose':'查询其他说明','other_assessment':first,'evidence_pool':facts},context=context,options=options,sequence=2,calls=[])
    assert [v for v,_,_ in calls_seen]==['lcsc-browser-jev']
    assert calls_seen[0][1]==['next'] and 'facts' not in calls_seen[0][2]
    assert second['items']==first['items'] and action['index']==0
    calls_seen.clear()
    stopped,_,_=assess_other(user=None,variant='lcsc-browser-jev',config={'purpose':'查询其他说明','other_assessment':second,'evidence_pool':facts},context=context,options=[],sequence=3,calls=[])
    assert stopped['stop'] and not calls_seen


@pytest.mark.parametrize('variant', ['lcsc-browser-jev','lcsc-browser-baseline'])
def test_both_providers_use_real_typed_response_and_preserve_billed_failure(app, monkeypatch, variant):
    monkeypatch.setattr('fde_api.control.lcsc_other._jev_key',lambda _: 'mock-key')
    monkeypatch.setattr('fde_api.control.lcsc_other.resolve_model_preference',lambda *args: {'provider':'deepseek','model':'deepseek-flash','base_url':'https://api.deepseek.com','api_key':'mock-key'})
    monkeypatch.setattr('fde_api.control.lcsc_other._cost',lambda _: {'cny_estimate':'0.001'})
    monkeypatch.setattr('fde_api.control.lcsc_other.estimate_chat_cost',lambda _: {'cny_estimate':'0.001'})
    data={'model':'jev-1.13.0','usage':{'input_tokens':123,'output_tokens':4},'answers':{'verified':{'noul':0.95}}} if variant.endswith('jev') else {'model':'deepseek-flash','usage':{'prompt_tokens':123,'completion_tokens':4,'prompt_cache_hit_tokens':0},'choices':[{'message':{'content':'{"answers":{"verified":{"noul":0.95}}}'}}]}
    response=Mock();response.json.return_value=data
    post=Mock(return_value=response);monkeypatch.setattr('fde_api.control.lcsc_other.requests.post',post)
    calls=[]
    with app.app_context():
        result=ask_questions(SimpleNamespace(id='x'),variant,None,{}, {'verified':{'type':'noul','instructions':'Does evidence answer the goal?'}},'test',calls)
        assert result['verified']['noul']==0.95
        assert calls[0]['usage']['input_tokens']==123
        if variant.endswith('jev'): data['answers']={}
        else: data['choices'][0]['message']['content']='not json'
        with pytest.raises(ControlServiceError):
            ask_questions(SimpleNamespace(id='x'),variant,None,{}, {'verified':{'type':'noul'}},'test',calls)
    assert len(calls)==3 and calls[-1]['status']=='failed'
    assert '重试' in calls[-1]['detail'] or '补问' in calls[-1]['detail']
    assert calls[-1]['usage']['input_tokens']==123 and calls[-1]['cost']['cny_estimate']=='0.001'


def test_missing_goal_answer_is_reasked_without_repeating_valid_answers(app, monkeypatch):
    monkeypatch.setattr('fde_api.control.lcsc_other.resolve_model_preference', lambda *args: {'provider':'deepseek','model':'deepseek-flash','base_url':'https://api.deepseek.com','api_key':'test'})
    monkeypatch.setattr('fde_api.control.lcsc_other.estimate_chat_cost', lambda _: {'cny_estimate':'0.001'})
    seen=[]
    def post(*args, **kwargs):
        question_ids=list(__import__('json').loads(kwargs['json']['messages'][1]['content'])['questions'])
        seen.append(question_ids)
        answers={'first':{'noul':0.9}} if len(seen)==1 else {'second':{'noul':0.8}}
        response=Mock()
        response.json.return_value={'model':'deepseek-flash','usage':{'prompt_tokens':100,'completion_tokens':10},'choices':[{'message':{'content':__import__('json').dumps({'answers':answers})}}]}
        return response
    monkeypatch.setattr('fde_api.control.lcsc_other.requests.post', post)
    questions={'first':{'type':'noul'},'second':{'type':'noul'}}
    calls=[]
    with app.app_context():
        answers=ask_questions(SimpleNamespace(id='x'),'lcsc-browser-baseline',None,{},questions,'核验',calls)
    assert answers == {'first':{'noul':0.9},'second':{'noul':0.8}}
    assert seen == [['first','second'],['second']]
    assert len(calls)==2 and '补问' in calls[1]['detail']


def test_both_skills_upgrade_without_overwriting_custom_text():
    current={s[0]:s for s in SKILLS}
    for key,old in _LCSC_V1.items():
        assert '独立核验' in current[key][-1] and '1.1.0' in current[key][-1]
        skill=SimpleNamespace(name=old[1],description=old[2],status='active')
        version=SimpleNamespace(instructions_text=old[-1],required_capabilities=[],manifest_json={'version':'1.0.0','source':'fde-workbench','read_only':True})
        assert _is_unchanged_builtin(skill,version,old)
        version.instructions_text+='custom'
        assert not _is_unchanged_builtin(skill,version,old)


def test_related_product_stock_is_not_selected_product_evidence():
    from fde_api.control.lcsc_other import collect_facts
    facts = collect_facts({'page':'库存总量\n单位：个\n现货：4955\n替代料\n现货：99999', 'url':'https://item.szlcsc.com/1.html'}, [], '查库存')
    assert any('4955' in f['text'] for f in facts)
    assert not any('99999' in f['text'] for f in facts)


@pytest.mark.parametrize('variant', ['lcsc-browser-jev','lcsc-browser-baseline'])
def test_rejected_action_replans_instead_of_abandoning(monkeypatch, variant):
    def ask(user, mode, model, state, questions, label, calls):
        if "reply_0" in questions:
            return {k:{"choice":"0" if k=='next' else "existence" if k.startswith("mode_") else "yes" if "yes" in q["criteria"] else "unknown"} for k,q in questions.items()}
        if 'fact_0' in questions: return {'fact_0': {'choice':'missing'}}
        if 'safe' in questions: return {'safe': {'noul':0.2 if state['proposed_action']['visible_text']=='uncertain' else 0.99}}
        if list(questions)==['next']:
            assert '0' not in questions['next']['criteria']
            return {'next': {'choice':'1'}}
        return {key:({'noul':0.1} if q['type']=='noul' else {'choice':'0' if key=='next' else 'insufficient'}) for key,q in questions.items()}
    monkeypatch.setattr('fde_api.control.lcsc_other.ask_questions', ask)
    assessment, action, _ = assess_other(user=None,variant=variant,config={'purpose':'查看环保合规声明'},context={'page':'商品资料','url':'https://item.szlcsc.com/1.html'},options=[{'visible_text':'uncertain'},{'visible_text':'Scroll down'}],sequence=2,calls=[])
    assert not assessment['stop'] and not assessment['complete']
    assert action['index']==1 and action['rejected_indices']==[0]


def test_replan_budget_yields_without_executing_rejected_action(monkeypatch):
    def ask(user,mode,model,state,questions,label,calls):
        if "reply_0" in questions:
            return {k:{"choice":"0" if k=='next' else "existence" if k.startswith("mode_") else "yes" if "yes" in q["criteria"] else "unknown"} for k,q in questions.items()}
        if 'fact_0' in questions: return {'fact_0':{'choice':'missing'}}
        if 'safe' in questions: return {'safe':{'noul':0.1}}
        if list(questions)==['next']: return {'next':{'choice':next(k for k in questions['next']['criteria'] if k!='stop')}}
        return {key:({'noul':0.1} if q['type']=='noul' else {'choice':'0' if key=='next' else 'insufficient'}) for key,q in questions.items()}
    monkeypatch.setattr('fde_api.control.lcsc_other.ask_questions', ask)
    assessment, action, _=assess_other(user=None,variant='lcsc-browser-baseline',config={'purpose':'查资料'},context={'page':'资料','url':'https://item.szlcsc.com/1.html'},options=[{'visible_text':str(i)} for i in range(4)],sequence=1,calls=[])
    assert not assessment['stop'] and action['retry'] and action['index'] is None
    assert action['rejected_indices']==[0,1,2]


@pytest.mark.parametrize('kind',['hover','scroll','wait','dismiss'])
def test_non_mutating_primitives_do_not_require_model_safety_score(monkeypatch,kind):
    def ask(user,mode,model,state,questions,label,calls):
        if "reply_0" in questions:
            return {k:{"choice":"0" if k=='next' else "existence" if k.startswith("mode_") else "yes" if "yes" in q["criteria"] else "unknown"} for k,q in questions.items()}
        assert 'safe' not in questions
        if 'fact_0' in questions:return {'fact_0':{'choice':'missing'}}
        return {key:({'noul':0.1} if q['type']=='noul' else {'choice':'0' if key=='next' else 'insufficient'}) for key,q in questions.items()}
    monkeypatch.setattr('fde_api.control.lcsc_other.ask_questions',ask)
    result,selection,_=assess_other(user=None,variant='lcsc-browser-jev',config={'purpose':'查看说明'},context={'page':'商品','url':'https://item.szlcsc.com/1.html'},options=[{'kind':kind,'visible_text':'查看说明'}],sequence=1,calls=[])
    assert not result['stop'] and selection['index']==0
