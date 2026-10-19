import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from datetime import datetime,timedelta
from concurrent.futures import ThreadPoolExecutor

from common.channel_attribution import build_attribution_receipt
from naver_kin import pipeline as p


def document(account='adinfo0905', qid='123456789'):
    article = {'url':'https://www.must-good.com/washing-machine-drain-filter-cleaning',
               'body':'Public article verified source. ' * 20, 'checked_at':p.stamp(),'http_status':200}
    article['body_sha256'] = hashlib.sha256(article['body'].encode()).hexdigest()
    receipt = build_attribution_receipt(article['url'],source='naver_kin',account=account,
        work_date=p.today_kst(),publication_date=p.today_kst(),slot='12:00',article_id=qid,allowed_hosts=p.HOSTS)
    doc = {'account':account,'question':{'question_url':'https://kin.naver.com/qna/detail.naver?docId='+qid,
             'title':'Drain filter question','body':'How do I check a blocked drain filter?', 'captured_at':p.stamp()},
           'article':article,'attribution':receipt,
           'answer_text':('Check the product manual before opening the service cover. Disconnect power and let hot water cool. '
                          'Prepare a shallow tray, drain residual water slowly, and stop if the model does not support user access. '
                          'The linked checklist adds the model-specific checks. '+receipt['outboundUrl'])}
    doc['review'] = {'approved':True,'reviewer':'supervisor-test','binding':p.draft_binding(doc)}
    return doc


