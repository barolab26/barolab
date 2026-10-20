import inspect
import unittest
from naver_blog_posting import pipeline_runner as runner

class SubmissionResponseTests(unittest.TestCase):
    def test_explicit_failure_stops_before_independent_success(self):
        for status, reply in ((500, {}), (403, {"isSuccess": True}), (200, {"isSuccess": False})):
            with self.subTest(status=status, reply=reply):
                with self.assertRaisesRegex(RuntimeError, "unknown"):
                    runner.require_no_explicit_submission_failure(reply, status)

    def test_success_or_ambiguous_response_still_requires_independent_verification(self):
        for reply in ({"isSuccess": True}, {"format": "non_json"}, {}):
            self.assertIsNone(runner.require_no_explicit_submission_failure(reply, 200))
        source = inspect.getsource(runner._run_pipeline)
        click = source.index("frame.locator('button[class*=\"confirm_btn\"]').click")
        guard = source.index("require_no_explicit_submission_failure(reply, response.status)")
        verify = source.index("verification = verify_reservation(")
        success = source.index("write_attempt(account_key, 'verified'")
        self.assertLess(click, guard)
        self.assertLess(guard, verify)
        self.assertLess(verify, success)
        self.assertEqual(source.count("frame.locator('button[class*=\"confirm_btn\"]').click"), 1)

if __name__ == "__main__":
    unittest.main()
