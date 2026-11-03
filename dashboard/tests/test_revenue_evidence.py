"""Offline fixtures for Radar's revenue and keyword evidence boundary."""
import copy
from datetime import datetime, timedelta
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from common import asset_map, knowledge_policy
from server import radar_scout as radar


class RevenueEvidenceTests(unittest.TestCase):
    now = datetime(2026, 11, 3, 11, tzinfo=radar.KST)

    def source(self, ident, currency, daily, **extra):
        return dict(id=ident, category='adsense' if currency == 'USD' else 'adpost',
                    label=ident, currency=currency, daily=daily, status='collected',
                    valueKind='estimated', scope='fixture only', checkedAt=self.now.isoformat(), **extra)

    def document(self):
        return {'months': {
            '2026-10': {'sources': [self.source('usd', 'USD', {'2026-10-31': '1.96'}),
                                    self.source('krw', 'KRW', {'2026-10-31': '8461'})]},
            '2026-11': {'sources': [self.source('usd', 'USD', {'2026-11-01': '.02', '2026-11-02': '0'}),
                                    self.source('krw', 'KRW', {'2026-11-01': '264'})]}}}

    def keyword(self, now=None):
        return dict(keyword='연금 신청', totalSearch=600, docCount=10, grade='S', measurementStatus='reported', metricEvidence={
            'sourceId': 'blokey_golden', 'sourceUrl': 'https://blokey.co.kr/api/golden?period=year',
            'checkedAt': (now or self.now).isoformat(), 'searchPeriod': 'provider_reported_unspecified',
            'raw': {'keyword': '연금 신청', 'total': 600, 'doc': 10}})

    def test_actual_schema_missing_is_distinct_from_observed_zero(self):
        document = self.document()
        original = copy.deepcopy(document)
        leaders = {r['id']: r for r in radar.revenue_leaders(document, self.now)}
        self.assertEqual(leaders['usd']['yesterdayAmount'], '0')
        self.assertTrue(leaders['usd']['periods']['yesterday']['complete'])
        self.assertIsNone(leaders['krw']['yesterdayAmount'])
        self.assertFalse(leaders['krw']['periods']['yesterday']['complete'])
        self.assertEqual(leaders['krw']['latestObservedCompletedDate'], '2026-11-01')
        self.assertEqual(leaders['krw']['previousMonthAmount'], '8461')
        self.assertEqual(leaders['krw']['currency'], 'KRW')
        self.assertEqual(leaders['usd']['previousMonthAmount'], '1.96')
        self.assertTrue(leaders['usd']['periods']['previousMonth']['estimated'])
        self.assertFalse(leaders['usd']['periods']['previousMonth']['complete'])
        self.assertEqual(document, original)

    def test_month_boundary_uses_previous_month_without_fake_current_rows(self):
        leaders = {r['id']: r for r in radar.revenue_leaders(
            self.document(), datetime(2026, 11, 1, 11, tzinfo=radar.KST))}
        self.assertEqual(leaders['usd']['yesterdayAmount'], '1.96')
        self.assertIsNone(leaders['usd']['periods']['throughYesterday']['amount'])

    def test_invalid_amounts_duplicates_and_missing_currency_are_not_zero(self):
        document = {'months': {'2026-11': {'sources': [
            self.source('invalid', 'USD', {'2026-11-01': 'NaN', '2026-11-02': None}),
            self.source('duplicate', 'KRW', {'2026-11-02': '100'}, aggregationEligible=False),
            self.source('unknown', None, {'2026-11-02': '100'})]}}}
        rows = radar.revenue_leaders(document, self.now)
        self.assertEqual([r['id'] for r in rows], ['invalid'])
        self.assertIsNone(rows[0]['yesterdayAmount'])
        self.assertIsNone(rows[0]['latestObservedCompletedDate'])

    def test_keyword_requires_matching_recent_source_metrics(self):
        measured = radar.reported_keyword(self.keyword(), self.now)
        self.assertEqual(measured['grade'], 'A')  # Derived, not copied from an S claim.
        self.assertEqual(measured['searchVolume'], 600)
        self.assertNotIn('monthlySearch', measured)
        for row in [None, {}, {'metricEvidence': 'forged'}, {'metricEvidence': {'raw': []}},
                    {'keyword': 'legacy', 'totalSearch': 4500, 'grade': 'S'},
                    {**self.keyword(), 'measurementStatus': 'unverified'},
                    self.keyword(self.now - timedelta(days=8)),
                    {**self.keyword(), 'docCount': 11}]:
            self.assertIsNone(radar.reported_keyword(row, self.now), row)

    def test_offline_synthesis_excludes_legacy_fallback_and_preserves_manual_note(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            data = root / 'dashboard/data'
            (data / 'second_brain').mkdir(parents=True)
            (data / 'revenue.json').write_text(json.dumps(self.document()), encoding='utf-8')
            guide = data / 'second_brain/04_실측우승원고_황금키워드.md'
            guide.write_text('old\n## ✍️ 대표님 & 크루 수동 추가 노트\nKeep this note\n', encoding='utf-8')
            genuine = self.keyword()
            forged = dict(keyword='fabricated', totalSearch=3800, docCount=28, grade='S')
            ledger = {'cfAssignments': {'example.test': [genuine, forged]},
                      'naverAssignments': {'soultin': [genuine]}, 'pairedBridgeSets': [forged]}
            with patch.object(radar, 'datetime', wraps=datetime) as clock, \
                 patch.object(radar, 'ROOT', root), \
                 patch.object(asset_map, 'CF_DOMAINS', ['example.test']), \
                 patch.object(asset_map, 'CF_NICHE_VERIFIED_POOLS', {'example.test': ['editorial idea']}), \
                 patch.object(asset_map, 'NAVER_NICHE_VERIFIED_POOLS', {}), \
                 patch.object(asset_map, 'collect_used_cf_topics', return_value=[]), \
                 patch.object(asset_map, 'collect_used_naver_topics', return_value=[]), \
                 patch.object(asset_map, 'query_naver_blog_doc_count', side_effect=AssertionError('network forbidden')), \
                 patch('requests.sessions.Session.request', side_effect=AssertionError('network forbidden')):
                clock.now.return_value = self.now
                result = radar.build_daily_winning_topics(ledger)
            self.assertEqual(len(result['cfDomainKeywords']['example.test']), 1)
            self.assertEqual(result['cfDomainKeywords']['example.test'][0]['grade'], 'A')
            self.assertEqual(result['pairedBridgeSets'], [])
            unknown = {r['keyword']: r for r in result['unverifiedCandidates']}
            self.assertIsNone(unknown['fabricated']['searchVolume'])
            self.assertIsNone(unknown['editorial idea']['grade'])
            rendered = guide.read_text(encoding='utf-8')
            self.assertIn('Keep this note', rendered)
            self.assertIn('8461 KRW', rendered)
            self.assertIn('미측정', rendered)
            self.assertNotIn('3,800', rendered)
            self.assertNotIn('즉각적인 PV 상승이 발생', rendered)
            self.assertIn('수익 검증 별도', rendered)

    def test_renderer_rejects_old_unverified_golden_and_unknown_revenue(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            radar_dir = root / 'dashboard/data/radar'
            radar_dir.mkdir(parents=True)
            (radar_dir / 'daily_winning_topics.json').write_text(json.dumps({
                'revenueLeaders': [{'label': 'missing', 'currency': None, 'yesterdayAmount': 0}],
                'goldenKeywords': [{'keyword': 'forged', 'grade': 'S', 'monthlySearch': 4500}]
            }), encoding='utf-8')
            knowledge_policy.sync_second_brain_guides(root)
            rendered = (root / 'dashboard/data/second_brain/04_실측우승원고_황금키워드.md').read_text(encoding='utf-8')
            self.assertIn('미측정', rendered)
            self.assertNotIn('$0.00', rendered)
            self.assertNotIn('4,500', rendered)
            self.assertIn('실측 배정 보류', rendered)

    def test_radar_reads_do_not_collect_or_create_database(self):
        from dashboard.agents import agent_tools
        with tempfile.TemporaryDirectory() as folder:
            data = Path(folder)
            with patch.object(agent_tools, 'DATA_DIR', data), \
                 patch.dict('sys.modules', {'radar_scout': radar}), \
                 patch.object(radar, 'SCOUT', radar.RadarScout(data / 'radar')), \
                 patch.object(radar, 'fetch_blokey_golden', side_effect=AssertionError('collection forbidden')):
                for _ in range(2):
                    result = agent_tools.read_radar_data()
                    self.assertEqual(result['scoutStatus']['status'], 'not_collected')
                    self.assertEqual(result['blokeyGolden']['topKeywords'], [])
                self.assertFalse((data / 'radar').exists())
                (data / 'radar').mkdir()
                (data / 'radar/blokey-golden.json').write_text(json.dumps({
                    'topKeywords': [{'keyword': 'legacy', 'totalSearch': 4500, 'grade': 'S'}]
                }), encoding='utf-8')
                result = agent_tools.read_radar_data()
                self.assertEqual(result['blokeyGolden']['topKeywords'], [])
                self.assertEqual(result['blokeyGolden']['unverifiedCandidates'][0]['measurementStatus'], 'unverified')
                self.assertFalse((data / 'radar/scout.sqlite3').exists())
                import sqlite3
                db_path = data / 'radar/scout.sqlite3'
                with sqlite3.connect(db_path) as db:
                    db.executescript("CREATE TABLE runs(started REAL,result TEXT); CREATE TABLE settings(key TEXT,value TEXT);")
                    db.execute("INSERT INTO runs VALUES(1, '{}')")
                db.close()
                before = db_path.read_bytes()
                result = agent_tools.read_radar_data()
                self.assertEqual(result['scoutStatus']['latest']['started'], 1)
                self.assertEqual(db_path.read_bytes(), before)

    def test_planning_keeps_unverified_ideas_without_fabricated_metrics(self):
        from dashboard.agents.style_strategy import planning_keyword_candidates
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            directory = root / 'dashboard/data/radar'
            directory.mkdir(parents=True)
            measured = self.keyword(datetime.now(radar.KST))
            (directory / 'blokey-golden.json').write_text(json.dumps({'cfAssignments': {'example.test': [
                {'keyword': 'legacy idea', 'totalSearch': 3800, 'grade': 'S'}, measured]}}), encoding='utf-8')
            with patch.object(asset_map, 'CF_NICHE_VERIFIED_POOLS', {'example.test': ['editorial idea']}), \
                 patch.object(asset_map, 'query_naver_blog_doc_count', side_effect=AssertionError('network forbidden')):
                rows = planning_keyword_candidates('example.test', 'cf', [], root)
            self.assertEqual(rows[0]['measurementStatus'], 'reported')
            self.assertEqual(rows[0]['searchVolume'], 600)
            hypotheses = {r['keyword']: r for r in rows[1:]}
            self.assertIsNone(hypotheses['legacy idea']['searchVolume'])
            self.assertIsNone(hypotheses['editorial idea']['grade'])


if __name__ == '__main__':
    unittest.main()
