import json
import time
from pathlib import Path
from unittest.mock import Mock,patch
import pytest
from agents import crew_reasoning as crew


@pytest.fixture
def environment(tmp_path,monkeypatch):
    monkeypatch.setattr(crew,'ROOT',tmp_path)
    monkeypatch.setattr(crew,'GOALS',tmp_path/'goals')
    monkeypatch.setattr(crew,'deliver_step',lambda *args:None)
    monkeypatch.setattr(crew,'overview',lambda:{'projects':[{'id':'threads','status':'attention'}],'observedAt':123})
    return tmp_path


def choice(kind='tool',tool='',args=None,message='현재 근거를 확인합니다.',peer='',ids=None):
    return {'decision':kind,'tool':tool,'arguments':json.dumps(args or {}),'message':message,
            'colleague':peer,'plan':['원천 자료 확인','직원 협의','실측 기준으로 판단'],'evidence_ids':ids or ['e0']}


def decisions(monkeypatch,items):
    seen=[];items=iter(items)
    def ask(row):
        seen.append((row['actor'],row['goal'],[x['tool'] for x in row['observations']]))
        row['lastRoute']={'provider':'codex','model':'actual-'+row['actor'],'reasoningEffort':'high'}
        return next(items)
    monkeypatch.setattr(crew,'ask',ask)
    return seen


def test_revenue_question_inspects_metrics_and_consults_real_role_before_answer(environment,monkeypatch):
    data=environment/'dashboard/data';data.mkdir(parents=True)
    (data/'revenue.json').write_text(json.dumps({'checkedAt':'today','revenue':None}))
    (data/'traffic.json').write_text(json.dumps({'sessions':12,'revenue':None}))
    seen=decisions(monkeypatch,[choice(tool='evidence',args={'name':'revenue'}),
        choice('consult',peer='trace',message='트래픽과 미수집 수익을 구분해 주세요.'),
        choice(tool='evidence',args={'name':'traffic'}),
        choice('finish',message='수익은 미수집이며 0원으로 판단할 수 없습니다.',ids=['e1','e3']),
        choice('finish',message='먼저 수익 측정을 연결하고 유입이 확인된 글부터 개선해야 합니다.',ids=['e1','e3','e4'])])
    with patch('server.agent_tools.enqueue_staff_request') as enqueue:
        row=crew.reason_request('revenue','지금 뭘 해야 수익을 올릴 수 있겠어?',steps=6)
    assert row['status']=='answered'
    assert [x[0] for x in seen]==['jarvis','jarvis','trace','trace','jarvis']
    assert all(x[1]==row['goal'] for x in seen)
    assert row['observations'][1]['result']['data']['revenue'] is None
    assert row['leadRoute']['model']=='actual-jarvis'
    enqueue.assert_not_called()
    assert (crew.GOALS/'pending'/row['id']).exists()  # Survives a disconnected interactive client.
    assert json.loads((crew.GOALS/'recent-cases.json').read_text())['cases'][0]['adviceIsHypothesis']


def test_tool_failure_is_evidence_for_next_investigation_not_automatic_stop(environment,monkeypatch):
    source=environment/'dashboard/common/fix.py';source.parent.mkdir(parents=True);source.write_text('ready = False\n')
    decisions(monkeypatch,[choice(tool='read_source',args={'path':'../.env'}),
        choice(tool='read_source',args={'path':'dashboard/common/fix.py'}),
        choice('finish',message='원천 코드의 준비 상태 분기를 확인했습니다.',ids=['e2'])])
    row=crew.reason_request('failure','스레드가 왜 멈춰?',steps=3)
    assert row['status']=='answered'
    assert row['observations'][1]['result']['ok'] is False
    assert row['observations'][2]['result']['lines']==['ready = False']


def test_advice_cannot_dispatch_even_if_model_requests_execution(environment,monkeypatch):
    action={'agent':'publi','tool':'run_project_cycle','args':{'project':'threads'}}
    decisions(monkeypatch,[choice(tool='dispatch',args=action)])
    with patch('server.agent_tools.enqueue_staff_request') as enqueue:
        row=crew.reason_request('advice','스레드에서 무엇을 개선할까?',steps=1)
    enqueue.assert_not_called()
    assert 'does not authorize' in row['observations'][-1]['result']['reason']
    assert not row.get('pendingAction')


