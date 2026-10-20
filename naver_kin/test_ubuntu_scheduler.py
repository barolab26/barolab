import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from naver_kin import scheduler, ubuntu_scheduler as module


class UbuntuSchedulerTests(unittest.TestCase):
    def query(self, timer='active', result='success', loaded='loaded'):
        def run(command, **kwargs):
            name = command[3]
            if name.endswith('.timer'):
                values = dict(LoadState=loaded, ActiveState=timer, UnitFileState='enabled',
                              Unit=name.replace('.timer', '.service'))
            else:
                action = '--measure' if 'measurement' in name else '--tick'
                values = dict(LoadState=loaded, ActiveState='inactive', Result=result,
                              ExecMainStatus='0' if result == 'success' else '1',
                              WorkingDirectory='/checkout',
                              ExecStart='/python -m naver_kin.scheduler ' + action + ' --scheduled')
            return SimpleNamespace(returncode=0, stdout='\n'.join(k+'='+v for k,v in values.items()))
        return run

    def test_actual_timer_and_linked_service_failure_are_distinct(self):
        value = module.observe('/checkout', lambda: 'now', self.query())
        self.assertEqual(value['platform'], 'systemd-user')
        self.assertTrue(all(row['registered'] and row['state'] == 'Ready' for row in value['tasks']))
        value = module.observe('/checkout', lambda: 'now', self.query(result='exit-code'))
        self.assertTrue(all(row['state'] == 'Failed' for row in value['tasks']))
        value = module.observe('/checkout', lambda: 'now', self.query(loaded='not-found'))
        self.assertTrue(all(not row['registered'] and row['state'] == 'Missing' for row in value['tasks']))

    def test_wrong_checkout_cannot_be_reported_as_registered(self):
        value = module.observe('/different', lambda: 'now', self.query())
        self.assertTrue(all(not row['workflowMatches'] for row in value['tasks']))

    def test_install_is_disabled_and_rejects_existing_foreign_or_active_unit(self):
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp)
            calls = []
            def run(command, **kwargs):
                calls.append(command)
                return SimpleNamespace(returncode=0, stdout='LoadState=not-found\nActiveState=inactive')
            result = module.install_disabled(Path('/checkout'), Path('/python'), home, run)
            self.assertFalse(result['enabledByThisOperation'])
            self.assertEqual(len(result['units']), 4)
            self.assertFalse(any('enable' in cmd or 'start' in cmd for cmd in calls))
            text = (home/'.config/systemd/user/barolab-kin-measurement.timer').read_text()
            self.assertIn('20:30:00 Asia/Seoul', text)
            self.assertIn('Persistent=false', text)
            path = home/'.config/systemd/user/barolab-kin.service'
            path.write_text('foreign')
            with self.assertRaisesRegex(RuntimeError, 'differs'):
                module.install_disabled(Path('/checkout'), Path('/python'), home, run)
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaisesRegex(RuntimeError, 'enabled or active'):
                module.install_disabled(Path('/checkout'), Path('/python'), Path(temp),
                    lambda *a, **k: SimpleNamespace(returncode=0, stdout='ActiveState=active\nUnitFileState=enabled'))

    def test_ubuntu_launchers_touch_only_two_authorized_accounts(self):
        with patch.object(scheduler, 'os', SimpleNamespace(name='posix')), \
                patch('common.ubuntu_naver_browser.accounts', return_value={
                    'adinfo0905': {'cdp_port': 9230}, 'stone0747': {'cdp_port': 9231}}), \
                patch('common.ubuntu_naver_browser.account_paths', return_value=(Path('/chrome'), Path('/profile'), Path('/launcher'))), \
                patch('common.ubuntu_naver_browser.process_identity', return_value=100) as identity, \
                patch('common.ubuntu_naver_browser.listener_owner') as listener, \
                patch('common.ubuntu_naver_browser.ensure_account') as ensure:
            result = scheduler.ensure_naver_browsers()
            self.assertEqual([call.args[0] for call in identity.call_args_list], [9230, 9231])
            self.assertEqual([call.args[0] for call in listener.call_args_list], [9230, 9231])
            ensure.assert_not_called()
            self.assertTrue(all(row['ready'] for row in result))
            identity.return_value = None
            with self.assertRaisesRegex(RuntimeError, 'browser is closed'):
                scheduler.ensure_naver_browsers()
            ensure.assert_not_called()


if __name__ == '__main__':
    unittest.main()
