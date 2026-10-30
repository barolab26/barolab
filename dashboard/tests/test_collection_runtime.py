"""Scheduler evidence and collection isolation regressions."""
import json
import os
from pathlib import Path
from types import SimpleNamespace
import subprocess
import sys
import tempfile
import unittest
import datetime as dt
from decimal import Decimal
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'dashboard'))
sys.path.insert(0, str(ROOT))
from common import runtime_recovery as recovery
from dashboard.collectors import revenue
from dashboard.collectors.metrics import collector_lock


class CollectionRuntime(unittest.TestCase):
    def observed(self, rows):
        return patch.object(recovery.subprocess, 'run', return_value=SimpleNamespace(stdout=json.dumps(rows)))

    def test_source_lock_excludes_another_periodic_collector(self):
        with tempfile.TemporaryDirectory() as folder:
            with collector_lock(Path(folder) / 'revenue.lock') as first:
                with collector_lock(Path(folder) / 'revenue.lock') as second:
                    self.assertTrue(first)
                    self.assertFalse(second)

    def test_ego_adpost_uses_bounded_cli_and_existing_space(self):
        payload = {'ok': True, 'account': 'soul5373', 'publisher': '1224849',
                   'blogs': [{'publisherId': '1224849'}], 'medias': [], 'rows': [], 'spaceId': 61}
        with tempfile.TemporaryDirectory() as folder, patch.object(revenue, 'DATA', Path(folder)), \
             patch('shutil.which', return_value='ego-browser.cmd'), \
             patch('subprocess.run', return_value=SimpleNamespace(stdout='CLI preamble\nBAROLAB_ADPOST_RESULT='+json.dumps(payload))) as run:
            rows, publisher, blogs, medias = revenue._adpost_ego_report(dt.date(2026, 10, 1), dt.date(2026, 10, 30), space_id=61)
            state = json.loads((Path(folder)/'secure/adpost-ego-state.json').read_text())
        self.assertEqual(publisher, '1224849')
        self.assertEqual(state['status'], 'completed')
        self.assertTrue(state['taskFinished'])
        self.assertEqual(run.call_args.kwargs['timeout'], 120)
        self.assertEqual(run.call_args.args[0][1:3], ['nodejs', '-e'])

    def test_ego_timeout_preserves_space_and_fences_automatic_retry(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(revenue, 'DATA', Path(folder)), \
             patch('shutil.which', return_value='ego-browser.cmd'), \
             patch('subprocess.run', side_effect=subprocess.TimeoutExpired('ego', 120, output=b'BAROLAB_ADPOST_SPACE=61\n')) as run:
            for space_id in (61, None):
                with self.assertRaises(revenue.RevenueSourceError):
                    revenue._adpost_ego_report(dt.date(2026, 10, 1), dt.date(2026, 10, 30), space_id=space_id)
            state = json.loads((Path(folder)/'secure/adpost-ego-state.json').read_text())
        self.assertEqual(state['spaceId'], 61)
        self.assertEqual(state['status'], 'held')
        run.assert_called_once()

    def test_ego_console_envelope_on_stderr_is_accepted_without_logging_it(self):
        payload = {'ok': True, 'account': 'soul5373', 'publisher': '1224849',
                   'blogs': [{'publisherId': '1224849'}], 'medias': [], 'rows': [], 'spaceId': 61}
        captured = SimpleNamespace(stdout='', stderr='CLI notice\nBAROLAB_ADPOST_RESULT='+json.dumps(payload)+'\n\n')
        with tempfile.TemporaryDirectory() as folder, patch.object(revenue, 'DATA', Path(folder)), \
             patch('shutil.which', return_value='ego-browser.exe'), \
             patch('subprocess.run', return_value=captured):
            _, publisher, _, _ = revenue._adpost_ego_report(dt.date(2026, 10, 1), dt.date(2026, 10, 30), space_id=61)
            state = json.loads((Path(folder)/'secure/adpost-ego-state.json').read_text())
        self.assertEqual(publisher, '1224849')
        self.assertEqual(state['status'], 'completed')
        self.assertNotIn('CLI notice', json.dumps(state))

    def test_ego_timeout_retains_space_marker_from_stderr(self):
        timeout = subprocess.TimeoutExpired('ego', 120, output=b'', stderr=b'BAROLAB_ADPOST_SPACE=61\n')
        with tempfile.TemporaryDirectory() as folder, patch.object(revenue, 'DATA', Path(folder)), \
             patch('shutil.which', return_value='ego-browser.exe'), \
             patch('subprocess.run', side_effect=timeout):
            with self.assertRaises(revenue.RevenueSourceError):
                revenue._adpost_ego_report(dt.date(2026, 10, 1), dt.date(2026, 10, 30))
            state = json.loads((Path(folder)/'secure/adpost-ego-state.json').read_text())
        self.assertEqual(state['spaceId'], 61)
        self.assertEqual(state['status'], 'held')

    def test_ego_wrong_account_is_not_accepted_as_revenue(self):
        payload = {'ok': True, 'account': 'wrong', 'publisher': '1224849', 'spaceId': 61}
        with tempfile.TemporaryDirectory() as folder, patch.object(revenue, 'DATA', Path(folder)), \
             patch('shutil.which', return_value='ego-browser.cmd'), \
             patch('subprocess.run', return_value=SimpleNamespace(stdout='BAROLAB_ADPOST_RESULT='+json.dumps(payload))):
            with self.assertRaises(revenue.RevenueSourceError) as failure:
                revenue._adpost_ego_report(dt.date(2026, 10, 1), dt.date(2026, 10, 30), space_id=61)
        self.assertEqual(failure.exception.status, 'auth_required')

    def test_failed_unified_adpost_read_preserves_all_three_account_amounts(self):
        old = {}
        for index, (account, amount) in enumerate([('soultin', '0'), ('soul5373', '3731'), ('yoon_master', '2259')]):
            old['adpost-'+account] = {'id': 'adpost-'+account, 'category': 'adpost', 'account': account,
                'publisherId': '1224849', 'accountBreakdownVerified': True, 'mediaIds': [index+1],
                'daily': {'2026-10-29': amount}, 'checkedAt': 'old-evidence', 'status': 'collected'}
        sources = [{**old['adpost-soul5373'], 'status': 'browser_unavailable', 'attemptedAt': 'new-attempt'}]
        revenue.preserve_adpost_sources(sources, old)
        revenue.deduplicate_adpost_sources(sources)
        self.assertEqual(len(sources), 3)
        self.assertEqual(sum(Decimal(row['daily']['2026-10-29']) for row in sources), Decimal('5990'))
        self.assertTrue(all(row['checkedAt'] == 'old-evidence' for row in sources))
        self.assertTrue(all(row['status'] == 'browser_unavailable' for row in sources))

    def test_disabled_task_is_not_reported_as_active(self):
        with self.observed([{'name': 'BaroLab-Metrics-Collector', 'state': 'Disabled', 'enabled': False}]):
            rows = recovery.windows_runtime_state('collections')
        collector = next(r for r in rows if r['unit'] == 'barolab-metrics.service')
        self.assertEqual((collector['ActiveState'], collector['UnitFileState']), ('inactive', 'disabled'))
        unmapped = next(r for r in rows if r['unit'] == 'barolab-revenue-refresh.timer')
        self.assertEqual((unmapped['LoadState'], unmapped['ActiveState']), ('not-found', 'unknown'))

    def test_ready_timer_does_not_claim_its_collector_process_is_running(self):
        with self.observed([{'name': 'BaroLab-Metrics-Collector', 'state': 'Ready', 'enabled': True}]):
            rows = recovery.windows_runtime_state('collections')
        timer, service = rows[:2]
        self.assertEqual((timer['ActiveState'], timer['SubState']), ('active', 'waiting'))
        self.assertEqual((service['ActiveState'], service['SubState']), ('inactive', 'waiting'))

    def test_scheduler_query_failure_remains_unknown(self):
        with patch.object(recovery.subprocess, 'run', side_effect=subprocess.TimeoutExpired('scheduler', 15)):
            rows = recovery.windows_runtime_state('collections')
        self.assertEqual(rows[0]['LoadState'], 'unknown')
        self.assertEqual(rows[0]['reason'], 'scheduler_observation_failed')

    def test_unknown_scheduler_state_never_becomes_active(self):
        with self.observed([{'name': 'BaroLab-Metrics-Collector', 'state': 'Unknown', 'enabled': True}]):
            rows = recovery.windows_runtime_state('collections')
        self.assertEqual(rows[0]['ActiveState'], 'unknown')

    def test_disabled_collector_is_not_automatically_restarted(self):
        row = {'unit': 'barolab-metrics.service', 'LoadState': 'loaded', 'UnitFileState': 'disabled'}
        with patch.object(recovery, 'os', SimpleNamespace(name='nt')), \
             patch.object(recovery, 'runtime_state', return_value=[row]), \
             patch('common.work_agenda.enabled', return_value=False), \
             patch.object(recovery.subprocess, 'Popen') as launch:
            result = recovery.recover_project_runtime('collections')
        self.assertEqual(result['status'], 'held')
        launch.assert_not_called()

    def test_observed_running_collector_is_not_launched_twice(self):
        row = {'unit': 'barolab-metrics.service', 'LoadState': 'loaded',
               'UnitFileState': 'enabled', 'SubState': 'running'}
        with patch.object(recovery, 'os', SimpleNamespace(name='nt')), \
             patch.object(recovery, 'runtime_state', return_value=[row]), \
             patch('common.work_agenda.enabled', return_value=False), \
             patch.object(recovery.subprocess, 'Popen') as launch:
            result = recovery.recover_project_runtime('collections')
        self.assertEqual(result['status'], 'already_running')
        launch.assert_not_called()

    def test_scheduler_entrypoint_imports_without_launcher_pythonpath(self):
        env = dict(os.environ)
        env.pop('PYTHONPATH', None)
        result = subprocess.run([sys.executable, '-B', '-m', 'dashboard.server.worker', '--help'],
                                cwd=ROOT, env=env, capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('--task', result.stdout)

    def test_adpost_login_redirect_requires_user_instead_of_submitting_credentials(self):
        from contextlib import nullcontext
        page = SimpleNamespace(url='https://nid.naver.com/login', goto=lambda *a, **k: None)
        with patch.object(revenue, 'ego_action', return_value=nullcontext()), \
             patch.object(revenue, '_adpost_login') as login, \
             self.assertRaises(revenue.RevenueSourceError) as failure:
            revenue._adpost_report(page, {}, 'soul5373', None, None)
        self.assertEqual(failure.exception.status, 'auth_required')
        login.assert_not_called()

    def test_adpost_unauthenticated_report_never_clicks_login(self):
        from contextlib import nullcontext
        from unittest.mock import MagicMock
        page = MagicMock()
        page.url = 'https://adpost.naver.com/main'
        with patch.object(revenue, 'ego_action', return_value=nullcontext()), \
             patch.object(revenue, 'browser_json', return_value={'isLoggedIn': False}), \
             patch.object(revenue, '_adpost_login') as login, \
             self.assertRaises(revenue.RevenueSourceError) as failure:
            revenue._adpost_report(page, {}, 'soul5373', None, None)
        self.assertEqual(failure.exception.status, 'auth_required')
        page.locator.assert_not_called()
        login.assert_not_called()

    def test_launcher_demo_environment_cannot_replace_default_or_compact_evidence(self):
        from dashboard.server import main
        evidence = {'revenue': {'status': 'partial', 'totals': {
            'month': {'amounts': {'USD': '1.88'}, 'complete': False}}}}
        cache = SimpleNamespace(get=lambda *args: evidence)
        with patch.dict(os.environ, {'DEMO_PORTFOLIO_MODE': '1'}), \
             patch.object(main, 'METRICS_READ_CACHE', cache), \
             patch('server.dashboard_cache.compact_metrics', side_effect=lambda value: value):
            self.assertIs(main.get_metrics(), evidence)
            self.assertIs(main.get_metrics(compact=True), evidence)
        self.assertEqual(evidence['revenue']['totals']['month']['amounts']['USD'], '1.88')

    def test_explicit_demo_labels_synthetic_values_and_preserves_cached_evidence(self):
        from dashboard.server import main
        evidence = {'revenue': {'status': 'partial', 'categories': [], 'totals': {
            'month': {'amounts': {'USD': '1.88'}, 'complete': False}}}}
        with patch.object(main, 'METRICS_READ_CACHE', SimpleNamespace(get=lambda *args: evidence)):
            demo = main.get_metrics(demo=True)
        self.assertEqual(demo['dataMode'], 'demo')
        self.assertEqual(demo['revenue']['totals']['month']['amounts']['USD'], '5120.00')
        self.assertEqual(demo['revenue']['totals']['month']['status'], 'demo')
        self.assertFalse(demo['revenue']['totals']['month']['complete'])
        self.assertEqual(evidence['revenue']['totals']['month']['amounts']['USD'], '1.88')


if __name__ == '__main__':
    unittest.main()
