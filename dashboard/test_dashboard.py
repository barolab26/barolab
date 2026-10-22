"""Dashboard cache, high-contrast cockpit, native locks and model routing regressions."""

from __future__ import annotations

import sys

from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import datetime as _consolidated_part0_dt

import io as _consolidated_part0_io

import json as _consolidated_part0_json

import tempfile as _consolidated_part0_tempfile

import unittest as _consolidated_part0_unittest

from pathlib import Path as _consolidated_part0_Path

from unittest.mock import patch as _consolidated_part0_patch

from rich.console import Console as _consolidated_part0_Console

from server import mission_control as _consolidated_part0_ui

from common.llm_usage import record_codex_usage as _consolidated_part0_record_codex_usage

class _consolidated_part0_CockpitTests(_consolidated_part0_unittest.TestCase):

    def setUp(self):
        self.now = _consolidated_part0_dt.datetime(2026, 10, 22, 15, 0, tzinfo=_consolidated_part0_ui.KST)

    def test_daily_counts_exclude_reservations_old_dates_and_lifetime_totals(self):
        cf = {'date': '2026-10-21', 'items': [{'status': 'published', 'publicUrl': 'https://example.com/a'}]}
        nv = {'date': '2026-10-22', 'accounts': [{'account': 'a', 'slots': [{'status': 'done', 'publicationStatus': 'reserved'}, {'status': 'done', 'publicPublicationVerified': True, 'publicUrl': 'https://blog.naver.com/a/123'}, {'status': 'done', 'publicPublicationVerified': True, 'publicUrl': 'https://blog.naver.com/a/123'}]}]}
        kin = {'counts': {'published_verified': 999}, 'daily': {'date': '2026-10-22', 'publishedVerified': 2}}
        rows = _consolidated_part0_ui.channels(cf, nv, kin, self.now)
        self.assertEqual([r['done'] for r in rows], [None, 1, 2])
        self.assertIn('예약 1건', rows[1]['note'])
        self.assertEqual(sum((r['target'] for r in rows)), 43)

    def test_partial_write_uses_last_valid_value_and_then_recovers(self):
        with _consolidated_part0_tempfile.TemporaryDirectory() as directory:
            path = _consolidated_part0_Path(directory) / 'state.json'
            cache = _consolidated_part0_ui.JsonCache()
            path.write_text('{"date":"today"}')
            self.assertEqual(cache.read(path), {'date': 'today'})
            path.write_text('{')
            self.assertEqual(cache.read(path), {'date': 'today'})
            self.assertIn(path, cache.errors)
            path.write_text('{"date":"tomorrow"}')
            self.assertEqual(cache.read(path), {'date': 'tomorrow'})
            self.assertNotIn(path, cache.errors)

    def test_completed_stage_and_stale_model_are_not_shown_running(self):
        at = self.now.timestamp() * 1000
        events = [{'ownerAgent': 'patch', 'ts': at - 2000, 'phase': 'started', 'model': 'actual', 'stage': 'writer'}, {'ownerAgent': 'patch', 'ts': at - 1000, 'phase': 'completed', 'stage': 'writer'}, {'ownerAgent': 'publi', 'ts': at - 181000, 'phase': 'started', 'stage': 'writer', 'model': 'old'}]
        rows = _consolidated_part0_ui.crew_rows(events, [], {}, self.now)
        self.assertEqual([r['state'] for r in rows], ['IDLE'] * 6)
        self.assertFalse(any((r['model'] for r in rows)))

    def test_running_models_and_three_log_rows_preserve_event_scope(self):
        at = self.now.timestamp() * 1000
        events = [{'ownerAgent': 'patch', 'ts': at, 'phase': 'started', 'model': 'actual', 'stage': 'writer'}]
        for i in range(8):
            events.append({'ownerAgent': 'trace', 'ts': at - i * 1000, 'phase': 'completed', 'stage': 'read_agent_status'})
        events.append({'ownerAgent': 'radar', 'ts': at, 'phase': 'failed', 'stage': 'researcher'})
        rows = _consolidated_part0_ui.crew_rows(events, [], {}, self.now)
        self.assertEqual(rows[1]['model'], 'actual')
        self.assertEqual(rows[1]['state'], 'RUNNING')
        logs = _consolidated_part0_ui.activity_log(events, {}, {}, self.now)
        self.assertEqual(len(logs), 3)
        self.assertEqual([r['alert'] for r in logs], [False, False, True])
        self.assertFalse(any(('발행 완료' in r['text'] for r in logs)))

    def test_synchronous_model_request_shows_assigned_calling_model(self):
        event = {'ownerAgent': 'patch', 'ts': self.now.timestamp() * 1000, 'phase': 'requested', 'requestedTo': 'configured-model-runner', 'stage': 'repair-diagnosis-model'}
        row = _consolidated_part0_ui.crew_rows([event], [], {'patch': {'model': 'selected-model'}}, self.now)[1]
        self.assertEqual((row['state'], row['model']), ('RUNNING', 'selected-model'))

    def test_frame_fits_24_rows_and_treats_source_as_plain_text(self):
        data = {'channels': [dict(name='CF 블로그', done=4, target=16, note='[red]literal')], 'crew': _consolidated_part0_ui.crew_rows([], [], {}, self.now), 'logs': _consolidated_part0_ui.activity_log([], {}, {}, self.now), 'ports': {p: True for p in _consolidated_part0_ui.PORTS}}
        stream = _consolidated_part0_io.StringIO()
        console = _consolidated_part0_Console(file=stream, width=120, height=24, color_system=None)
        console.print(_consolidated_part0_ui.render(data, self.now, height=24))
        text = stream.getvalue()
        self.assertLessEqual(len(text.splitlines()), 24)
        for word in ('MISSION CONTROL', 'BRAIN', '우분투 격리 크롬 세션', 'PIPELINE', 'VAULT', '[ 4/16]', '25%'):
            self.assertIn(word, text)
        self.assertNotIn('성공 판정 아님', text)

    def test_reported_usage_is_atomic_accumulates_and_resets_on_kst_day(self):
        events = [{'type': 'turn.completed', 'usage': {'input_tokens': 100, 'cached_input_tokens': 70, 'output_tokens': 20}}]
        with _consolidated_part0_tempfile.TemporaryDirectory() as directory:
            root = _consolidated_part0_Path(directory)
            _consolidated_part0_record_codex_usage(events, 'actual-model', root, self.now)
            _consolidated_part0_record_codex_usage(events, 'actual-model', root, self.now)
            path = root / 'server/data/llm-usage.json'
            usage = _consolidated_part0_json.loads(path.read_text())
            self.assertEqual(usage['totalTokens'], 240)
            self.assertEqual(usage['byModel'], {'actual-model': 240})
            self.assertEqual(_consolidated_part0_ui.token_summary(usage, self.now), ('240 / 한도 미설정', None))
            usage['dailyTokenBudget'] = 1000
            self.assertEqual(_consolidated_part0_ui.token_summary(usage, self.now)[1], 0.24)
            _consolidated_part0_record_codex_usage(events, 'actual-model', root, self.now + _consolidated_part0_dt.timedelta(days=1))
            self.assertEqual(_consolidated_part0_json.loads(path.read_text())['totalTokens'], 120)

    def test_port_probes_are_cached_between_collections(self):
        with _consolidated_part0_tempfile.TemporaryDirectory() as directory, _consolidated_part0_patch('socket.create_connection', side_effect=OSError) as probe:
            collector = _consolidated_part0_ui.Collector(_consolidated_part0_Path(directory))
            collector.collect()
            collector.collect()
            self.assertEqual(probe.call_count, len(_consolidated_part0_ui.PORTS))
            self.assertTrue(collector.get()['cached'])

