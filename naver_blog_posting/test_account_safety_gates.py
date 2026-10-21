"""Explicit account selection must retain duplicate and recovery safeguards."""
from contextlib import ExitStack, nullcontext
from datetime import datetime
import unittest
from unittest.mock import patch

from naver_blog_posting import pipeline_runner as runner


class AccountSafetyGateTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.options = {}
        self.stack.enter_context(patch.object(runner, "RUN_OPTIONS", self.options))
        moment = datetime(2026, 10, 21, 0, 0, tzinfo=runner.KST)
        self.stack.enter_context(patch.object(runner, "now_kst", return_value=moment))
        self.stack.enter_context(patch.object(runner, "pipeline_lock", return_value=nullcontext()))
        self.stack.enter_context(patch.object(runner, "read_journal", return_value={"attempts": []}))
        self.stack.enter_context(patch.object(runner, "recovery_context_for_slot", return_value={"sha256": "test"}))
        for name in ("attempt_context_changed", "material_context_ready", "question_context_ready"):
            self.stack.enter_context(patch.object(runner, name, return_value=False))
        self.write = self.stack.enter_context(patch.object(runner, "write_attempt"))
        self.stack.enter_context(patch.object(runner, "monitor"))
        self.execute = self.stack.enter_context(patch.object(runner, "_run_pipeline"))

    def run_gate(self, gate):
        with patch.object(runner, "account_gate", side_effect=[gate, "verified"]):
            runner.run_accounts(["soul5373"], slot="20:00", publication_date="2026-10-21")

    def test_unknown_single_account_cannot_execute(self):
        with self.assertRaisesRegex(RuntimeError, "unknown"):
            self.run_gate("unknown")
        self.execute.assert_not_called()
        self.write.assert_not_called()

    def test_verified_single_account_keeps_existing_reservation(self):
        self.run_gate("verified")
        self.execute.assert_not_called()
        self.write.assert_not_called()

    def test_eligible_single_account_can_execute(self):
        self.run_gate("eligible")
        self.execute.assert_called_once_with("soul5373", True, None, slot="20:00", publication_date="2026-10-21")
        self.write.assert_called_once()

    def test_direct_entry_binds_stable_local_worker_before_pipeline(self):
        self.run_gate('eligible')
        worker = self.options['worker_id']
        self.assertTrue(worker.startswith('local-'))
        self.assertEqual(self.write.call_args.kwargs['workerId'], worker)
        self.assertIs(self.write.call_args.kwargs['submissionStarted'], False)
        self.run_gate('eligible')
        self.assertEqual(self.options['worker_id'], worker)

    def test_scheduled_worker_identity_is_preserved(self):
        self.options['worker_id'] = 'scheduled-exact-worker'
        self.run_gate('eligible')
        self.assertEqual(self.write.call_args.kwargs['workerId'], 'scheduled-exact-worker')

    def test_retry_wait_without_new_evidence_cannot_execute(self):
        with self.assertRaisesRegex(RuntimeError, "retry_wait"):
            self.run_gate("retry_wait")
        self.execute.assert_not_called()

    def test_validated_manual_recovery_still_allows_retry(self):
        self.options.update(worker_mode="manual", manual_recovery_reason="fixed", manual_recovery_fix=["fix.py"])
        with patch.object(runner, "manual_recovery_metadata", return_value={"reason": "validated"}) as validate:
            self.run_gate("retry_wait")
        validate.assert_called_once_with("fixed", ["fix.py"])
        self.execute.assert_called_once()

    def test_missing_materials_cannot_execute(self):
        with self.assertRaises(runner.MaterialRequired):
            self.run_gate("material_required")
        self.execute.assert_not_called()

    def test_verified_revision_preserves_explicit_target_contract(self):
        self.options["revision_target"] = {
            "account": "soul5373", "reserveTime": "2026-10-21 20:00", "logNo": "123456789",
        }
        self.run_gate("verified")
        self.execute.assert_called_once()


if __name__ == "__main__":
    unittest.main()
