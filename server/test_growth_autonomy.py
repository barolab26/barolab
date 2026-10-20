"""JEV triage never substitutes for source freshness or verified publication."""
import copy
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock, patch

from common import content_maintenance as maintenance
from server import growth


MOMENT = datetime(2026, 10, 20, 10, tzinfo=timezone.utc)


class CandidateTests(unittest.TestCase):
    def setUp(self):
        self.analysis = growth.action_analysis()
        window = self.analysis.periods(MOMENT)['current']
        self.report = {**window, 'status': 'collected', 'checkedAt': MOMENT.isoformat(),
                       'pagesStatus': 'collected', 'impressions': 500, 'clicks': 4,
                       'pages': [{'page': 'https://www.example.com/museum', 'impressions': 202,
                                  'clicks': 1, 'position': 8.62, 'ctr': 1 / 202}],
                       'queries': [{'page': 'https://www.example.com/museum', 'query': '박물관 방문'}]}
        self.job = {'id': 'job1', 'domain': 'example.com', 'url': 'https://www.example.com/museum'}

    def candidates(self, jobs=None):
        traffic = {'sites': {'example.com': {'google': {'periods': {'current28': self.report}}}}}
        metrics = {'sites': {'one': {'posts': {'titles': {self.job['url']: '박물관 이용 안내'}}}}}
        with patch.object(self.analysis, 'read_json', side_effect=lambda p: traffic if p.name == 'traffic.json' else metrics), \
                patch.object(growth, 'page_performance_evidence', return_value={'highTrafficPages': []}):
            return growth.maintenance_candidates(jobs or [self.job], moment=MOMENT)

    def test_page_one_candidate_preserves_actual_source_window_and_no_revenue_claim(self):
        found = self.candidates()
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]['evidence']['position'], 8.62)
        self.assertEqual(found[0]['evidence']['start'], self.report['start'])
        self.assertEqual(found[0]['query'], '박물관 방문')
        self.assertFalse(found[0]['evidence']['revenueVerified'])

    def test_stale_partial_and_wrong_period_never_reach_jev(self):
        for change in ({'checkedAt': (MOMENT - timedelta(hours=27)).isoformat()},
                       {'partialPeriod': True}, {'end': '2026-01-01'}, {'pagesStatus': 'partial'}):
            original = copy.deepcopy(self.report)
            self.report.update(change)
            self.assertEqual(self.candidates(), [], change)
            self.report = original

    def test_unknown_url_and_domain_cannot_be_selected(self):
        job = {**self.job, 'url': 'https://other.com/museum', 'domain': 'other.com'}
        self.assertEqual(self.candidates([job]), [])

    def test_shortlist_is_bounded_to_five(self):
        jobs = []
        for i in range(12):
            url = f'https://www.example.com/page-{i}'
            jobs.append({**self.job, 'id': f'job-{i}', 'url': url})
            self.report['pages'].append({**self.report['pages'][0], 'page': url, 'impressions': 100 + i})
        self.assertEqual(len(self.candidates(jobs)), 5)

    def test_partial_ga4_portfolio_retains_verified_domain_source_time(self):
        domain = {'domain': 'example.com', 'status': 'collected', 'complete': True,
                  'fullEnumeration': True, 'start': '2026-10-13', 'end': '2026-10-19',
                  'timezone': 'Asia/Seoul', 'checkedAt': MOMENT.isoformat()}
        metrics = {'pagePerformance': {'status': 'partial', 'complete': False,
                     'checkedAt': (MOMENT - timedelta(hours=27)).isoformat(), 'sites': [domain],
                     'pages': [{'url': self.job['url'], 'sessions': 10, 'pageViews': 20}]}}
        feedback = growth.page_performance_evidence(now=MOMENT, metrics=metrics, revenue={}, traffic_source={})
        self.assertEqual(feedback['highTrafficPages'][0]['checkedAt'], MOMENT.isoformat())
        with patch.object(self.analysis, 'read_json', side_effect=lambda p: metrics if p.name == 'metrics.json' else {}), \
                patch.object(growth, 'page_performance_evidence', return_value=feedback):
            candidate = growth.maintenance_candidates([self.job], moment=MOMENT)[0]
        self.assertEqual(candidate['evidence']['checkedAt'], domain['checkedAt'])
        self.assertEqual(candidate['evidence']['source'], 'GA4')


