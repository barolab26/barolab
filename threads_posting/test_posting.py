"""Basic formatting and the Threads submission ledger; no live API calls."""
import hashlib
import tempfile
import unittest
from datetime import datetime,timedelta,timezone
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from unittest.mock import patch
from threads_posting import posting as p


class PostingTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        telemetry=patch('common.ego_telemetry.DIRECTORY',Path(self.temp.name)/'telemetry');telemetry.start();self.addCleanup(telemetry.stop)
        self.db=Path(self.temp.name)/'threads.sqlite3'
        self.now=datetime.now(timezone.utc);self.day=self.now.astimezone(p.KST).date().isoformat()
        self.config=p.defaults();self.config.update(enabled=True,activationApproved=True,
            activatedAt=(self.now-timedelta(days=1)).isoformat(),endsAt=(self.now+timedelta(days=13)).isoformat(),
            startDate=self.day,endDate=self.day)
        self.config['connection']={'connected':True,'account_verified':True,'account_key':'mustpickinfo','publishReady':True}
        mock=patch.object(p,'_threads_pipeline__emit_crew_state');mock.start();self.addCleanup(mock.stop)

    def document(self,identifier='one'):
        body='Observed public source'
        source={'url':'https://www.must-pick.com/example','body':body,'body_sha256':hashlib.sha256(body.encode()).hexdigest()}
        receipt=p.receipt('mustpickinfo',source['url'],self.day,'00:00',identifier)
        return {'schema':'threads-document-v1','content_id':identifier,'account_key':'mustpickinfo',
            'publication_date':self.day,'slot':'00:00','mode':'cf_inbound','followup_delay_seconds':120,
            'title':'Example','source':source,'attribution':receipt,
            'parts':[{'kind':'main','text':'먼저 확인할 핵심 정보\n확인 순서 첫 단계\n세부 조건과 절차를 확인해요'},
                     {'kind':'followup','text':'제가 직접 정리·운영하는 블로그에 상세 가이드를 정리했습니다.\n'+receipt['outboundUrl']}]}

    def test_format_validation_requires_no_invented_review(self):
        doc=self.document();self.assertNotIn('review',doc)
        self.assertIs(p.validate_document(doc,self.config),doc)

    def test_oversized_part_is_not_sent(self):
        doc=self.document();doc['parts'][0]['text']='x'*501
        with self.assertRaises(ValueError):p.validate_document(doc,self.config)

    def test_account_mismatch_is_not_sent(self):
        doc=self.document();doc['account_key']='someone-else'
        with self.assertRaises(ValueError):p.validate_document(doc,self.config)

    def test_source_hash_is_not_silently_changed(self):
        doc=self.document();doc['source']['body']='Different body'
        with self.assertRaises(ValueError):p.validate_document(doc,self.config)

    def test_send_intent_is_irreversible(self):
        p.import_document(self.document(),self.config,self.db)
        with p.connect(self.db) as db:
            p.begin_send(db,'one-0',self.config,self.now)
            with self.assertRaises(RuntimeError):p.begin_send(db,'one-0',self.config,self.now)

    def test_disabled_scheduler_does_not_publish(self):
        from contextlib import nullcontext
        with patch.object(p,'_threads_scheduler_lock',return_value=nullcontext()), \
             patch.object(p,'_threads_config_load',return_value={'enabled':False}), \
             patch.object(p,'_threads_pipeline_snapshot'),patch.object(p,'_threads_pipeline_publish') as publish:
            self.assertEqual(p.tick()['state'],'noop');publish.assert_not_called()


if __name__=='__main__':unittest.main()