import datetime as _consolidated_part1_dt

import io as _consolidated_part1_io

from pathlib import Path as _consolidated_part1_Path

import tempfile as _consolidated_part1_tempfile

import unittest as _consolidated_part1_unittest

from unittest.mock import Mock as _consolidated_part1_Mock, patch as _consolidated_part1_patch

from rich.console import Console as _consolidated_part1_Console

from server import cockpit_telemetry as _consolidated_part1_probe, cockpit_panels as _consolidated_part1_view, mission_control as _consolidated_part1_ui

class _consolidated_part1_TelemetryTests(_consolidated_part1_unittest.TestCase):

    def test_credit_numbers_keep_key_cap_distinct_from_account_balance(self):
        key = _consolidated_part1_Mock(status_code=200)
        key.json.return_value = {'data': {'usage': 2.25, 'limit': 10, 'limit_remaining': 7.75}}
        credits = _consolidated_part1_Mock(status_code=200)
        credits.json.return_value = {'data': {'total_credits': 30, 'total_usage': 5}}
        with _consolidated_part1_patch.object(_consolidated_part1_probe.requests, 'get', side_effect=[key, credits]) as get:
            result = _consolidated_part1_probe.credit_probe({'OPENROUTER_API_KEY': 'private-key'})
        self.assertEqual((result['usage'], result['limit_remaining'], result['balance']), (2.25, 7.75, 25))
        self.assertNotIn('private-key', str(result))
        self.assertEqual(get.call_count, 2)

    def test_no_key_never_calls_remote_and_never_claims_zero_balance(self):
        with _consolidated_part1_patch.object(_consolidated_part1_probe.requests, 'get') as get:
            result = _consolidated_part1_probe.credit_probe({})
        get.assert_not_called()
        self.assertNotIn('balance', result)

    def test_cdp_probe_sanitizes_url_and_does_not_invent_active_tab(self):
        response = _consolidated_part1_Mock()
        response.json.return_value = [{'type': 'page', 'id': 'a', 'title': 'Title', 'url': 'https://user:pass@example.com/a?token=secret#private'}]
        with _consolidated_part1_patch.object(_consolidated_part1_probe.requests, 'get', return_value=response) as get:
            result = _consolidated_part1_probe.fleet_probe(_consolidated_part1_probe.FLEET[0])
        self.assertTrue(result['online'])
        self.assertEqual(result['tabs'][0]['url'], 'https://example.com/a')
        self.assertEqual(result['selection'], '열린 탭')
        self.assertEqual(get.call_args.kwargs['timeout'], 0.3)

    def test_high_frame_fills_height_with_six_panels_and_plain_source_text(self):
        now = _consolidated_part1_dt.datetime(2026, 10, 22, 15, tzinfo=_consolidated_part1_ui.KST)
        data = {'channels': [{'name': 'CF 블로그', 'done': 4, 'target': 16, 'note': '[red]literal'}], 'crew': _consolidated_part1_ui.crew_rows([], [], {}, now), 'remote': {'fleet': [dict(port=p, account=a, blog=b, purpose=u, online=True, tabs=[{'title': '[red]Title', 'url': 'https://example.com/'}]) for p, a, b, u in _consolidated_part1_probe.FLEET]}}
        for member in data['crew']:
            member['action'] = '실제 원인과 조치 ' + '긴 상세 설명 ' * 30
        stream = _consolidated_part1_io.StringIO()
        console = _consolidated_part1_Console(file=stream, width=144, height=76, color_system=None)
        console.print(_consolidated_part1_view.render(data, now, 76))
        text = stream.getvalue()
        self.assertEqual(len(text.splitlines()), 76)
        self.assertEqual(sum(_consolidated_part1_view.panel_sizes(76)), 76)
        for title in ('MISSION CONTROL', 'BRAIN', '우분투 격리 크롬 세션', 'PIPELINE', 'ACTIVE CREW', 'VAULT', '[red]Title', '[red]literal'):
            self.assertIn(title, text)
        for name in ('자비스', '패치', '퍼블리', '트레이스', '닥터', '레이더'):
            self.assertIn('@' + name, text)
        self.assertNotIn('성공 판정 아님', text)
        self.assertIn('┗', text.splitlines()[-1])

    def test_missing_daily_revenue_is_not_zero_and_duplicate_adpost_is_not_added(self):
        now = _consolidated_part1_dt.datetime(2026, 10, 22, 15, tzinfo=_consolidated_part1_ui.KST)
        src = {'category': 'adsense', 'currency': 'USD', 'daily': {'2026-10-20': '0.03'}}
        result = '\n'.join(_consolidated_part1_view.revenue_summary({'months': {'2026-10': {'sources': [src]}}}, {}, now))
        self.assertIn('오늘 집계 대기', result)
        self.assertIn('$0.03', result)
        self.assertNotIn('오늘 $0.00', result)

    def test_codex_subscription_limit_and_positive_extra_credits_are_both_visible(self):
        now = _consolidated_part1_dt.datetime(2026, 10, 22, 15, tzinfo=_consolidated_part1_ui.KST)
        data = {'remote': {'codexQuota': {'status': 'collected', 'buckets': {'codex': {'primary': {'usedPercent': 100, 'windowDurationMins': 10080}, 'credits': {'hasCredits': True, 'unlimited': False, 'balance': '39263.1127530000'}}}}}}
        text = '\n'.join(_consolidated_part1_view.brain_lines(data, now))
        self.assertIn('잔여 0%', text)
        self.assertIn('39,263.11 크레딧', text)
        self.assertNotIn('$39,263', text)

    def test_all_stages_match_and_editorial_precedes_research(self):
        for stage, wanted in [('keyword-selector', 1), ('researcher', 2), ('editorial-query', 3), ('writer', 4), ('reviewer', 5), ('최종발행', 6)]:
            self.assertEqual(_consolidated_part1_view.stage_number(stage), wanted)

