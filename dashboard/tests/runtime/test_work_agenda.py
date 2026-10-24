"""Enabled production contracts: ownership, actual evidence, room ACK and recovery."""
import ast
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import multiprocessing
from pathlib import Path
import threading
import time
from typing import Any, Dict
from unittest.mock import Mock

import pytest
from fastapi import HTTPException
from common import work_agenda as agendas, conference_dispatch as conferences
from common.collection_observability import load, write


@pytest.fixture
def runtime(monkeypatch):
    agendas.initialize()
    monkeypatch.setattr(conferences,'QUEUE',agendas.ROWS.parent)
    room={'messages':[]}
    source=Path(__file__).resolve().parents[2]/'agents/chat_room.py'
    node=next(n for n in ast.parse(source.read_text()).body if isinstance(n,ast.FunctionDef) and n.name=='receive_agenda_event')
    node.decorator_list=[]
    scope={'Dict':Dict,'Any':Any,'HTTPException':HTTPException,'_ROOM_LOCK':threading.RLock(),
           'load_room_data':lambda:room,'append_or_update_room_message':lambda message:room['messages'].append(message)}
    exec(compile(ast.Module(body=[node],type_ignores=[]),'<actual-agenda-receiver>','exec'),scope)
    def deliver(payload):
        scope['receive_agenda_event'](payload)
        return payload['id']
    monkeypatch.setattr('common.crew_chat_bridge._deliver',deliver)
    model=Mock(return_value=({'message':'실제 기록을 확인해 이 안건의 결과를 보고합니다.','plan':['같은 대상의 원천 확인','실제 결과 검증']},
                            {'provider':'test','model':'mock-model','reasoningEffort':'high'},'jarvis'))
    monkeypatch.setattr(agendas,'_model_message',model)
    return room,scope,model


def offer(name='A',kind='goal',project='naver_blog',priority=10):
    return agendas.propose(kind,name,title=name,project=project,source={'goalId':name},
                           completion='이 작업의 실제 원천 증거 확인',priority=priority)


def opened(identity):
    value=agendas.admit(identity)
    assert value
    agendas.record_plan(identity,['현재 대상 확인','실행 후 검증'])
    assert agendas.flush_events(identity)
    return value


def proof(identity):
    agendas.verified(identity,{'verified':True,'source':'actual-test-receipt'},
        staff={'actor':'publi','text':'실제 작업 결과를 확인했습니다.'},
        manager={'actor':'jarvis','text':'정해 둔 완료 조건을 확인했고 이 안건을 마무리합니다.'})


def test_next_meeting_waits_for_actual_verification_and_both_room_receipts(runtime,monkeypatch):
    first=offer();second=offer('B');opened(first)
    assert agendas.admit(second) is None
    with pytest.raises(ValueError):agendas.verified(first,{'verified':False,'source':'process exit 0'})
    proof(first)
    real=__import__('common.crew_chat_bridge',fromlist=['_deliver'])._deliver
    monkeypatch.setattr('common.crew_chat_bridge._deliver',lambda p:p['id'])
    assert not agendas.finish_reports(first)
    assert agendas.admit(second) is None
    assert agendas.get(first)['status']=='report_pending'
    monkeypatch.setattr('common.crew_chat_bridge._deliver',real)
    assert agendas.finish_reports(first)
    assert agendas.admit(second)
    assert [m['agendaStage'] for m in runtime[0]['messages']]==['opening','staff_result','closing']


def test_five_concurrent_producers_and_claims_have_one_owner(runtime):
    ids=list(ThreadPoolExecutor(5).map(lambda n:offer(str(n)),range(5)))
    with ThreadPoolExecutor(5) as pool:
        tokens=list(pool.map(agendas.admit,ids))
    assert sum(t is not None for t in tokens)==1
    assert len(load(agendas.STATE)['pending'])==4


def test_stable_candidate_does_not_reset_failed_or_finished_work(runtime):
    identity=offer();opened(identity);agendas.hold(identity,'로그인 확인 필요')
    assert offer()==identity and agendas.get(identity)['status']=='blocked'
    assert len(load(agendas.STATE)['pending'])==0
    assert agendas.admit(offer('B')) is None
    proof(identity);assert agendas.finish_reports(identity)
    assert offer()==identity and agendas.get(identity)['status']=='closed'


