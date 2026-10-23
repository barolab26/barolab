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

    def test_browser_lock_wait_does_not_spend_research_or_submission_budget(self):
        p._naver_scheduler_initialize_cadence(self.db)
        day=p.today_kst()
        for i,(state,reason,qid) in enumerate([('deferred','browser_busy',None),('blocked','operation_RuntimeError',None),('blocked','no_sources',None),('deferred','browser_busy','123')]):
            self.db.execute('INSERT INTO automation_slots(slot_id,account,planned_at,state,reason,question_id,updated_at) VALUES(?,?,?,?,?,?,?)', (str(i),'adinfo0905',day+'T09:00:00+09:00',state,reason,qid,p.stamp()))
        counts=p._naver_scheduler_operation_counts(self.db,day)
        self.assertEqual(counts['adinfo0905'],3)

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


class ExistingEditorRepairTests(unittest.TestCase):
    def editor(self, disabled=False):
        from unittest.mock import MagicMock
        from types import SimpleNamespace
        doc=document();page=MagicMock();page.url=doc['question']['question_url']
        page.content.return_value='<div class="endTitleSection">'+doc['question']['title']+'</div>'
        text=MagicMock();text.all_inner_texts.return_value=[doc['answer_text']]
        body=MagicMock();body.inner_text.return_value=doc['question']['body']
        links=MagicMock();links.evaluate_all.return_value=[doc['attribution']['outboundUrl']]
        button=MagicMock();button.count.return_value=1;button.is_visible.return_value=True;button.is_enabled.return_value=not disabled
        page.locator.side_effect=lambda selector:{'.se-canvas .se-text-paragraph':text,'.questionDetail':body,'#answerRegisterButton':button,'.se-canvas a[href], .se-canvas .se-link[data-href]':links}[selector]
        handlers={};page.on.side_effect=lambda name,fn:handlers.update({name:fn})
        response=SimpleNamespace(url='https://kin.naver.com/ajax/detail/registerAnswerForSmartEditorOne.naver',status=200,request=SimpleNamespace(method='POST',post_data='docId=123456789'),json=lambda:{'isSuccess':True,'result':{'result':{'answerNo':9}}})
        button.evaluate.side_effect=lambda script:handlers['response'](response)
        return page,button,doc

    def test_cdp_click_once_after_durable_intent_and_exact_match(self):
        from common.kin_submit_repair import click_existing
        from unittest.mock import Mock
        page,button,doc=self.editor();intent=Mock()
        with patch.object(p,'_naver_browser__check_service_state'),patch.object(p,'_naver_browser_wait_for_editor_ready'):
            result=click_existing(page,doc,{'known':True,'complete':True,'answer_ids':[]},intent)
        intent.assert_called_once();button.evaluate.assert_called_once()
        self.assertEqual(result['answer_id'],'9');self.assertIn('answerNo=9',result['answer_url'])
        self.assertEqual(page.remove_listener.call_count,2)

    def test_disabled_or_owned_answer_never_clicks(self):
        from common.kin_submit_repair import click_existing
        from unittest.mock import Mock
        for disabled,owned in [(True,[]),(False,['7'])]:
            page,button,doc=self.editor(disabled);intent=Mock()
            with patch.object(p,'_naver_browser__check_service_state'),patch.object(p,'_naver_browser_wait_for_editor_ready'),self.assertRaises(ValueError):
                click_existing(page,doc,{'known':True,'complete':True,'answer_ids':owned},intent)
            intent.assert_not_called();button.evaluate.assert_not_called()

    def test_editor_mismatch_preserves_text_and_never_submits(self):
        from common.kin_submit_repair import click_existing
        from unittest.mock import Mock
        page,button,doc=self.editor();doc['answer_text']='A different answer';intent=Mock()
        with patch.object(p,'_naver_browser__check_service_state'),patch.object(p,'_naver_browser_wait_for_editor_ready'),self.assertRaises(ValueError):
            click_existing(page,doc,{'known':True,'complete':True,'answer_ids':[]},intent)
        intent.assert_not_called();button.evaluate.assert_not_called()

    def test_verified_no_click_learning_is_connected_and_deduplicated(self):
        from common.kin_submit_repair import remember
        import json
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/'dashboard/data').mkdir(parents=True)
            result={'publicVerified':True,'publicUrl':'https://kin.naver.com/qna/detail.naver?docId=123456789&answerNo=9#answer9','account':'adinfo0905','questionId':'123456789','clicked':False,'originalSendDay':'2026-10-19'}
            self.assertTrue(remember(result,root));self.assertFalse(remember(result,root))
            graph=json.loads((root/'dashboard/data/memory_graph.json').read_text());nodes=graph['nodes']
            self.assertEqual(nodes['problem:KIN_SUBMIT_SELECTOR_HANG']['resolvedCount'],0)
            self.assertEqual(nodes['problem:KIN_ALERT_STALE_STATE']['resolvedCount'],1)
            self.assertTrue(all(e['source'] in nodes and e['target'] in nodes for e in graph['edges']))
            self.assertEqual(sum(n['type']=='Outcome' for n in nodes.values()),1)

    def test_uncertain_ledger_send_is_verification_only(self):
        from common.kin_submit_repair import repair
        from unittest.mock import MagicMock
        doc=document();db=MagicMock();db.execute.return_value.fetchone.return_value={'document':__import__('json').dumps(doc),'state':'submitted_unverified','answer_id':None,'answer_url':None}
        with patch.object(p,'connect',return_value=db),patch.object(p,'account_lock'),patch('common.kin_submit_repair.click_existing') as click:
            result=repair('adinfo0905','123456789')
        self.assertEqual(result['status'],'held');click.assert_not_called()


if __name__=='__main__':unittest.main()