def test_execution_waits_for_actual_result_and_resumes_original_goal(environment,monkeypatch):
    from server import agent_tools
    requests=environment/'staff';requests.mkdir()
    monkeypatch.setattr(agent_tools,'STAFF_REQUEST_DIR',requests)
    action={'agent':'publi','tool':'run_project_cycle','args':{'project':'threads'}}
    def enqueue(request_id,actions):
        import hashlib
        receipt={'requestId':request_id,'taskId':'staff:actual','status':'queued','results':[]}
        # Durable dispatch intent exists before the queue operation.
        persisted=json.loads(next(crew.GOALS.glob('*.json')).read_text())
        assert persisted['pendingAction']['requestId']==request_id
        (requests/(hashlib.sha256(request_id.encode()).hexdigest()+'.json')).write_text(json.dumps(receipt))
        return receipt
    monkeypatch.setattr(agent_tools,'enqueue_staff_request',enqueue)
    seen=decisions(monkeypatch,[choice(tool='dispatch',args=action),choice('finish',message='실제 직원 반환을 확인했습니다.',ids=['e2'])])
    row=crew.reason_request('execution','스레드 실행해',execute=True,steps=3)
    assert row['status']=='waiting' and len(seen)==1
    crew.advance(row,2);assert len(seen)==1
    path=next(requests.glob('*.json'));receipt=json.loads(path.read_text());receipt.update(status='completed',results=[{'tool':'run_project_cycle','result':{'status':'no_work','publicationVerified':False}}]);path.write_text(json.dumps(receipt))
    row=crew.advance(row,2)
    assert row['status']=='answered' and row['goal']=='스레드 실행해'
    assert row['observations'][-1]['result']['results'][0]['result']['publicationVerified'] is False


def test_wrong_project_dispatch_and_secret_reads_are_denied(environment,monkeypatch):
    decisions(monkeypatch,[choice(tool='dispatch',args={'agent':'publi','tool':'run_project_cycle','args':{'project':'cf_blog'}})])
    with patch('server.agent_tools.enqueue_staff_request') as enqueue:
        row=crew.reason_request('scope','스레드 실행해',execute=True,steps=1)
    enqueue.assert_not_called()
    assert 'scope' in row['observations'][-1]['result']['reason']
    with pytest.raises(ValueError):crew.read_source({'path':'.env'})
    with pytest.raises(ValueError):crew.read_evidence({'name':'../../credentials'})
    assert crew.safe({'access_token':'private','count':None})=={'access_token':'[redacted]','count':None}


def test_unknown_evidence_cannot_be_used_to_finish(environment,monkeypatch):
    decisions(monkeypatch,[choice('finish',message='복구 완료했습니다.',ids=['invented'])])
    row=crew.reason_request('invalid','상황 판단해',steps=1)
    assert row['status']=='ready' and 'answer' not in row
    assert row['observations'][-1]['tool']=='decision_error'


def test_delivery_failure_retains_bounded_retry_marker(environment,monkeypatch):
    decisions(monkeypatch,[choice('finish',message='실제 관측에 근거한 답변입니다.')])
    row=crew.reason_request('delivery','상황 알려줘',steps=1)
    row['nextCheckAt']=0;row['interactiveUntil']=0;crew.save(row)
    marker=crew.GOALS/'pending'/row['id'];marker.touch()
    with patch('urllib.request.urlopen',side_effect=OSError('offline')):
        assert crew.resume_once()
    assert marker.exists()
    saved=json.loads(crew.goal_path(row['id']).read_text())
    assert saved['deliveryAttempts']==1 and saved['nextCheckAt']>time.time()


