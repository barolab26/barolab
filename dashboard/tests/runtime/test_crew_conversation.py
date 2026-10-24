"""Production entry/contract regressions: acknowledgement, continuity, ownership and outcomes."""
import ast
import hashlib
import json
import threading
import time
from pathlib import Path
from typing import Any,Dict,Generator
from unittest.mock import Mock,patch
import pytest
from fastapi import FastAPI,HTTPException
from fastapi.responses import StreamingResponse
import asyncio
from types import SimpleNamespace
from agents import crew_reasoning as crew


@pytest.fixture
def environment(tmp_path,monkeypatch):
    monkeypatch.setattr(crew,'ROOT',tmp_path)
    monkeypatch.setattr(crew,'GOALS',tmp_path/'goals')
    monkeypatch.setattr(crew,'overview',lambda:{'projects':[{'id':'naver_kin','status':'attention','counts':{'submitted':0}}]})
    monkeypatch.setattr(crew,'deliver_step',lambda *a:None)
    def progress(row,phase,text):row['progress']={'phase':phase,'summary':text,'at':time.time()};crew.save(row)
    monkeypatch.setattr(crew,'set_progress',progress)
    return tmp_path


def chat_scope():
    source=Path(__file__).resolve().parents[2]/'agents/chat_room.py'
    names={'_stream_sequential_chat_turns','receive_goal_result','get_crew_goal','project_goal_messages'}
    nodes=[n for n in ast.parse(source.read_text()).body if isinstance(n,ast.FunctionDef) and n.name in names]
    for n in nodes:n.decorator_list=[]
    room={'messages':[],'sid':1};direct=Mock()
    def append(message):
        previous=next((i for i,m in enumerate(room['messages']) if m['id']==message['id']),None)
        if previous is None:room['messages'].append(message)
        else:room['messages'][previous]=message
    scope={'Dict':Dict,'Any':Any,'Generator':Generator,'time':time,'json':json,'HTTPException':HTTPException,
        '_ROOM_LOCK':threading.RLock(),'load_room_data':lambda:room,'append_or_update_room_message':append,
        '_append_agent_direct_thread':direct,'parse_mentioned_agents':lambda *a,**k:['jarvis']}
    exec(compile(ast.Module(body=nodes,type_ignores=[]),'<actual-chat-entry>','exec'),scope)
    return scope,room


def request(app,path,method='GET',payload=None):
    async def invoke():
        packets=[];body=json.dumps(payload).encode() if payload is not None else b''
        async def receive():return {'type':'http.request','body':body,'more_body':False}
        async def send(message):packets.append(message)
        route,_,query=path.partition('?')
        await app({'type':'http','asgi':{'version':'3.0','spec_version':'2.4'},'method':method,'path':route,'raw_path':route.encode(),'query_string':query.encode(),'headers':[(b'content-type',b'application/json')],'scheme':'http','server':('test',80),'client':('test',1),'http_version':'1.1'},receive,send)
        text=b''.join(p.get('body',b'') for p in packets).decode()
        return SimpleNamespace(status_code=packets[0]['status'],text=text,json=lambda:json.loads(text))
    return asyncio.run(invoke())


