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
        for word in ('MISSION CONTROL', 'AI 구독 한도 & 크레딧', '우분투 격리 크롬 세션', 'PIPELINE', 'VAULT', '[ 4/16]', '25%'):
            self.assertIn(word, text)
        self.assertNotIn('성공 판정 아님', text)

    def test_reported_usage_is_atomic_accumulates_and_resets_on_kst_day(self):
        events = [{'type': 'turn.completed', 'usage': {'input_tokens': 100, 'cached_input_tokens': 70, 'output_tokens': 20}}]
        with _consolidated_part0_tempfile.TemporaryDirectory() as directory:
            root = _consolidated_part0_Path(directory)
            _consolidated_part0_record_codex_usage(events, 'actual-model', root, self.now)
            _consolidated_part0_record_codex_usage(events, 'actual-model', root, self.now)
            path = root / 'dashboard/data/llm-usage.json'
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
        for title in ('MISSION CONTROL', 'AI 구독 한도 & 크레딧', '우분투 격리 크롬 세션', 'PIPELINE', 'ACTIVE CREW', 'VAULT', '[red]Title', '[red]literal'):
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
        self.assertIn('39,263.11 C', text)
        self.assertNotIn('$39,263', text)

    def test_brain_four_rows_and_activity_colors(self):
        now = _consolidated_part1_dt.datetime(2026, 10, 22, 15, tzinfo=_consolidated_part1_ui.KST)
        data = {'usage': {'date': '2026-10-22', 'active': {'one': {'provider': 'codex', 'agentSlot': 'publi', 'startedAt': now.isoformat()}}},
                'agentBrains': {'jarvis': {'model': 'actual-model'}, 'threads_pipeline': {'model': 'thread-model'}},
                'remote': {'openrouter': {'balance': -0.18}}}
        view = _consolidated_part1_view
        display = view.brain_display(data, now)
        self.assertEqual(len(display['rows']), 4)
        self.assertEqual(display['styles'], ['bold cyan', 'dim', 'bold red', 'dim'])
        self.assertIn('@jarvis(actual-model)', display['rows'][3])
        self.assertIn('Threads(thread-model)', display['rows'][3])
        self.assertIn('잔여 —', display['rows'][1])
        self.assertNotIn('사용 중', ''.join(display['rows']))
        rendered = list(view.brain_render(display).renderables)
        self.assertEqual([rendered[3].plain[a:b] for a,b in display['spans']], ['@publi'])
        self.assertEqual(str(rendered[0].style), 'bold cyan')
        self.assertFalse(rendered[3].spans[0].style == 'bold cyan')
        self.assertIn('not dim', str(rendered[3].spans[0].style))
        data['remote']['codexQuota'] = {'buckets': {'codex': {'primary': {'usedPercent': 100}}}}
        self.assertEqual(view.brain_display(data, now)['styles'][0], 'bold red')
        data['usage']['active']['one']['startedAt'] = '2026-10-21T15:00:00+09:00'
        data['remote'].pop('codexQuota')
        self.assertEqual(view.brain_display(data, now)['styles'][0], 'dim')

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
        source = (_consolidated_part2_Path(__file__).parent / 'server/main.py').read_text()
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

    def test_codex_accepts_all_four_channel_audits_and_rejects_private_data(self):
        from common import codex_cli
        from unittest.mock import patch
        from pathlib import Path
        import subprocess
        config={'home':str(self.root/'codex'),'executable':'mock-codex'}
        def run(command,**kwargs):
            Path(command[command.index('--output-last-message')+1]).write_text('{"json":"{\\"ok\\":true}"}')
            return subprocess.CompletedProcess(command,0,'{"type":"turn.completed"}\n','')
        with patch.object(codex_cli,'local_config',return_value=config),patch.object(codex_cli,'is_wsl',return_value=False),patch.object(codex_cli.Path,'home',return_value=self.root),patch.object(codex_cli.jobs,'ROOT',self.root),patch.object(codex_cli.subprocess,'run',side_effect=run):
            for channel in ('cf_posting','naver_blog_posting','naver_kin','threads_posting'):
                result,_=codex_cli.generate_local('task','fixture-model',audit_directory=self.root/channel/'output'/'model-audit',_skip_memory=True)
                self.assertEqual(result,{'ok':True})
            with self.assertRaisesRegex(RuntimeError,'포스팅 산출물'):
                codex_cli.generate_local('task','fixture-model',audit_directory=self.root/'dashboard/data/secure',_skip_memory=True)

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
        return _consolidated_part4_json.loads((self.root / 'dashboard/data/llm_usage_ledger.json').read_text())

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
            first = _consolidated_part5_runtime_locks.runtime_lock_path('/mnt/c/10_Project/BaroLab/dashboard/data/cf/cleaner.lock')
            self.assertTrue(first.is_relative_to('/tmp/native-home/.barolab/locks'))
            self.assertEqual(first, _consolidated_part5_runtime_locks.runtime_lock_path('/mnt/c/10_Project/BaroLab/dashboard/data/cf/cleaner.lock'))
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
            with _consolidated_part5_patch.object(project_autonomy, 'CONFIG', config), _consolidated_part5_patch('common.system_watchdog.is_process_running_match', return_value=True), _consolidated_part5_patch('server.agent_tools._ego_popen') as launch, _consolidated_part5_patch('common.project_autonomy.Path.home', return_value=_consolidated_part5_Path(folder)):
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

    def test_openrouter_uses_real_codex_adapter(self):
        for route in ('openrouter',):
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
        source = Path(__file__).with_name('server').joinpath('main.py').read_text()
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
            request = SimpleNamespace(url=SimpleNamespace(path='/dashboard/data/cf/'+name))
            with self.assertRaises(HTTPException): scope['public_channel_snapshot'](request, name)

    def test_reconciliation_waits_for_the_active_publisher(self):
        from unittest.mock import patch
        from dashboard.server import worker
        with patch('naver_blog_posting.posting.pipeline_lock', side_effect=RuntimeError('Naver pipeline already running for this project')), patch('dashboard.collectors.naver_public.reconcile') as reconcile:
            self.assertEqual(worker.run_task('naver-monitor'), 0)
            reconcile.assert_not_called()

    def test_channel_ledgers_have_no_root_aliases(self):
        root=Path(__file__).resolve().parents[1]
        from cf_posting import posting as cf
        from common import llm_settings
        self.assertEqual(cf.DATA_DIR,root/'dashboard/data/cf')
        self.assertEqual(llm_settings.CONFIG,root/'dashboard/data/llm-settings.json')
        for name in ('server','common','data','skills','.agent-routing'):
            self.assertFalse((root/name).exists(),name)
        self.assertTrue((root/'apps').is_dir())
        self.assertFalse((root/'apps').is_symlink())


