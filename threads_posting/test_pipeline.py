import copy
from datetime import datetime,timezone,timedelta
import hashlib,json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from . import config,pipeline,scheduler

class LedgerTests(unittest.TestCase):
    def setUp(self):
        events = patch('threads_posting.pipeline._emit_crew_state')
        events.start(); self.addCleanup(events.stop)
        learning = patch('common.llm_client.record_verified_work', return_value={'status':'test_only'})
        learning.start(); self.addCleanup(learning.stop)
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.db=Path(self.temp.name)/'ledger.db'
        self.c=config.defaults();self.now=datetime.now(timezone.utc);self.day=self.now.astimezone(pipeline.KST).date().isoformat()
        self.c.update(enabled=True,activationApproved=True,activatedAt=(self.now-timedelta(days=1)).isoformat(),endsAt=(self.now+timedelta(days=13)).isoformat(),startDate=self.day,endDate=self.day)
        self.c['connection']={'connected':True,'account_verified':True,'account_key':'mustpickinfo','publishReady':True}
        source_patch=patch('threads_posting.authoring.article_snapshot',return_value=self.document()['source']);source_patch.start();self.addCleanup(source_patch.stop)
    def document(self,id='one',slot='00:00',mode='cf_inbound'):
        source={'url':'https://www.must-pick.com/example','body':'Observed public source','body_sha256':hashlib.sha256(b'Observed public source').hexdigest()}
        attr=None if mode=='warmup' else pipeline.receipt('mustpickinfo',source['url'],self.day,slot,id)
        parts=[{'kind':'main','text':'먼저 확인할 핵심 정보\n확인 순서 첫 단계\n세부 조건과 절차를 확인해요'}]
        if mode!='warmup':
            parts.append({'kind':'followup','text':'제가 직접 정리·운영하는 블로그에 상세 가이드를 정리했습니다.\n'+attr['outboundUrl']})
        d={'schema':'threads-document-v1','content_id':id,'account_key':'mustpickinfo','publication_date':self.day,'slot':slot,'mode':mode,'followup_delay_seconds':120,'title':'Example','source':source,'attribution':attr,'parts':parts}
        d['review']={'approved':True,'reason':'supported','claims':[{'claim':'확인 순서','quote':'Observed','source_url':source['url']}],'checks':dict.fromkeys(pipeline.REVIEW_KEYS,True),'binding':pipeline.binding(d)};return d
    def test_changed_schedule_invalidates_review(self):
        d=self.document();d['slot']='10:00'
        with self.assertRaises(ValueError):pipeline.import_document(d,self.c,self.db)
    def test_missing_review_checks_block(self):
        d=self.document();d['review']['checks']={'anything':True}
        with self.assertRaises(ValueError):pipeline.validate_document(d,self.c)
    def test_zero_links_in_main_post_rule_enforced(self):
        d=self.document()
        d['parts'][0]['text']='본문에 링크가 들어가면 차단됩니다 https://www.must-pick.com/example'
        d['review']['binding']=pipeline.binding(d)
        with self.assertRaisesRegex(ValueError,'Zero links in main post required'):
            pipeline.validate_document(d,self.c)
    def test_legacy_warmup_without_followup_is_blocked(self):
        d=self.document(id='warm1',slot='08:00',mode='warmup')
        self.assertEqual(len(d['parts']),1)
        self.assertIsNone(d['attribution'])
        with self.assertRaisesRegex(ValueError, r'main \+ followup link pair'):
            pipeline.validate_document(d,self.c)
    def test_future_slot_blocks(self):
        d=self.document(slot='23:59');pipeline.import_document(d,self.c,self.db)
        with pipeline.connect(self.db) as db:
            with self.assertRaisesRegex(RuntimeError,'slot_not_due'):pipeline.begin_send(db,'one-0',self.c,datetime.fromisoformat(self.day+'T00:01:00+09:00'))
    def test_cap_consumes_unknown_and_intent(self):
        c2=dict(self.c,mainDailyCap=2)
        for id in ('one','two','three'):pipeline.import_document(self.document(id),c2,self.db)
        with pipeline.connect(self.db) as db:
            pipeline.begin_send(db,'one-0',c2);pipeline._update(db,'one-0','submitted_unknown');pipeline.begin_send(db,'two-0',c2)
            with self.assertRaisesRegex(RuntimeError,'daily_cap'):pipeline.begin_send(db,'three-0',c2)
    def test_changed_ledger_text_blocked(self):
        pipeline.import_document(self.document(),self.c,self.db)
        with pipeline.connect(self.db) as db:
            db.execute("UPDATE parts SET text='tampered' WHERE part_id='one-0'")
            with self.assertRaisesRegex(RuntimeError,'ledger_document_mismatch'):pipeline.begin_send(db,'one-0',self.c)
    def test_unknown_not_reposted(self):
        pipeline.import_document(self.document(),self.c,self.db)
        class API:
            @staticmethod
            def connection_status(c):return c['connection']
            @staticmethod
            def submit_part(c,p,callback):callback();raise TimeoutError()
        with self.assertRaises(TimeoutError):pipeline.publish('one-0',self.c,self.db,API)
        with self.assertRaisesRegex(RuntimeError,'never_resend'):pipeline.publish('one-0',self.c,self.db,API)
        with pipeline.connect(self.db) as db:self.assertEqual(db.execute("SELECT state FROM parts WHERE part_id='one-0'").fetchone()[0],'submitted_unknown')
    def test_public_verifier_failure_retains_api_id(self):
        pipeline.import_document(self.document(),self.c,self.db)
        class API:
            @staticmethod
            def connection_status(c):return c['connection']
            @staticmethod
            def submit_part(c,p,callback):callback();return {'platform_id':'123','permalink':None}
            @staticmethod
            def verify_public(*args):raise TimeoutError()
        result=pipeline.publish('one-0',self.c,self.db,API)
        self.assertEqual(result['state'],'api_submitted');self.assertEqual(result['platform_id'],'123')
        with pipeline.connect(self.db) as db:
            row=db.execute("SELECT * FROM parts WHERE part_id='one-0'").fetchone();self.assertIsNone(row['published_at']);self.assertIsNotNone(row['api_submitted_at']);self.assertEqual(row['publication_time_basis'],'unknown')
    def test_trial_starts_only_activation(self):
        c=config.defaults();self.assertIsNone(c['activatedAt']);c['connection']=self.c['connection'];activated=config.activate(c,approved=True,now=self.now)
        self.assertEqual(datetime.fromisoformat(activated['endsAt'])-datetime.fromisoformat(activated['activatedAt']),timedelta(days=14))
    def test_disabled_tick_no_external_call(self):
        c=config.defaults();path=Path(self.temp.name)/'config.json';config.save(c,path)
        with patch('threads_posting.pipeline.reconcile',side_effect=AssertionError('network')),patch('threads_posting.scheduler.lock'):
            self.assertEqual(scheduler.tick(path,self.db,Path(self.temp.name)/'snapshot.json')['state'],'noop')
    def test_concurrent_remaining_cap_only_one_claims(self):
        import concurrent.futures,threading
        c2=dict(self.c,mainDailyCap=2)
        for id in ('one','two','three'):pipeline.import_document(self.document(id),c2,self.db)
        with pipeline.connect(self.db) as db:pipeline.begin_send(db,'one-0',c2)
        barrier=threading.Barrier(2)
        def claim(id):
            with pipeline.connect(self.db) as db:
                barrier.wait()
                try:pipeline.begin_send(db,id,c2);return 'sent'
                except RuntimeError as exc:return str(exc)
        with concurrent.futures.ThreadPoolExecutor(2) as pool:results=list(pool.map(claim,('two-0','three-0')))
        self.assertCountEqual(results,['sent','daily_cap'])
    def test_followup_requires_verified_parent_and_delay(self):
        d=self.document();pipeline.import_document(d,self.c,self.db)
        with pipeline.connect(self.db) as db:
            with self.assertRaisesRegex(RuntimeError,'verified_parent'):pipeline.begin_send(db,'one-1',self.c)
            pipeline._update(db,'one-0','published_verified',platform_id='123',published_at=(self.now-timedelta(seconds=30)).isoformat())
            with self.assertRaisesRegex(RuntimeError,'followup_delay_not_elapsed'):pipeline.begin_send(db,'one-1',self.c,now=self.now)
            pipeline._update(db,'one-0','published_verified',platform_id='123',published_at=(self.now-timedelta(seconds=135)).isoformat())
            pipeline.begin_send(db,'one-1',self.c,now=self.now)
    def test_final_config_disabled_before_callback(self):
        pipeline.import_document(self.document(),self.c,self.db)
        class API:
            @staticmethod
            def connection_status(c):return c['connection']
            @staticmethod
            def submit_part(c,p,callback):callback();raise AssertionError('must not publish')
        with self.assertRaisesRegex(RuntimeError,'disabled'):pipeline.publish('one-0',self.c,self.db,API,config_loader=lambda:dict(self.c,enabled=False))
        with pipeline.connect(self.db) as db:self.assertEqual(db.execute("SELECT state FROM parts WHERE part_id='one-0'").fetchone()[0],'queued')
    def test_trial_end_keeps_readonly_measurement_without_authoring(self):
        c=dict(self.c,continuousMode=False,endsAt=(self.now-timedelta(seconds=1)).isoformat());path=Path(self.temp.name)/'config.json';config.save(c,path)
        with patch('threads_posting.scheduler.lock'),patch('threads_posting.pipeline.reconcile') as reconcile,patch('threads_posting.measurement.should_collect',return_value=True),patch('threads_posting.measurement.collect',return_value={'status':'partial','revenue':None}) as collect,patch('threads_posting.authoring.prepare_next',side_effect=AssertionError('no model after trial')),patch('threads_posting.pipeline.publish',side_effect=AssertionError('no publish after trial')):
            result=scheduler.tick(path,self.db,Path(self.temp.name)/'snapshot.json')
        self.assertEqual(result['state'],'trial_ended');reconcile.assert_called_once();collect.assert_called_once()
    def test_evening_activation_never_backfills_morning(self):
        evening=datetime.fromisoformat(self.day+'T20:00:00+09:00')
        self.assertEqual(scheduler.current_slot(self.c,evening),'18:10')
        self.assertIsNone(scheduler.current_slot(self.c,evening,{'18:10'}))
        self.assertIsNone(scheduler.current_slot(self.c,evening,{'08:00','18:10'}))
    def test_timestamp_recovery_preserves_existing_public_proof(self):
        pipeline.import_document(self.document(),self.c,self.db)
        with pipeline.connect(self.db) as db:
            pipeline._update(db,'one-0','published_verified',platform_id='123',verified_at='2026-10-15T01:00:00+00:00')
            part=dict(db.execute("SELECT * FROM parts WHERE part_id='one-0'").fetchone())
        class API:
            @staticmethod
            def verify_public(*args):return {k:part[k] for k in ('account_key','platform_id','text_sha256','outbound_url')}|{'public':False,'verified':False,'published_at':'2026-10-15T00:55:00+00:00'}
        pipeline.reconcile(self.c,self.db,API)
        with pipeline.connect(self.db) as db:
            row=db.execute("SELECT * FROM parts WHERE part_id='one-0'").fetchone();self.assertEqual(row['published_at'],'2026-10-15T00:55:00+00:00');self.assertEqual(row['state'],'published_verified');self.assertEqual(row['verified_at'],'2026-10-15T01:00:00+00:00')
    def test_uncertain_adoption_requires_unique_exact_post_after_intent(self):
        pipeline.import_document(self.document(),self.c,self.db)
        with pipeline.connect(self.db) as db:
            pipeline._update(db,'one-0','published_verified',platform_id='999',published_at=(self.now-timedelta(seconds=200)).isoformat())
            pipeline.begin_send(db,'one-1',self.c,now=self.now-timedelta(seconds=5));pipeline._update(db,'one-1','submitted_unknown');row=dict(db.execute("SELECT * FROM parts WHERE part_id='one-1'").fetchone())
        evidence={k:row[k] for k in ('account_key','text_sha256','outbound_url')}|{'matched':True,'match_count':1,'platform_id':'123','permalink':'https://www.threads.com/@mustpickinfo/post/EXAMPLE','published_at':self.now.isoformat()}
        for changed in ({'match_count':0},{'match_count':2},{'text_sha256':'wrong'},{'account_key':'other'},{'outbound_url':'wrong'},{'published_at':(self.now-timedelta(minutes=1)).isoformat()}):
            with self.assertRaises(ValueError):pipeline.adopt_recovered('one-1',evidence|changed,self.db)
        pipeline.adopt_recovered('one-1',evidence,self.db)
        with pipeline.connect(self.db) as db:self.assertEqual(db.execute("SELECT state FROM parts WHERE part_id='one-1'").fetchone()[0],'api_submitted')

