"""Publication adapters, with browser/model/network boundaries replaced by fixtures.

These tests do not claim that fixture PNGs are real browser evidence. The shared
engine tests own provenance validation; these exercise routing, preservation and
the public output produced from its approved result.
"""
import asyncio
import copy
import hashlib
import json
from contextlib import nullcontext
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from bs4 import BeautifulSoup
from PIL import Image
from cf_posting import posting as cf
from naver_blog_posting import posting as nv
from common import editorial_images as engine, flow_images


class EditorialPosting(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.folder = self.root / 'output' / 'draft'
        self.folder.mkdir(parents=True)
        self.real_build, self.real_validate = engine.build_editorial_assets, engine.validate_editorial_assets
        self.build = self.enterContext(patch.object(engine, 'build_editorial_assets', side_effect=self.capture))
        self.validate = self.enterContext(patch.object(engine, 'validate_editorial_assets', return_value=True))
        self.generator = self.enterContext(patch.object(flow_images, 'generate', side_effect=AssertionError('synthetic image used')))

    def capture(self, title, sections, folder, **kwargs):
        assets = []
        for index, section in enumerate(sections):
            if section.get('image_optional'):
                continue
            path = Path(folder) / 'images' / f'capture-{index}.png'
            path.parent.mkdir(exist_ok=True)
            Image.new('RGB', (40, 40), (index, 90, 110)).save(path)
            assets.append({'path': str(path), 'filename': 'images/' + path.name,
                           'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
                           'section_index': index, 'sectionId': section['id'],
                           'anchor_text': section['body'].splitlines()[0],
                           'caption': section['heading'], 'alt': section['heading'], 'origin': 'screenshot',
                           'sourceUrl': f'https://agency.example/notice/{index}', 'sourceTitle': 'Source agency',
                           'evidence': {'fixture': True}})
        return {'status': 'ready', 'assets': assets, 'manifest_path': str(Path(folder) / 'fixture.json'),
                'manifest_sha256': 'fixture', 'content_sha256': 'fixture', 'reasons': []}

    def article(self, title='Benefit application guide'):
        return {'title': title, 'summary': 'Two distinct source contexts', 'category': 'news', 'topicSlug': 'source-guide',
                'contentHtml': '<p>Introduction.</p><h2>Application</h2><p>Apply using the official form.</p>'
                               '<h2>Application update</h2><p>The event venue changed today.</p>'}

    def document(self, title='Benefit application guide'):
        return {'title': title, 'published': False, 'blocks': [
            {'type': 'text', 'text': 'Introduction.'},
            {'type': 'heading', 'text': 'Application'}, {'type': 'text', 'text': 'Apply using the official form.'},
            {'type': 'heading', 'text': 'Application update'}, {'type': 'text', 'text': 'The event venue changed today.'},
            {'type': 'signoff', 'text': 'Thank you.'}, {'type': 'tags', 'text': '#guide'}]}

    def test_information_and_event_articles_use_exact_sections_in_both_channels(self):
        for title in ('Benefit application guide', 'Festival venue changed today'):
            with self.subTest(title=title):
                article = cf.ensure_article_images(self.article(title), self.folder)
                soup = BeautifulSoup(article['contentHtml'], 'html.parser')
                figures = soup.find_all('figure')
                self.assertEqual([f.find_previous('h2').text for f in figures], ['Application', 'Application update'])
                self.assertEqual([f['data-editorial-section'] for f in figures], ['section-1', 'section-2'])
                self.assertTrue(all(f.find('a')['href'].startswith('https://agency.example/') for f in figures))
                doc = self.document(title)
                plan = nv.prepare_document_images(doc, self.folder, 'guide', 'Thank you.')
                nv.verify_document_images(doc, plan, self.folder)
                rendered = BeautifulSoup(nv.render_document(doc, plan, self.folder / 'images'), 'html.parser')
                self.assertEqual([f.find_previous('h2').text for f in rendered.select('figure')], ['Application', 'Application update'])
                self.assertEqual(plan['assets'][1]['editorialAsset']['sourceUrl'], 'https://agency.example/notice/2')
        self.generator.assert_not_called()

    def test_no_source_holds_without_synthetic_fallback(self):
        self.build.side_effect = None
        self.build.return_value = {'status': 'held', 'assets': [], 'reasons': ['no_matching_source']}
        for prepare in (lambda: cf.ensure_article_images(self.article(), self.folder),
                        lambda: nv.prepare_document_images(self.document(), self.folder, 'guide')):
            with self.assertRaisesRegex(ValueError, 'no_matching_source'):
                prepare()
        self.assertFalse((self.folder / 'article.json').exists())
        self.assertEqual(json.loads((self.folder / 'image-preparation-status.json').read_text())['status'], 'held')
        self.generator.assert_not_called()

    def test_core_rejection_blocks_reuse_and_upload(self):
        article = cf.ensure_article_images(self.article(), self.folder)
        keyword = article['title'].split()[0]
        article['mainKeyword'] = keyword
        (self.folder / 'planning.json').write_text(json.dumps({'keyword': keyword}), encoding='utf-8')
        (self.folder / 'research.json').write_text(json.dumps({'keyword': keyword, 'requestedKeyword': keyword}), encoding='utf-8')
        self.validate.return_value = False
        with patch.object(cf, 'registered_categories', return_value=['news']), \
             patch.object(cf, 'published_inventory', return_value=[]), \
             patch.object(cf, 'upload_images_to_cf') as upload, patch.object(cf.requests, 'post') as post:
            with self.assertRaisesRegex(ValueError, 'stale_or_mismatched'):
                cf.publish_basic_article('example.com', article, self.folder)
            upload.assert_not_called()
            post.assert_not_called()

    def test_engine_section_mismatch_cannot_fall_back_to_nearby_heading(self):
        bad = self.capture('title', cf.article_image_sections(self.article()), self.folder)
        bad['assets'][0]['sectionId'] = 'unknown-section'
        self.build.side_effect = None
        self.build.return_value = bad
        with self.assertRaisesRegex(ValueError, 'capture_section'):
            cf.ensure_article_images(self.article(), self.folder)
        with self.assertRaisesRegex(ValueError, 'capture_section'):
            nv.prepare_document_images(self.document(), self.folder, 'guide')

    def test_moving_image_to_other_section_is_rejected_even_if_local_digest_is_updated(self):
        article = cf.ensure_article_images(self.article(), self.folder)
        soup = BeautifulSoup(article['contentHtml'], 'html.parser')
        soup.h2.insert_before(soup.figure.extract())
        article['contentHtml'] = str(soup)
        article['imageDocumentSha256'] = hashlib.sha256(article['contentHtml'].encode()).hexdigest()
        with self.assertRaisesRegex(ValueError, 'section_or_source_mapping'):
            cf.verify_article_images(article, self.folder)
        doc = self.document()
        plan = nv.prepare_document_images(doc, self.folder, 'guide', 'Thank you.')
        image = next(b for b in doc['blocks'] if b['type'] == 'image')
        doc['blocks'].remove(image)
        doc['blocks'].insert(0, image)
        plan['documentSha256'] = nv.document_fingerprint(doc)
        with self.assertRaisesRegex(ValueError, 'image_section_mapping'):
            nv.verify_document_images(doc, plan, self.folder)

    def test_exact_later_paragraph_anchor_controls_placement(self):
        def capture_later(title, sections, folder, **kwargs):
            result = self.capture(title, sections, folder, **kwargs)
            result['assets'][0]['anchor_text'] = 'The precise evidence appears here.'
            return result
        self.build.side_effect = capture_later
        article = self.article()
        article['contentHtml'] = article['contentHtml'].replace('Apply using the official form.</p>',
            'Apply using the official form.</p><div><p>The precise evidence appears here.</p></div><p>Later commentary.</p>')
        article = cf.ensure_article_images(article, self.folder)
        soup = BeautifulSoup(article['contentHtml'], 'html.parser')
        self.assertEqual(soup.figure.find_previous('p').text, 'The precise evidence appears here.')
        doc = self.document()
        doc['blocks'][2]['text'] += '\nThe precise evidence appears here.\nLater commentary.'
        sections_before = nv.naver_image_sections(doc)
        plan = nv.prepare_document_images(doc, self.folder, 'guide', 'Thank you.')
        self.assertEqual(nv.naver_image_sections(doc), sections_before)
        image_index = next(i for i, b in enumerate(doc['blocks']) if b['type'] == 'image')
        self.assertTrue(doc['blocks'][image_index - 1]['text'].endswith('The precise evidence appears here.'))
        self.assertEqual(doc['blocks'][image_index + 1]['text'], 'Later commentary.')
        nv.verify_document_images(doc, plan, self.folder)

    def test_unmatched_paragraph_anchor_holds_instead_of_using_section_start(self):
        def capture_wrong(title, sections, folder, **kwargs):
            result = self.capture(title, sections, folder, **kwargs)
            result['assets'][0]['anchor_text'] = 'This sentence was never in this article.'
            return result
        self.build.side_effect = capture_wrong
        with self.assertRaisesRegex(ValueError, 'exact_text_anchor_missing'):
            cf.ensure_article_images(self.article(), self.folder)
        with self.assertRaisesRegex(ValueError, 'exact_text_anchor_missing'):
            nv.prepare_document_images(self.document(), self.folder, 'guide')

    def test_legacy_prepared_images_preserved_and_explicitly_held(self):
        old = self.article()
        old['imagePlans'] = [{'filename': 'fake.png', 'source': 'generated'}]
        original = copy.deepcopy(old)
        with self.assertRaisesRegex(ValueError, 'legacy_prepared'):
            cf.ensure_article_images(old, self.folder)
        self.assertEqual(old, original)
        doc = self.document()
        (self.folder / 'editor-content.json').write_text(json.dumps(doc), encoding='utf-8')
        (self.folder / 'photo-plan.json').write_text(json.dumps({'assets': [{'file': 'fake.png'}]}), encoding='utf-8')
        before = (self.folder / 'editor-content.json').read_bytes()
        with patch.object(nv, 'BASE_DIR', self.root), self.assertRaisesRegex(ValueError, 'legacy_prepared'):
            nv.prepare_basic_content('soultin', self.folder)
        self.assertEqual((self.folder / 'editor-content.json').read_bytes(), before)
        self.build.assert_not_called()

    def test_submitted_artifacts_and_pending_prepare_only_are_preserved(self):
        article = self.article()
        article['imagePlans'] = [{'filename': 'old.png'}]
        for state in ('accepted', 'submitting', 'submission_unknown', 'published'):
            (self.folder / 'publication-receipt.json').write_text(json.dumps({'state': state}))
            self.assertIs(cf.ensure_article_images(article, self.folder), article)
        for state in ('submitting', 'submission_unknown', 'verified_reserved'):
            (self.folder / 'reservation-evidence.json').write_text(json.dumps({'submissionStatus': state}))
            with patch.object(nv, 'BASE_DIR', self.root), patch.object(nv, 'pipeline_lock', return_value=nullcontext()), \
                 patch.object(nv, 'reconcile_basic_submission') as reconcile, patch.object(nv, 'start_browser') as browser:
                result = nv.run_basic_pipeline('soultin', self.folder, prepare_only=True)
                self.assertEqual(result['submissionStatus'], state)
                reconcile.assert_not_called()
                browser.assert_not_called()
        self.build.assert_not_called()

    def test_explicit_optional_section_is_omitted_without_losing_required_image(self):
        article = self.article()
        article['sectionImages'] = [{'sectionHeading': 'Application', 'image_optional': True}]
        result = cf.ensure_article_images(article, self.folder)
        self.assertEqual([p['sectionId'] for p in result['imagePlans']], ['section-2'])
        doc = self.document()
        doc['editorialSectionOptions'] = {'section-1': True}
        plan = nv.prepare_document_images(doc, self.folder, 'guide', 'Thank you.')
        self.assertTrue(nv.validate_document(doc, plan, self.folder / 'images')['ok'])
        native = nv.basic_native_document({'document': {'components': [
            {'@ctype': 'documentTitle'}, {'@ctype': 'image', 'fileName': plan['assets'][0]['file']}]}}, doc)
        self.assertEqual(sum(c.get('@ctype') == 'image' for c in native['document']['components']), 1)
        self.assertEqual(plan['assets'][0]['sectionId'], 'section-2')

    def test_real_core_manifest_validates_five_section_writer_and_cf_roundtrip(self):
        from dashboard.tests.test_editorial_images import Browser, model, TEXT
        Browser.calls, Browser.failure = [], None

        def optional_model(stage, payload, *args):
            result, receipt = model(stage, payload, *args)
            if stage == 'plan':
                for section, choice in zip(payload['sections'], result['sections']):
                    if section['image_optional']:
                        choice['decision'] = 'omit'
                receipt['response_sha256'] = engine._hash(result)
            return result, receipt

        writer = {'title': 'Screen capture instructions', 'mainKeyword': 'capture', 'intro': TEXT,
                  'closing': 'Read the instructions before capturing.', 'signoff': 'Thank you.', 'tags': ['#capture'],
                  'sections': [{'heading': f'Capture instructions {i}', 'text': TEXT, 'image_optional': i > 3}
                               for i in range(1, 6)]}
        (self.folder / 'writer.json').write_text(json.dumps(writer), encoding='utf-8')
        with patch.object(engine, 'build_editorial_assets', self.real_build), \
             patch.object(engine, 'validate_editorial_assets', self.real_validate), \
             patch.object(engine, '_Browser', Browser), patch.object(engine, '_model', optional_model), \
             patch.object(engine.socket, 'getaddrinfo', return_value=[(2, 1, 6, '', ('93.184.215.14', 443))]), \
             patch.object(nv, 'BASE_DIR', self.root), patch.object(nv, 'update_pipeline_status'), \
             patch('common.content_quality.ensure_publication_review'):
            _, _, document, plan = nv.prepare_basic_content('soultin', self.folder)
            self.assertEqual(len(plan['assets']), 3)
            self.assertEqual(plan['editorialImages']['status'], 'ready')
            before = len(Browser.calls)
            nv.prepare_basic_content('soultin', self.folder)
            self.assertEqual(len(Browser.calls), before)
            cf_folder = self.root / 'cf'
            article = {'title': 'Screen capture instructions', 'summary': TEXT, 'category': 'guide',
                       'topicSlug': 'capture-guide', 'contentHtml': f'<p>{TEXT}</p><h2>Capture controls</h2><p>{TEXT}</p>'}
            article = cf.ensure_article_images(article, cf_folder)
            cf.verify_article_images(article, cf_folder)
            Path(article['editorialImages']['assets'][0]['path']).write_bytes(b'changed image')
            with self.assertRaisesRegex(ValueError, 'stale_or_mismatched'):
                cf.verify_article_images(article, cf_folder)
            Path(plan['editorialImages']['assets'][0]['path']).write_bytes(b'changed image')
            with self.assertRaisesRegex(ValueError, 'stale_or_mismatched'):
                nv.verify_document_images(document, plan, self.folder)

    def test_cf_upload_payload_preserves_exact_mapping_source_and_representative(self):
        article = cf.ensure_article_images(self.article(), self.folder)
        keyword = article['title'].split()[0]
        article['mainKeyword'] = keyword
        (self.folder / 'planning.json').write_text(json.dumps({'keyword': keyword}), encoding='utf-8')
        (self.folder / 'research.json').write_text(json.dumps({'keyword': keyword, 'requestedKeyword': keyword}), encoding='utf-8')
        urls = ['https://cdn.example/capture1.png', 'https://cdn.example/capture2.png']
        response = MagicMock(status_code=201)
        with patch.object(cf, 'registered_categories', return_value=['news']), \
             patch.object(cf, 'published_inventory', return_value=[]), \
             patch('common.content_quality.ensure_publication_review'), \
             patch.object(cf, 'get_api_key', return_value='test-only'), \
             patch.object(cf, 'upload_images_to_cf', return_value=urls) as upload, \
             patch.object(cf.requests, 'post', return_value=response) as post, \
             patch.object(cf, 'basic_public_receipt', return_value={'state': 'fixture'}) :
            cf.publish_basic_article('example.com', article, self.folder)
        payload = post.call_args.kwargs['json']
        self.assertEqual(payload['thumbnail'], urls[0])
        soup = BeautifulSoup(payload['content'], 'html.parser')
        self.assertEqual([x['src'] for x in soup.select('figure img')], urls)
        self.assertEqual([f.find_previous('h2').text for f in soup.select('figure')], ['Application', 'Application update'])
        self.assertEqual([a['href'] for a in soup.select('figure a')],
                         ['https://agency.example/notice/1', 'https://agency.example/notice/2'])
        self.assertEqual(len(upload.call_args.args[1]), 2)

    def test_native_image_moving_across_same_text_is_detected(self):
        def text(value):
            return {'@ctype': 'text', 'value': [{'nodes': [{'value': value}]}]}
        image = {'@ctype': 'image', 'fileName': 'capture.png', 'caption': [{'nodes': [{'value': 'Source caption'}]}]}
        native = {'document': {'components': [{'@ctype': 'documentTitle'}, text('Section one'), image, text('Section two')]}}
        moved = copy.deepcopy(native)
        moved['document']['components'].append(moved['document']['components'].pop(2))
        before, after = nv.basic_editor_content(native), nv.basic_editor_content(moved)
        self.assertEqual(before['body'], after['body'])
        self.assertEqual(before['images'], after['images'])
        self.assertNotEqual(before['sequence'], after['sequence'])

    def test_legacy_capture_requests_do_not_generate_when_browser_fails(self):
        with self.assertRaisesRegex(ValueError, 'simulated_capture_removed'):
            flow_images.generate_section_smart_capture('heading', 'body', self.folder, 'fake.png')
        with patch.object(flow_images, 'capture_research_evidence', new=AsyncMock(side_effect=RuntimeError('browser unavailable'))), \
             patch.object(flow_images, '_generate_via_openai_api') as generator:
            with self.assertRaisesRegex(RuntimeError, 'browser unavailable'):
                asyncio.run(flow_images._generate('title', 'body', self.folder, custom_prompt='RESEARCH_CAPTURE'))
            generator.assert_not_called()
        self.assertFalse((self.folder / 'images' / 'fake.png').exists())

    def test_ab_writer_routing_deconstraining_and_badge_resolution(self):
        from common import llm_client
        cf_schema = {'type': 'object', 'properties': {'contentHtml': {'type': 'string'}, 'topicSlug': {'type': 'string'}}}
        nv_schema = {'type': 'object', 'properties': {'intro': {'type': 'string'}, 'sections': {'type': 'array'}}}
        rev_schema = {'type': 'object', 'properties': {'status': {'type': 'string'}}}
        self.assertTrue(llm_client.is_article_writer_call('cf_pipeline', cf_schema))
        self.assertTrue(llm_client.is_article_writer_call('publi', nv_schema))
        self.assertFalse(llm_client.is_article_writer_call('reviewer', rev_schema))
        raw_prompt = '- [모바일 줄바꿈 (최우선)] 1문단 = 1~2문장(32~48자 단문)\n- 각 섹션은 5~6개 문단으로 작성\n본문 작성'
        cleaned = llm_client.deconstrain_writer_prompt(raw_prompt, 'cf_pipeline')
        self.assertNotIn('32~48자 단문', cleaned)
        self.assertNotIn('각 섹션은 5~6개 문단', cleaned)
        self.assertIn('De-Constrained Editorial Mode', cleaned)
        llm_client.persist_writer_meta(self.folder / 'model-audit', 'agy', 'claude-sonnet-5-5-high', deconstrained=True)
        resolved = llm_client.resolve_folder_writer_meta(self.folder)
        self.assertEqual(resolved['abArm'], 'claude')
        self.assertIn('Claude', resolved['writerBadge'])


if __name__ == '__main__':
    unittest.main()
