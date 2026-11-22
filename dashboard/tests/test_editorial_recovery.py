import copy
import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock,patch

from common import editorial_recovery as recovery
from common.collection_observability import load,write


class EditorialRecoveryTests(unittest.TestCase):
    def test_rewording_without_factual_progress_requires_new_evidence(self):
        from unittest.mock import Mock
        generate=Mock(return_value=self.proposal)
        def unsupported(document):
            recovery.write(self.folder/'claim-review-response.json',{'status':'changes_required',
                'issues':['Official interval source missing','Official coverage source missing']})
            raise ValueError('Draft held: independent factual/experience review missing or mismatched')
        with self.assertRaisesRegex(ValueError,'without validated progress'):
            recovery.review_and_repair(self.document,self.folder,[unsupported],generate=generate)
        generate.assert_called_once()
        state=recovery.load(self.folder/'editorial-recovery.json')
        self.assertEqual(state['status'],'needs_new_evidence')
        self.assertEqual(state['owner'],'radar')
        self.assertFalse(state['publicationVerified'])

    def test_native_identity_gate_is_not_sent_into_repeated_editorial_rewriting(self):
        import json
        from unittest.mock import Mock
        generate=Mock()
        def identity_gate(document):
            raise ValueError('Draft held: cached evidence requires the registered bounded repair revision: Input/research/article topic identity mismatch')
        before=json.loads(json.dumps(self.document))
        with self.assertRaisesRegex(ValueError,'registered bounded repair revision'):
            recovery.review_and_repair(self.document,self.folder,[identity_gate],generate=generate)
        generate.assert_not_called()
        self.assertEqual(self.document,before)
        state=recovery.load(self.folder/'editorial-recovery.json')
        self.assertEqual(state['status'],'needs_registered_identity_repair')
        self.assertEqual(state['owner'],'patch')
        self.assertFalse(state['publicationVerified'])

    def test_reviewed_native_handoff_preserves_real_holds(self):
        from common import work_agenda as agendas
        with tempfile.TemporaryDirectory() as folder:
            with patch.object(agendas,'ROWS',Path(folder)/'rows'),patch.object(agendas,'get') as get,patch.object(agendas,'_save') as save,patch.object(agendas,'running',return_value=[]),patch('common.repair_workflow.agenda_recovery_blocker',return_value='') as blocker:
                row={'id':'original','status':'blocked','blocker':'acceptance_unverified'}
                get.return_value=row.copy();recovery.resume_reviewed_agenda('original')
                self.assertEqual(save.call_args.args[0]['status'],'recovering')
                self.assertEqual(save.call_args.args[0]['blocker'],'acceptance_unverified')
                for extra in ({'status':'suspended'},{'blocker':'authentication'},{'switchRequest':True},{'resumeCondition':'user_control'}):
                    save.reset_mock();get.return_value={**row,**extra};recovery.resume_reviewed_agenda('original');save.assert_not_called()
                save.reset_mock();get.return_value=row.copy();blocker.return_value='budget_exhausted'
                recovery.resume_reviewed_agenda('original');save.assert_not_called()

    def test_reviewed_waiting_native_handoff_wakes_only_after_handler_change(self):
        row={'status':'returned','result':{'status':'reviewed_waiting_native_resume'},'handlerSha256':'old'}
        self.assertTrue(recovery.repaired_engine_ready(row,'new'))
        self.assertFalse(recovery.repaired_engine_ready(row,'old'))
        self.assertFalse(recovery.repaired_engine_ready({**row,'result':{'status':'unknown'}},'new'))

    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.folder=self.root/'naver_blog_posting/output/work';self.folder.mkdir(parents=True)
        self.document={'title':'Original reader question','blocks':[{'type':'heading','text':'Original heading'},
            {'type':'text','text':'Missing answer'}]}
        self.proposal={'sourceQueries':[],'edits':[{'path':'blocks/1/text','value':'Observed complete answer'}],'reason':'Address reviewer defect'}
        p=patch.object(recovery,'ROOT',self.root);p.start();self.addCleanup(p.stop)
        p=patch('common.operating_plan.enabled',return_value=True);p.start();self.addCleanup(p.stop)

    def check(self,document):
        if document['blocks'][1]['text']!='Observed complete answer':raise ValueError('Draft held: essential answer missing')
        return {'status':'passed'}

    def test_failed_research_without_a_draft_acquires_sources_before_native_writer(self):
        folder=self.root/'cf_posting/output/scheduled/2026-11-07/baronote.kr';folder.mkdir(parents=True)
        calls=[]
        def acquire(*args):calls.append('acquire');return ['https://official.example']
        def author(account,item,path):
            self.assertEqual(calls,['acquire']);self.assertEqual(account,'baronote.kr');self.assertEqual(path,folder)
            calls.append('write');return {'title':'Same assigned question','contentHtml':'Observed answer'}
        with patch.object(recovery,'acquire',side_effect=acquire),patch('cf_posting.posting.basic_article',side_effect=author):
            result=recovery.prepare_missing_cf_draft(folder,'baronote.kr',{'domain':'baronote.kr'},['official source query'])
        self.assertEqual(calls,['acquire','write']);self.assertEqual(result['title'],'Same assigned question')

    def test_missing_draft_recovery_preserves_existing_submission_before_fetch_or_writer(self):
        folder=self.root/'cf_posting/output/work';folder.mkdir(parents=True)
        write(folder/'publication-receipt.json',{'state':'submission_unknown'})
        with patch.object(recovery,'acquire') as fetch,patch('cf_posting.posting.basic_article') as author:
            with self.assertRaises(ValueError):recovery.prepare_missing_cf_draft(folder,'baronote.kr',{},['query'])
        fetch.assert_not_called();author.assert_not_called()

    def test_engine_recovery_wakes_known_preparation_failure_but_not_auth_or_unchanged_no_progress(self):
        prior={'status':'needs_attention','reason':'Original failed draft is missing','handlerSha256':'old'}
        self.assertTrue(recovery.repaired_engine_ready(prior,'new'))
        self.assertFalse(recovery.repaired_engine_ready(prior,'old'))
        self.assertFalse(recovery.repaired_engine_ready({**prior,'reason':'Authentication required'},'new'))
        self.assertFalse(recovery.repaired_engine_ready({**prior,'status':'unknown'},'new'))
        self.assertTrue(recovery.repaired_engine_ready({**prior,'reason':'Draft held: review engine changed'},'old'))

    def test_identical_failed_source_request_is_not_queued_again_but_changed_query_can_resume(self):
        from common import conference_dispatch as conferences
        identity='b'*64;queue=self.root/'conferences';queue.mkdir()
        write(queue/(identity+'.json'),{'status':'failed','kind':'parameters','arguments':{'action':'cf-prepare'},
              'failureDiagnostic':{'errorMessage':'Draft held: missing official evidence'}})
        path=self.root/'dashboard/data/editorial-recovery-jobs'/(identity+'.json')
        with patch.object(conferences,'QUEUE',queue):
            self.assertEqual(recovery.request_repair(identity,['first official query'])['status'],'queued')
            prior=load(path);prior.update(status='needs_attention',reason='Draft held: no new evidence');write(path,prior)
            before=path.read_bytes()
            result=recovery.request_repair(identity,['first official query'])
            self.assertEqual(result['status'],'needs_new_evidence');self.assertEqual(before,path.read_bytes())
            self.assertEqual(recovery.request_repair(identity,['different official query'])['status'],'queued')

    def test_kin_control_hold_resumes_only_after_exact_native_account_space_returns(self):
        import sqlite3
        from naver_kin import posting as kin
        db=sqlite3.connect(':memory:');self.addCleanup(db.close);db.row_factory=sqlite3.Row
        db.execute('CREATE TABLE automation_halts(account TEXT PRIMARY KEY,reason TEXT,checked_at TEXT)')
        db.executemany('INSERT INTO automation_halts VALUES(?,?,?)',[('stone0747','browser_user_control','original'),('adinfo0905','account_protected','protected')]);db.commit()
        space={'name':'barolab-kin-stone0747','profileId':'Profile 7','ownership':'user','id':10}
        with patch('common.ego_taskspace.resolve_ego_profile',return_value='Profile 7'):
            self.assertEqual(kin._naver_scheduler_reconcile_browser_control(db,observe=lambda:{'spaces':[space]})['releasedAccounts'],[])
            self.assertEqual(kin._naver_scheduler_reconcile_browser_control(db,observe=lambda:{'spaces':[{**space,'ownership':'agent','profileId':'wrong'}]})['releasedAccounts'],[])
            result=kin._naver_scheduler_reconcile_browser_control(db,observe=lambda:{'spaces':[{**space,'ownership':'agent'}]})
        self.assertEqual(result['releasedAccounts'],['stone0747'])
        self.assertEqual(db.execute('SELECT reason FROM automation_halts').fetchone()[0],'account_protected')
        self.assertEqual(db.execute('SELECT COUNT(*) FROM automation_halt_history').fetchone()[0],1)

    def test_negative_feedback_reaches_writer_and_changed_draft_is_independently_rechecked(self):
        model=Mock(return_value=self.proposal);check=Mock(side_effect=self.check)
        original=copy.deepcopy(self.document)
        recovery.review_and_repair(self.document,self.folder,[check],generate=model)
        self.assertEqual(check.call_count,2);model.assert_called_once()
        self.assertIn('essential answer missing',model.call_args.args[0])
        self.assertEqual(self.document['title'],original['title'])
        self.assertEqual(self.document['blocks'][0],original['blocks'][0])
        state=load(self.folder/'editorial-recovery.json');self.assertEqual(state['status'],'reviewed')
        self.assertFalse(state['publicationVerified'])
        archived=list((self.folder/'editorial-revisions').glob('*/document.json'))
        self.assertEqual(load(archived[0]),original)

    def test_resumption_restores_reviewed_data_without_repeating_writer_call(self):
        original=copy.deepcopy(self.document)
        recovery.review_and_repair(self.document,self.folder,[self.check],generate=Mock(return_value=self.proposal))
        model=Mock(side_effect=AssertionError('Do not rewrite accepted data'))
        recovery.review_and_repair(original,self.folder,[self.check],generate=model)
        self.assertEqual(original,self.document);model.assert_not_called()

    def test_no_progress_is_durable_and_does_not_repeat_same_model_call(self):
        model=Mock(return_value={'sourceQueries':[],'edits':[],'reason':'No additional evidence'})
        for _ in range(2):
            with self.assertRaisesRegex(ValueError,'no (changed|new)'):
                recovery.review_and_repair(self.document,self.folder,[self.check],generate=model)
        model.assert_called_once()
        self.assertEqual(load(self.folder/'editorial-recovery.json')['owner'],'radar')

    def test_existing_submission_receipt_prevents_mutation_and_model_call(self):
        write(self.folder/'reservation-evidence.json',{'submissionStatus':'submission_unknown'})
        original=copy.deepcopy(self.document);model=Mock(return_value=self.proposal)
        with self.assertRaisesRegex(ValueError,'reconciliation'):
            recovery.review_and_repair(self.document,self.folder,[self.check],generate=model)
        self.assertEqual(self.document,original);model.assert_not_called()

    def test_sources_are_fetched_and_hashed_before_writer_can_use_them(self):
        from common import source_discovery as sources
        from datetime import datetime,timezone
        text='Official actual source text '*20;sha=hashlib.sha256(text.encode()).hexdigest()
        collected=datetime.now(timezone.utc).isoformat()
        write(self.folder/'research.json',{'collectedAt':collected,'sources':[]})
        with patch.object(sources,'search_urls',return_value=[{'url':'https://official.example/help','title':'Help'}]), \
             patch.object(sources,'public_text',return_value={'url':'https://official.example/help','text':text,'status':200,'textSha256':sha}) as fetch:
            observed=recovery.acquire(self.folder,['Original question official help'])
        fetch.assert_called_once();self.assertEqual(observed,['https://official.example/help'])
        snapshot=load(self.folder/'research.json')
        self.assertEqual(snapshot['sources'][0]['textSha256'],sha)
        self.assertEqual(snapshot['collectedAt'],collected)

    def test_assignment_executable_markup_and_new_external_links_cannot_be_patched(self):
        for path,value in [('title','Different assignment'),
                           ('blocks/1/text','https://unobserved.example/new')]:
            with self.assertRaises(ValueError):recovery.apply_edits(self.document,[{'path':path,'value':value}])
        html={'title':'Same','contentHtml':'<h2>Original</h2><p>Answer</p>'}
        for value in ('<h2>Original</h2><script>evil()</script>','<h2>Changed</h2><p>Answer</p>'):
            with self.assertRaises(ValueError):recovery.apply_edits(html,[{'path':'contentHtml','value':value}])

    def test_heading_defects_are_editable_and_all_review_findings_reach_one_repair(self):
        changed=recovery.apply_edits(self.document,[{'path':'blocks/0/text','value':'Evidence-based corrected heading'}])
        self.assertEqual(changed['title'],self.document['title']);self.assertEqual(changed['blocks'][0]['text'],'Evidence-based corrected heading')
        def second(doc):
            if doc['blocks'][1]['text']!='Observed complete answer':raise ValueError('Draft held: missing numeric evidence')
            return {'status':'passed'}
        model=Mock(return_value=self.proposal)
        recovery.review_and_repair(self.document,self.folder,[self.check,second],generate=model)
        model.assert_called_once();prompt=model.call_args.args[0]
        self.assertIn('essential answer missing',prompt);self.assertIn('missing numeric evidence',prompt)

    def test_insurer_public_rules_are_first_party_but_contract_and_mutation_routes_are_not(self):
        from common.content_improvement import primary_url
        for url in ['https://www.kbinsure.co.kr/CG301030001.ec','https://www.kbinsure.co.kr/CG301030002.ec',
                    'https://www.kbinsure.co.kr/CG205020003.ec',
                    'https://www.nps.or.kr/elctcvlcpt/comm/getOHAC0000M5.do?menuId=MN24001073',
                    'https://www.nps.or.kr/elctcvlcpt/comm/getOHAC0000M3.do?menuId=MN24001719',
                    'https://www.idbins.com/pc/bizxpress/my/ac/FWMYCV5027.shtm',
                    'https://www.directdb.co.kr/comm/bnf/evt/atarcDstTtyView.do?pageDvn=trvDstc']:
            self.assertTrue(primary_url(url),url)
            self.assertFalse(primary_url(url+'&mode=write' if '?' in url else url+'?mode=write'))
            self.assertFalse(primary_url(url.replace('www.','www.fake.')))
        self.assertTrue(primary_url('https://www.kbinsure.co.kr/CG212010002.ec'))
        self.assertFalse(primary_url('https://www.kbinsure.co.kr/api/contracts/123'))
        self.assertFalse(primary_url('https://www.kbinsure.co.kr:444/CG212010002.ec'))

    def test_authority_context_preserves_canonical_source_ids_and_original_evidence(self):
        from common.content_quality import authoritative_research_context
        research={'sources':[{'url':'https://background.example/guide','text':'Secondary background '*10000,'visualCandidates':[{'url':'https://background.example/unselected.png'}]},
                              {'url':'https://www.gov.kr/portal/rcvfvrSvc/dtlEx/known','text':'Exact official eligibility criteria'}]}
        original=copy.deepcopy(research);context=authoritative_research_context(research)
        self.assertEqual(research,original);self.assertEqual(context['sources'][1]['sourceId'],'1')
        self.assertEqual(context['sources'][1]['text'],research['sources'][1]['text'])
        self.assertEqual(context['sources'][0]['text'],'');self.assertEqual(context['evidencePresentation']['primarySourceIds'],['1'])
        self.assertEqual(context['sources'][0]['visualCandidateCount'],1);self.assertNotIn('visualCandidates',context['sources'][0])
        secondary={'sources':[research['sources'][0]]}
        self.assertEqual(authoritative_research_context(secondary)['sources'][0]['text'],secondary['sources'][0]['text'])
        low_risk=authoritative_research_context(research,{'title':'Desk arrangement','contentHtml':'<p>Compare desk shapes.</p>'})
        self.assertEqual(low_risk['sources'][0]['text'],research['sources'][0]['text'])

    def test_cf_correction_verifier_clears_stale_cache_and_never_replays_content_update(self):
        from common import cf_recovery as cf
        from types import SimpleNamespace
        import requests
        folder=self.root/'cf_posting/output/corrections/test';folder.mkdir(parents=True)
        html='<h2>Reviewed heading</h2><p>Reviewed answer one.</p><p>Reviewed answer two.</p>'
        url='https://www.smilenote.kr/desk-guide';sha=hashlib.sha256(html.encode()).hexdigest()
        write(folder/'document.json',{'title':'Reviewed question','contentHtml':html})
        write(folder/'research.json',{});write(folder/'claim-review.json',{})
        write(folder/'correction-prepared.json',{'domain':'smilenote.kr','postId':7,'slug':'desk-guide','status':'independently_reviewed'})
        write(folder/'correction-intent.json',{'publicUrl':url,'domain':'smilenote.kr','postId':7,'state':'api_body_verified','afterBodySha256':sha})
        api=SimpleNamespace(raise_for_status=lambda:None,json=lambda:{'post':{'id':7,'slug':'desk-guide','content':html,'title':'Reviewed question','status':'published'}})
        old=SimpleNamespace(raise_for_status=lambda:None,text='<article><p>Stale old answer.</p></article>',headers={'CF-Cache-Status':'HIT'})
        fresh=SimpleNamespace(raise_for_status=lambda:None,text='<article>'+html+'</article>',headers={'CF-Cache-Status':'MISS'})
        with patch.object(cf,'ROOT',self.root),patch('common.content_quality.validate_publication_review'), \
             patch.object(requests,'get',side_effect=[api,old,fresh]),patch.object(requests,'put') as put, \
             patch.object(cf,'purge_cf_public_url',return_value={'accepted':True}) as purge,patch.object(Path,'home',return_value=self.root):
            result=cf.verify_cf_corrected_publication('cf_blog',url,str(folder))
        self.assertTrue(result['publicBodyMatched']);self.assertFalse(result['newPublication']);put.assert_not_called();purge.assert_called_once_with(url)
        self.assertEqual(load(folder/'correction-intent.json')['state'],'verified_updated')
        changed=SimpleNamespace(raise_for_status=lambda:None,json=lambda:{'post':{'id':7,'slug':'desk-guide','content':'Newer unrelated update','title':'Reviewed question','status':'published'}})
        with patch.object(cf,'ROOT',self.root),patch('common.content_quality.validate_publication_review'), \
             patch.object(requests,'get',return_value=changed),patch.object(cf,'purge_cf_public_url') as purge:
            result=cf.verify_cf_corrected_publication('cf_blog',url,str(folder))
        self.assertEqual(result['status'],'needs_reconciliation');purge.assert_not_called()

    def test_cf_cache_purge_resolves_the_deployed_versioned_key_and_scopes_exact_urls(self):
        from common import cf_recovery as cf
        from types import SimpleNamespace
        import requests
        def response(data=None,text=''):
            return SimpleNamespace(ok=True,status_code=200,json=lambda:data,text=text,raise_for_status=lambda:None)
        replies=[response({'success':True,'result':[{'id':'zone','name':'smilenote.kr','status':'active','account':{'id':'account'}}]}),
                 response({'result':[{'hostname':'www.smilenote.kr','zone_id':'zone','environment':'production','service':'smilenote'}]}),
                 response(text='const cacheKey=url+"?_baro_v=actual_deployed_v2";')]
        config={'CLOUDFLARE_API_EMAIL_baro':'test@example.invalid','CLOUDFLARE_GLOBAL_API_KEY_baro':'test-placeholder'}
        with patch('dotenv.dotenv_values',return_value=config),patch.object(requests,'get',side_effect=replies), \
             patch.object(requests,'post',return_value=response({'success':True})) as post:
            result=cf.purge_cf_public_url('https://www.smilenote.kr/desk-guide')
        self.assertTrue(result['accepted']);self.assertEqual(post.call_args.kwargs['json'],{'files':['https://www.smilenote.kr/desk-guide','https://www.smilenote.kr/desk-guide?_baro_v=actual_deployed_v2']})
        with patch.object(requests,'get') as get:
            with self.assertRaises(ValueError):cf.purge_cf_public_url('https://www.smilenote.kr.evil.example/desk-guide')
        get.assert_not_called()

    def test_revised_article_replans_real_image_proof_without_changing_captured_sections(self):
        from common import editorial_images as images
        import json
        folder=self.folder;sections=[{'heading':'Intro','body':'An original explanatory reader paragraph.','image_optional':True},
                 {'heading':'Actual interface','body':'An unchanged actual interface procedure paragraph.','image_optional':True}]
        changed=copy.deepcopy(sections);changed[0]['heading']='Corrected explanatory heading'
        plans=[{'index':i,'decision':'capture' if i==1 else 'omit','query':'q','subject':'s','event':'','date':'','reason':'Observed need'} for i in range(2)]
        original={'status':'ready','assets':[{'section_index':1,'sha256':'original-pixels'}],
                  'plan':{'sections':plans,'receipt':{'old':'unchanged'}},'budget':{'model_calls':4,'elapsed_seconds':1}}
        original['manifest_sha256']=images._hash(original);write(folder/images.MANIFEST,original)
        def model(stage,payload,files,schema,timeout):
            self.assertEqual(payload['sections'],images._sections(changed))
            return {'sections':plans},{'input_sha256':images._hash(payload),'actualReview':True}
        with patch.object(images,'validate_editorial_assets',side_effect=[False,True,True]),patch.object(images,'_model',side_effect=model) as called:
            result=images.replan_unchanged_captures('Original reader question',sections,changed,folder)
        called.assert_called_once();self.assertEqual(result['assets'],original['assets'])
        self.assertTrue(result['plan']['receipt']['actualReview']);self.assertEqual(original['plan']['receipt'],{'old':'unchanged'})
        self.assertEqual(result['budget']['model_calls'],5)
        write(folder/images.MANIFEST,original);changed[1]['body']='Changed screenshot context requiring fresh acquisition.'
        with patch.object(images,'validate_editorial_assets',side_effect=[False,True]),patch.object(images,'_model') as called:
            with self.assertRaisesRegex(images.Held,'context_changed'):images.replan_unchanged_captures('Original reader question',sections,changed,folder)
        called.assert_not_called();self.assertEqual(load(folder/images.MANIFEST),original)

    def test_image_credits_and_source_pixels_are_preserved(self):
        html={'contentHtml':'<h2>Original</h2><p>Answer</p><figure><img src="same.png"><figcaption>Observed credit</figcaption></figure>'}
        changed=html['contentHtml'].replace('Observed credit','Invented credit')
        with self.assertRaisesRegex(ValueError,'credits'):
            recovery.apply_edits(html,[{'path':'contentHtml','value':changed}])

    def test_native_download_rebinding_requires_reviewed_text_and_checks_both_original_and_candidate(self):
        from types import SimpleNamespace
        old=copy.deepcopy(self.document);new=copy.deepcopy(old);new['blocks'][1]['text']='Corrected answer'
        plan={'documentSha256':recovery.digest(old)}
        engine=SimpleNamespace(document_fingerprint=recovery.digest)
        write(self.folder/'editorial-revisions'/recovery.digest(old)/'document.json',old)
        write(self.folder/'editorial-reviewed-document.json',{'documentSha256':recovery.digest(new),'document':new})
        verify=Mock()
        result=recovery.rebind_reviewed_download(new,plan,self.folder,engine,verify)
        self.assertEqual(result['documentSha256'],recovery.digest(new));self.assertEqual(verify.call_count,2)
        changed=copy.deepcopy(new);changed['blocks'][0]['text']='Changed media heading'
        write(self.folder/'editorial-reviewed-document.json',{'documentSha256':recovery.digest(changed),'document':changed})
        with self.assertRaisesRegex(ValueError,'media binding'):
            recovery.rebind_reviewed_download(changed,plan,self.folder,engine,verify)

    def test_verified_input_revision_never_authorizes_unknown_or_post_editor_failures(self):
        current={'id':'original-owner','project':'naver_blog'}
        for status,frames in [('unknown',[{'file':'naver_blog_posting/posting.py','function':'prepare_basic_content'}]),
                              ('failed',[{'file':'naver_blog_posting/posting.py','function':'submit'}])]:
            original={'status':status,'businessAgendaId':current['id'],'arguments':{'action':'naver'},
                      'failureDiagnostic':{'sourceFrames':frames}}
            with self.assertRaisesRegex(ValueError,'editor or unknown'):
                recovery.reviewed_input_revision(current,original)

    def test_new_input_resume_requires_all_native_reviews_and_cannot_reconsume_same_revision(self):
        from common import channel_parameters,project_autonomy,content_quality,naver_reader,repair_workflow
        from naver_blog_posting import posting as engine
        write(self.folder/'editor-content.json',self.document);write(self.folder/'photo-plan.json',{'assets':[]})
        write(self.folder/'editorial-reviewed-document.json',{'document':self.document,'documentSha256':recovery.digest(self.document)})
        current={'id':'original-owner','project':'naver_blog'}
        args={'action':'naver','account':'account','date':'2026-11-07','slot':'19:30'}
        original={'status':'failed','businessAgendaId':current['id'],'arguments':args,
            'failureDiagnostic':{'sourceFrames':[{'file':'naver_blog_posting/posting.py','function':'prepare_basic_content'}]}}
        target={'identity':'account','date':args['date'],'slot':args['slot']}
        with patch.object(channel_parameters,'folder_for',return_value=self.folder), \
             patch.object(project_autonomy,'recoverable_work',return_value=[target]), \
             patch.object(repair_workflow,'agenda_recovery_blocker',return_value=''), \
             patch.object(content_quality,'ensure_publication_review') as factual, \
             patch.object(naver_reader,'ensure_reader_review') as reader, \
             patch.object(engine,'verify_document_images') as images, \
             patch.object(engine,'validate_document',return_value={'ok':True}) as native:
            revision=recovery.reviewed_input_revision(current,original)
            for check in (factual,reader,images,native):check.assert_called_once()
            original['editorialInputRevisions']=[revision]
            with self.assertRaisesRegex(ValueError,'already consumed'):
                recovery.reviewed_input_revision(current,original,revision)

    def test_reservation_due_requires_exact_account_time_and_public_body_proof(self):
        from dashboard.collectors import naver_public
        from datetime import datetime,timezone
        due={'status':'reserved_verified','outcomes':[{'account':'account','reserveTime':'2026-11-07 19:30','reservationVerified':True}]}
        evidence={'account':'other-account','reserveTime':'2026-11-07 19:30','publicPublicationVerified':True,
                  'publicBodyMatched':True,'publicUrl':'https://blog.naver.com/account/123'}
        path=self.root/'dashboard/data/naver/public-verification.json'
        with patch.object(naver_public,'reconcile') as collect:
            write(path,{'evidence':[evidence]})
            result=recovery.observe_publication(copy.deepcopy(due),datetime(2026,11,8,tzinfo=timezone.utc))
            self.assertEqual(result['status'],'awaiting_public_verification')
            evidence['account']='account';evidence['publicBodyMatched']=False;write(path,{'evidence':[evidence]})
            result=recovery.observe_publication(copy.deepcopy(due),datetime(2026,11,8,tzinfo=timezone.utc))
            self.assertEqual(result['status'],'awaiting_public_verification')
            evidence['publicBodyMatched']=True;write(path,{'evidence':[evidence]})
            result=recovery.observe_publication(copy.deepcopy(due),datetime(2026,11,8,tzinfo=timezone.utc))
            self.assertEqual(result['status'],'published_verified');self.assertEqual(len(result['publicEvidence']),1)
            collect.assert_called_with(force=False)

    def test_manager_can_run_registered_native_channels_but_cannot_release_premium_hold(self):
        from agents import crew_reasoning as crew
        from common import project_autonomy as autonomy
        row={'id':'manager','actor':'jarvis','permissions':{'execute':True,'projects':['naver_cafe','naver_premium']}}
        with patch.object(autonomy,'request_native_channel_cycle',return_value={'status':'queued','publicationVerified':False}) as native:
            result=crew.tool_call(row,'run_channel_cycle',{'project':'naver_cafe'})
        native.assert_called_once_with('naver_cafe','manager:0');self.assertEqual(result,{'status':'queued','publicationVerified':False})
        with self.assertRaisesRegex(ValueError,'registered staff'):
            crew.tool_call(row,'run_channel_cycle',{'project':'naver_premium'})

    def test_invalid_link_proposal_returns_to_writer_without_stopping_the_work(self):
        bad={**self.proposal,'edits':[{'path':'blocks/1/text','value':'https://unbound.example/'}]}
        model=Mock(side_effect=[bad,self.proposal])
        recovery.review_and_repair(self.document,self.folder,[self.check],generate=model)
        self.assertEqual(model.call_count,2)
        self.assertIn('unbound external link',model.call_args.args[0])
        self.assertEqual(self.document['blocks'][1]['text'],'Observed complete answer')

    def test_cf_editor_can_link_only_to_actual_collected_source_urls(self):
        old={'contentHtml':'<h2>Original</h2><p>Answer</p>'}
        value="<h2>Original</h2><p>Answer <a href='https://official.example/help'>Official help</a></p>"
        new=recovery.apply_edits(old,[{'path':'contentHtml','value':value}],allowed_urls=['https://official.example/help'])
        self.assertIn('official.example/help',new['contentHtml'])
        with self.assertRaises(ValueError):recovery.apply_edits(old,[{'path':'contentHtml','value':value}])

    def test_stale_sources_are_actually_refetched_and_original_snapshot_is_preserved(self):
        from common import source_discovery as sources
        old={'collectedAt':'2000-01-01T00:00:00+00:00','sources':[{'url':'https://official.example/help','text':'old','textSha256':'old'}]}
        write(self.folder/'research.json',old)
        text='Fresh observed source '*20;sha=hashlib.sha256(text.encode()).hexdigest()
        with patch.object(sources,'public_text',return_value={'url':'https://official.example/help','text':text,'status':200,'textSha256':sha}) as fetch:
            recovery.acquire(self.folder,[])
        fetch.assert_called_once();fresh=load(self.folder/'research.json')
        self.assertNotEqual(fresh['collectedAt'],old['collectedAt']);self.assertEqual(fresh['sources'][0]['textSha256'],sha)
        self.assertEqual(load(self.folder/'editorial-revisions'/('research-'+recovery.digest(old))/'research.json'),old)

    def test_resource_admission_failure_does_not_permanently_consume_unprocessed_input(self):
        with self.assertRaisesRegex(RuntimeError,'route cooling'):
            recovery.review_and_repair(self.document,self.folder,[self.check],generate=Mock(side_effect=RuntimeError('route cooling')))
        self.assertEqual(load(self.folder/'editorial-recovery.json').get('inputHistory',[]),[])
        recovery.review_and_repair(self.document,self.folder,[self.check],generate=Mock(return_value=self.proposal))
        self.assertEqual(load(self.folder/'editorial-recovery.json')['status'],'reviewed')

    def test_manager_repair_handoff_is_durable_nonblocking_and_deduplicated(self):
        from common import conference_dispatch as conferences
        queue=self.root/'dashboard/data/publication-conferences';queue.mkdir(parents=True)
        identity='c'*64;write(queue/(identity+'.json'),{'status':'failed','kind':'parameters','arguments':{'action':'naver'},
            'failureDiagnostic':{'errorMessage':'Draft held: source missing'}})
        with patch.object(conferences,'QUEUE',queue),patch.object(recovery,'repair_conference') as execute:
            first=recovery.request_repair(identity,['original question official source'])
            again=recovery.request_repair(identity,['a different query must not overwrite pending work'])
        execute.assert_not_called();self.assertEqual(first['status'],'queued');self.assertEqual(again['status'],'queued')
        pending=load(self.root/'dashboard/data/editorial-recovery-jobs'/(identity+'.json'))
        self.assertEqual(pending['sourceQueries'],['original question official source'])
        self.assertFalse(first['publicationVerified'])

    def test_registered_acquisition_refuses_wrong_phase_before_running_any_work(self):
        from common import project_autonomy as autonomy, repair_workflow as workflow
        with patch.object(workflow,'_recovery_row',return_value=(self.root/'row.json',{'step':'resume','status':'ready'})),patch.object(recovery,'repair_conference') as repair:
            with self.assertRaisesRegex(ValueError,'acquisition phase'):
                autonomy.acquire_registered_work('task','plan')
        repair.assert_not_called()

    def test_registered_acquisition_refuses_changed_input_capability(self):
        from common import project_autonomy as autonomy, repair_workflow as workflow, recovery_evidence as evidence
        row={'step':'acquire','status':'ready','plan':{'projectRoot':str(self.root),'workTarget':{}},
             'discovered':{'workEvidence':{'inputCapability':{'kind':'original'}}}}
        with patch.object(workflow,'_recovery_row',return_value=(self.root/'row.json',row)),patch.object(evidence,'task_evidence',return_value={'inputCapability':{'kind':'changed'}}),patch.object(recovery,'repair_conference') as repair:
            with self.assertRaisesRegex(ValueError,'capability changed'):
                autonomy.acquire_registered_work('task','plan')
        repair.assert_not_called()


if __name__=='__main__':unittest.main()