def test_http_ack_precedes_model_and_survives_reload_with_followup_binding(environment,monkeypatch):
    scope,room=chat_scope();app=FastAPI()
    @app.post('/send-stream')
    def send(payload:Dict[str,Any]):return StreamingResponse(scope['_stream_sequential_chat_turns'](payload['text']),media_type='text/event-stream')
    app.get('/goals/{identity}')(scope['get_crew_goal'])
    with patch.object(crew,'ask',side_effect=AssertionError('HTTP acknowledgement must not call a model')):
        started=time.monotonic();response=request(app,'/send-stream','POST',payload={'text':'지식인 왜 안 하고 있어?'})
        assert response.status_code==200 and time.monotonic()-started<1
        events=[json.loads(block.split('data: ',1)[1]) for block in response.text.strip().split('\n\n')]
        assert events[-1]['accepted'] is True
        identity=events[-1]['goalId'];ack=events[1]
        assert '접수했습니다' in ack['text'] and '지식인' in ack['text']
        assert ack['brain']['provider']=='host' and ack['isGoalProgress']
        row=json.loads(crew.goal_path(identity).read_text());assert row['decisions']==0
        # A later request (not an open SSE connection) reconstructs the durable progress.
        snapshot=request(app,'/goals/'+identity+'?view_only=true').json()
        assert snapshot['status']=='ready' and '접수했습니다' in snapshot['view']['text']
        projected=scope['project_goal_messages'](room['messages'])
        assert projected[-1]['goalStatus']=='ready'
        time.sleep(.003)
        second=request(app,'/send-stream','POST',payload={'text':'그거 복구해줘'})
        child=json.loads(crew.goal_path(json.loads(second.text.strip().split('\n\n')[-1].split('data: ',1)[1])['goalId']).read_text())
        assert child['parentGoalId']==identity and child['permissions']=={'execute':False,'repair':True,'projects':['naver_kin']}
        assert child['parentObjective']=='지식인 왜 안 하고 있어?' and child['observations'][0]['sha256']==row['observations'][0]['sha256']


def test_global_question_includes_collection_and_ambiguous_repair_does_not_expand_permissions(environment):
    scope=crew.requested_projects('애드센스 수집과 네이버 블로그를 전체적으로 체크해봐')
    assert {'collections','naver_blog','cf_blog','naver_kin'}<=set(scope)
    first=crew.reason_request('msg-1-user:jarvis','애드센스와 네이버 블로그 전체적으로 체크해봐',steps=0)
    history=[{'id':'msg-1-user','who':'user','text':first['goal']},{'who':'jarvis','goalId':first['id'],'userTurnId':'msg-1-user'}]
    child=crew.reason_request('msg-2-user:jarvis','그거 복구해줘',repair=True,history=history,steps=0)
    assert child['status']=='answered' and child['resolution']['status']=='needs_clarification'
    assert not child.get('pendingAction') and child['permissions']['execute'] is False


def test_search_runs_with_service_path_and_keeps_private_and_frozen_guards(environment,monkeypatch):
    root=environment/'dashboard/common';root.mkdir(parents=True)
    (root/'example.py').write_text('needle = 1\n')
    (root/'token_config.py').write_text('needle = 2\n')
    monkeypatch.setenv('PATH','/usr/bin:/bin')
    result=crew.search_source({'query':'needle'})
    assert 'example.py:1:' in result['matches'] and 'token_config' not in result['matches']
    with pytest.raises(ValueError):crew.read_source({'path':'dashboard/data/revenue.json'})


def test_host_routes_runtime_repair_to_registered_owner_without_weakening_validation(environment):
    row=crew.reason_request('owner','지식인 복구해',repair=True,steps=0)
    action={'agent':'publi','tool':'recover_project_runtime','args':{'project':'naver_kin'}}
    with patch('server.agent_tools.enqueue_staff_request',return_value={'taskId':'task','status':'queued'}) as enqueue:
        result=crew.tool_call(row,'dispatch',action)
    assert enqueue.call_args.args[1][0]['agent']=='patch' and result['publicationVerified'] is False
    assert any(e['tool']=='owner_routing' for e in row['observations'])
    from server.agent_tools import validate_staff_actions
    with pytest.raises(ValueError):validate_staff_actions([action])


def test_failed_receipt_answer_is_not_business_completion_and_hash_changes_do_not_prove_it(environment):
    row=crew.reason_request('failure','지식인 복구해',repair=True,steps=0)
    crew.observe(row,'host','execution_result',{}, {'status':'failed','results':[{'result':{'project':'naver_kin','status':'failed','reason':'duplicate_submission_prevented'}}]})
    row.update(status='answered',answer='차단 원인을 확인했습니다.',resolution=crew.verify_resolution(row))
    assert row['resolution']['status']=='failed'
    assert crew.progress_view(row)['status']=='failed'
    crew.observe(row,'host','project_status',{'project':'naver_kin'},{'data':{'observation':{'id':'naver_kin','status':'attention','source':{'sha256':'changed','sourceCheckedAt':'2099-01-01T00:00:00+00:00'}}}})
    assert crew.verify_resolution(row)['status']=='failed'


