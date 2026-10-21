import json
import tempfile
import unittest
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch
from server import project_health as h, project_monitor as m


class ProjectMonitorTests(unittest.TestCase):
    def setUp(self):
        guard = patch.object(m, 'known_cf_candidates', return_value=[])
        guard.start(); self.addCleanup(guard.stop)
        report = patch.object(m, 'report_project_incident_once', return_value={'status': 'mocked'})
        report.start(); self.addCleanup(report.stop)

    def test_missing_or_stale_source_never_claims_success(self):
        with tempfile.TemporaryDirectory() as td, patch.object(h, 'ROOT', Path(td)):
            rows = h.observed_projects()
            self.assertTrue(all(r['status'] == 'unknown' for r in rows))
            self.assertTrue(all(r['verifiedPublicCount'] is None for r in rows))
            p = Path(td) / 'cf_posting/data/daily_schedule.json'
            p.parent.mkdir(parents=True)
            p.write_text(json.dumps({'date': '2000-01-01', 'createdAt': '2000-01-01T00:00:00+09:00',
                'items': [{'domain': 'example.com', 'status': 'published', 'publicUrl': 'https://example.com/a'}]}))
            row = h.observed_projects()[0]
            self.assertEqual(row['status'], 'stale')
            self.assertIsNone(row['verifiedPublicCount'])

    def test_bad_source_isolated_from_other_projects(self):
        with tempfile.TemporaryDirectory() as td, patch.object(h, 'ROOT', Path(td)):
            p = Path(td) / 'cf_posting/data/daily_schedule.json'; p.parent.mkdir(parents=True)
            for invalid in ([], {'runtime': []}, {'runtime': ['not-object']}):
                p.write_text(json.dumps(invalid))
                rows = h.observed_projects()
                self.assertEqual(len(rows), 6)
                self.assertEqual(rows[0]['status'], 'unknown')
            with patch.object(Path, 'read_bytes', side_effect=PermissionError), patch.object(Path, 'is_file', return_value=True):
                rows = h.observed_projects()
                self.assertEqual(len(rows), 6)
                self.assertEqual(rows[0]['source']['errorType'], 'PermissionError')

    def test_cf_public_requires_unique_domain_valid_url_and_today(self):
        with tempfile.TemporaryDirectory() as td, patch.object(h, 'ROOT', Path(td)):
            p = Path(td) / 'cf_posting/data/daily_schedule.json'; p.parent.mkdir(parents=True)
            p.write_text(json.dumps({'date': h.today_kst_str(), 'createdAt': h.now_kst_iso(), 'items': [
                {'domain': 'a', 'status': 'published', 'publicUrl': 'https://a.example/a'},
                {'domain': 'a', 'status': 'published', 'publicUrl': 'https://a.example/b'},
                {'domain': 'b', 'status': 'published', 'publicUrl': ''},
                {'domain': 'c', 'status': 'failed'}]}))
            row = h.observed_projects()[0]
            self.assertEqual(row['verifiedPublicCount'], 1)
            self.assertEqual(row['status'], 'attention')

    def test_fingerprint_ignores_collection_timestamp_and_sha(self):
        a = {'id': 'cf_blog', 'status': 'attention', 'counts': {'failed': 1}, 'observedState': 'unknown', 'source': {'sha256': 'a'}}
        b = dict(a, source={'sha256': 'b'})
        self.assertEqual(m.incident_key(a), m.incident_key(b))
        self.assertNotEqual(m.incident_key(a), m.incident_key(dict(a, counts={'failed': 2})))

    def test_normal_progress_does_not_reclassify_but_failure_identity_does(self):
        a={'id':'cf_blog','status':'attention','counts':{'failed':1,'waiting':3},'failures':[{'identity':'a','status':'failed'}]}
        b=dict(a,counts={'failed':1,'waiting':2,'processing':1})
        self.assertEqual(m.incident_key(a),m.incident_key(b))
        self.assertNotEqual(m.incident_key(a),m.incident_key(dict(b,failures=[{'identity':'b','status':'failed'}])))

    def test_registered_repair_only_exact_host_evidence(self):
        candidate={'domain':'example.com','taskId':'cf-repair:today:example.com','itemSha256':'a','scheduleSha256':'b','failureType':'editorial_seed_pinned_as_keyword','evidencePath':'private.json','evidenceSha256':'c'}
        project={'id':'cf_blog','ownerAgentIds':['publi']}
        with patch.object(m,'known_cf_candidates',return_value=[candidate]):
            action=m.action_for_triage(project,{'decision':'repair_known_cf','domain':'example.com'},[candidate])
            self.assertEqual(action,{'agent':'patch','tool':'repair_cf_known_failure','args':{'domain':'example.com','evidencePath':'private.json','evidenceSha256':'c'}})
            with self.assertRaises(ValueError): m.action_for_triage(project,{'decision':'repair_known_cf','domain':'unlisted.com'},[candidate])
        with patch.object(m,'known_cf_candidates',return_value=[]):
            with self.assertRaises(ValueError): m.action_for_triage(project,{'decision':'repair_known_cf','domain':'example.com'},[candidate])

    def test_once_only_and_restart_does_not_replay_model(self):
        with tempfile.TemporaryDirectory() as td, patch.object(m, 'STATE', Path(td)/'state.json'), patch.object(m, 'INCIDENTS', Path(td)/'incidents'), patch.object(m, 'POLL_SECONDS', 0):
            row = {'id':'cf_blog','status':'attention','counts':{'failed':1},'observedState':'unknown'}
            with patch.object(m, 'observed_projects', return_value=[row]), patch.object(m, '_triage', return_value={'decision':'hold','reason':'Needs evidence'}) as triage:
                self.assertTrue(m.process_project_monitor_once())
                self.assertFalse(m.process_project_monitor_once())
                self.assertEqual(triage.call_count, 1)
            path = next(m.INCIDENTS.glob('*.json')); data=json.loads(path.read_text(encoding='utf-8')); data['status']='triaging'; path.write_text(json.dumps(data))
            m.recover_interrupted_triage()
            self.assertEqual(json.loads(path.read_text(encoding='utf-8'))['status'], 'interrupted_hold')

    def test_key_upgrade_preserves_old_receipt_and_does_not_resample(self):
        with tempfile.TemporaryDirectory() as td, patch.object(m,'STATE',Path(td)/'state.json'), patch.object(m,'INCIDENTS',Path(td)/'incidents'):
            m.INCIDENTS.mkdir();m.STATE.write_text('{}')
            old={'id':'cf_blog','status':'attention','counts':{'failed':1,'waiting':2}}
            current=dict(old,failures=[{'identity':'tripmarvel.com','status':'failed'}])
            path=m.INCIDENTS/'old.json';path.write_text(json.dumps({'status':'needs_attention','observation':old}));raw=path.read_bytes()
            with patch.object(m,'observed_projects',return_value=[current]): m.recover_interrupted_triage()
            state=json.loads(m.STATE.read_text(encoding='utf-8'));self.assertIn(m.incident_key(current),state['upgradeBaseline'])
            self.assertEqual(path.read_bytes(),raw)
            self.assertEqual(state['upgradeBaselineBindings'][0]['previousSha256'],m.hashlib.sha256(raw).hexdigest())
            self.assertNotIn(m.incident_key(dict(current,failures=[{'identity':'other.com','status':'failed'}])),state['upgradeBaseline'])

    def test_other_incident_is_not_delayed_by_global_cooldown(self):
        with tempfile.TemporaryDirectory() as td, patch.object(m, 'STATE', Path(td)/'state.json'), patch.object(m, 'INCIDENTS', Path(td)/'incidents'), patch.object(m, 'POLL_SECONDS', 0):
            rows=[{'id':p,'status':'stale','counts':{},'observedState':'unknown'} for p in ('cf_blog','threads')]
            with patch.object(m, 'observed_projects', return_value=rows), patch.object(m, '_triage', return_value={'decision':'hold','reason':'stale'}):
                self.assertTrue(m.process_project_monitor_once()); self.assertTrue(m.process_project_monitor_once())
                self.assertEqual(len(list(m.INCIDENTS.glob('*.json'))), 2)

