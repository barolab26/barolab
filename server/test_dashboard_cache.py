import ast
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import threading
import unittest
from unittest.mock import patch

from fastapi import HTTPException
from server.dashboard_cache import ReadCache, compact_metrics


class DashboardCacheTests(unittest.TestCase):
    def test_compact_metrics_keeps_unknown_values_dates_and_drops_page_details(self):
        data = {'checkedAt': 'old-date', 'indexing': {'indexed': None},
            'trafficAnalysis': {'today': 'source-date', 'sites': [{'site': {'site_id': 'example'},
                'ga4': {'stale': True, 'periods': {'today': {'sessions': None, 'start': 'source-date',
                    'pages': ['large detail']}}}}]}, 'contentAudit': {'counts': {'not_indexed': 2}, 'rows': ['large detail']}}
        result = compact_metrics(data)
        self.assertIsNone(result['indexing']['indexed'])
        self.assertEqual(result['trafficAnalysis']['today'], 'source-date')
        ga4 = result['trafficAnalysis']['sites'][0]['ga4']
        self.assertTrue(ga4['stale'])
        self.assertIsNone(ga4['periods']['today']['sessions'])
        self.assertNotIn('pages', ga4['periods']['today'])
        self.assertNotIn('rows', result['contentAudit'])
        self.assertIn('rows', data['contentAudit'])

    def test_concurrent_read_does_not_repeat_build_or_wait_in_http_pool(self):
        cache = ReadCache()
        started, release = threading.Event(), threading.Event()
        value = {'stats': {'total': 7}}
        def build():
            started.set()
            self.assertTrue(release.wait(3))
            return value
        with ThreadPoolExecutor(max_workers=1) as executor:
            first = executor.submit(cache.get, 'graph', build)
            self.assertTrue(started.wait(3))
            try:
                with self.assertRaises(HTTPException) as error:
                    cache.get('graph', lambda: self.fail('duplicate build'))
                self.assertEqual(error.exception.status_code, 503)
            finally:
                release.set()
            self.assertIs(first.result(3), value)
        self.assertIs(cache.get('graph', lambda: self.fail('cache miss')), value)

    def test_expiry_bounded_entries_and_failed_build_recovery(self):
        cache = ReadCache(ttl=30, capacity=2)
        with patch('server.dashboard_cache.time.monotonic', return_value=100):
            cache.get('a', lambda: 1)
            cache.get('b', lambda: 2)
            cache.get('c', lambda: 3)
            self.assertEqual(list(cache.values), ['b', 'c'])
        with patch('server.dashboard_cache.time.monotonic', return_value=131):
            with self.assertRaises(ValueError):
                cache.get('b', lambda: (_ for _ in ()).throw(ValueError('failed')))
            self.assertEqual(cache.get('b', lambda: 4), 4)

    def test_metrics_read_does_not_verify_external_publication(self):
        source = (Path(__file__).parent / 'main.py').read_text()
        node = next(n for n in ast.parse(source).body if isinstance(n, ast.FunctionDef) and n.name == 'get_metrics')
        self.assertFalse(any(isinstance(n, ast.Name) and n.id == 'reconcile' for n in ast.walk(node)))


if __name__ == '__main__':
    unittest.main()
