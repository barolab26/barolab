"""Regression tests for evidence semantics and durable multi-process history."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
import json
import multiprocessing
import tempfile
import unittest
from common import collection_observability as o
NOW = datetime(2026, 10, 15, 5, tzinfo=timezone.utc)

def runtime(run='one', now=NOW, ok=True):
    return {'runId': run, 'startedAt': o.stamp(now - timedelta(seconds=30)), 'stages': [{'status': 'completed' if ok else 'failed', 'exitCode': 0 if ok else 1}]}

def source(status='success', now=NOW, **values):
    return {'source': 'gsc:example.com', 'scope': 'comparison-toprows', 'status': status, 'attemptedAt': o.stamp(now - timedelta(seconds=10)), 'lastSuccessAt': o.stamp(now), 'complete': True, 'stale': False, 'period': {'start': '2026-09-14', 'end': '2026-10-11'}, **values}

def concurrent_writer(folder, run):
    o.finish_run(folder, runtime(run), [source()], now=NOW)

class EvidenceTests(unittest.TestCase):

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)

    def finish(self, outcomes, run='one', now=NOW):
        return o.finish_run(self.folder, runtime(run, now), outcomes, now=now)

    def test_channel_measurement_adapters_preserve_incomplete_results(self):
        folder = self.folder / 'dashboard/data'
        folder.mkdir(parents=True)
        for script, filename in [('naver_kin.posting', 'kin-measurement.json'), ('threads_posting.posting', 'threads-measurement.json')]:
            o.write(folder / filename, {'checkedAt': o.stamp(NOW), 'status': 'partial', 'complete': False})
            row = o.snapshot_outcomes(self.folder, script)[0]
            self.assertEqual(row['status'], 'partial')
            self.assertFalse(row['complete'])
            self.assertIsNone(row['lastSuccessAt'])

    def test_process_zero_is_not_source_success(self):
        health = self.finish([source('failed', complete=False)])
        self.assertEqual(health['processStatus'], 'success')
        self.assertEqual(health['collectionStatus'], 'failed')
        self.assertIsNone(health['sources'][0]['verifiedLastSuccessAt'])

    def test_partial_missing_and_incomplete_are_not_success(self):
        self.assertEqual(self.finish([source(), source('partial', source='ga4:x')])['collectionStatus'], 'partial')
        self.assertEqual(self.finish([], 'two')['collectionStatus'], 'unknown')
        self.assertEqual(self.finish([source(complete=False)], 'three')['collectionStatus'], 'unknown')

    def test_cached_or_old_attempt_cannot_create_new_success(self):
        old = o.stamp(NOW - timedelta(days=1))
        health = self.finish([source(attemptedAt=old, lastSuccessAt=old)])
        self.assertEqual(health['sources'][0]['status'], 'stale')
        self.assertIsNone(health['sources'][0]['verifiedLastSuccessAt'])

    def test_missing_reporting_period_cannot_be_success(self):
        health = self.finish([source(period=None)])
        self.assertEqual(health['sources'][0]['status'], 'unknown')

    def test_repeated_alert_suppressed_recovery_requires_fresh_complete(self):
        first = self.finish([source('failed')])
        self.assertEqual(len(first['alerts']), 1)
        next_time = NOW + timedelta(minutes=30)
        repeated = self.finish([source('failed', next_time)], 'two', next_time)
        self.assertEqual(repeated['alerts'], [])
        self.assertTrue(repeated['sources'][0]['duplicateAlertSuppressed'])
        uncertain = self.finish([source(complete=False)], 'three', NOW + timedelta(minutes=45))
        self.assertFalse(any((a['kind'] == 'recovery' for a in uncertain['alerts'])))
        final_time = NOW + timedelta(hours=1)
        final = self.finish([source(now=final_time)], 'four', final_time)
        self.assertEqual(final['alerts'][0]['kind'], 'recovery')

    def test_duplicate_run_id_not_appended_twice(self):
        self.finish([source()])
        self.assertTrue(self.finish([source()])['duplicate'])
        self.assertEqual(len(list(o.records(self.folder))), 1)

    def test_corrupt_last_line_preserved_and_previous_valid_history_survives(self):
        self.finish([source()])
        path = self.folder / 'collection-runs.jsonl'
        with path.open('ab') as f:
            f.write(b'{"runId":"unfinished')
        original = path.read_bytes()
        self.finish([source()], 'two')
        archived = list(self.folder.glob('collection-runs.partial-*.jsonl'))
        self.assertEqual(len(archived), 1)
        self.assertEqual(archived[0].read_bytes(), original)
        self.assertEqual(len(list(o.records(self.folder))), 2)

    def test_rotation_keeps_archived_rows_and_never_backfills_historical_success(self):
        o.finish_run(self.folder, runtime(), [source()], now=NOW, rotate_bytes=1)
        health = o.finish_run(self.folder, runtime('two'), [source('failed')], now=NOW, rotate_bytes=1)
        self.assertTrue(list(self.folder.glob('collection-runs.archive-*.jsonl')))
        self.assertEqual(len(list(o.records(self.folder))), 2)
        week = health['windows']['7']
        self.assertFalse(week['fullWindowObserved'])
        self.assertEqual(week['knownOutcomeDenominator'], 2)
        self.assertEqual(week['successRate'], 0.5)

    def test_read_time_staleness_and_watchdog_recovery(self):
        self.finish([source()])
        later = NOW + timedelta(hours=2)
        self.assertEqual(o.read_health(self.folder, later)['collectionStatus'], 'stale')
        self.assertEqual(o.watchdog_check(self.folder, later)['kind'], 'failure')
        self.assertIsNone(o.watchdog_check(self.folder, later + timedelta(minutes=1)))
        resumed = later + timedelta(minutes=2)
        self.finish([source(now=resumed)], 'two', resumed)
        self.assertEqual(o.watchdog_check(self.folder, resumed)['kind'], 'recovery')

    def test_missing_intervals_not_counted_as_success(self):
        self.finish([source()])
        later = NOW + timedelta(hours=2)
        health = self.finish([source(now=later)], 'two', later)
        self.assertIsNone(health['windows']['7']['missingSlots'])
        self.assertFalse(health['windows']['7']['scheduleCoverageVerified'])
        self.assertEqual(health['windows']['7']['counts']['success'], 2)

    def test_early_runtime_jitter_does_not_create_missing_scheduler_slot(self):
        early = NOW + timedelta(seconds=1800 - 5.9)
        rows = [{'runId': 'one', 'startedAt': o.stamp(NOW), 'finishedAt': o.stamp(NOW + timedelta(seconds=10)), 'collectionStatus': 'failed'}, {'runId': 'two', 'startedAt': o.stamp(early), 'finishedAt': o.stamp(early + timedelta(seconds=120)), 'collectionStatus': 'failed'}]
        before = json.dumps(rows)
        window = o.window_summary(rows, NOW + timedelta(seconds=3599), 7)
        self.assertEqual(window['observedRuns'], 2)
        self.assertEqual(window['counts']['failed'], 2)
        self.assertIsNone(window['missingSlots'])
        self.assertIsNone(window['expectedSlotsSinceCoverageStart'])
        self.assertFalse(window['scheduleCoverageVerified'])
        self.assertEqual(json.dumps(rows), before)
        o.write(self.folder / 'collection-health.json', {'checkedAt': o.stamp(NOW), 'sources': [], 'windows': {'7': {'missingSlots': 1, 'expectedSlotsSinceCoverageStart': 2}}})
        self.assertIsNone(o.read_health(self.folder, NOW)['windows']['7']['missingSlots'])
        self.assertEqual(o.load(self.folder / 'collection-health.json')['windows']['7']['missingSlots'], 1)

    def test_unknown_outcomes_do_not_enter_known_success_denominator(self):
        self.finish([], 'one')
        h = self.finish([source()], 'two')
        self.assertEqual(h['windows']['7']['observedRuns'], 2)
        self.assertEqual(h['windows']['7']['knownOutcomeDenominator'], 1)
        self.assertEqual(h['windows']['7']['counts']['unknown'], 1)

    def test_failure_preserves_last_verified_success(self):
        self.finish([source()])
        later = NOW + timedelta(minutes=30)
        h = self.finish([source('failed', now=later)], 'two', later)
        self.assertEqual(h['sources'][0]['verifiedLastSuccessAt'], o.stamp(NOW))

    def test_existing_snapshot_adapter_preserves_errors_and_dictionary_naver(self):
        folder = self.folder / 'dashboard/data'
        folder.mkdir(parents=True)
        period = {'start': '2026-10-01', 'end': '2026-10-14', 'users': 1, 'sessions': 2, 'pageViews': 3}
        o.write(folder / 'traffic.json', {'sites': {'example.com': {'ga4': {'status': 'error', 'checkedAt': o.stamp(NOW), 'periods': {n: period for n in ('day', 'week', 'month')}}}}, 'naverBlogs': {'blog-key': {'status': 'collected', 'checkedAt': o.stamp(NOW)}}})
        rows = o.snapshot_outcomes(self.folder, 'dashboard/traffic.py')
        self.assertEqual(next((s for s in rows if s['source'] == 'ga4:example.com'))['status'], 'failed')
        self.assertTrue(any((s['source'] == 'naver:blog-key' for s in rows)))

    def test_gsc_cached_comparison_window_is_not_complete(self):
        folder = self.folder / 'dashboard/data'
        folder.mkdir(parents=True)
        p = {'start': '2026-09-01', 'end': '2026-09-28', 'clicks': 1, 'impressions': 10, 'ctr': 0.1, 'position': 12, 'queriesStatus': 'collected', 'pagesStatus': 'collected', 'checkedAt': o.stamp(NOW - timedelta(days=2))}
        o.write(folder / 'traffic.json', {'sites': {'example.com': {'google': {'status': 'collected', 'checkedAt': o.stamp(NOW), 'periods': {'current28': p, 'previous28': p}}}}})
        row = next((r for r in o.snapshot_outcomes(self.folder, 'dashboard/traffic.py') if r['source'] == 'google:example.com'))
        self.assertFalse(row['complete'])
        self.assertEqual(row['status'], 'partial')

    def test_missing_configured_domain_and_other_portals_remain_unknown(self):
        folder = self.folder / 'dashboard/data'
        folder.mkdir(parents=True)
        o.write(folder / 'metrics-config.json', {'sites': {'present.com': {}, 'missing.com': {}}})
        o.write(folder / 'traffic.json', {'sites': {'present.com': {}}})
        rows = o.snapshot_outcomes(self.folder, 'dashboard/traffic.py')
        for name in ('ga4:missing.com', 'google:missing.com', 'bing:missing.com', 'naver-search:missing.com'):
            row = next((r for r in rows if r['source'] == name))
            self.assertEqual(row['status'], 'unknown')
            self.assertTrue(row['required'])

    def test_inspection_domains_distinguish_api_owner_ui_and_missing_scope(self):
        folder = self.folder / 'dashboard/data'
        folder.mkdir(parents=True)
        o.write(folder / 'metrics-config.json', {'sites': {'api.com': {'search_property': 'https://www.api.com/'}, 'ui.com': {}}})
        o.write(folder / 'metrics.json', {'sites': {}, 'inspectionAutomation': {'accounts': {}}})
        rows = o.snapshot_outcomes(self.folder, 'dashboard/metrics.py')
        self.assertTrue(any((r['source'] == 'url-inspection-api:api.com' and r['status'] == 'unknown' for r in rows)))
        self.assertTrue(any((r['source'] == 'url-inspection-owner-ui:ui.com' and r['status'] == 'unknown' for r in rows)))

    def test_required_revenue_does_not_disappear_when_disconnected(self):
        folder = self.folder / 'dashboard/data'
        folder.mkdir(parents=True)
        o.write(folder / 'metrics-config.json', {'sites': {'example.com': {}}})
        o.write(folder / 'revenue.json', {'months': {'2026-10': {'sources': [{'id': 'adsense-sj', 'status': 'not_connected'}, {'id': 'trip', 'status': 'not_collected'}]}}})
        rows = o.snapshot_outcomes(self.folder, 'dashboard/revenue.py')
        self.assertTrue(next((r for r in rows if r['source'] == 'revenue:adsense-sj'))['required'])
        self.assertTrue(next((r for r in rows if r['source'] == 'revenue:coupang'))['required'])
        self.assertFalse(next((r for r in rows if r['source'] == 'revenue:trip'))['required'])

    def test_public_export_strips_sensitive_nested_data_and_preserves_evidence_time(self):
        original = o.stamp(NOW)
        o.write(self.folder / 'collection-health.json', {'runId': 'safe-run', 'checkedAt': original, 'processStatus': 'failed', 'collectionStatus': 'failed', 'api_key': 'SECRET', 'revenue': 999, 'raw_error': 'SECRET', 'sourceCount': 2, 'sources': [{'source': 'ga4:example.com', 'scope': 'traffic-day', 'status': 'success', 'verifiedLastSuccessAt': original, 'checkedAt': original, 'access_token': 'SECRET'}, {'source': 'revenue:private-account', 'scope': 'revenue', 'status': 'failed'}], 'windows': {'7': {'observedRuns': 1, 'counts': {'failed': 1, 'secret': 'SECRET'}, 'secret': 'SECRET'}}, 'recentAlerts': [{'at': original, 'kind': 'failure', 'source': 'ga4:example.com', 'raw_error': 'SECRET'}]})
        target = self.folder / 'public/collection-health.json'
        exported = o.export_public_health(self.folder, target, NOW + o.timedelta(seconds=30))
        self.assertEqual(exported['checkedAt'], original)
        self.assertNotEqual(exported['exportedAt'], original)
        self.assertEqual(exported['sources'][0]['verifiedLastSuccessAt'], original)
        self.assertEqual(exported['redactedSourceCount'], 1)
        self.assertEqual(exported['windows']['7']['counts']['failed'], 1)
        self.assertNotIn('SECRET', target.read_text(encoding='utf-8'))
        self.assertNotIn('private-account', target.read_text(encoding='utf-8'))
        self.assertEqual(len(list(target.parent.iterdir())), 1)

    def test_concurrent_writers_keep_unique_complete_json_lines(self):
        context = multiprocessing.get_context('spawn')
        workers = [context.Process(target=concurrent_writer, args=(str(self.folder), 'run' + str(i))) for i in range(4)]
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join(15)
            self.assertEqual(worker.exitcode, 0)
        rows = list(o.records(self.folder))
        self.assertEqual(len(rows), 4)
        self.assertEqual(len({r['runId'] for r in rows}), 4)
if __name__ == '__main__':
    unittest.main()

class LiveSnapshotTests(unittest.TestCase):
    """Exercise aggregate helpers without importing workers or creating files."""

    def helpers(self, documents=None):
        import ast
        import sqlite3
        import threading
        source = (Path(__file__).resolve().parents[2] / 'server/main.py').read_text(encoding='utf-8')
        tree = ast.parse(source)
        names = {'_snapshot_database', '_snapshot_publications', '_snapshot_metric_summary'}
        tree.body = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in names]
        env = {'sqlite3': sqlite3, 'closing': __import__('contextlib').closing, 'datetime': datetime, 'timezone': timezone, 'timedelta': timedelta, 'CF_DIR': Path('/cf'), 'DATA_DIR': Path('/dashboard/data'), 'NAVER_DIR': Path('/naver'), 'load_json': lambda path, default: (documents or {}).get(str(path).replace('\\', '/'), default)}
        exec(compile(tree, 'snapshot-helpers', 'exec'), env)
        return env

    def test_metrics_only_exports_whitelisted_aggregates(self):
        fn = self.helpers()['_snapshot_metric_summary']
        result = fn({'sites': [{'site': {'site_id': 'example.test'}, 'credential': 'DO_NOT_EXPORT', 'traffic': {'status': 'collected', 'sessions': 0, 'document': 'DO_NOT_EXPORT'}}], 'secret': 'DO_NOT_EXPORT', 'indexing': {'indexed': 2, 'token': 'DO_NOT_EXPORT'}})
        self.assertEqual(result['ga4'][0]['sessions'], 0)
        self.assertNotIn('DO_NOT_EXPORT', json.dumps(result))

    def test_old_schedule_and_unverified_naver_are_not_today(self):
        docs = {'/dashboard/data/cf/daily_schedule.json': {'date': '2026-10-18', 'items': [{'status': 'published', 'publicUrl': 'https://example.test/a'}]}, '/dashboard/data/naver/public-verification.json': {'publicationDate': '2026-10-19', 'evidence': [{'publishedAt': '2026-10-18T14:30:00+00:00', 'publicPublicationVerified': True, 'publicUrl': 'https://blog.naver.com/a/1'}, {'publishedAt': '2026-10-18T15:30:00+00:00', 'publicPublicationVerified': True, 'publicUrl': 'https://blog.naver.com/a/2'}, {'publishedAt': '2026-10-19T12:00:00+09:00', 'publicPublicationVerified': False, 'publicUrl': 'https://blog.naver.com/a/3'}]}}
        result = self.helpers(docs)['_snapshot_publications']('2026-10-19')
        self.assertIsNone(result['cf']['published'])
        self.assertEqual(result['naver']['publishedVerified'], 1)

    def test_sqlite_reads_only_and_counts_today_without_documents(self):
        import sqlite3
        from unittest.mock import MagicMock, patch
        db = sqlite3.connect(':memory:')
        self.addCleanup(db.close)
        db.execute('CREATE TABLE questions(state TEXT,send_day TEXT,document TEXT)')
        db.executemany('INSERT INTO questions VALUES(?,?,?)', [('published_verified', '2026-10-19', 'PRIVATE'), ('published_verified', '2026-10-18', 'PRIVATE')])
        db.commit()
        file = MagicMock()
        file.name = 'kin.sqlite3'
        file.is_file.return_value = True
        file.resolve.return_value.as_uri.return_value = 'file:///existing/kin.sqlite3'
        env = self.helpers()
        with patch.object(env['sqlite3'], 'connect', return_value=db) as connect:
            result = env['_snapshot_database'](file, ('questions',), '2026-10-19')
        self.assertTrue(connect.call_args.args[0].endswith('?mode=ro'))
        self.assertEqual(result['tables']['questions']['rows'], 2)
        self.assertEqual(result['tables']['questions']['todayStates']['published_verified'], 1)
        self.assertNotIn('PRIVATE', json.dumps(result))
        with self.assertRaises(sqlite3.ProgrammingError):
            db.execute('SELECT 1')

    def test_missing_database_stays_missing(self):
        from unittest.mock import MagicMock
        file = MagicMock()
        file.name = 'missing.sqlite3'
        file.is_file.return_value = False
        result = self.helpers()['_snapshot_database'](file, ('parts',), '2026-10-19')
        self.assertEqual(result['status'], 'missing')
        self.assertEqual(result['tables'], {})

class PagePerformanceTests(unittest.TestCase):

    def fixture(self, count=20):
        from server.growth import page_performance_evidence
        self.evaluate = page_performance_evidence
        self.now = datetime(2026, 10, 19, 12, tzinfo=timezone.utc)
        header = {'start': '2026-10-12', 'end': '2026-10-18', 'timezone': 'Asia/Seoul', 'checkedAt': self.now.isoformat(), 'complete': True, 'status': 'collected'}
        visits = [{'domain': 'example.test', 'url': f'https://www.example.test/p{i}', 'title': f'Page {i}', 'sessions': i + 1, 'pageViews': i + 2} for i in range(count)]
        earnings = [{'domain': 'example.test', 'url': f'https://example.test/p{i}', 'estimatedRevenue': (i + 1) / 100} for i in range(count)]
        return ({'pagePerformance': {**header, 'pages': visits}}, {'pagePerformance': {**header, 'currency': 'USD', 'source': 'AdSense Management API v2', 'pages': earnings}})

    def test_exact_completed_week_top_tenth_joins_page_not_domain(self):
        metrics, revenue = self.fixture()
        result = self.evaluate(self.now, metrics, revenue)
        self.assertTrue(result['complete'])
        self.assertEqual(len(result['revenueWinners']), 2)
        self.assertEqual(result['revenueWinners'][0]['estimatedRevenue'], 0.2)
        self.assertEqual(result['coverage']['joinedPages'], 20)

    def test_domain_earnings_cannot_become_page_revenue(self):
        metrics, _ = self.fixture()
        result = self.evaluate(self.now, metrics, {'months': {'2026-10': {'sources': [{'daily': {'2026-10-18': '90'}}]}}})
        self.assertFalse(result['complete'])
        self.assertEqual(result['revenueWinners'], [])
        self.assertEqual(len(result['highTrafficPages']), 20)

    def test_partial_or_old_window_cannot_rank(self):
        for change in ({'complete': False}, {'end': '2026-10-17'}, {'checkedAt': '2026-10-15T12:00:00+00:00'}):
            metrics, revenue = self.fixture()
            revenue['pagePerformance'].update(change)
            result = self.evaluate(self.now, metrics, revenue)
            self.assertFalse(result['complete'])
            self.assertEqual(result['revenueWinners'], [])

    def test_zero_requires_exhaustive_domain_report_and_complete_inventory(self):
        metrics, revenue = self.fixture(1)
        metrics['sites'] = {'example.test': {'site': {'site_id': 'example.test'}, 'posts': {'complete': True, 'urls': ['https://example.test/missing']}}}
        result = self.evaluate(self.now, metrics, revenue)
        self.assertEqual(result['zeroViewPages'], [])
        metrics['pagePerformance']['sites'] = [{'domain': 'example.test', 'complete': True, 'fullEnumeration': True}]
        result = self.evaluate(self.now, metrics, revenue)
        self.assertEqual(result['zeroViewPages'][0]['sessions'], 0)
        self.assertIn('exhaustive', result['zeroViewPages'][0]['zeroBasis'])

    def test_zero_income_and_unjoined_page_are_excluded(self):
        metrics, revenue = self.fixture(2)
        revenue['pagePerformance']['pages'][0]['estimatedRevenue'] = 0
        revenue['pagePerformance']['pages'][1]['url'] = 'https://example.test/unmatched'
        result = self.evaluate(self.now, metrics, revenue)
        self.assertTrue(result['complete'])
        self.assertEqual(result['revenueWinners'], [])
        self.assertIn('no_positive_joined_page_revenue', result['reasonCodes'])

    def test_duplicate_canonical_pages_do_not_double_count(self):
        metrics, revenue = self.fixture(1)
        metrics['pagePerformance']['pages'].append(dict(metrics['pagePerformance']['pages'][0]))
        result = self.evaluate(self.now, metrics, revenue)
        self.assertFalse(result['complete'])
        self.assertEqual(result['revenueWinners'], [])

    def test_partial_global_report_preserves_complete_domain_doctor_evidence(self):
        metrics, revenue = self.fixture(2)
        report = metrics['pagePerformance']
        domain = {key: report[key] for key in ('start', 'end', 'timezone', 'checkedAt')}
        report.update(complete=False, status='partial', sites=[{**domain, 'domain': 'example.test', 'complete': True, 'status': 'collected', 'fullEnumeration': True}, {**domain, 'domain': 'missing.test', 'complete': False, 'status': 'error', 'fullEnumeration': False}])
        report['pages'].append({'domain': 'missing.test', 'url': 'https://missing.test/untrusted', 'sessions': 100, 'pageViews': 100})
        metrics['sites'] = {'example.test': {'site': {'site_id': 'example.test'}, 'posts': {'complete': True, 'urls': ['https://example.test/zero']}}}
        result = self.evaluate(self.now, metrics, revenue)
        self.assertFalse(result['complete'])
        self.assertFalse(result['coverage']['trafficComplete'])
        self.assertEqual(result['revenueWinners'], [])
        self.assertEqual(len(result['highTrafficPages']), 2)
        self.assertEqual(result['zeroViewPages'][0]['url'], 'https://example.test/zero')
        self.assertTrue(result['zeroViewPages'][0]['complete'])
        self.assertEqual(result['coverage']['completeTrafficDomains'], ['example.test'])
        report['sites'][0]['end'] = '2026-10-17'
        result = self.evaluate(self.now, metrics, revenue)
        self.assertEqual(result['zeroViewPages'], [])
        self.assertEqual(result['highTrafficPages'], [])

    def test_radar_revenue_precedes_traffic_without_invented_earnings(self):
        metrics, revenue = self.fixture(20)
        result = self.evaluate(self.now, metrics, revenue, traffic_source={}, domains=['example.test'])
        self.assertEqual(len(result['radarCandidates']), 2)
        self.assertTrue(all((row['selectionBasis'] == 'adsense_revenue' and row['revenueVerified'] for row in result['radarCandidates'])))
        result = self.evaluate(self.now, metrics, {}, traffic_source={}, domains=['example.test'])
        self.assertEqual(result['radarMode'], 'traffic')
        self.assertEqual(len(result['radarCandidates']), 2)
        self.assertTrue(all((row['estimatedRevenue'] is None and (not row['revenueVerified']) for row in result['radarCandidates'])))
        for row in revenue['pagePerformance']['pages']:
            row['estimatedRevenue'] = 0
        result = self.evaluate(self.now, metrics, revenue, traffic_source={}, domains=['example.test'])
        self.assertEqual(result['radarCandidates'][0]['selectionBasis'], 'ga4_sessions')

    def test_radar_gsc_exact_week_fallback_never_substitutes_28_days(self):
        self.fixture()
        report = {'start': '2026-10-10', 'end': '2026-10-16', 'checkedAt': self.now.isoformat(), 'queries': [{'page': 'https://example.test/search', 'clicks': 3}]}
        source = {'sites': {'example.test': {'google': {'status': 'collected', 'periods': {'week': report}}}}}
        result = self.evaluate(self.now, {}, {}, traffic_source=source, domains=['example.test'])
        row = result['radarCandidates'][0]
        self.assertEqual(row['selectionBasis'], 'gsc_clicks')
        self.assertEqual(row['start'], '2026-10-10')
        self.assertFalse(row['revenueVerified'])
        report['start'] = '2026-09-19'
        result = self.evaluate(self.now, {}, {}, traffic_source=source, domains=['example.test'])
        self.assertEqual(result['radarCandidates'], [])
        self.assertEqual(result['coldStartDomains'][0]['evidenceState'], 'missing')

    def test_cold_start_distinguishes_exhaustive_zero_from_missing(self):
        metrics, revenue = self.fixture(0)
        report = metrics['pagePerformance']
        report['sites'] = [{**{key: report[key] for key in ('start', 'end', 'timezone', 'checkedAt')}, 'domain': 'zero.test', 'complete': True, 'fullEnumeration': True}]
        result = self.evaluate(self.now, metrics, {}, traffic_source={}, domains=['zero.test', 'missing.test'])
        states = {row['domain']: row['evidenceState'] for row in result['coldStartDomains']}
        self.assertEqual(states, {'zero.test': 'measured_zero', 'missing.test': 'missing'})
        self.assertEqual(len(result['domainCoverage']), 2)

    def test_radar_verified_positive_revenue_does_not_require_ga4(self):
        metrics, revenue = self.fixture(2)
        result = self.evaluate(self.now, {}, revenue, traffic_source={}, domains=['example.test'])
        self.assertEqual(result['revenueWinners'], [])
        self.assertEqual(result['radarCandidates'][0]['selectionBasis'], 'adsense_revenue')
        self.assertTrue(result['radarCandidates'][0]['revenueVerified'])
        self.assertIsNone(result['radarCandidates'][0]['sessions'])
        revenue['pagePerformance']['pages'][0]['currency'] = 'KRW'
        result = self.evaluate(self.now, {}, revenue, traffic_source={}, domains=['example.test'])
        self.assertEqual(result['radarCandidates'], [])
