import json
from pathlib import Path
import tempfile
import unittest
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import patch
from common import naver_ab as ab

class WorkflowExperimentTests(unittest.TestCase):
    def test_reservation_rollover_preserves_original_workflow_day_and_cached_wiring_updates(self):
        from contextlib import ExitStack
        from common import channel_parameters as parameters
        import naver_blog_posting.posting as engine
        class PreparedBrief(Exception):pass
        slots={'soultin':{'slots':['07:40']}}
        folder=self.root/'soultin-0740'
        with ExitStack() as stack:
            for name in ('DAILY_SLOTS','prepare_basic_content','basic_native_document','basic_summary_image',
                         'write_attempt','acquire_naver_editor','show_reservation_popup','basic_editor_content','bind_basic_editor'):
                stack.enter_context(patch.object(engine,name,getattr(engine,name,None),create=True))
            stack.enter_context(patch.object(engine,'RUN_OPTIONS',{'reserve_time':'2026-11-08 16:00','slot':'07:40'}))
            stack.enter_context(patch.object(engine,'_parameter_wiring',False,create=True))
            stack.enter_context(patch.object(engine,'_parameter_original_slots',{'soultin':('07:40',)},create=True))
            stack.enter_context(patch.object(parameters,'policy',return_value={'effectiveDate':'2026-01-01','naver':slots}))
            stack.enter_context(patch.object(parameters,'naver_slots_for_date',return_value=slots))
            stack.enter_context(patch.object(parameters,'styles',return_value={'summaryTable':False}))
            stack.enter_context(patch.object(ab,'normalize_saved_tags'))
            planning=stack.enter_context(patch.object(ab,'plan',side_effect=PreparedBrief))
            parameters.configure_naver('2026-11-07')
            with self.assertRaises(PreparedBrief):engine.prepare_basic_content('soultin',folder,'assigned question')
            self.assertEqual(planning.call_args.args[-2:],('2026-11-07','07:40'))
            parameters.configure_naver('2026-11-08')
            with self.assertRaises(PreparedBrief):engine.prepare_basic_content('soultin',folder,'assigned question')
            self.assertEqual(planning.call_args.args[-2:],('2026-11-08','07:40'))

    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.config=self.root/'experiment.json'
        self.settings={'id':'trial','status':'active','accounts':list(ab.ACCOUNTS),
                       'startDate':'2026-11-06','enrollmentEnd':'2026-11-19',
                       'seed':'test','provider':'codex','model':'same-model',
                       'maxModelCallsPerDay':2,'maxModelCallsPerArticle':1}
        self.config.write_text(json.dumps(self.settings))
        self.addCleanup(patch.stopall)
        patch.object(ab,'CONFIG',self.config).start()

    def test_each_time_window_crosses_over_on_next_day(self):
        for account in ab.ACCOUNTS:
            for slots in (['07:40'],['07:40','16:30']):
                for slot in slots:
                    self.assertNotEqual(ab.arm_for(account,'2026-11-06',slot,slots,'seed'),
                                        ab.arm_for(account,'2026-11-07',slot,slots,'seed'))

    def test_immutable_receipt_is_never_redirected(self):
        folder=self.root/'soultin-0740';folder.mkdir()
        (folder/'writer.json').write_text('{}')
        for state in ab.PROTECTED:
            (folder/'reservation-evidence.json').write_text(json.dumps({'submissionStatus':state}))
            self.assertEqual(ab.experiment_folder(folder,'soultin','2026-11-06','07:40'),folder)

    def test_old_unsent_draft_retained_and_new_folder_is_stable(self):
        folder=self.root/'soultin-0740';folder.mkdir()
        (folder/'writer.json').write_text('{"title":"old"}')
        destination=ab.experiment_folder(folder,'soultin','2026-11-06','07:40')
        self.assertNotEqual(folder,destination)
        self.assertEqual(destination,ab.experiment_folder(folder,'soultin','2026-11-06','07:40'))
        self.assertEqual(json.loads((folder/'writer.json').read_text())['title'],'old')

    def test_call_budget_charges_failures_and_scope_resets(self):
        with ab.scope({'arm':'A'},self.root/'article'):
            self.assertEqual(ab.reserve_call('draft')['arm'],'A')
            with self.assertRaisesRegex(Exception,'article_call_budget'):
                ab.reserve_call('retry')
        self.assertIsNone(ab.CURRENT.get())
        self.assertIsNone(ab.reserve_call('unrelated'))

    def test_B_has_different_prompt_and_explicit_fidelity_limit(self):
        self.assertIn('1600~1900',ab.writer_prompt('input',{'arm':'B'}))
        self.assertIn('완전 복제로 해석하지 않는다',ab.writer_prompt('input',{'arm':'B'}))
        self.assertNotIn('1600~1900',ab.writer_prompt('input',{'arm':'A'}))

    def test_standing_approval_is_limited_to_named_accounts_dates_and_existing_slots(self):
        settings={**self.settings,'approval':{'sourceType':'direct_user_instruction','instruction':'test directive',
                                             'slotsByAccount':{'soultin':['07:40']}}}
        self.config.write_text(json.dumps(settings))
        args={'action':'naver','date':'2026-11-06','account':'soultin','slot':'07:40'}
        self.assertIsNotNone(ab.approved_request('parameters',args))
        self.assertIsNone(ab.approved_request('parameters',{**args,'slot':'12:00'}))
        self.assertIsNone(ab.approved_request('parameters',{**args,'date':'2026-12-01'}))
        self.assertIsNone(ab.approved_request('parameters',{**args,'action':'cf'}))
        self.assertIsNone(ab.approved_request('threads',args))

    def test_repair_subfolder_uses_original_slot_without_rewriting_history(self):
        folder=self.root/'naver_blog_posting/output/source-repair-1';folder.mkdir(parents=True)
        (folder/'workflow-assignment.json').write_text(json.dumps({'account':'yoon_master','day':'2026-11-06','slot':'20:30'}))
        original={'account':'yoon_master','workDate':'2026-11-06','reserveTime':'2026-11-06 21:40',
                  'scheduledSlot':'21:40','artifactFolder':str(folder),'phase':'started'}
        with patch.object(ab,'ROOT',self.root):
            projected=ab.journal_row(original)
            self.assertEqual(projected['scheduledSlot'],'20:30')
            self.assertEqual(original['scheduledSlot'],'21:40')
            self.assertEqual(ab.journal_row({**original,'account':'other'})['scheduledSlot'],'21:40')

    def test_scheduler_uses_standing_approval_without_opening_general_naver_admission(self):
        from common import conference_dispatch as conferences
        args={'action':'naver','date':'2026-11-06','account':'soultin','slot':'07:40'}
        with patch.object(conferences,'concrete_requests',return_value=[args]), \
             patch.object(conferences,'_existing_concrete_work',return_value=False), \
             patch('naver_blog_posting.posting.pipeline_busy',return_value=False), \
             patch.object(conferences,'_request_single',return_value={'status':'conference_requested'}) as request, \
             patch.object(ab,'approved_request',return_value={'id':'explicit-user-trial'}):
            conferences.request('parameters',args,automatic=True)
            self.assertFalse(request.call_args.kwargs['automatic'])
        with patch.object(conferences,'concrete_requests',return_value=[args]), \
             patch.object(conferences,'_existing_concrete_work',return_value=False), \
             patch.object(conferences,'_request_single') as request, \
             patch.object(ab,'approved_request',return_value=None):
            self.assertEqual(conferences.request('parameters',args,automatic=True)['status'],'held')
            request.assert_not_called()

    def test_polish_failure_does_not_return_unreviewed_draft(self):
        def failure(*args,**kwargs):raise RuntimeError('review failed')
        with ab.scope({'arm':'B'},self.root/'article'):
            with self.assertRaisesRegex(RuntimeError,'review failed'):
                ab.polish_article(failure,{'title':'draft'},'prompt',(),{})

    def test_deferred_preimage_review_is_not_final_approval(self):
        from common.naver_reader import ensure_reader_review
        document={'title':'Question','blocks':[{'type':'text','text':'Answer with an actual next step.'}]}
        with ab.scope({'arm':'B'},self.root):
            deferred=ensure_reader_review(document,self.root)
            self.assertEqual(deferred['status'],'deferred_not_approved')
            (self.root/'photo-plan.json').write_text('{}')
            with self.assertRaisesRegex(ValueError,'observed research'):
                ensure_reader_review(document,self.root)

    def test_image_slots_are_separate_from_headings_and_do_not_drop_required_sections(self):
        from common.naver_reader import digest
        engine=SimpleNamespace(naver_image_sections=lambda d:[],prepare_document_images=lambda *a:None,
                               verify_document_images=lambda *a:None,
                               document_fingerprint=digest,validate_document=lambda *a:{'ok':True})
        ab.install_image_slots(engine)
        folder=self.root/'images';folder.mkdir()
        (folder/'workflow-assignment.json').write_text('{"arm":"B"}')
        doc={'title':'Reader question','blocks':[{'type':'heading','text':'One heading'},
             {'type':'text','text':'\n'.join('Evidence paragraph number '+str(i) for i in range(10))}],
             'editorialSectionOptions':{}}
        with patch('common.flow_images.require_editorial_images',return_value={'assets':[]}):
            engine.prepare_document_images(doc,folder,'question')
        self.assertEqual(len(doc['workflowImageSlots']),7)
        self.assertEqual(sum(b['type']=='heading' for b in doc['blocks']),1)
        self.assertEqual(len({r['id'] for r in engine.naver_image_sections(doc)}),7)
        required={'title':'Required evidence','blocks':[b for i in range(9) for b in
                  ({'type':'heading','text':'Heading '+str(i)},
                   {'type':'text','text':'Exact required evidence paragraph '+str(i)})],
                  'editorialSectionOptions':{'section-'+str(i):False for i in range(1,10)}}
        with patch('common.flow_images.require_editorial_images',side_effect=ValueError('required captures held')):
            with self.assertRaisesRegex(ValueError,'required captures held'):
                engine.prepare_document_images(required,folder,'question')
        self.assertEqual(sum(not r['image_optional'] for r in required['workflowImageSlots']),9)

    def cycle_fixture(self):
        from common import channel_parameters as channel
        settings={**self.settings,'maxModelCallsPerDay':20,'accounts':['soultin','soul5373']}
        self.config.write_text(json.dumps(settings))
        schedule=self.root/'dashboard/data/daily_schedule.json';schedule.parent.mkdir(parents=True)
        schedule.write_text(json.dumps({'naver':{'soultin':{'slots':['10:00']},'soul5373':{'slots':['10:30']}}}))
        patch.object(ab,'ROOT',self.root).start()
        engine=SimpleNamespace(pipeline_busy=lambda:False,RUN_OPTIONS={},run_basic_pipeline=unittest.mock.Mock())
        patch.object(channel,'configure_naver',return_value=engine).start()
        patch.object(channel,'monitor',return_value={}).start()
        patch.object(channel,'ROOT',self.root).start()
        patch('common.work_agenda.current',return_value=None).start()
        patch.object(ab,'approved_request',return_value={'id':'trial'}).start()
        patch.object(ab,'protected_slot',return_value=None).start()
        patch.object(ab,'assignment',return_value={'arm':'A'}).start()
        return engine

    def test_timer_enters_direct_workflow_without_requesting_a_conference(self):
        from common import channel_parameters as channel
        with patch.object(ab,'cycle',return_value={'status':'waiting'}) as cycle, \
             patch('common.conference_dispatch.request') as request:
            self.assertEqual(channel.main(['naver-cycle']),{'status':'waiting'})
            cycle.assert_called_once();request.assert_not_called()

    def test_a_held_article_does_not_block_the_next_account_on_later_ticks(self):
        engine=self.cycle_fixture()
        engine.run_basic_pipeline.side_effect=ValueError('quality hold')
        now=datetime(2026,11,6,9,0,tzinfo=ab.KST)
        first=ab.cycle(now);second=ab.cycle(now)
        self.assertEqual(first['account'],'soultin');self.assertEqual(first['status'],'held')
        self.assertEqual(second['account'],'soul5373');self.assertEqual(second['status'],'held')
        self.assertEqual(engine.run_basic_pipeline.call_count,2)
        ab.cycle(now);self.assertEqual(engine.run_basic_pipeline.call_count,2)

    def test_cycle_does_not_claim_success_from_a_return_without_saved_receipt(self):
        engine=self.cycle_fixture()
        engine.run_basic_pipeline.return_value={'submissionStatus':'verified_reserved'}
        result=ab.cycle(datetime(2026,11,6,9,0,tzinfo=ab.KST))
        self.assertEqual(result['status'],'held')
        self.assertIn('without a verified',result['blocker'])

    def test_future_slots_wait_and_daily_budget_does_not_spin(self):
        engine=self.cycle_fixture()
        result=ab.cycle(datetime(2026,11,6,7,0,tzinfo=ab.KST))
        self.assertEqual(result['status'],'waiting_or_preserved');engine.run_basic_pipeline.assert_not_called()
        settings=json.loads(self.config.read_text());settings['callsByDate']={'2026-11-06':20};self.config.write_text(json.dumps(settings))
        self.assertEqual(ab.cycle(datetime(2026,11,6,9,0,tzinfo=ab.KST))['status'],'daily_budget_hold')
        engine.run_basic_pipeline.assert_not_called()

    def test_uncertain_receipt_is_held_and_not_replayed(self):
        engine=self.cycle_fixture()
        def uncertain(account,folder,reserve_time):
            folder.mkdir(parents=True,exist_ok=True)
            (folder/'reservation-evidence.json').write_text(json.dumps({'submissionStatus':'submission_unknown'}))
            raise RuntimeError('readback interrupted')
        engine.run_basic_pipeline.side_effect=uncertain
        now=datetime(2026,11,6,9,0,tzinfo=ab.KST)
        self.assertEqual(ab.cycle(now)['status'],'unknown')
        ab.cycle(now)
        self.assertEqual(engine.run_basic_pipeline.call_args_list[1].args[0],'soul5373')

    def test_cycle_requires_explicit_enrollment_window(self):
        engine=self.cycle_fixture()
        result=ab.cycle(datetime(2026,11,20,9,0,tzinfo=ab.KST))
        self.assertEqual(result['status'],'outside_approved_experiment_window')
        engine.run_basic_pipeline.assert_not_called()

    def test_public_identity_requires_a_matching_saved_verified_receipt(self):
        folder=self.root/'naver_blog_posting/output/repair';folder.mkdir(parents=True)
        receipt={'submissionStatus':'verified_reserved','account':'yoon_master','title':'Exact title','reserveTime':'2026-11-06 21:40'}
        (folder/'reservation-evidence.json').write_text(json.dumps(receipt))
        (folder/'workflow-assignment.json').write_text(json.dumps({'account':'yoon_master','day':'2026-11-06','slot':'20:30'}))
        attempt={'phase':'verified','account':'yoon_master','title':'Exact title','reserveTime':'2026-11-06 21:40',
                 'artifactFolder':str(folder),'scheduledSlot':'21:40'}
        public={'account':'yoon_master','title':'Exact title','reserveTime':'2026-11-06 21:40','scheduledSlot':'21:40'}
        with patch.object(ab,'ROOT',self.root):
            self.assertEqual(ab.publication_identity(public,[attempt])['scheduledSlot'],'20:30')
            self.assertEqual(public['scheduledSlot'],'21:40')
            self.assertEqual(ab.publication_identity({**public,'title':'Other title'},[attempt])['scheduledSlot'],'21:40')
            (folder/'reservation-evidence.json').unlink()
            self.assertEqual(ab.publication_identity(public,[attempt])['scheduledSlot'],'21:40')

if __name__=='__main__':unittest.main()
