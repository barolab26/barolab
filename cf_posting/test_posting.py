"""Canonical publishing entry point and legacy import compatibility."""
import importlib
import unittest
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


class PostingEntryPointTests(unittest.TestCase):
    def test_canonical_entry_point_compiles(self):
        path = Path(__file__).with_name("posting.py")
        compile(path.read_text(encoding="utf-8"), str(path), "exec")

    def test_canonical_import_and_minimal_layout(self):
        canonical=importlib.import_module("cf_posting.posting")
        root=Path(__file__).parent
        self.assertEqual(Path(canonical.__file__),root/'posting.py')
        self.assertFalse((root/'pipeline_runner.py').exists())
        self.assertFalse((root/'data').exists())




class BasicPublicationTests(unittest.TestCase):
    def setUp(self):
        import tempfile
        from unittest.mock import patch
        from cf_posting import posting
        self.posting = posting
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.article = dict(title='Basic article', summary='A useful summary', category='General',
                            topicSlug='basic-article', contentHtml='<h2>Answer</h2><p>Useful answer.</p>')
        for name, value in [('registered_categories', ['General']), ('published_inventory', []), ('get_api_key', 'test-key')]:
            patcher = patch.object(posting, name, return_value=value)
            patcher.start(); self.addCleanup(patcher.stop)

    def test_only_format_checks_precede_post_and_public_http_verification(self):
        from unittest.mock import Mock, patch
        self.article['contentHtml'] += '<table><tr><td>보존할 값</td></tr></table>'
        response = Mock(status_code=201)
        response.json.return_value = {'post': {'id': 12, 'slug': 'basic-article'}}
        public = Mock(status_code=200, text='<h1>Basic article</h1>')
        with patch.object(self.posting.requests, 'post', return_value=response) as post, \
             patch.object(self.posting.requests, 'get', return_value=public):
            self.assertFalse(hasattr(self.posting, 'Handoff'))
            receipt = self.posting.publish_basic_article('example.com', self.article, self.folder)
            self.assertTrue(receipt['publicPublicationVerified'])
            self.assertEqual(receipt['httpStatus'], 200)
            self.assertEqual(post.call_count, 1)
            self.assertIn('cf-responsive-table-v1', post.call_args.kwargs['json']['content'])
            self.assertIn('보존할 값', post.call_args.kwargs['json']['content'])
            self.posting.publish_basic_article('example.com', self.article, self.folder)
            self.assertEqual(post.call_count, 1)

    def test_duplicate_is_not_submitted(self):
        from unittest.mock import patch
        with patch.object(self.posting, 'published_inventory', return_value=[dict(id=1, title='Basic article', slug='basic-article')]), \
             patch.object(self.posting.requests, 'post') as post:
            with self.assertRaises(ValueError):
                self.posting.publish_basic_article('example.com', self.article, self.folder)
            post.assert_not_called()

    def test_ambiguous_submission_is_not_repeated(self):
        from unittest.mock import patch
        import json
        (self.folder / 'publication-receipt.json').write_text(json.dumps({'state': 'submission_unknown'}))
        with patch.object(self.posting.requests, 'post') as post:
            with self.assertRaises(RuntimeError):
                self.posting.publish_basic_article('example.com', self.article, self.folder)
            post.assert_not_called()

    def test_active_html_and_malformed_slug_are_rejected(self):
        for field, value in [('contentHtml', '<p onclick="bad()">Hello</p>'), ('topicSlug', '../unsafe')]:
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.posting.validate_basic_article({**self.article, field: value})

class ProgressContractTests(unittest.TestCase):
    def test_progress_writes_schedule_and_expected_frontend_variable(self):
        import tempfile,json
        from unittest.mock import patch
        from cf_posting import posting as p
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);schedule=root/'daily_schedule.json'
            schedule.write_text(json.dumps({'items':[{'domain':'example.com','id':'site','status':'waiting'}]}))
            with patch.object(p,'SCHEDULE_JSON',schedule),patch.object(p,'STATE_JSON',root/'state.json'),patch.object(p,'STATUS_JS',root/'state.js'):
                p.basic_progress('example.com',2,'Research',30,'Collecting facts')
            self.assertIn('window.__PIPELINE_STATUS__', (root/'state.js').read_text())

class ScheduleAdmissionTests(unittest.TestCase):
    def test_future_slots_and_retry_backoff_do_not_launch_early(self):
        from cf_posting import posting as p
        now=p.datetime.datetime(2026,10,23,0,30,tzinfo=p.KST)
        self.assertFalse(p.slot_due({'status':'waiting','scheduledTime':'10:20'},now))
        self.assertFalse(p.slot_due({'status':'failed','nextRetryAt':'2026-10-23T00:35:00+09:00'},now))
        self.assertTrue(p.slot_due({'status':'failed','nextRetryAt':'2026-10-23T00:25:00+09:00'},now))

