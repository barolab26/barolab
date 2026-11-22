"""Approved slot repair must preserve uncertain effects, source identity and time."""
from contextlib import contextmanager, nullcontext
from datetime import datetime
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from common import cf_recovery as recovery


class CFNormalizationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.day=datetime.now().date().isoformat()
        self.row={'domain':'example.com','scheduledTime':'23:59','status':'waiting'}
        self.policy={'cf':{'example.com':'23:59'}}
        self.original=self.root/'cf_posting/output/scheduled'/self.day/'example.com'
        self.original.mkdir(parents=True)
        for name in ['article.json','research.json','planning.json']:
            (self.original/name).write_text(json.dumps({'title':'original','sources':[]}),encoding='utf-8')
        self.schedule=self.root/'dashboard/data/cf/daily_schedule.json'
        self.schedule.parent.mkdir(parents=True)
        self.save_schedule()

    def save_schedule(self):
        self.schedule.write_text(json.dumps({'date':self.day,'items':[self.row]}),encoding='utf-8')

    def normalize(self, make):
        with patch('common.channel_parameters.policy',return_value=self.policy), \
             patch.object(recovery,'make_revision',side_effect=make), \
             patch('cf_posting.posting.verify_article_images',return_value={}), \
             patch('common.content_quality.validate_research_freshness'), \
             patch('cf_posting.posting.run_basic_posting') as publish:
            result=recovery.normalize(root=self.root,limit=2)
            publish.assert_not_called()
            return result

    def fake_revision(self,row,day,original,revision,attempt,previous):
        revision.mkdir(parents=True)
        (revision/'article.json').write_bytes((original/'article.json').read_bytes())

    def test_receipts_all_uncertain_states_and_manual_stops_are_preserved(self):
        for status in recovery.PROTECTED:
            self.assertFalse(recovery.repair_eligible({**self.row,'status':status},self.day,self.policy,root=self.root))
        for flag in recovery.INTENTS:
            self.assertFalse(recovery.repair_eligible({**self.row,flag:True},self.day,self.policy,root=self.root))
        (self.original/'publication-receipt.json').write_text('{}')
        self.assertFalse(recovery.repair_eligible(self.row,self.day,self.policy,root=self.root))

    def test_reviewed_correction_handoff_keeps_original_and_uses_normal_publisher(self):
        from cf_posting import posting as cf
        state_path=self.schedule.with_name('normalization-state.json')
        original_bytes=(self.original/'article.json').read_bytes()
        old={'status':'held','attempts':2,'originalFolder':str(self.original),
             'originalSha256':recovery.fingerprint(self.original),'slot':'23:59'}
        state_path.write_text(json.dumps({'slots':{self.day+'/example.com':old}}))
        revision=self.root/'cf_posting/output/correction';revision.mkdir()
        (revision/'article.json').write_text('{"title":"corrected"}')
        (revision/'planning.json').write_text('{"keyword":"reader task"}')
        with patch('common.channel_parameters.policy',return_value=self.policy), \
             patch.object(cf,'verify_article_images'),patch.object(cf,'validate_cached_cf_evidence'), \
             patch('common.content_quality.ensure_publication_review'),patch.object(cf,'run_basic_posting') as publish:
            result=recovery.register_reviewed_revision('example.com',self.day,revision,root=self.root)
            self.assertEqual(result['owner'],'normal-cf-scheduler')
            self.assertFalse(result['publicationVerified'])
            publish.assert_not_called()
            with self.assertRaises(ValueError):
                recovery.register_reviewed_revision('example.com',self.day,revision,root=self.root)
        saved=json.loads(state_path.read_text())
        self.assertEqual(saved['slots'][self.day+'/example.com']['attempts'],2)
        self.assertEqual(saved['history'][0]['status'],'held')
        self.assertEqual((self.original/'article.json').read_bytes(),original_bytes)

    def test_wrong_slot_date_or_external_artifact_is_not_repaired(self):
        self.assertFalse(recovery.repair_eligible(self.row,'2000-01-01',self.policy,root=self.root))
        self.assertFalse(recovery.repair_eligible({**self.row,'scheduledTime':'00:01'},self.day,self.policy,root=self.root))
        with self.assertRaisesRegex(ValueError,'outside'):
            recovery.original_folder({**self.row,'artifactFolder':'../../outside'},self.day,self.root)

    def test_uncertain_original_request_and_browser_takeover_evidence_block_repair(self):
        queue=self.root/'dashboard/data/publication-conferences';queue.mkdir()
        request=queue/'original.json'
        request.write_text(json.dumps({'status':'pending_effect','arguments':{
            'action':'cf','date':self.day,'account':'example.com'}}))
        self.assertFalse(recovery.repair_eligible(self.row,self.day,self.policy,root=self.root))
        request.write_text(json.dumps({'status':'failed','arguments':{
            'action':'cf','date':self.day,'account':'example.com'}}))
        (self.original/'editorial-images.json').write_text(json.dumps({'reasons':['user_takeover']}))
        self.assertFalse(recovery.repair_eligible(self.row,self.day,self.policy,root=self.root))

    def test_enrichment_adds_only_fetched_primary_text_not_search_snippets(self):
        revision=self.root/'enriched';revision.mkdir()
        candidates=[{'url':'https://secondary.example/article','title':'secondary'},
                    {'url':'https://agency.go.kr/help','title':'Official help','snippet':'unverified snippet'}]
        observed={'url':candidates[1]['url'],'status':200,'text':'Observed official Task text',
                  'textSha256':hashlib.sha256(b'Observed official Task text').hexdigest()}
        with patch('common.source_discovery.search_urls',return_value=candidates), \
             patch('common.content_improvement.primary_url',side_effect=lambda u:'agency.go.kr' in u), \
             patch('common.source_discovery.public_text',return_value=observed) as fetch:
            result=recovery.enrich_primary_sources({'title':'Task','mainKeyword':'Task'},{'sources':[]},revision)
        self.assertEqual(len(result['sources']),1)
        self.assertEqual(result['sources'][0]['text'],'Observed official Task text')
        fetch.assert_called_once_with(candidates[1]['url'],timeout=12)

    def test_official_but_unrelated_discovery_is_not_used_as_topic_evidence(self):
        revision=self.root/'irrelevant';revision.mkdir()
        with patch('common.source_discovery.search_urls',return_value=[{'url':'https://agency.go.kr/weather'}]), \
             patch('common.content_improvement.primary_url',return_value=True), \
             patch('common.source_discovery.public_text',return_value={'url':'https://agency.go.kr/weather','text':'Weather forecast'}):
            result=recovery.enrich_primary_sources({'title':'Endoscopy insurance','mainKeyword':'Endoscopy insurance'},{'sources':[]},revision)
        self.assertEqual(result['sources'],[])
        self.assertEqual(len(json.loads((revision/'source-enrichment.json').read_text(encoding='utf-8'))['rejectedUnrelatedSources']),1)

    def test_research_does_not_promote_unrelated_search_hits_to_article_evidence(self):
        from common.source_discovery import research,topic_matches
        self.assertTrue(topic_matches('구글 백업코드 찾기','Google 백업 코드 안내'))
        self.assertFalse(topic_matches('2026년 위내시경 실비','2026년 날씨 예보'))
        folder=self.root/'source-research';folder.mkdir()
        candidates=[{'url':'https://example.com/weather'},{'url':'https://example.com/topic'}]
        with patch('common.source_discovery.search_urls',return_value=candidates), \
             patch('common.source_discovery.public_text',side_effect=[
                 {'url':candidates[0]['url'],'text':'Weather forecast '*30,'status':200},
                 {'url':candidates[1]['url'],'text':'Task evidence '*30,'status':200}]), \
             patch('common.crew_chat_bridge.emit_work_event'),patch('common.crew_chat_bridge.work_task_id',return_value='test'):
            result=research('Task',folder,exact_query=True)
        self.assertEqual([r['url'] for r in result],[candidates[1]['url']])
        self.assertEqual(len(json.loads((folder/'research.json').read_text(encoding='utf-8'))['rejectedUnrelatedSources']),1)

    def test_future_slot_is_prepared_once_without_early_publication_or_original_mutation(self):
        before=recovery.fingerprint(self.original)
        self.assertEqual(self.normalize(self.fake_revision)['outcomes'][0]['status'],'prepared')
        def no_second_revision(*args):raise AssertionError('Prepared article rebuilt')
        self.assertEqual(self.normalize(no_second_revision)['status'],'idle' if datetime.now().strftime('%H:%M')<'23:59' else 'processed')
        self.assertEqual(before,recovery.fingerprint(self.original))

    def test_ownership_failure_is_held_without_automatic_retry(self):
        def takeover(*args):raise ValueError('user_takeover')
        result=self.normalize(takeover)
        self.assertEqual(result['outcomes'][0]['status'],'held')
        self.assertEqual(self.normalize(lambda *a:self.fail('retried ownership hold'))['status'],'idle')

    def test_transport_failure_does_not_replay_unknown_browser_effects(self):
        def disconnected(*args):raise ValueError('browser_transport_unavailable')
        result=self.normalize(disconnected)
        self.assertEqual(result['outcomes'][0]['status'],'held')
        self.assertEqual(self.normalize(lambda *a:self.fail('retried uncertain browser effects'))['status'],'idle')

    def test_interrupted_preparation_is_reported_without_replaying_effects(self):
        state={'slots':{self.day+'/example.com':{'status':'preparing','attempts':1,
               'originalSha256':recovery.fingerprint(self.original),'slot':self.row['scheduledTime']}}}
        path=self.root/'dashboard/data/cf/normalization-state.json'
        path.write_text(json.dumps(state))
        result=self.normalize(lambda *a:self.fail('Replayed interrupted preparation'))
        self.assertEqual(result['outcomes'][0]['status'],'held')
        self.assertIn('reconciliation',result['outcomes'][0]['reason'])

    def test_dispatch_ownership_covers_backoff_and_holds_but_not_other_days(self):
        path=self.root/'dashboard/data/cf/normalization-state.json'
        for status in ('preparing','prepared','retry_wait','held','submitting'):
            path.write_text(json.dumps({'slots':{self.day+'/example.com':{'status':status,'slot':self.row['scheduledTime']}}}))
            self.assertTrue(recovery.owns_slot(self.day,'example.com',self.root))
            self.assertFalse(recovery.owns_slot('2000-01-01','example.com',self.root))
            self.assertFalse(recovery.owns_slot(self.day,'example.com',self.root,slot='00:00'))
            self.assertTrue(recovery.owns_slot(self.day,'example.com',self.root,slot=self.row['scheduledTime']))

    def test_future_source_is_not_prepared_outside_its_valid_release_window(self):
        from datetime import timedelta
        with patch('common.content_quality.source_maximum_age',return_value=timedelta(minutes=30)):
            result=self.normalize(lambda *a:self.fail('Research would expire before release'))
        self.assertEqual(result['status'],'idle')

    def test_private_ui_assumptions_are_aligned_without_dropping_required_visuals(self):
        article={'sectionImages':[{'sectionHeading':'Recovery','imagePrompt':'Google 계정 복구 화면',
                 'image_optional':False},{'sectionHeading':'Car','imagePrompt':'GV90 실제 전시차 외관',
                 'image_optional':False,'purpose':'actual vehicle photo'}]}
        revised=recovery.align_public_guide_visuals(article)
        self.assertIn('PUBLIC help/guide',revised['sectionImages'][0]['purpose'])
        self.assertFalse(revised['sectionImages'][0]['image_optional'])
        self.assertEqual(revised['sectionImages'][1]['purpose'],'actual vehicle photo')

    def test_ordinary_failure_records_finite_backoff_without_immediate_replay(self):
        def missing(*args):raise ValueError('no_suitable_region')
        self.assertEqual(self.normalize(missing)['outcomes'][0]['status'],'retry_wait')
        self.assertEqual(self.normalize(lambda *a:self.fail('retried before due time'))['status'],'idle')
        state=json.loads((self.root/'dashboard/data/cf/normalization-state.json').read_text(encoding='utf-8'))
        self.assertIsNotNone(datetime.fromisoformat(state['slots'][self.day+'/example.com']['retryAt']).tzinfo)

    def test_source_reader_dictionary_is_preserved_and_hash_is_not_fabricated(self):
        source={'url':'https://example.com/source','text':'Observed query source text','status':200,
                'textSha256':hashlib.sha256(b'Observed query source text').hexdigest()}
        (self.original/'research.json').write_text(json.dumps({'sources':[{'url':source['url']}]}))
        revision=self.root/'revision';revision.mkdir()
        with patch('common.source_discovery.public_text',return_value=source):
            result=recovery.refresh_sources({'mainKeyword':'query'},self.original,revision)
        self.assertEqual(result['sources'][0]['textSha256'],source['textSha256'])
        self.assertEqual(result['sources'][0]['text'],'Observed query source text')

    def test_collection_process_note_is_removed_but_real_dates_are_preserved(self):
        article={'contentHtml':'<p>이 글은 2026년 11월 6일에 확인한 공개 안내를 기준으로 합니다.</p>'
                 '<p>신청 기한은 2026년 11월 6일입니다.</p><p>관찰한 실제 조건을 확인하세요.</p>'}
        revised=recovery.remove_collection_note(article)
        self.assertNotIn('공개 안내를 기준',revised['contentHtml'])
        self.assertIn('신청 기한은 2026년 11월 6일입니다.',revised['contentHtml'])
        self.assertIn('공개 안내를 기준',article['contentHtml'])
        mixed={'contentHtml':'<p>이 글은 2026년 11월 6일에 확인한 공개 안내를 기준으로 합니다. 안내의 수정일은 2025-07-09입니다.</p>'}
        revised=recovery.remove_collection_note(mixed)
        self.assertNotIn('공개 안내를 기준',revised['contentHtml'])
        self.assertIn('안내의 수정일은 2025-07-09입니다.',revised['contentHtml'])

    def test_claim_review_receives_explicit_reviewer_without_unnecessary_rewrite(self):
        article={'title':'Original','mainKeyword':'Original','contentHtml':'<h2>Step</h2><p>Observed instructions.</p>'}
        (self.original/'article.json').write_text(json.dumps(article))
        revision=self.root/'reviewed-revision'
        with patch.object(recovery,'refresh_sources',return_value={'sources':[]}), \
             patch('dashboard.agents.style_strategy.attach_search_benchmark',side_effect=lambda p,f:p), \
             patch('common.content_quality.ensure_publication_review',return_value={'status':'passed'}) as review, \
             patch('common.llm_client.generate_json') as generate, \
             patch('cf_posting.posting.validate_cached_cf_evidence'), \
             patch('cf_posting.posting.ensure_article_images',side_effect=lambda a,*args:a), \
             patch('cf_posting.posting.verify_article_images'):
            recovery.make_revision(self.row,self.day,self.original,revision,1)
        self.assertIs(review.call_args.kwargs['generate'],generate)
        self.assertEqual(review.call_count,2)
        generate.assert_not_called()

    def test_contribution_and_wage_guides_require_independent_factual_review(self):
        from common.content_quality import publication_risk_signals
        for title in ('청년도약계좌 정부기여금 계산', '주휴수당 계산', '최저임금 확인', '실업급여 지급기간'):
            self.assertTrue(publication_risk_signals({'title':title})['sensitiveTopic'])

    def test_factual_quote_whitespace_and_service_names_do_not_change_quantity_checks(self):
        from common.content_improvement import fact_valid
        sources={'0':{'status':200,'text':'처리기간 총 10일\n처리기간 계산 방법 신청서 안내'}}
        claim={'sourceId':'0','claim':'정부24의 처리기간은 총 10일입니다.',
               'quote':'처리기간 총 10일 처리기간 계산 방법 신청서 안내'}
        self.assertTrue(fact_valid(claim,sources))
        self.assertFalse(fact_valid({**claim,'claim':'정부24의 처리기간은 총 12일입니다.'},sources))
        self.assertFalse(fact_valid({**claim,'quote':'처리기간 총 10일 처리기간 변경 방법 신청서 안내'},sources))
        self.assertTrue(fact_valid({**claim,'claim':'1350 상담은 총 10일로 안내합니다.'},sources))
        self.assertFalse(fact_valid({**claim,'claim':'총 1350일로 안내합니다.'},sources))

    def test_hug_primary_classification_is_limited_to_its_public_policy_answer_path(self):
        from common.content_improvement import primary_url
        path='/hug/web/cs/el/csel000182.jsp?hmpg_sno=157045&hmpg_cvap_dcd=04'
        self.assertTrue(primary_url('https://www.khug.or.kr'+path))
        self.assertFalse(primary_url('https://www.khug.or.kr/other'))
        self.assertFalse(primary_url('https://www.khug.or.kr'+path+'&private=true'))
        self.assertFalse(primary_url('https://www.khug.or.kr.evil.org'+path))

    def test_unknown_publication_receipt_is_never_replayed(self):
        self.row['scheduledTime']='00:00';self.policy['cf']['example.com']='00:00';self.save_schedule()
        def unknown(domain,artifact_folder):
            (artifact_folder/'publication-receipt.json').write_text(json.dumps({'state':'submission_unknown'}))
            raise TimeoutError('post result unknown')
        with patch('common.channel_parameters.policy',return_value=self.policy), \
             patch.object(recovery,'make_revision',side_effect=self.fake_revision), \
             patch('cf_posting.posting.verify_article_images'), \
             patch('cf_posting.posting.validate_cached_cf_evidence'), \
             patch('cf_posting.posting.cleaner_lock',return_value=nullcontext(True)), \
             patch('cf_posting.posting.run_basic_posting',side_effect=unknown) as publish:
            result=recovery.normalize(root=self.root)
            self.assertEqual(result['outcomes'][0]['status'],'held')
            recovery.normalize(root=self.root)
            self.assertEqual(publish.call_count,1)

    def test_existing_cleaner_uses_recovery_and_preserves_ordinary_authoring_fallback(self):
        from dashboard.server import worker
        with patch('common.cf_recovery.normalize',return_value={'status':'busy','workPerformed':False}) as normalize, \
             patch.object(worker,'export_environment',return_value={}),patch.object(worker.subprocess,'run') as run:
            self.assertEqual(worker.run_task('cleaner'),0)
            normalize.assert_called_once_with(limit=1);run.assert_not_called()
        with patch('common.cf_recovery.normalize',return_value={'status':'idle','workPerformed':False}), \
             patch.object(worker,'export_environment',return_value={}),patch.object(worker.subprocess,'run') as run:
            run.return_value.returncode=0
            self.assertEqual(worker.run_task('cleaner'),0)
            self.assertIn('cf-cycle',run.call_args.args[0])


if __name__=='__main__':unittest.main()
