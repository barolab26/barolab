"""Bounded provider and outcome hooks; no external model, publishing or real memory writes."""
import ast
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
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

    def test_reviewer_skip_propagates_and_never_records_recursive_episode(self):
        @llm_client.memory_call
        def nested(prompt):
            llm_client.memory_event('forbidden', 'test', 'should not be stored', review=True)
            return {'memory': [], 'skills': []}

        @llm_client.memory_call
        def outer(prompt):
            return nested(prompt)

        with patch.object(hermes_memory, 'frozen_session_context') as snapshot, \
                patch.object(hermes_memory, 'record_episode') as record, \
                patch.object(hermes_memory, 'enqueue_review') as review:
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
        with patch.object(hermes_memory, 'enqueue_review', return_value={'queued': True}) as enqueue, \
                patch.object(llm_client, 'generate_json') as provider:
            llm_client.memory_event('real-repair', 'pipeline_recovery_success', 'Confirmed repair',
                                    evidence={'verified': True}, review=True)
            self.assertEqual(enqueue.call_args.args, ('real-repair',))
            self.assertIs(enqueue.call_args.kwargs['reviewer'], llm_client._memory_review)
            provider.assert_not_called()

    def test_failed_call_is_not_a_success_or_review_trigger(self):
        @llm_client.memory_call
        def failed(prompt):
            raise RuntimeError('provider unavailable')

        with patch.object(hermes_memory, 'record_episode', return_value={}) as record, \
                patch.object(hermes_memory, 'enqueue_review') as review:
            with self.assertRaises(RuntimeError):
                failed('request')
            self.assertFalse(record.call_args.kwargs['success'])
            self.assertEqual(record.call_args.args[1], 'llm_call_failed')
            review.assert_not_called()

    def test_growth_requires_completed_comparable_positive_observation(self):
        from growth import _record_growth_observation
        item = {'id': 'action', 'url': 'https://example.org/article', 'status': 'done',
                'baseline': {}, 'followup': {}, 'observation': {'end': '2026-10-18'},
                'verification': {'status': 'observed_change', 'clicksDelta': 2, 'impressionsDelta': 0, 'causalProof': False}}
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

    def test_doctor_reviews_only_successful_republish_with_matching_public_text(self):
        from cf_posting import doctor_remodel as doctor
        with patch.object(doctor, 'parse_cf_post_url', return_value=('example.org', 'post')), \
                patch.object(doctor, 'find_live_cf_post', return_value={'id': 7, 'title': 'Repair', 'content': '<p>Actual corrected text</p>'}), \
                patch.object(doctor, 'find_local_output_runs', return_value=[]), \
                patch.object(doctor, '_get_cf_headers', return_value={}), \
                patch.object(doctor, 'get_device_profile', return_value={}), \
                patch.object(doctor, 'DOCTOR_LEDGER_PATH', Path(self.temp.name) / 'absent-ledger.json'), \
                patch.object(doctor.requests, 'put') as put, patch.object(doctor.requests, 'get') as get, \
                patch.object(llm_client, 'memory_event') as event:
            for apply, code, public_text, expected in [
                    (False, 200, 'Actual corrected text', False),
                    (True, 500, 'Actual corrected text', False),
                    (True, 200, 'Old unrelated body', False),
                    (True, 200, 'Actual corrected text', True)]:
                with self.subTest(apply=apply, code=code, public_text=public_text):
                    put.return_value = SimpleNamespace(status_code=code)
                    get.return_value = SimpleNamespace(status_code=200, text='<article class="content">' + public_text + '</article>')
                    doctor.remodel_cf_post_by_url('https://example.org/post', apply=apply)
                    self.assertEqual(event.call_args.kwargs['review'], expected)
                    self.assertEqual(event.call_args.kwargs['success'], expected)

    def test_revenue_growth_requires_complete_matching_periods(self):
        from growth import _record_metric_increase
        period = {'start': '2026-10-01', 'end': '2026-10-07', 'status': 'complete',
                  'currency': 'USD', 'source_timezone': 'America/Los_Angeles',
                  'value_kind': 'estimated', 'revenue_scope': 'excludes_arbitrage', 'total': 10}
        item = {'service': 'adsense', 'metric': 'revenue', 'previous': period,
                'current': {**period, 'start': '2026-10-08', 'end': '2026-10-14', 'total': 20}}
        with patch.object(llm_client, 'memory_event') as event:
            for changed in ({'status': 'partial'}, {'currency': 'KRW'}, {'value_kind': 'final'},
                            {'source_timezone': 'Asia/Seoul'}, {'total': None}, {'total': 9}):
                _record_metric_increase('site', {**item, 'current': {**item['current'], **changed}})
            event.assert_not_called()
            _record_metric_increase('site', item)
            self.assertEqual(event.call_args.kwargs['evidence']['delta'], 10)
            self.assertEqual(event.call_args.kwargs['evidence']['current']['value_kind'], 'estimated')
            self.assertFalse(event.call_args.kwargs['evidence']['causalProof'])

    def test_reservation_hook_is_post_submit_and_requires_real_prior_failure(self):
        source = (Path(__file__).resolve().parent.parent / 'naver_blog_posting/pipeline_runner.py').read_text(encoding='utf-8')
        tree = ast.parse(source)
        helper = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == '_record_reservation_memory')
        namespace = {}
        exec(compile(ast.Module(body=[helper], type_ignores=[]), '<reservation-hook>', 'exec'), namespace)
        record = namespace['_record_reservation_memory']
        with patch.object(llm_client, 'memory_event') as event:
            for status in ('submitting', 'failed', 'unknown'):
                record('account', Path(self.temp.name), {'submissionStatus': status}, {'priorFailure': {'phase': 'failed'}})
            event.assert_not_called()
            evidence = {'submissionStatus': 'verified_reserved'}
            record('account', Path(self.temp.name), evidence, {'runMode': 'automatic'})
            self.assertFalse(event.call_args.kwargs['review'])
            record('account', Path(self.temp.name), evidence, {'priorFailure': {'phase': 'failed'}})
            self.assertTrue(event.call_args.kwargs['review'])
            self.assertFalse(event.call_args.kwargs['evidence']['publicPublicationVerified'])
        pipeline = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == '_run_pipeline')
        calls = [n for n in ast.walk(pipeline) if isinstance(n, ast.Call)]
        hook_line = next(n.lineno for n in calls if isinstance(n.func, ast.Name) and n.func.id == '_record_reservation_memory')
        verify_line = max(n.lineno for n in calls if isinstance(n.func, ast.Name) and n.func.id == 'verify_reservation')
        self.assertGreater(hook_line, verify_line)
        self.assertLess(source.index("evidence['submissionStatus'] = 'verified_reserved'"), source.index('_record_reservation_memory(account_key, folder, evidence, attempt)'))

    def test_chat_generation_timeout_reaches_api_and_codex_process(self):
        from common import codex_cli
        config = {'active': 'openai', 'providers': {'openai': {'model': 'test-model'}}}
        with patch.object(llm_client.settings, 'load', return_value=config), \
                patch.object(llm_client.settings, 'environment_key', return_value='test-only'), \
                patch.object(llm_client.requests, 'post', side_effect=llm_client.requests.Timeout) as post:
            with self.assertRaises(RuntimeError):
                llm_client._generate_json('task', 'openai', timeout_seconds=9)
            self.assertEqual(post.call_args.kwargs['timeout'], 9)
        with patch.object(codex_cli, 'local_config', return_value={'executable': 'never-executed', 'home': self.temp.name}), \
                patch.object(codex_cli, 'runtime', return_value={'models': [{'id': 'test-model'}]}), \
                patch.object(codex_cli, 'environment', return_value={}), \
                patch.object(codex_cli.subprocess, 'run', side_effect=subprocess.TimeoutExpired('mock', 9)) as run:
            with self.assertRaises(RuntimeError):
                codex_cli.generate_local('task', 'test-model', timeout_seconds=9, _skip_memory=True)
            self.assertEqual(run.call_args.kwargs['timeout'], 9)
        chat = (Path(__file__).parent / 'chat_room.py').read_text(encoding='utf-8')
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


if __name__ == '__main__':
    unittest.main()