class MaintenanceReceiptTests(unittest.TestCase):
    def article_revision(self):
        before = 'Original museum guidance explains the booking categories and equipment restrictions.'
        after = 'Revised museum guidance makes the booking categories and equipment restrictions easier to find.'
        original = {'title': 'Museum guidance', 'content': '<article><p>' + before * 4 + '</p></article>'}
        draft = {'title': original['title'], 'summary': '', 'contentHtml': original['content'].replace(before, after, 1),
                 'newClaims': [], 'resolvedIssueIds': ['READ1'],
                 'changes': [{'issueId': 'READ1', 'before': before, 'after': after}]}
        return original, draft, [{'id': 'READ1', 'confidence': 'observed'}]

    def test_safe_body_revision_inside_existing_article_is_allowed(self):
        from common.content_improvement import draft_rules
        original, draft, issues = self.article_revision()
        self.assertEqual(draft_rules(original, draft, {}, issues), [])

    def test_article_revision_still_blocks_new_script_or_event_handler(self):
        from common.content_improvement import draft_rules
        original, draft, issues = self.article_revision()
        for html in (draft['contentHtml'] + '<script>alert(1)</script>',
                     draft['contentHtml'].replace('<p>', '<p onclick="alert(1)">', 1)):
            with self.subTest(html=html):
                self.assertTrue(draft_rules(original, {**draft, 'contentHtml': html}, {}, issues))

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        data = Path(self.temp.name)
        for name, value in {'DATA': data, 'DB': data / 'growth.sqlite3', 'STATE': data / 'state.json',
                            'POLICY': data / 'policy.json', 'BACKUPS': data / 'backups'}.items():
            p = patch.object(maintenance, name, value)
            p.start()
            self.addCleanup(p.stop)
        p = patch.object(maintenance, 'now', return_value=MOMENT)
        p.start()
        self.addCleanup(p.stop)
        self.job = {'id': 'job1', 'domain': 'example.com', 'url': 'https://www.example.com/museum',
                    'proof': '{}', 'status': 'issues_found'}
        with maintenance.database() as db:
            db.execute("""INSERT INTO maintenance_jobs(id,domain,url,issue,status,stage,updated_at)
                          VALUES (?,?,?,?,?,?,?)""",
                       ('job1', 'example.com', self.job['url'], 'title', 'issues_found', 'queued', MOMENT.isoformat()))
        self.original = {'id': 1, 'title': '박물관', 'content': '<p>본문</p>'}
        self.draft = {'title': '박물관 관람 안내', 'contentHtml': '<p>본문</p>'}

    def receipt(self):
        return {'jevSelection': {'status': 'ok', 'selected': {
                    **self.job, 'evidence': {'checkedAt': MOMENT.isoformat()}}},
                'jevReview': {'status': 'ok', 'decision': 'pass', 'checkedAt': MOMENT.isoformat(),
                              'originalSha256': maintenance.digest(self.original),
                              'draftSha256': maintenance.digest(self.draft), 'evidenceSha256': maintenance.digest({})}}

    def test_review_hash_binds_original_and_full_draft(self):
        receipt = self.receipt()
        maintenance.validate_jev_receipt(self.job, self.original, self.draft, receipt)
        for original, draft in (({**self.original, 'content': 'changed'}, self.draft),
                                (self.original, {**self.draft, 'title': 'changed'})):
            with self.assertRaises(ValueError):
                maintenance.validate_jev_receipt(self.job, original, draft, receipt)

    def test_missing_failed_ambiguous_or_stale_review_blocks(self):
        for change in ({'decision': 'review'}, {'status': 'api_error'},
                       {'checkedAt': (MOMENT - timedelta(hours=25)).isoformat()}):
            receipt = self.receipt()
            receipt['jevReview'].update(change)
            with self.assertRaises(ValueError):
                maintenance.validate_jev_receipt(self.job, self.original, self.draft, receipt)
        with self.assertRaises(ValueError):
            maintenance.validate_jev_receipt(self.job, self.original, self.draft, {})
        receipt = self.receipt()
        receipt['jevSelection']['selected']['evidence']['checkedAt'] = (MOMENT - timedelta(hours=27)).isoformat()
        with self.assertRaises(ValueError):
            maintenance.validate_jev_receipt(self.job, self.original, self.draft, receipt)

    def test_uncertain_review_can_escalate_once_but_reject_never_can(self):
        receipt = self.receipt()
        receipt['jevReview']['decision'] = 'review'
        assessment = {'status': 'passed', 'issues': [], 'checks': dict.fromkeys(maintenance.REVIEW_CHECKS, True)}
        with patch('common.content_improvement.model_json', return_value=(assessment, {'provider': 'codex'})) as model:
            receipt['jevEscalation'] = maintenance.escalate_jev_review(self.original, self.draft, {}, receipt['jevReview'])
            maintenance.validate_jev_receipt(self.job, self.original, self.draft, receipt)
            self.assertEqual(model.call_count, 1)
            prompt = model.call_args.args[1]
            self.assertIn('searchIntentImproved는 발행 전 편집 검수 항목', prompt)
            self.assertIn('실제 관측 검색어 또는 명시된 독자 과제', prompt)
            self.assertIn('상승의 입증을 이 항목의 통과 조건으로 삼지 않는다', prompt)
            self.assertIn('기존 CTR 저하의 원인이라고 추론하지 않는다', prompt)
            self.assertIn('제목이 본문·1차 원천보다 넓은 답을 약속하면 changes_required', prompt)
            self.assertEqual(receipt['jevEscalation']['reviewContractVersion'], 'editorial-intent-v1')
            payload = model.call_args.args[2]
            self.assertEqual(payload['jevReview']['decision'], 'review')
            self.assertNotIn('contentHtml', payload['draft'])
            self.assertEqual(payload['original']['bodyText'], '본문')
            self.assertTrue(payload['verifiedUnchanged']['bodyAndEmbeddedMediaBytesEqual'])
        receipt['jevReview']['decision'] = 'reject'
        with patch('common.content_improvement.model_json') as model:
            with self.assertRaises(ValueError):
                maintenance.escalate_jev_review(self.original, self.draft, {}, receipt['jevReview'])
            with self.assertRaises(ValueError):
                maintenance.validate_jev_receipt(self.job, self.original, self.draft, receipt)
            model.assert_not_called()

    def test_changed_body_is_never_omitted_from_escalation(self):
        draft = {**self.draft, 'contentHtml': '<p>새로 변경된 사실</p>'}
        review = {**self.receipt()['jevReview'], 'decision': 'review'}
        with patch('common.content_improvement.model_json', return_value=({'status': 'changes_required'}, {})) as model:
            maintenance.escalate_jev_review(self.original, draft, {}, review)
        payload = model.call_args.args[2]
        self.assertEqual(payload['draft']['contentHtml'], draft['contentHtml'])
        self.assertEqual(payload['original']['content'], self.original['content'])
        self.assertEqual(payload['verifiedUnchanged'], {})

    def test_escalation_cannot_reuse_old_review_or_changed_evidence(self):
        receipt = self.receipt()
        receipt['jevReview']['decision'] = 'review'
        assessment = {'status': 'passed', 'issues': [], 'checks': dict.fromkeys(maintenance.REVIEW_CHECKS, True)}
        with patch('common.content_improvement.model_json', return_value=(assessment, {'provider': 'codex'})):
            receipt['jevEscalation'] = maintenance.escalate_jev_review(self.original, self.draft, {}, receipt['jevReview'])
        for changed in ('evidence', 'draft', 'jev_review', 'timestamp', 'check'):
            value = copy.deepcopy(receipt)
            if changed == 'evidence':
                value['evidence'] = {'sources': ['new facts']}
            elif changed == 'draft':
                value['jevEscalation']['draftSha256'] = 'wrong'
            elif changed == 'jev_review':
                value['jevReview']['scores'] = {'new_judgment': .8}
            elif changed == 'timestamp':
                value['jevEscalation']['checkedAt'] = (MOMENT - timedelta(minutes=1)).isoformat()
            else:
                value['jevEscalation']['checks']['factsSupported'] = False
            with self.assertRaises(ValueError, msg=changed):
                maintenance.validate_jev_receipt(self.job, self.original, self.draft, value)

    def test_triage_does_not_fall_back_on_failure_and_persists_success(self):
        candidate = {**self.job, 'evidence': {'checkedAt': MOMENT.isoformat()}}
        with patch.object(growth, 'maintenance_candidates', return_value=[candidate]), \
                patch('common.jev.choose_candidates', return_value={'status': 'api_error'}):
            self.assertIsNone(maintenance.choose_growth_job([self.job]))
        result = {'status': 'ok', 'ranking': [{'candidateId': 'job1', 'score': .9, 'evidenceSupport': .9}],
                  'usage': {'input_tokens': 321}, 'estimatedCostUsd': .0001}
        with patch.object(growth, 'maintenance_candidates', return_value=[candidate]), \
                patch('common.jev.choose_candidates', return_value=result):
            chosen = maintenance.choose_growth_job([self.job])
        self.assertEqual(json.loads(chosen['proof'])['jevSelection']['usage']['input_tokens'], 321)

    def test_no_fresh_candidate_makes_no_model_call(self):
        with patch.object(growth, 'maintenance_candidates', return_value=[]), \
                patch('common.jev.choose_candidates') as model:
            self.assertIsNone(maintenance.choose_growth_job([self.job]))
        model.assert_not_called()

    def test_public_change_is_idempotent_observing_not_revenue_success(self):
        baseline = {'status': 'collected', 'start': '2026-09-19', 'end': '2026-10-16',
                    'checkedAt': MOMENT.isoformat(), 'clicks': 1, 'impressions': 202, 'ctr': 1 / 202, 'position': 8.62}
        receipt = {**self.receipt(), 'planningBaseline': baseline, 'diagnosisSnapshot': {},
                   'hashes': {'draftSha256': maintenance.digest(self.draft)},
                   'publicVerification': {'status': 'verified', 'checkedAt': MOMENT.isoformat()},
                   'intent': {'checkedAt': MOMENT.isoformat()}}
        with patch.object(growth, 'action_evidence', return_value={'status': 'not_collected'}), \
                patch.object(growth, 'diagnosis_snapshot', return_value={}):
            first = maintenance.register_completed_action(self.job, receipt)
            second = maintenance.register_completed_action(self.job, receipt)
        self.assertEqual(first, second)
        with growth.connect(maintenance.DB) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM improvement_actions').fetchone()[0], 1)
            record = growth.action_record(db.execute('SELECT * FROM improvement_actions').fetchone(), MOMENT)
        self.assertEqual(record['experiment']['status'], 'implemented')
        self.assertEqual(record['experiment']['revenueOutcome']['status'], 'unknown')
        self.assertEqual(record['baseline']['end'], '2026-10-16')
        self.assertEqual(record['experiment']['followupEnd'], '2026-11-17')
        self.assertFalse(record['verification']['causalProof'])

    def test_goal_never_uses_partial_revenue_as_zero_or_success(self):
        with growth.connect(maintenance.DB) as db:
            db.execute('INSERT INTO sites VALUES (?,?,?,?)', ('example.com', 'https://example.com', 'cf', 'test'))
        report = maintenance.refresh_growth_state()
        self.assertEqual(report['goal']['daily_target'], 100)
        self.assertIsNone(report['goal']['daily_average'])
        self.assertEqual(report['goal']['status'], 'unknown')
        self.assertEqual(maintenance.read(maintenance.STATE)['growth']['goal']['status'], 'unknown')

    def test_goal_uses_fresh_completed_importer_dates_without_hiding_scope_or_missing_sites(self):
        end = datetime(2026, 10, 17).date()
        with growth.connect(maintenance.DB) as db:
            for domain in ('first.com', 'second.com'):
                db.execute('INSERT INTO sites VALUES (?,?,?,?)', (domain, 'https://' + domain, 'cf', 'test'))
                for day in growth.dates(end, 30):
                    db.execute('INSERT INTO daily_metrics VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',
                               (domain, 'adsense', 'revenue', day, 60, 'USD', 'America/Los_Angeles',
                                'fixture', MOMENT.isoformat(), 1, 'estimated', 'excludes_arbitrage'))
            goal = growth.autonomy_goal(db, MOMENT)
            self.assertEqual(goal['end'], '2026-10-17')
            self.assertEqual(goal['start'], '2026-09-18')
            self.assertEqual(goal['status'], 'achieved')
            self.assertEqual(goal['daily_average'], 120)
            self.assertEqual(goal['freshness']['freshSites'], 2)
            self.assertEqual(goal['sourceDataThrough'], '2026-10-17')
            self.assertEqual(growth.revenue_goal(db, datetime(2026, 10, 19).date())['status'], 'unknown')
            db.execute("UPDATE daily_metrics SET revenue_scope='unknown' WHERE site_id='first.com'")
            self.assertEqual(growth.autonomy_goal(db, MOMENT)['status'], 'unknown')
            db.execute("UPDATE daily_metrics SET revenue_scope='excludes_arbitrage'")
            db.execute('UPDATE daily_metrics SET collected_at=? WHERE site_id=?',
                       ((MOMENT - timedelta(hours=27)).isoformat(), 'first.com'))
            stale = growth.autonomy_goal(db, MOMENT)
            self.assertEqual(stale['status'], 'unknown')
            self.assertIsNone(stale['daily_average'])
            db.execute('UPDATE daily_metrics SET collected_at=?', (MOMENT.isoformat(),))
            db.execute("DELETE FROM daily_metrics WHERE day='2026-10-17'")
            missing_latest = growth.autonomy_goal(db, MOMENT)
            self.assertEqual(missing_latest['end'], '2026-10-17')
            self.assertEqual(missing_latest['status'], 'unknown')
            self.assertIsNone(missing_latest['sourceDataThrough'])
            db.execute("INSERT INTO sites VALUES ('unconnected.com','https://unconnected.com','cf','test')")
            self.assertEqual(growth.autonomy_goal(db, MOMENT)['site_count'], 3)
            self.assertEqual(growth.autonomy_goal(db, MOMENT)['status'], 'unknown')

    def test_kst_morning_change_excludes_actual_pacific_change_day(self):
        changed_at = '2026-10-20T00:30:00+09:00'
        overlapping = {'status': 'collected', 'start': '2026-09-22', 'end': '2026-10-19'}
        receipt = {'planningBaseline': overlapping, 'diagnosisSnapshot': {},
                   'hashes': {'draftSha256': maintenance.digest(self.draft)},
                   'publicVerification': {'status': 'verified', 'checkedAt': changed_at},
                   'intent': {'checkedAt': changed_at}}
        with patch.object(growth, 'action_evidence', return_value={'status': 'not_collected'}) as source, \
                patch.object(growth, 'diagnosis_snapshot', return_value={}):
            maintenance.register_completed_action(self.job, receipt)
        source.assert_called_once_with(self.job['domain'], self.job['url'], '2026-09-21', '2026-10-18')
        self.assertEqual(receipt['experiment']['baseline']['status'], 'not_collected')
        self.assertEqual(receipt['experiment']['measurementDate'], '2026-10-19')
        self.assertEqual(receipt['experiment']['followupStart'], '2026-10-20')
        self.assertEqual(receipt['experiment']['followupEnd'], '2026-11-16')
        with growth.connect(maintenance.DB) as db:
            record = growth.action_record(db.execute('SELECT * FROM improvement_actions').fetchone(), MOMENT)
        self.assertEqual(record['completedAt'], '2026-10-20')
        self.assertEqual(record['observation']['start'], '2026-10-20')
        self.assertEqual(record['observation']['end'], '2026-11-16')
        self.assertEqual(record['observation']['measurementTimezone'], 'America/Los_Angeles')

    def test_reediting_waits_for_the_last_pacific_followup_day_to_finish(self):
        job = {**self.job, 'completed_at': '2026-10-20T10:00:00+00:00'}
        policy = {'cooldownHours': 672}
        self.assertTrue(maintenance.cooldown_active(job, policy, datetime(2026, 11, 17, 12, tzinfo=timezone.utc)))
        self.assertTrue(maintenance.cooldown_active(job, policy, datetime(2026, 11, 18, 7, 59, tzinfo=timezone.utc)))
        self.assertFalse(maintenance.cooldown_active(job, policy, datetime(2026, 11, 18, 8, tzinfo=timezone.utc)))
        self.assertTrue(maintenance.cooldown_active(job, {'cooldownHours': 2160},
                                                   datetime(2026, 11, 18, 8, tzinfo=timezone.utc)))

    def test_observed_source_window_survives_later_collector_rollover(self):
        baseline = {'status': 'collected', 'start': '2026-09-19', 'end': '2026-10-16',
                    'clicks': 1, 'impressions': 202, 'ctr': 1 / 202, 'position': 8.62}
        receipt = {'planningBaseline': baseline, 'diagnosisSnapshot': {},
                   'hashes': {'draftSha256': maintenance.digest(self.draft)},
                   'publicVerification': {'status': 'verified', 'checkedAt': MOMENT.isoformat()}}
        with patch.object(growth, 'action_evidence', return_value={'status': 'not_collected'}), \
                patch.object(growth, 'diagnosis_snapshot', return_value={}):
            maintenance.register_completed_action(self.job, receipt)
        after = {**baseline, 'start': '2026-10-21', 'end': '2026-11-17', 'clicks': 3}
        later = MOMENT + timedelta(days=33)
        with patch.object(growth, 'action_evidence', return_value=after):
            first = growth.autonomy_summary(maintenance.DB, later)
        with patch.object(growth, 'action_evidence', return_value={'status': 'not_collected'}):
            next_day = growth.autonomy_summary(maintenance.DB, later + timedelta(days=1))
        self.assertEqual(first['experiments'][0]['verification']['clicksDelta'], 2)
        self.assertEqual(first['experiments'][0]['experiment']['performanceStatus'], 'observed_change')
        self.assertEqual(next_day['experiments'][0]['verification']['clicksDelta'], 2)
        self.assertEqual(next_day['experiments'][0]['experiment']['revenueOutcome']['status'], 'unknown')

    def test_kill_switch_after_intent_cancels_before_put_and_preserves_ready_draft(self):
        quality = 'test-policy'
        original = {**self.original, 'slug': 'museum', 'updated_at': MOMENT.isoformat()}
        review = {'status': 'passed', 'rulesPassed': True, 'issues': [],
                  'checks': dict.fromkeys(maintenance.REVIEW_CHECKS, True),
                  'checkedAt': MOMENT.isoformat(), 'draftSha256': maintenance.digest(self.draft),
                  'contentQualitySha256': quality}
        stages = [{'contentQualitySha256': quality}]
        proposal = {'status': 'ready', 'review': review, 'evidence': {},
                    'originalSha256': maintenance.digest(original), 'draftSha256': maintenance.digest(self.draft),
                    'contentQualitySha256': quality, 'stageReceipts': stages}
        receipt = {'review': review, 'hashes': {
            'originalSha256': maintenance.digest(original), 'draftSha256': maintenance.digest(self.draft),
            'diffSha256': maintenance.hashlib.sha256(b'reviewed diff').hexdigest()},
            'contentQualitySha256': quality, 'stageReceipts': stages}
        folder = maintenance.BACKUPS / self.job['id']
        folder.mkdir(parents=True)
        for name, value in (('original.json', original), ('draft.json', self.draft),
                            ('proposal.json', proposal), ('receipt.json', receipt)):
            maintenance.atomic(folder / name, value)
        (folder / 'diff.txt').write_bytes(b'reviewed diff')
        maintenance.atomic(maintenance.POLICY, {'enabled': True})
        maintenance.save_job(self.job['id'], status='ready')
        stop = maintenance.DATA / 'EGO_EXEC_DISABLED'
        write = maintenance.atomic
        def cancel_after_intent(path, value):
            write(path, value)
            if value.get('intent'):
                stop.touch()
        response = Mock()
        response.json.return_value = {'post': original}
        from contextlib import nullcontext
        growth.action_analysis()
        with patch.object(Path, 'home', return_value=maintenance.DATA), \
                patch.object(maintenance, 'content_quality_sha256', return_value=quality), \
                patch.object(maintenance, 'idle_reason', return_value=None), \
                patch.object(maintenance, 'cache_binding', return_value=('zone', {})), \
                patch.object(maintenance, 'api_key', return_value='test-only-key'), \
                patch('metrics.collector_lock', side_effect=lambda _: nullcontext(True)), \
                patch('requests.get', return_value=response), patch('requests.put') as put, \
                patch.object(maintenance, 'atomic', side_effect=cancel_after_intent):
            with self.assertRaisesRegex(ValueError, '자동 운영 중지 상태'):
                maintenance._apply_job(self.job['id'], canary=True)
        put.assert_not_called()
        with maintenance.database() as db:
            job = db.execute('SELECT * FROM maintenance_jobs WHERE id=?', (self.job['id'],)).fetchone()
        self.assertEqual(job['status'], 'ready')
        self.assertIsNone(job['apply_attempt_at'])
        self.assertEqual(maintenance.read(folder / 'draft.json'), self.draft)
        self.assertIn('cancelledAt', maintenance.read(folder / 'receipt.json')['intent'])

    def test_kill_switch_stops_prepare_only_and_cache_writes(self):
        maintenance.atomic(maintenance.POLICY, {'enabled': True})
        (maintenance.DATA / 'EGO_EXEC_DISABLED').touch()
        with patch.object(Path, 'home', return_value=maintenance.DATA), \
                patch.object(maintenance, 'sync_inventory'), patch.object(maintenance, 'recover_jobs'), \
                patch.object(maintenance, 'refresh_growth_state'), \
                patch.object(maintenance, 'audit_batch') as audit, \
                patch('requests.post') as post:
            result = maintenance.run_once(force_prepare=True)
            self.assertEqual(result['runtime']['status'], 'paused')
            audit.assert_not_called()
            with self.assertRaisesRegex(ValueError, '자동 운영 중지 상태'):
                maintenance.purge_exact('example.com', self.job['url'], 'museum', ('zone', {}))
            post.assert_not_called()

    def test_kill_switch_during_research_stops_next_stage(self):
        maintenance.atomic(maintenance.POLICY, {'enabled': True})
        def researching(*args, observer, **kwargs):
            (maintenance.DATA / 'EGO_EXEC_DISABLED').touch()
            observer('writer')
        with patch.object(Path, 'home', return_value=maintenance.DATA), \
                patch.object(maintenance, 'load_article', return_value=self.original), \
                patch.object(growth.action_analysis(), 'summary', return_value={}), \
                patch('common.content_improvement.prepare_improvement', side_effect=researching), \
                patch('common.jev.review_revision') as jev:
            with self.assertRaisesRegex(ValueError, '자동 운영 중지 상태'):
                maintenance.prepare_job(self.job)
            jev.assert_not_called()