import ast as _consolidated_part2_ast

from concurrent.futures import ThreadPoolExecutor as _consolidated_part2_ThreadPoolExecutor

from pathlib import Path as _consolidated_part2_Path

import threading as _consolidated_part2_threading

import unittest as _consolidated_part2_unittest

from unittest.mock import patch as _consolidated_part2_patch

from fastapi import HTTPException as _consolidated_part2_HTTPException

from server.dashboard_cache import ReadCache as _consolidated_part2_ReadCache, compact_metrics as _consolidated_part2_compact_metrics

class _consolidated_part2_DashboardCacheTests(_consolidated_part2_unittest.TestCase):

    def test_compact_metrics_keeps_unknown_values_dates_and_drops_page_details(self):
        data = {'checkedAt': 'old-date', 'indexing': {'indexed': None}, 'trafficAnalysis': {'today': 'source-date', 'sites': [{'site': {'site_id': 'example'}, 'ga4': {'stale': True, 'periods': {'today': {'sessions': None, 'start': 'source-date', 'pages': ['large detail']}}}}]}, 'contentAudit': {'counts': {'not_indexed': 2}, 'rows': ['large detail']}}
        result = _consolidated_part2_compact_metrics(data)
        self.assertIsNone(result['indexing']['indexed'])
        self.assertEqual(result['trafficAnalysis']['today'], 'source-date')
        ga4 = result['trafficAnalysis']['sites'][0]['ga4']
        self.assertTrue(ga4['stale'])
        self.assertIsNone(ga4['periods']['today']['sessions'])
        self.assertNotIn('pages', ga4['periods']['today'])
        self.assertNotIn('rows', result['contentAudit'])
        self.assertIn('rows', data['contentAudit'])

    def test_concurrent_read_does_not_repeat_build_or_wait_in_http_pool(self):
        cache = _consolidated_part2_ReadCache()
        started, release = (_consolidated_part2_threading.Event(), _consolidated_part2_threading.Event())
        value = {'stats': {'total': 7}}

        def build():
            started.set()
            self.assertTrue(release.wait(3))
            return value
        with _consolidated_part2_ThreadPoolExecutor(max_workers=1) as executor:
            first = executor.submit(cache.get, 'graph', build)
            self.assertTrue(started.wait(3))
            try:
                with self.assertRaises(_consolidated_part2_HTTPException) as error:
                    cache.get('graph', lambda: self.fail('duplicate build'))
                self.assertEqual(error.exception.status_code, 503)
            finally:
                release.set()
            self.assertIs(first.result(3), value)
        self.assertIs(cache.get('graph', lambda: self.fail('cache miss')), value)

    def test_burst_does_not_spawn_duplicate_builds_or_block_http_workers(self):
        cache = _consolidated_part2_ReadCache()
        started = _consolidated_part2_threading.Event()
        release = _consolidated_part2_threading.Event()
        calls = []

        def build():
            calls.append(1)
            started.set()
            release.wait(3)
            return {'ok': True}

        def duplicate():
            try:
                cache.get('same-projection', build)
            except _consolidated_part2_HTTPException as error:
                return error.status_code
        with _consolidated_part2_ThreadPoolExecutor(max_workers=17) as executor:
            first = executor.submit(cache.get, 'same-projection', build)
            self.assertTrue(started.wait(1))
            try:
                futures = [executor.submit(duplicate) for _ in range(16)]
                self.assertEqual([f.result(0.5) for f in futures], [503] * 16)
                self.assertEqual(calls, [1])
            finally:
                release.set()
            self.assertEqual(first.result(1), {'ok': True})
        self.assertFalse(cache.building)

    def test_expiry_bounded_entries_and_failed_build_recovery(self):
        cache = _consolidated_part2_ReadCache(ttl=30, capacity=2)
        with _consolidated_part2_patch('server.dashboard_cache.time.monotonic', return_value=100):
            cache.get('a', lambda: 1)
            cache.get('b', lambda: 2)
            cache.get('c', lambda: 3)
            self.assertEqual(list(cache.values), ['b', 'c'])
        with _consolidated_part2_patch('server.dashboard_cache.time.monotonic', return_value=131):
            with self.assertRaises(ValueError):
                cache.get('b', lambda: (_ for _ in ()).throw(ValueError('failed')))
            self.assertEqual(cache.get('b', lambda: 4), 4)

    def test_metrics_read_does_not_verify_external_publication(self):
        source = (_consolidated_part2_Path(__file__).parent / 'runtime/main.py').read_text()
        node = next((n for n in _consolidated_part2_ast.parse(source).body if isinstance(n, _consolidated_part2_ast.FunctionDef) and n.name == 'get_metrics'))
        self.assertFalse(any((isinstance(n, _consolidated_part2_ast.Name) and n.id == 'reconcile' for n in _consolidated_part2_ast.walk(node))))