class QuotaReportTests(unittest.TestCase):
    now = datetime(2026, 10, 21, 12, tzinfo=h.KST)

    def test_cf_due_future_verified_and_missing_assignments(self):
        doc = {'date': '2026-10-21', 'items': [
            {'domain': 'a', 'scheduledTime': '11:00', 'status': 'published', 'publicUrl': 'https://a.example/post'},
            {'domain': 'b', 'scheduledTime': '11:30', 'status': 'reserved'},
            {'domain': 'c', 'scheduledTime': '13:00', 'status': 'waiting'}]}
        with patch.object(h, 'schedule_constants', return_value={'ALL_DOMAINS': ['a', 'b', 'c']}):
            q = h.publication_quota('cf_blog', doc, self.now, True)
            self.assertEqual((q['due'], q['verified'], q['missing']), (2, 1, 1))
            self.assertEqual(q['missingSlots'], ['b'])
            self.assertEqual(h.publication_quota('cf_blog', doc, self.now, False)['status'], 'unknown')
            self.assertEqual(h.publication_quota('cf_blog', dict(doc, date='2026-10-20'), self.now, True)['status'], 'unknown')
            doc['items'].pop()
            self.assertEqual(h.publication_quota('cf_blog', doc, self.now, True)['reason'], 'incomplete_schedule')

    def test_naver_reserved_is_not_public_and_old_proof_is_unknown(self):
        policy = {'DAILY_SLOTS': {'acc': ('11:00', '19:00')}, 'LEGACY_SINGLE_SLOTS': {}, 'LEGACY_SLOT_ALIASES': {}}
        proof = {'checkedAt': self.now.isoformat(), 'evidence': [
            {'account': 'acc', 'reserveTime': '2026-10-21 11:00', 'verified': True,
             'publicPublicationVerified': True, 'publicUrl': 'https://blog.naver.com/blog/123', 'status': 'reserved'}]}
        with patch.object(h, 'schedule_constants', return_value=policy), patch.object(h, 'load_json', return_value=proof):
            self.assertEqual(h.publication_quota('naver_blog', {}, self.now, True)['missing'], 1)
            proof['evidence'][0].pop('status')  # Canonical verifier records have no pipeline status.
            self.assertEqual(h.publication_quota('naver_blog', {}, self.now, True)['verified'], 1)
            proof['checkedAt'] = '2026-10-20T12:00:00+09:00'
            self.assertEqual(h.publication_quota('naver_blog', {}, self.now, True)['status'], 'unknown')

    def test_threads_invalid_source_and_unverified_are_not_success(self):
        doc = {'configuration': {'enabled': True, 'preferredTimes': ['08:00', '18:00']},
               'today': {'date': '2026-10-21', 'counts': []}, 'countsComplete': True,
               'recent': [{'kind': 'main', 'publication_date': '2026-10-21', 'slot': '08:00',
                           'state': 'submitted_unknown', 'permalink': 'https://threads.net/a'}]}
        self.assertEqual(h.publication_quota('threads', doc, self.now, True)['missing'], 1)
        for field, value in [('configuration', []), ('today', {'date': '2026-10-21', 'counts': [None]})]:
            self.assertEqual(h.publication_quota('threads', dict(doc, **{field: value}), self.now, True)['status'], 'unknown')

    def test_report_jev_outage_deduplicates_without_triage(self):
        project = {'id': 'cf_blog', 'status': 'attention', 'counts': {'failed': 1},
                   'quota': {'status': 'observed', 'date': '2026-10-21', 'due': 2, 'verified': 1, 'missing': 1, 'missingSlots': ['a']}}
        with tempfile.TemporaryDirectory() as td, patch.object(m, 'STATE', Path(td)/'state.json'), \
                patch('common.jev.classify_incident', return_value={'status': 'api_error'}) as jev, \
                patch('common.crew_chat_bridge.emit_pipeline_crew_message', side_effect=lambda *a, **kw: kw['msg_id']) as emit, \
                patch.object(m, '_triage') as triage:
            result = m.report_project_incident_once(project)
            self.assertEqual(result['status'], 'accepted_or_queued')
            self.assertEqual(m.report_project_incident_once(project)['status'], 'already_reported_or_claimed')
            self.assertEqual((jev.call_count, emit.call_count), (1, 1)); triage.assert_not_called()
            self.assertEqual(emit.call_args.args[0], 'ego-lite')
            self.assertIn('@자비스', emit.call_args.args[1])
            self.assertIn('JEV 분류 미확인', emit.call_args.args[1])
            receipt = json.loads(Path(result['receiptPath']).read_text(encoding='utf-8'))
            self.assertFalse(receipt['roomDeliveryVerified'])
            changed = dict(project, quota=dict(project['quota'], missingSlots=['a', 'b']))
            self.assertNotEqual(m.incident_key(project), m.incident_key(changed))

    def test_failed_delivery_not_labeled_sent(self):
        with tempfile.TemporaryDirectory() as td, patch.object(m, 'STATE', Path(td)/'state.json'), \
                patch('common.jev.classify_incident', return_value={'status': 'api_error'}) as jev, \
                patch('common.crew_chat_bridge.emit_pipeline_crew_message', return_value=None) as emit:
            self.assertEqual(m.report_project_incident_once({'id': 'threads', 'status': 'stale'})['status'], 'delivery_failed')
            emit.side_effect = lambda *a, **kw: kw['msg_id']
            self.assertEqual(m.report_project_incident_once({'id': 'threads', 'status': 'stale'})['status'], 'accepted_or_queued')
            self.assertEqual(jev.call_count, 1)
            self.assertEqual(emit.call_args_list[0].kwargs['msg_id'], emit.call_args_list[1].kwargs['msg_id'])

    def test_kin_actual_attempt_not_fresh_snapshot_establishes_liveness(self):
        import sqlite3
        with tempfile.TemporaryDirectory() as td, patch.object(h, 'ROOT', Path(td)):
            path = Path(td)/'server/data/kin.sqlite3'; path.parent.mkdir(parents=True)
            db = sqlite3.connect(path)
            self.addCleanup(db.close)
            db.execute('CREATE TABLE automation_slots(state TEXT,updated_at TEXT)')
            db.execute("INSERT INTO automation_slots VALUES ('skipped','2026-10-21T10:00:00+09:00')"); db.commit()
            doc = {'enabled': True, 'continuousMode': True, 'checkedAt': self.now.isoformat(),
                   'lastRunAt': '2026-10-21T10:00:00+09:00', 'intervalMinutes': 20,
                   'nextEligibleAt': '2026-10-21T10:20:00+09:00'}
            self.assertEqual(h.kin_activity(doc, self.now)['status'], 'overdue')
            self.assertEqual(h.kin_activity(doc, self.now)['expectedAt'], '2026-10-21T11:15:00+09:00')
            db.execute("UPDATE automation_slots SET updated_at='2026-10-21T11:30:00+09:00'"); db.commit()
            self.assertEqual(h.kin_activity(doc, self.now)['status'], 'recent')
            self.assertEqual(h.kin_activity(doc, self.now)['lastOutcome'], 'skipped')
            held = dict(doc, cadenceState='daily_limit_or_account_unavailable', globalRemainingRuns=0, nextEligibleAt='2026-10-22T00:00:00+09:00')
            self.assertEqual(h.kin_activity(held, self.now)['status'], 'held')
            self.assertEqual(h.kin_activity(dict(held, globalRemainingRuns=5), self.now)['status'], 'blocked')
            self.assertEqual(h.kin_activity(dict(held, cadenceState='accounts_suspended'), self.now)['status'], 'blocked')
            db.execute("UPDATE automation_slots SET updated_at='2026-10-20T11:30:00+09:00'"); db.commit()
            old = dict(held, checkedAt='2026-10-20T12:00:00+09:00', lastRunAt='2026-10-20T10:00:00+09:00')
            self.assertEqual(h.kin_activity(old, self.now)['status'], 'overdue')
            db.close()

    def test_kin_missing_evidence_is_unknown_and_active_run_stalls(self):
        import sqlite3
        with tempfile.TemporaryDirectory() as td, patch.object(h, 'ROOT', Path(td)):
            doc = {'enabled': True, 'checkedAt': self.now.isoformat(), 'activeRunId': 'actual',
                   'activeStartedAt': '2026-10-21T10:00:00+09:00'}
            self.assertEqual(h.kin_activity(doc, self.now)['status'], 'unknown')
            path = Path(td)/'server/data/kin.sqlite3'; path.parent.mkdir(parents=True)
            db = sqlite3.connect(path); db.execute('CREATE TABLE automation_slots(state TEXT,updated_at TEXT)'); db.commit(); db.close()
            self.assertEqual(h.kin_activity(doc, self.now)['status'], 'stalled')

    def test_jev_receives_only_bounded_fields(self):
        from common import jev
        with patch.object(jev, '_ask', return_value={'status': 'api_error'}) as ask:
            result = jev.classify_incident({'status': 'stale', 'source': {'path': 'private'},
                       'counts': {'failed': 1, 'secret': 'private'}, 'quota': {'missing': 2, 'missingSlots': ['private']}})
            self.assertNotIn('private', json.dumps(ask.call_args.args))
            self.assertEqual(result['priority'], 'unclassified')


