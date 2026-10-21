import hashlib
import unittest
from unittest.mock import Mock, patch
from contextlib import nullcontext
from naver_blog_posting.visible_research import ranked_posts, validate_capture_request, public_page, search_public_query


class ResearchEvidenceTests(unittest.TestCase):
    def test_public_search_uses_actual_keys_and_restores_existing_tab(self):
        original='https://blog.naver.com/mustpickinfo'
        page=Mock(url=original)
        page.is_closed.return_value=False
        page.locator.return_value.inner_text.return_value='Public result'
        page.goto.side_effect=lambda url, **kw: setattr(page,'url',url)
        with patch('common.ego_telemetry.action',side_effect=lambda *a,**kw:nullcontext()) as observed:
            result=search_public_query(page,'시니어브리프')
        self.assertTrue(result['queryMatched'])
        page.keyboard.type.assert_called_once_with('시니어브리프',delay=100)
        self.assertEqual(page.goto.call_args.args,(original,))
        self.assertIn(('type','naver-search-query'),[c.args for c in observed.call_args_list])
        page.close.assert_not_called()

    def test_editor_tab_is_never_navigated_and_search_failure_restores(self):
        page=Mock(url='https://blog.naver.com/PostWriteForm.naver')
        with self.assertRaises(ValueError):search_public_query(page,'test')
        page.goto.assert_not_called()
        original='https://blog.naver.com/mustpickinfo';page.url=original
        page.is_closed.return_value=False
        page.goto.side_effect=lambda url,**kw:setattr(page,'url',url)
        page.keyboard.type.side_effect=RuntimeError('input failed')
        with patch('common.ego_telemetry.action',side_effect=lambda *a,**kw:nullcontext()):
            with self.assertRaisesRegex(RuntimeError,'input failed'):search_public_query(page,'test')
        self.assertEqual(page.goto.call_args.args,(original,))

    def test_reused_public_tab_never_navigated_or_closed(self):
        page = Mock(url='https://example.com/article')
        context = Mock(pages=[page])
        with public_page(context, page.url) as (actual, owned):
            self.assertIs(actual, page)
            self.assertFalse(owned)
        page.goto.assert_not_called()
        page.close.assert_not_called()
        context.new_page.assert_not_called()

    def test_owned_tab_closed_even_when_navigation_fails(self):
        page = Mock()
        page.is_closed.return_value = False
        page.goto.side_effect = RuntimeError('navigation failed')
        context = Mock(pages=[])
        context.new_page.return_value = page
        with self.assertRaises(RuntimeError):
            with public_page(context, 'https://example.com/article'):
                self.fail('Navigation should fail')
        page.close.assert_called_once_with()

    def test_observed_order_deduplicates_and_excludes_ads(self):
        rows = [{'url': f'https://blog.naver.com/owner/{n}', 'title': str(n)} for n in (7, 7, 4, 1)]
        rows.insert(0, {'url': 'https://blog.naver.com/ad/88', 'title': 'paid', 'advertisement': True})
        result = ranked_posts(rows)
        self.assertEqual([r['url'].rsplit('/', 1)[1] for r in result], ['7', '4', '1'])
        self.assertEqual([r['observedRank'] for r in result], [1, 2, 3])

    def test_fewer_than_three_fails(self):
        with self.assertRaises(RuntimeError):
            ranked_posts([{'url': 'https://blog.naver.com/one/1', 'title': 'one'}])

    def request(self):
        text = 'A real official source paragraph describing an application.'
        url = 'https://www.easylaw.go.kr/example'
        return {'sourceUrl': url, 'materialId': 'application', 'stepId': 'apply',
                'observation': 'Application instructions', 'anchors': ['official source paragraph'],
                'sourceEvidence': {'url': url, 'text': text, 'bodySha256': hashlib.sha256(text.encode()).hexdigest()}}

    def test_capture_requires_real_source_anchor_and_hash(self):
        request = self.request()
        self.assertEqual(validate_capture_request(request), request['sourceUrl'])
        request['anchors'] = ['Invented unseen instruction']
        with self.assertRaises(ValueError):
            validate_capture_request(request)
        request = self.request()
        request['sourceEvidence']['text'] += 'changed'
        with self.assertRaises(ValueError):
            validate_capture_request(request)

    def test_private_or_nonofficial_capture_rejected(self):
        for url in ['https://example.com/x', 'https://www.easylaw.go.kr/x?token=secret', 'http://www.easylaw.go.kr/x']:
            request = self.request()
            request['sourceUrl'] = url
            with self.assertRaises(ValueError):
                validate_capture_request(request)


if __name__ == '__main__':
    unittest.main()