'Employee reasoning preferences: isolated config, mocked providers and CLI.'

import json as _consolidated_part3_json

from pathlib import Path as _consolidated_part3_Path

import subprocess as _consolidated_part3_subprocess

import tempfile as _consolidated_part3_tempfile

import unittest as _consolidated_part3_unittest

from unittest.mock import patch as _consolidated_part3_patch

from common import codex_cli as _consolidated_part3_codex_cli, llm_client as _consolidated_part3_llm_client, llm_settings as _consolidated_part3_settings

class _consolidated_part3_AgentReasoningTests(_consolidated_part3_unittest.TestCase):

    def setUp(self):
        self.temp = _consolidated_part3_tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = _consolidated_part3_Path(self.temp.name)
        self.config = {'active': 'codex', 'providers': {'codex': {'model': 'fixture-model'}}, 'agentBrains': {'patch': {'provider': 'codex', 'model': 'fixture-model', 'reasoningEffort': 'high'}}}
        self.path = self.root / 'settings.json'
        self.path.write_text(_consolidated_part3_json.dumps(self.config))
        self.catalog = [{'id': 'fixture-model', 'label': 'Fixture', 'reasoningEfforts': ['low', 'high', 'xhigh']}]
        for item in (_consolidated_part3_patch('common.llm_usage.ROOT', self.root), _consolidated_part3_patch.object(_consolidated_part3_settings, 'CONFIG', self.path), _consolidated_part3_patch.object(_consolidated_part3_codex_cli, 'model_catalog', return_value=self.catalog), _consolidated_part3_patch.object(_consolidated_part3_codex_cli, 'runtime', return_value={'models': self.catalog}), _consolidated_part3_patch('common.crew_chat_bridge.emit_work_event', return_value='event')):
            item.start()
            self.addCleanup(item.stop)

    def test_save_public_reload_preserve_explicit_and_default(self):
        saved = _consolidated_part3_settings.save_agent_brains({'agentBrains': {'patch': {'provider': 'codex', 'model': 'fixture-model', 'reasoningEffort': 'xhigh'}}})
        self.assertEqual(saved['agentBrains']['patch']['reasoningEffort'], 'xhigh')
        _consolidated_part3_settings.save_agent_brains({'agentBrains': {'patch': {'provider': 'codex', 'model': 'fixture-model'}}})
        self.assertEqual(_consolidated_part3_settings.get_agent_brain('patch')['reasoningEffort'], 'xhigh')
        _consolidated_part3_settings.save({'provider': 'codex', 'model': 'fixture-model', 'agentBrains': {'patch': {'provider': 'codex', 'model': 'fixture-model', 'reasoningEffort': None}}})
        self.assertIsNone(_consolidated_part3_settings.get_agent_brain('patch')['reasoningEffort'])

    def test_unsupported_effort_or_provider_does_not_write(self):
        original = self.path.read_bytes()
        for provider, effort in [('codex', 'ultra'), ('codex', 'invalid'), ('openai', 'high')]:
            with self.subTest(provider=provider, effort=effort), self.assertRaises(_consolidated_part3_settings.SettingsError):
                _consolidated_part3_settings.save_agent_brains({'agentBrains': {'patch': {'provider': provider, 'model': 'fixture-model', 'reasoningEffort': effort}}})
            self.assertEqual(self.path.read_bytes(), original)

    def test_employee_context_and_slot_reach_adapter_without_leaking(self):
        with _consolidated_part3_patch.object(_consolidated_part3_llm_client, '_generate_json', return_value=({'ok': True}, 'fixture-model')) as call:
            _consolidated_part3_llm_client.generate_json('task', provider='codex', model_override='fixture-model', crew_actor='patch', _skip_memory=True)
            self.assertEqual(call.call_args.args[6], 'high')
            _consolidated_part3_llm_client.generate_json('task', agent_slot='patch', _skip_memory=True)
            self.assertEqual(call.call_args.args[6], 'high')
            _consolidated_part3_llm_client.generate_json('task', provider='codex', model_override='fixture-model', reasoning_effort='low', crew_actor='patch', _skip_memory=True)
            self.assertEqual(call.call_args.args[6], 'low')
            _consolidated_part3_llm_client.generate_json('task', provider='codex', model_override='other-model', crew_actor='patch', _skip_memory=True)
            self.assertIsNone(call.call_args.args[6])
            _consolidated_part3_llm_client.generate_json('task', provider='codex', model_override='fixture-model', _skip_memory=True)
            self.assertIsNone(call.call_args.args[6])

    def test_exact_selected_effort_reaches_cli_without_lowering_or_model_switch(self):
        home = self.root / 'codex'
        home.mkdir()
        (home / 'models_cache.json').write_text(_consolidated_part3_json.dumps({'models': [{'slug': 'fixture-model', 'supported_reasoning_levels': [{'effort': 'high'}]}]}))
        cli_config = {'home': str(home), 'executable': 'mock-codex'}
        commands = []

        def run(command, **kwargs):
            commands.append(command)
            output = _consolidated_part3_Path(command[command.index('--output-last-message') + 1])
            output.write_text('{"json":"{\\"ok\\":true}"}')
            return _consolidated_part3_subprocess.CompletedProcess(command, 0, '{"type":"turn.completed"}\n', '')
        with _consolidated_part3_patch.object(_consolidated_part3_codex_cli, 'local_config', return_value=cli_config), _consolidated_part3_patch.object(_consolidated_part3_codex_cli, 'is_wsl', return_value=False), _consolidated_part3_patch.object(_consolidated_part3_Path, 'home', return_value=self.root), _consolidated_part3_patch.object(_consolidated_part3_codex_cli, '_fallback_candidates', side_effect=AssertionError('must honor choice')), _consolidated_part3_patch.object(_consolidated_part3_codex_cli.subprocess, 'run', side_effect=run):
            result, _ = _consolidated_part3_codex_cli.generate_local('task', 'fixture-model', reasoning_effort='high', _skip_memory=True)
        self.assertEqual(result, {'ok': True})
        self.assertIn('model_reasoning_effort="high"', commands[0])
        self.assertEqual(len(commands), 1)

