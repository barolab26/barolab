import copy
import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace

from naver_blog_posting import account_reconciliation as module
from naver_blog_posting import pipeline_runner as runner


class ReconciliationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.now = datetime(2026, 10, 21, 9, tzinfo=timezone(timedelta(hours=9)))
        self.attempt = {'account': 'soultin', 'startedAt': '2026-10-19T09:00:00+09:00',
                        'workDate': '2026-10-19', 'phase': 'failed', 'preSubmissionFailure': True,
                        'artifactFolder': str(self.base / 'foreign/missing-proof')}
        self.inventory = self.base / 'inventory.json'
        self.inventory.write_text(json.dumps({'accounts': {'soultin': {
            'fullInventoryComplete': True, 'fullCollectedAt': self.now.isoformat(), 'total': 1,
            'posts': [{'url': 'https://blog.naver.com/mustpickinfo/123', 'title': 'Existing'}]}}}))
        self.receipt = {
            'schema': 'naver-account-reconciliation-v1', 'account': 'soultin', 'blogId': 'mustpickinfo',
            'checkedAt': self.now.isoformat(), 'historicalCutoff': '2026-10-20T23:59:59+09:00',
            'pipelineIdleObservedAt': self.now.isoformat(),
            'identity': {'schema': 'naver-authenticated-reservation-preflight-v1',
                         'account': 'soultin', 'blogId': 'mustpickinfo', 'authenticatedAccount': 'soultin',
                         'ownerBlogId': 'mustpickinfo', 'identityVerified': True, 'checkedAt': self.now.isoformat()},
            'reservation': {'checkedAt': self.now.isoformat(), 'verificationSource': 'playwright-reservation-list',
                            'reservationListComplete': True, 'reservationCount': 0, 'reservations': [],
                            'independentReadings': 2, 'serverCountEvidence': [
                                {'pass': p, 'blogId': 'mustpickinfo', 'httpStatus': 200,
                                 'path': '/PrePostListCount.naver', 'isSuccess': True, 'totalCount': 0,
                                 'requestMethod': 'GET',
                                 'requestQuery': {'blogId': ['mustpickinfo'], 'editorVersion': [v]}}
                                for p in (1, 2) for v in ('2', '4')]},
            'inventoryFile': str(self.inventory),
            'inventorySha256': hashlib.sha256(self.inventory.read_bytes()).hexdigest(),
            'publicHead': {'blogId': 'mustpickinfo', 'checkedAt': self.now.isoformat(), 'total': 1, 'ids': ['123']},
            'failureIdentities': [module.failure_identity(self.attempt)]}

    def validate(self, receipt=None, attempts=None, now=None, day='2026-10-21'):
        return module.validated_failures(receipt or self.receipt, 'soultin',
                                         attempts or [self.attempt], day, now or self.now)

    def test_exact_old_terminal_failure_only(self):
        self.assertEqual(self.validate(), {module.failure_identity(self.attempt)})
        for field, value in [('phase', 'unknown'), ('phase', 'submitting'), ('phase', 'started'),
                             ('submissionStarted', True), ('preSubmissionFailure', False),
                             ('startedAt', '2026-10-21T08:00:00+09:00'), ('failureReason', 'changed'),
                             ('publicationDate', '2026-10-21')]:
            changed = dict(self.attempt, **{field: value})
            self.assertFalse(self.validate(attempts=[changed]), (field, value))

    def test_stale_wrong_identity_and_nonempty_reservation_fail_closed(self):
        self.assertFalse(self.validate(now=self.now + timedelta(minutes=11)))
        self.assertFalse(self.validate(day='2026-10-20'))
        for section, key, value in [('identity', 'authenticatedAccount', 'other'),
                                    ('identity', 'identityVerified', False),
                                    ('reservation', 'reservationCount', 1),
                                    ('reservation', 'independentReadings', 1),
                                    ('publicHead', 'ids', ['999'])]:
            changed = copy.deepcopy(self.receipt)
            changed[section][key] = value
            self.assertFalse(self.validate(changed), (section, key))

    def test_inventory_hash_and_partial_catalog_rejected(self):
        self.inventory.write_text('{}')
        self.assertFalse(self.validate())

    def test_gate_isolates_only_old_failure_preserves_journal(self):
        path = module.receipt_path(self.base, 'soultin')
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps(self.receipt))
        original = copy.deepcopy(self.attempt)
        with patch.object(runner, 'read_journal', return_value={'attempts': [self.attempt]}), \
                patch.object(runner, 'state_entries', return_value=[]):
            self.assertEqual(runner.account_gate('soultin', self.base, self.now,
                                                scheduled_slot='19:30', publication_date='2026-10-21'), 'waiting')
            self.assertEqual(runner.account_gate('soultin', self.base, self.now + timedelta(minutes=11),
                                                scheduled_slot='19:30', publication_date='2026-10-21'), 'unknown')
        self.assertEqual(self.attempt, original)

    def test_new_or_unresolved_attempt_keeps_account_blocked(self):
        path = module.receipt_path(self.base, 'soultin')
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps(self.receipt))
        for phase in ('started', 'submitting', 'unknown', 'failed'):
            new = dict(self.attempt, phase=phase, startedAt='2026-10-21T08:00:00+09:00',
                       workDate='2026-10-21', publicationDate='2026-10-21')
            with patch.object(runner, 'read_journal', return_value={'attempts': [self.attempt, new]}), \
                    patch.object(runner, 'state_entries', return_value=[]):
                self.assertEqual(runner.account_gate('soultin', self.base, self.now,
                                                    scheduled_slot='19:30', publication_date='2026-10-21'),
                                 'unknown', phase)

    def test_renewal_is_exact_worker_bound_and_still_expires(self):
        worker = {'account': 'soultin', 'workerId': 'one-worker', 'phase': 'started',
                  'startedAt': (self.now + timedelta(minutes=5)).isoformat(),
                  'publicationDate': '2026-10-21'}
        renewed = copy.deepcopy(self.receipt)
        later = self.now + timedelta(minutes=20)
        renewed['checkedAt'] = later.isoformat()
        for section in ('identity', 'reservation', 'publicHead'):
            renewed[section]['checkedAt'] = later.isoformat()
        renewed['renewal'] = {'workerId': worker['workerId'], 'startedAt': worker['startedAt']}
        self.assertTrue(self.validate(renewed, [self.attempt, worker], later))
        self.assertFalse(self.validate(renewed, [self.attempt, dict(worker, workerId='other')], later))
        self.assertFalse(self.validate(renewed, [self.attempt, dict(worker, phase='unknown')], later))
        self.assertFalse(self.validate(renewed, [self.attempt, worker], later + timedelta(minutes=11)))
        self.assertFalse(self.validate(renewed, [self.attempt, worker], later, '2026-10-22'))

    def test_public_collector_requires_full_stable_catalog_and_reuses_verified_cache(self):
        first = [{'logNo': str(i), 'title': 'title', 'addDate': '2026. 10. 19.'} for i in range(30, 0, -1)]
        last = [{'logNo': '31', 'title': 'older', 'addDate': '2026. 10. 18.'}]
        def response(rows, total=31):
            return SimpleNamespace(raise_for_status=lambda: None,
                                   text=json.dumps({'resultCode': 'S', 'totalCount': str(total), 'postList': rows}))
        with patch('requests.get', side_effect=[response(first), response(last), response(first)]) as get, \
                patch.object(runner, 'now_kst', return_value=self.now), patch('time.sleep'):
            path = module.collect_full_public_inventory(self.base, 'soultin')
            self.assertEqual(get.call_count, 3)
        data = json.loads(path.read_text())['accounts']['soultin']
        self.assertEqual(len(data['posts']), 31)
        with patch('requests.get', return_value=response(first)) as get, \
                patch.object(runner, 'now_kst', return_value=self.now):
            self.assertEqual(module.collect_full_public_inventory(self.base, 'soultin'), path)
            self.assertEqual(get.call_count, 1)
        path.unlink()
        with patch('requests.get', side_effect=[response(first), response(last, 32)]), \
                patch.object(runner, 'now_kst', return_value=self.now), patch('time.sleep'):
            with self.assertRaises(ValueError):
                module.collect_full_public_inventory(self.base, 'soultin')
        self.assertFalse(path.exists())

    def nonempty_observation(self, title='Other article', when='2026-10-21 11:00'):
        observation = copy.deepcopy(self.receipt['reservation'])
        observation['reservationCount'] = 1
        observation['reservations'] = [{'title': title, 'reserveTime': when}]
        for row in observation['serverCountEvidence']:
            if row['requestQuery']['editorVersion'] == ['4']:
                row['totalCount'] = 1
        return observation

    def test_complete_nonempty_list_allows_other_slot_but_blocks_occupied_slot(self):
        self.receipt['reservation'] = self.nonempty_observation()
        self.assertTrue(self.validate())
        path = module.receipt_path(self.base, 'soultin')
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps(self.receipt))
        with patch.object(runner, 'read_journal', return_value={'attempts': [self.attempt]}), \
                patch.object(runner, 'state_entries', return_value=[]):
            self.assertEqual(runner.account_gate('soultin', self.base, self.now,
                                                scheduled_slot='19:30', publication_date='2026-10-21'), 'waiting')
            self.assertEqual(runner.account_gate('soultin', self.base, self.now,
                                                scheduled_slot='11:00', publication_date='2026-10-21',
                                                allow_custom=True), 'unknown')
        known = dict(self.attempt, phase='verified', topic='Other article',
                     reserveTime='2026-10-21 11:00', verificationSource='actual-list')
        with patch.object(runner, 'read_journal', return_value={'attempts': [self.attempt, known]}), \
                patch.object(runner, 'state_entries', return_value=[]):
            self.assertEqual(runner.account_gate('soultin', self.base, self.now,
                                                scheduled_slot='11:00', publication_date='2026-10-21',
                                                allow_custom=True), 'verified')

    def test_nonempty_count_mismatch_and_legacy_reservations_rejected(self):
        observation = self.nonempty_observation()
        observation['reservations'] = []
        self.assertIsNone(module.validated_reservation_rows(observation, 'mustpickinfo', self.now))
        observation = self.nonempty_observation()
        observation['serverCountEvidence'][0]['totalCount'] = 1
        self.assertIsNone(module.validated_reservation_rows(observation, 'mustpickinfo', self.now))

    def test_final_guard_propagates_collection_failure_and_blocks_collisions(self):
        account = {'account_key': 'soultin', 'blog_id': 'mustpickinfo'}
        with patch.object(runner, 'collect_existing_reservations', side_effect=RuntimeError('offline')):
            with self.assertRaisesRegex(RuntimeError, 'offline'):
                runner.check_existing_reservations(None, account, title='New', reserve_time='2026-10-21 19:30')
        for title, when in [('New', '2026-10-21 19:30'), ('Other article', '2026-10-21 11:00')]:
            with patch.object(runner, 'collect_existing_reservations', return_value=self.nonempty_observation(title, when)), \
                    patch.object(runner, 'now_kst', return_value=self.now):
                with self.assertRaisesRegex(RuntimeError, 'already occupies'):
                    runner.check_existing_reservations(None, account, title='Other article',
                                                       reserve_time='2026-10-21 19:30')
        with patch.object(runner, 'collect_existing_reservations', return_value=self.nonempty_observation()), \
                patch.object(runner, 'now_kst', return_value=self.now):
            result = runner.check_existing_reservations(None, account, title='Brand new',
                                                        reserve_time='2026-10-21 19:30')
            self.assertEqual(result['reservationCount'], 1)


if __name__ == '__main__':
    unittest.main()