def test_fresh_healthy_verification_covers_every_target_and_old_success_cannot_hide_new_failure(environment):
    from datetime import datetime,timezone
    row=crew.reason_request('verified','지식인 복구해',repair=True,steps=0)
    crew.observe(row,'host','execution_result',{}, {'results':[{'result':{'project':'naver_kin','recoveryVerified':True}}]})
    assert crew.verify_resolution(row)['status']=='verified_resolved'
    crew.observe(row,'host','execution_result',{}, {'results':[{'result':{'project':'naver_kin','status':'failed'}}]})
    assert crew.verify_resolution(row)['status']=='failed'
    crew.observe(row,'host','project_status',{'project':'naver_kin'},{'data':{'observation':{'id':'naver_kin','status':'healthy','source':{'sourceCheckedAt':datetime.now(timezone.utc).isoformat()}}}})
    assert crew.verify_resolution(row)['status']=='verified_resolved'
    row['permissions']['projects'].append('naver_blog')
    assert crew.verify_resolution(row)['status']!='verified_resolved'


def test_colleague_can_consult_second_specialist_and_return_to_original_owner(environment,monkeypatch):
    replies=iter([('consult','publi'),('consult','patch'),('finish',''),('finish',''),('finish','')]);actors=[]
    def ask(row):
        actors.append(row['actor']);kind,peer=next(replies);row['lastRoute']={'provider':'codex','model':'actual','reasoningEffort':'high'}
        return {'decision':kind,'colleague':peer,'plan':['근거 확인'],'message':'실제 관측을 검토합니다.','tool':'','arguments':'{}','evidence_ids':['e0']}
    monkeypatch.setattr(crew,'ask',ask)
    row=crew.reason_request('collaborate','지식인 원인 알려줘',steps=5)
    assert actors==['jarvis','publi','patch','publi','jarvis'] and row['status']=='answered'


def test_ceo_lane_never_claims_background_goal_and_background_lane_never_claims_ceo(environment,monkeypatch):
    background=crew.reason_request('background','지식인 점검',origin='project-monitor',steps=0)
    ceo=crew.reason_request('ceo','지식인 질문',steps=0)
    for row in (background,ceo):row['nextCheckAt']=0;crew.save(row)
    seen=[]
    monkeypatch.setattr(crew,'advance',lambda row,steps:seen.append(row['id']))
    assert crew.resume_ceo_once() and seen==[ceo['id']]
    seen.clear();assert crew.resume_background_once() and seen==[background['id']]


def test_verified_case_is_evaluated_then_retrieved_but_not_falsely_marked_applied(environment,monkeypatch):
    row=crew.reason_request('learn','지식인 복구해',repair=True,steps=0)
    row.update(status='answered',answer='실제 복구 확인',resolution={'status':'verified_resolved'})
    crew.remember_case(row)
    index=crew.load(crew.GOALS/'recent-cases.json');index['cases'][0]['evaluateAfter']=0;crew.write(crew.GOALS/'recent-cases.json',index)
    monkeypatch.setattr(crew,'overview',lambda:{'projects':[{'id':'naver_kin','status':'healthy','counts':{'submitted':None}}]})
    assert crew.evaluate_case_once()
    case=crew.load(crew.GOALS/'recent-cases.json')['cases'][0]
    assert case['evaluationStatus']=='adopted' and case['postMetrics'][0]['counts']['submitted'] is None
    monkeypatch.setattr(crew,'overview',lambda:{'projects':[{'id':'naver_kin','status':'attention','counts':{'submitted':0}}]})
    second=crew.reason_request('learn-again','지식인 복구해',repair=True,steps=0)
    assert second['retrievedCases'][0]['recipeId']==row['id'] and second['priorCases']
    assert not second.get('caseApplications')


