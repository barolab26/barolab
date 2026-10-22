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

if __name__ == "__main__":
    unittest.main()
