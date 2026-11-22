"""No network, publishing, model calls or production-state writes."""
from datetime import date, datetime
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from dashboard.collectors import revenue_focus as f
from common import work_agenda


class RevenueFocusTests(unittest.TestCase):
    def row(self, start='2026-11-07', end='2026-11-13', sessions=40, **changes):
        return {'url': 'https://www.example.com/article', 'timezone': 'Asia/Seoul', 'source': f.SOURCE,
                'start': start, 'end': end, 'complete': True, 'qualifiedSessions': sessions, **changes}

    def test_internal_visits_are_not_acquisition(self):
        rows = [{'source': '127.0.0.1:8790', 'medium': 'referral', 'sessions': 3, 'pageViews': 11},
                {'source': '192.168.45.190:8790', 'medium': 'referral', 'sessions': 1, 'pageViews': 4},
                {'source': 'threads', 'medium': 'social', 'sessions': 1, 'pageViews': 1},
                {'source': 'm.facebook.com', 'medium': 'referral', 'sessions': 1, 'pageViews': 1}]
        r = f.summarize(rows, {'sessions': 6, 'pageViews': 17}, False, 'example.com')
        self.assertEqual(r['qualifiedPageViews'], 2)
        self.assertEqual(r['breakdown']['excluded']['pageViews'], 15)
        self.assertTrue(r['complete'])

    def test_threshold_or_reconciliation_failure_never_becomes_zero(self):
        for totals, limited in [({'sessions': 0, 'pageViews': 0}, True), ({'sessions': 2, 'pageViews': 3}, False)]:
            r = f.summarize([], totals, limited, 'example.com')
            self.assertIsNone(r['qualifiedSessions'])
            self.assertFalse(r['complete'])
        self.assertEqual(f.summarize([], {'sessions': 0, 'pageViews': 0}, False, 'example.com')['qualifiedSessions'], 0)

    def test_direct_unset_and_audits_stay_separate(self):
        self.assertEqual(f.qualify('(direct)', '(none)', 'example.com'), 'unattributed')
        self.assertEqual(f.qualify('barolab_audit', 'qa', 'example.com'), 'excluded')
        self.assertEqual(f.traffic.canonical_source('brunch.co.kr'), 'brunch')

    def test_windows_and_reporting_lag(self):
        h = f.observation_windows('2026-11-07')
        self.assertEqual([x['days'] for x in h], [7, 14, 28])
        self.assertEqual(h[0]['reviewDate'], '2026-11-14')
        self.assertEqual(h[0]['finalCollectionDate'], '2026-11-16')
        self.assertEqual(h[-1]['end'], '2026-12-04')

    def test_sample_and_scope_gates(self):
        base = self.row('2026-10-28', '2026-11-03', 0)
        self.assertEqual(f.evaluate(base, self.row(sessions=2), 30, 7)['status'], 'inconclusive')
        good = f.evaluate(base, self.row(), 30, 7)
        self.assertEqual(good['status'], 'initial_acquisition_observed')
        self.assertFalse(good['revenueSuccess'])
        self.assertFalse(good['causalClaim'])
        for changes in ({'url': 'https://www.example.com/other'}, {'end': '2026-11-14'}, {'provisional': True}):
            self.assertEqual(f.evaluate(base, self.row(**changes), 30, 7)['reason'], 'target_or_window_mismatch')

    def test_stop_expansion_after_28_days_with_small_sample(self):
        base = self.row('2026-10-07', '2026-11-03', 0)
        after = self.row(end='2026-12-04', sessions=2)
        result = f.evaluate(base, after, 30, 28)
        self.assertEqual(result['status'], 'inconclusive')
        self.assertEqual(result['action'], 'stop_new_spend')

    def test_missing_revenue_is_not_allocated_from_company_total(self):
        row = self.row()
        r = f.matched_revenue({'months': {'2026-11': {'total': 100}}}, row['url'], row)
        self.assertIsNone(r['amount'])

    def test_measurement_policy_does_not_block_routine_operations(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(work_agenda, 'DATA', Path(folder)), patch.object(work_agenda, 'current', return_value=None):
            self.assertTrue(work_agenda.new_authoring_allowed('cf_blog'))
            p = Path(folder)/'revenue-focus.json'
            p.write_text(json.dumps({'schema': 'revenue-focus-v1', 'policy': {'newAutonomousAuthoring': False}}))
            self.assertTrue(work_agenda.new_authoring_allowed('cf_blog'))
            p.write_text('[]')
            self.assertTrue(work_agenda.new_authoring_allowed('cf_blog'))

    def test_exact_revenue_empty_report_remains_unknown(self):
        cfg = {'adsense_accounts': {'sj': {'sites': ['example.com']}}}
        with patch('dashboard.collectors.revenue.revenue_config', return_value={}), patch('dashboard.collectors.revenue.adsense_page_performance', return_value=[]):
            r = f.collect_exact_revenue(cfg, 'https://www.example.com/article', {**self.row(), 'domain': 'example.com'})
        self.assertIsNone(r['amount'])

    def test_first_review_is_provisional_and_final_review_uses_same_exact_window(self):
        from contextlib import nullcontext
        target = {'url': 'https://www.example.com/article', 'baselineEnd': '2026-11-03',
                  'observationStart': '2026-11-07', 'checkpoints': f.observation_windows('2026-11-07'),
                  'minimumSessions': 30, 'selectionReport': {'complete': True}, 'baselines': {}, 'progress': {}}
        for days in (7, 14, 28):
            end = date(2026, 11, 3)
            from datetime import timedelta
            target['baselines'][str(days)] = self.row(str(end-timedelta(days=days-1)), str(end), 0, windowRevenueAttempted=True)
        cfg = {'sites': {'example.com': {'ga4_property': '123'}}, 'analytics_readers': {}}
        def collect_row(client, prop, url, start, end):
            return self.row(start, end, 40, domain='example.com', windowRevenueAttempted=True)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'focus.json'
            path.write_text(json.dumps({'schema': 'revenue-focus-v1', 'policy': {'apiReportBudgetPerRun': 12}, 'targets': [target]}))
            original_read = f.traffic.read_json
            def read(p):
                return original_read(p) if Path(p) == path else cfg if Path(p) == f.traffic.CONFIG else {}
            with patch.object(f.traffic, 'read_json', side_effect=read), patch.object(f.traffic, 'session', return_value=nullcontext(object())), patch.object(f, 'collect_window', side_effect=collect_row):
                first = f.collect(path, datetime(2026, 11, 14, tzinfo=f.KST))
                t = first['targets'][0]
                self.assertTrue(t['preliminary']['7']['provisional'])
                self.assertNotIn('7', t.get('evaluations', {}))
                self.assertEqual(t['nextCollectionDate'], '2026-11-16')
                final = f.collect(path, datetime(2026, 11, 16, tzinfo=f.KST))
                t = final['targets'][0]
                self.assertEqual(t['observations']['7']['end'], '2026-11-13')
                self.assertEqual(t['evaluations']['7']['status'], 'initial_acquisition_observed')
                self.assertLessEqual(final['lastApiReportBudgetUsed'], 12)


if __name__ == '__main__':
    unittest.main()
