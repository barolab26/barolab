import copy
import datetime as dt
import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from agents import crew_reasoning as crew
from common import llm_usage as usage
from common.collection_observability import load, write


class ReasoningEfficiencyTests(unittest.TestCase):
    def test_youtube_held_input_is_not_reported_as_missing_content_or_retried(self):
        from youtube_posting import posting
        path=self.data/'youtube-inputs.json'
        write(path,{'jobs':{'a'*64:{'status':'needs_attention','result':{'reason':'account_space_control_required'}}}})
        with patch.object(posting,'community_preparation_path',return_value=path), \
             patch.object(posting,'load_youtube_status',return_value={}), \
             patch('dashboard.common.ego_taskspace.native_publish_youtube_community_post') as publish:
            result=posting.publish_prepared_community()
        self.assertEqual(result['status'],'needs_attention')
        self.assertEqual(result['reason'],'account_space_control_required')
        self.assertEqual(result['owner'],'patch');publish.assert_not_called()

    def test_exact_terminal_clock_wait_releases_capacity_but_never_unknown_effect(self):
        from common import work_agenda as agendas
        import hashlib
        req='clock-wait';actions=[{'agent':'publi','tool':'run_project_cycle','args':{'project':'cf_blog'}}]
        row={'kind':'staff','status':'recovering','source':{'requestId':req,'actions':actions}}
        result={'status':'held','reason':'allocation_slot_not_currently_eligible','publicationVerified':False,
                'executorReceipt':{'requestId':req,'completed':True,'finishedAt':'2026-11-08T09:00:00+00:00'}}
        receipt={'requestId':req,'status':'failed','results':[{'tool':'run_project_cycle','result':result}]}
        path=self.data/'chats/staff-requests'/(hashlib.sha256(req.encode()).hexdigest()+'.json')
        with patch.object(agendas,'DATA',self.data),patch.object(agendas,'running',return_value=[]):
            write(path,receipt);self.assertFalse(agendas.occupies_lane(row))
            self.assertEqual(row['status'],'recovering');self.assertEqual(load(path),receipt)
            for change in ({'pendingEffect':True},{'status':'unknown'}):
                write(path,{**receipt,**change});self.assertTrue(agendas.occupies_lane(row))
            result['conferenceAgendaId']='uncertain-child';write(path,receipt)
            self.assertTrue(agendas.occupies_lane(row))

    def test_admission_explains_exact_blockers_and_does_not_release_them(self):
        from common import work_agenda as agendas
        blocker={'id':'a'*64,'kind':'staff','project':'naver_blog','status':'executing','source':{}}
        chosen={'id':'b'*64,'kind':'staff','project':'naver_blog','status':'queued','source':{}}
        with patch.object(agendas,'active_ids',return_value=[]),patch.object(agendas,'active_rows',return_value=[blocker]), \
             patch.object(agendas,'occupies_lane',return_value=True):
            state=agendas.admission_state(chosen,{})
        self.assertFalse(state['eligible']);self.assertEqual(state['reason'],'lane_capacity')
        self.assertEqual(state['blockers'][0]['agendaId'],blocker['id']);self.assertEqual(blocker['status'],'executing')

    def test_duplicate_scheduler_envelopes_count_exact_native_child_once_without_reopening_hold(self):
        from common import work_agenda as agendas
        import hashlib
        args={'action':'cf-prepare','account':'daynote.kr','date':'2026-11-08','slot':'18:40'}
        child=hashlib.sha256(json.dumps(['parameters',args],sort_keys=True).encode()).hexdigest();owner='c'*64
        native={'agendaId':child,'kind':'parameters','arguments':args,'requestedAt':123,
                'businessAgendaId':owner,'status':'unknown','pendingEffect':True}
        blockers=[]
        for index in range(2):
            request='same-child-'+str(index)
            blockers.append({'id':str(index)*64,'kind':'staff','project':'cf_blog','status':'recovering',
                'source':{'requestId':request,'actions':[{'tool':'run_project_cycle','args':{'project':'cf_blog'}}]}})
            write(self.data/'chats/staff-requests'/(hashlib.sha256(request.encode()).hexdigest()+'.json'),{
                'requestId':request,'status':'failed','results':[{'tool':'run_project_cycle','result':{
                    'conferenceAgendaId':child,'conferenceRequestedAt':123,'executorReceipt':{
                        'requestId':request,'completed':True,'finishedAt':'observed'}}}]})
        rows=self.data/'publication-conferences/operations';write(rows.parent/(child+'.json'),native)
        chosen={'id':'d'*64,'kind':'staff','project':'cf_blog','status':'queued','source':{
            'actions':[{'tool':'run_project_cycle','args':{'project':'cf_blog'}}]}}
        with patch.object(agendas,'DATA',self.data),patch.object(agendas,'ROWS',rows), \
             patch.object(agendas,'active_ids',return_value=[]),patch.object(agendas,'active_rows',return_value=blockers), \
             patch.object(agendas,'running',return_value=[]),patch.object(agendas,'occupies_lane',return_value=True), \
             patch.object(agendas,'get',return_value={'kind':'conference','source':{'conferenceId':child}}):
            result=agendas.admission_state(chosen,{})
            self.assertEqual(result['occupiedResources'],1);self.assertEqual(len(result['blockers']),2)
            native['requestedAt']=124;write(rows.parent/(child+'.json'),native)
            self.assertEqual(agendas.admission_state(chosen,{})['occupiedResources'],2)
        self.assertEqual(load(rows.parent/(child+'.json'))['status'],'unknown')
        self.assertTrue(load(rows.parent/(child+'.json'))['pendingEffect'])

    def test_tool_failure_keeps_redacted_message_and_source_identity(self):
        from common.collection_observability import failure_details
        try:raise ValueError('missing source; token=private-value https://example.com/a?key=private-query')
        except ValueError as exc:result=failure_details(exc)
        self.assertIn('missing source',result['errorMessage'])
        self.assertNotIn('private-value',str(result));self.assertNotIn('private-query',str(result))
        self.assertTrue(result['sourceLocation']);self.assertEqual(len(result['failureFingerprint']),64)

    def test_executor_failure_detail_reaches_staff_result_without_claiming_retry_permission(self):
        from common import ego_executor as executor,work_agenda as agendas
        from contextlib import nullcontext
        action={'agent':'publi','tool':'prepare_brunch_content','args':{'project':'brunch','part_no':13}}
        with patch.object(agendas,'enabled',return_value=False), \
             patch('server.agent_tools.execute_agent_tool',side_effect=ValueError('missing vaccine primary source')), \
             patch('common.ego_telemetry.execution_context',return_value=nullcontext()):
            result=executor.execute_staff_action(action,task_id='staff:exact',request_id='exact')
        self.assertEqual(result['status'],'failed')
        self.assertIn('missing vaccine primary source',result['errorMessage'])
        self.assertTrue(result['executorReceipt']['completed'])
        self.assertIn('no blind retry',result['nextAction'])

    def test_finished_preparation_feedback_releases_capacity_without_closing_held_work(self):
        from common import work_agenda as agendas
        import hashlib
        request='finished-preparation';row={'kind':'staff','status':'recovering','controllerGoalId':'b'*64,
            'source':{'requestId':request,'actions':[{'tool':'prepare_brunch_content','args':{'project':'brunch','part_no':13}}]}}
        path=self.data/'chats/staff-requests'/(hashlib.sha256(request.encode()).hexdigest()+'.json')
        receipt={'requestId':request,'status':'failed','results':[{'result':{'status':'needs_attention','publicationVerified':False}}]}
        write(path,receipt)
        with patch.object(agendas,'DATA',self.data),patch.object(agendas,'running',return_value=[]):
            self.assertFalse(agendas.occupies_lane(row))
            self.assertEqual(row['status'],'recovering');self.assertEqual(load(path),receipt)
            write(path,{**receipt,'pendingEffect':True})
            self.assertTrue(agendas.occupies_lane(row))

    def test_instruction_failure_cannot_leave_a_phantom_staff_agenda(self):
        from server import agent_tools as tools
        action={'agent':'publi','tool':'prepare_brunch_content','args':{'project':'brunch','part_no':13}}
        with patch.object(tools,'staff_instruction',side_effect=KeyError('domain')), \
             patch('common.work_agenda.staff_agenda') as agenda:
            with self.assertRaises(KeyError):tools.enqueue_staff_request('instruction-before-admission',[action])
            agenda.assert_not_called()

    def test_preparation_does_not_occupy_or_replay_uncertain_publication_lane(self):
        from common import work_agenda as agendas
        uncertain={'kind':'conference','status':'recovering','source':{'arguments':{'account':'brunch'}}}
        prepare={'kind':'staff','source':{'actions':[{'tool':'prepare_brunch_content','args':{'project':'brunch','part_no':13}}]}}
        self.assertEqual(agendas.execution_lane(prepare),'preparation')
        with patch.object(agendas,'running',return_value=[{'pid':123}]):
            self.assertFalse(agendas.shares_execution_lane(uncertain,prepare))
        self.assertEqual(uncertain['status'],'recovering')

    def test_manager_lane_never_loads_old_managers_or_starts_unrelated_work_while_current_waits(self):
        from common import operating_plan as operating,work_agenda as agendas
        current='a'*64;old='b'*64
        write(self.data/'operating-plan.json',{'manager':{'goalId':current}})
        pending=crew.GOALS/'pending';pending.mkdir(parents=True,exist_ok=True)
        for key in (current,old):(pending/key).touch()
        write(crew.goal_path(current),{'id':current,'origin':'company-manager','status':'ready','nextCheckAt':time.time()+3600})
        crew.goal_path(old).write_text('Old huge history must not be read',encoding='utf-8')
        with patch.object(operating,'STATE',self.data/'operating-plan.json'),patch.object(agendas,'enabled',return_value=False), \
             patch.object(crew,'load',wraps=load) as reads,patch.object(crew,'advance') as advance, \
             patch.object(crew,'evaluate_case_once') as evaluate,patch.object(crew,'start_autonomous_goal_once') as start:
            self.assertFalse(crew.resume_once('manager'))
            self.assertNotIn(crew.goal_path(old),[call.args[0] for call in reads.call_args_list])
            advance.assert_not_called();evaluate.assert_not_called();start.assert_not_called()

    def test_typed_admission_does_not_run_recovery_models_or_auxiliary_work(self):
        from common import work_agenda as agendas
        rows={'ready':{'id':'ready','kind':'conference','status':'queued','notBefore':0},
              'future':{'id':'future','kind':'staff','status':'queued','notBefore':time.time()+3600},
              'discussion':{'id':'discussion','kind':'goal','status':'queued','notBefore':0}}
        with patch.object(agendas,'ROWS',self.data/'operations'),patch.object(agendas,'enabled',return_value=True), \
             patch.object(agendas,'load',return_value={'pending':list(rows)}), \
             patch.object(agendas,'get',side_effect=lambda key:rows[key]), \
             patch.object(agendas,'admit',return_value={'id':'ready'}) as admit, \
             patch.object(agendas,'active_rows',return_value=[{**rows['ready'],'status':'meeting'}]), \
             patch.object(agendas,'prepare_open',return_value=True) as opening, \
             patch.object(agendas,'_model_message',side_effect=AssertionError('admission called model')):
            self.assertTrue(agendas.admit_ready_once())
            admit.assert_called_once_with('ready');opening.assert_called_once_with('ready')

    def test_general_writing_honors_staff_brain_and_only_bound_experiment_overrides_it(self):
        import inspect
        from common import llm_client as client
        generate=inspect.unwrap(client.generate_json)
        schema={'type':'object','properties':{'intro':{},'sections':{}}}
        config={'active':'agy','providers':{'codex':{'model':'base'},'agy':{'model':'legacy'}}}
        with patch.object(client.settings,'load',return_value=config), \
             patch.object(client.settings,'get_agent_brain',return_value={'provider':'codex','model':'configured-writer'}), \
             patch.object(client.settings,'reasoning_effort_for_call',return_value='high'), \
             patch('common.naver_ab.reserve_call',return_value=None) as experiment, \
             patch.object(client,'_generate_json',return_value=({'intro':'answer','sections':[]},'actual-writer')) as model, \
             patch.object(client,'persist_writer_meta'),patch('common.crew_chat_bridge.record_model_route'):
            generate('reader draft',agent_slot='publi',response_schema=schema)
            self.assertEqual((model.call_args.args[1],model.call_args.args[3]),('codex','configured-writer'))
            experiment.return_value={'provider':'agy','model':'bound-experiment','arm':'A'}
            generate('reader draft',agent_slot='publi',response_schema=schema)
            self.assertEqual((model.call_args.args[1],model.call_args.args[3]),('agy','bound-experiment'))

    def test_preparation_and_verification_instructions_do_not_require_domain(self):
        from server.agent_tools import staff_instruction
        for tool in ('prepare_cafe_content','prepare_youtube_content','prepare_brunch_content','verify_youtube_content','verify_cf_corrected_publication'):
            instruction=staff_instruction({'agent':'publi','tool':tool,'args':{'project':'naver_cafe'}})
            self.assertEqual(instruction['tool'],tool)
            self.assertLessEqual(len(instruction['text']),160)

    def test_parked_domain_failure_does_not_own_other_staff_domain(self):
        from common import work_agenda as agendas
        existing={'kind':'staff','source':{'actions':[{'tool':'repair_cf_normalization','args':{'domain':'topnote.kr'}}]}}
        chosen={'kind':'staff','source':{'actions':[{'tool':'repair_cf_normalization','args':{'domain':'joynote.kr'}}]}}
        with patch.object(agendas,'running',return_value=False):
            self.assertFalse(agendas.shares_execution_lane(existing,chosen))
            chosen['source']['actions'][0]['args']['domain']='topnote.kr'
            self.assertTrue(agendas.shares_execution_lane(existing,chosen))
            chosen['source']['actions'][0]['args']={}
            self.assertTrue(agendas.shares_execution_lane(existing,chosen))
        with patch.object(agendas,'running',return_value=[{'pid':123}]):
            self.assertTrue(agendas.shares_execution_lane(existing,chosen))

    def test_board_wait_preserves_novel_drilldowns_and_resets_after_execution(self):
        self.row['decisionBoardFingerprint']='board'
        with patch('common.operating_plan.execution_board',return_value={'fingerprint':'board'}), \
             patch.object(crew,'reasoning_source_state',return_value='volatile'), \
             patch.object(crew,'next_eligible_time',return_value=None):
            for index in range(5):
                crew.repeated_investigation(self.row,'evidence',{'name':'revenue'},{'data':{'newFact':index}})
            self.assertNotIn('inferenceWatch',self.row)
            for index in range(3):
                crew.repeated_investigation(self.row,'evidence',{'name':'revenue'},{'data':{'newFact':4},'observedAt':index})
            self.assertIn('decisionRequired',self.row)
            self.assertNotIn('inferenceWatch',self.row)
            self.assertFalse(crew.reasoning_waiting_for_change(self.row))
            crew.record_decision_hold(self.row,reason='Waiting for external source update')
            self.assertTrue(self.row['inferenceWatch']['board'])
            self.assertTrue(self.row['inferenceWatch']['holdRecorded'])
            crew.repeated_investigation(self.row,'dispatch',{})
            self.assertNotIn('inferenceWatch',self.row)
            self.assertEqual(self.row['boardUnchangedReads'],0)

    def test_dashboard_collector_start_is_idempotent(self):
        from server.mission_control import Collector
        import threading
        stopped=threading.Event()
        with patch('server.cockpit_telemetry.RemoteTelemetry') as remote:
            collector=Collector(root=self.root)
            with patch.object(collector,'run',side_effect=lambda:stopped.wait(2)):
                collector.start()
                first=collector.thread
                try:
                    collector.start()
                    self.assertIs(collector.thread,first)
                    remote.return_value.start.assert_called_once()
                finally:
                    stopped.set();first.join(2)

    def test_alternating_unchanged_sources_does_not_evade_idle_model_wait(self):
        with patch.object(crew,'reasoning_source_state',return_value='same-material-source'), \
             patch.object(crew,'next_eligible_time',return_value=None):
            for _ in range(4):
                crew.repeated_investigation(self.row,'evidence',{'name':'revenue'})
                crew.repeated_investigation(self.row,'projects',{})
            self.assertIn('inferenceWatch',self.row)
            crew.repeated_investigation(self.row,'dispatch',{'tool':'run_project_cycle'})
            self.assertNotIn('inferenceWatch',self.row)
            self.assertNotIn('investigationRepeatCounts',self.row)

    def test_unstarted_budget_hold_releases_capacity_without_resuming_or_closing_work(self):
        from common import work_agenda as agendas
        import hashlib
        request_id='held-staff-request'
        row={'id':'b'*64,'kind':'staff','status':'meeting','source':{'requestId':request_id}}
        receipt={'requestId':request_id,'status':'held','reasonCode':'budget_exhausted','results':[],'requests':[]}
        path=self.data/'chats/staff-requests'/(hashlib.sha256(request_id.encode()).hexdigest()+'.json')
        with patch.object(agendas,'DATA',self.data),patch.object(agendas,'running',return_value=False):
            write(path,receipt)
            self.assertFalse(agendas.occupies_lane(row))
            self.assertEqual(row['status'],'meeting')
            self.assertEqual(load(path),receipt)
            write(path,{**receipt,'pendingEffect':True})
            self.assertTrue(agendas.occupies_lane(row))
            write(path,{**receipt,'requests':[{'state':'unknown'}]})
            self.assertTrue(agendas.occupies_lane(row))
            write(path,{**receipt,'reasonCode':'manual_stop'})
            self.assertTrue(agendas.occupies_lane(row))

    def test_owned_staff_completion_uses_actual_receipt_directory(self):
        from common import work_agenda as agendas
        import hashlib
        request_id='known-completion'
        path=self.data/'chats/staff-requests'/(hashlib.sha256(request_id.encode()).hexdigest()+'.json')
        goal={'pendingAction':{'requestId':request_id}}
        with patch.object(agendas,'DATA',self.data):
            self.assertTrue(agendas._pending_owned_work(goal))
            write(path,{'requestId':request_id,'status':'completed'})
            self.assertFalse(agendas._pending_owned_work(goal))
            write(path,{'requestId':request_id,'status':'completed','pendingEffect':True})
            self.assertTrue(agendas._pending_owned_work(goal))

    def test_old_large_evidence_roundtrips_without_loading_it_into_goal(self):
        from common.observation_archive import ArchivedResult, materialize, source_values
        import hashlib
        original={'source':'dashboard/data/metrics.json','sha256':'source-sha','projects':[{'text':'facts '*6000}]}
        event=self.event(0,original)
        event['tool']='projects'
        event['sha256']=hashlib.sha256(json.dumps(event,sort_keys=True).encode()).hexdigest()
        expected=copy.deepcopy(event)
        self.row['observations']=[event]+[self.event(n,{'ok':True}) for n in range(1,14)]
        crew.save(self.row)
        disk=crew.goal_path(self.row['id'])
        self.assertLess(disk.stat().st_size,12000)
        restored=load(disk)
        result=restored['observations'][0]['result']
        # Tests use a custom goals folder; production hydration is path-scoped.
        from common.observation_archive import hydrate
        hydrate(restored,crew.GOALS/'observation-results')
        result=restored['observations'][0]['result']
        self.assertIsInstance(result,ArchivedResult)
        with patch.object(ArchivedResult,'read',side_effect=AssertionError('eager source read')):
            self.assertEqual(result.get('sha256'),'source-sha')
            self.assertEqual(list(source_values(result)),[{'source':'dashboard/data/metrics.json'}])
            self.assertLess(len(json.dumps(restored)),12000)
        self.assertEqual(materialize(result),original)
        restored['observations'][0]['result']=materialize(result)
        self.assertEqual(restored['observations'][0],expected)
        response=crew.tool_call(self.row,'evidence',{'name':'observation:e0','select':['projects'],'limit':1})
        self.assertEqual(response['sha256'],event['sha256'])
        self.assertEqual(response['data'][0]['readWith']['select'],['projects',0])
        self.assertTrue(response['data'][0]['detailRequired'])

    def test_archives_reject_corruption_and_execution_receipts_stay_inline(self):
        from common.observation_archive import ArchivedResult, materialize
        self.row['observations']=[self.event(0,{'payload':'x'*15000}),
            {**self.event(1,{'receipt':'x'*15000}),'tool':'execution_result'}]+[self.event(n,{'ok':True}) for n in range(2,15)]
        crew.save(self.row)
        self.assertNotIsInstance(self.row['observations'][1]['result'],ArchivedResult)
        result=self.row['observations'][0]['result']
        path=next((crew.GOALS/'observation-results').glob('*.json'))
        path.write_text('{"payload":"changed"}')
        with self.assertRaisesRegex(ValueError,'hash mismatch'):materialize(result)

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.data = self.root/'dashboard/data'
        self.data.mkdir(parents=True)
        for target, name, value in [(crew, 'ROOT', self.root), (crew, 'GOALS', self.data/'goals')]:
            p = patch.object(target, name, value)
            p.start(); self.addCleanup(p.stop)
        self.row = {'id':'a'*64, 'actor':'jarvis', 'origin':'company-manager', 'goal':'Grow revenue',
                    'status':'ready', 'permissions':{'projects':['naver_blog'],'execute':True,'repair':False},
                    'decisions':10, 'observations':[], 'timings':{}}

    def test_strategy_and_dispatch_share_permissioned_preparation_and_verification_tools(self):
        execute={'execute':True,'repair':False}
        repair={'execute':False,'repair':True}
        for strategy in (False,True):
            self.assertIn('prepare_youtube_content',crew.dispatch_tools(execute,strategy=strategy))
            self.assertIn('prepare_cafe_content',crew.dispatch_tools(execute,strategy=strategy))
            self.assertNotIn('verify_youtube_content',crew.dispatch_tools(execute,strategy=strategy))
            self.assertIn('verify_youtube_content',crew.dispatch_tools(repair,strategy=strategy))
            self.assertIn('repair_cf_normalization',crew.dispatch_tools(repair,strategy=strategy))
            self.assertNotIn('prepare_cafe_content',crew.dispatch_tools(repair,strategy=strategy))
        self.assertEqual(crew.dispatch_tools({}),{'read_agent_status'})
        self.assertTrue(crew.strategy_result_verified('prepare_youtube_content',{'ok':True,'status':'prepared','publicationVerified':False}))
        self.assertFalse(crew.strategy_result_verified('run_project_cycle',{'ok':True,'status':'prepared'}))
        self.assertFalse(crew.strategy_result_verified('verify_youtube_content',{'ok':True,'status':'unknown'}))
        self.assertTrue(crew.strategy_result_verified('verify_youtube_content',{'ok':True,'publicationVerified':True}))
        self.assertTrue(crew.strategy_result_verified('repair_cf_normalization',{'status':'prepared','owner':'normal-cf-scheduler','revision':'bound-revision','publicationVerified':False}))
        self.assertFalse(crew.strategy_result_verified('repair_cf_normalization',{'status':'prepared'}))

    def event(self, number, result):
        return {'id':'e'+str(number),'actor':'jarvis','tool':'evidence',
                'arguments':{'name':'revenue'},'observedAt':number,'sha256':str(number),'result':result}

    def test_hira_public_criteria_notices_are_primary_without_approving_private_or_spoofed_surfaces(self):
        from common.content_improvement import primary_url
        url='https://www.hira.or.kr/rc/insu/insuadtcrtr/InsuAdtCrtrPopup.do?mtgHmeDd=20250201&mtgMtrRegSno=0003&sno=5'
        self.assertTrue(primary_url(url))
        for bad in (url.replace('www.hira.or.kr','www.hira.or.kr.fake.example'),url.replace('https:','http:'),url+'&mode=write',url+'&sno=6',url.replace('20250201',''),url.replace('InsuAdtCrtrPopup.do','privateClaim.do')):
            self.assertFalse(primary_url(bad),bad)

    def test_cafe_settlement_requires_exact_verified_payload_and_preserves_newer_assignment(self):
        from naver_cafe_posting import posting as cafe
        from naver_cafe_posting.editorial import digest
        folder=self.root/'prepared';document={'title':'Reviewed question'};sha=digest(document)
        write(folder/'document.json',document)
        write(folder/'prepared.json',{'cafeId':'boutiqueinfo','documentSha256':sha})
        write(folder/'intent.json',{'status':'verified_published','url':'https://cafe.naver.com/ArticleRead.nhn?clubid=31608088&articleid=2480','documentSha256':sha})
        write(folder/'public-evidence.json',{'status':'verified_published','url':'https://cafe.naver.com/ArticleRead.nhn?clubid=31608088&articleid=2480','documentSha256':sha})
        index=self.root/'dashboard/data/cafe/preparation-jobs.json'
        write(index,{'jobs':{'boutiqueinfo:21':{'status':'prepared','prepared':{'documentSha256':sha}}}})
        with patch.object(cafe,'ROOT_DIR',self.root),patch.object(cafe,'load_cafe_status',return_value={'approvedPreparedPart':22}),patch.object(cafe,'save_cafe_status') as save:
            result=cafe.settle_cafe_preparation('boutiqueinfo',21,folder)
            self.assertTrue(result['publicationVerified']);self.assertFalse(result['submissionDispatched']);save.assert_not_called()
            self.assertEqual(load(index)['jobs']['boutiqueinfo:21']['status'],'published_verified')
            write(folder/'document.json',{'title':'Different payload'})
            self.assertIsNone(cafe.settle_cafe_preparation('boutiqueinfo',21,folder))

    def test_large_protected_history_is_small_and_original_retrievable(self):
        result = {'data':{'articles':[{'body':'x'*50000} for _ in range(10)],'revenue':None},
                  'pagination':{'truncated':False},'sha256':'actual-source'}
        self.row['observations']=[self.event(i,result) for i in range(300)]
        original = copy.deepcopy(self.row['observations'])
        context = crew.prompt_observations(self.row)
        self.assertLessEqual(len(json.dumps(context,ensure_ascii=False)),16000)
        self.assertLess(len(context),300)
        self.assertEqual(self.row['observations'],original)
        detail = crew.tool_call(self.row,'evidence',{'name':'observation:e299','select':['data','articles',0,'body']})
        self.assertEqual(detail['data']['totalCharacters'],50000)
        self.assertEqual(detail['data']['text'],'x'*16000)
        self.assertEqual(detail['observedAt'],299)
        with self.assertRaisesRegex(ValueError,'Unknown observation'):
            crew.tool_call(self.row,'evidence',{'name':'observation:e999'})

    def test_small_missingness_and_pagination_stay_structured(self):
        result={'data':{'revenue':None,'complete':False},'pagination':{'truncated':True,'nextOffset':80}}
        self.row['observations']=[self.event(1,result)]
        observed=crew.prompt_observations(self.row)[0]['result']
        self.assertIsNone(observed['data']['revenue'])
        self.assertFalse(observed['data']['complete'])
        self.assertEqual(observed['pagination']['nextOffset'],80)

    def test_same_goal_archive_supports_batch_and_selection(self):
        self.row['observations']=[self.event(1,{'account':'A','count':4})]
        result=crew.tool_call(self.row,'evidence_batch',{'names':['observation:e1']})
        self.assertEqual(result['observation:e1']['data']['account'],'A')
        with self.assertRaises(ValueError):
            crew.tool_call(self.row,'evidence',{'name':'observation:e1','select':['api_key']})

    def test_clock_only_changes_do_not_wake_but_real_change_does(self):
        path=self.data/'naver/automation-status.json'
        write(path,{'checkedAt':1,'accounts':{'A':{'status':'held'}}})
        signature=crew.reasoning_source_state(self.row)
        self.row['inferenceWatch']={'signature':signature,'reviewAt':time.time()+60}
        write(path,{'checkedAt':2,'accounts':{'A':{'status':'held'}}})
        with patch.object(crew,'save'):
            self.assertTrue(crew.reasoning_waiting_for_change(self.row))
            write(path,{'checkedAt':3,'accounts':{'A':{'status':'completed'}}})
            self.assertFalse(crew.reasoning_waiting_for_change(self.row))
        self.assertNotIn('inferenceWatch',self.row)

    def test_agenda_observer_bookkeeping_does_not_count_as_business_progress(self):
        path=self.data/'publication-conferences/operations'/('b'*64+'.json')
        document={'id':'b'*64,'status':'blocked','observationCount':1,'latestObservationSha256':'old',
            'priorityAssessment':{'checkedAt':1,'source':{'sha256':'old'}},'workTarget':{'account':'A'}}
        write(path,document);before=crew.reasoning_source_state(self.row)
        write(path,{**document,'observationCount':100,'latestObservationSha256':'new',
            'priorityAssessment':{'checkedAt':2,'source':{'sha256':'new'}}})
        self.assertEqual(crew.reasoning_source_state(self.row),before)
        write(path,{**document,'status':'completed'})
        self.assertNotEqual(crew.reasoning_source_state(self.row),before)

    def test_repeat_detector_observes_change_and_execution_stays_runnable(self):
        path=self.data/'naver/automation-status.json';write(path,{'status':'held'})
        for _ in range(4):crew.repeated_investigation(self.row,'evidence',{'name':'naver_schedule'})
        self.assertIn('inferenceWatch',self.row)
        write(path,{'status':'ready'})
        with patch.object(crew,'save'):
            self.assertFalse(crew.reasoning_waiting_for_change(self.row))
        crew.repeated_investigation(self.row,'dispatch',{'agent':'publi'})
        self.assertNotIn('inferenceWatch',self.row)
        self.assertEqual(self.row['unchangedInvestigations'],0)

    def test_watching_skips_inference_not_worker_or_goal_completion(self):
        self.row['inferenceWatch']={'signature':crew.reasoning_source_state(self.row),'reviewAt':time.time()+60}
        with patch('common.operating_plan.enabled',return_value=True), patch.object(crew,'refresh_operating_actions'), \
             patch.object(crew,'refresh_pending',return_value=True),patch.object(crew,'save'),patch.object(crew,'ask') as ask:
            crew._advance(self.row,1)
        ask.assert_not_called()
        self.assertEqual(self.row['status'],'ready')
        self.assertEqual(self.row['decisions'],10)
        self.assertNotIn('answer',self.row)
        self.row['inferenceWatch']['reviewAt']=time.time()-1
        self.assertFalse(crew.reasoning_waiting_for_change(self.row))

    def test_source_deletion_wakes_and_unknown_source_never_suppresses(self):
        path=self.data/'revenue.json';write(path,{'value':None})
        self.row['inferenceWatch']={'signature':crew.reasoning_source_state(self.row),'reviewAt':time.time()+60}
        path.unlink()
        self.assertFalse(crew.reasoning_waiting_for_change(self.row))
        path.write_text('invalid json')
        self.assertIsNone(crew.reasoning_source_state(self.row))

    def test_usage_separates_cache_from_unknown_and_retains_owner(self):
        def report(raw):
            call={'inputTokens':0,'outputTokens':0,'usageReports':0,'rateLimitHeaders':{}}
            token=usage._CURRENT.set(call)
            try:usage.report_response(events=[{'type':'turn.completed','usage':raw}])
            finally:usage._CURRENT.reset(token)
            return call
        known=report({'input_tokens':100,'cached_input_tokens':80,'output_tokens':3})
        self.assertEqual(known['uncachedInputTokens'],20)
        unknown=report({'input_tokens':100,'output_tokens':3})
        self.assertNotIn('uncachedInputTokens',unknown)
        now=dt.datetime.now(usage.KST)
        call={**known,'id':'test','provider':'codex','model':'test','agentSlot':'jarvis','goalId':'a'*64,
              'startedAt':now.isoformat(),'latencyMs':1,'promptCharacters':42}
        usage.record_call(call,'completed',root=self.root,now=now)
        recent=load(self.data/'llm_usage_ledger.json')['recent'][-1]
        self.assertEqual(recent['agentSlot'],'jarvis')
        self.assertEqual(recent['cachedInputTokens'],80)
        self.assertEqual(recent['goalId'],'a'*64)

    def test_usage_inherits_goal_after_outer_wrapper_consumes_task_metadata(self):
        from common.llm_client import memory_session
        @usage.metered
        def provider(prompt,**kwargs):return {'ok':True}
        with patch.object(usage,'record_call') as record,patch.object(usage,'_safe_record') as finish:
            with memory_session('crew-goal:'+'a'*64,'jarvis'):
                provider('compact prompt',provider='codex',model='test',agent_slot='jarvis')
        self.assertEqual(finish.call_args.args[0]['goalId'],'a'*64)
        self.assertEqual(finish.call_args.args[0]['promptCharacters'],14)

    def test_factual_review_sends_source_body_once_and_keeps_exact_quote_binding(self):
        from common import content_quality as quality
        marker='OBSERVED_SOURCE_SENTENCE_'
        claim='보험 지급 한도는 100만원입니다.'
        text=claim+marker*200
        folder=self.root/'claim';folder.mkdir()
        write(folder/'research.json',{'collectedAt':dt.datetime.now(dt.timezone.utc).isoformat(),
            'sources':[{'url':'https://www.gov.kr/policy','text':text}]})
        captured=[]
        def model(prompt,**kwargs):
            captured.append(prompt)
            raise RuntimeError('capture only, no model call')
        with self.assertRaisesRegex(RuntimeError,'capture only'):
            quality.ensure_publication_review({'title':'보험 지급 조건','contentHtml':claim},folder,generate=model)
        self.assertEqual(captured[0].count(marker),200)
        catalog=quality.source_quote_catalog([{'text':text}])
        identity=next(iter(catalog))
        resolved,_=quality.resolve_source_quotes({'claimSources':[{'sourceId':'0','quote':identity}]},catalog)
        self.assertEqual(resolved['claimSources'][0]['quote'],text)

    def test_review_timestamp_changes_cannot_replay_the_same_rejected_edits(self):
        from common import editorial_recovery as recovery
        folder=self.root/'naver_blog_posting/output/recovery';folder.mkdir(parents=True)
        document={'title':'Original title','blocks':[{'type':'text','text':'Original body'}]}
        write(folder/'research.json',{'sources':[]})
        counter=[]
        def check(d):
            counter.append(1)
            write(folder/'claim-review-response.json',{'status':'changes_required','checkedAt':len(counter)})
            raise ValueError('Draft held: essential answer missing')
        from unittest.mock import Mock
        proposal={'sourceQueries':[],'edits':[{'path':'title','value':'Wrong identity'}],'reason':'bad proposal'}
        model=Mock(side_effect=[proposal,proposal,AssertionError('Identical rejection must not call a third model')])
        with patch.object(recovery,'ROOT',self.root),patch('common.operating_plan.enabled',return_value=True):
            for _ in range(2):
                with self.assertRaisesRegex(ValueError,'no new evidence'):
                    recovery.review_and_repair(document,folder,[check],generate=model)
        self.assertEqual(model.call_count,2)
        self.assertEqual(document['title'],'Original title')
        self.assertEqual(load(folder/'editorial-recovery.json')['status'],'needs_new_evidence')

    def test_restarted_editor_keeps_candidate_but_rechecks_before_acceptance(self):
        from common import editorial_recovery as recovery
        from unittest.mock import Mock
        folder=self.root/'naver_blog_posting/output/resume';folder.mkdir(parents=True)
        original={'title':'Same assignment','contentHtml':'<p>Original text</p>'}
        candidate={**original,'contentHtml':'<p>Repaired text from observed source</p>'}
        write(folder/'editorial-current-document.json',{'originalSha256':recovery.digest(original),
            'documentSha256':recovery.digest(candidate),'document':candidate,'status':'candidate_not_approved'})
        check=Mock(return_value={'status':'passed'});model=Mock()
        with patch.object(recovery,'ROOT',self.root):
            recovery.review_and_repair(original,folder,[check],generate=model)
        check.assert_called_once_with(candidate)
        model.assert_not_called()
        self.assertEqual(original,candidate)

    def test_missing_claim_feedback_identifies_the_actual_unmapped_occurrence(self):
        from common import content_quality as quality
        from unittest.mock import Mock
        folder=self.root/'claim-feedback';folder.mkdir()
        claim='보험 지급 한도는 100만원입니다.'
        write(folder/'research.json',{'collectedAt':dt.datetime.now(dt.timezone.utc).isoformat(),
            'sources':[{'url':'https://www.gov.kr/policy','text':claim}]})
        response={'status':'passed','issues':[],'claimsComplete':True,'experienceHonest':True,
            'highRiskClaims':[],'experienceClaims':[],'hypotheticalClaims':[],'claimSources':[]}
        with self.assertRaises(ValueError) as failure:
            quality.ensure_publication_review({'title':'보험 안내','contentHtml':claim},folder,generate=Mock(return_value=response))
        self.assertIn('unmappedText',str(failure.exception))
        self.assertIn('100',str(failure.exception))
        self.assertIn('context',str(failure.exception))

    def test_uncertain_brunch_work_retains_ownership_without_blocking_other_work(self):
        from brunch_posting import posting as brunch
        folder=self.root/'prepared'
        path=folder/'part-11/publication-intent.json'
        write(path,{'state':'unknown','part':11,'title':'Original uncertain article'})
        before=path.read_bytes()
        self.assertEqual(brunch.next_unowned_brunch_part(set(range(1,11)),folder),12)
        self.assertEqual(path.read_bytes(),before)
        write(folder/'part-12/publication-intent.json',{'state':'published','receipt':{'url':'original'}})
        self.assertEqual(brunch.next_unowned_brunch_part(set(range(1,11)),folder),13)
        write(folder/'part-13/publication-intent.json',{'state':'staged_verified'})
        self.assertEqual(brunch.next_unowned_brunch_part(set(range(1,11)),folder),13)

    def test_new_brunch_work_does_not_reuse_a_source_owned_by_uncertain_submission(self):
        from brunch_posting import posting as brunch
        from unittest.mock import Mock
        script=self.root/'brunch_posting/posting.py'
        folder=script.parent/'output/prepared/part-11'
        write(folder/'publication-intent.json',{'state':'unknown'})
        write(folder/'article.json',{'bridgeUrl':'https://must-good.com/existing-reader-task'})
        model=Mock()
        with patch.object(brunch,'__file__',str(script)),patch.object(brunch,'get_today_cf_bridge_targets',
                return_value=[{'url':'https://must-good.com/existing-reader-task','domain':'must-good.com','title':'Same reader task'}]), \
             patch('common.llm_client.generate_json',model):
            with self.assertRaisesRegex(ValueError,'distinct verified'):
                brunch.generate_dynamic_brunch_column(12)
        model.assert_not_called()

    def test_leaf_fact_deduplication_across_envelopes_aliases_and_nested_offsets(self):
        self.row['decisionBoardFingerprint']='board-v1'
        with patch('common.operating_plan.execution_board',return_value={'fingerprint':'board-v1'}), \
             patch.object(crew,'reasoning_source_state',return_value='stable-source'), \
             patch.object(crew,'next_eligible_time',return_value=None):
            parent_args={'name':'revenue','select':['months','2026-11','sources'],'offset':0,'limit':2}
            parent_res={'available':True,'source':'dashboard/data/revenue.json','selection':['months','2026-11','sources'],
                'fields':None,'missingFields':[],'pagination':{'offset':0,'limit':2,'totalItems':2,'truncated':False,'nextOffset':None},
                'data':[
                    {'id':'adsense','status':'collected','rows':[{'domain':'must-pick.com','amount':0.81}]},
                    {'detailRequired':True,'characters':9200,'readWith':{'name':'revenue','select':['months','2026-11','sources',1]}}
                ]}
            self.row['observations'].append({'id':'e1','actor':'jarvis','tool':'evidence','arguments':parent_args,'result':parent_res,'sha256':'s1','observedAt':1})
            crew.repeated_investigation(self.row,'evidence',parent_args,parent_res)
            self.assertEqual(self.row['boardUnchangedReads'],0)
            self.assertNotIn('decisionRequired',self.row)
            # Same leaf facts via fields projection and limit variation -> not novel
            fields_args={'name':'revenue','select':['months','2026-11','sources',0],'fields':['id','status'],'offset':0,'limit':10}
            fields_res={'available':True,'source':'dashboard/data/revenue.json','selection':['months','2026-11','sources',0],
                'fields':['id','status'],'missingFields':[],'pagination':{'offset':0,'limit':2,'totalItems':2,'truncated':False,'nextOffset':None},
                'data':{'id':'adsense','status':'collected'}}
            crew.repeated_investigation(self.row,'evidence',fields_args,fields_res)
            self.assertEqual(self.row['boardUnchangedReads'],1)
            # Same leaf facts via observation:e1 archive alias -> not novel, triggers decisionRequired before inferenceWatch
            alias_args={'name':'observation:e1','select':['data',0,'rows',0],'offset':0,'limit':5}
            alias_res={'source':'persisted goal observation','evidenceId':'e1','selection':['data',0,'rows',0],
                'fields':None,'missingFields':[],'pagination':{'offset':0,'limit':2,'totalItems':2,'truncated':False,'nextOffset':None},
                'data':{'domain':'must-pick.com','amount':0.81}}
            crew.repeated_investigation(self.row,'evidence',alias_args,alias_res)
            self.assertEqual(self.row['boardUnchangedReads'],2)
            self.assertIn('decisionRequired',self.row)
            self.assertNotIn('inferenceWatch',self.row)
            # Drilling down into detailRequired stub at index 1 (or next page offset=1) is novel and clears decisionRequired
            page2_args={'name':'revenue','select':['months','2026-11','sources'],'offset':1,'limit':1}
            page2_res={'available':True,'source':'dashboard/data/revenue.json','selection':['months','2026-11','sources'],
                'fields':None,'missingFields':[],'pagination':{'offset':1,'limit':1,'totalItems':2,'truncated':False,'nextOffset':None},
                'data':[{'id':'adpost','status':'session_expired','rows':[{'domain':'naver','amount':0.0}]}]}
            crew.repeated_investigation(self.row,'evidence',page2_args,page2_res)
            self.assertEqual(self.row['boardUnchangedReads'],0)
            self.assertNotIn('decisionRequired',self.row)
            # Child read of nested list inside offset=1 item matches canonical path (sources -> 1 -> rows -> 0) -> not novel
            nested_child_args={'name':'revenue','select':['months','2026-11','sources',1,'rows',0]}
            nested_child_res={'available':True,'source':'dashboard/data/revenue.json','selection':['months','2026-11','sources',1,'rows',0],
                'data':{'domain':'naver','amount':0.0}}
            crew.repeated_investigation(self.row,'evidence',nested_child_args,nested_child_res)
            self.assertEqual(self.row['boardUnchangedReads'],1)

    def test_inspect_url_acquisition_reuses_collect_window_and_preserves_holds_and_incomplete_none(self):
        from contextlib import contextmanager
        from dashboard.collectors import revenue_focus
        from server.agent_tools import execute_agent_tool
        url='https://must-pick.com/entry/valid-article-slug'
        cfg_path=self.data/'collector_config.json'
        rev_path=self.data/'revenue.json'
        state_path=self.data/'revenue-focus.json'
        cache_path=self.data/'url-acquisition-cache.json'
        write(cfg_path,{'analytics_readers':{},'sites':{'must-pick.com':{'ga4_property':'12345'}}})
        write(rev_path,{'growth':{'sources':{'sj':{'rows':[{'domain':'must-pick.com','revenue':0.81,'pageViews':900}]}}},'pagePerformance':{}})
        write(state_path,{'schema':'revenue-focus-v1','policy':{'apiReportBudgetPerRun':12},'lastApiReportBudgetUsed':0,'targets':[]})
        @contextmanager
        def fake_session(*_a,**_kw):
            yield object()
        reports=[
            ([([],(10,15))],False),
            ([(['google','organic',''],(6,9)),(['barolab_qa','audit',''],(2,3)),(['(direct)','(none)',''],(2,3))],False)
        ]
        with patch.object(revenue_focus.traffic,'CONFIG',cfg_path), \
             patch.object(revenue_focus.traffic,'DATA',self.data), \
             patch.object(revenue_focus,'STATE',state_path), \
             patch.object(revenue_focus.traffic,'session',side_effect=fake_session), \
             patch.object(revenue_focus.traffic,'ga_report',side_effect=reports) as ga_mock:
            res=execute_agent_tool('trace','inspect_url_acquisition',project='cf_blog',url=url,start='2026-11-01',end='2026-11-07')
            self.assertTrue(res['ok'])
            self.assertTrue(res['complete'])
            self.assertEqual(res['qualifiedSessions'],6)
            self.assertEqual(res['breakdown']['excluded']['sessions'],2)
            self.assertEqual(res['breakdown']['unattributed']['sessions'],2)
            self.assertIsNone(res['articleRevenue'])
            self.assertFalse(res['domainRevenueAllocated'])
            self.assertEqual(ga_mock.call_count,2)
            # Second call hits cache without extra GA4 calls
            cached=execute_agent_tool('trace','inspect_url_acquisition',project='cf_blog',url=url,start='2026-11-01',end='2026-11-07')
            self.assertTrue(cached['cached'])
            self.assertEqual(ga_mock.call_count,2)
        # Incomplete report keeps qualifiedSessions/qualifiedPageViews as None
        incomplete_reports=[([([],(5,5))],True),([(['google','organic',''],(5,5))],False)]
        with patch.object(revenue_focus.traffic,'session',side_effect=fake_session), \
             patch.object(revenue_focus.traffic,'ga_report',side_effect=incomplete_reports):
            inc=revenue_focus.inspect_url_acquisition(url,'2026-10-01','2026-10-07',path=state_path,config_path=cfg_path,revenue_path=rev_path,cache_path=cache_path)
            self.assertFalse(inc['complete'])
            self.assertIsNone(inc['qualifiedSessions'])
            self.assertIsNone(inc['qualifiedPageViews'])
        # Auth/manual hold on target is never auto-retried
        write(state_path,{'schema':'revenue-focus-v1','policy':{'apiReportBudgetPerRun':12},'targets':[{'url':url,'collectionError':{'type':'PermissionError','manualResolutionRequired':True}}]})
        with patch.object(revenue_focus.traffic,'session',side_effect=AssertionError('must not retry held auth')):
            held=revenue_focus.inspect_url_acquisition(url,'2026-09-01','2026-09-07',path=state_path,config_path=cfg_path,revenue_path=rev_path,cache_path=cache_path)
            self.assertFalse(held['ok'])
            self.assertEqual(held['status'],'held')
            self.assertTrue(held['manualResolutionRequired'])

    def test_large_valid_page_repeated_read_retains_all_600_leaves_without_false_novelty(self):
        self.row['decisionBoardFingerprint']='board-600'
        page_args={'name':'traffic','select':['pagePerformance','pages'],'fields':['sessions','pageViews','url'],'offset':0,'limit':200}
        page_res={'available':True,'source':'dashboard/data/traffic.json','selection':['pagePerformance','pages'],
            'fields':['sessions','pageViews','url'],'missingFields':[],
            'pagination':{'offset':0,'limit':200,'totalItems':200,'truncated':False,'nextOffset':None},
            'data':[{'url':f'https://must-pick.com/entry/post-{i}','sessions':i+1,'pageViews':(i+1)*2} for i in range(200)]}
        with patch('common.operating_plan.execution_board',return_value={'fingerprint':'board-600'}), \
             patch.object(crew,'reasoning_source_state',return_value='stable-600'), \
             patch.object(crew,'next_eligible_time',return_value=None):
            leaves=crew._canonical_leaf_digests(self.row,'evidence',page_args,page_res)
            self.assertEqual(len(leaves),600)
            crew.repeated_investigation(self.row,'evidence',page_args,page_res)
            self.assertEqual(len(self.row['investigationFacts']),600)
            self.assertEqual(self.row['boardUnchangedReads'],0)
            # Second read of the same 600-leaf page must not evict the first 88 leaves
            crew.repeated_investigation(self.row,'evidence',page_args,page_res)
            self.assertEqual(len(self.row['investigationFacts']),600)
            self.assertEqual(self.row['boardUnchangedReads'],1)
            # Third read triggers decisionRequired without sleeping first
            crew.repeated_investigation(self.row,'evidence',page_args,page_res)
            self.assertEqual(self.row['boardUnchangedReads'],2)
            self.assertIn('decisionRequired',self.row)
            self.assertNotIn('inferenceWatch',self.row)

    def test_decision_transition_is_never_suppressed_before_action_or_explicit_hold(self):
        self.row['decisionBoardFingerprint']='board-sleep'
        small_args={'name':'revenue','select':['collectionStatus']}
        small_res={'available':True,'source':'dashboard/data/revenue.json','selection':['collectionStatus'],'data':'collected'}
        with patch('common.operating_plan.execution_board',return_value={'fingerprint':'board-sleep'}), \
             patch.object(crew,'reasoning_source_state',return_value='stable-sleep'), \
             patch.object(crew,'next_eligible_time',return_value=None):
            for _ in range(4):
                crew.repeated_investigation(self.row,'evidence',small_args,small_res)
            self.assertTrue(bool(self.row.get('decisionRequired')))
            self.assertFalse(bool(self.row.get('inferenceWatch')))
            self.assertFalse(crew.reasoning_waiting_for_change(self.row))
            # If the model in _advance keeps repeating unchanged reads after decisionRequired, host records explicit hold before watch
            self.row['observations']=[{'id':'e0','actor':'jarvis','tool':'evidence','arguments':small_args,'result':small_res,'sha256':'s0','observedAt':1}]
            stubborn={'decision':'tool','tool':'evidence','arguments':json.dumps(small_args),'colleague':'',
                      'message':'Re-reading same status','plan':['Check status'],'evidence_ids':['e0']}
            self.row['lastRoute']={'provider':'agy','model':'test'}
            with patch('common.operating_plan.enabled',return_value=True), \
                 patch.object(crew,'refresh_operating_actions'), \
                 patch.object(crew,'refresh_pending',return_value=True), \
                 patch.object(crew,'ask',return_value=stubborn), \
                 patch.object(crew,'tool_call',return_value=small_res), \
                 patch.object(crew,'deliver_step'), \
                 patch.object(crew,'save'):
                crew._advance(self.row,1)
            self.assertNotIn('decisionRequired',self.row)
            self.assertIn('decisionHold',self.row)
            self.assertEqual(self.row['decisionHold']['owner'],'jarvis')
            self.assertTrue(self.row['inferenceWatch']['holdRecorded'])
            self.assertTrue(crew.reasoning_waiting_for_change(self.row))

    def test_url_acquisition_budget_period_expiry_stale_cache_rejection_and_partial_failure_accounting(self):
        from contextlib import contextmanager
        from dashboard.collectors import revenue_focus
        cfg_path=self.data/'collector_config.json'
        rev_path=self.data/'revenue.json'
        state_path=self.data/'revenue-focus.json'
        cache_path=self.data/'url-acquisition-cache.json'
        write(cfg_path,{'analytics_readers':{},'sites':{'must-pick.com':{'ga4_property':'12345'}}})
        write(rev_path,{'pagePerformance':{}})
        now_t0=dt.datetime(2026,11,8,12,15,tzinfo=revenue_focus.KST)
        write(state_path,{'schema':'revenue-focus-v1','checkedAt':now_t0.isoformat(),
            'budgetPeriod':'run:2026-11-08-12','budgetExpiresAt':(now_t0+dt.timedelta(hours=1)).isoformat(),
            'policy':{'apiReportBudgetPerRun':12},'lastApiReportBudgetUsed':10,'targets':[]})
        # 1) Legacy exhausted cache with no budgetPeriod/budgetExpiresAt must NEVER be reset to 0
        stale_url='https://must-pick.com/entry/stale-article'
        write(cache_path,{'apiReportCallsUsed':12,'entries':{},'domainHolds':{}})
        @contextmanager
        def fake_session(*_a,**_kw):
            yield object()
        with patch.object(revenue_focus.traffic,'session',side_effect=fake_session), \
             patch.object(revenue_focus.traffic,'ga_report') as legacy_mock:
            legacy_held=revenue_focus.inspect_url_acquisition(stale_url,'2026-10-01','2026-10-07',
                path=state_path,config_path=cfg_path,revenue_path=rev_path,cache_path=cache_path,now=now_t0)
            self.assertEqual(legacy_held['status'],'held')
            self.assertEqual(legacy_held['reason'],'shared_api_report_budget_exhausted')
            self.assertEqual(legacy_mock.call_count,0)
            self.assertEqual(load(cache_path)['apiReportCallsUsed'],12)
        # 2) Unexpired budget period with different identifier must NEVER be reset to 0
        write(cache_path,{'apiReportCallsUsed':12,'budgetPeriod':'another-explicit-run',
            'budgetExpiresAt':(now_t0+dt.timedelta(hours=2)).isoformat(),'entries':{},'domainHolds':{}})
        with patch.object(revenue_focus.traffic,'session',side_effect=fake_session), \
             patch.object(revenue_focus.traffic,'ga_report') as unexpired_mock:
            unexpired_held=revenue_focus.inspect_url_acquisition(stale_url,'2026-10-01','2026-10-07',
                path=state_path,config_path=cfg_path,revenue_path=rev_path,cache_path=cache_path,now=now_t0)
            self.assertEqual(unexpired_held['status'],'held')
            self.assertEqual(unexpired_held['reason'],'shared_api_report_budget_exhausted')
            self.assertEqual(unexpired_mock.call_count,0)
            self.assertEqual(load(cache_path)['apiReportCallsUsed'],12)
            self.assertEqual(load(cache_path)['budgetPeriod'],'another-explicit-run')
        # 3) Concurrent call when collector_lock is busy returns busy without spending calls or mutating cache
        @contextmanager
        def busy_lock(*_a,**_kw):
            yield False
        with patch.object(revenue_focus.traffic,'collector_lock',side_effect=busy_lock), \
             patch.object(revenue_focus.traffic,'ga_report') as busy_mock:
            busy_res=revenue_focus.inspect_url_acquisition(stale_url,'2026-10-01','2026-10-07',
                path=state_path,config_path=cfg_path,revenue_path=rev_path,cache_path=cache_path,now=now_t0)
            self.assertEqual(busy_res['status'],'busy')
            self.assertEqual(busy_res['reason'],'collector_lock_busy')
            self.assertEqual(busy_mock.call_count,0)
        # 4) Seed a stale cache entry from 2026-10-01 in a fresh run -> stale entry rejected, fresh report collected
        write(cache_path,{'entries':{f'{stale_url}|2026-10-01|2026-10-07':{
            'ok':True,'tool':'inspect_url_acquisition','url':stale_url,'domain':'must-pick.com',
            'start':'2026-10-01','end':'2026-10-07','timezone':'Asia/Seoul','source':revenue_focus.SOURCE,
            'checkedAt':'2026-10-01T00:00:00+09:00','complete':True,'reconciled':True,'limited':False,
            'status':'collected','qualifiedSessions':9,'qualifiedPageViews':12,'breakdown':{'attributed':{'sessions':9,'pageViews':12}}
        }},'domainHolds':{}})
        fresh_reports=[
            ([([],(4,6))],False),
            ([(['google','organic',''],(4,6))],False)
        ]
        with patch.object(revenue_focus.traffic,'session',side_effect=fake_session), \
             patch.object(revenue_focus.traffic,'ga_report',side_effect=fresh_reports) as ga_mock, \
             patch.object(revenue_focus.traffic,'stamp',return_value=now_t0.isoformat()):
            refreshed=revenue_focus.inspect_url_acquisition(stale_url,'2026-10-01','2026-10-07',
                path=state_path,config_path=cfg_path,revenue_path=rev_path,cache_path=cache_path,now=now_t0)
            self.assertTrue(refreshed['ok'])
            self.assertFalse(refreshed['cached'])
            self.assertEqual(refreshed['qualifiedSessions'],4)
            self.assertTrue(refreshed['hasBudgetPeriodOrExpiry'])
            self.assertEqual(ga_mock.call_count,2)
            # Re-reading exact same URL/window within TTL uses fresh cache without extra API calls
            cached_hit=revenue_focus.inspect_url_acquisition(stale_url,'2026-10-01','2026-10-07',
                path=state_path,config_path=cfg_path,revenue_path=rev_path,cache_path=cache_path,now=now_t0+dt.timedelta(minutes=5))
            self.assertTrue(cached_hit['ok'])
            self.assertTrue(cached_hit['cached'])
            self.assertEqual(ga_mock.call_count,2)
            # Now 10 + 2 = 12 calls used in this period -> next distinct URL in the SAME period is held
            exhausted=revenue_focus.inspect_url_acquisition('https://must-pick.com/entry/second-article','2026-10-01','2026-10-07',
                path=state_path,config_path=cfg_path,revenue_path=rev_path,cache_path=cache_path,now=now_t0)
            self.assertFalse(exhausted['ok'])
            self.assertEqual(exhausted['reason'],'shared_api_report_budget_exhausted')
            self.assertTrue(exhausted['hasBudgetPeriodOrExpiry'])
            # Merely advancing clock past expiry WITHOUT an explicitly authorized new budgetPeriod in state keeps hold
            now_t1=now_t0+dt.timedelta(hours=2)
            still_held=revenue_focus.inspect_url_acquisition('https://must-pick.com/entry/second-article','2026-10-01','2026-10-07',
                path=state_path,config_path=cfg_path,revenue_path=rev_path,cache_path=cache_path,now=now_t1)
            self.assertFalse(still_held['ok'])
            self.assertEqual(still_held['reason'],'shared_api_report_budget_exhausted')
            self.assertEqual(ga_mock.call_count,2)
            # New state budgetPeriod WITHOUT budgetExpiresAt (or with past/invalid budgetExpiresAt) must NEVER invent expiry or reset usage
            for bad_state in (
                {'schema':'revenue-focus-v1','checkedAt':now_t1.isoformat(),'budgetPeriod':'new-period-without-expiry','policy':{'apiReportBudgetPerRun':12},'lastApiReportBudgetUsed':0,'targets':[]},
                {'schema':'revenue-focus-v1','checkedAt':now_t1.isoformat(),'budgetPeriod':'new-period-invalid-exp','budgetExpiresAt':'not-a-timestamp','policy':{'apiReportBudgetPerRun':12},'lastApiReportBudgetUsed':0,'targets':[]},
                {'schema':'revenue-focus-v1','checkedAt':now_t1.isoformat(),'budgetPeriod':'new-period-past-exp','budgetExpiresAt':(now_t1-dt.timedelta(minutes=5)).isoformat(),'policy':{'apiReportBudgetPerRun':12},'lastApiReportBudgetUsed':0,'targets':[]},
            ):
                write(state_path,bad_state)
                bad_res=revenue_focus.inspect_url_acquisition('https://must-pick.com/entry/second-article','2026-10-01','2026-10-07',
                    path=state_path,config_path=cfg_path,revenue_path=rev_path,cache_path=cache_path,now=now_t1)
                self.assertEqual(bad_res['status'],'held')
                self.assertEqual(bad_res['reason'],'shared_api_report_budget_exhausted')
                self.assertEqual(ga_mock.call_count,2)
                self.assertEqual(load(cache_path)['budgetPeriod'],'run:2026-11-08-12')
        # 5) Explicitly verified next budget period after expiry + mid-window failure call accounting
        write(state_path,{'schema':'revenue-focus-v1','checkedAt':now_t1.isoformat(),
            'budgetPeriod':'run:2026-11-08-14','budgetExpiresAt':(now_t1+dt.timedelta(hours=6)).isoformat(),
            'policy':{'apiReportBudgetPerRun':12},'lastApiReportBudgetUsed':0,'targets':[]})
        partial_fail_reports=[
            ([([],(3,3))],False),
            RuntimeError('transient network error on second GA4 report')
        ]
        with patch.object(revenue_focus.traffic,'session',side_effect=fake_session), \
             patch.object(revenue_focus.traffic,'ga_report',side_effect=partial_fail_reports):
            failed=revenue_focus.inspect_url_acquisition('https://must-pick.com/entry/second-article','2026-10-01','2026-10-07',
                path=state_path,config_path=cfg_path,revenue_path=rev_path,cache_path=cache_path,now=now_t1)
            self.assertFalse(failed['ok'])
            self.assertEqual(failed['status'],'failed')
            self.assertEqual(failed['apiReportCallsSpent'],2)
        saved_cache=load(cache_path)
        self.assertEqual(saved_cache['budgetPeriod'],'run:2026-11-08-14')
        self.assertEqual(saved_cache['apiReportCallsUsed'],2)
        self.assertEqual(saved_cache['budgetHistory'][-1]['budgetPeriod'],'run:2026-11-08-12')
        self.assertTrue(saved_cache['hasBudgetPeriodOrExpiry'])


class CafePreparationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)

    def test_preparation_connects_reviewed_artifact_without_claiming_publication(self):
        from common import project_autonomy as autonomy
        from naver_cafe_posting import editorial,posting
        from unittest.mock import Mock
        status={};writer=Mock(return_value={'documentSha256':'reviewed'})
        with patch.object(autonomy,'ROOT',self.root),patch.object(editorial,'OUTPUT',self.root/'output'), \
             patch.object(editorial,'prepare_part',writer),patch.object(posting,'load_cafe_status',return_value=status), \
             patch.object(posting,'save_cafe_status') as save:
            result=autonomy.prepare_cafe_content('naver_cafe','boutiqueinfo',21,'A new reader question')
        self.assertEqual(result['status'],'prepared');self.assertFalse(result['publicationVerified'])
        self.assertEqual(save.call_args.args[0]['approvedPreparedPart'],21)
        self.assertEqual(writer.call_args.kwargs['topic'],'A new reader question')

    def test_unknown_submission_is_never_reprepared(self):
        from common import project_autonomy as autonomy
        from naver_cafe_posting import editorial,posting
        folder=self.root/'output/prepared/part-21/boutiqueinfo'
        write(folder/'intent.json',{'status':'submission_unknown'})
        before=(folder/'intent.json').read_bytes()
        with patch.object(autonomy,'ROOT',self.root),patch.object(editorial,'OUTPUT',self.root/'output'), \
             patch.object(editorial,'prepare_part') as writer,patch.object(posting,'load_cafe_status',return_value={}):
            result=autonomy.prepare_cafe_content('naver_cafe','boutiqueinfo',21,'Reader question')
        self.assertEqual(result['status'],'held');writer.assert_not_called()
        self.assertEqual((folder/'intent.json').read_bytes(),before)

    def test_unchanged_failed_input_does_not_repeat_paid_drafting(self):
        from common import project_autonomy as autonomy
        from naver_cafe_posting import editorial,posting
        with patch.object(autonomy,'ROOT',self.root),patch.object(editorial,'OUTPUT',self.root/'output'), \
             patch.object(editorial,'prepare_part',side_effect=ValueError('Missing exact observed source')) as writer, \
             patch.object(posting,'load_cafe_status',return_value={}):
            first=autonomy.prepare_cafe_content('naver_cafe','boutiqueinfo',21,'Reader question')
            second=autonomy.prepare_cafe_content('naver_cafe','boutiqueinfo',21,'Reader question')
        self.assertEqual(writer.call_count,1);self.assertTrue(second['reusedUnchangedInput'])
        self.assertEqual(first['reason'],'Missing exact observed source')

    def test_restriction_prevents_browser_lease(self):
        from naver_cafe_posting import posting
        with patch('dashboard.common.ego_taskspace.run_ego_mjs') as browser:
            with self.assertRaisesRegex(ValueError,'restriction'):
                posting.acquire_cafe_browser_lease('dekilab')
        browser.assert_not_called()

    def test_wrong_visible_account_cannot_create_lease(self):
        from naver_cafe_posting import posting
        with patch.object(posting,'load_cafe_status',return_value={}), \
             patch.object(posting,'save_cafe_status') as save, \
             patch('dashboard.common.ego_taskspace.run_ego_mjs',return_value={'ok':False,'error':'mismatch'}):
            with self.assertRaisesRegex(ValueError,'verification failed'):
                posting.acquire_cafe_browser_lease('boutiqueinfo')
        save.assert_not_called()

    def test_writer_uses_the_same_audience_vocabulary_as_validator(self):
        from naver_cafe_posting import editorial,posting
        folder=self.root/'cafe';write(folder/'research.json',{'sources':[]})
        def capture(prompt,**kwargs):
            self.assertEqual(kwargs['response_schema']['properties']['audienceTags']['items']['enum'],
                posting.CAFE_POLICIES['boutiqueinfo']['topicTags'])
            raise RuntimeError('schema captured')
        with self.assertRaisesRegex(RuntimeError,'schema captured'):
            editorial.prepare_part('boutiqueinfo',21,folder,topic='Reader health question',generate=capture)

    def test_knowledgein_read_tools_preserve_user_control_and_existing_writing_tabs(self):
        from common import ego_taskspace as ego
        def capture(script,**kwargs):
            self.assertIn('found.ownership!=="agent"',script)
            self.assertLess(script.index('UserTakeoverError'),script.index('const task ='))
            self.assertIn('const page = await task.newPage()',script)
            self.assertIn('await page.close()',script)
            self.assertNotIn('task.page("p1")',script)
            return {'ok':False,'errorType':'UserTakeoverError'}
        with patch.object(ego,'run_ego_mjs',side_effect=capture),patch.object(ego,'resolve_ego_profile',return_value='Profile 4'):
            ego.native_kin_discover_links('soul5373',[])
            ego.native_kin_fetch_page_state('soul5373','https://kin.naver.com/')

    def test_brunch_repair_cannot_touch_an_uncertain_or_published_submission(self):
        from common import editorial_recovery as recovery
        folder=self.root/'brunch_posting/output/prepared/part-11';folder.mkdir(parents=True)
        with patch.object(recovery,'ROOT',self.root):
            for state in ('submitting','unknown','published'):
                write(folder/'publication-intent.json',{'state':state})
                with self.assertRaisesRegex(ValueError,'requires reconciliation'):
                    recovery.writable(folder)
            write(folder/'publication-intent.json',{'state':'prepared'})
            self.assertEqual(recovery.writable(folder),folder.resolve())

    def test_memory_restart_does_not_repeat_historical_fts_backfill(self):
        from common import hermes_memory as memory
        import sqlite3
        root=self.root/'memory';first=memory.HermesMemory(root=root,skills_root=self.root/'skills')
        first.initialize()
        with first.db() as db:
            db.execute('DELETE FROM memory_migrations')
            db.execute('INSERT INTO episodes VALUES(?,?,?,?,?,?,?,?)',
                ('legacy','session','test','old searchable knowledge','{}',1,'[]','2026-11-07'))
        upgraded=memory.HermesMemory(root=root,skills_root=self.root/'skills');upgraded.initialize()
        with upgraded.db() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM sessions_fts WHERE event_id='legacy'").fetchone()[0],1)
        queries=[];connect=sqlite3.connect
        def traced(*args,**kwargs):
            db=connect(*args,**kwargs);db.set_trace_callback(queries.append);return db
        with patch.object(memory.sqlite3,'connect',side_effect=traced),patch.object(memory,'file_lock') as lock:
            restarted=memory.HermesMemory(root=root,skills_root=self.root/'skills');restarted.initialize()
        lock.assert_not_called()
        self.assertTrue(restarted._initialized)
        self.assertFalse(any('INSERT' in q.upper() or 'CREATE' in q.upper() for q in queries))

    def test_refusal_feedback_identifies_the_precise_internal_meta_phrase(self):
        from common.content_quality import validate_no_refusal_or_corruption
        with self.assertRaises(ValueError) as failure:
            validate_no_refusal_or_corruption({'title':'Reader question','contentHtml':'Reader question: 제공된 자료의 수집일은 오늘입니다.'})
        self.assertIn('matchedText',str(failure.exception))
        self.assertIn('context',str(failure.exception))

    def test_cafe_repair_preserves_uncertain_submission(self):
        from common import editorial_recovery as recovery
        folder=self.root/'naver_cafe_posting/output/prepared/part-21/boutiqueinfo';folder.mkdir(parents=True)
        write(folder/'intent.json',{'status':'submission_unknown'})
        with patch.object(recovery,'ROOT',self.root):
            with self.assertRaisesRegex(ValueError,'requires reconciliation'):
                recovery.writable(folder)

    def test_cf_held_preparation_cannot_bypass_manual_stop(self):
        from common import cf_recovery as recovery
        from unittest.mock import Mock
        day=dt.date.today().isoformat();domain='maxnote.kr'
        write(self.root/'dashboard/data/cf/daily_schedule.json',{'date':day,'items':[{'domain':domain,'scheduledTime':'12:10','status':'waiting','manualStop':True}]})
        write(self.root/'dashboard/data/cf/normalization-state.json',{'slots':{day+'/'+domain:{'status':'held'}}})
        acquire=Mock()
        with patch('common.channel_parameters.policy',return_value={'cf':{domain:'12:10'}}),patch('common.editorial_recovery.acquire',acquire):
            with self.assertRaisesRegex(ValueError,'protected state'):
                recovery.repair_normalized_preparation(domain,day,root=self.root)
        acquire.assert_not_called()

    def test_cf_handoff_occurs_only_after_original_identity_and_final_checks(self):
        from common import cf_recovery as recovery
        from unittest.mock import Mock
        from contextlib import ExitStack
        day=dt.date.today().isoformat();domain='maxnote.kr'
        original=self.root/'cf_posting/output/scheduled'/day/domain
        revision=self.root/'cf_posting/output/normalization'/day/domain/'revision'
        article={'title':'Original reader task','contentHtml':'<p>Observed answer</p>'}
        for folder in (original,revision):
            write(folder/'article.json',article);write(folder/'planning.json',{'keyword':'Original reader task'})
        row={'domain':domain,'scheduledTime':'12:10','status':'waiting'}
        write(self.root/'dashboard/data/cf/daily_schedule.json',{'date':day,'items':[row]})
        write(self.root/'dashboard/data/cf/normalization-state.json',{'slots':{day+'/'+domain:{'status':'held',
            'revision':str(revision),'originalFolder':str(original),'originalSha256':recovery.fingerprint(original)}}})
        with ExitStack() as stack:
            for target,value in [('common.channel_parameters.policy',{'cf':{domain:'12:10'}}),
                ('common.cf_recovery.repair_eligible',True),('common.cf_recovery.original_folder',original),
                ('common.editorial_recovery.acquire',[]),('common.editorial_recovery.writable',revision),
                ('common.editorial_recovery.review_and_repair',[]),('cf_posting.posting.ensure_article_images',article),
                ('cf_posting.posting.verify_article_images',None),('common.content_quality.ensure_publication_review',{}),
                ('common.cf_recovery.register_reviewed_revision',{'status':'prepared','publicationVerified':False})]:
                stack.enter_context(patch(target,return_value=value))
            post=stack.enter_context(patch('cf_posting.posting.run_basic_posting'))
            result=recovery.repair_normalized_preparation(domain,day,root=self.root)
            self.assertEqual(result['status'],'prepared');self.assertTrue(result['ok']);self.assertFalse(result['publicationVerified']);post.assert_not_called()
            write(revision/'claim-review-response.json',{'status':'changes_required','issues':['Missing official deadline evidence']})
            with patch('common.content_quality.ensure_publication_review',side_effect=ValueError('Draft held: final source defect')):
                failed=recovery.repair_normalized_preparation(domain,day,root=self.root)
            self.assertEqual(failed['status'],'needs_attention');self.assertFalse(failed['publicationVerified'])
            self.assertEqual(failed['feedback']['claim']['issues'],['Missing official deadline evidence'])
            post.assert_not_called()

    def test_official_month_day_weekday_format_is_equivalent_without_splitting_decimal_amounts(self):
        from common.content_improvement import number_tokens,fact_valid
        quote='2026-07-16 공고일정: 7.24(금) ~ 8.7(금), 공고일 기준 무주택세대구성원'
        source={'status':200,'text':quote}
        self.assertTrue(fact_valid({'sourceId':'0','quote':quote,'claim':'2026년 7월 24일부터 8월 7일까지 안내했습니다.'},{'0':source}))
        for amount in ('8.7%','8.7만원','8.7mg','8.7','13.40(금)','2.30(금)'):
            self.assertNotIn('8',number_tokens(amount))
        self.assertFalse(fact_valid({'sourceId':'0','quote':quote,'claim':'8월 9일까지 안내했습니다.'},{'0':source}))

    def test_youtube_uncertain_click_cannot_be_replayed(self):
        from common import ego_taskspace as ego
        with patch.object(ego,'__file__',str(self.root/'dashboard/common/ego_taskspace.py')), \
             patch.object(ego,'_native_publish_youtube_community_once',return_value={'ok':True,'submissionDispatched':True}) as browser:
            first=ego.native_publish_youtube_community_post('@yoon_autolab','Exact approved post')
            second=ego.native_publish_youtube_community_post('@yoon_autolab','Exact approved post')
        self.assertFalse(first['publicationVerified']);self.assertEqual(second['status'],'existing_intent_preserved')
        self.assertEqual(browser.call_count,1)

    def test_youtube_channel_page_or_partial_body_is_never_public_proof(self):
        from common import ego_taskspace as ego
        alleged={'ok':True,'publicationVerified':True,'publicBodyMatched':True,'submissionDispatched':True,
            'post':{'url':'https://www.youtube.com/@yoon_autolab/posts','text':'Partial','channelHandle':'@yoon_autolab'}}
        with patch.object(ego,'__file__',str(self.root/'dashboard/common/ego_taskspace.py')), \
             patch.object(ego,'_native_publish_youtube_community_once',return_value=alleged):
            result=ego.native_publish_youtube_community_post('@yoon_autolab','Complete approved body')
        self.assertFalse(result['ok']);self.assertFalse(result['publicationVerified'])

    def test_youtube_package_cannot_report_success_from_click_acknowledgment(self):
        from youtube_posting import posting as youtube
        with patch('dashboard.common.ego_taskspace.native_publish_youtube_community_post',return_value={'ok':True,'clickInfo':{'clicked':True}}), \
             patch.object(youtube,'load_youtube_status',return_value={}),patch.object(youtube,'save_youtube_status'), \
             patch.object(youtube,'sync_youtube_live_state') as sync:
            result=youtube.produce_youtube_svml_package(4)
        self.assertFalse(result['ok']);self.assertFalse(result['publicationVerified']);sync.assert_not_called()

    def test_keyword_scope_variation_requires_bound_independent_judgment_without_relabeling_inputs(self):
        from common import content_quality as quality
        import hashlib
        folder=self.root/'cf_posting/output/prepared/router';folder.mkdir(parents=True)
        article={'title':'Router reset guide','mainKeyword':'router reset','contentHtml':'<p>Router reset safely using the documented controls.</p>'}
        planning={'keyword':'router reset safely'}
        text='Router reset documentation from the manufacturer.'
        research={'collectedAt':dt.datetime.now(dt.timezone.utc).isoformat(),'keyword':'router reset','requestedKeyword':'router reset',
            'sources':[{'url':'https://example.com/manual','status':200,'text':text,'textSha256':hashlib.sha256(text.encode()).hexdigest()}]}
        write(folder/'research.json',research);write(folder/'planning.json',planning)
        before=(folder/'research.json').read_bytes(),(folder/'planning.json').read_bytes()
        called=[]
        def reviewer(prompt,**kwargs):
            scope=quality.cf_topic_scope(article,folder)
            self.assertIn('topicScopeMapping',kwargs['response_schema']['required'])
            called.append(1)
            return {'status':'passed','issues':[],'experienceHonest':True,'claimsComplete':True,
                'highRiskClaims':[],'experienceClaims':[],'hypotheticalClaims':[],'claimSources':[],
                'topicScopeMapping':{**scope,'sameScope':True}}
        with patch.object(quality,'__file__',str(self.root/'dashboard/common/content_quality.py')):
            result=quality.ensure_publication_review(article,folder,generate=reviewer)
            quality.ensure_publication_review(article,folder,generate=reviewer)
            changed={**article,'contentHtml':'<p>Router reset with an unsupported different task.</p>'}
            rejected={k:result[k] for k in ('status','issues','experienceHonest','claimsComplete','highRiskClaims','experienceClaims','hypotheticalClaims','claimSources')}
            rejected['topicScopeMapping']={**quality.cf_topic_scope(changed,folder),'sameScope':False}
            with self.assertRaisesRegex(ValueError,'topic-scope review'):
                quality.ensure_publication_review(changed,folder,generate=lambda *a,**kw:rejected)
        self.assertEqual(len(called),1);self.assertTrue(result['topicScopeMapping']['sameScope'])
        self.assertEqual(before,((folder/'research.json').read_bytes(),(folder/'planning.json').read_bytes()))

    def test_hug_public_notices_are_primary_but_personal_and_write_surfaces_are_not(self):
        from common.content_improvement import primary_url
        base='https://www.khug.or.kr/jeonse/web/s07/'
        for path in ('s070101.jsp','s070102.jsp','s070301.jsp','s070301.jsp?currentPage=2','s070301.jsp?articleId=37971&currentPage=1&mode=S'):
            self.assertTrue(primary_url(base+path),path)
        for path in ('s070103.jsp','s070408.jsp','s070301.jsp?articleId=37971&mode=U','s070301.jsp?articleId=37971&mode=S&redirect=elsewhere','s070301.jsp?articleId=1&mode=S&mode=W'):
            self.assertFalse(primary_url(base+path),path)
        self.assertFalse(primary_url('https://www.khug.or.kr.fake.example/jeonse/web/s07/s070101.jsp'))

    def test_review_drains_at_model_boundary_without_destroying_candidate_or_calling_another_model(self):
        from common import editorial_recovery as recovery
        from unittest.mock import Mock
        import os
        folder=self.root/'naver_blog_posting/output/prepared';folder.mkdir(parents=True)
        write(self.root/'dashboard/data/memory-worker-control.json',{'action':'stop-after-current-actions','pid':os.getpid()})
        document={'title':'Original question','blocks':[{'type':'text','text':'Preserved answer'}]}
        model=Mock();check=Mock()
        with patch.object(recovery,'ROOT',self.root):
            self.assertTrue(recovery.worker_reload_requested())
            with self.assertRaisesRegex(ValueError,'worker reload requested'):
                recovery.review_and_repair(document,folder,[check],generate=model)
            write(self.root/'dashboard/data/memory-worker-control.json',{'action':'stop-after-current-actions','pid':os.getpid()+1})
            self.assertFalse(recovery.worker_reload_requested())
        model.assert_not_called();check.assert_not_called();self.assertEqual(document['blocks'][0]['text'],'Preserved answer')

    def test_brunch_pre_submit_editor_error_is_distinct_from_uncertain_submission(self):
        from brunch_posting.posting import brunch_receipt_state
        staged={'ok':False,'mode':'staged','editorVerified':True,'submissionDispatched':False,'stagedPage':{'space':155,'page':'p20'}}
        self.assertEqual(brunch_receipt_state(staged),'staged_verified')
        self.assertEqual(brunch_receipt_state({**staged,'submissionDispatched':True}),'unknown')
        self.assertEqual(brunch_receipt_state({'ok':True,'mode':'published'}),'unknown')
        self.assertEqual(brunch_receipt_state({'ok':True,'mode':'published','publicPublicationVerified':True,'publicBodyMatched':True,'url':'https://brunch.co.kr/@31d1f5fb288c4fc/11'}),'published')

    def test_youtube_preparation_preserves_uncertain_original_without_a_model_call(self):
        from youtube_posting import posting as youtube
        import hashlib
        topic='Independent reader question';channel='@yoon_autolab'
        key=hashlib.sha256(json.dumps([channel,topic],ensure_ascii=False).encode()).hexdigest()
        folder=self.root/'youtube_posting/output/prepared'/key;write(folder/'intent.json',{'status':'unknown'})
        with patch.object(youtube,'ROOT_DIR',self.root),patch.object(youtube,'load_youtube_status',return_value={}), \
             patch('common.llm_client.generate_json') as model:
            result=youtube.prepare_youtube_content('youtube',channel,topic)
        self.assertEqual(result['status'],'held');model.assert_not_called()

    def test_youtube_preparation_requires_both_independent_reviews_without_submitting(self):
        from youtube_posting import posting as youtube
        from common import editorial_recovery as recovery
        import hashlib
        topic='Router reset procedure';channel='@yoon_autolab'
        key=hashlib.sha256(json.dumps([channel,topic],ensure_ascii=False).encode()).hexdigest()
        folder=self.root/'youtube_posting/output/prepared'/key
        document={'title':'Router reset procedure','readerTask':topic,'blocks':[{'type':'text','text':'Read the device manual before choosing its reset control.'}]}
        write(folder/'candidate.json',document);write(folder/'research.json',{'sources':[{'url':'https://example.com/manual','text':'Observed instructions'}]})
        with patch.object(youtube,'ROOT_DIR',self.root),patch.object(recovery,'ROOT',self.root), \
             patch.object(youtube,'load_youtube_status',return_value={}),patch('common.editorial_recovery.acquire',return_value=[]), \
             patch('common.naver_reader.ensure_reader_review',return_value={}) as reader, \
             patch('common.content_quality.ensure_publication_review',return_value={}) as facts, \
             patch('dashboard.common.ego_taskspace.native_publish_youtube_community_post') as post, \
             patch('common.llm_client.generate_json') as model:
            result=youtube.prepare_youtube_content('youtube',channel,topic)
        self.assertEqual(result['status'],'prepared');self.assertFalse(result['publicationVerified'])
        reader.assert_called_once();facts.assert_called_once();post.assert_not_called();model.assert_not_called()

    def test_youtube_changed_prepared_document_cannot_reach_browser(self):
        from youtube_posting import posting as youtube
        key='a'*64;folder=self.root/'youtube_posting/output/prepared'/key
        write(folder/'document.json',{'title':'Changed payload','blocks':[]});write(folder/'prepared.json',{'documentSha256':'old'})
        write(self.root/'dashboard/data/youtube/preparation-jobs.json',{'jobs':{key:{'status':'prepared','channelHandle':'@yoon_autolab','topic':'Original question'}}})
        with patch.object(youtube,'ROOT_DIR',self.root),patch.object(youtube,'load_youtube_status',return_value={}), \
             patch('dashboard.common.ego_taskspace.native_publish_youtube_community_post') as post:
            result=youtube.publish_prepared_community()
        self.assertEqual(result['status'],'needs_attention');self.assertFalse(result['publicationVerified']);post.assert_not_called()

    def test_concurrent_youtube_consumer_keeps_verified_receipt_without_resubmitting(self):
        from youtube_posting import posting as youtube
        from common.editorial_recovery import digest
        key='b'*64;folder=self.root/'youtube_posting/output/prepared'/key
        doc={'title':'Reviewed question','blocks':[{'type':'text','text':'Complete reviewed answer.'}]};research={'sources':[]}
        receipt={'ok':True,'publicationVerified':True,'publicBodyMatched':True,'post':{'text':'Reviewed question\n\nComplete reviewed answer.'},'url':'https://www.youtube.com/post/VerifiedPost'}
        for name,data in [('document.json',doc),('research.json',research),('prepared.json',{'documentSha256':digest(doc),'researchSha256':digest(research),'policy':youtube.COMMUNITY_POLICY}),('intent.json',{'status':'published_verified'}),('publication-receipt.json',receipt)]:write(folder/name,data)
        write(self.root/'dashboard/data/youtube/preparation-jobs.json',{'jobs':{key:{'status':'prepared','channelHandle':'@yoon_autolab','topic':'Reviewed question'}}})
        with patch.object(youtube,'ROOT_DIR',self.root),patch.object(youtube,'load_youtube_status',return_value={}), \
             patch('dashboard.common.ego_taskspace.native_publish_youtube_community_post') as post:
            result=youtube.publish_prepared_community()
        self.assertTrue(result['reusedExistingReceipt']);post.assert_not_called()
        self.assertEqual(load(self.root/'dashboard/data/youtube/preparation-jobs.json')['jobs'][key]['status'],'published_verified')

    def test_pending_youtube_verification_never_downgrades_original_unknown_to_no_submission(self):
        from youtube_posting import posting as youtube
        from common.editorial_recovery import digest
        key='c'*64;folder=self.root/'youtube_posting/output/prepared'/key
        doc={'title':'Question','blocks':[{'type':'text','text':'Approved answer'}]};research={'sources':[]}
        for name,data in [('document.json',doc),('research.json',research),('prepared.json',{'documentSha256':digest(doc),'researchSha256':digest(research),'policy':youtube.COMMUNITY_POLICY}),('intent.json',{'status':'unknown','receipt':{'submissionDispatched':True}})]:write(folder/name,data)
        write(self.root/'dashboard/data/youtube/preparation-jobs.json',{'jobs':{key:{'status':'needs_reconciliation','channelHandle':'@yoon_autolab','topic':'Question'}}})
        before=(folder/'intent.json').read_bytes()
        with patch.object(youtube,'ROOT_DIR',self.root), \
             patch('dashboard.common.ego_taskspace.native_verify_youtube_community_post',return_value={'publicationVerified':False,'submissionDispatched':False,'verificationOnly':True}) as verify, \
             patch('dashboard.common.ego_taskspace.native_publish_youtube_community_post') as post:
            youtube.verify_youtube_content('youtube',key)
        self.assertEqual((folder/'intent.json').read_bytes(),before);post.assert_not_called();verify.assert_called_once()

    def test_native_youtube_verifier_uses_a_write_disabled_round_and_complete_public_proof(self):
        from common import ego_taskspace as ego
        receipt={'publicationVerified':True,'publicBodyMatched':True,'post':{'url':'https://www.youtube.com/post/Existing','text':'Complete answer','channelHandle':'@yoon_autolab'}}
        with patch.object(ego,'_native_publish_youtube_community_once',return_value=receipt) as round:
            result=ego.native_verify_youtube_community_post('@yoon_autolab','Complete answer')
        self.assertTrue(result['verificationOnly']);self.assertTrue(result['publicationVerified'])
        self.assertEqual(round.call_args.kwargs,{'verify_only':True})

    def test_summary_heading_context_does_not_approve_a_real_unsupported_timed_claim_or_repeat_failed_review(self):
        from common import content_quality as quality
        from unittest.mock import Mock
        import hashlib
        folder=self.root/'timed-claim';folder.mkdir()
        text='Official lending eligibility requires a separate assessment.'
        write(folder/'research.json',{'collectedAt':dt.datetime.now(dt.timezone.utc).isoformat(),
            'sources':[{'url':'https://www.gov.kr/policy','status':200,'text':text,'textSha256':hashlib.sha256(text.encode()).hexdigest()}]})
        doc={'title':'대출 승인 절차','contentHtml':'<h2>3초 요약</h2><p>대출 승인은 실제로 3초 이내 완료됩니다.</p>'}
        response={'status':'changes_required','issues':['Actual approval duration is unsupported'],'experienceHonest':True,'claimsComplete':False,
            'highRiskClaims':[],'experienceClaims':[],'hypotheticalClaims':[],'claimSources':[]}
        model=Mock(return_value=response)
        for _ in range(2):
            with self.assertRaises(ValueError):quality.ensure_publication_review(doc,folder,generate=model)
        self.assertEqual(model.call_count,1)
        self.assertIn('Observed document headings',model.call_args.args[0])
        self.assertIn('3초 요약',model.call_args.args[0])

    def test_scheduler_child_handoff_settled_releases_only_verified_pre_submission_failure_and_blocks_uncertain_states(self):
        from common import work_agenda as agendas, project_autonomy as autonomy, conference_dispatch as dispatch
        import hashlib
        data = self.root / 'dashboard/data'
        args = {'action': 'naver', 'account': 'soul5373', 'date': '2026-11-07', 'slot': '17:20'}
        child_id = hashlib.sha256(json.dumps(['parameters', args], sort_keys=True).encode()).hexdigest()
        owner_id = '2' * 64
        wrapper_id = '1' * 64
        chosen_id = '3' * 64
        req_id = 'goal:' + ('7' * 64) + ':097617f64133ba2097f1d33f'
        req_path = data / 'chats/staff-requests' / (hashlib.sha256(req_id.encode()).hexdigest() + '.json')
        rows_dir = data / 'publication-conferences/operations'
        child_path = rows_dir.parent / (child_id + '.json')

        base_child = {
            'agendaId': child_id,
            'kind': 'parameters',
            'arguments': args,
            'status': 'failed',
            'requestedAt': 1793981936.3,
            'completedAt': 1793985027.7,
            'businessAgendaId': owner_id,
            'errorType': 'RuntimeError',
            'failureReason': 'execution_error',
            'failureDiagnostic': {
                'errorType': 'RuntimeError',
                'errorMessage': 'Draft held: refusal, missing-research meta-text, or incomplete draft detected',
            },
        }
        write(child_path, base_child)

        initial_res = {
            'ok': True,
            'status': 'awaiting_completion',
            'project': 'naver_blog',
            'conferenceAgendaId': child_id,
            'conferenceRequestedAt': 1793981936.3,
            'publicationVerified': False,
            'executorReceipt': {
                'executor': 'ego-lite',
                'taskId': 'staff:test',
                'requestId': req_id,
                'agent': 'publi',
                'tool': 'run_project_cycle',
                'startedAt': '2026-11-06T16:50:59+00:00',
                'finishedAt': None,
                'status': 'awaiting_completion',
                'completed': False,
                'returnedAt': '2026-11-06T16:50:59+00:00',
            },
        }
        with patch.object(dispatch, 'QUEUE', rows_dir.parent):
            term_res, snap = autonomy.terminal_result(initial_res)
        self.assertTrue(term_res['executorReceipt']['completed'])
        self.assertEqual(term_res['executorReceipt']['finishedAt'], 1793985027.7)

        # Also verify legacy receipt shape where result lacked executorReceipt/conferenceRequestedAt
        legacy_term = {k: v for k, v in term_res.items() if k not in ('executorReceipt', 'conferenceRequestedAt')}
        base_receipt = {
            'requestId': req_id,
            'status': 'failed',
            'results': [{
                'agent': 'publi',
                'tool': 'run_project_cycle',
                'initialResult': initial_res,
                'result': legacy_term,
                'controllerSnapshot': snap,
                'hostReport': {'source': 'host', 'status': 'failed'},
            }],
        }
        write(req_path, base_receipt)

        base_journal = {
            'attempts': [{
                'account': 'soul5373',
                'publicationDate': '2026-11-07',
                'reserveTime': '2026-11-07 17:20',
                'scheduledSlot': '17:20',
                'submissionStarted': False,
                'preCommitIntent': False,
                'preSubmissionFailure': True,
                'phase': 'failed',
                'failureReason': 'Draft held: refusal, missing-research meta-text, or incomplete draft detected',
            }],
        }
        write(data / 'naver/automation-journal.json', base_journal)
        write(data / 'naver/public-verification.json', {'evidence': []})

        wrapper = {
            'id': wrapper_id,
            'kind': 'staff',
            'project': 'naver_blog',
            'status': 'blocked',
            'source': {'requestId': req_id, 'actions': [{'agent': 'publi', 'tool': 'run_project_cycle', 'args': {'project': 'naver_blog'}}]},
        }
        owner = {
            'id': owner_id,
            'kind': 'conference',
            'project': 'naver_blog',
            'status': 'blocked',
            'source': {'conferenceId': child_id, 'kind': 'parameters', 'arguments': args},
        }
        chosen = {
            'id': chosen_id,
            'kind': 'staff',
            'project': 'naver_blog',
            'status': 'queued',
            'source': {'requestId': 'new-req', 'actions': [{'agent': 'publi', 'tool': 'run_project_cycle', 'args': {'project': 'naver_blog'}}]},
        }
        agenda_map = {wrapper_id: wrapper, owner_id: owner, chosen_id: chosen}
        state = {'activeIds': [wrapper_id, owner_id], 'pending': [chosen_id]}

        with patch.object(agendas, 'DATA', data), patch.object(agendas, 'ROWS', rows_dir), \
             patch.object(agendas, 'get', side_effect=lambda k: copy.deepcopy(agenda_map.get(k, {}))), \
             patch.object(agendas, 'active_ids', return_value=[wrapper_id, owner_id]), \
             patch.object(agendas, 'active_rows', side_effect=lambda st=None: [copy.deepcopy(wrapper), copy.deepcopy(owner)]), \
             patch.object(agendas, 'running', return_value=[]):
            settled = agendas.scheduler_child_handoff_settled(wrapper)
            self.assertIsNotNone(settled)
            self.assertEqual(settled['businessAgendaId'], owner_id)
            self.assertFalse(agendas.occupies_lane(wrapper))
            admission = agendas.admission_state(chosen, state)
            self.assertTrue(admission['eligible'])
            self.assertEqual(admission['reason'], 'capacity_available')
            self.assertEqual(admission['occupiedResources'], 0)
            # Failure records remain intact and un-erased
            self.assertEqual(wrapper['status'], 'blocked')
            self.assertEqual(owner['status'], 'blocked')
            self.assertEqual(load(child_path)['status'], 'failed')
            self.assertEqual(load(req_path)['status'], 'failed')

            # Counterexample matrix: any uncertainty, submission start, pendingEffect, live process, or manual stop MUST block
            for child_override in (
                {'status': 'unknown'},
                {'status': 'submitting'},
                {'status': 'running'},
                {'pendingEffect': True},
                {'submissionStarted': True},
                {'preCommitIntent': True},
                {'manualStop': True},
                {'failureReason': 'screen_action_reconciliation_required'},
                {'requestedAt': 999999.0},
            ):
                write(child_path, {**base_child, **child_override})
                self.assertTrue(agendas.occupies_lane(wrapper), f'Failed to block child_override={child_override}')
                self.assertFalse(agendas.admission_state(chosen, state)['eligible'])
            write(child_path, base_child)

            for rec_override in (
                {'pendingEffect': True},
                {'status': 'unknown'},
                {'status': 'submitting'},
                {'status': 'awaiting_completion'},
            ):
                write(req_path, {**base_receipt, **rec_override})
                self.assertTrue(agendas.occupies_lane(wrapper), f'Failed to block rec_override={rec_override}')
                self.assertFalse(agendas.admission_state(chosen, state)['eligible'])
            write(req_path, base_receipt)

            for journal_override in (
                {'submissionStarted': True},
                {'preCommitIntent': True},
                {'phase': 'submitting'},
                {'phase': 'submission_unknown'},
            ):
                write(data / 'naver/automation-journal.json', {'attempts': [{**base_journal['attempts'][0], **journal_override}]})
                self.assertTrue(agendas.occupies_lane(wrapper), f'Failed to block journal_override={journal_override}')
                self.assertFalse(agendas.admission_state(chosen, state)['eligible'])
            write(data / 'naver/automation-journal.json', base_journal)

            # Live process on either wrapper or child conference owner must block
            with patch.object(agendas, 'running', side_effect=lambda r: [{'pid': 111}] if r.get('id') == wrapper_id else []):
                self.assertTrue(agendas.occupies_lane(wrapper))
                self.assertFalse(agendas.admission_state(chosen, state)['eligible'])
            with patch.object(agendas, 'running', side_effect=lambda r: [{'pid': 222}] if r.get('id') == owner_id else []):
                self.assertTrue(agendas.occupies_lane(wrapper))
                self.assertFalse(agendas.admission_state(chosen, state)['eligible'])

    def test_terminal_staff_and_threads_carry_release_lanes_while_preserving_protected_states(self):
        import hashlib
        from common import work_agenda as agendas
        import threads_posting.posting as tp
        data = self.root / 'dashboard/data'
        rows_dir = data / 'publication-conferences/operations'
        rows_dir.mkdir(parents=True, exist_ok=True)
        exec_done = {'completed': True, 'finishedAt': '2026-11-08T12:00:00+00:00'}
        cases = [
            ('no-work', [{'tool': 'run_project_cycle', 'args': {'project': 'naver_kin'}}],
             {'status': 'no_work', 'reason': 'no_eligible_concrete_work', 'protectedWork': [], 'publicationVerified': False, 'executorReceipt': {'requestId': 'no-work', **exec_done}}),
            ('norm-fail', [{'tool': 'repair_cf_normalization', 'args': {'project': 'cf_blog', 'domain': 'woorinote.kr'}}],
             {'status': 'failed', 'publicationVerified': False, 'executorReceipt': exec_done}),
            ('verify-fail', [{'tool': 'verify_cf_corrected_publication', 'args': {'project': 'cf_blog', 'url': 'https://www.smilenote.kr/a'}}],
             {'status': 'failed', 'executorReceipt': exec_done}),
            ('rec-held', [{'tool': 'recover_project_work', 'args': {'project': 'naver_blog', 'work_id': 'a' * 64}}],
             {'status': 'held', 'reason': 'same_work_not_eligible_or_requires_reconciliation', 'executorReceipt': exec_done}),
            ('runtime-obs', [{'tool': 'recover_project_runtime', 'args': {'project': 'naver_kin'}}],
             {'status': 'observed', 'executorReceipt': exec_done}),
        ]
        with patch.object(agendas, 'DATA', data), patch.object(agendas, 'ROWS', rows_dir), patch.object(agendas, 'running', return_value=[]):
            for req_id, actions, result in cases:
                row = {'id': hashlib.sha256(req_id.encode()).hexdigest(), 'kind': 'staff', 'status': 'recovering',
                       'source': {'requestId': req_id, 'actions': actions}}
                rpath = data / 'chats/staff-requests' / (hashlib.sha256(req_id.encode()).hexdigest() + '.json')
                rec = {'requestId': req_id, 'status': 'failed', 'results': [{'tool': actions[0]['tool'], 'result': result}]}
                write(rpath, rec)
                self.assertFalse(agendas.occupies_lane(row), req_id)
                write(rpath, {**rec, 'pendingEffect': True})
                self.assertTrue(agendas.occupies_lane(row), req_id)
        cfg_path = data / 'threads-automation.json'
        write(cfg_path, {**tp._threads_config_defaults(), 'preferredTimes': ['09:10', '21:00']})
        write(data / 'daily_schedule.json', {'operatingMode': 'adaptive', 'legacySlotsCarryThrough': '2026-11-07'})
        with patch('common.operating_plan.DATA', data), patch('common.operating_plan.enabled', return_value=True), \
             patch('common.operating_plan.allocations', return_value=[]):
            self.assertEqual(tp._threads_config_load(cfg_path)['preferredTimes'], ['09:10', '21:00'])
        with patch('common.operating_plan.DATA', data), patch('common.operating_plan.enabled', return_value=True), \
             patch('common.operating_plan.allocations', return_value=[{'slot': '14:10'}]):
            self.assertEqual(tp._threads_config_load(cfg_path)['preferredTimes'], ['14:10'])
        from common import operating_plan as op
        with patch.object(op, 'DATA', data), patch.object(op, 'cf_folder', return_value=data / 'cf-out'):
            self.assertTrue(op._can_activate_unallocated_cf({'domain': 'maxnote.kr', 'status': 'processing'}, '2026-11-08'))
            self.assertFalse(op._can_activate_unallocated_cf({'domain': 'maxnote.kr', 'status': 'processing', 'submissionStarted': True}, '2026-11-08'))
            self.assertFalse(op._can_activate_unallocated_cf({'domain': 'maxnote.kr', 'status': 'processing', 'allocationId': 'x'}, '2026-11-08'))


if __name__=='__main__':unittest.main()
