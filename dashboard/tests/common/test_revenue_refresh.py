import datetime as dt
from contextlib import contextmanager
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest

from common import revenue_refresh as refresh


class SourceError(ValueError):
    def __init__(self,status,reason):self.status=status;super().__init__(reason)


class RevenueRefreshTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        self.data=self.root/'dashboard/data';self.data.mkdir(parents=True)
        self.now=dt.datetime.now(refresh.KST);self.day=self.now.date().isoformat();self.month=self.day[:7];self.calls=0
        @contextmanager
        def lock(path):yield True
        def read(path):return json.loads(path.read_text()) if path.exists() else {}
        def collect(*args,**kwargs):self.calls+=1;return {'status':'collected','daily':{self.day:'1.25'}}
        self.backend=SimpleNamespace(collector_lock=lock,read_json=read,revenue_config=lambda:{'P_'+k:'configured' for k in ('ACCOUNT_ID','CLIENT_ID','CLIENT_SECRET','REFRESH_TOKEN')},
            source=lambda key,cat,label,currency,scope,**extra:dict(id=key,category=cat,currency=currency,label=label,scope=scope,**extra),
            ADPOST_ACCOUNTS=(),adsense=collect,coupang=collect,affiliate_configuration=lambda *a:{},RevenueSourceError=SourceError,
            money=float,deduplicate_adpost_sources=lambda rows:None)
        (self.data/'metrics-config.json').write_text(json.dumps({'adsense_accounts':{'sj':{'sites':['site.test'],'env_prefix':'P'}}}))
    def test_success_persists_immediately_and_repeated_tick_respects_due_time(self):
        result=refresh.collect_once(self.root,self.now,self.backend)
        self.assertEqual(result['sources']['adsense-sj'],'collected')
        self.assertEqual(self.calls,2)
        refresh.collect_once(self.root,self.now,self.backend);self.assertEqual(self.calls,2)
        rows=json.loads((self.data/'revenue.json').read_text())['months'][self.month]['sources']
        record=next(r for r in rows if r['id']=='adsense-sj')
        self.assertEqual(record['daily'][self.day],'1.25');self.assertIn('lastSuccessAt',record)
    def test_failure_keeps_last_success_and_money_without_relabeling_as_fresh(self):
        old={'id':'adsense-sj','daily':{self.day:'2.00'},'checkedAt':'2026-10-20T00:00:00+09:00'}
        (self.data/'revenue.json').write_text(json.dumps({'months':{self.month:{'sources':[old]}}}))
        def fail(*args,**kwargs):raise RuntimeError('private-token-do-not-store')
        self.backend.adsense=fail;refresh.collect_once(self.root,self.now,self.backend)
        raw=(self.data/'revenue.json').read_text();record=json.loads(raw)['months'][self.month]['sources'][0]
        self.assertEqual(record['daily'],old['daily']);self.assertEqual(record['checkedAt'],old['checkedAt'])
        self.assertEqual(record['status'],'error');self.assertNotIn('private-token',raw)
    def test_busy_does_not_collect(self):
        @contextmanager
        def lock(path):yield False
        self.backend.collector_lock=lock
        self.assertEqual(refresh.collect_once(self.root,self.now,self.backend),{'status':'busy'})
        self.assertEqual(self.calls,0)

if __name__=='__main__':unittest.main()
