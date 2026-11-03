"""Captured evidence must survive old maintenance; all transport is mocked."""
import copy
import unittest
from unittest.mock import patch

from common import content_improvement as improvement
from common import content_maintenance as maintenance
from dashboard.server import doctor, content_auditor as auditor


HTML = ('<h2>Capture instructions</h2><p>Press the capture button.</p>'
        '<figure data-editorial-section="section-1"><img src="https://example.org/capture.png">'
        '<figcaption>Capture controls <a href="https://example.org/help">Official help</a></figcaption></figure>')
ARTICLE = {'id': 1, 'title': 'Capture instructions', 'content': HTML, 'slug': 'capture', 'category': 'Help'}


class EditorialMaintenance(unittest.TestCase):
    def test_marker_is_narrow_and_unchanged_context_is_preserved(self):
        self.assertFalse(improvement.has_editorial_evidence('<p>data-editorial-section</p><img src="a">'))
        self.assertFalse(improvement.has_editorial_evidence(HTML.replace('data-editorial-section', 'data-other')))
        self.assertTrue(improvement.has_editorial_evidence(HTML))
        self.assertFalse(improvement.editorial_evidence_changed(ARTICLE, {'title': ARTICLE['title'], 'contentHtml': HTML}))

    def test_changed_section_credit_marker_and_title_require_recapture(self):
        drafts = [dict(title=ARTICLE['title'], summary='', contentHtml=HTML.replace(before, after))
                  for before, after in [('Press the capture button.', 'Delete the account.'),
                                       ('Official help', 'Unrelated source'), ('section-1', 'section-2'),
                                       ('https://example.org/help', 'https://example.org/unrelated')]]
        drafts.append(dict(title='Unrelated event', summary='', contentHtml=HTML))
        for draft in drafts:
            with self.subTest(draft=draft):
                self.assertIn(improvement.EDITORIAL_EVIDENCE_HOLD, improvement.draft_rules(ARTICLE, draft, {}, []))

    def test_prepare_holds_before_network_or_model(self):
        with patch.object(improvement, 'fetch_page') as fetch, patch.object(improvement, 'model_json') as model:
            result = improvement.prepare_improvement('example.org', 'https://example.org/capture', ARTICLE)
        self.assertEqual(result['status'], 'blocked')
        self.assertEqual(result['reason'], improvement.EDITORIAL_EVIDENCE_HOLD)
        fetch.assert_not_called()
        model.assert_not_called()

    def test_unmarked_edit_still_passes_existing_rules_and_media_removal_fails(self):
        body = '<p>Press the capture button. Read the instructions before continuing.</p>' * 8
        original = {'title': 'Capture instructions', 'content': body + '<img src="https://example.org/capture.png">'}
        draft = {'title': original['title'], 'summary': '', 'contentHtml': original['content'].replace(
            'Press the capture button.', 'Use the capture button.', 1), 'newClaims': [],
            'resolvedIssueIds': ['clarity'], 'changes': [{'issueId': 'clarity',
                'before': 'Press the capture button.', 'after': 'Use the capture button.'}]}
        self.assertEqual(improvement.draft_rules(original, draft, {}, []), [])
        draft['contentHtml'] = draft['contentHtml'].replace('<img src="https://example.org/capture.png">', '')
        errors = improvement.draft_rules(original, draft, {}, [])
        self.assertIn('기존 이미지·영상·광고 코드 변경', errors)
        self.assertNotIn(improvement.EDITORIAL_EVIDENCE_HOLD, errors)

    def test_marked_inspection_remains_available(self):
        with patch.object(improvement, 'fetch_page', side_effect=ValueError('fixture inspection boundary')) as fetch:
            result = improvement.prepare_improvement('example.org', 'https://example.org/capture', ARTICLE,
                                                     limits={'inspectOnly': True})
        fetch.assert_called_once()
        self.assertNotEqual(result.get('reason'), improvement.EDITORIAL_EVIDENCE_HOLD)

    def test_doctor_preserves_source_before_sanitizer_upload_or_local_rewrite(self):
        article = copy.deepcopy(ARTICLE)
        with patch.object(doctor, 'find_live_cf_post', return_value=article), \
             patch.object(doctor, 'find_local_output_runs') as local, \
             patch.object(doctor, 'sanitize_and_optimize_image_bytes') as sanitize, \
             patch.object(doctor.requests, 'post') as upload, patch.object(doctor.requests, 'put') as put:
            result = doctor.remodel_cf_post_by_url('https://www.example.org/capture')
        self.assertEqual(result['status'], 'held')
        self.assertFalse(result['ok'])
        for operation in (local, sanitize, upload, put):
            operation.assert_not_called()
        self.assertEqual(article, ARTICLE)

    def test_thumbnail_generator_rejects_captured_article_before_generation(self):
        with patch('dashboard.common.flow_images._generate_via_openai_api') as generate, \
             patch.object(doctor.requests, 'post') as upload:
            with self.assertRaisesRegex(ValueError, 'recapture and review'):
                doctor.generate_and_upload_clean_editorial_thumbnail('example.org', 'Capture', 'Help', 'capture', HTML)
        generate.assert_not_called()
        upload.assert_not_called()

    def test_auditor_holds_both_mutation_routes_without_transport(self):
        article = copy.deepcopy(ARTICLE)
        with patch.object(auditor.requests, 'get') as get, patch.object(auditor.requests, 'post') as upload, \
             patch.object(auditor.requests, 'put') as put, patch.object(auditor, 'patch_cf_post_category_live') as update:
            image = auditor.remediate_post_images_with_sanitizer('example.org', article, {'suitability': 'fake_person_or_broken_text_ai'}, 'Help')
            text = auditor.remodel_cf_post_content_live('example.org', article, 'Help', needs_full_rewrite=True)
        self.assertEqual(image['status'], 'held')
        self.assertFalse(image['remediated'])
        self.assertEqual(text['status'], 'held')
        self.assertFalse(text['ok'])
        for operation in (get, upload, put, update):
            operation.assert_not_called()
        self.assertEqual(article, ARTICLE)

    def test_cached_review_cannot_bypass_apply_gate(self):
        draft = {'title': ARTICLE['title'], 'contentHtml': HTML.replace('Press the capture button.', 'Delete the account.')}
        with patch('common.work_agenda.enabled', return_value=False), \
             patch.object(maintenance, 'read', side_effect=[ARTICLE, draft, {'status': 'ready'}, {}]), \
             patch.object(maintenance, 'database') as database, patch.object(maintenance, 'atomic') as write, \
             patch.object(doctor.requests, 'get') as get, patch.object(doctor.requests, 'put') as put:
            with self.assertRaisesRegex(ValueError, 'recapture and review'):
                maintenance._apply_job.__wrapped__('fixture')
        for operation in (database, write, get, put):
            operation.assert_not_called()


if __name__ == '__main__':
    unittest.main()
