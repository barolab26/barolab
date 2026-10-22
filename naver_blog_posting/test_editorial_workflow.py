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
        for change in ('query','rank','surface','body'):
            bad=copy.deepcopy(packet)
            if change=='query':bad['query']='another'
            elif change=='rank':bad['competitors'][0]['observedRank']=4
            elif change=='surface':bad['searchSurface']='integrated_recommendations'
            elif change=='body':bad['competitors'][0]['excerpt']['text']='search snippet'
            else:bad['competitors'].pop()
            with self.subTest(change=change), self.assertRaises(RuntimeError):
                r.require_top_three_evidence(bad,'specific query')

    def test_partial_competitors_preserve_real_ranks_and_exact_findings_count(self):
        packet=evidence();packet['competitors'].pop(1)
        rows=r.require_top_three_evidence(packet,'specific query')
        self.assertEqual([row['observedRank'] for row in rows],[1,3])
        urls=[row['url'] for row in rows]
        schema=r.editorial_decision_schema(urls)
        self.assertEqual(schema['properties']['competitorFindings']['minItems'],2)
        packet['competitors']=[]
        self.assertEqual(r.require_top_three_evidence(packet,'specific query'),[])
        self.assertEqual(r.editorial_decision_schema([])['properties']['competitorFindings']['maxItems'],0)

    def test_bridge_planning_reads_body_not_title_before_selecting_question(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(r,'fetch_bridge_article',return_value={
                'text':'실제 환급 절차 '*80,'canonicalUrl':'https://www.justinfo.co.kr/guide',
                'articleBodySha256':'b'*64,'collectedAt':r.now_kst().isoformat(),
                'summary':'실제 환급 범위','headings':['누락 공제'],'primarySourceReferences':[]}) as fetch:
            packet=r.observed_bridge_inventory({}, {'candidates':[{'url':'https://www.justinfo.co.kr/guide','title':'넓은 제목'}]},folder)
            self.assertIn('실제 환급',packet['candidates'][0]['bodyExcerpt'])
            self.assertEqual(packet['candidates'][0]['headings'],['누락 공제'])
            r.observed_bridge_inventory({}, {'candidates':[]},folder)
            self.assertEqual(fetch.call_count,1)

    def test_status_summary_separates_known_failure_from_historical_submission_gate(self):
        now=r.now_kst();day=now.date().isoformat()
        attempt={'account':'soultin','publicationDate':day,'scheduledSlot':'11:00','phase':'failed',
                 'submissionStarted':False,'preSubmissionFailure':True,'failureReason':'actual collection failure'}
        with tempfile.TemporaryDirectory() as folder, patch.object(r,'DAILY_SLOTS',{'soultin':['11:00']}), \
                patch.object(r,'read_journal',return_value={'attempts':[attempt]}), \
                patch.object(r,'account_gate',return_value='unknown'):
            result=r.classify(Path(folder),now.replace(hour=18))
        slot=result['accounts'][0]['slots'][0]
        self.assertEqual(slot['status'],'failed')
        self.assertEqual(slot['publicationGate'],'unknown')
        self.assertEqual(result['counts']['failed'],1)
        self.assertEqual(slot['failureReason'],'actual collection failure')

    def test_bridge_mismatch_enters_jarvis_scope_instead_of_generic_repair(self):
        from contextlib import nullcontext
        with patch.object(r,'_prepare_content',side_effect=r.BridgePlanningBlocked('body mismatch')), \
                patch.object(r,'_supervise_prewriting',return_value=({},Path('/tmp'))) as supervise, \
                patch.object(r,'repair_preparation_once') as generic, \
                patch('common.llm_client.memory_session',return_value=nullcontext()), \
                patch('common.llm_client.memory_event'),patch('common.editorial_supervisor.lineage'):
            r.prepare_content('adinfo0905')
        supervise.assert_called_once();generic.assert_not_called()

    def test_host_readiness_block_without_review_routes_to_material_recovery(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(r,'review_with_one_refinement',
                side_effect=r.AnswerBriefBlocked('essential source missing',[{'kind':'source_fact'}])):
            with self.assertRaises(r.MaterialRequired):
                r.plan_answer_before_writer({}, {'question':'actual question'},[],[],[],Path(folder),{}, {})
            packet=json.loads((Path(folder)/'required-materials.json').read_text())
            self.assertEqual(packet['requiredMaterials'][0]['kind'],'source_fact')
            self.assertFalse((Path(folder)/'answer-brief.json').exists())

    def test_public_readback_maps_shifted_reservation_to_original_slot(self):
        now=r.now_kst().replace(hour=18);day=now.date().isoformat()
        title='실제 예약 검증 제목';when=day+' 20:00'
        attempt={'account':'soultin','publicationDate':day,'scheduledSlot':'11:00','phase':'verified',
                 'topic':title,'reserveTime':when,'verificationSource':'actual reservation list'}
        with tempfile.TemporaryDirectory() as folder, patch.object(r,'DAILY_SLOTS',{'soultin':['11:00']}), \
                patch.object(r,'read_journal',return_value={'attempts':[attempt]}), \
                patch.object(r,'account_gate',return_value='verified'):
            root=Path(folder);(root/'data').mkdir()
            (root/'data/public-verification.json').write_text(json.dumps({'evidence':[{
                'account':'soultin','title':title,'publicationDate':day,'reserveTime':when,
                'publicPublicationVerified':True,'publicHttpStatus':200,'publicUrl':'https://blog.naver.com/mustpickinfo/123'}]}))
            result=r.classify(root,now)
        self.assertEqual(result['counts']['published'],1)
        self.assertEqual(result['accounts'][0]['slots'][0]['scheduledSlot'],'11:00')
        self.assertEqual(result['accounts'][0]['slots'][0]['status'],'published')

    def test_official_http_discovery_does_not_connect_shared_flow_browser(self):
        import asyncio
        candidates=[{'url':'https://www.gov.kr/page','title':'Actual search result'},
                    {'url':'https://unverified.example/page','title':'Other result'}]
        with patch('common.source_discovery.search_urls',return_value=candidates), \
                patch('common.browser_session.connect_async',side_effect=AssertionError('Flow must not be required')):
            result=asyncio.run(r.search_primary_sources('지원금'))
        self.assertEqual(result,[candidates[0]])

    def test_inline_pivot_preserves_approved_sources_and_conceptual_scope(self):
        import common.editorial_supervisor as supervisor
        from cf_posting import pipeline_runner as cf
        url='https://www.uniqlo.com/kr/ko/contents/feature/airism/'
        plan={'step':'pivot','approval':{'readerQuestion':'실제 확인된 소재 차이는 무엇인가요?',
              'sourceUrls':[url],'searchQuery':'공식 소재 안내'}}
        source={'url':url,'text':'Actual manufacturer source body. '*20}
        captured=[]
        def prepare(*args):
            captured.append(dict(r.RUN_OPTIONS));return {},Path(args[2])
        with tempfile.TemporaryDirectory() as folder, patch.dict(r.RUN_OPTIONS,{'_active_preparation_folder':folder},clear=True), \
                patch.object(supervisor,'dossier',return_value=({'keyword-selector.json':{'mainKeyword':'기능성 소재'}},{})), \
                patch.object(supervisor,'authorize_next',return_value=plan),patch.object(supervisor,'acquire_recovery_sources'), \
                patch.object(supervisor,'lineage'),patch.object(r,'collect_evidence',return_value={'primarySourceCandidates':[]}), \
                patch('common.source_discovery.search_urls',return_value=[source]),patch.object(cf,'source_snapshot',return_value=source), \
                patch.object(r,'is_bridge_account',return_value=False),patch.object(r,'_prepare_content',side_effect=prepare):
            r._supervise_prewriting('yoon_master',None,False,None,r.MaterialRequired('missing'))
        self.assertTrue(captured[0]['_editorial_conceptual_scope'])
        self.assertEqual(captured[0]['_editorial_source_urls'],[url])

    def test_pure_conceptual_calculation_has_no_artificial_fact_quota(self):
        result={'facts':[],'researchMd':'Explicit hypothetical: 2640 / 12 = 220; no measured income claim.',
                'answerBrief':{'readerTask':{'medium':'conceptual','articleType':'calculation'},
                               'readyForWriter':True,'missingInputs':[],'unresolvedQuestions':[]}}
        sources=[{'url':'https://www.gov.kr/unrelated'}]
        self.assertEqual(r.require_research_facts(result,sources),[])
        result['answerBrief']['missingInputs']=[{'kind':'source_fact'}]
        with self.assertRaises(RuntimeError):r.require_research_facts(result,sources)
        result['answerBrief']['missingInputs']=[]
        result['answerBrief']['readerTask']['medium']='screen'
        with self.assertRaises(RuntimeError):r.require_research_facts(result,sources)

    def test_empty_research_facts_create_real_acquisition_request(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(r.MaterialRequired):
                r.require_research_facts({'facts':[],'researchMd':'No supported body facts'},
                    [{'url':'https://www.gov.kr/page'}],recovery_folder=folder,reader_goal={'question':'실제 질문'})
            packet=json.loads((Path(folder)/'required-materials.json').read_text())
            self.assertEqual(packet['readerGoal']['question'],'실제 질문')
            self.assertEqual(packet['requiredMaterials'][0]['kind'],'source_fact')

    def test_researcher_only_sees_selected_query_bodies_and_url_schema(self):
        selected=evidence();seed=copy.deepcopy(selected)
        seed['query']='initial seed query'
        for row in seed['competitors']:
            row['url']=row['url'].replace('/123','/999')
            row['excerpt']['text']='Initial seed-only competitor body'
        context={'evidence':seed,'selectedEvidence':selected,'sources':[{'url':'https://www.gov.kr/official'}]}
        original=copy.deepcopy(context)
        results={'keyword-selector':{'mainKeyword':'specific query'}}
        inputs=r.researcher_input_context(context,results)
        self.assertNotIn('evidence',inputs)
        text=json.dumps(inputs)
        self.assertNotIn('Initial seed-only competitor body',text)
        for row in seed['competitors']:self.assertNotIn(row['url'],text)
        for row in selected['competitors']:
            self.assertIn(row['url'],text);self.assertIn(row['excerpt']['text'],text)
        urls=[row['url'] for row in selected['competitors']]
        schema=r.agent_output_schema('researcher',['https://www.gov.kr/official'],urls)
        self.assertEqual(schema['properties']['editorialDecision']['properties']['competitorFindings']['items']['properties']['url']['enum'],urls)
        self.assertEqual(context,original)

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

    def failed_writer_fixture(self, base):
        folder=base/'output'/'soultin'/'failed';folder.mkdir(parents=True)
        question='Is the proposed age change legally confirmed?'
        goal={'question':question,'successCondition':'Determine current proposal status','requiredAnswers':['Proposal legal status']}
        selection={'mainKeyword':'pension','title':'Proposed age status','readerQuestion':question,'readerGoal':goal,
            'demandEvidence':{'eligible':True,'mainKeyword':'pension','measuredQuery':'pension'}}
        writer={'title':selection['title'],'readerTask':{'articleType':'explainer','medium':'conceptual','question':question,
            'successCondition':goal['successCondition'],'requiredMaterialIds':[]},
            'blocks':[{'kind':'paragraph','text':'The available source establishes current age, but not proposal status.'}]}
        context={'account':'soultin','publicationDate':'2026-10-22','scheduledSlot':'11:00','strategyOverride':None,
            'publicationAttempt':False,'runOptions':{'publication_date':'2026-10-22'}}
        review={'inputs':r.reader_demand_alignment_inputs(selection,writer),
            'verdict':{'relation':'exact_subject',**dict.fromkeys(('matchesQuestion','matchesTitle','titleClear','titleNatural'),True),
                'fulfillsRequestedTask':False,'answerAudit':{'intentResolved':False},'issues':['Core proposal status unsupported']},
            'modelEvents':[{'state':'returned','model':'actual-test-model'}]}
        for name,value in {'keyword-selector.json':selection,'writer.json':writer,'writer-demand-alignment.json':review,
                           'sources.json':[],'preparation-context.json':context}.items():r.atomic_json(folder/name,value)
        r.atomic_json(folder/'handoff.json',{'account':'soultin','stages':[
            {'agent':'keyword-selector','fileHashes':{'keyword-selector.json':r.sha(folder/'keyword-selector.json')}},
            {'agent':'researcher','fileHashes':{'sources.json':r.sha(folder/'sources.json')}}]})
        return folder,context

    def test_saved_failure_reselection_requires_real_bound_review_and_source_gap(self):
        from unittest.mock import Mock
        with tempfile.TemporaryDirectory() as tmp:
            base=Path(tmp);folder,context=self.failed_writer_fixture(base)
            options={'publication_date':'2026-10-22'}
            def classify(prompt,observer=None,**kwargs):
                observer('test','actual-model','returned',actual_model='actual-model')
                return {'unsupportedCoreFact':True,'reason':'Core proposal status absent from fetched sources'}
            def fresh(*args,**kwargs):
                self.assertFalse(r.RUN_OPTIONS['allow_retry_handoff'])
                self.assertEqual(r.RUN_OPTIONS['_excluded_automatic_topics'][0]['mainKeyword'],'pension')
                self.assertEqual(args[4],'11:00')
                return ({},base/'alternative',{},[],{},0)
            with patch.object(r,'BASE_DIR',base),patch.object(r,'RUN_OPTIONS',options),patch.object(r,'read_journal',return_value={'attempts':[]}),patch.object(r,'_PIPELINE_LOCK_OWNER',(os.getpid(),threading.get_ident())),patch.object(r,'generate_content_json',side_effect=classify),patch.object(r,'_prepare_content',side_effect=fresh) as prepare:
                data=r.unresolved_writer_review('soultin',folder)
                failure=r.ReaderTaskUnfulfilled(folder,data['hashes']['writer-demand-alignment.json'])
                result=r._reselect_failed_preparation('soultin',folder,failure)
                self.assertEqual(result[1],base/'alternative');prepare.assert_called_once()
                self.assertEqual(options,{'publication_date':'2026-10-22'})
                for name,digest in data['hashes'].items():self.assertEqual(r.sha(folder/name),digest)
                with self.assertRaises(r.MaterialRequired):r._reselect_failed_preparation('soultin',folder,failure)
                self.assertEqual(prepare.call_count,1)
                alternative=base/'output'/'soultin'/'alternative';alternative.mkdir()
                options['_candidate_budget_origin']=str(folder)
                with self.assertRaises(r.MaterialRequired):
                    r.claim_repair_budget('soultin',alternative,context,False,kind='candidate-reselection')
                options.pop('_candidate_budget_origin')
                r.atomic_json(folder/'writer-demand-alignment.json',{'verdict':{'fulfillsRequestedTask':False}})
                with self.assertRaises(RuntimeError):r.unresolved_writer_review('soultin',folder)

    def test_alternative_retains_editorial_repair_but_never_recursively_reselects(self):
        for kind in ('editorial','unresolved','materials'):
            with self.subTest(kind=kind),tempfile.TemporaryDirectory() as tmp:
                base=Path(tmp);folder,context=self.failed_writer_fixture(base)
                def classify(prompt,observer=None,**kwargs):
                    observer('test','actual-model','returned',actual_model='actual-model')
                    return {'unsupportedCoreFact':True,'reason':'Unsupported core fact'}
                error=RuntimeError('structured assembler failure') if kind=='editorial' else (
                    r.ReaderTaskUnfulfilled(base/'alternative','new-failure') if kind=='unresolved' else r.MaterialRequired('Missing actual evidence'))
                with patch.object(r,'BASE_DIR',base),patch.object(r,'RUN_OPTIONS',{'publication_date':'2026-10-22'}),patch.object(r,'read_journal',return_value={'attempts':[]}),patch.object(r,'_PIPELINE_LOCK_OWNER',(os.getpid(),threading.get_ident())),patch.object(r,'generate_content_json',side_effect=classify) as judge,patch.object(r,'_prepare_content',side_effect=error) as prepare,patch.object(r,'repair_preparation_once',return_value=({},base/'alternative',{},[],{},0)) as repair:
                    data=r.unresolved_writer_review('soultin',folder)
                    failure=r.ReaderTaskUnfulfilled(folder,data['hashes']['writer-demand-alignment.json'])
                    if kind=='editorial':
                        self.assertEqual(r._reselect_failed_preparation('soultin',folder,failure)[1],base/'alternative')
                        repair.assert_called_once_with('soultin',None,None,False,'11:00',error)
                    else:
                        with self.assertRaises(r.MaterialRequired):r._reselect_failed_preparation('soultin',folder,failure)
                        repair.assert_not_called()
                    prepare.assert_called_once();judge.assert_called_once()

    def test_fixed_question_and_repeated_intent_cannot_be_reselected(self):
        excluded=[{'mainKeyword':'pension','readerQuestion':'What is the proposal status?'}]
        r.require_new_automatic_topic({'mainKeyword':'pension','readerQuestion':'Different question?'},excluded)
        for selection in ({'mainKeyword':'different','readerQuestion':'What is the proposal status?'},):
            with self.assertRaises(r.MaterialRequired):r.require_new_automatic_topic(selection,excluded)
        r.require_new_automatic_topic({'mainKeyword':'basic pension application','readerQuestion':'Which application documents?'},excluded)
        with tempfile.TemporaryDirectory() as tmp:
            base=Path(tmp);folder,_=self.failed_writer_fixture(base)
            with patch.object(r,'BASE_DIR',base),patch.object(r,'RUN_OPTIONS',{'topic_seed':'User fixed question'}),patch.object(r,'claim_repair_budget') as budget:
                data=r.unresolved_writer_review('soultin',folder)
                with self.assertRaises(r.MaterialRequired):r._reselect_failed_preparation('soultin',folder,r.ReaderTaskUnfulfilled(folder,data['hashes']['writer-demand-alignment.json']))
                budget.assert_not_called()

    def test_shared_broad_query_requires_independent_distinct_task_review(self):
        question='How do early and deferred pension choices compare in monthly and cumulative amounts?'
        selection={'mainKeyword':'pension','readerQuestion':question,'title':'Compare early and deferred pension amounts',
            'demandEvidence':{'eligible':True,'mainKeyword':'pension','measuredQuery':'pension'},
            'excludedAutomaticTopics':[{'mainKeyword':'pension','readerQuestion':'Is the age 68 proposal confirmed?',
                'readerGoal':{'question':'Is the age 68 proposal confirmed?','successCondition':'Know proposal status','requiredAnswers':['Status']},
                'reason':'Official proposal status not supported'}]}
        excluded=selection.pop('excludedAutomaticTopics')
        goal={'question':question,'successCondition':'Compare both payment choices','requiredAnswers':['Monthly difference','Cumulative difference']}
        valid={'relation':'direct_subtask',**dict.fromkeys(('matchesQuestion','matchesTitle','titleClear','titleNatural'),True),
            'issues':[],'readerGoal':goal,'distinctFromExcludedTasks':True,'reason':'Different concrete calculation task'}
        def judge(prompt,observer=None,response_schema=None):
            self.assertIn('excludedReaderTasks',prompt)
            self.assertIn('distinctFromExcludedTasks',response_schema['properties'])
            return valid
        r.require_new_automatic_topic(selection,excluded)
        receipt=r.review_reader_demand_alignment(selection,judge=judge,excluded_tasks=excluded)
        self.assertTrue(receipt['verdict']['distinctFromExcludedTasks'])
        valid['distinctFromExcludedTasks']=False
        with self.assertRaisesRegex(RuntimeError,'excluded reader intent'):
            r.review_reader_demand_alignment(selection,judge=judge,excluded_tasks=excluded)

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
