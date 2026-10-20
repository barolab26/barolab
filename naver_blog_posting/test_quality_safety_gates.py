"""Failed review evidence must never be promoted to approval."""
import copy
from pathlib import Path
import unittest
from unittest.mock import patch
from naver_blog_posting import pipeline_runner as r


class QualitySafetyTests(unittest.TestCase):
    def test_content_required_checks_fail_closed_without_mutation(self):
        valid = {'passed': True, 'issues': [], 'checks': dict.fromkeys(r.REQUIRED_PUBLICATION_CHECKS, True)}
        r.require_content_review(valid)
        for key in r.REQUIRED_PUBLICATION_CHECKS:
            bad = copy.deepcopy(valid)
            bad['checks'][key] = False
            before = copy.deepcopy(bad)
            with self.assertRaises(RuntimeError):
                r.require_content_review(bad)
            self.assertEqual(bad, before)
        for bad in ({}, {**valid, 'passed': False}, {**valid, 'issues': ['broken']}, {**valid, 'checks': {}}):
            with self.assertRaises(RuntimeError):
                r.require_content_review(bad)

    def test_demand_rejects_adjacent_and_changed_inputs(self):
        inputs = {'readerQuestion': 'question'}
        verdict = {'relation': 'direct_subtask', 'issues': [], 'readerGoal': {},
                   **dict.fromkeys(('matchesQuestion', 'matchesTitle', 'titleClear', 'titleNatural'), True)}
        with patch.object(r, 'reader_demand_alignment_inputs', return_value=inputs), patch.object(r, 'validate_reader_goal'):
            self.assertTrue(r.validate_reader_demand_alignment({'inputs': inputs, 'verdict': verdict}, {}))
            for receipt in ({'inputs': inputs, 'verdict': {**verdict, 'relation': 'adjacent_topic'}},
                            {'inputs': {}, 'verdict': verdict}, {'inputs': inputs, 'verdict': {}}):
                with self.assertRaises(RuntimeError):
                    r.validate_reader_demand_alignment(receipt, {})

    def test_bridge_rejects_failed_expired_or_incomplete_review(self):
        source = {'canonicalUrl': 'https://example.org/article', 'text': 'A supported procedure for the reader.'}
        verdict = dict(passed=True, topicRelevant=True, addsReaderValue=True, temporalCoherent=True,
                       issues=[], temporalStatus='evergreen', hasExplicitCutoff=False, validThrough='',
                       applicableYear=0, hasPeriodSpecificClaims=False, officialEvidenceId='', temporalEvidenceId='',
                       topicEvidenceId=r.bridge_article_fragments(source)[0]['id'])
        self.assertTrue(r.validate_bridge_eligibility(verdict, source, '2026-10-21'))
        for change in ({'passed': False}, {'issues': ['unsupported']}, {'temporalStatus': 'expired'},
                       {'topicEvidenceId': ''}, {'temporalCoherent': None}, {'hasPeriodSpecificClaims': True},
                       {'temporalStatus': 'active', 'hasExplicitCutoff': True, 'validThrough': '2026-10-21',
                        'temporalEvidenceId': verdict['topicEvidenceId']}):
            bad = {**verdict, **change}
            before = copy.deepcopy(bad)
            with self.assertRaises(RuntimeError):
                r.validate_bridge_eligibility(bad, source, '2026-10-21')
            self.assertEqual(bad, before)

    def test_native_failure_does_not_write_pass_receipt(self):
        good = dict(passed=True, issues=[], notes=[], pcWholeDocumentVisualReview=True,
                    mobileWholeDocumentVisualReview=True, categoryMatches=True)
        for key in ('passed', 'pcWholeDocumentVisualReview', 'mobileWholeDocumentVisualReview', 'categoryMatches'):
            verdict = {**good, key: False}
            receipt = {'screenshots': [], 'captureCoverage': {}}
            with patch.object(r, 'load_soul_policy', return_value={'text': '', 'sha256': 'test'}), \
                 patch.object(r, 'article_visual_profile', return_value={}), \
                 patch.object(r, 'read_agent_instruction', return_value=''), \
                 patch.object(r, 'generate_content_json', return_value=verdict), \
                 patch.object(r, 'atomic_json') as write:
                with self.assertRaises(RuntimeError):
                    r.review_native_layout(None, None, Path('unused'), 'soul5373', {}, None, receipt, {'category': 'Expected'})
                self.assertNotIn('reviewStatus', receipt)
                self.assertEqual(write.call_count, 1)  # Preserve raw rejected evidence only.
                self.assertEqual(write.call_args.args[0].name, 'native-visual-review.json')
                self.assertFalse(verdict[key])

    def test_native_unspecified_category_keeps_valid_review(self):
        result = dict(passed=True, issues=[], notes=['No category specified'],
                      pcWholeDocumentVisualReview=True, mobileWholeDocumentVisualReview=True,
                      categoryMatches=False)
        receipt = {'screenshots': [], 'captureCoverage': {}}
        with patch.object(r, 'load_soul_policy', return_value={'text': '', 'sha256': 'test'}), \
             patch.object(r, 'article_visual_profile', return_value={}), \
             patch.object(r, 'read_agent_instruction', return_value=''), \
             patch.object(r, 'generate_content_json', return_value=result), \
             patch.object(r, 'atomic_json'):
            reviewed = r.review_native_layout(None, None, Path('unused'), 'soul5373', {}, None, receipt, {})
            self.assertEqual(reviewed['reviewStatus'], 'passed')
            self.assertFalse(result['categoryMatches'])

    def test_surgical_repair_cannot_manufacture_review(self):
        with patch.object(r, 'atomic_json') as write:
            self.assertFalse(r._surgical_repair_naver(Path('unused'), {'passed': False}))
            write.assert_not_called()


if __name__ == '__main__':
    unittest.main()
