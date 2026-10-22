import copy
import json
import unittest
from unittest.mock import Mock, patch

from common import jev


def score(value=2.0):
    return {'type': 'score', 'score': value, 'confidence': 1.0,
            'probabilities': {'0': 0.0, '1': 2.0 - value, '2': value - 1.0}}


def response(answers):
    result = Mock(status_code=200)
    result.__enter__ = Mock(return_value=result)
    result.__exit__ = Mock(return_value=False)
    result.iter_content.return_value = [json.dumps({
        'model': jev.DEFAULT_MODEL, 'answers': answers,
        'usage': {'input_tokens': 100, 'output_tokens': 10}}).encode()]
    return result


class JevTest(unittest.TestCase):
    def setUp(self):
        self.config = patch.object(jev, '_config', return_value=('private-test-key', jev.DEFAULT_MODEL))
        self.config.start()
        self.addCleanup(self.config.stop)
        self.candidates = [{'id': 'one', 'title': '박물관 관람 안내', 'issue': 'low_ctr',
                            'evidence': {'impressions': 200, 'clicks': 1}}]

    def test_selection_ranks_without_inventing_observations(self):
        candidates = self.candidates + [{'id': 'two', 'title': '교통 안내',
                                        'evidence': {'impressions': 30, 'clicks': 2}}]
        before = copy.deepcopy(candidates)
        answers = {'relevance_0': score(1), 'evidence_0': score(1),
                   'relevance_1': score(), 'evidence_1': score()}
        with patch.object(jev.requests, 'post', return_value=response(answers)) as post:
            result = jev.choose_candidates(candidates)
        self.assertEqual('ok', result['status'])
        self.assertEqual(['two', 'one'], [r['candidateId'] for r in result['ranking']])
        self.assertEqual(1, result['ranking'][0]['score'])
        self.assertEqual(before, candidates)
        self.assertEqual(100, result['usage']['input_tokens'])
        self.assertAlmostEqual(0.0000042, result['estimatedCostUsd'])
        self.assertIsNone(result['billedCostUsd'])
        self.assertEqual(jev.ENDPOINT, post.call_args.args[0])
        self.assertFalse(post.call_args.kwargs['allow_redirects'])
        self.assertEqual((5, 45), post.call_args.kwargs['timeout'])

    def test_missing_key_fails_closed_without_request(self):
        with patch.object(jev, '_config', return_value=('', jev.DEFAULT_MODEL)), \
                patch.object(jev.requests, 'post') as post:
            result = jev.review_revision('원문', '수정문', '출처')
        self.assertEqual('not_configured', result['status'])
        self.assertEqual('review', result['decision'])
        post.assert_not_called()

    def test_duplicate_or_oversized_candidates_not_sent(self):
        with patch.object(jev.requests, 'post') as post:
            for candidates in (self.candidates * 2, self.candidates * 11,
                               [dict(self.candidates[0], content='가' * 12001)]):
                self.assertEqual('invalid_input', jev.choose_candidates(candidates)['status'])
        post.assert_not_called()

    def test_invalid_answers_and_nan_cannot_become_success(self):
        invalid = [
            {'relevance_0': score(), 'evidence_0': {'type': 'noul', 'noul': 1}},
            {'relevance_0': dict(score(), score=float('nan')), 'evidence_0': score()},
            {'relevance_0': dict(score(), score=20), 'evidence_0': score()},
            {'relevance_0': dict(score(), score=True), 'evidence_0': score()},
            {'relevance_0': dict(score(), probabilities={'0': 0, '1': 0, '2': 0}), 'evidence_0': score()},
            {'relevance_0': dict(score(), score=0), 'evidence_0': score()},
            {'relevance_0': score()},
        ]
        for answers in invalid:
            with self.subTest(answers=answers), patch.object(jev.requests, 'post', return_value=response(answers)):
                result = jev.choose_candidates(self.candidates)
                self.assertEqual('invalid_response', result['status'])
                self.assertEqual([], result['ranking'])
                self.assertEqual(100, result['usage']['input_tokens'])

    def test_review_pass_review_reject_and_metadata_filtered(self):
        for grounded, expected in ((0.99, 'pass'), (0.7, 'review'), (0.1, 'reject')):
            answers = {'groundedChanges': {'type': 'noul', 'noul': grounded},
                       'preservesIntent': {'type': 'noul', 'noul': 0.99}, 'usefulness': score()}
            with self.subTest(grounded=grounded), \
                    patch.object(jev.requests, 'post', return_value=response(answers)) as post:
                result = jev.review_revision({'content': '원문', 'api_key': 'excluded'},
                                             {'content': '수정문'}, {'source': '출처'})
            self.assertEqual(expected, result['decision'])
            self.assertNotIn('api_key', post.call_args.kwargs['json']['state']['original'])

    def test_errors_never_disclose_key_or_retry(self):
        with patch.object(jev.requests, 'post',
                          side_effect=jev.requests.ConnectionError('Authorization: private-test-key')) as post:
            result = jev.choose_candidates(self.candidates)
        self.assertEqual('api_error', result['status'])
        self.assertNotIn('private-test-key', json.dumps(result))
        self.assertEqual(1, post.call_count)

    def test_redirect_or_large_response_fails_closed(self):
        for reply in (Mock(status_code=302), Mock(status_code=200)):
            reply.__enter__ = Mock(return_value=reply)
            reply.__exit__ = Mock(return_value=False)
            reply.iter_content.return_value = [b'x' * (jev.MAX_RESPONSE_BYTES + 1)]
            with patch.object(jev.requests, 'post', return_value=reply):
                result = jev.choose_candidates(self.candidates)
            self.assertNotEqual('ok', result['status'])
            self.assertEqual([], result['ranking'])

    def test_model_and_usage_validation(self):
        for change in ({'model': 'unexpected-model'}, {'usage': {'input_tokens': -1, 'output_tokens': 2}},
                       {'usage': {'input_tokens': True, 'output_tokens': 2}}):
            data = {'model': jev.DEFAULT_MODEL, 'answers': {'relevance_0': score(), 'evidence_0': score()},
                    'usage': {'input_tokens': 100, 'output_tokens': 10}}
            data.update(change)
            reply = response({})
            reply.iter_content.return_value = [json.dumps(data).encode()]
            with patch.object(jev.requests, 'post', return_value=reply):
                self.assertEqual('invalid_response', jev.choose_candidates(self.candidates)['status'])


if __name__ == '__main__':
    unittest.main()
