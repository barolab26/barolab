import json
import tempfile
import unittest
from pathlib import Path

from cf_posting.searchadvisor import complete_crawl, record_site, reserve_crawl, queue_crawl_candidates, record_history_baseline, now, locked_ledger
from cf_posting.searchadvisor_ui import parse_visible_history, paused_reason
from unittest.mock import patch, Mock


class SearchAdvisorLedgerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "ledger.json"
        queue_crawl_candidates(['https://www.must-good.com/'+x for x in ('article','one','two')],
            evidence={'checkedAt':now(),'source':'actual canonical proof'}, path=self.path)
        self.baseline([])

    def baseline(self, urls):
        return record_history_baseline(urls, scope_sites=['https://www.must-good.com'], complete=True,
            evidence={'source':'all visible site histories','checkedAt':now(),
                      'siteListComplete':True,'allHistoryPagesComplete':True}, path=self.path)


    def test_submission_is_not_indexing_and_duplicate_is_blocked(self):
        url = "https://www.must-good.com/article"
        reserve_crawl(url, path=self.path)
        complete_crawl(url, status="requested", evidence="UI success row", path=self.path)
        row = json.loads(self.path.read_text())["crawlRequests"][0]
        self.assertIsNone(row["indexed"])
        with self.assertRaisesRegex(ValueError, "already"):
            reserve_crawl(url, path=self.path)

    def test_external_history_and_unknown_reservations_consume_cap(self):
        reserve_crawl("https://www.must-good.com/one", external_today_count=49, path=self.path)
        with self.assertRaisesRegex(ValueError, "cap"):
            reserve_crawl("https://www.must-good.com/two", external_today_count=49, path=self.path)

    def test_registration_and_ownership_do_not_claim_indexing(self):
        record_site("must-good.com", registration="registered", ownership="verified",
                    evidence="visible site list", path=self.path)
        site = json.loads(self.path.read_text())["sites"]["must-good.com"]
        self.assertEqual(site["registration"]["status"], "registered")
        self.assertIsNone(site["indexed"])

    def test_private_or_noncanonical_urls_rejected(self):
        for url in ["https://example.com/x", "https://www.must-good.com/x?token=secret",
                    "https://user:pass@www.example.com/x"]:
            with self.assertRaises(ValueError):
                reserve_crawl(url, path=self.path)


    def test_baseline_required_monotonic_and_own_not_double_counted(self):
        fresh=Path(self.tmp.name)/'fresh.json'
        with self.assertRaisesRegex(ValueError,'history unconfirmed'):
            reserve_crawl('https://www.must-good.com/article',path=fresh)
        reserve_crawl('https://www.must-good.com/article',path=self.path)
        self.assertEqual(self.baseline(['https://www.must-good.com/article','https://legacy.example/x'])['externalCount'],1)
        self.assertEqual(self.baseline([])['externalCount'],1)

    def test_repeated_url_history_rows_each_consume_budget(self):
        baseline=self.baseline(['https://legacy.example/x']*10)
        self.assertEqual(baseline['externalCount'],10)
        self.assertEqual(baseline['observedRequestCount'],10)
        self.assertEqual(self.baseline(['https://legacy.example/x']*5)['externalCount'],10)

    def test_today_fifty_blocks_consumer_before_browser_connection(self):
        from cf_posting.searchadvisor_ui import run
        self.baseline(['https://legacy.example/x']*50)
        with patch('cf_posting.searchadvisor_ui._runtime') as runtime:
            result=run(apply=True,path=self.path)
        self.assertEqual(result['remaining'],0)
        self.assertFalse(result['browserConnected']);runtime.assert_not_called()

    def test_history_truncation_empty_and_captcha(self):
        self.assertEqual(parse_visible_history([], '\ub370\uc774\ud130\uac00 \uc5c6\uc2b5\ub2c8\ub2e4.', '2026-10-19'), [])
        with self.assertRaises(ValueError): parse_visible_history([], 'loading', '2026-10-19')
        rows=[f'{i} https://www.must-good.com/{i} 2026.10.19' for i in range(50)]
        with self.assertRaisesRegex(ValueError,'truncated'):parse_visible_history(rows,'','2026-10-19')
        rows[-1]='50 https://www.must-good.com/old 2026.10.18'
        self.assertEqual(len(parse_visible_history(rows,'','2026-10-19')),49)
        self.assertEqual(paused_reason('captcha'),'blocked_captcha')

    def test_actual_two_digit_ui_dates_preserve_duplicate_requests(self):
        rows=['1 https://www.tripmarvel.com/article 26.10.19 01:12:23',
              '2 https://www.tripmarvel.com/article 26.10.19 00:51:48',
              '3 https://www.tripmarvel.com/old 26.10.18 23:59:00']
        self.assertEqual(parse_visible_history(rows,'','2026-10-19'),
                         ['https://www.tripmarvel.com/article']*2)
        with self.assertRaises(ValueError):
            parse_visible_history(['https://www.tripmarvel.com/x 26.13.19'],'','2026-10-19')

    def test_existing_indexing_pipeline_only_consumes_explicit_authorization(self):
        from common.auto_indexer import _consume_searchadvisor_queue
        policy={'searchadvisor':{'mode':'authorized_visible_ui','request_authorized':True,'account':'soultin'}}
        with patch('cf_posting.searchadvisor_ui.run',return_value={'status':'daily_budget_exhausted','submitted':0}) as runner:
            _consume_searchadvisor_queue({},apply=True)
            _consume_searchadvisor_queue(policy,apply=False)
            runner.assert_not_called()
            result=_consume_searchadvisor_queue(policy,apply=True)
        runner.assert_called_once_with(apply=True)
        self.assertEqual(result['status'],'daily_budget_exhausted')

    def test_lock_failure_preserves_state_and_releases(self):
        before=self.path.read_bytes()
        with self.assertRaises(RuntimeError):
            with locked_ledger(self.path) as state:
                state['bad']=True
                raise RuntimeError('abort')
        self.assertEqual(before,self.path.read_bytes())
        self.baseline([])

    def test_stale_proof_refresh_and_terminal_conflict(self):
        url='https://www.must-good.com/article'
        queue_crawl_candidates([url],evidence={'checkedAt':'2020-01-01T00:00:00+09:00','source':'proof'},path=self.path)
        with self.assertRaisesRegex(ValueError,'stale'):reserve_crawl(url,path=self.path)
        queue_crawl_candidates([url],evidence={'checkedAt':now(),'source':'new proof'},path=self.path)
        reserve_crawl(url,path=self.path)
        complete_crawl(url,status='request_received',evidence='UI row',path=self.path)
        complete_crawl(url,status='request_received',evidence='same',path=self.path)
        with self.assertRaisesRegex(ValueError,'Conflicting'):complete_crawl(url,status='failed',evidence='different',path=self.path)

    def test_reservation_precedes_click_captcha_stops(self):
        from cf_posting.searchadvisor_ui import submit_visible
        page=Mock();page.url='https://searchadvisor.naver.com/console/site/request/crawl'
        events=[]
        page.get_by_role.return_value.click.side_effect=lambda **kw:events.append('click')
        def reserve(*args,**kw):
            reserve_crawl(*args,**kw);events.append('reserve')
        with patch('cf_posting.searchadvisor_ui._history',return_value=[]), patch('cf_posting.searchadvisor_ui._check'), patch('cf_posting.searchadvisor_ui._text',return_value='captcha'), patch('cf_posting.searchadvisor_ui.ledger.reserve_crawl',side_effect=reserve):
            result=submit_visible(page,'https://www.must-good.com/article',path=self.path)
        self.assertEqual(result,'blocked_captcha');self.assertEqual(events,['reserve','click'])


if __name__ == "__main__":
    unittest.main()
