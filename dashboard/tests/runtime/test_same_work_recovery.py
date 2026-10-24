import copy
import hashlib
import json
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import Mock, patch
from common import project_autonomy as autonomy, repair_workflow as repair
from common import conference_dispatch as conference
from server import agent_tools as tools, project_monitor as monitor


class SameWorkRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.state=self.root/'state.json'
        root_patch=patch.object(autonomy,'ROOT',self.root);root_patch.start();self.addCleanup(root_patch.stop)
        self.config=self.root/'config.json';self.config.write_text(json.dumps({'enabled':True,'projects':['naver_blog','cf_blog']}))
        self.target={'workId':'a'*64,'project':'naver_blog','date':'2026-10-25','identity':'soultin','slot':'07:40','status':'failed','submissionStarted':False}

    def test_exact_request_deduplicates_without_model_or_engine_submission(self):
        with patch.object(autonomy,'CONFIG',self.config), patch.object(autonomy,'STATE',self.state), \
             patch.object(autonomy,'recoverable_work',return_value=[self.target]), \
             patch.object(conference,'request',return_value={'status':'conference_requested','agendaId':'b'*64}) as request:
            for _ in range(2):
                result=tools._execute_agent_tool('publi','recover_project_work',project='naver_blog',work_id='a'*64)
                self.assertEqual(result['status'],'awaiting_completion')
                self.assertEqual(result['conferenceAgendaId'],'b'*64)
                self.assertFalse(result['publicationVerified'])
            request.assert_called_once_with('parameters',{'action':'naver','date':'2026-10-25','account':'soultin','slot':'07:40'})
            with self.assertRaises(ValueError):tools._execute_agent_tool('patch','recover_project_work',project='naver_blog',work_id='a'*64)
        with self.assertRaises(ValueError):autonomy.recover_project_work('naver_blog','../escape')

    def test_ineligible_same_work_is_held_and_never_runs_whole_channel(self):
        with patch.object(autonomy,'CONFIG',self.config), patch.object(autonomy,'STATE',self.state), \
             patch.object(autonomy,'recoverable_work',return_value=[]), patch.object(conference,'request') as request:
            result=autonomy.recover_project_work('naver_blog','a'*64)
        self.assertEqual(result['status'],'held');request.assert_not_called()

    def test_candidates_preserve_schedule_submission_receipts_and_quality_holds(self):
        from common import channel_parameters as params
        now=datetime.now(params.KST);day=(now+timedelta(days=1)).date().isoformat()
        target={**self.target,'date':day}
        folder=self.root/'output';folder.mkdir()
        plan={'effectiveDate':now.date().isoformat(),'naver':{'soultin':{'slots':['07:40']}},'cf':{}}
        with patch.object(autonomy,'STATE',self.state),patch('common.channel_parameters.policy',return_value=plan), \
             patch('common.channel_parameters.folder_for',return_value=folder), \
             patch('common.recovery_evidence.artifact_folder',return_value=folder), \
             patch('common.recovery_evidence.failure_targets',return_value=[target]):
            self.assertEqual(len(autonomy.recoverable_work('naver_blog')),1)
            for change in ({'submissionStarted':True},{'status':'review_required'},{'slot':'19:30'},{'date':'2020-01-01'}):
                with patch('common.recovery_evidence.failure_targets',return_value=[{**target,**change}]):
                    self.assertEqual(autonomy.recoverable_work('naver_blog'),[])
            (folder/'reservation-evidence.json').write_text('{"submissionStatus":"submission_unknown"}')
            self.assertEqual(autonomy.recoverable_work('naver_blog'),[])

    def test_cf_inspection_cannot_read_unrelated_naver_owner_summary(self):
        row={'id':'cf_blog','status':'attention'}
        with patch('server.project_health.observed_projects',return_value=[row]), \
             patch('common.recovery_evidence.failure_targets',return_value=[]), patch.object(tools,'read_publi_data') as broad:
            result=tools._execute_agent_tool('publi','read_agent_status',project='cf_blog')
        self.assertEqual(result['data']['observation'],row);broad.assert_not_called()
        self.assertEqual(monitor.action_for_triage({'id':'cf_blog','ownerAgentIds':['publi']},{'decision':'inspect'},[])['args'],{'project':'cf_blog'})

    def test_presubmission_exception_is_work_blocked_not_published_failure(self):
        response={'reply':'@팀장 CF 블로그 원고 준비가 중단됐습니다. 제출 기록을 확인하겠습니다.','route':{'events':[{'actualModel':'fixture'}]}}
        with patch('agents.agent_tools.staff_tool_reply',return_value=response) as model,patch('common.crew_chat_bridge.emit_work_event') as event:
            result=conference.report_outcome({'errorType':'RuntimeError'},'fixture',{'channel':'CF 블로그','account':'example.com'})
        self.assertEqual(result['outcome'],'작업 차단')
        self.assertEqual(result['channel'],'CF 블로그')
        self.assertEqual(model.call_args.args[2]['tool'],'channel_execution')
        self.assertNotIn('게시 실패',event.call_args.kwargs['report']['status'])

    def test_blocked_legacy_dispatch_is_replaced_once_without_replaying_phase(self):
        request_id='legacy-unsupported'
        request_dir=self.root/'staff';request_dir.mkdir()
        (request_dir/(hashlib.sha256(request_id.encode()).hexdigest()+'.json')).write_text(json.dumps({'status':'failed','results':[{'tool':'advance_project_recovery','result':{'status':'unsupported'}}]}))
        path=self.root/'repair.json'
        row={'type':'project_recovery_v1','taskId':'fixture','planSha256':'a'*64,'status':'ready','step':'discover','steps':{},'plan':{},'dispatches':{'discover':{'requestId':request_id}}}
        path.write_text(json.dumps(row))
        def enqueue(request, actions):return {'requestId':request}
        with patch.object(repair,'ROOT',self.root),patch.object(tools,'STAFF_REQUEST_DIR',request_dir), \
             patch.object(tools,'enqueue_staff_request',side_effect=enqueue) as send, \
             patch.object(repair,'recovery_expected_actor',return_value='patch'):
            self.assertTrue(repair.dispatch_project_recovery_once())
            self.assertFalse(repair.dispatch_project_recovery_once())
        self.assertEqual(send.call_count,1)
        saved=json.loads(path.read_bytes())
        self.assertTrue(saved['unsupportedDispatchReplaced'])
        self.assertEqual(saved['supersededDispatches'][0]['requestId'],request_id)
        self.assertEqual(saved['steps'],{})
        self.assertEqual(send.call_args.args[1][0]['tool'],'advance_project_recovery')

    def test_chat_team_lead_can_request_actual_recovery_tools_with_host_bound_work(self):
        import ast,re
        from typing import Optional
        source=Path(tools.__file__).parent/'chat_room.py'
        tree=ast.parse(source.read_text())
        scope={'Optional':Optional,'re':re,'hashlib':hashlib,'json':json}
        function=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='_call_chat_llm')
        exec(compile(ast.Module(body=[function],type_ignores=[]),'<chat-tools>','exec'),scope)
        response={'reply':'@퍼블리, 해당 실패 슬롯의 복구를 요청합니다.','actions':[{'agent':'publi','tool':'recover_project_work','domain':'','project':'naver_blog','work_id':'a'*64}]}
        with patch('common.project_autonomy.recoverable_work',side_effect=lambda project:[self.target] if project=='naver_blog' else []), \
             patch('common.llm_client.generate_json',return_value=response) as model, \
             patch('agent_tools.enqueue_staff_request',return_value={'status':'queued','taskId':'fixture','requestId':'fixture'}) as enqueue:
            self.assertIsNotNone(scope['_call_chat_llm']('system','해결해주세요',agent_slug='jarvis',staff_request_id='fixture',allow_guarded_repair=True))
            self.assertEqual(enqueue.call_args.args[1],[{'agent':'publi','tool':'recover_project_work','args':{'project':'naver_blog','work_id':'a'*64}}])
            supported=model.call_args.kwargs['response_schema']['properties']['actions']['items']['properties']['tool']['enum']
            self.assertIn('recover_project_work',supported)
            self.assertIn('recover_project_runtime',supported)
            enqueue.reset_mock()
            self.assertIsNone(scope['_call_chat_llm']('system','상태 확인',agent_slug='jarvis',staff_request_id='fixture',allow_guarded_repair=False))
            enqueue.assert_not_called()

    def test_failed_conference_has_only_one_bounded_retry_and_retains_history(self):
        queue=self.root/'queue';queue.mkdir()
        (queue/('b'*64+'.json')).write_text(json.dumps({'status':'failed','retryAt':0}))
        with patch.object(autonomy,'CONFIG',self.config),patch.object(autonomy,'STATE',self.state), \
             patch.object(autonomy,'recoverable_work',return_value=[self.target]),patch.object(conference,'QUEUE',queue), \
             patch.object(conference,'request',return_value={'status':'conference_requested','agendaId':'b'*64}) as request:
            for _ in range(3):result=autonomy.recover_project_work('naver_blog','a'*64)
        self.assertEqual(request.call_count,2)
        self.assertEqual(result['attempts'],2)
        self.assertEqual(len(result['attemptHistory']),1)