def test_direct_staff_request_keeps_owner_after_consultation(environment,monkeypatch):
    seen=decisions(monkeypatch,[choice('consult',peer='doctor',message='이 검증 결과를 검토해 주세요.'),
        choice('finish',message='원천 관측을 확인했습니다.'),choice('finish',message='패치가 확인한 원인을 설명합니다.',ids=['e2'])])
    row=crew.reason_request('msg-11-user:patch','패치 원인을 확인해',lead='patch',steps=4)
    assert [x[0] for x in seen]==['patch','doctor','patch']
    assert row['leadActor']=='patch' and row['userTurnId']=='msg-11-user'
    assert row['leadRoute']['model']=='actual-patch'


def test_known_quota_reset_is_waited_without_extra_model_calls(environment,monkeypatch):
    data=environment/'dashboard/data';data.mkdir(parents=True)
    from datetime import datetime,timezone
    future=time.time()+3600
    (data/'kin-automation-state.json').write_text(json.dumps({'nextEligibleAt':datetime.fromtimestamp(future,timezone.utc).isoformat(),'globalRemainingRuns':0}))
    seen=decisions(monkeypatch,[choice(tool='evidence',args={'name':'kin'}),choice('wait',message='다음 실행 가능 시각까지 기다린 뒤 같은 목표를 재개합니다.',ids=['e1'])])
    row=crew.reason_request('wait','지식인 작업 실행해',execute=True,steps=3)
    assert row['status']=='waiting_external' and abs(row['nextCheckAt']-future)<1
    crew.advance(row,2)
    assert len(seen)==2


def test_duplicate_publication_request_is_not_dispatched_again(environment,monkeypatch):
    action={'agent':'publi','tool':'run_project_cycle','args':{'project':'threads'}}
    import hashlib
    identity=hashlib.sha256(b'duplicate').hexdigest()
    request_id='goal:'+identity+':'+hashlib.sha256(json.dumps(action,sort_keys=True).encode()).hexdigest()[:24]
    decisions(monkeypatch,[choice(tool='dispatch',args=action)])
    row={'id':identity,'requestId':'duplicate','goal':'스레드 실행해','permissions':{'execute':True,'repair':False,'projects':['threads']},
         'actor':'jarvis','leadActor':'jarvis','status':'ready','decisions':0,'observations':[],'plan':[],'executed':{request_id:'unknown'}}
    crew.GOALS.mkdir();crew.observe(row,'host','projects',{}, {'available':True})
    with patch('server.agent_tools.enqueue_staff_request') as enqueue:crew.advance(row,1)
    enqueue.assert_not_called()
    assert row['observations'][-1]['tool']=='decision_error'


def test_pending_claim_prevents_two_workers_advancing_the_same_goal(environment,monkeypatch):
    decisions(monkeypatch,[choice('finish',message='원천 관측을 확인했습니다.')])
    identity='a'*64
    with crew.claim(identity) as acquired:
        assert acquired
        with crew.claim(identity) as second:assert not second


def test_model_call_uses_the_active_staff_slot_and_shared_goal(environment,monkeypatch):
    row={'id':'a'*64,'goal':'수익 개선 우선순위','actor':'trace','permissions':{'execute':False,'repair':False,'projects':['threads']},'decisions':1,'observations':[],'plan':['실제 수익 확인']}
    def generate(prompt,**kwargs):
        assert kwargs['agent_slot']=='trace'
        assert kwargs['timeout_seconds']==180
        assert '수익 개선 우선순위' in prompt and '실제 수익 확인' in prompt
        kwargs['observer']('agy','requested','returned',actual_model='gemini-3.8-flash-medium',reasoning_effort='medium')
        return choice('finish',message='측정 누락을 구분했습니다.')
    with patch('common.llm_client.generate_json',side_effect=generate),patch('common.llm_client.memory_session'):
        crew.ask(row)
    assert row['lastRoute']=={'provider':'agy','model':'gemini-3.8-flash-medium','reasoningEffort':'medium'}


