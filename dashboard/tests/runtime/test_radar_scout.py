"""Durable scouting and progressive master-skill regression, isolated stores."""
import ast
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
import json
from pathlib import Path
import re
import sys
import tempfile
import types
import unittest
from unittest.mock import patch
from common.hermes_memory import HermesMemory
from server.radar_scout import RadarScout, KST, SOURCES, build_proposals, fetch_source, source_freshness

class RadarTests(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.scout = RadarScout(self.tmp.name)
        self.enqueue = patch('common.dashboard_jobs.enqueue', return_value={'id': 'a' * 32, 'kind': 'growth-radar', 'status': 'pending'}).start()
        self.addCleanup(patch.stopall)

    def tearDown(self):
        self.tmp.cleanup()

    def test_kst_schedule_no_missed_slot_flood(self):
        for hour in (9, 14, 20):
            self.assertIsNotNone(self.scout.due_slot(datetime(2026, 10, 19, hour, 3, tzinfo=KST)))
            self.assertIsNone(self.scout.due_slot(datetime(2026, 10, 19, hour, 16, tzinfo=KST)))
        self.assertIsNone(self.scout.due_slot(datetime(2026, 10, 19, 23, 0, tzinfo=KST)))

    def test_concurrent_process_claim_and_restart_dedup(self):
        with ThreadPoolExecutor(6) as pool:
            claims = list(pool.map(lambda _: RadarScout(self.tmp.name).claim('scheduled:09'), range(6)))
        self.assertEqual(sum((c['started'] for c in claims)), 1)
        self.assertFalse(RadarScout(self.tmp.name).claim('scheduled:09')['started'])
        self.assertFalse(self.scout.claim('different-manual')['started'])

    def test_failed_source_not_fabricated_and_result_persisted_before_post(self):

        def failed(spec):
            return {'sourceId': spec['id'], 'sourceUrl': spec['url'], 'track': spec['track'], 'items': [], 'status': 'failed', 'reason': 'HTTPError'}

        def publisher(result):
            state = self.scout.latest()['latest']
            self.assertEqual(state['status'], 'running')
            self.assertEqual(state['result']['trackA'], [])
            return {'postedInternally': True, 'messageIds': ['verified-message']}
        result = self.scout.run_claimed(self.scout.claim('test'), publisher, failed)
        self.assertEqual(result['status'], 'growth_action_queued')
        self.assertEqual(result['sourceStatus'], 'no_verified_candidates')
        self.assertEqual(result['growthAction']['status'], 'pending')
        self.assertFalse(result['publishedExternally'])
        self.enqueue.assert_called_once()
        self.assertEqual(result['trackA'], [])
        self.assertEqual(self.scout.latest()['latest']['status'], 'completed')

    def test_post_failure_does_not_mark_completed(self):

        def failed(spec):
            return {'sourceId': spec['id'], 'track': spec['track'], 'items': [], 'status': 'failed'}
        with self.assertRaises(RuntimeError):
            self.scout.run_claimed(self.scout.claim('test'), lambda _: (_ for _ in ()).throw(RuntimeError('write failed')), failed)
        self.assertEqual(self.scout.latest()['latest']['status'], 'failed')

    def test_unknown_price_and_rpm_are_not_claimed_as_revenue(self):
        source = [{'track': 'A', 'items': [{'title': '연금 신청 안내', 'url': 'https://www.korea.kr/test', 'sourceId': 'policy'}]}, {'track': 'B', 'sourceId': 'app_store', 'items': [{'title': 'Reminder', 'url': 'https://apps.apple.com/test', 'price': 0, 'currency': 'KRW'}]}]
        a, b = build_proposals(source)
        self.assertEqual(a[0]['status'], 'hypothesis')
        self.assertIsNone(a[0]['keywordRpm'])
        self.assertIsNone(a[0]['searchVolume'])
        self.assertEqual(b[0]['revenueEvidence']['value'], 0)
        self.assertIsNone(b[0]['revenueEvidence']['actualRevenue'])

    def test_enable_state_survives_restart(self):
        self.scout.set_enabled(False)
        self.assertFalse(RadarScout(self.tmp.name).enabled())

    def test_source_fetch_http_error_keeps_empty_candidates(self):
        with patch('server.radar_scout.requests.get', side_effect=TimeoutError):
            receipt = fetch_source(SOURCES[0])
        self.assertEqual(receipt['status'], 'failed')
        self.assertEqual(receipt['items'], [])

    def test_old_source_is_not_labeled_today_trend(self):
        current = datetime(2026, 10, 19, 12, tzinfo=KST)
        self.assertEqual(source_freshness('2026-07-01T00:00:00+09:00', current), 'older_source_collected_today')
        self.assertEqual(source_freshness(None, current), 'publication_date_unknown_collected_today')

    def test_senior_app_and_concrete_product_are_both_prioritized(self):
        sources = [{'sourceId': 'product_hunt', 'track': 'B', 'items': [{'title': 'Image model', 'summary': 'AI image generation', 'url': 'https://www.producthunt.com/a'}, {'title': 'MyLens', 'summary': 'Live Presentations', 'url': 'https://www.producthunt.com/b'}]}, {'sourceId': 'app_store', 'track': 'B', 'items': [{'title': 'Reminder', 'url': 'https://apps.apple.com/a', 'price': 0}]}]
        _, items = build_proposals(sources)
        self.assertEqual([i['title'] for i in items[:2]], ['Reminder', 'MyLens'])
        self.assertIn('3장', items[1]['idea'])

class MasterSkillTests(unittest.TestCase):

    def test_doctor_dispatch_is_pending_not_fake_completed(self):
        from unittest.mock import Mock
        tree = ast.parse(Path('dashboard/agents/agent_tools.py').read_text(encoding='utf-8'))
        fn = next((node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == 'run_doctor_audit'))
        scope = {'Any': __import__('typing').Any, 'Dict': __import__('typing').Dict, 'CF_16_DOMAINS': ['must-good.com']}
        exec(compile(ast.Module(body=[fn], type_ignores=[]), 'doctor-dispatch-test', 'exec'), scope)
        with patch('common.dashboard_jobs.enqueue', return_value={'id': 'b' * 32, 'kind': 'growth-doctor', 'status': 'pending'}) as enqueue:
            result = scope['run_doctor_audit'](target='must-good.com', limit=50)
        self.assertEqual(result['state'], 'queued')
        self.assertIsNone(result['exitCode'])
        self.assertFalse(result['verified'])
        self.assertEqual(enqueue.call_args.args[1]['limit'], 10)
        self.assertEqual(enqueue.call_args.args[1]['domain'], 'must-good.com')
        self.assertTrue(enqueue.call_args.args[1]['apply'])

    def test_canonical_root_dedup_freeze_patch_and_default_compatibility(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            for directory, body in (('data/skills', 'old duplicate'), ('skills', '# Master\ndescription: SEO 색인\ncanonical body')):
                path = base / directory / 'seo-marketing-master/SKILL.md'
                path.parent.mkdir(parents=True)
                path.write_text(body, encoding='utf-8')
            store = HermesMemory(base / 'data/memories', project_skills_root=base / 'skills')
            self.assertEqual(len(store.skill_list()), 1)
            self.assertIn('canonical body', store.skill_view('seo-marketing-master')['content'])
            original = store.skill_context('SEO', session_id='one')
            store.skill_manage('patch', 'seo-marketing-master', old_text='canonical body', new_text='updated body')
            self.assertEqual(store.skill_context('SEO', session_id='one'), original)
            self.assertIn('updated body', store.skill_context('SEO', session_id='two'))
            self.assertEqual((base / 'data/skills/seo-marketing-master/SKILL.md').read_text(), 'old duplicate')
            with self.assertRaises(ValueError):
                store.skill_view('../../secret')
            store.skill_manage('create', 'legacy-new', content='# Legacy\ndescription: Other\ntext')
            self.assertTrue((base / 'data/skills/legacy-new/SKILL.md').is_file())
            store.close()

    def test_every_agent_progressively_requests_same_master_only_for_topic(self):
        source = Path('dashboard/agents/chat_room.py').read_text(encoding='utf-8')
        fn = next((n for n in ast.parse(source).body if isinstance(n, ast.FunctionDef) and n.name == '_call_chat_llm'))
        scope = {'Optional': __import__('typing').Optional, 're': re}
        exec(compile(ast.Module(body=[fn], type_ignores=[]), 'chat-call-test', 'exec'), scope)
        captured = []
        fake = types.ModuleType('common.llm_client')
        fake.generate_json = lambda prompt, **kw: captured.append((prompt, kw)) or {'reply': 'grounded'}
        with patch.dict(sys.modules, {'common.llm_client': fake}):
            for slug in ('jarvis', 'trace', 'publi', 'patch', 'radar', 'doctor'):
                scope['_call_chat_llm']('role', '색인 마케팅 검토', agent_slug=slug)
            scope['_call_chat_llm']('role', '안녕하세요', agent_slug='jarvis')
        self.assertTrue(all(('seo-marketing-master' in p for p, _ in captured[:6])))
        self.assertNotIn('seo-marketing-master', captured[-1][0])

    def test_actual_provider_prompt_contains_canonical_body_for_six_roles(self):
        from common import hermes_memory, llm_client
        source = Path('dashboard/agents/chat_room.py').read_text(encoding='utf-8')
        fn = next((n for n in ast.parse(source).body if isinstance(n, ast.FunctionDef) and n.name == '_call_chat_llm'))
        scope = {'Optional': __import__('typing').Optional, 're': re}
        exec(compile(ast.Module(body=[fn], type_ignores=[]), 'chat-provider-test', 'exec'), scope)
        with tempfile.TemporaryDirectory() as tmp:
            store = HermesMemory(Path(tmp) / 'memories', project_skills_root=Path('skills').resolve())
            received = []

            def provider(prompt, *args, **kwargs):
                received.append(prompt)
                return ({'reply': 'tested'}, 'mock-model')
            with patch.object(hermes_memory, '_store', store), patch.object(llm_client, '_generate_json', side_effect=provider):
                for slug in ('jarvis', 'trace', 'publi', 'patch', 'radar', 'doctor'):
                    scope['_call_chat_llm']('role', '색인 마케팅 검토', agent_slug=slug)
            self.assertEqual(len(received), 6)
            for prompt in received:
                self.assertIn('# 4대 검색엔진·마케팅 마스터 절차', prompt)
                self.assertIn('FAQ rich result는 2026-05-07부터 중단', prompt)
            store.close()

    def test_no_hardcoded_scout_success_or_new_fake_seed(self):
        tree = ast.parse(Path('dashboard/agents/agent_tools.py').read_text(encoding='utf-8'))
        fn = next((n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'scout_high_value_keywords'))
        self.assertNotIn('HIGH_VALUE_KEYWORD_POOL', ast.unparse(fn))
        self.assertIn('SCOUT.trigger', ast.unparse(fn))
        chat = Path('dashboard/agents/chat_room.py').read_text(encoding='utf-8')
        self.assertNotIn('ws-seed-20261018-radar-publi', chat)
        self.assertNotIn('73.7%', chat)

    def test_indexer_timeout_is_running_not_fake_zero_exit_or_counts(self):
        import subprocess
        from unittest.mock import Mock
        tree = ast.parse(Path('dashboard/agents/agent_tools.py').read_text(encoding='utf-8'))
        names = {'run_auto_indexer', '_build_execution_receipt', 'index_check_and_submit'}
        functions = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in names]
        scope = {'Any': __import__('typing').Any, 'Dict': __import__('typing').Dict, 'subprocess': subprocess, 'sys': sys, 'json': json, 'BASE_DIR': Path('.'), 'CF_16_DOMAINS': ['woorinote.kr']}
        exec(compile(ast.Module(body=functions, type_ignores=[]), 'indexer-test', 'exec'), scope)
        process = Mock(pid=123, returncode=None)
        scope['_ego_popen'] = Mock(return_value=process)
        process.communicate.side_effect = subprocess.TimeoutExpired('worker', 45)
        queue = types.ModuleType('dashboard.indexing_submissions')
        queue.enqueue_gsc_request = Mock(return_value={'queued': True, 'started': False, 'status': 'queued'})
        with patch.object(subprocess, 'Popen', return_value=process) as popen, patch('threading.Thread'), patch.dict(sys.modules, {'dashboard.indexing_submissions': queue}):
            result = scope['index_check_and_submit']()
        self.assertEqual(scope['_ego_popen'].call_count, 1)
        self.assertIsNone(result['exitCode'])
        self.assertIsNone(result['totalSubmittedUrls'])
        self.assertIsNone(result['executionReceipt']['exit_code'])
        self.assertTrue(result['running'])
        self.assertFalse(result['browserRecovery']['started'])
        self.assertTrue(result['gscQueue']['queued'])
        self.assertFalse(result['indexingVerified'])
        queue.enqueue_gsc_request.assert_called_once_with('all', requested_by='agent_tools:sj')
        queue.enqueue_gsc_request.side_effect = RuntimeError('private exception detail')
        scope['run_auto_indexer'] = lambda *args: {'ok': True}
        with patch.dict(sys.modules, {'dashboard.indexing_submissions': queue}):
            failed = scope['index_check_and_submit']()
        self.assertEqual(failed['gscQueue']['status'], 'queue_unavailable')
        self.assertFalse(failed['gscQueue']['queued'])
        self.assertNotIn('private exception detail', json.dumps(failed))

    def test_four_engine_scope_excludes_naver_blogs_and_summary_has_no_json(self):
        tree = ast.parse(Path('dashboard/agents/chat_room.py').read_text(encoding='utf-8'))
        functions = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in {'radar_indexing_evidence', 'format_radar_indexing_evidence'}]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sites = {f'site{i}.kr': {'site': {'platform': 'cf'}, 'google': {'status': 'partial', 'indexed': 2, 'inspected': 3}} for i in range(16)}
            sites.update({f'naver:account{i}': {'site': {'platform': 'naver'}} for i in range(5)})
            (root / 'metrics.json').write_text(json.dumps({'sites': sites}), encoding='utf8')
            scope = {'DATA_DIR': root, 'json': json, 'datetime': datetime}
            exec(compile(ast.Module(body=functions, type_ignores=[]), 'summary-test', 'exec'), scope)
            with patch.dict(sys.modules, {'radar_scout': sys.modules['server.radar_scout']}):
                evidence = scope['radar_indexing_evidence']()
            self.assertEqual(evidence['overview']['google']['domainCount'], 16)
            summary = scope['format_radar_indexing_evidence'](evidence)
            self.assertNotIn('"statusCounts"', summary)
            self.assertIn('CF 16개', summary)
if __name__ == '__main__':
    unittest.main()