class KnownCandidateTests(unittest.TestCase):
    def test_actual_typed_gate_excludes_quality_submission_and_consumed_budget(self):
        from cf_posting import pipeline_runner as cf
        from common import repair_workflow as repair
        with tempfile.TemporaryDirectory() as td, patch.object(m,'STATE',Path(td)/'state.json'), patch.object(cf,'SCHEDULE_JSON',Path(td)/'schedule.json'), patch.object(repair,'ROOT',Path(td)/'repair'):
            seed='editorial title that is much longer than a measurable keyword'
            item={'domain':'tripmarvel.com','status':'failed','currentStage':1,'growthKeyword':{'keyword':seed},'lastError':'No eligible demand candidate: '+seed+' unknown=HTTP 400'}
            def write(row): cf.SCHEDULE_JSON.write_text(json.dumps({'date':h.today_kst_str(),'items':[row]}))
            write(item); candidates=m.known_cf_candidates({'id':'cf_blog'})
            self.assertEqual(len(candidates),1)
            proof=Path(candidates[0]['evidencePath']).read_bytes()
            self.assertEqual(m.hashlib.sha256(proof).hexdigest(),candidates[0]['evidenceSha256'])
            write(dict(item,status='review_required'));self.assertEqual(m.known_cf_candidates({'id':'cf_blog'}),[])
            write(dict(item,submissionStarted=True));self.assertEqual(m.known_cf_candidates({'id':'cf_blog'}),[])
            write(item);repair.ROOT.mkdir();task=candidates[0]['taskId'];fp=m.hashlib.sha256((task+'|editorial_seed_pinned_as_keyword').encode()).hexdigest();(repair.ROOT/(fp+'.resume.json')).write_text('{}')
            self.assertEqual(m.known_cf_candidates({'id':'cf_blog'}),[])

