"""Deterministic closure tests; all writes and external calls are isolated."""
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch
from types import SimpleNamespace

sys.path[:0] = [str(Path(__file__).resolve().parents[1]), str(Path(__file__).resolve().parents[2])]
from server import growth, doctor, content_auditor, radar_scout
from cf_posting import posting


class MeasurementClosure(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.data = self.root / 'dashboard/data'
        self.data.mkdir(parents=True)
        self.now = datetime(2026, 11, 3, 12, tzinfo=timezone.utc)
        self.db = self.data / 'growth.sqlite3'
        self.post = {'part_id': 'focus-1', 'attempt_id': 'focus', 'published_at': '2026-10-30T09:39:46+00:00',
                     'permalink': 'https://www.threads.com/@example/post/1', 'snapshots': {'72h': {
                         'actual_age_hours': 72.022, 'captured_at': '2026-11-02T09:41:04+00:00',
                         'platform': {'status': 'collected', 'scope': 'lifetime', 'metrics': {'views': 12}},
                         'ga4': {'status': 'collected', 'complete': True, 'provisional': True,
                                 'host': 'www.example.com', 'utm_content': 'exact', 'sessions': 0,
                                 'scope': 'calendar days', 'start_date': '2026-10-30', 'end_date': '2026-11-02'}}}}
        with growth.connect(self.db) as db:
            db.execute('INSERT INTO improvement_actions (id,domain,url,action,note,status,created_at,updated_at,planning_baseline) VALUES (?,?,?,?,?,?,?,?,?)',
                       ('action', 'example.com', 'https://www.example.com/post', 'experiment',
                        'experimentId=focus; UTM=exact', 'in_progress', self.now.isoformat(), self.now.isoformat(), '{}'))
        self.write('threads-measurement.json', {'collected_at': self.now.isoformat(), 'posts': [self.post]})
        self.identity = {'part_id': 'focus-1', 'attempt_id': 'focus', 'state': 'published_verified',
                         'source_url': 'https://www.example.com/post',
                         'outbound_url': 'https://www.example.com/post?utm_content=exact',
                         'permalink': self.post['permalink'], 'verified_at': self.now.isoformat()}
        self.write('public/threads.json', {'recent': [self.identity]})

    def write(self, name, value):
        target = self.data / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(value), encoding='utf-8')

    def reconcile(self, **kwargs):
        return growth.reconcile_threads_observation('action', 'focus-1', path=self.db, **kwargs)

    def test_dry_run_preserves_db_and_apply_is_idempotent_without_completion(self):
        before = self.db.read_bytes()
        preview = self.reconcile()
        self.assertEqual(before, self.db.read_bytes())
        self.assertEqual(preview['observation']['status'], 'inconclusive')
        self.assertEqual(preview['observation']['snapshots'], self.post['snapshots'])
        self.assertFalse(preview['applied'])
        self.assertTrue(self.reconcile(apply=True)['applied'])
        self.assertFalse(self.reconcile(apply=True)['changed'])
        with growth.connect(self.db) as db:
            row = db.execute('SELECT * FROM improvement_actions').fetchone()
            item = growth.action_record(row, self.now)
            self.assertEqual(row['status'], 'in_progress')
            self.assertIsNone(row['completed_at'])
        self.assertEqual(item['verification']['status'], 'inconclusive')
        self.assertIsNone(item['experiment']['revenueOutcome']['amountUsd'])

    def test_wrong_utm_and_no_snapshots_are_not_linked(self):
        for value in ({}, {'72h': {**self.post['snapshots']['72h'], 'ga4': {'status': 'collected', 'utm_content': 'wrong'}}}):
            self.write('threads-measurement.json', {'posts': [{**self.post, 'snapshots': value}]})
            with self.assertRaises(ValueError):
                self.reconcile(apply=True)

    def test_wrong_per_part_target_is_not_attributed_even_on_same_host(self):
        self.identity.update(source_url='https://www.example.com/other', outbound_url='https://www.example.com/other?utm_content=exact')
        self.write('public/threads.json', {'recent': [self.identity]})
        with self.assertRaisesRegex(ValueError, 'per-part outbound'):
            self.reconcile(apply=True)

    def test_final_measurements_progress_to_review_without_uplift_claim(self):
        self.post['snapshots']['72h']['ga4']['provisional'] = False
        self.write('threads-measurement.json', {'posts': [self.post]})
        evidence = self.reconcile()['observation']
        self.assertFalse(evidence['provisional'])
        self.assertEqual(evidence['status'], 'awaiting_review')
        self.assertFalse(evidence['causalProof'])

    def test_followups_keep_unknown_zero_and_due_scope_separate(self):
        self.write('revenue.json', {'months': {'2026-11': {'sources': [
            {'id': 'adpost-account', 'category': 'adpost', 'status': 'browser_unavailable',
             'checkedAt': '2026-11-01T01:00:00+00:00', 'pendingDates': ['2026-11-02']}]}}})
        self.write('play-console-status.json', {'apps': {'one': {'googleOptInCount': 12,
                   'googleInstallCount': None, 'continuousTestDays': None}}})
        rows = growth.measurement_followups(self.data, self.now.timestamp())
        by_key = {r['key']: r for r in rows}
        self.assertIsNone(by_key['measurement:adpost-account']['measuredValue'])
        self.assertEqual(by_key['measurement:adpost-account']['freshness'], 'stale')
        self.assertEqual(len(by_key['measurement:app:one']['missingMetrics']), 2)
        threads = by_key['measurement:threads:action:focus-1']
        self.assertEqual(threads['observation']['snapshots']['72h']['ga4']['sessions'], 0)
        self.assertIsInstance(threads['dueAt'], float)
        self.assertEqual(rows, growth.measurement_followups(self.data, self.now.timestamp()))

    def test_missing_schema_and_malformed_radar_do_not_hide_other_followups(self):
        with closing(sqlite3.connect(self.db)) as db, db:
            db.execute('DROP TABLE improvement_actions')
        self.write('radar/scout.sqlite3', {'not': 'sqlite'})
        keys = {r['key'] for r in growth.measurement_followups(self.data, self.now)}
        self.assertIn('measurement:radar:source', keys)
        self.assertIn('measurement:threads:action-source', keys)
        self.assertIn('measurement:adpost:source', keys)

    def test_missing_identity_and_malformed_other_sources_are_scoped_gaps(self):
        (self.data / 'public/threads.json').unlink()
        self.write('revenue.json', {'months': []})
        self.write('play-console-status.json', {'apps': []})
        rows = growth.measurement_followups(self.data, self.now)
        keys = {r['key'] for r in rows}
        self.assertIn('measurement:threads:action:identity', keys)
        self.assertIn('measurement:adpost:source', keys)
        self.assertIn('measurement:app:source', keys)

    def test_normal_sources_have_no_missing_measurement_blockers(self):
        self.write('revenue.json', {'months': {'2026-11': {'sources': [
            {'id': 'adpost-account', 'category': 'adpost', 'status': 'collected',
             'checkedAt': self.now.isoformat(), 'daily': {'2026-11-02': '0.00'}}]}}})
        self.write('play-console-status.json', {'apps': {'one': {'googleOptInCount': 12,
                   'googleInstallCount': 12, 'continuousTestDays': 14, 'status': 'collected', 'checkedAt': self.now.isoformat()}}})
        rows = growth.measurement_followups(self.data, self.now)
        self.assertTrue(all(r['status'] == 'resolved' for r in rows if r['key'].startswith(('measurement:adpost', 'measurement:app'))))

    def article(self, keyword='health insurance refund'):
        folder = self.root / 'article'
        folder.mkdir(exist_ok=True)
        (folder / 'planning.json').write_text(json.dumps({'keyword': keyword}), encoding='utf-8')
        (folder / 'research.json').write_text(json.dumps({'requestedKeyword': keyword, 'keyword': keyword}), encoding='utf-8')
        return folder, {'mainKeyword': keyword, 'title': 'Health refunds: when does the insurance payment arrive?', 'category': 'guide'}

    def test_title_paraphrase_and_mismatched_provenance(self):
        folder, article = self.article()
        self.assertEqual(posting.article_topic_consistency(article, folder), [])
        article['mainKeyword'] = 'tax service'
        self.assertIn('article_keyword_mismatch', posting.article_topic_consistency(article, folder))
        (folder / 'claim-review.json').write_text(json.dumps({'topicScopeMapping': {'sameScope': True}}))
        self.assertTrue(posting.article_topic_consistency(article, folder))

    def test_independent_hash_bound_scope_mapping_allows_synonyms_only_for_reviewed_inputs(self):
        from common import content_quality as quality
        folder, article = self.article('refund')
        article.update(mainKeyword='cashback', title='Cashback timing', contentHtml='<p>Payment review process.</p>')
        research = {'keyword': 'reimbursement', 'requestedKeyword': 'reimbursement',
                    'collectedAt': datetime.now(timezone.utc).isoformat(), 'sources': []}
        (folder / 'research.json').write_text(json.dumps(research), encoding='utf-8')
        response = {'status': 'passed', 'issues': [], 'experienceHonest': True, 'claimsComplete': True,
                    'claimSources': [], 'highRiskClaims': [], 'experienceClaims': [], 'hypotheticalClaims': [],
                    'topicScopeMapping': {'sameScope': True, 'approvedKeyword': 'refund',
                        'planningSha256': quality._digest({'keyword': 'refund'}), 'researchKeyword': 'reimbursement',
                        'requestedKeyword': 'reimbursement', 'articleKeyword': 'cashback', 'title': article['title']}}
        review = {**response, 'draftSha256': quality._digest(quality.publication_text(article)),
                  'researchSha256': quality._digest(research), 'contentQualitySha256': quality.content_quality_sha256(),
                  'responseSha256': quality._digest(response), 'checkedAt': datetime.now(timezone.utc).isoformat()}
        (folder / 'claim-review-response.json').write_text(json.dumps(response), encoding='utf-8')
        (folder / 'claim-review.json').write_text(json.dumps(review), encoding='utf-8')
        self.assertEqual(posting.article_topic_consistency(article, folder), [])
        (folder / 'planning.json').write_text(json.dumps({'keyword': 'unrelated tax'}), encoding='utf-8')
        self.assertTrue(posting.article_topic_consistency(article, folder))

    def test_missing_topic_provenance_fails_closed(self):
        folder, article = self.article()
        (folder / 'research.json').unlink()
        self.assertEqual(posting.article_topic_consistency(article, folder), ['topic_evidence_missing_or_invalid'])

    def test_radar_browser_failure_remains_failed_not_zero_candidates(self):
        with patch.object(radar_scout, 'os', SimpleNamespace(name='posix')), \
                patch.object(radar_scout.requests, 'get', side_effect=ConnectionError('unavailable')):
            receipt = radar_scout.fetch_blokey_golden()
        self.assertEqual(receipt['status'], 'failed')
        self.assertTrue(receipt['reason'])
        self.assertNotIn('NameError', receipt['reason'])

    def test_prepared_mismatch_holds_before_any_external_call(self):
        folder, article = self.article()
        article['mainKeyword'] = 'tax service'
        (folder / 'publication-receipt.json').write_text(json.dumps({'state': 'prepared'}))
        with patch.object(posting, 'validate_basic_article'), patch.object(posting, 'registered_categories', return_value=['guide']), \
                patch.object(posting, 'published_inventory') as inventory, patch.object(posting.requests, 'post') as submit:
            with self.assertRaisesRegex(ValueError, 'Publication held'):
                posting.publish_basic_article('example.com', article, folder)
            inventory.assert_not_called()
            submit.assert_not_called()

    def test_existing_published_receipt_is_preserved_without_repost(self):
        folder, article = self.article()
        receipt = {'state': 'published', 'publicUrl': 'https://example.com/old'}
        path = folder / 'publication-receipt.json'
        path.write_text(json.dumps(receipt))
        before = path.read_bytes()
        article['mainKeyword'] = 'tax service'
        with patch.object(posting, 'validate_basic_article'), patch.object(posting, 'registered_categories', return_value=['guide']), \
                patch.object(posting.requests, 'post') as submit:
            self.assertEqual(posting.publish_basic_article('example.com', article, folder), receipt)
            submit.assert_not_called()
        self.assertEqual(before, path.read_bytes())

    def test_auditor_public_match_success_failure_and_unverified_acceptance(self):
        post = {'slug': 'post', 'title': 'Real title', 'content': '<p>Verified replacement body</p>'}
        for status, body, expected in ((200, '<h1>Real title</h1><article>Verified replacement body</article>', True),
                                       (200, '<h1>Real title</h1><article>Old body</article>', False),
                                       (503, '<article>Verified replacement body</article>', False)):
            with patch.object(content_auditor.requests, 'get', return_value=Mock(status_code=status, text=body)):
                result = content_auditor.verify_remodel_publication({'ok': True}, 'example.com', post)
            self.assertEqual(result['ok'], expected)
            self.assertEqual(result['durableSuccess'], expected)
            self.assertEqual(bool(result['verifiedAt']), expected)

    def test_doctor_ledger_updates_only_after_matching_public_replacement(self):
        url = 'https://www.example.com/post'
        ledger_path = self.data / 'doctor.json'
        post = {'id': '1', 'title': 'Real title', 'content': '<p>Replacement body</p>', 'thumbnail': 'https://example.com/image.jpg'}
        original = {'auditedPosts': {url: {'remodelStatus': 'queued'}}}
        for accepted, matched, expected in ((False, True, False), (True, False, False), (True, True, True)):
            ledger_path.write_text(json.dumps(original))
            with patch.object(doctor, 'DOCTOR_LEDGER_PATH', ledger_path), \
                    patch.object(doctor, 'find_live_cf_post', return_value=post), \
                    patch.object(doctor, 'find_local_output_runs', return_value=[]), \
                    patch.object(doctor, '_get_cf_headers', return_value={}), \
                    patch.object(doctor, '_infer_cf_post_search_keyword', return_value=''), \
                    patch('dashboard.common.cf_tables.style_tables', side_effect=lambda x, **kw: x), \
                    patch('dashboard.common.cf_tables.inject_interactive_widget', side_effect=lambda x, **kw: x), \
                    patch.object(doctor.requests, 'put', return_value=Mock(status_code=200 if accepted else 500)), \
                    patch.object(doctor.requests, 'get', return_value=Mock(status_code=200, text='<h1>Real title</h1><article class="content">' + ('Replacement body' if matched else 'Old body') + '</article>')), \
                    patch('cf_posting.posting.ping_indexnow'), patch('common.llm_client.memory_event'):
                result = doctor.remodel_cf_post_by_url(url)
            saved = json.loads(ledger_path.read_text(encoding='utf-8'))
            self.assertEqual(result['durableSuccess'], expected)
            self.assertEqual(saved['auditedPosts'][url]['remodelStatus'], 'completed_remodel' if expected else 'queued')


if __name__ == '__main__':
    unittest.main()
