"""Offline checks for the existing-task recovery configurator; no task mutations."""
import json
import os
import subprocess
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from server import windows_worker as worker


class NaverRecoveryScheduleTests(unittest.TestCase):
    def test_public_body_match_counts_observed_paragraphs_not_rss_defaults(self):
        from naver_blog_posting.public_verification import verify_public_body
        from unittest.mock import MagicMock
        paragraphs = ['첫 번째 실제 원고 문장은 충분히 길게 작성합니다', '두 번째 실제 원고 내용도 서로 다릅니다', '세 번째 신청 서류 준비 방법을 확인합니다']
        document = {'document': {'components': [{'paragraphs': [{'nodes': [{'value': text}]} for text in paragraphs]}]}}
        response = MagicMock(); response.status_code = 200
        response.content = ('<div class="se-main-container">' + ''.join('<p class="se-text-paragraph">' + p + '</p>' for p in paragraphs) + '</div>').encode('utf-8')
        with patch('naver_blog_posting.public_verification.requests.get', return_value=response), \
                patch('pathlib.Path.read_text', return_value=json.dumps(document)):
            report = verify_public_body('https://blog.naver.com/example/123', 'existing')
            self.assertTrue(report['publicBodyMatched'])
            self.assertEqual(report['matchedParagraphs'], 3)
            self.assertIsNone(report['tagsVerified'])
            response.content = b'<div class="se-main-container"></div>'
            self.assertIsNone(verify_public_body('https://blog.naver.com/example/123', 'existing')['publicBodyMatched'])

    def test_rss_public_url_without_saved_document_does_not_claim_body_match(self):
        from naver_blog_posting.public_verification import verify_public_body
        from unittest.mock import MagicMock
        response = MagicMock(); response.status_code = 200; response.content = b'<html></html>'
        with patch('naver_blog_posting.public_verification.requests.get', return_value=response):
            result = verify_public_body('https://blog.naver.com/example/123')
            self.assertIsNone(result['publicBodyMatched'])
            self.assertEqual(result['matchedParagraphs'], 0)
            self.assertEqual(result['bodyVerificationStatus'], 'unknown')

    def test_existing_daily_action_routes_to_bounded_catch_up(self):
        with patch.object(worker.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0)) as run:
            self.assertEqual(worker.run_task('naver-daily'), 0)
        self.assertEqual(run.call_args.args[0][-1], '--catch-up')

    def call(self, apply=False, response=None):
        receipt = response or dict(applied=apply, actionVerified=True)
        with patch.object(worker, 'os', SimpleNamespace(name='nt', environ=os.environ)), patch.object(worker.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, json.dumps(receipt), '')) as run:
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
        with patch.object(worker, 'os', SimpleNamespace(name='nt', environ=os.environ)), patch.object(worker.subprocess, 'run', return_value=subprocess.CompletedProcess([], 1, '', 'wrong action')), self.assertRaisesRegex(RuntimeError, 'configuration failed'):
            worker.configure_naver_recovery_schedule()

    def test_missing_or_wrong_receipt_is_not_success(self):
        for receipt in (dict(applied=False), dict(applied=True, actionVerified=True), dict(applied=False, actionVerified=1)):
            with self.subTest(receipt=receipt), self.assertRaisesRegex(RuntimeError, 'invalid configuration receipt'):
                self.call(response=receipt)


if __name__ == '__main__':
    unittest.main()
