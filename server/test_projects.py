"""Isolated inventory regressions: no live files, databases or settings writes."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from projects import PROJECT_REGISTRY, inventory, load_manifest, _load_play_track_truth, compute_closed_test_schedule, build_admob_tracker


class ProjectInventoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)

    def write(self, project_id, **updates):
        relative = dict(PROJECT_REGISTRY)[project_id]
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        value = {'id': project_id, 'name': project_id, 'milestones': []}
        value.update(updates)
        path.write_text(json.dumps(value), encoding='utf-8')
        return path

    def test_missing_scopes_are_explicit(self):
        result = inventory(self.root)
        self.assertEqual(result['status'], 'missing')
        self.assertEqual(result['expectedProjects'], 4)
        self.assertEqual(len(result['sources']), 4)

    def test_all_four_are_independently_collected(self):
        for project_id, _ in PROJECT_REGISTRY:
            self.write(project_id)
        result = inventory(self.root)
        self.assertEqual(result['status'], 'collected')
        self.assertEqual([p['id'] for p in result['projects']], [p[0] for p in PROJECT_REGISTRY])

    def test_corrupt_new_app_does_not_hide_bible(self):
        self.write('bible_app')
        path = self.write('shopping')
        path.write_text('{broken', encoding='utf-8')
        result = inventory(self.root)
        self.assertEqual(result['status'], 'partial')
        self.assertEqual([p['id'] for p in result['projects']], ['bible_app'])
        self.assertEqual({s['id']: s['status'] for s in result['sources']}['shopping'], 'invalid')

    def test_wrong_identity_and_oversized_files_are_isolated(self):
        self.write('bible_app')
        self.write('magnifier', id='bible_app')
        self.write('greeting').write_text('x' * 65537)
        result = inventory(self.root)
        self.assertEqual([p['id'] for p in result['projects']], ['bible_app'])
        self.assertEqual(sum(s['status'] == 'invalid' for s in result['sources']), 2)

    def test_unknown_metrics_and_unproved_milestones_stay_unknown(self):
        self.write('bible_app', measurement={'admob': {'status': 'not_connected', 'revenue': 0},
                   'analytics': {'status': 'collected', 'activeUsers': 12, 'checkedAt': {}, 'period': 'today'}},
                   milestones=[{'id': 'release', 'status': 'verified', 'verifiedAt': {'fake': True}, 'evidence': 'file'}])
        app = inventory(self.root)['projects'][0]
        self.assertIsNone(app['measurement']['admob']['revenue'])
        self.assertIsNone(app['measurement']['analytics']['activeUsers'])
        self.assertEqual(app['milestones'][0]['status'], 'in_progress')

    def test_real_zero_needs_source_metadata(self):
        self.write('bible_app', measurement={'admob': {'status': 'collected', 'revenue': 0,
                   'checkedAt': '2026-10-14T10:00:00+09:00', 'period': '2026-10-14'}})
        self.assertEqual(inventory(self.root)['projects'][0]['measurement']['admob']['revenue'], 0)

    def test_secrets_and_unsafe_urls_never_enter_public_response(self):
        for url in ['https://127.0.0.1/', 'https://10.0.0.1/', 'https://user:pass@example.com/', 'http://example.com/']:
            self.write('bible_app', publicUrl=url, api_key='DO_NOT_ECHO')
            result = inventory(self.root)
            self.assertIsNone(result['projects'][0]['publicUrl'])
            self.assertNotIn('DO_NOT_ECHO', json.dumps(result))

    def test_historical_device_verification_does_not_verify_new_release(self):
        path = self.write('greeting', milestones=[{
            'id': 'device_test', 'status': 'verified',
            'verifiedAt': '2026-10-19T02:08:41+09:00', 'evidence': 'CEO Samsung v2',
            'verifiedVersionCode': 2,
        }], releaseBuild={'versionCode': 3, 'versionName': '0.3.0', 'physicalDeviceVerifiedForThisBuild': False})
        with patch('projects.verify_app_ads_txt', return_value={}), patch('projects._load_play_track_truth', return_value={}):
            app = load_manifest(path, 'greeting')['projects'][0]
        self.assertTrue(app['deviceVerified'])
        self.assertEqual(app['deviceVerifiedVersionCode'], 2)
        self.assertEqual(app['latestBuildVersionCode'], 3)
        self.assertEqual((app['versionCode'], app['versionName']), (3, '0.3.0'))
        self.assertFalse(app['latestBuildPhysicalDeviceVerified'])
        self.assertIn('v2 검증 완료', app['blocker'])
        self.assertIn('v3 실기기 미검증', app['blocker'])
        self.assertEqual(app['deviceVerificationLabel'], app['admobTracker']['deviceVerificationLabel'])
        self.assertEqual(app['admobTracker']['productionChecklist'][1]['status'], 'ready')

    def test_missing_device_version_is_not_inferred_from_release(self):
        path = self.write('bible_app', milestones=[{
            'id': 'device_test', 'status': 'verified',
            'verifiedAt': '2026-10-19T02:08:41+09:00', 'evidence': 'CEO report',
        }], releaseBuild={'versionCode': 5, 'physicalDeviceVerifiedForThisBuild': False})
        with patch('projects.verify_app_ads_txt', return_value={}), patch('projects._load_play_track_truth', return_value={}):
            app = load_manifest(path, 'bible_app')['projects'][0]
        self.assertIsNone(app['deviceVerifiedVersionCode'])
        self.assertIn('검증 버전 미기록', app['deviceVerificationLabel'])
        self.assertIn('v5 실기기 미검증', app['deviceVerificationLabel'])

    def test_submitted_alpha_does_not_request_promotion_or_start_from_list_count(self):
        path = self.root / 'apps' / 'deployment.json'
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({'apps': {'greeting': {
            'internalTesterListCount': 13,
            'closedTesting': {'reviewSubmitted': True, 'trackActive': True},
        }}}), encoding='utf-8')
        with patch('projects.load_app_testers', return_value={'emailCount': 13}), patch('projects.verify_app_ads_txt', return_value={}):
            truth = _load_play_track_truth('greeting', self.root)
            schedule = compute_closed_test_schedule('2026-10-19T02:45:00+09:00', track_truth=truth)
            tracker = build_admob_tracker('greeting', schedule)
        self.assertEqual(truth['internalTestersCount'], 13)
        self.assertTrue(schedule['closedReviewSubmitted'])
        self.assertFalse(schedule['countdownStarted'])
        self.assertIn('Google 검토 완료 후', tracker['nextAction'])
        self.assertIn('등록 명단 수는 참여 인원이 아니며', tracker['nextAction'])
        self.assertNotIn('승격을 실행', tracker['nextAction'])
        self.assertNotIn('14개 구글 계정', tracker['nextAction'])


if __name__ == '__main__':
    unittest.main()
