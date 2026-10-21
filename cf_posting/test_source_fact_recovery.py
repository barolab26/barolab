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
    def test_duplicate_or_unknown_submission_never_claims(self):
        with self.assertRaises(r.ReviewRequired):r.open_source_fact_continuation(self.folder,'healthcox.com',[{'slug':'same-question'}])
        self.item['submissionStarted']=True;self.save_schedule()
        with self.assertRaises(r.ReviewRequired):r.open_source_fact_continuation(self.folder,'healthcox.com',[])
        self.assertFalse((self.folder/'source-fact-continuation.json').exists())
    def test_changed_approved_keyword_rejected(self):
        with (self.folder/'keywords.md').open('a',encoding='utf-8') as stream:stream.write('modified')
        with self.assertRaises(r.ReviewRequired):r.open_source_fact_continuation(self.folder,'healthcox.com',[])

if __name__=='__main__':unittest.main()
