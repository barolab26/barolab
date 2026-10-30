"""Run with PYTHONPATH=dashboard:. python -m unittest discover -s dashboard/tests."""
import datetime as dt
import functools
import hashlib
import json
import sys
import tempfile
import unittest
from contextlib import nullcontext
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'server'))

from common import knowledge_policy as knowledge, llm_usage as usage
from dashboard.agents import synapse
from dashboard.collectors import revenue
from server.growth import page_performance_evidence


class BusinessControls(unittest.TestCase):
    def strategy_action(self, **changes):
        action=dict(owner='trace',task='수집 상태 관측 결과 보고',why='기존 수집 자료 확인',metric='원천 관측 상태',
                    checkAt=(self.now+dt.timedelta(days=1)).isoformat(),stopCondition='원천 조회 불가 시 다른 독립 작업 진행',
                    project='collections',targetUrl='',tool='read_agent_status',arguments='{"project":"collections"}',after=-1)
        return {**action,**changes}

    def test_strategy_assignment_runs_real_queue_worker_and_reports_returned_result(self):
        from agents import crew_reasoning as crew
        from server import agent_tools as tools
        from common import work_agenda as agendas
        requests=self.data/'staff-requests';requests.mkdir()
        (self.data/'goals').mkdir()
        row=dict(id=self.agenda,status='ready',mode='strategy_execute',origin='ceo',goal='계획대로 실행해',actor='jarvis',leadActor='jarvis',
                 permissions={'execute':True,'repair':False,'projects':['collections']},observations=[],
                 strategyValidated=True,strategy={'actions':[self.strategy_action()]})
        def execute(action,**kwargs):
            return tools.execute_agent_tool(action['agent'],action['tool'],**action['args'])
        with patch.object(crew,'GOALS',self.data/'goals'),patch.object(tools,'STAFF_REQUEST_DIR',requests), \
             patch.object(agendas,'enabled',return_value=False),patch('common.crew_chat_bridge.emit_work_event',return_value='observed-event'), \
             patch('common.ego_executor.execute_staff_action',side_effect=execute), \
             patch('server.project_health.observed_projects',return_value=[{'id':'collections','status':'observed'}]), \
             patch('common.recovery_evidence.failure_targets',return_value=[]), \
             patch.object(tools,'staff_tool_reply') as speech,patch.object(tools,'_review_ceo_request',side_effect=AssertionError('commentary must be asynchronous')),patch.object(crew,'remember_case'):
            crew.advance(row,1)
            self.assertEqual(row['status'],'waiting_execution')
            self.assertEqual(len(list(requests.glob('*.json'))),1)
            crew.advance(row,1)
            self.assertEqual(len(list(requests.glob('*.json'))),1)
            self.assertTrue(tools.process_staff_request_once())
            receipt=json.loads(next(requests.glob('*.json')).read_text())
            self.assertEqual(receipt['status'],'completed')
            self.assertIn('hostReport',receipt['results'][0])
            self.assertNotIn('staffResponse',receipt['results'][0])
            crew.advance(row,1)
        speech.assert_not_called()
        self.assertEqual(row['status'],'answered')
        self.assertEqual(row['resolution']['status'],'execution_completed')
        self.assertEqual(row['strategyAssignments'][0]['status'],'completed')
        self.assertIn('수익 효과는 별도로',row['answer'])
        self.assertIn(chr(10),row['answer'])

    def test_optional_ceo_review_has_its_own_consumer(self):
        from server import agent_tools as tools
        requests=self.data/'staff';requests.mkdir()
        receipt={'requestId':'msg-123-user:jarvis','status':'completed','results':[]}
        (requests/'receipt.json').write_text(json.dumps(receipt))
        with patch.object(tools,'STAFF_REQUEST_DIR',requests),patch.object(tools,'_review_ceo_request') as review:
            self.assertTrue(tools.process_staff_review_once())
        review.assert_called_once()
        with patch.object(tools,'STAFF_REQUEST_DIR',requests),patch.object(tools,'DATA_DIR',self.data), \
             patch.object(tools,'staff_tool_reply') as model:
            self.assertTrue(tools.process_staff_review_once())
            self.assertFalse(tools.process_staff_review_once())
        model.assert_not_called()

    def test_execute_followup_inherits_validated_strategy_without_global_agenda(self):
        from agents import crew_reasoning as crew
        parent=dict(id=self.agenda,mode='strategy',goal='오늘의 전략',permissions={'projects':['collections']},
                    strategyValidated=True,strategy={'actions':[self.strategy_action()]},observations=[],plan=[])
        with patch.object(crew,'GOALS',self.data/'goals'),patch.object(crew,'conversation_parent',return_value=parent), \
             patch.object(crew,'overview',return_value={'projects':[]}),patch.object(crew,'advance'):
            row=crew.reason_request('followup','그대로 실행해',execute=True,steps=0)
        self.assertEqual(row['mode'],'strategy_execute')
        self.assertEqual(row['strategy'],parent['strategy'])
        self.assertEqual(row['permissions']['projects'],['collections'])
        self.assertNotIn('businessAgendaId',row)

    def test_followup_to_model_failure_does_not_create_generic_execution_agendas(self):
        from agents import crew_reasoning as crew
        parent=dict(id=self.agenda,mode='strategy',goal='오늘의 전략',permissions={'projects':['threads']},
                    strategyValidated=False,strategy={'actions':[]},observations=[],plan=[])
        with patch.object(crew,'GOALS',self.data/'goals'),patch.object(crew,'conversation_parent',return_value=parent), \
             patch.object(crew,'overview',return_value={'projects':[]}),patch.object(crew,'advance'):
            row=crew.reason_request('failed-followup','그대로 실행해',execute=True,steps=0)
        self.assertEqual(row['mode'],'strategy_execute')
        self.assertNotIn('businessAgendaId',row)
        self.assertNotIn('strategyValidated',row)

    def test_independent_work_is_queued_when_repair_is_not_authorized(self):
        from agents import crew_reasoning as crew
        from server import agent_tools as tools
        requests=self.data/'staff';requests.mkdir()
        repair=self.strategy_action(owner='patch',project='naver_kin',tool='recover_project_runtime',arguments='{"project":"naver_kin"}')
        publish=self.strategy_action(owner='publi',project='threads',tool='run_project_cycle',arguments='{"project":"threads"}')
        row=dict(id=self.agenda,permissions={'execute':True,'repair':False,'projects':['naver_kin','threads']},
                 observations=[],strategyValidated=True,strategy={'actions':[repair,publish]})
        with patch.object(crew,'save'),patch.object(tools,'STAFF_REQUEST_DIR',requests), \
             patch.object(tools,'enqueue_staff_request',return_value={'taskId':'staff:real','status':'queued'}) as enqueue:
            crew.advance_strategy_execution(row)
        self.assertEqual(row['strategyAssignments'][0]['status'],'held')
        self.assertEqual(row['strategyAssignments'][1]['status'],'queued')
        enqueue.assert_called_once()

    def test_queued_publication_is_not_completed_without_public_proof(self):
        from agents import crew_reasoning as crew
        from server import agent_tools as tools
        requests=self.data/'staff';requests.mkdir()
        action=self.strategy_action(owner='publi',project='threads',tool='run_project_cycle',arguments='{"project":"threads"}')
        row=dict(id=self.agenda,permissions={'execute':True,'repair':False,'projects':['threads']},observations=[],
                 strategyValidated=True,strategy={'actions':[action]},strategyRound=1)
        with patch.object(crew,'save'),patch.object(tools,'STAFF_REQUEST_DIR',requests), \
             patch.object(tools,'enqueue_staff_request',return_value={'taskId':'task','status':'queued'}):
            crew.advance_strategy_execution(row)
            task=row['strategyAssignments'][0]
            Path(task['receiptPath']).write_text(json.dumps({'status':'completed','results':[{'result':{'ok':True,'status':'no_work'}}]}))
            with patch.object(crew,'remember_case'):
                crew.advance_strategy_execution(row)
        self.assertEqual(task['status'],'failed')
        self.assertEqual(row['resolution']['status'],'execution_partial')

    def test_failed_work_replans_once_and_never_replays_same_action(self):
        from agents import crew_reasoning as crew
        from server import agent_tools as tools
        requests=self.data/'staff';requests.mkdir()
        action=self.strategy_action(owner='publi',project='threads',tool='run_project_cycle',arguments='{"project":"threads"}')
        row=dict(id=self.agenda,permissions={'execute':True,'repair':False,'projects':['threads']},observations=[],
                 strategyValidated=True,strategy={'actions':[action]})
        with patch.object(crew,'save'),patch.object(tools,'STAFF_REQUEST_DIR',requests), \
             patch.object(tools,'enqueue_staff_request',return_value={'taskId':'task','status':'queued'}), \
             patch.object(crew,'remember_case'),patch.object(crew,'overview',return_value={'projects':[]}), \
             patch.object(crew,'answer_strategy',side_effect=lambda r:r) as review:
            crew.advance_strategy_execution(row)
            task=row['strategyAssignments'][0]
            Path(task['receiptPath']).write_text(json.dumps({'status':'failed','results':[]}))
            crew.advance_strategy_execution(row)
        review.assert_called_once()
        self.assertEqual(row['resolution']['status'],'execution_partial')
        self.assertNotIn('strategyHistory',row)

    def test_failed_channel_switches_to_new_independent_task_and_keeps_failure_history(self):
        from agents import crew_reasoning as crew
        from server import agent_tools as tools
        requests=self.data/'staff';requests.mkdir()
        first=self.strategy_action(owner='publi',project='threads',tool='run_project_cycle',arguments='{"project":"threads"}')
        alternate=self.strategy_action(owner='publi',project='cf_blog',tool='run_project_cycle',arguments='{"project":"cf_blog"}')
        row=dict(id=self.agenda,permissions={'execute':True,'repair':False,'projects':['threads','cf_blog']},observations=[],
                 strategyValidated=True,strategy={'actions':[first]})
        def enqueue(identity,actions):
            receipt={'taskId':'staff:'+hashlib.sha256(identity.encode()).hexdigest(),'status':'queued'}
            (requests/(hashlib.sha256(identity.encode()).hexdigest()+'.json')).write_text(json.dumps(receipt))
            return receipt
        def review(goal):
            goal.update(strategy={'decision':'기존 장애는 보존하고 CF의 독립 작업을 먼저 실행합니다.','actions':[alternate]},strategyValidated=True)
        with patch.object(crew,'save'),patch.object(tools,'STAFF_REQUEST_DIR',requests), \
             patch.object(tools,'enqueue_staff_request',side_effect=enqueue),patch.object(crew,'remember_case'), \
             patch.object(crew,'overview',return_value={'projects':[]}),patch.object(crew,'answer_strategy',side_effect=review):
            crew.advance_strategy_execution(row)
            failed=row['strategyAssignments'][0]
            Path(failed['receiptPath']).write_text(json.dumps({'status':'failed','results':[]}))
            crew.advance_strategy_execution(row)
            self.assertEqual(row['status'],'ready')
            crew.advance_strategy_execution(row)
            replacement=row['strategyAssignments'][0]
            self.assertNotEqual(replacement['requestId'],failed['requestId'])
            Path(replacement['receiptPath']).write_text(json.dumps({'status':'completed','results':[{'result':{
                'ok':True,'status':'completed','publicationVerified':True}}]}))
            crew.advance_strategy_execution(row)
        self.assertEqual(row['strategyRound'],2)
        self.assertEqual(row['strategyHistory'][0][0]['status'],'failed')
        self.assertEqual(row['resolution']['status'],'execution_completed')
        self.assertIn('미완료 1건',row['answer'])

    def test_selected_asset_must_match_observed_source_and_native_tool(self):
        from agents import crew_reasoning as crew
        action=self.strategy_action(owner='publi',project='threads',tool='publish_strategy_link',
            targetUrl='https://www.baronote.kr/selected',arguments='{"project":"threads","target_url":"https://www.baronote.kr/selected"}')
        row=dict(permissions={'projects':['threads']},observations=[{'tool':'projects','result':{'businessEvidence':{
            'trafficCandidates':[{'url':action['targetUrl']}]}}}])
        self.assertTrue(crew.validate_strategy(row,{'actions':[action]}))
        with self.assertRaises(ValueError):
            crew.validate_strategy({**row,'observations':[]},{'actions':[action]})
        with self.assertRaises(ValueError):
            crew.validate_strategy(row,{'actions':[{**action,'after':0}]})

    def test_selected_link_never_overwrites_existing_slot_content(self):
        import sqlite3
        from common import project_autonomy as autonomy, work_agenda as agendas, conference_dispatch as conference
        from threads_posting import posting as engine
        database=self.data/'threads.sqlite3'
        with sqlite3.connect(database) as db:
            db.execute('CREATE TABLE parts(part_id TEXT,document TEXT)')
            db.execute('INSERT INTO parts VALUES(?,?)',('existing-0',json.dumps({'source':{'url':'https://www.baronote.kr/original'}})))
        with patch.object(agendas,'enabled',return_value=False),patch.object(autonomy,'load',return_value={'enabled':True,'projects':['threads']}), \
             patch.object(conference,'concrete_requests',return_value=[{'partId':'existing-0'}]), \
             patch.object(engine,'_threads_config_DB',database),patch.object(conference,'request') as submit:
            result=autonomy.publish_strategy_link('https://www.baronote.kr/selected')
        submit.assert_not_called()
        self.assertEqual(result['reason'],'existing_slot_has_different_content')

    def test_strategy_publication_waits_for_selected_outbound_link_not_just_main_post(self):
        import sqlite3
        from common import project_autonomy as autonomy, conference_dispatch as conference
        from threads_posting import posting as engine
        database=self.data/'threads.sqlite3'
        target='https://www.baronote.kr/selected'
        arguments={'account':'mustpickinfo','date':'2026-10-26','slot':'12:30','targetUrl':target}
        document=json.dumps({'source':{'url':target},'outbound_url':target+'?utm_source=threads'})
        with sqlite3.connect(database) as db:
            db.execute('CREATE TABLE parts(kind TEXT,state TEXT,permalink TEXT,document TEXT,account_key TEXT,publication_date TEXT,slot TEXT)')
            db.executemany('INSERT INTO parts VALUES(?,?,?,?,?,?,?)',[
                ('main','published_verified','https://www.threads.com/@mustpickinfo/post/main',document,'mustpickinfo','2026-10-26','12:30'),
                ('followup','queued',None,document,'mustpickinfo','2026-10-26','12:30')])
        queue=self.data/'queue';queue.mkdir()
        identity='b'*64
        (queue/(identity+'.json')).write_text(json.dumps(dict(agendaId=identity,kind='threads',status='completed',
            requestedAt=1,arguments=arguments,outcomes=[{'publicationVerified':True}])))
        result=dict(project='threads',conferenceAgendaId=identity,conferenceRequestedAt=1,targetUrl=target)
        with patch.object(conference,'QUEUE',queue),patch.object(engine,'_threads_config_DB',database):
            self.assertIsNone(autonomy.terminal_result(result))
            with sqlite3.connect(database) as db:
                db.execute("UPDATE parts SET state='published_verified',permalink='https://www.threads.com/@mustpickinfo/post/reply' WHERE kind='followup'")
            terminal,_=autonomy.terminal_result(result)
            self.assertTrue(terminal['outboundLinkVerified'])
            self.assertTrue(terminal['publicationVerified'])
            with sqlite3.connect(database) as db:
                db.execute("UPDATE parts SET document=? WHERE kind='followup'",(json.dumps({'source':{'url':target},'outbound_url':'https://www.baronote.kr/different'}),))
            terminal,_=autonomy.terminal_result(result)
            self.assertFalse(terminal['ok'])
            self.assertFalse(terminal['outboundLinkVerified'])

    def test_model_failure_never_enqueues_a_strategy_task(self):
        from agents import crew_reasoning as crew
        from server import agent_tools as tools
        row=dict(id=self.agenda,goal='전략대로 실행해',leadActor='jarvis',permissions={'execute':True,'repair':True,'projects':['threads']},observations=[])
        with patch('common.llm_client.generate_json',side_effect=RuntimeError('down')),patch.object(crew,'save'), \
             patch.object(tools,'enqueue_staff_request') as enqueue:
            crew.advance_strategy_execution(row)
        enqueue.assert_not_called()
        self.assertEqual(row['resolution']['status'],'model_unavailable')
        self.assertEqual(row['strategy']['actions'],[])

    def test_expired_pending_assignment_reports_unresolved_without_cancelling_or_replaying(self):
        from agents import crew_reasoning as crew
        from server import agent_tools as tools
        requests=self.data/'staff';requests.mkdir()
        action=self.strategy_action()
        row=dict(id=self.agenda,strategyRound=1,permissions={'execute':True,'repair':False,'projects':['collections']},
                 observations=[],strategyValidated=True,strategy={'actions':[action]})
        with patch.object(crew,'save'),patch.object(crew,'remember_case'),patch.object(tools,'STAFF_REQUEST_DIR',requests), \
             patch.object(tools,'enqueue_staff_request',return_value={'taskId':'task','status':'queued'}) as enqueue:
            crew.advance_strategy_execution(row)
            task=row['strategyAssignments'][0]
            Path(task['receiptPath']).write_text(json.dumps({'status':'awaiting_completion'}))
            with patch.object(crew.time,'time',return_value=self.now.timestamp()+3*86400):
                crew.advance_strategy_execution(row)
        enqueue.assert_called_once()
        self.assertEqual(task['reason'],'deadline_elapsed_receipt_pending')
        self.assertEqual(json.loads(Path(task['receiptPath']).read_text())['status'],'awaiting_completion')
        self.assertEqual(row['resolution']['status'],'execution_partial')

    def test_staff_polls_closed_agenda_receipt_without_replaying_publication(self):
        from server import agent_tools as tools
        from common import work_agenda as agendas
        requests=self.data/'staff';requests.mkdir()
        result=dict(ok=True,status='awaiting_completion',project='threads',conferenceAgendaId='b'*64,conferenceRequestedAt=1)
        row=dict(requestId='strategy:'+self.agenda+':1:0',taskId='staff:task',status='awaiting_completion',
                 businessAgendaId=self.agenda,results=[{'agent':'publi','tool':'publish_strategy_link','result':result}])
        (requests/'task.json').write_text(json.dumps(row))
        terminal=dict(ok=True,status='completed',publicationVerified=True,project='threads')
        with patch.object(tools,'STAFF_REQUEST_DIR',requests),patch.object(agendas,'enabled',return_value=True), \
             patch.object(agendas,'active',side_effect=AssertionError('poll cannot depend on current agenda')), \
             patch.object(agendas,'staff_result'),patch('common.project_autonomy.terminal_result',return_value=(terminal,{})), \
             patch('common.ego_executor.execute_staff_action') as publish,patch.object(tools,'staff_tool_reply') as speech:
            self.assertTrue(tools.process_staff_request_once())
        publish.assert_not_called()
        speech.assert_not_called()
        receipt=json.loads((requests/'task.json').read_text())
        self.assertEqual(receipt['status'],'completed')
        self.assertTrue(receipt['results'][0]['result']['publicationVerified'])

    def test_company_strategy_routes_to_jarvis_before_check_keyword(self):
        from agents import chat_room as chat
        from agents import crew_reasoning as crew
        question='지금 현재 프로젝트 상태를 전반적으로 체크하고 너희들이 팀장이라면 다음으로 뭘 할 거 같아? 그리고 오늘 목표를 어떻게 전략적으로 수립할 거 같아?'
        self.assertEqual(chat.parse_mentioned_agents(question), ['jarvis'])
        self.assertEqual(crew.request_mode(question), 'strategy')
        self.assertEqual(chat.parse_mentioned_agents('@publi '+question), ['publi'])
        self.assertEqual(crew.request_mode('전략대로 실행해'), 'strategy_execute')

    def test_strategy_answers_without_operational_tools_and_preserves_plan(self):
        from agents import crew_reasoning as crew
        business={'priorDayRevenue':[{'amount':None,'currency':'USD'}], 'trafficSites':[{'domain':'example.com','status':'collected'}]}
        row=dict(id=self.agenda,mode='strategy',goal='오늘 목표를 어떻게 세울까?',leadActor='jarvis',
                 permissions={'execute':False,'repair':False,'projects':['threads']}, observations=[{'id':'e0','tool':'projects',
                 'result':{'businessEvidence':business,'executionContext':{'unrelated':'broken kin'},'projects':[]}}])
        action=self.strategy_action(owner='publi',project='threads',tool='run_project_cycle',arguments='{"project":"threads"}')
        value=dict(decision='기존 자산의 작은 유입 실험을 우선하겠습니다.',hypotheses=['유입 증가 여부는 검증 필요'],actions=[action])
        with patch('common.llm_client.generate_json',return_value=value) as model, \
             patch.object(crew,'save'),patch.object(crew,'remember_case'),patch.object(crew,'tool_call') as tool:
            crew._advance(row,1)
        self.assertEqual(row['status'],'answered')
        self.assertEqual(row['resolution']['status'],'advice_only')
        self.assertEqual(row['strategy']['actions'],[action])
        self.assertIn('trafficSites',model.call_args.args[0])
        self.assertNotIn('broken kin',model.call_args.args[0])
        self.assertIn('stopCondition',str(model.call_args.kwargs['response_schema']))
        self.assertTrue(model.call_args.kwargs['_skip_memory'])
        self.assertFalse(model.call_args.kwargs['allow_provider_recovery'])
        model.assert_called_once()
        tool.assert_not_called()

    def test_strategy_model_failure_reports_system_error_without_fake_plan(self):
        from agents import crew_reasoning as crew
        row=dict(id=self.agenda,goal='오늘 전략',leadActor='jarvis',observations=[])
        with patch('common.llm_client.generate_json',side_effect=usage.RouteCoolingDown('cooldown')), \
             patch.object(crew,'save'),patch.object(crew,'remember_case'):
            crew.answer_strategy(row)
        self.assertEqual(row['status'],'answered')
        self.assertEqual(row['answerSource'],'host')
        self.assertIn('[시스템 알림]',row['answer'])
        self.assertEqual(row['strategy']['actions'],[])
        self.assertFalse(row['strategyValidated'])
        self.assertEqual(row['resolution']['status'],'model_unavailable')

    def test_model_status_reads_alone_are_not_accepted_as_a_business_strategy(self):
        from agents import crew_reasoning as crew
        row=dict(id=self.agenda,goal='오늘 전략',leadActor='jarvis',permissions={'projects':['collections']},observations=[])
        value=dict(decision='자료부터 확인하겠습니다.',hypotheses=[],actions=[self.strategy_action()])
        with patch('common.llm_client.generate_json',return_value=value),patch.object(crew,'save'):
            crew.answer_strategy(row)
        self.assertFalse(row['strategyValidated'])
        self.assertEqual(row['strategy']['actions'],[])

    def test_model_error_is_delivered_as_system_notice_not_staff_dialogue(self):
        from agents import chat_room as chat
        from agents import crew_reasoning as crew
        path=self.data/'goal.json'
        goal=dict(id=self.agenda,userTurnId='msg-1-user',goal='오늘 전략',origin='ceo',leadActor='jarvis',
                  status='answered',answerSource='host',answer='[시스템 알림] 모델 응답 실패',
                  resolution={'status':'model_unavailable','label':'모델 장애'})
        path.write_text(json.dumps(goal))
        room={'messages':[{'id':'msg-1-user','who':'user','text':'오늘 전략'}]}
        with patch.object(crew,'goal_path',return_value=path),patch.object(chat,'load_room_data',return_value=room), \
             patch.object(chat,'append_or_update_room_message') as append,patch.object(chat,'_append_agent_direct_thread') as direct:
            chat.receive_goal_result({'goalId':self.agenda})
        self.assertEqual(append.call_args.args[0]['who'],'system')
        self.assertEqual(append.call_args.args[0]['taskTracker']['status'],'failed')
        direct.assert_not_called()

    def test_model_failure_does_not_manufacture_business_decision_from_candidate(self):
        from agents import crew_reasoning as crew
        candidate=dict(url='https://example.com/post',sessions=7,complete=True,start='2026-10-19',end='2026-10-25')
        row=dict(id=self.agenda,goal='오늘 전략',leadActor='jarvis',observations=[{
            'id':'e0','tool':'projects','result':{'businessEvidence':{'trafficCandidates':[candidate]}}}])
        with patch('common.llm_client.generate_json',side_effect=RuntimeError('unavailable')), \
             patch.object(crew,'save'),patch.object(crew,'remember_case'):
            crew.answer_strategy(row)
        self.assertNotIn(candidate['url'],row['answer'])
        self.assertNotIn('잠정 실행안',row['answer'])
        self.assertEqual(row['strategy']['actions'],[])
        self.assertEqual(row['leadRoute']['provider'],'host')

    def test_strategy_provider_timeout_does_not_cascade_into_another_provider(self):
        from common import llm_client
        config={'active':'codex','providers':{'codex':{'model':'primary'}}}
        with patch.object(llm_client.settings,'load',return_value=config), \
             patch.object(llm_client,'_generate_json',side_effect=RuntimeError('exceeded its hard timeout')) as model, \
             patch('common.crew_chat_bridge.record_model_route'):
            with self.assertRaises(RuntimeError):
                llm_client.generate_json.__wrapped__.__wrapped__('prompt',provider='codex',reasoning_effort='low',allow_provider_recovery=False)
        model.assert_called_once()

    def test_strategy_does_not_inherit_recovery_parent(self):
        from agents import crew_reasoning as crew
        with patch.object(crew,'GOALS',self.data/'goals'), \
             patch.object(crew,'conversation_parent') as parent,patch.object(crew,'overview',return_value={'projects':[]}), \
             patch.object(crew,'ensure_business_agenda'),patch.object(crew,'advance'):
            row=crew.reason_request('strategy-test','그럼 팀장이라면 오늘 전략은?',steps=0)
        parent.assert_not_called()
        self.assertNotIn('parentGoalId',row)
        self.assertEqual(row['mode'],'strategy')

    def test_business_summary_keeps_traffic_and_missing_revenue_separate(self):
        from server.growth import business_evidence
        (self.data/'traffic.json').write_text(json.dumps({'checkedAt':'now','sites':{'example.com':{
            'ga4':{'status':'collected','periods':{'day':{'sessions':7,'start':'2026-10-25','end':'2026-10-25'}}}}}}))
        summary=business_evidence(self.root)
        self.assertFalse(summary['availableSources']['revenue'])
        self.assertTrue(summary['availableSources']['traffic'])
        self.assertEqual(summary['trafficSites'][0]['periods']['day']['sessions'],7)
        self.assertEqual(summary['priorDayRevenue'],[])

    def test_low_level_work_events_stay_in_details_not_room_messages(self):
        from agents import chat_room as chat
        message=dict(id='event',taskId='goal-one',phase='completed',who='jarvis',stage='goal-decision')
        room={'messages':[]}
        with patch.object(chat,'project_work_event',return_value=message), \
             patch.object(chat,'load_room_data',return_value=room),patch.object(chat,'save_room_data'), \
             patch.object(chat,'append_or_update_room_message') as append,patch.object(chat.EVENT_BUS,'publish'):
            result=chat.receive_work_event({})
        append.assert_not_called()
        self.assertTrue(result['detailOnly'])
        self.assertEqual(room['workEvents'],[message])

    def test_parked_investigation_does_not_occupy_publication_lane(self):
        from common import work_agenda as agendas
        rows=self.data/'operations';rows.mkdir()
        goals=self.data/'chats/reasoning-goals';goals.mkdir(parents=True)
        goal_id='c'*64;next_id='b'*64
        goal_path=goals/(goal_id+'.json')
        goal_path.write_text(json.dumps({'status':'blocked'}))
        state=self.data/'agenda.json'
        state.write_text(json.dumps({'enabled':True,'activeId':self.agenda,'activeIds':[self.agenda],'pending':[next_id]}))
        blocked=dict(id=self.agenda,kind='goal',project='naver_kin',status='blocked',controllerGoalId=goal_id)
        pending=dict(id=next_id,kind='conference',project='naver_kin',status='queued',priority=0,createdAt=0,owner='host',version=1)
        for row in (blocked,pending):(rows/(row['id']+'.json')).write_text(json.dumps(row))
        with patch.object(agendas,'DATA',self.data),patch.object(agendas,'ROWS',rows), \
             patch.object(agendas,'STATE',state),patch.object(agendas,'running',return_value=[]):
            goal_path.write_text(json.dumps({'status':'blocked','pendingAction':{'requestId':'still-owned'}}))
            self.assertIsNone(agendas.admit(next_id))
            goal_path.write_text(json.dumps({'status':'blocked'}))
            self.assertTrue(agendas.admit(next_id))
            self.assertEqual(agendas.active()['id'],next_id)
            self.assertEqual(agendas.get(self.agenda)['status'],'blocked')

    def test_read_only_staff_task_runs_without_occupying_existing_write_lane(self):
        from common import work_agenda as agendas
        rows=self.data/'operations';rows.mkdir()
        state=self.data/'agenda.json';next_id='b'*64
        state.write_text(json.dumps({'enabled':True,'activeId':self.agenda,'activeIds':[self.agenda],'pending':[next_id]}))
        active=dict(id=self.agenda,kind='goal',project='collections',status='executing')
        query=dict(id=next_id,kind='staff',project='collections',status='queued',priority=10,createdAt=0,owner='host',version=1,
                   source={'actions':[{'tool':'read_agent_status','args':{'project':'collections'}}]})
        for row in (active,query):(rows/(row['id']+'.json')).write_text(json.dumps(row))
        with patch.object(agendas,'ROWS',rows),patch.object(agendas,'STATE',state):
            self.assertTrue(agendas.admit(next_id))
            self.assertEqual(agendas.get(self.agenda)['status'],'executing')

    def test_conference_evidence_resolves_business_id_only_with_matching_binding(self):
        from agents import crew_reasoning as crew
        from common import work_agenda as agendas
        folder=self.data/'publication-conferences';folder.mkdir()
        conference_id='b'*64;path=folder/(conference_id+'.json')
        path.write_text(json.dumps({'businessAgendaId':self.agenda,'status':'failed'}))
        business=dict(id=self.agenda,source={'conferenceId':conference_id})
        with patch.object(crew,'ROOT',self.root),patch.object(agendas,'get',return_value=business):
            self.assertTrue(crew.read_evidence({'name':'conference:'+self.agenda})['available'])
            path.write_text(json.dumps({'businessAgendaId':'wrong'}))
            self.assertFalse(crew.read_evidence({'name':'conference:'+self.agenda})['available'])

    def test_third_identical_read_parks_investigation_instead_of_looping(self):
        from agents import crew_reasoning as crew
        row=dict(id=self.agenda,actor='jarvis',leadActor='jarvis',status='ready',decisions=0,maxSteps=8,
                 permissions={'execute':False,'repair':False},observations=[],lastRoute={'provider':'test','model':'test'})
        decision=dict(decision='tool',message='근거 확인',plan=['자료 확인'],tool='evidence',arguments='{"name":"traffic"}')
        with patch.object(crew,'refresh_pending',return_value=True),patch.object(crew,'save'), \
             patch.object(crew,'set_progress'),patch.object(crew,'deliver_step'), \
             patch.object(crew,'ask',return_value=decision), \
             patch.object(crew,'tool_call',return_value={'sha256':'same-source'}) as read:
            crew._advance(row,4)
        self.assertEqual(read.call_count,3)
        self.assertEqual(row['status'],'blocked')
        self.assertIn('다른 실행 가능한 업무',row['answer'])

    def test_agenda_budget_exhaustion_answers_with_preserved_findings(self):
        from agents import crew_reasoning as crew
        row = dict(id=self.agenda, status='ready', actor='jarvis', leadActor='jarvis',
                   decisions=0, maxSteps=8, permissions={'repair': False}, observations=[],
                   lastMessage='수집 자료 일부의 확인 시각이 오래되었습니다.', plan=['캐시 갱신 주기 확인'])
        with patch.object(crew, 'refresh_pending', return_value=True), patch.object(crew, 'save'), \
             patch.object(crew, 'set_progress'), \
             patch.object(crew, 'ask', side_effect=usage.UsageBudgetExceeded('agenda_token_budget_exhausted')) as ask:
            crew._advance(row, 1)
        ask.assert_called_once()
        self.assertEqual(row['status'], 'answered')
        self.assertEqual(row['resolution']['status'], 'investigation_closed')
        self.assertIn(row['lastMessage'], row['answer'])
        self.assertIn('캐시 갱신 주기 확인', row['answer'])
        row['permissions'] = {'execute': True, 'repair': True}
        self.assertEqual(crew.progress_view(row)['status'], 'replied')
        self.assertEqual(usage.DEFAULT_BUDGET['agendaTokens'], 1000000)

    def test_budget_answer_is_not_rejected_for_lacking_publication_proof(self):
        from agents import crew_reasoning as crew
        from common import work_agenda as agendas
        row = dict(id=self.agenda, businessAgendaId=self.agenda, status='answered',
                   investigationClosed='agenda_token_budget_exhausted', answer='조사 요약',
                   resolution={'status': 'investigation_closed'})
        agenda = dict(id=self.agenda, kind='goal', status='executing', controllerGoalId=self.agenda)
        with patch.object(crew, 'ensure_business_agenda'), patch.object(crew, 'save'), \
             patch.object(crew, '_advance', return_value=row), patch.object(agendas, 'enabled', return_value=True), \
             patch.object(agendas, 'get', return_value=agenda), \
             patch.object(agendas, 'admit', return_value={'id': self.agenda}), \
             patch.object(agendas, 'context', return_value=nullcontext()), \
             patch.object(agendas, 'finish_investigation') as finish, patch.object(agendas, 'hold') as hold:
            crew.advance(row, 1)
        finish.assert_called_once_with(self.agenda, '조사 요약', 'agenda_token_budget_exhausted')
        hold.assert_not_called()
        self.assertTrue(row['delivered'])

    def test_reporting_budget_exhaustion_also_uses_host_summary(self):
        from common import work_agenda as agendas
        row = dict(id=self.agenda, kind='goal', status='report_pending', lastAction='실제 자료 확인')
        with patch.object(agendas, 'context', return_value=nullcontext()), \
             patch.object(agendas, 'token', return_value={}), patch.object(agendas, 'get', return_value=row), \
             patch.object(agendas, 'finish_reports', side_effect=usage.UsageBudgetExceeded('agenda_token_budget_exhausted')), \
             patch.object(agendas, 'finish_investigation') as finish:
            self.assertTrue(agendas._step_single_agenda(row))
        self.assertIn('실제 자료 확인', finish.call_args.args[1])

    def test_prompt_observations_deduplicates_without_changing_stored_evidence(self):
        from agents import crew_reasoning as crew
        events = [dict(id='e'+str(i), actor='jarvis', tool='project_status',
                       arguments={'project': 'collections'}, result={'large': 'x'*4000},
                       sha256=str(i), observedAt=i) for i in range(12)]
        original = json.dumps(events)
        compressed = crew.prompt_observations({'observations': events})
        self.assertEqual(sum('result' in e for e in compressed), 1)
        self.assertEqual(compressed[0]['sameAs'], 'e11')
        self.assertEqual(json.dumps(events), original)
        self.assertLess(len(json.dumps(compressed)), len(original)//3)

    def test_investigation_closes_without_model_or_success_claim_and_admits_next(self):
        from common import work_agenda as agendas
        rows = self.data / 'operations'
        rows.mkdir()
        state_path = self.data / 'agenda.json'
        next_id = 'b'*64
        state_path.write_text(json.dumps({'enabled': True, 'activeId': self.agenda, 'activeIds': [self.agenda],
                                          'pending': [next_id], 'recent': []}))
        for identity, status in ((self.agenda, 'blocked'), (next_id, 'queued')):
            (rows / (identity+'.json')).write_text(json.dumps(dict(id=identity, kind='goal', project='collections',
                status=status, title='raw '*100, version=1, owner='host', source={}, priority=10,
                createdAt=0, plan=['조사'], events={'opening': {'receivedAt': 1}})))
        def flush(identity):
            row = agendas.get(identity)
            for note in row['events'].values():note['receivedAt'] = 1
            agendas._save(row)
            return True
        with patch.object(agendas, 'ROWS', rows), patch.object(agendas, 'STATE', state_path), \
             patch.object(agendas, 'running', return_value=[]), patch.object(agendas, 'flush_events', side_effect=flush), \
             patch.object(agendas, 'performance', return_value={}), patch.object(agendas, '_model_message') as model:
            agendas.finish_investigation(self.agenda, '확인한 자료는 보존, 복구 결과는 미확인', 'agenda_token_budget_exhausted')
            self.assertTrue(agendas.finish_reports(self.agenda))
            closed = agendas.get(self.agenda)
            self.assertEqual(closed['status'], 'closed')
            self.assertFalse(closed.get('verification', {}).get('verified', False))
            self.assertLessEqual(len(closed['events']['closing']['text']), 30)
            self.assertNotIn('raw', closed['events']['closing']['text'])
            self.assertTrue(agendas.admit(next_id))
        model.assert_not_called()

    def test_closing_message_uses_slot_and_stays_under_thirty_characters(self):
        from common import work_agenda as agendas
        row = dict(id=self.agenda, project='naver_blog', title='원시 제목'*100,
                   source={'arguments': {'slot': '15:00'}})
        note = agendas.event(row, 'closing', 'jarvis', row['title'])
        self.assertEqual(note['text'], '[안건 종결] [네이버 블로그 15:00 슬롯]')
        self.assertLessEqual(len(note['text']), 30)

    def test_operational_check_title_is_korean_without_raw_observation(self):
        from agents import crew_reasoning as crew
        observation = dict(title='네이버 지식iN', status='attention',
                           activity={'status': 'overdue', 'lastAttemptAt': '2026-10-26T13:03:31+09:00'},
                           unrelated={'raw': 'must not appear'})
        now = dt.datetime.fromisoformat('2026-10-26T15:16:00+09:00').timestamp()
        with patch.object(crew.time, 'time', return_value=now):
            self.assertEqual(crew.operational_check_title(observation),
                             '[네이버 지식iN] 2시간 이상 주기 실행(13:03 이후) 미관측으로 인한 자동 운영 점검')
        self.assertNotIn('{', crew.operational_check_title({'title': '조회·수집', 'status': 'stale'}))
        self.assertIn('실행 기록 미확인', crew.operational_check_title({**observation, 'activity': {'status': 'overdue'}}))

    def test_kin_scheduler_recognizes_conference_dispatch_service(self):
        from naver_kin import posting as kin
        def query(args, **kwargs):
            unit = args[3]
            timer = unit.endswith('.timer')
            measure = 'measurement' in unit
            values = dict(LoadState='loaded', ActiveState='active' if timer else 'inactive',
                          UnitFileState='enabled', Result='success', ExecMainStatus='0',
                          WorkingDirectory='/project', Unit=unit.replace('.timer', '.service'),
                          ExecStart='python -m naver_kin.posting --measure' if measure else 'python -m common.conference_dispatch kin')
            return MagicMock(returncode=0, stdout='\n'.join(k+'='+v for k,v in values.items()))
        result = kin._naver_ubuntu_scheduler_observe(Path('/project'), lambda: 'now', query)
        self.assertTrue(all(task['registered'] and task['workflowMatches'] for task in result['tasks']))
        result = kin._naver_ubuntu_scheduler_observe(Path('/wrong'), lambda: 'now', query)
        self.assertFalse(any(task['registered'] for task in result['tasks']))

    def test_recovery_report_supersedes_older_stage_without_delivery_deadlock(self):
        from agents import chat_room as chat
        from common import work_agenda as agendas
        note=dict(id='report',who='jarvis',text='새 실패 원인',ts=2000,route={})
        row=dict(id=self.agenda,events={'blocked':note},status='recovering',completionCriteria='실제 결과')
        old=dict(id='report',who='jarvis',text='이전 실패 원인',ts=1000,agendaId=self.agenda,agendaStage='blocked')
        payload=dict(id='report',agendaId=self.agenda,stage='blocked')
        with patch.object(agendas,'get',return_value=row),patch.object(agendas,'acknowledge') as ack, \
             patch.object(chat,'load_room_data',return_value={'messages':[old]}), \
             patch.object(chat,'append_or_update_room_message') as append:
            self.assertTrue(chat.receive_agenda_event(payload)['stored'])
            self.assertEqual(append.call_args.args[0]['text'],'새 실패 원인')
            ack.assert_called_once()
            old['ts']=2000
            with self.assertRaises(chat.HTTPException):chat.receive_agenda_event(payload)

    def test_active_goal_recovers_missing_pending_marker(self):
        from agents import crew_reasoning as crew
        from common import work_agenda as agendas
        goals=self.data/'goals';goals.mkdir()
        (goals/(self.agenda+'.json')).write_text(json.dumps(dict(id=self.agenda,origin='agenda',status='waiting',nextCheckAt=1e20)))
        with patch.object(crew,'GOALS',goals),patch.object(agendas,'enabled',return_value=True), \
             patch.object(agendas,'active_rows',return_value=[{'recoveryGoalId':self.agenda}]), \
             patch.object(crew,'evaluate_case_once',return_value=False),patch.object(crew,'start_autonomous_goal_once',return_value=False):
            crew.resume_once('background')
        self.assertTrue((goals/'pending'/self.agenda).exists())

    def test_finished_investigation_reports_unresolved_and_releases_agenda(self):
        from common import work_agenda as agendas
        row=dict(id=self.agenda,status='blocked',kind='goal',controllerGoalId='b'*64)
        with patch.object(agendas,'context',return_value=nullcontext()),patch.object(agendas,'token',return_value={}), \
             patch.object(agendas,'waiting_investigation',return_value=True), \
             patch.object(agendas,'load',return_value={'answer':'수집 누락은 미해결'}), \
             patch.object(agendas,'finish_investigation') as finish:
            self.assertTrue(agendas._step_single_agenda(row))
        finish.assert_called_once_with(self.agenda,'수집 누락은 미해결','investigation_finished_unresolved')

    def test_recovery_discovery_keeps_the_bound_agenda_context(self):
        from common import repair_workflow as repair, work_agenda as agendas
        root=self.data/'repairs';root.mkdir()
        row=dict(type='project_recovery_v1',businessAgendaId=self.agenda,status='held',step='discover',
                 taskId='repair-test',planSha256='plan',plan={},discovered={})
        (root/'repair.json').write_text(json.dumps(row))
        business=dict(id=self.agenda,version=1,owner='owner',status='recovering',project='threads')
        def discover(value):
            self.assertEqual(agendas.current(),agendas.token(business))
            return {}
        with patch.object(repair,'ROOT',root),patch.object(repair,'_discover_recovery',side_effect=discover) as probe, \
             patch.object(agendas,'enabled',return_value=True),patch.object(agendas,'active_ids',return_value=[self.agenda]), \
             patch.object(agendas,'get',return_value=business):
            repair.dispatch_project_recovery_once()
        probe.assert_called_once()

    def test_bound_recovery_goal_can_deliver_without_a_ceo_chat_turn(self):
        from agents import chat_room as chat, crew_reasoning as crew
        from common import work_agenda as agendas
        path=self.data/'goal.json'
        path.write_text(json.dumps(dict(id=self.agenda,origin='agenda',businessAgendaId='b'*64,
                                       status='answered',answer='복구 조사 결과',answerSource='host')))
        with patch.object(crew,'goal_path',return_value=path), \
             patch.object(agendas,'get',return_value={'recoveryGoalId':self.agenda}), \
             patch.object(chat,'load_room_data',return_value={'messages':[{'id':'goal-result-'+self.agenda}]}):
            self.assertTrue(chat.receive_goal_result({'goalId':self.agenda})['ok'])
        with patch.object(crew,'goal_path',return_value=path),patch.object(agendas,'get',return_value={}), \
             patch.object(chat,'load_room_data',return_value={'messages':[]}):
            with self.assertRaises(chat.HTTPException):chat.receive_goal_result({'goalId':self.agenda})

    def setUp(self):
        import gc
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(lambda: (gc.collect(), self.temp.cleanup()))
        self.root = Path(self.temp.name)
        self.data = self.root / 'dashboard/data'
        self.data.mkdir(parents=True)
        self.now = dt.datetime.now(dt.timezone.utc)
        self.agenda = 'a' * 64

    def call(self, identity='one'):
        return dict(id=identity, provider='test', model='model', agendaId=self.agenda,
                    startedAt=self.now.isoformat(), inputTokens=100, outputTokens=20,
                    usageReports=1, latencyMs=2000, rateLimitHeaders={})

    def proof(self):
        from common.hermes_memory import write_verified_work_receipt
        document = self.root / 'publication.json'
        document.write_text(json.dumps({'status': 'verified', 'postId': '1', 'publicUrl': 'https://example.com/post',
                                        'publication': 'verified', 'verifiedAt': self.now.isoformat()}))
        return write_verified_work_receipt(self.root / 'receipt.json', work_type='verified_work_receipt_v1',
            channel='cf_blog', outcome='public_verified', scope='public_verified', source_agent='publi',
            evidence_text='Submitted article and matched public content to the saved document.',
            artifacts=[{'path': str(document), 'sha256': hashlib.sha256(document.read_bytes()).hexdigest()}],
            checks=[{'type': k, 'passed': True, 'evidenceRef': str(document)} for k in ('public_identity', 'public_content')])

    def test_summary_and_source_url_cannot_certify_knowledge(self):
        node = dict(type='PracticalKnowHow', active=True, title='Claim', method='Revenue doubled',
                    whenToUse='Always', measurementStatus='verified_fact_checked',
                    sourceUrl='https://example.com', factCheckSummary='Doctor agrees')
        self.assertFalse(knowledge.usable_knowhow(node))
        node['measurementStatus'] = 'observed_procedure'
        self.assertFalse(knowledge.usable_knowhow(node))

    def test_receipt_excerpt_and_changed_evidence(self):
        proof = self.proof()
        node = dict(type='PracticalKnowHow', active=True, title='Public verification',
                    method='matched public content to the saved document', whenToUse='After submission',
                    measurementStatus='observed_procedure', verifiedWorkProof=proof)
        self.assertTrue(knowledge.usable_knowhow(node))
        node['method'] = 'Revenue doubled'
        self.assertFalse(knowledge.usable_knowhow(node))
        node['method'] = 'matched public content to the saved document'
        (self.root / 'publication.json').write_text('{}')
        self.assertFalse(knowledge.usable_knowhow(node))

    def test_stale_cached_knowledge_is_filtered_at_delivery(self):
        (self.data / 'synapse-recipes.json').write_text(json.dumps({'knowledgeNotes': [
            dict(type='PracticalKnowHow', title='False promise', method='Guaranteed revenue', whenToUse='Always')]}))
        self.assertNotIn('Guaranteed revenue', synapse.recipe('draft', 'publi', self.root))

    def test_usage_attribution_and_admission(self):
        usage.record_call(self.call(), 'started', root=self.root, now=self.now)
        usage.record_call(self.call(), 'completed', root=self.root, now=self.now)
        state = json.loads((self.data / 'llm_usage_ledger.json').read_text())
        row = state['byAgenda'][self.agenda]
        self.assertEqual((row['inputTokens'], row['outputTokens'], row['modelCalls']), (100, 20, 1))
        policy = {**usage.DEFAULT_BUDGET, 'agendaTokens': 120}
        with self.assertRaisesRegex(usage.UsageBudgetExceeded, 'agenda_token'):
            usage.check_budget(state, self.call('two'), policy, self.root)
        self.assertIsNone(usage.resource_summary(self.root)['actualCostUsd'])

    def test_active_calls_and_experiment_limit_are_enforced(self):
        folder = self.data / 'publication-conferences/operations'
        folder.mkdir(parents=True)
        (folder / (self.agenda + '.json')).write_text(json.dumps({'businessExperiment': {'maxModelCalls': 1}}))
        usage.record_call(self.call(), 'started', root=self.root, now=self.now)
        with self.assertRaisesRegex(usage.UsageBudgetExceeded, 'agenda_call'):
            usage.record_call(self.call('two'), 'started', root=self.root, now=self.now)
        state = json.loads((self.data / 'llm_usage_ledger.json').read_text())
        self.assertEqual(len(state['active']), 1)

    def test_metered_rejection_never_calls_provider(self):
        (self.data / 'llm-settings.json').write_text(json.dumps({'resourceBudget': {'dailyCalls': 1}}))
        provider = MagicMock(return_value={'ok': True})
        metered = usage.metered(provider)
        recorder = functools.partial(usage.record_call, root=self.root)
        with patch.object(usage, 'record_call', side_effect=recorder), \
             patch.object(usage, 'agenda_identity', return_value=None), \
             patch('common.crew_chat_bridge.current_model_identity', return_value=(None, None)):
            metered(provider='test', model='model')
            with self.assertRaises(usage.UsageBudgetExceeded):
                metered(provider='test', model='model')
        self.assertEqual(provider.call_count, 1)
        self.assertIsNone(usage._CURRENT.get())

    def test_midnight_preserves_agenda_budget_and_route_health(self):
        usage.record_call(self.call(), 'started', root=self.root, now=self.now)
        usage.record_call(self.call(), 'completed', root=self.root, now=self.now)
        tomorrow = self.now + dt.timedelta(days=1)
        usage.record_call({**self.call('two'), 'startedAt': tomorrow.isoformat()}, 'started', root=self.root, now=tomorrow)
        state = json.loads((self.data / 'llm_usage_ledger.json').read_text())
        self.assertEqual(state['byModel'], {})
        self.assertEqual(state['byAgenda'][self.agenda]['inputTokens'], 100)

    def test_direct_cli_calls_use_the_same_route_circuit(self):
        provider = MagicMock(side_effect=RuntimeError('failed'))
        provider.__module__ = 'common.codex_cli'
        metered = usage.metered(provider)
        recorder = functools.partial(usage.record_call, root=self.root)
        route = functools.partial(usage.route_attempt, root=self.root)
        with patch.object(usage, 'record_call', side_effect=recorder), \
             patch.object(usage, 'route_attempt', side_effect=route), \
             patch.object(usage, 'agenda_identity', return_value=None), \
             patch('common.crew_chat_bridge.current_model_identity', return_value=(None, None)):
            for _ in range(3):
                with self.assertRaises(RuntimeError):
                    metered(model='bad')
            with self.assertRaises(usage.RouteCoolingDown):
                metered(model='bad')
        self.assertEqual(provider.call_count, 3)

    def test_repeated_failures_open_route_and_one_probe_recovers(self):
        clock = [1000]
        for _ in range(3):
            with self.assertRaises(ValueError), usage.route_attempt('test', 'bad', root=self.root, now=lambda: clock[0]):
                raise ValueError('provider failed')
        with self.assertRaises(usage.RouteCoolingDown), usage.route_attempt('test', 'bad', root=self.root, now=lambda: clock[0]):
            self.fail('Cooling route must not run')
        with usage.route_attempt('test', 'other', root=self.root, now=lambda: clock[0]):
            pass
        clock[0] += 301
        with usage.route_attempt('test', 'bad', root=self.root, now=lambda: clock[0]):
            with self.assertRaises(usage.RouteCoolingDown), usage.route_attempt('test', 'bad', root=self.root, now=lambda: clock[0]):
                self.fail('Only one probe is allowed')
        self.assertEqual(json.loads((self.data / 'llm_usage_ledger.json').read_text())['routeHealth']['test:bad']['failures'], 0)

    def page_report(self, rows=None):
        return {'complete': True, 'checkedAt': self.now.isoformat(), 'currency': 'USD',
                'source': 'AdSense Management API v2', 'dimension': 'PAGE_URL',
                'start': (self.now.date() - dt.timedelta(days=7)).isoformat(),
                'end': (self.now.date() - dt.timedelta(days=1)).isoformat(),
                'timezone': 'Asia/Seoul', 'pages': rows or []}

    def test_actual_revenue_field_reaches_learning_and_partial_domains(self):
        address = 'https://www.example.com/post'
        node = {'type': 'Post', 'url': address, 'measurements': {}, 'publishedAt': self.now.isoformat()}
        graph = {'nodes': {synapse.key('post', synapse.url(address)): node}}
        report = self.page_report([{'url': address, 'estimatedRevenue': 1.25}])
        report.update(complete=False, sites=[{'domain': 'example.com', 'complete': True}, {'domain': 'other.com', 'complete': False}])
        synapse.observe(graph, report, 'adsense', ['revenue'])
        self.assertEqual(node['measurements']['adsense']['revenue'], 1.25)
        node['measurements'] = {}
        report['checkedAt'] = (self.now - dt.timedelta(hours=27)).isoformat()
        synapse.observe(graph, report, 'adsense', ['revenue'])
        self.assertEqual(node['measurements'], {})

    def test_missing_page_revenue_is_not_a_zero_or_winner(self):
        result = page_performance_evidence(now=self.now, metrics={'pagePerformance': self.page_report()},
                    revenue={'pagePerformance': {**self.page_report(), 'complete': False}}, traffic_source={}, domains=[])
        self.assertFalse(result['coverage']['revenueComplete'])
        self.assertEqual(result['revenueWinners'], [])

    def test_page_report_filters_content_product_and_preserves_missingness(self):
        cfg = {f'TEST_{k}': 'dummy' for k in ('ACCOUNT_ID', 'CLIENT_ID', 'CLIENT_SECRET', 'REFRESH_TOKEN')}
        client = MagicMock()
        meta = {'state': 'READY', 'timeZone': {'id': 'Asia/Seoul'}}
        report = {'headers': [{'name': 'PAGE_URL'}, {'name': 'ESTIMATED_EARNINGS', 'currencyCode': 'USD'}]}
        with patch('google.auth.transport.requests.AuthorizedSession') as session:
            session.return_value.__enter__.return_value = client
            client.get.side_effect = [MagicMock(ok=True, json=lambda: meta), MagicMock(ok=True, json=lambda: report)]
            with self.assertRaisesRegex(revenue.RevenueSourceError, 'No eligible page rows'):
                revenue.adsense_page_performance(cfg, self.now.date(), self.now.date(), ['example.com'], 'TEST')
            self.assertEqual(client.get.call_args.kwargs['params']['filters'], ['PRODUCT_CODE==AFC'])

    def test_frequent_refresh_collects_pages_once_and_refreshes_feedback(self):
        from common.revenue_refresh import collect_once
        backend = MagicMock()
        backend.read_json.side_effect = lambda p: json.loads(p.read_text()) if p.exists() else {}
        backend.collector_lock.side_effect = lambda p: nullcontext(True)
        backend.revenue_config.return_value = {}
        backend.ADPOST_ACCOUNTS = []
        backend.RevenueSourceError = revenue.RevenueSourceError
        backend.source = revenue.source
        backend.affiliate_configuration.return_value = {}
        backend.coupang.return_value = {'status': 'collected', 'daily': {}}
        backend.collect_page_revenue.return_value = {'complete': False, 'pages': [], 'sites': []}
        with patch('common.crew_chat_bridge.emit_work_event'), \
             patch('server.growth.refresh_performance_feedback', return_value={'status': 'partial'}) as refresh:
            collect_once(root=self.root, now=self.now, backend=backend)
            collect_once(root=self.root, now=self.now + dt.timedelta(seconds=60), backend=backend)
        self.assertEqual(backend.collect_page_revenue.call_count, 1)
        self.assertEqual(refresh.call_count, 2)
        self.assertFalse(json.loads((self.data / 'revenue.json').read_text())['pagePerformance']['complete'])

    def test_fallback_calls_have_separate_usage_and_correct_error(self):
        from common import llm_client
        config = {'active': 'codex', 'providers': {'codex': {'model': 'primary'}}}
        call = self.call()
        def respond(*args):
            usage.report_response(data={'usage': {'input_tokens': 30, 'output_tokens': 5}})
            return {'ok': True}, 'fallback'
        def generate(*args):
            if args[1] == 'codex':
                usage.report_response(data={'usage': {'input_tokens': 10, 'output_tokens': 2}})
                raise RuntimeError('exceeded its hard timeout')
            return respond(*args)
        token = usage._CURRENT.set(call)
        self.addCleanup(usage._CURRENT.reset, token)
        with patch.object(llm_client.settings, 'load', return_value=config), \
             patch.object(llm_client, '_generate_json', side_effect=generate), \
             patch('common.crew_chat_bridge.record_model_route'), \
             patch.object(usage, '_safe_record') as record:
            result = llm_client.generate_json.__wrapped__.__wrapped__('prompt', provider='codex', reasoning_effort='low')
        self.assertEqual(result, {'ok': True})
        rejected = record.call_args_list[0].args[0]
        self.assertEqual(rejected['errorType'], 'RuntimeError')
        self.assertNotEqual(rejected['id'], call['id'])
        self.assertEqual((rejected['inputTokens'], call['inputTokens']), (110, 30))

    def test_experiment_requires_measurement_and_bounded_resources(self):
        from common.work_agenda import validate_business_experiment
        value = dict(hypothesis='Link improves acquisition', targetUrl='https://example.com/post',
                     measurementDate='2026-11-02', evidenceConfidence='low', maxModelCalls=4,
                     successMetric='Measured UTM sessions', stopCondition='Stop after observation with no acquisition')
        self.assertEqual(validate_business_experiment(value), value)
        with self.assertRaises(ValueError):
            validate_business_experiment({**value, 'maxModelCalls': 0})
        with self.assertRaises(ValueError):
            validate_business_experiment({**value, 'measurementDate': 'soon'})


    def test_existing_threads_draft_reaches_ego_cleanup(self):
        from common import threads_screen as screen, ego_screen
        engine=MagicMock(BASE_DIR=str(self.root))
        part=dict(account_key=screen.ACCOUNT,part_id='attempt-1',kind='main',
                  publication_date='2026-10-26',text='approved')
        with patch.object(screen,'session',side_effect=lambda **kw:nullcontext(MagicMock())), \
             patch.object(screen,'web_identity',return_value=True), \
             patch.object(screen,'existing_draft',return_value=True), \
             patch.object(screen,'completed_draft',return_value=None), \
             patch.object(screen,'owned_empty_composer',return_value=None), \
             patch.object(ego_screen,'run',side_effect=RuntimeError('ego reached')) as run:
            with self.assertRaisesRegex(RuntimeError,'ego reached'):
                screen.ScreenAdapter(engine).submit_part({'account_key':screen.ACCOUNT},part,lambda:None)
        self.assertIn('Discard',run.call_args.kwargs['goal'])

    def test_failure_carries_its_own_screen_and_raw_traceback(self):
        from common import ego_screen, conference_dispatch as conference
        folder=self.root/'screen';folder.mkdir()
        (folder/'screen-execution.json').write_text(json.dumps({'observations':['Discard edit?','Discard','Cancel']}))
        page=MagicMock(url='https://www.threads.com/@mustpickinfo')
        page.locator.return_value.inner_text.return_value='Discard edit? Discard Cancel'
        with patch.object(ego_screen,'screen_lock',return_value=nullcontext()), \
             patch.object(ego_screen,'_run',side_effect=RuntimeError('actual failure')):
            try:ego_screen.run(page,port=9450,folder=folder)
            except RuntimeError as exc:
                with patch.object(conference,'extract_screen_context',side_effect=AssertionError('unrelated history')):
                    diagnostic=conference.failure_diagnostic(exc)
        self.assertEqual(diagnostic['errorMessage'],'actual failure')
        self.assertIn('RuntimeError: actual failure',diagnostic['traceback'])
        self.assertEqual(diagnostic['observations'],['Discard edit?','Discard','Cancel'])
        self.assertIn('Discard edit?',diagnostic['liveScreenContext']['domText'])
        self.assertIn('sourceLocation',diagnostic)

    def test_patch_browser_tool_runs_existing_ego_executor(self):
        from dashboard.agents import crew_reasoning as crew
        from common import browser_session, ubuntu_naver_browser, ego_screen
        import playwright.sync_api as playwright
        row={'id':self.agenda,'actor':'patch','permissions':{'repair':True,'projects':['threads']}}
        args={'port':9450,'url':'https://www.threads.com/@mustpickinfo','goal':'화면의 팝업을 닫아라'}
        page=MagicMock(url=args['url']);browser=MagicMock();browser.contexts=[MagicMock(pages=[page])]
        with patch.object(crew,'GOALS',self.root), \
             patch.object(crew,'browser_observe',return_value={'tabs':[{'url':args['url']}]}), \
             patch.object(ubuntu_naver_browser,'account_paths',return_value=('exe','profile',None)), \
             patch.object(playwright,'sync_playwright'), \
             patch.object(browser_session,'connect_sync',return_value=browser), \
             patch.object(ego_screen,'run',return_value={'status':'screen_task_complete','observations':['팝업 닫힘']}) as run:
            result=crew.tool_call(row,'browser_ego_action',args)
        self.assertTrue(result['ok'])
        self.assertEqual(run.call_args.kwargs['actor'],'patch')
        self.assertIn(args['goal'],run.call_args.kwargs['goal'])
        self.assertIn('browser_ego_action',crew.SCHEMA['properties']['tool']['enum'])
        for actor,repair in [('patch',False),('radar',True)]:
            with self.assertRaises(ValueError):
                crew.browser_ego_action({**row,'actor':actor,'permissions':{'repair':repair}},args)

    def test_browser_action_rejects_other_project_and_unknown_tab(self):
        from dashboard.agents import crew_reasoning as crew
        row={'id':self.agenda,'actor':'patch','permissions':{'repair':True,'projects':['threads']}}
        with self.assertRaisesRegex(ValueError,'outside'):
            crew.browser_ego_action(row,{'port':9335,'url':'https://blog.naver.com/yoonviews','goal':'close popup'})
        with patch.object(crew,'browser_observe',return_value={'tabs':[]}):
            with self.assertRaisesRegex(ValueError,'existing tab'):
                crew.browser_ego_action(row,{'port':9450,'url':'https://www.threads.com/other','goal':'close popup'})

    def test_threads_lane_advances_only_after_main_verified(self):
        import sqlite3
        from common import work_agenda as agendas
        with sqlite3.connect(self.data/'threads.sqlite3') as db:
            db.execute('CREATE TABLE parts(part_id TEXT,kind TEXT,state TEXT,account_key TEXT,publication_date TEXT,slot TEXT)')
            db.execute('INSERT INTO parts VALUES(?,?,?,?,?,?)',('attempt-0','main','submitted_unknown','mustpickinfo','2026-10-26','08:00'))
        args={'partId':'attempt-1','account':'mustpickinfo','date':'2026-10-26','slot':'08:00'}
        row={'kind':'conference','project':'threads','status':'blocked','source':{'arguments':args}}
        with patch.object(agendas,'DATA',self.data),patch.object(agendas,'running',return_value=False):
            self.assertFalse(agendas._should_auto_advance(row))
            self.assertFalse(agendas._should_auto_advance({**row,'blocker':'followup_delay_waiting'}))
            with sqlite3.connect(self.data/'threads.sqlite3') as db:
                db.execute("UPDATE parts SET state='published_verified'")
            self.assertTrue(agendas._should_auto_advance(row))
            self.assertTrue(agendas._should_auto_advance({**row,'source':{'arguments':{k:v for k,v in args.items() if k!='partId'}}}))
            with patch.object(agendas,'running',return_value=True):
                self.assertFalse(agendas._should_auto_advance(row))

    def test_unresolved_agenda_never_advances_on_time_or_reasoning_limits(self):
        from common import work_agenda as agendas
        for status in ('blocked', 'recovering', 'suspended'):
            row = dict(status=status, controllerFailures=3, updatedAt=0,
                       recoveryWatch={'checks': 10, 'continuationEpisodes': 2, 'state': 'needs_ceo_action'})
            with patch.object(agendas, 'running', return_value=[]):
                self.assertFalse(agendas._should_auto_advance(row))

    def test_monitor_goal_reconciles_only_its_original_missing_publications(self):
        from agents import crew_reasoning as crew
        from common import work_agenda as agendas
        quota = dict(status='observed', date='2026-10-26', due=4, missingSlots=['adinfo0905:12:20'])
        goal = dict(origin='project-monitor', permissions={'projects': ['naver_blog']},
                    baselineMetrics=[{'id': 'naver_blog', 'quota': quota}])
        goal_path = self.data / 'goal.json'
        goal_path.write_text(json.dumps(goal))
        proof = self.data / 'naver/public-verification.json'
        proof.parent.mkdir()
        proof.write_text('{}')
        row = dict(id=self.agenda, kind='goal', project='naver_blog', status='blocked',
                   controllerGoalId='b'*64, blocker='agenda_token_budget_exhausted', events={'opening': { 'id': 'opening' }})
        current = dict(id='naver_blog', source={'fresh': True}, quota={**quota, 'missingSlots': []})
        with patch.object(agendas, 'DATA', self.data), patch.object(agendas, 'running', return_value=[]), \
             patch.object(crew, 'claim', return_value=nullcontext(True)), \
             patch.object(crew, 'goal_path', return_value=goal_path), patch.object(crew, 'save'), \
             patch('server.project_health.observed_projects', return_value=[current]), \
             patch.object(agendas, 'verified') as verified:
            for changed in (current, {**current, 'source': {'fresh': False}},
                            {**current, 'quota': quota},
                            {**current, 'quota': {**current['quota'], 'date': '2026-10-27'}}):
                with patch('server.project_health.observed_projects', return_value=[changed]):
                    self.assertEqual(agendas.reconcile_monitor_goal(row), changed == current)
            verified.assert_called_once()
            self.assertTrue(verified.call_args.args[1]['monitorReconciled'])
            self.assertFalse(agendas._should_auto_advance(row))
            self.assertFalse(agendas.reconcile_monitor_goal({**row, 'workTarget': {'account': 'other'}}))

    def test_reconciled_monitor_reports_without_another_model_call(self):
        from common import work_agenda as agendas
        row = dict(id=self.agenda, kind='goal', status='report_pending', events={},
                   title='발행 누락 점검', verification={'verified': True, 'monitorReconciled': True,
                                                      'scope': 'adinfo0905:12:20 공개 게시 확인'})
        with patch.object(agendas, 'get', return_value=row), patch.object(agendas, 'running', return_value=[]), \
             patch.object(agendas, 'locked', return_value=nullcontext()), patch.object(agendas, '_save'), \
             patch.object(agendas, 'flush_events', return_value=False), patch.object(agendas, '_model_message') as model:
            self.assertFalse(agendas.finish_reports(self.agenda))
        model.assert_not_called()
        self.assertIn('staff_result', row['events'])
        self.assertIn('closing', row['events'])

    def test_failed_conference_goes_to_diagnosis_without_blind_replay(self):
        from common import work_agenda as agendas, conference_dispatch as conferences
        row = dict(businessAgendaId=self.agenda, agendaId='b'*64, status='failed', kind='threads',
                   arguments={}, errorType='RuntimeError', failureReason='threads_existing_draft_preserved')
        with patch.object(agendas, 'get', return_value={'id': self.agenda, 'kind': 'conference'}), \
             patch.object(agendas, 'hold') as hold, patch.object(conferences, 'write') as write:
            conferences.record_conference_result(row)
        hold.assert_called_once_with(self.agenda, 'threads_existing_draft_preserved', recovery=True)
        write.assert_not_called()

    def test_kin_selection_reason_is_kept_for_recovery(self):
        from common import work_agenda as agendas, conference_dispatch as conferences
        row = dict(businessAgendaId=self.agenda, status='completed',
                   eligibility={'runs': [{'reason': 'model_skipped_no_good_match'}]})
        with patch.object(agendas, 'get', return_value={'id': self.agenda}), patch.object(agendas, 'hold') as hold:
            conferences.record_conference_result(row)
        hold.assert_called_once_with(self.agenda, 'model_skipped_no_good_match', recovery=True)

    def test_closed_unverified_agenda_is_not_reported_as_success(self):
        from agents import crew_reasoning as crew
        from common import work_agenda as agendas
        row = dict(businessAgendaId=self.agenda)
        with patch.object(crew, 'ensure_business_agenda'), patch.object(crew, 'save'), \
             patch.object(agendas, 'enabled', return_value=True), \
             patch.object(agendas, 'get', return_value={'status': 'closed'}):
            crew.advance(row, 0)
        self.assertEqual(row['resolution']['status'], 'unresolved')
        self.assertEqual(row['status'], 'blocked')

    def test_failure_log_is_supplied_before_any_model_decision(self):
        from agents import crew_reasoning as crew
        from common import work_agenda as agendas
        failure = {'sha256': 'receipt-hash', 'data': {'logTail': 'RuntimeError: original failure'}}
        row = dict(businessAgendaId=self.agenda, permissions={'repair': True}, observations=[], status='ready')
        with patch.object(crew, 'refresh_pending', return_value=True), patch.object(crew, 'save'), \
             patch.object(agendas, 'get', return_value={'source': {'conferenceId': 'b'*64}}), \
             patch.object(crew, 'read_evidence', return_value=failure) as read, patch.object(crew, 'ask') as ask:
            crew._advance(row, 0)
            crew._advance(row, 0)
        self.assertEqual(row['observations'][0]['result']['data']['logTail'], 'RuntimeError: original failure')
        self.assertEqual(len(row['observations']), 1)
        ask.assert_not_called()
        self.assertEqual(read.call_count, 2)

    def test_recovery_prepares_existing_pipeline_before_manager_investigation(self):
        from common import work_agenda as agendas, repair_workflow as repair
        from agents import crew_reasoning as crew
        row = dict(id=self.agenda, kind='conference', status='recovering', project='threads',
                   title='Original draft', source={'conferenceId': 'b'*64}, blocker='RuntimeError')
        with patch.object(agendas, 'context', return_value=nullcontext()), patch.object(agendas, 'token', return_value={}), \
             patch.object(agendas, 'flush_events', return_value=True), patch.object(agendas, 'recovery_watch', return_value=False), \
             patch.object(agendas, 'get', return_value=row), patch.object(agendas, '_save'), \
             patch.object(agendas, 'locked', return_value=nullcontext()), \
             patch.object(repair, 'prepare_conference_recovery', return_value={'status': 'ready'}) as prepare, \
             patch.object(crew, 'reason_request', return_value={'id': 'c'*64}) as request:
            self.assertTrue(agendas._step_single_agenda(row))
        prepare.assert_called_once()
        self.assertTrue(request.call_args.kwargs['repair'])
        self.assertEqual(row['recoveryPreparation']['status'], 'ready')

    def test_channel_recovery_preserves_receipt_and_rejects_uncertain_submission(self):
        import sqlite3
        from contextlib import closing
        from common import conference_dispatch as conferences, repair_workflow as repair, work_agenda as agendas
        from server import project_health
        queue = self.data / 'publication-conferences'
        queue.mkdir()
        arguments = dict(account='mustpickinfo', date='2026-10-26', slot='08:00', partId='original')
        target = dict(kind='threads', arguments=arguments)
        identity = hashlib.sha256(json.dumps(['threads', arguments], sort_keys=True).encode()).hexdigest()
        original = dict(businessAgendaId=self.agenda, status='failed', kind='threads', arguments=arguments)
        source = queue / (identity + '.json')
        source.write_text(json.dumps(original))
        business = dict(id=self.agenda, project='threads')
        with closing(sqlite3.connect(self.data / 'threads.sqlite3', isolation_level=None)) as db:
            db.execute('CREATE TABLE parts(part_id,state,account_key,publication_date,slot)')
            db.execute('INSERT INTO parts VALUES (?,?,?,?,?)', ('original','queued','mustpickinfo','2026-10-26','08:00'))
        with patch.object(repair, 'ROOT', self.data / 'repair-workflows'), \
             patch.object(conferences, 'QUEUE', queue), patch.object(project_health, 'ROOT', self.root), \
             patch.object(agendas, 'require', return_value=business), patch.object(agendas, 'running', return_value=[]):
            result = repair._prepare_channel_recovery(business, target)
            _, row = repair._recovery_row(result['taskId'], result['planSha256'])
            self.assertEqual(json.loads(Path(row['plan']['failureReceiptPath']).read_text()), original)
            repair._recovery_resume_guard(row)
            with closing(sqlite3.connect(self.data / 'threads.sqlite3', isolation_level=None)) as db:
                db.execute("UPDATE parts SET state='submitted_unknown'")
            with self.assertRaisesRegex(ValueError, 'reconciliation'):
                repair._recovery_resume_guard(row)

    def test_channel_resume_requires_verified_publication_outcome(self):
        from common import repair_workflow as repair
        source = self.data / 'conference.json'
        row = {'businessAgendaId': self.agenda, 'planSha256': 'plan',
               'plan': {'action': {'tool': 'retry_conference'}, 'sourcePath': str(source)}, 'resumeResult': {}}
        for outcomes, expected in (([], 'resume_held'), ([{'publicationVerified': True}], 'work_verified')):
            source.write_text(json.dumps({'businessAgendaId': self.agenda, 'status': 'completed', 'outcomes': outcomes}))
            repair._observe_recovery_process(row)
            self.assertEqual(row['status'], expected)


    def test_discovery_reads_real_traceback_and_existing_regressions(self):
        from common import repair_workflow as repair, recovery_evidence, coding_job
        root = self.root
        source = root / 'threads_posting/posting.py'
        source.parent.mkdir()
        source.write_text("def publish():\n    raise RuntimeError('preserved_draft')\n")
        tests = root / 'dashboard/tests'
        tests.mkdir()
        (tests / 'test_existing.py').write_text('from threads_posting import posting\n')
        conference = self.data / 'publication-conferences' / ('b'*64 + '.json')
        conference.parent.mkdir()
        conference.write_text('{}')
        conference.with_suffix('.log').write_text('Traceback (most recent call last):\n  File "'+str(source)+'", line 2, in publish\nRuntimeError: preserved_draft\n')
        row = {'plan': {'projectRoot': str(root), 'project': 'threads', 'originalTaskId': 'conference:'+'b'*64,
                       'originalRequestPath': str(conference), 'sourceSnapshot': {}, 'failure': [],
                       'action': {'tool': 'retry_conference'}}}
        with patch.object(recovery_evidence, 'environment_evidence', return_value={}), \
             patch.object(repair, '_recovery_resume_guard', side_effect=ValueError('reconciliation')):
            found = repair._discover_recovery(row)
        self.assertIn('RuntimeError: preserved_draft', found['errors'])
        self.assertIn('threads_posting/posting.py', found['files'])
        self.assertEqual(found['testFiles'], ['dashboard/tests/test_existing.py'])
        self.assertFalse(found['originalRetryEligible'])


if __name__ == '__main__':
    unittest.main()
