"""Offline traffic-focus and reserved test URL boundary regressions."""
import ast
from contextlib import nullcontext
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch, Mock
ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from common.channel_attribution import PRIORITY_CF_DOMAINS, domain_cpc_priority_rank, is_dummy_rescue_url, _canonical
from dashboard import metrics

class BridgeIndexingTests(unittest.TestCase):

    def test_reserved_prefix_normalization_preserves_normal_articles(self):
        for value in ['index-rescue-test', 'https://www.must-good.com/INDEX-RESCUE-one?q=1', 'https://www.must-good.com/%69ndex-rescue-two#fragment', 'https://www.must-good.com/%2569ndex-rescue-three', '/x/index-rescue-four']:
            self.assertTrue(is_dummy_rescue_url(value), value)
        for value in ['https://www.must-good.com/normal?q=index-rescue-test', '/how-index-rescue-works', '/normal-article', '/index-rescue']:
            self.assertFalse(is_dummy_rescue_url(value), value)

    def test_three_domain_focus_preserves_other_hosts_and_real_name_accounts(self):
        from naver_kin import posting as pipeline, posting as measurement
        from threads_posting import posting as config
        self.assertEqual(pipeline.CF_BASE_DOMAINS[:3], PRIORITY_CF_DOMAINS)
        self.assertEqual(config.CF_DOMAINS_16[:3], PRIORITY_CF_DOMAINS)
        self.assertEqual(len(set(config.CF_DOMAINS_16)), 16)
        self.assertIn('www.baronote.kr', config.HOSTS)
        self.assertIn('www.woorinote.kr', measurement.HOSTS)
        ordered = sorted(['baronote.kr', 'must-pick.com', 'woorinote.kr', 'must-good.com'], key=domain_cpc_priority_rank)
        self.assertEqual(ordered[:3], list(PRIORITY_CF_DOMAINS))
        tree = ast.parse((ROOT / 'naver_blog_posting/posting.py').read_text(encoding='utf-8'))
        account_map = next((ast.literal_eval(n.value) for n in tree.body if isinstance(n, ast.Assign) and any((isinstance(t, ast.Name) and t.id == 'ACCOUNT_MAP' for t in n.targets))))
        for account in ['adinfo0905', 'stone0747']:
            self.assertEqual(account_map[account]['bridge_domains'][:3], ['www.' + x for x in PRIORITY_CF_DOMAINS])
        for account in ['soultin', 'soul5373', 'yoon_master']:
            self.assertEqual(account_map[account]['bridge_domains'], [])

    def test_final_outbound_attribution_rejects_dummy(self):
        with self.assertRaises(ValueError):
            _canonical('https://www.must-good.com/index-rescue-test', ['www.must-good.com'])
        self.assertEqual(_canonical('https://www.must-good.com/normal', ['www.must-good.com']), 'https://www.must-good.com/normal')

    def test_collector_filters_posts_without_mutating_remote_inventory(self):
        with patch.object(metrics, 'api', return_value={'posts': [{'slug': 'normal', 'title': 'Normal'}, {'slug': 'INDEX-RESCUE-test', 'title': 'Test'}]}) as api:
            result = metrics.public_inventory({'url': 'https://www.must-good.com/', 'site_id': 'must-good.com', 'platform': 'cf'})
        self.assertEqual(result['total'], 1)
        self.assertEqual(result['excludedDummyCount'], 1)
        self.assertEqual(api.call_args.args[1], 'GET')

    def test_sitemap_reports_raw_exclusions_and_never_claims_public_change(self):
        xml = b'<urlset><url><loc>https://www.must-good.com/normal</loc></url><url><loc>https://www.must-good.com/INDEX-RESCUE-test</loc></url></urlset>'
        with patch.object(metrics.requests, 'get', return_value=SimpleNamespace(status_code=200, content=xml)):
            result = metrics.sitemap_status({'url': 'https://www.must-good.com/', 'site_id': 'must-good.com', 'platform': 'cf'}, {})
        self.assertEqual((result['rawEntries'], result['entries'], result['excludedDummyCount']), (2, 1, 1))
        self.assertFalse(result['publicSitemapFiltered'])

    def test_indexing_submit_boundary_filters_and_holds_dirty_sitemap(self):
        site = {'url': 'https://www.must-good.com/', 'site_id': 'must-good.com', 'platform': 'cf'}
        good = site['url'] + 'normal'
        bad = site['url'] + '%69NDEX-RESCUE-test?utm_source=test'
        sitemap = {'status': 'available', 'url': site['url'] + 'sitemap.xml', 'locations': [good, bad]}
        with tempfile.TemporaryDirectory() as temporary, patch('dashboard.indexing_submissions.LEDGER', Path(temporary) / 'ledger.json'), patch.object(metrics, 'api') as google, patch.object(metrics.requests, 'get', return_value=SimpleNamespace(status_code=200, text='test-only')), patch.object(metrics.requests, 'post', return_value=SimpleNamespace(status_code=200)) as post:
            result = metrics.request_indexing(object(), site, {'indexnow_key': 'test-only'}, [good, bad], sitemap)
        google.assert_not_called()
        self.assertEqual(result['google']['status'], 'held_dummy_sitemap')
        self.assertEqual(post.call_args.kwargs['json']['urlList'], [good])
        self.assertEqual(result['excludedDummyCount'], 1)

    def test_cf_publication_rejects_dummy_before_write_or_credentials(self):
        from cf_posting import posting
        article = dict(title='Title', summary='Summary', category='category', topicSlug='index-rescue-test', contentHtml='<p>Text</p>')
        with tempfile.TemporaryDirectory() as folder, patch.object(posting, 'get_api_key') as credentials, patch.object(posting.requests, 'post') as post:
            with self.assertRaisesRegex(ValueError, 'Reserved'):
                posting.publish_basic_article('must-good.com', article, Path(folder))
            credentials.assert_not_called()
            post.assert_not_called()

    def test_auditor_dummy_branch_preserves_remote_post(self):
        from server import content_auditor as auditor
        ledger = {}
        queue = {'items': [{'url': 'https://www.must-good.com/index-rescue-test'}]}
        response = SimpleNamespace(status_code=200, json=lambda: {'posts': [{'id': 7, 'slug': 'index-rescue-test'}]})
        with patch.object(auditor, '_load_cf_api_keys', return_value={'must-good.com': 'test-only'}), patch.object(auditor, 'load_doctor_ledger', return_value=ledger), patch.object(auditor, 'load_remodeling_queue', return_value=queue), patch.object(auditor, 'save_doctor_ledger'), patch.object(auditor, 'save_remodeling_queue'), patch.object(auditor.requests, 'get', return_value=response), patch.object(auditor.requests, 'delete') as delete, patch.object(auditor.requests, 'put') as put:
            result = auditor.quarantine_dummy_and_gossip_posts_live()
        delete.assert_not_called()
        put.assert_not_called()
        self.assertEqual(result['deletedDummyCount'], 0)
        self.assertEqual(result['excludedDummyCount'], 1)
        self.assertEqual(queue['items'], [])

    def test_indexer_unknown_counts_do_not_reuse_legacy_dummy_aggregate(self):
        from common import auto_indexer
        site = {'site_id': 'must-good.com', 'url': 'https://www.must-good.com/', 'platform': 'cf'}
        good, bad = (site['url'] + 'normal', site['url'] + 'index-rescue-test')
        for complete in [False, True]:
            record = {'posts': {'urls': [good, bad], 'complete': complete, 'total': 999}, 'google': {'indexed': 999, 'urls': [{'url': bad, 'indexed': True}] + ([{'url': good, 'indexed': True}] if complete else [])}}
            snapshot = {'sites': {site['site_id']: record}}
            with patch.dict(sys.modules, {'metrics': metrics}), patch.object(metrics, 'inventory', return_value=[site]), patch.object(metrics, 'sitemap_status', return_value={'status': 'available', 'kind': 'urlset', 'locations': [good]}), patch.object(auto_indexer, '_check_rss_feed', return_value={'status': 'available'}), patch.object(auto_indexer, '_read_json', side_effect=lambda path, default: {} if path == auto_indexer.CONFIG_PATH else snapshot), patch.object(auto_indexer.requests, 'post') as post, patch.object(auto_indexer, '_atomic_write_json') as write:
                result = auto_indexer.run_auto_indexing(apply=False)
            self.assertEqual(result['totalInventoryPosts'], 1 if complete else None)
            self.assertEqual(result['totalIndexedPosts'], 1 if complete else None)
            self.assertEqual(result['totalSubmittedUrls'], 0)
            self.assertEqual(result['domains'][0]['excludedDummyCount'], 1)
            post.assert_not_called()
            write.assert_not_called()

    def test_prior_google_submitted_status_cannot_override_dirty_sitemap_hold(self):
        site = {'site_id': 'must-good.com', 'url': 'https://www.must-good.com/', 'platform': 'cf'}
        snapshot = {'sites': {'must-good.com': {'posts': {'urls': [site['url'] + 'normal']}, 'indexingRequest': {'google': {'status': 'submitted'}}}}}
        with patch.object(metrics, 'inventory', return_value=[site]), patch.object(metrics, 'read_json', side_effect=lambda path: {} if path == metrics.CONFIG else snapshot), patch.object(metrics, 'sitemap_status', return_value={'status': 'available', 'excludedDummyCount': 1}), patch.object(metrics, 'request_indexing', return_value={'google': {'status': 'held_dummy_sitemap'}}), patch.object(metrics, 'collector_lock', return_value=nullcontext(False)), patch.object(metrics, 'atomic_write') as write:
            results = metrics.submit_all_indexnow_and_sitemaps()
        self.assertEqual(results[0][2]['google']['status'], 'held_dummy_sitemap')
        write.assert_not_called()

    def test_indexer_preserves_prior_success_without_restamping_failed_attempt(self):
        from common import auto_indexer
        tree = ast.parse((ROOT / 'dashboard/common/auto_indexer.py').read_text(encoding='utf-8'))
        run = next((n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'run_auto_indexing'))
        process = next((n for n in run.body if isinstance(n, ast.FunctionDef) and n.name == '_process_domain'))
        good = 'https://www.must-good.com/normal'
        previous = {'status': 'submitted', 'submittedAt': '2026-10-10T01:00:00+09:00'}
        record = {'posts': {'urls': [good], 'complete': True}, 'indexingRequest': {'google': previous}}
        namespace = dict(vars(auto_indexer))
        namespace.update(config={}, snapshot={'sites': {'must-good.com': record}}, apply=True, dm=SimpleNamespace(sitemap_status=lambda *a: {'status': 'available', 'locations': [good]}, google_session=lambda *a: object(), request_indexing=lambda *a, **kw: {'google': {'status': 'not_collected'}}), _check_rss_feed=lambda *a: {})
        namespace['_validate_candidates'] = lambda site, urls: [{'url': url, 'valid': True} for url in urls]
        exec(compile(ast.Module(body=[process], type_ignores=[]), '<indexer-domain>', 'exec'), namespace)
        result = namespace['_process_domain']({'site_id': 'must-good.com', 'url': 'https://www.must-good.com/', 'platform': 'cf'})
        google = result['_indexingRequestObj']['google']
        self.assertEqual(google['status'], 'not_collected')
        self.assertIsNone(google['submittedAt'])
        self.assertEqual(google['previousSubmission'], previous)
if __name__ == '__main__':
    unittest.main()
