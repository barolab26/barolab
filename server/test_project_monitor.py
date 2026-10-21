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