def test_wrong_owner_version_project_and_different_slot_cannot_execute(runtime):
    identity=offer();value=opened(identity)
    with pytest.raises(agendas.AgendaWaiting):
        with agendas.context({**value,'version':2}):pass
    with agendas.context(value):
        with pytest.raises(agendas.AgendaWaiting):agendas.require(project='threads')
        agendas.bind_target({'account':'soultin','date':'2026-10-25','slot':'07:40'})
        with pytest.raises(agendas.AgendaWaiting):agendas.bind_target({'account':'other','date':'2026-10-25','slot':'07:40'})


def test_execution_cannot_start_before_opening_reaches_room(runtime,monkeypatch):
    identity=offer();value=agendas.admit(identity)
    agendas.record_plan(identity,['실제 상태 확인'])
    with agendas.context(value),pytest.raises(agendas.AgendaWaiting):
        with agendas.execution():pass
    agendas.flush_events(identity)
    with agendas.context(value),agendas.execution():
        assert agendas.running(agendas.get(identity))
    assert not agendas.running(agendas.get(identity))


def test_two_steps_of_same_agenda_cannot_overlap(runtime):
    identity=offer();value=opened(identity)
    def other_thread():
        with agendas.context(value),agendas.execution():return True
    with agendas.context(value),agendas.execution():
        with ThreadPoolExecutor(1) as pool:
            with pytest.raises(agendas.AgendaWaiting):pool.submit(other_thread).result()


def test_crash_after_verification_replays_only_reports_and_survives_reload(runtime):
    identity=offer();opened(identity);proof(identity)
    before=load(agendas.path(identity))
    assert agendas.process_once()
    after=load(agendas.path(identity))
    assert after['status']=='closed' and before['verification']==after['verification']
    assert not agendas.process_once()
    assert len(runtime[0]['messages'])==3
    runtime[2].assert_not_called()


def test_receiver_rejects_unrecorded_reports_and_deduplicates(runtime):
    identity=offer();opened(identity)
    note=agendas.get(identity)['events']['opening']
    packet={'agendaId':identity,'stage':'opening','id':note['id']}
    runtime[1]['receive_agenda_event'](packet)
    assert len(runtime[0]['messages'])==1
    with pytest.raises(HTTPException):runtime[1]['receive_agenda_event']({**packet,'id':'invented'})


def test_dead_conference_worker_is_unknown_and_never_automatically_restarted(runtime,monkeypatch):
    identity=offer('conference','conference');opened(identity)
    item={'agendaId':'a'*64,'kind':'kin','arguments':{},'requestedAt':1,'status':'running',
          'pid':99999999,'startTicks':'not-a-process','businessAgendaId':identity}
    file=conferences.QUEUE/(item['agendaId']+'.json');write(file,item)
    spawn=Mock();monkeypatch.setattr(conferences.subprocess,'Popen',spawn)
    assert not conferences.process_once()
    assert load(file)['status']=='unknown'
    assert agendas.active()['id']==identity
    spawn.assert_not_called()


def test_different_channel_pending_worker_cannot_bypass_global_owner(runtime,monkeypatch):
    first=offer();opened(first)
    other=offer('B','conference',project='threads')
    file=conferences.QUEUE/('b'*64+'.json')
    write(file,{'agendaId':'b'*64,'kind':'threads','arguments':{},'requestedAt':1,'status':'queued','businessAgendaId':other})
    spawn=Mock();monkeypatch.setattr(conferences.subprocess,'Popen',spawn)
    assert not conferences.process_once()
    spawn.assert_not_called()


def test_conference_no_work_and_failed_receipts_keep_same_agenda(runtime):
    identity=offer('A','conference');opened(identity)
    conferences.record_conference_result({'businessAgendaId':identity,'agendaId':'a'*64,'status':'completed','outcomes':[],
                                         'eligibility':{'reason':'no_due_slot'}})
    assert agendas.active()['id']==identity
    assert agendas.get(identity)['status']=='recovering'
    assert not agendas.get(identity).get('verification')


