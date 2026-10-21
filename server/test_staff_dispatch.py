"""Actual dispatch functions, isolated storage/providers; no live tools or messages."""
import ast
import hashlib
import json
import re
import tempfile
import time
import types
import unittest
from datetime import datetime
from pathlib import Path
from typing import Optional
from unittest.mock import Mock, patch


class StaffDispatchTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        names = {'validate_staff_actions', 'enqueue_staff_request', 'process_staff_request_once', 'staff_tool_reply',
                 '_repair_terminal_result','_finish_staff_repairs','staff_instruction'}
        tree = ast.parse(Path(__file__).with_name('agent_tools.py').read_text(encoding='utf-8'))
        self.scope = {'re': re, 'json': json, 'time': time, 'BASE_DIR':Path(self.temp.name), '_STAFF_CHILDREN':{},
                      'STAFF_REQUEST_DIR': Path(self.temp.name),
                      'STAFF_ROLES': ('jarvis','publi','trace','patch','doctor','radar'),
                      'CF_16_DOMAINS': ['example.com'],
                      'execute_agent_tool': Mock(return_value={'ok': True, 'status': 'observed', 'data': {'waiting': 2}})}
        exec(compile(ast.Module(body=[n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in names], type_ignores=[]), '<staff>', 'exec'), self.scope)
        for name in ('validate_staff_actions', 'execute_agent_tool'):
            p = patch('server.agent_tools.' + name, side_effect=lambda *a, _name=name, **kw: self.scope[_name](*a, **kw))
            p.start(); self.addCleanup(p.stop)
        self.emit = Mock(side_effect=lambda **kw: 'event-' + str(self.emit.call_count))
        p = patch('common.crew_chat_bridge.emit_work_event', self.emit); p.start(); self.addCleanup(p.stop)
        self.actions = [{'agent':'patch','tool':'read_agent_status','args':{}}]
        self.scope['staff_tool_reply'] = Mock(return_value={'reply':'대기 2건을 확인했으며 수리는 실행하지 않았습니다.',
            'route':{'events':[{'actualModel':'configured-model'}]}})

    def test_review_preserves_checked_approved_bytes_before_process(self):
        import sys, subprocess
        tree=ast.parse(Path(__file__).with_name('agent_tools.py').read_text(encoding='utf-8'))
        node=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='review_cf_existing')
        root=Path(self.temp.name); relative='output/national-certification-exam-schedule-registration-checklist/run-20261021-161201-409636'
        folder=root/'cf_posting'/relative; folder.mkdir(parents=True)
        for name in ('article.json','review.json','images.md'): (folder/name).write_bytes(b'approved')
        names=['cf_posting/pipeline_runner.py','cf_posting/domain_themes.py']
        for name in names:(root/name).write_bytes(b'# source')
        digest=lambda path:hashlib.sha256(path.read_bytes()).hexdigest()
        source=hashlib.sha256(json.dumps({n:digest(root/n) for n in names},sort_keys=True).encode()).hexdigest()
        handoff=Mock(); handoff.check.return_value=[{'fileHashes':{'images.md':digest(folder/'images.md')}}]
        handoff.file.side_effect=lambda name:folder/name
        process=Mock();process.pid=123;process.wait.return_value=0
        def start(*args,**kwargs):
            self.assertTrue((root/'.barolab/scratch/soulnote-crew-review/approved-bytes'/digest(folder/'images.md')).exists())
            self.assertIn('--prepare-only',args[0]);return process
        scope={'BASE_DIR':root,'Path':Path,'json':json,'sys':sys,'subprocess':subprocess,'_ego_popen':start,
               'get_kst_now':datetime.now,'_read_json':lambda *a:{'date':datetime.now().date().isoformat(),'items':[{'domain':'soulnote.kr','status':'review_required','artifactFolder':relative}]}}
        exec(compile(ast.Module(body=[node],type_ignores=[]),'<review>','exec'),scope)
        with patch.object(Path,'home',return_value=root),patch('cf_posting.pipeline_runner.Handoff',return_value=handoff):
            result=scope['review_cf_existing']('soulnote.kr',source,digest(folder/'article.json'),digest(folder/'review.json'))
        self.assertFalse(result['publicationAttempted']);handoff.check.assert_called_once()
        self.assertEqual((folder/'images.md').read_bytes(),b'approved')
        (folder/'handoff.json').write_bytes(b'original handoff');(folder/'photo-review.md').write_bytes(b'changed review')
        handoff.data={'stages':[{'fileHashes':{'article.json':digest(folder/'article.json')}} for _ in range(3)]}
        revision=hashlib.sha256(json.dumps({n:digest(folder/n) for n in ('handoff.json','images.md','photo-review.md')},sort_keys=True).encode()).hexdigest()
        with patch.object(Path,'home',return_value=root),patch('cf_posting.pipeline_runner.Handoff',return_value=handoff):
            revised=scope['review_cf_existing']('soulnote.kr',source,digest(folder/'article.json'),digest(folder/'review.json'),'asset_revalidation',revision)
        self.assertFalse(revised['publicationAttempted'])
        self.assertEqual((root/'.barolab/scratch/soulnote-crew-review/revision-before'/revision/'handoff.json').read_bytes(),b'original handoff')

    def test_prepare_selects_only_bound_same_goal_request(self):
        import sys, subprocess
        tree = ast.parse(Path(__file__).with_name('agent_tools.py').read_text(encoding='utf-8'))
        node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'prepare_cf_source_fact')
        root = Path(self.temp.name)
        source = root / 'cf_posting/pipeline_runner.py'; source.parent.mkdir(); source.write_text('# fixed')
        original = root / 'cf_posting/output/wrist-pain-when-bending-or-bearing-weight/run-20261021-171212-82b832'
        child = original / 'source-fact-continuation'; child.mkdir(parents=True)
        original.joinpath('prewriter-acquisition-request.json').write_text(json.dumps({'readerGoal':{'question':'fixed'},'articleSlug':'fixed'}))
        request = child / 'prewriter-acquisition-request.json'
        request.write_text(json.dumps({'readerGoal':{'question':'fixed'},'articleSlug':'fixed','missingInputs':['new']}))
        process = Mock(); process.pid=123; process.wait.return_value=0; popen=Mock(return_value=process)
        scope={'BASE_DIR':root,'Path':Path,'json':json,'sys':sys,'subprocess':subprocess,'_ego_popen':popen}
        exec(compile(ast.Module(body=[node],type_ignores=[]),'<prepare>','exec'),scope)
        digest=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
        with patch.object(Path,'home',return_value=root):
            result=scope['prepare_cf_source_fact'](digest(source),digest(request))
            self.assertFalse(result['publicationAttempted'])
            self.assertEqual(popen.call_args.args[0][-1],str(child))
            self.assertIn('--prepare-only',popen.call_args.args[0])
            popen.reset_mock(); request.write_text(json.dumps({'readerGoal':{'question':'changed'},'articleSlug':'fixed'}))
            self.assertEqual(scope['prepare_cf_source_fact'](digest(source),digest(request))['status'],'held')
            popen.assert_not_called()
            self.assertEqual(scope['prepare_cf_source_fact'](digest(source),'0'*64)['status'],'held')

    def test_fixed_cf_verification_preserves_nonzero_and_checks_source(self):
        import subprocess, sys
        tree = ast.parse(Path(__file__).with_name('agent_tools.py').read_text(encoding='utf-8'))
        node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'verify_cf_source_fact_fix')
        source = Path(self.temp.name) / 'cf_posting/pipeline_runner.py'
        source.parent.mkdir(); source.write_text('# fixed source')
        source.with_name('test_source_fact_recovery.py').write_text('# fixed tests')
        run = Mock(return_value=types.SimpleNamespace(returncode=1, stdout=b'failed', stderr=b''))
        scope = {'BASE_DIR':Path(self.temp.name),'sys':sys,'re':re,'subprocess':types.SimpleNamespace(run=run)}
        exec(compile(ast.Module(body=[node],type_ignores=[]),'<fixed-verification>','exec'),scope)
        verify = scope['verify_cf_source_fact_fix']
        self.assertEqual(verify('0'*64)['status'],'held'); run.assert_not_called()
        result = verify(hashlib.sha256(source.read_bytes()).hexdigest())
        self.assertFalse(result['ok']); self.assertEqual(result['exitCode'],1)
        self.assertFalse(result['publicationAttempted'])
        run.return_value = types.SimpleNamespace(returncode=0, stdout=b'', stderr=b'Ran 0 tests in 0.0s\n\nOK\n')
        self.assertFalse(verify(hashlib.sha256(source.read_bytes()).hexdigest())['ok'])
        run.return_value.stderr = b'Ran 2 tests in 0.1s\n\nOK\n'
        self.assertTrue(verify(hashlib.sha256(source.read_bytes()).hexdigest())['ok'])
        self.assertEqual(run.call_args.args[0][1:],['-m','unittest','cf_posting.test_source_fact_recovery'])
        renderer=source.with_name('domain_themes.py'); renderer.write_text('# renderer')
        source.with_name('test_category_preview.py').write_text('# fixed category tests')
        checked=verify(hashlib.sha256(source.read_bytes()).hexdigest(),hashlib.sha256(renderer.read_bytes()).hexdigest())
        self.assertTrue(checked['ok'])
        self.assertEqual(checked['testModules'],['cf_posting.test_source_fact_recovery','cf_posting.test_category_preview'])
        self.assertEqual(run.call_args.args[0][-1],'cf_posting.test_category_preview')
        self.assertEqual(verify(hashlib.sha256(source.read_bytes()).hexdigest(),'0'*64)['status'],'held')

    def test_fixed_cf_verification_is_patch_only_and_has_no_arbitrary_command(self):
        action = {'agent':'patch','tool':'verify_cf_source_fact_fix','args':{'source_sha256':'a'*64}}
        self.assertEqual(self.scope['validate_staff_actions']([action]), [action])
        self.assertIn('발행·재개는 실행하지 않습니다', self.scope['staff_instruction'](action)['text'])
        for bad in ({**action,'agent':'publi'}, {**action,'args':{'command':'publish'}},
                    {**action,'args':{'source_sha256':'../escape'}}):
            with self.assertRaises(ValueError): self.scope['validate_staff_actions']([bad])

    def test_request_ack_tool_actual_response_and_duplicate_once(self):
        enqueue = self.scope['enqueue_staff_request']
        row = enqueue('turn-1', self.actions)
        self.assertEqual(row['status'], 'queued')
        self.assertTrue(self.scope['process_staff_request_once']())
        self.assertFalse(self.scope['process_staff_request_once']())
        final = enqueue('turn-1', self.actions)
        self.assertEqual(final['status'], 'completed')
        receipt = final['results'][0]['result']['executorReceipt']
        self.assertEqual(receipt['executor'], 'ego-lite')
        self.assertEqual(receipt['taskId'], final['taskId'])
        self.assertEqual(receipt['requestId'], 'turn-1')
        self.assertTrue(receipt['completed'])
        self.assertEqual(final['results'][0]['responseEventId'], 'event-4')
        self.scope['execute_agent_tool'].assert_called_once_with('patch','read_agent_status')
        self.scope['staff_tool_reply'].assert_called_once()
        calls = [call.kwargs for call in self.emit.call_args_list]
        self.assertEqual([c['phase'] for c in calls], ['requested','progress','completed','completed'])
        self.assertEqual(calls[1]['parent_request_id'], row['requests'][0])
        self.assertEqual(calls[-1]['requested_to'], 'jarvis')
        self.assertEqual(calls[-1]['model'], 'configured-model')
        self.assertEqual(row['instructions'][0]['source'],'host_structured_instruction')
        self.assertIn('@패치',calls[0]['output_kind'])
        self.assertNotIn('read_agent_status',calls[0]['output_kind'])
        self.assertEqual(row['instructions'][0]['tool'],'read_agent_status')
        self.assertIn('발행·재시작·수리는 하지 않습니다',calls[0]['output_kind'])
        self.assertEqual(calls[1]['output_kind'],'지시를 접수했고 운영 상태 확인을 시작했습니다.')
        self.assertIn('도구 실행 기록',calls[2]['output_kind'])
        self.assertEqual([c['message_kind'] for c in calls],['host_instruction','host_ack','tool_result','staff_reply'])
        self.assertEqual(calls[-1]['output_kind'],self.scope['staff_tool_reply'].return_value['reply'])

    def test_repair_instruction_names_scope_without_exposing_private_proof(self):
        action={'agent':'patch','tool':'repair_cf_known_failure',
                'args':{'domain':'example.com','evidencePath':'/private/proof.json','evidenceSha256':'a'*64}}
        text=self.scope['staff_instruction'](action)['text']
        self.assertIn('example.com',text)
        self.assertIn('기존 검수와 중복 방지 확인을 통과한 경우에만',text)
        self.assertNotIn('repair_cf_known_failure',text)
        self.assertNotIn('구조화',text)
        self.assertNotIn('/private',text)
        self.assertLessEqual(len(text),160)

    def test_unknown_publish_recursive_duplicate_and_id_conflict_are_rejected(self):
        validate = self.scope['validate_staff_actions']
        for actions in ([], self.actions * 2, [{'agent':'publi','tool':'run_cf_publish','args':{}}],
                        [{'agent':'jarvis','tool':'dispatch_multi_agent_action','args':{}}]):
            with self.assertRaises(ValueError): validate(actions)
        self.scope['enqueue_staff_request']('turn-1', self.actions)
        with self.assertRaises(ValueError):
            self.scope['enqueue_staff_request']('turn-1', [{'agent':'trace','tool':'read_agent_status','args':{}}])
        self.scope['execute_agent_tool'].assert_not_called()

    def test_response_failure_does_not_erase_tool_return_or_retry(self):
        self.scope['staff_tool_reply'].side_effect = RuntimeError('provider unavailable')
        self.scope['enqueue_staff_request']('turn-1', self.actions)
        self.scope['process_staff_request_once']()
        row = self.scope['enqueue_staff_request']('turn-1', self.actions)
        self.assertEqual(row['status'], 'failed')
        self.assertTrue(row['results'][0]['result']['ok'])
        self.assertEqual(row['results'][0]['responseError'], 'RuntimeError')
        self.assertFalse(self.scope['process_staff_request_once']())

    def test_running_child_is_not_completed_repair_and_bad_file_does_not_starve(self):
        bad = Path(self.temp.name)/'000-invalid.json'
        bad.write_text('{invalid', encoding='utf-8')
        self.scope['execute_agent_tool'].return_value = {'ok':True,'status':'running','pid':123}
        actions=[{'agent':'patch','tool':'repair_cf_known_failure','args':{'domain':'example.com'}}]
        self.scope['enqueue_staff_request']('turn-1', actions)
        self.scope['process_staff_request_once']()
        self.assertEqual(self.scope['enqueue_staff_request']('turn-1',actions)['status'],'awaiting_completion')
        self.assertEqual(bad.read_text(encoding='utf-8'),'{invalid')

    def test_staff_response_uses_configured_brain_and_records_actual_model(self):
        tree=ast.parse(Path(__file__).with_name('agent_tools.py').read_text(encoding='utf-8'))
        node=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='staff_tool_reply')
        scope={'re':re,'json':json}
        exec(compile(ast.Module(body=[node],type_ignores=[]),'<response>','exec'),scope)
        def generate(prompt,**kwargs):
            self.assertEqual(kwargs['provider'],'codex')
            self.assertEqual(kwargs['model_override'],'configured-patch')
            self.assertIn('two complete sentences within 80 characters',prompt)
            self.assertIn('Start the reply with @자비스',prompt)
            self.assertIn('never truncate a sentence',prompt)
            self.assertIn('must retain their source date and historical scope',prompt)
            self.assertIn('never describe stale statistics as current failures',prompt)
            kwargs['observer']('codex','configured-patch','returned',actual_model='actual-patch')
            return {'reply':'대기 상태를 읽었으며 수리 실행은 하지 않았습니다.'}
        with patch('common.llm_settings.get_agent_brain',return_value={'provider':'codex','model':'configured-patch'}),patch('common.llm_client.generate_json',side_effect=generate):
            result=scope['staff_tool_reply']('patch','task',self.actions[0],{'status':'observed'})
        self.assertEqual(result['route']['events'][0]['actualModel'],'actual-patch')
        def unfinished(prompt,**kwargs):
            kwargs['observer']('codex','configured-patch','returned',actual_model='actual-patch')
            return {'reply':'실제 작업 정상 수행, 오류 복구 및'}
        with patch('common.llm_settings.get_agent_brain',return_value={'provider':'codex','model':'configured-patch'}),patch('common.llm_client.generate_json',side_effect=unfinished):
            with self.assertRaises(ValueError):
                scope['staff_tool_reply']('patch','task',self.actions[0],{'status':'observed'})

    def test_running_repair_terminal_rejection_is_observed_once_without_relaunch(self):
        task='cf-repair:2026-10-21:example.com'
        fp=hashlib.sha256((task+'|editorial_seed_pinned_as_keyword').encode()).hexdigest()
        ledger=Path(self.temp.name)/'server/data/repair-workflows'/(fp+'.json')
        ledger.parent.mkdir(parents=True)
        result={'ok':True,'tool':'repair_cf_known_failure','status':'running','pid':123,
                'controllerTaskId':task,'controllerFingerprint':fp,'controllerLedgerPath':str(ledger)}
        self.scope['execute_agent_tool'].return_value=result
        actions=[{'agent':'patch','tool':'repair_cf_known_failure','args':{'domain':'example.com'}}]
        self.scope['enqueue_staff_request']('turn-1',actions)
        self.scope['process_staff_request_once']()
        raw=json.dumps({'taskId':task,'fingerprint':fp,'status':'review_rejected','resumeAttempted':False}).encode()
        ledger.write_bytes(raw)
        self.assertTrue(self.scope['process_staff_request_once']())
        row=self.scope['enqueue_staff_request']('turn-1',actions)
        self.assertEqual(row['status'],'held')
        self.assertEqual(row['results'][0]['result']['controllerStatus'],'review_rejected')
        self.assertEqual(row['results'][0]['result']['controllerEvidenceSha256'],hashlib.sha256(raw).hexdigest())
        initial = row['results'][0]['initialResult']
        self.assertEqual({k:v for k,v in initial.items() if k != 'executorReceipt'}, result)
        self.assertFalse(initial['executorReceipt']['completed'])
        self.assertEqual(ledger.read_bytes(),raw)
        self.scope['execute_agent_tool'].assert_called_once()
        self.assertEqual(self.scope['staff_tool_reply'].call_count,2)
        self.assertFalse(self.scope['process_staff_request_once']())

    def test_missing_terminal_and_unobserved_process_is_unknown_not_success(self):
        task='cf-repair:2026-10-21:example.com'
        fp=hashlib.sha256((task+'|editorial_seed_pinned_as_keyword').encode()).hexdigest()
        path=Path(self.temp.name)/'server/data/repair-workflows'/(fp+'.json')
        result={'controllerTaskId':task,'controllerFingerprint':fp,'controllerLedgerPath':str(path),'pid':123}
        observed,snapshot=self.scope['_repair_terminal_result'](result)
        self.assertEqual(observed['status'],'unknown')
        self.assertIsNone(snapshot)
        with self.assertRaises(ValueError):
            self.scope['_repair_terminal_result']({**result,'controllerFingerprint':'wrong'})

    def test_host_repair_proof_binds_current_schedule_and_blocks_changed_bytes(self):
        tree=ast.parse(Path(__file__).with_name('agent_tools.py').read_text(encoding='utf-8'))
        node=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='repair_cf_known_failure')
        root=Path(self.temp.name)
        schedule={'date':'2026-10-21','items':[{'domain':'example.com','status':'failed'}]}
        schedule_path=root/'cf_posting/data/daily_schedule.json';schedule_path.parent.mkdir(parents=True)
        schedule_path.write_text(json.dumps(schedule),encoding='utf-8')
        module=types.ModuleType('cf_posting.pipeline_runner')
        module.editorial_seed_failure=lambda item: True
        module._item_digest=lambda item: hashlib.sha256(json.dumps(item,sort_keys=True).encode()).hexdigest()
        proof={'domain':'example.com','taskId':'cf-repair:2026-10-21:example.com',
            'failureType':'editorial_seed_pinned_as_keyword','itemSha256':module._item_digest(schedule['items'][0]),
            'scheduleSha256':hashlib.sha256(schedule_path.read_bytes()).hexdigest()}
        raw=json.dumps(proof).encode();sha=hashlib.sha256(raw).hexdigest()
        path=root/'.barolab/project-monitor/repair-candidates'/(sha+'.json');path.parent.mkdir(parents=True);path.write_bytes(raw)
        spawn=Mock(return_value=types.SimpleNamespace(pid=123))
        scope={**self.scope,'Path':Path,'Dict':dict,'Any':object,'_read_json':lambda *a:schedule,
            'get_kst_now':lambda:datetime(2026,10,21),'sys':types.SimpleNamespace(executable='python'),
            '_ego_popen':spawn, 'subprocess':types.SimpleNamespace(Popen=spawn,STDOUT=-2,CREATE_NO_WINDOW=0)}
        exec(compile(ast.Module(body=[node],type_ignores=[]),'<repair-tool>','exec'),scope)
        with patch.dict('sys.modules',{'cf_posting.pipeline_runner':module}),patch.object(Path,'home',return_value=root):
            path.write_bytes(raw+b' ')
            self.assertEqual(scope['repair_cf_known_failure']('example.com',str(path),sha)['status'],'held')
            spawn.assert_not_called()
            path.write_bytes(raw)
            result=scope['repair_cf_known_failure']('example.com',str(path),sha)
        self.assertEqual(result['status'],'running')
        self.assertEqual(result['controllerTaskId'],proof['taskId'])
        spawn.assert_called_once()

    def test_interrupted_claim_is_unknown_without_reexecution(self):
        self.scope['enqueue_staff_request']('turn-1', self.actions)
        path = next(Path(self.temp.name).glob('*.json'))
        row = json.loads(path.read_text(encoding='utf-8'))
        row.update(status='acknowledged', claimedAt=time.time()-1801)
        path.write_text(json.dumps(row), encoding='utf-8')
        self.assertFalse(self.scope['process_staff_request_once']())
        self.assertEqual(json.loads(path.read_text(encoding='utf-8'))['status'],'unknown')
        self.scope['execute_agent_tool'].assert_not_called()

    def test_actual_chat_structured_reply_enqueues_but_mentions_do_not(self):
        tree = ast.parse(Path(__file__).with_name('chat_room.py').read_text(encoding='utf-8'))
        scope = {'Optional':Optional, 're':re, 'hashlib':hashlib}
        node = next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='_call_chat_llm')
        exec(compile(ast.Module(body=[node],type_ignores=[]),'<chat>', 'exec'),scope)
        module = types.ModuleType('agent_tools')
        module.enqueue_staff_request = self.scope['enqueue_staff_request']
        receipts=[]
        response={'reply':'패치에게 상태 확인을 요청합니다.',
                  'actions':[{'agent':'patch','tool':'read_agent_status','domain':''}]}
        with patch.dict('sys.modules', {'agent_tools':module}), patch('common.llm_client.generate_json',return_value=response):
            scope['_call_chat_llm']('system','user',agent_slug='jarvis',staff_request_id='turn-1',dispatch_receipts=receipts)
        self.assertEqual(receipts[0]['status'],'queued')
        with patch('common.llm_client.generate_json',return_value={'reply':'@패치 과거 보고입니다.'}):
            scope['_call_chat_llm']('system','user',agent_slug='jarvis')
        self.assertEqual(len(list(Path(self.temp.name).glob('*.json'))),1)
        forbidden={'reply':'수리 요청','actions':[{'agent':'patch','tool':'repair_cf_known_failure','domain':'example.com'}]}
        with patch.dict('sys.modules', {'agent_tools':module}),patch('common.llm_client.generate_json',return_value=forbidden):
            self.assertIsNone(scope['_call_chat_llm']('system','read only',agent_slug='jarvis',staff_request_id='turn-2'))
        self.assertEqual(len(list(Path(self.temp.name).glob('*.json'))),1)

    def test_queued_reply_is_pending_not_missing_parameters_or_completed(self):
        tree=ast.parse(Path(__file__).with_name('chat_room.py').read_text(encoding='utf-8'))
        node=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='_guard_dispatch_reply')
        guard=Mock(return_value='unmatched')
        scope={'_enforce_status_only_guard':guard}
        exec(compile(ast.Module(body=[node],type_ignores=[]),'<guard>','exec'),scope)
        reply=scope['_guard_dispatch_reply']('패치에게 확인을 요청합니다.','읽기 요청',
            [{'tool':'staff_dispatch','status':'queued'}],False)
        self.assertEqual(reply,'패치에게 확인을 요청합니다.')
        self.assertNotIn('파라미터',reply)
        self.assertNotIn('구조화 지시',reply)
        guard.assert_not_called()
        self.assertEqual(scope['_guard_dispatch_reply']('text','request',[],False),'unmatched')



if __name__ == '__main__': unittest.main()
