"""Isolated installation ledger/API regressions; no browser or live-state writes."""
import copy
import json
import tempfile
import subprocess
import sys
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch
from common import app_testers_store as store

class TesterStoreTests(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.patch = patch.object(store, 'ROOT', self.root)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.path = self.root / 'server/data/app_testers.json'
        self.path.parent.mkdir(parents=True)
        self.original = {'emails': ['baro76650@gmail.com', 'barolab26@gmail.com'] + [f'fixture{i}@example.test' for i in range(11)], 'customExisting': {'keep': True}, 'closedTestOptIns': None, 'closedTestOptInsVerified': False, 'closedTestStartAt': None, 'apps': {'bible_app': {'unknownField': 'preserved'}}}
        self.path.write_text(json.dumps(self.original), encoding='utf-8')
        self.now = datetime(2026, 10, 19, 23, 59, tzinfo=store.KST)

    def load(self, when=None):
        return store.load_app_testers(now=when or self.now)

    def test_initial_two_once_and_uncheck_survives_reloads(self):
        doc = self.load()
        self.assertEqual((doc['emailCount'], doc['localTracking']['installedCount']), (13, 2))
        self.assertEqual(len({x['slot'] for x in doc['accounts']}), 13)
        self.assertIsNone(doc['localTracking']['startedAt'])
        row = doc['accounts'][0]
        store.patch_installation(row['id'], False, expected_revision=doc['revision'], now=self.now)
        for _ in range(3):
            current = self.load()
            self.assertFalse(current['accounts'][0]['installed'])
            self.assertEqual(current['localTracking']['installedCount'], 1)
        self.assertEqual(current['customExisting'], self.original['customExisting'])

    def test_threshold_kst_day_and_continuity_reset_with_history(self):
        doc = self.load()
        for row in doc['accounts'][2:12]:
            store.patch_installation(row['id'], True, now=self.now)
        started = self.load()['localTracking']
        self.assertEqual((started['installedCount'], started['dayNumber']), (12, 1))
        next_day = self.load(self.now + timedelta(minutes=2))['localTracking']
        self.assertEqual((next_day['dayNumber'], next_day['elapsedDays']), (2, 0))
        self.assertFalse(next_day['googleQualificationVerified'])
        row = doc['accounts'][11]
        reset = store.patch_installation(row['id'], False, now=self.now + timedelta(days=3))
        self.assertIsNone(reset['localTracking']['startedAt'])
        self.assertEqual(reset['localTracking']['history'][-1]['type'], 'continuity_reset')
        restarted = store.patch_installation(row['id'], True, now=self.now + timedelta(days=4))
        self.assertNotEqual(started['startedAt'], restarted['localTracking']['startedAt'])
        self.assertEqual(restarted['localTracking']['dayNumber'], 1)
        self.assertIsNone(restarted['closedTestOptIns'])
        self.assertIsNone(restarted['closedTestStartAt'])

    def test_fourteen_day_status_does_not_confirm_google(self):
        doc = self.load()
        for row in doc['accounts'][2:12]:
            store.patch_installation(row['id'], True, now=self.now)
        tracking = self.load(self.now + timedelta(days=14))['localTracking']
        self.assertEqual(tracking['status'], 'local_14_days_elapsed')
        self.assertEqual(tracking['dayNumber'], 14)
        self.assertFalse(tracking['googleQualificationVerified'])

    def test_revision_conflict_and_idempotent_same_value(self):
        doc = self.load()
        row = doc['accounts'][2]
        result = store.patch_installation(row['id'], True, expected_revision=doc['revision'], now=self.now)
        before = self.path.read_bytes()
        same = store.patch_installation(row['id'], True, expected_revision=result['revision'], now=self.now)
        self.assertEqual(same['revision'], result['revision'])
        self.assertEqual(before, self.path.read_bytes())
        with self.assertRaises(store.RevisionConflict):
            store.patch_installation(row['id'], False, expected_revision=doc['revision'], now=self.now)
        self.assertEqual(before, self.path.read_bytes())

    def test_stale_automator_save_preserves_installations_and_unknown_metadata(self):
        stale = self.load()
        row = stale['accounts'][2]
        store.patch_installation(row['id'], True, now=self.now)
        stale['syncStatus'] = 'verified'
        saved = store.save_app_testers(stale, now=self.now)
        self.assertTrue(saved['accounts'][2]['installed'])
        self.assertEqual(saved['localTracking']['installedCount'], 3)
        self.assertEqual(saved['apps']['bible_app']['unknownField'], 'preserved')

    def test_two_concurrent_different_accounts_no_lost_update(self):
        doc = self.load()
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda row: store.patch_installation(row['id'], True, now=self.now), doc['accounts'][2:4]))
        self.assertEqual(len(results), 2)
        self.assertEqual(self.load()['localTracking']['installedCount'], 4)

    def test_two_processes_share_os_lock_and_preserve_both_updates(self):
        doc = self.load()
        code = 'import sys;from pathlib import Path;from common import app_testers_store as s;s.ROOT=Path(sys.argv[1]);s.patch_installation(sys.argv[2],True)'
        workers = [subprocess.Popen([sys.executable, '-c', code, str(self.root), row['id']], stdout=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0)) for row in doc['accounts'][2:4]]
        for worker in workers:
            _, error = worker.communicate(timeout=15)
            self.assertEqual(worker.returncode, 0, error.decode(errors='replace'))
        self.assertEqual(self.load()['localTracking']['installedCount'], 4)

    def test_atomic_failure_and_corrupt_canonical_never_reset(self):
        doc = self.load()
        before = self.path.read_bytes()
        with patch.object(store.os, 'replace', side_effect=OSError('disk unavailable')):
            with self.assertRaises(OSError):
                store.patch_installation(doc['accounts'][2]['id'], True, now=self.now)
        self.assertEqual(before, self.path.read_bytes())
        self.assertEqual(list(self.path.parent.glob('*.tmp')), [])
        self.path.write_text('{invalid', encoding='utf-8')
        with self.assertRaises(json.JSONDecodeError):
            self.load()
        self.assertEqual(self.path.read_text(), '{invalid')

    def test_roster_removal_resets_and_preserves_removed_account(self):
        doc = self.load()
        for row in doc['accounts'][2:12]:
            store.patch_installation(row['id'], True, now=self.now)
        doc = self.load()
        removed = doc['accounts'][11]
        doc['emails'].remove(removed['email'])
        current = store.save_app_testers(doc, now=self.now)
        self.assertIsNone(current['localTracking']['startedAt'])
        self.assertEqual(current['removedAccounts'][0]['id'], removed['id'])
        self.assertEqual(current['removedAccounts'][0]['installedAt'], removed['installedAt'])

    def test_console_zero_persists_separately_without_manual_revision_churn(self):
        doc = self.load()
        observation = {'status': 'collected', 'checkedAt': self.now.isoformat(), 'alpha': {'trackActive': True}, 'googleOptInCount': 0, 'googleInstallCount': None, 'continuousTestDays': None, 'evidence': [{'page': 'alpha', 'signals': {'optIn': 'actual explicit 0'}}]}
        result = store.save_console_evidence({'apps': {'bible_app': observation}})
        after = self.load()
        self.assertEqual(after['revision'], doc['revision'])
        self.assertEqual(after['accounts'], doc['accounts'])
        self.assertEqual(after['localTracking']['installedCount'], 2)
        self.assertEqual(after['consoleEvidence']['bible_app']['googleOptInCount'], 0)
        self.assertFalse(store.save_console_evidence({'apps': {'bible_app': observation}})['saved'])
        self.assertFalse(store.save_console_evidence({'apps': {'bible_app': {'status': 'error'}}})['saved'])
        self.assertTrue(result['saved'])

    def test_api_strict_bool_conflict_and_manual_optin_rejected(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from server import projects
        app = FastAPI()
        app.include_router(projects.router)
        client = TestClient(app)
        doc = self.load()
        row = doc['accounts'][2]
        with patch.object(projects, 'tester_control_center', side_effect=lambda doc=None: doc or self.load()):
            bad = client.patch('/api/projects/testers/accounts/' + row['id'], json={'installed': 'true'})
            self.assertEqual(bad.status_code, 422)
            ok = client.patch('/api/projects/testers/accounts/' + row['id'], json={'installed': True, 'expectedRevision': doc['revision']})
            self.assertEqual(ok.status_code, 200)
            conflict = client.patch('/api/projects/testers/accounts/' + row['id'], json={'installed': False, 'expectedRevision': doc['revision']})
            self.assertEqual(conflict.status_code, 409)
            rejected = client.post('/api/projects/testers', json={'closedTestOptIns': 12})
            self.assertEqual(rejected.status_code, 400)
if __name__ == '__main__':
    unittest.main()