def test_autonomous_goal_uses_existing_incident_and_deduplicates(environment,monkeypatch):
    from server import project_monitor
    data=environment/'dashboard/data';data.mkdir(parents=True)
    (data/'project-autonomy.json').write_text(json.dumps({'enabled':True,'projects':['threads']}))
    incidents=environment/'incidents';incidents.mkdir()
    monkeypatch.setattr(project_monitor,'INCIDENTS',incidents)
    (incidents/'one.json').write_text(json.dumps({'taskId':'project-incident:actual','status':'needs_attention','observation':{'id':'threads','status':'attention'}}))
    assert crew.start_autonomous_goal_once()
    row=json.loads(next(crew.GOALS.glob('[a-f0-9]'*64+'.json')).read_text())
    assert row['origin']=='project-monitor' and row['permissions']['projects']==['threads']
    assert row['decisions']==0 and row['status']=='ready'
    (crew.GOALS/'autonomy.json').write_text('{}')
    assert not crew.start_autonomous_goal_once()


def test_goal_endpoint_binds_original_question_and_keeps_actual_staff_brain(environment,monkeypatch):
    import ast,threading
    from typing import Dict,Any
    from fastapi import HTTPException
    source=Path(__file__).resolve().parents[2]/'agents/chat_room.py'
    tree=ast.parse(source.read_text());node=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='receive_goal_result');node.decorator_list=[]
    messages=[{'id':'msg-1-user','who':'user','text':'수익 개선 방법'}]
    append=Mock(side_effect=lambda row:messages.append(row));direct=Mock()
    scope={'Dict':Dict,'Any':Any,'time':time,'_ROOM_LOCK':threading.RLock(),'load_room_data':lambda:{'messages':messages},'append_or_update_room_message':append,'_append_agent_direct_thread':direct,'HTTPException':HTTPException}
    exec(compile(ast.Module(body=[node],type_ignores=[]),'<goal-endpoint>','exec'),scope)
    crew.GOALS.mkdir()
    identity='a'*64
    row={'id':identity,'goal':'수익 개선 방법','userTurnId':'msg-1-user','status':'answered','answer':'원천 수익 측정부터 보완해야 합니다.',
         'leadRoute':{'provider':'agy','model':'gemini-4-argon-high'},'discussion':[{'id':1,'actor':'trace','text':'미수집 수익을 0으로 계산할 수 없습니다.','ts':10,'route':{'provider':'codex','model':'gpt-6.1-sol','reasoningEffort':'high'}}]}
    crew.goal_path(identity).write_text(json.dumps(row))
    scope['receive_goal_result']({'goalId':identity,'decisionIndex':1})
    assert messages[-1]['who']=='trace' and messages[-1]['brain']['badge']=='gpt-6.1-sol · High'
    scope['receive_goal_result']({'goalId':identity,'decisionIndex':1});assert append.call_count==1
    scope['receive_goal_result']({'goalId':identity})
    assert messages[-1]['who']=='jarvis' and messages[-1]['replyToCeo'] is True
    assert messages[-1]['userTurnId']=='msg-1-user'
    messages[0]['text']='다른 질문'
    with pytest.raises(HTTPException) as error:scope['receive_goal_result']({'goalId':identity})
    assert error.value.status_code==409


def test_native_gemini_schema_has_no_empty_enum_and_restores_only_enum_fields():
    from common.agy_cli import transport_schema,restore_empty_choices
    original={'type':'object','properties':{'tool':{'type':'string','enum':['','read']},'text':{'type':'string'},'actions':{'type':'array','items':{'type':'object','properties':{'domain':{'type':'string','enum':['']}}}}}}
    wire,empty=transport_schema(original)
    assert original['properties']['tool']['enum']==['','read']
    assert wire['properties']['tool']['enum']==[empty,'read']
    restored=restore_empty_choices({'tool':empty,'text':empty,'actions':[{'domain':empty}]},original,empty)
    assert restored=={'tool':'','text':empty,'actions':[{'domain':''}]}


def test_learning_failure_does_not_discard_actual_answer(environment,monkeypatch):
    decisions(monkeypatch,[choice('finish',message='현재 관측에 근거한 답변입니다.')])
    monkeypatch.setattr(crew,'remember_case',Mock(side_effect=OSError('busy')))
    row=crew.reason_request('memory-failure','상황 설명해',steps=1)
    assert row['status']=='answered' and row['answer']=='현재 관측에 근거한 답변입니다.'
    assert row['memoryError']=='OSError'


