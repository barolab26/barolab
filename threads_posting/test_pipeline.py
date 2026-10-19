import copy
from datetime import datetime,timezone,timedelta
import hashlib,json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from . import config,pipeline,scheduler

class LedgerTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.db=Path(self.temp.name)/'ledger.db'
        self.c=config.defaults();self.now=datetime.now(timezone.utc);self.day=self.now.astimezone(pipeline.KST).date().isoformat()
        self.c.update(enabled=True,activationApproved=True,activatedAt=(self.now-timedelta(days=1)).isoformat(),endsAt=(self.now+timedelta(days=13)).isoformat(),startDate=self.day,endDate=self.day)
        self.c['connection']={'connected':True,'account_verified':True,'account_key':'mustpickinfo','publishReady':True}
        source_patch=patch('threads_posting.authoring.article_snapshot',return_value=self.document()['source']);source_patch.start();self.addCleanup(source_patch.stop)
    def document(self,id='one',slot='00:00',mode='cf_inbound'):
        source={'url':'https://www.must-pick.com/example','body':'Observed public source','body_sha256':hashlib.sha256(b'Observed public source').hexdigest()}
        attr=None if mode=='warmup' else pipeline.receipt('mustpickinfo',source['url'],self.day,slot,id)
        parts=[{'kind':'main','text':'솔직히 이거 몰라서 그냥 지나치면 손해거든! 확인 순서 3줄 요약 👇'}]
        if mode!='warmup':
            parts.append({'kind':'followup','text':'제가 직접 정리·운영하는 블로그에 상세 가이드를 정리했습니다.\n'+attr['outboundUrl']})
        d={'schema':'threads-document-v1','content_id':id,'account_key':'mustpickinfo','publication_date':self.day,'slot':slot,'mode':mode,'followup_delay_seconds':120,'title':'Example','source':source,'attribution':attr,'parts':parts}
        d['review']={'approved':True,'reason':'supported','claims':[{'claim':'확인 순서','quote':'Observed','source_url':source['url']}],'checks':dict.fromkeys(pipeline.REVIEW_KEYS,True),'binding':pipeline.binding(d)};return d
    def test_changed_schedule_invalidates_review(self):
        d=self.document();d['slot']='10:00'
        with self.assertRaises(ValueError):pipeline.import_document(d,self.c,self.db)
    def test_missing_review_checks_block(self):
        d=self.document();d['review']['checks']={'anything':True}
        with self.assertRaises(ValueError):pipeline.validate_document(d,self.c)
    def test_zero_links_in_main_post_rule_enforced(self):
        d=self.document()
        d['parts'][0]['text']='본문에 링크가 들어가면 차단됩니다 https://www.must-pick.com/example'
        d['review']['binding']=pipeline.binding(d)
        with self.assertRaisesRegex(ValueError,'Zero links in main post required'):
            pipeline.validate_document(d,self.c)
    def test_warmup_mode_allows_zero_outbound_links(self):
        d=self.document(id='warm1',slot='08:00',mode='warmup')
        self.assertEqual(len(d['parts']),1)
        self.assertIsNone(d['attribution'])
        pipeline.validate_document(d,self.c)
        pipeline.import_document(d,self.c,self.db)
    def test_future_slot_blocks(self):
        d=self.document(slot='23:59');pipeline.import_document(d,self.c,self.db)
        with pipeline.connect(self.db) as db:
            with self.assertRaisesRegex(RuntimeError,'slot_not_due'):pipeline.begin_send(db,'one-0',self.c,datetime.fromisoformat(self.day+'T00:01:00+09:00'))
    def test_cap_consumes_unknown_and_intent(self):
        c2=dict(self.c,mainDailyCap=2)
        for id in ('one','two','three'):pipeline.import_document(self.document(id),c2,self.db)
        with pipeline.connect(self.db) as db:
            pipeline.begin_send(db,'one-0',c2);pipeline._update(db,'one-0','submitted_unknown');pipeline.begin_send(db,'two-0',c2)
            with self.assertRaisesRegex(RuntimeError,'daily_cap'):pipeline.begin_send(db,'three-0',c2)
    def test_changed_ledger_text_blocked(self):
        pipeline.import_document(self.document(),self.c,self.db)
        with pipeline.connect(self.db) as db:
            db.execute("UPDATE parts SET text='tampered' WHERE part_id='one-0'")
            with self.assertRaisesRegex(RuntimeError,'ledger_document_mismatch'):pipeline.begin_send(db,'one-0',self.c)
    def test_unknown_not_reposted(self):
        pipeline.import_document(self.document(),self.c,self.db)
        class API:
            @staticmethod
            def connection_status(c):return c['connection']
            @staticmethod
            def submit_part(c,p,callback):callback();raise TimeoutError()
        with self.assertRaises(TimeoutError):pipeline.publish('one-0',self.c,self.db,API)
        with self.assertRaisesRegex(RuntimeError,'never_resend'):pipeline.publish('one-0',self.c,self.db,API)
        with pipeline.connect(self.db) as db:self.assertEqual(db.execute("SELECT state FROM parts WHERE part_id='one-0'").fetchone()[0],'submitted_unknown')
    def test_public_verifier_failure_retains_api_id(self):
        pipeline.import_document(self.document(),self.c,self.db)
        class API:
            @staticmethod
            def connection_status(c):return c['connection']
            @staticmethod
            def submit_part(c,p,callback):callback();return {'platform_id':'123','permalink':None}
            @staticmethod
            def verify_public(*args):raise TimeoutError()
        result=pipeline.publish('one-0',self.c,self.db,API)
        self.assertEqual(result['state'],'api_submitted');self.assertEqual(result['platform_id'],'123')
        with pipeline.connect(self.db) as db:
            row=db.execute("SELECT * FROM parts WHERE part_id='one-0'").fetchone();self.assertIsNone(row['published_at']);self.assertIsNotNone(row['api_submitted_at']);self.assertEqual(row['publication_time_basis'],'unknown')
    def test_trial_starts_only_activation(self):
        c=config.defaults();self.assertIsNone(c['activatedAt']);c['connection']=self.c['connection'];activated=config.activate(c,approved=True,now=self.now)
        self.assertEqual(datetime.fromisoformat(activated['endsAt'])-datetime.fromisoformat(activated['activatedAt']),timedelta(days=14))
    def test_disabled_tick_no_external_call(self):
        c=config.defaults();path=Path(self.temp.name)/'config.json';config.save(c,path)
        with patch('threads_posting.pipeline.reconcile',side_effect=AssertionError('network')),patch('threads_posting.scheduler.lock'):
            self.assertEqual(scheduler.tick(path,self.db,Path(self.temp.name)/'snapshot.json')['state'],'noop')
    def test_concurrent_remaining_cap_only_one_claims(self):
        import concurrent.futures,threading
        c2=dict(self.c,mainDailyCap=2)
        for id in ('one','two','three'):pipeline.import_document(self.document(id),c2,self.db)
        with pipeline.connect(self.db) as db:pipeline.begin_send(db,'one-0',c2)
        barrier=threading.Barrier(2)
        def claim(id):
            with pipeline.connect(self.db) as db:
                barrier.wait()
                try:pipeline.begin_send(db,id,c2);return 'sent'
                except RuntimeError as exc:return str(exc)
        with concurrent.futures.ThreadPoolExecutor(2) as pool:results=list(pool.map(claim,('two-0','three-0')))
        self.assertCountEqual(results,['sent','daily_cap'])
    def test_followup_requires_verified_parent_and_delay(self):
        d=self.document();pipeline.import_document(d,self.c,self.db)
        with pipeline.connect(self.db) as db:
            with self.assertRaisesRegex(RuntimeError,'verified_parent'):pipeline.begin_send(db,'one-1',self.c)
            pipeline._update(db,'one-0','published_verified',platform_id='123',published_at=(self.now-timedelta(seconds=30)).isoformat())
            with self.assertRaisesRegex(RuntimeError,'followup_delay_not_elapsed'):pipeline.begin_send(db,'one-1',self.c,now=self.now)
            pipeline._update(db,'one-0','published_verified',platform_id='123',published_at=(self.now-timedelta(seconds=135)).isoformat())
            pipeline.begin_send(db,'one-1',self.c,now=self.now)
    def test_final_config_disabled_before_callback(self):
        pipeline.import_document(self.document(),self.c,self.db)
        class API:
            @staticmethod
            def connection_status(c):return c['connection']
            @staticmethod
            def submit_part(c,p,callback):callback();raise AssertionError('must not publish')
        with self.assertRaisesRegex(RuntimeError,'disabled'):pipeline.publish('one-0',self.c,self.db,API,config_loader=lambda:dict(self.c,enabled=False))
        with pipeline.connect(self.db) as db:self.assertEqual(db.execute("SELECT state FROM parts WHERE part_id='one-0'").fetchone()[0],'queued')
    def test_trial_end_keeps_readonly_measurement_without_authoring(self):
        c=dict(self.c,continuousMode=False,endsAt=(self.now-timedelta(seconds=1)).isoformat());path=Path(self.temp.name)/'config.json';config.save(c,path)
        with patch('threads_posting.scheduler.lock'),patch('threads_posting.pipeline.reconcile') as reconcile,patch('threads_posting.measurement.should_collect',return_value=True),patch('threads_posting.measurement.collect',return_value={'status':'partial','revenue':None}) as collect,patch('threads_posting.authoring.prepare_next',side_effect=AssertionError('no model after trial')),patch('threads_posting.pipeline.publish',side_effect=AssertionError('no publish after trial')):
            result=scheduler.tick(path,self.db,Path(self.temp.name)/'snapshot.json')
        self.assertEqual(result['state'],'trial_ended');reconcile.assert_called_once();collect.assert_called_once()
    def test_evening_activation_never_backfills_morning(self):
        evening=datetime.fromisoformat(self.day+'T20:00:00+09:00')
        self.assertEqual(scheduler.current_slot(self.c,evening),'18:10')
        self.assertIsNone(scheduler.current_slot(self.c,evening,{'18:10'}))
        self.assertIsNone(scheduler.current_slot(self.c,evening,{'08:00','18:10'}))
    def test_timestamp_recovery_preserves_existing_public_proof(self):
        pipeline.import_document(self.document(),self.c,self.db)
        with pipeline.connect(self.db) as db:
            pipeline._update(db,'one-0','published_verified',platform_id='123',verified_at='2026-10-15T01:00:00+00:00')
            part=dict(db.execute("SELECT * FROM parts WHERE part_id='one-0'").fetchone())
        class API:
            @staticmethod
            def verify_public(*args):return {k:part[k] for k in ('account_key','platform_id','text_sha256','outbound_url')}|{'public':False,'verified':False,'published_at':'2026-10-15T00:55:00+00:00'}
        pipeline.reconcile(self.c,self.db,API)
        with pipeline.connect(self.db) as db:
            row=db.execute("SELECT * FROM parts WHERE part_id='one-0'").fetchone();self.assertEqual(row['published_at'],'2026-10-15T00:55:00+00:00');self.assertEqual(row['state'],'published_verified');self.assertEqual(row['verified_at'],'2026-10-15T01:00:00+00:00')
    def test_uncertain_adoption_requires_unique_exact_post_after_intent(self):
        pipeline.import_document(self.document(),self.c,self.db)
        with pipeline.connect(self.db) as db:
            pipeline._update(db,'one-0','published_verified',platform_id='999',published_at=(self.now-timedelta(seconds=200)).isoformat())
            pipeline.begin_send(db,'one-1',self.c,now=self.now-timedelta(seconds=5));pipeline._update(db,'one-1','submitted_unknown');row=dict(db.execute("SELECT * FROM parts WHERE part_id='one-1'").fetchone())
        evidence={k:row[k] for k in ('account_key','text_sha256','outbound_url')}|{'matched':True,'match_count':1,'platform_id':'123','permalink':'https://www.threads.com/@mustpickinfo/post/EXAMPLE','published_at':self.now.isoformat()}
        for changed in ({'match_count':0},{'match_count':2},{'text_sha256':'wrong'},{'account_key':'other'},{'outbound_url':'wrong'},{'published_at':(self.now-timedelta(minutes=1)).isoformat()}):
            with self.assertRaises(ValueError):pipeline.adopt_recovered('one-1',evidence|changed,self.db)
        pipeline.adopt_recovered('one-1',evidence,self.db)
        with pipeline.connect(self.db) as db:self.assertEqual(db.execute("SELECT state FROM parts WHERE part_id='one-1'").fetchone()[0],'api_submitted')

if __name__=='__main__':unittest.main()
