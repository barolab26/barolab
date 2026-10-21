"""Offline autonomous editorial contracts: evidence, scope and durable retry budget."""
import copy
import hashlib
import json
import os
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
from naver_blog_posting import pipeline_runner as r


def evidence():
    body = 'Observed complete public article body. ' * 8
    now = r.now_kst().isoformat()
    return {'query':'specific query','searchSurface':'naver_blog','sort':'relevance','observedAt':now,
        'competitors':[{'observedRank':i,'url':f'https://blog.naver.com/blog{i}/123',
            'excerpt':{'url':f'https://blog.naver.com/blog{i}/123','text':body,
                'bodySha256':hashlib.sha256(body.encode()).hexdigest(),
                'collectionMethod':'visible_browser_article','collectedAt':now}} for i in (1,2,3)]}


class EditorialWorkflowTests(unittest.TestCase):
    def test_top_three_requires_exact_query_rank_surface_and_actual_bodies(self):
        packet=evidence()
        self.assertEqual(len(r.require_top_three_evidence(packet,'specific query')),3)
        for change in ('query','rank','surface','body','missing'):
            bad=copy.deepcopy(packet)
            if change=='query':bad['query']='another'
            elif change=='rank':bad['competitors'][0]['observedRank']=4
            elif change=='surface':bad['searchSurface']='integrated_recommendations'
            elif change=='body':bad['competitors'][0]['excerpt']['text']='search snippet'
            else:bad['competitors'].pop()
            with self.subTest(change=change), self.assertRaises(RuntimeError):
                r.require_top_three_evidence(bad,'specific query')

    def test_test_decision_requires_hypothesis_and_observed_findings(self):
        packet=evidence()
        decision={'decision':'test','reason':'Narrow intent not fully answered','readerBenefit':'Can choose next action',
            'testHypothesis':'Measure qualified impressions after public publication',
            'competitorFindings':[{'url':x['url'],'observedStrength':'clear steps','unansweredNeed':'specific exception',
                'adoptPattern':'short paragraphs','avoidPattern':'unsupported certainty'} for x in packet['competitors']]}
        self.assertIs(r.require_editorial_decision(decision,packet,'specific query'),decision)
        for key in ('testHypothesis','url'):
            bad=copy.deepcopy(decision)
            if key=='url':bad['competitorFindings'][0]['url']='https://blog.naver.com/unobserved/99'
            else:bad[key]=''
            with self.assertRaises(RuntimeError):r.require_editorial_decision(bad,packet,'specific query')

    def test_title_only_repair_preserves_question_and_requires_fresh_independent_pass(self):
        from unittest.mock import Mock
        question='How do I check pension age and the income gap?'
        selection={'mainKeyword':'pension','title':'Check pension age','readerQuestion':question,
            'angle':'Check age and gap','demandEvidence':{'eligible':True,'mainKeyword':'pension','measuredQuery':'pension'},'sourceUrls':[]}
        goal={'question':question,'successCondition':'Check age and income gap','requiredAnswers':['age','income gap']}
        rejected={'relation':'exact_subject','matchesQuestion':False,'matchesTitle':False,'titleClear':True,
            'titleNatural':True,'reason':'Title omits gap','issues':['Income gap omitted'],'readerGoal':goal}
        approved={**rejected,'matchesQuestion':True,'matchesTitle':True,'issues':[],'reason':'Both tasks preserved'}
        for final in (approved,rejected):
            with self.subTest(passed=not final['issues']),tempfile.TemporaryDirectory() as tmp:
                base=Path(tmp);folder=base/'output'/'soultin'/'run';folder.mkdir(parents=True)
                (folder/'preparation-context.json').write_text(json.dumps({'publicationDate':'2026-10-22','scheduledSlot':'11:00'}))
                def judge(prompt,observer=None,response_schema=None):
                    observer('test','test-model','returned',actual_model='test-model')
                    return reviews.pop(0)
                reviews=[copy.deepcopy(rejected),copy.deepcopy(final)]
                draft=Mock(return_value={'title':'Check pension age and income gap'})
                with patch.object(r,'BASE_DIR',base),patch.object(r,'read_journal',return_value={'attempts':[]}),patch.object(r,'_PIPELINE_LOCK_OWNER',(os.getpid(),threading.get_ident())):
                    original=copy.deepcopy(selection)
                    if final['issues']:
                        with self.assertRaises(r.MaterialRequired):r.review_keyword_title_once(selection,folder,'soultin',False,judge=judge,drafter=draft)
                    else:
                        updated,receipt=r.review_keyword_title_once(selection,folder,'soultin',False,judge=judge,drafter=draft)
                        self.assertEqual({k:v for k,v in updated.items() if k!='title'},{k:v for k,v in original.items() if k!='title'})
                        self.assertEqual(receipt['verdict']['readerGoal'],goal)
                        _,editorial=r.claim_repair_budget('soultin',folder,{'publicationDate':'2026-10-22','scheduledSlot':'11:00'},False)
                        self.assertFalse(editorial.endswith('|keyword-title'))
                    self.assertEqual(selection,original);draft.assert_called_once();self.assertEqual(reviews,[])
                    self.assertTrue((folder/'keyword-demand-alignment-before-title-repair.json').exists())

    def test_empty_writer_never_receives_placeholder_prose(self):
        for blocks in ([],[{'kind':'heading','text':'A title'}],[{'kind':'paragraph','text':'#tags'}]):
            original=copy.deepcopy(blocks)
            with self.assertRaisesRegex(RuntimeError,'placeholder'):
                r.require_actual_writer_blocks(blocks)
            self.assertEqual(blocks,original)

    def test_duplicate_caption_rejection_preserves_actual_plan_and_prose(self):
        article={'blocks':[{'kind':'paragraph','text':'Official application conditions'}]}
        plans=[{'caption':'Official application conditions','source':'generated','filename':'example.jpg'}]
        before=copy.deepcopy((article,plans))
        with self.assertRaises(RuntimeError):r.reject_duplicate_caption_blocks(article,plans)
        self.assertEqual((article,plans),before)
        self.assertNotIn('화면',plans[0]['caption'])

    def test_wrong_fact_url_is_not_reassigned_to_first_official_source(self):
        result={'facts':[{'id':'F1','claim':'Unsupported claim','url':'https://unobserved.example/a'}], 'researchMd':'Actual draft'}
        original=copy.deepcopy(result)
        with self.assertRaisesRegex(RuntimeError,'source reassignment'):
            r.require_research_facts(result,[{'url':'https://www.gov.kr/actual'}])
        self.assertEqual(result,original)

    def test_empty_facts_never_synthesize_source_text_but_observation_only_remains_valid(self):
        result={'facts':[],'researchMd':'Actual observed physical steps; no external factual assertion'}
        with self.assertRaisesRegex(RuntimeError,'synthetic fallback'):
            r.require_research_facts(result,[{'url':'https://www.gov.kr/actual','text':'Do not synthesize F1'}])
        self.assertEqual(result['facts'],[])
        self.assertEqual(r.require_research_facts(result,[],actual_observations=True),[])
        with self.assertRaises(RuntimeError):r.require_research_facts(result,[])

    def test_empty_proposed_urls_use_discovered_actual_official_body(self):
        from unittest.mock import AsyncMock
        selected={'query':'specific policy','primarySourceCandidates':[]}
        body='Actual official published policy text. '*10
        record={'url':'https://www.gov.kr/example','text':body,
                'bodySha256':hashlib.sha256(body.encode()).hexdigest(),'collectedAt':r.now_kst().isoformat()}
        with patch.object(r,'search_primary_sources',new=AsyncMock(return_value=[{
                'url':record['url'],'text':'Search preview is not used'}])) as search, \
                patch.object(r,'evidence_text',return_value=(record,None)) as fetch:
            sources,failures=r.collect_primary_sources(selected,[])
            self.assertEqual(sources,[record]);self.assertEqual(failures,[])
            fetch.assert_called_once_with(record['url'],official=True)
            search.assert_awaited_once_with('specific policy')

    def test_failed_official_fetch_never_promotes_search_snippets_or_fabricates_government_body(self):
        from unittest.mock import AsyncMock
        selected={'query':'specific policy','primarySourceCandidates':[], 'serp':{'text':'Search summary'}}
        with patch.object(r,'evidence_text',side_effect=RuntimeError('actual body unavailable')), \
                patch.object(r,'search_primary_sources',new=AsyncMock(return_value=[{
                    'url':'https://www.gov.kr/portal/main','text':'Unverified search snippet '*20}])):
            with self.assertRaisesRegex(r.MaterialRequired,'search snippets'):
                r.collect_primary_sources(selected,[])
            self.assertEqual(r.collect_primary_sources(selected,[],allow_empty=True),([],[]))

    def test_capture_binding_never_trusts_model_source_body_or_hash(self):
        text='Official condition A. Official alternative condition B.'
        source={'url':'https://www.easylaw.go.kr/example','text':text,'bodySha256':hashlib.sha256(text.encode()).hexdigest()}
        request={'materialId':'conditions','stepId':'eligibility','sourceUrl':source['url'],
            'anchors':['Official condition A.','Official alternative condition B.'],'observation':'Both alternatives',
            'sourceEvidence':{'text':'fabrication','bodySha256':'fake'}}
        bound=r.bind_official_capture_requests([request],[source])
        self.assertEqual(bound[0]['sourceEvidence']['text'],text)
        source['text']+=' changed'
        with self.assertRaises(r.MaterialRequired):r.bind_official_capture_requests([request],[source])

    def test_optional_supplied_captures_not_forced_but_required_remain(self):
        packet={'materials':[{'source':'capture','materialId':'essential'},{'source':'capture','materialId':'optional'}]}
        prompt,schema=r.supplied_capture_image_contract(r.ROLE_SCHEMAS['image-maker'],r.agent_output_schema('image-maker'),packet,['essential'])
        self.assertEqual(schema['properties']['imagePlans']['minItems'],1)
        self.assertEqual(schema['properties']['imagePlans']['maxItems'],2)
        self.assertNotIn('Use exactly',prompt)
        self.assertNotIn('at least 3',prompt)
        self.assertEqual(r.pad_generated_image_plans([],None,[], 'query','title'),[])

    def test_current_worker_only_and_unknown_never_claimed(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp)
            row={'phase':'started','submissionStarted':False,'workerId':'current','startedAt':'now'}
            scope={'account':'soultin','folder':str(folder.resolve()),'workerId':'current','startedAt':'now'}
            with patch.object(r,'_PIPELINE_LOCK_OWNER',(os.getpid(),threading.get_ident())),patch.object(r,'_REPAIR_SCOPE',scope),patch.object(r,'RUN_OPTIONS',{'worker_id':'current'}),patch.object(r,'attempt_has_submission_evidence',return_value=False):
                self.assertTrue(r.repair_owns_attempt('soultin',folder,row))
                for field,value in [('phase','unknown'),('phase','submitting'),('submissionStarted',True),('workerId','other'),('startedAt','old')]:
                    self.assertFalse(r.repair_owns_attempt('soultin',folder,{**row,field:value}))
                (folder/'reservation-evidence.json').write_text('{}')
                self.assertFalse(r.repair_owns_attempt('soultin',folder,row))

    def test_preparation_budget_isolated_from_production_and_persistent(self):
        with tempfile.TemporaryDirectory() as tmp:
            base=Path(tmp);folder=base/'output'/'soultin'/'fixture';folder.mkdir(parents=True)
            context={'publicationDate':'2026-10-22','scheduledSlot':'11:00'}
            row={'account':'soultin','phase':'started','submissionStarted':False,'workerId':'worker','startedAt':'now','artifactFolder':str(folder)}
            with patch.object(r,'BASE_DIR',base),patch.object(r,'_PIPELINE_LOCK_OWNER',(os.getpid(),threading.get_ident())),patch.object(r,'RUN_OPTIONS',{'worker_id':'worker'}),patch.object(r,'read_journal',return_value={'attempts':[]}),patch.object(r,'attempt_has_submission_evidence',return_value=False):
                path,prep=r.claim_repair_budget('soultin',folder,context,False)
                self.assertTrue(prep.startswith('prepare|'))
                with self.assertRaises(r.MaterialRequired):r.claim_repair_budget('soultin',folder,context,False)
                with patch.object(r,'read_journal',return_value={'attempts':[row]}):
                    _,prod=r.claim_repair_budget('soultin',folder,context,True)
                    self.assertEqual(prod,'soultin|2026-10-22|11:00')
                    with self.assertRaises(r.MaterialRequired):r.claim_repair_budget('soultin',folder,context,True)
                self.assertEqual(len(json.loads(path.read_text())['slots']),2)
            r._REPAIR_SCOPE=None

    def test_senior_slot_keeps_legacy_duplicate_protection(self):
        self.assertEqual(r.DAILY_SLOTS['soultin'],('11:00',))
        self.assertEqual(r.PREPARATION_TIMES['soultin'],'21:00')
        self.assertEqual(r.SLOT_TRACK_POLICY['soultin']['11:00']['prepTime'],'21:00')
        self.assertTrue(r._slot_matches('soultin','19:30','11:00'))
        self.assertEqual(r.DAILY_SLOTS['soul5373'],('20:00',))


if __name__=='__main__':unittest.main()