class SynapseFlywheelTests(_consolidated_part0_unittest.TestCase):
    def setUp(self):
        import tempfile
        from pathlib import Path
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.data=self.root/'dashboard/data';self.data.mkdir(parents=True)
        self.now=__import__('datetime').datetime(2026,10,23,tzinfo=__import__('datetime').timezone.utc)
    def graph(self):
        return {'nodes':{},'edges':[]}
    def post(self,g,age=1):
        from dashboard.agents import synapse as s
        address='https://example.com/pension-amount'
        published=(self.now-__import__('datetime').timedelta(days=age)).isoformat()
        s.add_post(g,dict(publicUrl=address,title='기초연금 30만원 대상',publishedAt=published,publicPublicationVerified=True,httpStatus=200),dict(contentHtml='<h2>대상</h2><table><tr><td>조건</td></tr></table>',category='연금'))
        return g['nodes'][s.key('post',address)]
    def test_outcome_weight_and_recipe_round_trip(self):
        import json
        from dashboard.agents import synapse as s
        g=self.graph();n=self.post(g)
        n['measurements']['index']={'indexed':True,'checkedAt':(self.now-__import__('datetime').timedelta(hours=1)).isoformat()}
        report=dict(complete=True,checkedAt=self.now.isoformat(),start='2026-10-22',end='2026-10-22',pages=[dict(url=n['url'],clicks=2,impressions=30)])
        s.observe(g,report,'gsc',['clicks','impressions'])
        s.observe(g,{**report,'currency':'USD','pages':[dict(url=n['url'],revenue=.8)]},'adsense',['revenue'])
        s.score(g,self.now)
        self.assertEqual(n['synapseWeight'],16)
        self.assertFalse(n['weightEvidence']['causalClaim'])
        (self.data/'synapse-recipes.json').write_text(json.dumps(s.build_index(g)))
        card=s.recipe('example.com 연금 대상','cf_pipeline',self.root)
        self.assertIn('16.0',card);self.assertLessEqual(len(card.splitlines()),10)
    def test_missing_and_site_only_revenue_never_reward_or_penalize(self):
        from dashboard.agents import synapse as s
        g=self.graph();n=self.post(g,8)
        s.observe(g,dict(complete=True,checkedAt=self.now.isoformat(),total=100,sites=[{'revenue':100}]),'adsense',['revenue'])
        s.score(g,self.now)
        self.assertEqual(n['synapseWeight'],1)
        self.assertIsNone(n['weightEvidence']['pageRevenue'])
    def test_only_explicit_full_week_zero_observation_decays(self):
        from dashboard.agents import synapse as s
        g=self.graph();n=self.post(g,9)
        n['measurements']['gsc']=dict(start='2026-10-15',end='2026-10-21',clicks=0)
        s.score(g,self.now);self.assertEqual(n['synapseWeight'],-4)
        s.score(g,self.now);self.assertEqual(n['synapseWeight'],-4)
    def test_question_identity_survives_query_canonicalization(self):
        from dashboard.agents import synapse as s
        first=s.url('https://kin.naver.com/qna/detail.naver?docId=123&trackingCode=secret')
        second=s.url('https://kin.naver.com/qna/detail.naver?docId=456')
        self.assertNotEqual(first,second)
        self.assertIn('docId=123',first);self.assertNotIn('trackingCode',first)
        self.assertEqual(s.url('https://10.0.0.1/private'),'')

    def test_query_memory_is_account_scoped_and_never_changes_other_topics(self):
        import json
        from dashboard.agents import synapse as s
        (self.data/'synapse-recipes.json').write_text(json.dumps({'queryHints':[{'account':'adinfo0905','originalQuery':'broad query','preferredQuery':'official query'}]}))
        self.assertEqual(s.research_query('broad query',self.root/'adinfo0905/output',self.root),'official query')
        self.assertEqual(s.research_query('broad query',self.root/'other/output',self.root),'broad query')
        self.assertEqual(s.research_query('different',self.root/'adinfo0905/output',self.root),'different')

    def test_card_audit_creates_the_output_directory_before_provider(self):
        from unittest.mock import patch
        from dashboard.agents import synapse as s
        folder=self.root/'naver_blog_posting/output/draft/model-audit'
        with patch.object(s,'ROOT',self.root):s.audit_card('observed recipe',folder)
        self.assertTrue((folder/'synapse-card.json').is_file())

    def test_public_monitor_does_not_relearn_the_same_url_each_poll(self):
        import json
        from unittest.mock import patch
        from dashboard.collectors import naver_public as collector
        base=self.root/'naver_blog_posting';base.mkdir()
        dashboard=self.root/'dashboard'
        now=self.now.astimezone(collector.KST)
        address='https://blog.naver.com/mustpickinfo/123'
        (dashboard/'data/naver').mkdir(parents=True,exist_ok=True)
        (dashboard/'data/naver/public-verification.json').write_text(json.dumps({'evidence':[{'publicUrl':address,'checkedAt':now.isoformat()}]}))
        with patch.object(collector,'DEFAULT_ACCOUNTS',{}),patch('common.llm_client.memory_event') as event:
            result=collector.reconcile(base,now=now,force=True)
        self.assertEqual(result['totalVerifiedEvidence'],1)
        event.assert_not_called()

    def test_resolution_feedback_supersedes_only_the_unsent_failed_artifact(self):
        import json
        from dashboard.agents import synapse as s
        failed=self.root/'naver_blog_posting/output/adinfo0905/failed';good=failed.with_name('recovered')
        for folder in (failed,good):
            folder.mkdir(parents=True)
            (folder/'identity.json').write_text(json.dumps({'account':'adinfo0905','blogId':'adinfo0905'}))
        (failed/'photo-plan.json').write_text(json.dumps({'signoff':''}))
        (good/'photo-plan.json').write_text(json.dumps({'signoff':'감사합니다.'}))
        (good/'reservation-evidence.json').write_text(json.dumps({'submissionStatus':'verified_reserved','reserveTime':'2026-10-23 11:00','verifiedAt':'2026-10-23T01:00:00+09:00','title':'근거 있는 안내','verificationSource':'actual-reservation-list'}))
        journal=self.data/'naver/automation-journal.json';journal.parent.mkdir()
        bad=dict(account='adinfo0905',artifactFolder=str(failed),phase='failed',submissionStarted=False,workDate='2026-10-23',updatedAt='2026-10-23T00:00:00+09:00')
        uncertain={**bad,'phase':'unknown','submissionStarted':True}
        journal.write_text(json.dumps({'attempts':[bad,uncertain,dict(account='adinfo0905',artifactFolder=str(good),phase='verified')]}))
        s.refresh_once(self.root,force=True)
        graph=s.read(self.data/'memory_graph.json')
        lesson=next(n for n in graph['nodes'].values() if n['type']=='FailureLesson')
        self.assertEqual(lesson['resolvedCount'],1)
        self.assertFalse(lesson['concreteExamples'][0]['publicVerified'])
        attempts=s.read(journal)['attempts']
        self.assertEqual(attempts[0]['phase'],'superseded')
        self.assertEqual(attempts[1]['phase'],'unknown')
        s.refresh_once(self.root,force=True)
        self.assertEqual(next(n for n in s.read(self.data/'memory_graph.json')['nodes'].values() if n['type']=='FailureLesson')['resolvedCount'],1)

    def test_cross_channel_links_use_verified_body_and_keep_unknown_publish_date(self):
        import json,sqlite3,hashlib
        from dashboard.agents import synapse as s
        body='확인된 기초연금 신청 대상과 준비 방법입니다.'*20
        (self.data/'metrics.json').write_text(json.dumps({'sites':{'example.com':{}}}))
        document={'question':{'question_url':'https://kin.naver.com/qna/detail.naver?docId=123','title':'기초연금 신청 대상'},'article':{'url':'https://example.com/pension','body':body,'body_sha256':hashlib.sha256(body.encode()).hexdigest(),'http_status':200,'checked_at':self.now.isoformat()}}
        with sqlite3.connect(self.data/'kin.sqlite3') as db:
            db.execute('CREATE TABLE questions(state,document,answer_url,updated_at)')
            db.execute('INSERT INTO questions VALUES(?,?,?,?)',('published_verified',json.dumps(document),'https://kin.naver.com/qna/detail.naver?docId=123&answerNo=1',self.now.isoformat()))
        graph=s.ingest(self.graph(),self.root)
        post=graph['nodes'][s.key('post','https://example.com/pension')]
        self.assertIsNone(post['publishedAt'])
        self.assertTrue(any(e['type']=='links_to' and e['target']==s.key('post',post['url']) for e in graph['edges']))
        self.assertTrue(any(e['type']=='answers_observed_question' for e in graph['edges']))
        pattern=next(n for n in graph['nodes'].values() if n['type']=='Pattern')
        self.assertIsNone(pattern['pattern']['headingCount'])

    def test_reservation_is_never_a_public_post(self):
        from dashboard.agents import synapse as s
        g=self.graph();s.add_post(g,dict(publicUrl='https://example.com/a',submissionStatus='verified_reserved',httpStatus=200))
        self.assertFalse(g['nodes'])
    def test_corrupt_index_uses_cache_and_never_blocks_generation(self):
        import json
        from dashboard.agents import synapse as s
        g=self.graph();self.post(g);s.score(g,self.now)
        path=self.data/'synapse-recipes.json';path.write_text(json.dumps(s.build_index(g)))
        good=s.recipe('example.com','publi',self.root)
        path.write_text('{')
        self.assertEqual(s.recipe('example.com','publi',self.root),good)
        self.assertEqual(s.recipe('example.com','jarvis',self.root),'')
    def test_winner_doctor_selection_is_after_publication_only(self):
        import json
        from dashboard.agents import synapse as s
        g=self.graph();n=self.post(g,4)
        n['measurements']['gsc']=dict(impressions=10,clicks=1,checkedAt=self.now.isoformat())
        s.score(g,self.now)
        (self.data/'memory_graph.json').write_text(json.dumps(g))
        jobs=[{'url':n['url']},{'url':'https://example.com/unmeasured'}]
        self.assertEqual(s.winner_jobs(jobs,self.root),jobs[:1])
        self.assertEqual(g['doctorPlans'][0]['baseline'],n['measurements'])
    def test_automatic_coding_cannot_modify_frozen_engine(self):
        from common.coding_job import _file
        with self.assertRaisesRegex(ValueError,'Frozen'):_file(self.root,'cf_posting/posting.py')
    def test_shared_injection_precedes_provider_and_engine_hash_is_unchanged(self):
        import inspect
        from common import llm_client
        from pathlib import Path
        import hashlib,subprocess
        self.assertIn("recipe(prompt, kwargs.get('agent_slot'))",inspect.getsource(llm_client.memory_call))
        root=Path(__file__).resolve().parents[1]
        for channel in ('cf_posting','naver_blog_posting','naver_kin','threads_posting'):
            relative=channel+'/posting.py'
            before=bytes.fromhex(__import__('json').loads((root/'dashboard/agents/frozen-engines.json').read_text())['hashes'][channel])
            self.assertEqual(before.hex(),hashlib.sha256((root/relative).read_bytes()).hexdigest())


