import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from common.hermes_memory import write_verified_work_receipt

class ThreadsLearningReceiptTests(unittest.TestCase):
    def proof(self,outbound=None,observed_outbound=None,account='mustpickinfo',channel='threads'):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);path=root/'verified.json'
            expected={'account_key':'mustpickinfo','platform_id':'123','text_sha256':'hash','outbound_url':outbound,'permalink':'https://www.threads.com/@mustpickinfo/post/abc'}
            observation={**expected,'account_key':account,'outbound_url':observed_outbound,'verified':True,'public':True}
            outcome='public_thread_verified'
            if channel=='naver_kin':
                expected={'account':'adinfo0905','question_id':'123','answer_id':'2','answer_text_sha256':'hash','outbound_url':outbound,'answer_url':'https://kin.naver.com/qna/detail.naver?docId=123'}
                observation={**expected,'verified':True,'public':True};outcome='public_answer_verified'
            path.write_text(json.dumps({'expected':expected,'observation':observation}))
            return write_verified_work_receipt(root/'receipt.json',work_type='verified_work_receipt_v1',channel=channel,outcome=outcome,scope=outcome,source_agent='publi',evidence_text='Exact account and public body verified.',artifacts=[{'path':str(path),'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}],checks=[{'type':kind,'passed':True,'evidenceRef':str(path)} for kind in ('public_identity','public_content')])
    def test_verified_threads_main_can_have_no_external_link(self):self.assertIn('sourceSha256',self.proof())
    def test_threads_external_link_and_identity_must_still_match(self):
        for kwargs in ({'outbound':'https://example.com','observed_outbound':None},{'account':'other'}):
            with self.assertRaises(ValueError):self.proof(**kwargs)
    def test_kin_link_requirement_is_preserved(self):
        with self.assertRaises(ValueError):self.proof(channel='naver_kin')
