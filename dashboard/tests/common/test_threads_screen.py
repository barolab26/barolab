import hashlib
import tempfile
import unittest
from datetime import datetime,timezone,timedelta
from pathlib import Path
from unittest.mock import patch,Mock
from threads_posting import posting as engine
from common.threads_screen import recover_unknown,repair_claims,ScreenAdapter,install,web_identity


class ThreadsScreenTests(unittest.TestCase):
    def setUp(self):
        self.text='안내\n\nhttps://www.healthcox.com/a?utm_source=threads&utm_medium=social&utm_campaign=cf_bridge&utm_content=unique'
        self.part={'account_key':'mustpickinfo','kind':'followup','parent_platform_id':'123',
            'text':self.text,'text_sha256':hashlib.sha256(self.text.encode()).hexdigest(),
            'outbound_url':self.text.splitlines()[-1],'intent_at':'2026-10-22T23:35:00+00:00'}
        self.row={'id':'456','username':'mustpickinfo','text':self.text,'permalink':'https://www.threads.com/@mustpickinfo/post/Abc123',
            'timestamp':'2026-10-22T23:36:00+0000','is_reply':True,'replied_to':{'id':'123'}}
        self.client=Mock(base='https://graph.threads.net/v1.0',token='private-test')
        self.client_patch=patch.object(engine,'_threads_adapter_Client',return_value=self.client);self.client_patch.start();self.addCleanup(self.client_patch.stop)
        self.identity=patch.object(engine,'_threads_adapter__identity');self.identity.start();self.addCleanup(self.identity.stop)
    def recover(self,rows=None,paging=None):
        with patch('requests.get',return_value=Mock(status_code=200,json=lambda:{'data':rows if rows is not None else [self.row],'paging':paging or {}})) as get:
            result=recover_unknown(engine,{},self.part)
            self.last_get=get
            return result
    def test_reply_uses_parent_conversation_read_only(self):
        self.assertTrue(self.recover()['matched'])
        self.assertEqual(self.last_get.call_args.args[0],'https://graph.threads.net/v1.0/123/conversation')
        self.assertFalse(self.last_get.call_args.kwargs['allow_redirects'])
        self.client.request.assert_not_called()
    def test_wrong_parent_is_not_recovered(self):
        self.row['replied_to']['id']='999';self.assertFalse(self.recover()['matched'])
    def test_wrong_account_text_time_kind_rejected(self):
        for change in ({'username':'other'},{'text':'different'},{'timestamp':'2026-10-22T23:34:00+0000'},{'is_reply':False}):
            self.assertFalse(self.recover([{**self.row,**change}])['matched'])
    def test_hash_and_utm_rejected_before_network(self):
        self.part['text_sha256']='bad';self.assertFalse(self.recover()['matched']);self.last_get.assert_not_called()
    def test_incomplete_inventory_and_ambiguous_match_rejected(self):
        self.assertEqual(self.recover(paging={'next':'ignored','cursors':{'after':'cursor'}})['reason'],'recovery_inventory_incomplete')
        self.assertEqual(self.recover([self.row,{**self.row,'id':'789'}])['reason'],'recovery_ambiguous_matches')
    def test_main_uses_readonly_feed_and_no_link_needed(self):
        self.part.update(kind='main',text='새 글',outbound_url=None,text_sha256=hashlib.sha256('새 글'.encode()).hexdigest())
        self.client.request.return_value={'data':[{**self.row,'text':'새 글','is_reply':False}]}
        with patch('requests.get') as get:
            self.assertTrue(recover_unknown(engine,{},self.part)['matched']);get.assert_not_called()
        self.assertEqual(self.client.request.call_args.args[:2],('GET','me/threads'))
    def test_login_required_disables_screen_submission(self):
        adapter=ScreenAdapter(engine)
        with patch.object(engine,'_threads_adapter_readiness_status',return_value={'publishReady':True}),patch('common.threads_screen.session',side_effect=RuntimeError('offline')):
            result=adapter.readiness_status({})
        self.assertFalse(result['publishReady']);self.assertEqual(result['reason'],'threads_web_login_required')
    def test_public_profile_is_not_login_proof(self):
        page=Mock();page.locator.return_value.evaluate_all.return_value=False
        self.assertFalse(web_identity(page))
    def test_abandoned_claim_preserves_evidence_and_fresh_claim(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'db.sqlite3';now=datetime.now(timezone.utc)
            with engine.connect(path) as db:
                for slot,age in [('08:00',60),('12:30',2)]:
                    db.execute('INSERT INTO authoring_slots VALUES(?,?,?,?,?,?)',('mustpickinfo','2026-10-23',slot,'claimed',None,(now-timedelta(minutes=age)).isoformat()))
            repair_claims(engine,{'account_key':'mustpickinfo'},path,now)
            with engine.connect(path) as db:
                self.assertEqual([r['slot'] for r in db.execute('SELECT * FROM authoring_slots')],['12:30'])
                self.assertEqual(db.execute("SELECT count(*) FROM runtime WHERE key LIKE 'abandoned_authoring_claim:%'").fetchone()[0],1)
    def test_due_queued_main_is_selected_after_its_original_slot(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'db.sqlite3'
            now=datetime(2026,10,23,10,0,tzinfo=timezone.utc)
            with engine.connect(path) as db:
                db.execute("INSERT INTO parts(part_id,attempt_id,account_key,kind,state,publication_date,slot,document,text,text_sha256,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                    ('part','attempt','mustpickinfo','main','queued','2026-10-23','12:30','{}','body','hash',now.isoformat(),now.isoformat()))
                db.execute('INSERT INTO authoring_slots VALUES(?,?,?,?,?,?)',('mustpickinfo','2026-10-23','12:30','claimed',None,(now-timedelta(hours=1)).isoformat()))
            repair_claims(engine,{'account_key':'mustpickinfo'},path,now)
            with engine.connect(path) as db:self.assertEqual(db.execute('SELECT count(*) FROM authoring_slots').fetchone()[0],1)
            names=['_namespace_adapter','_threads_scheduler_tick','_threads_scheduler_current_slot']
            originals={name:getattr(engine,name) for name in names}
            try:
                with patch.object(engine,'_threads_config_DB',path):install(engine)
                config={'account_key':'mustpickinfo','preferredTimes':['08:00','12:30','18:10','21:30']}
                self.assertEqual(engine._threads_scheduler_current_slot(config,now),'12:30')
                self.assertEqual(engine._threads_scheduler_current_slot(config,now,{'08:00','12:30'}),'18:10')
                next_day=now+timedelta(days=1)
                self.assertEqual(engine._threads_scheduler_current_slot(config,next_day),'08:00')
            finally:
                for name,value in originals.items():setattr(engine,name,value)

    def test_uncertain_browser_tab_is_preserved_until_readonly_adoption(self):
        import common.threads_screen as screen
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);database=root/'dashboard/data/threads.sqlite3';database.parent.mkdir(parents=True)
            proof=root/'threads_posting/output/scheduled/2026-10-23/p/ego-1/intent.json';proof.parent.mkdir(parents=True)
            proof.write_text('{"partId":"p","targetId":"target-1"}')
            with engine.connect(database) as db:
                db.execute("INSERT INTO parts(part_id,attempt_id,account_key,kind,state,publication_date,slot,document,text,text_sha256,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",('p','a','mustpickinfo','main','submitted_unknown','2026-10-23','12:30','{}','body','hash','now','now'))
            page=Mock(url='https://www.threads.com/@mustpickinfo');page.context.new_cdp_session.return_value.send.return_value={'targetInfo':{'targetId':'target-1'}}
            browser=Mock(contexts=[Mock(pages=[page])])
            with patch.object(screen,'__file__',str(root/'dashboard/common/threads_screen.py')),patch('playwright.sync_api.sync_playwright'),patch('common.browser_session.connect_sync',return_value=browser),patch('common.ubuntu_naver_browser.focus_workflow_window') as focus:
                with self.assertRaisesRegex(RuntimeError,'uncertain_submission_tab_preserved'):
                    with screen.session(for_submission=True):pass
                focus.assert_not_called()
                with engine.connect(database) as db:db.execute("UPDATE parts SET state='api_submitted',platform_id='456' WHERE part_id='p'")
                with screen.session(for_submission=True) as existing:self.assertIs(existing,page)
            page.close.assert_not_called()
            page.goto.assert_not_called()

    def test_resume_requires_completed_exact_draft_same_tab_and_no_intent(self):
        from common.threads_screen import completed_draft
        import json
        page=Mock();editor=page.locator.return_value;editor.count.return_value=1;editor.inner_text.return_value='승인 문장\n'
        page.context.new_cdp_session.return_value.send.return_value={'targetInfo':{'targetId':'same-tab'}}
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);proof=root/'ego-123/type/screen-execution.json';proof.parent.mkdir(parents=True)
            state={'status':'screen_task_complete','editorTargetId':'same-tab','written':['0']};proof.write_text(json.dumps(state))
            self.assertEqual(completed_draft(page,{'text':'승인 문장'},root),str(proof))
            self.assertIsNone(completed_draft(page,{'text':'다른 문장'},root))
            state['editorTargetId']='other-tab';proof.write_text(json.dumps(state))
            self.assertIsNone(completed_draft(page,{'text':'승인 문장'},root))
            state['editorTargetId']='same-tab';proof.write_text(json.dumps(state));(proof.parent.parent/'intent.json').write_text('{}')
            self.assertIsNone(completed_draft(page,{'text':'승인 문장'},root))

    def test_planning_uses_exact_saved_draft_and_slot(self):
        from dashboard.agents.style_strategy import plan_post
        prompts=[]
        def generate(prompt,**kwargs):
            prompts.append(prompt);kwargs['observer']('codex','test','returned',actual_model='observed-test')
            keys=kwargs['response_schema']['properties']
            if 'keyword' in keys:return {'message':'기존 원고를 유지합니다.','keyword':'반려동물 진료비'}
            if 'benchmarkNeeded' in keys:return {'message':'본문을 보존합니다.','researchTask':'기존 원고 확인','benchmarkNeeded':False,'consultAgents':[]}
            if 'writingGuide' in keys:return {'message':'직접 입력합니다.','writingGuide':'승인 본문과 문단을 보존한다.'}
            return {'message':'원래 시간대 원고의 복구 회의를 엽니다.'}
        with tempfile.TemporaryDirectory() as temp,patch('dashboard.agents.synapse.cached_index',return_value={}),patch('common.llm_settings.get_agent_brain',return_value={'provider':'codex','model':'test'}),patch('common.llm_client.generate_json',side_effect=generate),patch('common.crew_chat_bridge.emit_work_event'):
            result=plan_post('mustpickinfo','기존 승인 원고',Path(temp)/'opaque',{'agenda':{'publicationDate':'2026-10-23','slot':'12:30'},'existingDraft':{'title':'반려동물 진료비 확인','text':'보존할 실제 본문'}},'threads')
        self.assertEqual(result['agenda']['slot'],'12:30')
        self.assertEqual(result['agenda']['publicationDate'],'2026-10-23')
        self.assertIn('반려동물 진료비 확인',prompts[1])
        self.assertEqual(result['keyword'],'반려동물 진료비')

    def test_conference_installs_ui_adapter_without_api_submit(self):
        import inspect
        from common.conference_dispatch import install_channel_conferences
        source=inspect.getsource(install_channel_conferences)
        self.assertIn('from common.threads_screen import install',source)
        self.assertNotIn('_threads_adapter_submit_part',inspect.getsource(ScreenAdapter))

if __name__=='__main__':unittest.main()