class SynapseExecutionTests(_consolidated_part0_unittest.TestCase):
    setUp=SynapseFlywheelTests.setUp
    graph=SynapseFlywheelTests.graph
    post=SynapseFlywheelTests.post
    def test_real_provider_boundary_to_mocked_publish_and_memory_feedback(self):
        import json
        from pathlib import Path
        from types import SimpleNamespace
        from unittest.mock import patch,Mock
        from dashboard.agents import synapse as s
        from common import llm_client,hermes_memory
        from cf_posting import posting
        g=self.graph();self.post(g);s.score(g,self.now)
        (self.data/'synapse-recipes.json').write_text(json.dumps(s.build_index(g)))
        captured=[]
        article=dict(title='연금 대상 확인',summary='확인할 조건',category='연금',topicSlug='pension-check',contentHtml='<h2>대상</h2><p>공식 안내를 확인합니다.</p>')
        original_recipe=s.recipe
        def provider(prompt,**kwargs):captured.append(prompt);return article
        store=SimpleNamespace(experience_context=lambda *a:{'text':'','selected':[]})
        with patch('common.crew_chat_bridge.model_crew_call',side_effect=lambda f:f),patch.object(s,'recipe',side_effect=lambda p,slot:original_recipe(p,slot,self.root)),patch.object(hermes_memory,'frozen_session_context',return_value='snapshot'),patch.object(hermes_memory,'skill_context',return_value=''),patch.object(hermes_memory,'_store',store),patch.object(llm_client,'memory_event'):
            document=llm_client.memory_call(provider)('example.com 연금 대상',agent_slot='cf_pipeline',memory_read_only=True)
        self.assertIn('승리 시냅스',captured[0])
        folder=self.root/'cf_posting/output/test-result';folder.mkdir(parents=True)
        posted=Mock(status_code=201);posted.json.return_value={'post':{'id':23,'slug':'pension-check'}}
        public=Mock(status_code=200,text='<h1>연금 대상 확인</h1>')
        with patch.object(posting,'registered_categories',return_value=['연금']),patch.object(posting,'published_inventory',return_value=[]),patch.object(posting,'get_api_key',return_value='test-only'),patch.object(posting.requests,'post',return_value=posted) as send,patch.object(posting.requests,'get',return_value=public):
            receipt=posting.publish_basic_article('example.com',document,folder)
        self.assertTrue(receipt['publicPublicationVerified']);send.assert_called_once()
        (folder/'article.json').write_text(json.dumps(article))
        (self.data/'cf').mkdir()
        (self.data/'cf/daily_schedule.json').write_text(json.dumps({'items':[{'artifactFolder':'output/test-result'}]}))
        g=s.ingest(self.graph(),self.root)
        node=g['nodes'][s.key('post',receipt['publicUrl'])]
        node['measurements']['gsc']={'clicks':2,'impressions':30,'checkedAt':self.now.isoformat()}
        node['measurements']['adsense']={'revenue':1,'currency':'USD','checkedAt':self.now.isoformat()}
        s.score(g,self.now);weight=node['synapseWeight'];s.score(g,self.now)
        self.assertEqual(weight,node['synapseWeight']);self.assertGreater(weight,1)
        (self.data/'synapse-recipes.json').write_text(json.dumps(s.build_index(g)))
        self.assertIn('examples',s.recipe('example.com 연금','cf_pipeline',self.root))
    def test_doctor_before_after_uses_equal_nonoverlapping_windows(self):
        import sqlite3
        from dashboard.agents import synapse as s
        g=self.graph();node=self.post(g,4)
        node['measurements']['gsc']=dict(clicks=1,impressions=10,start='2026-10-20',end='2026-10-21',checkedAt=self.now.isoformat())
        s.score(g,self.now);s.record_boosts(g,self.root)
        with sqlite3.connect(self.data/'growth.sqlite3') as db:
            db.execute('CREATE TABLE maintenance_jobs(url,completed_at,action_id,status)')
            db.execute('INSERT INTO maintenance_jobs VALUES(?,?,?,?)',(node['url'],'2026-10-22T10:00:00+00:00','actual-action','completed'))
        node['measurements']['gsc']=dict(clicks=3,impressions=20,start='2026-10-24',end='2026-10-25',checkedAt='2026-10-26T00:00:00+00:00')
        s.record_boosts(g,self.root)
        boost=g['nodes'][s.key('boost',node['url'])]
        self.assertEqual(boost['observedDeltas']['gsc:clicks'],2)
        self.assertFalse(boost['causalClaim'])