import datetime as _consolidated_part4_dt

import json as _consolidated_part4_json

from pathlib import Path as _consolidated_part4_Path

import tempfile as _consolidated_part4_tempfile

import unittest as _consolidated_part4_unittest

from unittest.mock import patch as _consolidated_part4_patch

from concurrent.futures import ThreadPoolExecutor as _consolidated_part4_ThreadPoolExecutor

from common import llm_usage as _consolidated_part4_usage

class _consolidated_part4_UsageTests(_consolidated_part4_unittest.TestCase):

    def setUp(self):
        self.temp = _consolidated_part4_tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = _consolidated_part4_Path(self.temp.name)

    def ledger(self):
        return _consolidated_part4_json.loads((self.root / 'server/data/llm_usage_ledger.json').read_text())

    def test_nested_adapters_are_counted_once_and_headers_are_allowlisted(self):

        @_consolidated_part4_usage.metered
        def inner(prompt, **kwargs):
            _consolidated_part4_usage.report_response({'usage': {'input_tokens': 12, 'output_tokens': 3}}, {'x-ratelimit-remaining-requests': '20', 'Authorization': 'secret', 'Set-Cookie': 'private'}, 200, 'actual')
            return {'ok': True}

        @_consolidated_part4_usage.metered
        def outer(prompt, **kwargs):
            return inner(prompt, provider='codex', model='requested')
        with _consolidated_part4_patch.object(_consolidated_part4_usage, 'ROOT', self.root):
            outer('private prompt', provider='codex', model='requested')
        ledger = self.ledger()
        row = ledger['byModel']['codex:actual']
        self.assertEqual((row['calls'], row['inputTokens'], row['outputTokens']), (1, 12, 3))
        self.assertEqual(row['rateLimitHeaders'], {'x-ratelimit-remaining-requests': '20'})
        self.assertEqual(ledger['active'], {})
        self.assertNotIn('private', _consolidated_part4_json.dumps(ledger))
        self.assertNotIn('secret', _consolidated_part4_json.dumps(ledger))

    def test_failure_preserves_exception_counts_quota_and_unknown_tokens(self):

        @_consolidated_part4_usage.metered
        def failed(prompt, **kwargs):
            raise RuntimeError('HTTP 429 secret error body')
        with _consolidated_part4_patch.object(_consolidated_part4_usage, 'ROOT', self.root), self.assertRaisesRegex(RuntimeError, '429'):
            failed('secret prompt', provider='gemini', model='flash')
        row = self.ledger()['byModel']['gemini:flash']
        self.assertEqual((row['errors'], row['rateLimited'], row['usageReportedCalls']), (1, 1, 0))
        self.assertNotIn('secret', _consolidated_part4_json.dumps(self.ledger()))

    def test_concurrent_calls_accumulate_without_loss(self):

        @_consolidated_part4_usage.metered
        def call(prompt, **kwargs):
            _consolidated_part4_usage.report_response(events=[{'type': 'turn.completed', 'usage': {'input_tokens': 10, 'output_tokens': 2}}])
            return 1
        with _consolidated_part4_patch.object(_consolidated_part4_usage, 'ROOT', self.root), _consolidated_part4_ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(lambda _: call('x', provider='codex', model='m'), range(30)))
        row = self.ledger()['byModel']['codex:m']
        self.assertEqual((row['calls'], row['success'], row['inputTokens'], row['outputTokens']), (30, 30, 300, 60))

    def test_kst_midnight_resets_daily_counters(self):
        call = dict(id='x', provider='p', model='m', startedAt='2026-10-22T23:59:00+09:00', inputTokens=1, outputTokens=2, usageReports=1, latencyMs=1, rateLimitHeaders={})
        now = _consolidated_part4_dt.datetime(2026, 10, 22, 23, 59, tzinfo=_consolidated_part4_usage.KST)
        _consolidated_part4_usage.record_call(call, 'completed', root=self.root, now=now)
        _consolidated_part4_usage.record_call(call, 'failed', root=self.root, now=now + _consolidated_part4_dt.timedelta(minutes=2))
        row = self.ledger()['byModel']['p:m']
        self.assertEqual((row['calls'], row['success'], row['errors']), (1, 0, 1))