def test_evidence_can_select_exact_metrics_without_exposing_secret_fields(environment):
    data=environment/'dashboard/data';data.mkdir(parents=True)
    (data/'traffic.json').write_text(json.dumps({'sites':{'example.com':{'sessions':None}},'access_token':'private'}))
    result=crew.read_evidence({'name':'traffic','select':['sites','example.com']})
    assert result['data']=={'sessions':None}
    with pytest.raises(ValueError):crew.read_evidence({'name':'traffic','select':['access_token']})
    assert 'private-value' not in crew.safe("api_key = 'private-value'")


def test_transient_tool_failure_remains_an_actual_tool_result(environment,monkeypatch):
    decisions(monkeypatch,[choice(tool='project_status',args={'project':'threads'}),choice('finish',message='원천 조회 오류를 확인했으며 성공으로 보고하지 않았습니다.',ids=['e1'])])
    with patch('server.agent_tools.execute_agent_tool',side_effect=RuntimeError('reader unavailable')):
        row=crew.reason_request('reader-failure','스레드 현황은?',steps=2)
    assert row['status']=='answered'
    assert row['observations'][1]['tool']=='project_status'
    assert row['observations'][1]['result']['errorType']=='RuntimeError'


def test_dispatch_recovery_uses_same_intent_and_has_a_bounded_enqueue_retry(environment,monkeypatch):
    from server import agent_tools
    row={'id':'a'*64,'goal':'스레드 실행해','permissions':{'execute':True,'repair':False,'projects':['threads']},
         'actor':'jarvis','status':'waiting','decisions':1,'observations':[],'pendingAction':{'requestId':'same-claim','action':{'agent':'publi','tool':'run_project_cycle','args':{'project':'threads'}}}}
    crew.GOALS.mkdir()
    monkeypatch.setattr(agent_tools,'STAFF_REQUEST_DIR',environment/'empty-queue')
    with patch.object(agent_tools,'enqueue_staff_request',side_effect=OSError('busy')) as enqueue:
        for _ in range(3):assert crew.refresh_pending(row) is False
    assert enqueue.call_count==3 and row['pendingAction']['requestId']=='same-claim'
    assert row['status']=='blocked' and row['answerSource']=='host'


@pytest.mark.parametrize('question,repair',[('왜 진행이 안 돼?',False),('왜 해결이 안 돼?',False),('정상화 방법을 알려줘',False),('복구해줘',True),('정상화 시켜줘',True),('복구하지 마',False)])
def test_interactive_staff_question_enters_durable_goal_instead_of_legacy_status_report(question,repair):
    import ast,re
    from typing import Optional,List,Dict,Any
    source=Path(__file__).resolve().parents[2]/'agents/chat_room.py'
    node=next(n for n in ast.parse(source.read_text()).body if isinstance(n,ast.FunctionDef) and n.name=='synthesize_agent_reply')
    scope={'Optional':Optional,'List':List,'Dict':Dict,'Any':Any,'re':re,'AGENT_MAP':{'jarvis':{}},'_project_cycle_requested':lambda q:False}
    exec(compile(ast.Module(body=[node],type_ignores=[]),'<interactive-goal>','exec'),scope)
    row={'id':'a'*64,'status':'ready','plan':['실제 수익 자료 확인'],'actor':'trace'}
    with patch.object(crew,'reason_request',return_value=row) as reason:
        answer,artifacts,tools=scope['synthesize_agent_reply']('jarvis',question,[],'',staff_request_id='msg-1-user:jarvis')
    reason.assert_called_once_with('msg-1-user:jarvis',question,execute=False,repair=repair,lead='jarvis')
    assert tools[0]['goalId']==row['id'] and tools[0]['activeActor']=='trace'
    assert '실제 도구 결과' in answer and not artifacts