class SharedMissionSnapshotTests(_consolidated_part0_unittest.TestCase):
    def test_web_and_monitor_read_exactly_the_same_safe_revision(self):
        import json,tempfile
        from pathlib import Path
        from unittest.mock import patch
        from server import main,mission_control as mc
        now=_consolidated_part0_dt.datetime(2026,10,23,9,tzinfo=mc.KST)
        data=dict(collectedAt=now.timestamp(),channels=mc.channels({'date':'2026-10-23','items':[{'status':'published','publicUrl':'https://example.com/a'}]}, {'date':'2026-10-23'}, {'daily':{'date':'2026-10-23','publishedVerified':2}},now),
            crew=mc.crew_rows([],[],{},now),synapses={'nodes':{'p':{'resolvedCount':3}},'edges':[]},
            events=[{'private':'DO_NOT_EXPORT'}],cf={'secret':'DO_NOT_EXPORT'},naver={'accounts':[{'account':'a','accId':'acc1','expected':1,'slots':[{'publicationDate':'2026-10-23','publicationStatus':'reserved','secret':'DO_NOT_EXPORT'}]}]})
        data.update(naverWorkflow={'schema':'naver-active-workflow-v1','workerId':'worker','artifactFolder':'DO_NOT_EXPORT'},naverJournal={'attempts':[{'account':'soultin','phase':'started','artifactFolder':'DO_NOT_EXPORT','apiKey':'DO_NOT_EXPORT'}]})
        snapshot=mc.shared_snapshot(data)
        self.assertNotIn('DO_NOT_EXPORT',json.dumps(snapshot))
        self.assertEqual(len(snapshot['panels']),6)
        self.assertEqual(snapshot['naverLive']['workflow']['workerId'],'worker')
        self.assertEqual(snapshot['naverLive']['journal']['attempts'][0]['phase'],'started')
        self.assertEqual(snapshot['naverAccounts'][0]['slots'][0]['publicationStatus'],'reserved')
        self.assertEqual(snapshot['vault'],dict(nodes=1,edges=0,episodes=3))
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);target=root/'dashboard/data';target.mkdir(parents=True)
            path=target/'live_snapshot.json';path.write_text(json.dumps(snapshot))
            reader=mc.SnapshotReader(root)
            with patch.object(main,'DATA_DIR',target),patch.object(main,'refresh_live_snapshot',side_effect=AssertionError('Reader re-aggregated')):
                self.assertEqual(main.get_live_snapshot(),reader.get())
            path.write_text('{')
            self.assertEqual(reader.get(),snapshot)
            self.assertIsNone(reader.thread)
    def test_readonly_collector_lock_does_not_mean_naver_is_publishing(self):
        import tempfile
        from pathlib import Path
        from unittest.mock import patch
        from naver_blog_posting import posting as naver
        now=naver.now_kst()
        journal={'version':1,'attempts':[{'account':'stone0747','workDate':now.date().isoformat(),'phase':'started'}]}
        with tempfile.TemporaryDirectory() as directory:
            base=Path(directory)/'naver_blog_posting';base.mkdir()
            with patch.object(naver,'read_journal',return_value=journal),patch.object(naver,'pipeline_busy',return_value=True),patch('common.system_watchdog.is_process_running_match',return_value=False):
                self.assertEqual(naver.monitor(base,now)['counts']['running'],0)
            with patch.object(naver,'read_journal',return_value=journal),patch.object(naver,'pipeline_busy',return_value=True),patch('common.system_watchdog.is_process_running_match',return_value=True):
                self.assertEqual(naver.monitor(base,now)['counts']['running'],1)

    def test_memory_page_counts_every_central_node_and_relation(self):
        import tempfile,json
        from pathlib import Path
        from unittest.mock import patch
        from server import memory_graph as memory
        with tempfile.TemporaryDirectory() as directory:
            data=Path(directory)
            graph={'nodes':{'hub':{'type':'MemoryHub'},'post':{'type':'Post','title':'공개 가이드','secret':'PRIVATE'}},
                   'edges':[{'source':'hub','target':'post','type':'contains'},{'source':'hub','target':'post','type':'resolved'}]}
            (data/'memory_graph.json').write_text(json.dumps(graph))
            with patch.object(memory,'DATA_DIR',data):
                projection=memory._synapse_graph()
                self.assertEqual(projection['stats']['total'],2)
                self.assertEqual(projection['stats']['links'],2)
                self.assertEqual(projection['stats']['isolated'],0)
                self.assertNotIn('PRIVATE',json.dumps(projection))
                self.assertFalse(projection['nodes'][1]['verifiedKnowledge'])

    def test_daily_retry_counts_do_not_become_completed_slot_counts(self):
        import sqlite3,tempfile
        from pathlib import Path
        from server import mission_control as mc
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);data=root/'dashboard/data';data.mkdir(parents=True)
            path=data/'kin.sqlite3'
            with sqlite3.connect(path) as db:
                db.execute('CREATE TABLE automation_slots(state,planned_at)')
                db.executemany('INSERT INTO automation_slots VALUES(?,?)',[('blocked','2026-10-22T16:00:00Z'),('blocked','2026-10-22T16:00:01Z'),('blocked','2026-10-22T01:00:00Z')])
            collector=mc.Collector(root)
            states=collector.operation_states('kin.sqlite3','automation_slots','2026-10-23',True)
            self.assertEqual(states,{'blocked':2})
            now=_consolidated_part0_dt.datetime(2026,10,23,tzinfo=mc.KST)
            snapshot=mc.shared_snapshot(dict(collectedAt=now.timestamp(),channels=mc.channels({}, {}, {'daily':{'date':'2026-10-23','publishedVerified':0}},now),kinOperations=states))
            kin=next(r for r in snapshot['channels'] if r['id']=='kin')
            self.assertEqual(kin['counts']['completed'],0)
            self.assertEqual(kin['counts']['waiting'],20)
            self.assertEqual(kin['blockedAttempts'],2)
            path.unlink()
            self.assertEqual(collector.operation_states('kin.sqlite3','automation_slots','2026-10-23',True),states)
            self.assertIsNone(collector.operation_states('kin.sqlite3','automation_slots','2026-10-24',True))
            unknown=mc.shared_snapshot(dict(collectedAt=now.timestamp(),channels=mc.channels({}, {}, {'daily':{'date':'2026-10-23','publishedVerified':0}},now)))
            self.assertIsNone(unknown['channels'][2]['counts']['failed'])

    def test_real_terminal_height_wins_over_inherited_shell_size(self):
        import os,pty,fcntl,termios,struct,subprocess,sys
        master,slave=pty.openpty()
        try:
            fcntl.ioctl(slave,termios.TIOCSWINSZ,struct.pack('HHHH',70,120,0,0))
            code="from server import mission_control as m; m.render=lambda data,now=None,height=0:'REAL_TERMINAL_HEIGHT='+str(height); m.main(['--once'])"
            child=subprocess.Popen([sys.executable,'-B','-c',code],stdin=subprocess.DEVNULL,stdout=slave,stderr=subprocess.PIPE,
                env={**os.environ,'LINES':'24','COLUMNS':'80','PYTHONDONTWRITEBYTECODE':'1'})
            child.wait(timeout=10)
            output=os.read(master,4096)
            self.assertEqual(child.returncode,0,child.stderr.read())
            self.assertIn(b'REAL_TERMINAL_HEIGHT=70',__import__('re').sub(rb'\x1b\[[0-9;]*m',b'',output))
        finally:os.close(master);os.close(slave)

    def test_shared_frame_uses_all_rows_at_multiple_heights(self):
        from server.cockpit_panels import render_snapshot
        from rich.console import Console
        import io
        snapshot={'schema':'barolab-mission-control-v2','date':'2026-10-23','revision':'a'*64,'panels':[['행']]*6}
        for height in (32,70,95):
            output=io.StringIO();console=Console(file=output,width=100,height=height)
            console.print(render_snapshot(snapshot,_consolidated_part0_dt.datetime.now(),height))
            self.assertEqual(len(output.getvalue().splitlines()),height)


