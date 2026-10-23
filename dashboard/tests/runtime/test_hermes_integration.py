"""Bounded provider and outcome hooks; no external model, publishing or real memory writes."""
import ast
import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from common import hermes_memory, llm_client

class MemoryIntegrationTests(unittest.TestCase):

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = hermes_memory.HermesMemory(Path(self.temp.name) / 'memories')
        self.store_patch = patch.object(hermes_memory, '_store', self.store)
        self.store_patch.start()
        self.addCleanup(self.store_patch.stop)
        self.addCleanup(self.store.close)

    def test_kin_writing_policy_applies_at_actual_shared_boundary(self):
        from common.kin_answering import POLICY_ID
        policy = '안정적인 일반 지식은 직접 짧게 답하고 관련 글만 안내한다. 소유 관계와 사실 확인은 보존한다. ' * 3
        evidence = '{"question_id":"actual-fixture","sources_by_article":[]}'
        old = 'Return question_id from sources_by_article.\nEVIDENCE_JSON:\n' + evidence
        captured = []
        @llm_client.memory_call
        def provider(prompt, agent_slot):
            captured.append(prompt)
            return {'ok':True}
        index = {'operatingDirectives':[{'id':POLICY_ID,'active':True,'promptPolicy':policy}]}
        with patch('dashboard.agents.synapse.recipe',return_value=''), patch('dashboard.agents.synapse.cached_index',return_value=index):
            provider(old, agent_slot='kin_pipeline', memory_read_only=True)
        self.assertIn(policy,captured[0])
        self.assertTrue(captured[0].endswith(evidence))
        self.assertNotIn('Return question_id from sources_by_article.',captured[0])

    def test_nested_provider_calls_inject_once_and_freeze_task_snapshot(self):
        self.store.memory('memory', 'add', text='Initial durable rule')
        prompts = []

        @llm_client.memory_call
        def direct_cli(prompt):
            prompts.append(prompt)
            return {'ok': True}

        @llm_client.memory_call
        def configured_provider(prompt):
            return direct_cli(prompt)
        with llm_client.memory_session('one-task', 'writer'):
            configured_provider('task')
            self.store.memory('memory', 'add', text='Later reviewer update')
            configured_provider('task')
        self.assertEqual(prompts[0], prompts[1])
        self.assertEqual(prompts[0].count('<project-memory>'), 1)
        self.assertNotIn('Later reviewer update', prompts[1])
        with llm_client.memory_session('next-task', 'writer'):
            configured_provider('task')
        self.assertIn('Later reviewer update', prompts[2])

    def test_read_only_memory_injects_and_traces_without_recording_episode(self):
        self.store.memory('memory', 'add', text='Verified bounded procedure')
        seen = []

        @llm_client.memory_call
        def provider(prompt):
            seen.append(prompt)
            llm_client.memory_event('must-not-record', 'task', 'Operational reply')
            return llm_client.record_provider_memory_delivery(prompt, 'codex', 'fixture', status='completed')
        with patch.object(hermes_memory, 'record_episode') as record:
            trace = provider('관련 작업 점검', memory_read_only=True, memory_session_id='incident-one')
            self.assertIn('Verified bounded procedure', seen[0])
            self.assertTrue(trace['memoryPrefixPresent'])
            self.assertEqual(trace['sessionId'], 'incident-one')
            record.assert_not_called()
        self.assertFalse(llm_client._memory_read_only.get())

    def test_delivery_db_lock_preserves_response_trace_and_replays_outbox(self):
        import sqlite3
        token = llm_client._memory_delivery.set({'trace': {}, 'eventId': 'llm:' + 'a' * 32, 'sessionId': 'test', 'prefix': '<project-memory>'})
        self.addCleanup(lambda: llm_client._memory_delivery.reset(token))
        self.store.initialize()
        with patch.object(self.store, 'db', side_effect=sqlite3.OperationalError('database is locked')):
            row = llm_client.record_provider_memory_delivery('<project-memory> task', 'codex', 'fixture', status='completed')
        self.assertTrue(row['memoryPrefixPresent'])
        outbox = self.store.root / 'provider-delivery-outbox'
        self.assertEqual(len(list(outbox.glob('*.json'))), 1)
        self.assertEqual(llm_client.flush_provider_memory_deliveries(), 1)
        self.assertEqual(llm_client.flush_provider_memory_deliveries(), 0)
        with self.store.db() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM memory_deliveries').fetchone()[0], 1)

    def test_reviewer_skip_propagates_and_never_records_recursive_episode(self):

        @llm_client.memory_call
        def nested(prompt):
            llm_client.memory_event('forbidden', 'test', 'should not be stored', review=True)
            return {'memory': [], 'skills': []}

        @llm_client.memory_call
        def outer(prompt):
            return nested(prompt)
        with patch.object(hermes_memory, 'frozen_session_context') as snapshot, patch.object(hermes_memory, 'record_episode') as record, patch.object(hermes_memory, 'enqueue_review') as review:
            outer('review request', _skip_memory=True)
            snapshot.assert_not_called()
            record.assert_not_called()
            review.assert_not_called()

    def test_selected_skill_body_is_frozen_until_next_task(self):
        self.store.skill_manage('create', 'repair', content='# Repair\nDescription: repair\nOriginal procedure')
        prompts = []

        @llm_client.memory_call
        def call(prompt):
            prompts.append(prompt)
            return {'ok': True}
        with llm_client.memory_session('skill-task', 'doctor'):
            call('repair')
            self.store.skill_manage('patch', 'repair', old_text='Original procedure', new_text='Updated procedure')
            call('repair')
        self.assertEqual(prompts[0], prompts[1])
        self.assertIn('Original procedure', prompts[1])
        with llm_client.memory_session('next-skill-task', 'doctor'):
            call('repair')
        self.assertIn('Updated procedure', prompts[2])

    def test_review_is_queued_without_executing_provider_in_foreground(self):
        with patch.object(hermes_memory, 'enqueue_review', return_value={'queued': True}) as enqueue, patch.object(llm_client, 'generate_json') as provider:
            llm_client.memory_event('real-repair', 'pipeline_recovery_success', 'Confirmed repair', evidence={'verified': True}, review=True)
            self.assertEqual(enqueue.call_args.args, ('real-repair',))
            self.assertIs(enqueue.call_args.kwargs['reviewer'], llm_client._memory_review)
            provider.assert_not_called()

    def test_failed_call_is_not_a_success_or_review_trigger(self):

        @llm_client.memory_call
        def failed(prompt):
            raise RuntimeError('provider unavailable')
        with patch.object(hermes_memory, 'record_episode', return_value={}) as record, patch.object(hermes_memory, 'enqueue_review') as review:
            with self.assertRaises(RuntimeError):
                failed('request')
            self.assertFalse(record.call_args.kwargs['success'])
            self.assertEqual(record.call_args.args[1], 'llm_call_failed')
            review.assert_not_called()

    def test_growth_requires_completed_comparable_positive_observation(self):
        from growth import _record_growth_observation
        item = {'id': 'action', 'url': 'https://example.org/article', 'status': 'done', 'baseline': {}, 'followup': {}, 'observation': {'end': '2026-10-18'}, 'verification': {'status': 'observed_change', 'clicksDelta': 2, 'impressionsDelta': 0, 'causalProof': False}}
        with patch.object(llm_client, 'memory_event') as event:
            _record_growth_observation({**item, 'status': 'in_progress'})
            _record_growth_observation({**item, 'verification': {'status': 'observing', 'clicksDelta': 2}})
            _record_growth_observation({**item, 'verification': {'status': 'observed_change', 'clicksDelta': -2}})
            event.assert_not_called()
            _record_growth_observation(item)
            self.assertTrue(event.call_args.kwargs['review'])
            self.assertFalse(event.call_args.kwargs['evidence']['verification']['causalProof'])

    def test_direct_cli_is_wrapped_without_duplicating_outer_context(self):
        from common import codex_cli
        self.assertTrue(hasattr(codex_cli.generate_local, '__wrapped__'))
        self.assertTrue(hasattr(llm_client.generate_json, '__wrapped__'))

    def test_actual_direct_cli_injects_once_and_skip_reviewer_does_not_record(self):
        from common import codex_cli
        self.store.memory('memory', 'add', text='Verified test-only rule')
        captured = []

        def run(command, **kwargs):
            captured.append(kwargs)
            output = Path(command[command.index('--output-last-message') + 1])
            output.write_text(json.dumps({'json': '{"ok": true}'}), encoding='utf-8')
            return SimpleNamespace(returncode=0, stdout='{"type":"turn.completed"}', stderr='')
        with patch.object(codex_cli, 'local_config', return_value={'executable': 'never-executed', 'home': self.temp.name}), patch.object(codex_cli, 'runtime', return_value={'models': [{'id': 'test-model'}]}), patch.object(codex_cli, 'environment', return_value={}), patch.object(codex_cli, 'is_wsl', return_value=False), patch.object(codex_cli.Path, 'home', return_value=Path(self.temp.name)), patch.object(codex_cli, '_fallback_candidates', return_value=[('test-model', 'low')]), patch.object(codex_cli.subprocess, 'run', side_effect=run):
            with llm_client.memory_session('direct-real-entry', 'kin'):
                self.assertEqual(codex_cli.generate_local('direct task', 'test-model', timeout_seconds=9)[0], {'ok': True})

            @llm_client.memory_call
            def outer(prompt):
                return codex_cli.generate_local(prompt, 'test-model', timeout_seconds=9)
            outer('nested task', memory_session_id='outer-real-entry')
            outer('review-only', _skip_memory=True)
        self.assertEqual([x['input'].count('<project-memory>') for x in captured], [1, 1, 0])
        self.assertIn('Verified test-only rule', captured[0]['input'])
        self.assertTrue(all((0 < x['timeout'] <= 9 for x in captured)))
        with self.store.db() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM episodes').fetchone()[0], 2)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM review_queue').fetchone()[0], 0)
            deliveries = [json.loads(row[0]) for row in db.execute("SELECT payload FROM memory_deliveries WHERE status='completed'").fetchall()]
        self.assertEqual(len(deliveries), 2)
        self.assertEqual({row['actualPromptSha256'] for row in deliveries}, {hashlib.sha256(call['input'].encode('utf-8')).hexdigest() for call in captured[:2]})
        self.assertTrue(all((row['memoryPrefixPresent'] for row in deliveries)))

    def test_doctor_reviews_only_successful_republish_with_matching_public_text(self):
        from dashboard.server import doctor
        with patch.object(doctor, 'parse_cf_post_url', return_value=('example.org', 'post')), patch.object(doctor, 'find_live_cf_post', return_value={'id': 7, 'title': 'Repair', 'content': '<p>Actual corrected text</p>'}), patch.object(doctor, 'find_local_output_runs', return_value=[]), patch.object(doctor, '_get_cf_headers', return_value={}), patch.object(doctor, 'get_device_profile', return_value={}), patch.object(doctor, 'DOCTOR_LEDGER_PATH', Path(self.temp.name) / 'absent-ledger.json'), patch.object(doctor.requests, 'put') as put, patch.object(doctor.requests, 'get') as get, patch.object(llm_client, 'memory_event') as event:
            for apply, code, public_text, expected in [(False, 200, 'Actual corrected text', False), (True, 500, 'Actual corrected text', False), (True, 200, 'Old unrelated body', False), (True, 200, 'Actual corrected text', True)]:
                with self.subTest(apply=apply, code=code, public_text=public_text):
                    put.return_value = SimpleNamespace(status_code=code)
                    get.return_value = SimpleNamespace(status_code=200, text='<article class="content">' + public_text + '</article>')
                    doctor.remodel_cf_post_by_url('https://example.org/post', apply=apply)
                    self.assertEqual(event.call_args.kwargs['review'], expected)
                    self.assertEqual(event.call_args.kwargs['success'], expected)

    def test_revenue_growth_requires_complete_matching_periods(self):
        from growth import _record_metric_increase
        period = {'start': '2026-10-01', 'end': '2026-10-07', 'status': 'complete', 'currency': 'USD', 'source_timezone': 'America/Los_Angeles', 'value_kind': 'estimated', 'revenue_scope': 'excludes_arbitrage', 'total': 10}
        item = {'service': 'adsense', 'metric': 'revenue', 'previous': period, 'current': {**period, 'start': '2026-10-08', 'end': '2026-10-14', 'total': 20}}
        with patch.object(llm_client, 'memory_event') as event:
            for changed in ({'status': 'partial'}, {'currency': 'KRW'}, {'value_kind': 'final'}, {'source_timezone': 'Asia/Seoul'}, {'total': None}, {'total': 9}):
                _record_metric_increase('site', {**item, 'current': {**item['current'], **changed}})
            event.assert_not_called()
            _record_metric_increase('site', item)
            self.assertEqual(event.call_args.kwargs['evidence']['delta'], 10)
            self.assertEqual(event.call_args.kwargs['evidence']['current']['value_kind'], 'estimated')
            self.assertFalse(event.call_args.kwargs['evidence']['causalProof'])

    def test_publication_learning_is_separate_from_writer_approval(self):
        from dashboard.collectors import naver_public
        import inspect
        text = inspect.getsource(naver_public.reconcile)
        self.assertIn('learn_naver_public', text)
        source = (Path(__file__).resolve().parents[3] / 'naver_blog_posting/posting.py').read_text()
        self.assertNotIn('editorial_supervisor', source)

    def test_chat_generation_timeout_reaches_api_and_codex_process(self):
        from common import codex_cli
        config = {'active': 'openai', 'providers': {'openai': {'model': 'test-model'}}}
        with patch.object(llm_client.settings, 'load', return_value=config), patch.object(llm_client.settings, 'environment_key', return_value='test-only'), patch.object(llm_client.requests, 'post', side_effect=llm_client.requests.Timeout) as post:
            with self.assertRaises(RuntimeError):
                llm_client._generate_json('task', 'openai', timeout_seconds=9)
            self.assertEqual(post.call_args.kwargs['timeout'], 9)
        with patch.object(codex_cli, 'local_config', return_value={'executable': 'never-executed', 'home': self.temp.name}), patch.object(codex_cli, 'runtime', return_value={'models': [{'id': 'test-model'}]}), patch.object(codex_cli, 'environment', return_value={}), patch.object(codex_cli.subprocess, 'run', side_effect=subprocess.TimeoutExpired('mock', 9)) as run:
            with self.assertRaises(RuntimeError):
                codex_cli.generate_local('task', 'test-model', timeout_seconds=9)
            self.assertLessEqual(run.call_args.kwargs['timeout'], 9)
            self.assertGreater(run.call_args.kwargs['timeout'], 0)
        chat = (Path(__file__).resolve().parents[2] / 'agents/chat_room.py').read_text(encoding='utf-8')
        self.assertIn('timeout_seconds=timeout_sec', chat)

    def test_local_service_has_no_scheduler_and_rejects_untrusted_origin(self):
        from fastapi.testclient import TestClient
        from memory_service import create_app
        app = create_app(8792)
        with TestClient(app) as client:
            response = client.get('/api/status', headers={'Origin': 'http://192.168.45.190:8790'})
            self.assertEqual(response.status_code, 200)
            self.assertFalse(response.json()['schedulersStarted'])
            self.assertEqual(response.headers['access-control-allow-origin'], 'http://192.168.45.190:8790')
            self.assertEqual(client.get('/api/status', headers={'Origin': 'https://untrusted.invalid'}).status_code, 403)

def setUpModule():
    import tempfile
    from pathlib import Path
    from unittest.mock import patch
    from common import repair_workflow
    global _isolated_crew_temp, _isolated_crew_patches
    _isolated_crew_temp = tempfile.TemporaryDirectory()
    root = Path(_isolated_crew_temp.name)
    _isolated_crew_patches = [patch('common.crew_chat_bridge._deliver', return_value=True), patch('common.crew_chat_bridge.OUTBOX_DIR', root / 'outbox'), patch.object(repair_workflow, 'ROOT', root / 'repairs')]
    for guard in _isolated_crew_patches:
        guard.start()

def tearDownModule():
    for guard in reversed(_isolated_crew_patches):
        guard.stop()
    _isolated_crew_temp.cleanup()
if __name__ == '__main__':
    unittest.main()