def test_old_incident_cannot_start_recovery_after_project_evidence_changes(environment,monkeypatch):
    from server import project_monitor
    data=environment/'dashboard/data';data.mkdir(parents=True)
    (data/'project-autonomy.json').write_text(json.dumps({'enabled':True,'projects':['threads']}))
    incidents=environment/'incidents';incidents.mkdir();monkeypatch.setattr(project_monitor,'INCIDENTS',incidents)
    (incidents/'old.json').write_text(json.dumps({'taskId':'project-incident:old','status':'needs_attention','observation':{'id':'threads','status':'attention','failures':['old failure']}}))
    assert not crew.start_autonomous_goal_once()
    assert not list(crew.GOALS.glob('[a-f0-9]'*64+'.json'))


def test_project_cannot_start_a_second_automatic_goal_while_first_is_pending(environment,monkeypatch):
    from server import project_monitor
    data=environment/'dashboard/data';data.mkdir(parents=True)
    (data/'project-autonomy.json').write_text(json.dumps({'enabled':True,'projects':['threads']}))
    incidents=environment/'incidents';incidents.mkdir();monkeypatch.setattr(project_monitor,'INCIDENTS',incidents)
    incident={'taskId':'project-incident:first','status':'needs_attention','observation':{'id':'threads','status':'attention'}}
    (incidents/'first.json').write_text(json.dumps(incident));assert crew.start_autonomous_goal_once()
    incident['taskId']='project-incident:second';(incidents/'second.json').write_text(json.dumps(incident))
    (crew.GOALS/'autonomy.json').write_text('{}')
    assert not crew.start_autonomous_goal_once()
    assert len(list(crew.GOALS.glob('[a-f0-9]'*64+'.json')))==1


@pytest.mark.parametrize('tool,allowed',[('finish',True),('run_command',False),('read_file',False),('',False)])
def test_native_finish_is_output_transport_and_other_native_tools_stay_denied(tool,allowed):
    import subprocess
    from common import agy_cli
    payload=[{'event':'init','init':{'model':'gemini-4-argon-high'}},
        {'event':'step_update','step_update':{'step_type':'tool','tool_name':tool}},
        {'event':'result','result':{'status':'SUCCESS','structured_output':{'reply':'근거를 확인했습니다.'}}}]
    schema={'type':'object','properties':{'reply':{'type':'string'}},'required':['reply']}
    with patch('common.llm_settings.resolve_agy_executable',return_value='/native/agy'), \
         patch.object(agy_cli.subprocess,'run',return_value=subprocess.CompletedProcess([],0,'\n'.join(json.dumps(p) for p in payload),'')), \
         patch('common.llm_client.record_provider_memory_delivery'),patch('common.llm_usage.report_response'):
        if allowed:
            result,model=agy_cli.generate('답변',model='gemini-4-argon-high',response_schema=schema)
            assert result=={'reply':'근거를 확인했습니다.'} and model=='gemini-4-argon-high'
        else:
            with pytest.raises(RuntimeError,match='unexpected_tool_use'):agy_cli.generate('답변',model='gemini-4-argon-high',response_schema=schema)


def test_large_ledgers_do_not_crowd_out_latest_colleague_findings(environment):
    row=crew.reason_request('large-context','수익 우선순위를 판단해',steps=0)
    for index in range(5):crew.observe(row,'trace','evidence',{'name':'traffic'},{'rows':['value'*5000]*4})
    crew.observe(row,'publi','colleague_answer',{}, {'reply':'실측 유입 137세션이며 수익은 미수집입니다.'})
    def generate(prompt,**kwargs):
        context=json.loads(prompt.split('\nRespond in Korean.\n')[1])
        assert len(json.dumps(context,ensure_ascii=False))<40000
        assert context['observations'][-1]['result']['reply']=='실측 유입 137세션이며 수익은 미수집입니다.'
        assert all(event['sha256'] for event in context['observations'])
        assert any(event.get('result',{}).get('truncated') for event in context['observations'])
        kwargs['observer']('agy','requested','returned',actual_model='gemini-4-argon-high')
        return choice('finish')
    with patch('common.llm_client.generate_json',side_effect=generate),patch('common.llm_client.memory_session'):crew.ask(row)
    # Projection never rewrites the durable evidence or its original hash.
    persisted=json.loads(crew.goal_path(row['id']).read_text())
    assert persisted['observations'][1]['result']==row['observations'][1]['result']
