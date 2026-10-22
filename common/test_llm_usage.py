import datetime as dt
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from concurrent.futures import ThreadPoolExecutor

from common import llm_usage as usage


class UsageTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
    def ledger(self):return json.loads((self.root/'server/data/llm_usage_ledger.json').read_text())
    def test_nested_adapters_are_counted_once_and_headers_are_allowlisted(self):
        @usage.metered
        def inner(prompt,**kwargs):
            usage.report_response({'usage':{'input_tokens':12,'output_tokens':3}},
                {'x-ratelimit-remaining-requests':'20','Authorization':'secret','Set-Cookie':'private'},200,'actual')
            return {'ok':True}
        @usage.metered
        def outer(prompt,**kwargs):return inner(prompt,provider='codex',model='requested')
        with patch.object(usage,'ROOT',self.root):outer('private prompt',provider='codex',model='requested')
        ledger=self.ledger();row=ledger['byModel']['codex:actual']
        self.assertEqual((row['calls'],row['inputTokens'],row['outputTokens']),(1,12,3))
        self.assertEqual(row['rateLimitHeaders'],{'x-ratelimit-remaining-requests':'20'})
        self.assertEqual(ledger['active'],{})
        self.assertNotIn('private',json.dumps(ledger));self.assertNotIn('secret',json.dumps(ledger))
    def test_failure_preserves_exception_counts_quota_and_unknown_tokens(self):
        @usage.metered
        def failed(prompt,**kwargs):raise RuntimeError('HTTP 429 secret error body')
        with patch.object(usage,'ROOT',self.root),self.assertRaisesRegex(RuntimeError,'429'):
            failed('secret prompt',provider='gemini',model='flash')
        row=self.ledger()['byModel']['gemini:flash']
        self.assertEqual((row['errors'],row['rateLimited'],row['usageReportedCalls']),(1,1,0))
        self.assertNotIn('secret',json.dumps(self.ledger()))
    def test_concurrent_calls_accumulate_without_loss(self):
        @usage.metered
        def call(prompt,**kwargs):
            usage.report_response(events=[{'type':'turn.completed','usage':{'input_tokens':10,'output_tokens':2}}]);return 1
        with patch.object(usage,'ROOT',self.root),ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(lambda _:call('x',provider='codex',model='m'),range(30)))
        row=self.ledger()['byModel']['codex:m']
        self.assertEqual((row['calls'],row['success'],row['inputTokens'],row['outputTokens']),(30,30,300,60))
    def test_kst_midnight_resets_daily_counters(self):
        call=dict(id='x',provider='p',model='m',startedAt='2026-10-22T23:59:00+09:00',inputTokens=1,outputTokens=2,
                  usageReports=1,latencyMs=1,rateLimitHeaders={})
        now=dt.datetime(2026,10,22,23,59,tzinfo=usage.KST)
        usage.record_call(call,'completed',root=self.root,now=now)
        usage.record_call(call,'failed',root=self.root,now=now+dt.timedelta(minutes=2))
        row=self.ledger()['byModel']['p:m'];self.assertEqual((row['calls'],row['success'],row['errors']),(1,0,1))

if __name__=='__main__':unittest.main()
