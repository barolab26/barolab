import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from common import repair_workflow as repair


class RepairWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.path=self.root/'proof.json'
        self.proof={'failureType':repair.KNOWN_FAILURE,'taskId':'job1','submissionStarted':False,'status':'failed'}
        self.path.write_text(json.dumps(self.proof));self.sha=hashlib.sha256(self.path.read_bytes()).hexdigest()
        evidence=self.root/'validated.json';evidence.write_text(json.dumps({'taskId':'job1','testsPassed':True,'repairRevision':'fixed-source-sha'}))
        self.handler=Mock(return_value={'status':'validated','testsPassed':True,'repairRevision':'fixed-source-sha',
            'evidencePath':str(evidence),'evidenceSha256':hashlib.sha256(evidence.read_bytes()).hexdigest()})
        self.resume=Mock(return_value={'status':'held'})
        self.verdict={**{key:True for key in ('supported','gatesPreserved','sameTask','safeToResume')},'contract':'guarded-attempt-v1','reason':'Host evidence supports this bounded repair','missingEvidence':[]}
        def generate(prompt,**kwargs):
            self.last_prompt=prompt
            kwargs['observer'](kwargs['provider'],kwargs['model_override'],'calling')
            kwargs['observer'](kwargs['provider'],kwargs['model_override'],'returned',actual_model='actual-configured-model')
            return self.verdict
        self.patches=[patch.object(repair,'ROOT',self.root/'ledger'),patch('common.crew_chat_bridge.emit_work_event',return_value='request-event'),
                      patch('common.llm_client.generate_json',side_effect=generate),
                      patch('common.llm_settings.get_agent_brain',return_value={'provider':'codex','model':'configured-jarvis-model'})]
        for p in self.patches:p.start()
    def tearDown(self):
        for p in reversed(self.patches):p.stop()
        self.temp.cleanup()
    def run_job(self):
        return repair.run_known_repair('job1',self.path,self.sha,handler=self.handler,resume=self.resume)
    def test_review_then_single_resume_without_attempt_reset(self):
        result=self.run_job();self.assertEqual(result['status'],'resume_held')
        args=self.resume.call_args.args
        permit=Path(args[2]['resumePermitPath'])
        self.assertEqual(hashlib.sha256(permit.read_bytes()).hexdigest(),args[2]['resumePermitSha256'])
        self.run_job();self.handler.assert_called_once();self.resume.assert_called_once()
    def test_actual_stage_evidence_is_required_for_verified_resume(self):
        artifact=self.root/'stage.json';artifact.write_text('{"status":"accepted"}')
        evidence=self.root/'resume.json'
        evidence.write_text(json.dumps({'taskId':'job1','failureType':repair.KNOWN_FAILURE,'failureStagePassed':True,
            'sourceArtifacts':[{'path':str(artifact),'sha256':hashlib.sha256(artifact.read_bytes()).hexdigest()}]}))
        self.resume.return_value={'returncode':0,'evidencePath':str(evidence),'evidenceSha256':hashlib.sha256(evidence.read_bytes()).hexdigest()}
        self.assertEqual(self.run_job()['status'],'resume_verified')

    def test_material_review_continuation_preserves_rejection_and_shared_budget(self):
        self.verdict['supported']=False
        old=self.run_job()
        old_path=repair.ROOT/(old['fingerprint']+'.json');old_bytes=old_path.read_bytes()
        evidence=Path(self.handler.return_value['evidencePath'])
        actual=json.loads(evidence.read_text());actual['newEvidence']='Host integration regression and callsite proof'
        evidence.write_text(json.dumps(actual));new_sha=hashlib.sha256(evidence.read_bytes()).hexdigest()
        self.handler.return_value['evidenceSha256']=new_sha
        approval=self.root/'approval.json'
        value={'taskId':'job1','approved':True,'reviewRevision':'review-v2',
               'oldReviewSha256':hashlib.sha256(old_bytes).hexdigest(),'newRepairEvidenceSha256':new_sha}
        approval.write_text(json.dumps(value));approval_sha=hashlib.sha256(approval.read_bytes()).hexdigest()
        self.verdict['supported']=True
        result=repair.run_known_repair('job1',self.path,self.sha,handler=self.handler,resume=self.resume,
             review_approval_path=approval,review_approval_sha256=approval_sha)
        self.assertEqual(result['status'],'resume_held')
        self.assertEqual(old_path.read_bytes(),old_bytes)
        self.assertNotEqual(result['fingerprint'],old['fingerprint'])
        repair.run_known_repair('job1',self.path,self.sha,handler=self.handler,resume=self.resume,
             review_approval_path=approval,review_approval_sha256=approval_sha)
        self.resume.assert_called_once()

    def test_explicit_v3_binds_host_query_and_preserves_v2(self):
        base=repair._sha(('job1|'+repair.KNOWN_FAILURE).encode())
        v2=repair._sha((base+'|review-v2').encode())
        repair.ROOT.mkdir(parents=True)
        old_path=repair.ROOT/(v2+'.json')
        old_path.write_text(json.dumps({'taskId':'job1','status':'review_rejected','resumeAttempted':False,
            'reviewRevision':'review-v2','failureEvidenceSha256':self.sha,'repairEvidenceSha256':'old-evidence'}))
        old_bytes=old_path.read_bytes()
        evidence=Path(self.handler.return_value['evidencePath']);actual=json.loads(evidence.read_text())
        actual['approvedQuery']='수목원 예약'
        for field in ('queryEvidence','intentEvidence'):
            artifact=self.root/(field+'.json');artifact.write_text('{"hostVerified":true}')
            actual[field+'Path']=str(artifact);actual[field+'Sha256']=repair._sha(artifact.read_bytes())
        evidence.write_text(json.dumps(actual));new_sha=repair._sha(evidence.read_bytes())
        self.handler.return_value['evidenceSha256']=new_sha
        approval=self.root/'approval-v3.json';approval.write_text(json.dumps({'taskId':'job1','approved':True,
            'reviewRevision':'review-v3','oldReviewSha256':repair._sha(old_bytes),'newRepairEvidenceSha256':new_sha}))
        result=repair.run_known_repair('job1',self.path,self.sha,handler=self.handler,resume=self.resume,
            review_approval_path=approval,review_approval_sha256=repair._sha(approval.read_bytes()))
        self.assertEqual(result['status'],'resume_held')
        self.assertEqual(old_path.read_bytes(),old_bytes)
        self.assertEqual(result['previousFingerprint'],v2)
        permit=json.loads(Path(self.resume.call_args.args[2]['resumePermitPath']).read_text(encoding='utf-8'))
        self.assertEqual(permit['reviewedInputs']['approvedQuery'],'수목원 예약')
        self.assertIn('verifiedQueryIntentEvidence',self.last_prompt)
        self.assertIn('hostVerified',self.last_prompt)
        self.assertEqual(permit['reviewedInputs']['intentEvidenceSha256'],actual['intentEvidenceSha256'])
        self.assertEqual(result['fingerprint'],repair._sha((base+'|review-v3').encode()))

    def test_actual_generic_diagnosis_runs_once_without_repair_or_resume(self):
        event={'eventId':'failure1','taskId':'other-task','who':'cf-pipeline','phase':'failed','stage':'model','evidenceId':'sha'}
        repair.record_failed_event(event)
        def diagnose(prompt,**kwargs):
            kwargs['observer']('codex','configured-jarvis-model','returned',actual_model='actual-model')
            if kwargs.get('crew_actor')=='jarvis':
                return {'diagnosisSupported':True,'requiredEvidenceAppropriate':True,'handlerSupported':False,'reason':'More host evidence is needed'}
            return {'classification':'needs_evidence','reason':'No exception or source was supplied',
                    'requiredEvidence':['Host exception class and bounded stack location']}
        with patch('common.llm_client.generate_json',side_effect=diagnose) as model:
            self.assertTrue(repair.process_repair_diagnosis_once())
            self.assertFalse(repair.process_repair_diagnosis_once())
            self.assertEqual(model.call_count,2)
        rows=[json.loads(p.read_text(encoding='utf-8')) for p in repair.ROOT.glob('*.json')]
        self.assertEqual(rows[0]['status'],'diagnosed_needs_evidence')
        self.assertEqual(rows[0]['diagnosisRoute']['events'][0]['actualModel'],'actual-model')
        self.resume.assert_not_called();self.handler.assert_not_called()

    def test_v4_cannot_skip_exact_rejected_v3(self):
        base=repair._sha(('job1|'+repair.KNOWN_FAILURE).encode())
        v3=repair._sha((base+'|review-v3').encode())
        repair.ROOT.mkdir(parents=True)
        old=repair.ROOT/(v3+'.json')
        old.write_text(json.dumps({'taskId':'job1','status':'review_rejected','resumeAttempted':False,
            'reviewRevision':'review-v2','failureEvidenceSha256':self.sha,'repairEvidenceSha256':'old'}))
        approval=self.root/'v4.json';approval.write_text(json.dumps({'taskId':'job1','approved':True,
            'reviewRevision':'review-v4','oldReviewSha256':repair._sha(old.read_bytes()),'newRepairEvidenceSha256':'new'}))
        with self.assertRaises(ValueError):
            repair.run_known_repair('job1',self.path,self.sha,handler=self.handler,resume=self.resume,
                review_approval_path=approval,review_approval_sha256=repair._sha(approval.read_bytes()))
        self.handler.assert_not_called();self.resume.assert_not_called()

    def test_diagnosis_request_id_is_persisted_for_actual_reply_parent(self):
        event={'eventId':'original-failure','taskId':'request-task','who':'cf-pipeline','phase':'failed','stage':'model','evidenceId':'sha'}
        row=repair.record_failed_event(event)
        self.assertEqual(row['diagnosisRequestId'],'request-event')
        stored=json.loads((repair.ROOT/(row['fingerprint']+'.json')).read_text())
        self.assertEqual(stored['diagnosisRequestId'],'request-event')
        self.assertEqual(stored['sourceEventId'],'original-failure')

    def test_stale_diagnosis_is_held_without_automatic_retry(self):
        repair.ROOT.mkdir(parents=True)
        path=repair.ROOT/'stale.json';path.write_text(json.dumps({'status':'diagnosing','diagnosisStartedAt':0}))
        with patch('common.llm_client.generate_json') as model:
            self.assertFalse(repair.process_repair_diagnosis_once())
            model.assert_not_called()
        self.assertEqual(json.loads(path.read_text())['status'],'diagnosis_hold')

    def test_same_evidence_review_continuation_is_rejected(self):
        self.verdict['supported']=False;old=self.run_job()
        old_path=repair.ROOT/(old['fingerprint']+'.json')
        approval=self.root/'approval.json'
        approval.write_text(json.dumps({'taskId':'job1','approved':True,'reviewRevision':'review-v2',
            'oldReviewSha256':hashlib.sha256(old_path.read_bytes()).hexdigest(),
            'newRepairEvidenceSha256':old['repairEvidenceSha256']}))
        with self.assertRaises(ValueError):
            repair.run_known_repair('job1',self.path,self.sha,handler=self.handler,resume=self.resume,
                review_approval_path=approval,review_approval_sha256=hashlib.sha256(approval.read_bytes()).hexdigest())
        self.resume.assert_not_called()

    def test_missing_review_reason_holds_without_resume(self):
        del self.verdict['reason']
        self.assertEqual(self.run_job()['status'],'hold')
        self.resume.assert_not_called()

    def test_jarvis_configured_route_and_actual_model_are_recorded(self):
        result=self.run_job()
        route=result['reviewRoute']
        self.assertEqual(route['configuredProvider'],'codex')
        self.assertEqual(route['configuredModel'],'configured-jarvis-model')
        self.assertEqual(route['events'][-1]['actualModel'],'actual-configured-model')
        self.assertEqual(route['events'][-1]['provider'],'codex')

    def test_prohibited_jarvis_route_never_calls_model_or_resume(self):
        with patch('common.llm_settings.get_agent_brain',return_value={'provider':'freellmapi','model':'any'}), patch('common.llm_client.generate_json') as model:
            result=self.run_job()
        self.assertEqual(result['status'],'hold')
        model.assert_not_called();self.resume.assert_not_called()

    def test_independent_reject_never_resumes(self):
        self.verdict['safeToResume']=False
        self.assertEqual(self.run_job()['status'],'review_rejected');self.resume.assert_not_called()
    def test_unknown_submission_and_changed_evidence_rejected(self):
        self.proof['submissionStarted']=True;self.path.write_text(json.dumps(self.proof))
        self.sha=hashlib.sha256(self.path.read_bytes()).hexdigest()
        with self.assertRaises(ValueError):self.run_job()
        self.handler.assert_not_called()
    def test_crash_after_resume_is_held_without_second_attempt(self):
        self.resume.side_effect=RuntimeError('private')
        result=self.run_job();self.assertEqual(result['status'],'hold');self.assertTrue(result['resumeAttempted'])
        self.run_job();self.resume.assert_called_once()
    def test_generic_intake_deduplicates_without_handler_or_recursive_repair(self):
        event={'eventId':'event1','taskId':'model1','who':'common-runner','phase':'failed','stage':'model','evidenceId':'proof'}
        first=repair.record_failed_event(event);second=repair.record_failed_event(event)
        self.assertEqual(first,second);self.assertEqual(first['status'],'needs_diagnosis')
        self.assertIsNotNone(repair.record_failed_event({**event,'who':'patch','taskId':'patch-own-task'}))
        token=repair._active.set(True)
        try:self.assertIsNone(repair.record_failed_event(event))
        finally:repair._active.reset(token)
        self.handler.assert_not_called()

if __name__=='__main__':unittest.main()