def test_new_timer_tick_preserves_exact_conference_history(runtime,monkeypatch):
    args={'action':'naver','date':'2099-01-01','account':'soultin','slot':'07:40'}
    receipt=conferences._request_single('parameters',args)
    file=conferences.QUEUE/(receipt['agendaId']+'.json');row=load(file)
    row.update(status='failed',attemptHistory=[{'evidence':'preserved'}]);write(file,row)
    again=conferences._request_single('parameters',args)
    assert again['agendaId']==receipt['agendaId'] and load(file)['attemptHistory']==row['attemptHistory']
    assert load(file)['requestedAt']==row['requestedAt'] and load(file)['status']=='failed'


def test_batch_requests_become_independent_concrete_slots_without_running_engine(runtime,monkeypatch):
    from common import channel_parameters as parameters
    monkeypatch.setattr(parameters,'policy',lambda:{'effectiveDate':'2099-01-01','naver':{'soultin':{'slots':['07:40','12:20']}},'cf':{}})
    result=conferences.request('parameters',{'action':'prepare','date':'2099-01-01','account':None,'slot':None})
    assert result['count']==2
    rows=[load(conferences.QUEUE/(r['agendaId']+'.json')) for r in result['items']]
    assert {r['arguments']['slot'] for r in rows}=={'07:40','12:20'}
    assert len({r['businessAgendaId'] for r in rows})==2
    assert all(r['status']=='queued' for r in rows)


def test_staff_boundary_rejects_unowned_execution_before_tool_call(runtime,monkeypatch):
    from common.ego_executor import execute_staff_action
    execute=Mock();monkeypatch.setattr('server.agent_tools.execute_agent_tool',execute)
    with pytest.raises(agendas.AgendaWaiting):
        execute_staff_action({'agent':'patch','tool':'recover_project_runtime','args':{'project':'collections'}},task_id='test',request_id='test')
    execute.assert_not_called()


def test_direct_runtime_recovery_cannot_start_services_without_owner(runtime,monkeypatch):
    from common import runtime_recovery
    shell=Mock();monkeypatch.setattr(runtime_recovery.subprocess,'run',shell)
    with pytest.raises(agendas.AgendaWaiting):runtime_recovery.recover_project_runtime('collections')
    shell.assert_not_called()


def test_board_omits_private_source_and_does_not_claim_held_is_complete(runtime):
    identity=offer();opened(identity);agendas.hold(identity,'외부 로그인 필요')
    view=agendas.view()
    assert 'source' not in view['active'] and 'owner' not in view['active']
    assert view['active']['status']=='blocked' and not view['active']['verified']
    assert view['recent']==[]


def test_no_extra_model_for_unchanged_opening_or_report_retries(runtime):
    identity=offer('A','staff');agendas.admit(identity)
    assert agendas.process_once()
    for _ in range(3):agendas.process_once()
    assert runtime[2].call_count==1
    assert len(runtime[0]['messages'])==1


def test_child_environment_preserves_owner_and_other_environment(runtime):
    identity=offer();value=opened(identity)
    with agendas.context(value):
        env=agendas.child_environment({'DISPLAY':':10'})
    assert json.loads(env['BAROLAB_AGENDA_CONTEXT'])==value and env['DISPLAY']==':10'


def test_report_model_failure_keeps_publication_proof(runtime,monkeypatch):
    monkeypatch.setattr('agents.agent_tools.staff_tool_reply',Mock(side_effect=TimeoutError))
    result=conferences.report_outcome({'state':'published_verified','permalink':'https://example.org/post'},'test')
    assert result['publicationVerified'] is True and result['reportPending'] is True
    identity=offer('A','conference');opened(identity)
    conferences.record_conference_result({'businessAgendaId':identity,'agendaId':'b'*64,'status':'completed','outcomes':[result]})
    assert agendas.active()['status']=='report_pending'
    with agendas.context(agendas.token(agendas.active())),pytest.raises(agendas.AgendaWaiting):
        with agendas.execution():pass


