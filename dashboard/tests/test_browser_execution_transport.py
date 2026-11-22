"""Do not replay uncertain browser effects; preserve ESM and Unicode transport."""
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from common import ego_taskspace as ego

class BrowserTransport(unittest.TestCase):
    def run_with(self, effect):
        with tempfile.TemporaryDirectory() as temporary:
            with patch.object(ego, 'find_ego_cli', return_value=Path('ego-browser.exe')), \
                 patch.object(ego, '_ego_cli_lock_path', return_value=Path(temporary)/'lock'), \
                 patch.object(ego.subprocess, 'run', side_effect=effect) as run:
                return run, ego.run_ego_mjs('await Promise.resolve("한글");')

    def test_file_module_preserves_top_level_await_and_unicode(self):
        def execute(args, **kwargs):
            from urllib.parse import unquote,urlparse
            self.assertEqual(args[1:3], ['nodejs','-e'])
            self.assertNotIn('input', kwargs)
            uri=args[3].split("'")[1]
            filename=unquote(urlparse(uri).path)
            if filename.startswith('/') and len(filename)>2 and filename[2]==':':filename=filename[1:]
            self.assertIn('await Promise.resolve("한글")',Path(filename).read_text(encoding='utf-8'))
            return subprocess.CompletedProcess(args,0,'BAROLAB_EGO_JSON:{"ok":true}','')
        run,result=self.run_with(execute)
        self.assertTrue(result['ok']);self.assertEqual(run.call_count,1)

    def test_timeout_is_not_replayed(self):
        count=[]
        def execute(args, **kwargs):
            count.append(args);raise subprocess.TimeoutExpired(args,1)
        with self.assertRaises(subprocess.TimeoutExpired):self.run_with(execute)
        self.assertEqual(len(count),1)

    def test_user_stop_is_not_replayed(self):
        count=[]
        def execute(args, **kwargs):
            count.append(args);return subprocess.CompletedProcess(args,5,'','user control')
        with self.assertRaisesRegex(RuntimeError,'code 5'):self.run_with(execute)
        self.assertEqual(len(count),1)

    def test_shared_ego_9440_gc_blank_tabs_is_noop_without_requests_websocket_or_tab_close(self):
        from common import ubuntu_naver_browser
        with patch.dict('sys.modules', {'requests': None, 'websocket': None}):
            self.assertEqual(ubuntu_naver_browser.gc_blank_tabs(9440), 0)
            self.assertEqual(ubuntu_naver_browser.gc_blank_tabs('9440'), 0)

if __name__=='__main__':unittest.main()
