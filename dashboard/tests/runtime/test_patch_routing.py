import unittest
from unittest.mock import patch
from server import agent_tools as a

class PatchRoutingTests(unittest.TestCase):

    def test_code_never_falls_through_to_post_or_watchdog(self):
        with patch.object(a, 'run_watchdog_heal') as heal, patch.object(a, 'run_doctor_remodel_url') as publish:
            result = a.maybe_execute_tools_for_message('patch', '코드 고쳐 작업 https://must-good.com/example')
        self.assertEqual(result[0]['status'], 'needs_input')
        heal.assert_not_called()
        publish.assert_not_called()

    def test_exact_files_reach_proposal(self):
        with patch.object(a, 'propose_patch_code', return_value={'status': 'proposed'}) as propose:
            a.maybe_execute_tools_for_message('patch', 'common/example.py 버그 수정 test_example.py')
        self.assertEqual(propose.call_args.args[:2], (['common/example.py'], ['test_example.py']))

    def test_diagnostic_does_not_repair(self):
        with patch.object(a, 'read_patch_data', return_value={}), patch.object(a, 'fix_scheduler_task') as repair:
            result = a.maybe_execute_tools_for_message('patch', '스케줄러 작업 확인해')
        self.assertEqual(result[0]['status'], 'observed')
        repair.assert_not_called()

    def test_linux_heal_reuses_native_session_and_timer_start_is_idempotent(self):
        with patch('common.ubuntu_naver_browser.ensure_account', return_value=123) as ensure, patch.object(a, 'probe_cdp_port', return_value={}), patch.object(a.subprocess, 'run') as run:
            run.return_value.returncode = 0
            self.assertEqual(a.restart_browser_cdp(9334)['pid'], 123)
            self.assertTrue(a.fix_scheduler_task()['ok'])
            ensure.assert_called_once_with(9334)
            self.assertEqual(run.call_args.args[0], ['systemctl', '--user', 'start', 'barolab-kin.timer'])

    def test_job_status_requires_exact_pair(self):
        with patch.object(a, 'read_patch_code_status', return_value={}) as read:
            a.maybe_execute_tools_for_message('patch', 'job:' + 'a' * 32 + ' sha:' + 'b' * 64)
        read.assert_called_once_with('a' * 32, 'b' * 64)

    def test_non_patch_direct_coding_tool_rejected(self):
        self.assertEqual(a.execute_agent_tool('publi', 'propose_coding_job')['status'], 'forbidden')
if __name__ == '__main__':
    unittest.main()