def test_explicit_switch_waits_for_running_step_and_room_ack(runtime,monkeypatch):
    first=offer();second=offer('B');value=opened(first)
    with agendas.context(value),agendas.execution():
        agendas.request_switch(first,second,'현재 안건 보류 후 B로 전환해')
        assert not agendas.switch_once(agendas.active())
    deliver=__import__('common.crew_chat_bridge',fromlist=['_deliver'])._deliver
    monkeypatch.setattr('common.crew_chat_bridge._deliver',lambda p:p['id'])
    assert not agendas.process_once() and agendas.active()['id']==first
    monkeypatch.setattr('common.crew_chat_bridge._deliver',deliver)
    assert agendas.process_once()
    assert agendas.get(first)['status']=='suspended' and not agendas.get(first).get('verifiedAt')
    assert agendas.admit(second)
    assert agendas.view()['suspended'][0]['id']==first
    with pytest.raises(agendas.AgendaWaiting):
        with agendas.context(value):pass
    agendas.record_plan(second,['현재 B 확인']);agendas.flush_events(second)
    proof(second);assert agendas.finish_reports(second)
    agendas.resume(first)
    new_token=agendas.admit(first)
    assert new_token['version']>value['version'] and new_token['owner']!=value['owner']
    assert agendas.get(first)['plan']==['현재 대상 확인','실행 후 검증']


def test_uncertain_submission_cannot_release_owner_even_with_explicit_switch(runtime):
    first=offer();second=offer('B');opened(first)
    write(conferences.QUEUE/('b'*64+'.json'),{'businessAgendaId':first,'status':'unknown'})
    agendas.request_switch(first,second,'A 보류 후 B 먼저')
    assert not agendas.process_once()
    assert agendas.active()['id']==first and agendas.admit(second) is None
    assert '제출 여부' in agendas.active()['blocker']


def test_pending_timer_target_merges_into_exact_active_goal_without_duplicate_run(runtime):
    goal=offer('CEO',priority=0);value=opened(goal)
    args={'action':'naver','date':'2099-01-01','account':'soultin','slot':'07:40'}
    timer=conferences._request_single('parameters',args)
    old=load(conferences.QUEUE/(timer['agendaId']+'.json'))['businessAgendaId']
    with agendas.context(value):receipt=conferences._request_single('parameters',args)
    assert receipt['agendaId']==timer['agendaId']
    assert agendas.get(old)['status']=='linked'
    assert old not in load(agendas.STATE)['pending']
    assert load(conferences.QUEUE/(timer['agendaId']+'.json'))['businessAgendaId']==goal


def test_exact_reservation_terminal_receipt_and_repair_observer(runtime):
    from common import project_autonomy as autonomy,repair_workflow
    identity='c'*64
    write(conferences.QUEUE/(identity+'.json'),{'agendaId':identity,'kind':'parameters',
        'arguments':{'action':'naver','date':'2099-01-01','account':'soultin','slot':'07:40'},
        'requestedAt':123,'status':'completed','outcomes':[{'reservationVerified':True,'publicationVerified':False}]})
    result={'project':'naver_blog','status':'awaiting_completion','conferenceAgendaId':identity,'conferenceRequestedAt':123}
    outcome,_=autonomy.terminal_result(result)
    assert outcome['reservationVerified'] is True and outcome['publicationVerified'] is False
    row={'planSha256':'sha','resumeResult':result}
    repair_workflow._observe_recovery_process(row)
    assert row['status']=='ready' and row['step']=='verify'
    assert row['resumeResult']['reservationVerified'] is True


def test_mult_project_execution_splits_and_keeps_original_unfinished(runtime,monkeypatch,tmp_path):
    from agents import crew_reasoning as crew
    monkeypatch.setattr(crew,'GOALS',tmp_path/'goals')
    monkeypatch.setattr(crew,'overview',lambda:{'projects':[]})
    ask=Mock();monkeypatch.setattr(crew,'ask',ask)
    parent=crew.reason_request('ceo-all','CF와 네이버 블로그를 모두 정상화해',execute=True,repair=True,steps=0,projects=['cf_blog','naver_blog'])
    assert parent['status']=='waiting_children' and not parent.get('businessAgendaId')
    children=[load(crew.goal_path(i)) for i in parent['subgoals']]
    assert len(children)==2 and not parent.get('resolution')
    assert len({c['businessAgendaId'] for c in children})==2
    assert sum(agendas.get(c['businessAgendaId'])['status']=='meeting' for c in children)==1
    ask.assert_not_called()
    for child in children:
        identity=child['businessAgendaId'];opened(identity);proof(identity);assert agendas.finish_reports(identity)
        crew.advance(parent,0)
    assert parent['status']=='waiting_children' and not parent.get('resolution')
    from datetime import datetime,timezone
    monkeypatch.setattr(crew,'overview',lambda:{'projects':[{'id':p,'status':'healthy','source':{'sourceCheckedAt':datetime.now(timezone.utc).isoformat()}} for p in ('cf_blog','naver_blog')]})
    crew.advance(parent,0)
    assert parent['status']=='answered' and parent['resolution']['status']=='verified_resolved'