class IndependentChannelDispatchTests(__import__('unittest').TestCase):
    def test_active_cf_request_does_not_starve_other_channels(self):
        import tempfile,json,hashlib
        from pathlib import Path
        from unittest.mock import patch
        from common import project_autonomy as autonomy
        from server import agent_tools
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);config=root/'config.json';state=root/'state.json';requests=root/'requests';requests.mkdir()
            config.write_text(json.dumps({'enabled':True,'projects':['cf_blog','threads']}))
            state.write_text(json.dumps({'mode':'basic-one-pass','projects':{'cf_blog':{'requestId':'cf-active','lastStartedAt':1}}}))
            (requests/(hashlib.sha256(b'cf-active').hexdigest()+'.json')).write_text(json.dumps({'status':'awaiting_completion'}))
            with patch.object(autonomy,'CONFIG',config),patch.object(autonomy,'STATE',state),patch.object(autonomy.Path,'home',return_value=root),patch.object(agent_tools,'STAFF_REQUEST_DIR',requests),patch.object(agent_tools,'enqueue_staff_request') as enqueue,patch('common.crew_chat_bridge.emit_work_event'):
                self.assertTrue(autonomy.process_project_autonomy_once())
                self.assertEqual(enqueue.call_args.args[1][0]['args']['project'],'threads')
                self.assertEqual(json.loads(state.read_text())['projects']['cf_blog']['requestId'],'cf-active')