class EditorialBudgetTests(unittest.TestCase):
    def test_reviewer_keeps_complete_40k_evidence_in_one_bounded_request(self):
        from common import content_improvement as improvement
        evidence = '원문시작:' + '검증근거' * 10000 + ':원문끝'
        result = {'status': 'changes_required', 'issues': ['fixture assessment'], 'checks': {}}
        with tempfile.TemporaryDirectory() as folder, \
                patch.object(improvement, 'ROOT', Path(folder)), \
                patch.object(improvement, 'provider_record', return_value={}), \
                patch.object(improvement.time, 'monotonic', return_value=100.0), \
                patch.object(improvement, 'generate_json', return_value=result) as generate:
            actual, _ = improvement.model_json('reviewer', 'complete evidence review', {'evidence': evidence}, 280.0)
        self.assertEqual(actual, result)
        generate.assert_called_once()
        prompt = generate.call_args.args[0]
        self.assertIn(evidence, prompt)
        self.assertGreater(len(prompt), 40000)
        self.assertLessEqual(len(prompt), 48000)

    def test_reviewer_over_48k_is_blocked_before_any_model_call(self):
        from common import content_improvement as improvement
        with tempfile.TemporaryDirectory() as folder, \
                patch.object(improvement, 'ROOT', Path(folder)), \
                patch.object(improvement, 'provider_record', return_value={}), \
                patch.object(improvement.time, 'monotonic', return_value=100.0), \
                patch.object(improvement, 'generate_json') as generate:
            with self.assertRaisesRegex(ValueError, '입력 상한 초과'):
                improvement.model_json('reviewer', 'complete evidence review', {'evidence': '가' * 48001}, 280.0)
            self.assertFalse((Path(folder) / '.agent-routing').exists())
        generate.assert_not_called()

    def test_writer_and_researcher_keep_existing_16k_input_limit(self):
        from common import content_improvement as improvement
        for role in ('writer', 'researcher'):
            with self.subTest(role=role), tempfile.TemporaryDirectory() as folder, \
                    patch.object(improvement, 'ROOT', Path(folder)), \
                    patch.object(improvement, 'provider_record', return_value={}), \
                    patch.object(improvement.time, 'monotonic', return_value=100.0), \
                    patch.object(improvement, 'generate_json') as generate:
                with self.assertRaisesRegex(ValueError, '입력 상한 초과'):
                    improvement.model_json(role, 'bounded draft', {'evidence': '가' * 16001}, 280.0)
                generate.assert_not_called()

    def test_actual_model_call_receives_only_remaining_deadline(self):
        from common import content_improvement as improvement
        with patch.object(improvement, 'provider_record', return_value={}), \
                patch.object(improvement.time, 'monotonic', return_value=100.0), \
                patch.object(improvement, 'generate_json', side_effect=RuntimeError('test transport')) as generate:
            with self.assertRaises(improvement.ProviderUnavailable):
                improvement.model_json('reviewer', 'bounded review', {}, 280.0)
        self.assertEqual(generate.call_args.kwargs['timeout_seconds'], 180.0)


if __name__ == '__main__':
    unittest.main()