def test_status_question_does_not_preempt_or_create_business_agenda(runtime,monkeypatch,tmp_path):
    from agents import crew_reasoning as crew
    monkeypatch.setattr(crew,'GOALS',tmp_path/'goals')
    monkeypatch.setattr(crew,'overview',lambda:{'projects':[]})
    active=offer();opened(active)
    question=crew.reason_request('status','왜 아직 진행을 못하고 있어?',steps=0)
    assert not question.get('businessAgendaId') and not agendas.active().get('switchRequest')
    assert agendas.active()['id']==active


def test_exact_target_cannot_close_from_generic_healthy_snapshot(runtime):
    from agents import crew_reasoning as crew
    from datetime import datetime,timezone
    identity=offer();value=opened(identity)
    with agendas.context(value):agendas.bind_target({'account':'soultin','slot':'07:40'})
    row={'permissions':{'execute':True,'repair':True,'projects':['naver_blog']},'businessAgendaId':identity,
         'createdAt':time.time(),'observations':[{'id':'e0','tool':'project_status','observedAt':time.time(),
         'result':{'data':{'observation':{'id':'naver_blog','status':'healthy','source':{'sourceCheckedAt':datetime.now(timezone.utc).isoformat()}}}}}]}
    assert crew.verify_resolution(row)['status']=='waiting_verification'


def test_watchdog_proposes_work_without_direct_engine_process(runtime,monkeypatch):
    from common import system_watchdog
    propose=Mock(return_value={'status':'no_work'});spawn=Mock()
    monkeypatch.setattr(conferences,'request',propose);monkeypatch.setattr(system_watchdog.subprocess,'Popen',spawn)
    assert system_watchdog.trigger_missed_slot_catchup()==[]
    assert system_watchdog.clean_zombie_locks_and_recover()==[]
    propose.assert_called_once();spawn.assert_not_called()


def test_known_failed_slots_are_separate_units_under_original_goal(runtime,monkeypatch,tmp_path):
    from agents import crew_reasoning as crew
    monkeypatch.setattr(crew,'GOALS',tmp_path/'goals')
    units=[{'workId':str(i)*64,'date':'2099-01-01','identity':'soultin','slot':slot} for i,slot in [(1,'07:40'),(2,'12:20')]]
    monkeypatch.setattr(crew,'overview',lambda:{'projects':[{'id':'naver_blog','recoverableWork':units}]})
    row=crew.reason_request('all-slots','네이버 블로그 정상화해',execute=True,repair=True,steps=0,projects=['naver_blog'])
    assert row['status']=='waiting_children' and len(row['subgoals'])==2
    children=[load(crew.goal_path(i)) for i in row['subgoals']]
    targets=[agendas.get(c['businessAgendaId'])['workTarget']['arguments'] for c in children]
    assert {t['slot'] for t in targets}=={'07:40','12:20'}
    assert not row.get('businessAgendaId') and row['recheckWholeScope'] is True