class EgoAlertBusTests(__import__('unittest').TestCase):
    def test_deduplicated_ordered_inspection_never_resubmits(self):
        import tempfile, datetime
        from pathlib import Path
        from unittest.mock import patch
        from common import ego_alerts as alerts
        now=datetime.datetime(2026,10,23,12,0,tzinfo=alerts.KST)
        row={'question_id':'q1','account':'adinfo0905','state':'publishing',
             'updated_at':(now-datetime.timedelta(seconds=181)).isoformat(),
             'title':'국민연금 수령 나이'}
        with tempfile.TemporaryDirectory() as folder, patch('common.crew_chat_bridge.emit_pipeline_crew_message',side_effect=lambda *a,**k:k['msg_id']) as emit, patch('server.agent_tools.enqueue_staff_request',return_value={'requestId':'test'}) as enqueue:
            result=alerts.observe({'kinOperationsRows':[row]},Path(folder),now)
            self.assertTrue(result['submissionUncertain'])
            self.assertIsNone(alerts.observe({'kinOperationsRows':[row]},Path(folder),now))
            self.assertEqual(emit.call_count,1)
            actions=enqueue.call_args.args[1]
            self.assertEqual([a['agent'] for a in actions],['jarvis','patch','trace'])
            self.assertTrue(all(a['tool']=='read_agent_status' for a in actions))

    def test_stale_or_successful_captcha_and_open_tabs_are_not_failures(self):
        import datetime
        from common import ego_alerts as alerts
        now=datetime.datetime(2026,10,23,12,0,tzinfo=alerts.KST)
        row={'question_id':'q1','account':'adinfo0905','state':'failed',
             'updated_at':'2026-10-22T12:00:00+09:00','reason':'captcha'}
        data={'kinOperationsRows':[row], 'remote':{'fleet':[{'port':9231,'account':'adinfo0905','online':False,'tabs':[{'title':'국민연금'}]}]}}
        self.assertEqual(list(alerts.incidents(data,now)),[])
        row.update(state='published_verified',updated_at=now.isoformat())
        self.assertEqual(list(alerts.incidents(data,now)),[])
        row.update(state='failed')
        self.assertEqual(list(alerts.incidents(data,now))[0]['cause'],'captcha')

    def test_visible_captcha_is_reported_without_clicking_or_old_tab_inference(self):
        import datetime
        from common import ego_alerts as alerts
        now=datetime.datetime(2026,10,23,12,0,tzinfo=alerts.KST)
        data={'remote':{'fleet':[{'port':9231,'account':'adinfo0905','online':True,'tabs':[{'id':'tab1','questionId':'123456789','captchaVisible':True}]}]}}
        rows=list(alerts.incidents(data,now));self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]['cause'],'captcha')
        data['remote']['fleet'][0]['tabs'][0]['captchaVisible']=False
        self.assertEqual(list(alerts.incidents(data,now)),[])

    def test_numeric_kin_ticket_uses_guarded_helper_except_captcha(self):
        import tempfile, datetime
        from pathlib import Path
        from unittest.mock import patch
        from common import ego_alerts as alerts
        now=datetime.datetime(2026,10,23,12,0,tzinfo=alerts.KST)
        row={'question_id':'492662135','account':'adinfo0905','state':'publishing',
             'updated_at':(now-datetime.timedelta(seconds=181)).isoformat()}
        for protected in (False, True):
            row['reason']='captcha' if protected else ''
            with tempfile.TemporaryDirectory() as folder, patch('common.crew_chat_bridge.emit_pipeline_crew_message',side_effect=lambda *a,**k:k['msg_id']), patch('server.agent_tools.enqueue_staff_request',return_value={'requestId':'test'}) as enqueue:
                alerts.observe({'kinOperationsRows':[row]},Path(folder),now)
                action=enqueue.call_args.args[1][1]
                self.assertEqual(action['tool'],'read_agent_status' if protected else 'repair_kin_submission')
                if not protected:
                    self.assertEqual(action['args'],{'account':'adinfo0905','question_id':'492662135'})

    def test_candidate_answer_url_is_not_publication_proof(self):
        import datetime
        from common import ego_alerts as alerts
        now=datetime.datetime(2026,10,23,12,0,tzinfo=alerts.KST)
        row={'question_id':'123456789','state':'submitted_unverified','account':'adinfo0905','answer_url':'https://kin.naver.com/qna/detail.naver?docId=123456789','updated_at':(now-datetime.timedelta(seconds=181)).isoformat()}
        self.assertEqual(list(alerts.incidents({'kinOperationsRows':[row]},now))[0]['cause'],'submission_unknown')
        workflow={'account':'soultin','status':'running','observedAt':now.isoformat(),'progress':{'updatedAt':'11:50:00','workDate':'2026-10-23'}}
        self.assertEqual(list(alerts.incidents({'naverWorkflow':workflow},now))[0]['cause'],'editor_stalled')

    def test_current_cf_api_error_and_three_minute_boundary(self):
        import datetime
        from common import ego_alerts as alerts
        now=datetime.datetime(2026,10,23,12,0,tzinfo=alerts.KST)
        cf={'domain':'example.com','status':'failed','lastError':'HTTP 503', 'updatedAt':now.isoformat()}
        self.assertEqual(list(alerts.incidents({'cf':{'date':'2026-10-23','items':[cf]}},now))[0]['cause'],'api_error')
        row={'question_id':'q1','state':'prepared','account':'adinfo0905','updated_at':(now-datetime.timedelta(seconds=179)).isoformat()}
        self.assertEqual(list(alerts.incidents({'kinOperationsRows':[row]},now)),[])
        row['updated_at']=(now-datetime.timedelta(seconds=180)).isoformat()
        self.assertEqual(list(alerts.incidents({'kinOperationsRows':[row]},now))[0]['cause'],'editor_stalled')