def test_same_recovery_plan_can_advance_distinct_phases_but_not_repeat_a_phase(environment):
    row=crew.reason_request('phases','지식인 복구해',repair=True,steps=0)
    plan={'step':'review','status':'ready','plan':{'project':'naver_kin'}}
    action={'agent':'publi','tool':'advance_project_recovery','args':{'task_id':'project-incident:actual','plan_sha256':'a'*64}}
    with patch('common.repair_workflow._recovery_row',return_value=(Path('/tmp/unused'),plan)),patch('common.repair_workflow.recovery_expected_actor',return_value='jarvis'),patch('server.agent_tools.enqueue_staff_request',return_value={'taskId':'task','status':'queued'}) as enqueue:
        first=crew.tool_call(row,'dispatch',action)
        row.setdefault('executed',{})[first['requestId']]='completed';row.pop('pendingAction')
        with pytest.raises(ValueError,match='Same action'):crew.tool_call(row,'dispatch',action)
        plan['step']='final_review'
        second=crew.tool_call(row,'dispatch',action)
        assert first['requestId']!=second['requestId'] and enqueue.call_count==2


def test_reused_recipe_is_recorded_only_after_actual_matching_action_is_queued(environment):
    row=crew.reason_request('apply-case','지식인 복구해',repair=True,steps=0)
    action={'agent':'patch','tool':'recover_project_runtime','args':{'project':'naver_kin'}}
    row['priorCases']=[{'goalId':'prior','actionHistory':[{'action':action}]}]
    row['retrievedCases']=[{'recipeId':'prior','version':'sha'}]
    with patch('server.agent_tools.enqueue_staff_request',return_value={'taskId':'task','status':'queued'}):
        crew.tool_call(row,'dispatch',action)
    assert row['caseApplications'][0]['recipeId']=='prior' and row['caseApplications'][0]['requestId']==row['pendingAction']['requestId']


def test_real_frontend_keeps_goal_replies_with_dates_and_peer_dialogue_visible():
    import subprocess
    source=(Path(__file__).resolve().parents[2]/'chat.html').read_text()
    functions=[]
    for name,next_name in [('isMessageWorkstream','workActorDisplay'),('isNoiseMessage','getAgentBrainBadge'),('staffMessageText','isConversationMessage'),('isConversationMessage','renderWorkRecords')]:
        start=source.index('  function '+name+'(');end=source.index('  function '+next_name+'(',start);functions.append(source[start:end])
    script='\n'.join(functions)+'''
const assert = require('node:assert/strict');
const goal = {id:'goal-result-x', who:'jarvis', goalId:'verified-goal', userTurnId:'ceo-turn', text:'10월 23일 이후 미수집입니다.', replyToCeo:true};
assert.equal(isNoiseMessage(goal), false);
assert.equal(isConversationMessage(goal), true);
assert.equal(isConversationMessage({...goal, id:'goal-step-x', who:'publi', replyToCeo:false}), true);
assert.equal(isConversationMessage({...goal, autonomous:true, userTurnId:''}), false);
'''
    result=subprocess.run(['node','-e',script],capture_output=True,text=True)
    assert result.returncode==0,result.stderr


def test_channel_engine_is_searchable_read_only_and_outputs_are_not_walked(environment):
    root=environment/'naver_kin';root.mkdir()
    (root/'posting.py').write_text('operationCounts = {}\n')
    output=root/'output';output.mkdir();(output/'private.py').write_text('operationCounts = private\n')
    result=crew.search_source({'query':'operationCounts'})
    assert 'naver_kin/posting.py:1:' in result['matches'] and 'private.py' not in result['matches']
    from common.coding_job import _file
    with pytest.raises(ValueError,match='Frozen'):_file(environment,'naver_kin/posting.py')
    assert _file(environment,'naver_kin/posting.py',read_only=True).is_file()


def test_new_ownership_registry_is_readable_but_not_an_autonomous_edit_target(environment):
    from common.coding_job import _file
    root=environment/'dashboard/common';root.mkdir(parents=True)
    (root/'staff_capabilities.py').write_text('ACTION_OWNERS = {}\n')
    with pytest.raises(ValueError):_file(environment,'dashboard/common/staff_capabilities.py')
    assert _file(environment,'dashboard/common/staff_capabilities.py',read_only=True).is_file()