def test_native_blocked_run_is_failed_not_no_work(runtime,monkeypatch,tmp_path):
    from types import SimpleNamespace
    monkeypatch.setattr(conferences,'ROOT',tmp_path)
    identity=offer('kin','conference',project='naver_kin');opened(identity)
    key='d'*64
    write(conferences.QUEUE/(key+'.json'),{'agendaId':key,'businessAgendaId':identity,'kind':'kin','arguments':{},'status':'running'})
    (tmp_path/'dashboard/data').mkdir(parents=True)
    write(tmp_path/'dashboard/data/kin-automation-state.json',{'runs':[{'runId':'actual-run','state':'blocked','reason':'operation_RuntimeError'}]})
    monkeypatch.setattr(conferences,'install_channel_conferences',lambda kind:SimpleNamespace(main=lambda args:None,_conference_results=[]))
    monkeypatch.setattr(conferences,'report_outcome',Mock(return_value={'outcome':'작업 차단'}))
    conferences._work(key)
    receipt=load(conferences.QUEUE/(key+'.json'))
    assert receipt['status']=='failed' and receipt['failureReason']=='native_run_blocked:operation_RuntimeError'
    assert receipt['eligibility']['runs'][0]['runId']=='actual-run'
    assert agendas.get(identity)['status']=='recovering' and not agendas.get(identity).get('verification')


def test_kin_retry_keeps_agenda_and_original_attempt_with_bounded_retries(runtime,monkeypatch):
    args={'date':'2026-10-25','account':'stone0747','slot':'original-cadence'}
    request=conferences._request_single('kin',args);file=conferences.QUEUE/(request['agendaId']+'.json')
    receipt=load(file);identity=receipt['businessAgendaId'];ownership=opened(identity)
    receipt.update(status='failed',failureReason='execution_evidence_directory_collision',
                                    eligibility={'runs':[{'runId':'original-run','state':'blocked'}]})
    write(file,receipt)
    monkeypatch.setattr(conferences,'kin_retry_target',lambda row:{'questionId':'123','account':'stone0747','runId':'original-run'})
    with agendas.context(ownership):result=conferences.retry_active()
    retried=load(file)
    assert result['businessAgendaId']==identity and retried['attempts']==2 and retried['status']=='queued'
    assert retried['attemptHistory'][0]['eligibility']==receipt['eligibility']
    assert retried['retryTarget']['questionId']=='123'
    retried['status']='failed';write(file,retried)
    with agendas.context(ownership):conferences.retry_active()
    retried=load(file);assert retried['attempts']==3
    retried['status']='failed';write(file,retried)
    with agendas.context(ownership),pytest.raises(ValueError,match='budget is exhausted'):conferences.retry_active()


def test_kin_underlying_failure_reaches_recovery_instead_of_draft_validation(runtime,monkeypatch,tmp_path):
    from types import SimpleNamespace
    monkeypatch.setattr(conferences,'ROOT',tmp_path)
    identity=offer('kin','conference',project='naver_kin');opened(identity);key='e'*64
    write(conferences.QUEUE/(key+'.json'),{'agendaId':key,'businessAgendaId':identity,'kind':'kin','arguments':{},'status':'running'})
    (tmp_path/'dashboard/data').mkdir(parents=True)
    write(tmp_path/'dashboard/data/kin-automation-state.json',{'runs':[{'runId':'actual-run','state':'blocked','reason':'operation_RuntimeError'}]})
    failure={'errorType':'FileExistsError','reason':'execution_evidence_directory_collision','questionId':'123'}
    monkeypatch.setattr(conferences,'install_channel_conferences',lambda kind:SimpleNamespace(main=lambda args:None,_conference_results=[],_conference_failures=[failure]))
    monkeypatch.setattr(conferences,'report_outcome',Mock(return_value={'outcome':'작업 차단'}))
    conferences._work(key)
    receipt=load(conferences.QUEUE/(key+'.json'))
    assert receipt['status']=='failed' and receipt['failureReason']==failure['reason']
    assert receipt['executionFailures']==[failure]
    assert agendas.get(identity)['blocker']==failure['reason']


def test_late_result_does_not_implicitly_resume_suspended_work(runtime):
    first=offer();second=offer('B');opened(first)
    agendas.request_switch(first,second,'A 유예 후 B 먼저')
    assert agendas.process_once()
    agendas.hold(first,'늦게 도착한 오류 기록',recovery=True)
    assert agendas.get(first)['status']=='suspended'
    proof(first)
    assert agendas.get(first)['status']=='suspended' and not agendas.active()
    agendas.resume(first);assert agendas.admit(first)
    assert agendas.active()['status']=='report_pending'
    assert agendas.finish_reports(first)
    assert agendas.admit(second)
