import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch, MagicMock
import sys

from .pipeline import connect, ROOT
from . import measurement
sys.path.insert(0, str(ROOT / 'dashboard'))
import traffic


class MeasurementTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = connect(Path(self.temp.name) / 'ledger.sqlite3')
        self.config = {'sites': {host.removeprefix('www.'): {'ga4_property': '123', 'analytics_reader': 'existing'} for host in measurement.HOSTS}}

    def tearDown(self):
        self.db.close(); self.temp.cleanup()

    def run_collect(self, **kwargs):
        return measurement.collect(self.db, datetime(2026, 10, 15, 12, tzinfo=timezone.utc), config=self.config, persist=False, **kwargs)

    def test_exact_filter_and_window(self):
        body = measurement.report_body('2026-10-08', '2026-10-14', ['www.must-good.com'])
        filters = body['dimensionFilter']['andGroup']['expressions']
        self.assertEqual([row['filter']['stringFilter']['value'] for row in filters[:3]], ['naver_kin', 'referral', 'cf_bridge'])
        self.assertEqual(body['dimensions'][1]['name'], 'sessionManualAdContent')

    @patch.object(traffic, 'session')
    @patch.object(traffic, 'ga_report', return_value=([], False))
    def test_measured_zero_is_not_unknown_revenue(self, report, session):
        value = self.run_collect()
        self.assertEqual(value['sessions'], 0)
        self.assertTrue(value['complete'])
        self.assertTrue(value['provisional'])
        self.assertIsNone(value['publisherRevenue'])
        self.assertEqual(value['startDate'], '2026-10-08')

    @patch.object(traffic, 'session')
    @patch.object(traffic, 'ga_report', side_effect=[([], False), ([], True), ([], False)])
    def test_partial_does_not_turn_unknown_into_zero(self, report, session):
        value = self.run_collect()
        self.assertEqual(value['status'], 'partial')
        self.assertIsNone(value['sessions'])

    @patch.object(traffic, 'session')
    @patch.object(traffic, 'ga_report', side_effect=[([(['20261001', 'fake'], [4, 2, 5])], False), ([], False), ([], False)])
    def test_scope_mismatch_is_error(self, report, session):
        value = self.run_collect()
        self.assertEqual(value['sites'][0]['status'], 'collection_error')
        self.assertIsNone(value['sessions'])

    def test_unconnected_null(self):
        self.config = {}
        value = self.run_collect()
        self.assertIsNone(value['sessions'])
        self.assertEqual(value['sites'][0]['status'], 'not_connected')

    @patch.object(traffic, 'session')
    @patch.object(traffic, 'ga_report', side_effect=[([(['20261014', 'not_in_ledger'], [3, 2, 4])], False), ([], False), ([], False)])
    def test_unmapped_sessions_stay_in_total(self, report, session):
        value = self.run_collect()
        self.assertEqual(value['sessions'], 3)
        self.assertEqual(value['matchedSessions'], 0)
        self.assertEqual(value['unmatchedSessions'], 3)
        self.assertEqual(value['rows'][0]['mappingStatus'], 'unattributed')

    @patch.object(traffic, 'session')
    @patch.object(traffic, 'ga_report', return_value=([], False))
    def test_trial_never_queries_today_or_after_trial(self, report, session):
        value = measurement.collect(self.db, datetime(2026,10,16,2,tzinfo=timezone.utc),config=self.config,persist=False)
        self.assertEqual((value['startDate'],value['endDate']),('2026-10-15','2026-10-15'))
        value = measurement.collect(self.db, datetime(2026,10,24,2,tzinfo=timezone.utc),config=self.config,persist=False)
        self.assertEqual((value['startDate'],value['endDate']),('2026-10-15','2026-10-21'))

    @patch.object(traffic, 'session')
    @patch.object(traffic, 'ga_report', return_value=([], False))
    def test_final_collection_preserves_all_trial_cohorts(self, report, session):
        self.db.execute('INSERT INTO discoveries VALUES (?,?,?,?)',('12345','adinfo0905','{}','2026-10-14T15:05:00+00:00'))
        self.db.commit()
        value = measurement.collect(self.db, datetime(2026,10,24,2,tzinfo=timezone.utc),config=self.config,persist=False)
        days = {row['day']: row for row in value['dailyFunnel']}
        self.assertEqual(set(days), {'2026-10-'+str(i) for i in range(15,22)})
        self.assertEqual(days['2026-10-15']['discovered'],1)
        self.assertFalse(value['funnelTodayProvisional'])

    @patch.object(traffic, 'session')
    @patch.object(traffic, 'ga_report', return_value=([], False))
    def test_kst_midnight_first_trial_day_keeps_baseline_report(self, report, session):
        value = measurement.collect(self.db, datetime(2026,10,14,15,tzinfo=timezone.utc),config=self.config,persist=False)
        self.assertEqual(value['periodKind'],'baseline')
        self.assertEqual([row['day'] for row in value['dailyFunnel']],['2026-10-15'])
        self.assertTrue(value['funnelTodayProvisional'])

    @patch.object(traffic, 'session')
    @patch.object(traffic, 'ga_report', return_value=([], False))
    def test_pretrial_funnel_is_today_without_changing_ga_baseline(self, report, session):
        value = measurement.collect(self.db, datetime(2026,10,14,2,tzinfo=timezone.utc),config=self.config,persist=False)
        self.assertEqual([row['day'] for row in value['dailyFunnel']],['2026-10-14'])
        self.assertEqual(value['funnelPeriodKind'],'pretrial_check')
        self.assertEqual((value['startDate'],value['endDate']),('2026-10-08','2026-10-14'))


if __name__ == '__main__': unittest.main()
