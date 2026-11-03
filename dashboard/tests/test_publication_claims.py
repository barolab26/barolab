"""Collected-source fixtures only; no model, browser, or publishing calls."""
from datetime import datetime, timezone
from contextlib import nullcontext
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from common import content_quality as quality


class PublicationClaims(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.claim = '보험 지급 한도는 100만원입니다.'
        self.document = {'title': '보험 지급 조건', 'summary': '조건을 확인합니다.', 'contentHtml': '<p>' + self.claim + '</p>'}
        self.research = {'collectedAt': datetime.now(timezone.utc).isoformat(),
                         'sources': [{'url': 'https://www.gov.kr/policy', 'text': self.claim + ' 적용 대상과 지급 조건을 함께 확인합니다.'}]}
        self.response = {'status': 'passed', 'issues': [], 'experienceHonest': True, 'claimsComplete': True,
                         'highRiskClaims': [self.claim], 'experienceClaims': [], 'hypotheticalClaims': [],
                         'claimSources': [{'claim': self.claim, 'sourceId': '0', 'quote': self.claim}]}
        self.save_research()

    def save_research(self):
        for source in self.research['sources']:
            source.setdefault('status', 200)
            source['textSha256'] = hashlib.sha256(source['text'].encode('utf-8')).hexdigest()
        (self.folder / 'research.json').write_text(json.dumps(self.research), encoding='utf-8')

    def test_low_risk_numbers_do_not_trigger_model_or_blanket_hold(self):
        model = MagicMock()
        result = quality.ensure_publication_review({'title': '책 정리', 'contentHtml': '<p>선반을 3칸으로 나누는 예시입니다.</p>'}, self.folder, generate=model)
        self.assertEqual(result['status'], 'not_required')
        model.assert_not_called()

    def test_explicit_hypothetical_financial_quantity_is_not_an_actual_revenue_claim(self):
        claim = '가정 예시: 보험 지급액을 100만원으로 놓고 비교합니다.'
        document = {'title': '보험 계산 예시', 'contentHtml': '<p>' + claim + '</p>'}
        response = {**self.response, 'highRiskClaims': [], 'claimSources': [], 'hypotheticalClaims': [claim]}
        self.assertEqual(quality.ensure_publication_review(document, self.folder, generate=MagicMock(return_value=response))['status'], 'passed')

    def test_same_quantity_in_example_does_not_validate_a_different_actual_claim(self):
        example = '가정 예시: 보험 지급액을 100만원으로 놓습니다.'
        document = {'title': '보험 안내', 'contentHtml': '<p>' + example + '</p><p>다른 보험의 지급 한도는 100만원입니다.</p>'}
        response = {**self.response, 'highRiskClaims': [], 'claimSources': [], 'hypotheticalClaims': [example]}
        with self.assertRaisesRegex(ValueError, 'primary-source evidence'):
            quality.ensure_publication_review(document, self.folder, generate=MagicMock(return_value=response))

    def test_primary_quote_mapping_and_review_cache(self):
        model = MagicMock(return_value=self.response)
        first = quality.ensure_publication_review(self.document, self.folder, generate=model)
        second = quality.ensure_publication_review(self.document, self.folder, generate=model)
        self.assertEqual(first, second)
        model.assert_called_once()
        self.assertEqual(model.call_args.kwargs['agent_slot'], 'doctor')

    def test_collected_long_source_hash_survives_research_storage_and_review(self):
        from common import source_discovery
        body = self.claim + ' 적용 대상과 지급 조건을 확인합니다.' * 1000
        response = MagicMock(status_code=200, headers={'Content-Type': 'text/html'})
        response.__enter__.return_value = response
        response.iter_content.return_value = [('<article>' + body + '</article>').encode('utf-8')]
        with patch.object(source_discovery, 'search_urls', return_value=[{'url': 'https://www.gov.kr/policy'}]), \
             patch.object(source_discovery.requests, 'get', return_value=response) as http, \
             patch.object(source_discovery.socket, 'getaddrinfo', return_value=[(None, None, None, None, ('8.8.8.8', 443))]), \
             patch('dashboard.agents.synapse.research_query', side_effect=lambda keyword, folder: keyword), \
             patch('common.crew_chat_bridge.emit_work_event'), \
             patch('common.crew_chat_bridge.work_task_id', return_value='fixture'):
            collected = source_discovery.research('fixture', self.folder)
        stored = json.loads((self.folder / 'research.json').read_text(encoding='utf-8'))
        self.assertEqual(stored['sources'], collected)
        self.assertEqual(len(collected[0]['text']), 9000)
        self.assertEqual(collected[0]['textSha256'], hashlib.sha256(collected[0]['text'].encode('utf-8')).hexdigest())
        http.assert_called_once()
        model = MagicMock(return_value=self.response)
        self.assertEqual(quality.ensure_publication_review(self.document, self.folder, generate=model)['status'], 'passed')
        model.assert_called_once()

    def test_writer_boolean_without_mapping_cannot_pass(self):
        response = {**self.response, 'claimSources': [], 'highRiskClaims': []}
        with self.assertRaisesRegex(ValueError, 'primary-source evidence'):
            quality.ensure_publication_review(self.document, self.folder, generate=MagicMock(return_value=response))

    def test_source_quote_and_sensitive_number_must_match(self):
        self.research['sources'][0]['text'] = '보험 지급 한도는 10만원입니다.'
        self.save_research()
        with self.assertRaisesRegex(ValueError, 'quote/number'):
            quality.ensure_publication_review(self.document, self.folder, generate=MagicMock(return_value=self.response))

    def test_secondary_source_cannot_back_high_stakes_claim(self):
        self.research['sources'][0]['url'] = 'https://blog.example.com/post'
        self.save_research()
        with self.assertRaisesRegex(ValueError, 'primary-source mapping'):
            quality.ensure_publication_review(self.document, self.folder, generate=MagicMock(return_value=self.response))

    def test_unsupported_first_person_is_held_despite_pass_boolean(self):
        document = {'title': '사용 기록', 'contentHtml': '<p>제가 직접 사용해보니 편했습니다.</p>'}
        response = {**self.response, 'highRiskClaims': [], 'claimSources': []}
        with self.assertRaisesRegex(ValueError, 'author experience'):
            quality.ensure_publication_review(document, self.folder, generate=MagicMock(return_value=response))

    def test_first_person_regional_visit_is_not_missed_by_distance(self):
        document = {'title': '업체 비교', 'contentHtml': '<p>저는 대구, 포항, 구미 지역의 5개 업체를 직접 방문하고 문의했습니다.</p>'}
        response = {**self.response, 'highRiskClaims': [], 'claimSources': []}
        with self.assertRaisesRegex(ValueError, 'author experience'):
            quality.ensure_publication_review(document, self.folder, generate=MagicMock(return_value=response))

    def test_http_failure_or_missing_status_cannot_be_recast_as_collected_success(self):
        for status in (None, 404, 500):
            with self.subTest(status=status):
                self.research['sources'][0]['status'] = status
                self.save_research()
                with self.assertRaisesRegex(ValueError, 'quote/number'):
                    quality.ensure_publication_review(self.document, self.folder, generate=MagicMock(return_value=self.response))

    def test_changed_draft_requires_new_review_and_failed_draft_is_not_retried(self):
        model = MagicMock(return_value=self.response)
        quality.ensure_publication_review(self.document, self.folder, generate=model)
        changed = {**self.document, 'contentHtml': '<p>보험 지급 한도는 200만원입니다.</p>'}
        rejected = {**self.response, 'status': 'changes_required', 'issues': ['Unsupported amount']}
        model.return_value = rejected
        for _ in range(2):
            with self.assertRaises(ValueError):
                quality.ensure_publication_review(changed, self.folder, generate=model)
        self.assertEqual(model.call_count, 2)

    def test_missing_research_holds_without_model_call(self):
        (self.folder / 'research.json').unlink()
        model = MagicMock()
        with self.assertRaisesRegex(ValueError, 'research snapshot missing'):
            quality.ensure_publication_review(self.document, self.folder, generate=model)
        model.assert_not_called()

    def test_cf_submission_and_media_upload_do_not_run_after_gate_rejection(self):
        from cf_posting import posting as cf
        article = {**self.document, 'category': 'test', 'topicSlug': 'test-claim'}
        with patch.object(cf, 'registered_categories', return_value=['test']), \
             patch.object(cf, 'published_inventory', return_value=[]), \
             patch.object(cf, 'duplicate_posts', return_value=[]), \
             patch.object(cf, 'verify_article_images', return_value={}), \
             patch('common.cf_tables.style_tables', side_effect=lambda content, **k: content), \
             patch('common.cf_tables.inject_interactive_widget', side_effect=lambda content, *a, **k: content), \
             patch.object(quality, 'ensure_publication_review', side_effect=ValueError('draft held')), \
             patch.object(cf, 'upload_images_to_cf') as upload, patch.object(cf.requests, 'post') as post:
            with self.assertRaisesRegex(ValueError, 'draft held'):
                cf.publish_basic_article('example.com', article, self.folder)
            upload.assert_not_called()
            post.assert_not_called()
            self.assertFalse((self.folder / 'publication-receipt.json').exists())

    def test_naver_submission_gate_runs_before_browser_and_submission_receipt(self):
        from naver_blog_posting import posting as naver
        folder = self.folder / 'output/draft'
        folder.mkdir(parents=True)
        document = {'title': '보험 지급 조건', 'blocks': [{'type': 'text', 'text': self.claim}]}
        account = {'blog_id': 'fixture', 'cdp_port': 1}
        with patch.object(naver, 'BASE_DIR', self.folder), \
             patch.object(naver, 'pipeline_lock', return_value=nullcontext()), \
             patch.object(naver, 'prepare_basic_content', return_value=(account, folder, document, {})), \
             patch.object(naver, 'write_attempt'), patch.object(naver, 'read_journal', return_value={'attempts': []}), \
             patch.object(naver, 'start_browser') as browser, \
             patch('common.ubuntu_naver_browser.close_account'), \
             patch.object(quality, 'ensure_publication_review', side_effect=ValueError('draft held')):
            with self.assertRaisesRegex(ValueError, 'draft held'):
                naver.run_basic_pipeline('fixture', folder=folder)
            browser.assert_not_called()
            self.assertFalse((folder / 'reservation-evidence.json').exists())


if __name__ == '__main__':
    unittest.main()