class ReasonDisplayTests(unittest.TestCase):
    def test_actual_instruction_preserved_with_returned_model(self):
        with tempfile.TemporaryDirectory() as td, patch('common.crew_chat_bridge.emit_work_event',return_value='event') as emit:
            row={'taskId':'incident:test','triage':{'reason':'@퍼블리, 현재 상태를 읽고 미확인 항목을 보고해 주세요.'},'route':{'events':[{'state':'returned','actualModel':'actual-model'}]}}
            m.emit_triage_reason(row,Path(td)/'incident.json',{'agent':'publi'})
            self.assertEqual(emit.call_args.kwargs['output_kind'],row['triage']['reason'])
            self.assertEqual(emit.call_args.kwargs['message_kind'],'staff_reply')
            self.assertEqual(emit.call_args.kwargs['model'],'actual-model')
            self.assertEqual(row['instructionEventId'],'event')

    def test_invalid_instruction_retained_without_event(self):
        with tempfile.TemporaryDirectory() as td, patch('common.crew_chat_bridge.emit_work_event') as emit:
            row={'triage':{'reason':'private /home/user/file.'}}
            m.emit_triage_reason(row,Path(td)/'incident.json',None)
            emit.assert_not_called()
            self.assertEqual(row['triage']['reason'],'private /home/user/file.')
            self.assertEqual(row['triageDisplay'],'withheld')

    def test_exact_model_reason_kept_without_rewriting(self):
        reason='현재 실패 상태가 남아 있습니다. 퍼블리가 원장과 검수 근거를 확인해야 합니다.'
        self.assertEqual(m.public_reason(reason),reason)

    def test_overlength_sensitive_or_incomplete_is_not_truncated(self):
        for reason in ('가'*160+'.','password: private.','https://example.com 확인.','C:/private/key 확인.','<script>실행</script>.','아직 필요한 확인은','두 줄\n문장입니다.'):
            with self.subTest(reason=reason),self.assertRaises(ValueError): m.public_reason(reason)

