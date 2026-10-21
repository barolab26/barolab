import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from common import crew_chat_bridge as bridge


class CrewLifecycleTests(unittest.TestCase):
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
