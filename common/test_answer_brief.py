import copy
import unittest
from unittest.mock import Mock, patch

from common.answer_brief import (
    AnswerBriefBlocked, BRIEF_CHECKS, bind_brief_review_draft,
    review_with_one_refinement, validate_brief_review,
)


class BriefReviewEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.goal = {'question': 'Original question', 'successCondition': 'A supported answer',
                     'requiredAnswers': ['Explain the supported action']}
        self.brief = {'sections': [{'id': 'answer'}]}

    def verdict(self, passed=True):
        return {'passed': passed, 'checks': {key: True for key in BRIEF_CHECKS},
                'coverage': [{'goalIndex': 0, 'answered': True, 'sectionIds': ['answer'],
                              'reason': 'The supplied source supports the action'}],
                'issues': [], 'missingInputs': []}

    def test_failed_review_and_missing_evidence_are_preserved(self):
        raw = self.verdict(False)
        raw['checks']['directAnswerComplete'] = False
        raw['coverage'][0]['answered'] = False
        raw['issues'] = ['The core action has no supporting evidence']
        raw['missingInputs'] = [{'kind': 'source_fact', 'reason': 'Need the actual source'}]
        expected_missing = copy.deepcopy(raw['missingInputs'])
        bound = bind_brief_review_draft(raw, self.goal, self.brief)
        before = copy.deepcopy(bound)
        with self.assertRaises(AnswerBriefBlocked) as raised:
            validate_brief_review(bound, self.brief, self.goal)
        self.assertEqual(raised.exception.missing_inputs, expected_missing)
        self.assertEqual(bound, before)
        self.assertFalse(raw['passed'])
        self.assertEqual(raw['missingInputs'], expected_missing)

    def test_claimed_pass_cannot_override_failed_checks_or_coverage(self):
        for field in ('checks', 'coverage'):
            with self.subTest(field=field):
                verdict = self.verdict()
                if field == 'checks':
                    verdict['checks']['directAnswerComplete'] = False
                else:
                    verdict['coverage'][0]['answered'] = False
                with self.assertRaises(AnswerBriefBlocked):
                    validate_brief_review(verdict, self.brief, self.goal)

    def test_complete_new_review_passes_without_mutation(self):
        verdict = self.verdict()
        before = copy.deepcopy(verdict)
        self.assertTrue(validate_brief_review(verdict, self.brief, self.goal))
        self.assertEqual(verdict, before)

    @patch('common.answer_brief.validate_answer_brief', return_value=True)
    def test_missing_input_stops_before_refinement_or_approval(self, _validate):
        failed = self.verdict(False)
        failed['missingInputs'] = [{'kind': 'source_fact', 'reason': 'Actual evidence absent'}]
        refine, record = Mock(), Mock()
        with self.assertRaises(AnswerBriefBlocked):
            review_with_one_refinement(self.brief, self.goal, [], [], [],
                                      Mock(return_value=failed), refine, record)
        refine.assert_not_called()
        self.assertEqual(record.call_args.args[0]['status'], 'blocked')

    @patch('common.answer_brief.validate_answer_brief', return_value=True)
    def test_one_refinement_can_pass_a_new_complete_review(self, _validate):
        failed = self.verdict(False)
        failed['issues'] = ['Explain the supplied evidence more clearly']
        complete = self.verdict()
        refine, record = Mock(return_value=self.brief), Mock()
        _, result = review_with_one_refinement(self.brief, self.goal, [], [], [],
                                              Mock(side_effect=[failed, complete]), refine, record)
        refine.assert_called_once()
        self.assertEqual(result, complete)
        self.assertEqual(record.call_args.args[0]['status'], 'approved')
        self.assertFalse(failed['passed'])


if __name__ == '__main__':
    unittest.main()
