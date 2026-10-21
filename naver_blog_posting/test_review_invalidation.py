import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from naver_blog_posting import pipeline_runner as r


class ReviewInvalidationTests(unittest.TestCase):
    def test_original_backup_and_image_hashes_required(self):
        with TemporaryDirectory() as temp:
            folder=Path(temp); backup=folder/'audit-backup';backup.mkdir();(folder/'images').mkdir();(backup/'images').mkdir()
            plans={'imagePlans':[{'filename':'one.jpg'}]}
            values={'handoff.json':'{}','image-maker.json':'{}','image-plan.json':json.dumps(plans),
                    'assembler.json':'{"issues":["no pixel evidence"]}','images/one.jpg':'original-bytes'}
            hashes={}
            for name,value in values.items():
                (folder/name).write_text(value);(backup/name).write_text(value);hashes[name]=r.sha(backup/name)
            (folder/'reused-photo-source.json').write_text(json.dumps(plans))
            audit={'reason':'stub visual review invalidated; fresh actual pixels required','backupDirectory':'audit-backup','backupHashes':hashes}
            (folder/'review-invalidation.json').write_text(json.dumps(audit))
            handoff=SimpleNamespace(folder=folder,check=lambda:[{}, {}, {}],file=lambda name:folder/name)
            r.require_review_invalidation(handoff)
            (folder/'images/one.jpg').write_text('changed')
            with self.assertRaisesRegex(RuntimeError,'image changed'):
                r.require_review_invalidation(handoff)
            (folder/'images/one.jpg').write_text('original-bytes')
            (backup/'assembler.json').write_text('{}')
            with self.assertRaisesRegex(RuntimeError,'backup changed'):
                r.require_review_invalidation(handoff)

    def test_editorial_candidate_preserves_identity_structure_and_image_anchor(self):
        import copy
        original = {'title': 'Question', 'mainKeyword': 'keyword', 'readerTask': {'kind': 'decision'},
                    'blocks': [{'kind': 'paragraph', 'text': 'image explanation'},
                               {'kind': 'source', 'text': 'old source'}]}
        candidate = copy.deepcopy(original)
        candidate['blocks'][1]['text'] = 'Corrected official source and verification date'
        plans = [{'afterBlock': 0}]
        r.validate_editorial_candidate(original, candidate, plans)
        for field in ('title', 'mainKeyword', 'readerTask', 'blocks', 'anchor'):
            changed = copy.deepcopy(candidate)
            if field == 'blocks':
                changed['blocks'].append({'kind': 'source', 'text': 'extra'})
            elif field == 'anchor':
                changed['blocks'][0]['text'] = 'changed image context'
            else:
                changed[field] = 'different'
            with self.subTest(field=field), self.assertRaises(RuntimeError):
                r.validate_editorial_candidate(original, changed, plans)

    def test_failed_editorial_review_preserves_original_handoff_and_writer(self):
        from unittest.mock import patch
        with TemporaryDirectory() as temp:
            folder = Path(temp)
            original = {'title': 'Title', 'mainKeyword': 'keyword', 'readerTask': {},
                        'blocks': [{'kind': 'paragraph', 'text': 'image context'},
                                   {'kind': 'source', 'text': 'source'}], 'draftMd': 'draft'}
            values = {'writer.json': original, 'image-plan.json': {'imagePlans': [{'afterBlock': 0}]},
                      'researcher.json': {'answerBrief': {}}, 'keyword-selector.json': {},
                      'handoff.json': {'stages': [1, 2, 3]}}
            for name, value in values.items():
                (folder/name).write_text(json.dumps(value), encoding='utf-8')
            candidate = folder/'candidate-input.json'
            candidate.write_text(json.dumps(original), encoding='utf-8')
            hashes = {name: r.sha(folder/name) for name in values}
            handoff = SimpleNamespace(folder=folder, file=lambda name:folder/name)
            with patch.object(r, 'validate_prepared_context', return_value=(handoff, {})), \
                 patch.object(r, 'require_reader_task'), patch.object(r, 'require_writer_answer_plan'), \
                 patch.object(r, 'validate_article'), patch.object(r, 'public_link_findings', return_value=[]), \
                 patch.object(r, 'review_reader_demand_alignment', side_effect=RuntimeError('independent rejection')):
                with self.assertRaisesRegex(RuntimeError, 'independent rejection'):
                    r._apply_editorial_correction('soultin', folder, candidate, slot='11:00', publication_date='2026-10-21')
            self.assertEqual(hashes, {name: r.sha(folder/name) for name in values})
            backups = list(folder.glob('editorial-backup-*'))
            self.assertEqual(len(backups), 1)
            self.assertEqual(r.sha(backups[0]/'writer.json'), hashes['writer.json'])
            self.assertFalse((folder/'editorial-correction.json').exists())

    def test_editorial_without_image_plan_resumes_after_fresh_writer_review(self):
        from unittest.mock import Mock, patch
        with TemporaryDirectory() as temp:
            folder = Path(temp)
            article = {'title': 'Title', 'mainKeyword': 'keyword', 'readerTask': {},
                       'blocks': [{'kind': 'source', 'text': 'official source'}], 'draftMd': 'draft'}
            data = {'stages': [{'agent': 'keyword-selector'}, {'agent': 'researcher'}, {'agent': 'writer'}]}
            for name, value in {'writer.json': article, 'researcher.json': {'answerBrief': {}},
                                'keyword-selector.json': {}, 'handoff.json': data}.items():
                (folder/name).write_text(json.dumps(value), encoding='utf-8')
            candidate = folder/'candidate-input.json'
            candidate.write_text(json.dumps(article), encoding='utf-8')
            handoff = SimpleNamespace(folder=folder, file=lambda name:folder/name, data=data,
                                      accept=Mock(), check=lambda:data['stages'])
            def review(selection, value, audit_path, observer):
                observer('codex', 'actual-test-model', 'returned')
                audit_path.write_text('{}', encoding='utf-8')
            with patch.object(r, 'validate_prepared_context', return_value=(handoff, {})), \
                 patch.object(r, 'AgentHandoff', return_value=handoff), \
                 patch.object(r, 'require_reader_task'), patch.object(r, 'require_writer_answer_plan'), \
                 patch.object(r, 'validate_article'), patch.object(r, 'public_link_findings', return_value=[]), \
                 patch.object(r, 'review_reader_demand_alignment', side_effect=review):
                r._apply_editorial_correction('soultin', folder, candidate, slot='11:00', publication_date='2026-10-21')
            handoff.accept.assert_called_once()
            self.assertFalse((folder/'reused-photo-source.json').exists())
            r.require_review_invalidation(handoff)
            (folder/'writer.json').write_text('{}', encoding='utf-8')
            with self.assertRaisesRegex(RuntimeError, 'corrected writer changed'):
                r.require_review_invalidation(handoff)

    def test_review_material_relocation_preserves_all_evidence_except_paths(self):
        import copy
        from unittest.mock import patch
        supplied = {'version': 1, 'account': 'soultin', 'readerQuestion': 'question',
                    'manifestSha256': 'source-digest',
                    'materials': [{'materialId': 'one', 'filePath': '/source/one.png',
                                   'sha256': 'same-image-bytes', 'observation': 'actual observation',
                                   'sourceUrl': 'https://example.go.kr/source'}]}
        stored = copy.deepcopy(supplied)
        stored['manifestSha256'] = 'run-digest'
        stored['materials'][0]['filePath'] = '/run/materials/one.png'
        handoff = SimpleNamespace(file=lambda name:Path('/run')/name,
                                  data={'materialsManifestSha256': 'run-digest'})
        with patch.object(r, 'load_material_manifest', return_value=stored):
            self.assertIs(r.reviewed_run_materials(handoff, supplied, 'soultin'), stored)
            for key in ('sha256', 'observation', 'sourceUrl', 'materialId'):
                changed = copy.deepcopy(supplied)
                changed['materials'][0][key] = 'changed'
                with self.subTest(key=key), self.assertRaisesRegex(RuntimeError, 'material evidence differs'):
                    r.reviewed_run_materials(handoff, changed, 'soultin')
            changed = {**supplied, 'readerQuestion': 'different question'}
            with self.assertRaises(RuntimeError):
                r.reviewed_run_materials(handoff, changed, 'soultin')
            handoff.data['materialsManifestSha256'] = 'wrong'
            with self.assertRaisesRegex(RuntimeError, 'digest changed'):
                r.reviewed_run_materials(handoff, supplied, 'soultin')

    def test_image_purpose_only_correction_rejects_caption_placement_or_identity_change(self):
        import copy
        before = [{'purpose': 'Too broad', 'caption': 'Visible conditions', 'afterBlock': 1,
                   'filename': 'official.png', 'sha256': 'unchanged'}]
        after = copy.deepcopy(before)
        after[0]['purpose'] = 'Check the two visible eligibility conditions'
        r.validate_visual_plan_correction(before, after)
        for key, value in [('caption', 'different'), ('afterBlock', 2), ('sha256', 'different'),
                           ('filename', 'different.png'), ('purpose', '')]:
            bad = copy.deepcopy(after)
            bad[0][key] = value
            with self.subTest(key=key), self.assertRaises(RuntimeError):
                r.validate_visual_plan_correction(before, bad)
        with self.assertRaises(RuntimeError):
            r.validate_visual_plan_correction(before, before)

    def test_visual_placement_is_bounded_auditable_and_preserves_caption_and_bytes(self):
        import copy
        before = [{'purpose': 'Check conditions', 'caption': 'Actual guidance', 'afterBlock': 2,
                   'filename': 'official.png', 'sha256': 'unchanged'}]
        after = copy.deepcopy(before)
        after[0]['afterBlock'] = 3
        self.assertEqual(r.validate_visual_plan_correction(before, after, 6),
                         [{'index': 0, 'field': 'afterBlock', 'before': 2, 'after': 3}])
        for key, value in [('caption', 'different'), ('filename', 'other.png'), ('sha256', 'changed'),
                           ('afterBlock', -1), ('afterBlock', 6), ('afterBlock', True)]:
            bad = copy.deepcopy(after)
            bad[0][key] = value
            with self.subTest(key=key, value=value), self.assertRaises(RuntimeError):
                r.validate_visual_plan_correction(before, bad, 6)
        with self.assertRaisesRegex(RuntimeError, 'overlap'):
            r.validate_visual_plan_correction(before + [{**before[0], 'filename': 'two.png', 'afterBlock': 4}],
                                             after + [{**before[0], 'filename': 'two.png', 'afterBlock': 3}], 6)

    def test_uninvalidated_stage_sequence_rejected(self):
        with self.assertRaises(RuntimeError):
            r.require_review_invalidation(SimpleNamespace(check=lambda:[{}, {}, {}, {}]))
