"""Read-only scheduler observation regression tests."""
from types import SimpleNamespace
import unittest
from naver_blog_posting import pipeline_runner as runner


def result(text, code=0):
    return SimpleNamespace(stdout=text, returncode=code)


class SystemdSchedulerTests(unittest.TestCase):
    def test_missing_timer_is_observed_missing(self):
        status = runner.observe_systemd_daily_scheduler(query=lambda _: result('LoadState=not-found\nActiveState=inactive'))
        self.assertEqual(status['state'], 'Missing')
        self.assertIs(status['registered'], False)
        self.assertIs(status['workflowMatches'], False)

    def test_active_timer_requires_matching_daily_command(self):
        def query(command):
            if command[3].endswith('.timer'):
                return result('LoadState=loaded\nActiveState=active\nUnitFileState=enabled\nUnit=barolab-naver-daily.service')
            return result('LoadState=loaded\nExecStart=' + str(runner.PROJECT_ROOT / 'server/windows_worker.py') + ' --task naver-daily ;')
        status = runner.observe_systemd_daily_scheduler(query=query)
        self.assertEqual(status['state'], 'Active')
        self.assertIs(status['enabled'], True)
        self.assertIs(status['workflowMatches'], True)

    def test_failed_timer_is_not_active(self):
        status = runner.observe_systemd_daily_scheduler(query=lambda _: result('LoadState=loaded\nActiveState=failed\nUnitFileState=enabled'))
        self.assertEqual(status['state'], 'Failed')
        self.assertIs(status['workflowMatches'], False)

    def test_active_timer_with_failed_service_reports_failure(self):
        def query(command):
            if command[3].endswith('.timer'):
                return result('LoadState=loaded\nActiveState=active\nUnitFileState=enabled\nUnit=barolab-naver-daily.service')
            return result('LoadState=loaded\nActiveState=failed\nResult=exit-code\nExecMainStatus=1\nExecStart='
                          + str(runner.PROJECT_ROOT / 'server/windows_worker.py') + ' --task naver-daily ;')
        status = runner.observe_systemd_daily_scheduler(query=query)
        self.assertEqual(status['state'], 'Failed')
        self.assertEqual(status['lastResult'], 'exit-code')
        self.assertEqual(status['lastExitCode'], '1')
        self.assertIn('서비스 실행 실패', status['reason'])

    def test_missing_service_cannot_match_workflow(self):
        def query(command):
            if command[3].endswith('.timer'):
                return result('LoadState=loaded\nActiveState=active\nUnitFileState=enabled\nUnit=barolab-naver-daily.service')
            return result('LoadState=not-found\nExecStart='
                          + str(runner.PROJECT_ROOT / 'server/windows_worker.py') + ' --task naver-daily ;')
        self.assertIs(runner.observe_systemd_daily_scheduler(query=query)['workflowMatches'], False)

    def test_active_unrelated_command_is_not_daily_workflow(self):
        def query(command):
            return result('LoadState=loaded\nActiveState=active\nUnitFileState=enabled\nUnit=other.service'
                          if command[3].endswith('.timer') else 'LoadState=loaded\nExecStart=/bin/true')
        status = runner.observe_systemd_daily_scheduler(query=query)
        self.assertIs(status['workflowMatches'], False)
        self.assertIn('일치하지 않음', status['reason'])

    def test_query_failure_does_not_reuse_windows_success(self):
        status = runner.observe_systemd_daily_scheduler(
            {'status': 'observed', 'source': 'Windows Task Scheduler read-only', 'checkedAt': 'old'},
            query=lambda _: result('', 1))
        self.assertEqual(status['state'], 'Unknown')
        self.assertIsNone(status['registered'])
        self.assertIsNone(status['checkedAt'])

    def test_malformed_output_is_unknown(self):
        status = runner.observe_systemd_daily_scheduler(query=lambda _: result(''))
        self.assertEqual(status['state'], 'Unknown')


if __name__ == '__main__':
    unittest.main()
