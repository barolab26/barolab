"""Observed competitor evidence must survive the planning-to-writer boundary."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from agents import style_strategy as strategy


class SearchContentStrategyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)

    def article(self, text='observed body ' * 30):
        return {'url': 'https://example.com/article', 'bodyText': text,
                'bodySha256': hashlib.sha256(text.encode()).hexdigest()}

    def test_hash_only_and_changed_bodies_are_not_comparison_evidence(self):
        article = self.article(); article['bodyText'] += 'changed'
        with patch.object(strategy, 'benchmark', return_value={'articles': [article, {'bodySha256': 'x'}]}):
            plan = strategy.attach_search_benchmark({'keyword': 'query'}, self.folder)
        self.assertEqual(plan['searchStrategy']['status'], 'benchmark_unavailable')
        self.assertFalse(plan['searchStrategy']['rankingGuaranteed'])

    def test_writer_receives_only_hash_bound_observed_text_and_marks_truncation(self):
        valid = self.article('body ' * 3000)
        valid.update(readScope='observed DOM and screenshots',visualObservations=['Answer first; comparison table then steps'])
        invalid = self.article(); invalid['bodySha256'] = 'changed'
        (self.folder/'planning.json').write_text(json.dumps({'benchmark': {'articles': [valid, invalid]}}), encoding='utf-8')
        context = strategy.search_writing_context(self.folder)
        self.assertEqual(len(context['observedCompetitors']), 1)
        self.assertEqual(len(context['observedCompetitors'][0]['bodyText']), 12000)
        self.assertTrue(context['observedCompetitors'][0]['excerptTruncated'])
        self.assertEqual(context['observedCompetitors'][0]['visualObservations'],valid['visualObservations'])
        self.assertEqual(context['observedCompetitors'][0]['readScope'],valid['readScope'])
        self.assertIn('structural starting point',context['policy'])

    def test_channel_uses_matching_search_surface(self):
        with patch('common.ego_executor.benchmark_blog_screen', return_value={'articles': []}) as observe:
            strategy.benchmark('query', self.folder, channel='cf')
            self.assertEqual(observe.call_args.kwargs['surface'], 'google_web')
            strategy.benchmark('query', self.folder, channel='naver')
            self.assertEqual(observe.call_args.kwargs['surface'], 'naver_blog')

    def test_user_takeover_is_not_hidden_as_missing_research(self):
        with patch('common.ego_executor.benchmark_blog_screen', side_effect=RuntimeError('user_takeover')):
            with self.assertRaisesRegex(RuntimeError, 'user_takeover'):
                strategy.benchmark('query', self.folder)

    def test_cached_decision_survives_only_identical_observed_content(self):
        article = self.article()
        observed = {'articles': [article]}
        with patch.object(strategy, 'benchmark', return_value=observed):
            plan = strategy.attach_search_benchmark({'keyword': 'query'}, self.folder)
            plan['searchStrategy']['decision'] = {'readerTask': 'checked task'}
            plan = strategy.attach_search_benchmark(plan, self.folder)
        self.assertEqual(plan['searchStrategy']['decision']['readerTask'], 'checked task')
        with patch.object(strategy, 'benchmark', return_value={'articles': [self.article('different ' * 40)]}):
            plan = strategy.attach_search_benchmark(plan, self.folder)
        self.assertNotIn('decision', plan['searchStrategy'])


if __name__ == '__main__':
    unittest.main()
