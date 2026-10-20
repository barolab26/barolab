import copy
import unittest
from naver_blog_posting.title_answer_contract import (
    answer_review_inputs, canonicalize_answer_audit, validate_answer_audit)


class TitleAnswerContractTests(unittest.TestCase):
    def test_review_receives_actual_question_title_and_body(self):
        article = {"title": "White or black socks?", "blocks": [{"text": "Compare contrast with the same trousers."}],
                   "readerTask": {"question": "Which socks?", "successCondition": "Choose a contrast."}}
        before = copy.deepcopy(article)
        inputs = answer_review_inputs("Which socks?", article)
        self.assertEqual(inputs["blocks"], article["blocks"])
        self.assertEqual(inputs["title"], article["title"])
        self.assertEqual(inputs["readerQuestion"], "Which socks?")
        self.assertEqual(article, before)
        self.assertTrue(validate_answer_audit({"titleMatches": True, "intentResolved": True}, inputs))
        for audit in ({}, None, {"titleMatches": True, "intentResolved": False},
                      {"titleMatches": False, "intentResolved": True}):
            with self.assertRaises(RuntimeError):
                validate_answer_audit(audit, inputs)

    def test_missing_body_is_rejected(self):
        for article in ({}, {"title": "Title", "blocks": []}, {"title": "Title", "blocks": [{"text": ""}]}):
            with self.assertRaises(RuntimeError):
                answer_review_inputs("Question", article)
        with self.assertRaises(RuntimeError):
            validate_answer_audit({"titleMatches": True, "intentResolved": True}, {})

    def test_canonicalization_preserves_failure_and_rejects_missing(self):
        audit = {"titleMatches": False, "intentResolved": False}
        self.assertEqual(canonicalize_answer_audit(audit), audit)
        with self.assertRaises(RuntimeError):
            canonicalize_answer_audit(None)
