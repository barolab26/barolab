import asyncio
import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from PIL import Image
from naver_blog_posting import material_assets as m


class CaptureMaterialTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.folder = self.root / 'soultin' / 'intake'
        self.folder.mkdir(parents=True)
        self.image = self.folder / 'official.png'
        Image.new('RGB', (12, 12), 'white').save(self.image)
        self.packet = {'version': 1, 'account': 'soultin', 'readerQuestion': 'Which form?',
            'materials': [{'materialId': 'official', 'source': 'capture', 'filename': 'official.png',
                'filePath': str(self.image.resolve()), 'sha256': hashlib.sha256(self.image.read_bytes()).hexdigest(),
                'sourceUrl': 'https://www.easylaw.go.kr/CSP/example', 'capturedAt': '2026-01-01T00:00:00+09:00',
                'observation': 'Public form instructions', 'sensitiveDataAbsent': True, 'stepId': 'application'}]}

    def load(self, packet=None, account='soultin'):
        manifest = self.folder / 'manifest.json'
        manifest.write_text(json.dumps(packet or self.packet))
        return m.load_material_manifest(manifest, account, [self.root])

    def test_supplied_capture_count_overrides_generic_three_image_contract_only(self):
        from naver_blog_posting import pipeline_runner as r
        schema = r.agent_output_schema('image-maker', [])
        original = copy.deepcopy(schema)
        prompt = r.ROLE_SCHEMAS['image-maker']
        actual, bound = r.supplied_capture_image_contract(prompt, schema,
            {'materials': [{'materialId': 'documents', 'source': 'capture'},
                           {'materialId': 'eligibility', 'source': 'capture'}]}, ['documents','eligibility'])
        plans = bound['properties']['imagePlans']
        self.assertEqual((plans['minItems'], plans['maxItems']), (2, 2))
        self.assertEqual(plans['items']['properties']['materialId']['enum'], ['documents', 'eligibility'])
        self.assertEqual(plans['items']['properties']['source']['enum'], ['capture'])
        self.assertNotIn('at least 3', actual)
        self.assertIn('at most once', actual)
        self.assertEqual(schema, original)
        normal_prompt, normal_schema = r.supplied_capture_image_contract(prompt, schema, None)
        self.assertEqual(normal_prompt, prompt)
        self.assertEqual((normal_schema['properties']['imagePlans']['minItems'],
                          normal_schema['properties']['imagePlans']['maxItems']), (0, 12))

    def test_two_capture_model_output_stays_two_through_host_padding_and_validation(self):
        from naver_blog_posting import pipeline_runner as r
        packet = copy.deepcopy(self.packet)
        second = self.folder/'eligibility.png'
        Image.new('RGB', (12, 12), 'black').save(second)
        row = {**packet['materials'][0], 'materialId': 'eligibility', 'filename': 'eligibility.png',
               'filePath': str(second.resolve()), 'sha256': hashlib.sha256(second.read_bytes()).hexdigest(),
               'stepId': 'eligibility'}
        packet['materials'].append(row)
        packet = self.load(packet)
        run = self.root/'soultin'/'run'
        packet = m.import_materials(packet, run)
        # Model returned two truthful captures at distinct content-relevant positions.
        plans = [{**{key: row[key] for key in ('materialId', 'filename', 'source', 'stepId')},
                  'afterBlock': index * 2, 'caption': 'Official guidance', 'prompt': ''}
                 for index, row in enumerate(packet['materials'])]
        original = copy.deepcopy(plans)
        blocks = [{'kind': 'paragraph', 'text': 'reader explanation'} for _ in range(6)]
        plans = r.pad_generated_image_plans(plans, packet, blocks, 'keyword', 'title')
        r.validate_image_plans(plans, blocks)
        m.bind_material_plans(plans, packet, run)
        self.assertEqual(plans, original)
        self.assertEqual(len(plans), 2)
        self.assertEqual(len(list((run/'images').iterdir())), 2)
        generated = r.pad_generated_image_plans([], None, blocks, 'keyword', 'title')
        self.assertEqual(generated, [])
        self.assertTrue(all(plan['source'] == 'generated' for plan in generated))

    def test_assembly_receives_hash_checked_pixels_and_kst_dates_without_claiming_direct_view(self):
        from naver_blog_posting import pipeline_runner as r
        packet = self.load()
        run = self.root/'soultin'/'assembly'
        packet = m.import_materials(packet, run)
        row = packet['materials'][0]
        plan = {**{key: row[key] for key in ('materialId', 'filename', 'source', 'stepId')},
                'caption': 'Official guidance', 'afterBlock': 0, 'purpose': 'Check conditions'}
        m.bind_material_plans([plan], packet, run)
        records = m.review_visual_groups([plan], [run/'images'/plan['filename']],
            lambda *args: {'passed': True, 'issues': [], 'observation': 'Two requirements visible'},
            {}, run/'review', 'assembly')
        (run/'photo-review.json').write_text(json.dumps({'groups': records}), encoding='utf-8')
        result = r.assembly_review_evidence(run, [plan], [
            {'url': 'https://example.go.kr', 'collectedAt': '2026-10-21T00:13:00Z', 'text': 'Official exception', 'bodySha256': hashlib.sha256(b'Official exception').hexdigest()},
            {'url': 'https://example.go.kr/unknown', 'collectedAt': '2026-10-21T00:13:00', 'text': 'Official guidance', 'bodySha256': hashlib.sha256(b'Official guidance').hexdigest()}])
        self.assertEqual(result['sourceCollectionTimes'][0]['collectedDateKst'], '2026-10-21')
        self.assertEqual(result['sourceCollectionTimes'][0]['collectedAtKst'], '2026-10-21T09:13:00+09:00')
        self.assertEqual(result['sourceCollectionTimes'][1]['localDateStatus'], 'unknown')
        self.assertIn('must not claim direct pixel inspection', result['assemblyEvidenceScope'])
        self.assertEqual(result['validatedImageObservations'], records)
        self.assertEqual(result['officialSourceEvidence'][0]['excerpt'], 'Official exception')
        self.assertEqual(result['officialSourceEvidence'][0]['sourceBodySha256'], hashlib.sha256(b'Official exception').hexdigest())
        self.assertEqual(result['officialSourceEvidence'][0]['excerptSha256'], hashlib.sha256(b'Official exception').hexdigest())
        self.assertIn('notes', r.agent_output_schema('assembler')['properties'])
        with self.assertRaisesRegex(RuntimeError, 'digest mismatch'):
            r.assembly_review_evidence(run, [plan], [{'url': 'https://example.go.kr', 'text': 'changed', 'bodySha256': 'wrong'}])
        changed = {**plan, 'afterBlock': 1}
        with self.assertRaises(ValueError):
            r.assembly_review_evidence(run, [changed], [])
        Image.new('RGB', (12, 12), 'red').save(run/'images'/plan['filename'])
        with self.assertRaises(ValueError):
            r.assembly_review_evidence(run, [plan], [])

    def test_import_review_bind_and_reload_exact_bytes(self):
        packet = self.load()
        run = self.root / 'soultin' / 'run'
        packet = m.import_materials(packet, run)
        row = packet['materials'][0]
        records = m.review_visual_groups([row], [row['filePath']],
            lambda *args: {'passed': True, 'issues': [], 'observation': 'Public form instructions visible'},
            {}, run / 'review', 'intake', plan_focus=True)
        approved = asyncio.run(m.annotate_observed_materials(packet, records))
        self.assertEqual(approved, packet)
        plan = {k: row[k] for k in ('materialId', 'filename', 'source', 'stepId')}
        m.bind_material_plans([plan], approved, run)
        self.assertEqual((run / 'images' / 'official.png').read_bytes(), self.image.read_bytes())
        self.assertEqual(m.load_material_manifest(run / 'materials-manifest.json', 'soultin', [self.root]), packet)
        self.assertNotIn('filePath', m.material_context(packet)['materials'][0])
        with self.assertRaises(ValueError):
            asyncio.run(m.annotate_observed_materials(packet, []))

    def test_account_traversal_hash_url_privacy_and_future_rejected(self):
        for field, value in [('filename', '../outside.png'), ('sha256', '0' * 64),
                             ('sourceUrl', 'https://www.easylaw.go.kr.evil.test/path'),
                             ('sourceUrl', 'https://www.easylaw.go.kr/?access_token=secret'),
                             ('sensitiveDataAbsent', False), ('capturedAt', '2999-01-01T00:00:00Z'),
                             ('source', 'original')]:
            with self.subTest(field=field, value=value):
                packet = copy.deepcopy(self.packet); packet['materials'][0][field] = value
                with self.assertRaises(m.MaterialRequired): self.load(packet)
        with self.assertRaises(m.MaterialRequired): self.load(account='other')
        outside = self.root / 'other' / 'file.png'; outside.parent.mkdir(); outside.write_bytes(self.image.read_bytes())
        packet = copy.deepcopy(self.packet); packet['materials'][0]['filePath'] = str(outside)
        with self.assertRaises(m.MaterialRequired): self.load(packet)

    def test_copy_change_and_unbound_capture_fail_closed(self):
        packet = self.load()
        Image.new('RGB', (12, 12), 'black').save(self.image)
        with self.assertRaises(m.MaterialRequired): m.import_materials(packet, self.root / 'soultin' / 'run')
        with self.assertRaises(m.MaterialRequired): m.bind_material_plans([{'source': 'capture'}])
        self.assertEqual(m.bind_material_plans([{'source': 'generated'}]), [{'source': 'generated'}])

    def test_other_encoding_disguised_as_png_is_rejected(self):
        Image.new('RGB', (12, 12), 'white').save(self.image, format='BMP')
        self.packet['materials'][0]['sha256'] = hashlib.sha256(self.image.read_bytes()).hexdigest()
        with self.assertRaises(m.MaterialRequired): self.load()

    def test_capture_never_receives_generation_prompt(self):
        self.assertEqual(m.visual_prompt({'source': 'capture', 'materialId': 'official', 'prompt': 'Photorealistic'}, 'generated'), '')
        self.assertEqual(m.visual_prompt({'source': 'generated', 'prompt': 'Existing subject'}, 'default'), 'Existing subject')
        self.assertEqual(m.visual_prompt({'source': 'generated'}, 'default'), 'default')

    def test_each_image_review_has_its_own_plan_and_cross_image_assignment(self):
        prompts = []
        plans = [{'source': 'capture', 'caption': 'Application documents'}, {'source': 'capture', 'caption': 'Eligibility table'}]
        def judge(request, paths, schema):
            prompts.append(request)
            self.assertEqual(len(paths), 1)
            return {'passed': True, 'issues': [], 'observation': 'Visible instructions'}
        m.review_visual_groups(plans, [self.image, self.image], judge, {'writer': 'Both sections'}, self.folder / 'reviews', 'scope')
        self.assertIn('THIS image', prompts[0])
        self.assertIn('"imageIndex": 0', prompts[0])
        self.assertIn('"imageIndex": 1', prompts[1])
        self.assertIn('publicationPlans', prompts[0])
        self.assertIn('Still reject every unsupported', prompts[0])

    def test_rejected_privacy_review_cannot_annotate(self):
        packet = self.load(); row = packet['materials'][0]
        with self.assertRaises(ValueError):
            m.review_visual_groups([row], [row['filePath']], lambda *args: {
                'passed': False, 'issues': ['Personal data visible'], 'observation': 'Logged-in identity'},
                {}, self.folder / 'reviews', 'intake', plan_focus=True)

    def test_symlink_cannot_escape_root(self):
        link = self.folder / 'escape'
        outside = self.root / 'outside'; outside.mkdir()
        try: link.symlink_to(outside, target_is_directory=True)
        except OSError: self.skipTest('Symlink creation unavailable')
        (outside / 'official.png').write_bytes(self.image.read_bytes())
        packet = copy.deepcopy(self.packet); packet['materials'][0]['filePath'] = str(link / 'official.png')
        with self.assertRaises(m.MaterialRequired): self.load(packet)

    def test_required_capture_missing_blocks_but_generated_article_remains_supported(self):
        from naver_blog_posting.pipeline_runner import require_generation_materials
        writer = {'readerTask': {'articleType': 'explainer', 'medium': 'conceptual',
            'question': 'Which form?', 'successCondition': 'Find the required form',
            'requiredMaterialIds': ['official']}, 'blocks': [{'text': 'Instructions'}]}
        result = {'requiredMaterials': [{'kind': 'actual_capture', 'materialId': 'official',
            'description': 'Official page', 'reason': 'Reader needs the real form', 'afterBlock': 0}],
            'imagePlans': []}
        with self.assertRaises(m.MaterialRequired): require_generation_materials(writer, result, self.folder)
        writer['readerTask']['requiredMaterialIds'] = []
        require_generation_materials(writer, {'requiredMaterials': [], 'imagePlans': [{'source': 'generated'}]}, self.folder)


if __name__ == '__main__': unittest.main()
