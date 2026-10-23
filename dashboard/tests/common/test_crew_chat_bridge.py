import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from common import crew_chat_bridge as bridge


class CrewLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.intake=patch('common.repair_workflow.record_failed_event',return_value=None)
        self.intake.start()
        self.addCleanup(self.intake.stop)

    def test_nested_and_skip_memory_calls_have_one_pair_without_content(self):
        from common.llm_client import memory_call
        @memory_call
        def inner(prompt):
            return {'secret-response':'private'}
        @memory_call
        def outer(prompt):
            return inner(prompt)
        with patch.object(bridge,'_deliver') as deliver:
            result = outer('secret prompt', _skip_memory=True, crew_stage='extract',
                           crew_actor='hermes-learning',crew_actor_label='Hermes')
        self.assertEqual(result, {'secret-response':'private'})
        rows=[call.args[0] for call in deliver.call_args_list]
        self.assertEqual([row['phase'] for row in rows],['requested','completed'])
        self.assertEqual(rows[1]['parentRequestId'], rows[0]['eventId'])
        self.assertEqual(rows[0]['taskId'],rows[1]['taskId'])
        self.assertNotIn('secret',json.dumps(rows))
        self.assertEqual(rows[0]['who'],'hermes-learning')

    def test_staff_ownership_preserves_tool_origin_and_unknown(self):
        for actor,owner in [('cf-image-maker','publi'),('kin-pipeline','publi'),('threads-pipeline','publi'),('naver-keyword-selector','radar'),('patch','patch'),('common-runner','')]:
            with patch.object(bridge,'_deliver') as deliver:
                bridge.emit_work_event(actor=actor,actor_label=actor,task_id='t',phase='completed')
            event=deliver.call_args.args[0]
            self.assertEqual(event['who'],actor)
            self.assertEqual(event['ownerAgent'],owner)
            self.assertEqual(event['toolActor'],'' if actor=='patch' else actor)
        @bridge.model_crew_call
        def call(prompt): return {'passed':False}
        with patch.object(bridge,'_deliver') as deliver:
            call('private',crew_owner_agent='doctor')
        self.assertTrue(all(c.args[0]['ownerAgent']=='doctor' and c.args[0]['who']=='common-runner' for c in deliver.call_args_list))
        with self.assertRaises(ValueError):bridge.work_actor_owner('patch','publi')
        with self.assertRaises(ValueError):bridge.work_actor_owner('common-runner','invented')
        with patch.object(bridge,'_deliver') as deliver:
            bridge.emit_work_event(actor='jarvis',actor_label='자비스',task_id='t',phase='requested',message_kind='host_instruction')
        self.assertEqual(deliver.call_args.args[0]['messageKind'],'host_instruction')
        with self.assertRaises(ValueError):
            bridge.emit_work_event(actor='jarvis',actor_label='자비스',task_id='t',phase='requested',message_kind='invented')

    def test_channel_model_calls_use_the_assigned_staff_owner(self):
        @bridge.model_crew_call
        def call(prompt, agent_slot):return {'ok':True}
        for slot,owner in [('cf_pipeline','publi'),('kin_pipeline','publi'),('patch','patch'),('unknown-slot','')]:
            with patch.object(bridge,'_deliver') as deliver:
                call('private',agent_slot=slot)
            self.assertTrue(all(row.args[0]['ownerAgent']==owner for row in deliver.call_args_list))

    def test_run_identity_target_and_actual_result_shape(self):
        @bridge.model_crew_call
        def call(prompt, model=None):
            return {'status':'private value','unsafe key!':'private'}
        task=bridge.work_task_id(Path('output')/'sample')
        self.assertEqual(task,bridge.work_task_id(Path('output')/'sample'/'model-audit'/'writer'))
        with patch.object(bridge,'_deliver') as deliver:
            call('private',model='chosen-model',crew_task_id=task)
        rows=[c.args[0] for c in deliver.call_args_list]
        self.assertTrue(all(r['taskId']==task for r in rows))
        self.assertEqual(rows[0]['requestedTo'],'model:chosen-model')
        self.assertIn('dict fields:status',rows[1]['outputKind'])
        self.assertNotIn('private',json.dumps(rows))
        self.assertNotIn('unsafe key',json.dumps(rows))

    def test_only_fixed_result_values_are_displayed(self):
        @bridge.model_crew_call
        def call(prompt):
            return {'classification':'held','status':'private raw text','state':'waiting',
                    'decision':'reject','passed':False,'reason':'private details'}
        with patch.object(bridge,'_deliver') as deliver:
            call('private prompt')
        output=deliver.call_args.args[0]['outputKind']
        self.assertIn('classification=held',output)
        self.assertIn('state=waiting',output)
        self.assertIn('decision=reject',output)
        self.assertIn('passed=false',output)
        self.assertNotIn('private',output)
        self.assertNotIn('status=',output)

    def test_failure_is_reported_without_exception_body_and_reraised(self):
        @bridge.model_crew_call
        def fail(prompt):
            raise RuntimeError('private failure body')
        with patch.object(bridge,'_deliver') as deliver:
            with self.assertRaises(RuntimeError): fail('private prompt')
        rows=[call.args[0] for call in deliver.call_args_list]
        self.assertEqual([r['phase'] for r in rows],['requested','failed'])
        self.assertNotIn('private',json.dumps(rows))

    def test_offline_delivery_preserves_atomic_event_not_room_ledger(self):
        with tempfile.TemporaryDirectory() as directory:
            outbox=Path(directory)/'outbox'
            with patch.object(bridge,'OUTBOX_DIR',outbox), patch.object(bridge.urllib.request,'urlopen',side_effect=OSError('offline')):
                event=bridge.emit_work_event(actor='runner',actor_label='Runner',task_id='run1',phase='progress',stage='reading')
            files=list(outbox.glob('*.json'))
            self.assertEqual(len(files),1)
            row=json.loads(files[0].read_text(encoding='utf-8'))
            self.assertEqual(row['eventId'],event)
            self.assertEqual(row['stage'],'reading')
            self.assertFalse(list(outbox.glob('*.tmp')))

    def test_legacy_outbox_is_separate_from_canonical_events(self):
        with tempfile.TemporaryDirectory() as directory:
            outbox=Path(directory)/'outbox'
            with patch.object(bridge,'OUTBOX_DIR',outbox), patch.object(bridge.urllib.request,'urlopen',side_effect=OSError('offline')):
                event=bridge.emit_pipeline_crew_message('patch','Legacy status',msg_id='legacy-test')
            self.assertEqual(event,'legacy-test')
            self.assertEqual(list(outbox.glob('*.json')),[])
            files=list((outbox/'legacy').glob('*.json'))
            self.assertEqual(len(files),1)
            self.assertEqual(json.loads(files[0].read_text(encoding='utf-8'))['id'],event)

    def test_canonical_endpoint_and_non_model_metadata(self):
        with patch.object(bridge.urllib.request,'urlopen') as send:
            send.return_value.__enter__.return_value.status=200
            bridge.emit_work_event(actor='worker',actor_label='Worker',task_id='run',phase='completed',stage='read-files')
        request=send.call_args.args[0]
        self.assertTrue(request.full_url.endswith('/api/chat/work-event'))
        self.assertEqual(json.loads(request.data)['model'],'')

if __name__ == '__main__': unittest.main()