class BoundedNaverPublicTests(__import__('unittest').TestCase):
    def test_verified_old_or_recent_body_proof_is_not_refetched_or_redated(self):
        import tempfile,json,datetime
        from pathlib import Path
        from unittest.mock import patch
        from dashboard.collectors import naver_public as collector
        now=datetime.datetime(2026,10,23,12,0,tzinfo=collector.KST)
        for day,checked in [('2026-10-22','2026-10-22T12:00:00+09:00'),('2026-10-23','2026-10-23T11:40:00+09:00')]:
            with tempfile.TemporaryDirectory() as folder:
                root=Path(folder);base=root/'naver_blog_posting';base.mkdir();data=root/'dashboard/data/naver';data.mkdir(parents=True)
                url='https://blog.naver.com/mustpickinfo/123'
                prior={'publicUrl':url,'publicHttpStatus':200,'publicPublicationVerified':True,'checkedAt':checked,'publicBodySha256':'real-body-hash','bodyVerificationStatus':'matched'}
                (data/'public-verification.json').write_text(json.dumps({'evidence':[prior]}))
                collector._save_pipeline_status(data/'pipeline_status.js',{'completedAccounts':{'acc1':{'topic':'실제 글 제목','publicationDate':day,'publicPublicationVerified':True,'publicUrl':url}}})
                rss=[{'publicUrl':url,'blogId':'mustpickinfo','publicationDate':day,'title':'실제 글 제목','publishedAt':day+'T11:00:00+09:00'}]
                with patch.object(collector,'DEFAULT_ACCOUNTS',{'soultin':{'acc_id':'acc1','blog_id':'mustpickinfo'}}),patch.object(collector,'_LAST_RECONCILE_TS',0),patch.object(collector,'fetch_blog_rss',return_value=rss),patch.object(collector,'verify_public_body') as body:
                    collector.reconcile(base,now=now)
                    body.assert_not_called()
                result=json.loads((data/'public-verification.json').read_text())['evidence'][0]
                self.assertEqual(result['checkedAt'],checked)
                self.assertEqual(result['publicBodySha256'],'real-body-hash')

    def test_normal_cycle_limits_new_body_requests_and_marks_remaining_deferred(self):
        import tempfile,json,datetime
        from pathlib import Path
        from unittest.mock import patch
        from dashboard.collectors import naver_public as collector
        now=datetime.datetime(2026,10,23,12,0,tzinfo=collector.KST)
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);base=root/'naver_blog_posting';base.mkdir();data=root/'dashboard/data/naver';data.mkdir(parents=True)
            rss=[{'publicUrl':'https://blog.naver.com/mustpickinfo/'+str(n),'blogId':'mustpickinfo','publicationDate':'2026-10-23','title':'실제 글 제목'+str(n),'publishedAt':'2026-10-23T11:00:00+09:00'} for n in range(5)]
            journal={'attempts':[{'account':'soultin','phase':'verified','topic':r['title'],'publicationDate':'2026-10-23'} for r in rss]}
            (data/'automation-journal.json').write_text(json.dumps(journal))
            with patch.object(collector,'DEFAULT_ACCOUNTS',{'soultin':{'acc_id':'acc1','blog_id':'mustpickinfo'}}),patch.object(collector,'_LAST_RECONCILE_TS',0),patch.object(collector,'fetch_blog_rss',return_value=rss),patch.object(collector,'verify_public_body',return_value={'publicHttpStatus':200,'bodyVerificationStatus':'unknown'}) as body,patch('dashboard.agents.work_learning.learn_naver_public'),patch('common.llm_client.memory_event'):
                result=collector.reconcile(base,now=now)
            self.assertEqual(body.call_count,2)
            self.assertEqual(result['updated'],2)
            saved=json.loads((data/'public-verification.json').read_text())['evidence']
            self.assertEqual(sum(e['publicPublicationVerified'] for e in saved),2)
            self.assertEqual(sum(e.get('bodyVerificationStatus')=='deferred' for e in saved),3)

    def test_automatic_api_honors_reconciliation_cooldown(self):
        import inspect
        from server.main import verify_naver_public
        self.assertIn('reconcile(NAVER_DIR, force=False)',inspect.getsource(verify_naver_public))


if __name__ == "__main__":
    import unittest
    unittest.main()
