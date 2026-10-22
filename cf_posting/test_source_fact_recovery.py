"""Bounded official fact acquisition: offline, no model or network requests."""
import asyncio
import hashlib
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, AsyncMock, patch
from cf_posting import pipeline_runner as r

class SourceFactAcquisitionTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.folder=Path(self.tmp.name)
        self.goal={'question':'When does wrist pain need care?'}
        self.missing=[{'kind':'source_fact','description':'care criteria','acquisitionAction':'Read official guidance'}]
        self.model=Mock(return_value={'queries':[{'query':'wrist pain care','officialHost':'nhs.uk'}]})
        self.text='Actual official source body. '*10
        self.source={'url':'https://www.nhs.uk/conditions/hand-pain/wrist-pain/','text':self.text,
                     'bodySha256':hashlib.sha256(self.text.encode()).hexdigest()}
        self.gather=AsyncMock(return_value={'sources':[self.source]})
    def run_call(self):
        return asyncio.run(r.acquire_missing_source_facts(self.folder,self.missing,self.goal,self.model,self.gather))
    def test_actual_body_bound_and_once(self):
        result=self.run_call()
        self.assertEqual(result['sources'][0]['text'],self.text)
        self.assertEqual(result['readerQuestion'],self.goal['question'])
        self.assertNotIn('readyForWriter',result)
        self.assertEqual(self.gather.call_args.args[0]['sourceQueries'],['wrist pain care site:nhs.uk'])
        self.assertIsNone(self.run_call());self.model.assert_called_once()
    def test_snippet_or_unapproved_host_is_not_evidence(self):
        self.gather.return_value={'sources':[{'url':self.source['url'],'snippet':'fake summary'},
                                           {**self.source,'url':'https://example.com/'}]}
        self.assertIsNone(self.run_call())
    def test_queries_have_one_host_and_groups_share_capacity(self):
        self.model.return_value={'queries':[{'query':'site:nhs.uk wrist pain site:example.com','officialHost':'nhs.uk'}]}
        self.run_call()
        query=self.gather.call_args.args[0]['sourceQueries'][0]
        self.assertEqual(query.count('site:'),1)
        self.assertNotIn('example.com',query)
        self.assertEqual(r.round_robin_sources([['a1','a2','a3','a4'],['b1','b2','b3'],[]])[:6],['a1','b1','a2','b2','a3','b3'])

    def test_quote_catalog_keeps_original_bodies_when_new_sources_are_unrelated(self):
        original={'url':'https://www.gov.kr/pension','text':'Confirmed pension application timing. '*20,
                  'quotes':['Invented unobserved quote that must never be offered']}
        unrelated={'url':'https://www.gov.kr/other','text':'Other official department announcement. '*20}
        catalog=r.observed_quote_catalog([original,unrelated])
        self.assertEqual({row['sourceUrl'] for row in catalog},{original['url'],unrelated['url']})
        for row in catalog:
            body=next(s['text'] for s in [original,unrelated] if s['url']==row['sourceUrl'])
            self.assertIn(row['quote'],body)
        self.assertNotIn(original['quotes'][0],[row['quote'] for row in catalog])

    def test_independent_review_sees_original_quote_beyond_excerpt_limit(self):
        quote='Actual supported timing from the original official document.'
        body='Navigation boilerplate. '*180+quote+' End of document.'
        source={'url':'https://www.gov.kr/original','text':body,'kind':'primary'}
        rows=r.review_source_evidence([source,source],[{'sourceUrl':source['url'],'quote':quote}])
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]['bodySha256'],hashlib.sha256(body.encode()).hexdigest())
        self.assertTrue(any(quote in passage for passage in rows[0]['passages']))
        self.assertEqual(r.review_source_evidence([{'url':source['url'],'snippet':'search only'}],[]),[])

    def test_scope_reuses_only_approved_unchanged_bodies_in_same_domain(self):
        output=self.folder/'output';folder=output/'run';folder.mkdir(parents=True)
        (folder/'handoff.json').write_text(json.dumps({'domain':'example.com'}))
        source={**self.source,'bodySha256':hashlib.sha256(self.text.encode()).hexdigest()}
        (folder/'observed-research-sources.json').write_text(json.dumps({'sources':[source]}))
        plan={'approval':{'sourceUrls':[source['url']]}}
        with patch.object(r,'BASE_DIR',self.folder):
            self.assertEqual(r.retained_approved_sources(folder,plan,'example.com'),[source])
            self.assertEqual(r.retained_approved_sources(folder,plan,'other.com'),[])
            self.assertEqual(r.retained_approved_sources(folder,{'approval':{'sourceUrls':[]}},'example.com'),[])
            source['text']='Tampered source body. '*20
            (folder/'observed-research-sources.json').write_text(json.dumps({'sources':[source]}))
            self.assertEqual(r.retained_approved_sources(folder,plan,'example.com'),[])

    def test_hash_mismatch_fails_closed(self):
        self.gather.return_value={'sources':[{**self.source,'bodySha256':'0'*64}]}
        with self.assertRaises(r.ReviewRequired):self.run_call()
    def test_unknown_host_rejected_before_search(self):
        self.model.return_value={'queries':[{'query':'wrist','officialHost':'example.com'}]}
        with self.assertRaises(r.ReviewRequired):self.run_call()
        self.gather.assert_not_called()
    def test_non_source_missing_does_not_consume(self):
        self.missing=[{'kind':'actual_capture'}]
        self.assertIsNone(self.run_call());self.model.assert_not_called()
        self.assertFalse((self.folder/'source-fact-acquisition').exists())


class SourceContinuationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.base=Path(self.tmp.name);self.folder=self.base/'output'/'same-question'/'original';self.folder.mkdir(parents=True)
        (self.base/'data').mkdir();(self.base/'agents').mkdir()
        shutil.copy2(r.BASE_DIR/'agents'/'keyword-selector.md',self.base/'agents'/'keyword-selector.md')
        for key,value in [('BASE_DIR',self.base),('DATA_DIR',self.base/'data'),('RUN_CONTEXT',{})]:
            item=patch.object(r,key,value);item.start();self.addCleanup(item.stop)
        self.goal={'question':'same question','requiredAnswers':['same requirement']}
        kw={'topicSlug':'same-question','title':'Same title','readerGoal':self.goal,'demandEvidence':{'observed':True}}
        r.document(self.folder/'keywords.md','Keywords',kw)
        data={'version':2,'runId':'original-run','domain':'healthcox.com','slug':'same-question',
              'contentQualitySha256':r.content_quality_sha256(),'stages':[]}
        (self.folder/'handoff.json').write_text(json.dumps(data),encoding='utf-8')
        h=r.Handoff(self.folder,'healthcox.com','same-question')
        with patch('common.crew_chat_bridge.emit_work_event'):
            h.accept('keyword-selector',['keywords.md'],{'status':'returned','actualModel':'fixture'})
        r.document(self.folder/'research.md','Research',{'readerGoal':self.goal,'observations':{'sources':[]}})
        (self.folder/'prewriter-acquisition-request.json').write_text(json.dumps({'status':'answer_inputs_required','readerGoal':self.goal,'missingInputs':[{'kind':'source_fact'}]}),encoding='utf-8')
        self.item={'domain':'healthcox.com','artifactFolder':str(self.folder),'status':'review_required','attemptCount':3}
        self.save_schedule()
    def save_schedule(self):
        (self.base/'data'/'daily_schedule.json').write_text(json.dumps({'date':r.datetime.datetime.now(r.KST).date().isoformat(),'items':[self.item]}),encoding='utf-8')
    def test_reuses_exact_stage_preserves_original_and_claim_once(self):
        before={p.name:p.read_bytes() for p in self.folder.iterdir() if p.is_file()}
        h,kw,goal,_,_=r.open_source_fact_continuation(self.folder,'healthcox.com',[])
        self.assertEqual(len(h.check()),1);self.assertEqual(goal,self.goal)
        self.assertEqual((h.folder/'keywords.md').read_bytes(),before['keywords.md'])
        for name,raw in before.items():self.assertEqual((self.folder/name).read_bytes(),raw)
        self.assertEqual(json.loads((self.base/'data'/'daily_schedule.json').read_text())['items'][0]['attemptCount'],3)
        with self.assertRaises(FileExistsError):r.open_source_fact_continuation(self.folder,'healthcox.com',[])
    def test_copy_metadata_failure_can_complete_same_claim_once(self):
        actual_copy=shutil.copyfile
        def old_copy_failure(source,target):
            actual_copy(source,target)
            raise PermissionError('keywords.md metadata denied')
        with patch.object(r.shutil,'copyfile',side_effect=old_copy_failure):
            with self.assertRaises(PermissionError):r.open_source_fact_continuation(self.folder,'healthcox.com',[])
        claim=(self.folder/'source-fact-continuation.json').read_bytes()
        self.item.update(status='failed',lastError='PermissionError: keywords.md metadata denied');self.save_schedule()
        with patch.object(r.shutil,'copyfile') as copying:
            h,*_=r.open_source_fact_continuation(self.folder,'healthcox.com',[])
        copying.assert_not_called()
        self.assertEqual(len(h.check()),1)
        self.assertEqual((self.folder/'source-fact-continuation.json').read_bytes(),claim)
        self.assertTrue((self.folder/'source-fact-bootstrap-recovery.json').exists())
        with self.assertRaises((r.ReviewRequired,FileExistsError)):
            r.open_source_fact_continuation(self.folder,'healthcox.com',[])

    def test_bootstrap_with_external_stage_evidence_cannot_resume(self):
        actual_copy=shutil.copyfile
        def interrupted(source,target):
            actual_copy(source,target)
            raise PermissionError('keywords.md')
        with patch.object(r.shutil,'copyfile',side_effect=interrupted):
            with self.assertRaises(PermissionError):r.open_source_fact_continuation(self.folder,'healthcox.com',[])
        (self.folder/'source-fact-continuation'/'model-audit').mkdir()
        self.assertIsNone(r.source_fact_bootstrap_state(self.folder,'healthcox.com'))

    def test_duplicate_or_unknown_submission_never_claims(self):
        with self.assertRaises(r.ReviewRequired):r.open_source_fact_continuation(self.folder,'healthcox.com',[{'slug':'same-question'}])
        self.item['submissionStarted']=True;self.save_schedule()
        with self.assertRaises(r.ReviewRequired):r.open_source_fact_continuation(self.folder,'healthcox.com',[])
        self.assertFalse((self.folder/'source-fact-continuation.json').exists())
    def test_new_request_followup_once_preserves_lineage(self):
        first,*_=r.open_source_fact_continuation(self.folder,'healthcox.com',[])
        def fail_again(h,reason):
            r.document(h.folder/'research.md','Research',{'readerGoal':self.goal,'observations':{'sources':[]}})
            (h.folder/'prewriter-acquisition-request.json').write_text(json.dumps({'status':'answer_inputs_required','readerGoal':self.goal,'missingInputs':[{'kind':'source_fact','reason':reason}]}),encoding='utf-8')
            self.item.update(artifactFolder=str(h.folder),status='review_required');self.save_schedule()
        fail_again(first,'new missing criteria')
        second,*_=r.open_source_fact_continuation(first.folder,'healthcox.com',[])
        self.assertEqual(second.data['sourceFactContinuation']['depth'],2)
        fail_again(second,'another reason cannot reset budget')
        with self.assertRaises(r.ReviewRequired):r.open_source_fact_continuation(second.folder,'healthcox.com',[])

    def test_changed_approved_keyword_rejected(self):
        with (self.folder/'keywords.md').open('a',encoding='utf-8') as stream:stream.write('modified')
        with self.assertRaises(r.ReviewRequired):r.open_source_fact_continuation(self.folder,'healthcox.com',[])

if __name__=='__main__':unittest.main()
