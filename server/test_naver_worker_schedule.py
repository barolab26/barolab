"""Offline checks for the existing-task recovery configurator; no task mutations."""
import json
import subprocess
import unittest
from unittest.mock import patch

from server import windows_worker as worker


class NaverRecoveryScheduleTests(unittest.TestCase):
    def test_existing_daily_action_routes_to_bounded_catch_up(self):
        with patch.object(worker.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0)) as run:
            self.assertEqual(worker.run_task('naver-daily'), 0)
        self.assertEqual(run.call_args.args[0][-1], '--catch-up')

    def call(self, apply=False, response=None):
        receipt = response or dict(applied=apply, actionVerified=True)
        with patch.object(worker.os, 'name', 'nt'), patch.object(worker.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, json.dumps(receipt), '')) as run:
            result = worker.configure_naver_recovery_schedule(apply=apply)
        return result, run.call_args

    def test_default_preview_is_read_only(self):
        report, call = self.call()
        self.assertFalse(report['applied'])
        script = call.args[0][-1]
        for mutation in ('Set-ScheduledTask', 'Export-ScheduledTask', 'New-ScheduledTaskTrigger', '[IO.File]::Open'):
            self.assertNotIn(mutation, script)
        self.assertNotIn('BAROLAB_NAVER_TASK_BACKUP', call.kwargs['env'])

    def test_apply_preserves_action_account_and_other_settings(self):
        _, call = self.call(apply=True)
        script = call.args[0][-1]
        self.assertIn('$settings = $task.Settings', script)
        self.assertIn('-AtLogOn -User $task.Principal.UserId', script)
        self.assertIn('-Once -At (Get-Date).AddMinutes(1)', script)
        self.assertNotIn('Register-ScheduledTask', script)
        self.assertNotIn('Start-ScheduledTask', script)
        self.assertNotIn('Stop-ScheduledTask', script)
        self.assertLess(script.index('Export-ScheduledTask'), script.index('Set-ScheduledTask'))
        self.assertIn('[IO.FileMode]::CreateNew', script)
        self.assertIn('.barolab', call.kwargs['env']['BAROLAB_NAVER_TASK_BACKUP'])

    def test_action_validation_precedes_mutation(self):
        script = worker._naver_recovery_schedule_script(True)
        self.assertLess(script.index('$actions.Count -ne 1'), script.index('Set-ScheduledTask'))
        self.assertIn('[string]::Equals($actions[0].Arguments', script)
        self.assertIn('configuration refused', script)

    def test_provider_error_is_not_success(self):
        with patch.object(worker.os, 'name', 'nt'), patch.object(worker.subprocess, 'run', return_value=subprocess.CompletedProcess([], 1, '', 'wrong action')), self.assertRaisesRegex(RuntimeError, 'configuration failed'):
            worker.configure_naver_recovery_schedule()

    def test_missing_or_wrong_receipt_is_not_success(self):
        for receipt in (dict(applied=False), dict(applied=True, actionVerified=True), dict(applied=False, actionVerified=1)):
            with self.subTest(receipt=receipt), self.assertRaisesRegex(RuntimeError, 'invalid configuration receipt'):
                self.call(response=receipt)


if __name__ == '__main__':
    unittest.main()