class ResponsiveTableTests(unittest.TestCase):
    def test_styles_preserve_content_links_and_merged_cells_and_are_idempotent(self):
        from common.cf_tables import style_tables,content_signature,VERSION
        from bs4 import BeautifulSoup
        html='<h2>지원금 비교</h2><table style="width:2000px"><tr><th colspan="2">기준</th></tr><tr><td rowspan="2">한글/긴문자열</td><td><a href="https://example.org/source">근거</a></td></tr></table><p>출처: <a href="https://example.org/official">공식 자료</a></p>'
        result=style_tables(html);doc=BeautifulSoup(result,'html.parser')
        self.assertEqual(content_signature(result),content_signature(html))
        self.assertEqual(style_tables(result),result)
        self.assertEqual(len(doc.select('[data-cf-table-style]')),1)
        self.assertIn('overflow-x:auto',doc.table.parent['style'])
        self.assertIn('width:100%',doc.table['style'])
        self.assertIn('background:#f8fafc',doc.th['style'])
        self.assertIn('padding:10px 14px',doc.td['style'])
        self.assertEqual(doc.caption.get_text(),'지원금 비교')
        self.assertIn('font-size:13px',doc.find('p')['style'])

    def test_existing_captions_and_scroll_wrappers_are_preserved_without_fake_sources(self):
        from common.cf_tables import style_tables
        from bs4 import BeautifulSoup
        html='<div style="overflow-x: auto"><table><caption>실제 제목</caption><tr><td>값</td></tr></table></div>'
        result=style_tables(html);doc=BeautifulSoup(result,'html.parser')
        self.assertEqual(len(doc.find_all('div')),1)
        self.assertEqual(doc.caption.get_text(),'실제 제목')
        self.assertNotIn('출처',result)
        self.assertEqual(style_tables('<p>표 없음</p>'),'<p>표 없음</p>')

class TableRepairBoundaryTests(unittest.TestCase):
    def test_cache_purge_targets_only_verified_article_urls(self):
        from unittest.mock import patch,Mock
        from common import cf_tables as tables
        posts=[{'domain':'example.com','url':'https://www.example.com/original'}]
        for success in (True,False):
            response=Mock();response.json.return_value={'success':success}
            with patch('common.content_maintenance.cache_binding',return_value=('own-zone',{'fixture':'auth'})),patch('common.content_maintenance.deployed_cache_urls',side_effect=lambda domain,urls,binding:urls) as expand,patch('requests.post',return_value=response) as purge:
                result=tables.purge_repaired_posts(posts)
            self.assertEqual(result['example.com']['status'],'confirmed' if success else 'failed')
            self.assertEqual(set(purge.call_args.kwargs['json']),{'files'})
            self.assertEqual(expand.call_args.args[1],['https://www.example.com/original','https://www.example.com/posts/original','https://example.com/original'])

    def test_remote_repair_backs_up_and_reads_back_the_same_article(self):
        import datetime as dt,tempfile
        from unittest.mock import patch,Mock
        from common import cf_tables as tables
        from cf_posting import posting
        body='<table><tr><td>원문</td></tr></table>'
        original={'id':1,'title':'원제목','slug':'original','category':'정책','status':'published','content':body}
        styled=tables.style_tables(body)
        item={**original,'created_at':dt.datetime.now(dt.timezone.utc).isoformat()}
        def response(post):
            result=Mock(status_code=200,text=tables.VERSION);result.json.return_value={'post':post};return result
        for changed,expired_auth in ((False,False),(True,False),(False,True)):
            with self.subTest(concurrent=changed,expired_auth=expired_auth),tempfile.TemporaryDirectory() as directory:
                latest={**original,'updated_at':'changed'} if changed else original
                first=response({});first.status_code=401 if expired_auth else 200
                login=Mock();login.json.return_value={'token':'fixture-token'}
                with patch.object(tables,'purge_repaired_posts',return_value={'example.com':{'status':'confirmed'}}),patch.object(posting,'published_inventory',return_value=[item]),patch.object(posting,'cleaner_lock') as lock,patch.object(posting,'get_api_key',return_value='test-only'),patch('requests.get',side_effect=[response(original),response(latest),response({**original,'content':styled}),response({})]),patch('requests.put',side_effect=[first,response({})]) as put,patch('requests.post',return_value=login),patch('dotenv.dotenv_values',return_value={'EXAMPLE_CF_ADMIN_PASSWORD':'fixture-password'}):
                    lock.return_value.__enter__.return_value=True
                    folder,report=tables.repair_recent(root=Path(directory),domains=['example.com'])
                self.assertTrue((folder/'example.com/1/original.json').exists())
                if changed:
                    put.assert_not_called();self.assertEqual(len(report['errors']),1)
                else:
                    self.assertEqual(put.call_args.kwargs['json']['content'],styled)
                    self.assertEqual(put.call_args.kwargs['json']['title'],'원제목')
                    self.assertTrue(report['posts'][0]['publicStyleVerified'])
                    self.assertEqual(report['errors'],[])
                    self.assertEqual(put.call_count,2 if expired_auth else 1)
                    if expired_auth:self.assertEqual(put.call_args.kwargs['headers'],{'Authorization':'Bearer fixture-token'})

if __name__ == "__main__":
    unittest.main()
