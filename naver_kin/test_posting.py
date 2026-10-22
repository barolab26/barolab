"""Basic documents, isolated accounts and irreversible submission boundaries."""
import hashlib
import tempfile
import unittest
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from unittest.mock import patch
from common.channel_attribution import build_attribution_receipt
from naver_kin import posting as p


def document(account='adinfo0905',qid='123456789'):
    article={'url':'https://www.must-good.com/washing-machine-drain-filter-cleaning',
             'body':'Actual source body. '*20,'checked_at':p.stamp(),'http_status':200}
    article['body_sha256']=hashlib.sha256(article['body'].encode()).hexdigest()
    receipt=build_attribution_receipt(article['url'],source='naver_kin',account=account,
        work_date=p.today_kst(),publication_date=p.today_kst(),slot='12:00',article_id=qid,allowed_hosts=p.HOSTS)
    return {'account':account,'question':{'question_url':'https://kin.naver.com/qna/detail.naver?docId='+qid,
        'title':'Drain filter question','body':'How do I check a blocked drain filter?','captured_at':p.stamp()},
        'article':article,'attribution':receipt,
        'answer_text':'Check the actual product manual before opening the service cover. Disconnect power and let hot water cool. '
                      'Prepare a shallow tray, drain residual water slowly, and stop if the model does not support user access. '
                      'The linked checklist explains the details. '+receipt['outboundUrl']}


class PostingTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        telemetry=patch('common.ego_telemetry.DIRECTORY',Path(self.temp.name)/'telemetry');telemetry.start();self.addCleanup(telemetry.stop)
        self.db=p.connect(Path(self.temp.name)/'kin.sqlite3');self.addCleanup(self.db.close)
        for target in ('_naver_pipeline_enforce_trial_window','_naver_pipeline__emit_crew_state'):
            mock=patch.object(p,target);mock.start();self.addCleanup(mock.stop)
        mock=patch('common.host_failure.report_host_failure');mock.start();self.addCleanup(mock.stop)

    def test_basic_document_needs_no_reviewer(self):
        doc=document();self.assertNotIn('review',doc)
        self.assertEqual(p.validate_document(doc,reviewed=True),'123456789')

    def test_global_dedupe_across_accounts(self):
        p.import_draft(self.db,document())
        with self.assertRaises(ValueError):p.import_draft(self.db,document('stone0747'))
        self.assertEqual(self.db.execute('SELECT count(*) FROM questions').fetchone()[0],1)

    def test_crash_after_send_intent_is_not_resubmitted(self):
        qid=p.import_draft(self.db,document());p.begin_send(self.db,qid,'adinfo0905')
        with self.assertRaises(ValueError):p.begin_send(self.db,qid,'adinfo0905')

    def test_ambiguous_submission_is_not_resubmitted(self):
        qid=p.import_draft(self.db,document());p.begin_send(self.db,qid,'adinfo0905')
        p.finish_send(self.db,qid,{'reason':'timeout after submit'})
        with self.assertRaises(ValueError):p.begin_send(self.db,qid,'adinfo0905')
        self.assertEqual(self.db.execute('SELECT state FROM questions').fetchone()[0],'submitted_unverified')

    def test_submission_caps_remain_effective(self):
        first=p.import_draft(self.db,document());p.begin_send(self.db,first,'adinfo0905',cap=1)
        second=p.import_draft(self.db,document(qid='123456790'))
        with self.assertRaises(ValueError):p.begin_send(self.db,second,'adinfo0905',cap=1)
        self.assertEqual((p.GLOBAL_DAILY_CAP,p.ACCOUNT_DAILY_CAP),(20,10))

    def test_invalid_question_identity_is_rejected(self):
        for url in ('http://kin.naver.com/qna/detail.naver?docId=123456789',
                    'https://kin.naver.com/qna/detail.naver?docId=123456789&docId=222222222',
                    'https://other.example/qna/detail.naver?docId=123456789'):
            with self.subTest(url=url),self.assertRaises(ValueError):p.question_id(url)

    def test_real_account_protection_is_preserved(self):
        with self.assertRaises(p.AccountProtectionError):p._check_protection_message('자동입력 방지 CAPTCHA')


if __name__=='__main__':unittest.main()