'Shared native locks and duplicate publisher admission; no live workers launched.'

import ast as _consolidated_part5_ast

import json as _consolidated_part5_json

import os as _consolidated_part5_os

from pathlib import Path as _consolidated_part5_Path

import subprocess as _consolidated_part5_subprocess

import sys as _consolidated_part5_sys

import tempfile as _consolidated_part5_tempfile

import unittest as _consolidated_part5_unittest

from unittest.mock import patch as _consolidated_part5_patch, Mock as _consolidated_part5_Mock

from common import runtime_locks as _consolidated_part5_runtime_locks

class _consolidated_part5_RuntimeLockTests(_consolidated_part5_unittest.TestCase):

    def test_windows_mounted_project_uses_native_home_lock(self):
        with _consolidated_part5_patch.object(_consolidated_part5_runtime_locks.sys, 'platform', 'linux'), _consolidated_part5_patch.object(_consolidated_part5_Path, 'home', return_value=_consolidated_part5_Path('/tmp/native-home')):
            first = _consolidated_part5_runtime_locks.runtime_lock_path('/mnt/c/10_Project/BaroLab/cf_posting/data/cleaner.lock')
            self.assertTrue(first.is_relative_to('/tmp/native-home/.barolab/locks'))
            self.assertEqual(first, _consolidated_part5_runtime_locks.runtime_lock_path('/mnt/c/10_Project/BaroLab/cf_posting/data/cleaner.lock'))
            self.assertNotEqual(first, _consolidated_part5_runtime_locks.runtime_lock_path('/mnt/c/10_Project/BaroLab/naver/data/cleaner.lock'))
            self.assertEqual(_consolidated_part5_runtime_locks.runtime_lock_path('/tmp/example.lock'), _consolidated_part5_Path('/tmp/example.lock'))
        with _consolidated_part5_patch.object(_consolidated_part5_runtime_locks.sys, 'platform', 'win32'):
            self.assertEqual(_consolidated_part5_runtime_locks.runtime_lock_path('/tmp/example.lock'), _consolidated_part5_Path('/tmp/example.lock'))

    def test_native_lock_is_exclusive_between_processes_and_releases_on_exit(self):
        import fcntl
        with _consolidated_part5_tempfile.TemporaryDirectory() as folder, _consolidated_part5_patch.object(_consolidated_part5_Path, 'home', return_value=_consolidated_part5_Path(folder)):
            path = _consolidated_part5_runtime_locks.runtime_lock_path('/mnt/c/project/worker.lock')
            path.parent.mkdir(parents=True)
            code = 'import fcntl,sys; f=open(sys.argv[1],"a+b"); fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB)'
            with path.open('a+b') as stream:
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
                blocked = _consolidated_part5_subprocess.run([_consolidated_part5_sys.executable, '-c', code, str(path)], capture_output=True)
                self.assertNotEqual(blocked.returncode, 0)
            self.assertEqual(_consolidated_part5_subprocess.run([_consolidated_part5_sys.executable, '-c', code, str(path)], capture_output=True).returncode, 0)

    def test_existing_publishers_do_not_spawn_more_workers(self):
        root = _consolidated_part5_Path(__file__).resolve().parents[1]
        tree = _consolidated_part5_ast.parse((root / 'dashboard/agents/agent_tools.py').read_text())
        nodes = [n for n in tree.body if isinstance(n, _consolidated_part5_ast.FunctionDef) and n.name in ('run_cf_publish', 'run_naver_publish')]
        launch = _consolidated_part5_Mock(side_effect=AssertionError('Duplicate worker created'))
        scope = dict(Dict=dict, Any=object, CF_DIR=root / 'cf_posting', NAVER_DIR=root / 'naver_blog_posting', _ego_popen=launch)
        exec(compile(_consolidated_part5_ast.Module(body=nodes, type_ignores=[]), '<publisher-admission>', 'exec'), scope)
        with _consolidated_part5_patch('common.system_watchdog.is_process_running_match', return_value=True):
            self.assertEqual(scope['run_cf_publish']('baronote.kr')['status'], 'busy')
            self.assertEqual(scope['run_naver_publish']('soultin')['status'], 'busy')
        launch.assert_not_called()

    def test_project_cycle_rejects_an_existing_worker_before_spawn(self):
        from common import project_autonomy
        with _consolidated_part5_tempfile.TemporaryDirectory() as folder:
            config = _consolidated_part5_Path(folder) / 'project-autonomy.json'
            config.write_text(_consolidated_part5_json.dumps({'enabled': True, 'projects': ['cf_blog']}))
            with _consolidated_part5_patch.object(project_autonomy, 'CONFIG', config), _consolidated_part5_patch('common.system_watchdog.is_process_running_match', return_value=True), _consolidated_part5_patch('server.agent_tools._ego_popen') as launch:
                self.assertEqual(project_autonomy.run_project_cycle('cf_blog')['status'], 'busy')
            launch.assert_not_called()