class LedgerTests(unittest.TestCase):
    def setUp(self):
        self.folder=tempfile.TemporaryDirectory()
        self.db=p.connect(Path(self.folder.name)/'kin.sqlite3')
        self.window=patch.object(p,'enforce_trial_window');self.window.start()
    def tearDown(self):
        self.window.stop();self.db.close(); self.folder.cleanup()

    def test_global_dedupe_across_accounts(self):
        p.import_draft(self.db,document())
        with self.assertRaises(ValueError):
            p.import_draft(self.db,document('stone0747'))
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM questions').fetchone()[0],1)

    def test_uncertain_send_never_reposts(self):
        qid=p.import_draft(self.db,document())
        p.begin_send(self.db,qid,'adinfo0905')
        p.finish_send(self.db,qid,{'reason':'timeout after click'})
        with self.assertRaises(ValueError):p.begin_send(self.db,qid,'adinfo0905')
        with self.assertRaises(ValueError):p.import_draft(self.db,document())
        self.assertEqual(self.db.execute('SELECT state FROM questions').fetchone()[0],'submitted_unverified')

    def test_crash_in_publishing_never_reposts(self):
        qid=p.import_draft(self.db,document());p.begin_send(self.db,qid,'adinfo0905')
        with self.assertRaises(ValueError):p.begin_send(self.db,qid,'adinfo0905')

    def test_supervisor_binding_rejects_edited_answer(self):
        doc=document();doc['answer_text']+=' Added unreviewed advice.'
        qid=p.import_draft(self.db,doc)
        with self.assertRaises(ValueError):p.begin_send(self.db,qid,'adinfo0905')
        self.assertEqual(self.db.execute('SELECT state FROM questions').fetchone()[0],'drafted')

    def test_daily_global_cap(self):
        for i,account in enumerate(p.ACCOUNTS):
            qid=p.import_draft(self.db,document(account,str(123456780+i)))
            p.begin_send(self.db,qid,account,cap=2)
        qid=p.import_draft(self.db,document(qid='123456799'))
        with self.assertRaises(ValueError):p.begin_send(self.db,qid,'adinfo0905',cap=2)

    def test_per_account_ten_attempts_including_uncertainty(self):
        for i in range(p.ACCOUNT_DAILY_CAP):
            qid=p.import_draft(self.db,document(qid=str(123450000+i)))
            p.begin_send(self.db,qid,'adinfo0905')
            p.finish_send(self.db,qid,{'reason':'uncertain result'})
        qid=p.import_draft(self.db,document(qid='123459999'))
        with self.assertRaises(ValueError):p.begin_send(self.db,qid,'adinfo0905')
        other=p.import_draft(self.db,document('stone0747',qid='123459998'))
        p.begin_send(self.db,other,'stone0747')

    def test_twenty_attempts_across_accounts_and_no_more(self):
        for i in range(p.GLOBAL_DAILY_CAP):
            account=p.ACCOUNTS[i//p.ACCOUNT_DAILY_CAP]
            qid=p.import_draft(self.db,document(account,qid=str(123460000+i)))
            p.begin_send(self.db,qid,account)
        qid=p.import_draft(self.db,document(qid='123469999'))
        with self.assertRaises(ValueError):p.begin_send(self.db,qid,'adinfo0905')
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM questions WHERE send_day=?',(p.today_kst(),)).fetchone()[0],p.GLOBAL_DAILY_CAP)

    def test_atomic_account_cap_with_concurrent_connections(self):
        ids=[p.import_draft(self.db,document(qid=str(123470000+i))) for i in range(p.ACCOUNT_DAILY_CAP + 2)]
        path=Path(self.folder.name)/'kin.sqlite3'
        def attempt(qid):
            db=p.connect(path)
            try:
                try:p.begin_send(db,qid,'adinfo0905');return True
                except ValueError:return False
            finally:db.close()
        with ThreadPoolExecutor(max_workers=6) as workers:
            self.assertEqual(sum(workers.map(attempt,ids)),p.ACCOUNT_DAILY_CAP)

    def test_public_identity_is_required_for_verification(self):
        doc=document();qid=p.import_draft(self.db,doc);p.begin_send(self.db,qid,'adinfo0905')
        p.finish_send(self.db,qid,{'answer_url':doc['question']['question_url']+'#answer_123','answer_id':'123'})
        evidence={'verified':True,'public':True,'account':'stone0747','question_id':qid,'answer_id':'123',
                  'answer_text_sha256':hashlib.sha256(doc['answer_text'].encode()).hexdigest(),
                  'outbound_url':doc['attribution']['outboundUrl']}
        self.assertFalse(p.record_verification(self.db,qid,evidence))
        evidence['account']='adinfo0905';evidence['public']=False
        self.assertFalse(p.record_verification(self.db,qid,evidence))
        evidence['public']=True;evidence['answer_id']='456'
        self.assertFalse(p.record_verification(self.db,qid,evidence))
        evidence['answer_id']='123'
        old_url=doc['question']['question_url']+'#answer_123'
        evidence['answer_url']=doc['question']['question_url']+'&answerNo=123#answer123'
        self.assertTrue(p.record_verification(self.db,qid,evidence))
        row=self.db.execute('SELECT answer_url,result FROM questions WHERE question_id=?',(qid,)).fetchone()
        self.assertEqual(row['answer_url'],evidence['answer_url'])
        self.assertEqual(json.loads(row['result'])['previous_answer_url'],old_url)

    def test_account_url_and_article_tampering_rejected(self):
        with self.assertRaises(ValueError):p.account_key('soultin')
        for url in ['https://kin.naver.com.evil.test/qna/detail.naver?docId=123456',
                    'https://kin.naver.com/qna/detail.naver?docId=123456&docId=987654',
                    'https://user@kin.naver.com/qna/detail.naver?docId=123456',
                    'http://kin.naver.com/qna/detail.naver?docId=123456']:
            with self.assertRaises(ValueError):p.question_id(url)
        for change in ('body','link'):
            doc=document()
            if change=='body':doc['article']['body']+='corruption'
            else:doc['answer_text']=doc['answer_text'].replace('utm_source=naver_kin','utm_source=evil')
            with self.assertRaises(ValueError):p.validate_document(doc)

    def test_snapshot_preserves_unmeasured_and_sanitizes_urls(self):
        doc=document();qid=p.import_draft(self.db,doc);p.begin_send(self.db,qid,'adinfo0905')
        p.finish_send(self.db,qid,{'answer_url':'javascript:alert(1)','answer_id':'1'})
        result=p.snapshot(self.db,Path(self.folder.name)/'public.json')
        self.assertIsNone(result['inboundSessions']);self.assertIsNone(result['attributedRevenue'])
        self.assertIsNone(result['recent'][0]['answer_url'])
        self.assertNotIn('answer_text',json.dumps(result))


class SchedulerTests(unittest.TestCase):
    def setUp(self):
        from naver_kin import scheduler as s
        from naver_kin.experiment import TRIAL_START,TRIAL_END,FINAL_COLLECTION
        self.s=s;self.folder=tempfile.TemporaryDirectory();self.root=Path(self.folder.name)
        self.path=self.root/'ledger.sqlite3';self.db=p.connect(self.path)
        self.now=datetime.fromisoformat(TRIAL_START.isoformat()+'T09:15:00+09:00')
        self.config={'enabled':True,'timezone':'Asia/Seoul','provider':'authenticated-codex-subscription',
          'model':'gpt-6.1-sol','startDate':TRIAL_START.isoformat(),'endDate':TRIAL_END.isoformat(),
          'measurementEndDate':FINAL_COLLECTION.isoformat(),'globalDailyCap':20,'accountDailyCap':10,
          'mode':'alternating_interval','intervalMinutes':60,'pollMinutes':5,
          'operationDailyCap':20,'operationAccountDailyCap':10,'articleCatalog':[]}
        original=p.connect
        self.patches=[patch.object(s,'ROOT',self.root),patch.object(p,'ROOT',self.root),
          patch.object(s,'STATE',self.root/'state.json'),patch.object(s,'now_kst',side_effect=lambda:self.now),
          patch.object(p,'connect',side_effect=lambda:original(self.path)),patch.object(p,'snapshot',return_value={}),
          patch.object(p,'enforce_trial_window'),patch.object(s,'observe_tasks',return_value={'status':'test'}),
          patch('naver_kin.measurement.collect',return_value={})]
        for item in self.patches:item.start()
        s.initialize_cadence(self.db)
    def tearDown(self):
        for item in reversed(self.patches):item.stop()
        self.db.close();self.folder.cleanup()
    def test_wait_checks_do_not_slide_anchor_or_query_ga(self):
        with self.db:self.db.execute('UPDATE operating_cadence SET last_completed_at=?,last_account=?',(self.now.isoformat(),'adinfo0905'))
        with patch('naver_kin.authoring.generate_for_slot') as generate,patch('naver_kin.measurement.collect') as collect:
            for minutes in (5,10,55):self.s.tick(self.config,self.now+timedelta(minutes=minutes))
            generate.assert_not_called();collect.assert_not_called()
        row=self.db.execute('SELECT * FROM operating_cadence').fetchone()
        self.assertEqual(row['last_completed_at'],self.now.isoformat());self.assertEqual(row['last_account'],'adinfo0905')
    def test_59_minutes_waits_exactly_60_reserves_other_account(self):
        with self.db:self.db.execute('UPDATE operating_cadence SET last_completed_at=?,last_account=?',(self.now.isoformat(),'adinfo0905'))
        self.assertEqual(self.s.reserve_run(self.db,self.config,self.now+timedelta(minutes=59))['state'],'waiting')
        r=self.s.reserve_run(self.db,self.config,self.now+timedelta(minutes=60))
        self.assertEqual(r['state'],'reserved');self.assertEqual(r['account'],'stone0747')
    def test_cross_midnight_does_not_reset_interval(self):
        anchor=self.now.replace(hour=23,minute=40)
        with self.db:self.db.execute('UPDATE operating_cadence SET last_completed_at=?,last_account=?',(anchor.isoformat(),'adinfo0905'))
        self.assertEqual(self.s.reserve_run(self.db,self.config,anchor+timedelta(minutes=30))['state'],'waiting')
    def test_interrupted_claim_recovers_without_posting_and_waits_hour(self):
        self.s.reserve_run(self.db,self.config,self.now)
        recovered=self.s.reserve_run(self.db,self.config,self.now+timedelta(minutes=10))
        self.assertEqual(recovered['state'],'recovered_wait')
        self.assertEqual(self.s.reserve_run(self.db,self.config,self.now+timedelta(minutes=69))['state'],'waiting')
    def test_rejected_review_is_skipped_without_consuming_submission_quota(self):
        with patch('naver_kin.authoring.generate_for_slot',return_value={'document':None,'reason':'review_rejected','discovered':[{}]*12}):
            result=self.s.tick(self.config,self.now)
        self.assertEqual(result['runs'][0]['state'],'skipped')
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM discoveries').fetchone()[0],0)
        status=self.s.cadence_status(self.db,self.config,self.now)
        self.assertEqual(status['nextAccount'],'stone0747')
        self.assertEqual(status['globalRemainingRuns'],20)
        with patch('naver_kin.authoring.generate_for_slot') as generate:self.s.tick(self.config,self.now+timedelta(minutes=5));generate.assert_not_called()
    def test_operating_round_cap_for_submitted_slots(self):
        cfg = {**self.config, 'intervalMinutes': 35}
        self.now = self.now.replace(hour=8, minute=0)
        for i in range(20):
            if i > 0:
                self.now = self.now + timedelta(minutes=35)
                self.s.complete_run(self.db, previous, self.now - timedelta(minutes=35))
            r = self.s.reserve_run(self.db, cfg, self.now)
            self.assertEqual(r['state'], 'reserved')
            previous = r['runId']
        self.s.complete_run(self.db, previous, self.now)
        self.assertEqual(self.s.reserve_run(self.db, cfg, self.now + timedelta(minutes=35))['state'], 'waiting')
    def test_random_jitter_30_to_40_minutes_is_deterministic_per_anchor(self):
        jitter_cfg={**self.config,'intervalMinutes':35,'intervalJitterMinutes':[30,40]}
        c1=self.s._cooldown_minutes(jitter_cfg,self.now.isoformat())
        c2=self.s._cooldown_minutes(jitter_cfg,self.now.isoformat())
        self.assertEqual(c1,c2)
        self.assertTrue(30<=c1<=40)
    def test_uncertain_send_consumed_and_manual_unreserved_send_rejected(self):
        doc=document();qid=p.import_draft(self.db,doc)
        with self.assertRaises(ValueError):p.begin_send(self.db,qid,'adinfo0905')
        r=self.s.reserve_run(self.db,self.config,self.now)
        with self.db:self.db.execute('UPDATE automation_slots SET question_id=? WHERE slot_id=?',(qid,r['runId']))
        p.begin_send(self.db,qid,'adinfo0905',run_id=r['runId'])
        with self.assertRaises(ValueError):p.begin_send(self.db,qid,'adinfo0905',run_id=r['runId'])
    def test_dry_run_does_not_consume_rounds_or_generate(self):
        with patch('naver_kin.authoring.generate_for_slot') as generate:self.s.tick(self.config,self.now,dry_run=True);generate.assert_not_called()
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM automation_slots').fetchone()[0],0)
    def test_bootstrap_legacy_timestamp_is_used_only_once(self):
        self.db.execute('DELETE FROM operating_cadence');self.db.commit()
        doc=document();qid=p.import_draft(self.db,doc)
        with self.db:self.db.execute("UPDATE questions SET state='published_verified',send_day=?,updated_at=?",(self.now.date().isoformat(),self.now.isoformat()))
        self.s.initialize_cadence(self.db)
        with self.db:self.db.execute('UPDATE questions SET updated_at=?',((self.now+timedelta(hours=3)).isoformat(),))
        self.s.initialize_cadence(self.db)
        self.assertEqual(self.db.execute('SELECT last_completed_at FROM operating_cadence').fetchone()[0],self.now.isoformat())
    def test_final_date_rejects_reserved_candidate_at_send(self):
        qid=p.import_draft(self.db,document());r=self.s.reserve_run(self.db,self.config,self.now)
        with self.db:self.db.execute('UPDATE automation_slots SET question_id=? WHERE slot_id=?',(qid,r['runId']))
        with patch.object(p,'enforce_trial_window',side_effect=ValueError('experiment ended')):
            with self.assertRaises(ValueError):p.begin_send(self.db,qid,'adinfo0905',run_id=r['runId'])
        self.assertIsNone(self.db.execute('SELECT send_day FROM questions WHERE question_id=?',(qid,)).fetchone()[0])
    def test_running_state_has_no_guessed_next_timestamp(self):
        r=self.s.reserve_run(self.db,self.config,self.now)
        status=self.s.cadence_status(self.db,self.config,self.now)
        self.assertIsNone(status['nextEligibleAt']);self.assertEqual(status['activeRunId'],r['runId'])
        self.assertEqual(status['activeAccount'],r['account'])
    def test_trial_finished_has_no_next_timestamp(self):
        status=self.s.cadence_status(self.db,self.config,self.now+timedelta(days=7))
        self.assertIsNone(status['nextEligibleAt']);self.assertIsNone(status['nextAccount'])
    def test_daily_budget_rolls_next_time_to_next_kst_date(self):
        for i in range(20):
            with self.db:self.db.execute('INSERT INTO automation_slots(slot_id,account,planned_at,state,updated_at) VALUES(?,?,?,?,?)',
                ('budget'+str(i),p.ACCOUNTS[i//10],self.now.isoformat(),'published_verified',self.now.isoformat()))
        status=self.s.cadence_status(self.db,self.config,self.now)
        self.assertEqual(datetime.fromisoformat(status['nextEligibleAt']).hour,0)
        self.assertGreater(datetime.fromisoformat(status['nextEligibleAt']).date(),self.now.date())


if __name__=='__main__':unittest.main()