if __name__=='__main__':unittest.main()


class AuthoringPolicyTests(unittest.TestCase):
    """Pure policy checks: no files, model calls, network, or publication."""
    def test_real_generator_signature_and_fallback_identity(self):
        from . import authoring
        from unittest.mock import MagicMock
        fixture = LedgerTests(); fixture.day = '2026-10-19'
        source = fixture.document()['source']
        cfg = config.defaults(); cfg['model'] = 'gpt-6-luna'
        def generated(prompt, model, response_schema=None):
            return {'hook_main': '첫 번째 사실\n두 번째 사실\n세 번째 사실', 'followup': ''}, model
        with patch.object(authoring, 'article_snapshot', return_value=source), patch.object(authoring, 'load_hook_templates', return_value=[]), patch.object(config, 'PRIVATE', MagicMock()), patch.object(authoring, 'write'), patch.object(pipeline, 'validate_document'), patch.object(authoring.codex_cli, 'refresh_runtime', return_value={'authenticated': True, 'models': [{'id': 'gpt-6-luna'}]}), patch.object(authoring.codex_cli, 'generate_local', side_effect=generated) as generate:
            result = authoring.prepare(cfg, source['url'], fixture.day, '12:30', mode='cf_inbound')
            self.assertEqual(result['document']['model'], 'gpt-6-luna')
            self.assertNotIn('memory_session_id', generate.call_args.kwargs)
            generate.side_effect = RuntimeError('test unavailable')
            result = authoring.prepare(cfg, source['url'], fixture.day, '12:30', mode='cf_inbound')
            self.assertEqual(result['document']['model'], 'template-fallback')
            self.assertEqual('RuntimeError', result['document']['generation_error'])
            def invalid_main(prompt, model, response_schema=None):
                return {'hook_main': 'https://example.com', 'followup': ''}, model
            generate.side_effect = invalid_main
            result = authoring.prepare(cfg, source['url'], fixture.day, '12:30', mode='cf_inbound')
            self.assertEqual(result['document']['model'], 'template-fallback')
            self.assertEqual(result['document']['generation_provenance']['generated_model'], 'gpt-6-luna')
            self.assertEqual(result['document']['generation_provenance']['accepted_model_variants'], [])
            self.assertEqual(result['document']['generation_provenance']['selected_main_origin'], 'template')
            def unsupported_affiliate(prompt, model, response_schema=None):
                data = json.loads(prompt.split('자료:\n', 1)[1])
                return {'hook_main': '첫 번째 사실\n두 번째 사실\n세 번째 사실', 'followup': '광고/제휴 링크입니다.\n' + data['outbound_url']}, model
            generate.side_effect = unsupported_affiliate
            result = authoring.prepare(cfg, source['url'], fixture.day, '12:30', mode='cf_inbound')
            self.assertEqual(result['document']['model'], 'gpt-6-luna')
            self.assertEqual(result['document']['generation_provenance']['followup_origin'], 'template')
            self.assertNotIn('광고', result['document']['parts'][1]['text'])
            self.assertNotIn('제휴', result['document']['parts'][1]['text'])
            self.assertEqual(result['document']['parts'][1]['text'].count(result['document']['attribution']['outboundUrl']), 1)

    def test_all_sixteen_domains_without_adsense_gate(self):
        from . import authoring
        from unittest.mock import MagicMock
        db = MagicMock()
        db.execute.return_value = []
        root = MagicMock()
        (root / 'cf_posting/output').glob.return_value = []
        rows = [{'url': 'https://' + domain + '/latest-article'} for domain in config.CF_DOMAINS_16]
        with patch.object(pipeline, 'connect') as connect, patch.object(config, 'ROOT', root):
            connect.return_value.__enter__.return_value = db
            result = authoring.catalog({'articleCatalog': rows})
        self.assertEqual(len(result), 16)
        self.assertEqual({row['url'] for row in result}, {row['url'] for row in rows})

    def test_four_line_variants_and_exact_reply_link(self):
        from . import authoring
        url = 'https://baronote.kr/latest-article?utm_source=threads'
        variants, followup = authoring._build_3_variants(
            '생활 정보', '첫 번째 조건과 신청 절차를 확인합니다. 두 번째 조건과 상세 내역을 확인합니다. 세 번째 조건과 주의사항을 확인합니다.', outbound_url=url)
        for variant in variants.values():
            self.assertEqual(len(variant['text'].splitlines()), 4)
            self.assertFalse(pipeline.contains_external_url(variant['text']))
        self.assertEqual(followup.count(url), 1)

    def test_bare_and_uppercase_urls_blocked(self):
        for text in ('HTTPS://example.com/a', 'www.example.com', 'example.kr/a'):
            self.assertTrue(pipeline.contains_external_url(text))

    def test_pair_and_line_count_validation(self):
        fixture = LedgerTests()
        fixture.day = '2026-10-19'
        doc = fixture.document()
        pipeline.validate_document(doc, config.defaults())
        for text in ('한 줄뿐', '첫 줄\n둘째 줄\n셋째 줄\n넷째 줄\n다섯째 줄'):
            bad = copy.deepcopy(doc)
            bad['parts'][0]['text'] = text
            with self.assertRaisesRegex(ValueError, '3 or 4 lines'):
                pipeline.validate_document(bad, config.defaults())
        bad = copy.deepcopy(doc)
        bad['parts'] = bad['parts'][:1]
        with self.assertRaisesRegex(ValueError, 'exact attributed link in followup'):
            pipeline.validate_document(bad, config.defaults())

    def test_catalog_recent_domain_rotates_after_unused(self):
        from . import authoring
        from unittest.mock import MagicMock
        db = MagicMock()
        db.execute.return_value = [(json.dumps({'source': {'url': 'https://must-pick.com/used'}}),)]
        root = MagicMock()
        (root / 'cf_posting/output').glob.return_value = []
        rows = [{'url': 'https://must-pick.com/new'}, {'url': 'https://baronote.kr/new'},
                {'url': 'https://must-pick.com/older'}]
        with patch.object(pipeline, 'connect') as connect, patch.object(config, 'ROOT', root):
            connect.return_value.__enter__.return_value = db
            result = authoring.catalog({'articleCatalog': rows})
        self.assertEqual(result[0]['url'], 'https://baronote.kr/new')
        self.assertEqual(result[1]['url'], 'https://must-pick.com/new')

    def test_no_official_links_still_queues_article_pair_mode(self):
        from . import authoring
        from unittest.mock import MagicMock
        private = MagicMock()
        (private / 'threads-evaluations.json').read_text.side_effect = OSError()
        candidate = {'url': 'https://baronote.kr/new'}
        snapshot = {'url': candidate['url'], 'body_sha256': 'hash'}
        with patch.object(config, 'PRIVATE', private), patch.object(authoring, 'catalog', return_value=[candidate]), \
                patch.object(authoring, 'article_snapshot', return_value=snapshot), \
                patch.object(authoring, 'official_links', return_value=[]), \
                patch.object(authoring, 'prepare', return_value={'approved': True, 'reason': 'ok', 'document': {'content_id': 'test'}}) as prepare, \
                patch.object(authoring, 'write'), patch.object(pipeline, 'import_document'):
            legacy = config.defaults()
            legacy['slotModes']['08:00'] = 'warmup'
            result = authoring.prepare_next(legacy, '2026-10-19', '08:00')
        self.assertEqual(result['state'], 'queued')
        self.assertEqual(prepare.call_args.args[4], [])
        self.assertEqual(prepare.call_args.kwargs['mode'], 'cf_inbound')

    def test_legacy_main_only_cannot_pass_send_validation(self):
        fixture = LedgerTests()
        fixture.day = '2026-10-19'
        with self.assertRaisesRegex(ValueError, 'pair is required'):
            pipeline.validate_document(fixture.document(mode='warmup'), config.defaults())