'Quota bypass regression checks; no model processes or network requests.'

import copy as _consolidated_part6_copy

import json as _consolidated_part6_json

from pathlib import Path as _consolidated_part6_Path

import tempfile as _consolidated_part6_tempfile

import time as _consolidated_part6_time

import unittest as _consolidated_part6_unittest

from unittest.mock import Mock as _consolidated_part6_Mock, patch as _consolidated_part6_patch

from common import agy_fallback as _consolidated_part6_agy_fallback, codex_cli as _consolidated_part6_codex_cli, content_improvement as _consolidated_part6_content_improvement, llm_client as _consolidated_part6_llm_client

class _consolidated_part6_AgyBypassTests(_consolidated_part6_unittest.TestCase):

    def setUp(self):
        self.usage_temp = _consolidated_part6_tempfile.TemporaryDirectory()
        self.addCleanup(self.usage_temp.cleanup)
        meter = _consolidated_part6_patch('common.llm_usage.ROOT', _consolidated_part6_Path(self.usage_temp.name))
        meter.start()
        self.addCleanup(meter.stop)
        from common import hermes_memory
        store = hermes_memory.HermesMemory(_consolidated_part6_Path(self.usage_temp.name) / 'memories')
        isolated = _consolidated_part6_patch.object(hermes_memory, '_store', store)
        isolated.start()
        self.addCleanup(isolated.stop)
        self.addCleanup(store.close)
        delivery = _consolidated_part6_patch('common.crew_chat_bridge._deliver')
        delivery.start()
        self.addCleanup(delivery.stop)
        self.config = {'active': 'agy', 'providers': {'agy': {'model': 'gemini-4-argon-high'}, 'codex': {'model': 'gpt-6-luna'}, 'openai': {'model': 'api-model'}}}
        self.settings = _consolidated_part6_patch.object(_consolidated_part6_llm_client.settings, 'load', side_effect=lambda: _consolidated_part6_copy.deepcopy(self.config))
        self.settings.start()
        self.subprocess = _consolidated_part6_patch('subprocess.run', side_effect=AssertionError('Unexpected subprocess'))
        self.subprocess.start()
        self.codex = _consolidated_part6_patch.object(_consolidated_part6_codex_cli, 'generate', return_value=({'ok': True}, 'actual-codex'))
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
                    result = _consolidated_part6_llm_client.agy_generate('task', 'gemini-4-argon-high', schema)
                elif entry == 'internal':
                    result, _ = _consolidated_part6_llm_client._generate_json('task', 'agy', model_override='bad-agy', response_schema=schema)
                elif entry == 'agent_slot':
                    with _consolidated_part6_patch.object(_consolidated_part6_llm_client.settings, 'get_agent_brain', return_value={'provider': 'agy', 'model': 'bad-agy'}):
                        result = _consolidated_part6_llm_client.generate_json('task', agent_slot='jarvis', response_schema=schema)
                else:
                    result = _consolidated_part6_llm_client.generate_json('task', provider='agy' if entry == 'explicit' else None, model_override='bad-agy', response_schema=schema)
                self.assertEqual(result, {'ok': True})
                self.assertTrue(self.generate.call_args.args[0].endswith('task'))
                self.assertEqual(self.generate.call_args.args[1], 'gpt-6-luna')
                self.assertEqual(self.generate.call_args.args[3], schema)

    def test_observer_records_codex_and_actual_model(self):
        observer = _consolidated_part6_Mock()
        _consolidated_part6_llm_client.generate_json('task', observer=observer)
        self.assertEqual(observer.call_args_list[0].args, ('codex', 'gpt-6-luna', 'calling'))
        self.assertEqual(observer.call_args.kwargs, {'actual_model': 'actual-codex'})
        self.generate.side_effect = RuntimeError('failed')
        with self.assertRaisesRegex(RuntimeError, 'failed'):
            _consolidated_part6_llm_client.generate_json('task', observer=observer)
        self.assertEqual(observer.call_args.args, ('codex', 'gpt-6-luna', 'failed'))

    def test_active_api_route_is_preserved(self):
        response = _consolidated_part6_Mock(status_code=200)
        response.json.return_value = {'status': 'completed', 'model': 'actual-api', 'output': [{'type': 'message', 'content': [{'type': 'output_text', 'text': '{"ok":true}'}]}]}
        with _consolidated_part6_patch.object(_consolidated_part6_llm_client.settings, 'environment_key', return_value='test-key'), _consolidated_part6_patch.object(_consolidated_part6_llm_client.requests, 'post', return_value=response) as post:
            self.assertEqual(_consolidated_part6_llm_client.generate_json('task', provider='openai'), {'ok': True})
        self.assertEqual(post.call_args.kwargs['json']['model'], 'api-model')
        self.generate.assert_not_called()

    def test_credit_exhaustion_uses_codex_preserving_schema_and_observer(self):
        observer = _consolidated_part6_Mock()
        schema = {'type': 'object'}
        with _consolidated_part6_patch.object(_consolidated_part6_llm_client, '_generate_json', side_effect=[RuntimeError('LLM HTTP 402: 잔액 부족'), ({'ok': True}, 'actual-codex')]) as generate:
            result = _consolidated_part6_llm_client.generate_json('credit test', provider='openai', response_schema=schema, images=['actual.png'], observer=observer, _skip_memory=True)
        self.assertEqual(result, {'ok': True})
        self.assertEqual(generate.call_args.args[1], 'codex')
        self.assertEqual(generate.call_args.args[2], ['actual.png'])
        self.assertEqual(generate.call_args.args[4], schema)
        self.assertEqual(observer.call_args.args, ('codex', 'gpt-6-luna', 'returned'))
        with _consolidated_part6_patch.object(_consolidated_part6_llm_client, '_generate_json', side_effect=RuntimeError('LLM HTTP 401: 인증 실패')) as generate:
            with self.assertRaises(RuntimeError):
                _consolidated_part6_llm_client.generate_json('auth test', provider='openai', _skip_memory=True)
            self.assertEqual(generate.call_count, 1)

    def test_openrouter_and_unsupported_local_route_use_real_codex_adapter(self):
        for route in ('openrouter', 'freellm'):
            result = _consolidated_part6_llm_client.generate_json('task', provider=route, model_override='external-only-model', _skip_memory=True)
            self.assertEqual(result, {'ok': True})
            self.assertEqual(self.generate.call_args.args[1], 'gpt-6-luna')

    def test_legacy_text_fallback_uses_codex_and_truthful_ledger(self):
        router = _consolidated_part6_Mock()
        router.prepare.return_value = 'task'
        router.redact.side_effect = lambda text: text
        self.generate.return_value = ({'draft': 'bounded draft'}, 'actual-codex')
        runner = _consolidated_part6_Mock(side_effect=AssertionError('AGY must not run'))
        self.assertEqual(_consolidated_part6_agy_fallback.generate(router, 'task', run=runner), 'bounded draft')
        runner.assert_not_called()
        entry = router.ledger.call_args.args[0]
        self.assertEqual((entry['provider'], entry['returned_model'], entry['status']), ('codex', 'actual-codex', 'ok'))

    def test_editorial_candidates_bypass_external_router_and_remain_audited(self):
        draft = {'title': 'title', 'summary': 'summary', 'contentHtml': '<p>draft</p>', 'newClaims': [], 'resolvedIssueIds': [], 'changes': []}
        self.generate.return_value = (draft, 'actual-codex')
        with _consolidated_part6_tempfile.TemporaryDirectory() as folder, _consolidated_part6_patch.object(_consolidated_part6_content_improvement, 'ROOT', _consolidated_part6_Path(folder)), _consolidated_part6_patch.object(_consolidated_part6_content_improvement, 'provider_record', return_value={}), _consolidated_part6_patch.object(_consolidated_part6_content_improvement, 'routing_module', side_effect=AssertionError('Disabled external router')):
            result, metadata = _consolidated_part6_content_improvement.model_json('writer', 'contract', {}, _consolidated_part6_time.monotonic() + 120)
            self.assertEqual(result, draft)
            self.assertEqual(metadata['provider'], 'codex')
            self.assertEqual(metadata['returnedModel'], 'actual-codex')
            self.assertEqual(_consolidated_part6_json.loads((_consolidated_part6_Path(folder) / metadata['candidateRef']).read_text(encoding='utf-8')), draft)


