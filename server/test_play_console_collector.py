import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch

from server import play_console_collector as c


def observation(app='bible_app', count=0, status='Google Play에서 테스터에게 제공 전체 출시'):
    base = f'https://play.google.com/console/u/0/developers/{c.DEVELOPER_ID}/app/{c.APP_IDS[app]}'
    return {
        'releases': {'url': base + '/releases/overview', 'text': '최신 버전 및 번들',
                     'rows': [['0.5.0 개선', '5', '비공개 테스트 - Alpha', status, '2026년 10월 19일', '1 /178', '0.00%'],
                              ['0.5.0 개선', '5', '내부 테스트', '내부 테스터에게 제공됨 전체 출시', '-', '-', '0.00%']]},
        'dashboard': {'url': base + '/app-dashboard', 'text':
                      f'비공개 테스트\n활성\n트랙 1개\n12명 이상의 테스터가 비공개 테스트 참여를 선택\n'
                      f'현재 참여를 선택한 테스터 {count}명\n12명 이상의 테스터를 대상으로 14일 이상 비공개 테스트 실행'},
    }


class ParserTests(unittest.TestCase):
    def test_actual_zero_and_one_are_per_app_and_not_requirement(self):
        bible = c.parse_observation('bible_app', observation(count=0))
        greeting = c.parse_observation('greeting', observation('greeting', 1))
        self.assertEqual(bible['googleOptInCount'], 0)
        self.assertEqual(greeting['googleOptInCount'], 1)
        self.assertIsNone(bible['continuousTestDays'])
        self.assertIsNone(bible['googleInstallCount'])
        self.assertTrue(bible['alpha']['released'])
        self.assertEqual(bible['alpha']['reviewStatus'], 'approved')
        self.assertEqual(bible['alpha']['versionCode'], 5)
        self.assertTrue(bible['internal']['released'])

    def test_capacity_email_list_buckets_and_percentages_are_unknown(self):
        pages = observation()
        pages['dashboard']['text'] = '테스터 13명\n최대 100명의 내부 테스터\n12명 이상\n14일 이상\n설치한 사용자 수\n≤ 100\n0.00%\n설치 확인 2명'
        result = c.parse_observation('bible_app', pages)
        for field in ('googleOptInCount', 'googleInstallCount', 'continuousTestDays'):
            self.assertIsNone(result[field])

    def test_reviewing_alpha_is_not_internal_release_approval(self):
        result = c.parse_observation('bible_app', observation(status='검토 중'))
        self.assertEqual(result['alpha']['reviewStatus'], 'in_review')
        self.assertFalse(result['alpha']['released'])
        self.assertTrue(result['internal']['released'])

    def test_app_and_auth_redirect_rejected(self):
        for url in ['https://accounts.google.com/signin', observation('shopping')['dashboard']['url']]:
            pages = observation()
            pages['dashboard']['url'] = url
            with self.assertRaises(ValueError):
                c.parse_observation('bible_app', pages)

    def test_ambiguous_alpha_rows_not_guessed(self):
        pages = observation()
        pages['releases']['rows'].append(pages['releases']['rows'][0])
        result = c.parse_observation('bible_app', pages)
        self.assertIsNone(result['alpha']['released'])
        self.assertIsNone(result['alpha']['versionCode'])

    def test_missing_alpha_row_keeps_other_observations_without_guessing_review(self):
        pages = observation()
        pages['releases']['rows'] = pages['releases']['rows'][1:]
        result = c.parse_observation('bible_app', pages)
        self.assertEqual(result['status'], 'collected')
        self.assertIsNone(result['alpha']['released'])
        self.assertEqual(result['alpha']['reviewStatus'], 'unknown')
        self.assertTrue(result['internal']['released'])
        self.assertEqual(result['googleOptInCount'], 0)

    def test_explicit_continuous_day_measurement_only(self):
        pages = observation()
        pages['dashboard']['text'] += '\n연속 테스트 일수: 3일\n현재 설치된 기기: 2대'
        result = c.parse_observation('bible_app', pages)
        self.assertEqual(result['continuousTestDays'], 3)
        self.assertEqual(result['googleInstallCount'], 2)

    def test_actual_material_icon_does_not_hide_track_state(self):
        pages = observation()
        pages['dashboard']['text'] = pages['dashboard']['text'].replace('활성\n트랙', '활성\nbrightness_1\n트랙')
        self.assertTrue(c.parse_observation('bible_app', pages)['alpha']['trackActive'])


class CacheAndOwnershipTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'status.json'

    def reader(self):
        return {app: c.parse_observation(app, observation(app, i))
                for i, app in enumerate(c.APP_IDS)}, {'tabOwnership': 'owned_and_closed'}

    def test_ttl_suppresses_duplicate_collection_and_force_is_explicit(self):
        reader = Mock(side_effect=self.reader)
        self.assertTrue(c.refresh_console_status(path=self.path, reader=reader))
        self.assertFalse(c.refresh_console_status(path=self.path, reader=reader))
        self.assertEqual(reader.call_count, 1)
        self.assertTrue(c.refresh_console_status(path=self.path, reader=reader, force=True))
        self.assertEqual(reader.call_count, 2)

    def test_temporary_collection_never_mirrors_production_tester_store(self):
        with patch('common.app_testers_store.save_console_evidence') as mirror:
            c.refresh_console_status(path=self.path, reader=self.reader)
            mirror.assert_not_called()

    def test_error_retains_previous_timestamp_and_actual_zero(self):
        c.refresh_console_status(path=self.path, reader=self.reader)
        before = json.loads(self.path.read_text(encoding='utf-8'))
        c.refresh_console_status(path=self.path, reader=Mock(side_effect=RuntimeError('private details')), force=True)
        after = c.get_console_status(False, path=self.path)
        self.assertEqual(after['apps']['bible_app']['googleOptInCount'], 0)
        self.assertEqual(after['apps']['bible_app']['checkedAt'], before['apps']['bible_app']['checkedAt'])
        self.assertTrue(after['apps']['bible_app']['stale'])
        self.assertNotIn('private details', json.dumps(after))

    def test_cross_thread_lock_prevents_overlap(self):
        entered, release = threading.Event(), threading.Event()
        def slow_reader():
            entered.set()
            release.wait(3)
            return self.reader()
        worker = threading.Thread(target=lambda: c.refresh_console_status(path=self.path, reader=slow_reader))
        worker.start()
        self.assertTrue(entered.wait(2))
        try:
            second = Mock(side_effect=self.reader)
            self.assertFalse(c.refresh_console_status(path=self.path, reader=second, force=True))
            second.assert_not_called()
            started = time.monotonic()
            result = c.get_console_status(False, path=self.path)
            self.assertLess(time.monotonic() - started, .5)
            self.assertEqual(result['status'], 'collecting')
        finally:
            release.set()
            worker.join(3)

    def test_only_owned_tab_closed_even_on_failure(self):
        user, owned, browser = Mock(url='https://play.google.com/console/user-work'), Mock(), Mock()
        context = Mock(pages=[user])
        context.new_page.return_value = owned
        browser.contexts = [context]
        with self.assertRaises(RuntimeError):
            with c.owned_console_page(browser) as (page, ownership):
                self.assertIs(page, owned)
                self.assertEqual(ownership['existingTabCount'], 1)
                raise RuntimeError('read failed')
        owned.close.assert_called_once()
        user.close.assert_not_called()
        user.goto.assert_not_called()
        browser.close.assert_not_called()
        self.assertTrue(ownership['existingTabsPreserved'])

    def test_nas_returns_unknown_without_browser_connection(self):
        with patch.object(c.os, 'name', 'posix'), patch.object(c, '_schedule') as schedule:
            # _schedule is not reached on NAS when the real scheduling guard runs.
            schedule.return_value = False
            result = c.get_console_status(path=self.path)
        self.assertEqual(result['refreshPendingReason'], 'waiting_for_windows_collector')
        self.assertIsNone(result['apps']['bible_app']['googleOptInCount'])


if __name__ == '__main__':
    unittest.main()
