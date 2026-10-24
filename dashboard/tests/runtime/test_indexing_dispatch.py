import unittest
from types import SimpleNamespace
from unittest.mock import patch

from common import indexing_dispatch as dispatch
from dashboard.collectors.searchadvisor_ui import run as crawl
from dashboard.indexing_submissions import observe_daum


class DispatchTests(unittest.TestCase):
    def test_google_sitemap_recovery_preserves_existing_receipt_and_uses_no_indexnow(self):
        sites = [{'site_id': x, 'platform': 'cf'} for x in ('done', 'missing')]
        snapshot = {'sites': {'done': {'indexingRequest': {'google': {'status': 'submitted', 'checkedAt': dispatch.metrics.stamp()}}}}}
        from contextlib import nullcontext
        with patch.object(dispatch.metrics, 'inventory', return_value=sites), \
                patch.object(dispatch.metrics, 'read_json', return_value=snapshot), \
                patch.object(dispatch.metrics, 'google_session', return_value=nullcontext(object())), \
                patch.object(dispatch.metrics, 'sitemap_status', return_value={'status': 'available'}), \
                patch.object(dispatch.metrics, 'request_indexing', return_value={
                    'google': {'status': 'submitted', 'indexed': None}}) as request, \
                patch.object(dispatch.metrics, 'collector_lock', return_value=nullcontext(True)), \
                patch.object(dispatch.metrics, 'atomic_write'):
            rows = dispatch.submit_google_sitemaps({})
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['domain'], 'missing')
        self.assertIsNone(rows[0]['indexed'])
        self.assertIs(request.call_args.kwargs['indexnow'], False)

    def test_daum_official_missing_registration_is_separate_from_search_presence(self):
        site = {'site_id': 'example.com', 'url': 'https://www.example.com/'}
        client = SimpleNamespace(
            post=lambda *a, **kw: SimpleNamespace(status_code=200, text=site['url'] +
                ' 등록조회 결과 해당 사이트는 현재 등록 되어 있지 않습니다'),
            get=lambda *a, **kw: SimpleNamespace(status_code=200,
                text='<a href="https://www.example.com/article">found</a>'))
        result = observe_daum(site, client)
        self.assertFalse(result['registrationVerified'])
        self.assertTrue(result['searchResultObserved'])
        self.assertIsNone(result['indexed'])
        client.post = lambda *a, **kw: SimpleNamespace(status_code=200, text='captcha')
        self.assertIsNone(observe_daum(site, client)['registrationVerified'])

    def test_visible_batch_accepts_daily_cap_and_rejects_over_cap(self):
        self.assertEqual(crawl(apply=False, batch_size=50)['status'], 'explicit_apply_required')
        with self.assertRaises(ValueError):
            crawl(apply=False, batch_size=51)

    def test_refresh_excludes_reserved_and_invalid_and_refreshes_only_live_evidence(self):
        site = {'site_id': 'example.com', 'url': 'https://www.example.com/'}
        root = site['url']
        state = {'crawlQueue': [{'url': root + x} for x in ('done', 'broken', 'new')],
                 'crawlRequests': [{'url': root + 'done'}]}
        with patch.object(dispatch, 'validate_public_url', side_effect=lambda s, u: {
                'url': u, 'valid': u.endswith('new')}) as validate, \
                patch.object(dispatch.metrics, 'atomic_write'), \
                patch.object(dispatch.searchadvisor, 'queue_crawl_candidates') as queue:
            self.assertEqual(dispatch.refresh_candidates(site, state, 1), [root + 'new'])
        self.assertEqual(validate.call_count, 2)
        self.assertEqual(queue.call_args.args[0], [root + 'new'])
        self.assertNotEqual(queue.call_args.kwargs['evidence']['checkedAt'], '1970-01-01T00:00:00+00:00')


if __name__ == '__main__':
    unittest.main()