class ConsolidationBoundaryTests(_consolidated_part0_unittest.TestCase):
    def test_private_files_remain_blocked_after_data_move(self):
        import ast, asyncio
        from types import SimpleNamespace
        from pathlib import Path
        from fastapi import HTTPException, Request
        source = Path(__file__).with_name('runtime').joinpath('main.py').read_text()
        tree = ast.parse(source)
        names = {'protect_internal_files', 'public_channel_snapshot'}
        nodes = [n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name in names]
        for node in nodes: node.decorator_list = []
        scope = dict(Path=Path, Request=Request, HTTPException=HTTPException, DASHBOARD_DIR=Path(__file__).parent)
        exec(compile(ast.Module(body=nodes, type_ignores=[]), '<static-boundary>', 'exec'), scope)
        async def next_response(request):
            from fastapi.responses import Response
            return Response(status_code=200)
        for path in ('/data/revenue.json', '/DATA/revenue.json', '/runtime/main.py', '/data/secure/config.json', '/agents/chat_room.py', '/data/public/kin.json'):
            request = SimpleNamespace(url=SimpleNamespace(path=path))
            response = asyncio.run(scope['protect_internal_files'](request, next_response))
            self.assertEqual(response.status_code, 404, path)
        for name in ('../secure/config.json', 'automation-journal.json', 'secure/key.json'):
            request = SimpleNamespace(url=SimpleNamespace(path='/cf_posting/data/'+name))
            with self.assertRaises(HTTPException): scope['public_channel_snapshot'](request, name)

    def test_reconciliation_waits_for_the_active_publisher(self):
        from unittest.mock import patch
        from dashboard.runtime import worker
        with patch('naver_blog_posting.posting.pipeline_lock', side_effect=RuntimeError('Naver pipeline already running for this project')), patch('dashboard.collectors.naver_public.reconcile') as reconcile:
            self.assertEqual(worker.run_task('naver-monitor'), 0)
            reconcile.assert_not_called()

    def test_legacy_data_aliases_preserve_one_physical_ledger(self):
        from pathlib import Path
        root = Path(__file__).resolve().parents[1]
        for channel, key in [('cf_posting','cf'), ('naver_blog_posting','naver')]:
            self.assertTrue((root/channel/'data').is_symlink())
            self.assertEqual((root/channel/'data').resolve(), (root/'dashboard/data'/key).resolve())


if __name__ == "__main__":
    import unittest
    unittest.main()