class FeedbackTests(unittest.TestCase):
    def setUp(self):
        from common import repair_workflow
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        guard=patch.object(repair_workflow,'ROOT',Path(temporary.name));guard.start();self.addCleanup(guard.stop)
        prepare=patch.object(repair_workflow,'prepare_project_recovery',return_value={'status':'ready'})
        self.prepare=prepare.start();self.addCleanup(prepare.stop)

    def test_unresolved_host_cannot_be_model_promoted_and_replayed(self):
        from server import agent_tools
        with tempfile.TemporaryDirectory() as td, patch.object(m, 'INCIDENTS', Path(td)/'incidents'), patch.object(agent_tools, 'STAFF_REQUEST_DIR', Path(td)/'staff'):
            m.INCIDENTS.mkdir(); agent_tools.STAFF_REQUEST_DIR.mkdir()
            request_id='actual-request'; task='staff:abc'
            result={'status':'completed','taskId':task,'requestId':request_id,'results':[]}
            (agent_tools.STAFF_REQUEST_DIR/(m.hashlib.sha256(request_id.encode()).hexdigest()+'.json')).write_text(json.dumps(result))
            path=m.INCIDENTS/'a.json';path.write_text(json.dumps({'status':'dispatched','observation':{'id':'cf_blog'},'dispatch':{'taskId':task,'requestId':request_id}}))
            def judge(*args, **kwargs):
                kwargs['observer']('codex','configured','returned',actual_model='configured')
                return {'decision':'observed_resolved','reason':'unsupported'}
            with patch.object(m,'observed_projects',return_value=[{'id':'cf_blog','status':'attention','source':{'fresh':True}}]), patch('common.llm_settings.get_agent_brain',return_value={'provider':'codex','model':'configured'}), patch('common.llm_client.generate_json',side_effect=judge) as model:
                self.assertTrue(m.process_project_feedback_once())
                self.assertEqual(json.loads(path.read_text(encoding='utf-8'))['status'],'feedback_hold')
                self.assertFalse(m.process_project_feedback_once())
                self.assertEqual(model.call_count,1)

    def test_held_staff_result_gets_neutral_feedback_once(self):
        from server import agent_tools
        with tempfile.TemporaryDirectory() as td, patch.object(m, 'INCIDENTS', Path(td)/'incidents'), patch.object(agent_tools, 'STAFF_REQUEST_DIR', Path(td)/'staff'):
            m.INCIDENTS.mkdir(); agent_tools.STAFF_REQUEST_DIR.mkdir()
            request_id='actual-request'; task='staff:abc'
            result={'status':'held','taskId':task,'requestId':request_id,'results':[]}
            (agent_tools.STAFF_REQUEST_DIR/(m.hashlib.sha256(request_id.encode()).hexdigest()+'.json')).write_text(json.dumps(result))
            path=m.INCIDENTS/'a.json';path.write_text(json.dumps({'status':'dispatched','observation':{'id':'cf_blog'},'dispatch':{'taskId':task,'requestId':request_id}}))
            def judge(*args, **kwargs):
                kwargs['observer']('codex','configured','returned',actual_model='configured')
                return {'decision':'needs_attention','reason':'수리는 보류 상태입니다. 패치는 부족한 검증 근거를 확인해야 합니다.'}
            with patch.object(m,'observed_projects',return_value=[{'id':'cf_blog','status':'attention','source':{'fresh':True}}]), patch('common.llm_settings.get_agent_brain',return_value={'provider':'codex','model':'configured'}), patch('common.llm_client.generate_json',side_effect=judge) as model, patch('common.crew_chat_bridge.emit_work_event',return_value='event') as emit:
                self.assertTrue(m.process_project_feedback_once())
                self.assertEqual(json.loads(path.read_text(encoding='utf-8'))['status'],'needs_attention')
                self.assertFalse(m.process_project_feedback_once())
                self.assertEqual(model.call_count,1)
                self.assertEqual(emit.call_args.kwargs['output_kind'], '수리는 보류 상태입니다. 패치는 부족한 검증 근거를 확인해야 합니다.')
                self.assertEqual(emit.call_args.kwargs['message_kind'], 'staff_reply')
                self.prepare.assert_called_once()
                self.assertEqual(json.loads(path.read_text(encoding='utf-8'))['feedback']['reason'], emit.call_args.kwargs['output_kind'])

# Plain unittest runs must never publish fixture events or diagnose them in production.
def setUpModule():
    import tempfile
    from pathlib import Path
    from unittest.mock import patch
    from common import repair_workflow
    global _isolated_crew_temp, _isolated_crew_patches
    _isolated_crew_temp = tempfile.TemporaryDirectory()
    root = Path(_isolated_crew_temp.name)
    _isolated_crew_patches = [
        patch('common.crew_chat_bridge._deliver', return_value=True),
        patch('common.crew_chat_bridge.OUTBOX_DIR', root / 'outbox'),
        patch.object(repair_workflow, 'ROOT', root / 'repairs'),
    ]
    for guard in _isolated_crew_patches:
        guard.start()


def tearDownModule():
    for guard in reversed(_isolated_crew_patches):
        guard.stop()
    _isolated_crew_temp.cleanup()


if __name__ == '__main__':
    unittest.main()
