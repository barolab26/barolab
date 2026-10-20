import json
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from naver_blog_posting import pipeline_runner as runner


class PreparedContentTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.base = Path(temp.name)
        self.folder = self.base / 'output' / 'yoon_master' / 'prepared'
        self.folder.mkdir(parents=True)
        self.options = dict(topic_seed='Which socks work with loafers?', main_keyword='loafers',
                            evidence_dir='/private/evidence', publication_date='2026-10-21')
        for target, value in [('BASE_DIR', self.base), ('RUN_OPTIONS', self.options)]:
            patcher = patch.object(runner, target, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.journal = {'attempts': []}
        patcher = patch.object(runner, 'read_journal', return_value=self.journal)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.handoff = SimpleNamespace(folder=self.folder,
            data={'requestedContentInputsSha256': runner.content_inputs_sha256()},
            file=lambda name: self.folder / name, check=lambda **kwargs: [1, 2, 3])
        patcher = patch.object(runner, 'AgentHandoff', return_value=self.handoff)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.context = dict(schema='naver-preparation-context-v1', account='yoon_master',
            publicationDate='2026-10-21', scheduledSlot='20:30', strategyOverride=None,
            topicSeed=self.options['topic_seed'], mainKeyword='loafers', evidenceDir='/private/evidence',
            runOptions=dict(self.options), strategyIndex=0, selectedStrategyId=runner.STRATEGIES[0]['id'])
        self.write('preparation-context.json', self.context)
        self.write('keyword-selector.json', {'readerQuestion': self.options['topic_seed'], 'mainKeyword': 'loafers'})
        self.write('article.json', {'title': 'New question answer'})
        self.write('image-plan.json', {'imagePlans': []})

    def write(self, name, value):
        (self.folder / name).write_text(json.dumps(value), encoding='utf-8')

    def validate(self, **kwargs):
        return runner.validate_prepared_context('yoon_master', self.folder, slot='20:30',
                                               publication_date='2026-10-21', **kwargs)

    def test_partial_requires_real_handoff_check_and_three_stages(self):
        self.validate(complete=False)
        self.handoff.check = lambda **kwargs: [1, 2]
        with self.assertRaisesRegex(RuntimeError, 'accepted researcher'):
            self.validate(complete=False)

    def test_account_containment_and_submission_evidence(self):
        with self.assertRaisesRegex(RuntimeError, 'belong'):
            runner.validate_prepared_context('soultin', self.folder, complete=False)
        self.write('reservation-evidence.json', {})
        with self.assertRaisesRegex(RuntimeError, 'submission evidence'):
            self.validate(complete=False)

    def test_uncertain_journal_cannot_reuse(self):
        for phase in ('started', 'submitting', 'unknown', 'verified'):
            self.journal['attempts'] = [{'account': 'yoon_master', 'artifactFolder': str(self.folder), 'phase': phase}]
            with self.assertRaisesRegex(RuntimeError, 'active or uncertain'):
                self.validate(complete=False)

    def test_binding_rejects_changed_date_slot_inputs_and_question(self):
        for key, value in [('publicationDate', '2026-10-22'), ('scheduledSlot', '10:00'),
                           ('topicSeed', 'Other question'), ('evidenceDir', '/other')]:
            with self.subTest(key=key):
                self.write('preparation-context.json', dict(self.context, **{key: value}))
                with self.assertRaises(RuntimeError):
                    self.validate(complete=False)
        self.write('preparation-context.json', self.context)
        self.write('keyword-selector.json', {'readerQuestion': 'Different question', 'mainKeyword': 'loafers'})
        with self.assertRaisesRegex(RuntimeError, 'reader question'):
            self.validate(complete=False)

    def test_original_inputs_and_handoff_hash_are_independent_checks(self):
        changed = dict(self.context, runOptions=dict(self.options, main_keyword='other'))
        self.write('preparation-context.json', changed)
        with self.assertRaisesRegex(RuntimeError, 'Original preparation'):
            self.validate(complete=False)
        self.write('preparation-context.json', self.context)
        self.handoff.data['requestedContentInputsSha256'] = 'changed'
        with self.assertRaisesRegex(RuntimeError, 'content inputs'):
            self.validate(complete=False)

    def test_full_loader_requires_content_checks_and_live_public_collision_check(self):
        catalog = self.base / 'catalog.json'
        catalog.write_text(json.dumps({'accounts': {'yoon_master': {'posts': []}}}))
        with patch.object(runner, 'require_content_handoff') as check, patch(
                'naver_blog_posting.account_reconciliation.collect_full_public_inventory', return_value=catalog):
            result = runner.load_prepared_content('yoon_master', self.folder, slot='20:30')
            check.assert_called_once_with(self.folder, 'yoon_master')
            self.assertEqual(result[2]['title'], 'New question answer')
            catalog.write_text(json.dumps({'accounts': {'yoon_master': {'posts': [{'title': 'NEW question answer!'}]}}}))
            with self.assertRaisesRegex(RuntimeError, 'already exists'):
                runner.load_prepared_content('yoon_master', self.folder, slot='20:30')
        with patch.object(runner, 'require_content_handoff', side_effect=RuntimeError('real review rejected')):
            with self.assertRaisesRegex(RuntimeError, 'real review rejected'):
                self.validate()

    def test_record_context_observes_actual_strategy_and_ignores_prepared_dir_in_input_hash(self):
        before = runner.content_inputs_sha256()
        self.options['prepared_dir'] = str(self.folder)
        self.assertEqual(before, runner.content_inputs_sha256())
        context = dict(self.context)
        context.pop('selectedStrategyId')
        context.pop('strategyIndex')
        self.write('preparation-context.json', context)
        runner.record_preparation_context(self.folder, 'yoon_master', runner.STRATEGIES[0], 0, None, False, '20:30')
        saved = json.loads((self.folder / 'preparation-context.json').read_text())
        self.assertEqual(saved['selectedStrategyId'], runner.STRATEGIES[0]['id'])
        self.assertEqual(saved['runOptions'], context['runOptions'])


if __name__ == '__main__':
    unittest.main()
