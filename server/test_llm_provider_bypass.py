"""Quota bypass regression checks; no model processes or network requests."""
import copy
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

from common import agy_fallback, codex_cli, content_improvement, llm_client


class AgyBypassTests(unittest.TestCase):
    def setUp(self):
        self.usage_temp=tempfile.TemporaryDirectory();self.addCleanup(self.usage_temp.cleanup)
        meter=patch('common.llm_usage.ROOT',Path(self.usage_temp.name));meter.start();self.addCleanup(meter.stop)
        self.config = {'active': 'agy', 'providers': {
            'agy': {'model': 'gemini-4-argon-high'},
            'codex': {'model': 'gpt-6-luna'},
            'openai': {'model': 'api-model'},
        }}
        self.settings = patch.object(llm_client.settings, 'load', side_effect=lambda: copy.deepcopy(self.config))
        self.settings.start()
        self.subprocess = patch('subprocess.run', side_effect=AssertionError('Unexpected subprocess'))
        self.subprocess.start()
        self.codex = patch.object(codex_cli, 'generate', return_value=({'ok': True}, 'actual-codex'))
        self.generate = self.codex.start()

    def tearDown(self):
        self.codex.stop()
        self.subprocess.stop()
        self.settings.stop()

    def test_all_agy_entry_points_drop_agy_model_and_preserve_contract(self):
        schema = {'type': 'object'}
        for entry in ('default', 'explicit', 'internal', 'legacy', 'agent_slot'):
            with self.subTest(entry=entry):
                self.generate.reset_mock()
                if entry == 'legacy':
                    result = llm_client.agy_generate('task', 'gemini-4-argon-high', schema)
                elif entry == 'internal':
                    result, _ = llm_client._generate_json('task', 'agy', model_override='bad-agy', response_schema=schema)
                elif entry == 'agent_slot':
                    with patch.object(llm_client.settings, 'get_agent_brain', return_value={'provider': 'agy', 'model': 'bad-agy'}):
                        result = llm_client.generate_json('task', agent_slot='jarvis', response_schema=schema)
                else:
                    result = llm_client.generate_json('task', provider='agy' if entry == 'explicit' else None,
                                                      model_override='bad-agy', response_schema=schema)
                self.assertEqual(result, {'ok': True})
                self.assertTrue(self.generate.call_args.args[0].endswith('task'))
                self.assertEqual(self.generate.call_args.args[1], 'gpt-6-luna')
                self.assertEqual(self.generate.call_args.args[3], schema)

    def test_observer_records_codex_and_actual_model(self):
        observer = Mock()
        llm_client.generate_json('task', observer=observer)
        self.assertEqual(observer.call_args_list[0].args, ('codex', 'gpt-6-luna', 'calling'))
        self.assertEqual(observer.call_args.kwargs, {'actual_model': 'actual-codex'})
        self.generate.side_effect = RuntimeError('failed')
        with self.assertRaisesRegex(RuntimeError, 'failed'):
            llm_client.generate_json('task', observer=observer)
        self.assertEqual(observer.call_args.args, ('codex', 'gpt-6-luna', 'failed'))

    def test_active_api_route_is_preserved(self):
        response = Mock(status_code=200)
        response.json.return_value = {'status': 'completed', 'model': 'actual-api',
                                     'output': [{'type': 'message', 'content': [{'type': 'output_text', 'text': '{"ok":true}'}]}]}
        with patch.object(llm_client.settings, 'environment_key', return_value='test-key'), patch.object(llm_client.requests, 'post', return_value=response) as post:
            self.assertEqual(llm_client.generate_json('task', provider='openai'), {'ok': True})
        self.assertEqual(post.call_args.kwargs['json']['model'], 'api-model')
        self.generate.assert_not_called()

    def test_legacy_text_fallback_uses_codex_and_truthful_ledger(self):
        router = Mock()
        router.prepare.return_value = 'task'
        router.redact.side_effect = lambda text: text
        self.generate.return_value = ({'draft': 'bounded draft'}, 'actual-codex')
        runner = Mock(side_effect=AssertionError('AGY must not run'))
        self.assertEqual(agy_fallback.generate(router, 'task', run=runner), 'bounded draft')
        runner.assert_not_called()
        entry = router.ledger.call_args.args[0]
        self.assertEqual((entry['provider'], entry['returned_model'], entry['status']), ('codex', 'actual-codex', 'ok'))

    def test_editorial_candidates_bypass_external_router_and_remain_audited(self):
        draft = {'title': 'title', 'summary': 'summary', 'contentHtml': '<p>draft</p>',
                 'newClaims': [], 'resolvedIssueIds': [], 'changes': []}
        self.generate.return_value = (draft, 'actual-codex')
        with tempfile.TemporaryDirectory() as folder, patch.object(content_improvement, 'ROOT', Path(folder)), \
                patch.object(content_improvement, 'provider_record', return_value={}), \
                patch.object(content_improvement, 'routing_module', side_effect=AssertionError('Disabled external router')):
            result, metadata = content_improvement.model_json('writer', 'contract', {}, time.monotonic()+120)
            self.assertEqual(result, draft)
            self.assertEqual(metadata['provider'], 'codex')
            self.assertEqual(metadata['returnedModel'], 'actual-codex')
            self.assertEqual(json.loads((Path(folder)/metadata['candidateRef']).read_text(encoding='utf-8')), draft)


if __name__ == '__main__':
    unittest.main()
