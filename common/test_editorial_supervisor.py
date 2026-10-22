import asyncio
import datetime as dt
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from contextlib import nullcontext,closing
from types import SimpleNamespace
from unittest.mock import patch,AsyncMock

from common import editorial_supervisor as supervisor


class SupervisorTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.folder=self.root/'failed';self.folder.mkdir()

    def save(self,name,data):
        path=self.folder/name;path.write_text(json.dumps(data));return path

    def model(self,question='확인된 제도의 뜻은 무엇인가요?',sources=None):
        def generate(prompt,**kwargs):
            kwargs['observer']('codex','configured','returned',actual_model='actual-model')
            return {'approved':True,'category':'evidence','reason':'관찰한 공식 자료에 한정해 새 기획',
                    'readerQuestion':question,'searchQuery':'공식 제도 기준','sourceUrls':sources or []}
        return generate

    def test_no_sources_promotes_scope_to_fresh_pivot_and_preserves_original(self):
        path=self.save('required-materials.json',{'requiredMaterials':[{'kind':'actual_capture'}]})
        before=path.read_bytes()
        with patch('common.llm_client.generate_json',side_effect=self.model()), \
                patch('common.llm_settings.get_agent_brain',return_value={'provider':'codex','model':'configured'}),patch.object(supervisor,'event'):
            result=supervisor.authorize('cf_blog','example.com',self.folder,'scope','missing inputs')
        self.assertEqual(result['step'],'pivot')
        self.assertFalse(result['oldQuestionSolved'])
        self.assertTrue(result['freshReviewRequired'])
        self.assertEqual(path.read_bytes(),before)
        self.assertEqual(result['routes'][0]['model'],'actual-model')

    def test_unobserved_scope_sources_are_rejected(self):
        self.save('sources.json',{'sources':[{'url':'https://www.gov.kr/page','text':'actual observed body '*20}]})
        with patch('common.llm_client.generate_json',side_effect=self.model(sources=['https://invented.test/'])), \
                patch('common.llm_settings.get_agent_brain',return_value={'provider':'codex','model':'configured'}),patch.object(supervisor,'event'):
            with self.assertRaisesRegex(ValueError,'unobserved'):supervisor.authorize('cf_blog','example.com',self.folder,'scope','missing screen')
        self.assertFalse((self.folder/'jarvis-scope-approval.json').exists())

    def test_submission_and_accepted_writer_cannot_be_pivoted(self):
        path=self.save('reservation-evidence.json',{'submissionStatus':'unknown'})
        with self.assertRaisesRegex(RuntimeError,'reconciliation'):supervisor.authorize('naver_blog','a',self.folder,'pivot','error')
        path.unlink();self.save('handoff.json',{'stages':[{'agent':'writer'}]})
        with self.assertRaisesRegex(RuntimeError,'targeted rework'):supervisor.authorize('cf_blog','example.com',self.folder,'pivot','error')

    def test_query_cannot_silently_change_question(self):
        with patch('common.llm_client.generate_json',side_effect=self.model()) as generate, \
                patch('common.llm_settings.get_agent_brain',return_value={'provider':'codex','model':'configured'}),patch.object(supervisor,'event'):
            with self.assertRaisesRegex(supervisor.QuestionRebindingRequired,'original question'):
                supervisor.authorize('cf_blog','example.com',self.folder,'query','missing','원래 질문 그대로 유지해야 합니다')
        self.assertEqual(generate.call_args.kwargs['response_schema']['properties']['readerQuestion']['enum'],
                         ['원래 질문 그대로 유지해야 합니다'])

    def test_structured_budget_preserves_valid_json_source_identity_and_redacts_contacts(self):
        payload={'originalQuestion':'실제 질문 유지','sources':[
            {'url':f'https://www.gov.kr/{i}','body':'공식 내용 '*5000+' user@example.org',
             'bodySha256':'a'*64} for i in range(8)],'failure':{'large':'x'*40000}}
        encoded=supervisor.budgeted_evidence(payload)
        value=json.loads(encoded)
        self.assertLessEqual(len(encoded),22000)
        self.assertEqual(value['originalQuestion'],payload['originalQuestion'])
        self.assertEqual(len(value['sources']),8)
        self.assertEqual(value['sources'][0]['bodySha256'],'a'*64)
        self.assertNotIn('user@example.org',encoded)

    def test_changed_query_advances_to_separately_approved_scope(self):
        with patch.object(supervisor,'authorize',side_effect=[
                supervisor.QuestionRebindingRequired('changed intent'),{'step':'scope'}]) as authorize:
            result=supervisor.authorize_next('cf_blog','example.com',self.folder,
                ('query','scope','pivot'),'missing','original')
        self.assertEqual(result['step'],'scope')
        self.assertEqual([c.args[3] for c in authorize.call_args_list],['query','scope'])

    def test_consumed_query_advances_without_repeating_the_model_call(self):
        self.save('jarvis-query-approval.json',{'historical':'preserve'})
        with patch('common.llm_client.generate_json') as generate:
            with self.assertRaises(supervisor.ApprovalDeclined):
                supervisor.authorize('cf_blog','example.com',self.folder,'query','missing','same exact original question')
        generate.assert_not_called()

    def test_scoped_goal_cannot_expand_back_into_unobserved_ui_tasks(self):
        question='단위기간과 출석률은 어떻게 다른가요?'
        goal=supervisor.scoped_reader_goal(question)
        self.assertEqual(goal['question'],question)
        self.assertEqual(goal['requiredAnswers'],[question])
        self.assertNotIn('화면',goal['successCondition'])

    def test_live_event_contract_accepts_progress_and_links_staff_roles(self):
        with patch('common.crew_chat_bridge._deliver') as deliver,patch.object(supervisor,'ROOT',self.root):
            supervisor.event('cf_blog','example.com','query','추가 자료 조사')
        self.assertEqual(deliver.call_count,2)
        self.assertEqual([c.args[0]['who'] for c in deliver.call_args_list],['jarvis','radar'])
        self.assertTrue(all(c.args[0]['phase']=='progress' for c in deliver.call_args_list))
        self.assertEqual(len(json.loads((self.root/'server/data/editorial-live-events.json').read_text())['messages']),2)

    def test_conceptual_scope_uses_new_schema_without_mutating_original(self):
        schema={'properties':{'answerBrief':{'properties':{'readerTask':{'properties':{
            'medium':{'type':'string','enum':['screen','conceptual']},
            'articleType':{'type':'string','enum':['how_to','explainer']}}}}}}}
        scoped=supervisor.conceptual_schema(schema)
        task=scoped['properties']['answerBrief']['properties']['readerTask']['properties']
        self.assertEqual(task['medium']['enum'],['conceptual'])
        self.assertNotIn('how_to',task['articleType']['enum'])
        self.assertIn('screen',schema['properties']['answerBrief']['properties']['readerTask']['properties']['medium']['enum'])

    def test_public_footer_contacts_do_not_block_supervisor_or_enter_context(self):
        from common.hermes_memory import learning_text
        raw='실제 제도 기준 및 조건. Contact person@example.org 010-1234-5678 cookie: session-value'
        clean=supervisor.private_text_removed(raw)
        self.assertNotIn('person@example.org',clean)
        self.assertNotIn('session-value',clean)
        self.assertIn('실제 제도 기준',learning_text(clean))

    def test_public_numeric_identifiers_are_not_private_phone_substrings(self):
        from common.hermes_memory import learning_text
        value='공공 문서 식별자 https://www.gov.kr/01012345678 202601012345678'
        self.assertEqual(learning_text(value),value)
        for secret in ('연락처 010-1234-5678', 'user@example.org', 'cookie: actual-session'):
            with self.assertRaises(ValueError):learning_text(secret)

    def test_owned_body_can_bind_scope_but_remains_secondary_evidence(self):
        url='https://www.justinfo.co.kr/guide'
        self.save('sources.json',[{'url':'https://www.gov.kr/rule','text':'host official body '*40}])
        self.save('bridge-body-observations.json',{'candidates':[{
            'url':url,'canonicalUrl':url,'articleBodySha256':'a'*64,'bodyExcerpt':'observed guide body '*40}]})
        with patch('common.llm_client.generate_json',side_effect=self.model(sources=[url])) as generate, \
                patch('common.llm_settings.get_agent_brain',return_value={'provider':'codex','model':'configured'}),patch.object(supervisor,'event'):
            result=supervisor.authorize('naver_blog','adinfo0905',self.folder,'scope','bridge mismatch')
        self.assertEqual(result['step'],'scope')
        self.assertTrue(result['freshReviewRequired'])
        self.assertIn(url,generate.call_args.kwargs['response_schema']['properties']['sourceUrls']['items']['enum'])
        self.assertIn('secondary guides',generate.call_args.args[0])

    def test_graph_is_connected_idempotent_and_only_public_outcomes_learn(self):
        approval={'originalQuestion':'Original','originalHashes':{},'step':'scope','approvedAt':1,
                  'approval':{'readerQuestion':'Narrow','reason':'Observed support'}}
        saved=self.save('approval.json',approval)
        approval.update(approvalPath=str(saved),approvalSha256=hashlib.sha256(saved.read_bytes()).hexdigest())
        supervisor.lineage(self.folder,[approval])
        proof={'sourceRef':'strict-host-proof','sourceSha256':'a'*64}
        with patch('common.hermes_memory.verified_work_proof',return_value={'outcome':'reservation_verified'}):
            with self.assertRaises(ValueError):supervisor.learn_public(self.folder,proof,'cf_blog','example.com',self.root,public_url='https://example.com/post')
        with patch('common.hermes_memory.verified_work_proof',return_value={'outcome':'public_verified'}):
            for _ in range(2):supervisor.learn_public(self.folder,proof,'cf_blog','example.com',self.root,public_url='https://example.com/post')
        graph=json.loads((self.root/'server/data/editorial-memory-graph.json').read_text())
        self.assertEqual(len(graph['nodes']),4);self.assertEqual(len(graph['edges']),3)
        pattern=next(n for n in graph['nodes'].values() if n.get('type')=='ProblemPattern')
        self.assertEqual(pattern['resolvedCount'],1);self.assertEqual(len(pattern['concreteExamples']),1)
        self.assertEqual(pattern['concreteExamples'][0]['publicUrl'],'https://example.com/post')
        connected={e[k] for e in graph['edges'] for k in ('source','target')}
        self.assertEqual(connected,set(graph['nodes']))
        with patch('common.hermes_memory.verified_work_proof',return_value={'outcome':'public_verified'}):
            self.assertEqual(len(supervisor.lessons('cf_blog','example.com',self.root)),1)
        self.assertEqual(supervisor.lessons('cf_blog','example.com',self.root),[])
        self.assertEqual(supervisor.lessons('cf_blog','other.com',self.root),[])
        outcome=next(v for v in graph['nodes'].values() if v['type']=='Outcome')
        self.assertIsNone(outcome['revenue'])

    def test_cf_three_step_replanning_reaches_writer_without_changing_failure(self):
        from cf_posting import pipeline_runner as runner
        self.save('prewriter-acquisition-request.json',{'readerGoal':{'question':'Original question'}})
        target=self.root/'success';target.mkdir()
        handoff=SimpleNamespace(folder=target)
        calls=AsyncMock(side_effect=[runner.ReviewRequired('missing'),runner.ReviewRequired('still missing'),
                                     runner.ReviewRequired('empty sources'),({'title':'valid'},handoff)])
        def approve(project,identity,folder,step,*args):
            return {'step':step,'approval':{'readerQuestion':'Original question' if step=='query' else 'New supported question',
                                          'searchQuery':'official query'}}
        with patch.dict(runner.RUN_CONTEXT,{'artifactFolder':str(self.folder)}),patch.object(runner,'_draft_agents_once',calls), \
                patch.object(supervisor,'authorize',side_effect=approve),patch.object(supervisor,'lineage') as lineage, patch.object(supervisor,'acquire_recovery_sources',return_value={}):
            result=asyncio.run(runner.draft_agents('example.com','생활',[],[],None,None,lambda *a:None,None))
        self.assertEqual(result[0]['title'],'valid')
        self.assertEqual(calls.await_count,4)
        self.assertTrue(calls.await_args_list[2].args[-1]['supervisorScope'])
        self.assertTrue(calls.await_args_list[3].args[-1]['supervisorScope'])
        self.assertEqual([p['step'] for p in lineage.call_args.args[1]],['query','scope','pivot'])

    def test_watchdog_reclaims_frozen_review_without_replaying_uncertain_submission(self):
        from cf_posting import pipeline_runner as runner
        now=dt.datetime.now(supervisor.KST)
        path=self.root/'schedule.json'
        state={'date':now.date().isoformat(),'items':[
            {'domain':'waiting.example','order':1,'status':'waiting','scheduledTime':'00:00'},
            {'domain':'review.example','order':2,'status':'review_required','scheduledTime':'00:00'},
            {'domain':'uncertain.example','order':0,'status':'failed','scheduledTime':'00:00','submissionStarted':True}]}
        path.write_text(json.dumps(state))
        with patch.object(supervisor,'refresh_measurements'),patch.object(supervisor,'event'), \
                patch.object(runner,'SCHEDULE_JSON',path),patch.object(runner,'cleaner_lock',return_value=nullcontext(True)), \
                patch.object(runner,'reconcile_item',return_value=False), \
                patch.object(runner,'publication_may_be_inflight',side_effect=lambda r:bool(r.get('submissionStarted'))), \
                patch.object(runner,'run_publisher_for_item',return_value=True) as publish:
            result=supervisor.recover_cycle('cf_blog')
        self.assertEqual(result['identity'],'review.example')
        self.assertIn('nextRetryAt',publish.call_args.args[0])
        self.assertIs(publish.call_args.kwargs['_repair_authorization'],runner._REPAIR_AUTHORIZATION)
        ledger=json.loads(path.read_text())
        self.assertNotIn('editorialRecoveryCycles',ledger['items'][2])

    def test_model_proposal_body_cannot_become_observed_source(self):
        rows=supervisor.observed_sources({'researcher.json':{'url':'https://www.gov.kr/fake','text':'invented '*60},
            'sources.json':[{'url':'https://www.gov.kr/real','text':'host fetched '*60}]})
        self.assertEqual([row['url'] for row in rows],['https://www.gov.kr/real'])
        self.assertEqual(len(rows[0]['bodySha256']),64)

    def test_cf_checkpoint_preserves_accepted_assembly_instead_of_replanning(self):
        from cf_posting import pipeline_runner as runner
        folder=self.root/'output'/'draft';folder.mkdir(parents=True)
        agents=runner.Handoff.agents
        rows=[{'agent':name} for name in agents[:4]]
        (folder/'handoff.json').write_text(json.dumps({'stages':rows}))
        (folder/'article.json').write_text(json.dumps({'topicSlug':'draft'}))
        handoff=SimpleNamespace(check=lambda:rows)
        with patch.object(runner,'BASE_DIR',self.root),patch.object(runner,'publication_may_be_inflight',return_value=False), \
                patch.object(runner,'require_prewriting_handoff'),patch.object(runner,'Handoff',return_value=handoff) as cls:
            cls.agents=agents
            result=runner.preserved_rework_checkpoint({'domain':'example.com','artifactFolder':'output/draft'})
        self.assertEqual(result,{'folder':str(folder),'mode':'assembly'})
        rows.pop();(folder/'handoff.json').write_text(json.dumps({'stages':rows}))
        with patch.object(runner,'BASE_DIR',self.root),patch.object(runner,'publication_may_be_inflight',return_value=False), \
                patch.object(runner,'require_prewriting_handoff'),patch.object(runner,'Handoff',return_value=handoff) as cls:
            cls.agents=agents
            self.assertEqual(runner.preserved_rework_checkpoint({'domain':'example.com','artifactFolder':'output/draft'})['mode'],'assets')

    def test_keyword_identity_mismatch_requests_schema_bound_repair(self):
        from cf_posting import pipeline_runner as runner
        candidate={'mainKeyword':'기초연금','question':'기초연금 기준을 어떻게 이해하나요?',
                   'category':'제도','title':'기초연금 기준 이해하기','topicSlug':'pension-criteria-explained'}
        wrong={**candidate,'mainKeyword':'다른 키워드','selectedCandidateIndex':0}
        class CorrectionReached(Exception):pass
        calls=[]
        def generate(prompt,response_schema=None):
            calls.append(response_schema)
            if len(calls)==1:return {'candidates':[candidate]}
            if len(calls)==2:return wrong
            properties=response_schema['properties']
            self.assertEqual(properties['selectedCandidateIndex']['enum'],[0])
            for field in ('mainKeyword','title','topicSlug'):
                self.assertEqual(properties[field]['enum'],[candidate[field]])
            raise CorrectionReached()
        measured={'candidates':[{'eligible':True,'currentIssue':True,'volume':{'monthlyLowerBound':1000},
                                'issueSignals':['ongoingDemand'],'news':[]}]}
        with patch.object(runner,'_news',return_value=([],None)),patch.object(runner,'keyword_demand_evidence',return_value=measured):
            with self.assertRaises(CorrectionReached):
                runner.select_keyword_with_demand('instruction',{'preferredCategory':'제도'},generate)
        self.assertEqual(len(calls),3)

    def test_stale_kin_draft_requires_fresh_same_question_independent_review(self):
        from naver_kin import pipeline,authoring
        from naver_kin.test_pipeline import document
        old_day=(dt.datetime.now(supervisor.KST)-dt.timedelta(days=1)).date().isoformat()
        with patch.object(pipeline,'today_kst',return_value=old_day):old=document()
        new=document();output=self.root/'fresh';output.mkdir()
        with closing(pipeline.connect(self.root/'ledger.sqlite3')) as db:
            qid=pipeline.import_draft(db,old)
            with patch.object(pipeline,'ROOT',self.root),patch.object(pipeline,'account_lock',return_value=nullcontext()), \
                    patch.object(authoring,'generate_for_slot',return_value={'document':new,'artifact_dir':str(output)}) as regenerate, \
                    patch.object(supervisor,'event'):
                self.assertTrue(authoring.renew_stale_draft(db,'adinfo0905',qid,'slot','model'))
            stored=json.loads(db.execute('SELECT document FROM questions WHERE question_id=?',(qid,)).fetchone()[0])
            self.assertEqual(stored['attribution']['publicationDate'],pipeline.today_kst())
            self.assertEqual(stored['question']['question_url'],old['question']['question_url'])
            self.assertEqual(regenerate.call_args.kwargs['question_urls'],[old['question']['question_url']])
            self.assertTrue((output/'editorial-lineage.json').exists())

    def test_pipelines_use_assigned_staff_model_and_effort(self):
        from cf_posting import pipeline_runner as cf
        from naver_blog_posting import pipeline_runner as naver
        brain={'provider':'codex','model':'assigned-staff-model','reasoningEffort':'xhigh'}
        with patch('common.llm_settings.load',return_value={'active':'gemini'}), \
                patch('common.llm_settings.get_agent_brain',return_value=brain) as settings, \
                patch.object(cf,'generate_with_prompt_budget',return_value={}) as generate, \
                patch.dict(cf.RUN_CONTEXT,{'agent':'researcher','artifactFolder':str(self.folder)}):
            cf.call_model_json('test',response_schema={'type':'object'})
            self.assertEqual(settings.call_args.args[0],'radar')
            self.assertEqual(generate.call_args.args[1],'codex')
            self.assertEqual(generate.call_args.kwargs['model_override'],'assigned-staff-model')
            self.assertEqual(generate.call_args.kwargs['reasoning_effort'],'xhigh')
        with patch('common.llm_settings.load',return_value={'active':'gemini'}), \
                patch('common.llm_settings.get_agent_brain',return_value=brain) as settings, \
                patch.object(naver,'generate_json',return_value={}) as generate:
            naver.generate_content_json('test','reviewer')
            self.assertEqual(settings.call_args.args[0],'doctor')
            self.assertEqual(generate.call_args.kwargs['provider'],'codex')
            self.assertEqual(generate.call_args.kwargs['model_override'],'assigned-staff-model')
            self.assertEqual(generate.call_args.kwargs['reasoning_effort'],'xhigh')

    def test_naver_future_slot_prepares_after_preparation_time(self):
        from naver_blog_posting import pipeline_runner as runner
        class FixedDatetime(dt.datetime):
            @classmethod
            def now(cls,tz=None):return cls(2026,10,22,12,0,tzinfo=tz)
        source=self.root/'dashboard/naver_automation.json';source.parent.mkdir()
        source.write_text(json.dumps({'accounts':[{'account':'soul5373','preparationTime':'09:00',
            'slots':[{'scheduledSlot':'20:00','publicationDate':'2026-10-22','status':'waiting'}]}]}))
        with patch.object(supervisor,'ROOT',self.root),patch.object(supervisor.dt,'datetime',FixedDatetime), \
                patch.object(supervisor,'event'),patch.object(supervisor,'refresh_measurements'), \
                patch.object(runner,'pipeline_busy',return_value=False),patch.object(runner,'account_gate',return_value='waiting'),patch.object(runner,'read_journal',return_value={'attempts':[]}), \
                patch.object(runner,'run_accounts',return_value={'status':'prepared_and_reserved'}) as run:
            supervisor.recover_cycle('naver_blog')
        self.assertEqual(run.call_args.kwargs['slot'],'20:00')
        self.assertEqual(run.call_args.kwargs['publication_date'],'2026-10-22')

    def test_verified_housing_sources_are_collectable_without_accepting_lookalikes(self):
        from cf_posting.pipeline_runner import primary_url
        from naver_blog_posting.pipeline_runner import is_primary_source_host
        for host in ('www.applyhome.co.kr','apply.lh.or.kr','www.khug.or.kr'):
            self.assertTrue(primary_url('https://'+host+'/'))
            self.assertTrue(is_primary_source_host(host))
        self.assertFalse(primary_url('https://applyhome.co.kr.attacker.example/'))
        self.assertFalse(is_primary_source_host('applyhome.co.kr.attacker.example'))


if __name__=='__main__':unittest.main()
